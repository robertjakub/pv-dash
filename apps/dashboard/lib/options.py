#!/usr/bin/env python3
"""The dashboard's option registry — the one row per knob (docs/TODO.md,
"one knob, one source"): the rows live in lib/options.json next to this
loader — the registry name (the set-grammar config key and the `set <name>`
control name), the flag, the env twin(s), the optional display group (a
row may carry a `group` — the surfaces bucket it under it; ungrouped rows
render bare), the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable (a '/'-path — `modbus/profile` spells as its words on the
wire: `set modbus profile <value>`), and the secret flag. This module
loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary, the log-level choices, the
resolved-config key renames and the set-grammar rendering of the effective
values. The config script (the ini's replacement), `show config`, the knob
-> control-command mapper, the argparse parser (--help, built from these
rows — common/settings/options.py build_parser) and scripts/gates/check_options.py all
read this table."""
import os

from common.settings.options import load_options_module, registry_view, unpack_registry_view


def _load_options():
    """The rows from lib/options.json (next to this loader): the shared
    registry parser (common/settings/options.py parse_registry_sections — the
    show/commands sections, the control-grammar vocabulary), the shared row
    builder (option_rows) and the shared loader glue (load_options_module —
    the rows carry their `default`, the static rung; lib/statics.py reads
    them off OPTIONS). No static default rides the argparse parser: a
    static-wired default would shadow the env layer (the resolver never
    falls through a truthy flag value) — every knob ladders
    flag > env > config > the row's default in lib/config.py, the rows read
    there (a wired listen hid the LISTEN env once). defaults.json is read
    directly so the module also imports flat (scripts/gates/check_options.py
    walks lib/ on sys.path)."""
    return load_options_module(globals(), os.path.dirname(os.path.realpath(__file__)))


# the control commands (the registries' `commands` rows — _load_options
# fills these from lib/options.json; the module-level empties keep the
# import flat when a walk skips the loader's registry)
COMMANDS = ()
COMMAND_HELP = {}
COMMAND_GROUPS = {}
COMMAND_HIDDEN = frozenset()
COMMAND_INTERNAL = frozenset()

OPTIONS = _load_options()

OPTION_BY_NAME = {o.name: o for o in OPTIONS}

# the resolved-config keys that do not follow the name.replace('-', '_') rule
CFG_KEYS = {'log-level': 'level', 'prom-prefix': 'prom_prefix', 'static-dir': 'static_dir',
            'config-js': 'config_js'}

# the control grammar's live settings — the SAME rows, viewed from the wire
# (the `set`/`clear` vocabulary, the console completions and word-help).
# The registry_view builds the tables once for the family: SET_BY_NAME is
# the KNOB rows only — a show report never joins it, so it cannot shadow a
# knob VALUE on the wire (one word per side of the verb); the row aliases
# answer the cli beside the flat names (the cli translates them)
unpack_registry_view(registry_view(OPTIONS, SHOW_OPTIONS), globals())


# the show words ride the registry's `show` section (the loader reads them
# into SHOW_COMMANDS/SHOW_WORDS/SHOW_HIDDEN/SHOW_VALUES)
