#!/usr/bin/env python3
"""Modbus TCP wire format: the cache's frame layer on the common core
(stdlib only). The limits and codes come from lib/static.json (see statics.py)."""
import struct

from common.protocol import ModbusError


class DeviceError(ModbusError):
    """The device answered with a Modbus exception; .code carries it."""

    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


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
