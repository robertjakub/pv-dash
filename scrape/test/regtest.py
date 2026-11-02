#!/usr/bin/env python3
"""Regression suite for modbus-scraper (+ fake inverter).

Run from anywhere: python3 scrape/test/regtest.py
Starts its own fake inverter + scraper instances on scratch ports and
cleans up after itself.
"""
import os
import random
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPE_DIR = os.path.dirname(TEST_DIR)
REPO = os.path.dirname(SCRAPE_DIR)
P = os.path.join(SCRAPE_DIR, 'src', 'scraper.py')
F = os.path.join(SCRAPE_DIR, 'src', 'fake_inverter.py')
FAKE_PORT = 15541
PORT_A, PORT_B = 19441, 19442

failures = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name, (' — ' + detail) if detail else ''))
    if not cond:
        failures.append(name)


def get(path, port, timeout=5, headers=None):
    """GET a path, return (status, body)."""
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path))
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def metrics_dict(body):
    out = {}
    for line in body.splitlines():
        if line and not line.startswith('#'):
            name, _, value = line.rpartition(' ')
            out[name] = float(value)
    return out


def wait_metrics(port, tries=30):
    for _ in range(tries):
        try:
            status, body = get('/metrics', port)
            return status, metrics_dict(body)
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise SystemExit('scraper on %d never came up' % port)


def _recvn(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('peer closed')
        buf += chunk
    return buf


def i32_regs(d, addr, value):
    v = int(value) & 0xFFFFFFFF
    d[addr], d[addr + 1] = v >> 16, v & 0xFFFF


class EvilInverter:
    """Scripted FC3 server: live-mutable register map + hostile reply modes."""

    def __init__(self, port, values):
        self.values = values
        self.mode = 'fine'  # fine | garbage | short | lying | txn | unit | bc | stall | garbage_after
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', port))
        srv.listen(8)
        srv.settimeout(0.2)
        self.srv = srv
        self.running = True
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while self.running:
            try:
                conn, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        try:
            conn.settimeout(5)
            while True:
                tid, _pid, length = struct.unpack('>HHH', _recvn(conn, 6))
                rest = _recvn(conn, length)
                uid, fc = rest[0], rest[1]
                if fc != 3 or len(rest) < 6:
                    raise ConnectionError('unsupported request')
                start, count = struct.unpack('>HH', rest[2:6])
                payload = bytes([count * 2]) + b''.join(
                    struct.pack('>H', self.values.get(a, 0)) for a in range(start, start + count))
                mode = self.mode
                if mode == 'garbage':
                    conn.sendall(b'\xde\xad\xbe\xef' * 8)
                    raise ConnectionError('garbage sent')
                if mode == 'short':
                    conn.sendall(struct.pack('>HHH', tid, 0, 8) + bytes([uid, 3]))
                    raise ConnectionError('short body sent')
                if mode == 'lying':
                    conn.sendall(struct.pack('>HHH', tid, 0, 0xFFFF) + bytes([uid, 3]) + b'\x00' * 8)
                    raise ConnectionError('lying length sent')
                if mode == 'txn':
                    conn.sendall(struct.pack('>HHH', (tid + 1) & 0xFFFF, 0, 2 + len(payload))
                                 + bytes([uid, 3]) + payload)
                elif mode == 'unit':
                    conn.sendall(struct.pack('>HHH', tid, 0, 2 + len(payload))
                                 + bytes([uid + 1, 3]) + payload)
                elif mode == 'bc':
                    conn.sendall(struct.pack('>HHH', tid, 0, 2 + len(payload))
                                 + bytes([uid, 3]) + struct.pack('>H', 99) + payload[2:])
                elif mode == 'stall':
                    time.sleep(10)  # the client's read timeout must fire first
                elif mode == 'garbage_after':
                    conn.sendall(struct.pack('>HHH', tid, 0, 2 + len(payload))
                                 + bytes([uid, 3]) + payload + b'\xde\xad' * 4)
                else:
                    conn.sendall(struct.pack('>HHH', tid, 0, 2 + len(payload)) + bytes([uid, 3]) + payload)
        except (ConnectionError, OSError, struct.error, IndexError):
            pass
        finally:
            conn.close()

    def stop(self):
        self.running = False
        self.srv.close()


def write_ini(path, extra=''):
    with open(path, 'w') as fh:
        fh.write('[scraper]\ninterval = 0.3\ntimeout = 1\n%s\n' % extra)


procs = []
try:
    # 1. baseline: fake with battery + scraper with battery enabled
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', str(FAKE_PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    write_ini('/tmp/scr_base.ini')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_base.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:%d' % PORT_A, '--battery'],
                                  stdout=open('/tmp/scr_reg.log', 'w'), stderr=subprocess.STDOUT))
    status, m = wait_metrics(PORT_A)
    check('pv value', m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_pv_generation_watts')))
    check('grid net = -1500 (positive = export)', m.get('huawei_grid_net_watts') == -1500)
    check('export/import split', m.get('huawei_grid_export_watts') == 0 and m.get('huawei_grid_import_watts') == 1500)
    check('home = pv - batt - grid = 4300', m.get('huawei_home_consumption_watts') == 4300,
          str(m.get('huawei_home_consumption_watts')))
    check('battery net + charge + soc', m.get('huawei_battery_net_watts') == 1200
          and m.get('huawei_battery_charge_watts') == 1200
          and m.get('huawei_battery_discharge_watts') == 0
          and m.get('huawei_battery_soc_percent') == 65)
    check('battery flag + health gauges', m.get('huawei_battery') == 1 and m.get('huawei_up') == 1
          and m.get('huawei_modbus_errors_total') == 0 and m.get('huawei_last_poll_timestamp_seconds', 0) > 0)
    check('cache diag auto-detected (fake serves the block)', m.get('huawei_cache_device_up') == 1
          and m.get('huawei_cache_age_seconds') == 7 and m.get('huawei_cache_uptime_seconds') == 4242,
          str({k: v for k, v in m.items() if 'cache' in k}))
    status, root = get('/', PORT_A)
    check('root path answers', status == 200 and b'modbus-scraper' in root.encode())
    status, _ = get('/nope', PORT_A)
    check('404 for unknown paths', status == 404)

    # 2. battery disabled: flag 0, no battery metrics
    write_ini('/tmp/scr_nobatt.ini')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_nobatt.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:%d' % PORT_B],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    status, m = wait_metrics(PORT_B)
    check('battery off: flag 0', m.get('huawei_battery') == 0)
    check('battery off: no battery metrics', 'huawei_battery_net_watts' not in m)
    check('battery off: home = pv - grid', m.get('huawei_home_consumption_watts') == 5500)

    # 3. sanity caps: max_kwp=2 -> 4000 W exceeds -> 503, then reload fixes it
    write_ini('/tmp/scr_cap.ini', 'max_kwp = 2')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_cap.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:19443'],
                                  stdout=open('/tmp/scr_cap.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)
    status, _ = get('/metrics', 19443)
    check('cap exceeded -> HTTP 503', status == 503)
    write_ini('/tmp/scr_cap.ini', 'max_kwp = 6')
    pid = int(subprocess.run(['pgrep', '-f', 'scraper.py.*19443'], capture_output=True,
                             text=True).stdout.split()[0])
    os.kill(pid, signal.SIGHUP)
    time.sleep(1.5)
    status, body = get('/metrics', 19443)
    m = metrics_dict(body)
    check('SIGHUP with raised cap -> 200 again', status == 200 and m.get('huawei_pv_generation_watts') == 4000)

    # 2b. graceful shutdown of the cap instance leaves a session summary in the log
    os.kill(pid, signal.SIGTERM)
    time.sleep(1)
    cap_log = open('/tmp/scr_cap.log').read()
    check('shutdown: session summary (duration + poll errors)',
          'shutdown: SIGTERM received after ' in cap_log and 'poll errors)' in cap_log
          and 'SIGHUP: applied' in cap_log)

    # 3b. audit log: quiet by default, --log-access logs every request at INFO
    base_log = open('/tmp/scr_reg.log').read()
    check('access log off by default', '"GET /metrics"' not in base_log)
    write_ini('/tmp/scr_audit.ini', 'log_access = true')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_audit.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:19444'],
                                  stdout=open('/tmp/scr_audit.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)
    get('/metrics', 19444)
    get('/nope', 19444)
    time.sleep(0.3)
    audit = open('/tmp/scr_audit.log').read()
    check('log-access: INFO line per request', audit.count('"GET /metrics" 200') >= 1
          and '"GET /nope" 404' in audit, audit.count('"GET') and 'found' or 'none')

    # 3c. bearer auth: disabled by default (earlier checks pass with no header); enforced when set
    write_ini('/tmp/scr_auth.ini', 'auth_token = s3cret')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_auth.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:19446'],
                                  stdout=open('/tmp/scr_auth.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)
    status, _ = get('/metrics', 19446)
    check('bearer auth: no token -> 401', status == 401)
    status, _ = get('/metrics', 19446, headers={'Authorization': 'Bearer wrong'})
    check('bearer auth: wrong token -> 401', status == 401)
    status, body = get('/metrics', 19446, headers={'Authorization': 'Bearer s3cret'})
    check('bearer auth: correct token -> 200', status == 200
          and 'huawei_pv_generation_watts 4000' in body)
    auth_log = open('/tmp/scr_auth.log').read()
    check('401s always audited at WARNING (no --log-access needed)',
          auth_log.count('unauthorized 127.0.0.1 request for /metrics') >= 2
          and '"GET /metrics" 200' not in auth_log)

    # 3d. token from file: enforced, rotates on SIGHUP, error paths fail dry-run
    with open('/tmp/scr_token.txt', 'w') as fh:
        fh.write('first-token\n')
    write_ini('/tmp/scr_tokfile.ini', 'auth_token_file = /tmp/scr_token.txt')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_tokfile.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:19447'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    status, _ = get('/metrics', 19447, headers={'Authorization': 'Bearer first-token'})
    check('token file: works as bearer token', status == 200)
    with open('/tmp/scr_token.txt', 'w') as fh:
        fh.write('second-token\n')
    pid = int(subprocess.run(['pgrep', '-f', 'scraper.py.*19447'], capture_output=True,
                             text=True).stdout.split()[0])
    os.kill(pid, signal.SIGHUP)
    time.sleep(1)
    status, _ = get('/metrics', 19447, headers={'Authorization': 'Bearer first-token'})
    status2, _ = get('/metrics', 19447, headers={'Authorization': 'Bearer second-token'})
    check('token file: SIGHUP rotates the token', status == 401 and status2 == 200)
    r = subprocess.run([sys.executable, P, '--dry-run', '--auth-token', 'a', '--auth-token-file',
                        '/tmp/scr_token.txt'], capture_output=True)
    check('token file: mutually exclusive with --auth-token', r.returncode == 1
          and b'mutually exclusive' in r.stderr)
    r = subprocess.run([sys.executable, P, '--dry-run', '--auth-token-file', '/nonexistent/file'],
                       capture_output=True)
    check('token file: missing file -> clean rc=1', r.returncode == 1 and b'cannot read' in r.stderr)

    # 3e. resource limits: --max-clients 503s the overflow, --client-timeout kicks idle keep-alives
    write_ini('/tmp/scr_lim.ini', 'max_clients = 1\nclient_timeout = 1')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_lim.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:19448'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    parked = socket.create_connection(('127.0.0.1', 19448), timeout=5)
    parked.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\n')  # incomplete: parks a handler thread
    time.sleep(0.5)
    s2 = socket.create_connection(('127.0.0.1', 19448), timeout=5)
    s2.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\n\r\n')
    reply = s2.recv(64)
    check('max-clients: overflow connection -> 503 rate limit', reply.startswith(b'HTTP/1.1 503'),
          reply.split(b'\r\n')[0].decode())
    s2.close()
    parked.close()  # release the only client slot for the idle test
    time.sleep(1)
    idle = socket.create_connection(('127.0.0.1', 19448), timeout=10)
    idle.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\n\r\n')
    buf = b''
    while b'\r\n\r\n' not in buf:
        buf += idle.recv(4096)
    check('client-timeout: served before idle kick', buf.startswith(b'HTTP/1.1 200'))
    clen = int(next(line.split(b': ')[1] for line in buf.split(b'\r\n')
                    if line.lower().startswith(b'content-length: ')))
    while len(buf) - buf.index(b'\r\n\r\n') - 4 < clen:  # drain the body: keep-alive must go idle
        buf += idle.recv(4096)
    idle.settimeout(6)
    eof = idle.recv(64)  # blocks until the server closes the idle keep-alive socket (~1 s)
    check('client-timeout: idle keep-alive closed', eof == b'', repr(eof[:40]))

    # 3f. arg/config sanitization: non-finite floats, host charset, malformed ini, token rules
    def dry(*flags):
        return subprocess.run([sys.executable, P, '--dry-run'] + list(flags), capture_output=True)

    r = dry('--timeout', 'inf')
    check('reject inf timeout', r.returncode == 1 and b'finite number' in r.stderr)
    r = dry('--scale', 'nan')
    check('reject nan scale', r.returncode == 1 and b'finite number' in r.stderr)
    r = dry('--host', 'inva lid')
    check('reject host with spaces', r.returncode == 1 and b'invalid host' in r.stderr)
    with open('/tmp/scr_broken.ini', 'w') as fh:
        fh.write('[scraper]\ninterval = 5\ninterval = 6\n')
    r = dry('--config', '/tmp/scr_broken.ini')
    check('malformed ini is fatal (no silent defaults)', r.returncode == 1
          and b'cannot parse config file' in r.stderr)
    r = dry('--auth-token', 'bad token')
    check('reject token with whitespace', r.returncode == 1 and b'whitespace' in r.stderr)
    r = subprocess.run([sys.executable, P, '--dry-run', '--config', '/tmp/scr_base.ini'],
                       capture_output=True, env=dict(os.environ, SCRAPER_LOG_LEVEL='  info  '))
    check('log level is stripped/normalized', r.returncode == 0 and b'log level: INFO' in r.stderr)
    r = dry('--interval', '0.5', '--timeout', '2')
    check('timeout > interval warns but starts', r.returncode == 0 and b'back-to-back' in r.stderr)
    r = dry('--max-kwp', '-1')
    check('negative max_kwp rejected', r.returncode == 1 and b'0 (checks off) or a positive' in r.stderr)
    r = dry('--max-grid-kw', '-0.5')
    check('negative max_grid_kw rejected', r.returncode == 1 and b'0 (checks off) or a positive' in r.stderr)

    # 3g. hostile startup paths fail clean (no traceback), rc=1
    r = dry('--interval', '1e308')
    check('huge interval accepted but clamped config prints', r.returncode == 0 and b'every 1e+308s' in r.stderr)
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; Metrics(%r)'
                        % (os.path.join(REPO, 'scrape', 'src'), '/nonexistent/metrics.json')],
                       capture_output=True)
    check('missing metrics.json: clean rc=1', r.returncode == 1 and b'metrics spec /nonexistent/metrics.json not found' in r.stderr)
    with open('/tmp/bad_spec.json', 'w') as fh:
        fh.write('{not json')
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; Metrics(%r)'
                        % (os.path.join(REPO, 'scrape', 'src'), '/tmp/bad_spec.json')],
                       capture_output=True)
    check('corrupt metrics.json: clean rc=1', r.returncode == 1 and b'not valid JSON' in r.stderr)

    # 4. sanity-check controls against a scripted inverter (every F5 claim, live)
    regs = {}
    i32_regs(regs, 32064, 1000)   # PV
    i32_regs(regs, 37113, 0)      # grid
    i32_regs(regs, 37001, 0)      # battery
    regs[37004] = 650             # SoC 65.0 %
    for i, w in enumerate((0xCAFE, 1, 7, 4242)):
        regs[65000 + i] = w       # cache diagnostics block
    evil = EvilInverter(15542, regs)
    write_ini('/tmp/scr_evil.ini', 'log_level = DEBUG')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_evil.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15542',
                                   '--listen', '127.0.0.1:19450', '--battery'],
                                  stdout=open('/tmp/scr_evil.log', 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        try:
            status, body = get('/metrics', 19450)
            m = metrics_dict(body)
            if status == 200 and m.get('huawei_pv_generation_watts') == 1000:
                break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.3)
    check('evil inverter: plausible baseline -> 200', status == 200 and m.get('huawei_pv_generation_watts') == 1000)
    check('evil inverter: diag present in fine mode', m.get('huawei_cache_device_up') == 1
          and m.get('huawei_cache_age_seconds') == 7 and m.get('huawei_cache_uptime_seconds') == 4242)
    regs[65000] = 0x1234          # lying magic: a device that is not a modbus-cache
    time.sleep(1.5)
    status, body = get('/metrics', 19450)
    m = metrics_dict(body)
    check('diag magic mismatch: cache metrics stay absent', status == 200
          and not any('huawei_cache' in k for k in m), str([k for k in m if 'cache' in k]))
    regs[65000] = 0xCAFE
    time.sleep(1.5)
    status, body = get('/metrics', 19450)
    m = metrics_dict(body)
    check('diag restored: cache metrics return', status == 200 and m.get('huawei_cache_device_up') == 1)
    i32_regs(regs, 32064, -1000)
    time.sleep(1.5)
    status, _ = get('/metrics', 19450)
    check('negative PV rejected -> 503', status == 503)
    check('negative PV logged with raw-register forensics',
          'PV power is negative' in open('/tmp/scr_evil.log').read())
    i32_regs(regs, 32064, 1000)
    i32_regs(regs, 37113, 7000)   # export 7 kW > 6 kWp cap, no battery discharge yet
    time.sleep(1.5)
    status, _ = get('/metrics', 19450)
    check('export above PV cap -> 503', status == 503)
    i32_regs(regs, 37001, -6000)  # battery discharging 6 kW: 7 kW export is now plausible
    time.sleep(1.5)
    status, body = get('/metrics', 19450)
    m = metrics_dict(body)
    check('battery discharge covers export -> 200', status == 200
          and m.get('huawei_battery_discharge_watts') == 6000 and m.get('huawei_battery_soc_percent') == 65)
    i32_regs(regs, 37001, 0)
    i32_regs(regs, 37113, 2000)   # import 2 kW with only 1 kW PV -> home = -1 kW
    time.sleep(1.5)
    status, _ = get('/metrics', 19450)
    check('home < 0 rejected -> 503', status == 503)
    i32_regs(regs, 37113, -13000) # |grid| above the 12 kW line, import direction
    time.sleep(1.5)
    status, _ = get('/metrics', 19450)
    check('grid cap enforced in both directions -> 503', status == 503)
    i32_regs(regs, 37113, -1500)
    time.sleep(1.5)
    status, body = get('/metrics', 19450)
    m = metrics_dict(body)
    check('sane values accepted again -> 200', status == 200 and m.get('huawei_grid_net_watts') == -1500)

    # 4b. no tracebacks in any scenario log (exceptions must be one-line, handled)
    for name in ('scr_reg', 'scr_cap', 'scr_auth', 'scr_audit', 'scr_evil'):
        log = open('/tmp/%s.log' % name).read()
        check('no tracebacks in %s.log' % name, 'Traceback' not in log)

    # 5. hostile inverter: every garbage mode must fail clean (up=0, one-line error) and recover
    evil.mode = 'garbage'
    time.sleep(1.5)
    status, body = get('/metrics', 19450)
    m = metrics_dict(body)
    check('garbage reply: still HTTP 200 with last values, up=0',
          status == 200 and m.get('huawei_up') == 0 and m.get('huawei_pv_generation_watts') == 1000)
    check('garbage reply: error counter grew', m.get('huawei_modbus_errors_total', 0) >= 1)
    evil.mode = 'short'
    time.sleep(1.5)
    evil.mode = 'lying'
    time.sleep(1.5)
    evil.mode = 'txn'
    time.sleep(1.5)
    evil.mode = 'unit'
    time.sleep(1.5)
    evil.mode = 'bc'
    time.sleep(1.5)
    evil.mode = 'stall'
    time.sleep(3)
    evil.mode = 'garbage_after'
    time.sleep(2)
    status, body = get('/metrics', 19450)
    m = metrics_dict(body)
    check('all hostile modes: still alive, up=0, errors counted',
          status == 200 and m.get('huawei_up') == 0 and m.get('huawei_modbus_errors_total', 0) >= 7)
    evil_log = open('/tmp/scr_evil.log').read()
    for needle in ('transaction id mismatch', 'connection closed by peer', 'timed out'):
        check('hostile mode logged cleanly: %s' % needle, needle in evil_log)
    evil.mode = 'fine'
    time.sleep(2)
    status, body = get('/metrics', 19450)
    m = metrics_dict(body)
    check('hostile inverter gone sane: recovery -> up=1, fresh values',
          status == 200 and m.get('huawei_up') == 1 and m.get('huawei_pv_generation_watts') == 1000)
    check('no tracebacks in scr_evil.log after hostile modes',
          'Traceback' not in open('/tmp/scr_evil.log').read())

    # 5b. client-garbage burst against the same instance (50 frames incl. a 70 KB line)
    for i in range(50):
        try:
            s = socket.create_connection(('127.0.0.1', 19450), timeout=3)
            s.sendall(b'GET ' + b'A' * (70000 if i % 10 == 0 else random.randrange(1, 500))
                      + b' HTTP/1.1\r\n\r\n')
            s.close()
        except OSError:
            pass
    time.sleep(0.5)
    status, body = get('/metrics', 19450)
    check('client garbage burst: still 200, metrics intact',
          status == 200 and 'huawei_pv_generation_watts 1000' in body)
    evil.stop()

    # 4. inverter dies: up=0, values stay (no 503), counter grows; recovery -> up=1
    for p in procs:
        if 'fake_inverter' in ' '.join(p.args):
            p.kill()
    time.sleep(1.5)
    status, body = get('/metrics', PORT_A)
    m = metrics_dict(body)
    check('inverter dead: up=0, still HTTP 200 with last values',
          status == 200 and m.get('huawei_up') == 0 and m.get('huawei_pv_generation_watts') == 4000)
    check('inverter dead: error counter grew', m.get('huawei_modbus_errors_total', 0) >= 1)
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', str(FAKE_PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    status, body = get('/metrics', PORT_A)
    m = metrics_dict(body)
    check('inverter back: up=1', status == 200 and m.get('huawei_up') == 1)

    # 5. dry-run exit codes
    r = subprocess.run([sys.executable, P, '--dry-run', '--config', '/tmp/scr_base.ini'], capture_output=True)
    check('dry-run valid config: rc=0, nothing bound', r.returncode == 0 and b'dry-run' in r.stderr)
    r = subprocess.run([sys.executable, P, '--dry-run', '--interval', '-1'], capture_output=True)
    check('dry-run invalid config: rc=1, clean message', r.returncode == 1 and b'invalid interval' in r.stderr)
finally:
    for p in procs:
        p.kill()

print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
