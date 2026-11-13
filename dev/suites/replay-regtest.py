"""replay-regtest: modbus-replay's capture/replay battery — the capture
pipe records both directions (the decoded fields, the exceptions), the
replay answers byte-identical under the client's own transaction ids,
the miss policies speak (exception 11 / the zero shapes), the ladder's
refusals hold, the pass-through runs without a trace. The device is the
fake inverter (--static). Exits 0 on ALL PASS."""
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'harness'))
from harness import *   # the boot: the gate, the scratch, check(), start(), mbap()

BIN = os.path.join(REPO, 'apps', 'modbus-replay', 'bin', 'modbus-replay.py')
FAKE = os.path.join(REPO, 'apps', 'inverter', 'bin', 'modbus-fake-inverter.py')

PORT_FAKE = 15940 + BASE   # the device (the fake inverter)
PORT_CAP = 15941 + BASE    # the capture proxy
PORT_REP = 15942 + BASE    # the replay server (miss exception)
PORT_REP0 = 15943 + BASE   # the replay server (miss zero)
PORT_PASSTHRU = 15944 + BASE   # the pass-through capture (no trace)
TRACE = os.path.join(SCRATCH, 'replay-trace.jsonl')
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
print('== capture: the wire to the trace ==')

p_cap = daemon(['--listen', '127.0.0.1:%d' % PORT_CAP, '--upstream', '127.0.0.1:%d' % PORT_FAKE,
                '--log-level', 'DEBUG',
                '--capture', TRACE], LOG % 'cap')
check('the capture proxy came up (port %d)' % PORT_CAP, wait_port(PORT_CAP))

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

p_cap.send_signal(signal.SIGTERM)
p_cap.wait(timeout=10)
check('the capture daemon exited 0 on SIGTERM', p_cap.returncode == 0, str(p_cap.returncode))

print()
print('== the trace file ==')

check('the trace exists', os.path.exists(TRACE))
mode = os.stat(TRACE).st_mode & 0o777
check('the trace is 0600', mode == 0o600, '%03o' % mode)
lines = [ln for ln in open(TRACE, encoding='utf-8').read().splitlines() if ln.strip()]
recs = []
for no, ln in enumerate(lines, 1):
    try:
        recs.append(json.loads(ln))
    except ValueError:
        check('the trace line %d is JSON' % no, False, ln[:60])
header = recs[0] if recs else {}
check('the header names the format', header.get('format') == 'pv-suite-modbus-trace'
      and header.get('version') == 1, str(header))
check('the header spells the mode + upstream', header.get('mode') == 'capture'
      and str(PORT_FAKE) in str(header.get('upstream', '')), str(header))
reqs = [r_ for r_ in recs[1:] if r_.get('dir') == 'req']
rsps = [r_ for r_ in recs[1:] if r_.get('dir') == 'rsp']
check('the trace holds 4 request + 4 response records', len(reqs) == 4 and len(rsps) == 4,
      '%d req / %d rsp of %d records' % (len(reqs), len(rsps), len(recs) - 1))
check('no undecodable records (clean MBAP both ways)',
      not [r_ for r_ in recs[1:] if r_.get('dir') == 'raw'])
fc3r = [r_ for r_ in recs[1:] if r_.get('dir') == 'req' and r_.get('txn') == TXN['fc3']]
check('the request record carries the decoded fields', fc3r and fc3r[0].get('fc') == 3
      and fc3r[0].get('addr') == 32064 and fc3r[0].get('count') == 2 and fc3r[0].get('unit') == 1,
      str(fc3r[0]) if fc3r else '-')
fc4r = [r_ for r_ in rsps if r_.get('txn') == TXN['fc4']]
check('the response record carries the byte count', fc4r and fc4r[0].get('fc') == 4
      and fc4r[0].get('bytes') == 2 and 'addr' not in fc4r[0], str(fc4r[0]) if fc4r else '-')
fc6r = [r_ for r_ in rsps if r_.get('txn') == TXN['fc6']]
check('the refused write recorded its exception', fc6r and fc6r[0].get('exc') == 1
      and fc6r[0].get('fc') == 6, str(fc6r[0]) if fc6r else '-')

print()
print('== replay: the trace back on the wire ==')

p_rep = daemon(['--listen', '127.0.0.1:%d' % PORT_REP, '--replay', TRACE], LOG % 'rep')
check('the replay server came up (port %d)' % PORT_REP, wait_port(PORT_REP))

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

p_rep.send_signal(signal.SIGTERM)
p_rep.wait(timeout=10)
check('the replay daemon exited 0 on SIGTERM', p_rep.returncode == 0, str(p_rep.returncode))

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
print('== the posture ==')

for name, proc in (('cap', p_cap), ('rep', p_rep), ('rep0', p_rep0), ('pass', p_pass), ('fake', p_fake)):
    check('%s: alive at the end' % name, proc.poll() is None or proc.returncode == 0,
          str(proc.returncode))
for name in ('cap', 'rep', 'rep0', 'pass', 'fake', 'warn'):
    log = read_log(LOG % name)
    check('%s: zero tracebacks' % name, 'Traceback' not in log)
for name in ('cap', 'rep', 'rep0', 'pass'):
    check('%s: the loopback bind stayed silent' % name,
          'NOT loopback' not in read_log(LOG % name))
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
