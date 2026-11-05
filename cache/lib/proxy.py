#!/usr/bin/env python3
"""The proxy itself: poller thread, client handling, forwarding and reload (stdlib only)."""
import ipaddress
import logging
import socket
import struct
import threading
import time
from collections import deque

from common.protocol import ModbusError, exception_frame, recv_exact
from .protocol import DeviceError, describe_write
from .config import load_registers_file, load_selection
from .cache import build_blocks, span
from .statics import (MAX_COUNT, MAX_PDU, WRITE_FUNCS, GATEWAY_FAILED, ILLEGAL_FUNCTION,
                      ILLEGAL_VALUE, ILLEGAL_ADDRESS, DIAG_BASE, DIAG_COUNT, DIAG_MAGIC, DIAG_MAX,
                      REQUESTS_AUDIT_S)

logger = logging.getLogger('modbus-cache')

# Diagnostics registers synthesized by the cache (never forwarded, never cached;
# FC3 only — the input-register space has no synthetic block):
# 65000 magic, 65001 device flag, 65002 cache age in s (0xFFFF = no read yet),
# 65003 cache uptime in s.


def _write_target(pdu):
    """The register span a write request touches: (addr, count) for the
    known write function codes, None when the frame is too short to tell."""
    if len(pdu) < 5:
        return None
    func = pdu[0]
    if func in (5, 6, 22):          # single register (coil / register / mask-write)
        addr = struct.unpack('>H', pdu[1:3])[0]
        return addr, 1
    if func in (15, 16, 23):        # multiple registers/coils
        addr, count = struct.unpack('>HH', pdu[1:5])
        return addr, count
    return None


class Proxy:
    def __init__(self, upstream, cache, read_delay=0.0, merge_gap=0, interval=10.0, profile=None, config=None,
                 audit=None):
        self.upstream = upstream
        self.cache = cache
        self.read_delay = read_delay
        self.merge_gap = merge_gap
        self.interval = interval
        self.profile = profile
        self.config = config or {}
        self.audit = audit   # the CACHE audit trail (common.audit), None = off
        self.allow_write = bool(self.config.get('allow_write', False))
        self.write_ranges = self.config.get('write_registers')   # None = any register, () = none
        self.log_access = bool(self.config.get('log_access', False))
        self.max_clients = max(0, int(self.config.get('max_clients') or 0))
        self.client_timeout = max(0.0, float(self.config.get('client_timeout') or 0.0))
        self.requests_audit_s = max(0.0, float(self.config.get('requests_audit_s', REQUESTS_AUDIT_S)))
        self.connect_acl = self.config.get('connect_acl')
        self.write_acl = self.config.get('write_acl')
        self.no_cache = self.config.get('selection') == 'none'   # selection none: forward only
        self.poll_secs_last = 0.0        # the poll-cycle durations for /metrics
        self.poll_secs_max = 0.0
        self.poll_secs_sum = 0.0
        self.poll_count = 0
        self.client_count = 0
        self.client_lock = threading.Lock()
        self.clients = {}          # 'ip:port' -> {'since': monotonic, 'requests': n, 'audited': n}
        self.cache_hits = 0
        self.cache_misses = 0
        self.started = time.monotonic()
        self.last_ok = None
        self.poll_ok = False
        self.blocks = build_blocks(cache.ranges, merge_gap)
        self.block_stats = {}    # (fc, start, count) -> the uplink tally: attempts, latency, errors
        self.dump_path = None    # the state-dump file (write-behind); None = persistence off
        self.dump_interval = 0.0 # seconds between the automatic dumps; 0 = only the command/shutdown dumps
        self.dump_wake = threading.Event()
        self.generation = 0
        self.poll_wake = threading.Event()
        self.listen_sock = None
        self.listen_addr = None
        self.stopping = False

    def poll_loop(self):
        next_requests_audit = time.monotonic() + self.requests_audit_s
        while True:
            t0 = time.monotonic()
            try:
                self.poll_once()
            except Exception as e:
                logger.error('poll cycle crashed (%s), retrying next cycle', e)
            dur = time.monotonic() - t0
            self.poll_secs_last = dur
            self.poll_secs_max = max(self.poll_secs_max, dur)
            self.poll_secs_sum += dur
            self.poll_count += 1
            if self.requests_audit_s and self.audit:
                now = time.monotonic()
                if now >= next_requests_audit:
                    next_requests_audit = now + self.requests_audit_s
                    self.audit_requests()
            self.poll_wake.wait(self.interval)
            self.poll_wake.clear()

    def log_map(self):
        for fc, start, count in self.cache.ranges:
            name = self.cache.names.get((fc, start, count))
            logger.info('caching %s%d:%d%s', '' if fc == 3 else 'fc%d ' % fc, start, count,
                        ' ' + name if name else '')
        logger.info('poll plan: %d block(s): %s', len(self.blocks),
                    ' '.join('%s%d:%d' % ('' if fc == 3 else 'fc%d ' % fc, start, count)
                             for fc, start, count, _ in self.blocks))

    def load_map(self):
        """The register map from the current config: the profile + the
        selection filter (SIGHUP and the control's set profile/selection share
        this path). Raises ValueError on a bad file (never SystemExit)."""
        try:
            sel = self.config.get('selection')
            if sel == 'none':
                return [], {}, {}      # cache nothing: an empty map
            ranges, names, ttls = load_registers_file(self.config['profile'])
            if sel:
                ranges, names, ttls = load_selection(sel, names, ttls)
        except SystemExit as e:
            raise ValueError(str(e))
        return ranges, names, ttls

    def apply_map(self):
        """Swap the register map to the config's profile (+ selection)
        atomically: the poll plan rebuilds, the poller repopulates."""
        ranges, names, ttls = self.load_map()
        self.no_cache = self.config.get('selection') == 'none'
        self.cache.update_map(ranges, names, ttls)
        self.generation += 1
        self.blocks = build_blocks(ranges, self.merge_gap)
        logger.info('map reloaded: %d range(s) from %s%s, merge gap %d',
                    len(ranges), self.config['profile'],
                    ' (selection: %s)' % self.config['selection'] if self.config.get('selection') else '',
                    self.merge_gap)
        self.log_map()
        self.poll_wake.set()

    def reload(self):
        """Apply a freshly resolved config + register map (SIGHUP)."""
        self.upstream.host = self.config['host']
        self.upstream.port = self.config['port']
        self.upstream.unit = self.config['unit']
        self.upstream.timeout = self.config['timeout']
        with self.upstream.lock:
            self.upstream.close()
        ranges, names, ttls = self.load_map()
        self.no_cache = self.config.get('selection') == 'none'
        self.read_delay = self.config['read_delay']
        self.merge_gap = self.config['merge_gap']
        self.interval = self.config['interval']
        self.allow_write = bool(self.config.get('allow_write', False))
        self.write_ranges = self.config.get('write_registers')
        self.log_access = bool(self.config.get('log_access', False))
        self.max_clients = max(0, int(self.config.get('max_clients') or 0))
        self.client_timeout = max(0.0, float(self.config.get('client_timeout') or 0.0))
        self.requests_audit_s = max(0.0, float(self.config.get('requests_audit_s', REQUESTS_AUDIT_S)))
        self.connect_acl = self.config.get('connect_acl')
        self.write_acl = self.config.get('write_acl')
        self.cache.cache_ttl = self.config['cache_ttl']
        self.cache.update_map(ranges, names, ttls)
        self.generation += 1
        self.blocks = build_blocks(ranges, self.config['merge_gap'])
        logger.info('SIGHUP: reloaded %d range(s) from %s (upstream %s:%d unit %d, interval %gs, cache ttl %gs, merge gap %d)',
                    len(ranges), self.config['profile'], self.upstream.host, self.upstream.port,
                    self.upstream.unit, self.interval, self.cache.cache_ttl, self.merge_gap)
        self.log_map()
        self.poll_wake.set()

    def _name(self, leaf):
        return self.cache.names.get(leaf, '%s%d:%d' % ('' if leaf[0] == 3 else 'fc%d ' % leaf[0],
                                                       leaf[1], leaf[2]))

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

    def _block_stat(self, key, secs, err=None):
        """The `show uplink` tally of one poll-block attempt: the round-trip
        time, the outcome (DeviceError keeps its Modbus exception code)."""
        s = self.block_stats.setdefault(key, {'n': 0, 'ok_n': 0, 'fails': 0,
                                              'last': 0.0, 'sum': 0.0, 'max': 0.0,
                                              'last_err': None, 'last_code': None})
        s['n'] += 1
        s['last'] = secs
        s['max'] = max(s['max'], secs)
        if err is None:
            s['ok_n'] += 1
            s['sum'] += secs
            s['last_err'] = None
            s['last_code'] = None
        else:
            s['fails'] += 1
            s['last_err'] = str(err)
            s['last_code'] = err.code if isinstance(err, DeviceError) else None

    def poll_once(self):
        generation = self.generation
        version = self.cache.map_version
        pending = deque(self.blocks)
        done = []
        ok = {}
        first = True
        paced = True   # the read delay paces a healthy device; failures sweep unpaced
        while pending:
            fc, start, count, leaves = pending.popleft()
            if first:
                first = False
            elif self.read_delay and paced:
                time.sleep(self.read_delay)
            try:
                t0 = time.monotonic()
                with self.upstream.lock:
                    words = self.upstream.read(fc, start, count)
                self._block_stat((fc, start, count), time.monotonic() - t0)
                paced = True
                self.cache.store(fc, start, words, version)
                self.last_ok = time.monotonic()
                for leaf in leaves:
                    self._leaf_ok(leaf)
                    ok[leaf] = True
                done.append((fc, start, count, leaves))
            except (ModbusError, OSError) as e:
                paced = False
                self.upstream.close()
                if len(leaves) > 1:
                    mid = len(leaves) // 2
                    left, right = leaves[:mid], leaves[mid:]
                    logger.debug('splitting block %s%d:%d after failure (%s)',
                                 '' if fc == 3 else 'fc%d ' % fc, start, count, e)
                    pending.appendleft((fc, right[0][1], span(right), right))
                    pending.appendleft((fc, left[0][1], span(left), left))
                else:
                    self._block_stat((fc, start, count), time.monotonic() - t0, e)
                    self._leaf_fail(leaves[0], e)
                    ok[leaves[0]] = False
                    done.append((fc, start, count, leaves))
        if generation == self.generation:
            self.blocks = done
            live = {(fc, s, c) for fc, s, c, _ in done}
            self.block_stats = {k: v for k, v in self.block_stats.items() if k in live}
        self.poll_ok = any(ok.values())

    def audit_requests(self):
        """The per-client request tally (reads and writes alike), rate-limited:
        one REQUESTS event per client per period (the 'who is hammering the
        cache' evidence)."""
        now = time.monotonic()
        with self.client_lock:
            for key, entry in self.clients.items():
                delta = entry['requests'] - entry['audited']
                if delta <= 0:
                    continue
                entry['audited'] = entry['requests']
                self.audit.event('REQUESTS', 'peer=%s requests=%d (last %ds: %d)'
                                 % (key, entry['requests'], int(self.requests_audit_s), delta))

    def _allowed(self, acl, ip):
        """None = the ACL is off (everybody allowed); () = nobody allowed
        (the 'none' mode); otherwise the ip must land in one network."""
        if acl is None:
            return True
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a.version == n.version and a in n for n in acl)

    def _write_allowed(self, target):
        """The register-range allow-list: every touched register must land
        inside one of the configured ranges (None = any register; () = none
        writable — the 'none' mode)."""
        if self.write_ranges is None or target is None:
            return True
        addr, count = target
        return any(rs <= addr and addr + count <= rs + rc for rs, rc in self.write_ranges)

    def serve(self, host, port):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(128)
        self.listen_sock = srv
        self.listen_addr = (host, port)
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
        key = '%s:%d' % addr[:2]
        with self.client_lock:
            self.clients[key] = {'since': time.monotonic(), 'requests': 0, 'audited': 0}
        try:
            while True:
                head = recv_exact(client, 7)
                txn, proto, length, unit = struct.unpack('>HHHB', head)
                if not 2 <= length <= MAX_PDU + 2:
                    break
                pdu = recv_exact(client, length - 1)
                with self.client_lock:
                    entry = self.clients.get(key)
                    if entry:
                        entry['requests'] += 1
                client.sendall(self.respond(txn, proto, unit, pdu, addr))
        except (ConnectionError, OSError) as e:
            access('client %s:%d disconnected (%s)', *addr[:2], e)
        except Exception as e:
            logger.error('error handling %s:%d: %s', *addr[:2], e)
        finally:
            with self.client_lock:
                self.client_count -= 1
                entry = self.clients.pop(key, None)
            client.close()
            if self.audit and entry:
                self.audit.event('REQUESTS', 'peer=%s requests=%d connected=%ds'
                                 % (key, entry['requests'], int(time.monotonic() - entry['since'])))

    def respond(self, txn, proto, unit, pdu, addr):
        if proto != 0 or not pdu:
            return exception_frame(txn, proto, unit, pdu[0] if pdu else 3, ILLEGAL_VALUE)
        func = pdu[0]
        if func in WRITE_FUNCS:
            target = _write_target(pdu)
            if target is None:
                desc = describe_write(pdu, unit) or 'FC%d, %d byte(s) (unit %d)' % (func, len(pdu) - 1, unit)
                logger.info('write: refused %s (the frame is too short to carry a register address)', desc)
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s (the frame is too short to carry a register address)' % desc)
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            if not self.allow_write:
                desc = describe_write(pdu, unit) or 'FC%d, %d byte(s) (unit %d)' % (func, len(pdu) - 1, unit)
                logger.info('write: refused %s (write support disabled, enable with --allow-write)', desc)
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s (write support disabled)' % desc)
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
            if not self._allowed(self.write_acl, addr[0]):
                desc = describe_write(pdu, unit) or 'FC%d, %d byte(s) (unit %d)' % (func, len(pdu) - 1, unit)
                logger.info('write: refused %s (client %s not on the write ACL)', desc, addr[0])
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s (client %s not on the write ACL)' % (desc, addr[0]))
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
            if not self._write_allowed(target):
                desc = describe_write(pdu, unit) or 'FC%d (unit %d)' % (func, unit)
                logger.info('write: refused %s (registers outside the write allow-list %s)',
                            desc, self.describe_write_ranges())
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s (registers outside the write allow-list)' % desc)
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
        if func == 3 or func == 4:
            if len(pdu) < 5:
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            addr_, count = struct.unpack('>HH', pdu[1:5])
            if not 1 <= count <= MAX_COUNT or addr_ + count > 65536:
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            if func == 3 and addr_ >= DIAG_BASE:
                if addr_ + count <= DIAG_BASE + DIAG_COUNT:
                    return self._diag(txn, proto, unit, addr_, count)
                return exception_frame(txn, proto, unit, func, ILLEGAL_ADDRESS)
            if func == 3 and addr_ < DIAG_BASE and addr_ + count > DIAG_BASE:
                return exception_frame(txn, proto, unit, func, ILLEGAL_ADDRESS)
            code = self.cache.failed_leaf(func, addr_, count)
            if code is not None:
                logger.info('read: registers %d:%d served from last poll: the device rejects them (modbus exception %d)',
                            addr_, count, code)
                return exception_frame(txn, proto, unit, func, code)
            if self.cache.covers(func, addr_, count):
                self.cache_hits += 1
                logger.debug('read: fc%d registers %d:%d served from cache', func, addr_, count)
                words = self.cache.words(func, addr_, count)
                body = struct.pack('>BB', func, count * 2) + struct.pack('>%dH' % count, *words)
                return struct.pack('>HHHB', txn, proto, len(body) + 1, unit) + body
            self.cache_misses += 1
        return self.forward(txn, proto, unit, pdu)

    def describe_write_ranges(self):
        """The allow-list for humans: 'any', 'none' or the configured ranges."""
        if self.write_ranges is None:
            return 'any'
        if not self.write_ranges:
            return 'none'
        return ','.join('%d:%d' % r for r in self.write_ranges)

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
            if self.audit:
                self.audit.event('WRITE', desc)
        is_read = bool(pdu) and pdu[0] in (3, 4) and len(pdu) >= 5
        fc = addr = count = None
        if is_read:
            fc = pdu[0]
            addr, count = struct.unpack('>HH', pdu[1:5])
            logger.info('read: fc%d registers %d:%d not cached, polling the device', fc, addr, count)
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
                    if self.audit:
                        self.audit.event('WRITE-REJECTED', '%s (modbus exception %d)' % (desc, code))
                elif not is_read:
                    logger.info('forwarded FC%d rejected by the device (modbus exception %d)', pdu[0], code)
            if is_read:
                if body and body[0] == fc and len(body) >= 2 and body[1] == count * 2:
                    if not self.no_cache:
                        self.cache.store(fc, addr, struct.unpack('>%dH' % count, body[2:2 + count * 2]))
                    logger.info('read: fc%d registers %d:%d ok%s', fc, addr, count,
                                '' if not self.no_cache else ' (not cached: selection none)')
                elif body and body[0] == fc | 0x80:
                    logger.warning('read: fc%d registers %d:%d rejected by the device (modbus exception %d)',
                                   fc, addr, count, body[2] if len(body) > 2 else -1)
                else:
                    logger.warning('read: fc%d registers %d:%d unexpected response', fc, addr, count)
            elif desc and body and body[0] == pdu[0] and pdu[0] in (6, 16, 22, 23):
                # write-through invalidation: the device took the write, so the
                # cached words of the touched range are stale — drop exactly
                # them (per-register) and let the poller refill promptly
                target = _write_target(pdu)
                if target:
                    waddr, wcount = target
                    dropped = self.cache.invalidate(3, waddr, wcount)
                    if dropped:
                        self.poll_wake.set()
                        logger.info('write: invalidated %d cached word(s) at registers %d:%d, repolling',
                                    dropped, waddr, wcount)
            return resp
        except (ModbusError, OSError) as e:
            self.upstream.close()
            if desc:
                logger.warning('write failed: %s (%s)', desc, e)
                if self.audit:
                    self.audit.event('WRITE-FAILED', '%s (%s)' % (desc, e))
            elif is_read:
                logger.warning('read: fc%d registers %d:%d failed (%s)', fc, addr, count, e)
            return exception_frame(txn, proto, unit, pdu[0], GATEWAY_FAILED)
