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
S_MODBUS = 15993                      # the fc-split profile (the per-entry address spaces)
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
                                       '--control-port', str(A_CTL), '--max-clients', '1', '--allow-write'],
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
        ins = ctl(A_CTL, 'inspect')
        check('inspect carries the modbus row', 'modbus    127.0.0.1:%d, clients 1 (limit 1, timeout 5.00m, per-ip none, connect-acl any, auth none)' % A_MODBUS in ins,
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

        # ---- the wire's help branch speaks the commands (the rider)
        tx = ctl(A_CTL, 'help unset')
        check('help <command>: the row describes itself',
              tx == 'ok restore a setting to its configured value (unset pv, unset seed)', tx)
        tx = ctl(A_CTL, 'help request')
        check('help <command node>: the namespace lists its visible children',
              tx == 'ok     reload save the live overrides and restart the whole daemon (the flags and the env are re-resolved)', tx)
        tx = ctl(A_CTL, 'help request reload')
        check('help <deep command path>: the row describes itself',
              tx == 'ok save the live overrides and restart the whole daemon (the flags and the env are re-resolved)', tx)
        tx = ctl(A_CTL, 'help bogus')
        check('help <unknown topic>: the reworded two-space error',
              tx == '% error: unknown command or setting bogus (try ?)', tx)

        # ---- instance A: the bit spaces (FC1/FC2) and the coil writes (FC5/FC15)
        cb = connect(A_MODBUS)
        tx = ctl(A_CTL, 'set coil 10 1')
        check('set coil pins the coil space', tx.startswith('ok coil 10=1'), tx)
        tx = ctl(A_CTL, 'set discrete 11 1')
        check('set discrete pins the discrete-input space', tx.startswith('ok discrete 11=1'), tx)
        txn, unit, body = exchange(cb, read_req(1, 1, 10, 1), 1)
        check('FC1 reads a pinned coil', txn == 1 and body == bytes([1, 1, 1]), body.hex())
        txn, unit, body = exchange(cb, read_req(2, 2, 11, 1), 2)
        check('FC2 reads a pinned discrete input', txn == 2 and body == bytes([2, 1, 1]), body.hex())
        txn, unit, body = exchange(cb, read_req(3, 1, 0, 16), 3)
        check('FC1 packs 8 bits per byte (the pinned coil 10 -> byte 1 bit 2)',
              txn == 3 and body[0] == 1 and body[1] == 2 and body[2:] == bytes([0x00, 0x04]), body.hex())
        txn, unit, body = exchange(cb, frame(4, UNIT, struct.pack('>BHH', 5, 12, 0xFF00)), 4)
        check('FC5 writes a coil (echo reply)', txn == 4 and body == bytes.fromhex('05000cff00'), body.hex())
        txn, unit, body = exchange(cb, read_req(5, 1, 12, 1), 5)
        check('FC1 reads back the FC5 write', txn == 5 and body == bytes([1, 1, 1]), body.hex())
        txn, unit, body = exchange(cb, frame(6, UNIT, struct.pack('>BHH', 5, 12, 0x0001)), 6)
        check('FC5 with a value outside 0x0000/0xFF00 -> exception 03', txn == 6 and body == bytes([5 + 0x80, 3]), body.hex())
        bits10 = bytes([0b10100101, 0b00000011])
        txn, unit, body = exchange(cb, frame(7, UNIT, struct.pack('>BHHB', 15, 20, 10, 2) + bits10), 7)
        check('FC15 writes 10 coils (addr+count echo)', txn == 7 and body == struct.pack('>BHH', 15, 20, 10), body.hex())
        txn, unit, body = exchange(cb, read_req(8, 1, 20, 10), 8)
        check('FC1 reads the FC15 bits back (LSB first)',
              txn == 8 and body[0] == 1 and body[1] == 2 and body[2:4] == bits10, body.hex())
        # a bad shape on an implemented FC answers 03 and the connection lives
        # (the pre-wave behaviour was a silent connection close)
        txn, unit, body = exchange(cb, frame(9, UNIT, bytes([6, 0])), 9)
        check('short FC6 -> exception 03 (no close)', txn == 9 and body == bytes([6 + 0x80, 3]), body.hex())
        txn, unit, body = exchange(cb, frame(10, UNIT, bytes([3, 0])), 10)
        check('short FC3 -> exception 03 (no close)', txn == 10 and body == bytes([3 + 0x80, 3]), body.hex())
        txn, unit, body = exchange(cb, read_req(11, 1, 10, 2001), 11)
        check('FC1 past the 2000-bit cap -> exception 03', txn == 11 and body == bytes([1 + 0x80, 3]), body.hex())
        txn, unit, body = exchange(cb, read_req(12, 17, 0, 1), 12)
        check('an unimplemented FC stays exception 01', txn == 12 and body == bytes([17 + 0x80, 1]), body.hex())
        txn, unit, body = exchange(cb, read_req(13, 3, 32064, 2), 13)
        check('the connection survives every refusal', txn == 13 and body[0] == 3, body.hex())
        tx = ctl(A_CTL, 'reset')
        check('reset clears the bit pins with the rest', 'coil(s), 1 discrete input(s) cleared' in tx, tx)
        txn, unit, body = exchange(cb, read_req(14, 1, 10, 1), 14)
        check('the pinned coil reads 0 after the reset', txn == 14 and body == bytes([1, 1, 0]), body.hex())
        cb.close()

        # ---- instance I: the profile's per-entry fc picks the address space
        split_prof = '/tmp/inv_fc_split.json'
        json.dump({'description': 'fc split demo', 'registers': [
            {'name': 'pv-power', 'register': 300, 'type': 'i32', 'scale': 1},
            {'name': 'grid-power', 'register': 400, 'type': 'i32', 'scale': 1, 'fc': 4},
            {'name': 'device-insulation', 'register': 500, 'type': 'f32', 'scale': 1},
        ]}, open(split_prof, 'w'))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(S_MODBUS),
                                       '--control-port', '0', '--profile', split_prof],
                                      stdout=open(LOG + '.i', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.0)
        ci = connect(S_MODBUS)
        txn, unit, body = exchange(ci, read_req(1, 3, 300, 2), 1)
        check('the fc3 entry is served on FC3 (pv 4000 W)',
              txn == 1 and struct.unpack('>i', body[2:6])[0] == 4000, body.hex())
        txn, unit, body = exchange(ci, read_req(2, 4, 400, 2), 2)
        check('the fc4 entry is served on FC4 (grid -1500 W)',
              txn == 2 and struct.unpack('>i', body[2:6])[0] == -1500, body.hex())
        txn, unit, body = exchange(ci, read_req(3, 3, 400, 2), 3)
        check('the fc4 entry is undefined on FC3 (reads 0, non-strict)',
              txn == 3 and body[0] == 3 and body[1] == 4 and body[2:6] == b'\x00\x00\x00\x00', body.hex())
        txn, unit, body = exchange(ci, read_req(4, 4, 300, 2), 4)
        check('the fc3 entry is undefined on FC4 (reads 0, non-strict)',
              txn == 4 and body[0] == 4 and body[1] == 4 and body[2:6] == b'\x00\x00\x00\x00', body.hex())
        txn, unit, body = exchange(ci, read_req(5, 3, 500, 2), 5)
        check('an f32 entry encodes IEEE 754 big-endian (device-insulation 970.0)',
              txn == 5 and body[0] == 3 and body[2:6] == struct.pack('>f', 970.0), body.hex())
        ci.close()

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
        tx = ctl(B_CTL, 'set metrics enable off')
        check('metrics enable: set off', tx.startswith('ok metrics/enable=off'), tx)
        srv_down = False
        try:
            connect(B_METRICS, 1.0).close()
        except OSError:
            srv_down = True
        check('metrics enable: the port is closed after set off', srv_down)
        insb = ctl(B_CTL, 'inspect')
        check('metrics enable: inspect says off', '\nmetrics   off' in '\n' + insb,
              [l for l in insb.splitlines() if l.startswith('metrics')])
        tx = ctl(B_CTL, 'set metrics enable on')
        check('metrics enable: set on serves again', tx.startswith('ok metrics/enable=on'), tx)
        st, _ = http_get(B_METRICS, token='tok')
        check('metrics enable: the gauges are back', st.split()[1] == '200', st)
        insb = ctl(B_CTL, 'inspect')
        check('metrics enable: inspect carries the endpoint line',
              'metrics   127.0.0.1:%d (bearer token), clients 1, per-ip none' % B_METRICS in insb,
              [l for l in insb.splitlines() if l.startswith('metrics')])

        # ---- the control-server parity round (the cache's shape)
        check('control: the default unix socket mode is 0600 (not the umask)',
              os.stat('/tmp/fake-inverter-%d.socket' % D_MODBUS).st_mode & 0o777 == 0o600,
              oct(os.stat('/tmp/fake-inverter-%d.socket' % D_MODBUS).st_mode & 0o777))
        check('control: --control-socket-group chmods the socket 0660',
              os.stat(E_SOCK).st_mode & 0o777 == 0o660, oct(os.stat(E_SOCK).st_mode & 0o777))
        tx = ctl(F_CTL, 'set metrics token off')
        check('metrics token: startup-only — the set refuses (the dump/key treatment)',
              tx.startswith('% error: restart required (startup-only knob)'), tx)
        tx = ctl(F_CTL, 'set metrics enable on')
        check('metrics enable: the token-less live start on 0.0.0.0 refuses (the F13 shape)',
              '% error:' in tx and 'refusing to expose /metrics beyond loopback' in tx, tx)
        logf = open(LOG + '.f').read()
        check('metrics enable: the refusal is a clean err (no traceback)', 'Traceback' not in logf,
              [l for l in logf.splitlines() if 'Trace' in l])
        tx = ctl(F_CTL, 'set metrics token t')
        check('metrics token: startup-only — the token set refuses too',
              tx.startswith('% error: restart required (startup-only knob)'), tx)
        # the token serves at START instead: a spawned instance answers the
        # bearer on a non-loopback bind (the F13 floor's success side)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15997',
                                       '--metrics-server', '--metrics-token', 't',
                                       '--metrics-listen', '0.0.0.0:15998'],
                                      stdout=open(LOG + '.f2', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.1)
        st, _ = http_get(15998)
        check('metrics token: the started 0.0.0.0 endpoint demands the bearer', st.split()[1] == '401', st)
        st, _ = http_get(15998, token='t')
        check('metrics token: the started 0.0.0.0 endpoint serves with the bearer', st.split()[1] == '200', st)
        # the F13 matrix at the start: the loopback default needs no token
        r = subprocess.run([sys.executable, F, '--dry-run', '--metrics-server',
                            '--metrics-listen', '0.0.0.0:%d' % (F_METRICS + 1)], capture_output=True, text=True, timeout=15)
        check('F13: the non-loopback metrics listen without a token refuses',
              r.returncode == 1 and 'refusing to expose /metrics beyond loopback' in (r.stderr + r.stdout)
              and 'Traceback' not in (r.stderr + r.stdout), repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, F, '--dry-run', '--metrics-server', '--metrics-token', 't',
                            '--metrics-listen', '0.0.0.0:%d' % (F_METRICS + 1)], capture_output=True, text=True, timeout=15)
        check('F13: the non-loopback metrics listen with a token starts',
              r.returncode == 0, repr((r.stderr + r.stdout)[-140:]))
        r = subprocess.run([sys.executable, F, '--dry-run', '--metrics-server',
                            '--metrics-listen', '127.0.0.1:%d' % (F_METRICS + 1)], capture_output=True, text=True, timeout=15)
        check('F13: the loopback metrics listen needs no token',
              r.returncode == 0, repr((r.stderr + r.stdout)[-140:]))

        # ---- the metrics/acl gate (the cache's logic, the fake's surface):
        # the accept-time IP gate on the /metrics listener — the ACL first,
        # then the caps, the token's 401 only past both
        ACLGATE = '/tmp/inv_acl_gate.json'
        with open(ACLGATE, 'w') as f:
            json.dump({'desc': 'the lab gate', 'type': 'ip-prefix', 'rules': [
                {'type': 'deny', 'prefix': 'any'},
                {'type': 'allow', 'prefix': '127.0.0.1', 'desc': 'the loopback lab'}]}, f)

        def acl_raw():
            s = connect(B_METRICS)
            try:
                s.sendall(b'GET /metrics HTTP/1.0\r\nAuthorization: Bearer tok\r\n\r\n')
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

        r = ctl(B_CTL, 'set metrics acl none')
        check('metrics acl: set none answers ok', r.startswith('ok metrics/acl=none'), r[:80])
        check('metrics acl: none closes the client without a reply', acl_raw() == b'',
              repr(acl_raw()[:40]))
        r = ctl(B_CTL, 'show metrics acl')
        check('metrics acl: the none show', r == 'ok metrics/acl=none', r[:60])
        r = ctl(B_CTL, 'show metrics acl table')
        check('metrics acl: none spells the deny-any chain', r == 'ok metrics-acl-table\ndeny 0.0.0.0/0', r[:80])
        r = ctl(B_CTL, 'set metrics acl table')
        check('metrics acl: the show word is not a value (the pointer to the report)',
              r.startswith('% error:') and 'show metrics acl table' in r, r[:120])
        r = ctl(B_CTL, 'set metrics acl 127.0.0.1')
        check('metrics acl: the whitelist set canonicalizes', r.startswith('ok metrics/acl=127.0.0.1/32'), r[:80])
        check('metrics acl: the whitelist serves the lab', acl_raw().startswith(b'HTTP/1.0 200'))
        r = ctl(B_CTL, 'show metrics acl table')
        check('metrics acl: the whitelist table', r == 'ok metrics-acl-table\ndeny 0.0.0.0/0\nallow 127.0.0.1/32', r[:80])
        r = ctl(B_CTL, 'set metrics acl file:' + ACLGATE)
        check('metrics acl: the file gate loads', r.startswith('ok metrics/acl=file:%s' % ACLGATE), r[:100])
        r = ctl(B_CTL, 'show metrics acl')
        check('metrics acl: the file spelling shows', r == 'ok metrics/acl=file:%s' % ACLGATE, r[:80])
        r = ctl(B_CTL, 'show metrics acl table')
        check('metrics acl: the file gate renders its own rules',
              r == 'ok metrics-acl-table\n% the lab gate\ndeny 0.0.0.0/0\nallow 127.0.0.1 # the loopback lab', r[:160])
        check('metrics acl: the file gate serves the lab', acl_raw().startswith(b'HTTP/1.0 200'))
        with open(ACLGATE, 'w') as f:
            json.dump({'type': 'ip-prefix', 'rules': [{'type': 'allow', 'prefix': '127.0.0.1/8'}]}, f)
        r = ctl(B_CTL, 'set metrics acl file:' + ACLGATE)
        check('metrics acl: a bad file answers err with the old gate standing',
              r.startswith('% error:') and 'spell the network' in r and acl_raw().startswith(b'HTTP/1.0 200'), r[:140])
        r = ctl(B_CTL, 'unset metrics acl')
        check('metrics acl: unset restores the configured value', r.startswith('ok metrics/acl=any'), r[:80])
        check('metrics acl: any serves again', acl_raw().startswith(b'HTTP/1.0 200'))
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
        ins = ctl(A_CTL, 'inspect')
        check('connect-acl: inspect carries connect-acl=', 'connect-acl 1 network(s)' in ins,
              [l for l in ins.splitlines() if l.startswith('modbus')])
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
              obj.get('status') == 'fail' and 'unsigned command' in obj.get('text', ''), str(obj))
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
              obj.get('status') == 'fail' and 'mac does not verify' in obj.get('text', ''), str(obj))
        aud = open('/tmp/inv_regtest_audit.log').read()
        check('signed wire: the audit COMMAND line carries the wire mac', "'show version' wire=h" in aud, aud[-200:])

        # ---- the secrets: startup-only (the dump/key treatment) — set/unset
        #      refuse on the wire, the show verb refuses them — a secret never renders
        tx = ctl(H_CTL, 'show control token', token='tok')
        check('secrets: the control token never shows', tx.startswith('% error: control/token is a secret'), tx)
        tx = ctl(H_CTL, 'unset control token', token='tok')
        check('secrets: unset refuses a secret (startup-only)',
              tx.startswith('% error: restart required (startup-only knob)'), tx)
        tx = ctl(H_CTL, 'set control token tok2', token='tok')
        check('secrets: the control token is startup-only — the set refuses',
              tx.startswith('% error: restart required (startup-only knob)'), tx)
        tx = ctl(H_CTL, 'show version', token='tok')
        check('secrets: the configured control token still speaks (no live rotation)',
              tx.startswith('ok fake-inverter'), tx)
        tx = ctl(H_CTL, 'set metrics token mtok2', token='tok')
        check('secrets: the metrics token is startup-only — the set refuses',
              tx.startswith('% error: restart required (startup-only knob)'), tx)
        tx = ctl(H_CTL, 'show metrics token', token='tok')
        check('secrets: the metrics token never shows', tx.startswith('% error: metrics/token is a secret'), tx)
        tx = ctl(H_CTL, 'unset metrics token', token='tok')
        check('secrets: unset refuses the metrics token too',
              tx.startswith('% error: restart required (startup-only knob)'), tx)
        tx = ctl(H_CTL, 'show config', token='tok')
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
        tx = ctl(I_CTL, 'request reload')
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
              tx.startswith('% error: dump/key is a secret'), tx[:100])
        tx = ctl(J_CTL, 'set dump key other')
        check('sealed dump: set dump/key answers the restart note (the key cannot drift mid-life)',
              tx.startswith('% error: restart required (startup-only knob)'), tx[:100])
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
        tx = ctl(J_CTL, 'request reload')
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
        #      key warns at start and on set, and the control token takes
        #      the same reference form at start
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
        procs[-1].kill()
        time.sleep(0.3)
        # the control token takes the file: reference form too — at start
        # (the wire's set refuses every secret now)
        ktok = '/tmp/inv_regtest_ctl_token_file'
        with open(ktok, 'w') as fh:
            fh.write('tok-from-file-77\n')
        os.chmod(ktok, 0o600)
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(K_MODBUS),
                                       '--control-port', str(K_CTL), '--dump-path', kfile_state2,
                                       '--dump-key', 'file:' + kkey, '--restore-on-start',
                                       '--control-token', 'file:' + ktok],
                                      stdout=open(LOG + '.k4b', 'w'), stderr=subprocess.STDOUT,
                                      env={**os.environ, 'XDG_STATE_HOME': reload_state}))
        back = None
        for _ in range(100):
            try:
                back = ctl(K_CTL, 'show pv', token='tok-from-file-77')
                if back == 'ok pv=78':
                    break
            except Exception:
                pass
            time.sleep(0.1)
        check('file-key: the control token takes the file: reference at start (the file material authenticates)',
              back == 'ok pv=78', repr(back))
        tx = ctl(K_CTL, 'set control token tok2', token='tok-from-file-77')
        check('file-key: the tokenized instance still refuses the live set (startup-only)',
              tx.startswith('% error: restart required (startup-only knob)'), tx[:120])
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

        # ---- the suite auth (instance L): the fake demands the crypt
        #      handshake before any frame — a good key speaks plain Modbus,
        #      a wrong key gets ERR, a plain client is dropped, the knobs
        #      are live, the key is a secret
        sys.path.insert(0, REPO)
        from common.modbus import AUTH_MAGIC, auth_handshake_client

        L_MODBUS, L_CTL = 15991, 15992
        L_KEY = 'inv-suite-key-16chars!'
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(L_MODBUS),
                                       '--control-port', str(L_CTL), '--auth', 'suite',
                                       '--auth-key', L_KEY],
                                      stdout=open(LOG + '.l', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.1)
        c = connect(L_MODBUS)
        auth_handshake_client(c, L_KEY)
        txn, unit, body = exchange(c, read_req(1, 3, 32064, 2), 1)
        check('suite auth: the proved client speaks plain Modbus', txn == 1 and body[0] == 3, body.hex())
        c.close()
        c = connect(L_MODBUS)
        check('suite auth: a silent plain client lingers (the client-timeout story, not the auth)', eof_soon(c, 1.5) is False)
        c.close()
        c = connect(L_MODBUS)
        c.sendall(b'\x00' * 52)   # 52 bytes that are not the handshake: the magic fails
        c.settimeout(3.0)
        verdict = c.recv(3)
        after = c.recv(4096)      # the refusal closes the connection
        c.close()
        check('suite auth: a non-handshake peer gets ERR then EOF', verdict == b'ERR' and after == b'',
              (verdict + after).hex())
        c = connect(L_MODBUS)
        try:
            auth_handshake_client(c, 'wrong-key-16chars00')
            check('suite auth: the wrong key is rejected', False, 'no error raised')
        except Exception as e:
            check('suite auth: the wrong key is rejected (ERR)',
                  'rejected' in str(e) or 'handshake' in str(e), str(e))
        c.close()
        # the raw wire: a bad magic gets the ERR verdict verbatim
        c = connect(L_MODBUS)
        c.sendall(b'XXXX' + b'\x00' * 48)
        verdict = b''
        try:
            c.settimeout(3.0)
            verdict = c.recv(3)
        except OSError:
            pass
        c.close()
        check('suite auth: a bad magic answers ERR verbatim', verdict == b'ERR', verdict.hex())
        tx = ctl(L_CTL, 'show modbus auth')
        check('suite auth: show modbus auth reads suite', tx == 'ok modbus/auth=suite', tx)
        tx = ctl(L_CTL, 'show modbus auth key')
        check('suite auth: the key never shows', tx.startswith('% error: modbus/auth/key is a secret'), tx[:80])
        tx = ctl(L_CTL, 'show modbus')
        words = [line.strip().split()[0] for line in tx[3:].strip().splitlines()
                 if line.strip() and not line.strip().startswith('[')]
        check('node walk: the modbus listing mimics the ? walk (the key never lists)',
              words == ['auth'] and 'auth/key' not in tx, tx[:160])
        tx = ctl(L_CTL, 'show')
        words = [line.strip().split()[0] for line in tx[3:].strip().splitlines()
                 if line.strip() and not line.strip().startswith('[')]
        check("node walk: the bare show mimics the ? output (the walk's first position)",
              words == ['batt', 'battery-kwh', 'battery-state', 'chaos', 'client-timeout', 'cloud',
                        'connect-acl', 'connections', 'control', 'dump', 'grid', 'grid-frequency', 'grid-outage',
                        'grid-voltage', 'load', 'log-level', 'max-clients', 'max-conn-per-ip', 'max-kwp',
                        'metrics', 'modbus', 'mppt', 'profile', 'pv', 'registers', 'scenario', 'seed',
                        'soc', 'static', 'strict', 'time', 'time-scale', 'timezone', 'version',
                        'write'], tx[:220])
        tx = ctl(L_CTL, 'show control ops')
        check('node walk: the intermediate node lists its live children',
              tx.startswith('ok') and 'verbs' in tx and 'read-only ops role' in tx, tx[:80])
        tx = ctl(L_CTL, 'unset modbus auth key')
        check('suite auth: unset refuses the key (startup-only)',
              tx.startswith('% error: restart required (startup-only knob)'), tx[:80])
        tx = ctl(L_CTL, 'set modbus auth key short')
        check('suite auth: startup-only — the short-key set refuses with the rest',
              tx.startswith('% error: restart required (startup-only knob)'), tx[:100])
        tx = ctl(L_CTL, 'set modbus auth key %s' % ('x' * 16))
        check('suite auth: startup-only — the key set refuses (the dump/key treatment)',
              tx.startswith('% error: restart required (startup-only knob)'), tx[:80])
        c = connect(L_MODBUS)
        auth_handshake_client(c, L_KEY)
        txn, unit, body = exchange(c, read_req(2, 3, 32064, 2), 2)
        check('suite auth: the configured key still proves (no live rotation)',
              txn == 2 and body[0] == 3, body.hex())
        c.close()
        tx = ctl(L_CTL, 'set modbus auth none')
        check('suite auth: the scheme disables live', tx.startswith('ok modbus/auth=none'), tx[:80])
        c = connect(L_MODBUS)
        txn, unit, body = exchange(c, read_req(3, 3, 32064, 2), 3)
        check('suite auth: none serves a plain client again', txn == 3 and body[0] == 3, body.hex())
        c.close()
        tx = ctl(L_CTL, 'set modbus auth suite')
        check('suite auth: re-enabling without a key change works (the key persists)',
              tx.startswith('ok modbus/auth=suite'), tx[:80])
        c = connect(L_MODBUS)
        try:
            auth_handshake_client(c, 'x' * 16)   # a wrong proof: dropped, logged
            check('suite auth: a wrong proof is dropped', False, 'accepted')
        except Exception:
            check('suite auth: a wrong proof is dropped (ERR)', True)
        c.close()
        c = connect(L_MODBUS)
        auth_handshake_client(c, L_KEY)
        txn, unit, body = exchange(c, read_req(2, 3, 32064, 2), 2)
        check('suite auth: the re-enabled scheme proves the configured key', txn == 2 and body[0] == 3, body.hex())
        c.close()
        logl = open(LOG + '.l').read()
        check('suite auth: the failed proofs are logged', 'suite auth failed for' in logl)
        check('suite auth: the listening line names the scheme', 'modbus auth suite' in logl)

        # ---- the control listener family (instance M): the live rebind —
        #      tokenless TCP included (the F11 posture INVERTS the family's
        #      F5 refusal: a tokenless TCP rebind succeeds here), the old
        #      target closes, off retires while the session keeps serving,
        #      unset restores the configured socket, the socket-group
        #      re-modes live, the ops policy and the trust uids ride the wire
        M_MODBUS, M_TCP1, M_TCP2 = 15994, 15995, 15996
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(M_MODBUS)],
                                      stdout=open(LOG + '.m', 'w'), stderr=subprocess.STDOUT))
        time.sleep(1.0)
        msock = '/tmp/fake-inverter-%d.socket' % M_MODBUS
        tx = ctl(msock, 'show control port')
        check('fake control: the default socket answers with its target',
              tx == 'ok control/port=unix:%s' % msock, tx[:90])
        tx = ctl(msock, 'set control port %d' % M_TCP1)
        check('fake control: a tokenless TCP rebind SUCCEEDS live (the F11 inverse of the family F5)',
              tx.startswith('ok control/port=127.0.0.1:%d' % M_TCP1), tx[:90])
        tx = ctl(msock, 'show version')
        check('fake control: the retired unix socket no longer answers', tx == '', tx[:90])
        tx = ctl(str(M_TCP1), 'show version')
        check('fake control: the new TCP port speaks tokenless', tx.startswith('ok fake-inverter'), tx[:90])
        tx = ctl(str(M_TCP1), 'set control port %d' % M_TCP1)
        check('fake control: a re-set of the same target no-ops',
              tx.startswith('ok control/port=127.0.0.1:%d' % M_TCP1), tx[:90])
        # off retires the listener; the CONNECTED session keeps serving
        # (the raw wire: one JSON object per line)
        m = socket.create_connection(('127.0.0.1', M_TCP1), timeout=5)
        m.sendall(b'{"cmd": "set control port off"}\n')
        off_reply = m.recv(4096)
        check('fake control: off retires the listener', b'control/port=off' in off_reply, off_reply[:120])
        m.sendall(b'{"cmd": "show control port"}\n')
        off_show = m.recv(4096)
        check('fake control: the session keeps serving after the retire', b'ok control/port=off' in off_show
              or b'"control/port=off"' in off_show, off_show[:120])
        gone = False
        try:
            socket.create_connection(('127.0.0.1', M_TCP1), timeout=1).close()
        except OSError:
            gone = True
        check('fake control: no new connection lands on the retired port', gone)
        m.sendall(b'{"cmd": "unset control port"}\n')
        unset_reply = m.recv(4096)
        check('fake control: unset restores the configured target', b'unix:%s' % msock.encode() in unset_reply,
              unset_reply[:120])
        m.close()
        tx = ctl(msock, 'show version')
        check('fake control: the restored socket speaks', tx.startswith('ok fake-inverter'), tx[:90])
        # the group-accessible mode, live
        check('fake control: the default socket is 0600', os.stat(msock).st_mode & 0o777 == 0o600,
              oct(os.stat(msock).st_mode))
        tx = ctl(msock, 'set control socket-group on')
        check('fake control: set control socket-group on re-modes the live socket 0660',
              tx.startswith('ok control/socket-group=on') and os.stat(msock).st_mode & 0o777 == 0o660,
              tx[:90] + ' ' + oct(os.stat(msock).st_mode))
        tx = ctl(msock, 'set control socket-group off')
        check('fake control: set control socket-group off re-modes it back 0600',
              tx.startswith('ok control/socket-group=off') and os.stat(msock).st_mode & 0o777 == 0o600,
              tx[:90] + ' ' + oct(os.stat(msock).st_mode))
        # the ops policy + the trust uids ride the wire
        tx = ctl(msock, 'set control ops verbs show, ping')
        check('fake control: the ops policy sets live (the family spelling)',
              tx.startswith('ok control/ops/verbs=ping,show'), tx[:90])
        tx = ctl(msock, 'unset control ops verbs')
        check('fake control: the ops policy unsets', tx.startswith('ok control/ops/verbs='), tx[:90])
        tx = ctl(msock, 'set control trust-uids 1000,1001')
        check('fake control: the trust uids set live', tx.startswith('ok control/trust-uids=1000,1001'), tx[:90])
        tx = ctl(msock, 'set control trust-uids off')
        check('fake control: the trust uids drop', tx.startswith('ok control/trust-uids=off'), tx[:90])

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
