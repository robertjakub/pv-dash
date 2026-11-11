#!/usr/bin/env python3
"""The cache's option registry — the one row per knob (docs/TODO.md, "one
knob, one source"): the rows live in lib/options.json next to this loader —
the registry name (the set-grammar config key and the `set <name>` control
name, dashes included), the flag, the env twin(s), the optional display
group (a row may carry a `group` — the surfaces bucket it under it;
ungrouped rows render bare), the knob's description (the shared help
text --help and the man pages render), whether the knob is live-settable
(the control `set` name — a '/'-path spelled as its words on the wire:
`set modbus profile <value>` — when it is) and whether it is a secret.
This module
loads the JSON into the common Option rows and keeps the Python-side wiring:
the control-grammar vocabulary, the resolved-config key renames and the
set-grammar rendering of the effective values. The config script (the ini's
replacement), `show config`, the knob -> control-command mapper, the
argparse parser (--help, built from these rows — common/settings/options.py
build_parser) and scripts/check_options.py all read this table."""
import json
import os

from common.modbus.protocol import apply_socket_timeout
from common.settings.options import default_ops_verbs, known_verbs, load_registry, make_describe, registry_view, settings_of


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
    apply_socket_timeout(options)   # the modbus timeout's default is the protocol tree's socket_timeout
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
# (the `set`/`clear` vocabulary, the console completions and word-help);
# the show commands ride the same space under their flat words, so
# ?/TAB/the groups run one machinery for both. The registry_view builds
# the tables once for the family: SET_BY_NAME is the KNOB rows only — a
# show report never joins it, so it cannot shadow a knob VALUE on the
# wire: `set write-registers profile` is the write-registers knob taking
# 'profile', while `show write-registers-table` answers the report — one
# word per side of the verb
_VIEW = registry_view(OPTIONS, SHOW_OPTIONS)
SETTINGS = _VIEW.settings
SETTING_BY_NAME = _VIEW.setting_by_name   # the FLAT wire names — the daemon's match map
SETTING_SPELLINGS = _VIEW.spellings   # + the console spellings (the live/alias paths) — the cli's match map
SETTING_NAMES = _VIEW.setting_names   # the flat names: the dump keys, the clear defaults, the help lists
POOL_NAMES = _VIEW.pool_names   # the console spellings (the lives + aliases) — the ?/TAB pools' raw list
ALIAS_NAMES = _VIEW.alias_names
SET_BY_NAME = _VIEW.set_by_name
SHOW_LIVES = _VIEW.show_lives
LIVE_SETTINGS = _VIEW.live_settings   # a row the registry spells without a `live` name (the restart-marked
HIDDEN_SETTINGS = _VIEW.hidden_settings   # startup knobs, mid-grant) never lists; the wire still answers
NODE_BY_NAME = _VIEW.node_by_name
describe_setting, describe_value = _VIEW.describe


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
