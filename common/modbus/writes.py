"""The shared write shapes (stdlib only): the human description, the
touched span and the consistency check for every write function code —
the cache's gate vets with them, the fake inverter parses its own writes
with them. The FC23 note: the request reads first and writes second, so
the WRITE span is the second address pair — the gate vets what is written."""
import struct


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


def write_target(pdu):
    """The register span a write request touches: (addr, count) for the
    known write function codes, None when the frame is too short to tell."""
    if len(pdu) < 5:
        return None
    func = pdu[0]
    if func in (5, 6, 22):          # single register (coil / register / mask-write)
        addr = struct.unpack('>H', pdu[1:3])[0]
        return addr, 1
    if func == 23:                  # read/write multiple: read addr/count, write addr/count
        if len(pdu) < 10:
            return None
        addr, count = struct.unpack('>HH', pdu[5:9])
        return addr, count
    if func in (15, 16):            # multiple registers/coils
        addr, count = struct.unpack('>HH', pdu[1:5])
        return addr, count
    return None


def write_shape_error(pdu):
    """None when an FC15/FC16 frame's declared counts are consistent (the
    byte-count byte matches the data actually present, the register count
    is at least 1); the reason otherwise. FC5/6/22 carry no byte-count
    byte and FC23's is the device's call — None for them (the too-short
    check already answered what it could)."""
    func = pdu[0]
    if func not in (15, 16):
        return None
    if len(pdu) < 6:
        return 'the byte-count byte is missing'
    count = struct.unpack('>H', pdu[3:5])[0]
    n = pdu[5]
    want = count * 2 if func == 16 else (count + 7) // 8
    if count < 1:
        return 'register count %d is zero' % count
    if n != want:
        return 'the byte count is %d, the register count needs %d' % (n, want)
    if len(pdu) != 6 + n:
        return 'the frame carries %d data byte(s), the byte count says %d' % (len(pdu) - 6, n)
    return None
