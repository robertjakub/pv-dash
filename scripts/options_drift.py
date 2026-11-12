#!/usr/bin/env python3
"""Combine the four tools' lib/options.json with shared/suite/options.json —
the one drift report the family-unify assumption asks for: the option keys
MUST be the same across the tools, and the family-wide definition lives in
the canon. Every knob compares in its FOLDED form (the canon ref resolved by
the loader's own canon_fold — the truth the daemons load):

- the canon adoption — every block of shared/suite/options.json and the
  tools that ref it: FAMILY (all of them), partial, single-tool, DEAD
  (nobody listens — a candidate for deletion);
- the deviations — a row that contradicts a field its own canon block
  speaks (the inline-wins escape hatch, one line per field), plus the
  block gaps: the row-borne fields the block lacks (candidates to fold
  up into the canon);
- the candidates — the same flat knob in two or more tools with the
  whole shape agreeing, still spelled inline (or ref'd by some tools
  only): the promotion list, the keys that should move into
  shared/suite/options.json;
- the differences — the same flat knob, a shape field disagrees across
  the tools (the drift that blocks a shared definition), each drifting
  field spelled per tool, the per-tool console placements (live/alias)
  noted beside;
- the single-tool knobs — no cross-tool comparison exists.

The shape fields are the family contract (flag, env, conv, default, the
bounds, the values, the markers); live/alias/node/no-env/group are the
per-tool console placements and never gate a match. A report only — the
form gates live in lint_options.py, the tool-vs-tool identity fields in
compare_options.py.

  python3 scripts/options_drift.py                 # all four tools
  python3 scripts/options_drift.py --tool cache,scraper

Exit 0 = printed; rc 1 = a missing registry or a missing canon file;
rc 2 = a bad --tool or a missing value. Stdlib only."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scriptlib import TOOLS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = ('options', 'show', 'commands')
FIELD = {'show': 'setting-help', 'commands': 'help'}   # the text a plain-string block fills
PLACEMENT = ('live', 'alias', 'node', 'no-env', 'group')
SHAPE = ('flag', 'env', 'conv', 'negates', 'secret', 'hidden', 'restart',
         'min', 'max', 'check', 'values', 'hint', 'value-help', 'default')
PROSE = ('help', 'setting-help')


def jv(v):
    """A field value as a comparable/displayable token."""
    return json.dumps(v, sort_keys=True) if not isinstance(v, str) else v


def load(order):
    """The registries (raw rows) + the canon. Returns (raw, canon) — raw
    keyed tool then section; a missing registry exits 1."""
    canon_path = os.path.join(ROOT, 'shared', 'suite', 'options.json')
    try:
        with open(canon_path, encoding='utf-8') as f:
            canon = json.load(f)
    except OSError:
        print('options_drift.py: no canon at %s' % canon_path)
        raise SystemExit(1)
    raw = {}
    for tool in order:
        path = os.path.join(ROOT, tool, 'lib', 'options.json')
        try:
            with open(path, encoding='utf-8') as f:
                meta = json.load(f)
        except OSError:
            print('options_drift.py: no registry at %s' % path)
            raise SystemExit(1)
        raw[tool] = {s: meta.get(s) or [] for s in SECTIONS}
    return raw, canon


def adoption(raw, canon, order):
    """The blocks' ref map per section: [(tag, key, tools)]."""
    out = []
    for section in SECTIONS:
        users = {k: [] for k in (canon.get(section) or {})}
        for tool in order:
            for r in raw[tool][section]:
                key = r.get('shared')
                if key in users:
                    users[key].append(tool)
        for key in sorted(users):
            tools = users[key]
            tag = ('FAMILY' if len(tools) == len(order) else
                   'partial' if tools else 'DEAD')
            out.append((section, tag, key, ', '.join(tools) or '-'))
    return out


def dev_text(field, block_v, row_v, row):
    """One deviation line's body; the env-free rows (env: null + a no-env
    note) get their own wording — the refusal is the design, not a typo."""
    if field == 'env' and row_v is None and row.get('no-env'):
        return 'env: the block says %s — the row refuses it (no-env: %s)' \
            % (jv(block_v), jv(row['no-env']))
    return '%s: block %s vs row %s' % (field, clip(block_v), clip(row_v))


def clip(v, cap=110):
    """A value for display — long help texts cut to one line's worth."""
    text = jv(v)
    return text if len(text) <= cap else text[:cap - 1] + '…'


def deviations(raw, canon, order):
    """The rows that contradict their block, and the fields the block
    lacks. Returns (dev_lines, gap_groups): dev_lines =
    [(section, name, tool, [texts])] — the inline-wins overrides, the
    row's own gaps appended; gap_groups = [(section, name, [tools],
    [gaps])] — the identical gap set borne by several tools' otherwise
    conforming rows, one line for the lot."""
    dev_lines, gap_groups = [], {}
    for section in SECTIONS:
        blocks = canon.get(section) or {}
        text_field = FIELD.get(section)
        for tool in order:
            for r in raw[tool][section]:
                key = r.get('shared')
                if key not in blocks:
                    continue
                block = blocks[key]
                dev, gaps = [], []
                if isinstance(block, dict):
                    dev = [dev_text(f, block[f], r[f], r)
                           for f in sorted(set(block) & set(r)) if r[f] != block[f]]
                    gaps = sorted((set(r) - set(block))
                                  - set(PLACEMENT) - {'name', 'shared', 'only'})
                else:   # the plain-text block: the row's description field may contradict
                    if text_field and r.get(text_field) not in (None, block):
                        dev.append(dev_text(text_field, block, r[text_field], r))
                    gaps = sorted((set(r) - set(PLACEMENT))
                                  - {'name', 'shared', 'only', text_field})
                name = r.get('name', '?')
                if dev:
                    dev_lines.append((section, name, tool, dev, gaps))
                elif gaps:
                    gap_groups.setdefault((section, name, tuple(gaps)), []).append(tool)
    return dev_lines, [k + (v,) for k, v in sorted(gap_groups.items(),
                                                    key=lambda p: (p[0][0], p[0][1], p[0][2]))]


def folded(raw, canon, order):
    """The folded option rows per tool: {tool: {name: row}} (the loader's
    own fold — a bad ref fails loud here too)."""
    from common.settings.options import canon_fold
    rows = {}
    for tool in order:
        rows[tool] = {r['name']: canon_fold(r, canon, 'options', tool)
                      for r in raw[tool]['options'] if isinstance(r, dict) and 'name' in r}
    return rows


def compare(rows, order):
    """The flat names in two or more tools, split: candidates (the shape
    agrees, the canon ref misses on at least one tool) and drifts (a
    shape field disagrees). Returns (candidates, drifts, singles):
    candidates = [(name, tools, kind, prose-fields)], drifts =
    [(name, tools, {field: {tool: value}})], singles = {tool: [names]}."""
    names = sorted(set().union(*[set(r) for r in rows.values()]))
    cands, drifts, singles = [], [], {}
    for name in names:
        carrying = [t for t in order if name in rows[t]]
        if len(carrying) < 2:
            for t in carrying:
                singles.setdefault(t, []).append(name)
            continue
        table = {t: rows[t][name] for t in carrying}
        if any(table[t].get('only') for t in carrying):
            singles.setdefault(carrying[0], []).append(name)
            continue
        drift = [f for f in SHAPE
                 if len({jv(table[t].get(f)) for t in carrying}) > 1]
        refs = [t for t in carrying if table[t].get('shared')]
        if not drift:
            if len(refs) == len(carrying):
                continue   # on the canon everywhere — the assumption holds
            kind = ('partial ref — %s spell it inline' % ', '.join(
                t for t in carrying if t not in refs)) if refs else \
                'inline — promote the block'
            prose = [f for f in PROSE
                     if len({jv(table[t].get(f)) for t in carrying}) > 1]
            cands.append((name, carrying, kind, prose))
        else:
            prose = [f for f in PROSE
                     if len({jv(table[t].get(f)) for t in carrying}) > 1]
            place = [f for f in ('live', 'alias')
                     if len({jv(table[t].get(f)) for t in carrying}) > 1]
            vals = {f: {t: table[t].get(f) for t in carrying} for f in drift}
            drifts.append((name, carrying, vals, prose, place))
    return cands, drifts, singles


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
        else:
            print('options_drift.py: unknown flag: %s' % a)
            return 2
    if pending:
        print('options_drift.py: --tool needs a tool: %s, or all' % ', '.join(TOOLS))
        return 2
    bad = sorted(set(tool_flag) - set(TOOLS))
    if bad:
        print('options_drift.py: unknown tool: %s (%s, or all)'
              % (', '.join(bad), ', '.join(TOOLS)))
        return 2
    order = [t for t in TOOLS if not tool_flag or t in tool_flag]

    raw, canon = load(order)
    rows = folded(raw, canon, order)
    cands, drifts, singles = compare(rows, order)

    print('the option registries of %s against shared/suite/options.json'
          % ', '.join(order))
    print('')

    print('## canon — the blocks\' adoption (FAMILY = every tool named, '
          'DEAD = nobody refs it)')
    kw = max([0] + [len(key) for _, tag, key, _ in adoption(raw, canon, order)])
    for section, tag, key, who in adoption(raw, canon, order):
        print('  %-8s %-8s %-*s  %s' % (section, tag, kw, key, who))
    print('')

    dev_lines, gap_groups = deviations(raw, canon, order)
    print('## deviations — the row contradicts its own canon block '
          '(the inline-wins overrides)')
    if dev_lines:
        for section, name, tool, dev, gaps in dev_lines:
            for d in dev:
                print('  %-8s %-24s [%s]  %s' % (section, name, tool, d))
            if gaps:
                print('  %-8s %-24s [%s]  the block lacks: %s'
                      % (section, name, tool, ', '.join(gaps)))
    else:
        print('  (none)')
    print('')

    print('## block gaps — the fields the rows carry and the block lacks '
          '(the fold-up candidates; identical sets grouped)')
    if gap_groups:
        for section, name, gaps, tools in gap_groups:
            print('  %-8s %-24s %-38s %s'
                  % (section, name, 'the block lacks: ' + ', '.join(gaps),
                     ', '.join(tools)))
    else:
        print('  (none)')
    print('')

    print('## candidates — the same knob, the whole shape agreeing, '
          'not on the canon everywhere (the promotion list)')
    if cands:
        for name, carrying, kind, prose in cands:
            note = (' — the prose drifts: %s' % ', '.join(prose)) if prose else ''
            print('  %-24s %-30s %s%s'
                  % (name, ', '.join(carrying), kind, note))
    else:
        print('  (none)')
    print('')

    print('## differences — the same flat knob, a shape field disagrees '
          '(the drift that blocks a shared definition)')
    if drifts:
        for name, carrying, vals, prose, place in drifts:
            print('  %s  [%s]' % (name, ', '.join(carrying)))
            for f in vals:
                cells = '  '.join('%s=%s' % (t, clip(vals[f][t], 90))
                                  for t in carrying)
                print('    %-10s %s' % (f, cells))
            if prose:
                print('    %-10s %s' % ('prose', ', '.join(prose)))
            if place:
                print('    %-10s %s' % ('placement', ', '.join(place)))
    else:
        print('  (none)')
    print('')

    print('## single-tool knobs — no cross-tool comparison')
    for tool in order:
        if singles.get(tool):
            print('  %-10s %s' % (tool, ', '.join(sorted(singles[tool]))))
    print('')

    adoptions = adoption(raw, canon, order)
    blocks = len(adoptions)
    fam = sum(1 for _, tag, _, _ in adoptions if tag == 'FAMILY')
    dead = sum(1 for _, tag, _, _ in adoptions if tag == 'DEAD')
    print('%d canon blocks (%d family-wide, %d dead), %d deviating rows, '
          '%d block gaps, %d candidates, %d drifting, %d single-tool '
          '(%d knobs over %d tools)'
          % (blocks, fam, dead, len(dev_lines), len(gap_groups),
             len(cands), len(drifts),
             sum(len(v) for v in singles.values()),
             sum(len(rows[t]) for t in order), len(order)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
