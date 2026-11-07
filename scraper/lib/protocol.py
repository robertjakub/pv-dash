#!/usr/bin/env python3
"""Modbus TCP wire format and the single-client poller connection (stdlib only).
The limits come from lib/static.json (see statics.py)."""
import socket
import struct

from common.protocol import ModbusError, auth_handshake_client, recv_exact
from .statics import MAX_BITS, MAX_PDU, MAX_COUNT


class ModbusTCP:
    """FC1-FC4 read client (word and bit spaces); connects lazily,
    reconnects on any error.
    The suite auth (auth='suite' + a >=16-char key) handshakes right after
    every connect: the peer answers OK and the session speaks plain Modbus,
    or ERR and the connection fails like any other."""

    def __init__(self, host, port, unit, timeout, offset=0, auth=None, auth_key=None):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.offset = offset
        self.auth = auth          # None = no auth | 'suite' = the crypt handshake
        self.auth_key = auth_key  # the shared key the handshake proves
        self.sock = None
        self.txn = 0

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    _UNSET = object()

    def apply(self, host=None, port=None, unit=None, timeout=None, auth=_UNSET, auth_key=_UNSET):
        """Update the endpoint (and the auth material); the socket
        reconnects on the next read. The auth kwargs are positional-aware:
        pass them explicitly (None included — a reload that disables the
        suite auth must reach the client)."""
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        if unit is not None:
            self.unit = unit
        if timeout is not None:
            self.timeout = timeout
        if auth is not self._UNSET:
            self.auth = auth
        if auth_key is not self._UNSET:
            self.auth_key = auth_key

    def _recv_exact(self, n):
        try:
            return recv_exact(self.sock, n)
        except OSError as e:
            raise ModbusError(str(e))

    def _connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        if self.auth == 'suite' and self.auth_key:
            auth_handshake_client(self.sock, self.auth_key)

    def read_registers(self, addr, count, fc=3):
        if not 1 <= count <= MAX_COUNT:
            raise ModbusError('register count %d out of range' % count)
        words = self._read(fc, addr, count, expect=lambda c: c * 2)
        return struct.unpack('>%dH' % count, words)

    def read_bits(self, addr, count, fc=1):
        """One FC1 (coils) / FC2 (discrete inputs) read: count bits, packed
        8 per byte, LSB first — returned as 0/1 per address."""
        if not 1 <= count <= MAX_BITS:
            raise ModbusError('bit count %d out of range' % count)
        raw = self._read(fc, addr, count, expect=lambda c: (c + 7) // 8)
        return tuple((raw[i >> 3] >> (i & 7)) & 1 for i in range(count))

    def _read(self, fc, addr, count, expect):
        """The shared read exchange: pack, send, validate the MBAP and the
        reply shape, return the raw data bytes (the caller decodes)."""
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
            raise ModbusError('FC%d modbus exception, code %d' % (fc, body[1] if len(body) > 1 else -1))
        if func != fc:
            raise ModbusError('unexpected function byte 0x%02x' % func)
        if len(body) < 2:
            raise ModbusError('short response: function byte only')
        got = body[1]
        want = expect(count)
        if got != want:
            raise ModbusError('expected %d data bytes, got %d' % (want, got))
        return body[2:2 + got]

    def read_i32(self, addr, fc=3):
        hi, lo = self.read_registers(addr, 2, fc=fc)
        return struct.unpack('>i', struct.pack('>HH', hi, lo))[0]
