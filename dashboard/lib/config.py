#!/usr/bin/env python3
"""Configuration for the dashboard: ini/env/CLI resolution (stdlib only).

The precedence is the family's: CLI flags > the DASHBOARD_* env > the
[server] ini > the shipped defaults (lib/static.json). The generic envs the
docker image documents (PORT, BIND, PROM_URL, CONFIG_JS, BATTERY) keep
working alongside.
"""
import configparser
import logging
import os

from common.config import load_token_file
from .statics import DEFAULTS, DEFAULT_PORT, LOG_LEVELS

logger = logging.getLogger('dashboard')


def resolve_control_target(explicit, listen_port=DEFAULT_PORT):
    """The control server target for the daemon and the clients: the flag
    wins, then DASHBOARD_CTL, then the default unix socket named after the
    listen port (/tmp/dashboard-8080.socket)."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('DASHBOARD_CTL')
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
    """Parse the ini (missing file is fine); a malformed file is fatal."""
    cfg = configparser.ConfigParser()
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                cfg.read_file(fh)
        except (configparser.Error, OSError) as e:
            raise SystemExit('cannot parse config file %s: %s' % (path, e))
    if not cfg.has_section('server'):
        cfg.add_section('server')
    return cfg['server']


def next_to_script(name, script_dir=None):
    """The flattened package layout first (the file next to the script),
    then the dev checkout's subproject root (the parent of bin/)."""
    for base in (script_dir or '.', os.path.dirname(script_dir or '.')):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return os.path.join(script_dir or '.', name)


def resolve_config(args, script_dir=None):
    """Effective settings: CLI flags > env > [server] ini > defaults.

    The legacy generic envs (PORT, BIND, STATIC_DIR, CONFIG_JS, PROM_PREFIX,
    PROM_URL, BATTERY) keep their place between the flags and the ini — the
    docker image points the proxy at the stack's Prometheus with PROM_URL
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
        'log_access': resolve(args.log_access, 'DASHBOARD_LOG_ACCESS', 'log_access',
                              DEFAULTS['log_access'], str_to_bool),
        'local_time': resolve(getattr(args, 'local_time', None), 'DASHBOARD_LOCAL_TIME',
                              'local_time', False, str_to_bool),
        'max_clients': resolve(getattr(args, 'max_clients', None), 'DASHBOARD_MAX_CLIENTS',
                               'max_clients', DEFAULTS['max_clients'], int),
        'client_timeout': resolve(getattr(args, 'client_timeout', None), 'DASHBOARD_CLIENT_TIMEOUT',
                                  'client_timeout', DEFAULTS['client_timeout_s'], float),
        'max_conn_per_ip': resolve(getattr(args, 'max_conn_per_ip', None), 'DASHBOARD_MAX_CONN_PER_IP',
                                   'max_conn_per_ip', DEFAULTS['max_conn_per_ip'], int),
        'level': resolve(args.log_level, None, 'log_level', DEFAULTS['log_level'], str).strip().upper(),
    }
    cfg['control_port'] = resolve(getattr(args, 'control_port', None), 'DASHBOARD_CONTROL_PORT',
                                  'control_port', None, str)
    cfg['control_token'] = (resolve(getattr(args, 'control_token', None), 'DASHBOARD_CONTROL_TOKEN',
                                    'control_token', None, str) or '').strip() or None
    control_token_file = resolve(getattr(args, 'control_token_file', None), 'DASHBOARD_CONTROL_TOKEN_FILE',
                                 'control_token_file', None, str)
    cfg['control_trust_uids'] = resolve(getattr(args, 'control_trust_uids', None),
                                        'DASHBOARD_CONTROL_TRUST_UIDS', 'control_trust_uids', None, str)
    if cfg['control_token'] and control_token_file:
        raise SystemExit('--control-token and --control-token-file are mutually exclusive')
    if control_token_file:
        cfg['control_token'] = load_token_file(control_token_file, 'control-token-file')
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
    control_port = str(cfg['control_port'] or '').strip()
    if control_port.isdigit() and control_port != '0' and not cfg['control_token']:
        raise SystemExit('the TCP control port %s without a token is open to every local process; '
                         'set --control-token or --control-token-file (the default unix socket needs none), '
                         'or disable it with --control-port 0' % control_port)
    return cfg
