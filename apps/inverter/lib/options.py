#!/usr/bin/env python3
"""The fake's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name, the flag, the env twin(s), the optional display group
(a row may carry a `group` — the surfaces bucket it under it; ungrouped
rows render bare), the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable (a '/'-path — `modbus/profile` spells as its words on the
wire: `set modbus profile <value>`), and the secret flag. This module
loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary and the choice vocabularies (log-level from defaults.json, the
timezone from the settings registry's values). The fake takes the family's
config file now (--config, the set grammar —
apps/inverter/examples/modbus-fake-inverter.conf
is the bundled sample): the CLI defaults stay out of the parser (a
static-wired default would shadow the env/config layers — the flag never
looks unset) and ladder flag > env > config > static in lib/config.py like
every serving tool's resolver. The registry still drives `show config` (the
set-grammar form of the running fake's effective startup options), the knob
-> control-command mapper and scripts/gates/check_options.py."""
import os

from common.settings.options import load_options_module, registry_view, unpack_registry_view


def _load_options():
    """The rows from lib/options.json (next to this loader): the shared
    registry parser (common/settings/options.py parse_registry_sections — the
    show/commands sections, the control-grammar vocabulary), the shared row
    builder (option_rows) and the shared loader glue (load_options_module).
    Control-only settings (the pins and the machines — a live `set` name,
    no flag) ride the same rows with their control vocabulary. The CLI
    defaults stay out of the parser (a static-wired default would shadow
    the env/config layers — the flag never looks unset): they ladder
    flag > env > config > static in lib/config.py like every serving
    tool's resolver; only the choice vocabularies ride here (log-level from
    defaults.json, the timezone — read directly so the module also imports
    flat (scripts/gates/check_options.py walks lib/ on sys.path))."""
    return load_options_module(globals(), os.path.dirname(os.path.realpath(__file__)),
                               extra_choices={'timezone': ('utc', 'local')})


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

# the control grammar's live settings — the SAME rows, viewed from the wire
# (the `set`/`clear` vocabulary: the pins, the machines, the live knobs;
# the console completions and word-help). The registry_view builds the
# tables once for the family: SET_BY_NAME is the KNOB rows only — a show
# report never joins it, so it cannot shadow a knob VALUE on the wire (one
# word per side of the verb)
unpack_registry_view(registry_view(OPTIONS, SHOW_OPTIONS), globals())

# command -> short description (the CLI's first-word completions)
