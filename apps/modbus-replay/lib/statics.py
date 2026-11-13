#!/usr/bin/env python3
"""modbus-replay's static configuration: the trace format's identity, the
replay miss codes and the shipped CLI defaults, kept in one JSON
(lib/defaults.json) instead of being scattered over the modules. Loaded
once at import; everything reads the STATIC dict (or the named aliases
below). Stdlib only."""
from common.settings.options import load_static_json, static_defaults

STATIC = load_static_json(__file__)

from common.modbus.protocol import PROTOCOL    # the family's one protocol tree
MAX_PDU = PROTOCOL['max_pdu']                  # the largest accepted Modbus frame

from common.modbus.trace import (TRACE_FORMAT, TRACE_MAGIC,      # the trace identity rides
                                 TRACE_BINARY_VERSION, TRACE_VERSION)   # the family's one tree
                                                                 # (lib/trace.py re-exports them too)

EXC_GATEWAY = STATIC['replay_miss_code']       # 11 — gateway target device failed
                                               # to respond (the replay miss default)
EXC_VALUE = STATIC['replay_value_code']        # 3 — illegal data value (a synthesized
                                               # read whose count is past the caps)
EXC_ILLEGAL = STATIC['replay_illegal_code']    # 1 — illegal function (the zero-mode
                                               # fallback for a function the
                                               # synthesizer cannot shape)

from .options import OPTIONS   # the registry rows — the defaults' one home (the rows' `default`)
DEFAULTS = static_defaults(OPTIONS)
DEFAULT_LISTEN_PORT = int(DEFAULTS['listen'].rsplit(':', 1)[1])
