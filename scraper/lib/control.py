#!/usr/bin/env python3
"""JSON-lines control server for modbus-scraper: inspect and steer the
running exporter — show status/connections/version, the live
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
import time

from common.human import secs
from common.version import version_string
from common.wiresec import verify_request_mac, sign_reply, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.control import ControlServer as _ControlServer, num, numi
from common.options import control_command, describe_node, describe_root, grouped_rows, match_setting_path
from common.config import default_profile_path, is_loopback_host, parse_auth_type, parse_listen, \
    parse_secret, parse_upstream, resolve_profile_file
from common.dump import SECRET_REMOVED, dump_filter
from common.modbus import AUTH_MIN_KEY
from .config import build_sources, load_device_profile
from .options import OPTIONS, SETTING_BY_NAME, describe_setting, SHOW_BY_LIVE, SHOW_OPTIONS, NODE_BY_NAME, \
    KNOWN_VERBS, CFG_KEYS
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, LOG_LEVELS

logger = logging.getLogger('scraper')

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
                 defaults=None, trust_uids=None, ops_token=None, ops_verbs=None, config_path=None,
                 dump_path=None, restore_on_start=False, dump_key=None):
        self.scraper = scraper
        self.httpd = httpd
        super().__init__(target, reloader=reloader, stopper=stopper, audit=audit, token=token,
                         defaults=defaults, trust_uids=trust_uids, ops_token=ops_token,
                         ops_verbs=ops_verbs, config_path=config_path, dump_path=dump_path,
                         restore_on_start=restore_on_start, dump_key=dump_key)

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
        if low == 'ping':                 # keep-alive from scraper_ctl
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
            return 'ok modbus-scraper %s' % version_string()
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
        ValueError (the message becomes the err reply)."""
        s = self.scraper
        val = str(value).strip()

        if key == 'interval':
            v = num(val, 'interval', 'seconds')
            if not 0 < v <= 86400:
                raise ValueError('interval must be 0 < N <= 86400 seconds')
            with s.lock:
                s.cfg['interval'] = v
            s.wake.set()
            return secs(v)
        if key == 'timeout':
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
        if key == 'max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            if not self.httpd:
                raise ValueError('no http server attached')
            self.httpd.gate.max_total = v
            return '%d' % v
        if key == 'client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            if not self.httpd:
                raise ValueError('no http server attached')
            with s.lock:
                s.cfg['client_timeout'] = v
            self.httpd.RequestHandlerClass.timeout = v or None
            return secs(v)
        if key == 'limits/max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            if not self.httpd:
                raise ValueError('no http server attached')
            self.httpd.gate.max_per_ip = v
            return '%d' % v
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
        if key == 'profile':
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
        if key == 'auth/token':
            if val in ('off', 'none', ''):
                host, _port = parse_listen(s.cfg['listen'])
                if not is_loopback_host(host):
                    raise ValueError('auth/token is mandatory while the listen is non-loopback '
                                     '(F13 in docs/AUDIT.md) — set the new token')
                self.httpd.RequestHandlerClass.auth_token = None
                with s.lock:
                    s.cfg['auth_token'] = None
                return 'off'
            try:
                val = parse_secret(val, 'auth/token')   # file: reads the first line of an owner-only file
            except SystemExit as e:
                raise ValueError(str(e))
            if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in val):
                raise ValueError('auth/token must not contain whitespace or control characters')
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
        if key == 'dump/restore-on-start':
            if val in ('on', 'true', '1', 'yes'):
                on = True
            elif val in ('off', 'false', '0', 'no'):
                on = False
            else:
                raise ValueError('dump/restore-on-start must be on or off')
            self.dump_restore = on   # prospective: the START behaviour this session already chose stands
            return 'on' if on else 'off'
        # the generic path: a typed row (int/float/str conv) needs no branch
        # — the row's conv parses, the row's min/max gate, the config key
        # takes the value; the value takes effect wherever the config is
        # next consumed (a client rebuild, a reload)
        opt = OPTION_BY_LIVE.get(key)
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
        if key == 'interval':
            return secs(cfg['interval'])
        if key == 'timeout':
            return secs(cfg['timeout'])
        if key == 'max-clients':
            return '%d' % (self.httpd.gate.max_total if self.httpd else cfg['max_clients'])
        if key == 'client-timeout':
            ct = self.httpd.RequestHandlerClass.timeout if self.httpd else cfg['client_timeout'] or None
            return 'off' if not ct else secs(ct)
        if key == 'limits/max-conn-per-ip':
            return '%d' % (self.httpd.gate.max_per_ip if self.httpd else cfg['max_conn_per_ip'])
        if key == 'log-access':
            return 'on' if (self.httpd.RequestHandlerClass.log_access if self.httpd else cfg['log_access']) else 'off'
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger().getEffectiveLevel())
        if key == 'profile':
            return cfg['profile']
        if key == 'control/token':
            return '<set>' if self.token else 'off'   # the secret never renders
        if key == 'control/ops/token':
            return '<set>' if self.ops_token else 'off'   # the secret never renders
        if key == 'auth/token':
            return '<set>' if cfg['auth_token'] else 'off'   # the secret never renders
        if key == 'modbus/auth':
            return cfg.get('auth') or 'none'
        if key == 'modbus/auth/key':
            return '<set>' if cfg.get('auth_key') else 'none'   # the secret never renders
        if key == 'dump/path':
            return self.dump_path or 'off'
        if key == 'dump/restore-on-start':
            return 'on' if self.dump_restore else 'off'
        # the generic path: a registry row with a typed conv reads its
        # config key with no branch at all
        opt = OPTION_BY_LIVE.get(key)
        if opt is not None and opt.conv in TYPED_CONVS and opt.name.replace('-', '_') in cfg:
            return str(cfg[opt.name.replace('-', '_')])
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

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
            'interval': cfg['interval'],
            'timeout': cfg['timeout'],
            'profile': cfg['profile'],
            'max-clients': cfg['max_clients'],
            'client-timeout': cfg['client_timeout'],
            'limits/max-conn-per-ip': cfg['max_conn_per_ip'],
            'log-access': 'on' if cfg['log_access'] else 'off',
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

    def status_report(self):
        """The status as a compact multi-field report: one stable key=value
        per line (scriptable)."""
        s = self.scraper
        now = time.time()
        cfg = s.cfg
        gate = self.httpd.gate if self.httpd else None
        rows = [
            'upstream=%s:%d' % (cfg['host'], cfg['modbus_port']),
            'unit=%d' % cfg['modbus_unit'],
            'offset=%d' % cfg['modbus_offset'],
            'modbus_auth=%s' % (cfg.get('auth') or 'none'),
            'timeout=%s' % secs(cfg['timeout']),
            'listen=%s' % cfg['listen'],
            'control=%s' % self.describe(),
            'uptime=%s' % secs(time.monotonic() - self.started),
            'poll=%s' % ('ok' if s.up else 'down'),
            'last_poll=%s' % ('never' if not s.last_poll else secs(now - s.last_poll)),
            'interval=%s' % secs(cfg['interval']),
            'errors=%d' % s.errors,
            'sanity=%s' % ('ok' if not s.error_state() else 'failed'),
            'battery=%s' % ('on' if cfg['battery'] else 'off'),
            'auth=%s' % ('bearer' if cfg['auth_token'] else 'none'),
            'clients=%d' % (gate.total() if gate else 0),
            'max_clients=%s' % ((gate.max_total if gate else cfg['max_clients']) or 'none'),
            'client_timeout=%s' % (secs(cfg['client_timeout']) if cfg['client_timeout'] else 'off'),
            'max_conn_per_ip=%s' % ((gate.max_per_ip if gate else cfg['max_conn_per_ip']) or 'none'),
            'log_access=%s' % ('on' if cfg['log_access'] else 'off'),
            'profile=%s' % cfg['profile'],
            'overridden=%s' % (','.join(sorted(self.overridden)) or 'none'),
        ]
        return 'ok status\n' + '\n'.join(rows)

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
