#!/usr/bin/env python3
"""Configuration for modbus-cache: ini/env/CLI resolution and the register map (stdlib only)."""
import configparser
import ipaddress
import json
import logging
import os

logger = logging.getLogger('modbus-cache')


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


def check_range(start, count, label):
    if start < 0 or start + count > 65536 or not 0 < count <= 125:
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
    """JSON register map: {"registers": [{"name": ..., "start": N, "count": N}, ...]}.

    List entries may also be plain "START:COUNT" strings. Returns
    (ranges, names) with names keyed by (start, count).
    """
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read ranges file %s: %s' % (path, e))
    entries = data.get('registers') if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise SystemExit('ranges file %s must contain a "registers" list' % path)
    ranges, names = [], {}
    for i, entry in enumerate(entries):
        label = 'ranges file %s, entry %d' % (path, i + 1)
        if isinstance(entry, str):
            ranges.append(parse_range(entry, label))
        elif isinstance(entry, dict):
            try:
                start, count = int(entry['start']), int(entry['count'])
            except (KeyError, TypeError, ValueError):
                raise SystemExit('%s needs integer "start" and "count"' % label)
            start_count = check_range(start, count, label)
            ranges.append(start_count)
            if entry.get('name'):
                names[start_count] = str(entry['name'])
        else:
            raise SystemExit('%s must be a string or an object' % label)
    return ranges, names


def parse_listen(text):
    host, sep, port = text.rpartition(':')
    if not sep:
        raise SystemExit('--listen must be HOST:PORT, got %r' % text)
    try:
        port = int(port)
    except ValueError:
        raise SystemExit('--listen port must be a number, got %r' % port)
    if not 0 <= port <= 65535:
        raise SystemExit('--listen port out of range, got %d' % port)
    return host.strip('[]'), port


def validate_config(cfg):
    """Fail fast on nonsensical settings.

    Raises SystemExit with a clean message; at startup that aborts with a
    proper error, on SIGHUP the reload watcher keeps the previous settings.
    """
    def fail(key, rule):
        raise SystemExit('invalid %s = %r: %s' % (key, cfg.get(key), rule))

    if not 1 <= cfg['port'] <= 65535:
        fail('port', 'must be 1..65535')
    if not 1 <= cfg['unit'] <= 247:
        fail('unit', 'must be 1..247 (Modbus unit id)')
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


def resolve_config(args, script_dir):
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

    interval = resolve(args.interval, 'MODBUS_CACHE_INTERVAL', 'interval', 10.0, float)
    cfg = {
        'host': resolve(args.host, 'MODBUS_CACHE_HOST', 'host', '127.0.0.1', str),
        'port': resolve(args.port, 'MODBUS_CACHE_PORT', 'port', 5502, int),
        'unit': resolve(args.unit, 'MODBUS_CACHE_UNIT', 'unit', 1, int),
        'timeout': resolve(args.timeout, 'MODBUS_CACHE_TIMEOUT', 'timeout', 3.0, float),
        'listen': resolve(args.listen, 'MODBUS_CACHE_LISTEN', 'listen', '0.0.0.0:15502', str),
        'interval': interval,
        'read_delay': resolve(args.read_delay, 'MODBUS_CACHE_READ_DELAY', 'read_delay', 0.05, float),
        'merge_gap': resolve(args.merge_gap, 'MODBUS_CACHE_MERGE_GAP', 'merge_gap', 8, int),
        'allow_write': resolve_bool(args.allow_write or None, 'MODBUS_CACHE_ALLOW_WRITE', 'allow_write', False),
        'registers_file': resolve(args.registers_file, 'MODBUS_CACHE_REGISTERS_FILE', 'registers_file',
                                  os.path.join(script_dir, 'registers.json'), str),
        'cache_ttl': resolve(args.cache_ttl, 'MODBUS_CACHE_TTL', 'cache_ttl', 3 * interval, float),
        'local_time': resolve_bool(args.local_time, 'MODBUS_CACHE_LOCAL_TIME', 'local_time', False),
        'log_access': resolve_bool(args.log_access, 'MODBUS_CACHE_LOG_ACCESS', 'log_access', False),
        'max_clients': resolve(args.max_clients, 'MODBUS_CACHE_MAX_CLIENTS', 'max_clients', 64, int),
        'client_timeout': resolve(args.client_timeout, 'MODBUS_CACHE_CLIENT_TIMEOUT', 'client_timeout', 300.0, float),
        'connect_acl': parse_acl(resolve(args.connect_acl, 'MODBUS_CACHE_CONNECT_ACL', 'connect_acl', 'any', str),
                                 'connect-acl'),
        'write_acl': parse_acl(resolve(args.write_acl, 'MODBUS_CACHE_WRITE_ACL', 'write_acl', 'any', str),
                               'write-acl'),
        'level': resolve(args.log_level, 'MODBUS_CACHE_LOG_LEVEL', 'log_level', 'INFO', str).upper(),
    }
    validate_config(cfg)
    return cfg
