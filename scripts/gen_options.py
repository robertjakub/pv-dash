#!/usr/bin/env python3
"""Render OPTIONS.md — the knob comparison table across the four daemons —
from the per-tool option registries (lib/options.json via lib/options.py,
the one-knob-one-source rows). The file is GENERATED: edit the registries
and re-run, never the markdown.

  python3 scripts/gen_options.py

Stdlib only."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

# the daemons, in the chain order the README tells: fake -> cache -> scraper,
# then the dashboard that renders the numbers
TOOLS = (('cache', 'cache'),
         ('scraper', 'scraper'),
         ('inverter', 'inverter'),
         ('dashboard', 'dashboard'))



def load(tool_dir):
    """The tool's wired rows (check_options.py's import dance: one module
    named `options` at a time): the knob Options + the show-command Options
    (the registry's `show` section — the reports the wire answers with)."""
    sys.path.insert(0, os.path.join(REPO, tool_dir, 'lib'))
    sys.modules.pop('options', None)
    mod = __import__('options')
    sys.path.pop(0)
    rows = tuple(mod.OPTIONS)
    shows = tuple(mod.SHOW_OPTIONS)
    sys.modules.pop('options', None)
    return rows, shows


def marks(rows_by_tool, show=False):
    """One cell per tool: ✓ (bold when every tool has the row), plus the
    markers — a knob's live/secret, a show command's hidden."""
    common = all(rows_by_tool.get(t) for t, _ in TOOLS)
    cells = []
    for t, _ in TOOLS:
        opt = rows_by_tool.get(t)
        if not opt:
            cells.append('')
            continue
        if show:
            note = 'hidden' if getattr(opt, 'hidden', False) else ''
        else:
            note = opt.live and 'live' or ''
            if opt.secret:
                note = (note + '+secret') if note else 'secret'
        cells.append(('**✓**' if common else '✓') + (' ' + note if note else ''))
    return cells


def live_cell(rows_by_tool):
    """The live column: the control command the knob answers to on a running
    daemon — `set <flat-name>` (the wire's one spelling = the registry's
    flattened name; the console also completes the row's live/alias path
    spellings and translates them), the tools' names joined when they
    diverge, the `, restart` suffix when every tool holds
    the knob restart-marked (the set records the value, the restart applies
    it). A restart-marked SECRET renders no set recipe — the wire refuses
    set/clear on it (startup-only: pass it by flag/env/config). No live
    name = *(startup-only)*: a restart applies it."""
    names = sorted({opt.name for opt in rows_by_tool.values() if opt.live})
    if not names:
        return '*(startup-only)*'
    lives = [opt for opt in rows_by_tool.values() if opt.live]
    if all(opt.restart for opt in lives) and all(opt.secret for opt in lives):
        return '`startup-only — pass it by flag/env/config (set/clear refuse)`'
    suffix = ', restart' if lives and all(opt.restart for opt in lives) else ''
    return ', '.join('`set %s%s`' % (n, suffix) for n in names)


def group_cell(rows_by_tool):
    """The group column: the row's display bucket (the registry's group
    field — the surfaces file the knob under it; blank = ungrouped, the
    surfaces render it bare), the tools' names joined when they diverge."""
    names = sorted({opt.group for opt in rows_by_tool.values() if opt.group})
    return ', '.join('`%s`' % n for n in names)


def main():
    registries = {key: load(d) for key, d in TOOLS}

    # the merged universes: name -> {tool: opt} — the knobs and the show
    # commands (a show row is a report the wire answers with, never a knob;
    # the name spaces don't collide — the generator would render both rows)
    merged, shown = {}, {}
    for key, _ in TOOLS:
        for opt in registries[key][0]:
            merged.setdefault(opt.name, {})[key] = opt
        for opt in registries[key][1]:
            shown.setdefault(opt.name, {})[key] = opt

    out = ['# The knobs of the family (OPTIONS.md)',
           '',
           'One alphabetical table of every knob and every show command of the',
           'four daemons — the kind,',
           'the name, the group it renders under, and the control command that',
           'changes it (or answers with the report) on a running daemon — with a mark per',
           'tool. **Generated** from the per-tool `lib/options.json` registries (the',
           'one-knob-one-source rows) by `scripts/gen_options.py` — edit the',
           'registries and re-run `python3 scripts/gen_options.py`, never this file.',
           'The resolution order on every tool is flag > env > config script >',
           'default; the env twin is the knob\'s bare upper-snake name (the',
           'exceptions spell their own: `--control-port` -> `CTL`,',
           '`--cache-ttl` -> `TTL`, the dashboard\'s `--upstream` -> `PROM_URL`;',
           '`--config` also honors `$CONFIG`). Every bin also carries the',
           'CLI-only `--config`/`--dry-run`/`--man`',
           '(plus `--version`/`--help`) — flags, not knobs, so they have no rows',
           'here. The ctl/cli clients speak the control plane only',
           '(`--control-port`, the token env) and are not compared.',
           '']
    all_four = sorted(name for name, by_tool in merged.items()
                      if len(by_tool) == len(TOOLS))
    show_four = sorted(name for name, by_tool in shown.items()
                       if len(by_tool) == len(TOOLS))
    out.append('Common to **all four** tools (%d): %s. The control-plane block is'
               % (len(all_four), ', '.join('`%s`' % n for n in all_four)))
    out.append('shared nearly verbatim; the audit, limits and metrics blocks follow the')
    out.append('family shape with per-tool defaults. The show commands %s ride'
               % ', '.join('`%s`' % n for n in show_four))
    out.append('on all four too (the per-tool extras carry their own rows below).')
    out.append('')
    cols = ['kind', 'name', 'group', 'live'] + [t for _, t in TOOLS]
    out.append('| ' + ' | '.join(cols) + ' |')
    out.append('|' + '---|' * len(cols))
    # one alphabetical run over the whole merged universe (the knobs and the
    # show commands share the name space — a collision renders both rows)
    rows = [(n, True, shown[n]) for n in shown]
    rows += [(n, False, merged[n]) for n in merged]
    for name, is_show, by_tool in sorted(rows, key=lambda r: (r[0], r[1])):
        first = next(iter(by_tool.values()))
        cells = marks(by_tool, show=is_show)
        if is_show:
            kind, live = 's', '`show %s`' % name
        else:
            kind, live = ('c' if not first.flag else 'k'), live_cell(by_tool)
        out.append('| %s | `%s` | %s | %s | %s |'
                   % (kind, name, group_cell(by_tool),
                      live, ' | '.join(cells)))
    out.append('')
    out.append('Legend: `k` = a knob — the flag/env/config-file rows; '
               '`c` = control-only — a setting that lives on the control wire '
               'alone (the fake\'s pins and machines — no flag, no env, no '
               'config-file row); '
               '`s` = a show command — a report the wire answers with '
               '(`show <name>`; not a knob, nothing to set, the registry\'s '
               '`show` section); '
               '✓ = the tool has the row (**bold** = all four do); '
               'the `live` column is the control command itself — `set <name>` over '
               'the control plane, the wire name the registry gives the knob (it can '
               'differ from the flag: the cache\'s `cache-ttl` sets `ttl`) — '
               'a show row spells `show <name>`; '
               '*(startup-only)* = no live form, a restart applies the knob; a trailing '
               '`, restart` = the knob is startup-only too — the set records the value '
               '(the wire answers the restart note), the restart applies it; every '
               'secret is restart-marked and renders `startup-only — pass it by '
               'flag/env/config` — the wire refuses set/clear on it outright; a cell\'s '
               '`live` mark says the tool takes the knob live (a cell without one = '
               'that tool applies the knob at startup only); '
               '`group` = the row\'s display bucket — the tool\'s '
               'surfaces file the knob under it (blank = ungrouped, rendered bare); '
               '`hidden` = the command stays out of the wire\'s listings (it still '
               'answers); '
               '`secret` = a token — `show config` and the dumps render the knob as '
               '`*** SECRET REMOVED ***` (the value never does; the `-file` form renders '
               'the same placeholder when the row is set). The knob descriptions stay '
               'in the registries — `--help`, the man pages, `show knobs` and '
               '`help config` render them per tool.')
    out.append('')
    # the ruled-env-free rows: the registries' no-env notes (a flag row
    # without an env twin names why — the silent-gap rule)
    notes = []
    for tool, _t in TOOLS:
        rows, _shows = load(tool)
        for o in rows:
            if o.flag and not o.node and not o.env:
                notes.append((tool, o))
    if notes:
        out.append('Ruled env-free (the rows\' `no-env` notes — a flag row without an env twin names why): %s.'
                   % '; '.join('%s %s — %s' % (tool, '`--%s`' % o.name, o.no_env)
                               for tool, o in notes))
        out.append('')

    path = os.path.join(REPO, 'docs', 'OPTIONS.md')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    print('OPTIONS.md: %d knobs + %d show rows, %d knobs common to all four'
          % (len(merged), len(shown), len(all_four)))


if __name__ == '__main__':
    main()
