#!/usr/bin/env python3
"""The scraper's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name (the set-grammar config key and the `set <name>` control
name), the flag, the env twin(s), the section it files under
(common/options.py SECTIONS), the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable, and the secret flag. This module loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary, the static.json-wired defaults and choices, the resolved-config
key renames and the set-grammar rendering of the effective values. The
config script (the ini's replacement), `show config`, the knob ->
control-command mapper, the argparse parser (--help, built from these rows —
common/options.py build_parser) and scripts/check_options.py all read this
table."""
import json
import os

from common.options import Option, make_describe, settings_of

_CONV = {'str': str, 'int': int, 'float': float, 'bool': bool}

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the scraper it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'request', 'poll', 'clear', 'restart', 'shutdown',
               'help', 'ping', 'quit')


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
        rows = json.load(f)['options']
    out = []
    for row in rows:
        opt = Option(row['name'], row.get('flag'), row.get('env'), row['section'],
                     help=row.get('help', ''), conv=_CONV[row.get('conv', 'str')],
                     live=row.get('live'), secret=bool(row.get('secret', False)),
                     setting_help=row.get('setting-help'), values=row.get('values'),
                     hint=row.get('hint'), value_help=row.get('value-help'))
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


OPTIONS = _load_options()

OPTION_BY_NAME = {o.name: o for o in OPTIONS}

# the resolved-config keys that do not follow the name.replace('-', '_') rule
CFG_KEYS = {'log-level': 'level'}

# the control grammar's live settings — the SAME rows, viewed from the wire
# (the `set`/`unset` vocabulary, the console completions and word-help)
SETTINGS = settings_of(OPTIONS)
SETTING_BY_NAME = {s.name: s for s in SETTINGS}
SETTING_NAMES = tuple(s.name for s in SETTINGS)
describe_setting, describe_value = make_describe(SETTING_BY_NAME)

COMMANDS = ('set', 'unset', 'show', 'inspect', 'request', 'restart', 'shutdown', 'quit')

COMMAND_HELP = {
    'set': 'configure a setting live: set <setting> <value>',
    'unset': 'restore a setting to its configured value: unset <setting>',
    'inspect': 'one pretty dump of everything (the state, the counters, the caps)',
    'show': 'runtime state: show <setting|status|connections|settings|version|knobs>',
    'request': 'request reload: re-read the config (the SIGHUP path, the token file included)',
    'restart': 'drop the Modbus session (reconnects on the next poll)',
    'shutdown': 'stop the scraper gracefully',
    'quit': 'close the session',
    'ping': 'keep-alive: answers pong',
}

SHOW_VALUES = (
    ('status', 'multi-line effective state report: one key=value per field'),
    ('connections', 'the live HTTP clients of /metrics: the gate counters, one row per peer IP'),
    ('settings', 'every tunable setting with its live value, one per line'),
    ('version', 'the modbus-scraper version'),
    ('knobs', 'the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes'),
)


def config_value(name, cfg):
    """The set-grammar form of one option's effective startup value (the
    resolved config dict), or None when it should not render (secrets hide;
    empty values drop — the defaults apply on re-run)."""
    opt = OPTION_BY_NAME[name]
    key = CFG_KEYS.get(name, name.replace('-', '_'))
    v = cfg.get(key)
    if opt.secret:
        return None
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 'true' if v else 'false'
    return str(v)
