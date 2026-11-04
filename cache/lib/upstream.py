#!/usr/bin/env python3
"""The single Modbus TCP upstream connection to the inverter, shared by all threads (stdlib only)."""
import socket
import struct
import threading

from .protocol import MAX_PDU, ModbusError, DeviceError, recv_exact


class Upstream:
    def __init__(self, host, port, unit, timeout):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.lock = threading.Lock()
        self.sock = None
        self.txn = 0

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def _recv_exact(self, n):
        try:
            return recv_exact(self.sock, n)
        except OSError as e:
            raise ModbusError(str(e))

    def _exchange(self, frame, want_txn):
        if not self.sock:
            self._connect()
        self.sock.sendall(frame)
        txn, proto, length, unit = struct.unpack('>HHHB', self._recv_exact(7))
        if not 2 <= length <= MAX_PDU + 2:
            raise ModbusError('bad response length %d' % length)
        body = self._recv_exact(length - 1)
        if txn != want_txn:
            raise ModbusError('transaction id mismatch')
        if proto != 0:
            raise ModbusError('unexpected protocol id %d' % proto)
        return txn, proto, length, unit, body

    def read(self, fc, addr, count):
        """One FC3/FC4 read; the caller serializes on .lock."""
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', fc, addr, count)
        _, _, _, unit, body = self._exchange(struct.pack('>HHHB', self.txn, 0, len(pdu) + 1, self.unit) + pdu, self.txn)
        if unit != self.unit:
            raise ModbusError('reply from unit id %d, expected %d' % (unit, self.unit))
        func = body[0]
        if func == fc + 0x80:
            raise DeviceError('modbus exception, code %d' % (body[1] if len(body) > 1 else -1),
                              body[1] if len(body) > 1 else -1)
        if func != fc:
            raise ModbusError('unexpected function byte 0x%02x' % func)
        if len(body) < 2:
            raise ModbusError('short response: function byte only')
        got = body[1]
        if got != count * 2:
            raise ModbusError('expected %d register bytes, got %d' % (count * 2, got))
        return struct.unpack('>%dH' % count, body[2:2 + got])

    def forward(self, frame):
        """Send a client frame verbatim and return the response frame."""
        want = struct.unpack('>H', frame[0:2])[0]
        txn, proto, length, unit, body = self._exchange(frame, want)
        return struct.pack('>HHHB', txn, proto, length, unit) + body
