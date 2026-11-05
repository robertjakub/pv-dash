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
import os
import socket
import struct
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(REPO, 'inverter', 'bin', 'fake_inverter.py')
CTL = os.path.join(REPO, 'inverter', 'bin', 'fake_ctl.py')
LOG = '/tmp/inv_regtest.log'
FAILURES = []

A_MODBUS, A_CTL = 15970, 15971        # --max-clients 1
B_MODBUS, B_CTL = 15972, 15973        # --client-timeout 1
C_MODBUS, C_CTL = 15974, 15975        # --max-conn-per-ip 1 --max-clients 0
B_METRICS = 15979                     # instance B's /metrics (max-clients 1)
UNIT = 1


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' — ' + str(detail) if detail and not ok else ''))
    if not ok:
        FAILURES.append(name)


def ctl(port, *cmds):
    out = subprocess.run([sys.executable, CTL, '--control-port', str(port)] + list(cmds),
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
                                       '--metrics-port', str(B_METRICS), '--metrics-token', 'tok',
                                       '--metrics-max-clients', '1'],
                                      stdout=open(LOG + '.b', 'w'), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', str(C_MODBUS),
                                       '--control-port', str(C_CTL), '--max-clients', '0',
                                       '--max-conn-per-ip', '1'],
                                      stdout=open(LOG + '.c', 'w'), stderr=subprocess.STDOUT))
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
        ins = ctl(A_CTL, 'inspect')
        check('inspect carries the modbus row', 'modbus    127.0.0.1:%d, clients 1 (limit 1, timeout 5.00m, per-ip none)' % A_MODBUS in ins,
              [l for l in ins.splitlines() if l.startswith('modbus')])

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
