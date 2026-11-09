#!/usr/bin/env python3
"""The fake's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name, the flag, the env twin(s), the optional display group
(a row may carry a `group` — the surfaces bucket it under it; ungrouped
rows render bare), the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable (a '/'-path — `inverter/profile` spells as its words on the
wire: `set inverter profile <value>`), and the secret flag. This module
loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary and the choice vocabularies (log-level from static.json, the
timezone from the settings registry's values). The fake takes the family's
config file now (--config, the set grammar — inverter/examples/inverter.conf
is the bundled sample): the CLI defaults stay out of the parser (a
static-wired default would shadow the env/config layers — the flag never
looks unset) and ladder flag > env > config > static in lib/config.py like
every serving tool's resolver. The registry still drives `show config` (the
set-grammar form of the running fake's effective startup options), the knob
-> control-command mapper and scripts/check_options.py."""
import json
import os

from common.options import as_bool, make_describe, option_rows, parse_registry_sections, settings_of


# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the fake it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'reset', 'clear', 'reload', 'dump', 'restore', 'shutdown',
               'help', 'ping', 'quit')


def _load_options():
    """The rows from lib/options.json (next to this loader): the shared
    registry parser (common/options.py parse_registry_sections — the
    show/commands sections, the control-grammar vocabulary) and the
    shared row builder (option_rows). Control-only settings (the pins and
    the machines — a live `set` name, no flag) ride the same rows with
    their control vocabulary. The CLI defaults stay out of the parser
    (a static-wired default would shadow the env/config layers — the flag
    never looks unset): they ladder flag > env > config > static in
    lib/config.py like every serving tool's resolver; only the choice
    vocabularies ride here (log-level from static.json, the timezone —
    read directly so the module also imports flat
    (scripts/check_options.py walks lib/ on sys.path))."""
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, 'static.json'), encoding='utf-8') as f:
        static = json.load(f)
    choices = {'log-level': tuple(static['log_levels']), 'timezone': ('utc', 'local')}
    with open(os.path.join(here, 'options.json'), encoding='utf-8') as f:
        meta = json.load(f)
        rows = meta['options']
        for key, value in parse_registry_sections(meta).items():
            globals()[key] = value
    return option_rows(rows, choices=choices)


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
# (the `set`/`unset` vocabulary: the pins, the machines, the live knobs;
# the console completions and word-help)
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

# command -> short description (the CLI's first-word completions)
