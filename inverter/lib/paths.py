#!/usr/bin/env python3
"""The default control-socket path and the token-file loader, shared by the
fake and its CLI tools.

Short and determinable on every platform: /tmp (cleared on reboot), one
instance per Modbus port, nothing ever lands in a working directory or a
source tree.

Both programs resolve the control target the same way: --control-port flag
> FAKE_CTL environment variable > default socket for the Modbus port.
The control token comes from --control-token / FAKE_CONTROL_TOKEN, or —
the hardened way — from --control-token-file / FAKE_CONTROL_TOKEN_FILE:
a key file or a systemd LoadCredential, first line = the token (the
loader itself is the shared common.config.load_token_file)."""
import os

from .statics import DEFAULT_MODBUS_PORT


def default_socket(modbus_port=DEFAULT_MODBUS_PORT):
    return '/tmp/fake-inverter-%d.socket' % int(modbus_port)


def resolve_control_target(explicit, modbus_port=DEFAULT_MODBUS_PORT):
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('FAKE_CTL')
    if env and env.strip():
        return env.strip()
    return default_socket(modbus_port)
