#!/usr/bin/env python3
"""The cache's static configuration: the Modbus protocol limits, the
synthesized diagnostics block, the register-type word map and the shipped
defaults — kept in one JSON file (lib/static.json) instead of being
scattered over the modules. Loaded once at import; everything reads the
STATIC dict (or the named aliases below). Stdlib only."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'static.json'), encoding='utf-8') as _f:
    STATIC = json.load(_f)

PROTOCOL = STATIC['protocol']
MAX_PDU = PROTOCOL['max_pdu']                  # the largest Modbus PDU
MAX_COUNT = PROTOCOL['max_count']              # max registers per FC3/FC4 read
MAX_REGISTERS = PROTOCOL['max_registers']      # the 16-bit register space
READ_FUNCS = tuple(PROTOCOL['read_funcs'])     # cacheable reads: FC3 (holding), FC4 (input)
WRITE_FUNCS = frozenset(PROTOCOL['write_funcs'])
ILLEGAL_FUNCTION = PROTOCOL['exceptions']['illegal_function']
ILLEGAL_ADDRESS = PROTOCOL['exceptions']['illegal_address']
ILLEGAL_VALUE = PROTOCOL['exceptions']['illegal_value']
GATEWAY_FAILED = PROTOCOL['exceptions']['gateway_failed']
LOG_LEVELS = tuple(STATIC['log_levels'])

REGISTER_TYPES = STATIC['register_types']      # type name -> words per register
UNIT_ID_RANGE = tuple(STATIC['unit_id_range'])

DIAGNOSTICS = STATIC['diagnostics']
DIAG_BASE = DIAGNOSTICS['base']                # the synthesized block
DIAG_COUNT = DIAGNOSTICS['count']
DIAG_MAGIC = DIAGNOSTICS['magic']
DIAG_MAX = DIAGNOSTICS['max_age']              # the age/uptime clamp (0xFFFF)

DEFAULTS = STATIC['defaults']
DEFAULT_LISTEN_PORT = int(DEFAULTS['listen'].rsplit(':', 1)[1])
REQUESTS_AUDIT_S = DEFAULTS['requests_audit_s']  # the per-client REQUESTS audit period
CLI_KEEPALIVE_S = DEFAULTS['cli_keepalive_s']
CLI_TIMEOUT_S = DEFAULTS['cli_timeout_s']
CLI_RECONNECT = DEFAULTS['cli_reconnect']
CLI_RECONNECT_WAIT_S = DEFAULTS['cli_reconnect_wait_s']
CONTROL_IDLE_TIMEOUT_S = DEFAULTS['control_idle_timeout_s']
CONTROL_LINE_CAP = int(STATIC['control']['line_cap_bytes'])
