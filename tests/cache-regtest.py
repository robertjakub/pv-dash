#!/usr/bin/env python3
"""Regression suite for modbus-cache (+ fake inverter with --strict).

Run from anywhere: python3 cache/test/regtest.py
Starts its own fake inverter + proxy on scratch ports and cleans up.
"""
import json as _json
import os
import socket
import struct
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO, 'cache')

P = os.path.join(CACHE_DIR, 'bin', 'modbus_cache.py')
F = os.path.join(REPO, 'inverter', 'bin', 'fake_inverter.py')
R = os.path.join(REPO, 'profiles', 'sun2000.json')

CACHE_PORT = 15505
INV_PORT = 15501

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
    start([sys.executable, F, '--control-port', '0', '--static', '--battery', '--strict', '--port', str(INV_PORT)])
    time.sleep(0.7)
    start([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT), '--listen', '127.0.0.1:%d' % CACHE_PORT,
           '--interval', '1', '--cache-ttl', '3', '--allow-write', '--profile', R,
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
    c3 = subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT),
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

    # write support disabled by default: refused with illegal function, upstream untouched
    procs.append(subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT),
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
        if 'fake_inverter' in ' '.join(p.args):
            p.kill()
    time.sleep(3.5)  # > cache-ttl 3
    b = rd(32064, 2)
    check('expired + inverter dead -> gateway exception 0x0B', b[0] == 0x83 and b[1] == 11, b.hex())
    b = rd(65000, 4)
    w = struct.unpack('>4H', b[2:10]) if b[0] == 3 else ()
    check('device dead: diag still served, flags down, age grows',
          b[0] == 3 and w[:2] == (0xCAFE, 0) and w[2] >= 3, str(w))

    # 3. poll status caching: profile variant with a register the device rejects
    procs[0] = subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--battery', '--strict', '--port', str(INV_PORT)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    import json as _json
    map_ = _json.load(open(R))
    map_["registers"].append({'name': 'undefined test register', 'register': 32100, 'type': 'u16', 'cache': True})
    badmap = '/tmp/reg_badmap.json'
    _json.dump(map_, open(badmap, 'w'))
    c2 = subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', str(INV_PORT),
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
    start([sys.executable, P, '--host', '127.0.0.1', '--port', '15509',
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
    #    cache_cli, shutdown (+ the default unix socket / MODBUS_CACHE_CTL)
    K = os.path.join(CACHE_DIR, 'bin', 'cache_cli.py')

    def ctl_cmd(cmd, port):
        """One JSON-lines control exchange: send {"cmd": ...}, return 'status text'."""
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        s.sendall(_json.dumps({'cmd': cmd}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            b2 = s.recv(4096)
            if not b2:
                break
            buf += b2
        s.close()
        obj = _json.loads(buf.decode())
        return '%s %s' % (obj.get('status'), obj.get('text', ''))

    start([sys.executable, F, '--static', '--port', '15512', '--control-port', '0'])
    # the shipped example selection: the essential set, by name
    SEL = os.path.join(CACHE_DIR, 'selection.json')
    start([sys.executable, P, '--host', '127.0.0.1', '--port', '15512',
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

    start([sys.executable, P, '--host', '127.0.0.1', '--port', '15512',
           '--listen', '127.0.0.1:15513', '--interval', '1', '--profile', R,
           '--control-port', '15514'], log='/tmp/reg_ctl.log')
    time.sleep(2)
    r = ctl_cmd('show status', 15514)
    check('control: show status one line', r.startswith('ok status upstream=127.0.0.1:15512 unit=1 listen=127.0.0.1:15513 clients=0')
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
    def ctl_raw(wire_bytes, port, reads=1):
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
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

    r = ctl_raw(b'not json at all\n', 15514)
    check('control: malformed frame rejected cleanly', r.get('status') == 'err'
          and 'malformed request' in r.get('text', ''), str(r))

    start([sys.executable, P, '--host', '127.0.0.1', '--port', '15512',
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
    s.sendall(b'{"cmd": "show status"}\n')
    buf = b''
    while not buf.endswith(b'\n'):
        buf += s.recv(4096)
    st = _json.loads(buf.decode())
    s.close()
    check('control: the right token authenticates, commands work after it',
          auth.get('status') == 'ok' and st.get('status') == 'ok'
          and 'upstream=127.0.0.1:15512' in st.get('text', ''), '%s %s' % (auth, st))
    tok_audit = open('/tmp/reg_audit_ctl.log').read()
    check('audit: AUTH-FAIL + COMMAND events with the peer',
          'AUTH-FAIL' in tok_audit and 'AUDIT CACHE COMMAND peer=127.0.0.1:' in tok_audit
          and "'show status' -> ok" in tok_audit, tok_audit[-200:])

    def cli(stdin, port=15514, env_extra=None, use_flag=True):
        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
        args = [sys.executable, K]
        if use_flag:
            args += ['--control-port', str(port)]
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=30, env=env)

    r = cli('show status\nquit\n')
    check('cache_cli: show status prints the state line', r.returncode == 0
          and '\ncache:15514 > status upstream=' in r.stdout, repr(r.stdout[-120:]))
    r = cli('clear cache\nquit\n')
    check('cache_cli: clear cache confirms silently', r.returncode == 0
          and '\ncache:15514 > ok\n' in r.stdout, repr(r.stdout[-120:]))
    r = cli('shutdown\nn\n')
    check('cache_cli: shutdown refuses without confirming', r.returncode == 0
          and 'Proceed with shutdown? [confirm]' in r.stdout and '% Aborted.' in r.stdout, repr(r.stdout))
    p = subprocess.Popen([sys.executable, K, '--control-port', '15514'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, env={**os.environ, 'CACHE_CLI_KEEPALIVE': '0.2'})
    time.sleep(1.2)          # the CLI idles, pinging every 0.2s
    p.stdin.write('show status\n')
    p.stdin.flush()
    time.sleep(0.4)
    p.stdin.write('quit\n')
    p.stdin.flush()
    out, _ = p.communicate(timeout=15)
    check('cache_cli: keepalive keeps an idle session alive (pongs absorbed)',
          p.returncode == 0 and 'status upstream=127.0.0.1:15512' in out
          and 'ok pong' not in out, repr(out[-120:]))
    p_unix = subprocess.Popen([sys.executable, P, '--host', '127.0.0.1', '--port', '15512',
                               '--listen', '127.0.0.1:15515', '--interval', '1', '--profile', R],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p_unix)
    time.sleep(1.5)
    check('control: default unix socket for the listen port', os.path.exists('/tmp/modbus-cache-15515.socket'))
    r = cli('show status\nquit\n', 15515, {'MODBUS_CACHE_CTL': '/tmp/modbus-cache-15515.socket'}, use_flag=False)
    check('cache_cli: MODBUS_CACHE_CTL reaches the default socket', r.returncode == 0
          and 'status upstream=127.0.0.1:15512' in r.stdout and 'cache:15515 > ' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show status\nquit\n', 15515, {'CACHE_CTL': '/tmp/modbus-cache-15515.socket'}, use_flag=False)
    check('cache_cli: short CACHE_CTL env works too', r.returncode == 0
          and 'status upstream=127.0.0.1:15512' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show status\nquit\n', 15520, {'MODBUS_CACHE_CONTROL_TOKEN': 'sekrit'})
    check('cache_cli: token env authenticates the TCP control session', r.returncode == 0
          and 'status upstream=127.0.0.1:15512' in r.stdout, repr(r.stdout[-120:]))
    r = cli('show status\nquit\n', 15520)
    check('cache_cli: token server refuses the token-less CLI', r.returncode == 0
          and 'err authenticate first' in r.stdout, repr(r.stdout[-160:]))

    # 5c. cache_ctl: the one-shot client (args, piped batches, token)
    ctl = os.path.join(CACHE_DIR, 'bin', 'cache_ctl.py')
    r = subprocess.run([sys.executable, ctl, '--control-port', '15514', 'show', 'status'],
                       capture_output=True, text=True, timeout=30)
    check('cache_ctl: one-shot show status', r.returncode == 0
          and r.stdout.startswith('ok status upstream=127.0.0.1:15512'), repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, ctl, '--control-port', '15520'],
                       input='show cache\nclear cache\n', capture_output=True, text=True,
                       timeout=30, env={**os.environ, 'MODBUS_CACHE_CONTROL_TOKEN': 'sekrit'})
    check('cache_ctl: piped batch with the token env', r.returncode == 0
          and r.stdout.startswith('ok cache ') and 'ok cache cleared' in r.stdout, repr(r.stdout[:160]))
    r = cli('shutdown\n\n', 15515, {'MODBUS_CACHE_CTL': '/tmp/modbus-cache-15515.socket'}, use_flag=False)
    time.sleep(1)
    check('cache_cli: RETURN at [confirm] stops the proxy', r.returncode == 0
          and 'bye shutdown' in r.stdout and p_unix.poll() == 0, repr(r.stdout))
    check('control: unix socket unlinked on shutdown', not os.path.exists('/tmp/modbus-cache-15515.socket'))
    r = cli('shutdown\n\n', 15514)
    time.sleep(1)
    check('cache_cli: confirm stops the TCP-control proxy', 'bye shutdown' in r.stdout, repr(r.stdout))
finally:
    for p in procs:
        p.kill()


print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
