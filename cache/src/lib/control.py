#!/usr/bin/env python3
"""Line-protocol control server for modbus-cache: inspect and steer the
running proxy — show status/connections/cache, clear the cache, restart the
upstream session, graceful shutdown. One command per line, one reply per
line; the target is a TCP port (bound to 127.0.0.1) or a unix socket path."""
import logging
import os
import socket
import threading
import time

from .protocol import recv_exact

logger = logging.getLogger('modbus-cache')

COMMAND_HELP = 'commands: show status | show connections | show cache | clear cache | restart | shutdown | quit'


class ControlServer:
    """Control socket for the cache. The target is either a TCP port (bound
    to 127.0.0.1) or a unix socket path (stale files are replaced, unlinked
    on shutdown). `stopper` is the graceful-stop callback shared with the
    signal handlers; it runs after the shutdown reply left the wire."""

    def __init__(self, proxy, target, stopper=None):
        self.proxy = proxy
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
            srv.listen(4)
        except OSError as e:
            logger.error('control server cannot bind %s: %s (use --control-port 0 to disable it)', self.describe(), e)
            return
        logger.info('control server listening on %s (show status/connections/cache, clear cache, restart, shutdown)',
                    self.describe())
        while True:
            try:
                client, _ = srv.accept()
                threading.Thread(target=self.handle, args=(client,), daemon=True).start()
            except (OSError, RuntimeError) as e:
                logger.error('control accept failed (%s), retrying', e)
                time.sleep(0.1)

    def handle(self, client):
        logger.debug('control client connected')
        try:
            client.settimeout(300)
            buf = b''
            while True:
                chunk = recv_exact(client, 1) if b'\n' not in buf else b''
                buf += chunk
                if b'\n' not in buf:
                    continue
                line, buf = buf.split(b'\n', 1)
                cmd = line.decode('utf-8', 'replace').strip()
                reply = self.command(cmd)
                if reply is None:          # quit: no reply, just close
                    break
                logger.debug('control: %s -> %s', cmd, reply)
                client.sendall((reply + '\n').encode())
                if reply.startswith('bye'):
                    break
            if self.shutdown_pending and self.stopper:
                self.stopper('control command')   # reply is out, now really stop
        except (ConnectionError, OSError):
            pass
        except Exception as e:
            logger.error('control handler crashed (%s)', e)
        finally:
            logger.debug('control client disconnected')
            client.close()

    def command(self, cmd):
        cmd = cmd.strip()
        low = cmd.lower()
        if low in ('help', '?'):
            return 'ok ' + COMMAND_HELP
        if low == 'quit':
            return None
        if low == 'ping':                 # keep-alive from cache_cli
            return 'ok pong'
        if low == 'show status':
            return 'ok ' + self.status_line()
        if low == 'show connections':
            return 'ok connections ' + self.connections_line()
        if low == 'show cache':
            return 'ok ' + self.cache_line()
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
