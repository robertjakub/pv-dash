#!/usr/bin/env python3
"""The fake's static configuration: the numbers a demo device is born with,
kept in one JSON file (lib/defaults.json) instead of being scattered over the
modules — the Modbus protocol limits, the diagnostics block, the solar
times (the day window, the east/west strings), the PV peak ratio, the cloud
state machines, the home-load day curve, the grid nominals and their
wander, the lifetime meter totals, the grid-outage machine, the battery
limits and every shipped CLI default. Loaded once at import; everything
reads the STATIC dict (or the named aliases below). Stdlib only."""
from common.settings.options import load_static_json, static_defaults

STATIC = load_static_json(__file__)

from common.modbus.protocol import PROTOCOL    # the family's one protocol tree
MAX_PDU = PROTOCOL['max_pdu']                  # the largest accepted Modbus frame
MAX_REGISTERS = PROTOCOL['max_registers']      # the 16-bit register space
MAX_COUNT = PROTOCOL['max_count']              # max registers per FC3/FC4 read (the cache's cap)
MAX_BITS = PROTOCOL['max_bits']                # max bits per FC1/FC2 read (the Modbus spec's 0x7D0)
UNIT_ID_RANGE = tuple(PROTOCOL['unit_id_range'])  # the migrated cache support: the unit check

DIAGNOSTICS = STATIC['diagnostics']
DIAG_BASE = DIAGNOSTICS['base']                # the synthesized diagnostics block
DIAG_COUNT = DIAGNOSTICS['count']
DIAG_MAGIC = DIAGNOSTICS['magic']

from .options import OPTIONS   # the registry rows — the defaults' one home (the rows' `default`)
DEFAULTS = static_defaults(OPTIONS)
DEFAULT_LISTEN_PORT = int(DEFAULTS['listen'].rsplit(':', 1)[1])
DEFAULT_BATTERY_KWH = DEFAULTS['battery_kwh']
TIME_SCALE_MAX = STATIC['time_scale_max']      # a day per minute (the knob's live-set bound stays
                                               # a plain static — no row of its own)

# the control socket's name: the daemon's template (common.config's parsers
# take it as the argument), the clients' default (the template spelled with
# the default listen port)
CONTROL_SOCKET_TEMPLATE = '/tmp/fake-inverter-%d.socket'
DEFAULT_CONTROL_SOCKET = CONTROL_SOCKET_TEMPLATE % DEFAULT_LISTEN_PORT
LOG_LEVELS = tuple(STATIC['log_levels'])
SCENARIOS = {k: float(v) for k, v in STATIC['scenarios'].items()}
AUDIT_MAX_MB = DEFAULTS['audit_max_mb']
AUDIT_FILES = DEFAULTS['audit_files']
from common.wire.control import CLI_IDLE_TIMEOUT_S, CLI_KEEPALIVE_S, CLI_MAX_LINE_BYTES_S, \
    CLI_MIN_HEIGHT, CLI_MIN_WIDTH, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S   # the clients' wire constants (the shared tree)

SUNRISE = STATIC['sun']['sunrise']             # the simulated day's window
SUNSET = STATIC['sun']['sunset']               # (the battery day plan)
MPPT_WINDOWS = {k: (v['sunrise'], v['sunset']) for k, v in STATIC['mppt'].items()}
PEAK_RATIO = STATIC['peak_ratio']              # peak PV = ratio of the array kWp

# cloud_machines: mode -> (mean, theta/h, sigma/sqrt(h), lo, hi) — the
# Ornstein-Uhlenbeck parameters (a mean-reverting random walk over the
# simulated clock: time-lapse jumps move the clouds, a frozen clock
# freezes them)
CLOUD_MACHINES = {k: tuple(v) for k, v in STATIC['cloud_machines'].items()}

# the home-load day curve: a base plus Gaussian bells (W, hour, width h)
LOAD_BASE_W = STATIC['load_curve']['base_w']
LOAD_BELLS = STATIC['load_curve']['bells']

METER_EXPORT_KWH = STATIC['meter_export_kwh']
METER_IMPORT_KWH = STATIC['meter_import_kwh']

# the grid-outage machine: a connected->outage hazard per simulated hour and
# an outage->connected hazard per simulated minute (a two-state Markov chain
# over the simulated clock — the time-lapse factor speeds it up like
# everything else)
GRID_OUTAGE_FAIL_H = STATIC['grid_outage']['fail_per_h']
GRID_OUTAGE_REPAIR_MIN = STATIC['grid_outage']['repair_per_min']

# the battery limits (battery.py's constants)
BATT_MAX_W = STATIC['battery']['max_w']
BATT_RESERVE_SOC = STATIC['battery']['reserve_soc']
BATT_GRID_MARGIN_W = STATIC['battery']['grid_margin_w']
BATT_STANDBY_W = STATIC['battery']['standby_w']
BATT_MAX_TICK_H = STATIC['battery']['max_tick_h']
BATT_CHARGE_EFF = STATIC['battery']['charge_eff']
BATT_SELF_DISCH_H = STATIC['battery']['self_disch_h']
BATT_DISCHARGE_CAP = STATIC['battery']['discharge_cap']
