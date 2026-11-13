#!/usr/bin/env python3
"""The Modbus wire trace (stdlib only) — the file format both sides of
the sidecar share, and the one home for the MBAP decode the capture tap
uses. A trace is JSON lines, one record per frame, 0600 at rest:

    {"format": "pv-suite-modbus-trace", "version": 1, ...}   (a run's header)
    {"ts": <epoch float>, "dir": "req"|"rsp"|"raw", "conn": N,
     "peer": "ip:port", "raw": "<hex frame>", "unit": N, "fc": N,
     "addr": N, "count": N, "exc": N, "note": "..."}

`dir` speaks the client's view (req = client to device, rsp = the
device's answer); a record the MBAP framing cannot parse rides `raw`
with the flow it arrived on. The writer appends across runs (each run
stamps its header line — a multi-run trace is a longer history) and
flushes per frame, so a killed capture leaves a readable trace.

The replay side (TraceIndex) reads the file back and keys every recorded
response under its request's identity — unit + function code + PDU
bytes, transaction ids aside (the head's txn is the client's own
counter; a replayed session speaks its own) — the most recent response
winning, with the recorded device latency (rsp.ts - req.ts) alongside
for --replay-speed."""
import json
import os
import struct
import threading
import time

from .statics import MAX_PDU, TRACE_FORMAT, TRACE_VERSION

READ_FCS = (1, 2, 3, 4)      # addr + count requests, data replies
SINGLE_WRITE_FCS = (5, 6)    # addr + value requests, the echo replies
MULTI_WRITE_FCS = (15, 16)   # addr + count + data requests, addr + count echoes


def decode_frame(head_pdu, unit, is_request=True):
    """The decoded fields of one frame ((unit, pdu) from the tap): the
    unit id, the function code and the direction's own fields — a
    request carries addr/count (or addr/value), a response carries the
    byte count (reads) or the echoed addr/count / addr/value (writes),
    an exception carries the code. Returns the dict that rides the
    record (bare, merged by the caller)."""
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


class FrameTap:
    """The MBAP reassembler one capture direction runs: feed it the raw
    chunks as they pipe through, it yields (frame_bytes, (txn, unit,
    pdu)) per complete frame. The tap never blocks the pipe — it reads
    what arrived. A poisoned head (a bad length, a non-zero protocol id)
    flushes the whole buffer as one undecodable frame and resyncs empty:
    the bytes reach the trace raw, the next head tries fresh."""

    def __init__(self):
        self.buf = b''
        self.broken = False   # a head failed since the last clean frame

    def feed(self, chunk):
        out = []
        self.buf += chunk
        while len(self.buf) >= 7:
            txn, proto, length, unit = struct.unpack('>HHHB', self.buf[:7])
            if not 2 <= length <= MAX_PDU + 2 or proto != 0:
                self.broken = True
                out.append((self.buf, None))
                self.buf = b''
                return out
            total = 6 + length
            if len(self.buf) < total:
                break
            frame = bytes(self.buf[:total])
            self.buf = self.buf[total:]
            self.broken = False
            out.append((frame, (txn, unit, frame[7:])))
        return out


class TraceWriter:
    """The capture side's append-only trace writer: one JSON record per
    frame, a lock serializing the pump threads, a flush per record (a
    killed capture leaves a readable trace), the file 0600 (the wire
    carries values — and a Waveshare capture carries the connection
    password raw; the trace is not world-readable material). Every run
    stamps one header line first — the format word + version a replay
    validates, the posture it captured (the upstream, the suite
    version)."""

    def __init__(self, path, upstream):
        self.path = path
        self.n = 0
        existed = os.path.exists(path)
        self._f = open(path, 'a', encoding='utf-8')
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self._lock = threading.Lock()
        header = {'format': TRACE_FORMAT, 'version': TRACE_VERSION,
                  'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'tool': 'modbus-replay', 'mode': 'capture', 'upstream': upstream}
        self._write(header)

    def _write(self, obj):
        with self._lock:
            self._f.write(json.dumps(obj, separators=(',', ':')) + '\n')
            self._f.flush()
            self.n += 1

    def record(self, direction, conn, peer, raw, dec=None, note=None):
        """One wire record: direction 'c2d' | 'd2c' (the client's view:
        c2d is a request, d2c a response), the connection id pairing the
        proxy legs, the peer the bytes came from, the raw frame bytes —
        plus the decoded fields when the tap parsed them. A direction
        the framing never parsed rides dir 'raw' with the flow in
        'flow'."""
        obj = {'ts': round(time.time(), 6),
               'dir': {'c2d': 'req', 'd2c': 'rsp'}.get(direction, 'raw'),
               'conn': conn, 'peer': peer, 'raw': raw.hex()}
        if direction not in ('c2d', 'd2c'):
            obj['flow'] = direction
        if dec:
            obj.update(dec)
        if note:
            obj['note'] = note
        self._write(obj)

    def close(self):
        try:
            self._f.close()
        except OSError:
            pass


class TraceIndex:
    """The replay side: the trace read back and keyed for answering —
    every recorded response under (unit, request pdu bytes), the most
    recent one winning, each entry carrying the recorded device latency
    (rsp.ts - req.ts, clamped non-negative; the wall clock is the
    trace's own domain — the file is the artifact, not a monotonic
    reader). A trace that opens wrong (missing, foreign format, a
    future version) refuses with a clean one-liner; the summary feeds
    the start log."""

    def __init__(self, path):
        self.path = path
        self.requests = 0
        self.responses = 0
        self.orphans = 0      # response records no recorded request matches
        self.conns = 0
        self.units = set()
        self.fcs = set()
        self.span = 0.0
        self.index = {}
        try:
            with open(path, encoding='utf-8') as f:
                lines = f.read().splitlines()
        except OSError as e:
            raise SystemExit('cannot read trace %s: %s' % (path, e))
        if not lines:
            raise SystemExit('trace %s is empty — capture something first' % path)
        try:
            header = json.loads(lines[0])
        except ValueError as e:
            raise SystemExit('trace %s: the first line is not JSON (%s)' % (path, e))
        if not isinstance(header, dict) or header.get('format') != TRACE_FORMAT:
            raise SystemExit('trace %s: not a %s file (the first line carries no '
                             '"format": "%s" header)' % (path, TRACE_FORMAT, TRACE_FORMAT))
        if header.get('version') != TRACE_VERSION:
            raise SystemExit('trace %s: format version %r, this tool speaks %r — '
                             're-capture' % (path, header.get('version'), TRACE_VERSION))
        pending = {}   # conn -> last request record (the response pairs with it)
        conns = set()
        first_ts = last_ts = None
        for no, line in enumerate(lines[1:], 2):
            try:
                rec = json.loads(line)
            except ValueError:
                raise SystemExit('trace %s:%d: not JSON' % (path, no))
            if not isinstance(rec, dict) or rec.get('format') == TRACE_FORMAT:
                continue   # a later run's header line: the session boundary, not a frame
            ts = rec.get('ts')
            if isinstance(ts, (int, float)):
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)
            direction = rec.get('dir')
            if direction == 'raw' or 'raw' not in rec:
                continue
            try:
                raw = bytes.fromhex(rec['raw'])
            except ValueError:
                raise SystemExit('trace %s:%d: the raw field is not hex' % (path, no))
            if len(raw) < 8:
                continue
            unit, pdu = raw[6], raw[7:]
            is_request = direction == 'req'
            if is_request:
                self.requests += 1
                conns.add(rec.get('conn'))
                pending[rec.get('conn')] = (ts, pdu)
            elif direction == 'rsp':
                self.responses += 1
                req = pending.pop(rec.get('conn'), None)
                if req is None or req[1] is None:
                    self.orphans += 1
                    continue
                latency = max(0.0, (ts or 0.0) - (req[0] or 0.0)) \
                    if isinstance(ts, (int, float)) and isinstance(req[0], (int, float)) else 0.0
                self.index[(unit, req[1])] = (pdu, latency)
            else:
                continue
            if isinstance(rec.get('unit'), int):
                self.units.add(rec['unit'])
            if isinstance(rec.get('fc'), int):
                self.fcs.add(rec['fc'])
        self.conns = len(conns)
        self.span = max(0.0, (last_ts or 0.0) - (first_ts or 0.0))
        if not self.index:
            raise SystemExit('trace %s: no request/response pair recorded — '
                             'nothing to replay' % path)

    def answer(self, unit, pdu):
        """The recorded answer for one request (unit, pdu bytes):
        (response pdu, recorded latency) or None — the miss the
        replay-miss policy speaks."""
        return self.index.get((unit, pdu))

    def summary(self):
        """The start-log line's words: what the trace holds."""
        units = ','.join(str(u) for u in sorted(self.units)) or '-'
        fcs = ','.join('FC%d' % fc for fc in sorted(self.fcs)) or '-'
        return ('%d request(s), %d response(s) indexed (%d orphan(s)), '
                '%d unit(s) [%s], %s, span %gs'
                % (self.requests, len(self.index), self.orphans,
                   len(self.units), units, fcs, self.span))
