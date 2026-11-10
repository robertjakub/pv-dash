#!/usr/bin/env python3
"""Configuration for modbus-fake-inverter: the set-grammar config script, the
env layer and the CLI flags (stdlib only). The config file speaks the control
grammar (common/settings/options.py): every line a `set <name> <value>`, every comment
a `#` comment — the ini format is gone. The fake keeps its args-driven shape
(the bins read args.* everywhere), so the resolver's job is to slot the two
lower layers under the flags and write the effective values back onto the
parsed args namespace: flag > env > config script > the static defaults
(common/settings/config.py Resolver, keep-last-good) — every flag row the same ladder,
the demo twins included (they re-apply on SIGHUP, lib/signals.py). The pins
and the machines (pv, load, batt, grid, soc, mppt, cloud, scenario,
battery-state, grid-outage) are control-wire settings without flags: the
config file names one and the start refuses."""
import logging

from .options import OPTIONS
from .statics import DEFAULTS, GRID
from common.settings.config import Resolver, load_config_script, str_to_bool

logger = logging.getLogger('fake-inverter')

# the static defaults the parser no longer carries (a static-wired default
# would shadow the env/config layers — the flag never looks unset): the
# same dict lib/options.py used to bake into build_parser, applied last in
# the ladder instead. The bool rows read the tree's false entries like the
# rest; the untwinned knobs left out stay None (the secrets to off).
STATIC_DEFAULTS = {
    'listen': DEFAULTS['listen'],
    'unit': DEFAULTS['unit'],
    'max-kwp': DEFAULTS['max_kwp'],
    'battery-kwh': DEFAULTS['battery_kwh'],
    'time-scale': DEFAULTS['time_scale'],
    'chaos': DEFAULTS['chaos'],
    'static': DEFAULTS['static'],
    'strict': DEFAULTS['strict'],
    'timezone': DEFAULTS['timezone'],
    'dump-interval': DEFAULTS['dump_interval'],
    'max-clients': DEFAULTS['max_clients'],
    'client-timeout': DEFAULTS['client_timeout_s'],
    'max-conn-per-ip': DEFAULTS['max_conn_per_ip'],
    'connect-acl': DEFAULTS['connect_acl'],
    'allow-write': DEFAULTS['allow_write'],
    'metrics-listen': DEFAULTS['metrics_listen'],
    'metrics-acl': DEFAULTS['metrics_acl'],
    'metrics-max-clients': DEFAULTS['metrics_max_clients'],
    'metrics-client-timeout': DEFAULTS['metrics_client_timeout_s'],
    'metrics-max-conn-per-ip': DEFAULTS['metrics_max_conn_per_ip'],
    'metrics-server': DEFAULTS['metrics_server'],
    'log-level': DEFAULTS['log_level'],
    'audit-max-mb': DEFAULTS['audit_max_mb'],
    'audit-files': DEFAULTS['audit_files'],
    'audit-forward': DEFAULTS['audit_forward'],
    'audit-forward-format': DEFAULTS['audit_forward_format'],
    'audit-daily': DEFAULTS['audit_daily'],
    'modbus-auth': DEFAULTS['modbus_auth'],
    'no-audit-log': DEFAULTS['no_audit_log'],
    'audit-log': DEFAULTS['audit_log'],
    'dump-path': DEFAULTS['dump_path'],
    'control-trust-uids': DEFAULTS['control_trust_uids'],
    'profile': DEFAULTS['modbus_profile'],
    'control-log-replies': DEFAULTS['control_log_replies'],
    'control-socket-group': DEFAULTS['control_socket_group'],
    'restore-on-start': DEFAULTS['restore_on_start'],
    'grid-voltage': GRID['voltage_v'],
    'grid-frequency': GRID['frequency_hz'],
}


def load_config(path):
    """Parse the set-grammar config script (missing file is fine); a
    malformed file — or the legacy ini format — is fatal. Returns {key:
    raw-string value} with the dash names underscore-normalized."""
    return load_config_script(path, OPTIONS)


def resolve_args(args):
    """The fake's ladder, family precedence: CLI flags > env > the config
    script (args.config, the set grammar) > the static defaults — written
    back onto the parsed args namespace so every args.* reader downstream
    (validate, the dry run, the control defaults, `show config`) sees the
    effective values. A store_true flag can only mean True when given, so
    the bool rows read False/None as unset. A config line naming a
    flagless row (a pin or a machine) refuses the start — the wire sets
    those at runtime."""
    cfg = load_config(args.config)
    known = {o.name.replace('-', '_') for o in OPTIONS if o.flag}
    unknown = sorted(k for k in cfg if k not in known)
    if unknown:
        raise SystemExit(
            '%s: not startup knobs: %s — the config file sets the flags; '
            'the pins and the machines ride the control wire '
            '(`set pv 2500` on a running fake)'
            % (args.config, ', '.join(k.replace('_', '-') for k in unknown)))
    r = Resolver(cfg, logger)
    for o in OPTIONS:
        if not o.flag:
            continue
        dest = o.name.replace('-', '_')
        given = getattr(args, dest)
        if o.conv is bool:
            cli = True if given else None
        else:
            cli = given if (given is not None and given != '') else None
        conv = str_to_bool if o.conv is bool else o.conv
        value = r.resolve(cli, o.env, dest, STATIC_DEFAULTS.get(o.name), conv)
        if value is None and o.conv is bool:
            value = False
        setattr(args, dest, value)
    return cfg
