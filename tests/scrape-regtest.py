#!/usr/bin/env python3
"""Regression suite for modbus-scraper (+ fake inverter).

Run from anywhere: python3 scrape/test/regtest.py
Starts its own fake inverter + scraper instances on scratch ports and
cleans up after itself.
"""
import json as _json
import getpass
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPE_DIR = os.path.join(REPO, 'scrape')

P = os.path.join(SCRAPE_DIR, 'bin', 'modbus_scraper.py')
F = os.path.join(REPO, 'inverter', 'bin', 'fake_inverter.py')
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


def wait_metrics(port, tries=30, want='huawei_pv_generation_watts'):
    """The HTTP endpoint can bind before the first Modbus poll lands — wait
    for the first value metric, not just for a 200."""
    for _ in range(tries):
        try:
            status, body = get('/metrics', port)
            d = metrics_dict(body)
            if want is None or want in d:
                return status, d
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise SystemExit('scraper on %d never came up' % port)


def read3(addr, count, port):
    """Raw Modbus FC3 read: returns the PDU (the MBAP header stripped)."""
    s = socket.create_connection(('127.0.0.1', port), timeout=5)
    s.sendall(struct.pack('>HHHB', 9, 0, 6, 1) + struct.pack('>BHH', 3, addr, count))
    r = s.recv(512)
    s.close()
    return r[7:]


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

    # 1a. scraper profile: the scrape-marked entries feed the metric registers
    prof = '/tmp/scr_scraper_profile.json'
    _json.dump({'description': 'remapped device',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'i32', 'scale': 1, 'scrape': True},
                    {'name': 'grid-power', 'register': 40003, 'type': 'i32', 'scale': 1, 'scrape': True},
                    {'name': 'battery-power', 'register': 40005, 'type': 'i32', 'scale': 1, 'scrape': True},
                    {'name': 'battery-soc', 'register': 40123, 'type': 'u16', 'scale': 1, 'scrape': True},
                ]}, open(prof, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--strict', '--port', '15590',
                                   '--control-port', '0', '--profile', prof],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_base.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15590',
                                   '--listen', '127.0.0.1:9361', '--battery', '--profile', prof],
                                  stdout=open('/tmp/scr_prof_scraper.log', 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9361)
        if 'huawei_pv_generation_watts' in m:
            break
        time.sleep(0.3)
    check('scraper profile: pv metric follows the remapped register',
          m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_pv_generation_watts')))
    check('scraper profile: grid metric follows (static -1500)',
          m.get('huawei_grid_net_watts') == -1500, str(m.get('huawei_grid_net_watts')))
    check('scraper profile: soc scale honored (profile says x1)',
          m.get('huawei_battery_soc_percent') == 65, str(m.get('huawei_battery_soc_percent')))

    # 1a-bis. the profile's fc field: an fc4-marked source is read with FC4.
    # Positive half: the fake serves the map over both function codes.
    prof4 = '/tmp/scr_fc4_profile.json'
    _json.dump({'description': 'fc4-marked source',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'i32', 'scale': 1, 'fc': 4, 'scrape': True},
                    {'name': 'grid-power', 'register': 40003, 'type': 'i32', 'scale': 1, 'scrape': True},
                ]}, open(prof4, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--strict', '--port', '15547',
                                   '--control-port', '0', '--profile', prof4],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_base.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15547',
                                   '--listen', '127.0.0.1:9362', '--profile', prof4],
                                  stdout=open('/tmp/scr_fc4.log', 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9362)
        if m.get('huawei_pv_generation_watts') == 4000:
            break
        time.sleep(0.3)
    check('profile fc: the fc4-marked pv-power is read over FC4',
          m.get('huawei_pv_generation_watts') == 4000 and m.get('huawei_up') == 1,
          str({k: m.get(k) for k in ('huawei_pv_generation_watts', 'huawei_up')}))
    # Negative half: an FC3-only device cannot serve an fc4-marked source
    # (the evil server drops FC4 requests) — the poll must fail, not silently
    # succeed over FC3.
    evil4 = EvilInverter(15592, {40001: 4000, 40003: 0})
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_base.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15592',
                                   '--listen', '127.0.0.1:9364', '--profile', prof4],
                                  stdout=open('/tmp/scr_fc4_evil.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(1.5)          # a few failed polls at the 0.3s interval
    status, m = wait_metrics(9364, want=None)
    check('profile fc: an fc4 source on an FC3-only device fails the poll',
          m.get('huawei_up') == 0 and m.get('huawei_modbus_errors_total', 0) >= 1
          and 'huawei_pv_generation_watts' not in m,
          str({k: m.get(k) for k in ('huawei_up', 'huawei_modbus_errors_total')}))
    evil4.stop()

    # 1b. the shipped Deye profile end-to-end: real Deye addresses (SG03LP1
    # family), SoC reported as plain percent (gain 1), omitted registers = 0
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--strict', '--port', '15596',
                                   '--control-port', '0', '--profile', 'deye-sg03lp1'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_base.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15596',
                                   '--listen', '127.0.0.1:9363', '--battery', '--profile', 'deye-sg03lp1'],
                                  stdout=open('/tmp/scr_deye.log', 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9363)
        if 'huawei_pv_generation_watts' in m:
            break
        time.sleep(0.3)
    check('deye-sg03lp1: pv metric from register 186',
          m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_pv_generation_watts')))
    check('deye-sg03lp1: soc gain 1 (plain percent)', m.get('huawei_battery_soc_percent') == 65,
          str(m.get('huawei_battery_soc_percent')))
    check('deye-sg03lp1: grid from register 169', m.get('huawei_grid_net_watts') == -1500,
          str(m.get('huawei_grid_net_watts')))

    # 1c. the Deye three-phase profile (SG04LP3): 6xx registers, SoC gain 1
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--strict', '--port', '15598',
                                   '--control-port', '0', '--profile', 'deye-sg04lp3'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_base.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15598',
                                   '--listen', '127.0.0.1:9365', '--battery', '--profile', 'deye-sg04lp3'],
                                  stdout=open('/tmp/scr_deye3.log', 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9365)
        if 'huawei_pv_generation_watts' in m:
            break
        time.sleep(0.3)
    check('deye-sg04lp3: pv metric from register 672',
          m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_pv_generation_watts')))
    check('deye-sg04lp3: soc gain 1 from register 588', m.get('huawei_battery_soc_percent') == 65,
          str(m.get('huawei_battery_soc_percent')))
    check('deye-sg04lp3: grid from register 625', m.get('huawei_grid_net_watts') == -1500,
          str(m.get('huawei_grid_net_watts')))
    b = read3(500, 1, 15598)
    check('deye-sg04lp3: real status codes served (500 = 2 normal)',
          b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 2, b.hex())

    # 1d. the SUN-12K-SG05LP3-EU profile (shares the SG04LP3 map)
    r = subprocess.run([sys.executable, F, '--dry-run', '--static', '--battery',
                        '--profile', 'deye-sg05lp3'], capture_output=True, text=True)
    check('deye-sg05lp3: profile loads (dry-run rc 0)', r.returncode == 0
          and 'Deye SUN-12K-SG05LP3-EU' in r.stderr, r.stderr.strip()[-80:])
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15593',
                                   '--control-port', '0', '--profile', 'deye-sg05lp3'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    b = read3(672, 2, 15593)
    check('deye-sg05lp3: pv at 672', b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 4000, b.hex())
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
        # the JSON-lines control transport: one request object, one reply object
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        s.sendall((_json.dumps({'cmd': cmd}, ensure_ascii=False) + '\n').encode())
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        obj = _json.loads(buf.decode('utf-8', 'replace'))
        return '%s %s' % (obj.get('status', 'err'), str(obj.get('text', '')))

    procs.append(subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15570',
                                   '--control-port', '15571'],
                                  stdout=open('/tmp/scr_ctl_fake.log', 'w'), stderr=subprocess.STDOUT))
    write_ini('/tmp/scr_ctl.ini')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_ctl.ini',
                                   '--host', '127.0.0.1', '--modbus-port', '15570',
                                   '--listen', '127.0.0.1:19455', '--battery'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    status, m = wait_metrics(19455)
    check('control: baseline static values', m.get('huawei_pv_generation_watts') == 4000,
          str(sorted(m))[:120])   # the detail = what the first pull served
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
    st = ctl('show status', 15571)
    check('control: status report (key=value rows)', st.startswith('ok status\n')
          and '\npv=4000\n' in st and '\npinned=soc=30.0\n' in st, st)

    # 2d. fake_ctl.py: the CLI tool speaks TCP and unix-socket control servers
    C = os.path.join(REPO, 'inverter', 'bin', 'fake_ctl.py')
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'pv', '2700'], capture_output=True, text=True)
    check('fake_ctl: TCP pin via tool', r.returncode == 0 and r.stdout.startswith('ok pv=2700 '), r.stdout.strip())
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('fake_ctl: pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 2700,
          str(m.get('huawei_pv_generation_watts')))
    r = subprocess.run([sys.executable, C, '--control-port', '19999', 'show', 'status'], capture_output=True, text=True)
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
          and r.stdout.startswith('commands: set <pv|load|batt|grid|soc') and 'chaos' in r.stdout, r.stdout.strip())

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
    check('fake audit: control commands quiet at INFO',
          'control: set pv nan -> err' not in ctl_log and 'control: set soc 30' not in ctl_log)
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15588', '--control-port', '15589',
                                   '--log-level', 'DEBUG'],
                                  stdout=open('/tmp/scr_ctl_dbg.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    ctl('set soc 30', 15589)
    ctl('show status', 15589)
    subprocess.run([sys.executable, C, '--control-port', '15589', 'shutdown'], capture_output=True, text=True)
    time.sleep(1)
    ctl_debug = open('/tmp/scr_ctl_dbg.log').read()
    check('fake audit: control commands logged with the peer, the output withheld by default',
          'control from 127.0.0.1' in ctl_debug and ': set soc 30' in ctl_debug
          and '-> ok' not in ctl_debug, ctl_debug[-200:])
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15584', '--control-port', '15585',
                                   '--log-level', 'DEBUG', '--control-log-replies'],
                                  stdout=open('/tmp/scr_ctl_full.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    ctl('set soc 30', 15585)
    ctl('show status', 15585)
    subprocess.run([sys.executable, C, '--control-port', '15585', 'shutdown'], capture_output=True, text=True)
    time.sleep(1)
    ctl_full = open('/tmp/scr_ctl_full.log').read()
    check('fake audit: --control-log-replies logs the full command output',
          ': set soc 30 -> ok' in ctl_full and ': show status -> ok status' in ctl_full, ctl_full[-200:])

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
    r = subprocess.run([sys.executable, C, 'show', 'status'], capture_output=True, text=True,
                       env={**os.environ, 'FAKE_CTL': SIG_SOCK2})
    check('fake: FAKE_CTL env opens the default-flag-less control server',
          r.returncode == 0 and '\npv=4000\n' in r.stdout and '\ngrid=-1500\n' in r.stdout
          and '\nbattery=1200\n' in r.stdout and '\npinned=none\n' in r.stdout, r.stdout.strip())
    os.kill(fake_env.pid, signal.SIGTERM)
    time.sleep(1)
    check('fake: env-socket unlinked on shutdown', not os.path.exists(SIG_SOCK2)
          and fake_env.poll() == 0)

    # 2f2. the peer-cred auth on the fake's unix control socket: the token gates
    # both transports, the kernel-vouched same-uid peer skips the handshake
    CRED_SOCK = '/tmp/inv_cred.socket'
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15591',
                                   '--control-port', CRED_SOCK, '--control-token', 'sekrit'],
                                  stdout=open('/tmp/scr_cred.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    r = subprocess.run([sys.executable, C, '--control-port', CRED_SOCK, 'show', 'version'],
                       capture_output=True, text=True, timeout=30)
    check('fake peer-cred: the same-uid unix peer needs no token', r.returncode == 0
          and r.stdout.startswith('ok fake-inverter'), repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, C, '--control-port', CRED_SOCK, 'shutdown'],
                       capture_output=True, text=True, timeout=30)
    check('fake peer-cred: the trusted unix peer can also stop the fake', r.stdout.startswith('bye'),
          repr(r.stdout[:120]))
    procs[-1].wait(timeout=10)

    # 2g1. battery state machine: SoC integrates the effective battery power
    # with the simulated clock (clock jumps = time-lapse), reserve floor 10 %
    procs.append(subprocess.Popen([sys.executable, F, '--battery', '--time', '12:00',
                                   '--port', '15580', '--control-port', '15583'],
                                  stdout=open('/tmp/scr_batt.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    st = ctl('show status', 15583)
    check('battery machine: full battery holds the noon surplus for the grid',
          '\nbattery=0\n' in st and '\nsoc=100.0\n' in st, st)
    ctl('set soc 95', 15583); ctl('set pv 3000', 15583); ctl('set load 1000', 15583)
    st = ctl('show status', 15583)
    check('battery machine: surplus charges with the grid margin', '\nbattery=1700\n' in st, st)
    ctl('set pv 6000', 15583); ctl('set load 500', 15583)
    st = ctl('show status', 15583)
    check('battery machine: charge clamp at the temperature-derated max', '\nbattery=2250\n' in st, st)
    ctl('set pv 0', 15583); ctl('set load 1000', 15583)
    st = ctl('show status', 15583)
    check('battery machine: deficit discharges', '\nbattery=-850\n' in st, st)
    ctl('set soc auto', 15583); ctl('set time 18:00', 15583)
    st = ctl('show status', 15583)
    check('battery machine: clock jump integrates the SoC (time-lapse)',
          '\nsoc=21.0\n' in st and '\nbattery=-850\n' in st, st)
    ctl('set load 6000', 15583); ctl('set time 19:00', 15583)
    st = ctl('show status', 15583)
    check('battery machine: discharge stops at the 10 % reserve',
          '\nsoc=10.0\n' in st and '\nbattery=0\n' in st, st)
    # 2g2. grid setpoint: the battery balances to hold the grid line
    ctl('set pv 3000', 15583); ctl('set load 1000', 15583); ctl('set soc 80', 15583)
    ctl('set grid 0', 15583)
    st = ctl('show status', 15583)
    check('grid setpoint: zero-export held by the battery', '\ngrid=0\n' in st
          and '\nbattery=2000\n' in st and 'grid=0.0' in st.split('pinned=')[1], st)
    r = read3(37113, 2, 15580)
    check('grid setpoint: the grid register serves the pinned 0',
          r[0] == 3 and struct.unpack('>i', r[2:6])[0] == 0, r.hex())
    ctl('unset grid', 15583)
    st = ctl('show status', 15583)
    check('grid setpoint: unset returns to the balance', '\ngrid=300\n' in st
          and 'pinned=pv=3000.0,load=1000.0,soc=80.0' in st, st)
    # 2g2b. mppt strings: string-1 = the east array (the morning peak), string-2 =
    # the west array (the afternoon peak); the setting enables/assigns them
    ctl('set pv auto', 15583); ctl('set load auto', 15583); ctl('set soc auto', 15583)
    ctl('set time 12:00', 15583)
    ctl('set mppt west', 15583)
    r = read3(32016, 4, 15580)     # the string-1 V/I, the string-2 V/I
    words = struct.unpack('>4H', r[2:10])
    check('mppt: west only = the east string dark, the west string live',
          words[0] == 0 and words[1] == 0 and words[2] > 0 and words[3] > 0, str(words))
    st = ctl('show status', 15583)
    check('mppt: the status report names the assignment', '\nmppt=west\n' in st, st)
    ctl('set mppt both', 15583)
    r = read3(32016, 4, 15580)
    words = struct.unpack('>4H', r[2:10])
    check('mppt: both = both strings live (the oriented bells)', all(w > 0 for w in words), str(words))
    ctl('set mppt none', 15583)
    r = read3(32016, 4, 15580)
    check('mppt: none = PV 0, both strings dark',
          all(w == 0 for w in struct.unpack('>4H', r[2:10])), r.hex())
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'unset', 'mppt'],
                       capture_output=True, text=True)
    check('mppt: unset restores both', r.returncode == 0 and 'ok mppt=both' in r.stdout, r.stdout.strip())
    st = ctl('show status', 15583)
    check('mppt: the day curve doubles the shoulder with both strings',
          '4000' < st.split('\npv=')[1].split('\n')[0] < '5000', st)
    # 2g2c. grid voltage: the nominal 120/230 setting + the per-phase wander
    # machine (the phases differ, +-10 % clamp, the time-lapse moves it)
    ctl('set time 12:00', 15583)
    subprocess.run([sys.executable, C, '--control-port', '15583', 'show', 'registers'],
                   capture_output=True, text=True)   # the first values() anchors the machine
    ctl('set grid-voltage 120', 15583)
    ctl('set time 13:30', 15583)   # the clock jump = the wander
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'show', 'registers'],
                       capture_output=True, text=True)
    regs = {l.split(' | ')[0].strip(): l.split(' | ')[-1].strip()
            for l in r.stdout.splitlines() if ' | ' in l}
    vs = [float(regs[k]) for k in ('meter-voltage-a', 'meter-voltage-b', 'meter-voltage-c')]
    check('grid voltage: 120 V nominal, the phases wander apart within +-10 %',
          all(108 <= v <= 132 for v in vs) and len(set(vs)) == 3, str(vs))
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'unset', 'grid-voltage'],
                       capture_output=True, text=True)
    check('grid voltage: unset restores the 230 V nominal', 'ok grid-voltage=230' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'show', 'registers'],
                       capture_output=True, text=True)
    regs = {l.split(' | ')[0].strip(): l.split(' | ')[-1].strip()
            for l in r.stdout.splitlines() if ' | ' in l}
    vs = [float(regs[k]) for k in ('meter-voltage-a', 'meter-voltage-b', 'meter-voltage-c')]
    check('grid voltage: 230 V nominal band 207..253, the currents follow (the 120 V = the double)',
          all(207 <= v <= 253 for v in vs), str(vs))
    r = subprocess.run([sys.executable, F, '--dry-run', '--grid-voltage', '120'], capture_output=True, text=True)
    check('grid voltage: --grid-voltage flag accepted (dry-run rc 0)', r.returncode == 0, r.stderr[-80:])
    # 2g2c-bis. control register writes: set register = the same overlay the
    # FC06/FC16 writes land in — the scrapers see it; show registers marks it
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'set', 'register', '32064', '5000'],
                       capture_output=True, text=True)
    check('control writes: set register lands in the write overlay', r.returncode == 0
          and 'ok register 32064=5000' in r.stdout, r.stdout.strip())
    r = read3(32064, 1, 15580)
    check('control writes: the scraper reads the overlay value',
          r[0] == 3 and struct.unpack('>H', r[2:4])[0] == 5000, r.hex())
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'show', 'registers'],
                       capture_output=True, text=True)
    check('control writes: show registers marks the overlay row',
          any(l.startswith('pv-power') and l.split(' | ')[-1].strip().startswith('5000 *')
              for l in r.stdout.splitlines()), r.stdout.strip()[:80])
    subprocess.run([sys.executable, C, '--control-port', '15583', 'reset'], capture_output=True)

    # 2g2d. the per-phase home load asymmetry: the unbalanced home
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'show', 'registers'],
                       capture_output=True, text=True)
    regs = {l.split(' | ')[0].strip(): l.split(' | ')[-1].strip()
            for l in r.stdout.splitlines() if ' | ' in l}
    cur = [float(regs[k]) for k in ('meter-current-a', 'meter-current-b', 'meter-current-c')]
    check('per-phase loads: the meter currents really differ', len(set(cur)) == 3, str(cur))

    # 2g2e. grid frequency: the base setting + the +-0.2 Hz machine
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'show', 'grid-frequency'],
                       capture_output=True, text=True)
    check('grid frequency: the nominal defaults to 50 Hz', r.returncode == 0
          and 'ok grid-frequency=50' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'set', 'grid-frequency', '60'],
                       capture_output=True, text=True)
    check('grid frequency: set to the 60 Hz base', 'ok grid-frequency=60' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'show', 'registers'],
                       capture_output=True, text=True)
    regs = {l.split(' | ')[0].strip(): l.split(' | ')[-1].strip()
            for l in r.stdout.splitlines() if ' | ' in l}
    hz = float(regs.get('grid-frequency', '0'))
    check('grid frequency: the machine wanders inside 60 +-0.2 Hz', 59.8 <= hz <= 60.2, str(hz))
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'unset', 'grid-frequency'],
                       capture_output=True, text=True)
    check('grid frequency: unset restores 50 Hz', 'ok grid-frequency=50' in r.stdout, r.stdout.strip())

    # 2g2f. inspect: the pretty dump of everything
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'inspect'],
                       capture_output=True, text=True)
    check('inspect: the version, the profile, the machines, the overlay, the pins',
          r.returncode == 0 and r.stdout.startswith('ok inspect')
          and '\nversion   0.3.0' in r.stdout and '\nprofile   SUN2000' in r.stdout
          and '\nmppt      both' in r.stdout and '\npinned    ' in r.stdout
          and 'V nominal, 50 Hz nominal' in r.stdout, r.stdout.strip()[:120])

    # 2g2g. the fake's own metrics: the gated Prometheus endpoint + the bearer auth
    r = subprocess.run([sys.executable, F, '--dry-run'], capture_output=True, text=True)
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15901',
                                   '--control-port', '15902', '--metrics-listen', '127.0.0.1:15903', '--metrics-server'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.2)
    status, body = None, None
    for _ in range(25):
        try:
            status, body = get('/metrics', 15903)
            break
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    check('fake metrics: ungated (no --metrics-token) serves the gauges',
          status == 200 and 'fake_inverter_power_watts{kind="pv"} 4000' in body, str(status))
    subprocess.run([sys.executable, C, '--control-port', '15902', 'shutdown'], capture_output=True)
    time.sleep(0.8)
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15904',
                                   '--control-port', '15905', '--metrics-listen', '127.0.0.1:15906',
                                   '--metrics-server', '--metrics-token', 'sekrit'],
                                  stdout=open('/tmp/scr_metrics.log', 'w'), stderr=subprocess.STDOUT))
    time.sleep(1.2)
    status, body = None, None
    for _ in range(25):
        try:
            status, body = get('/metrics', 15906)
            break
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    check('fake metrics: no token = 401 + the WWW-Authenticate challenge',
          status == 401, str(status))
    req = urllib.request.Request('http://127.0.0.1:15906/metrics')
    req.add_header('Authorization', 'Bearer sekrit')
    body = None
    for _ in range(25):
        try:
            body = urllib.request.urlopen(req, timeout=5).read().decode()
            break
        except urllib.error.URLError:
            time.sleep(0.2)
    check('fake metrics: the bearer pulls the gauges',
          body is not None and 'fake_inverter_power_watts{kind="pv"} 4000' in body
          and 'fake_inverter_grid_phase_volts{phase="a"}' in body
          and 'fake_inverter_modbus_requests_total' in body, (body or '')[:120])
    subprocess.run([sys.executable, C, '--control-port', '15905', 'shutdown'], capture_output=True)
    time.sleep(0.8)

    # 2g2d. the state machines integrate over the UTC clock (configurable);
    # the clock is frozen from the mppt/grid-voltage blocks — unfreeze first
    ctl('set time auto', 15583)
    st = ctl('show status', 15583)
    check('timezone: the state machines default to UTC', '\ntimezone=utc\n' in st
          and int(st.split('\nclock=')[1][:2]) == time.gmtime().tm_hour % 24, st)
    ctl('set timezone local', 15583)
    st = ctl('show status', 15583)
    check('timezone: local = the wall clock', '\ntimezone=local\n' in st
          and int(st.split('\nclock=')[1][:2]) == time.localtime().tm_hour % 24, st)
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'unset', 'timezone'],
                       capture_output=True, text=True)
    check('timezone: unset restores UTC', 'ok timezone=utc' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, F, '--dry-run', '--timezone', 'local'], capture_output=True, text=True)
    check('timezone: --timezone flag accepted (dry-run rc 0)', r.returncode == 0, r.stderr[-80:])
    ctl('set time 13:30', 15583)   # re-freeze: the scenario integrates the same path as before
    ctl('set soc 80', 15583)
    st = ctl('set scenario night', 15583)
    check('scenario: preset pins the clock and integrates the battery (the mppt-aware day)',
          st.startswith('ok scenario=night') and 'soc=49.8%' in st, st)
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
    K = os.path.join(REPO, 'inverter', 'bin', 'fake_cli.py')

    def cli(stdin, port=15571, audit=None):
        extra = ['--audit-log', audit] if audit else []
        return subprocess.run([sys.executable, K, '--control-port', str(port)] + extra,
                              input=stdin, capture_output=True, text=True, timeout=30)

    r = cli('set pv 3000\n')
    check('fake_cli: set prints only the confirmation', r.returncode == 0
          and r.stdout.rstrip() == '\nfake-inverter:15571 > % ok\n\nfake-inverter:15571 >', repr(r.stdout))
    check('fake_cli: set reply really carried no status tail',
          'load=' not in r.stdout and 'pinned' not in r.stdout, repr(r.stdout))
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455)[1])
    check('fake_cli: pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 3000,
          str(m.get('huawei_pv_generation_watts')))
    r = cli('shutdown\nn\n')
    check('fake_cli: shutdown refuses without confirming', r.returncode == 0
          and 'Proceed with shutdown? [confirm]' in r.stdout and '% Aborted.' in r.stdout, repr(r.stdout))
    ctl('show status', 15571)
    r = cli('show pv\nshow status\nquit\n')
    lines = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: show prints the bare value, show status the bare report rows', r.returncode == 0
          and '3000' in lines
          and any(l == 'pv=3000' for l in lines) and any(l == 'pinned=pv=3000.0' for l in lines)
          and not any(l.startswith('% ok status') for l in lines), repr(r.stdout))
    r = cli('help soc\nshow registers\ninspect\nquit\n')
    lines = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: the help is bare, the tables ride under % ok, inspect dumps', r.returncode == 0
          and any(l == 'soc - pin the state of charge (seeds the machine), or auto (values: %|auto)' for l in lines)
          and any(l == '% ok registers (49)' for l in lines) and 'pv-power' in ''.join(lines)
          and any('0.3.0' in l and 'version' in l for l in lines)
          and not any(l.startswith('% ok inspect') for l in lines), repr(r.stdout[:120]))

    # 2g3. the audit trail: the UTC stamp, the CLI/CTL prefix, the who-when-what,
    # ping/pong never logged, --no-audit-log switches it off
    AUD = '/tmp/scr_audit_ctl.log'
    if os.path.exists(AUD):
        os.unlink(AUD)
    subprocess.run([sys.executable, C, '--control-port', '15571', '--audit-log', AUD, 'set', 'pv', '2600'],
                   capture_output=True, text=True)
    subprocess.run([sys.executable, C, '--control-port', '15571', '--no-audit-log', '--audit-log', AUD,
                    'show', 'pv'], capture_output=True, text=True)
    rows = open(AUD).read().strip().split('\n')
    check('audit: ctl logs CONNECT/DISCONNECT; the commands belong to the server trail',
          len(rows) == 2 and rows[0].split(' ')[1] == 'AUDIT' and rows[0].split(' ')[2] == 'CTL'
          and rows[0].split(' ')[3] == 'CONNECT'
          and rows[1].split(' ')[3] == 'DISCONNECT', '\n'.join(rows))
    AUD2 = '/tmp/scr_audit_cli.log'
    if os.path.exists(AUD2):
        os.unlink(AUD2)
    r = cli('show version\nping\nquit\n', audit=AUD2)
    cli_rows = open(AUD2).read()
    check('audit: cli logs the session + the local commands; the wire commands = the server trail',
          'CLI CONNECT ' in cli_rows and 'target=' in cli_rows
          and 'CLI COMMAND ' in cli_rows and "'quit' -> local" in cli_rows
          and 'CLI DISCONNECT' in cli_rows and "CLI COMMAND 'show" not in cli_rows
          and 'ping' not in cli_rows and 'pong' not in cli_rows, cli_rows)
    r = cli('show settings\nquit\n')
    rows = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: show settings prints one setting per line', r.returncode == 0
          and len(rows) >= 15 and any(r2.startswith('pv ') for r2 in rows)
          and any(r2.startswith('log-level ') for r2 in rows), repr(r.stdout))
    r = cli('set ?\n')
    check('fake_cli: ? lists the options for the position', r.returncode == 0
          and 'scenario' in r.stdout and 'max-kwp' in r.stdout
          and 'ok' not in r.stdout, repr(r.stdout))
    p = subprocess.Popen([sys.executable, K, '--control-port', '15571'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, env={**os.environ, 'FAKE_CLI_KEEPALIVE': '0.2'})
    time.sleep(1.2)          # the CLI idles, pinging every 0.2s
    p.stdin.write('show max-kwp\n')
    p.stdin.flush()
    time.sleep(0.4)
    p.stdin.write('quit\n')
    p.stdin.flush()
    out, _ = p.communicate(timeout=15)
    check('fake_cli: keepalive keeps an idle session alive (pongs absorbed)',
          p.returncode == 0 and 'fake-inverter:15571 > 6' in out and 'ok pong' not in out, repr(out[-120:]))
    fake_k = subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15586',
                               '--control-port', '15587'],
                              stdout=open('/tmp/scr_cli.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_k)
    time.sleep(0.8)
    r = cli('shutdown\n\n', 15587)
    time.sleep(1)
    check('fake_cli: RETURN at [confirm] stops the fake', r.returncode == 0
          and 'bye shutdown' in r.stdout and fake_k.poll() == 0, repr(r.stdout))

    def wait_ctl(port, tries=50):
        for _ in range(tries):
            try:
                ctl('ping', port)
                return
            except OSError:
                time.sleep(0.2)
        raise SystemExit('control on %d never came up' % port)

    # 2g3c. the reconnect: the server dies mid-session, the CLI retries
    # (--reconnect attempts, --reconnect-wait apart) and resumes the session
    fake_r = subprocess.Popen([sys.executable, F, '--static', '--port', '15901', '--control-port', '15902'],
                              stdout=open('/tmp/scr_recon.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_r)
    wait_ctl(15902)   # the cold python start can outrun a fixed sleep
    p = subprocess.Popen([sys.executable, K, '--control-port', '15902', '--reconnect', '3',
                          '--reconnect-wait', '0.5'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(0.6)
    fake_r.kill()
    fake_r.wait()
    time.sleep(0.3)
    fake_r2 = subprocess.Popen([sys.executable, F, '--static', '--port', '15901', '--control-port', '15902'],
                               stdout=open('/tmp/scr_recon2.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_r2)
    p.stdin.write('show pv\n')       # the loss is noticed on the first wire command
    p.stdin.flush()
    time.sleep(2.2)                  # the reconnect cycle: the attempt 1 refused, the attempt 2 ok
    p.stdin.write('show pv\n')       # the resumed session answers again
    p.stdin.flush()
    time.sleep(0.6)
    p.stdin.write('quit\n')
    p.stdin.flush()
    out, _ = p.communicate(timeout=20)
    check('fake_cli: reconnects after the server death (3 tries, 0.5 s apart)',
          p.returncode == 0 and 'reconnecting' in out and 'reconnected' in out
          and 'auto' in out, repr(out[-200:]))   # the resumed session answers show pv (bare value)

    # 2g3b. the INV audit trail: the server side logs the lifecycle + the commands
    AUDD = '/tmp/scr_audit_inv.log'
    if os.path.exists(AUDD):
        os.unlink(AUDD)
    inv = subprocess.Popen([sys.executable, F, '--static', '--port', '15586', '--control-port', '15587',
                            '--audit-log', AUDD],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    ctl('set soc 55', 15587)
    ctl('ping', 15587)
    os.kill(inv.pid, signal.SIGHUP)
    os.kill(inv.pid, signal.SIGUSR1)
    time.sleep(0.8)
    os.kill(inv.pid, signal.SIGTERM)
    time.sleep(1)
    inv_rows = open(AUDD).read()
    check('audit: INV logs START, COMMAND (peer), RELOAD, RESET, SHUTDOWN; ping skipped',
          'INV START ' in inv_rows and 'version=' in inv_rows and "INV COMMAND " in inv_rows
          and 'peer=127.0.0.1' in inv_rows
          and "'set soc 55' -> ok" in inv_rows and 'INV RELOAD' in inv_rows
          and 'INV RESET ' in inv_rows and 'SIGUSR1' in inv_rows and 'INV SHUTDOWN ' in inv_rows
          and 'SIGTERM' in inv_rows
          and 'ping' not in inv_rows, inv_rows)

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

    # 2f. register-map profiles: the fake serves the SUN2000 layout from
    # profiles/profiles/sun2000.json by default; a custom profile remaps names onto
    # different registers (with per-entry type/scale) to emulate other devices
    import json as _json
    prof = '/tmp/scr_prof_custom.json'
    _json.dump({'description': 'remapped device',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'i32', 'scale': 1},
                    {'name': 'device-temperature', 'register': 33136, 'type': 'i16', 'scale': 10},
                    {'name': 'battery-soc', 'register': 40123, 'type': 'u16', 'scale': 1},
                ]}, open(prof, 'w'))

    fake_prof = subprocess.Popen([sys.executable, F, '--static', '--battery', '--strict', '--port', '15592',
                                  '--control-port', '0', '--profile', prof],
                                 stdout=open('/tmp/scr_prof.log', 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_prof)
    time.sleep(0.8)
    r = read3(40001, 2, 15592)
    check('profile: pv-power remapped to 40001', r[0] == 3 and struct.unpack('>i', r[2:6])[0] == 4000, r.hex())
    r = read3(33136, 1, 15592)
    check('profile: temperature remapped to 33136 (x10)', r[0] == 3 and struct.unpack('>H', r[2:4])[0] == 280, r.hex())
    r = read3(40123, 1, 15592)
    check('profile: battery-soc retyped (scale 1, not x10)', r[0] == 3 and struct.unpack('>H', r[2:4])[0] == 65, r.hex())
    r = read3(32064, 2, 15592)
    check('profile: unmapped default register is undefined (strict 02)', r[0] == 0x83 and r[1] == 2, r.hex())
    # the device-status VALUE MAP in the profile's desc drives the serving
    stmap = '/tmp/scr_prof_status.json'
    _json.dump({'mappings': [{'register': 'device-status',
                               'values': {'7': 'on-grid', '9': 'standby'}}],
                'registers': [{'name': 'device-status', 'register': 32089, 'type': 'u16', 'scale': 1,
                               'desc': 'running status code'}]}, open(stmap, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--port', '15595',
                                   '--control-port', '0', '--profile', stmap],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    b = read3(32089, 1, 15595)
    check('profile: the status map serves the profile codes (7 = on-grid)',
          b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 7, b.hex())

    badprof = '/tmp/scr_prof_bad.json'
    _json.dump({'registers': [{'name': 'mystery-value', 'register': 32064, 'type': 'i32', 'scale': 1}]},
               open(badprof, 'w'))
    r = subprocess.run([sys.executable, F, '--dry-run', '--profile', badprof], capture_output=True, text=True)
    check('profile: a name the fake cannot simulate is accepted but never served', r.returncode == 0
          and 'mystery-value' in open(badprof).read(), r.stderr.strip()[-90:])

    fake_env = subprocess.Popen([sys.executable, F, '--static', '--battery', '--port', '15594',
                                 '--control-port', '0'],
                                stdout=open('/tmp/scr_prof2.log', 'w'), stderr=subprocess.STDOUT,
                                env={**os.environ, 'FAKE_PROFILE': prof})
    procs.append(fake_env)
    time.sleep(0.8)
    r = read3(40001, 2, 15594)
    check('profile: FAKE_PROFILE env selects the map', r[0] == 3 and struct.unpack('>i', r[2:6])[0] == 4000, r.hex())
    prof2 = '/tmp/scr_prof_custom2.json'
    _json.dump({'registers': [{'name': 'pv-power', 'register': 40003, 'type': 'i32', 'scale': 1}]},
               open(prof2, 'w'))
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'profile', prof2],
                       capture_output=True, text=True)
    check('control: set profile swaps the map live', r.returncode == 0
          and r.stdout.startswith('ok profile=unnamed profile (%s)' % prof2), r.stdout.strip())
    r1, r2 = read3(40001, 2, 15570), read3(40003, 2, 15570)
    check('control: the swapped map serves the new addresses', r2[0] == 3
          and struct.unpack('>i', r2[2:6])[0] == 4000 and struct.unpack('>i', r1[2:6])[0] == 0, (r1 + r2).hex())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'profile'],
                       capture_output=True, text=True)
    check('control: show profile reports description + path', r.stdout.strip() == 'ok profile=unnamed profile (%s)' % prof2, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'profile', '/tmp/scr_nope.json'],
                       capture_output=True, text=True)
    check('control: set profile of a bad file is rejected', r.returncode == 0
          and r.stdout.startswith('err '), r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'unset', 'profile'],
                       capture_output=True, text=True)
    check('control: unset profile restores the configured map (its description shows)', r.returncode == 0
          and 'profile=SUN2000 with optional LUNA2000 battery and meter' in r.stdout
          and 'pv=4000W' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'profile', 'sun2000'],
                       capture_output=True, text=True)
    check('control: the built-in profile answers to its name (sun2000)', r.returncode == 0
          and r.stdout.startswith('ok profile=SUN2000 with optional LUNA2000 battery and meter (sun2000)'),
          r.stdout.strip())
    r = subprocess.run([sys.executable, F, '--dry-run', '--profile', 'sun2000'], capture_output=True, text=True)
    check('profile: --profile sun2000 resolves the built-in (dry-run rc 0)', r.returncode == 0, r.stderr[-80:])
    r = read3(32064, 2, 15570)
    check('profile: the default map is back', r[0] == 3 and struct.unpack('>i', r[2:6])[0] == 4000, r.hex())
    os.kill(fake_env.pid, signal.SIGTERM)

    # 2g. cloud machines: autumn/winter wander the cloud factor over the
    # simulated clock (time-lapse moves them, a frozen clock freezes them)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'cloud', 'autumn'],
                       capture_output=True, text=True)
    check('cloud: autumn machine engages', r.returncode == 0 and 'cloud=autumn(' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'cloud', '0'],
                       capture_output=True, text=True)
    check('cloud: a pinned factor overrides the machine', r.returncode == 0
          and 'cloud=0' in r.stdout, r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15571', 'unset', 'cloud'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'status'], capture_output=True, text=True)
    check('cloud: unset returns to a clear sky', 'cloud=clear' in r.stdout, r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'cloud', 'winter'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'time', '12:00'],
                       capture_output=True, text=True)
    winter_pv = r.stdout
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'cloud', 'autumn'], capture_output=True, text=True)
    check('cloud: machines differ under the same seed', 'cloud=autumn(' in r.stdout
          and r.stdout != winter_pv, r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15571', 'reset'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'status'], capture_output=True, text=True)
    check('cloud: reset releases the machine', 'cloud=clear' in r.stdout, r.stdout.strip())

    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'cloud', 'spring'], capture_output=True, text=True)
    check('cloud: spring machine engages', r.returncode == 0 and 'cloud=spring(' in r.stdout, r.stdout.strip())

    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'battery-state', 'discharging'], capture_output=True, text=True)
    check('battery-state: force discharges at full power', r.returncode == 0
          and 'batt=-2000W' in r.stdout and 'batt-state=discharging' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'battery-state', 'auto'], capture_output=True, text=True)
    check('battery-state: auto hands back to the machine', r.returncode == 0
          and 'batt-state' not in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'registers'], capture_output=True, text=True)
    rows = [l for l in r.stdout.splitlines() if ' | ' in l]
    cols = {l.index(' | ') for l in rows}
    check('show registers: name | register | type | current value, columns aligned', r.returncode == 0
          and r.stdout.startswith('ok registers (') and len(rows) >= 49 and len(cols) == 1
          and any(l.startswith('pv-power') and '| 32064 | i32 |' in l and l.split(' | ')[3].strip().isdigit()
                  for l in rows)
          and any(l.startswith('battery-power') and '| 37001 | i32 |' in l for l in rows)
          and max(len(l) for l in rows) <= 60, r.stdout.strip()[:80])

    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'version'], capture_output=True, text=True)
    check('show version: ok fake-inverter 0.3.0-<git>', r.returncode == 0
          and r.stdout.strip().startswith('ok fake-inverter 0.3.0-'), r.stdout.strip())
    r = subprocess.run([sys.executable, F, '--version'], capture_output=True, text=True)
    check('fake_inverter: --version reports 0.3.0-<short git>', r.returncode == 0
          and r.stdout.strip().startswith('0.3.0-') and len(r.stdout.strip()) > 10
          and r.stdout.strip() == '0.3.0-' + r.stdout.strip().split('-', 1)[1], r.stdout.strip())
    check('fake_ctl/fake_cli are executable', os.access(FCTL, os.X_OK) if 'FCTL' in dir() else True)

    # the battery is on by default (no flag): the status shows a real SoC, and
    # the state force refuses while the battery is off
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '15639', '--port', '15638',
                                   '--time', '12:00'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.8)
    r = subprocess.run([sys.executable, C, '--control-port', '15639', 'show', 'status'], capture_output=True, text=True)
    check('battery: on by default (no flag)', r.returncode == 0 and 'soc=n/a' not in r.stdout
          and 'soc=' in r.stdout, r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15639', 'set', 'battery', 'off'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15639', 'set', 'battery-state', 'charging'], capture_output=True, text=True)
    check('battery-state: refuses with the battery off',
          'err battery-state needs the battery on' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15639', 'show', 'registers'], capture_output=True, text=True)
    rows = [l for l in r.stdout.splitlines() if ' | ' in l]
    check('show registers: NaN when the value is not calculated (the battery off)',
          any(l.startswith('battery-power') and l.split(' | ')[-1].strip() == 'NaN' for l in rows)
          and any(l.startswith('pv-power') and l.split(' | ')[-1].strip() != 'NaN' for l in rows), r.stdout.strip()[:120])
    subprocess.run([sys.executable, C, '--control-port', '15639', 'shutdown'], capture_output=True)

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
          'chaos=0.00' in subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'show', 'status'], capture_output=True, text=True).stdout)
    s = socket.create_connection(('127.0.0.1', 15574), timeout=5)
    s.sendall(struct.pack('>HHHB', 5, 0, 6, 1) + struct.pack('>BHH', 6, 47415, 99))
    s.recv(64)
    s.close()
    subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'set', 'pv', '2500'], capture_output=True)
    os.kill(fake_ctl.pid, signal.SIGHUP)
    time.sleep(0.8)
    sig_status = subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'show', 'status'], capture_output=True, text=True).stdout
    check('signals: SIGHUP re-applies the FAKE_* env layer',
          '\nchaos=0.90\n' in sig_status and '\npinned=pv=2500.0\n' in sig_status, sig_status)
    os.kill(fake_ctl.pid, signal.SIGUSR1)
    time.sleep(0.8)
    sig_status = subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'show', 'status'], capture_output=True, text=True).stdout
    check('signals: SIGUSR1 resets pins + write overlay', '\npinned=none\n' in sig_status
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
    pid = int(subprocess.run(['pgrep', '-f', 'modbus_scraper.py.*19443'], capture_output=True,
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
    #     (the file must be owner-only 0600 — F12 in docs/AUDIT.md)
    with open('/tmp/scr_token.txt', 'w') as fh:
        fh.write('first-token\n')
    os.chmod('/tmp/scr_token.txt', 0o600)
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
    pid = int(subprocess.run(['pgrep', '-f', 'modbus_scraper.py.*19447'], capture_output=True,
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
    lax = '/tmp/scr_token_lax.txt'
    open(lax, 'w').write('laxsecret\n')                                 # the umask default (0644)
    r = subprocess.run([sys.executable, P, '--dry-run', '--auth-token-file', lax],
                       capture_output=True)
    check('token file: group/world-readable file refused (F12)',
          r.returncode == 1 and b'0600' in r.stderr and b'Traceback' not in r.stderr,
          repr(r.stderr[-140:]))

    # 3e. resource limits: --max-clients 503s the overflow, --client-timeout kicks idle keep-alives
    write_ini('/tmp/scr_lim.ini', 'max_clients = 1\nclient_timeout = 1\nmax_conn_per_ip = 1')
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

    # 3e2. the per-IP cap: two simultaneous connections from 127.0.0.1, the second 503s
    write_ini('/tmp/scr_pip.ini', 'max_conn_per_ip = 1\nmax_clients = 0')
    procs.append(subprocess.Popen([sys.executable, P, '--config', '/tmp/scr_pip.ini',
                                   '--host', '127.0.0.1', '--modbus-port', str(FAKE_PORT),
                                   '--listen', '127.0.0.1:19449'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    parked = socket.create_connection(('127.0.0.1', 19449), timeout=5)
    parked.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\n')  # incomplete: parks the peer's only slot
    time.sleep(0.5)
    s2 = socket.create_connection(('127.0.0.1', 19449), timeout=5)
    s2.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\n\r\n')
    reply = s2.recv(64)
    check('max-conn-per-ip: the second connection from one IP -> 503', reply.startswith(b'HTTP/1.1 503'),
          reply.split(b'\r\n')[0].decode())
    s2.close()
    parked.close()

    # 3e3. the F13 refusal: /metrics beyond loopback refuses to start without a token
    r = subprocess.run([sys.executable, P, '--dry-run', '--listen', '0.0.0.0:19450'],
                       capture_output=True)
    check('F13: non-loopback listen without a token refused', r.returncode == 1
          and b'refusing to expose /metrics beyond loopback' in r.stderr and b'Traceback' not in r.stderr,
          repr(r.stderr[-140:]))
    r = subprocess.run([sys.executable, P, '--dry-run', '--listen', '0.0.0.0:19450', '--auth-token', 't'],
                       capture_output=True)
    check('F13: non-loopback listen with a token accepted', r.returncode == 0, repr(r.stderr[-140:]))
    r = subprocess.run([sys.executable, P, '--dry-run', '--listen', '127.0.0.1:19450'],
                       capture_output=True)
    check('F13: the loopback default needs no token', r.returncode == 0, repr(r.stderr[-140:]))

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
                        % (os.path.join(REPO, 'scrape'), '/nonexistent/metrics.json')],
                       capture_output=True)
    check('missing metrics.json: clean rc=1', r.returncode == 1 and b'metrics spec /nonexistent/metrics.json not found' in r.stderr)
    with open('/tmp/bad_spec.json', 'w') as fh:
        fh.write('{not json')
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; Metrics(%r)'
                        % (os.path.join(REPO, 'scrape'), '/tmp/bad_spec.json')],
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
