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

from common.audit import AuditLog
from common.config import parse_listen
from common.cred import parse_trust_uids
from common.logutil import UtcFormatter
from common.version import version_string
from lib.config import resolve_config, resolve_control_target
from lib.control import ControlServer
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
    ap.add_argument('--interval', type=float, help='seconds between polls (default: config, $SCRAPER_INTERVAL or 10)')
    ap.add_argument('--max-clients', type=int, help='maximum concurrent HTTP clients; extras get an immediate 503 '
                    '(default: config, $SCRAPER_MAX_CLIENTS or 64; 0 = unlimited)')
    ap.add_argument('--client-timeout', type=float, help='seconds an idle keep-alive HTTP client is kept before '
                    'being kicked (default: config, $SCRAPER_CLIENT_TIMEOUT or 300; 0 = off)')
    ap.add_argument('--max-conn-per-ip', dest='max_conn_per_ip', type=int, help='maximum concurrent HTTP connections '
                    'from one peer IP; extras get an immediate 503 '
                    '(default: config, $SCRAPER_MAX_CONN_PER_IP or 0 = no per-IP limit)')
    ap.add_argument('--local-time', action='store_true', help='log timestamps in the system time zone instead of UTC')
    ap.add_argument('--control-port', dest='control_port',
                    help='JSON-lines control server target: unix socket path (default: /tmp/modbus-scraper-<listen-port>.socket) or TCP port number on 127.0.0.1 (e.g. 15599); 0 = off. Talk to it with scraper_ctl.py (default: config, $SCRAPER_CONTROL_PORT)')
    ap.add_argument('--control-token', dest='control_token',
                    help='require a token on control connections: the client authenticates with {"cmd": "auth", "token": ...}; over the unix socket a trusted peer (root, the daemon\'s own user or --control-trust-uids — SO_PEERCRED) skips the token (default: config, $SCRAPER_CONTROL_TOKEN or none)')
    ap.add_argument('--control-token-file', dest='control_token_file',
                    help='the control token from a file (the first line; e.g. a systemd LoadCredential or a key file; must be owner-only 0600) — takes the place of --control-token; giving both is an error (env SCRAPER_CONTROL_TOKEN_FILE)')
    ap.add_argument('--control-trust-uids', dest='control_trust_uids',
                    help='extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon\'s own user are always trusted (default: config, $SCRAPER_CONTROL_TRUST_UIDS or none)')
    ap.add_argument('--audit-log', default=None,
                    help='SCR audit trail: a file path or - for stdout (the docker/journald way); '
                         'default: the XDG state home (~/.local/state/modbus-scraper/audit.log)')
    ap.add_argument('--audit-max-mb', type=float, default=10.0, help='rotate the audit log at this size in MB, keeping 3 backups; 0 = no size rotation (default %(default)s)')
    ap.add_argument('--audit-files', type=int, default=3, help='rotated audit backups to keep (default %(default)s)')
    ap.add_argument('--no-audit-log', action='store_true', help='disable the SCR audit trail')
    ap.add_argument('--log-access', action='store_true', default=None,
                    help='log every HTTP request at INFO (default: config, $SCRAPER_LOG_ACCESS or quiet)')
    ap.add_argument('--auth-token', help='require Authorization: Bearer <token> on all requests '
                     '(default: config, $SCRAPER_AUTH_TOKEN or disabled)')
    ap.add_argument('--auth-token-file', help='read the bearer token from this file instead (single line, '
                    'trimmed; re-read on every SIGHUP — rotate by rewriting the file and reloading; '
                    'must be owner-only 0600); '
                    'mutually exclusive with --auth-token')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='log level (default: config, $SCRAPER_LOG_LEVEL or INFO)')
    ap.add_argument('--dry-run', action='store_true', help='validate the configuration, print the effective settings and exit (nothing is bound or connected)')
    ap.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (modbus-scraper --man | man -l -)')
    args = ap.parse_args()
    if args.man:
        from lib.man import daemon_page
        sys.stdout.write(daemon_page(ap))
        raise SystemExit(0)
    return args


def setup_logging(cfg):
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg['level'], logging.INFO))
    fmt = '%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM') \
        else '%(asctime)s %(levelname)-7s %(message)s'
    handler = logging.StreamHandler()
    handler.setFormatter(UtcFormatter(fmt) if not cfg['local_time'] else logging.Formatter(fmt))
    root.addHandler(handler)


def describe(cfg, args, control_desc):
    caps = (['pv cap %gW' % (cfg['max_kwp'] * 1000.0)] if cfg['max_kwp'] > 0 else []) + \
           (['grid cap %gW' % (cfg['max_grid_kw'] * 1000.0)] if cfg['max_grid_kw'] > 0 else [])
    limits = (['max-clients %d' % cfg['max_clients']] if cfg['max_clients'] else []) + \
             (['client-timeout %gs' % cfg['client_timeout']] if cfg['client_timeout'] else []) + \
             (['max-conn-per-ip %d' % cfg['max_conn_per_ip']] if cfg['max_conn_per_ip'] else [])
    listen_host, listen_port = parse_listen(cfg['listen'])
    return ('polling %s:%d unit %d (registers pv=%d grid=%d, scale pv=%g grid=%g, positive=%s%s) every %gs; '
            '%s /metrics on %s:%d (config: %s, log level: %s, log time: %s, log access: %s, auth: %s, '
            'limits: %s, caps: %s, control server: %s, version: %s)' % (
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
                control_desc,
                version_string()))


def install_signal_handlers(scraper, httpd, args, started, apply_reload=None, graceful_stop=None):
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
                    summary = apply_reload()
                    logger.info('SIGHUP: applied (%s)', summary)
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
            graceful_stop(signal.Signals(stop_signal[0]).name)

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
    control_target = resolve_control_target(cfg['control_port'], listen_port)
    control_token = cfg['control_token'] or None
    trust_uids = parse_trust_uids(cfg['control_trust_uids'], 'control-trust-uids')
    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'SCR', app='modbus-scraper',
                                                    max_mb=args.audit_max_mb, files=args.audit_files)
    control_desc = 'off' if control_target == '0' \
        else ('127.0.0.1:%s' % control_target if control_target.isdigit() else 'unix:%s' % control_target)
    client = ModbusTCP(cfg['host'], cfg['modbus_port'], cfg['unit'], cfg['timeout'], cfg['modbus_offset'])
    scraper = Scraper(cfg, client, spec)
    Handler.scraper = scraper
    Handler.log_access = cfg['log_access']
    Handler.auth_token = cfg['auth_token']
    Handler.timeout = cfg['client_timeout'] or None
    logger.info('%s', describe(cfg, args, control_desc))
    if args.dry_run:
        logger.info('dry-run: configuration is valid, nothing was bound or connected')
        return
    httpd = Server((listen_host, listen_port), Handler)
    httpd.setup_gate(cfg['max_clients'], cfg['max_conn_per_ip'])
    started = time.monotonic()

    control = None
    if control_target != '0':
        defaults = {
            'interval': '%g' % cfg['interval'],
            'timeout': '%g' % cfg['timeout'],
            'max-clients': str(cfg['max_clients']),
            'client-timeout': '%g' % cfg['client_timeout'],
            'max-conn-per-ip': str(cfg['max_conn_per_ip']),
            'log-access': 'on' if cfg['log_access'] else 'off',
            'log-level': cfg['level'],
        }
        control = ControlServer(scraper, httpd, int(control_target) if control_target.isdigit() else control_target,
                                audit=audit, token=control_token, defaults=defaults, trust_uids=trust_uids)
        control.start()

    def apply_reload():
        """The SIGHUP and the `request reload` command share this: re-resolve
        the config, apply what is live (the gate, the handler, the poller),
        clear the override markers, audit."""
        new_cfg = resolve_config(args, SCRIPT_DIR)
        scraper.reload(new_cfg)
        Handler.log_access = new_cfg['log_access']
        Handler.auth_token = new_cfg['auth_token']
        Handler.timeout = new_cfg['client_timeout'] or None
        httpd.gate.max_total = new_cfg['max_clients']
        httpd.gate.max_per_ip = new_cfg['max_conn_per_ip']
        if control:
            control.clear_overrides()   # the config won: nothing is live-overridden
        if audit:
            audit.event('RELOAD', 'upstream %s:%d unit %d, interval %gs, auth %s'
                        % (new_cfg['host'], new_cfg['modbus_port'], new_cfg['unit'], new_cfg['interval'],
                           'bearer' if new_cfg['auth_token'] else 'none'))
        return 'upstream %s:%d unit %d, interval %gs' % (new_cfg['host'], new_cfg['modbus_port'],
                                                         new_cfg['unit'], new_cfg['interval'])

    control.reloader = apply_reload   # the control server's `request reload` runs the same path

    def graceful_stop(reason):
        logger.info('shutdown: %s received after %ds (%d poll errors), stopping the web server',
                    reason, time.monotonic() - started, scraper.errors)
        if audit:
            audit.event('SHUTDOWN', '%s: uptime=%ds errors=%d'
                        % (reason, int(time.monotonic() - started), scraper.errors))
        if control:
            control.announce_exit(reason)   # the consoles print the notice and exit
            control.cleanup()
        httpd.shutdown()

    if control:
        control.stopper = graceful_stop
    install_signal_handlers(scraper, httpd, args, started, apply_reload=apply_reload, graceful_stop=graceful_stop)
    if audit:
        audit.event('START', 'version=%s upstream=%s:%d unit %d listen=%s control=%s'
                    % (version_string(), cfg['host'], cfg['modbus_port'], cfg['unit'], cfg['listen'],
                       control_desc))
    try:
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
