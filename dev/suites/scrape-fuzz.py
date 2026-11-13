#!/usr/bin/env python3
"""Client-garbage fuzz for the modbus-scraper HTTP endpoint.

Fires hostile client traffic (binary junk, huge request lines, wrong methods,
pipelined+nulls, partial requests, slow trickle) at a live scraper instance
and verifies it stays up, keeps serving correct metrics and never prints a
traceback. Runs through dev/battery.py: dev/suites/scrape-fuzz.py [rounds] [quick|full]
"""
import os
import random
import subprocess
import sys
import time
import urllib.request

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'harness'))
from harness import *   # the boot: the gate, SCRATCH, BASE, the NOTE stamp — the shared check accumulator (PROFILE rebinds below: the fuzz argv leads with the rounds)

SCRAPER_DIR = os.path.join(REPO, 'apps', 'scraper')
P = os.path.join(SCRAPER_DIR, 'bin', 'modbus-scraper.py')
F = os.path.join(REPO, 'apps', 'inverter', 'bin', 'modbus-fake-inverter.py')
# the suite's spec — via the env; examples/ is never a loader default
os.environ['METRICS_SPEC'] = os.path.join(SCRAPER_DIR, 'examples', 'metrics.json')
INV_PORT, PORT = 15545 + BASE, 19455 + BASE
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 300
PROFILE = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('PV_SUITE_PROFILE', 'quick')
# quick: the basic HTTP shapes plus a small raw-junk sample; full: the whole
# hostile spread (the nightly depth — the battery full passes it)
KIND_POOL = ([3, 4, 3, 4, 0] if PROFILE == 'quick' else [0, 1, 2, 3, 4])


def get(path, timeout=5):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d%s' % (PORT, path), timeout=timeout) as r:
            return r.status, r.read().decode()
    except Exception as e:
        return getattr(e, 'code', None), ''


def conn(data):
    """One scratch connection: send, maybe half-open, close; client-side errors are fine."""
    try:
        s = socket.create_connection(('127.0.0.1', PORT), timeout=3)
        if data:
            s.sendall(data)
        s.close()
    except OSError:
        pass


import socket  # noqa: E402  (late import keeps the helpers above readable)

procs = []
try:
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--listen', '127.0.0.1:%d' % (INV_PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    with open(os.path.join(SCRATCH, 'scr_fuzz.ini'), 'w') as fh:
        fh.write('# the set grammar (the ini format is gone)\nset modbus-interval 1\nset modbus-timeout 1\n'
                  'set metrics-client-timeout 2\nset metrics-max-clients 16\nset log-level DEBUG\n')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_fuzz.ini'),
                                   '--upstream', '127.0.0.1:%d' % INV_PORT,
                                   '--listen', '127.0.0.1:%d' % PORT],
                                  stdout=open(os.path.join(SCRATCH, 'scr_fuzz.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)

    random.seed(1234)
    frames = []
    for i in range(ROUNDS):
        kind = KIND_POOL[i % len(KIND_POOL)]
        if kind == 0:
            frames.append(bytes(random.randrange(256) for _ in range(random.randrange(1, 200))))
        elif kind == 1:
            frames.append(b'GET ' + b'A' * random.randrange(100, 70000) + b' HTTP/1.1\r\n\r\n')
        elif kind == 2:
            frames.append(b'POST /metrics HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n')
        elif kind == 3:
            frames.append(b'GET /metrics HTTP/1.1\r\nHost: x\r\n\r\n' * 2 + b'\x00' * 64)
        else:
            frames.append(b'GET /metrics HTTP/1.1\r\nHost: x\r\n')
    t0 = time.time()
    for i, f in enumerate(frames, 1):
        conn(f)                                    # steady fire
        if i % 100 == 0:
            print('NOTE %d of %d frames at %s' % (i, len(frames), time.strftime('%Y-%m-%d %H:%M:%S %z')))
        if i % 500 == 0:                            # periodic bursts of 50
            for _ in range(50):
                conn(frames[random.randrange(len(frames))])
    slow = None                                     # one slow trickle client
    try:
        slow = socket.create_connection(('127.0.0.1', PORT), timeout=3)
        slow.sendall(b'GET /metrics HTTP/1.1\r\nHost: ')
        time.sleep(1)
        slow.sendall(b'x')
    except OSError:
        pass
    finally:
        if slow:
            slow.close()
    print('sent %d frames + 1 trickle in %.1fs' % (ROUNDS + 50 * (ROUNDS // 500), time.time() - t0))

    status, body = get('/metrics')
    check('scraper alive after fuzz -> 200', status == 200, str(status))
    check('metrics still correct', 'huawei_pv_generation_watts 4000' in body)
    log = open(os.path.join(SCRATCH, 'scr_fuzz.log')).read()
    check('no tracebacks in fuzz log', 'Traceback' not in log)
    check('client errors logged as one-liners', 'ConnectionResetError: ' in log or 'Request timed out' in log
          or 'Bad request' in log or '400' in log, 'some client-error lines expected at DEBUG')
except KeyboardInterrupt:
    print()
    print('INTERRUPTED')
    raise SystemExit(130)
except Exception as e:
    print('FAIL suite crashed: %s: %s' % (type(e).__name__, e))
    failures.append('suite crashed: %s: %s' % (type(e).__name__, e))
finally:
    for p in procs:
        p.kill()

print()
print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
