#!/usr/bin/env python3
"""The control server's shared base, one implementation for the family: the
wire tier (the unix/TCP listener with the 0600/0660 socket mode, the
peer-cred trusted peers, the token auth with the admin / read-only-ops
roles, the HMAC frame verification both ways, and the live control/port
rebind family — the listener swaps by identity, the sessions keep
serving), the buffered session handler, the bye-frame announce ladder and
the dump/reload family (the write-behind dump — on command, on the graceful
stop and every dump-interval via the parked dumper loop — the restore, the
whole-daemon reload with its re-exec and the one-shot state file). The
tool subclasses it with its grammar — command()/_apply()/_get() — its
registry rows and its reports; the class attributes name the logger, the
registry and the exit texts. Stdlib only."""
import hmac
import json
import logging
import os
import socket
import sys
import threading
import time

from common.settings import dump as state
from common.runtime.audit import AuditLog, AUDIT_FORWARD_FORMATS, AUDIT_FORWARD_GRAMMAR, parse_forward
from common.runtime.logutil import UtcFormatter
from common.wire.cred import peer_uid, parse_trust_uids
from common.settings.config import parse_control_target
from common.settings.dump import SECRET_REMOVED
from common.settings.options import config_value, control_command, default_ops_verbs, describe_command_node, \
    describe_node, describe_root, grouped_rows, knob_dictionary, known_verbs, make_describe, \
    match_setting_path, render_config_script
from common.render.human import secs
from common.render.texts import T
from common.runtime.version import version_string
from common.wire.wiresec import ROLE_ADMIN, ROLE_OPS, command_verb, proof_tag, role_allows, \
    role_tag, sanitize_command, sign_reply, verify_request_mac

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'defaults.json'), encoding='utf-8') as _f:
    CONTROL_WIRE_DEFAULTS = json.load(_f)    # the shared control-wire tree (flat: the cli_* keys)

# the clients' wire constants, off the same tree (the four lib/statics.py
# re-export them beside their own statics)
CLI_KEEPALIVE_S = CONTROL_WIRE_DEFAULTS['cli_keepalive_s']
CLI_TIMEOUT_S = CONTROL_WIRE_DEFAULTS['cli_timeout_s']
CLI_RECONNECT = CONTROL_WIRE_DEFAULTS['cli_reconnect']
CLI_RECONNECT_WAIT_S = CONTROL_WIRE_DEFAULTS['cli_reconnect_wait_s']
CLI_IDLE_TIMEOUT_S = CONTROL_WIRE_DEFAULTS['cli_idle_timeout_s']
CLI_MAX_LINE_BYTES_S = CONTROL_WIRE_DEFAULTS['cli_max_line_bytes_s']


def num(text, label, what):
    """The `_apply` branches' float parser: the err message keeps the knob's
    label and its unit ('seconds', 'clients', ...)."""
    try:
        return float(text)
    except ValueError:
        raise ValueError('%s must be %s, got %r' % (label, what, text))


def numi(text, label, what):
    """The `_apply` branches' int parser — num's integer sibling."""
    try:
        return int(text)
    except ValueError:
        raise ValueError('%s must be %s, got %r' % (label, what, text))


ON_OFF_WORDS = ('on', 'true', '1', 'yes', 'off', 'false', '0', 'no')


def on_off(val, label):
    """The on/off ladder the family's bool branches share (the eight
    spellings; the truthy set returns True, the falsy set False, anything
    else is the label's ValueError — the err reply). The label is the
    branch's own spelling of the knob (the cache's allow-write, the
    wire's write/allow) — the refusal keeps the pinned text."""
    if val in ('on', 'true', '1', 'yes'):
        return True
    if val in ('off', 'false', '0', 'no'):
        return False
    raise ValueError(T('wire.must_be_on_off') % label)


class ControlServer:
    """The family's control server. The subclass sets the class attributes:
    LOG (the daemon's logger), OPTIONS/SETTINGS (its registry), WHO (the
    show-knobs voice), EXIT_TEXT/RELOAD_TEXT (the bye-frame wording) and
    XDG_STATE_NAME (the reload state's home when a tool starts with no config
    path — --config '' keeps it alive on every tool). RELOAD_NEEDS_CONFIG
    (the reload verb needs a config path) is True family-wide, the fake
    included since it takes the config file too. APPLY_FIRST ('scenario'
    applies before the pins).
    The dump seal key reads self.dump_key — a subclass may replace it with
    a property pointing at its one home (the cache: the proxy's key)."""

    LOG = logging.getLogger('control')   # the subclass names its daemon's logger
    OPTIONS = ()                          # the registry rows — the subclass sets
    SETTINGS = {}                         # SETTING_BY_NAME — the subclass sets
    WHO = 'the daemon'                    # the show-knobs dictionary's voice
    EXIT_TEXT = 'the daemon is shutting down'
    RELOAD_TEXT = 'the daemon is reloading — the daemon restarts with the saved configuration'
    RELOAD_NEEDS_CONFIG = True            # the reload verb needs --config
    XDG_STATE_NAME = None                 # set = the reload state falls back to the state home
    APPLY_FIRST = ()                      # the settings that apply first on a restore
    CLI_MAX_LINE_BYTES_S = CONTROL_WIRE_DEFAULTS['cli_max_line_bytes_s']  # the pre-auth line-buffer cap (the shared tree)
    CLI_IDLE_TIMEOUT_S = CONTROL_WIRE_DEFAULTS['cli_idle_timeout_s']  # the control session's idle cap (the shared tree)
    dump_key = None                       # the dump seal key — a subclass may property it
    CFG_KEYS = {}                         # the knob -> cfg-key renames — the subclass's registry wiring
    CFG_FORMATTERS = {}                   # the cfg key -> text map for the structured values
    APP = 'daemon'                        # the show-version voice ('ok <app> <version>')
    SHOW_REPORTS = {}                     # the tool's own show words: low -> method (or (method, arg))
    RELOAD_CONFIG = True                  # request/reload-config answers family-wide (the reloader is the bin's apply_reload)
    COMMANDS = ()                         # the registries' command rows — the subclass sets
    COMMAND_HELP = {}                     # the command words' one-line help
    COMMAND_GROUPS = {}                   # the command nodes' group buckets
    COMMAND_HIDDEN = frozenset()          # the hidden rows (the dump gate's children)
    NODE_BY_NAME = {}                     # the command namespace's nodes
    SET_BY_NAME = {}                      # the set vocabulary's rows (the knobs — the show reports are not)
    SHOW_BY_LIVE = {}                     # the live name -> the custom show word (the report routing)
    OPTION_BY_LIVE = {}                   # the live name -> the Option row (the bounds, the secrets)
    SHOW_OPTIONS = ()                     # the registry's show section (the bare-show pool)
    AUDIT_PREFIX = None                   # the audit trail's chain prefix ('CACHE') — the subclass sets
    AUDIT_APP = None                      # the audit trail's app voice ('modbus-cache')
    CONTROL_PORT_DEFAULT = None           # the ctl socket's default port (the subclass's statics)
    CONTROL_SOCKET_TEMPLATE = None        # the ctl unix-socket path template
    LOG_LEVELS = ()                       # the log-level words (the subclass's defaults.json list)

    def __init__(self, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None, socket_group=False, ops_token=None,
                 ops_verbs=None, audit_params=None, config_path=None, dump_path=None,
                 restore_on_start=False, dump_key=None, dump_interval=0.0):
        self.reloader = reloader         # request reload: re-resolve the config, apply, returns the summary
        self.audit = audit               # the audit trail (common.audit), None = off
        self.token = token               # the TCP auth token (the admin role); None = no auth (the unix = the perms)
        self.ops_token = ops_token       # the read-only ops token (the ops role); None = off
        # the ops role's RBAC policy — the fallback derives from this server's own command rows
        self.ops_verbs = frozenset(v.lower() for v in (ops_verbs or default_ops_verbs(known_verbs(self.COMMANDS))))
        self.audit_params = dict(audit_params or {})   # the audit family's live swaps rebuild from these (a subclass may re-home after super)
        self.config_path = config_path   # the config script the daemon started from — the reload state lives beside it
        self.reload_pending = False      # a reload saved the state; the exec runs after the reply leaves the wire
        self.dump_path = dump_path or None   # the state dump file (the dump family)
        self.dump_restore = bool(restore_on_start)   # prospective-only: the START already chose
        self.dump_interval = float(dump_interval or 0.0)   # seconds between the automatic dumps; 0 = only the command/shutdown dumps
        self.dump_wake = threading.Event()   # a live `set dump-interval` (and the off/on swaps) wake the dumper without a restart
        if dump_key is not None:
            self.dump_key = dump_key   # only when given: a subclass may property dump_key
        self.is_unix = not isinstance(target, int) and not str(target).isdigit()
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.socket_group = bool(socket_group)   # chmod 0660 instead of 0600 on the unix socket
        self.trust_uids = trust_uids or frozenset()   # extra peer uids the unix socket trusts without the token
        self._srv = None                 # the current accept() socket — a live control/port rebind swaps it
        self.stopped = False             # the listener is retired (set control/port off); sessions keep serving
        self.stopper = stopper
        self.shutdown_pending = False
        self.defaults = defaults or {}   # setting -> configured value (the restart-marked knobs' pending writes land here)
        self.baseline = dict(self.defaults)   # the startup-resolved values — what `clear` restores
        self.overridden = set()          # settings changed live (the dumps carry the overrides)
        self.clients = set()             # the live control sockets (announce_exit)
        self.clients_lock = threading.Lock()
        self.started = time.monotonic()
        self.option_by_live = {o.live: o for o in self.OPTIONS if o.live}   # the row bounds' one home
        self.option_by_name = {o.name: o for o in self.OPTIONS}   # the registry rows by knob name (show config)
        self._describe = make_describe(self.SETTINGS)[0]   # the help-topic knob line (the wire's help <setting>)

    # --- the wire tier ---

    def start(self):
        self._restore_reload_state()   # a reload exec: the saved overrides re-apply once, the state file is consumed
        threading.Thread(target=self.serve, daemon=True).start()

    def describe(self):
        if self.stopped:
            return 'off'
        return 'unix:%s' % self.sockpath if self.is_unix else '127.0.0.1:%d' % self.port

    def cleanup(self):
        if self.is_unix and self.sockpath and os.path.exists(self.sockpath):
            try:
                os.unlink(self.sockpath)
            except OSError:
                pass

    def _open_sock(self):
        """Bind+listen the control socket per the current target attrs: the
        unix path is replaced (stale files unlinked), the mode 0600/0660 is
        not left to the umask, TCP takes SO_REUSEADDR; the listen(64) backlog
        keeps a connect burst from RSTing."""
        srv = socket.socket(socket.AF_UNIX if self.is_unix else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if self.is_unix:
                if os.path.exists(self.sockpath):
                    self.LOG.warning('control socket %s exists, replacing it', self.sockpath)
                    os.unlink(self.sockpath)
                srv.bind(self.sockpath)
                os.chmod(self.sockpath, 0o660 if self.socket_group else 0o600)
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(('127.0.0.1', self.port))
            srv.listen(64)
        except OSError:
            try:
                srv.close()
            except OSError:
                pass
            raise
        return srv

    def serve(self):
        try:
            srv = self._open_sock()
        except OSError as e:
            self.LOG.error(T('daemon.control_cannot_bind'), self.describe(), e)
            return
        self._srv = srv
        self.LOG.info(T('daemon.control_listening'),
                      self.describe(), (T('daemon.control_listening_token') if self.token and not self.is_unix else '')
                      + (T('daemon.control_listening_ops') if self.ops_token else ''))
        self._accept_loop(srv)

    def _accept_loop(self, srv):
        """accept() until this socket stops being the current one: a live
        control/port rebind (or off) swaps self._srv and retires the old
        listener by identity — this loop exits, the new thread takes over."""
        while self._srv is srv:
            try:
                client, addr = srv.accept()
                threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
            except (OSError, RuntimeError) as e:
                if self._srv is not srv:
                    return   # rebinding or stopped: this listener is retired
                self.LOG.error('control accept failed (%s), retrying', e)
                time.sleep(0.1)

    def _is_target(self, target):
        """Whether `target` is the listener already running (a re-set of the
        same control/port must not bounce the socket)."""
        if self.stopped:
            return False
        if isinstance(target, int):
            return not self.is_unix and target == self.port
        return self.is_unix and str(target) == self.sockpath

    @staticmethod
    def _retire_listener(srv):
        """The retired listener: shutdown BEFORE close — a bare close leaves
        a Linux accept() blocked on the kernel-live listener (a connect in
        the window still succeeds; the CI caught the old control port
        answering once), the shutdown wakes the accept and the loop's
        identity check retires it."""
        try:
            srv.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            srv.close()
        except OSError:
            pass

    def _rebind_control(self, target):
        """The live control target (the `set control/port` plumb): bind the
        new socket FIRST (a failed bind leaves the old listener untouched —
        the attrs roll back), then swap self._srv (the old accept loop exits
        by identity), close the old listener and start the new accept loop.
        None retires the listener: the connected sessions keep their threads
        and their replies, no new connection is accepted."""
        old_attrs = (self.is_unix, self.port, self.sockpath)
        if target is None:
            old = self._srv
            self._srv = None
            self.stopped = True
            if old is not None:
                self._retire_listener(old)
            self.LOG.info('control: the control server stopped (a control/port set re-enables it)')
            return 'off'
        self.is_unix = not isinstance(target, int)
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.stopped = False
        try:
            srv = self._open_sock()
        except OSError as e:
            self.is_unix, self.port, self.sockpath = old_attrs
            raise ValueError(T('daemon.control_rebind_cannot_bind') % (target, e))
        old = self._srv
        self._srv = srv
        if old is not None:
            self._retire_listener(old)
        self.LOG.info('control: the control server rebound to %s (the old listener closed)', self.describe())
        threading.Thread(target=self._accept_loop, args=(srv,), daemon=True).start()
        return self.describe()

    def refuse_tokenless_rebind(self, target):
        """The F5 posture on the live wire: a TCP control bind without the
        admin token refuses (TOKENLESS_TCP='allow' exempts — the fake's
        F11 test-tool posture)."""
        if self.TOKENLESS_TCP != 'allow' and isinstance(target, int) and self.token is None:
            raise ValueError(T('wire.f5_tokenless'))

    def handle(self, client, addr):
        who = self.peer(addr)
        self.LOG.debug('control client connected from %s', who)
        role = self.trusted_peer(client, who)   # the peer-cred shortcut = the admin role; TCP starts unauthenticated
        with self.clients_lock:
            self.clients.add(client)
        try:
            client.settimeout(self.CLI_IDLE_TIMEOUT_S)
            buf = b''
            while True:
                if b'\n' not in buf:      # buffered reads: a 1 MB frame must not
                    chunk = client.recv(65536)   # cost a syscall per byte
                    if not chunk:
                        break
                else:
                    chunk = b''
                buf += chunk
                if len(buf) > self.CLI_MAX_LINE_BYTES_S:   # no newline = no frame: drop the amplifier
                    self.LOG.warning('control client from %s: the line exceeded %d bytes, dropping it', who, self.LINE_CAP)
                    break
                if b'\n' not in buf:
                    continue
                line, buf = buf.split(b'\n', 1)
                cmd, obj, reply, role = self.framed(line.decode('utf-8', 'replace').strip(), who, role)
                if cmd == 'auth':
                    ok = reply.startswith('ok')
                    if not ok and self.audit:
                        self.audit.event('AUTH-FAIL', 'peer=%s' % who)
                elif self.audit and cmd.lower() != 'ping':
                    self.audit.event('COMMAND', "peer=%s%s '%s'%s -> %s"
                                     % (who, role_tag(role), cmd, proof_tag(obj), reply.split(' ', 1)[0]))
                self.log_exchange(who, cmd, reply)
                if obj is not None:
                    client.sendall((json.dumps(obj, ensure_ascii=False) + '\n').encode())
                if reply.startswith('bye'):
                    break
                if self.reload_pending:
                    break   # the reply is out — the post-loop hook re-execs
            if self.shutdown_pending and self.stopper:
                self.stopper('control command')   # reply is out, now really stop
            if self.reload_pending:
                self._exec_reload()               # reply is out, now really re-exec
        except (ConnectionError, OSError):
            pass
        except Exception as e:
            self.LOG.error('control handler crashed (%s)', e)
        finally:
            self.LOG.debug('control client from %s disconnected', who)
            with self.clients_lock:
                self.clients.discard(client)
            client.close()

    def log_exchange(self, who, cmd, reply):
        """The per-command debug line (the reply text rides it). A subclass
        may shorten it — the fake hides the reply unless log_replies (the
        words are demo state)."""
        self.LOG.debug('control from %s: %s -> %s', who, cmd, reply)

    @staticmethod
    def peer(addr):
        """Where the client sits: an IP:port for TCP, the socket for unix."""
        if isinstance(addr, (tuple, list)) and len(addr) >= 2:
            return '%s:%d' % (addr[0], addr[1])
        return 'unix socket'

    def trusted_peer(self, client, who):
        """The peer-cred auth on the unix control socket: with a token
        configured, a peer the kernel vouches for — root, the daemon's own
        user or one of trust_uids — is authenticated without the token (a
        local systemd unit speaks without sharing the secret) and holds the
        admin role. TCP peers always need a token (admin or ops)."""
        if not (self.token and self.is_unix):
            return None
        uid = peer_uid(client)
        if uid is None:
            return None
        if uid == 0 or uid == os.getuid() or uid in self.trust_uids:
            self.LOG.debug('control client from %s: trusted peer uid %d, no token required', who, uid)
            return ROLE_ADMIN
        self.LOG.info('control client from %s: peer uid %d is not trusted, the token is required', who, uid)
        return None

    def session_key(self, role):
        """The hmac key of one session's role: the ops sessions sign and
        verify with the ops token, everything else (admin, trusted peer,
        pre-auth) with the admin token."""
        return self.ops_token if role == ROLE_OPS else self.token

    def auth_role(self, given):
        """Which role a presented token authenticates into (hmac.compare_digest
        against both keys): the admin token, the ops token, or None."""
        if isinstance(given, str):
            if self.token and hmac.compare_digest(given, self.token):
                return ROLE_ADMIN
            if self.ops_token and hmac.compare_digest(given, self.ops_token):
                return ROLE_OPS
        return None

    def framed(self, line, who, role):
        """One wire frame in, one out: parse {"cmd": ...}, gate the TCP auth,
        gate the ops role (the policy's verbs), verify the frame mac keyed by
        the session's token, fold the client's utf-8 to the grammar's
        printable 8-bit, run the command. Returns (cmd, reply-obj,
        internal-reply, role) — the role so the auth reply can promote the
        session. The text of a multi-line reply keeps its embedded newlines;
        the '.' terminator of the internal form is stripped (the JSON frame
        needs no framing)."""
        try:
            obj = json.loads(line) if line else {}
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or not isinstance(obj.get('cmd'), str):
            return '', {'status': 'fail',
                        'text': T('wire.malformed_request')}, 'err ' + T('wire.malformed_request_short'), role
        cmd = obj['cmd']
        if self.token and cmd.lower() != 'auth' and role is None:
            return cmd, {'status': 'fail', 'text': T('wire.authenticate_first')}, \
                'err ' + T('wire.authenticate_first_short'), role
        if cmd.lower() == 'auth':
            granted = self.auth_role(obj.get('token'))
            if granted:
                key = self.session_key(granted)
                text = T('wire.authenticated')
                reply = 'ok ' + text
                return 'auth', {'status': 'ok', 'text': text, 'mac': sign_reply(key, reply)}, reply, granted
            return 'auth', {'status': 'fail', 'text': T('wire.bad_token')}, 'err ' + T('wire.bad_token'), role
        key = self.session_key(role)
        if key and obj.get('mac') is None and not self.is_unix:
            return cmd, {'status': 'fail',
                         'text': T('wire.unsigned_command')}, \
                'err ' + T('wire.unsigned_command_short'), role
        if key and obj.get('mac') is not None and not verify_request_mac(key, cmd, obj.get('mac')):
            return cmd, {'status': 'fail',
                         'text': T('wire.command_mac_failed')}, 'err ' + T('wire.command_mac_failed_short'), role
        folded = sanitize_command(cmd)   # the mac spoke the client's bytes; the grammar is printable 8-bit
        if not role_allows(role, folded, self.ops_verbs):
            verb = command_verb(folded) or folded
            text = T('wire.forbidden') % ('/'.join(sorted(self.ops_verbs)), verb)
            reply = 'err ' + text
            reply_obj = {'status': 'fail', 'text': text}
            if key:
                reply_obj['mac'] = sign_reply(key, 'fail ' + text)   # the mac is over the wire form
            self.LOG.warning('control: ops session from %s denied %r (read-only role)', who, cmd)
            return cmd, reply_obj, reply, role
        reply = self.command(folded)
        if reply is None:              # quit: no reply, just close
            return cmd, None, 'bye', role
        status, _, text = reply.partition(' ')
        wstatus = 'fail' if status == 'err' else status   # the wire speaks ok|fail|note|bye; the internal err maps here
        reply_obj = {'status': wstatus, 'text': text}
        if key:
            reply_obj['mac'] = sign_reply(key, '%s %s' % (wstatus, text))   # over the wire form, not the internal
        return cmd, reply_obj, reply, role

    def announce_exit(self, reason, text=None):
        """The daemon is going down: send every connected control client a
        bye frame (the consoles print the notice and exit instead of trying
        to reconnect to a dead daemon) and close their sockets. `text`
        replaces the shutdown wording (the reload speaks of restarting)."""
        frame = (json.dumps({'status': 'bye',
                             'text': text or 'daemon-exit: %s (%s)' % (self.EXIT_TEXT, reason)},
                            ensure_ascii=False)   # the frame is utf-8 like every other reply
                 + '\n').encode()
        with self.clients_lock:
            clients, self.clients = list(self.clients), set()
        for client in clients:
            try:
                client.sendall(frame)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass

    # --- the registry surfaces ---

    def config_mapping(self):
        """The knob -> control-command mapper (help config): every option of
        the registry under its display group (the row's `group`, ungrouped
        rows headerless), with the command that changes it on a running
        daemon — or the restart note when the knob is startup-only."""
        lines = [T('wire.config_mapping')]
        for key, rows in grouped_rows(self.OPTIONS):
            if key:
                lines.append('# --- %s ---' % key)
            for o in rows:
                lines.append('%-24s %s' % (o.name, control_command(o)))
        return '\n'.join(lines)

    def knobs_dictionary(self):
        """The dictionary of all knobs (show knobs): every option of the
        registry under its display group, with its flag, its env twin(s),
        the control command that changes it and the secret marker."""
        return knob_dictionary(self.OPTIONS, who=self.WHO)

    # --- the command grammar (the family's wire verb walk) ---

    def command(self, cmd):
        """The family's wire grammar, one walk (the four tools' copies died
        into it): the help/topic ladder, the quit/ping keepalives, the
        set/clear pair, the show reports and the show walk, then the tool's
        own verbs and the family's request namespace. The hooks the
        subclasses use: SHOW_REPORTS (the tool's show words, beside show
        knobs), RELOAD_CONFIG (request/reload-config answers — the
        reloader wiring is each bin's apply_reload), command_set_special (the fake's
        Modbus-write set words), _after_set (the fake's pin bookkeeping),
        show_root_hidden (the bare-show pool's extra hidden words),
        show_walk_tail (the walk's no-match tail), command_tool (the tool
        verbs: poll now, reset, request flush cache / restart, the dump
        with-cache spelling) and unknown_command (the final err's
        spelling)."""
        cmd = cmd.strip()
        low = cmd.lower()
        if not low:
            return 'err ' + T('wire.empty_command')
        if low.split()[0] in ('help', '?') and low != '?':
            args = cmd.split()[1:]
            if args and args[0].lower() == 'config':
                return self.config_mapping()
            if args and args[0].lower() == 'knobs':
                return self.knobs_dictionary()
            path = '/'.join(w.lower() for w in args)   # the command paths spell as words too — the golden ladder: the commands before the settings
            listing = describe_command_node(self.COMMANDS, self.COMMAND_HELP, self.COMMAND_GROUPS, self.COMMAND_HIDDEN, path)
            if listing is not None:
                return 'ok %s' % listing
            if path in self.COMMAND_HELP:   # a command word — or a childless command node — describes itself
                return 'ok %s' % self.COMMAND_HELP[path]
            key, rest = match_setting_path(args, self.SETTINGS)
            if key is not None and not rest:
                if key == 'dump-interval' and not self.dump_path:
                    return 'err ' + T('wire.dump_interval_needs_path')
                return 'ok %s' % self._describe(key)
            if path in self.NODE_BY_NAME:
                return 'ok %s' % describe_node(self.OPTIONS, path)
            if args:
                return 'err ' + (T('wire.unknown_help_topic') % ' '.join(args))
            return 'ok ' + self.command_help()
        if low == '?':
            return 'ok ' + self.command_help()
        if low == 'quit':
            return 'bye'
        if low == 'ping':                 # keep-alive from the tool's ctl
            return 'ok pong'
        if cmd.startswith('clear'):
            args = cmd.split()[1:]
            if not args:
                return 'err ' + T('wire.clear_needs_setting')
            key, rest = match_setting_path(args, self.SET_BY_NAME)   # the knobs: the show reports have nothing to clear
            s = self.SET_BY_NAME.get(key) if key is not None else None
            if s is not None and not rest and s.restart:
                if s.secret:   # a secret never rides the reload state — the wire refuses it
                    return 'err ' + T('wire.restart_required')
                self.defaults[key] = self.baseline.get(key, self.defaults.get(key))
                self.overridden.discard(key)
                self.LOG.info('control: clear %s (the restart re-applies the configured value)', key)
                return 'note ' + T('wire.restart_required')
            if key is None or rest or key not in self.defaults:
                return 'err ' + (T('wire.unknown_setting') % ' '.join(args))
            try:
                shown = self._apply(key, self.defaults[key])
            except ValueError as e:
                return 'err %s' % e
            self.overridden.discard(key)
            self.LOG.info('control: clear %s -> ok %s=%s', key, key, shown)
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if cmd.startswith('set'):
            args = cmd.split()[1:]
            if len(args) < 2:
                return 'err ' + T('wire.set_needs_value')
            special = self.command_set_special(args)   # the tool's own set words (the fake's Modbus writes)
            if special is not None:
                return special
            key, rest = match_setting_path(args, self.SET_BY_NAME)   # the knobs: the show reports are not settable (and a show path never shadows a knob value)
            if key is None:
                return 'err ' + (T('wire.unknown_setting') % ' '.join(args))
            if not rest:
                return 'err ' + T('wire.set_needs_value')
            s = self.SET_BY_NAME.get(key)
            if s is not None and s.restart and s.secret:
                return 'err ' + T('wire.restart_required')   # a secret cannot ride the reload state
            value = ' '.join(rest)
            if value == SECRET_REMOVED and getattr(s, 'secret', False):
                return 'err ' + T('wire.secret_not_value')
            try:
                shown = self._apply(key, value)
            except ValueError as e:
                return 'err %s' % e
            self._after_set(key)
            self.overridden.add(key)
            self.LOG.info('control: set %s=%s', key, shown)
            if s is not None and s.restart:   # the value is recorded; the restart applies it — a note, not a verdict
                return 'note restart required (startup-only knob)'
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if low == 'show connections':
            return 'ok connections ' + self.connections_line()
        if low == 'show version':
            return 'ok %s %s' % (self.APP, version_string())
        if low in ('show config', 'show config all'):   # 'all' rides along: the script IS the full config
            return self.show_config()
        if low == 'show knobs':
            return self.knobs_dictionary()
        for word, report in self.SHOW_REPORTS.items():   # the tool's own show words (the SHOW_BY_LIVE routing)
            if low == word:
                if isinstance(report, tuple):
                    return getattr(self, report[0])(report[1])
                return getattr(self, report)()
        if low.startswith('show'):
            args = cmd.split()[1:]
            if not args:   # the bare `show`: the walk's first position, the ? output byte for byte
                return 'ok %s' % describe_root(self.OPTIONS, self.SHOW_OPTIONS, hidden_words=self.show_root_hidden())
            key, rest = match_setting_path(args, self.SETTINGS)
            if key is not None and not rest:
                opt = self.OPTION_BY_LIVE.get(key)
                if opt is not None and opt.secret:
                    return 'err ' + (T('wire.secret_never_shows') % key)
                word = self.SHOW_BY_LIVE.get(key)
                if word:
                    return self.command('show ' + word)   # a show command's report, by its word
                if key == 'dump-interval' and not self.dump_path:
                    return 'err ' + T('wire.dump_interval_needs_path')
                return 'ok %s=%s' % (key, self._get(key))
            if key is not None and rest:
                return 'err ' + (T('wire.unexpected_tail') % (key, ' '.join(rest)))
            node_path = '/'.join(w.lower() for w in args)   # the walk the ? offers: every word of the path answers
            if node_path in self.NODE_BY_NAME:
                return 'ok %s' % describe_node(self.OPTIONS, node_path)
            tail = self.show_walk_tail(args)
            if tail is not None:
                return tail
        if low == 'inspect':
            return self.inspect()
        tool = self.command_tool(low, cmd)   # the tool's own verbs, beside the family's request namespace
        if tool is not None:
            return tool
        if low == 'request reload-config' and self.RELOAD_CONFIG:
            if not self.reloader:
                return 'err ' + T('wire.no_reloader')
            try:
                return 'ok reloaded (%s)' % self.reloader()
            except (Exception, SystemExit) as e:   # the resolvers fail SystemExit — keep-last-good, answer the wire
                return 'err reload failed: %s' % e
        if low == 'request dump':
            return self.dump_state()
        if low == 'request restore':
            return self.restore_state()
        if low == 'request reload':
            return self.reload_daemon()
        if low == 'shutdown':
            self.shutdown_pending = True
            self.LOG.info('control: shutdown requested')
            return 'bye shutdown'
        return self.unknown_command(cmd)

    def command_set_special(self, args):
        """The tool's own set words ahead of the registry walk (the fake's
        `set register/coil/discrete` Modbus-write emulation). None = not
        special."""
        return None

    def _after_set(self, key):
        """Post-apply bookkeeping (the fake: a manual pin clears the
        scenario). The default is none."""

    def show_root_hidden(self):
        """Extra hidden words for the bare `show`'s pool (the cache hides
        dump-interval while no dump path is configured)."""
        return ()

    def show_walk_tail(self, args):
        """The show walk's no-match tail: None falls through to the next
        branches (the family's `err unknown command` on a stray extra
        word); a reply ends the walk (the fake reports the whole path)."""
        if len(args) == 1:
            return 'err ' + (T('wire.unknown_setting') % args[0].lower())
        return None

    def command_tool(self, low, cmd):
        """The tool's own verbs, checked before the family's request
        namespace (poll now, reset, request flush cache / restart, the
        dump with-cache spelling). None = not one of them."""
        return None

    def unknown_command(self, cmd):
        """The final err: the family spells the whole command %r-quoted
        (the fake's first-word %s walk keeps its own)."""
        return 'err ' + (T('wire.unknown_command') % cmd)

    # --- the family's shared live knobs (one body, four tools) ---
    #
    # The control/audit/dump/log-level branches the four tools carried as
    # near-copies ride here; only the show-config state write differs (the
    # cache's resolved-config dict, the scraper's locked cfg, the
    # dashboard's startup values, the fake's argv view — record_cfg). The
    # tools' _apply route: the restart preamble, then apply_family_key,
    # then the tool's own branches; _get mirrors through get_family_key.

    def record_cfg(self, updates):
        """The show-config state write (the live truth show config renders —
        the show-config-writeback contract): the subclass points this at its
        resolved-config home. The default drops (the fake's show config is
        the argv that would restart it — the live values are runtime state,
        not there)."""
        return

    def _rebuild_audit(self):
        """Swap the audit trail for one rebuilt from the params (the live
        path/rotation/forward changes rebuild from it — rebuild_audit
        re-chains from the file's own tail, the chain verifiable across the
        swap). The old trail is NOT closed — a session still holding it
        writes its last commands there, and an in-flight writer must never
        hit a closed file. Returns the display line: the trail's path,
        'remote' for the collector-only mode, 'off'."""
        self.audit = self.rebuild_audit(self.audit_params, self.AUDIT_PREFIX, self.AUDIT_APP)
        if self.audit is None or self.audit.disabled:
            return 'off'
        return 'remote' if self.audit.path == 'none' else self.audit.path

    def audit_dump_rows(self):
        """The audit family's dump rows, one shape family-wide (the four
        dump_settings fold these): the re-appliable spellings — the raw
        path/`-`/`none` under audit/log-file, never the display words
        ('stdout', 'remote') a re-apply would take for a path. The daily
        row rides even where a tool's status line folds it away."""
        prm = self.audit_params
        return {
            'audit/log-file': ('off' if (self.audit is None or self.audit.disabled) else self.audit.path),
            'audit/forward': prm.get('forward') or 'none',
            'audit/forward/format': prm.get('forward_format') or 'rfc5424',
            'audit/rotate/max-size': '%g' % prm['max_mb'],
            'audit/rotate/daily': 'on' if prm.get('daily') else 'off',
            'audit/rotate/files': '%d' % prm['files'],
            'audit/disable': 'on' if prm['disabled'] else 'off',
        }

    def apply_restart_key(self, key, val):
        """The restart preamble's shared block: the startup-only knobs every
        tool carries. Returns (True, shown) when key is one of them,
        (False, None) for the tool's own preamble keys (the listen/upstream
        probes differ per tool)."""
        if key == 'dump/restore-on-start':
            if val not in ON_OFF_WORDS:
                raise ValueError(T('wire.restore_on_start_invalid'))
            self.defaults[key] = 'on' if val in ('on', 'true', '1', 'yes') else 'off'
            return True, self.defaults[key]
        return False, None

    def apply_audit_key(self, key, val, raw=None):
        """The audit family's live swaps (the log-file, the rotation, the
        forward pair, the kill switch): the params dict updates, the state
        records, the trail rebuilds. Returns (True, shown) / (False, None).
        The log-file spelling is raw — a path, '-' (= stdout) or empty (the
        XDG state home; AuditLog owns both readings) — `raw` is the case-
        kept spelling (the fake lowercases `val`; a path never lowers),
        `val` carries the word comparisons."""
        raw = val if raw is None else raw
        if key == 'audit/log-file':
            if val == 'none' and self.audit_params.get('forward'):
                # remote-only: the collector is the sole holder (the chain
                # reseeds at GENESIS on the next restart)
                self.audit_params['path'] = 'none'
                self.audit_params['disabled'] = False
                self.record_cfg({'audit_log': 'none', 'no_audit_log': False})
                return True, self._rebuild_audit()
            if val in ('off', 'none'):
                # the full off — none without a forward folds to it (the
                # same state --no-audit-log spells)
                self.audit_params['disabled'] = True
                updates = {'no_audit_log': True}
                if val == 'none':
                    updates['audit_log'] = 'none'
                self.record_cfg(updates)
                return True, self._rebuild_audit()
            self.audit_params['path'] = raw
            self.audit_params['disabled'] = False
            self.record_cfg({'audit_log': raw, 'no_audit_log': False})
            return True, self._rebuild_audit()
        if key == 'audit/rotate/max-size':
            v = num(val, 'max-size', 'MB')
            self._gate_range(key, v, 'MB')
            self.audit_params['max_mb'] = v
            self.record_cfg({'audit_max_mb': v})
            self._rebuild_audit()   # the rotation re-chains live
            return True, '%g' % v
        if key == 'audit/rotate/daily':
            on = on_off(val, 'audit/rotate/daily')
            self.audit_params['daily'] = on
            self.record_cfg({'audit_daily': on})
            self._rebuild_audit()
            return True, 'on' if on else 'off'
        if key == 'audit/rotate/files':
            v = numi(val, 'files', 'backups')
            self._gate_range(key, v, 'backups')
            self.audit_params['files'] = v
            self.record_cfg({'audit_files': v})
            self._rebuild_audit()
            return True, '%d' % v
        if key == 'audit/forward':
            try:
                parse_forward(raw)
            except ValueError:
                raise ValueError(T('wire.audit_forward_grammar') % AUDIT_FORWARD_GRAMMAR)   # the wire speaks the live name
            self.audit_params['forward'] = None if val in ('', 'none') else raw
            self.record_cfg({'audit_forward': raw})
            self._rebuild_audit()   # the fresh forward re-arms the sender, the collector-only fold re-chains
            return True, val
        if key == 'audit/forward/format':
            if val not in AUDIT_FORWARD_FORMATS:
                raise ValueError(T('wire.audit_forward_format_invalid') % ', '.join(AUDIT_FORWARD_FORMATS))
            self.audit_params['forward_format'] = val
            self.record_cfg({'audit_forward_format': val})
            self._rebuild_audit()
            return True, val
        if key == 'audit/disable':
            on = on_off(val, 'audit/disable')
            self.audit_params['disabled'] = on
            self.record_cfg({'no_audit_log': on})
            self._rebuild_audit()   # the kill-switch swaps the live trail for None (the commands stop landing)
            return True, 'on' if on else 'off'
        return False, None

    def apply_family_key(self, key, val, raw=None):
        """The family's shared live knobs: the control plane (the port
        rebind, the ops policy, the trusted peers, the socket group), the
        audit family, the log level, the local-time formatter swap and the
        dump pair. `val` is the tool-normalized value (the off/on words
        compare against it), `raw` the case-kept stripped spelling (a unix
        path or a dump file keeps its case). Returns (True, shown) when
        key is one of them, (False, None) for the tool's own branches."""
        raw = val if raw is None else raw
        if key == 'control/port':
            try:
                target = parse_control_target(raw, self.CONTROL_PORT_DEFAULT, self.CONTROL_SOCKET_TEMPLATE)
            except SystemExit as e:
                raise ValueError(str(e))
            if val in ('off', 'none', '0'):
                target = None
            if target is not None and not self.stopped and self._is_target(target):
                return True, self.describe()   # the same target: nothing to rebind
            self.refuse_tokenless_rebind(target)
            shown = self._rebind_control(target)
            self.record_cfg({'control_port': '0' if target is None else str(target)})
            return True, shown
        if key == 'control/ops/verbs':
            verbs = frozenset(v.strip().lower() for v in val.split(',') if v.strip())
            known = known_verbs(self.COMMANDS)   # the registry is the one home of the vocabulary
            unknown = sorted(v for v in verbs if v not in known)
            if not verbs or unknown:
                raise ValueError(T('wire.ops_policy_invalid')
                                 % ('' if not unknown else ' (unknown: %s)' % ', '.join(unknown),
                                    ', '.join(sorted(known))))
            self.ops_verbs = verbs
            self.record_cfg({'control_ops_verbs': ','.join(sorted(verbs))})
            return True, ','.join(sorted(verbs))
        if key == 'control/trust-uids':
            try:
                uids = parse_trust_uids('none' if val == 'off' else val, 'control/trust-uids')
            except SystemExit as e:
                raise ValueError(str(e))
            self.trust_uids = uids or frozenset()
            self.record_cfg({'control_trust_uids': ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'})
            return True, ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
        if key == 'control/socket-group':
            on = on_off(val, 'control/socket-group')
            self.socket_group = on
            self.record_cfg({'control_socket_group': on})
            if self.is_unix and self._srv is not None and os.path.exists(self.sockpath):
                os.chmod(self.sockpath, 0o660 if on else 0o600)   # the live socket re-modes too
            return True, 'on' if on else 'off'
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in self.LOG_LEVELS:
                raise ValueError(T('wire.log_level_invalid') % ', '.join(self.LOG_LEVELS))
            logging.getLogger().setLevel(getattr(logging, lvl))
            self.record_cfg({'level': lvl})
            return True, lvl
        if key == 'local-time':
            if val not in ON_OFF_WORDS:
                raise ValueError(T('wire.local_time_invalid'))
            on = val in ('on', 'true', '1', 'yes')
            swapped = 0
            for h in logging.getLogger().handlers:
                f = h.formatter
                if f is None or not getattr(f, '_fmt', None):
                    continue
                h.setFormatter(logging.Formatter(f._fmt) if on else UtcFormatter(f._fmt))
                swapped += 1
            if not swapped:
                raise ValueError(T('wire.log_handler_missing'))
            self.record_cfg({'local_time': on})
            return True, 'on' if on else 'off'
        if key == 'dump/path':
            if val in ('off', 'none', ''):
                self.dump_path = None
                self.record_cfg({'dump_path': ''})
                return True, 'off'
            self.dump_path = raw   # request dump and the graceful shutdown write it from here on
            self.record_cfg({'dump_path': raw})
            # the seal is opt-in: without dump/key the dump stays plaintext — say so, once, where the choice is made
            return True, raw if self.dump_key else '%s (not sealed — set dump/key to encrypt at rest)' % raw
        if key == 'dump-interval':
            if not self.dump_path:
                raise ValueError(T('wire.dump_interval_needs_path'))
            if val in ('off', 'none', '0'):
                self.dump_interval = 0
                self.record_cfg({'dump_interval': 0})
                self.dump_wake.set()
                return True, 'off'
            v = num(val, 'dump-interval', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            self.dump_interval = v
            self.record_cfg({'dump_interval': v})
            self.dump_wake.set()
            return True, secs(v)
        return self.apply_audit_key(key, val, raw=raw)

    def get_family_key(self, key):
        """The `_get` view of the family's shared knobs (get_family_key's
        apply-side sibling). Returns (True, value) / (False, None)."""
        if key == 'control/port':
            return True, ('off' if self.stopped else self.describe())
        if key == 'control/ops/verbs':
            return True, (','.join(sorted(self.ops_verbs)) or 'off')
        if key == 'control/trust-uids':
            return True, (','.join(str(u) for u in sorted(self.trust_uids)) or 'off')
        if key == 'control/socket-group':
            return True, ('on' if self.socket_group else 'off')
        if key == 'log-level':
            return True, logging.getLevelName(logging.getLogger().getEffectiveLevel())
        if key == 'local-time':
            for h in logging.getLogger().handlers:
                f = h.formatter
                if f is not None and getattr(f, '_fmt', None):
                    return True, ('off' if isinstance(f, UtcFormatter) else 'on')
            return True, 'off'
        if key == 'dump/path':
            return True, (self.dump_path or 'off')
        if key == 'dump-interval':
            return True, ('off' if not self.dump_interval else secs(self.dump_interval))
        if key == 'audit/log-file':
            if self.audit is None or self.audit.disabled:
                return True, 'off'
            return True, ('remote' if self.audit.path == 'none' else self.audit.path)
        if key == 'audit/forward':
            return True, (self.audit_params.get('forward') or 'none')
        if key == 'audit/forward/format':
            return True, (self.audit_params.get('forward_format') or 'rfc5424')
        if key == 'audit/rotate/max-size':
            return True, ('%g' % self.audit_params['max_mb'])
        if key == 'audit/rotate/daily':
            return True, ('on' if self.audit_params['daily'] else 'off')
        if key == 'audit/rotate/files':
            return True, ('%d' % self.audit_params['files'])
        if key == 'audit/disable':
            return True, ('on' if self.audit_params['disabled'] else 'off')
        return False, None

    def show_config(self):
        """The effective configuration as a set-grammar script (modbus-cache's
        golden shape, family-wide): every line a `set`, sectioned by the
        shared registry comments — the output pipes straight back into a
        config file (or through a ctl client). The secret knobs render as
        `set <name> *** SECRET REMOVED ***` (the value never does — the
        file/flag/env form is the documented way); the live overrides ride
        in as their current values. The resolved startup dict rides
        show_config_cfg(); a knob's special render (the dashboard's
        metrics-server: the live start/stop state, not the startup flag)
        overrides show_config_value()."""
        cfg = dict(self.show_config_cfg() or {})
        values = {}
        for o in self.OPTIONS:
            v = self.show_config_value(o.name, cfg)
            if v is not None:
                values[o.name] = v
            elif o.secret and o.flag and cfg.get(o.flag[2:].replace('-', '_')):
                values[o.name] = SECRET_REMOVED   # the knob renders, the value never does
        script = render_config_script(self.OPTIONS, values,
                                      comment=T('wire.show_config_comment'))
        return T('wire.config_head') + script

    def show_config_cfg(self):
        """The resolved startup config dict the render reads (the subclass
        points it at its one home — the cache's proxy.config, the live dict
        the _apply branches write back into)."""
        return {}

    def show_config_value(self, name, cfg):
        """One knob's set-grammar value off the resolved dict — the
        registry's chain (common.options config_value): the CFG_KEYS
        renames, the CFG_FORMATTERS structured values, secrets hide,
        empties drop."""
        return config_value(name, cfg, self.option_by_name, self.CFG_KEYS, self.CFG_FORMATTERS)

    TYPED_CONVS = (int, float, str)       # the typed knobs the row's bounds gate
    TOKENLESS_TCP = 'refuse'   # the F5 posture: a tokenless TCP control bind refuses (the fake allows — F11's test-tool posture)

    def _gate_range(self, key, v, what=''):
        """The row's min/max (inclusive) — the registry is the one home for
        a knob's bounds; the branch parses and plumbs, the row gates."""
        opt = self.option_by_live.get(key)
        if opt is None or opt.conv not in self.TYPED_CONVS:
            return
        if (opt.min is not None and not v >= opt.min) or (opt.max is not None and not v <= opt.max):
            raise ValueError('%s must be %s..%s%s' % (key, opt.min, opt.max, (' ' + what) if what else ''))

    # --- the dump/reload family ---

    def clear_overrides(self):
        """The config was re-applied (the reload): nothing is
        live-overridden anymore. The base owns `overridden` — the reload's
        wholesale path calls this."""
        self.overridden.clear()

    def dump_settings_tail(self, raw):
        """The dump_settings subclasses' shared tail: the restart-marked
        knobs speak their CONFIGURED value (the pending override, not the
        running one), then the filter keeps the overridden raw and
        re-appliable."""
        for opt in self.OPTIONS:
            if opt.restart and not opt.secret and opt.live and opt.live in self.defaults:
                raw[opt.live] = self.defaults[opt.live]
        from common.settings.dump import dump_filter
        return dump_filter(self.overridden, raw, self.SETTINGS)

    def command_help_tail(self, cmds, dump_words=', request dump, request restore'):
        """The command_help subclasses' shared tail: the dump commands
        appear only when a dump path is configured (there is nothing to
        dump into otherwise), then the help/config pointers."""
        if self.dump_path:
            cmds += dump_words
        cmds += ('; help <setting> describes it, help config maps every knob to '
                 'its control command, show knobs prints the full dictionary')
        return cmds

    @staticmethod
    def probe_bind(t, key):
        """The live listen-move's bind probe: fail fast — the bind at
        restart is too late to complain (the cannot_bind ValueError the
        wire answers)."""
        probe = socket.socket()
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(t)
        except OSError as e:
            raise ValueError(T('wire.cannot_bind') % (t[0], t[1], e))
        finally:
            probe.close()

    @staticmethod
    def gate_connections_line(httpd):
        """The exposition endpoint's live clients: the gate's counters, one
        row per peer IP (the scraper's and dashboard's show connections)."""
        total, per_ip = httpd.gate.snapshot() if httpd else (0, {})
        if not total:
            return 'none'
        rows = ['%d active' % total]
        rows += ['%s: %d' % (ip, n) for ip, n in sorted(per_ip.items())]
        return '; '.join(rows)

    @staticmethod
    def modbus_connections_line(clients, lock):
        """The Modbus surface's live clients: peer, connection age,
        requests served (the cache's and fake's show connections)."""
        with lock:
            if not clients:
                return 'none'
            now = time.monotonic()
            return '; '.join('%s connected %s requests %d' % (k, secs(now - v['since']), v['requests'])
                             for k, v in sorted(clients.items()))

    def apply_dump_settings(self, settings):
        """Re-apply the dumped overrides; returns (applied, failed-name-list).
        An unknown setting or a value the current config rejects is skipped,
        never fatal; a *** SECRET REMOVED *** placeholder (the dump renders
        an overridden secret's knob) is skipped and named — the secret keeps
        its current value. APPLY_FIRST names apply before the rest (the
        fake's scenario: a preset release is the state the pins were pinned
        after — the pins must land on top of it, never under it)."""
        applied, failed = 0, []
        for name in sorted(settings or {}, key=lambda k: k not in self.APPLY_FIRST):
            value = settings[name]
            if name not in self.SETTINGS:
                failed.append(name)
                continue
            if str(value) == SECRET_REMOVED:
                failed.append('%s (secret, not restored — re-pass by flag/env, or as file:<path>)' % name)
                continue
            try:
                self._apply(name, str(value))
                self.overridden.add(name)
                applied += 1
            except ValueError as e:
                failed.append('%s (%s)' % (name, e))
        return applied, failed

    def _reload_state_path(self):
        """The one-shot reload state file: beside the config script — or,
        when the tool has no config (XDG_STATE_NAME set), under the state
        home."""
        if self.config_path:
            return self.config_path + '.reload'
        if self.XDG_STATE_NAME:
            base = os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')
            return os.path.join(base, self.XDG_STATE_NAME, 'reload.json')
        return None

    @classmethod
    def fold_restart_state(cls, config_path, dump_key=None):
        """The reload state's startup-only overrides, folded into the
        startup config BEFORE the sockets bind — the piece that makes the
        restart note true: a `set` of a restart-marked knob records the
        pending value (the dump/reload state carries it), and the execv'd
        restart applies it only if the fresh process reads it before the
        binds. Returns the {live-name: value} of the fresh state's
        non-secret restart knobs (a secret never rides the state — the
        placeholder rule). Read-only: the file is left for
        _restore_reload_state to consume; unreadable or stale, {} (the
        restore at start() reports it)."""
        if config_path:
            path = config_path + '.reload'
        elif cls.XDG_STATE_NAME:
            base = os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')
            path = os.path.join(base, cls.XDG_STATE_NAME, 'reload.json')
        else:
            return {}
        if not os.path.exists(path):
            return {}
        try:
            state_obj = state.read_dump_state(path, key=dump_key)
            if time.time() - state_obj.get('saved', 0) > 120:
                return {}   # stale: the restore at start() discards it and logs
        except (OSError, ValueError):
            return {}
        out = {}
        for name, value in (state_obj.get('settings') or {}).items():
            opt = cls.SETTINGS.get(name)
            if opt is not None and opt.restart and not opt.secret:
                out[name] = value
        return out

    def _save_reload_state(self):
        """The overrides in their wire-parsable form (dump_settings) to the
        state file — the shared dump writer (sealed when dump/key is
        configured). No secret can be overridden (the wire refuses them —
        startup-only), so the lost-secret list stays empty; the naming
        below stays as the class invariant's guard (the value never lands
        in the file either way). Returns (settings, lost-secret-names);
        raises OSError on an unwritable home."""
        settings = self.dump_settings()
        lost = sorted(k for k in self.overridden if settings.get(k) == SECRET_REMOVED)
        path = self._reload_state_path()
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)   # the XDG home may not exist yet
        state.write_dump(path, settings, key=self.dump_key)
        return settings, lost

    def _restore_reload_state(self):
        """One-shot, at start: a reload exec re-applies the saved overrides
        and consumes the state file — a later manual start stays pure (the
        config file and the flags alone). A state older than two minutes is
        stale (a failed start in between): discarded, never applied. The
        file is the shared dump shape — sealed when dump/key is configured
        (the re-exec re-resolves the same key)."""
        path = self._reload_state_path()
        if not path or not os.path.exists(path):
            return
        try:
            state_obj = state.read_dump_state(path, key=self.dump_key)
            if time.time() - state_obj.get('saved', 0) > 120:
                self.LOG.warning('reload: the state file %s is stale, discarding it', path)
                os.unlink(path)
                return
            applied, failed = self.apply_dump_settings(state_obj.get('settings'))
            os.unlink(path)
            self.LOG.info('reload: %d override(s) re-applied from %s%s', applied, path,
                          (T('wire.skipped_suffix') % (len(failed), ', '.join(failed))) if failed else '')
            if self.audit:
                self.audit.event('RELOAD', 'restored %d override(s) from %s' % (applied, path))
        except (OSError, ValueError) as e:
            self.LOG.error('reload: the state file %s is unreadable (%s) — starting without it', path, e)

    def reloaded(self, summary, dump_interval=None, applied=None):
        """The reloader's shared tail (every apply_reload body's last
        lines): the override markers drop — wholesale via the subclass's
        clear_overrides when the reload re-applies every live knob, or
        just the `applied` keys where the tool re-applies a subset (the
        fake's machine pins keep theirs) — and the dump-interval loop
        re-reads the configured interval (the parked dumper wakes). The
        RELOAD audit stays caller-side: the audit voices and the extra
        events differ per tool."""
        if applied is None:
            self.clear_overrides()
        else:
            self.overridden.difference_update(applied)
        if dump_interval is not None:
            self.dump_interval = dump_interval
            self.dump_wake.set()
        return summary

    def reload_daemon(self):
        """The `reload` verb: save the overrides, then restart the whole
        daemon. The fresh process re-resolves the config file — the
        startup-only knobs take their configured values — and start()
        re-applies the saved overrides once. The secrets never save (the
        dump rule): an overridden secret is named in the reply, to re-pass
        by flag/env, or as file:<path>."""
        if self.RELOAD_NEEDS_CONFIG and not self.config_path:
            return T('wire.reload_needs_config')
        try:
            settings, lost = self._save_reload_state()
        except OSError as e:
            self.LOG.error('control: reload could not save the overrides: %s', e)
            return T('wire.reload_failed') % e
        self.reload_pending = True
        self.LOG.info('control: reload — %d override(s) saved to %s, re-execing',
                      len(settings), self._reload_state_path())
        msg = T('wire.reload_ok') % (
            T('wire.reload_saved') % len(settings) if settings else T('wire.reload_none'))
        if lost:
            msg += T('wire.reload_lost_secret') % ', '.join(lost)
        return msg

    def _exec_reload(self):
        """The reply is out (the session loop calls this after it): announce
        to the consoles and re-exec in place — the same argv re-resolves the
        config, the fresh daemon rebinds the control target (stale sockets
        are replaced) and restores the saved overrides."""
        if self.audit:
            self.audit.event('RELOAD', 'exec: the daemon re-execs (pid %d)' % os.getpid())
        self.announce_exit('reload', text='daemon-exit: %s' % self.RELOAD_TEXT)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(0.2)   # let the bye frames drain
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def dump_state(self):
        """The write-behind: the live setting overrides to the configured
        dump path (the `request dump` command and the graceful shutdown) —
        sealed when dump/key is configured."""
        if not self.dump_path:
            return T('wire.no_dump_path')
        settings = self.dump_settings()
        try:
            n = state.write_dump(self.dump_path, settings, key=self.dump_key)
        except (OSError, ValueError) as e:
            self.LOG.error('control: the dump to %s failed: %s', self.dump_path, e)
            return T('wire.dump_failed') % e
        self.LOG.info('control: state dumped to %s (%d setting(s)%s)', self.dump_path, n,
                      T('daemon.sealed_log_suffix') if self.dump_key else '')
        return T('wire.dumped') % (n, self.dump_path, T('wire.sealed_suffix') if self.dump_key else '')

    def restore_state(self):
        """Load a dump back: the setting overrides re-apply (a sealed dump
        restores only under the configured dump/key)."""
        if not self.dump_path:
            return T('wire.no_dump_path')
        if not os.path.exists(self.dump_path):
            return T('wire.no_dump_yet') % self.dump_path
        try:
            settings = state.read_dump(self.dump_path, key=self.dump_key)
            applied, failed = self.apply_dump_settings(settings)
        except ValueError as e:
            return T('wire.restore_failed') % e
        self._after_restore()
        self.LOG.info('control: state restored from %s (%d setting(s))', self.dump_path, applied)
        return T('wire.restored') % (
            applied, self.dump_path,
            T('wire.skipped_suffix') % (len(failed), ', '.join(failed)) if failed else '')

    def _after_restore(self):
        """The tool's post-restore nudge (the scraper wakes its poll loop)."""

    def rebuild_audit(self, prm, prefix, app):
        """Build the audit trail from its params dict (the live
        path/rotation/forward changes rebuild from it): the fresh writer
        re-chains from the file's own tail (common/runtime/audit.py tail_hash), so the chain
        stays verifiable across the swap — except the remote-only mode
        (path 'none' + a forward), which reseeds at GENESIS by design (the
        collector whitelists the restart discontinuity). The old trail is
        NOT closed — a session still holding it writes its last commands
        there, and an in-flight writer must never hit a closed file.
        Returns the writer (None = off); the caller assigns where its live
        state reads. The daily-rotation flag, the forward target/format
        ride the params when the tool carries them."""
        if prm['disabled']:
            return None
        return AuditLog(prm['path'], prefix, app=app, max_mb=prm['max_mb'],
                        daily=prm.get('daily', False), files=prm['files'],
                        forward=prm.get('forward'),
                        forward_format=prm.get('forward_format') or 'rfc5424')

    def shutdown_dump(self):
        """The graceful stop's write-behind: the overrides to the dump path
        (no reply — the log carries it; sealed when dump/key is set)."""
        if not self.dump_path:
            return
        try:
            n = state.write_dump(self.dump_path, self.dump_settings(), key=self.dump_key)
            self.LOG.info('state dumped to %s (%d setting(s)%s)', self.dump_path, n,
                          T('daemon.sealed_log_suffix') if self.dump_key else '')
        except (OSError, ValueError) as e:
            self.LOG.error('the shutdown dump to %s failed: %s', self.dump_path, e)

    def run_dump_interval(self, stopping=None):
        """The dump-interval loop (the cache's golden shape, family-wide):
        parks while the interval is off — a live `set dump-interval` wakes it
        without a restart — and writes the write-behind (the shutdown dump's
        write, on a timer) every interval. `stopping` is the daemon's stop
        predicate; the loop skips the tick once it runs."""
        while not (stopping and stopping()):
            if not self.dump_interval:
                self.dump_wake.wait()
                self.dump_wake.clear()
                continue
            if self.dump_wake.wait(self.dump_interval):
                self.dump_wake.clear()
            if stopping and stopping():
                break
            if not self.dump_path:
                continue   # the path went off live: the interval ticks on, there is nothing to dump into
            try:
                n = state.write_dump(self.dump_path, self.dump_settings(), key=self.dump_key)
                self.LOG.debug('state dumped to %s (%d setting(s)%s)', self.dump_path, n,
                               T('daemon.sealed_log_suffix') if self.dump_key else '')
            except (OSError, ValueError) as e:
                self.LOG.error('the periodic dump to %s failed: %s', self.dump_path, e)
