#!/usr/bin/env python3
"""Single source of truth for the fake inverter's control grammar: every
command and setting with its short description and value hints. Both the
control server (lib.control) and the console CLI (fake_cli) read from here,
so the wire grammar, the help texts and the completions can never drift."""


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
    Setting('pv', 'pin the PV power in W, or auto', ('auto',), 'W|auto',
            {'auto': 'follow the simulation'}),
    Setting('load', 'pin the home load in W, or auto', ('auto',), 'W|auto',
            {'auto': 'follow the simulation'}),
    Setting('batt', 'pin the battery power in W (+charge/-discharge), or auto', ('auto',), 'W|auto',
            {'auto': 'follow the simulation'}),
    Setting('soc', 'pin the state of charge (seeds the machine), or auto', ('auto',), '%|auto',
            {'auto': 'follow the simulation'}),
    Setting('cloud', 'scale the PV: 0 = clear, 1 = dark, auto, or a cloud machine', ('auto', 'autumn', 'winter'),
            '0..1|auto|autumn|winter',
            {'auto': 'clear sky', 'autumn': 'passing clouds, quick swings',
             'winter': 'heavy overcast spells, slow breaks'}),
    Setting('time', 'freeze the clock HH:MM (jumps integrate the battery), or auto', ('auto',), 'HH:MM|auto',
            {'auto': 'follow the real clock'}),
    Setting('scenario', 'preset scene; releases the value pins',
            ('morning', 'noon', 'evening', 'night', 'custom'), None,
            {'morning': 'freeze 08:30 + release the pins',
             'noon': 'freeze 12:00 + release the pins',
             'evening': 'freeze 19:30 + release the pins',
             'night': 'freeze 23:00 + release the pins',
             'custom': 'no preset (a value was pinned by hand)'}),
    Setting('chaos', 'hostile-reply probability; off = disable', ('off',), '0..1|off',
            {'off': 'disable chaos'}),
    Setting('seed', 're-seed the chaos RNG', (), 'N', {}),
    Setting('battery', 'toggle the simulated LUNA2000', ('on', 'off'), None,
            {'on': 'simulate the LUNA2000', 'off': 'no battery values'}),
    Setting('strict', 'reject undefined registers with exception 02', ('on', 'off'), None,
            {'on': 'exception 02 on undefined registers', 'off': 'read them as 0'}),
    Setting('static', 'constant demo values instead of the day simulation', ('on', 'off'), None,
            {'on': 'constant demo values', 'off': 'day simulation'}),
    Setting('max-kwp', 'PV array size (peak = 75 % of it)', (), 'kW', {}),
    Setting('battery-kwh', 'usable battery capacity', (), 'kWh', {}),
    Setting('profile', 'register-map profile (JSON: name -> register + optional type/scale)', (), '<file>',
            {'default': 'the shipped SUN2000 map'}),
    Setting('log-level', 'log verbosity', ('DEBUG', 'INFO', 'WARNING', 'ERROR'), None,
            {'DEBUG': 'client traffic + per-poll detail',
             'INFO': 'lifecycle, control commands, writes',
             'WARNING': 'problems only',
             'ERROR': 'quietest'}),
)

SETTING_BY_NAME = {s.name: s for s in SETTINGS}
SETTING_NAMES = tuple(s.name for s in SETTINGS)

# command -> short description (the CLI's first-word completions)
COMMANDS = (
    ('set', 'configure a setting: set <setting> <value>'),
    ('unset', 'restore a setting to its configured value: unset <setting>'),
    ('show', 'display a setting or all: show <setting|settings>'),
    ('status', 'effective register state + pins'),
    ('reset', 'clear all pins + the write overlay'),
    ('shutdown', 'stop the fake inverter (asks to confirm)'),
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
