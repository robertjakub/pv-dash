#!/usr/bin/env python3
"""Render the modbus-replay example trace — the shipped sample
(extras/examples/modbus-replay-trace.pvmb) the README's format section
points at: a small, deterministic capture wearing everything the format
can carry. Two sessions (two runs' headers — a multi-run file is a
longer history), the suite-auth handshake peeled and named (the PVA1
proof the family's own auth_mac computes — a demo key, a fixed nonce —
and the OK verdict), one Waveshare session (the raw-ASCII password),
the polls with their recorded latencies (the FC3 repeat climbs the ask
count), a refused write riding its exception, one framing-lost record.

The bytes are FIXED (the stamps are literals, not the wall clock), so
the default render is reproducible and the --check gate is stable;
--exchanges renders a longer sample (the shapes cycle, the transaction
ids count up) for the bench — the gate always pins the default:

  python3 dev/generators/trace_example.py                  # the default render
  python3 dev/generators/trace_example.py --exchanges 20   # a longer bench sample (-o moves it)
  python3 dev/generators/trace_example.py --check          # exit 1 when the shipped file drifts

The record bytes build through lib.trace's own encoders — the sample
cannot drift from the format's real shape. The content is SYNTHETIC
(the keys, the passwords, the values are filler) — an example, not a
secret, so it ships 0644 with the other extras. Stdlib only."""
import argparse
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)                                         # common/
sys.path.insert(0, os.path.join(REPO, 'apps', 'modbus-replay'))  # lib/trace

from common.modbus.protocol import AUTH_MAGIC, auth_mac
from lib.trace import (KIND_RAW_C2D, KIND_RAW_D2C, KIND_REQ, KIND_RSP,
                       encode_header, encode_record)

OUT = os.path.join(REPO, 'extras', 'examples', 'modbus-replay-trace.pvmb')

BASE = 1794588996.048          # the README's example epoch — fixed, not the wall clock
DEMO_KEY = 'demo-key-not-a-secret'   # the suite auth's demo key (>= the 16-char floor)
DEMO_NONCE = bytes(range(16))        # fixed: the example is deterministic

# the polls a SUN2000 morning speaks, cycled in order: the holding
# registers, the input register, the refused write (exception 1), the
# bits read, the derate word
POLL_SHAPES = (
    ('fc3', 32064, 2, (0x0190, 0x00f0)),
    ('fc4', 37113, 1, (0x07d0,)),
    ('fc6', 40001, 1234, None),
    ('fc1', 100, 10, (0x00ff,)),
    ('fc3', 32003, 1, (0x0bb8,)),
)
LATENCIES = (0.0123, 0.0097, 0.0062, 0.0118, 0.0084, 0.0071)
GAP = 0.018                    # the fixed pause between the exchanges


def poll_pair(txn, shape):
    """One exchange's (req, rsp) MBAP frames for a shape: the wrapper
    around the struct-built PDUs; the refused write's answer is its
    exception (illegal function)."""
    kind, addr, count, words = shape
    unit = 1
    if kind == 'fc3':
        req_pdu = struct.pack('>BHH', 3, addr, count)
        rsp_pdu = struct.pack('>BB', 3, count * 2) + \
            b''.join(struct.pack('>H', w) for w in words)
    elif kind == 'fc4':
        req_pdu = struct.pack('>BHH', 4, addr, count)
        rsp_pdu = struct.pack('>BB', 4, count * 2) + \
            b''.join(struct.pack('>H', w) for w in words)
    elif kind == 'fc1':
        nbytes = (count + 7) // 8
        data = b''.join(struct.pack('>H', w) for w in words)
        req_pdu = struct.pack('>BHH', 1, addr, count)
        rsp_pdu = struct.pack('>BB', 1, nbytes) + (data + b'\x00' * nbytes)[:nbytes]
    else:   # fc6: the write the device refuses
        req_pdu = struct.pack('>BHH', 6, addr, count)
        rsp_pdu = struct.pack('>BB', 0x86, 1)
    req = struct.pack('>HHHB', txn, 0, len(req_pdu) + 1, unit) + req_pdu
    rsp = struct.pack('>HHHB', txn, 0, len(rsp_pdu) + 1, unit) + rsp_pdu
    return req, rsp


def build(exchanges=20):
    """The sample's bytes: two runs — session 1 speaks the suite-auth
    handshake then `exchanges` poll exchanges (the shapes cycle, the
    ask counts climb), session 2 speaks the Waveshare password and two
    more polls, plus one framing-lost burst."""
    out = bytearray()
    # --- session 1: the suite-auth handshake, then the polls ---
    out += encode_header('inverter-lan:502', int(BASE) - 1)
    proof = AUTH_MAGIC + DEMO_NONCE + auth_mac(DEMO_KEY, DEMO_NONCE)
    out += encode_record(BASE, KIND_RAW_C2D, 1, '127.0.0.1:64824',
                         'PVA1 handshake proof', proof)
    out += encode_record(BASE + 0.005, KIND_RAW_D2C, 1, 'inverter-lan:502',
                         'auth verdict', b'OK')
    ts = BASE + 0.010
    for i in range(exchanges):
        req, rsp = poll_pair(0x0007 + i, POLL_SHAPES[i % len(POLL_SHAPES)])
        gap = LATENCIES[i % len(LATENCIES)]
        out += encode_record(ts, KIND_REQ, 1, '127.0.0.1:64824', None, req)
        out += encode_record(ts + gap, KIND_RSP, 1, 'inverter-lan:502', None, rsp)
        ts += gap + GAP
    # --- session 2: a second run (the conn ids restart), the Waveshare
    # password this time, two more polls (the same queries — the ask
    # counts climb), one framing-lost burst ---
    out += encode_header('waveshare-gw:502', int(BASE) + 60)
    out += encode_record(BASE + 60.010, KIND_RAW_C2D, 1, '127.0.0.1:64901',
                         'Waveshare password', b'sun2000!')
    out += encode_record(BASE + 60.015, KIND_RAW_D2C, 1, 'waveshare-gw:502',
                         'auth verdict', b'OK')
    ts = BASE + 60.020
    for i in range(2):
        req, rsp = poll_pair(0x0007 + exchanges + i, POLL_SHAPES[i % len(POLL_SHAPES)])
        gap = LATENCIES[i % len(LATENCIES)]
        out += encode_record(ts, KIND_REQ, 1, '127.0.0.1:64901', None, req)
        out += encode_record(ts + gap, KIND_RSP, 1, 'waveshare-gw:502', None, rsp)
        ts += gap + GAP
    out += encode_record(BASE + 60.040, KIND_RAW_C2D, 2, '127.0.0.1:64999',
                         'framing lost — raw bytes only', b'\x01\x02\x03\x04\x05')
    return bytes(out)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog='trace_example',
        description='render the modbus-replay example trace '
                    '(extras/examples/modbus-replay-trace.pvmb) — '
                    'deterministic bytes; --check pins the default render')
    p.add_argument('--exchanges', type=int, default=20, metavar='N',
                   help='the poll exchanges session 1 speaks (default 20; '
                        'the shapes cycle — bench renders only, --check '
                        'always pins the default)')
    p.add_argument('-o', '--out', default=OUT, help='the output path '
                   '(default: the shipped example)')
    p.add_argument('--check', action='store_true',
                   help='compare the shipped file against the default '
                        'render; exit 1 on drift')
    args = p.parse_args(argv)
    data = build() if args.check else build(max(1, args.exchanges))
    if args.check:
        try:
            with open(OUT, 'rb') as f:
                shipped = f.read()
        except OSError as e:
            raise SystemExit('trace_example: %s: %s' % (OUT, e))
        if shipped != data:
            raise SystemExit('trace_example: %s drifted — re-run the generator'
                             % OUT)
        print('trace_example: %s is current' % OUT)
        return
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'wb') as f:
        f.write(data)
    if out == OUT:
        os.chmod(out, 0o644)
    else:
        os.chmod(out, 0o600)   # a bench render rides the trace's own posture
    print('trace_example: wrote %s (%d bytes, %d exchange(s))'
          % (out, len(data), max(1, args.exchanges)))


if __name__ == '__main__':
    main()
