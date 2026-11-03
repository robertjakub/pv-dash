#!/usr/bin/env python3
"""Control-protocol fuzz for the fake inverter: malformed, hostile and
degenerate JSON-line requests against the control server. The server must
answer with a well-formed JSON frame (or close cleanly) and stay alive and
serving afterwards.

  python3 tests/control-fuzz.py

Checks: ALL PASS (or a FAILURES list; exit 1).
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
F = os.path.join(REPO, 'inverter', 'bin', 'fake_inverter.py')
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


def main():
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15960',
                                       '--control-port', '15961'],
                                      stdout=open('/tmp/ctl_fuzz.log', 'w'), stderr=subprocess.STDOUT))
        time.sleep(0.9)

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
            (b'{"cmd": "show status", "extra": ' + b'[' * 40 + b']' * 40 + b'}\n', 'deeply nested'),   # the extra field is ignored
            (b'\n', 'empty line'),
            (b'   \n', 'whitespace line'),
        ]
        expect_ok = {'deeply nested'}   # a valid command with the extra fields = honored
        for wire, label in garbage:
            st, tx = roundtrip(15961, wire)
            check('fuzz: %s answered with a JSON frame' % label, st in ('ok', 'err'), '%s %s' % (st, tx))
            want = 'ok' if label in expect_ok else 'err'
            check('fuzz: %s %s' % (label, 'honored' if label in expect_ok else 'rejected cleanly'),
                  st == want, '%s %s' % (st, tx))

        # 2. the overlong request (1 MB): answered or closed, never a crash
        st, tx = roundtrip(15961, b'{"cmd": "show status", "pad": "' + b'a' * (1024 * 1024) + b'"}\n', timeout=10)
        check('fuzz: 1 MB request handled', st in ('ok', 'err', 'dead'), '%s %s' % (st, tx[:80]))

        # 3. split packets: one byte at a time, the server assembles the frame
        try:
            s = connect(15961)
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
        s = connect(15961)
        s.sendall(b'{"cmd": "show status"}')
        s.close()
        st, tx = roundtrip(15961, b'{"cmd": "show version"}\n')
        check('fuzz: frameless close does not wedge the server', st == 'ok', '%s %s' % (st, tx))

        # 5. ping flood: 100 keepalives, then a real command still works
        ok = True
        for _ in range(100):
            st, tx = roundtrip(15961, b'{"cmd": "ping"}\n', timeout=10)
            ok = ok and st == 'ok'
        check('fuzz: ping flood survives (100x)', ok)
        st, tx = roundtrip(15961, b'{"cmd": "show status"}\n')
        check('fuzz: real command after the flood', st == 'ok', '%s %s' % (st, tx))

        # 6. the token server: the auth abuse is rejected, the real token works
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15962',
                                       '--control-port', '15963', '--control-token', 'sekrit'],
                                      stdout=open('/tmp/ctl_fuzz2.log', 'w'), stderr=subprocess.STDOUT))
        time.sleep(0.9)
        st, tx = roundtrip(15963, b'{"cmd": "show version"}\n')
        check('fuzz: token server rejects the unauthenticated', st == 'err' and 'authenticate' in tx,
              '%s %s' % (st, tx))
        bad = True
        for _ in range(30):
            st, tx = roundtrip(15963, b'{"cmd": "auth", "token": "guess-%d"}\n' % _)
            bad = bad and st == 'err' and 'bad token' in tx
        check('fuzz: 30 wrong tokens all rejected', bad)
        try:
            s = connect(15963)
            s.sendall(_json.dumps({'cmd': 'auth', 'token': 'sekrit'}).encode() + b'\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            auth = _json.loads(buf.decode())
            check('fuzz: the right token authenticates', auth.get('status') == 'ok', str(auth))
            s.sendall(b'{"cmd": "show version"}\n')
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
            reply = _json.loads(buf.decode())
            check('fuzz: authenticated command works on the same connection', reply.get('status') == 'ok'
                  and 'fake-inverter' in reply.get('text', ''), str(reply))
            s.close()
        except (OSError, ValueError) as e:
            check('fuzz: the right token authenticates', False, str(e))

        # 7. twenty parallel clients: garbage and real commands interleaved
        results = []

        def hammer(i):
            try:
                if i % 2:
                    wire = b'{"cmd": "show settings"}\n'
                else:
                    wire = ('garbage %d\n' % i).encode()
                st, tx = roundtrip(15961, wire, timeout=15)
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

        # 8. the fake is still alive and serving Modbus
        s = connect(15960, timeout=5)
        s.sendall(struct.pack('>HHHB', 9, 0, 6, 1) + struct.pack('>BHH', 3, 32064, 1))
        r = s.recv(512)
        s.close()
        check('fuzz: modbus side still answers after the fuzzing', len(r) >= 10, r.hex())

        # 9. clean shutdown
        st, tx = roundtrip(15961, b'{"cmd": "shutdown"}\n')
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
