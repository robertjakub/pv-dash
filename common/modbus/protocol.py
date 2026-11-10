"""The Modbus TCP wire core shared by the tools (stdlib only): the error
types, the recv-exact loop, the exception-frame builder, the MBAP framing
helpers, the bit packing, the function code table, the suite auth
handshake and the Waveshare connection-password handshake. The client
(scraper, cache upstream) and the servers (cache listener, fake inverter)
layer their own framing on top; the family's protocol limits live in
protocol.json beside this module (one tree, no per-tool drift) — the
tools' lib/statics.py alias them."""
import hashlib
import hmac
import json
import os
import secrets
import struct

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'protocol.json'), encoding='utf-8') as _f:
    PROTOCOL = json.load(_f)                 # the family's one protocol tree


def unit_in_range(unit):
    """The MBAP unit-id validity per protocol.json: 1..247 — 0 is the
    broadcast id and 248-255 are reserved, and neither reaches a server."""
    lo, hi = PROTOCOL['unit_id_range']
    return lo <= unit <= hi


class ModbusError(Exception):
    pass


class DeviceError(ModbusError):
    """The device answered with a Modbus exception; .code carries it."""

    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


# --- the suite auth handshake ------------------------------------------------
# One round trip, client-speaks-first: after the TCP connect (and before any
# Modbus frame) the client proves the shared key — a fresh 16-byte nonce plus
# the HMAC-SHA256 of the domain-tagged magic+nonce, 52 bytes on the wire — and
# waits for the server's verdict. OK and the session speaks plain Modbus; ERR
# (or anything else) and the connection is dead: the client raises, the
# connector fails, the usual reconnect logic tries again.
AUTH_MAGIC = b'PVA1'          # the handshake marker (also the scheme version)
AUTH_NONCE_LEN = 16           # the fresh challenge bytes
AUTH_MAC_LEN = 32             # HMAC-SHA256
AUTH_FRAME_LEN = 4 + AUTH_NONCE_LEN + AUTH_MAC_LEN   # 52 bytes, fixed
AUTH_MIN_KEY = 16             # the shared key's floor (characters)
AUTH_DOMAIN = b'pv-suite-modbus-auth\x01'
AUTH_OK = b'OK'
AUTH_ERR = b'ERR'


def auth_mac(key, nonce):
    """The handshake proof: HMAC-SHA256 over the domain + magic + nonce,
    keyed by the shared key (str)."""
    return hmac.new(key.encode('utf-8'), AUTH_DOMAIN + AUTH_MAGIC + nonce,
                    hashlib.sha256).digest()


def auth_handshake_client(sock, key):
    """The client side: send magic + nonce + mac, then wait for the verdict.
    Returns on OK; raises ModbusError on ERR (key mismatch — the peer refuses
    the session) or on anything else it reads instead (a peer without the
    suite auth enabled answers a Modbus exception frame, not a verdict)."""
    nonce = secrets.token_bytes(AUTH_NONCE_LEN)
    sock.sendall(AUTH_MAGIC + nonce + auth_mac(key, nonce))
    head = recv_exact(sock, 1)
    if head == b'O':
        if recv_exact(sock, 1) == b'K':
            return
        raise ModbusError('bad auth handshake reply')
    if head == b'E' and recv_exact(sock, 2) == b'RR':
        raise ModbusError('auth handshake rejected by the peer (key mismatch?)')
    raise ModbusError('bad auth handshake reply')


def auth_handshake_server(sock, key):
    """The server side: read the 52-byte handshake, check the magic and the
    mac. True (after the OK reply) when the peer proved the key; False
    (after the ERR reply) when it did not — the caller logs and closes.
    OSError/ConnectionError propagate (the transport died mid-handshake)."""
    frame = recv_exact(sock, AUTH_FRAME_LEN)
    if frame[:4] == AUTH_MAGIC and \
       hmac.compare_digest(frame[4 + AUTH_NONCE_LEN:], auth_mac(key, frame[4:4 + AUTH_NONCE_LEN])):
        sock.sendall(AUTH_OK)
        return True
    sock.sendall(AUTH_ERR)
    return False


# --- the Waveshare TCP connection password -----------------------------------
# The Waveshare RS485-to-TCP gateways guard their serial side with an
# optional connection password: the first bytes on a fresh TCP connection
# are the password itself — raw ASCII, no framing, no length prefix — and
# the gateway answers OK (the session speaks plain Modbus from there) or
# anything else / nothing at all (the connection is dead: the client
# raises, the connector fails, the usual reconnect logic tries again).
# Same discipline as the suite handshake above: every (re)connect
# re-proves, the socket timeout bounds the wait, and a failed proof is an
# ordinary exchange error.
WAVESHARE_REPLY_MAX = 16      # the verdict arrives inside a few bytes


def waveshare_handshake_client(sock, password):
    """The client side of the Waveshare TCP connection-password handshake:
    send the password raw, then wait for the gateway's OK — the recv is
    bounded by the socket timeout. Returns on OK; raises ModbusError on
    anything else (a wrong password, a peer that is not a Waveshare
    gateway, silence, an early EOF)."""
    try:
        sock.sendall(password.encode('ascii'))
    except UnicodeEncodeError:
        raise ModbusError('the Waveshare password must be ASCII')
    resp = b''
    while b'OK' not in resp and len(resp) < WAVESHARE_REPLY_MAX:
        chunk = sock.recv(2)
        if not chunk:
            break
        resp += chunk
    if b'OK' not in resp:
        raise ModbusError('Waveshare TCP auth failed: %r' % resp)


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


# --- the MBAP framing helpers ------------------------------------------------
# The shape both servers read and every leg writes, so the framing exists
# once: a reply is a header around the PDU bytes, a request is read with
# the length bounds checked before the body (a bad length poisons the
# whole frame — there is no reading past it, the caller closes).

def frame(txn, unit, body, proto=0):
    """One outgoing MBAP frame: the header around the PDU/data bytes."""
    return struct.pack('>HHHB', txn, proto, len(body) + 1, unit) + body


def check_head(head, max_pdu):
    """The inbound MBAP head: unpacked, with the length bounds checked —
    'bad response length %d' when out of bounds (both clients' text).
    Returns (txn, proto, length, unit)."""
    txn, proto, length, unit = struct.unpack('>HHHB', head)
    if not 2 <= length <= max_pdu + 2:
        raise ModbusError('bad response length %d' % length)
    return txn, proto, length, unit


def read_frame(sock, max_pdu):
    """One inbound MBAP frame: the 7-byte head (bounds checked), then the
    rest of the frame. Returns (txn, proto, length, unit, pdu); raises
    ModbusError on a bad length (the caller logs and closes — the frame
    is not parseable enough to answer) and ConnectionError/OSError on a
    dead transport."""
    txn, proto, length, unit = check_head(recv_exact(sock, 7), max_pdu)
    return txn, proto, length, unit, recv_exact(sock, length - 1)


def pack_bits(bits):
    """The wire shape of a bit read reply: 8 bits per byte, LSB first —
    bit i of the span lives in byte i >> 3, bit position i & 7. Accepts
    any iterable of truthy/falsy values (generators included)."""
    bits = list(bits)
    packed = bytearray((len(bits) + 7) // 8)
    for i, bit in enumerate(bits):
        if bit:
            packed[i >> 3] |= 1 << (i & 7)
    return bytes(packed)


def unpack_bits(data, count):
    """The inverse of pack_bits: a bit reply's data bytes -> one 0/1 per
    address, the count clamped to what the bytes carry."""
    return tuple((data[i >> 3] >> (i & 7)) & 1 for i in range(count))
