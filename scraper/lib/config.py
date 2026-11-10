#!/usr/bin/env python3
"""Configuration for modbus-scraper: the set-grammar config script, the env
layer and the CLI flags (stdlib only). The config file speaks the control
grammar (common/settings/options.py): every line a `set <name> <value>`, every
comment a `#` comment — the ini format is gone (the breaking wave in
docs/TODO.md)."""
import json
import logging
import math
import re

from .options import DEFAULT_OPS_VERBS, OPTIONS
from common.runtime.audit import AUDIT_FILES_MAX, AUDIT_FILES_MIN, AUDIT_MAX_MB_MAX, AUDIT_MAX_MB_MIN
from common.settings.config import (check_auth_key, check_token_chars, check_control_tokens,
                           is_loopback_host, load_config_script, parse_acl, parse_auth_type, parse_listen,
                           parse_secret, parse_upstream, resolve_metrics_acl, resolve_profile_file, Resolver,
                           str_to_bool)
from .metrics import Metrics
from .statics import DEFAULTS, DEFAULT_LISTEN_PORT, LOG_LEVELS, MAX_REGISTERS, UNIT_ID_RANGE

logger = logging.getLogger('scraper')

HOST_RE = re.compile(r'[A-Za-z0-9._:\[\]-]+')

# the control socket's name: the daemon's template (common.config's parsers
# take it as the argument), the clients' default (the template spelled with
# the default serving port)
CONTROL_SOCKET_TEMPLATE = '/tmp/modbus-scraper-%d.socket'
DEFAULT_CONTROL_SOCKET = CONTROL_SOCKET_TEMPLATE % DEFAULT_LISTEN_PORT


def check_register(value, label):
    if not 0 <= value <= MAX_REGISTERS:
        raise SystemExit('invalid %s = %d: must be 0..%d' % (label, MAX_REGISTERS))
    return value


def load_config(path):
    """Parse the set-grammar config script (missing file is fine); a
    malformed file — or the legacy ini format — is fatal. Returns {key:
    raw-string value} with the dash names underscore-normalized."""
    return load_config_script(path, OPTIONS)


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
    if not (AUDIT_MAX_MB_MIN <= cfg['audit_max_mb'] <= AUDIT_MAX_MB_MAX):
        fail('audit_max_mb', 'must be %d..%d (0 = no size rotation)'
             % (AUDIT_MAX_MB_MIN, AUDIT_MAX_MB_MAX))
    if not (AUDIT_FILES_MIN <= cfg['audit_files'] <= AUDIT_FILES_MAX):
        fail('audit_files', 'must be %d..%d' % (AUDIT_FILES_MIN, AUDIT_FILES_MAX))
    for key in ('timeout', 'interval', 'max_kwp', 'max_grid_kw', 'client_timeout'):
        if not math.isfinite(cfg[key]):
            fail(key, 'must be a finite number (nan/inf are nonsense here)')
    if cfg['dump_interval'] < 0:
        fail('dump_interval', 'must be >= 0 (0 = off)')
    if not math.isfinite(cfg['dump_interval']):
        fail('dump_interval', 'must be a finite number (nan/inf are nonsense here)')
    if cfg['dump_interval'] and not cfg['dump_path']:
        fail('dump_interval', 'needs dump_path set (there is nothing to dump into)')
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
                         'listen = %r — set --auth-token (or file:<path>) or bind 127.0.0.1:PORT' % cfg['listen'])
    control_port = str(cfg.get('control_port') or '').strip()
    if control_port.isdigit() and control_port != '0' and not cfg.get('control_token'):
        raise SystemExit('the TCP control port %s without a token is open to every local process; '
                         'set --control-token (the default unix socket needs none), '
                         'or disable it with --control-port 0' % control_port)


def load_device_profile(path):
    """Device profile (the shared profiles/ schema) -> {name: (register, type, scale, fc)}.
    The fc field is optional; the type picks its legal range and default:
    word types (i16/u16/i32/u32/i32swap/u32swap/f32/f32swap) read on FC3
    (holding) or FC4 (input), the bit type reads on FC1 (coils, the
    default) or FC2 (discrete inputs)."""
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
        if typ not in ('i16', 'u16', 'i32', 'u32', 'i32swap', 'u32swap', 'f32', 'f32swap', 'bit'):
            raise SystemExit('%s (%s): unknown "type" %r (i16/u16/i32/u32/i32swap/u32swap/f32/f32swap/bit)'
                             % (label, entry['name'], typ))
        try:
            fc = int(entry.get('fc', 1 if typ == 'bit' else 3))
        except (TypeError, ValueError):
            raise SystemExit('%s (%s): bad "fc" %r' % (label, entry['name'], entry.get('fc')))
        if fc not in ((1, 2) if typ == 'bit' else (3, 4)):
            raise SystemExit('%s (%s): "fc" must be %s, got %d'
                             % (label, entry['name'],
                                '1 (coils) or 2 (discrete inputs)' if typ == 'bit'
                                else '3 (holding) or 4 (input)', fc))
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
    r = Resolver(cfg, logger)
    resolve = r.resolve

    profile_path = resolve_profile_file(resolve(getattr(args, 'profile', None), 'PROFILE',
                                                'profile', DEFAULTS['modbus_profile'], str))
    profile = load_device_profile(profile_path)
    prefix_default = DEFAULTS['metric_prefix']
    metric_prefix = (resolve(getattr(args, 'metric_prefix', None), 'METRIC_PREFIX',
                             'metric_prefix', prefix_default, str)
                     or prefix_default).strip() or prefix_default
    metrics_spec = resolve(getattr(args, 'metrics_spec', None), 'METRICS_SPEC',
                           'metrics_spec', None, str)
    spec = Metrics(metrics_spec, prefix=metric_prefix)

    # the metrics spec's "profile" fields pick the device registers feeding
    # the register-backed metrics; each source carries register/type/gain
    # and the metric it feeds
    try:
        sources = build_sources(profile, spec, profile_path)
    except ValueError as e:
        raise SystemExit(str(e))

    upstream = resolve(getattr(args, 'upstream', None), 'UPSTREAM', 'upstream',
                       DEFAULTS['upstream'], str)
    host, modbus_port = parse_upstream(upstream or DEFAULTS['upstream'])
    cfg = {
        'profile': profile_path,
        'metrics_spec': metrics_spec,
        'upstream': '%s:%d' % (host, modbus_port),
        'host': host,
        'modbus_port': modbus_port,
        'modbus_unit': resolve(getattr(args, 'modbus_unit', None), 'MODBUS_UNIT',
                               'modbus_unit', DEFAULTS['modbus_unit'], int),
        'modbus_offset': resolve(args.modbus_offset, 'MODBUS_OFFSET', 'modbus_offset',
                                 DEFAULTS['modbus_offset'], int),
        'auth': parse_auth_type(resolve(getattr(args, 'modbus_auth', None), 'MODBUS_AUTH', 'modbus-auth', DEFAULTS['modbus_auth'], str), 'modbus-auth'),
        'auth_key': check_auth_key(
            parse_secret((resolve(getattr(args, 'auth_key', None), 'AUTH_KEY', 'auth_key', '', str)
                          or '').strip() or None, 'auth-key'), 'auth-key'),
        'timeout': resolve(args.timeout, 'TIMEOUT', 'timeout', DEFAULTS['timeout_s'], float),
        'max_kwp': resolve(args.max_kwp, 'MAX_KWP', 'max_kwp', DEFAULTS['max_kwp'], float),
        'max_grid_kw': resolve(args.max_grid_kw, 'MAX_GRID_KW', 'max_grid_kw', DEFAULTS['max_grid_kw'], float),
        'grid_positive_import': resolve(args.grid_positive_import or None, 'GRID_POSITIVE_IMPORT',
                                        'grid_positive_import', DEFAULTS['grid_positive_import'], str_to_bool),
        'listen': resolve(args.listen, 'LISTEN', 'listen', DEFAULTS['listen'], str),
        'interval': resolve(args.interval, 'INTERVAL', 'interval', DEFAULTS['interval_s'], float),
        'max_clients': resolve(args.max_clients, 'MAX_CLIENTS', 'max_clients',
                               DEFAULTS['max_clients'], int),
        'client_timeout': resolve(args.client_timeout, 'CLIENT_TIMEOUT', 'client_timeout',
                                  DEFAULTS['client_timeout_s'], float),
        'max_conn_per_ip': resolve(getattr(args, 'max_conn_per_ip', None), 'MAX_CONN_PER_IP',
                                   'max_conn_per_ip', DEFAULTS['max_conn_per_ip'], int),
        'metrics_acl': (resolve(getattr(args, 'metrics_acl', None), 'METRICS_ACL',
                                'metrics_acl', DEFAULTS['metrics_acl'], str) or '').strip() or 'any',
        'local_time': resolve(args.local_time or None, 'LOCAL_TIME', 'local_time', DEFAULTS['local_time'], str_to_bool),
        'log_access': resolve(args.log_access or None, 'LOG_ACCESS', 'log_access', DEFAULTS['log_access'], str_to_bool),
        'metric_prefix': metric_prefix,
        'auth_token': parse_secret((resolve(args.auth_token, 'AUTH_TOKEN', 'auth_token', None, str)
                                    or '').strip() or None, 'auth/token'),
        'level': resolve(args.log_level, 'LOG_LEVEL', 'log_level',
                         DEFAULTS['log_level'], str).strip().upper(),
    }
    cfg['control_port'] = resolve(getattr(args, 'control_port', None), 'CTL',
                                  'control_port', None, str)
    cfg['control_token'] = parse_secret((resolve(getattr(args, 'control_token', None), 'CONTROL_TOKEN',
                                                 'control_token', None, str) or '').strip() or None, 'control/token')
    cfg['control_ops_token'] = parse_secret((resolve(getattr(args, 'control_ops_token', None), 'CONTROL_OPS_TOKEN',
                                                     'control_ops_token', None, str) or '').strip() or None,
                                            'control-ops-token')
    cfg['control_ops_verbs'] = (resolve(getattr(args, 'control_ops_verbs', None), 'CONTROL_OPS_VERBS',
                                        'control_ops_verbs', DEFAULT_OPS_VERBS,
                                        str) or DEFAULT_OPS_VERBS).strip() or DEFAULT_OPS_VERBS
    cfg['control_trust_uids'] = resolve(getattr(args, 'control_trust_uids', None), 'CONTROL_TRUST_UIDS',
                                        'control_trust_uids', DEFAULTS['control_trust_uids'], str)
    cfg['control_socket_group'] = resolve(getattr(args, 'control_socket_group', False) or None,
                                          'CONTROL_SOCKET_GROUP', 'control_socket_group', DEFAULTS['control_socket_group'], str_to_bool)
    cfg['audit_log'] = resolve(getattr(args, 'audit_log', None), 'AUDIT_LOG', 'audit_log', DEFAULTS['audit_log'], str)
    cfg['audit_forward'] = resolve(getattr(args, 'audit_forward', None), 'AUDIT_FORWARD',
                                   'audit_forward', DEFAULTS['audit_forward'], str)
    cfg['audit_forward_format'] = resolve(getattr(args, 'audit_forward_format', None), 'AUDIT_FORWARD_FORMAT',
                                          'audit_forward_format', DEFAULTS['audit_forward_format'], str)
    cfg['audit_max_mb'] = resolve(getattr(args, 'audit_max_mb', None), 'AUDIT_MAX_MB',
                                  'audit_max_mb', DEFAULTS['audit_max_mb'], float)
    cfg['audit_files'] = resolve(getattr(args, 'audit_files', None), 'AUDIT_FILES',
                                 'audit_files', DEFAULTS['audit_files'], int)
    cfg['audit_daily'] = resolve(getattr(args, 'audit_daily', False) or None,
                                 'AUDIT_DAILY', 'audit_daily', DEFAULTS['audit_daily'], str_to_bool)
    cfg['no_audit_log'] = resolve(getattr(args, 'no_audit_log', False) or None,
                                  'NO_AUDIT_LOG', 'no_audit_log', DEFAULTS['no_audit_log'], str_to_bool)
    check_control_tokens(cfg['control_token'], cfg['control_ops_token'])
    check_token_chars(cfg['control_token'], 'control_token')
    check_token_chars(cfg['auth_token'], 'auth_token')
    resolve_metrics_acl(cfg['metrics_acl'])   # a bad acl value or gate file refuses the start
    if not re.match(r'[A-Za-z_][A-Za-z0-9_]*$', cfg['metric_prefix']):
        raise SystemExit('invalid metric_prefix = %r: must be a valid metric-name start '
                         '(letters/digits/underscore, not starting with a digit)' % cfg['metric_prefix'])
    cfg['dump_path'] = resolve(getattr(args, 'dump_path', None), 'DUMP_PATH', 'dump_path', DEFAULTS['dump_path'], str)
    cfg['dump_key'] = parse_secret((resolve(getattr(args, 'dump_key', None), 'DUMP_KEY', 'dump_key',
                                            None, str) or '').strip() or None, 'dump/key')
    cfg['dump_interval'] = resolve(getattr(args, 'dump_interval', None), 'DUMP_INTERVAL',
                                   'dump_interval', DEFAULTS['dump_interval'], float)
    cfg['restore_on_start'] = resolve(getattr(args, 'restore_on_start', False) or None, 'RESTORE_ON_START',
                                      'restore_on_start', DEFAULTS['restore_on_start'], str_to_bool)
    cfg['listen'] = cfg['listen'].strip()
    cfg['sources'] = sources
    validate_config(cfg)
    return cfg
