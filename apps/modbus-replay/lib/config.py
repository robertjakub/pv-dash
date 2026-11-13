#!/usr/bin/env python3
"""Configuration for modbus-replay: the env layer and the CLI flags
(stdlib only) — there is no config file. The sidecar keeps its
args-driven shape (the bin reads args.* everywhere), so the resolver's
job is to slot the env layer and the static defaults under the flags
and write the effective values back onto the parsed args namespace:
flag > env > the static defaults (common/settings/config.py Resolver,
keep-last-good) — every flag row the same ladder as every serving
tool's, the config-script leg simply absent."""
import logging

from .options import OPTIONS
from common.settings.config import Resolver, str_to_bool

logger = logging.getLogger('modbus-replay')

# the static defaults the parser no longer carries (a static-wired default
# would shadow the env layer — the flag never looks unset): the registry
# rows' `default` fields — the one home — applied last in the ladder,
# keyed by the row name.
STATIC_DEFAULTS = {o.name: o.static_default for o in OPTIONS if o.static_default is not None}


def resolve_args(args):
    """The sidecar's ladder, family precedence minus the config file:
    CLI flags > env > the static defaults — written back onto the parsed
    args namespace so every args.* reader downstream (validate, the
    serve wiring) sees the effective values. A store_true flag
    can only mean True when given, so the bool rows read False/None as
    unset."""
    r = Resolver({}, logger)
    for o in OPTIONS:
        if not o.flag:
            continue
        dest = o.name.replace('-', '_')
        given = getattr(args, dest)
        if o.conv is bool:
            cli = True if given else None
        else:
            cli = given if (given is not None and given != '') else None
        conv = str_to_bool if o.conv is bool else o.conv
        value = r.resolve(cli, o.env, dest, STATIC_DEFAULTS.get(o.name), conv,
                          row=None if o.conv is bool else o)
        if value is None and o.conv is bool:
            value = False
        setattr(args, dest, value)
