#!/usr/bin/env python3
"""Prometheus exporter for Huawei SUN2000 inverters (Modbus TCP, stdlib only).

Polls the inverter over Modbus TCP and serves the huawei_*_watts metrics the
pv-dashboard expects at /metrics in the Prometheus text format.
"""
import argparse
import configparser
import json
import logging
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger('sun2000')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_metrics(path=None):
    """Metric names, help texts and types from metrics.json next to this script."""
    path = path or os.path.join(SCRIPT_DIR, 'metrics.json')
    with open(path, encoding='utf-8') as fh:
        specs = json.load(fh)
    for spec in specs.values():
        spec.setdefault('type', 'gauge')
    return specs


METRICS = load_metrics()
PV_METRIC = METRICS['pv']['name']
EXPORT_METRIC = METRICS['export']['name']
IMPORT_METRIC = METRICS['import']['name']
HOME_METRIC = METRICS['home']['name']
GRID_METRIC = METRICS['grid']['name']
BATT_METRIC = METRICS['batt_net']['name']
BATT_CHARGE_METRIC = METRICS['batt_charge']['name']
BATT_DISCHARGE_METRIC = METRICS['batt_discharge']['name']
BATT_SOC_METRIC = METRICS['batt_soc']['name']
BATTERY_ENABLED_METRIC = METRICS['battery']['name']
UP_METRIC = METRICS['up']['name']
ERRORS_METRIC = METRICS['modbus_errors']['name']
LAST_POLL_METRIC = METRICS['last_poll']['name']

HELP_TEXT = {spec['name']: spec['help'] for spec in METRICS.values()}
TYPE_TEXT = {spec['name']: spec['type'] for spec in METRICS.values()}


class ModbusError(Exception):
    pass


class ModbusTCP:
    def __init__(self, host, port, unit, timeout, offset):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.offset = offset
        self.sock = None
        self.txn = 0

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _recv_exact(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ModbusError('connection closed by inverter')
            buf += chunk
        return buf

    def _connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def read_registers(self, addr, count):
        if not self.sock:
            self._connect()
        self.txn = (self.txn + 1) & 0xFFFF
        pdu = struct.pack('>BHH', 3, addr + self.offset, count)
        self.sock.sendall(struct.pack('>HHHB', self.txn, 0, len(pdu) + 1, self.unit) + pdu)
        txn, proto, length, unit = struct.unpack('>HHHB', self._recv_exact(7))
        body = self._recv_exact(length - 1)
        if txn != self.txn:
            raise ModbusError('transaction id mismatch')
        if proto != 0:
            raise ModbusError('unexpected protocol id %d' % proto)
        if unit != self.unit:
            raise ModbusError('reply from unit id %d, expected %d' % (unit, self.unit))
        func = body[0]
        if func == 3 + 0x80:
            raise ModbusError('modbus exception, code %d' % (body[2] if len(body) > 2 else -1))
        if func != 3:
            raise ModbusError('unexpected function byte 0x%02x' % func)
        got = body[1]
        if got != count * 2:
            raise ModbusError('expected %d register bytes, got %d' % (count * 2, got))
        return struct.unpack('>%dH' % count, body[2:2 + got])

    def read_i32(self, addr):
        hi, lo = self.read_registers(addr, 2)
        return struct.unpack('>i', struct.pack('>HH', hi, lo))[0]


class Scraper:
    def __init__(self, opts):
        self.opts = opts
        self.lock = threading.Lock()
        self.values = {}
        self.error = None
        self.up = False
        self.last_poll = 0.0
        self.errors = 0
        self.client = ModbusTCP(opts.host, opts.modbus_port, opts.unit, opts.timeout, opts.modbus_offset)

    def _mark_up(self, ok, err):
        with self.lock:
            was = self.up
            if ok:
                self.up = True
            else:
                self.up = False
                self.errors += 1
        if was != ok:
            if ok:
                logger.info('inverter %s:%d reachable', self.opts.host, self.opts.modbus_port)
            else:
                logger.warning('inverter %s:%d unreachable: %s', self.opts.host, self.opts.modbus_port, err)

    def poll_once(self):
        try:
            pv_raw = self.client.read_i32(self.opts.pv_register)
            grid_raw = self.client.read_i32(self.opts.grid_register)
            battery = self.opts.battery
            batt_raw = self.client.read_i32(self.opts.battery_register) if battery else 0
            soc = self.client.read_registers(self.opts.battery_soc_register, 1)[0] / 10.0 if battery else None
        except Exception as e:
            self.client.close()
            self._mark_up(False, e)
            logger.debug('poll failed: %s', e)
            return
        pv = pv_raw * self.opts.scale
        grid = grid_raw * self.opts.grid_scale
        if self.opts.grid_positive_import:
            grid = -grid
        batt = batt_raw * self.opts.scale
        home = pv - batt - grid
        cap = self.opts.max_kwp * 1000.0
        grid_cap = self.opts.max_grid_kw * 1000.0
        discharge = max(-batt, 0.0)
        if battery:
            context = ' [poll: pv_raw=%d grid_raw=%d batt_raw=%d -> pv=%.0fW grid=%.0fW batt=%.0fW]' % (
                pv_raw, grid_raw, batt_raw, pv, grid, batt)
        else:
            context = ' [poll: pv_raw=%d grid_raw=%d -> pv=%.0fW grid=%.0fW]' % (pv_raw, grid_raw, pv, grid)
        err = None
        if pv < 0:
            err = 'PV power is negative: %.0f W (register %d raw %d)%s' % (
                pv, self.opts.pv_register, pv_raw, context)
        elif self.opts.max_kwp > 0 and pv > cap:
            err = 'PV energy exceeds max_kwp: %.0f W > %.0f W (register %d raw %d)%s' % (
                pv, cap, self.opts.pv_register, pv_raw, context)
        elif self.opts.max_kwp > 0 and grid > cap + discharge:
            err = 'Exported power exceeds max_kwp: %.0f W > %.0f W (register %d raw %d)%s' % (
                grid, cap + discharge, self.opts.grid_register, grid_raw, context)
        elif self.opts.max_grid_kw > 0 and abs(grid) > grid_cap:
            err = 'Grid power exceeds max_grid_kw: %.0f W > %.0f W (register %d raw %d)%s' % (
                abs(grid), grid_cap, self.opts.grid_register, grid_raw, context)
        elif home < 0:
            err = 'Home power is negative: %.0f W (inconsistent readings)%s' % (home, context)
        with self.lock:
            self.error = err
            if err is None:
                self.values = {
                    PV_METRIC: pv,
                    GRID_METRIC: grid,
                    EXPORT_METRIC: max(grid, 0.0),
                    IMPORT_METRIC: max(-grid, 0.0),
                    HOME_METRIC: home,
                    BATTERY_ENABLED_METRIC: 1 if battery else 0,
                }
                if battery:
                    self.values[BATT_METRIC] = batt
                    self.values[BATT_CHARGE_METRIC] = max(batt, 0.0)
                    self.values[BATT_DISCHARGE_METRIC] = max(-batt, 0.0)
                    self.values[BATT_SOC_METRIC] = soc
                self.last_poll = time.time()
            else:
                self.errors += 1
        if err is not None:
            logger.error('%s', err)
            return
        self._mark_up(True, None)
        logger.debug('poll ok: pv_raw=%d grid_raw=%d batt_raw=%d', pv_raw, grid_raw, batt_raw)

    def poll_loop(self):
        while True:
            self.poll_once()
            time.sleep(self.opts.interval)

    def snapshot(self):
        with self.lock:
            return self.up, dict(self.values), self.last_poll, self.errors

    def error_state(self):
        with self.lock:
            return self.error


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    scraper = None

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        try:
            if path == '/metrics':
                if self.scraper.error_state():
                    self.relay(503, b'# Error collecting metrics from inverter\n', 'text/plain; charset=utf-8')
                else:
                    self.relay(200, self.exposition(), 'text/plain; version=0.0.4; charset=utf-8')
            elif path == '/':
                self.relay(200, b'sun2000-scraper: see /metrics\n', 'text/plain; charset=utf-8')
            else:
                self.relay(404, b'not found\n', 'text/plain; charset=utf-8')
        except (BrokenPipeError, ConnectionResetError):
            logger.debug('client %s disconnected', self.address_string())
        except Exception as e:
            logger.error('unhandled error serving %s: %s', self.path, e)
            try:
                self.relay(500, b'internal server error\n', 'text/plain; charset=utf-8')
            except Exception:
                pass

    def exposition(self):
        up, values, last_poll, errors = self.scraper.snapshot()

        def fmt(v):
            return '%d' % round(v) if float(v).is_integer() else '%.3f' % v

        lines = [
            '# HELP %s %s' % (UP_METRIC, HELP_TEXT[UP_METRIC]),
            '# TYPE %s %s' % (UP_METRIC, TYPE_TEXT[UP_METRIC]),
            '%s %d' % (UP_METRIC, int(up)),
            '# HELP %s %s' % (ERRORS_METRIC, HELP_TEXT[ERRORS_METRIC]),
            '# TYPE %s %s' % (ERRORS_METRIC, TYPE_TEXT[ERRORS_METRIC]),
            '%s %d' % (ERRORS_METRIC, errors),
            '# HELP %s %s' % (LAST_POLL_METRIC, HELP_TEXT[LAST_POLL_METRIC]),
            '# TYPE %s %s' % (LAST_POLL_METRIC, TYPE_TEXT[LAST_POLL_METRIC]),
            '%s %.3f' % (LAST_POLL_METRIC, last_poll),
        ]
        for name in sorted(values):
            lines.append('# HELP %s %s' % (name, HELP_TEXT.get(name, name)))
            lines.append('# TYPE %s %s' % (name, TYPE_TEXT.get(name, 'gauge')))
            lines.append('%s %s' % (name, fmt(values[name])))
        return ('\n'.join(lines) + '\n').encode()

    def relay(self, status, body, ctype):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.debug('%s - %s', self.address_string(), fmt % args)


class Server(ThreadingHTTPServer):
    daemon_threads = True


def parse_listen(text):
    host, sep, port = text.rpartition(':')
    if not sep:
        raise SystemExit('--listen must be HOST:PORT, got %r' % text)
    return host.strip('[]'), int(port)


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('true', 'yes', 'on', '1'):
        return True
    if text in ('false', 'no', 'off', '0'):
        return False
    raise ValueError('not a boolean')


def load_config(path):
    cfg = configparser.ConfigParser()
    try:
        if os.path.isfile(path):
            cfg.read(path)
    except (configparser.Error, OSError) as e:
        logger.error('cannot read config file %s: %s (using defaults)', path, e)
    if not cfg.has_section('scraper'):
        cfg.add_section('scraper')
    return cfg['scraper']


def main():
    ap = argparse.ArgumentParser(description='Prometheus exporter for Huawei SUN2000 inverters (Modbus TCP).')
    ap.add_argument('--config', default=os.path.join(SCRIPT_DIR, 'scraper.ini'),
                    help='config file (default: scraper.ini next to this script)')
    ap.add_argument('--host', help='inverter Modbus TCP address (default: config, $SUN2000_HOST or 127.0.0.1)')
    ap.add_argument('--modbus-port', type=int, help='inverter Modbus TCP port (default: config, $SUN2000_MODBUS_PORT or 5502)')
    ap.add_argument('--unit', type=int, help='Modbus unit id (default: config, $SUN2000_UNIT or 1)')
    ap.add_argument('--modbus-offset', type=int, help='added to register addresses (default: config, $SUN2000_MODBUS_OFFSET or 0)')
    ap.add_argument('--timeout', type=float, help='Modbus timeout in seconds (default: config, $SUN2000_TIMEOUT or 3)')
    ap.add_argument('--pv-register', type=int, help='PV power register, signed I32 watts (default: config, $SUN2000_PV_REGISTER or 32064)')
    ap.add_argument('--grid-register', type=int, help='grid power register, signed I32 watts (default: config, $SUN2000_GRID_REGISTER or 37113)')
    ap.add_argument('--scale', type=float, help='PV register multiplier (default: config, $SUN2000_SCALE or 1)')
    ap.add_argument('--grid-scale', type=float, help='grid register multiplier (default: config, $SUN2000_GRID_SCALE or 1)')
    ap.add_argument('--max-kwp', type=float, help='maximum PV array kWp (default: config, $SUN2000_MAX_KWP or 6; 0 = no checking)')
    ap.add_argument('--max-grid-kw', type=float, help='maximum grid kW, either direction (default: config, $SUN2000_MAX_GRID_KW or 12; 0 = no checking)')
    ap.add_argument('--battery', action='store_true', default=None,
                    help='enable battery support (default: config, $SUN2000_BATTERY or off)')
    ap.add_argument('--battery-register', type=int, help='battery power register, signed I32 watts, +charging (default: config, $SUN2000_BATTERY_REGISTER or 37001)')
    ap.add_argument('--battery-soc-register', type=int, help='battery SoC register, U16 percent*10 (default: config, $SUN2000_BATTERY_SOC_REGISTER or 37004)')
    ap.add_argument('--grid-positive-import', action='store_true', default=None,
                    help='grid register positive when importing (default: config, $SUN2000_GRID_POSITIVE_IMPORT or positive = export)')
    ap.add_argument('--listen', help='listen address HOST:PORT (default: config, $SUN2000_LISTEN or 0.0.0.0:9350)')
    ap.add_argument('--interval', type=float, help='seconds between polls (default: config, $SUN2000_INTERVAL or 5)')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='log level (default: config, $SUN2000_LOG_LEVEL or INFO)')
    args = ap.parse_args()

    cfg = load_config(args.config)

    def resolve(cli_value, env_name, cfg_key, default, conv):
        raw = cli_value
        if raw is None or raw == '':
            raw = os.environ.get(env_name)
        if raw is None or raw == '':
            raw = cfg.get(cfg_key)
        if raw is None:
            return default
        try:
            return conv(raw)
        except (TypeError, ValueError) as e:
            logger.error('invalid %s = %r: %s (using %r)', cfg_key, raw, e, default)
            return default

    host = resolve(args.host, 'SUN2000_HOST', 'host', '127.0.0.1', str)
    modbus_port = resolve(args.modbus_port, 'SUN2000_MODBUS_PORT', 'modbus_port', 5502, int)
    unit = resolve(args.unit, 'SUN2000_UNIT', 'unit', 1, int)
    modbus_offset = resolve(args.modbus_offset, 'SUN2000_MODBUS_OFFSET', 'modbus_offset', 0, int)
    timeout = resolve(args.timeout, 'SUN2000_TIMEOUT', 'timeout', 3.0, float)
    pv_register = resolve(args.pv_register, 'SUN2000_PV_REGISTER', 'pv_register', 32064, int)
    grid_register = resolve(args.grid_register, 'SUN2000_GRID_REGISTER', 'grid_register', 37113, int)
    scale = resolve(args.scale, 'SUN2000_SCALE', 'scale', 1.0, float)
    grid_scale = resolve(args.grid_scale, 'SUN2000_GRID_SCALE', 'grid_scale', 1.0, float)
    max_kwp = resolve(args.max_kwp, 'SUN2000_MAX_KWP', 'max_kwp', 6.0, float)
    max_grid_kw = resolve(args.max_grid_kw, 'SUN2000_MAX_GRID_KW', 'max_grid_kw', 12.0, float)
    battery = resolve(args.battery, 'SUN2000_BATTERY', 'battery', False, str_to_bool)
    battery_register = resolve(args.battery_register, 'SUN2000_BATTERY_REGISTER', 'battery_register', 37001, int)
    battery_soc_register = resolve(args.battery_soc_register, 'SUN2000_BATTERY_SOC_REGISTER',
                                   'battery_soc_register', 37004, int)
    grid_positive_import = resolve(args.grid_positive_import, 'SUN2000_GRID_POSITIVE_IMPORT',
                                   'grid_positive_import', False, str_to_bool)
    listen = resolve(args.listen, 'SUN2000_LISTEN', 'listen', '0.0.0.0:9350', str)
    interval = resolve(args.interval, 'SUN2000_INTERVAL', 'interval', 5.0, float)
    level = resolve(args.log_level, 'SUN2000_LOG_LEVEL', 'log_level', 'INFO', str).upper()

    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format='%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM')
                        else '%(asctime)s %(levelname)-7s %(message)s')
    if max_kwp > 0 and max_grid_kw > 0 and max_kwp > max_grid_kw:
        logger.warning('max_kwp (%g) is greater than max_grid_kw (%g): the grid line cannot be '
                       'smaller than the inverter capacity, check the caps', max_kwp, max_grid_kw)

    listen_host, listen_port = parse_listen(listen)
    caps = (['pv cap %gW' % (max_kwp * 1000.0)] if max_kwp > 0 else []) + \
           (['grid cap %gW' % (max_grid_kw * 1000.0)] if max_grid_kw > 0 else []) + \
           (['battery reg %d (soc reg %d)' % (battery_register, battery_soc_register)]
            if battery_register > 0 else [])
    opts = argparse.Namespace(host=host, modbus_port=modbus_port, unit=unit, modbus_offset=modbus_offset,
                              timeout=timeout, pv_register=pv_register, grid_register=grid_register,
                              scale=scale, grid_scale=grid_scale, max_kwp=max_kwp, max_grid_kw=max_grid_kw,
                              battery=battery, battery_register=battery_register,
                              battery_soc_register=battery_soc_register,
                              grid_positive_import=grid_positive_import, interval=interval)
    Handler.scraper = Scraper(opts)
    threading.Thread(target=Handler.scraper.poll_loop, daemon=True).start()
    logger.info('polling %s:%d unit %d (registers pv=%d grid=%d, scale pv=%g grid=%g, positive=%s%s) every %gs; '
                'serving /metrics on %s:%d (config: %s, log level: %s)',
                host, modbus_port, unit, pv_register, grid_register, scale, grid_scale,
                'import' if grid_positive_import else 'export',
                ', ' + ', '.join(caps) if caps else '',
                interval, listen_host, listen_port,
                args.config, level)
    try:
        Server((listen_host, listen_port), Handler).serve_forever()
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        logger.error('cannot bind %s:%d: %s', listen_host, listen_port, e)
        raise SystemExit(1)
    finally:
        Handler.scraper.client.close()


if __name__ == '__main__':
    main()
