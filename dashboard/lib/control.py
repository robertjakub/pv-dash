#!/usr/bin/env python3
"""JSON-lines control server for the dashboard: inspect and steer the running
server — show status/connections/version, the live settings (the
connection caps, the log surface, the battery flag), the config reload (the
SIGHUP path), graceful shutdown. One command per line, one reply line. Every
request and reply is one JSON object per line (the stdlib json module): the
request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. TCP connections need a token
auth handshake when --control-token is set ({"cmd": "auth", "token": ...});
the unix socket relies on filesystem permissions plus the peer-cred
shortcut (root, the daemon's own user or --control-trust-uids skips the
handshake). With a token configured the wire is HMAC-signed: every command
and reply carries the full sha256 HMAC of its payload, keyed by the token
(common/wiresec.py) — a token-holding client verifies both directions; over
TCP the signed commands are mandatory. A second, read-only token
(--control-ops-token) authenticates into the show/clear verbs only — the
ops shift against the admin key, both audited."""
import hmac
import json
import logging
import os
import socket
import sys
import threading
import time

from common.cred import peer_uid
from common.human import secs
from common.version import version_string
from common.wiresec import verify_request_mac, sign_reply, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.options import control_command, grouped_rows, match_setting_path, describe_node
from common.config import parse_secret
from common.dump import SECRET_REMOVED, dump_filter
from common import dump as state
from .options import OPTIONS, SETTING_BY_NAME, describe_setting, SHOW_BY_LIVE, NODE_BY_NAME
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, LOG_LEVELS

logger = logging.getLogger('dashboard')

# The registry-driven bounds: the row's min/max (inclusive) are the one
# home for a knob's range — the branches parse and plumb, the row gates.
OPTION_BY_LIVE = {o.live: o for o in OPTIONS if o.live}
TYPED_CONVS = (int, float, str)

MAX_LINE = CONTROL_LINE_CAP   # the pre-auth line-buffer cap (drop past it)


class ControlServer:
    """JSON-lines control socket for the dashboard. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. A second, read-only token (ops_token) may be
    configured beside the admin token: it authenticates into the show/clear
    verbs only — no set/unset, no request reload, no reload, no shutdown
    (common/wiresec.py's roles). `stopper` is the graceful-stop callback
    shared with the signal handlers; it runs after the shutdown reply left
    the wire."""

    def __init__(self, httpd, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None, ops_token=None, ops_verbs=None, startup_values=None,
                 config_path=None, dump_path=None, restore_on_start=False, dump_key=None):
        self.httpd = httpd
        self.reloader = reloader         # request reload: re-resolve the config, apply, returns the summary
        self.audit = audit               # the SCR audit trail (common.audit), None = off
        self.token = token               # the TCP auth token (the admin role); None = no auth (the unix = the perms)
        self.ops_token = ops_token       # the read-only ops token (the ops role); None = off
        self.ops_verbs = frozenset(v.lower() for v in (ops_verbs or OPS_VERBS))   # the ops role's RBAC policy
        self.startup_values = startup_values or {}   # the set-grammar form of the startup options (show config)
        self.config_path = config_path   # the config script the daemon started from — the reload state lives beside it
        self.reload_pending = False      # a reload saved the state; the exec runs after the reply leaves the wire
        self.dump_path = dump_path or None   # the state dump file (the dump family)
        self.dump_restore = bool(restore_on_start)   # prospective-only: the START already chose
        self.dump_key = dump_key or None   # the dump seal key (startup-only: the reload re-exec re-resolves the same)
        self.metrics_srv = None          # set by the entry (the live metrics-server toggle)
        self.metrics_token = None        # the /metrics bearer token (the entry passes it)
        self.metrics_listen = None       # the /metrics bind address (the entry passes it)
        self.metrics_desc = 'off'        # the status/inspect one-liner
        self.is_unix = not isinstance(target, int)
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.trust_uids = trust_uids or frozenset()   # extra peer uids the unix socket trusts without the token
        self.stopper = stopper
        self.shutdown_pending = False
        self.defaults = defaults or {}   # setting -> configured startup value (what `unset` restores)
        self.overridden = set()          # settings changed live (`show status` carries the overridden= row)
        self.clients = set()             # the live control sockets (announce_exit)
        self.clients_lock = threading.Lock()
        self.started = time.monotonic()

    def start(self):
        self._restore_reload_state()   # a reload exec: the saved overrides re-apply once, the state file is consumed
        threading.Thread(target=self.serve, daemon=True).start()

    def describe(self):
        return 'unix:%s' % self.sockpath if self.is_unix else '127.0.0.1:%d' % self.port

    def cleanup(self):
        if self.is_unix and self.sockpath and os.path.exists(self.sockpath):
            try:
                os.unlink(self.sockpath)
            except OSError:
                pass

    def serve(self):
        srv = socket.socket(socket.AF_UNIX if self.is_unix else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if self.is_unix:
                if os.path.exists(self.sockpath):
                    logger.warning('control socket %s exists, replacing it', self.sockpath)
                    os.unlink(self.sockpath)
                srv.bind(self.sockpath)
                # the mode is not left to the umask: 0600 = owner only
                os.chmod(self.sockpath, 0o600)
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(('127.0.0.1', self.port))
            srv.listen(64)   # the backlog above the client limit: a connect burst must not RST
        except OSError as e:
            logger.error('control server cannot bind %s: %s (use --control-port 0 to disable it)', self.describe(), e)
            return
        logger.info('control server listening on %s%s',
                    self.describe(), (', token auth required on TCP' if self.token and not self.is_unix else '')
                    + (', read-only ops token accepted' if self.ops_token else ''))
        while True:
            try:
                client, addr = srv.accept()
                threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
            except (OSError, RuntimeError) as e:
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
        session."""
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
        status, _, text = reply.partition(' ')
        reply_obj = {'status': status, 'text': text}
        if key:
            reply_obj['mac'] = sign_reply(key, reply)
        return cmd, reply_obj, reply, role

    def announce_exit(self, reason, text=None):
        """The daemon is going down: send every connected control client a
        bye frame (the consoles print the notice and exit instead of trying
        to reconnect to a dead server) and close their sockets. `text`
        replaces the shutdown wording (the reload speaks of restarting)."""
        frame = (json.dumps({'status': 'bye',
                             'text': text or 'daemon-exit: the dashboard is shutting down (%s)' % reason},
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

    def command(self, cmd):
        cmd = cmd.strip()
        low = cmd.lower()
        if not low:
            return 'err empty command'
        if low.split()[0] in ('help', '?') and low != '?':
            args = cmd.split()[1:]
            if args and args[0].lower() == 'config':
                return self.config_mapping()
            if args and args[0].lower() == 'knobs':
                return self.knobs_dictionary()
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                return 'ok %s' % describe_setting(key)
            if args:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            return 'ok ' + self.command_help()
        if low == '?':
            return 'ok ' + self.command_help()
        if low == 'quit':
            return 'bye'
        if low == 'ping':                 # keep-alive from dashboard_ctl
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
                return 'err *** SECRET REMOVED *** is not a value — pass the secret by flag/env, or as file:<path>'
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
        if low == 'show version':
            return 'ok dashboard %s' % version_string()
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
                    return 'err %s is a secret — it never shows (pass it by flag/env, or as file:<path>)' % key
                word = SHOW_BY_LIVE.get(key)
                if word:
                    return self.command('show ' + word)   # a show command's report, by its word
                return 'ok %s=%s' % (key, self._get(key))
            if key is not None and rest:
                return 'err %s: unexpected %s' % (key, ' '.join(rest))
            if len(args) == 1 and args[0].lower() in NODE_BY_NAME:
                return 'ok %s' % describe_node(OPTIONS, args[0].lower())
            if len(args) == 1:
                return 'err unknown setting %s (try help)' % args[0].lower()
        if low == 'inspect':
            return self.inspect()
        if low == 'request reload':
            if not self.reloader:
                return 'err no reloader configured'
            try:
                return 'ok reloaded (%s)' % self.reloader()
            except Exception as e:
                return 'err reload failed: %s' % e
        if low == 'request dump':
            return self.dump_state()
        if low == 'request restore':
            return self.restore_state()
        if low == 'reload':
            return self.reload_daemon()
        if low == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        return 'err unknown command %r (try help)' % cmd

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, unset <setting>, inspect, '
                'show <setting|status|connections|version|config|knobs>, request reload')
        if self.dump_path:
            cmds += ', request dump, request restore'
        cmds += ', reload, shutdown, quit; '
        cmds += 'help <setting> describes it, help config maps every knob to its control command, '
        cmds += 'show knobs prints the full dictionary'
        return cmds

    def config_mapping(self):
        """The knob -> control-command mapper (help config): every option of
        the registry under its display group (the row's `group`, ungrouped
        rows headerless), with the command that changes it on a running dashboard —
        or the restart note when the knob is startup-only."""
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
        section, the control command that changes it and the secret marker."""
        from .options import OPTIONS
        from common.options import knob_dictionary
        return knob_dictionary(OPTIONS, who='the dashboard')

    def show_config(self):
        """The effective configuration as a set-grammar script (the output
        pipes straight back into a config file or through a ctl client).
        The secret knobs render as `set <name> *** SECRET REMOVED ***` (the
        value never does); the live overrides ride in as their current
        values."""
        from .options import OPTIONS, config_value
        from common.options import render_config_script
        cfg = dict(self.startup_values or {})
        values = {}
        for o in OPTIONS:
            if o.name == 'metrics-server':
                values[o.name] = 'on' if self.metrics_srv else None
                continue
            v = config_value(o.name, cfg)
            if v is not None:
                values[o.name] = v
            elif o.secret and o.flag and cfg.get(o.flag[2:].replace('-', '_')):
                values[o.name] = SECRET_REMOVED   # the knob renders, the value never does
        script = render_config_script(OPTIONS, values,
                                      comment='generated by show config — the secret knobs render as '
                                              '*** SECRET REMOVED ***, pass them by flag/env, or as file:<path>')
        return 'ok config\n' + script

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
        val = str(value).strip()

        def numi(text, label, what):
            try:
                return int(text)
            except ValueError:
                raise ValueError('%s must be %s, got %r' % (label, what, text))

        def num(text, label, what):
            try:
                return float(text)
            except ValueError:
                raise ValueError('%s must be %s, got %r' % (label, what, text))

        if key == 'max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            self.httpd.gate.max_total = v
            return '%d' % v
        if key == 'client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            self.httpd.RequestHandlerClass.timeout = v or None
            return secs(v)
        if key == 'max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            self.httpd.gate.max_per_ip = v
            return '%d' % v
        if key == 'log-access':
            if val not in ('on', 'off', 'true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError('log-access must be on or off')
            on = val in ('on', 'true', '1', 'yes')
            self.httpd.RequestHandlerClass.log_access = on
            return 'on' if on else 'off'
        if key == 'log-queries':
            if val not in ('on', 'off', 'true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError('log-queries must be on or off')
            on = val in ('on', 'true', '1', 'yes')
            self.httpd.RequestHandlerClass.log_queries = on
            return 'on' if on else 'off'
        if key == 'battery':
            if val not in ('on', 'off', 'true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError('battery must be on or off')
            on = val in ('on', 'true', '1', 'yes')
            self.httpd.RequestHandlerClass.battery = on
            return 'on' if on else 'off'
        if key == 'metrics-server':
            from .statics import DEFAULT_METRICS_CAPS
            if val in ('on', 'true', '1', 'yes'):
                if self.metrics_srv:
                    return 'on'
                if not self.metrics_token:
                    raise ValueError('the metrics endpoint serves the request counters: '
                                     'set --metrics-token first (or file:<path>) (F6 in docs/AUDIT.md)')
                from .metrics import MetricsServer, describe_metrics
                listen = self.metrics_listen
                caps = DEFAULT_METRICS_CAPS
                srv = MetricsServer(self.httpd, listen, token=self.metrics_token,
                                    max_clients=caps[0], client_timeout=caps[1], max_per_ip=caps[2])
                srv.start()
                self.metrics_srv = srv
                self.metrics_desc = describe_metrics(listen, self.metrics_token, caps[0], caps[2])
                return 'on'
            if val in ('off', 'false', '0', 'no'):
                if self.metrics_srv:
                    self.metrics_srv.stop()
                    self.metrics_srv = None
                    self.metrics_desc = 'off'
                return 'off'
            raise ValueError('metrics-server must be on or off')
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in LOG_LEVELS:
                raise ValueError('log-level must be one of %s' % ', '.join(LOG_LEVELS))
            logging.getLogger().setLevel(getattr(logging, lvl))
            return lvl
        if key == 'control/token':
            if val in ('off', 'none', ''):
                if not self.is_unix:
                    raise ValueError('the TCP control port needs its token (F5 in docs/AUDIT.md) — '
                                     'only the unix socket (the filesystem is the auth) may run tokenless')
                self.token = None
                return 'off'
            try:
                val = parse_secret(val, 'control/token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            if self.ops_token and hmac.compare_digest(val, self.ops_token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.token = val   # the rotation is live: the sessions re-auth, the macs verify against the new key
            return '<set>'
        if key == 'control/ops/token':
            if val in ('off', 'none', ''):
                self.ops_token = None   # the ops shift signs off; the admin role is untouched
                return 'off'
            try:
                val = parse_secret(val, 'control-ops-token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            if self.token and hmac.compare_digest(val, self.token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.ops_token = val
            return '<set>'
        if key == 'metrics/token':
            if not val or val in ('off', 'none', '0'):
                raise ValueError('metrics/token is mandatory while the endpoint serves (F6 in docs/AUDIT.md) '
                                 '— set the new token')
            try:
                val = parse_secret(val, 'metrics/token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            self.metrics_token = val
            if self.metrics_srv:
                self.metrics_srv.token = val   # the handler reads it per request — the swap is live
            from .metrics import describe_metrics
            caps = self._metrics_caps()
            self.metrics_desc = describe_metrics(self.metrics_listen, val, caps[0], caps[2])
            return '<set>'
        if key == 'dump/path':
            if val in ('off', 'none', ''):
                self.dump_path = None
                return 'off'
            self.dump_path = val   # request dump and the graceful shutdown write it from here on
            # the seal is opt-in: without dump/key the dump stays plaintext — say so, once, where the choice is made
            return val if self.dump_key else '%s (not sealed — set dump/key to encrypt at rest)' % val
        if key == 'dump/restore-on-start':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('dump/restore-on-start must be on or off')
            self.dump_restore = on   # prospective: the START behaviour this session already chose stands
            return 'on' if on else 'off'
        raise ValueError('unknown setting %s' % key)

    def _metrics_caps(self):
        """The caps the describe line renders: the running server's when it
        is up, the defaults otherwise."""
        from .statics import DEFAULT_METRICS_CAPS
        return ((self.metrics_srv.max_clients, self.metrics_srv.client_timeout, self.metrics_srv.max_per_ip)
                if self.metrics_srv else DEFAULT_METRICS_CAPS)

    def _get(self, key):
        h = self.httpd.RequestHandlerClass
        if key == 'max-clients':
            return '%d' % self.httpd.gate.max_total
        if key == 'client-timeout':
            ct = h.timeout
            return 'off' if not ct else secs(ct)
        if key == 'max-conn-per-ip':
            return '%d' % self.httpd.gate.max_per_ip
        if key == 'log-access':
            return 'on' if h.log_access else 'off'
        if key == 'log-queries':
            return 'on' if h.log_queries else 'off'
        if key == 'battery':
            return 'on' if h.battery else 'off'
        if key == 'metrics-server':
            return 'on' if self.metrics_srv else 'off'
        if key == 'control/token':
            return '<set>' if self.token else 'off'   # the secret never renders
        if key == 'control/ops/token':
            return '<set>' if self.ops_token else 'off'   # the secret never renders
        if key == 'metrics/token':
            return '<set>' if self.metrics_token else 'off'   # the secret never renders
        if key == 'dump/path':
            return self.dump_path or 'off'
        if key == 'dump/restore-on-start':
            return 'on' if self.dump_restore else 'off'
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

    def clear_overrides(self):
        """The config was re-applied (SIGHUP/request reload): nothing is
        live-overridden anymore."""
        self.overridden.clear()

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values. The
        secrets (control/token, the ops token, metrics/token) ride as
        *** SECRET REMOVED ***: the knob renders, the value never lands in
        the file — the restore skips the placeholder and keeps the
        secret's current value."""
        h = self.httpd.RequestHandlerClass
        raw = {
            'battery': 'on' if h.battery else 'off',
            'max-clients': self.httpd.gate.max_total,
            'client-timeout': h.timeout or 0,
            'max-conn-per-ip': self.httpd.gate.max_per_ip,
            'log-access': 'on' if h.log_access else 'off',
            'log-queries': 'on' if h.log_queries else 'off',
            'metrics-server': 'on' if self.metrics_srv else 'off',
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'dump/path': self.dump_path or 'off',
            'dump/restore-on-start': 'on' if self.dump_restore else 'off',
        }
        return dump_filter(self.overridden, raw, SETTING_BY_NAME)

    def apply_dump_settings(self, settings):
        """Re-apply the dumped overrides; returns (applied, failed-name-list).
        An unknown setting or a value the current config rejects is skipped,
        never fatal; a *** SECRET REMOVED *** placeholder (the dump renders
        an overridden secret's knob) is skipped and named — the secret keeps
        its current value."""
        applied, failed = 0, []
        for name, value in (settings or {}).items():
            if name not in SETTING_BY_NAME:
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

    # --- the whole-daemon reload (`reload`): the live overrides serialize to
    # a state file beside the config, the reply leaves the wire, the process
    # re-execs. The fresh daemon re-resolves the config file (the
    # startup-only knobs take their configured values) and re-applies the
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
        state.write_dump(self._reload_state_path(), settings, key=self.dump_key)
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
        startup-only knobs take their configured values — and start()
        re-applies the saved overrides once. The secrets never save (the
        dump rule): an overridden secret is named in the reply, to re-pass
        by flag/env, or as file:<path>."""
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
            msg += ' (%s: secret, not saved — re-pass by flag/env, or as file:<path>)' % ', '.join(lost)
        return msg

    def _exec_reload(self):
        """The reply is out (the session loop calls this after it): announce
        to the consoles and re-exec in place — the same argv re-resolves the
        config, the fresh daemon rebinds the control target (stale sockets
        are replaced) and restores the saved overrides."""
        if self.audit:
            self.audit.event('RELOAD', 'exec: the daemon re-execs (pid %d)' % os.getpid())
        self.announce_exit('reload', text='daemon-exit: the dashboard is reloading — '
                                          'the daemon restarts with the saved configuration')
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(0.2)   # let the bye frames drain
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def dump_state(self):
        """The write-behind: the live setting overrides to the configured
        dump path (the `request dump` command and the graceful shutdown) —
        sealed when dump/key is configured."""
        if not self.dump_path:
            return 'err no dump path configured (set dump/path or --dump-path)'
        settings = self.dump_settings()
        try:
            n = state.write_dump(self.dump_path, settings, key=self.dump_key)
        except (OSError, ValueError) as e:
            logger.error('control: the dump to %s failed: %s', self.dump_path, e)
            return 'err dump failed: %s' % e
        logger.info('control: state dumped to %s (%d setting(s)%s)', self.dump_path, n,
                    ', sealed' if self.dump_key else '')
        return 'ok dumped %d setting(s) to %s%s' % (n, self.dump_path, ' (sealed)' if self.dump_key else '')

    def restore_state(self):
        """Load a dump back: the setting overrides re-apply (a sealed dump
        restores only under the configured dump/key)."""
        if not self.dump_path:
            return 'err no dump path configured (set dump/path or --dump-path)'
        if not os.path.exists(self.dump_path):
            return 'err no dump at %s yet (run dump first)' % self.dump_path
        try:
            settings = state.read_dump(self.dump_path, key=self.dump_key)
            applied, failed = self.apply_dump_settings(settings)
        except ValueError as e:
            return 'err restore failed: %s' % e
        logger.info('control: state restored from %s (%d setting(s))', self.dump_path, applied)
        return 'ok restored %d setting(s) from %s%s' % (
            applied, self.dump_path,
            ' (%d skipped: %s)' % (len(failed), ', '.join(failed)) if failed else '')

    def shutdown_dump(self):
        """The graceful stop's write-behind: the overrides to the dump path
        (no reply — the log carries it; sealed when dump/key is set)."""
        if not self.dump_path:
            return
        try:
            n = state.write_dump(self.dump_path, self.dump_settings(), key=self.dump_key)
            logger.info('state dumped to %s (%d setting(s)%s)', self.dump_path, n,
                        ', sealed' if self.dump_key else '')
        except (OSError, ValueError) as e:
            logger.error('the shutdown dump to %s failed: %s', self.dump_path, e)

    def summary(self):
        """The compact state summary appended to the set/unset replies."""
        total, _ = self.httpd.gate.snapshot()
        return ('upstream=%s upstream_ok=%s clients=%d'
                % (self.httpd.RequestHandlerClass.upstream,
                   'ok' if self.httpd.RequestHandlerClass.upstream_ok else 'down', total))

    def connections_line(self):
        """The live HTTP clients (the static pages + the proxy): the gate's
        counters, one row per peer IP."""
        total, per_ip = self.httpd.gate.snapshot()
        if not total:
            return 'none'
        rows = ['%d active' % total]
        rows += ['%s: %d' % (ip, n) for ip, n in sorted(per_ip.items())]
        return '; '.join(rows)

    def status_report(self):
        """The status as a compact multi-field report: one stable key=value
        per line (scriptable)."""
        h = self.httpd.RequestHandlerClass
        gate = self.httpd.gate
        rows = [
            'upstream=%s' % h.upstream,
            'upstream_ok=%s' % ('yes' if h.upstream_ok else 'no'),
            'listen=%s:%d' % (self.httpd.server_address[0], self.httpd.server_address[1]),
            'control=%s' % self.describe(),
            'uptime=%s' % secs(time.monotonic() - self.started),
            'clients=%d' % gate.total(),
            'max_clients=%s' % (gate.max_total or 'none'),
            'client_timeout=%s' % (secs(h.timeout) if h.timeout else 'off'),
            'max_conn_per_ip=%s' % (gate.max_per_ip or 'none'),
            'log_access=%s' % ('on' if h.log_access else 'off'),
            'log_queries=%s' % ('on' if h.log_queries else 'off'),
            'battery=%s' % ('on' if h.battery else 'off'),
            'config_js=%s' % h.config_js,
            'overridden=%s' % (','.join(sorted(self.overridden)) or 'none'),
        ]
        return 'ok status\n' + '\n'.join(rows)

    def inspect(self):
        """One pretty dump of everything — the state, the counters, the caps,
        the proxy health: the baton for a bug report."""
        h = self.httpd.RequestHandlerClass
        total, per_ip = self.httpd.gate.snapshot()
        rows = [
            'version   dashboard %s' % version_string(),
            'upstream  %s (%s), proxy %s/*' % (h.upstream, 'ok' if h.upstream_ok else 'DOWN', h.prom_prefix or '/'),
            'listen    %s:%d, control %s' % (self.httpd.server_address[0], self.httpd.server_address[1],
                                             self.describe()),
            'pages     %s, config.js %s%s' % (h.static_dir, h.config_js,
                                              ', battery on' if h.battery else ''),
            'clients   %d active (limit %s, timeout %s, per-ip %s)'
            % (total, self.httpd.gate.max_total or 'none',
               secs(h.timeout) if h.timeout else 'off',
               self.httpd.gate.max_per_ip or 'none'),
            'auth      none, log access %s, log queries %s' % ('on' if h.log_access else 'off',
                                                               'on' if h.log_queries else 'off'),
            'audit     %s' % ('off' if self.audit is None
                              else (self.audit.path if self.audit.path != '-' else 'stdout')),
            'uptime    %s' % secs(time.monotonic() - self.started),
        ]
        return 'ok inspect\n' + '\n'.join(rows)
