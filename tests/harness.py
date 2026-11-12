"""The suites' shared harness: the gate, the scratch, the check
accumulator + the shared daemon spawn and Modbus frame builders — the
code every suite carried as a private copy. A suite's first line imports
this module (the import IS the boot: the gate refuses a standalone run,
the scratch is created, the NOTE stamp prints) and the shared names ride
the star import; the suite's own paths, port consts and thin frame
wrappers bind after and override."""

import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if not os.environ.get('PV_RUN_DIR'):   # the battery sets it (scripts/battery.py)
    sys.exit('suite: run through scripts/battery.py (the run dir + the port slot; '
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
