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
a key file or a systemd LoadCredential, first line = the token."""
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


def load_token_file(path, label='control-token-file'):
    """The token from a file: the first line, whitespace-stripped. Fails
    fast with a clean one-liner (an audit trail that silently vanishes is
    worse than no session; so is a token that silently vanishes)."""
    try:
        with open(path, encoding='utf-8') as fh:
            token = fh.readline().strip()
    except OSError as e:
        raise SystemExit('cannot read %s %s: %s' % (label, path, e))
    if not token:
        raise SystemExit('%s %s: the file is empty' % (label, path))
    return token
