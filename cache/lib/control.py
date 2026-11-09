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
import socket
import threading
import time

from common.version import version_string
from common.config import auth_key_floor_error, default_profile_path, is_loopback_host, parse_auth_type, parse_control_target, \
    parse_upstream, resolve_profile_file
from common.dump import SECRET_REMOVED, dump_filter
from common.modbus import AUTH_MIN_KEY
from common.cred import parse_trust_uids
from common.human import secs
from common.logutil import UtcFormatter
from common.wiresec import sign_reply, verify_request_mac, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.control import ControlServer as _ControlServer, num, numi
from common.options import control_command, grouped_rows, match_setting_path, describe_node, describe_root, \
    describe_command_node
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, DEFAULT_LISTEN_PORT, LOG_LEVELS
from .options import OPTIONS, SETTING_BY_NAME, SET_BY_NAME, describe_setting, SHOW_BY_LIVE, SHOW_OPTIONS, NODE_BY_NAME, \
    KNOWN_VERBS, CFG_KEYS, CFG_FORMATTERS, COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN
from .cache import build_blocks
from .config import CONTROL_SOCKET_TEMPLATE, parse_write_registers, acl_value_text, acl_gate_summary, acl_table, parse_selection, parse_listen, \
    render_write_acl
from .metrics import MetricsServer, describe_metrics
from . import persist

logger = logging.getLogger('modbus-cache')

# The registry-driven bounds: the row's min/max (inclusive) are the one
# home for a knob's range — the branches parse and plumb, the row gates.
OPTION_BY_LIVE = {o.live: o for o in OPTIONS if o.live}
TYPED_CONVS = (int, float, str)

MAX_LINE = CONTROL_LINE_CAP   # the pre-auth line-buffer cap (drop past it)


class ControlServer(_ControlServer):
    """JSON-lines control socket for the cache. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. A second, read-only token (ops_token) may be
    configured beside the admin token: it authenticates into the show/clear
    verbs only — no set/unset, no request dump/restore, no reload, no
    restart, no shutdown (common/wiresec.py's roles). `stopper` is the graceful-stop
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

    def show_config_cfg(self):
        """The resolved startup config dict — the proxy's live one home (the
        `_apply` branches write back into it, so the live overrides ride in
        as their current values)."""
        return self.proxy.config

    def __init__(self, proxy, target, stopper=None, audit=None, token=None, defaults=None, trust_uids=None,
                 socket_group=False, ops_token=None, ops_verbs=None, config_path=None):
        self.proxy = proxy
        super().__init__(target, stopper=stopper, audit=audit, token=token, defaults=defaults,
                         trust_uids=trust_uids, socket_group=socket_group, ops_token=ops_token,
                         ops_verbs=ops_verbs, config_path=config_path)

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, unset <setting>, inspect, show <setting|connections|cache|'
                'uplink|version|config|knobs|write-registers-profile|acl-connect-table|acl-write-table>')
        if self.proxy.dump_path:
            cmds += ', request dump [with-cache], request restore'
        cmds += ', request clear cache, request reload, request restart, shutdown, quit; help <setting> describes it, help config maps every knob to its control command, show knobs prints the full dictionary'
        return cmds

    def command(self, cmd):
        cmd = cmd.strip()
        low = cmd.lower()
        if low.split()[0] in ('help', '?') and low != '?':
            args = cmd.split()[1:]
            if args and args[0].lower() == 'config':
                return self.config_mapping()
            if args and args[0].lower() == 'knobs':
                return self.knobs_dictionary()
            path = '/'.join(w.lower() for w in args)   # the command paths spell as words too — the golden ladder: the commands before the settings
            listing = describe_command_node(COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN, path)
            if listing is not None:
                return 'ok %s' % listing
            if path in COMMAND_HELP:   # a command word — or a childless command node — describes itself
                return 'ok %s' % COMMAND_HELP[path]
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                if key == 'dump-interval' and not self.proxy.dump_path:
                    return 'err dump-interval needs a dump path (set dump/path or --dump-path)'
                return 'ok %s' % describe_setting(key)
            if path in NODE_BY_NAME:
                return 'ok %s' % describe_node(OPTIONS, path)
            if args:
                return 'err unknown command or setting %s (try ?)' % ' '.join(args)
            return 'ok ' + self.command_help()
        if low == '?':
            return 'ok ' + self.command_help()
        if low == 'quit':
            return 'bye'
        if low == 'ping':                 # keep-alive from cache_cli
            return 'ok pong'
        if cmd.startswith('unset'):
            args = cmd.split()[1:]
            if not args:
                return 'err unset needs a setting (try help)'
            key, rest = match_setting_path(args, SET_BY_NAME)   # the knobs: the show reports have nothing to unset
            s = SET_BY_NAME.get(key) if key is not None else None
            if s is not None and not rest and s.restart:
                if s.secret:   # a secret never rides the reload state — the wire refuses it
                    return 'err restart required (startup-only knob)'
                self.defaults[key] = self.baseline.get(key, self.defaults.get(key))
                self.overridden.discard(key)
                logger.info('control: unset %s (the restart re-applies the configured value)', key)
                return 'note restart required (startup-only knob)'
            if key is None or rest or key not in self.defaults:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            try:
                shown = self._apply(key, self.defaults[key])
            except ValueError as e:
                return 'err %s' % e
            self.overridden.discard(key)
            logger.info('control: unset %s -> ok %s=%s', key, key, shown)
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if cmd.startswith('set'):
            args = cmd.split()[1:]
            if len(args) < 2:
                return 'err set needs a setting and a value (try help)'
            key, rest = match_setting_path(args, SET_BY_NAME)   # the knobs: the show reports are not settable (and a show path never shadows a knob value)
            if key is None:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            if not rest:
                return 'err set needs a setting and a value (try help)'
            s = SET_BY_NAME.get(key)
            if s is not None and s.restart and s.secret:
                return 'err restart required (startup-only knob)'   # a secret cannot ride the reload state
            value = ' '.join(rest)
            if value == SECRET_REMOVED and getattr(s, 'secret', False):
                return 'err *** SECRET REMOVED *** is not a value — pass the secret by flag/env, or as file:<path>'
            try:
                shown = self._apply(key, value)
            except ValueError as e:
                return 'err %s' % e
            self.overridden.add(key)
            logger.info('control: set %s=%s', key, shown)
            if s is not None and s.restart:   # the value is recorded; the restart applies it — a note, not a verdict
                return 'note restart required (startup-only knob)'
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if low == 'show connections':
            return 'ok connections ' + self.connections_line()
        if low == 'show cache-all':
            return self.cache_all_report()
        if low == 'show uplink':
            return self.uplink_report()
        if low == 'show cache':
            return 'ok ' + self.cache_line()
        if low == 'show version':
            return 'ok modbus-cache %s' % version_string()
        if low in ('show config', 'show config all'):   # 'all' rides along: the script IS the full config
            return self.show_config()
        if low == 'show knobs':
            return self.knobs_dictionary()
        if low == 'show write-registers-profile':
            return self.write_registers_profile_report()
        if low == 'show connect-acl-table':
            return self.acl_table_report('connect')
        if low == 'show write-acl-table':
            return self.acl_table_report('write')
        if low == 'show metrics-acl-table':
            return self.acl_table_report('metrics')
        if low.startswith('show'):
            args = cmd.split()[1:]
            if not args:   # the bare `show`: the walk's first position, the ? output byte for byte
                return 'ok %s' % describe_root(OPTIONS, SHOW_OPTIONS,
                                               hidden_words=() if self.proxy.dump_path else ('dump-interval',))
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                opt = OPTION_BY_LIVE.get(key)
                if opt is not None and opt.secret:
                    return 'err %s is a secret — it never shows (pass it by flag/env, or as file:<path>)' % key
                word = SHOW_BY_LIVE.get(key)
                if word:
                    return self.command('show ' + word)   # a show command's report, by its word
                if key == 'dump-interval' and not self.proxy.dump_path:
                    return 'err dump-interval needs a dump path (set dump/path or --dump-path)'
                return 'ok %s=%s' % (key, self._get(key))
            if key is not None and rest:
                return 'err %s: unexpected %s' % (key, ' '.join(rest))
            node_path = '/'.join(w.lower() for w in args)   # the walk the ? offers: every word of the path answers
            if node_path in NODE_BY_NAME:
                return 'ok %s' % describe_node(OPTIONS, node_path)
            if len(args) == 1:
                return 'err unknown setting %s (try help)' % args[0].lower()
        if low == 'inspect':
            return self.inspect()
        if low == 'request clear cache':
            dropped = self.proxy.cache.clear()
            self.proxy.poll_wake.set()
            logger.info('control: cache cleared (%d register word(s) dropped), repolling now', dropped)
            return 'ok cache cleared (%d register word(s) dropped), repolling now' % dropped
        if low == 'request dump':
            return self.dump_state(self.proxy.dump_with_cache)
        if low == 'request dump with-cache':
            return self.dump_state(True)
        if low == 'request restore':
            return self.restore_state()
        if low == 'request restart':
            with self.proxy.upstream.lock:
                self.proxy.upstream.close()
            dropped = self.proxy.cache.clear()
            self.proxy.poll_wake.set()
            logger.info('control: upstream session restarted (connection dropped, %d register word(s) dropped, repolling now)',
                        dropped)
            return 'ok upstream session restarted (connection dropped, %d register word(s) dropped, repolling now)' % dropped
        if low == 'request reload':
            return self.reload_daemon()
        if low == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        return 'err unknown command %r (try help)' % cmd

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
                raise ValueError('restart required (startup-only knob)')
            if key == 'modbus/upstream':
                try:
                    host, port = parse_upstream(val, label='modbus/upstream')
                except SystemExit as e:
                    raise ValueError(str(e))
                self.defaults[key] = '%s:%d' % (host, port)
                return self.defaults[key]
            if key in ('system/listen', 'metrics/listen'):
                try:
                    t = parse_listen(val)
                except SystemExit as e:
                    raise ValueError(str(e))
                if key == 'metrics/listen':   # fail fast: the bind at restart is too late to complain
                    probe = socket.socket()
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        probe.bind(t)
                    except OSError as e:
                        raise ValueError('cannot bind %s:%d: %s' % (t[0], t[1], e))
                    finally:
                        probe.close()
                    if p.metrics_srv is not None and not p.metrics_token and not is_loopback_host(t[0]):
                        raise ValueError('metrics/listen cannot move beyond loopback while the endpoint '
                                         'serves without a token (F13 in docs/AUDIT.md) — '
                                         'pass metrics-token by flag/env/config and restart')
                self.defaults[key] = '%s:%d' % t
                return self.defaults[key]
            if key == 'dump/restore-on-start':
                if val not in ('on', 'true', '1', 'yes', 'off', 'false', '0', 'no'):
                    raise ValueError('dump/restore-on-start must be on or off')
                self.defaults[key] = 'on' if val in ('on', 'true', '1', 'yes') else 'off'
                return self.defaults[key]
            raise ValueError('unknown setting %s' % key)

        if key == 'modbus/interval':
            v = num(val, 'interval', 'seconds')
            if not 0 < v <= 86400:
                raise ValueError('interval must be 0 < N <= 86400 seconds')
            p.interval = v
            p.config['interval'] = v   # the live overrides ride show config (show_config_cfg's contract)
            p.poll_wake.set()
            return secs(v)
        if key == 'cache/ttl':
            if val in ('off', 'none', '0'):
                p.cache.cache_ttl = 0
                p.config['cache_ttl'] = 0
                return 'off'
            v = num(val, 'ttl', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.cache.cache_ttl = v
            p.config['cache_ttl'] = v
            return secs(v)
        if key == 'modbus/read-delay':
            v = num(val, 'read-delay', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.read_delay = v
            p.config['read_delay'] = v
            return secs(v)
        if key == 'modbus/merge-gap':
            v = numi(val, 'merge-gap', 'registers')
            self._gate_range(key, v, 'registers')
            p.merge_gap = v
            p.config['merge_gap'] = v
            p.blocks = build_blocks(p.cache.ranges, v)
            p.poll_wake.set()
            return '%d' % v
        if key == 'modbus/unit':
            v = numi(val, 'unit', 'unit id')
            self._gate_range(key, v)
            p.upstream.unit = v
            p.upstream.close()   # the in-flight session spoke the old unit
            p.config['unit'] = v
            return '%d' % v
        if key == 'modbus/auth':
            try:
                v = parse_auth_type(val, 'modbus/auth')
            except SystemExit as e:
                raise ValueError(str(e))
            if v and not p.config.get('auth_key'):
                raise ValueError('the suite auth needs a key: pass auth-key by flag/env/config '
                                 '(min %d characters) and restart' % AUTH_MIN_KEY)
            p.config['auth'] = v   # the next connection handshakes; the standing ones keep their session
            return v or 'none'
        if key == 'modbus/auth-upstream':
            try:
                v = parse_auth_type(val, 'modbus/auth-upstream', schemes=('suite', 'waveshare'))
            except SystemExit as e:
                raise ValueError(str(e))
            standing = p.config.get('auth_upstream_key')
            if v and not standing:
                raise ValueError('the %s auth needs a key: pass auth-upstream-key by flag/env/config and restart%s'
                                 % (v, ' (min %d characters)' % AUTH_MIN_KEY if v == 'suite' else ''))
            if v and standing is not None:
                err = auth_key_floor_error(v, standing)
                if err:
                    raise ValueError('the %s auth rejects the standing key (modbus/auth-upstream-key %s) — '
                                     'pass auth-upstream-key by flag/env/config and restart' % (v, err))
            p.config['auth_upstream'] = v
            p.upstream.auth = v
            p.upstream.close()   # the session re-proves the new scheme on the next exchange
            return v or 'none'
        if key == 'write/allow':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('allow-write must be on or off')
            p.allow_write = on
            p.config['allow_write'] = on
            return 'on' if on else 'off'
        if key == 'write/registers':
            try:
                p.set_write_registers(parse_write_registers(val, 'write-registers'))
            except SystemExit as e:
                raise ValueError(str(e))
            p.config['write_registers'] = p.write_registers
            shown = p.describe_write_ranges()
            if p.write_gate_warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % p.write_gate_warn
            return shown
        if key == 'limits/max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            p.max_clients = v
            p.config['max_clients'] = v
            return '%d' % v
        if key == 'limits/client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.client_timeout = v
            p.config['client_timeout'] = v
            return secs(v)
        if key == 'limits/max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            p.conn_gate.max_per_ip = v
            p.config['max_conn_per_ip'] = v
            return '%d' % v
        if key == 'control/port':
            try:
                target = parse_control_target(val, DEFAULT_LISTEN_PORT, CONTROL_SOCKET_TEMPLATE)
            except SystemExit as e:
                raise ValueError(str(e))
            if val in ('off', 'none', '0'):
                target = None
            if target is not None and not self.stopped and self._is_target(target):
                return self.describe()   # the same target: nothing to rebind
            self.refuse_tokenless_rebind(target)
            shown = self._rebind_control(target)
            p.config['control_port'] = '0' if target is None else str(target)
            return shown
        if key == 'control/ops/verbs':
            verbs = frozenset(v.strip().lower() for v in val.split(',') if v.strip())
            unknown = sorted(v for v in verbs if v not in KNOWN_VERBS)
            if not verbs or unknown:
                raise ValueError('the ops policy needs at least one verb the grammar speaks%s: %s'
                                 % ('' if not unknown else ' (unknown: %s)' % ', '.join(unknown),
                                    ', '.join(sorted(KNOWN_VERBS))))
            self.ops_verbs = verbs
            p.config['control_ops_verbs'] = ','.join(sorted(verbs))
            return ','.join(sorted(verbs))
        if key == 'control/trust-uids':
            try:
                uids = parse_trust_uids('none' if val == 'off' else val, 'control/trust-uids')
            except SystemExit as e:
                raise ValueError(str(e))
            self.trust_uids = uids or frozenset()
            p.config['control_trust_uids'] = self.trust_uids
            return ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
        if key == 'control/socket-group':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('control/socket-group must be on or off')
            self.socket_group = on
            p.config['control_socket_group'] = on
            if self.is_unix and self._srv is not None and os.path.exists(self.sockpath):
                os.chmod(self.sockpath, 0o660 if on else 0o600)   # the live socket re-modes too
            return 'on' if on else 'off'
        if key == 'metrics/enable':
            if val in ('on', 'true', '1', 'yes'):
                if p.metrics_srv:
                    return 'on'
                if not p.metrics_token:
                    host, _port = p.metrics_listen
                    if not is_loopback_host(host):
                        raise ValueError('the metrics endpoint serves register values: refusing to expose '
                                         '/metrics beyond loopback without a token (F13 in docs/AUDIT.md) — '
                                         'pass metrics-token by flag/env/config and restart, or bind '
                                         'metrics/listen on 127.0.0.1')
                srv = MetricsServer(p, p.metrics_listen, token=p.metrics_token,
                                    max_clients=p.metrics_caps[0], client_timeout=p.metrics_caps[1],
                                    max_per_ip=p.metrics_caps[2])
                try:
                    srv.start()
                except SystemExit:
                    host, port = p.metrics_listen
                    raise ValueError('cannot bind %s:%d: %s' % (host, port, srv.bind_error))
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
            raise ValueError('metrics enable must be on or off')
        if key == 'metrics/limits/max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            p.metrics_caps = (v, p.metrics_caps[1], p.metrics_caps[2])
            p.config['metrics_max_clients'] = v
            if p.metrics_srv:
                p.metrics_srv.max_clients = v
                p.metrics_srv._http.gate.max_total = v   # the gate reads its caps per admit
            return '%d' % v
        if key == 'metrics/limits/timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            p.metrics_caps = (p.metrics_caps[0], v, p.metrics_caps[2])
            p.config['metrics_client_timeout'] = v
            if p.metrics_srv:
                p.metrics_srv.client_timeout = v
                p.metrics_srv._Handler.timeout = v or 5   # 0 = the built-in slowloris cap
            return secs(v)
        if key == 'metrics/limits/max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            p.metrics_caps = (p.metrics_caps[0], p.metrics_caps[1], v)
            p.config['metrics_max_conn_per_ip'] = v
            if p.metrics_srv:
                p.metrics_srv.max_per_ip = v
                p.metrics_srv._http.gate.max_per_ip = v
            return '%d' % v
        if key == 'audit/log-file':
            if val in ('off', 'none'):
                p.audit_params['disabled'] = True
                p.config['audit_log'] = ''
                p.config['no_audit_log'] = True
                self._rebuild_audit()
                return 'off'
            p.audit_params['path'] = None if val in ('-', 'stdout') else val
            p.audit_params['disabled'] = False
            p.config['audit_log'] = '' if p.audit_params['path'] is None else val
            p.config['no_audit_log'] = False
            self._rebuild_audit()
            return p.audit.path if p.audit else 'off'
        if key == 'audit/rotate/max-size':
            v = num(val, 'max-size', 'MB')
            self._gate_range(key, v, 'MB')
            p.audit_params['max_mb'] = v
            p.config['audit_max_mb'] = v
            self._rebuild_audit()
            return '%g' % v
        if key == 'audit/rotate/daily':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('audit/rotate/daily must be on or off')
            p.audit_params['daily'] = on
            p.config['audit_daily'] = on
            self._rebuild_audit()
            return 'on' if on else 'off'
        if key == 'audit/rotate/files':
            v = numi(val, 'files', 'backups')
            self._gate_range(key, v, 'backups')
            p.audit_params['files'] = v
            p.config['audit_files'] = v
            self._rebuild_audit()
            return '%d' % v
        if key == 'audit/disable':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('audit/disable must be on or off')
            p.audit_params['disabled'] = on
            p.config['no_audit_log'] = on
            self._rebuild_audit()
            return 'on' if on else 'off'
        if key == 'audit/requests':
            if val in ('off', 'none', '0'):
                p.requests_audit_s = 0
                p.config['requests_audit_s'] = 0
                return 'off'
            v = num(val, 'requests-audit', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            p.requests_audit_s = v
            p.config['requests_audit_s'] = v
            return secs(v)
        if key == 'dump-interval':
            if not p.dump_path:
                raise ValueError('dump-interval needs a dump path (set dump/path or --dump-path)')
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
        if key == 'dump/path':
            if val in ('off', 'none', ''):
                p.dump_path = None
                p.config['dump_path'] = ''
                return 'off'
            p.dump_path = val   # the dump loop, request dump and the shutdown write it from here on
            p.config['dump_path'] = val
            # the seal is opt-in: without dump/key the dump stays plaintext — say so, once, where the choice is made
            return val if p.dump_key else '%s (not sealed — set dump/key to encrypt at rest)' % val
        if key == 'dump/with-cache':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('dump/with-cache must be on or off')
            p.dump_with_cache = on
            p.config['dump_with_cache'] = on
            return 'on' if on else 'off'
        if key == 'local-time':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('local-time must be on|off')
            swapped = 0
            for h in logging.getLogger().handlers:
                f = h.formatter
                if f is None or not getattr(f, '_fmt', None):
                    continue
                h.setFormatter(logging.Formatter(f._fmt) if on else UtcFormatter(f._fmt))
                swapped += 1
            if not swapped:
                raise ValueError('no log handler to re-format')
            p.config['local_time'] = on
            return 'on' if on else 'off'
        if key == 'system/log-access':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('system/log-access must be on or off')
            p.log_access = on   # the next connect/disconnect log line picks it up
            p.config['log_access'] = on
            return 'on' if on else 'off'
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in LOG_LEVELS:
                raise ValueError('log-level must be one of %s' % ', '.join(LOG_LEVELS))
            logging.getLogger().setLevel(getattr(logging, lvl))
            p.config['level'] = lvl
            return lvl
        if key == 'modbus/timeout':
            v = num(val, 'timeout', 'seconds')
            if not 0 < v <= 60:
                raise ValueError('timeout must be 0 < N <= 60 seconds')
            p.upstream.timeout = v
            p.config['timeout'] = v
            return secs(v)
        if key == 'acl/connect':
            if val.lower() == 'table':   # the show word is never a value — point at the report
                raise ValueError('"table" is not an acl/connect value — the table is the show: '
                                 'show acl connect table')
            shown = p.set_connect_acl(val)
            if p.connect_acl_warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % p.connect_acl_warn
            return shown
        if key == 'acl/write':
            if val.lower() == 'table':
                raise ValueError('"table" is not an acl/write value — the table is the show: '
                                 'show acl write table')
            shown = p.set_write_acl(val)
            if p.write_acl_warn:
                shown += ' (%s)' % p.write_acl_warn
            return shown
        if key == 'metrics/acl':
            if val.lower() == 'table':   # the show word is never a value — point at the report
                raise ValueError('"table" is not a metrics/acl value — the table is the show: '
                                 'show metrics acl table')
            shown = p.set_metrics_acl(val)
            if p.metrics_acl_warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % p.metrics_acl_warn
            return shown
        if key in ('modbus/profile', 'modbus/selection'):
            cfg = self._live_cfg()
            if key == 'modbus/profile':
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
            return cfg['profile'] if key == 'modbus/profile' else (cfg['selection'] or 'all')
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

    def _rebuild_audit(self):
        """Swap the CACHE audit trail for one rebuilt from the proxy's audit
        params (the live path/rotation changes): the shared rebuild re-chains
        from the file's own tail, the chain verifiable across the swap. The
        old trail is NOT closed — a session still holding it writes its last
        commands there, and an in-flight writer must never hit a closed file."""
        p = self.proxy
        p.audit = self.rebuild_audit(p.audit_params, 'CACHE', 'modbus-cache')
        self.audit = p.audit   # this server's new sessions (and this one) audit the new trail

    @staticmethod
    def _acl_text(acl):
        """'any' | 'none' | the normalized network list | the file: reference
        (what `unset` re-parses)."""
        return acl_value_text(acl)

    def _get(self, key):
        p = self.proxy
        if key == 'modbus/interval':
            return secs(p.interval)
        if key == 'cache/ttl':
            return 'off' if not p.cache.cache_ttl else secs(p.cache.cache_ttl)
        if key == 'modbus/read-delay':
            return secs(p.read_delay)
        if key == 'modbus/merge-gap':
            return '%d' % p.merge_gap
        if key == 'modbus/unit':
            return '%d' % p.upstream.unit
        if key == 'modbus/auth':
            return p.config.get('auth') or 'none'
        if key == 'modbus/auth-upstream':
            return p.config.get('auth_upstream') or 'none'
        if key == 'write/allow':
            return 'on' if p.allow_write else 'off'
        if key == 'write/registers':
            return p.describe_write_ranges()
        if key == 'limits/max-clients':
            return '%d' % p.max_clients
        if key == 'limits/client-timeout':
            return 'none' if not p.client_timeout else secs(p.client_timeout)
        if key == 'limits/max-conn-per-ip':
            return '%d' % p.conn_gate.max_per_ip
        if key == 'control/port':
            return 'off' if self.stopped else self.describe()
        if key == 'control/ops/verbs':
            return ','.join(sorted(self.ops_verbs)) or 'off'
        if key == 'control/trust-uids':
            return ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
        if key == 'control/socket-group':
            return 'on' if self.socket_group else 'off'
        if key == 'metrics/enable':
            return 'on' if p.metrics_srv else 'off'
        if key == 'metrics/limits/max-clients':
            return '%d' % p.metrics_caps[0]
        if key == 'metrics/limits/timeout':
            return secs(p.metrics_caps[1])
        if key == 'metrics/limits/max-conn-per-ip':
            return '%d' % p.metrics_caps[2]
        if key == 'audit/log-file':
            return p.audit.path if p.audit else 'off'
        if key == 'audit/rotate/max-size':
            return '%g' % p.audit_params['max_mb']
        if key == 'audit/rotate/daily':
            return 'on' if p.audit_params['daily'] else 'off'
        if key == 'audit/rotate/files':
            return '%d' % p.audit_params['files']
        if key == 'audit/disable':
            return 'on' if p.audit_params['disabled'] else 'off'
        if key == 'dump/path':
            return p.dump_path or 'off'
        if key == 'dump/with-cache':
            return 'on' if p.dump_with_cache else 'off'
        if key == 'audit/requests':
            return 'off' if not p.requests_audit_s else secs(p.requests_audit_s)
        if key == 'dump-interval':
            return 'off' if not p.dump_interval else secs(p.dump_interval)
        if key == 'local-time':
            for h in logging.getLogger().handlers:
                f = h.formatter
                if f is not None and getattr(f, '_fmt', None):
                    return 'off' if isinstance(f, UtcFormatter) else 'on'
            return 'off'
        if key == 'system/log-access':
            return 'on' if p.log_access else 'off'
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        if key == 'modbus/timeout':
            return secs(p.upstream.timeout)
        if key == 'acl/connect':
            return self._acl_text(p.connect_acl)
        if key == 'acl/write':
            return self._acl_text(p.write_acl)
        if key == 'metrics/acl':
            return self._acl_text(p.metrics_acl)
        if key == 'modbus/profile':
            return p.config.get('profile') or p.profile
        if key == 'modbus/selection':
            return p.config.get('selection') or 'all'
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

    def clear_overrides(self):
        """The config was re-applied (SIGHUP): nothing is live-overridden anymore."""
        self.overridden.clear()

    def summary(self):
        """The compact state summary appended to the set/unset replies."""
        p = self.proxy
        now = time.monotonic()
        age = 'never' if p.last_ok is None else secs(max(0, now - p.last_ok))
        return ('upstream=%s:%d interval=%s ttl=%s poll=%s last-poll=%s hits=%d misses=%d clients=%d'
                % (p.upstream.host, p.upstream.port, secs(p.interval), secs(p.cache.cache_ttl),
                   'ok' if p.poll_ok else 'down', age, p.cache_hits, p.cache_misses, p.client_count))

    def connections_line(self):
        with self.proxy.client_lock:
            if not self.proxy.clients:
                return 'none'
            now = time.monotonic()
            return '; '.join('%s connected %s requests %d' % (k, secs(now - v['since']), v['requests'])
                             for k, v in sorted(self.proxy.clients.items()))

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
                                                                                       p.config.get('auth_upstream') or 'none',
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

    def write_registers_profile_report(self):
        """The write/registers/profile show report (the show-only view of
        the write gate): 'allow any' when the knob is any, 'deny any' when
        it is none; a range list renders as its whitelist — 'deny any' and
        one allow line per range; a string knob ('profile' or the
        'file:<path>' acl) renders the gate's own rules — the gate's desc
        as the '% ' line, then one '<verb> <range> # <desc>' line per
        range, the comments aligned (the live gate: the rules the running
        gate resolved from, not the file's current state)."""
        p = self.proxy
        lines = ['ok write-registers-profile']
        wr = p.write_registers
        if wr is None:
            lines.append('allow any')
        elif isinstance(wr, str):   # 'profile' or the file:<path> acl reference
            if p.write_gate_rules is None:
                return 'err write/registers/profile: the gate is not resolved'
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
        SECRET_REMOVED placeholder occurs; the dump filter's secret branch
        stays as the class invariant's guard."""
        p = self.proxy
        prm = p.audit_params
        raw = {
            'modbus/interval': p.interval, 'cache/ttl': p.cache.cache_ttl,
            'modbus/read-delay': p.read_delay,
            'modbus/merge-gap': p.merge_gap, 'write/allow': 'on' if p.allow_write else 'off',
            'write/registers': p.describe_write_ranges(), 'limits/max-clients': p.max_clients,
            'limits/client-timeout': p.client_timeout, 'limits/max-conn-per-ip': p.conn_gate.max_per_ip,
            'metrics/enable': 'on' if p.metrics_srv else 'off',
            'metrics/listen': '%s:%d' % p.metrics_listen,
            'metrics/limits/max-clients': p.metrics_caps[0],
            'metrics/limits/timeout': p.metrics_caps[1],
            'metrics/limits/max-conn-per-ip': p.metrics_caps[2],
            'audit/requests': p.requests_audit_s,
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'modbus/profile': p.config.get('profile'), 'modbus/selection': p.config.get('selection') or 'all',
            'acl/connect': self._acl_text(p.connect_acl), 'acl/write': self._acl_text(p.write_acl),
            'metrics/acl': self._acl_text(p.metrics_acl),
            'modbus/auth': p.config.get('auth') or 'none',
            'modbus/auth-upstream': p.config.get('auth_upstream') or 'none',
            'modbus/upstream': '%s:%d' % (p.upstream.host, p.upstream.port),
            'modbus/unit': p.upstream.unit,
            'modbus/timeout': p.upstream.timeout, 'dump-interval': p.dump_interval,
            'local-time': self._get('local-time'),
            'control/port': 'off' if self.stopped else (str(self.port) if not self.is_unix else self.sockpath),
            'control/ops/verbs': ','.join(sorted(self.ops_verbs)) or 'off',
            'control/trust-uids': ','.join(str(u) for u in sorted(self.trust_uids)) or 'off',
            'control/socket-group': 'on' if self.socket_group else 'off',
            'audit/log-file': (p.audit.path if p.audit else 'off'),
            'audit/rotate/max-size': '%g' % prm['max_mb'],
            'audit/rotate/daily': 'on' if prm['daily'] else 'off',
            'audit/rotate/files': '%d' % prm['files'],
            'audit/disable': 'on' if prm['disabled'] else 'off',
            'dump/path': p.dump_path or 'off',
            'dump/with-cache': 'on' if p.dump_with_cache else 'off',
            'dump/restore-on-start': 'on' if getattr(p, 'restore_on_start', False) else 'off',
        }
        for opt in OPTIONS:   # a restart-marked knob speaks its CONFIGURED value (the pending override), not the running one
            if opt.restart and not opt.secret and opt.live and opt.live in self.defaults:
                raw[opt.live] = self.defaults[opt.live]
        return dump_filter(self.overridden, raw, SETTING_BY_NAME)

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


    def dump_state(self, with_cache):
        """The write-behind: the live setting overrides and — when
        with_cache (the `request dump with-cache` command, the
        `--dump-with-cache` default or the dump-interval loop) — the cached
        words (+ stamps), to the configured dump path — sealed when
        dump/key is configured."""
        path = self.proxy.dump_path
        if not path:
            return 'err no dump path configured (set dump/path or --dump-path)'
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
            return 'err no dump path configured (set dump/path or --dump-path)'
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

    def uplink_report(self):
        """The inverter link: the session counters (connects, exchanges,
        bytes, errors) and one row per poll block with its status, latency
        and last error — for analysing what the upstream connection does."""
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
        for fc, start, count, _leaves in p.blocks:
            s = p.block_stats.get((fc, start, count))
            if s is None:
                cells.append(('fc%d' % fc, '%d:%d' % (start, count), 'pending', '-', '-', '-', '0', '-'))
                continue
            if s['last_err'] is None:
                status, err = 'ok', '-'
            elif s['last_code'] is not None:
                status, err = 'ex %d' % s['last_code'], s['last_err']
            else:
                status, err = 'error', s['last_err']
            cells.append(('fc%d' % fc, '%d:%d' % (start, count), status, secs(s['last']),
                          secs(s['sum'] / s['ok_n']) if s['ok_n'] else '-',
                          secs(s['max']), '%d' % s['fails'], err))
        if cells:
            head = ('fc', 'range', 'status', 'last', 'mean', 'max', 'fails', 'last error')
            widths = [max(len(h), max((len(r[i]) for r in cells), default=0)) for i, h in enumerate(head)]
            rows.append('  '.join(h.ljust(w) for h, w in zip(head, widths)))
            for r in cells:
                rows.append('  '.join(v.ljust(w) for v, w in zip(r, widths)))
        return 'ok uplink\n' + '\n'.join(rows)
