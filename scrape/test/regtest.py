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
F = os.path.join(REPO, 'inverter', 'src', 'fake_inverter.py')
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
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--battery', '--port', str(FAKE_PORT)],
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

    # 2c. fake extras: control server (runtime overrides) + chaos injection
    def ctl(cmd, port):
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        s.sendall((cmd + '\n').encode())
        r = s.recv(512)
        s.close()
        return r.decode().strip()

    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15570',
                                   '--control-port', '15571'],
                                  stdout=open('/tmp/scr_ctl_fake.log', 'w'), stderr=subprocess.STDOUT))
    write_ini('/tmp/scr_ctl.ini')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_ctl.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15570',
                                   '--listen', '127.0.0.1:19455', '--battery'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    status, m = wait_metrics(19455)
    check('control: baseline static values', m.get('huawei_pv_generation_watts') == 4000)
    ctl('set pv 2500', 15571)
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('control: pv pinned at runtime', m.get('huawei_pv_generation_watts') == 2500,
          str(m.get('huawei_pv_generation_watts')))
    ctl('set soc 30', 15571)
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('control: soc pinned at runtime', m.get('huawei_battery_soc_percent') == 30,
          str(m.get('huawei_battery_soc_percent')))
    ctl('set pv auto', 15571)
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('control: pv override released', m.get('huawei_pv_generation_watts') == 4000)
    check('control: status line', 'pv=4000W' in ctl('status', 15571)
          and 'pinned: soc=30.0' in ctl('status', 15571), ctl('status', 15571))

    # 2d. fake_ctl.py: the CLI tool speaks TCP and unix-socket control servers
    C = os.path.join(REPO, 'inverter', 'src', 'fake_ctl.py')
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'pv', '2700'], capture_output=True, text=True)
    check('fake_ctl: TCP pin via tool', r.returncode == 0 and r.stdout.startswith('ok pv=2700 '), r.stdout.strip())
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('fake_ctl: pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 2700,
          str(m.get('huawei_pv_generation_watts')))
    r = subprocess.run([sys.executable, C, '--control-port', '19999', 'status'], capture_output=True, text=True)
    check('fake_ctl: dead port -> clean rc=1', r.returncode == 1 and 'cannot reach' in r.stderr)

    # 2e. fake audit-logging + malformed-input defense (no tracebacks, no bricking)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'pv', 'nan'], capture_output=True, text=True)
    check('control: non-finite pin rejected', r.stdout.startswith('err value must be finite'), r.stdout.strip())
    time.sleep(1)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('control: register truth intact after rejected pin (pv pin 2700 survives)',
          m.get('huawei_pv_generation_watts') == 2700, str(m.get('huawei_pv_generation_watts')))
    s = socket.create_connection(('127.0.0.1', 15570), timeout=5)
    s.sendall(struct.pack('>HHHB', 4, 0, 0, 1))   # MBAP length 0: malformed
    s.close()
    s = socket.create_connection(('127.0.0.1', 15570), timeout=5)
    s.sendall(struct.pack('>HHHB', 5, 0, 6, 1) + struct.pack('>BHH', 6, 47415, 99))
    s.recv(64)
    s.close()
    s = socket.create_connection(('127.0.0.1', 15570), timeout=5)
    s.sendall(struct.pack('>HHHB', 6, 0, 6, 1) + struct.pack('>BHH', 5, 1, 255))
    s.recv(64)
    s.close()
    time.sleep(0.5)
    ctl_log = open('/tmp/scr_ctl_fake.log').read()
    check('fake audit: write + rejected FC + malformed frame logged one-line',
          'write: register 47415 = 99 (single register, unit 1)' in ctl_log
          and 'rejected FC5 from' in ctl_log
          and 'malformed frame from' in ctl_log)
    subprocess.run([sys.executable, C, '--control-port', '15571', 'pv', '1234'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'reset'], capture_output=True, text=True)
    check('control: reset clears all pins', r.returncode == 0
          and r.stdout.startswith('ok reset (') and 'pinned' not in r.stdout, r.stdout.strip())
    time.sleep(1)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('control: reset returns the register truth', m.get('huawei_pv_generation_watts') == 4000,
          str(m.get('huawei_pv_generation_watts')))
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'reset'], capture_output=True, text=True)
    check('control: reset is idempotent', r.returncode == 0
          and r.stdout.startswith('ok reset (0 pin(s)') and 'pinned' not in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'help'], capture_output=True, text=True)
    check('control: help lists the commands', r.returncode == 0
          and r.stdout.startswith('commands: set <pv|load|batt|soc') and 'chaos' in r.stdout, r.stdout.strip())

    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'settings'], capture_output=True, text=True)
    check('control: show settings lists every setting', r.returncode == 0
          and all(k in r.stdout for k in ('pv=', 'load=', 'batt=', 'soc=', 'cloud=', 'time=', 'chaos=',
                                          'seed=', 'battery=', 'strict=', 'static=', 'max-kwp=',
                                          'battery-kwh=', 'log-level=', 'scenario=')), r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'battery', 'off'], capture_output=True)
    time.sleep(1)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('control: set battery off zeroes battery values live (scraper flag unaffected)',
          m.get('huawei_battery') == 1 and m.get('huawei_battery_net_watts') == 0
          and m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_battery_net_watts')))
    subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'battery', 'on'], capture_output=True)
    check('fake audit: control commands logged at INFO (status too)',
          'control: set pv nan -> err' in ctl_log and 'control: set soc 30 -> ok' in ctl_log
          and 'control: status -> pv=' in ctl_log)

    # 2f. FAKE_CTL environment (short name) drives both tools when the flag is unset
    r = subprocess.run([sys.executable, C, 'set', 'pv', '2200'], capture_output=True, text=True,
                       env={**os.environ, 'FAKE_CTL': '15571'})
    check('fake_ctl: FAKE_CTL env picks the target', r.returncode == 0
          and r.stdout.startswith('ok pv=2200 '), r.stdout.strip() or r.stderr.strip())
    time.sleep(1)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('fake_ctl: env-pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 2200,
          str(m.get('huawei_pv_generation_watts')))
    SIG_SOCK2 = '/tmp/fake-inverter-15577.socket'
    fake_env = subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15577'],
                                stdout=open('/tmp/scr_sig2.log', 'w'), stderr=subprocess.STDOUT,
                                env={**os.environ, 'FAKE_CTL': SIG_SOCK2})
    procs.append(fake_env)
    time.sleep(0.8)
    r = subprocess.run([sys.executable, C, 'status'], capture_output=True, text=True,
                       env={**os.environ, 'FAKE_CTL': SIG_SOCK2})
    check('fake: FAKE_CTL env opens the default-flag-less control server',
          r.returncode == 0 and 'pv=4000W' in r.stdout and os.path.exists(SIG_SOCK2), r.stdout.strip())
    os.kill(fake_env.pid, signal.SIGTERM)
    time.sleep(1)
    check('fake: env-socket unlinked on shutdown', not os.path.exists(SIG_SOCK2)
          and fake_env.poll() == 0)

    # 2g1. battery state machine: SoC integrates the effective battery power
    # with the simulated clock (clock jumps = time-lapse), reserve floor 10 %
    procs.append(subprocess.Popen([sys.executable, F, '--battery', '--time', '12:00',
                                   '--port', '15580', '--control-port', '15583'],
                                  stdout=open('/tmp/scr_batt.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    st = ctl('status', 15583)
    check('battery machine: full battery holds the noon surplus for the grid',
          'batt=0W soc=100.0%' in st, st)
    ctl('set soc 95', 15583); ctl('set pv 3000', 15583); ctl('set load 1000', 15583)
    st = ctl('status', 15583)
    check('battery machine: surplus charges with the grid margin', 'batt=1700W' in st, st)
    ctl('set pv 6000', 15583); ctl('set load 500', 15583)
    st = ctl('status', 15583)
    check('battery machine: charge clamp at max power', 'batt=2500W' in st, st)
    ctl('set pv 0', 15583); ctl('set load 1000', 15583)
    st = ctl('status', 15583)
    check('battery machine: deficit discharges', 'batt=-850W' in st, st)
    ctl('set soc auto', 15583); ctl('set time 18:00', 15583)
    st = ctl('status', 15583)
    check('battery machine: clock jump integrates the SoC (time-lapse)',
          'soc=21.1%' in st and 'batt=-850W' in st, st)
    ctl('set load 6000', 15583); ctl('set time 19:00', 15583)
    st = ctl('status', 15583)
    check('battery machine: discharge stops at the 10 % reserve',
          'soc=10.0%' in st and 'batt=0W' in st, st)
    ctl('set soc 80', 15583)
    st = ctl('set scenario night', 15583)
    check('scenario: preset pins the clock and integrates the battery',
          st.startswith('ok scenario=night') and 'soc=67.3%' in st, st)
    check('scenario: preset releases the value pins', 'pinned' not in st, st)
    st = ctl('set scenario tea', 15583)
    check('scenario: unknown name rejected with the valid list',
          st.startswith('err unknown scenario tea') and 'morning' in st, st)
    ctl('set pv 2200', 15583)
    st = ctl('show scenario', 15583)
    check('scenario: manual pin turns the state custom', st == 'ok scenario=custom', st)

    # 2g2. control 'shutdown' command = graceful stop without a signal
    fake_sd = subprocess.Popen([sys.executable, F, '--static', '--port', '15578', '--control-port', '15579'],
                               stdout=open('/tmp/scr_sd.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_sd)
    time.sleep(0.8)
    r = subprocess.run([sys.executable, C, '--control-port', '15579', 'shutdown'], capture_output=True, text=True)
    time.sleep(1)
    sd_log = open('/tmp/scr_sd.log').read()
    check('control: shutdown stops the fake gracefully', r.returncode == 0
          and 'bye shutdown' in r.stdout and fake_sd.poll() == 0
          and 'shutdown: control received after' in sd_log
          and 'chaos hit(s)' in sd_log, r.stdout.strip() or r.stderr.strip())

    # 2g1. fake_cli.py: the Cisco-style session — silent set confirmations,
    # full show/status replies, [confirm] before shutdown
    K = os.path.join(REPO, 'inverter', 'src', 'fake_cli.py')

    def cli(stdin, port=15571):
        return subprocess.run([sys.executable, K, '--control-port', str(port)],
                              input=stdin, capture_output=True, text=True, timeout=30)

    r = cli('set pv 3000\n')
    check('fake_cli: set prints only the confirmation', r.returncode == 0
          and r.stdout.rstrip() == 'fake-inverter:15571 > ok\nfake-inverter:15571 >', repr(r.stdout))
    check('fake_cli: set reply really carried no status tail',
          'load=' not in r.stdout and 'pinned' not in r.stdout, repr(r.stdout))
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('fake_cli: pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 3000,
          str(m.get('huawei_pv_generation_watts')))
    r = cli('shutdown\nn\n')
    check('fake_cli: shutdown refuses without confirming', r.returncode == 0
          and 'Proceed with shutdown? [confirm]' in r.stdout and '% Aborted.' in r.stdout, repr(r.stdout))
    ctl('status', 15571)
    r = cli('show pv\nstatus\nquit\n')
    lines = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: show prints the bare value, status the full line', r.returncode == 0
          and '3000' in lines and any(l.startswith('pv=3000W') for l in lines), repr(r.stdout))
    r = cli('help soc\n')
    check('fake_cli: help <setting> describes it (shared registry)', r.returncode == 0
          and r.stdout.startswith('fake-inverter:15571 > ok soc - pin the state of charge'), repr(r.stdout))
    r = cli('show settings\nquit\n')
    rows = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: show settings prints one setting per line', r.returncode == 0
          and len(rows) >= 15 and any(r2.startswith('pv ') for r2 in rows)
          and any(r2.startswith('log-level ') for r2 in rows), repr(r.stdout))
    r = cli('set ?\n')
    check('fake_cli: ? lists the options for the position', r.returncode == 0
          and 'scenario' in r.stdout and 'max-kwp' in r.stdout
          and 'ok' not in r.stdout, repr(r.stdout))
    fake_k = subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15586',
                               '--control-port', '15587'],
                              stdout=open('/tmp/scr_cli.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_k)
    time.sleep(0.8)
    r = cli('shutdown\n\n', 15587)
    time.sleep(1)
    check('fake_cli: RETURN at [confirm] stops the fake', r.returncode == 0
          and 'bye shutdown' in r.stdout and fake_k.poll() == 0, repr(r.stdout))

    # 2g1b. unset command + scenario custom (server side, shared registry)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'unset', 'pv'], capture_output=True, text=True)
    check('control: unset releases the pin back to the simulation', r.returncode == 0
          and r.stdout.startswith('ok pv=auto '), r.stdout.strip())
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('control: unset really releases (metrics back to the static base)',
          m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_pv_generation_watts')))
    subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'pv', '2700'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'scenario', 'custom'],
                       capture_output=True, text=True)
    check('control: scenario custom releases pins + clock', r.returncode == 0
          and r.stdout.startswith('ok scenario=custom ') and 'pinned' not in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'unset', 'seed'], capture_output=True, text=True)
    check('control: unset seed restores the random RNG', r.returncode == 0
          and r.stdout.startswith('ok seed=random '), r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'unset', 'bogus'], capture_output=True, text=True)
    check('control: unset of an unknown setting is rejected', r.returncode == 0
          and r.stdout.startswith('err unknown setting bogus'), r.stdout.strip())

    # 2e. signals, mirroring the scraper/cache family: SIGHUP = FAKE_* env reload,
    # SIGUSR1 = scenario reset (pins + write overlay), SIGTERM = summary + exit 0
    SIG_SOCK = '/tmp/scr_sig_ctl.sock'
    fake_ctl = subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15574',
                                 '--control-port', SIG_SOCK],
                                stdout=open('/tmp/scr_sig.log', 'w'), stderr=subprocess.STDOUT,
                                env={**os.environ, 'FAKE_CHAOS': '0.9', 'FAKE_LOG_LEVEL': 'DEBUG'})
    procs.append(fake_ctl)
    time.sleep(0.8)
    check('signals: chaos off by flag despite FAKE_CHAOS env',
          'chaos=0.00' in subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'status'], capture_output=True, text=True).stdout)
    s = socket.create_connection(('127.0.0.1', 15574), timeout=5)
    s.sendall(struct.pack('>HHHB', 5, 0, 6, 1) + struct.pack('>BHH', 6, 47415, 99))
    s.recv(64)
    s.close()
    subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'set', 'pv', '2500'], capture_output=True)
    os.kill(fake_ctl.pid, signal.SIGHUP)
    time.sleep(0.8)
    sig_status = subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'status'], capture_output=True, text=True).stdout
    check('signals: SIGHUP re-applies the FAKE_* env layer',
          'chaos=0.90' in sig_status and 'pinned: pv=2500' in sig_status, sig_status)
    os.kill(fake_ctl.pid, signal.SIGUSR1)
    time.sleep(0.8)
    sig_status = subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'status'], capture_output=True, text=True).stdout
    check('signals: SIGUSR1 resets pins + write overlay', 'pinned' not in sig_status
          and '1 overlay register(s) cleared' in open('/tmp/scr_sig.log').read(), sig_status)
    os.kill(fake_ctl.pid, signal.SIGTERM)
    time.sleep(1)
    sig_log = open('/tmp/scr_sig.log').read()
    check('signals: SIGTERM -> session summary + exit',
          fake_ctl.poll() == 0 and 'shutdown: SIGTERM received after' in sig_log
          and 'chaos hit(s)' in sig_log)
    check('signals: unix control socket unlinked on shutdown', not os.path.exists(SIG_SOCK))

    # 2e. fake dry-run: validate config, print effective settings, family exit codes
    r = subprocess.run([sys.executable, F, '--dry-run', '--static', '--battery'], capture_output=True)
    check('fake dry-run: valid rc=0', r.returncode == 0
          and b'nothing was bound or connected' in r.stderr
          and b'peak PV 4500W' in r.stderr)
    r = subprocess.run([sys.executable, F, '--dry-run', '--unit', '300'], capture_output=True)
    check('fake dry-run: invalid rc=1, clean message', r.returncode == 1
          and b'--unit out of range (1-247): 300' in r.stderr
          and b'Traceback' not in r.stderr)
    r = subprocess.run([sys.executable, F, '--dry-run', '--time', '25:00'], capture_output=True)
    check('fake dry-run: bad time rc=1', r.returncode == 1 and b'--time invalid' in r.stderr)


    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15572',
                                   '--control-port', '15573', '--chaos', '0.4', '--seed', '42'],
                                  stdout=open('/tmp/scr_chaos_fake.log', 'w'), stderr=subprocess.STDOUT))
    write_ini('/tmp/scr_chaos.ini')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_chaos.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15572',
                                   '--listen', '127.0.0.1:19456'],
                                  stdout=open('/tmp/scr_chaos.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(6)
    status, body = get('/metrics', 19456)
    m = metrics_dict(body)
    check('chaos: exporter stays up, errors counted', status == 200
          and m.get('huawei_modbus_errors_total', 0) > 0, str(m.get('huawei_modbus_errors_total')))
    ctl('set chaos off', 15573)
    time.sleep(2)
    status, body = get('/metrics', 19456)
    m = metrics_dict(body)
    check('chaos off: recovery to up=1', status == 200 and m.get('huawei_up') == 1)
    check('chaos: zero tracebacks in fake + scraper logs',
          'Traceback' not in open('/tmp/scr_chaos.log').read())
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
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--battery', '--port', str(FAKE_PORT)],
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
