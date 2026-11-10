#!/usr/bin/env python3
"""JSON-lines control server: set/show the fake's settings at runtime
(value pins, the grid setpoint, the battery state force, cloud machines,
clock freeze, chaos), scenario presets, and the inspect dump / registers
table / version / reset / shutdown. Speaks one command per line, one reply
line. Every request and reply is one JSON object per line (the stdlib
json module): the request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. Connections need a token auth
handshake when --control-token is set ({"cmd": "auth", "token": ...}); over
the unix socket a kernel-vouched peer (root, the daemon's own user or
--control-trust-uids — SO_PEERCRED) skips the handshake. A second,
read-only token (--control-ops-token) authenticates into its policy's verbs (the
verbs only — the ops shift against the admin key, both audited."""
import logging
import math
import time

from common.settings.config import acl_table, acl_text, acl_value_text, parse_acl, parse_auth_type, \
    parse_listen, resolve_metrics_acl
from common.render.human import secs
from common.modbus import AUTH_MIN_KEY
from common.wire.control import ControlServer as _ControlServer, num, numi, on_off
from .metrics import MetricsServer, describe_metrics
from .profile import load_profile, profile_label, resolve_profile
from .signals import parse_time
from common.runtime.version import version_string
from common.render.texts import T
from .options import OPTIONS, SETTING_NAMES, SETTING_BY_NAME, SET_BY_NAME, SHOW_BY_LIVE, \
    SHOW_OPTIONS, NODE_BY_NAME, COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN
from .simulator import CLOUD_MACHINES, format_clock
from .statics import CONTROL_SOCKET_TEMPLATE, DEFAULT_LISTEN_PORT, \
    LOG_LEVELS, MAX_REGISTERS, PEAK_RATIO, SCENARIOS, TIME_SCALE_MAX

logger = logging.getLogger('fake-inverter')

# The registry-driven bounds: the row's min/max (inclusive) are the one
# home for a knob's range — the branches parse and plumb, the row gates.
OPTION_BY_LIVE = {o.live: o for o in OPTIONS if o.live}
TYPED_CONVS = (int, float, str)




class ControlServer(_ControlServer):
    """JSON-lines control socket: pin values, freeze time, tune chaos — see
    the README for the command list. The target is either a TCP port (bound to
    127.0.0.1) or a unix socket path (stale files are replaced, unlinked on
    shutdown). A connection must authenticate with the token first when one
    is configured — over the unix socket a kernel-vouched peer (root, the
    daemon's own user or trust_uids — SO_PEERCRED) skips the handshake. A
    second, read-only token (ops_token) may be configured beside the admin
    token: it authenticates into its policy's verbs —     no set/clear,
    no reset, no reload, no shutdown (common/wire/wiresec.py's roles). The
    listener rides the base's rebind family: a live `set control/port`
    swaps the socket (bind first, the failed bind rolls back, the sessions
    keep serving, off retires) — tokenless TCP included (F11)."""

    def log_exchange(self, who, cmd, reply):
        """The reply text is demo state: logged only when --log-replies
        (the base line carries it unconditionally)."""
        if self.log_replies:
            self.LOG.debug('control from %s: %s -> %s', who, cmd, reply)
        else:
            self.LOG.debug('control from %s: %s', who, cmd)

    def _signalbox_stop(self, source='control command'):
        """The base's post-loop stopper: hand the shutdown to the
        signalbox when the entry has set one."""
        if self.signalbox:
            self.signalbox.shutdown('control')

    # every configurable of the fake: the shared registry (lib.settings)
    SETTING_KEYS = SETTING_NAMES

    # the scenario presets live in defaults.json (lib.statics.SCENARIOS):
    # freeze the clock at a typical moment and release the value pins, so
    # the day simulation (and the battery machine) take over

    LOG = logger
    OPTIONS = OPTIONS
    SETTINGS = SETTING_BY_NAME
    WHO = 'the fake inverter'
    EXIT_TEXT = 'the fake inverter is shutting down'
    RELOAD_TEXT = 'the fake inverter is reloading — the daemon restarts with the saved configuration'
    RELOAD_NEEDS_CONFIG = True    # the fake takes the family's config file now — the reload state rides beside it
    XDG_STATE_NAME = 'fake-inverter'   # the base's _reload_state_path fallback (--config '')
    APPLY_FIRST = ('scenario',)   # a preset release is the state the pins were pinned after — pins land on top
    TOKENLESS_TCP = 'allow'   # the F11 test-tool posture: a tokenless TCP control bind is fine here (the family refuses — F5)
    APP = 'fake-inverter'
    AUDIT_PREFIX = 'INV'
    AUDIT_APP = 'fake-inverter'
    CONTROL_PORT_DEFAULT = DEFAULT_LISTEN_PORT
    CONTROL_SOCKET_TEMPLATE = CONTROL_SOCKET_TEMPLATE
    LOG_LEVELS = LOG_LEVELS
    COMMANDS = COMMANDS
    COMMAND_HELP = COMMAND_HELP
    COMMAND_GROUPS = COMMAND_GROUPS
    COMMAND_HIDDEN = COMMAND_HIDDEN
    NODE_BY_NAME = NODE_BY_NAME
    SET_BY_NAME = SET_BY_NAME
    SHOW_BY_LIVE = SHOW_BY_LIVE
    OPTION_BY_LIVE = OPTION_BY_LIVE
    SHOW_OPTIONS = SHOW_OPTIONS
    SHOW_REPORTS = {'show registers': 'registers_report',
                    'show metrics-acl-table': 'acl_table_report'}   # `show metrics acl table` (the live path's words) forwards here

    def __init__(self, simulator, chaos, target, fake=None, defaults=None, log_replies=False, audit=None, token=None,
                 trust_uids=None, socket_group=False, ops_token=None, ops_verbs=None, startup_values=None,
                 dump_path=None, restore_on_start=False, config_path=None, dump_key=None, dump_interval=0.0,
                 audit_params=None):
        super().__init__(target, audit=audit, token=token, defaults=defaults, trust_uids=trust_uids,
                         socket_group=socket_group, ops_token=ops_token, ops_verbs=ops_verbs,
                         audit_params=audit_params, config_path=config_path, dump_path=dump_path,
                         restore_on_start=restore_on_start, dump_key=dump_key, dump_interval=dump_interval,
                         stopper=self._signalbox_stop)
        self.log_replies = log_replies   # DEBUG also logs the full command output
        self.startup_values = startup_values or {}   # the set-grammar form of the startup options (show config)
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.signalbox = None       # set by the entry; 'shutdown' hands over to it
        self.scenario = None        # last applied preset, or None = 'custom'
        self.metrics_acl_warn = None   # the metrics/acl file's permission warning (the stash, None = no warning standing)

    def show_config(self):
        """The startup options as a set-grammar script — the argv that would
        restart this fake (the configured secrets render as *** SECRET
        REMOVED ***; the live `set` values are runtime state, not here)."""
        from common.settings.options import render_config_script
        script = render_config_script(OPTIONS, dict(self.startup_values),
                                      comment='generated by show config — the argv that would restart this fake '
                                              '(the secret knobs render as *** SECRET REMOVED ***)')
        return 'ok config\n' + script

    def _apply(self, key, value):
        sim, chaos, fake = self.simulator, self.chaos, self.fake
        val = value.lower()
        rs = SETTING_BY_NAME.get(key)
        if rs is not None and rs.restart:   # a startup-only knob: validate + record the pending value (the restart applies it)
            if rs.secret:
                raise ValueError(T('wire.restart_required'))
            handled, shown = self.apply_restart_key(key, val)
            if handled:
                return shown
            if key == 'system/listen':
                try:
                    t = parse_listen(val)
                except SystemExit as e:
                    raise ValueError(str(e))
                self.defaults[key] = '%s:%d' % t
                return self.defaults[key]
            raise ValueError(T('wire.unknown_setting_bare') % key)

        handled, shown = self.apply_family_key(key, val, raw=value.strip())   # the family's shared knobs
        if handled:   # (the record hook drops — the fake's show config is the argv view)
            return shown
        auto = val in ('auto', 'off', 'none', 'clear', 'live')
        if key in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud'):
            if key == 'cloud' and val in CLOUD_MACHINES:
                sim.set_cloud_mode(val)
                return val
            if key == 'cloud':
                sim.set_cloud_mode(None)   # 'clear' = clear sky: the machine is off
            if auto:
                sim.override(key, None)   # the word releases the pin before any parse
                return 'clear' if key == 'cloud' else 'auto'
            v = num(val, key, 'a number')
            sim.override(key, v)
            return '%g' % v
        if key == 'timezone':
            if val not in ('utc', 'local'):
                raise ValueError('timezone must be utc|local')
            sim.utc = val == 'utc'
            return val
        if key == 'time':
            if auto:
                sim.freeze(None)
                return 'auto'
            t = self._parse_hour(val)
            sim.freeze(t)
            return format_clock(t)
        if key == 'time-scale':
            if auto:
                sim.set_time_scale(1.0)
                return 'x1 (real time)'
            v = num(val, 'time-scale', 'a multiplier')
            if not math.isfinite(v) or v <= 0 or v > TIME_SCALE_MAX:
                raise ValueError('time-scale must be 0 < N <= %g (a day per minute)' % TIME_SCALE_MAX)
            sim.set_time_scale(v)
            return 'x%g' % v
        if key == 'chaos':
            if val in ('off', 'none'):
                chaos.set_probability(0.0)
            else:
                chaos.set_probability(num(val, 'chaos', 'a probability 0..1'))
            return '%.2f' % chaos.p
        if key == 'seed':
            if val in ('random', 'none', 'auto'):
                chaos.reseed(None)
                return 'random'
            v = numi(val, 'seed', 'an integer')
            chaos.reseed(v)
            return str(v)
        if key == 'mppt':
            if val not in ('both', 'east', 'west', 'none'):
                raise ValueError('mppt must be both|east|west|none')
            sim.mppt = val
            return val
        if key == 'battery-state':
            if val not in ('auto', 'charging', 'discharging'):
                raise ValueError('battery-state must be auto|charging|discharging')
            sim.batt_state = None if val == 'auto' else val
            return val
        if key == 'grid-voltage':
            v = num(val, 'grid-voltage', 'V')
            self._gate_range(key, v, 'V')
            sim.grid_voltage = v
            return '%g' % v
        if key == 'grid-frequency':
            v = num(val, 'grid-frequency', 'Hz')
            self._gate_range(key, v, 'Hz')
            sim.grid_frequency = v
            return '%g' % v
        if key == 'grid-voltage-wander':
            v = num(val, 'grid-voltage-wander', 'a fraction')
            self._gate_range(key, v, 'fraction')
            sim.grid_voltage_wander = v
            return '%g' % v
        if key == 'grid-frequency-wander':
            v = num(val, 'grid-frequency-wander', 'Hz')
            self._gate_range(key, v, 'Hz')
            sim.grid_frequency_wander = v
            return '%g' % v
        if key == 'grid-outage':
            if val in ('outage', 'down', 'blackout'):
                sim.grid_outage = 'outage'
                return 'outage'
            if val in ('off', 'none', 'ok', 'up'):
                sim.set_outage_machine('off')
                return 'off'
            if auto or val == 'on':        # auto = let the machine decide
                sim.set_outage_machine('on')
                return sim.outage_display()
            raise ValueError('grid-outage must be on|off|outage')
        if key == 'strict':
            fake.strict = on_off(val, 'strict')
            return 'on' if fake.strict else 'off'
        if key == 'static':
            sim.static = on_off(val, 'static')
            return 'on' if sim.static else 'off'
        if key == 'max-kwp':
            v = num(val, 'max-kwp', 'a number')
            if not math.isfinite(v) or v <= 0:
                raise ValueError('max-kwp must be a positive kW value')
            sim.peak_w = PEAK_RATIO * v * 1000.0
            return '%g' % v
        if key == 'modbus/profile':
            path = resolve_profile('sun2000' if val in ('default', 'auto', 'none') else value.strip())
            try:
                m = load_profile(path)
            except SystemExit as e:
                raise ValueError(str(e))
            sim.set_profile(m)
            return '%s (%s)' % (m.description, profile_label(m.path))
        if key == 'battery-kwh':
            v = num(val, 'battery-kwh', 'a number')
            if not math.isfinite(v) or v <= 0:
                raise ValueError('battery-kwh must be a positive kWh value')
            sim.battery_kwh = v
            return '%g' % v
        if key == 'max-clients':
            v = numi(val, 'max-clients', 'clients')
            self._gate_range(key, v)
            if fake:
                fake.max_clients = v
                return str(v)
            raise ValueError('no modbus device attached')
        if key == 'max-conn-per-ip':
            v = numi(val, 'max-conn-per-ip', 'connections')
            self._gate_range(key, v)
            if fake:
                fake.conn_gate.max_per_ip = v
                return str(v)
            raise ValueError('no modbus device attached')
        if key == 'connect-acl':
            if not fake:
                raise ValueError('no modbus device attached')
            try:
                fake.connect_acl = parse_acl(val, 'connect-acl')
            except SystemExit as e:
                raise ValueError(str(e))
            return acl_text(fake.connect_acl)
        if key == 'write/allow':
            if not fake:
                raise ValueError('no modbus device attached')
            fake.allow_write = on_off(val, 'write/allow')
            return 'on' if fake.allow_write else 'off'
        if key == 'modbus/auth':
            if not fake:
                raise ValueError('no modbus device attached')
            try:
                v = parse_auth_type(val, 'modbus/auth')
            except SystemExit as e:
                raise ValueError(str(e))
            if v and not fake.auth_key:
                raise ValueError(T('wire.suite_auth_needs_key') % AUTH_MIN_KEY)
            fake.auth = v   # the next connection handshakes; the standing ones keep their session
            return v or 'none'
        if key == 'metrics/enable':
            if not fake:
                raise ValueError('no modbus device attached')
            if val in ('on', 'true', '1', 'yes'):
                if fake.metrics_srv:
                    return 'on'
                if not fake.metrics_token:
                    from common.settings.config import is_loopback_host
                    if not is_loopback_host(fake.metrics_listen[0]):
                        raise ValueError('refusing to expose /metrics beyond loopback without a token '
                                         '(F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config '
                                         'and restart, or bind 127.0.0.1:PORT')
                srv = MetricsServer(sim, chaos, fake, self, fake.metrics_listen, token=fake.metrics_token,
                                    max_clients=fake.metrics_caps[0], client_timeout=fake.metrics_caps[1],
                                    max_per_ip=fake.metrics_caps[2])
                try:
                    srv.start()
                except SystemExit:
                    host, port = fake.metrics_listen
                    raise ValueError('cannot bind %s:%d: %s' % (host, port, srv.bind_error))
                fake.metrics_srv = srv
                fake.metrics_desc = describe_metrics(fake.metrics_listen, fake.metrics_token,
                                                     fake.metrics_caps[0], fake.metrics_caps[2])
                return 'on'
            if val in ('off', 'false', '0', 'no'):
                if fake.metrics_srv:
                    fake.metrics_srv.stop()
                    fake.metrics_srv = None
                    fake.metrics_desc = 'off'
                return 'off'
            raise ValueError('metrics-server must be on or off')
        if key == 'client-timeout':
            v = num(val, 'client-timeout', 'seconds')
            self._gate_range(key, v, 'seconds')
            if fake:
                fake.client_timeout = v
                return '%gs' % v if v else 'never'
            raise ValueError('no modbus device attached')
        if key == 'scenario':
            if val == 'custom':
                sim.freeze(None)
                for k in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud'):
                    sim.override(k, None)
                self.scenario = 'custom'
                return val
            if val not in SCENARIOS:
                raise ValueError('unknown scenario %s (try %s)' % (val, '|'.join(sorted(SCENARIOS))))
            sim.freeze(SCENARIOS[val])
            for k in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud'):
                sim.override(k, None)
            self.scenario = val
            return val
        if key == 'metrics/acl':
            if not fake:
                raise ValueError('no modbus device attached')
            if val == 'table':   # the show word is never a value — point at the report
                raise ValueError('"table" is not a metrics/acl value — the table is the show: '
                                 'show metrics acl table')
            try:
                gate, warn = resolve_metrics_acl(value)
            except SystemExit as e:
                raise ValueError(str(e))
            self.metrics_acl_warn = warn   # the fresh state: an inline set clears a standing file warning
            if warn is not None:   # the acl file's permission warning: the log, the audit trail, the reply's suffix
                logger.warning('acl file: %s', warn)
                if self.audit:
                    self.audit.event('ACL-FILE', warn)
            fake.metrics_acl = gate   # the swap is live: the accept check reads it per connection
            shown = acl_value_text(gate)
            if warn:   # the acl file's permission warning rides the reply (the log and the audit trail carry it too)
                shown += ' (%s)' % warn
            return shown
        raise ValueError(T('wire.unknown_setting_bare') % key)

    def _parse_hour(self, text):
        try:
            return parse_time(text)
        except ValueError as e:
            raise ValueError('time out of range (00:00-23:59)') from e

    def _get(self, key):
        sim, ov, fake, chaos = self.simulator, self.simulator.overrides(), self.fake, self.chaos
        handled, value = self.get_family_key(key)   # the family's shared knobs (the control plane,
        if handled:                                 # the audit family, local-time, the dump pair)
            return value
        if key in ('pv', 'load', 'batt', 'grid', 'soc'):
            if ov[key] is None:
                return 'auto'
            return '%g' % ov[key]
        if key == 'cloud':
            return sim.cloud_display()   # the pin, the machine with its factor, or clear — the summary's wording
        if key == 'timezone':
            return 'utc' if sim.utc else 'local'
        if key == 'time':
            return 'auto' if sim.frozen_time is None else format_clock(sim.frozen_time)
        if key == 'time-scale':
            return 'x%g' % sim.time_scale
        if key == 'chaos':
            return '%.2f' % chaos.p
        if key == 'seed':
            return 'random' if chaos.seed is None else str(chaos.seed)
        if key == 'mppt':
            return sim.mppt
        if key == 'battery-state':
            return sim.batt_state or 'auto'
        if key == 'grid-voltage':
            return '%g' % sim.grid_voltage
        if key == 'grid-frequency':
            return '%g' % sim.grid_frequency
        if key == 'grid-voltage-wander':
            return '%g' % sim.grid_voltage_wander
        if key == 'grid-frequency-wander':
            return '%g' % sim.grid_frequency_wander
        if key == 'grid-outage':
            return sim.outage_display()
        if key == 'strict':
            return 'on' if fake.strict else 'off'
        if key == 'static':
            return 'on' if sim.static else 'off'
        if key == 'max-kwp':
            return '%g' % (sim.peak_w / (1000.0 * PEAK_RATIO))
        if key == 'battery-kwh':
            return '%g' % sim.battery_kwh
        if key == 'max-clients':
            return str(fake.max_clients) if fake else '?'
        if key == 'max-conn-per-ip':
            return str(fake.conn_gate.max_per_ip) if fake else '?'
        if key == 'connect-acl':
            return acl_text(fake.connect_acl) if fake else '?'
        if key == 'write/allow':
            return ('on' if fake.allow_write else 'off') if fake else '?'
        if key == 'modbus/auth':
            return (fake.auth or 'none') if fake else '?'
        if key == 'metrics/enable':
            return ('on' if fake.metrics_srv else 'off') if fake else '?'
        if key == 'client-timeout':
            return ('%gs' % fake.client_timeout if fake.client_timeout else 'never') if fake else '?'
        if key == 'modbus/profile':
            return '%s (%s)' % (sim.profile.description, profile_label(sim.profile.path))
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger('fake-inverter').getEffectiveLevel())
        if key == 'metrics/acl':
            return acl_value_text(fake.metrics_acl) if fake else '?'
        if key == 'scenario':
            return self.scenario or 'custom'
        s = SETTING_BY_NAME.get(key)
        if s is not None and s.restart:   # a startup-only knob: the configured value
            return self.defaults.get(key, '?')   # renders (the secrets answer '<set>'/'off')
        return '?'

    def _rebuild_audit(self):
        """The family rebuild, mirrored onto the fake's writer (the WRITE /
        WRITE-REFUSED events audit there, the control's COMMAND events
        here)."""
        shown = super()._rebuild_audit()
        if self.fake is not None:
            self.fake.audit = self.audit
        return shown

    def acl_table_report(self):
        """The metrics/acl/table show report (the show-only view of the
        metrics ACL, one entry per line): the system forms spell the chain
        they implement — 'allow 0.0.0.0/0' (any), 'deny 0.0.0.0/0' (none),
        'deny 0.0.0.0/0' + one allow line per network (the whitelist); a
        file gate renders its own rules — the gate desc as the '% ' line,
        the rule descs as aligned '# ' comments, the matcher 'any' spelled
        0.0.0.0/0 (common/settings/config.py acl_table, the family's one renderer)."""
        fake = self.fake
        return 'ok metrics-acl-table\n%s' % '\n'.join(acl_table(fake.metrics_acl if fake else None))

    def command_help(self):
        """The one-line command reference: the fake's verb list speaks the
        pin names; the state-dump commands appear only when a dump path is
        configured (there is nothing to dump into otherwise)."""
        cmds = ('commands: set <%s> <value|auto|on|off>, clear <setting>, show <setting|connections|config|knobs>, '
                'reset' % '|'.join(self.SETTING_KEYS))
        cmds += ', request reload, request reload-config, shutdown, quit'
        return self.command_help_tail(cmds)

    def command_tool(self, low, cmd):
        """The fake's own verb: reset clears the pins, the machines'
        overlays and the scenario (the set-grammar settings re-apply from
        the configured values)."""
        if low == 'reset':
            pins = self.simulator.reset_overrides()
            overlay = coils = discrete = 0
            if self.fake:
                overlay = len(self.fake.overlay)
                coils = len(self.fake.coils)
                discrete = len(self.fake.discrete)
                self.fake.overlay.clear()
                self.fake.coils.clear()
                self.fake.discrete.clear()
            self.scenario = None
            self.overridden.difference_update(('pv', 'load', 'batt', 'grid', 'soc', 'cloud',
                                               'battery-state', 'grid-outage', 'scenario'))
            logger.info('control: reset cleared %d pin(s) + %d overlay register(s), %d coil(s), %d discrete input(s)',
                        pins, overlay, coils, discrete)
            return 'ok reset (%d pin(s), %d overlay register(s), %d coil(s), %d discrete input(s) cleared) %s' \
                % (pins, overlay, coils, discrete, self.status())
        return None

    def command_set_special(self, args):
        """The fake's Modbus-write set words: the same overlay the wire
        writes land in, so the scrapers see it — `set register/coil/
        discrete ADDR VAL` (no live row, reset clears)."""
        if args[0].lower() not in ('register', 'coil', 'discrete'):
            return None
        what = args[0].lower()
        if not self.fake:
            return 'err no modbus device attached'
        if len(args) < 3:
            return 'err set %s needs an address and a value%s' % (
                what, ' (0 or 1)' if what != 'register' else '')
        try:
            addr, val = int(args[1]), int(args[2])
        except ValueError:
            return 'err %s address and value must be integers' % what
        if what == 'register':
            if not 0 <= addr <= MAX_REGISTERS - 1 or not 0 <= val <= MAX_REGISTERS - 1:
                return 'err register address/value out of range (0..%d)' % (MAX_REGISTERS - 1)
            self.fake.overlay[addr] = val
            logger.info('control: set register %d=%d (write overlay)', addr, val)
            return 'ok register %d=%d (the write overlay, the scrapers read it)' % (addr, val)
        if not 0 <= addr <= MAX_REGISTERS - 1 or val not in (0, 1):
            return 'err %s address out of range (0..%d) or value not 0/1' % (what, MAX_REGISTERS - 1)
        if what == 'coil':
            self.fake.coils[addr] = val
            logger.info('control: set coil %d=%d', addr, val)
            return 'ok coil %d=%d (the coil space, FC1/FC5/FC15 see it)' % (addr, val)
        self.fake.discrete[addr] = val
        logger.info('control: set discrete %d=%d', addr, val)
        return 'ok discrete %d=%d (the discrete-input space, FC2 sees it)' % (addr, val)

    def _after_set(self, key):
        """A manual pin turns the day simulation's state 'custom' (the
        scenario preset releases)."""
        if key != 'scenario':
            self.scenario = None

    def show_walk_tail(self, args):
        """The fake's walk tail reports the whole path (the family's
        one-word tail keeps the stray-word fall-through)."""
        return 'err ' + (T('wire.unknown_setting') % ' '.join(args))

    def unknown_command(self, cmd):
        """The fake's unknown errs on the first word, unquoted (the
        family's whole-command %r keeps its own)."""
        return 'err ' + (T('wire.unknown_command_first') % cmd.split()[0].lower())

    def registers_report(self):
        """The registers table (show registers): name | register | type |
        current value (NaN = the profile maps a value the simulator is
        not calculating right now; a write overlay wins — set
        register/FC16)."""
        entries = self.simulator.profile.entries
        if not entries:
            return 'ok registers: (the profile has no registers)'
        vals = self.simulator.values()
        overlay = dict(self.fake.overlay) if self.fake else {}
        rows = []
        for name, addr, typ, _scale, _fc in entries:
            if addr in overlay:
                val = '%d *' % overlay[addr]   # a write overlay wins (set register/FC16)
            elif vals.get(name) is None:
                val = 'NaN'
            else:
                val = '%g' % vals.get(name)
            rows.append((name, str(addr), typ, val))
        # the multi-line reply carries its newlines inside the JSON text
        w1 = max(len(r[0]) for r in rows)
        w2 = max(len(r[1]) for r in rows)
        w3 = max(len(r[2]) for r in rows)
        w4 = max(len(r[3]) for r in rows)
        table = '\n'.join('%-*s | %*s | %*s | %*s' % (w1, a, w2, b, w3, c, w4, d)
                          for a, b, c, d in rows)
        return 'ok registers (%d)\n%s' % (len(rows), table)

    def summary(self):
        """The status line is the fake's set/clear suffix (the family's
        summary hook)."""
        return self.status()

    def connections_line(self):
        """The fake's live Modbus clients: peer, connection age, requests
        served (the base's reading, pointed at the simulator)."""
        if not self.fake:
            return 'err no modbus device attached'
        return self.modbus_connections_line(self.fake.clients, self.fake.client_lock)

    def inspect(self):
        """One pretty dump of everything — the status, the machines' states,
        the write overlay, the version: the baton for a bug report."""
        sim = self.simulator
        pv_w, load_w, batt_w, soc, cloud, ov = sim.effective()
        t = sim.clock()
        overlay = dict(self.fake.overlay) if self.fake else {}
        rows = [
            'version   %s' % version_string(),
            'profile   %s' % sim.profile.description,
            'registers %d served, overlay %d: %s' % (len(sim.profile.entries), len(overlay),
                ', '.join('%d=%d' % kv for kv in sorted(overlay.items())[:8]) or 'empty'),
            'bits      coils %d pinned, discrete inputs %d pinned: %s' % (
                len(self.fake.coils) if self.fake else 0,
                len(self.fake.discrete) if self.fake else 0,
                ', '.join('%s%d=%d' % ('c' if k in self.fake.coils else 'd', k, v)
                          for k, v in sorted({**self.fake.coils, **self.fake.discrete}.items())[:8]) if self.fake else 'none'),
            'now       %s %s%s, uptime %s' % (format_clock(t),
                'utc' if sim.utc else 'local',
                ' x%g' % sim.time_scale if sim.time_scale != 1.0 else '',
                secs(time.monotonic() - self.started)),
            'power     pv %g W, load %g W, grid %g W' % (pv_w, load_w,
                0.0 if sim.outage_active() else pv_w - batt_w - load_w),
            'battery   %s' % ('%g W, SoC %s, state %s' % (batt_w,
                '%.1f %%' % soc if soc is not None else 'n/a', sim.batt_state or 'auto')),
            'mppt      %s (string-1 = the east array, string-2 = the west)' % sim.mppt,
            'cloud     %s' % sim.cloud_display(),
            'grid      %g V nominal, %g Hz nominal; machines: %s V/phase, %.2f Hz now; outage %s'
            % (sim.grid_voltage, sim.grid_frequency,
               '/'.join('%g' % v for v in sim._grid_voltages(t)),
               sim.grid_frequency_value(t), sim.outage_display()),
            'chaos     p=%.2f, %d hit(s)' % (self.chaos.p, self.chaos.hits),
            'pinned    %s' % ('; '.join('%s=%s' % (k, ov[k]) for k in
                              ('pv', 'load', 'batt', 'grid', 'soc', 'cloud') if ov[k] is not None) or 'nothing'),
            'metrics   %s' % getattr(self.fake, 'metrics_desc', 'off'),
        ]
        if self.fake:
            la = self.fake.listen_addr or ('?', '?')
            rows.append('modbus    %s:%d, clients %d (limit %s, timeout %s, per-ip %s, connect-acl %s, auth %s)'
                        % (la[0], la[1], self.fake.client_count, self.fake.max_clients or 'none',
                           secs(self.fake.client_timeout) if self.fake.client_timeout else 'none',
                           self.fake.conn_gate.max_per_ip or 'none',
                           'any' if self.fake.connect_acl is None
                           else ('none' if not self.fake.connect_acl else '%d network(s)' % len(self.fake.connect_acl)),
                           self.fake.auth or 'none'))
        return 'ok inspect\n' + '\n'.join(rows)

    def status(self):
        sim = self.simulator
        pv_w, load_w, batt_w, soc, cloud, ov = sim.effective()
        t = sim.clock()
        pinned = ' '.join('%s=%s' % (k, ov[k]) for k in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud') if ov[k] is not None)
        extra = ' batt-state=%s' % sim.batt_state if sim.batt_state else ''
        scale = 'x%g' % sim.time_scale if sim.time_scale != 1.0 else ''
        outage = '' if sim.grid_outage == 'off' else ' outage=%s' % sim.outage_display()
        return ('pv=%.0fW load=%.0fW batt=%.0fW soc=%s cloud=%s mppt=%s t=%s%s chaos=%.2f hits=%d%s%s%s'
                % (pv_w, load_w, batt_w,
                   '%.1f%%' % soc if soc is not None else 'n/a',
                   sim.cloud_display(), sim.mppt,
                   format_clock(t), scale, self.chaos.p, self.chaos.hits, outage, extra,
                   (' pinned: ' + pinned) if pinned else ''))

    def dump_settings(self):
        """The live-overridden settings as raw, re-appliable values. No
        secret can be overridden (the wire refuses them — startup-only),
        so no secret placeholder occurs; the dump filter's secret
        branch stays as the class invariant's guard. The scenario rides as
        its truth ('custom' when the pins took over — the restore applies
        it first and re-pins on top)."""
        sim, chaos, fake = self.simulator, self.chaos, self.fake
        ov = sim.overrides()
        raw = {
            'pv': 'auto' if ov['pv'] is None else '%g' % ov['pv'],
            'load': 'auto' if ov['load'] is None else '%g' % ov['load'],
            'batt': 'auto' if ov['batt'] is None else '%g' % ov['batt'],
            'grid': 'auto' if ov['grid'] is None else '%g' % ov['grid'],
            'soc': 'auto' if ov['soc'] is None else '%g' % ov['soc'],
            'cloud': ('clear' if not sim.cloud_mode else sim.cloud_mode) if ov['cloud'] is None
                     else '%g' % ov['cloud'],
            'mppt': sim.mppt,
            'timezone': 'utc' if sim.utc else 'local',
            'time': 'auto' if sim.frozen_time is None
                    else '%02d:%02d' % (int(sim.frozen_time), round((sim.frozen_time % 1.0) * 60)),
            'time-scale': '%g' % sim.time_scale,
            'static': 'on' if sim.static else 'off',
            'battery-state': sim.batt_state or 'auto',
            'battery-kwh': '%g' % sim.battery_kwh,
            'strict': 'on' if fake.strict else 'off',
            'chaos': '%.2f' % chaos.p,
            'seed': 'random' if chaos.seed is None else str(chaos.seed),
            'grid-voltage': '%g' % sim.grid_voltage,
            'grid-voltage-wander': '%g' % sim.grid_voltage_wander,
            'grid-frequency': '%g' % sim.grid_frequency,
            'grid-frequency-wander': '%g' % sim.grid_frequency_wander,
            'grid-outage': sim.grid_outage,
            'max-kwp': '%g' % (sim.peak_w / (1000.0 * PEAK_RATIO)),
            'modbus/profile': sim.profile.path,
            'max-clients': fake.max_clients,
            'client-timeout': fake.client_timeout,
            'max-conn-per-ip': fake.conn_gate.max_per_ip,
            'connect-acl': acl_text(fake.connect_acl),
            'modbus/auth': fake.auth or 'none',
            'metrics/enable': 'on' if fake.metrics_srv else 'off',
            'metrics/acl': acl_value_text(fake.metrics_acl),
            'log-level': logging.getLevelName(logging.getLogger('fake-inverter').getEffectiveLevel()),
            'scenario': self.scenario or 'custom',
            'dump/path': self.dump_path or 'off',
            'dump/restore-on-start': 'on' if self.dump_restore else 'off',
            'dump-interval': self.dump_interval,
            'control/port': 'off' if self.stopped else (str(self.port) if not self.is_unix else self.sockpath),
            'control/ops/verbs': ','.join(sorted(self.ops_verbs)) or 'off',
            'control/trust-uids': ','.join(str(u) for u in sorted(self.trust_uids)) or 'off',
            'control/socket-group': 'on' if self.socket_group else 'off',
            **self.audit_dump_rows(),
        }
        return self.dump_settings_tail(raw)

    # --- the whole-daemon reload (`reload`) and the dump family ride the
    # base (_save/_restore/_reload_state_path/apply_dump_settings/reload_daemon):
    # the reply leaves the wire, the process re-execs. The fresh daemon
    # re-resolves the flags and the env (the fake has no config file — F11;
    # XDG_STATE_NAME points the state file at the XDG state home, beside its
    # audit trail) and re-applies the saved overrides once (start;
    # APPLY_FIRST lands the scenario before the pins) — the flags stay the
    # owners of the base, the state file is consumed, nothing lingers. ---

