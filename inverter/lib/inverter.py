#!/usr/bin/env python3
"""The fake inverter's Modbus TCP server: FC3/FC4 register reads and
FC1/FC2 bit reads from the simulator (strict mode, write overlays),
FC05/FC06/FC15/FC16 writes, every other function code named and refused,
chaos injection."""
import ipaddress
import logging
import socket
import struct
import threading
import time

from common.protocol import auth_handshake_server, describe_fc, recv_exact
from common.connlimit import ConnGate
from .statics import MAX_BITS, MAX_COUNT, MAX_PDU
from common.version import version_string

logger = logging.getLogger('fake-inverter')


class FakeInverter:
    def __init__(self, unit, simulator, strict=False, chaos=None, max_clients=64, client_timeout=300.0,
                 max_conn_per_ip=0, connect_acl=None, auth=None, auth_key=None):
        self.unit = unit
        self.simulator = simulator
        self.strict = strict
        self.chaos = chaos
        self.overlay = {}      # FC06/FC16 write overlay on the holding registers
        self.coils = {}        # FC05/FC15 writes + `set coil`: addr -> 0/1 (FC1 reads)
        self.discrete = {}     # `set discrete` pins: addr -> 0/1 (FC2 reads)
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
        """The connect ACL: None = off (everybody allowed — the default, the
        trusted-LAN posture); () = nobody; otherwise the ip must land in one
        network (the cache's _allowed, mirrored)."""
        if self.connect_acl is None:
            return True
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a.version == n.version and a in n for n in self.connect_acl)

    def serve(self, host, port):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(16)
        self.srv = srv
        self.listen_addr = (host, port)
        logger.info('fake inverter %s listening on %s:%d (unit %d, peak PV %gW, client limit %s, client timeout %s, per-ip limit %s, connect-acl %s, modbus auth %s)%s',
                    version_string(), host, port, self.unit, self.simulator.peak_w,
                    self.max_clients or 'none',
                    '%gs' % self.client_timeout if self.client_timeout else 'none',
                    self.conn_gate.max_per_ip or 'none',
                    'any' if self.connect_acl is None else ('none' if not self.connect_acl else '%d network(s)' % len(self.connect_acl)),
                    self.auth or 'none',
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
                txn, proto, length, unit = struct.unpack('>HHHB', recv_exact(client, 7))
                if not 2 <= length <= MAX_PDU + 2:
                    logger.info('malformed frame from %s:%d (MBAP length %d), closing', addr[0], addr[1], length)
                    break
                pdu = recv_exact(client, length - 1)
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
                if func in (3, 4) and addr_ is not None:   # holding (FC3) / input (FC4) registers
                    if not 1 <= count <= MAX_COUNT or addr_ + count > 65536:
                        # the read-count gate, the cache's shape: a declared
                        # count beyond the PDU (0xFFFF with a truncated frame)
                        # must not make the fake assemble an oversized reply
                        body = struct.pack('>BB', func + 0x80, 3)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.info('fc%d read %d regs @%d from %s:%d -> exception 03 (illegal data value)',
                                    func, count, addr_, addr[0], addr[1])
                        continue
                    regs = self.simulator.registers(func)
                    if func == 3:
                        regs.update(self.overlay)
                    if self.strict and any(addr_ + i not in regs for i in range(count)):
                        body = struct.pack('>BB', func + 0x80, 2)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.debug('fc%d read %d regs @%d -> exception 02 (undefined register)', func, count, addr_)
                        continue
                    words = [regs.get(addr_ + i, 0) & 0xFFFF for i in range(count)]
                    data = struct.pack('>%dH' % count, *words) if words else b''
                    body = struct.pack('>BB', func, count * 2) + data
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.debug('fc%d read %d regs @%d -> %s', func, count, addr_, words)
                elif func in (1, 2) and addr_ is not None:   # coils (FC1) / discrete inputs (FC2)
                    if not 1 <= count <= MAX_BITS or addr_ + count > 65536:
                        body = struct.pack('>BB', func + 0x80, 3)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.info('fc%d read %d bit(s) @%d from %s:%d -> exception 03 (illegal data value)',
                                    func, count, addr_, addr[0], addr[1])
                        continue
                    bits_map = self.simulator.registers(func)
                    bits_map.update(self.coils if func == 1 else self.discrete)
                    if self.strict and any(addr_ + i not in bits_map for i in range(count)):
                        body = struct.pack('>BB', func + 0x80, 2)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.debug('fc%d read %d bit(s) @%d -> exception 02 (undefined bit)', func, count, addr_)
                        continue
                    bits = [(bits_map.get(addr_ + i, 0) & 1) for i in range(count)]
                    packed = bytearray((count + 7) // 8)
                    for i, bit in enumerate(bits):
                        if bit:
                            packed[i >> 3] |= 1 << (i & 7)
                    body = struct.pack('>BB', func, len(packed)) + bytes(packed)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.debug('fc%d read %d bit(s) @%d -> %s', func, count, addr_, bits)
                elif func == 5 and addr_ is not None:   # write single coil: the second word is 0x0000/0xFF00
                    value = count
                    if value not in (0x0000, 0xFF00):
                        body = struct.pack('>BB', func + 0x80, 3)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.info('write: coil %d = 0x%04x from %s:%d -> exception 03 (illegal data value)',
                                    addr_, value, addr[0], addr[1])
                        continue
                    self.coils[addr_] = 1 if value else 0
                    client.sendall(struct.pack('>HHHB', txn, 0, len(pdu) + 1, unit) + pdu)
                    logger.info('write: coil %d = %d (single coil, unit %d)', addr_, self.coils[addr_], unit)
                elif func == 6 and len(pdu) == 5:
                    self.overlay[addr_] = struct.unpack('>H', pdu[3:5])[0]
                    client.sendall(struct.pack('>HHHB', txn, 0, len(pdu) + 1, unit) + pdu)
                    logger.info('write: register %d = %d (single register, unit %d)', addr_, self.overlay[addr_], unit)
                elif func == 15 and addr_ is not None and len(pdu) >= 6 and count \
                        and pdu[5] == (count + 7) // 8 and len(pdu) == 6 + pdu[5]:
                    if not 1 <= count <= MAX_BITS or addr_ + count > 65536:
                        body = struct.pack('>BB', func + 0x80, 3)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.info('write: %d coil(s) @%d from %s:%d -> exception 03 (illegal data value)',
                                    count, addr_, addr[0], addr[1])
                        continue
                    bits = ''.join(str((pdu[6 + (i >> 3)] >> (i & 7)) & 1) for i in range(count))
                    for i in range(count):
                        self.coils[addr_ + i] = (pdu[6 + (i >> 3)] >> (i & 7)) & 1
                    body = struct.pack('>BHH', func, addr_, count)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.info('write: coils %d:%d = %s (multiple coils, unit %d)',
                                addr_, count, bits, unit)
                elif func == 16 and len(pdu) >= 6 and pdu[5] == count * 2 and len(pdu) == 6 + count * 2:
                    values = struct.unpack('>%dH' % count, pdu[6:6 + count * 2])
                    for i, w in enumerate(values):
                        self.overlay[addr_ + i] = w
                    body = struct.pack('>BHH', func, addr_, count)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.info('write: registers %d:%d = %s (multiple registers, unit %d)',
                                addr_, count, list(values), unit)
                else:
                    # everything the fake does not serve is named and refused:
                    # a bad shape on an implemented FC (including a frame too
                    # short to carry its address) is exception 03 (illegal
                    # data value), an unimplemented FC is 01
                    implemented = func in (1, 2, 3, 4, 5, 6, 15, 16)
                    body = struct.pack('>BB', func + 0x80, 3 if implemented else 1)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
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
