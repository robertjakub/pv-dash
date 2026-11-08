#!/usr/bin/env python3
"""The cache's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name (the set-grammar config key and the `set <name>` control
name, dashes included), the flag, the env twin(s), the optional display
group (a row may carry a `group` — the surfaces bucket it under it;
ungrouped rows render bare), the knob's description (the shared help
text --help and the man pages render), whether the knob is live-settable
(the control `set` name — a '/'-path spelled as its words on the wire:
`set inverter profile <value>` — when it is) and whether it is a secret.
This module
loads the JSON into the common Option rows and keeps the Python-side wiring:
the control-grammar vocabulary, the resolved-config key renames and the
set-grammar rendering of the effective values. The config script (the ini's
replacement), `show config`, the knob -> control-command mapper, the
argparse parser (--help, built from these rows — common/options.py
build_parser) and scripts/check_options.py all read this table."""
import json
import os

from common.options import Option, as_bool, make_describe, settings_of

_CONV = {'str': str, 'int': int, 'float': float, 'bool': bool}


def _load_options():
    """The rows from lib/options.json (next to this loader). A bool knob
    without an explicit default parses as the argparse store_true native
    (False); a value knob defaults to None — the resolution layers decide.
    The control-grammar vocabulary (the live setting's short description,
    the completable value words, the shape hint, the per-value notes) rides
    the same rows. The log-level row takes its choices from lib/static.json
    (the constants audit's home — the same LOG_LEVELS the control grammar
    validates against); the loader reads it directly so the module also
    imports flat (scripts/check_options.py walks lib/ on sys.path)."""
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, 'static.json'), encoding='utf-8') as f:
        log_levels = tuple(json.load(f)['log_levels'])
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
                cmd_groups[w] = r.get('group', '')   # the namespace word's group in the wire's node listing
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
                     min=row.get('min'), max=row.get('max'), check=row.get('check'), hidden=as_bool(row.get('hidden')),
                     restart=as_bool(row.get('restart')),
                     node=as_bool(row.get('node')))
        if 'default' in row:
            opt.default = row['default']
        elif opt.conv is bool:
            opt.default = False
        if opt.name == 'log-level':
            opt.choices = log_levels
            opt.values = log_levels   # the control grammar's completable words
        out.append(opt)
    return tuple(out)


# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). `request` is the namespace
# prefix, not a verb: the verb is the word past it (`request clear cache`
# decides on `clear`).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'dump', 'restore', 'clear', 'reload', 'restart', 'shutdown',
               'help', 'ping', 'quit')

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
CFG_KEYS = {'log-level': 'level', 'requests-audit': 'requests_audit_s', 'cache-ttl': 'cache_ttl'}

# the control grammar's live settings — the SAME rows, viewed from the wire
# (the `set`/`unset` vocabulary, the console completions and word-help);
# the show commands ride the same space (the live = the word when the row
# spells no hierarchy), so ?/TAB/the groups run one machinery for both
SETTINGS = settings_of(OPTIONS) + settings_of(SHOW_OPTIONS)
SETTING_BY_NAME = {s.name: s for s in SETTINGS}
alias_names = []
for s in SETTINGS:   # the row's `alias` spelling answers the same Setting — the canonical renders
    if s.alias and s.alias not in SETTING_BY_NAME:
        SETTING_BY_NAME[s.alias] = s
        alias_names.append(s.alias)
SETTING_NAMES = tuple(s.name for s in SETTINGS)   # the canonical spellings — the dump keys and the unset defaults iterate these
ALIAS_NAMES = tuple(alias_names)                  # the ?/TAB pools ride them beside the canonicals

# the set/unset vocabulary: the KNOB rows only — a show report's live path
# never joins it, so it cannot shadow a knob VALUE on the wire: `set write
# registers profile` is the write-registers knob taking 'profile', while
# `show write registers profile` answers the write/registers/profile
# report — one spelling per side of the verb
_KNOB_SETTINGS = settings_of(OPTIONS)
SET_BY_NAME = {s.name: s for s in _KNOB_SETTINGS}
for s in _KNOB_SETTINGS:   # the aliases ride the set vocabulary beside the canonicals
    if s.alias and s.alias not in SET_BY_NAME:
        SET_BY_NAME[s.alias] = s
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


def cfg_acl_text(v):
    """The connect/write ACL as its set-grammar text (any, none, the
    ip[/mask] list, or the file: reference)."""
    from .config import acl_value_text
    return acl_value_text(v)


def cfg_write_registers(v):
    """The write-register map as its set-grammar text (any, none, the
    addr:count list, or the 'profile'/'file:<path>' markers — both
    re-resolve on the way back in)."""
    if v is None:
        return 'any'
    if isinstance(v, str):   # the 'profile' marker / the file reference — never a range list
        return v
    return 'none' if not v else ','.join('%d:%d' % r for r in v)


def cfg_trust_uids(v):
    """The trusted-peer uid list as its csv text (empty = nothing renders)."""
    return ','.join(str(u) for u in v) if v else None


def cfg_selection(v):
    """The register-selection spec ('all' when empty)."""
    return v or 'all'


CFG_FORMATTERS = {'connect_acl': cfg_acl_text, 'write_acl': cfg_acl_text,
                  'write_registers': cfg_write_registers, 'control_trust_uids': cfg_trust_uids,
                  'selection': cfg_selection}
