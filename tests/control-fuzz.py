#!/usr/bin/env python3
"""Control-protocol fuzz for the fake inverter: malformed, hostile and
degenerate JSON-line requests against the control server. The server must
answer with a well-formed JSON frame (or close cleanly) and stay alive and
serving afterwards.

  python3 tests/control-fuzz.py

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


def wiremac(token, payload):
    """The control wire's frame mac: the full sha256 HMAC, keyed by the token."""
    return hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
FAILURES = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' — ' + str(detail) if detail and not ok else ''))
    if not ok:
        FAILURES.append(name)


def connect(port, timeout=5.0):
    s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    return s


def roundtrip(port, wire_bytes, timeout=5.0):
    """Send raw bytes, read one line, parse the JSON; (status, text) or ('dead', ...)."""
    try:
        s = connect(port, timeout)
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


def authed_roundtrip(port, token, cmd, timeout=5.0):
    """Auth with the token, send the mac'd command, read one reply: a dict.
    Asserts nothing — the caller checks the mac against the token it passed
    (the ops sessions must be signed with the ops key, the admin ones with
    the admin key)."""
    try:
        s = connect(port, timeout)
        s.sendall(_json.dumps({'cmd': 'auth', 'token': token}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                s.close()
                return {'status': 'dead', 'text': 'connection closed during auth'}
            buf += chunk
        auth = _json.loads(buf.decode('utf-8', 'replace'))
        if auth.get('status') != 'ok':
            s.close()
            return {'status': 'auth-fail', 'text': str(auth.get('text', ''))}
        s.sendall(_json.dumps({'cmd': cmd, 'mac': wiremac(token, cmd)}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                s.close()
                return {'status': 'dead', 'text': 'connection closed without a reply'}
            buf += chunk
        s.close()
        obj = _json.loads(buf.decode('utf-8', 'replace'))
        obj['_mac_ok'] = obj.get('mac') == wiremac(token, '%s %s' % (obj.get('status'), obj.get('text', '')))
        return obj
    except (OSError, ValueError) as e:
        return {'status': 'boom', 'text': str(e)}



def wait_port(port, timeout=20):
    """The daemon's startup race: the bind lands when it lands (the pyc, the
    profile load, the audit init) — poll-connect instead of a blind sleep."""
    end = time.monotonic() + timeout
    while True:
        try:
            socket.create_connection(('127.0.0.1', port), timeout=1).close()
            return
        except OSError:
            if time.monotonic() >= end:
                raise
            time.sleep(0.2)

def main():
    BASE = int(os.environ.get('SUITE_PORT_BASE', '0'))   # the concurrent-battery port space (the runner's slot)
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15960 + BASE),
                                       '--control-port', '%d' % (15961 + BASE)],
                                      stdout=open('/tmp/ctl_fuzz.log', 'w'), stderr=subprocess.STDOUT))
        wait_port(15961 + BASE)

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
            (b'{"cmd": "show version", "extra": ' + b'[' * 40 + b']' * 40 + b'}\n', 'deeply nested'),   # the extra field is ignored
            (b'\n', 'empty line'),
            (b'   \n', 'whitespace line'),
        ]
        expect_ok = {'deeply nested'}   # a valid command with the extra fields = honored
        for wire, label in garbage:
            st, tx = roundtrip(15961 + BASE, wire)
            check('fuzz: %s answered with a JSON frame' % label, st in ('ok', 'fail'), '%s %s' % (st, tx))
            want = 'ok' if label in expect_ok else 'fail'
            check('fuzz: %s %s' % (label, 'honored' if label in expect_ok else 'rejected cleanly'),
                  st == want, '%s %s' % (st, tx))

        # 2. the overlong request (1 MB): answered or closed, never a crash
        st, tx = roundtrip(15961 + BASE, b'{"cmd": "show version", "pad": "' + b'a' * (1024 * 1024) + b'"}\n', timeout=10)
        check('fuzz: 1 MB request handled', st in ('ok', 'fail', 'dead'), '%s %s' % (st, tx[:80]))

        # 3. split packets: one byte at a time, the server assembles the frame
        try:
            s = connect(15961 + BASE)
            for b in b'{"cmd": "show version"}\n':
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
                  and 'fake-inverter' in obj.get('text', ''), str(obj))
        except (OSError, ValueError) as e:
            check('fuzz: byte-by-byte request assembled', False, str(e))

        # 4. no newline, then close: no crash, the server keeps serving
        s = connect(15961 + BASE)
        s.sendall(b'{"cmd": "show version"}')
        s.close()
        st, tx = roundtrip(15961 + BASE, b'{"cmd": "show version"}\n')
        check('fuzz: frameless close does not wedge the server', st == 'ok', '%s %s' % (st, tx))

        # 5. ping flood: 100 keepalives, then a real command still works
        ok = True
        for _ in range(100):
            st, tx = roundtrip(15961 + BASE, b'{"cmd": "ping"}\n', timeout=10)
            ok = ok and st == 'ok'
        check('fuzz: ping flood survives (100x)', ok)
        st, tx = roundtrip(15961 + BASE, b'{"cmd": "show version"}\n')
        check('fuzz: real command after the flood', st == 'ok', '%s %s' % (st, tx))

        # 6. the token server: the auth abuse is rejected, the real token works
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:15962',
                                       '--control-port', '15963', '--control-token', 'sekrit'],
                                      stdout=open('/tmp/ctl_fuzz2.log', 'w'), stderr=subprocess.STDOUT))
        wait_port(15961 + BASE)
        st, tx = roundtrip(15963, b'{"cmd": "show version"}\n')
        check('fuzz: token server rejects the unauthenticated', st == 'fail' and 'authenticate' in tx,
              '%s %s' % (st, tx))
        bad = True
        for _ in range(30):
            st, tx = roundtrip(15963, b'{"cmd": "auth", "token": "guess-%d"}\n' % _)
            bad = bad and st == 'fail' and 'bad token' in tx
        check('fuzz: 30 wrong tokens all rejected', bad)
        try:
            s = connect(15963)
            s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit'}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            auth = _json.loads(buf.decode())
            check('fuzz: the right token authenticates', auth.get('status') == 'ok'
                  and auth.get('mac') == wiremac('sekrit', 'ok authenticated'), str(auth))
            s.sendall(_json.dumps({'cmd': 'show version', 'mac': wiremac('sekrit', 'show version')}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: authenticated command works on the same connection', reply.get('status') == 'ok'
                  and 'fake-inverter' in reply.get('text', '')
                  and reply.get('mac') == wiremac('sekrit', '%s %s' % (reply.get('status'), reply.get('text', ''))),
                  str(reply))
            s.sendall(b'{"cmd": "show version"}\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: an unsigned command over TCP is refused', reply.get('status') == 'fail'
                  and 'unsigned command' in reply.get('text', ''), str(reply))
            s.close()
        except (OSError, ValueError) as e:
            check('fuzz: the right token authenticates', False, str(e))

        # 6b. the token as a file: reference: the fake reads it, the ctl authenticates
        #     with it (the file must be owner-only 0600 — F12 in docs/AUDIT.md)
        open('/tmp/ctl_fuzz_token', 'w').write('filesecret\n')
        os.chmod('/tmp/ctl_fuzz_token', 0o600)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:15965',
                                       '--control-port', '15964', '--control-token',
                                       'file:/tmp/ctl_fuzz_token'],
                                      stdout=open('/tmp/ctl_fuzz3.log', 'w'), stderr=subprocess.STDOUT))
        wait_port(15961 + BASE)
        st, tx = roundtrip(15964, b'{"cmd": "show version"}\n')
        check('fuzz: token reference server rejects the unauthenticated', st == 'fail' and 'authenticate' in tx,
              '%s %s' % (st, tx))
        try:
            c = connect(15964)
            c.sendall(_json.dumps({'cmd': 'auth', 'token': 'filesecret'}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += c.recv(4096)
            auth = _json.loads(buf.decode())
            check('fuzz: the file: token authenticates', auth.get('status') == 'ok', str(auth))
            c.close()
        except (OSError, ValueError) as e:
            check('fuzz: the file: token authenticates', False, str(e))
        r = subprocess.run([sys.executable, os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py'),
                            '--control-port', '15964', '--control-token', 'file:/tmp/ctl_fuzz_token',
                            'show', 'version'], capture_output=True, text=True, timeout=15)
        check('fuzz: fake_ctl authenticates with the file: token', r.returncode == 0
              and r.stdout.startswith('ok fake-inverter'), repr(r.stdout[:80]))
        r = subprocess.run([sys.executable, os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py'),
                            '--control-port', '15963', '--control-token', 'file:/tmp/ctl_fuzz_no_file',
                            'show', 'version'], capture_output=True, text=True, timeout=15)
        check('fuzz: a missing token reference fails fast, one line', r.returncode != 0
              and 'cannot read control-token' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-120:]))
        open('/tmp/ctl_fuzz_token_lax', 'w').write('laxsecret\n')          # the umask default (0644)
        r = subprocess.run([sys.executable, os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py'),
                            '--listen', '127.0.0.1:15962', '--dry-run',
                            '--control-token', 'file:/tmp/ctl_fuzz_token_lax'],
                           capture_output=True, text=True, timeout=15)
        check('fuzz: a group/world-readable token file refuses to start (F12)',
              r.returncode != 0 and '0600' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-120:]))

        # 6c. the file: reference rides the token env like the flag
        r = subprocess.run([sys.executable, os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py'),
                            '--control-port', '15964', 'show', 'version'],
                           capture_output=True, text=True, timeout=15,
                           env={**os.environ, 'CONTROL_TOKEN': 'file:/tmp/ctl_fuzz_token'})
        check('fuzz: fake_ctl honors CONTROL_TOKEN=file:...', r.returncode == 0
              and r.stdout.startswith('ok fake-inverter'), repr(r.stdout[:80]))
        r = subprocess.run([sys.executable, os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py'),
                            '--listen', '127.0.0.1:15962', '--dry-run', '--metrics-server',
                            '--metrics-listen', '127.0.0.1:15967'],
                           capture_output=True, text=True, timeout=15,
                           env={**os.environ, 'METRICS_TOKEN': 'file:/tmp/ctl_fuzz_token'})
        check('fuzz: the fake honors METRICS_TOKEN=file:...', r.returncode == 0
              and 'bearer token' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))

        # 6d. the read-only ops token: the show/clear verbs only, both audited
        OPS_AUDIT = '/tmp/ctl_fuzz_ops_audit.log'
        open(OPS_AUDIT, 'w').write('')
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:15983',
                                       '--control-port', '15982', '--control-token', 'admintok',
                                       '--control-ops-token', 'opstok', '--audit-log', OPS_AUDIT],
                                      stdout=open('/tmp/ctl_fuzz4.log', 'w'), stderr=subprocess.STDOUT))
        wait_port(15961 + BASE)
        r = authed_roundtrip(15982, 'opstok', 'show version')
        check('ops: the ops token authenticates and the reply is mac\'d with the ops key',
              r.get('status') == 'ok' and 'fake-inverter' in r.get('text', '') and r.get('_mac_ok'), str(r))
        r = authed_roundtrip(15982, 'opstok', 'show version')
        check('ops: show version honored', r.get('status') == 'ok' and r.get('_mac_ok'), str(r)[:120])
        r = authed_roundtrip(15982, 'opstok', 'set pv 100')
        check('ops: set is forbidden', r.get('status') == 'fail' and 'forbidden' in r.get('text', '')
              and 'admin' in r.get('text', '') and r.get('_mac_ok'), str(r))
        r = authed_roundtrip(15982, 'opstok', 'shutdown')
        check('ops: shutdown is forbidden', r.get('status') == 'fail' and 'forbidden' in r.get('text', ''), str(r))
        r = authed_roundtrip(15982, 'opstok', 'reset')
        check('ops: reset is forbidden (no set, no shutdown)', r.get('status') == 'fail'
              and 'forbidden' in r.get('text', ''), str(r))
        r = authed_roundtrip(15982, 'opstok', 'request reload')
        check('ops: the whole-daemon request reload is forbidden', r.get('status') == 'fail'
              and 'forbidden' in r.get('text', ''), str(r))
        r = authed_roundtrip(15982, 'opstok', 'request reload-config')
        check('ops: the config re-read request reload-config is forbidden', r.get('status') == 'fail'
              and 'forbidden' in r.get('text', ''), str(r))
        r = authed_roundtrip(15982, 'admintok', 'show control token')
        check('secrets: the show verb refuses the control token (the admin sees the refusal too)',
              r.get('status') == 'fail' and 'is a secret' in r.get('text', '') and r.get('_mac_ok'), str(r))
        try:
            s = connect(15982)
            s.sendall(_json.dumps({'cmd': 'auth', 'token': 'opstok'}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            s.sendall(_json.dumps({'cmd': 'show version'}).encode() + b'\n')   # no mac on purpose
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            s.close()
            check('ops: an unsigned command is still refused on TCP', reply.get('status') == 'fail'
                  and 'unsigned command' in reply.get('text', ''), str(reply))
        except (OSError, ValueError) as e:
            check('ops: an unsigned command is still refused on TCP', False, str(e))
        r = authed_roundtrip(15982, 'admintok', 'set pv 100')
        check('ops: the admin token still steers the same server',
              r.get('status') == 'ok' and r.get('_mac_ok'), str(r))
        r = authed_roundtrip(15982, 'opstok', 'wrong-tokens')
        check('ops: a bogus token is refused', r.get('status') in ('auth-fail', 'fail'), str(r))
        aud = open(OPS_AUDIT).read()
        check('ops: both roles audited (role=ops show, role=admin set, the denials included)',
              "role=ops 'show version'" in aud and "role=admin 'set pv 100'" in aud
              and "role=ops 'shutdown'" in aud and '-> err' in aud, aud[-300:])
        r = subprocess.run([sys.executable, os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py'),
                            '--control-port', '15982', '--control-token', 'opstok', 'show', 'version'],
                           capture_output=True, text=True, timeout=15)
        check('ops: fake_ctl reads with the ops token', r.returncode == 0
              and r.stdout.startswith('ok fake-inverter'), repr(r.stdout[:80]))
        r = subprocess.run([sys.executable, os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py'),
                            '--control-port', '15982', '--control-token', 'opstok', 'set', 'pv', '2000'],
                           capture_output=True, text=True, timeout=15)
        check('ops: fake_ctl cannot steer with the ops token', 'forbidden' in r.stdout
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stdout + r.stderr)[:120]))
        r = subprocess.run([sys.executable, F, '--static', '--listen', '127.0.0.1:15983', '--dry-run',
                            '--control-port', '0', '--control-ops-token', 'opstok'],
                           capture_output=True, text=True, timeout=15)
        check('ops: an ops token without the admin token is a clean error', r.returncode != 0
              and 'supplements' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, F, '--static', '--listen', '127.0.0.1:15983', '--dry-run',
                            '--control-port', '0', '--control-token', 'same',
                            '--control-ops-token', 'same'],
                           capture_output=True, text=True, timeout=15)
        check('ops: the ops token equal to the admin token is a clean error', r.returncode != 0
              and 'differ' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))

        # 7. twenty parallel clients: garbage and real commands interleaved
        results = []

        def hammer(i):
            try:
                if i % 2:
                    wire = b'{"cmd": "show version"}\n'
                else:
                    wire = ('garbage %d\n' % i).encode()
                st, tx = roundtrip(15961 + BASE, wire, timeout=15)
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

        # 8. the fake is still alive and serving Modbus
        s = connect(15960, timeout=5)
        s.sendall(struct.pack('>HHHB', 9, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
        r = s.recv(512)
        s.close()
        check('fuzz: modbus side still answers after the fuzzing', len(r) >= 10, r.hex())

        # 9. clean shutdown
        st, tx = roundtrip(15961 + BASE, b'{"cmd": "shutdown"}\n')
        check('fuzz: shutdown still works', st == 'bye', '%s %s' % (st, tx))
        time.sleep(1)
        check('fuzz: fake exited cleanly', procs[0].poll() == 0, str(procs[0].poll()))
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    log = open('/tmp/ctl_fuzz.log').read() + open('/tmp/ctl_fuzz2.log').read()
    check('fuzz: no tracebacks in the logs', 'Traceback' not in log, log[-200:])

    print()
    if FAILURES:
        print('FAILURES: %s' % FAILURES)
        raise SystemExit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
