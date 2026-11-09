#!/usr/bin/env python3
"""The fake inverter's Modbus TCP server: FC3/FC4 register reads and
FC1/FC2 bit reads from the simulator (strict mode, write overlays),
FC05/FC06/FC15/FC16 writes behind the write gate, every other function
code named and refused, chaos injection. The wire lives in
common.modbus — the framing, the bit packing and the write shapes are
the family's one implementation."""
import logging
import socket
import struct
import threading
import time

from common.config import acl_admits
from common.modbus import (ModbusError, auth_handshake_server, describe_fc,
                           describe_write, exception_frame, frame, pack_bits,
                           read_frame, unpack_bits)
from common.connlimit import ConnGate
from .statics import MAX_BITS, MAX_COUNT, MAX_PDU
from common.version import version_string

logger = logging.getLogger('fake-inverter')


class FakeInverter:
    def __init__(self, unit, simulator, strict=False, chaos=None, max_clients=64, client_timeout=300.0,
                 max_conn_per_ip=0, connect_acl=None, auth=None, auth_key=None,
                 allow_write=False, audit=None):
        self.unit = unit
        self.simulator = simulator
        self.strict = strict
        self.chaos = chaos
        self.overlay = {}      # FC06/FC16 write overlay on the holding registers
        self.coils = {}        # FC05/FC15 writes + `set coil`: addr -> 0/1 (FC1 reads)
        self.discrete = {}     # `set discrete` pins: addr -> 0/1 (FC2 reads)
        self.allow_write = allow_write   # the write gate: off = every Modbus write is refused (01)
        self.audit = audit     # the INV audit trail (common.audit), None = off — WRITE / WRITE-REFUSED ride it
        self.srv = None
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
        self.clients = {}        # 'ip:port' -> {'since': monotonic, 'requests': n} (show connections)

    def allowed(self, ip):
        """The connect ACL (the shared acl_admits — the fake's acl is the
        plain networks shape; the IPGate branch never fires here): None =
        off (everybody allowed — the default, the trusted-LAN posture);
        () = nobody; otherwise the ip must land in one network."""
        return acl_admits(self.connect_acl, ip)

    def serve(self, host, port):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(16)
        self.srv = srv
        self.listen_addr = (host, port)
        logger.info('fake inverter %s listening on %s:%d (unit %d, peak PV %gW, client limit %s, client timeout %s, per-ip limit %s, connect-acl %s, modbus auth %s, writes %s)%s',
                    version_string(), host, port, self.unit, self.simulator.peak_w,
                    self.max_clients or 'none',
                    '%gs' % self.client_timeout if self.client_timeout else 'none',
                    self.conn_gate.max_per_ip or 'none',
                    'any' if self.connect_acl is None else ('none' if not self.connect_acl else '%d network(s)' % len(self.connect_acl)),
                    self.auth or 'none',
                    'on' if self.allow_write else 'off',
                    ', chaos p=%.2f' % self.chaos.p if self.chaos and self.chaos.p else '')
        while True:
            try:
                client, addr = srv.accept()
                admitted = False
                try:
                    if self.client_timeout:
                        client.settimeout(self.client_timeout)
                    ok, _why = self.conn_gate.admit(addr[0])   # counts always; enforces only when capped
                    if not ok:
                        logger.info('connection refused: per-IP limit of %d reached (%s:%d)',
                                    self.conn_gate.max_per_ip, *addr[:2])
                    elif not self.allowed(addr[0]):
                        self.conn_gate.release(addr[0])
                        logger.info('connection rejected: %s:%d not on the connect ACL', *addr[:2])
                    elif self.max_clients and self.client_count >= self.max_clients:
                        self.conn_gate.release(addr[0])
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
                        self.conn_gate.release(addr[0])
                        admitted = False
                finally:
                    if not admitted:
                        client.close()
            except (OSError, RuntimeError) as e:
                if self.stopping:
                    return   # the signal box closed the listener; it logs the shutdown
                logger.error('accept failed (%s), retrying', e)
                time.sleep(0.1)

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

    def handle(self, client, addr):
        logger.info('client connected: %s:%d', *addr[:2])
        self.conns += 1
        key = '%s:%d' % addr[:2]
        with self.client_lock:
            self.clients[key] = {'since': time.monotonic(), 'requests': 0}
        try:
            # the suite auth (when enabled) gates the Modbus loop: the
            # client speaks the handshake first, and one that cannot prove
            # the key is dropped before it ever sees a register
            if self.auth == 'suite' and self.auth_key:
                try:
                    proved = auth_handshake_server(client, self.auth_key)
                except (ConnectionError, OSError) as e:
                    logger.info('suite auth with %s:%d died mid-handshake (%s)', addr[0], addr[1], e)
                    return
                if not proved:
                    logger.info('suite auth failed for %s:%d, closing', *addr[:2])
                    return
                logger.debug('client %s:%d passed the suite handshake', *addr[:2])
            while True:
                self.requests += 1
                try:
                    txn, proto, length, unit, pdu = read_frame(client, MAX_PDU)
                except ModbusError as e:
                    logger.info('malformed frame from %s:%d (%s), closing', addr[0], addr[1], e)
                    break
                with self.client_lock:
                    entry = self.clients.get(key)
                    if entry:
                        entry['requests'] += 1
                func = pdu[0]
                addr_ = count = None
                if len(pdu) >= 5:
                    addr_, count = struct.unpack('>HH', pdu[1:5])
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
                        self.audit.event('WRITE-REFUSED', '%s (write support disabled)' % desc)
                    continue
                if func in (3, 4) and addr_ is not None:   # holding (FC3) / input (FC4) registers
                    if not 1 <= count <= MAX_COUNT or addr_ + count > 65536:
                        # the read-count gate, the cache's shape: a declared
                        # count beyond the PDU (0xFFFF with a truncated frame)
                        # must not make the fake assemble an oversized reply
                        client.sendall(exception_frame(txn, 0, unit, func, 3))
                        logger.info('fc%d read %d regs @%d from %s:%d -> exception 03 (illegal data value)',
                                    func, count, addr_, addr[0], addr[1])
                        continue
                    regs = self.simulator.registers(func)
                    if func == 3:
                        regs.update(self.overlay)
                    if self.strict and any(addr_ + i not in regs for i in range(count)):
                        client.sendall(exception_frame(txn, 0, unit, func, 2))
                        logger.debug('fc%d read %d regs @%d -> exception 02 (undefined register)', func, count, addr_)
                        continue
                    words = [regs.get(addr_ + i, 0) & 0xFFFF for i in range(count)]
                    data = struct.pack('>%dH' % count, *words) if words else b''
                    client.sendall(frame(txn, unit, struct.pack('>BB', func, count * 2) + data))
                    logger.debug('fc%d read %d regs @%d -> %s', func, count, addr_, words)
                elif func in (1, 2) and addr_ is not None:   # coils (FC1) / discrete inputs (FC2)
                    if not 1 <= count <= MAX_BITS or addr_ + count > 65536:
                        client.sendall(exception_frame(txn, 0, unit, func, 3))
                        logger.info('fc%d read %d bit(s) @%d from %s:%d -> exception 03 (illegal data value)',
                                    func, count, addr_, addr[0], addr[1])
                        continue
                    bits_map = self.simulator.registers(func)
                    bits_map.update(self.coils if func == 1 else self.discrete)
                    if self.strict and any(addr_ + i not in bits_map for i in range(count)):
                        client.sendall(exception_frame(txn, 0, unit, func, 2))
                        logger.debug('fc%d read %d bit(s) @%d -> exception 02 (undefined bit)', func, count, addr_)
                        continue
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
                        continue
                    self.coils[addr_] = 1 if value else 0
                    client.sendall(frame(txn, unit, pdu))
                    logger.info('write: %s', describe_write(pdu, unit))
                    if self.audit:
                        self.audit.event('WRITE', describe_write(pdu, unit))
                elif func == 6 and len(pdu) == 5:
                    self.overlay[addr_] = struct.unpack('>H', pdu[3:5])[0]
                    client.sendall(frame(txn, unit, pdu))
                    logger.info('write: %s', describe_write(pdu, unit))
                    if self.audit:
                        self.audit.event('WRITE', describe_write(pdu, unit))
                elif func == 15 and addr_ is not None and len(pdu) >= 6 and count \
                        and pdu[5] == (count + 7) // 8 and len(pdu) == 6 + pdu[5]:
                    if not 1 <= count <= MAX_BITS or addr_ + count > 65536:
                        client.sendall(exception_frame(txn, 0, unit, func, 3))
                        logger.info('write: %d coil(s) @%d from %s:%d -> exception 03 (illegal data value)',
                                    count, addr_, addr[0], addr[1])
                        continue
                    for i, bit in enumerate(unpack_bits(pdu[6:6 + pdu[5]], count)):
                        self.coils[addr_ + i] = bit
                    client.sendall(frame(txn, unit, struct.pack('>BHH', func, addr_, count)))
                    logger.info('write: %s', describe_write(pdu, unit))
                    if self.audit:
                        self.audit.event('WRITE', describe_write(pdu, unit))
                elif func == 16 and len(pdu) >= 6 and pdu[5] == count * 2 and len(pdu) == 6 + count * 2:
                    values = struct.unpack('>%dH' % count, pdu[6:6 + count * 2])
                    for i, w in enumerate(values):
                        self.overlay[addr_ + i] = w
                    client.sendall(frame(txn, unit, struct.pack('>BHH', func, addr_, count)))
                    logger.info('write: %s', describe_write(pdu, unit))
                    if self.audit:
                        self.audit.event('WRITE', describe_write(pdu, unit))
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
        except (ConnectionError, OSError) as e:
            logger.info('client %s:%d disconnected (%s)', *addr[:2], e)
        except struct.error as e:
            logger.info('malformed frame from %s:%d (%s)', addr[0], addr[1], e)
        except Exception as e:
            logger.error('error handling %s:%d: %s', *addr[:2], e)
        finally:
            with self.client_lock:
                self.clients.pop(key, None)
                self.client_count -= 1
            self.conn_gate.release(addr[0])
            client.close()
