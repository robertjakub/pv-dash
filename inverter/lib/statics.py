#!/usr/bin/env python3
"""The fake's static configuration: the numbers a demo device is born with,
kept in one JSON file (lib/defaults.json) instead of being scattered over the
modules — the Modbus protocol limits, the diagnostics block, the solar
times (the day window, the east/west strings), the PV peak ratio, the cloud
state machines, the home-load day curve, the grid nominals and their
wander, the lifetime meter totals, the grid-outage machine, the battery
limits and every shipped CLI default. Loaded once at import; everything
reads the STATIC dict (or the named aliases below). Stdlib only."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'defaults.json'), encoding='utf-8') as _f:
    STATIC = json.load(_f)

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

DEFAULTS = STATIC['defaults']
DEFAULT_LISTEN_PORT = int(DEFAULTS['listen'].rsplit(':', 1)[1])
DEFAULT_UNIT = DEFAULTS['unit']
DEFAULT_MAX_KWP = DEFAULTS['max_kwp']
DEFAULT_BATTERY_KWH = DEFAULTS['battery_kwh']
DEFAULT_TIME_SCALE = DEFAULTS['time_scale']
TIME_SCALE_MAX = DEFAULTS['time_scale_max']    # a day per minute

# the control socket's name: the daemon's template (common.config's parsers
# take it as the argument), the clients' default (the template spelled with
# the default listen port)
CONTROL_SOCKET_TEMPLATE = '/tmp/fake-inverter-%d.socket'
DEFAULT_CONTROL_SOCKET = CONTROL_SOCKET_TEMPLATE % DEFAULT_LISTEN_PORT
DEFAULT_CHAOS = DEFAULTS['chaos']
DEFAULT_MAX_CLIENTS = DEFAULTS['max_clients']
DEFAULT_CLIENT_TIMEOUT_S = DEFAULTS['client_timeout_s']
DEFAULT_MAX_CONN_PER_IP = DEFAULTS['max_conn_per_ip']
DEFAULT_METRICS_LISTEN = DEFAULTS['metrics_listen']
DEFAULT_METRICS_MAX_CLIENTS = DEFAULTS['metrics_max_clients']
DEFAULT_METRICS_CLIENT_TIMEOUT_S = DEFAULTS['metrics_client_timeout_s']
DEFAULT_METRICS_MAX_CONN_PER_IP = DEFAULTS['metrics_max_conn_per_ip']
LOG_LEVELS = tuple(STATIC['log_levels'])
DEFAULT_LOG_LEVEL = DEFAULTS['log_level']
SCENARIOS = {k: float(v) for k, v in STATIC['scenarios'].items()}
AUDIT_MAX_MB = DEFAULTS['audit_max_mb']
AUDIT_FILES = DEFAULTS['audit_files']
from common.wire.control import CONTROL_WIRE_DEFAULTS  # the shared wire tree (flat: the cli_* keys)
CLI_KEEPALIVE_S = CONTROL_WIRE_DEFAULTS['cli_keepalive_s']
CLI_TIMEOUT_S = CONTROL_WIRE_DEFAULTS['cli_timeout_s']
CLI_RECONNECT = CONTROL_WIRE_DEFAULTS['cli_reconnect']
CLI_RECONNECT_WAIT_S = CONTROL_WIRE_DEFAULTS['cli_reconnect_wait_s']
CLI_IDLE_TIMEOUT_S = CONTROL_WIRE_DEFAULTS['cli_idle_timeout_s']
CLI_MAX_LINE_BYTES_S = CONTROL_WIRE_DEFAULTS['cli_max_line_bytes_s']

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

GRID = STATIC['grid']
GRID_VOLTAGE_V = GRID['voltage_v']             # nominal phase voltage
GRID_VOLTAGE_WANDER = GRID['voltage_wander']   # the per-phase machine's range (fraction)
GRID_FREQUENCY_HZ = GRID['frequency_hz']       # nominal frequency
GRID_FREQUENCY_WANDER = GRID['frequency_wander']   # the machine's clamp (Hz)

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
