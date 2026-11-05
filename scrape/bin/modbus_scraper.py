#!/usr/bin/env python3
"""Prometheus exporter for Huawei SUN2000 inverters (Modbus TCP, stdlib only).

Polls the inverter over Modbus TCP and serves the huawei_* metrics the
dashboard expects at /metrics in the Prometheus text format.

Layout: lib/protocol (Modbus client), lib/config (settings resolution),
lib/metrics (metric specs), lib/poller (poller + sanity checks),
lib/server (exposition endpoint), lib/version, this file (CLI, logging,
signals).
"""
import argparse
import logging
import os
import signal
import sys
import threading
import time

here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.config import parse_listen
from common.logutil import UtcFormatter
from common.version import version_string
from lib.config import resolve_config
from lib.metrics import Metrics
from lib.poller import Scraper
from lib.protocol import ModbusTCP
from lib.server import Handler, Server

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def default_config_path():
    """$SCRAPER_CONFIG wins (the docker config volume); then a user's ini
    next to the script (the flattened package layout); then the dev
    checkout's sample at the subproject root."""
    env = os.environ.get('SCRAPER_CONFIG')
    if env and env.strip():
        return env.strip()
    for candidate in (os.path.join(SCRIPT_DIR, 'scraper.ini'),
                      os.path.join(os.path.dirname(SCRIPT_DIR), 'scraper.ini')):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(SCRIPT_DIR, 'scraper.ini')


logger = logging.getLogger('scraper')


def parse_args():
    ap = argparse.ArgumentParser(description='Prometheus exporter for Huawei SUN2000 inverters (Modbus TCP).')
    ap.add_argument('--config', default=default_config_path(),
                    help='config file (default: $SCRAPER_CONFIG, then scraper.ini next to this script, then the subproject root)')
    ap.add_argument('--host', help='inverter Modbus TCP address (default: config, $SCRAPER_HOST or 127.0.0.1)')
    ap.add_argument('--modbus-port', type=int, help='inverter Modbus TCP port (default: config, $SCRAPER_MODBUS_PORT or 5502)')
    ap.add_argument('--unit', type=int, help='Modbus unit id (default: config, $SCRAPER_UNIT or 1)')
    ap.add_argument('--modbus-offset', type=int, help='added to register addresses (default: config, $SCRAPER_MODBUS_OFFSET or 0)')
    ap.add_argument('--timeout', type=float, help='Modbus timeout in seconds (default: config, $SCRAPER_TIMEOUT or 3)')
    ap.add_argument('--profile', dest='profile',
                    help='device profile JSON (the shared profiles/ schema; scrape-marked entries feed the metric registers) (default: config, $SCRAPER_PROFILE or the bundled sun2000 profile)')
    ap.add_argument('--metrics-spec', dest='metrics_spec',
                    help='metrics spec JSON: metric name -> {help, type, profile?} (default: config, $SCRAPER_METRICS_SPEC or the bundled metrics.json)')
    ap.add_argument('--pv-register', type=int, help='PV power register, signed I32 watts (default: config, $SCRAPER_PV_REGISTER, the profile or 32064)')
    ap.add_argument('--grid-register', type=int, help='grid power register, signed I32 watts (default: config, $SCRAPER_GRID_REGISTER or 37113)')
    ap.add_argument('--scale', type=float, help='PV register multiplier (default: config, $SCRAPER_SCALE or 1)')
    ap.add_argument('--grid-scale', type=float, help='grid register multiplier (default: config, $SCRAPER_GRID_SCALE or 1)')
    ap.add_argument('--max-kwp', type=float, help='maximum PV array kWp (default: config, $SCRAPER_MAX_KWP or 6; 0 = no checking)')
    ap.add_argument('--max-grid-kw', type=float, help='maximum grid kW, either direction (default: config, $SCRAPER_MAX_GRID_KW or 12; 0 = no checking)')
    ap.add_argument('--battery', action='store_true', default=None,
                    help='enable battery support (default: config, $SCRAPER_BATTERY or off)')
    ap.add_argument('--battery-register', type=int, help='battery power register, signed I32 watts, +charging (default: config, $SCRAPER_BATTERY_REGISTER or 37001)')
    ap.add_argument('--battery-soc-register', type=int, help='battery SoC register, U16 percent*10 (default: config, $SCRAPER_BATTERY_SOC_REGISTER or 37004)')
    ap.add_argument('--grid-positive-import', action='store_true', default=None,
                    help='grid register positive when importing (default: config, $SCRAPER_GRID_POSITIVE_IMPORT or positive = export)')
    ap.add_argument('--listen', help='listen address HOST:PORT (default: config, $SCRAPER_LISTEN or 127.0.0.1:9350)')
    ap.add_argument('--interval', type=float, help='seconds between polls (default: config, $SCRAPER_INTERVAL or 5)')
    ap.add_argument('--max-clients', type=int, help='maximum concurrent HTTP clients; extras get an immediate 503 '
                    '(default: config, $SCRAPER_MAX_CLIENTS or 64; 0 = unlimited)')
    ap.add_argument('--client-timeout', type=float, help='seconds an idle keep-alive HTTP client is kept before '
                    'being kicked (default: config, $SCRAPER_CLIENT_TIMEOUT or 300; 0 = off)')
    ap.add_argument('--local-time', action='store_true', help='log timestamps in the system time zone instead of UTC')
    ap.add_argument('--log-access', action='store_true', default=None,
                    help='log every HTTP request at INFO (default: config, $SCRAPER_LOG_ACCESS or quiet)')
    ap.add_argument('--auth-token', help='require Authorization: Bearer <token> on all requests '
                     '(default: config, $SCRAPER_AUTH_TOKEN or disabled)')
    ap.add_argument('--auth-token-file', help='read the bearer token from this file instead (single line, '
                    'trimmed; re-read on every SIGHUP — rotate by rewriting the file and reloading); '
                    'mutually exclusive with --auth-token')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='log level (default: config, $SCRAPER_LOG_LEVEL or INFO)')
    ap.add_argument('--dry-run', action='store_true', help='validate the configuration, print the effective settings and exit (nothing is bound or connected)')
    return ap.parse_args()


def setup_logging(cfg):
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg['level'], logging.INFO))
    fmt = '%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM') \
        else '%(asctime)s %(levelname)-7s %(message)s'
    handler = logging.StreamHandler()
    handler.setFormatter(UtcFormatter(fmt) if not cfg['local_time'] else logging.Formatter(fmt))
    root.addHandler(handler)


def describe(cfg, args):
    caps = (['pv cap %gW' % (cfg['max_kwp'] * 1000.0)] if cfg['max_kwp'] > 0 else []) + \
           (['grid cap %gW' % (cfg['max_grid_kw'] * 1000.0)] if cfg['max_grid_kw'] > 0 else [])
    limits = (['max-clients %d' % cfg['max_clients']] if cfg['max_clients'] else []) + \
             (['client-timeout %gs' % cfg['client_timeout']] if cfg['client_timeout'] else [])
    listen_host, listen_port = parse_listen(cfg['listen'])
    return ('polling %s:%d unit %d (registers pv=%d grid=%d, scale pv=%g grid=%g, positive=%s%s) every %gs; '
            '%s /metrics on %s:%d (config: %s, log level: %s, log time: %s, log access: %s, auth: %s, '
            'limits: %s, caps: %s, version: %s)' % (
                cfg['host'], cfg['modbus_port'], cfg['unit'], cfg['pv_register'], cfg['grid_register'],
                cfg['scale'], cfg['grid_scale'],
                'import' if cfg['grid_positive_import'] else 'export',
                ', battery reg %d (soc reg %d)' % (cfg['battery_register'], cfg['battery_soc_register'])
                if cfg['battery'] else '',
                cfg['interval'],
                'would serve' if args.dry_run else 'serving',
                listen_host, listen_port, args.config, cfg['level'],
                'local' if cfg['local_time'] else 'UTC',
                'on' if cfg['log_access'] else 'off',
                'bearer' if cfg['auth_token'] else 'none',
                ', '.join(limits) if limits else 'off',
                ', '.join(caps) if caps else 'none',
                version_string()))


def install_signal_handlers(scraper, httpd, args, started):
    if hasattr(signal, 'SIGHUP'):
        reload_requested = threading.Event()

        def on_hup(signum, frame):
            reload_requested.set()

        def watch_reload():
            while True:
                reload_requested.wait()
                reload_requested.clear()
                logger.info('SIGHUP: reload requested')
                try:
                    cfg = resolve_config(args, SCRIPT_DIR)
                    scraper.reload(cfg)
                    Handler.log_access = cfg['log_access']
                    Handler.auth_token = cfg['auth_token']
                    Handler.timeout = cfg['client_timeout'] or None
                    Server.max_clients = cfg['max_clients']
                    logger.info('SIGHUP: applied (upstream %s:%d unit %d, interval %gs, battery %s, '
                                'caps pv=%g grid=%g, limits clients=%d idle=%gs, auth %s, log access %s)',
                                cfg['host'], cfg['modbus_port'], cfg['unit'], cfg['interval'],
                                'on' if cfg['battery'] else 'off', cfg['max_kwp'], cfg['max_grid_kw'],
                                cfg['max_clients'], cfg['client_timeout'],
                                'bearer' if cfg['auth_token'] else 'none',
                                'on' if cfg['log_access'] else 'off')
                except (Exception, SystemExit) as e:
                    logger.error('SIGHUP: reload failed (%s), keeping the previous settings', e)

        signal.signal(signal.SIGHUP, on_hup)
        threading.Thread(target=watch_reload, daemon=True).start()
    if hasattr(signal, 'SIGTERM'):
        stop_signal = []

        def on_stop(signum, frame):
            stop_signal.append(signum)

        def watch_stop():
            while not stop_signal:
                time.sleep(0.2)
            logger.info('shutdown: %s received after %ds (%d poll errors), stopping the web server',
                        signal.Signals(stop_signal[0]).name, time.monotonic() - started, scraper.errors)
            httpd.shutdown()

        signal.signal(signal.SIGTERM, on_stop)
        signal.signal(signal.SIGINT, on_stop)
        threading.Thread(target=watch_stop, daemon=True).start()


def main():
    if '--version' in sys.argv:
        print(version_string())
        raise SystemExit(0)
    args = parse_args()
    cfg = resolve_config(args, SCRIPT_DIR)
    spec = Metrics()

    setup_logging(cfg)

    if cfg['max_kwp'] > 0 and cfg['max_grid_kw'] > 0 and cfg['max_kwp'] > cfg['max_grid_kw']:
        logger.warning('max_kwp (%g) is greater than max_grid_kw (%g): the grid line cannot be '
                       'smaller than the inverter capacity, check the caps', cfg['max_kwp'], cfg['max_grid_kw'])

    listen_host, listen_port = parse_listen(cfg['listen'])
    client = ModbusTCP(cfg['host'], cfg['modbus_port'], cfg['unit'], cfg['timeout'], cfg['modbus_offset'])
    scraper = Scraper(cfg, client, spec)
    Handler.scraper = scraper
    Handler.log_access = cfg['log_access']
    Handler.auth_token = cfg['auth_token']
    Handler.timeout = cfg['client_timeout'] or None
    Server.max_clients = cfg['max_clients']
    logger.info('%s', describe(cfg, args))
    if args.dry_run:
        logger.info('dry-run: configuration is valid, nothing was bound or connected')
        return
    try:
        httpd = Server((listen_host, listen_port), Handler)
        install_signal_handlers(scraper, httpd, args, time.monotonic())
        threading.Thread(target=scraper.poll_loop, daemon=True).start()
        httpd.serve_forever()
        logger.info('stopped')
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        logger.error('cannot bind %s:%d: %s', listen_host, listen_port, e)
        raise SystemExit(1)
    finally:
        client.close()


if __name__ == '__main__':
    main()
