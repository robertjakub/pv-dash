#!/usr/bin/env python3
"""The cache's static configuration: the Modbus protocol limits, the
synthesized diagnostics block, the register-type word map and the shipped
defaults — kept in one JSON file (lib/defaults.json) instead of being
scattered over the modules. Loaded once at import; everything reads the
STATIC dict (or the named aliases below). Stdlib only."""
from common.settings.options import load_static_json, static_defaults

STATIC = load_static_json(__file__)

from common.modbus.protocol import PROTOCOL    # the family's one protocol tree:
                                               # the limits, the unit range, the FC
                                               # policy and the exception codes
MAX_PDU = PROTOCOL['max_pdu']                  # the largest Modbus PDU
MAX_COUNT = PROTOCOL['max_count']              # max registers per FC3/FC4 read
MAX_BITS = PROTOCOL['max_bits']                # max bits per FC1/FC2 read (the Modbus spec's 0x7D0)
MAX_REGISTERS = PROTOCOL['max_registers']      # the 16-bit register space
READ_FUNCS = tuple(PROTOCOL['read_funcs'])     # cacheable reads: FC1 (coils), FC2 (discrete),
                                               # FC3 (holding), FC4 (input) — one space each
BIT_READ_FUNCS = (1, 2)                        # the bit-shaped reads (packed 8 per byte, LSB first)
WRITE_FUNCS = frozenset(PROTOCOL['write_funcs'])
ILLEGAL_FUNCTION = PROTOCOL['exceptions']['illegal_function']
ILLEGAL_ADDRESS = PROTOCOL['exceptions']['illegal_address']
ILLEGAL_VALUE = PROTOCOL['exceptions']['illegal_value']
GATEWAY_FAILED = PROTOCOL['exceptions']['gateway_failed']
LOG_LEVELS = tuple(STATIC['log_levels'])

REGISTERS_TYPE = PROTOCOL['registers_type']   # type name -> words per register (the shared tree)
UNIT_ID_RANGE = tuple(PROTOCOL['unit_id_range'])

DIAGNOSTICS = STATIC['diagnostics']
DIAG_BASE = DIAGNOSTICS['base']                # the synthesized block
DIAG_COUNT = DIAGNOSTICS['count']
DIAG_MAGIC = DIAGNOSTICS['magic']
DIAG_MAX = DIAGNOSTICS['max_age']              # the age/uptime clamp (0xFFFF)

from .options import OPTIONS   # the registry rows — the defaults' one home (the rows' `default`)
DEFAULTS = static_defaults(OPTIONS)
DEFAULT_LISTEN_PORT = int(DEFAULTS['listen'].rsplit(':', 1)[1])
AUDIT_MAX_MB = DEFAULTS['audit_max_mb']
AUDIT_FILES = DEFAULTS['audit_files']
REQUESTS_AUDIT_S = DEFAULTS['audit_requests']  # the per-client REQUESTS audit period
from common.wire.control import CLI_IDLE_TIMEOUT_S, CLI_KEEPALIVE_S, CLI_MAX_LINE_BYTES_S, \
    CLI_MIN_HEIGHT, CLI_MIN_WIDTH, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S   # the clients' wire constants (the shared tree)
