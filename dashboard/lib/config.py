#!/usr/bin/env python3
"""Configuration for the dashboard: the set-grammar config script, the env
layer and the CLI flags (stdlib only).

The precedence is the family's: CLI flags > the env > the config
script > the shipped defaults (lib/static.json). The env twins are the
bare upper-snake names (PORT, BIND, PROM_URL, CONFIG_JS, BATTERY) the
docker image documents. The config file speaks the control grammar
(common/options.py):
every line a `set <name> <value>`, every comment a `#` comment — the ini
format is gone (the breaking wave in docs/TODO.md).
"""
import logging
import os

from common.options import parse_config_script
from .options import OPTIONS
from common.config import parse_secret
from .statics import DEFAULTS, DEFAULT_PORT, LOG_LEVELS

logger = logging.getLogger('dashboard')


def resolve_control_target(explicit, listen_port=DEFAULT_PORT):
    """The control server target for the daemon and the clients: the flag
    wins, then CTL, then the default unix socket named after the
    listen port (/tmp/dashboard-8080.socket)."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('CTL')
    if env and env.strip():
        return env.strip()
    return '/tmp/dashboard-%d.socket' % int(listen_port)


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('true', 'yes', 'on', '1'):
        return True
    if text in ('false', 'no', 'off', '0'):
        return False
    raise ValueError('not a boolean')


def load_config(path):
    """Parse the set-grammar config script (missing file is fine); a
    malformed file — or the legacy ini format — is fatal. Returns {key:
    raw-string value} with the dash names underscore-normalized."""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except OSError as e:
        raise SystemExit('cannot read config file %s: %s' % (path, e))
    try:
        rows = parse_config_script(text, path, OPTIONS)   # the registry: the CLI spelling + the unknown-setting fail fast
    except ValueError as e:
        raise SystemExit(str(e))
    out = {}
    for name, value in rows:
        key = name.replace('-', '_')
        if key in out:
            raise SystemExit('%s: %s is set twice (the file applies top to bottom — say it once)'
                             % (path, name))
        out[key] = value
    return out


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

    def resolve(cli_value, env_name, cfg_key, default, conv):
        raw = cli_value
        if raw is None or raw == '':
            raw = os.environ.get(env_name) if env_name else None
        if raw is None or raw == '':
            raw = ini.get(cfg_key)
        if raw is None or raw == '':
            return default
        try:
            return conv(raw)
        except (TypeError, ValueError) as e:
            logger.error('invalid %s = %r: %s (using %r)', cfg_key, raw, e, default)
            return default

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
    battery = resolve(args.battery, 'BATTERY', 'battery', DEFAULTS['battery'], str_to_bool)

    cfg = {
        'port': resolve(args.port, 'PORT', 'port', DEFAULT_PORT, int),
        'bind': resolve(args.bind, 'BIND', 'bind', DEFAULTS['bind'], str),
        'upstream': resolve(args.upstream, 'PROM_URL', 'upstream', DEFAULTS['upstream'], str),
        'prom_prefix': prom_prefix,
        'static_dir': static_dir,
        'config_js': config_js,
        'battery': battery,
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
        'level': resolve(args.log_level, None, 'log_level', DEFAULTS['log_level'], str).strip().upper(),
    }
    cfg['control_port'] = resolve(getattr(args, 'control_port', None), 'CTL',
                                  'control_port', None, str)
    cfg['control_token'] = parse_secret((resolve(getattr(args, 'control_token', None), 'CONTROL_TOKEN',
                                                 'control_token', None, str) or '').strip() or None, 'control/token')
    cfg['control_ops_token'] = parse_secret((resolve(getattr(args, 'control_ops_token', None), 'CONTROL_OPS_TOKEN',
                                                     'control_ops_token', None, str) or '').strip() or None,
                                            'control-ops-token')
    cfg['control_trust_uids'] = resolve(getattr(args, 'control_trust_uids', None),
                                        'CONTROL_TRUST_UIDS', 'control_trust_uids', None, str)
    if cfg['control_ops_token']:
        if not cfg['control_token']:
            raise SystemExit('the read-only ops token supplements the admin token: '
                             'set --control-token too')
        if cfg['control_ops_token'] == cfg['control_token']:
            raise SystemExit('the ops token must differ from the admin token (the same secret would '
                             'hand every holder the role the server picks first)')
    if cfg['control_token'] and any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in cfg['control_token']):
        raise SystemExit('invalid control_token: must not contain whitespace or control characters')
    if cfg['port'] < 1 or cfg['port'] > 65535:
        raise SystemExit('invalid port = %d: must be 1..65535' % cfg['port'])
    if cfg['max_clients'] < 0:
        raise SystemExit('invalid max_clients = %d: must be >= 0 (0 = unlimited)' % cfg['max_clients'])
    if cfg['client_timeout'] < 0:
        raise SystemExit('invalid client_timeout = %g: must be >= 0 (0 = off)' % cfg['client_timeout'])
    if cfg['max_conn_per_ip'] < 0:
        raise SystemExit('invalid max_conn_per_ip = %d: must be >= 0 (0 = no per-IP limit)' % cfg['max_conn_per_ip'])
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
    cfg['restore_on_start'] = resolve(getattr(args, 'restore_on_start', False) or None, 'RESTORE_ON_START',
                                      'restore_on_start', False, str_to_bool)
    control_port = str(cfg['control_port'] or '').strip()
    if control_port.isdigit() and control_port != '0' and not cfg['control_token']:
        raise SystemExit('the TCP control port %s without a token is open to every local process; '
                         'set --control-token (the default unix socket needs none), '
                         'or disable it with --control-port 0' % control_port)
    return cfg
