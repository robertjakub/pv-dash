#!/usr/bin/env python3
"""Regression suite for modbus-cache (+ fake inverter with --strict).

Run from anywhere: python3 cache/test/regtest.py
Starts its own fake inverter + proxy on scratch ports and cleans up.
"""
import hashlib
import hmac
import json as _json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

if not os.environ.get('PV_RUN_DIR'):   # the battery sets it (scripts/battery.sh)
    sys.exit('suite: run through scripts/battery.sh (the run dir + the port slot; '
             'a standalone run shares /tmp scratch and collides across sessions)')
print('NOTE started at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))

PROFILE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ('quick', 'full') \
    else os.environ.get('PV_SUITE_PROFILE', 'quick')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO, 'cache')

P = os.path.join(CACHE_DIR, 'bin', 'modbus-cache.py')
F = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
R = os.path.join(REPO, 'profiles', 'profiles', 'sun2000.json')

BASE = int(os.environ.get('SUITE_PORT_BASE', '0'))   # the concurrent-battery port space (the runner's slot)
CACHE_PORT = 15505 + BASE
PORT = 15501 + BASE

failures = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name, (' — ' + detail) if detail else ''))
    if not cond:
        failures.append(name)


def txn(pdu, port=CACHE_PORT):
    s = socket.create_connection(('127.0.0.1', port), timeout=10)
    s.sendall(struct.pack('>HHHB', 77, 0, len(pdu) + 1, 1) + pdu)
    head = b''
    while len(head) < 7:                          # TCP is a stream: read the
        chunk = s.recv(7 - len(head))             # MBAP header exactly, then
        if not chunk:
            raise ConnectionError('eof')
        head += chunk
    txn_, proto, length, unit = struct.unpack('>HHHB', head)
    body = b''
    while len(body) < length - 1:                 # ... the body exactly
        chunk = s.recv(length - 1 - len(body))
        if not chunk:
            raise ConnectionError('eof')
        body += chunk
    s.close()
    return body


def rd(addr, n, port=CACHE_PORT):
    return txn(struct.pack('>BHH', 3, addr, n), port)


def wr6(addr, value, port=CACHE_PORT):
    return txn(struct.pack('>BHH', 6, addr, value), port)


def wr16(addr, values, port=CACHE_PORT):
    return txn(struct.pack('>BHHB', 16, addr, len(values), len(values) * 2)
               + struct.pack('>%dH' % len(values), *values), port)


procs = []


def start(cmd, log=None, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    if log:
        p = subprocess.Popen(cmd, stdout=open(log, 'w'), stderr=subprocess.STDOUT, env=env)
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    procs.append(p)
    return p


def _recvn(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('eof')
        buf += chunk
    return buf


class EvilUpstream:
    """Scripted FC3 server: live-mutable reply modes for hostile-upstream tests."""

    REGS = {32064: 0, 32065: 4000}

    def __init__(self, port):
        self.mode = 'fine'  # fine | garbage | short | lying | txn | unit | stall | garbage_after
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', port))
        srv.listen(8)
        srv.settimeout(0.2)
        self.srv = srv
        self.running = True
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while self.running:
            try:
                conn, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        try:
            conn.settimeout(15)
            while True:
                tid, _pid, length = struct.unpack('>HHH', _recvn(conn, 6))
                rest = _recvn(conn, length)
                uid, fc = rest[0], rest[1]
                if fc != 3 or len(rest) < 6:
                    raise ConnectionError('unsupported request')
                start, count = struct.unpack('>HH', rest[2:6])
                payload = bytes([count * 2]) + b''.join(
                    struct.pack('>H', self.REGS.get(a, 0)) for a in range(start, start + count))
                mode = self.mode
                if mode == 'garbage':
                    conn.sendall(b'\xde\xad\xbe\xef' * 8)
                    raise ConnectionError('garbage sent')
                if mode == 'short':
                    conn.sendall(struct.pack('>HHH', tid, 0, 8) + bytes([uid, 3]))
                    raise ConnectionError('short body sent')
                if mode == 'lying':
                    conn.sendall(struct.pack('>HHH', tid, 0, 0xFFFF) + bytes([uid, 3]) + b'\x00' * 8)
                    raise ConnectionError('lying length sent')
                if mode == 'txn':
                    conn.sendall(struct.pack('>HHH', (tid + 1) & 0xFFFF, 0, 2 + len(payload))
                                 + bytes([uid, 3]) + payload)
                elif mode == 'unit':
                    conn.sendall(struct.pack('>HHH', tid, 0, 2 + len(payload))
                                 + bytes([uid + 1, 3]) + payload)
                elif mode == 'stall':
                    time.sleep(12)  # the cache's upstream timeout must fire first
                elif mode == 'garbage_after':
                    conn.sendall(struct.pack('>HHH', tid, 0, 2 + len(payload))
                                 + bytes([uid, 3]) + payload + b'\xde\xad' * 4)
                else:
                    conn.sendall(struct.pack('>HHH', tid, 0, 2 + len(payload)) + bytes([uid, 3]) + payload)
        except (ConnectionError, OSError, struct.error, IndexError):
            pass
        finally:
            conn.close()

    def stop(self):
        self.running = False
        self.srv.close()

class QuickDone(Exception):
    pass


try:
    # 1. baseline: strict fake (undefined regs rejected with 02) + cache
    start([sys.executable, F, '--control-port', '0', '--static', '--strict', '--listen', '127.0.0.1:%d' % (PORT),
           '--allow-write'])
    time.sleep(0.7)
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT, '--listen', '127.0.0.1:%d' % CACHE_PORT,
           '--interval', '1', '--cache-ttl', '3', '--allow-write', '--profile', R,
           '--write-acl', 'any', '--write-registers', 'any',
           '--audit-log', '/tmp/reg_audit.log'], log='/tmp/reg_cache.log')
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

    # forwarded (uncached) read: a mini profile (only pv+grid marked) proves
    # the marks: 32089 is not in it -> forwarded once, cached, then served
    mini = '/tmp/reg_mini_profile.json'
    _json.dump({'description': 'mini device (marks test)',
                'registers': [
                    {'name': 'pv-power', 'register': 32064, 'type': 'i32', 'scale': 1, 'cache': True},
                    {'name': 'grid-power', 'register': 37113, 'type': 'i32', 'scale': 1, 'cache': True},
                ]}, open(mini, 'w'))
    c3 = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                           '--listen', '127.0.0.1:%d' % (15517 + BASE), '--interval', '1', '--cache-ttl', '3',
                           '--profile', mini], stdout=open('/tmp/reg_mini.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(c3)
    time.sleep(1.5)
    b = rd(32089, 1, port=15517 + BASE)
    check('profile marks: unmarked register forwarded (32089 = on-grid)',
          b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 512, b.hex())
    b2 = rd(32089, 1, port=15517 + BASE)
    forwards = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_mini.log'],
                              capture_output=True, text=True).stdout.strip()
    check('profile marks: repeat read served from cache', b2[0] == 3
          and struct.unpack('>H', b2[2:4])[0] == 512 and forwards == '1',
          'forwards: %s' % forwards)

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
    audit_txt = open('/tmp/reg_audit.log').read()
    check('audit: START + forwarded writes land in the trail',
          'tools=CACHE tag=daemon type=start' in audit_txt and 'tools=CACHE tag=daemon type=write' in audit_txt
          and 'register 47415 = 5' in audit_txt, audit_txt[-200:])

    # write-through invalidation: the written range serves the NEW value immediately
    b = rd(47415, 1)
    old = struct.unpack('>H', b[2:4])[0]
    wr6(47415, 99)
    b = rd(47415, 1)
    check('write-through invalidation: the read right after a write is not stale',
          struct.unpack('>H', b[2:4])[0] == 99 and old != 99, 'old=%d resp=%s' % (old, b.hex()))
    wr6(47415, 5)
    b = rd(47415, 1)
    check('write-through: the device value is served again after the restore',
          struct.unpack('>H', b[2:4])[0] == 5, b.hex())

    # write support disabled by default: refused with illegal function, upstream untouched
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (15507 + BASE), '--interval', '1',
                                   '--profile', R],
                                  stdout=open('/tmp/reg_cache_nowrite.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(1.5)
    s = socket.create_connection(('127.0.0.1', 15507 + BASE), timeout=5)
    s.sendall(struct.pack('>HHHB', 78, 0, 6, 1) + struct.pack('>BHH', 6, 47415, 99))
    b = s.recv(64)
    s.close()
    check('write refused when disabled (exception 0x86/01)', b[7] == 0x86 and b[8] == 1, b.hex())
    b = rd(47415, 1)
    check('refused write did not reach the inverter', struct.unpack('>H', b[2:4])[0] == 5)
    check('refusal logged with detail', 'write: refused register 47415 = 99' in open('/tmp/reg_cache_nowrite.log').read())

    # 1c. diagnostics registers: synthesized by the cache from poller state (never forwarded)
    b = rd(65000, 4)
    w = struct.unpack('>4H', b[2:10]) if b[0] == 3 else ()
    check('diag block: magic, device up, fresh age', b[0] == 3 and w[:2] == (0xCAFE, 1) and w[2] <= 2, str(w))
    b = rd(65002, 2)
    check('diag sub-range read (age, uptime)', b[0] == 3 and b[1] == 4
          and struct.unpack('>H', b[2:4])[0] <= 2 and struct.unpack('>H', b[4:6])[0] < 300, b.hex())
    b = rd(64999, 2)
    check('diag straddle read -> exception 02', b[0] == 0x83 and b[1] == 2, b.hex())
    b = rd(65004, 1)
    check('past diag block -> forwarded to the device (02)', b[0] == 0x83 and b[1] == 2, b.hex())

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
        if 'modbus-fake-inverter' in ' '.join(p.args):
            p.kill()
    time.sleep(3.5)  # > cache-ttl 3
    b = rd(32064, 2)
    check('expired + inverter dead -> gateway exception 0x0B', b[0] == 0x83 and b[1] == 11, b.hex())
    b = rd(65000, 4)
    w = struct.unpack('>4H', b[2:10]) if b[0] == 3 else ()
    check('device dead: diag still served, flags down, age grows',
          b[0] == 3 and w[:2] == (0xCAFE, 0) and w[2] >= 3, str(w))

    # 3. poll status caching: profile variant with a register the device rejects
    procs[0] = subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--strict', '--listen', '127.0.0.1:%d' % (PORT),
                                 '--allow-write'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    import json as _json
    map_ = _json.load(open(R))
    map_["registers"].append({'name': 'undefined test register', 'register': 32100, 'type': 'u16', 'cache': True})
    badmap = '/tmp/reg_badmap.json'
    _json.dump(map_, open(badmap, 'w'))
    c2 = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                           '--listen', '127.0.0.1:%d' % (15506 + BASE), '--interval', '1', '--cache-ttl', '3',
                           '--profile', badmap], stdout=open('/tmp/reg_cache2.log', 'w'),
                          stderr=subprocess.STDOUT)
    procs.append(c2)
    time.sleep(2.5)
    b = rd(32100, 1, port=15506 + BASE)
    check('failed poll leaf -> client served the failure (02)', b[0] == 0x83 and b[1] == 2, b.hex())
    n1 = subprocess.run(['grep', '-c', 'polling the device', '/tmp/reg_cache2.log'],
                        capture_output=True, text=True).stdout.strip()
    rd(32100, 1, port=15506 + BASE)
    rd(32100, 1, port=15506 + BASE)
    n2 = subprocess.run(['grep', '-c', 'polling the device', '/tmp/reg_cache2.log'],
                        capture_output=True, text=True).stdout.strip()
    check('failed leaf answered from poll status, no device hammering', n1 == n2)
    b = rd(32064, 2, port=15506 + BASE)
    check('healthy leaf unaffected by failed sibling', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000)

    # 4. hostile upstream: every garbage reply mode must fail clean (0x0B, one-line log) and recover
    evil = EvilUpstream(15509 + BASE)
    evil.mode = 'garbage'  # cold from the start: no fine-mode poll can fill the cache
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15509 + BASE),
           '--listen', '127.0.0.1:%d' % (15508 + BASE), '--interval', '1', '--cache-ttl', '3',
           '--profile', R], log='/tmp/reg_evil.log')
    time.sleep(2)
    for mode in ('garbage', 'short', 'lying', 'txn', 'unit', 'stall'):
        evil.mode = mode
        time.sleep(1.2)
        b = rd(32064, 2, port=15508 + BASE)
        check('evil upstream %s -> client gets 0x0B' % mode, b[0] == 0x83 and b[1] == 11, b.hex())
    evil.mode = 'garbage_after'  # valid reply + trailing junk: the read itself may succeed
    time.sleep(1.2)
    b = rd(32064, 2, port=15508 + BASE)
    check('evil upstream garbage_after: handled without a crash',
          (b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000) or (b[0] == 0x83 and b[1] == 11), b.hex())
    b = rd(65000, 4, port=15508 + BASE)
    w = struct.unpack('>4H', b[2:10]) if b[0] == 3 else ()
    check('diag unaffected by hostile upstream', b[0] == 3 and w[0] == 0xCAFE, str(w))
    evil.mode = 'fine'
    time.sleep(2.5)
    b = rd(32064, 2, port=15508 + BASE)
    check('evil upstream: recovers when replies turn sane',
          b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    evil_log = open('/tmp/reg_evil.log').read()
    check('evil upstream: zero tracebacks, failures are one-liners',
          'Traceback' not in evil_log and 'poll of' in evil_log)
    evil.stop()

    # 5. control server: show config/connections/cache, request flush cache,
    #    request restart,
    #    cache_cli, shutdown (+ the default unix socket / CTL)
    K = os.path.join(CACHE_DIR, 'bin', 'modbus-cache-cli.py')

    def ctl_cmd(cmd, port):
        """One JSON-lines control exchange (the token handshake first — every
        regtest TCP control speaks 'sekrit'): sign the command, verify the
        reply's mac, return 'status text'."""

        def wiremac(payload):
            return hmac.new(b'sekrit', payload.encode(), hashlib.sha256).hexdigest()

        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit'}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        auth = _json.loads(buf.decode())
        assert auth.get('status') == 'ok', auth
        s.sendall(_json.dumps({'cmd': cmd, 'mac': wiremac(cmd)}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            b2 = s.recv(4096)
            if not b2:
                break
            buf += b2
        s.close()
        obj = _json.loads(buf.split(b'\n', 1)[0].decode())   # one reply line — the reload's bye frame may race into the buffer
        assert obj.get('mac') == wiremac('%s %s' % (obj.get('status'), obj.get('text', ''))), \
            'the reply mac does not verify: %r' % obj
        return '%s %s' % (obj.get('status'), obj.get('text', ''))

    start([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15512 + BASE), '--control-port', '0', '--allow-write'])
    # the shipped example selection: the essential set, by name
    SEL = os.path.join(CACHE_DIR, 'examples', 'selection.json')
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
           '--listen', '127.0.0.1:%d' % (15518 + BASE), '--interval', '1', '--profile', R,
           '--selection', SEL], log='/tmp/reg_sel.log')
    time.sleep(1.5)
    plan = open('/tmp/reg_sel.log').read()
    b = rd(32064, 2, port=15518 + BASE)
    check('selection: the essential set polls pv-power', b[0] == 3
          and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    check('selection: 22 selected ranges, the plan logs pools',
          'caching 22 range(s)' in plan and 'poll plan: ' in plan and 'pool 1:' in plan)
    b = rd(32089, 1, port=15518 + BASE)
    check('selection: an unselected register forwards (device-status 512)',
          b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 512, b.hex())

    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
           '--listen', '127.0.0.1:%d' % (15513 + BASE), '--interval', '1', '--profile', R,
           '--write-acl', 'any', '--write-registers', 'any',
           '--control-port', '%d' % (15514 + BASE)], log='/tmp/reg_ctl.log',
          env_extra={'CONTROL_TOKEN': 'sekrit'})
    time.sleep(2)
    r = ctl_cmd('show upstream', 15514 + BASE)
    check('control: the per-setting show (upstream)', r == 'ok upstream=127.0.0.1:%d' % (15512 + BASE), r)
    r = ctl_cmd('inspect', 15514 + BASE)
    check('control: inspect carries the state', 'upstream  127.0.0.1:%d' % (15512 + BASE) in r
          and 'listen    127.0.0.1:%d' % (15513 + BASE) in r and 'hits 0' in r, r[:400])
    c1 = socket.create_connection(('127.0.0.1', 15513 + BASE), timeout=5)
    pdu = struct.pack('>BHH', 3, 32064, 2)
    c1.sendall(struct.pack('>HHHB', 78, 0, len(pdu) + 1, 1) + pdu)
    c1.recv(512)
    r = ctl_cmd('show connections', 15514 + BASE)
    check('control: show connections lists peer + requests', 'connected' in r and 'requests 1' in r
          and r.startswith('ok connections 127.0.0.1:'), r)
    r = ctl_cmd('show cache', 15514 + BASE)
    check('control: show cache counters', 'hits 1' in r and 'range(s)' in r and 'map v0' in r, r)
    r = ctl_cmd('request flush cache', 15514 + BASE)
    check('control: clear cache', r.startswith('ok cache cleared (') and 'repolling now' in r, r)
    b = rd(32064, 2, port=15513 + BASE)
    check('control: cache refills after clear', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    r = ctl_cmd('request restart', 15514 + BASE)
    check('control: restart drops the upstream session', r.startswith('ok upstream session restarted'), r)
    b = rd(32064, 2, port=15513 + BASE)
    check('control: upstream reconnects after restart', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    r = ctl_cmd('request reload-config', 15514 + BASE)
    check('control: request reload-config re-reads the config (the SIGHUP path)',
          r.startswith('ok reloaded (') and 'range(s) from' in r, r[:120])
    r = ctl_cmd('bogus', 15514 + BASE)
    check('control: unknown command', r.startswith('fail unknown command'), r)
    r = ctl_cmd('ping', 15514 + BASE)
    check('control: ping answers pong', r == 'ok pong', r)
    c1.close()

    # 5b. JSON framing + token auth: malformed frames are answered cleanly,
    #     TCP control needs the token, the unix socket does not
    def ctl_raw(wire_bytes, port, reads=1, token=None):
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        if token:
            s.sendall(_json.dumps({'cmd': 'auth', 'token': token}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            buf = b''
        s.sendall(wire_bytes)
        buf = b''
        for _ in range(reads):
            while not buf.endswith(b'\n'):
                b2 = s.recv(4096)
                if not b2:
                    break
                buf += b2
        s.close()
        return _json.loads(buf.decode())

    r = ctl_raw(b'not json at all\n', 15514, token='sekrit')
    check('control: malformed frame rejected cleanly', r.get('status') == 'fail'
          and 'malformed request' in r.get('text', ''), str(r))

    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
           '--listen', '127.0.0.1:%d' % (15519 + BASE), '--interval', '1', '--profile', R,
           '--control-port', '%d' % (15520 + BASE), '--control-token', 'sekrit',
           '--audit-log', '/tmp/reg_audit_ctl.log'], log='/tmp/reg_ctl_tok.log')
    time.sleep(1.5)
    r = ctl_raw(b'{"cmd": "show version"}\n', 15520)
    check('control: token server rejects the unauthenticated', r.get('status') == 'fail'
          and 'authenticate first' in r.get('text', ''), str(r))
    ok = True
    for i in range(3):
        r = ctl_raw(_json.dumps({'cmd': 'auth', 'token': 'guess-%d' % i}).encode() + b'\n', 15520)
        ok = ok and r.get('status') == 'fail' and 'bad token' in r.get('text', '')
    check('control: wrong tokens rejected', ok)
    s = socket.create_connection(('127.0.0.1', 15520 + BASE), timeout=5)
    s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit'}).encode() + b'\n')
    buf = b''
    while not buf.endswith(b'\n'):
        buf += s.recv(4096)
    auth = _json.loads(buf.decode())
    signed_cmd = _json.dumps({'cmd': 'show version',
                              'mac': hmac.new(b'sekrit', b'show version', hashlib.sha256).hexdigest()})
    s.sendall(signed_cmd.encode() + b'\n')
    buf = b''
    while not buf.endswith(b'\n'):
        buf += s.recv(4096)
    st = _json.loads(buf.decode())
    s.close()
    check('control: the right token authenticates, signed commands work after it',
          auth.get('status') == 'ok' and st.get('status') == 'ok'
          and st.get('text', '').startswith('modbus-cache'), '%s %s' % (auth, st))
    r = ctl_raw(b'{"cmd": "show version"}\n', 15520, token='sekrit')
    check('control: an unsigned command over TCP is refused (the signed wire)',
          r.get('status') == 'fail' and 'unsigned command' in r.get('text', ''), str(r))
    r = ctl_raw(_json.dumps({'cmd': 'show version', 'mac': 'ab' * 32}).encode() + b'\n', 15520, token='sekrit')
    check('control: a bad command mac is refused',
          r.get('status') == 'fail' and 'mac does not verify' in r.get('text', ''), str(r))
    tok_audit = open('/tmp/reg_audit_ctl.log').read()
    check('audit: AUTH-FAIL + COMMAND events with the peer and the wire mac',
          'type=auth-fail' in tok_audit and 'tools=CACHE tag=daemon type=command' in tok_audit
          and 'peer=127.0.0.1:' in tok_audit and "'show version' wire=h" in tok_audit
          and 'result=ok' in tok_audit, tok_audit[-240:])

    # show config: the secret knobs render as the placeholder — the knob is
    # public, the value never is
    r = ctl_cmd('show config', 15520 + BASE)
    check('show config: the secret knob renders as *** SECRET REMOVED ***',
          'set control token *** SECRET REMOVED ***' in r and 'sekrit' not in r, r[:160])

    # the pre-auth line buffer is capped: a newline-less stream is dropped, not buffered
    s = socket.create_connection(('127.0.0.1', 15520 + BASE), timeout=10)
    try:
        s.sendall(b'x' * (1024 * 1024 + 65536))   # > CLI_MAX_LINE_BYTES_S, no newline: the server drops us
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            dropped = not s.recv(4096)            # the orderly drop: EOF
        except ConnectionResetError:
            dropped = True                        # the RST flavor: the server closed mid-stream
        check('control: the uncapped pre-auth buffer is capped (connection dropped)', dropped)
    finally:
        s.close()

    def cli(stdin, port=15514 + BASE, env_extra=None, use_flag=True):
        env = {**os.environ, 'CONTROL_TOKEN': 'sekrit'}
        if env_extra:
            env.update(env_extra)
        args = [sys.executable, K]
        if use_flag:
            args += ['--control-port', str(port)]
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=30, env=env)

    r = cli('show modbus upstream\nquit\n')
    check('cache_cli: the per-setting show prints the bare value', r.returncode == 0
          and '\ncache:%d > 127.0.0.1:%d' % (15514 + BASE, 15512 + BASE) in r.stdout, repr(r.stdout[-160:]))
    r = cli('request flush cache\nquit\n')
    check('cache_cli: request flush cache confirms silently', r.returncode == 0
          and '\ncache:%d > \ncache:%d > ' % (15514 + BASE, 15514 + BASE) in r.stdout, repr(r.stdout[-120:]))
    r = cli('show control-token ?\nshow control ops ?\nset connections ?\nrequest?\nquit\n')
    check("cache_cli: ? at a hidden leaf describes it (the wire's help answer)",
          'control-token - require a token on control connections' in r.stdout, repr(r.stdout[-300:]))
    check("cache_cli: ? at the ops namespace lists its non-secret child (the verbs row rides the walk)",
          'verbs the read-only ops role' in r.stdout, repr(r.stdout[-300:]))
    check("cache_cli: ? at a show-only namespace stays Invalid input (the reports never join the set space)",
          r.stdout.count('% Invalid input.') == 1, repr(r.stdout[-300:]))
    check('cache_cli: the command tree describes by its registry row (the walk-on borrows the node descr)',
          'request the state machinery: the dump written and restored' in r.stdout, repr(r.stdout[-300:]))
    r = cli('shutdown\nn\n')
    check('cache_cli: shutdown refuses without confirming', r.returncode == 0
          and 'Proceed with shutdown? [confirm]' in r.stdout and '% Aborted.' in r.stdout, repr(r.stdout))
    p = subprocess.Popen([sys.executable, K, '--control-port', '%d' % (15514 + BASE)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True,
                         env={**os.environ, 'CLI_KEEPALIVE': '0.2', 'CONTROL_TOKEN': 'sekrit'})
    time.sleep(1.2)          # the CLI idles, pinging every 0.2s
    p.stdin.write('show modbus upstream\n')
    p.stdin.flush()
    time.sleep(0.4)
    p.stdin.write('quit\n')
    p.stdin.flush()
    out, _ = p.communicate(timeout=15)
    check('cache_cli: keepalive keeps an idle session alive (pongs absorbed)',
          p.returncode == 0 and '127.0.0.1:%d' % (15512 + BASE) in out
          and 'ok pong' not in out, repr(out[-120:]))
    r = cli('quit\n', 15514 + BASE, {'CLI_KEEPALIVE': 'soon'})
    check('cache_cli: a non-float CLI_KEEPALIVE is the one-line refusal at startup, not a traceback',
          r.returncode == 1 and 'invalid CLI_KEEPALIVE' in r.stderr and 'Traceback' not in r.stderr
          and r.stdout == '',
          repr((r.returncode, r.stderr[-160:])))
    p_unix = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                               '--listen', '127.0.0.1:%d' % (15515 + BASE), '--interval', '1', '--profile', R],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p_unix)
    time.sleep(1.5)
    check('control: default unix socket for the listen port', os.path.exists('/tmp/modbus-cache-%d.socket' % (15515 + BASE)))
    check('control: the unix socket mode is 0600 (not the umask)',
          os.stat('/tmp/modbus-cache-%d.socket' % (15515 + BASE)).st_mode & 0o777 == 0o600,
          oct(os.stat('/tmp/modbus-cache-%d.socket' % (15515 + BASE)).st_mode))
    r = cli('show modbus upstream\nquit\n', 15515 + BASE, {'CTL': '/tmp/modbus-cache-%d.socket' % (15515 + BASE)}, use_flag=False)
    check('cache_cli: CTL reaches the default socket', r.returncode == 0
          and '127.0.0.1:%d' % (15512 + BASE) in r.stdout and 'cache:15515 > ' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show modbus upstream\nquit\n', 15515 + BASE, {'CTL': '/tmp/modbus-cache-%d.socket' % (15515 + BASE)}, use_flag=False)
    check('cache_cli: short CTL env works too', r.returncode == 0
          and '127.0.0.1:%d' % (15512 + BASE) in r.stdout, repr(r.stdout[-120:]))
    r = cli('show modbus upstream\nquit\n', 15520 + BASE, {'CONTROL_TOKEN': 'sekrit'})
    check('cache_cli: token env authenticates the TCP control session', r.returncode == 0
          and '127.0.0.1:%d' % (15512 + BASE) in r.stdout, repr(r.stdout[-120:]))
    r = cli('show version\nquit\n', 15520 + BASE, {'CONTROL_TOKEN': ''})
    check('cache_cli: token server refuses the token-less CLI', r.returncode == 0
          and '% error: authenticate first' in r.stdout, repr(r.stdout[-160:]))

    # the group-accessible unix socket (--control-socket-group): 0660
    p_unix_g = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                 '--listen', '127.0.0.1:%d' % (15516 + BASE), '--interval', '1', '--profile', R,
                                 '--control-socket-group'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p_unix_g)
    time.sleep(1.5)
    gsock = '/tmp/modbus-cache-%d.socket' % (15516 + BASE)
    check('control: --control-socket-group chmods the socket 0660',
          os.stat(gsock).st_mode & 0o777 == 0o660, oct(os.stat(gsock).st_mode))
    r = cli('show version\nquit\n', 15516 + BASE, {'CTL': gsock}, use_flag=False)
    check('control: the group socket speaks (the owner, us)', r.returncode == 0
          and 'modbus-cache 0.4.2' in r.stdout, repr(r.stdout[-120:]))

    # 5c. cache_ctl: the one-shot client (args, piped batches, token)
    ctl = os.path.join(CACHE_DIR, 'bin', 'modbus-cache-ctl.py')
    r = subprocess.run([sys.executable, ctl, '--control-port', '%d' % (15514 + BASE), 'show', 'upstream'],
                       capture_output=True, text=True, timeout=30,
                       env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    check('cache_ctl: one-shot per-setting show', r.returncode == 0
          and r.stdout.startswith('ok upstream=127.0.0.1:%d' % (15512 + BASE)), repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '%d' % (15520 + BASE)],
                       input='show cache\nrequest flush cache\n', capture_output=True, text=True,
                       timeout=30, env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    check('cache_ctl: piped batch with the token env', r.returncode == 0
          and r.stdout.startswith('ok cache ') and 'ok cache cleared' in r.stdout, repr(r.stdout[:160]))

    # 5d. set/clear/show: the live settings registry (the inverter's pattern)
    r = ctl_cmd('set interval 2', 15514 + BASE)
    check('set: interval applied with the state summary', r.startswith('ok interval=2.00s upstream=127.0.0.1:%d' % (15512 + BASE))
          and 'poll=' in r and 'hits=' in r, r[:120])
    r = ctl_cmd('show interval', 15514 + BASE)
    check('set: the per-setting show reflects the new interval', r == 'ok interval=2.00s', r[:120])
    r = ctl_cmd('set interval bogus', 15514 + BASE)
    check('set: a bogus value is a clean err', r.startswith('fail interval must be seconds'), r[:100])
    r = ctl_cmd('set bogus 1', 15514 + BASE)
    check('set: unknown setting', r.startswith('fail unknown setting'), r[:100])
    r = ctl_cmd('show settings', 15514 + BASE)
    check('show settings: retired answers the fail verdict', r.startswith('fail'), r[:80])
    r = ctl_cmd('show interval', 15514 + BASE)
    check('show <setting>: the bare value', r == 'ok interval=2.00s', r)
    r = ctl_cmd('show cache-ttl', 15514 + BASE)
    check('show <setting>: the path spelling answers the live', r == 'ok cache-ttl=30.00s', r)
    r = ctl_cmd('help cache-ttl', 15514 + BASE)
    check('help <setting>: the registry description', r.startswith('ok cache-ttl - per-register cache TTL'), r[:110])
    r = ctl_cmd('help clear', 15514 + BASE)
    check('help <command>: the row describes itself',
          r == 'ok restore a setting to its configured value: clear <setting>', r)
    r = ctl_cmd('help request', 15514 + BASE)
    check('help <command node>: the namespace lists its children (the ? shape)',
          r == 'ok     flush         drop the cached registers and repoll now\n'
               '    reload        save the live overrides and restart the whole daemon (the restart-marked knobs take their configured values)\n'
               '    reload-config re-read the config file (the SIGHUP path)', r)
    r = ctl_cmd('help request reload', 15514 + BASE)
    check('help <deep command path>: the row describes itself',
          r == 'ok save the live overrides and restart the whole daemon (the restart-marked knobs take their configured values)', r)
    r = ctl_cmd('help request reload-config', 15514 + BASE)
    check('help <the re-read deep path>: the row describes itself',
          r == 'ok re-read the config file (the SIGHUP path)', r)
    r = ctl_cmd('help bogus', 15514 + BASE)
    check('help <unknown topic>: the reworded two-space error',
          r == 'fail unknown command or setting bogus (try ?)', r)
    r = ctl_cmd('clear interval', 15514 + BASE)
    check('clear: restores the configured value', r.startswith('ok interval=1.00s'), r[:110])
    r = ctl_cmd('set timeout 5', 15514 + BASE)
    check('set: modbus timeout applied (the rekeyed branch)', r.startswith('ok timeout=5.00s upstream='), r[:120])
    r = ctl_cmd('show timeout', 15514 + BASE)
    check('show: modbus timeout answers the bare value', r == 'ok timeout=5.00s', r)
    r = ctl_cmd('set timeout 99', 15514 + BASE)
    check('set: modbus timeout range-gated', r.startswith('fail timeout must be 0 < N <= 60'), r[:100])
    r = ctl_cmd('clear timeout', 15514 + BASE)
    check('clear: modbus timeout restores the configured value', r.startswith('ok timeout=3.00s'), r[:110])
    r = ctl_cmd('set config 5', 15514 + BASE)
    check('set: a show report is not a setting', r.startswith('fail unknown setting config'), r[:100])
    r = ctl_cmd('set connections 5', 15514 + BASE)
    check('set: connections is not a setting', r.startswith('fail unknown setting connections'), r[:100])
    r = ctl_cmd('set local-time on', 15514 + BASE)
    check('set: local-time toggles live', r.startswith('ok local-time=on'), r[:110])
    r = ctl_cmd('show local-time', 15514 + BASE)
    check('show: local-time answers the bare value', r == 'ok local-time=on', r)
    r = ctl_cmd('set local-time bogus', 15514 + BASE)
    check('set: local-time validates on|off', r.startswith('fail local-time must be on|off'), r[:100])
    r = ctl_cmd('clear local-time', 15514 + BASE)
    check('clear: local-time restores the configured value', r.startswith('ok local-time=off'), r[:110])
    r = ctl_cmd('show cache-all', 15514 + BASE)
    check('show cache-all: per-entry rows with age, expiry and status', r.startswith('ok cache-all\n')
          and 'pv-power' in r and 'expires' in r and 'fc3' in r and '2/2' in r, r[:200])
    rows = r.splitlines()
    check('show cache-all: the values column carries the cached words',
          'values' in rows[1] and any(len(row.split()) > 3 and row.split()[3].isdigit()
                                      for row in rows[2:]), r[:200])
    r = ctl_cmd('show cache', 15514 + BASE)
    check('show cache: the summary still works beside the dump', r.startswith('ok cache '), r[:80])
    r = ctl_cmd('request dump', 15514 + BASE)
    check('request dump: no dump path configured is a clean err', r.startswith('fail no dump path configured'), r[:80])
    r = ctl_cmd('show dump-interval', 15514 + BASE)
    check('dump: show dump-interval without a path is a clean err', r.startswith('fail dump-interval needs a dump path'), r[:80])
    r = ctl_cmd('help', 15514 + BASE)
    check('dump: the help hides the dump commands without a path', 'request dump' not in r, r[:160])
    r = ctl_cmd('show knobs', 15514 + BASE)
    check('show knobs: the dictionary of the registry — flag, env twin, how it changes',
          r.startswith('ok knobs') and '--interval' in r and '$INTERVAL' in r
          and 'set modbus interval <value>' in r and '--control-ops-token' in r and ', secret' in r
          and 'set modbus upstream <value>, restart' in r, r[:200])   # the restart-marked knob carries the suffix
    r = ctl_cmd('help knobs', 15514 + BASE)
    check('help knobs: the same dictionary under the help verb', r.startswith('ok knobs'), r[:80])
    r = ctl_cmd('show uplink', 15514 + BASE)
    check('show uplink: session counters and per-block latency rows', r.startswith('ok uplink\n')
          and 'exchanges' in r and 'connects' in r and 'mean' in r and 'fails' in r
          and 'fc3' in r and 'status' in r, r[:200])

    # selection none: the map empties, every read forwards, nothing is stored
    r = ctl_cmd('set selection none', 15514 + BASE)
    check('set selection none: accepted', r.startswith('ok selection=none'), r[:100])
    r = ctl_cmd('show cache', 15514 + BASE)
    check('set selection none: the map empties', '0 range(s)' in r
          and ctl_cmd('show selection', 15514 + BASE) == 'ok selection=none', r[:160])
    m1 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache.log'],
                        capture_output=True, text=True).stdout.strip()
    rd(47415, 1)
    rd(47415, 1)
    m2 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache.log'],
                        capture_output=True, text=True).stdout.strip()
    check('selection none: repeat reads forward, nothing is stored', int(m2) == int(m1) + 2,
          '%s -> %s' % (m1, m2))
    ctl_cmd('clear selection', 15514 + BASE)
    r = ctl_cmd('show cache', 15514 + BASE)
    check('clear selection: the map refills', '49 range(s)' in r
          and ctl_cmd('show selection', 15514 + BASE) == 'ok selection=all', r[:160])

    # --selection none at startup: the same, straight from the command line
    p_none = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                               '--listen', '127.0.0.1:%d' % (15526 + BASE), '--interval', '1', '--profile', R,
                               '--selection', 'none', '--control-port', '%d' % (15527 + BASE)],
                              stdout=open('/tmp/reg_cache_none.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_none)
    time.sleep(1.5)
    b = rd(47415, 1, port=15526 + BASE)
    check('selection none at startup: the read forwards', b[0] == 3, b.hex())
    r = ctl_cmd('show cache', 15527 + BASE)
    check('selection none at startup: 0 range(s), nothing cached',
          '0 range(s)' in r and ctl_cmd('show selection', 15527 + BASE) == 'ok selection=none', r[:160])
    ctl_cmd('shutdown', 15527 + BASE)

    # the poll-cycle durations ride in inspect
    r = ctl_cmd('inspect', 15514 + BASE)
    check('inspect: the poll-cycle durations', 'poll cyc  last ' in r and 'mean ' in r, r[:300])

    # per-entry ttl: the profile entry expires early, the global-ttl one stays
    ttlmap = '/tmp/reg_ttl_profile.json'
    _json.dump({'description': 'per-entry ttl',
                'registers': [
                    {'name': 'pv-power', 'register': 32064, 'type': 'i32', 'ttl': 2},
                    {'name': 'device-status', 'register': 32089, 'type': 'u16'},
                ]}, open(ttlmap, 'w'))
    p_ttl = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                              '--listen', '127.0.0.1:%d' % (15533 + BASE), '--interval', '5', '--cache-ttl', '30',
                              '--profile', ttlmap, '--control-port', '%d' % (15534 + BASE)],
                             stdout=open('/tmp/reg_cache_ttl.log', 'w'), stderr=subprocess.STDOUT,
                             env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_ttl)
    time.sleep(1.5)
    rd(32064, 2, port=15533 + BASE)
    rd(32089, 1, port=15533 + BASE)
    f1 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache_ttl.log'],
                        capture_output=True, text=True).stdout.strip()
    time.sleep(2.0)          # pv-power (ttl 2s) expires mid-cycle; device-status (global 30s) stays
    rd(32064, 2, port=15533 + BASE)
    rd(32089, 1, port=15533 + BASE)
    f2 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache_ttl.log'],
                        capture_output=True, text=True).stdout.strip()
    check('per-entry ttl: the fast entry re-forwards, the global one stays cached',
          int(f2) == int(f1) + 1, '%s -> %s' % (f1, f2))
    r = ctl_cmd('show cache-all', 15534 + BASE)
    check('show cache-all: the entry ttl is marked', 'pv-power' in r and '[ttl 2.00s]' in r, r[:200])
    p_ttl.send_signal(signal.SIGTERM)
    p_ttl.wait(timeout=10)

    # the peer-cred auth on the unix control socket: a token gates both transports,
    # but the kernel-vouched peers (root, the daemon's own user) skip the handshake
    cred_sock = '/tmp/reg_cred.socket'
    p_cred = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                               '--listen', '127.0.0.1:%d' % (15538 + BASE), '--interval', '1', '--profile', R,
                               '--control-port', cred_sock, '--control-token', 'sekrit'],
                              stdout=open('/tmp/reg_cache_cred.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(p_cred)
    time.sleep(1.5)
    r = subprocess.run([sys.executable, ctl, '--control-port', cred_sock, 'show', 'version'],
                       capture_output=True, text=True, timeout=30)
    check('peer-cred: the same-uid unix peer needs no token', r.returncode == 0
          and r.stdout.startswith('ok modbus-cache'), repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, ctl, '--control-port', cred_sock, 'shutdown'],
                       capture_output=True, text=True, timeout=30)
    check('peer-cred: the trusted unix peer can also stop the proxy', r.stdout.startswith('bye'),
          repr(r.stdout[:120]))
    p_cred.wait(timeout=10)

    # the state dump (write-behind): the cached words + the live setting overrides
    dumpfile = '/tmp/reg_dump.json'
    p_dump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                               '--listen', '127.0.0.1:%d' % (15536 + BASE), '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '%d' % (15537 + BASE),
                               '--dump-path', dumpfile],
                              stdout=open('/tmp/reg_cache_dump.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_dump)
    time.sleep(1.5)
    r = ctl_cmd('request dump', 15537 + BASE)
    check('request dump: settings-only by default (F18 round)', r.startswith('ok dumped 0 word(s)')
          and 'setting(s)' in r, r[:120])
    d = _json.load(open(dumpfile))
    check('request dump: the format is the versioned modbus-cache-dump, empty registers',
          d.get('format') == 'modbus-cache-dump' and d.get('version') == 1
          and d.get('registers') == [] and d.get('settings') == {}, str(d.get('saved')))
    check('request dump: the file is 0600 (F18) and carries the integrity hash',
          os.stat(dumpfile).st_mode & 0o777 == 0o600 and isinstance(d.get('hash'), str)
          and len(d['hash']) == 64, '%03o %r' % (os.stat(dumpfile).st_mode & 0o777, d.get('hash'))[:80])
    r = ctl_cmd('show dump-interval', 15537 + BASE)
    check('request dump: the dump-interval setting answers with a dump path', r == 'ok dump-interval=off', r[:80])
    r = ctl_cmd('help', 15537 + BASE)
    check('request dump: the help lists the dump commands with a path', 'request dump' in r
          and 'request restore' in r, r[:160])
    r = ctl_cmd('request dump with-cache', 15537 + BASE)
    check('request dump with-cache: the words ride along', r.startswith('ok dumped 91 word(s)'), r[:120])
    d = _json.load(open(dumpfile))
    check('request dump with-cache: the registers are in the json', len(d.get('registers', [])) == 91,
          str(len(d.get('registers', []))))
    r = ctl_cmd('request restore', 15537 + BASE)
    check('request restore: the words are back without the device', r.startswith('ok restored 91 word(s)')
          and '0 setting(s)' in r, r[:120])
    ctl_cmd('set interval 2', 15537 + BASE)
    ctl_cmd('request dump', 15537 + BASE)
    d = _json.load(open(dumpfile))
    check('request dump: the settings-only dump keeps the words out', d.get('registers') == []
          and d.get('settings', {}).get('modbus/interval') == 2.0, str(d.get('settings')))
    ctl_cmd('request flush cache', 15537 + BASE)
    r = ctl_cmd('show cache', 15537 + BASE)
    check('request restore: the clear emptied the cache first', '0 word(s) cached' in r, r[:80])
    r = ctl_cmd('request restore', 15537 + BASE)
    check('request restore: the settings-only dump restores the override (the cache stays empty)',
          r.startswith('ok restored 0 word(s), 1 setting(s)'), r[:120])
    time.sleep(1.4)   # the poller refills (interval 1 s) before the with-cache dump
    ctl_cmd('request dump with-cache', 15537 + BASE)
    ctl_cmd('request flush cache', 15537 + BASE)
    r = ctl_cmd('request restore', 15537 + BASE)
    check('request restore: the with-cache dump brings the words back',
          r.startswith('ok restored 91 word(s), 1 setting(s)'), r[:120])
    r = ctl_cmd('show interval', 15537 + BASE)
    check('request restore: the setting override re-applied', r == 'ok interval=2.00s', r)
    r = ctl_cmd('show dump-path', 15537 + BASE)
    check('dump: the dump path shows (the per-setting row)', r == 'ok dump-path=%s' % dumpfile, r[-160:])
    # the F18 restore gates: tampering, a group-writable dump and an unsigned dump all refuse
    good = open(dumpfile).read()
    d = _json.loads(good); d['registers'][0][2] = 65535
    open(dumpfile, 'w').write(_json.dumps(d))
    r = ctl_cmd('request restore', 15537 + BASE)
    check('dump: a tampered dump refuses to restore (integrity hash)',
          r.startswith('fail restore failed: the dump') and 'integrity hash' in r, r[:140])
    open(dumpfile, 'w').write(good)
    d = _json.loads(good); d.pop('hash')
    open(dumpfile, 'w').write(_json.dumps(d))
    r = ctl_cmd('request restore', 15537 + BASE)
    check('dump: an unsigned (pre-hash) dump refuses to restore',
          r.startswith('fail restore failed: the dump') and 'predates the integrity hash' in r, r[:140])
    open(dumpfile, 'w').write(good)
    os.chmod(dumpfile, 0o646)
    r = ctl_cmd('request restore', 15537 + BASE)
    check('dump: a group/world-writable dump refuses to restore',
          r.startswith('fail restore failed: the dump') and 'chmod 0600' in r, r[:140])
    os.chmod(dumpfile, 0o600)
    r = ctl_cmd('request restore', 15537 + BASE)
    check('dump: the restored dump still loads after the refused attempts',
          r.startswith('ok restored 91 word(s)'), r[:120])

    # ---- the sealed dumps (dump-key): the words and the settings ride
    #      encrypted; a restore fails closed on a wrong or missing key
    kdumpfile = '/tmp/reg_dump_sealed.json'
    p_kdump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                '--listen', '127.0.0.1:%d' % (15538 + BASE), '--interval', '1', '--cache-ttl', '30',
                                '--profile', R, '--control-port', '%d' % (15539 + BASE),
                                '--dump-path', kdumpfile, '--dump-key', 'seal-key-1'],
                               stdout=open('/tmp/reg_cache_kdump.log', 'w'), stderr=subprocess.STDOUT,
                               env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_kdump)
    time.sleep(1.5)
    r = ctl_cmd('show dump-key', 15539 + BASE)
    check('sealed dump: show dump-key is a secret — it never shows',
          r.startswith('fail dump-key is a secret'), r[:100])
    r = ctl_cmd('set dump-key other', 15539 + BASE)
    check('sealed dump: set dump-key answers the restart note (the key cannot drift mid-life)',
          r.startswith('fail restart required (startup-only knob)'), r[:100])
    r = ctl_cmd('show config', 15539 + BASE)
    check('sealed dump: show config renders the key row as *** SECRET REMOVED ***',
          'set dump key *** SECRET REMOVED ***' in r and 'seal-key-1' not in r, r[:200])
    time.sleep(1.6)   # the poller fills the cache (interval 1 s)
    r = ctl_cmd('request dump with-cache', 15539 + BASE)
    check('sealed dump: the with-cache dump reports sealed',
          r.startswith('ok dumped 91 word(s)') and '(sealed)' in r, r[:120])
    raw = open(kdumpfile).read()
    d = _json.loads(raw)
    check('sealed dump: the envelope is the sealed version-2 shape — the words and the settings encrypted away',
          d.get('format') == 'modbus-cache-dump' and d.get('version') == 2
          and d.get('cipher') == 'sha256-ctr' and 'registers' not in d and 'settings' not in d
          and d.get('box') and d.get('mac') and 'interval' not in raw, raw[:120])
    check('sealed dump: the payload is opaque — the sealed file is one flat envelope, no nested plaintext JSON',
          raw.count('{') == 1, raw[:120])
    r = ctl_cmd('request restore', 15539 + BASE)
    check('sealed dump: the restore re-applies under the configured key',
          r.startswith('ok restored 91 word(s)'), r[:120])
    plain = open(dumpfile).read()   # the keyless block's good plaintext dump — the symmetric gate's fixture
    open(kdumpfile, 'w').write(plain)
    r = ctl_cmd('request restore', 15539 + BASE)
    check('sealed dump: the configured key refuses an unsealed dump (the symmetric gate, live)',
          r.startswith('fail restore failed') and 'not sealed but dump-key is configured' in r, r[:160])
    r = ctl_cmd('request dump with-cache', 15539 + BASE)   # re-seal: the next legs read the sealed file
    check('sealed dump: the file is sealed again for the next legs', '(sealed)' in r, r[:120])
    p_kdump.kill()
    time.sleep(0.4)
    # the wrong key: the sealed dump refuses at start (the mac reads it as tampered content)
    p_wrong = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                '--listen', '127.0.0.1:%d' % (15538 + BASE), '--interval', '1', '--cache-ttl', '30',
                                '--profile', R, '--control-port', '%d' % (15539 + BASE),
                                '--dump-path', kdumpfile, '--dump-key', 'seal-key-WRONG',
                                '--restore-on-start'],
                               stdout=open('/tmp/reg_cache_kwrong.log', 'w'), stderr=subprocess.STDOUT,
                               env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_wrong)
    line = ''
    for _ in range(80):
        line = open('/tmp/reg_cache_kwrong.log').read()
        if 'fails its seal' in line:
            break
        time.sleep(0.1)
    check('sealed dump: a wrong key refuses the dump at start (fails closed)',
          'fails its seal' in line, line[-220:])
    r = ctl_cmd('show version', 15539 + BASE)
    check('sealed dump: the daemon is up despite the refused dump', r.startswith('ok modbus-cache'), r[:80])
    p_wrong.kill()
    time.sleep(0.4)
    # the missing-key half of the symmetric gate: a keyless daemon refuses the sealed dump
    p_nokey = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                '--listen', '127.0.0.1:%d' % (15538 + BASE), '--interval', '1', '--cache-ttl', '30',
                                '--profile', R, '--control-port', '%d' % (15539 + BASE),
                                '--dump-path', kdumpfile, '--restore-on-start'],
                               stdout=open('/tmp/reg_cache_knokey.log', 'w'), stderr=subprocess.STDOUT,
                               env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_nokey)
    line = ''
    for _ in range(80):
        line = open('/tmp/reg_cache_knokey.log').read()
        if 'pass the key' in line:
            break
        time.sleep(0.1)
    check('sealed dump: a keyless daemon refuses the sealed dump at start (fail closed)',
          'pass the key' in line, line[-220:])
    r = ctl_cmd('show version', 15539 + BASE)
    check('sealed dump: the daemon is up despite the refused sealed dump', r.startswith('ok modbus-cache'), r[:80])
    p_nokey.kill()
    time.sleep(0.4)
    # the right key: the sealed dump restores (the words are back without the device)
    p_right = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                '--listen', '127.0.0.1:%d' % (15538 + BASE), '--interval', '1', '--cache-ttl', '30',
                                '--profile', R, '--control-port', '%d' % (15539 + BASE),
                                '--dump-path', kdumpfile, '--dump-key', 'seal-key-1',
                                '--restore-on-start'],
                               stdout=open('/tmp/reg_cache_kright.log', 'w'), stderr=subprocess.STDOUT,
                               env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_right)
    line = ''
    for _ in range(80):
        line = open('/tmp/reg_cache_kright.log').read()
        if 'restored the state dump' in line:
            break
        time.sleep(0.1)
    check('sealed dump: the right key restores the words at start',
          'restored the state dump' in line and '91 word(s)' in line, line[-220:])
    r = ctl_cmd('show cache', 15539 + BASE)
    check('sealed dump: the restored words serve', '91 word(s) cached' in r, r[:80])
    p_right.kill()
    time.sleep(0.4)
    # the file: reference form (one secret knob, two forms): the key
    # material comes from an owner-only file — and an unreadable reference
    # fails the start; the keyless dump posture warns at start
    kkeyfile = '/tmp/reg_cache_dump_key_file'
    with open(kkeyfile, 'w') as fh:
        fh.write('seal-key-1\n')
    os.chmod(kkeyfile, 0o600)
    log = open('/tmp/reg_cache_dump.log').read()   # the keyless dump instance's start
    check('file-key: a dump path without a key warns unsealed at start',
          'is not sealed' in log and 'set dump-key' in log, log[-220:])
    p_file = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                               '--listen', '127.0.0.1:%d' % (15538 + BASE), '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '%d' % (15539 + BASE),
                               '--dump-path', kdumpfile, '--dump-key', 'file:' + kkeyfile,
                               '--restore-on-start'],
                              stdout=open('/tmp/reg_cache_kfile.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_file)
    line = ''
    for _ in range(80):
        line = open('/tmp/reg_cache_kfile.log').read()
        if 'restored the state dump' in line:
            break
        time.sleep(0.1)
    check('file-key: the file-reference key restores the sealed words at start',
          'restored the state dump' in line and '91 word(s)' in line, line[-220:])
    r = ctl_cmd('show cache', 15539 + BASE)
    check('file-key: the restored words serve', '91 word(s) cached' in r, r[:80])
    p_file.kill()
    time.sleep(0.4)
    p_missing = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                  '--listen', '127.0.0.1:%d' % (15538 + BASE), '--interval', '1', '--cache-ttl', '30',
                                  '--profile', R, '--control-port', '%d' % (15539 + BASE),
                                  '--dump-path', kdumpfile, '--dump-key', 'file:/nonexistent/dump_key',
                                  '--restore-on-start'],
                                 stdout=open('/tmp/reg_cache_kmissing.log', 'w'), stderr=subprocess.STDOUT,
                                 env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    line = ''
    for _ in range(80):
        line = open('/tmp/reg_cache_kmissing.log').read()
        if 'cannot read dump-key' in line:
            break
        time.sleep(0.1)
    time.sleep(0.3)   # the SystemExit prints, then the process is gone
    check('file-key: an unreadable reference fails the start (fail fast, never plaintext)',
          'cannot read dump-key' in line and p_missing.poll() is not None, line[-220:])
    p_missing.poll()
    time.sleep(0.4)

    r = ctl_cmd('set dump-interval 1', 15537 + BASE)
    check('dump-interval: the live setting accepted', r.startswith('ok dump-interval=1.00s'), r[:120])
    r = ctl_cmd('show dump-interval', 15537 + BASE)
    check('dump-interval: the live setting shows', r == 'ok dump-interval=1.00s', r[-160:])
    m1 = os.stat(dumpfile).st_mtime
    time.sleep(2.5)
    m2 = os.stat(dumpfile).st_mtime
    check('dump-interval: the file refreshes by itself', m2 > m1, '%.2f -> %.2f' % (m1, m2))
    r = ctl_cmd('set dump-interval off', 15537 + BASE)
    check('dump-interval: off again', r.startswith('ok dump-interval=off'), r[:80])
    # the periodic dumper's failure speaks its one line (the canon phrase —
    # the dumper keeps ticking, the write failure is logged, never fatal)
    ctl_cmd('set dump-path /nonexistent-dir-zz/dump.json', 15537 + BASE)
    ctl_cmd('set dump-interval 1', 15537 + BASE)
    time.sleep(2.2)
    ctl_cmd('set dump-interval off', 15537 + BASE)
    dlog = open('/tmp/reg_cache_dump.log', errors='replace').read()
    check('dump-interval: a failing periodic dump logs its one line',
          'the periodic dump to /nonexistent-dir-zz/dump.json failed' in dlog, dlog[-200:])
    ctl_cmd('set dump-path ' + dumpfile, 15537 + BASE)
    # the write-behind story: the shutdown dump restores into the next start
    ctl_cmd('set interval 3', 15537 + BASE)
    r = ctl_cmd('shutdown', 15537 + BASE)
    check('shutdown dump: the stopper wrote the file', r.startswith('bye'), r[:40])
    p_dump.wait(timeout=10)
    d = _json.load(open(dumpfile))
    check('shutdown dump: settings-only by default (the override is in it, the words stay out)',
          d.get('registers') == [] and d.get('settings', {}).get('modbus/interval') == 3.0, repr(d.get('settings')))
    p_dump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                               '--listen', '127.0.0.1:%d' % (15536 + BASE), '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '%d' % (15537 + BASE), '--dump-with-cache',
                               '--dump-path', dumpfile],
                              stdout=open('/tmp/reg_cache_dump2.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_dump)
    time.sleep(1.5)
    log = open('/tmp/reg_cache_dump2.log').read()
    check('restore-on-start: the gate defaults to off — the dump is not loaded', 'not loaded on start' in log
          and 'restored the state dump' not in log.split('state dumps:')[1], log[-200:])
    r = ctl_cmd('show interval', 15537 + BASE)
    check('restore-on-start: the override in the file did not leak in', r == 'ok interval=1.00s', r)
    r = ctl_cmd('request dump', 15537 + BASE)
    check('dump-with-cache: the flag turns the plain request dump full', r.startswith('ok dumped 91 word(s)'),
          r[:120])
    ctl_cmd('request flush cache', 15537 + BASE)
    r = ctl_cmd('request restore', 15537 + BASE)
    check('restore-on-start: the manual request restore still works', r.startswith('ok restored 91 word(s), ')
          and 'setting(s) from' in r, r[:120])
    r = ctl_cmd('show cache', 15537 + BASE)
    check('restore-on-start: the manual restore loaded the words', '91 word(s) cached' in r, r[:80])
    ctl_cmd('set interval 3', 15537 + BASE)
    ctl_cmd('shutdown', 15537 + BASE)
    p_dump.wait(timeout=10)
    p_dump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                               '--listen', '127.0.0.1:%d' % (15536 + BASE), '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '%d' % (15537 + BASE), '--dump-with-cache',
                               '--dump-path', dumpfile, '--restore-on-start'],
                              stdout=open('/tmp/reg_cache_dump2.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_dump)
    time.sleep(1.5)
    r = ctl_cmd('show cache', 15537 + BASE)
    check('restore-on-start: the gate loads the dump', '91 word(s) cached' in r, r[:80])
    r = ctl_cmd('show interval', 15537 + BASE)
    check('restore-on-start: the override came back with the gate', r == 'ok interval=3.00s', r)
    ctl_cmd('clear interval', 15537 + BASE)
    ctl_cmd('shutdown', 15537 + BASE)
    p_dump.wait(timeout=10)

    # the native metrics endpoint: bearer auth + the cache gauges
    p_metrics = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                  '--listen', '127.0.0.1:%d' % (15528 + BASE), '--interval', '1', '--profile', R,
                                  '--control-port', '%d' % (15530 + BASE),
                                  '--metrics-listen', '127.0.0.1:%d' % (15529 + BASE), '--metrics-server', '--metrics-token', 'sekrit',
                                  '--metrics-max-clients', '1'],
                                 stdout=open('/tmp/reg_cache_metrics.log', 'w'), stderr=subprocess.STDOUT,
                                 env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_metrics)
    time.sleep(1.5)
    import urllib.request, urllib.error

    def get_metrics(tok=None, port=15529 + BASE):
        req = urllib.request.Request('http://127.0.0.1:%d/metrics' % port)
        if tok:
            req.add_header('Authorization', 'Bearer ' + tok)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
    st, body = get_metrics()
    check('metrics: unauthenticated read is a 401', st == 401, '%s %r' % (st, body[:40]))
    st, body = get_metrics('wrong')
    check('metrics: a wrong token is a 401', st == 401, str(st))
    st, body = get_metrics('sekrit')
    check('metrics: the token reads the gauges', st == 200
          and all(n in body for n in ('modbus_cache_hits_total', 'modbus_cache_misses_total',
                                      'modbus_cache_poll_up', 'modbus_cache_age_seconds',
                                      'modbus_cache_words', 'modbus_cache_clients',
                                      'modbus_cache_poll_duration_seconds',
                                      'modbus_cache_poll_duration_mean_seconds',
                                      'modbus_cache_last_poll_age_seconds')), '%s %r' % (st, body[:120]))
    check('metrics: the poll is up and the words are cached', 'modbus_cache_poll_up 1' in body
          and 'modbus_cache_words 91' in body, repr(body[:200]))
    check('metrics: the uplink session and the per-block gauges',
          all(n in body for n in ('modbus_cache_uplink_up 1', 'modbus_cache_uplink_exchanges_total',
                                  'modbus_cache_uplink_errors_total', 'modbus_cache_uplink_bytes_total',
                                  'modbus_cache_uplink_block_up{fc="3"', 'modbus_cache_uplink_block_latency_seconds',
                                  'modbus_cache_uplink_block_fails_total')), repr(body[:200]))
    r = ctl_cmd('show metrics-listen', 15530 + BASE)
    check('metrics: the per-setting show carries the endpoint', 'ok metrics-listen=127.0.0.1:%d' % (15529 + BASE) in r, r[:160])
    # the metrics caps: a parked (silent) connection holds the one slot, the next request gets 503
    parked = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
    time.sleep(0.3)
    over = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
    over.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nAuthorization: Bearer sekrit\r\n\r\n')
    reply = over.recv(64)
    check('metrics: 503 past --metrics-max-clients 1', reply.startswith(b'HTTP/1.1 503'),
          reply.split(b'\r\n')[0].decode() if reply else 'empty reply')
    over.close()
    parked.close()
    # the metrics client timeout: a silent peer is dropped on the timer (the slowloris cap)
    r = ctl_cmd('show metrics-client-timeout', 15530 + BASE)
    check('metrics client-timeout: the show renders the default cap', r == 'ok metrics-client-timeout=5.00s', r)
    r = ctl_cmd('set metrics-client-timeout 1', 15530 + BASE)
    check('metrics client-timeout: set takes the seconds value', r.startswith('ok metrics-client-timeout=1.00s'), r[:90])
    idle = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
    dropped = False
    idle.settimeout(0.2)
    for _ in range(60):          # the handler times the silent peer out at ~1s
        time.sleep(0.1)
        try:
            if idle.recv(16) == b'':
                dropped = True
                break
        except OSError:
            continue             # keep polling until the server's timer closes the socket
    idle.close()
    check('metrics client-timeout: the silent peer is dropped on the timer', dropped,
          'the idle socket stayed open past the cap')
    r = ctl_cmd('clear metrics-client-timeout', 15530 + BASE)
    check('metrics client-timeout: clear restores the default cap', r.startswith('ok metrics-client-timeout=5.00s'), r[:90])
    # the read-delay: the poll paces between the upstream blocks (the wire round-trip;
    # the pacing itself shows in the poll-duration gauge when the spec splits)
    r = ctl_cmd('set read-delay 0.25', 15530 + BASE)
    check('read-delay: set takes the seconds value', r.startswith('ok read-delay=250.00ms'), r[:90])
    r = ctl_cmd('show read-delay', 15530 + BASE)
    check('read-delay: the show renders it', r == 'ok read-delay=250.00ms', r)
    r = ctl_cmd('clear read-delay', 15530 + BASE)
    check('read-delay: clear restores the configured default', r.startswith('ok read-delay=50.00ms'), r[:90])
    # the live metrics enable switch: off stops the endpoint, on restarts it
    r = ctl_cmd('set metrics-server off', 15530 + BASE)
    check('metrics enable: set off stops the endpoint', r.startswith('ok metrics-server=off'), r[:80])
    srv_down = False
    try:
        socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=1).close()
    except OSError:
        srv_down = True
    check('metrics enable: the port is closed after set off', srv_down)
    r = ctl_cmd('set metrics-server on', 15530 + BASE)
    check('metrics enable: set on serves again', r.startswith('ok metrics-server=on'), r[:80])
    st, _ = get_metrics('sekrit')
    check('metrics enable: the gauges are back', st == 200, str(st))
    # show config speaks the live overrides (the _apply write-backs): the
    # toggle's row follows the endpoint, not the startup flag
    r = ctl_cmd('show config', 15530 + BASE)
    check('show config: the live metrics enable rides (true after set on)',
          'set metrics enable true' in r, r[:160])
    check('show config: the metrics token renders as *** SECRET REMOVED ***',
          'set metrics token *** SECRET REMOVED ***' in r and 'sekrit' not in r, r[:200])
    ctl_cmd('set metrics-server off', 15530 + BASE)
    r = ctl_cmd('show config', 15530 + BASE)
    check('show config: the live metrics enable rides (false after set off)',
          'set metrics enable false' in r, r[:160])
    ctl_cmd('set metrics-server on', 15530 + BASE)
    # the live ttl rides too, and the write-register file marker renders
    # without crashing the handler (the string markers are not range lists)
    with open('/tmp/reg_acl_write.json', 'w') as f:
        _json.dump({'type': 'write-registers', 'rules': [{'type': 'allow', 'range': '127:2'}]}, f)
    r = ctl_cmd('set write-registers file:/tmp/reg_acl_write.json', 15530 + BASE)
    check('write registers: the file marker sets', r.startswith('ok write-registers=file:'), r[:90])
    r = ctl_cmd('set cache-ttl 55', 15530 + BASE)
    check('cache ttl: the live set answers', r.startswith('ok cache-ttl='), r[:90])
    r = ctl_cmd('show config', 15530 + BASE)
    check('show config: the live cache ttl and the file marker ride',
          'set cache ttl 55.0' in r and 'set write registers file:/tmp/reg_acl_write.json' in r, r[:220])
    ctl_cmd('clear cache-ttl', 15530 + BASE)
    r = ctl_cmd('show config', 15530 + BASE)
    check('show config: the clear ttl returns the configured value',
          'set cache ttl 30.0' in r, r[:160])   # the default is the tree's flat 30 s
    ctl_cmd('set write-registers any', 15530 + BASE)
    # requests-audit: the live name is the wire spelling (the branch keys it)
    r = ctl_cmd('set requests-audit 120', 15530 + BASE)
    check('audit requests: the live set answers the path name', r.startswith('ok requests-audit='), r[:90])
    r = ctl_cmd('show requests-audit', 15530 + BASE)
    check('audit requests: the show answers the tally seconds', r == 'ok requests-audit=2.00m', r)
    ctl_cmd('clear requests-audit', 15530 + BASE)
    # the live caps: raising the cap serves the second concurrent client, lowering 503s it again
    r = ctl_cmd('set metrics-max-clients 2', 15530 + BASE)
    check('metrics limits: the live cap set', r.startswith('ok metrics-max-clients=2'), r[:90])
    parked = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
    time.sleep(0.3)
    over = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
    over.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nAuthorization: Bearer sekrit\r\n\r\n')
    reply = over.recv(64)
    check('metrics limits: the raised cap serves the second client', reply.startswith(b'HTTP/1.0 200'),
          reply.split(b'\r\n')[0].decode() if reply else 'empty reply')
    over.close()
    parked.close()
    r = ctl_cmd('set metrics-max-clients 1', 15530 + BASE)
    check('metrics limits: the cap lowered again', r.startswith('ok metrics-max-clients=1'), r[:90])
    parked = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
    time.sleep(0.3)
    over = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
    over.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nAuthorization: Bearer sekrit\r\n\r\n')
    reply = over.recv(64)
    check('metrics limits: 503 past the lowered cap', reply.startswith(b'HTTP/1.1 503'),
          reply.split(b'\r\n')[0].decode() if reply else 'empty reply')
    over.close()
    parked.close()
    # the secrets are startup-only (the dump-key treatment): the set/clear
    # refuse on the wire, the configured token keeps serving
    r = ctl_cmd('set metrics-token sekrit2', 15530 + BASE)
    check('metrics token: startup-only — the set refuses',
          r.startswith('fail restart required (startup-only knob)'), r[:90])
    st, _ = get_metrics('sekrit')
    check('metrics token: the configured token still serves (no live rotation)', st == 200, str(st))
    r = ctl_cmd('show metrics-token', 15530 + BASE)
    check('metrics token: the secret never renders back', r.startswith('fail metrics-token is a secret'), r)
    # the startup-only listen: the set records the pending value and answers
    # the note; the running endpoint keeps the old address until the restart
    r = ctl_cmd('set metrics-listen 127.0.0.1:%d' % (15535 + BASE), 15530 + BASE)
    check('metrics listen: the set answers the restart note',
          r.startswith('note restart required (startup-only knob)'), r[:90])
    r = ctl_cmd('show metrics-listen', 15530 + BASE)
    check('metrics listen: show renders the recorded pending value',
          r.startswith('ok metrics-listen=127.0.0.1:%d' % (15535 + BASE)), r[:90])
    st, _ = get_metrics('sekrit')
    check('metrics listen: the running endpoint kept the old address (the restart applies it)', st == 200, str(st))
    r = ctl_cmd('set metrics-listen bogus', 15530 + BASE)
    check('metrics listen: a bad value still fails the set', r.startswith('fail'), r[:90])
    r = ctl_cmd('clear metrics-listen', 15530 + BASE)
    check('metrics listen: the clear answers the note too',
          r.startswith('note restart required (startup-only knob)'), r[:90])
    r = ctl_cmd('show metrics-listen', 15530 + BASE)
    check('metrics listen: the clear restored the configured value',
          r.startswith('ok metrics-listen=127.0.0.1:%d' % (15529 + BASE)), r[:90])
    # the tokenless metrics endpoint (the F13 shapes on the live wire): the
    # tokenless loopback serve is the auth, the enable dance works without a
    # token, and the pending listen cannot move beyond loopback while it serves
    p_tokless = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                                  '--listen', '127.0.0.1:%d' % (15540 + BASE), '--interval', '1', '--profile', R,
                                  '--control-port', '%d' % (15542 + BASE),
                                  '--metrics-listen', '127.0.0.1:%d' % (15541 + BASE), '--metrics-server'],
                                 stdout=open('/tmp/reg_cache_tokless.log', 'w'), stderr=subprocess.STDOUT,
                                 env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_tokless)
    time.sleep(1.5)
    st, _ = get_metrics(port=15541 + BASE)
    check('metrics token: the tokenless loopback endpoint serves (the bind is the auth)', st == 200, str(st))
    r = ctl_cmd('set metrics-token off', 15542 + BASE)
    check('metrics token: startup-only — the off refuses too',
          r.startswith('fail restart required (startup-only knob)'), r[:90])
    r = ctl_cmd('set metrics-server off', 15542 + BASE)
    check('metrics enable: off stops the tokenless endpoint', r.startswith('ok metrics-server=off'), r[:80])
    r = ctl_cmd('set metrics-server on', 15542 + BASE)
    check('metrics enable: on serves tokenless again (the F13 shape on loopback)',
          r.startswith('ok metrics-server=on'), r[:80])
    r = ctl_cmd('set metrics-listen 0.0.0.0:15543', 15542 + BASE)
    check('metrics listen: the pending move beyond loopback refuses while serving tokenless (F13)',
          r.startswith('fail metrics-listen cannot move beyond loopback') and 'F13' in r, r[:140])
    p_tokless.send_signal(signal.SIGTERM)
    p_tokless.wait(timeout=10)

    # the metrics-acl gate: the connect-acl reading on the /metrics listener
    # (the scraper's metrics-acl shape) — the inline grammar + the file:
    # chain, checked at accept: a client off the ACL is closed without a reply
    r = subprocess.run([sys.executable, P, '--dry-run', '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                        '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                        '--metrics-acl', 'file:' + os.path.join(REPO, 'examples', 'acl-ip-prefix.json')],
                       capture_output=True, text=True, timeout=60)
    check('metrics acl: the shipped ip-prefix example loads (dry-run)',
          r.returncode == 0 and 'dry-run: configuration and register map are valid' in (r.stdout + r.stderr),
          '%s %r' % (r.returncode, (r.stdout + r.stderr)[-120:]))
    r = subprocess.run([sys.executable, P, '--dry-run', '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                        '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                        '--metrics-acl', 'file:/nonexistent/acl.json'],
                       capture_output=True, text=True, timeout=60)
    check('metrics acl: a missing acl file refuses the start (rc 1, clean)',
          r.returncode == 1 and 'cannot read acl file' in r.stderr, r.stderr[-100:])
    r = subprocess.run([sys.executable, P, '--dry-run', '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                        '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                        '--metrics-acl', '10.0.0.0/999'],
                       capture_output=True, text=True, timeout=60)
    check('metrics acl: a bad inline entry refuses the start (rc 1, clean)',
          r.returncode == 1 and 'bad ACL entry' in r.stderr, r.stderr[-100:])

    def metrics_acl_raw(tok):
        # one GET over a raw socket, the full reply or the close: the
        # accept-check refusal closes without a reply — a reset on some stacks
        try:
            s = socket.create_connection(('127.0.0.1', 15529 + BASE), timeout=5)
            s.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nAuthorization: Bearer ' + tok.encode()
                      + b'\r\nConnection: close\r\n\r\n')
            buf = b''
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            s.close()
            return buf
        except (ConnectionResetError, BrokenPipeError):
            return b''

    check('metrics acl: any serves (the default)', metrics_acl_raw('sekrit').startswith(b'HTTP/1.0 200'),
          metrics_acl_raw('sekrit').split(b'\r\n')[0].decode()[:60])
    r = ctl_cmd('set metrics-acl none', 15530 + BASE)
    check('metrics acl: set none answers ok', r.startswith('ok metrics-acl=none'), r[:80])
    check('metrics acl: none closes the client without a reply', metrics_acl_raw('sekrit') == b'',
          repr(metrics_acl_raw('sekrit')[:40]))
    r = ctl_cmd('show metrics-acl', 15530 + BASE)
    check('metrics acl: the none show', r == 'ok metrics-acl=none', r[:60])
    r = ctl_cmd('show config', 15530 + BASE)
    check('metrics acl: the live set rides show config', 'set metrics acl none' in r, r[:200])
    r = ctl_cmd('show metrics-acl-table', 15530 + BASE)
    check('metrics acl: none spells the deny-any chain', r == 'ok acl-metrics-table\ndeny 0.0.0.0/0', r[:80])
    r = ctl_cmd('set metrics-acl table', 15530 + BASE)
    check('metrics acl: the show word is not a value (the pointer to the report)',
          r.startswith('fail') and 'show metrics-acl-table' in r, r[:120])
    r = ctl_cmd('set metrics-acl 127.0.0.1', 15530 + BASE)
    check('metrics acl: the whitelist set canonicalizes', r.startswith('ok metrics-acl=127.0.0.1/32'), r[:80])
    check('metrics acl: the whitelist serves the lab', metrics_acl_raw('sekrit').startswith(b'HTTP/1.0 200'))
    r = ctl_cmd('show metrics-acl-table', 15530 + BASE)
    check('metrics acl: the whitelist table',
          r == 'ok acl-metrics-table\ndeny 0.0.0.0/0\nallow 127.0.0.1/32', r[:80])
    mgate = '/tmp/reg_acl_metrics-%d.json' % PORT
    with open(mgate, 'w') as fh:
        _json.dump({'desc': 'the lab gate', 'type': 'ip-prefix', 'rules': [
            {'type': 'deny', 'prefix': 'any'},
            {'type': 'allow', 'prefix': '127.0.0.1', 'desc': 'the loopback lab'},
        ]}, fh)
    r = ctl_cmd('set metrics-acl file:%s' % mgate, 15530)
    check('metrics acl: the file gate loads', r.startswith('ok metrics-acl=file:%s' % mgate), r[:100])
    r = ctl_cmd('show metrics-acl', 15530 + BASE)
    check('metrics acl: the file spelling shows', r == 'ok metrics-acl=file:%s' % mgate, r[:80])
    r = ctl_cmd('show metrics-acl-table', 15530 + BASE)
    check('metrics acl: the file gate renders its own rules',
          r == 'ok acl-metrics-table\n% the lab gate\ndeny 0.0.0.0/0\nallow 127.0.0.1 # the loopback lab', r[:160])
    check('metrics acl: the file gate serves the lab', metrics_acl_raw('sekrit').startswith(b'HTTP/1.0 200'))
    with open(mgate, 'w') as fh:   # the gate re-reads on every set: a bad prefix refuses, the old gate stands
        _json.dump({'type': 'ip-prefix', 'rules': [{'type': 'allow', 'prefix': '127.0.0.1/8'}]}, fh)
    r = ctl_cmd('set metrics-acl file:%s' % mgate, 15530)
    check('metrics acl: a bad file answers err with the old gate standing',
          r.startswith('fail') and 'spell the network' in r
          and metrics_acl_raw('sekrit').startswith(b'HTTP/1.0 200'), r[:140])
    r = ctl_cmd('clear metrics-acl', 15530 + BASE)
    check('metrics acl: clear restores the configured value', r.startswith('ok metrics-acl=any'), r[:80])
    check('metrics acl: any serves again', metrics_acl_raw('sekrit').startswith(b'HTTP/1.0 200'))

    # the control plane, audit trail and dump lives (the same metrics pattern:
    # set/show/clear on the wire, the secrets never render, the rebind moves it)
    def ctl_tok(cmd, port, tok):
        """ctl_cmd with a custom token (the rotation pins re-key the session)."""
        mac = hmac.new(tok.encode(), cmd.encode(), hashlib.sha256).hexdigest()
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        s.sendall(_json.dumps({'cmd': 'auth', 'token': tok}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        obj = _json.loads(buf.decode())
        assert obj.get('status') == 'ok', obj
        s.sendall(_json.dumps({'cmd': cmd, 'mac': mac}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            b2 = s.recv(4096)
            if not b2:
                break
            buf += b2
        s.close()
        obj = _json.loads(buf.decode())
        assert obj.get('mac') == hmac.new(tok.encode(), ('%s %s' % (obj.get('status'), obj.get('text', ''))).encode(),
                                          hashlib.sha256).hexdigest(), 'the reply mac does not verify: %r' % obj
        return '%s %s' % (obj.get('status'), obj.get('text', ''))

    r = ctl_cmd('show control-ops-verbs', 15530 + BASE)
    check('control ops verbs: show answers the policy', r == 'ok control-ops-verbs=flush,show', r)
    r = ctl_cmd('set control-ops-verbs show, ping', 15530 + BASE)
    check('control ops verbs: set takes the comma list', r.startswith('ok control-ops-verbs=ping,show'), r[:90])
    r = ctl_cmd('set control-ops-verbs bogus', 15530 + BASE)
    check('control ops verbs: an unknown verb is a clean err', r.startswith('fail the ops policy needs at least one'),
          r[:80])
    ctl_cmd('clear control-ops-verbs', 15530 + BASE)
    r = ctl_cmd('show control-token', 15530 + BASE)
    check('control token: the secret never renders back', r.startswith('fail control-token is a secret'), r)
    r = ctl_cmd('clear control-token', 15530 + BASE)
    check('control token: clear refuses (startup-only)', r.startswith('fail restart required (startup-only knob)'), r[:80])
    r = ctl_cmd('set control-trust-uids 1000, 1001', 15530 + BASE)
    check('control trust-uids: set takes the uid list', r.startswith('ok control-trust-uids=1000,1001'), r[:90])
    r = ctl_cmd('clear control-trust-uids', 15530 + BASE)
    check('control trust-uids: clear restores the configured none', r.startswith('ok control-trust-uids=off'), r[:90])
    r = ctl_cmd('set control-socket-group on', 15530 + BASE)
    check('control socket-group: set answers on', r.startswith('ok control-socket-group=on'), r[:90])
    ctl_cmd('clear control-socket-group', 15530 + BASE)
    r = ctl_cmd('show audit-max-mb', 15530 + BASE)
    check('audit rotate: show answers the configured MB', r == 'ok audit-max-mb=10', r)
    listing = '\n'.join([
        '    audit-forward        also forward every audit line: the local syslog mirror or a remote collector (the off-box copy)',
        '    audit-forward-format the remote forward\'s envelope: RFC5424 (the default) or CEF — the local syslog forms keep the verbatim send',
        '    audit-log            the audit trail\'s file: a path, - for stdout, none = no local file (the forward carries the trail), empty = the XDG state home',
        '    no-audit-log         disable the audit trail entirely',
        '    requests-audit       audit one REQUESTS tally per client per this many seconds',
        '    rotate               the audit trail\'s rotation: the size trigger, the UTC-midnight trigger and the backup count'])
    r = ctl_cmd('show audit', 15530 + BASE)
    check('audit node: the listing answers the flat names under the namespace', r == 'ok ' + listing, r)
    r = ctl_cmd('show audit rotate', 15530 + BASE)
    check('audit node: the walk answers the intermediate node in the same shape',
          r == 'ok ' + '\n'.join([
              '    audit-daily  also rotate the audit trail at UTC midnight',
              '    audit-files  the rotated audit backups kept',
              '    audit-max-mb rotate the audit trail at this size in MB, 0 = no size rotation']), r)
    r = ctl_cmd('help audit', 15530 + BASE)
    check('audit node: help answers the same listing', r == 'ok ' + listing, r)
    r = ctl_cmd('show modbus', 15530 + BASE)
    check('modbus node: the listing hides the secret rows (the pools rule — the typed path still answers)',
          r.count('\n') == 9 and 'auth-key' not in r and 'auth-upstream-key' not in r, r[:160])
    r = ctl_cmd('show', 15530 + BASE)
    words = [line.strip().split()[0] for line in r[3:].strip().splitlines()
             if line.strip() and not line.strip().startswith('[')]
    check("bare show: the flat grammar's root (the gated word hidden while the dump is off)",
          words == ['acl', 'audit', 'cache', 'cache-ttl', 'config', 'connections', 'control', 'dump',
                    'knobs', 'limits', 'log-level', 'metrics', 'modbus', 'system',
                    'uplink', 'version', 'write'],
          r[:220])
    r = ctl_cmd('set audit-max-mb 5', 15530 + BASE)
    check('audit rotate: max-size set', r.startswith('ok audit-max-mb=5'), r[:90])
    r = ctl_cmd('show audit-log', 15530 + BASE)
    check('audit log-file: the XDG default renders', r.startswith('ok audit-log=')
          and r.endswith('modbus-cache/audit.log'), r)
    live_audit = '/tmp/reg_live_audit.log'
    if os.path.exists(live_audit):
        os.remove(live_audit)
    r = ctl_cmd('set audit-log %s' % live_audit, 15530)
    check('audit log-file: the trail moves live', r.startswith('ok audit-log=%s' % live_audit), r[:120])
    ctl_cmd('show version', 15530 + BASE)
    check('audit log-file: the new sink takes the commands', 'tools=CACHE tag=daemon type=command' in open(live_audit).read(),
          open(live_audit).read()[-120:])
    r = ctl_cmd('set audit-daily on', 15530 + BASE)
    check('audit rotate: daily set', r.startswith('ok audit-daily=on'), r[:90])
    r = ctl_cmd('set audit-files 7', 15530 + BASE)
    check('audit rotate: files set', r.startswith('ok audit-files=7'), r[:90])
    r = ctl_cmd('set no-audit-log on', 15530 + BASE)
    check('audit disable: set answers on', r.startswith('ok no-audit-log=on'), r[:90])
    r = ctl_cmd('show audit-log', 15530 + BASE)
    check('audit disable: the trail is off', r == 'ok audit-log=off', r)
    n_lines = len(open(live_audit).read().splitlines())
    ctl_cmd('show version', 15530 + BASE)
    check('audit disable: no command lands while off', len(open(live_audit).read().splitlines()) == n_lines,
          open(live_audit).read()[-120:])
    ctl_cmd('set no-audit-log off', 15530 + BASE)
    r = ctl_cmd('show audit-log', 15530 + BASE)
    check('audit disable: off rebuilds the trail', r == 'ok audit-log=%s' % live_audit, r)
    ctl_cmd('show version', 15530 + BASE)
    check('audit disable: the commands land again', len(open(live_audit).read().splitlines()) > n_lines,
          open(live_audit).read()[-120:])
    r = ctl_cmd('set audit-forward tcp://127.0.0.1:%d' % (19799 + BASE), 15530 + BASE)
    check('audit forward: the remote target takes the grammar (the soft bind warns, the set lands)',
          r.startswith('ok audit-forward=tcp://127.0.0.1:%d' % (19799 + BASE)), r[:120])
    r = ctl_cmd('show audit-forward-format', 15530 + BASE)
    check('audit forward format: the default renders', r == 'ok audit-forward-format=rfc5424', r)
    r = ctl_cmd('set audit-forward-format cef', 15530 + BASE)
    check('audit forward format: cef takes', r.startswith('ok audit-forward-format=cef'), r)
    r = ctl_cmd('set audit-forward-format gelf', 15530 + BASE)
    check('audit forward format: a foreign format refuses',
          r.startswith('fail audit-forward-format must be one of rfc5424, cef'), r)
    r = ctl_cmd('set audit-forward bogus', 15530 + BASE)
    check('audit forward: a bad spelling refuses with the grammar one-liner',
          r.startswith('fail audit-forward must be none, syslog, syslog:/path'), r)
    r = ctl_cmd('set audit-log none', 15530 + BASE)
    check('audit log-file: none with a forward spells the remote-only mode',
          r.startswith('ok audit-log=remote'), r)
    ctl_cmd('set audit-forward none', 15530 + BASE)
    r = ctl_cmd('show audit-log', 15530 + BASE)
    check('audit log-file: none without a forward folds to off', r == 'ok audit-log=off', r)
    r = ctl_cmd('clear audit-log', 15530 + BASE)
    check('audit log-file: clear restores the configured sink', r.startswith('ok audit-log=')
          and 'modbus-cache/audit.log' in r, r[:120])
    live_dump = '/tmp/reg_live_dump.json'
    r = ctl_cmd('set dump-path %s' % live_dump, 15530)
    check('dump path: set live', r.startswith('ok dump-path=%s' % live_dump), r[:120])
    r = ctl_cmd('show dump', 15530 + BASE)
    check('bare show: the dump on, the interval word lists under the dump node (the dump/ grammar)',
          'dump-interval' in r, r[:160])
    r = ctl_cmd('request dump', 15530 + BASE)
    check('dump path: request dump writes the live path', r.startswith('ok dumped') and live_dump in r, r[:90])
    r = ctl_cmd('set dump-with-cache on', 15530 + BASE)
    check('dump with-cache: set answers on', r.startswith('ok dump-with-cache=on'), r[:90])
    r = ctl_cmd('clear dump-with-cache', 15530 + BASE)
    check('dump with-cache: clear restores off', r.startswith('ok dump-with-cache=off'), r[:90])
    r = ctl_cmd('set restore-on-start on', 15530 + BASE)
    check('dump restore-on-start: the set answers the restart note (the value records pending)',
          r.startswith('note restart required (startup-only knob)'), r[:90])
    r = ctl_cmd('show restore-on-start', 15530 + BASE)
    check('dump restore-on-start: show renders the recorded pending value',
          r.startswith('ok restore-on-start=on'), r[:90])
    ctl_cmd('clear restore-on-start', 15530 + BASE)
    r = ctl_cmd('clear dump-path', 15530 + BASE)
    check('dump path: clear restores off', r.startswith('ok dump-path=off'), r[:90])
    r = ctl_cmd('show', 15530 + BASE)
    words = [line.strip().split()[0] for line in r[3:].strip().splitlines()
             if line.strip() and not line.strip().startswith('[')]
    check('bare show: the dump off again, the gated word hides', 'dump-interval' not in words, r[:160])
    r = ctl_cmd('request dump', 15530 + BASE)
    check('dump path: request dump without a path is a clean err', r.startswith('fail no dump path configured'),
          r[:80])
    r = ctl_cmd('set control-port 15536', 15530 + BASE)
    check('control port: the control rebinds live', r.startswith('ok control-port=127.0.0.1:%d' % (15536 + BASE)), r[:90])
    old_gone = False
    try:
        socket.create_connection(('127.0.0.1', 15530 + BASE), timeout=1).close()
    except OSError:
        old_gone = True
    check('control port: the old port is closed', old_gone)
    r = ctl_cmd('show version', 15536 + BASE)
    check('control port: the new port speaks', r.startswith('ok modbus-cache'), r[:60])
    r = ctl_cmd('clear control-port', 15536 + BASE)
    check('control port: clear restores the configured target', r.startswith('ok control-port=127.0.0.1:%d' % (15530 + BASE)), r[:90])
    r = ctl_cmd('show version', 15530 + BASE)
    check('control port: the restored target speaks', r.startswith('ok modbus-cache'), r[:60])
    r = ctl_cmd('set control-token sekrit2', 15530 + BASE)
    check('control token: startup-only — the set refuses',
          r.startswith('fail restart required (startup-only knob)'), r[:90])
    s = socket.create_connection(('127.0.0.1', 15530 + BASE), timeout=5)
    s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit2'}).encode() + b'\n')
    buf = b''
    while not buf.endswith(b'\n'):
        buf += s.recv(4096)
    s.close()
    check('control token: the never-set token does not authenticate',
          _json.loads(buf.decode()).get('status') == 'fail', buf.decode()[:80])
    r = ctl_tok('show version', 15530, 'sekrit')
    check('control token: the configured token still speaks (no live rotation)', r.startswith('ok modbus-cache'), r[:60])
    r = ctl_tok('show control-token', 15530, 'sekrit')
    check('control token: the secret never renders back', r.startswith('fail control-token is a secret'), r)

    p_metrics.send_signal(signal.SIGTERM)
    p_metrics.wait(timeout=10)

    # the Modbus per-IP gate: --max-conn-per-ip 1 refuses the second connection from one peer
    p_pip = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                              '--listen', '127.0.0.1:%d' % (15533 + BASE), '--interval', '1', '--profile', R,
                              '--max-clients', '0', '--max-conn-per-ip', '1', '--control-port', '%d' % (15534 + BASE),
                              '--control-token', 'sekrit'],
                             stdout=open('/tmp/reg_cache_pip.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(p_pip)
    time.sleep(1.5)
    g1 = socket.create_connection(('127.0.0.1', 15533 + BASE), timeout=5)
    g1.sendall(struct.pack('>HHHB', 1, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
    g1r = g1.recv(512)
    check('per-IP: the first connection serves', len(g1r) >= 10, g1r.hex() if g1r else 'empty')
    g2 = socket.create_connection(('127.0.0.1', 15533 + BASE), timeout=5)
    g2.settimeout(2)
    refused = False
    try:
        refused = g2.recv(64) == b''
    except OSError:
        refused = False
    check('per-IP: the second connection from the same IP is refused (EOF)', refused)
    check('per-IP: the first connection keeps serving', g1r[7:8] == b'\x03', g1r.hex())
    r = ctl_cmd('set max-conn-per-ip 2', 15534 + BASE)
    check('per-IP: raised live (the path form)', r.startswith('ok max-conn-per-ip=2'), r[:80])
    g2 = socket.create_connection(('127.0.0.1', 15533 + BASE), timeout=5)
    g2.sendall(struct.pack('>HHHB', 2, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
    g2r = g2.recv(512)
    check('per-IP: the second connection admitted after the raise', len(g2r) >= 10, g2r.hex() if g2r else 'empty')
    r = ctl_cmd('show max-conn-per-ip', 15534 + BASE)
    check('per-IP: the cap shows (the per-setting row)', r == 'ok max-conn-per-ip=2', r[:160])
    g1.close(); g2.close()
    p_pip.send_signal(signal.SIGTERM)
    p_pip.wait(timeout=10)

    # the metrics per-IP cap (the ledger's knob promise) and the log-cmd-replies
    # toggle: the live set/show/clear roundtrips on the main daemon
    r = ctl_cmd('set metrics-max-conn-per-ip 3', 15514 + BASE)
    check('metrics per-IP: raised live', r.startswith('ok metrics-max-conn-per-ip=3'), r[:100])
    r = ctl_cmd('show metrics-max-conn-per-ip', 15514 + BASE)
    check('metrics per-IP: the cap shows (the per-setting row)', r == 'ok metrics-max-conn-per-ip=3', r[:100])
    r = ctl_cmd('clear metrics-max-conn-per-ip', 15514 + BASE)
    check('metrics per-IP: clear restores the configured cap', r.startswith('ok metrics-max-conn-per-ip='), r[:100])
    r = ctl_cmd('set control-log-replies on', 15514 + BASE)
    check('log-cmd-replies: the live toggle takes (the flat wire spelling)', r.startswith('ok control-log-replies=on'), r[:100])
    r = ctl_cmd('show control-log-replies', 15514 + BASE)
    check('log-cmd-replies: the toggle shows (the per-setting row)', r == 'ok control-log-replies=on', r[:100])
    ctl_cmd('clear control-log-replies', 15514 + BASE)

    r_before = ctl_cmd('inspect', 15514 + BASE)
    ctl_cmd('set merge-gap 0', 15514 + BASE)
    r_after = ctl_cmd('inspect', 15514 + BASE)
    n_before = r_before.split('poll plan ')[1].split(' block(s)')[0]
    n_after = r_after.split('poll plan ')[1].split(' block(s)')[0]
    check('set merge-gap: the poll plan rebuilds live', int(n_after) > int(n_before),
          '%s -> %s' % (n_before, n_after))
    ctl_cmd('clear merge-gap', 15514 + BASE)

    r = ctl_cmd('set allow-write on', 15514 + BASE)
    check('set allow-write: the gate opens', r.startswith('ok allow-write=on'), r[:100])
    b = wr6(47415, 3, port=15513 + BASE)
    check('set allow-write: the forwarded write passes', b == bytes.fromhex('06b9370003'), b.hex())
    ctl_cmd('clear allow-write', 15514 + BASE)
    b = wr6(47415, 4, port=15513 + BASE)
    check('clear allow-write: the gate closes again', b[0] == 0x86 and b[1] == 1, b.hex())
    r = cli('shutdown\n\n', 15515 + BASE, {'CTL': '/tmp/modbus-cache-%d.socket' % (15515 + BASE)}, use_flag=False)
    time.sleep(1)
    check('cache_cli: RETURN at [confirm] stops the proxy', r.returncode == 0
          and 'bye shutdown' in r.stdout and p_unix.poll() == 0, repr(r.stdout))
    check('control: unix socket unlinked on shutdown', not os.path.exists('/tmp/modbus-cache-%d.socket' % (15515 + BASE)))
    if PROFILE == 'quick':
        raise QuickDone()   # quick: the core sections only
    # 6. FC4 input-register caching, the write allow-list, inspect,
    #    per-client REQUESTS accounting, the control token file
    fc4map = '/tmp/reg_fc4_profile.json'
    _json.dump({'description': 'fc4 device (mixed spaces)',
                'registers': [
                    {'name': 'pv-power', 'register': 32064, 'type': 'i32', 'fc': 3, 'cache': True},
                    {'name': 'meter-live', 'register': 40001, 'type': 'u32', 'fc': 4, 'cache': True},
                    {'name': 'coil-flag', 'register': 47400, 'type': 'bit', 'fc': 1, 'cache': True},
                ]}, open(fc4map, 'w'))
    # the allow-list rides the config script (the reloadable source: the env is frozen at start)
    ini4 = '/tmp/reg_fc4.conf'
    open(ini4, 'w').write('# the fc4 regtest config: the set grammar\n'
                          'set write-registers 47400:100,40001:2\n'
                          'set write-acl any\n')

    def rd4(addr, n, port=CACHE_PORT):
        return txn(struct.pack('>BHH', 4, addr, n), port)

    def wr5(addr, value, port=CACHE_PORT):
        return txn(struct.pack('>BHH', 5, addr, value), port)

    p_fc4 = start([sys.executable, P, '--config', ini4,
                    '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                   '--listen', '127.0.0.1:%d' % (15521 + BASE), '--interval', '1', '--cache-ttl', '3',
                   '--allow-write', '--control-port', '%d' % (15522 + BASE),
                   '--profile', fc4map, '--audit-log', '/tmp/reg_audit_fc4.log'],
                  log='/tmp/reg_fc4.log', env_extra={'REQUESTS_AUDIT': '1',
                                                     'CONTROL_TOKEN': 'sekrit'})
    time.sleep(2.5)
    b = rd(32064, 2, port=15521 + BASE)
    check('fc3 range polled and served', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    b = rd4(40001, 2, port=15521 + BASE)
    check('fc4 range polled and served from cache', b[0] == 4 and struct.unpack('>i', b[2:6])[0] == 0, b.hex())
    b = rd4(31000, 1, port=15521 + BASE)
    check('fc4 uncached register forwarded (device answers 0)', b[0] == 4 and struct.unpack('>H', b[2:4])[0] == 0, b.hex())
    forwards = subprocess.run(['grep', '-c', 'fc4 registers 31000:1 not cached', '/tmp/reg_fc4.log'],
                              capture_output=True, text=True).stdout.strip()
    b = rd4(31000, 1, port=15521 + BASE)
    forwards2 = subprocess.run(['grep', '-c', 'fc4 registers 31000:1 not cached', '/tmp/reg_fc4.log'],
                               capture_output=True, text=True).stdout.strip()
    check('fc4 forward cached on first pass', forwards == '1' and forwards2 == '1', '%s/%s' % (forwards, forwards2))
    b = rd4(65000, 1, port=15521 + BASE)
    forwards = subprocess.run(['grep', '-c', 'fc4 registers 65000:1 not cached', '/tmp/reg_fc4.log'],
                              capture_output=True, text=True).stdout.strip()
    check('fc4 65000 not synthetic -> forwarded to the device', b[0] == 4 and forwards == '1',
          '%s forwards=%s' % (b.hex(), forwards))
    b = rd(65000, 4, port=15521 + BASE)
    check('fc3 diagnostics block still synthesized', b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 0xCAFE, b.hex())

    # the bit space: the profile's fc1 entry is polled, cached and served;
    # the FC5 coil write passes the same allow-list and invalidates the
    # coil space (the repoll picks the new state)
    b = txn(struct.pack('>BHH', 1, 47400, 1), port=15521 + BASE)
    check('fc1 bit range polled and served from cache', b == bytes.fromhex('010100'), b.hex())
    b = wr5(47400, 0xFF00, port=15521 + BASE)
    check('fc5 coil write forwarded (echo)', b == bytes.fromhex('05b928ff00'), b.hex())
    time.sleep(0.5)
    b = txn(struct.pack('>BHH', 1, 47400, 1), port=15521 + BASE)
    check('fc5 write invalidates the coil space (the repoll serves the new state)',
          b == bytes.fromhex('010101'), b.hex())

    # the write allow-list: inside passes, outside refuses, a spanning write refuses
    b = wr6(47415, 7, port=15521 + BASE)
    check('write allow-list: register inside the range passes', b == bytes.fromhex('06b9370007'), b.hex())
    b = rd(47415, 1, port=15521 + BASE)
    check('write allow-list: value landed (fc06 readback)', struct.unpack('>H', b[2:4])[0] == 7)
    b = wr6(47999, 9, port=15521 + BASE)
    check('write allow-list: register outside refused (0x86/01)', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr16(47498, [1, 2, 3, 4], port=15521 + BASE)
    check('write allow-list: fc16 spanning the edge refused', b[0] == 0x90 and b[1] == 1, b.hex())

    # FC23 awareness: the gate vets the WRITE span (the second address
    # pair) — the read span riding first does not smuggle the write through
    b = txn(struct.pack('>BHHHH', 23, 47415, 2, 47999, 1) + struct.pack('>BH', 2, 5), port=15521 + BASE)
    check('write allow-list: fc23 write span outside refused (0x97/01)',
          b[0] == 0x97 and b[1] == 1, b.hex())
    check('write allow-list: the refused fc23 write is a WRITE-REFUSED naming the span',
          'registers 47999:1 = [5], read back 47415:2 (read/write multiple registers, unit 1) '
          '(registers outside the write allow-list)' in open('/tmp/reg_audit_fc4.log').read())
    b = txn(struct.pack('>BHHHH', 23, 47415, 2, 47498, 1) + struct.pack('>BH', 2, 5), port=15521 + BASE)
    fc4_log = open('/tmp/reg_fc4.log').read()
    check('write allow-list: fc23 spans inside pass the gate (the device answers)',
          b[0] == 0x97 and b[1] == 1
          and 'write: registers 47498:1 = [5], read back 47415:2 (read/write multiple registers, unit 1)' in fc4_log
          and 'write rejected by the device' in fc4_log, b.hex())

    # the named forward: a frame with no cache semantics is forwarded and
    # its function code named in the log
    b = txn(struct.pack('>B', 17), port=15521 + BASE)   # FC17 report slave id
    check('unknown-FC forward: the frame is named in the log',
          'forwarded FC17 (report slave id)' in open('/tmp/reg_fc4.log').read(), b.hex())

    # the bulk-write shape gate: an FC16 whose byte count lies about its
    # data is refused at the cache (exception 03), never forwarded
    b = txn(struct.pack('>BHHB', 16, 47400, 2, 3) + b'\x00\x00\x00', port=15521 + BASE)
    check('malformed fc16 (the byte count lies) -> exception 03 at the cache',
          b == bytes.fromhex('9003'), b.hex())
    check('malformed fc16: the WRITE-REFUSED names the inconsistency',
          'the byte count is 3, the register count needs 4' in open('/tmp/reg_audit_fc4.log').read(),
          open('/tmp/reg_audit_fc4.log').read()[-200:])
    # write-through invalidation now sweeps both register spaces: the fc4
    # copy of meter-live is dropped by an fc06 write to the same address
    b = rd4(40001, 2, port=15521 + BASE)
    b = wr6(40001, 7, port=15521 + BASE)
    check('write-through: an fc06 write to the fc4 range echoes (dual-space drop)',
          b == bytes.fromhex('069c410007'), b.hex())
    check('write-through: the fc4 copy invalidated, the repoll refills',
          'write: invalidated 1 cached word(s) at registers 40001:1, repolling'
          in open('/tmp/reg_fc4.log').read(), open('/tmp/reg_fc4.log').read()[-200:])

    # inspect: the pretty multi-line dump
    r = ctl_cmd('inspect', 15522 + BASE)
    check('control: inspect dumps state, map, write gate',
          r.startswith('ok inspect') and 'modbus-cache' in r and 'upstream  127.0.0.1:%d' % (15512 + BASE)
          and 'write-registers 47400:100' in r and 'fc4' in r, repr(r[:160]))
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    check('audit: WRITE + WRITE-REFUSED (allow-list) events',
          'tools=CACHE tag=daemon type=write' in fc4_audit and 'type=write-refused' in fc4_audit
          and 'outside the write allow-list' in fc4_audit, fc4_audit[-160:])

    # SIGHUP reloads the allow-list from the config script
    conf_txt = open(ini4).read().replace('set write-registers 47400:100', 'set write-registers 47600:100')
    open(ini4, 'w').write(conf_txt)
    os.kill(p_fc4.pid, signal.SIGHUP)
    time.sleep(1)
    b = wr6(47415, 8, port=15521 + BASE)
    check('SIGHUP: the reloaded allow-list refuses the old range', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(47615, 9, port=15521 + BASE)
    check('SIGHUP: the reloaded allow-list accepts the new range', b == bytes.fromhex('06b9ff0009'), b.hex())

    # reload: the whole-daemon restart that keeps the sets (a dedicated daemon):
    # the overrides save to the state file beside the config, the process
    # re-execs, the fresh daemon re-resolves the config (the file edit takes
    # effect — the restart-marked style) and re-applies the saved overrides once
    ini_r = '/tmp/reg_reload.conf'
    open(ini_r, 'w').write('# the reload regtest config: the set grammar\nset unit 4\n')
    p_r = start([sys.executable, P, '--config', ini_r, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                 '--listen', '127.0.0.1:%d' % (15581 + BASE), '--interval', '1', '--cache-ttl', '3',
                 '--control-port', '%d' % (15582 + BASE), '--profile', fc4map],
                log='/tmp/reg_reload.log', env_extra={'CONTROL_TOKEN': 'sekrit'})
    time.sleep(2)
    r = ctl_cmd('set interval 7', 15582 + BASE)
    check('reload: the override lands before the reload', r.startswith('ok interval=7'), r[:120])
    r = ctl_cmd('request reload', 15582 + BASE)
    check('reload: the reply reports the saved override', r.startswith('ok reload: 1 override(s) saved'), r[:120])
    back = None
    for _ in range(100):     # the exec is fast; a connect that lands on the dying daemon (the bye frame, unsigned) retries
        try:
            back = ctl_cmd('show interval', 15582 + BASE)
            break
        except Exception:
            time.sleep(0.1)
    check('reload: the daemon came back with the override re-applied (above the flag)',
          back is not None and back.startswith('ok interval=7.00s'), repr((back or '')[-200:]))
    check('reload: the state file is consumed', not os.path.exists(ini_r + '.reload'), ini_r + '.reload')
    # the startup-only override rides the reload: the set records the pending
    # value (the note), the fold lands it in the fresh process before the binds
    r = ctl_cmd('set listen 127.0.0.1:%d' % (15583 + BASE), 15582 + BASE)
    check('reload fold: the startup-only set answers the note',
          r.startswith('note restart required (startup-only knob)'), r[:90])
    r = ctl_cmd('show listen', 15582 + BASE)
    check('reload fold: show renders the recorded pending value',
          r.startswith('ok listen=127.0.0.1:%d' % (15583 + BASE)), r[:90])
    r = ctl_cmd('request reload', 15582 + BASE)
    check('reload fold: the reload saves both overrides', r.startswith('ok reload: 2 override(s) saved'), r[:120])
    back = None
    for _ in range(100):
        try:
            back = ctl_cmd('show listen', 15582 + BASE)
            break
        except Exception:
            time.sleep(0.1)
    check('reload fold: the fresh daemon kept the folded listen (the control port stayed)',
          back is not None and back.startswith('ok listen=127.0.0.1:%d' % (15583 + BASE)), repr(back))
    mod = socket.create_connection(('127.0.0.1', 15583 + BASE), timeout=5)   # the modbus socket moved with the fold
    mod.close()
    # F23: the reload state file is config-equivalent trust at rest — it is
    # created 0600 explicitly, never the umask's (white-box: the round above
    # consumes the file before a stat could land)
    r = subprocess.run([sys.executable, '-c', '''
import os, sys
sys.path.insert(0, %r)
sys.path.insert(0, %r)
import lib.control as C
class Stub(C.ControlServer):
    def __init__(self, key):
        self.config_path = '/tmp/reg_reload_mode.conf'
        self.overridden = {'interval'}
        class _Proxy:
            dump_key = key   # the reload state file seals only under dump-key
        self.proxy = _Proxy()
    def dump_settings(self):
        return {'interval': '7'}
Stub(None)._save_reload_state()
st = os.stat('/tmp/reg_reload_mode.conf.reload')
assert st.st_mode & 0o777 == 0o600, oct(st.st_mode)
plain = open('/tmp/reg_reload_mode.conf.reload').read()
os.unlink('/tmp/reg_reload_mode.conf.reload')
Stub('seal-key-9')._save_reload_state()
sealed = open('/tmp/reg_reload_mode.conf.reload').read()
os.unlink('/tmp/reg_reload_mode.conf.reload')
import json as _js
d = _js.loads(sealed)
assert d.get('version') == 2 and d.get('cipher') == 'sha256-ctr' and d.get('box') and d.get('mac'), d.keys()
assert 'interval' not in sealed and sealed.count('{') == 1, sealed[:120]
print('mode 0600 ok; the keyed state file seals (version 2, opaque)')
''' % (REPO, CACHE_DIR)], capture_output=True, text=True, timeout=15)
    check('reload: the state file saves 0600 (F23, the F18 posture) and seals under dump-key',
          r.returncode == 0 and 'mode 0600 ok' in r.stdout and 'state file seals' in r.stdout,
          repr((r.stderr or r.stdout)[-200:]))
    open(ini_r, 'w').write('# the reload regtest config: the set grammar\nset unit 7\n')   # rewrite: a name set twice fails the start
    r = ctl_cmd('request reload', 15582 + BASE)
    back = None
    for _ in range(100):
        try:
            back = ctl_cmd('show unit', 15582 + BASE)
            break
        except Exception:
            time.sleep(0.1)
    check('reload: the fresh resolve takes the config edit (unit=7), the override still rides',
          back is not None and back.startswith('ok unit=7')
          and ctl_cmd('show interval', 15582 + BASE).startswith('ok interval=7.00s'),
          repr((back or '')[-200:]))
    # the console path: the reload's bye frame rides utf-8 and the notice decodes it (no raw \u escapes)
    p = subprocess.Popen([sys.executable, K, '--control-port', '%d' % (15582 + BASE)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, 'CLI_KEEPALIVE': '0.2', 'CONTROL_TOKEN': 'sekrit'})
    time.sleep(1.0)
    p.stdin.write('request reload\n')
    p.stdin.flush()
    time.sleep(3.0)          # stdin stays open: the console lives at the prompt until the bye notice exits it
    out, _ = p.communicate(timeout=25)
    check('reload: the console prints the notice and exits clean (utf-8, no raw escapes)',
          p.returncode == 0 and 'daemon exit: the modbus-cache proxy is reloading' in out
          and '\u2014' in out and '\\u2014' not in out, repr(out[-160:]))
    back = None
    for _ in range(100):
        try:
            back = ctl_cmd('show version', 15582 + BASE)
            break
        except Exception:
            time.sleep(0.1)
    r = ctl_cmd('shutdown', 15582 + BASE)
    check('reload: the re-execed daemon still shuts down clean', r.startswith('bye shutdown'), r[:80])

    # the 'none' modes: the write path defaults fully closed (write-acl none +
    # write-registers none — --allow-write alone refuses every write); the
    # connect ACL's none refuses every connection at accept
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
           '--listen', '127.0.0.1:%d' % (15531 + BASE), '--interval', '1', '--profile', R,
           '--allow-write', '--control-port', '%d' % (15532 + BASE), '--control-token', 'sekrit'],
          log='/tmp/reg_none.log')
    time.sleep(2)
    none_log = open('/tmp/reg_none.log').read()
    check('defaults logged: write acl none, allow-list none',
          'connect acl: any' in none_log and 'write acl: none' in none_log
          and 'write allow-list: none' in none_log, none_log[:240])
    b = wr6(47415, 5, port=15531 + BASE)
    check('write-acl none (the default): the write is refused', b[0] == 0x86 and b[1] == 1, b.hex())
    none_log = open('/tmp/reg_none.log').read()
    check('write-acl none: the refusal names the ACL',
          'not on the write ACL' in none_log)
    r = ctl_cmd('set write-acl any', 15532 + BASE)
    check('write-acl any: the write is still refused (write-registers none)',
          r.startswith('ok write-acl=any'), r[:80])
    b = wr6(47415, 5, port=15531 + BASE)
    check('write-registers none: refused via the allow-list', b[0] == 0x86 and b[1] == 1, b.hex())
    r = ctl_cmd('set write-registers any', 15532 + BASE)
    b = wr6(47415, 5, port=15531 + BASE)
    check('write-acl any + write-registers any: the write passes',
          b == bytes.fromhex('06b9370005'), b.hex())
    r = ctl_cmd('clear write-acl', 15532 + BASE)
    check('clear write-acl restores the default none', r.startswith('ok write-acl=none'), r[:80])
    b = wr6(47415, 5, port=15531 + BASE)
    check('write-acl none again: refused', b[0] == 0x86 and b[1] == 1, b.hex())

    # the alias: the row's second CONSOLE spelling — the cli translates it
    # to the flat name before it sends (the wire itself takes no alias)
    r = ctl_cmd('show write-acl', 15532 + BASE)
    check('alias: show write-acl (the flat wire name) answers', r.startswith('ok write-acl=none'), r[:80])
    r = cli('set write acl any\nquit\n', port=15532 + BASE)
    check('alias: the cli translates the alias spelling (set write acl any)', r.returncode == 0
          and '\ncache:%d > ' % (15532 + BASE) in r.stdout, repr(r.stdout[-200:]))
    b = wr6(47415, 5, port=15531 + BASE)
    check('alias: the write passes through the aliased set', b == bytes.fromhex('06b9370005'), b.hex())
    r = cli('clear write acl\nshow write-acl\nquit\n', port=15532 + BASE)
    check('alias: the cli translates the alias clear', r.returncode == 0, repr(r.stdout[-200:]))
    r = ctl_cmd('show write-acl', 15532 + BASE)
    check('alias: clear write acl restores none', r.startswith('ok write-acl=none'), r[:80])
    r = cli('write ?\nquit\n', port=15532 + BASE)
    check('alias: the cli ? lists the aliased row under the walk-on, the ? shape',
          'clients allowed to write (requires allow-write)' in r.stdout
          and '(the alias of write-acl)' in r.stdout, repr(r.stdout[-300:]))
    r = ctl_cmd('help write-acl', 15532 + BASE)
    check('alias: help write-acl describes the row', r.startswith('ok write-acl -'), r[:80])
    r = ctl_cmd('show write', 15532 + BASE)
    check('write node: the listing answers the flat names (the alias lists on the cli only)',
          'write-registers' in r and 'write-registers-table' in r and 'write-acl' not in r, r[:200])

    # the profile write acl: --write-registers profile compiles the device
    # profile's write-acl rule chain (the whitelist: the last matching rule
    # decides, a register no rule decides refuses) — the deye profile allows
    # the TOU schedule slots (148-177) and the grid-start registers (127-128)
    deye = os.path.join(REPO, 'profiles', 'profiles', 'deye-sg05lp3.json')
    start([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15584 + BASE), '--profile', deye,
           '--control-port', '0', '--allow-write'], log='/tmp/reg_deye_fake.log')
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
           '--listen', '127.0.0.1:%d' % (15585 + BASE), '--interval', '1', '--profile', 'deye-sg05lp3',
           '--allow-write', '--write-acl', 'any', '--write-registers', 'profile',
           '--control-port', '%d' % (15586 + BASE), '--control-token', 'sekrit'],
          log='/tmp/reg_profile_acl.log')
    time.sleep(2)
    b = wr6(127, 55, port=15585 + BASE)
    check('profile acl: grid-start register 127 passes', b == bytes.fromhex('06007f0037'), b.hex())
    b = wr6(130, 1, port=15585 + BASE)
    check('profile acl: register 130 refused', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr16(148, [600, 1300] + [0] * 28, port=15585 + BASE)
    check('profile acl: the TOU span 148:30 passes', b[:3] == bytes.fromhex('100094'), b.hex())
    b = wr16(148, [0] * 31, port=15585 + BASE)
    check('profile acl: a write spanning past 177 refused', b[0] == 0x90 and b[1] == 1, b.hex())
    pal_log = open('/tmp/reg_profile_acl.log').read()
    check('profile acl: the refusal names the profile gate',
          'outside the write allow-list profile (127:2,148:30)' in pal_log, pal_log[-200:])
    r = ctl_cmd('show write-registers', 15586 + BASE)
    check('profile acl: show answers the profile spelling', r == 'ok write-registers=profile', r[:80])
    r = ctl_cmd('show write-registers-table', 15586 + BASE)
    check('profile acl: the show report renders the profile rules (the comments aligned)',
          r == 'ok write-registers-table\n'
               '% Time-of-Use schedule slots (148-177) and operational mode registers (127-128)\n'
               'allow 127:2  # operational mode registers\n'
               'allow 148:30 # Time-of-Use schedule slots', repr(r[:220]))
    r = ctl_cmd('show write-registers-table', 15586 + BASE)
    check('profile acl: the word spelling answers the same report',
          r.startswith('ok write-registers-table'), r[:80])
    r = ctl_cmd('set write-registers 100:1', 15586 + BASE)
    check('profile acl: explicit ranges still set', r.startswith('ok write-registers=100:1'), r[:80])
    r = ctl_cmd('show write-registers-table', 15586 + BASE)
    check('profile acl: a range knob renders as its whitelist',
          r == 'ok write-registers-table\ndeny any\nallow 100:1', repr(r[:80]))
    b = wr6(130, 1, port=15585 + BASE)
    check('profile acl: the explicit range gates instead', b[0] == 0x86 and b[1] == 1, b.hex())
    r = ctl_cmd('set write-registers none', 15586 + BASE)
    check('profile acl: the none knob renders deny any',
          r.startswith('ok write-registers=none')
          and ctl_cmd('show write-registers-table', 15586 + BASE) == 'ok write-registers-table\ndeny any', r[:80])
    r = ctl_cmd('set write-registers any', 15586 + BASE)
    check('profile acl: the any knob renders allow any',
          r.startswith('ok write-registers=any')
          and ctl_cmd('show write-registers-table', 15586 + BASE) == 'ok write-registers-table\nallow any', r[:80])
    r = ctl_cmd('clear write-registers', 15586 + BASE)
    check('profile acl: clear restores the configured profile mode',
          r.startswith('ok write-registers=profile'), r[:80])
    r = ctl_cmd('set write-registers profile', 15586 + BASE)
    check('profile acl: the wire set answers the profile spelling',
          r.startswith('ok write-registers=profile'), r[:80])
    r = ctl_cmd('set write-registers profile any', 15586 + BASE)
    check('profile acl: a value past the profile word is a clean err (the show path never shadows the knob value)',
          r.startswith('fail write-registers entries must be START:COUNT'), r[:80])

    # the deny side: a profile copy with allow any + the deye spans denied —
    # everything EXCEPT 127-128/148-177 becomes writable
    deny_prof = '/tmp/reg_deye_deny.json'
    with open(deye) as fh:
        dj = _json.load(fh)
    dj['acl'] = {'write': {'rules': [
        {'type': 'allow', 'range': 'any'},
        {'type': 'deny', 'range': ['127:2', '148:30'], 'desc': 'the deye write spans'},
    ]}}
    with open(deny_prof, 'w') as fh:
        _json.dump(dj, fh)
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
           '--listen', '127.0.0.1:%d' % (15587 + BASE), '--interval', '1', '--profile', deny_prof,
           '--allow-write', '--write-acl', 'any', '--write-registers', 'profile',
           '--control-port', '%d' % (15588 + BASE), '--control-token', 'sekrit'],
          log='/tmp/reg_profile_deny.log')
    time.sleep(2)
    b = wr6(200, 1, port=15587 + BASE)
    check('profile acl deny: register 200 passes (allow any)',
          b == bytes.fromhex('0600c80001'), b.hex())
    b = wr6(127, 1, port=15587 + BASE)
    check('profile acl deny: the denied 127:2 refused', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(148, 1, port=15587 + BASE)
    check('profile acl deny: the denied 148:30 refused', b[0] == 0x86 and b[1] == 1, b.hex())
    pdl_log = open('/tmp/reg_profile_deny.log').read()
    check('profile acl deny: the refusal names the carved gate',
          'outside the write allow-list profile (0:127,129:19,178:65358)' in pdl_log, pdl_log[-200:])
    r = ctl_cmd('show write-registers-table', 15588 + BASE)
    check('profile acl deny: the show report renders the deny chain (the comments aligned)',
          r == 'ok write-registers-table\n'
               'allow any\n'
               'deny 127:2  # the deye write spans\n'
               'deny 148:30 # the deye write spans', repr(r[:160]))

    # the rule-chain form: the last matching rule decides, an undecided
    # register refuses (default deny any — the chain is a whitelist) — the
    # deny-any chain opens from a clean slate
    for name, gate in [('clean', [{'type': 'deny', 'range': 'any'}, {'type': 'allow', 'range': '148:30'}]),
                       ('reopen', [{'type': 'allow', 'range': 'any'}, {'type': 'deny', 'range': '148:30'},
                                   {'type': 'allow', 'range': '148:1'}])]:
        cp = '/tmp/reg_deye_%s.json' % name
        with open(deye) as fh:
            dj = _json.load(fh)
        dj['acl'] = {'write': {'rules': gate}}
        with open(cp, 'w') as fh:
            _json.dump(dj, fh)
        start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
               '--listen', '127.0.0.1:%d' % (15590 if name == 'clean' else 15591),
               '--interval', '1', '--profile', cp,
               '--allow-write', '--write-acl', 'any', '--write-registers', 'profile'],
              log='/tmp/reg_profile_%s.log' % name)
    time.sleep(2)
    b = wr6(148, 1, port=15590 + BASE)
    check('profile acl chain (clean slate): the allowed span passes', b[0] == 6, b.hex())
    b = wr6(130, 1, port=15590 + BASE)
    check('profile acl chain (clean slate): an undecided register refuses', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(148, 1, port=15591 + BASE)
    check('profile acl chain (re-open): 148 re-allowed by the last rule', b[0] == 6, b.hex())
    b = wr6(160, 1, port=15591 + BASE)
    check('profile acl chain (re-open): the denied span refuses', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(200, 1, port=15591 + BASE)
    check('profile acl chain (re-open): outside the deny passes', b[0] == 6, b.hex())

    # a profile without the acl section refuses the profile value, at start
    p = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
                        '--listen', '127.0.0.1:%d' % (15589 + BASE), '--profile', R,
                        '--write-registers', 'profile', '--dry-run'],
                       capture_output=True, text=True, timeout=60)
    check('profile acl: a profile without the section fails the start',
          p.returncode == 1 and 'carries no "acl"/"write" gate' in p.stderr, '%s %r' % (p.returncode, p.stderr[-120:]))

    # the standalone acl file: --write-registers file:<path> — the file IS
    # the gate object (what a profile carries under write-acl), read and
    # compiled at start and on every set, the whitelist semantics the same
    aclf = '/tmp/reg_acl_file.json'
    with open(aclf, 'w') as fh:
        _json.dump({'desc': 'the regtest gate',
                    'rules': [{'type': 'allow', 'range': '148:30', 'desc': 'the TOU slots'},
                              {'type': 'deny', 'range': '148:1', 'desc': 'carved back'}]}, fh)
    os.chmod(aclf, 0o644)   # group/world-readable: the permission warning fires at start and on the set/clear replies
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
           '--listen', '127.0.0.1:%d' % (15600 + BASE), '--interval', '1',
           '--allow-write', '--write-acl', 'any', '--write-registers', 'file:' + aclf,
           '--control-port', '15601', '--control-token', 'sekrit',
           '--audit-log', '/tmp/reg_acl_audit.log'],
          log='/tmp/reg_acl_file.log')
    time.sleep(2)
    acl_start_log = open('/tmp/reg_acl_file.log').read()
    check('acl file: a group/world-readable file warns at start',
          'the acl file %s is group/world-readable, mode 644 — chmod 0600' % aclf in acl_start_log,
          acl_start_log[-200:])
    acl_audit = open('/tmp/reg_acl_audit.log').read()
    check('acl file: the warning lands in the audit trail (ACL-FILE)',
          'ACL-FILE' in acl_audit and 'group/world-readable' in acl_audit, acl_audit[-200:])
    b = wr6(149, 1, port=15600)
    check('acl file: 149 passes (the allow 148:30)', b[0] == 6, b.hex())
    b = wr6(148, 1, port=15600)
    check('acl file: 148 refused by the deny carve', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(200, 1, port=15600)
    check('acl file: 200 refused (the whitelist default deny)', b[0] == 0x86 and b[1] == 1, b.hex())
    r = ctl_cmd('show write-registers', 15601)
    check('acl file: show answers the file spelling (re-appliable)',
          r == 'ok write-registers=file:%s' % aclf, r[:120])
    r = ctl_cmd('show write-registers-table', 15601)
    check('acl file: the show report renders the file rules (the comments aligned)',
          r == 'ok write-registers-table\n'
               '% the regtest gate\n'
               'allow 148:30 # the TOU slots\n'
               'deny 148:1   # carved back', repr(r[:160]))
    r = ctl_cmd('set write-registers file:%s' % aclf, 15601)
    check('acl file: the set reply carries the permission warning',
          r.startswith('ok write-registers=file:%s' % aclf)
          and 'the acl file %s is group/world-readable, mode 644 — chmod 0600' % aclf in r, r[:200])
    os.chmod(aclf, 0o600)
    r = ctl_cmd('clear write-registers', 15601)
    check('acl file: a 0600 acl file is silent (the clear restores the file gate)',
          r.startswith('ok write-registers=file:%s' % aclf)
          and 'group/world-readable' not in r, r[:160])
    r = ctl_cmd('set write-registers file:/nonexistent/acl.json', 15601)
    check('acl file: a bad file is a clean err, the old gate stands',
          r.startswith('fail cannot read acl file /nonexistent/acl.json')
          and ctl_cmd('show write-registers', 15601) == 'ok write-registers=file:%s' % aclf, r[:120])
    r = ctl_cmd('set write-registers 100:1', 15601)
    check('acl file: the explicit ranges take over', r.startswith('ok write-registers=100:1'), r[:80])
    r = ctl_cmd('clear write-registers', 15601)
    check('acl file: clear restores the configured file gate',
          r.startswith('ok write-registers=file:%s' % aclf), r[:100])
    p = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
                        '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                        '--write-registers', 'file:/nonexistent/acl.json', '--dry-run'],
                       capture_output=True, text=True, timeout=60)
    check('acl file: a bad file fails the start',
          p.returncode == 1 and 'cannot read acl file /nonexistent/acl.json' in p.stderr,
          '%s %r' % (p.returncode, p.stderr[-120:]))
    p = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
                        '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                        '--write-registers', 'file:' + os.path.join(REPO, 'examples', 'acl-write-registers.json'),
                        '--dry-run'],
                       capture_output=True, text=True, timeout=60)
    check('acl file: the shipped example loads (the deye gate)',
          p.returncode == 0 and 'dry-run: configuration and register map are valid' in (p.stdout + p.stderr),
          '%s %r' % (p.returncode, (p.stdout + p.stderr)[-120:]))

    # the matcher grammar: a range, a list of ranges, or the word any —
    # the range-map form and the none word refuse
    for what, matcher in [('the range-map matcher', {'148:18': 'the TOU slots'}),
                          ('the none word', 'none')]:
        badf = '/tmp/reg_acl_bad_matcher.json'
        with open(badf, 'w') as fh:
            _json.dump({'rules': [{'type': 'allow', 'range': matcher}]}, fh)
        p = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
                            '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                            '--write-registers', 'file:' + badf, '--dry-run'],
                           capture_output=True, text=True, timeout=60)
        check('acl file: %s refuses (a range, a list of ranges, or "any")' % what,
              p.returncode == 1 and 'must be' in p.stderr,
              '%s %r' % (p.returncode, p.stderr[-160:]))


    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
           '--listen', '127.0.0.1:%d' % (15539 + BASE), '--interval', '1', '--profile', R,
           '--connect-acl', 'none', '--control-port', '%d' % (15540 + BASE), '--control-token', 'sekrit'],
          log='/tmp/reg_noconn.log')
    time.sleep(2)
    try:
        b = rd(32064, 2, port=15539 + BASE)
        ok = False
    except (ConnectionError, OSError):
        ok = True
    check('connect-acl none: the connection is rejected at accept', ok)
    r = ctl_cmd('set connect-acl any', 15540 + BASE)
    check('set connect-acl any', r.startswith('ok connect-acl=any'), r[:80])
    b = rd(32064, 2, port=15539 + BASE)
    check('connect-acl any: the client connects again',
          b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())

    # the connect-acl + write-acl file: gates — the standalone ip-prefix
    # acl file (the chain: the last matching rule decides, no match denies,
    # the matcher word any = 0.0.0.0/0); the table shows spell either ACL
    # one entry per line
    aclc = '/tmp/reg_acl_connect.json'
    with open(aclc, 'w') as fh:
        _json.dump({'desc': 'the lab connect policy', 'type': 'ip-prefix', 'rules': [
            {'type': 'allow', 'prefix': '127.0.0.0/8', 'desc': 'the loopback lab'}]}, fh)
    r = ctl_cmd('set connect-acl file:%s' % aclc, 15540)
    check('acl connect: the file: gate sets (the reference is the reply)',
          r.startswith('ok connect-acl=file:%s' % aclc), r[:120])
    b = rd(32064, 2, port=15539 + BASE)
    check('acl connect file: the peer the allow rule decides serves',
          b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    r = ctl_cmd('show connect-acl-table', 15540 + BASE)
    check('acl connect table: the file gate renders its rules',
          r == 'ok acl-connect-table\n'
               '% the lab connect policy\n'
               'allow 127.0.0.0/8 # the loopback lab', repr(r[:160]))
    with open(aclc, 'w') as fh:   # the gate re-reads on every set: the whole-space deny refuses now
        _json.dump({'desc': 'the lab connect policy', 'type': 'ip-prefix', 'rules': [
            {'type': 'allow', 'prefix': '127.0.0.0/8', 'desc': 'the loopback lab'},
            {'type': 'deny', 'prefix': 'any', 'desc': 'the clean slate wins: the last match decides'}]}, fh)
    r = ctl_cmd('set connect-acl file:%s' % aclc, 15540)
    check('acl connect file: the re-set takes the new chain', r.startswith('ok connect-acl=file:'), r[:120])
    try:
        b = rd(32064, 2, port=15539 + BASE)
        ok = False
    except (ConnectionError, OSError):
        ok = True
    check('acl connect file: the deny-any last rule refuses the peer', ok)
    r = ctl_cmd('show connect-acl-table', 15540 + BASE)
    check('acl connect table: the any matcher spells 0.0.0.0/0',
          'deny 0.0.0.0/0' in r and 'the clean slate wins: the last match decides' in r, r[:200])
    r = ctl_cmd('set connect-acl file:/tmp/reg_acl_missing-%d.json' % PORT, 15540)
    check('acl connect: a missing acl file answers err, the old gate stands',
          r.startswith('fail cannot read acl file')
          and ctl_cmd('show connect-acl', 15540 + BASE).startswith('ok connect-acl=file:%s' % aclc), r[:120])
    with open(aclc, 'w') as fh:   # restore the allow-only gate
        _json.dump({'desc': 'the lab connect policy', 'type': 'ip-prefix', 'rules': [
            {'type': 'allow', 'prefix': '127.0.0.0/8', 'desc': 'the loopback lab'}]}, fh)
    ctl_cmd('set connect-acl file:%s' % aclc, 15540)
    # the write acl speaks the same grammar (the file gate)
    r = ctl_cmd('set write-acl file:%s' % aclc, 15540)
    check('acl write: the file: gate sets', r.startswith('ok write-acl=file:%s' % aclc), r[:120])
    r = ctl_cmd('show write-acl-table', 15540 + BASE)
    check('acl write table: the file gate renders its rules',
          r.startswith('ok acl-write-table') and 'allow 127.0.0.0/8 # the loopback lab' in r, r[:160])
    r = ctl_cmd('clear write-acl', 15540 + BASE)
    check('clear write-acl restores the default none', r.startswith('ok write-acl=none'), r[:80])
    # the system forms spell the chain they implement
    r = ctl_cmd('show connect-acl-table', 15540 + BASE)
    check('acl connect table: the file gate still renders (clear write untouched)',
          r.startswith('ok acl-connect-table') and 'allow 127.0.0.0/8' in r, r[:120])
    r = ctl_cmd('set connect-acl any', 15540 + BASE)
    r = ctl_cmd('show connect-acl-table', 15540 + BASE)
    check('acl connect table: any spells allow 0.0.0.0/0',
          r == 'ok acl-connect-table\nallow 0.0.0.0/0', repr(r[:80]))
    r = ctl_cmd('set connect-acl 127.0.0.0/8,10.48.0.0/16', 15540 + BASE)
    check('acl connect: the network list sets', r.startswith('ok connect-acl=127.0.0.0/8,10.48.0.0/16'), r[:120])
    r = ctl_cmd('show connect-acl-table', 15540 + BASE)
    check('acl connect table: the whitelist spells deny any + the allows',
          r == 'ok acl-connect-table\ndeny 0.0.0.0/0\nallow 127.0.0.0/8\nallow 10.48.0.0/16', repr(r[:120]))
    r = ctl_cmd('clear connect-acl', 15540 + BASE)
    check('acl connect: clear restores the configured default (none here)',
          r.startswith('ok connect-acl=none'), r[:120])
    ctl_cmd('set connect-acl any', 15540 + BASE)
    r = ctl_cmd('set connect-acl none', 15540 + BASE)
    r = ctl_cmd('show connect-acl-table', 15540 + BASE)
    check('acl connect table: none spells deny 0.0.0.0/0',
          r == 'ok acl-connect-table\ndeny 0.0.0.0/0', repr(r[:80]))
    r = ctl_cmd('set connect-acl table', 15540 + BASE)
    check('acl connect: the show word table is not a value (the pointer to the report)',
          r.startswith('fail') and '"table" is not a connect-acl value' in r
          and 'show connect-acl-table' in r, r[:160])
    r = ctl_cmd('set write-acl table', 15540 + BASE)
    check('acl write: the show word table is not a value (the pointer to the report)',
          r.startswith('fail') and 'show write-acl-table' in r, r[:160])
    ctl_cmd('set connect-acl any', 15540 + BASE)

    # the write-registers file: reader checks the gate schema: an
    # ip-prefix gate refuses (this reader takes the write-registers gate)
    badk = '/tmp/reg_acl_wrong_kind.json'
    with open(badk, 'w') as fh:
        _json.dump({'type': 'ip-prefix', 'rules': [{'type': 'allow', 'prefix': '10.0.0.0/8'}]}, fh)
    p = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
                        '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                        '--write-registers', 'file:' + badk, '--dry-run'],
                       capture_output=True, text=True, timeout=60)
    check('acl file: an ip-prefix gate refuses the write-registers reader (the schema check)',
          p.returncode == 1 and 'this reader takes the write-registers gate' in p.stderr,
          '%s %r' % (p.returncode, p.stderr[-160:]))
    # and the ip-prefix reader takes it: the connect acl file the example ships
    p = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15584 + BASE),
                        '--listen', '127.0.0.1:%d' % (15600 + BASE), '--profile', R,
                        '--connect-acl', 'file:' + os.path.join(REPO, 'examples', 'acl-ip-prefix.json'),
                        '--dry-run'],
                       capture_output=True, text=True, timeout=60)
    check('acl connect: the shipped ip-prefix example loads (dry-run)',
          p.returncode == 0 and 'dry-run: configuration and register map are valid' in (p.stdout + p.stderr),
          '%s %r' % (p.returncode, (p.stdout + p.stderr)[-120:]))

    # a write frame too short to carry an address fails CLOSED (the
    # allow-list cannot vet what it cannot parse)
    b = txn(b'\x06', port=15521 + BASE)          # FC6 with no address: forwarded before the fix
    check('write allow-list: an unparseable write frame is refused (fail closed)',
          b == bytes.fromhex('8603'), b.hex())
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    check('audit: the unparseable write is a WRITE-REFUSED event',
          'WRITE-REFUSED' in fc4_audit and 'too short to carry a register address' in fc4_audit,
          fc4_audit[-160:])

    # the audit trail folds control characters: a \n inside a command cannot
    # forge a second, attacker-crafted trail line
    r = ctl_cmd('show version\n2026-01-01T00:00:00Z AUDIT CACHE WRITE forged line', 15522 + BASE)
    check('control: the injection attempt is a clean err', r.startswith('fail unknown command'), r[:100])
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    forged = [line for line in fc4_audit.splitlines() if 'AUDIT CACHE WRITE forged' in line]
    check('audit: the trail injection folds to one physical line',
          forged and all('COMMAND' in line and line.startswith('2026-11-') for line in forged),
          str(forged[-1:]))

    # per-client REQUESTS accounting: the periodic tally + the disconnect line
    s = socket.create_connection(('127.0.0.1', 15521 + BASE), timeout=5)
    for _ in range(3):
        s.sendall(struct.pack('>HHHB', 77, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
        s.recv(64)
    time.sleep(1.2)          # > the 1s REQUESTS audit period: the periodic tally fires
    s.close()
    time.sleep(0.5)
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    check('audit: per-client REQUESTS tallies (periodic + disconnect)',
          'tools=CACHE tag=daemon type=requests' in fc4_audit and 'peer=127.0.0.1:' in fc4_audit
          and '(last 1s:' in fc4_audit and 'connected=' in fc4_audit, fc4_audit[-160:])

    # the control token as a file: reference (the LoadCredential pattern);
    # the file must be owner-only 0600 (F12 in docs/AUDIT.md)
    tokfile = '/tmp/reg_token_file'
    open(tokfile, 'w').write('tokensecret\n')
    os.chmod(tokfile, 0o600)
    p_tok = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                              '--listen', '127.0.0.1:%d' % (15523 + BASE), '--interval', '1', '--profile', fc4map,
                              '--control-port', '%d' % (15524 + BASE), '--control-token', 'file:' + tokfile],
                             stdout=open('/tmp/reg_tok.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(p_tok)
    time.sleep(1.5)
    r = subprocess.run([sys.executable, ctl, '--control-port', '%d' % (15524 + BASE),
                        '--control-token', 'file:' + tokfile, 'show', 'version'],
                       capture_output=True, text=True, timeout=15)
    check('token file: cache_ctl authenticates with the file: reference', r.returncode == 0
          and r.stdout.startswith('ok modbus-cache'), repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '%d' % (15524 + BASE), 'show', 'version'],
                       capture_output=True, text=True, timeout=15,
                       env={**os.environ, 'CONTROL_TOKEN': 'file:' + tokfile})
    check('token file: cache_ctl honors CONTROL_TOKEN=file:...', r.returncode == 0
          and r.stdout.startswith('ok modbus-cache'), repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '%d' % (15524 + BASE), 'show', 'version'],
                       capture_output=True, text=True, timeout=15)
    check('token file: token-less ctl refused', r.returncode == 0
          and '% error: authenticate first' in r.stdout, repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE), '--listen', '127.0.0.1:%d' % (15525 + BASE),
                        '--control-token', 'file:/tmp/reg_no_such_token_file', '--dry-run'],
                       capture_output=True, text=True, timeout=15)
    check('token file: a missing reference fails fast, one line', r.returncode != 0
          and 'cannot read control-token' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
    lax = '/tmp/reg_token_file_lax'
    open(lax, 'w').write('laxsecret\n')                                 # the umask default (0644)
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE), '--listen', '127.0.0.1:%d' % (15525 + BASE),
                        '--control-token', 'file:' + lax, '--dry-run'],
                       capture_output=True, text=True, timeout=15)
    check('token file: a group/world-readable file refuses to start (F12)',
          r.returncode != 0 and '0600' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))

    # the audit-finding refusals (F5/F13 in docs/AUDIT.md): the token-less
    # TCP control refuses to start; the metrics endpoint serves tokenless
    # on the loopback default and refuses beyond loopback without a token
    # (the F13 posture — the scraper's golden shape, the cache conformed)
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE), '--dry-run',
                        '--listen', '127.0.0.1:%d' % (15599 + BASE), '--control-port', '%d' % (15599 + BASE), '--profile', R],
                       capture_output=True, text=True, timeout=15)
    check('control: a TCP control port without a token refuses to start',
          r.returncode != 0 and 'TCP control port' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE), '--dry-run',
                        '--listen', '127.0.0.1:%d' % (15599 + BASE), '--metrics-listen', '127.0.0.1:%d' % (15598 + BASE), '--metrics-server', '--profile', R],
                       capture_output=True, text=True, timeout=15)
    check('metrics: the loopback endpoint serves without a token (the F13 shape)',
          r.returncode == 0 and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE), '--dry-run',
                        '--listen', '127.0.0.1:%d' % (15599 + BASE), '--metrics-listen', '0.0.0.0:15598', '--metrics-server', '--profile', R],
                       capture_output=True, text=True, timeout=15)
    check('metrics: a non-loopback endpoint without a token refuses to start (F13)',
          r.returncode != 0 and 'refusing to expose /metrics beyond loopback' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15512 + BASE), '--dry-run',
                        '--listen', '127.0.0.1:%d' % (15599 + BASE), '--metrics-listen', '0.0.0.0:15598', '--metrics-server',
                        '--metrics-token', 'sekrit', '--profile', R],
                       capture_output=True, text=True, timeout=15)
    check('metrics: a non-loopback endpoint with a token starts',
          r.returncode == 0 and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))
    mtc = '/tmp/reg_metrics_token.conf'
    open(mtc, 'w').write('# the token rides the config layer\n'
                         'set metrics-token sekrit\n')
    r = subprocess.run([sys.executable, P, '--config', mtc, '--upstream', '127.0.0.1:%d' % (15512 + BASE), '--dry-run',
                        '--listen', '127.0.0.1:%d' % (15599 + BASE), '--metrics-listen', '0.0.0.0:15598', '--metrics-server', '--profile', R],
                       capture_output=True, text=True, timeout=15)
    check('metrics: a non-loopback endpoint with the config-file token starts (the full ladder)',
          r.returncode == 0 and '(bearer token)' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))

    # the paste-back gate: a rendered `set <secret> *** SECRET REMOVED ***`
    # line refuses to parse — the placeholder is never a value
    ph = '/tmp/reg_placeholder.conf'
    open(ph, 'w').write('# the rendered script pasted back\n'
                        'set control token *** SECRET REMOVED ***\n')
    r = subprocess.run([sys.executable, P, '--config', ph, '--upstream', '127.0.0.1:%d' % (15512 + BASE),
                        '--listen', '127.0.0.1:%d' % (15599 + BASE), '--dry-run'],
                       capture_output=True, text=True, timeout=15)
    check('config: a *** SECRET REMOVED *** line refuses to parse (pass the secret by flag/env, or as file:<path)',
          r.returncode != 0 and 'not a value' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))

    # 6b-9. the suite auth, both legs: the cache demands the handshake from
    #       its own clients (--auth/--auth-key) and presents it upstream
    #       (--auth-upstream/--auth-upstream-key) — one round trip after
    #       every connect, OK opens the session, ERR kills it
    sys.path.insert(0, REPO)
    from common.modbus import auth_handshake_client

    AUTH_FAKE, AUTH_PORT, AUTH_CTL = 15561, 15562, 15563
    CL_KEY, UP_KEY = 'cl-suite-key-16chars!', 'up-suite-key-16chars!'
    start([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (AUTH_FAKE), '--control-port', '0',
           '--modbus-auth', 'suite', '--auth-key', UP_KEY])
    time.sleep(0.7)
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
           '--listen', '127.0.0.1:%d' % AUTH_PORT, '--profile', R,
           '--timeout', '1', '--interval', '2',
           '--control-port', str(AUTH_CTL), '--control-token', 'ctok-a',
           '--modbus-auth', 'suite', '--auth-key', CL_KEY,
           '--auth-upstream', 'suite', '--auth-upstream-key', UP_KEY],
          log='/tmp/reg_auth_cache.log')
    time.sleep(1.2)

    def ctl_auth(*cmds):
        r = subprocess.run([sys.executable, os.path.join(CACHE_DIR, 'bin', 'modbus-cache-ctl.py'),
                            '--control-port', str(AUTH_CTL), '--control-token', 'ctok-a'] + list(cmds),
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()

    c = socket.create_connection(('127.0.0.1', AUTH_PORT), timeout=5)
    c.settimeout(5)
    auth_handshake_client(c, CL_KEY)
    c.sendall(struct.pack('>HHHB', 9, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 2))
    head = _recvn(c, 7)
    body = _recvn(c, struct.unpack('>HHH', head[:6])[2] - 1)
    check('suite auth: the proved client reads through the cache',
          body[0] == 3 and body[1] == 4, body.hex())
    c.close()
    r = ctl_auth('show', 'modbus-auth')
    check('suite auth: the per-setting show carries auth=', r == 'ok modbus-auth=suite', r[:120])
    r = ctl_auth('show', 'auth-upstream')
    check('suite auth: the per-setting show carries auth-upstream=', r == 'ok auth-upstream=suite', r[:120])
    ins = ctl_auth('inspect')
    check('suite auth: the poll is healthy (no FAILING mark)',
          'upstream' in ins and '(FAILING)' not in ins, ins[:200])
    c = socket.create_connection(('127.0.0.1', AUTH_PORT), timeout=5)
    c.sendall(b'\x00' * 52)     # 52 bytes that are not the handshake
    c.settimeout(5)
    verdict = c.recv(3)
    after = c.recv(4096)
    c.close()
    check('suite auth: a non-handshake client gets ERR then EOF (no frame ever served)',
          verdict == b'ERR' and after == b'', (verdict + after).hex())
    c = socket.create_connection(('127.0.0.1', AUTH_PORT), timeout=5)
    try:
        auth_handshake_client(c, 'wrong-key-16chars00')
        check('suite auth: the wrong key is rejected', False, 'accepted')
    except Exception:
        check('suite auth: the wrong key is rejected (ERR)', True)
    c.close()
    loga = open('/tmp/reg_auth_cache.log').read()
    check('suite auth: the failed proofs are logged',
          'suite auth failed for' in loga)
    check('suite auth: the start log names both schemes',
          'client auth: suite, upstream auth: suite' in loga)
    # the wire: the four lives speak, the keys are secrets
    r = ctl_auth('show', 'modbus-auth')
    check('suite auth: show modbus auth reads suite', r == 'ok modbus-auth=suite', r[:80])
    r = ctl_auth('show', 'auth-upstream')
    check('suite auth: show modbus auth-upstream reads suite', r == 'ok auth-upstream=suite', r[:80])
    r = ctl_auth('show', 'auth-key')
    check('suite auth: the client key never shows', r.startswith('% error: auth-key is a secret'), r[:80])
    r = ctl_auth('clear', 'auth-upstream-key')
    check('suite auth: clear refuses the upstream key (startup-only)',
          r.startswith('% error: restart required (startup-only knob)'), r[:80])
    r = ctl_auth('set', 'auth-key', 'short')
    check('suite auth: startup-only — the key set refuses with the rest',
          r.startswith('% error: restart required (startup-only knob)'), r[:100])
    # the live legs: disabling the client auth serves plain clients again,
    # disabling the upstream auth drops the poll (the fake still demands
    # the handshake), re-enabling restores it
    r = ctl_auth('set', 'modbus-auth', 'none')
    check('suite auth: the client auth disables live', r.startswith('ok modbus-auth=none'), r[:100])
    c = socket.create_connection(('127.0.0.1', AUTH_PORT), timeout=5)
    c.settimeout(5)
    c.sendall(struct.pack('>HHHB', 10, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 2))
    head = _recvn(c, 7)
    body = _recvn(c, struct.unpack('>HHH', head[:6])[2] - 1)
    c.close()
    check('suite auth: a plain client reads after the disable', body[0] == 3, body.hex())
    r = ctl_auth('set', 'auth-upstream', 'none')
    check('suite auth: the upstream auth disables live', r.startswith('ok auth-upstream=none'), r[:100])
    for _ in range(200):
        r = ctl_auth('inspect')
        if '(FAILING)' in r:
            break
        time.sleep(0.5)
    check('suite auth: the plain upstream session fails against the authed fake (poll=down)',
          '(FAILING)' in r, r[-200:])
    r = ctl_auth('set', 'auth-upstream', 'suite')
    check('suite auth: the upstream auth re-enables live (the key persisted)',
          r.startswith('ok auth-upstream=suite'), r[:100])
    for _ in range(90):
        r = ctl_auth('inspect')
        if '(FAILING)' not in r:
            break
        time.sleep(0.5)
    check('suite auth: the upstream poll recovers under the re-enabled scheme', '(FAILING)' not in r, r[-200:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
                        '--listen', '127.0.0.1:%d' % AUTH_PORT, '--dry-run',
                        '--modbus-auth', 'bogus'], capture_output=True, text=True, timeout=15)
    check('suite auth: a bogus scheme fails the config fast',
          r.returncode != 0 and "use 'suite'" in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
                        '--listen', '127.0.0.1:%d' % AUTH_PORT, '--dry-run',
                        '--modbus-auth', 'suite'], capture_output=True, text=True, timeout=15)
    check('suite auth: suite without a key fails the config fast',
          r.returncode != 0 and 'needs a key' in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
                        '--listen', '127.0.0.1:%d' % AUTH_PORT, '--dry-run',
                        '--modbus-auth', 'suite', '--auth-key', 'short'], capture_output=True, text=True, timeout=15)
    check('suite auth: a short key fails the config fast',
          r.returncode != 0 and 'at least 16 characters' in r.stderr, r.stderr[-160:])

    # 6b-10. the waveshare upstream auth: the cache presents the shared key
    #        as a Waveshare gateway's connection password — raw ASCII after
    #        every connect, OK opens the session, anything else kills it
    class WavesharePeer:
        """A stand-in gateway: the first bytes on a connection must be the
        password (raw), the verdict is OK or NO+drop, then canned MBAP
        FC3/FC4 answers (echoing txn/unit, count*2 words)."""

        def __init__(self, port, password):
            self.password = password.encode('ascii')
            self.ok_attempts = 0
            self.bad_attempts = 0
            self.lock = threading.Lock()
            self.srv = socket.socket()
            self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.srv.bind(('127.0.0.1', port))
            self.srv.listen(16)
            threading.Thread(target=self._accept_loop, daemon=True).start()

        def _accept_loop(self):
            while True:
                try:
                    conn, _ = self.srv.accept()
                except OSError:
                    return
                threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

        def _serve(self, conn):
            try:
                conn.settimeout(5)
                got = b''
                while len(got) < len(self.password):
                    chunk = conn.recv(len(self.password) - len(got))
                    if not chunk:
                        return
                    got += chunk
                if got != self.password:
                    with self.lock:
                        self.bad_attempts += 1
                    conn.sendall(b'NO')
                    return
                with self.lock:
                    self.ok_attempts += 1
                conn.sendall(b'OK')
                while True:
                    head = b''
                    while len(head) < 7:
                        chunk = conn.recv(7 - len(head))
                        if not chunk:
                            return
                        head += chunk
                    t, p, l, u = struct.unpack('>HHHB', head)
                    pdu = b''
                    while len(pdu) < l - 1:
                        chunk = conn.recv(l - 1 - len(pdu))
                        if not chunk:
                            return
                        pdu += chunk
                    fc, addr, count = struct.unpack('>BHH', pdu[:5])
                    if fc in (3, 4):
                        conn.sendall(struct.pack('>HHHB', t, 0, 3 + count * 2, u)
                                     + bytes([fc, count * 2]) + b'\x12\x34' * count)
                    else:
                        conn.sendall(struct.pack('>HHHB', t, 0, 3, u) + bytes([fc + 0x80, 1]))
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    WS_FAKE, WS_PORT, WS_CTL = 15565, 15566, 15567
    GW_KEY = 'gw-pass1'
    ws = WavesharePeer(WS_FAKE, GW_KEY)
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
           '--listen', '127.0.0.1:%d' % WS_PORT, '--profile', R,
           '--timeout', '2', '--interval', '2',
           '--control-port', str(WS_CTL), '--control-token', 'ctok-w',
           '--auth-upstream', 'waveshare', '--auth-upstream-key', GW_KEY],
          log='/tmp/reg_ws_cache.log')
    time.sleep(1.2)

    def ctl_ws(*cmds):
        r = subprocess.run([sys.executable, os.path.join(CACHE_DIR, 'bin', 'modbus-cache-ctl.py'),
                            '--control-port', str(WS_CTL), '--control-token', 'ctok-w'] + list(cmds),
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()

    logw = open('/tmp/reg_ws_cache.log').read()
    check('waveshare auth: the start log names the scheme',
          'client auth: none, upstream auth: waveshare' in logw, logw[-200:])
    for _ in range(40):
        r = ctl_ws('inspect')
        if '(FAILING)' not in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the gateway password opens the poll', '(FAILING)' not in r, r[-200:])
    check('waveshare auth: the gateway saw the password (no bad attempts)',
          ws.ok_attempts >= 1 and ws.bad_attempts == 0,
          'ok=%d bad=%d' % (ws.ok_attempts, ws.bad_attempts))
    r = ctl_ws('show', 'auth-upstream')
    check('waveshare auth: the per-setting show carries auth-upstream=',
          r == 'ok auth-upstream=waveshare', r[:200])
    # the reconnect re-proves: the restart verb drops the session, the next
    # poll dials fresh and hands the password over again
    ok_before = ws.ok_attempts
    r = ctl_ws('request restart')
    check('waveshare auth: the restart verb restarts the upstream session',
          r.startswith('ok upstream session restarted'), r[:100])
    for _ in range(40):
        if ws.ok_attempts > ok_before:
            break
        time.sleep(0.5)
    check('waveshare auth: the reconnect hands the password over again',
          ws.ok_attempts > ok_before, 'ok=%d' % ws.ok_attempts)
    r = ctl_ws('inspect')
    check('waveshare auth: the poll recovers after the restart', '(FAILING)' not in r, r[-200:])
    # the wrong password: a spawned instance (the key is startup-only) — the
    # proofs fail against the gateway, the poll goes down, the log carries
    # the exchange errors
    r = ctl_ws('set', 'auth-upstream-key', 'gw-pass2')
    check('waveshare auth: startup-only — the key set refuses',
          r.startswith('% error: restart required (startup-only knob)'), r[:100])
    procs[-1].terminate()
    procs[-1].wait(timeout=10)
    time.sleep(0.5)
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
           '--listen', '127.0.0.1:%d' % WS_PORT, '--profile', R,
           '--timeout', '2', '--interval', '2',
           '--control-port', str(WS_CTL), '--control-token', 'ctok-w',
           '--auth-upstream', 'waveshare', '--auth-upstream-key', 'gw-pass2'],
          log='/tmp/reg_ws_cache_bad.log')
    time.sleep(1.2)
    for _ in range(200):
        r = ctl_ws('inspect')
        if '(FAILING)' in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the wrong password fails against the gateway (poll=down)',
          '(FAILING)' in r, r[-200:])
    check('waveshare auth: the gateway counted the bad attempts',
          ws.bad_attempts >= 1, 'bad=%d' % ws.bad_attempts)
    logw = open('/tmp/reg_ws_cache_bad.log').read()
    check('waveshare auth: the failed proofs land in the log as exchange errors',
          'Waveshare TCP auth failed' in logw, logw[-200:])
    procs[-1].terminate()
    procs[-1].wait(timeout=10)
    time.sleep(0.5)
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
           '--listen', '127.0.0.1:%d' % WS_PORT, '--profile', R,
           '--timeout', '2', '--interval', '2',
           '--control-port', str(WS_CTL), '--control-token', 'ctok-w',
           '--auth-upstream', 'waveshare', '--auth-upstream-key', GW_KEY],
          log='/tmp/reg_ws_cache.log')
    time.sleep(1.2)
    for _ in range(40):
        r = ctl_ws('inspect')
        if '(FAILING)' not in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the poll recovers under the gateway password', '(FAILING)' not in r, r[-200:])
    # the scheme dance (the scheme is not a secret — it sets live; the KEY
    # stands): the short standing key refuses the suite wake, the waveshare
    # wake re-proves the standing password
    r = ctl_ws('set', 'auth-upstream', 'none')
    check('waveshare auth: the upstream auth disables live',
          r.startswith('ok auth-upstream=none'), r[:100])
    r = ctl_ws('set', 'auth-upstream', 'suite')
    check('waveshare auth: going suite over the short standing key refuses',
          r.startswith('% error: the suite auth rejects the standing key'), r[:120])
    r = ctl_ws('set', 'auth-upstream', 'waveshare')
    check('waveshare auth: the scheme wakes over the standing key',
          r.startswith('ok auth-upstream=waveshare'), r[:100])
    for _ in range(40):
        r = ctl_ws('inspect')
        if '(FAILING)' not in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the woken scheme hands the standing password over', '(FAILING)' not in r, r[-200:])
    r = ctl_ws('set', 'auth-upstream', 'none')
    check('waveshare auth: the upstream auth disables again', r.startswith('ok'), r[:60])
    # the dormant floor at start: a short key with no scheme passes (dormant
    # material), the same key under suite refuses — the dry-run proves both
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
                        '--listen', '127.0.0.1:%d' % WS_PORT, '--dry-run',
                        '--auth-upstream', 'none', '--auth-upstream-key', 'shorty'],
                       capture_output=True, text=True, timeout=15)
    check('waveshare auth: a short key with no scheme is accepted at start (dormant)',
          r.returncode == 0 and 'dry-run' in (r.stdout + r.stderr), (r.stdout + r.stderr)[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
                        '--listen', '127.0.0.1:%d' % WS_PORT, '--dry-run',
                        '--auth-upstream', 'suite', '--auth-upstream-key', 'shorty'],
                       capture_output=True, text=True, timeout=15)
    check('waveshare auth: the same key under the suite scheme refuses the start',
          r.returncode != 0 and 'must be at least' in r.stderr, r.stderr[-160:])
    # the start-time grammar: the waveshare fast-fails and the dry-run accept
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
                        '--listen', '127.0.0.1:%d' % WS_PORT, '--dry-run',
                        '--auth-upstream', 'waveshare'], capture_output=True, text=True, timeout=15)
    check('waveshare auth: waveshare without a key fails the config fast',
          r.returncode != 0 and 'needs a key' in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
                        '--listen', '127.0.0.1:%d' % WS_PORT, '--dry-run',
                        '--auth-upstream', 'waveshare', '--auth-upstream-key', 'pässwört'],
                       capture_output=True, text=True, timeout=15)
    check('waveshare auth: a non-ASCII password fails the config fast',
          r.returncode != 0 and 'ASCII' in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
                        '--listen', '127.0.0.1:%d' % WS_PORT, '--dry-run',
                        '--auth-upstream', 'waveshare', '--auth-upstream-key', GW_KEY],
                       capture_output=True, text=True, timeout=15)
    check('waveshare auth: the dry-run accepts the waveshare pair',
          r.returncode == 0 and 'dry-run' in (r.stdout + r.stderr), (r.stdout + r.stderr)[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
                        '--listen', '127.0.0.1:%d' % WS_PORT, '--dry-run',
                        '--auth-upstream', 'bogus'], capture_output=True, text=True, timeout=15)
    check('waveshare auth: a bogus upstream scheme names both schemes',
          r.returncode != 0 and "use 'suite' / 'waveshare'" in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % WS_FAKE,
                        '--listen', '127.0.0.1:%d' % WS_PORT, '--dry-run',
                        '--modbus-auth', 'waveshare', '--auth-key', 'x' * 16],
                       capture_output=True, text=True, timeout=15)
    check('waveshare auth: waveshare on the client leg fails the config fast (upstream only)',
          r.returncode != 0 and "use 'suite'" in r.stderr, r.stderr[-160:])

    # 7. clean shutdowns
    r = cli('shutdown\n\n', 15514 + BASE)
    time.sleep(1)
    check('cache_cli: confirm stops the TCP-control proxy', 'bye shutdown' in r.stdout, repr(r.stdout))
except QuickDone:
    pass
finally:
    for p in procs:
        p.kill()


print()
print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
