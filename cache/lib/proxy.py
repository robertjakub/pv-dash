#!/usr/bin/env python3
"""The proxy itself: poller thread, client handling, forwarding and reload (stdlib only)."""
import logging
import struct
import threading
import time
from collections import deque

from common.modbus import (DeviceError, ModbusError, describe_fc, describe_write,
                           exception_frame, frame, pack_bits, serve_modbus,
                           unit_in_range, unpack_bits, write_kv, write_shape_error,
                           write_target)
from common.runtime.audit import audit_quote
from common.serve.connlimit import ConnGate
from .config import (IPGate, acl_admits, acl_file_warn, acl_gate_summary, acl_value_text,
                     load_profile_write_gate, load_write_gate_file, compile_write_acl,
                     load_registers_file, load_selection, parse_acl)
from .cache import build_blocks, span
from .statics import (MAX_COUNT, MAX_PDU, MAX_BITS, READ_FUNCS, BIT_READ_FUNCS, WRITE_FUNCS,
                      GATEWAY_FAILED, ILLEGAL_FUNCTION,
                      ILLEGAL_VALUE, ILLEGAL_ADDRESS, DIAG_BASE, DIAG_COUNT, DIAG_MAGIC, DIAG_MAX,
                      REQUESTS_AUDIT_S)

logger = logging.getLogger('modbus-cache')

# Diagnostics registers synthesized by the cache (never forwarded, never cached;
# FC3 only — the other address spaces have no synthetic block):
# 65000 magic, 65001 device flag, 65002 cache age in s (0xFFFF = no read yet),
# 65003 cache uptime in s.


def _space_name(fc):
    """The log spelling of a read space: coils (FC1), discrete inputs
    (FC2), registers (FC3/FC4 — the historical wording the logs and the
    regtests quote)."""
    if fc == 1:
        return 'coils'
    if fc == 2:
        return 'discrete inputs'
    return 'registers'


def _read_shape(fc, count):
    """The data-byte count a valid FC1-FC4 reply carries for `count`
    addresses: registers take two bytes each, bits pack 8 per byte."""
    if fc in BIT_READ_FUNCS:
        return (count + 7) // 8
    return count * 2



def _write_desc(func, pdu, unit):
    """The write frame's one-line description: the shared describer's
    words, else the fc + payload size."""
    return describe_write(pdu, unit) or \
        ('%s, %d byte(s) (unit %d)' % (describe_fc(func), len(pdu) - 1, unit)
         if pdu else '%s (unit %d)' % (describe_fc(func), unit))


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
        self.write_registers = self.config.get('write_registers')   # the knob: None = any, () = none, 'profile' = the profile's acl, 'file:<path>' = the standalone acl file
        self.write_gate_rules = None   # the profile/file gate's parsed rules (the write/registers/table show report), None = not in profile/file mode
        self.write_gate_warn = None    # the acl file's permission warning (set on a resolved file: gate, None otherwise)
        try:
            self.write_ranges = self._resolve_write_ranges(self.write_registers)   # the effective gate
        except ValueError as e:
            raise SystemExit(str(e))
        self.log_access = bool(self.config.get('log_access', False))
        self.max_clients = max(0, int(self.config.get('max_clients') or 0))
        self.client_timeout = max(0.0, float(self.config.get('client_timeout') or 0.0))
        self.conn_gate = ConnGate(0, max(0, int(self.config.get('max_conn_per_ip') or 0)))
        self.requests_audit_s = max(0.0, float(self.config.get('requests_audit_s', REQUESTS_AUDIT_S)))
        self.connect_acl_warn = None   # the acl/connect file's permission warning (the stash, None = no warning standing)
        self.write_acl_warn = None     # the acl/write file's warning
        self.metrics_acl_warn = None   # the metrics/acl file's warning
        try:
            self.connect_acl = self._resolve_ip_acl(self.config.get('connect_acl'), 'connect')
            self.write_acl = self._resolve_ip_acl(self.config.get('write_acl'), 'write')
            self.metrics_acl = self._resolve_ip_acl(self.config.get('metrics_acl'), 'metrics')
        except ValueError as e:
            raise SystemExit(str(e))   # the start refuses clean (the SIGHUP watcher keeps the previous settings)
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
        self.write_refused = 0   # the WRITE-REFUSED events, exported on /metrics (F16's alert pack watches the burst)
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
        """The start/reload map log: the generated poll pools, one line
        each — not one line per cached range."""
        logger.info('poll plan: %d pool(s) over %d range(s)',
                    len(self.blocks), len(self.cache.ranges))
        for i, (fc, start, count, leaves) in enumerate(self.blocks, 1):
            logger.info('  pool %d: fc%d %d:%d [ %d range%s ]', i, fc,
                        start, count, len(leaves), '' if len(leaves) == 1 else '(s)')

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
        # the gates resolve BEFORE the swaps: a bad value or acl file keeps
        # the previous settings wholesale (the watcher logs the failure)
        connect_acl = self._resolve_ip_acl(self.config.get('connect_acl'), 'connect')
        write_acl = self._resolve_ip_acl(self.config.get('write_acl'), 'write')
        metrics_acl = self._resolve_ip_acl(self.config.get('metrics_acl'), 'metrics')
        self.upstream.host = self.config['host']
        self.upstream.port = self.config['port']
        self.upstream.unit = self.config['unit']
        self.upstream.timeout = self.config['timeout']
        self.upstream.auth = self.config['modbus_auth_upstream']
        self.upstream.auth_key = self.config['modbus_auth_upstream_key']
        with self.upstream.lock:
            self.upstream.close()
        ranges, names, ttls = self.load_map()
        self.no_cache = self.config.get('selection') == 'none'
        self.read_delay = self.config['read_delay']
        self.merge_gap = self.config['merge_gap']
        self.interval = self.config['interval']
        self.allow_write = bool(self.config.get('allow_write', False))
        self.set_write_registers(self.config.get('write_registers'))
        self.log_access = bool(self.config.get('log_access', False))
        self.max_clients = max(0, int(self.config.get('max_clients') or 0))
        self.client_timeout = max(0.0, float(self.config.get('client_timeout') or 0.0))
        self.conn_gate = ConnGate(0, max(0, int(self.config.get('max_conn_per_ip') or 0)))
        self.requests_audit_s = max(0.0, float(self.config.get('requests_audit_s', REQUESTS_AUDIT_S)))
        self.connect_acl = connect_acl
        self.write_acl = write_acl
        self.metrics_acl = metrics_acl
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
                self.audit.event('REQUESTS', 'peer=%s requests=%d window=%ds recent=%d'
                                 % (key, entry['requests'], int(self.requests_audit_s), delta))

    def _allowed(self, acl, ip):
        """The IP ACL on one peer (common/settings/config.py acl_admits — one
        implementation for the family's IP gates)."""
        return acl_admits(acl, ip)

    def _resolve_ip_acl(self, val, knob):
        """The acl/connect + acl/write knob value -> the effective gate:
        the system words and the network lists ride parse_acl; 'file:<path>'
        loads the standalone ip-prefix gate file (the chain evaluates at
        connect/write: last matching rule decides, no match denies).
        ValueError on a bad value or file — the caller keeps the old gate.
        A group/world-readable acl file warns (the log, the audit trail's
        ACL-FILE event, the set/clear reply's suffix — the <knob>_acl_warn
        stash; chmod 0600 silences all three). The resolved shapes pass
        through: None / () / the networks tuple from the config resolution,
        an IPGate from a live set."""
        if not isinstance(val, str):   # None, () or the networks tuple: resolved already
            return val
        t = val.strip()
        if t.startswith('file:'):
            try:
                desc, rules = load_write_gate_file(t[5:], allow=('ip-prefix',))
            except SystemExit as e:
                raise ValueError(str(e))
            warn = acl_file_warn(t[5:])
            setattr(self, '%s_acl_warn' % knob, warn)
            if warn is not None:
                logger.warning('acl file: %s', warn)
                if self.audit is not None:
                    self.audit.event('ACL-FILE', 'warn=%s' % audit_quote(warn))
            return IPGate(t, desc, rules)
        setattr(self, '%s_acl_warn' % knob, None)   # an inline set clears a standing file warning
        try:
            return parse_acl(t, 'acl/%s' % knob)
        except SystemExit as e:
            raise ValueError(str(e))

    def set_connect_acl(self, val):
        """Swap the acl/connect knob (any/none/the networks/file:<path>):
        resolve first — a bad value or acl file leaves the old gate
        standing."""
        self.connect_acl = self._resolve_ip_acl(val, 'connect')
        self.config['connect_acl'] = self.connect_acl
        return acl_value_text(self.connect_acl)

    def set_write_acl(self, val):
        """Swap the acl/write knob (the same grammar): resolve first — a
        bad value or acl file leaves the old gate standing."""
        self.write_acl = self._resolve_ip_acl(val, 'write')
        self.config['write_acl'] = self.write_acl
        return acl_value_text(self.write_acl)

    def set_metrics_acl(self, val):
        """Swap the metrics/acl knob (the acl/connect grammar on the
        /metrics listener): resolve first — a bad value or acl file leaves
        the old gate standing. The live swap is read-through: the
        MetricsServer's accept hook reads self.metrics_acl per connection."""
        self.metrics_acl = self._resolve_ip_acl(val, 'metrics')
        self.config['metrics_acl'] = self.metrics_acl
        return acl_value_text(self.metrics_acl)

    def _write_allowed(self, target):
        """The register-range allow-list: every touched register must land
        inside one of the effective ranges (None = any register; () = none
        writable — the 'none' mode)."""
        if self.write_ranges is None or target is None:
            return True
        addr, count = target
        return any(rs <= addr and addr + count <= rs + rc for rs, rc in self.write_ranges)

    def _resolve_write_ranges(self, val):
        """The knob value -> the effective ranges. 'profile' loads the
        device profile's write acl against the CURRENT config, 'file:<path>'
        the standalone acl file (the same gate object a profile carries
        under "acl"/"write") — both ValueError on a missing or bad gate
        (the start re-raises as SystemExit, the wire answers err) and keep
        the parsed rules for the write/registers/table show report, the
        stash swapping only on a successful resolve so a bad gate leaves
        the old one AND its report standing; everything else passes
        through unchanged. A group/world-readable acl file warns — the
        log, the audit trail's ACL-FILE event, and the set/clear reply's
        suffix all carry it (the file is config trust: chmod 0600)."""
        try:
            if val == 'profile':
                desc, rules = load_profile_write_gate(self.config.get('profile'))
                self.write_gate_warn = None
            elif isinstance(val, str) and val.startswith('file:'):
                desc, rules = load_write_gate_file(val[5:])
                self.write_gate_warn = acl_file_warn(val[5:])
                if self.write_gate_warn is not None:
                    logger.warning('acl file: %s', self.write_gate_warn)
                    if self.audit is not None:
                        self.audit.event('ACL-FILE', 'warn=%s' % audit_quote(self.write_gate_warn))
            else:
                self.write_gate_warn = None
                return val
            ranges = compile_write_acl(rules)
        except SystemExit as e:
            raise ValueError(str(e))   # the old gate and its warning stand
        self.write_gate_rules = (desc, rules)
        return ranges

    def set_write_registers(self, val):
        """Swap the write-registers knob (None/()/(ranges)/'profile'/
        'file:<path>'): resolve first — a bad profile acl or acl file
        leaves the old gate standing."""
        ranges = self._resolve_write_ranges(val)
        self.write_registers = val
        self.write_ranges = ranges

    def _ranges_text(self):
        """The effective ranges for humans: 'any', 'none' or START:COUNT,..."""
        if self.write_ranges is None:
            return 'any'
        if not self.write_ranges:
            return 'none'
        return ','.join('%d:%d' % r for r in self.write_ranges)

    def describe_write_ranges(self):
        """The knob value for the wire and the dumps (re-appliable): 'any',
        'none', 'profile', the 'file:<path>' acl reference or the
        configured ranges."""
        if isinstance(self.write_registers, str):
            return self.write_registers   # 'profile' / the file reference — both re-resolve
        return self._ranges_text()

    def describe_write_gate(self):
        """The gate for humans (the logs, inspect): like
        describe_write_ranges, but a profile- or file-mode gate names the
        effective ranges it resolved to."""
        if isinstance(self.write_registers, str):
            return '%s (%s)' % (self.write_registers, self._ranges_text())
        return self._ranges_text()

    # The accept ladder and the session opener are the family's one
    # implementation (common/modbus/server.py serve_modbus) — the refusal
    # texts and logs are identical at both Modbus faces by construction.
    # The face hooks below carry what differs: the forwarding dispatch, the
    # in-band answer for malformed PDUs, the REQUESTS evidence.

    def serve(self, host, port):
        serve_modbus(self, host, port)

    max_pdu = MAX_PDU
    log = logger

    def access(self, fmt, *args):
        (logger.info if self.log_access else logger.debug)(fmt, *args)

    def listening(self, host, port):
        logger.info('modbus-cache listening on %s:%d (client limit %s, client timeout %s)',
                    host, port,
                    self.max_clients or 'none', '%gs' % self.client_timeout if self.client_timeout else 'none')

    def allowed(self, ip):
        return self._allowed(self.connect_acl, ip)

    def suite_key(self):
        return self.config.get('modbus_auth_key') if self.config.get('auth') == 'suite' else None

    def on_session(self):
        pass

    def on_frame(self):
        pass

    def malformed(self, addr, err):
        pass   # a bad MBAP length: the frame is not parseable enough to answer — the PDU-level
               # malformations get the in-band exception inside respond()

    def frame(self, client, txn, proto, unit, pdu, addr):
        client.sendall(self.respond(txn, proto, unit, pdu, addr))

    def on_disconnect(self, key, entry):
        if self.audit and entry:
            self.audit.event('REQUESTS', 'peer=%s requests=%d connected=%ds'
                             % (key, entry['requests'], int(time.monotonic() - entry['since'])))

    def respond(self, txn, proto, unit, pdu, addr):
        if proto != 0 or not pdu:
            return exception_frame(txn, proto, unit, pdu[0] if pdu else 3, ILLEGAL_VALUE)
        func = pdu[0]
        if not unit_in_range(unit):
            # the family's unit-id range (protocol.json): 0 is the broadcast
            # id, 248-255 reserved — the gateway answers in-band, no upstream
            return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
        if func in WRITE_FUNCS:
            target = write_target(pdu)
            if target is None:
                desc = _write_desc(func, pdu, unit)
                logger.info('write: refused %s (the frame is too short to carry a register address)', desc)
                self.write_refused += 1
                if self.audit:
                    self.audit.event('WRITE-REFUSED', 'fc=%d unit=%d reason=too-short' % (func, unit))
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            if not self.allow_write:
                desc = _write_desc(func, pdu, unit)
                logger.info('write: refused %s (write support disabled, enable with --allow-write)', desc)
                self.write_refused += 1
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s reason=write-disabled' % write_kv(pdu, unit))
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
            if not self._allowed(self.write_acl, addr[0]):
                desc = _write_desc(func, pdu, unit)
                logger.info('write: refused %s (client %s not on the write ACL)', desc, addr[0])
                self.write_refused += 1
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s reason=not-on-write-acl client=%s'
                                     % (write_kv(pdu, unit), addr[0]))
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
            if not self._write_allowed(target):
                desc = _write_desc(func, pdu, unit)
                logger.info('write: refused %s (registers outside the write allow-list %s)',
                            desc, self.describe_write_gate())
                self.write_refused += 1
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s reason=outside-allow-list' % write_kv(pdu, unit))
                return exception_frame(txn, proto, unit, func, ILLEGAL_FUNCTION)
            shape_err = write_shape_error(pdu)
            if shape_err:
                desc = _write_desc(func, pdu, unit)
                logger.info('write: refused %s (malformed frame: %s)', desc, shape_err)
                self.write_refused += 1
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s reason=malformed-frame error=%s'
                                     % (write_kv(pdu, unit), audit_quote(shape_err)))
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
        if func in READ_FUNCS:
            if len(pdu) < 5:
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            addr_, count = struct.unpack('>HH', pdu[1:5])
            cap = MAX_BITS if func in BIT_READ_FUNCS else MAX_COUNT
            if not 1 <= count <= cap or addr_ + count > 65536:
                return exception_frame(txn, proto, unit, func, ILLEGAL_VALUE)
            if func == 3 and addr_ >= DIAG_BASE:
                if addr_ + count <= DIAG_BASE + DIAG_COUNT:
                    return self._diag(txn, proto, unit, addr_, count)
                return exception_frame(txn, proto, unit, func, ILLEGAL_ADDRESS)
            if func == 3 and addr_ < DIAG_BASE and addr_ + count > DIAG_BASE:
                return exception_frame(txn, proto, unit, func, ILLEGAL_ADDRESS)
            code = self.cache.failed_leaf(func, addr_, count)
            if code is not None:
                logger.info('read: %s %d:%d served from last poll: the device rejects them (modbus exception %d)',
                            _space_name(func), addr_, count, code)
                return exception_frame(txn, proto, unit, func, code)
            if self.cache.covers(func, addr_, count):
                self.cache_hits += 1
                logger.debug('read: fc%d %s %d:%d served from cache', func, _space_name(func), addr_, count)
                words = self.cache.words(func, addr_, count)
                if func in BIT_READ_FUNCS:
                    packed = pack_bits(w & 1 for w in words)
                    body = struct.pack('>BB', func, len(packed)) + packed
                else:
                    body = struct.pack('>BB', func, count * 2) + struct.pack('>%dH' % count, *words)
                return frame(txn, unit, body, proto=proto)
            self.cache_misses += 1
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
        return frame(txn, unit, body, proto=proto)

    def forward(self, txn, proto, unit, pdu):
        desc = describe_write(pdu, unit)
        if desc:
            logger.info('write: %s', desc)
            if self.audit:
                self.audit.event('WRITE', write_kv(pdu, unit))
        is_read = bool(pdu) and pdu[0] in READ_FUNCS and len(pdu) >= 5
        fc = addr = count = None
        if is_read:
            fc = pdu[0]
            addr, count = struct.unpack('>HH', pdu[1:5])
            logger.info('read: fc%d %s %d:%d not cached, polling the device',
                        fc, _space_name(fc), addr, count)
        else:
            # the frame carries no cache semantics (FC7/8/17/…, vendor
            # codes) — forward it untouched, named in the log
            logger.info('forwarded %s, %d byte(s) (unit %d)', describe_fc(pdu[0]), len(pdu) - 1, unit)
        frame_out = frame(txn, unit, pdu, proto=proto)
        try:
            with self.upstream.lock:
                resp = self.upstream.forward(frame_out)
            if resp[6:7] != bytes([unit & 0xFF]):
                raise ModbusError('reply from unit id %d, expected %d' % (resp[6], unit))
            body = resp[7:]
            if resp and body and body[0] == pdu[0] | 0x80:
                code = body[1] if len(body) > 1 else -1
                if desc:
                    logger.warning('write rejected by the device: %s (modbus exception %d)', desc, code)
                    if self.audit:
                        self.audit.event('WRITE-REJECTED', '%s exception=%d' % (write_kv(pdu, unit), code))
                elif not is_read:
                    logger.info('forwarded %s rejected by the device (modbus exception %d)',
                                describe_fc(pdu[0]), code)
            if is_read:
                expect = _read_shape(fc, count)
                if body and body[0] == fc and len(body) >= 2 and body[1] == expect:
                    if not self.no_cache:
                        if fc in BIT_READ_FUNCS:
                            vals = unpack_bits(body[2:2 + expect], count)
                        else:
                            vals = struct.unpack('>%dH' % count, body[2:2 + count * 2])
                        self.cache.store(fc, addr, vals)
                    logger.info('read: fc%d %s %d:%d ok%s', fc, _space_name(fc), addr, count,
                                '' if not self.no_cache else ' (not cached: selection none)')
                elif body and body[0] == fc | 0x80:
                    logger.warning('read: fc%d %s %d:%d rejected by the device (modbus exception %d)',
                                   fc, _space_name(fc), addr, count, body[2] if len(body) > 2 else -1)
                else:
                    logger.warning('read: fc%d %s %d:%d unexpected response',
                                   fc, _space_name(fc), addr, count)
            elif desc and body and body[0] == pdu[0] and pdu[0] in WRITE_FUNCS:
                # write-through invalidation: the device took the write, so the
                # cached words of the touched range are stale — drop exactly
                # them (per-register) and let the poller refill promptly. The
                # register writes (FC6/16/22/23) invalidate both register
                # spaces (a device is free to mirror), the coil writes
                # (FC5/15) the coil space.
                target = write_target(pdu)
                if target:
                    waddr, wcount = target
                    spaces = (1,) if pdu[0] in (5, 15) else (3, 4)
                    dropped = sum(self.cache.invalidate(s, waddr, wcount) for s in spaces)
                    if dropped:
                        self.poll_wake.set()
                        logger.info('write: invalidated %d cached word(s) at %s %d:%d, repolling',
                                    dropped, _space_name(1 if pdu[0] in (5, 15) else 3), waddr, wcount)
            return resp
        except (ModbusError, OSError) as e:
            self.upstream.close()
            if desc:
                logger.warning('write failed: %s (%s)', desc, e)
                if self.audit:
                    self.audit.event('WRITE-FAILED', '%s error=%s' % (write_kv(pdu, unit), audit_quote(e)))
            elif is_read:
                logger.warning('read: fc%d registers %d:%d failed (%s)', fc, addr, count, e)
            return exception_frame(txn, proto, unit, pdu[0], GATEWAY_FAILED)
