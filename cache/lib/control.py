#!/usr/bin/env python3
"""JSON-lines control server for modbus-cache: inspect and steer the running
proxy — show status/connections/cache/version, clear the cache, restart the
upstream session, graceful shutdown. One command per line, one reply line.
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
import threading
import time

from common.version import version_string
from common.config import default_profile_path, resolve_profile_file
from common.cred import peer_uid, parse_trust_uids
from common.human import secs
from common.protocol import ModbusError
from common.wiresec import frame_mac, sign_reply, verify_request_mac, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.options import control_command
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, LOG_LEVELS
from .options import SETTING_BY_NAME, SETTING_NAMES, describe_setting
from .cache import build_blocks
from .config import parse_write_registers, parse_acl, acl_text, acl_summary, parse_selection
from .metrics import MetricsServer, describe_metrics
from . import persist

logger = logging.getLogger('modbus-cache')

MAX_LINE = CONTROL_LINE_CAP   # the pre-auth line-buffer cap (drop past it)


class ControlServer:
    """JSON-lines control socket for the cache. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. A second, read-only token (ops_token) may be
    configured beside the admin token: it authenticates into the show/clear
    verbs only — no set/unset, no request dump/restore, no restart, no
    shutdown (common/wiresec.py's roles). `stopper` is the graceful-stop
    callback shared with the signal handlers; it runs after the shutdown
    reply left the wire."""

    def __init__(self, proxy, target, stopper=None, audit=None, token=None, defaults=None, trust_uids=None,
                 socket_group=False, ops_token=None, ops_verbs=None):
        self.proxy = proxy
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
        self.overridden = set()          # settings changed live (`show settings` marks them with *)
        self.clients = set()             # the live control sockets (announce_exit)
        self.clients_lock = threading.Lock()

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
                # the mode is not left to the umask: 0600 = owner only,
                # 0660 with --control-socket-group (a local group shares it)
                os.chmod(self.sockpath, 0o660 if self.socket_group else 0o600)
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(('127.0.0.1', self.port))
            srv.listen(16)
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

    def announce_exit(self, reason):
        """The daemon is going down: send every connected control client a
        bye frame (the consoles print the notice and exit instead of trying
        to reconnect to a dead proxy) and close their sockets."""
        frame = (json.dumps({'status': 'bye',
                             'text': 'daemon-exit: the modbus-cache proxy is shutting down (%s)' % reason})
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

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, unset <setting>, inspect, show <setting|status|connections|cache|'
                'uplink|settings|version|config|knobs>')
        if self.proxy.dump_path:
            cmds += ', request dump [with-cache], request restore'
        cmds += ', clear cache, restart, shutdown, quit; help <setting> describes it, help config maps every knob to its control command, show knobs prints the full dictionary'
        return cmds

    def config_mapping(self):
        """The knob -> control-command mapper (help config): every option of
        the registry under its section, with the command that changes it on a
        running daemon — or the restart note when the knob is startup-only."""
        from .options import OPTIONS
        from common.options import SECTIONS, section_title
        lines = ['ok config mapping']
        for section, _title in SECTIONS:
            rows = [o for o in OPTIONS if o.section == section]
            if not rows:
                continue
            lines.append('# --- %s ---' % section_title(section))
            for o in rows:
                lines.append('%-24s %s' % (o.name, control_command(o)))
        return '\n'.join(lines)

    def knobs_dictionary(self):
        """The dictionary of all knobs (show knobs): every option of the
        registry under its section, with its flag, its env twin(s), its home
        section, the control command that changes it and the secret marker."""
        from .options import OPTIONS
        from common.options import knob_dictionary
        return knob_dictionary(OPTIONS, who='the modbus-cache')

    def show_config(self):
        """The effective configuration as a set-grammar script: every line a
        `set`, sectioned by the shared registry comments — the output pipes
        straight back into a config file (or through a ctl client). Secrets
        never render (the file/flag/env form is the documented way); the
        live overrides ride in as their current values."""
        from .options import OPTIONS, config_value
        from common.options import render_config_script
        cfg = dict(self.proxy.config or {})
        values = {}
        for o in OPTIONS:
            v = config_value(o.name, cfg)
            if v is not None:
                values[o.name] = v
            elif o.secret and (cfg.get(o.name.replace('-', '_')) or cfg.get(o.flag[2:].replace('-', '_') + '_file')):
                values[o.name] = None   # skipped, and noted below
        script = render_config_script(OPTIONS, values, comment='generated by show config — the secrets are hidden, pass them by flag/env/token-file')
        if any(o.secret and (cfg.get(o.name.replace('-', '_'))) for o in OPTIONS):
            script += '# (set <name> <secret> values are hidden here — the inline tokens do not render)\n'
        return 'ok config\n' + script

    def command(self, cmd):
        cmd = cmd.strip()
        low = cmd.lower()
        if low.split()[0] in ('help', '?') and low != '?':
            what = cmd[4:].strip().lower()
            if what == 'config':
                return self.config_mapping()
            if what == 'knobs':
                return self.knobs_dictionary()
            if what and what in SETTING_BY_NAME:
                if what == 'dump-interval' and not self.proxy.dump_path:
                    return 'err dump-interval needs a dump path (set --dump-path)'
                return 'ok %s' % describe_setting(what)
            if what:
                return 'err unknown setting %s (try help)' % what
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
            key = args[0].lower()
            if key not in self.defaults:
                return 'err unknown setting %s (try help)' % key
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
            key = args[0].lower()
            value = ' '.join(args[1:])
            if key not in SETTING_BY_NAME:
                return 'err unknown setting %s (try help)' % key
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
        if low == 'show cache all':
            return self.cache_all_report()
        if low == 'show uplink':
            return self.uplink_report()
        if low == 'show cache':
            return 'ok ' + self.cache_line()
        if low == 'show settings':
            return self.settings_report()
        if low == 'show version':
            return 'ok modbus-cache %s' % version_string()
        if low == 'show config':
            return self.show_config()
        if low == 'show knobs':
            return self.knobs_dictionary()
        if low.startswith('show') and len(cmd.split()) == 2:
            what = cmd.split()[1].lower()
            if what in SETTING_BY_NAME:
                if what == 'dump-interval' and not self.proxy.dump_path:
                    return 'err dump-interval needs a dump path (set --dump-path)'
                return 'ok %s=%s' % (what, self._get(what))
            return 'err unknown setting %s (try help)' % what
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
        if low == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        return 'err unknown command %r (try help)' % cmd

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

        if key == 'interval':
            v = num(val, 'interval', 'seconds')
            if not 0 < v <= 86400:
                raise ValueError('interval must be 0 < N <= 86400 seconds')
            p.interval = v
            p.poll_wake.set()
            return secs(v)
        if key == 'ttl':
            if val in ('off', 'none', '0'):
                p.cache.cache_ttl = 0
                return 'off'
            v = num(val, 'ttl', 'seconds or off')
            if not 0 <= v <= 86400 * 7:
                raise ValueError('ttl must be 0..604800 seconds')
            p.cache.cache_ttl = v
            return secs(v)
        if key == 'read-delay':
            v = num(val, 'read-delay', 'seconds')
            if not 0 <= v <= 60:
                raise ValueError('read-delay must be 0..60 seconds')
            p.read_delay = v
            return secs(v)
        if key == 'merge-gap':
            v = numi(val, 'merge-gap', 'registers')
            if not 0 <= v <= 100:
                raise ValueError('merge-gap must be 0..100 registers')
            p.merge_gap = v
            p.blocks = build_blocks(p.cache.ranges, v)
            p.poll_wake.set()
            return '%d' % v
        if key == 'allow-write':
            if val not in ('on', 'off'):
                raise ValueError('allow-write must be on|off')
            p.allow_write = val == 'on'
            return val
        if key == 'write-registers':
            p.write_ranges = parse_write_registers(val, 'write-registers')
            return p.describe_write_ranges()
        if key == 'max-clients':
            v = numi(val, 'max-clients', 'clients')
            if not 0 <= v <= 4096:
                raise ValueError('max-clients must be 0..4096')
            p.max_clients = v
            return '%d' % v
        if key == 'client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            if not 0 <= v <= 86400:
                raise ValueError('client-timeout must be 0..86400 seconds')
            p.client_timeout = v
            return secs(v)
        if key == 'max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            if not 0 <= v <= 4096:
                raise ValueError('max-conn-per-ip must be 0..4096')
            p.conn_gate.max_per_ip = v
            return '%d' % v
        if key == 'metrics-server':
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
            raise ValueError('metrics-server must be on or off')
        if key == 'requests-audit':
            if val in ('off', 'none', '0'):
                p.requests_audit_s = 0
                return 'off'
            v = num(val, 'requests-audit', 'seconds or off')
            if not 1 <= v <= 86400:
                raise ValueError('requests-audit must be 1..86400 seconds')
            p.requests_audit_s = v
            return secs(v)
        if key == 'dump-interval':
            if not p.dump_path:
                raise ValueError('dump-interval needs a dump path (set --dump-path)')
            if val in ('off', 'none', '0'):
                p.dump_interval = 0
                p.dump_wake.set()
                return 'off'
            v = num(val, 'dump-interval', 'seconds or off')
            if not 1 <= v <= 86400:
                raise ValueError('dump-interval must be 1..86400 seconds')
            p.dump_interval = v
            p.dump_wake.set()
            return secs(v)
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in LOG_LEVELS:
                raise ValueError('log-level must be one of %s' % ', '.join(LOG_LEVELS))
            logging.getLogger().setLevel(getattr(logging, lvl))
            return lvl
        if key == 'timeout':
            v = num(val, 'timeout', 'seconds')
            if not 0 < v <= 60:
                raise ValueError('timeout must be 0 < N <= 60 seconds')
            p.upstream.timeout = v
            p.config['timeout'] = v
            return secs(v)
        if key == 'connect-acl':
            acl = self._acl(val, 'connect-acl')
            p.connect_acl = acl
            p.config['connect_acl'] = acl
            return self._acl_text(acl)
        if key == 'write-acl':
            acl = self._acl(val, 'write-acl')
            p.write_acl = acl
            p.config['write_acl'] = acl
            return self._acl_text(acl)
        if key in ('profile', 'selection'):
            cfg = self._live_cfg()
            if key == 'profile':
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
            return cfg['profile'] if key == 'profile' else (cfg['selection'] or 'all')
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
                   connect_acl=p.connect_acl, write_acl=p.write_acl, timeout=p.upstream.timeout)
        return cfg

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
        if key == 'interval':
            return secs(p.interval)
        if key == 'ttl':
            return 'off' if not p.cache.cache_ttl else secs(p.cache.cache_ttl)
        if key == 'read-delay':
            return secs(p.read_delay)
        if key == 'merge-gap':
            return '%d' % p.merge_gap
        if key == 'allow-write':
            return 'on' if p.allow_write else 'off'
        if key == 'write-registers':
            return p.describe_write_ranges()
        if key == 'max-clients':
            return '%d' % p.max_clients
        if key == 'client-timeout':
            return 'none' if not p.client_timeout else secs(p.client_timeout)
        if key == 'max-conn-per-ip':
            return '%d' % p.conn_gate.max_per_ip
        if key == 'metrics-server':
            return 'on' if p.metrics_srv else 'off'
        if key == 'requests-audit':
            return 'off' if not p.requests_audit_s else secs(p.requests_audit_s)
        if key == 'dump-interval':
            return 'off' if not p.dump_interval else secs(p.dump_interval)
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        if key == 'timeout':
            return secs(p.upstream.timeout)
        if key == 'connect-acl':
            return self._acl_text(p.connect_acl)
        if key == 'write-acl':
            return self._acl_text(p.write_acl)
        if key == 'profile':
            return p.config.get('profile') or p.profile
        if key == 'selection':
            return p.config.get('selection') or 'all'
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
            'dump=%s' % ('off' if not p.dump_path else '%s every %s' % (
                p.dump_path, 'off' if not p.dump_interval else secs(p.dump_interval))),
            'profile=%s' % (cfg.get('profile') or p.profile),
            'selection=%s' % (cfg.get('selection') or 'all'),
            'metrics=%s' % getattr(p, 'metrics_desc', 'off'),
            'overridden=%s' % (','.join(sorted(self.overridden)) or 'none'),
        ]
        return 'ok status\n' + '\n'.join(rows)

    def settings_report(self):
        """Every tunable setting with its live value: one key=value per line
        (scriptable). A live-overridden setting carries a `*` on the value —
        a SIGHUP re-applies the config and clears the markers. The
        state-dump tunables show only when a dump path is configured."""
        names = [k for k in SETTING_NAMES if k != 'dump-interval' or self.proxy.dump_path]
        return 'ok settings\n' + '\n'.join('%s=%s%s' % (k, self._get(k), '*' if k in self.overridden else '')
                                           for k in names)

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
        return 'ok cache all\n' + '\n'.join(rows)

    @staticmethod
    def _bytes(n):
        return '%.1fkiB' % (n / 1024) if n >= 1024 else '%dB' % n

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values (a
        SIGHUP clears the override set — the dump follows)."""
        p = self.proxy
        raw = {
            'interval': p.interval, 'ttl': p.cache.cache_ttl, 'read-delay': p.read_delay,
            'merge-gap': p.merge_gap, 'allow-write': 'on' if p.allow_write else 'off',
            'write-registers': p.describe_write_ranges(), 'max-clients': p.max_clients,
            'client-timeout': p.client_timeout, 'max-conn-per-ip': p.conn_gate.max_per_ip,
            'metrics-server': 'on' if p.metrics_srv else 'off',
            'requests-audit': p.requests_audit_s,
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'profile': p.config.get('profile'), 'selection': p.config.get('selection') or 'all',
            'connect-acl': self._acl_text(p.connect_acl), 'write-acl': self._acl_text(p.write_acl),
            'timeout': p.upstream.timeout, 'dump-interval': p.dump_interval,
        }
        return {k: raw[k] for k in sorted(self.overridden)}

    def apply_dump_settings(self, settings):
        """Re-apply the dumped overrides; returns (applied, failed-name-list).
        An unknown setting or a value the current config rejects (a moved
        profile, a pruned ACL) is skipped, never fatal."""
        applied, failed = 0, []
        for name, value in (settings or {}).items():
            if name not in SETTING_BY_NAME:
                failed.append(name)
                continue
            try:
                self._apply(name, str(value))
                self.overridden.add(name)
                applied += 1
            except ValueError as e:
                failed.append('%s (%s)' % (name, e))
        return applied, failed

    def dump_state(self, with_cache):
        """The write-behind: the live setting overrides and — when
        with_cache (the `request dump with-cache` command, the
        `--dump-with-cache` default or the dump-interval loop) — the cached
        words (+ stamps), to the configured dump path."""
        path = self.proxy.dump_path
        if not path:
            return 'err no dump path configured (set --dump-path)'
        settings = self.dump_settings()
        try:
            n = persist.write_dump(path, self.proxy.cache, settings, with_cache=with_cache)
        except (OSError, ValueError) as e:
            logger.error('control: the dump to %s failed: %s', path, e)
            return 'err dump failed: %s' % e
        logger.info('control: state dumped to %s (%d word(s), %d setting(s), %s)', path, n,
                    len(settings), 'with cache' if with_cache else 'settings only')
        return 'ok dumped %d word(s), %d setting(s) to %s' % (n, len(settings), path)

    def restore_state(self):
        """Load a dump back: the words (+ their original stamps, so the
        freshness carries over) land in the cache — only what the current
        register map still covers — and the setting overrides re-apply."""
        path = self.proxy.dump_path
        if not path:
            return 'err no dump path configured (set --dump-path)'
        if not os.path.exists(path):
            return 'err no dump at %s yet (run dump first)' % path
        try:
            words, stamps, settings = persist.read_dump(path)
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
