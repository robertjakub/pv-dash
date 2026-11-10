#!/usr/bin/env python3
"""The scraper's static configuration: the Modbus protocol limits, the
cache diagnostics block it reads, the log levels and the shipped defaults —
kept in one JSON file (lib/defaults.json) instead of being scattered over the
modules. Loaded once at import; everything reads the STATIC dict (or the
named aliases below). Stdlib only."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'defaults.json'), encoding='utf-8') as _f:
    STATIC = json.load(_f)

from common.modbus.protocol import PROTOCOL    # the family's one protocol tree
MAX_PDU = PROTOCOL['max_pdu']                  # the largest Modbus PDU
MAX_COUNT = PROTOCOL['max_count']              # max registers per FC3/FC4 read
MAX_BITS = PROTOCOL['max_bits']                # max bits per FC1/FC2 read (the Modbus spec's 0x7D0)
MAX_REGISTERS = PROTOCOL['max_registers']      # the 16-bit register space
UNIT_ID_RANGE = tuple(PROTOCOL['unit_id_range'])

DIAGNOSTICS = STATIC['diagnostics']
DIAG_BASE = DIAGNOSTICS['base']                # the cache's synthesized block
DIAG_COUNT = DIAGNOSTICS['count']
DIAG_MAGIC = DIAGNOSTICS['magic']
DIAG_MAX = DIAGNOSTICS['max_age']              # the age/uptime clamp (0xFFFF)

LOG_LEVELS = tuple(STATIC['log_levels'])

DEFAULTS = STATIC['defaults']
DEFAULT_LISTEN_PORT = int(DEFAULTS['listen'].rsplit(':', 1)[1])
AUDIT_MAX_MB = DEFAULTS['audit_max_mb']
AUDIT_FILES = DEFAULTS['audit_files']
CONTROL_PLANE = STATIC['control-plane']
CLI_KEEPALIVE_S = CONTROL_PLANE['cli_keepalive_s']
CLI_TIMEOUT_S = CONTROL_PLANE['cli_timeout_s']
CLI_RECONNECT = CONTROL_PLANE['cli_reconnect']
CLI_RECONNECT_WAIT_S = CONTROL_PLANE['cli_reconnect_wait_s']
CONTROL_IDLE_TIMEOUT_S = DEFAULTS['control_idle_timeout_s']
CONTROL_LINE_CAP = int(STATIC['control']['line_cap_bytes'])
