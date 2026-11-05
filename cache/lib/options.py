#!/usr/bin/env python3
"""The cache's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the registry name (the set-grammar config key and the
`set <name>` control name, dashes included), the flag, the env twin(s), the
section it files under (common/options.py SECTIONS), whether the knob is
live-settable (the control `set` name when it is) and whether it is a
secret. The config script (the ini's replacement), `show config`, the
knob -> control-command mapper and scripts/check_options.py all read this
table; --help and the man pages render from the argparse parser built in
bin/modbus-cache.py, and this table cross-references it (the check gate
keeps the four surfaces honest)."""
from common.options import Option

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'request', 'clear', 'restart', 'shutdown',
               'help', 'ping', 'quit')

# section, name, flag, env twin(s), live name (None = startup-only), secret
OPTIONS = (
    Option('host', '--host', 'MCH_HOST', 'device'),
    Option('port', '--port', 'MCH_PORT', 'device'),
    Option('unit', '--unit', 'MCH_UNIT', 'device'),
    Option('timeout', '--timeout', 'MCH_TIMEOUT', 'device', live='timeout'),
    Option('interval', '--interval', 'MCH_INTERVAL', 'device', live='interval'),
    Option('read-delay', '--read-delay', 'MCH_READ_DELAY', 'device', live='read-delay'),
    Option('merge-gap', '--merge-gap', 'MCH_MERGE_GAP', 'device', live='merge-gap'),
    Option('cache-ttl', '--cache-ttl', 'MCH_TTL', 'device', live='ttl'),
    Option('allow-write', '--allow-write', 'MCH_ALLOW_WRITE', 'device', live='allow-write'),
    Option('write-registers', '--write-registers', 'MCH_WRITE_REGISTERS', 'device', live='write-registers'),
    Option('profile', '--profile', 'MCH_PROFILE', 'device', live='profile'),
    Option('selection', '--selection', 'MCH_SELECTION', 'device', live='selection'),
    Option('connect-acl', '--connect-acl', 'MCH_CONNECT_ACL', 'device', live='connect-acl'),
    Option('write-acl', '--write-acl', 'MCH_WRITE_ACL', 'device', live='write-acl'),

    Option('listen', '--listen', 'MCH_LISTEN', 'serving'),
    Option('local-time', '--local-time', 'MCH_LOCAL_TIME', 'serving'),

    Option('max-clients', '--max-clients', 'MCH_MAX_CLIENTS', 'limits', live='max-clients'),
    Option('client-timeout', '--client-timeout', 'MCH_CLIENT_TIMEOUT', 'limits', live='client-timeout'),
    Option('max-conn-per-ip', '--max-conn-per-ip', 'MCH_MAX_CONN_PER_IP', 'limits', live='max-conn-per-ip'),

    Option('control-port', '--control-port', 'MCH_CTL', 'control'),
    Option('control-token', '--control-token', 'MCH_CONTROL_TOKEN', 'control', secret=True),
    Option('control-token-file', '--control-token-file', 'MCH_CONTROL_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-token', '--control-ops-token', 'MCH_CONTROL_OPS_TOKEN', 'control', secret=True),
    Option('control-ops-token-file', '--control-ops-token-file', 'MCH_CONTROL_OPS_TOKEN_FILE', 'control', secret=True),
    Option('control-ops-verbs', '--control-ops-verbs', 'MCH_CONTROL_OPS_VERBS', 'control'),
    Option('control-trust-uids', '--control-trust-uids', 'MCH_CONTROL_TRUST_UIDS', 'control'),
    Option('control-socket-group', '--control-socket-group', 'MCH_CONTROL_SOCKET_GROUP', 'control'),

    Option('metrics-server', '--metrics-server', 'MCH_METRICS_SERVER', 'metrics', live='metrics-server'),
    Option('metrics-listen', '--metrics-listen', 'MCH_METRICS_LISTEN', 'metrics'),
    Option('metrics-token', '--metrics-token', 'MCH_METRICS_TOKEN', 'metrics', secret=True),
    Option('metrics-token-file', '--metrics-token-file', 'MCH_METRICS_TOKEN_FILE', 'metrics', secret=True),
    Option('metrics-max-clients', '--metrics-max-clients', 'MCH_METRICS_MAX_CLIENTS', 'metrics'),
    Option('metrics-client-timeout', '--metrics-client-timeout', 'MCH_METRICS_CLIENT_TIMEOUT', 'metrics'),
    Option('metrics-max-conn-per-ip', '--metrics-max-conn-per-ip', 'MCH_METRICS_MAX_CONN_PER_IP', 'metrics'),

    Option('audit-log', '--audit-log', 'MCH_AUDIT_LOG', 'audit'),
    Option('audit-max-mb', '--audit-max-mb', 'MCH_AUDIT_MAX_MB', 'audit'),
    Option('audit-daily', '--audit-daily', 'MCH_AUDIT_DAILY', 'audit'),
    Option('audit-files', '--audit-files', 'MCH_AUDIT_FILES', 'audit'),
    Option('no-audit-log', '--no-audit-log', 'MCH_NO_AUDIT_LOG', 'audit'),
    Option('requests-audit', '--requests-audit', 'MCH_REQUESTS_AUDIT', 'audit', live='requests-audit'),

    Option('log-level', '--log-level', 'MCH_LOG_LEVEL', 'logging', live='log-level'),
    Option('log-access', '--log-access', 'MCH_LOG_ACCESS', 'logging', live=None),
    Option('dump-path', '--dump-path', 'MCH_DUMP_PATH', 'persistence'),
    Option('dump-with-cache', '--dump-with-cache', 'MCH_DUMP_WITH_CACHE', 'persistence'),
    Option('dump-interval', '--dump-interval', 'MCH_DUMP_INTERVAL', 'persistence', live='dump-interval'),
    Option('restore-on-start', '--restore-on-start', 'MCH_RESTORE_ON_START', 'persistence'),
)

OPTION_BY_NAME = {o.name: o for o in OPTIONS}

# the resolved-config keys that do not follow the name.replace('-', '_') rule
CFG_KEYS = {'log-level': 'level', 'requests-audit': 'requests_audit_s', 'cache-ttl': 'cache_ttl'}


def config_value(name, cfg):
    """The set-grammar form of one option's effective startup value (the
    resolved config dict), or None when it should not render (unset secrets
    hide; empty strings drop). Secrets never render inline — the file/flag/
    env form is the documented way, and `show config` output must be safe
    to paste."""
    opt = OPTION_BY_NAME[name]
    key = CFG_KEYS.get(name, name.replace('-', '_'))
    v = cfg.get(key)
    if opt.secret:
        return None
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if key in ('connect_acl', 'write_acl'):
        from .config import acl_text
        return acl_text(v)
    if key == 'write_registers':
        from .config import parse_write_registers
        return 'any' if v is None else ('none' if not v else ','.join('%d:%d' % r for r in v))
    if key == 'control_trust_uids':
        return ','.join(str(u) for u in v) if v else None
    if key == 'selection':
        return v or 'all'
    if key == 'port' or key == 'unit':
        return str(v)
    return str(v)
