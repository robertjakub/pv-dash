#!/usr/bin/env python3
"""The fake's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the registry name, the flag, the env twin(s), the
section it files under (common/options.py SECTIONS), the live control name
when the knob is live-settable, and the secret flag. The fake is a test
instrument (F11) and never carried a config file — its startup surface is
the flags and the INV_* env layer — so unlike the serving tools it has no
--config; the registry still drives `show config` (the set-grammar form of
the running fake's startup options — the argv that would restart it), the
knob -> control-command mapper and scripts/check_options.py."""
from common.options import Option

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the fake it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'reset', 'clear', 'shutdown',
               'help', 'ping', 'quit')

OPTIONS = (
    Option('host', '--host', None, 'device'),
    Option('port', '--port', None, 'device'),
    Option('unit', '--unit', None, 'device'),
    Option('profile', '--profile', 'INV_PROFILE', 'device'),
    Option('max-kwp', '--max-kwp', 'INV_MAX_KWP', 'device'),
    Option('timezone', '--timezone', None, 'device'),
    Option('time', '--time', 'INV_TIME', 'device'),
    Option('time-scale', '--time-scale', 'INV_TIME_SCALE', 'device'),
    Option('static', '--static', None, 'device'),
    Option('battery', '--battery', 'INV_BATTERY', 'device'),
    Option('no-battery', '--no-battery', None, 'device'),
    Option('battery-kwh', '--battery-kwh', None, 'device'),
    Option('strict', '--strict', 'INV_STRICT', 'device'),
    Option('chaos', '--chaos', 'INV_CHAOS', 'device'),
    Option('grid-voltage', '--grid-voltage', None, 'device'),
    Option('grid-frequency', '--grid-frequency', None, 'device'),
    Option('seed', '--seed', None, 'device'),
    Option('connect-acl', '--connect-acl', 'INV_CONNECT_ACL', 'device'),

    Option('max-clients', '--max-clients', None, 'limits'),
    Option('client-timeout', '--client-timeout', None, 'limits'),
    Option('max-conn-per-ip', '--max-conn-per-ip', None, 'limits'),

    Option('control-port', '--control-port', 'INV_CTL', 'control'),
    Option('control-token', '--control-token', 'INV_CONTROL_TOKEN', 'control', secret=True),
    Option('control-token-file', '--control-token-file', 'INV_CONTROL_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-token', '--control-ops-token', 'INV_CONTROL_OPS_TOKEN', 'control', secret=True),
    Option('control-ops-token-file', '--control-ops-token-file', 'INV_CONTROL_OPS_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-verbs', '--control-ops-verbs', 'INV_CONTROL_OPS_VERBS', 'control'),
    Option('control-trust-uids', '--control-trust-uids', 'INV_CONTROL_TRUST_UIDS', 'control'),
    Option('control-socket-group', '--control-socket-group', None, 'control'),
    Option('control-log-replies', '--control-log-replies', None, 'control'),

    Option('metrics-server', '--metrics-server', None, 'metrics'),
    Option('metrics-listen', '--metrics-listen', None, 'metrics'),
    Option('metrics-token', '--metrics-token', 'INV_METRICS_TOKEN', 'metrics', secret=True),
    Option('metrics-token-file', '--metrics-token-file', 'INV_METRICS_TOKEN_FILE', 'metrics', secret=True),
    Option('metrics-max-clients', '--metrics-max-clients', None, 'metrics'),
    Option('metrics-client-timeout', '--metrics-client-timeout', None, 'metrics'),
    Option('metrics-max-conn-per-ip', '--metrics-max-conn-per-ip', None, 'metrics'),

    Option('audit-log', '--audit-log', None, 'audit'),
    Option('audit-max-mb', '--audit-max-mb', None, 'audit'),
    Option('audit-daily', '--audit-daily', None, 'audit'),
    Option('audit-files', '--audit-files', None, 'audit'),
    Option('no-audit-log', '--no-audit-log', None, 'audit'),

    Option('log-level', '--log-level', 'INV_LOG_LEVEL', 'logging'),
)

OPTION_BY_NAME = {o.name: o for o in OPTIONS}
