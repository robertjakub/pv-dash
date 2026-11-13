"""replay-regtest: modbus-replay's capture/replay battery — the capture
pipe records both directions (the binary PVMB blocks by default, the
JSON v1 spelling beside it), the walk keeps what a torn tail leaves and
resyncs at the next run header, the dump bin renders the three views
and converts between the shapes, the record feed pushes the records
live (the capture's wire, the replay's served session), the replay
answers byte-identical under the client's own transaction ids, the miss
policies speak (exception 11 / the zero shapes), the ladder's refusals
hold, the pass-through runs without a trace. The device is the fake
inverter (--static). Exits 0 on ALL PASS."""
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'harness'))
from harness import *   # the boot: the gate, the scratch, check(), start(), mbap()

BIN = os.path.join(REPO, 'apps', 'modbus-replay', 'bin', 'modbus-replay.py')
DUMP = os.path.join(REPO, 'apps', 'modbus-replay', 'bin', 'modbus-replay-dump.py')
FAKE = os.path.join(REPO, 'apps', 'inverter', 'bin', 'modbus-fake-inverter.py')
EXAMPLE = os.path.join(REPO, 'extras', 'examples', 'modbus-replay-trace.pvmb')

PORT_FAKE = 15940 + BASE   # the device (the fake inverter)
PORT_CAP = 15941 + BASE    # the capture proxy
PORT_REP = 15942 + BASE    # the replay server (miss exception)
PORT_REP0 = 15943 + BASE   # the replay server (miss zero)
PORT_PASSTHRU = 15944 + BASE   # the pass-through capture (no trace)
TRACE = os.path.join(SCRATCH, 'replay-trace.pvmb')
TRACE_JSON = os.path.join(SCRATCH, 'replay-trace.jsonl')
TRACE_TORN = os.path.join(SCRATCH, 'replay-trace-torn.pvmb')
LOG = os.path.join(SCRATCH, 'replay-%s.log')

TXN = {'fc3': 7701, 'fc4': 7702, 'fc6': 7703, 'fc3b': 7704, 'other': 7799}


def daemon(args, log):
    return start([sys.executable, BIN] + args, log=log)


def raw_exchange(port, pdu, txn, unit=1, timeout=10.0):
    """One full MBAP round trip: the whole frame comes back (the txn
    echo included)."""
    s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    s.sendall(struct.pack('>HHHB', txn, 0, len(pdu) + 1, unit) + pdu)
    head = recvn(s, 7)
    txn_, proto, length, unit_ = struct.unpack('>HHHB', head)
    body = recvn(s, length - 1)
    s.close()
    return head + body


def read_log(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def _header_ok(data, off):
    """The run header at off parses (the resync's validation: the
    magic, the version, the reserved zero, the crc)."""
    if len(data) - off < 16 or data[off:off + 4] != b'PVMB':
        return False
    if data[off + 4] != 1 or data[off + 5] != 0:
        return False
    (up_len,) = struct.unpack_from('>H', data, off + 14)
    end = off + 16 + up_len + 4
    if end > len(data):
        return False
    (crc,) = struct.unpack_from('>I', data, off + 16 + up_len)
    return zlib.crc32(data[off:off + 16 + up_len]) == crc


def walk_pvmb(data, name):
    """The independent binary walk (the suite does not trust the tool's
    own reader for the shape checks): the magic + version, then the
    length-framed crc-checked blocks — the headers and the records
    yielded separately. The walk mirrors the tool's rules: a torn tail
    stops it, a mid-file crc failure resync-scans for the next header."""
    check('%s: the PVMB magic' % name, data[:4] == b'PVMB', data[:8].hex())
    check('%s: the binary version' % name, data[4] == 1 and data[5] == 0,
          'version %d reserved %d' % (data[4], data[5]))
    off = 0
    headers = []
    recs = []
    while off < len(data):
        if data[off:off + 4] == b'PVMB':
            if not _header_ok(data, off):
                break   # a torn tail that opens like a header
            (started, up_len) = struct.unpack_from('>QH', data, off + 6)
            check('%s: the header at %d crc-valid' % (name, off), True,
                  '%d byte(s)' % (16 + up_len + 4))
            headers.append(data[off + 16:off + 16 + up_len].decode())
            off += 16 + up_len + 4
            continue
        if off + 4 > len(data):
            break
        (body_len,) = struct.unpack_from('>I', data, off)
        if off + 4 + body_len + 4 > len(data):
            check('%s: the torn tail at %d' % (name, off), True,
                  'body_len %d past EOF' % body_len)
            break
        body = data[off + 4:off + 4 + body_len]
        (crc,) = struct.unpack_from('>I', data, off + 4 + body_len)
        if zlib.crc32(body) != crc:
            # the resync: the next parseable header re-anchors the walk
            nxt = data.find(b'PVMB', off + 4)
            while nxt != -1 and not _header_ok(data, nxt):
                nxt = data.find(b'PVMB', nxt + 1)
            check('%s: the resync at %d found the re-anchor' % (name, off),
                  nxt is not None and nxt != -1, str(nxt))
            if nxt == -1:
                break
            off = nxt
            continue
        check('%s: the record at %d crc-valid' % (name, off), True,
              'body_len %d' % body_len)
        ts, kind, conn = struct.unpack_from('>dBI', body, 0)
        p = 13
        peer_len = body[p]; p += 1
        peer = body[p:p + peer_len].decode(); p += peer_len
        note_len = body[p]; p += 1
        note = body[p:p + note_len].decode(); p += note_len
        (raw_len,) = struct.unpack_from('>H', body, p); p += 2
        recs.append({'ts': ts, 'kind': kind, 'conn': conn, 'peer': peer,
                     'note': note, 'raw': body[p:p + raw_len]})
        off += 4 + body_len + 4
    return headers, recs


def feed_handshake(sock, name, timeout=10.0):
    """The feed's connect: the full header block (the magic, the
    version, the started stamp, the posture string, the crc) — the
    tail bytes consumed, the stream clean for the records."""
    sock.settimeout(timeout)
    head = b''
    while len(head) < 16:
        chunk = sock.recv(16 - len(head))
        if not chunk:
            raise ConnectionError('the feed closed')
        head += chunk
    up_len = struct.unpack('>H', head[14:16])[0]
    tail = b''
    while len(tail) < up_len + 4:
        chunk = sock.recv(up_len + 4 - len(tail))
        if not chunk:
            raise ConnectionError('the feed closed')
        tail += chunk
    crc = struct.unpack('>I', tail[up_len:])[0]
    check('%s: the feed header crc-valid' % name, zlib.crc32(head + tail[:up_len]) == crc, '')
    return head


def feed_records(sock, n, timeout=10.0):
    """n record blocks off the record feed (the header already read):
    the length prefix, the body, the crc — decoded."""
    sock.settimeout(timeout)
    recs = []
    for _ in range(n):
        buf = b''
        while len(buf) < 4:
            chunk = sock.recv(4 - len(buf))
            if not chunk:
                raise ConnectionError('the feed closed')
            buf += chunk
        (body_len,) = struct.unpack('>I', buf)
        body = b''
        while len(body) < body_len + 4:
            chunk = sock.recv(body_len + 4 - len(body))
            if not chunk:
                raise ConnectionError('the feed closed')
            body += chunk
        crc = struct.unpack('>I', body[body_len:])[0]
        check('the feed record crc-valid', zlib.crc32(body[:body_len]) == crc, '')
        ts, kind, conn = struct.unpack_from('>dBI', body, 0)
        recs.append(kind)
    return recs


print()
print('== the ladder and the refusals ==')

r = subprocess.run([sys.executable, BIN], capture_output=True, text=True)
check('no mode refused', r.returncode == 1 and 'pick a mode' in r.stderr, r.stderr.strip().splitlines()[-1] if r.stderr else '')

r = subprocess.run([sys.executable, BIN, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                    '--replay', TRACE], capture_output=True, text=True)
check('both modes refused', r.returncode == 1 and 'exactly one' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, BIN, '--replay', TRACE], capture_output=True, text=True)
check('a missing trace refused', r.returncode == 1 and 'no such trace file' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, BIN, '--capture', TRACE], capture_output=True, text=True)
check('capture without upstream refused', r.returncode == 1 and 'needs --upstream' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, BIN, '--upstream', 'nonsense-no-port'],
                   capture_output=True, text=True)
check('a malformed upstream refused', r.returncode == 1 and 'HOST:PORT' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

print()
print('== the dump bin\'s refusals ==')

r = subprocess.run([sys.executable, DUMP], capture_output=True, text=True)
check('the dump: no source refused', r.returncode == 1 and 'give a trace file' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, DUMP, 'a.pvmb', '--socket'], capture_output=True, text=True)
check('the dump: two sources refused', r.returncode == 1 and 'two sources' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, DUMP, 'a.pvmb', '--to', 'json'],
                   capture_output=True, text=True)
check('the dump: --to without -o refused', r.returncode == 1 and 'needs -o' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, DUMP, 'a.pvmb', '--to', 'json', '-o', 'b.jsonl', '--socket'],
                   capture_output=True, text=True)
check('the dump: the live-conversion combo refused', r.returncode == 1 and 'racy' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, DUMP, 'a.pvmb', '--record', 'b.pvmb'],
                   capture_output=True, text=True)
check('the dump: --record without a feed refused', r.returncode == 1 and 'rides --socket' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

r = subprocess.run([sys.executable, DUMP, '--quiet'], capture_output=True, text=True)
check('the dump: --quiet without a feed refused', r.returncode == 1 and 'rides --socket' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

print()
print('== the example trace renders ==')

r = subprocess.run([sys.executable, DUMP, EXAMPLE], capture_output=True, text=True)
check('the shipped example: the views render', r.returncode == 0
      and 'the answer index' in r.stdout and 'the conversations' in r.stdout
      and 'PVA1 handshake proof' in r.stdout and 'Waveshare password' in r.stdout
      and 'addr 32064' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[0][:120])
check('the shipped example: two sessions named', '(session 2)' in r.stdout, '')
check('the shipped example: the packets name their sources',
      '127.0.0.1:64824  #1:7  req' in r.stdout and 'inverter-lan:502  #1:7  rsp' in r.stdout
      and 'device inverter-lan:502' in r.stdout
      and '#1:-  raw' in r.stdout and '#2:-  raw' in r.stdout,
      next((l for l in r.stdout.splitlines() if 'device ' in l), '-'))

print()
print('== the device: the fake inverter ==')

p_fake = start([sys.executable, FAKE, '--listen', '127.0.0.1:%d' % PORT_FAKE,
                '--static', '--no-audit-log'], log=LOG % 'fake')
check('the fake inverter came up (port %d)' % PORT_FAKE, wait_port(PORT_FAKE))

print()
print('== the shared-bind warning ==')

p_warn = start([sys.executable, BIN, '--listen', '0.0.0.0:%d' % PORT_PASSTHRU,
                '--upstream', '127.0.0.1:%d' % PORT_FAKE], log=LOG % 'warn')
check('the 0.0.0.0 bind came up (port %d)' % PORT_PASSTHRU, wait_port(PORT_PASSTHRU))
warn_log = read_log(LOG % 'warn')
check('a shared bind warned loudly', 'WARNING: the listen address' in warn_log
      and 'NOT loopback' in warn_log,
      next((l for l in warn_log.splitlines() if 'WARNING' in l), '-')[:100])
p_warn.send_signal(signal.SIGTERM)
p_warn.wait(timeout=10)

print()
print('== capture: the wire to the binary trace ==')

# the feed socket subscribes BEFORE the exchanges: the header + the
# live records come off it
feed_cap = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
FEED_CAP = '/tmp/modbus-replay-%d.socket' % PORT_CAP   # the derived default
p_cap = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                '--log-level', 'DEBUG',
                '--capture', TRACE], LOG % 'cap')
check('the capture proxy came up (port %d)' % PORT_CAP, wait_port(PORT_CAP))
check('the capture bound the record feed', os.path.exists(FEED_CAP), FEED_CAP)
try:
    feed_cap.connect(FEED_CAP)
    head = feed_handshake(feed_cap, 'the capture')
    check('the feed speaks the PVMB header', head[:4] == b'PVMB' and head[4] == 1,
          head[:6].hex())
except OSError as e:
    check('the feed speaks the PVMB header', False, str(e))

fc3_req = struct.pack('>BHH', 3, 32064, 2)
fc4_req = struct.pack('>BHH', 4, 37113, 1)
fc6_req = struct.pack('>BHH', 6, 40001, 1234)
miss_req = struct.pack('>BHH', 3, 40000, 1)
frames = {
    'fc3': raw_exchange(PORT_CAP, fc3_req, TXN['fc3']),
    'fc4': raw_exchange(PORT_CAP, fc4_req, TXN['fc4']),
    'fc6': raw_exchange(PORT_CAP, fc6_req, TXN['fc6']),
    'fc3b': raw_exchange(PORT_CAP, miss_req, TXN['fc3b']),
}
for name, frame_ in frames.items():
    check('capture: the %s exchange answered (%d bytes)' % (name, len(frame_)), len(frame_) > 7,
          frame_.hex())
try:
    kinds = feed_records(feed_cap, 8)
    check('the feed pushed the eight records live',
          kinds == [0, 1, 0, 1, 0, 1, 0, 1], str(kinds))
except (ConnectionError, socket.timeout) as e:
    check('the feed pushed the eight records live', False, str(e))
feed_cap.close()

p_cap.send_signal(signal.SIGTERM)
p_cap.wait(timeout=10)
check('the capture daemon exited 0 on SIGTERM', p_cap.returncode == 0, str(p_cap.returncode))

print()
print('== the binary trace file ==')

check('the trace exists', os.path.exists(TRACE))
mode = os.stat(TRACE).st_mode & 0o777
check('the trace is 0600', mode == 0o600, '%03o' % mode)
headers, recs = walk_pvmb(open(TRACE, 'rb').read(), 'the binary trace')
check('one run header stamped', len(headers) == 1 and str(PORT_FAKE) in headers[0],
      str(headers))
reqs = [r_ for r_ in recs if r_['kind'] == 0]
rsps = [r_ for r_ in recs if r_['kind'] == 1]
raws = [r_ for r_ in recs if r_['kind'] in (2, 3)]
check('the trace holds 4 request + 4 response records', len(reqs) == 4 and len(rsps) == 4,
      '%d req / %d rsp / %d raw' % (len(reqs), len(rsps), len(raws)))
check('no raw records (clean MBAP both ways)', not raws, str(len(raws)))
by_txn = {struct.unpack('>H', r_['raw'][:2])[0]: r_ for r_ in recs}
fc3r = by_txn.get(TXN['fc3'])
check('the request record carries the frame verbatim',
      fc3r is not None and fc3r['raw'] == frames['fc3'], fc3r['raw'].hex() if fc3r else '-')
fc4r = by_txn.get(TXN['fc4'])
check('the response record carries its frame verbatim',
      fc4r is not None and fc4r['kind'] == 1 and fc4r['raw'] == frames['fc4'],
      fc4r['raw'].hex() if fc4r else '-')

print()
print('== the json spelling (--dump-type json) ==')

p_capj = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                 '--dump-type', 'json', '--capture', TRACE_JSON], LOG % 'capj')
check('the json capture came up', wait_port(PORT_CAP))
again = raw_exchange(PORT_CAP, fc3_req, TXN['fc3'])
check('the json capture pipes the wire', again == frames['fc3'], again.hex())
p_capj.send_signal(signal.SIGTERM)
p_capj.wait(timeout=10)

lines = [ln for ln in open(TRACE_JSON, encoding='utf-8').read().splitlines() if ln.strip()]
jrecs = []
for no, ln in enumerate(lines, 1):
    try:
        jrecs.append(json.loads(ln))
    except ValueError:
        check('the json trace line %d is JSON' % no, False, ln[:60])
jheader = jrecs[0] if jrecs else {}
check('the json header names the format', jheader.get('format') == 'pv-suite-modbus-trace'
      and jheader.get('version') == 1, str(jheader))
jreqs = [r_ for r_ in jrecs[1:] if r_.get('dir') == 'req']
jrsp = [r_ for r_ in jrecs[1:] if r_.get('dir') == 'rsp']
check('the json trace holds the request + response records', len(jreqs) == 1 and len(jrsp) == 1,
      '%d req / %d rsp' % (len(jreqs), len(jrsp)))
check('the json record carries the decoded fields',
      jreqs and jreqs[0].get('txn') == TXN['fc3'] and jreqs[0].get('fc') == 3
      and jreqs[0].get('addr') == 32064 and jreqs[0].get('count') == 2 and jreqs[0].get('unit') == 1,
      str(jreqs[0]) if jreqs else '-')

print()
print('== capture: the pair survives the poll gap ==')

# the regression: the capture face once armed both legs with the
# modbus-timeout as a recv timeout — every pair died modbus-timeout into
# the client's first silence, so a scraper polling every 10s re-dialed
# every poll (the flapping: one reachable, one unreachable, the conn #
# climb). The pipe never times a leg: the idle kick belongs to
# --client-timeout alone, and a device that stops answering surfaces
# through the client's own timeout.

def live_exchange(s, pdu, txn):
    s.sendall(struct.pack('>HHHB', txn, 0, len(pdu) + 1, 1) + pdu)
    head = recvn(s, 7)
    txn_, proto, length, unit_ = struct.unpack('>HHHB', head)
    body = recvn(s, length - 1)
    return head + body

p_gap = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                '--modbus-timeout', '1',
                '--capture', TRACE + '.gap.pvmb'], LOG % 'gap')
check('the gap capture came up (modbus-timeout 1s)', wait_port(PORT_CAP))
try:
    s_gap = socket.create_connection(('127.0.0.1', PORT_CAP), timeout=10)
    s_gap.settimeout(10)
    first = live_exchange(s_gap, fc3_req, TXN['fc3'])
    check('the gap pair: the first exchange answered', first == frames['fc3'], first.hex())
    time.sleep(2.5)   # well past the 1s modbus-timeout — the old bug killed here
    second = live_exchange(s_gap, fc3_req, TXN['fc3b'])
    check('the gap pair survived the 2.5s idle on one connection',
          second == struct.pack('>H', TXN['fc3b']) + frames['fc3'][2:], second.hex())
    s_gap.close()
except (OSError, ConnectionError) as e:
    check('the gap pair survived the 2.5s idle on one connection', False, str(e))
p_gap.send_signal(signal.SIGTERM)
p_gap.wait(timeout=10)

p_kick = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                 '--client-timeout', '1',
                 '--capture', TRACE + '.kick.pvmb'], LOG % 'kick')
check('the kick capture came up (client-timeout 1s)', wait_port(PORT_CAP))
try:
    s_kick = socket.create_connection(('127.0.0.1', PORT_CAP), timeout=10)
    s_kick.settimeout(5)
    kicked = s_kick.recv(1)   # the client stays silent: the server closes it, no reply
    check('the kick: --client-timeout ended the silent pair', kicked == b'', kicked.hex())
    s_kick.close()
except (OSError, ConnectionError) as e:
    check('the kick: --client-timeout ended the silent pair', False, str(e))
p_kick.send_signal(signal.SIGTERM)
p_kick.wait(timeout=10)

print()
print('== two clients, one capture (the pairing) ==')

# two clients on one capture proxy never cross-pair: every accepted
# client gets its own upstream connection and its own conn id, a
# response can only arrive on the socket pair that carried its request,
# and the pairing walks the MBAP transaction id inside the connection —
# pipelined requests included (the most recent open one stands in for a
# device that echoes a foreign id).

TRACE_TWO = TRACE + '.two.pvmb'
TXN_TWO = {'a1': 7711, 'b1': 7712, 'b2': 7713, 'a2': 7714, 'a3': 7715, 'a4': 7716}
fc3_two = struct.pack('>BHH', 3, 32003, 1)   # client B's distinguishing shape

def read_frame(s):
    head = recvn(s, 7)
    txn_, proto, length, unit_ = struct.unpack('>HHHB', head)
    return head + recvn(s, length - 1)

p_two = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                '--capture', TRACE_TWO], LOG % 'two')
check('the two-client capture came up', wait_port(PORT_CAP))
try:
    s_a = socket.create_connection(('127.0.0.1', PORT_CAP), timeout=10)
    s_a.settimeout(10)
    s_b = socket.create_connection(('127.0.0.1', PORT_CAP), timeout=10)
    s_b.settimeout(10)
    a1 = live_exchange(s_a, fc3_req, TXN_TWO['a1'])
    check('client A: the fc3 exchange answered',
          a1 == struct.pack('>H', TXN_TWO['a1']) + frames['fc3'][2:], a1.hex())
    b1 = live_exchange(s_b, fc4_req, TXN_TWO['b1'])
    check('client B: the fc4 exchange answered',
          b1 == struct.pack('>H', TXN_TWO['b1']) + frames['fc4'][2:], b1.hex())
    b2 = live_exchange(s_b, fc3_two, TXN_TWO['b2'])
    check('client B: the fc3 32003 exchange answered',
          b2[:7] == struct.pack('>HHHB', TXN_TWO['b2'], 0, 5, 1) and b2[7] == 3, b2.hex())
    a2 = live_exchange(s_a, fc6_req, TXN_TWO['a2'])
    check('client A: the fc6 exchange answered',
          a2[:2] == struct.pack('>H', TXN_TWO['a2']), a2.hex())
    # the pipelining probe: two requests on the wire before either
    # answer is read — the txn-aware pairing keeps both straight
    s_a.sendall(struct.pack('>HHHB', TXN_TWO['a3'], 0, len(fc3_req) + 1, 1) + fc3_req)
    s_a.sendall(struct.pack('>HHHB', TXN_TWO['a4'], 0, len(fc4_req) + 1, 1) + fc4_req)
    a3 = read_frame(s_a)
    a4 = read_frame(s_a)
    check('the pipelined pair answered both, in order',
          a3[:2] == struct.pack('>H', TXN_TWO['a3']) and a3[7:] == frames['fc3'][7:]
          and a4[:2] == struct.pack('>H', TXN_TWO['a4']),
          (a3 + a4).hex())
    s_a.close()
    s_b.close()
except (OSError, ConnectionError) as e:
    check('the two-client capture ran', False, str(e))
p_two.send_signal(signal.SIGTERM)
p_two.wait(timeout=10)

two_headers, two_recs = walk_pvmb(open(TRACE_TWO, 'rb').read(), 'the two-client trace')
two_reqs = [r_ for r_ in two_recs if r_['kind'] == 0]
two_rsps = [r_ for r_ in two_recs if r_['kind'] == 1]
two_raws = [r_ for r_ in two_recs if r_['kind'] in (2, 3)]
check('the two-client trace holds 6 request + 6 response records',
      len(two_reqs) == 6 and len(two_rsps) == 6,
      '%d req / %d rsp / %d raw' % (len(two_reqs), len(two_rsps), len(two_raws)))
two_keys = lambda recs: {(r_['conn'], struct.unpack('>H', r_['raw'][:2])[0])
                         for r_ in recs if r_['raw']}
check('every response rode its request\'s connection + txn',
      two_keys(two_reqs) == two_keys(two_rsps) and len(two_keys(two_reqs)) == 6,
      str(sorted(two_keys(two_rsps))))
check('the two clients rode two distinct conn ids',
      len({r_['conn'] for r_ in two_recs}) == 2,
      str(sorted({r_['conn'] for r_ in two_recs})))

r = subprocess.run([sys.executable, DUMP, TRACE_TWO], capture_output=True, text=True)
heads = [ln for ln in r.stdout.splitlines() if ln.startswith('conn ')]
check('the dump pairs both clients, zero orphans',
      r.returncode == 0 and '0 orphan(s)' in r.stdout and '(orphan' not in r.stdout
      and len(heads) == 2 and all('client 127.0.0.1:' in h for h in heads),
      next((h for h in heads), r.stdout.splitlines()[0] if r.stdout else '-')[:140])
blocks, cur = {}, None
for ln in r.stdout.splitlines():
    if ln.startswith('conn '):
        cur = ln.split()[1]
        blocks[cur] = []
    elif cur is not None:
        blocks[cur].append(ln)
fc6_block = next((k for k, v in blocks.items()
                  if any('addr 40001 value 1234' in ln for ln in v)), None)
b_block = next((k for k, v in blocks.items()
                if any('addr 32003' in ln for ln in v)), None)
check('the conversations keep the clients apart',
      fc6_block is not None and b_block is not None and fc6_block != b_block,
      str({k: len(v) for k, v in blocks.items()}))

print()
print('== the converter: between the shapes ==')

r = subprocess.run([sys.executable, DUMP, TRACE, '--to', 'json', '-o', TRACE_JSON + '.conv'],
                   capture_output=True, text=True)
check('binary -> json converted', r.returncode == 0 and 'written as json' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[-1])
r = subprocess.run([sys.executable, DUMP, TRACE_JSON + '.conv', '--to', 'binary',
                    '-o', TRACE + '.conv'], capture_output=True, text=True)
check('json -> binary converted', r.returncode == 0 and 'written as binary' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[-1])
_, conv_recs = walk_pvmb(open(TRACE + '.conv', 'rb').read(), 'the converted trace')
check('the round trip carries the same records',
      [(r_['kind'], r_['raw']) for r_ in conv_recs] == [(r_['kind'], r_['raw']) for r_ in recs],
      '%d vs %d record(s)' % (len(conv_recs), len(recs)))
check('the converted trace is 0600', os.stat(TRACE + '.conv').st_mode & 0o777 == 0o600, '')

print()
print('== the torn tail and the second run (the resync) ==')

data = open(TRACE, 'rb').read()
open(TRACE_TORN, 'wb').write(data + b'\x00\x00\x00\x50' + b'garbage!')
# a second capture run appends onto the torn file: the reader resyncs
# at the new run's header
p_cap2 = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                 '--capture', TRACE_TORN], LOG % 'cap2')
check('the second capture came up', wait_port(PORT_CAP))
torn_again = raw_exchange(PORT_CAP, fc3_req, TXN['fc3'])
check('the second capture answered', torn_again == frames['fc3'], torn_again.hex())
p_cap2.send_signal(signal.SIGTERM)
p_cap2.wait(timeout=10)

torn_headers, torn_recs = walk_pvmb(open(TRACE_TORN, 'rb').read(), 'the torn trace')
check('the torn trace holds two run headers', len(torn_headers) == 2, str(len(torn_headers)))
check('the torn trace indexed both runs\' pairs', len([r_ for r_ in torn_recs if r_['kind'] == 0]) == 5
      and len([r_ for r_ in torn_recs if r_['kind'] == 1]) == 5,
      '%d req / %d rsp' % (len([r_ for r_ in torn_recs if r_['kind'] == 0]),
                           len([r_ for r_ in torn_recs if r_['kind'] == 1])))

r = subprocess.run([sys.executable, DUMP, TRACE_TORN], capture_output=True, text=True)
check('the dump renders the torn trace', r.returncode == 0 and '2 session(s)' in r.stdout
      and 'damaged record(s) skipped' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[0][:140])
check('the dump names the sessions in the conversations', '(session 2)' in r.stdout, '')

print()
print('== the dump bin\'s static views ==')

r = subprocess.run([sys.executable, DUMP, TRACE], capture_output=True, text=True)
check('the dump renders the summary', r.returncode == 0 and '4 request(s)' in r.stdout
      and '4 response(s) indexed' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[0][:140])
check('the answer index carries the query, the data words, the latency, the ask count',
      'FC3 (read holding registers) unit 1 addr 32064 count 2 ->' in r.stdout
      and 'asked 1x' in r.stdout and 'latency' in r.stdout,
      next((l for l in r.stdout.splitlines() if '->' in l), '-')[:140])
check('the values dump address-prefixed under the lines',
      '32064:  ' in r.stdout, next((l for l in r.stdout.splitlines() if '32064:' in l), '-'))
check('the conversations pair the exchange',
      '  req  FC3 (read holding registers) unit 1 addr 32064 count 2' in r.stdout
      and ':%d  rsp' % TXN['fc3'] in r.stdout and 'ms' in r.stdout,
      next((l for l in r.stdout.splitlines() if 'req' in l and '->' in l), '-')[:140])
check('the conversations name both ends of the pipe',
      'client 127.0.0.1:' in r.stdout
      and 'device 127.0.0.1:%d' % PORT_FAKE in r.stdout,
      next((l for l in r.stdout.splitlines() if 'device ' in l), '-'))
check('the refused write rode its exception into the views',
      'FC6 (write single register) unit 1 addr 40001 value 1234' in r.stdout
      and 'exception 1' in r.stdout, '')

print()
print('== the values cap (--values-cap) ==')

# its own wide read (20 words — the static trace's reads are small) on
# a fresh capture: the wide trace is its own file, TRACE stays the
# earlier pins' subject
TRACE_WIDE = os.path.join(SCRATCH, 'replay-trace-wide.pvmb')
p_wide = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                 '--capture', TRACE_WIDE], LOG % 'wide')
check('the wide capture came up', wait_port(PORT_CAP))
wide = raw_exchange(PORT_CAP, struct.pack('>BHH', 3, 32064, 20), TXN['other'])
check('the wide read answered (20 words)', len(wide) > 7 and wide[8] == 40, wide.hex())
p_wide.send_signal(signal.SIGTERM)
p_wide.wait(timeout=10)

r = subprocess.run([sys.executable, DUMP, TRACE_WIDE], capture_output=True, text=True)
check('the conversations cap at 16 words by default (+4 more), the answer index full',
      '(+4 more)' in r.stdout and '32080:  ' in r.stdout,
      next((l for l in r.stdout.splitlines() if '(+' in l), r.stdout[:140]))
r = subprocess.run([sys.executable, DUMP, TRACE_WIDE, '--values-cap', 'all'],
                   capture_output=True, text=True)
check('--values-cap all renders the whole block (the marker gone, the index full)',
      r.returncode == 0 and '(+' not in r.stdout and '32080:  ' in r.stdout,
      next((l for l in r.stdout.splitlines() if '32080:' in l), '-'))
r = subprocess.run([sys.executable, DUMP, TRACE_WIDE, '--values-cap', '8'],
                   capture_output=True, text=True)
check('--values-cap 8 moves the cap (+12 more)', '(+12 more)' in r.stdout,
      next((l for l in r.stdout.splitlines() if '(+' in l), '-'))
r = subprocess.run([sys.executable, DUMP, TRACE_WIDE, '--values-cap', '0'],
                   capture_output=True, text=True)
check('--values-cap 0 refuses (the CLI misuse, rc 2)', r.returncode == 2,
      (r.stderr.strip().splitlines() or ['-'])[-1])
r = subprocess.run([sys.executable, DUMP, TRACE_WIDE, '--values-cap', 'x'],
                   capture_output=True, text=True)
check('--values-cap x refuses (the CLI misuse, rc 2)', r.returncode == 2,
      (r.stderr.strip().splitlines() or ['-'])[-1])
r = subprocess.run([sys.executable, DUMP, '--socket', '/tmp/no-such-feed-%d.socket' % BASE,
                    '--values-cap', '8'], capture_output=True, text=True)
check('the live view refuses --values-cap without --values (rc 1)',
      r.returncode == 1 and '--values-cap shapes the values dump' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

print()
print('== replay: the trace back on the wire ==')

# the replay's feed subscribes before the queries: the served session
# pushes live
feed_rep = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
FEED_REP = '/tmp/modbus-replay-%d.socket' % PORT_REP
p_rep = daemon(['--listen', '127.0.0.1:%d' % PORT_REP, '--replay', TRACE], LOG % 'rep')
check('the replay server came up (port %d)' % PORT_REP, wait_port(PORT_REP))
check('the replay bound its record feed', os.path.exists(FEED_REP), FEED_REP)
try:
    feed_rep.connect(FEED_REP)
    head = feed_handshake(feed_rep, 'the replay')
    check('the replay\'s feed speaks the PVMB header', head[:4] == b'PVMB', head[:6].hex())
except OSError as e:
    check('the replay\'s feed speaks the PVMB header', False, str(e))

for name, req in (('fc3', fc3_req), ('fc4', fc4_req), ('fc6', fc6_req), ('fc3b', miss_req)):
    again = raw_exchange(PORT_REP, req, TXN[name])
    check('replay %s: byte-identical to the capture' % name, again == frames[name],
          '%s vs %s' % (again.hex(), frames[name].hex()))
other = raw_exchange(PORT_REP, fc3_req, TXN['other'])
check('the replay speaks the client\'s own transaction id',
      other[:2] == struct.pack('>H', TXN['other']) and other[7:] == frames['fc3'][7:],
      other.hex())

miss = raw_exchange(PORT_REP, struct.pack('>BHH', 3, 55555, 3), TXN['other'])
check('the miss answers exception 11', miss[7:] == b'\x83\x0b', miss.hex())

try:
    kinds = feed_records(feed_rep, 10)   # 4 answered pairs + the miss's pair = 10
    check('the replay\'s feed pushed the served session',
          kinds == [0, 1] * 5, str(kinds))
except (ConnectionError, socket.timeout) as e:
    check('the replay\'s feed pushed the served session', False, str(e))
feed_rep.close()

p_rep.send_signal(signal.SIGTERM)
p_rep.wait(timeout=10)
check('the replay daemon exited 0 on SIGTERM', p_rep.returncode == 0, str(p_cap.returncode))

print()
print('== the zero-miss policy ==')

p_rep0 = daemon(['--listen', '127.0.0.1:%d' % PORT_REP0, '--replay', TRACE,
                 '--replay-miss', 'zero'], LOG % 'rep0')
check('the zero-mode replay came up (port %d)' % PORT_REP0, wait_port(PORT_REP0))

z = raw_exchange(PORT_REP0, struct.pack('>BHH', 3, 55555, 3), TXN['other'])
check('the zero FC3 miss: the byte count + zero data',
      z[7:] == b'\x03\x06' + b'\x00' * 6, z.hex())
z1 = raw_exchange(PORT_REP0, struct.pack('>BHH', 1, 100, 10), TXN['other'])
check('the zero FC1 miss: the bits + zero data',
      z1[7:] == b'\x01\x02\x00\x00', z1.hex())
z2 = raw_exchange(PORT_REP0, struct.pack('>BHH', 3, 0, 200), TXN['other'])
check('the oversize count answers exception 3', z2[7:] == b'\x83\x03', z2.hex())
z3 = raw_exchange(PORT_REP0, struct.pack('>BB', 43, 1), TXN['other'])
check('an unshapeable function answers exception 1', z3[7:] == b'\xab\x01', z3.hex())
z4 = raw_exchange(PORT_REP0, struct.pack('>BHH', 5, 100, 0xFF00), TXN['other'])
check('the zero FC5 miss echoes', z4[7:] == b'\x05\x00\x64\xff\x00', z4.hex())

p_rep0.send_signal(signal.SIGTERM)
p_rep0.wait(timeout=10)

print()
print('== the pass-through capture (no trace) ==')

p_pass = daemon(['--listen', '127.0.0.1:%d' % PORT_PASSTHRU, '--upstream', '127.0.0.1:%d' % PORT_FAKE],
                LOG % 'pass')
check('the pass-through came up (port %d)' % PORT_PASSTHRU, wait_port(PORT_PASSTHRU))
again = raw_exchange(PORT_PASSTHRU, fc3_req, TXN['fc3'])
check('the pass-through pipes the wire untouched', again == frames['fc3'], again.hex())
p_pass.send_signal(signal.SIGTERM)
p_pass.wait(timeout=10)

print()
print('== the live view (the dump bin on the feed) ==')

# its own capture daemon: the earlier captures terminated at their
# sections' ends, the live view needs a live feed to watch
p_livecap = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                    '--capture', TRACE], LOG % 'livecap')
check('the live-viewed capture came up', wait_port(PORT_CAP))
p_live = start([sys.executable, DUMP, '--socket', FEED_CAP], log=LOG % 'live')
time.sleep(1.0)
live_again = raw_exchange(PORT_CAP, fc3_req, TXN['fc3'])
check('the live-viewed capture pipes the wire', live_again == frames['fc3'], live_again.hex())
time.sleep(1.0)
p_live.send_signal(signal.SIGTERM)
p_live.wait(timeout=10)
p_livev = start([sys.executable, DUMP, '--socket', FEED_CAP, '--values'],
                log=LOG % 'livev')
time.sleep(1.0)
livev_again = raw_exchange(PORT_CAP, fc3_req, TXN['fc3'])
check('the values-viewed capture pipes the wire', livev_again == frames['fc3'],
      livev_again.hex())
time.sleep(1.0)
p_livev.send_signal(signal.SIGTERM)
p_livev.wait(timeout=10)
p_livecapw = start([sys.executable, DUMP, '--socket', FEED_CAP, '--values',
                    '--values-cap', '4'], log=LOG % 'livecapw')
time.sleep(1.0)
livecapw_again = raw_exchange(PORT_CAP, struct.pack('>BHH', 3, 32064, 20), TXN['other'])
check('the cap-viewed capture pipes the wide read', len(livecapw_again) > 7
      and livecapw_again[8] == 40, livecapw_again.hex())
time.sleep(1.0)
p_livecapw.send_signal(signal.SIGTERM)
p_livecapw.wait(timeout=10)
live_log = read_log(LOG % 'live')
check('the live view rendered the exchange',
      'req' in live_log and '(pending)' in live_log and 'rsp' in live_log and 'ms' in live_log,
      next((l for l in live_log.splitlines() if 'pending' in l), '-')[:120])
check('the live view named the client', 'client 127.0.0.1:' in live_log,
      next((l for l in live_log.splitlines() if 'client' in l), '-')[:80])
check('the live view named the answer\'s source (the device)',
      ':%d  rsp' % TXN['fc3'] in live_log,
      next((l for l in live_log.splitlines() if 'rsp' in l), '-')[:100])
check('the live view hides the values by default',
      '32064:  ' not in live_log and 'pending' in live_log,
      next((l for l in live_log.splitlines() if 'pending' in l), '-')[:120])
livev_log = read_log(LOG % 'livev')
check('the live view dumps the values under --values',
      '32064:  ' in livev_log and 'rsp' in livev_log,
      next((l for l in livev_log.splitlines() if '32064:' in l), '-')[:100])
livecapw_log = read_log(LOG % 'livecapw')
check('the live view honors --values-cap (the wide read capped at 4, +16 more)',
      '32064:  ' in livecapw_log and '(+16 more)' in livecapw_log,
      next((l for l in livecapw_log.splitlines() if '(+' in l), '-')[:120])

print()
print('== the recorder (--record on the live view) ==')

# the recorder face: the feed's bytes land verbatim — a record in the
# file is byte-identical to the one the daemon's own --capture writes
# off the same emit, so the walk compares the two files' records one to
# one. The daemon keeps capturing to TRACE; the recorder watches the feed.
TRACE_REC = os.path.join(SCRATCH, 'replay-trace-rec.pvmb')
p_rec = start([sys.executable, DUMP, '--socket', FEED_CAP, '--record', TRACE_REC],
              log=LOG % 'rec')
time.sleep(1.0)
rec_again = raw_exchange(PORT_CAP, fc4_req, TXN['fc4'])
check('the recorded capture pipes the wire', rec_again == frames['fc4'], rec_again.hex())
time.sleep(1.0)
p_rec.send_signal(signal.SIGTERM)
p_rec.wait(timeout=10)

check('the recorded trace exists', os.path.exists(TRACE_REC))
check('the recorded trace is 0600',
      os.stat(TRACE_REC).st_mode & 0o777 == 0o600, '%03o' % (os.stat(TRACE_REC).st_mode & 0o777))
rec_headers, rec_recs = walk_pvmb(open(TRACE_REC, 'rb').read(), 'the recorded trace')
check('the recorded trace holds one run header (the feed\'s posture)',
      len(rec_headers) == 1 and str(PORT_FAKE) in rec_headers[0], str(rec_headers))
check('the recorded trace holds the exchange',
      [(r_['kind'], r_['raw']) for r_ in rec_recs]
      == [(0, struct.pack('>HHHB', TXN['fc4'], 0, len(fc4_req) + 1, 1) + fc4_req),
          (1, frames['fc4'])],
      str([(r_['kind'], r_['raw'].hex()) for r_ in rec_recs]))
_, trace_now = walk_pvmb(open(TRACE, 'rb').read(), 'the capture trace')
check('the recorded records are byte-identical to the capture\'s',
      [(r_['kind'], r_['raw']) for r_ in rec_recs]
      == [(r_['kind'], r_['raw']) for r_ in trace_now[-2:]],
      '%d recorded / %d captured' % (len(rec_recs), len(trace_now)))

# the quiet recorder renders nothing per record — and the feed's close
# (the daemon's SIGTERM) ends it by itself, exit 0, the save tally told
TRACE_QUIET = os.path.join(SCRATCH, 'replay-trace-quiet.pvmb')
p_quiet = start([sys.executable, DUMP, '--socket', FEED_CAP, '--record', TRACE_QUIET,
                 '--quiet'], log=LOG % 'quiet')
time.sleep(1.0)
quiet_again = raw_exchange(PORT_CAP, fc3_req, TXN['fc3b'])
check('the quiet-viewed capture pipes the wire',
      quiet_again == struct.pack('>H', TXN['fc3b']) + frames['fc3'][2:], quiet_again.hex())
time.sleep(1.0)
p_livecap.send_signal(signal.SIGTERM)
p_livecap.wait(timeout=10)
p_quiet.wait(timeout=10)
check('the quiet recorder ended by itself when the feed closed',
      p_quiet.returncode == 0, str(p_quiet.returncode))
quiet_headers, quiet_recs = walk_pvmb(open(TRACE_QUIET, 'rb').read(), 'the quiet trace')
check('the quiet trace holds the exchange',
      [(r_['kind'], r_['raw']) for r_ in quiet_recs]
      == [(0, struct.pack('>HHHB', TXN['fc3b'], 0, len(fc3_req) + 1, 1) + fc3_req),
          (1, struct.pack('>H', TXN['fc3b']) + frames['fc3'][2:])],
      str([(r_['kind'], r_['raw'].hex()) for r_ in quiet_recs]))
quiet_log = read_log(LOG % 'quiet')
check('the quiet recorder rendered nothing per record',
      'req' not in quiet_log and 'pending' not in quiet_log and 'rsp' not in quiet_log,
      next((l for l in quiet_log.splitlines() if 'req' in l or 'rsp' in l), '-')[:100])
check('the quiet recorder told the save tally',
      'record(s) recorded' in quiet_log and '--- the live feed on' in quiet_log,
      next((l for l in quiet_log.splitlines() if 'record(s) recorded' in l), '-')[:100])

r = subprocess.run([sys.executable, DUMP, TRACE_REC], capture_output=True, text=True)
check('the recorded trace renders like a captured one',
      r.returncode == 0 and 'the answer index' in r.stdout and '0 orphan(s)' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[0][:140])

# the re-connected recorder appends: the feed re-stamps its header per
# subscriber connect, the second session's header the boundary the
# reader walks (two sessions, both exchanges served)
p_recap = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                  '--capture', TRACE], LOG % 'livecap2')
check('the append capture came up', wait_port(PORT_CAP))
p_rec2 = start([sys.executable, DUMP, '--socket', FEED_CAP, '--record', TRACE_REC, '--quiet'],
               log=LOG % 'rec2')
time.sleep(1.0)
rec2_again = raw_exchange(PORT_CAP, fc3_req, TXN['fc3'])
check('the append capture pipes the wire', rec2_again == frames['fc3'], rec2_again.hex())
time.sleep(1.0)
p_rec2.send_signal(signal.SIGTERM)
p_rec2.wait(timeout=10)
p_recap.send_signal(signal.SIGTERM)
p_recap.wait(timeout=10)

rec2_headers, rec2_recs = walk_pvmb(open(TRACE_REC, 'rb').read(), 'the appended trace')
check('the appended trace holds two run headers', len(rec2_headers) == 2, str(len(rec2_headers)))
check('the appended trace holds both sessions\' exchanges', len(rec2_recs) == 4,
      '%d record(s)' % len(rec2_recs))
r = subprocess.run([sys.executable, DUMP, TRACE_REC], capture_output=True, text=True)
check('the reader walks the appended trace\'s two sessions',
      r.returncode == 0 and '2 session(s)' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[0][:140])

r = subprocess.run([sys.executable, DUMP, EXAMPLE, '--values'],
                   capture_output=True, text=True)
check('the dump: --values refused on the file views',
      r.returncode == 1 and 'rides the live view' in r.stderr,
      (r.stderr.strip().splitlines() or ['-'])[-1])

print()
print('== the posture ==')

for name, proc in (('cap', p_cap), ('rep', p_rep), ('rep0', p_rep0), ('pass', p_pass),
                   ('wide', p_wide), ('fake', p_fake)):
    check('%s: alive at the end' % name, proc.poll() is None or proc.returncode == 0,
          str(proc.returncode))
for name in ('cap', 'rep', 'rep0', 'pass', 'fake', 'warn', 'wide', 'live', 'livev',
             'livecapw', 'livecap', 'rec', 'quiet', 'rec2', 'livecap2'):
    log = read_log(LOG % name)
    check('%s: zero tracebacks' % name, 'Traceback' not in log)
for name in ('cap', 'rep', 'rep0', 'pass', 'wide'):
    check('%s: the loopback bind stayed silent' % name,
          'NOT loopback' not in read_log(LOG % name))
for name in ('cap', 'rep', 'wide'):
    check('%s: the record feed logged' % name, 'the record feed on' in read_log(LOG % name))
rep_log = read_log(LOG % 'rep')
check('the miss logged with the request spelled out',
      'replay miss for FC3 (read holding registers) unit 1 addr 55555 count 3' in rep_log)
cap_log = read_log(LOG % 'cap')
check('the capture logged the summary', 'capture summary:' in cap_log)
check('the capture logged the response as a reply shape',
      'recv FC3 (read holding registers) unit 1 4 data byte(s) (2 register(s))' in cap_log,
      next((l for l in cap_log.splitlines() if 'recv' in l and 'FC3' in l), '-')[:120])
check('the replay logged the summary', 'replay summary:' in read_log(LOG % 'rep'))

kill_all()
print()
print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
