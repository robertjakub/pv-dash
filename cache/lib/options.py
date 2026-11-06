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
        rows = json.load(f)['options']
    out = []
    for row in rows:
        opt = Option(row['name'], row.get('flag'), row.get('env'), row['section'],
                     help=row.get('help', ''), conv=_CONV[row.get('conv', 'str')],
                     live=row.get('live'), secret=bool(row.get('secret', False)),
                     group=row.get('group'),
                     setting_help=row.get('setting-help'), values=row.get('values'),
                     hint=row.get('hint'), value_help=row.get('value-help'))
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

OPTIONS = _load_options()

OPTION_BY_NAME = {o.name: o for o in OPTIONS}

# the resolved-config keys that do not follow the name.replace('-', '_') rule
CFG_KEYS = {'log-level': 'level', 'requests-audit': 'requests_audit_s', 'cache-ttl': 'cache_ttl'}

# the control grammar's live settings — the SAME rows, viewed from the wire
# (the `set`/`unset` vocabulary, the console completions and word-help)
SETTINGS = settings_of(OPTIONS)
SETTING_BY_NAME = {s.name: s for s in SETTINGS}
SETTING_NAMES = tuple(s.name for s in SETTINGS)
describe_setting, describe_value = make_describe(SETTING_BY_NAME)

# command -> short description (the CLI's first-word completions)
COMMANDS = (
    ('set', 'configure a setting live: set <setting> <value>'),
    ('unset', 'restore a setting to its configured value: unset <setting>'),
    ('show', 'display a setting, the state or the settings: show <setting|status|connections|cache|settings|version>'),
    ('inspect', 'one pretty dump of everything: the status, the map, the counters'),
    ('request dump', 'write the cached words + the live setting overrides to the dump path (write-behind)'),
    ('request restore', 'load the dump back: the cached words (+ their stamps) and the setting overrides return'),    ('clear', 'drop the cached registers, repoll now (clear cache)'),
    ('restart', 'restart the upstream session: connection + cache dropped, repoll'),
    ('shutdown', 'stop the proxy (asks to confirm)'),
    ('quit', 'close the session'),
    ('exit', 'close the session'),
    ('logout', 'close the session'),
    ('?', 'this help'),
)

COMMAND_HELP = dict(COMMANDS)


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
