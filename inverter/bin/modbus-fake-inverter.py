#!/usr/bin/env python3
"""Fake Inverter Simulator: a Modbus TCP server with demo values. Through
inverter profiles it can emulate different inverter/battery/meter devices —
the shipped default profile is the sun2000 (Huawei SUN2000) map, a Deye
hybrid map is included as well.

Simulates a sunny day (bell-curve PV between 06:00 and 18:00, home load
with morning and evening peaks) and serves the profile's registers over
FC3 (holding) and FC4 (input — the same map on both), the diagnostics
block (65000+) included: 32064 PV
input power and 37113 grid active power (positive = feed-in, as reported by
the simulated smart meter), plus the smart meter block (37100+ status/
voltages/currents/energies), device status (32089), inverter output
(32080), PV strings (32016-32019, voltage x10 V / current x100 A), phase
voltages (32069+), grid frequency (32085), temperature (32087) and PV
yields (32106/32114), plus the modbus-cache diagnostics block (65000+).
Raw register values are watts and kWh*100, matching the default profile's gain
convention.

Optional extras for demos and testing: a JSON-lines control server
(--control-port, default unix socket /tmp/fake-inverter-<port>.socket; 0 = off) to pin
values / freeze time / tune chaos at runtime, and
seeded chaos injection (--chaos) that answers requests hostile. Signals
mirror the family: SIGHUP re-applies the environment layer
(CHAOS/MAX_KWP/STRICT/TIME/TIME_SCALE/
LOG_LEVEL, keep-last-good), SIGUSR1 resets the scenario (releases pins
+ write overlay), SIGTERM/SIGINT shut down with a session summary.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

import logging
import math

from common.audit import AuditLog
from common.config import acl_text, acl_value_text, check_auth_key, parse_acl, parse_auth_type, parse_listen, \
    parse_secret, resolve_control_target, resolve_metrics_acl
from common.cred import parse_trust_uids
from common.daemon import apply_restart_state, parse_ops_verbs
from common.options import build_parser
from common.version import version_string
from lib.chaos import Chaos
from lib.control import ControlServer
from lib.options import KNOWN_VERBS, OPTIONS
from lib.inverter import FakeInverter
from lib.profile import load_profile, profile_label, resolve_profile
from lib.statics import CONTROL_SOCKET_TEMPLATE, PEAK_RATIO, TIME_SCALE_MAX
from lib.signals import SignalBox, parse_time
from lib.metrics import MetricsServer, describe_metrics
from lib.simulator import Simulator

logger = logging.getLogger('fake-inverter')


def validate(args):
    """Clean one-line failures instead of ugly bind errors (family convention)."""
    problems = []
    host = (args.host or '').strip()
    if not host or len(host) > 253 or not all(c.isalnum() or c in '._-[]:' for c in host):
        problems.append('--host is not a valid hostname/address: %r' % args.host)
    if not 1 <= args.port <= 65535:
        problems.append('--port out of range: %d' % args.port)
    ctl = resolve_control_target(args.control_port, args.port, CONTROL_SOCKET_TEMPLATE)
    if ctl != '0':
        if ctl.isdigit():
            if not 1 <= int(ctl) <= 65535:
                problems.append('--control-port out of range: %d' % int(ctl))
        elif len(ctl) > 100:
            problems.append('--control-port socket path too long (max ~100 chars): %r' % ctl)
    if not 1 <= args.unit <= 247:
        problems.append('--unit out of range (1-247): %d' % args.unit)
    if not (math.isfinite(args.max_kwp) and args.max_kwp > 0):
        problems.append('--max-kwp must be a positive kW value, got %r' % args.max_kwp)
    if not (math.isfinite(args.battery_kwh) and args.battery_kwh > 0):
        problems.append('--battery-kwh must be a positive kWh value, got %r' % args.battery_kwh)
    if not (math.isfinite(args.time_scale) and 0 < args.time_scale <= TIME_SCALE_MAX):
        problems.append('--time-scale must be 0 < N <= %g (a day per minute), got %r' % (TIME_SCALE_MAX, args.time_scale))
    if not 0.0 <= args.chaos <= 1.0:
        problems.append('--chaos must be a probability 0..1, got %r' % args.chaos)
    if args.max_clients < 0:
        problems.append('--max-clients must be >= 0 (0 = no limit), got %d' % args.max_clients)
    if not (math.isfinite(args.client_timeout) and args.client_timeout >= 0):
        problems.append('--client-timeout must be >= 0 seconds (0 = never), got %r' % args.client_timeout)
    if args.max_conn_per_ip < 0:
        problems.append('--max-conn-per-ip must be >= 0 (0 = no per-IP limit), got %d' % args.max_conn_per_ip)
    if args.metrics_max_clients < 0:
        problems.append('--metrics-max-clients must be >= 0 (0 = unlimited), got %d' % args.metrics_max_clients)
    if not (math.isfinite(args.metrics_client_timeout) and args.metrics_client_timeout >= 0):
        problems.append('--metrics-client-timeout must be >= 0 seconds, got %r' % args.metrics_client_timeout)
    if args.metrics_max_conn_per_ip < 0:
        problems.append('--metrics-max-conn-per-ip must be >= 0 (0 = no per-IP limit), got %d' % args.metrics_max_conn_per_ip)
    return problems


def configured_defaults(args, frozen, profile_text, connect_acl, modbus_auth,
                        control_target, ops_verbs, trust_uids, metrics_acl):
    """Every setting's configured startup value — what `unset <setting>`
    restores (the connect ACL, the auth type and the control family ride
    in, parsed once in main). The secret rows (control/token,
    control/ops/token, metrics/token, auth-key) carry NO entry: `unset`
    refuses them (the metrics/token treatment) — a secret never renders,
    never re-applies."""
    return {
        'pv': 'auto', 'load': 'auto', 'batt': 'auto', 'grid': 'auto', 'soc': 'auto', 'cloud': 'clear',
        'time': '%02d:%02d' % (int(frozen), round((frozen % 1.0) * 60)) if frozen is not None else 'auto',
        'time-scale': '%g' % args.time_scale,
        'scenario': 'custom',
        'chaos': '%.2f' % args.chaos,
        'seed': 'random' if args.seed is None else str(args.seed),
        'battery-state': 'auto',
        'mppt': 'both',
        'grid-voltage': '%g' % args.grid_voltage,
        'grid-frequency': '%g' % args.grid_frequency,
        'grid-outage': 'off',
        'timezone': args.timezone,
        'strict': 'on' if args.strict else 'off',
        'static': 'on' if args.static else 'off',
        'max-kwp': '%g' % args.max_kwp,
        'battery-kwh': '%g' % args.battery_kwh,
        'max-clients': str(args.max_clients),
        'client-timeout': '%g' % args.client_timeout,
        'max-conn-per-ip': str(args.max_conn_per_ip),
        'connect-acl': acl_text(connect_acl),
        'write/allow': 'on' if args.allow_write else 'off',
        'modbus/auth': modbus_auth or 'none',
        'metrics/enable': 'on' if args.metrics_server else 'off',
        'metrics/acl': acl_value_text(metrics_acl),
        'profile': profile_text,
        'log-level': args.log_level,
        'dump/path': args.dump_path or 'off',
        'dump/restore-on-start': 'on' if args.restore_on_start else 'off',
        # the live control family — what `unset` restores (the cache's model)
        'control/port': control_target,
        'control/ops/verbs': ','.join(sorted(ops_verbs)) if ops_verbs else 'off',
        'control/trust-uids': ','.join(str(u) for u in sorted(trust_uids or ())) or 'off',
        'control/socket-group': 'on' if args.control_socket_group else 'off',
        # the startup-only knobs (restart: true) — what `show <knob>` answers
        'host': args.host, 'port': str(args.port), 'unit': str(args.unit),
        'control-log-replies': 'on' if args.control_log_replies else 'off',
        'metrics-listen': args.metrics_listen or 'off',
        'metrics-max-clients': str(args.metrics_max_clients),
        'metrics-client-timeout': '%g' % args.metrics_client_timeout,
        'metrics-max-conn-per-ip': str(args.metrics_max_conn_per_ip),
        'audit-log': 'off' if args.no_audit_log else ('stdout' if args.audit_log == '-'
                                                      else (args.audit_log or 'the XDG state home')),
        'audit-max-mb': '%g' % args.audit_max_mb,
        'audit-daily': 'on' if args.audit_daily else 'off',
        'audit-files': str(args.audit_files),
        'no-audit-log': 'on' if args.no_audit_log else 'off',
    }


def startup_values(args, secrets):
    """The startup options as display strings by registry name — what
    `show config` renders (the argv that would restart this fake; the
    unset flags drop). A configured secret renders as *** SECRET REMOVED
    *** (the knob is public, the value never is): `secrets` is the resolved
    {registry name: set-or-not} of the secret rows."""
    from lib.options import OPTION_BY_NAME
    from common.dump import SECRET_REMOVED
    out = {}
    for name, opt in OPTION_BY_NAME.items():
        v = getattr(args, name.replace('-', '_'), None)
        if opt.secret:
            if secrets.get(name) or secrets.get(opt.live):   # either key spelling
                out[name] = SECRET_REMOVED
            continue
        if v is None or v == '' or v is False:
            continue
        if v is True:
            out[name] = 'true'
        elif name == 'connect-acl':
            continue          # the parsed ACL renders in inspect
        else:
            out[name] = str(v)
    return out


def main():
    import sys
    if '--version' in sys.argv:
        print(version_string())
        raise SystemExit(0)
    p = build_parser(OPTIONS, description='Fake Inverter Simulator: a Modbus TCP server with demo values. Simulates different inverter/battery/meter devices through inverter profiles — the shipped default profile is the sun2000 (Huawei SUN2000) map, a Deye hybrid map is included as well.')
    p.add_argument('--dry-run', action='store_true', help='validate the configuration, print the effective settings and exit (nothing is bound or connected)')
    p.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (modbus-fake-inverter --man | man -l -)')
    args = p.parse_args()
    if args.man:
        from lib.man import daemon_page
        sys.stdout.write(daemon_page(p))
        raise SystemExit(0)
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format='%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM')
                        else '%(asctime)s %(levelname)-7s %(message)s')
    problems = validate(args)
    try:
        frozen = parse_time(args.time) if args.time else None
    except ValueError:
        logger.error('--time must be HH:MM (00:00-23:59), got %r', args.time)
        frozen = None
        problems.append('--time invalid')
    if problems:
        for problem in problems:
            logger.error(problem)
        raise SystemExit(1)
    profile_text = args.profile or os.environ.get('PROFILE') or 'sun2000'
    profile_path = resolve_profile(profile_text)
    simulator = Simulator(PEAK_RATIO * args.max_kwp * 1000.0, args.static, frozen,
                          battery_kwh=args.battery_kwh,
                          profile=load_profile(profile_path), seed=args.seed)
    simulator.set_time_scale(args.time_scale)   # validated above; before any machine reads the clock
    connect_acl = parse_acl(args.connect_acl or os.environ.get('CONNECT_ACL'), 'connect-acl')
    modbus_auth = parse_auth_type(args.auth or os.environ.get('AUTH'), 'auth')
    modbus_auth_key = check_auth_key(
        parse_secret((args.auth_key or os.environ.get('AUTH_KEY') or '').strip() or None, 'auth-key'), 'auth-key')
    if modbus_auth and not modbus_auth_key:
        logger.error('the suite auth needs a key: set --auth-key/$AUTH_KEY too (min 16 characters)')
        raise SystemExit(1)
    chaos = Chaos(args.chaos, seed=args.seed)
    target = resolve_control_target(args.control_port, args.port, CONTROL_SOCKET_TEMPLATE)
    dump_key = parse_secret((args.dump_key or os.environ.get('DUMP_KEY') or '').strip() or None, 'dump/key')
    apply_restart_state(vars(args), None, dump_key, ControlServer)
    control_token = parse_secret(args.control_token or os.environ.get('CONTROL_TOKEN'), 'control/token')
    control_ops_token = parse_secret(args.control_ops_token or os.environ.get('CONTROL_OPS_TOKEN'),
                                     'control-ops-token')
    if control_ops_token and not control_token:
        logger.error('the read-only ops token supplements the admin token: set --control-token too '
                     '(an ops token alone would leave the control plane unusable)')
        raise SystemExit(1)
    if control_ops_token and control_ops_token == control_token:
        logger.error('the ops token must differ from the admin token (the same secret would hand '
                     'every holder the role the server picks first)')
        raise SystemExit(1)
    ops_verbs = parse_ops_verbs(args.control_ops_verbs or os.environ.get('CONTROL_OPS_VERBS'), KNOWN_VERBS, rc=1)
    trust_uids = parse_trust_uids(args.control_trust_uids or os.environ.get('CONTROL_TRUST_UIDS'),
                                  'control-trust-uids')
    metrics_token = parse_secret(args.metrics_token or os.environ.get('METRICS_TOKEN'), 'metrics/token')
    metrics_listen = parse_listen(args.metrics_listen)
    metrics_acl, metrics_acl_warn = resolve_metrics_acl(args.metrics_acl or os.environ.get('METRICS_ACL'),
                                                        'metrics/acl')   # a bad acl value or gate file refuses the start
    if args.metrics_server and metrics_token is None:
        from common.config import is_loopback_host
        if not is_loopback_host(metrics_listen[0]):
            raise SystemExit('refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md): '
                             'listen = %r — set --metrics-token (or file:<path>) or bind 127.0.0.1:PORT'
                             % args.metrics_listen)
    if args.dump_path and not dump_key:
        logger.warning('the state dump %s is not sealed (the integrity hash only — plaintext at rest): '
                       'set dump/key (--dump-key, $DUMP_KEY or set dump-key, a file: reference works) '
                       'to encrypt it', args.dump_path)
    if args.dry_run:
        mode = 'static values' if args.static else (
            'day simulation at x%g' % args.time_scale if args.time_scale != 1.0 else 'day simulation')
        logger.info('would serve Modbus TCP on %s:%d (unit %d, peak PV %gW, %s, battery %g kWh, strict %s, chaos %g, seed %s, client limit %s, client timeout %s, per-ip limit %s, modbus auth %s, profile %s: %s, %d register(s), metrics server %s, control server %s)',
                    args.host, args.port, args.unit, PEAK_RATIO * args.max_kwp * 1000.0,
                    mode,
                    args.battery_kwh,
                    args.strict, args.chaos,
                    args.seed if args.seed is not None else 'random',
                    args.max_clients or 'none',
                    '%gs' % args.client_timeout if args.client_timeout else 'never',
                    args.max_conn_per_ip or 'none',
                    modbus_auth or 'none',
                    simulator.profile.description, profile_label(profile_path), len(simulator.profile.entries),
                    '%s:%d%s' % (metrics_listen[0], metrics_listen[1],
                                 ' (bearer token)' if metrics_token else '') if args.metrics_server else 'off',
                    ('127.0.0.1:' + target) if target.isdigit() else ('unix:' + target) if target != '0' else 'off')
        logger.info('dry-run: configuration is valid, nothing was bound or connected')
        return
    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'INV', app='fake-inverter',
                                                    max_mb=args.audit_max_mb,
                                                    daily=args.audit_daily, files=args.audit_files)
    fake = FakeInverter(args.unit, simulator, strict=args.strict, chaos=chaos,
                        max_clients=args.max_clients, client_timeout=args.client_timeout,
                        max_conn_per_ip=args.max_conn_per_ip, connect_acl=connect_acl,
                        auth=modbus_auth, auth_key=modbus_auth_key,
                        allow_write=args.allow_write, audit=audit)
    control = None
    if target != '0':
        control = ControlServer(simulator, chaos, target, fake=fake,
                                defaults=configured_defaults(args, frozen, profile_text,
                                                             connect_acl, modbus_auth,
                                                             target, ops_verbs, trust_uids, metrics_acl),
                                log_replies=args.control_log_replies, audit=audit,
                                token=control_token, trust_uids=trust_uids,
                                socket_group=args.control_socket_group,
                                ops_token=control_ops_token, ops_verbs=ops_verbs,
                                startup_values=startup_values(args, {
                                    'control-token': bool(control_token),
                                    'control-ops-token': bool(control_ops_token),
                                    'metrics-token': bool(metrics_token),
                                    'auth-key': bool(modbus_auth_key),
                                    'dump-key': bool(dump_key)}),
                                dump_path=args.dump_path, restore_on_start=args.restore_on_start,
                                dump_key=dump_key)
    fake.metrics_listen = metrics_listen
    fake.metrics_token = metrics_token
    fake.metrics_acl = metrics_acl
    fake.metrics_caps = (args.metrics_max_clients, args.metrics_client_timeout, args.metrics_max_conn_per_ip)
    fake.metrics_desc = describe_metrics(metrics_listen, metrics_token,
                                         args.metrics_max_clients, args.metrics_max_conn_per_ip) \
        if args.metrics_server else 'off'
    if args.metrics_server:
        fake.metrics_srv = MetricsServer(simulator, chaos, fake, control, metrics_listen,
                                         token=metrics_token, max_clients=args.metrics_max_clients,
                                         client_timeout=args.metrics_client_timeout,
                                         max_per_ip=args.metrics_max_conn_per_ip)
        fake.metrics_srv.start()
    else:
        fake.metrics_srv = None
    if control:
        control.start()   # the reload state restores first, then the listener binds
        if control.dump_path and args.restore_on_start:
            logger.info('restore-on-start: %s', control.restore_state())
    box = SignalBox(simulator, chaos, fake, control=control, audit=audit)
    if control:
        control.signalbox = box
    box.install()
    if audit:
        audit.event('START', 'version=%s modbus=%s:%d control=%s profile=%s: %s'
                    % (version_string(), args.host, args.port,
                       ('127.0.0.1:' + target) if target != '0' else 'off',
                       profile_label(profile_path), simulator.profile.description))
        if metrics_acl_warn:   # the start resolve warned before the audit existed — the ACL-FILE event lands after START
            audit.event('ACL-FILE', metrics_acl_warn)
    try:
        fake.serve(args.host, args.port)
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        if box.stop:
            return   # the signal box closed the listener; it logs the shutdown
        logger.error('cannot serve on %s:%d: %s', args.host, args.port, e)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
