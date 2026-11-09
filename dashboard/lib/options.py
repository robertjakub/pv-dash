#!/usr/bin/env python3
"""The dashboard's option registry — the one row per knob (docs/TODO.md,
"one knob, one source"): the rows live in lib/options.json next to this
loader — the registry name (the set-grammar config key and the `set <name>`
control name), the flag, the env twin(s), the optional display group (a
row may carry a `group` — the surfaces bucket it under it; ungrouped rows
render bare), the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable (a '/'-path — `inverter/profile` spells as its words on the
wire: `set inverter profile <value>`), and the secret flag. This module
loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary, the static.json-wired audit defaults and log-level choices, the
resolved-config key renames and the set-grammar rendering of the effective
values. The config script (the ini's replacement), `show config`, the knob
-> control-command mapper, the argparse parser (--help, built from these
rows — common/options.py build_parser) and scripts/check_options.py all
read this table."""
import json
import os

from common.options import as_bool, load_registry, make_describe, settings_of


# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the dashboard it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'dump', 'restore', 'reload', 'reload-config', 'clear', 'shutdown',
               'help', 'ping', 'quit')   # 'clear': the default ops policy names it;
                                          # the wire answers unknown command (nothing to flush)


def _load_options():
    """The rows from lib/options.json (next to this loader): the shared
    registry parser (common/options.py parse_registry_sections — the
    show/commands sections, the control-grammar vocabulary) and the
    shared row builder (option_rows). The static.json-wired bits ride
    here too (the audit log's rotation defaults, the log-level choices)
    so the constants keep their one home; the loader reads static.json
    directly so the module also imports flat (scripts/check_options.py
    walks lib/ on sys.path)."""
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, 'static.json'), encoding='utf-8') as f:
        static = json.load(f)
    defaults = static['defaults']
    # the audit rotation defaults do NOT ride the argparse parser: a
    # static-wired default would shadow the env layer (the resolver never
    # falls through a truthy flag value) — they ladder flag > env > config
    # > static in lib/config.py like every other knob
    static_defaults = {'listen': defaults['listen']}
    rows, sections, options = load_registry(here, static_defaults=static_defaults,
                                            choices={'log-level': tuple(static['log_levels'])})
    for key, value in sections.items():
        globals()[key] = value
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
# (the `set`/`unset` vocabulary, the console completions and word-help)
SETTINGS = settings_of(OPTIONS) + settings_of(SHOW_OPTIONS)
SETTING_BY_NAME = {s.name: s for s in SETTINGS}
alias_names = []
for s in SETTINGS:   # the row's `alias` spelling answers the same Setting — the canonical renders
    if s.alias and s.alias not in SETTING_BY_NAME:
        SETTING_BY_NAME[s.alias] = s
        alias_names.append(s.alias)
SETTING_NAMES = tuple(s.name for s in SETTINGS)   # the canonical spellings — the dump keys and the unset defaults iterate these
SET_BY_NAME = {s.name: s for s in settings_of(OPTIONS)}   # the knobs only: the show reports are not settable (and a show path never shadows a knob value — the cache's reading)
ALIAS_NAMES = tuple(alias_names)                  # the ?/TAB pools ride them beside the canonicals
SHOW_LIVES = frozenset(o.live for o in SHOW_OPTIONS)   # the show reports' lives: show answers them, set/unset never offers them
LIVE_SETTINGS = frozenset(o.live for o in OPTIONS if o.live) | SHOW_LIVES   # the live-named settings: the pools list these — a row the registry spells
# without a `live` name (the restart-marked startup knobs, mid-grant) never lists
HIDDEN_SETTINGS = frozenset(o.live for o in OPTIONS if o.hidden and o.live) \
    | frozenset(o.live for o in SHOW_OPTIONS if o.hidden and o.live) \
    | frozenset(o.alias for o in OPTIONS if o.hidden and o.alias) \
    | frozenset(o.alias for o in SHOW_OPTIONS if o.hidden and o.alias) \
    | frozenset(o.name for o in OPTIONS if o.hidden and not o.live)   # the flat hidden knobs (the restart ones)
   # the rows that never list in the ?/TAB pools (the wire still answers)

NODE_BY_NAME = {o.name: o for o in OPTIONS if o.node}   # the hierarchy nodes (help-only)
describe_setting, describe_value = make_describe(SETTING_BY_NAME)


# the show words ride the registry's `show` section (the loader reads them
# into SHOW_COMMANDS/SHOW_WORDS/SHOW_HIDDEN/SHOW_VALUES)

