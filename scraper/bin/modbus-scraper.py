#!/usr/bin/env python3
"""Prometheus exporter for PV inverters (Modbus TCP, stdlib only).

Polls the inverter over Modbus TCP and serves the profile- and
compute-fed metrics (the huawei_* names by default) the dashboard
expects, plus the fixed scraper_* health gauges, at /metrics in the
Prometheus text format.

Layout: lib/protocol (Modbus client), lib/config (settings resolution),
lib/metrics (metric specs), lib/poller (poller + sanity checks),
lib/server (exposition endpoint), lib/version, this file (CLI, logging,
signals).
"""
import logging
import os
import sys
import threading
import time

here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.runtime.audit import load_audit_tags, audit_params_of, build_audit, default_path, audit_quote
from common.settings.config import parse_listen, resolve_control_target
from common.wire.cred import parse_trust_uids
from common.runtime.daemon import apply_restart_state, default_config_path, fold_listen, install_signal_handlers, log_state_dumps, \
    parse_ops_verbs, setup_logging
from common.serve.connlimit import limits_words
from common.settings.options import build_parser
from common.runtime.version import version_string
from lib.config import CONTROL_SOCKET_TEMPLATE, resolve_config, resolve_metrics_acl
from lib.control import ControlServer
from lib.metrics import Metrics
from lib.options import DEFAULT_OPS_VERBS, KNOWN_VERBS, OPTIONS
from lib.poller import Scraper
from lib.protocol import ModbusTCP
from lib.server import Handler, Server

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


logger = logging.getLogger('scraper')


def parse_args():
    ap = build_parser(OPTIONS, description='Prometheus exporter for PV inverters (Modbus TCP).')
    ap.add_argument('--config', default=default_config_path(SCRIPT_DIR, 'modbus-scraper.conf'),
                    help='config file — the set grammar: every line a `set <name> <value>`, comments start with # ($CONFIG, then modbus-scraper.conf next to this script, then the subproject root)')
    ap.add_argument('--dry-run', action='store_true', help='validate the configuration, print the effective settings and exit (nothing is bound or connected)')
    ap.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (modbus-scraper --man | man -l -)')
    args = ap.parse_args()
    if args.man:
        from lib.man import daemon_page
        sys.stdout.write(daemon_page(ap))
        raise SystemExit(0)
    return args


def describe(cfg, args, control_desc):
    caps = (['pv cap %gW' % (cfg['max_kwp'] * 1000.0)] if cfg['max_kwp'] > 0 else []) + \
           (['grid cap %gW' % (cfg['max_grid_kw'] * 1000.0)] if cfg['max_grid_kw'] > 0 else [])
    limits = limits_words(cfg['max_clients'], cfg['client_timeout'], cfg['max_conn_per_ip']) + \
             (['metrics-acl %s' % cfg['metrics_acl']] if cfg['metrics_acl'] not in ('any', '') else [])
    listen_host, listen_port = parse_listen(cfg['listen'])
    return ('polling %s:%d unit %d (profile %s, %d registers, positive=%s, modbus auth %s) every %gs; '
            '%s /metrics on %s:%d (config: %s, log level: %s, log time: %s, log access: %s, auth: %s, '
            'limits: %s, caps: %s, control server: %s, version: %s)' % (
                cfg['host'], cfg['modbus_port'], cfg['modbus_unit'], cfg['profile'], len(cfg['sources']),
                'import' if cfg['grid_positive_import'] else 'export',
                cfg['auth'] or 'none',
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


def main():
    import faulthandler
    import signal as _sig
    faulthandler.register(_sig.SIGUSR2)
    if '--version' in sys.argv:
        print(version_string())
        raise SystemExit(0)
    args = parse_args()
    cfg = resolve_config(args, SCRIPT_DIR)
    # the spec the daemon exports: the CONFIGURED one (resolve_config binds
    # the sources from the same file) — a plain Metrics() here would silently
    # swap the default spec back in over --metrics-spec
    spec = Metrics(cfg['metrics_spec'], prefix=cfg['metric_prefix'])

    setup_logging(cfg)

    apply_restart_state(cfg, args.config, cfg['dump_key'], ControlServer,
                        extra={'listen': fold_listen, 'metrics-listen': fold_listen})

    if cfg['max_kwp'] > 0 and cfg['max_grid_kw'] > 0 and cfg['max_kwp'] > cfg['max_grid_kw']:
        logger.warning('max_kwp (%g) is greater than max_grid_kw (%g): the grid line cannot be '
                       'smaller than the inverter capacity, check the caps', cfg['max_kwp'], cfg['max_grid_kw'])

    listen_host, listen_port = parse_listen(cfg['listen'])
    control_target = resolve_control_target(cfg['control_port'], listen_port, CONTROL_SOCKET_TEMPLATE)
    control_token = cfg['control_token'] or None
    control_ops_token = cfg['control_ops_token'] or None
    ops_verbs = parse_ops_verbs(cfg.get('control_ops_verbs'), KNOWN_VERBS, default=DEFAULT_OPS_VERBS)
    trust_uids = parse_trust_uids(cfg['control_trust_uids'], 'control-trust-uids')
    audit_derive = control_target if control_target.isdigit() and control_target != '0' else str(listen_port)
    audit_params = audit_params_of(cfg, derive=audit_derive)
    tag = load_audit_tags('scraper')
    audit = build_audit(cfg, tag, 'modbus-scraper', logger, derive=audit_derive)
    control_desc = 'off' if control_target == '0' \
        else ('127.0.0.1:%s' % control_target if control_target.isdigit() else 'unix:%s' % control_target) \
        + (', read-only ops token accepted' if control_ops_token else '')
    client = ModbusTCP(cfg['host'], cfg['modbus_port'], cfg['modbus_unit'], cfg['timeout'], cfg['modbus_offset'],
                       auth=cfg['auth'], auth_key=cfg['auth_key'])
    scraper = Scraper(cfg, client, spec)
    Handler.scraper = scraper
    Handler.log_access = cfg['log_access']
    Handler.auth_token = cfg['auth_token']
    Handler.timeout = cfg['client_timeout'] or None
    logger.info('%s', describe(cfg, args, control_desc))
    log_state_dumps(cfg['dump_path'], cfg['dump_key'], cfg['restore_on_start'])
    if args.dry_run:
        logger.info('dry-run: configuration is valid, nothing was bound or connected')
        return
    try:
        httpd = Server((listen_host, listen_port), Handler)
    except OSError as e:
        logger.error('cannot bind %s:%d: %s', listen_host, listen_port, e)
        raise SystemExit(1)
    httpd.setup_gate(cfg['max_clients'], cfg['max_conn_per_ip'])
    metrics_acl, metrics_acl_warn = resolve_metrics_acl(cfg['metrics_acl'])   # the accept-time gate (validated at resolve_config)
    httpd.metrics_acl = metrics_acl
    if metrics_acl_warn:
        logger.warning('acl file: %s', metrics_acl_warn)
    started = time.monotonic()

    control = None
    if control_target != '0':
        # `clear` restores these: the typed knobs read straight from the
        # registry rows (live name, config key, conv), the choice/bool
        # knobs stay hand-rendered (their convs do not round-trip a string)
        defaults = {'log-access': 'on' if cfg['log_access'] else 'off',
                    'log-level': cfg['level'],
                    'control-socket-group': 'on' if cfg['control_socket_group'] else 'off',
                    'dump-path': cfg['dump_path'] or 'off',
                    'restore-on-start': 'on' if cfg['restore_on_start'] else 'off',
                    'modbus-auth': cfg['auth'] or 'none',
                    'audit-log': 'off' if cfg['no_audit_log']
                                      else (cfg['audit_log'] or default_path('modbus-scraper'))}
        for o in OPTIONS:
            if o.live and o.conv in (int, float, str) and not o.secret:
                key = o.name.replace('-', '_')
                if key in cfg and cfg[key] is not None:
                    defaults[o.name] = str(cfg[key])   # the defaults speak the FLAT wire name
            elif o.live and o.conv is bool and not o.secret:
                key = o.name.replace('-', '_')
                if key in cfg:   # the live bools: `clear` needs a configured value too
                    defaults[o.name] = 'on' if cfg[key] else 'off'
            if o.restart and not o.secret:   # the startup-only knobs: what `show <knob>` answers
                key = o.name.replace('-', '_')
                v = cfg.get(key, getattr(args, key, None))
                wire = o.name                    # the flat registry name — the wire's one spelling
                if o.name == 'audit-log':
                    defaults[wire] = ('off' if args.no_audit_log
                                      else 'stdout' if args.audit_log == '-'
                                      else (args.audit_log or 'the XDG state home'))
                elif o.name == 'control-port':
                    defaults[wire] = 'off' if control_target == '0' else control_target
                elif o.conv is bool:
                    defaults[wire] = 'on' if v else 'off'
                elif o.name == 'control-trust-uids':
                    defaults[wire] = ','.join(str(u) for u in sorted(trust_uids or [])) or 'off'
                else:
                    defaults[wire] = str(v) if v not in (None, '') else 'off'
        defaults['dump-interval'] = 'off' if not cfg['dump_interval'] else '%g' % cfg['dump_interval']
        #   ^ the off canonical: str(0.0) is not a live-set spelling (the cache's defaults model)
        # the secret rows (control-token, control-ops-token, auth-token,
        # auth-key, dump-key) carry NO
        # defaults entry: `clear` refuses them (the metrics/token treatment) — a
        # secret never renders, never re-applies
        control = ControlServer(scraper, httpd, int(control_target) if control_target.isdigit() else control_target,
                                audit=audit, token=control_token, defaults=defaults, trust_uids=trust_uids,
                                socket_group=cfg['control_socket_group'],
                                log_replies=cfg['control_log_replies'],
                                ops_token=control_ops_token, ops_verbs=ops_verbs, config_path=args.config,
                                dump_path=cfg['dump_path'], restore_on_start=cfg['restore_on_start'],
                                dump_key=cfg['dump_key'], dump_interval=cfg['dump_interval'],
                                audit_params=audit_params)
        control.start()
        if control.dump_path and cfg['restore_on_start']:
            logger.info('restore-on-start: %s', control.restore_state())
        # the dumper thread always runs (it parks while dump-interval is off):
        # a live `set dump interval` wakes it without a restart — and a live
        # `set dump/path` (no path at start) finds the thread waiting too
        threading.Thread(target=control.run_dump_interval, daemon=True, name='dump').start()

    def the_audit():
        """The live trail: the control server's own (the audit family's
        live moves swap it), else the startup writer."""
        return control.audit if control else audit

    def apply_reload():
        """The SIGHUP and the `request reload-config` command share this: re-resolve
        the config, apply what is live (the gate, the handler, the poller),
        clear the override markers, audit."""
        new_cfg = resolve_config(args, SCRIPT_DIR)
        scraper.reload(new_cfg)
        Handler.log_access = new_cfg['log_access']
        Handler.auth_token = new_cfg['auth_token']
        Handler.timeout = new_cfg['client_timeout'] or None
        httpd.gate.max_total = new_cfg['max_clients']
        httpd.gate.max_per_ip = new_cfg['max_conn_per_ip']
        metrics_acl, metrics_acl_warn = resolve_metrics_acl(new_cfg['metrics_acl'])   # a bad value or file keeps the previous gate
        httpd.metrics_acl = metrics_acl
        if metrics_acl_warn:
            logger.warning('acl file: %s', metrics_acl_warn)
        summary = 'upstream %s:%d unit %d, interval %gs' % (new_cfg['host'], new_cfg['modbus_port'],
                                                            new_cfg['modbus_unit'], new_cfg['interval'])
        if control:
            control.metrics_acl_warn = metrics_acl_warn
            control.reloaded(summary, dump_interval=new_cfg['dump_interval'])
        a = the_audit()
        if a:
            a.event('RELOAD', 'result=ok upstream=%s:%d unit=%d interval=%gs auth=%s'
                    % (new_cfg['host'], new_cfg['modbus_port'], new_cfg['modbus_unit'], new_cfg['interval'],
                       'bearer' if new_cfg['auth_token'] else 'none'))
            if metrics_acl_warn:
                a.event('ACL-FILE', 'warn=%s' % audit_quote(metrics_acl_warn))
        return summary

    if control:
        control.reloader = apply_reload   # the control server's `request reload-config` runs the same path

    def graceful_stop(reason):
        logger.info('shutdown: %s received after %ds (%d poll errors), stopping the web server',
                    reason, time.monotonic() - started, scraper.errors)
        a = the_audit()
        if a:
            a.event('SHUTDOWN', 'reason=%s uptime=%ds errors=%d'
                    % (reason.replace(' ', '-'), int(time.monotonic() - started), scraper.errors))
        if control:
            control.shutdown_dump()   # the write-behind: the overrides ride the next start
            control.announce_exit(reason)   # the consoles print the notice and exit
            control.cleanup()
        httpd.shutdown()

    if control:
        control.stopper = graceful_stop
    install_signal_handlers(apply_reload=apply_reload, graceful_stop=graceful_stop)
    if audit:
        audit.event('START', 'version=%s upstream=%s:%d unit=%d listen=%s control=%s'
                    % (version_string(), cfg['host'], cfg['modbus_port'], cfg['modbus_unit'],
                       audit_quote(cfg['listen']), audit_quote(control_desc)))
        if metrics_acl_warn:   # the start resolve warned before the audit existed — the ACL-FILE event lands after START
            audit.event('ACL-FILE', 'warn=%s' % audit_quote(metrics_acl_warn))
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
