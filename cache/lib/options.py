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
argparse parser (--help, built from these rows — common/settings/options.py
build_parser) and scripts/check_options.py all read this table."""
import json
import os

from common.settings.options import as_bool, default_ops_verbs, known_verbs, load_registry, make_describe, settings_of


def _load_options():
    """The rows from lib/options.json (next to this loader): the shared
    registry parser (common/settings/options.py parse_registry_sections — the
    show/commands sections, the control-grammar vocabulary) and the
    shared row builder (option_rows). The log-level row takes its choices
    from lib/defaults.json (the constants audit's home — the same
    LOG_LEVELS the control grammar validates against); the loader reads
    it directly so the module also imports flat (scripts/check_options.py
    walks lib/ on sys.path)."""
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, 'defaults.json'), encoding='utf-8') as f:
        log_levels = tuple(json.load(f)['log_levels'])
    rows, sections, options = load_registry(here, choices={'log-level': log_levels})
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
# `show write registers table` answers the write/registers/table
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
    """The connect/write/metrics ACL as its set-grammar text (any, none,
    the ip[/mask] list, or the file: reference)."""
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
    """The trusted-peer uid list as its csv text (empty = nothing renders;
    a csv string — the live set's recorded spelling — rides through)."""
    if isinstance(v, str):
        return v or None
    return ','.join(str(u) for u in v) if v else None


def cfg_selection(v):
    """The register-selection spec ('all' when empty)."""
    return v or 'all'


CFG_FORMATTERS = {'connect_acl': cfg_acl_text, 'write_acl': cfg_acl_text, 'metrics_acl': cfg_acl_text,
                  'write_registers': cfg_write_registers, 'control_trust_uids': cfg_trust_uids,
                  'selection': cfg_selection}
