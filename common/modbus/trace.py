"""The Modbus wire trace (stdlib only) — the family's one home for the
trace format both sides share, the record feed's one encoding, and the
MBAP decode the capture tap uses. Two shapes, feature the same:

    binary (the default, --dump-type binary): a PVMB file — the magic
    + version + started + posture header block per run, then one
    length-framed crc-checked block per record:

        {"ts": <epoch f64>, "kind": 0=req|1=rsp|2=raw-c2d|3=raw-d2c,
         "conn": N, "peer": "ip:port", "note": "...", "raw": <bytes>}

    json (the v1 spelling, --dump-type json): JSON lines, one record
    per frame, the decoded fields riding beside the raw hex:

        {"format": "pv-suite-modbus-trace", "version": 1, ...}  (a run's header)
        {"ts": <epoch float>, "dir": "req"|"rsp"|"raw", "conn": N,
         "peer": "ip:port", "raw": "<hex frame>", "unit": N, "fc": N,
         "addr": N, "count": N, "exc": N, "note": "..."}

The binary carries the frame once (the decoded fields re-derive on
read — the JSON's echo is its readability sugar, frozen at v1); both
shapes answer the same tool surface. The writer appends across runs
(each run stamps its header — a multi-run trace is a longer history)
and flushes per record, so a killed capture leaves a readable trace;
the framing is length-based, so a torn tail costs one record — the
reader resyncs at the next run header instead of refusing the file.
An unbounded capture is a disk hazard: at --trace-max-mb the writer
rotates (the backups shift .1 .. .N, the oldest dropped), the fresh
file stamps its own header — every backup a complete trace, readers
unchanged.

The auth handshakes do not ride MBAP (the PVA1 proof is a raw 52-byte
frame, the Waveshare password raw ASCII, the verdicts raw 2-3 bytes):
the tap peels and names them (the handshake renders whole in the
conversations and the device's first frame survives), and the bytes
ride the trace verbatim as raw records — the reason the trace is 0600
at rest (the wire carries values, a Waveshare capture carries the
connection password, a PVA1 proof can replay).

The record feed (FeedSocket) is the family's shared one too: the
replay's capture and replay faces fan their records out to the dump
tools, and so does the cache's trace feed (trace/socket) — the same
PVMB encoding, the same subscriber contract (modbus-replay-dump
--socket renders any of them). The socket binds 0600: connect needs
write on the inode, and the records carry register values — the mode
is policy, not the umask's mood. The format's identity lives in the
family's one protocol tree (shared/suite/protocol.json "trace") — no
per-tool drift.
"""
import json
import os
import socket
import struct
import threading
import time
import zlib

from .protocol import PROTOCOL

READ_FCS = (1, 2, 3, 4)      # addr + count requests, data replies
SINGLE_WRITE_FCS = (5, 6)    # addr + value requests, the echo replies
MULTI_WRITE_FCS = (15, 16)   # addr + count + data requests, addr + count echoes

KIND_REQ = 0                 # a parsed request (c2d)
KIND_RSP = 1                 # a parsed response (d2c)
KIND_RAW_C2D = 2             # the framing lost, client to device
KIND_RAW_D2C = 3             # the framing lost, device to client

TRACE_FORMAT = PROTOCOL['trace']['format']        # the JSON trace's format word (the v1 spelling)
TRACE_VERSION = PROTOCOL['trace']['version']      # (the replay side refuses a foreign one)
TRACE_MAGIC = PROTOCOL['trace']['binary_magic'].encode('ascii')
"""The binary trace's magic (b'PVMB') — the file's first bytes, the
format detection's peek and the resync scan's anchor."""
TRACE_BINARY_VERSION = PROTOCOL['trace']['binary_version']

REC_HEAD = struct.Struct('>dBI')     # ts, kind, conn
HDR_HEAD = struct.Struct('>4sBBQH')  # magic, version, reserved, started, upstream_len
MAX_PDU_LEN = 0xFFFF                 # the raw slot is u16 — MAX_PDU+7 fits with room

# The rotation bounds (the trace family's audit-max-mb/audit-files twins —
# the registries' trace-max-mb/trace-files rows repeat them as min/max, the
# flag layer gates there): the rotated backups kept and the size that
# triggers a rotation in MB (0 = no size rotation — the capture appends
# unbounded, the default).
TRACE_FILES_MIN = 1
TRACE_FILES_MAX = 100
TRACE_MAX_MB_MIN = 0
TRACE_MAX_MB_MAX = 1048576


def shift_backups(path, keep):
    """The rotated backup shift (.1 <- .2 <- ... <- .N, the oldest
    dropped) then the live file to .1 — the audit log's rotation shape,
    the one spelling the trace family's writers share. A rotated file is
    a complete trace of its own: every run stamps its header, so every
    reader takes each backup for captured."""
    for i in range(keep - 1, 0, -1):
        src, dst = '%s.%d' % (path, i), '%s.%d' % (path, i + 1)
        if os.path.exists(src):
            os.replace(src, dst)
    if os.path.exists(path):
        os.replace(path, path + '.1')


def encode_header(upstream, started):
    """The run header block: the magic + version + started (u64 epoch
    seconds) + the posture string, the crc32 over it as the trailer —
    the anchor the record walk and the resync scan both start from."""
    up = upstream.encode('utf-8')[:0xFFFF]
    head = HDR_HEAD.pack(TRACE_MAGIC, TRACE_BINARY_VERSION, 0, int(started), len(up)) + up
    return head + struct.pack('>I', zlib.crc32(head))


def parse_binary_header(data, off=0):
    """The run header at off: (dict(started, upstream), total length) or
    None — incomplete, a foreign version, or a false magic (the crc
    validates the real ones; the resync scan leans on that)."""
    if len(data) - off < HDR_HEAD.size:
        return None
    magic, version, _reserved, started, up_len = HDR_HEAD.unpack_from(data, off)
    if magic != TRACE_MAGIC or version != TRACE_BINARY_VERSION:
        return None
    total = HDR_HEAD.size + up_len + 4
    if len(data) - off < total:
        return None
    head = data[off:off + HDR_HEAD.size + up_len]
    (crc,) = struct.unpack_from('>I', data, off + HDR_HEAD.size + up_len)
    if zlib.crc32(head) != crc:
        return None
    upstream = head[HDR_HEAD.size:].decode('utf-8', 'replace')
    return {'started': started, 'upstream': upstream}, total


def encode_record(ts, kind, conn, peer, note, raw):
    """The binary record block: the u32 body-length prefix (the skip
    unit), the body (ts, kind, conn, peer, note, the raw frame bytes
    verbatim), the crc32 over the body as the trailer. Big-endian
    throughout — MBAP's own order."""
    peer_b = (peer or '')[:255].encode('utf-8', 'replace')
    note_b = (note or '')[:255].encode('utf-8', 'replace')
    if len(raw) > MAX_PDU_LEN:
        raw = raw[:MAX_PDU_LEN]
    body = (REC_HEAD.pack(ts, kind, conn)
            + bytes((len(peer_b),)) + peer_b
            + bytes((len(note_b),)) + note_b
            + struct.pack('>H', len(raw)) + raw)
    return struct.pack('>I', len(body)) + body + struct.pack('>I', zlib.crc32(body))


def decode_record(body):
    """The record body (ts..raw) back to the dict the dump and the
    index speak."""
    ts, kind, conn = REC_HEAD.unpack_from(body, 0)
    off = REC_HEAD.size
    peer_len = body[off]
    off += 1
    peer = body[off:off + peer_len].decode('utf-8', 'replace')
    off += peer_len
    note_len = body[off]
    off += 1
    note = body[off:off + note_len].decode('utf-8', 'replace')
    off += note_len
    (raw_len,) = struct.unpack_from('>H', body, off)
    off += 2
    raw = body[off:off + raw_len]
    return {'ts': ts, 'kind': kind, 'conn': conn, 'peer': peer,
            'note': note, 'raw': raw}


def decode_frame(head_pdu, unit, is_request=True):
    """The decoded fields of one frame ((unit, pdu) from the tap): the
    unit id, the function code and the direction's own fields — a
    request carries addr/count (or addr/value), a response carries the
    byte count (reads) or the echoed addr/count / addr/value (writes),
    an exception carries the code. Returns the dict that rides the
    JSON record (bare, merged by the caller)."""
    dec = {'unit': unit}
    pdu = head_pdu
    if not pdu:
        return dec
    fc = pdu[0]
    dec['fc'] = fc
    if fc & 0x80:
        dec['fc'] = fc & 0x7F
        if len(pdu) > 1:
            dec['exc'] = pdu[1]
        return dec
    if is_request:
        if fc in READ_FCS and len(pdu) >= 5:
            dec['addr'], dec['count'] = struct.unpack('>HH', pdu[1:5])
        elif fc in SINGLE_WRITE_FCS and len(pdu) >= 5:
            dec['addr'], dec['value'] = struct.unpack('>HH', pdu[1:5])
        elif fc in MULTI_WRITE_FCS and len(pdu) >= 6:
            dec['addr'], dec['count'] = struct.unpack('>HH', pdu[1:5])
            dec['bytes'] = pdu[5]
    else:
        if fc in READ_FCS and len(pdu) >= 2:
            dec['bytes'] = pdu[1]          # the data's byte count (the echo's shape)
        elif fc in SINGLE_WRITE_FCS and len(pdu) >= 5:
            dec['addr'], dec['value'] = struct.unpack('>HH', pdu[1:5])
        elif fc in MULTI_WRITE_FCS and len(pdu) >= 5:
            dec['addr'], dec['count'] = struct.unpack('>HH', pdu[1:5])
    return dec


def describe_frame(unit, pdu, is_request=True):
    """One frame for humans (the DEBUG log line, the summaries): a
    request speaks 'FC3 (read holding registers) unit 1 addr 32064
    count 2', a response speaks its own shape — the reads' byte count
    ('4 data byte(s) (2 register(s))') or the writes' echo ('addr 40001
    value 1234') — and an exception speaks 'FC3 exception 02' — the
    same words the family's logs speak."""
    from common.modbus.protocol import describe_fc
    if not pdu:
        return 'empty frame'
    fc = pdu[0]
    if fc & 0x80:
        code = pdu[1] if len(pdu) > 1 else -1
        return '%s exception %d' % (describe_fc(fc & 0x7F), code)
    words = [describe_fc(fc)]
    if not is_request and fc in READ_FCS and len(pdu) >= 2:
        n = pdu[1]
        kind = '%d register(s)' % (n // 2) if fc in (3, 4) else '%d bit(s)' % (n * 8)
        words.append('unit %d %d data byte(s) (%s)' % (unit, n, kind))
    elif fc in SINGLE_WRITE_FCS and len(pdu) >= 5:
        addr, value = struct.unpack('>HH', pdu[1:5])
        words.append('unit %d addr %d value %d' % (unit, addr, value))
    elif fc in MULTI_WRITE_FCS and len(pdu) >= (6 if is_request else 5):
        addr, count = struct.unpack('>HH', pdu[1:5])
        words.append('unit %d addr %d count %d' % (unit, addr, count))
    elif fc in READ_FCS and len(pdu) >= 5:
        addr, count = struct.unpack('>HH', pdu[1:5])
        words.append('unit %d addr %d count %d' % (unit, addr, count))
    else:
        words.append('unit %d %d data byte(s)' % (unit, max(0, len(pdu) - 1)))
    return ' '.join(words)


class FeedSocket:
    """The record feed: a unix stream socket the daemon binds at start
    (the derived default path, the word 'none' refuses) and the dump
    tools subscribe to; every record the writer encodes fans out here
    in the binary encoding verbatim — read-only push, no verbs, no
    tokens (the no-control-plane ruling stands: it is a second view of
    the trace, not a listener that answers). Best effort by design: a
    slow subscriber's send times out and the subscriber is dropped —
    the FILE keeps every record, the wire pump never waits on a
    viewer. The header block re-stamps per subscriber connect, so the
    dump tool's format detection is the same peek it does on files.
    The socket file binds 0600: connecting needs write permission on
    the inode, and the records carry register values — the mode is the
    family's secrets posture, not the umask's mood."""
    MODE = 0o600

    def __init__(self, path, posture):
        self.path = path
        self.posture = posture
        self.subs = set()
        self.lock = threading.Lock()
        self.header = encode_header(posture, time.time())
        try:
            os.unlink(path)
        except OSError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.bind(path)
            os.chmod(path, self.MODE)
            self.sock.listen(16)
        except OSError:
            self.sock.close()
            raise
        threading.Thread(target=self._accept_loop, daemon=True,
                         name='dump-feed').start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return   # the socket closed: the daemon is stopping
            conn.settimeout(1.0)   # a slow viewer drops; the pump never waits
            with self.lock:
                self.subs.add(conn)
            try:
                conn.sendall(self.header)
            except OSError:
                self._drop(conn)

    def broadcast(self, data):
        with self.lock:
            subs = list(self.subs)
        for s in subs:
            try:
                s.sendall(data)
            except OSError:
                self._drop(s)

    def _drop(self, s):
        with self.lock:
            self.subs.discard(s)
        try:
            s.close()
        except OSError:
            pass

    def close(self):
        with self.lock:
            subs = list(self.subs)
            self.subs.clear()
        for s in subs:
            try:
                s.close()
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            os.unlink(self.path)   # the rebind's set-none leaves no stale file
        except OSError:
            pass


class TraceWriter:
    """The capture side's trace writer: one record per frame, a lock
    serializing the pump threads, a flush per record (a killed capture
    leaves a readable trace), the file 0600 (the wire carries values —
    and a Waveshare capture carries the connection password raw; the
    trace is not world-readable material). The format: the binary PVMB
    blocks by default (--dump-type binary) or the JSON v1 lines
    (--dump-type json) — the decoded echo re-derives from the raw
    bytes either way, the frame is the one truth. Every record also
    fans out to the record feed (the dump tools' socket) in the binary
    encoding. Every run stamps one header first — the format identity
    + the posture a reader validates; the trace appends across runs
    (a multi-run file is a longer history). A path of None writes no
    file: a pass-through capture feeds the subscribers only.

    The size rotation (max_mb, files — 0 = off, the default): at
    max_mb the writer shifts the backups (.1 <- .2 <- ... <- .N, the
    oldest dropped — shift_backups), reopens fresh and stamps a new
    run header, so the live file keeps the plain name and every backup
    is a complete trace of its own (a reader takes each for captured).
    The record is the boundary: the size check runs before a record is
    written, a block never straddles two files."""
    MODE = 0o600

    def __init__(self, path, dump_type='binary', feed=None, max_mb=0.0, files=3):
        if not TRACE_MAX_MB_MIN <= max_mb <= TRACE_MAX_MB_MAX:
            raise ValueError('trace-max-mb must be %d..%d MB' % (TRACE_MAX_MB_MIN, TRACE_MAX_MB_MAX))
        if not TRACE_FILES_MIN <= files <= TRACE_FILES_MAX:
            raise ValueError('trace-files must be %d..%d' % (TRACE_FILES_MIN, TRACE_FILES_MAX))
        self.path = path
        self.dump_type = dump_type
        self.feed = feed
        self.max_bytes = int(max_mb * 1024 * 1024) if max_mb and max_mb > 0 else 0
        self.keep = int(files)
        self.n = 0
        self._lock = threading.Lock()
        self._f = None
        if path:
            self._open_file()

    def _open_file(self):
        """The trace file opened (appended), 0600 — __init__ and every
        rotation's one open."""
        self._f = open(self.path, 'ab' if self.dump_type == 'binary' else 'a',
                       **({} if self.dump_type == 'binary' else {'encoding': 'utf-8'}))
        try:
            os.chmod(self.path, self.MODE)
        except OSError:
            pass

    def _stamp_header(self, started):
        """The run's header block into the open file (binary or json) —
        open_run's write half, _rotate's re-stamp."""
        if self.dump_type == 'binary':
            self._f.write(encode_header(self.upstream, started))
        else:
            self._f.write(json.dumps(
                {'format': TRACE_FORMAT, 'version': TRACE_VERSION,
                 'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(started)),
                 'tool': 'modbus-replay', 'mode': 'capture',
                 'upstream': self.upstream},
                separators=(',', ':')) + '\n')
        self._f.flush()

    def open_run(self, upstream, started=None):
        """The run's header: the format identity + the posture —
        stamped per run, the session boundary a reader walks past."""
        started = int(started if started is not None else time.time())
        with self._lock:
            self.upstream = upstream
            if self._f is None:
                return
            self._stamp_header(started)

    def _rotate(self):
        """The size rotation: the backups shift (.1 <- .2 <- ... <- .N,
        the oldest dropped), the file reopens fresh and stamps a new run
        header — the caller holds the lock (emit's)."""
        self._f.close()
        shift_backups(self.path, self.keep)
        self._open_file()
        self._stamp_header(int(time.time()))

    def _maybe_rotate(self):
        """The size check before a record is written (the caller holds
        the lock): at max_bytes the file rotates, the record lands in
        the fresh file."""
        if self.max_bytes and os.path.getsize(self.path) >= self.max_bytes:
            self._rotate()

    def record(self, direction, conn, peer, raw, dec=None, note=None):
        """One wire record from the capture tap: direction 'c2d' | 'd2c'
        (the client's view: c2d is a request, d2c a response), the
        connection id pairing the proxy legs, the peer the bytes came
        from, the raw frame bytes — plus the decoded fields when the
        tap parsed them. A direction the framing never parsed rides
        raw with the tap's note naming it."""
        ts = round(time.time(), 6)
        if direction == 'c2d':
            kind = KIND_REQ if dec is not None else KIND_RAW_C2D
        else:
            kind = KIND_RSP if dec is not None else KIND_RAW_D2C
        self.emit(ts, kind, conn, peer, note, raw)

    def emit(self, ts, kind, conn, peer, note, raw):
        """One record: the file (the format's own shape — the binary
        block or the JSON v1 line, the decoded echo re-derived from
        the raw bytes) + the feed (the binary encoding verbatim). The
        converter's path too: the source's stamps ride unchanged."""
        with self._lock:
            if self._f is not None:
                self._maybe_rotate()
                if self.dump_type == 'binary':
                    self._f.write(encode_record(ts, kind, conn, peer, note, raw))
                else:
                    self._f.write(self._json_line(ts, kind, conn, peer, note, raw))
                self._f.flush()
            if self.feed is not None:
                self.feed.broadcast(encode_record(ts, kind, conn, peer, note, raw))
            self.n += 1

    def _json_line(self, ts, kind, conn, peer, note, raw):
        obj = {'ts': ts,
               'dir': {KIND_REQ: 'req', KIND_RSP: 'rsp'}.get(kind, 'raw'),
               'conn': conn, 'peer': peer, 'raw': raw.hex()}
        if kind in (KIND_RAW_C2D, KIND_RAW_D2C):
            obj['flow'] = 'c2d' if kind == KIND_RAW_C2D else 'd2c'
        elif len(raw) >= 8:
            dec = {'txn': struct.unpack('>H', raw[:2])[0]}
            dec.update(decode_frame(raw[7:], raw[6], is_request=(kind == KIND_REQ)))
            obj.update(dec)
        if note:
            obj['note'] = note
        return json.dumps(obj, separators=(',', ':')) + '\n'

    def close(self):
        if self.feed is not None:
            self.feed.close()
        if self._f is not None:
            try:
                self._f.close()
            except OSError:
                pass
