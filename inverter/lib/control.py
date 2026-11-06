#!/usr/bin/env python3
"""JSON-lines control server: set/show the fake's settings at runtime
(value pins, the grid setpoint, the battery state force, cloud machines,
clock freeze, chaos), scenario presets, and the status report / registers
table / version / reset / shutdown. Speaks one command per line, one reply
line. Every request and reply is one JSON object per line (the stdlib
json module): the request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. Connections need a token auth
handshake when --control-token is set ({"cmd": "auth", "token": ...}); over
the unix socket a kernel-vouched peer (root, the daemon's own user or
--control-trust-uids — SO_PEERCRED) skips the handshake. A second,
read-only token (--control-ops-token) authenticates into the show/clear
verbs only — the ops shift against the admin key, both audited."""
import hmac
import json
import logging
import math
import os
import socket
import threading
import time

from common.audit import AuditLog
from common.config import acl_summary, acl_text, parse_acl
from common.cred import peer_uid
from common.human import secs
from common.wiresec import verify_request_mac, sign_reply, proof_tag, ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, role_allows, role_tag
from common.options import control_command, grouped_rows, match_setting_path, describe_node
from .metrics import MetricsServer, describe_metrics
from .profile import load_profile, profile_label, resolve_profile
from common.version import version_string
from .options import OPTIONS, SETTING_NAMES, SETTING_BY_NAME, describe_setting, SHOW_BY_LIVE, NODE_BY_NAME
from .simulator import CLOUD_MACHINES, format_clock
from .statics import CONTROL_IDLE_TIMEOUT_S, CONTROL_LINE_CAP, LOG_LEVELS, MAX_REGISTERS, PEAK_RATIO, SCENARIOS, TIME_SCALE_MAX, MAX_REGISTERS, PEAK_RATIO, TIME_SCALE_MAX

logger = logging.getLogger('fake-inverter')

# The registry-driven bounds: the row's min/max (inclusive) are the one
# home for a knob's range — the branches parse and plumb, the row gates.
OPTION_BY_LIVE = {o.live: o for o in OPTIONS if o.live}
TYPED_CONVS = (int, float, str)

MAX_LINE = CONTROL_LINE_CAP   # the pre-auth line-buffer cap (drop past it)


class ControlServer:
    """JSON-lines control socket: pin values, freeze time, tune chaos — see
    the README for the command list. The target is either a TCP port (bound to
    127.0.0.1) or a unix socket path (stale files are replaced, unlinked on
    shutdown). A connection must authenticate with the token first when one
    is configured — over the unix socket a kernel-vouched peer (root, the
    daemon's own user or trust_uids — SO_PEERCRED) skips the handshake. A
    second, read-only token (ops_token) may be configured beside the admin
    token: it authenticates into the show/clear verbs only — no set/unset,
    no reset, no shutdown (common/wiresec.py's roles)."""

    def describe(self):
        return 'unix:%s' % self.sockpath if self.is_unix else '127.0.0.1:%d' % self.port

    def cleanup(self):
        if self.is_unix and self.sockpath and os.path.exists(self.sockpath):
            try:
                os.unlink(self.sockpath)
            except OSError:
                pass

    def trusted_peer(self, client, who):
        """The peer-cred auth on the unix control socket: with a token
        configured, a peer the kernel vouches for — root, the daemon's own
        user or one of trust_uids — is authenticated without the token (a
        local systemd unit speaks without sharing the secret) and holds the
        admin role. TCP peers always need a token (admin or ops)."""
        if not (self.token and self.is_unix):
            return None
        uid = peer_uid(client)
        if uid is None:
            return None
        if uid == 0 or uid == os.getuid() or uid in self.trust_uids:
            logger.debug('control client from %s: trusted peer uid %d, no token required', who, uid)
            return ROLE_ADMIN
        logger.info('control client from %s: peer uid %d is not trusted, the token is required', who, uid)
        return None

    def session_key(self, role):
        """The hmac key of one session's role: the ops sessions sign and
        verify with the ops token, everything else (admin, trusted peer,
        pre-auth) with the admin token."""
        return self.ops_token if role == ROLE_OPS else self.token

    def auth_role(self, given):
        """Which role a presented token authenticates into (hmac.compare_digest
        against both keys): the admin token, the ops token, or None."""
        if isinstance(given, str):
            if self.token and hmac.compare_digest(given, self.token):
                return ROLE_ADMIN
            if self.ops_token and hmac.compare_digest(given, self.ops_token):
                return ROLE_OPS
        return None

    def serve(self):
        srv = socket.socket(socket.AF_UNIX if self.is_unix else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if self.is_unix:
                if os.path.exists(self.sockpath):
                    logger.warning('control socket %s exists, replacing it', self.sockpath)
                    os.unlink(self.sockpath)
                srv.bind(self.sockpath)
                # the mode is not left to the umask: 0600 = owner only,
                # 0660 with --control-socket-group (a local group shares it)
                os.chmod(self.sockpath, 0o660 if self.socket_group else 0o600)
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(('127.0.0.1', self.port))
            srv.listen(64)   # the backlog above the client limit: a connect burst must not RST
        except OSError as e:
            logger.error('control server cannot bind %s: %s (use --control-port 0 to disable it)', self.describe(), e)
            return
        logger.info('control server listening on %s%s',
                    self.describe(), (', token auth required on TCP' if self.token and not self.is_unix else '')
                    + (', read-only ops token accepted' if self.ops_token else ''))
        while True:
            try:
                client, addr = srv.accept()
                threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
            except (OSError, RuntimeError) as e:
                logger.error('control accept failed (%s), retrying', e)
                time.sleep(0.1)

    def framed(self, line, who, role):
        """One wire frame in, one out: parse {"cmd": ...}, gate the TCP auth,
        gate the ops role (show/clear only), verify the frame mac keyed by
        the session's token, run the command. Returns (cmd, reply-obj,
        internal-reply, role) — the role so the auth reply can promote the
        session. The text of a multi-line reply keeps its embedded newlines;
        the '.' terminator of the internal form is stripped (the JSON frame
        needs no framing)."""
        try:
            obj = json.loads(line) if line else {}
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or not isinstance(obj.get('cmd'), str):
            return '', {'status': 'err',
                        'text': 'malformed request: expected {"cmd": "<command>"} JSON'}, 'err malformed request', role
        cmd = obj['cmd']
        if self.token and cmd.lower() != 'auth' and role is None:
            return cmd, {'status': 'err', 'text': 'authenticate first: {"cmd": "auth", "token": "..."}'}, \
                'err authenticate first', role
        if cmd.lower() == 'auth':
            granted = self.auth_role(obj.get('token'))
            if granted:
                key = self.session_key(granted)
                reply = 'ok authenticated'
                return 'auth', {'status': 'ok', 'text': 'authenticated', 'mac': sign_reply(key, reply)}, reply, granted
            return 'auth', {'status': 'err', 'text': 'bad token'}, 'err bad token', role
        key = self.session_key(role)
        if key and obj.get('mac') is None and not self.is_unix:
            return cmd, {'status': 'err',
                         'text': 'unsigned command rejected: TCP commands carry the hmac-sha256 of the command, keyed by the token'}, \
                'err unsigned command', role
        if key and obj.get('mac') is not None and not verify_request_mac(key, cmd, obj.get('mac')):
            return cmd, {'status': 'err',
                         'text': 'the command mac does not verify (tampered or corrupted frame)'}, 'err bad command mac', role
        if not role_allows(role, cmd, self.ops_verbs):
            verb = command_verb(cmd) or cmd
            text = ('forbidden: the ops token runs the %s verbs only (%s needs the admin token)'
                    % ('/'.join(sorted(self.ops_verbs)), verb))
            reply = 'err ' + text
            reply_obj = {'status': 'err', 'text': text}
            if key:
                reply_obj['mac'] = sign_reply(key, reply)
            logger.warning('control: ops session from %s denied %r (read-only role)', who, cmd)
            return cmd, reply_obj, reply, role
        reply = self.command(cmd)
        status, _, text = reply.partition(' ')
        reply_obj = {'status': status, 'text': text}
        if key:
            reply_obj['mac'] = sign_reply(key, reply)
        return cmd, reply_obj, reply, role

    @staticmethod
    def peer(addr):
        """Where the client sits: an IP:port for TCP, the socket for unix."""
        if isinstance(addr, (tuple, list)) and len(addr) >= 2:
            return '%s:%d' % (addr[0], addr[1])
        return 'unix socket'

    def announce_exit(self, reason):
        """The daemon is going down: send every connected control client a
        bye frame (the consoles print the notice and exit instead of trying
        to reconnect to a dead fake) and close their sockets."""
        frame = (json.dumps({'status': 'bye',
                             'text': 'daemon-exit: the fake inverter is shutting down (%s)' % reason})
                 + '\n').encode()
        with self.clients_lock:
            clients, self.clients = list(self.clients), set()
        for client in clients:
            try:
                client.sendall(frame)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass

    def handle(self, client, addr):
        who = self.peer(addr)
        logger.debug('control client connected from %s', who)
        role = self.trusted_peer(client, who)   # the peer-cred shortcut = the admin role; TCP starts unauthenticated
        with self.clients_lock:
            self.clients.add(client)
        try:
            client.settimeout(CONTROL_IDLE_TIMEOUT_S)
            buf = b''
            while True:
                if b'\n' not in buf:      # buffered reads: a 1 MB frame must not
                    chunk = client.recv(65536)   # cost a syscall per byte
                    if not chunk:
                        break
                else:
                    chunk = b''
                buf += chunk
                if len(buf) > MAX_LINE:   # no newline = no frame: drop the amplifier
                    logger.warning('control client from %s: the line exceeded %d bytes, dropping it', who, MAX_LINE)
                    break
                if b'\n' not in buf:
                    continue
                line, buf = buf.split(b'\n', 1)
                cmd, obj, reply, role = self.framed(line.decode('utf-8', 'replace').strip(), who, role)
                if cmd == 'auth':
                    ok = reply.startswith('ok')
                    if not ok and self.audit:
                        self.audit.event('AUTH-FAIL', 'peer=%s' % who)
                elif self.audit and cmd.lower() != 'ping':
                    self.audit.event('COMMAND', "peer=%s%s '%s'%s -> %s"
                                     % (who, role_tag(role), cmd, proof_tag(obj), reply.split(' ', 1)[0]))
                if self.log_replies:
                    logger.debug('control from %s: %s -> %s', who, cmd, reply)
                else:
                    logger.debug('control from %s: %s', who, cmd)
                client.sendall((json.dumps(obj, ensure_ascii=False) + '\n').encode())
                if reply.startswith('bye'):
                    break
            if self.shutdown_pending and self.signalbox:
                self.signalbox.shutdown('control')   # reply is out, now really stop
        except (ConnectionError, OSError):
            pass
        except Exception as e:
            logger.error('control handler crashed (%s)', e)
        finally:
            logger.debug('control client from %s disconnected', who)
            with self.clients_lock:
                self.clients.discard(client)
            client.close()

    # every configurable of the fake: the shared registry (lib.settings)
    SETTING_KEYS = SETTING_NAMES

    # the scenario presets live in static.json (lib.statics.SCENARIOS):
    # freeze the clock at a typical moment and release the value pins, so
    # the day simulation (and the battery machine) take over

    def __init__(self, simulator, chaos, target, fake=None, defaults=None, log_replies=False, audit=None, token=None,
                 trust_uids=None, socket_group=False, ops_token=None, ops_verbs=None, startup_values=None):
        self.log_replies = log_replies   # DEBUG also logs the full command output
        self.audit = audit               # the INV audit trail (common.audit), None = off
        self.token = token               # the control auth token (the admin role); None = no auth (the unix = the perms)
        self.ops_token = ops_token       # the read-only ops token (the ops role); None = off
        self.ops_verbs = frozenset(v.lower() for v in (ops_verbs or OPS_VERBS))   # the ops role's RBAC policy
        self.startup_values = startup_values or {}   # the set-grammar form of the startup options (show config)
        self.trust_uids = trust_uids or frozenset()   # extra peer uids the unix socket trusts without the token
        self.socket_group = bool(socket_group)   # chmod 0660 instead of 0600 on the unix socket
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.signalbox = None       # set by the entry; 'shutdown' hands over to it
        self.shutdown_pending = False
        self.scenario = None        # last applied preset, or None = 'custom'
        self.defaults = defaults or {}   # setting -> configured startup value ('unset')
        self.overridden = set()          # settings changed live (`show status` carries the overridden= row)
        self.clients = set()             # the live control sockets (announce_exit)
        self.clients_lock = threading.Lock()
        self.target = str(target)
        self.started = time.monotonic()
        self.is_unix = not self.target.isdigit()
        self.port = int(self.target) if not self.is_unix else None
        self.sockpath = self.target if self.is_unix else None

    def config_mapping(self):
        """The knob -> control-command mapper (help config): every option of
        the registry under its display group (the row's `group`, else its
        section), with the command that changes it on a running fake — or
        the restart note when the knob is startup-only."""
        from .options import OPTIONS
        from common.options import section_title
        lines = ['ok config mapping']
        for key, rows in grouped_rows(OPTIONS):
            lines.append('# --- %s ---' % section_title(key))
            for o in rows:
                lines.append('%-24s %s' % (o.name, control_command(o)))
        return '\n'.join(lines)

    def knobs_dictionary(self):
        """The dictionary of all knobs (show knobs): every option of the
        registry under its section, with its flag, its env twin(s) when it
        has one, its home section, the control command that changes it and
        the secret marker."""
        from .options import OPTIONS
        from common.options import knob_dictionary
        return knob_dictionary(OPTIONS, who='the fake inverter')

    def show_config(self):
        """The startup options as a set-grammar script — the argv that would
        restart this fake (the secrets never render; the live `set` values
        are runtime state, not here)."""
        from .options import OPTIONS
        from common.options import render_config_script
        script = render_config_script(OPTIONS, dict(self.startup_values),
                                      comment='generated by show config — the argv that would restart this fake (secrets hidden)')
        return 'ok config\n' + script

    def _gate_range(self, key, v, what=''):
        """The row's min/max (inclusive) — the registry is the one home for
        a knob's bounds; the branch parses and plumbs, the row gates."""
        opt = OPTION_BY_LIVE.get(key)
        if opt is None or opt.conv not in TYPED_CONVS:
            return
        if (opt.min is not None and not v >= opt.min) or (opt.max is not None and not v <= opt.max):
            raise ValueError('%s must be %s..%s%s' % (key, opt.min, opt.max, (' ' + what) if what else ''))

    def _apply(self, key, value):
        sim, chaos, fake = self.simulator, self.chaos, self.fake
        val = value.lower()
        auto = val in ('auto', 'off', 'none', 'clear', 'live')
        if key in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud'):
            if key == 'cloud' and val in CLOUD_MACHINES:
                sim.set_cloud_mode(val)
                return val
            if key == 'cloud':
                sim.set_cloud_mode(None)   # 'clear' = clear sky: the machine is off
            sim.override(key, None if auto else float(val))
            if auto:
                return 'clear' if key == 'cloud' else 'auto'
            return '%g' % float(val)
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
            v = float(val)
            if not math.isfinite(v) or v <= 0 or v > TIME_SCALE_MAX:
                raise ValueError('time-scale must be 0 < N <= %g (a day per minute)' % TIME_SCALE_MAX)
            sim.set_time_scale(v)
            return 'x%g' % v
        if key == 'chaos':
            if val in ('off', 'none'):
                chaos.set_probability(0.0)
            else:
                chaos.set_probability(float(val))
            return '%.2f' % chaos.p
        if key == 'seed':
            if val in ('random', 'none', 'auto'):
                chaos.reseed(None)
                return 'random'
            chaos.reseed(int(val))
            return str(int(val))
        if key == 'battery':
            sim.battery = val in ('on', 'true', '1', 'yes')
            return 'on' if sim.battery else 'off'
        if key == 'mppt':
            if val not in ('both', 'east', 'west', 'none'):
                raise ValueError('mppt must be both|east|west|none')
            sim.mppt = val
            return val
        if key == 'battery-state':
            if val not in ('auto', 'charging', 'discharging'):
                raise ValueError('battery-state must be auto|charging|discharging')
            if val != 'auto' and not sim.battery:
                raise ValueError('battery-state needs the battery on (set battery on)')
            sim.batt_state = None if val == 'auto' else val
            return val
        if key == 'grid-voltage':
            v = float(val)
            self._gate_range(key, v, 'V')
            sim.grid_voltage = v
            return '%g' % v
        if key == 'grid-frequency':
            v = float(val)
            self._gate_range(key, v, 'Hz')
            sim.grid_frequency = v
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
            fake.strict = val in ('on', 'true', '1', 'yes')
            return 'on' if fake.strict else 'off'
        if key == 'static':
            sim.static = val in ('on', 'true', '1', 'yes')
            return 'on' if sim.static else 'off'
        if key == 'max-kwp':
            v = float(val)
            if not math.isfinite(v) or v <= 0:
                raise ValueError('max-kwp must be a positive kW value')
            sim.peak_w = PEAK_RATIO * v * 1000.0
            return '%g' % v
        if key == 'profile':
            path = resolve_profile('sun2000' if val in ('default', 'auto', 'none') else value.strip())
            try:
                m = load_profile(path)
            except SystemExit as e:
                raise ValueError(str(e))
            sim.set_profile(m)
            return '%s (%s)' % (m.description, profile_label(m.path))
        if key == 'battery-kwh':
            v = float(val)
            if not math.isfinite(v) or v <= 0:
                raise ValueError('battery-kwh must be a positive kWh value')
            sim.battery_kwh = v
            return '%g' % v
        if key == 'max-clients':
            v = int(float(val))
            self._gate_range(key, v)
            if fake:
                fake.max_clients = v
                return str(v)
            raise ValueError('no modbus device attached')
        if key == 'max-conn-per-ip':
            v = int(float(val))
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
        if key == 'metrics-server':
            if not fake:
                raise ValueError('no modbus device attached')
            if val in ('on', 'true', '1', 'yes'):
                if fake.metrics_srv:
                    return 'on'
                if not fake.metrics_token:
                    from common.config import is_loopback_host
                    if not is_loopback_host(fake.metrics_listen[0]):
                        logger.warning('serving /metrics on %s:%d without a token: the values are production-shaped '
                                       'even though this is a test tool — set --metrics-token', *fake.metrics_listen)
                srv = MetricsServer(sim, chaos, fake, self, fake.metrics_listen, token=fake.metrics_token,
                                    max_clients=fake.metrics_caps[0], client_timeout=fake.metrics_caps[1],
                                    max_per_ip=fake.metrics_caps[2])
                srv.start()
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
            v = float(val)
            self._gate_range(key, v, 'seconds')
            if fake:
                fake.client_timeout = v
                return '%gs' % v if v else 'never'
            raise ValueError('no modbus device attached')
        if key == 'log-level':
            level = val.upper()
            if level not in LOG_LEVELS:
                raise ValueError('log level must be one of %s' % ', '.join(LOG_LEVELS))
            logging.getLogger('fake-inverter').setLevel(level)
            return level
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
        raise ValueError('unknown setting %s' % key)

    def _parse_hour(self, text):
        h, m = text.split(':')
        t = int(h) + int(m) / 60.0
        if not 0 <= t < 24:
            raise ValueError('time out of range (00:00-23:59)')
        return t

    def _get(self, key):
        sim, ov, fake, chaos = self.simulator, self.simulator.overrides(), self.fake, self.chaos
        if key in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud'):
            if ov[key] is None:
                return 'clear' if key == 'cloud' else 'auto'
            return '%g' % ov[key]
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
        if key == 'battery':
            return 'on' if sim.battery else 'off'
        if key == 'mppt':
            return sim.mppt
        if key == 'battery-state':
            return sim.batt_state or 'auto'
        if key == 'grid-voltage':
            return '%g' % sim.grid_voltage
        if key == 'grid-frequency':
            return '%g' % sim.grid_frequency
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
        if key == 'metrics-server':
            return ('on' if fake.metrics_srv else 'off') if fake else '?'
        if key == 'client-timeout':
            return ('%gs' % fake.client_timeout if fake.client_timeout else 'never') if fake else '?'
        if key == 'profile':
            return '%s (%s)' % (sim.profile.description, profile_label(sim.profile.path))
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger('fake-inverter').getEffectiveLevel())
        if key == 'scenario':
            return self.scenario or 'custom'
        return '?'

    def command(self, line):
        if not line:
            return 'err empty command'
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
        if cmd == 'ping':                 # keep-alive from fake_cli
            return 'ok pong'
        if cmd in ('help', '?'):
            if args:
                if args[0].lower() == 'config':
                    return self.config_mapping()
                if args[0].lower() == 'knobs':
                    return self.knobs_dictionary()
                key, rest = match_setting_path(args, SETTING_BY_NAME)
                if key is not None and not rest:
                    return 'ok %s' % describe_setting(key)
                return 'err unknown setting %s (try help)' % ' '.join(args)
            return ('commands: set <%s> <value|auto|on|off>, unset <setting>, show <setting|status|connections|config|knobs>, '
                    'reset, shutdown, quit; help <setting> describes it, help config maps every knob to its control command, '
                    'show knobs prints the full dictionary'
                    % '|'.join(self.SETTING_KEYS))
        if cmd == 'show' and args and args[0].lower() == 'config':
            return self.show_config()
        if cmd == 'show' and args and args[0].lower() == 'knobs':
            return self.knobs_dictionary()
        if cmd == 'unset':
            if not args:
                return 'err unset needs a setting (try help)'
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is None or rest or key not in self.defaults:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            shown = self._apply(key, self.defaults[key])
            self.overridden.discard(key)
            logger.info('control: unset %s -> ok %s=%s', key, key, shown)
            return 'ok %s=%s %s' % (key, shown, self.status())
        if cmd == 'reset':
            pins = self.simulator.reset_overrides()
            overlay = 0
            if self.fake:
                overlay = len(self.fake.overlay)
                self.fake.overlay.clear()
            self.scenario = None
            self.overridden.difference_update(('pv', 'load', 'batt', 'grid', 'soc', 'cloud',
                                               'battery-state', 'grid-outage', 'scenario'))
            logger.info('control: reset cleared %d pin(s) + %d overlay register(s)', pins, overlay)
            return 'ok reset (%d pin(s), %d overlay register(s) cleared) %s' % (pins, overlay, self.status())
        if cmd == 'inspect':
            return self.inspect()
        if cmd == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        if cmd == 'quit':
            return 'bye'
        if cmd == 'show':
            if not args:
                return 'err show what? (a setting, "status", or "registers")'
            what = args[0].lower()
            if what == 'status':
                return self.status_report()
            if what == 'connections':
                return 'ok connections ' + self.connections_line()
            if what == 'version':
                return 'ok fake-inverter %s' % version_string()
            if what == 'registers':
                entries = self.simulator.profile.entries
                if not entries:
                    return 'ok registers: (the profile has no registers)'
                # name | register | type | current value (NaN = the profile
                # maps a value the simulator is not calculating right now,
                # e.g. the battery block with the battery off)
                vals = self.simulator.values()
                overlay = dict(self.fake.overlay) if self.fake else {}
                rows = []
                for name, addr, typ, _scale in entries:
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
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is not None and not rest:
                word = SHOW_BY_LIVE.get(key)
                if word:
                    return self.command('show ' + word)   # a show command's report, by its word
                return 'ok %s=%s' % (key, self._get(key))
            if len(args) == 1 and args[0].lower() in NODE_BY_NAME:
                return 'ok %s' % describe_node(OPTIONS, args[0].lower())
            if key is not None and rest:
                return 'err %s: unexpected %s' % (key, ' '.join(rest))
            return 'err unknown setting %s (try help)' % ' '.join(args)
        if cmd == 'set':
            if len(args) < 2:
                return 'err set needs a setting and a value (try help)'
            if args[0].lower() == 'register':   # the control write = the Modbus write: the same
                if not self.fake:   # overlay FC06/FC16 land in, so the scrapers see it
                    return 'err no modbus device attached'
                if len(args) < 3:
                    return 'err set register needs an address and a value'
                try:
                    addr, val = int(args[1]), int(args[2])
                except ValueError:
                    return 'err register address and value must be integers'
                if not 0 <= addr <= MAX_REGISTERS - 1 or not 0 <= val <= MAX_REGISTERS - 1:
                    return 'err register address/value out of range (0..%d)' % (MAX_REGISTERS - 1)
                self.fake.overlay[addr] = val
                logger.info('control: set register %d=%d (write overlay)', addr, val)
                return 'ok register %d=%d (the write overlay, the scrapers read it)' % (addr, val)
            key, rest = match_setting_path(args, SETTING_BY_NAME)
            if key is None:
                return 'err unknown setting %s (try help)' % ' '.join(args)
            if not rest:
                return 'err set needs a setting and a value (try help)'
            value = ' '.join(rest)
            try:
                shown = self._apply(key, value)
            except ValueError as e:
                return 'err %s' % e
            if key != 'scenario':
                self.scenario = None   # a manual pin turns the state 'custom'
            self.overridden.add(key)
            return 'ok %s=%s %s' % (key, shown, self.status())
        return 'err unknown command %s (try help)' % cmd

    def connections_line(self):
        """The fake's live Modbus clients: peer, connection age, requests
        served (the cache's show connections, pointed at the simulator)."""
        if not self.fake:
            return 'err no modbus device attached'
        with self.fake.client_lock:
            if not self.fake.clients:
                return 'none'
            now = time.monotonic()
            return '; '.join('%s connected %s requests %d' % (k, secs(now - v['since']), v['requests'])
                             for k, v in sorted(self.fake.clients.items()))

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
            'now       %s %s%s, uptime %s' % (format_clock(t),
                'utc' if sim.utc else 'local',
                ' x%g' % sim.time_scale if sim.time_scale != 1.0 else '',
                secs(time.monotonic() - self.started)),
            'power     pv %g W, load %g W, grid %g W' % (pv_w, load_w,
                0.0 if sim.outage_active() else pv_w - batt_w - load_w),
            'battery   %s' % ('%g W, SoC %s, state %s' % (batt_w,
                '%.1f %%' % soc if soc is not None else 'n/a', sim.batt_state or 'auto')
                if sim.battery else 'off'),
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
            rows.append('modbus    %s:%d, clients %d (limit %s, timeout %s, per-ip %s, connect-acl %s)'
                        % (la[0], la[1], self.fake.client_count, self.fake.max_clients or 'none',
                           secs(self.fake.client_timeout) if self.fake.client_timeout else 'none',
                           self.fake.conn_gate.max_per_ip or 'none',
                           'any' if self.fake.connect_acl is None
                           else ('none' if not self.fake.connect_acl else '%d network(s)' % len(self.fake.connect_acl))))
        return 'ok inspect\n' + '\n'.join(rows)

    def status_report(self):
        """The status as a compact multi-field report: one stable key=value
        per line (scriptable)."""
        sim = self.simulator
        pv_w, load_w, batt_w, soc, cloud, ov = sim.effective()
        grid_w = 0.0 if sim.outage_active() else pv_w - batt_w - load_w
        t = sim.clock()
        pinned = ','.join('%s=%s' % (k, ov[k]) for k in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud')
                          if ov[k] is not None) or 'none'
        rows = ['pv=%d' % round(pv_w), 'load=%d' % round(load_w), 'grid=%d' % round(grid_w),
                'mppt=%s' % sim.mppt, 'grid_voltage=%g' % sim.grid_voltage,
                'grid_outage=%s' % sim.outage_display(),
                'timezone=%s' % ('utc' if sim.utc else 'local')]
        if sim.battery:
            rows += ['battery=%d' % round(batt_w),
                     'soc=%s' % ('%.1f' % soc if soc is not None else 'n/a'),
                     'battery_state=%s' % (sim.batt_state or 'auto')]
        rows += ['cloud=%s' % sim.cloud_display(),
                 'clock=%s' % format_clock(t), 'time_scale=x%g' % sim.time_scale,
                 'uptime=%s' % secs(time.monotonic() - self.started),
                 'chaos=%.2f' % self.chaos.p, 'chaos_hits=%d' % self.chaos.hits,
                 'pinned=%s' % pinned, 'profile=%s' % sim.profile.description,
                 'metrics=%s' % getattr(self.fake, 'metrics_desc', 'off'),
                 'overridden=%s' % (','.join(sorted(self.overridden)) or 'none')]
        if self.fake:
            rows.append('clients=%d' % self.fake.client_count)
            rows.append('connect_acl=%s' % acl_summary(self.fake.connect_acl))
        return 'ok status\n' + '\n'.join(rows)

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
