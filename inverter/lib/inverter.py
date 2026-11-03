#!/usr/bin/env python3
"""The fake inverter's Modbus TCP server: FC3 reads from the simulator
(strict mode, write overlay), FC06/16 writes, chaos injection."""
import logging
import socket
import struct
import threading
import time

from .protocol import recv_exact
from .version import version_string

logger = logging.getLogger('fake-inverter')


class FakeInverter:
    def __init__(self, unit, simulator, strict=False, chaos=None):
        self.unit = unit
        self.simulator = simulator
        self.strict = strict
        self.chaos = chaos
        self.overlay = {}
        self.srv = None
        self.stopping = False
        self.conns = 0
        self.requests = 0

    def serve(self, host, port):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(4)
        self.srv = srv
        logger.info('fake inverter %s listening on %s:%d (unit %d, peak PV %gW)%s',
                    version_string(),
                    host, port, self.unit, self.simulator.peak_w,
                    ', chaos p=%.2f' % self.chaos.p if self.chaos and self.chaos.p else '')
        while True:
            try:
                client, addr = srv.accept()
                threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
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
        try:
            while True:
                self.requests += 1
                txn, proto, length, unit = struct.unpack('>HHHB', recv_exact(client, 7))
                if not 2 <= length <= 260:
                    logger.info('malformed frame from %s:%d (MBAP length %d), closing', addr[0], addr[1], length)
                    break
                pdu = recv_exact(client, length - 1)
                func, addr_, count = struct.unpack('>BHH', pdu[:5])
                if unit != self.unit:
                    logger.debug('request for unit %d, serving %d', unit, self.unit)
                if self.chaos and self.chaos.hit():
                    self._chaos_fault(client, txn, self.unit)
                if func == 3:
                    regs = self.simulator.registers()
                    regs.update(self.overlay)
                    if self.strict and any(addr_ + i not in regs for i in range(count)):
                        body = struct.pack('>BB', 3 + 0x80, 2)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.debug('read %d regs @%d -> exception 02 (undefined register)', count, addr_)
                        continue
                    words = [regs.get(addr_ + i, 0) & 0xFFFF for i in range(count)]
                    data = struct.pack('>%dH' % count, *words) if words else b''
                    body = struct.pack('>BB', func, count * 2) + data
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.debug('read %d regs @%d -> %s', count, addr_, words)
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
                    body = struct.pack('>BB', func + 0x80, 1 if func not in (6, 16) else 3)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.info('rejected FC%d from %s:%d (illegal function)', func, addr[0], addr[1])
        except (ConnectionError, OSError) as e:
            logger.info('client %s:%d disconnected (%s)', *addr[:2], e)
        except struct.error as e:
            logger.info('malformed frame from %s:%d (%s)', addr[0], addr[1], e)
        except Exception as e:
            logger.error('error handling %s:%d: %s', *addr[:2], e)
        finally:
            client.close()
