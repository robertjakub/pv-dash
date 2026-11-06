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
import threading
import time

from common.cred import peer_uid
from common.human import secs
from common.version import version_string
from common.wiresec import verify_request_mac, sign_reply, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.options import control_command, grouped_rows, match_setting_path, describe_node
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
    verbs only — no set/unset, no request reload, no shutdown
    (common/wiresec.py's roles). `stopper` is the graceful-stop callback
    shared with the signal handlers; it runs after the shutdown reply left
    the wire."""

    def __init__(self, httpd, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None, ops_token=None, ops_verbs=None, startup_values=None):
        self.httpd = httpd
        self.reloader = reloader         # request reload: re-resolve the config, apply, returns the summary
        self.audit = audit               # the SCR audit trail (common.audit), None = off
        self.token = token               # the TCP auth token (the admin role); None = no auth (the unix = the perms)
        self.ops_token = ops_token       # the read-only ops token (the ops role); None = off
        self.ops_verbs = frozenset(v.lower() for v in (ops_verbs or OPS_VERBS))   # the ops role's RBAC policy
        self.startup_values = startup_values or {}   # the set-grammar form of the startup options (show config)
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

    def announce_exit(self, reason):
        """The daemon is going down: send every connected control client a
        bye frame (the consoles print the notice and exit instead of trying
        to reconnect to a dead server) and close their sockets."""
        frame = (json.dumps({'status': 'bye',
                             'text': 'daemon-exit: the dashboard is shutting down (%s)' % reason})
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
            if self.shutdown_pending and self.stopper:
                self.stopper('control command')   # reply is out, now really stop
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
            value = ' '.join(rest)
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
        if low == 'show config':
            return self.show_config()
        if low == 'show knobs':
            return self.knobs_dictionary()
        if low.startswith('show'):
            args = cmd.split()[1:]
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
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
        if low == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        return 'err unknown command %r (try help)' % cmd

    def command_help(self):
        """The one-line command reference."""
        return ('commands: set <setting> <value>, unset <setting>, inspect, '
                'show <setting|status|connections|version|config|knobs>, request reload, shutdown, quit; '
                'help <setting> describes it, help config maps every knob to its control command, '
                'show knobs prints the full dictionary')

    def config_mapping(self):
        """The knob -> control-command mapper (help config): every option of
        the registry under its display group (the row's `group`, else its
        section), with the command that changes it on a running dashboard —
        or the restart note when the knob is startup-only."""
        from .options import OPTIONS
        from common.options import section_title
        lines = ['ok config mapping']
        for key, rows in grouped_rows(OPTIONS):
            lines.append('# --- %s ---' % section_title(key))
            for o in rows:
                lines.append('%-24s %s' % (o.name, control_command(o)))
        return '\n'.join(lines)

    def knobs_dictionary(self):
        """The dictionary of all knobs (show knobs): every option of the
        registry under its section, with its flag, its env twin(s), its home
        section, the control command that changes it and the secret marker."""
        from .options import OPTIONS
        from common.options import knob_dictionary
        return knob_dictionary(OPTIONS, who='the dashboard')

    def show_config(self):
        """The effective configuration as a set-grammar script (the output
        pipes straight back into a config file or through a ctl client).
        Secrets never render; the live overrides ride in as their current
        values."""
        from .options import OPTIONS, config_value
        from common.options import render_config_script
        values = {}
        for o in OPTIONS:
            if o.name == 'metrics-server':
                values[o.name] = 'on' if self.metrics_srv else None
                continue
            v = config_value(o.name, self.startup_values)
            if v is not None:
                values[o.name] = v
        script = render_config_script(OPTIONS, values,
                                      comment='generated by show config — the secrets are hidden, pass them by flag/env/token-file')
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
                                     'set --metrics-token/--metrics-token-file first (F6 in docs/AUDIT.md)')
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
        raise ValueError('unknown setting %s' % key)

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
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        return '?'

    def clear_overrides(self):
        """The config was re-applied (SIGHUP/request reload): nothing is
        live-overridden anymore."""
        self.overridden.clear()

    def summary(self):
        """The compact state summary appended to the set/unset replies."""
        total, _ = self.httpd.gate.snapshot()
        return ('upstream=%s upstream=%s clients=%d'
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
