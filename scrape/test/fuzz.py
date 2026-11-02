#!/usr/bin/env python3
"""Client-garbage fuzz for the modbus-scraper HTTP endpoint.

Fires hostile client traffic (binary junk, huge request lines, wrong methods,
pipelined+nulls, partial requests, slow trickle) at a live scraper instance
and verifies it stays up, keeps serving correct metrics and never prints a
traceback. Run from anywhere: python3 scrape/test/fuzz.py
"""
import os
import random
import subprocess
import sys
import time
import urllib.request

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPE_DIR = os.path.dirname(TEST_DIR)
REPO = os.path.dirname(SCRAPE_DIR)
P = os.path.join(SCRAPE_DIR, 'src', 'scraper.py')
F = os.path.join(SCRAPE_DIR, 'src', 'fake_inverter.py')
FAKE_PORT, PORT = 15545, 19455
ROUNDS = 3000

failures = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name, (' — ' + detail) if detail else ''))
    if not cond:
        failures.append(name)


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
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(FAKE_PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    with open('/tmp/scr_fuzz.ini', 'w') as fh:
        fh.write('[scraper]\ninterval = 1\ntimeout = 1\nclient_timeout = 2\nmax_clients = 16\nlog_level = DEBUG\n')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_fuzz.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:%d' % PORT],
                                  stdout=open('/tmp/scr_fuzz.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)

    random.seed(1234)
    frames = []
    for i in range(ROUNDS):
        kind = i % 5
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
    for f in frames:
        conn(f)                                    # steady fire
        if i % 500 == 499:                          # periodic bursts of 50
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
    log = open('/tmp/scr_fuzz.log').read()
    check('no tracebacks in fuzz log', 'Traceback' not in log)
    check('client errors logged as one-liners', 'ConnectionResetError: ' in log or 'Request timed out' in log
          or 'Bad request' in log or '400' in log, 'some client-error lines expected at DEBUG')
finally:
    for p in procs:
        p.kill()

print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
