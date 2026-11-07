#!/usr/bin/env python3
"""The scraper's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name (the set-grammar config key and the `set <name>` control
name), the flag, the env twin(s), the optional display group (a row may
carry a `group` — the surfaces bucket it under it; ungrouped rows render
bare), the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable (a '/'-path — `inverter/profile` spells as its words on the
wire: `set inverter profile <value>`), and the secret flag. This module
loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary, the static.json-wired defaults and choices, the resolved-config
key renames and the set-grammar rendering of the effective values. The
config script (the ini's replacement), `show config`, the knob ->
control-command mapper, the argparse parser (--help, built from these rows —
common/options.py build_parser) and scripts/check_options.py all read this
table."""
import json
import os

from common.options import Option, as_bool, make_describe, settings_of

_CONV = {'str': str, 'int': int, 'float': float, 'bool': bool}

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the scraper it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'poll', 'dump', 'restore', 'reload', 'reload-config', 'restart',
               'clear', 'shutdown', 'help', 'ping', 'quit')   # 'clear': the default ops policy names it;
                                                               # the wire answers unknown command (nothing to flush)


def _load_options():
    """The rows from lib/options.json (next to this loader). A bool knob
    without an explicit default parses as the argparse store_true native
    (False); a value knob defaults to None — the resolution layers decide.
    The control-grammar vocabulary (the live setting's short description,
    the completable value words, the shape hint, the per-value notes) rides
    the same rows. The static.json-wired bits ride here too (the audit
    log's rotation defaults, the log-level choices) so the constants keep
    their one home."""
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, 'static.json'), encoding='utf-8') as f:
        static = json.load(f)
    defaults = static['defaults']
    static_defaults = {'audit-max-mb': defaults['audit_max_mb'],
                       'audit-files': defaults['audit_files']}
    with open(os.path.join(here, 'options.json'), encoding='utf-8') as f:
        meta = json.load(f)
    rows = meta['options']
    global SHOW_COMMANDS, SHOW_WORDS, SHOW_HIDDEN, SHOW_VALUES, SHOW_GROUPS, SHOW_OPTIONS, SHOW_BY_LIVE
    global COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN, COMMAND_INTERNAL
    SHOW_COMMANDS = tuple((r['name'], r.get('setting-help') or r.get('help', ''), as_bool(r.get('hidden')),
                           r.get('group'))
                          for r in meta.get('show') or [])
    SHOW_WORDS = tuple(w for w, _, _, _ in SHOW_COMMANDS)
    SHOW_HIDDEN = frozenset(w for w, _, hid, _ in SHOW_COMMANDS if hid)
    SHOW_VALUES = tuple((w, d) for w, d, _, _ in SHOW_COMMANDS)
    SHOW_GROUPS = {w: g for w, _, _, g in SHOW_COMMANDS}
    # the show commands expand into the live-path space: the row's own
    # `live` when it spells the hierarchy, else the word itself
    SHOW_OPTIONS = tuple(Option(r['name'], None, None,
                                help=r.get('setting-help') or r.get('help', ''),
                                live=r.get('live') or r['name'],
                                group=r.get('group'),
                                setting_help=r.get('setting-help'),
                                hidden=as_bool(r.get('hidden')))
                         for r in meta.get('show') or [])
    SHOW_BY_LIVE = {o.live: o.name for o in SHOW_OPTIONS}   # the hierarchy live -> the report's word
    # the control commands: the registries' `commands` rows (the wire's
    # verb list — the console help, the completion pools and the editor
    # read these). The wire spells the row's `live` — the show rows'
    # fallback (the live when the row spells one, else the name); the
    # name is the registry key, never typed. The maps key by the wire
    # word. An `internal` row is the machinery's own word — the wire
    # answers, the cli never offers or lists it.
    cmd_rows = meta.get('commands') or []
    commands, cmd_help, cmd_groups, cmd_hidden = [], {}, {}, set()
    cmd_internal = set()
    for r in cmd_rows:
        w = r.get('live') or r['name']
        if as_bool(r.get('node')):   # a tree row: its descr carries the namespace's word-help
            cmd_help[w] = r.get('help', '')   # (the walk-on borrows it); it is no command word itself
            continue
        commands.append(w)
        cmd_help[w] = r.get('help', '')
        cmd_groups[w] = r.get('group', '')
        if as_bool(r.get('hidden')):
            cmd_hidden.add(w)
        if as_bool(r.get('internal')):
            cmd_internal.add(w)
    COMMANDS = tuple(commands)
    COMMAND_HELP = cmd_help
    COMMAND_GROUPS = cmd_groups
    COMMAND_HIDDEN = frozenset(cmd_hidden)
    COMMAND_INTERNAL = frozenset(cmd_internal)   # the machinery's words: the wire answers, the cli never offers
    out = []
    for row in rows:
        opt = Option(row['name'], row.get('flag'), row.get('env'),
                     help=row.get('help', ''), conv=_CONV[row.get('conv', 'str')],
                     live=row.get('live'), alias=row.get('alias'),
                     secret=as_bool(row.get('secret')),
                     group=row.get('group'),
                     setting_help=row.get('setting-help'), values=row.get('values'),
                     hint=row.get('hint'), value_help=row.get('value-help'),
                     min=row.get('min'), max=row.get('max'), check=row.get('check'),
                     node=as_bool(row.get('node')), hidden=as_bool(row.get('hidden')),
                     restart=as_bool(row.get('restart')))
        if 'default' in row:
            opt.default = row['default']
        elif opt.conv is bool:
            opt.default = False
        if opt.name in static_defaults:
            opt.default = static_defaults[opt.name]
        if opt.name == 'log-level':
            opt.choices = tuple(static['log_levels'])
            opt.values = opt.choices   # the control grammar's completable words
        out.append(opt)
    return tuple(out)


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
CFG_KEYS = {'log-level': 'level'}

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
ALIAS_NAMES = tuple(alias_names)                  # the ?/TAB pools ride them beside the canonicals
SHOW_LIVES = frozenset(o.live for o in SHOW_OPTIONS)   # the show reports' lives: show answers them, set/unset never offers them
LIVE_SETTINGS = frozenset(o.live for o in OPTIONS if o.live) | SHOW_LIVES   # the live-named settings: the pools list these — a row the registry spells
# without a `live` name (the restart-marked startup knobs, mid-grant) never lists
# The custom show words ride the registry's `show` section (the loader
# reads them into SHOW_COMMANDS/SHOW_WORDS/SHOW_HIDDEN/SHOW_VALUES): the
# non-knob, non-control-grammar views the show verb answers — the hidden
# ones answer on the wire but never list in the ?/TAB pools.

NODE_BY_NAME = {o.name: o for o in OPTIONS if o.node}   # the hierarchy nodes (help-only)
HIDDEN_SETTINGS = frozenset(o.live for o in OPTIONS if o.hidden and o.live) \
    | frozenset(o.live for o in SHOW_OPTIONS if o.hidden and o.live) \
    | frozenset(o.alias for o in OPTIONS if o.hidden and o.alias) \
    | frozenset(o.alias for o in SHOW_OPTIONS if o.hidden and o.alias) \
    | frozenset(o.name for o in OPTIONS if o.hidden and not o.live)   # the flat hidden knobs (the restart ones)
describe_setting, describe_value = make_describe(SETTING_BY_NAME)


# The custom show words: the non-knob, non-control-grammar views the show
# verb answers (`show status`, `show connections`, ...) — the word, the
# short description the ?/TAB listing renders, and the hidden mark (the
# word answers on the wire but never lists in the ?/TAB pool — the
# power-user views; `help config`/`help knobs` map them).
# the knob -> the ?/TAB descriptions the show words render (the registry's
# `show` section feeds them; nothing hardcodes a show word here)
