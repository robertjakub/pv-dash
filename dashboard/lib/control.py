#!/usr/bin/env python3
"""JSON-lines control server for the dashboard: inspect and steer the running
server — show status/connections/settings/version, the live settings (the
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
TCP the signed commands are mandatory."""
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
from common.wiresec import verify_request_mac, sign_reply, proof_tag
from .settings import SETTING_BY_NAME, SETTING_NAMES, describe_setting
from .statics import CONTROL_IDLE_TIMEOUT_S

logger = logging.getLogger('dashboard')

MAX_LINE = 1024 * 1024   # the pre-auth line-buffer cap (drop past it)


class ControlServer:
    """JSON-lines control socket for the dashboard. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. `stopper` is the graceful-stop callback shared
    with the signal handlers; it runs after the shutdown reply left the
    wire."""

    def __init__(self, httpd, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None):
        self.httpd = httpd
        self.reloader = reloader         # request reload: re-resolve the config, apply, returns the summary
        self.audit = audit               # the SCR audit trail (common.audit), None = off
        self.token = token               # the TCP auth token; None = no auth (the unix = the perms)
        self.is_unix = not isinstance(target, int)
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.trust_uids = trust_uids or frozenset()   # extra peer uids the unix socket trusts without the token
        self.stopper = stopper
        self.shutdown_pending = False
        self.defaults = defaults or {}   # setting -> configured startup value (what `unset` restores)
        self.overridden = set()          # settings changed live (`show settings` marks them with *)
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
            srv.listen(16)
        except OSError as e:
            logger.error('control server cannot bind %s: %s (use --control-port 0 to disable it)', self.describe(), e)
            return
        logger.info('control server listening on %s%s',
                    self.describe(), ', token auth required on TCP' if self.token and not self.is_unix else '')
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
        local systemd unit speaks without sharing the secret). TCP peers
        always need the token."""
        if not (self.token and self.is_unix):
            return False
        uid = peer_uid(client)
        if uid is None:
            return False
        if uid == 0 or uid == os.getuid() or uid in self.trust_uids:
            logger.debug('control client from %s: trusted peer uid %d, no token required', who, uid)
            return True
        logger.info('control client from %s: peer uid %d is not trusted, the token is required', who, uid)
        return False

    def framed(self, line, who, authed):
        """One wire frame in, one out: parse {"cmd": ...}, gate the TCP auth,
        verify the frame mac (the signed wire, common/wiresec.py), run the
        command, return (cmd, reply-obj, internal-reply)."""
        try:
            obj = json.loads(line) if line else {}
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or not isinstance(obj.get('cmd'), str):
            return '', {'status': 'err',
                        'text': 'malformed request: expected {"cmd": "<command>"} JSON'}, 'err malformed request'
        cmd = obj['cmd']
        if self.token and cmd.lower() != 'auth' and not authed:
            return cmd, {'status': 'err', 'text': 'authenticate first: {"cmd": "auth", "token": "..."}'}, \
                'err authenticate first'
        if cmd.lower() == 'auth':
            given = obj.get('token')
            if self.token and isinstance(given, str) and hmac.compare_digest(given, self.token):
                reply = 'ok authenticated'
                return 'auth', {'status': 'ok', 'text': 'authenticated', 'mac': sign_reply(self.token, reply)}, reply
            return 'auth', {'status': 'err', 'text': 'bad token'}, 'err bad token'
        if self.token and obj.get('mac') is None and not self.is_unix:
            return cmd, {'status': 'err',
                         'text': 'unsigned command rejected: TCP commands carry the hmac-sha256 of the command, keyed by the token'}, \
                'err unsigned command'
        if self.token and obj.get('mac') is not None and not verify_request_mac(self.token, cmd, obj.get('mac')):
            return cmd, {'status': 'err',
                         'text': 'the command mac does not verify (tampered or corrupted frame)'}, 'err bad command mac'
        reply = self.command(cmd)
        status, _, text = reply.partition(' ')
        reply_obj = {'status': status, 'text': text}
        if self.token:
            reply_obj['mac'] = sign_reply(self.token, reply)
        return cmd, reply_obj, reply

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
        authed = self.trusted_peer(client, who)
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
                cmd, obj, reply = self.framed(line.decode('utf-8', 'replace').strip(), who, authed)
                if cmd == 'auth':
                    ok = reply.startswith('ok')
                    if ok:
                        authed = True
                    elif self.audit:
                        self.audit.event('AUTH-FAIL', 'peer=%s' % who)
                elif self.audit and cmd.lower() != 'ping':
                    self.audit.event('COMMAND', "peer=%s '%s'%s -> %s"
                                     % (who, cmd, proof_tag(obj), reply.split(' ', 1)[0]))
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
            what = cmd[4:].strip().lower()
            if what and what in SETTING_BY_NAME:
                return 'ok %s' % describe_setting(what)
            if what:
                return 'err unknown setting %s (try help)' % what
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
        if low == 'show settings':
            return self.settings_report()
        if low == 'show version':
            return 'ok dashboard %s' % version_string()
        if low.startswith('show') and len(cmd.split()) == 2:
            what = cmd.split()[1].lower()
            if what in SETTING_BY_NAME:
                return 'ok %s=%s' % (what, self._get(what))
            return 'err unknown setting %s (try help)' % what
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
                'show <setting|status|connections|settings|version>, request reload, shutdown, quit; '
                'help <setting> describes it')

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
            if not 0 <= v <= 4096:
                raise ValueError('max-clients must be 0..4096')
            self.httpd.gate.max_total = v
            return '%d' % v
        if key == 'client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            if not 0 <= v <= 86400:
                raise ValueError('client-timeout must be 0..86400 seconds')
            self.httpd.RequestHandlerClass.timeout = v or None
            return secs(v)
        if key == 'max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            if not 0 <= v <= 4096:
                raise ValueError('max-conn-per-ip must be 0..4096')
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
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
                raise ValueError('log-level must be DEBUG, INFO, WARNING or ERROR')
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
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        return '?'

    def settings_report(self):
        """Every tunable setting with its live value: one key=value per line
        (scriptable). A live-overridden setting carries a `*` on the value —
        a SIGHUP re-applies the config and clears the markers."""
        return 'ok settings\n' + '\n'.join('%s=%s%s' % (k, self._get(k), '*' if k in self.overridden else '')
                                           for k in SETTING_NAMES)

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
