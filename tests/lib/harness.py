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
# lib/ -> tests/ -> the repo root

if not os.environ.get('PV_RUN_DIR'):   # the battery sets it (tests/battery.py)
    sys.exit('suite: run through tests/battery.py (the run dir + the port slot; '
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
