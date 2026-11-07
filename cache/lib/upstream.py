#!/usr/bin/env python3
"""The single Modbus TCP upstream connection to the inverter, shared by all threads (stdlib only)."""
import socket
import struct
import threading
import time

from common.protocol import ModbusError, auth_handshake_client, recv_exact, waveshare_handshake_client
from .protocol import DeviceError
from .statics import MAX_PDU


class Upstream:
    def __init__(self, host, port, unit, timeout, auth=None, auth_key=None):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.auth = auth          # None = no auth | 'suite' = the crypt handshake after every connect
                                  # | 'waveshare' = the Waveshare gateway connection password after every connect
        self.auth_key = auth_key  # the shared key the handshake proves
        self.lock = threading.Lock()
        self.sock = None
        self.txn = 0
        self.exchanges = 0         # completed request/reply exchanges
        self.connects = 0          # successful connects (2 = one reconnect)
        self.errors = 0            # failed exchanges (timeout, reset, bad frame)
        self.last_error = None     # the text of the last failure
        self.last_error_at = None  # monotonic
        self.connected_since = None
        self.bytes_in = 0
        self.bytes_out = 0

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
        if self.auth == 'suite' and self.auth_key:
            auth_handshake_client(self.sock, self.auth_key)
        elif self.auth == 'waveshare' and self.auth_key:
            waveshare_handshake_client(self.sock, self.auth_key)
        self.connects += 1
        self.connected_since = time.monotonic()

    def _recv_exact(self, n):
        try:
            return recv_exact(self.sock, n)
        except OSError as e:
            raise ModbusError(str(e))

    def _exchange(self, frame, want_txn):
        try:
            if not self.sock:
                self._connect()
            self.sock.sendall(frame)
            self.bytes_out += len(frame)
            head = self._recv_exact(7)
            self.bytes_in += len(head)
            txn, proto, length, unit = struct.unpack('>HHHB', head)
            if not 2 <= length <= MAX_PDU + 2:
                raise ModbusError('bad response length %d' % length)
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
        """One FC3/FC4 read; the caller serializes on .lock."""
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', fc, addr, count)
        _, _, _, unit, body = self._exchange(struct.pack('>HHHB', self.txn, 0, len(pdu) + 1, self.unit) + pdu, self.txn)
        if unit != self.unit:
            raise ModbusError('reply from unit id %d, expected %d' % (unit, self.unit))
        func = body[0]
        if func == fc + 0x80:
            code = body[1] if len(body) > 1 else -1
            raise DeviceError('FC%d modbus exception, code %d' % (fc, code), code)
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
