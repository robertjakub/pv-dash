#!/usr/bin/env python3
"""Modbus TCP caching proxy for single-client devices (stdlib only).

A Modbus TCP device that accepts only a single client (an inverter, its
SDongle/EMMA radio — the bundled device profile is the Huawei SUN2000 map)
allows exactly one consumer.
This proxy owns that one upstream connection: a background loop polls the
configured register ranges at a fixed interval while any number of clients
connect and are served FC3 reads from the in-memory cache. Reads outside the
cached ranges and every other function code are forwarded to the device
(serialized, one at a time).

Layout: common/modbus (the wire core package), lib/upstream (inverter connection),
lib/cache (register cache + block plan), lib/proxy (poller + client
handling), lib/control (JSON-lines control server), common/audit (the
append-only audit trail), common/version, this file (CLI, logging, signals).
"""
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
from common.config import default_profile_path, parse_listen, parse_secret
from common.logutil import UtcFormatter
from common.options import build_parser
from common.modbus import exception_frame
from common.version import version_string
from lib.config import load_registers_file, load_selection, resolve_config, parse_control_target, acl_text, acl_summary
from lib.options import KNOWN_VERBS, OPTIONS
from lib.metrics import MetricsServer, describe_metrics
from lib import persist
from lib.upstream import Upstream
from lib.cache import Cache
from lib.proxy import Proxy
from lib.control import ControlServer
from lib.metrics import MetricsServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def default_config_path():
    """$CONFIG wins (the docker config volume); then a user's
    config script next to the script (the flattened package layout); then
    the dev checkout's sample at the subproject root."""
    env = os.environ.get('CONFIG')
    if env and env.strip():
        return env.strip()
    for candidate in (os.path.join(SCRIPT_DIR, 'modbus_cache.conf'),
                      os.path.join(os.path.dirname(SCRIPT_DIR), 'modbus_cache.conf')):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(SCRIPT_DIR, 'modbus_cache.conf')

logger = logging.getLogger('modbus-cache')


def parse_args():
    ap = build_parser(OPTIONS, description='Modbus TCP caching proxy for single-client devices.')
    ap.add_argument('--config', default=None,
                    help='config file — the set grammar: every line a `set <name> <value>`, comments start with # (default: $CONFIG, then modbus_cache.conf next to this script, then the subproject root)')
    ap.add_argument('--dry-run', action='store_true', help='validate the configuration and register map, print the effective settings and exit (nothing is bound or connected)')
    ap.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (modbus-cache --man | man -l -)')
    args = ap.parse_args()
    if args.man:
        from lib.man import daemon_page
        sys.stdout.write(daemon_page(ap))
        raise SystemExit(0)
    if args.config is None:
        args.config = default_config_path()
    return args


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
                                       proxy.control.dump_settings() if getattr(proxy, 'control', None) else None,
                                       with_cache=proxy.dump_with_cache, key=proxy.dump_key)
                logger.info('state dumped to %s (%d word(s), %s%s)', proxy.dump_path, n,
                            'with cache' if proxy.dump_with_cache else 'settings only',
                            ', sealed' if proxy.dump_key else '')
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
    control_ops_token = cfg['control_ops_token'] or None
    if control_ops_token and not control_token:
        logger.error('the read-only ops token supplements the admin token: set --control-token too '
                     '(an ops token alone would leave the control plane unusable)')
        raise SystemExit(2)
    if control_ops_token and control_ops_token == control_token:
        logger.error('the ops token must differ from the admin token (the same secret would hand '
                     'every holder the role the server picks first)')
        raise SystemExit(2)
    ops_verbs = frozenset(v.strip().lower() for v in (cfg['control_ops_verbs'] or 'show,clear').split(',') if v.strip())
    unknown = sorted(v for v in ops_verbs if v not in KNOWN_VERBS)
    if not ops_verbs or unknown:
        logger.error('--control-ops-verbs: %s (the ops policy needs at least one verb the grammar speaks: %s)',
                     ', '.join(unknown) if unknown else 'empty', ', '.join(sorted(KNOWN_VERBS)))
        raise SystemExit(2)
    if isinstance(control_target, int) and not control_token:
        logger.error('the TCP control port %d without a token is open to every local process; '
                     'set --control-token (the default unix socket needs none), '
                     'or disable it with --control-port 0', control_target)
        raise SystemExit(2)
    metrics_token = parse_secret(args.metrics_token or os.environ.get('METRICS_TOKEN'), 'metrics/token')
    metrics_listen = parse_listen(cfg['metrics_listen'])
    if cfg['metrics_server'] and not metrics_token:
        logger.error('the metrics endpoint serves register values: set --metrics-token '
                     '(or file:<path>) when --metrics-server is on (or drop --metrics-server)')
        raise SystemExit(2)
    metrics_desc = 'off'
    if cfg['metrics_server']:
        metrics_desc = describe_metrics(metrics_listen, metrics_token,
                                        cfg['metrics_max_clients'], cfg['metrics_max_conn_per_ip'])
    if cfg['no_audit_log']:
        audit_display = 'off'
    elif cfg['audit_log'] == '-':
        audit_display = 'stdout'
    else:
        audit_display = cfg['audit_log'] or default_audit_path('modbus-cache')
    upstream = Upstream(cfg['host'], cfg['port'], cfg['unit'], cfg['timeout'],
                        auth=cfg['auth_upstream'], auth_key=cfg['auth_upstream_key'])
    cache = Cache(ranges, cfg['cache_ttl'], range_names, range_ttls)
    proxy = Proxy(upstream, cache, cfg['read_delay'], cfg['merge_gap'], cfg['interval'],
                  cfg['profile'], cfg)
    proxy.metrics_desc = metrics_desc
    proxy.metrics_srv = MetricsServer(proxy, metrics_listen, token=metrics_token,
                                      max_clients=cfg['metrics_max_clients'],
                                      client_timeout=cfg['metrics_client_timeout'],
                                      max_per_ip=cfg['metrics_max_conn_per_ip'],
                                      started=time.monotonic()) if cfg['metrics_server'] else None
    proxy.metrics_listen = metrics_listen
    proxy.metrics_token = metrics_token
    proxy.metrics_caps = (cfg['metrics_max_clients'], cfg['metrics_client_timeout'],
                          cfg['metrics_max_conn_per_ip'])
    proxy.dump_path = cfg['dump_path'] or None
    proxy.dump_key = cfg['dump_key']   # the dump seal key (startup-only: the reload re-exec re-resolves the same)
    proxy.dump_interval = cfg['dump_interval']
    proxy.dump_with_cache = cfg['dump_with_cache']
    proxy.restore_on_start = cfg['restore_on_start']
    proxy.audit_params = {'path': cfg['audit_log'] or None, 'max_mb': cfg['audit_max_mb'],
                          'daily': cfg['audit_daily'], 'files': cfg['audit_files'],
                          'disabled': bool(cfg['no_audit_log'])}   # the audit lives rebuild from here
    logger.info('caching %d range(s) from %s (%s:%d unit %d) every %gs, %gs between reads, merge gap %d, cache ttl %gs, write support %s, client access log at %s; %s Modbus TCP on %s:%d (config: %s, log level: %s, log time: %s, client limit: %s, client timeout: %s, per-ip limit: %s, connect acl: %s, write acl: %s, write allow-list: %s, client auth: %s, upstream auth: %s, control token: %s, ops token: %s, audit trail: %s, requests audit: %s, metrics: %s)',
                len(ranges), cfg['selection'] or cfg['profile'], cfg['host'], cfg['port'], cfg['unit'], cfg['interval'],
                cfg['read_delay'], cfg['merge_gap'], cfg['cache_ttl'],
                'ENABLED' if cfg['allow_write'] else 'disabled (write requests are refused)',
                'INFO' if cfg['log_access'] else 'DEBUG',
                'would serve' if args.dry_run else 'serving',
                listen_host, listen_port, args.config, cfg['level'],
                'local' if cfg['local_time'] else 'UTC',
                cfg['max_clients'] or 'none', '%gs' % cfg['client_timeout'] if cfg['client_timeout'] else 'none',
                cfg['max_conn_per_ip'] or 'none',
                acl_summary(cfg['connect_acl']),
                acl_summary(cfg['write_acl']),
                proxy.describe_write_gate(),
                cfg['auth'] or 'none', cfg['auth_upstream'] or 'none',
                'required on TCP' if control_token else 'none',
                'read-only ops token set' if control_ops_token else 'no ops token',
                audit_display,
                '%gs' % cfg['requests_audit_s'] if cfg['requests_audit_s'] else 'off',
                metrics_desc)
    logger.info('state dumps: %s',
                'off' if not proxy.dump_path
                else '%s every %s (plus request dump and the shutdown)%s, restore on start'
                % (proxy.dump_path, 'off' if not proxy.dump_interval else '%gs' % proxy.dump_interval,
                   ', sealed' if proxy.dump_key else ''))
    if proxy.dump_path and not proxy.dump_key:
        logger.warning('the state dump %s is not sealed (the integrity hash only — plaintext at rest): '
                       'set dump/key (--dump-key, $DUMP_KEY or set dump-key, a file: reference works) '
                       'to encrypt it', proxy.dump_path)
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
        defaults = {'modbus/interval': '%g' % cfg['interval'],
                    'cache/ttl': 'off' if not cfg['cache_ttl'] else '%g' % cfg['cache_ttl'],
                    'modbus/read-delay': '%g' % cfg['read_delay'],
                    'modbus/merge-gap': '%d' % cfg['merge_gap'],
                    'modbus/upstream': cfg['upstream'],
                    'modbus/unit': '%d' % cfg['unit'],
                    'write/allow': 'on' if cfg['allow_write'] else 'off',
                    'write/registers': proxy.describe_write_ranges(),
                    'limits/max-clients': '%d' % cfg['max_clients'],
                    'limits/client-timeout': '%g' % cfg['client_timeout'],
                    'limits/max-conn-per-ip': '%d' % cfg['max_conn_per_ip'],
                    'metrics/enable': 'on' if cfg['metrics_server'] else 'off',
                    'metrics/listen': '%s:%d' % metrics_listen,
                    'metrics/limits/max-clients': '%d' % cfg['metrics_max_clients'],
                    'metrics/limits/timeout': '%g' % cfg['metrics_client_timeout'],
                    'metrics/limits/max-conn-per-ip': '%d' % cfg['metrics_max_conn_per_ip'],
                    'requests-audit': 'off' if not cfg['requests_audit_s'] else '%g' % cfg['requests_audit_s'],
                    'dump-interval': 'off' if not cfg['dump_interval'] else '%g' % cfg['dump_interval'],
                    'log-level': cfg['level'],
                    'local-time': 'on' if cfg['local_time'] else 'off',
                    'modbus/profile': cfg['profile'],
                    'modbus/selection': cfg['selection'] or 'all',
                    'acl/connect': acl_text(cfg['connect_acl']),
                    'acl/write': acl_text(cfg['write_acl']),
                    'modbus/timeout': '%g' % cfg['timeout'],
                    'modbus/auth': cfg['auth'] or 'none',
                    'modbus/auth-upstream': cfg['auth_upstream'] or 'none',
                    'control/port': control_target,
                    'control/ops-verbs': ','.join(sorted(ops_verbs)) if ops_verbs else 'off',
                    'control/trust-uids': ','.join(str(u) for u in sorted(cfg['control_trust_uids'] or [])) or 'off',
                    'control/socket-group': 'on' if cfg['control_socket_group'] else 'off',
                    'audit/log-file': audit_display,
                    'audit/rotate/max-size': '%g' % cfg['audit_max_mb'],
                    'audit/rotate/daily': 'on' if cfg['audit_daily'] else 'off',
                    'audit/rotate/files': '%d' % cfg['audit_files'],
                    'audit/disable': 'on' if cfg['no_audit_log'] else 'off',
                    'dump/path': cfg['dump_path'] or 'off',
                    'dump/with-cache': 'on' if cfg['dump_with_cache'] else 'off',
                    'dump/restore-on-start': 'on' if cfg['restore_on_start'] else 'off',
                    'log-access': 'on' if cfg['log_access'] else 'off'}
        # the secret rows (control/token, control/ops/token, metrics/token)
        # carry NO defaults entry: `unset` refuses them
        # (the metrics/token treatment) — a secret never renders, never re-applies
        proxy.control = ControlServer(proxy, control_target, stop, audit=audit,
                                      token=control_token, defaults=defaults,
                                      trust_uids=cfg['control_trust_uids'],
                                      socket_group=cfg['control_socket_group'],
                                      ops_token=control_ops_token,
                                      ops_verbs=ops_verbs,
                                      config_path=args.config)
        proxy.control.start()
    if proxy.dump_path:
        if not cfg['restore_on_start']:
            if os.path.exists(proxy.dump_path):
                logger.info('the state dump %s exists, not loaded on start (restore-on-start is off; request restore loads it on demand)',
                            proxy.dump_path)
        elif os.path.exists(proxy.dump_path):
            try:
                words, stamps, settings = persist.read_dump(proxy.dump_path, key=proxy.dump_key)
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
                                           proxy.control.dump_settings() if getattr(proxy, 'control', None) else None,
                                           with_cache=proxy.dump_with_cache, key=proxy.dump_key)
                    logger.debug('state dumped to %s (%d word(s), %s)', proxy.dump_path, n,
                                 'with cache' if proxy.dump_with_cache else 'settings only')
                except (OSError, ValueError) as e:
                    logger.error('the periodic dump to %s failed: %s', proxy.dump_path, e)
        threading.Thread(target=watch_dump, daemon=True, name='dump').start()
    if proxy.metrics_srv:
        proxy.metrics_srv.start()
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
