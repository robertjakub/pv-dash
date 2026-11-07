#!/usr/bin/env python3
"""The fake inverter's Modbus TCP server: FC3 reads from the simulator
(strict mode, write overlay), FC06/16 writes, every other function code
named and refused, chaos injection."""
import ipaddress
import logging
import socket
import struct
import threading
import time

from common.protocol import describe_fc, recv_exact
from common.connlimit import ConnGate
from .statics import MAX_COUNT, MAX_PDU
from common.version import version_string

logger = logging.getLogger('fake-inverter')


class FakeInverter:
    def __init__(self, unit, simulator, strict=False, chaos=None, max_clients=64, client_timeout=300.0,
                 max_conn_per_ip=0, connect_acl=None):
        self.unit = unit
        self.simulator = simulator
        self.strict = strict
        self.chaos = chaos
        self.overlay = {}
        self.srv = None
        self.listen_addr = None
        self.stopping = False
        self.conns = 0
        self.requests = 0
        self.max_clients = max(0, int(max_clients))       # 0 = no limit
        self.client_timeout = max(0.0, float(client_timeout))   # 0 = never
        self.conn_gate = ConnGate(0, max(0, int(max_conn_per_ip)))   # 0 = no per-IP limit
        self.connect_acl = connect_acl    # None = any (the default); () = none; networks = the allow list
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
        logger.info('fake inverter %s listening on %s:%d (unit %d, peak PV %gW, client limit %s, client timeout %s, per-ip limit %s, connect-acl %s)%s',
                    version_string(), host, port, self.unit, self.simulator.peak_w,
                    self.max_clients or 'none',
                    '%gs' % self.client_timeout if self.client_timeout else 'none',
                    self.conn_gate.max_per_ip or 'none',
                    'any' if self.connect_acl is None else ('none' if not self.connect_acl else '%d network(s)' % len(self.connect_acl)),
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
                func, addr_, count = struct.unpack('>BHH', pdu[:5])
                if unit != self.unit:
                    logger.debug('request for unit %d, serving %d', unit, self.unit)
                if self.chaos and self.chaos.hit():
                    self._chaos_fault(client, txn, self.unit)
                if func in (3, 4):   # the same map over holding (FC3) and input (FC4) registers
                    if not 1 <= count <= MAX_COUNT or addr_ + count > 65536:
                        # the read-count gate, the cache's shape: a declared
                        # count beyond the PDU (0xFFFF with a truncated frame)
                        # must not make the fake assemble an oversized reply
                        body = struct.pack('>BB', func + 0x80, 3)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.info('fc%d read %d regs @%d from %s:%d -> exception 03 (illegal data value)',
                                    func, count, addr_, addr[0], addr[1])
                        continue
                    regs = self.simulator.registers()
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
                elif func == 6 and len(pdu) == 5:
                    self.overlay[addr_] = struct.unpack('>H', pdu[3:5])[0]
                    client.sendall(struct.pack('>HHHB', txn, 0, len(pdu) + 1, unit) + pdu)
                    logger.info('write: register %d = %d (single register, unit %d)', addr_, self.overlay[addr_], unit)
                elif func == 16 and len(pdu) >= 6 and pdu[5] == count * 2 and len(pdu) == 6 + count * 2:
                    values = struct.unpack('>%dH' % count, pdu[6:6 + count * 2])
                    for i, w in enumerate(values):
                        self.overlay[addr_ + i] = w
                    body = struct.pack('>BHH', func, addr_, count)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.info('write: registers %d:%d = %s (multiple registers, unit %d)',
                                addr_, count, list(values), unit)
                else:
                    # every other function code is named and refused: a
                    # malformed shape on an implemented write is exception 03
                    # (illegal data value), an unimplemented FC is 01
                    malformed = func in (6, 16)
                    body = struct.pack('>BB', func + 0x80, 3 if malformed else 1)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.info('rejected %s from %s:%d (%s)', describe_fc(func), addr[0], addr[1],
                                'malformed frame' if malformed else 'illegal function')
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
