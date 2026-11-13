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

print()
print('== the example trace renders ==')

r = subprocess.run([sys.executable, DUMP, EXAMPLE], capture_output=True, text=True)
check('the shipped example: the views render', r.returncode == 0
      and 'the answer index' in r.stdout and 'the conversations' in r.stdout
      and 'PVA1 handshake proof' in r.stdout and 'Waveshare password' in r.stdout
      and 'addr 32064' in r.stdout,
      (r.stdout.strip().splitlines() or ['-'])[0][:120])
check('the shipped example: two sessions named', '(session 2)' in r.stdout, '')

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
      'req  FC3 (read holding registers) unit 1 addr 32064 count 2' in r.stdout
      and 'rsp' in r.stdout and 'ms' in r.stdout,
      next((l for l in r.stdout.splitlines() if 'req' in l and '->' in l), '-')[:140])
check('the refused write rode its exception into the views',
      'FC6 (write single register) unit 1 addr 40001 value 1234' in r.stdout
      and 'exception 1' in r.stdout, '')

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
p_livecap.send_signal(signal.SIGTERM)
p_livecap.wait(timeout=10)
live_log = read_log(LOG % 'live')
check('the live view rendered the exchange',
      'req' in live_log and '(pending)' in live_log and 'rsp' in live_log and 'ms' in live_log,
      next((l for l in live_log.splitlines() if 'pending' in l), '-')[:120])
check('the live view named the client', 'client 127.0.0.1:' in live_log,
      next((l for l in live_log.splitlines() if 'client' in l), '-')[:80])

print()
print('== the posture ==')

for name, proc in (('cap', p_cap), ('rep', p_rep), ('rep0', p_rep0), ('pass', p_pass), ('fake', p_fake)):
    check('%s: alive at the end' % name, proc.poll() is None or proc.returncode == 0,
          str(proc.returncode))
for name in ('cap', 'rep', 'rep0', 'pass', 'fake', 'warn', 'live', 'livecap'):
    log = read_log(LOG % name)
    check('%s: zero tracebacks' % name, 'Traceback' not in log)
for name in ('cap', 'rep', 'rep0', 'pass'):
    check('%s: the loopback bind stayed silent' % name,
          'NOT loopback' not in read_log(LOG % name))
for name in ('cap', 'rep'):
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
