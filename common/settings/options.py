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
  `clear` verbs, the console completions and the word-help speak, derived
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
import json
import os

from common.settings.dump import SECRET_REMOVED
from common.render.texts import T


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
                 min=None, max=None, check=None, node=False, hidden=False, no_env=None):
        self.name = name
        self.flag = flag
        self.env = env
        self.no_env = no_env      # the ruled-env-free note: why a flag row carries no env twin
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
    common/render/manpage.py). Boolean flags become store_true (a `negates` row
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
        elif line.startswith('clear '):
            raise ValueError('%s:%d: clear is a control-session verb, not a config verb: %r'
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


def render_word_sections(sections):
    """The listing render — the console's ? output and the wire's node help
    (describe_node) share the one shape: the ungrouped words on top (no
    header), then every labeled section under a blank line and its
    `  [label]` header, the descriptions in one column across all the
    sections (`    word  text`; an undescribed word rides bare)."""
    width = max((len(w) for _, ws in sections for w, d in ws if d), default=0)
    rows = []
    for label, ws in sections:
        if not ws:
            continue
        if label:
            rows.append('')
            rows.append('  [%s]' % label)
        rows.extend(('    %-*s %s' % (width, w, d)) if d else ('    %s' % w) for w, d in ws)
    return rows


def _listing(name, options, node=None, hidden_words=()):
    """The walk listing describe_node and describe_root share — the
    console's ? render of one position: the next words under `name`'s
    prefix (the root when empty) one per row, the node-first
    descriptions, the display groups' sections (the ungrouped on top,
    soft-alphabetical within), the hidden rows never listing (the pools'
    rule; `hidden_words` hides more — the runtime-gated words). A node
    whose every child is hidden falls back to its own `name - help` line;
    the root never falls back."""
    prefix = name + '/' if name else ''
    nodes = {o.name: o for o in options if o.node}
    by_live = {}
    for o in options:
        if o.live and o.live not in by_live:
            by_live[o.live] = o
    words = {}
    for o in options:
        if o.hidden:
            continue   # the pools' rule: the hidden rows never list (the typed path still answers)
        spellings = [(o.live, False)]
        if o.alias:
            spellings.append((o.alias, True))
        for spelling, by_alias in spellings:
            if spelling and spelling.startswith(prefix):
                word = spelling[len(prefix):].split('/')[0]
                if word and word not in hidden_words:
                    words.setdefault(word, (o, by_alias))
    if not words:
        return ('%s - %s' % (name, node.setting_help or node.help)) if node is not None else None
    buckets = {}
    for word, (o, by_alias) in words.items():   # registry order = the sections' first-appearance order
        child = nodes.get(prefix + word)
        row = by_live.get(prefix + word)
        if child is not None:   # a namespace child: the word walks on, the node row describes
            text, via, group = child.setting_help or child.help, None, child.group
        elif row is not None:   # a setting at the path describes the word (the console's rule)
            text, via, group = row.setting_help or row.help, None, row.group
        else:                   # a walk-on: the contributing row describes (the lint keeps nodes on every prefix)
            text = o.setting_help or o.help
            via, group = (o.live if by_alias else None), o.group
        buckets.setdefault(group or '', []).append(
            (word, '%s%s' % (text, (' (the alias of %s)' % via) if via else '')))
    bare = buckets.pop('', None)
    sections = ([('', sorted(bare, key=lambda p: p[0].lower()))] if bare else []) \
        + [(label, sorted(ws, key=lambda p: p[0].lower())) for label, ws in buckets.items()]
    return '\n'.join(render_word_sections(sections))


def describe_node(options, name):
    """The hierarchy node's wire help (`show audit`, `show audit rotate`;
    also `help audit`): the node's own children as the console's ?
    listing renders them — the golden master, byte for byte (the walk
    carries the depth: `show audit rotate` names the rotation namespace
    and its own listing answers past it). The alias rows list marked with
    the canonical name (one knob, two spellings). None when the name is
    no node."""
    node = next((o for o in options if o.node and o.name == name), None)
    if node is None:
        return None
    return _listing(name, options, node)


def describe_command_node(commands, help_map, groups, hidden, name):
    """The command namespace's wire help (`help request`, `help request
    clear`): the next command words under the prefix, as the console's ?
    renders the setting namespaces — the node-first descriptions (a word
    that is itself a namespace describes by its node row, whose help and
    group COMMAND_HELP/COMMAND_GROUPS carry beside the commands), the
    display groups' sections, the hidden rows never listing (the pools'
    rule; the typed path still answers). None when nothing lists (the
    name is no command node)."""
    prefix = name + '/'
    words = {}
    for w in commands:
        if w in hidden:
            continue   # the pools' rule: the hidden rows never list (the typed path still answers)
        if w.startswith(prefix):
            word = w[len(prefix):].split('/')[0]
            if word and word not in words:
                words[word] = help_map.get(prefix + word, '')
    if not words:
        return None
    buckets = {}
    for word, text in words.items():   # registry order = the sections' first-appearance order
        buckets.setdefault(groups.get(prefix + word, ''), []).append((word, text))
    bare = buckets.pop('', None)
    sections = ([('', sorted(bare, key=lambda p: p[0].lower()))] if bare else []) \
        + [(label, sorted(ws, key=lambda p: p[0].lower())) for label, ws in buckets.items()]
    return '\n'.join(render_word_sections(sections))


def describe_root(options, show_options=(), hidden_words=()):
    """The bare `show` answer — the walk's first position as the console's
    ? renders it: every visible top-level word (the namespaces, the
    knobs, the show reports) one per row, the node-first descriptions,
    the sectioned render. `show_options` rides the same space (the show
    reports are rows of it); `hidden_words` carries the runtime-gated
    words — the dump-gated `dump-interval` lists only while the dump node
    is on, and the caller knows."""
    return _listing('', tuple(options) + tuple(show_options), None, hidden_words)


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


def config_value(name, cfg, by_name, cfg_keys=None, formatters=None):
    """The set-grammar form of one option's effective startup value (the
    resolved config dict), or None when it should not render: secrets never
    render inline (the file/flag/env form is the documented way — `show
    config` output must be safe to paste), empty values drop (the defaults
    apply on re-run), bools render true/false. `cfg_keys` carries the
    per-tool knob -> cfg-key renames, `formatters` the cfg key -> text
    map for the structured values (the ACLs, the register map) — the
    tool's registry wiring passes both; this is modbus-cache's chain made
    family-wide (the golden show_config)."""
    opt = by_name[name]
    key = (cfg_keys or {}).get(name, name.replace('-', '_'))
    v = cfg.get(key)
    if opt.secret:
        return None
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 'true' if v else 'false'
    f = (formatters or {}).get(key)
    if f is not None:
        return f(v)
    return str(v)


def control_command(opt):
    """The knob -> control-command mapper: the command that changes this knob
    on a running daemon (`set interval 10`; a live path spells as its words:
    `set inverter profile <value>`; an aliased row names its second spelling
    too), or the note that the knob is startup-only (restart to apply). A
    knob the registry marks restart carries ', restart' on its recipe — the
    set records the value, the restart applies it. A restart-marked SECRET
    renders no recipe at all: the wire refuses set/clear on it (a secret can
    never ride the reload state, so it has no pending form) — it passes by
    flag/env/config and a restart."""
    if opt.live:
        if opt.restart and opt.secret:
            return 'startup-only — pass it by flag/env/config (set/clear refuse)'
        cmd = 'set %s <value>' % opt.live.replace('/', ' ')
        if opt.alias:
            cmd += ' (alias: %s)' % opt.alias.replace('/', ' ')
        if opt.restart:
            cmd += ', restart'
        return cmd
    return T('wire.restart_required')


def knob_dictionary(options, who='the tool'):
    """The dictionary of all knobs (`show knobs`): every option of the
    registry under its display group (the row's `group`, ungrouped and
    headerless when none), one row per knob with every surface — the
    config/set-grammar name, the argparse flag (control-only settings show
    the set command in their flag's place), the env twin(s), the control
    command that changes it (or the restart note, or the startup-only
    secret note) and the secret marker.
    Registry data only — no values render here (`show config` is the
    values view), so secrets are named, never shown."""
    lines = [T('wire.knobs_header') % who]
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


def as_bool(v):
    """The registry row's bool field (secret/internal/hidden/restart/node):
    the JSON booleans plus the wire's on/off spelling — 'on' is true,
    'off' is false, absent is false; anything else fails loud (the
    registries are lint-gated, a typo must never load as a truthy
    string)."""
    if v is None or v is False:
        return False
    if v is True:
        return True
    if v == 'on':
        return True
    if v == 'off':
        return False
    raise ValueError('a bool field is true/false (or on/off), got %r' % (v,))


_CONV = {'str': str, 'int': int, 'float': float, 'bool': bool}


def load_registry(here, choices=None, static_defaults=None):
    """The one registry load the four lib/options.py share: options.json
    next to the loader — the rows through option_rows (the static defaults
    and the choices wired per tool), the `show`/`commands` sections through
    parse_registry_sections (the caller folds them into its globals).
    Returns (rows, sections, options); the module imports flat (the loaders
    walk lib/ on sys.path — scripts/check_options.py)."""
    with open(os.path.join(here, 'options.json'), encoding='utf-8') as f:
        meta = json.load(f)
    return meta['options'], parse_registry_sections(meta), \
        option_rows(meta['options'], static_defaults=static_defaults, choices=choices or {})


CONSOLE_VERBS = frozenset(('exit', 'logout'))
"""The console's local spellings of quit — common/wire/cli.py closes the
session before the wire sees them, so the RBAC vocabulary (the verbs the
SERVER can decide on) excludes them; the registry rows document them for
the ? listing only."""


def known_verbs(commands):
    """The RBAC vocabulary, derived from the registry's command rows — the
    one home (the drift doc's "derived, not hand-maintained" item): a row's
    `live` path names its verb as the first segment past a leading
    `request` (command_verb's rule: `request/clear/cache` decides on
    `clear`), a row without one IS the verb (`set`, `poll`, the fake's
    `reset`). The node rows never join (parse_registry_sections skips
    them — a namespace is grammar, not authority); the hidden/internal
    rows count (the display flags do not gate the vocabulary); the
    console-eaten verbs ride out (CONSOLE_VERBS — the wire never decides
    on them). Sorted tuple, stable across the surfaces that render it."""
    verbs = set()
    for w in commands:
        segs = w.split('/')
        if segs[0] == 'request':
            segs = segs[1:]
        if segs and segs[0] not in CONSOLE_VERBS:
            verbs.add(segs[0])
    return tuple(sorted(verbs))


def default_ops_verbs(verbs):
    """The read-only shift's default policy, derived from the same rows:
    `show` everywhere, `flush` only where the grammar actually speaks it
    (the cache's cache-drop; the old family-wide `show,clear` accepted a
    verb three tools' wires refuse — the policy the registry could not
    back)."""
    return 'show,flush' if 'flush' in verbs else 'show'


def parse_registry_sections(meta):
    """The registry's `show` and `commands` sections -> the control-grammar
    vocabulary, one parse for the family's four loaders (the rows live in
    each lib/options.json; the shape is the family's — the loaders assign
    their globals from the returned dict). The show commands expand into
    the live-path space: the row's own `live` when it spells the hierarchy,
    else the word itself. The control commands key by the wire word (the
    row's `live`, else the name — the name is the registry key, never
    typed). A `node` row's descr carries the namespace's word-help (the
    walk-on borrows it; it is no command word itself). An `internal` row
    is the machinery's own word — the wire answers, the cli never offers
    or lists it."""
    show_rows = meta.get('show') or []
    show_commands = tuple((r['name'], r.get('setting-help') or r.get('help', ''), as_bool(r.get('hidden')),
                           r.get('group'))
                          for r in show_rows)
    show_options = tuple(Option(r['name'], None, None,
                                help=r.get('setting-help') or r.get('help', ''),
                                live=r.get('live') or r['name'],
                                group=r.get('group'),
                                setting_help=r.get('setting-help'),
                                hidden=as_bool(r.get('hidden')))
                         for r in show_rows)
    commands, cmd_help, cmd_groups, cmd_hidden = [], {}, {}, set()
    cmd_internal = set()
    for r in meta.get('commands') or []:
        w = r.get('live') or r['name']
        if as_bool(r.get('node')):   # a tree row: its descr carries the namespace's word-help
            cmd_help[w] = r.get('help', '')   # (the walk-on borrows it); it is no command word itself
            cmd_groups[w] = r.get('group', '')   # the namespace word's group in the wire's node listing
            continue
        commands.append(w)
        cmd_help[w] = r.get('help', '')
        cmd_groups[w] = r.get('group', '')
        if as_bool(r.get('hidden')):
            cmd_hidden.add(w)
        if as_bool(r.get('internal')):
            cmd_internal.add(w)
    return {
        'SHOW_COMMANDS': show_commands,
        'SHOW_WORDS': tuple(w for w, _, _, _ in show_commands),
        'SHOW_HIDDEN': frozenset(w for w, _, hid, _ in show_commands if hid),
        'SHOW_VALUES': tuple((w, d) for w, d, _, _ in show_commands),
        'SHOW_GROUPS': {w: g for w, _, _, g in show_commands},
        'SHOW_OPTIONS': show_options,
        'SHOW_BY_LIVE': {o.live: o.name for o in show_options},   # the hierarchy live -> the report's word
        'COMMANDS': tuple(commands),
        'COMMAND_HELP': cmd_help,
        'COMMAND_GROUPS': cmd_groups,
        'COMMAND_HIDDEN': frozenset(cmd_hidden),
        'COMMAND_INTERNAL': frozenset(cmd_internal),
    }


def option_rows(rows, static_defaults=None, choices=None):
    """The registry's option rows -> the common Option tuples. The default
    ladder: the static.json-wired default wins, then the row's explicit
    `default`, then the bool native (False) — a negates row (the --no-x
    form) stays None so the negating flag defaults off. `choices` is the
    tool's name -> word-tuple map from static.json; the log-level's word
    list doubles as the control grammar's completable values (the values
    ride the choices)."""
    static_defaults = static_defaults or {}
    choices = choices or {}
    out = []
    for row in rows:
        opt = Option(row['name'], row.get('flag'), row.get('env'),
                     help=row.get('help', ''), conv=_CONV[row.get('conv', 'str')],
                     live=row.get('live'), alias=row.get('alias'),
                     secret=as_bool(row.get('secret')),
                     group=row.get('group'),
                     negates=row.get('negates'),
                     setting_help=row.get('setting-help'), values=row.get('values'),
                     hint=row.get('hint'), value_help=row.get('value-help'),
                     min=row.get('min'), max=row.get('max'), check=row.get('check'), hidden=as_bool(row.get('hidden')),
                     restart=as_bool(row.get('restart')), no_env=row.get('no-env'),
                     node=as_bool(row.get('node')))
        if opt.name in static_defaults:
            opt.default = static_defaults[opt.name]
        elif 'default' in row:
            opt.default = row['default']
        elif opt.conv is bool and not opt.negates:
            opt.default = False
        if opt.name in choices:
            opt.choices = choices[opt.name]
            if opt.name == 'log-level':
                opt.values = opt.choices   # the control grammar's completable words
        out.append(opt)
    return tuple(out)


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
        self.restart = restart            # startup-only: set/clear answers the restart note
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
    its set/clear attempt with the restart note) joins under its live
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
    """The live setting a set/clear/show/help word list names: a `live` path
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
    """The completion pool for a set/clear/show word list: the Setting the
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
    words on the wire (`request/flush/cache` is `request flush cache`),
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
