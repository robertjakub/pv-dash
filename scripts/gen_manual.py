#!/usr/bin/env python3
"""Render <tool>/MANUAL.md — one page per daemon: every command, knob and
show report its control wire answers, the kind of each (command, settable
— set/clear — or show-only), the flag and the env twin, the value shape
and the description — from the per-tool registries (lib/options.json via
lib/options.py, the one-knob-one-source rows). The files are GENERATED:
edit the registry and re-run, never the markdown.

  python3 scripts/gen_manual.py          # render the four pages
  python3 scripts/gen_manual.py --check  # exit 1 when a shipped page drifts

Stdlib only."""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

# the daemons in the chain order the README tells: fake -> cache -> scraper,
# then the dashboard that renders the numbers — the tool dir, the daemon
# name, the bin whose --man carries the startup surface, the one-line
# blurb, the ctl/cli bins, the default control socket, the ctl example
# (port + command, the bins' docstrings' own), whether TCP control refuses
# to start without a token (F5; the fake is the F11 exempt) and the
# bundled config script (the bundled sample's checkout path, examples/)
TOOLS = (
    ('cache', 'modbus-cache', 'modbus-cache',
     'A dependency-free (Python stdlib only) Modbus TCP caching proxy for '
     'single-client devices: it polls the inverter once and serves every '
     'client from the cache.',
     'modbus-cache-ctl', 'modbus-cache-cli', '/tmp/modbus-cache-15502.socket',
     '15509', 'request flush cache', True, 'cache/examples/modbus_cache.conf'),
    ('scraper', 'modbus-scraper', 'modbus-scraper',
     'A dependency-free (Python stdlib only) Prometheus exporter that polls '
     'a Modbus device and exposes the metrics at /metrics.',
     'modbus-scraper-ctl', 'modbus-scraper-cli', '/tmp/modbus-scraper-9350.socket',
     '15509', 'poll now', True, 'scraper/examples/scraper.conf'),
    ('inverter', 'fake-inverter', 'modbus-fake-inverter',
     'A dependency-free (Python stdlib only) Modbus TCP server that plays '
     'an inverter — the battery, the smart meter, the diagnostics — for '
     'the family to develop and test against.',
     'modbus-fake-ctl', 'modbus-fake-cli', '/tmp/fake-inverter-5502.socket',
     '15599', 'show registers', False, 'inverter/examples/inverter.conf'),
    ('dashboard', 'dashboard', 'dashboard',
     'A single-page dashboard for home PV monitoring, fed by Prometheus: '
     'it serves the page and proxies the upstream queries.',
     'dashboard-ctl', 'dashboard-cli', '/tmp/dashboard-8080.socket',
     '15598', 'request reload-config', True, 'dashboard/examples/server.conf'),
)

# the wire words no registry row carries (the registries' own audit's
# finding): the fake's Modbus write emulation — a `set` form that plants a
# value in the write overlay instead of steering a knob
EXTRA_COMMANDS = {
    'inverter': (
        ('set register <addr> <value>',
         'the Modbus write emulation: plant a register value in the write '
         'overlay — reads answer it, reset clears it'),
        ('set coil <addr> <0|1>',
         'the write emulation: plant a coil value (the coil space, '
         'FC1/FC5/FC15 see it, reset clears it)'),
        ('set discrete <addr> <0|1>',
         'the write emulation: plant a discrete-input value (the discrete '
         'space, FC2 sees it, reset clears it)'),
    ),
}

WIDTH = 76


def load(tool_dir):
    """The tool's wired rows (gen_options.py's import dance: one module
    named `options` at a time) plus the raw registry (the commands/show
    sections' row order and flags — the loader keys them by live word and
    drops the node rows, the page wants both)."""
    sys.path.insert(0, os.path.join(REPO, tool_dir, 'lib'))
    sys.modules.pop('options', None)
    mod = __import__('options')
    sys.path.pop(0)
    with open(os.path.join(REPO, tool_dir, 'lib', 'options.json'), encoding='utf-8') as f:
        meta = json.load(f)
    rows, shows = tuple(mod.OPTIONS), tuple(mod.SHOW_OPTIONS)
    sys.modules.pop('options', None)
    return rows, shows, meta


def wrap(text):
    """Greedy wrap at WIDTH — the prose paragraphs; the tables never wrap
    (one row per line)."""
    words, lines, line = text.split(), [], ''
    for w in words:
        if line and len(line) + 1 + len(w) > WIDTH:
            lines.append(line)
            line = w
        else:
            line = (line + ' ' + w) if line else w
    if line:
        lines.append(line)
    return '\n'.join(lines)


def bullet(text):
    """A wrapped list item: `- ` on the first line, the continuation lines
    at the two-space content indent cmark gives a `- ` bullet."""
    lines = wrap(text).split('\n')
    return '- ' + lines[0] + ('' if len(lines) == 1 else
                              '\n' + '\n'.join('  ' + l for l in lines[1:]))


def esc(text):
    """One table cell: a bare `<` outside a code span would parse as HTML
    and swallow the word (`<file>`) — backslash-escape it (no code-span
    imbalance: the registry text stays verbatim); the pipes escaped last
    (GFM's rule — a `|` ends the cell even inside backticks)."""
    import re
    parts = text.split('`')
    for i, part in enumerate(parts):
        if i % 2 == 0:
            parts[i] = part.replace('<', '\\<')
    return '`'.join(parts).replace('|', '\\|')


def shape(opt):
    """The value-shape cell: the row's hint, else its completable words,
    else the conv's plain shape."""
    if opt.hint:
        return opt.hint
    if opt.values:
        return '|'.join(opt.values)
    return {'bool': 'on|off', 'int': 'N', 'float': 'N'}.get(opt.conv, 'TEXT')


def knob_kind(opt):
    """The kind cell of a knob row: settable (the restart and the secret
    markers) or startup-only (the secret dump-key refuses outright — its
    set/clear/show all answer the restart error)."""
    if not opt.live:
        kind = 'startup-only'
        if opt.secret:
            kind += ' (secret)'
        return kind
    if opt.restart:
        kind = 'settable (restart)'
        if opt.secret:
            kind = 'startup-only (secret)'
        return kind
    kind = 'settable'
    if opt.secret:
        kind += ' (secret)'
    return kind


def knob_row(opt):
    """One knob table row: the registry key, the wire spelling a running
    daemon takes (the set/clear/show words; the alias beside it), the
    kind, the value shape, the flag / env twins and the description (the
    setting-help — the wire's own wording)."""
    set_cell = '—'
    kind = knob_kind(opt)
    if opt.live and not kind.startswith('startup-only'):
        words = ' '.join(opt.live.split('/'))
        set_cell = '`set %s`' % words
        if opt.alias:
            set_cell += ' (alias: `set %s`)' % ' '.join(opt.alias.split('/'))
    flag = '`%s`' % opt.flag if opt.flag else '—'
    envs = '/'.join('`%s`' % e for e in opt.env_names() if e) or '—'
    desc = opt.setting_help or opt.help
    marks = ''
    if opt.hidden:
        marks = ' *(hidden)*'
    return '| `%s` | %s | %s | `%s` | %s / %s | %s%s |' % (
        esc(opt.name), esc(set_cell), esc(kind), esc(shape(opt)),
        flag, envs, esc(desc), marks)


def knobs_section(rows):
    """The knobs tables: the flat knobs first (no namespace — the general
    bucket), then one table per namespace node in registry first-appearance
    order, the rows in registry order (the file order every surface
    renders). A knob belongs to the longest node naming its live path's
    prefix; a startup-only knob (no live path) always rides the general
    bucket."""
    nodes = [o for o in rows if o.node]
    buckets = {'': []}
    for o in rows:
        if o.node:
            continue
        best = ''
        for n in nodes:
            if o.live and (o.live == n.name or o.live.startswith(n.name + '/')) \
                    and len(n.name) > len(best):
                best = n.name
        buckets.setdefault(best, []).append(o)
    out = ['## Knobs', '',
           wrap('The tables spell the knob\'s registry key (the config-file '
                'name and the dump\'s key); the set / clear column spells the '
                'wire words a running daemon takes. The namespaces group '
                'them.'), '']
    order = [''] + [n.name for n in nodes if n.name in buckets]
    by_name = {n.name: n for n in nodes}
    for i, key in enumerate(order):
        if not buckets.get(key):
            continue
        if i:
            out.append('')
        if key:
            node = by_name[key]
            out.append('### %s' % key)
            out.append('')
            out.append(wrap(node.setting_help or node.help or ''))
            out.append('')
        else:
            out.append('### general')
            out.append('')
        out.append('| knob | set / clear | kind | value | flag / env | description |')
        out.append('|---|---|---|---|---|---|')
        out.extend(knob_row(o) for o in buckets[key])
    return out


def commands_section(meta, tool):
    """The commands table: the registry's rows in file order (the nodes
    render as namespace rows at their position), the fake's rowless write
    emulation appended. Rows spelling the same wire words merge into one
    (the cache's `request dump`: the namespace node and the hidden leaf
    command) — the kinds joined, the namespace's fuller description kept."""
    rows = []
    for r in meta.get('commands') or []:
        wire = (r.get('live') or r['name']).replace('/', ' ')
        node = (r.get('node') == True or r.get('node') == 'on')
        internal = (r.get('internal') == True or r.get('internal') == 'on')
        hidden = (r.get('hidden') == True or r.get('hidden') == 'on')
        rows.append((wire, node, internal, hidden, r.get('help', '')))
    merged = []
    for wire, node, internal, hidden, help in rows:
        for i, (m_wire, m_node, m_int, m_hid, m_help) in enumerate(merged):
            if m_wire == wire:
                marks = [m for m, on in (('internal', m_int or internal),
                                         ('hidden', m_hid or hidden)) if on]
                kind = ('namespace' if m_node or node else 'command')
                if m_node and not node:
                    kind = 'namespace + command'
                if marks:
                    kind += ' (%s)' % ', '.join(marks)
                merged[i] = (m_wire, m_node or node, m_int or internal,
                             m_hid or hidden,
                             m_help if (m_node or not node) else help)
                break
        else:
            merged.append((wire, node, internal, hidden, help))
    out = ['## Commands', '',
           '| command | kind | description |', '|---|---|---|']
    for wire, node, internal, hidden, help in merged:
        marks = [m for m, on in (('internal', internal), ('hidden', hidden)) if on]
        kind = 'namespace' if node else 'command'
        if marks:
            kind += ' (%s)' % ', '.join(marks)
        out.append('| `%s` | %s | %s |' % (esc(wire), esc(kind), esc(help)))
    for wire, desc in EXTRA_COMMANDS.get(tool, ()):
        out.append('| `%s` | command | %s |' % (esc(wire), esc(desc)))
    return out


def show_section(shows):
    """The show reports table: the registry's `show` rows — the wire
    spelling is the live path's words (the flat name when the row spells
    no hierarchy)."""
    out = ['## Show reports', '',
           '| report | kind | description |', '|---|---|---|']
    for o in shows:
        wire = ' '.join(o.live.split('/'))
        kind = 'show-only' + (' (hidden)' if o.hidden else '')
        out.append('| `show %s` | %s | %s |' % (esc(wire), esc(kind), esc(o.setting_help or o.help)))
    return out


def render(tool, daemon, daemon_bin, blurb, ctl, cli, sock, port, example,
           token_mandatory, conf, rows, shows, meta):
    """The page: the speaking-to-the-daemon intro (the clients, the token
    rules, the kinds legend), then the three tables — commands, knobs,
    show reports."""
    out = []
    w = out.append
    w('# The %s manual (MANUAL.md)' % daemon)
    w('')
    w(wrap('%s Part of the pv-suite family. The daemon\'s own `--help` and '
           'the man page (`%s --man`) carry the startup surface; this page '
           'carries the control wire. **Generated** from `lib/options.json` '
           '(the one-knob-one-source rows) by `scripts/gen_manual.py` — '
           'edit the registry and re-run, never this file.' % (blurb, daemon_bin)))
    w('')
    w('## Speaking to the daemon')
    w('')
    if token_mandatory:
        token = wrap('TCP control demands the token (`--control-token` / env '
                     '`CONTROL_TOKEN`; the wire\'s `auth` verb carries it) and '
                     'refuses to start without one; over the unix socket a '
                     'trusted peer (root, the daemon\'s own user or '
                     '`--control-trust-uids` — SO_PEERCRED) speaks without it.')
    else:
        token = wrap('The fake keeps its trusted-LAN posture (F11): control '
                     'works over TCP without a token too; over the unix socket '
                     'a trusted peer (root, the daemon\'s own user or '
                     '`--control-trust-uids` — SO_PEERCRED) always speaks '
                     'without one.')
    w(wrap('The control server is a JSON-lines listener: a unix socket (the '
           'default `%s`) or a TCP port on 127.0.0.1 — the `--control-port` '
           'flag, env `CTL`, `0` = off. Two clients speak it:' % sock))
    w('')
    w('    python3 bin/%s.py --control-port %s %s' % (ctl, port, example))
    w('    python3 bin/%s.py' % cli)
    w('')
    w(bullet('the **ctl** runs one command per invocation (or a batch on '
             'stdin);'))
    w(bullet('the **cli** is the interactive console: `?` lists the words, '
             'TAB completes, `help <setting>` describes one, `help config` '
             'maps every knob to its control command, `show knobs` prints '
             'the dictionary.'))
    w('')
    w(token)
    w('')
    w(wrap('The optional ops token (`--control-ops-token`) scopes a session '
           'to the read-only verbs (the default: show and clear). Every '
           'command is audited. The clients take `--control-port` (env '
           '`CTL`), `--timeout`, `--control-token`, the audit flags and '
           '`--man`; the cli adds `--reconnect` / `--reconnect-wait`.'))
    w('')
    if conf:
        w(wrap('A knob\'s value resolves at start as flag > env > config '
               'script > default; the config file (the bundled `%s`) speaks '
               'the same grammar — `set <name> <value>` lines in the '
               'registry\'s flat keys, `--dry-run` prints the effective '
               'settings. No defaults live in these tables: `show config` '
               'prints the effective values, the READMEs are the '
               'reference.' % conf))
    w('')
    w('The kinds — every row of the tables below carries one:')
    w('')
    w(bullet('**command** — a one-shot action, no value.'))
    w(bullet('**namespace** — a word that groups deeper words: the console '
             'walk lists its children, `help <namespace>` describes them.'))
    w(bullet('**settable** — the knob is live: `set <words> <value>` applies '
             'at once, `clear <words>` returns the configured value, '
             '`show <words>` prints the live value. *(restart)* — the set '
             'records a pending value and `request reload` applies it. '
             '*(secret)* — the value never renders back (show answers '
             'err); pass it by flag/env or as `file:<path>`. *(hidden)* — '
             'never lists in the ?/TAB pools; the wire still answers.'))
    w(bullet('**startup-only** — flag/env/config at start, a restart applies '
             'a change; the wire has no set/clear/show for it (it renders '
             'in `show config` only). Every secret is startup-only now (the '
             'tokens, the auth keys, the dump key): the wire refuses '
             'set/clear outright, the value passes by flag/env/config or as '
             '`file:<path>` and a restart applies it.'))
    w(bullet('**show-only** — a runtime report: `show <report>` answers, '
             'nothing to set.'))
    w('')
    if any(o.live == 'write/registers' for o in rows) \
            and any(o.live == 'write/registers/table' for o in shows):
        # the set/show spelling collision (the cache's pair): the legend note
        w(wrap('A show report\'s path never shadows a knob value: one '
               'spelling per side of the verb — `set write registers '
               'profile` feeds the write-registers knob the word `profile`, '
               '`show write registers profile` answers the report.'))
        w('')
    out.extend(commands_section(meta, tool))
    w('')
    out.extend(knobs_section(rows))
    w('')
    out.extend(show_section(shows))
    w('')
    w(wrap('The ?/TAB pools, `show knobs` and `help config` all render from '
           'the same rows this page was generated from.'))
    w('')
    return '\n'.join(out) + '\n'


def raw_angle_guard(text, path):
    """The cmark guard: a `<` outside a code span parses as HTML and
    vanishes (`<file>`). Fail loud — esc() escapes them, so a hit means a
    shape the escaper missed."""
    import re
    for no, line in enumerate(text.splitlines(), 1):
        for i, part in enumerate(line.split('`')):
            if i % 2 == 0 and re.search(r'(?<!\\)<', part):
                raise SystemExit('%s:%d: a raw < outside a code span: %r' % (path, no, part.strip()))


def main(argv):
    check = '--check' in argv
    drift = []
    for tool, daemon, daemon_bin, blurb, ctl, cli, sock, port, example, token_mandatory, conf in TOOLS:
        rows, shows, meta = load(tool)
        page = render(tool, daemon, daemon_bin, blurb, ctl, cli, sock, port,
                      example, token_mandatory, conf, rows, shows, meta)
        raw_angle_guard(page, daemon)
        path = os.path.join(REPO, tool, 'MANUAL.md')
        if check:
            with open(path, encoding='utf-8') as f:
                if f.read() != page:
                    drift.append(path)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(page)
            print('wrote %s' % path)
    if check:
        if drift:
            print('drift: %s' % ', '.join(drift))
            return 1
        print('manual pages up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
