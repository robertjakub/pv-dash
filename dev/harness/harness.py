"""The suites' shared harness: the gate, the scratch, the check
accumulator + the shared daemon spawn and Modbus frame builders — the
code every suite carried as a private copy. A suite's first line imports
this module (the import IS the boot: the gate refuses a standalone run,
the scratch is created, the NOTE stamp prints) and the shared names ride
the star import; the suite's own paths, port consts and thin frame
wrappers bind after and override."""

import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# harness/ -> dev/ -> the repo root

if not os.environ.get('PV_RUN_DIR'):   # the battery sets it (dev/battery.py)
    sys.exit('suite: run through dev/battery.py (the run dir + the port slot; '
             'a standalone run shares scratch and collides across sessions)')
SCRATCH = os.environ['PV_RUN_DIR']   # the battery's per-run tmp — every scratch file lands here (the sockets are the daemons' own /tmp constants)
os.makedirs(SCRATCH, exist_ok=True)   # the CI legs set a fixed path the battery never made
print('NOTE started at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))

PROFILE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ('quick', 'full') \
    else os.environ.get('PV_SUITE_PROFILE', 'quick')
BASE = int(os.environ.get('SUITE_PORT_BASE', '0'))   # the concurrent-battery port space (the runner's slot)

failures = []
procs = []


def check(name, cond, detail=''):
    # the detail may be any shape (lists of log rows, captured tool output
    # that itself speaks PASS/FAIL verdict lines) — it stringifies at the
    # render and every line INDENTS, so a captured '^FAIL' can never pose
    # as a check row in the log (the tally greps the column)
    txt = str(detail) if detail else ''
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name,
                       (' — ' + txt.replace('\n', '\n     ')) if txt else ''))
    if not cond:
        failures.append(name)


def start(cmd, log=None, env_extra=None):
    import subprocess
    env = {**os.environ, **(env_extra or {})}
    if log:
        p = subprocess.Popen(cmd, stdout=open(log, 'w'), stderr=subprocess.STDOUT, env=env)
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    procs.append(p)
    return p


def kill_all():
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass


def recvn(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('eof')
        buf += chunk
    return buf


def pack_mbap(txn, unit, pdu):
    """the MBAP frame bytes: the header wrapped around the PDU (no socket)"""
    import struct
    return struct.pack('>HHHB', txn, 0, len(pdu) + 1, unit) + pdu


def mbap(pdu, port, unit=1):
    """one MBAP transaction: the PDU in, the response body out"""
    import socket
    import struct
    s = socket.create_connection(('127.0.0.1', port), timeout=10)
    s.sendall(pack_mbap(77, unit, pdu))
    head = b''
    while len(head) < 7:                          # TCP is a stream: read the
        chunk = s.recv(7 - len(head))             # MBAP header exactly, then
        if not chunk:
            raise ConnectionError('eof')
        head += chunk
    txn_, proto, length, unit_ = struct.unpack('>HHHB', head)
    body = b''
    while len(body) < length - 1:                 # ... the body exactly
        chunk = s.recv(length - 1 - len(body))
        if not chunk:
            raise ConnectionError('eof')
        body += chunk
    s.close()
    return body


def pty_cli(bin_path, rows, cols, args=(), env_extra=None, port=None):
    """the cli bin on a real pty sized rows x cols: stdin/stdout/stderr on
    the slave — the tty edition the suites' piped runs never see. Returns
    (master, proc); the proc joins the kill list."""
    import fcntl
    import pty
    import struct
    import termios
    m, s = pty.openpty()
    fcntl.ioctl(s, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
    env = {**os.environ, 'TERM': 'dumb'}
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, bin_path]
    if port is not None:
        cmd += ['--control-port', str(port)]
    p = subprocess.Popen(cmd + list(args), stdin=s, stdout=s, stderr=s, env=env)
    os.close(s)
    procs.append(p)
    return m, p


def pty_read(m, quiet=0.5, limit=8.0):
    """read the pty master until it goes quiet (the reply whole) or the
    limit passes."""
    import select
    out = b''
    end = time.time() + limit
    while time.time() < end:
        r, _, _ = select.select([m], [], [], quiet)
        if not r:
            if out:
                break
            continue
        try:
            chunk = os.read(m, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    return out.decode('utf-8', 'replace')


def pty_send(m, text):
    """one write to the pty master: a command line ('quit\\n') or one pause
    key ('q' — no newline, the pager reads a single char)."""
    os.write(m, text.encode())


FAILURES = failures   # the suites' upper-case name for the same accumulator list


class QuickDone(Exception):
    pass


def wait_port(port, timeout=20):
    """The daemon's startup race: the bind lands when it lands (the pyc, the
    profile load, the audit init) — poll-connect instead of a blind sleep.
    False when the port never opened — the caller fails its named check."""
    import socket
    end = time.monotonic() + timeout
    while True:
        try:
            socket.create_connection(('127.0.0.1', port), timeout=1).close()
            return True
        except OSError:
            if time.monotonic() >= end:
                return False
            time.sleep(0.2)


def connect(port, timeout=5.0):
    import socket
    return socket.create_connection(('127.0.0.1', port), timeout=timeout)


def _recv_line(s):
    """one newline-terminated JSON frame off the socket, or None on eof —
    the read loop every control client here shares"""
    buf = b''
    while not buf.endswith(b'\n'):
        chunk = s.recv(65536)
        if not chunk:
            return None
        buf += chunk
    return buf


def wire_mac(token, payload):
    """The control wire's frame mac: the full sha256 HMAC, keyed by the token."""
    import hashlib
    import hmac
    return hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()


def signed_wire(cmd, token):
    """The signed wire form of one command (the token'd server refuses the unsigned)."""
    import json as _json
    return _json.dumps({'cmd': cmd, 'mac': wire_mac(token, cmd)}).encode() + b'\n'


def control_roundtrip(port, wire_bytes, timeout=5.0, auth_ports=(), token=None):
    """Send raw bytes, read one line, parse the JSON; (status, text) or
    ('dead', ...). A port in auth_ports speaks the token handshake first
    (the F5 rule: a TCP control port refuses to start without a token) —
    the suites bind their own thin wrappers naming which of their ports
    those are."""
    import json as _json
    try:
        s = connect(port, timeout)
        if port in auth_ports:
            s.sendall(_json.dumps({'cmd': 'auth', 'token': token}).encode() + b'\n')
            buf = _recv_line(s)
            if buf is None:
                s.close()
                return 'dead', 'connection closed during auth'
        s.sendall(wire_bytes)
        buf = _recv_line(s)
        s.close()
        if buf is None:
            return 'dead', 'connection closed without a reply'
        obj = _json.loads(buf.decode('utf-8', 'replace'))
        return str(obj.get('status')), str(obj.get('text', ''))
    except (OSError, ValueError) as e:
        return 'boom', str(e)


def ops_control_roundtrip(cmd, token, port, unsigned=False, timeout=5.0):
    """Auth with the given token (the ops or the admin one), send the command,
    read one reply: (status, text, mac-verifies-with-the-same-token) — the
    ops sessions must be signed and answered with the ops key, the admin
    ones with the admin key. The suites bind the default token and port."""
    import json as _json
    try:
        s = connect(port, timeout)
        s.sendall(_json.dumps({'cmd': 'auth', 'token': token}).encode() + b'\n')
        buf = _recv_line(s)
        if buf is None:
            s.close()
            return 'dead', 'connection closed during auth', False
        auth = _json.loads(buf.decode('utf-8', 'replace'))
        if auth.get('status') != 'ok':
            s.close()
            return 'auth-fail', str(auth.get('text', '')), False
        if token and not unsigned:
            mac = wire_mac(token, cmd)
            s.sendall(_json.dumps({'cmd': cmd, 'mac': mac}).encode() + b'\n')
        else:
            s.sendall(_json.dumps({'cmd': cmd}).encode() + b'\n')
        buf = _recv_line(s)
        s.close()
        if buf is None:
            return 'dead', 'connection closed without a reply', False
        obj = _json.loads(buf.decode('utf-8', 'replace'))
        want = wire_mac(token, '%s %s' % (obj.get('status'), obj.get('text', '')))
        return str(obj.get('status')), str(obj.get('text', '')), obj.get('mac') == want
    except (OSError, ValueError) as e:
        return 'boom', str(e), False


def authed_roundtrip(port, token, cmd, timeout=5.0):
    """Auth with the token, send the mac'd command, read one reply: a dict.
    Asserts nothing — the caller checks the mac against the token it passed
    (the ops sessions must be signed with the ops key, the admin ones with
    the admin key)."""
    import json as _json
    try:
        s = connect(port, timeout)
        s.sendall(_json.dumps({'cmd': 'auth', 'token': token}).encode() + b'\n')
        buf = _recv_line(s)
        if buf is None:
            return {'status': 'dead', 'text': 'connection closed during auth'}
        auth = _json.loads(buf.decode('utf-8', 'replace'))
        if auth.get('status') != 'ok':
            s.close()
            return {'status': 'auth-fail', 'text': str(auth.get('text', ''))}
        s.sendall(signed_wire(cmd, token))
        buf = _recv_line(s)
        s.close()
        if buf is None:
            return {'status': 'dead', 'text': 'connection closed without a reply'}
        obj = _json.loads(buf.decode('utf-8', 'replace'))
        obj['_mac_ok'] = obj.get('mac') == wire_mac(token, '%s %s' % (obj.get('status'), obj.get('text', '')))
        return obj
    except (OSError, ValueError) as e:
        return {'status': 'boom', 'text': str(e)}
