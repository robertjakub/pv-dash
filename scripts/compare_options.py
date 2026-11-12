#!/usr/bin/env python3
"""Compare the knob rows across the tool registries — which options are
spelled identically everywhere they ride (the common candidates) and
which drift (the difference table).

The knobs group by their flat registry name (the node rows are
namespaces, not knobs); four identity fields compare — the flat name,
the live path, the env twin and the --flag. A knob riding two or more
tools with all four fields equal is a common candidate (one shared
definition could carry it); any drift prints as a per-tool table, one
line per field, `*` marking the drifted values, the drifting fields
named on the knob's header line. The single-tool knobs and the
near-misses (one live path answering to several flat names, an alias
only some tools carry) follow as notes:

  python3 scripts/compare_options.py                 # all four tools
  python3 scripts/compare_options.py --tool cache,scraper

Exit 0 = printed; rc 1 = a missing registry; rc 2 = a bad --tool, a
missing value, or the mutually exclusive forms together. Stdlib only."""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scriptlib import TOOLS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELDS = ('live', 'env', 'flag')


def cell(row, field):
    if field == 'flag':
        return row['flag'] if row.get('flag') else '-'
    return row.get(field) or '-'


def knobs_of(path):
    try:
        reg = json.load(open(path))
    except (OSError, ValueError):
        return None
    return [r for r in (reg.get('options') or [])
            if isinstance(r, dict) and not r.get('node')]


def main():
    args = sys.argv[1:]
    if '-h' in args or '--help' in args:
        print(__doc__.strip())
        return 0
    tool_flag, tools, pending = [], [], None
    for a in args:
        if pending == '--tool':
            tool_flag.extend(s.strip() for s in a.split(',') if s.strip())
            pending = None
        elif a == '--tool':
            pending = a
        elif a.startswith('--tool='):
            tool_flag.extend(s.strip() for s in a[7:].split(',') if s.strip())
        elif a.startswith('--'):
            print('compare_options.py: unknown flag: %s' % a)
            return 2
        else:
            tools.append(a)
    if pending:
        print('compare_options.py: --tool needs a tool: %s, or all' % ', '.join(TOOLS))
        return 2
    if tool_flag and tools:
        print('compare_options.py: --tool and the named tools refuse each other')
        return 2
    named = tool_flag or tools
    bad = sorted({t for t in named if t != 'all'} - set(TOOLS))
    if bad:
        print('compare_options.py: unknown tool: %s (%s, or all)'
              % (', '.join(bad), ', '.join(TOOLS)))
        return 2
    if 'all' in named:
        named = list(TOOLS)
    order = [t for t in TOOLS if t in (named or TOOLS)]
    table = {}
    for tool in order:
        path = os.path.join(ROOT, tool, 'lib', 'options.json')
        knobs = knobs_of(path)
        if knobs is None:
            print('compare_options.py: no registry at %s' % path)
            return 1
        table[tool] = knobs

    groups = {}
    for tool in order:
        for row in table[tool]:
            groups.setdefault(row.get('name', '?'), {})[tool] = row
    common, diffs, singles = [], [], {}
    for name in sorted(groups):
        rows = groups[name]
        if len(rows) == 1:
            tool = next(iter(rows))
            singles.setdefault(tool, []).append(name)
            continue
        sigs = {(cell(r, 'live'), cell(r, 'env'), cell(r, 'flag'))
                for r in rows.values()}
        (common if len(sigs) == 1 else diffs).append((name, rows))

    print('the knobs of %s compared on the flat name, the live path, the env '
          'twin and the flag' % ', '.join(order))
    print('')

    print('## common — identical in every tool that carries the knob '
          '(the shared-definition candidates)')
    w = {}
    for name, rows in common:
        vals = (' '.join(t for t in order if t in rows),
                cell(next(iter(rows.values())), 'live'),
                cell(next(iter(rows.values())), 'env'),
                cell(next(iter(rows.values())), 'flag'))
        for i, v in enumerate((name,) + vals):
            w[i] = max(w.get(i, 0), len(v))
    for name, rows in common:
        vals = (name,
                ' '.join(t for t in order if t in rows),
                cell(next(iter(rows.values())), 'live'),
                cell(next(iter(rows.values())), 'env'),
                cell(next(iter(rows.values())), 'flag'))
        print('  ' + '  '.join('%-*s' % (w[i], v)
                               for i, v in enumerate(vals)).rstrip())
    if not common:
        print('  (none)')
    print('')

    print('## differences — the same flat knob, a field drifts '
          '(* marks the drifted values)')
    for name, rows in diffs:
        cols = [t for t in order if t in rows]
        fields = list(FIELDS)
        if any(r.get('alias') for r in rows.values()):
            fields.append('alias')
        drift = [f for f in fields
                 if len({cell(rows[t], f) for t in cols}) > 1]
        fw = max(len(f) for f in fields)
        cw = {t: max(len(t), *(len(cell(rows[t], f)) for f in fields))
              for t in cols}
        print('  %s  drifts: %s' % (name, ', '.join(drift)))
        print(('    %s  %s' % (' ' * fw,
              '  '.join('%-*s' % (cw[t], t) for t in cols))).rstrip())
        for f in fields:
            usual = Counter(cell(rows[t], f)
                            for t in cols).most_common(1)[0][0]
            line = []
            for t in cols:
                v = cell(rows[t], f)
                if f in drift and v != usual:
                    v += '*'
                line.append('%-*s' % (cw[t], v))
            print(('    %-*s  %s' % (fw, f, '  '.join(line))).rstrip())
    if not diffs:
        print('  (none)')
    print('')

    print('## single-tool knobs — no cross-tool comparison')
    for tool in order:
        if singles.get(tool):
            print('  %-*s  %s' % (max(len(t) for t in order), tool,
                  ', '.join(singles[tool])))
    print('')

    notes = []
    by_live = {}
    for name, rows in groups.items():
        for t, r in rows.items():
            if r.get('live'):
                by_live.setdefault(r['live'], set()).add((name, t))
    for live in sorted(by_live):
        names = {n for n, _ in by_live[live]}
        if len(names) > 1:
            spell = ', '.join('%s (%s)' % (n, ', '.join(
                t for t in order if (n, t) in by_live[live]))
                for n in sorted(names))
            notes.append('the live path %s answers to several flat names: %s'
                         % (live, spell))
    for name, rows in common:
        als = {rows[t].get('alias') or '-' for t in rows}
        if len(als) > 1:
            notes.append('the common knob %s carries an alias on %s only: %s'
                         % (name, ', '.join(t for t in rows if rows[t].get('alias')),
                            ', '.join(sorted(a for a in als if a != '-'))))
    if notes:
        print('## notes — the near-misses')
        for note in notes:
            print('  - %s' % note)
        print('')
    print('%d common, %d drifting, %d single-tool (%d knobs over %d tools)'
          % (len(common), len(diffs), sum(len(v) for v in singles.values()),
             len(groups), len(order)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
