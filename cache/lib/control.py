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

logger = logging.getLogger('modbus-cache')

COMMAND_HELP = 'commands: show status | show connections | show cache | show version | clear cache | restart | shutdown | quit'


class ControlServer:
    """JSON-lines control socket for the cache. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. `stopper` is the graceful-stop callback shared
    with the signal handlers; it runs after the shutdown reply left the
    wire."""

    def __init__(self, proxy, target, stopper=None, audit=None, token=None):
        self.proxy = proxy
        self.audit = audit               # the CACHE audit trail (lib.audit), None = off
        self.token = token               # the TCP auth token; None = no auth (the unix = the perms)
        self.is_unix = not isinstance(target, int)
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.stopper = stopper
        self.shutdown_pending = False

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
            client.settimeout(300)
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
        if low in ('help', '?'):
            return 'ok ' + COMMAND_HELP
        if low == 'quit':
            return 'bye'
        if low == 'ping':                 # keep-alive from cache_cli
            return 'ok pong'
        if low == 'show status':
            return 'ok ' + self.status_line()
        if low == 'show connections':
            return 'ok connections ' + self.connections_line()
        if low == 'show cache':
            return 'ok ' + self.cache_line()
        if low == 'show version':
            return 'ok modbus-cache %s' % version_string()
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

    def status_line(self):
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else '%ds ago' % max(0, int(now - p.last_ok))
        return ('status upstream=%s:%d unit=%d listen=%s:%d clients=%d uptime=%ds poll=%s last-poll=%s '
                'interval=%gs ttl=%gs ranges=%d map=v%d hits=%d misses=%d'
                % (p.upstream.host, p.upstream.port, p.upstream.unit, p.listen_addr[0], p.listen_addr[1],
                   p.client_count, int(now - p.started), 'ok' if p.poll_ok else 'down', age,
                   p.interval, p.cache.cache_ttl, len(p.cache.ranges), p.cache.map_version,
                   p.cache_hits, p.cache_misses))

    def connections_line(self):
        with self.proxy.client_lock:
            if not self.proxy.clients:
                return 'none'
            now = time.monotonic()
            return '; '.join('%s connected %ds requests %d' % (k, int(now - v['since']), v['requests'])
                             for k, v in sorted(self.proxy.clients.items()))

    def cache_line(self):
        c = self.proxy.cache
        with c.lock:
            words = len(c.regs)
            oldest = max((time.time() - t for t in c.ts.values()), default=None)
        failed = sum(1 for v in c.range_ok.values() if v is False)
        return ('cache %d range(s), %d word(s) cached%s, ttl %gs, map v%d, failed range(s) %d, hits %d, misses %d'
                % (len(c.ranges), words,
                   ', oldest %ds' % int(oldest) if oldest is not None else '',
                   c.cache_ttl, c.map_version, failed, self.proxy.cache_hits, self.proxy.cache_misses))
