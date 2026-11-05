#!/usr/bin/env python3
"""Client-garbage fuzz for modbus-cache.

Run from anywhere: python3 cache/test/fuzz.py [iterations]
Starts its own fake inverter + proxy on scratch ports and cleans up.
Every request must be answered; lying MBAP lengths must close the
connection. The proxy must never crash or log a traceback.
"""
import os
import random
import socket
import struct
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO, 'cache')

P = os.path.join(CACHE_DIR, 'bin', 'modbus_cache.py')
F = os.path.join(REPO, 'inverter', 'bin', 'fake_inverter.py')
INV_PORT, CACHE_PORT = 15591, 15592
ITERATIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 3000

failures = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name, (' — ' + detail) if detail else ''))
    if not cond:
        failures.append(name)


procs = []
try:
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--strict', '--port', str(INV_PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT),
                                   '--listen', '127.0.0.1:%d' % CACHE_PORT, '--interval', '1',
                                   '--allow-write', '--profile',
                                   os.path.join(REPO, 'profiles', 'profiles', 'sun2000.json')],
                                  stdout=open('/tmp/fuzz_cache.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)

    rnd = random.Random(1337)
    answered = drop = done = 0

    def conn():
        s = socket.create_connection(('127.0.0.1', CACHE_PORT), timeout=5)
        s.settimeout(5)
        return s

    def reply_ok(s):
        h = s.recv(7)
        assert len(h) == 7, 'short header'
        s.recv(min(struct.unpack('>H', h[4:6])[0] - 1, 300))
        return 1

    s = conn()
    trickle_frame = struct.pack('>HHHB', 1, 0, 3, 1) + b'\x03\x20\x40'   # 9 bytes, len-3 frame
    for i in range(ITERATIONS):
        k = rnd.random()
        try:
            if k < 0.30:                              # random garbage PDUs
                pdu = bytes([rnd.choice([0, 3, 5, 6, 15, 16, 22, 99, 170, 255])]) + \
                    bytes(rnd.randrange(256) for _ in range(rnd.randrange(0, 60)))
                s.sendall(struct.pack('>HHHB', i & 0xFFFF, 0, len(pdu) + 1, 1) + pdu)
            elif k < 0.45:                            # garbage with self-consistent lengths
                ln = rnd.choice([2, 3, 10, 40, 254, 255])
                s.sendall(struct.pack('>HHHB', i & 0xFFFF, 0, ln, 1) +
                          bytes(rnd.randrange(256) for _ in range(ln - 1)))
            elif k < 0.55:                            # lying lengths -> must be dropped
                ln = rnd.choice([0, 1, 256, 65535])
                s.sendall(struct.pack('>HHHB', i & 0xFFFF, 0, ln, 1) + b'\x00' * min(ln, 40))
                h = s.recv(7)
                assert h == b'', 'should be closed'
                s = conn()
                drop += 1
                done += 1
                continue
            elif k < 0.65:                            # wrong proto / unit ids
                pdu = struct.pack('>BHH', 3, rnd.randrange(65536), 1)
                s.sendall(struct.pack('>HHHB', i & 0xFFFF, rnd.choice([0, 1, 255]),
                                      len(pdu) + 1, rnd.choice([0, 1, 2, 248, 255])) + pdu)
            elif k < 0.75:                            # pipelined burst of 10
                s.sendall(b''.join(struct.pack('>HHHB', (i * 10 + j) & 0xFFFF, 0, 6, 1) +
                                   struct.pack('>BHH', 3, 32064, 2) for j in range(10)))
                for j in range(10):
                    h = s.recv(7)
                    assert len(h) == 7, 'short header'
                    s.recv(min(struct.unpack('>H', h[4:6])[0] - 1, 300))
                answered += 10
                done += 1
                continue
            elif k < 0.85:                            # complete frame in two tranches
                s.sendall(trickle_frame[:3])
                time.sleep(0.002)
                s.sendall(trickle_frame[3:])
            else:                                     # valid reads still work
                s.sendall(struct.pack('>HHHB', i & 0xFFFF, 0, 6, 1) +
                          struct.pack('>BHH', 3, 32064, 2))
            answered += reply_ok(s)
            done += 1
        except (OSError, AssertionError):
            drop += 1
            done += 1
            try:
                s.close()
            except OSError:
                pass
            s = conn()
    s.close()

    check('every iteration handled (%d of %d)' % (done, ITERATIONS), done == ITERATIONS)
    check('no tracebacks in the proxy log', 'Traceback' not in open('/tmp/fuzz_cache.log').read())
    check('proxy still alive after the fuzz', procs[1].poll() is None)
finally:
    for p in procs:
        p.kill()

print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
