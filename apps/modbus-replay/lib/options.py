#!/usr/bin/env python3
"""modbus-replay's option registry — the one row per knob (docs/TODO.md,
"one knob, one source"): the rows live in lib/options.json next to this
loader — the registry name, the flag, the env twin, the knob's description
(the shared help text --help and the man page render) — and fold their
family-wide canon blocks (shared/suite/options.json: listen, upstream,
the limits, the audit family). The sidecar has no control plane (no live
rows, no commands): every knob is a startup knob and the registry's
control-grammar half stays empty — the loaders fill the same module names
the family's four loaders publish, they just stay empty here. The CLI
defaults stay out of the parser (a static-wired default would shadow the
env layer — the flag never looks unset): they ladder flag > env > static
in lib/config.py (no config file — the knobs are the flags and their env
twins only); the protocol tree arms the modbus-timeout row's default
(common/modbus/protocol.py apply_socket_timeout)."""
import os

from common.settings.options import load_options_module


def _load_options():
    """The rows from lib/options.json (next to this loader): the shared
    registry parser (the show/commands sections — both empty here, the
    sidecar speaks no control grammar), the shared row builder and the
    loader glue with the protocol tree's socket_timeout splice (the
    modbus-timeout row's default). The module imports flat
    (dev/gates/check_options.py walks lib/ on sys.path)."""
    return load_options_module(globals(), os.path.dirname(os.path.realpath(__file__)),
                               socket_timeout=True)


# the control vocabulary — the loaders' module names, empty by design
# (no control plane: the sidecar has no set/clear/show wire)
COMMANDS = ()
COMMAND_HELP = {}
COMMAND_GROUPS = {}
COMMAND_HIDDEN = frozenset()
COMMAND_INTERNAL = frozenset()

OPTIONS = _load_options()

OPTION_BY_NAME = {o.name: o for o in OPTIONS}
