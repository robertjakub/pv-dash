#!/usr/bin/env python3
"""Regression suite for modbus-scraper (+ fake inverter).

Run from anywhere: python3 tests/scrape-regtest.py
Starts its own fake inverter + scraper instances on scratch ports and
cleans up after itself.
"""
import json as _json
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

if not os.environ.get('PV_RUN_DIR'):   # the battery sets it (scripts/battery.sh)
    sys.exit('suite: run through scripts/battery.sh (the run dir + the port slot; '
             'a standalone run shares /tmp scratch and collides across sessions)')
SCRATCH = os.environ['PV_RUN_DIR']   # the battery's per-run tmp — every scratch file lands here (the sockets are the daemons' own /tmp constants)
os.makedirs(SCRATCH, exist_ok=True)   # the CI legs set a fixed path the battery never made
print('NOTE started at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))

PROFILE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ('quick', 'full') \
    else os.environ.get('PV_SUITE_PROFILE', 'quick')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPER_DIR = os.path.join(REPO, 'scraper')

P = os.path.join(SCRAPER_DIR, 'bin', 'modbus-scraper.py')
F = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
# the suite's spec — via the env (a test's explicit --metrics-spec still wins);
# examples/ is never a loader default, a checkout has no bundled spec
os.environ['METRICS_SPEC'] = os.path.join(SCRAPER_DIR, 'examples', 'metrics.json')
BASE = int(os.environ.get('SUITE_PORT_BASE', '0'))   # the concurrent-battery port space (the runner's slot)
PORT = 15541 + BASE
PORT_A = 19441 + BASE

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
    # the set grammar (the ini format is gone): every line a `set`
    with open(path, 'w') as fh:
        fh.write('# the regtest config\nset interval 0.3\nset timeout 1\n%s\n' % extra)


procs = []

class QuickDone(Exception):
    pass


try:
    # 1. baseline: the fake's battery (always on) + the scraper
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--listen', '127.0.0.1:%d' % (PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    write_ini(os.path.join(SCRATCH, 'scr_base.ini'))
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % PORT_A],
                                  stdout=open(os.path.join(SCRATCH, 'scr_reg.log'), 'w'), stderr=subprocess.STDOUT))
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
    check('health gauges', m.get('scraper_up') == 1
          and m.get('scraper_modbus_errors_total') == 0 and m.get('scraper_last_poll_timestamp_seconds', 0) > 0)
    check('cache diag auto-detected (fake serves the block)', m.get('scraper_cache_device_up') == 1
          and m.get('scraper_cache_age_seconds') == 7 and m.get('scraper_cache_uptime_seconds') == 4242,
          str({k: v for k, v in m.items() if 'cache' in k}))

    # 1a. scraper profile: the scrape-marked entries feed the metric registers
    prof = os.path.join(SCRATCH, 'scr_scraper_profile.json')
    _json.dump({'description': 'remapped device',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'i32', 'scale': 1, 'scrape': True},
                    {'name': 'grid-power', 'register': 40003, 'type': 'i32', 'scale': 1, 'scrape': True},
                    {'name': 'battery-power', 'register': 40005, 'type': 'i32', 'scale': 1, 'scrape': True},
                    {'name': 'battery-soc', 'register': 40123, 'type': 'u16', 'scale': 1, 'scrape': True},
                ]}, open(prof, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--strict', '--listen', '127.0.0.1:%d' % (15590 + BASE),
                                   '--control-port', '0', '--profile', prof],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15590 + BASE),
                                   '--listen', '127.0.0.1:%d' % (9361 + BASE), '--profile', prof],
                                  stdout=open(os.path.join(SCRATCH, 'scr_prof_scraper.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9361 + BASE)
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
    prof4 = os.path.join(SCRATCH, 'scr_fc4_profile.json')
    _json.dump({'description': 'fc4-marked source',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'i32', 'scale': 1, 'fc': 4, 'scrape': True},
                    {'name': 'grid-power', 'register': 40003, 'type': 'i32', 'scale': 1, 'scrape': True},
                ]}, open(prof4, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--strict', '--listen', '127.0.0.1:%d' % (15547 + BASE),
                                   '--control-port', '0', '--profile', prof4],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15547 + BASE),
                                   '--listen', '127.0.0.1:%d' % (9362 + BASE), '--profile', prof4],
                                  stdout=open(os.path.join(SCRATCH, 'scr_fc4.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9362 + BASE)
        if m.get('huawei_pv_generation_watts') == 4000:
            break
        time.sleep(0.3)
    check('profile fc: the fc4-marked pv-power is read over FC4',
          m.get('huawei_pv_generation_watts') == 4000 and m.get('scraper_up') == 1,
          str({k: m.get(k) for k in ('huawei_pv_generation_watts', 'huawei_up')}))
    # Negative half: an FC3-only device cannot serve an fc4-marked source
    # (the evil server drops FC4 requests) — the poll must fail, not silently
    # succeed over FC3.
    evil4 = EvilInverter(15592, {40001: 4000, 40003: 0})
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15592 + BASE),
                                   '--listen', '127.0.0.1:%d' % (9364 + BASE), '--profile', prof4],
                                  stdout=open(os.path.join(SCRATCH, 'scr_fc4_evil.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(1.5)          # a few failed polls at the 0.3s interval
    status, m = wait_metrics(9364, want=None)
    check('profile fc: an fc4 source on an FC3-only device fails the poll',
          m.get('scraper_up') == 0 and m.get('scraper_modbus_errors_total', 0) >= 1
          and 'huawei_pv_generation_watts' not in m,
          str({k: m.get(k) for k in ('huawei_up', 'huawei_modbus_errors_total')}))
    evil4.stop()

    # 1a-bis-2. the modbus offset: the live set reaches the client and the
    # next poll reads the shifted addresses — a large offset moves the whole
    # window off the device map (the poll must fail loudly, not silently),
    # clear reads the map true again. The shipped sun2000 map anchors the reads.
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--strict', '--listen', '127.0.0.1:%d' % (15608 + BASE),
                                   '--control-port', '0'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15608 + BASE),
                                   '--listen', '127.0.0.1:%d' % (9368 + BASE),
                                   '--control-port', '15610', '--control-token', 'offstok'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_offset.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9368 + BASE)
        if 'huawei_pv_generation_watts' in m:
            break
        time.sleep(0.3)
    check('modbus offset: the poll reads the map true (pv 4000, up)',
          m.get('huawei_pv_generation_watts') == 4000 and m.get('scraper_up') == 1,
          str({k: m.get(k) for k in ('huawei_pv_generation_watts', 'scraper_up')}))
    r = subprocess.run([sys.executable, os.path.join(SCRAPER_DIR, 'bin', 'modbus-scraper-ctl.py'),
                        '--control-port', '15610', '--control-token', 'offstok',
                        'set', 'modbus-offset', '20000'], capture_output=True, text=True, timeout=15)
    check('modbus offset: the live set answers the typed value', r.stdout.startswith('ok modbus-offset=20000'),
          repr(r.stdout[:90] + r.stderr[:90]))
    for _ in range(30):
        status, m = wait_metrics(9368, want='scraper_up')
        if m.get('scraper_up') == 0 and m.get('scraper_modbus_errors_total', 0) >= 1:
            break
        time.sleep(0.3)
    check('modbus offset: the shift moves the window off the map (the poll fails loudly)',
          m.get('scraper_up') == 0 and m.get('scraper_modbus_errors_total', 0) >= 1,
          str({k: m.get(k) for k in ('scraper_up', 'scraper_modbus_errors_total')}))
    r = subprocess.run([sys.executable, os.path.join(SCRAPER_DIR, 'bin', 'modbus-scraper-ctl.py'),
                        '--control-port', '15610', '--control-token', 'offstok',
                        'clear', 'modbus-offset'], capture_output=True, text=True, timeout=15)
    check('modbus offset: clear restores the configured zero', r.stdout.startswith('ok modbus-offset=0'),
          repr(r.stdout[:90]))
    for _ in range(30):
        status, m = wait_metrics(9368, want='scraper_up')
        if m.get('scraper_up') == 1 and m.get('huawei_pv_generation_watts') == 4000:
            break
        time.sleep(0.3)
    check('modbus offset: the restore reads the map true again',
          m.get('huawei_pv_generation_watts') == 4000 and m.get('scraper_up') == 1,
          str({k: m.get(k) for k in ('huawei_pv_generation_watts', 'scraper_up')}))
    subprocess.run([sys.executable, os.path.join(SCRAPER_DIR, 'bin', 'modbus-scraper-ctl.py'),
                    '--control-port', '15610', '--control-token', 'offstok', 'shutdown'],
                   capture_output=True, text=True, timeout=15)

    # 1a-ter. the bit and float types: a bit source reads over FC1, an f32
    # source decodes IEEE 754, an f32swap source the lo-hi word order — and
    # the profile-bound extras (beyond the power math) export soft.
    profx = os.path.join(SCRATCH, 'scr_bits_profile.json')
    _json.dump({'description': 'bit + float sources',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'i32', 'scale': 1},
                    {'name': 'grid-power', 'register': 40003, 'type': 'i32', 'scale': 1},
                    {'name': 'device-insulation', 'register': 40010, 'type': 'f32', 'scale': 1},
                    {'name': 'meter-status', 'register': 40020, 'type': 'bit', 'scale': 1},
                ]}, open(profx, 'w'))
    specx = os.path.join(SCRATCH, 'scr_bits_spec.json')
    _json.dump({'metrics': {
        'pv_generation_watts': {'profile': 'pv-power', 'help': 'pv watts'},
        'grid_net_watts': {'profile': 'grid-power', 'help': 'grid watts'},
        'float_value': {'profile': 'device-insulation', 'help': 'an f32 row'},
        'coil_flag': {'profile': 'meter-status', 'help': 'an FC1 bit row'},
    }}, open(specx, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15548 + BASE),
                                   '--control-port', '0', '--profile', profx],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15548 + BASE), '--profile', profx,
                                   '--listen', '127.0.0.1:%d' % (9366 + BASE), '--metrics-spec', specx],
                                  stdout=open(os.path.join(SCRATCH, 'scr_bits.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9366 + BASE)
        if 'huawei_coil_flag' in m:
            break
        time.sleep(0.3)
    check('profile types: the bit source reads over FC1 (meter-status -> 1)',
          m.get('huawei_coil_flag') == 1, str(m.get('huawei_coil_flag')))
    check('profile types: the f32 source decodes IEEE 754 (device-insulation 970.0)',
          m.get('huawei_float_value') == 970.0, str(m.get('huawei_float_value')))
    check('profile types: the power math still holds on the i32 sources',
          m.get('huawei_pv_generation_watts') == 4000 and m.get('huawei_grid_net_watts') == -1500,
          str({k: m.get(k) for k in ('huawei_pv_generation_watts', 'huawei_grid_net_watts')}))
    # the swapped word orders: pv on f32swap (lo word first), grid on plain f32
    profs = os.path.join(SCRATCH, 'scr_swap_profile.json')
    _json.dump({'description': 'swapped word order',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'f32swap', 'scale': 1},
                    {'name': 'grid-power', 'register': 40003, 'type': 'f32', 'scale': 1},
                ]}, open(profs, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15549 + BASE),
                                   '--control-port', '0', '--profile', profs],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15549 + BASE), '--profile', profs,
                                   '--listen', '127.0.0.1:%d' % (9367 + BASE), '--metrics-spec', specx],
                                  stdout=open(os.path.join(SCRATCH, 'scr_swap.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9367 + BASE)
        if 'huawei_pv_generation_watts' in m:
            break
        time.sleep(0.3)
    check('profile types: the f32swap source decodes the lo-hi word order (pv 4000)',
          m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_pv_generation_watts')))
    check('profile types: the plain f32 grid decodes (-1500, the math holds)',
          m.get('huawei_grid_net_watts') == -1500 and m.get('huawei_home_consumption_watts') == 5500,
          str({k: m.get(k) for k in ('huawei_grid_net_watts', 'huawei_home_consumption_watts')}))

    # 1b. the shipped Deye profile end-to-end: real Deye addresses (SG03LP1
    # family), SoC reported as plain percent (gain 1), omitted registers = 0
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--strict', '--listen', '127.0.0.1:%d' % (15596 + BASE),
                                   '--control-port', '0', '--profile', 'deye-sg03lp1'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15596 + BASE),
                                   '--listen', '127.0.0.1:%d' % (9363 + BASE), '--profile', 'deye-sg03lp1'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_deye.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9363 + BASE)
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
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--strict', '--listen', '127.0.0.1:%d' % (15598 + BASE),
                                   '--control-port', '0', '--profile', 'deye-sg04lp3'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15598 + BASE),
                                   '--listen', '127.0.0.1:%d' % (9365 + BASE), '--profile', 'deye-sg04lp3'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_deye3.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        status, m = wait_metrics(9365 + BASE)
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
    r = subprocess.run([sys.executable, F, '--dry-run', '--static',
                        '--profile', 'deye-sg05lp3'], capture_output=True, text=True)
    check('deye-sg05lp3: profile loads (dry-run rc 0)', r.returncode == 0
          and 'Deye SUN-12K-SG05LP3-EU' in r.stderr, r.stderr.strip()[-80:])
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15593 + BASE),
                                   '--control-port', '0', '--profile', 'deye-sg05lp3'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    b = read3(672, 2, 15593)
    check('deye-sg05lp3: pv at 672', b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 4000, b.hex())
    status, root = get('/', PORT_A)
    check('root path answers', status == 200 and b'modbus-scraper' in root.encode())
    status, _ = get('/nope', PORT_A)
    check('404 for unknown paths', status == 404)

    # 2. the compute expressions: a custom spec evaluates per poll
    with open(os.path.join(SCRATCH, 'scr_spec_expr.json'), 'w') as fh:
        _json.dump({'metrics': {'pv_generation_watts': {'profile': 'pv-power', 'help': 'Current PV power in watts.'},
                                'grid_net_watts': {'profile': 'grid-power', 'help': 'Net grid power in watts.'},
                                'battery_net_watts': {'profile': 'battery-power', 'help': 'Battery net power in watts.'},
                                'battery_soc_percent': {'profile': 'battery-soc', 'help': 'Battery state of charge in percent.'},
                                'pv_kilowatts': {'expr': 'pv / 1000', 'help': 'PV power in kilowatts.'}}}, fh)
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_base.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--metrics-spec', os.path.join(SCRATCH, 'scr_spec_expr.json'),
                                   '--listen', '127.0.0.1:%d' % (19470 + BASE)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    status, m = wait_metrics(19470 + BASE)
    check('compute expr: pv / 1000 exports 4.0', m.get('huawei_pv_kilowatts') == 4.0,
          str(m.get('huawei_pv_kilowatts')))

    # 2c. fake extras: control server (runtime overrides) + chaos injection
    def ctl(cmd, port):
        # the JSON-lines control transport: one request object, one reply object
        try:
            s = socket.create_connection(('127.0.0.1', port), timeout=5)
            s.sendall((_json.dumps({'cmd': cmd}, ensure_ascii=False) + '\n').encode())
            buf = b''
            while not buf.endswith(b'\n'):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            s.close()
        except OSError as e:
            return 'fail cannot reach control server at 127.0.0.1:%d: %s' % (port, e)
        # the first frame only: the daemon-exit bye can ride the same
        # segment on a shutdown (announce_exit)
        obj = _json.loads(buf.split(b'\n', 1)[0].decode('utf-8', 'replace'))
        return '%s %s' % (obj.get('status', 'fail'), str(obj.get('text', '')))

    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15570 + BASE),
                                   '--control-port', '15571', '--allow-write'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_ctl_fake.log'), 'w'), stderr=subprocess.STDOUT))
    write_ini(os.path.join(SCRATCH, 'scr_ctl.ini'))
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_ctl.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15570 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19455 + BASE)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    status, m = wait_metrics(19455 + BASE)
    check('control: baseline static values', m.get('huawei_pv_generation_watts') == 4000,
          str(sorted(m))[:120])   # the detail = what the first pull served
    ctl('set pv 2500', 15571)
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('control: pv pinned at runtime', m.get('huawei_pv_generation_watts') == 2500,
          str(m.get('huawei_pv_generation_watts')))
    ctl('set soc 30', 15571)
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('control: soc pinned at runtime', m.get('huawei_battery_soc_percent') == 30,
          str(m.get('huawei_battery_soc_percent')))
    ctl('set pv auto', 15571)
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('control: pv override released', m.get('huawei_pv_generation_watts') == 4000)
    check('control: pv override released (the pin reads auto)',
          ctl('show pv', 15571) == 'ok pv=auto', ctl('show pv', 15571))
    check('control: soc stays pinned (the pin reads 30)', ctl('show soc', 15571).startswith('ok soc=30'),
          ctl('show soc', 15571))

    # 2d. modbus-fake-ctl.py: the CLI tool speaks TCP and unix-socket control servers
    C = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py')
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'pv', '2700'], capture_output=True, text=True)
    check('fake_ctl: TCP pin via tool', r.returncode == 0 and r.stdout.startswith('ok pv=2700 '), r.stdout.strip())
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('fake_ctl: pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 2700,
          str(m.get('huawei_pv_generation_watts')))
    r = subprocess.run([sys.executable, C, '--control-port', '19999', 'show', 'version'], capture_output=True, text=True)
    check('fake_ctl: dead port -> clean rc=1', r.returncode == 1 and 'cannot reach' in r.stderr)

    # 2e. fake audit-logging + malformed-input defense (no tracebacks, no bricking)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'pv', 'nan'], capture_output=True, text=True)
    check('control: non-finite pin rejected', r.stdout.startswith('% error: value must be finite'), r.stdout.strip())
    time.sleep(1)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
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
    ctl_log = open(os.path.join(SCRATCH, 'scr_ctl_fake.log')).read()
    check('fake audit: write + rejected FC + malformed frame logged one-line',
          'write: register 47415 = 99 (single register, unit 1)' in ctl_log
          and 'write: coil 1 = 0x00ff from' in ctl_log
          and '-> exception 03 (illegal data value)' in ctl_log
          and 'malformed frame from' in ctl_log)
    subprocess.run([sys.executable, C, '--control-port', '15571', 'pv', '1234'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'reset'], capture_output=True, text=True)
    check('control: reset clears all pins', r.returncode == 0
          and r.stdout.startswith('ok reset (') and 'pinned' not in r.stdout, r.stdout.strip())
    time.sleep(1)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('control: reset returns the register truth', m.get('huawei_pv_generation_watts') == 4000,
          str(m.get('huawei_pv_generation_watts')))
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'reset'], capture_output=True, text=True)
    check('control: reset is idempotent', r.returncode == 0
          and r.stdout.startswith('ok reset (0 pin(s)') and 'pinned' not in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'help'], capture_output=True, text=True)
    check('control: help lists the commands', r.returncode == 0
          and r.stdout.startswith('ok commands: set <pv|load|batt|grid|soc') and 'chaos' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'knobs'], capture_output=True, text=True)
    check('control: show knobs, the dictionary of the registry', r.returncode == 0
          and '--chaos' in r.stdout and '$CHAOS' in r.stdout and ', secret' in r.stdout,
          r.stdout.strip()[:200])

    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'show', 'settings'], capture_output=True, text=True)
    check('control: show settings is retired (err)', r.returncode == 0
          and r.stdout.startswith('% error:'), r.stdout.strip()[:120])
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'battery', 'off'], capture_output=True, text=True)
    check('control: set battery is retired (the battery is always on, err)',
          r.returncode == 0 and r.stdout.startswith('% error:'), r.stdout.strip()[:120])
    check('fake audit: control commands quiet at INFO',
          'control: set pv nan -> err' not in ctl_log and 'control: set soc 30' not in ctl_log)
    if PROFILE == 'quick':
        raise QuickDone()   # quick: the core sections only
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15588 + BASE), '--control-port', '15589',
                                   '--log-level', 'DEBUG'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_ctl_dbg.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    ctl('set soc 30', 15589)
    ctl('show version', 15589)
    subprocess.run([sys.executable, C, '--control-port', '15589', 'shutdown'], capture_output=True, text=True)
    time.sleep(1)
    ctl_debug = open(os.path.join(SCRATCH, 'scr_ctl_dbg.log')).read()
    check('fake audit: control commands logged with the peer, the status only — the output withheld by default',
          'control from 127.0.0.1' in ctl_debug and ': set soc 30 -> ok' in ctl_debug
          and '-> ok fake-inverter' not in ctl_debug, ctl_debug[-200:])
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15584 + BASE), '--control-port', '15585',
                                   '--log-level', 'DEBUG', '--control-log-replies'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_ctl_full.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    ctl('set soc 30', 15585)
    ctl('show version', 15585)
    ctl_full = open(os.path.join(SCRATCH, 'scr_ctl_full.log')).read()
    check('fake audit: --control-log-replies logs the full command output',
          ': set soc 30 -> ok soc=30' in ctl_full and ': show version -> ok fake-inverter' in ctl_full, ctl_full[-200:])
    r = subprocess.run([sys.executable, C, '--control-port', '15585', 'set', 'system', 'log-replies', 'off'],
                       capture_output=True, text=True)
    check('fake audit: set system log-replies off (the live toggle, the ctl translates)',
          r.returncode == 0 and r.stdout.startswith('ok control-log-replies=off'), r.stdout.strip() or r.stderr.strip())
    ctl('show version', 15585)
    subprocess.run([sys.executable, C, '--control-port', '15585', 'shutdown'], capture_output=True, text=True)
    time.sleep(1)
    ctl_full = open(os.path.join(SCRATCH, 'scr_ctl_full.log')).read()
    check('fake audit: the live off withholds the output again',
          ': set control-log-replies off -> ok' in ctl_full and ': show version -> ok\n' in ctl_full,
          ctl_full[-200:])

    # 2f. CTL environment (short name) drives both tools when the flag is clear
    r = subprocess.run([sys.executable, C, 'set', 'pv', '2200'], capture_output=True, text=True,
                       env={**os.environ, 'CTL': '15571'})
    check('fake_ctl: CTL env picks the target', r.returncode == 0
          and r.stdout.startswith('ok pv=2200 '), r.stdout.strip() or r.stderr.strip())
    time.sleep(1)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('fake_ctl: env-pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 2200,
          str(m.get('huawei_pv_generation_watts')))
    SIG_SOCK2 = '/tmp/fake-inverter-15577.socket'
    fake_env = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15577 + BASE)],
                                stdout=open(os.path.join(SCRATCH, 'scr_sig2.log'), 'w'), stderr=subprocess.STDOUT,
                                env={**os.environ, 'CTL': SIG_SOCK2})
    procs.append(fake_env)
    time.sleep(0.8)
    r = subprocess.run([sys.executable, C, 'inspect'], capture_output=True, text=True,
                       env={**os.environ, 'CTL': SIG_SOCK2})
    check('fake: CTL env opens the default-flag-less control server',
          r.returncode == 0 and 'pv 4000 W' in r.stdout and 'grid -1500 W' in r.stdout
          and 'battery   1200 W' in r.stdout and '\npinned    nothing' in r.stdout, r.stdout.strip())
    os.kill(fake_env.pid, signal.SIGTERM)
    time.sleep(1)
    check('fake: env-socket unlinked on shutdown', not os.path.exists(SIG_SOCK2)
          and fake_env.poll() == 0)

    # 2f2. the peer-cred auth on the fake's unix control socket: the token gates
    # both transports, the kernel-vouched same-uid peer skips the handshake
    CRED_SOCK = '/tmp/inv_cred.socket'
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15591 + BASE),
                                   '--control-port', CRED_SOCK, '--control-token', 'sekrit'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_cred.log'), 'w'), stderr=subprocess.STDOUT))
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
    procs.append(subprocess.Popen([sys.executable, F, '--time', '12:00',
                                   '--listen', '127.0.0.1:%d' % (15580 + BASE), '--control-port', '15583'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_batt.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.8)
    ins = ctl('inspect', 15583)
    check('battery machine: full battery holds the noon surplus for the grid',
          '\nbattery   0 W, SoC 100.0 %' in ins, ins)
    ctl('set soc 95', 15583); ctl('set pv 3000', 15583); ctl('set load 1000', 15583)
    ins = ctl('inspect', 15583)
    check('battery machine: surplus charges with the grid margin', '\nbattery   1700 W' in ins, ins)
    ctl('set pv 6000', 15583); ctl('set load 500', 15583)
    ins = ctl('inspect', 15583)
    check('battery machine: charge clamp at the temperature-derated max', '\nbattery   2250 W' in ins, ins)
    ctl('set pv 0', 15583); ctl('set load 1000', 15583)
    ins = ctl('inspect', 15583)
    check('battery machine: deficit discharges', '\nbattery   -850 W' in ins, ins)
    ctl('set soc auto', 15583); ctl('set time 18:00', 15583)
    ins = ctl('inspect', 15583)
    check('battery machine: clock jump integrates the SoC (time-lapse)',
          'SoC 21.0 %' in ins and '\nbattery   -850 W' in ins, ins)
    ctl('set load 6000', 15583); ctl('set time 19:00', 15583)
    ins = ctl('inspect', 15583)
    check('battery machine: discharge stops at the 10 % reserve',
          'SoC 10.0 %' in ins and '\nbattery   0 W' in ins, ins)
    # 2g2. grid setpoint: the battery balances to hold the grid line
    ctl('set pv 3000', 15583); ctl('set load 1000', 15583); ctl('set soc 80', 15583)
    ctl('set grid 0', 15583)
    ins = ctl('inspect', 15583)
    check('grid setpoint: zero-export held by the battery', 'pv 3000 W, load 1000 W, grid 0 W' in ins
          and '\nbattery   2000 W' in ins and 'grid=0.0' in ins.split('\npinned', 1)[1], ins)
    r = read3(37113, 2, 15580)
    check('grid setpoint: the grid register serves the pinned 0',
          r[0] == 3 and struct.unpack('>i', r[2:6])[0] == 0, r.hex())
    ctl('clear grid', 15583)
    ins = ctl('inspect', 15583)
    check('grid setpoint: clear returns to the balance', 'grid 300 W' in ins
          and 'pv=3000.0; load=1000.0; soc=80.0' in ins.split('\npinned', 1)[1], ins)
    # 2g2b. mppt strings: string-1 = the east array (the morning peak), string-2 =
    # the west array (the afternoon peak); the setting enables/assigns them
    ctl('set pv auto', 15583); ctl('set load auto', 15583); ctl('set soc auto', 15583)
    ctl('set time 12:00', 15583)
    ctl('set mppt west', 15583)
    r = read3(32016, 4, 15580)     # the string-1 V/I, the string-2 V/I
    words = struct.unpack('>4H', r[2:10])
    check('mppt: west only = the east string dark, the west string live',
          words[0] == 0 and words[1] == 0 and words[2] > 0 and words[3] > 0, str(words))
    ins = ctl('inspect', 15583)
    check('mppt: inspect names the assignment', '\nmppt      west ' in ins, ins)
    ctl('set mppt both', 15583)
    r = read3(32016, 4, 15580)
    words = struct.unpack('>4H', r[2:10])
    check('mppt: both = both strings live (the oriented bells)', all(w > 0 for w in words), str(words))
    ctl('set mppt none', 15583)
    r = read3(32016, 4, 15580)
    check('mppt: none = PV 0, both strings dark',
          all(w == 0 for w in struct.unpack('>4H', r[2:10])), r.hex())
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'clear', 'mppt'],
                       capture_output=True, text=True)
    check('mppt: clear restores both', r.returncode == 0 and 'ok mppt=both' in r.stdout, r.stdout.strip())
    ins = ctl('inspect', 15583)
    pv_w = float(ins.split('pv ', 1)[1].split(' W', 1)[0])
    check('mppt: the day curve doubles the shoulder with both strings',
          4000 < pv_w < 5000, ins)
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
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'clear', 'grid-voltage'],
                       capture_output=True, text=True)
    check('grid voltage: clear restores the 230 V nominal', 'ok grid-voltage=230' in r.stdout, r.stdout.strip())
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
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'clear', 'grid-frequency'],
                       capture_output=True, text=True)
    check('grid frequency: clear restores 50 Hz', 'ok grid-frequency=50' in r.stdout, r.stdout.strip())

    # 2g2f. inspect: the pretty dump of everything
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'inspect'],
                       capture_output=True, text=True)
    check('inspect: the version, the profile, the machines, the overlay, the pins',
          r.returncode == 0 and r.stdout.startswith('ok inspect')
          and '\nversion   0.4.3' in r.stdout and '\nprofile   SUN2000' in r.stdout
          and '\nmppt      both' in r.stdout and '\npinned    ' in r.stdout
          and 'V nominal, 50 Hz nominal' in r.stdout, r.stdout.strip()[:120])

    # 2g2g. the fake's own metrics: the gated Prometheus endpoint + the bearer auth
    r = subprocess.run([sys.executable, F, '--dry-run'], capture_output=True, text=True)
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15901 + BASE),
                                   '--control-port', '15902', '--metrics-listen', '127.0.0.1:%d' % (15903 + BASE), '--metrics-server'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.2)
    status, body = None, None
    for _ in range(25):
        try:
            status, body = get('/metrics', 15903 + BASE)
            break
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    check('fake metrics: ungated (no --metrics-token) serves the gauges',
          status == 200 and 'fake_inverter_power_watts{kind="pv"} 4000' in body, str(status))
    subprocess.run([sys.executable, C, '--control-port', '15902', 'shutdown'], capture_output=True)
    time.sleep(0.8)
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15904 + BASE),
                                   '--control-port', '15905', '--metrics-listen', '127.0.0.1:%d' % (15906 + BASE),
                                   '--metrics-server', '--metrics-token', 'sekrit'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_metrics.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(1.2)
    status, body = None, None
    for _ in range(25):
        try:
            status, body = get('/metrics', 15906 + BASE)
            break
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    check('fake metrics: no token = 401 + the WWW-Authenticate challenge',
          status == 401, str(status))
    req = urllib.request.Request('http://127.0.0.1:%d/metrics' % (15906 + BASE))
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
    ins = ctl('inspect', 15583)
    tz = ctl('show timezone', 15583)
    check('timezone: the state machines default to UTC', tz.startswith('ok timezone=utc')
          and int(ins.split('\nnow', 1)[1].lstrip()[:2]) == time.gmtime().tm_hour % 24, ins)
    ctl('set timezone local', 15583)
    ins = ctl('inspect', 15583)
    tz = ctl('show timezone', 15583)
    check('timezone: local = the wall clock', tz.startswith('ok timezone=local')
          and int(ins.split('\nnow', 1)[1].lstrip()[:2]) == time.localtime().tm_hour % 24, ins)
    r = subprocess.run([sys.executable, C, '--control-port', '15583', 'clear', 'timezone'],
                       capture_output=True, text=True)
    check('timezone: clear restores UTC', 'ok timezone=utc' in r.stdout, r.stdout.strip())
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
          st.startswith('fail unknown scenario tea') and 'morning' in st, st)
    ctl('set pv 2200', 15583)
    st = ctl('show scenario', 15583)
    check('scenario: manual pin turns the state custom', st == 'ok scenario=custom', st)

    # 2g2. control 'shutdown' command = graceful stop without a signal
    fake_sd = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15578 + BASE), '--control-port', '15579'],
                               stdout=open(os.path.join(SCRATCH, 'scr_sd.log'), 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_sd)
    time.sleep(0.8)
    r = subprocess.run([sys.executable, C, '--control-port', '15579', 'shutdown'], capture_output=True, text=True)
    time.sleep(1)
    sd_log = open(os.path.join(SCRATCH, 'scr_sd.log')).read()
    check('control: shutdown stops the fake gracefully', r.returncode == 0
          and 'bye shutdown' in r.stdout and fake_sd.poll() == 0
          and 'shutdown: control received after' in sd_log
          and 'chaos hit(s)' in sd_log, r.stdout.strip() or r.stderr.strip())

    # 2g1. modbus-fake-cli.py: the Cisco-style session — silent set confirmations,
    # full show/status replies, [confirm] before shutdown
    K = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-cli.py')

    def cli(stdin, port=15571, audit=None):
        extra = ['--audit-log', audit] if audit else []
        return subprocess.run([sys.executable, K, '--control-port', str(port)] + extra,
                              input=stdin, capture_output=True, text=True, timeout=30)

    r = cli('set pv 3000\n')
    check('fake_cli: set prints only the confirmation', r.returncode == 0
          and r.stdout.rstrip() == '\nfake-inverter:15571 > % changed\n\nfake-inverter:15571 >', repr(r.stdout))
    check('fake_cli: set reply really carried no status tail',
          'load=' not in r.stdout and 'pinned' not in r.stdout, repr(r.stdout))
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('fake_cli: pinned value reaches /metrics', m.get('huawei_pv_generation_watts') == 3000,
          str(m.get('huawei_pv_generation_watts')))
    r = cli('shutdown\nn\n')
    check('fake_cli: shutdown refuses without confirming', r.returncode == 0
          and 'Proceed with shutdown? [confirm]' in r.stdout and '% Aborted.' in r.stdout, repr(r.stdout))
    ctl('show version', 15571)
    r = cli('show pv\ninspect\nquit\n')
    lines = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: show prints the bare value, inspect dumps the state', r.returncode == 0
          and '3000' in lines
          and any(l.startswith('power') and 'pv 3000 W' in l for l in lines)
          and any(l == 'pinned    pv=3000.0' for l in lines), repr(r.stdout))
    r = cli('help soc\nshow registers\ninspect\nquit\n')
    lines = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: the help rides bare, the registers table prints bare, inspect dumps',
          r.returncode == 0
          and any(l == 'soc - pin the state of charge (seeds the machine), or auto (values: %|auto)' for l in lines)
          and any(l == 'registers (49)' for l in lines) and 'pv-power' in ''.join(lines)
          and any('0.4.3' in l and 'version' in l for l in lines)
          and not any(l.startswith('% ok inspect') for l in lines), repr(r.stdout[:120]))

    # 2g3. the audit trail: the UTC stamp, the CLI/CTL prefix, the who-when-what,
    # ping/pong never logged, --no-audit-log switches it off
    AUD = os.path.join(SCRATCH, 'scr_audit_ctl.log')
    if os.path.exists(AUD):
        os.unlink(AUD)
    subprocess.run([sys.executable, C, '--control-port', '15571', '--audit-log', AUD, 'set', 'pv', '2600'],
                   capture_output=True, text=True)
    subprocess.run([sys.executable, C, '--control-port', '15571', '--no-audit-log', '--audit-log', AUD,
                    'show', 'pv'], capture_output=True, text=True)
    rows = open(AUD).read().strip().split('\n')
    check('audit: ctl logs CONNECT/DISCONNECT; the commands belong to the server trail',
          len(rows) == 2 and rows[0].split(' ')[1] == 'AUDIT' and rows[0].split(' ')[2] == 'application=INV'
          and rows[0].split(' ')[4] == 'instance=15571'
          and 'tag=cli' in rows[0] and 'type=connect' in rows[0]
          and 'type=disconnect' in rows[1], '\n'.join(rows))
    AUD2 = os.path.join(SCRATCH, 'scr_audit_cli.log')
    if os.path.exists(AUD2):
        os.unlink(AUD2)
    r = cli('show version\nping\nquit\n', audit=AUD2)
    cli_rows = open(AUD2).read()
    check('audit: cli logs the session + the local commands; the wire commands = the server trail',
          'application=INV tag=cli instance=15571 type=connect' in cli_rows and 'target=' in cli_rows
          and 'application=INV tag=cli' in cli_rows and 'type=command' in cli_rows and "cmd='quit' result=local" in cli_rows
          and 'type=disconnect' in cli_rows and "message='show" not in cli_rows
          and 'ping' not in cli_rows and 'pong' not in cli_rows, cli_rows)
    r = cli('inspect\nquit\n')
    rows = [l.strip() for l in r.stdout.replace('fake-inverter:15571 > ', '').splitlines() if l.strip()]
    check('fake_cli: inspect dumps the state bare', r.returncode == 0
          and len(rows) >= 10 and any(r2.startswith('power') for r2 in rows)
          and any(r2.startswith('pinned') for r2 in rows), repr(r.stdout))
    r = cli('set ?\n')
    check('fake_cli: ? lists the options for the position', r.returncode == 0
          and 'scenario' in r.stdout and 'max-kwp' in r.stdout
          and not any(line.startswith('ok') for line in r.stdout.splitlines()),
          repr(r.stdout[:400]))   # the token rows' prose carries the letters 'ok' — the check
                                  # anchors the ok-REPLY to the line head, not the substring
    p = subprocess.Popen([sys.executable, K, '--control-port', '15571'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, env={**os.environ, 'CLI_KEEPALIVE': '0.2'})
    time.sleep(1.2)          # the CLI idles, pinging every 0.2s
    p.stdin.write('show max-kwp\n')
    p.stdin.flush()
    time.sleep(0.4)
    p.stdin.write('quit\n')
    p.stdin.flush()
    out, _ = p.communicate(timeout=15)
    check('fake_cli: keepalive keeps an idle session alive (pongs absorbed)',
          p.returncode == 0 and 'fake-inverter:15571 > 6' in out and 'ok pong' not in out, repr(out[-120:]))
    fake_k = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15586 + BASE),
                               '--control-port', '15587'],
                              stdout=open(os.path.join(SCRATCH, 'scr_cli.log'), 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_k)
    time.sleep(0.8)
    r = cli('shutdown\n\n', 15587)
    time.sleep(1)
    check('fake_cli: RETURN at [confirm] stops the fake', r.returncode == 0
          and 'bye shutdown' in r.stdout and fake_k.poll() == 0, repr(r.stdout))

    def wait_ctl(port, tries=50):
        for _ in range(tries):
            if ctl('ping', port).startswith('ok pong'):   # the unreachable server degrades to a fail string — judge the reply
                return
            time.sleep(0.2)
        raise SystemExit('control on %d never came up' % port)

    # 2g3c. the reconnect: the server dies mid-session, the CLI retries
    # (--reconnect attempts, --reconnect-wait apart) and resumes the session
    fake_r = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15901 + BASE), '--control-port', '15902'],
                              stdout=open(os.path.join(SCRATCH, 'scr_recon.log'), 'w'), stderr=subprocess.STDOUT)
    procs.append(fake_r)
    wait_ctl(15902)   # the cold python start can outrun a fixed sleep
    p = subprocess.Popen([sys.executable, K, '--control-port', '15902', '--reconnect', '3',
                          '--reconnect-wait', '0.5'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    p.stdout.readline()   # the welcome's first line: the session is connected (the cold boot outruns any fixed sleep)
    fake_r.kill()
    fake_r.wait()
    time.sleep(0.3)
    fake_r2 = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15901 + BASE), '--control-port', '15902'],
                               stdout=open(os.path.join(SCRATCH, 'scr_recon2.log'), 'w'), stderr=subprocess.STDOUT)
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
    AUDD = os.path.join(SCRATCH, 'scr_audit_inv.log')
    if os.path.exists(AUDD):
        os.unlink(AUDD)
    inv = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15586 + BASE), '--control-port', '15587',
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
          'application=INV tag=daemon' in inv_rows and 'instance=' in inv_rows and 'type=start' in inv_rows
          and 'version=' in inv_rows and 'type=command' in inv_rows
          and 'peer=127.0.0.1' in inv_rows
          and "cmd='set soc 55' result=ok" in inv_rows and 'type=reload' in inv_rows
          and 'type=reset' in inv_rows and 'SIGUSR1' in inv_rows and 'type=shutdown' in inv_rows
          and 'SIGTERM' in inv_rows
          and 'ping' not in inv_rows, inv_rows)

    # 2g1b. clear command + scenario custom (server side, shared registry)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'clear', 'pv'], capture_output=True, text=True)
    check('control: clear releases the pin back to the simulation', r.returncode == 0
          and r.stdout.startswith('ok pv=auto '), r.stdout.strip())
    time.sleep(1.5)
    m = metrics_dict(get('/metrics', 19455 + BASE)[1])
    check('control: clear really releases (metrics back to the static base)',
          m.get('huawei_pv_generation_watts') == 4000, str(m.get('huawei_pv_generation_watts')))
    subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'pv', '2700'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'scenario', 'custom'],
                       capture_output=True, text=True)
    check('control: scenario custom releases pins + clock', r.returncode == 0
          and r.stdout.startswith('ok scenario=custom ') and 'pinned' not in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'clear', 'seed'], capture_output=True, text=True)
    check('control: clear seed restores the random RNG', r.returncode == 0
          and r.stdout.startswith('ok seed=random '), r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'clear', 'bogus'], capture_output=True, text=True)
    check('control: clear of an unknown setting is rejected', r.returncode == 0
          and r.stdout.startswith('% error: unknown setting bogus'), r.stdout.strip())

    # 2f. register-map profiles: the fake serves the SUN2000 layout from
    # profiles/profiles/sun2000.json by default; a custom profile remaps names onto
    # different registers (with per-entry type/scale) to emulate other devices
    import json as _json
    prof = os.path.join(SCRATCH, 'scr_prof_custom.json')
    _json.dump({'description': 'remapped device',
                'registers': [
                    {'name': 'pv-power', 'register': 40001, 'type': 'i32', 'scale': 1},
                    {'name': 'device-temperature', 'register': 33136, 'type': 'i16', 'scale': 10},
                    {'name': 'battery-soc', 'register': 40123, 'type': 'u16', 'scale': 1},
                ]}, open(prof, 'w'))

    fake_prof = subprocess.Popen([sys.executable, F, '--static', '--strict', '--listen', '127.0.0.1:%d' % (15592 + BASE),
                                  '--control-port', '0', '--profile', prof],
                                 stdout=open(os.path.join(SCRATCH, 'scr_prof.log'), 'w'), stderr=subprocess.STDOUT)
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
    stmap = os.path.join(SCRATCH, 'scr_prof_status.json')
    _json.dump({'mappings': [{'register': 'device-status',
                               'values': {'7': 'on-grid', '9': 'standby'}}],
                'registers': [{'name': 'device-status', 'register': 32089, 'type': 'u16', 'scale': 1,
                               'desc': 'running status code'}]}, open(stmap, 'w'))
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15595 + BASE),
                                   '--control-port', '0', '--profile', stmap],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    b = read3(32089, 1, 15595)
    check('profile: the status map serves the profile codes (7 = on-grid)',
          b[0] == 3 and struct.unpack('>H', b[2:4])[0] == 7, b.hex())

    badprof = os.path.join(SCRATCH, 'scr_prof_bad.json')
    _json.dump({'registers': [{'name': 'mystery-value', 'register': 32064, 'type': 'i32', 'scale': 1}]},
               open(badprof, 'w'))
    r = subprocess.run([sys.executable, F, '--dry-run', '--profile', badprof], capture_output=True, text=True)
    check('profile: a name the fake cannot simulate is accepted but never served', r.returncode == 0
          and 'mystery-value' in open(badprof).read(), r.stderr.strip()[-90:])

    fake_env = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15594 + BASE),
                                 '--control-port', '0'],
                                stdout=open(os.path.join(SCRATCH, 'scr_prof2.log'), 'w'), stderr=subprocess.STDOUT,
                                env={**os.environ, 'PROFILE': prof})
    procs.append(fake_env)
    time.sleep(0.8)
    r = read3(40001, 2, 15594)
    check('profile: PROFILE env selects the map', r[0] == 3 and struct.unpack('>i', r[2:6])[0] == 4000, r.hex())
    prof2 = os.path.join(SCRATCH, 'scr_prof_custom2.json')
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
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'profile', os.path.join(SCRATCH, 'scr_nope.json')],
                       capture_output=True, text=True)
    check('control: set profile of a bad file is rejected', r.returncode == 0
          and r.stdout.startswith('% error: '), r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'clear', 'profile'],
                       capture_output=True, text=True)
    check('control: clear profile restores the configured map (its description shows)', r.returncode == 0
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
    subprocess.run([sys.executable, C, '--control-port', '15571', 'clear', 'cloud'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'inspect'], capture_output=True, text=True)
    check('cloud: clear returns to a clear sky', '\ncloud     clear' in r.stdout, r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'cloud', 'winter'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'time', '12:00'],
                       capture_output=True, text=True)
    winter_pv = r.stdout
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'set', 'cloud', 'autumn'], capture_output=True, text=True)
    check('cloud: machines differ under the same seed', 'cloud=autumn(' in r.stdout
          and r.stdout != winter_pv, r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15571', 'reset'], capture_output=True)
    r = subprocess.run([sys.executable, C, '--control-port', '15571', 'inspect'], capture_output=True, text=True)
    check('cloud: reset releases the machine', '\ncloud     clear' in r.stdout, r.stdout.strip())

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
    check('show version: ok fake-inverter 0.4.3-<git>', r.returncode == 0
          and r.stdout.strip().startswith('ok fake-inverter 0.4.3-'), r.stdout.strip())
    r = subprocess.run([sys.executable, F, '--version'], capture_output=True, text=True)
    check('fake_inverter: --version reports 0.4.3-<short git>', r.returncode == 0
          and r.stdout.strip().startswith('0.4.3-') and len(r.stdout.strip()) > 10
          and r.stdout.strip() == '0.4.3-' + r.stdout.strip().split('-', 1)[1], r.stdout.strip())
    check('fake_ctl/fake_cli carry no exec bit (python runs the family)',
          not (os.stat(C).st_mode & 0o111) and not (os.stat(K).st_mode & 0o111))

    # the battery is always on (the flag retired): the status shows a real
    # SoC without any flag, the toggle answers err, the state force works
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '15639', '--listen', '127.0.0.1:%d' % (15638 + BASE),
                                   '--time', '12:00'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.8)
    r = subprocess.run([sys.executable, C, '--control-port', '15639', 'inspect'], capture_output=True, text=True)
    check('battery: always on (no flag)', r.returncode == 0 and 'SoC n/a' not in r.stdout
          and '\nbattery   ' in r.stdout, r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15639', 'set', 'battery', 'off'], capture_output=True, text=True)
    check('battery: the toggle is retired (err)', r.returncode == 0
          and r.stdout.startswith('% error:'), r.stdout.strip())
    r = subprocess.run([sys.executable, C, '--control-port', '15639', 'set', 'battery-state', 'charging'], capture_output=True, text=True)
    check('battery-state: forces the machine with the battery always on',
          r.returncode == 0 and r.stdout.startswith('ok battery-state=charging'), r.stdout.strip())
    subprocess.run([sys.executable, C, '--control-port', '15639', 'shutdown'], capture_output=True)

    # 2e. signals, mirroring the scraper/cache family: SIGHUP = env reload,
    # SIGUSR1 = scenario reset (pins + write overlay), SIGTERM = summary + exit 0.
    # The demo envs are ordinary env twins now: CHAOS applies at start
    # (flag > env), SIGHUP re-applies the layer.
    SIG_SOCK = os.path.join(SCRATCH, 'scr_sig_ctl.sock')
    fake_ctl = subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15574 + BASE),
                                 '--control-port', SIG_SOCK, '--allow-write'],
                                stdout=open(os.path.join(SCRATCH, 'scr_sig.log'), 'w'), stderr=subprocess.STDOUT,
                                env={**os.environ, 'CHAOS': '0.9', 'LOG_LEVEL': 'DEBUG'})
    procs.append(fake_ctl)
    time.sleep(0.8)
    check('signals: chaos from the env at start (flag > env)',
          'chaos     p=0.90' in subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'inspect'], capture_output=True, text=True).stdout)
    subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'set', 'chaos', 'off'], capture_output=True)
    # ^ chaos p=0.90 now rides the start: the wire turns it off so the raw
    # write below lands (the SIGHUP re-applies the env right after)
    s = socket.create_connection(('127.0.0.1', 15574), timeout=5)
    s.sendall(struct.pack('>HHHB', 5, 0, 6, 1) + struct.pack('>BHH', 6, 47415, 99))
    s.recv(64)
    s.close()
    subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'set', 'pv', '2500'], capture_output=True)
    os.kill(fake_ctl.pid, signal.SIGHUP)
    time.sleep(0.8)
    sig_status = subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'inspect'], capture_output=True, text=True).stdout
    check('signals: SIGHUP re-applies the env layer',
          'chaos     p=0.90' in sig_status and '\npinned    pv=2500.0' in sig_status, sig_status)
    os.kill(fake_ctl.pid, signal.SIGUSR1)
    time.sleep(0.8)
    sig_status = subprocess.run([sys.executable, C, '--control-port', SIG_SOCK, 'inspect'], capture_output=True, text=True).stdout
    check('signals: SIGUSR1 resets pins + write overlay', '\npinned    nothing' in sig_status
          and '1 overlay register(s) cleared' in open(os.path.join(SCRATCH, 'scr_sig.log')).read(), sig_status)
    os.kill(fake_ctl.pid, signal.SIGTERM)
    time.sleep(1)
    sig_log = open(os.path.join(SCRATCH, 'scr_sig.log')).read()
    check('signals: SIGTERM -> session summary + exit',
          fake_ctl.poll() == 0 and 'shutdown: SIGTERM received after' in sig_log
          and 'chaos hit(s)' in sig_log)
    check('signals: unix control socket unlinked on shutdown', not os.path.exists(SIG_SOCK))

    # 2e. fake dry-run: validate config, print effective settings, family exit codes
    r = subprocess.run([sys.executable, F, '--dry-run', '--static'], capture_output=True)
    check('fake dry-run: valid rc=0', r.returncode == 0
          and b'nothing was bound or connected' in r.stderr
          and b'peak PV 4500W' in r.stderr)
    r = subprocess.run([sys.executable, F, '--dry-run', '--unit', '300'], capture_output=True)
    check('fake dry-run: invalid rc=2, clean message', r.returncode == 2
          and b'unit must be 1..247' in r.stderr
          and b'Traceback' not in r.stderr)
    r = subprocess.run([sys.executable, F, '--dry-run', '--time', '25:00'], capture_output=True)
    check('fake dry-run: bad time rc=1', r.returncode == 1 and b'--time invalid' in r.stderr)


    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15572 + BASE),
                                   '--control-port', '15573', '--chaos', '0.4', '--seed', '42'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_chaos_fake.log'), 'w'), stderr=subprocess.STDOUT))
    write_ini(os.path.join(SCRATCH, 'scr_chaos.ini'))
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_chaos.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15572 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19456 + BASE)],
                                  stdout=open(os.path.join(SCRATCH, 'scr_chaos.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(6)
    status, body = get('/metrics', 19456 + BASE)
    m = metrics_dict(body)
    check('chaos: exporter stays up, errors counted', status == 200
          and m.get('scraper_modbus_errors_total', 0) > 0, str(m.get('scraper_modbus_errors_total')))
    ctl('set chaos off', 15573)
    time.sleep(2)
    status, body = get('/metrics', 19456 + BASE)
    m = metrics_dict(body)
    check('chaos off: recovery to up=1', status == 200 and m.get('scraper_up') == 1)
    check('chaos: zero tracebacks in fake + scraper logs',
          'Traceback' not in open(os.path.join(SCRATCH, 'scr_chaos.log')).read())
    check('chaos recovery: home = pv - batt - grid', m.get('huawei_home_consumption_watts') == 4300,
          str(m.get('huawei_home_consumption_watts')))

    # 3. sanity caps: max_kwp=2 -> 4000 W exceeds -> 503, then reload fixes it
    write_ini(os.path.join(SCRATCH, 'scr_cap.ini'), 'set max-kwp 2')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_cap.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19443 + BASE)],
                                  stdout=open(os.path.join(SCRATCH, 'scr_cap.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)
    status, _ = get('/metrics', 19443 + BASE)
    check('cap exceeded -> HTTP 503', status == 503)
    write_ini(os.path.join(SCRATCH, 'scr_cap.ini'), 'set max-kwp 6')
    pid = int(subprocess.run(['pgrep', '-f', 'modbus-scraper.py.*%d' % (19443 + BASE)], capture_output=True,
                             text=True).stdout.split()[0])
    os.kill(pid, signal.SIGHUP)
    time.sleep(1.5)
    status, body = get('/metrics', 19443 + BASE)
    m = metrics_dict(body)
    check('SIGHUP with raised cap -> 200 again', status == 200 and m.get('huawei_pv_generation_watts') == 4000)

    # 2b. graceful shutdown of the cap instance leaves a session summary in the log
    os.kill(pid, signal.SIGTERM)
    time.sleep(1)
    cap_log = open(os.path.join(SCRATCH, 'scr_cap.log')).read()
    check('shutdown: session summary (duration + poll errors)',
          'shutdown: SIGTERM received after ' in cap_log and 'poll errors)' in cap_log
          and 'SIGHUP: applied' in cap_log)

    # 3b. audit log: quiet by default, --log-access logs every request at INFO
    base_log = open(os.path.join(SCRATCH, 'scr_reg.log')).read()
    check('access log off by default', '"GET /metrics"' not in base_log)
    write_ini(os.path.join(SCRATCH, 'scr_audit.ini'), 'set log-access true')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_audit.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19444 + BASE)],
                                  stdout=open(os.path.join(SCRATCH, 'scr_audit.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)
    get('/metrics', 19444 + BASE)
    get('/nope', 19444 + BASE)
    time.sleep(0.3)
    audit = open(os.path.join(SCRATCH, 'scr_audit.log')).read()
    check('log-access: INFO line per request', audit.count('"GET /metrics" 200') >= 1
          and '"GET /nope" 404' in audit, audit.count('"GET') and 'found' or 'none')

    # 3c. bearer auth: disabled by default (earlier checks pass with no header); enforced when set
    write_ini(os.path.join(SCRATCH, 'scr_auth.ini'), 'set auth-token s3cret')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_auth.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19446 + BASE)],
                                  stdout=open(os.path.join(SCRATCH, 'scr_auth.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)
    status, _ = get('/metrics', 19446 + BASE)
    check('bearer auth: no token -> 401', status == 401)
    status, _ = get('/metrics', 19446, headers={'Authorization': 'Bearer wrong'})
    check('bearer auth: wrong token -> 401', status == 401)
    status, body = get('/metrics', 19446, headers={'Authorization': 'Bearer s3cret'})
    check('bearer auth: correct token -> 200', status == 200
          and 'huawei_pv_generation_watts 4000' in body)
    auth_log = open(os.path.join(SCRATCH, 'scr_auth.log')).read()
    check('401s always audited at WARNING (no --log-access needed)',
          auth_log.count('unauthorized 127.0.0.1 request for /metrics') >= 2
          and '"GET /metrics" 200' not in auth_log)

    # 3d. token from a file: reference: enforced, rotates on SIGHUP, error paths fail dry-run
    #     (the file must be owner-only 0600 — F12 in docs/AUDIT.md)
    with open(os.path.join(SCRATCH, 'scr_token.txt'), 'w') as fh:
        fh.write('first-token\n')
    os.chmod(os.path.join(SCRATCH, 'scr_token.txt'), 0o600)
    write_ini(os.path.join(SCRATCH, 'scr_tokfile.ini'), 'set auth-token file:' + os.path.join(SCRATCH, 'scr_token.txt'))
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_tokfile.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19447 + BASE)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    status, _ = get('/metrics', 19447, headers={'Authorization': 'Bearer first-token'})
    check('token file: works as bearer token', status == 200)
    with open(os.path.join(SCRATCH, 'scr_token.txt'), 'w') as fh:
        fh.write('second-token\n')
    pid = int(subprocess.run(['pgrep', '-f', 'modbus-scraper.py.*%d' % (19447 + BASE)], capture_output=True,
                             text=True).stdout.split()[0])
    os.kill(pid, signal.SIGHUP)
    time.sleep(1)
    status, _ = get('/metrics', 19447, headers={'Authorization': 'Bearer first-token'})
    status2, _ = get('/metrics', 19447, headers={'Authorization': 'Bearer second-token'})
    check('token file: SIGHUP rotates the token', status == 401 and status2 == 200)
    r = subprocess.run([sys.executable, P, '--dry-run', '--auth-token', 'file:/nonexistent/file'],
                       capture_output=True)
    check('token file: missing reference -> clean rc=1', r.returncode == 1 and b'cannot read' in r.stderr)
    lax = os.path.join(SCRATCH, 'scr_token_lax.txt')
    open(lax, 'w').write('laxsecret\n')                                 # the umask default (0644)
    r = subprocess.run([sys.executable, P, '--dry-run', '--auth-token', 'file:' + lax],
                       capture_output=True)
    check('token file: group/world-readable file refused (F12)',
          r.returncode == 1 and b'0600' in r.stderr and b'Traceback' not in r.stderr,
          repr(r.stderr[-140:]))

    # 3e. resource limits: --max-clients 503s the overflow, --client-timeout kicks idle keep-alives
    write_ini(os.path.join(SCRATCH, 'scr_lim.ini'), 'set max-clients 1\nset client-timeout 1\nset max-conn-per-ip 1')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_lim.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19448 + BASE)],
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
    write_ini(os.path.join(SCRATCH, 'scr_pip.ini'), 'set max-conn-per-ip 1\nset max-clients 0')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_pip.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19449 + BASE)],
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
    r = subprocess.run([sys.executable, P, '--dry-run', '--listen', '127.0.0.1:%d' % (19450 + BASE)],
                       capture_output=True)
    check('F13: the loopback default needs no token', r.returncode == 0, repr(r.stderr[-140:]))

    # 3f. arg/config sanitization: non-finite floats, host charset, malformed ini, token rules
    def dry(*flags):
        return subprocess.run([sys.executable, P, '--dry-run'] + list(flags), capture_output=True)

    r = dry('--timeout', 'inf')
    check('reject inf timeout', r.returncode == 2 and b'finite number' in r.stderr)
    nanprof = os.path.join(SCRATCH, 'scr_nan_scale_profile.json')
    _json.dump({'description': 'nan gain',
                'registers': [{'name': 'pv-power', 'register': 32064, 'type': 'i32', 'scale': float('nan')},
                              {'name': 'grid-power', 'register': 37113, 'type': 'i32'}]}, open(nanprof, 'w'))
    r = dry('--profile', nanprof)
    check('reject nan scale (the profile gain is the divisor now)', r.returncode == 1
          and b'finite number > 0' in r.stderr, r.stderr.decode('utf-8', 'replace')[:160])
    r = dry('--upstream', 'inva lid:5502')
    check('reject upstream host with spaces', r.returncode == 1 and b'invalid upstream host' in r.stderr)
    r = dry('--upstream', 'nonsense')
    check('reject upstream without a port', r.returncode == 1
          and b'HOST:PORT' in r.stderr and b'127.0.0.1' in r.stderr)
    r = dry('--upstream', ':99999')
    check('reject upstream port out of range', r.returncode == 1 and b'out of range' in r.stderr)
    r = dry('--modbus-unit', '248')
    check('reject unit id out of range', r.returncode == 2 and b'modbus-unit must be 1..247' in r.stderr)
    with open(os.path.join(SCRATCH, 'scr_broken.ini'), 'w') as fh:
        fh.write('# a set line missing its value\nset interval\n')
    r = dry('--config', os.path.join(SCRATCH, 'scr_broken.ini'))
    check('malformed config is fatal (no silent defaults)', r.returncode == 1
          and b'a set line needs a name and a value' in r.stderr)
    r = dry('--auth-token', 'bad token')
    check('reject token with whitespace', r.returncode == 1 and b'whitespace' in r.stderr)
    r = subprocess.run([sys.executable, P, '--dry-run', '--config', os.path.join(SCRATCH, 'scr_base.ini')],
                       capture_output=True, env=dict(os.environ, LOG_LEVEL='  info  '))
    check('log level is stripped/normalized', r.returncode == 0 and b'log level: INFO' in r.stderr)
    r = dry('--interval', '0.5', '--timeout', '2')
    check('timeout > interval warns but starts', r.returncode == 0 and b'back-to-back' in r.stderr)
    r = dry('--max-kwp', '-1')
    check('negative max_kwp rejected', r.returncode == 2 and b'max-kwp must be >= 0' in r.stderr)
    r = dry('--max-grid-kw', '-0.5')
    check('negative max_grid_kw rejected', r.returncode == 2 and b'max-grid-kw must be >= 0' in r.stderr)

    # 3g. hostile startup paths fail clean (no traceback), rc=1
    r = dry('--interval', '1e308')
    check('huge interval rejected by the row bound', r.returncode == 2 and b'interval must be 0..86400' in r.stderr)
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; Metrics(%r)'
                        % (os.path.join(REPO, 'scraper'), '/nonexistent/metrics.json')],
                       capture_output=True)
    check('missing metrics.json: clean rc=1', r.returncode == 1 and b'metrics spec /nonexistent/metrics.json not found' in r.stderr)
    with open(os.path.join(SCRATCH, 'bad_spec.json'), 'w') as fh:
        fh.write('{not json')
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; Metrics(%r)'
                        % (os.path.join(REPO, 'scraper'), os.path.join(SCRATCH, 'bad_spec.json'))],
                       capture_output=True)
    check('corrupt metrics.json: clean rc=1', r.returncode == 1 and b'not valid JSON' in r.stderr)

    # 3g+. the spec merge: lib/metrics.json (the built-in scraper_* block) under every spec
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; m = Metrics();'
                        'print(m.section_of("scraper_up"), m.section_of("huawei_pv_generation_watts"),'
                        'list(m.specs)[0], list(m.specs)[-1])'
                        % SCRAPER_DIR], capture_output=True)
    check('default spec: scraper_* merged in, the canonical metrics built-in, scraper last',
          r.returncode == 0 and b'scraper profile huawei_phase_a_voltage_volts scraper_cache_uptime_seconds' in r.stdout)
    with open(os.path.join(SCRATCH, 'scr_spec_noscraper.json'), 'w') as fh:
        _json.dump({'metrics': {'pv_generation_watts': {'profile': 'pv-power', 'help': 'Current PV power in watts.'}}}, fh)
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; m = Metrics(%r);'
                        'print("scraper_up" in m.specs, list(m.specs)[0], list(m.specs)[-1])'
                        % (SCRAPER_DIR, os.path.join(SCRATCH, 'scr_spec_noscraper.json'))], capture_output=True)
    check('custom spec without a scraper section: the built-ins merged in',
          r.returncode == 0 and b'True huawei_pv_generation_watts scraper_cache_uptime_seconds' in r.stdout)
    with open(os.path.join(SCRATCH, 'scr_spec_override.json'), 'w') as fh:
        _json.dump({'scraper': {'scraper_up': {'help': 'custom up help.'}}}, fh)
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; m = Metrics(%r);'
                        'print(m.help["scraper_up"], len(m.specs))'
                        % (SCRAPER_DIR, os.path.join(SCRATCH, 'scr_spec_override.json'))], capture_output=True)
    check('custom scraper section: its entries override the built-ins by name',
          r.returncode == 0 and b'custom up help. 13' in r.stdout, r.stdout.decode().strip())

    # 3h. the compute expressions: the bundled five compile (and the bad specs fail fast)
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r);'
                        'from lib.metrics import Metrics; m = Metrics();'
                        'print(len(m.compute), list(m.compute)[0], m.section_of("huawei_home_consumption_watts"),'
                        'len(m.inputs), m.inputs["batt"]["register"], m.inputs["batt"]["help"][:20])'
                        % SCRAPER_DIR], capture_output=True)
    check('default spec: the five compute metrics compiled, the declared vocabulary is the reserved four',
          r.returncode == 0 and b'5 huawei_grid_export_watts compute 4 battery-power Net battery power' in r.stdout,
          r.stdout.decode().strip())
    for case, spec, needle in (
            ('no-expr', {'metrics': {'custom_watts': {'help': 'A compute entry without an expr.'}}},
             b'has no "expr"'),
            ('unknown-input', {'metrics': {'custom_watts': {'expr': 'pv + mystery', 'help': 'x.'}}},
             b'unknown input(s) mystery'),
            ('bad-syntax', {'metrics': {'custom_watts': {'expr': 'pv +', 'help': 'x.'}}},
             b'cannot parse'),
            ('compute-chained', {'metrics': {'a_watts': {'expr': 'pv', 'help': 'x.'},
                                             'b_watts': {'expr': 'a_watts + 1', 'help': 'x.'}}},
             b'unknown input(s) a_watts'),
            ('both-fields', {'metrics': {'custom_watts': {'profile': 'pv-power', 'expr': 'pv', 'help': 'x.'}}},
             b'one or the other'),
            ('old-sections', {'profile': {'pv_generation_watts': {'profile': 'pv-power', 'help': 'x.'}}},
             b'live in one "metrics" tree'),
            ('inputs-unknown', {'inputs': {'mystery': {'help': 'not a real input.'}},
                                'metrics': {'custom_watts': {'expr': 'pv', 'help': 'x.'}}},
             b'declares \'mystery\', which is not an input'),
            ('inputs-no-help', {'inputs': {'pv': {}},
                                'metrics': {'custom_watts': {'expr': 'pv', 'help': 'x.'}}},
             b'declares no "help" string'),
            ('inputs-shape', {'inputs': [], 'metrics': {'custom_watts': {'expr': 'pv', 'help': 'x.'}}},
             b'the "inputs" section must be a non-empty object'),
            ('unknown-section', {'metrics': {'custom_watts': {'expr': 'pv', 'help': 'x.'}},
                                 'gauge': {'loose': {'help': 'x.'}}},
             b'unknown section'),
            ('rebind-canonical', {'metrics': {'panel_watts': {'profile': 'pv-power', 'help': 'x.'}}},
             b'bound twice')):
        path = os.path.join(SCRATCH, 'scr_spec_%s.json') % case
        with open(path, 'w') as fh:
            _json.dump(spec, fh)
        r = subprocess.run([sys.executable, '-c',
                            'import sys; sys.path.insert(0, %r);'
                            'from lib.metrics import Metrics; Metrics(%r)'
                            % (SCRAPER_DIR, path)], capture_output=True)
        check('compute spec %s: clean rc=1' % case, r.returncode == 1 and needle in r.stderr,
              r.stderr.decode().strip()[-90:])

    # 4. sanity-check controls against a scripted inverter (every F5 claim, live)
    regs = {}
    i32_regs(regs, 32064, 1000)   # PV
    i32_regs(regs, 37113, 0)      # grid
    i32_regs(regs, 37001, 0)      # battery
    regs[37004] = 650             # SoC 65.0 %
    for i, w in enumerate((0xCAFE, 1, 7, 4242)):
        regs[65000 + i] = w       # cache diagnostics block
    evil = EvilInverter(15542, regs)
    write_ini(os.path.join(SCRATCH, 'scr_evil.ini'), 'set log-level DEBUG')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_evil.ini'),
                                    '--upstream', '127.0.0.1:%d' % (15542 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19450 + BASE)],
                                  stdout=open(os.path.join(SCRATCH, 'scr_evil.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        try:
            status, body = get('/metrics', 19450 + BASE)
            m = metrics_dict(body)
            if status == 200 and m.get('huawei_pv_generation_watts') == 1000:
                break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.3)
    check('evil inverter: plausible baseline -> 200', status == 200 and m.get('huawei_pv_generation_watts') == 1000)
    check('evil inverter: diag present in fine mode', m.get('scraper_cache_device_up') == 1
          and m.get('scraper_cache_age_seconds') == 7 and m.get('scraper_cache_uptime_seconds') == 4242)
    regs[65000] = 0x1234          # lying magic: a device that is not a modbus-cache
    time.sleep(1.5)
    status, body = get('/metrics', 19450 + BASE)
    m = metrics_dict(body)
    check('diag magic mismatch: cache metrics stay absent', status == 200
          and not any('huawei_cache' in k for k in m), str([k for k in m if 'cache' in k]))
    regs[65000] = 0xCAFE
    time.sleep(1.5)
    status, body = get('/metrics', 19450 + BASE)
    m = metrics_dict(body)
    check('diag restored: cache metrics return', status == 200 and m.get('scraper_cache_device_up') == 1)
    i32_regs(regs, 32064, -1000)
    time.sleep(1.5)
    status, _ = get('/metrics', 19450 + BASE)
    check('negative PV rejected -> 503', status == 503)
    check('negative PV logged with raw-register forensics',
          'PV power is negative' in open(os.path.join(SCRATCH, 'scr_evil.log')).read())
    i32_regs(regs, 32064, 1000)
    i32_regs(regs, 37113, 7000)   # export 7 kW > 6 kWp cap, no battery discharge yet
    time.sleep(1.5)
    status, _ = get('/metrics', 19450 + BASE)
    check('export above PV cap -> 503', status == 503)
    i32_regs(regs, 37001, -6000)  # battery discharging 6 kW: 7 kW export is now plausible
    time.sleep(1.5)
    status, body = get('/metrics', 19450 + BASE)
    m = metrics_dict(body)
    check('battery discharge covers export -> 200', status == 200
          and m.get('huawei_battery_discharge_watts') == 6000 and m.get('huawei_battery_soc_percent') == 65)
    i32_regs(regs, 37001, 0)
    i32_regs(regs, 37113, 2000)   # import 2 kW with only 1 kW PV -> home = -1 kW
    time.sleep(1.5)
    status, _ = get('/metrics', 19450 + BASE)
    check('home < 0 rejected -> 503', status == 503)
    i32_regs(regs, 37113, -13000) # |grid| above the 12 kW line, import direction
    time.sleep(1.5)
    status, _ = get('/metrics', 19450 + BASE)
    check('grid cap enforced in both directions -> 503', status == 503)
    i32_regs(regs, 37113, -1500)
    time.sleep(1.5)
    status, body = get('/metrics', 19450 + BASE)
    m = metrics_dict(body)
    check('sane values accepted again -> 200', status == 200 and m.get('huawei_grid_net_watts') == -1500)

    # 4b. no tracebacks in any scenario log (exceptions must be one-line, handled)
    for name in ('scr_reg', 'scr_cap', 'scr_auth', 'scr_audit', 'scr_evil'):
        log = open(os.path.join(SCRATCH, '%s.log') % name).read()
        check('no tracebacks in %s.log' % name, 'Traceback' not in log)

    # 5. hostile inverter: every garbage mode must fail clean (up=0, one-line error) and recover
    evil.mode = 'garbage'
    time.sleep(1.5)
    status, body = get('/metrics', 19450 + BASE)
    m = metrics_dict(body)
    check('garbage reply: still HTTP 200 with last values, up=0',
          status == 200 and m.get('scraper_up') == 0 and m.get('huawei_pv_generation_watts') == 1000)
    check('garbage reply: error counter grew', m.get('scraper_modbus_errors_total', 0) >= 1)
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
    status, body = get('/metrics', 19450 + BASE)
    m = metrics_dict(body)
    check('all hostile modes: still alive, up=0, errors counted',
          status == 200 and m.get('scraper_up') == 0 and m.get('scraper_modbus_errors_total', 0) >= 7)
    evil_log = open(os.path.join(SCRATCH, 'scr_evil.log')).read()
    for needle in ('transaction id mismatch', 'connection closed by peer', 'timed out'):
        check('hostile mode logged cleanly: %s' % needle, needle in evil_log)
    evil.mode = 'fine'
    time.sleep(2)
    status, body = get('/metrics', 19450 + BASE)
    m = metrics_dict(body)
    check('hostile inverter gone sane: recovery -> up=1, fresh values',
          status == 200 and m.get('scraper_up') == 1 and m.get('huawei_pv_generation_watts') == 1000)
    check('no tracebacks in scr_evil.log after hostile modes',
          'Traceback' not in open(os.path.join(SCRATCH, 'scr_evil.log')).read())

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
    status, body = get('/metrics', 19450 + BASE)
    check('client garbage burst: still 200, metrics intact',
          status == 200 and 'huawei_pv_generation_watts 1000' in body)
    evil.stop()

    # 4. inverter dies: up=0, values stay (no 503), counter grows; recovery -> up=1
    for p in procs:
        if 'modbus-fake-inverter' in ' '.join(p.args):
            p.kill()
    time.sleep(1.5)
    status, body = get('/metrics', PORT_A)
    m = metrics_dict(body)
    check('inverter dead: up=0, still HTTP 200 with last values',
          status == 200 and m.get('scraper_up') == 0 and m.get('huawei_pv_generation_watts') == 4000)
    check('inverter dead: error counter grew', m.get('scraper_modbus_errors_total', 0) >= 1)
    procs.append(subprocess.Popen([sys.executable, F, '--control-port', '0', '--static', '--listen', '127.0.0.1:%d' % (PORT)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    status, body = get('/metrics', PORT_A)
    m = metrics_dict(body)
    check('inverter back: up=1', status == 200 and m.get('scraper_up') == 1)

    # 5. dry-run exit codes
    r = subprocess.run([sys.executable, P, '--dry-run', '--config', os.path.join(SCRATCH, 'scr_base.ini')], capture_output=True)
    check('dry-run valid config: rc=0, nothing bound', r.returncode == 0 and b'dry-run' in r.stderr)
    r = subprocess.run([sys.executable, P, '--dry-run', '--interval', '-1'], capture_output=True)
    check('dry-run invalid config: rc=2, clean message', r.returncode == 2 and b'interval must be 0..86400' in r.stderr)

    # 6. the scraper's control plane (the cache's shape, mirrored): the
    # signed wire (the full sha256 HMAC keyed by the token), the live
    # settings, poll now, the config re-read, the request reload, the Modbus
    # request restart, the shutdown
    import hashlib
    import hmac as _hmac

    STOK = 'stok'

    def wiremac(payload, token=STOK):
        return _hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def sctl(cmd, port, token=STOK, auth=True, unsigned=False, badmac=False):
        """One signed control exchange; asserts the reply mac every time."""
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        if auth and token:
            s.sendall((_json.dumps({'cmd': 'auth', 'token': token}) + '\n').encode())
            buf = b''
            while not buf.endswith(b'\n'):
                buf += s.recv(4096)
        if token and not unsigned:
            mac = 'ab' * 32 if badmac else wiremac(cmd, token)
            s.sendall((_json.dumps({'cmd': cmd, 'mac': mac}) + '\n').encode())
        else:
            s.sendall((_json.dumps({'cmd': cmd}) + '\n').encode())
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        # the first frame only: the daemon-exit bye can ride the same
        # segment on a shutdown (announce_exit)
        obj = _json.loads(buf.split(b'\n', 1)[0].decode('utf-8', 'replace'))
        if token and not unsigned and not badmac and obj.get('mac') is not None:
            want = wiremac('%s %s' % (obj.get('status'), obj.get('text', '')), token)
            assert obj.get('mac') == want, 'the reply mac does not verify: %r' % obj
        return '%s %s' % (obj.get('status', 'fail'), str(obj.get('text', '')))

    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19457 + BASE), '--interval', '1',
                                   '--control-port', '15597', '--control-token', STOK,
                                   '--audit-log', os.path.join(SCRATCH, 'scr_regtest_audit.log')],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.5)
    r = sctl('show version', 15597)
    check('scraper control: show version', r.startswith('ok modbus-scraper'), r[:80])
    r = sctl('set metric-prefix deye', 15597)
    check('scraper control: the prefix set re-builds the spec', r.startswith('ok metric-prefix=deye'), r[:80])
    m = {}
    for _ in range(10):
        m = metrics_dict(get('/metrics', 19457 + BASE)[1])
        if 'deye_pv_generation_watts' in m:
            break
        time.sleep(0.3)
    check('control: the exported names carry the live prefix', 'deye_pv_generation_watts' in m
          and 'huawei_pv_generation_watts' not in m, str(sorted(m))[:80])
    r = sctl('set metric-prefix 9bad', 15597)
    check('control: an invalid prefix refuses', r.startswith('fail invalid metric_prefix'), r[:80])
    r = sctl('clear metric-prefix', 15597)
    check('control: the prefix clear re-applies huawei', r.startswith('ok metric-prefix=huawei'), r[:80])
    m = {}
    for _ in range(10):
        m = metrics_dict(get('/metrics', 19457 + BASE)[1])
        if 'huawei_pv_generation_watts' in m:
            break
        time.sleep(0.3)
    check('control: the exported names carry huawei again', 'huawei_pv_generation_watts' in m
          and 'deye_pv_generation_watts' not in m, str(sorted(m))[:80])
    r = sctl('show version', 15597)
    check('scraper control: the wire is alive (show version)', r.startswith('ok modbus-scraper'), r[:80])
    r = sctl('show version', 15597, auth=False, unsigned=True)
    check('scraper control: the token server rejects the unauthenticated',
          r.startswith('fail authenticate first'), r[:80])
    r = sctl('show version', 15597, auth=True, unsigned=True)
    check('scraper control: an unsigned command over TCP is refused',
          r.startswith('fail unsigned command'), r[:80])
    r = sctl('show version', 15597, badmac=True)
    check('scraper control: a bad command mac is refused',
          r.startswith('fail the command mac does not verify'), r[:80])
    r = sctl('set interval 5', 15597)
    check('scraper control: set interval', r.startswith('ok interval=5.00s'), r[:80])
    r = sctl('show interval', 15597)
    check('scraper control: show interval', r.startswith('ok interval=5.00s'), r[:80])
    r = sctl('set interval 0', 15597)
    check('scraper control: a bad value refused', r.startswith('fail interval must be'), r[:80])
    r = sctl('help clear', 15597)
    check('scraper control: help <command> describes the row',
          r == 'ok restore a setting to its configured value (clear metrics interval, clear system log-level)', r)
    r = sctl('help request', 15597)
    check('scraper control: help <command node> lists the namespace (the ? shape)',
          r.startswith('ok ') and all(w in r for w in ('dump', 'reload', 'reload-config', 'restart', 'restore')), r[:200])
    r = sctl('help request reload', 15597)
    check('scraper control: help <deep command path> describes the row', r.startswith('ok save the live overrides'), r[:110])
    r = sctl('help bogus', 15597)
    check('scraper control: help <unknown topic> is the reworded two-space error',
          r == 'fail unknown command or setting bogus (try ?)', r)
    r = sctl('clear interval', 15597)
    check('scraper control: clear restores the configured value', r.startswith('ok interval='), r[:80])
    r = sctl('set log-access on', 15597)
    check('scraper control: set log-access', r.startswith('ok log-access=on'), r[:80])
    r = sctl('set max-conn-per-ip 2', 15597)
    check('scraper control: the per-IP cap live (the path form)', r.startswith('ok max-conn-per-ip=2'), r[:80])
    r = sctl('set max-conn-per-ip 9999', 15597)
    check('scraper control: the row bounds gate (min/max off the registry row)',
          r.startswith('fail max-conn-per-ip must be 0..4096'), r[:80])
    r = sctl('help modbus', 15597)
    words = [line.strip().split()[0] for line in r[3:].strip().splitlines()
             if line.strip() and not line.strip().startswith('[')]
    check('scraper control: the hierarchy node answers its namespace (the ? shape)',
          words == ['auth', 'grid-positive-import', 'offset', 'profile',
                    'timeout', 'unit', 'upstream'], r[:160])
    # 6b-2. the register map lives in the device profile: `set profile` swaps
    #        it live, a profile without the power registers rolls back
    r = sctl('show profile', 15597)
    check('scraper control: show profile names the resolved device profile',
          r.startswith('ok profile=') and 'sun2000.json' in r, r[:120])
    r = sctl('set profile sun2000', 15597)
    check('scraper control: set profile default re-resolves the bundled profile',
          r.startswith('ok profile=') and 'sun2000.json' in r, r[:120])
    badprof = os.path.join(SCRATCH, 'scr_no_pv_profile.json')
    _json.dump({'description': 'no power registers',
                'registers': [{'name': 'device-status', 'register': 32000, 'type': 'u16', 'scrape': True}]},
               open(badprof, 'w'))
    r = sctl('set profile %s' % badprof, 15597)
    check('scraper control: a profile without the power registers is refused (rollback)',
          r.startswith('fail ') and 'pv_generation_watts' in r, r[:160])
    r = sctl('set profile ' + os.path.join(SCRATCH, 'scr_no_such_profile.json'), 15597)
    check('scraper control: a missing profile file is refused', r.startswith('fail cannot read'), r[:120])
    r = sctl('clear profile', 15597)
    check('scraper control: clear profile restores the configured profile',
          r.startswith('ok profile=') and 'sun2000.json' in r, r[:120])
    r = sctl('show settings', 15597)
    check('scraper control: show settings is retired (fail)', r.startswith('fail'), r[:80])
    r = sctl('show knobs', 15597)
    check('scraper control: show knobs, the dictionary of the registry — flag, env twin, how it changes',
          r.startswith('ok knobs') and '--metric-prefix' in r and '$METRIC_PREFIX' in r
          and 'set metrics interval <value>' in r and ', secret' in r, r[:200])
    r = sctl('show inputs', 15597)
    check('scraper control: show inputs shows the declared inputs only, aligned, the help capped',
          r.startswith('ok inputs') and '[battery_net_watts]' in r
          and '[pv_generation_watts]' in r
          and 'battery  ' not in r
          and 'phase_a_voltage_volts' not in r, r[:240])
    r = sctl('show inputs-metrics', 15597)
    check('scraper control: show inputs metrics (the words forward to the dashed report) lists the exported metrics',
          r.startswith('ok inputs-metrics') and 'huawei_battery_charge_watts' in r and '[compute]' in r
          and '[profile]' in r and 'scraper_up  ' in r and 'gauge' not in r
          and list(r.splitlines()[1:]) == sorted(r.splitlines()[1:]), r[:240])
    r = sctl('show inputs-metrics', 15597)
    check('scraper control: the dashed spelling answers the same report',
          r.startswith('ok inputs-metrics') and 'huawei_battery_charge_watts' in r, r[:80])
    r = sctl('poll now', 15597)
    check('scraper control: poll now', r.startswith('ok poll now'), r[:80])
    r = sctl('request reload-config', 15597)
    check('scraper control: request reload-config', r.startswith('ok reloaded'), r[:80])
    # 6b-3. the secrets on the wire: startup-only (the dump-key treatment) —
    #       set/clear refuse on the wire, the show verb refuses them — a
    #       secret never renders
    r = sctl('show auth-token', 15597)
    check('scraper control: the auth token is a secret that never shows',
          r.startswith('fail auth-token is a secret'), r[:90])
    r = sctl('clear auth-token', 15597)
    check('scraper control: clear refuses a secret (startup-only)',
          r.startswith('fail restart required (startup-only knob)'), r[:90])
    r = sctl('show control-token', 15597)
    check('scraper control: the control token never shows', r.startswith('fail control-token is a secret'), r[:90])
    r = sctl('set auth-token bearer9', 15597)
    check('scraper control: the auth token is startup-only — the set refuses',
          r.startswith('fail restart required (startup-only knob)'), r[:90])
    st, _ = get('/metrics', 19457 + BASE)
    check('scraper control: the tokenless loopback endpoint keeps serving (the bind is the auth)',
          st == 200, str(st))
    r = sctl('set control-token ctok9', 15597)
    check('scraper control: the control token is startup-only — the set refuses',
          r.startswith('fail restart required (startup-only knob)'), r[:90])
    r = sctl('show version', 15597)
    check('scraper control: the configured control token still speaks (no live rotation)',
          r.startswith('ok modbus-scraper'), r[:80])
    r = sctl('show control-token', 15597)
    check('scraper control: the control token never renders back',
          r.startswith('fail control-token is a secret'), r[:90])
    # 6b-4. the state dump (settings by default — there are no cache words
    #       here): request dump writes 0600 + the integrity hash, the restore
    #       re-applies, the whole-daemon reload keeps the sets across the exec
    r = sctl('set dump-path ' + os.path.join(SCRATCH, 'scr_regtest_state.json'), 15597)
    check('scraper control: the dump path set live', r.startswith('ok dump-path=' + os.path.join(SCRATCH, 'scr_regtest_state.json')), r[:90])
    check('scraper control: the set dump path reply notes the unsealed dump (no key configured)',
          '(not sealed' in r and 'set dump-key' in r, r[:160])
    r = sctl('set interval 9', 15597)
    check('scraper control: the override before the dump', r.startswith('ok interval=9.00s'), r[:80])
    r = sctl('request dump', 15597)
    check('scraper control: request dump writes the live path', r.startswith('ok dumped 2 setting(s)'), r[:80])
    dumpst = os.stat(os.path.join(SCRATCH, 'scr_regtest_state.json'))
    check('scraper control: the state dump is 0600 (the F18 posture)', dumpst.st_mode & 0o777 == 0o600,
          oct(dumpst.st_mode & 0o777))
    raw = open(os.path.join(SCRATCH, 'scr_regtest_state.json')).read()
    check('scraper control: the dump carries the settings, never the secrets',
          '"metrics/interval"' in raw and 'sekrit' not in raw and 'ctok9' not in raw and 'bearer9' not in raw
          and 'auth-token' not in raw and 'control-token' not in raw, raw[:240])
    r = sctl('set interval 1', 15597)
    r = sctl('request restore', 15597)
    check('scraper control: the restore re-applies the dump (the secrets never ride it)',
          r.startswith('ok restored 2 setting(s)'), r[:80])
    r = sctl('show interval', 15597)
    check('scraper control: the restored override reads back', r == 'ok interval=9.00s', r[:80])
    r = sctl('request dump', 15597)   # a tamper check: edit the dump, the restore refuses
    tampered = open(os.path.join(SCRATCH, 'scr_regtest_state.json')).read().replace('9.0', '3.0')
    open(os.path.join(SCRATCH, 'scr_regtest_state.json'), 'w').write(tampered)
    r = sctl('request restore', 15597)
    check('scraper control: a tampered dump fails closed', r.startswith('fail restore failed')
          and 'integrity' in r, r[:120])
    r = sctl('clear dump-path', 15597)
    check('scraper control: the dump path clear back to off', r.startswith('ok dump-path=off'), r[:80])
    # 6b-4c. the dump-interval (the family knob, the cache's golden shape):
    #        the set/show/describe gate on the dump path, the dumper loop
    #        rewrites the file on the timer (the thread parks while off)
    r = sctl('show dump-interval', 15597)
    check('scraper control: show dump-interval without a path is a clean err',
          r.startswith('fail dump-interval needs a dump path'), r[:90])
    r = sctl('help dump-interval', 15597)
    check('scraper control: describe dump-interval without a path is a clean err',
          r.startswith('fail dump-interval needs a dump path'), r[:90])
    r = sctl('set dump-interval 5', 15597)
    check('scraper control: set dump-interval without a path is a clean err',
          r.startswith('fail dump-interval needs a dump path'), r[:90])
    r = sctl('set dump-path ' + os.path.join(SCRATCH, 'scr_regtest_state.json'), 15597)
    check('scraper control: the dump path set for the interval loop', r.startswith('ok dump-path='), r[:80])
    r = sctl('set dump-interval 2', 15597)
    check('scraper control: the interval set live', r.startswith('ok dump-interval=2.00s'), r[:80])
    r = sctl('show dump-interval', 15597)
    check('scraper control: the interval shows', r == 'ok dump-interval=2.00s', r[:80])
    m1 = os.path.getmtime(os.path.join(SCRATCH, 'scr_regtest_state.json'))
    time.sleep(2.6)
    m2 = os.path.getmtime(os.path.join(SCRATCH, 'scr_regtest_state.json'))
    check('scraper control: the dumper rewrote the file on the timer', m2 > m1, '%.2f -> %.2f' % (m1, m2))
    r = sctl('set dump-interval off', 15597)
    check('scraper control: the interval off again', r.startswith('ok dump-interval=off'), r[:80])
    r = sctl('clear dump-path', 15597)
    check('scraper control: the dump path clear back to off again', r.startswith('ok dump-path=off'), r[:80])
    # 6b-4b. the sealed dump (the DUMP_KEY env twin): the state rides encrypted,
    #        the restore fails closed without the key (the restart matrix lives
    #        in the inverter and cache regtests — the same open_dump gate)
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19466 + BASE), '--interval', '1',
                                   '--control-port', '15601', '--control-token', STOK,
                                   '--dump-path', os.path.join(SCRATCH, 'scr_regtest_state_sealed.json')],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  env={**os.environ, 'DUMP_KEY': 'scr-seal-key'}))
    time.sleep(1.5)
    r = sctl('show dump-key', 15601, token=STOK)
    check('scraper sealed dump: show dump-key is a secret — it never shows',
          r.startswith('fail dump-key is a secret'), r[:100])
    r = sctl('set dump-key other', 15601, token=STOK)
    check('scraper sealed dump: set dump-key answers the restart note',
          r.startswith('fail restart required (startup-only knob)'), r[:100])
    r = sctl('set interval 7', 15601, token=STOK)
    r = sctl('request dump', 15601, token=STOK)
    check('scraper sealed dump: request dump reports sealed (the DUMP_KEY env twin)',
          r.startswith('ok dumped 1 setting(s)') and '(sealed)' in r, r[:120])
    raw = open(os.path.join(SCRATCH, 'scr_regtest_state_sealed.json')).read()
    d = _json.loads(raw)
    check('scraper sealed dump: the envelope is sealed — the settings encrypted away',
          d.get('version') == 2 and d.get('cipher') == 'sha256-ctr' and 'settings' not in d
          and '"interval"' not in raw and d.get('box'), raw[:120])
    r = sctl('set interval 1', 15601, token=STOK)
    r = sctl('request restore', 15601, token=STOK)
    check('scraper sealed dump: the restore re-applies under the configured key',
          r.startswith('ok restored 1 setting(s)'), r[:120])
    # the file: reference form: the same material rides an owner-only file
    # (env DUMP_KEY=file:...), and an unreadable reference fails the start
    procs[-1].kill()
    time.sleep(0.4)
    scrkeyfile = os.path.join(SCRATCH, 'scr_regtest_dump_key_file')
    with open(scrkeyfile, 'w') as fh:
        fh.write('scr-seal-key\n')
    os.chmod(scrkeyfile, 0o600)
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19466 + BASE), '--interval', '1',
                                   '--control-port', '15601', '--control-token', STOK,
                                   '--dump-path', os.path.join(SCRATCH, 'scr_regtest_state_sealed.json')],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  env={**os.environ, 'DUMP_KEY': 'file:' + scrkeyfile}))
    time.sleep(1.5)
    r = sctl('request restore', 15601, token=STOK)
    check('scraper sealed dump: the file-reference key restores the sealed dump',
          r.startswith('ok restored 1 setting(s)'), r[:120])
    procs[-1].kill()
    time.sleep(0.4)
    p_nofile = subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                 '--listen', '127.0.0.1:%d' % (19466 + BASE), '--interval', '1',
                                 '--control-port', '15601', '--control-token', STOK,
                                 '--dump-path', os.path.join(SCRATCH, 'scr_regtest_state_sealed.json'),
                                 '--dump-key', 'file:/nonexistent/dump_key'],
                                stdout=open(os.path.join(SCRATCH, 'scr_regtest_keyfile_missing.log'), 'w'),
                                stderr=subprocess.STDOUT)
    line = ''
    for _ in range(80):
        line = open(os.path.join(SCRATCH, 'scr_regtest_keyfile_missing.log')).read()
        if 'cannot read dump-key' in line:
            break
        time.sleep(0.1)
    time.sleep(0.3)   # the SystemExit prints, then the process is gone
    check('scraper sealed dump: an unreadable key reference fails the start (fail fast, never plaintext)',
          'cannot read dump-key' in line and p_nofile.poll() is not None, line[-220:])
    p_nofile.poll()
    time.sleep(0.4)
    # a dump path without a key warns at start (the plaintext posture is a
    # choice, and now a visible one)
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19466 + BASE), '--interval', '1',
                                   '--control-port', '15601', '--control-token', STOK,
                                   '--dump-path', os.path.join(SCRATCH, 'scr_regtest_state_plain.json')],
                                  stdout=open(os.path.join(SCRATCH, 'scr_regtest_unsealed_warn.log'), 'w'),
                                  stderr=subprocess.STDOUT,
                                  env={**os.environ, 'DUMP_PATH': os.path.join(SCRATCH, 'scr_regtest_state_plain.json')}))
    line = ''
    for _ in range(80):
        line = open(os.path.join(SCRATCH, 'scr_regtest_unsealed_warn.log')).read()
        if 'is not sealed' in line:
            break
        time.sleep(0.1)
    check('scraper sealed dump: a dump path without a key warns unsealed at start',
          'is not sealed' in line and 'set dump-key' in line, line[-220:])
    procs[-1].kill()
    time.sleep(0.4)
    r = sctl('request restart', 15597)
    check('scraper control: the modbus session restart', r.startswith('ok modbus session dropped'), r[:80])
    r = sctl('inspect', 15597)
    check('scraper control: inspect', r.startswith('ok inspect\n') and 'version   modbus-scraper' in r, r[:120])
    aud = open(os.path.join(SCRATCH, 'scr_regtest_audit.log')).read()
    check('scraper control: the SCR audit trail with the wire mac',
          'application=SCR tag=daemon' in aud and 'type=command' in aud and "cmd='set interval 5' wire=h" in aud
          and 'result=ok' in aud, aud[-200:])

    # 6c. the read-only ops token: show allowed, everything that steers the
    #     daemon forbidden; both roles audited, both mac keys
    OPS_AUDIT = os.path.join(SCRATCH, 'scr_regtest_ops_audit.log')
    open(OPS_AUDIT, 'w').write('')
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19459 + BASE), '--interval', '1',
                                   '--control-port', '15598', '--control-token', STOK,
                                   '--control-ops-token', 'opssecret', '--audit-log', OPS_AUDIT],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.5)
    r = sctl('show version', 15598, token='opssecret')
    check('scraper control: the ops token reads (show version)', r.startswith('ok modbus-scraper'), r[:80])
    r = sctl('show knobs', 15598, token='opssecret')
    check('scraper control: the ops token reads (show knobs, a show verb)', r.startswith('ok knobs'), r[:80])
    r = sctl('set interval 5', 15598, token='opssecret')
    check('scraper control: the ops token cannot set', r.startswith('fail forbidden:') and 'admin' in r, r[:80])
    r = sctl('poll now', 15598, token='opssecret')
    check('scraper control: the ops token cannot poll now', r.startswith('fail forbidden:'), r[:80])
    r = sctl('request restart', 15598, token='opssecret')
    check('scraper control: the ops token cannot request restart', r.startswith('fail forbidden:'), r[:80])
    r = sctl('shutdown', 15598, token='opssecret')
    check('scraper control: the ops token cannot shutdown', r.startswith('fail forbidden:'), r[:80])
    r = sctl('request reload', 15598, token='opssecret')
    check('scraper control: the ops token cannot request reload', r.startswith('fail forbidden:'), r[:80])
    r = sctl('show version', 15598, token=STOK)
    check('scraper control: the admin token still steers the same server', r.startswith('ok modbus-scraper'),
          r[:80])
    opsaud = open(OPS_AUDIT).read()
    ops_lines = [l for l in opsaud.splitlines() if 'type=command' in l]
    check('scraper control: both roles audited on the ops server',
          any('role=ops' in l and "cmd='show version'" in l and 'result=ok' in l for l in ops_lines)
          and any('role=ops' in l and "cmd='shutdown'" in l and 'result=err' in l for l in ops_lines)
          and any('role=admin' in l and "cmd='show version'" in l and 'result=ok' in l for l in ops_lines),
          opsaud[-200:])
    r = subprocess.run([sys.executable, P, '--dry-run', '--upstream', '127.0.0.1:%d' % PORT,
                        '--listen', '127.0.0.1:%d' % (19459 + BASE), '--control-port', '15598', '--control-ops-token', 'x'],
                       capture_output=True, text=True, timeout=15)
    check('scraper control: an ops token without the admin token is a clean error',
          r.returncode != 0 and 'supplements' in (r.stderr + r.stdout) and 'Traceback' not in (r.stderr + r.stdout),
          (r.stderr + r.stdout)[-160:])
    r = subprocess.run([sys.executable, P, '--dry-run', '--upstream', '127.0.0.1:%d' % PORT,
                        '--listen', '127.0.0.1:%d' % (19459 + BASE), '--control-port', '15598', '--control-token', 'same',
                        '--control-ops-token', 'same'],
                       capture_output=True, text=True, timeout=15)
    check('scraper control: the ops token equal to the admin token is a clean error',
          r.returncode != 0 and 'differ' in (r.stderr + r.stdout) and 'Traceback' not in (r.stderr + r.stdout),
          (r.stderr + r.stdout)[-160:])

    # 6d. the whole-daemon reload (a dedicated daemon — the reload state
    #     lives beside ITS config): the overrides save, the process re-execs,
    #     the fresh daemon re-applies them once and consumes the file
    ini_r = os.path.join(SCRATCH, 'scr_reload.conf')
    open(ini_r, 'w').write('# the reload regtest config: the set grammar\nset timeout 2\n')
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19463 + BASE), '--interval', '1',
                                   '--config', ini_r, '--control-port', '15600', '--control-token', STOK,
                                   '--audit-log', os.path.join(SCRATCH, 'scr_regtest_reload_audit.log')],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.5)
    r = sctl('set interval 7', 15600)
    check('scraper reload: the override lands before the reload', r.startswith('ok interval=7.00s'), r[:90])
    r = sctl('request reload', 15600)
    check('scraper reload: the reply reports the saved override', r.startswith('ok reload: 1 override(s) saved'),
          r[:100])
    back = None
    for _ in range(100):     # the exec is fast: a connect in the drain window rides the dying daemon's
        try:                 # unsigned bye frame — only the freshly re-resolved status settles it
            back = sctl('show interval', 15600)
        except Exception:
            back = None
        if back is not None and back.startswith('ok interval=7.00s'):
            break
        time.sleep(0.1)
    check('scraper reload: the daemon came back with the override re-applied (above the config)',
          back is not None and back.startswith('ok interval=7.00s'),
          repr((back or '')[-200:]))
    gone = False
    for _ in range(100):     # the fresh daemon consumes the state at start — poll for the disappearance
        if not os.path.exists(ini_r + '.reload'):
            gone = True
            break
        time.sleep(0.1)
    check('scraper reload: the state file is consumed', gone, ini_r + '.reload')
    down = None
    for _ in range(100):
        try:
            down = sctl('shutdown', 15600)
        except Exception:
            down = None
        if down is not None and down.startswith('bye shutdown'):
            break
        time.sleep(0.1)
    check('scraper reload: the re-execed daemon still shuts down clean',
          down is not None and down.startswith('bye shutdown'), repr(down))

    r = sctl('shutdown', 15597)
    check('scraper control: shutdown', r.startswith('bye shutdown'), r[:80])
    time.sleep(0.6)

    # 7. scraper_ctl + scraper_cli (the family clients) + the F5 refusal
    CTLB = os.path.join(SCRAPER_DIR, 'bin', 'modbus-scraper-ctl.py')
    CLIB = os.path.join(SCRAPER_DIR, 'bin', 'modbus-scraper-cli.py')
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19457 + BASE), '--interval', '1',
                                   '--control-port', '15597', '--control-token', STOK],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.5)
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', '--control-token', STOK,
                        'show', 'version'], capture_output=True, text=True, timeout=15)
    check('scraper_ctl: one-shot show version', r.returncode == 0 and 'ok modbus-scraper' in r.stdout,
          repr(r.stdout[:80]) + repr(r.stderr[-80:]))
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', '--control-token', STOK],
                       input='set interval 5\nshow version\n', capture_output=True, text=True, timeout=15)
    check('scraper_ctl: a piped batch', r.returncode == 0 and 'ok interval=5.00s' in r.stdout
          and 'ok modbus-scraper' in r.stdout, repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, CLIB, '--control-port', '15597', '--control-token', STOK],
                       input='set log-access off\nshow metrics interval\nquit\n', capture_output=True, text=True, timeout=15)
    check('scraper_cli: the console session', r.returncode == 0 and '5' in r.stdout
          and 'Welcome to the modbus-scraper console' not in r.stdout, repr(r.stdout[:120]))
    stok_file = os.path.join(SCRATCH, 'scr_ctl_fuzz_token')
    open(stok_file, 'w').write(STOK + '\n')
    os.chmod(stok_file, 0o600)
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', 'show', 'version'],
                       capture_output=True, text=True, timeout=15,
                       env={**os.environ, 'CONTROL_TOKEN': 'file:' + stok_file})
    check('scraper_ctl: honors CONTROL_TOKEN=file:...', r.returncode == 0
          and 'ok modbus-scraper' in r.stdout, repr(r.stdout[:80]) + repr(r.stderr[-80:]))
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', '--control-token', STOK,
                        'show', 'modbus'], capture_output=True, text=True, timeout=15)
    words = [line.strip().split()[0] for line in r.stdout[3:].strip().splitlines()
             if line.strip() and not line.strip().startswith('[')]
    check('scraper_ctl: show modbus answers the live words (the grouped sections, the direct children)',
          r.returncode == 0 and words == ['auth', 'grid-positive-import', 'offset', 'profile', 'timeout', 'unit',
                                          'upstream'],
          repr(r.stdout[:240]))
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', '--control-token', STOK,
                        'show'], capture_output=True, text=True, timeout=15)
    words = [line.strip().split()[0] for line in r.stdout[3:].strip().splitlines()
             if line.strip() and not line.strip().startswith('[')]
    check("scraper_ctl: the bare show answers the root in the console's own words",
          r.returncode == 0 and words == ['audit', 'caps', 'config', 'connections', 'control', 'dump',
                                          'dump-interval', 'inputs', 'knobs', 'metrics', 'modbus', 'system',
                                          'version'],
          repr(r.stdout[:240]))
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', '--control-token', STOK,
                        'show', 'control', 'ops'], capture_output=True, text=True, timeout=15)
    check('scraper_ctl: the node walk answers the intermediate node', r.returncode == 0
          and r.stdout.startswith('ok') and 'verbs the read-only ops role' in r.stdout, repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, CLIB, '--control-port', '15597'],
                       input='show metrics interval\nquit\n', capture_output=True, text=True, timeout=15,
                       env={**os.environ, 'CONTROL_TOKEN': 'file:' + stok_file})
    check('scraper_cli: honors CONTROL_TOKEN=file:...', r.returncode == 0 and '5' in r.stdout,
          repr(r.stdout[:120]))
    r = subprocess.run([sys.executable, P, '--dry-run', '--control-port', '15596'], capture_output=True,
                       text=True, timeout=15)
    check('scraper control: a TCP control port without a token refuses to start (F5)',
          r.returncode == 1 and 'TCP control port' in r.stderr and 'Traceback' not in r.stderr,
          r.stderr[-160:])
    # the live rebind (`set control port`): the listener swaps by identity,
    # the old port closes, clear restores the configured target
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', '--control-token', STOK,
                        'set', 'control-port', '15603'], capture_output=True, text=True, timeout=15)
    check('scraper control: the control rebinds live', r.stdout.startswith('ok control-port=127.0.0.1:%d' % (15603 + BASE)),
          repr(r.stdout[:90]))
    old_gone = False
    try:
        socket.create_connection(('127.0.0.1', 15597), timeout=1).close()
    except OSError:
        old_gone = True
    check('scraper control: the old port is closed', old_gone)
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15603', '--control-token', STOK,
                        'show', 'version'], capture_output=True, text=True, timeout=15)
    check('scraper control: the new port speaks', r.returncode == 0 and r.stdout.startswith('ok modbus-scraper'),
          repr(r.stdout[:60]) + repr(r.stderr[-80:]))
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15603', '--control-token', STOK,
                        'clear', 'control-port'], capture_output=True, text=True, timeout=15)
    check('scraper control: clear restores the configured target',
          r.stdout.startswith('ok control-port=127.0.0.1:%d' % (15597 + BASE)), repr(r.stdout[:90]))
    r = subprocess.run([sys.executable, CTLB, '--control-port', '15597', '--control-token', STOK,
                        'show', 'version'], capture_output=True, text=True, timeout=15)
    check('scraper control: the restored target speaks', r.returncode == 0 and r.stdout.startswith('ok modbus-scraper'),
          repr(r.stdout[:60]) + repr(r.stderr[-80:]))

    # 7b. the audit family's one shape on the SCR: the bounds, the daily knob,
    #     the write-back, the env twins (the bounds' one home: common/runtime/audit.py)
    def sctl(*words, port=15597):
        return subprocess.run([sys.executable, CTLB, '--control-port', str(port), '--control-token', STOK]
                              + list(words), capture_output=True, text=True, timeout=15).stdout.strip()

    r = sctl('set', 'audit-files', '0')
    check('scraper audit: the files bound refuses low (the family text)',
          'must be 1..100 backups' in r, repr(r[:130]))
    r = sctl('set', 'audit-files', '101')
    check('scraper audit: the files bound refuses high', 'must be 1..100 backups' in r, repr(r[:130]))
    r = sctl('set', 'audit-max-mb', '-1')
    check('scraper audit: the max-size bound refuses', 'must be 0..1048576 MB' in r, repr(r[:130]))
    r = sctl('set', 'audit-daily', 'on')
    check('scraper audit-daily: the daily trigger switches on', r.startswith('ok audit-daily=on'), repr(r[:110]))
    check('scraper audit-daily: show audit rotate daily answers on',
          sctl('show', 'audit-daily') == 'ok audit-daily=on')
    r = sctl('clear', 'audit-daily')
    check('scraper audit-daily: the daily trigger unsets to the configured off',
          r.startswith('ok audit-daily=off'), repr(r[:110]))
    r = sctl('set', 'audit-files', '7')
    check('scraper audit: the live set writes the config back (the fresh show config)',
          'set audit rotate files 7' in sctl('show', 'config'), sctl('show', 'config')[:80])
    r = sctl('clear', 'no-audit-log')
    check('scraper audit: the live bool rows clear (the defaults loop)',
          r.startswith('ok no-audit-log='), repr(r[:110]))
    env = dict(os.environ, AUDIT_MAX_MB='77', AUDIT_DAILY='1', AUDIT_FILES='9')
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19471 + BASE), '--interval', '1',
                                   '--control-port', '15609', '--control-token', STOK],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env))
    time.sleep(1.5)
    check('scraper audit: the env twins drive the rotation',
          sctl('show', 'audit-max-mb', port=15609) == 'ok audit-max-mb=77'
          and sctl('show', 'audit-daily', port=15609) == 'ok audit-daily=on'
          and sctl('show', 'audit-files', port=15609) == 'ok audit-files=9',
          ' | '.join(sctl('show', 'audit', 'rotate', w, port=15609) for w in ('max-size', 'daily', 'files')))
    env = dict(os.environ, AUDIT_FILES='0')
    r = subprocess.run([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT, '--dry-run',
                        '--control-port', '0'], capture_output=True, text=True, env=env, timeout=15)
    check('scraper audit: $AUDIT_FILES=0 refuses at start (the bound, the clean one-liner)',
          r.returncode == 1 and 'must be 1..100' in r.stdout + r.stderr
          and 'Traceback' not in r.stdout + r.stderr, (r.stdout + r.stderr)[-160:])

    # the group-accessible unix socket (--control-socket-group): 0660,
    # and the live set re-modes it
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19458 + BASE), '--interval', '1',
                                   '--control-socket-group'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.5)
    gsock = '/tmp/modbus-scraper-19458.socket'
    check('scraper control: --control-socket-group chmods the socket 0660',
          os.stat(gsock).st_mode & 0o777 == 0o660, oct(os.stat(gsock).st_mode))
    r = subprocess.run([sys.executable, CTLB, 'show', 'version'], capture_output=True, text=True,
                       timeout=15, env={**os.environ, 'CTL': gsock})
    check('scraper control: the group socket speaks (the owner, us)', r.returncode == 0
          and 'ok modbus-scraper' in r.stdout, repr(r.stdout[-120:]))
    r = subprocess.run([sys.executable, CTLB, 'set', 'control-socket-group', 'off'],
                       capture_output=True, text=True, timeout=15, env={**os.environ, 'CTL': gsock})
    check('scraper control: set control socket-group off re-modes the live socket 0600',
          r.stdout.startswith('ok control-socket-group=off') and os.stat(gsock).st_mode & 0o777 == 0o600,
          repr(r.stdout[:120]) + ' ' + oct(os.stat(gsock).st_mode))
    r = subprocess.run([sys.executable, CTLB, 'set', 'control-port', '15603'],
                       capture_output=True, text=True, timeout=15, env={**os.environ, 'CTL': gsock})
    check('scraper control: a tokenless TCP rebind refuses on the live wire (F5)',
          r.stdout.startswith('% error: control-port cannot serve TCP without a token'), repr(r.stdout[:120]))
    # 7b. the suite auth: an authed fake + an authed scraper — the good key
    #     polls, the wrong key fails the connector (ERR), the live `set`
    #     drops the session; then a plain fake under an authed scraper
    #     fails the same way (the peer must speak the scheme)
    SKEY = 'scr-suite-key-16chars!'
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15910 + BASE),
                                   '--control-port', '0', '--modbus-auth', 'suite', '--auth-key', SKEY],
                                  stdout=open(os.path.join(SCRATCH, 'scr_auth_fake.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15910 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19461 + BASE), '--interval', '1',
                                   '--control-port', '0', '--modbus-auth', 'suite', '--auth-key', SKEY],
                                  stdout=open(os.path.join(SCRATCH, 'scr_auth.log'), 'w'), stderr=subprocess.STDOUT))
    for _ in range(30):
        try:
            status, m = wait_metrics(19461, want='scraper_up')
            if m.get('scraper_up') == 1:
                break
        except Exception:
            pass
        time.sleep(0.3)
    status, m = wait_metrics(19461 + BASE)
    check('suite auth: the matching key polls (scraper_up 1)', m.get('scraper_up') == 1,
          str({k: m.get(k) for k in ('scraper_up', 'scraper_modbus_errors_total')}))
    check('suite auth: the start log names the scheme', 'modbus auth suite' in open(os.path.join(SCRATCH, 'scr_auth.log')).read())
    # the wrong key: the handshake is refused — the connector fails, the poll stays down
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15910 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19462 + BASE), '--interval', '1',
                                   '--control-port', '0', '--modbus-auth', 'suite',
                                   '--auth-key', 'wrong-key-16chars00'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_auth_wrong.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(3.0)
    status, m = wait_metrics(19462, want='scraper_up')
    check('suite auth: the wrong key keeps the connector failed (scraper_up 0)',
          m.get('scraper_up') == 0, str({k: m.get(k) for k in ('scraper_up', 'scraper_modbus_errors_total')}))
    check('suite auth: the refusals pile up as poll errors', m.get('scraper_modbus_errors_total', 0) > 0,
          str(m.get('scraper_modbus_errors_total')))
    # the right key: a spawned instance (the key is startup-only) — the set
    # refuses on the wire, a fresh start applies the configured key
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15910 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19468 + BASE), '--interval', '1',
                                   '--control-port', '19469', '--control-token', 'ctok-a',
                                   '--modbus-auth', 'suite', '--auth-key', 'wrong-key-16chars00'],
                                  stdout=open(os.path.join(SCRATCH, 'scr_auth_rot.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(2.0)
    r = subprocess.run([sys.executable, CTLB, '--control-port', '19469', '--control-token', 'ctok-a',
                        'set', 'auth-key', SKEY], capture_output=True, text=True, timeout=15)
    check('suite auth: startup-only — the key set refuses',
          r.stdout.startswith('% error: restart required (startup-only knob)'), r.stdout[:120])
    procs[-1].terminate()
    procs[-1].wait(timeout=10)
    time.sleep(0.5)
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15910 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19468 + BASE), '--interval', '1',
                                   '--control-port', '19469', '--control-token', 'ctok-a',
                                   '--modbus-auth', 'suite', '--auth-key', SKEY],
                                  stdout=open(os.path.join(SCRATCH, 'scr_auth_rot.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(2.0)
    for _ in range(30):
        try:
            status, m = wait_metrics(19468, want='scraper_up')
            if m.get('scraper_up') == 1:
                break
        except Exception:
            pass
        time.sleep(0.3)
    status, m = wait_metrics(19468, want='scraper_up')
    check('suite auth: the configured key polls (a fresh start applies it)', m.get('scraper_up') == 1,
          str(m.get('scraper_up')))
    r = subprocess.run([sys.executable, P, '--dry-run', '--modbus-auth', 'bogus'], capture_output=True,
                       text=True, timeout=15)
    check('suite auth: a bogus scheme fails the config fast',
          r.returncode == 1 and "use 'suite'" in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--dry-run', '--modbus-auth', 'suite'], capture_output=True,
                       text=True, timeout=15)
    check('suite auth: suite without a key fails the config fast',
          r.returncode == 1 and 'needs a key' in r.stderr, r.stderr[-160:])
    r = subprocess.run([sys.executable, P, '--dry-run', '--modbus-auth', 'suite', '--auth-key', 'short'],
                       capture_output=True, text=True, timeout=15)
    check('suite auth: a short key fails the config fast',
          r.returncode == 1 and 'at least 16 characters' in r.stderr, r.stderr[-160:])
    # an authed scraper against a PLAIN fake: the handshake gets a Modbus
    # exception frame back — the connector fails there too
    procs.append(subprocess.Popen([sys.executable, F, '--static', '--listen', '127.0.0.1:%d' % (15911 + BASE),
                                   '--control-port', '0'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.7)
    procs.append(subprocess.Popen([sys.executable, P, '--upstream', '127.0.0.1:%d' % (15911 + BASE),
                                   '--listen', '127.0.0.1:%d' % (19464 + BASE), '--interval', '1',
                                   '--control-port', '0', '--modbus-auth', 'suite', '--auth-key', SKEY],
                                  stdout=open(os.path.join(SCRATCH, 'scr_auth_plain.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(3.0)
    status, m = wait_metrics(19464, want='scraper_up')
    check('suite auth: an authed client of a plain server fails (scraper_up 0)',
          m.get('scraper_up') == 0, str(m.get('scraper_up')))
    check('suite auth: the plain-server failures pile up too', m.get('scraper_modbus_errors_total', 0) > 0,
          str(m.get('scraper_modbus_errors_total')))

    # 9. the metrics ACL: the cache's acl/connect reading on the /metrics
    # listener — the accept-time IP gate (the inline grammar + the file: chain)
    r = subprocess.run([sys.executable, P, '--dry-run',
                        '--metrics-acl', 'file:' + os.path.join(REPO, 'extras', 'examples', 'acl-ip-prefix.json')],
                       capture_output=True, text=True, timeout=15)
    check('metrics acl: the shipped ip-prefix example loads (dry-run rc 0)',
          r.returncode == 0 and 'dry-run: configuration is valid' in r.stderr, r.stderr[-100:])
    r = subprocess.run([sys.executable, P, '--dry-run', '--metrics-acl', 'file:/nonexistent/acl.json'],
                       capture_output=True, text=True, timeout=15)
    check('metrics acl: a missing acl file refuses the start (rc 1, clean)',
          r.returncode == 1 and 'cannot read acl file' in r.stderr, r.stderr[-100:])
    r = subprocess.run([sys.executable, P, '--dry-run', '--metrics-acl', '10.0.0.0/999'],
                       capture_output=True, text=True, timeout=15)
    check('metrics acl: a bad inline entry refuses the start (rc 1, clean)',
          r.returncode == 1 and 'bad ACL entry' in r.stderr, r.stderr[-100:])

    ACLGATE = os.path.join(SCRATCH, 'scr_acl_gate.json')
    with open(ACLGATE, 'w') as f:
        _json.dump({'desc': 'the lab gate', 'type': 'ip-prefix', 'rules': [
            {'type': 'deny', 'prefix': 'any'},
            {'type': 'allow', 'prefix': '127.0.0.1', 'desc': 'the loopback lab'},
        ]}, f)
    write_ini(os.path.join(SCRATCH, 'scr_acl.ini'), 'set control-port /tmp/scr_acl_ctl.socket')
    procs.append(subprocess.Popen([sys.executable, P, '--config', os.path.join(SCRATCH, 'scr_acl.ini'),
                                   '--upstream', '127.0.0.1:%d' % PORT,
                                   '--listen', '127.0.0.1:%d' % (19465 + BASE)],
                                  stdout=open(os.path.join(SCRATCH, 'scr_acl.log'), 'w'), stderr=subprocess.STDOUT))
    time.sleep(2)

    def acl_ctl(cmd):
        # the unix-socket control transport (no token: the filesystem is the auth)
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(5)
        s.connect('/tmp/scr_acl_ctl.socket')
        s.sendall((_json.dumps({'cmd': cmd}) + '\n').encode())
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        obj = _json.loads(buf.split(b'\n', 1)[0].decode('utf-8', 'replace'))
        return '%s %s' % (obj.get('status', 'fail'), str(obj.get('text', '')))

    def acl_raw():
        # one GET over a raw socket, the full reply or the close: the
        # accept-check refusal closes without a reply — a reset on some stacks
        try:
            s = socket.create_connection(('127.0.0.1', 19465), timeout=5)
            s.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n')
            buf = b''
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            s.close()
            return buf
        except (ConnectionResetError, BrokenPipeError):
            return b''

    check('metrics acl: any serves (the default)', acl_raw().startswith(b'HTTP/1.1 200'),
          acl_raw().split(b'\r\n')[0].decode()[:60])
    r = acl_ctl('set metrics-acl none')
    check('metrics acl: set none answers ok', r.startswith('ok metrics-acl=none'), r[:80])
    check('metrics acl: none closes the client without a reply', acl_raw() == b'',
          repr(acl_raw()[:40]))
    r = acl_ctl('show metrics-acl')
    check('metrics acl: the none show', r == 'ok metrics-acl=none', r[:60])
    r = acl_ctl('show metrics-acl-table')
    check('metrics acl: none spells the deny-any chain', r == 'ok metrics-acl-table\ndeny 0.0.0.0/0', r[:80])
    r = acl_ctl('set metrics-acl table')
    check('metrics acl: the show word is not a value (the pointer to the report)',
          r.startswith('fail') and 'show metrics-acl-table' in r, r[:120])
    r = acl_ctl('set metrics-acl 127.0.0.1')
    check('metrics acl: the whitelist set canonicalizes', r.startswith('ok metrics-acl=127.0.0.1/32'), r[:80])
    check('metrics acl: the whitelist serves the lab', acl_raw().startswith(b'HTTP/1.1 200'))
    r = acl_ctl('show metrics-acl-table')
    check('metrics acl: the whitelist table', r == 'ok metrics-acl-table\ndeny 0.0.0.0/0\nallow 127.0.0.1/32', r[:80])
    r = acl_ctl('set metrics-acl file:' + ACLGATE)
    check('metrics acl: the file gate loads', r.startswith('ok metrics-acl=file:%s' % ACLGATE), r[:100])
    r = acl_ctl('show metrics-acl')
    check('metrics acl: the file spelling shows', r == 'ok metrics-acl=file:%s' % ACLGATE, r[:80])
    r = acl_ctl('show metrics-acl-table')
    check('metrics acl: the file gate renders its own rules',
          r == 'ok metrics-acl-table\n% the lab gate\ndeny 0.0.0.0/0\nallow 127.0.0.1 # the loopback lab', r[:160])
    check('metrics acl: the file gate serves the lab', acl_raw().startswith(b'HTTP/1.1 200'))
    with open(ACLGATE, 'w') as f:
        _json.dump({'type': 'ip-prefix', 'rules': [{'type': 'allow', 'prefix': '127.0.0.1/8'}]}, f)
    r = acl_ctl('set metrics-acl file:' + ACLGATE)
    check('metrics acl: a bad file answers err with the old gate standing',
          r.startswith('fail') and 'spell the network' in r and acl_raw().startswith(b'HTTP/1.1 200'), r[:140])
    r = acl_ctl('clear metrics-acl')
    check('metrics acl: clear restores the configured value', r.startswith('ok metrics-acl=any'), r[:80])
    check('metrics acl: any serves again', acl_raw().startswith(b'HTTP/1.1 200'))

    # the accept ladder's order: the ACL first, then the caps — the cap
    # refusal is only ever answered to a peer the ACL admitted
    r = acl_ctl('set max-clients 1')
    check('metrics acl order: the cap sets live', r.startswith('ok'), r[:80])
    hold = socket.create_connection(('127.0.0.1', 19465), timeout=5)
    hold.sendall(b'GET /metrics HTTP/1.1\r\nHost: t\r\n')   # the partial request parks the handler thread (the exposition handler has no timeout)
    time.sleep(0.5)
    check('metrics acl order: the admitted peer past the cap gets the 503',
          acl_raw().startswith(b'HTTP/1.1 503'), repr(acl_raw()[:24]))
    r = acl_ctl('set metrics-acl none')
    check('metrics acl order: none sets past the full cap', r.startswith('ok metrics-acl=none'), r[:80])
    check('metrics acl order: the off-ACL peer closes silently past the cap (the ACL first, then the caps)',
          acl_raw() == b'', repr(acl_raw()[:40]))
    hold.close()
    time.sleep(0.3)
    acl_ctl('clear metrics-acl')
    r = acl_ctl('clear max-clients')
    check('metrics acl order: the cap unsets back', r.startswith('ok'), r[:80])
    check('metrics acl order: any serves after the ladder', acl_raw().startswith(b'HTTP/1.1 200'))
    os.remove(ACLGATE)

    for tool, title in ((P, 'MODBUS-SCRAPER'), (CTLB, 'MODBUS-SCRAPER-CTL'), (CLIB, 'MODBUS-SCRAPER-CLI')):
        r = subprocess.run([sys.executable, tool, '--man'], capture_output=True, text=True, timeout=30)
        check('--man: %s prints the page' % os.path.basename(tool),
              r.returncode == 0 and r.stdout.startswith('.TH %s 1' % title), r.stdout[:40] or r.stderr[-80:])
except QuickDone:
    pass
except KeyboardInterrupt:
    print()
    print('INTERRUPTED')
    raise SystemExit(130)
except Exception as e:
    print('FAIL suite crashed: %s: %s' % (type(e).__name__, e))
    failures.append('suite crashed: %s: %s' % (type(e).__name__, e))
finally:
    for p in procs:
        p.kill()

print()
print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
