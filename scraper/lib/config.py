#!/usr/bin/env python3
"""Configuration for modbus-scraper: the set-grammar config script, the env
layer and the CLI flags (stdlib only). The config file speaks the control
grammar (common/options.py): every line a `set <name> <value>`, every
comment a `#` comment — the ini format is gone (the breaking wave in
docs/TODO.md)."""
import json
import logging
import math
import os
import re

from common.options import parse_config_script
from .options import OPTIONS
from common.config import check_auth_key, check_token_file_mode, default_profile_path, is_loopback_host, \
    load_token_file, parse_auth_type, parse_listen, parse_secret, parse_upstream, resolve_profile_file
from .metrics import Metrics
from .statics import DEFAULTS, DEFAULT_LISTEN_PORT, LOG_LEVELS, MAX_REGISTERS, UNIT_ID_RANGE

logger = logging.getLogger('scraper')

HOST_RE = re.compile(r'[A-Za-z0-9._:\[\]-]+')


def resolve_control_target(explicit, listen_port=DEFAULT_LISTEN_PORT):
    """The control server target for the daemon and the clients: the flag
    wins, then CTL, then the default unix socket named after the
    listen port (/tmp/modbus-scraper-9350.socket)."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('CTL')
    if env and env.strip():
        return env.strip()
    return '/tmp/modbus-scraper-%d.socket' % int(listen_port)


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
    if not UNIT_ID_RANGE[0] <= cfg['modbus_unit'] <= UNIT_ID_RANGE[1]:
        fail('modbus-unit', 'must be %d..%d (Modbus unit id)' % UNIT_ID_RANGE)
    if not -100000 <= cfg['modbus_offset'] <= 100000:
        fail('modbus_offset', 'must be within +/-100000')
    if cfg['timeout'] <= 0:
        fail('timeout', 'must be > 0')
    if cfg['interval'] <= 0:
        fail('interval', 'must be > 0')
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
    for key in ('timeout', 'interval', 'max_kwp', 'max_grid_kw', 'client_timeout'):
        if not math.isfinite(cfg[key]):
            fail(key, 'must be a finite number (nan/inf are nonsense here)')
    if cfg['timeout'] > cfg['interval']:
        logger.warning('timeout (%gs) > interval (%gs): one poll can take longer than the poll '
                       'interval; the loop simply runs back-to-back', cfg['timeout'], cfg['interval'])
    check_hostname(cfg['host'], 'upstream host')
    if cfg['auth'] and not cfg['auth_key']:
        fail('auth', "the suite auth needs a key: set --auth-key/$AUTH_KEY too (min 16 characters)")
    listen_host, _listen_port = parse_listen(cfg['listen'])
    check_hostname(listen_host, 'listen')
    if not is_loopback_host(listen_host) and not cfg['auth_token']:
        raise SystemExit('refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md): '
                         'listen = %r — set --auth-token/--auth-token-file or bind 127.0.0.1:PORT' % cfg['listen'])
    control_port = str(cfg.get('control_port') or '').strip()
    if control_port.isdigit() and control_port != '0' and not cfg.get('control_token'):
        raise SystemExit('the TCP control port %s without a token is open to every local process; '
                         'set --control-token or --control-token-file (the default unix socket needs none), '
                         'or disable it with --control-port 0' % control_port)


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
        if not math.isfinite(scale) or scale <= 0:
            raise SystemExit('%s (%s): "scale" %r must be a finite number > 0 '
                             '(the decode divides the wire value by it)' % (label, entry['name'], scale))
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


def build_sources(profile, spec, profile_path):
    """Bind the metrics spec's "profile" fields to the device profile's
    registers: {profile register name: {register, type, gain, fc, metric}}.
    Each source carries register/type/gain and the metric it feeds; the
    power math depends on pv-power and grid-power (ValueError when the
    profile lacks them — the live `set profile` rolls back on it)."""
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
        raise ValueError('the metrics spec must bind %s to device-profile registers '
                         '(the power math depends on them)' %
                         ' and '.join(spec.by_profile.get(n, n) for n in ('pv-power', 'grid-power')
                                      if n not in sources))
    return sources


def resolve_config(args, script_dir=None):
    """Effective settings: CLI flags > env > config script >
    device profile (the shared profiles/ schema) > defaults. The register
    map itself — addresses, types, gains, function codes — comes from the
    device profile alone: there are no register override knobs."""
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

    profile_path = resolve_profile_file(resolve(getattr(args, 'profile', None), 'PROFILE',
                                                'profile', default_profile_path(), str))
    profile = load_device_profile(profile_path)
    metric_prefix = (resolve(getattr(args, 'metric_prefix', None), 'METRIC_PREFIX',
                             'metric_prefix', 'huawei', str) or 'huawei').strip() or 'huawei'
    spec = Metrics(resolve(getattr(args, 'metrics_spec', None), 'METRICS_SPEC',
                           'metrics_spec', None, str), prefix=metric_prefix)

    # the metrics spec's "profile" fields pick the device registers feeding
    # the register-backed metrics; each source carries register/type/gain
    # and the metric it feeds
    try:
        sources = build_sources(profile, spec, profile_path)
    except ValueError as e:
        raise SystemExit(str(e))

    battery = resolve(args.battery, 'BATTERY', 'battery', False, str_to_bool)
    upstream = resolve(getattr(args, 'upstream', None), 'UPSTREAM', 'upstream',
                       DEFAULTS['upstream'], str)
    host, modbus_port = parse_upstream(upstream or DEFAULTS['upstream'])
    cfg = {
        'profile': profile_path,
        'upstream': '%s:%d' % (host, modbus_port),
        'host': host,
        'modbus_port': modbus_port,
        'modbus_unit': resolve(getattr(args, 'modbus_unit', None), 'MODBUS_UNIT',
                               'modbus_unit', DEFAULTS['modbus_unit'], int),
        'modbus_offset': resolve(args.modbus_offset, 'MODBUS_OFFSET', 'modbus_offset', 0, int),
        'auth': parse_auth_type(resolve(getattr(args, 'auth', None), 'AUTH', 'auth', '', str), 'auth'),
        'auth_key': check_auth_key(
            parse_secret((resolve(getattr(args, 'auth_key', None), 'AUTH_KEY', 'auth_key', '', str)
                          or '').strip() or None, 'auth-key'), 'auth-key'),
        'timeout': resolve(args.timeout, 'TIMEOUT', 'timeout', DEFAULTS['timeout_s'], float),
        'max_kwp': resolve(args.max_kwp, 'MAX_KWP', 'max_kwp', DEFAULTS['max_kwp'], float),
        'max_grid_kw': resolve(args.max_grid_kw, 'MAX_GRID_KW', 'max_grid_kw', DEFAULTS['max_grid_kw'], float),
        'battery': battery,
        'grid_positive_import': resolve(args.grid_positive_import, 'GRID_POSITIVE_IMPORT',
                                        'grid_positive_import', False, str_to_bool),
        'listen': resolve(args.listen, 'LISTEN', 'listen', DEFAULTS['listen'], str),
        'interval': resolve(args.interval, 'INTERVAL', 'interval', DEFAULTS['interval_s'], float),
        'max_clients': resolve(args.max_clients, 'MAX_CLIENTS', 'max_clients',
                               DEFAULTS['max_clients'], int),
        'client_timeout': resolve(args.client_timeout, 'CLIENT_TIMEOUT', 'client_timeout',
                                  DEFAULTS['client_timeout_s'], float),
        'max_conn_per_ip': resolve(getattr(args, 'max_conn_per_ip', None), 'MAX_CONN_PER_IP',
                                   'max_conn_per_ip', DEFAULTS['max_conn_per_ip'], int),
        'local_time': resolve(args.local_time, 'LOCAL_TIME', 'local_time', False, str_to_bool),
        'log_access': resolve(args.log_access, 'LOG_ACCESS', 'log_access', False, str_to_bool),
        'metric_prefix': metric_prefix,
        'auth_token': parse_secret((resolve(args.auth_token, 'AUTH_TOKEN', 'auth_token', None, str)
                                    or '').strip() or None, 'auth/token'),
        'auth_token_file': resolve(args.auth_token_file, 'AUTH_TOKEN_FILE', 'auth_token_file',
                                   None, str),
        'level': resolve(args.log_level, 'LOG_LEVEL', 'log_level',
                         DEFAULTS['log_level'], str).strip().upper(),
    }
    cfg['control_port'] = resolve(getattr(args, 'control_port', None), 'CTL',
                                  'control_port', None, str)
    cfg['control_token'] = parse_secret((resolve(getattr(args, 'control_token', None), 'CONTROL_TOKEN',
                                                 'control_token', None, str) or '').strip() or None, 'control/token')
    control_token_file = resolve(getattr(args, 'control_token_file', None), 'CONTROL_TOKEN_FILE',
                                 'control_token_file', None, str)
    cfg['control_ops_token'] = parse_secret((resolve(getattr(args, 'control_ops_token', None), 'CONTROL_OPS_TOKEN',
                                                     'control_ops_token', None, str) or '').strip() or None,
                                            'control-ops-token')
    control_ops_token_file = resolve(getattr(args, 'control_ops_token_file', None), 'CONTROL_OPS_TOKEN_FILE',
                                     'control_ops_token_file', None, str)
    cfg['control_ops_verbs'] = (resolve(getattr(args, 'control_ops_verbs', None), 'CONTROL_OPS_VERBS',
                                        'control_ops_verbs', 'show,clear', str) or 'show,clear').strip() or 'show,clear'
    cfg['control_trust_uids'] = resolve(getattr(args, 'control_trust_uids', None), 'CONTROL_TRUST_UIDS',
                                        'control_trust_uids', None, str)
    if cfg['control_token'] and control_token_file:
        raise SystemExit('--control-token and --control-token-file are mutually exclusive')
    if control_token_file:
        cfg['control_token'] = load_token_file(control_token_file, 'control-token-file')
    if cfg['control_ops_token'] and control_ops_token_file:
        raise SystemExit('--control-ops-token and --control-ops-token-file are mutually exclusive')
    if control_ops_token_file:
        cfg['control_ops_token'] = load_token_file(control_ops_token_file, 'control-ops-token-file')
    if cfg['control_ops_token']:
        if not cfg['control_token']:
            raise SystemExit('the read-only ops token supplements the admin token: '
                             'set --control-token/--control-token-file too')
        if cfg['control_ops_token'] == cfg['control_token']:
            raise SystemExit('the ops token must differ from the admin token (the same secret would '
                             'hand every holder the role the server picks first)')
    if cfg['control_token'] and any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in cfg['control_token']):
        raise SystemExit('invalid control_token: must not contain whitespace or control characters')
    if cfg['auth_token'] and any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in cfg['auth_token']):
        raise SystemExit('invalid auth_token: must not contain whitespace or control characters')
    if cfg['auth_token_file'] and any(ord(c) < 32 or ord(c) == 127 for c in cfg['auth_token_file']):
        raise SystemExit('invalid auth_token_file: must not contain control characters')
    if cfg['auth_token'] and cfg['auth_token_file']:
        raise SystemExit('--auth-token and --auth-token-file are mutually exclusive')
    if not re.match(r'[A-Za-z_][A-Za-z0-9_]*$', cfg['metric_prefix']):
        raise SystemExit('invalid metric_prefix = %r: must be a valid metric-name start '
                         '(letters/digits/underscore, not starting with a digit)' % cfg['metric_prefix'])
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
    cfg['dump_path'] = resolve(getattr(args, 'dump_path', None), 'DUMP_PATH', 'dump_path', None, str)
    cfg['dump_key'] = parse_secret((resolve(getattr(args, 'dump_key', None), 'DUMP_KEY', 'dump_key',
                                            None, str) or '').strip() or None, 'dump/key')
    cfg['restore_on_start'] = resolve(getattr(args, 'restore_on_start', False) or None, 'RESTORE_ON_START',
                                      'restore_on_start', False, str_to_bool)
    cfg['listen'] = cfg['listen'].strip()
    cfg['sources'] = sources
    validate_config(cfg)
    return cfg
