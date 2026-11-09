#!/usr/bin/env python3
"""Configuration for the dashboard: the set-grammar config script, the env
layer and the CLI flags (stdlib only).

The precedence is the family's: CLI flags > the env > the config
script > the shipped defaults (lib/static.json). The env twins are the
bare upper-snake names (PORT, BIND, PROM_URL, CONFIG_JS, BATTERY) the
docker image documents. The config file speaks the control grammar
(common/settings/options.py):
every line a `set <name> <value>`, every comment a `#` comment — the ini
format is gone (the breaking wave in docs/TODO.md).
"""
import logging
import os

from .options import OPTIONS
from common.runtime.audit import AUDIT_FILES_MAX, AUDIT_FILES_MIN, AUDIT_MAX_MB_MAX, AUDIT_MAX_MB_MIN
from common.settings.config import check_control_tokens, check_token_chars, load_config_script, parse_listen, parse_secret, \
    resolve_metrics_acl, Resolver, str_to_bool
from .statics import DEFAULTS, DEFAULT_LISTEN, DEFAULT_LISTEN_PORT, LOG_LEVELS

logger = logging.getLogger('dashboard')

# the control socket's name: the daemon's template (common.config's parsers
# take it as the argument), the clients' default (the template spelled with
# the default page port)
CONTROL_SOCKET_TEMPLATE = '/tmp/dashboard-%d.socket'
DEFAULT_CONTROL_SOCKET = CONTROL_SOCKET_TEMPLATE % DEFAULT_LISTEN_PORT


def load_config(path):
    """Parse the set-grammar config script (missing file is fine); a
    malformed file — or the legacy ini format — is fatal. Returns {key:
    raw-string value} with the dash names underscore-normalized."""
    return load_config_script(path, OPTIONS)


def next_to_script(name, script_dir=None):
    """The flattened package layout first (the file next to the script),
    then the dev checkout's subproject root (the parent of bin/)."""
    for base in (script_dir or '.', os.path.dirname(script_dir or '.')):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return os.path.join(script_dir or '.', name)


def resolve_config(args, script_dir=None):
    """Effective settings: CLI flags > env > config script > defaults.

    The environment twins are the bare upper-snake names (no tool prefix):
    the docker image points the proxy at the stack's Prometheus with PROM_URL
    and the served config.js at the config volume with CONFIG_JS.
    """
    ini = load_config(args.config)
    r = Resolver(ini, logger)
    resolve = r.resolve

    static_dir = resolve(args.static_dir, 'STATIC_DIR', 'static_dir',
                         next_to_script('static', script_dir), str)
    if not os.path.isabs(static_dir):
        static_dir = os.path.join(script_dir or '.', static_dir)
    static_dir = os.path.realpath(static_dir)
    config_js = resolve(args.config_js, 'CONFIG_JS', 'config_js',
                        next_to_script('config.js', script_dir), str)
    config_js = os.path.realpath(config_js if os.path.isabs(config_js)
                                 else os.path.join(script_dir or '.', config_js))
    prom_prefix = resolve(args.prom_prefix, 'PROM_PREFIX', 'prom_prefix',
                          DEFAULTS['prom_prefix'], str).rstrip('/')

    cfg = {
        'listen': resolve(args.listen, 'LISTEN', 'listen', DEFAULT_LISTEN, str),
        'upstream': resolve(args.upstream, 'PROM_URL', 'upstream', DEFAULTS['upstream'], str),
        'prom_prefix': prom_prefix,
        'static_dir': static_dir,
        'config_js': config_js,
        'log_queries': resolve(args.log_queries, None, 'log_queries', DEFAULTS['log_queries'], str_to_bool),
        'log_access': resolve(args.log_access, 'LOG_ACCESS', 'log_access',
                              DEFAULTS['log_access'], str_to_bool),
        'local_time': resolve(getattr(args, 'local_time', None), 'LOCAL_TIME',
                              'local_time', False, str_to_bool),
        'max_clients': resolve(getattr(args, 'max_clients', None), 'MAX_CLIENTS',
                               'max_clients', DEFAULTS['max_clients'], int),
        'client_timeout': resolve(getattr(args, 'client_timeout', None), 'CLIENT_TIMEOUT',
                                  'client_timeout', DEFAULTS['client_timeout_s'], float),
        'max_conn_per_ip': resolve(getattr(args, 'max_conn_per_ip', None), 'MAX_CONN_PER_IP',
                                   'max_conn_per_ip', DEFAULTS['max_conn_per_ip'], int),
        'level': resolve(args.log_level, 'LOG_LEVEL', 'log_level', DEFAULTS['log_level'], str).strip().upper(),
    }
    cfg['control_port'] = resolve(getattr(args, 'control_port', None), 'CTL',
                                  'control_port', None, str)
    cfg['audit_log'] = resolve(getattr(args, 'audit_log', None), 'AUDIT_LOG', 'audit_log', None, str)
    cfg['audit_forward'] = resolve(getattr(args, 'audit_forward', None), 'AUDIT_FORWARD',
                                   'audit_forward', 'none', str)
    cfg['audit_max_mb'] = resolve(getattr(args, 'audit_max_mb', None), 'AUDIT_MAX_MB',
                                  'audit_max_mb', DEFAULTS['audit_max_mb'], float)
    cfg['audit_files'] = resolve(getattr(args, 'audit_files', None), 'AUDIT_FILES',
                                 'audit_files', DEFAULTS['audit_files'], int)
    cfg['audit_daily'] = resolve(getattr(args, 'audit_daily', False) or None,
                                 'AUDIT_DAILY', 'audit_daily', False, str_to_bool)
    cfg['no_audit_log'] = resolve(getattr(args, 'no_audit_log', False) or None,
                                  'NO_AUDIT_LOG', 'no_audit_log', False, str_to_bool)
    cfg['control_token'] = parse_secret((resolve(getattr(args, 'control_token', None), 'CONTROL_TOKEN',
                                                 'control_token', None, str) or '').strip() or None, 'control/token')
    cfg['control_ops_token'] = parse_secret((resolve(getattr(args, 'control_ops_token', None), 'CONTROL_OPS_TOKEN',
                                                     'control_ops_token', None, str) or '').strip() or None,
                                            'control-ops-token')
    cfg['control_trust_uids'] = resolve(getattr(args, 'control_trust_uids', None),
                                        'CONTROL_TRUST_UIDS', 'control_trust_uids', None, str)
    cfg['control_socket_group'] = resolve(getattr(args, 'control_socket_group', None), 'CONTROL_SOCKET_GROUP',
                                          'control_socket_group', False, str_to_bool)
    check_control_tokens(cfg['control_token'], cfg['control_ops_token'])
    check_token_chars(cfg['control_token'], 'control_token')
    parse_listen(cfg['listen'])   # the serve address validates: HOST:PORT, the port in range
    if cfg['max_clients'] < 0:
        raise SystemExit('invalid max_clients = %d: must be >= 0 (0 = unlimited)' % cfg['max_clients'])
    if cfg['client_timeout'] < 0:
        raise SystemExit('invalid client_timeout = %g: must be >= 0 (0 = off)' % cfg['client_timeout'])
    if cfg['max_conn_per_ip'] < 0:
        raise SystemExit('invalid max_conn_per_ip = %d: must be >= 0 (0 = no per-IP limit)' % cfg['max_conn_per_ip'])
    if not (AUDIT_MAX_MB_MIN <= cfg['audit_max_mb'] <= AUDIT_MAX_MB_MAX):
        raise SystemExit('invalid audit_max_mb = %g: must be %d..%d (0 = no size rotation)'
                         % (cfg['audit_max_mb'], AUDIT_MAX_MB_MIN, AUDIT_MAX_MB_MAX))
    if not (AUDIT_FILES_MIN <= cfg['audit_files'] <= AUDIT_FILES_MAX):
        raise SystemExit('invalid audit_files = %d: must be %d..%d'
                         % (cfg['audit_files'], AUDIT_FILES_MIN, AUDIT_FILES_MAX))
    if cfg['level'] not in LOG_LEVELS:
        raise SystemExit('invalid log_level = %r: must be one of %s' % (cfg['level'], ', '.join(LOG_LEVELS)))
    cfg['control_ops_verbs'] = (resolve(getattr(args, 'control_ops_verbs', None), 'CONTROL_OPS_VERBS',
                                        'control_ops_verbs', 'show,clear', str) or 'show,clear').strip() or 'show,clear'
    cfg['metrics_server'] = resolve(getattr(args, 'metrics_server', False) or None, 'METRICS_SERVER',
                                    'metrics_server', False, str_to_bool)
    cfg['metrics_listen'] = resolve(getattr(args, 'metrics_listen', None), 'METRICS_LISTEN',
                                    'metrics_listen', DEFAULTS['metrics_listen'], str)
    cfg['metrics_token'] = parse_secret((resolve(getattr(args, 'metrics_token', None), 'METRICS_TOKEN',
                                                  'metrics_token', None, str) or '').strip() or None, 'metrics/token')
    cfg['metrics_acl'] = resolve(getattr(args, 'metrics_acl', None), 'METRICS_ACL',
                                 'metrics_acl', DEFAULTS['metrics_acl'], str) or 'any'
    resolve_metrics_acl(cfg['metrics_acl'], 'metrics/acl')   # a bad acl value or gate file refuses the start
    cfg['auth_token'] = parse_secret((resolve(getattr(args, 'auth_token', None), 'AUTH_TOKEN',
                                              'auth_token', None, str) or '').strip() or None, 'auth/token')
    check_token_chars(cfg['auth_token'], 'auth_token')
    cfg['metrics_max_clients'] = resolve(getattr(args, 'metrics_max_clients', None), 'METRICS_MAX_CLIENTS',
                                         'metrics_max_clients', DEFAULTS['metrics_max_clients'], int)
    cfg['metrics_client_timeout'] = resolve(getattr(args, 'metrics_client_timeout', None),
                                            'METRICS_CLIENT_TIMEOUT', 'metrics_client_timeout',
                                            DEFAULTS['metrics_client_timeout_s'], float)
    cfg['metrics_max_conn_per_ip'] = resolve(getattr(args, 'metrics_max_conn_per_ip', None),
                                             'METRICS_MAX_CONN_PER_IP', 'metrics_max_conn_per_ip',
                                             DEFAULTS['metrics_max_conn_per_ip'], int)
    cfg['dump_path'] = resolve(getattr(args, 'dump_path', None), 'DUMP_PATH', 'dump_path', None, str)
    cfg['dump_key'] = parse_secret((resolve(getattr(args, 'dump_key', None), 'DUMP_KEY', 'dump_key',
                                            None, str) or '').strip() or None, 'dump/key')
    cfg['dump_interval'] = resolve(getattr(args, 'dump_interval', None), 'DUMP_INTERVAL',
                                   'dump_interval', 0.0, float)
    cfg['restore_on_start'] = resolve(getattr(args, 'restore_on_start', False) or None, 'RESTORE_ON_START',
                                      'restore_on_start', False, str_to_bool)
    if cfg['dump_interval'] < 0:
        raise SystemExit('invalid dump_interval = %r: must be >= 0 (0 = off)' % cfg['dump_interval'])
    if cfg['dump_interval'] and not cfg['dump_path']:
        raise SystemExit('invalid dump_interval = %r: needs dump_path set (there is nothing to dump into)'
                         % cfg['dump_interval'])
    control_port = str(cfg['control_port'] or '').strip()
    if control_port.isdigit() and control_port != '0' and not cfg['control_token']:
        raise SystemExit('the TCP control port %s without a token is open to every local process; '
                         'set --control-token (the default unix socket needs none), '
                         'or disable it with --control-port 0' % control_port)
    return cfg
