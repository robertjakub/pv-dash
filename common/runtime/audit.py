"""Append-only audit trail shared by the tools and their control CLIs: one
line per event — who, when, what, result. Every line carries the AUDIT level
between the stamp and the writer prefix ('<stamp> AUDIT <PREFIX> <EVENT> ...')
so the trail filters cleanly out of a mixed log. ping/pong keepalives are
never logged. The file is opened append-only and flushed per event, so a
crash keeps everything up to the last command.

Every entry carries a short chained hash right after the event name (12 hex
chars, no decoration): `<stamp> AUDIT <PREFIX> <EVENT> <hash> [detail]` —
h = sha256(prev | stamp | prefix | event + detail) truncated. The chain is
per writer prefix (CACHE, INV, CLI, CTL each chain their own lines), so
several writers can interleave in one file and every chain stays
verifiable on its own — scripts/audit_verify.py walks a file (and its
rotated backups, oldest first), recomputes each prefix's chain and names the
line where it breaks. The chain is tamper-EVIDENT: any edited, reordered or
deleted middle entry breaks it; trailing deletion and a full rechain by
someone holding the algorithm are outside its reach. The stronger answers
are BUILT IN as the trail's three tiers (docs/AUDIT.md): the local chain,
the local mirror (audit/forward = syslog — journald's sealed copy on the
same box) and the off-box copy (audit/forward = udp:// or tcp:// — a line
that left the box before an attacker arrived cannot be touched from it).

The default location is the tool's XDG state directory
(~/.local/state/<app>/audit.log), NOT the current directory: a packaged
install (nix store, container) has a read-only working directory. Rotation
is gated: size-based (--audit-max-mb, default 10 MB, 0 = off) keeps N
backups; time-based (--audit-daily) rotates at UTC midnight. A path of "-"
sends the trail to stdout — what docker logs / journald capture (stdout,
not stderr: the audit is data, not an error, and it stays in the single
ordered stream the service manager captures). When the sink is stdout,
rotation is disabled by definition. The rotation depth is configurable:
--audit-files N (the default 3). A path of "none" turns the local file
off: with a forward spelled that is the remote-only mode (the collector
is the sole holder — no file, no XDG directory, the chain reseeds at
GENESIS every run); without one it folds to the audit being disabled
(the same state --no-audit-log spells). The forwarding is opt-in:
--audit-forward mirrors every finished line (the chain hash included) —
`none` (off), `syslog` (the local socket auto-scan), `syslog:/path` (an
explicit local socket), `udp://host[:514]` (RFC5426 datagrams,
best-effort) or `tcp://host[:514]` (RFC6587 octet-count framing). The
remote envelopes ride --audit-forward-format: RFC5424 (the default) or
CEF — the local forms always keep the verbatim stdlib send. A send
failure stops the mirroring with one stderr note and the NEXT event
re-arms (a success notes once with the dropped count) — no threads, no
buffers, the sink keeps the chain either way."""
import hashlib
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time

from common.runtime.version import VERSION

HASH_LEN = 12                                   # hex chars per entry hash
GENESIS = '0' * HASH_LEN                        # the chain's first prev

# The audit-forward target grammar (one value, one validator — parse_forward):
# the one-liner every refusal speaks (the wire's audit/forward, the argparse
# gates, the nix module's check).
AUDIT_FORWARD_GRAMMAR = 'none, syslog, syslog:/path, udp://host[:port] or tcp://host[:port]'
# The local syslog unix sockets tried in order (audit/forward = syslog) —
# journald's /dev/log (the systemd compat socket, Linux), the real journal
# syslog socket beside it, the macOS one. The first that exists wins; none
# = the spelling refuses to start (a promised forward that cannot exist is
# a misprint, not a posture).
SYSLOG_SOCKETS = ('/dev/log', '/run/systemd/journal/syslog', '/var/run/syslog')
# The remote envelopes (audit-forward-format; the local forms ignore the
# knob — journald must not eat RFC5424 or CEF headers).
AUDIT_FORWARD_FORMATS = ('rfc5424', 'cef')
# The remote connect/send timeout (the lazy re-arm's cost ceiling: one
# audit event stalls at most this long while a collector is down).
FORWARD_TIMEOUT = 2.0
# The envelope severity table: a line ending '-> ok' (and the verdict-less
# START/SHUTDOWN events) ride 4; '-> err' (a refused/failed command) rides 7.
FORWARD_SEV_OK = 4
FORWARD_SEV_ERR = 7


class ForwardSoftError(Exception):
    """A remote forward target that does not resolve or refuses to connect
    at bind — soft by ruling (boot ordering never keeps the daemon from
    serving Modbus because a collector woke up late): the bins warn and
    start, the lazy re-arm carries the forward from the first event."""


def parse_forward(value):
    """One audit-forward value → the target tuple: None (off — None, ''
    and 'none' all fold), ('syslog', None) (the auto-scan), ('syslog',
    path) (an explicit local socket), ('udp', host, port) / ('tcp', host,
    port) (remote). Grammar errors raise ValueError with the one-liner
    (the unknown schemes — a later TLS among them — get the same
    refusal). The host is anything getaddrinfo takes (IPv6 literals in
    brackets included), the port 1-65535, the default 514."""
    if value in (None, '', 'none'):
        return None
    if value == 'syslog':
        return ('syslog', None)
    if value.startswith('syslog:'):
        path = value[len('syslog:'):]
        if not path.startswith('/') or ' ' in path:
            raise ValueError('audit-forward must be %s' % AUDIT_FORWARD_GRAMMAR)
        return ('syslog', path)
    scheme, sep, rest = value.partition('://')
    if not sep or scheme not in ('udp', 'tcp'):
        raise ValueError('audit-forward must be %s' % AUDIT_FORWARD_GRAMMAR)
    host, port = _parse_host_port(rest)
    return (scheme, host, port)


def _parse_host_port(rest):
    """The remote form's authority: `host`, `host:port` or `[v6]:port` —
    the empty host, the empty port, a bad port and spaces all refuse."""
    if not rest or ' ' in rest:
        raise ValueError('audit-forward must be %s' % AUDIT_FORWARD_GRAMMAR)
    if rest.startswith('['):
        host, sep, tail = rest[1:].partition(']')
        if not sep or tail == ':' or (tail and not tail.startswith(':')):
            raise ValueError('audit-forward must be %s' % AUDIT_FORWARD_GRAMMAR)
        port_s = tail[1:]
    else:
        host, sep, port_s = rest.rpartition(':')
        if not sep:
            host, port_s = rest, ''
        elif not port_s:
            raise ValueError('audit-forward must be %s' % AUDIT_FORWARD_GRAMMAR)
    if not host:
        raise ValueError('audit-forward must be %s' % AUDIT_FORWARD_GRAMMAR)
    port = 514
    if port_s:
        if not all(c in '0123456789' for c in port_s) or not 1 <= int(port_s) <= 65535:
            raise ValueError('audit-forward must be %s' % AUDIT_FORWARD_GRAMMAR)
        port = int(port_s)
    return host, port


class FailLoudSysLogHandler(logging.handlers.SysLogHandler):
    """The one behavior the base omits: a send failure SURFACES (the base's
    handleError swallows it into a stderr traceback per event and silently
    keeps the handler alive). The audit mirror's fail-stop needs the
    exception — handleError is called from emit's except block, so a bare
    re-raise propagates the original failure to the caller."""

    def handleError(self, record):
        raise   # the active exception (emit's) — the caller decides


def open_syslog_handler(path):
    """The local mirror's handler on one unix syslog socket: the DGRAM
    connect() probe picks the socket type (journald's sockets take
    datagrams, some syslogs only take streams — a refused probe falls
    back to a stream)."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        probe.connect(path)
        socktype = socket.SOCK_DGRAM
    except OSError:
        socktype = socket.SOCK_STREAM
    finally:
        probe.close()
    return FailLoudSysLogHandler(address=path, facility=logging.handlers.SysLogHandler.LOG_DAEMON,
                                 socktype=socktype)


def sd_escape(text):
    """The RFC5424 PARAM-VALUE escaping: `\\`, `"` and `]` carry a
    backslash (the prefix and the chain hash are safe by construction —
    the escape keeps the envelope honest anyway)."""
    return text.replace('\\', '\\\\').replace('"', '\\"').replace(']', '\\]')


class RemoteForwardHandler(logging.Handler):
    """The remote mirror's shared envelope layer (udp://, tcp://): one
    finished audit line per send, wrapped RFC5424 or CEF. The line's own
    pieces (the prefix, the event, the chain hash) ride the SD-ELEMENT /
    the CEF extension as extracted fields, so a scheduled search at the
    collector can run the chain-verify logic on the off-box copy and alert
    on a chain break — and the MSG carries the exact native line, so the
    verification works identically under both formats."""

    def __init__(self, app, fmt):
        super().__init__()
        self.app = app          # APP-NAME / the CEF device product field
        self.fmt = fmt          # 'rfc5424' | 'cef'
        self._host = socket.gethostname() or 'unknown'

    def emit(self, record):
        self.send(self.envelope(record.getMessage()))

    def send(self, payload):
        raise NotImplementedError

    @staticmethod
    def severity(line):
        """The severity table: `-> err` = 7, everything else = 4."""
        return FORWARD_SEV_ERR if ' -> err' in line else FORWARD_SEV_OK

    def envelope(self, line):
        """The wire payload for one native audit line: the RFC5424 envelope
        `<PRI>1 <RFC3339-ms> <hostname> <app> <pid> <EVENT> [pvDash@1
        prefix=... chain=...] <line>` or the CEF additive wrapping
        (`msg=` carries the exact native line, so chain verification reads
        the same text under both)."""
        parts = line.split(' ')
        event, chain = parts[3], parts[4]
        if self.fmt == 'cef':
            msg = line.replace('\\', '\\\\').replace('=', '\\=')
            return ('CEF:0|pv-dash|%s|%s|%s|%s|%d| rt=%d cs1Label=AuditChain cs1=%s '
                    'cs2Label=AuditPrefix cs2=%s msg=%s'
                    % (self.app, VERSION, event, event, self.severity(line),
                       int(time.time() * 1000), chain, sd_escape(parts[2]), msg)).encode('utf-8')
        now = time.time()
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now)) + '.%03dZ' % (int(now * 1000) % 1000)
        pri = logging.handlers.SysLogHandler.LOG_DAEMON * 8 + self.severity(line)
        sd = '[pvDash@1 prefix="%s" chain="%s"]' % (sd_escape(parts[2]), sd_escape(chain))
        return ('<%d>1 %s %s %s %d %s %s %s'
                % (pri, stamp, self._host, self.app, os.getpid(), event, sd, line)).encode('utf-8')


class UdpForwardHandler(RemoteForwardHandler):
    """RFC5426: one datagram per line, best-effort — sendto does not fail
    on a down collector, so the re-arm never triggers; the drops show as
    the per-prefix chain-hash gaps at the collector (the source stays
    silent). The target resolves at bind (a miss is soft) and again on
    every re-arm."""

    def __init__(self, app, host, port, fmt):
        RemoteForwardHandler.__init__(self, app, fmt)
        try:
            info = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM)
            self._family, self._sockaddr = info[0][0], info[0][4]
        except (OSError, IndexError) as e:
            raise ForwardSoftError('the forward target %s does not resolve: %s' % (host, e))
        self._sock = socket.socket(self._family, socket.SOCK_DGRAM)

    def send(self, payload):
        self._sock.sendto(payload, self._sockaddr)


class TcpForwardHandler(RemoteForwardHandler):
    """RFC6587: one segment per line, the octet-count framing (`<len> `).
    The connect at bind/re-arm and every send carry the short timeout; a
    failure raises (fail-loud) and the caller's lazy re-arm re-opens on
    the next event."""

    def __init__(self, app, host, port, fmt):
        RemoteForwardHandler.__init__(self, app, fmt)
        self._addr = (host, port)
        self._sock = self._connect()

    def _connect(self):
        try:
            s = socket.create_connection(self._addr, timeout=FORWARD_TIMEOUT)
            s.settimeout(FORWARD_TIMEOUT)
        except OSError as e:
            raise ForwardSoftError('the forward target %s:%d refuses: %s' % (self._addr[0], self._addr[1], e))
        return s

    def send(self, payload):
        self._sock.sendall(b'%d %s' % (len(payload), payload))


def syslog_socket():
    """The local syslog unix socket to forward to (the first candidate that
    exists — see SYSLOG_SOCKETS), None when the host has none."""
    for cand in SYSLOG_SOCKETS:
        if os.path.exists(cand):
            return cand
    return None

# The rotation bounds (the one home — the registries' audit-files/audit-max-mb
# rows and the tools' startup gates repeat them, scripts/check_options.py
# cross-checks that they never drift): the rotated backups kept and the size
# that triggers a rotation in MB (0 = no size rotation).
AUDIT_FILES_MIN = 1
AUDIT_FILES_MAX = 100
AUDIT_MAX_MB_MIN = 0
AUDIT_MAX_MB_MAX = 1048576


def entry_hash(prev, stamp, prefix, body):
    """The chained entry hash: sha256(prev | stamp | prefix | text), hex-truncated.
    Shared by the writer and scripts/audit_verify.py — one implementation."""
    material = '%s|%s|%s|%s' % (prev, stamp, prefix, body)
    return hashlib.sha256(material.encode('utf-8')).hexdigest()[:HASH_LEN]


def parse_entry_hash(line):
    """The chained hash of one audit line (None when absent/malformed): the
    5th space-separated token, right after the event name, exactly
    HASH_LEN hex chars — `<stamp> AUDIT <PREFIX> <EVENT> <hash> [detail...]`."""
    parts = line.rstrip().split(' ')
    if len(parts) < 5 or parts[1] != 'AUDIT':
        return None
    h = parts[4]
    if len(h) != HASH_LEN or not all(c in '0123456789abcdef' for c in h):
        return None
    return h


def entry_body(line):
    """The hashed text of one audit line: `<EVENT> [detail...]` — the hash
    token skipped, everything after it verbatim."""
    parts = line.rstrip().split(' ')
    return ' '.join(parts[3:4] + parts[5:])


def tail_hash(path, prefix):
    """The last `h=` this prefix left in an existing file (or its rotated
    backups), so a restarted writer chains seamlessly from its own previous
    entries. Reads each file's trailing 64 KB, live file first; GENESIS when
    nothing is found."""
    candidates = [path] + ['%s.%d' % (path, i) for i in range(1, 17)]
    for p in candidates:
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        try:
            with open(p, 'rb') as fh:
                if size > 65536:
                    fh.seek(-65536, os.SEEK_END)
                data = fh.read().decode('utf-8', 'replace')
        except OSError:
            continue
        for line in reversed(data.splitlines()):
            if (' AUDIT %s ' % prefix) not in line:
                continue
            h = parse_entry_hash(line)
            if h:
                return h   # this file's newest matching entry wins
    return GENESIS


def default_path(app):
    """The XDG state dir for app (the fallback base = ~/.local/state);
    created on demand."""
    base = os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')
    d = os.path.join(base, app)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'audit.log')


class AuditLog:
    """'<UTC stamp> AUDIT <PREFIX> <EVENT> <chain hash> [detail]' per line —
    the 12-hex hash chains the entry to this writer's previous one
    (entry_hash), making any edit/reorder/middle-deletion evident to
    scripts/audit_verify.py. PREFIX distinguishes the writer (CACHE / INV /
    CLI / CTL) and each prefix chains its own lines, so interleaved writers
    in one file verify independently. Opening failure = fatal: an audit
    trail that silently vanishes is worse than no session.
    All writers share one process-wide file, so every write+flush+rotate
    cycle is serialized — without the lock, a rotation (size/daily) races a
    concurrent writer into an ENOENT and kills the caller's connection.
    The remote-only mode (path 'none' + a forward) keeps the object alive —
    the chain and the forward run, the file write + rotation are skipped and
    no XDG directory is created; `none` without a forward folds to the full
    off (--no-audit-log's state) with one warn line."""

    def __init__(self, path=None, prefix='AUDIT', app='pv-suite',
                 max_mb=10.0, daily=False, files=3, forward=None,
                 forward_format='rfc5424'):
        if not AUDIT_MAX_MB_MIN <= max_mb <= AUDIT_MAX_MB_MAX:
            raise ValueError('audit-max-mb must be %d..%d MB' % (AUDIT_MAX_MB_MIN, AUDIT_MAX_MB_MAX))
        if not AUDIT_FILES_MIN <= files <= AUDIT_FILES_MAX:
            raise ValueError('audit-files must be %d..%d' % (AUDIT_FILES_MIN, AUDIT_FILES_MAX))
        if forward_format not in AUDIT_FORWARD_FORMATS:
            raise ValueError('audit-forward-format must be one of %s' % ', '.join(AUDIT_FORWARD_FORMATS))
        self.prefix = prefix
        self.app = app          # the syslog tag / APP-NAME (the bin name) when forwarding
        self.max_bytes = int(max_mb * 1024 * 1024) if max_mb and max_mb > 0 else 0
        self.daily = daily
        self.keep = max(1, int(files))   # the rotated backups kept (audit.log.1 .. .N)
        self._lock = threading.Lock()
        self._last = GENESIS             # this prefix's last entry hash (the chain)
        self.disabled = False            # the kill switch: the writer object survives, the trail stops
        self._forward_spec = forward or ''
        self._forward_fmt = forward_format
        self._forward_on = self._forward_spec not in ('', 'none')
        self._dropped = 0                # the events not mirrored while the forward is down
        self._syslog = None
        self._f = None
        self._suppressed = False
        if path == 'none' and not self._forward_on:
            # the full-off fold: the same state --no-audit-log spells — one
            # warn line (the typo tripwire for a meant remote-only), the
            # object answers disabled and every event no-ops
            self.disabled = True
            self.path = 'none'
            sys.stderr.write('audit: the local trail is off and no forward is spelled — the audit is disabled\n')
            return
        self._suppressed = path == 'none'   # remote-only: the collector is the sole holder
        self.path = 'none' if self._suppressed else (path or default_path(app))
        self._day = time.strftime('%Y-%m-%d', time.gmtime())
        if self._forward_on:
            try:
                self._syslog = self._open_forward(self._forward_spec)
            except ForwardSoftError as e:
                sys.stderr.write('audit: %s — re-arming on the first event\n' % e)
        if self._suppressed:
            return   # no sink at all: the chain lives in the forwarded lines
        if self.path == '-':    # the stdout sink: no rotation by definition
            self._f = sys.stdout
        else:
            try:
                self._f = open(self.path, 'a', encoding='utf-8')
                self._last = tail_hash(self.path, self.prefix)   # chain from the writer's own trail
            except OSError:
                # a read-only working directory (a container, a packaged install):
                # the trail belongs in the service log rather than nowhere
                sys.stderr.write('audit: %s is not writable, logging the trail to stdout\n' % self.path)
                self.path = '-'
                self._f = sys.stdout

    def _open_forward(self, spec):
        """The mirror's handler for one audit-forward spelling (the
        grammar: none | syslog | syslog:/path | udp://host[:port] |
        tcp://host[:port]). Grammar errors and a missing explicit socket
        raise ValueError — the bins answer with one clean ERROR line + rc
        1; a remote target that does not resolve or refuses raises
        ForwardSoftError (soft: the daemon starts, the lazy re-arm carries
        the forward from the first event)."""
        target = parse_forward(spec)
        if target is None:
            return None
        if target[0] == 'syslog':
            path = target[1]
            if path is None:
                path = syslog_socket()
                if path is None:
                    raise ValueError('no local syslog socket found (%s) — audit-forward syslog cannot forward'
                                     % ', '.join(SYSLOG_SOCKETS))
            elif not os.path.exists(path):
                raise ValueError('audit-forward syslog socket %s does not exist' % path)
            return open_syslog_handler(path)
        kind, host, port = target
        return (UdpForwardHandler if kind == 'udp' else TcpForwardHandler)(
            self.app, host, port, self._forward_fmt)

    def _forward(self, line):
        """The mirror of one finished line (the chain hash included). The
        local forms keep the verbatim stdlib send; the remote forms wrap
        RFC5424/CEF. Fail-stop then lazy re-arm, uniform over every form:
        a send failure closes the handler and notes once; the next event
        re-opens — a success notes once with the dropped count, a failure
        skips silently (no per-event spam). The sink keeps the chain
        either way, and a rebuild (a live set) re-arms the handler."""
        if self._syslog is None:
            if not self._forward_on:
                return
            try:
                self._syslog = self._open_forward(self._forward_spec)
            except (ForwardSoftError, OSError, ValueError):
                self._dropped += 1
                return
            sys.stderr.write('audit: forwarding re-armed after %d event(s) not mirrored\n' % self._dropped)
            self._dropped = 0
        local = not isinstance(self._syslog, RemoteForwardHandler)
        msg = line if not local else '%s: %s' % (self.app, line)
        try:
            self._syslog.handle(logging.LogRecord(self.app, logging.INFO, __file__, 0, msg, None, None))
        except OSError as e:
            try:
                self._syslog.close()
            except OSError:
                pass
            self._syslog = None
            self._dropped += 1
            sys.stderr.write('audit: forwarding stopped (%s) — re-arming on the next event\n' % e)

    def _rotate(self):
        """Close, shift the backups (.1 <- .2 <- .3), reopen fresh."""
        if self.path == '-':
            return
        self._f.close()
        for i in range(self.keep - 1, 0, -1):
            src, dst = '%s.%d' % (self.path, i), '%s.%d' % (self.path, i + 1)
            if os.path.exists(src):
                os.replace(src, dst)
        if os.path.exists(self.path):
            os.replace(self.path, self.path + '.1')
        self._f = open(self.path, 'a', encoding='utf-8')

    def _maybe_rotate(self):
        if self.path == '-':
            return
        if self.daily:
            day = time.strftime('%Y-%m-%d', time.gmtime())
            if day != self._day:
                self._day = day
                self._rotate()
                return
        if self.max_bytes and os.path.getsize(self.path) >= self.max_bytes:
            self._rotate()

    def event(self, event, detail=''):
        if self.disabled:
            return
        with self._lock:
            if not self._suppressed:
                self._maybe_rotate()
            stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            detail = ' '.join(detail.split())   # fold \n\r\t etc: one event = one physical line
            h = entry_hash(self._last, stamp, self.prefix, '%s%s' % (event, (' ' + detail) if detail else ''))
            self._last = h
            native = '%s AUDIT %s %s %s%s' % (stamp, self.prefix, event, h,
                                              (' ' + detail) if detail else '')
            if not self._suppressed:
                self._f.write('%s\n' % native)
                self._f.flush()
            if self._forward_on:
                self._forward(native)

    def command(self, cmd, result):
        """A command the user entered and its outcome (ok/err/bye/local/aborted)."""
        self.event('COMMAND', "'%s' -> %s" % (cmd, result))

    def close(self):
        with self._lock:
            if self._syslog:
                try:
                    self._syslog.close()
                except OSError:
                    pass
                self._syslog = None
            if self._f is None or self.path == '-':
                return
            try:
                self._f.close()
            except OSError:
                pass
