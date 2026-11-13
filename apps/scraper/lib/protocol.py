#!/usr/bin/env python3
"""Modbus TCP wire format and the single-client poller connection (stdlib only).
The limits come from lib/defaults.json (see statics.py); the framing, the
session counters and the reply ladders are the shared common.modbus ones."""
import struct

from common.modbus import (ClientBase, ModbusError, check_data_bytes,
                           check_reply, frame, unpack_bits)
from .statics import MAX_BITS, MAX_COUNT


class ModbusTCP(ClientBase):
    """FC1-FC4 read client (word and bit spaces); connects lazily,
    reconnects on any error.
    The suite auth (auth='suite' + a >=16-char key) handshakes right after
    every connect: the peer answers OK and the session speaks plain Modbus,
    or ERR and the connection fails like any other.
    The session counters ride ClientBase (connects, exchanges, bytes,
    errors — `show uplink` renders them). The poll thread is the only
    writer; the control thread reads the plain attributes (the cache's
    report does the same)."""

    _UNSET = object()

    def __init__(self, host, port, unit, timeout, offset=0, auth=None, auth_key=None):
        super().__init__(host, port, unit, timeout, auth=auth, auth_key=auth_key)
        self.offset = offset

    def apply(self, host=None, port=None, unit=None, timeout=None, offset=None, auth=_UNSET, auth_key=_UNSET):
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
        if offset is not None:
            self.offset = offset
        if timeout is not None:
            self.timeout = timeout
        if auth is not self._UNSET:
            self.auth = auth
        if auth_key is not self._UNSET:
            self.auth_key = auth_key

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
        return unpack_bits(raw, count)

    def _read(self, fc, addr, count, expect):
        """The shared read exchange: pack, send, validate the MBAP and the
        reply shape, return the raw data bytes (the caller decodes)."""
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', fc, addr + self.offset, count)
        txn, proto, length, unit, body = self._exchange(frame(self.txn, self.unit, pdu), self.txn)
        check_reply(txn, proto, unit, body, self.txn, self.unit, fc)
        got = body[1]
        check_data_bytes(got, expect(count))
        return body[2:2 + got]
