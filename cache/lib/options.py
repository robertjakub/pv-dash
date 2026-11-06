#!/usr/bin/env python3
"""The cache's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name (the set-grammar config key and the `set <name>` control
name, dashes included), the flag, the env twin(s), the section it files
under (common/options.py SECTIONS), the optional finer display group (a row
may carry a `group` — the surfaces bucket it under it instead of its
section), the knob's description (the shared help
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

from common.options import Option, make_describe, settings_of

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
                     live=row.get('live'), secret=bool(row.get('secret', False)),
                     group=row.get('group'),
                     setting_help=row.get('setting-help'), values=row.get('values'),
                     hint=row.get('hint'), value_help=row.get('value-help'),
                     min=row.get('min'), max=row.get('max'), check=row.get('check'), hidden=bool(row.get('hidden', False)),
                     node=bool(row.get('node', False)))
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
# set must name verbs this server knows).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'request', 'clear', 'restart', 'shutdown',
               'help', 'ping', 'quit')

# the control commands (the registries' `commands` rows — _load_options
# fills these from lib/options.json; the module-level empties keep the
# import flat when a walk skips the loader's registry)
COMMANDS = ()
COMMAND_HELP = {}
COMMAND_GROUPS = {}
COMMAND_HIDDEN = frozenset()

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
SETTING_NAMES = tuple(s.name for s in SETTINGS)
HIDDEN_SETTINGS = frozenset(o.live for o in OPTIONS if o.hidden and o.live) \
    | frozenset(o.live for o in SHOW_OPTIONS if o.hidden and o.live)
   # the rows that never list in the ?/TAB pools (the wire still answers)

NODE_BY_NAME = {o.name: o for o in OPTIONS if o.node}   # the hierarchy nodes (help-only)
describe_setting, describe_value = make_describe(SETTING_BY_NAME)


def config_value(name, cfg):
    """The set-grammar form of one option's effective startup value (the
    resolved config dict), or None when it should not render (unset secrets
    hide; empty strings drop). Secrets never render inline — the file/flag/
    env form is the documented way, and `show config` output must be safe
    to paste."""
    opt = OPTION_BY_NAME[name]
    key = CFG_KEYS.get(name, name.replace('-', '_'))
    v = cfg.get(key)
    if opt.secret:
        return None
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if key in ('connect_acl', 'write_acl'):
        from .config import acl_text
        return acl_text(v)
    if key == 'write_registers':
        from .config import parse_write_registers
        return 'any' if v is None else ('none' if not v else ','.join('%d:%d' % r for r in v))
    if key == 'control_trust_uids':
        return ','.join(str(u) for u in v) if v else None
    if key == 'selection':
        return v or 'all'
    return str(v)
