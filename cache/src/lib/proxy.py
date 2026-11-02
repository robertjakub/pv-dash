#!/usr/bin/env python3
"""The proxy itself: poller thread, client handling, forwarding and reload (stdlib only)."""
import ipaddress
import logging
import socket
import struct
import threading
import time
from collections import deque

from .protocol import (MAX_COUNT, MAX_PDU, WRITE_FUNCS, GATEWAY_FAILED, ILLEGAL_FUNCTION,
                       ILLEGAL_VALUE, ILLEGAL_ADDRESS, ModbusError, DeviceError, recv_exact,
                       exception_frame, describe_write)
from .config import load_registers_file
from .cache import build_blocks, span

logger = logging.getLogger('modbus-cache')

# Diagnostics registers synthesized by the cache (never forwarded, never cached):
# 65000 magic, 65001 device flag, 65002 cache age in s (0xFFFF = no read yet),
# 65003 cache uptime in s.
DIAG_BASE = 65000
DIAG_COUNT = 4
DIAG_MAGIC = 0xCAFE
DIAG_MAX = 0xFFFF


class Proxy:
    def __init__(self, upstream, cache, read_delay=0.0, merge_gap=0, interval=10.0, registers_file=None, config=None):
        self.upstream = upstream
        self.cache = cache
        self.read_delay = read_delay
        self.merge_gap = merge_gap
        self.interval = interval
        self.registers_file = registers_file
        self.config = config or {}
        self.allow_write = bool(self.config.get('allow_write', False))
        self.log_access = bool(self.config.get('log_access', False))
        self.max_clients = max(0, int(self.config.get('max_clients') or 0))
        self.client_timeout = max(0.0, float(self.config.get('client_timeout') or 0.0))
        self.connect_acl = self.config.get('connect_acl')
        self.write_acl = self.config.get('write_acl')
        self.client_count = 0
        self.client_lock = threading.Lock()
        self.started = time.monotonic()
        self.last_ok = None
        self.poll_ok = False
        self.blocks = build_blocks(cache.ranges, merge_gap)
        self.generation = 0
        self.poll_wake = threading.Event()
        self.listen_sock = None

    def poll_loop(self):
        while True:
            try:
                self.poll_once()
            except Exception as e:
                logger.error('poll cycle crashed (%s), retrying next cycle', e)
            self.poll_wake.wait(self.interval)
            self.poll_wake.clear()

    def log_map(self):
        for start, count in self.cache.ranges:
            name = self.cache.names.get((start, count))
            logger.info('caching %d:%d%s', start, count, ' ' + name if name else '')
        logger.info('poll plan: %d block(s): %s', len(self.blocks),
                    ' '.join('%d:%d' % (b[0], b[1]) for b in self.blocks))

    def reload(self):
        """Apply a freshly resolved config + register map (SIGHUP)."""
        self.upstream.host = self.config['host']
        self.upstream.port = self.config['port']
        self.upstream.unit = self.config['unit']
        self.upstream.timeout = self.config['timeout']
        with self.upstream.lock:
            self.upstream.close()
        ranges, names = load_registers_file(self.config['registers_file'])
        self.read_delay = self.config['read_delay']
        self.merge_gap = self.config['merge_gap']
        self.interval = self.config['interval']
        self.allow_write = bool(self.config.get('allow_write', False))
        self.log_access = bool(self.config.get('log_access', False))
        self.max_clients = max(0, int(self.config.get('max_clients') or 0))
        self.client_timeout = max(0.0, float(self.config.get('client_timeout') or 0.0))
        self.connect_acl = self.config.get('connect_acl')
        self.write_acl = self.config.get('write_acl')
        self.cache.cache_ttl = self.config['cache_ttl']
        self.cache.update_map(ranges, names)
        self.generation += 1
        self.blocks = build_blocks(ranges, self.config['merge_gap'])
        logger.info('SIGHUP: reloaded %d range(s) from %s (upstream %s:%d unit %d, interval %gs, cache ttl %gs, merge gap %d)',
                    len(ranges), self.config['registers_file'], self.upstream.host, self.upstream.port,
                    self.upstream.unit, self.interval, self.cache.cache_ttl, self.merge_gap)
        self.log_map()
        self.poll_wake.set()

    def _name(self, leaf):
        return self.cache.names.get(leaf, '%d:%d' % leaf)

    def _leaf_ok(self, leaf):
        if leaf not in self.cache.range_ok:
            return
        if self.cache.range_ok[leaf] is False:
            logger.info('poll of %s recovered', self._name(leaf))
        self.cache.clear_leaf_error(leaf)
        self.cache.range_ok[leaf] = True

    def _leaf_fail(self, leaf, e):
        if leaf not in self.cache.range_ok:
            return
        if self.cache.range_ok[leaf] is not False:
            logger.warning('poll of %s failed (%s)%s', self._name(leaf), e,
                           ', serving cached values' if self.cache.regs else '')
        if isinstance(e, DeviceError):
            self.cache.set_leaf_error(leaf, e.code)
        self.cache.range_ok[leaf] = False

    def poll_once(self):
        generation = self.generation
        version = self.cache.map_version
        pending = deque(self.blocks)
        done = []
        ok = {}
        first = True
        while pending:
            start, count, leaves = pending.popleft()
            if first:
                first = False
            elif self.read_delay:
                time.sleep(self.read_delay)
            try:
                with self.upstream.lock:
                    words = self.upstream.read(start, count)
                self.cache.store(start, words, version)
                self.last_ok = time.monotonic()
                for leaf in leaves:
                    self._leaf_ok(leaf)
                    ok[leaf] = True
                done.append((start, count, leaves))
            except (ModbusError, OSError) as e:
                self.upstream.close()
                if len(leaves) > 1:
                    mid = len(leaves) // 2
                    left, right = leaves[:mid], leaves[mid:]
                    logger.debug('splitting block %d:%d after failure (%s)', start, count, e)
                    pending.appendleft((right[0][0], span(right), right))
                    pending.appendleft((left[0][0], span(left), left))
                else:
                    self._leaf_fail(leaves[0], e)
                    ok[leaves[0]] = False
                    done.append((start, count, leaves))
        if generation == self.generation:
            self.blocks = done
        self.poll_ok = any(ok.values())

    def _allowed(self, acl, ip):
        if acl is None:
            return True
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a.version == n.version and a in n for n in acl)

    def serve(self, host, port):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(128)
        self.listen_sock = srv
        logger.info('modbus-cache listening on %s:%d (client limit %s, client timeout %s)',
                    host, port,
                    self.max_clients or 'none', '%gs' % self.client_timeout if self.client_timeout else 'none')
        while True:
            client, addr = srv.accept()
            admitted = False
            try:
                if self.client_timeout:
                    client.settimeout(self.client_timeout)
                if not self._allowed(self.connect_acl, addr[0]):
                    logger.info('connection rejected: %s:%d not on the connect ACL', *addr[:2])
                elif self.max_clients and self.client_count >= self.max_clients:
                    logger.info('connection refused: client limit of %d reached (%s:%d)',
                                self.max_clients, *addr[:2])
                else:
                    with self.client_lock:
                        self.client_count += 1
                    admitted = True
                    threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
            except (OSError, RuntimeError) as e:
                logger.error('connection from %s:%d failed before serving (%s)', addr[0], addr[1], e)
                if admitted:
                    with self.client_lock:
                        self.client_count -= 1
                    admitted = False
            finally:
                if not admitted:
                    client.close()

    def handle(self, client, addr):
        access = logger.info if self.log_access else logger.debug
        access('client connected: %s:%d', *addr[:2])
        try:
            while True:
                head = recv_exact(client, 7)
                txn, proto, length, unit = struct.unpack('>HHHB', head)
                if not 2 <= length <= MAX_PDU + 2:
                    break
                pdu = recv_exact(client, length - 1)
                client.sendall(self.respond(txn, proto, unit, pdu, addr))
        except (ConnectionError, OSError) as e:
            access('client %s:%d disconnected (%s)', *addr[:2], e)
        except Exception as e:
            logger.error('error handling %s:%d: %s', *addr[:2], e)
        finally:
            with self.client_lock:
                self.client_count -= 1
            client.close()

    def respond(self, txn, proto, unit, pdu, addr):
        if proto != 0 or not pdu:
            return exception_frame(txn, proto, unit, pdu[0] if pdu else 3, ILLEGAL_VALUE)
        func = pdu[0]
        if func in WRITE_FUNCS:
            if not self.allow_write:
                desc = describe_write(pdu, unit) or 'FC%d, %d byte(s) (unit %d)' % (func, len(pdu) - 1, unit)
                logger.info('write: refused %s (write support disabled, enable with --allow-write)', desc)
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
            if not self._allowed(self.write_acl, addr[0]):
                desc = describe_write(pdu, unit) or 'FC%d, %d byte(s) (unit %d)' % (func, len(pdu) - 1, unit)
                logger.info('write: refused %s (client %s not on the write ACL)', desc, addr[0])
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
        if func == 3:
            if len(pdu) < 5:
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            addr, count = struct.unpack('>HH', pdu[1:5])
            if not 1 <= count <= MAX_COUNT or addr + count > 65536:
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            if addr >= DIAG_BASE:
                if addr + count <= DIAG_BASE + DIAG_COUNT:
                    return self._diag(txn, proto, unit, addr, count)
                return exception_frame(txn, proto, unit, func, ILLEGAL_ADDRESS)
            if addr < DIAG_BASE and addr + count > DIAG_BASE:
                return exception_frame(txn, proto, unit, func, ILLEGAL_ADDRESS)
            code = self.cache.failed_leaf(addr, count)
            if code is not None:
                logger.info('read: registers %d:%d served from last poll: the device rejects them (modbus exception %d)',
                            addr, count, code)
                return exception_frame(txn, proto, unit, func, code)
            if self.cache.covers(addr, count):
                logger.debug('read: registers %d:%d served from cache', addr, count)
                words = self.cache.words(addr, count)
                body = struct.pack('>BB', func, count * 2) + struct.pack('>%dH' % count, *words)
                return struct.pack('>HHHB', txn, proto, len(body) + 1, unit) + body
        return self.forward(txn, proto, unit, pdu)

    def _diag(self, txn, proto, unit, addr, count):
        """Answer a diagnostics read from live poller state (no device contact)."""
        now = time.monotonic()
        age = DIAG_MAX if self.last_ok is None else min(int(now - self.last_ok), DIAG_MAX)
        words = [DIAG_MAGIC,
                 1 if self.poll_ok else 0,
                 age,
                 min(int(now - self.started), DIAG_MAX)]
        vals = words[addr - DIAG_BASE:addr - DIAG_BASE + count]
        logger.debug('read: diag registers %d:%d (device %s, cache age %ss)',
                     addr, count, 'up' if words[1] else 'DOWN',
                     'n/a' if age == DIAG_MAX else age)
        body = struct.pack('>BB', 3, count * 2) + struct.pack('>%dH' % count, *vals)
        return struct.pack('>HHHB', txn, proto, len(body) + 1, unit) + body

    def forward(self, txn, proto, unit, pdu):
        desc = describe_write(pdu, unit)
        if desc:
            logger.info('write: %s', desc)
        is_read = bool(pdu) and pdu[0] == 3 and len(pdu) >= 5
        if is_read:
            addr, count = struct.unpack('>HH', pdu[1:5])
            logger.info('read: registers %d:%d not cached, polling the device', addr, count)
        frame = struct.pack('>HHHB', txn, proto, len(pdu) + 1, unit) + pdu
        try:
            with self.upstream.lock:
                resp = self.upstream.forward(frame)
            if resp[6:7] != bytes([unit & 0xFF]):
                raise ModbusError('reply from unit id %d, expected %d' % (resp[6], unit))
            body = resp[7:]
            if resp and body and body[0] == pdu[0] | 0x80:
                code = body[1] if len(body) > 1 else -1
                if desc:
                    logger.warning('write rejected by the device: %s (modbus exception %d)', desc, code)
                elif not is_read:
                    logger.info('forwarded FC%d rejected by the device (modbus exception %d)', pdu[0], code)
            if is_read:
                if body and body[0] == 3 and len(body) >= 2 and body[1] == count * 2:
                    self.cache.store(addr, struct.unpack('>%dH' % count, body[2:2 + count * 2]))
                    logger.info('read: registers %d:%d ok, cached %s', addr, count, self.cache.describe_ttl())
                elif body and body[0] == 3 | 0x80:
                    logger.warning('read: registers %d:%d rejected by the device (modbus exception %d)',
                                   addr, count, body[2] if len(body) > 2 else -1)
                else:
                    logger.warning('read: registers %d:%d unexpected response', addr, count)
            return resp
        except (ModbusError, OSError) as e:
            self.upstream.close()
            if desc:
                logger.warning('write failed: %s (%s)', desc, e)
            elif is_read:
                logger.warning('read: registers %d:%d failed (%s)', addr, count, e)
            return exception_frame(txn, proto, unit, pdu[0], GATEWAY_FAILED)
