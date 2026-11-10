#!/usr/bin/env python3
"""JSON-lines control server for the dashboard: inspect and steer the running
server — show connections/version/config, the live settings (the
connection caps, the log surface), the config reload (the
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
(common/wire/wiresec.py) — a token-holding client verifies both directions; over
TCP the signed commands are mandatory. A second, read-only token
(--control-ops-token) authenticates into the show/clear verbs only — the
ops shift against the admin key, both audited."""
import logging
import os
import time

from common.render.human import secs
from common.runtime.audit import AUDIT_FORWARD_FORMATS, AUDIT_FORWARD_GRAMMAR, parse_forward
from common.runtime.version import version_string
from common.wire.wiresec import verify_request_mac, sign_reply, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.wire.control import ControlServer as _ControlServer, num, numi
from common.settings.config import acl_table, acl_value_text, is_loopback_host, parse_control_target, parse_listen, \
    resolve_metrics_acl
from common.wire.cred import parse_trust_uids
from common.settings.dump import SECRET_REMOVED, dump_filter
from .options import OPTIONS, SETTING_BY_NAME, SET_BY_NAME, SHOW_BY_LIVE, SHOW_OPTIONS, NODE_BY_NAME, CFG_KEYS, \
    COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN, KNOWN_VERBS
from .statics import CONTROL_LINE_CAP, CONTROL_SOCKET_TEMPLATE, DEFAULT_LISTEN_PORT, LOG_LEVELS

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
    (common/wire/wiresec.py's roles). `stopper` is the graceful-stop callback
    shared with the signal handlers; it runs after the shutdown reply left
    the wire."""

    LOG = logger
    OPTIONS = OPTIONS
    SETTINGS = SETTING_BY_NAME
    WHO = 'the dashboard'
    EXIT_TEXT = 'the dashboard is shutting down'
    RELOAD_TEXT = 'the dashboard is reloading — the daemon restarts with the saved configuration'
    CFG_KEYS = CFG_KEYS   # the registry's knob -> cfg-key renames (show config)
    APP = 'dashboard'
    COMMANDS = COMMANDS
    COMMAND_HELP = COMMAND_HELP
    COMMAND_GROUPS = COMMAND_GROUPS
    COMMAND_HIDDEN = COMMAND_HIDDEN
    NODE_BY_NAME = NODE_BY_NAME
    SET_BY_NAME = SET_BY_NAME
    SHOW_BY_LIVE = SHOW_BY_LIVE
    OPTION_BY_LIVE = OPTION_BY_LIVE
    SHOW_OPTIONS = SHOW_OPTIONS
    SHOW_REPORTS = {'show metrics-acl-table': 'acl_table_report'}   # `show metrics acl table` (the live path's words) forwards here — the SHOW_BY_LIVE routing

    def __init__(self, httpd, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None, socket_group=False, ops_token=None, ops_verbs=None,
                 startup_values=None, config_path=None, dump_path=None, restore_on_start=False,
                 dump_key=None, dump_interval=0.0, audit_params=None):
        self.httpd = httpd
        super().__init__(target, reloader=reloader, stopper=stopper, audit=audit, token=token,
                         defaults=defaults, trust_uids=trust_uids, socket_group=socket_group,
                         ops_token=ops_token, ops_verbs=ops_verbs, config_path=config_path,
                         dump_path=dump_path, restore_on_start=restore_on_start, dump_key=dump_key,
                         dump_interval=dump_interval)
        self.startup_values = startup_values or {}   # the set-grammar form of the startup options (show config)
        self.audit_params = dict(audit_params or {})   # the audit family's live swaps rebuild from these
        self.config_path = config_path   # the config script the daemon started from — the reload state lives beside it
        self.reload_pending = False      # a reload saved the state; the exec runs after the reply leaves the wire
        self.dump_path = dump_path or None   # the state dump file (the dump family)
        self.dump_restore = bool(restore_on_start)   # prospective-only: the START already chose
        self.metrics_srv = None          # set by the entry (the live metrics enable toggle)
        self.metrics_token = None        # the /metrics bearer token (the entry passes it)
        self.metrics_listen = None       # the /metrics bind address (the entry passes it)
        self.metrics_acl = None          # the /metrics accept gate (the entry passes it; the hooks read it per connection)
        self.metrics_acl_warn = None     # the metrics/acl file's permission warning (the stash, None = no warning standing)
        self.metrics_caps = None         # the /metrics caps the entry configured (the re-enable reads them — the cache's p.metrics_caps reading)
        self.metrics_desc = 'off'        # the status/inspect one-liner

    def command_help(self):
        """The one-line command reference: the state-dump commands appear
        only when a dump path is configured (there is nothing to dump
        into otherwise)."""
        cmds = ('commands: set <setting> <value>, unset <setting>, inspect, '
                'show <setting|connections|version|config|knobs>, request reload-config')
        if self.dump_path:
            cmds += ', request dump, request restore'
        cmds += ', request reload, shutdown, quit; '
        cmds += 'help <setting> describes it, help config maps every knob to its control command, '
        cmds += 'show knobs prints the full dictionary'
        return cmds

    def show_config_cfg(self):
        """The resolved startup values with the metrics knobs' LIVE state
        folded in (the dashboard's own endpoint runs on and off and its
        acl sets live — the rows render what runs, not what the startup
        flag said)."""
        from common.settings.config import acl_value_text
        return dict(self.startup_values or {}, metrics_server=bool(self.metrics_srv),
                    metrics_acl=acl_value_text(self.metrics_acl))

    def _apply(self, key, value):
        """Apply a live setting; returns the display string or raises
        ValueError (the message becomes the err reply). A restart-marked
        knob records only: the value lands in the configured-value table
        (show renders it, the dump/reload state carries it) — the restart
        (the reload's execv, whose fold reads the state before the start's
        dump-restore decision) applies it. A restart-marked secret refuses:
        it can never ride the reload state."""
        val = str(value).strip()

        rs = SETTING_BY_NAME.get(key)
        if rs is not None and rs.restart:   # a startup-only knob: validate + record the pending value
            if rs.secret:
                raise ValueError('restart required (startup-only knob)')
            if key == 'dump/restore-on-start':
                if val not in ('on', 'true', '1', 'yes', 'off', 'false', '0', 'no'):
                    raise ValueError('dump/restore-on-start must be on or off')
                self.defaults[key] = 'on' if val in ('on', 'true', '1', 'yes') else 'off'
                return self.defaults[key]
            if key == 'system/listen':
                try:
                    t = parse_listen(val)
                except SystemExit as e:
                    raise ValueError(str(e))
                if not self.httpd.RequestHandlerClass.auth_token and not is_loopback_host(t[0]):
                    raise ValueError('system/listen cannot move beyond loopback while the page serves '
                                     'without a token (F21 in docs/AUDIT.md) — pass auth-token by '
                                     'flag/env/config and restart')
                self.defaults[key] = '%s:%d' % t
                return self.defaults[key]
            raise ValueError('unknown setting %s' % key)

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
        if key == 'metrics/enable':
            from .statics import DEFAULT_METRICS_CAPS
            if val in ('on', 'true', '1', 'yes'):
                if self.metrics_srv:
                    return 'on'
                if not self.metrics_token:
                    host, _port = self.metrics_listen
                    if not is_loopback_host(host):
                        raise ValueError('the metrics endpoint serves the request counters: refusing to expose '
                                         '/metrics beyond loopback without a token (F13 in docs/AUDIT.md) — '
                                         'pass metrics-token by flag/env/config and restart, or bind '
                                         'metrics/listen on 127.0.0.1')
                from .metrics import MetricsServer, describe_metrics
                listen = self.metrics_listen
                caps = self.metrics_caps or DEFAULT_METRICS_CAPS   # the CONFIGURED caps (the cache's rebind reading) — not the defaults
                srv = MetricsServer(self.httpd, self, listen, token=self.metrics_token,
                                    max_clients=caps[0], client_timeout=caps[1], max_per_ip=caps[2],
                                    acl=self.metrics_acl)
                try:
                    srv.start()
                except SystemExit:
                    raise ValueError('cannot bind %s:%d: %s' % (listen[0], listen[1], srv.bind_error))
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
        if key == 'audit/rotate/daily':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('audit/rotate/daily must be on or off')
            self.audit_params['daily'] = on
            self._rebuild_audit()
            return 'on' if on else 'off'
        if key == 'audit/forward':
            try:
                parse_forward(val)
            except ValueError:
                raise ValueError('audit/forward must be %s' % AUDIT_FORWARD_GRAMMAR)   # the wire speaks the live name
            self.audit_params['forward'] = None if val in ('', 'none') else val
            self._rebuild_audit()
            return val
        if key == 'audit/forward-format':
            if val not in AUDIT_FORWARD_FORMATS:
                raise ValueError('audit/forward-format must be one of %s' % ', '.join(AUDIT_FORWARD_FORMATS))
            self.audit_params['forward_format'] = val
            self._rebuild_audit()
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
            self.startup_values['control_port'] = '0' if target is None else str(target)
            return shown
        if key == 'control/ops/verbs':
            verbs = frozenset(v.strip().lower() for v in val.split(',') if v.strip())
            unknown = sorted(v for v in verbs if v not in KNOWN_VERBS)
            if not verbs or unknown:
                raise ValueError('the ops policy needs at least one verb the grammar speaks%s: %s'
                                 % ('' if not unknown else ' (unknown: %s)' % ', '.join(unknown),
                                    ', '.join(sorted(KNOWN_VERBS))))
            self.ops_verbs = verbs
            self.startup_values['control_ops_verbs'] = ','.join(sorted(verbs))
            return ','.join(sorted(verbs))
        if key == 'control/trust-uids':
            try:
                uids = parse_trust_uids('none' if val == 'off' else val, 'control/trust-uids')
            except SystemExit as e:
                raise ValueError(str(e))
            self.trust_uids = uids or frozenset()
            self.startup_values['control_trust_uids'] = ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
            return ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
        if key == 'control/socket-group':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('control/socket-group must be on or off')
            self.socket_group = on
            self.startup_values['control_socket_group'] = on
            if self.is_unix and self._srv is not None and os.path.exists(self.sockpath):
                os.chmod(self.sockpath, 0o660 if on else 0o600)   # the live socket re-modes too
            return 'on' if on else 'off'
        if key == 'metrics/acl':
            if val.lower() == 'table':   # the show word is never a value — point at the report
                raise ValueError('"table" is not a metrics/acl value — the table is the show: '
                                 'show metrics acl table')
            try:
                gate, warn = resolve_metrics_acl(val)
            except SystemExit as e:
                raise ValueError(str(e))
            self.metrics_acl_warn = warn   # the fresh state: an inline set clears a standing file warning
            if warn is not None:   # the acl file's permission warning: the log, the audit trail, the reply's suffix
                logger.warning('acl file: %s', warn)
                if self.audit:
                    self.audit.event('ACL-FILE', warn)
            self.metrics_acl = gate   # the swap is live: the accept check reads it per connection
            shown = acl_value_text(gate)
            if warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % warn
            return shown
        if key == 'dump-interval':
            if not self.dump_path:
                raise ValueError('dump-interval needs a dump path (set dump/path or --dump-path)')
            if val in ('off', 'none', '0'):
                self.dump_interval = 0
                self.dump_wake.set()
                return 'off'
            v = num(val, 'dump-interval', 'seconds or off')
            self._gate_range(key, v, 'seconds')
            self.dump_interval = v
            self.dump_wake.set()
            return secs(v)
        if key == 'dump/path':
            if val in ('off', 'none', ''):
                self.dump_path = None
                return 'off'
            self.dump_path = val   # request dump and the graceful shutdown write it from here on
            # the seal is opt-in: without dump/key the dump stays plaintext — say so, once, where the choice is made
            return val if self.dump_key else '%s (not sealed — set dump/key to encrypt at rest)' % val
        raise ValueError('unknown setting %s' % key)

    def _metrics_caps(self):
        """The caps the describe line renders: the running server's when it
        is up, the configured ones otherwise (the defaults only when the
        entry passed nothing)."""
        from .statics import DEFAULT_METRICS_CAPS
        return ((self.metrics_srv.max_clients, self.metrics_srv.client_timeout, self.metrics_srv.max_per_ip)
                if self.metrics_srv else (self.metrics_caps or DEFAULT_METRICS_CAPS))

    def _rebuild_audit(self):
        """Swap the DSH audit trail for one rebuilt from the params (the
        shared rebuild re-chains from the file's own tail). The old trail
        is NOT closed — a session still holding it writes its last
        commands there."""
        self.audit = self.rebuild_audit(self.audit_params, 'DSH', 'dashboard')
        return self.audit.path if self.audit else 'off'

    def _get(self, key):
        h = self.httpd.RequestHandlerClass
        if key == 'max-clients':
            return '%d' % self.httpd.gate.max_total
        if key == 'client-timeout':
            ct = h.timeout
            return 'off' if not ct else secs(ct)
        if key == 'max-conn-per-ip':
            return '%d' % self.httpd.gate.max_per_ip
        if key == 'audit/rotate/daily':
            return 'on' if self.audit_params['daily'] else 'off'
        if key == 'audit/forward':
            return self.audit_params.get('forward') or 'none'
        if key == 'audit/forward-format':
            return self.audit_params.get('forward_format') or 'rfc5424'
        if key == 'log-access':
            return 'on' if h.log_access else 'off'
        if key == 'log-queries':
            return 'on' if h.log_queries else 'off'
        if key == 'metrics/enable':
            return 'on' if self.metrics_srv else 'off'
        if key == 'control/port':
            return 'off' if self.stopped else self.describe()
        if key == 'control/ops/verbs':
            return ','.join(sorted(self.ops_verbs)) or 'off'
        if key == 'control/trust-uids':
            return ','.join(str(u) for u in sorted(self.trust_uids)) or 'off'
        if key == 'control/socket-group':
            return 'on' if self.socket_group else 'off'
        if key == 'metrics/acl':
            return acl_value_text(self.metrics_acl)
        if key == 'dump/path':
            return self.dump_path or 'off'
        if key == 'dump-interval':
            return 'off' if not self.dump_interval else secs(self.dump_interval)
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # the secrets never reach here — the show gate refuses them
        return '?'

    def clear_overrides(self):
        """The config was re-applied (SIGHUP/request reload-config): nothing is
        live-overridden anymore."""
        self.overridden.clear()

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values. No
        secret can be overridden (the wire refuses them — startup-only),
        so no SECRET_REMOVED placeholder occurs; the dump filter's secret
        branch stays as the class invariant's guard."""
        h = self.httpd.RequestHandlerClass
        raw = {
            'max-clients': self.httpd.gate.max_total,
            'client-timeout': h.timeout or 0,
            'max-conn-per-ip': self.httpd.gate.max_per_ip,
            'log-access': 'on' if h.log_access else 'off',
            'log-queries': 'on' if h.log_queries else 'off',
            'metrics/enable': 'on' if self.metrics_srv else 'off',
            'metrics/acl': acl_value_text(self.metrics_acl),
            'log-level': logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            'dump/path': self.dump_path or 'off',
            'dump/restore-on-start': 'on' if self.dump_restore else 'off',
            'dump-interval': self.dump_interval,
            'control/port': 'off' if self.stopped else (str(self.port) if not self.is_unix else self.sockpath),
            'control/ops/verbs': ','.join(sorted(self.ops_verbs)) or 'off',
            'control/trust-uids': ','.join(str(u) for u in sorted(self.trust_uids)) or 'off',
            'control/socket-group': 'on' if self.socket_group else 'off',
            'audit/forward': self.audit_params.get('forward') or 'none',
            'audit/forward-format': self.audit_params.get('forward_format') or 'rfc5424',
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

    def acl_table_report(self):
        """The metrics/acl/table show report (the show-only view of the
        metrics ACL, one entry per line): the system forms spell the chain
        they implement — 'allow 0.0.0.0/0' (any), 'deny 0.0.0.0/0' (none),
        'deny 0.0.0.0/0' + one allow line per network (the whitelist); a
        file gate renders its own rules — the gate desc as the '% ' line,
        the rule descs as aligned '# ' comments, the matcher 'any' spelled
        0.0.0.0/0 (common/settings/config.py acl_table, the family's one renderer)."""
        return 'ok metrics-acl-table\n%s' % '\n'.join(acl_table(self.metrics_acl))

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
            'pages     %s, config.js %s' % (h.static_dir, h.config_js),
            'clients   %d active (limit %s, timeout %s, per-ip %s)'
            % (total, self.httpd.gate.max_total or 'none',
               secs(h.timeout) if h.timeout else 'off',
               self.httpd.gate.max_per_ip or 'none'),
            'auth      %s, log access %s, log queries %s'
            % ('bearer token' if h.auth_token else 'none (the loopback bind is the auth)',
               'on' if h.log_access else 'off',
               'on' if h.log_queries else 'off'),
            'audit     %s' % ('off' if self.audit is None
                              else (self.audit.path if self.audit.path != '-' else 'stdout')),
            'uptime    %s' % secs(time.monotonic() - self.started),
        ]
        return 'ok inspect\n' + '\n'.join(rows)
