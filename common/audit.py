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
someone holding the algorithm are outside its reach (journald forwarding
stays the strong answer — docs/AUDIT.md F10).

The default location is the tool's XDG state directory
(~/.local/state/<app>/audit.log), NOT the current directory: a packaged
install (nix store, container) has a read-only working directory. Rotation
is gated: size-based (--audit-max-mb, default 10 MB, 0 = off) keeps N
backups; time-based (--audit-daily) rotates at UTC midnight. A path of "-"
sends the trail to stdout — what docker logs / journald capture (stdout,
not stderr: the audit is data, not an error, and it stays in the single
ordered stream the service manager captures). When the sink is stdout,
rotation is disabled by definition. The rotation depth is configurable:
--audit-files N (the default 3)."""
import hashlib
import os
import sys
import threading
import time

HASH_LEN = 12                                   # hex chars per entry hash
GENESIS = '0' * HASH_LEN                        # the chain's first prev


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
    """'<UTC stamp> AUDIT <PREFIX> <EVENT> [detail]' per line. PREFIX
    distinguishes the writer (CACHE / INV / CLI / CTL). Opening failure =
    fatal: an audit trail that silently vanishes is worse than no session.
    All writers share one process-wide file, so every write+flush+rotate
    cycle is serialized — without the lock, a rotation (size/daily) races a
    concurrent writer into an ENOENT and kills the caller's connection."""

    def __init__(self, path=None, prefix='AUDIT', app='pv-suite',
                 max_mb=10.0, daily=False, files=3):
        self.prefix = prefix
        self.path = path or default_path(app)
        self.max_bytes = int(max_mb * 1024 * 1024) if max_mb and max_mb > 0 else 0
        self.daily = daily
        self.keep = max(1, int(files))   # the rotated backups kept (audit.log.1 .. .N)
        self._day = time.strftime('%Y-%m-%d', time.gmtime())
        self._lock = threading.Lock()
        self._last = GENESIS             # this prefix's last entry hash (the chain)
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
        with self._lock:
            self._maybe_rotate()
            stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            detail = ' '.join(detail.split())   # fold \n\r\t etc: one event = one physical line
            body = '%s%s' % (event, (' ' + detail) if detail else '')
            h = entry_hash(self._last, stamp, self.prefix, body)
            self._last = h
            self._f.write('%s AUDIT %s %s %s%s\n' % (stamp, self.prefix, event, h,
                                                     (' ' + detail) if detail else ''))
            self._f.flush()

    def command(self, cmd, result):
        """A command the user entered and its outcome (ok/err/bye/local/aborted)."""
        self.event('COMMAND', "'%s' -> %s" % (cmd, result))

    def close(self):
        with self._lock:
            if self.path == '-':
                return
            try:
                self._f.close()
            except OSError:
                pass
