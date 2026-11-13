#!/usr/bin/env python3
"""The sidecar's own trace face beside the family's shared one: the
FrameTap (the MBAP reassembler one capture direction runs) and the
TraceIndex (the replay side's read-back). The format itself — the
file shapes, the record feed, the encoders and decoders, the writer —
is the family's one home now (common/modbus/trace.py, the protocol
tree's "trace" section the identity); this module re-exports it so
the app's imports stay put."""
import json
import struct
import zlib

from common.modbus.trace import (KIND_RAW_C2D, KIND_RAW_D2C, KIND_REQ, KIND_RSP,   # re-exported
                                 HDR_HEAD, MAX_PDU_LEN, MULTI_WRITE_FCS, READ_FCS,
                                 SINGLE_WRITE_FCS, TRACE_BINARY_VERSION, TRACE_FORMAT,
                                 TRACE_MAGIC, TRACE_VERSION, decode_frame, decode_record,
                                 describe_frame, encode_header, encode_record,
                                 parse_binary_header, FeedSocket, TraceWriter)
from .statics import MAX_PDU


class FrameTap:
    """The MBAP reassembler one capture direction runs: feed it the raw
    chunks as they pipe through, it yields (frame_bytes, parsed, note)
    per complete frame — parsed is the (txn, unit, pdu) head triple,
    None for a record the framing cannot parse (the note names it). The
    tap never blocks the pipe — it reads what arrived. A poisoned head
    (a bad length, a non-zero protocol id) flushes the whole buffer as
    one undecodable frame and resyncs empty: the bytes reach the trace
    raw, the next head tries fresh.

    The auth handshakes ride ahead of any MBAP frame and unframed (the
    PVA1 proof is a raw 52-byte frame, the Waveshare password raw
    ASCII, the verdicts raw OK/ERR): before the first clean frame the
    tap peels and names them — a PVA1 magic burst, a printable-ASCII
    password, a leading OK/ERR verdict — so the handshake renders whole
    in the conversations and the device's first real frame survives
    (the verdict glue would otherwise flush the frame into the raw
    record, losing it from the answer index). flush() yields the
    residual buffer when the pipe ends — a short verdict plus EOF is
    traced too, not dropped."""

    def __init__(self, flow='c2d'):
        self.flow = flow        # the leg's direction: the peel rules speak it
        self.buf = b''
        self.broken = False     # a head failed since the last clean frame
        self.saw_clean = False  # the handshake window closes on the first clean frame

    @staticmethod
    def _printable(buf):
        return all(0x20 <= c <= 0x7e for c in buf)

    def _head_ok(self, buf):
        """A plausible MBAP head at the buffer's start (the peel's
        guard: a real frame never peels)."""
        if len(buf) < 7:
            return False
        _txn, proto, length, _unit = struct.unpack('>HHHB', buf[:7])
        return proto == 0 and 2 <= length <= MAX_PDU + 2

    def _raw_note(self):
        """The name the raw record rides under: the shapes the tap
        knows (the handshake bursts before the first clean frame),
        'framing lost' otherwise — the lengths render, the notes
        name."""
        if self.buf.startswith(b'PVA1'):
            return 'PVA1 handshake proof'
        if not self.saw_clean and self.flow == 'c2d' and self._printable(self.buf):
            return 'Waveshare password'
        return 'framing lost — raw bytes only'

    def _peel(self, out):
        """The handshake peels, before the first clean frame: the PVA1
        proof (wait for its whole 52 bytes), a leading OK/ERR verdict,
        a printable password prefix. A buffer that starts with a
        plausible MBAP head never peels — the handshake is over or
        there was none."""
        if self.buf.startswith(b'PVA1'):
            if len(self.buf) < 52:
                return False    # wait for the whole proof
            out.append((self.buf[:52], None, 'PVA1 handshake proof'))
            self.buf = self.buf[52:]
            return True
        if self._head_ok(self.buf):
            return False
        if self.buf.startswith(b'OK'):
            out.append((self.buf[:2], None, 'auth verdict'))
            self.buf = self.buf[2:]
            return True
        if self.buf.startswith(b'ERR') and len(self.buf) >= 3:
            out.append((self.buf[:3], None, 'auth verdict'))
            self.buf = self.buf[3:]
            return True
        if self.buf and 0x20 <= self.buf[0] <= 0x7e:
            cut = len(self.buf)
            for i, c in enumerate(self.buf):
                if not 0x20 <= c <= 0x7e:
                    cut = i
                    break
            if cut == len(self.buf):
                return False    # all printable so far: the password may continue — wait
            out.append((self.buf[:cut], None,
                        'Waveshare password (%d byte(s))' % cut))
            self.buf = self.buf[cut:]
            return True
        return False

    def feed(self, chunk):
        out = []
        self.buf += chunk
        if not self.saw_clean:
            while self.buf and not self.saw_clean:
                before = len(self.buf)
                if not self._peel(out):
                    break
                if len(self.buf) >= before:
                    break   # a peel that ate nothing: stop, the head loop tries
        while len(self.buf) >= 7:
            txn, proto, length, unit = struct.unpack('>HHHB', self.buf[:7])
            if not 2 <= length <= MAX_PDU + 2 or proto != 0:
                self.broken = True
                out.append((self.buf, None, self._raw_note()))
                self.buf = b''
                return out
            total = 6 + length
            if len(self.buf) < total:
                break
            frame = bytes(self.buf[:total])
            self.buf = self.buf[total:]
            self.broken = False
            self.saw_clean = True
            out.append((frame, (txn, unit, frame[7:]), None))
        return out

    def flush(self):
        """The pipe's end: the residual buffer rides the trace raw (a
        short verdict plus EOF, a torn handshake) — nothing the pump
        piped dies unrecorded."""
        if not self.buf:
            return []
        out = [(self.buf, None, self._raw_note())]
        self.buf = b''
        return out


class TraceIndex:
    """The replay side: the trace read back and keyed for answering —
    every recorded response under (unit, request pdu bytes), the most
    recent one winning, each entry carrying the recorded device latency
    (rsp.ts - req.ts, clamped non-negative; the wall clock is the
    trace's own domain — the file is the artifact, not a monotonic
    reader) and the ask count (how many times the capture saw the
    query). The trace may wear either shape — the binary PVMB blocks
    or the JSON v1 lines; the first bytes pick the walk. The
    conversations come from the same pass: a response pairs with its
    request by the MBAP transaction id within their connection (per
    run — the conn ids restart each run), the most recent open request
    standing in when a device echoes a foreign id — so concurrent
    clients and pipelined requests pair correctly. A trace that opens
    wrong (missing, foreign format, a future version) refuses with a
    clean one-liner; a torn tail or a mid-file corruption keeps what
    parsed — the loss noted in the summary; the summary feeds the
    start log."""

    def __init__(self, path):
        self.path = path
        self.requests = 0
        self.responses = 0
        self.orphans = 0      # response records no recorded request matches
        self.torn = 0         # the damaged records: torn tails, resyncs, skipped lines
        self.sessions = 0
        self.conns = 0
        self.units = set()
        self.fcs = set()
        self.span = 0.0
        self.index = {}       # (unit, req pdu) -> (rsp pdu, latency) — the most recent wins
        self.counts = {}      # (unit, req pdu) -> the ask count
        self.records = []     # every record, in order — the dump's views read these
        self.pairs = {}       # a request record's no -> its response record's no
        self.session_headers = {}   # the session no -> the run header's (upstream, started)
        self._pending = {}    # (session, conn, txn) -> (ts, pdu, no) — the open requests
        self._first_ts = None
        self._last_ts = None
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError as e:
            raise SystemExit('cannot read trace %s: %s' % (path, e))
        if not data:
            raise SystemExit('trace %s is empty — capture something first' % path)
        if data[:1] == b'{':
            self._walk_json(data)
        elif data[:4] == TRACE_MAGIC:
            self._walk_binary(data)
        else:
            raise SystemExit('trace %s: not a pv-suite trace (the first bytes are '
                             'neither the PVMB magic nor a JSON header)' % path)
        self.conns = len({(r['session'], r['conn']) for r in self.records})
        self.span = max(0.0, (self._last_ts or 0.0) - (self._first_ts or 0.0))
        if not self.index:
            raise SystemExit('trace %s: no request/response pair recorded — '
                             'nothing to replay' % path)

    def _session(self, header=None):
        """A run's boundary: the session counter + the run header's
        stamps (the converter re-stamps them per session)."""
        self.sessions += 1
        self.session_headers[self.sessions] = header or {}
        return self.sessions

    def _span_ts(self, ts):
        if ts and ts > 0:
            self._first_ts = ts if self._first_ts is None else min(self._first_ts, ts)
            self._last_ts = ts if self._last_ts is None else max(self._last_ts, ts)

    def _record(self, session, kind, ts, conn, peer, note, raw):
        entry = {'no': len(self.records) + 1, 'session': session, 'kind': kind,
                 'ts': ts, 'conn': conn, 'peer': peer or '', 'note': note,
                 'raw': raw}
        self.records.append(entry)
        self._span_ts(ts)
        if kind in (KIND_RAW_C2D, KIND_RAW_D2C) or len(raw) < 8:
            return entry   # the raw/framing-lost records ride the conversations, not the index
        unit, pdu = raw[6], raw[7:]
        self.units.add(unit)
        if pdu:
            self.fcs.add(pdu[0] & 0x7F)
        if kind == KIND_REQ:
            self.requests += 1
            key = (unit, pdu)
            self.counts[key] = self.counts.get(key, 0) + 1
            self._pending[(session, conn, raw[:2])] = (ts, pdu, entry['no'])
        elif kind == KIND_RSP:
            self.responses += 1
            req = self._pending.pop((session, conn, raw[:2]), None)
            if req is None:
                # a device that echoes a foreign txn id: the most recent
                # still-open request on the connection pairs
                cand = [k for k in self._pending if k[:2] == (session, conn)]
                if cand:
                    k = max(cand, key=lambda k_: self._pending[k_][2])
                    req = self._pending.pop(k)
            if req is None:
                self.orphans += 1
                return entry
            latency = max(0.0, (ts or 0.0) - (req[0] or 0.0)) if ts and req[0] else 0.0
            key = (unit, req[1])
            self.index[key] = (pdu, latency)
            self.pairs[req[2]] = entry['no']
        return entry

    def _walk_binary(self, data):
        hdr = parse_binary_header(data, 0)
        if hdr is None:
            raise SystemExit('trace %s: not a PVMB trace (the magic is there, '
                             'the header does not parse)' % self.path)
        session = self._session({'upstream': hdr[0]['upstream'],
                                 'started': hdr[0]['started']})
        off = hdr[1]
        n = len(data)
        while off < n:
            if data[off:off + 4] == TRACE_MAGIC:
                hdr = parse_binary_header(data, off)
                if hdr is None:
                    self.torn += 1
                    break
                session = self._session({'upstream': hdr[0]['upstream'],
                                         'started': hdr[0]['started']})
                off += hdr[1]
                continue
            if off + 4 > n:
                self.torn += 1
                break
            (body_len,) = struct.unpack_from('>I', data, off)
            if off + 4 + body_len + 4 > n:
                self.torn += 1
                break   # the torn tail: keep what parsed, note the loss
            body = data[off + 4:off + 4 + body_len]
            (crc,) = struct.unpack_from('>I', data, off + 4 + body_len)
            if zlib.crc32(body) != crc:
                nxt = self._resync(data, off)
                self.torn += 1
                if nxt is None:
                    break
                off = nxt
                continue
            rec = decode_record(body)
            self._record(session, rec['kind'], rec['ts'], rec['conn'],
                         rec['peer'], rec['note'], rec['raw'])
            off += 4 + body_len + 4

    def _resync(self, data, off):
        """The scan past a corrupt block: the next parseable run header
        re-anchors the walk (the records between the tear and the
        re-anchor are lost with the tear — a bounded gap)."""
        nxt = data.find(TRACE_MAGIC, off + 4)
        while nxt != -1:
            if parse_binary_header(data, nxt) is not None:
                return nxt
            nxt = data.find(TRACE_MAGIC, nxt + 1)
        return None

    def _walk_json(self, data):
        lines = data.decode('utf-8', 'replace').splitlines()
        try:
            header = json.loads(lines[0])
        except ValueError as e:
            raise SystemExit('trace %s: the first line is not JSON (%s)'
                             % (self.path, e))
        if not isinstance(header, dict) or header.get('format') != TRACE_FORMAT:
            raise SystemExit('trace %s: not a %s file (the first line carries no '
                             '"format": "%s" header)' % (self.path, TRACE_FORMAT,
                                                          TRACE_FORMAT))
        if header.get('version') != TRACE_VERSION:
            raise SystemExit('trace %s: format version %r, this tool speaks %r — '
                             're-capture' % (self.path, header.get('version'),
                                              TRACE_VERSION))
        session = self._session({'upstream': header.get('upstream'),
                                 'started': header.get('started')})
        for line in lines[1:]:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                self.torn += 1   # a torn write: skipped, the loss noted in the summary
                continue
            if not isinstance(rec, dict):
                self.torn += 1
                continue
            if rec.get('format') == TRACE_FORMAT:
                session = self._session({'upstream': rec.get('upstream'),
                                         'started': rec.get('started')})
                continue   # a later run's header: the session boundary
            self._json_record(session, rec)

    def _json_record(self, session, rec):
        direction = rec.get('dir')
        if direction not in ('req', 'rsp', 'raw') or not isinstance(rec.get('raw'), str):
            return
        try:
            raw = bytes.fromhex(rec['raw'])
        except ValueError:
            self.torn += 1   # the raw field corrupted: the record is damaged, skip it
            return
        if direction == 'raw':
            kind = KIND_RAW_C2D if rec.get('flow') == 'c2d' else KIND_RAW_D2C
        else:
            kind = KIND_REQ if direction == 'req' else KIND_RSP
        ts = rec.get('ts')
        ts = float(ts) if isinstance(ts, (int, float)) else 0.0
        conn = rec.get('conn')
        conn = int(conn) if isinstance(conn, int) else 0
        self._record(session, kind, ts, conn, rec.get('peer') or '',
                     rec.get('note'), raw)

    def answer(self, unit, pdu):
        """The recorded answer for one request (unit, pdu bytes):
        (response pdu, recorded latency) or None — the miss the
        replay-miss policy speaks."""
        return self.index.get((unit, pdu))

    def summary(self):
        """The start-log line's words: what the trace holds."""
        units = ','.join(str(u) for u in sorted(self.units)) or '-'
        fcs = ','.join('FC%d' % fc for fc in sorted(self.fcs)) or '-'
        out = ('%d request(s), %d response(s) indexed (%d orphan(s)), '
               '%d unit(s) [%s], %s, span %gs in %d session(s)'
               % (self.requests, len(self.index), self.orphans,
                  len(self.units), units, fcs, self.span, self.sessions))
        if self.torn:
            out += ', %d damaged record(s) skipped' % self.torn
        return out
