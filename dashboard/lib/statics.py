#!/usr/bin/env python3
"""The dashboard's static configuration: the shipped defaults for the static
file server with the Prometheus proxy — the listen port, the bind address,
the upstream Prometheus URL, the proxy path prefix and timeout, the log
level and the battery flag — kept in one JSON file (lib/static.json)
instead of being scattered over the modules. Loaded once at import;
everything reads the STATIC dict (or the named aliases below). Stdlib only."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, 'static.json'), encoding='utf-8') as _f:
    STATIC = json.load(_f)

LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR')

DEFAULTS = STATIC['defaults']
DEFAULT_PORT = DEFAULTS['port']
DEFAULT_BIND = DEFAULTS['bind']
DEFAULT_UPSTREAM = DEFAULTS['upstream']
DEFAULT_PROM_PREFIX = DEFAULTS['prom_prefix']
PROXY_TIMEOUT_S = DEFAULTS['proxy_timeout_s']
DEFAULT_LOG_LEVEL = DEFAULTS['log_level']
AUDIT_MAX_MB = DEFAULTS['audit_max_mb']
AUDIT_FILES = DEFAULTS['audit_files']
CLI_KEEPALIVE_S = DEFAULTS['cli_keepalive_s']
CLI_TIMEOUT_S = DEFAULTS['cli_timeout_s']
CLI_RECONNECT = DEFAULTS['cli_reconnect']
CLI_RECONNECT_WAIT_S = DEFAULTS['cli_reconnect_wait_s']
CONTROL_IDLE_TIMEOUT_S = DEFAULTS['control_idle_timeout_s']
