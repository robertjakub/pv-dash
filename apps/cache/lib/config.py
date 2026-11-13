#!/usr/bin/env python3
"""Configuration for modbus-cache: the set-grammar config script, the env
layer and the CLI flags, plus the register map (stdlib only). The config
file speaks the control grammar (common/settings/options.py): every line a
`set <name> <value>`, every comment a `#` comment — the ini format is gone
(the breaking wave in docs/TODO.md)."""
import json
import logging

from .options import OPTIONS
from common.settings.config import (IPGate, _GATE_TYPES, _write_gate_object,
                           acl_admits, acl_file_warn, acl_gate_summary, acl_table,
                           acl_value_text, check_auth_key, check_token_chars, load_config_script,
                           load_write_gate_file, parse_acl, parse_acl_value, parse_auth_type, parse_listen,
                           parse_secret, parse_upstream, resolve_profile_file, Resolver)
from common.wire.cred import parse_trust_uids
from common.runtime.audit import AUDIT_FILES_MAX, AUDIT_FILES_MIN, AUDIT_MAX_MB_MAX, AUDIT_MAX_MB_MIN
from .statics import DEFAULTS, DEFAULT_LISTEN_PORT, LOG_LEVELS, MAX_COUNT, MAX_REGISTERS, \
    REGISTERS_TYPE, UNIT_ID_RANGE

logger = logging.getLogger('modbus-cache')

# the control socket's name: the daemon's template (common.config's parsers
# take it as the argument), the clients' default (the template spelled with
# the default serving port)
CONTROL_SOCKET_TEMPLATE = '/tmp/modbus-cache-%d.socket'
DEFAULT_CONTROL_SOCKET = CONTROL_SOCKET_TEMPLATE % DEFAULT_LISTEN_PORT

# the registry rows by knob name — the resolver's row-driven validation
# (row_value: the words, the conv, the choices, the min/max bounds)
OPT = {o.name: o for o in OPTIONS}


def off_float(text):
    """The off-worded floats (cache-ttl, audit-requests): the documented
    off word rides as 0 — the wire branches' own mapping. A plain number
    parses as before; the row's min/max bounds stay validate_config's."""
    return 0.0 if str(text).strip().lower() in ('off', 'none') else float(text)


def parse_write_registers(text, label='write-registers'):
    """'any'/'*'/empty/None -> None (any register writable); 'none' -> ()
    (no register writable); 'profile' -> 'profile' (the device profile's
    write acl — the proxy resolves it against the configured profile);
    'file:<path>' -> 'file:<path>' (the standalone acl file — the same
    gate object a profile carries under "acl"/"write"; the proxy reads and
    compiles it); 'START:COUNT,...' (comma-separated) -> tuple of (start,
    count) ranges. A write is allowed only when every register it touches
    lands inside one of the ranges."""
    if text is None:
        return None
    t = str(text).strip()
    if t in ('', 'any', '*'):
        return None
    if t.lower() == 'none':
        return ()
    if t.lower() == 'profile':
        return 'profile'
    if t.startswith('file:'):
        return t
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


def _acl_range(text, where):
    """One acl range "START:COUNT" -> (start, count) — the profile bounds
    (the register space; no per-frame cap, the gate is coverage)."""
    try:
        start, count = (int(x) for x in str(text).split(':'))
    except ValueError:
        raise SystemExit('%s: %r must be START:COUNT' % (where, text))
    if start < 0 or count < 1 or start + count > MAX_REGISTERS:
        raise SystemExit('%s: range %d:%d out of bounds (0..%d)'
                         % (where, start, count, MAX_REGISTERS - 1))
    return start, count


def _acl_matcher(v, where):
    """A rule matcher: 'any' (all registers) / 'START:COUNT' / a list of
    those -> ('any' | 'ranges', ranges)."""
    if isinstance(v, str):
        t = v.strip().lower()
        if t == 'any':
            return 'any', None
        return 'ranges', [_acl_range(t, where)]
    if isinstance(v, list):
        ranges = []
        for x in v:
            t = str(x).strip().lower()
            if t == 'any':
                raise SystemExit('%s: the word %r stands alone, not in a list' % (where, t))
            ranges.append(_acl_range(t, where))
        return 'ranges', ranges
    raise SystemExit('%s must be a range ("START:COUNT"), a list of ranges, or "any"' % where)


def _ranges_from_bits(bits):
    """The set bytes -> disjoint (start, count) ranges (touching bits merge)."""
    out = []
    i, n = 0, len(bits)
    while i < n:
        if bits[i]:
            j = i
            while j < n and bits[j]:
                j += 1
            out.append((i, j - i))
            i = j
        else:
            i += 1
    return out


def load_profile_write_gate(path, label=None):
    """The device profile's write acl, parsed but not compiled: the
    optional top-level "acl" object keyed by access kind — "write" is the
    one the cache speaks; its gate is the acl gate object (see
    _write_gate_object). A profile without acl/write refuses: the caller
    asked for the profile's gating, silence would look like a gate that is
    not there."""
    label = label or 'device profile %s' % path
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read device profile %s: %s' % (path, e))
    acl = data.get('acl') if isinstance(data, dict) else None
    gate = acl.get('write') if isinstance(acl, dict) else None
    if not isinstance(gate, dict):
        raise SystemExit('%s carries no "acl"/"write" gate for write-registers profile '
                         '(add "acl": {"write": {"rules": '
                         '[{"type": "allow", "range": "START:COUNT"}]}})' % label)
    return _write_gate_object(gate, '%s acl/write' % label)


def compile_write_acl(rules):
    """The parsed rule chain (load_profile_write_gate's rules) -> the
    write-registers shapes: None (any register writable), () (none), else
    the disjoint (start, count) ranges. Compiles to a bitmap — allow sets
    1, deny clears to 0, so the last rule touching a register decides and
    the untouched bits stay refused (the default deny any) — the chain
    never needs a second check at write time. Register kind only (range
    rules) — a prefix chain is the IP kind's, its reader compiles its
    own."""
    bits = bytearray(MAX_REGISTERS)   # 0 = refused (the default), 1 = writable
    for verb, matcher, _desc, where in rules:
        kind, ranges = _acl_matcher(matcher, where)
        byte = b'\x01' if verb == 'allow' else b'\x00'   # deny resets to refused
        if kind == 'any':
            bits[:] = byte * MAX_REGISTERS
        else:
            for s, c in ranges:
                bits[s:s + c] = byte * c
    if not any(bits):
        return ()
    if all(bits):
        return None
    return tuple(_ranges_from_bits(bits))


def render_write_acl(desc, rules):
    """The parsed gate as the write/registers/table show report's lines:
    the gate-level desc first as the '% ' line, then one
    '<verb> <range>[ # desc]' line per range — a list matcher fans out
    (the rule's desc repeats), the bare word 'any' stands alone, and the
    lines that carry a desc ALIGN: the '<verb> <range>' prefixes pad to
    one width so the '# <desc>' comments start at one column. A chain
    with no deciding rule renders as the default it is: 'deny any'."""
    lines = ['%% %s' % desc] if desc else []
    rows = []   # ('<verb> <range>', desc-or-None) in chain order
    for verb, matcher, rdesc, _where in rules:
        if isinstance(matcher, list):
            entries = [(str(x).strip().lower(), rdesc) for x in matcher]
        else:
            entries = [(str(matcher).strip().lower(), rdesc)]
        for rng, d in entries:
            rows.append(('%s %s' % (verb, rng), (d or '').strip() or None))
    if not rows:
        rows.append(('deny any', None))
    width = max((len(prefix) for prefix, d in rows if d), default=0)
    for prefix, d in rows:
        lines.append(('%s # %s' % (prefix.ljust(width), d)) if d else prefix.rstrip())
    return lines


def load_registers_file(path):
    """Device profile: {"registers": [{"name", "register", "type", "fc", ...}]} —
    the shared schema from the profiles/ subproject. Returns the full
    (ranges, names) map; which entries are actually fetched is the
    selection file's job (load_selection). "type" gives the word width
    (i16/u16 = 1 register word, i32/u32 and the swap/float variants = 2,
    bit = 1 address on the bit spaces). "fc" is the function code the
    device answers for the entry — 1 (coils) or 2 (discrete inputs) for
    bit entries (1 the default), 3 (holding registers, the default) or 4
    (input registers) for the word types; the four address spaces are
    cached separately."""
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
        count = REGISTERS_TYPE.get(typ)
        if count is None:
            raise SystemExit('%s (%s): unknown "type" %r (i16/u16/i32/u32/i32swap/u32swap/f32/f32swap/bit)'
                             % (label, entry['name'], typ))
        default_fc = 1 if typ == 'bit' else 3
        fc = entry.get('fc', default_fc)
        legal = (1, 2) if typ == 'bit' else (3, 4)
        try:
            fc = int(fc)
        except (TypeError, ValueError):
            raise SystemExit('%s (%s): bad "fc" %r' % (label, entry['name'], entry.get('fc')))
        if fc not in legal:
            raise SystemExit('%s (%s): "fc" must be %s, got %d'
                             % (label, entry['name'],
                                '1 (coils) or 2 (discrete inputs)' if typ == 'bit'
                                else '3 (holding) or 4 (input)', fc))
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
        shown = cfg.get(key, cfg.get(key.replace('-', '_')))   # the label keeps the knob's dash spelling
        raise SystemExit('invalid %s = %r: %s' % (key, shown, rule))

    if not 1 <= cfg['port'] <= 65535:
        fail('port', 'must be 1..65535')
    if not UNIT_ID_RANGE[0] <= cfg['modbus_unit'] <= UNIT_ID_RANGE[1]:
        fail('modbus-unit', 'must be %d..%d (Modbus unit id)' % UNIT_ID_RANGE)
    if cfg['modbus_timeout'] <= 0:
        fail('modbus-timeout', 'must be > 0')
    if cfg['modbus_interval'] <= 0:
        fail('modbus-interval', 'must be > 0')
    if cfg['modbus_read_delay'] < 0:
        fail('modbus-read-delay', 'must be >= 0')
    if cfg['modbus_merge_gap'] < 0:
        fail('modbus-merge-gap', 'must be >= 0')
    if cfg['cache_ttl'] < 0:
        fail('cache_ttl', 'must be >= 0')
    if cfg['cache_ttl'] > OPT['cache-ttl'].max:
        fail('cache_ttl', 'must be <= %g' % OPT['cache-ttl'].max)
    if cfg['requests_audit_s'] > OPT['audit-requests'].max:
        fail('audit-requests', 'must be <= %g' % OPT['audit-requests'].max)
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
    if cfg['auth'] and not cfg['modbus_auth_key']:
        fail('auth', "the suite auth needs a key: set --modbus-auth-key/$MODBUS_AUTH_KEY too (min 16 characters)")
    if cfg['modbus_auth_upstream'] and not cfg['modbus_auth_upstream_key']:
        fail('modbus_auth_upstream', "the %s auth needs a key: set --modbus-auth-upstream-key/$MODBUS_UPSTREAM_AUTH_KEY too%s"
                              % (cfg['modbus_auth_upstream'],
                                 ' (min 16 characters)' if cfg['modbus_auth_upstream'] == 'suite' else ''))
    if cfg['level'] not in LOG_LEVELS:
        fail('log-level', 'must be one of %s' % ', '.join(LOG_LEVELS))
    if not (AUDIT_MAX_MB_MIN <= cfg['audit_max_mb'] <= AUDIT_MAX_MB_MAX):
        fail('audit_max_mb', 'must be %d..%d (0 = no size rotation)'
             % (AUDIT_MAX_MB_MIN, AUDIT_MAX_MB_MAX))
    if not (AUDIT_FILES_MIN <= cfg['audit_files'] <= AUDIT_FILES_MAX):
        fail('audit_files', 'must be %d..%d' % (AUDIT_FILES_MIN, AUDIT_FILES_MAX))
    if cfg['requests_audit_s'] < 0:
        fail('audit-requests', 'must be >= 0 (0 = off)')
    if cfg['dump_interval'] < 0:
        fail('dump_interval', 'must be >= 0 (0 = off)')
    if cfg['dump_interval'] and not cfg['dump_path']:
        fail('dump_interval', 'needs dump_path set (there is nothing to dump into)')
    if cfg['control_ops_token']:
        if not cfg['control_token']:
            fail('control-ops-token', 'the read-only ops token supplements the admin token — '
                 'set --control-token too')
        if cfg['control_ops_token'] == cfg['control_token']:
            fail('control-ops-token', 'the ops token must differ from the admin token '
                 '(the same secret would hand every holder the role the server picks first)')
    check_token_chars(cfg['control_token'], 'control-token')
    check_token_chars(cfg['control_ops_token'], 'control-ops-token')
    check_token_chars(cfg['metrics_token'], 'metrics-token')
    parse_listen(cfg['listen'])


def load_config(path):
    """The config script: every line a `set <name> <value>` (or the bare
    `<name> <value>` shorthand), `#` comments stay comments — a config file
    pipes through a ctl client unchanged. Returns {key: raw-string value}
    with the dash names underscore-normalized (the resolver's keys). A
    missing file is no config at all; an unreadable one or a legacy ini
    file fails fast with the pointer to the new grammar."""
    return load_config_script(path, OPTIONS)


def resolve_config(args, script_dir=None):
    """Effective settings: CLI flags > env > config script > defaults."""
    cfg = load_config(args.config)
    r = Resolver(cfg, logger)
    resolve = r.resolve
    resolve_bool = r.resolve_bool

    interval = resolve(args.modbus_interval, 'MODBUS_INTERVAL', 'modbus_interval', DEFAULTS['modbus_interval'],
                       float, row=OPT['modbus-interval'])
    upstream = resolve(getattr(args, 'upstream', None), 'UPSTREAM', 'upstream',
                       DEFAULTS['upstream'], str)
    host, port = parse_upstream(upstream or DEFAULTS['upstream'])
    upstream_auth = parse_auth_type(
        resolve(getattr(args, 'modbus_auth_upstream', None), 'MODBUS_UPSTREAM_AUTH', 'modbus_auth_upstream',
                DEFAULTS['modbus_auth_upstream'], str),
        'modbus-auth-upstream', schemes=('suite', 'waveshare'))
    cfg = {
        'upstream': '%s:%d' % (host, port),
        'host': host,
        'port': port,
        'modbus_unit': resolve(args.modbus_unit, 'MODBUS_UNIT', 'modbus_unit',
                               DEFAULTS['modbus_unit'], int, row=OPT['modbus-unit']),
        'modbus_timeout': resolve(args.modbus_timeout, 'MODBUS_TIMEOUT', 'modbus_timeout',
                                  DEFAULTS['modbus_timeout'], float, row=OPT['modbus-timeout']),
        'auth': parse_auth_type(resolve(args.modbus_auth, 'MODBUS_AUTH', 'modbus-auth', DEFAULTS['modbus_auth'], str), 'modbus-auth'),
        'modbus_auth_key': check_auth_key(
            parse_secret((resolve(getattr(args, 'modbus_auth_key', None), 'MODBUS_AUTH_KEY', 'modbus_auth_key', '', str)
                          or '').strip() or None, 'modbus-auth-key'), 'modbus-auth-key'),
        'modbus_auth_upstream': upstream_auth,
        'modbus_auth_upstream_key': check_auth_key(
            parse_secret((resolve(getattr(args, 'modbus_auth_upstream_key', None), 'MODBUS_UPSTREAM_AUTH_KEY',
                                  'modbus_auth_upstream_key', '', str) or '').strip() or None, 'modbus-auth-upstream-key'),
            'modbus-auth-upstream-key', kind=upstream_auth),
        'listen': resolve(args.listen, 'LISTEN', 'listen', DEFAULTS['listen'], str),
        'modbus_interval': interval,
        'modbus_read_delay': resolve(args.modbus_read_delay, 'MODBUS_READ_DELAY', 'modbus_read_delay',
                                     DEFAULTS['modbus_read_delay'], float, row=OPT['modbus-read-delay']),
        'modbus_merge_gap': resolve(args.modbus_merge_gap, 'MODBUS_MERGE_GAP', 'modbus_merge_gap',
                                    DEFAULTS['modbus_merge_gap'], int, row=OPT['modbus-merge-gap']),
        'allow_write': resolve_bool(args.allow_write or None, 'ALLOW_WRITE', 'allow_write', DEFAULTS['allow_write']),
        'write_registers': parse_write_registers(
            resolve(getattr(args, 'write_registers', None), 'WRITE_REGISTERS',
                    'write_registers', DEFAULTS['write_registers'], str)),
        'modbus_profile': resolve_profile_file(resolve(getattr(args, 'modbus_profile', None), 'MODBUS_PROFILE',
                                                       'modbus_profile', DEFAULTS['modbus_profile'], str)),
        'selection': parse_selection(resolve(getattr(args, 'selection', None), 'SELECTION',
                                            'selection', DEFAULTS['selection'], str)),
        'cache_ttl': resolve(args.cache_ttl, 'TTL', 'cache_ttl',
                             DEFAULTS['cache_ttl'], off_float),
        'local_time': resolve_bool(args.local_time or None, 'LOCAL_TIME', 'local_time', DEFAULTS['local_time']),
        'log_access': resolve_bool(args.log_access or None, 'LOG_ACCESS', 'log_access', DEFAULTS['log_access']),
        'max_clients': resolve(args.max_clients, 'MAX_CLIENTS', 'max_clients', DEFAULTS['max_clients'], int,
                               row=OPT['max-clients']),
        'client_timeout': resolve(args.client_timeout, 'CLIENT_TIMEOUT', 'client_timeout',
                                  DEFAULTS['client_timeout'], float, row=OPT['client-timeout']),
        'max_conn_per_ip': resolve(getattr(args, 'max_conn_per_ip', None), 'MAX_CONN_PER_IP',
                                   'max_conn_per_ip', DEFAULTS['max_conn_per_ip'], int,
                                   row=OPT['max-conn-per-ip']),
        'metrics_max_clients': resolve(getattr(args, 'metrics_max_clients', None), 'METRICS_MAX_CLIENTS',
                                       'metrics_max_clients', DEFAULTS['metrics_max_clients'], int,
                                       row=OPT['metrics-max-clients']),
        'metrics_client_timeout': resolve(getattr(args, 'metrics_client_timeout', None),
                                          'METRICS_CLIENT_TIMEOUT', 'metrics_client_timeout',
                                          DEFAULTS['metrics_client_timeout'], float,
                                          row=OPT['metrics-client-timeout']),
        'metrics_max_conn_per_ip': resolve(getattr(args, 'metrics_max_conn_per_ip', None),
                                           'METRICS_MAX_CONN_PER_IP', 'metrics_max_conn_per_ip',
                                           DEFAULTS['metrics_max_conn_per_ip'], int,
                                           row=OPT['metrics-max-conn-per-ip']),
        'metrics_server': resolve_bool(getattr(args, 'metrics_server', False) or None,
                                       'METRICS_SERVER', 'metrics_server', DEFAULTS['metrics_server']),
        'metrics_listen': resolve(getattr(args, 'metrics_listen', None), 'METRICS_LISTEN',
                                  'metrics_listen', DEFAULTS['metrics_listen'], str),
        'metrics_token': parse_secret((resolve(getattr(args, 'metrics_token', None), 'METRICS_TOKEN',
                                               'metrics_token', None, str) or '').strip() or None, 'metrics-token'),
        'metrics_acl': parse_acl_value(resolve(getattr(args, 'metrics_acl', None), 'METRICS_ACL',
                                               'metrics_acl', DEFAULTS['metrics_acl'], str), 'metrics-acl'),
        'connect_acl': parse_acl_value(resolve(args.connect_acl, 'CONNECT_ACL', 'connect_acl',
                                               DEFAULTS['connect_acl'], str),
                                       'connect-acl'),
        'write_acl': parse_acl_value(resolve(args.write_acl, 'WRITE_ACL', 'write_acl',
                                             DEFAULTS['write_acl'], str),
                                     'write-acl'),
        'level': resolve(args.log_level, 'LOG_LEVEL', 'log_level', DEFAULTS['log_level'], str).upper(),
        'control_port': resolve(getattr(args, 'control_port', None), 'CTL',
                                'control_port', DEFAULTS['control_port'], str),
        'control_token': parse_secret(resolve(getattr(args, 'control_token', None), 'CONTROL_TOKEN',
                                              'control_token', '', str), 'control-token'),
        'control_ops_token': parse_secret(resolve(getattr(args, 'control_ops_token', None), 'CONTROL_OPS_TOKEN',
                                                  'control_ops_token', '', str), 'control-ops-token'),
        'control_ops_verbs': resolve(getattr(args, 'control_ops_verbs', None), 'CONTROL_OPS_VERBS',
                                     'control_ops_verbs', DEFAULTS['control_ops_verbs'], str),
        'audit_log': resolve(getattr(args, 'audit_log', None), 'AUDIT_LOG', 'audit_log', DEFAULTS['audit_log'], str),
        'audit_forward': resolve(getattr(args, 'audit_forward', None), 'AUDIT_FORWARD',
                                 'audit_forward', DEFAULTS['audit_forward'], str),
        'audit_forward_format': resolve(getattr(args, 'audit_forward_format', None), 'AUDIT_FORWARD_FORMAT',
                                        'audit_forward_format', DEFAULTS['audit_forward_format'], str),
        'audit_instance': resolve(getattr(args, 'audit_instance', None), 'AUDIT_INSTANCE',
                                  'audit_instance', DEFAULTS['audit_instance'], str),
        'audit_max_mb': resolve(getattr(args, 'audit_max_mb', None), 'AUDIT_MAX_MB',
                                'audit_max_mb', DEFAULTS['audit_max_mb'], float, row=OPT['audit-max-mb'],
                                strict_bounds=True),
        'audit_daily': resolve_bool(getattr(args, 'audit_daily', False) or None, 'AUDIT_DAILY',
                                    'audit_daily', DEFAULTS['audit_daily']),
        'audit_files': resolve(getattr(args, 'audit_files', None), 'AUDIT_FILES',
                               'audit_files', DEFAULTS['audit_files'], int, row=OPT['audit-files'],
                               strict_bounds=True),
        'no_audit_log': resolve_bool(getattr(args, 'no_audit_log', False) or None, 'NO_AUDIT_LOG',
                                     'no_audit_log', DEFAULTS['no_audit_log']),
        'requests_audit_s': resolve(getattr(args, 'audit_requests', None), 'AUDIT_REQUESTS',
                                    'requests_audit_s', DEFAULTS['audit_requests'], off_float),
        'dump_path': resolve(getattr(args, 'dump_path', None), 'DUMP_PATH',
                             'dump_path', DEFAULTS['dump_path'], str),
        'dump_key': parse_secret((resolve(getattr(args, 'dump_key', None), 'DUMP_KEY',
                                          'dump_key', None, str) or '').strip() or None, 'dump-key'),
        'dump_interval': resolve(getattr(args, 'dump_interval', None), 'DUMP_INTERVAL',
                                 'dump_interval', DEFAULTS['dump_interval'], float, row=OPT['dump-interval']),
        'dump_with_cache': resolve_bool(getattr(args, 'dump_with_cache', False) or None,
                                        'DUMP_WITH_CACHE', 'dump_with_cache', DEFAULTS['dump_with_cache']),
        'restore_on_start': resolve_bool(getattr(args, 'restore_on_start', False) or None,
                                         'RESTORE_ON_START', 'restore_on_start', DEFAULTS['restore_on_start']),
        'control_trust_uids': parse_trust_uids(resolve(getattr(args, 'control_trust_uids', None),
                                                       'CONTROL_TRUST_UIDS',
                                                       'control_trust_uids', DEFAULTS['control_trust_uids'], str)),
        'control_socket_group': resolve_bool(getattr(args, 'control_socket_group', False) or None,
                                             'CONTROL_SOCKET_GROUP', 'control_socket_group', DEFAULTS['control_socket_group']),
        'control_log_replies': resolve_bool(getattr(args, 'control_log_replies', False) or None,
                                            None, 'control_log_replies', False),
    }
    validate_config(cfg)
    return cfg
