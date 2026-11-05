#!/usr/bin/env python3
"""Modbus TCP wire format and the single-client poller connection (stdlib only).
The limits come from lib/static.json (see statics.py)."""
import socket
import struct

from common.protocol import ModbusError, recv_exact
from .statics import MAX_PDU, MAX_COUNT


class ModbusTCP:
    """FC3/FC4 register client; connects lazily, reconnects on any error."""

    def __init__(self, host, port, unit, timeout, offset=0):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.offset = offset
        self.sock = None
        self.txn = 0

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def apply(self, host=None, port=None, unit=None, timeout=None):
        """Update the endpoint; the socket reconnects on the next read."""
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        if unit is not None:
            self.unit = unit
        if timeout is not None:
            self.timeout = timeout

    def _recv_exact(self, n):
        try:
            return recv_exact(self.sock, n)
        except OSError as e:
            raise ModbusError(str(e))

    def _connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def read_registers(self, addr, count, fc=3):
        if not 1 <= count <= MAX_COUNT:
            raise ModbusError('register count %d out of range' % count)
        if not self.sock:
            self._connect()
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', fc, addr + self.offset, count)
        self.sock.sendall(struct.pack('>HHHB', self.txn, 0, len(pdu) + 1, self.unit) + pdu)
        txn, proto, length, unit = struct.unpack('>HHHB', self._recv_exact(7))
        if not 2 <= length <= MAX_PDU + 2:
            raise ModbusError('bad response length %d' % length)
        body = self._recv_exact(length - 1)
        if txn != self.txn:
            raise ModbusError('transaction id mismatch')
        if proto != 0:
            raise ModbusError('unexpected protocol id %d' % proto)
        if unit != self.unit:
            raise ModbusError('reply from unit id %d, expected %d' % (unit, self.unit))
        func = body[0]
        if func == fc + 0x80:
            raise ModbusError('modbus exception, code %d' % (body[1] if len(body) > 1 else -1))
        if func != fc:
            raise ModbusError('unexpected function byte 0x%02x' % func)
        if len(body) < 2:
            raise ModbusError('short response: function byte only')
        got = body[1]
        if got != count * 2:
            raise ModbusError('expected %d register bytes, got %d' % (count * 2, got))
        return struct.unpack('>%dH' % count, body[2:2 + got])

    def read_i32(self, addr, fc=3):
        hi, lo = self.read_registers(addr, 2, fc=fc)
        return struct.unpack('>i', struct.pack('>HH', hi, lo))[0]
