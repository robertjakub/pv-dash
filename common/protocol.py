"""The Modbus TCP wire core shared by the tools (stdlib only): the error
type, the recv-exact loop, the exception-frame builder and the function
code table. The client (scraper, cache upstream) and the servers (cache
listener, fake inverter) layer their own framing on top; the per-tool
limits come from each tool's lib/static.json (see its statics.py)."""
import struct


class ModbusError(Exception):
    pass


# Every standard Modbus function code (the spec's public list, serial-line
# and TCP): the one table the whole family names the wire with. Codes
# outside it (the vendor blocks, the reserved gaps) describe as bare FC<n>.
FC_NAMES = {
    1: 'read coils',
    2: 'read discrete inputs',
    3: 'read holding registers',
    4: 'read input registers',
    5: 'write single coil',
    6: 'write single register',
    7: 'read exception status',
    8: 'diagnostics',
    11: 'get comm event counter',
    12: 'get comm event log',
    13: 'program 484',
    14: 'poll 484',
    15: 'write multiple coils',
    16: 'write multiple registers',
    17: 'report slave id',
    18: 'program 884',
    19: 'reset comm link 884',
    20: 'read file record',
    21: 'write file record',
    22: 'mask write register',
    23: 'read/write multiple registers',
    24: 'read fifo queue',
    43: 'read device identification',
}


def describe_fc(func):
    """The named form of a function code: 'FC6 (write single register)';
    'FC%d' alone when the code has no standard name (vendor blocks,
    reserved gaps)."""
    name = FC_NAMES.get(func)
    return 'FC%d (%s)' % (func, name) if name else 'FC%d' % func


def recv_exact(sock, n):
    """Read exactly n bytes or raise ConnectionError (an OSError subclass —
    callers that wrap OSErrors into ModbusError keep working)."""
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
