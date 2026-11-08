#!/usr/bin/env python3
"""Control-protocol fuzz for modbus-cache: malformed, hostile and degenerate
JSON-line requests against the control server. The server must answer with
a well-formed JSON frame (or close cleanly) and stay alive and serving
afterwards.

  python3 tests/cache-control-fuzz.py

Checks: ALL PASS (or a FAILURES list; exit 1).
"""
import hashlib
import hmac
import json as _json
import os
import socket
import struct
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(REPO, 'cache', 'bin', 'modbus-cache.py')
F = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
FAILURES = []
TOKEN = 'sekrit'
AUTH_PORT = 15965   # the fuzz cache runs token'd (F5): roundtrip authenticates first there
OPS_TOKEN = 'opssecret'
OPS_PORT = 15969    # the ops-token'd cache (the read-only role, §6d)


def wiremac(payload):
    """The control wire's frame mac: the full sha256 HMAC, keyed by the token."""
    import hashlib
    import hmac
    return hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha256).hexdigest()


def signed(cmd):
    """The signed wire form of one command (the token'd server refuses the unsigned)."""
    return _json.dumps({'cmd': cmd, 'mac': wiremac(cmd)}).encode() + b'\n'


def ops_roundtrip(cmd, token=OPS_TOKEN, port=None, unsigned=False, timeout=5.0):
    """Auth with the given token (the ops or the admin one), send the command,
    read one reply: (status, text, mac-verifies-with-the-same-token) — the
    ops sessions must be signed and answered with the ops key, the admin
    ones with the admin key."""
    port = port or OPS_PORT
    try:
        s = connect(port, timeout)
        s.sendall(_json.dumps({'cmd': 'auth', 'token': token}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                s.close()
                return 'dead', 'connection closed during auth', False
            buf += chunk
        auth = _json.loads(buf.decode('utf-8', 'replace'))
        if auth.get('status') != 'ok':
            s.close()
            return 'auth-fail', str(auth.get('text', '')), False
        if token and not unsigned:
            mac = hmac.new(token.encode(), cmd.encode(), hashlib.sha256).hexdigest()
            s.sendall(_json.dumps({'cmd': cmd, 'mac': mac}).encode() + b'\n')
        else:
            s.sendall(_json.dumps({'cmd': cmd}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                s.close()
                return 'dead', 'connection closed without a reply', False
            buf += chunk
        s.close()
        obj = _json.loads(buf.decode('utf-8', 'replace'))
        want = hmac.new(token.encode(), ('%s %s' % (obj.get('status'), obj.get('text', ''))).encode(),
                        hashlib.sha256).hexdigest()
        return str(obj.get('status')), str(obj.get('text', '')), obj.get('mac') == want
    except (OSError, ValueError) as e:
        return 'boom', str(e), False


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' — ' + str(detail) if detail and not ok else ''))
    if not ok:
        FAILURES.append(name)


def connect(port, timeout=5.0):
    s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    return s


def roundtrip(port, wire_bytes, timeout=5.0):
    """Send raw bytes, read one line, parse the JSON; (status, text) or ('dead', ...).
    On AUTH_PORT the token handshake runs first (the F5 rule: a TCP control
    port refuses to start without a token)."""
    try:
        s = connect(port, timeout)
        if port == AUTH_PORT:
            s.sendall(_json.dumps({'cmd': 'auth', 'token': TOKEN}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                chunk = s.recv(65536)
                if not chunk:
                    s.close()
                    return 'dead', 'connection closed during auth'
                buf += chunk
        s.sendall(wire_bytes)
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                s.close()
                return 'dead', 'connection closed without a reply'
            buf += chunk
        s.close()
        obj = _json.loads(buf.decode('utf-8', 'replace'))
        return str(obj.get('status')), str(obj.get('text', ''))
    except (OSError, ValueError) as e:
        return 'boom', str(e)


def main():
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15960',
                                       '--control-port', '0'], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
        procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15960',
                                       '--listen', '127.0.0.1:15964', '--interval', '1',
                                       '--control-port', '15965', '--control-token', TOKEN],
                                      stdout=open('/tmp/cache_ctl_fuzz.log', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.5)

        # 1. malformed and hostile frames: always a well-formed err reply
        garbage = [
            (b'not json at all\n', 'plain garbage'),
            (b'{broken\n', 'broken json'),
            (b'[]\n', 'json array'),
            (b'42\n', 'json number'),
            (b'{}\n', 'empty object'),
            (b'{"no": "cmd"}\n', 'missing cmd'),
            (b'{"cmd": 42}\n', 'non-string cmd'),
            (b'{"cmd": null}\n', 'null cmd'),
            (b'\xff\xfe\x00binary\n', 'binary bytes'),
            (b'{"cmd": "show stat\xc3\xbc\u007f"}\n', 'unicode cmd'),
            (signed('show status')[:-2] + b', "extra": ' + b'[' * 40 + b']' * 40 + b'}\n', 'deeply nested'),   # the extra field is ignored
            (b'\n', 'empty line'),
            (b'   \n', 'whitespace line'),
        ]
        expect_ok = {'deeply nested'}   # a valid command with the extra fields = honored
        for wire, label in garbage:
            st, tx = roundtrip(15965, wire)
            check('fuzz: %s answered with a JSON frame' % label, st in ('ok', 'fail'), '%s %s' % (st, tx))
            want = 'ok' if label in expect_ok else 'fail'
            check('fuzz: %s %s' % (label, 'honored' if label in expect_ok else 'rejected cleanly'),
                  st == want, '%s %s' % (st, tx))

        # 2. the overlong request (1 MB): answered or closed, never a crash
        st, tx = roundtrip(15965, b'{"cmd": "show status", "pad": "' + b'a' * (1024 * 1024) + b'"}\n', timeout=10)
        check('fuzz: 1 MB request handled', st in ('ok', 'fail', 'dead'), '%s %s' % (st, tx[:80]))

        # 3. split packets: one byte at a time, the server assembles the frame
        try:
            s = connect(15965)
            s.sendall(_json.dumps({'cmd': 'auth', 'token': TOKEN}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            for b in signed('show version'):
                s.sendall(bytes([b]))
                time.sleep(0.001)
            buf = b''
            while not buf.endswith(b'\n'):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            s.close()
            obj = _json.loads(buf.decode())
            check('fuzz: byte-by-byte request assembled', obj.get('status') == 'ok'
                  and 'modbus-cache' in obj.get('text', ''), str(obj))
        except (OSError, ValueError) as e:
            check('fuzz: byte-by-byte request assembled', False, str(e))

        # 4. no newline, then close: no crash, the server keeps serving
        s = connect(15965)
        s.sendall(b'{"cmd": "show status"}')
        s.close()
        st, tx = roundtrip(15965, signed('show version'))
        check('fuzz: frameless close does not wedge the server', st == 'ok', '%s %s' % (st, tx))

        # 5. ping flood: 100 keepalives, then a real command still works
        ok = True
        for _ in range(100):
            st, tx = roundtrip(15965, signed('ping'), timeout=10)
            ok = ok and st == 'ok'
        check('fuzz: ping flood survives (100x)', ok)
        st, tx = roundtrip(15965, signed('show status'))
        check('fuzz: real command after the flood', st == 'ok', '%s %s' % (st, tx))

        # 6. the token server: the auth abuse is rejected, the real token works
        procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15960',
                                       '--listen', '127.0.0.1:15966', '--interval', '1',
                                       '--control-port', '15967', '--control-token', 'sekrit'],
                                      stdout=open('/tmp/cache_ctl_fuzz2.log', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.5)
        st, tx = roundtrip(15967, b'{"cmd": "show version"}\n')
        check('fuzz: token server rejects the unauthenticated', st == 'fail' and 'authenticate' in tx,
              '%s %s' % (st, tx))
        bad = True
        for _ in range(30):
            st, tx = roundtrip(15967, b'{"cmd": "auth", "token": "guess-%d"}\n' % _)
            bad = bad and st == 'fail' and 'bad token' in tx
        check('fuzz: 30 wrong tokens all rejected', bad)
        try:
            s = connect(15967)
            s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit'}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            auth = _json.loads(buf.decode())
            check('fuzz: the right token authenticates', auth.get('status') == 'ok', str(auth))
            s.sendall(signed('show version'))
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: authenticated command works on the same connection', reply.get('status') == 'ok'
                  and 'modbus-cache' in reply.get('text', ''), str(reply))
            s.close()
        except (OSError, ValueError) as e:
            check('fuzz: the right token authenticates', False, str(e))

        # 6d. the read-only ops token: show/clear allowed, everything that
        #     steers the daemon forbidden; both roles audited, both mac keys
        OPS_AUDIT = '/tmp/cache_ctl_fuzz_ops_audit.log'
        open(OPS_AUDIT, 'w').write('')
        procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:15960',
                                       '--listen', '127.0.0.1:15968', '--interval', '1',
                                       '--control-port', str(OPS_PORT), '--control-token', 'admintok2',
                                       '--control-ops-token', OPS_TOKEN, '--audit-log', OPS_AUDIT],
                                      stdout=open('/tmp/cache_ctl_fuzz3.log', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.5)
        st, tx, macok = ops_roundtrip('show status')
        check('ops: the ops token authenticates, show status honored, mac\'d with the ops key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show cache')
        check('ops: show cache honored', st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request clear cache')
        check('ops: request clear cache honored (the read-only shift may flush)',
              st == 'ok' and 'cache cleared' in tx and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('set modbus interval 5')
        check('ops: set is forbidden', st == 'fail' and 'forbidden' in tx and 'admin' in tx and macok,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('unset modbus interval')
        check('ops: unset is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request restore')
        check('ops: request restore is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request restart')
        check('ops: request restart is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request reload')
        check('ops: request reload is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('shutdown')
        check('ops: shutdown is forbidden', st == 'fail' and 'forbidden' in tx and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show status', unsigned=True)
        check('ops: an unsigned command is still refused first', st == 'fail' and 'unsigned command' in tx,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('set modbus interval 5', token='admintok2')
        check('ops: the admin token still steers the same server, mac\'d with the admin key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show version', token='nope')
        check('ops: a bogus token is refused', st == 'auth-fail', '%s %s' % (st, tx))
        aud = open(OPS_AUDIT).read()
        check('ops: both roles audited (role=ops clear, role=admin set, the denials included)',
              "role=ops 'request clear cache'" in aud and "role=admin 'set modbus interval 5'" in aud
              and "role=ops 'shutdown'" in aud and "role=ops 'set modbus interval 5' wire=h" in aud, aud[-300:])
        r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15960',
                            '--listen', '127.0.0.1:15968', '--control-port', str(OPS_PORT),
                            '--control-ops-token', 'x', '--dry-run'],
                           capture_output=True, text=True, timeout=15)
        check('ops: an ops token without the admin token is a clean error', r.returncode != 0
              and 'supplements' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:15960',
                            '--listen', '127.0.0.1:15968', '--control-port', str(OPS_PORT),
                            '--control-token', 'same', '--control-ops-token', 'same', '--dry-run'],
                           capture_output=True, text=True, timeout=15)
        check('ops: the ops token equal to the admin token is a clean error', r.returncode != 0
              and 'differ' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))

        # 7. twenty parallel clients: garbage and real commands interleaved
        results = []

        def hammer(i):
            try:
                if i % 2:
                    wire = signed('show cache')
                else:
                    wire = ('garbage %d\n' % i).encode()
                st, tx = roundtrip(15965, wire, timeout=15)
                results.append((i, st))
            except OSError as e:
                results.append((i, 'boom: %s' % e))

        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        check('fuzz: 20 parallel clients all answered', len(results) == 20
              and all(st in ('ok', 'fail') for _, st in results), str(results[:6]))

        # 8. the proxy is still alive and serving Modbus (the device answers)
        s = connect(15964, timeout=5)
        s.sendall(struct.pack('>HHHB', 9, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
        r = s.recv(512)
        s.close()
        check('fuzz: modbus side still answers after the fuzzing', len(r) >= 10, r.hex())

        # 9. clean shutdown
        st, tx = roundtrip(15965, signed('shutdown'))
        check('fuzz: shutdown still works', st == 'bye', '%s %s' % (st, tx))
        time.sleep(1)
        check('fuzz: proxy exited cleanly', procs[1].poll() == 0, str(procs[1].poll()))
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    log = open('/tmp/cache_ctl_fuzz.log').read() + open('/tmp/cache_ctl_fuzz2.log').read() \
        + open('/tmp/cache_ctl_fuzz3.log').read()
    check('fuzz: no tracebacks in the logs', 'Traceback' not in log, log[-200:])

    print()
    if FAILURES:
        print('FAILURES: %s' % FAILURES)
        raise SystemExit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
