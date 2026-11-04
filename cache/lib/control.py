#!/usr/bin/env python3
"""JSON-lines control server for modbus-cache: inspect and steer the running
proxy — show status/connections/cache/version, clear the cache, restart the
upstream session, graceful shutdown. One command per line, one reply line.
Every request and reply is one JSON object per line (the stdlib json
module): the request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. TCP connections need a token
auth handshake when --control-token is set ({"cmd": "auth", "token": ...});
the unix socket relies on filesystem permissions instead."""
import hmac
import json
import logging
import os
import socket
import threading
import time

from .version import version_string
from .statics import CONTROL_IDLE_TIMEOUT_S
from .settings import SETTING_BY_NAME, SETTING_NAMES, describe_setting
from .cache import build_blocks
from .config import parse_write_registers

logger = logging.getLogger('modbus-cache')

COMMAND_HELP = ('commands: set <setting> <value>, unset <setting>, inspect, show <setting|status|connections|cache|'
                'settings|version>, clear cache, restart, shutdown, quit; help <setting> describes it')


class ControlServer:
    """JSON-lines control socket for the cache. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. `stopper` is the graceful-stop callback shared
    with the signal handlers; it runs after the shutdown reply left the
    wire."""

    def __init__(self, proxy, target, stopper=None, audit=None, token=None, defaults=None):
        self.proxy = proxy
        self.audit = audit               # the CACHE audit trail (lib.audit), None = off
        self.token = token               # the TCP auth token; None = no auth (the unix = the perms)
        self.is_unix = not isinstance(target, int)
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.stopper = stopper
        self.shutdown_pending = False
        self.defaults = defaults or {}   # setting -> configured startup value (what `unset` restores)

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
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(('127.0.0.1', self.port))
            srv.listen(16)
        except OSError as e:
            logger.error('control server cannot bind %s: %s (use --control-port 0 to disable it)', self.describe(), e)
            return
        logger.info('control server listening on %s (show status/connections/cache, clear cache, restart, shutdown)%s',
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

    def framed(self, line, who, authed):
        """One wire frame in, one out: parse {"cmd": ...}, gate the TCP auth,
        run the command, return (cmd, reply-obj, internal-reply). The text of
        a multi-line reply keeps its embedded newlines; the '.' terminator of
        the internal form is stripped (the JSON frame needs no framing)."""
        try:
            obj = json.loads(line) if line else {}
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or not isinstance(obj.get('cmd'), str):
            return '', {'status': 'err',
                        'text': 'malformed request: expected {"cmd": "<command>"} JSON'}, 'err malformed request'
        cmd = obj['cmd']
        if self.token and not self.is_unix and cmd.lower() != 'auth' and not authed:
            return cmd, {'status': 'err', 'text': 'authenticate first: {"cmd": "auth", "token": "..."}'}, \
                'err authenticate first'
        if cmd.lower() == 'auth':
            given = obj.get('token')
            if self.token and isinstance(given, str) and hmac.compare_digest(given, self.token):
                return 'auth', {'status': 'ok', 'text': 'authenticated'}, 'ok authenticated'
            return 'auth', {'status': 'err', 'text': 'bad token'}, 'err bad token'
        reply = self.command(cmd)
        if reply is None:              # quit: no reply, just close
            return cmd, None, 'bye'
        status, _, text = reply.partition(' ')
        return cmd, {'status': status, 'text': text}, reply

    def handle(self, client, addr):
        who = self.peer(addr)
        logger.debug('control client connected from %s', who)
        authed = False
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
                    self.audit.event('COMMAND', "peer=%s '%s' -> %s" % (who, cmd, reply.split(' ', 1)[0]))
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
            client.close()

    def command(self, cmd):
        cmd = cmd.strip()
        low = cmd.lower()
        if low.split()[0] in ('help', '?') and low != '?':
            what = cmd[4:].strip().lower()
            if what and what in SETTING_BY_NAME:
                return 'ok %s' % describe_setting(what)
            if what:
                return 'err unknown setting %s (try help)' % what
            return 'ok ' + COMMAND_HELP
        if low == '?':
            return 'ok ' + COMMAND_HELP
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
            logger.info('control: set %s=%s', key, shown)
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if low == 'show status':
            return self.status_report()
        if low == 'show connections':
            return 'ok connections ' + self.connections_line()
        if low == 'show cache':
            return 'ok ' + self.cache_line()
        if low == 'show settings':
            return self.settings_report()
        if low == 'show version':
            return 'ok modbus-cache %s' % version_string()
        if low.startswith('show') and len(cmd.split()) == 2:
            what = cmd.split()[1].lower()
            if what in SETTING_BY_NAME:
                return 'ok %s=%s' % (what, self._get(what))
            return 'err unknown setting %s (try help)' % what
        if low == 'inspect':
            return self.inspect()
        if low == 'clear cache':
            dropped = self.proxy.cache.clear()
            self.proxy.poll_wake.set()
            logger.info('control: cache cleared (%d register word(s) dropped), repolling now', dropped)
            return 'ok cache cleared (%d register word(s) dropped), repolling now' % dropped
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
            return '%gs' % v
        if key == 'ttl':
            if val in ('off', 'none', '0'):
                p.cache.cache_ttl = 0
                return 'off'
            v = num(val, 'ttl', 'seconds or off')
            if not 0 <= v <= 86400 * 7:
                raise ValueError('ttl must be 0..604800 seconds')
            p.cache.cache_ttl = v
            return '%gs' % v
        if key == 'read-delay':
            v = num(val, 'read-delay', 'seconds')
            if not 0 <= v <= 60:
                raise ValueError('read-delay must be 0..60 seconds')
            p.read_delay = v
            return '%gs' % v
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
            return '%gs' % v
        if key == 'reads-audit':
            if val in ('off', 'none', '0'):
                p.reads_audit_s = 0
                return 'off'
            v = num(val, 'reads-audit', 'seconds or off')
            if not 1 <= v <= 86400:
                raise ValueError('reads-audit must be 1..86400 seconds')
            p.reads_audit_s = v
            return '%gs' % v
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
                raise ValueError('log-level must be DEBUG, INFO, WARNING or ERROR')
            logging.getLogger().setLevel(getattr(logging, lvl))
            return lvl
        raise ValueError('unknown setting %s' % key)

    def _get(self, key):
        p = self.proxy
        if key == 'interval':
            return '%gs' % p.interval
        if key == 'ttl':
            return 'off' if not p.cache.cache_ttl else '%gs' % p.cache.cache_ttl
        if key == 'read-delay':
            return '%gs' % p.read_delay
        if key == 'merge-gap':
            return '%d' % p.merge_gap
        if key == 'allow-write':
            return 'on' if p.allow_write else 'off'
        if key == 'write-registers':
            return p.describe_write_ranges()
        if key == 'max-clients':
            return '%d' % p.max_clients
        if key == 'client-timeout':
            return '%gs' % p.client_timeout
        if key == 'reads-audit':
            return 'off' if not p.reads_audit_s else '%gs' % p.reads_audit_s
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        return '?'

    def status_report(self):
        """The status as a compact multi-field report: one stable key=value
        per line (scriptable)."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else '%ds' % max(0, int(now - p.last_ok))
        fc4 = sum(1 for r in p.cache.ranges if r[0] == 4)
        cfg = p.config or {}
        rows = [
            'upstream=%s:%d' % (p.upstream.host, p.upstream.port),
            'unit=%d' % p.upstream.unit,
            'listen=%s:%d' % (p.listen_addr[0], p.listen_addr[1]),
            'control=%s' % self.describe(),
            'uptime=%d' % int(now - p.started),
            'poll=%s' % ('ok' if p.poll_ok else 'down'),
            'last_poll=%s' % age,
            'interval=%gs' % p.interval,
            'ttl=%gs' % p.cache.cache_ttl,
            'merge_gap=%d' % p.merge_gap,
            'ranges=%d' % len(p.cache.ranges),
            'fc4_ranges=%d' % fc4,
            'map_version=%d' % p.cache.map_version,
            'hits=%d' % p.cache_hits,
            'misses=%d' % p.cache_misses,
            'clients=%d' % p.client_count,
            'max_clients=%s' % (p.max_clients or 'none'),
            'client_timeout=%s' % ('%gs' % p.client_timeout if p.client_timeout else 'none'),
            'writes=%s' % ('enabled' if p.allow_write else 'disabled'),
            'write_acl=%s' % ('any' if p.write_acl is None else '%d network(s)' % len(p.write_acl)),
            'write_allow_list=%s' % p.describe_write_ranges(),
            'reads_audit=%s' % ('off' if not p.reads_audit_s else '%gs' % p.reads_audit_s),
            'profile=%s' % (cfg.get('profile') or p.profile),
            'selection=%s' % (cfg.get('selection') or 'all'),
        ]
        return 'ok status\n' + '\n'.join(rows)

    def settings_report(self):
        """Every tunable setting with its live value: one key=value per line
        (scriptable)."""
        return 'ok settings\n' + '\n'.join('%s=%s' % (k, self._get(k)) for k in SETTING_NAMES)

    def summary(self):
        """The compact state summary appended to the set/unset replies."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else '%ds' % max(0, int(now - p.last_ok))
        return ('upstream=%s:%d interval=%gs ttl=%gs poll=%s last-poll=%s hits=%d misses=%d clients=%d'
                % (p.upstream.host, p.upstream.port, p.interval, p.cache.cache_ttl,
                   'ok' if p.poll_ok else 'down', age, p.cache_hits, p.cache_misses, p.client_count))

    def connections_line(self):
        with self.proxy.client_lock:
            if not self.proxy.clients:
                return 'none'
            now = time.monotonic()
            return '; '.join('%s connected %ds requests %d' % (k, int(now - v['since']), v['requests'])
                             for k, v in sorted(self.proxy.clients.items()))

    def inspect(self):
        """One pretty dump of everything — the state, the map, the counters,
        the write gate: the baton for a bug report. Multi-line reply."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else '%ds ago' % max(0, int(now - p.last_ok))
        fc3 = sum(1 for r in p.cache.ranges if r[0] == 3)
        fc4 = len(p.cache.ranges) - fc3
        cfg = p.config or {}
        rows = [
            'version   modbus-cache %s' % version_string(),
            'upstream  %s:%d unit %d, last poll %s%s' % (p.upstream.host, p.upstream.port,
                                                         p.upstream.unit, age,
                                                         '' if p.poll_ok else ' (FAILING)'),
            'listen    %s:%d, control %s' % (p.listen_addr[0], p.listen_addr[1], self.describe()),
            'profile   %s%s, map v%d' % (cfg.get('profile') or p.profile,
                                         ' (selection: %s)' % cfg['selection'] if cfg.get('selection') else '',
                                         p.cache.map_version),
            'cache     %d range(s) (fc3 %d, fc4 %d), %d word(s), oldest %s, ttl %gs, failed range(s) %d'
            % (len(p.cache.ranges), fc3, fc4, len(p.cache.regs),
               self._oldest() or 'n/a', p.cache.cache_ttl,
               sum(1 for v in p.cache.range_ok.values() if v is False)),
            'poll plan %d block(s): %s' % (len(p.blocks),
                                           ' '.join('%s%d:%d' % ('' if fc == 3 else 'fc%d ' % fc, s, c)
                                                    for fc, s, c, _ in p.blocks)),
            'counters  hits %d, misses %d, clients %d (limit %s, timeout %s)'
            % (p.cache_hits, p.cache_misses, p.client_count,
               p.max_clients or 'none', '%gs' % p.client_timeout if p.client_timeout else 'none'),
            'writes    %s, acl %s, allow-list %s'
            % ('ENABLED' if p.allow_write else 'disabled',
               'any' if p.write_acl is None else '%d network(s)' % len(p.write_acl),
               p.describe_write_ranges()),
            'audit     %s%s' % ('off' if p.audit is None else (p.audit.path if p.audit.path != '-' else 'stdout'),
                                ', reads accounting every %gs' % p.reads_audit_s if p.audit and p.reads_audit_s else ''),
            'uptime    %ds' % int(now - p.started),
        ]
        return 'ok inspect\n' + '\n'.join(rows)

    def _oldest(self):
        with self.proxy.cache.lock:
            oldest = max((time.time() - t for t in self.proxy.cache.ts.values()), default=None)
        return '%ds' % int(oldest) if oldest is not None else None

    def cache_line(self):
        c = self.proxy.cache
        with c.lock:
            words = len(c.regs)
            fc4 = sum(1 for r in c.ranges if r[0] == 4)
        failed = sum(1 for v in c.range_ok.values() if v is False)
        return ('cache %d range(s)%s, %d word(s) cached%s, ttl %gs, map v%d, failed range(s) %d, hits %d, misses %d'
                % (len(c.ranges), ' (fc4 %d)' % fc4 if fc4 else '', words,
                   ', oldest %s' % (self._oldest() or 'n/a'),
                   c.cache_ttl, c.map_version, failed, self.proxy.cache_hits, self.proxy.cache_misses))
