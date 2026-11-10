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
rows — common/settings/options.py build_parser) and scripts/check_options.py all
read this table."""
import json
import os

from common.settings.options import default_ops_verbs, known_verbs, load_registry, make_describe, registry_view, settings_of


def _load_options():
    """The rows from lib/options.json (next to this loader): the shared
    registry parser (common/settings/options.py parse_registry_sections — the
    show/commands sections, the control-grammar vocabulary) and the
    shared row builder (option_rows) — the rows carry their `default` (the
    static rung; lib/statics.py reads them off OPTIONS). The log-level row
    takes its choices from lib/defaults.json (the same LOG_LEVELS the
    control grammar validates against); the loader reads defaults.json
    directly so the module also imports flat (scripts/check_options.py
    walks lib/ on sys.path)."""
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, 'defaults.json'), encoding='utf-8') as f:
        static = json.load(f)
    # no static default rides the argparse parser: a static-wired default
    # would shadow the env layer (the resolver never falls through a truthy
    # flag value) — every knob ladders flag > env > config > the row's
    # default in lib/config.py, the rows read there (a wired listen hid the
    # LISTEN env once)
    rows, sections, options = load_registry(here,
                                            choices={'log-level': tuple(static['log_levels'])})
    for key, value in sections.items():
        globals()[key] = value
    globals()['KNOWN_VERBS'] = known_verbs(sections['COMMANDS'])   # the RBAC vocabulary — the registry's rows are its one home
    globals()['DEFAULT_OPS_VERBS'] = default_ops_verbs(globals()['KNOWN_VERBS'])
    return options


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
_VIEW = registry_view(OPTIONS, SHOW_OPTIONS)
SETTINGS = _VIEW.settings
SETTING_BY_NAME = _VIEW.setting_by_name   # the FLAT wire names — the daemon's match map
SETTING_SPELLINGS = _VIEW.spellings   # + the console spellings (the live/alias paths) — the cli's match map
SETTING_NAMES = _VIEW.setting_names   # the flat names: the dump keys, the clear defaults, the help lists
POOL_NAMES = _VIEW.pool_names   # the console spellings (the lives + aliases) — the ?/TAB pools' raw list
ALIAS_NAMES = _VIEW.alias_names
SET_BY_NAME = _VIEW.set_by_name
SHOW_LIVES = _VIEW.show_lives
LIVE_SETTINGS = _VIEW.live_settings   # a row the registry spells without a `live` name (the restart-marked
HIDDEN_SETTINGS = _VIEW.hidden_settings   # startup knobs, mid-grant) never lists; the wire still answers
NODE_BY_NAME = _VIEW.node_by_name
describe_setting, describe_value = _VIEW.describe


# the show words ride the registry's `show` section (the loader reads them
# into SHOW_COMMANDS/SHOW_WORDS/SHOW_HIDDEN/SHOW_VALUES)

