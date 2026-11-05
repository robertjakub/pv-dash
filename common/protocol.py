"""The Modbus TCP wire core shared by the tools (stdlib only): the error
type, the recv-exact loop and the exception-frame builder. The client
(scraper, cache upstream) and the servers (cache listener, fake inverter)
layer their own framing on top; the per-tool limits come from each tool's
lib/static.json (see its statics.py)."""
import struct


class ModbusError(Exception):
    pass


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
