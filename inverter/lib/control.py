#!/usr/bin/env python3
"""JSON-lines control server: set/show the fake's settings at runtime
(value pins, the grid setpoint, the battery state force, cloud machines,
clock freeze, chaos), scenario presets, and the status report / registers
table / version / reset / shutdown. Speaks one command per line, one reply
line. Every request and reply is one JSON object per line (the stdlib
json module): the request = {"cmd": "<command>"}, the reply =
{"status": "ok|err|bye", "text": "<reply text>"}. The target is a TCP port
(bound to 127.0.0.1) or a unix socket path. TCP connections need a token
auth handshake when --control-token is set ({"cmd": "auth", "token": ...});
the unix socket relies on filesystem permissions instead."""
import hmac
import json
import logging
import math
import os
import socket
import threading
import time

from .audit import AuditLog
from .profile import load_profile, profile_label, resolve_profile
from .version import version_string
from .settings import SETTING_NAMES, SETTING_BY_NAME, describe_setting
from .simulator import CLOUD_MACHINES, format_clock
from .statics import CONTROL_IDLE_TIMEOUT_S, MAX_REGISTERS, PEAK_RATIO, TIME_SCALE_MAX

logger = logging.getLogger('fake-inverter')


class ControlServer:
    """JSON-lines control socket: pin values, freeze time, tune chaos — see
    the README for the command list. The target is either a TCP port (bound to
    127.0.0.1) or a unix socket path (stale files are replaced, unlinked on
    shutdown). A TCP connection must authenticate with the token first when
    one is configured; the unix socket relies on filesystem permissions."""

    def describe(self):
        return 'unix:%s' % self.sockpath if self.is_unix else '127.0.0.1:%d' % self.port

    def cleanup(self):
        if self.is_unix and self.sockpath and os.path.exists(self.sockpath):
            try:
                os.unlink(self.sockpath)
            except OSError:
                pass

    def serve(self):
        srv = socket.socket(socket.AF_UNIX if self.is_unix else socket.AF_INET, socket.SOCK_STREAM)
        if self.is_unix:
            if os.path.exists(self.sockpath):
                logger.warning('control socket %s exists, replacing it', self.sockpath)
                os.unlink(self.sockpath)
            srv.bind(self.sockpath)
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(('127.0.0.1', self.port))
        srv.listen(16)
        logger.info('control server listening on %s', self.describe())
        while True:
            try:
                client, addr = srv.accept()
                threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
            except (OSError, RuntimeError) as e:
                logger.error('control accept failed (%s), retrying', e)
                time.sleep(0.1)

    def framed(self, line, who, authed):
        """One wire frame in, one out: parse {"cmd": ...}, gate the TCP auth,
        run the command, return (cmd, reply-obj, internal-reply). The text of
        a multi-line reply keeps its embedded newlines; the '.' terminator of
        the internal form is stripped (the JSON frame needs no framing)."""
        try:
            obj = json.loads(line) if line else {}
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or not isinstance(obj.get('cmd'), str):
            return '', {'status': 'err',
                        'text': 'malformed request: expected {"cmd": "<command>"} JSON'}, 'err malformed request'
        cmd = obj['cmd']
        if self.token and not self.is_unix and cmd.lower() != 'auth' and not authed:
            return cmd, {'status': 'err', 'text': 'authenticate first: {"cmd": "auth", "token": "..."}'}, \
                'err authenticate first'
        if cmd.lower() == 'auth':
            given = obj.get('token')
            if self.token and isinstance(given, str) and hmac.compare_digest(given, self.token):
                return 'auth', {'status': 'ok', 'text': 'authenticated'}, 'ok authenticated'
            return 'auth', {'status': 'err', 'text': 'bad token'}, 'err bad token'
        reply = self.command(cmd)
        if reply.endswith('\n.'):        # a legacy multi-line terminator; the JSON frames need none
            reply = reply[:-2]
        status, _, text = reply.partition(' ')
        return cmd, {'status': status, 'text': text}, reply

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
        authed = False
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
                if b'\n' not in buf:
                    continue
                line, buf = buf.split(b'\n', 1)
                cmd, obj, reply = self.framed(line.decode('utf-8', 'replace').strip(), who, authed)
                if cmd == 'auth':
                    ok = reply.startswith('ok')
                    if ok:
                        authed = True
                    elif self.audit:
                        self.audit.event('AUTH-FAIL', 'peer=%s' % who)
                elif self.audit and cmd.lower() != 'ping':
                    self.audit.event('COMMAND', "peer=%s '%s' -> %s" % (who, cmd, reply.split(' ', 1)[0]))
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

    # scenario presets: freeze the clock at a typical moment and release the
    # value pins, so the day simulation (and the battery machine) take over
    SCENARIOS = {'morning': 8.5, 'noon': 12.0, 'evening': 19.5, 'night': 23.0}

    def __init__(self, simulator, chaos, target, fake=None, defaults=None, log_replies=False, audit=None, token=None):
        self.log_replies = log_replies   # DEBUG also logs the full command output
        self.audit = audit               # the INV audit trail (lib.audit), None = off
        self.token = token               # the TCP auth token; None = no auth (the unix = the perms)
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.signalbox = None       # set by the entry; 'shutdown' hands over to it
        self.shutdown_pending = False
        self.scenario = None        # last applied preset, or None = 'custom'
        self.defaults = defaults or {}   # setting -> configured startup value ('unset')
        self.clients = set()             # the live control sockets (announce_exit)
        self.clients_lock = threading.Lock()
        self.target = str(target)
        self.started = time.monotonic()
        self.is_unix = not self.target.isdigit()
        self.port = int(self.target) if not self.is_unix else None
        self.sockpath = self.target if self.is_unix else None

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
            if not 1 <= v <= 500:
                raise ValueError('grid-voltage must be a sane nominal voltage (1-500 V)')
            sim.grid_voltage = v
            return '%g' % v
        if key == 'grid-frequency':
            v = float(val)
            if not 1 <= v <= 500:
                raise ValueError('grid-frequency must be a sane nominal frequency (1-500 Hz)')
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
        if key == 'log-level':
            level = val.upper()
            if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
                raise ValueError('log level must be DEBUG|INFO|WARNING|ERROR')
            logging.getLogger('fake-inverter').setLevel(level)
            return level
        if key == 'scenario':
            if val == 'custom':
                sim.freeze(None)
                for k in ('pv', 'load', 'batt', 'grid', 'soc', 'cloud'):
                    sim.override(k, None)
                self.scenario = 'custom'
                return val
            if val not in self.SCENARIOS:
                raise ValueError('unknown scenario %s (try %s)' % (val, '|'.join(sorted(self.SCENARIOS))))
            sim.freeze(self.SCENARIOS[val])
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
        if key == 'profile':
            return '%s (%s)' % (sim.profile.description, profile_label(sim.profile.path))
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger('fake-inverter').getEffectiveLevel())
        if key == 'scenario':
            return self.scenario or 'custom'
        return '?'

    def settings(self):
        """Every setting with its value: one key=value per line (scriptable)."""
        return 'ok settings\n' + '\n'.join('%s=%s' % (k, self._get(k)) for k in self.SETTING_KEYS)

    def command(self, line):
        if not line:
            return 'err empty command'
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
        if cmd == 'ping':                 # keep-alive from fake_cli
            return 'ok pong'
        if cmd in ('help', '?'):
            if args:
                what = args[0].lower()
                if what in SETTING_BY_NAME:
                    return 'ok %s' % describe_setting(what)
                return 'err unknown setting %s (try help)' % what
            return ('commands: set <%s> <value|auto|on|off>, unset <setting>, show <setting|status|settings>, '
                    'reset, shutdown, quit; help <setting> describes it' % '|'.join(self.SETTING_KEYS))
        if cmd == 'unset':
            if not args:
                return 'err unset needs a setting (try help)'
            key = args[0].lower()
            if key not in self.defaults:
                return 'err unknown setting %s (try help)' % key
            shown = self._apply(key, self.defaults[key])
            logger.info('control: unset %s -> ok %s=%s', key, key, shown)
            return 'ok %s=%s %s' % (key, shown, self.status())
        if cmd == 'reset':
            pins = self.simulator.reset_overrides()
            overlay = 0
            if self.fake:
                overlay = len(self.fake.overlay)
                self.fake.overlay.clear()
            self.scenario = None
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
                return 'err show what? (a setting, "status", or "settings")'
            what = args[0].lower()
            if what == 'status':
                return self.status_report()
            if what == 'version':
                return 'ok fake-inverter %s' % version_string()
            if what in ('settings', 'all'):
                return 'ok ' + self.settings()
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
                # a multi-line reply: the clients read on until the '.' terminator
                w1 = max(len(r[0]) for r in rows)
                w2 = max(len(r[1]) for r in rows)
                w3 = max(len(r[2]) for r in rows)
                w4 = max(len(r[3]) for r in rows)
                table = '\n'.join('%-*s | %*s | %*s | %*s' % (w1, a, w2, b, w3, c, w4, d)
                                  for a, b, c, d in rows)
                return 'ok registers (%d)\n%s' % (len(rows), table)
            if what not in self.SETTING_KEYS:
                return 'err unknown setting %s (try help)' % what
            return 'ok %s=%s' % (what, self._get(what))
        if cmd == 'set':
            if len(args) < 2:
                return 'err set needs a setting and a value (try help)'
            key, value = args[0].lower(), ' '.join(args[1:])
            if key == 'register':   # the control write = the Modbus write: the same
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
            if key not in self.SETTING_KEYS:
                return 'err unknown setting %s (try help)' % key
            try:
                shown = self._apply(key, value)
            except ValueError as e:
                return 'err %s' % e
            if key != 'scenario':
                self.scenario = None   # a manual pin turns the state 'custom'
            return 'ok %s=%s %s' % (key, shown, self.status())
        return 'err unknown command %s (try help)' % cmd

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
            'now       %s %s%s, uptime %d s' % (format_clock(t),
                'utc' if sim.utc else 'local',
                ' x%g' % sim.time_scale if sim.time_scale != 1.0 else '',
                int(time.monotonic() - self.started)),
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
        ]
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
                 'uptime=%d' % int(time.monotonic() - self.started),
                 'chaos=%.2f' % self.chaos.p, 'chaos_hits=%d' % self.chaos.hits,
                 'pinned=%s' % pinned, 'profile=%s' % sim.profile.description]
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
