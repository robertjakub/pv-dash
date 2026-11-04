#!/usr/bin/env python3
"""Fake Inverter Simulator: a Modbus TCP server with demo values. Through
inverter profiles it can emulate different inverter/battery/meter devices —
the shipped default profile is the Huawei SUN2000 map, a Deye hybrid map is
included as well.

Simulates a sunny day (bell-curve PV between 06:00 and 18:00, home load
with morning and evening peaks) and serves the profile's registers over
FC3 (holding) and FC4 (input — the same map on both), the diagnostics
block (65000+) included: 32064 PV
input power and 37113 grid active power (positive = feed-in, as reported by
the simulated smart meter), plus the smart meter block (37100+ status/
voltages/currents/energies), device status (32089), inverter output
(32080), PV strings (32016-32019, voltage x10 V / current x100 A), phase
voltages (32069+), grid frequency (32085), temperature (32087) and PV
yields (32106/32114), plus the modbus-cache diagnostics block (65000+).
Raw register values are watts and kWh*100, matching the default profile's gain
convention.

Optional extras for demos and testing: a JSON-lines control server
(--control-port, default unix socket /tmp/fake-inverter-<port>.socket; 0 = off) to pin
values / freeze time / tune chaos at runtime, and
seeded chaos injection (--chaos) that answers requests hostile. Signals
mirror the family: SIGHUP re-applies the FAKE_* environment layer
(FAKE_CHAOS/FAKE_MAX_KWP/FAKE_BATTERY/FAKE_STRICT/FAKE_TIME/FAKE_TIME_SCALE/
FAKE_LOG_LEVEL, keep-last-good), SIGUSR1 resets the scenario (releases pins
+ write overlay), SIGTERM/SIGINT shut down with a session summary.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the src/ — the lib/ lives next to bin/

import argparse
import logging
import math
import os
import threading

from lib.chaos import Chaos
from lib.audit import AuditLog
from lib.paths import load_token_file, resolve_control_target
from lib.control import ControlServer
from lib.inverter import FakeInverter
from lib.profile import load_profile, profile_label, resolve_profile
from lib.statics import (AUDIT_FILES, AUDIT_MAX_MB, DEFAULT_BATTERY_KWH, DEFAULT_CHAOS, DEFAULT_HOST,
                         DEFAULT_LOG_LEVEL, DEFAULT_MAX_KWP, DEFAULT_MODBUS_PORT, DEFAULT_TIME_SCALE,
                         DEFAULT_UNIT, GRID_FREQUENCY_HZ, GRID_VOLTAGE_V, PEAK_RATIO, TIME_SCALE_MAX)
from lib.version import version_string
from lib.signals import SignalBox, parse_time
from lib.metrics import MetricsServer
from lib.simulator import Simulator

logger = logging.getLogger('fake-inverter')


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
    if not (math.isfinite(args.time_scale) and 0 < args.time_scale <= TIME_SCALE_MAX):
        problems.append('--time-scale must be 0 < N <= %g (a day per minute), got %r' % (TIME_SCALE_MAX, args.time_scale))
    if not 0.0 <= args.chaos <= 1.0:
        problems.append('--chaos must be a probability 0..1, got %r' % args.chaos)
    return problems


def configured_defaults(args, frozen, profile_text):
    """Every setting's configured startup value — what `unset <setting>` restores."""
    return {
        'pv': 'auto', 'load': 'auto', 'batt': 'auto', 'grid': 'auto', 'soc': 'auto', 'cloud': 'clear',
        'time': '%02d:%02d' % (int(frozen), round((frozen % 1.0) * 60)) if frozen is not None else 'auto',
        'time-scale': '%g' % args.time_scale,
        'scenario': 'custom',
        'chaos': '%.2f' % args.chaos,
        'seed': 'random' if args.seed is None else str(args.seed),
        'battery': 'on' if args.battery else 'off',
        'battery-state': 'auto',
        'mppt': 'both',
        'grid-voltage': '%g' % args.grid_voltage,
        'grid-frequency': '%g' % args.grid_frequency,
        'grid-outage': 'off',
        'timezone': args.timezone,
        'strict': 'on' if args.strict else 'off',
        'static': 'on' if args.static else 'off',
        'max-kwp': '%g' % args.max_kwp,
        'battery-kwh': '%g' % args.battery_kwh,
        'profile': profile_text,
        'log-level': args.log_level,
    }


def main():
    import sys
    if '--version' in sys.argv:
        print(version_string())
        raise SystemExit(0)
    p = argparse.ArgumentParser(description='Fake Inverter Simulator: a Modbus TCP server with demo values. Simulates different inverter/battery/meter devices through inverter profiles — the shipped default is the Huawei SUN2000 map, a Deye hybrid map is included as well.')
    p.add_argument('--host', default=DEFAULT_HOST, help='bind address (default %(default)s)')
    p.add_argument('--port', type=int, default=DEFAULT_MODBUS_PORT, help='Modbus TCP port (default %(default)s)')
    p.add_argument('--unit', type=int, default=DEFAULT_UNIT, help='Modbus unit id served (default %(default)s)')
    p.add_argument('--timezone', default='utc', choices=['utc', 'local'], help='clock the state machines integrate over (the PV bell, the home load, the clouds, the battery, the grid voltage): UTC (the default) or the local wall clock')
    p.add_argument('--grid-voltage', type=float, default=GRID_VOLTAGE_V, help='nominal grid phase voltage in V (120 or 230; the per-phase machine wanders ±10 %% around it, default %(default)s)')
    p.add_argument('--grid-frequency', type=float, default=GRID_FREQUENCY_HZ, help='nominal grid frequency in Hz (the machine wanders ±0.2 Hz around it, default %(default)s)')
    p.add_argument('--max-kwp', type=float, default=DEFAULT_MAX_KWP, help='PV array size in kWp, peak = 75%% of it (default %(default)s)')
    p.add_argument('--time', help='freeze simulated time HH:MM (default: real clock)')
    p.add_argument('--time-scale', type=float, default=DEFAULT_TIME_SCALE, help='the simulated clock speed: N× real time — every machine (the battery, the clouds, the voltages, the day counters) integrates over it, so a full simulated day takes 24/N real hours (default: 1 = real time)')
    p.add_argument('--static', action='store_true', help='constant demo values instead of the day simulation')
    p.add_argument('--battery', action='store_true', default=True, help='simulate a battery (the default)')
    p.add_argument('--no-battery', dest='battery', action='store_false', help='no battery values')
    p.add_argument('--strict', action='store_true', help='reject reads of undefined registers with exception 02 (like the real device)')
    p.add_argument('--battery-kwh', type=float, default=DEFAULT_BATTERY_KWH, help='usable battery capacity in kWh (default %(default)s)')
    p.add_argument('--control-log-replies', action='store_true', help='DEBUG-log the full output of every control command (the default logs the command only)')
    p.add_argument('--metrics-port', type=int, default=0, help='serve the fake\'s own Prometheus /metrics on 127.0.0.1:PORT; 0 = off (the default)')
    p.add_argument('--metrics-token', default=None, help='require Authorization: Bearer <token> on the /metrics endpoint (the same scheme the scraper speaks)')
    p.add_argument('--metrics-token-file', default=None, help='the metrics bearer token from a file (the first line) — takes the place of --metrics-token; giving both is an error (env FAKE_METRICS_TOKEN_FILE)')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path (default: /tmp/fake-inverter-<modbus-port>.socket) or TCP port number on 127.0.0.1 (e.g. 15599); 0 = off. Talk to it with fake_ctl.py')
    p.add_argument('--profile', default=None, help='inverter profile JSON: name -> register (+ optional type/scale), e.g. profiles/sun2000.json (the default); FAKE_PROFILE when unset')
    p.add_argument('--chaos', type=float, default=DEFAULT_CHAOS, help='probability 0..1 that a request is answered hostile and dropped (default: off); seed with --seed for reproducibility')
    p.add_argument('--seed', type=int, help='chaos RNG seed (default: random)')
    p.add_argument('--dry-run', action='store_true', help='validate the configuration, print the effective settings and exit (nothing is bound or connected)')
    p.add_argument('--log-level', default=DEFAULT_LOG_LEVEL, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    p.add_argument('--audit-log', default=None, help='INV audit trail: a file path or - for stdout (the docker/journald way); default: %s — the XDG state home' % AuditLog.default_path())
    p.add_argument('--audit-max-mb', type=float, default=AUDIT_MAX_MB, help='rotate the audit log at this size in MB, keeping 3 backups; 0 = no size rotation (default %(default)s)')
    p.add_argument('--audit-daily', action='store_true', help='also rotate the audit log at UTC midnight')
    p.add_argument('--audit-files', type=int, default=AUDIT_FILES, help='rotated audit backups to keep (default %(default)s)')
    p.add_argument('--no-audit-log', action='store_true', help='disable the INV audit trail')
    p.add_argument('--control-token', default=None, help='require a token on TCP control connections: the client authenticates with {"cmd": "auth", "token": ...}; the unix socket needs no token')
    p.add_argument('--control-token-file', default=None, help='the token from a file (the first line; e.g. a systemd LoadCredential or a key file) — takes the place of --control-token; giving both is an error (env FAKE_CONTROL_TOKEN_FILE)')
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
    simulator = Simulator(PEAK_RATIO * args.max_kwp * 1000.0, args.static, frozen,
                          battery=args.battery, battery_kwh=args.battery_kwh,
                          profile=load_profile(profile_path), seed=args.seed)
    simulator.set_time_scale(args.time_scale)   # validated above; before any machine reads the clock
    chaos = Chaos(args.chaos, seed=args.seed)
    target = resolve_control_target(args.control_port, args.port)
    if args.control_token and args.control_token_file:
        logger.error('--control-token and --control-token-file are mutually exclusive')
        raise SystemExit(1)
    control_token = args.control_token
    if args.control_token_file:
        control_token = load_token_file(args.control_token_file)
    if args.metrics_token and args.metrics_token_file:
        logger.error('--metrics-token and --metrics-token-file are mutually exclusive')
        raise SystemExit(1)
    metrics_token = args.metrics_token
    if args.metrics_token_file:
        metrics_token = load_token_file(args.metrics_token_file, 'metrics-token-file')
    if args.dry_run:
        mode = 'static values' if args.static else (
            'day simulation at x%g' % args.time_scale if args.time_scale != 1.0 else 'day simulation')
        logger.info('would serve Modbus TCP on %s:%d (unit %d, peak PV %gW, %s, battery %s%s, strict %s, chaos %g, seed %s, profile %s: %s, %d register(s), control server %s)',
                    args.host, args.port, args.unit, PEAK_RATIO * args.max_kwp * 1000.0,
                    mode,
                    'on' if args.battery else 'off',
                    ' (%g kWh)' % args.battery_kwh if args.battery else '',
                    args.strict, args.chaos,
                    args.seed if args.seed is not None else 'random',
                    simulator.profile.description, profile_label(profile_path), len(simulator.profile.entries),
                    ('127.0.0.1:' + target) if target.isdigit() else ('unix:' + target) if target != '0' else 'off')
        logger.info('dry-run: configuration is valid, nothing was bound or connected')
        return
    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'INV', args.audit_max_mb,
                                                    args.audit_daily, args.audit_files)
    fake = FakeInverter(args.unit, simulator, strict=args.strict, chaos=chaos)
    control = None
    if target != '0':
        control = ControlServer(simulator, chaos, target, fake=fake,
                                defaults=configured_defaults(args, frozen, profile_text),
                                log_replies=args.control_log_replies, audit=audit,
                                token=control_token)
        threading.Thread(target=control.serve, daemon=True).start()
    if args.metrics_port:
        MetricsServer(simulator, chaos, fake, control, args.metrics_port,
                      token=metrics_token).start()
    box = SignalBox(simulator, chaos, fake, control=control, audit=audit)
    if control:
        control.signalbox = box
    box.install()
    if audit:
        audit.event('START', 'version=%s modbus=%s:%d control=%s profile=%s: %s'
                    % (version_string(), args.host, args.port,
                       ('127.0.0.1:' + target) if target != '0' else 'off',
                       profile_label(profile_path), simulator.profile.description))
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
