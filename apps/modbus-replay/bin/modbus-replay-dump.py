#!/usr/bin/env python3
"""Modbus Replay Dump: the trace's reader face — the ctl/cli sibling
shape, minus the control plane (there is nothing to control: the trace
is the record). One tool, three abilities:

  the views      modbus-replay-dump.py TRACE — the summary, the answer
                 index (query -> the recorded reply the replay will
                 serve, the latency, the ask count) and the
                 conversations (the per-connection query->answer
                 diagram, unpaired records marked in place);
  the converter  --to json|binary -o OUT — either shape reads, the
                 other writes; the raw bytes are the one truth (the
                 JSON side re-derives the decoded echo, never copies
                 it), so a binary->json->binary round trip lands
                 byte-identical;
  the live view  --socket [PATH] — the daemon's record feed
                 (--dump-socket) pushes every record as it lands; the
                 conversations render realtime (a request prints
                 pending, its response completes the exchange). The
                 default path derives the family's ctl way:
                 /tmp/modbus-replay-<listen-port>.socket.

Both trace shapes read the same (the binary PVMB blocks or the JSON v1
lines — the first bytes pick the walk). The reader refuses with clean
one-liners; ^C ends the live view with a zero exit."""
import argparse
import calendar
import os
import socket
import struct
import sys
import time
import zlib

here = os.path.dirname(os.path.realpath(__file__))   # .../bin
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(here))))   # the repo root — the common/ package

from lib.man import dump_page
from lib.statics import DEFAULT_LISTEN_PORT
from lib.trace import (HDR_HEAD, KIND_RAW_C2D, KIND_RAW_D2C, KIND_REQ,
                       KIND_RSP, READ_FCS, TRACE_MAGIC, TraceIndex,
                       TraceWriter, decode_record, describe_frame,
                       parse_binary_header)

DEFAULT_FEED = '/tmp/modbus-replay-%d.socket' % DEFAULT_LISTEN_PORT


def stamp(ts):
    """The record's wall stamp for the views: UTC HH:MM:SS.mmm (the
    trace's own domain — the file is the artifact)."""
    if not ts or ts <= 0:
        return '-'
    return '%s.%03d' % (time.strftime('%H:%M:%S', time.gmtime(ts)),
                        round((ts % 1) * 1000) % 1000)


def rsp_words(unit, pdu):
    """The response's words for the answer-index line: the describe,
    plus the read data's hex u16 words (capped) — the values the
    device answered, the wire's own truth."""
    words = describe_frame(unit, pdu, is_request=False)
    if pdu and not pdu[0] & 0x80 and pdu[0] in READ_FCS and len(pdu) >= 2:
        n = pdu[1]
        data = pdu[2:2 + n]
        count = len(data) // 2
        if count:
            shown = struct.unpack('>%dH' % count, data[:count * 2])
            text = ' '.join('%04x' % w for w in shown[:8])
            if count > 8:
                text += ' …(%d more)' % (count - 8)
            words += ': %s' % text
    return words


def frame_words(rec, is_request):
    """One framed record's words (the describe); a short raw rides its
    note."""
    if rec['kind'] in (KIND_REQ, KIND_RSP) and len(rec['raw']) >= 8:
        return describe_frame(rec['raw'][6], rec['raw'][7:], is_request=is_request)
    return rec['note'] or 'framing lost — raw bytes only'


def answer_index(idx):
    """The answer map: one line per unique (unit, request PDU) — the
    query, the recorded reply the replay will serve, the recorded
    latency, the ask count. The winners stay the winners."""
    print()
    n = len(idx.index)
    print('--- the answer index (%d unique quer%s) ---'
          % (n, 'y' if n == 1 else 'ies'))
    for key, (rsp_pdu, latency) in idx.index.items():
        unit, req_pdu = key
        print('%s -> %s  latency %gms  asked %dx'
              % (describe_frame(unit, req_pdu, is_request=True),
                 rsp_words(unit, rsp_pdu), latency * 1000.0,
                 idx.counts.get(key, 1)))


def conversations(idx):
    """The query->answer diagram: one block per (session, conn), one
    line per exchange, the unpaired records marked in place — who
    asked what, got what, how fast; the concurrency named."""
    print()
    print('--- the conversations ---')
    blocks = {}
    for r in idx.records:
        blocks.setdefault((r['session'], r['conn']), []).append(r)
    order = list(blocks.keys())
    spans = {}
    for key, recs in blocks.items():
        tss = [r['ts'] for r in recs if r['ts']]
        spans[key] = (min(tss), max(tss)) if tss else None
    rsp_targets = set(idx.pairs.values())
    for pos, ((session, conn), recs) in enumerate(blocks.items()):
        peer = next((r['peer'] for r in recs
                     if r['kind'] in (KIND_REQ, KIND_RAW_C2D)), None)
        head = 'conn %d  client %s' % (conn, peer or 'unknown')
        span = spans[(session, conn)]
        if span:
            for earlier in order[:pos]:
                o = spans[earlier]
                if earlier[0] == session and o and o[0] <= span[1] and span[0] <= o[1]:
                    head += '  (overlaps conn %d)' % earlier[1]
                    break
        if idx.sessions > 1:
            head += '  (session %d)' % session
        print(head)
        for r in recs:
            when = stamp(r['ts'])
            if r['kind'] == KIND_REQ:
                rsp_no = idx.pairs.get(r['no'])
                if rsp_no is None:
                    print('  #%d %s  req  %s  (no answer recorded)'
                          % (r['no'], when, frame_words(r, True)))
                    continue
                rsp = idx.records[rsp_no - 1]
                latency = max(0.0, (rsp['ts'] or 0.0) - (r['ts'] or 0.0))
                print('  #%d %s  req  %s  -> #%d  rsp  %s  %.1fms'
                      % (r['no'], when, frame_words(r, True), rsp_no,
                         frame_words(rsp, False), latency * 1000.0))
            elif r['kind'] == KIND_RSP:
                if r['no'] not in rsp_targets:
                    print('  #%d %s  rsp  %s  (orphan — no request recorded)'
                          % (r['no'], when, frame_words(r, False)))
            else:
                print('  #%d %s  raw  %s (%d byte(s))'
                      % (r['no'], when, r['note'] or 'framing lost',
                         len(r['raw'])))


def header_stamp(value):
    """The run header's started stamp to an epoch (the binary's u64
    rides through; the JSON's ISO string parses)."""
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return calendar.timegm(time.strptime(str(value), '%Y-%m-%dT%H:%M:%SZ'))
    except (TypeError, ValueError):
        return None


def convert(src, dst_type, out):
    """The converter: either shape reads, the other writes — the raw
    bytes are the one truth (the echo re-derives on the JSON side),
    the run boundaries re-stamp, a torn tail converts as far as it
    parsed, the crc recomputes."""
    idx = TraceIndex(src)
    writer = TraceWriter(out, dump_type=dst_type)
    try:
        current = 0
        for r in idx.records:
            if r['session'] != current:
                current = r['session']
                hdr = idx.session_headers.get(current, {})
                writer.open_run(hdr.get('upstream') or '-',
                                started=header_stamp(hdr.get('started')))
            writer.emit(r['ts'], r['kind'], r['conn'], r['peer'],
                        r['note'], r['raw'])
    finally:
        writer.close()
    print('%s: %d record(s) in %d session(s) written as %s'
          % (out, len(idx.records), idx.sessions, dst_type))


def recv_exact(sock, n):
    """The stream's exact read: the feed pushes records; a short read
    waits (the record is half-arrived, not absent). EOF — the daemon
    stopped, or this viewer was dropped — ends it."""
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('the feed closed')
        buf += chunk
    return buf


def live(sock_path):
    """The feed: connect, the header (the same peek a file gets), then
    the records as they land — the conversations render realtime."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(sock_path)
    except OSError as e:
        print('modbus-replay-dump: cannot reach the feed socket %s: %s'
              % (sock_path, e), file=sys.stderr)
        raise SystemExit(1)
    print('--- the live feed on %s (^C ends it) ---' % sock_path)
    try:
        sys.stdout.reconfigure(line_buffering=True)   # a live view renders live
    except (AttributeError, ValueError):
        pass
    try:
        head = recv_exact(sock, HDR_HEAD.size)
        magic, version, _r, started, up_len = HDR_HEAD.unpack(head)
        if magic != TRACE_MAGIC:
            print('modbus-replay-dump: %s is not a pv-suite record feed '
                  '(the magic is %r)' % (sock_path, magic), file=sys.stderr)
            raise SystemExit(1)
        hdr = parse_binary_header(head + recv_exact(sock, up_len + 4), 0)
        if hdr is None:
            print('modbus-replay-dump: %s: the feed header does not parse'
                  % sock_path, file=sys.stderr)
            raise SystemExit(1)
        session = 1
        printed = set()
        pending = {}   # conn -> (no, ts, words) — the open request
        spans = {}     # conn -> [first_ts, last_ts]
        no = 0
        while True:
            (body_len,) = struct.unpack('>I', recv_exact(sock, 4))
            body = recv_exact(sock, body_len)
            (crc,) = struct.unpack('>I', recv_exact(sock, 4))
            if zlib.crc32(body) != crc:
                print('modbus-replay-dump: the feed sent a corrupt record '
                      '— stopping', file=sys.stderr)
                raise SystemExit(1)
            rec = decode_record(body)
            no += 1
            key = (session, rec['conn'])
            if key not in printed:
                printed.add(key)
                print('conn %d  client %s' % (rec['conn'], rec['peer'] or 'unknown'))
            elif rec['ts'] > 0:
                span = spans.setdefault(key, [rec['ts'], rec['ts']])
                span[1] = max(span[1], rec['ts'])
            when = stamp(rec['ts'])
            if rec['kind'] == KIND_REQ:
                words = frame_words(rec, True)
                pending[rec['conn']] = (no, rec['ts'], words)
                print('  #%d %s  req  %s  (pending)' % (no, when, words))
            elif rec['kind'] == KIND_RSP:
                req = pending.pop(rec['conn'], None)
                words = frame_words(rec, False)
                if req is None:
                    print('  #%d %s  rsp  %s  (orphan — no request recorded)'
                          % (no, when, words))
                else:
                    latency = max(0.0, (rec['ts'] or 0.0) - (req[1] or 0.0))
                    print('  #%d %s  rsp  %s  (%.1fms)' % (no, when, words, latency * 1000.0))
            else:
                print('  #%d %s  raw  %s (%d byte(s))'
                      % (no, when, rec['note'] or 'framing lost', len(rec['raw'])))
    except ConnectionError:
        print('--- the feed closed (the daemon stopped, or the capture '
              'outpaced this viewer — the trace file has everything) ---')


def validate(args):
    problems = []
    if args.socket is not None and args.trace:
        problems.append('a file and a socket feed are two sources — one per run '
                        '(the file gives the three views and the converter, the '
                        'socket the live view)')
    if args.socket is not None and args.to:
        problems.append('--to converts a snapshot — a live feed converts nothing '
                        '(the combo is racy by definition)')
    if args.out and not args.to:
        problems.append('-o writes the converted trace — it needs --to')
    if args.to and not args.out:
        problems.append('--to needs -o OUT (the converted trace\'s path)')
    if args.trace is None and args.socket is None:
        problems.append('give a trace file (the three views, the converter) '
                        'or --socket (the live view)')
    return problems


def main():
    p = argparse.ArgumentParser(
        prog='modbus-replay-dump',
        description='modbus-replay-dump: the trace\'s reader face — the three '
                    'views (the summary, the answer index, the conversations), '
                    'the converter (--to json|binary -o OUT), the live view '
                    '(--socket: the daemon\'s record feed). Both trace shapes '
                    'read the same; the trace is 0600 at rest and belongs with '
                    'the secrets.')
    p.add_argument('trace', nargs='?', help='the trace file (the binary PVMB '
                   'blocks or the JSON v1 lines — the first bytes pick the walk)')
    p.add_argument('--socket', nargs='?', const=DEFAULT_FEED, default=None,
                   metavar='PATH',
                   help='the daemon\'s record feed (--dump-socket): the '
                        'conversations render live; bare --socket spells the '
                        'derived default (/tmp/modbus-replay-<listen-port>.socket)')
    p.add_argument('--to', choices=('json', 'binary'),
                   help='convert the trace to the other shape (with -o OUT)')
    p.add_argument('-o', '--out', help='the converted trace\'s path (0600)')
    p.add_argument('--man', action='store_true',
                   help='print the man page (roff) to stdout and exit '
                        '(modbus-replay-dump --man | man -l -)')
    args = p.parse_args()
    if args.man:
        from lib.man import dump_page
        sys.stdout.write(dump_page(p))
        raise SystemExit(0)
    problems = validate(args)
    if problems:
        for problem in problems:
            print('modbus-replay-dump: %s' % problem, file=sys.stderr)
        raise SystemExit(1)
    try:
        if args.socket is not None:
            live(args.socket)
        elif args.to:
            convert(args.trace, args.to, args.out)
        else:
            idx = TraceIndex(args.trace)
            print('%s: %s' % (args.trace, idx.summary()))
            answer_index(idx)
            conversations(idx)
    except KeyboardInterrupt:
        print('--- stopped ---')
        raise SystemExit(0)


if __name__ == '__main__':
    main()
