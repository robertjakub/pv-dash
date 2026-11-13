#!/usr/bin/env python3
"""Control-protocol fuzz for the dashboard: malformed, hostile and degenerate
JSON-line requests against the control server. The server must answer with a
well-formed JSON frame (or close cleanly) and stay alive and serving
afterwards.

  python3 tests/suites/dashboard-control-fuzz.py

Checks: ALL PASS (or a FAILURES list; exit 1). A dead daemon or a refused
port fails its named check — the suite never tracebacks.
"""
import json as _json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'harness'))
from harness import *   # the boot: the gate, SCRATCH, PROFILE, BASE, the NOTE stamp — the shared check accumulator

P = os.path.join(REPO, 'apps', 'dashboard', 'bin', 'dashboard.py')
TOKEN = 'sekrit'
PROM_PORT = 15970 + BASE     # the stub Prometheus
HTTP_PORT = 15971 + BASE     # the dashboard's page/proxy surface
CTRL_PORT = 15972 + BASE     # the dashboard's control server (token'd: the F5 rule)
AUTH_PORT = CTRL_PORT
OPS_TOKEN = 'opssecret'
OPS_HTTP_PORT = 15973 + BASE   # the ops-token'd dashboard (the read-only role, §6c)
OPS_CTRL_PORT = 15974 + BASE
PAGES_PORT = 15975 + BASE    # the token'd page (the F21 auth round)
PAGES_CTL = 15977 + BASE


def wait_file(path, timeout=10):
    """The control rebind's socket file: it exists when the rebound control
    says it does — poll-stat instead of a blind sleep. False when it never
    appeared — the caller fails its named check."""
    end = time.monotonic() + timeout
    while not os.path.exists(path):
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)
    return True

METRICS_PORT = 15976 + BASE  # the main instance's /metrics (the metrics-acl round)


class PromStub(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"success","data":{"result":[]}}')

    def log_message(self, *a):
        pass


def wiremac(payload):   # the suite's thin wrapper: the TOKEN'd frame mac
    return wire_mac(TOKEN, payload)


def signed(cmd):   # the signed wire form (the token'd server refuses the unsigned)
    return signed_wire(cmd, TOKEN)


def ops_roundtrip(cmd, token=OPS_TOKEN, port=None, unsigned=False, timeout=5.0):
    """The suite's thin wrapper: OPS_CTRL_PORT is the default port."""
    return ops_control_roundtrip(cmd, token, port or OPS_CTRL_PORT, unsigned, timeout)


def roundtrip(port, wire_bytes, timeout=5.0):
    """The suite's thin wrapper: on the token'd control ports the handshake
    runs first (the F5 rule: a TCP control port refuses to start without a
    token)."""
    return control_roundtrip(port, wire_bytes, timeout, (AUTH_PORT, PAGES_CTL), TOKEN)



def main():
    stub = HTTPServer(('127.0.0.1', PROM_PORT), PromStub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, P, '--listen', '127.0.0.1:%d' % (HTTP_PORT),
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--config-js', os.path.join(REPO, 'apps', 'dashboard', 'examples', 'config.js'),
                                       '--metrics-server', '--metrics-listen', '127.0.0.1:%d' % METRICS_PORT,
                                       '--control-port', str(CTRL_PORT), '--control-token', TOKEN,
                                       '--audit-log', '-'],
                                      stdout=open(os.path.join(SCRATCH, 'dash_ctl_fuzz.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(HTTP_PORT):
            check('fuzz: the dashboard came up (page port %d)' % HTTP_PORT, False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'dash_ctl_fuzz.log'))

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
            (b'{"cmd": "show stat\xc3\xbc\x7f"}\n', 'unicode cmd'),
            (b'\n', 'empty line'),
            (b'   \n', 'whitespace line'),
        ]
        for wire, label in garbage:
            st, tx = roundtrip(CTRL_PORT, wire)
            check('fuzz: %s answered with a JSON frame' % label, st in ('ok', 'fail'), '%s %s' % (st, tx))
            check('fuzz: %s rejected cleanly' % label, st == 'fail', '%s %s' % (st, tx))

        # 2. the overlong request (1 MB): answered or closed, never a crash
        st, tx = roundtrip(CTRL_PORT, signed('show version')[:-2] + b', "pad": "' + b'a' * (1024 * 1024) + b'"}\n',
                           timeout=10)
        check('fuzz: 1 MB request handled', st in ('ok', 'fail', 'dead'), '%s %s' % (st, tx[:80]))

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
        try:
            s = connect(CTRL_PORT)
            s.sendall(b'{"cmd": "show version"}')
            s.close()
        except OSError as e:
            check('fuzz: frameless close does not wedge the server', False, str(e))
        else:
            st, tx = roundtrip(CTRL_PORT, signed('show version'))
            check('fuzz: frameless close does not wedge the server', st == 'ok', '%s %s' % (st, tx))

        # 5. ping flood: 100 keepalives, then a real command still works
        ok = True
        for _ in range(100):
            st, tx = roundtrip(CTRL_PORT, signed('ping'), timeout=10)
            ok = ok and st == 'ok'
        check('fuzz: ping flood survives (100x)', ok)
        st, tx = roundtrip(CTRL_PORT, signed('show version'))
        check('fuzz: real command after the flood', st == 'ok', '%s %s' % (st, tx))

        # 5b. the wire's help branch speaks the commands (the rider)
        st, tx = roundtrip(CTRL_PORT, signed('help clear'))
        check('rider: the wire help describes a command row',
              st == 'ok' and 'restore a setting' in tx, '%s %s' % (st, tx))
        st, tx = roundtrip(CTRL_PORT, signed('help request'))
        check('rider: the wire help over a fully-hidden namespace answers the node one-liner',
              st == 'ok' and tx == 'the state machinery: the dump written and restored, the daemon reloaded', '%s %s' % (st, tx))
        st, tx = roundtrip(CTRL_PORT, signed('help bogus'))
        check('rider: the unknown topic is the reworded two-space error',
              st == 'fail' and tx == 'unknown command or setting bogus (try ?)', '%s %s' % (st, tx))

        # 5c. the dump-interval knob (the family unification, the cache's
        #     golden shape): no dump path configured here — the gate answers
        st, tx = roundtrip(CTRL_PORT, signed('show dump-interval'))
        check('rider: show dump-interval without a dump path is a clean err',
              st == 'fail' and tx.startswith('dump-interval needs a dump path'), '%s %s' % (st, tx))
        st, tx = roundtrip(CTRL_PORT, signed('set dump-interval 5'))
        check('rider: set dump-interval without a dump path is a clean err',
              st == 'fail' and tx.startswith('dump-interval needs a dump path'), '%s %s' % (st, tx))

        # 6. the auth abuse is rejected, the real token works, the unsigned refused
        bad = True
        for _ in range(30):
            st, tx = roundtrip(CTRL_PORT, b'{"cmd": "auth", "token": "guess-%d"}\n' % _)
            bad = bad and st == 'fail' and 'bad token' in tx
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
            check('fuzz: the unsigned command is refused on TCP', reply.get('status') == 'fail'
                  and 'unsigned' in reply.get('text', ''), str(reply))
            s.sendall(signed('show version'))
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: the signed command verifies and answers', reply.get('status') == 'ok'
                  and 'dashboard' in reply.get('text', ''), str(reply))
            s.sendall(signed('sh\u00f6w versi\u00f6n'))   # the mac covers the client's utf-8 bytes
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: the utf-8 command folds to the 8-bit grammar and answers', reply.get('status') == 'ok'
                  and 'dashboard' in reply.get('text', ''), str(reply))
            s.close()
        except (OSError, ValueError) as e:
            check('fuzz: the right token authenticates', False, str(e))

        # 6b. the token as a file: reference on the env: honored like the flag
        open(os.path.join(SCRATCH, 'dash_ctl_fuzz_token'), 'w').write(TOKEN + '\n')
        os.chmod(os.path.join(SCRATCH, 'dash_ctl_fuzz_token'), 0o600)
        r = subprocess.run([sys.executable, os.path.join(REPO, 'apps', 'dashboard', 'bin', 'dashboard-cli.py'),
                            '--control-port', str(CTRL_PORT), 'show', 'version'],
                           capture_output=True, text=True, timeout=15,
                           env={**os.environ, 'CONTROL_TOKEN': 'file:' + os.path.join(SCRATCH, 'dash_ctl_fuzz_token')})
        check('fuzz: dashboard_ctl honors CONTROL_TOKEN=file:...', r.returncode == 0
              and 'dashboard' in r.stdout, repr(r.stdout[:80]))

        # 6c. the read-only ops token: show allowed, steering forbidden; both audited
        OPS_AUDIT = os.path.join(SCRATCH, 'dash_ctl_fuzz_ops_audit.log')
        open(OPS_AUDIT, 'w').write('')
        procs.append(subprocess.Popen([sys.executable, P, '--listen', '127.0.0.1:%d' % (OPS_HTTP_PORT),
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--control-port', str(OPS_CTRL_PORT), '--control-token', 'admintok2',
                                       '--control-ops-token', OPS_TOKEN, '--audit-log', OPS_AUDIT],
                                      stdout=open(os.path.join(SCRATCH, 'dash_ctl_fuzz_ops.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(OPS_HTTP_PORT):
            check('ops: the ops dashboard came up (page port %d)' % OPS_HTTP_PORT, False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'dash_ctl_fuzz_ops.log'))
        st, tx, macok = ops_roundtrip('show version')
        check('ops: the ops token authenticates, show version honored, mac\'d with the ops key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show version')
        check('ops: show version honored', st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show knobs')
        check('ops: show knobs honored (the dictionary of the registry, a show verb)',
              st == 'ok' and macok and '--listen' in tx, '%s %s' % (st, tx[:160]))
        st, tx, macok = ops_roundtrip('set log-level DEBUG')
        check('ops: set is forbidden', st == 'fail' and 'forbidden' in tx and 'admin' in tx and macok,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request reload-config')
        check('ops: request reload-config is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request reload')
        check('ops: the whole-daemon request reload is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show control-token', token='admintok2')
        check('secrets: the show verb refuses the control token (the admin sees the refusal too)',
              st == 'fail' and 'is a secret' in tx and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('shutdown')
        check('ops: shutdown is forbidden', st == 'fail' and 'forbidden' in tx and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show version', unsigned=True)
        check('ops: an unsigned command is still refused first', st == 'fail' and 'unsigned command' in tx,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('set log-level DEBUG', token='admintok2')
        check('ops: the admin token still steers the same server, mac\'d with the admin key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        try:
            aud = open(OPS_AUDIT).read()
            ok = ("role=ops cmd='show version'" in aud and "role=admin cmd='set log-level DEBUG'" in aud
                  and "role=ops cmd='shutdown'" in aud and 'result=err' in aud)
        except OSError as e:
            aud, ok = str(e), False
        check('ops: both roles audited (role=ops show, role=admin set, the denials included)',
              ok, aud[-300:])

        # the query log: the admin switch flips the page handler's logger
        # level — on, a proxied query logs at info; off, it sinks to debug
        import urllib.request, urllib.error
        def query_lines():
            try:
                body = open(os.path.join(SCRATCH, 'dash_ctl_fuzz_ops.log')).read()
            except OSError as e:
                return ['the daemon log is unreadable: %s' % e]
            return [l for l in body.splitlines() if 'GET /prom/metrics ->' in l]
        st, tx, macok = ops_roundtrip('set log-queries on', token='admintok2')
        check('log-queries: the admin switches it on', st == 'ok' and macok, '%s %s' % (st, tx))
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/prom/metrics' % OPS_HTTP_PORT, timeout=5)
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass                     # any status logs the line; the prom leg may wobble
        time.sleep(0.5)
        lines = query_lines()
        check('log-queries: the proxied query logs at info', lines and 'INFO' in lines[-1],
              repr(lines[-1] if lines else 'no GET line in the daemon log'))
        st, tx, macok = ops_roundtrip('set log-queries off', token='admintok2')
        check('log-queries: the admin switches it off', st == 'ok' and macok, '%s %s' % (st, tx))
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/prom/metrics' % OPS_HTTP_PORT, timeout=5)
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass
        time.sleep(0.5)
        lines = query_lines()
        check('log-queries: off sinks the line to debug', lines and 'DEBUG' in lines[-1],
              repr(lines[-1] if lines else 'no GET line in the daemon log'))

        r = subprocess.run([sys.executable, os.path.join(REPO, 'apps', 'dashboard', 'bin', 'dashboard-cli.py'),
                            '--control-port', str(OPS_CTRL_PORT), '--control-token', OPS_TOKEN,
                            'show', 'version'], capture_output=True, text=True, timeout=15)
        check('ops: dashboard_ctl reads with the ops token', r.returncode == 0
              and 'ok dashboard' in r.stdout, repr(r.stdout[:80]))
        r = subprocess.run([sys.executable, os.path.join(REPO, 'apps', 'dashboard', 'bin', 'dashboard-cli.py'),
                            '--control-port', str(OPS_CTRL_PORT), '--control-token', OPS_TOKEN,
                            'shutdown'], capture_output=True, text=True, timeout=15)
        check('ops: dashboard_ctl cannot steer with the ops token', 'forbidden' in r.stdout
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stdout + r.stderr)[:120]))
        r = subprocess.run([sys.executable, P, '--listen', '127.0.0.1:%d' % (OPS_HTTP_PORT),
                            '--control-port', str(OPS_CTRL_PORT), '--control-ops-token', 'x', '--dry-run'],
                           capture_output=True, text=True, timeout=15)
        check('ops: an ops token without the admin token is a clean error', r.returncode != 0
              and 'supplements' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, P, '--listen', '127.0.0.1:%d' % (OPS_HTTP_PORT),
                            '--control-port', str(OPS_CTRL_PORT), '--control-token', 'same',
                            '--control-ops-token', 'same', '--dry-run'],
                           capture_output=True, text=True, timeout=15)
        check('ops: the ops token equal to the admin token is a clean error', r.returncode != 0
              and 'differ' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))

        if PROFILE == 'quick':
            raise QuickDone()   # quick: the core sections only
        # 7. twenty parallel clients: garbage and real commands interleaved
        results = []

        def hammer(i):
            try:
                if i % 2:
                    wire = signed('show version')
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
              and all(st in ('ok', 'fail') for _, st in results), str(results[:6]))

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

        # 8b. the page's auth (F21): the bearer token on every route, the
        #     ?auth= bootstrap exchanging for the session cookie
        def page_get(port, path, headers=b''):
            try:
                s = connect(port, timeout=5)
                s.sendall(b'GET ' + path + b' HTTP/1.1\r\nHost: localhost\r\n' + headers +
                          b'Connection: close\r\n\r\n')
                r = b''
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    r += chunk
                s.close()
                return r
            except OSError as e:
                return ('boom: %s' % e).encode()

        r = subprocess.run([sys.executable, P, '--listen', '0.0.0.0:%d' % (PAGES_PORT), '--dry-run',
                            '--upstream', 'http://127.0.0.1:%d' % PROM_PORT], capture_output=True, text=True, timeout=15)
        check('page auth: a token-less non-loopback bind refuses to start (F21)',
              r.returncode != 0 and 'refusing to expose the page beyond loopback' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-160:]))
        r = subprocess.run([sys.executable, P, '--listen', '0.0.0.0:%d' % (PAGES_PORT), '--dry-run',
                            '--auth-token', 'ptok',
                            '--upstream', 'http://127.0.0.1:%d' % PROM_PORT], capture_output=True, text=True, timeout=15)
        check('page auth: a non-loopback bind with a token starts', r.returncode == 0, repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, P, '--listen', '127.0.0.1:%d' % (PAGES_PORT), '--dry-run',
                            '--upstream', 'http://127.0.0.1:%d' % PROM_PORT], capture_output=True, text=True, timeout=15)
        check('page auth: the loopback default needs no token', r.returncode == 0, repr((r.stderr + r.stdout)[-140:]))

        procs.append(subprocess.Popen([sys.executable, P, '--listen', '127.0.0.1:%d' % (PAGES_PORT),
                                       '--auth-token', 'ptok',
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--config-js', os.path.join(REPO, 'apps', 'dashboard', 'examples', 'config.js'),
                                       '--control-port', str(PAGES_CTL), '--control-token', TOKEN,
                                       '--audit-log', '-'],
                                      stdout=open(os.path.join(SCRATCH, 'dash_ctl_fuzz_pages.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(PAGES_PORT):
            check('page auth: the token\'d page came up (page port %d)' % PAGES_PORT, False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'dash_ctl_fuzz_pages.log'))
        r = page_get(PAGES_PORT, b'/config.js')
        check('page auth: the token-less read is a 401', r.startswith(b'HTTP/1.1 401')
              and b'WWW-Authenticate: Bearer' in r, r[:60])
        r = page_get(PAGES_PORT, b'/config.js?auth=ptok')
        check('page auth: the ?auth= bootstrap serves and sets the cookie',
              r.startswith(b'HTTP/1.1 200') and b'Set-Cookie: auth=ptok' in r, r[:80])
        r = page_get(PAGES_PORT, b'/config.js', b'Cookie: auth=ptok\r\n')
        check('page auth: the session cookie reads', r.startswith(b'HTTP/1.1 200'), r[:40])
        r = page_get(PAGES_PORT, b'/config.js', b'Authorization: Bearer ptok\r\n')
        check('page auth: the bearer header reads', r.startswith(b'HTTP/1.1 200'), r[:40])
        r = page_get(PAGES_PORT, b'/config.js', b'Authorization: Bearer wrong\r\n')
        check('page auth: a wrong bearer is a 401', r.startswith(b'HTTP/1.1 401'), r[:40])
        st, tx = roundtrip(PAGES_CTL, signed('set auth-token off'))
        check('page auth: startup-only — the off refuses (the dump-key treatment)',
              st == 'fail' and 'restart required (startup-only knob)' in tx, '%s %s' % (st, tx))
        st, tx = roundtrip(PAGES_CTL, signed('set auth-token ptok2'))
        check('page auth: startup-only — the rotation refuses too',
              st == 'fail' and 'restart required (startup-only knob)' in tx, '%s %s' % (st, tx))
        r = page_get(PAGES_PORT, b'/config.js', b'Authorization: Bearer ptok\r\n')
        check('page auth: the configured token still reads (no live rotation)', r.startswith(b'HTTP/1.1 200'), r[:40])
        # the tokenless loopback page serves (the bind is the auth — the F21 shape)
        procs.append(subprocess.Popen([sys.executable, P, '--listen', '127.0.0.1:%d' % (15980 + BASE),
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--config-js', os.path.join(REPO, 'apps', 'dashboard', 'examples', 'config.js')],
                                      stdout=open(os.path.join(SCRATCH, 'dash_ctl_fuzz_tokless.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(15980 + BASE):
            check('page auth: the tokenless page came up (page port %d)' % (15980 + BASE), False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'dash_ctl_fuzz_tokless.log'))
        r = page_get(15980 + BASE, b'/config.js')
        check('page auth: the tokenless loopback page serves', r.startswith(b'HTTP/1.1 200'), r[:40])

        # 8b2. the audit family's one shape on the DSH: the daily knob's live
        #      name (the UTC-midnight trigger switches on the wire), the
        #      bounds refuse at the resolve layer
        st, tx = roundtrip(PAGES_CTL, signed('set audit-daily on'))
        check('dash audit-daily: the daily trigger switches on',
              st == 'ok' and tx.startswith('audit-daily=on'), '%s %s' % (st, tx))
        st, tx = roundtrip(PAGES_CTL, signed('show audit-daily'))
        check('dash audit-daily: show audit rotate daily answers on',
              st == 'ok' and tx == 'audit-daily=on', '%s %s' % (st, tx))
        st, tx = roundtrip(PAGES_CTL, signed('clear audit-daily'))
        check('dash audit-daily: the daily trigger unsets to the configured off',
              st == 'ok' and tx.startswith('audit-daily=off'), '%s %s' % (st, tx))
        env = dict(os.environ, AUDIT_FILES='0')
        r = subprocess.run([sys.executable, P, '--dry-run', '--control-port', '0'],
                           capture_output=True, text=True, env=env)
        check('dash audit: $AUDIT_FILES=0 refuses at start (the bound, no traceback)',
              r.returncode == 1 and 'must be 1..100' in r.stdout + r.stderr
              and 'Traceback' not in r.stdout + r.stderr, (r.stdout + r.stderr)[-160:])

        # 8c. the control listener family (the cache's, family-wide): the
        #     live rebind — the tokenless TCP rebind refuses on the live
        #     wire (F5), the token'd rebind swaps the socket, the old one
        #     closes, the group-accessible mode re-modes the unix socket live
        REB_HTTP, REB_TCP = 15978 + BASE, 15979 + BASE
        reb_sock = '/tmp/dashboard-%d.socket' % REB_HTTP
        procs.append(subprocess.Popen([sys.executable, P, '--listen', '127.0.0.1:%d' % (REB_HTTP),
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--audit-log', '-'],
                                      stdout=open(os.path.join(SCRATCH, 'dash_ctl_fuzz_rebind.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(REB_HTTP):
            check('family listener: the rebind dashboard came up (page port %d)' % REB_HTTP, False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'dash_ctl_fuzz_rebind.log'))

        def rctl(*cmds, port=None, token=None):
            r = subprocess.run([sys.executable, os.path.join(REPO, 'apps', 'dashboard', 'bin', 'dashboard-cli.py'),
                                '--control-port', port if port is not None else reb_sock]
                               + (['--control-token', token] if token else []) + list(cmds),
                               capture_output=True, text=True, timeout=15)
            return r.stdout.strip()

        def sock_mode():
            try:
                return oct(os.stat(reb_sock).st_mode & 0o777)
            except OSError:
                return 'gone'
        check('family listener: the rebound control socket came up', wait_file(reb_sock), reb_sock)
        check('family listener: the default unix socket is 0600',
              sock_mode() == oct(0o600), sock_mode())
        tx = rctl('set control-socket-group on')
        check('family listener: set control socket-group on re-modes the live socket 0660',
              tx.startswith('ok control-socket-group=on') and sock_mode() == oct(0o660),
              tx[:120] + ' ' + sock_mode())
        tx = rctl('set control-socket-group off')
        check('family listener: set control socket-group off re-modes it back 0600',
              tx.startswith('ok control-socket-group=off') and sock_mode() == oct(0o600),
              tx[:120] + ' ' + sock_mode())
        tx = rctl('set control-port %d' % REB_TCP)
        check('family listener: a tokenless TCP rebind refuses on the live wire (F5)',
              tx.startswith('% error: control-port cannot serve TCP without a token'), tx[:140])
        tx = rctl('show control-token')
        check('family listener: the show verb still refuses the secret', tx.startswith('% error') and 'is a secret' in tx,
              tx[:140])
        tx = rctl('set control-token rtok2')
        check('family listener: startup-only — the token set refuses (the instance stays tokenless)',
              tx.startswith('% error: restart required (startup-only knob)'), tx[:120])
        # the token'd rebind: a spawned-token instance (the token is startup-only)
        procs.append(subprocess.Popen([sys.executable, P, '--listen', '127.0.0.1:%d' % (15981 + BASE),
                                       '--upstream', 'http://127.0.0.1:%d' % PROM_PORT,
                                       '--audit-log', '-', '--control-port', '%d' % (15982 + BASE),
                                       '--control-token', 'rtok2'],
                                      stdout=open(os.path.join(SCRATCH, 'dash_ctl_fuzz_rebind2.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(15981 + BASE):
            check('family listener: the tokenized rebind dashboard came up (page port %d)' % (15981 + BASE), False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'dash_ctl_fuzz_rebind2.log'))
        tx = rctl('set control-port %d' % REB_TCP, port=str(15982 + BASE), token='rtok2')
        check('family listener: the tokenized TCP rebind succeeds', tx.startswith('ok control-port=127.0.0.1:%d' % REB_TCP),
              tx[:120])
        tx = rctl('show version', port=str(15982 + BASE))
        check('family listener: the retired control port no longer answers', tx == '', tx[:120])
        tx = rctl('show version', port=str(REB_TCP), token='rtok2')
        check('family listener: the new TCP port speaks (signed with the token)',
              tx.startswith('ok dashboard'), tx[:120])
        tx = rctl('clear control-port', port=str(REB_TCP), token='rtok2')
        check('family listener: clear restores the configured target',
              tx.startswith('ok control-port=127.0.0.1:%d' % (15982 + BASE)), tx[:120])
        tx = rctl('show version', port=str(15982 + BASE), token='rtok2')
        check('family listener: the restored port speaks', tx.startswith('ok dashboard'), tx[:120])

        # 8b. the metrics-acl gate (the cache's logic, the dashboard's
        # surface): the accept-time IP gate on the /metrics listener — the
        # ACL first, then the caps, the token's 401 only past both
        def metrics_raw():
            try:
                s = socket.create_connection(('127.0.0.1', METRICS_PORT), timeout=5)
            except OSError:
                return b''
            try:
                s.sendall(b'GET /metrics HTTP/1.0\r\n\r\n')
                buf = b''
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                return buf
            except (ConnectionResetError, BrokenPipeError):
                return b''
            finally:
                s.close()

        st, tx = roundtrip(CTRL_PORT, signed('set metrics-acl none'))
        check('metrics acl: set none answers ok', st == 'ok' and tx.startswith('metrics-acl=none'), '%s %s' % (st, tx[:80]))
        check('metrics acl: none closes the client without a reply', metrics_raw() == b'', repr(metrics_raw()[:40]))
        st, tx = roundtrip(CTRL_PORT, signed('show metrics-acl'))
        check('metrics acl: the none show', st == 'ok' and tx == 'metrics-acl=none', '%s %s' % (st, tx[:60]))
        st, tx = roundtrip(CTRL_PORT, signed('show metrics-acl-table'))
        check('metrics acl: none spells the deny-any chain',
              st == 'ok' and tx.startswith('metrics-acl-table') and 'deny 0.0.0.0/0' in tx, '%s %s' % (st, tx[:80]))
        st, tx = roundtrip(CTRL_PORT, signed('set metrics-acl table'))
        check('metrics acl: the show word is not a value (the pointer to the report)',
              st == 'fail' and 'show metrics-acl-table' in tx, '%s %s' % (st, tx[:120]))
        st, tx = roundtrip(CTRL_PORT, signed('set metrics-acl 127.0.0.1'))
        check('metrics acl: the whitelist set canonicalizes', st == 'ok' and tx.startswith('metrics-acl=127.0.0.1/32'), '%s %s' % (st, tx[:80]))
        check('metrics acl: the whitelist serves the lab', metrics_raw().startswith(b'HTTP/1.0 200'))
        st, tx = roundtrip(CTRL_PORT, signed('clear metrics-acl'))
        check('metrics acl: clear restores the configured value', st == 'ok' and tx.startswith('metrics-acl=any'), '%s %s' % (st, tx[:80]))
        check('metrics acl: any serves again', metrics_raw().startswith(b'HTTP/1.0 200'))

        # 9. clean shutdown
        st, tx = roundtrip(CTRL_PORT, signed('shutdown'))
        check('fuzz: shutdown still works', st == 'bye', '%s %s' % (st, tx))
        time.sleep(1)
        check('fuzz: dashboard exited cleanly', procs[0].poll() == 0, str(procs[0].poll()))
    except QuickDone:
        pass
    finally:
        stub.shutdown()
        for p in procs:
            if p.poll() is None:
                p.kill()
    log = ''
    for f in (os.path.join(SCRATCH, 'dash_ctl_fuzz.log'), os.path.join(SCRATCH, 'dash_ctl_fuzz_ops.log'), os.path.join(SCRATCH, 'dash_ctl_fuzz_pages.log')):
        if os.path.exists(f):          # quick skips the sections that own some of these
            log += open(f).read()
    ok = 'Traceback' not in log
    check('fuzz: no tracebacks in the logs', ok, log[-200:])

    print()
    print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
    print()
    if FAILURES:
        print('FAILURES: %s' % FAILURES)
        raise SystemExit(1)
    print('ALL PASS')


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print()
        print('INTERRUPTED')
        raise SystemExit(130)
    except Exception as e:
        print('FAIL suite crashed: %s: %s' % (type(e).__name__, e))
        if FAILURES:
            print('FAILURES: %s' % FAILURES)
        sys.exit(1)
