#!/usr/bin/env python3
"""Line-protocol control server: set/show the fake's settings at runtime,
scenario presets, status/reset/shutdown. Speaks one command per line, one
reply per line; the target is a TCP port (bound to 127.0.0.1) or a unix
socket path."""
import logging
import math
import os
import socket
import threading
import time

from .protocol import recv_exact
from .profile import load_profile, profile_label, resolve_profile
from .settings import SETTING_NAMES, SETTING_BY_NAME, describe_setting
from .simulator import CLOUD_MACHINES

logger = logging.getLogger('fake-sun2000')


class ControlServer:
    """Line-protocol control socket: pin values, freeze time, tune chaos — see
    the README for the command list. The target is either a TCP port (bound to
    127.0.0.1) or a unix socket path (stale files are replaced, unlinked on
    shutdown)."""

    CMDS = ('pv', 'load', 'batt', 'soc', 'cloud', 'time', 'chaos', 'status')

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
        srv.listen(4)
        logger.info('control server listening on %s (pv/load/batt/soc/cloud/time/chaos/status)', self.describe())
        while True:
            try:
                client, addr = srv.accept()
                threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
            except (OSError, RuntimeError) as e:
                logger.error('control accept failed (%s), retrying', e)
                time.sleep(0.1)

    def handle(self, client, addr):
        logger.debug('control client connected')
        try:
            client.settimeout(300)
            buf = b''
            while True:
                chunk = recv_exact(client, 1) if b'\n' not in buf else b''
                buf += chunk
                if b'\n' not in buf:
                    continue
                line, buf = buf.split(b'\n', 1)
                cmd = line.decode('utf-8', 'replace').strip()
                reply = self.command(cmd)
                logger.debug('control: %s -> %s', cmd, reply.split(' pinned')[0])
                client.sendall((reply + '\n').encode())
                if reply.startswith('bye'):
                    break
            if self.shutdown_pending and self.signalbox:
                self.signalbox.shutdown('control')   # reply is out, now really stop
        except (ConnectionError, OSError):
            pass
        except Exception as e:
            logger.error('control handler crashed (%s)', e)
        finally:
            logger.debug('control client disconnected')
            client.close()

    # every configurable of the fake: the shared registry (lib.settings)
    SETTING_KEYS = SETTING_NAMES

    # scenario presets: freeze the clock at a typical moment and release the
    # value pins, so the day simulation (and the battery machine) take over
    SCENARIOS = {'morning': 8.5, 'noon': 12.0, 'evening': 19.5, 'night': 23.0}

    def __init__(self, simulator, chaos, target, fake=None, defaults=None):
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.signalbox = None       # set by the entry; 'shutdown' hands over to it
        self.shutdown_pending = False
        self.scenario = None        # last applied preset, or None = 'custom'
        self.defaults = defaults or {}   # setting -> configured startup value ('unset')
        self.target = str(target)
        self.is_unix = not self.target.isdigit()
        self.port = int(self.target) if not self.is_unix else None
        self.sockpath = self.target if self.is_unix else None

    def _apply(self, key, value):
        sim, chaos, fake = self.simulator, self.chaos, self.fake
        val = value.lower()
        auto = val in ('auto', 'off', 'none', 'clear', 'live')
        if key in ('pv', 'load', 'batt', 'soc', 'cloud'):
            if key == 'cloud' and val in CLOUD_MACHINES:
                sim.set_cloud_mode(val)
                return val
            if key == 'cloud':
                sim.set_cloud_mode(None)   # 'auto' = clear sky: the machine is off
            sim.override(key, None if auto else float(val))
            return 'auto' if auto else '%g' % float(val)
        if key == 'time':
            if auto:
                sim.freeze(None)
                return 'auto'
            t = self._parse_hour(val)
            sim.freeze(t)
            return '%02d:%02d' % (int(t), round((t % 1.0) * 60))
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
            sim.peak_w = 0.75 * v * 1000.0
            return '%g' % v
        if key == 'profile':
            path = 'sun2000' if val in ('default', 'auto', 'none') else resolve_profile(value.strip())
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
            logging.getLogger('fake-sun2000').setLevel(level)
            return level
        if key == 'scenario':
            if val == 'custom':
                sim.freeze(None)
                for k in ('pv', 'load', 'batt', 'soc', 'cloud'):
                    sim.override(k, None)
                self.scenario = 'custom'
                return val
            if val not in self.SCENARIOS:
                raise ValueError('unknown scenario %s (try %s)' % (val, '|'.join(sorted(self.SCENARIOS))))
            sim.freeze(self.SCENARIOS[val])
            for k in ('pv', 'load', 'batt', 'soc', 'cloud'):
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
        if key in ('pv', 'load', 'batt', 'soc', 'cloud'):
            return 'auto' if ov[key] is None else '%g' % ov[key]
        if key == 'time':
            return 'auto' if sim.frozen_time is None else '%02d:%02d' % (int(sim.frozen_time), round((sim.frozen_time % 1.0) * 60))
        if key == 'chaos':
            return '%.2f' % chaos.p
        if key == 'seed':
            return 'random' if chaos.seed is None else str(chaos.seed)
        if key == 'battery':
            return 'on' if sim.battery else 'off'
        if key == 'strict':
            return 'on' if fake.strict else 'off'
        if key == 'static':
            return 'on' if sim.static else 'off'
        if key == 'max-kwp':
            return '%g' % (sim.peak_w / 750.0)
        if key == 'battery-kwh':
            return '%g' % sim.battery_kwh
        if key == 'profile':
            return '%s (%s)' % (sim.profile.description, profile_label(sim.profile.path))
        if key == 'log-level':
            return logging.getLevelName(logging.getLogger('fake-sun2000').getEffectiveLevel())
        if key == 'scenario':
            return self.scenario or 'custom'
        return '?'

    def settings(self):
        return ' '.join('%s=%s' % (k, self._get(k)) for k in self.SETTING_KEYS)

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
            return ('commands: set <%s> <value|auto|on|off>, unset <setting>, show <setting|settings>, '
                    'status, reset, shutdown, quit; help <setting> describes it' % '|'.join(self.SETTING_KEYS))
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
        if cmd == 'shutdown':
            self.shutdown_pending = True
            logger.info('control: shutdown requested')
            return 'bye shutdown'
        if cmd == 'quit':
            return 'bye'
        if cmd == 'status':
            return self.status()
        if cmd == 'show':
            if not args:
                return 'err show what? (a setting, or "settings")'
            what = args[0].lower()
            if what in ('settings', 'all'):
                return 'ok ' + self.settings()
            if what not in self.SETTING_KEYS:
                return 'err unknown setting %s (try help)' % what
            return 'ok %s=%s' % (what, self._get(what))
        if cmd == 'set':
            if len(args) < 2:
                return 'err set needs a setting and a value (try help)'
            key, value = args[0].lower(), ' '.join(args[1:])
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

    def status(self):
        sim = self.simulator
        pv_w, load_w, batt_w, soc, cloud, ov = sim.effective()
        t = sim.clock()
        pinned = ' '.join('%s=%s' % (k, ov[k]) for k in ('pv', 'load', 'batt', 'soc', 'cloud') if ov[k] is not None)
        return ('pv=%.0fW load=%.0fW batt=%.0fW soc=%s cloud=%s t=%02d:%02d chaos=%.2f hits=%d%s'
                % (pv_w, load_w, batt_w,
                   '%.1f%%' % soc if soc is not None else 'n/a',
                   sim.cloud_display(),
                   int(t), round((t % 1.0) * 60), self.chaos.p, self.chaos.hits,
                   (' pinned: ' + pinned) if pinned else ''))
