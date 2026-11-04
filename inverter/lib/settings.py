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
    Setting('grid', 'pin the grid power in W (+export/-import), or auto; the battery balances', ('auto',), 'W|auto',
            {'auto': 'grid follows the balance'}),
    Setting('soc', 'pin the state of charge (seeds the machine), or auto', ('auto',), '%|auto',
            {'auto': 'follow the simulation'}),
    Setting('mppt', 'enabled PV strings: string-1 = the east array, string-2 = the west', ('both', 'east', 'west', 'none'), None,
            {'both': 'both strings (the default)', 'east': 'string-1 only: the east array, the morning peak',
             'west': 'string-2 only: the west array, the afternoon peak', 'none': 'no strings: PV = 0'}),
    Setting('cloud', 'scale the PV: 0 = clear, 1 = dark, clear, or a cloud machine', ('clear', 'autumn', 'spring', 'winter'),
            '0..1|clear|autumn|spring|winter',
            {'clear': 'clear sky (default)', 'autumn': 'passing clouds, quick swings',
             'spring': 'fair-weather cumulus, brief dips',
             'winter': 'heavy overcast spells, slow breaks'}),
    Setting('timezone', 'clock the state machines integrate over: UTC (the default) or the local wall clock', ('utc', 'local'), None,
            {'utc': 'UTC (the default)', 'local': 'the host wall clock'}),
    Setting('time', 'freeze the clock HH:MM (jumps integrate the battery), or auto', ('auto',), 'HH:MM|auto',
            {'auto': 'follow the real clock'}),
    Setting('time-scale', 'the simulated clock speed: N× real time — the machines integrate over it', ('1', 'auto'), 'N|1',
            {'1': 'real time (the default)', 'auto': 'real time (same as 1)'}),
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
    Setting('battery', 'toggle the simulated battery', ('on', 'off'), None,
            {'on': 'simulate a battery (the default)', 'off': 'no battery values'}),
    Setting('battery-state', 'force the battery state machine, or auto', ('auto', 'charging', 'discharging'), None,
            {'auto': 'the machine decides (the default)',
             'charging': 'charge at full power', 'discharging': 'discharge at full power'}),
    Setting('grid-voltage', 'nominal grid phase voltage; the machine wanders ±10 % per phase', ('120', '230'), 'V',
            {'120': '120 V nominal (split-phase)', '230': '230 V nominal (the default)'}),
    Setting('grid-frequency', 'nominal grid frequency; the machine wanders around it', (), 'Hz',
            {'50': 'the European/IEC nominal (the default)', '60': 'the American/IEEE nominal'}),
    Setting('grid-outage', 'the grid-outage machine: random blackouts over the simulated clock', ('on', 'off', 'outage'), None,
            {'on': 'the seeded machine drops and restores the grid',
             'off': 'the grid stays up (the default)',
             'outage': 'force the blackout now (until on/off/reset)'}),
    Setting('strict', 'reject undefined registers with exception 02', ('on', 'off'), None,
            {'on': 'exception 02 on undefined registers', 'off': 'read them as 0'}),
    Setting('static', 'constant demo values instead of the day simulation', ('on', 'off'), None,
            {'on': 'constant demo values', 'off': 'day simulation'}),
    Setting('max-kwp', 'PV array size (peak = 75 % of it)', (), 'kW', {}),
    Setting('battery-kwh', 'usable battery capacity', (), 'kWh', {}),
    Setting('profile', 'inverter profile (JSON: name -> register + optional type/scale)', (), '<file>',
            {'default': 'the shipped sun2000 profile'}),
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
    ('show', 'display a setting, the status report, or all: show <setting|status|settings>'),
    ('reset', 'clear all pins + the write overlay'),
    ('shutdown', 'stop the fake inverter (asks to confirm)'),
    ('quit', 'close the session'),
    ('exit', 'close the session'),
    ('logout', 'close the session'),
    ('inspect', 'one pretty dump of everything: the status, the machines, the overlay'),
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
