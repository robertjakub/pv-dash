#!/usr/bin/env python3
"""JSON-lines control server for the dashboard: inspect and steer the running
server — show status/connections/version, the live settings (the
connection caps, the log surface, the battery flag), the config reload (the
SIGHUP path), graceful shutdown. One command per line, one reply line. Every
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
import time

from common.human import secs
from common.version import version_string
from common.wiresec import verify_request_mac, sign_reply, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.control import ControlServer as _ControlServer, num, numi
from common.options import control_command, describe_node, describe_root, grouped_rows, match_setting_path
from common.config import parse_secret
from common.dump import SECRET_REMOVED, dump_filter
from .options import OPTIONS, SETTING_BY_NAME, describe_setting, SHOW_BY_LIVE, SHOW_OPTIONS, NODE_BY_NAME, CFG_KEYS
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, LOG_LEVELS

logger = logging.getLogger('dashboard')

# The registry-driven bounds: the row's min/max (inclusive) are the one
# home for a knob's range — the branches parse and plumb, the row gates.
OPTION_BY_LIVE = {o.live: o for o in OPTIONS if o.live}
TYPED_CONVS = (int, float, str)

MAX_LINE = CONTROL_LINE_CAP   # the pre-auth line-buffer cap (drop past it)


class ControlServer(_ControlServer):
    """JSON-lines control socket for the dashboard. The target is either a TCP
    port (bound to 127.0.0.1) or a unix socket path (stale files are
    replaced, unlinked on shutdown). A TCP connection must authenticate with
    the token first when one is configured; the unix socket relies on
    filesystem permissions. A second, read-only token (ops_token) may be
    configured beside the admin token: it authenticates into the show/clear
    verbs only — no set/unset, no request reload-config, no request reload,
    no request dump/restore, no shutdown
    (common/wiresec.py's roles). `stopper` is the graceful-stop callback
    shared with the signal handlers; it runs after the shutdown reply left
    the wire."""

    LOG = logger
    OPTIONS = OPTIONS
    SETTINGS = SETTING_BY_NAME
    WHO = 'the dashboard'
    EXIT_TEXT = 'the dashboard is shutting down'
    RELOAD_TEXT = 'the dashboard is reloading — the daemon restarts with the saved configuration'
    CFG_KEYS = CFG_KEYS   # the registry's knob -> cfg-key renames (show config)

    def __init__(self, httpd, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None, ops_token=None, ops_verbs=None, startup_values=None,
                 config_path=None, dump_path=None, restore_on_start=False, dump_key=None):
        self.httpd = httpd
        super().__init__(target, reloader=reloader, stopper=stopper, audit=audit, token=token,
                         defaults=defaults, trust_uids=trust_uids, ops_token=ops_token,
                         ops_verbs=ops_verbs, config_path=config_path, dump_path=dump_path,
                         restore_on_start=restore_on_start, dump_key=dump_key)
        self.startup_values = startup_values or {}   # the set-grammar form of the startup options (show config)
        self.metrics_srv = None          # set by the entry (the live metrics-server toggle)
        self.metrics_token = None        # the /metrics bearer token (the entry passes it)
        self.metrics_listen = None       # the /metrics bind address (the entry passes it)
        self.metrics_desc = 'off'        # the status/inspect one-liner

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
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                return 'ok %s' % describe_setting(key)
            node_path = '/'.join(w.lower() for w in args)   # a node path spells as words too — the walk the ? offers
            if node_path in NODE_BY_NAME:
                return 'ok %s' % describe_node(OPTIONS, node_path)
            if args:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            return 'ok ' + self.command_help()
        if low == '?':
            return 'ok ' + self.command_help()
        if low == 'quit':
            return 'bye'
        if low == 'ping':                 # keep-alive from dashboard_ctl
            return 'ok pong'
        if cmd.startswith('unset'):
            args = cmd.split()[1:]
            if not args:
                return 'err unset needs a setting (try help)'
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest and getattr(SETTING_BY_NAME.get(key), 'restart', False):
                return 'err restart required (startup-only knob)'
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
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is None:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            if not rest:
                return 'err set needs a setting and a value (try help)'
            if getattr(SETTING_BY_NAME.get(key), 'restart', False):
                return 'err restart required (startup-only knob)'
            value = ' '.join(rest)
            if value == SECRET_REMOVED and getattr(SETTING_BY_NAME.get(key), 'secret', False):
                return 'err *** SECRET REMOVED *** is not a value — pass the secret by flag/env, or as file:<path>'
            try:
                shown = self._apply(key, value)
            except ValueError as e:
                return 'err %s' % e
            self.overridden.add(key)
            logger.info('control: set %s=%s', key, shown)
            return 'ok %s=%s %s' % (key, shown, self.summary())
        if low == 'show status':
            return self.status_report()
        if low == 'show connections':
            return 'ok connections ' + self.connections_line()
        if low == 'show version':
            return 'ok dashboard %s' % version_string()
        if low in ('show config', 'show config all'):   # 'all' rides along: the script IS the full config
            return self.show_config()
        if low == 'show knobs':
            return self.knobs_dictionary()
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
        if low == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        return 'err unknown command %r (try help)' % cmd

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, unset <setting>, inspect, '
                'show <setting|status|connections|version|config|knobs>, request reload-config')
        if self.dump_path:
            cmds += ', request dump, request restore'
        cmds += ', request reload, shutdown, quit; '
        cmds += 'help <setting> describes it, help config maps every knob to its control command, '
        cmds += 'show knobs prints the full dictionary'
        return cmds

    def show_config_cfg(self):
        """The resolved startup values with the metrics-server knob's LIVE
        state folded in (the dashboard's own endpoint runs on and off — the
        row renders what runs, not what the startup flag said)."""
        return dict(self.startup_values or {}, metrics_server=bool(self.metrics_srv))

    def _apply(self, key, value):
        """Apply a live setting; returns the display string or raises
        ValueError (the message becomes the err reply)."""
        val = str(value).strip()

        if key == 'max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            self.httpd.gate.max_total = v
            return '%d' % v
        if key == 'client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            self.httpd.RequestHandlerClass.timeout = v or None
            return secs(v)
        if key == 'max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            self.httpd.gate.max_per_ip = v
            return '%d' % v
        if key == 'log-access':
            if val not in ('on', 'off', 'true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError('log-access must be on or off')
            on = val in ('on', 'true', '1', 'yes')
            self.httpd.RequestHandlerClass.log_access = on
            return 'on' if on else 'off'
        if key == 'log-queries':
            if val not in ('on', 'off', 'true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError('log-queries must be on or off')
            on = val in ('on', 'true', '1', 'yes')
            self.httpd.RequestHandlerClass.log_queries = on
            return 'on' if on else 'off'
        if key == 'battery':
            if val not in ('on', 'off', 'true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError('battery must be on or off')
            on = val in ('on', 'true', '1', 'yes')
            self.httpd.RequestHandlerClass.battery = on
            return 'on' if on else 'off'
        if key == 'metrics-server':
            from .statics import DEFAULT_METRICS_CAPS
            if val in ('on', 'true', '1', 'yes'):
                if self.metrics_srv:
                    return 'on'
                if not self.metrics_token:
                    raise ValueError('the metrics endpoint serves the request counters: '
                                     'set --metrics-token first (or file:<path>) (F6 in docs/AUDIT.md)')
                from .metrics import MetricsServer, describe_metrics
                listen = self.metrics_listen
                caps = DEFAULT_METRICS_CAPS
                srv = MetricsServer(self.httpd, listen, token=self.metrics_token,
                                    max_clients=caps[0], client_timeout=caps[1], max_per_ip=caps[2])
                srv.start()
                self.metrics_srv = srv
                self.metrics_desc = describe_metrics(listen, self.metrics_token, caps[0], caps[2])
                return 'on'
            if val in ('off', 'false', '0', 'no'):
                if self.metrics_srv:
                    self.metrics_srv.stop()
                    self.metrics_srv = None
                    self.metrics_desc = 'off'
                return 'off'
            raise ValueError('metrics-server must be on or off')
        if key == 'log-level':
            lvl = val.upper()
            if lvl not in LOG_LEVELS:
                raise ValueError('log-level must be one of %s' % ', '.join(LOG_LEVELS))
            logging.getLogger().setLevel(getattr(logging, lvl))
            return lvl
        if key == 'control/token':
            if val in ('off', 'none', ''):
                if not self.is_unix:
                    raise ValueError('the TCP control port needs its token (F5 in docs/AUDIT.md) — '
                                     'only the unix socket (the filesystem is the auth) may run tokenless')
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
        if key == 'metrics/token':
            if not val or val in ('off', 'none', '0'):
                raise ValueError('metrics/token is mandatory while the endpoint serves (F6 in docs/AUDIT.md) '
                                 '— set the new token')
            try:
                val = parse_secret(val, 'metrics/token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            self.metrics_token = val
            if self.metrics_srv:
                self.metrics_srv.token = val   # the handler reads it per request — the swap is live
            from .metrics import describe_metrics
            caps = self._metrics_caps()
            self.metrics_desc = describe_metrics(self.metrics_listen, val, caps[0], caps[2])
            return '<set>'
        if key == 'dump/path':
            if val in ('off', 'none', ''):
                self.dump_path = None
                return 'off'
            self.dump_path = val   # request dump and the graceful shutdown write it from here on
            # the seal is opt-in: without dump/key the dump stays plaintext — say so, once, where the choice is made
            return val if self.dump_key else '%s (not sealed — set dump/key to encrypt at rest)' % val
        if key == 'dump/restore-on-start':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('dump/restore-on-start must be on or off')
            self.dump_restore = on   # prospective: the START behaviour this session already chose stands
            return 'on' if on else 'off'
        raise ValueError('unknown setting %s' % key)

    def _metrics_caps(self):
        """The caps the describe line renders: the running server's when it
        is up, the defaults otherwise."""
        from .statics import DEFAULT_METRICS_CAPS
        return ((self.metrics_srv.max_clients, self.metrics_srv.client_timeout, self.metrics_srv.max_per_ip)
                if self.metrics_srv else DEFAULT_METRICS_CAPS)

    def _get(self, key):
        h = self.httpd.RequestHandlerClass
        if key == 'max-clients':
            return '%d' % self.httpd.gate.max_total
        if key == 'client-timeout':
            ct = h.timeout
            return 'off' if not ct else secs(ct)
        if key == 'max-conn-per-ip':
            return '%d' % self.httpd.gate.max_per_ip
        if key == 'log-access':
            return 'on' if h.log_access else 'off'
        if key == 'log-queries':
            return 'on' if h.log_queries else 'off'
        if key == 'battery':
            return 'on' if h.battery else 'off'
        if key == 'metrics-server':
            return 'on' if self.metrics_srv else 'off'
        if key == 'control/token':
            return '<set>' if self.token else 'off'   # the secret never renders
        if key == 'control/ops/token':
            return '<set>' if self.ops_token else 'off'   # the secret never renders
        if key == 'metrics/token':
            return '<set>' if self.metrics_token else 'off'   # the secret never renders
        if key == 'dump/path':
            return self.dump_path or 'off'
        if key == 'dump/restore-on-start':
            return 'on' if self.dump_restore else 'off'
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

    def clear_overrides(self):
        """The config was re-applied (SIGHUP/request reload-config): nothing is
        live-overridden anymore."""
        self.overridden.clear()

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values. The
        secrets (control/token, the ops token, metrics/token) ride as
        *** SECRET REMOVED ***: the knob renders, the value never lands in
        the file — the restore skips the placeholder and keeps the
        secret's current value."""
        h = self.httpd.RequestHandlerClass
        raw = {
            'battery': 'on' if h.battery else 'off',
            'max-clients': self.httpd.gate.max_total,
            'client-timeout': h.timeout or 0,
            'max-conn-per-ip': self.httpd.gate.max_per_ip,
            'log-access': 'on' if h.log_access else 'off',
            'log-queries': 'on' if h.log_queries else 'off',
            'metrics-server': 'on' if self.metrics_srv else 'off',
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'dump/path': self.dump_path or 'off',
            'dump/restore-on-start': 'on' if self.dump_restore else 'off',
        }
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
        total, _ = self.httpd.gate.snapshot()
        return ('upstream=%s upstream_ok=%s clients=%d'
                % (self.httpd.RequestHandlerClass.upstream,
                   'ok' if self.httpd.RequestHandlerClass.upstream_ok else 'down', total))

    def connections_line(self):
        """The live HTTP clients (the static pages + the proxy): the gate's
        counters, one row per peer IP."""
        total, per_ip = self.httpd.gate.snapshot()
        if not total:
            return 'none'
        rows = ['%d active' % total]
        rows += ['%s: %d' % (ip, n) for ip, n in sorted(per_ip.items())]
        return '; '.join(rows)

    def status_report(self):
        """The status as a compact multi-field report: one stable key=value
        per line (scriptable)."""
        h = self.httpd.RequestHandlerClass
        gate = self.httpd.gate
        rows = [
            'upstream=%s' % h.upstream,
            'upstream_ok=%s' % ('yes' if h.upstream_ok else 'no'),
            'listen=%s:%d' % (self.httpd.server_address[0], self.httpd.server_address[1]),
            'control=%s' % self.describe(),
            'uptime=%s' % secs(time.monotonic() - self.started),
            'clients=%d' % gate.total(),
            'max_clients=%s' % (gate.max_total or 'none'),
            'client_timeout=%s' % (secs(h.timeout) if h.timeout else 'off'),
            'max_conn_per_ip=%s' % (gate.max_per_ip or 'none'),
            'log_access=%s' % ('on' if h.log_access else 'off'),
            'log_queries=%s' % ('on' if h.log_queries else 'off'),
            'battery=%s' % ('on' if h.battery else 'off'),
            'config_js=%s' % h.config_js,
            'overridden=%s' % (','.join(sorted(self.overridden)) or 'none'),
        ]
        return 'ok status\n' + '\n'.join(rows)

    def inspect(self):
        """One pretty dump of everything — the state, the counters, the caps,
        the proxy health: the baton for a bug report."""
        h = self.httpd.RequestHandlerClass
        total, per_ip = self.httpd.gate.snapshot()
        rows = [
            'version   dashboard %s' % version_string(),
            'upstream  %s (%s), proxy %s/*' % (h.upstream, 'ok' if h.upstream_ok else 'DOWN', h.prom_prefix or '/'),
            'listen    %s:%d, control %s' % (self.httpd.server_address[0], self.httpd.server_address[1],
                                             self.describe()),
            'pages     %s, config.js %s%s' % (h.static_dir, h.config_js,
                                              ', battery on' if h.battery else ''),
            'clients   %d active (limit %s, timeout %s, per-ip %s)'
            % (total, self.httpd.gate.max_total or 'none',
               secs(h.timeout) if h.timeout else 'off',
               self.httpd.gate.max_per_ip or 'none'),
            'auth      none, log access %s, log queries %s' % ('on' if h.log_access else 'off',
                                                               'on' if h.log_queries else 'off'),
            'audit     %s' % ('off' if self.audit is None
                              else (self.audit.path if self.audit.path != '-' else 'stdout')),
            'uptime    %s' % secs(time.monotonic() - self.started),
        ]
        return 'ok inspect\n' + '\n'.join(rows)
