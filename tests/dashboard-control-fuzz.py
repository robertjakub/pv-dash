#!/usr/bin/env python3
"""Control-protocol fuzz for the dashboard: malformed, hostile and degenerate
JSON-line requests against the control server. The server must answer with a
well-formed JSON frame (or close cleanly) and stay alive and serving
afterwards.

  python3 tests/dashboard-control-fuzz.py

Checks: ALL PASS (or a FAILURES list; exit 1).
"""
import hashlib
import hmac
import json as _json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(REPO, 'dashboard', 'bin', 'dashboard.py')
FAILURES = []
TOKEN = 'sekrit'
PROM_PORT = 15970     # the stub Prometheus
HTTP_PORT = 15971     # the dashboard's page/proxy surface
CTRL_PORT = 15972     # the dashboard's control server (token'd: the F5 rule)
AUTH_PORT = CTRL_PORT
OPS_TOKEN = 'opssecret'
OPS_HTTP_PORT = 15973   # the ops-token'd dashboard (the read-only role, §6c)
OPS_CTRL_PORT = 15974


class PromStub(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"success","data":{"result":[]}}')

    def log_message(self, *a):
        pass


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
    read one reply: (status, text, mac-verifies-with-the-same-token)."""
    port = port or OPS_CTRL_PORT
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
    On the control port the token handshake runs first (the F5 rule: a TCP
    control port refuses to start without a token)."""
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
    stub = HTTPServer(('127.0.0.1', PROM_PORT), PromStub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, P, '--port', str(HTTP_PORT), '--bind', '127.0.0.1',
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--control-port', str(CTRL_PORT), '--control-token', TOKEN,
                                       '--audit-log', '-'],
                                      stdout=open('/tmp/dash_ctl_fuzz.log', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.2)

        # 1. malformed and hostile frames (pre-auth): always a well-formed err reply
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
            (b'\n', 'empty line'),
            (b'   \n', 'whitespace line'),
        ]
        for wire, label in garbage:
            st, tx = roundtrip(CTRL_PORT, wire)
            check('fuzz: %s answered with a JSON frame' % label, st in ('ok', 'err'), '%s %s' % (st, tx))
            check('fuzz: %s rejected cleanly' % label, st == 'err', '%s %s' % (st, tx))

        # 2. the overlong request (1 MB): answered or closed, never a crash
        st, tx = roundtrip(CTRL_PORT, signed('show status')[:-2] + b', "pad": "' + b'a' * (1024 * 1024) + b'"}\n',
                           timeout=10)
        check('fuzz: 1 MB request handled', st in ('ok', 'err', 'dead'), '%s %s' % (st, tx[:80]))

        # 3. split packets: one byte at a time, the server assembles the frame
        try:
            s = connect(CTRL_PORT)
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
                  and 'dashboard' in obj.get('text', ''), str(obj))
        except (OSError, ValueError) as e:
            check('fuzz: byte-by-byte request assembled', False, str(e))

        # 4. no newline, then close: no crash, the server keeps serving
        s = connect(CTRL_PORT)
        s.sendall(b'{"cmd": "show status"}')
        s.close()
        st, tx = roundtrip(CTRL_PORT, signed('show version'))
        check('fuzz: frameless close does not wedge the server', st == 'ok', '%s %s' % (st, tx))

        # 5. ping flood: 100 keepalives, then a real command still works
        ok = True
        for _ in range(100):
            st, tx = roundtrip(CTRL_PORT, signed('ping'), timeout=10)
            ok = ok and st == 'ok'
        check('fuzz: ping flood survives (100x)', ok)
        st, tx = roundtrip(CTRL_PORT, signed('show status'))
        check('fuzz: real command after the flood', st == 'ok', '%s %s' % (st, tx))

        # 6. the auth abuse is rejected, the real token works, the unsigned refused
        bad = True
        for _ in range(30):
            st, tx = roundtrip(CTRL_PORT, b'{"cmd": "auth", "token": "guess-%d"}\n' % _)
            bad = bad and st == 'err' and 'bad token' in tx
        check('fuzz: 30 wrong tokens all rejected', bad)
        try:
            s = connect(CTRL_PORT)
            s.sendall(_json.dumps({'cmd': 'auth', 'token': TOKEN}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            auth = _json.loads(buf.decode())
            check('fuzz: the right token authenticates', auth.get('status') == 'ok'
                  and len(auth.get('mac', '')) == 64, str(auth))
            s.sendall(_json.dumps({'cmd': 'show version'}).encode() + b'\n')   # no mac on purpose
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: the unsigned command is refused on TCP', reply.get('status') == 'err'
                  and 'unsigned' in reply.get('text', ''), str(reply))
            s.sendall(signed('show version'))
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: the signed command verifies and answers', reply.get('status') == 'ok'
                  and 'dashboard' in reply.get('text', ''), str(reply))
            s.close()
        except (OSError, ValueError) as e:
            check('fuzz: the right token authenticates', False, str(e))

        # 6b. the token-file env var the help promises: honored like the flags
        open('/tmp/dash_ctl_fuzz_token', 'w').write(TOKEN + '\n')
        os.chmod('/tmp/dash_ctl_fuzz_token', 0o600)
        r = subprocess.run([sys.executable, os.path.join(REPO, 'dashboard', 'bin', 'dashboard-ctl.py'),
                            '--control-port', str(CTRL_PORT), 'show', 'version'],
                           capture_output=True, text=True, timeout=15,
                           env={**os.environ, 'CONTROL_TOKEN_FILE': '/tmp/dash_ctl_fuzz_token'})
        check('fuzz: dashboard_ctl honors CONTROL_TOKEN_FILE', r.returncode == 0
              and 'dashboard' in r.stdout, repr(r.stdout[:80]))
        r = subprocess.run([sys.executable, os.path.join(REPO, 'dashboard', 'bin', 'dashboard-ctl.py'),
                            '--control-port', str(CTRL_PORT), 'status'],
                           capture_output=True, text=True, timeout=15,
                           env={**os.environ, 'CONTROL_TOKEN': 'x',
                                'CONTROL_TOKEN_FILE': '/tmp/dash_ctl_fuzz_token'})
        check('fuzz: the token env + the token-file env is a clean error', r.returncode != 0
              and 'mutually exclusive' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-120:]))

        # 6c. the read-only ops token: show allowed, steering forbidden; both audited
        OPS_AUDIT = '/tmp/dash_ctl_fuzz_ops_audit.log'
        open(OPS_AUDIT, 'w').write('')
        procs.append(subprocess.Popen([sys.executable, P, '--port', str(OPS_HTTP_PORT), '--bind', '127.0.0.1',
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--control-port', str(OPS_CTRL_PORT), '--control-token', 'admintok2',
                                       '--control-ops-token', OPS_TOKEN, '--audit-log', OPS_AUDIT],
                                      stdout=open('/tmp/dash_ctl_fuzz_ops.log', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.2)
        st, tx, macok = ops_roundtrip('show status')
        check('ops: the ops token authenticates, show status honored, mac\'d with the ops key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show settings')
        check('ops: show settings honored', st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show knobs')
        check('ops: show knobs honored (the dictionary of the registry, a show verb)',
              st == 'ok' and macok and '--port' in tx and '# ---' in tx, '%s %s' % (st, tx[:160]))
        st, tx, macok = ops_roundtrip('set log-level DEBUG')
        check('ops: set is forbidden', st == 'err' and 'forbidden' in tx and 'admin' in tx and macok,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request reload')
        check('ops: request reload is forbidden', st == 'err' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('shutdown')
        check('ops: shutdown is forbidden', st == 'err' and 'forbidden' in tx and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show version', unsigned=True)
        check('ops: an unsigned command is still refused first', st == 'err' and 'unsigned command' in tx,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('set log-level DEBUG', token='admintok2')
        check('ops: the admin token still steers the same server, mac\'d with the admin key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        aud = open(OPS_AUDIT).read()
        check('ops: both roles audited (role=ops show, role=admin set, the denials included)',
              "role=ops 'show settings'" in aud and "role=admin 'set log-level DEBUG'" in aud
              and "role=ops 'shutdown'" in aud and '-> err' in aud, aud[-300:])
        r = subprocess.run([sys.executable, os.path.join(REPO, 'dashboard', 'bin', 'dashboard-ctl.py'),
                            '--control-port', str(OPS_CTRL_PORT), '--control-token', OPS_TOKEN,
                            'show', 'version'], capture_output=True, text=True, timeout=15)
        check('ops: dashboard_ctl reads with the ops token', r.returncode == 0
              and 'ok dashboard' in r.stdout, repr(r.stdout[:80]))
        r = subprocess.run([sys.executable, os.path.join(REPO, 'dashboard', 'bin', 'dashboard-ctl.py'),
                            '--control-port', str(OPS_CTRL_PORT), '--control-token', OPS_TOKEN,
                            'shutdown'], capture_output=True, text=True, timeout=15)
        check('ops: dashboard_ctl cannot steer with the ops token', 'forbidden' in r.stdout
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stdout + r.stderr)[:120]))
        r = subprocess.run([sys.executable, P, '--port', str(OPS_HTTP_PORT), '--bind', '127.0.0.1',
                            '--control-port', str(OPS_CTRL_PORT), '--control-ops-token', 'x', '--dry-run'],
                           capture_output=True, text=True, timeout=15)
        check('ops: an ops token without the admin token is a clean error', r.returncode != 0
              and 'supplements' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, P, '--port', str(OPS_HTTP_PORT), '--bind', '127.0.0.1',
                            '--control-port', str(OPS_CTRL_PORT), '--control-token', 'same',
                            '--control-ops-token', 'same', '--dry-run'],
                           capture_output=True, text=True, timeout=15)
        check('ops: the ops token equal to the admin token is a clean error', r.returncode != 0
              and 'differ' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))

        # 7. twenty parallel clients: garbage and real commands interleaved
        results = []

        def hammer(i):
            try:
                if i % 2:
                    wire = signed('show settings')
                else:
                    wire = ('garbage %d\n' % i).encode()
                st, tx = roundtrip(CTRL_PORT, wire, timeout=15)
                results.append((i, st))
            except OSError as e:
                results.append((i, 'boom: %s' % e))

        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        check('fuzz: 20 parallel clients all answered', len(results) == 20
              and all(st in ('ok', 'err') for _, st in results), str(results[:6]))

        # 8. the page surface is still alive and serving after the fuzzing
        try:
            s = connect(HTTP_PORT, timeout=5)
            s.sendall(b'GET /config.js HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            r = b''
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                r += chunk
            s.close()
            check('fuzz: the page surface still answers after the fuzzing',
                  r.startswith(b'HTTP/1.1 200'), r[:40])
        except OSError as e:
            check('fuzz: the page surface still answers after the fuzzing', False, str(e))

        # 9. clean shutdown
        st, tx = roundtrip(CTRL_PORT, signed('shutdown'))
        check('fuzz: shutdown still works', st == 'bye', '%s %s' % (st, tx))
        time.sleep(1)
        check('fuzz: dashboard exited cleanly', procs[0].poll() == 0, str(procs[0].poll()))
    finally:
        stub.shutdown()
        for p in procs:
            if p.poll() is None:
                p.kill()
    log = open('/tmp/dash_ctl_fuzz.log').read() + open('/tmp/dash_ctl_fuzz_ops.log').read()
    check('fuzz: no tracebacks in the logs', 'Traceback' not in log, log[-200:])

    print()
    if FAILURES:
        print('FAILURES: %s' % FAILURES)
        raise SystemExit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
