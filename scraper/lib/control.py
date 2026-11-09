#!/usr/bin/env python3
"""JSON-lines control server for modbus-scraper: inspect and steer the
running exporter — show connections/version/config, the live
settings (interval, timeout, the connection caps, the log surface), an
immediate poll, the config reload (the SIGHUP path), the Modbus session
restart, graceful shutdown. One command per line, one reply line. Every
request and reply is one JSON object per line (the stdlib json module): the
request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. TCP connections need a token
auth handshake when --control-token is set ({"cmd": "auth", "token": ...});
the unix socket relies on filesystem permissions plus the peer-cred
shortcut (root, the daemon's own user or --control-trust-uids skips the
handshake). With a token configured the wire is HMAC-signed: every command
and reply carries the full sha256 HMAC of its payload, keyed by the token
(common/wiresec.py) — a token-holding client verifies both directions; over
TCP the signed commands are mandatory. A second, read-only token
(--control-ops-token) authenticates into the show/clear verbs only — the
ops shift against the admin key, both audited."""
import hmac
import logging
import os
import re
import socket
import threading
import time

from common.human import secs
from common.version import version_string
from common.wiresec import verify_request_mac, sign_reply, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.control import ControlServer as _ControlServer, num, numi
from common.options import control_command, describe_node, describe_root, describe_command_node, grouped_rows, \
    match_setting_path
from common.config import acl_table, acl_value_text, default_profile_path, is_loopback_host, parse_auth_type, \
    parse_control_target, parse_listen, parse_secret, parse_upstream, resolve_profile_file
from common.dump import SECRET_REMOVED, dump_filter
from common.modbus import AUTH_MIN_KEY
from common.audit import AuditLog
from common.logutil import UtcFormatter
from .config import CONTROL_SOCKET_TEMPLATE, build_sources, load_device_profile, resolve_metrics_acl
from .metrics import Metrics
from .options import OPTIONS, SETTING_BY_NAME, SET_BY_NAME, describe_setting, SHOW_BY_LIVE, SHOW_OPTIONS, \
    NODE_BY_NAME, KNOWN_VERBS, CFG_KEYS, COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, DEFAULT_LISTEN_PORT, LOG_LEVELS

logger = logging.getLogger('scraper')

SHORT_HELP = 40   # the reports' help column: a display cap, the full text lives in the exposition and the docs


def _short_help(text):
    """One display line: word-boundary-truncated to SHORT_HELP with an
    ellipsis (a dangling open paren trimmed) — never applied to the
    exposition's # HELP lines."""
    if len(text) <= SHORT_HELP:
        return text
    out = ''
    for word in text.split():
        if out and len(out) + 1 + len(word) > SHORT_HELP - 1:
            break
        out = word if not out else '%s %s' % (out, word)
    return out.rstrip(' (=;') + ' …'

MAX_LINE = CONTROL_LINE_CAP   # the pre-auth line-buffer cap (drop past it)

# The registry-driven dispatch: a typed row (int/float/str conv) sets,
# shows and unsets itself — the conv parses, the config key takes it, no
# branch needed. The explicit branches stay first-class for the range
# gates and the runtime plumbing a bare config write cannot reach (the
# client, the gate, the logger); bool/choice knobs keep theirs.
OPTION_BY_LIVE = {o.live: o for o in OPTIONS if o.live}
TYPED_CONVS = (int, float, str)


def _check_upstream(text):
    """The `upstream` row's check: the HOST:PORT shape (the :PORT loopback
    shorthand included), normalized — and the keys derived from the knob
    (the endpoint renders as host:port in the status, the client dials
    host and port separately). Returns the config updates."""
    try:
        host, port = parse_upstream(text, label='modbus/upstream')
    except SystemExit as e:
        raise ValueError(str(e))
    return {'upstream': '%s:%d' % (host, port), 'host': host, 'modbus_port': port}


CHECKS = {'upstream': _check_upstream}

# The hierarchy nodes (`help modbus`): the rows that name a live-path
# prefix and describe the namespace — never knobs, never on the wire
# grammar, help-only.
NODE_BY_NAME = {o.name: o for o in OPTIONS if o.node}


class ControlServer(_ControlServer):
    """JSON-lines control socket for the scraper. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. A second, read-only token (ops_token) may be
    configured beside the admin token: it authenticates into the show/clear
    verbs only — no set/unset, no poll now, no request reload, no reload, no
    restart, no shutdown (common/wiresec.py's roles). `stopper` is the
    graceful-stop callback shared with the signal handlers; it runs after the
    shutdown reply left the wire."""

    LOG = logger
    OPTIONS = OPTIONS
    SETTINGS = SETTING_BY_NAME
    WHO = 'the modbus-scraper'
    CFG_KEYS = CFG_KEYS   # the registry's knob -> cfg-key renames (show config)
    EXIT_TEXT = 'the modbus-scraper is shutting down'
    RELOAD_TEXT = 'the modbus-scraper is reloading — the daemon restarts with the saved configuration'

    def __init__(self, scraper, httpd, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None, socket_group=False, ops_token=None, ops_verbs=None,
                 config_path=None, dump_path=None, restore_on_start=False, dump_key=None,
                 audit_params=None):
        self.scraper = scraper
        self.httpd = httpd
        self.metrics_acl_warn = None   # the metrics/acl file's permission warning (the stash, None = no warning standing)
        self.audit_params = dict(audit_params or {})   # the audit family's live swaps rebuild from these
        super().__init__(target, reloader=reloader, stopper=stopper, audit=audit, token=token,
                         defaults=defaults, trust_uids=trust_uids, socket_group=socket_group,
                         ops_token=ops_token, ops_verbs=ops_verbs, config_path=config_path,
                         dump_path=dump_path, restore_on_start=restore_on_start, dump_key=dump_key)

    def _after_restore(self):
        self.scraper.wake.set()   # the poll loop re-reads the config-driven knobs now

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, unset <setting>, inspect, show <setting|status|connections|'
                'version|config|knobs>, poll now, request reload-config')
        if self.dump_path:
            cmds += ', request dump, request restore'
        cmds += ', request reload, request restart, shutdown, quit; '
        cmds += 'help <setting> describes it, help config maps every knob to its control command, '
        cmds += 'show knobs prints the full dictionary'
        return cmds

    def show_config_cfg(self):
        """The resolved startup config dict — the scraper's live one home."""
        return self.scraper.cfg

    def command(self, cmd):
        cmd = cmd.strip()
        low = cmd.lower()
        if not low:
            return 'err empty command'
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
        if low == 'ping':                 # keep-alive from scraper_ctl
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
        if low == 'show version':
            return 'ok modbus-scraper %s' % version_string()
        if low in ('show config', 'show config all'):   # 'all' rides along: the script IS the full config
            return self.show_config()
        if low == 'show knobs':
            return self.knobs_dictionary()
        if low == 'show inputs-metrics':   # `show inputs metrics` (the live path's words) forwards here
            return self.inputs_metrics_report()
        if low == 'show inputs':
            return self.inputs_report()
        if low == 'show metrics-acl-table':
            return self.acl_table_report()
        if low.startswith('show'):
            args = cmd.split()[1:]
            if not args:   # the bare `show`: the walk's first position, the ? output byte for byte
                return 'ok %s' % describe_root(OPTIONS, SHOW_OPTIONS)
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                opt = OPTION_BY_LIVE.get(key)
                if opt is not None and opt.secret:
                    return 'err %s is a secret — it never shows (pass it by flag/env, or as file:<path>)' % key
                word = SHOW_BY_LIVE.get(key)
                if word:
                    return self.command('show ' + word)   # a show command's report, by its word
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
        if low == 'poll now':
            self.scraper.wake.set()
            logger.info('control: poll now (the loop wakes immediately)')
            return 'ok poll now (the loop wakes immediately, %s)' % self.summary()
        if low == 'request reload-config':
            if not self.reloader:
                return 'err no reloader configured'
            try:
                return 'ok reloaded (%s)' % self.reloader()
            except Exception as e:
                return 'err reload failed: %s' % e
        if low == 'request dump':
            return self.dump_state()
        if low == 'request restore':
            return self.restore_state()
        if low == 'request reload':
            return self.reload_daemon()
        if low == 'request restart':
            self.scraper.client.close()
            logger.info('control: the modbus session dropped (reconnects on the next poll)')
            return 'ok modbus session dropped (reconnects on the next poll)'
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
        (the reload's execv, whose fold reads the state before the start's
        dump-restore decision) applies it. A restart-marked secret refuses:
        it can never ride the reload state."""
        s = self.scraper
        val = str(value).strip()

        rs = SETTING_BY_NAME.get(key)
        if rs is not None and rs.restart:   # a startup-only knob: validate + record the pending value
            if rs.secret:
                raise ValueError('restart required (startup-only knob)')
            if key == 'metrics/listen':
                try:
                    t = parse_listen(val)
                except SystemExit as e:
                    raise ValueError(str(e))
                probe = socket.socket()   # fail fast: the bind at restart is too late to complain
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(t)
                except OSError as e:
                    raise ValueError('cannot bind %s:%d: %s' % (t[0], t[1], e))
                finally:
                    probe.close()
                self.defaults[key] = '%s:%d' % t
                return self.defaults[key]
            if key == 'dump/restore-on-start':
                if val not in ('on', 'true', '1', 'yes', 'off', 'false', '0', 'no'):
                    raise ValueError('dump/restore-on-start must be on or off')
                self.defaults[key] = 'on' if val in ('on', 'true', '1', 'yes') else 'off'
                return self.defaults[key]
            raise ValueError('unknown setting %s' % key)

        if key == 'metrics/interval':
            v = num(val, 'interval', 'seconds')
            if not 0 < v <= 86400:
                raise ValueError('interval must be 0 < N <= 86400 seconds')
            with s.lock:
                s.cfg['interval'] = v
            s.wake.set()
            return secs(v)
        if key == 'modbus/timeout':
            v = num(val, 'timeout', 'seconds')
            if not 0 < v <= 60:
                raise ValueError('timeout must be 0 < N <= 60 seconds')
            with s.lock:
                s.cfg['timeout'] = v
            s.client.apply(timeout=v)
            return secs(v)
        if key == 'modbus/unit':
            v = self._typed(key, val)
            s.client.apply(unit=v)
            return '%d' % v
        if key == 'modbus/auth':
            try:
                v = parse_auth_type(val, 'modbus/auth')
            except SystemExit as e:
                raise ValueError(str(e))
            if v and not s.client.auth_key:
                raise ValueError('the suite auth needs a key: set modbus auth key <value> first '
                                 '(min %d characters)' % AUTH_MIN_KEY)
            with s.lock:
                s.cfg['auth'] = v
            s.client.auth = v
            s.client.close()   # the next poll reconnects — and handshakes when suite is on
            return v or 'none'
        if key == 'modbus/auth/key':
            try:
                v = parse_secret(val, 'modbus/auth/key')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            if v is not None and len(v) < AUTH_MIN_KEY:
                raise ValueError('modbus/auth/key must be at least %d characters, got %d' % (AUTH_MIN_KEY, len(v)))
            with s.lock:
                s.cfg['auth_key'] = v
            s.client.auth_key = v
            s.client.close()   # the session re-proves the new key on the next connect
            return '<set>'
        if key == 'metrics/limits/max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            if not self.httpd:
                raise ValueError('no http server attached')
            self.httpd.gate.max_total = v
            return '%d' % v
        if key == 'metrics/limits/timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            if not self.httpd:
                raise ValueError('no http server attached')
            with s.lock:
                s.cfg['client_timeout'] = v
            self.httpd.RequestHandlerClass.timeout = v or None
            return secs(v)
        if key == 'metrics/limits/max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            if not self.httpd:
                raise ValueError('no http server attached')
            self.httpd.gate.max_per_ip = v
            return '%d' % v
        if key == 'metrics/acl':
            if val.lower() == 'table':   # the show word is never a value — point at the report
                raise ValueError('"table" is not a metrics/acl value — the table is the show: '
                                 'show metrics acl table')
            if not self.httpd:
                raise ValueError('no http server attached')
            try:
                gate, warn = resolve_metrics_acl(val)
            except SystemExit as e:
                raise ValueError(str(e))
            self.metrics_acl_warn = warn   # the fresh state: an inline set clears a standing file warning
            if warn is not None:   # the acl file's permission warning: the log, the audit trail, the reply's suffix
                logger.warning('acl file: %s', warn)
                if self.audit:
                    self.audit.event('ACL-FILE', warn)
            self.httpd.metrics_acl = gate   # the swap is live: the accept check reads it per connection
            with s.lock:
                s.cfg['metrics_acl'] = acl_value_text(gate)
            shown = acl_value_text(gate)
            if warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % warn
            return shown
        if key == 'log-access':
            if val not in ('on', 'off', 'true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError('log-access must be on or off')
            on = val in ('on', 'true', '1', 'yes')
            if self.httpd:
                self.httpd.RequestHandlerClass.log_access = on
            with s.lock:
                s.cfg['log_access'] = on
            return 'on' if on else 'off'
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in LOG_LEVELS:
                raise ValueError('log-level must be one of %s' % ', '.join(LOG_LEVELS))
            logging.getLogger().setLevel(getattr(logging, lvl))
            return lvl
        if key == 'modbus/profile':
            # the register map swaps to the new profile: load it, rebuild the
            # sources, then swap atomically (a bad file rolls everything back)
            path = default_profile_path() if val in ('default', 'auto') else resolve_profile_file(val)
            try:
                profile = load_device_profile(path)
                sources = build_sources(profile, s.spec, path)
            except (ValueError, SystemExit) as e:
                raise ValueError(str(e))
            with s.lock:
                s.cfg['profile'], s.cfg['sources'] = path, sources
            logger.info('control: profile set to %s (the next poll reads the new register map)', path)
            return path
        if key == 'metrics/prefix':
            # the exported names carry the prefix: the spec re-builds (the
            # same files re-read, re-compiled) and swaps atomically — the
            # rename lands with the next poll (woken); a bad spec file
            # rolls back to the old spec
            val = val.strip() or 'huawei'
            if not re.match(r'[A-Za-z_][A-Za-z0-9_]*$', val):
                raise ValueError('invalid metric_prefix = %r: must be a valid metric-name start '
                                 '(letters/digits/underscore, not starting with a digit)' % val)
            try:
                new_spec = Metrics(s.cfg['metrics_spec'], prefix=val)
                profile = load_device_profile(s.cfg['profile'])
                sources = build_sources(profile, new_spec, s.cfg['profile'])
            except (ValueError, SystemExit) as e:
                raise ValueError(str(e))
            with s.lock:
                s.spec, s.cfg['metric_prefix'], s.cfg['sources'] = new_spec, val, sources
            s.wake.set()
            return val
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
            with s.lock:
                s.cfg['control_port'] = '0' if target is None else str(target)
            return shown
        if key == 'control/token':
            if val in ('off', 'none', ''):
                self.refuse_token_drop()
                self.token = None
                return 'off'
            try:
                val = parse_secret(val, 'control/token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            if self.ops_token and hmac.compare_digest(val, self.ops_token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.token = val   # the rotation is live: the sessions re-auth, the macs verify against the new key
            return '<set>'
        if key == 'control/ops/token':
            if val in ('off', 'none', ''):
                self.ops_token = None   # the ops shift signs off; the admin role is untouched
                return 'off'
            try:
                val = parse_secret(val, 'control-ops-token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            if self.token and hmac.compare_digest(val, self.token):
                raise ValueError('the ops token must differ from the admin token (the same secret would hand '
                                 'every holder the role the server picks first)')
            self.ops_token = val
            return '<set>'
        if key == 'control/socket-group':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('control/socket-group must be on or off')
            self.socket_group = on
            if self.is_unix and self._srv is not None and os.path.exists(self.sockpath):
                os.chmod(self.sockpath, 0o660 if on else 0o600)   # the live socket re-modes too
            return 'on' if on else 'off'
        if key == 'metrics/auth/token':
            if val in ('off', 'none', ''):
                host, _port = parse_listen(s.cfg['listen'])
                if not is_loopback_host(host):
                    raise ValueError('metrics/auth/token is mandatory while the listen is non-loopback '
                                     '(F13 in docs/AUDIT.md) — set the new token')
                self.httpd.RequestHandlerClass.auth_token = None
                with s.lock:
                    s.cfg['auth_token'] = None
                return 'off'
            try:
                val = parse_secret(val, 'metrics/auth/token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in val):
                raise ValueError('metrics/auth/token must not contain whitespace or control characters')
            self.httpd.RequestHandlerClass.auth_token = val   # the handler reads it per request — the swap is live
            with s.lock:
                s.cfg['auth_token'] = val
            return '<set>'
        if key == 'dump/path':
            if val in ('off', 'none', ''):
                self.dump_path = None
                return 'off'
            self.dump_path = val   # request dump and the graceful shutdown write it from here on
            # the seal is opt-in: without dump/key the dump stays plaintext — say so, once, where the choice is made
            return val if self.dump_key else '%s (not sealed — set dump/key to encrypt at rest)' % val
        if key == 'audit/log-file':
            if val in ('off', 'none'):
                self.audit_params['disabled'] = True
                return self._rebuild_audit()
            self.audit_params['path'] = val   # the raw spelling: a path, '-' (= stdout) or empty (the XDG state home)
            self.audit_params['disabled'] = False
            return self._rebuild_audit()
        if key == 'audit/rotate/max-size':
            v = num(val, 'max-size', 'MB')
            self._gate_range(key, v, 'MB')
            self.audit_params['max_mb'] = v
            self._rebuild_audit()
            return '%g' % v
        if key == 'audit/rotate/files':
            v = numi(val, 'files', 'backups')
            self._gate_range(key, v, 'backups')
            self.audit_params['files'] = v
            self._rebuild_audit()
            return '%d' % v
        if key == 'audit/disable':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('audit/disable must be on or off')
            self.audit_params['disabled'] = on
            self._rebuild_audit()
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
            with s.lock:
                s.cfg['local_time'] = on
            return 'on' if on else 'off'
        # the generic path: a typed row (int/float/str conv) needs no branch
        # — the row's conv parses, the row's min/max gate, the config key
        # takes the value; the value takes effect wherever the config is
        # next consumed (a client rebuild, a reload)
        opt = OPTION_BY_LIVE.get(key)
        if opt is not None and opt.conv is bool:
            if val not in ('on', 'true', '1', 'yes', 'off', 'false', '0', 'no'):
                raise ValueError('%s must be on or off' % key)
            with s.lock:
                s.cfg[opt.name.replace('-', '_')] = val in ('on', 'true', '1', 'yes')
            return 'on' if val in ('on', 'true', '1', 'yes') else 'off'
        if opt is not None and opt.conv in TYPED_CONVS:
            return str(self._typed(key, val))
        raise ValueError('unknown setting %s' % key)

    def _typed(self, key, val):
        """The registry-driven typed write: the row's conv parses, the
        row's check validates the shape (and hands back the config
        updates — a check normalizes and fills the keys derived from the
        knob), the row's min/max gate, the config keys take the values.
        Returns the canonical display value — the caller adds any
        runtime plumbing a bare config write cannot reach."""
        s = self.scraper
        opt = OPTION_BY_LIVE.get(key)
        try:
            v = opt.conv(val)
        except ValueError:
            raise ValueError('%s must be %s' % (key, {int: 'an integer', float: 'a number'}.get(opt.conv, 'text')))
        if opt.check:
            updates = CHECKS[opt.check](v)
        else:
            if (opt.min is not None and not v >= opt.min) or (opt.max is not None and not v <= opt.max):
                raise ValueError('%s must be %s..%s' % (key, opt.min, opt.max))
            updates = {opt.name.replace('-', '_'): v}
        with s.lock:
            s.cfg.update(updates)
        return updates[opt.name.replace('-', '_')]

    def _get(self, key):
        s = self.scraper
        with s.lock:
            cfg = dict(s.cfg)
        if key == 'metrics/interval':
            return secs(cfg['interval'])
        if key == 'modbus/timeout':
            return secs(cfg['timeout'])
        if key == 'metrics/limits/max-clients':
            return '%d' % (self.httpd.gate.max_total if self.httpd else cfg['max_clients'])
        if key == 'metrics/limits/timeout':
            ct = self.httpd.RequestHandlerClass.timeout if self.httpd else cfg['client_timeout'] or None
            return 'off' if not ct else secs(ct)
        if key == 'metrics/limits/max-conn-per-ip':
            return '%d' % (self.httpd.gate.max_per_ip if self.httpd else cfg['max_conn_per_ip'])
        if key == 'metrics/acl':
            return acl_value_text(self.httpd.metrics_acl) if self.httpd else (cfg['metrics_acl'] or 'any')
        if key == 'log-access':
            return 'on' if (self.httpd.RequestHandlerClass.log_access if self.httpd else cfg['log_access']) else 'off'
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        if key == 'modbus/profile':
            return cfg['profile']
        if key == 'control/port':
            return 'off' if self.stopped else self.describe()
        if key == 'control/token':
            return '<set>' if self.token else 'off'   # the secret never renders
        if key == 'control/ops/token':
            return '<set>' if self.ops_token else 'off'   # the secret never renders
        if key == 'control/socket-group':
            return 'on' if self.socket_group else 'off'
        if key == 'metrics/auth/token':
            return '<set>' if cfg['auth_token'] else 'off'   # the secret never renders
        if key == 'audit/log-file':
            return self.audit.path if self.audit else 'off'
        if key == 'audit/rotate/max-size':
            return '%g' % self.audit_params['max_mb']
        if key == 'audit/rotate/files':
            return '%d' % self.audit_params['files']
        if key == 'audit/disable':
            return 'on' if self.audit_params['disabled'] else 'off'
        if key == 'modbus/auth':
            return cfg.get('auth') or 'none'
        if key == 'metrics/filter':
            return cfg['metrics_spec'] or 'off'
        if key == 'modbus/auth/key':
            return '<set>' if cfg.get('auth_key') else 'none'   # the secret never renders
        if key == 'dump/path':
            return self.dump_path or 'off'
        # the generic path: a registry row with a typed conv reads its
        # config key with no branch at all; a bool row renders on/off
        opt = OPTION_BY_LIVE.get(key)
        if opt is not None and opt.conv is bool and opt.name.replace('-', '_') in cfg:
            return 'on' if cfg[opt.name.replace('-', '_')] else 'off'
        if opt is not None and opt.conv in TYPED_CONVS and opt.name.replace('-', '_') in cfg:
            return str(cfg[opt.name.replace('-', '_')])
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

    def _rebuild_audit(self):
        """Swap the SCR audit trail for one rebuilt from the params (the
        live path/rotation/kill-switch changes): the fresh writer re-chains
        from the file's own tail (common/audit.py tail_hash), so the chain
        stays verifiable across the swap. The old trail is NOT closed — a
        session still holding it writes its last commands there."""
        p = self.audit_params
        if p['disabled']:
            self.audit = None
        else:
            self.audit = AuditLog(p['path'], 'SCR', app='modbus-scraper',
                                  max_mb=p['max_mb'], files=p['files'])
        return self.audit.path if self.audit else 'off'

    def clear_overrides(self):
        """The config was re-applied (SIGHUP/request reload): nothing is
        live-overridden anymore."""
        self.overridden.clear()

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values. The
        secrets (control/token, the ops token, auth/token) ride as
        *** SECRET REMOVED ***: the knob renders, the value never lands in
        the file — the restore skips the placeholder and keeps the
        secret's current value."""
        s = self.scraper
        with s.lock:
            cfg = dict(s.cfg)
        raw = {
            'modbus/upstream': cfg['upstream'],
            'modbus/unit': cfg['modbus_unit'],
            'modbus/offset': cfg['modbus_offset'],
            'modbus/auth': cfg.get('auth') or 'none',
            'modbus/timeout': cfg['timeout'],
            'modbus/profile': cfg['profile'],
            'modbus/battery': 'on' if cfg['battery'] else 'off',
            'modbus/grid-positive-import': 'on' if cfg['grid_positive_import'] else 'off',
            'metrics/interval': cfg['interval'],
            'metrics/filter': cfg['metrics_spec'],
            'metrics/prefix': cfg['metric_prefix'],
            'caps/max-pv': cfg['max_kwp'],
            'caps/max-grid': cfg['max_grid_kw'],
            'metrics/limits/max-clients': cfg['max_clients'],
            'metrics/limits/timeout': cfg['client_timeout'],
            'metrics/limits/max-conn-per-ip': cfg['max_conn_per_ip'],
            'metrics/acl': acl_value_text(self.httpd.metrics_acl) if self.httpd else (cfg['metrics_acl'] or 'any'),
            'log-access': 'on' if cfg['log_access'] else 'off',
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'local-time': self._get('local-time'),
            'control/port': 'off' if self.stopped else (str(self.port) if not self.is_unix else self.sockpath),
            'control/socket-group': 'on' if self.socket_group else 'off',
            'audit/log-file': self.audit.path if self.audit else 'off',
            'audit/rotate/max-size': '%g' % self.audit_params['max_mb'],
            'audit/rotate/files': '%d' % self.audit_params['files'],
            'audit/disable': 'on' if self.audit_params['disabled'] else 'off',
            'dump/path': self.dump_path or 'off',
            'dump/restore-on-start': 'on' if self.dump_restore else 'off',
        }
        for opt in OPTIONS:   # a restart-marked knob speaks its CONFIGURED value (the pending override), not the running one
            if opt.restart and not opt.secret and opt.live and opt.live in self.defaults:
                raw[opt.live] = self.defaults[opt.live]
        return dump_filter(self.overridden, raw, SETTING_BY_NAME)

    # --- the whole-daemon reload (`reload`) and the dump family ride the
    # base (_save/_restore/_reload_state_path/apply_dump_settings/reload_daemon):
    # the state file sits beside the config, the reply leaves the wire, the
    # process re-execs. The fresh daemon re-resolves the config file (the
    # startup-only knobs take their configured values) and re-applies the
    # saved overrides once (start) — the file and the flags stay the owners
    # of the base, the state file is consumed, nothing lingers. ---

    def summary(self):
        """The compact state summary appended to the set/unset replies."""
        s = self.scraper
        age = 'never' if not s.last_poll else secs(time.time() - s.last_poll)
        return ('upstream=%s:%d interval=%s poll=%s last-poll=%s errors=%d'
                % (s.cfg['host'], s.cfg['modbus_port'], secs(s.cfg['interval']),
                   'ok' if s.up else 'down', age, s.errors))

    def connections_line(self):
        """The live HTTP clients of the exposition endpoint: the gate's
        counters, one row per peer IP."""
        total, per_ip = self.httpd.gate.snapshot() if self.httpd else (0, {})
        if not total:
            return 'none'
        rows = ['%d active' % total]
        rows += ['%s: %d' % (ip, n) for ip, n in sorted(per_ip.items())]
        return '; '.join(rows)

    def _aligned(self, rows):
        """[(name, bracket, help)] -> the aligned `name  [bracket]  help`
        lines: the name and bracket columns pad to their widest member, the
        help caps at a word-boundary 40 with an ellipsis (the full text
        lives in the exposition and the docs)."""
        name_w = max(len(name) for name, _bracket, _help in rows)
        brackets = ['[%s]' % bracket if bracket else '' for _name, bracket, _help in rows]
        bracket_w = max(len(bracket) for bracket in brackets)
        return ['%-*s  %-*s  %s' % (name_w, name, bracket_w, bracket, _short_help(help))
                for (name, _bracket, help), bracket in zip(rows, brackets)]

    def inputs_report(self):
        """The declared compute inputs: one aligned `name  [metric]  help`
        line per input the spec's "inputs" section declares (the reserved
        five included) — the bracket names the spec's own metric whose
        value the input carries (pv == the pv-power-bound metric, battery
        == scraper_battery); a profile-fed input's bracket would name
        itself, so it ships bare."""
        mirrors = self.scraper.spec.profile_inputs     # the canonical register -> the spec key it feeds
        rows = []
        for name, decl in sorted(self.scraper.spec.inputs.items()):
            register = decl['register']
            if register is None:
                mirror = 'scraper_battery' if name == 'battery' else None
            else:
                mirror = mirrors.get(register)
            rows.append((name, mirror if mirror and mirror != name else None, decl['help']))
        return 'ok inputs\n' + '\n'.join(self._aligned(rows))

    def inputs_metrics_report(self):
        """The exported metrics: one aligned `name  [section]  help` line
        per metric the exposition serves (the merged spec — the built-in
        scraper_* block included), sorted by name; the bracket is the
        section group the dashboards know (the legacy flat specs' entries
        ship bare)."""
        spec = self.scraper.spec
        rows = [(name, spec.section_of(name) or '', spec.help.get(name, name))
                for name in sorted(spec.specs)]
        return 'ok inputs-metrics\n' + '\n'.join(self._aligned(rows))

    def acl_table_report(self):
        """The metrics/acl/table show report (the show-only view of the
        metrics ACL, one entry per line): the system forms spell the chain
        they implement — 'allow 0.0.0.0/0' (any), 'deny 0.0.0.0/0' (none),
        'deny 0.0.0.0/0' + one allow line per network (the whitelist); a
        file gate renders its own rules — the gate desc as the '% ' line,
        the rule descs as aligned '# ' comments, the matcher 'any' spelled
        0.0.0.0/0 (common/config.py acl_table, the family's one renderer)."""
        if self.httpd:
            acl = self.httpd.metrics_acl
        else:
            with self.scraper.lock:
                text = self.scraper.cfg.get('metrics_acl')
            acl, _warn = resolve_metrics_acl(text or 'any')
        return 'ok metrics-acl-table\n%s' % '\n'.join(acl_table(acl))

    def inspect(self):
        """One pretty dump of everything — the state, the counters, the caps,
        the poll health: the baton for a bug report."""
        s = self.scraper
        now = time.time()
        cfg = s.cfg
        up, values, last_poll, _errors = s.snapshot()
        gate = self.httpd.gate if self.httpd else None
        rows = [
            'version   modbus-scraper %s' % version_string(),
            'upstream  %s:%d unit %d (offset %d), timeout %s, modbus auth %s, last poll %s%s'
            % (cfg['host'], cfg['modbus_port'], cfg['modbus_unit'], cfg['modbus_offset'], secs(cfg['timeout']),
               cfg.get('auth') or 'none',
               'never' if not last_poll else '%s ago' % secs(now - last_poll),
               '' if s.up else ' (FAILING)'),
            'listen    %s, control %s' % (cfg['listen'], self.describe()),
            'profile   %s' % cfg['profile'],
            'poll      interval %s, errors %d, sanity %s'
            % (secs(cfg['interval']), s.errors, 'ok' if not s.error_state() else s.error_state()),
            'values    %s' % ('; '.join('%s=%g' % (k, v) for k, v in sorted(values.items())) or 'none yet'),
            'clients   %d active (limit %s, timeout %s, per-ip %s)'
            % (gate.total() if gate else 0,
               (gate.max_total if gate else cfg['max_clients']) or 'none',
               secs(cfg['client_timeout']) if cfg['client_timeout'] else 'off',
               (gate.max_per_ip if gate else cfg['max_conn_per_ip']) or 'none'),
            'auth      %s, log access %s' % ('bearer' if cfg['auth_token'] else 'none',
                                             'on' if cfg['log_access'] else 'off'),
            'audit     %s' % ('off' if self.audit is None
                              else (self.audit.path if self.audit.path != '-' else 'stdout')),
            'uptime    %s' % secs(time.monotonic() - self.started),
        ]
        return 'ok inspect\n' + '\n'.join(rows)
