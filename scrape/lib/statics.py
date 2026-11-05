#!/usr/bin/env python3
"""The scraper's static configuration: the Modbus protocol limits, the
cache diagnostics block it reads, the log levels and the shipped defaults —
kept in one JSON file (lib/static.json) instead of being scattered over the
modules. Loaded once at import; everything reads the STATIC dict (or the
named aliases below). Stdlib only."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'static.json'), encoding='utf-8') as _f:
    STATIC = json.load(_f)

PROTOCOL = STATIC['protocol']
MAX_PDU = PROTOCOL['max_pdu']                  # the largest Modbus PDU
MAX_COUNT = PROTOCOL['max_count']              # max registers per FC3/FC4 read
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
