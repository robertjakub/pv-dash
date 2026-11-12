#!/usr/bin/env python3
"""Modbus TCP wire format and the single-client poller connection (stdlib only).
The limits come from lib/defaults.json (see statics.py); the framing and the
reply ladders are the shared common.modbus ones."""
import struct
import time

from common.modbus import (ClientBase, ModbusError, check_data_bytes,
                           check_head, check_reply, frame, recv_exact,
                           unpack_bits)
from .statics import MAX_BITS, MAX_PDU, MAX_COUNT


class ModbusTCP(ClientBase):
    """FC1-FC4 read client (word and bit spaces); connects lazily,
    reconnects on any error.
    The suite auth (auth='suite' + a >=16-char key) handshakes right after
    every connect: the peer answers OK and the session speaks plain Modbus,
    or ERR and the connection fails like any other.
    The session counters mirror the cache's Upstream (connects, exchanges,
    bytes, errors) — `show uplink` renders them and a later hoist to
    ClientBase is a move, not a rename. The poll thread is the only writer;
    the control thread reads the plain attributes (the cache's report does
    the same)."""

    _UNSET = object()

    def __init__(self, host, port, unit, timeout, offset=0, auth=None, auth_key=None):
        super().__init__(host, port, unit, timeout, auth=auth, auth_key=auth_key)
        self.offset = offset
        self.exchanges = 0         # completed request/reply exchanges
        self.connects = 0          # successful connects (2 = one reconnect)
        self.errors = 0            # failed exchanges (timeout, reset, bad frame)
        self.last_error = None     # the text of the last failure
        self.last_error_at = None  # monotonic
        self.connected_since = None
        self.bytes_in = 0
        self.bytes_out = 0

    def after_connect(self):
        self.connects += 1
        self.connected_since = time.monotonic()

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

    def _exchange(self, pdu, want_txn):
        """The wire exchange with the session accounting (the cache's
        Upstream._exchange shape): send + the two recvs count the bytes,
        any failure lands in errors/last_error and re-raises."""
        try:
            if not self.sock:
                self._connect()
            out = frame(want_txn, self.unit, pdu)
            self.sock.sendall(out)
            self.bytes_out += len(out)
            head = self._recv_exact(7)
            self.bytes_in += len(head)
            txn, proto, length, unit = check_head(head, MAX_PDU)
            body = self._recv_exact(length - 1)
            self.bytes_in += len(body)
            if txn != want_txn:
                raise ModbusError('transaction id mismatch')
            if proto != 0:
                raise ModbusError('unexpected protocol id %d' % proto)
        except (ModbusError, OSError) as e:
            self.errors += 1
            self.last_error = str(e)
            self.last_error_at = time.monotonic()
            raise
        self.exchanges += 1
        return txn, proto, length, unit, body

    def _read(self, fc, addr, count, expect):
        """The shared read exchange: pack, send, validate the MBAP and the
        reply shape, return the raw data bytes (the caller decodes)."""
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', fc, addr + self.offset, count)
        txn, proto, length, unit, body = self._exchange(pdu, self.txn)
        check_reply(txn, proto, unit, body, self.txn, self.unit, fc)
        got = body[1]
        check_data_bytes(got, expect(count))
        return body[2:2 + got]
