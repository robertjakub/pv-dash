#!/usr/bin/env python3
"""The family's option registry — one knob, one source (docs/TODO.md).

Every knob of every tool lives here ONCE as an `Option`: its registry name
(the set-grammar config key and the ini-era key, dashes included), the
argparse flag, the environment twin, the **section** it belongs to, its
help text, its converter and its default. From this one row the surfaces
are built or checked:

- the **configuration file** — the set grammar the control servers already
  speak (`parse_config_script` / `render_config_script`): a config file is a
  runnable script, every line a `set <name> <value>`, every comment a `#`
  comment (the ini format is gone — the breaking wave);
- `show knobs` — the **dictionary of all knobs**: every option under its
  section with its flag, its env twin, its home section, the control
  command that changes it (or the restart note) and the secret marker
  (`knob_dictionary` below — registry data only, no values render);
- the **control grammar's live settings** — the `Setting` rows the `set`/
  `unset` verbs, the console completions and the word-help speak, derived
  from the same rows (`settings_of`/`make_describe`: a row's `live` name,
  its `setting_help`, its completable `values`, the value-shape `hint` and
  the per-value `value_help`; a flagless row is a control-only setting —
  the fake's pins and machines);
- `scripts/check_options.py` — the CI gate that the four surfaces (the
  flags, the env names, the bundled config, the NixOS module and the README
  tables) agree with the registry.

Sections are shared here so the whole family files its knobs under the same
heads: device, serving, control plane, metrics, audit, limits, persistence,
logging. Stdlib only."""
import argparse
import os


# --- the shared section heads (the family files its knobs under the same ones) ---
SECTIONS = (
    ('device', 'the device (upstream inverter) and the register map'),
    ('serving', 'what the tool serves and where'),
    ('control', 'the control plane (the JSON-lines server, its tokens, its audit)'),
    ('metrics', 'the own Prometheus /metrics endpoint'),
    ('audit', 'the audit trail'),
    ('limits', 'the connection caps'),
    ('persistence', 'the state dump (write-behind)'),
    ('logging', 'the log surface'),
)


def section_title(key):
    for name, title in SECTIONS:
        if name == key:
            return title
    return key


class Option:
    """One knob: `name` (the config/set-grammar key), `flag` ('--interval';
    None on a control-only setting — a live `set` name with no flag), `env`
    (the twin — a str or a tuple of fallbacks), `section` (a SECTIONS key),
    `help` (the shared help text — the parser's help and the docs render
    it), `conv` (the value shape: str/int/float/bool — bool flags are
    store_true, int/float type the argparse value), `default` (the argparse
    default — None = unset, the resolution layers decide), `live` (the
    control `set` name when the knob is live-settable — the knob ->
    control-command mapper), `secret` (a token: rendered into a config file
    only in its -file form), `choices` (the values the parser accepts) and
    `negates` (the name of the boolean knob this row switches off — the
    --no-x form of an --x flag). A control-only setting (the fake's pins and
    machines) carries the live name and no flag/env; its `setting_help`,
    `values`, `hint` and `value_help` are the control grammar's vocabulary
    (the short description, the completable words, the value shape and the
    per-value notes)."""

    def __init__(self, name, flag, env, section, help='', conv=str, default=None, live=None,
                 secret=False, choices=None, negates=None,
                 setting_help=None, values=None, hint=None, value_help=None):
        self.name = name
        self.flag = flag
        self.env = env
        self.section = section
        self.help = help
        self.conv = conv
        self.default = default
        self.live = live          # the live control setting name, or None = startup-only
        self.secret = bool(secret)
        self.choices = tuple(choices) if choices else None
        self.negates = negates
        self.setting_help = setting_help
        self.values = tuple(values) if values else ()
        self.hint = hint
        self.value_help = dict(value_help or {})

    @property
    def optname(self):
        return self.flag[2:] if self.flag and self.flag.startswith('--') else (self.flag or self.name)

    def env_names(self):
        return self.env if isinstance(self.env, tuple) else (self.env,)


def build_parser(options, prog=None, description=None, epilog=None, add_help=True):
    """The argparse parser for one tool, built from its registry: the one
    source renders --help (and the man pages render from the parser —
    common/manpage.py). Boolean flags become store_true (a `negates` row
    becomes the matching store_false on the negated knob's dest), int/float
    convs type the value, `choices` constrains it; everything else takes a
    free string. The rows carry the defaults (None = unset). Control-only
    settings (no flag) render nowhere here — they live on the wire only."""
    p = argparse.ArgumentParser(prog=prog, description=description, epilog=epilog, add_help=add_help)
    for opt in options:
        if not opt.flag:
            continue
        if opt.negates:
            p.add_argument(opt.flag, dest=opt.negates.replace('-', '_'), action='store_false',
                           help=opt.help)
        elif opt.conv is bool:
            p.add_argument(opt.flag, dest=opt.name.replace('-', '_'), action='store_true',
                           default=opt.default, help=opt.help)
        else:
            p.add_argument(opt.flag, dest=opt.name.replace('-', '_'), default=opt.default,
                           type=(opt.conv if opt.conv in (int, float) else None),
                           choices=opt.choices, help=opt.help)
    return p


def parse_config_script(text, label):
    """Parse one set-grammar config file: every non-comment line is a
    control command — `set <name> <value>` or the bare `<name> <value>`
    shorthand; `#` comments and blank lines stay comments (a config file
    pipes through a ctl client unchanged). Returns [(name, value)]. A line
    the grammar cannot read fails fast with the line number (never partial
    state); the legacy ini shapes (`[section]` headers, `key = value`
    lines) get the pointer to the new form — the ini format is gone."""
    out = []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('['):
            raise ValueError(('%s:%d: the ini format is gone — the config is the control grammar now: '
                              "every line a `set <name> <value>` (or the bare `<name> <value>`), "
                              'comments start with #') % (label, no))
        if line.startswith('set ') or line == 'set':
            body = line[4:].strip()
        elif line.startswith('unset '):
            raise ValueError('%s:%d: unset is a control-session verb, not a config verb: %r'
                             % (label, no, line))
        else:
            body = line
        if not body:
            raise ValueError('%s:%d: a set line needs a name and a value' % (label, no))
        parts = body.split(None, 1)
        if len(parts) != 2:
            raise ValueError('%s:%d: a set line needs a name and a value: %r' % (label, no, line))
        name, value = parts[0], parts[1].strip()
        if '_' in name or value.startswith('='):
            raise ValueError(('%s:%d: the ini format is gone (key = value) — the config is the control grammar: '
                              '`set %s <value>`') % (label, no, name.replace('_', '-')))
        out.append((name, value))
    return out


def render_config_script(options, values, comment=None):
    """The set-grammar form of the current values, grouped under the section
    comments — `show config` prints this, and the output pipes straight back
    into a config file (or a ctl client). Options whose value is None are
    skipped (unset / off)."""
    header = '# pv-suite configuration — every line is a set command (pipe it back through the ctl client)'
    if comment:
        header += '\n# %s' % comment
    lines = [header, '']
    for section, title in SECTIONS:
        rows = [o for o in options if o.section == section]
        if not rows:
            continue
        rows_left = []
        for o in rows:
            v = values.get(o.name)
            if v is None or v == '':
                continue
            rows_left.append('set %s %s' % (o.name, v))
        if rows_left:
            lines.append('# --- %s ---' % title)
            lines.extend(rows_left)
            lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def control_command(opt):
    """The knob -> control-command mapper: the command that changes this knob
    on a running daemon (`set interval 10`), or the note that the knob is
    startup-only (restart to apply)."""
    if opt.live:
        return 'set %s <value>' % opt.live
    return 'restart required (startup-only knob)'


def knob_dictionary(options, who='the tool'):
    """The dictionary of all knobs (`show knobs`): every option of the
    registry under its section, one row per knob with every surface — the
    config/set-grammar name, the argparse flag (control-only settings show
    the set command in their flag's place), the env twin(s), the home
    section, the control command that changes it (or the restart note) and
    the secret marker. Registry data only — no values render here (`show
    config` is the values view), so secrets are named, never shown."""
    lines = ['ok knobs — the registry of %s: every knob, its flag, its env twin, '
             'its section, how it changes' % who]
    for section, title in SECTIONS:
        rows = [o for o in options if o.section == section]
        if not rows:
            continue
        lines.append('# --- %s ---' % title)
        for o in rows:
            env = '/'.join('$' + e for e in o.env_names()) if o.env else '-'
            notes = control_command(o)
            if o.secret:
                notes += ', secret'
            lines.append('%-23s %-26s %-30s %-11s %s'
                         % (o.name, o.flag or '(control-only)', env, section, notes))
    return '\n'.join(lines)


class Setting:
    """One live control setting — the registry's control-grammar view: the
    `set <name>` name, the short description the wire help answers with, the
    completable value words, the value-shape hint (shown after the words)
    and the per-value short descriptions. Derived from the Option rows
    (settings_of) — the registry is the one place a knob's vocabulary
    lives."""

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


def settings_of(options):
    """The Setting rows derived from the registry: every option with a
    `live` name — a live-settable knob or a control-only setting — in
    registry order; a repeated live name (two knobs steering one setting)
    keeps the first row's vocabulary."""
    seen = set()
    out = []
    for o in options:
        if not o.live or o.live in seen:
            continue
        seen.add(o.live)
        out.append(Setting(o.live, o.setting_help or o.help, o.values, o.hint, o.value_help))
    return tuple(out)


def make_describe(by_name):
    """The describe pair bound to one tool's SETTING_BY_NAME: describe_setting
    (the `help set <name>` answer) and describe_value (the per-value note the
    console clients' word-help shows — case-insensitive: DEBUG/debug, ON/on,
    ...)."""
    def describe_setting(name):
        s = by_name[name]
        return '%s - %s (values: %s)' % (s.name, s.help, s.value_shape)

    def describe_value(name, value):
        s = by_name.get(name)
        if not s:
            return ''
        v = s.value_help
        for cand in (value, value.lower(), value.upper(), value.capitalize()):
            if cand in v:
                return v[cand]
        return ''
    return describe_setting, describe_value
