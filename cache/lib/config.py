#!/usr/bin/env python3
"""Configuration for modbus-cache: ini/env/CLI resolution and the register map (stdlib only)."""
import configparser
import ipaddress
import json
import logging
import os

from common.config import default_profile_path, parse_listen, resolve_profile_file
from common.cred import parse_trust_uids
from .statics import DEFAULTS, DEFAULT_LISTEN_PORT, MAX_COUNT, MAX_REGISTERS, \
    REGISTER_TYPES, UNIT_ID_RANGE

logger = logging.getLogger('modbus-cache')


def parse_control_target(text, listen_port=DEFAULT_LISTEN_PORT):
    """'' → the default unix socket for the listen port (/tmp is cleared on
    reboot, nothing lands in a working directory); '0' → None (off); digits
    → TCP port on 127.0.0.1; anything else → unix socket path."""
    t = (text or '').strip()
    if t == '0':
        return None
    if t.isdigit():
        p = int(t)
        if not 1 <= p <= 65535:
            raise SystemExit('invalid control-port %d: use 1..65535, a unix socket path, or 0 to disable' % p)
        return p
    if t:
        return t
    return '/tmp/modbus-cache-%d.socket' % listen_port


def resolve_control_target(explicit, listen_port=DEFAULT_LISTEN_PORT):
    """--control-port flag > MODBUS_CACHE_CTL / CACHE_CTL environment > default socket."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('MODBUS_CACHE_CTL') or os.environ.get('CACHE_CTL')
    if env and env.strip():
        return env.strip()
    return '/tmp/modbus-cache-%d.socket' % listen_port


def parse_acl(text, label):
    """'any'/empty/None -> None (allow all); 'IP, CIDR, ...' -> tuple of networks."""
    if text is None or str(text).strip() in ('', 'any', '*'):
        return None
    nets = []
    for part in str(text).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError as e:
            raise SystemExit('%s: bad ACL entry %r (%s)' % (label, part, e))
    return tuple(nets)


def parse_write_registers(text, label='write-registers'):
    """'any'/empty/None -> None (any register writable); 'START:COUNT,...'
    (comma-separated) -> tuple of (start, count) ranges. A write is allowed
    only when every register it touches lands inside one of the ranges."""
    if text is None or str(text).strip() in ('', 'any', '*'):
        return None
    ranges = []
    for part in str(text).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            start, count = (int(x) for x in part.split(':'))
        except ValueError:
            raise SystemExit('%s entries must be START:COUNT, got %r' % (label, part))
        if start < 0 or count < 1 or start + count > MAX_REGISTERS or count > MAX_COUNT:
            raise SystemExit('%s: range %d:%d out of bounds (0..%d, max %d registers)'
                             % (label, start, count, MAX_REGISTERS - 1, MAX_COUNT))
        ranges.append((start, count))
    if not ranges:
        return None
    return tuple(ranges)


def check_range(start, count, label):
    if start < 0 or start + count > MAX_REGISTERS or not 0 < count <= MAX_COUNT:
        raise SystemExit('%s out of bounds' % label)
    return (start, count)


def parse_range(text, label):
    try:
        start, count = str(text).split(':')
        start, count = int(start), int(count)
    except ValueError:
        raise SystemExit('%s must be START:COUNT, got %r' % (label, text))
    return check_range(start, count, label)


def load_registers_file(path):
    """Device profile: {"registers": [{"name", "register", "type", "fc", ...}]} —
    the shared schema from the profiles/ subproject. Returns the full
    (ranges, names) map; which entries are actually fetched is the
    selection file's job (load_selection). "type" gives the word width
    (i16/u16 = 1 register word, i32/u32 = 2). "fc" is the function code the
    device answers for the entry: 3 (holding registers, the default) or 4
    (input registers); the two address spaces are cached separately."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read device profile %s: %s' % (path, e))
    entries = data.get('registers') if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise SystemExit('device profile %s must contain a "registers" list' % path)
    ranges, names, ttls = [], {}, {}
    for i, entry in enumerate(entries):
        label = 'device profile %s, entry %d' % (path, i + 1)
        if not isinstance(entry, dict) or 'name' not in entry:
            raise SystemExit('%s needs a "name"' % label)
        try:
            start = int(entry['register'])
        except (KeyError, TypeError, ValueError):
            raise SystemExit('%s (%s) needs an integer "register"' % (label, entry['name']))
        typ = str(entry.get('type', 'i32'))
        count = REGISTER_TYPES.get(typ)
        if count is None:
            raise SystemExit('%s (%s): unknown "type" %r (i16/u16/i32/u32)' % (label, entry['name'], typ))
        fc = entry.get('fc', 3)
        if fc not in (3, 4):
            raise SystemExit('%s (%s): "fc" must be 3 (holding) or 4 (input), got %r' % (label, entry['name'], fc))
        if not 0 <= start <= MAX_REGISTERS - count:
            raise SystemExit('%s (%s): register %d out of range' % (label, entry['name'], start))
        ttl = entry.get('ttl')
        if ttl is not None:
            try:
                ttl = float(ttl)
            except (TypeError, ValueError):
                raise SystemExit('%s (%s): "ttl" must be seconds, got %r' % (label, entry['name'], ttl))
            if ttl < 0:
                raise SystemExit('%s (%s): "ttl" must be >= 0' % (label, entry['name']))
            ttls[(fc, start, count)] = ttl
        ranges.append((fc, start, count))
        names[(fc, start, count)] = str(entry['name'])
    return ranges, names, ttls


def load_selection(path, names, ttls=None):
    """A selection file: {"registers": ["pv-power", ...]} — profile NAMES to
    fetch. Returns (ranges, names, ttls) filtered to the selected entries."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read selection file %s: %s' % (path, e))
    wanted = data.get('registers') if isinstance(data, dict) else data
    if not isinstance(wanted, list) or not all(isinstance(w, str) for w in wanted):
        raise SystemExit('selection file %s must be a "registers" list of names' % path)
    by_name = {v: k for k, v in names.items()}
    missing = [w for w in wanted if w not in by_name]
    if missing:
        raise SystemExit('selection file %s: not in the device profile: %s' % (path, ', '.join(missing)))
    ranges = [by_name[w] for w in wanted]
    return ranges, {by_name[w]: w for w in wanted}, {by_name[w]: ttls[by_name[w]] for w in wanted
                                                     if ttls and by_name[w] in ttls}


def parse_selection(text):
    """''/'all' -> '' (every profile entry); 'none' -> 'none' (cache nothing,
    every read forwards); else the selection file path."""
    t = (text or '').strip()
    if t.lower() in ('', 'all', '-'):
        return ''
    if t.lower() == 'none':
        return 'none'
    return t


def validate_config(cfg):
    """Fail fast on nonsensical settings.

    Raises SystemExit with a clean message; at startup that aborts with a
    proper error, on SIGHUP the reload watcher keeps the previous settings.
    """
    def fail(key, rule):
        raise SystemExit('invalid %s = %r: %s' % (key, cfg.get(key), rule))

    if not 1 <= cfg['port'] <= 65535:
        fail('port', 'must be 1..65535')
    if not UNIT_ID_RANGE[0] <= cfg['unit'] <= UNIT_ID_RANGE[1]:
        fail('unit', 'must be %d..%d (Modbus unit id)' % UNIT_ID_RANGE)
    if cfg['timeout'] <= 0:
        fail('timeout', 'must be > 0')
    if cfg['interval'] <= 0:
        fail('interval', 'must be > 0')
    if cfg['read_delay'] < 0:
        fail('read_delay', 'must be >= 0')
    if cfg['merge_gap'] < 0:
        fail('merge_gap', 'must be >= 0')
    if cfg['cache_ttl'] < 0:
        fail('cache_ttl', 'must be >= 0')
    if cfg['max_clients'] < 0:
        fail('max_clients', 'must be >= 0')
    if cfg['client_timeout'] < 0:
        fail('client_timeout', 'must be >= 0')
    if cfg['level'] not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
        fail('log-level', 'must be DEBUG, INFO, WARNING or ERROR')
    if cfg['audit_max_mb'] < 0:
        fail('audit_max_mb', 'must be >= 0 (0 = no size rotation)')
    if cfg['audit_files'] < 1:
        fail('audit_files', 'must be >= 1')
    if cfg['requests_audit_s'] < 0:
        fail('requests_audit', 'must be >= 0 (0 = off)')
    if cfg['dump_interval'] < 0:
        fail('dump_interval', 'must be >= 0 (0 = off)')
    if cfg['dump_interval'] and not cfg['dump_path']:
        fail('dump_interval', 'needs dump_path set (there is nothing to dump into)')
    if cfg['control_token'] and cfg['control_token_file']:
        fail('control-token', 'set --control-token or --control-token-file, not both')
    parse_listen(cfg['listen'])
    if not cfg['host']:
        fail('host', 'must not be empty')


def load_config(path):
    cfg = configparser.ConfigParser()
    try:
        if os.path.isfile(path):
            cfg.read(path)
    except (configparser.Error, OSError) as e:
        logger.error('cannot read config file %s: %s (using defaults)', path, e)
    if not cfg.has_section('cache'):
        cfg.add_section('cache')
    return cfg['cache']


def resolve_config(args, script_dir=None):
    """Effective settings: CLI flags > MODBUS_CACHE_* env > [cache] ini > defaults."""
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

    def resolve_bool(cli_value, env_name, cfg_key, default):
        def parse_bool(raw):
            s = str(raw).strip().lower()
            if s in ('1', 'true', 'yes', 'on'):
                return True
            if s in ('0', 'false', 'no', 'off', ''):
                return False
            raise ValueError('expected true/false, got %r' % raw)
        return resolve(cli_value, env_name, cfg_key, default, parse_bool)

    interval = resolve(args.interval, 'MODBUS_CACHE_INTERVAL', 'interval', DEFAULTS['interval_s'], float)
    cfg = {
        'host': resolve(args.host, 'MODBUS_CACHE_HOST', 'host', DEFAULTS['host'], str),
        'port': resolve(args.port, 'MODBUS_CACHE_PORT', 'port', DEFAULTS['modbus_port'], int),
        'unit': resolve(args.unit, 'MODBUS_CACHE_UNIT', 'unit', DEFAULTS['unit'], int),
        'timeout': resolve(args.timeout, 'MODBUS_CACHE_TIMEOUT', 'timeout', DEFAULTS['timeout_s'], float),
        'listen': resolve(args.listen, 'MODBUS_CACHE_LISTEN', 'listen', DEFAULTS['listen'], str),
        'interval': interval,
        'read_delay': resolve(args.read_delay, 'MODBUS_CACHE_READ_DELAY', 'read_delay', DEFAULTS['read_delay_s'], float),
        'merge_gap': resolve(args.merge_gap, 'MODBUS_CACHE_MERGE_GAP', 'merge_gap', DEFAULTS['merge_gap'], int),
        'allow_write': resolve_bool(args.allow_write or None, 'MODBUS_CACHE_ALLOW_WRITE', 'allow_write', False),
        'write_registers': parse_write_registers(
            resolve(getattr(args, 'write_registers', None), 'MODBUS_CACHE_WRITE_REGISTERS',
                    'write_registers', 'any', str)),
        'profile': resolve_profile_file(resolve(getattr(args, 'profile', None), 'MODBUS_CACHE_PROFILE',
                                                'profile', default_profile_path(), str)),
        'selection': parse_selection(resolve(getattr(args, 'selection', None), 'MODBUS_CACHE_SELECTION',
                                            'selection', '', str)),
        'cache_ttl': resolve(args.cache_ttl, 'MODBUS_CACHE_TTL', 'cache_ttl',
                             DEFAULTS['cache_ttl_factor'] * interval, float),
        'local_time': resolve_bool(args.local_time, 'MODBUS_CACHE_LOCAL_TIME', 'local_time', False),
        'log_access': resolve_bool(args.log_access, 'MODBUS_CACHE_LOG_ACCESS', 'log_access', False),
        'max_clients': resolve(args.max_clients, 'MODBUS_CACHE_MAX_CLIENTS', 'max_clients', DEFAULTS['max_clients'], int),
        'client_timeout': resolve(args.client_timeout, 'MODBUS_CACHE_CLIENT_TIMEOUT', 'client_timeout',
                                  DEFAULTS['client_timeout_s'], float),
        'connect_acl': parse_acl(resolve(args.connect_acl, 'MODBUS_CACHE_CONNECT_ACL', 'connect_acl', 'any', str),
                                 'connect-acl'),
        'write_acl': parse_acl(resolve(args.write_acl, 'MODBUS_CACHE_WRITE_ACL', 'write_acl', 'any', str),
                               'write-acl'),
        'level': resolve(args.log_level, 'MODBUS_CACHE_LOG_LEVEL', 'log_level', DEFAULTS['log_level'], str).upper(),
        'control_port': resolve(getattr(args, 'control_port', None), 'MODBUS_CACHE_CTL', 'control_port', '', str)
                        or (os.environ.get('CACHE_CTL', '').strip() or ''),
        'control_token': resolve(getattr(args, 'control_token', None), 'MODBUS_CACHE_CONTROL_TOKEN',
                                 'control_token', '', str),
        'control_token_file': resolve(getattr(args, 'control_token_file', None), 'MODBUS_CACHE_CONTROL_TOKEN_FILE',
                                      'control_token_file', '', str),
        'audit_log': resolve(getattr(args, 'audit_log', None), 'MODBUS_CACHE_AUDIT_LOG', 'audit_log', '', str),
        'audit_max_mb': resolve(getattr(args, 'audit_max_mb', None), 'MODBUS_CACHE_AUDIT_MAX_MB',
                                'audit_max_mb', DEFAULTS['audit_max_mb'], float),
        'audit_daily': resolve_bool(getattr(args, 'audit_daily', False), 'MODBUS_CACHE_AUDIT_DAILY',
                                    'audit_daily', False),
        'audit_files': resolve(getattr(args, 'audit_files', None), 'MODBUS_CACHE_AUDIT_FILES',
                               'audit_files', DEFAULTS['audit_files'], int),
        'no_audit_log': resolve_bool(getattr(args, 'no_audit_log', False), 'MODBUS_CACHE_NO_AUDIT_LOG',
                                     'no_audit_log', False),
        'requests_audit_s': resolve(getattr(args, 'requests_audit', None), 'MODBUS_CACHE_REQUESTS_AUDIT',
                                    'requests_audit_s', DEFAULTS['requests_audit_s'], float),
        'dump_path': resolve(getattr(args, 'dump_path', None), 'MODBUS_CACHE_DUMP_PATH',
                             'dump_path', '', str),
        'dump_interval': resolve(getattr(args, 'dump_interval', None), 'MODBUS_CACHE_DUMP_INTERVAL',
                                 'dump_interval', 0.0, float),
        'restore_on_start': resolve_bool(getattr(args, 'restore_on_start', False) or None,
                                         'MODBUS_CACHE_RESTORE_ON_START', 'restore_on_start', False),
        'control_trust_uids': parse_trust_uids(resolve(getattr(args, 'control_trust_uids', None),
                                                       'MODBUS_CACHE_CONTROL_TRUST_UIDS',
                                                       'control_trust_uids', '', str)),
        'control_socket_group': resolve_bool(getattr(args, 'control_socket_group', False),
                                             'MODBUS_CACHE_CONTROL_SOCKET_GROUP', 'control_socket_group', False),
    }
    validate_config(cfg)
    return cfg
