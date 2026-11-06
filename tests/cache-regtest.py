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
    start([sys.executable, F, '--control-port', '0', '--static', '--battery', '--strict', '--port', str(PORT)])
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
    procs[0] = subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--battery', '--strict', '--port', str(PORT)],
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
        obj = _json.loads(buf.decode())
        assert obj.get('mac') == wiremac('%s %s' % (obj.get('status'), obj.get('text', ''))), \
            'the reply mac does not verify: %r' % obj
        return '%s %s' % (obj.get('status'), obj.get('text', ''))

    start([sys.executable, F, '--static', '--port', '15512', '--control-port', '0'])
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
          and '\ncache:15514 > ok\n' in r.stdout, repr(r.stdout[-120:]))
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

    # 5d. set/unset/show settings: the live settings registry (the inverter's pattern)
    r = ctl_cmd('set interval 2', 15514)
    check('set: interval applied with the state summary', r.startswith('ok interval=2.00s upstream=127.0.0.1:15512')
          and 'poll=' in r and 'hits=' in r, r[:120])
    r = ctl_cmd('show status', 15514)
    check('set: show status reflects the new interval', 'interval=2.00s' in r, r[:120])
    r = ctl_cmd('show settings', 15514)
    check('set: the live override carries the * marker', 'interval=2.00s*' in r, r[:160])
    r = ctl_cmd('show status', 15514)
    check('set: the overridden row lists the setting', 'overridden=interval' in r, r[-160:])
    r = ctl_cmd('set interval bogus', 15514)
    check('set: a bogus value is a clean err', r.startswith('err interval must be seconds'), r[:100])
    r = ctl_cmd('set bogus 1', 15514)
    check('set: unknown setting', r.startswith('err unknown setting'), r[:100])
    r = ctl_cmd('show settings', 15514)
    check('show settings: every tunable, one per line', r.startswith('ok settings\n')
          and 'interval=2.00s*' in r and '\nttl=' in r and '\nmerge-gap=' in r
          and '\nlog-level=INFO' in r, r[:160])
    r = ctl_cmd('show interval', 15514)
    check('show <setting>: the bare value', r == 'ok interval=2.00s', r)
    r = ctl_cmd('help ttl', 15514)
    check('help <setting>: the registry description', r.startswith('ok ttl - per-register cache TTL'), r[:110])
    r = ctl_cmd('unset interval', 15514)
    check('unset: restores the configured value', r.startswith('ok interval=1.00s'), r[:110])
    r = ctl_cmd('show status', 15514)
    check('unset: the override marker clears', 'overridden=none' in r, r[-160:])
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
    r = ctl_cmd('show settings', 15514)
    check('dump: the dump-interval setting hides without a dump path', 'dump-interval' not in r, r[:160])
    r = ctl_cmd('show dump-interval', 15514)
    check('dump: show dump-interval without a path is a clean err', r.startswith('err dump-interval needs a dump path'), r[:80])
    r = ctl_cmd('help', 15514)
    check('dump: the help hides the dump commands without a path', 'request dump' not in r, r[:160])
    r = ctl_cmd('show knobs', 15514)
    check('show knobs: the dictionary of the registry — flag, env twin, section, how it changes',
          r.startswith('ok knobs') and '--interval' in r and '$INTERVAL' in r
          and 'set interval <value>' in r and 'control-ops-token-file' in r and ', secret' in r
          and '# ---' in r, r[:200])
    r = ctl_cmd('help knobs', 15514)
    check('help knobs: the same dictionary under the help verb', r.startswith('ok knobs'), r[:80])
    r = ctl_cmd('show uplink', 15514)
    check('show uplink: session counters and per-block latency rows', r.startswith('ok uplink\n')
          and 'exchanges' in r and 'connects' in r and 'mean' in r and 'fails' in r
          and 'fc3' in r and 'status' in r, r[:200])

    # selection none: the map empties, every read forwards, nothing is stored
    r = ctl_cmd('set selection none', 15514)
    check('set selection none: accepted', r.startswith('ok selection=none'), r[:100])
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
    ctl_cmd('unset selection', 15514)
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
    r = ctl_cmd('show settings', 15537)
    check('request dump: the dump-interval setting shows with a dump path', 'dump-interval=off' in r, r[:160])
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
    ctl_cmd('set interval 2', 15537)
    ctl_cmd('request dump', 15537)
    d = _json.load(open(dumpfile))
    check('request dump: the settings-only dump keeps the words out', d.get('registers') == []
          and d.get('settings', {}).get('interval') == 2.0, str(d.get('settings')))
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
    r = ctl_cmd('show interval', 15537)
    check('request restore: the setting override re-applied', r == 'ok interval=2.00s', r)
    r = ctl_cmd('show settings', 15537)
    check('request restore: the override is marked again', 'interval=2.00s*' in r, r[:120])
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
    ctl_cmd('set interval 3', 15537)
    r = ctl_cmd('shutdown', 15537)
    check('shutdown dump: the stopper wrote the file', r.startswith('bye'), r[:40])
    p_dump.wait(timeout=10)
    d = _json.load(open(dumpfile))
    check('shutdown dump: settings-only by default (the override is in it, the words stay out)',
          d.get('registers') == [] and d.get('settings', {}).get('interval') == 3.0, repr(d.get('settings')))
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
    r = ctl_cmd('show interval', 15537)
    check('restore-on-start: the override in the file did not leak in', r == 'ok interval=1.00s', r)
    r = ctl_cmd('request dump', 15537)
    check('dump-with-cache: the flag turns the plain request dump full', r.startswith('ok dumped 91 word(s)'),
          r[:120])
    ctl_cmd('clear cache', 15537)
    r = ctl_cmd('request restore', 15537)
    check('restore-on-start: the manual request restore still works', r.startswith('ok restored 91 word(s), ')
          and 'setting(s) from' in r, r[:120])
    r = ctl_cmd('show cache', 15537)
    check('restore-on-start: the manual restore loaded the words', '91 word(s) cached' in r, r[:80])
    ctl_cmd('set interval 3', 15537)
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
    r = ctl_cmd('show interval', 15537)
    check('restore-on-start: the override came back with the gate', r == 'ok interval=3.00s', r)
    r = ctl_cmd('show settings', 15537)
    check('restore-on-start: the override is marked with the gate', 'interval=3.00s*' in r, r[:120])
    ctl_cmd('unset interval', 15537)
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
    # the live metrics-server switch: off stops the endpoint, on restarts it
    r = ctl_cmd('set metrics-server off', 15530)
    check('metrics-server: set off stops the endpoint', r.startswith('ok metrics-server=off'), r[:80])
    srv_down = False
    try:
        socket.create_connection(('127.0.0.1', 15529), timeout=1).close()
    except OSError:
        srv_down = True
    check('metrics-server: the port is closed after set off', srv_down)
    r = ctl_cmd('set metrics-server on', 15530)
    check('metrics-server: set on serves again', r.startswith('ok metrics-server=on'), r[:80])
    st, _ = get_metrics('sekrit')
    check('metrics-server: the gauges are back', st == 200, str(st))
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
    ctl_cmd('set merge-gap 0', 15514)
    r_after = ctl_cmd('inspect', 15514)
    n_before = r_before.split('poll plan ')[1].split(' block(s)')[0]
    n_after = r_after.split('poll plan ')[1].split(' block(s)')[0]
    check('set merge-gap: the poll plan rebuilds live', int(n_after) > int(n_before),
          '%s -> %s' % (n_before, n_after))
    ctl_cmd('unset merge-gap', 15514)

    r = ctl_cmd('set allow-write on', 15514)
    check('set allow-write: the gate opens', r.startswith('ok allow-write=on'), r[:100])
    b = wr6(47415, 3, port=15513)
    check('set allow-write: the forwarded write passes', b == bytes.fromhex('06b9370003'), b.hex())
    ctl_cmd('unset allow-write', 15514)
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
                ]}, open(fc4map, 'w'))
    # the allow-list rides the config script (the reloadable source: the env is frozen at start)
    ini4 = '/tmp/reg_fc4.conf'
    open(ini4, 'w').write('# the fc4 regtest config: the set grammar\n'
                          'set write-registers 47400:100\n'
                          'set write-acl any\n')

    def rd4(addr, n, port=CACHE_PORT):
        return txn(struct.pack('>BHH', 4, addr, n), port)

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

    # the write allow-list: inside passes, outside refuses, a spanning write refuses
    b = wr6(47415, 7, port=15521)
    check('write allow-list: register inside the range passes', b == bytes.fromhex('06b9370007'), b.hex())
    b = rd(47415, 1, port=15521)
    check('write allow-list: value landed (fc06 readback)', struct.unpack('>H', b[2:4])[0] == 7)
    b = wr6(47999, 9, port=15521)
    check('write allow-list: register outside refused (0x86/01)', b[0] == 0x86 and b[1] == 1, b.hex())
    b = wr16(47498, [1, 2, 3, 4], port=15521)
    check('write allow-list: fc16 spanning the edge refused', b[0] == 0x90 and b[1] == 1, b.hex())

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
    r = ctl_cmd('set write-registers any', 15532)
    b = wr6(47415, 5, port=15531)
    check('write-acl any + write-registers any: the write passes',
          b == bytes.fromhex('06b9370005'), b.hex())
    r = ctl_cmd('unset acl write', 15532)
    check('unset write-acl restores the default none', r.startswith('ok acl/write=none'), r[:80])
    b = wr6(47415, 5, port=15531)
    check('write-acl none again: refused', b[0] == 0x86 and b[1] == 1, b.hex())

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

    # the control token from a file (the LoadCredential pattern);
    # the file must be owner-only 0600 (F12 in docs/AUDIT.md)
    tokfile = '/tmp/reg_token_file'
    open(tokfile, 'w').write('tokensecret\n')
    os.chmod(tokfile, 0o600)
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15512',
                        '--listen', '127.0.0.1:15523', '--interval', '1', '--profile', fc4map,
                        '--control-port', '15524', '--control-token', 'a', '--control-token-file', tokfile],
                       capture_output=True, text=True, timeout=15)
    check('token file: both token sources is a clean error', r.returncode != 0
          and 'not both' in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-120:]))
    p_tok = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15512',
                              '--listen', '127.0.0.1:15523', '--interval', '1', '--profile', fc4map,
                              '--control-port', '15524', '--control-token-file', tokfile],
                             stdout=open('/tmp/reg_tok.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(p_tok)
    time.sleep(1.5)
    r = subprocess.run([sys.executable, ctl, '--control-port', '15524',
                        '--control-token-file', tokfile, 'show', 'version'],
                       capture_output=True, text=True, timeout=15)
    check('token file: cache_ctl authenticates with the file token', r.returncode == 0
          and r.stdout.startswith('ok modbus-cache'), repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '15524', 'show', 'version'],
                       capture_output=True, text=True, timeout=15,
                       env={**os.environ, 'CONTROL_TOKEN_FILE': tokfile})
    check('token file: cache_ctl honors CONTROL_TOKEN_FILE', r.returncode == 0
          and r.stdout.startswith('ok modbus-cache'), repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '15524', 'status'],
                       capture_output=True, text=True, timeout=15,
                       env={**os.environ, 'CONTROL_TOKEN': 'x',
                            'CONTROL_TOKEN_FILE': tokfile})
    check('token file: the token env + the token-file env is a clean error', r.returncode != 0
          and 'mutually exclusive' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-120:]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '15524', 'show', 'version'],
                       capture_output=True, text=True, timeout=15)
    check('token file: token-less ctl refused', r.returncode == 0
          and 'err authenticate first' in r.stdout, repr(r.stdout[:80]))
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15512', '--listen', '127.0.0.1:15525',
                        '--control-token-file', '/tmp/reg_no_such_token_file', '--dry-run'],
                       capture_output=True, text=True, timeout=15)
    check('token file: a missing file fails fast, one line', r.returncode != 0
          and 'cannot read control-token-file' in (r.stderr + r.stdout)
          and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
    lax = '/tmp/reg_token_file_lax'
    open(lax, 'w').write('laxsecret\n')                                 # the umask default (0644)
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15512', '--listen', '127.0.0.1:15525',
                        '--control-token-file', lax, '--dry-run'],
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

    # 7. clean shutdowns
    r = cli('shutdown\n\n', 15514)
    time.sleep(1)
    check('cache_cli: confirm stops the TCP-control proxy', 'bye shutdown' in r.stdout, repr(r.stdout))
finally:
    for p in procs:
        p.kill()


print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
