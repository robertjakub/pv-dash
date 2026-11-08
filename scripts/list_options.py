#!/usr/bin/env python3
"""Print every row of the lib/options.json registries — the knobs, the show
reports and the commands alike, one line each, the columns aligned:

  <name> <live> <type> [hidden] [restart] [secret]

`<type>` is the section the row rides in: options | show | commands; `<live>`
is the row's live wire name (the set/spell path — or the report/command's
live where the section carries one), `-` when the row has none (a pure
node/startup-only/commands row); `hidden`/`restart`/`secret` name the row's
flags, present only when true. With no arguments every registry prints
under a `# <tool>` header; name the projects to print a subset:

  python3 scripts/list_options.py            # all four
  python3 scripts/list_options.py cache      # one

Exit 0 = printed. Stdlib only."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = ('cache', 'scraper', 'dashboard', 'inverter')


def section_rows(path, section):
    try:
        reg = json.load(open(path))
    except (OSError, ValueError):
        return None
    return reg.get(section) or []


def main():
    args = sys.argv[1:]
    tools = args or TOOLS
    blocks = []
    for tool in tools:
        path = os.path.join(ROOT, tool, 'lib', 'options.json')
        if not os.path.exists(path):
            print('list_options.py: no registry at %s' % path)
            return 1
        rows = [(row.get('name', '?'), row.get('live') or '-', section,
                 ''.join(' %s' % f for f in ('hidden', 'restart', 'secret') if row.get(f)))
                for section in ('options', 'show', 'commands')
                for row in (section_rows(path, section) or []) if isinstance(row, dict)]
        blocks.append((tool, rows))
    width = {}
    for _, rows in blocks:
        for row in rows:
            for i, cell in enumerate(row[:3]):
                width[i] = max(width.get(i, 0), len(cell))
    for tool, rows in blocks:
        print('# %s' % tool)
        for name, live, section, flags in rows:
            print('%-*s  %-*s  %-*s%s' % (width[0], name, width[1], live, width[2], section, flags))
    return 0


if __name__ == '__main__':
    sys.exit(main())
