#!/usr/bin/env python3
"""JSON-lines control server for modbus-cache: inspect and steer the running
proxy — show status/connections/cache/version, clear the cache, restart the
upstream session, reload the whole daemon (the overrides saved, then a
re-exec), graceful shutdown. One command per line, one reply line.
Every request and reply is one JSON object per line (the stdlib json
module): the request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. TCP connections need a token
auth handshake when --control-token is set ({"cmd": "auth", "token": ...});
the unix socket relies on filesystem permissions instead. A second,
read-only token (--control-ops-token) authenticates into the show/clear
verbs only — the ops shift against the admin key, both audited."""
import hmac
import json
import logging
import os
import socket
import struct
import sys
import threading
import time

from common.version import version_string
from common.config import default_profile_path, parse_upstream, resolve_profile_file, load_token_file
from common.dump import SECRET_REMOVED, dump_filter
from common.cred import peer_uid, parse_trust_uids
from common.human import secs
from common.logutil import UtcFormatter
from common.protocol import ModbusError
from common.audit import AuditLog
from common.wiresec import frame_mac, sign_reply, verify_request_mac, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.options import control_command, grouped_rows, match_setting_path, describe_node
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, LOG_LEVELS
from .options import OPTIONS, SETTING_BY_NAME, describe_setting, SHOW_BY_LIVE, NODE_BY_NAME, KNOWN_VERBS
from .cache import build_blocks
from .config import parse_write_registers, parse_acl, acl_text, acl_summary, parse_selection, parse_listen, parse_control_target
from .metrics import MetricsServer, describe_metrics
from . import persist

logger = logging.getLogger('modbus-cache')

# The registry-driven bounds: the row's min/max (inclusive) are the one
# home for a knob's range — the branches parse and plumb, the row gates.
OPTION_BY_LIVE = {o.live: o for o in OPTIONS if o.live}
TYPED_CONVS = (int, float, str)

MAX_LINE = CONTROL_LINE_CAP   # the pre-auth line-buffer cap (drop past it)


class ControlServer:
    """JSON-lines control socket for the cache. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. A second, read-only token (ops_token) may be
    configured beside the admin token: it authenticates into the show/clear
    verbs only — no set/unset, no request dump/restore, no reload, no
    restart, no shutdown (common/wiresec.py's roles). `stopper` is the graceful-stop
    callback shared with the signal handlers; it runs after the shutdown
    reply left the wire."""

    def __init__(self, proxy, target, stopper=None, audit=None, token=None, defaults=None, trust_uids=None,
                 socket_group=False, ops_token=None, ops_verbs=None, config_path=None):
        self.proxy = proxy
        self.config_path = config_path  # the config script the daemon started from — the reload state lives beside it
        self.reload_pending = False     # a reload saved the state; the exec runs after the reply leaves the wire
        self.audit = audit               # the CACHE audit trail (common.audit), None = off
        self.token = token               # the TCP auth token (the admin role); None = no auth (the unix = the perms)
        self.ops_token = ops_token       # the read-only ops token (the ops role); None = off
        self.ops_verbs = frozenset(v.lower() for v in (ops_verbs or OPS_VERBS))   # the ops role's RBAC policy
        self.is_unix = not isinstance(target, int)
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.socket_group = bool(socket_group)   # chmod 0660 instead of 0600 on the unix socket
        self.trust_uids = trust_uids or frozenset()   # extra peer uids the unix socket trusts without the token
        self.stopper = stopper
        self.shutdown_pending = False
        self.defaults = defaults or {}   # setting -> configured startup value (what `unset` restores)
        self.overridden = set()          # settings changed live (`show status` carries the overridden= row)
        self.clients = set()             # the live control sockets (announce_exit)
        self.clients_lock = threading.Lock()
        self._srv = None                 # the current accept() socket — a live control/port rebind swaps it
        self.stopped = False             # the listener is retired (set control/port off); sessions keep serving

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
                    logger.warning('control socket %s exists, replacing it', self.sockpath)
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
            logger.error('control server cannot bind %s: %s (use --control-port 0 to disable it)', self.describe(), e)
            return
        self._srv = srv
        logger.info('control server listening on %s%s',
                    self.describe(), (', token auth required on TCP' if self.token and not self.is_unix else '')
                    + (', read-only ops token accepted' if self.ops_token else ''))
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
                logger.error('control accept failed (%s), retrying', e)
                time.sleep(0.1)

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
            logger.debug('control client from %s: trusted peer uid %d, no token required', who, uid)
            return ROLE_ADMIN
        logger.info('control client from %s: peer uid %d is not trusted, the token is required', who, uid)
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
        gate the ops role (show/clear only), verify the frame mac keyed by
        the session's token, run the command. Returns (cmd, reply-obj,
        internal-reply, role) — the role so the auth reply can promote the
        session. The text of a multi-line reply keeps its embedded newlines;
        the '.' terminator of the internal form is stripped (the JSON frame
        needs no framing)."""
        try:
            obj = json.loads(line) if line else {}
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or not isinstance(obj.get('cmd'), str):
            return '', {'status': 'err',
                        'text': 'malformed request: expected {"cmd": "<command>"} JSON'}, 'err malformed request', role
        cmd = obj['cmd']
        if self.token and cmd.lower() != 'auth' and role is None:
            return cmd, {'status': 'err', 'text': 'authenticate first: {"cmd": "auth", "token": "..."}'}, \
                'err authenticate first', role
        if cmd.lower() == 'auth':
            granted = self.auth_role(obj.get('token'))
            if granted:
                key = self.session_key(granted)
                reply = 'ok authenticated'
                return 'auth', {'status': 'ok', 'text': 'authenticated', 'mac': sign_reply(key, reply)}, reply, granted
            return 'auth', {'status': 'err', 'text': 'bad token'}, 'err bad token', role
        key = self.session_key(role)
        if key and obj.get('mac') is None and not self.is_unix:
            return cmd, {'status': 'err',
                         'text': 'unsigned command rejected: TCP commands carry the hmac-sha256 of the command, keyed by the token'}, \
                'err unsigned command', role
        if key and obj.get('mac') is not None and not verify_request_mac(key, cmd, obj.get('mac')):
            return cmd, {'status': 'err',
                         'text': 'the command mac does not verify (tampered or corrupted frame)'}, 'err bad command mac', role
        if not role_allows(role, cmd, self.ops_verbs):
            verb = command_verb(cmd) or cmd
            text = ('forbidden: the ops token runs the %s verbs only (%s needs the admin token)'
                    % ('/'.join(sorted(self.ops_verbs)), verb))
            reply = 'err ' + text
            reply_obj = {'status': 'err', 'text': text}
            if key:
                reply_obj['mac'] = sign_reply(key, reply)
            logger.warning('control: ops session from %s denied %r (read-only role)', who, cmd)
            return cmd, reply_obj, reply, role
        reply = self.command(cmd)
        if reply is None:              # quit: no reply, just close
            return cmd, None, 'bye', role
        status, _, text = reply.partition(' ')
        reply_obj = {'status': status, 'text': text}
        if key:
            reply_obj['mac'] = sign_reply(key, reply)
        return cmd, reply_obj, reply, role

    def announce_exit(self, reason, text=None):
        """The daemon is going down: send every connected control client a
        bye frame (the consoles print the notice and exit instead of trying
        to reconnect to a dead proxy) and close their sockets. `text`
        replaces the shutdown wording (the reload speaks of restarting)."""
        frame = (json.dumps({'status': 'bye',
                             'text': text or 'daemon-exit: the modbus-cache proxy is shutting down (%s)' % reason}, ensure_ascii=False)
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

    def handle(self, client, addr):
        who = self.peer(addr)
        logger.debug('control client connected from %s', who)
        role = self.trusted_peer(client, who)   # the peer-cred shortcut = the admin role; TCP starts unauthenticated
        with self.clients_lock:
            self.clients.add(client)
        try:
            client.settimeout(CONTROL_IDLE_TIMEOUT_S)
            buf = b''
            while True:
                if b'\n' not in buf:      # buffered reads: a 1 MB frame must not
                    chunk = client.recv(65536)   # cost a syscall per byte
                    if not chunk:
                        break
                else:
                    chunk = b''
                buf += chunk
                if len(buf) > MAX_LINE:   # no newline = no frame: drop the amplifier
                    logger.warning('control client from %s: the line exceeded %d bytes, dropping it', who, MAX_LINE)
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
                logger.debug('control from %s: %s -> %s', who, cmd, reply)
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
            logger.error('control handler crashed (%s)', e)
        finally:
            logger.debug('control client from %s disconnected', who)
            with self.clients_lock:
                self.clients.discard(client)
            client.close()

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, unset <setting>, inspect, show <setting|status|connections|cache|'
                'uplink|version|config|knobs>')
        if self.proxy.dump_path:
            cmds += ', request dump [with-cache], request restore'
        cmds += ', clear cache, reload, restart, shutdown, quit; help <setting> describes it, help config maps every knob to its control command, show knobs prints the full dictionary'
        return cmds

    def config_mapping(self):
        """The knob -> control-command mapper (help config): every option of
        the registry under its display group (the row's `group`, ungrouped
        rows headerless), with the command that changes it on a running daemon — or
        the restart note when the knob is startup-only."""
        from .options import OPTIONS
        lines = ['ok config mapping']
        for key, rows in grouped_rows(OPTIONS):
            if key:
                lines.append('# --- %s ---' % key)
            for o in rows:
                lines.append('%-24s %s' % (o.name, control_command(o)))
        return '\n'.join(lines)

    def knobs_dictionary(self):
        """The dictionary of all knobs (show knobs): every option of the
        registry under its display group, with its flag, its env twin(s),
        the control command that changes it and the secret marker."""
        from .options import OPTIONS
        from common.options import knob_dictionary
        return knob_dictionary(OPTIONS, who='the modbus-cache')

    def show_config(self):
        """The effective configuration as a set-grammar script: every line a
        `set`, sectioned by the shared registry comments — the output pipes
        straight back into a config file (or through a ctl client). The
        secret knobs render as `set <name> *** SECRET REMOVED ***` (the
        value never does — the file/flag/env form is the documented way);
        the live overrides ride in as their current values."""
        from .options import OPTIONS, config_value
        from common.options import render_config_script
        cfg = dict(self.proxy.config or {})
        values = {}
        for o in OPTIONS:
            v = config_value(o.name, cfg)
            if v is not None:
                values[o.name] = v
            elif o.secret and o.flag and cfg.get(o.flag[2:].replace('-', '_')):
                values[o.name] = SECRET_REMOVED   # the knob renders, the value never does
        script = render_config_script(OPTIONS, values,
                                      comment='generated by show config — the secret knobs render as '
                                              '*** SECRET REMOVED ***, pass them by flag/env/token-file')
        return 'ok config\n' + script

    def command(self, cmd):
        cmd = cmd.strip()
        low = cmd.lower()
        if low.split()[0] in ('help', '?') and low != '?':
            args = cmd.split()[1:]
            if args and args[0].lower() == 'config':
                return self.config_mapping()
            if args and args[0].lower() == 'knobs':
                return self.knobs_dictionary()
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                if key == 'dump-interval' and not self.proxy.dump_path:
                    return 'err dump-interval needs a dump path (set dump/path or --dump-path)'
                return 'ok %s' % describe_setting(key)
            if args:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            return 'ok ' + self.command_help()
        if low == '?':
            return 'ok ' + self.command_help()
        if low == 'quit':
            return 'bye'
        if low == 'ping':                 # keep-alive from cache_cli
            return 'ok pong'
        if cmd.startswith('unset'):
            args = cmd.split()[1:]
            if not args:
                return 'err unset needs a setting (try help)'
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest and getattr(SETTING_BY_NAME.get(key), 'restart', False):
                return 'err restart required (startup-only knob)'
            if key is None or rest or key not in self.defaults:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            try:
                shown = self._apply(key, self.defaults[key])
            except ValueError as e:
                return 'err %s' % e
            self.overridden.discard(key)
            logger.info('control: unset %s -> ok %s=%s', key, key, shown)
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if cmd.startswith('set'):
            args = cmd.split()[1:]
            if len(args) < 2:
                return 'err set needs a setting and a value (try help)'
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is None:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            if not rest:
                return 'err set needs a setting and a value (try help)'
            if getattr(SETTING_BY_NAME.get(key), 'restart', False):
                return 'err restart required (startup-only knob)'
            value = ' '.join(rest)
            if value == SECRET_REMOVED and getattr(SETTING_BY_NAME.get(key), 'secret', False):
                return 'err *** SECRET REMOVED *** is not a value — pass the secret by flag/env/token-file'
            try:
                shown = self._apply(key, value)
            except ValueError as e:
                return 'err %s' % e
            self.overridden.add(key)
            logger.info('control: set %s=%s', key, shown)
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if low == 'show status':
            return self.status_report()
        if low == 'show connections':
            return 'ok connections ' + self.connections_line()
        if low == 'show cache-all':
            return self.cache_all_report()
        if low == 'show uplink':
            return self.uplink_report()
        if low == 'show cache':
            return 'ok ' + self.cache_line()
        if low == 'show version':
            return 'ok modbus-cache %s' % version_string()
        if low in ('show config', 'show config all'):   # 'all' rides along: the script IS the full config
            return self.show_config()
        if low == 'show knobs':
            return self.knobs_dictionary()
        if low.startswith('show'):
            args = cmd.split()[1:]
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                opt = OPTION_BY_LIVE.get(key)
                if opt is not None and opt.secret:
                    return 'err %s is a secret — it never shows (pass it by flag/env/token-file)' % key
                word = SHOW_BY_LIVE.get(key)
                if word:
                    return self.command('show ' + word)   # a show command's report, by its word
                if key == 'dump-interval' and not self.proxy.dump_path:
                    return 'err dump-interval needs a dump path (set dump/path or --dump-path)'
                return 'ok %s=%s' % (key, self._get(key))
            if key is not None and rest:
                return 'err %s: unexpected %s' % (key, ' '.join(rest))
            if len(args) == 1 and args[0].lower() in NODE_BY_NAME:
                return 'ok %s' % describe_node(OPTIONS, args[0].lower())
            if len(args) == 1:
                return 'err unknown setting %s (try help)' % args[0].lower()
        if low == 'inspect':
            return self.inspect()
        if low == 'clear cache':
            dropped = self.proxy.cache.clear()
            self.proxy.poll_wake.set()
            logger.info('control: cache cleared (%d register word(s) dropped), repolling now', dropped)
            return 'ok cache cleared (%d register word(s) dropped), repolling now' % dropped
        if low == 'request dump':
            return self.dump_state(self.proxy.dump_with_cache)
        if low == 'request dump with-cache':
            return self.dump_state(True)
        if low == 'request restore':
            return self.restore_state()
        if low == 'restart':
            with self.proxy.upstream.lock:
                self.proxy.upstream.close()
            dropped = self.proxy.cache.clear()
            self.proxy.poll_wake.set()
            logger.info('control: upstream session restarted (connection dropped, %d register word(s) dropped, repolling now)',
                        dropped)
            return 'ok upstream session restarted (connection dropped, %d register word(s) dropped, repolling now)' % dropped
        if low == 'reload':
            return self.reload_daemon()
        if low == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        return 'err unknown command %r (try help)' % cmd

    def _gate_range(self, key, v, what=''):
        """The row's min/max (inclusive) — the registry is the one home for
        a knob's bounds; the branch parses and plumbs, the row gates."""
        opt = OPTION_BY_LIVE.get(key)
        if opt is None or opt.conv not in TYPED_CONVS:
            return
        if (opt.min is not None and not v >= opt.min) or (opt.max is not None and not v <= opt.max):
            raise ValueError('%s must be %s..%s%s' % (key, opt.min, opt.max, (' ' + what) if what else ''))

    def _apply(self, key, value):
        """Apply a live setting; returns the display string or raises
        ValueError (the message becomes the err reply)."""
        p = self.proxy
        val = str(value).strip()

        def num(text, label, what):
            try:
                return float(text)
            except ValueError:
                raise ValueError('%s must be %s, got %r' % (label, what, text))

        def numi(text, label, what):
            try:
                return int(text)
            except ValueError:
                raise ValueError('%s must be %s, got %r' % (label, what, text))

        if key == 'modbus/interval':
            v = num(val, 'interval', 'seconds')
            if not 0 < v <= 86400:
                raise ValueError('interval must be 0 < N <= 86400 seconds')
            p.interval = v
            p.poll_wake.set()
            return secs(v)
        if key == 'cache/ttl':
            if val in ('off', 'none', '0'):
                p.cache.cache_ttl = 0
                return 'off'
            v = num(val, 'ttl', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.cache.cache_ttl = v
            return secs(v)
        if key == 'modbus/read-delay':
            v = num(val, 'read-delay', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.read_delay = v
            return secs(v)
        if key == 'modbus/merge-gap':
            v = numi(val, 'merge-gap', 'registers')
            self._gate_range(key, v, 'registers')
            p.merge_gap = v
            p.blocks = build_blocks(p.cache.ranges, v)
            p.poll_wake.set()
            return '%d' % v
        if key == 'modbus/upstream':
            try:
                host, port = parse_upstream(val, label='modbus/upstream')
            except SystemExit as e:
                raise ValueError(str(e))
            p.upstream.host, p.upstream.port = host, port
            p.upstream.close()   # the session drops; the next exchange dials the new endpoint
            p.config['upstream'] = '%s:%d' % (host, port)
            p.config['host'], p.config['port'] = host, port
            return '%s:%d' % (host, port)
        if key == 'modbus/unit':
            v = numi(val, 'unit', 'unit id')
            self._gate_range(key, v)
            p.upstream.unit = v
            p.upstream.close()   # the in-flight session spoke the old unit
            p.config['unit'] = v
            return '%d' % v
        if key == 'write/allow':
            if val not in ('on', 'off'):
                raise ValueError('allow-write must be on|off')
            p.allow_write = val == 'on'
            return val
        if key == 'write/registers':
            p.write_ranges = parse_write_registers(val, 'write-registers')
            return p.describe_write_ranges()
        if key == 'limits/max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            p.max_clients = v
            return '%d' % v
        if key == 'limits/client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.client_timeout = v
            return secs(v)
        if key == 'limits/max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            p.conn_gate.max_per_ip = v
            return '%d' % v
        if key == 'control/port':
            try:
                target = parse_control_target(val)
            except SystemExit as e:
                raise ValueError(str(e))
            if val in ('off', 'none', '0'):
                target = None
            if target is not None and not self.stopped and self._is_target(target):
                return self.describe()   # the same target: nothing to rebind
            if isinstance(target, int) and self.token is None:
                raise ValueError('control/port cannot serve TCP without a token (F5 in docs/AUDIT.md): '
                                 'set control/token first')
            return self._rebind_control(target)
        if key == 'control/token':
            if val in ('off', 'none', ''):
                if not self.is_unix and not self.stopped:
                    raise ValueError('the TCP control port needs its token (F5 in docs/AUDIT.md) — '
                                     'only the unix socket (the filesystem is the auth) may run tokenless')
                self.token = None
                return 'off'
            if self.ops_token and hmac.compare_digest(val, self.ops_token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.token = val   # the rotation is live: the sessions re-auth, the macs verify against the new key
            return '<set>'
        if key == 'control/token-file':
            try:
                tok = load_token_file(val, 'control-token-file')
            except SystemExit as e:
                raise ValueError(str(e))
            if self.ops_token and hmac.compare_digest(tok, self.ops_token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.token = tok
            return '<set>'
        if key == 'control/ops/token':
            if val in ('off', 'none', ''):
                self.ops_token = None   # the ops shift signs off; the admin role is untouched
                return 'off'
            if self.token and hmac.compare_digest(val, self.token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.ops_token = val
            return '<set>'
        if key == 'control/ops/token-file':
            try:
                tok = load_token_file(val, 'control-ops-token-file')
            except SystemExit as e:
                raise ValueError(str(e))
            if self.token and hmac.compare_digest(tok, self.token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.ops_token = tok
            return '<set>'
        if key == 'control/ops-verbs':
            verbs = frozenset(v.strip().lower() for v in val.split(',') if v.strip())
            unknown = sorted(v for v in verbs if v not in KNOWN_VERBS)
            if not verbs or unknown:
                raise ValueError('the ops policy needs at least one verb the grammar speaks%s: %s'
                                 % ('' if not unknown else ' (unknown: %s)' % ', '.join(unknown),
                                    ', '.join(sorted(KNOWN_VERBS))))
            self.ops_verbs = verbs
            return ','.join(sorted(verbs))
        if key == 'control/trust-uids':
            try:
                uids = parse_trust_uids('none' if val == 'off' else val, 'control/trust-uids')
            except SystemExit as e:
                raise ValueError(str(e))
            self.trust_uids = uids or frozenset()
            return ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
        if key == 'control/socket-group':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('control/socket-group must be on or off')
            self.socket_group = on
            if self.is_unix and self._srv is not None and os.path.exists(self.sockpath):
                os.chmod(self.sockpath, 0o660 if on else 0o600)   # the live socket re-modes too
            return 'on' if on else 'off'
        if key == 'metrics/enable':
            if val in ('on', 'true', '1', 'yes'):
                if p.metrics_srv:
                    return 'on'
                if not p.metrics_token:
                    raise ValueError('the metrics endpoint serves register values: '
                                     'set --metrics-token/--metrics-token-file first (F6 in docs/AUDIT.md)')
                srv = MetricsServer(p, p.metrics_listen, token=p.metrics_token,
                                    max_clients=p.metrics_caps[0], client_timeout=p.metrics_caps[1],
                                    max_per_ip=p.metrics_caps[2])
                srv.start()
                p.metrics_srv = srv
                p.metrics_desc = describe_metrics(p.metrics_listen, p.metrics_token,
                                                  p.metrics_caps[0], p.metrics_caps[2])
                return 'on'
            if val in ('off', 'false', '0', 'no'):
                if p.metrics_srv:
                    p.metrics_srv.stop()
                    p.metrics_srv = None
                    p.metrics_desc = 'off'
                return 'off'
            raise ValueError('metrics enable must be on or off')
        if key == 'metrics/listen':
            try:
                t = parse_listen(val)
            except SystemExit as e:
                raise ValueError(str(e))
            probe = socket.socket()
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(t)
            except OSError as e:
                raise ValueError('cannot bind %s:%d: %s' % (t[0], t[1], e))
            finally:
                probe.close()
            p.metrics_listen = t
            if p.metrics_srv:
                p.metrics_srv.stop()
                p.metrics_srv.listen = t
                p.metrics_srv.start()
            p.metrics_desc = describe_metrics(t, p.metrics_token, p.metrics_caps[0], p.metrics_caps[2])
            return '%s:%d' % t
        if key == 'metrics/token':
            if not val or val in ('off', 'none', '0'):
                raise ValueError('metrics/token is mandatory while the endpoint serves (F6 in docs/AUDIT.md) — set the new token')
            p.metrics_token = val
            if p.metrics_srv:
                p.metrics_srv.token = val   # the handler reads it per request — the swap is live
            p.metrics_desc = describe_metrics(p.metrics_listen, val, p.metrics_caps[0], p.metrics_caps[2])
            return '<set>'
        if key == 'metrics/token-file':
            token = load_token_file(val, 'metrics-token-file')
            p.metrics_token = token
            if p.metrics_srv:
                p.metrics_srv.token = token
            p.metrics_desc = describe_metrics(p.metrics_listen, token, p.metrics_caps[0], p.metrics_caps[2])
            return '<set>'
        if key == 'metrics/limits/max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            p.metrics_caps = (v, p.metrics_caps[1], p.metrics_caps[2])
            if p.metrics_srv:
                p.metrics_srv.max_clients = v
                p.metrics_srv._http.gate.max_total = v   # the gate reads its caps per admit
            return '%d' % v
        if key == 'metrics/limits/timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.metrics_caps = (p.metrics_caps[0], v, p.metrics_caps[2])
            if p.metrics_srv:
                p.metrics_srv.client_timeout = v
                p.metrics_srv._Handler.timeout = v or 5   # 0 = the built-in slowloris cap
            return secs(v)
        if key == 'metrics/limits/max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            p.metrics_caps = (p.metrics_caps[0], p.metrics_caps[1], v)
            if p.metrics_srv:
                p.metrics_srv.max_per_ip = v
                p.metrics_srv._http.gate.max_per_ip = v
            return '%d' % v
        if key == 'audit/log-file':
            if val in ('off', 'none'):
                p.audit_params['disabled'] = True
                self._rebuild_audit()
                return 'off'
            p.audit_params['path'] = None if val in ('-', 'stdout') else val
            p.audit_params['disabled'] = False
            self._rebuild_audit()
            return p.audit.path if p.audit else 'off'
        if key == 'audit/rotate/max-size':
            v = num(val, 'max-size', 'MB')
            self._gate_range(key, v, 'MB')
            p.audit_params['max_mb'] = v
            self._rebuild_audit()
            return '%g' % v
        if key == 'audit/rotate/daily':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('audit/rotate/daily must be on or off')
            p.audit_params['daily'] = on
            self._rebuild_audit()
            return 'on' if on else 'off'
        if key == 'audit/rotate/files':
            v = numi(val, 'files', 'backups')
            self._gate_range(key, v, 'backups')
            p.audit_params['files'] = v
            self._rebuild_audit()
            return '%d' % v
        if key == 'audit/disable':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('audit/disable must be on or off')
            p.audit_params['disabled'] = on
            self._rebuild_audit()
            return 'on' if on else 'off'
        if key == 'requests-audit':
            if val in ('off', 'none', '0'):
                p.requests_audit_s = 0
                return 'off'
            v = num(val, 'requests-audit', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.requests_audit_s = v
            return secs(v)
        if key == 'dump-interval':
            if not p.dump_path:
                raise ValueError('dump-interval needs a dump path (set dump/path or --dump-path)')
            if val in ('off', 'none', '0'):
                p.dump_interval = 0
                p.dump_wake.set()
                return 'off'
            v = num(val, 'dump-interval', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.dump_interval = v
            p.dump_wake.set()
            return secs(v)
        if key == 'dump/path':
            if val in ('off', 'none', ''):
                p.dump_path = None
                return 'off'
            p.dump_path = val   # the dump loop, request dump and the shutdown write it from here on
            return val
        if key == 'dump/with-cache':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('dump/with-cache must be on or off')
            p.dump_with_cache = on
            return 'on' if on else 'off'
        if key == 'dump/restore-on-start':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('dump/restore-on-start must be on or off')
            p.restore_on_start = on   # prospective: the START behaviour this session already chose stands
            return 'on' if on else 'off'
        if key == 'local-time':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('local-time must be on|off')
            swapped = 0
            for h in logging.getLogger().handlers:
                f = h.formatter
                if f is None or not getattr(f, '_fmt', None):
                    continue
                h.setFormatter(logging.Formatter(f._fmt) if on else UtcFormatter(f._fmt))
                swapped += 1
            if not swapped:
                raise ValueError('no log handler to re-format')
            return 'on' if on else 'off'
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in LOG_LEVELS:
                raise ValueError('log-level must be one of %s' % ', '.join(LOG_LEVELS))
            logging.getLogger().setLevel(getattr(logging, lvl))
            return lvl
        if key == 'modbus/timeout':
            v = num(val, 'timeout', 'seconds')
            if not 0 < v <= 60:
                raise ValueError('timeout must be 0 < N <= 60 seconds')
            p.upstream.timeout = v
            p.config['timeout'] = v
            return secs(v)
        if key == 'acl/connect':
            acl = self._acl(val, 'acl/connect')
            p.connect_acl = acl
            p.config['connect_acl'] = acl
            return self._acl_text(acl)
        if key == 'acl/write':
            acl = self._acl(val, 'acl/write')
            p.write_acl = acl
            p.config['write_acl'] = acl
            return self._acl_text(acl)
        if key in ('modbus/profile', 'modbus/selection'):
            cfg = self._live_cfg()
            if key == 'modbus/profile':
                cfg['profile'] = default_profile_path() if val in ('default', 'auto') \
                    else resolve_profile_file(val)
            else:
                cfg['selection'] = parse_selection(val)
            saved = p.config
            p.config = cfg
            try:
                p.apply_map()      # ValueError on a bad file: swap and config roll back
            except Exception:
                p.config = saved
                raise
            return cfg['profile'] if key == 'modbus/profile' else (cfg['selection'] or 'all')
        raise ValueError('unknown setting %s' % key)

    def _live_cfg(self):
        """The startup config overlaid with every live setting value, so a map
        reload never undoes what the control surface already applied."""
        p = self.proxy
        cfg = dict(p.config)
        cfg.update(interval=p.interval, read_delay=p.read_delay, merge_gap=p.merge_gap,
                   cache_ttl=p.cache.cache_ttl, allow_write=p.allow_write,
                   write_registers=p.write_ranges, max_clients=p.max_clients,
                   client_timeout=p.client_timeout, requests_audit_s=p.requests_audit_s,
                   connect_acl=p.connect_acl, write_acl=p.write_acl, timeout=p.upstream.timeout,
                   upstream='%s:%d' % (p.upstream.host, p.upstream.port),
                   host=p.upstream.host, port=p.upstream.port, unit=p.upstream.unit)
        return cfg

    def _is_target(self, target):
        """Whether `target` is the listener already running (a re-set of the
        same control/port must not bounce the socket)."""
        if self.stopped:
            return False
        if isinstance(target, int):
            return not self.is_unix and target == self.port
        return self.is_unix and str(target) == self.sockpath

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
                try:
                    old.close()
                except OSError:
                    pass
            logger.info('control: the control server stopped (a control/port set re-enables it)')
            return 'off'
        self.is_unix = not isinstance(target, int)
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.stopped = False
        try:
            srv = self._open_sock()
        except OSError as e:
            self.is_unix, self.port, self.sockpath = old_attrs
            raise ValueError('cannot bind control/port %s: %s' % (target if target is not None else 'off', e))
        old = self._srv
        self._srv = srv
        if old is not None:
            try:
                old.close()
            except OSError:
                pass
        logger.info('control: the control server rebound to %s (the old listener closed)', self.describe())
        threading.Thread(target=self._accept_loop, args=(srv,), daemon=True).start()
        return self.describe()

    def _rebuild_audit(self):
        """Swap the CACHE audit trail for one rebuilt from the proxy's audit
        params (the live path/rotation changes): the fresh writer re-chains
        from the file's own tail (common/audit.py tail_hash), so the chain
        stays verifiable across the swap. The old trail is NOT closed — a
        session still holding it writes its last commands there, and an
        in-flight writer must never hit a closed file."""
        p = self.proxy
        prm = p.audit_params
        if prm['disabled']:
            p.audit = None
        else:
            p.audit = AuditLog(prm['path'], 'CACHE', app='modbus-cache',
                               max_mb=prm['max_mb'], daily=prm['daily'], files=prm['files'])
        self.audit = p.audit   # this server's new sessions (and this one) audit the new trail

    @staticmethod
    def _acl_text(acl):
        """'any' | 'none' | the normalized network list (what `unset` re-parses)."""
        return acl_text(acl)

    def _acl(self, val, label):
        try:
            return parse_acl(val, label)
        except SystemExit as e:
            raise ValueError(str(e))

    def _get(self, key):
        p = self.proxy
        if key == 'modbus/interval':
            return secs(p.interval)
        if key == 'cache/ttl':
            return 'off' if not p.cache.cache_ttl else secs(p.cache.cache_ttl)
        if key == 'modbus/read-delay':
            return secs(p.read_delay)
        if key == 'modbus/merge-gap':
            return '%d' % p.merge_gap
        if key == 'modbus/upstream':
            return '%s:%d' % (p.upstream.host, p.upstream.port)
        if key == 'modbus/unit':
            return '%d' % p.upstream.unit
        if key == 'write/allow':
            return 'on' if p.allow_write else 'off'
        if key == 'write/registers':
            return p.describe_write_ranges()
        if key == 'limits/max-clients':
            return '%d' % p.max_clients
        if key == 'limits/client-timeout':
            return 'none' if not p.client_timeout else secs(p.client_timeout)
        if key == 'limits/max-conn-per-ip':
            return '%d' % p.conn_gate.max_per_ip
        if key == 'control/port':
            return 'off' if self.stopped else self.describe()
        if key in ('control/token', 'control/token-file'):
            return '<set>' if self.token else 'off'   # the secret never renders
        if key in ('control/ops/token', 'control/ops/token-file'):
            return '<set>' if self.ops_token else 'off'   # the secret never renders
        if key == 'control/ops-verbs':
            return ','.join(sorted(self.ops_verbs)) or 'off'
        if key == 'control/trust-uids':
            return ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
        if key == 'control/socket-group':
            return 'on' if self.socket_group else 'off'
        if key == 'metrics/enable':
            return 'on' if p.metrics_srv else 'off'
        if key == 'metrics/listen':
            return '%s:%d' % p.metrics_listen
        if key in ('metrics/token', 'metrics/token-file'):
            return '<set>' if p.metrics_token else 'off'   # the secret never renders
        if key == 'metrics/limits/max-clients':
            return '%d' % p.metrics_caps[0]
        if key == 'metrics/limits/timeout':
            return secs(p.metrics_caps[1])
        if key == 'metrics/limits/max-conn-per-ip':
            return '%d' % p.metrics_caps[2]
        if key == 'audit/log-file':
            return p.audit.path if p.audit else 'off'
        if key == 'audit/rotate/max-size':
            return '%g' % p.audit_params['max_mb']
        if key == 'audit/rotate/daily':
            return 'on' if p.audit_params['daily'] else 'off'
        if key == 'audit/rotate/files':
            return '%d' % p.audit_params['files']
        if key == 'audit/disable':
            return 'on' if p.audit_params['disabled'] else 'off'
        if key == 'dump/path':
            return p.dump_path or 'off'
        if key == 'dump/with-cache':
            return 'on' if p.dump_with_cache else 'off'
        if key == 'dump/restore-on-start':
            return 'on' if getattr(p, 'restore_on_start', False) else 'off'
        if key == 'requests-audit':
            return 'off' if not p.requests_audit_s else secs(p.requests_audit_s)
        if key == 'dump-interval':
            return 'off' if not p.dump_interval else secs(p.dump_interval)
        if key == 'local-time':
            for h in logging.getLogger().handlers:
                f = h.formatter
                if f is not None and getattr(f, '_fmt', None):
                    return 'off' if isinstance(f, UtcFormatter) else 'on'
            return 'off'
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        if key == 'modbus/timeout':
            return secs(p.upstream.timeout)
        if key == 'acl/connect':
            return self._acl_text(p.connect_acl)
        if key == 'acl/write':
            return self._acl_text(p.write_acl)
        if key == 'modbus/profile':
            return p.config.get('profile') or p.profile
        if key == 'modbus/selection':
            return p.config.get('selection') or 'all'
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

    def status_report(self):
        """The status as a compact multi-field report: one stable key=value
        per line (scriptable)."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else secs(max(0, now - p.last_ok))
        fc4 = sum(1 for r in p.cache.ranges if r[0] == 4)
        cfg = p.config or {}
        rows = [
            'upstream=%s:%d' % (p.upstream.host, p.upstream.port),
            'unit=%d' % p.upstream.unit,
            'timeout=%s' % secs(p.upstream.timeout),
            'listen=%s:%d' % (p.listen_addr[0], p.listen_addr[1]),
            'control=%s' % self.describe(),
            'uptime=%s' % secs(now - p.started),
            'poll=%s' % ('ok' if p.poll_ok else 'down'),
            'last_poll=%s' % age,
            'poll_duration=%s' % secs(p.poll_secs_last),
            'poll_duration_mean=%s' % secs(p.poll_secs_sum / p.poll_count if p.poll_count else 0),
            'interval=%s' % secs(p.interval),
            'ttl=%s' % secs(p.cache.cache_ttl),
            'merge_gap=%d' % p.merge_gap,
            'ranges=%d' % len(p.cache.ranges),
            'fc4_ranges=%d' % fc4,
            'map_version=%d' % p.cache.map_version,
            'hits=%d' % p.cache_hits,
            'misses=%d' % p.cache_misses,
            'clients=%d' % p.client_count,
            'max_clients=%s' % (p.max_clients or 'none'),
            'client_timeout=%s' % (secs(p.client_timeout) if p.client_timeout else 'none'),
            'max_conn_per_ip=%s' % (p.conn_gate.max_per_ip or 'none'),
            'connect_acl=%s' % acl_summary(p.connect_acl),
            'writes=%s' % ('enabled' if p.allow_write else 'disabled'),
            'write_acl=%s' % acl_summary(p.write_acl),
            'write_allow_list=%s' % p.describe_write_ranges(),
            'requests_audit=%s' % ('off' if not p.requests_audit_s else secs(p.requests_audit_s)),
            'dump=%s' % ('off' if not p.dump_path else '%s every %s%s' % (
                p.dump_path, 'off' if not p.dump_interval else secs(p.dump_interval),
                ', sealed' if p.dump_key else '')),
            'profile=%s' % (cfg.get('profile') or p.profile),
            'selection=%s' % (cfg.get('selection') or 'all'),
            'metrics=%s' % getattr(p, 'metrics_desc', 'off'),
            'overridden=%s' % (','.join(sorted(self.overridden)) or 'none'),
        ]
        return 'ok status\n' + '\n'.join(rows)

    def clear_overrides(self):
        """The config was re-applied (SIGHUP): nothing is live-overridden anymore."""
        self.overridden.clear()

    def summary(self):
        """The compact state summary appended to the set/unset replies."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else secs(max(0, now - p.last_ok))
        return ('upstream=%s:%d interval=%s ttl=%s poll=%s last-poll=%s hits=%d misses=%d clients=%d'
                % (p.upstream.host, p.upstream.port, secs(p.interval), secs(p.cache.cache_ttl),
                   'ok' if p.poll_ok else 'down', age, p.cache_hits, p.cache_misses, p.client_count))

    def connections_line(self):
        with self.proxy.client_lock:
            if not self.proxy.clients:
                return 'none'
            now = time.monotonic()
            return '; '.join('%s connected %s requests %d' % (k, secs(now - v['since']), v['requests'])
                             for k, v in sorted(self.proxy.clients.items()))

    def inspect(self):
        """One pretty dump of everything — the state, the map, the counters,
        the write gate: the baton for a bug report. Multi-line reply."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else '%s ago' % secs(max(0, now - p.last_ok))
        fc3 = sum(1 for r in p.cache.ranges if r[0] == 3)
        fc4 = len(p.cache.ranges) - fc3
        cfg = p.config or {}
        rows = [
            'version   modbus-cache %s' % version_string(),
            'upstream  %s:%d unit %d, timeout %s, last poll %s%s' % (p.upstream.host, p.upstream.port,
                                                                     p.upstream.unit, secs(p.upstream.timeout), age,
                                                                     '' if p.poll_ok else ' (FAILING)'),
            'listen    %s:%d, control %s, connect-acl %s'
            % (p.listen_addr[0], p.listen_addr[1], self.describe(),
               acl_summary(p.connect_acl)),
            'profile   %s, map v%d' % (cfg.get('profile') or p.profile,
                                       p.cache.map_version),
            'selection %s' % (cfg.get('selection') or 'all'),
            'metrics   %s' % getattr(p, 'metrics_desc', 'off'),
            'selection %s' % (cfg.get('selection') or 'all'),
            'cache     %d range(s) (fc3 %d, fc4 %d), %d word(s), oldest %s, ttl %s, failed range(s) %d'
            % (len(p.cache.ranges), fc3, fc4, len(p.cache.regs),
               self._oldest() or 'n/a', secs(p.cache.cache_ttl),
               sum(1 for v in p.cache.range_ok.values() if v is False)),
            'poll plan %d block(s): %s' % (len(p.blocks),
                                           ' '.join('%s%d:%d' % ('' if fc == 3 else 'fc%d ' % fc, s, c)
                                                    for fc, s, c, _ in p.blocks)),
            'poll cyc  last %s, mean %s, max %s'
            % (secs(p.poll_secs_last),
               secs(p.poll_secs_sum / p.poll_count if p.poll_count else 0), secs(p.poll_secs_max)),
            'counters  hits %d, misses %d, clients %d (limit %s, timeout %s, per-ip %s)'
            % (p.cache_hits, p.cache_misses, p.client_count,
               p.max_clients or 'none', secs(p.client_timeout) if p.client_timeout else 'none',
               p.conn_gate.max_per_ip or 'none'),
            'writes    %s, write-acl %s, write-registers %s'
            % ('ENABLED' if p.allow_write else 'disabled',
               acl_summary(p.write_acl),
               p.describe_write_ranges()),
            'audit     %s%s' % ('off' if p.audit is None else (p.audit.path if p.audit.path != '-' else 'stdout'),
                                ', requests accounting every %s' % secs(p.requests_audit_s) if p.audit and p.requests_audit_s else ''),
            'dump      %s' % ('off' if not p.dump_path else '%s, every %s (plus the dump command and the shutdown)'
                              % (p.dump_path, 'off' if not p.dump_interval else secs(p.dump_interval))),
            'uptime    %s' % secs(now - p.started),
        ]
        return 'ok inspect\n' + '\n'.join(rows)

    def _oldest(self):
        with self.proxy.cache.lock:
            oldest = max((time.time() - t for t in self.proxy.cache.ts.values()), default=None)
        return secs(oldest) if oldest is not None else None

    def cache_line(self):
        c = self.proxy.cache
        with c.lock:
            words = len(c.regs)
            fc4 = sum(1 for r in c.ranges if r[0] == 4)
        failed = sum(1 for v in c.range_ok.values() if v is False)
        return ('cache %d range(s)%s, %d word(s) cached%s, ttl %s, map v%d, failed range(s) %d, hits %d, misses %d'
                % (len(c.ranges), ' (fc4 %d)' % fc4 if fc4 else '', words,
                   ', oldest %s' % (self._oldest() or 'n/a'),
                   secs(c.cache_ttl), c.map_version, failed, self.proxy.cache_hits, self.proxy.cache_misses))

    def cache_all_report(self):
        """Every cached entry, one row per profile range: the words cached,
        their values, the age of the oldest, when it expires and the poll
        status."""
        c = self.proxy.cache
        names = c.names
        cells = []
        for fc, start, count, words, values, oldest, err, entry_ttl in c.entries():
            ttl = entry_ttl if entry_ttl is not None else c.cache_ttl
            age = 'n/a' if oldest is None else secs(oldest)
            shown = [('-' if v is None else '%d' % v) for v in values] or ['-']
            if not ttl:
                exp = 'never'
            elif oldest is None:
                exp = 'n/a'
            else:
                left = ttl - oldest
                exp = secs(left) if left > 0 else 'expired'
            if err is not None:
                status = 'failed (ex %d)' % err
            elif not words:
                status = 'empty'
            elif words < count:
                status = 'partial'
            else:
                status = 'ok'
            name = names.get((fc, start, count), '')
            if entry_ttl is not None:
                name = ('%s [ttl %s]' % (name, secs(entry_ttl))).strip()
            cells.append(('fc%d' % fc, '%d:%d' % (start, count), '%d/%d' % (words, count),
                          ' '.join(shown), age, exp, status, name))
        head = ('fc', 'range', 'words', 'values', 'age', 'expires', 'status', 'name')
        widths = [max(len(h), max((len(r[i]) for r in cells), default=0)) for i, h in enumerate(head)]
        rows = ['  '.join(h.ljust(w) for h, w in zip(head, widths))]
        for r in cells:
            rows.append('  '.join(v.ljust(w) for v, w in zip(r, widths)))
        return 'ok cache-all\n' + '\n'.join(rows)

    @staticmethod
    def _bytes(n):
        return '%.1fkiB' % (n / 1024) if n >= 1024 else '%dB' % n

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values (a
        SIGHUP clears the override set — the dump follows). The secrets
        (control/token, the ops token) ride as *** SECRET REMOVED ***: the
        knob renders, the value never lands in the file — the restore
        skips the placeholder and keeps the secret's current value."""
        p = self.proxy
        prm = p.audit_params
        raw = {
            'modbus/interval': p.interval, 'cache/ttl': p.cache.cache_ttl,
            'modbus/read-delay': p.read_delay,
            'modbus/merge-gap': p.merge_gap, 'write/allow': 'on' if p.allow_write else 'off',
            'write/registers': p.describe_write_ranges(), 'limits/max-clients': p.max_clients,
            'limits/client-timeout': p.client_timeout, 'limits/max-conn-per-ip': p.conn_gate.max_per_ip,
            'metrics/enable': 'on' if p.metrics_srv else 'off',
            'metrics/listen': '%s:%d' % p.metrics_listen,
            'metrics/limits/max-clients': p.metrics_caps[0],
            'metrics/limits/timeout': p.metrics_caps[1],
            'metrics/limits/max-conn-per-ip': p.metrics_caps[2],
            'requests-audit': p.requests_audit_s,
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'modbus/profile': p.config.get('profile'), 'modbus/selection': p.config.get('selection') or 'all',
            'acl/connect': self._acl_text(p.connect_acl), 'acl/write': self._acl_text(p.write_acl),
            'modbus/upstream': '%s:%d' % (p.upstream.host, p.upstream.port),
            'modbus/unit': p.upstream.unit,
            'modbus/timeout': p.upstream.timeout, 'dump-interval': p.dump_interval,
            'local-time': self._get('local-time'),
            'control/port': 'off' if self.stopped else (str(self.port) if not self.is_unix else self.sockpath),
            'control/ops-verbs': ','.join(sorted(self.ops_verbs)) or 'off',
            'control/trust-uids': ','.join(str(u) for u in sorted(self.trust_uids)) or 'off',
            'control/socket-group': 'on' if self.socket_group else 'off',
            'audit/log-file': (p.audit.path if p.audit else 'off'),
            'audit/rotate/max-size': '%g' % prm['max_mb'],
            'audit/rotate/daily': 'on' if prm['daily'] else 'off',
            'audit/rotate/files': '%d' % prm['files'],
            'audit/disable': 'on' if prm['disabled'] else 'off',
            'dump/path': p.dump_path or 'off',
            'dump/with-cache': 'on' if p.dump_with_cache else 'off',
            'dump/restore-on-start': 'on' if getattr(p, 'restore_on_start', False) else 'off',
        }
        return dump_filter(self.overridden, raw, SETTING_BY_NAME)

    def apply_dump_settings(self, settings):
        """Re-apply the dumped overrides; returns (applied, failed-name-list).
        An unknown setting or a value the current config rejects (a moved
        profile, a pruned ACL) is skipped, never fatal; a *** SECRET
        REMOVED *** placeholder (the dump renders an overridden secret's
        knob) is skipped and named — the secret keeps its current value."""
        applied, failed = 0, []
        for name, value in (settings or {}).items():
            if name not in SETTING_BY_NAME:
                failed.append(name)
                continue
            if str(value) == SECRET_REMOVED:
                failed.append('%s (secret, not restored — re-pass by flag/env/token-file)' % name)
                continue
            try:
                self._apply(name, str(value))
                self.overridden.add(name)
                applied += 1
            except ValueError as e:
                failed.append('%s (%s)' % (name, e))
        return applied, failed

    # --- the whole-daemon reload (`reload`): the live overrides serialize to
    # a state file beside the config, the reply leaves the wire, the process
    # re-execs. The fresh daemon re-resolves the config file (the
    # restart-marked knobs take their configured values) and re-applies the
    # saved overrides once (start) — the file and the flags stay the owners
    # of the base, the state file is consumed, nothing lingers. ---

    def _reload_state_path(self):
        return self.config_path + '.reload' if self.config_path else None

    def _save_reload_state(self):
        """The overrides in their wire-parsable form (dump_settings) to the
        state file — the shared dump writer (sealed when dump/key is
        configured); the secrets ride as *** SECRET REMOVED *** (the value
        never lands in the file). Returns (settings, lost-secret-names);
        raises OSError on an unwritable home."""
        settings = self.dump_settings()
        lost = sorted(k for k in self.overridden if settings.get(k) == SECRET_REMOVED)
        persist.write_state_dump(self._reload_state_path(), settings, key=self.proxy.dump_key)
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
            state_obj = persist.read_state_dump(path, key=self.proxy.dump_key)
            if time.time() - state_obj.get('saved', 0) > 120:
                logger.warning('reload: the state file %s is stale, discarding it', path)
                os.unlink(path)
                return
            applied, failed = self.apply_dump_settings(state_obj.get('settings'))
            os.unlink(path)
            logger.info('reload: %d override(s) re-applied from %s%s', applied, path,
                        (' (%d skipped: %s)' % (len(failed), ', '.join(failed))) if failed else '')
            if self.audit:
                self.audit.event('RELOAD', 'restored %d override(s) from %s' % (applied, path))
        except (OSError, ValueError) as e:
            logger.error('reload: the state file %s is unreadable (%s) — starting without it', path, e)

    def reload_daemon(self):
        """The `reload` verb: save the overrides, then restart the whole
        daemon. The fresh process re-resolves the config file — the
        restart-marked knobs (the registry's `restart: true` rows) take
        their configured values — and start() re-applies the saved
        overrides once. The secrets save as *** SECRET REMOVED *** (the
        value never lands in the file): an overridden secret is named in
        the reply, to re-pass by flag/env/token-file."""
        if not self.config_path:
            return 'err reload needs a config path (start with --config)'
        try:
            settings, lost = self._save_reload_state()
        except OSError as e:
            logger.error('control: reload could not save the overrides: %s', e)
            return 'err reload failed: %s' % e
        self.reload_pending = True
        logger.info('control: reload — %d override(s) saved to %s, re-execing',
                    len(settings), self._reload_state_path())
        msg = 'ok reload: %s, the daemon restarts now' % (
            '%d override(s) saved' % len(settings) if settings else 'no overrides to save')
        if lost:
            msg += ' (%s: secret, not saved — re-pass by flag/env/token-file)' % ', '.join(lost)
        return msg

    def _exec_reload(self):
        """The reply is out (the session loop calls this after it): announce
        to the consoles and re-exec in place — the same argv re-resolves the
        config, the fresh daemon rebinds the control target (stale sockets
        are replaced) and restores the saved overrides."""
        if self.audit:
            self.audit.event('RELOAD', 'exec: the daemon re-execs (pid %d)' % os.getpid())
        self.announce_exit('reload', text='daemon-exit: the modbus-cache proxy is reloading — '
                                          'the daemon restarts with the saved configuration')
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(0.2)   # let the bye frames drain
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def dump_state(self, with_cache):
        """The write-behind: the live setting overrides and — when
        with_cache (the `request dump with-cache` command, the
        `--dump-with-cache` default or the dump-interval loop) — the cached
        words (+ stamps), to the configured dump path — sealed when
        dump/key is configured."""
        path = self.proxy.dump_path
        if not path:
            return 'err no dump path configured (set dump/path or --dump-path)'
        settings = self.dump_settings()
        try:
            n = persist.write_dump(path, self.proxy.cache, settings, with_cache=with_cache,
                                   key=self.proxy.dump_key)
        except (OSError, ValueError) as e:
            logger.error('control: the dump to %s failed: %s', path, e)
            return 'err dump failed: %s' % e
        logger.info('control: state dumped to %s (%d word(s), %d setting(s), %s%s)', path, n,
                    len(settings), 'with cache' if with_cache else 'settings only',
                    ', sealed' if self.proxy.dump_key else '')
        return 'ok dumped %d word(s), %d setting(s) to %s%s' % (
            n, len(settings), path, ' (sealed)' if self.proxy.dump_key else '')

    def restore_state(self):
        """Load a dump back: the words (+ their original stamps, so the
        freshness carries over) land in the cache — only what the current
        register map still covers — and the setting overrides re-apply (a
        sealed dump restores only under the configured dump/key)."""
        path = self.proxy.dump_path
        if not path:
            return 'err no dump path configured (set dump/path or --dump-path)'
        if not os.path.exists(path):
            return 'err no dump at %s yet (run dump first)' % path
        try:
            words, stamps, settings = persist.read_dump(path, key=self.proxy.dump_key)
            n = 0 if self.proxy.no_cache else self.proxy.cache.restore(words, stamps)
            applied, failed = self.apply_dump_settings(settings)
        except ValueError as e:
            return 'err restore failed: %s' % e
        self.proxy.poll_wake.set()
        logger.info('control: state restored from %s (%d word(s), %d setting(s))', path, n, applied)
        return 'ok restored %d word(s), %d setting(s) from %s%s' % (
            n, applied, path, ' (%d skipped: %s)' % (len(failed), ', '.join(failed)) if failed else '')

    def uplink_report(self):
        """The inverter link: the session counters (connects, exchanges,
        bytes, errors) and one row per poll block with its status, latency
        and last error — for analysing what the upstream connection does."""
        p = self.proxy
        u = p.upstream
        now = time.monotonic()
        if u.sock is not None:
            sess = 'connected %s' % (secs(now - u.connected_since)
                                     if u.connected_since is not None else '?')
        else:
            sess = 'down' if u.connects else 'never connected'
        mean = p.poll_secs_sum / p.poll_count if p.poll_count else 0.0
        last_ok = 'never' if p.last_ok is None else secs(now - p.last_ok)
        if u.last_error is None:
            last_err = 'none'
        else:
            when = '' if u.last_error_at is None else '%s ago: ' % secs(now - u.last_error_at)
            last_err = '%s%s' % (when, u.last_error)
        rows = [
            'upstream  %s:%d unit %d, timeout %s' % (u.host, u.port, u.unit, secs(u.timeout)),
            'session   %s, connects %d, exchanges %d, in %s out %s, errors %d'
            % (sess, u.connects, u.exchanges, self._bytes(u.bytes_in), self._bytes(u.bytes_out), u.errors),
            'last err  %s' % last_err,
            'poll      interval %s, cycle last %s mean %s max %s, last ok %s ago, plan %d block(s)'
            % (secs(p.interval), secs(p.poll_secs_last), secs(mean), secs(p.poll_secs_max),
               last_ok, len(p.blocks)),
        ]
        cells = []
        for fc, start, count, _leaves in p.blocks:
            s = p.block_stats.get((fc, start, count))
            if s is None:
                cells.append(('fc%d' % fc, '%d:%d' % (start, count), 'pending', '-', '-', '-', '0', '-'))
                continue
            if s['last_err'] is None:
                status, err = 'ok', '-'
            elif s['last_code'] is not None:
                status, err = 'ex %d' % s['last_code'], s['last_err']
            else:
                status, err = 'error', s['last_err']
            cells.append(('fc%d' % fc, '%d:%d' % (start, count), status, secs(s['last']),
                          secs(s['sum'] / s['ok_n']) if s['ok_n'] else '-',
                          secs(s['max']), '%d' % s['fails'], err))
        if cells:
            head = ('fc', 'range', 'status', 'last', 'mean', 'max', 'fails', 'last error')
            widths = [max(len(h), max((len(r[i]) for r in cells), default=0)) for i, h in enumerate(head)]
            rows.append('  '.join(h.ljust(w) for h, w in zip(head, widths)))
            for r in cells:
                rows.append('  '.join(v.ljust(w) for v, w in zip(r, widths)))
        return 'ok uplink\n' + '\n'.join(rows)
