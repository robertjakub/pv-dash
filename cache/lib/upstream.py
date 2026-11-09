#!/usr/bin/env python3
"""The single Modbus TCP upstream connection to the inverter, shared by all threads (stdlib only)."""
import struct
import threading
import time

from common.modbus import (ClientBase, ModbusError, check_data_bytes,
                           check_head, check_reply, frame, recv_exact,
                           unpack_bits)
from .statics import BIT_READ_FUNCS, MAX_PDU


class Upstream(ClientBase):
    def __init__(self, host, port, unit, timeout, auth=None, auth_key=None):
        super().__init__(host, port, unit, timeout, auth=auth, auth_key=auth_key)
        self.lock = threading.Lock()
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

    def _exchange(self, out, want_txn):
        try:
            if not self.sock:
                self._connect()
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

    def read(self, fc, addr, count):
        """One FC1-FC4 read (coils/discrete inputs return 0/1 per address);
        the caller serializes on .lock."""
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', fc, addr, count)
        txn, proto, _, unit, body = self._exchange(frame(self.txn, self.unit, pdu), self.txn)
        check_reply(txn, proto, unit, body, self.txn, self.unit, fc)
        got = body[1]
        if fc in BIT_READ_FUNCS:
            check_data_bytes(got, (count + 7) // 8)
            return unpack_bits(body[2:2 + got], count)
        check_data_bytes(got, count * 2, 'register')
        return struct.unpack('>%dH' % count, body[2:2 + got])

    def forward(self, out):
        """Send a client frame verbatim and return the response frame."""
        want = struct.unpack('>H', out[0:2])[0]
        txn, proto, length, unit, body = self._exchange(out, want)
        return frame(txn, unit, body, proto=proto)
