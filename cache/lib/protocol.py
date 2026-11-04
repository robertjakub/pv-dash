#!/usr/bin/env python3
"""Modbus TCP wire format: constants, errors and frame helpers (stdlib only).
The limits and codes come from lib/static.json (see statics.py)."""
import struct

from .statics import MAX_PDU, MAX_COUNT, WRITE_FUNCS, ILLEGAL_FUNCTION, \
    ILLEGAL_ADDRESS, ILLEGAL_VALUE, GATEWAY_FAILED


class ModbusError(Exception):
    pass


class DeviceError(ModbusError):
    """The device answered with a Modbus exception; .code carries it."""

    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('connection closed by peer')
        buf += chunk
    return buf


def exception_frame(txn, proto, unit, func, code):
    code = max(0, min(0xFF, code))
    body = struct.pack('>BB', func | 0x80, code)
    return struct.pack('>HHHB', txn, proto, len(body) + 1, unit) + body


def describe_write(pdu, unit):
    """Human-readable description of a write request, None if not a known write."""
    if not pdu:
        return None
    func = pdu[0]
    if func == 6 and len(pdu) == 5:
        addr, value = struct.unpack('>HH', pdu[1:5])
        return 'register %d = %d (single register, unit %d)' % (addr, value, unit)
    if func == 16 and len(pdu) >= 6:
        addr, count = struct.unpack('>HH', pdu[1:5])
        n = pdu[5]
        if count and n == count * 2 and len(pdu) == 6 + n:
            values = list(struct.unpack('>%dH' % count, pdu[6:6 + n]))
            return 'registers %d:%d = %s (multiple registers, unit %d)' % (addr, count, values, unit)
        return 'multiple registers, malformed frame (unit %d)' % unit
    return None
