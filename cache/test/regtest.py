#!/usr/bin/env python3
"""Regression suite for modbus-cache (+ fake inverter with --strict).

Run from anywhere: python3 cache/test/regtest.py
Starts its own fake inverter + proxy on scratch ports and cleans up.
"""
import os
import socket
import struct
import subprocess
import sys
import threading
import time

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.dirname(TEST_DIR)
REPO = os.path.dirname(CACHE_DIR)
P = os.path.join(CACHE_DIR, 'src', 'modbus_cache.py')
F = os.path.join(REPO, 'scrape', 'src', 'fake_inverter.py')
R = os.path.join(CACHE_DIR, 'src', 'registers.json')

CACHE_PORT = 15505
INV_PORT = 15501

failures = []


def sync_check():
    """The module's inline default must equal cache/src/registers.json."""
    import json as _json
    r = subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', """
let
  flake = builtins.getFlake "%s";
  nixos = flake.inputs.nixpkgs.lib.nixosSystem {
    system = builtins.currentSystem;
    modules = [ flake.nixosModules.modbus-cache { services.modbus-cache.enable = true; } ];
  };
in nixos.config.services.modbus-cache.registers
""" % REPO], capture_output=True, text=True)
    if r.returncode != 0:
        check('registers.json <-> module.nix sync', False, 'nix eval failed')
        return
    default = _json.loads(r.stdout)
    shipped = _json.load(open(R))['registers']
    check('registers.json <-> module.nix sync', default == shipped,
          'keep the inline default in cache/module.nix in sync with cache/src/registers.json')


def check(name, cond, detail=''):
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name, (' — ' + detail) if detail else ''))
    if not cond:
        failures.append(name)


def txn(pdu, port=CACHE_PORT, expect_len=True):
    s = socket.create_connection(('127.0.0.1', port), timeout=10)
    s.sendall(struct.pack('>HHHB', 77, 0, len(pdu) + 1, 1) + pdu)
    r = s.recv(512)
    s.close()
    txn_, proto, length, unit = struct.unpack('>HHHB', r[:7])
    if expect_len:
        assert length - 1 == len(r) - 7, 'MBAP length %d vs %d body bytes' % (length, len(r) - 7)
    return r[7:7 + length - 1]


def rd(addr, n, port=CACHE_PORT):
    return txn(struct.pack('>BHH', 3, addr, n), port)


def wr6(addr, value):
    return txn(struct.pack('>BHH', 6, addr, value))


def wr16(addr, values):
    return txn(struct.pack('>BHHB', 16, addr, len(values), len(values) * 2) + struct.pack('>%dH' % len(values), *values))


procs = []


def start(cmd, log=None):
    if log:
        p = subprocess.Popen(cmd, stdout=open(log, 'w'), stderr=subprocess.STDOUT)
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


try:
    # 1. baseline: strict fake (undefined regs rejected with 02) + cache
    start([sys.executable, F, '--static', '--battery', '--strict', '--port', str(INV_PORT)])
    time.sleep(0.7)
    start([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT), '--listen', '127.0.0.1:%d' % CACHE_PORT,
           '--interval', '1', '--cache-ttl', '3', '--allow-write', '--registers-file', R], log='/tmp/reg_cache.log')
    time.sleep(2.5)

    # cached reads served with correct values
    b = rd(32064, 2)
    check('cached pv read', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000)
    b = rd(37001, 4)
    check('cached battery block', b[0] == 3
          and struct.unpack('>i', b[2:6])[0] == 1200
          and struct.unpack('>H', b[8:10])[0] == 650, b.hex())
    b = rd(32016, 4)
    check('cached string block', b[0] == 3 and b[1] == 8)
    b = rd(37780, 8)
    w = struct.unpack('>8H', b[2:18])
    check('cached battery energy block', b[0] == 3 and struct.unpack('>I', struct.pack('>HH', w[0], w[1]))[0] == 25000)

    # forwarded (uncached) read: forwarded, cached, then served from cache
    log_before = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache.log'],
                                capture_output=True, text=True).stdout.strip()
    b = rd(32089, 1)
    check('passthrough read ok (32089 = on-grid)', b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 512, b.hex())
    b2 = rd(32089, 1)
    log_after = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache.log'],
                               capture_output=True, text=True).stdout.strip()
    check('repeat read served from cache', b2[0] == 3 and int(log_after) == int(log_before) + 1,
          'forwards: %s -> %s' % (log_before, log_after))

    # undefined register (strict fake): client gets the device's failure
    b = rd(32100, 1)
    check('undefined register -> client gets exception 02', b[0] == 0x83 and b[1] == 2, b.hex())
    # ... and NOT cached as data (next read forwards again — grep grows)
    n1 = subprocess.run(['grep', '-c', 'polling the device', '/tmp/reg_cache.log'],
                        capture_output=True, text=True).stdout.strip()
    rd(32100, 1)
    n2 = subprocess.run(['grep', '-c', 'polling the device', '/tmp/reg_cache.log'],
                        capture_output=True, text=True).stdout.strip()
    check('failed read not cached as data', int(n2) == int(n1) + 1)

    # writes pass through (regression from earlier bug)
    b = wr6(47415, 5)
    check('fc06 echo', b == bytes.fromhex('06b9370005'), b.hex())
    b = rd(47415, 1)
    check('fc06 readback', struct.unpack('>H', b[2:4])[0] == 5)
    b = wr16(47416, [2, 6000])
    check('fc16 echo', b[0] == 16 and struct.unpack('>HH', b[1:5]) == (47416, 2), b.hex())
    b = rd(47416, 2)
    check('fc16 readback', struct.unpack('>2H', b[2:6]) == (2, 6000))

    # write support disabled by default: refused with illegal function, upstream untouched
    procs.append(subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT),
                                   '--listen', '127.0.0.1:15507', '--interval', '1',
                                   '--registers-file', R],
                                  stdout=open('/tmp/reg_cache_nowrite.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(1.5)
    s = socket.create_connection(('127.0.0.1', 15507), timeout=5)
    s.sendall(struct.pack('>HHHB', 78, 0, 6, 1) + struct.pack('>BHH', 6, 47415, 99))
    b = s.recv(64)
    s.close()
    check('write refused when disabled (exception 0x86/01)', b[7] == 0x86 and b[8] == 1, b.hex())
    b = rd(47415, 1)
    check('refused write did not reach the inverter', struct.unpack('>H', b[2:4])[0] == 5)
    check('refusal logged with detail', 'write: refused register 47415 = 99' in open('/tmp/reg_cache_nowrite.log').read())

    # lock/deadlock stress: mixed cached + passthrough + writes while polling at 10Hz
    errs = []
    maxlat = [0.0]

    def worker(k):
        for i in range(120):
            t0 = time.time()
            try:
                for addr, n in ((32064, 2), (47415, 1), (37001, 4)):
                    b = rd(addr, n)
                    assert b[0] == 3, 'func %x' % b[0]
                if i % 10 == 0:
                    wr6(47415, i)
            except Exception as e:
                errs.append('%d: %r' % (k, e))
                return
            finally:
                maxlat[0] = max(maxlat[0], time.time() - t0)

    ts = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    t0 = time.time()
    [t.start() for t in ts]
    [t.join() for t in ts]
    dur = time.time() - t0
    check('no deadlocks / no errors under stress', not errs and dur < 60,
          '%d ops in %.1fs, max per-batch %.0fms' % (8 * 120 * 4, dur, maxlat[0] * 1000))

    # 2. inverter dies: cached values until cache-ttl, then client gets 0x0B
    for p in procs:
        if 'fake_inverter' in ' '.join(p.args):
            p.kill()
    time.sleep(3.5)  # > cache-ttl 3
    b = rd(32064, 2)
    check('expired + inverter dead -> gateway exception 0x0B', b[0] == 0x83 and b[1] == 11, b.hex())

    # 3. poll status caching: registers.json variant with an undefined register
    procs[0] = subprocess.Popen([sys.executable, F, '--static', '--battery', '--strict', '--port', str(INV_PORT)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    import json as _json
    map_ = _json.load(open(R))
    map_["registers"].append({'name': 'undefined test register', 'start': 32100, 'count': 1})
    badmap = '/tmp/reg_badmap.json'
    _json.dump(map_, open(badmap, 'w'))
    c2 = subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT),
                           '--listen', '127.0.0.1:15506', '--interval', '1', '--cache-ttl', '3',
                           '--registers-file', badmap], stdout=open('/tmp/reg_cache2.log', 'w'),
                          stderr=subprocess.STDOUT)
    procs.append(c2)
    time.sleep(2.5)
    b = rd(32100, 1, port=15506)
    check('failed poll leaf -> client served the failure (02)', b[0] == 0x83 and b[1] == 2, b.hex())
    n1 = subprocess.run(['grep', '-c', 'polling the device', '/tmp/reg_cache2.log'],
                        capture_output=True, text=True).stdout.strip()
    rd(32100, 1, port=15506)
    rd(32100, 1, port=15506)
    n2 = subprocess.run(['grep', '-c', 'polling the device', '/tmp/reg_cache2.log'],
                        capture_output=True, text=True).stdout.strip()
    check('failed leaf answered from poll status, no device hammering', n1 == n2)
    b = rd(32064, 2, port=15506)
    check('healthy leaf unaffected by failed sibling', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000)
finally:
    for p in procs:
        p.kill()

sync_check()

print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
