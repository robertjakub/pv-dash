#!/usr/bin/env python3
"""Static file server with a Prometheus proxy at /prom — the dashboard's
serving surface, the family shape: the connection gate (--max-clients,
--max-conn-per-ip, --client-timeout), the SCR audit trail, the JSON-lines
control server (--control-port, talked to with dashboard-ctl / dashboard-cli)
and the SIGHUP config reload. Stdlib only.

Layout: lib/config (settings resolution), lib/settings (the control grammar
registry), lib/control (the control server), lib/man (the man pages),
lib/statics, this file (CLI, logging, signals).
"""
import argparse
import logging
import mimetypes
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.audit import AuditLog
from common.cred import parse_trust_uids
from common.connlimit import GatedHTTPServer
from common.logutil import UtcFormatter
from common.version import version_string
from lib.config import resolve_config, resolve_control_target
from lib.control import ControlServer
from lib.man import daemon_page
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, PROXY_TIMEOUT_S

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger('dashboard')


def next_to_script(name):
    """The flattened package layout first (the file next to the script),
    then the dev checkout's subproject root (the parent of bin/)."""
    for base in (SCRIPT_DIR, os.path.dirname(SCRIPT_DIR)):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return os.path.join(SCRIPT_DIR, name)


def default_config_path():
    """$DASHBOARD_CONFIG wins (the docker config volume); then a user's ini
    next to the script (the flattened package layout); then the dev
    checkout's sample at the subproject root."""
    env = os.environ.get('DASHBOARD_CONFIG')
    if env and env.strip():
        return env.strip()
    for candidate in (os.path.join(SCRIPT_DIR, 'server.ini'),
                      os.path.join(os.path.dirname(SCRIPT_DIR), 'server.ini')):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(SCRIPT_DIR, 'server.ini')


RATE_LIMIT_503 = (b'HTTP/1.1 503 Service Unavailable\r\n'
                  b'Content-Type: text/plain; charset=utf-8\r\n'
                  b'Cache-Control: no-store\r\n'
                  b'Connection: close\r\n\r\n'
                  b'too many concurrent clients\n')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    upstream = None
    log_queries = False
    log_access = False
    static_dir = next_to_script('static')
    config_js = next_to_script('config.js')
    prom_prefix = None
    battery = False
    upstream_ok = True
    _upstream_lock = threading.Lock()

    def do_GET(self):
        try:
            parts = urlsplit(self.path)
            prefix = self.prom_prefix.rstrip('/')
            if not prefix or parts.path == prefix or parts.path.startswith(prefix + '/'):
                self.proxy(parts)
            else:
                self.static(parts.path)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug('client %s disconnected', self.address_string())
        except Exception as e:
            logger.error('unhandled error serving %s: %s', self.path, e)
            logger.debug('traceback:', exc_info=True)
            try:
                self.send_error(500, 'internal server error')
            except Exception:
                pass

    def proxy(self, parts):
        prefix = self.prom_prefix.rstrip('/')
        rest = parts.path[len(prefix):] if prefix else parts.path
        url = self.upstream.rstrip('/') + rest
        if parts.query:
            url += '?' + parts.query
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT_S) as r:
                status, body, ctype = r.status, r.read(), r.headers.get('Content-Type', 'application/json')
            self._mark_upstream(True, None)
        except urllib.error.HTTPError as e:
            status, body, ctype = e.code, e.read(), e.headers.get('Content-Type', 'text/plain')
            self._mark_upstream(True, e.code)
        except Exception as e:
            status, body, ctype = 502, ('proxy error: ' + str(e)).encode(), 'text/plain'
            self._mark_upstream(False, e)
            logger.debug('proxy %s: %s', url, e)
        self.relay(status, body, ctype)
        msg = 'GET %s -> %s (%d ms, %d bytes)' % (
            parts.path + ('?' + parts.query if parts.query else ''),
            status, (time.time() - t0) * 1000, len(body))
        if self.log_queries:
            logger.info(msg)
        else:
            logger.debug(msg)

    def relay(self, code, body, ctype):
        try:
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            self.wfile.write(body)
            if self.log_access:
                logger.info('%s - "%s %s" %d %d bytes', self.address_string(),
                            self.command, self.path, code, len(body))
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            logger.debug('client %s disconnected while sending %d', self.address_string(), code)

    def _mark_upstream(self, ok, detail):
        with self._upstream_lock:
            if Handler.upstream_ok == ok:
                return
            Handler.upstream_ok = ok
        if ok:
            logger.info('prometheus at %s is reachable again%s', self.upstream,
                        ' (HTTP %s)' % detail if detail is not None else '')
        else:
            logger.warning('prometheus at %s not available: %s (serving 502 until it recovers)', self.upstream, detail)

    def static(self, path):
        if path == '/':
            path = '/index.html'
        name = path.lstrip('/')
        if name == 'config.js' and self.config_js and os.path.isfile(self.config_js):
            self.serve_file(self.config_js, inject_battery=self.battery)
            return
        fpath = os.path.realpath(os.path.join(self.static_dir, path.lstrip('/')))
        base = os.path.realpath(self.static_dir)
        if fpath != base and not fpath.startswith(base + os.sep):
            self.send_error(403)
            return
        if not os.path.isfile(fpath):
            self.send_error(404)
            return
        self.serve_file(fpath)

    def serve_file(self, fpath, inject_battery=False):
        try:
            ctype = mimetypes.guess_type(fpath)[0] or 'application/octet-stream'
            with open(fpath, 'rb') as f:
                body = f.read()
        except OSError as e:
            logger.error('cannot read %s: %s', fpath, e)
            self.send_error(500, 'cannot read file')
            return
        if inject_battery and b'battery: true' not in body:
            body = body.replace(b'\n};', b',\n  battery: true\n};', 1)
        self.relay(200, body, ctype)

    def log_message(self, fmt, *args):
        if self.log_access:
            logger.info('%s - %s', self.address_string(), fmt % args)
        else:
            logger.debug('%s - %s', self.address_string(), fmt % args)


class Server(GatedHTTPServer):
    """The static+proxy server behind the connection caps (F13 round):
    --max-clients (total) and --max-conn-per-ip — past either, an immediate
    503; 0 = unlimited. setup_gate() runs before serve_forever."""

    def gate_refused(self, request, client_address, why):
        logger.info('rejected %s: too many concurrent clients (%s, max %d/%d)',
                    client_address, why, self.gate.max_total, self.gate.max_per_ip)
        try:
            request.sendall(RATE_LIMIT_503)
        except OSError:
            pass
        self.shutdown_request(request)

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, socket.timeout, TimeoutError)):
            logger.debug('client %s disconnected: %s', client_address, exc)
        else:
            logger.error('request handling error: %s', exc)
            logger.debug('traceback:', exc_info=True)


def setup_logging(cfg):
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg['level'], logging.INFO))
    fmt = '%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM') \
        else '%(asctime)s %(levelname)-7s %(message)s'
    handler = logging.StreamHandler()
    handler.setFormatter(UtcFormatter(fmt) if not cfg['local_time'] else logging.Formatter(fmt))
    root.addHandler(handler)


def describe(cfg, args, control_desc):
    limits = (['max-clients %d' % cfg['max_clients']] if cfg['max_clients'] else []) + \
             (['client-timeout %gs' % cfg['client_timeout']] if cfg['client_timeout'] else []) + \
             (['max-conn-per-ip %d' % cfg['max_conn_per_ip']] if cfg['max_conn_per_ip'] else [])
    return ('serving %s on http://%s:%d (proxy: %s/* -> %s, config.js: %s, log level: %s, log time: %s, '
            'log access: %s, log queries: %s%s, limits: %s, control server: %s, version: %s)' % (
                cfg['static_dir'], cfg['bind'], cfg['port'], cfg['prom_prefix'] or '/', cfg['upstream'],
                cfg['config_js'], cfg['level'],
                'local' if cfg['local_time'] else 'UTC',
                'on' if cfg['log_access'] else 'off',
                'on' if cfg['log_queries'] else 'off',
                ', battery enabled' if cfg['battery'] else '',
                ', '.join(limits) if limits else 'off',
                control_desc,
                version_string()))


def install_signal_handlers(httpd, apply_reload=None, graceful_stop=None):
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


def parse_args():
    ap = argparse.ArgumentParser(description='Static file server with a Prometheus proxy at /prom')
    ap.add_argument('--config', default=default_config_path(),
                    help='config file (default: $DASHBOARD_CONFIG, then server.ini next to this script, then the subproject root)')
    ap.add_argument('--port', type=int, help='listen port (default: config file, $PORT or 8080)')
    ap.add_argument('--bind', help='address to bind (default: config file, $BIND or 0.0.0.0)')
    ap.add_argument('--static-dir', help='directory to serve (default: config file, $STATIC_DIR or static next to the script)')
    ap.add_argument('--config-js', help='config.js to serve at /config.js (default: config file, $CONFIG_JS or config.js next to the script)')
    ap.add_argument('--prom-prefix', help='path under which Prometheus is proxied (default: config file, $PROM_PREFIX or /prom); empty string proxies everything')
    ap.add_argument('--upstream', help='upstream Prometheus URL (default: config file, $PROM_URL or http://localhost:9090)')
    ap.add_argument('--max-clients', type=int, help='maximum concurrent HTTP clients (pages + proxy); extras get an immediate 503 '
                    '(default: config file, $DASHBOARD_MAX_CLIENTS or 64; 0 = unlimited)')
    ap.add_argument('--client-timeout', type=float, help='seconds an idle keep-alive HTTP client is kept before '
                    'being kicked (default: config file, $DASHBOARD_CLIENT_TIMEOUT or 300; 0 = off)')
    ap.add_argument('--max-conn-per-ip', dest='max_conn_per_ip', type=int, help='maximum concurrent HTTP connections '
                    'from one peer IP; extras get an immediate 503 '
                    '(default: config file, $DASHBOARD_MAX_CONN_PER_IP or 0 = no per-IP limit)')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='log level (default: config file or INFO); DEBUG logs every request')
    ap.add_argument('--log-queries', action='store_true', default=None,
                    help='log proxied Prometheus queries at INFO level')
    ap.add_argument('--log-access', action='store_true', default=None,
                    help='log every HTTP request at INFO (default: config file, $DASHBOARD_LOG_ACCESS or quiet)')
    ap.add_argument('--local-time', action='store_true', help='log timestamps in the system time zone instead of UTC')
    ap.add_argument('--battery', action='store_true', default=None,
                    help='enable battery support in the served config.js (default: config file, $BATTERY or off)')
    ap.add_argument('--control-port', dest='control_port',
                    help='JSON-lines control server target: unix socket path (default: /tmp/dashboard-<port>.socket) '
                         'or TCP port number on 127.0.0.1 (e.g. 15598); 0 = off. Talk to it with dashboard-ctl.py '
                         '(default: config file, $DASHBOARD_CONTROL_PORT)')
    ap.add_argument('--control-token', dest='control_token',
                    help='require a token on control connections: the client authenticates with '
                         '{"cmd": "auth", "token": ...}; over the unix socket a trusted peer (root, the daemon\'s '
                         'own user or --control-trust-uids — SO_PEERCRED) skips the token '
                         '(default: config file, $DASHBOARD_CONTROL_TOKEN or none)')
    ap.add_argument('--control-token-file', dest='control_token_file',
                    help='the control token from a file (the first line; e.g. a systemd LoadCredential or a key '
                         'file; must be owner-only 0600) — takes the place of --control-token; giving both is an '
                         'error (env DASHBOARD_CONTROL_TOKEN_FILE)')
    ap.add_argument('--control-trust-uids', dest='control_trust_uids',
                    help='extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local '
                         'systemd unit speaks without the secret); root and the daemon\'s own user are always '
                         'trusted (default: config file, $DASHBOARD_CONTROL_TRUST_UIDS or none)')
    ap.add_argument('--audit-log', default=None,
                    help='DSH audit trail: a file path or - for stdout (the docker/journald way); '
                         'default: the XDG state home (~/.local/state/dashboard/audit.log)')
    ap.add_argument('--audit-max-mb', type=float, default=AUDIT_MAX_MB,
                    help='rotate the audit log at this size in MB, keeping 3 backups; 0 = no size rotation (default %(default)s)')
    ap.add_argument('--audit-files', type=int, default=AUDIT_FILES, help='rotated audit backups to keep (default %(default)s)')
    ap.add_argument('--no-audit-log', action='store_true', help='disable the SCR audit trail')
    ap.add_argument('--dry-run', action='store_true', help='validate the configuration, print the effective settings and exit (nothing is bound)')
    ap.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (dashboard --man | man -l -)')
    args = ap.parse_args()
    if args.man:
        sys.stdout.write(daemon_page(ap))
        raise SystemExit(0)
    return args


def main():
    if '--version' in sys.argv:
        print(version_string())
        raise SystemExit(0)
    args = parse_args()
    cfg = resolve_config(args, SCRIPT_DIR)
    setup_logging(cfg)
    control_target = resolve_control_target(cfg['control_port'], cfg['port'])
    control_token = cfg['control_token'] or None
    trust_uids = parse_trust_uids(cfg['control_trust_uids'], 'control-trust-uids')
    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'DSH', app='dashboard',
                                                    max_mb=args.audit_max_mb, files=args.audit_files)
    control_desc = 'off' if control_target == '0' \
        else ('127.0.0.1:%s' % control_target if control_target.isdigit() else 'unix:%s' % control_target)
    Handler.upstream = cfg['upstream']
    Handler.log_queries = cfg['log_queries']
    Handler.log_access = cfg['log_access']
    Handler.static_dir = cfg['static_dir']
    Handler.config_js = cfg['config_js']
    Handler.prom_prefix = cfg['prom_prefix']
    Handler.battery = cfg['battery']
    Handler.timeout = cfg['client_timeout'] or None
    logger.info('%s', describe(cfg, args, control_desc))
    if args.dry_run:
        logger.info('dry-run: configuration is valid, nothing was bound')
        return
    try:
        httpd = Server((cfg['bind'], cfg['port']), Handler)
    except OSError as e:
        logger.error('cannot bind %s:%d: %s', cfg['bind'], cfg['port'], e)
        raise SystemExit(1)
    httpd.setup_gate(cfg['max_clients'], cfg['max_conn_per_ip'])
    started = time.monotonic()

    control = None
    if control_target != '0':
        defaults = {
            'max-clients': str(cfg['max_clients']),
            'client-timeout': '%g' % cfg['client_timeout'],
            'max-conn-per-ip': str(cfg['max_conn_per_ip']),
            'log-access': 'on' if cfg['log_access'] else 'off',
            'log-queries': 'on' if cfg['log_queries'] else 'off',
            'battery': 'on' if cfg['battery'] else 'off',
            'log-level': cfg['level'],
        }
        control = ControlServer(httpd, int(control_target) if control_target.isdigit() else control_target,
                                audit=audit, token=control_token, defaults=defaults, trust_uids=trust_uids)
        control.start()

    def apply_reload():
        """The SIGHUP and the `request reload` command share this: re-resolve
        the config, apply what is live (the handler, the gate, the log
        level), clear the override markers, audit. The listen address and
        the port are bound — they stay."""
        new_cfg = resolve_config(args, SCRIPT_DIR)
        Handler.upstream = new_cfg['upstream']
        Handler.log_queries = new_cfg['log_queries']
        Handler.log_access = new_cfg['log_access']
        Handler.static_dir = new_cfg['static_dir']
        Handler.config_js = new_cfg['config_js']
        Handler.prom_prefix = new_cfg['prom_prefix']
        Handler.battery = new_cfg['battery']
        Handler.timeout = new_cfg['client_timeout'] or None
        httpd.gate.max_total = new_cfg['max_clients']
        httpd.gate.max_per_ip = new_cfg['max_conn_per_ip']
        logging.getLogger().setLevel(getattr(logging, new_cfg['level'], logging.INFO))
        if control:
            control.clear_overrides()   # the config won: nothing is live-overridden
        if audit:
            audit.event('RELOAD', 'upstream %s, battery %s' % (new_cfg['upstream'],
                                                               'on' if new_cfg['battery'] else 'off'))
        return 'upstream %s, battery %s' % (new_cfg['upstream'], 'on' if new_cfg['battery'] else 'off')

    if control:
        control.reloader = apply_reload   # the control server's `request reload` runs the same path

    def graceful_stop(reason):
        logger.info('shutdown: %s received after %ds, stopping the web server',
                    reason, time.monotonic() - started)
        if audit:
            audit.event('SHUTDOWN', '%s: uptime=%ds' % (reason, int(time.monotonic() - started)))
        if control:
            control.announce_exit(reason)   # the consoles print the notice and exit
            control.cleanup()
        httpd.shutdown()

    if control:
        control.stopper = graceful_stop
    install_signal_handlers(httpd, apply_reload=apply_reload, graceful_stop=graceful_stop)
    if audit:
        audit.event('START', 'version=%s upstream=%s listen=%s:%d control=%s'
                    % (version_string(), cfg['upstream'], cfg['bind'], cfg['port'], control_desc))
    try:
        httpd.serve_forever()
        logger.info('stopped')
    except KeyboardInterrupt:
        logger.info('stopped')
    finally:
        if audit:
            audit.close()


if __name__ == '__main__':
    main()
