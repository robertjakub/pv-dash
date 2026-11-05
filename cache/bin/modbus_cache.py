#!/usr/bin/env python3
"""Modbus TCP caching proxy for Huawei SUN2000 inverters (stdlib only).

The inverter (or its SDongle/EMMA) accepts only a single Modbus TCP client.
This proxy owns that one upstream connection: a background loop polls the
configured register ranges at a fixed interval while any number of clients
connect and are served FC3 reads from the in-memory cache. Reads outside the
cached ranges and every other function code are forwarded to the inverter
(serialized, one at a time).

Layout: common/protocol (the wire core), lib/upstream (inverter connection),
lib/cache (register cache + block plan), lib/proxy (poller + client
handling), lib/control (JSON-lines control server), common/audit (the
append-only audit trail), common/version, this file (CLI, logging, signals).
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

from common.audit import AuditLog, default_path as default_audit_path
from common.config import default_profile_path, load_token_file, parse_listen
from common.logutil import UtcFormatter
from common.protocol import exception_frame
from common.version import version_string
from lib.config import load_registers_file, load_selection, resolve_config, parse_control_target, acl_text, acl_summary
from lib import persist
from lib.upstream import Upstream
from lib.cache import Cache
from lib.proxy import Proxy
from lib.control import ControlServer
from lib.metrics import MetricsServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def default_config_path():
    """$MODBUS_CACHE_CONFIG wins (the docker config volume); then a user's
    ini next to the script (the flattened package layout); then the dev
    checkout's sample at the subproject root."""
    env = os.environ.get('MODBUS_CACHE_CONFIG')
    if env and env.strip():
        return env.strip()
    for candidate in (os.path.join(SCRIPT_DIR, 'modbus_cache.ini'),
                      os.path.join(os.path.dirname(SCRIPT_DIR), 'modbus_cache.ini')):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(SCRIPT_DIR, 'modbus_cache.ini')

logger = logging.getLogger('modbus-cache')


def parse_args():
    ap = argparse.ArgumentParser(description='Modbus TCP caching proxy for Huawei SUN2000 inverters.')
    ap.add_argument('--config', default=default_config_path(),
                    help='config file (default: $MODBUS_CACHE_CONFIG, then modbus_cache.ini next to this script, then the subproject root)')
    ap.add_argument('--host', help='inverter Modbus TCP address (default: config, $MODBUS_CACHE_HOST or 127.0.0.1)')
    ap.add_argument('--port', type=int, help='inverter Modbus TCP port (default: config, $MODBUS_CACHE_PORT or 5502)')
    ap.add_argument('--unit', type=int, help='Modbus unit id (default: config, $MODBUS_CACHE_UNIT or 1)')
    ap.add_argument('--timeout', type=float, help='Modbus connect/read timeout in seconds (default: config, $MODBUS_CACHE_TIMEOUT or 3)')
    ap.add_argument('--listen', help='listen address HOST:PORT (default: config, $MODBUS_CACHE_LISTEN or 127.0.0.1:15502)')
    ap.add_argument('--interval', type=float, help='seconds between cache polls (default: config, $MODBUS_CACHE_INTERVAL or 10)')
    ap.add_argument('--read-delay', type=float, help='seconds between consecutive inverter reads within a poll cycle, 0 = no delay (default: config, $MODBUS_CACHE_READ_DELAY or 0.05)')
    ap.add_argument('--merge-gap', type=int, help='max register gap when merging ranges into block reads, 0 = read ranges separately (default: config, $MODBUS_CACHE_MERGE_GAP or 8)')
    ap.add_argument('--profile', dest='profile',
                    help='device profile JSON (the shared profiles/ schema) (default: config, $MODBUS_CACHE_PROFILE or the bundled sun2000 profile)')
    ap.add_argument('--selection', dest='selection',
                    help='selection JSON: {"registers": ["pv-power", ...]} — the profile names to fetch (default: config, $MODBUS_CACHE_SELECTION or every profile entry)')
    ap.add_argument('--cache-ttl', type=float, help='per-register cache TTL: cached registers older than this are refetched from the inverter, 0 = never expire, serve last known values forever (default: config, $MODBUS_CACHE_TTL or 3x interval)')
    ap.add_argument('--allow-write', action='store_true', help='forward write requests (FC05/06/15/16) to the inverter; default: refuse them with a Modbus illegal-function exception')
    ap.add_argument('--write-registers', dest='write_registers',
                    help='register ranges a (forwarded) write may touch: comma-separated START:COUNT, e.g. 47400:100,47600:100; "any" = unrestricted; "none" = no register writable (default: config, $MODBUS_CACHE_WRITE_REGISTERS or none)')
    ap.add_argument('--local-time', action='store_true', help='log timestamps in the system time zone instead of UTC')
    ap.add_argument('--log-access', action='store_true', help='log client connects/disconnects at INFO instead of DEBUG')
    ap.add_argument('--max-clients', type=int, help='refuse further connections past this many simultaneous clients, 0 = no limit (default: config, $MODBUS_CACHE_MAX_CLIENTS or 64)')
    ap.add_argument('--client-timeout', type=float, help='disconnect clients silent for this many seconds, 0 = never (default: config, $MODBUS_CACHE_CLIENT_TIMEOUT or 300)')
    ap.add_argument('--connect-acl', help='clients allowed to connect: "any", "none" (refuse everyone) or comma-separated IPs/prefixes like 10.0.0.7,10.48.0.0/16 (default: config, $MODBUS_CACHE_CONNECT_ACL or any)')
    ap.add_argument('--write-acl', help='clients allowed to write (requires --allow-write): "any", "none" (refuse everyone) or comma-separated IPs/prefixes (default: config, $MODBUS_CACHE_WRITE_ACL or none)')
    ap.add_argument('--control-port', dest='control_port',
                    help='control server target: unix socket path or TCP port on 127.0.0.1 (default: config, $MODBUS_CACHE_CTL or /tmp/modbus-cache-<listen-port>.socket); 0 = off')
    ap.add_argument('--control-token', dest='control_token',
                    help='require a token on control connections: the client authenticates with {"cmd": "auth", "token": ...}; over the unix socket a trusted peer (root, the daemon\'s own user or --control-trust-uids — SO_PEERCRED) skips the token (default: config, $MODBUS_CACHE_CONTROL_TOKEN or none)')
    ap.add_argument('--control-token-file', dest='control_token_file',
                    help='the token from a file (the first line; e.g. a systemd LoadCredential or a key file; must be owner-only 0600) — takes the place of --control-token; giving both is an error (default: config, $MODBUS_CACHE_CONTROL_TOKEN_FILE)')
    ap.add_argument('--control-socket-group', dest='control_socket_group', action='store_true',
                    help='leave the unix control socket group-accessible (chmod 0660 instead of the default 0600) (default: config, $MODBUS_CACHE_CONTROL_SOCKET_GROUP)')
    ap.add_argument('--requests-audit', dest='requests_audit', type=float,
                    help='audit one REQUESTS tally per client per this many seconds, 0 = off (default: config, $MODBUS_CACHE_REQUESTS_AUDIT or 300)')
    ap.add_argument('--dump-path', dest='dump_path',
                    help='the state dump (write-behind): the cached words + the live setting overrides as one JSON; dumped on shutdown, on the request dump command and every --dump-interval seconds; loaded on start only with --restore-on-start, on demand with the request restore command (default: config, $MODBUS_CACHE_DUMP_PATH or none)')
    ap.add_argument('--dump-interval', dest='dump_interval', type=float,
                    help='seconds between the automatic state dumps, 0 = on request (the request dump command and the shutdown) (default: config, $MODBUS_CACHE_DUMP_INTERVAL or 0)')
    ap.add_argument('--restore-on-start', dest='restore_on_start', action='store_true',
                    help='load the state dump when the daemon starts (needs --dump-path) — a restart serves last-known values instead of cold misses; default: start cold, load only on demand (env MODBUS_CACHE_RESTORE_ON_START, ini restore_on_start)')
    ap.add_argument('--control-trust-uids', dest='control_trust_uids',
                    help='extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon\'s own user are always trusted (default: config, $MODBUS_CACHE_CONTROL_TRUST_UIDS or none)')
    ap.add_argument('--metrics-port', dest='metrics_port', type=int, default=0,
                    help="serve the cache's own Prometheus /metrics on 127.0.0.1:PORT; 0 = off (the default)")
    ap.add_argument('--metrics-token', dest='metrics_token',
                    help='require Authorization: Bearer <token> on the /metrics endpoint (the same scheme the scraper speaks)')
    ap.add_argument('--metrics-token-file', dest='metrics_token_file',
                    help='the metrics bearer token from a file (the first line; must be owner-only 0600) — takes the place of --metrics-token; giving both is an error (env MODBUS_CACHE_METRICS_TOKEN_FILE)')
    ap.add_argument('--audit-log', dest='audit_log',
                    help='CACHE audit trail: a file path or - for stdout (the docker/journald way); default: config, $MODBUS_CACHE_AUDIT_LOG or %s — the XDG state home' % default_audit_path('modbus-cache'))
    ap.add_argument('--audit-max-mb', dest='audit_max_mb', type=float,
                    help='rotate the audit log at this size in MB, keeping N backups; 0 = no size rotation (default: config, $MODBUS_CACHE_AUDIT_MAX_MB or 10)')
    ap.add_argument('--audit-daily', dest='audit_daily', action='store_true',
                    help='also rotate the audit log at UTC midnight (default: config, $MODBUS_CACHE_AUDIT_DAILY)')
    ap.add_argument('--audit-files', dest='audit_files', type=int,
                    help='rotated audit backups to keep (default: config, $MODBUS_CACHE_AUDIT_FILES or 3)')
    ap.add_argument('--no-audit-log', dest='no_audit_log', action='store_true',
                    help='disable the CACHE audit trail (default: config, $MODBUS_CACHE_NO_AUDIT_LOG)')
    ap.add_argument('--dry-run', action='store_true', help='validate the configuration and register map, print the effective settings and exit (nothing is bound or connected)')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='log level (default: config, $MODBUS_CACHE_LOG_LEVEL or INFO)')
    return ap.parse_args()


def setup_logging(cfg):
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg['level'], logging.INFO))
    fmt = '%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM') \
        else '%(asctime)s %(levelname)-7s %(message)s'
    handler = logging.StreamHandler()
    handler.setFormatter(UtcFormatter(fmt) if not cfg['local_time'] else logging.Formatter(fmt))
    root.addHandler(handler)


def install_signal_handlers(proxy, cache, args):
    def graceful_stop(reason):
        logger.info('shutdown: %s, closing the listener', reason)
        if proxy.dump_path:
            try:
                n = persist.write_dump(proxy.dump_path, proxy.cache,
                                       proxy.control.dump_settings() if getattr(proxy, 'control', None) else None)
                logger.info('state dumped to %s (%d word(s))', proxy.dump_path, n)
            except OSError as e:
                logger.error('the shutdown dump to %s failed: %s', proxy.dump_path, e)
        if proxy.audit:
            proxy.audit.event('SHUTDOWN', '%s: uptime=%ds clients=%d hits=%d misses=%d'
                              % (reason, int(time.monotonic() - proxy.started), proxy.client_count,
                                 proxy.cache_hits, proxy.cache_misses))
        proxy.stopping = True
        ctl = getattr(proxy, 'control', None)
        if ctl:
            ctl.announce_exit(reason)   # the consoles print the notice and exit
            ctl.cleanup()
        try:
            proxy.listen_sock.close()
        except OSError:
            pass
        for h in logging.getLogger().handlers:
            h.flush()
        time.sleep(0.2)   # let the serve loop log 'stopped' ...
        os._exit(0)       # ... as a backstop if it somehow didn't

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
                    proxy.config = resolve_config(args, SCRIPT_DIR)
                    proxy.reload()
                    ctl = getattr(proxy, 'control', None)
                    if ctl:
                        ctl.clear_overrides()   # the config won: nothing is live-overridden
                    if proxy.audit:
                        proxy.audit.event('RELOAD', '%d range(s) from %s' % (len(proxy.cache.ranges),
                                                                             proxy.config['profile']))
                except (Exception, SystemExit) as e:
                    logger.error('SIGHUP: reload failed (%s), keeping the previous settings', e)
                    if proxy.audit:
                        proxy.audit.event('RELOAD', 'failed: %s' % e)

        signal.signal(signal.SIGHUP, on_hup)
        threading.Thread(target=watch_reload, daemon=True).start()
    if hasattr(signal, 'SIGUSR1'):
        clean_requested = threading.Event()

        def on_usr1(signum, frame):
            clean_requested.set()

        def watch_clean():
            while True:
                clean_requested.wait()
                clean_requested.clear()
                dropped = cache.clear()
                proxy.poll_wake.set()
                logger.info('SIGUSR1: cache cleared (%d register(s) dropped), repolling now', dropped)
                if proxy.audit:
                    proxy.audit.event('RESET', 'SIGUSR1: %d register(s) dropped' % dropped)

        signal.signal(signal.SIGUSR1, on_usr1)
        threading.Thread(target=watch_clean, daemon=True).start()
    if hasattr(signal, 'SIGTERM'):
        stop_signal = []

        def on_stop(signum, frame):
            stop_signal.append(signum)

        def watch_stop():
            while not stop_signal:
                time.sleep(0.2)
            graceful_stop('%s received' % signal.Signals(stop_signal[0]).name)

        signal.signal(signal.SIGTERM, on_stop)
        signal.signal(signal.SIGINT, on_stop)
        threading.Thread(target=watch_stop, daemon=True).start()
    return graceful_stop


def main():
    args = parse_args()
    cfg = resolve_config(args, SCRIPT_DIR)
    if cfg['selection'] == 'none':
        ranges, range_names, range_ttls = [], {}, {}   # cache nothing: every read forwards
    else:
        ranges, range_names, range_ttls = load_registers_file(cfg['profile'])
        if cfg['selection']:
            ranges, range_names, range_ttls = load_selection(cfg['selection'], range_names, range_ttls)

    setup_logging(cfg)

    listen_host, listen_port = parse_listen(cfg['listen'])
    control_target = parse_control_target(cfg['control_port'], listen_port)
    control_token = cfg['control_token'] or None
    if cfg['control_token_file']:
        control_token = load_token_file(cfg['control_token_file'])
    if isinstance(control_target, int) and not control_token:
        logger.error('the TCP control port %d without a token is open to every local process; '
                     'set --control-token or --control-token-file (the default unix socket needs none), '
                     'or disable it with --control-port 0', control_target)
        raise SystemExit(2)
    if args.metrics_token and args.metrics_token_file:
        logger.error('--metrics-token and --metrics-token-file are mutually exclusive')
        raise SystemExit(2)
    metrics_token = args.metrics_token or os.environ.get('MODBUS_CACHE_METRICS_TOKEN')
    if args.metrics_token_file:
        metrics_token = load_token_file(args.metrics_token_file, 'metrics-token-file')
    if args.metrics_port and not metrics_token:
        logger.error('the metrics endpoint serves register values: set --metrics-token or '
                     '--metrics-token-file when --metrics-port is on (or drop --metrics-port)')
        raise SystemExit(2)
    metrics_desc = 'off'
    if args.metrics_port:
        if not 0 < args.metrics_port <= 65535:
            logger.error('--metrics-port out of range: %d', args.metrics_port)
            raise SystemExit(2)
        metrics_desc = '127.0.0.1:%d%s' % (args.metrics_port, ' (bearer token)' if metrics_token else '')
    if cfg['no_audit_log']:
        audit_display = 'off'
    elif cfg['audit_log'] == '-':
        audit_display = 'stdout'
    else:
        audit_display = cfg['audit_log'] or default_audit_path('modbus-cache')
    upstream = Upstream(cfg['host'], cfg['port'], cfg['unit'], cfg['timeout'])
    cache = Cache(ranges, cfg['cache_ttl'], range_names, range_ttls)
    proxy = Proxy(upstream, cache, cfg['read_delay'], cfg['merge_gap'], cfg['interval'],
                  cfg['profile'], cfg)
    proxy.metrics_desc = metrics_desc
    proxy.dump_path = cfg['dump_path'] or None
    proxy.dump_interval = cfg['dump_interval']
    logger.info('caching %d range(s) from %s (%s:%d unit %d) every %gs, %gs between reads, merge gap %d, cache ttl %gs, write support %s, client access log at %s; %s Modbus TCP on %s:%d (config: %s, log level: %s, log time: %s, client limit: %s, client timeout: %s, connect acl: %s, write acl: %s, write allow-list: %s, control token: %s, audit trail: %s, requests audit: %s, metrics: %s)',
                len(ranges), cfg['selection'] or cfg['profile'], cfg['host'], cfg['port'], cfg['unit'], cfg['interval'],
                cfg['read_delay'], cfg['merge_gap'], cfg['cache_ttl'],
                'ENABLED' if cfg['allow_write'] else 'disabled (write requests are refused)',
                'INFO' if cfg['log_access'] else 'DEBUG',
                'would serve' if args.dry_run else 'serving',
                listen_host, listen_port, args.config, cfg['level'],
                'local' if cfg['local_time'] else 'UTC',
                cfg['max_clients'] or 'none', '%gs' % cfg['client_timeout'] if cfg['client_timeout'] else 'none',
                acl_summary(cfg['connect_acl']),
                acl_summary(cfg['write_acl']),
                proxy.describe_write_ranges(),
                'required on TCP' if control_token else 'none',
                audit_display,
                '%gs' % cfg['requests_audit_s'] if cfg['requests_audit_s'] else 'off',
                metrics_desc)
    logger.info('state dumps: %s',
                'off' if not proxy.dump_path
                else '%s every %s (plus request dump and the shutdown), restore on start'
                % (proxy.dump_path, 'off' if not proxy.dump_interval else '%gs' % proxy.dump_interval))
    proxy.log_map()
    if args.dry_run:
        logger.info('dry-run: configuration and register map are valid, nothing was bound or connected (control server would listen on %s)',
                    'off' if control_target is None else
                    ('127.0.0.1:%d' % control_target if isinstance(control_target, int) else control_target))
        return
    audit = None if cfg['no_audit_log'] else AuditLog(cfg['audit_log'] or None, 'CACHE',
                                                      app='modbus-cache', max_mb=cfg['audit_max_mb'],
                                                      daily=cfg['audit_daily'], files=cfg['audit_files'])
    proxy.audit = audit
    if audit:
        audit.event('START', 'version=%s upstream=%s:%d unit=%d listen=%s:%d control=%s profile=%s'
                    % (version_string(), cfg['host'], cfg['port'], cfg['unit'], listen_host, listen_port,
                       'off' if control_target is None else
                       ('127.0.0.1:%d' % control_target if isinstance(control_target, int) else control_target),
                       cfg['selection'] or cfg['profile']))
    stop = install_signal_handlers(proxy, cache, args)
    if control_target is not None:
        defaults = {'interval': '%g' % cfg['interval'],
                    'ttl': 'off' if not cfg['cache_ttl'] else '%g' % cfg['cache_ttl'],
                    'read-delay': '%g' % cfg['read_delay'],
                    'merge-gap': '%d' % cfg['merge_gap'],
                    'allow-write': 'on' if cfg['allow_write'] else 'off',
                    'write-registers': proxy.describe_write_ranges(),
                    'max-clients': '%d' % cfg['max_clients'],
                    'client-timeout': '%g' % cfg['client_timeout'],
                    'requests-audit': 'off' if not cfg['requests_audit_s'] else '%g' % cfg['requests_audit_s'],
                    'dump-interval': 'off' if not cfg['dump_interval'] else '%g' % cfg['dump_interval'],
                    'log-level': cfg['level'],
                    'profile': cfg['profile'],
                    'selection': cfg['selection'] or 'all',
                    'connect-acl': acl_text(cfg['connect_acl']),
                    'write-acl': acl_text(cfg['write_acl']),
                    'timeout': '%g' % cfg['timeout']}
        proxy.control = ControlServer(proxy, control_target, stop, audit=audit,
                                      token=control_token, defaults=defaults,
                                      trust_uids=cfg['control_trust_uids'],
                                      socket_group=cfg['control_socket_group'])
        proxy.control.start()
    if proxy.dump_path:
        if not cfg['restore_on_start']:
            if os.path.exists(proxy.dump_path):
                logger.info('the state dump %s exists, not loaded on start (restore-on-start is off; request restore loads it on demand)',
                            proxy.dump_path)
        elif os.path.exists(proxy.dump_path):
            try:
                words, stamps, settings = persist.read_dump(proxy.dump_path)
                n = 0 if proxy.no_cache else cache.restore(words, stamps)
                applied, failed = (proxy.control.apply_dump_settings(settings)
                                   if getattr(proxy, 'control', None) else (0, ['no control server']))
                logger.info('restored the state dump %s: %d word(s), %d setting(s)%s',
                            proxy.dump_path, n, applied,
                            (' (%d skipped: %s)' % (len(failed), ', '.join(failed))) if failed else '')
                if audit:
                    audit.event('RESTORE', '%s: %d word(s), %d setting(s)' % (proxy.dump_path, n, applied))
            except ValueError as e:
                logger.error('cannot restore the state dump %s: %s (starting cold)', proxy.dump_path, e)
        else:
            logger.info('no state dump at %s yet, starting cold', proxy.dump_path)
        # the dumper thread always runs (it parks while dump-interval is off):
        # a live `set dump-interval` wakes it without a restart
        def watch_dump():
            while not proxy.stopping:
                if not proxy.dump_interval:
                    proxy.dump_wake.wait()
                    proxy.dump_wake.clear()
                    continue
                if proxy.dump_wake.wait(proxy.dump_interval):
                    proxy.dump_wake.clear()
                if proxy.stopping:
                    break
                try:
                    n = persist.write_dump(proxy.dump_path, proxy.cache,
                                           proxy.control.dump_settings() if getattr(proxy, 'control', None) else None)
                    logger.debug('state dumped to %s (%d word(s))', proxy.dump_path, n)
                except (OSError, ValueError) as e:
                    logger.error('the periodic dump to %s failed: %s', proxy.dump_path, e)
        threading.Thread(target=watch_dump, daemon=True, name='dump').start()
    if args.metrics_port:
        MetricsServer(proxy, args.metrics_port, token=metrics_token,
                      started=time.monotonic()).start()
    try:
        threading.Thread(target=proxy.poll_loop, daemon=True).start()
        proxy.serve(listen_host, listen_port)
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        if proxy.stopping:
            logger.info('stopped')
            return
        logger.error('cannot serve on %s:%d: %s', listen_host, listen_port, e)
        raise SystemExit(1)
    finally:
        upstream.close()
        if audit:
            audit.close()


if __name__ == '__main__':
    main()
