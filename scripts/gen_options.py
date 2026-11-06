#!/usr/bin/env python3
"""Render options.md — the knob comparison table across the four daemons —
from the per-tool option registries (lib/options.json via lib/options.py,
the one-knob-one-source rows). The file is GENERATED: edit the registries
and re-run, never the markdown.

  python3 scripts/gen_options.py

Stdlib only."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

from common.options import SECTIONS                              # noqa: E402

# the daemons, in the chain order the README tells: fake -> cache -> scraper,
# then the dashboard that renders the numbers
TOOLS = (('cache', 'cache'),
         ('scraper', 'scraper'),
         ('inverter', 'inverter'),
         ('dashboard', 'dashboard'))

CLI_ONLY = ('--config', '--dry-run', '--man', '--version', '--help')


def load(tool_dir):
    """The tool's wired Option rows (check_options.py's import dance: one
    module named `options` at a time)."""
    sys.path.insert(0, os.path.join(REPO, tool_dir, 'lib'))
    sys.modules.pop('options', None)
    mod = __import__('options')
    sys.path.pop(0)
    rows = tuple(mod.OPTIONS)
    sys.modules.pop('options', None)
    return rows


def marks(rows_by_tool):
    """One cell per tool: ✓ (bold when every tool has the knob), plus the
    live/secret markers."""
    common = all(rows_by_tool.get(t) for t, _ in TOOLS)
    cells = []
    for t, _ in TOOLS:
        opt = rows_by_tool.get(t)
        if not opt:
            cells.append('')
            continue
        note = opt.live and 'live' or ''
        if opt.secret:
            note = (note + '+secret') if note else 'secret'
        cells.append(('**✓**' if common else '✓') + (' ' + note if note else ''))
    return cells


def live_cell(rows_by_tool):
    """The live column: the control command the knob answers to on a running
    daemon — `set <name>` from the registry's live field (the wire name,
    which can differ from the flag: the cache's --cache-ttl sets ttl; a
    '/'-path spells as its words: `set inverter profile`), the tools' names
    joined when they diverge. No live name = *(startup-only)*: a restart
    applies it."""
    names = sorted({opt.live for opt in rows_by_tool.values() if opt.live})
    if not names:
        return '*(startup-only)*'
    return ', '.join('`set %s`' % n.replace('/', ' ') for n in names)


def main():
    registries = {key: load(d) for key, d in TOOLS}
    names = {key: t for key, t in TOOLS}

    # the merged knob universe: section -> name -> {tool: opt}
    merged = {}
    for key, _ in TOOLS:
        for opt in registries[key]:
            merged.setdefault(opt.section, {}).setdefault(opt.name, {})[key] = opt

    out = ['# The knobs of the family (options.md)',
           '',
           'One alphabetical table of every knob of the four daemons — the kind,',
           'the name, the function it files under and the control command that',
           'changes it on a running daemon — with a mark per',
           'tool. **Generated** from the per-tool `lib/options.json` registries (the',
           'one-knob-one-source rows) by `scripts/gen_options.py` — edit the',
           'registries and re-run `python3 scripts/gen_options.py`, never this file.',
           'The resolution order on every tool is flag > env > config script >',
           'default; the bare `$NAME` env forms are the knob\'s upper-snake name.',
           'Every bin also carries the CLI-only `--config`/`--dry-run`/`--man`',
           '(plus `--version`/`--help`) — flags, not knobs, so they have no rows',
           'here. The ctl/cli clients speak the control plane only',
           '(`--control-port`, the token file/env pair) and are not compared.',
           '']
    all_four = sorted(name for section in merged.values() for name, by_tool in section.items()
                      if len(by_tool) == len(TOOLS))
    out.append('Common to **all four** tools (%d): %s. The control-plane block is'
               % (len(all_four), ', '.join('`%s`' % n for n in all_four)))
    out.append('shared nearly verbatim; the audit, limits and metrics blocks follow the')
    out.append('family shape with per-tool defaults.')
    out.append('')
    cols = ['kind', 'name', 'function', 'live'] + [t for _, t in TOOLS]
    out.append('| ' + ' | '.join(cols) + ' |')
    out.append('|' + '---|' * len(cols))
    # one alphabetical run over the whole merged universe — the section only
    # breaks the ties (the same name files twice: interval on the cache's
    # device and the scraper's logging)
    order = {key: i for i, (key, _title) in enumerate(SECTIONS)}
    flat = [(name, section, by_tool)
            for section in merged for name, by_tool in merged[section].items()]
    flat.sort(key=lambda row: (row[0], order.get(row[1], len(order))))
    for name, section, by_tool in flat:
        first = next(iter(by_tool.values()))
        cells = marks(by_tool)
        kind = 'c' if not first.flag else 'k'
        out.append('| %s | `%s` | %s | %s | %s |'
                   % (kind, name, first.group or section, live_cell(by_tool),
                      ' | '.join(cells)))
    out.append('')
    out.append('Legend: `k` = a knob — the flag/env/config-file rows; '
               '`c` = control-only — a setting that lives on the control wire '
               'alone (the fake\'s pins and machines — no flag, no env, no '
               'config-file row); '
               '✓ = the tool has the knob (**bold** = all four do); '
               'the `live` column is the control command itself — `set <name>` over '
               'the control plane, the wire name the registry gives the knob (it can '
               'differ from the flag: the cache\'s `cache-ttl` sets `ttl`); '
               '*(startup-only)* = no live form, a restart applies the knob; a cell\'s '
               '`live` mark says the tool takes the knob live (a cell without one = '
               'that tool applies the knob at startup only); '
               '`secret` = a token — never rendered inline by '
               '`show config` (the `-file` form is). The knob descriptions stay '
               'in the registries — `--help`, the man pages, `show knobs` and '
               '`help config` render them per tool.')
    out.append('')

    path = os.path.join(REPO, 'options.md')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    total = sum(len(s) for s in merged.values())
    print('options.md: %d knobs, %d common to all four' % (total, len(all_four)))


if __name__ == '__main__':
    main()
