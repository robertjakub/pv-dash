#!/usr/bin/env python3
"""The scraper's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the registry name (the set-grammar config key and the
`set <name>` control name), the flag, the env twin(s), the section it files
under (common/options.py SECTIONS), the live control name when the knob is
live-settable, and the secret flag. The config script (the ini's
replacement), `show config`, the knob -> control-command mapper and
scripts/check_options.py read this table; --help and the man pages render
from the argparse parser built in bin/modbus-scraper.py."""
from common.options import Option

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the scraper it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'request', 'poll', 'clear', 'restart', 'shutdown',
               'help', 'ping', 'quit')

OPTIONS = (
    Option('host', '--host', 'SCR_HOST', 'device'),
    Option('modbus-port', '--modbus-port', 'SCR_MODBUS_PORT', 'device'),
    Option('unit', '--unit', 'SCR_UNIT', 'device'),
    Option('modbus-offset', '--modbus-offset', 'SCR_MODBUS_OFFSET', 'device'),
    Option('timeout', '--timeout', 'SCR_TIMEOUT', 'device', live='timeout'),
    Option('profile', '--profile', 'SCR_PROFILE', 'device', live='profile'),
    Option('metrics-spec', '--metrics-spec', 'SCR_METRICS_SPEC', 'device'),
    Option('metric-prefix', '--metric-prefix', 'SCR_METRIC_PREFIX', 'device'),
    Option('max-kwp', '--max-kwp', 'SCR_MAX_KWP', 'device'),
    Option('max-grid-kw', '--max-grid-kw', 'SCR_MAX_GRID_KW', 'device'),
    Option('battery', '--battery', 'SCR_BATTERY', 'device'),
    Option('grid-positive-import', '--grid-positive-import', 'SCR_GRID_POSITIVE_IMPORT', 'device'),

    Option('listen', '--listen', 'SCR_LISTEN', 'serving'),
    Option('local-time', '--local-time', 'SCR_LOCAL_TIME', 'serving'),

    Option('max-clients', '--max-clients', 'SCR_MAX_CLIENTS', 'limits', live='max-clients'),
    Option('client-timeout', '--client-timeout', 'SCR_CLIENT_TIMEOUT', 'limits', live='client-timeout'),
    Option('max-conn-per-ip', '--max-conn-per-ip', 'SCR_MAX_CONN_PER_IP', 'limits', live='max-conn-per-ip'),

    Option('control-port', '--control-port', 'SCR_CTL', 'control'),
    Option('control-token', '--control-token', 'SCR_CONTROL_TOKEN', 'control', secret=True),
    Option('control-token-file', '--control-token-file', 'SCR_CONTROL_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-token', '--control-ops-token', 'SCR_CONTROL_OPS_TOKEN', 'control', secret=True),
    Option('control-ops-token-file', '--control-ops-token-file', 'SCR_CONTROL_OPS_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-verbs', '--control-ops-verbs', 'SCR_CONTROL_OPS_VERBS', 'control'),
    Option('control-trust-uids', '--control-trust-uids', 'SCR_CONTROL_TRUST_UIDS', 'control'),

    Option('auth-token', '--auth-token', 'SCR_AUTH_TOKEN', 'metrics', secret=True),
    Option('auth-token-file', '--auth-token-file', 'SCR_AUTH_TOKEN_FILE', 'metrics', secret=True),

    Option('audit-log', '--audit-log', 'SCR_AUDIT_LOG', 'audit'),
    Option('audit-max-mb', '--audit-max-mb', 'SCR_AUDIT_MAX_MB', 'audit'),
    Option('audit-files', '--audit-files', 'SCR_AUDIT_FILES', 'audit'),
    Option('no-audit-log', '--no-audit-log', None, 'audit'),

    Option('interval', '--interval', 'SCR_INTERVAL', 'logging', live='interval'),
    Option('log-access', '--log-access', 'SCR_LOG_ACCESS', 'logging', live='log-access'),
    Option('log-level', '--log-level', 'SCR_LOG_LEVEL', 'logging', live='log-level'),
)

OPTION_BY_NAME = {o.name: o for o in OPTIONS}

# the resolved-config keys that do not follow the name.replace('-', '_') rule
CFG_KEYS = {'log-level': 'level'}


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
    if key == 'host':
        return str(v)
    return str(v)
