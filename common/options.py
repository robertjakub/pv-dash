#!/usr/bin/env python3
"""The family's option registry — one knob, one source (docs/TODO.md).

Every knob of every tool lives here ONCE as an `Option`: its registry name
(the set-grammar config key and the ini-era key, dashes included), the
argparse flag, the environment twin, its optional **group** (the display
bucket the surfaces file it under), its help text, its converter and its
default. From this one row the surfaces are built or checked:

- the **configuration file** — the set grammar the control servers already
  speak (`parse_config_script` / `render_config_script`): a config file is a
  runnable script, every line a `set <name> <value>`, every comment a `#`
  comment (the ini format is gone — the breaking wave);
- `show knobs` — the **dictionary of all knobs**: every option under its
  group with its flag, its env twin, the control command that changes it
  (or the restart note) and the secret marker (`knob_dictionary` below —
  registry data only, no values render);
- the **control grammar's live settings** — the `Setting` rows the `set`/
  `unset` verbs, the console completions and the word-help speak, derived
  from the same rows (`settings_of`/`make_describe`: a row's `live` name —
  a `/`-path, `inverter/profile` — its `setting_help`, its completable
  `values`, the value-shape `hint` and the per-value `value_help`; a
  flagless row is a control-only setting — the fake's pins and machines;
  the path spells as its words on the wire: `set inverter profile <value>`,
  however deep — `a/b/c` → `set a b c <value>`);
- `scripts/check_options.py` — the CI gate that the four surfaces (the
  flags, the env names, the bundled config, the NixOS module and the README
  tables) agree with the registry.

Groups are free words each registry files its knobs under; a row without
one renders ungrouped — bare, no header. Stdlib only."""
import argparse
import os

from common.dump import SECRET_REMOVED


class Option:
    """One knob: `name` (the config/set-grammar key), `flag` ('--interval';
    None on a control-only setting — a live `set` name with no flag), `env`
    (the twin — a str or a tuple of fallbacks), `group` (the optional
    display bucket the surfaces file the row under — ungrouped when None),
    `help` (the shared help
    text --help and the docs render it), `conv` (the value
    shape: str/int/float/bool — bool flags are store_true, int/float type
    the argparse value), `default` (the argparse default — None = unset, the
    resolution layers decide), `live` (the control `set` name when the knob
    is live-settable — a '/'-path whose segments spell as words on the wire:
    `inverter/profile` is `set inverter profile <value>`), `secret` (a
    token: rendered into a config file only in its -file form), `choices`
    (the values the parser accepts) and `negates` (the name of the boolean
    knob this row switches off — the --no-x form of an --x flag). A
    control-only setting (the fake's pins and machines) carries the live
    name and no flag/env; its `setting_help`, `values`, `hint` and
    `value_help` are the control grammar's vocabulary (the short
    description, the completable words, the value shape and the per-value
    notes)."""

    def __init__(self, name, flag, env, help='', conv=str, default=None, live=None,
                 secret=False, choices=None, negates=None, group=None, alias=None, restart=False,
                 setting_help=None, values=None, hint=None, value_help=None,
                 min=None, max=None, check=None, node=False, hidden=False):
        self.name = name
        self.flag = flag
        self.env = env
        self.group = group        # the display bucket; None = ungrouped (bare, no header)
        self.alias = alias        # a second wire spelling for the same knob (a '/'-path
                                  # like live: acl/write and writer/acl both answer)
        self.restart = restart    # startup-only: the wire answers the set with the restart note
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
        self.min = min            # the inclusive bounds the live dispatch gates
        self.max = max            # a typed value with (the control path; None = unbounded)
        self.check = check        # the named shape validator (the tool's CHECKS registry;
                                  # None = the conv parse is the whole validation)
        self.node = bool(node)    # a hierarchy node: no flag/env/conv/live — the row
                                  # names a live-path prefix and carries its setting-help
        self.hidden = bool(hidden)   # never lists in the ?/TAB pools (the wire still answers)

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


def _config_word_index(options):
    """The config-line word lookup for the CLI spelling: `set modbus
    upstream <value>` — a live path (or an alias spelling, or the flat
    dashed knob name) spelled as words maps to the row's canonical name.
    The hierarchy nodes ride out (they are not knobs)."""
    index = {}
    for o in options:
        if o.node:
            continue
        if o.live:
            index.setdefault(' '.join(o.live.split('/')), o.name)
            if o.alias:
                index.setdefault(' '.join(o.alias.split('/')), o.name)
        index.setdefault(o.name, o.name)
    return index


def parse_config_script(text, label, options=None):
    """Parse one set-grammar config file: every non-comment line is a
    control command — `set <name> <value>` or the bare `<name> <value>`
    shorthand; `#` comments and blank lines stay comments (a config file
    pipes through a ctl client unchanged). The name speaks the CLI
    spelling — the live path as words (`set modbus upstream <value>`, what
    the console, the help and the knob dictionary all say) — and the flat
    dashed knob name reads too (`set upstream <value>`, the older files'
    form); the canonical name comes back either way. Pass the registry
    (`options`) to get the word matching and the unknown-setting fail
    fast; without it the name is the line's first word, loose as before.
    Returns [(name, value)]. A line the grammar cannot read fails fast
    with the line number (never partial state); the legacy ini shapes
    (`[section]` headers, `key = value` lines) get the pointer to the new
    form — the ini format is gone."""
    index = _config_word_index(options) if options else None
    depth = max((k.count(' ') for k in index), default=0) + 1 if index else 1
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
        if index is not None:
            words = body.split()
            name = value = None
            for n in range(min(depth, len(words)), 0, -1):
                key = ' '.join(words[:n])
                if key in index:
                    name, value = index[key], ' '.join(words[n:]).strip()
                    break
            if name is None:
                raise ValueError(("%s:%d: unknown setting in %r — the config is the control grammar: "
                                  '`set modbus upstream <value>` (or the flat `set upstream <value>`)')
                                 % (label, no, line))
            if not value:
                raise ValueError('%s:%d: a set line needs a name and a value: %r' % (label, no, line))
        else:
            parts = body.split(None, 1)
            if len(parts) != 2:
                raise ValueError('%s:%d: a set line needs a name and a value: %r' % (label, no, line))
            name, value = parts[0], parts[1].strip()
        if '_' in name or value.startswith('='):
            raise ValueError(('%s:%d: the ini format is gone (key = value) — the config is the control grammar: '
                              '`set %s <value>`') % (label, no, name.replace('_', '-')))
        if SECRET_REMOVED in value:
            raise ValueError(('%s:%d: *** SECRET REMOVED *** is not a value — a rendered script hides the '
                              "secret's value; pass the secret by flag/env, or as file:<path>") % (label, no))
        out.append((name, value))
    return out


def grouped_rows(options):
    """The rows bucketed under their display group — the row's `group`,
    ungrouped ('') when it carries none — in registry first-appearance
    order (the order the registries file the rows in — the same order
    --help renders). The one grouping show config, show knobs and help
    config render: a group key renders raw (`# --- key ---`), the bare ''
    bucket renders headerless at the top. The hierarchy nodes ride out
    (they name live-path prefixes, they are not knobs)."""
    buckets = {}
    for o in options:
        if o.node:
            continue
        buckets.setdefault(o.group or '', []).append(o)
    return list(buckets.items())


def describe_node(options, name):
    """The hierarchy node's wire help (`help modbus`): the node row's
    setting-help, then the child settings the node namespaces — one per
    line, the path suffix as the word (the console completes it); a row
    that reaches the node through its `alias` lists too, the line marked
    with the canonical name (one knob, two spellings). None when the name
    is no node."""
    node = next((o for o in options if o.node and o.name == name), None)
    if node is None:
        return None
    lines = ['%s - %s' % (name, node.setting_help or node.help)]
    for o in options:
        if o.live and o.live.startswith(name + '/'):
            lines.append('  %s - %s' % (o.live[len(name) + 1:], o.setting_help or o.help))
        elif o.alias and o.alias.startswith(name + '/'):
            lines.append('  %s - %s (the alias of %s)'
                         % (o.alias[len(name) + 1:], o.setting_help or o.help, o.live))
    return '\n'.join(lines)


def render_config_script(options, values, comment=None):
    """The set-grammar form of the current values, grouped under the
    display-group comments (`# --- group ---`; the ungrouped rows render
    headerless at the top) — `show config` prints this, and the output
    pipes straight back into a config file (or a ctl client). Options whose
    value is None are skipped (unset / off)."""
    header = '# pv-suite configuration — every line is a set command (pipe it back through the ctl client)'
    if comment:
        header += '\n# %s' % comment
    lines = [header, '']
    for key, rows in grouped_rows(options):
        rows_left = []
        for o in rows:
            v = values.get(o.name)
            if v is None or v == '':
                continue
            word = ' '.join(o.live.split('/')) if o.live else o.name   # the CLI spelling — the line pastes onto the wire
            rows_left.append('set %s %s' % (word, v))
        if rows_left:
            if key:
                lines.append('# --- %s ---' % key)
            lines.extend(rows_left)
            lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def control_command(opt):
    """The knob -> control-command mapper: the command that changes this knob
    on a running daemon (`set interval 10`; a live path spells as its words:
    `set inverter profile <value>`; an aliased row names its second spelling
    too), or the note that the knob is startup-only (restart to apply). A
    knob the registry marks restart carries ', restart' on its recipe — the
    set lands in the config, the restart applies it."""
    if opt.live:
        cmd = 'set %s <value>' % opt.live.replace('/', ' ')
        if opt.alias:
            cmd += ' (alias: %s)' % opt.alias.replace('/', ' ')
        if opt.restart:
            cmd += ', restart'
        return cmd
    return 'restart required (startup-only knob)'


def knob_dictionary(options, who='the tool'):
    """The dictionary of all knobs (`show knobs`): every option of the
    registry under its display group (the row's `group`, ungrouped and
    headerless when none), one row per knob with every surface — the
    config/set-grammar name, the argparse flag (control-only settings show
    the set command in their flag's place), the env twin(s), the control
    command that changes it (or the restart note) and the secret marker.
    Registry data only — no values render here (`show config` is the
    values view), so secrets are named, never shown."""
    lines = ['ok knobs — the registry of %s: every knob, its flag, its env twin, '
             'how it changes' % who]
    for key, rows in grouped_rows(options):
        if key:
            lines.append('# --- %s ---' % key)
        for o in rows:
            env = '/'.join('$' + e for e in o.env_names()) if o.env else '-'
            notes = control_command(o)
            if o.secret:
                notes += ', secret'
            lines.append('%-23s %-26s %-30s %s' % (o.name, o.flag or '(control-only)', env, notes))
    return '\n'.join(lines)


class Setting:
    """One live control setting — the registry's control-grammar view: the
    `set <name>` name (a '/'-path: the wire spells its segments as words —
    `inverter/profile` is `set inverter profile <value>`), the short
    description the wire help answers with, the completable value words, the
    value-shape hint (shown after the words), the per-value short
    descriptions and the display group it renders in (the row's `group`,
    ungrouped — bare, no header — when the row carries none; the console
    word-help and the completions group by the `group` field alone).
    Derived from the Option rows (settings_of) — the
    registry is the one place a knob's vocabulary lives."""

    def __init__(self, name, help, values=(), hint=None, value_help=None, group=None, alias=None, restart=False, secret=False):
        self.name = name
        self.help = help
        self.values = values              # completable words
        self.hint = hint                  # the value's shape (N, s, HOST:PORT)
        self.value_help = value_help or {}   # per-value short description
        self.group = group                # the display bucket; None = ungrouped (bare)
        self.alias = alias                # the row's second wire spelling (the canonical renders)
        self.restart = restart            # startup-only: set/unset answers the restart note
        self.secret = secret              # a token: the dump/show-config placeholder rule, the paste-back gate

    @property
    def display_group(self):
        """The bucket the setting renders under: the registry's `group`,
        else '' (ungrouped — bare, no header) — the console listings
        group by the `group` field alone."""
        return self.group or ''

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
    keeps the first row's vocabulary. A `restart` knob (the wire answers
    its set/unset attempt with the restart note) joins under its live
    name, or under its flat name when the row carries none yet."""
    seen = set()
    out = []
    for o in options:
        if o.live:
            if o.live in seen:
                continue
            seen.add(o.live)
            out.append(Setting(o.live, o.setting_help or o.help, o.values, o.hint, o.value_help,
                               o.group, o.alias, restart=o.restart, secret=o.secret))
        elif o.restart:
            out.append(Setting(o.name, o.setting_help or o.help, o.values, o.hint, o.value_help,
                               o.group, restart=True, secret=o.secret))
    return tuple(out)


def setting_groups(names, by_name):
    """The live settings grouped under their display groups (the row's
    `group`, ungrouped — the '' bare bucket, no header — when it carries
    none; the console word-help and the completions group by the `group`
    field alone; the [values] group stays the caller's).
    First-appearance order over the given names, only the non-empty groups;
    a name no Setting answers for belongs to the caller's bare bucket,
    never here."""
    buckets = {}
    for n in names:
        s = by_name.get(n)
        if s is not None:
            buckets.setdefault(s.display_group, []).append(n)
    return list(buckets.items())


def word_groups(words, groups):
    """The command words bucketed under their `group` field (the
    first-appearance order; a word the map misses, or one filed under no
    group, rides the '' bare-top bucket — the console renders bare words
    unheadered, above the filed groups)."""
    buckets = {}
    for w in words:
        buckets.setdefault(groups.get(w, ''), []).append(w)
    return list(buckets.items())


def match_setting_path(words, by_name):
    """The live setting a set/unset/show/help word list names: a `live` path
    (`inverter/profile`) spells as its segments' words on the wire — the
    longest '/'-joined prefix of `words` that `by_name` answers wins, the
    remaining words belong to the value (`set inverter profile <value>`;
    however deep: `a/b/c` → `set a b c <value>`). The map also answers a
    row's `alias` spelling — the return is the CANONICAL live name either
    way (the replies, the dump keys and the defaults render one name).
    Returns (path, rest words); (None, words) when the words name no
    setting."""
    for k in range(len(words), 0, -1):
        cand = '/'.join(words[:k]).lower()
        if cand in by_name:
            return by_name[cand].name, words[k:]
    return None, words


def setting_path_pool(typed, names, by_name):
    """The completion pool for a set/unset/show word list: the Setting the
    words already name (exact — the caller completes its values) or the
    distinct next path segments of `names` under the '/'-joined prefix so
    far (the pool's order kept — `inverter` completes before `profile`).
    A trailing empty word asks for the children of the named path — the
    exact match does not short-circuit (the caller wants the walk-on:
    a word can be both a report and a namespace). Returns (exact,
    segments); exact is None while the path is still partial (a flat
    registry keeps the whole name one segment: the pool itself)."""
    ask_children = bool(typed) and typed[-1] == ''
    words = [w.lower() for w in typed if w]
    path = '/'.join(words)
    if not ask_children and path in by_name:
        return by_name[path], ()
    prefix = path + '/' if path else ''
    segs, seen = [], set()
    for n in names:
        if path and not n.startswith(prefix):
            continue
        seg = n[len(prefix):].split('/')[0]
        if seg not in seen:
            seen.add(seg)
            segs.append(seg)
    return None, tuple(segs)


def command_path_pool(typed, names):
    """The completion pool for a command word list — the settings'
    setting_path_pool's sibling: the command rows are '/'-paths spelled as
    words on the wire (`request/clear/cache` is `request clear cache`),
    and the pool is the distinct next path segment of `names` under the
    '/'-joined prefix so far (the pool's order kept) — the first position
    offers the verbs (`request` completes its children: dump, reload,
    restart, restore, clear), the leaf's own children follow (`request
    clear` offers `cache`), a whole childless command completes nothing.
    A trailing empty word asks for the children of the named path."""
    words = [w.lower() for w in typed if w]
    path = '/'.join(words)
    prefix = path + '/' if path else ''
    segs, seen = [], set()
    for n in names:
        if path and not n.startswith(prefix):
            continue
        seg = n[len(prefix):].split('/')[0]
        if seg and seg not in seen:
            seen.add(seg)
            segs.append(seg)
    return tuple(segs)


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
