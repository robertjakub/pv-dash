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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO, 'cache')

P = os.path.join(CACHE_DIR, 'bin', 'modbus-cache.py')
F = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
R = os.path.join(REPO, 'profiles', 'profiles', 'sun2000.json')

CACHE_PORT = 15505
PORT = 15501

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


try:
    # 1. baseline: strict fake (undefined regs rejected with 02) + cache
    start([sys.executable, F, '--control-port', '0', '--static', '--battery', '--strict', '--port', str(PORT),
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
                           '--listen', '127.0.0.1:15517', '--interval', '1', '--cache-ttl', '3',
                           '--profile', mini], stdout=open('/tmp/reg_mini.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(c3)
    time.sleep(1.5)
    b = rd(32089, 1, port=15517)
    check('profile marks: unmarked register forwarded (32089 = on-grid)',
          b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 512, b.hex())
    b2 = rd(32089, 1, port=15517)
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
          'AUDIT CACHE START' in audit_txt and 'AUDIT CACHE WRITE' in audit_txt
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
                                   '--listen', '127.0.0.1:15507', '--interval', '1',
                                   '--profile', R],
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
    procs[0] = subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--battery', '--strict', '--port', str(PORT),
                                 '--allow-write'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    import json as _json
    map_ = _json.load(open(R))
    map_["registers"].append({'name': 'undefined test register', 'register': 32100, 'type': 'u16', 'cache': True})
    badmap = '/tmp/reg_badmap.json'
    _json.dump(map_, open(badmap, 'w'))
    c2 = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                           '--listen', '127.0.0.1:15506', '--interval', '1', '--cache-ttl', '3',
                           '--profile', badmap], stdout=open('/tmp/reg_cache2.log', 'w'),
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

    # 4. hostile upstream: every garbage reply mode must fail clean (0x0B, one-line log) and recover
    evil = EvilUpstream(15509)
    evil.mode = 'garbage'  # cold from the start: no fine-mode poll can fill the cache
    start([sys.executable, P, '--upstream', '127.0.0.1:15509',
           '--listen', '127.0.0.1:15508', '--interval', '1', '--cache-ttl', '3',
           '--profile', R], log='/tmp/reg_evil.log')
    time.sleep(2)
    for mode in ('garbage', 'short', 'lying', 'txn', 'unit', 'stall'):
        evil.mode = mode
        time.sleep(1.2)
        b = rd(32064, 2, port=15508)
        check('evil upstream %s -> client gets 0x0B' % mode, b[0] == 0x83 and b[1] == 11, b.hex())
    evil.mode = 'garbage_after'  # valid reply + trailing junk: the read itself may succeed
    time.sleep(1.2)
    b = rd(32064, 2, port=15508)
    check('evil upstream garbage_after: handled without a crash',
          (b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000) or (b[0] == 0x83 and b[1] == 11), b.hex())
    b = rd(65000, 4, port=15508)
    w = struct.unpack('>4H', b[2:10]) if b[0] == 3 else ()
    check('diag unaffected by hostile upstream', b[0] == 3 and w[0] == 0xCAFE, str(w))
    evil.mode = 'fine'
    time.sleep(2.5)
    b = rd(32064, 2, port=15508)
    check('evil upstream: recovers when replies turn sane',
          b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    evil_log = open('/tmp/reg_evil.log').read()
    check('evil upstream: zero tracebacks, failures are one-liners',
          'Traceback' not in evil_log and 'poll of' in evil_log)
    evil.stop()

    # 5. control server: show status/connections/cache, clear cache, restart,
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

    start([sys.executable, F, '--static', '--port', '15512', '--control-port', '0', '--allow-write'])
    # the shipped example selection: the essential set, by name
    SEL = os.path.join(CACHE_DIR, 'selection.json')
    start([sys.executable, P, '--upstream', '127.0.0.1:15512',
           '--listen', '127.0.0.1:15518', '--interval', '1', '--profile', R,
           '--selection', SEL], log='/tmp/reg_sel.log')
    time.sleep(1.5)
    plan = open('/tmp/reg_sel.log').read()
    b = rd(32064, 2, port=15518)
    check('selection: the essential set polls pv-power', b[0] == 3
          and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    check('selection: 22 selected ranges, essentials in the plan',
          'caching 22 range(s)' in plan and 'pv-power' in plan
          and 'battery-soc' in plan and 'meter-export' in plan)
    b = rd(32089, 1, port=15518)
    check('selection: an unselected register forwards (device-status 512)',
          b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 512, b.hex())

    start([sys.executable, P, '--upstream', '127.0.0.1:15512',
           '--listen', '127.0.0.1:15513', '--interval', '1', '--profile', R,
           '--write-acl', 'any', '--write-registers', 'any',
           '--control-port', '15514'], log='/tmp/reg_ctl.log',
          env_extra={'CONTROL_TOKEN': 'sekrit'})
    time.sleep(2)
    r = ctl_cmd('show status', 15514)
    check('control: show status multi-line report', r.startswith('ok status\n')
          and 'upstream=127.0.0.1:15512' in r and 'listen=127.0.0.1:15513' in r
          and 'poll=ok' in r and 'hits=0' in r
          and 'poll=' in r and 'hits=0' in r, r)
    c1 = socket.create_connection(('127.0.0.1', 15513), timeout=5)
    pdu = struct.pack('>BHH', 3, 32064, 2)
    c1.sendall(struct.pack('>HHHB', 78, 0, len(pdu) + 1, 1) + pdu)
    c1.recv(512)
    r = ctl_cmd('show connections', 15514)
    check('control: show connections lists peer + requests', 'connected' in r and 'requests 1' in r
          and r.startswith('ok connections 127.0.0.1:'), r)
    r = ctl_cmd('show cache', 15514)
    check('control: show cache counters', 'hits 1' in r and 'range(s)' in r and 'map v0' in r, r)
    r = ctl_cmd('clear cache', 15514)
    check('control: clear cache', r.startswith('ok cache cleared (') and 'repolling now' in r, r)
    b = rd(32064, 2, port=15513)
    check('control: cache refills after clear', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    r = ctl_cmd('restart', 15514)
    check('control: restart drops the upstream session', r.startswith('ok upstream session restarted'), r)
    b = rd(32064, 2, port=15513)
    check('control: upstream reconnects after restart', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    r = ctl_cmd('bogus', 15514)
    check('control: unknown command', r.startswith('err unknown command'), r)
    r = ctl_cmd('ping', 15514)
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
    check('control: malformed frame rejected cleanly', r.get('status') == 'err'
          and 'malformed request' in r.get('text', ''), str(r))

    start([sys.executable, P, '--upstream', '127.0.0.1:15512',
           '--listen', '127.0.0.1:15519', '--interval', '1', '--profile', R,
           '--control-port', '15520', '--control-token', 'sekrit',
           '--audit-log', '/tmp/reg_audit_ctl.log'], log='/tmp/reg_ctl_tok.log')
    time.sleep(1.5)
    r = ctl_raw(b'{"cmd": "show status"}\n', 15520)
    check('control: token server rejects the unauthenticated', r.get('status') == 'err'
          and 'authenticate first' in r.get('text', ''), str(r))
    ok = True
    for i in range(3):
        r = ctl_raw(_json.dumps({'cmd': 'auth', 'token': 'guess-%d' % i}).encode() + b'\n', 15520)
        ok = ok and r.get('status') == 'err' and 'bad token' in r.get('text', '')
    check('control: wrong tokens rejected', ok)
    s = socket.create_connection(('127.0.0.1', 15520), timeout=5)
    s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit'}).encode() + b'\n')
    buf = b''
    while not buf.endswith(b'\n'):
        buf += s.recv(4096)
    auth = _json.loads(buf.decode())
    signed_cmd = _json.dumps({'cmd': 'show status',
                              'mac': hmac.new(b'sekrit', b'show status', hashlib.sha256).hexdigest()})
    s.sendall(signed_cmd.encode() + b'\n')
    buf = b''
    while not buf.endswith(b'\n'):
        buf += s.recv(4096)
    st = _json.loads(buf.decode())
    s.close()
    check('control: the right token authenticates, signed commands work after it',
          auth.get('status') == 'ok' and st.get('status') == 'ok'
          and 'upstream=127.0.0.1:15512' in st.get('text', ''), '%s %s' % (auth, st))
    r = ctl_raw(b'{"cmd": "show status"}\n', 15520, token='sekrit')
    check('control: an unsigned command over TCP is refused (the signed wire)',
          r.get('status') == 'err' and 'unsigned command' in r.get('text', ''), str(r))
    r = ctl_raw(_json.dumps({'cmd': 'show status', 'mac': 'ab' * 32}).encode() + b'\n', 15520, token='sekrit')
    check('control: a bad command mac is refused',
          r.get('status') == 'err' and 'mac does not verify' in r.get('text', ''), str(r))
    tok_audit = open('/tmp/reg_audit_ctl.log').read()
    check('audit: AUTH-FAIL + COMMAND events with the peer and the wire mac',
          'AUTH-FAIL' in tok_audit and 'AUDIT CACHE COMMAND ' in tok_audit
          and 'peer=127.0.0.1:' in tok_audit and "'show status' wire=h" in tok_audit
          and ' -> ok' in tok_audit, tok_audit[-240:])

    # show config: the secret knobs render as the placeholder — the knob is
    # public, the value never is
    r = ctl_cmd('show config', 15520)
    check('show config: the secret knob renders as *** SECRET REMOVED ***',
          'set control token *** SECRET REMOVED ***' in r and 'sekrit' not in r, r[:160])

    # the pre-auth line buffer is capped: a newline-less stream is dropped, not buffered
    s = socket.create_connection(('127.0.0.1', 15520), timeout=10)
    try:
        s.sendall(b'x' * (1024 * 1024 + 65536))   # > MAX_LINE, no newline: the server drops us
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

    def cli(stdin, port=15514, env_extra=None, use_flag=True):
        env = {**os.environ, 'CONTROL_TOKEN': 'sekrit'}
        if env_extra:
            env.update(env_extra)
        args = [sys.executable, K]
        if use_flag:
            args += ['--control-port', str(port)]
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=30, env=env)

    r = cli('show status\nquit\n')
    check('cache_cli: show status prints the report', r.returncode == 0
          and '\ncache:15514 > upstream=127.0.0.1:15512' in r.stdout, repr(r.stdout[-160:]))
    r = cli('clear cache\nquit\n')
    check('cache_cli: clear cache confirms silently', r.returncode == 0
          and '\ncache:15514 > % ok\n' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show control token ?\nshow control ops ?\nset connections ?\nquit\n')
    check("cache_cli: ? at a hidden leaf describes it (the wire's help answer)",
          'control/token - require a token on control connections' in r.stdout, repr(r.stdout[-300:]))
    check("cache_cli: ? at a hidden-only namespace stays Invalid input (the secrets never list)",
          r.stdout.count('% Invalid input.') == 2, repr(r.stdout[-300:]))
    r = cli('shutdown\nn\n')
    check('cache_cli: shutdown refuses without confirming', r.returncode == 0
          and 'Proceed with shutdown? [confirm]' in r.stdout and '% Aborted.' in r.stdout, repr(r.stdout))
    p = subprocess.Popen([sys.executable, K, '--control-port', '15514'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True,
                         env={**os.environ, 'CLI_KEEPALIVE': '0.2', 'CONTROL_TOKEN': 'sekrit'})
    time.sleep(1.2)          # the CLI idles, pinging every 0.2s
    p.stdin.write('show status\n')
    p.stdin.flush()
    time.sleep(0.4)
    p.stdin.write('quit\n')
    p.stdin.flush()
    out, _ = p.communicate(timeout=15)
    check('cache_cli: keepalive keeps an idle session alive (pongs absorbed)',
          p.returncode == 0 and 'upstream=127.0.0.1:15512' in out
          and 'ok pong' not in out, repr(out[-120:]))
    p_unix = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                               '--listen', '127.0.0.1:15515', '--interval', '1', '--profile', R],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p_unix)
    time.sleep(1.5)
    check('control: default unix socket for the listen port', os.path.exists('/tmp/modbus-cache-15515.socket'))
    check('control: the unix socket mode is 0600 (not the umask)',
          os.stat('/tmp/modbus-cache-15515.socket').st_mode & 0o777 == 0o600,
          oct(os.stat('/tmp/modbus-cache-15515.socket').st_mode))
    r = cli('show status\nquit\n', 15515, {'CTL': '/tmp/modbus-cache-15515.socket'}, use_flag=False)
    check('cache_cli: CTL reaches the default socket', r.returncode == 0
          and 'upstream=127.0.0.1:15512' in r.stdout and 'cache:15515 > ' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show status\nquit\n', 15515, {'CTL': '/tmp/modbus-cache-15515.socket'}, use_flag=False)
    check('cache_cli: short CTL env works too', r.returncode == 0
          and 'upstream=127.0.0.1:15512' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show status\nquit\n', 15520, {'CONTROL_TOKEN': 'sekrit'})
    check('cache_cli: token env authenticates the TCP control session', r.returncode == 0
          and 'upstream=127.0.0.1:15512' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show status\nquit\n', 15520, {'CONTROL_TOKEN': ''})
    check('cache_cli: token server refuses the token-less CLI', r.returncode == 0
          and 'err authenticate first' in r.stdout, repr(r.stdout[-160:]))

    # the group-accessible unix socket (--control-socket-group): 0660
    p_unix_g = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                                 '--listen', '127.0.0.1:15516', '--interval', '1', '--profile', R,
                                 '--control-socket-group'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p_unix_g)
    time.sleep(1.5)
    gsock = '/tmp/modbus-cache-15516.socket'
    check('control: --control-socket-group chmods the socket 0660',
          os.stat(gsock).st_mode & 0o777 == 0o660, oct(os.stat(gsock).st_mode))
    r = cli('show version\nquit\n', 15516, {'CTL': gsock}, use_flag=False)
    check('control: the group socket speaks (the owner, us)', r.returncode == 0
          and 'modbus-cache 0.3.0' in r.stdout, repr(r.stdout[-120:]))

    # 5c. cache_ctl: the one-shot client (args, piped batches, token)
    ctl = os.path.join(CACHE_DIR, 'bin', 'modbus-cache-ctl.py')
    r = subprocess.run([sys.executable, ctl, '--control-port', '15514', 'show', 'status'],
                       capture_output=True, text=True, timeout=30,
                       env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    check('cache_ctl: one-shot show status', r.returncode == 0
          and r.stdout.startswith('ok status\nupstream=127.0.0.1:15512'), repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '15520'],
                       input='show cache\nclear cache\n', capture_output=True, text=True,
                       timeout=30, env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    check('cache_ctl: piped batch with the token env', r.returncode == 0
          and r.stdout.startswith('ok cache ') and 'ok cache cleared' in r.stdout, repr(r.stdout[:160]))

    # 5d. set/unset/show: the live settings registry (the inverter's pattern)
    r = ctl_cmd('set modbus interval 2', 15514)
    check('set: interval applied with the state summary', r.startswith('ok modbus/interval=2.00s upstream=127.0.0.1:15512')
          and 'poll=' in r and 'hits=' in r, r[:120])
    r = ctl_cmd('show status', 15514)
    check('set: show status reflects the new interval', 'interval=2.00s' in r, r[:120])
    r = ctl_cmd('show status', 15514)
    check('set: the overridden row lists the setting', 'overridden=modbus/interval' in r, r[-160:])
    r = ctl_cmd('set modbus interval bogus', 15514)
    check('set: a bogus value is a clean err', r.startswith('err interval must be seconds'), r[:100])
    r = ctl_cmd('set bogus 1', 15514)
    check('set: unknown setting', r.startswith('err unknown setting'), r[:100])
    r = ctl_cmd('show settings', 15514)
    check('show settings: retired answers err', r.startswith('err'), r[:80])
    r = ctl_cmd('show modbus interval', 15514)
    check('show <setting>: the bare value', r == 'ok modbus/interval=2.00s', r)
    r = ctl_cmd('show cache ttl', 15514)
    check('show <setting>: the path spelling answers the live', r == 'ok cache/ttl=3.00s', r)
    r = ctl_cmd('help cache ttl', 15514)
    check('help <setting>: the registry description', r.startswith('ok cache/ttl - per-register cache TTL'), r[:110])
    r = ctl_cmd('unset modbus interval', 15514)
    check('unset: restores the configured value', r.startswith('ok modbus/interval=1.00s'), r[:110])
    r = ctl_cmd('show status', 15514)
    check('unset: the override marker clears', 'overridden=none' in r, r[-160:])
    r = ctl_cmd('set modbus timeout 5', 15514)
    check('set: modbus timeout applied (the rekeyed branch)', r.startswith('ok modbus/timeout=5.00s upstream='), r[:120])
    r = ctl_cmd('show modbus timeout', 15514)
    check('show: modbus timeout answers the bare value', r == 'ok modbus/timeout=5.00s', r)
    r = ctl_cmd('set modbus timeout 99', 15514)
    check('set: modbus timeout range-gated', r.startswith('err timeout must be 0 < N <= 60'), r[:100])
    r = ctl_cmd('unset modbus timeout', 15514)
    check('unset: modbus timeout restores the configured value', r.startswith('ok modbus/timeout=3.00s'), r[:110])
    r = ctl_cmd('set config 5', 15514)
    check('set: a show report is not a setting', r.startswith('err unknown setting config'), r[:100])
    r = ctl_cmd('set connections 5', 15514)
    check('set: connections is not a setting', r.startswith('err unknown setting connections'), r[:100])
    r = ctl_cmd('set local-time on', 15514)
    check('set: local-time toggles live', r.startswith('ok local-time=on'), r[:110])
    r = ctl_cmd('show local-time', 15514)
    check('show: local-time answers the bare value', r == 'ok local-time=on', r)
    r = ctl_cmd('set local-time bogus', 15514)
    check('set: local-time validates on|off', r.startswith('err local-time must be on|off'), r[:100])
    r = ctl_cmd('unset local-time', 15514)
    check('unset: local-time restores the configured value', r.startswith('ok local-time=off'), r[:110])
    r = ctl_cmd('show cache-all', 15514)
    check('show cache-all: per-entry rows with age, expiry and status', r.startswith('ok cache-all\n')
          and 'pv-power' in r and 'expires' in r and 'fc3' in r and '2/2' in r, r[:200])
    rows = r.splitlines()
    check('show cache-all: the values column carries the cached words',
          'values' in rows[1] and any(len(row.split()) > 3 and row.split()[3].isdigit()
                                      for row in rows[2:]), r[:200])
    r = ctl_cmd('show cache', 15514)
    check('show cache: the summary still works beside the dump', r.startswith('ok cache '), r[:80])
    r = ctl_cmd('request dump', 15514)
    check('request dump: no dump path configured is a clean err', r.startswith('err no dump path configured'), r[:80])
    r = ctl_cmd('show dump-interval', 15514)
    check('dump: show dump-interval without a path is a clean err', r.startswith('err dump-interval needs a dump path'), r[:80])
    r = ctl_cmd('help', 15514)
    check('dump: the help hides the dump commands without a path', 'request dump' not in r, r[:160])
    r = ctl_cmd('show knobs', 15514)
    check('show knobs: the dictionary of the registry — flag, env twin, how it changes',
          r.startswith('ok knobs') and '--interval' in r and '$INTERVAL' in r
          and 'set modbus interval <value>' in r and '--control-ops-token' in r and ', secret' in r
          and 'set modbus upstream <value>, restart' in r, r[:200])   # the restart-marked knob carries the suffix
    r = ctl_cmd('help knobs', 15514)
    check('help knobs: the same dictionary under the help verb', r.startswith('ok knobs'), r[:80])
    r = ctl_cmd('show uplink', 15514)
    check('show uplink: session counters and per-block latency rows', r.startswith('ok uplink\n')
          and 'exchanges' in r and 'connects' in r and 'mean' in r and 'fails' in r
          and 'fc3' in r and 'status' in r, r[:200])

    # selection none: the map empties, every read forwards, nothing is stored
    r = ctl_cmd('set modbus selection none', 15514)
    check('set modbus selection none: accepted', r.startswith('ok modbus/selection=none'), r[:100])
    r = ctl_cmd('show status', 15514)
    check('set selection none: the map empties', 'ranges=0' in r and 'selection=none' in r, r[:160])
    m1 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache.log'],
                        capture_output=True, text=True).stdout.strip()
    rd(47415, 1)
    rd(47415, 1)
    m2 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache.log'],
                        capture_output=True, text=True).stdout.strip()
    check('selection none: repeat reads forward, nothing is stored', int(m2) == int(m1) + 2,
          '%s -> %s' % (m1, m2))
    ctl_cmd('unset modbus selection', 15514)
    r = ctl_cmd('show status', 15514)
    check('unset selection: the map refills', 'ranges=49' in r and 'selection=all' in r, r[:160])

    # --selection none at startup: the same, straight from the command line
    p_none = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                               '--listen', '127.0.0.1:15526', '--interval', '1', '--profile', R,
                               '--selection', 'none', '--control-port', '15527'],
                              stdout=open('/tmp/reg_cache_none.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_none)
    time.sleep(1.5)
    b = rd(47415, 1, port=15526)
    check('selection none at startup: the read forwards', b[0] == 3, b.hex())
    r = ctl_cmd('show status', 15527)
    check('selection none at startup: 0 range(s), nothing cached',
          'ranges=0' in r and 'selection=none' in r, r[:160])
    ctl_cmd('shutdown', 15527)

    # the poll-cycle durations ride in show status + inspect
    r = ctl_cmd('show status', 15514)
    check('show status: the poll-cycle durations', 'poll_duration=' in r
          and 'poll_duration_mean=' in r, r[:200])
    r = ctl_cmd('inspect', 15514)
    check('inspect: the poll-cycle durations', 'poll cyc  last ' in r and 'mean ' in r, r[:300])

    # per-entry ttl: the profile entry expires early, the global-ttl one stays
    ttlmap = '/tmp/reg_ttl_profile.json'
    _json.dump({'description': 'per-entry ttl',
                'registers': [
                    {'name': 'pv-power', 'register': 32064, 'type': 'i32', 'ttl': 2},
                    {'name': 'device-status', 'register': 32089, 'type': 'u16'},
                ]}, open(ttlmap, 'w'))
    p_ttl = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                              '--listen', '127.0.0.1:15533', '--interval', '5', '--cache-ttl', '30',
                              '--profile', ttlmap, '--control-port', '15534'],
                             stdout=open('/tmp/reg_cache_ttl.log', 'w'), stderr=subprocess.STDOUT,
                             env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_ttl)
    time.sleep(1.5)
    rd(32064, 2, port=15533)
    rd(32089, 1, port=15533)
    f1 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache_ttl.log'],
                        capture_output=True, text=True).stdout.strip()
    time.sleep(2.0)          # pv-power (ttl 2s) expires mid-cycle; device-status (global 30s) stays
    rd(32064, 2, port=15533)
    rd(32089, 1, port=15533)
    f2 = subprocess.run(['grep', '-c', 'not cached, polling', '/tmp/reg_cache_ttl.log'],
                        capture_output=True, text=True).stdout.strip()
    check('per-entry ttl: the fast entry re-forwards, the global one stays cached',
          int(f2) == int(f1) + 1, '%s -> %s' % (f1, f2))
    r = ctl_cmd('show cache-all', 15534)
    check('show cache-all: the entry ttl is marked', 'pv-power' in r and '[ttl 2.00s]' in r, r[:200])
    p_ttl.send_signal(signal.SIGTERM)
    p_ttl.wait(timeout=10)

    # the peer-cred auth on the unix control socket: a token gates both transports,
    # but the kernel-vouched peers (root, the daemon's own user) skip the handshake
    cred_sock = '/tmp/reg_cred.socket'
    p_cred = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                               '--listen', '127.0.0.1:15538', '--interval', '1', '--profile', R,
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
    p_dump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                               '--listen', '127.0.0.1:15536', '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '15537',
                               '--dump-path', dumpfile],
                              stdout=open('/tmp/reg_cache_dump.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_dump)
    time.sleep(1.5)
    r = ctl_cmd('request dump', 15537)
    check('request dump: settings-only by default (F18 round)', r.startswith('ok dumped 0 word(s)')
          and 'setting(s)' in r, r[:120])
    d = _json.load(open(dumpfile))
    check('request dump: the format is the versioned modbus-cache-dump, empty registers',
          d.get('format') == 'modbus-cache-dump' and d.get('version') == 1
          and d.get('registers') == [] and d.get('settings') == {}, str(d.get('saved')))
    check('request dump: the file is 0600 (F18) and carries the integrity hash',
          os.stat(dumpfile).st_mode & 0o777 == 0o600 and isinstance(d.get('hash'), str)
          and len(d['hash']) == 64, '%03o %r' % (os.stat(dumpfile).st_mode & 0o777, d.get('hash'))[:80])
    r = ctl_cmd('show dump-interval', 15537)
    check('request dump: the dump-interval setting answers with a dump path', r == 'ok dump-interval=off', r[:80])
    r = ctl_cmd('help', 15537)
    check('request dump: the help lists the dump commands with a path', 'request dump' in r
          and 'request restore' in r, r[:160])
    r = ctl_cmd('request dump with-cache', 15537)
    check('request dump with-cache: the words ride along', r.startswith('ok dumped 91 word(s)'), r[:120])
    d = _json.load(open(dumpfile))
    check('request dump with-cache: the registers are in the json', len(d.get('registers', [])) == 91,
          str(len(d.get('registers', []))))
    r = ctl_cmd('request restore', 15537)
    check('request restore: the words are back without the device', r.startswith('ok restored 91 word(s)')
          and '0 setting(s)' in r, r[:120])
    ctl_cmd('set modbus interval 2', 15537)
    ctl_cmd('request dump', 15537)
    d = _json.load(open(dumpfile))
    check('request dump: the settings-only dump keeps the words out', d.get('registers') == []
          and d.get('settings', {}).get('modbus/interval') == 2.0, str(d.get('settings')))
    ctl_cmd('clear cache', 15537)
    r = ctl_cmd('show cache', 15537)
    check('request restore: the clear emptied the cache first', '0 word(s) cached' in r, r[:80])
    r = ctl_cmd('request restore', 15537)
    check('request restore: the settings-only dump restores the override (the cache stays empty)',
          r.startswith('ok restored 0 word(s), 1 setting(s)'), r[:120])
    time.sleep(1.4)   # the poller refills (interval 1 s) before the with-cache dump
    ctl_cmd('request dump with-cache', 15537)
    ctl_cmd('clear cache', 15537)
    r = ctl_cmd('request restore', 15537)
    check('request restore: the with-cache dump brings the words back',
          r.startswith('ok restored 91 word(s), 1 setting(s)'), r[:120])
    r = ctl_cmd('show modbus interval', 15537)
    check('request restore: the setting override re-applied', r == 'ok modbus/interval=2.00s', r)
    r = ctl_cmd('show status', 15537)
    check('request restore: the override is listed again', 'overridden=modbus/interval' in r, r[-160:])
    r = ctl_cmd('show status', 15537)
    check('dump: the status carries the dump row', 'dump=%s every off' % dumpfile in r, r[-160:])
    # the F18 restore gates: tampering, a group-writable dump and an unsigned dump all refuse
    good = open(dumpfile).read()
    d = _json.loads(good); d['registers'][0][2] = 65535
    open(dumpfile, 'w').write(_json.dumps(d))
    r = ctl_cmd('request restore', 15537)
    check('dump: a tampered dump refuses to restore (integrity hash)',
          r.startswith('err restore failed: the dump') and 'integrity hash' in r, r[:140])
    open(dumpfile, 'w').write(good)
    d = _json.loads(good); d.pop('hash')
    open(dumpfile, 'w').write(_json.dumps(d))
    r = ctl_cmd('request restore', 15537)
    check('dump: an unsigned (pre-hash) dump refuses to restore',
          r.startswith('err restore failed: the dump') and 'predates the integrity hash' in r, r[:140])
    open(dumpfile, 'w').write(good)
    os.chmod(dumpfile, 0o646)
    r = ctl_cmd('request restore', 15537)
    check('dump: a group/world-writable dump refuses to restore',
          r.startswith('err restore failed: the dump') and 'chmod 0600' in r, r[:140])
    os.chmod(dumpfile, 0o600)
    r = ctl_cmd('request restore', 15537)
    check('dump: the restored dump still loads after the refused attempts',
          r.startswith('ok restored 91 word(s)'), r[:120])

    # ---- the sealed dumps (dump/key): the words and the settings ride
    #      encrypted; a restore fails closed on a wrong or missing key
    kdumpfile = '/tmp/reg_dump_sealed.json'
    p_kdump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                                '--listen', '127.0.0.1:15538', '--interval', '1', '--cache-ttl', '30',
                                '--profile', R, '--control-port', '15539',
                                '--dump-path', kdumpfile, '--dump-key', 'seal-key-1'],
                               stdout=open('/tmp/reg_cache_kdump.log', 'w'), stderr=subprocess.STDOUT,
                               env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_kdump)
    time.sleep(1.5)
    r = ctl_cmd('show dump key', 15539)
    check('sealed dump: show dump/key is a secret — it never shows',
          r.startswith('err dump/key is a secret'), r[:100])
    r = ctl_cmd('set dump key other', 15539)
    check('sealed dump: set dump/key answers the restart note (the key cannot drift mid-life)',
          r.startswith('err restart required (startup-only knob)'), r[:100])
    time.sleep(1.6)   # the poller fills the cache (interval 1 s)
    r = ctl_cmd('request dump with-cache', 15539)
    check('sealed dump: the with-cache dump reports sealed',
          r.startswith('ok dumped 91 word(s)') and '(sealed)' in r, r[:120])
    raw = open(kdumpfile).read()
    d = _json.loads(raw)
    check('sealed dump: the envelope is the sealed version-2 shape — the words and the settings encrypted away',
          d.get('format') == 'modbus-cache-dump' and d.get('version') == 2
          and d.get('cipher') == 'sha256-ctr' and 'registers' not in d and 'settings' not in d
          and d.get('box') and d.get('mac') and 'modbus/interval' not in raw, raw[:120])
    r = ctl_cmd('request restore', 15539)
    check('sealed dump: the restore re-applies under the configured key',
          r.startswith('ok restored 91 word(s)'), r[:120])
    p_kdump.kill()
    time.sleep(0.4)
    # the wrong key: the sealed dump refuses at start (the mac reads it as tampered content)
    p_wrong = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                                '--listen', '127.0.0.1:15538', '--interval', '1', '--cache-ttl', '30',
                                '--profile', R, '--control-port', '15539',
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
    r = ctl_cmd('show version', 15539)
    check('sealed dump: the daemon is up despite the refused dump', r.startswith('ok modbus-cache'), r[:80])
    p_wrong.kill()
    time.sleep(0.4)
    # the right key: the sealed dump restores (the words are back without the device)
    p_right = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                                '--listen', '127.0.0.1:15538', '--interval', '1', '--cache-ttl', '30',
                                '--profile', R, '--control-port', '15539',
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
    r = ctl_cmd('show cache', 15539)
    check('sealed dump: the restored words serve', '91 word(s) cached' in r, r[:80])
    r = ctl_cmd('show status', 15539)
    check('sealed dump: the status dump row marks the seal',
          'dump=%s every off, sealed' % kdumpfile in r, r[-160:])
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
          'is not sealed' in log and 'set dump/key' in log, log[-220:])
    p_file = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                               '--listen', '127.0.0.1:15538', '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '15539',
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
    r = ctl_cmd('show cache', 15539)
    check('file-key: the restored words serve', '91 word(s) cached' in r, r[:80])
    p_file.kill()
    time.sleep(0.4)
    p_missing = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                                  '--listen', '127.0.0.1:15538', '--interval', '1', '--cache-ttl', '30',
                                  '--profile', R, '--control-port', '15539',
                                  '--dump-path', kdumpfile, '--dump-key', 'file:/nonexistent/dump_key',
                                  '--restore-on-start'],
                                 stdout=open('/tmp/reg_cache_kmissing.log', 'w'), stderr=subprocess.STDOUT,
                                 env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    line = ''
    for _ in range(80):
        line = open('/tmp/reg_cache_kmissing.log').read()
        if 'cannot read dump/key' in line:
            break
        time.sleep(0.1)
    time.sleep(0.3)   # the SystemExit prints, then the process is gone
    check('file-key: an unreadable reference fails the start (fail fast, never plaintext)',
          'cannot read dump/key' in line and p_missing.poll() is not None, line[-220:])
    p_missing.poll()
    time.sleep(0.4)

    r = ctl_cmd('set dump-interval 1', 15537)
    check('dump-interval: the live setting accepted', r.startswith('ok dump-interval=1.00s'), r[:120])
    r = ctl_cmd('show status', 15537)
    check('dump-interval: the live setting shows in the dump row', 'dump=%s every 1.00s' % dumpfile in r, r[-160:])
    m1 = os.stat(dumpfile).st_mtime
    time.sleep(2.5)
    m2 = os.stat(dumpfile).st_mtime
    check('dump-interval: the file refreshes by itself', m2 > m1, '%.2f -> %.2f' % (m1, m2))
    r = ctl_cmd('set dump-interval off', 15537)
    check('dump-interval: off again', r.startswith('ok dump-interval=off'), r[:80])
    # the write-behind story: the shutdown dump restores into the next start
    ctl_cmd('set modbus interval 3', 15537)
    r = ctl_cmd('shutdown', 15537)
    check('shutdown dump: the stopper wrote the file', r.startswith('bye'), r[:40])
    p_dump.wait(timeout=10)
    d = _json.load(open(dumpfile))
    check('shutdown dump: settings-only by default (the override is in it, the words stay out)',
          d.get('registers') == [] and d.get('settings', {}).get('modbus/interval') == 3.0, repr(d.get('settings')))
    p_dump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                               '--listen', '127.0.0.1:15536', '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '15537', '--dump-with-cache',
                               '--dump-path', dumpfile],
                              stdout=open('/tmp/reg_cache_dump2.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_dump)
    time.sleep(1.5)
    log = open('/tmp/reg_cache_dump2.log').read()
    check('restore-on-start: the gate defaults to off — the dump is not loaded', 'not loaded on start' in log
          and 'restored the state dump' not in log.split('state dumps:')[1], log[-200:])
    r = ctl_cmd('show modbus interval', 15537)
    check('restore-on-start: the override in the file did not leak in', r == 'ok modbus/interval=1.00s', r)
    r = ctl_cmd('request dump', 15537)
    check('dump-with-cache: the flag turns the plain request dump full', r.startswith('ok dumped 91 word(s)'),
          r[:120])
    ctl_cmd('clear cache', 15537)
    r = ctl_cmd('request restore', 15537)
    check('restore-on-start: the manual request restore still works', r.startswith('ok restored 91 word(s), ')
          and 'setting(s) from' in r, r[:120])
    r = ctl_cmd('show cache', 15537)
    check('restore-on-start: the manual restore loaded the words', '91 word(s) cached' in r, r[:80])
    ctl_cmd('set modbus interval 3', 15537)
    ctl_cmd('shutdown', 15537)
    p_dump.wait(timeout=10)
    p_dump = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                               '--listen', '127.0.0.1:15536', '--interval', '1', '--cache-ttl', '30',
                               '--profile', R, '--control-port', '15537', '--dump-with-cache',
                               '--dump-path', dumpfile, '--restore-on-start'],
                              stdout=open('/tmp/reg_cache_dump2.log', 'w'), stderr=subprocess.STDOUT,
                              env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_dump)
    time.sleep(1.5)
    r = ctl_cmd('show cache', 15537)
    check('restore-on-start: the gate loads the dump', '91 word(s) cached' in r, r[:80])
    r = ctl_cmd('show modbus interval', 15537)
    check('restore-on-start: the override came back with the gate', r == 'ok modbus/interval=3.00s', r)
    r = ctl_cmd('show status', 15537)
    check('restore-on-start: the override is listed with the gate', 'overridden=modbus/interval' in r, r[-160:])
    ctl_cmd('unset modbus interval', 15537)
    ctl_cmd('shutdown', 15537)
    p_dump.wait(timeout=10)

    # the native metrics endpoint: bearer auth + the cache gauges
    p_metrics = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                                  '--listen', '127.0.0.1:15528', '--interval', '1', '--profile', R,
                                  '--control-port', '15530',
                                  '--metrics-listen', '127.0.0.1:15529', '--metrics-server', '--metrics-token', 'sekrit',
                                  '--metrics-max-clients', '1'],
                                 stdout=open('/tmp/reg_cache_metrics.log', 'w'), stderr=subprocess.STDOUT,
                                 env={**os.environ, 'CONTROL_TOKEN': 'sekrit'})
    procs.append(p_metrics)
    time.sleep(1.5)
    import urllib.request, urllib.error

    def get_metrics(tok=None):
        req = urllib.request.Request('http://127.0.0.1:15529/metrics')
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
    r = ctl_cmd('show status', 15530)
    check('metrics: show status carries the endpoint', 'metrics=127.0.0.1:15529 (bearer token), clients 1, per-ip none' in r, r[:400])
    # the metrics caps: a parked (silent) connection holds the one slot, the next request gets 503
    parked = socket.create_connection(('127.0.0.1', 15529), timeout=5)
    time.sleep(0.3)
    over = socket.create_connection(('127.0.0.1', 15529), timeout=5)
    over.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nAuthorization: Bearer sekrit\r\n\r\n')
    reply = over.recv(64)
    check('metrics: 503 past --metrics-max-clients 1', reply.startswith(b'HTTP/1.1 503'),
          reply.split(b'\r\n')[0].decode() if reply else 'empty reply')
    over.close()
    parked.close()
    # the live metrics enable switch: off stops the endpoint, on restarts it
    r = ctl_cmd('set metrics enable off', 15530)
    check('metrics enable: set off stops the endpoint', r.startswith('ok metrics/enable=off'), r[:80])
    srv_down = False
    try:
        socket.create_connection(('127.0.0.1', 15529), timeout=1).close()
    except OSError:
        srv_down = True
    check('metrics enable: the port is closed after set off', srv_down)
    r = ctl_cmd('set metrics enable on', 15530)
    check('metrics enable: set on serves again', r.startswith('ok metrics/enable=on'), r[:80])
    st, _ = get_metrics('sekrit')
    check('metrics enable: the gauges are back', st == 200, str(st))
    # the live caps: raising the cap serves the second concurrent client, lowering 503s it again
    r = ctl_cmd('set metrics limits max-clients 2', 15530)
    check('metrics limits: the live cap set', r.startswith('ok metrics/limits/max-clients=2'), r[:90])
    parked = socket.create_connection(('127.0.0.1', 15529), timeout=5)
    time.sleep(0.3)
    over = socket.create_connection(('127.0.0.1', 15529), timeout=5)
    over.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nAuthorization: Bearer sekrit\r\n\r\n')
    reply = over.recv(64)
    check('metrics limits: the raised cap serves the second client', reply.startswith(b'HTTP/1.0 200'),
          reply.split(b'\r\n')[0].decode() if reply else 'empty reply')
    over.close()
    parked.close()
    r = ctl_cmd('set metrics limits max-clients 1', 15530)
    check('metrics limits: the cap lowered again', r.startswith('ok metrics/limits/max-clients=1'), r[:90])
    parked = socket.create_connection(('127.0.0.1', 15529), timeout=5)
    time.sleep(0.3)
    over = socket.create_connection(('127.0.0.1', 15529), timeout=5)
    over.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nAuthorization: Bearer sekrit\r\n\r\n')
    reply = over.recv(64)
    check('metrics limits: 503 past the lowered cap', reply.startswith(b'HTTP/1.1 503'),
          reply.split(b'\r\n')[0].decode() if reply else 'empty reply')
    over.close()
    parked.close()
    # the live token rotation: the old token is refused the moment the new one lands
    r = ctl_cmd('set metrics token sekrit2', 15530)
    check('metrics token: rotated live', r.startswith('ok metrics/token=<set>'), r[:90])
    st, _ = get_metrics('sekrit')
    check('metrics token: the old token is a 401', st == 401, str(st))
    st, _ = get_metrics('sekrit2')
    check('metrics token: the new token serves', st == 200, str(st))
    r = ctl_cmd('show metrics token', 15530)
    check('metrics token: the secret never renders back', r.startswith('err metrics/token is a secret'), r)
    # the live rebind: the endpoint moves to the new address
    r = ctl_cmd('set metrics listen 127.0.0.1:15535', 15530)
    check('metrics listen: rebound live', r.startswith('ok metrics/listen=127.0.0.1:15535'), r[:90])
    old_closed = False
    try:
        socket.create_connection(('127.0.0.1', 15529), timeout=1).close()
    except OSError:
        old_closed = True
    check('metrics listen: the old address is closed', old_closed)
    try:
        req = urllib.request.Request('http://127.0.0.1:15535/metrics')
        req.add_header('Authorization', 'Bearer sekrit2')
        with urllib.request.urlopen(req, timeout=5) as resp:
            st = resp.status
    except urllib.error.HTTPError as e:
        st = e.code
    check('metrics listen: the new address serves the gauges', st == 200, str(st))

    # the control plane, audit trail and dump lives (the same metrics pattern:
    # set/show/unset on the wire, the secrets never render, the rebind moves it)
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

    r = ctl_cmd('show control ops-verbs', 15530)
    check('control ops-verbs: show answers the policy', r == 'ok control/ops-verbs=clear,show', r)
    r = ctl_cmd('set control ops-verbs show, ping', 15530)
    check('control ops-verbs: set takes the comma list', r.startswith('ok control/ops-verbs=ping,show'), r[:90])
    r = ctl_cmd('set control ops-verbs bogus', 15530)
    check('control ops-verbs: an unknown verb is a clean err', r.startswith('err the ops policy needs at least one'),
          r[:80])
    ctl_cmd('unset control ops-verbs', 15530)
    r = ctl_cmd('show control token', 15530)
    check('control token: the secret never renders back', r.startswith('err control/token is a secret'), r)
    r = ctl_cmd('unset control token', 15530)
    check('control token: unset refuses (a secret has no defaults)', r.startswith('err unknown setting'), r[:80])
    r = ctl_cmd('set control trust-uids 1000, 1001', 15530)
    check('control trust-uids: set takes the uid list', r.startswith('ok control/trust-uids=1000,1001'), r[:90])
    r = ctl_cmd('unset control trust-uids', 15530)
    check('control trust-uids: unset restores the configured none', r.startswith('ok control/trust-uids=off'), r[:90])
    r = ctl_cmd('set control socket-group on', 15530)
    check('control socket-group: set answers on', r.startswith('ok control/socket-group=on'), r[:90])
    ctl_cmd('unset control socket-group', 15530)
    r = ctl_cmd('show audit rotate max-size', 15530)
    check('audit rotate: show answers the configured MB', r == 'ok audit/rotate/max-size=10', r)
    r = ctl_cmd('set audit rotate max-size 5', 15530)
    check('audit rotate: max-size set', r.startswith('ok audit/rotate/max-size=5'), r[:90])
    r = ctl_cmd('show audit log-file', 15530)
    check('audit log-file: the XDG default renders', r.startswith('ok audit/log-file=')
          and r.endswith('modbus-cache/audit.log'), r)
    live_audit = '/tmp/reg_live_audit.log'
    if os.path.exists(live_audit):
        os.remove(live_audit)
    r = ctl_cmd('set audit log-file %s' % live_audit, 15530)
    check('audit log-file: the trail moves live', r.startswith('ok audit/log-file=%s' % live_audit), r[:120])
    ctl_cmd('show version', 15530)
    check('audit log-file: the new sink takes the commands', ' CACHE COMMAND' in open(live_audit).read(),
          open(live_audit).read()[-120:])
    r = ctl_cmd('set audit rotate daily on', 15530)
    check('audit rotate: daily set', r.startswith('ok audit/rotate/daily=on'), r[:90])
    r = ctl_cmd('set audit rotate files 7', 15530)
    check('audit rotate: files set', r.startswith('ok audit/rotate/files=7'), r[:90])
    r = ctl_cmd('set audit disable on', 15530)
    check('audit disable: set answers on', r.startswith('ok audit/disable=on'), r[:90])
    r = ctl_cmd('show audit log-file', 15530)
    check('audit disable: the trail is off', r == 'ok audit/log-file=off', r)
    n_lines = len(open(live_audit).read().splitlines())
    ctl_cmd('show version', 15530)
    check('audit disable: no command lands while off', len(open(live_audit).read().splitlines()) == n_lines,
          open(live_audit).read()[-120:])
    ctl_cmd('set audit disable off', 15530)
    r = ctl_cmd('show audit log-file', 15530)
    check('audit disable: off rebuilds the trail', r == 'ok audit/log-file=%s' % live_audit, r)
    ctl_cmd('show version', 15530)
    check('audit disable: the commands land again', len(open(live_audit).read().splitlines()) > n_lines,
          open(live_audit).read()[-120:])
    r = ctl_cmd('unset audit log-file', 15530)
    check('audit log-file: unset restores the configured sink', r.startswith('ok audit/log-file=')
          and 'modbus-cache/audit.log' in r, r[:120])
    live_dump = '/tmp/reg_live_dump.json'
    r = ctl_cmd('set dump/path %s' % live_dump, 15530)
    check('dump path: set live', r.startswith('ok dump/path=%s' % live_dump), r[:120])
    r = ctl_cmd('request dump', 15530)
    check('dump path: request dump writes the live path', r.startswith('ok dumped') and live_dump in r, r[:90])
    r = ctl_cmd('set dump with-cache on', 15530)
    check('dump with-cache: set answers on', r.startswith('ok dump/with-cache=on'), r[:90])
    r = ctl_cmd('unset dump with-cache', 15530)
    check('dump with-cache: unset restores off', r.startswith('ok dump/with-cache=off'), r[:90])
    r = ctl_cmd('set dump restore-on-start on', 15530)
    check('dump restore-on-start: set answers on', r.startswith('ok dump/restore-on-start=on'), r[:90])
    ctl_cmd('unset dump restore-on-start', 15530)
    r = ctl_cmd('unset dump/path', 15530)
    check('dump path: unset restores off', r.startswith('ok dump/path=off'), r[:90])
    r = ctl_cmd('request dump', 15530)
    check('dump path: request dump without a path is a clean err', r.startswith('err no dump path configured'),
          r[:80])
    r = ctl_cmd('set control port 15536', 15530)
    check('control port: the control rebinds live', r.startswith('ok control/port=127.0.0.1:15536'), r[:90])
    old_gone = False
    try:
        socket.create_connection(('127.0.0.1', 15530), timeout=1).close()
    except OSError:
        old_gone = True
    check('control port: the old port is closed', old_gone)
    r = ctl_cmd('show version', 15536)
    check('control port: the new port speaks', r.startswith('ok modbus-cache'), r[:60])
    r = ctl_cmd('unset control port', 15536)
    check('control port: unset restores the configured target', r.startswith('ok control/port=127.0.0.1:15530'), r[:90])
    r = ctl_cmd('show version', 15530)
    check('control port: the restored target speaks', r.startswith('ok modbus-cache'), r[:60])
    r = ctl_cmd('set control token sekrit2', 15530)
    check('control token: rotated live', r.startswith('ok control/token=<set>'), r[:90])
    s = socket.create_connection(('127.0.0.1', 15530), timeout=5)
    s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit'}).encode() + b'\n')
    buf = b''
    while not buf.endswith(b'\n'):
        buf += s.recv(4096)
    s.close()
    check('control token: the old token is refused', _json.loads(buf.decode()).get('status') == 'err',
          buf.decode()[:80])
    r = ctl_tok('show version', 15530, 'sekrit2')
    check('control token: the new token speaks', r.startswith('ok modbus-cache'), r[:60])
    r = ctl_tok('show control token', 15530, 'sekrit2')
    check('control token: the rotated secret never renders back', r.startswith('err control/token is a secret'), r)

    p_metrics.send_signal(signal.SIGTERM)
    p_metrics.wait(timeout=10)

    # the Modbus per-IP gate: --max-conn-per-ip 1 refuses the second connection from one peer
    p_pip = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                              '--listen', '127.0.0.1:15533', '--interval', '1', '--profile', R,
                              '--max-clients', '0', '--max-conn-per-ip', '1', '--control-port', '15534',
                              '--control-token', 'sekrit'],
                             stdout=open('/tmp/reg_cache_pip.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(p_pip)
    time.sleep(1.5)
    g1 = socket.create_connection(('127.0.0.1', 15533), timeout=5)
    g1.sendall(struct.pack('>HHHB', 1, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
    g1r = g1.recv(512)
    check('per-IP: the first connection serves', len(g1r) >= 10, g1r.hex() if g1r else 'empty')
    g2 = socket.create_connection(('127.0.0.1', 15533), timeout=5)
    g2.settimeout(2)
    refused = False
    try:
        refused = g2.recv(64) == b''
    except OSError:
        refused = False
    check('per-IP: the second connection from the same IP is refused (EOF)', refused)
    check('per-IP: the first connection keeps serving', g1r[7:8] == b'\x03', g1r.hex())
    r = ctl_cmd('set limits max-conn-per-ip 2', 15534)
    check('per-IP: raised live (the path form)', r.startswith('ok limits/max-conn-per-ip=2'), r[:80])
    g2 = socket.create_connection(('127.0.0.1', 15533), timeout=5)
    g2.sendall(struct.pack('>HHHB', 2, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
    g2r = g2.recv(512)
    check('per-IP: the second connection admitted after the raise', len(g2r) >= 10, g2r.hex() if g2r else 'empty')
    r = ctl_cmd('show status', 15534)
    check('per-IP: show status carries the cap', 'max_conn_per_ip=2' in r, r[:160])
    g1.close(); g2.close()
    p_pip.send_signal(signal.SIGTERM)
    p_pip.wait(timeout=10)

    r_before = ctl_cmd('inspect', 15514)
    ctl_cmd('set modbus merge-gap 0', 15514)
    r_after = ctl_cmd('inspect', 15514)
    n_before = r_before.split('poll plan ')[1].split(' block(s)')[0]
    n_after = r_after.split('poll plan ')[1].split(' block(s)')[0]
    check('set merge-gap: the poll plan rebuilds live', int(n_after) > int(n_before),
          '%s -> %s' % (n_before, n_after))
    ctl_cmd('unset modbus merge-gap', 15514)

    r = ctl_cmd('set write allow on', 15514)
    check('set allow-write: the gate opens', r.startswith('ok write/allow=on'), r[:100])
    b = wr6(47415, 3, port=15513)
    check('set allow-write: the forwarded write passes', b == bytes.fromhex('06b9370003'), b.hex())
    ctl_cmd('unset write allow', 15514)
    b = wr6(47415, 4, port=15513)
    check('unset allow-write: the gate closes again', b[0] == 0x86 and b[1] == 1, b.hex())
    r = cli('shutdown\n\n', 15515, {'CTL': '/tmp/modbus-cache-15515.socket'}, use_flag=False)
    time.sleep(1)
    check('cache_cli: RETURN at [confirm] stops the proxy', r.returncode == 0
          and 'bye shutdown' in r.stdout and p_unix.poll() == 0, repr(r.stdout))
    check('control: unix socket unlinked on shutdown', not os.path.exists('/tmp/modbus-cache-15515.socket'))
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
                    '--upstream', '127.0.0.1:15512',
                   '--listen', '127.0.0.1:15521', '--interval', '1', '--cache-ttl', '3',
                   '--allow-write', '--control-port', '15522',
                   '--profile', fc4map, '--audit-log', '/tmp/reg_audit_fc4.log'],
                  log='/tmp/reg_fc4.log', env_extra={'REQUESTS_AUDIT': '1',
                                                     'CONTROL_TOKEN': 'sekrit'})
    time.sleep(2.5)
    b = rd(32064, 2, port=15521)
    check('fc3 range polled and served', b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())
    b = rd4(40001, 2, port=15521)
    check('fc4 range polled and served from cache', b[0] == 4 and struct.unpack('>i', b[2:6])[0] == 0, b.hex())
    b = rd4(31000, 1, port=15521)
    check('fc4 uncached register forwarded (device answers 0)', b[0] == 4 and struct.unpack('>H', b[2:4])[0] == 0, b.hex())
    forwards = subprocess.run(['grep', '-c', 'fc4 registers 31000:1 not cached', '/tmp/reg_fc4.log'],
                              capture_output=True, text=True).stdout.strip()
    b = rd4(31000, 1, port=15521)
    forwards2 = subprocess.run(['grep', '-c', 'fc4 registers 31000:1 not cached', '/tmp/reg_fc4.log'],
                               capture_output=True, text=True).stdout.strip()
    check('fc4 forward cached on first pass', forwards == '1' and forwards2 == '1', '%s/%s' % (forwards, forwards2))
    b = rd4(65000, 1, port=15521)
    forwards = subprocess.run(['grep', '-c', 'fc4 registers 65000:1 not cached', '/tmp/reg_fc4.log'],
                              capture_output=True, text=True).stdout.strip()
    check('fc4 65000 not synthetic -> forwarded to the device', b[0] == 4 and forwards == '1',
          '%s forwards=%s' % (b.hex(), forwards))
    b = rd(65000, 4, port=15521)
    check('fc3 diagnostics block still synthesized', b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 0xCAFE, b.hex())

    # the bit space: the profile's fc1 entry is polled, cached and served;
    # the FC5 coil write passes the same allow-list and invalidates the
    # coil space (the repoll picks the new state)
    b = txn(struct.pack('>BHH', 1, 47400, 1), port=15521)
    check('fc1 bit range polled and served from cache', b == bytes.fromhex('010100'), b.hex())
    b = wr5(47400, 0xFF00, port=15521)
    check('fc5 coil write forwarded (echo)', b == bytes.fromhex('05b928ff00'), b.hex())
    time.sleep(0.5)
    b = txn(struct.pack('>BHH', 1, 47400, 1), port=15521)
    check('fc5 write invalidates the coil space (the repoll serves the new state)',
          b == bytes.fromhex('010101'), b.hex())

    # the write allow-list: inside passes, outside refuses, a spanning write refuses
    b = wr6(47415, 7, port=15521)
    check('write allow-list: register inside the range passes', b == bytes.fromhex('06b9370007'), b.hex())
    b = rd(47415, 1, port=15521)
    check('write allow-list: value landed (fc06 readback)', struct.unpack('>H', b[2:4])[0] == 7)
    b = wr6(47999, 9, port=15521)
    check('write allow-list: register outside refused (0x86/01)', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr16(47498, [1, 2, 3, 4], port=15521)
    check('write allow-list: fc16 spanning the edge refused', b[0] == 0x90 and b[1] == 1, b.hex())

    # FC23 awareness: the gate vets the WRITE span (the second address
    # pair) — the read span riding first does not smuggle the write through
    b = txn(struct.pack('>BHHHH', 23, 47415, 2, 47999, 1) + struct.pack('>BH', 2, 5), port=15521)
    check('write allow-list: fc23 write span outside refused (0x97/01)',
          b[0] == 0x97 and b[1] == 1, b.hex())
    check('write allow-list: the refused fc23 write is a WRITE-REFUSED naming the span',
          'registers 47999:1 = [5], read back 47415:2 (read/write multiple registers, unit 1) '
          '(registers outside the write allow-list)' in open('/tmp/reg_audit_fc4.log').read())
    b = txn(struct.pack('>BHHHH', 23, 47415, 2, 47498, 1) + struct.pack('>BH', 2, 5), port=15521)
    fc4_log = open('/tmp/reg_fc4.log').read()
    check('write allow-list: fc23 spans inside pass the gate (the device answers)',
          b[0] == 0x97 and b[1] == 1
          and 'write: registers 47498:1 = [5], read back 47415:2 (read/write multiple registers, unit 1)' in fc4_log
          and 'write rejected by the device' in fc4_log, b.hex())

    # the named forward: a frame with no cache semantics is forwarded and
    # its function code named in the log
    b = txn(struct.pack('>B', 17), port=15521)   # FC17 report slave id
    check('unknown-FC forward: the frame is named in the log',
          'forwarded FC17 (report slave id)' in open('/tmp/reg_fc4.log').read(), b.hex())

    # the bulk-write shape gate: an FC16 whose byte count lies about its
    # data is refused at the cache (exception 03), never forwarded
    b = txn(struct.pack('>BHHB', 16, 47400, 2, 3) + b'\x00\x00\x00', port=15521)
    check('malformed fc16 (the byte count lies) -> exception 03 at the cache',
          b == bytes.fromhex('9003'), b.hex())
    check('malformed fc16: the WRITE-REFUSED names the inconsistency',
          'the byte count is 3, the register count needs 4' in open('/tmp/reg_audit_fc4.log').read(),
          open('/tmp/reg_audit_fc4.log').read()[-200:])
    # write-through invalidation now sweeps both register spaces: the fc4
    # copy of meter-live is dropped by an fc06 write to the same address
    b = rd4(40001, 2, port=15521)
    b = wr6(40001, 7, port=15521)
    check('write-through: an fc06 write to the fc4 range echoes (dual-space drop)',
          b == bytes.fromhex('069c410007'), b.hex())
    check('write-through: the fc4 copy invalidated, the repoll refills',
          'write: invalidated 1 cached word(s) at registers 40001:1, repolling'
          in open('/tmp/reg_fc4.log').read(), open('/tmp/reg_fc4.log').read()[-200:])

    # inspect: the pretty multi-line dump
    r = ctl_cmd('inspect', 15522)
    check('control: inspect dumps state, map, write gate',
          r.startswith('ok inspect') and 'modbus-cache' in r and 'upstream  127.0.0.1:15512'
          and 'write-registers 47400:100' in r and 'fc4' in r, repr(r[:160]))
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    check('audit: WRITE + WRITE-REFUSED (allow-list) events',
          'AUDIT CACHE WRITE ' in fc4_audit and 'WRITE-REFUSED' in fc4_audit
          and 'outside the write allow-list' in fc4_audit, fc4_audit[-160:])

    # SIGHUP reloads the allow-list from the config script
    conf_txt = open(ini4).read().replace('set write-registers 47400:100', 'set write-registers 47600:100')
    open(ini4, 'w').write(conf_txt)
    os.kill(p_fc4.pid, signal.SIGHUP)
    time.sleep(1)
    b = wr6(47415, 8, port=15521)
    check('SIGHUP: the reloaded allow-list refuses the old range', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(47615, 9, port=15521)
    check('SIGHUP: the reloaded allow-list accepts the new range', b == bytes.fromhex('06b9ff0009'), b.hex())

    # reload: the whole-daemon restart that keeps the sets (a dedicated daemon):
    # the overrides save to the state file beside the config, the process
    # re-execs, the fresh daemon re-resolves the config (the file edit takes
    # effect — the restart-marked style) and re-applies the saved overrides once
    ini_r = '/tmp/reg_reload.conf'
    open(ini_r, 'w').write('# the reload regtest config: the set grammar\nset unit 4\n')
    p_r = start([sys.executable, P, '--config', ini_r, '--upstream', '127.0.0.1:15512',
                 '--listen', '127.0.0.1:15581', '--interval', '1', '--cache-ttl', '3',
                 '--control-port', '15582', '--profile', fc4map],
                log='/tmp/reg_reload.log', env_extra={'CONTROL_TOKEN': 'sekrit'})
    time.sleep(2)
    r = ctl_cmd('set modbus interval 7', 15582)
    check('reload: the override lands before the reload', r.startswith('ok modbus/interval=7'), r[:120])
    r = ctl_cmd('reload', 15582)
    check('reload: the reply reports the saved override', r.startswith('ok reload: 1 override(s) saved'), r[:120])
    back = None
    for _ in range(100):     # the exec is fast; a connect that lands on the dying daemon (the bye frame, unsigned) retries
        try:
            back = ctl_cmd('show status', 15582)
            break
        except Exception:
            time.sleep(0.1)
    check('reload: the daemon came back with the override re-applied (above the flag)',
          back is not None and 'interval=7.00s' in back and 'overridden=modbus/interval' in back, repr((back or '')[-200:]))
    check('reload: the state file is consumed', not os.path.exists(ini_r + '.reload'), ini_r + '.reload')
    # F23: the reload state file is config-equivalent trust at rest — it is
    # created 0600 explicitly, never the umask's (white-box: the round above
    # consumes the file before a stat could land)
    r = subprocess.run([sys.executable, '-c', '''
import os, sys
sys.path.insert(0, %r)
sys.path.insert(0, %r)
import lib.control as C
class Stub(C.ControlServer):
    def __init__(self):
        self.config_path = '/tmp/reg_reload_mode.conf'
        self.overridden = {'modbus/interval'}
        class _Proxy:
            dump_key = None   # the reload state file seals only under dump/key
        self.proxy = _Proxy()
    def dump_settings(self):
        return {'modbus/interval': '7'}
Stub()._save_reload_state()
st = os.stat('/tmp/reg_reload_mode.conf.reload')
assert st.st_mode & 0o777 == 0o600, oct(st.st_mode)
os.unlink('/tmp/reg_reload_mode.conf.reload')
print('mode 0600 ok')
''' % (REPO, CACHE_DIR)], capture_output=True, text=True, timeout=15)
    check('reload: the state file saves 0600 (F23, the F18 posture)',
          r.returncode == 0 and 'mode 0600 ok' in r.stdout, repr((r.stderr or r.stdout)[-160:]))
    open(ini_r, 'w').write('# the reload regtest config: the set grammar\nset unit 7\n')   # rewrite: a name set twice fails the start
    r = ctl_cmd('reload', 15582)
    back = None
    for _ in range(100):
        try:
            back = ctl_cmd('show status', 15582)
            break
        except Exception:
            time.sleep(0.1)
    check('reload: the fresh resolve takes the config edit (unit=7), the override still rides',
          back is not None and 'unit=7' in back and 'interval=7.00s' in back, repr((back or '')[-200:]))
    # the console path: the reload's bye frame rides utf-8 and the notice decodes it (no raw \u escapes)
    p = subprocess.Popen([sys.executable, K, '--control-port', '15582'], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, 'CLI_KEEPALIVE': '0.2', 'CONTROL_TOKEN': 'sekrit'})
    time.sleep(1.0)
    p.stdin.write('reload\n')
    p.stdin.flush()
    time.sleep(3.0)          # stdin stays open: the console lives at the prompt until the bye notice exits it
    out, _ = p.communicate(timeout=25)
    check('reload: the console prints the notice and exits clean (utf-8, no raw escapes)',
          p.returncode == 0 and 'daemon exit: the modbus-cache proxy is reloading' in out
          and '\u2014' in out and '\\u2014' not in out, repr(out[-160:]))
    back = None
    for _ in range(100):
        try:
            back = ctl_cmd('show status', 15582)
            break
        except Exception:
            time.sleep(0.1)
    r = ctl_cmd('shutdown', 15582)
    check('reload: the re-execed daemon still shuts down clean', r.startswith('bye shutdown'), r[:80])

    # the 'none' modes: the write path defaults fully closed (write-acl none +
    # write-registers none — --allow-write alone refuses every write); the
    # connect ACL's none refuses every connection at accept
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
           '--listen', '127.0.0.1:15531', '--interval', '1', '--profile', R,
           '--allow-write', '--control-port', '15532', '--control-token', 'sekrit'],
          log='/tmp/reg_none.log')
    time.sleep(2)
    none_log = open('/tmp/reg_none.log').read()
    check('defaults logged: write acl none, allow-list none',
          'connect acl: any' in none_log and 'write acl: none' in none_log
          and 'write allow-list: none' in none_log, none_log[:240])
    b = wr6(47415, 5, port=15531)
    check('write-acl none (the default): the write is refused', b[0] == 0x86 and b[1] == 1, b.hex())
    none_log = open('/tmp/reg_none.log').read()
    check('write-acl none: the refusal names the ACL',
          'not on the write ACL' in none_log)
    r = ctl_cmd('set acl write any', 15532)
    check('write-acl any: the write is still refused (write-registers none)',
          r.startswith('ok acl/write=any'), r[:80])
    b = wr6(47415, 5, port=15531)
    check('write-registers none: refused via the allow-list', b[0] == 0x86 and b[1] == 1, b.hex())
    r = ctl_cmd('set write registers any', 15532)
    b = wr6(47415, 5, port=15531)
    check('write-acl any + write-registers any: the write passes',
          b == bytes.fromhex('06b9370005'), b.hex())
    r = ctl_cmd('unset acl write', 15532)
    check('unset write-acl restores the default none', r.startswith('ok acl/write=none'), r[:80])
    b = wr6(47415, 5, port=15531)
    check('write-acl none again: refused', b[0] == 0x86 and b[1] == 1, b.hex())

    # the alias: the row's second wire spelling — the same knob, the canonical name renders
    r = ctl_cmd('show write acl', 15532)
    check('alias: show write acl answers the write-acl', r.startswith('ok acl/write=none'), r[:80])
    r = ctl_cmd('set write acl any', 15532)
    check('alias: set write acl any', r.startswith('ok acl/write=any'), r[:80])
    b = wr6(47415, 5, port=15531)
    check('alias: the write passes through the aliased set', b == bytes.fromhex('06b9370005'), b.hex())
    r = ctl_cmd('unset write acl', 15532)
    check('alias: unset write acl restores none', r.startswith('ok acl/write=none'), r[:80])
    r = ctl_cmd('help write acl', 15532)
    check('alias: help write acl describes the row', r.startswith('ok acl/write -'), r[:80])
    r = ctl_cmd('show write', 15532)
    check('alias: the write node lists the aliased acl child',
          r.startswith('ok write - ') and 'acl - clients allowed to write' in r
          and '(the alias of acl/write)' in r, r[:120])

    # the profile write acl: --write-registers profile compiles the device
    # profile's acl/write tree (allow minus deny) — the deye profile allows
    # the TOU schedule slots (148-177) and the grid-start registers (127-128)
    deye = os.path.join(REPO, 'profiles', 'profiles', 'deye-sg05lp3.json')
    start([sys.executable, F, '--static', '--port', '15584', '--profile', deye,
           '--control-port', '0', '--allow-write'], log='/tmp/reg_deye_fake.log')
    start([sys.executable, P, '--upstream', '127.0.0.1:15584',
           '--listen', '127.0.0.1:15585', '--interval', '1', '--profile', 'deye-sg05lp3',
           '--allow-write', '--write-acl', 'any', '--write-registers', 'profile',
           '--control-port', '15586', '--control-token', 'sekrit'],
          log='/tmp/reg_profile_acl.log')
    time.sleep(2)
    b = wr6(127, 55, port=15585)
    check('profile acl: grid-start register 127 passes', b == bytes.fromhex('06007f0037'), b.hex())
    b = wr6(130, 1, port=15585)
    check('profile acl: register 130 refused', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr16(148, [600, 1300] + [0] * 28, port=15585)
    check('profile acl: the TOU span 148:30 passes', b[:3] == bytes.fromhex('100094'), b.hex())
    b = wr16(148, [0] * 31, port=15585)
    check('profile acl: a write spanning past 177 refused', b[0] == 0x90 and b[1] == 1, b.hex())
    pal_log = open('/tmp/reg_profile_acl.log').read()
    check('profile acl: the refusal names the profile gate',
          'outside the write allow-list profile (127:2,148:30)' in pal_log, pal_log[-200:])
    r = ctl_cmd('show write registers', 15586)
    check('profile acl: show answers the profile spelling', r == 'ok write/registers=profile', r[:80])
    r = ctl_cmd('show status', 15586)
    check('profile acl: status renders the effective gate',
          'write_allow_list=profile (127:2,148:30)' in r, r[:200])
    r = ctl_cmd('set write registers 100:1', 15586)
    check('profile acl: explicit ranges still set', r.startswith('ok write/registers=100:1'), r[:80])
    b = wr6(130, 1, port=15585)
    check('profile acl: the explicit range gates instead', b[0] == 0x86 and b[1] == 1, b.hex())
    r = ctl_cmd('unset write registers', 15586)
    check('profile acl: unset restores the configured profile mode',
          r.startswith('ok write/registers=profile'), r[:80])
    r = ctl_cmd('set write registers profile', 15586)
    check('profile acl: the wire set answers the profile spelling',
          r.startswith('ok write/registers=profile'), r[:80])

    # the deny side: a profile copy with allow any + the deye spans denied —
    # everything EXCEPT 127-128/148-177 becomes writable
    deny_prof = '/tmp/reg_deye_deny.json'
    with open(deye) as fh:
        dj = _json.load(fh)
    dj['acl'] = {'write': {'allow': 'any', 'deny': ['127:2', '148:30']}}
    with open(deny_prof, 'w') as fh:
        _json.dump(dj, fh)
    start([sys.executable, P, '--upstream', '127.0.0.1:15584',
           '--listen', '127.0.0.1:15587', '--interval', '1', '--profile', deny_prof,
           '--allow-write', '--write-acl', 'any', '--write-registers', 'profile'],
          log='/tmp/reg_profile_deny.log')
    time.sleep(2)
    b = wr6(200, 1, port=15587)
    check('profile acl deny: register 200 passes (allow any)',
          b == bytes.fromhex('0600c80001'), b.hex())
    b = wr6(127, 1, port=15587)
    check('profile acl deny: the denied 127:2 refused', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(148, 1, port=15587)
    check('profile acl deny: the denied 148:30 refused', b[0] == 0x86 and b[1] == 1, b.hex())
    pdl_log = open('/tmp/reg_profile_deny.log').read()
    check('profile acl deny: the refusal names the carved gate',
          'outside the write allow-list profile (0:127,129:19,178:65358)' in pdl_log, pdl_log[-200:])

    # the rule-chain form: the last matching rule decides, defer resets the
    # decision for its span, an undecided register refuses (default deny)
    for name, gate in [('defer', [{'defer': 'any'}, {'allow': '148:30'}]),
                       ('reopen', [{'allow': 'any'}, {'deny': '148:30'}, {'allow': '148:1'}])]:
        cp = '/tmp/reg_deye_%s.json' % name
        with open(deye) as fh:
            dj = _json.load(fh)
        dj['acl'] = {'write': gate}
        with open(cp, 'w') as fh:
            _json.dump(dj, fh)
        start([sys.executable, P, '--upstream', '127.0.0.1:15584',
               '--listen', '127.0.0.1:%d' % (15590 if name == 'defer' else 15591),
               '--interval', '1', '--profile', cp,
               '--allow-write', '--write-acl', 'any', '--write-registers', 'profile'],
              log='/tmp/reg_profile_%s.log' % name)
    time.sleep(2)
    b = wr6(148, 1, port=15590)
    check('profile acl chain (defer): the allowed span passes', b[0] == 6, b.hex())
    b = wr6(130, 1, port=15590)
    check('profile acl chain (defer): an undecided register refuses', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(148, 1, port=15591)
    check('profile acl chain (re-open): 148 re-allowed by the last rule', b[0] == 6, b.hex())
    b = wr6(160, 1, port=15591)
    check('profile acl chain (re-open): the denied span refuses', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr6(200, 1, port=15591)
    check('profile acl chain (re-open): outside the deny passes', b[0] == 6, b.hex())

    # a profile without the acl section refuses the profile value, at start
    p = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15584',
                        '--listen', '127.0.0.1:15589', '--profile', R,
                        '--write-registers', 'profile', '--dry-run'],
                       capture_output=True, text=True, timeout=60)
    check('profile acl: a profile without the section fails the start',
          p.returncode == 1 and 'carries no "acl"/"write" gate' in p.stderr, '%s %r' % (p.returncode, p.stderr[-120:]))


    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
           '--listen', '127.0.0.1:15539', '--interval', '1', '--profile', R,
           '--connect-acl', 'none', '--control-port', '15540', '--control-token', 'sekrit'],
          log='/tmp/reg_noconn.log')
    time.sleep(2)
    try:
        b = rd(32064, 2, port=15539)
        ok = False
    except (ConnectionError, OSError):
        ok = True
    check('connect-acl none: the connection is rejected at accept', ok)
    r = ctl_cmd('set acl connect any', 15540)
    check('set connect-acl any', r.startswith('ok acl/connect=any'), r[:80])
    b = rd(32064, 2, port=15539)
    check('connect-acl any: the client connects again',
          b[0] == 3 and struct.unpack('>i', b[2:6])[0] == 4000, b.hex())

    # a write frame too short to carry an address fails CLOSED (the
    # allow-list cannot vet what it cannot parse)
    b = txn(b'\x06', port=15521)          # FC6 with no address: forwarded before the fix
    check('write allow-list: an unparseable write frame is refused (fail closed)',
          b == bytes.fromhex('8603'), b.hex())
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    check('audit: the unparseable write is a WRITE-REFUSED event',
          'WRITE-REFUSED' in fc4_audit and 'too short to carry a register address' in fc4_audit,
          fc4_audit[-160:])

    # the audit trail folds control characters: a \n inside a command cannot
    # forge a second, attacker-crafted trail line
    r = ctl_cmd('show status\n2026-01-01T00:00:00Z AUDIT CACHE WRITE forged line', 15522)
    check('control: the injection attempt is a clean err', r.startswith('err status: unexpected'), r[:100])
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    forged = [line for line in fc4_audit.splitlines() if 'AUDIT CACHE WRITE forged' in line]
    check('audit: the trail injection folds to one physical line',
          forged and all('COMMAND' in line and line.startswith('2026-11-') for line in forged),
          str(forged[-1:]))

    # per-client REQUESTS accounting: the periodic tally + the disconnect line
    s = socket.create_connection(('127.0.0.1', 15521), timeout=5)
    for _ in range(3):
        s.sendall(struct.pack('>HHHB', 77, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
        s.recv(64)
    time.sleep(1.2)          # > the 1s REQUESTS audit period: the periodic tally fires
    s.close()
    time.sleep(0.5)
    fc4_audit = open('/tmp/reg_audit_fc4.log').read()
    check('audit: per-client REQUESTS tallies (periodic + disconnect)',
          'AUDIT CACHE REQUESTS' in fc4_audit and 'peer=127.0.0.1:' in fc4_audit
          and '(last 1s:' in fc4_audit and 'connected=' in fc4_audit, fc4_audit[-160:])

    # the control token as a file: reference (the LoadCredential pattern);
    # the file must be owner-only 0600 (F12 in docs/AUDIT.md)
    tokfile = '/tmp/reg_token_file'
    open(tokfile, 'w').write('tokensecret\n')
    os.chmod(tokfile, 0o600)
    p_tok = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                              '--listen', '127.0.0.1:15523', '--interval', '1', '--profile', fc4map,
                              '--control-port', '15524', '--control-token', 'file:' + tokfile],
                             stdout=open('/tmp/reg_tok.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(p_tok)
    time.sleep(1.5)
    r = subprocess.run([sys.executable, ctl, '--control-port', '15524',
                        '--control-token', 'file:' + tokfile, 'show', 'version'],
                       capture_output=True, text=True, timeout=15)
    check('token file: cache_ctl authenticates with the file: reference', r.returncode == 0
          and r.stdout.startswith('ok modbus-cache'), repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '15524', 'show', 'version'],
                       capture_output=True, text=True, timeout=15,
                       env={**os.environ, 'CONTROL_TOKEN': 'file:' + tokfile})
    check('token file: cache_ctl honors CONTROL_TOKEN=file:...', r.returncode == 0
          and r.stdout.startswith('ok modbus-cache'), repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '15524', 'show', 'version'],
                       capture_output=True, text=True, timeout=15)
    check('token file: token-less ctl refused', r.returncode == 0
          and 'err authenticate first' in r.stdout, repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15512', '--listen', '127.0.0.1:15525',
                        '--control-token', 'file:/tmp/reg_no_such_token_file', '--dry-run'],
                       capture_output=True, text=True, timeout=15)
    check('token file: a missing reference fails fast, one line', r.returncode != 0
          and 'cannot read control/token' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
    lax = '/tmp/reg_token_file_lax'
    open(lax, 'w').write('laxsecret\n')                                 # the umask default (0644)
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15512', '--listen', '127.0.0.1:15525',
                        '--control-token', 'file:' + lax, '--dry-run'],
                       capture_output=True, text=True, timeout=15)
    check('token file: a group/world-readable file refuses to start (F12)',
          r.returncode != 0 and '0600' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))

    # the audit-finding refusals (F5/F6 in docs/AUDIT.md): the token-less
    # TCP control and the token-less metrics endpoint refuse to start
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15512', '--dry-run',
                        '--listen', '127.0.0.1:15599', '--control-port', '15599', '--profile', R],
                       capture_output=True, text=True, timeout=15)
    check('control: a TCP control port without a token refuses to start',
          r.returncode != 0 and 'TCP control port' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15512', '--dry-run',
                        '--listen', '127.0.0.1:15599', '--metrics-listen', '127.0.0.1:15598', '--metrics-server', '--profile', R],
                       capture_output=True, text=True, timeout=15)
    check('metrics: the metrics endpoint without a token refuses to start',
          r.returncode != 0 and 'serves register values' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))

    # the paste-back gate: a rendered `set <secret> *** SECRET REMOVED ***`
    # line refuses to parse — the placeholder is never a value
    ph = '/tmp/reg_placeholder.conf'
    open(ph, 'w').write('# the rendered script pasted back\n'
                        'set control token *** SECRET REMOVED ***\n')
    r = subprocess.run([sys.executable, P, '--config', ph, '--upstream', '127.0.0.1:15512',
                        '--listen', '127.0.0.1:15599', '--dry-run'],
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
    start([sys.executable, F, '--static', '--port', str(AUTH_FAKE), '--control-port', '0',
           '--auth', 'suite', '--auth-key', UP_KEY])
    time.sleep(0.7)
    start([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
           '--listen', '127.0.0.1:%d' % AUTH_PORT, '--profile', R,
           '--timeout', '1', '--interval', '2',
           '--control-port', str(AUTH_CTL), '--control-token', 'ctok-a',
           '--auth', 'suite', '--auth-key', CL_KEY,
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
    r = ctl_auth('show', 'status')
    check('suite auth: show status carries auth= + upstream_auth=',
          'auth=suite' in r and 'upstream_auth=suite' in r and 'poll=ok' in r, r[:200])
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
    r = ctl_auth('show', 'modbus', 'auth')
    check('suite auth: show modbus auth reads suite', r == 'ok modbus/auth=suite', r[:80])
    r = ctl_auth('show', 'modbus', 'auth-upstream')
    check('suite auth: show modbus auth-upstream reads suite', r == 'ok modbus/auth-upstream=suite', r[:80])
    r = ctl_auth('show', 'modbus', 'auth', 'key')
    check('suite auth: the client key never shows', r.startswith('err modbus/auth/key is a secret'), r[:80])
    r = ctl_auth('unset', 'modbus', 'auth-upstream-key')
    check('suite auth: unset refuses the upstream key', r.startswith('err unknown setting'), r[:80])
    r = ctl_auth('set', 'modbus', 'auth', 'key', 'short')
    check('suite auth: a short key refuses on the wire',
          r.startswith('err modbus/auth/key must be at least 16'), r[:100])
    # the live legs: disabling the client auth serves plain clients again,
    # disabling the upstream auth drops the poll (the fake still demands
    # the handshake), re-enabling restores it
    r = ctl_auth('set', 'modbus', 'auth', 'none')
    check('suite auth: the client auth disables live', r.startswith('ok modbus/auth=none'), r[:100])
    c = socket.create_connection(('127.0.0.1', AUTH_PORT), timeout=5)
    c.settimeout(5)
    c.sendall(struct.pack('>HHHB', 10, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 2))
    head = _recvn(c, 7)
    body = _recvn(c, struct.unpack('>HHH', head[:6])[2] - 1)
    c.close()
    check('suite auth: a plain client reads after the disable', body[0] == 3, body.hex())
    r = ctl_auth('set', 'modbus', 'auth-upstream', 'none')
    check('suite auth: the upstream auth disables live', r.startswith('ok modbus/auth-upstream=none'), r[:100])
    r = ctl_auth('show', 'status')
    for _ in range(200):
        r = ctl_auth('show', 'status')
        if 'poll=down' in r:
            break
        time.sleep(0.5)
    check('suite auth: the plain upstream session fails against the authed fake (poll=down)',
          'poll=down' in r, r[-200:])
    r = ctl_auth('set', 'modbus', 'auth-upstream', 'suite')
    check('suite auth: the upstream auth re-enables live (the key persisted)',
          r.startswith('ok modbus/auth-upstream=suite'), r[:100])
    for _ in range(90):
        r = ctl_auth('show', 'status')
        if 'poll=ok' in r:
            break
        time.sleep(0.5)
    check('suite auth: the upstream poll recovers under the re-enabled scheme', 'poll=ok' in r, r[-200:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
                        '--listen', '127.0.0.1:%d' % AUTH_PORT, '--dry-run',
                        '--auth', 'bogus'], capture_output=True, text=True, timeout=15)
    check('suite auth: a bogus scheme fails the config fast',
          r.returncode != 0 and "use 'suite'" in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
                        '--listen', '127.0.0.1:%d' % AUTH_PORT, '--dry-run',
                        '--auth', 'suite'], capture_output=True, text=True, timeout=15)
    check('suite auth: suite without a key fails the config fast',
          r.returncode != 0 and 'needs a key' in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % AUTH_FAKE,
                        '--listen', '127.0.0.1:%d' % AUTH_PORT, '--dry-run',
                        '--auth', 'suite', '--auth-key', 'short'], capture_output=True, text=True, timeout=15)
    check('suite auth: a short key fails the config fast',
          r.returncode != 0 and 'at least 16 characters' in r.stderr, r.stderr[-160:])

    # 6b-10. the waveshare upstream auth: the cache presents the shared key
    #        as a Waveshare gateway's connection password — raw ASCII after
    #        every connect, OK opens the session, anything else kills it
    from common.modbus import waveshare_handshake_client

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
        r = ctl_ws('show', 'status')
        if 'poll=ok' in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the gateway password opens the poll', 'poll=ok' in r, r[-200:])
    check('waveshare auth: the gateway saw the password (no bad attempts)',
          ws.ok_attempts >= 1 and ws.bad_attempts == 0,
          'ok=%d bad=%d' % (ws.ok_attempts, ws.bad_attempts))
    r = ctl_ws('show', 'status')
    check('waveshare auth: show status carries upstream_auth=waveshare',
          'upstream_auth=waveshare' in r, r[:200])
    # the reconnect re-proves: the restart verb drops the session, the next
    # poll dials fresh and hands the password over again
    ok_before = ws.ok_attempts
    r = ctl_ws('restart')
    check('waveshare auth: the restart verb restarts the upstream session',
          r.startswith('ok upstream session restarted'), r[:100])
    for _ in range(40):
        if ws.ok_attempts > ok_before:
            break
        time.sleep(0.5)
    check('waveshare auth: the reconnect hands the password over again',
          ws.ok_attempts > ok_before, 'ok=%d' % ws.ok_attempts)
    r = ctl_ws('show', 'status')
    check('waveshare auth: the poll recovers after the restart', 'poll=ok' in r, r[-200:])
    # live rotation under waveshare: a new (non-empty, short) password is
    # accepted, the session drops, the old password now fails, the poll goes
    # down; back to the gateway's password and the poll recovers
    r = ctl_ws('set', 'modbus', 'auth-upstream-key', 'gw-pass2')
    check('waveshare auth: a short password rotates live (non-empty is the floor)',
          r.startswith('ok modbus/auth-upstream-key=<set>'), r[:100])
    for _ in range(200):
        r = ctl_ws('show', 'status')
        if 'poll=down' in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the rotated password fails against the gateway (poll=down)',
          'poll=down' in r, r[-200:])
    check('waveshare auth: the gateway counted the bad attempts',
          ws.bad_attempts >= 1, 'bad=%d' % ws.bad_attempts)
    logw = open('/tmp/reg_ws_cache.log').read()
    check('waveshare auth: the failed proofs land in the log as exchange errors',
          'Waveshare TCP auth failed' in logw, logw[-200:])
    r = ctl_ws('set', 'modbus', 'auth-upstream-key', GW_KEY)
    check('waveshare auth: the gateway password rotates back',
          r.startswith('ok modbus/auth-upstream-key=<set>'), r[:100])
    for _ in range(40):
        r = ctl_ws('show', 'status')
        if 'poll=ok' in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the poll recovers under the restored password', 'poll=ok' in r, r[-200:])
    # the dormant flow: scheme none first, then the short password (the
    # suite floor would refuse it — dormant material passes), then the
    # scheme — and the poll proves the pairing end to end
    r = ctl_ws('set', 'modbus', 'auth-upstream', 'none')
    check('waveshare auth: the upstream auth disables live',
          r.startswith('ok modbus/auth-upstream=none'), r[:100])
    r = ctl_ws('set', 'modbus', 'auth-upstream-key', 'shorty')
    check('waveshare auth: a short key with no scheme set is accepted (dormant)',
          r.startswith('ok modbus/auth-upstream-key=<set>'), r[:100])
    r = ctl_ws('set', 'modbus', 'auth-upstream', 'suite')
    check('waveshare auth: going suite over a short standing key refuses',
          r.startswith('err the suite auth rejects the standing key'), r[:120])
    r = ctl_ws('set', 'modbus', 'auth-upstream', 'waveshare')
    check('waveshare auth: the dormant key wakes with the scheme',
          r.startswith('ok modbus/auth-upstream=waveshare'), r[:100])
    for _ in range(200):
        r = ctl_ws('show', 'status')
        if 'poll=down' in r:
            break
        time.sleep(0.5)
    check('waveshare auth: the dormant short key fails against the gateway (poll=down)',
          'poll=down' in r, r[-200:])
    r = ctl_ws('set', 'modbus', 'auth-upstream', 'none')
    check('waveshare auth: the upstream auth disables again', r.startswith('ok'), r[:60])
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
                        '--auth', 'waveshare', '--auth-key', 'x' * 16],
                       capture_output=True, text=True, timeout=15)
    check('waveshare auth: waveshare on the client leg fails the config fast (upstream only)',
          r.returncode != 0 and "use 'suite'" in r.stderr, r.stderr[-160:])

    # 7. clean shutdowns
    r = cli('shutdown\n\n', 15514)
    time.sleep(1)
    check('cache_cli: confirm stops the TCP-control proxy', 'bye shutdown' in r.stdout, repr(r.stdout))
finally:
    for p in procs:
        p.kill()


print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
