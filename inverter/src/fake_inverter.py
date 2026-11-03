#!/usr/bin/env python3
"""Fake Huawei SUN2000 inverter: a Modbus TCP server with demo values.

Simulates a sunny day (bell-curve PV between 06:00 and 18:00, home load
with morning and evening peaks) and serves the registers from Huawei's
Modbus Interface Definitions the modbus-scraper reads: 32064 PV input
power and 37113 grid active power (positive = feed-in, as reported by the
simulated smart meter), plus the smart meter block (37100+ status/
voltages/currents/energies), device status (32089), inverter output
(32080), PV strings (32016-32019, voltage x10 V / current x100 A), phase
voltages (32069+), grid frequency (32085), temperature (32087) and PV
yields (32106/32114), plus the modbus-cache diagnostics block (65000+).
Raw register values are watts and kWh*100, matching the Huawei gain
convention.

Optional extras for demos and testing: a line-protocol control server
(--control-port, default unix socket /tmp/fake-inverter-<port>.socket; 0 = off) to pin
values / freeze time / tune chaos at runtime, and
seeded chaos injection (--chaos) that answers requests hostile. Signals
mirror the family: SIGHUP re-applies the FAKE_* environment layer
(FAKE_CHAOS/FAKE_MAX_KWP/FAKE_BATTERY/FAKE_STRICT/FAKE_TIME/FAKE_LOG_LEVEL,
keep-last-good), SIGUSR1 resets the scenario (releases pins + write
overlay), SIGTERM/SIGINT shut down with a session summary.
"""
import argparse
import logging
import math
import os
import threading

from lib.chaos import Chaos
from lib.paths import resolve_control_target
from lib.control import ControlServer
from lib.inverter import FakeInverter
from lib.profile import load_profile, profile_label, resolve_profile
from lib.signals import SignalBox, parse_time
from lib.simulator import Simulator

logger = logging.getLogger('fake-sun2000')


def validate(args):
    """Clean one-line failures instead of ugly bind errors (family convention)."""
    problems = []
    host = (args.host or '').strip()
    if not host or len(host) > 253 or not all(c.isalnum() or c in '._-[]:' for c in host):
        problems.append('--host is not a valid hostname/address: %r' % args.host)
    if not 1 <= args.port <= 65535:
        problems.append('--port out of range: %d' % args.port)
    ctl = resolve_control_target(args.control_port, args.port)
    if ctl != '0':
        if ctl.isdigit():
            if not 1 <= int(ctl) <= 65535:
                problems.append('--control-port out of range: %d' % int(ctl))
        elif len(ctl) > 100:
            problems.append('--control-port socket path too long (max ~100 chars): %r' % ctl)
    if not 1 <= args.unit <= 247:
        problems.append('--unit out of range (1-247): %d' % args.unit)
    if not (math.isfinite(args.max_kwp) and args.max_kwp > 0):
        problems.append('--max-kwp must be a positive kW value, got %r' % args.max_kwp)
    if not (math.isfinite(args.battery_kwh) and args.battery_kwh > 0):
        problems.append('--battery-kwh must be a positive kWh value, got %r' % args.battery_kwh)
    if not 0.0 <= args.chaos <= 1.0:
        problems.append('--chaos must be a probability 0..1, got %r' % args.chaos)
    return problems


def configured_defaults(args, frozen, profile_text):
    """Every setting's configured startup value — what `unset <setting>` restores."""
    return {
        'pv': 'auto', 'load': 'auto', 'batt': 'auto', 'soc': 'auto', 'cloud': 'auto',
        'time': '%02d:%02d' % (int(frozen), round((frozen % 1.0) * 60)) if frozen is not None else 'auto',
        'scenario': 'custom',
        'chaos': '%.2f' % args.chaos,
        'seed': 'random' if args.seed is None else str(args.seed),
        'battery': 'on' if args.battery else 'off',
        'strict': 'on' if args.strict else 'off',
        'static': 'on' if args.static else 'off',
        'max-kwp': '%g' % args.max_kwp,
        'battery-kwh': '%g' % args.battery_kwh,
        'profile': profile_text,
        'log-level': args.log_level,
    }


def main():
    p = argparse.ArgumentParser(description='Fake Huawei SUN2000 inverter + smart meter (Modbus TCP server with demo values).')
    p.add_argument('--host', default='127.0.0.1', help='bind address (default %(default)s)')
    p.add_argument('--port', type=int, default=5502, help='Modbus TCP port (default %(default)s)')
    p.add_argument('--unit', type=int, default=1, help='Modbus unit id served (default %(default)s)')
    p.add_argument('--max-kwp', type=float, default=6.0, help='PV array size in kWp, peak = 75%% of it (default %(default)s)')
    p.add_argument('--time', help='freeze simulated time HH:MM (default: real clock)')
    p.add_argument('--static', action='store_true', help='constant demo values instead of the day simulation')
    p.add_argument('--battery', action='store_true', help='simulate a LUNA2000 battery')
    p.add_argument('--strict', action='store_true', help='reject reads of undefined registers with exception 02 (like the real device)')
    p.add_argument('--battery-kwh', type=float, default=6.9, help='usable battery capacity in kWh (default %(default)s)')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path (default: /tmp/fake-inverter-<modbus-port>.socket) or TCP port number on 127.0.0.1 (e.g. 15599); 0 = off. Talk to it with fake_ctl.py')
    p.add_argument('--profile', default=None, help='register-map profile JSON: name -> register (+ optional type/scale), e.g. profiles/sun2000.json (default); FAKE_PROFILE when unset')
    p.add_argument('--chaos', type=float, default=0.0, help='probability 0..1 that a request is answered hostile and dropped (default: off); seed with --seed for reproducibility')
    p.add_argument('--seed', type=int, help='chaos RNG seed (default: random)')
    p.add_argument('--dry-run', action='store_true', help='validate the configuration, print the effective settings and exit (nothing is bound or connected)')
    p.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    args = p.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format='%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM')
                        else '%(asctime)s %(levelname)-7s %(message)s')
    problems = validate(args)
    try:
        frozen = parse_time(args.time) if args.time else None
    except ValueError:
        logger.error('--time must be HH:MM (00:00-23:59), got %r', args.time)
        frozen = None
        problems.append('--time invalid')
    if problems:
        for problem in problems:
            logger.error(problem)
        raise SystemExit(1)
    profile_text = args.profile or os.environ.get('FAKE_PROFILE') or 'sun2000'
    profile_path = resolve_profile(profile_text)
    simulator = Simulator(0.75 * args.max_kwp * 1000.0, args.static, frozen,
                          battery=args.battery, battery_kwh=args.battery_kwh,
                          profile=load_profile(profile_path), seed=args.seed)
    chaos = Chaos(args.chaos, seed=args.seed)
    target = resolve_control_target(args.control_port, args.port)
    if args.dry_run:
        logger.info('would serve Modbus TCP on %s:%d (unit %d, peak PV %gW, %s, battery %s%s, strict %s, chaos %g, seed %s, profile %s: %s, %d register(s), control server %s)',
                    args.host, args.port, args.unit, 0.75 * args.max_kwp * 1000.0,
                    'static values' if args.static else 'day simulation',
                    'on' if args.battery else 'off',
                    ' (%g kWh)' % args.battery_kwh if args.battery else '',
                    args.strict, args.chaos,
                    args.seed if args.seed is not None else 'random',
                    simulator.profile.description, profile_label(profile_path), len(simulator.profile.entries),
                    ('127.0.0.1:' + target) if target.isdigit() else ('unix:' + target) if target != '0' else 'off')
        logger.info('dry-run: configuration is valid, nothing was bound or connected')
        return
    fake = FakeInverter(args.unit, simulator, strict=args.strict, chaos=chaos)
    control = None
    if target != '0':
        control = ControlServer(simulator, chaos, target, fake=fake,
                                defaults=configured_defaults(args, frozen, profile_text))
        threading.Thread(target=control.serve, daemon=True).start()
    box = SignalBox(simulator, chaos, fake, control=control)
    if control:
        control.signalbox = box
    box.install()
    try:
        fake.serve(args.host, args.port)
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        if box.stop:
            return   # the signal box closed the listener; it logs the shutdown
        logger.error('cannot serve on %s:%d: %s', args.host, args.port, e)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
