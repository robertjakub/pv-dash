#!/usr/bin/env python3
"""JSON-lines control server for modbus-cache: inspect and steer the running
proxy — show connections/cache/version/config, clear the cache, restart the
upstream session, reload the whole daemon (the overrides saved, then a
re-exec), graceful shutdown. One command per line, one reply line.
Every request and reply is one JSON object per line (the stdlib json
module): the request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. TCP connections need a token
auth handshake when --control-token is set ({"cmd": "auth", "token": ...});
the unix socket relies on filesystem permissions instead. A second,
read-only token (--control-ops-token) authenticates into the show/clear
verbs only — the ops shift against the admin key, both audited."""
import logging
import os
import time

from common.runtime.version import version_string
from common.settings.config import auth_key_floor_error, default_profile_path, is_loopback_host, parse_auth_type, \
    parse_upstream, resolve_profile_file
from common.modbus import AUTH_MIN_KEY
from common.render.human import secs
from common.wire.control import ControlServer as _ControlServer, num, numi, on_off
from common.render.texts import T
from common.runtime.audit import load_audit_tags
from .statics import DEFAULT_LISTEN_PORT, LOG_LEVELS
from .options import OPTIONS, SETTING_BY_NAME, SET_BY_NAME, SHOW_OPTIONS, NODE_BY_NAME, \
    CFG_KEYS, CFG_FORMATTERS, COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN
from .cache import build_blocks
from .config import CONTROL_SOCKET_TEMPLATE, parse_write_registers, acl_value_text, acl_gate_summary, acl_table, parse_selection, parse_listen, \
    render_write_acl
from .metrics import MetricsServer, describe_metrics
from . import persist

logger = logging.getLogger('modbus-cache')



class ControlServer(_ControlServer):
    """JSON-lines control socket for the cache. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. A second, read-only token (ops_token) may be
    configured beside the admin token: it authenticates into the show/clear
    verbs only — no set/clear, no request dump/restore, no reload, no
    restart, no shutdown (common/wire/wiresec.py's roles). `stopper` is the graceful-stop
    callback shared with the signal handlers; it runs after the shutdown
    reply left the wire."""

    LOG = logger
    OPTIONS = OPTIONS
    SETTINGS = SETTING_BY_NAME
    WHO = 'the modbus-cache'
    EXIT_TEXT = 'the modbus-cache proxy is shutting down'
    RELOAD_TEXT = 'the modbus-cache proxy is reloading — the daemon restarts with the saved configuration'
    CFG_KEYS = CFG_KEYS               # the registry's knob -> cfg-key renames (show config)
    CFG_FORMATTERS = CFG_FORMATTERS   # the structured values (the ACLs, the write map, the selection)
    APP = 'modbus-cache'
    AUDIT_PREFIX = load_audit_tags('cache')
    AUDIT_APP = 'modbus-cache'
    CONTROL_PORT_DEFAULT = DEFAULT_LISTEN_PORT
    CONTROL_SOCKET_TEMPLATE = CONTROL_SOCKET_TEMPLATE
    LOG_LEVELS = LOG_LEVELS
    COMMANDS = COMMANDS
    COMMAND_HELP = COMMAND_HELP
    COMMAND_GROUPS = COMMAND_GROUPS
    COMMAND_HIDDEN = COMMAND_HIDDEN
    NODE_BY_NAME = NODE_BY_NAME
    SET_BY_NAME = SET_BY_NAME
    SHOW_OPTIONS = SHOW_OPTIONS
    SHOW_REPORTS = {'show cache-all': 'cache_all_report',
                    'show uplink': 'uplink_report',
                    'show uplink-sources': ('uplink_report', True),
                    'show cache': 'cache_report',
                    'show write-registers-table': 'write_registers_table_report',
                    'show connect-acl-table': ('acl_table_report', 'connect'),
                    'show write-acl-table': ('acl_table_report', 'write'),
                    'show metrics-acl-table': ('acl_table_report', 'metrics')}

    @property
    def dump_path(self):
        """The state dump file's one home is the proxy's (set dump-path
        applies there) — the base's dump-family reads and the command
        spine's dump-interval gates ride this view."""
        return self.proxy.dump_path

    @dump_path.setter
    def dump_path(self, v):
        pass   # the base __init__'s startup assignment lands nowhere — the proxy's value rules

    def show_config_cfg(self):
        """The resolved startup config dict — the proxy's live one home (the
        `_apply` branches write back into it, so the live overrides ride in
        as their current values)."""
        return self.proxy.config

    def __init__(self, proxy, target, stopper=None, audit=None, token=None, defaults=None, trust_uids=None,
                 socket_group=False, ops_token=None, ops_verbs=None, config_path=None, log_replies=False):
        self.proxy = proxy
        super().__init__(target, stopper=stopper, audit=audit, token=token, defaults=defaults,
                         trust_uids=trust_uids, socket_group=socket_group, ops_token=ops_token,
                         ops_verbs=ops_verbs, config_path=config_path, log_replies=log_replies)
        self.audit_params = proxy.audit_params   # the family handler rebuilds from the proxy's params

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, clear <setting>, inspect, show <setting|connections|cache|'
                'uplink|uplink-sources|version|config|knobs|write-registers-table|acl-connect-table|acl-write-table>')
        cmds += ', request flush cache, request poll now, request reload, request reload-config, request restart, shutdown, quit'
        return self.command_help_tail(cmds, dump_words=', request dump [with-cache], request restore')

    def command_tool(self, low, cmd):
        """The cache's own verbs beside the family's request namespace:
        the cache clear (the words drop, the poll wakes), the poll-now
        nudge, the dump with-cache spelling and the upstream session
        restart."""
        if low == 'request flush cache':
            dropped = self.proxy.cache.clear()
            self.proxy.poll_wake.set()
            logger.info('control: cache cleared (%d register word(s) dropped), repolling now', dropped)
            return 'ok cache cleared (%d register word(s) dropped), repolling now' % dropped
        if low == 'request poll now':
            self.proxy.poll_wake.set()
            logger.info('control: request poll now (the loop wakes immediately)')
            return 'ok request poll now (the loop wakes immediately, %s)' % self.summary()
        if low == 'request dump with-cache':
            return self.dump_state(True)
        if low == 'request restart':
            with self.proxy.upstream.lock:
                self.proxy.upstream.close()
            dropped = self.proxy.cache.clear()
            self.proxy.poll_wake.set()
            logger.info('control: upstream session restarted (connection dropped, %d register word(s) dropped, repolling now)',
                        dropped)
            return 'ok upstream session restarted (connection dropped, %d register word(s) dropped, repolling now)' % dropped
        return None

    def cache_report(self):
        """The one-line cache state (show cache): the ok frame wraps the
        bare line the proxy renders."""
        return 'ok ' + self.cache_line()

    def _apply(self, key, value):
        """Apply a live setting; returns the display string or raises
        ValueError (the message becomes the err reply). A restart-marked
        knob records only: the value lands in the configured-value table
        (show renders it, the dump/reload state carries it) — the restart
        (the reload's execv, whose fold reads the state before the binds)
        applies it. A restart-marked secret refuses: it can never ride the
        reload state."""
        p = self.proxy
        val = str(value).strip()

        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: validate + record the pending value
            if s.secret:
                raise ValueError(T('wire.restart_required'))
            handled, shown = self.apply_restart_key(key, val)
            if handled:
                return shown
            if key == 'upstream':
                try:
                    host, port = parse_upstream(val, label='upstream')
                except SystemExit as e:
                    raise ValueError(str(e))
                self.defaults[key] = '%s:%d' % (host, port)
                return self.defaults[key]
            if key in ('listen', 'metrics-listen'):
                try:
                    t = parse_listen(val)
                except SystemExit as e:
                    raise ValueError(str(e))
                if key == 'metrics-listen':
                    self.probe_bind(t, key)
                    if p.metrics_srv is not None and not p.metrics_token and not is_loopback_host(t[0]):
                        raise ValueError('metrics-listen cannot move beyond loopback while the endpoint '
                                         'serves without a token (F13 in docs/SECURITY.md) — '
                                         'pass metrics-token by flag/env/config and restart')
                self.defaults[key] = '%s:%d' % t
                return self.defaults[key]
            raise ValueError(T('wire.unknown_setting_bare') % key)

        if key == 'dump-interval':   # the proxy's homes — the family handler's attrs are not
            if not p.dump_path:
                raise ValueError(T('wire.dump_interval_needs_path'))
            if val in ('off', 'none', '0'):
                p.dump_interval = 0
                p.config['dump_interval'] = 0
                p.dump_wake.set()
                return 'off'
            v = num(val, 'dump-interval', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.dump_interval = v
            p.config['dump_interval'] = v
            p.dump_wake.set()
            return secs(v)
        if key == 'dump-path':
            if val in ('off', 'none', ''):
                p.dump_path = None
                p.config['dump_path'] = ''
                return 'off'
            p.dump_path = val   # the dump loop, request dump and the shutdown write it from here on
            p.config['dump_path'] = val
            # the seal is opt-in: without dump/key the dump stays plaintext — say so, once, where the choice is made
            return val if p.dump_key else '%s (not sealed — set dump/key to encrypt at rest)' % val

        handled, shown = self.apply_family_key(key, val)   # the family's shared knobs (the control plane,
        if handled:                                        # the audit family, the log level, local-time)
            return shown

        if key == 'interval':
            v = num(val, 'interval', 'seconds')
            if not 0 < v <= 86400:
                raise ValueError(T('wire.interval_range'))
            p.interval = v
            p.config['interval'] = v   # the live overrides ride show config (show_config_cfg's contract)
            p.poll_wake.set()
            return secs(v)
        if key == 'cache-ttl':
            if val in ('off', 'none', '0'):
                p.cache.cache_ttl = 0
                p.config['cache_ttl'] = 0
                return 'off'
            v = num(val, 'ttl', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.cache.cache_ttl = v
            p.config['cache_ttl'] = v
            return secs(v)
        if key == 'read-delay':
            v = num(val, 'read-delay', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.read_delay = v
            p.config['read_delay'] = v
            return secs(v)
        if key == 'merge-gap':
            v = numi(val, 'merge-gap', 'registers')
            self._gate_range(key, v, 'registers')
            p.merge_gap = v
            p.config['merge_gap'] = v
            p.blocks = build_blocks(p.cache.ranges, v)
            p.poll_wake.set()
            return '%d' % v
        if key == 'unit':
            v = numi(val, 'unit', 'unit id')
            self._gate_range(key, v)
            p.upstream.unit = v
            p.upstream.close()   # the in-flight session spoke the old unit
            p.config['unit'] = v
            return '%d' % v
        if key == 'modbus-auth':
            try:
                v = parse_auth_type(val, 'modbus-auth')
            except SystemExit as e:
                raise ValueError(str(e))
            if v and not p.config.get('modbus_auth_key'):
                raise ValueError(T('wire.suite_auth_needs_key') % AUTH_MIN_KEY)
            p.config['auth'] = v   # the next connection handshakes; the standing ones keep their session
            return v or 'none'
        if key == 'modbus-auth-upstream':
            try:
                v = parse_auth_type(val, 'modbus-auth-upstream', schemes=('suite', 'waveshare'))
            except SystemExit as e:
                raise ValueError(str(e))
            standing = p.config.get('modbus_auth_upstream_key')
            if v and not standing:
                raise ValueError('the %s auth needs a key: pass modbus-auth-upstream-key by flag/env/config and restart%s'
                                 % (v, ' (min %d characters)' % AUTH_MIN_KEY if v == 'suite' else ''))
            if v and standing is not None:
                err = auth_key_floor_error(v, standing)
                if err:
                    raise ValueError('the %s auth rejects the standing key (modbus-auth-upstream-key %s) — '
                                     'pass modbus-auth-upstream-key by flag/env/config and restart' % (v, err))
            p.config['modbus_auth_upstream'] = v
            p.upstream.auth = v
            p.upstream.close()   # the session re-proves the new scheme on the next exchange
            return v or 'none'
        if key == 'allow-write':
            on = on_off(val, 'allow-write')
            p.allow_write = on
            p.config['allow_write'] = on
            return 'on' if on else 'off'
        if key == 'write-registers':
            try:
                p.set_write_registers(parse_write_registers(val, 'write-registers'))
            except SystemExit as e:
                raise ValueError(str(e))
            p.config['write_registers'] = p.write_registers
            shown = p.describe_write_ranges()
            if p.write_gate_warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % p.write_gate_warn
            return shown
        if key == 'max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            p.max_clients = v
            p.config['max_clients'] = v
            return '%d' % v
        if key == 'client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.client_timeout = v
            p.config['client_timeout'] = v
            return secs(v)
        if key == 'max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            p.conn_gate.max_per_ip = v
            p.config['max_conn_per_ip'] = v
            return '%d' % v
        if key == 'metrics-server':
            if val in ('on', 'true', '1', 'yes'):
                if p.metrics_srv:
                    return 'on'
                if not p.metrics_token:
                    host, _port = p.metrics_listen
                    if not is_loopback_host(host):
                        raise ValueError('the metrics endpoint serves register values: refusing to expose '
                                         '/metrics beyond loopback without a token (F13 in docs/SECURITY.md) — '
                                         'pass metrics-token by flag/env/config and restart, or bind '
                                         'metrics-listen on 127.0.0.1')
                srv = MetricsServer(p, p.metrics_listen, token=p.metrics_token,
                                    max_clients=p.metrics_caps[0], client_timeout=p.metrics_caps[1],
                                    max_per_ip=p.metrics_caps[2])
                try:
                    srv.start()
                except SystemExit:
                    host, port = p.metrics_listen
                    raise ValueError(T('wire.cannot_bind') % (host, port, srv.bind_error))
                p.metrics_srv = srv
                p.config['metrics_server'] = True
                p.metrics_desc = describe_metrics(p.metrics_listen, p.metrics_token,
                                                  p.metrics_caps[0], p.metrics_caps[2])
                return 'on'
            if val in ('off', 'false', '0', 'no'):
                if p.metrics_srv:
                    p.metrics_srv.stop()
                    p.metrics_srv = None
                    p.metrics_desc = 'off'
                p.config['metrics_server'] = False
                return 'off'
            on_off(val, 'metrics-server')   # raises the refusal
        if key == 'metrics-max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            p.metrics_caps = (v, p.metrics_caps[1], p.metrics_caps[2])
            p.config['metrics_max_clients'] = v
            if p.metrics_srv:
                p.metrics_srv.max_clients = v
                p.metrics_srv._http.gate.max_total = v   # the gate reads its caps per admit
            return '%d' % v
        if key == 'metrics-client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.metrics_caps = (p.metrics_caps[0], v, p.metrics_caps[2])
            p.config['metrics_client_timeout'] = v
            if p.metrics_srv:
                p.metrics_srv.client_timeout = v
                p.metrics_srv._Handler.timeout = v or 5   # 0 = the built-in slowloris cap
            return secs(v)
        if key == 'metrics-max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            p.metrics_caps = (p.metrics_caps[0], p.metrics_caps[1], v)
            p.config['metrics_max_conn_per_ip'] = v
            if p.metrics_srv:
                p.metrics_srv.max_per_ip = v
                p.metrics_srv._http.gate.max_per_ip = v
            return '%d' % v
        if key == 'requests-audit':
            if val in ('off', 'none', '0'):
                p.requests_audit_s = 0
                p.config['requests_audit_s'] = 0
                return 'off'
            v = num(val, 'requests-audit', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.requests_audit_s = v
            p.config['requests_audit_s'] = v
            return secs(v)
        if key == 'dump-with-cache':
            on = on_off(val, 'dump-with-cache')
            p.dump_with_cache = on
            p.config['dump_with_cache'] = on
            return 'on' if on else 'off'
        if key == 'log-access':
            on = on_off(val, 'log-access')
            p.log_access = on   # the next connect/disconnect log line picks it up
            p.config['log_access'] = on
            return 'on' if on else 'off'
        if key == 'timeout':
            v = num(val, 'timeout', 'seconds')
            if not 0 < v <= 60:
                raise ValueError(T('wire.timeout_range'))
            p.upstream.timeout = v
            p.config['timeout'] = v
            return secs(v)
        if key == 'connect-acl':
            if val.lower() == 'table':   # the show word is never a value — point at the report
                raise ValueError(T('wire.acl_table_value') % ('connect-acl', 'connect-acl-table'))
            shown = p.set_connect_acl(val)
            if p.connect_acl_warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % p.connect_acl_warn
            return shown
        if key == 'write-acl':
            if val.lower() == 'table':
                raise ValueError(T('wire.acl_table_value') % ('write-acl', 'write-acl-table'))
            shown = p.set_write_acl(val)
            if p.write_acl_warn:
                shown += ' (%s)' % p.write_acl_warn
            return shown
        if key == 'metrics-acl':
            if val.lower() == 'table':   # the show word is never a value — point at the report
                raise ValueError(T('wire.acl_table_value') % ('metrics-acl', 'metrics-acl-table'))
            shown = p.set_metrics_acl(val)
            if p.metrics_acl_warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % p.metrics_acl_warn
            return shown
        if key in ('profile', 'selection'):
            cfg = self._live_cfg()
            if key == 'profile':
                cfg['profile'] = default_profile_path() if val in ('default', 'auto') \
                    else resolve_profile_file(val)
            else:
                cfg['selection'] = parse_selection(val)
            saved = p.config
            saved_gate = (p.write_registers, p.write_ranges)
            p.config = cfg
            try:
                if p.write_registers == 'profile':
                    p.write_ranges = p._resolve_write_ranges(p.write_registers)   # the new profile's gate
                p.apply_map()      # ValueError on a bad file: swap and config roll back
            except Exception:
                p.config = saved
                p.write_registers, p.write_ranges = saved_gate
                raise
            return cfg['profile'] if key == 'profile' else (cfg['selection'] or 'all')
        shown = self.apply_typed_key(key, val)   # the typed-row fallback: the row's words, conv, choices, bounds, check
        if shown is not None:
            return str(shown)
        raise ValueError('unknown setting %s' % key)

    def _live_cfg(self):
        """The startup config overlaid with every live setting value, so a map
        reload never undoes what the control surface already applied."""
        p = self.proxy
        cfg = dict(p.config)
        cfg.update(interval=p.interval, read_delay=p.read_delay, merge_gap=p.merge_gap,
                   cache_ttl=p.cache.cache_ttl, allow_write=p.allow_write,
                   write_registers=p.write_registers, max_clients=p.max_clients,
                   client_timeout=p.client_timeout, requests_audit_s=p.requests_audit_s,
                   connect_acl=p.connect_acl, write_acl=p.write_acl, metrics_acl=p.metrics_acl,
                   timeout=p.upstream.timeout,
                   upstream='%s:%d' % (p.upstream.host, p.upstream.port),
                   host=p.upstream.host, port=p.upstream.port, unit=p.upstream.unit)
        return cfg

    def record_cfg(self, updates):
        """The live truth rides the proxy's resolved-config dict (the
        show-config-writeback contract — show_config_cfg returns it)."""
        self.proxy.config.update(updates)

    def _rebuild_audit(self):
        """The family rebuild, mirrored onto the proxy — the requests' audit
        and the summary read the proxy's view."""
        shown = super()._rebuild_audit()
        self.proxy.audit = self.audit
        return shown

    @staticmethod
    def _acl_text(acl):
        """'any' | 'none' | the normalized network list | the file: reference
        (what `clear` re-parses)."""
        return acl_value_text(acl)

    def _get(self, key):
        p = self.proxy
        if key == 'dump-interval':   # the proxy's home — the family handler's attr is not
            return 'off' if not p.dump_interval else secs(p.dump_interval)
        handled, value = self.get_family_key(key)   # the family's shared knobs (the control plane,
        if handled:                                 # the audit family, the log level, local-time, dump/path)
            return value
        if key == 'interval':
            return secs(p.interval)
        if key == 'cache-ttl':
            return 'off' if not p.cache.cache_ttl else secs(p.cache.cache_ttl)
        if key == 'read-delay':
            return secs(p.read_delay)
        if key == 'merge-gap':
            return '%d' % p.merge_gap
        if key == 'unit':
            return '%d' % p.upstream.unit
        if key == 'modbus-auth':
            return p.config.get('auth') or 'none'
        if key == 'modbus-auth-upstream':
            return p.config.get('modbus_auth_upstream') or 'none'
        if key == 'allow-write':
            return 'on' if p.allow_write else 'off'
        if key == 'write-registers':
            return p.describe_write_ranges()
        if key == 'max-clients':
            return '%d' % p.max_clients
        if key == 'client-timeout':
            return 'none' if not p.client_timeout else secs(p.client_timeout)
        if key == 'max-conn-per-ip':
            return '%d' % p.conn_gate.max_per_ip
        if key == 'metrics-server':
            return 'on' if p.metrics_srv else 'off'
        if key == 'metrics-max-clients':
            return '%d' % p.metrics_caps[0]
        if key == 'metrics-client-timeout':
            return secs(p.metrics_caps[1])
        if key == 'metrics-max-conn-per-ip':
            return '%d' % p.metrics_caps[2]
        if key == 'dump-with-cache':
            return 'on' if p.dump_with_cache else 'off'
        if key == 'requests-audit':
            return 'off' if not p.requests_audit_s else secs(p.requests_audit_s)
        if key == 'log-access':
            return 'on' if p.log_access else 'off'
        if key == 'timeout':
            return secs(p.upstream.timeout)
        if key == 'connect-acl':
            return self._acl_text(p.connect_acl)
        if key == 'write-acl':
            return self._acl_text(p.write_acl)
        if key == 'metrics-acl':
            return self._acl_text(p.metrics_acl)
        if key == 'profile':
            return p.config.get('profile') or p.profile
        if key == 'selection':
            return p.config.get('selection') or 'all'
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

    def summary(self):
        """The compact state summary appended to the set/clear replies."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else secs(max(0, now - p.last_ok))
        return ('upstream=%s:%d interval=%s ttl=%s poll=%s last-poll=%s hits=%d misses=%d clients=%d'
                % (p.upstream.host, p.upstream.port, secs(p.interval), secs(p.cache.cache_ttl),
                   'ok' if p.poll_ok else 'down', age, p.cache_hits, p.cache_misses, p.client_count))

    def connections_line(self):
        return self.modbus_connections_line(self.proxy.clients, self.proxy.client_lock)

    def inspect(self):
        """One pretty dump of everything — the state, the map, the counters,
        the write gate: the baton for a bug report. Multi-line reply."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else '%s ago' % secs(max(0, now - p.last_ok))
        fc3 = sum(1 for r in p.cache.ranges if r[0] == 3)
        fc4 = len(p.cache.ranges) - fc3
        cfg = p.config or {}
        rows = [
            'version   modbus-cache %s' % version_string(),
            'upstream  %s:%d unit %d, timeout %s, upstream auth %s, last poll %s%s' % (p.upstream.host, p.upstream.port,
                                                                                       p.upstream.unit, secs(p.upstream.timeout),
                                                                                       p.config.get('modbus_auth_upstream') or 'none',
                                                                                       age,
                                                                                       '' if p.poll_ok else ' (FAILING)'),
            'listen    %s:%d, control %s, connect-acl %s, client auth %s'
            % (p.listen_addr[0], p.listen_addr[1], self.describe(),
               acl_gate_summary(p.connect_acl), p.config.get('auth') or 'none'),
            'profile   %s, map v%d' % (cfg.get('profile') or p.profile,
                                       p.cache.map_version),
            'selection %s' % (cfg.get('selection') or 'all'),
            'metrics   %s' % getattr(p, 'metrics_desc', 'off'),
            'selection %s' % (cfg.get('selection') or 'all'),
            'cache     %d range(s) (fc3 %d, fc4 %d), %d word(s), oldest %s, ttl %s, failed range(s) %d'
            % (len(p.cache.ranges), fc3, fc4, len(p.cache.regs),
               self._oldest() or 'n/a', secs(p.cache.cache_ttl),
               sum(1 for v in p.cache.range_ok.values() if v is False)),
            'poll plan %d block(s): %s' % (len(p.blocks),
                                           ' '.join('%s%d:%d' % ('' if fc == 3 else 'fc%d ' % fc, s, c)
                                                    for fc, s, c, _ in p.blocks)),
            'poll cyc  last %s, mean %s, max %s'
            % (secs(p.poll_secs_last),
               secs(p.poll_secs_sum / p.poll_count if p.poll_count else 0), secs(p.poll_secs_max)),
            'counters  hits %d, misses %d, clients %d (limit %s, timeout %s, per-ip %s)'
            % (p.cache_hits, p.cache_misses, p.client_count,
               p.max_clients or 'none', secs(p.client_timeout) if p.client_timeout else 'none',
               p.conn_gate.max_per_ip or 'none'),
            'writes    %s, write-acl %s, write-registers %s'
            % ('ENABLED' if p.allow_write else 'disabled',
               acl_gate_summary(p.write_acl),
               p.describe_write_gate()),
            'audit     %s%s' % ('off' if p.audit is None else (p.audit.path if p.audit.path != '-' else 'stdout'),
                                ', requests accounting every %s' % secs(p.requests_audit_s) if p.audit and p.requests_audit_s else ''),
            'dump      %s' % ('off' if not p.dump_path else '%s, every %s (plus the dump command and the shutdown)'
                              % (p.dump_path, 'off' if not p.dump_interval else secs(p.dump_interval))),
            'uptime    %s' % secs(now - p.started),
        ]
        return 'ok inspect\n' + '\n'.join(rows)

    def _oldest(self):
        with self.proxy.cache.lock:
            oldest = max((time.time() - t for t in self.proxy.cache.ts.values()), default=None)
        return secs(oldest) if oldest is not None else None

    def cache_line(self):
        c = self.proxy.cache
        with c.lock:
            words = len(c.regs)
            fc4 = sum(1 for r in c.ranges if r[0] == 4)
        failed = sum(1 for v in c.range_ok.values() if v is False)
        return ('cache %d range(s)%s, %d word(s) cached%s, ttl %s, map v%d, failed range(s) %d, hits %d, misses %d'
                % (len(c.ranges), ' (fc4 %d)' % fc4 if fc4 else '', words,
                   ', oldest %s' % (self._oldest() or 'n/a'),
                   secs(c.cache_ttl), c.map_version, failed, self.proxy.cache_hits, self.proxy.cache_misses))

    def write_registers_table_report(self):
        """The write/registers/table show report (the show-only view of
        the write gate): 'allow any' when the knob is any, 'deny any' when
        it is none; a range list renders as its whitelist — 'deny any' and
        one allow line per range; a string knob ('profile' or the
        'file:<path>' acl) renders the gate's own rules — the gate's desc
        as the '% ' line, then one '<verb> <range> # <desc>' line per
        range, the comments aligned (the live gate: the rules the running
        gate resolved from, not the file's current state)."""
        p = self.proxy
        lines = ['ok write-registers-table']
        wr = p.write_registers
        if wr is None:
            lines.append('allow any')
        elif isinstance(wr, str):   # 'profile' or the file:<path> acl reference
            if p.write_gate_rules is None:
                return 'err write-registers-table: the gate is not resolved'
            lines.extend(render_write_acl(*p.write_gate_rules))
        elif not wr:
            lines.append('deny any')
        else:   # a range list renders as its whitelist: the default deny, then the opens
            lines.append('deny any')
            lines.extend('allow %d:%d' % r for r in wr)
        return '\n'.join(lines)

    def acl_table_report(self, which):
        """The acl/connect/table + acl/write/table + metrics/acl/table
        show reports (the show-only view of the three IP ACLs, one entry
        per line): the system forms spell the chain they implement —
        'allow 0.0.0.0/0' (any), 'deny 0.0.0.0/0' (none), 'deny 0.0.0.0/0'
        + one allow line per network (the whitelist); a file gate renders
        its own rules — the gate desc as the '% ' line, the rule descs as
        aligned '# ' comments, the matcher 'any' spelled 0.0.0.0/0."""
        p = self.proxy
        acl = {'connect': p.connect_acl, 'write': p.write_acl, 'metrics': p.metrics_acl}[which]
        return 'ok acl-%s-table\n%s' % (which, '\n'.join(acl_table(acl)))

    def cache_all_report(self):
        """Every cached entry, one row per profile range: the words cached,
        their values, the age of the oldest, when it expires and the poll
        status."""
        c = self.proxy.cache
        names = c.names
        cells = []
        for fc, start, count, words, values, oldest, err, entry_ttl in c.entries():
            ttl = entry_ttl if entry_ttl is not None else c.cache_ttl
            age = 'n/a' if oldest is None else secs(oldest)
            shown = [('-' if v is None else '%d' % v) for v in values] or ['-']
            if not ttl:
                exp = 'never'
            elif oldest is None:
                exp = 'n/a'
            else:
                left = ttl - oldest
                exp = secs(left) if left > 0 else 'expired'
            if err is not None:
                status = 'failed (ex %d)' % err
            elif not words:
                status = 'empty'
            elif words < count:
                status = 'partial'
            else:
                status = 'ok'
            name = names.get((fc, start, count), '')
            if entry_ttl is not None:
                name = ('%s [ttl %s]' % (name, secs(entry_ttl))).strip()
            cells.append(('fc%d' % fc, '%d:%d' % (start, count), '%d/%d' % (words, count),
                          ' '.join(shown), age, exp, status, name))
        head = ('fc', 'range', 'words', 'values', 'age', 'expires', 'status', 'name')
        widths = [max(len(h), max((len(r[i]) for r in cells), default=0)) for i, h in enumerate(head)]
        rows = ['  '.join(h.ljust(w) for h, w in zip(head, widths))]
        for r in cells:
            rows.append('  '.join(v.ljust(w) for v, w in zip(r, widths)))
        return 'ok cache-all\n' + '\n'.join(rows)

    @staticmethod
    def _bytes(n):
        return '%.1fkiB' % (n / 1024) if n >= 1024 else '%dB' % n

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values (a
        SIGHUP clears the override set — the dump follows). No secret can
        be overridden (the wire refuses them — startup-only), so no
        secret placeholder occurs; the dump filter's secret branch
        stays as the class invariant's guard."""
        p = self.proxy
        raw = {
            'interval': p.interval, 'cache-ttl': p.cache.cache_ttl,
            'read-delay': p.read_delay,
            'merge-gap': p.merge_gap, 'allow-write': 'on' if p.allow_write else 'off',
            'write-registers': p.describe_write_ranges(), 'max-clients': p.max_clients,
            'client-timeout': p.client_timeout, 'max-conn-per-ip': p.conn_gate.max_per_ip,
            'metrics-server': 'on' if p.metrics_srv else 'off',
            'metrics-listen': '%s:%d' % p.metrics_listen,
            'metrics-max-clients': p.metrics_caps[0],
            'metrics-client-timeout': p.metrics_caps[1],
            'metrics-max-conn-per-ip': p.metrics_caps[2],
            'requests-audit': p.requests_audit_s,
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'log-access': 'on' if p.log_access else 'off',
            'profile': p.config.get('profile'), 'selection': p.config.get('selection') or 'all',
            'connect-acl': self._acl_text(p.connect_acl), 'write-acl': self._acl_text(p.write_acl),
            'metrics-acl': self._acl_text(p.metrics_acl),
            'modbus-auth': p.config.get('auth') or 'none',
            'modbus-auth-upstream': p.config.get('modbus_auth_upstream') or 'none',
            'upstream': '%s:%d' % (p.upstream.host, p.upstream.port),
            'unit': p.upstream.unit,
            'timeout': p.upstream.timeout, 'dump-interval': p.dump_interval,
            'local-time': self._get('local-time'),
            'control-port': 'off' if self.stopped else (str(self.port) if not self.is_unix else self.sockpath),
            'control-ops-verbs': ','.join(sorted(self.ops_verbs)) or 'off',
            'control-trust-uids': ','.join(str(u) for u in sorted(self.trust_uids)) or 'off',
            'control-socket-group': 'on' if self.socket_group else 'off',
            'control-log-replies': 'on' if self.log_replies else 'off',
            **self.audit_dump_rows(),
            'dump-path': p.dump_path or 'off',
            'dump-with-cache': 'on' if p.dump_with_cache else 'off',
            'restore-on-start': 'on' if getattr(p, 'restore_on_start', False) else 'off',
        }
        return self.dump_settings_tail(raw)

    # --- the dump/reload family: the reload state file and the whole-daemon
    # reload (`reload`) ride the base (_save/_restore/_reload_state_path/
    # apply_dump_settings/reload_daemon — the seal key reads the dump_key
    # property below: the proxy is the one home, startup-only — the re-exec
    # re-resolves the same argv, so the key is identical on both sides).
    # The cache's own dump/restore OVERRIDES the base's — the words
    # (+ stamps) ride along beside the settings (the write-behind that lets
    # a restart serve last-known values). ---

    @property
    def dump_key(self):
        return self.proxy.dump_key


    def dump_state(self, with_cache=None):
        """The write-behind: the live setting overrides and — when
        with_cache (the `request dump with-cache` command, the
        `--dump-with-cache` default or the dump-interval loop) — the cached
        words (+ stamps), to the configured dump path — sealed when
        dump/key is configured. The family's `request dump` calls bare:
        None = the configured --dump-with-cache default."""
        if with_cache is None:
            with_cache = self.proxy.dump_with_cache
        path = self.proxy.dump_path
        if not path:
            return 'err no dump path configured (set dump-path or --dump-path)'
        settings = self.dump_settings()
        try:
            n = persist.write_dump(path, self.proxy.cache, settings, with_cache=with_cache,
                                   key=self.proxy.dump_key)
        except (OSError, ValueError) as e:
            logger.error('control: the dump to %s failed: %s', path, e)
            return 'err dump failed: %s' % e
        logger.info('control: state dumped to %s (%d word(s), %d setting(s), %s%s)', path, n,
                    len(settings), 'with cache' if with_cache else 'settings only',
                    ', sealed' if self.proxy.dump_key else '')
        return 'ok dumped %d word(s), %d setting(s) to %s%s' % (
            n, len(settings), path, ' (sealed)' if self.proxy.dump_key else '')

    def restore_state(self):
        """Load a dump back: the words (+ their original stamps, so the
        freshness carries over) land in the cache — only what the current
        register map still covers — and the setting overrides re-apply (a
        sealed dump restores only under the configured dump/key)."""
        path = self.proxy.dump_path
        if not path:
            return 'err no dump path configured (set dump-path or --dump-path)'
        if not os.path.exists(path):
            return 'err no dump at %s yet (run dump first)' % path
        try:
            words, stamps, settings = persist.read_dump(path, key=self.proxy.dump_key)
            n = 0 if self.proxy.no_cache else self.proxy.cache.restore(words, stamps)
            applied, failed = self.apply_dump_settings(settings)
        except ValueError as e:
            return 'err restore failed: %s' % e
        self.proxy.poll_wake.set()
        logger.info('control: state restored from %s (%d word(s), %d setting(s))', path, n, applied)
        return 'ok restored %d word(s), %d setting(s) from %s%s' % (
            n, applied, path, ' (%d skipped: %s)' % (len(failed), ', '.join(failed)) if failed else '')

    def uplink_report(self, with_sources=False):
        """The inverter link: the session counters (connects, exchanges,
        bytes, errors) and one row per poll block with its status, latency
        and last error — `show uplink-sources` widens the table with the
        block's sources column right after the range (one name,
        comma-separated when pooled), for analysing what the upstream
        connection does."""
        p = self.proxy
        u = p.upstream
        now = time.monotonic()
        if u.sock is not None:
            sess = 'connected %s' % (secs(now - u.connected_since)
                                     if u.connected_since is not None else '?')
        else:
            sess = 'down' if u.connects else 'never connected'
        mean = p.poll_secs_sum / p.poll_count if p.poll_count else 0.0
        last_ok = 'never' if p.last_ok is None else secs(now - p.last_ok)
        if u.last_error is None:
            last_err = 'none'
        else:
            when = '' if u.last_error_at is None else '%s ago: ' % secs(now - u.last_error_at)
            last_err = '%s%s' % (when, u.last_error)
        rows = [
            'upstream  %s:%d unit %d, timeout %s' % (u.host, u.port, u.unit, secs(u.timeout)),
            'session   %s, connects %d, exchanges %d, in %s out %s, errors %d'
            % (sess, u.connects, u.exchanges, self._bytes(u.bytes_in), self._bytes(u.bytes_out), u.errors),
            'last err  %s' % last_err,
            'poll      interval %s, cycle last %s mean %s max %s, last ok %s ago, plan %d block(s)'
            % (secs(p.interval), secs(p.poll_secs_last), secs(mean), secs(p.poll_secs_max),
               last_ok, len(p.blocks)),
        ]
        cells = []
        for fc, start, count, leaves in p.blocks:
            names = ', '.join(p._name(lf) for lf in leaves) if with_sources else None
            s = p.block_stats.get((fc, start, count))
            if s is None:
                row = ('fc%d' % fc, '%d:%d' % (start, count), 'pending', '-', '-', '-', '0', '-')
            else:
                if s['last_err'] is None:
                    status, err = 'ok', '-'
                elif s['last_code'] is not None:
                    status, err = 'ex %d' % s['last_code'], s['last_err']
                else:
                    status, err = 'error', s['last_err']
                row = ('fc%d' % fc, '%d:%d' % (start, count), status, secs(s['last']),
                       secs(s['sum'] / s['ok_n']) if s['ok_n'] else '-',
                       secs(s['max']), '%d' % s['fails'], err)
            if names is not None:
                row = row[:2] + (names,) + row[2:]   # the sources column rides after the range
            cells.append(row)
        if cells:
            head = (('fc', 'range', 'sources', 'status', 'last', 'mean', 'max', 'fails', 'last error')
                    if with_sources else
                    ('fc', 'range', 'status', 'last', 'mean', 'max', 'fails', 'last error'))
            widths = [max(len(h), max((len(r[i]) for r in cells), default=0)) for i, h in enumerate(head)]
            rows.append('  '.join(h.ljust(w) for h, w in zip(head, widths)))
            for r in cells:
                rows.append('  '.join(v.ljust(w) for v, w in zip(r, widths)))
        return 'ok %s\n%s' % ('uplink-sources' if with_sources else 'uplink', '\n'.join(rows))
