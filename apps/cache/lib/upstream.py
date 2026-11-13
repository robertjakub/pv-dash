#!/usr/bin/env python3
"""The single Modbus TCP upstream connection to the inverter, shared by all threads (stdlib only)."""
import struct
import threading

from common.modbus import (ClientBase, check_data_bytes, check_reply,
                           frame, unpack_bits)
from common.modbus.trace import KIND_REQ, KIND_RSP, KIND_RAW_C2D
from .statics import BIT_READ_FUNCS
from .tracefeed import UPSTREAM_CONN_BASE


class Upstream(ClientBase):
    def __init__(self, host, port, unit, timeout, auth=None, auth_key=None):
        super().__init__(host, port, unit, timeout, auth=auth, auth_key=auth_key)
        self.lock = threading.Lock()
        self.tracer = None   # the record feed's emit (the proxy's hub) — None = no feed

    def _emit(self, kind, raw, note=''):
        """One upstream-face wire record: the device conversation lives in
        its own conn space (UPSTREAM_CONN_BASE + the connection serial —
        never colliding with the client face's ids), the peer is the device
        endpoint, the poller's and the forwards' records ride the same
        face."""
        if self.tracer:
            self.tracer('upstream', kind, UPSTREAM_CONN_BASE + self.connects,
                        '%s:%d' % (self.host, self.port), note, raw)

    def after_connect(self):
        """The connect's byte-less marker: the auth handshake (when armed)
        ran inside open_socket — the feed shows it happened, the proof and
        the password never ride (the cache knows its own handshake, unlike
        the replay's dumb pipe tap)."""
        super().after_connect()
        if self.auth == 'suite' and self.auth_key:
            self._emit(KIND_RAW_C2D, b'', 'PVA1 handshake (bytes withheld)')
        elif self.auth == 'waveshare' and self.auth_key:
            self._emit(KIND_RAW_C2D, b'', 'waveshare password (bytes withheld)')

    def read(self, fc, addr, count):
        """One FC1-FC4 read (coils/discrete inputs return 0/1 per address);
        the caller serializes on .lock. The poller voice: the request and
        the validated reply both ride the feed — a failed exchange rides no
        reply record (the orphan is the device-died signal)."""
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', fc, addr, count)
        out = frame(self.txn, self.unit, pdu)
        self._emit(KIND_REQ, out, 'poll')
        txn, proto, _, unit, body = self._exchange(out, self.txn)
        check_reply(txn, proto, unit, body, self.txn, self.unit, fc)
        self._emit(KIND_RSP, struct.pack('>HHH', txn, proto, 1 + len(body)) + bytes((unit,)) + body)
        got = body[1]
        if fc in BIT_READ_FUNCS:
            check_data_bytes(got, (count + 7) // 8)
            return unpack_bits(body[2:2 + got], count)
        check_data_bytes(got, count * 2, 'register')
        return struct.unpack('>%dH' % count, body[2:2 + count * 2])

    def forward(self, out):
        """Send a client frame verbatim and return the response frame. The
        forward voice: the client's own txn survives (the client-face
        record of the same request pairs by eye), a failed exchange leaves
        the request orphaned — the client face answers the in-band
        GATEWAY_FAILED."""
        want = struct.unpack('>H', out[0:2])[0]
        self._emit(KIND_REQ, out)
        txn, proto, length, unit, body = self._exchange(out, want)
        self._emit(KIND_RSP, struct.pack('>HHH', txn, proto, length) + bytes((unit,)) + body)
        return frame(txn, unit, body, proto=proto)
