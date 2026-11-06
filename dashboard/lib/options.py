#!/usr/bin/env python3
"""The dashboard's option registry — the one row per knob (docs/TODO.md,
"one knob, one source"): the rows live in lib/options.json next to this
loader — the registry name (the set-grammar config key and the `set <name>`
control name), the flag, the env twin(s), the section it files under
(common/options.py SECTIONS), the knob's description (the shared help text
--help and the man pages render), the live control name when the knob is
live-settable, and the secret flag. This module loads the JSON into the
common Option rows and keeps the Python-side wiring: the control-grammar
vocabulary, the static.json-wired audit defaults and log-level choices, the
resolved-config key renames and the set-grammar rendering of the effective
values. The config script (the ini's replacement), `show config`, the knob
-> control-command mapper, the argparse parser (--help, built from these
rows — common/options.py build_parser) and scripts/check_options.py all
read this table."""
import json
import os

from common.options import Option

_CONV = {'str': str, 'int': int, 'float': float, 'bool': bool}

# The verbs the control grammar speaks (the RBAC vocabulary — an ops verb
# set must name verbs this server knows). 'clear' rides along: the family's
# default ops policy names it, and on the dashboard it just answers
# "unknown command" (there is nothing to flush).
KNOWN_VERBS = ('set', 'unset', 'show', 'inspect', 'request', 'clear', 'shutdown',
               'help', 'ping', 'quit')


def _load_options():
    """The rows from lib/options.json (next to this loader). A bool knob
    without an explicit default parses as the argparse store_true native
    (False); a value knob defaults to None — the resolution layers decide.
    The static.json-wired bits ride here (the audit log's rotation defaults,
    the log-level choices) so the constants keep their one home."""
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
        opt = Option(row['name'], row['flag'], row.get('env'), row['section'],
                     help=row.get('help', ''), conv=_CONV[row.get('conv', 'str')],
                     live=row.get('live'), secret=bool(row.get('secret', False)))
        if 'default' in row:
            opt.default = row['default']
        elif opt.conv is bool:
            opt.default = False
        if opt.name in static_defaults:
            opt.default = static_defaults[opt.name]
        if opt.name == 'log-level':
            opt.choices = tuple(static['log_levels'])
        out.append(opt)
    return tuple(out)


OPTIONS = _load_options()

OPTION_BY_NAME = {o.name: o for o in OPTIONS}

# the resolved-config keys that do not follow the name.replace('-', '_') rule
CFG_KEYS = {'log-level': 'level', 'prom-prefix': 'prom_prefix', 'static-dir': 'static_dir',
            'config-js': 'config_js'}


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
