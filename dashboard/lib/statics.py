#!/usr/bin/env python3
"""The dashboard's static configuration: the shipped defaults for the static
file server with the Prometheus proxy — the listen address,
the upstream Prometheus URL, the proxy path prefix and timeout and the log
level — kept in one JSON file (lib/defaults.json)
instead of being scattered over the modules. Loaded once at import;
everything reads the STATIC dict (or the named aliases below). Stdlib only."""
from common.settings.options import load_static_json, static_defaults

STATIC = load_static_json(__file__)

LOG_LEVELS = tuple(STATIC['log_levels'])

from .options import OPTIONS   # the registry rows — the defaults' one home (the rows' `default`)
DEFAULTS = static_defaults(OPTIONS)
DEFAULT_LISTEN = DEFAULTS['listen']
DEFAULT_LISTEN_PORT = int(DEFAULT_LISTEN.rsplit(':', 1)[1])

# the control socket's name: the daemon's template (common.config's parsers
# take it as the argument), the clients' default (the template spelled with
# the default page port)
CONTROL_SOCKET_TEMPLATE = '/tmp/dashboard-%d.socket'
DEFAULT_CONTROL_SOCKET = CONTROL_SOCKET_TEMPLATE % DEFAULT_LISTEN_PORT
PROXY_TIMEOUT_S = STATIC['proxy_timeout_s']   # a plain static — the proxy has no knob row
AUDIT_MAX_MB = DEFAULTS['audit_max_mb']
AUDIT_FILES = DEFAULTS['audit_files']
from common.wire.control import CLI_IDLE_TIMEOUT_S, CLI_KEEPALIVE_S, CLI_MAX_LINE_BYTES_S, \
    CLI_MIN_HEIGHT, CLI_MIN_WIDTH, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S   # the clients' wire constants (the shared tree)

# the live `set metrics enable on` defaults (the flags configure the start-up one)
DEFAULT_METRICS_CAPS = (int(DEFAULTS['metrics_max_clients']),
                        float(DEFAULTS['metrics_client_timeout']),
                        int(DEFAULTS['metrics_max_conn_per_ip']))
