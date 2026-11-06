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

SECTION_TAG = {'device': 'device', 'serving': 'serving', 'control': 'control plane',
               'metrics': 'own /metrics', 'limits': 'limits', 'audit': 'audit trail',
               'persistence': 'persistence', 'logging': 'logging'}

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


def default_text(opt):
    """The argparse-rendered default for the %(default)s helps."""
    v = opt.default
    if v is None:
        return 'unset'
    if isinstance(v, bool):
        return 'on' if v else 'off'
    if isinstance(v, float):
        return '%g' % v
    return str(v)


def description(opt):
    """The registry help with the %(default)s placeholders filled and the
    markdown-hostile characters escaped — pipes and bare angle-bracket
    placeholders (<token>, <listen-port>) render literally in the table
    instead of vanishing as unknown HTML tags. Code spans stay untouched."""
    try:
        text = opt.help % {'default': default_text(opt)}
    except (KeyError, TypeError, ValueError):
        text = opt.help
    parts = text.split('`')
    for i, part in enumerate(parts):
        if i % 2 == 0:  # the segments outside the backtick code spans
            parts[i] = part.replace('|', '\\|').replace('<', '\\<')
    return ''.join(parts)


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
           'One table comparing every knob of the four daemons — the name, the',
           'function it files under and the registry description — with a mark per',
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
               % (len(all_four), ', '.join('`--%s`' % n for n in all_four)))
    out.append('shared nearly verbatim; the audit, limits and metrics blocks follow the')
    out.append('family shape with per-tool defaults.')
    out.append('')
    out.append('| knob | function | description | ' + ' | '.join(t for _, t in TOOLS) + ' |')
    out.append('|---|---|---|---|---|---|---|---|')
    for section, _title in SECTIONS:
        if section not in merged:
            continue
        for name in sorted(merged[section]):
            by_tool = merged[section][name]
            first = next(iter(by_tool.values()))
            cells = marks(by_tool)
            out.append('| `--%s` | %s | %s | %s |'
                       % (name, SECTION_TAG.get(section, section), description(first),
                          ' | '.join(cells)))
    out.append('')
    out.append('Legend: ✓ = the tool has the knob (**bold** = all four do); '
               '`live` = settable on a running daemon (`set <name> <value>` over the '
               'control plane); `secret` = a token — never rendered inline by '
               '`show config` (the `-file` form is). The description is the shared '
               'registry text (the same one `--help`, the man pages, `show knobs` '
               'and the bundled configs render), taken from the first tool that '
               'defines the knob and with its default filled in — where the tools '
               'word a knob differently, the tool\'s own `--help`/man page wins.')
    out.append('')

    path = os.path.join(REPO, 'options.md')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    total = sum(len(s) for s in merged.values())
    print('options.md: %d knobs, %d common to all four' % (total, len(all_four)))


if __name__ == '__main__':
    main()
