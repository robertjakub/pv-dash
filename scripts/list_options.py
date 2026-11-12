#!/usr/bin/env python3
"""Print every row of the lib/options.json registries — the knobs, the show
reports and the commands alike, one line each, the columns aligned:

  <tool> <name> <live> <type> <env> <snake> [hidden] [restart] [secret]

`<type>` is the section the row rides in: options | show | commands; `<live>`
is the row's live wire name (the set/spell path — or the report/command's
live where the section carries one), `-` when the row has none (a pure
node/startup-only/commands row); `<env>` is the row's environment variable
(the options rows carry one, `-` when the row reads none — the demo-only
knobs, the show/command rows); `<snake>` is the option's flag spelling,
taken verbatim (`--modbus-unit`, `-` where the row carries no flag — the
node rows, the show/command rows);
`hidden`/`restart`/`secret` name the row's flags, present only when true.
The hierarchy-node rows (`"node": true`, the
bare namespace words) stay hidden unless `--nodes` asks for them. Every tool
prints into the one flat table. With no arguments every registry prints in
registry order; name the projects to print a subset — positionally or via
`--tool` (one or more comma separated, `all` = the default; the two forms
refuse each other) — `--sort` orders the table by knob name (same-name rows
keep their tool order), `--hide` drops the named sections and `--show` keeps
only them — one or more, comma separated (options | show | commands); the
two refuse each other:

  python3 scripts/list_options.py            # all four
  python3 scripts/list_options.py cache      # one
  python3 scripts/list_options.py --nodes    # + the node rows
  python3 scripts/list_options.py --sort     # by knob name
  python3 scripts/list_options.py --hide commands,show    # the knobs only
  python3 scripts/list_options.py --show commands         # the commands only
  python3 scripts/list_options.py --tool cache,inverter   # the two tools

Exit 0 = printed; rc 2 = a bad --hide/--show section, an unknown --tool, a
missing value, or the mutually exclusive flags together. Stdlib only."""
import json
import os
import sys

from lib import REPO as ROOT, TOOLS   # the scripts' common lib — the canon fold rides the loader's own
SECTIONS = ('options', 'show', 'commands')


def section_rows(path, section):
    try:
        reg = json.load(open(path))
    except (OSError, ValueError):
        return None
    from common.settings.options import canon_fold, load_canon
    canon = load_canon()
    return [canon_fold(r, canon, section, path) for r in reg.get(section) or []]


def main():
    args = sys.argv[1:]
    if '-h' in args or '--help' in args:
        print(__doc__.strip())
        return 0
    nodes = '--nodes' in args
    sort = '--sort' in args
    hide, show = set(), set()
    tool_flag = []
    tools = []
    pending = None
    for a in args:
        if pending == '--tool':
            tool_flag.extend(s.strip() for s in a.split(',') if s.strip())
            pending = None
        elif pending:
            (hide if pending == '--hide' else show).update(
                s.strip() for s in a.split(',') if s.strip())
            pending = None
        elif a in ('--hide', '--show', '--tool'):
            pending = a
        elif a.startswith('--hide='):
            hide.update(s.strip() for s in a[7:].split(',') if s.strip())
        elif a.startswith('--show='):
            show.update(s.strip() for s in a[7:].split(',') if s.strip())
        elif a.startswith('--tool='):
            tool_flag.extend(s.strip() for s in a[7:].split(',') if s.strip())
        elif a.startswith('--'):
            continue
        else:
            tools.append(a)
    if pending:
        if pending == '--tool':
            print('list_options.py: --tool needs a tool: %s, or all' % ', '.join(TOOLS))
        else:
            print('list_options.py: %s needs a section: %s' % (pending, ', '.join(SECTIONS)))
        return 2
    bad = sorted((hide | show) - set(SECTIONS))
    if bad:
        print('list_options.py: unknown section: %s (%s)' % (', '.join(bad), ', '.join(SECTIONS)))
        return 2
    if hide and show:
        print('list_options.py: --hide and --show refuse each other')
        return 2
    keep = ([s for s in SECTIONS if s in show] if show
            else [s for s in SECTIONS if s not in hide])
    if tool_flag:
        if tools:
            print('list_options.py: --tool and the named tools refuse each other')
            return 2
        bad = sorted({t for t in tool_flag if t != 'all'} - set(TOOLS))
        if bad:
            print('list_options.py: unknown tool: %s (%s, or all)' % (', '.join(bad), ', '.join(TOOLS)))
            return 2
        if 'all' in tool_flag:
            tools = list(TOOLS)
        else:
            seen = set()
            tools = [t for t in tool_flag if not (t in seen or seen.add(t))]
    tools = tools or TOOLS
    blocks = []
    for tool in tools:
        path = os.path.join(ROOT, tool, 'lib', 'options.json')
        if not os.path.exists(path):
            print('list_options.py: no registry at %s' % path)
            return 1
        rows = [(tool, row.get('name', '?'), row.get('live') or '-', section,
                 (row.get('env') or '-') if section == 'options' else '-',
                 (row['flag'] if row.get('flag') else '-'),
                 ''.join(' %s' % f for f in ('hidden', 'restart', 'secret') if row.get(f)))
                for section in keep
                for row in (section_rows(path, section) or [])
                if isinstance(row, dict) and (nodes or not row.get('node'))]
        blocks.append((tool, rows))
    rows = [r for _, rs in blocks for r in rs]
    if sort:
        rows.sort(key=lambda r: r[1])
    width = {}
    for row in rows:
        for i, cell in enumerate(row[:6]):
            width[i] = max(width.get(i, 0), len(cell))
    for tool, name, live, section, env, snake, flags in rows:
        print('%-*s  %-*s  %-*s  %-*s  %-*s  %-*s%s' % (
            width[0], tool, width[1], name, width[2], live, width[3], section,
            width[4], env, width[5], snake, flags))
    return 0


if __name__ == '__main__':
    sys.exit(main())
