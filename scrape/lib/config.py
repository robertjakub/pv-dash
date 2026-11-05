#!/usr/bin/env python3
"""Configuration for modbus-scraper: ini/env/CLI resolution (stdlib only)."""
import configparser
import json
import logging
import math
import os
import re

from common.config import check_token_file_mode, default_profile_path, is_loopback_host, parse_listen, resolve_profile_file
from .metrics import Metrics
from .statics import DEFAULTS, LOG_LEVELS, MAX_REGISTERS, UNIT_ID_RANGE

logger = logging.getLogger('scraper')

HOST_RE = re.compile(r'[A-Za-z0-9._:\[\]-]+')


def check_register(value, label):
    if not 0 <= value <= MAX_REGISTERS:
        raise SystemExit('invalid %s = %d: must be 0..%d' % (label, MAX_REGISTERS))
    return value


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
    if not cfg.has_section('scraper'):
        cfg.add_section('scraper')
    return cfg['scraper']


def check_hostname(host, label):
    """Charset/length sanity for inverter host and listen address ('' allowed for listen = all interfaces)."""
    if not host:
        return
    if len(host) > 253:
        raise SystemExit('invalid %s = %r: longer than 253 characters' % (label, host))
    if not HOST_RE.fullmatch(host):
        raise SystemExit('invalid %s = %r: only letters, digits, ".", "-", "_", ":" and "[ ]" allowed'
                         % (label, host))


def validate_config(cfg):
    """Fail fast on nonsensical settings (SystemExit; on SIGHUP the watcher keeps previous)."""

    def fail(key, rule):
        raise SystemExit('invalid %s = %r: %s' % (key, cfg.get(key), rule))

    if not 1 <= cfg['modbus_port'] <= 65535:
        fail('modbus_port', 'must be 1..65535')
    if not UNIT_ID_RANGE[0] <= cfg['unit'] <= UNIT_ID_RANGE[1]:
        fail('unit', 'must be %d..%d (Modbus unit id)' % UNIT_ID_RANGE)
    if not -100000 <= cfg['modbus_offset'] <= 100000:
        fail('modbus_offset', 'must be within +/-100000')
    for key in ('pv_register', 'grid_register', 'battery_register', 'battery_soc_register'):
        check_register(cfg[key], key)
    if cfg['timeout'] <= 0:
        fail('timeout', 'must be > 0')
    if cfg['interval'] <= 0:
        fail('interval', 'must be > 0')
    if cfg['scale'] < 0 or cfg['grid_scale'] < 0:
        fail('scale', 'must be >= 0')
    if cfg['max_kwp'] < 0 or cfg['max_grid_kw'] < 0:
        fail('max_kwp', 'must be 0 (checks off) or a positive kW value')
    if cfg['level'] not in LOG_LEVELS:
        fail('log_level', 'must be one of %s' % ', '.join(LOG_LEVELS))
    if cfg['max_clients'] < 0:
        fail('max_clients', 'must be >= 0 (0 = unlimited)')
    if cfg['client_timeout'] < 0:
        fail('client_timeout', 'must be >= 0 (0 = off)')
    if cfg['max_conn_per_ip'] < 0:
        fail('max_conn_per_ip', 'must be >= 0 (0 = no per-IP limit)')
    for key in ('timeout', 'interval', 'scale', 'grid_scale', 'max_kwp', 'max_grid_kw', 'client_timeout'):
        if not math.isfinite(cfg[key]):
            fail(key, 'must be a finite number (nan/inf are nonsense here)')
    if cfg['timeout'] > cfg['interval']:
        logger.warning('timeout (%gs) > interval (%gs): one poll can take longer than the poll '
                       'interval; the loop simply runs back-to-back', cfg['timeout'], cfg['interval'])
    check_hostname(cfg['host'], 'host')
    if not cfg['host']:
        fail('host', 'must not be empty')
    listen_host, _listen_port = parse_listen(cfg['listen'])
    check_hostname(listen_host, 'listen')
    if not is_loopback_host(listen_host) and not cfg['auth_token']:
        raise SystemExit('refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md): '
                         'listen = %r — set --auth-token/--auth-token-file or bind 127.0.0.1:PORT' % cfg['listen'])


def load_device_profile(path):
    """Device profile (the shared profiles/ schema) -> {name: (register, type, scale, fc)}.
    The fc field is optional (the default 3 = holding registers); 4 = input registers."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read device profile %s: %s' % (path, e))
    entries = data.get('registers') if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise SystemExit('device profile %s must contain a "registers" list' % path)
    out = {}
    for i, entry in enumerate(entries):
        label = 'device profile %s, entry %d' % (path, i + 1)
        if not isinstance(entry, dict) or 'name' not in entry:
            raise SystemExit('%s needs a "name"' % label)
        try:
            register = int(entry['register'])
        except (KeyError, TypeError, ValueError):
            raise SystemExit('%s (%s) needs an integer "register"' % (label, entry['name']))
        typ = str(entry.get('type', 'i32'))
        if typ not in ('i16', 'u16', 'i32', 'u32'):
            raise SystemExit('%s (%s): unknown "type" %r (i16/u16/i32/u32)' % (label, entry['name'], typ))
        try:
            fc = int(entry.get('fc', 3))
        except (TypeError, ValueError):
            raise SystemExit('%s (%s): bad "fc" %r' % (label, entry['name'], entry.get('fc')))
        if fc not in (3, 4):
            raise SystemExit('%s (%s): "fc" must be 3 (holding) or 4 (input), got %d'
                             % (label, entry['name'], fc))
        scale = entry.get('scale', 1.0)
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            raise SystemExit('%s (%s): bad "scale" %r' % (label, entry['name'], scale))
        check_register(register, '%s (%s) register' % (label, entry['name']))
        out[str(entry['name'])] = (register, typ, scale, fc)
    return out


def load_mapping(path):
    """mapping.json: profile register name -> metrics.json catalog key (the
    four register-fed keys: pv, grid, batt_net, batt_soc)."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read mapping spec %s: %s' % (path, e))
    if not isinstance(data, dict):
        raise SystemExit('mapping spec %s must be a JSON object' % path)
    valid = ('pv', 'grid', 'batt_net', 'batt_soc')
    out = {}
    for name, key in data.items():
        if key not in valid:
            raise SystemExit('mapping spec %s: %r maps to %r (valid targets: %s)'
                             % (path, name, key, ', '.join(valid)))
        out[str(name)] = key
    return out


def resolve_config(args, script_dir=None):
    """Effective settings: CLI flags > SCRAPER_* env > [scraper] ini >
    device profile (the shared profiles/ schema) > defaults."""
    cfg = load_config(args.config)

    def resolve(cli_value, env_name, cfg_key, default, conv):
        raw = cli_value
        if raw is None or raw == '':
            raw = os.environ.get(env_name)
        if raw is None or raw == '':
            raw = cfg.get(cfg_key)
        if raw is None or raw == '':
            return default
        try:
            return conv(raw)
        except (TypeError, ValueError) as e:
            logger.error('invalid %s = %r: %s (using %r)', cfg_key, raw, e, default)
            return default

    profile_path = resolve_profile_file(resolve(getattr(args, 'profile', None), 'SCRAPER_PROFILE',
                                                'profile', default_profile_path(), str))
    profile = load_device_profile(profile_path)
    spec = Metrics(resolve(getattr(args, 'metrics_spec', None), 'SCRAPER_METRICS_SPEC',
                           'metrics_spec', None, str))

    # the metrics spec's "profile" fields pick the device registers feeding
    # the register-backed metrics; each source carries register/type/gain
    # and the metric it feeds
    sources = {}
    for profile_name, metric in spec.by_profile.items():
        entry = profile.get(profile_name)
        if entry is None:
            logger.warning('metrics: %r binds profile register %r, which the device profile %s does not define; the metric stays absent',
                           metric, profile_name, profile_path)
            continue
        sources[profile_name] = {'register': entry[0], 'type': entry[1], 'gain': entry[2],
                                 'fc': entry[3], 'metric': metric}
    if 'pv-power' not in sources or 'grid-power' not in sources:
        raise SystemExit('the metrics spec must bind huawei_pv_generation_watts and huawei_grid_net_watts '
                         'to device-profile registers (the power math depends on them)')

    battery = resolve(args.battery, 'SCRAPER_BATTERY', 'battery', False, str_to_bool)
    cfg = {
        'profile': profile_path,
        'host': resolve(args.host, 'SCRAPER_HOST', 'host', DEFAULTS['host'], str),
        'modbus_port': resolve(args.modbus_port, 'SCRAPER_MODBUS_PORT', 'modbus_port',
                               DEFAULTS['modbus_port'], int),
        'unit': resolve(args.unit, 'SCRAPER_UNIT', 'unit', DEFAULTS['unit'], int),
        'modbus_offset': resolve(args.modbus_offset, 'SCRAPER_MODBUS_OFFSET', 'modbus_offset', 0, int),
        'timeout': resolve(args.timeout, 'SCRAPER_TIMEOUT', 'timeout', DEFAULTS['timeout_s'], float),
        'pv_register': resolve(args.pv_register, 'SCRAPER_PV_REGISTER', 'pv_register',
                               sources['pv-power']['register'], int),
        'grid_register': resolve(args.grid_register, 'SCRAPER_GRID_REGISTER', 'grid_register',
                                 sources['grid-power']['register'], int),
        'scale': resolve(args.scale, 'SCRAPER_SCALE', 'scale', DEFAULTS['scale'], float),
        'grid_scale': resolve(args.grid_scale, 'SCRAPER_GRID_SCALE', 'grid_scale', DEFAULTS['grid_scale'], float),
        'max_kwp': resolve(args.max_kwp, 'SCRAPER_MAX_KWP', 'max_kwp', DEFAULTS['max_kwp'], float),
        'max_grid_kw': resolve(args.max_grid_kw, 'SCRAPER_MAX_GRID_KW', 'max_grid_kw', DEFAULTS['max_grid_kw'], float),
        'battery': battery,
        'battery_register': resolve(args.battery_register, 'SCRAPER_BATTERY_REGISTER', 'battery_register',
                                    sources.get('battery-power', {}).get('register', 37001), int),
        'battery_soc_register': resolve(args.battery_soc_register, 'SCRAPER_BATTERY_SOC_REGISTER',
                                        'battery_soc_register',
                                        sources.get('battery-soc', {}).get('register', 37004), int),
        'grid_positive_import': resolve(args.grid_positive_import, 'SCRAPER_GRID_POSITIVE_IMPORT',
                                        'grid_positive_import', False, str_to_bool),
        'listen': resolve(args.listen, 'SCRAPER_LISTEN', 'listen', DEFAULTS['listen'], str),
        'interval': resolve(args.interval, 'SCRAPER_INTERVAL', 'interval', DEFAULTS['interval_s'], float),
        'max_clients': resolve(args.max_clients, 'SCRAPER_MAX_CLIENTS', 'max_clients',
                               DEFAULTS['max_clients'], int),
        'client_timeout': resolve(args.client_timeout, 'SCRAPER_CLIENT_TIMEOUT', 'client_timeout',
                                  DEFAULTS['client_timeout_s'], float),
        'max_conn_per_ip': resolve(getattr(args, 'max_conn_per_ip', None), 'SCRAPER_MAX_CONN_PER_IP',
                                   'max_conn_per_ip', DEFAULTS['max_conn_per_ip'], int),
        'local_time': resolve(args.local_time, 'SCRAPER_LOCAL_TIME', 'local_time', False, str_to_bool),
        'log_access': resolve(args.log_access, 'SCRAPER_LOG_ACCESS', 'log_access', False, str_to_bool),
        'auth_token': (resolve(args.auth_token, 'SCRAPER_AUTH_TOKEN', 'auth_token', None, str) or '').strip() or None,
        'auth_token_file': resolve(args.auth_token_file, 'SCRAPER_AUTH_TOKEN_FILE', 'auth_token_file',
                                   None, str),
        'level': resolve(args.log_level, 'SCRAPER_LOG_LEVEL', 'log_level',
                         DEFAULTS['log_level'], str).strip().upper(),
    }
    if cfg['auth_token'] and any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in cfg['auth_token']):
        raise SystemExit('invalid auth_token: must not contain whitespace or control characters')
    if cfg['auth_token_file'] and any(ord(c) < 32 or ord(c) == 127 for c in cfg['auth_token_file']):
        raise SystemExit('invalid auth_token_file: must not contain control characters')
    if cfg['auth_token'] and cfg['auth_token_file']:
        raise SystemExit('--auth-token and --auth-token-file are mutually exclusive')
    if cfg['auth_token_file']:
        check_token_file_mode(cfg['auth_token_file'], 'auth_token_file')
        try:
            with open(cfg['auth_token_file']) as fh:
                token = fh.read(8192).strip()
        except OSError as e:
            raise SystemExit('cannot read auth_token_file %s: %s' % (cfg['auth_token_file'], e))
        if len(token) >= 8192:
            raise SystemExit('auth_token_file %s: token longer than 8191 characters' % cfg['auth_token_file'])
        if not token:
            raise SystemExit('auth_token_file %s is empty' % cfg['auth_token_file'])
        cfg['auth_token'] = token
    cfg['host'] = cfg['host'].strip()
    cfg['listen'] = cfg['listen'].strip()
    for profile_name, reg_key in (('pv-power', 'pv_register'), ('grid-power', 'grid_register'),
                                  ('battery-power', 'battery_register'), ('battery-soc', 'battery_soc_register')):
        if profile_name in sources:
            sources[profile_name]['register'] = cfg[reg_key]
    cfg['sources'] = sources
    validate_config(cfg)
    return cfg
