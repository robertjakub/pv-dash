#!/usr/bin/env python3
"""The default control-socket path and the token-file loader, shared by the
fake and its CLI tools.

Short and determinable on every platform: /tmp (cleared on reboot), one
instance per Modbus port, nothing ever lands in a working directory or a
source tree.

Both programs resolve the control target the same way: --control-port flag
> CTL environment variable > default socket for the Modbus port.
The control token comes from --control-token / CONTROL_TOKEN — the value
may be a file:<path> reference (the first line of an owner-only 0600
file — a key file or a systemd LoadCredential; the loader is the shared
common.config.load_token_file)."""
from common.config import resolve_target
from .statics import DEFAULT_MODBUS_PORT


def default_socket(modbus_port=DEFAULT_MODBUS_PORT):
    return '/tmp/fake-inverter-%d.socket' % int(modbus_port)


def resolve_control_target(explicit, modbus_port=DEFAULT_MODBUS_PORT):
    return resolve_target(explicit, default_socket(modbus_port))
