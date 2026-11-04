#!/usr/bin/env python3
"""Single source of truth for the cache's control grammar: every command and
setting with its short description and value hints. Both the control server
(lib.control) and the console CLI (cache_cli) read from here, so the wire
grammar, the help texts and the completions can never drift."""


class Setting:
    def __init__(self, name, help, values=(), hint=None, value_help=None):
        self.name = name
        self.help = help
        self.values = values              # completable words
        self.hint = hint                  # free-text value shape shown after the list
        self.value_help = value_help or {}   # per-value short description

    @property
    def value_shape(self):
        if self.hint:
            return self.hint
        if self.values:
            return '|'.join(self.values)
        return 'value'


# name, description, completable values, value-shape hint, per-value descriptions
SETTINGS = (
    Setting('interval', 'seconds between cache polls of the device', (), 's', {}),
    Setting('ttl', 'per-register cache TTL: older entries are refetched', ('off',), 's|off',
            {'off': 'never expire: serve the last known values forever'}),
    Setting('read-delay', 'seconds between consecutive device reads within a poll cycle', (), 's',
            {'0': 'no wait between reads'}),
    Setting('merge-gap', 'max register gap when merging ranges into block reads; the plan rebuilds', (), 'registers',
            {'0': 'read each range separately'}),
    Setting('allow-write', 'forward write requests (FC05/06/15/16) to the device', ('on', 'off'), None,
            {'on': 'forward writes (the ACLs and the allow-list still gate them)',
             'off': 'refuse writes with a Modbus illegal-function exception (the default)'}),
    Setting('write-registers', 'the register ranges a write may touch: START:COUNT,...', ('any',), 'START:COUNT,...|any',
            {'any': 'every register writable (the default)'}),
    Setting('max-clients', 'simultaneous client limit', (), 'N',
            {'0': 'no limit'}),
    Setting('client-timeout', 'disconnect clients silent for this long', (), 's',
            {'0': 'never disconnect idle clients'}),
    Setting('reads-audit', 'audit one READS tally per client per this many seconds', ('off',), 's|off',
            {'off': 'no per-client read tallies'}),
    Setting('log-level', 'log verbosity', ('DEBUG', 'INFO', 'WARNING', 'ERROR'), None,
            {'DEBUG': 'client traffic + per-poll detail',
             'INFO': 'lifecycle, control commands, writes',
             'WARNING': 'problems only',
             'ERROR': 'quietest'}),
    Setting('profile', 'device profile JSON: the register ranges to cache (a bare name resolves in profiles/)', ('default',), '<file>',
            {'default': 'the bundled sun2000 profile'}),
    Setting('selection', 'selection JSON: which profile names to fetch ("all" = every profile entry)', ('all',), '<file>|all',
            {'all': 'every profile entry (the default)'}),
    Setting('connect-acl', 'clients allowed to connect: "any" or comma-separated IPs/prefixes', ('any',), 'any|IP,...',
            {'any': 'every client may connect (the default)'}),
    Setting('write-acl', 'clients allowed to write (requires allow-write): "any" or comma-separated IPs/prefixes', ('any',), 'any|IP,...',
            {'any': 'the write gate is allow-write alone (the default)'}),
    Setting('timeout', 'upstream Modbus connect/read timeout in seconds', (), 's', {}),
)

SETTING_BY_NAME = {s.name: s for s in SETTINGS}
SETTING_NAMES = tuple(s.name for s in SETTINGS)

# command -> short description (the CLI's first-word completions)
COMMANDS = (
    ('set', 'configure a setting live: set <setting> <value>'),
    ('unset', 'restore a setting to its configured value: unset <setting>'),
    ('show', 'display a setting, the state or the settings: show <setting|status|connections|cache|settings|version>'),
    ('inspect', 'one pretty dump of everything: the status, the map, the counters'),
    ('clear', 'drop the cached registers, repoll now (clear cache)'),
    ('restart', 'restart the upstream session: connection + cache dropped, repoll'),
    ('shutdown', 'stop the proxy (asks to confirm)'),
    ('quit', 'close the session'),
    ('exit', 'close the session'),
    ('logout', 'close the session'),
    ('?', 'this help'),
)

COMMAND_HELP = dict(COMMANDS)


def describe_setting(name):
    s = SETTING_BY_NAME[name]
    return '%s - %s (values: %s)' % (s.name, s.help, s.value_shape)


def describe_value(name, value):
    """The short description of one VALUE of a setting, if documented
    (case-insensitive: DEBUG/debug, ON/on, ...)."""
    s = SETTING_BY_NAME.get(name)
    if not s:
        return ''
    v = s.value_help
    for cand in (value, value.lower(), value.upper(), value.capitalize()):
        if cand in v:
            return v[cand]
    return ''
