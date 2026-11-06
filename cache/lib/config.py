#!/usr/bin/env python3
"""Configuration for modbus-cache: the set-grammar config script, the env
layer and the CLI flags, plus the register map (stdlib only). The config
file speaks the control grammar (common/options.py): every line a
`set <name> <value>`, every comment a `#` comment — the ini format is gone
(the breaking wave in docs/TODO.md)."""
import ipaddress
import json
import logging
import os

from common.options import parse_config_script
from .options import OPTIONS
from common.config import acl_summary, acl_text, default_profile_path, parse_acl, parse_listen, parse_upstream, \
    resolve_profile_file
from common.cred import parse_trust_uids
from .statics import DEFAULTS, DEFAULT_LISTEN_PORT, LOG_LEVELS, MAX_COUNT, MAX_REGISTERS, \
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
    """--control-port flag > CTL environment > default socket."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('CTL')
    if env and env.strip():
        return env.strip()
    return '/tmp/modbus-cache-%d.socket' % listen_port


def parse_write_registers(text, label='write-registers'):
    """'any'/'*'/empty/None -> None (any register writable); 'none' -> ()
    (no register writable); 'START:COUNT,...' (comma-separated) -> tuple of
    (start, count) ranges. A write is allowed only when every register it
    touches lands inside one of the ranges."""
    if text is None:
        return None
    t = str(text).strip()
    if t in ('', 'any', '*'):
        return None
    if t.lower() == 'none':
        return ()
    ranges = []
    for part in t.split(','):
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
    if cfg['max_conn_per_ip'] < 0:
        fail('max_conn_per_ip', 'must be >= 0 (0 = no per-IP limit)')
    if cfg['metrics_max_clients'] < 0:
        fail('metrics_max_clients', 'must be >= 0 (0 = unlimited)')
    if cfg['metrics_client_timeout'] < 0:
        fail('metrics_client_timeout', 'must be >= 0 (0 = the built-in 5 s cap)')
    if cfg['metrics_max_conn_per_ip'] < 0:
        fail('metrics_max_conn_per_ip', 'must be >= 0 (0 = no per-IP limit)')
    parse_listen(cfg['metrics_listen'])
    if cfg['level'] not in LOG_LEVELS:
        fail('log-level', 'must be one of %s' % ', '.join(LOG_LEVELS))
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
    if cfg['control_ops_token'] and cfg['control_ops_token_file']:
        fail('control-ops-token', 'set --control-ops-token or --control-ops-token-file, not both')
    if cfg['control_ops_token']:
        if not cfg['control_token']:
            fail('control-ops-token', 'the read-only ops token supplements the admin token — '
                 'set --control-token/--control-token-file too')
        if cfg['control_ops_token'] == cfg['control_token']:
            fail('control-ops-token', 'the ops token must differ from the admin token '
                 '(the same secret would hand every holder the role the server picks first)')
    parse_listen(cfg['listen'])


def load_config(path):
    """The config script: every line a `set <name> <value>` (or the bare
    `<name> <value>` shorthand), `#` comments stay comments — a config file
    pipes through a ctl client unchanged. Returns {key: raw-string value}
    with the dash names underscore-normalized (the resolver's keys). A
    missing file is no config at all; an unreadable one or a legacy ini
    file fails fast with the pointer to the new grammar."""
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


def resolve_config(args, script_dir=None):
    """Effective settings: CLI flags > env > config script > defaults."""
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

    interval = resolve(args.interval, 'INTERVAL', 'interval', DEFAULTS['interval_s'], float)
    upstream = resolve(getattr(args, 'upstream', None), 'UPSTREAM', 'upstream',
                       DEFAULTS['upstream'], str)
    host, port = parse_upstream(upstream or DEFAULTS['upstream'])
    cfg = {
        'upstream': '%s:%d' % (host, port),
        'host': host,
        'port': port,
        'unit': resolve(args.unit, 'UNIT', 'unit', DEFAULTS['unit'], int),
        'timeout': resolve(args.timeout, 'TIMEOUT', 'timeout', DEFAULTS['timeout_s'], float),
        'listen': resolve(args.listen, 'LISTEN', 'listen', DEFAULTS['listen'], str),
        'interval': interval,
        'read_delay': resolve(args.read_delay, 'READ_DELAY', 'read_delay', DEFAULTS['read_delay_s'], float),
        'merge_gap': resolve(args.merge_gap, 'MERGE_GAP', 'merge_gap', DEFAULTS['merge_gap'], int),
        'allow_write': resolve_bool(args.allow_write or None, 'ALLOW_WRITE', 'allow_write', False),
        'write_registers': parse_write_registers(
            resolve(getattr(args, 'write_registers', None), 'WRITE_REGISTERS',
                    'write_registers', 'none', str)),
        'profile': resolve_profile_file(resolve(getattr(args, 'profile', None), 'PROFILE',
                                                'profile', default_profile_path(), str)),
        'selection': parse_selection(resolve(getattr(args, 'selection', None), 'SELECTION',
                                            'selection', '', str)),
        'cache_ttl': resolve(args.cache_ttl, 'TTL', 'cache_ttl',
                             DEFAULTS['cache_ttl_factor'] * interval, float),
        'local_time': resolve_bool(args.local_time, 'LOCAL_TIME', 'local_time', False),
        'log_access': resolve_bool(args.log_access, 'LOG_ACCESS', 'log_access', False),
        'max_clients': resolve(args.max_clients, 'MAX_CLIENTS', 'max_clients', DEFAULTS['max_clients'], int),
        'client_timeout': resolve(args.client_timeout, 'CLIENT_TIMEOUT', 'client_timeout',
                                  DEFAULTS['client_timeout_s'], float),
        'max_conn_per_ip': resolve(getattr(args, 'max_conn_per_ip', None), 'MAX_CONN_PER_IP',
                                   'max_conn_per_ip', DEFAULTS['max_conn_per_ip'], int),
        'metrics_max_clients': resolve(getattr(args, 'metrics_max_clients', None), 'METRICS_MAX_CLIENTS',
                                       'metrics_max_clients', DEFAULTS['metrics_max_clients'], int),
        'metrics_client_timeout': resolve(getattr(args, 'metrics_client_timeout', None),
                                          'METRICS_CLIENT_TIMEOUT', 'metrics_client_timeout',
                                          DEFAULTS['metrics_client_timeout_s'], float),
        'metrics_max_conn_per_ip': resolve(getattr(args, 'metrics_max_conn_per_ip', None),
                                           'METRICS_MAX_CONN_PER_IP', 'metrics_max_conn_per_ip',
                                           DEFAULTS['metrics_max_conn_per_ip'], int),
        'metrics_server': resolve_bool(getattr(args, 'metrics_server', False) or None,
                                       'METRICS_SERVER', 'metrics_server', False),
        'metrics_listen': resolve(getattr(args, 'metrics_listen', None), 'METRICS_LISTEN',
                                  'metrics_listen', DEFAULTS['metrics_listen'], str),
        'connect_acl': parse_acl(resolve(args.connect_acl, 'CONNECT_ACL', 'connect_acl', 'any', str),
                                 'connect-acl'),
        'write_acl': parse_acl(resolve(args.write_acl, 'WRITE_ACL', 'write_acl', 'none', str),
                               'write-acl'),
        'level': resolve(args.log_level, 'LOG_LEVEL', 'log_level', DEFAULTS['log_level'], str).upper(),
        'control_port': resolve(getattr(args, 'control_port', None), 'CTL', 'control_port', '', str),
        'control_token': resolve(getattr(args, 'control_token', None), 'CONTROL_TOKEN',
                                 'control_token', '', str),
        'control_token_file': resolve(getattr(args, 'control_token_file', None), 'CONTROL_TOKEN_FILE',
                                      'control_token_file', '', str),
        'control_ops_token': resolve(getattr(args, 'control_ops_token', None), 'CONTROL_OPS_TOKEN',
                                     'control_ops_token', '', str),
        'control_ops_token_file': resolve(getattr(args, 'control_ops_token_file', None),
                                          'CONTROL_OPS_TOKEN_FILE', 'control_ops_token_file', '', str),
        'control_ops_verbs': resolve(getattr(args, 'control_ops_verbs', None), 'CONTROL_OPS_VERBS',
                                     'control_ops_verbs', 'show,clear', str),
        'audit_log': resolve(getattr(args, 'audit_log', None), 'AUDIT_LOG', 'audit_log', '', str),
        'audit_max_mb': resolve(getattr(args, 'audit_max_mb', None), 'AUDIT_MAX_MB',
                                'audit_max_mb', DEFAULTS['audit_max_mb'], float),
        'audit_daily': resolve_bool(getattr(args, 'audit_daily', False), 'AUDIT_DAILY',
                                    'audit_daily', False),
        'audit_files': resolve(getattr(args, 'audit_files', None), 'AUDIT_FILES',
                               'audit_files', DEFAULTS['audit_files'], int),
        'no_audit_log': resolve_bool(getattr(args, 'no_audit_log', False), 'NO_AUDIT_LOG',
                                     'no_audit_log', False),
        'requests_audit_s': resolve(getattr(args, 'requests_audit', None), 'REQUESTS_AUDIT',
                                    'requests_audit_s', DEFAULTS['requests_audit_s'], float),
        'dump_path': resolve(getattr(args, 'dump_path', None), 'DUMP_PATH',
                             'dump_path', '', str),
        'dump_interval': resolve(getattr(args, 'dump_interval', None), 'DUMP_INTERVAL',
                                 'dump_interval', 0.0, float),
        'dump_with_cache': resolve_bool(getattr(args, 'dump_with_cache', False) or None,
                                        'DUMP_WITH_CACHE', 'dump_with_cache', False),
        'restore_on_start': resolve_bool(getattr(args, 'restore_on_start', False) or None,
                                         'RESTORE_ON_START', 'restore_on_start', False),
        'control_trust_uids': parse_trust_uids(resolve(getattr(args, 'control_trust_uids', None),
                                                       'CONTROL_TRUST_UIDS',
                                                       'control_trust_uids', '', str)),
        'control_socket_group': resolve_bool(getattr(args, 'control_socket_group', False),
                                             'CONTROL_SOCKET_GROUP', 'control_socket_group', False),
    }
    validate_config(cfg)
    return cfg
