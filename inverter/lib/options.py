#!/usr/bin/env python3
"""The fake's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name, the flag, the env twin(s), the section it files under
(common/options.py SECTIONS), the optional finer display group (a row may
carry a `group` — the surfaces bucket it under it instead of its section),
the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable (a '/'-path — `inverter/profile` spells as its words on the
wire: `set inverter profile <value>`), and the secret flag. This module
loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary, the static.json-wired CLI defaults (the fake parses its
settings straight off the argv — F11: no config file) and the choice
vocabularies (log-level from static.json, the timezone from the settings
registry's values). The fake is a test instrument (F11) and never carried a
config file — its startup surface is the flags and the env layer — so
unlike the serving tools it has no --config; the registry still drives
`show config` (the set-grammar form of the running fake's startup options —
the argv that would restart it), the knob -> control-command mapper and
scripts/check_options.py."""
import json
import os

from common.options import Option, make_describe, settings_of

_CONV = {'str': str, 'int': int, 'float': float, 'bool': bool}

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the fake it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'reset', 'clear', 'shutdown',
               'help', 'ping', 'quit')


def _load_options():
    """The rows from lib/options.json (next to this loader). A bool knob
    without an explicit default parses as the argparse store_true native
    (False) unless the row negates one (--no-battery); a value knob
    defaults to None. Control-only settings (the pins and the machines —
    a live `set` name, no flag) ride the same rows with their control
    vocabulary. The CLI defaults come from static.json (the same defaults
    block lib/statics.py serves the rest of the tool) — read directly here
    so the module also imports flat (scripts/check_options.py walks lib/
    on sys.path)."""
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, 'static.json'), encoding='utf-8') as f:
        static = json.load(f)
    d = static['defaults']
    static_defaults = {'host': d['host'], 'port': d['modbus_port'], 'unit': d['unit'],
                       'max-kwp': d['max_kwp'], 'battery-kwh': d['battery_kwh'],
                       'time-scale': d['time_scale'], 'chaos': d['chaos'],
                       'max-clients': d['max_clients'], 'client-timeout': d['client_timeout_s'],
                       'max-conn-per-ip': d['max_conn_per_ip'],
                       'metrics-listen': d['metrics_listen'],
                       'metrics-max-clients': d['metrics_max_clients'],
                       'metrics-client-timeout': d['metrics_client_timeout_s'],
                       'metrics-max-conn-per-ip': d['metrics_max_conn_per_ip'],
                       'audit-max-mb': d['audit_max_mb'], 'audit-files': d['audit_files'],
                       'log-level': d['log_level'],
                       'grid-voltage': static['grid']['voltage_v'],
                       'grid-frequency': static['grid']['frequency_hz'],
                       'timezone': 'utc',       # the settings registry's default
                       'battery': True}         # --no-battery turns it off
    choices = {'log-level': tuple(static['log_levels']), 'timezone': ('utc', 'local')}
    with open(os.path.join(here, 'options.json'), encoding='utf-8') as f:
        meta = json.load(f)
        rows = meta['options']
        global SHOW_COMMANDS, SHOW_WORDS, SHOW_HIDDEN, SHOW_VALUES, SHOW_GROUPS, SHOW_OPTIONS, SHOW_BY_LIVE
        global COMMANDS, COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN
        SHOW_COMMANDS = tuple((r['name'], r.get('setting-help') or r.get('help', ''), bool(r.get('hidden', False)),
                               r.get('group'))
                              for r in meta.get('show') or [])
        SHOW_WORDS = tuple(w for w, _, _, _ in SHOW_COMMANDS)
        SHOW_HIDDEN = frozenset(w for w, _, hid, _ in SHOW_COMMANDS if hid)
        SHOW_VALUES = tuple((w, d) for w, d, _, _ in SHOW_COMMANDS)
        SHOW_GROUPS = {w: g for w, _, _, g in SHOW_COMMANDS}
        # the show commands expand into the live-path space: the row's own
        # `live` when it spells the hierarchy, else the word itself
        SHOW_OPTIONS = tuple(Option(r['name'], None, None, None,
                                    help=r.get('setting-help') or r.get('help', ''),
                                    live=r.get('live') or r['name'],
                                    group=r.get('group'),
                                    setting_help=r.get('setting-help'),
                                    hidden=bool(r.get('hidden', False)))
                             for r in meta.get('show') or [])
        SHOW_BY_LIVE = {o.live: o.name for o in SHOW_OPTIONS}   # the hierarchy live -> the report's word
        # the control commands: the registries' `commands` rows (the wire's
        # verb list — the console help, the completion pools and the editor
        # read these)
        cmd_rows = meta.get('commands') or []
        COMMANDS = tuple(r['name'] for r in cmd_rows)
        COMMAND_HELP = {r['name']: r.get('help', '') for r in cmd_rows}
        COMMAND_GROUPS = {r['name']: r.get('group', '') for r in cmd_rows}
        COMMAND_HIDDEN = frozenset(r['name'] for r in cmd_rows if r.get('hidden'))
    out = []
    for row in rows:
        opt = Option(row['name'], row.get('flag'), row.get('env'), row['section'],
                     help=row.get('help', ''), conv=_CONV[row.get('conv', 'str')],
                     live=row.get('live'), alias=row.get('alias'),
                     secret=bool(row.get('secret', False)),
                     group=row.get('group'),
                     choices=choices.get(row['name']), negates=row.get('negates'),
                     setting_help=row.get('setting-help'), values=row.get('values'),
                     hint=row.get('hint'), value_help=row.get('value-help'),
                     min=row.get('min'), max=row.get('max'), check=row.get('check'), hidden=bool(row.get('hidden', False)),
                     node=bool(row.get('node', False)))
        if opt.name in static_defaults:
            opt.default = static_defaults[opt.name]
        elif 'default' in row:
            opt.default = row['default']
        elif opt.conv is bool and not opt.negates:
            opt.default = False
        if opt.name == 'log-level':
            opt.values = choices['log-level']   # the control grammar's completable words
        out.append(opt)
    return tuple(out)


# the control commands (the registries' `commands` rows — _load_options
# fills these from lib/options.json; the module-level empties keep the
# import flat when a walk skips the loader's registry)
COMMANDS = ()
COMMAND_HELP = {}
COMMAND_GROUPS = {}
COMMAND_HIDDEN = frozenset()

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
ALIAS_NAMES = tuple(alias_names)                  # the ?/TAB pools ride them beside the canonicals
SHOW_LIVES = frozenset(o.live for o in SHOW_OPTIONS)   # the show reports' lives: show answers them, set/unset never offers them
HIDDEN_SETTINGS = frozenset(o.live for o in OPTIONS if o.hidden and o.live) \
    | frozenset(o.live for o in SHOW_OPTIONS if o.hidden and o.live) \
    | frozenset(o.alias for o in OPTIONS if o.hidden and o.alias) \
    | frozenset(o.alias for o in SHOW_OPTIONS if o.hidden and o.alias)
   # the rows that never list in the ?/TAB pools (the wire still answers)

NODE_BY_NAME = {o.name: o for o in OPTIONS if o.node}   # the hierarchy nodes (help-only)
describe_setting, describe_value = make_describe(SETTING_BY_NAME)

# command -> short description (the CLI's first-word completions)
