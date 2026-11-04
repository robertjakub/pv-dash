#!/usr/bin/env python3
"""The fake's static configuration: the numbers a demo device is born with,
kept in one JSON file (lib/static.json) instead of being scattered over the
modules — the solar times (the day window, the east/west strings), the cloud
state machines, the lifetime meter totals, the battery limits and the
default Modbus port. Loaded once at import; everything reads the STATIC
dict (or the named aliases below). Stdlib only."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'static.json'), encoding='utf-8') as _f:
    STATIC = json.load(_f)

DEFAULT_MODBUS_PORT = STATIC['default_modbus_port']
SUNRISE = STATIC['sun']['sunrise']              # the simulated day's window
SUNSET = STATIC['sun']['sunset']                # (the battery day plan)
MPPT_WINDOWS = {k: (v['sunrise'], v['sunset']) for k, v in STATIC['mppt'].items()}
# cloud_machines: mode -> (mean, theta/h, sigma/sqrt(h), lo, hi) — the
# Ornstein-Uhlenbeck parameters (a mean-reverting random walk over the
# simulated clock: time-lapse jumps move the clouds, a frozen clock
# freezes them)
CLOUD_MACHINES = {k: tuple(v) for k, v in STATIC['cloud_machines'].items()}
METER_EXPORT_KWH = STATIC['meter_export_kwh']
METER_IMPORT_KWH = STATIC['meter_import_kwh']

# the grid-outage machine: a connected->outage hazard per simulated hour and
# an outage->connected hazard per simulated minute (a two-state Markov chain
# over the simulated clock — the time-lapse factor speeds it up like
# everything else)
GRID_OUTAGE_FAIL_H = STATIC['grid_outage']['fail_per_h']
GRID_OUTAGE_REPAIR_MIN = STATIC['grid_outage']['repair_per_min']

# the battery limits (battery.py's constants)
BATT_MAX_W = STATIC['batt_max_w']
BATT_RESERVE_SOC = STATIC['batt_reserve_soc']
BATT_GRID_MARGIN_W = STATIC['batt_grid_margin_w']
BATT_STANDBY_W = STATIC['batt_standby_w']
BATT_MAX_TICK_H = STATIC['batt_max_tick_h']
BATT_CHARGE_EFF = STATIC['batt_charge_eff']
BATT_SELF_DISCH_H = STATIC['batt_self_disch_h']
BATT_DISCHARGE_CAP = STATIC['batt_discharge_cap']
