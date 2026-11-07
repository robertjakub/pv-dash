#!/usr/bin/env python3
"""Modbus TCP wire format: the cache's frame layer on the common core
(stdlib only). The limits and codes come from lib/static.json (see statics.py)."""
import struct

from common.modbus import ModbusError, describe_fc


class DeviceError(ModbusError):
    """The device answered with a Modbus exception; .code carries it."""

    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


def describe_write(pdu, unit):
    """Human-readable description of a write request, None if not a known
    write. Every write function code describes — the value and the span,
    or the malformed-frame note when the shape is wrong."""
    if not pdu:
        return None
    func = pdu[0]
    if func == 5:                    # write single coil: addr, value (0x0000/0xff00)
        if len(pdu) == 5:
            addr, value = struct.unpack('>HH', pdu[1:5])
            if value in (0x0000, 0xFF00):
                return 'coil %d = %d (single coil, unit %d)' % (addr, 1 if value else 0, unit)
        return 'single coil, malformed frame (unit %d)' % unit
    if func == 6:                    # write single register: addr, value
        if len(pdu) == 5:
            addr, value = struct.unpack('>HH', pdu[1:5])
            return 'register %d = %d (single register, unit %d)' % (addr, value, unit)
        return 'single register, malformed frame (unit %d)' % unit
    if func == 15:                   # write multiple coils: addr, count, byte count, bits
        if len(pdu) >= 6:
            addr, count = struct.unpack('>HH', pdu[1:5])
            n = pdu[5]
            if count and n == (count + 7) // 8 and len(pdu) == 6 + n:
                bits = ''.join(str((pdu[6 + (i >> 3)] >> (i & 7)) & 1) for i in range(count))
                return 'coils %d:%d = %s (multiple coils, unit %d)' % (addr, count, bits, unit)
        return 'multiple coils, malformed frame (unit %d)' % unit
    if func == 16:                   # write multiple registers: addr, count, byte count, words
        if len(pdu) >= 6:
            addr, count = struct.unpack('>HH', pdu[1:5])
            n = pdu[5]
            if count and n == count * 2 and len(pdu) == 6 + n:
                values = list(struct.unpack('>%dH' % count, pdu[6:6 + n]))
                return 'registers %d:%d = %s (multiple registers, unit %d)' % (addr, count, values, unit)
        return 'multiple registers, malformed frame (unit %d)' % unit
    if func == 22:                   # mask write register: addr, and-mask, or-mask
        if len(pdu) == 7:
            addr, and_mask, or_mask = struct.unpack('>HHH', pdu[1:7])
            return 'register %d and=%04x or=%04x (mask write, unit %d)' % (addr, and_mask, or_mask, unit)
        return 'mask write, malformed frame (unit %d)' % unit
    if func == 23:                   # read/write multiple registers: read addr/count,
        if len(pdu) >= 11:           # write addr/count, byte count, words
            raddr, rcount, waddr, wcount = struct.unpack('>HHHH', pdu[1:9])
            n = pdu[9]
            if wcount and n == wcount * 2 and len(pdu) == 10 + n:
                values = list(struct.unpack('>%dH' % wcount, pdu[10:10 + n]))
                return 'registers %d:%d = %s, read back %d:%d (read/write multiple registers, unit %d)' % (
                    waddr, wcount, values, raddr, rcount, unit)
        return 'read/write multiple registers, malformed frame (unit %d)' % unit
    return None
