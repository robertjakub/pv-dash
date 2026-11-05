#!/usr/bin/env python3
"""Single source of truth for the dashboard's control grammar: every live
setting with its short description and value hints. The control server
(lib.control), the ctl/cli clients and the man-page generator all read from
here, so the wire grammar, the help texts, the completions and the docs can
never drift."""


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
    Setting('max-clients', 'simultaneous HTTP clients (static pages + the proxy); extras get an immediate 503',
            (), 'N', {'0': 'no limit'}),
    Setting('client-timeout', 'kick idle keep-alive HTTP clients after this long', (), 's',
            {'0': 'never (the built-in slowloris cap still applies on the metrics surfaces that have one)'}),
    Setting('max-conn-per-ip', 'simultaneous HTTP connections from one peer IP', (), 'N',
            {'0': 'no per-IP limit (the default)'}),
    Setting('log-access', 'log every HTTP request at INFO', ('on', 'off'), None,
            {'on': 'audit trail for who loaded the page and polled /prom and when',
             'off': 'quiet (the default)'}),
    Setting('log-queries', 'log the proxied Prometheus queries at INFO', ('on', 'off'), None,
            {'on': 'every /prom query with its status and duration',
             'off': 'quiet (the default)'}),
    Setting('battery', 'serve config.js with the battery panels enabled', ('on', 'off'), None,
            {'on': 'the battery KPIs and charts appear (the reload of the page picks it up)',
             'off': 'the generation-only view (the default)'}),
    Setting('log-level', 'log verbosity', ('DEBUG', 'INFO', 'WARNING', 'ERROR'), None,
            {'DEBUG': 'every request, the proxy detail, the gate decisions',
             'INFO': 'lifecycle, control commands, the upstream up/down flips',
             'WARNING': 'problems only',
             'ERROR': 'quietest'}),
)

SETTING_BY_NAME = {s.name: s for s in SETTINGS}
SETTING_NAMES = tuple(s.name for s in SETTINGS)

COMMANDS = ('set', 'unset', 'show', 'inspect', 'request', 'shutdown', 'quit')

COMMAND_HELP = {
    'set': 'configure a setting live: set <setting> <value>',
    'unset': 'restore a setting to its configured value: unset <setting>',
    'inspect': 'one pretty dump of everything (the state, the counters, the caps)',
    'show': 'runtime state: show <setting|status|connections|settings|version>',
    'request': 'request reload: re-read the config (the SIGHUP path)',
    'shutdown': 'stop the dashboard server gracefully',
    'quit': 'close the session',
    'ping': 'keep-alive: answers pong',
}

SHOW_VALUES = (
    ('status', 'multi-line effective state report: one key=value per field'),
    ('connections', 'the live HTTP clients: the gate counters, one row per peer IP'),
    ('settings', 'every tunable setting with its live value, one per line'),
    ('version', 'the dashboard version'),
)


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
