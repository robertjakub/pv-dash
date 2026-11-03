#!/usr/bin/env python3
"""Stress: 100-register map, 100 persistent clients, 20% pass-through, 20% writes.

Run from anywhere: python3 cache/test/stress.py
Starts its own fake inverter + proxy on scratch ports and cleans up.
"""
import json
import os
import random
import resource
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO, 'cache')

P = os.path.join(CACHE_DIR, 'src', 'modbus_cache.py')
F = os.path.join(REPO, 'inverter', 'src', 'fake_inverter.py')
INV_PORT, CACHE_PORT = 15601, 15602
CLIENTS, DURATION = 100, 15.0


def raise_fds():
    resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 4096))

starts = [32000 + i * 18 for i in range(50)]              # 50 x 2 = 100 registers, gaps 16 > merge-gap 8
map_file = '/tmp/stress_profile.json'
json.dump({'registers': [{'name': 'r%d' % s, 'register': s, 'type': 'u32', 'cache': True}
                         for s in starts]}, open(map_file, 'w'))

procs = []
stop = threading.Event()
lat = {'cached': [], 'pass': [], 'write': []}
errs = []
count = {'cached': 0, 'pass': 0, 'write': 0}
lock = threading.Lock()


def check(name, cond, detail=''):
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name, (' — ' + detail) if detail else ''))
    if not cond:
        errs.append(name)


try:
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--battery', '--port', str(INV_PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=raise_fds))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT),
                                   '--listen', '127.0.0.1:%d' % CACHE_PORT, '--interval', '1',
                                   '--cache-ttl', '3', '--allow-write', '--max-clients', '0',
                                   '--client-timeout', '0', '--profile', map_file],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=raise_fds))
    for _ in range(50):                                        # wait until the listener is up
        try:
            socket.create_connection(('127.0.0.1', CACHE_PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    def txn(s, pdu):
        s.sendall(struct.pack('>HHHB', 77, 0, len(pdu) + 1, 1) + pdu)
        r = s.recv(4096)
        txn_, proto, length, unit = struct.unpack('>HHHB', r[:7])
        assert length - 1 == len(r) - 7, 'MBAP mismatch'
        return r[7:7 + length - 1]

    def client(k):
        s = socket.create_connection(('127.0.0.1', CACHE_PORT), timeout=10)
        rnd = random.Random(k)
        try:
            while not stop.is_set():
                r = rnd.random()
                try:
                    if r < 0.6:                                   # 60% cached reads
                        addr = rnd.choice(starts)
                        t0 = time.time()
                        b = txn(s, struct.pack('>BHH', 3, addr, 2))
                        lat['cached'].append(time.time() - t0)
                        assert b[0] == 3 and b[1] == 4, 'bad read'
                        with lock: count['cached'] += 1
                    elif r < 0.8:                                 # 20% pass-through reads
                        addr = 31000 + rnd.randrange(50)
                        t0 = time.time()
                        b = txn(s, struct.pack('>BHH', 3, addr, 1))
                        lat['pass'].append(time.time() - t0)
                        assert b[0] == 3 and b[1] == 2, 'bad passthrough'
                        with lock: count['pass'] += 1
                    else:                                         # 20% writes
                        t0 = time.time()
                        if rnd.random() < 0.5:
                            b = txn(s, struct.pack('>BHH', 6, 34000 + k, rnd.randrange(65536)))
                        else:
                            b = txn(s, struct.pack('>BHHB', 16, 34000 + k, 2, 4) +
                                    struct.pack('>2H', rnd.randrange(65536), rnd.randrange(65536)))
                        lat['write'].append(time.time() - t0)
                        assert b[0] in (6, 16), 'bad write echo'
                        with lock: count['write'] += 1
                except Exception as e:
                    with lock: errs.append('%d: %r' % (k, e))
                    return
                time.sleep(0.005)
        finally:
            s.close()

    ts = [threading.Thread(target=client, args=(k,)) for k in range(CLIENTS)]
    t0 = time.time()
    [t.start() for t in ts]
    time.sleep(DURATION)
    stop.set()
    [t.join() for t in ts]
    dur = time.time() - t0

    total = sum(count.values())
    print('ops: %d in %.1fs (%.0f ops/s) — cached %d, passthrough %d, writes %d'
          % (total, dur, total / dur, count['cached'], count['pass'], count['write']))
    for kind in ('cached', 'pass', 'write'):
        if lat[kind]:
            ls = sorted(lat[kind])
            p = lambda q: ls[min(len(ls) - 1, int(len(ls) * q))] * 1000
            print('  %s: p50 %.1fms  p95 %.1fms  max %.1fms' % (kind, p(0.5), p(0.95), p(1.0)))

    check('no errors under stress', not errs, '%d errors, first: %s' % (len(errs), errs[0] if errs else ''))
    check('p95 cached read < 250ms',
          not lat['cached'] or sorted(lat['cached'])[int(len(lat['cached']) * 0.95)] < 0.25)

    s = socket.create_connection(('127.0.0.1', CACHE_PORT), timeout=10)
    b = txn(s, struct.pack('>BHH', 3, 32064, 2))               # known-value pass-through still works
    check('post-stress passthrough value correct', struct.unpack('>i', b[2:6])[0] == 4000)
    s.close()
finally:
    for p in procs:
        p.kill()

print('\n%s' % ('ALL PASS' if not errs else 'FAILURES'))
sys.exit(1 if errs else 0)
