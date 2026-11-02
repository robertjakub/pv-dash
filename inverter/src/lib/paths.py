#!/usr/bin/env python3
"""The default control-socket path, shared by the fake and its CLI tool.

Short and determinable on every platform: /tmp (cleared on reboot), one
instance per Modbus port, nothing ever lands in a working directory or a
source tree.

Both programs resolve the control target the same way: --control-port flag
> FAKE_CTL environment variable > default socket for the Modbus port."""
import os

DEFAULT_MODBUS_PORT = 5502


def default_socket(modbus_port=DEFAULT_MODBUS_PORT):
    return '/tmp/fake-inverter-%d.socket' % int(modbus_port)


def resolve_control_target(explicit, modbus_port=DEFAULT_MODBUS_PORT):
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('FAKE_CTL')
    if env and env.strip():
        return env.strip()
    return default_socket(modbus_port)
