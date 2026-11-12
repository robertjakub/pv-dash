#!/usr/bin/env python3
"""Control-protocol fuzz for modbus-cache: malformed, hostile and degenerate
JSON-line requests against the control server. The server must answer with
a well-formed JSON frame (or close cleanly) and stay alive and serving
afterwards.

  python3 tests/cache-control-fuzz.py

Checks: ALL PASS (or a FAILURES list; exit 1). A dead daemon or a refused
port fails its named check — the suite never tracebacks.
"""
import json as _json
import os
import struct
import subprocess
import sys
import threading
import time

from harness import *   # the boot: the gate, SCRATCH, PROFILE, BASE, the NOTE stamp — the shared check accumulator

P = os.path.join(REPO, 'cache', 'bin', 'modbus-cache.py')
F = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')

TOKEN = 'sekrit'
AUTH_PORT = 15965 + BASE   # the fuzz cache runs token'd (F5): roundtrip authenticates first there
OPS_TOKEN = 'opssecret'
OPS_PORT = 15969 + BASE    # the ops-token'd cache (the read-only role, §6d)


def wiremac(payload):   # the suite's thin wrapper: the TOKEN'd frame mac
    return wire_mac(TOKEN, payload)


def signed(cmd):   # the signed wire form (the token'd server refuses the unsigned)
    return signed_wire(cmd, TOKEN)


def ops_roundtrip(cmd, token=OPS_TOKEN, port=None, unsigned=False, timeout=5.0):
    """The suite's thin wrapper: OPS_PORT is the default port."""
    return ops_control_roundtrip(cmd, token, port or OPS_PORT, unsigned, timeout)


def roundtrip(port, wire_bytes, timeout=5.0):
    """The suite's thin wrapper: on AUTH_PORT the token handshake runs first
    (the F5 rule: a TCP control port refuses to start without a token)."""
    return control_roundtrip(port, wire_bytes, timeout, (AUTH_PORT,), TOKEN)


def main():
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15960 + BASE),
                                       '--control-port', '0'], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
        procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15960 + BASE),
                                       '--listen', '127.0.0.1:%d' % (15964 + BASE), '--modbus-interval', '1',
                                       '--control-port', '%d' % AUTH_PORT, '--control-token', TOKEN],
                                      stdout=open(os.path.join(SCRATCH, 'cache_ctl_fuzz.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(AUTH_PORT):
            check('fuzz: the fuzz cache came up (control port %d)' % AUTH_PORT, False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'cache_ctl_fuzz.log'))

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
            (signed('show version')[:-2] + b', "extra": ' + b'[' * 40 + b']' * 40 + b'}\n', 'deeply nested'),   # the extra field is ignored
            (b'\n', 'empty line'),
            (b'   \n', 'whitespace line'),
        ]
        expect_ok = {'deeply nested'}   # a valid command with the extra fields = honored
        for wire, label in garbage:
            st, tx = roundtrip(AUTH_PORT, wire)
            check('fuzz: %s answered with a JSON frame' % label, st in ('ok', 'fail'), '%s %s' % (st, tx))
            want = 'ok' if label in expect_ok else 'fail'
            check('fuzz: %s %s' % (label, 'honored' if label in expect_ok else 'rejected cleanly'),
                  st == want, '%s %s' % (st, tx))

        # 2. the overlong request (1 MB): answered or closed, never a crash
        st, tx = roundtrip(AUTH_PORT, b'{"cmd": "show version", "pad": "' + b'a' * (1024 * 1024) + b'"}\n', timeout=10)
        check('fuzz: 1 MB request handled', st in ('ok', 'fail', 'dead'), '%s %s' % (st, tx[:80]))

        # 3. split packets: one byte at a time, the server assembles the frame
        try:
            s = connect(AUTH_PORT)
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
        try:
            s = connect(AUTH_PORT)
            s.sendall(b'{"cmd": "show version"}')
            s.close()
        except OSError as e:
            check('fuzz: frameless close does not wedge the server', False, str(e))
        else:
            st, tx = roundtrip(AUTH_PORT, signed('show version'))
            check('fuzz: frameless close does not wedge the server', st == 'ok', '%s %s' % (st, tx))

        # 5. ping flood: 100 keepalives, then a real command still works
        ok = True
        for _ in range(100):
            st, tx = roundtrip(AUTH_PORT, signed('ping'), timeout=10)
            ok = ok and st == 'ok'
        check('fuzz: ping flood survives (100x)', ok)
        st, tx = roundtrip(AUTH_PORT, signed('show version'))
        check('fuzz: real command after the flood', st == 'ok', '%s %s' % (st, tx))

        # 6. the token server: the auth abuse is rejected, the real token works
        procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15960 + BASE),
                                       '--listen', '127.0.0.1:%d' % (15966 + BASE), '--modbus-interval', '1',
                                       '--control-port', '%d' % (15967 + BASE), '--control-token', 'sekrit'],
                                      stdout=open(os.path.join(SCRATCH, 'cache_ctl_fuzz2.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(15967 + BASE):
            check('fuzz: the token cache came up (control port %d)' % (15967 + BASE), False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'cache_ctl_fuzz2.log'))
        st, tx = roundtrip(15967 + BASE, b'{"cmd": "show version"}\n')
        check('fuzz: token server rejects the unauthenticated', st == 'fail' and 'authenticate' in tx,
              '%s %s' % (st, tx))
        bad = True
        for _ in range(30):
            st, tx = roundtrip(15967 + BASE, b'{"cmd": "auth", "token": "guess-%d"}\n' % _)
            bad = bad and st == 'fail' and 'bad token' in tx
        check('fuzz: 30 wrong tokens all rejected', bad)
        try:
            s = connect(15967 + BASE)
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
        OPS_AUDIT = os.path.join(SCRATCH, 'cache_ctl_fuzz_ops_audit.log')
        open(OPS_AUDIT, 'w').write('')
        procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15960 + BASE),
                                       '--listen', '127.0.0.1:%d' % (15968 + BASE), '--modbus-interval', '1',
                                       '--control-port', str(OPS_PORT), '--control-token', 'admintok2',
                                       '--control-ops-token', OPS_TOKEN, '--audit-log', OPS_AUDIT],
                                      stdout=open(os.path.join(SCRATCH, 'cache_ctl_fuzz3.log'), 'w'), stderr=subprocess.STDOUT))
        if not wait_port(OPS_PORT):
            check('ops: the ops cache came up (control port %d)' % OPS_PORT, False,
                  'the port never opened — see ' + os.path.join(SCRATCH, 'cache_ctl_fuzz3.log'))
        st, tx, macok = ops_roundtrip('show version')
        check('ops: the ops token authenticates, show version honored, mac\'d with the ops key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show cache')
        check('ops: show cache honored', st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request flush cache')
        check('ops: request flush cache honored (the read-only shift may flush)',
              st == 'ok' and 'cache cleared' in tx and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('set modbus-interval 5')
        check('ops: set is forbidden', st == 'fail' and 'forbidden' in tx and 'admin' in tx and macok,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('clear modbus-interval')
        check('ops: clear is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request restore')
        check('ops: request restore is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request restart')
        check('ops: request restart is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request reload')
        check('ops: request reload is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('request reload-config')
        check('ops: request reload-config is forbidden', st == 'fail' and 'forbidden' in tx, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('shutdown')
        check('ops: shutdown is forbidden', st == 'fail' and 'forbidden' in tx and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show version', unsigned=True)
        check('ops: an unsigned command is still refused first', st == 'fail' and 'unsigned command' in tx,
              '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('set modbus-interval 5', token='admintok2')
        check('ops: the admin token still steers the same server, mac\'d with the admin key',
              st == 'ok' and macok, '%s %s' % (st, tx))
        st, tx, macok = ops_roundtrip('show version', token='nope')
        check('ops: a bogus token is refused', st == 'auth-fail', '%s %s' % (st, tx))
        try:
            aud = open(OPS_AUDIT).read()
            ok = ("role=ops cmd='request flush cache'" in aud and "role=admin cmd='set modbus-interval 5'" in aud
                  and "role=ops cmd='shutdown'" in aud and "role=ops cmd='set modbus-interval 5' wire=h" in aud
                  and 'result=ok' in aud)
        except OSError as e:
            aud, ok = str(e), False
        check('ops: both roles audited (role=ops clear, role=admin set, the denials included)',
              ok, aud[-300:])
        r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15960 + BASE),
                            '--listen', '127.0.0.1:%d' % (15968 + BASE), '--control-port', str(OPS_PORT),
                            '--control-ops-token', 'x', '--dry-run'],
                           capture_output=True, text=True, timeout=15)
        check('ops: an ops token without the admin token is a clean error', r.returncode != 0
              and 'supplements' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15960 + BASE),
                            '--listen', '127.0.0.1:%d' % (15968 + BASE), '--control-port', str(OPS_PORT),
                            '--control-token', 'same', '--control-ops-token', 'same', '--dry-run'],
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
                    wire = signed('show cache')
                else:
                    wire = ('garbage %d\n' % i).encode()
                st, tx = roundtrip(AUTH_PORT, wire, timeout=15)
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
        try:
            s = connect(15964 + BASE, timeout=5)
            s.sendall(struct.pack('>HHHB', 9, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
            r = s.recv(512)
            s.close()
            ok, detail = len(r) >= 10, r.hex()
        except OSError as e:
            ok, detail = False, str(e)
        check('fuzz: modbus side still answers after the fuzzing', ok, detail)

        # 9. clean shutdown
        st, tx = roundtrip(AUTH_PORT, signed('shutdown'))
        check('fuzz: shutdown still works', st == 'bye', '%s %s' % (st, tx))
        time.sleep(1)
        check('fuzz: proxy exited cleanly', procs[1].poll() == 0, str(procs[1].poll()))
    except QuickDone:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    ok = False
    try:
        log = open(os.path.join(SCRATCH, 'cache_ctl_fuzz.log')).read() + open(os.path.join(SCRATCH, 'cache_ctl_fuzz2.log')).read() \
            + open(os.path.join(SCRATCH, 'cache_ctl_fuzz3.log')).read()
        ok = 'Traceback' not in log
    except OSError as e:
        log = 'the daemon logs are unreadable: %s' % e
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
