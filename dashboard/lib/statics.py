#!/usr/bin/env python3
"""The dashboard's static configuration: the shipped defaults for the static
file server with the Prometheus proxy — the listen address,
the upstream Prometheus URL, the proxy path prefix and timeout, the log
level and the battery flag — kept in one JSON file (lib/defaults.json)
instead of being scattered over the modules. Loaded once at import;
everything reads the STATIC dict (or the named aliases below). Stdlib only."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'defaults.json'), encoding='utf-8') as _f:
    STATIC = json.load(_f)

LOG_LEVELS = tuple(STATIC['log_levels'])

from .options import OPTIONS   # the registry rows — the defaults' one home (the rows' `default`)
DEFAULTS = {o.name.replace('-', '_'): o.static_default
            for o in OPTIONS if o.static_default is not None}
DEFAULT_LISTEN = DEFAULTS['listen']
DEFAULT_LISTEN_PORT = int(DEFAULT_LISTEN.rsplit(':', 1)[1])

# the control socket's name: the daemon's template (common.config's parsers
# take it as the argument), the clients' default (the template spelled with
# the default page port)
CONTROL_SOCKET_TEMPLATE = '/tmp/dashboard-%d.socket'
DEFAULT_CONTROL_SOCKET = CONTROL_SOCKET_TEMPLATE % DEFAULT_LISTEN_PORT
DEFAULT_UPSTREAM = DEFAULTS['upstream']
DEFAULT_PROM_PREFIX = DEFAULTS['prom_prefix']
PROXY_TIMEOUT_S = STATIC['proxy_timeout_s']   # a plain static — the proxy has no knob row
DEFAULT_LOG_LEVEL = DEFAULTS['log_level']
AUDIT_MAX_MB = DEFAULTS['audit_max_mb']
AUDIT_FILES = DEFAULTS['audit_files']
from common.wire.control import CONTROL_WIRE_DEFAULTS  # the shared wire tree (flat: the cli_* keys)
CLI_KEEPALIVE_S = CONTROL_WIRE_DEFAULTS['cli_keepalive_s']
CLI_TIMEOUT_S = CONTROL_WIRE_DEFAULTS['cli_timeout_s']
CLI_RECONNECT = CONTROL_WIRE_DEFAULTS['cli_reconnect']
CLI_RECONNECT_WAIT_S = CONTROL_WIRE_DEFAULTS['cli_reconnect_wait_s']
CLI_IDLE_TIMEOUT_S = CONTROL_WIRE_DEFAULTS['cli_idle_timeout_s']
CLI_MAX_LINE_BYTES_S = CONTROL_WIRE_DEFAULTS['cli_max_line_bytes_s']

# the live `set metrics enable on` defaults (the flags configure the start-up one)
DEFAULT_METRICS_CAPS = (int(DEFAULTS.get('metrics_max_clients', 16)),
                        float(DEFAULTS.get('metrics_client_timeout_s', 5.0)),
                        int(DEFAULTS.get('metrics_max_conn_per_ip', 0)))
