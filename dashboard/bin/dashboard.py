#!/usr/bin/env python3
"""Static file server with a Prometheus proxy at /prom — the dashboard's
serving surface, the family shape: the connection gate (--max-clients,
--max-conn-per-ip, --client-timeout), the SCR audit trail, the JSON-lines
control server (--control-port, talked to with dashboard-ctl / dashboard-cli)
and the SIGHUP config reload. Stdlib only.

Layout: lib/config (settings resolution), lib/options (the knob registry and
the control grammar's vocabulary), lib/control (the control server),
lib/man (the man pages), lib/statics, this file (CLI, logging, signals).
"""
import hmac
import logging
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.audit import AuditLog
from common.cred import parse_trust_uids
from common.connlimit import GatedHTTPServer, rate_limit_503
from common.daemon import apply_restart_state, default_config_path, fold_listen, install_signal_handlers, log_state_dumps, \
    next_to_script, parse_ops_verbs, setup_logging
from common.options import build_parser
from common.version import version_string
from common.config import acl_value_text, is_loopback_host, parse_control_target, parse_listen, parse_secret, \
    resolve_control_target, resolve_metrics_acl
from lib.config import CONTROL_SOCKET_TEMPLATE, resolve_config
from lib.control import ControlServer
from lib.man import daemon_page
from lib.metrics import MetricsServer, describe_metrics
from lib.options import KNOWN_VERBS, OPTIONS
from lib.statics import DEFAULTS, PROXY_TIMEOUT_S

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger('dashboard')


RATE_LIMIT_503 = rate_limit_503(b'too many concurrent clients\n')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    upstream = None
    auth_token = None   # the F21 page token (the bin/the control set it) — None = the loopback bind is the story
    UNAUTH_401_BODY = b'the dashboard needs its bearer token: open /?auth=<token> (or send Authorization: Bearer <token>)\n'
    log_queries = False
    log_access = False
    static_dir = next_to_script(SCRIPT_DIR, 'static')
    config_js = next_to_script(SCRIPT_DIR, 'config.js')
    prom_prefix = None
    upstream_ok = True
    _upstream_lock = threading.Lock()
    status_counts = {'2xx': 0, '4xx': 0, '5xx': 0, 'prom': 0}   # the /metrics counters

    @classmethod
    def count(cls, key):
        try:
            cls.status_counts[key] += 1
        except (KeyError, TypeError):
            pass

    def send_response(self, code, message=None):
        Handler.count('2xx' if code < 400 else '4xx' if code < 500 else '5xx')
        super().send_response(code, message)
        if getattr(self, '_auth_bootstrap', False):   # the ?auth= exchange rides the first response
            self.send_header('Set-Cookie', 'auth=%s; Path=/; HttpOnly; SameSite=Strict' % Handler.auth_token)
            self._auth_bootstrap = False

    def _admits(self):
        """The F21 gate: the bearer token on every route when one is
        configured — the Authorization: Bearer header, the auth session
        cookie, or the ?auth=<token> bootstrap (the exchange sets the
        cookie; the token is stripped from the path before anything logs
        or forwards). A token-less config serves on the loopback bind
        only: the start refuses beyond loopback."""
        token = Handler.auth_token
        if not token:
            return True
        cand = self.headers.get('Authorization') or ''
        if cand.startswith('Bearer ') and hmac.compare_digest(cand[7:].strip(), token):
            return True
        jar = SimpleCookie()
        for hdr in (self.headers.get_all('Cookie') or []):
            try:
                jar.load(hdr)
            except CookieError:
                pass
        if jar.get('auth') and hmac.compare_digest(jar['auth'].value, token):
            return True
        parts = urlsplit(self.path)
        supplied = (parse_qs(parts.query, keep_blank_values=True).get('auth') or [''])[0]
        if supplied:
            rest = [(k, v) for k, vs in parse_qs(parts.query, keep_blank_values=True).items()
                    if k != 'auth' for v in vs]
            self.path = urlunsplit(parts._replace(query=urlencode(rest)))
            if hmac.compare_digest(supplied, token):
                self._auth_bootstrap = True
                return True
        try:
            self.send_response(401)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('WWW-Authenticate', 'Bearer realm="dashboard"')
            self.send_header('Content-Length', str(len(self.UNAUTH_401_BODY)))
            self.end_headers()
            self.wfile.write(self.UNAUTH_401_BODY)
        except (BrokenPipeError, ConnectionResetError):
            pass
        logger.debug('unauthorized request from %s', self.address_string())
        return False

    def do_GET(self):
        if not self._admits():
            return
        parts = urlsplit(self.path)
        prefix = self.prom_prefix.rstrip('/')
        if prefix and (parts.path == prefix or parts.path.startswith(prefix + '/')):
            Handler.count('prom')
        try:
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
            self.serve_file(self.config_js, inject_battery=True)
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
        """Serve one file; config.js always rides with the battery panels
        enabled — `battery: true` injected when the file does not already
        spell it (battery support is always on, the --battery knob
        retired)."""
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

    RATE_LIMIT_503 = RATE_LIMIT_503
    gate_log = logger

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, socket.timeout, TimeoutError)):
            logger.debug('client %s disconnected: %s', client_address, exc)
        else:
            logger.error('request handling error: %s', exc)
            logger.debug('traceback:', exc_info=True)


def describe(cfg, args, control_desc):
    limits = (['max-clients %d' % cfg['max_clients']] if cfg['max_clients'] else []) + \
             (['client-timeout %gs' % cfg['client_timeout']] if cfg['client_timeout'] else []) + \
             (['max-conn-per-ip %d' % cfg['max_conn_per_ip']] if cfg['max_conn_per_ip'] else [])
    listen_host, listen_port = parse_listen(cfg['listen'])
    return ('serving %s on http://%s:%d (proxy: %s/* -> %s, config.js: %s, page auth: %s, log level: %s, log time: %s, '
            'log access: %s, log queries: %s, limits: %s, control server: %s, %s, version: %s)' % (
                cfg['static_dir'], listen_host, listen_port, cfg['prom_prefix'] or '/', cfg['upstream'],
                cfg['config_js'],
                'bearer token' if cfg['auth_token'] else 'none (the loopback bind is the auth)',
                cfg['level'],
                'local' if cfg['local_time'] else 'UTC',
                'on' if cfg['log_access'] else 'off',
                'on' if cfg['log_queries'] else 'off',
                ', '.join(limits) if limits else 'off',
                control_desc,
                ('metrics: %s' % args.metrics_desc) if getattr(args, 'metrics_desc', 'off') != 'off' else 'metrics: off',
                version_string()))


def parse_args():
    ap = build_parser(OPTIONS, description='Static file server with a Prometheus proxy at /prom')
    ap.add_argument('--config', default=default_config_path(SCRIPT_DIR, 'server.conf'),
                    help='config file — the set grammar: every line a `set <name> <value>`, comments start with # ($CONFIG, then server.conf next to this script, then the subproject root)')
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

    apply_restart_state(cfg, args.config, cfg['dump_key'], ControlServer,
                        extra={'system/listen': fold_listen})
    listen_host, listen_port = parse_listen(cfg['listen'])   # the fold may have moved it
    control_target = resolve_control_target(cfg['control_port'], listen_port, CONTROL_SOCKET_TEMPLATE)
    control_token = cfg['control_token'] or None
    control_ops_token = cfg['control_ops_token'] or None
    trust_uids = parse_trust_uids(cfg['control_trust_uids'], 'control-trust-uids')
    ops_verbs = parse_ops_verbs(cfg['control_ops_verbs'], KNOWN_VERBS)
    metrics_token = parse_secret(args.metrics_token or cfg.get('metrics_token'), 'metrics/token')
    metrics_listen = parse_listen(cfg.get('metrics_listen') or DEFAULTS.get('metrics_listen', '127.0.0.1:9353'))
    metrics_acl, metrics_acl_warn = resolve_metrics_acl(cfg.get('metrics_acl') or 'any', 'metrics/acl')
    if cfg['metrics_server'] and not metrics_token and not is_loopback_host(metrics_listen[0]):
        logger.error('refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md): '
                     'listen = %r — set --metrics-token (or file:<path>) or bind 127.0.0.1:PORT'
                     % (cfg.get('metrics_listen') or DEFAULTS.get('metrics_listen', '127.0.0.1:9353')))
        raise SystemExit(2)
    if not cfg['auth_token'] and not is_loopback_host(listen_host):
        logger.error('refusing to expose the page beyond loopback without a token (F21 in docs/AUDIT.md): '
                     'listen = %r — set --auth-token (or file:<path>) or bind 127.0.0.1' % cfg['listen'])
        raise SystemExit(2)
    metrics_desc = 'off'
    if cfg['metrics_server']:
        metrics_desc = describe_metrics(metrics_listen, metrics_token, cfg.get('metrics_max_clients', 16),
                                        cfg.get('metrics_max_conn_per_ip', 0))
    audit_params = {'path': None if cfg['no_audit_log'] else cfg['audit_log'],
                    'max_mb': cfg['audit_max_mb'], 'files': cfg['audit_files'],
                    'daily': cfg['audit_daily'], 'disabled': bool(cfg['no_audit_log'])}
    audit = None if cfg['no_audit_log'] else AuditLog(cfg['audit_log'], 'DSH', app='dashboard',
                                                      max_mb=cfg['audit_max_mb'], daily=cfg['audit_daily'],
                                                      files=cfg['audit_files'])
    control_desc = 'off' if control_target == '0' \
        else ('127.0.0.1:%s' % control_target if control_target.isdigit() else 'unix:%s' % control_target)
    Handler.upstream = cfg['upstream']
    Handler.log_queries = cfg['log_queries']
    Handler.log_access = cfg['log_access']
    Handler.static_dir = cfg['static_dir']
    Handler.config_js = cfg['config_js']
    Handler.prom_prefix = cfg['prom_prefix']
    Handler.auth_token = cfg['auth_token']
    Handler.timeout = cfg['client_timeout'] or None
    args.metrics_desc = metrics_desc
    logger.info('%s', describe(cfg, args, control_desc))
    log_state_dumps(cfg['dump_path'], cfg['dump_key'], cfg['restore_on_start'])
    if args.dry_run:
        logger.info('dry-run: configuration is valid, nothing was bound')
        return
    try:
        httpd = Server((listen_host, listen_port), Handler)
    except OSError as e:
        logger.error('cannot bind %s:%d: %s', listen_host, listen_port, e)
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
            'log-level': cfg['level'],
            # the startup-only knobs (restart: true) — what `show <knob>` answers
            'system/listen': cfg['listen'],
            'upstream': cfg['upstream'],
            'prom-prefix': cfg['prom_prefix'] or 'off',
            'static-dir': cfg['static_dir'] or 'off',
            'config-js': cfg['config_js'] or 'off',
            'control/port': control_target,
            'control/ops/verbs': ','.join(sorted(ops_verbs)) if ops_verbs else 'off',
            'control/trust-uids': ','.join(str(u) for u in sorted(trust_uids or [])) if trust_uids else 'off',
            'control/socket-group': 'on' if cfg['control_socket_group'] else 'off',
            'metrics-listen': cfg['metrics_listen'],
            'metrics/acl': acl_value_text(metrics_acl),
            'metrics-max-clients': str(cfg['metrics_max_clients']),
            'metrics-client-timeout': '%g' % cfg['metrics_client_timeout'],
            'metrics-max-conn-per-ip': str(cfg['metrics_max_conn_per_ip']),
            'dump/path': cfg['dump_path'] or 'off',
            'dump/restore-on-start': 'on' if cfg['restore_on_start'] else 'off',
            'dump-interval': 'off' if not cfg['dump_interval'] else '%g' % cfg['dump_interval'],
            'audit-log': 'off' if cfg['no_audit_log'] else ('stdout' if cfg['audit_log'] == '-'
                                                            else (cfg['audit_log'] or 'the XDG state home')),
            'audit-max-mb': '%g' % cfg['audit_max_mb'],
            'audit/rotate/daily': 'on' if cfg['audit_daily'] else 'off',
            'audit-files': str(cfg['audit_files']),
            'no-audit-log': 'on' if cfg['no_audit_log'] else 'off',
            'local-time': 'on' if cfg['local_time'] else 'off',
        }
        # the secret rows (control/token, control/ops/token, metrics/token,
        # auth/token) carry NO defaults entry: `unset` refuses them (the
        # metrics/token treatment) — a secret never renders, never re-applies
        control = ControlServer(httpd, int(control_target) if control_target.isdigit() else control_target,
                                audit=audit, token=control_token, defaults=defaults, trust_uids=trust_uids,
                                audit_params=audit_params,
                                socket_group=cfg['control_socket_group'],
                                ops_token=control_ops_token, ops_verbs=ops_verbs, config_path=args.config,
                                dump_path=cfg['dump_path'], restore_on_start=cfg['restore_on_start'],
                                dump_key=cfg['dump_key'], dump_interval=cfg['dump_interval'],
                                # the secret rows' configured-ness for `show config`
                                # (the values never render — config_value refuses them)
                                startup_values={'control_token': control_token,
                                                'control_ops_token': control_ops_token,
                                                'control_port': control_target,
                                                'control_ops_verbs': ','.join(sorted(ops_verbs)) if ops_verbs else 'off',
                                                'control_trust_uids': ','.join(str(u) for u in sorted(trust_uids or [])) or 'off',
                                                'control_socket_group': cfg['control_socket_group'],
                                                'metrics_token': metrics_token,
                                                'metrics_acl': acl_value_text(metrics_acl),
                                                'auth_token': cfg['auth_token'],
                                                'audit_log': cfg['audit_log'],
                                                'audit_max_mb': cfg['audit_max_mb'],
                                                'audit_daily': cfg['audit_daily'],
                                                'audit_files': cfg['audit_files'],
                                                'no_audit_log': cfg['no_audit_log'],
                                                'log_level': cfg['level'],
                                                'dump_key': cfg.get('dump_key')})
        control.start()
        if control.dump_path and cfg['restore_on_start']:
            logger.info('restore-on-start: %s', control.restore_state())
        # the dumper thread always runs (it parks while dump-interval is off):
        # a live `set dump-interval` wakes it without a restart — and a live
        # `set dump/path` (no path at start) finds the thread waiting too
        threading.Thread(target=control.run_dump_interval, daemon=True, name='dump').start()
    metrics_srv = None
    if cfg['metrics_server']:
        metrics_srv = MetricsServer(httpd, control, metrics_listen, token=metrics_token, started=started,
                                    max_clients=cfg.get('metrics_max_clients', 16),
                                    client_timeout=cfg.get('metrics_client_timeout', 5),
                                    max_per_ip=cfg.get('metrics_max_conn_per_ip', 0), acl=metrics_acl)
        metrics_srv.start()
        httpd.metrics_srv = metrics_srv
    if control:
        # the control always knows the metrics state: the live token
        # rotation and the metrics enable toggle re-describe from here
        control.metrics_srv = metrics_srv
        control.metrics_token = metrics_token
        control.metrics_listen = metrics_listen
        control.metrics_acl = metrics_acl
        control.metrics_acl_warn = metrics_acl_warn
        control.metrics_desc = metrics_desc

    def apply_reload():
        """The SIGHUP and the `request reload-config` command share this: re-resolve
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
        Handler.timeout = new_cfg['client_timeout'] or None
        httpd.gate.max_total = new_cfg['max_clients']
        httpd.gate.max_per_ip = new_cfg['max_conn_per_ip']
        logging.getLogger().setLevel(getattr(logging, new_cfg['level'], logging.INFO))
        if control:
            control.clear_overrides()   # the config won: nothing is live-overridden
            # the dump-interval loop re-reads the configured interval (the
            # parked dumper wakes to see it)
            control.dump_interval = new_cfg['dump_interval']
            control.dump_wake.set()
        if audit:
            audit.event('RELOAD', 'upstream %s' % new_cfg['upstream'])
        return 'upstream %s' % new_cfg['upstream']

    if control:
        control.reloader = apply_reload   # the control server's `request reload-config` runs the same path

    def graceful_stop(reason):
        logger.info('shutdown: %s received after %ds, stopping the web server',
                    reason, time.monotonic() - started)
        if audit:
            audit.event('SHUTDOWN', '%s: uptime=%ds' % (reason, int(time.monotonic() - started)))
        if control:
            control.shutdown_dump()   # the write-behind: the overrides ride the next start
            control.announce_exit(reason)   # the consoles print the notice and exit
            control.cleanup()
        httpd.shutdown()

    if control:
        control.stopper = graceful_stop
    install_signal_handlers(apply_reload=apply_reload, graceful_stop=graceful_stop)
    if audit:
        audit.event('START', 'version=%s upstream=%s listen=%s:%d control=%s'
                    % (version_string(), cfg['upstream'], listen_host, listen_port, control_desc))
        if metrics_acl_warn:   # the start resolve warned before the audit existed — the ACL-FILE event lands after START
            audit.event('ACL-FILE', metrics_acl_warn)
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
