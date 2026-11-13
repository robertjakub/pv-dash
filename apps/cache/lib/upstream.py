#!/usr/bin/env python3
"""The single Modbus TCP upstream connection to the inverter, shared by all threads (stdlib only)."""
import struct
import threading

from common.modbus import (ClientBase, check_data_bytes, check_reply,
                           frame, unpack_bits)
from .statics import BIT_READ_FUNCS


class Upstream(ClientBase):
    def __init__(self, host, port, unit, timeout, auth=None, auth_key=None):
        super().__init__(host, port, unit, timeout, auth=auth, auth_key=auth_key)
        self.lock = threading.Lock()

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
