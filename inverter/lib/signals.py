#!/usr/bin/env python3
"""Signal handling mirroring the scraper/cache family: SIGHUP reloads the
environment layer (keep-last-good), SIGUSR1 resets the scenario,
SIGTERM/SIGINT shut down gracefully with a session summary."""
import logging
import os
import signal
import sys
import threading
import time

from .profile import load_profile, profile_label

logger = logging.getLogger('fake-inverter')


def parse_time(text):
    """HH:MM -> float hours; anything else raises ValueError."""
    h, m = text.split(':')
    t = int(h) + int(m) / 60.0
    if not 0 <= t < 24:
        raise ValueError(t)
    return t


class SignalBox:
    """Installs the family signal set; a watcher thread does the work so the
    Modbus accept loop (main thread) is never interrupted mid-request."""

    def __init__(self, simulator, chaos, fake, control=None, audit=None):
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.control = control
        self.audit = audit               # the INV audit trail (common.audit), None = off
        self.started = time.monotonic()
        self.received = []          # signal names, drained by the watcher
        self.stop = False

    def install(self):
        for sig in (signal.SIGHUP, signal.SIGUSR1, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._on)
        threading.Thread(target=self.watch, daemon=True).start()

    def _on(self, signum, frame):
        self.received.append(signal.Signals(signum).name)

    def watch(self):
        while not self.stop:
            if self.received:
                name, self.received = self.received[0], self.received[1:]
                try:
                    if name == 'SIGHUP':
                        self.reload()
                    elif name == 'SIGUSR1':
                        self.reset()
                    else:
                        self.shutdown(name)   # SIGTERM / SIGINT
                        return
                except Exception as e:
                    logger.error('%s handling crashed (%s)', name, e)
            time.sleep(0.2)

    # ---- SIGHUP: re-read the environment layer, all-or-nothing

    def reload(self):
        plan = []
        env = os.environ
        try:
            v = env.get('CHAOS')
            if v:
                plan.append(('chaos=%g' % float(v), lambda v=float(v): self.chaos.set_probability(v)))
            v = env.get('MAX_KWP')
            if v:
                plan.append(('peak=%gW' % (0.75 * float(v) * 1000.0),
                             lambda v=float(v): setattr(self.simulator, 'peak_w', 0.75 * v * 1000.0)))
            v = env.get('BATTERY')
            if v:
                flag = v.strip().lower() in ('1', 'true', 'yes', 'on')
                plan.append(('battery=%s' % flag, lambda: setattr(self.simulator, 'battery', flag)))
            v = env.get('STRICT')
            if v:
                flag = v.strip().lower() in ('1', 'true', 'yes', 'on')
                plan.append(('strict=%s' % flag, lambda: setattr(self.fake, 'strict', flag)))
            v = env.get('TIME')
            if v:
                if v.strip().lower() in ('auto', 'live'):
                    plan.append(('time=live', lambda: self.simulator.freeze(None)))
                else:
                    plan.append(('time=%s' % v.strip(), lambda v=v: self.simulator.freeze(parse_time(v))))
            v = env.get('TIME_SCALE')
            if v:
                x = float(v)
                if not 0 < x <= 1440:
                    raise ValueError('TIME_SCALE must be 0 < N <= 1440, got %r' % v)
                plan.append(('time-scale=x%g' % x, lambda x=x: self.simulator.set_time_scale(x)))
            v = env.get('PROFILE')
            if v:
                path = v.strip()
                new_map = load_profile(path)   # eager: a bad profile keeps everything
                plan.append(('profile=%s: %s' % (profile_label(new_map.path), new_map.description),
                             lambda m=new_map: self.simulator.set_profile(m)))
            v = env.get('LOG_LEVEL')
            if v:
                level = getattr(logging, v.strip().upper())
                plan.append(('log_level=%s' % v.strip().upper(),
                             lambda: (logging.getLogger('fake-inverter').setLevel(level),
                                      logging.getLogger('fake-inverter-control').setLevel(level))))
        except (ValueError, AttributeError, SystemExit) as e:
            logger.warning('SIGHUP: reload failed (%s), keeping previous settings', e)
            if self.audit:
                self.audit.event('RELOAD', 'failed: %s' % e)
            return
        if not plan:
            logger.info('SIGHUP: reloaded, no environment settings to apply')
            if self.audit:
                self.audit.event('RELOAD', 'no environment settings to apply')
            return
        for _, fn in plan:
            fn()
        logger.info('SIGHUP: reloaded %d setting(s): %s', len(plan), ', '.join(label for label, _ in plan))
        if self.audit:
            self.audit.event('RELOAD', '%d setting(s): %s' % (len(plan), ', '.join(label for label, _ in plan)))

    # ---- SIGUSR1: reset the scenario (release pins + drop the write overlay)

    def reset(self):
        pins = self.simulator.reset_overrides()
        overlay = len(self.fake.overlay)
        bits = len(self.fake.coils) + len(self.fake.discrete)
        self.fake.overlay.clear()
        self.fake.coils.clear()
        self.fake.discrete.clear()
        logger.info('SIGUSR1: scenario reset (%d pin(s), %d coil/discrete pin(s), %d overlay register(s) cleared), simulation continues',
                    pins, bits, overlay)
        if self.audit:
            self.audit.event('RESET', 'SIGUSR1: %d pin(s), %d coil/discrete pin(s), %d overlay register(s) cleared'
                             % (pins, bits, overlay))

    # ---- SIGTERM / SIGINT

    def shutdown(self, name):
        self.stop = True
        dur = time.monotonic() - self.started
        logger.info('shutdown: %s received after %.0fs (%d client connection(s), %d request(s), %d chaos hit(s))',
                    name, dur, self.fake.conns, self.fake.requests, self.chaos.hits)
        if self.audit:
            self.audit.event('SHUTDOWN', '%s: uptime=%.0fs conns=%d requests=%d chaos_hits=%d'
                             % (name, dur, self.fake.conns, self.fake.requests, self.chaos.hits))
        if self.control:
            self.control.shutdown_dump()   # the write-behind: the overrides ride the next start
            self.control.announce_exit(name)   # the consoles print the notice and exit
            self.control.cleanup()   # unlink the socket file before anything can exit first
        self.fake.stopping = True
        fake_serve = getattr(self.fake, 'srv', None)
        if fake_serve:
            try:
                fake_serve.close()
            except OSError:
                pass
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except OSError:
                pass
        os._exit(0)
