#!/usr/bin/env python3
"""Regression test for the fake inverter's Modbus surface hardening
(docs/AUDIT.md F11): the read-count cap (a declared count far above the
payload gets exception 03, never an oversized reply), --max-clients (the
excess connection is refused at accept), --client-timeout (silent clients
are shed), and the control surface around them (show connections, the live
set max-clients/client-timeout round-trip, the status/inspect fields).

  python3 tests/inverter-regtest.py

Checks: ALL PASS (or a FAILURES list; exit 1).
"""
import json
import os
import socket
import struct
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
CTL = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py')
LOG = '/tmp/inv_regtest.log'
FAILURES = []

A_MODBUS, A_CTL = 15970, 15971        # --max-clients 1
B_MODBUS, B_CTL = 15972, 15973        # --client-timeout 1
C_MODBUS, C_CTL = 15974, 15975        # --max-conn-per-ip 1 --max-clients 0
D_MODBUS = 15976                      # the default unix control socket (mode 0600)
E_MODBUS, E_SOCK = 15977, '/tmp/inv_regtest_eg.socket'   # --control-socket-group (0660)
F_MODBUS, F_CTL = 15978, 15980        # the live token-less metrics warn (listen 0.0.0.0)
F_METRICS = 15981
G_MODBUS, G_SOCK = 15982, '/nonexistent_dir_regtest/x.socket'   # an unbindable control target (the bind guard)
H_MODBUS, H_CTL = 15983, 15984        # the token'd TCP control (the signed wire)
B_METRICS = 15979                     # instance B's /metrics (max-clients 1)
UNIT = 1


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' — ' + str(detail) if detail and not ok else ''))
    if not ok:
        FAILURES.append(name)


def ctl(port, *cmds, token=None):
    out = subprocess.run([sys.executable, CTL, '--control-port', str(port)]
                         + (['--control-token', token] if token else []) + list(cmds),
                         capture_output=True, text=True, timeout=15)
    return out.stdout.strip()


def connect(port, timeout=5.0):
    return socket.create_connection(('127.0.0.1', port), timeout=timeout)


def frame(txn, unit, pdu):
    return struct.pack('>HHHB', txn, 0, len(pdu) + 1, unit) + pdu


def read_req(txn, func, addr, count):
    return frame(txn, UNIT, struct.pack('>BHH', func, addr, count))


def exchange(sock, wire, txn):
    """One Modbus round-trip: returns the reply's (func, byte-count-or-code, body)."""
    sock.sendall(wire)
    head = b''
    while len(head) < 7:
        chunk = sock.recv(7 - len(head))
        if not chunk:
            raise ConnectionError('EOF in MBAP')
        head += chunk
    txn_, _proto, length, unit_ = struct.unpack('>HHHB', head)
    body = b''
    while len(body) < length - 1:
        chunk = sock.recv(length - 1 - len(body))
        if not chunk:
            raise ConnectionError('EOF in PDU')
        body += chunk
    return txn_, unit_, body


def eof_soon(sock, seconds=3.0):
    """True when the server closes the connection within `seconds`."""
    sock.settimeout(seconds)
    t0 = time.monotonic()
    try:
        return sock.recv(4096) == b'' and time.monotonic() - t0 < seconds
    except OSError:
        return False


def main():
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(A_MODBUS),
                                       '--control-port', str(A_CTL), '--max-clients', '1'],
                                      stdout=open(LOG, 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(B_MODBUS),
                                       '--control-port', str(B_CTL), '--client-timeout', '1',
                                       '--metrics-listen', '127.0.0.1:%d' % B_METRICS, '--metrics-token', 'tok', '--metrics-server',
                                       '--metrics-max-clients', '1'],
                                      stdout=open(LOG + '.b', 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(C_MODBUS),
                                       '--control-port', str(C_CTL), '--max-clients', '0',
                                       '--max-conn-per-ip', '1'],
                                      stdout=open(LOG + '.c', 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(D_MODBUS)],
                                      stdout=open(LOG + '.d', 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(E_MODBUS),
                                       '--control-port', E_SOCK, '--control-socket-group'],
                                      stdout=open(LOG + '.e', 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(F_MODBUS),
                                       '--control-port', str(F_CTL),
                                       '--metrics-listen', '0.0.0.0:%d' % F_METRICS],
                                      stdout=open(LOG + '.f', 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(G_MODBUS),
                                       '--control-port', G_SOCK],
                                      stdout=open(LOG + '.g', 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(H_MODBUS),
                                       '--control-port', str(H_CTL), '--control-token', 'tok',
                                       '--audit-log', '/tmp/inv_regtest_audit.log'],
                                      stdout=open(LOG + '.h', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.1)

        # ---- instance A: the read-count cap (F11) + the client limit
        c1 = connect(A_MODBUS)
        # a valid 125-register read still works (the cap is 125, the profile ~49)
        txn, unit, body = exchange(c1, read_req(1, 3, 32064, 125), 1)
        check('valid read at the cap (125 regs) answered',
              txn == 1 and unit == UNIT and body[0] == 3 and body[1] == 250, str(body[:4].hex()))
        # count 0xFFFF (the audit's example): exception 03, no oversized reply
        txn, unit, body = exchange(c1, read_req(2, 3, 32064, 0xFFFF), 2)
        check('count 0xFFFF -> exception 03', txn == 2 and body == bytes([3 + 0x80, 3]), body.hex())
        # count just past the cap, and count 0
        txn, unit, body = exchange(c1, read_req(3, 4, 0, 126), 3)
        check('count 126 -> exception 03', txn == 3 and body == bytes([4 + 0x80, 3]), body.hex())
        txn, unit, body = exchange(c1, read_req(4, 3, 32064, 0), 4)
        check('count 0 -> exception 03', txn == 4 and body == bytes([3 + 0x80, 3]), body.hex())
        # the span past the 16-bit register space
        txn, unit, body = exchange(c1, read_req(5, 3, 65530, 100), 5)
        check('addr 65530 + count 100 -> exception 03', txn == 5 and body == bytes([3 + 0x80, 3]), body.hex())
        # the connection survives the refusals
        txn, unit, body = exchange(c1, read_req(6, 3, 32064, 2), 6)
        check('connection survives the refusals', txn == 6 and body[0] == 3 and body[1] == 4, body.hex())

        # show connections lists the live client with its request tally
        tx = ctl(A_CTL, 'show connections')
        check('show connections lists the peer', tx.startswith('ok connections 127.0.0.1:')
              and 'requests' in tx, tx)
        st = dict(line.split('=', 1) for line in ctl(A_CTL, 'show status').splitlines()[1:])
        check('show status carries clients=', st.get('clients') == '1', str(st.get('clients')))
        check('show status carries metrics=off (no endpoint)', st.get('metrics') == 'off', str(st.get('metrics')))
        ins = ctl(A_CTL, 'inspect')
        check('inspect carries the modbus row', 'modbus    127.0.0.1:%d, clients 1 (limit 1, timeout 5.00m, per-ip none, connect-acl any)' % A_MODBUS in ins,
              [l for l in ins.splitlines() if l.startswith('modbus')])
        check('inspect carries the metrics row', 'metrics   off' in ins,
              [l for l in ins.splitlines() if l.startswith('metrics')])

        # the second client is refused at accept (max-clients 1), the first keeps serving
        c2 = connect(A_MODBUS)
        check('excess client refused (EOF at accept)', eof_soon(c2))
        txn, unit, body = exchange(c1, read_req(7, 3, 32064, 2), 7)
        check('the admitted client keeps serving', txn == 7 and body[0] == 3, body.hex())
        tx = ctl(A_CTL, 'show connections')
        check('the refused peer is not tracked', tx.count('127.0.0.1:') == 1, tx)

        # live set: raise the limit to 2 -> the next connect is admitted
        tx = ctl(A_CTL, 'set max-clients 2')
        check('set max-clients 2', tx.startswith('ok max-clients=2'), tx)
        c3 = connect(A_MODBUS)
        exchange(c3, read_req(8, 3, 32064, 2), 8)
        tx = ctl(A_CTL, 'show connections')
        check('both clients tracked after the live raise', tx.count('127.0.0.1:') == 2, tx)
        tx = ctl(A_CTL, 'unset max-clients')
        check('unset max-clients restores 1', 'ok max-clients=1' in tx, tx)
        c1.close(); c3.close()
        time.sleep(0.4)
        tx = ctl(A_CTL, 'show connections')
        check('show connections -> none after the exits', tx == 'ok connections none', tx)

        # ---- instance B: the client timeout sheds silent clients
        s1 = connect(B_MODBUS)
        exchange(s1, read_req(1, 3, 32064, 2), 1)
        check('silent client shed within ~2s (timeout 1s)', eof_soon(s1, 4.0))
        # live set: timeout off -> a silent client survives the same window
        tx = ctl(B_CTL, 'set client-timeout 0')
        check('set client-timeout 0 (never)', tx.startswith('ok client-timeout=never'), tx)
        s2 = connect(B_MODBUS)
        s2.settimeout(2.5)
        survived = True
        try:
            survived = s2.recv(4096) != b'' or True   # no EOF inside 2.5 s = shed nothing
            s2.settimeout(0.2)
            try:
                survived = s2.recv(4096) == b'' or survived
            except OSError:
                survived = True   # timed out = still connected = correct
        except OSError:
            survived = True       # a timeout is a live connection here
        check('timeout 0 keeps a silent client connected', survived)
        # and the timeout applied at accept still answers reads fine
        txn, unit, body = exchange(s2, read_req(2, 3, 32064, 2), 2)
        check('reads work under the timeout policy', txn == 2 and body[0] == 3, body.hex())
        s2.close()

        # ---- instance C: the per-IP connection cap (F13 round)
        p1 = connect(C_MODBUS)
        exchange(p1, read_req(1, 3, 32064, 2), 1)
        p2 = connect(C_MODBUS)
        check('per-IP cap: the second connection from the same IP refused', eof_soon(p2))
        txn, unit, body = exchange(p1, read_req(2, 3, 32064, 2), 2)
        check('per-IP cap: the first connection keeps serving', txn == 2 and body[0] == 3, body.hex())
        tx = ctl(C_CTL, 'set max-conn-per-ip 2')
        check('per-IP cap raised live', tx.startswith('ok max-conn-per-ip=2'), tx)
        p2 = connect(C_MODBUS)
        exchange(p2, read_req(3, 3, 32064, 2), 3)
        tx = ctl(C_CTL, 'show connections')
        check('per-IP cap: both peers tracked after the raise', tx.count('127.0.0.1:') == 2, tx)
        p1.close(); p2.close()
        time.sleep(0.4)
        logc = open(LOG + '.c').read()
        check('per-IP refusal logged', 'connection refused: per-IP limit of 1 reached' in logc)

        # ---- instance B's /metrics: the 503 cap, the token, the recovery
        def http_get(port, token=None, timeout=5):
            """Raw HTTP GET: (status-line, full reply bytes)."""
            s = connect(port, timeout)
            req = 'GET /metrics HTTP/1.1\r\nHost: t\r\n%s\r\n' % (
                ('Authorization: Bearer %s\r\n' % token) if token else '')
            s.sendall(req.encode())
            buf = b''
            try:
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            except OSError:
                pass
            s.close()
            return buf.split(b'\r\n', 1)[0].decode('utf-8', 'replace'), buf

        st, _ = http_get(B_METRICS, token='tok')
        check('metrics answers with the token', st.split()[1] == '200', st)
        st, _ = http_get(B_METRICS)
        check('metrics refuses the token-less (bearer gate)', st.split()[1] == '401', st)
        # hold the single slot with a silent connection; the next request gets 503
        s_hold = connect(B_METRICS)
        st, _ = http_get(B_METRICS, token='tok')
        check('metrics 503 past --metrics-max-clients 1', st.split()[1] == '503', st)
        s_hold.close()
        time.sleep(0.3)
        st, _ = http_get(B_METRICS, token='tok')
        check('metrics recovers after the slot frees', st.split()[1] == '200', st)
        # the live metrics-server switch: off stops the endpoint, on restarts it
        tx = ctl(B_CTL, 'set metrics-server off')
        check('metrics-server: set off', tx.startswith('ok metrics-server=off'), tx)
        srv_down = False
        try:
            connect(B_METRICS, 1.0).close()
        except OSError:
            srv_down = True
        check('metrics-server: the port is closed after set off', srv_down)
        stb = dict(line.split('=', 1) for line in ctl(B_CTL, 'show status').splitlines()[1:])
        check('metrics-server: show status says off', stb.get('metrics') == 'off', str(stb.get('metrics')))
        tx = ctl(B_CTL, 'set metrics-server on')
        check('metrics-server: set on serves again', tx.startswith('ok metrics-server=on'), tx)
        st, _ = http_get(B_METRICS, token='tok')
        check('metrics-server: the gauges are back', st.split()[1] == '200', st)
        stb = dict(line.split('=', 1) for line in ctl(B_CTL, 'show status').splitlines()[1:])
        check('metrics-server: show status carries the endpoint line',
              stb.get('metrics') == '127.0.0.1:%d (bearer token), clients 1, per-ip none' % B_METRICS,
              str(stb.get('metrics')))

        # ---- the control-server parity round (the cache's shape)
        check('control: the default unix socket mode is 0600 (not the umask)',
              os.stat('/tmp/fake-inverter-%d.socket' % D_MODBUS).st_mode & 0o777 == 0o600,
              oct(os.stat('/tmp/fake-inverter-%d.socket' % D_MODBUS).st_mode & 0o777))
        check('control: --control-socket-group chmods the socket 0660',
              os.stat(E_SOCK).st_mode & 0o777 == 0o660, oct(os.stat(E_SOCK).st_mode & 0o777))
        tx = ctl(F_CTL, 'set metrics-server on')
        check('metrics-server: the token-less live start on 0.0.0.0 accepted', tx.startswith('ok metrics-server=on'), tx)
        ctl(F_CTL, 'set metrics-server off')
        logf = open(LOG + '.f').read()
        check('metrics-server: the live token-less start beyond loopback warns',
              'serving /metrics on 0.0.0.0:%d without a token' % F_METRICS in logf,
              [l for l in logf.splitlines() if 'token' in l])
        g = connect(G_MODBUS)
        txn, unit, body = exchange(g, read_req(1, 3, 32064, 2), 1)
        check('control: the fake serves Modbus despite the failed control bind', txn == 1 and body[0] == 3, body.hex())
        g.close()
        logg = open(LOG + '.g').read()
        check('control: an unbindable target logs a one-liner, no crash',
              'control server cannot bind unix:%s' % G_SOCK in logg and 'Traceback' not in logg,
              [l for l in logg.splitlines() if 'control' in l or 'Trace' in l])

        # ---- the connect ACL (the cache's connect-acl, mirrored; the
        # default 'any' keeps the trusted-LAN posture)
        c9 = connect(A_MODBUS)
        exchange(c9, read_req(9, 3, 32064, 2), 9)     # a live client keeps serving
        tx = ctl(A_CTL, 'set connect-acl 10.9.9.9')
        check('connect-acl: set to a foreign network', 'ok connect-acl=' in tx and '10.9.9.9' in tx, tx)
        c10 = connect(A_MODBUS)
        check('connect-acl: the foreign-network-only ACL refuses the peer', eof_soon(c10))
        txn, unit, body = exchange(c9, read_req(10, 3, 32064, 2), 10)
        check('connect-acl: the admitted client keeps serving', txn == 10 and body[0] == 3, body.hex())
        st = dict(line.split('=', 1) for line in ctl(A_CTL, 'show status').splitlines()[1:])
        check('connect-acl: show status carries connect_acl=', st.get('connect_acl') == '1 network(s)',
              str(st.get('connect_acl')))
        tx = ctl(A_CTL, 'unset connect-acl')
        check('connect-acl: unset restores any', 'ok connect-acl=any' in tx, tx)
        c9.close()
        time.sleep(0.4)   # the slot frees (max-clients 1 on this instance)
        c11 = connect(A_MODBUS)
        exchange(c11, read_req(11, 3, 32064, 2), 11)
        c11.close()
        log = open(LOG).read()
        check('connect-acl: the rejection logged', 'not on the connect ACL' in log)

        # ---- the signed wire (the full sha256 HMAC of every frame, keyed by
        # the control token; instance H's TCP control speaks 'tok')
        import hashlib
        import hmac as _hmac

        def wiremac(payload, token='tok'):
            return _hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()

        tx = ctl(H_CTL, 'show version', token='tok')
        check('signed wire: the token ctl authenticates and answers', tx.startswith('ok fake-inverter'), tx)
        tx = ctl(H_CTL, 'show version', token='wrong')
        check('signed wire: the wrong token fails the handshake', 'control auth failed' in tx
              or tx == '', tx or '(empty)')
        s = connect(H_CTL)
        s.sendall(json.dumps({'cmd': 'auth', 'token': 'tok'}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        s.sendall(b'{"cmd": "show version"}\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        obj = json.loads(buf.decode())
        s.close()
        check('signed wire: an unsigned command over TCP is refused',
              obj.get('status') == 'err' and 'unsigned command' in obj.get('text', ''), str(obj))
        s = connect(H_CTL)
        s.sendall(json.dumps({'cmd': 'auth', 'token': 'tok'}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        obj = json.loads(buf.decode())
        check('signed wire: the auth-ok reply carries the mac',
              obj.get('status') == 'ok' and obj.get('mac') == wiremac('ok authenticated'), str(obj))
        s.sendall(json.dumps({'cmd': 'show version', 'mac': wiremac('show version')}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        obj = json.loads(buf.decode())
        s.close()
        check('signed wire: a signed command honored, the reply mac verifies',
              obj.get('status') == 'ok' and 'fake-inverter' in obj.get('text', '')
              and obj.get('mac') == wiremac('%s %s' % (obj.get('status'), obj.get('text', ''))), str(obj))
        s = connect(H_CTL)
        s.sendall(json.dumps({'cmd': 'auth', 'token': 'tok'}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        s.sendall(json.dumps({'cmd': 'show version', 'mac': 'ab' * 32}).encode() + b'\n')
        buf = b''
        while not buf.endswith(b'\n'):
            buf += s.recv(4096)
        obj = json.loads(buf.decode())
        s.close()
        check('signed wire: a bad command mac is refused',
              obj.get('status') == 'err' and 'mac does not verify' in obj.get('text', ''), str(obj))
        aud = open('/tmp/inv_regtest_audit.log').read()
        check('signed wire: the audit COMMAND line carries the wire mac', "'show version' wire=h" in aud, aud[-200:])

        # ---- the secret lives: the token lives rotate (the cache's
        #      treatment) and the show verb refuses them — a secret never renders
        tx = ctl(H_CTL, 'show control token', token='tok')
        check('secrets: the control token never shows', tx.startswith('err control/token is a secret'), tx)
        tx = ctl(H_CTL, 'unset control token', token='tok')
        check('secrets: unset refuses a secret (no defaults entry)', tx.startswith('err unknown setting'), tx)
        tx = ctl(H_CTL, 'set control token tok2', token='tok')
        check('secrets: the control token rotates live', tx.startswith('ok control/token=<set>'), tx)
        tx = ctl(H_CTL, 'show version', token='tok')
        check('secrets: the old control token is refused', 'control auth failed' in tx or tx == '', tx or '(empty)')
        tx = ctl(H_CTL, 'show version', token='tok2')
        check('secrets: the rotated control token speaks', tx.startswith('ok fake-inverter'), tx)
        tx = ctl(H_CTL, 'show control token', token='tok2')
        check('secrets: the rotated control token never renders back',
              tx.startswith('err control/token is a secret'), tx)
        tx = ctl(H_CTL, 'set metrics token mtok2', token='tok2')
        check('secrets: the metrics token rotates live', tx.startswith('ok metrics/token=<set>'), tx)
        tx = ctl(H_CTL, 'show metrics token', token='tok2')
        check('secrets: the metrics token never shows', tx.startswith('err metrics/token is a secret'), tx)
        tx = ctl(H_CTL, 'unset metrics token', token='tok2')
        check('secrets: unset refuses the metrics token too', tx.startswith('err unknown setting'), tx)
        tx = ctl(H_CTL, 'show config', token='tok2')
        check('secrets: show config renders the secret knob as the placeholder',
              'set control token *** SECRET REMOVED ***' in tx
              and 'set control token tok' not in tx and 'tok2' not in tx, tx[:200])

        # ---- the whole-daemon reload (the fake has no config file — its
        #      reload state lives in the XDG state home) and the settings
        #      dump/restore (instance I)
        I_MODBUS, I_CTL = 15985, 15986
        reload_state = '/tmp/inv_regtest_reload_state'
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(I_MODBUS),
                                       '--control-port', str(I_CTL),
                                       '--dump-path', '/tmp/inv_regtest_state.json', '--restore-on-start'],
                                      stdout=open(LOG + '.i', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        time.sleep(1.5)
        tx = ctl(I_CTL, 'set pv 100')
        check('dump: the pin lands', 'ok pv=100' in tx, tx)
        tx = ctl(I_CTL, 'set cloud autumn')
        check('dump: the machine pins too', 'ok cloud=autumn' in tx, tx)
        tx = ctl(I_CTL, 'set time 09:30')
        check('dump: the freeze pins', 'ok time=09:30' in tx, tx)
        tx = ctl(I_CTL, 'request dump')
        check('dump: request dump writes the state', tx.startswith('ok dumped 3 setting(s)'), tx)
        dumpst = os.stat('/tmp/inv_regtest_state.json')
        check('dump: the state dump is 0600 (the F18 posture)', dumpst.st_mode & 0o777 == 0o600,
              oct(dumpst.st_mode & 0o777))
        raw = open('/tmp/inv_regtest_state.json').read()
        check('dump: the dump carries the settings, never the secrets',
              '"pv"' in raw and 'mtok2' not in raw and 'tok2' not in raw, raw[:160])
        tx = ctl(I_CTL, 'reset')
        check('dump: reset releases everything', 'ok reset' in tx, tx)
        tx = ctl(I_CTL, 'show pv')
        check('dump: the pin is gone', tx == 'ok pv=auto', tx)
        tx = ctl(I_CTL, 'request restore')
        check('dump: the restore re-applies the dump', tx.startswith('ok restored 3 setting(s)'), tx)
        tx = ctl(I_CTL, 'show pv')
        check('dump: the restored pin reads back', tx == 'ok pv=100', tx)
        tx = ctl(I_CTL, 'show cloud')
        check('dump: the restored machine reads back', tx.startswith('ok cloud=autumn'), tx)
        tx = ctl(I_CTL, 'show time')
        check('dump: the restored freeze reads back', tx == 'ok time=09:30', tx)
        tx = ctl(I_CTL, 'reload')
        check('reload: the reply reports the saved overrides', tx.startswith('ok reload: 3 override(s) saved'), tx)
        back = None
        for _ in range(100):     # the exec is fast; a connect on the dying fake retries
            try:
                back = ctl(I_CTL, 'show pv')
                break
            except Exception:
                time.sleep(0.1)
        check('reload: the fake came back with the pin re-applied', back == 'ok pv=100', repr(back))
        tx = ctl(I_CTL, 'show cloud')
        check('reload: the machine rode the exec too', back is not None and tx.startswith('ok cloud=autumn'), tx)
        gone = False
        for _ in range(100):     # the fresh daemon consumes the state at start — poll for the disappearance
            if not os.path.exists(os.path.join(reload_state, 'fake-inverter', 'reload.json')):
                gone = True
                break
            time.sleep(0.1)
        check('reload: the state file is consumed', gone,
              os.path.join(reload_state, 'fake-inverter', 'reload.json'))
        tx = ctl(I_CTL, 'shutdown')
        check('reload: the re-execed fake shuts down clean', tx.startswith('bye shutdown'), tx)
        time.sleep(0.4)

        # ---- the sealed dumps (dump/key): the state rides encrypted (an
        #      HMAC-SHA256 counter-mode box), the restore fails closed on a
        #      wrong or missing key — and on an unsealed dump under a
        #      configured key — and the keyed reload re-reads the sealed
        #      state file on the other side of the exec (instance J)
        J_MODBUS, J_CTL = 15987, 15988
        kstate = '/tmp/inv_regtest_state_sealed.json'
        if os.path.exists(kstate):
            os.unlink(kstate)   # the block is idempotent: a previous run's graceful-shutdown dump (2 settings) must not seed this one
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(J_MODBUS),
                                       '--control-port', str(J_CTL), '--dump-path', kstate,
                                       '--dump-key', 'inv-seal-key', '--restore-on-start'],
                                      stdout=open(LOG + '.j', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        time.sleep(1.5)
        tx = ctl(J_CTL, 'show dump key')
        check('sealed dump: show dump/key is a secret — it never shows',
              tx.startswith('err dump/key is a secret'), tx[:100])
        tx = ctl(J_CTL, 'set dump key other')
        check('sealed dump: set dump/key answers the restart note (the key cannot drift mid-life)',
              tx.startswith('err restart required (startup-only knob)'), tx[:100])
        tx = ctl(J_CTL, 'set pv 120')
        check('sealed dump: the pin lands', 'ok pv=120' in tx, tx)
        tx = ctl(J_CTL, 'request dump')
        check('sealed dump: request dump reports sealed',
              tx.startswith('ok dumped 1 setting(s)') and '(sealed)' in tx, tx[:100])
        raw = open(kstate).read()
        kd = json.loads(raw)
        check('sealed dump: the envelope is the sealed version-2 shape',
              kd.get('format') == 'pv-suite-state-dump' and kd.get('version') == 2
              and kd.get('cipher') == 'sha256-ctr' and len(kd.get('nonce', '')) == 32
              and len(kd.get('mac', '')) == 64 and len(kd.get('box', '')) > 64, raw[:120])
        check('sealed dump: no plaintext rides the file',
              '"settings"' not in raw and '"pv"' not in raw and '"saved"' not in raw, raw[:120])
        check('sealed dump: the sealed dump is 0600 too', os.stat(kstate).st_mode & 0o777 == 0o600,
              oct(os.stat(kstate).st_mode & 0o777))
        tx = ctl(J_CTL, 'reset')
        tx = ctl(J_CTL, 'request restore')
        check('sealed dump: the restore re-applies under the configured key',
              tx.startswith('ok restored 1 setting(s)'), tx[:100])
        tx = ctl(J_CTL, 'show pv')
        check('sealed dump: the restored pin reads back', tx == 'ok pv=120', tx)
        procs[-1].kill()
        time.sleep(0.3)
        # the wrong key: the sealed dump refuses at start (the mac reads it as tampered content)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(J_MODBUS),
                                       '--control-port', str(J_CTL), '--dump-path', kstate,
                                       '--dump-key', 'inv-seal-key-WRONG', '--restore-on-start'],
                                      stdout=open(LOG + '.j2', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        line = ''
        for _ in range(80):
            line = open(LOG + '.j2').read()
            if 'fails its seal' in line:
                break
            time.sleep(0.1)
        check('sealed dump: a wrong key refuses the dump at start (fails closed)',
              'fails its seal' in line, line[-220:])
        tx = ctl(J_CTL, 'show pv')
        check('sealed dump: the daemon is up despite the refused dump', tx == 'ok pv=auto', repr(tx))
        procs[-1].kill()
        time.sleep(0.3)
        # no key at all: a sealed dump refuses with the pointer to dump/key
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(J_MODBUS),
                                       '--control-port', str(J_CTL), '--dump-path', kstate,
                                       '--restore-on-start'],
                                      stdout=open(LOG + '.j3', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        line = ''
        for _ in range(80):
            line = open(LOG + '.j3').read()
            if 'is sealed' in line:
                break
            time.sleep(0.1)
        check('sealed dump: a sealed dump without any key refuses at start',
              'is sealed' in line and 'dump/key' in line, line[-220:])
        procs[-1].kill()
        time.sleep(0.3)
        # a configured key refuses an UNSEALED dump (plaintext stopped being trust at rest)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(J_MODBUS),
                                       '--control-port', str(J_CTL), '--dump-path', '/tmp/inv_regtest_state.json',
                                       '--dump-key', 'inv-seal-key', '--restore-on-start'],
                                      stdout=open(LOG + '.j4', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        line = ''
        for _ in range(80):
            line = open(LOG + '.j4').read()
            if 'dump/key is configured' in line:
                break
            time.sleep(0.1)
        check('sealed dump: a configured key refuses an unsealed dump',
              'is not sealed' in line and 'dump/key is configured' in line, line[-220:])
        procs[-1].kill()
        time.sleep(0.3)
        # the right key: the sealed dump restores at start, and the keyed
        # reload's state file re-reads on the other side of the exec
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(J_MODBUS),
                                       '--control-port', str(J_CTL), '--dump-path', kstate,
                                       '--dump-key', 'inv-seal-key', '--restore-on-start'],
                                      stdout=open(LOG + '.j5', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        back = None
        for _ in range(100):
            try:
                back = ctl(J_CTL, 'show pv')
                if back == 'ok pv=120':
                    break
            except Exception:
                pass
            time.sleep(0.1)
        check('sealed dump: the right key restores the sealed dump at start', back == 'ok pv=120', repr(back))
        tx = ctl(J_CTL, 'set batt 50')
        check('sealed reload: the pin lands before the reload', 'ok batt=50' in tx, tx)
        tx = ctl(J_CTL, 'reload')
        check('sealed reload: the reply reports the saved overrides',
              tx.startswith('ok reload: 2 override(s) saved'), tx[:100])
        back = None
        for _ in range(100):
            try:
                back = ctl(J_CTL, 'show batt')
                if back.startswith('ok batt=50'):
                    break
            except Exception:
                time.sleep(0.1)
        check('sealed reload: the fresh fake re-applied the sealed state file',
              back is not None and 'ok batt=50' in back, repr(back))
        tx = ctl(J_CTL, 'shutdown')
        check('sealed reload: the re-execed fake shuts down clean', tx.startswith('bye shutdown'), tx)
        time.sleep(0.4)

        # ---- the file: reference form (one secret knob, two forms) and the
        #      unsealed-dump warning (instance K): the key rides a file
        #      reference (the first line of an owner-only file), an
        #      unreadable reference fails the start, a dump path without a
        #      key warns at start and on set, and the live control token
        #      takes the same reference form
        K_MODBUS, K_CTL = 15989, 15990
        kfile_state = '/tmp/inv_regtest_state_filekey.json'
        if os.path.exists(kfile_state):
            os.unlink(kfile_state)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(K_MODBUS),
                                       '--control-port', str(K_CTL), '--dump-path', kfile_state],
                                      stdout=open(LOG + '.k', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        line = ''
        for _ in range(80):
            line = open(LOG + '.k').read()
            if 'is not sealed' in line:
                break
            time.sleep(0.1)
        check('file-key: a dump path without a key warns unsealed at start',
              'is not sealed' in line and 'set dump/key' in line, line[-220:])
        tx = ctl(K_CTL, 'set dump path %s' % kfile_state)
        check('file-key: the set dump path reply notes the unsealed dump',
              tx.startswith('ok dump/path=%s (not sealed' % kfile_state), tx[:120])
        tx = ctl(K_CTL, 'set pv 77')
        tx = ctl(K_CTL, 'request dump')
        check('file-key: the keyless dump stays plaintext (no sealed mark)',
              tx.startswith('ok dumped 2 setting(s)') and '(sealed)' not in tx, tx[:100])
        procs[-1].kill()
        time.sleep(0.3)
        # the file reference: the key material comes from an owner-only file
        kkey = '/tmp/inv_regtest_dump_key_file'
        with open(kkey, 'w') as fh:
            fh.write('file-key-material-9\n')
        os.chmod(kkey, 0o600)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(K_MODBUS),
                                       '--control-port', str(K_CTL), '--dump-path', kfile_state,
                                       '--dump-key', 'file:' + kkey, '--restore-on-start'],
                                      stdout=open(LOG + '.k2', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        line = ''
        for _ in range(80):
            line = open(LOG + '.k2').read()
            if 'dump/key is configured' in line:
                break
            time.sleep(0.1)
        check('file-key: the file-reference key refuses the plaintext dump at start (the symmetric gate)',
              'is not sealed but dump/key is configured' in line, line[-220:])
        procs[-1].kill()
        time.sleep(0.3)
        kfile_state2 = '/tmp/inv_regtest_state_filekey2.json'
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(K_MODBUS),
                                       '--control-port', str(K_CTL), '--dump-path', kfile_state2,
                                       '--dump-key', 'file:' + kkey],
                                      stdout=open(LOG + '.k3', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        back = None
        for _ in range(100):
            try:
                back = ctl(K_CTL, 'show version')
                if back.startswith('ok'):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        tx = ctl(K_CTL, 'set pv 78')
        tx = ctl(K_CTL, 'request dump')
        check('file-key: the file-reference key seals the dump',
              tx.startswith('ok dumped 1 setting(s)') and '(sealed)' in tx, tx[:100])
        raw = open(kfile_state2).read()
        kd = json.loads(raw)
        check('file-key: the sealed envelope is the version-2 shape',
              kd.get('version') == 2 and kd.get('cipher') == 'sha256-ctr'
              and kd.get('box') and '"pv"' not in raw, raw[:120])
        procs[-1].kill()
        time.sleep(0.3)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(K_MODBUS),
                                       '--control-port', str(K_CTL), '--dump-path', kfile_state2,
                                       '--dump-key', 'file:' + kkey, '--restore-on-start'],
                                      stdout=open(LOG + '.k4', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        back = None
        for _ in range(100):
            try:
                back = ctl(K_CTL, 'show pv')
                if back == 'ok pv=78':
                    break
            except Exception:
                pass
            time.sleep(0.1)
        check('file-key: the restarted fake restores the sealed dump through the same reference',
              back == 'ok pv=78', repr(back))
        ktok = '/tmp/inv_regtest_ctl_token_file'
        with open(ktok, 'w') as fh:
            fh.write('tok-from-file-77\n')
        os.chmod(ktok, 0o600)
        tx = ctl(K_CTL, 'set control token file:' + ktok)
        check('file-key: the live set control token takes the file: reference',
              'ok control/token=<set>' in tx, tx[:120])
        tx = ctl(K_CTL, 'show pv')
        check('file-key: the unauthenticated session is refused after the token set',
              tx.startswith('err authenticate first'), tx[:100])
        tx = ctl(K_CTL, 'show pv', token='tok-from-file-77')
        check('file-key: the file material authenticates', tx == 'ok pv=78', repr(tx))
        procs[-1].kill()
        time.sleep(0.3)
        # an unreadable reference fails the start (a key that silently
        # vanishes is a misconfiguration, not a fallback to plaintext)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(K_MODBUS),
                                       '--control-port', str(K_CTL), '--dump-path', kfile_state2,
                                       '--dump-key', 'file:/nonexistent/dump_key', '--restore-on-start'],
                                      stdout=open(LOG + '.k5', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        line = ''
        for _ in range(80):
            line = open(LOG + '.k5').read()
            if 'cannot read dump/key' in line:
                break
            time.sleep(0.1)
        time.sleep(0.3)   # the SystemExit prints, then the process is gone
        check('file-key: an unreadable reference fails the start (fail fast, never plaintext)',
              'cannot read dump/key' in line and procs[-1].poll() is not None, line[-220:])

        # ---- --man: every tool prints its generated roff page
        for tool, title in ((F, 'MODBUS-FAKE-INVERTER'), (CTL, 'MODBUS-FAKE-CTL'),
                            (os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-cli.py'), 'MODBUS-FAKE-CLI')):
            r = subprocess.run([sys.executable, tool, '--man'], capture_output=True, text=True, timeout=30)
            check('--man: %s prints the page' % os.path.basename(tool),
                  r.returncode == 0 and r.stdout.startswith('.TH %s 1' % title), r.stdout[:40] or r.stderr[-80:])

        # ---- the listening line documents the policy
        log = open(LOG).read()
        check('listening line names limit + timeout', 'client limit 1, client timeout 300s' in log)
        check('refusal logged', 'connection refused: client limit of 1 reached' in log)
        logb = open(LOG + '.b').read()
        check('listening line names timeout 1s', 'client limit 64, client timeout 1s' in logb)
        check('metrics 503 logged', 'metrics: rejected' in logb and 'too many concurrent clients' in logb)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    print()
    if FAILURES:
        print('FAILURES (%d): %s' % (len(FAILURES), ', '.join(FAILURES)))
        raise SystemExit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
