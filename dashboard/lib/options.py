#!/usr/bin/env python3
"""The dashboard's option registry — the one row per knob (docs/TODO.md,
"one knob, one source"): the registry name (the set-grammar config key and
the `set <name>` control name), the flag, the env twin(s), the section it
files under (common/options.py SECTIONS), the live control name when the
knob is live-settable, and the secret flag. The config script (the ini's
replacement), `show config`, the knob -> control-command mapper and
scripts/check_options.py read this table; --help and the man pages render
from the argparse parser built in bin/dashboard.py."""
from common.options import Option

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the dashboard it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'request', 'clear', 'shutdown',
               'help', 'ping', 'quit')

OPTIONS = (
    Option('port', '--port', 'DSH_PORT', 'serving'),
    Option('bind', '--bind', 'DSH_BIND', 'serving'),
    Option('upstream', '--upstream', 'DSH_PROM_URL', 'serving'),
    Option('prom-prefix', '--prom-prefix', 'DSH_PROM_PREFIX', 'serving'),
    Option('static-dir', '--static-dir', 'DSH_STATIC_DIR', 'serving'),
    Option('config-js', '--config-js', 'DSH_CONFIG_JS', 'serving'),
    Option('battery', '--battery', 'DSH_BATTERY', 'serving', live='battery'),

    Option('max-clients', '--max-clients', 'DSH_MAX_CLIENTS', 'limits', live='max-clients'),
    Option('client-timeout', '--client-timeout', 'DSH_CLIENT_TIMEOUT', 'limits', live='client-timeout'),
    Option('max-conn-per-ip', '--max-conn-per-ip', 'DSH_MAX_CONN_PER_IP', 'limits', live='max-conn-per-ip'),

    Option('control-port', '--control-port', 'DSH_CTL', 'control'),
    Option('control-token', '--control-token', 'DSH_CONTROL_TOKEN', 'control', secret=True),
    Option('control-token-file', '--control-token-file', 'DSH_CONTROL_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-token', '--control-ops-token', 'DSH_CONTROL_OPS_TOKEN', 'control', secret=True),
    Option('control-ops-token-file', '--control-ops-token-file', 'DSH_CONTROL_OPS_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-verbs', '--control-ops-verbs', 'DSH_CONTROL_OPS_VERBS', 'control'),
    Option('control-trust-uids', '--control-trust-uids', 'DSH_CONTROL_TRUST_UIDS', 'control'),

    Option('metrics-server', '--metrics-server', 'DSH_METRICS_SERVER', 'metrics', live='metrics-server'),
    Option('metrics-listen', '--metrics-listen', 'DSH_METRICS_LISTEN', 'metrics'),
    Option('metrics-token', '--metrics-token', 'DSH_METRICS_TOKEN', 'metrics', secret=True),
    Option('metrics-token-file', '--metrics-token-file', 'DSH_METRICS_TOKEN_FILE', 'metrics', secret=True),
    Option('metrics-max-clients', '--metrics-max-clients', 'DSH_METRICS_MAX_CLIENTS', 'metrics'),
    Option('metrics-client-timeout', '--metrics-client-timeout', 'DSH_METRICS_CLIENT_TIMEOUT', 'metrics'),
    Option('metrics-max-conn-per-ip', '--metrics-max-conn-per-ip', 'DSH_METRICS_MAX_CONN_PER_IP', 'metrics'),

    Option('audit-log', '--audit-log', None, 'audit'),
    Option('audit-max-mb', '--audit-max-mb', None, 'audit'),
    Option('audit-files', '--audit-files', None, 'audit'),
    Option('no-audit-log', '--no-audit-log', None, 'audit'),

    Option('log-level', '--log-level', None, 'logging', live='log-level'),
    Option('log-queries', '--log-queries', None, 'logging', live='log-queries'),
    Option('log-access', '--log-access', 'DSH_LOG_ACCESS', 'logging', live='log-access'),
    Option('local-time', '--local-time', 'DSH_LOCAL_TIME', 'logging'),
)

OPTION_BY_NAME = {o.name: o for o in OPTIONS}

# the resolved-config keys that do not follow the name.replace('-', '_') rule
CFG_KEYS = {'log-level': 'level', 'prom-prefix': 'prom_prefix', 'static-dir': 'static_dir',
            'config-js': 'config_js'}


def config_value(name, cfg):
    """The set-grammar form of one option's effective startup value (the
    resolved config dict), or None when it should not render (secrets hide;
    empty values drop — the defaults apply on re-run)."""
    opt = OPTION_BY_NAME[name]
    key = CFG_KEYS.get(name, name.replace('-', '_'))
    v = cfg.get(key)
    if opt.secret:
        return None
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 'true' if v else 'false'
    return str(v)
