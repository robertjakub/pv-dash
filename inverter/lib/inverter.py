#!/usr/bin/env python3
"""The fake inverter's Modbus TCP server: FC3/FC4 register reads and
FC1/FC2 bit reads from the simulator (strict mode, write overlays),
FC05/FC06/FC15/FC16 writes behind the write gate, every other function
code named and refused, chaos injection. The wire lives in
common.modbus — the framing, the bit packing and the write shapes are
the family's one implementation."""
import logging
import struct
import threading
import time

from common.settings.config import acl_admits
from common.modbus import (describe_fc, describe_write, exception_frame, write_kv,
                           frame, pack_bits, serve_modbus, unit_in_range,
                           unpack_bits)
from common.serve.connlimit import ConnGate
from .statics import MAX_BITS, MAX_COUNT, MAX_PDU
from common.runtime.version import version_string

logger = logging.getLogger('fake-inverter')


class FakeInverter:
    def __init__(self, unit, simulator, strict=False, chaos=None, max_clients=64, client_timeout=300.0,
                 max_conn_per_ip=0, connect_acl=None, auth=None, auth_key=None,
                 allow_write=False, audit=None, log_access=False):
        self.unit = unit
        self.simulator = simulator
        self.strict = strict
        self.chaos = chaos
        self.overlay = {}      # FC06/FC16 write overlay on the holding registers
        self.coils = {}        # FC05/FC15 writes + `set coil`: addr -> 0/1 (FC1 reads)
        self.discrete = {}     # `set discrete` pins: addr -> 0/1 (FC2 reads)
        self.allow_write = allow_write   # the write gate: off = every Modbus write is refused (01)
        self.log_access = log_access   # the connect/disconnect lines: INFO when on, DEBUG by default
        self.audit = audit     # the INV audit trail (common.audit), None = off — WRITE / WRITE-REFUSED ride it
        self.listen_sock = None   # the shared ladder's listener (the signal box closes it)
        self.listen_addr = None
        self.stopping = False
        self.conns = 0
        self.requests = 0
        self.max_clients = max(0, int(max_clients))       # 0 = no limit
        self.client_timeout = max(0.0, float(client_timeout))   # 0 = never
        self.conn_gate = ConnGate(0, max(0, int(max_conn_per_ip)))   # 0 = no per-IP limit
        self.connect_acl = connect_acl    # None = any (the default); () = none; networks = the allow list
        self.auth = auth                  # None = no auth | 'suite' = the crypt handshake before any frame
        self.auth_key = auth_key          # the shared key the handshake demands
        self.client_lock = threading.Lock()
        self.client_count = 0
        self.clients = {}        # 'ip:port' -> {'since': monotonic, 'requests': n, 'audited': n} (show connections)

    def allowed(self, ip):
        """The connect ACL (the shared acl_admits — the fake's acl is the
        plain networks shape; the IPGate branch never fires here): None =
        off (everybody allowed — the default, the trusted-LAN posture);
        () = nobody; otherwise the ip must land in one network."""
        return acl_admits(self.connect_acl, ip)

    # The accept ladder and the session opener are the family's one
    # implementation (common/modbus/server.py serve_modbus) — the refusal
    # texts and logs are identical at both Modbus faces by construction.
    # The face hooks below carry what differs: the simulator's dispatch,
    # the chaos injection and the malformed-frame log (the fake closes —
    # it has no in-band answer to give).

    def serve(self, host, port):
        serve_modbus(self, host, port)

    max_pdu = MAX_PDU
    log = logger

    def access(self, fmt, *args):
        (logger.info if self.log_access else logger.debug)(fmt, *args)

    def on_session(self):
        self.conns += 1

    def on_frame(self):
        self.requests += 1

    def malformed(self, addr, err):
        logger.info('malformed frame from %s:%d (%s), closing', addr[0], addr[1], err)

    def suite_key(self):
        return self.auth_key if self.auth == 'suite' else None

    def on_disconnect(self, key, entry):
        pass

    def listening(self, host, port):
        logger.info('fake inverter %s listening on %s:%d (unit %d, peak PV %gW, client limit %s, client timeout %s, per-ip limit %s, connect-acl %s, modbus auth %s, writes %s)%s',
                    version_string(), host, port, self.unit, self.simulator.peak_w,
                    self.max_clients or 'none',
                    '%gs' % self.client_timeout if self.client_timeout else 'none',
                    self.conn_gate.max_per_ip or 'none',
                    'any' if self.connect_acl is None else ('none' if not self.connect_acl else '%d network(s)' % len(self.connect_acl)),
                    self.auth or 'none',
                    'on' if self.allow_write else 'off',
                    ', chaos p=%.2f' % self.chaos.p if self.chaos and self.chaos.p else '')

    def _chaos_fault(self, client, tid, uid):
        """Inject one hostile reply; every mode ends with the connection dropped."""
        mode = self.chaos.mode()
        logger.warning('chaos %s (hit #%d)', mode, self.chaos.hits)
        if mode == 'garbage':
            client.sendall(b'\xde\xad\xbe\xef' * 4)
        elif mode == 'short':
            client.sendall(struct.pack('>HHH', tid, 0, 0xFFFF))
        elif mode == 'lying':
            client.sendall(struct.pack('>HHH', tid, 0, 0xFFFF) + bytes([uid, 3]) + b'\x00' * 8)
        elif mode == 'txn':
            body = struct.pack('>BB', 3, 2) + b'\x00\x00'
            client.sendall(struct.pack('>HHHB', (tid + 1) & 0xFFFF, 0, len(body) + 1, uid) + body)
        elif mode == 'unit':
            body = struct.pack('>BB', 3, 2) + b'\x00\x00'
            client.sendall(struct.pack('>HHHB', tid, 0, len(body) + 1, uid + 1) + body)
        elif mode == 'stall':
            time.sleep(5)
        elif mode == 'exception':
            body = struct.pack('>BB', 3 + 0x80, 2)
            client.sendall(struct.pack('>HHHB', tid, 0, len(body) + 1, uid) + body)
        # 'dropout': send nothing at all
        raise ConnectionError('chaos %s' % mode)

    def frame(self, client, txn, proto, unit, pdu, addr):
        """One parsed frame, dispatched: the reads off the simulator,
        the writes behind the gate, chaos on the way out. The shared
        session loop (common/modbus/server.py) owns the framing and
        the unwind; the struct.error malformation log stays the
        fake's own (it closes where the cache answers in-band)."""
        try:
            func = pdu[0]
            addr_ = count = None
            if len(pdu) >= 5:
                addr_, count = struct.unpack('>HH', pdu[1:5])
            if not unit_in_range(unit):
                # the family's unit-id range (protocol.json): 0 is the
                # broadcast id, 248-255 reserved — the fake answers 03
                logger.info('request for unit %d outside 1..247 -> exception 03 (illegal data value)', unit)
                client.sendall(exception_frame(txn, 0, unit, func, 3))
                return
            if unit != self.unit:
                logger.debug('request for unit %d, serving %d', unit, self.unit)
            if self.chaos and self.chaos.hit():
                self._chaos_fault(client, txn, self.unit)
            if func in (5, 6, 15, 16) and addr_ is not None and not self.allow_write:
                # the write gate (the cache's, mirrored): a write-disabled
                # fake answers exception 01 before any shape verdict —
                # enable with --allow-write; audited like the cache's trail
                desc = describe_write(pdu, unit) or '%s (unit %d)' % (describe_fc(func), unit)
                client.sendall(exception_frame(txn, 0, unit, func, 1))
                logger.info('write: refused %s (write support disabled, enable with --allow-write)', desc)
                if self.audit:
                    self.audit.event('WRITE-REFUSED', '%s reason=write-disabled' % write_kv(pdu, unit))
                return
            if func in (3, 4) and addr_ is not None:   # holding (FC3) / input (FC4) registers
                if not 1 <= count <= MAX_COUNT or addr_ + count > 65536:
                    # the read-count gate, the cache's shape: a declared
                    # count beyond the PDU (0xFFFF with a truncated frame)
                    # must not make the fake assemble an oversized reply
                    client.sendall(exception_frame(txn, 0, unit, func, 3))
                    logger.info('fc%d read %d regs @%d from %s:%d -> exception 03 (illegal data value)',
                                func, count, addr_, addr[0], addr[1])
                    return
                regs = self.simulator.registers(func)
                if func == 3:
                    regs.update(self.overlay)
                if self.strict and any(addr_ + i not in regs for i in range(count)):
                    client.sendall(exception_frame(txn, 0, unit, func, 2))
                    logger.debug('fc%d read %d regs @%d -> exception 02 (undefined register)', func, count, addr_)
                    return
                words = [regs.get(addr_ + i, 0) & 0xFFFF for i in range(count)]
                data = struct.pack('>%dH' % count, *words) if words else b''
                client.sendall(frame(txn, unit, struct.pack('>BB', func, count * 2) + data))
                logger.debug('fc%d read %d regs @%d -> %s', func, count, addr_, words)
            elif func in (1, 2) and addr_ is not None:   # coils (FC1) / discrete inputs (FC2)
                if not 1 <= count <= MAX_BITS or addr_ + count > 65536:
                    client.sendall(exception_frame(txn, 0, unit, func, 3))
                    logger.info('fc%d read %d bit(s) @%d from %s:%d -> exception 03 (illegal data value)',
                                func, count, addr_, addr[0], addr[1])
                    return
                bits_map = self.simulator.registers(func)
                bits_map.update(self.coils if func == 1 else self.discrete)
                if self.strict and any(addr_ + i not in bits_map for i in range(count)):
                    client.sendall(exception_frame(txn, 0, unit, func, 2))
                    logger.debug('fc%d read %d bit(s) @%d -> exception 02 (undefined bit)', func, count, addr_)
                    return
                bits = [(bits_map.get(addr_ + i, 0) & 1) for i in range(count)]
                packed = pack_bits(bits)
                client.sendall(frame(txn, unit, struct.pack('>BB', func, len(packed)) + packed))
                logger.debug('fc%d read %d bit(s) @%d -> %s', func, count, addr_, bits)
            elif func == 5 and addr_ is not None:   # write single coil: the second word is 0x0000/0xFF00
                value = count
                if value not in (0x0000, 0xFF00):
                    client.sendall(exception_frame(txn, 0, unit, func, 3))
                    logger.info('write: coil %d = 0x%04x from %s:%d -> exception 03 (illegal data value)',
                                addr_, value, addr[0], addr[1])
                    return
                self.coils[addr_] = 1 if value else 0
                client.sendall(frame(txn, unit, pdu))
                logger.info('write: %s', describe_write(pdu, unit))
                if self.audit:
                    self.audit.event('WRITE', write_kv(pdu, unit))
            elif func == 6 and len(pdu) == 5:
                self.overlay[addr_] = struct.unpack('>H', pdu[3:5])[0]
                client.sendall(frame(txn, unit, pdu))
                logger.info('write: %s', describe_write(pdu, unit))
                if self.audit:
                    self.audit.event('WRITE', write_kv(pdu, unit))
            elif func == 15 and addr_ is not None and len(pdu) >= 6 and count \
                    and pdu[5] == (count + 7) // 8 and len(pdu) == 6 + pdu[5]:
                if not 1 <= count <= MAX_BITS or addr_ + count > 65536:
                    client.sendall(exception_frame(txn, 0, unit, func, 3))
                    logger.info('write: %d coil(s) @%d from %s:%d -> exception 03 (illegal data value)',
                                count, addr_, addr[0], addr[1])
                    return
                for i, bit in enumerate(unpack_bits(pdu[6:6 + pdu[5]], count)):
                    self.coils[addr_ + i] = bit
                client.sendall(frame(txn, unit, struct.pack('>BHH', func, addr_, count)))
                logger.info('write: %s', describe_write(pdu, unit))
                if self.audit:
                    self.audit.event('WRITE', write_kv(pdu, unit))
            elif func == 16 and len(pdu) >= 6 and pdu[5] == count * 2 and len(pdu) == 6 + count * 2:
                values = struct.unpack('>%dH' % count, pdu[6:6 + count * 2])
                for i, w in enumerate(values):
                    self.overlay[addr_ + i] = w
                client.sendall(frame(txn, unit, struct.pack('>BHH', func, addr_, count)))
                logger.info('write: %s', describe_write(pdu, unit))
                if self.audit:
                    self.audit.event('WRITE', write_kv(pdu, unit))
            else:
                # everything the fake does not serve is named and refused:
                # a bad shape on an implemented FC (including a frame too
                # short to carry its address) is exception 03 (illegal
                # data value), an unimplemented FC is 01
                implemented = func in (1, 2, 3, 4, 5, 6, 15, 16)
                body = struct.pack('>BB', func + 0x80, 3 if implemented else 1)
                client.sendall(frame(txn, unit, body))
                logger.info('rejected %s from %s:%d (%s)', describe_fc(func), addr[0], addr[1],
                            'malformed frame' if implemented else 'illegal function')
        except struct.error as e:
            logger.info('malformed frame from %s:%d (%s)', addr[0], addr[1], e)