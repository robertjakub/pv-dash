#!/usr/bin/env python3
"""The registries' compare tools, one script: the three lenses over the
four lib/options.json registries and shared/suite/options.json — the
instruments that built the knob canon and the eye that audits it.

- `family` (the default) — the knobs grouped by flat registry name, the
  four identity fields compared (the flat name, the live path, the env
  twin, the --flag): the common candidates (one shared definition could
  carry them), the per-tool difference tables (`*` marks the drifted
  values), the single-tool knobs and the near-miss notes (one live path
  answering to several flat names, an alias on some tools only);
- `name <flat>` — the deep diff on one registry name across the three
  sections (options, show, commands; a `clear` commands row gets the
  commands report): the effective folded form per tool, what a canon
  move takes (the byte-identical fields the block could carry, the
  placements the house keeps on the rows, the gated drift and its
  EXEMPT entries) — the verdict re-uses gates/options.py's own
  GATED/EXEMPT/KEY_RANK and the loader's canon_fold, so it can never
  drift from the gates it predicts;
- `drift` — the whole-family report against the canon, every knob in
  its folded form: the canon adoption census (FAMILY / partial /
  single-tool / DEAD), the inline-wins deviations and the block gaps
  (the fold-up candidates), the promotion list, the shape differences
  that block a shared definition, the single-tool remainder.

The shape fields are the family contract (flag, env, conv, default, the
bounds, the values, the markers); live/alias/node/no-env/group are the
per-tool console placements and never gate a match. A report family —
the form gates live in gates/options.py, the battery runs them via
lint-gates' checks; nothing here exits 1 on drift.

  python3 dev/options_compare.py                       # the family lens, all four tools
  python3 dev/options_compare.py --tool cache,scraper  # the lens, two tools
  python3 dev/options_compare.py name modbus-unit      # one knob, all tools
  python3 dev/options_compare.py name clear            # a commands row
  python3 dev/options_compare.py drift                 # the folded family report

Exit 0 = printed; rc 1 = a missing/failed registry, canon or name;
rc 2 = bad usage. Stdlib only."""
import json
import os
import sys
from collections import Counter

from lib import REPO as ROOT, TOOLS   # the scripts' common lib — the canon fold rides the loader's own
from common.settings.options import canon_fold

SECTIONS = ('options', 'show', 'commands')
NOUN = {'options': 'knob', 'show': 'show row', 'commands': 'commands row'}
FIELD = {'show': 'setting-help', 'commands': 'help'}   # the text a plain-string block fills
PLACEMENT = ('live', 'alias', 'node', 'no-env', 'group')
SHAPE = ('flag', 'env', 'conv', 'negates', 'secret', 'hidden', 'restart',
         'min', 'max', 'check', 'values', 'hint', 'value-help', 'default')
PROSE = ('help', 'setting-help')
BLOCK_KEYS = ('name', 'only', 'shared')
FIELDS = ('live', 'env', 'flag')


def jv(v):
    """A field value as a comparable/displayable token."""
    return json.dumps(v, ensure_ascii=False, sort_keys=True) if not isinstance(v, str) else v


def clip(v, cap=110):
    """A value for display — long help texts cut to one line's worth."""
    text = jv(v)
    return text if len(text) <= cap else text[:cap - 1] + '…'


def dev_text(field, block_v, row_v, row):
    """One deviation line's body; the env-free rows (env: null + a no-env
    note) get their own wording — the refusal is the design, not a typo."""
    if field == 'env' and row_v is None and row.get('no-env'):
        return 'env: the block says %s — the row refuses it (no-env: %s)' \
            % (jv(block_v), jv(row['no-env']))
    return '%s: block %s vs row %s' % (field, clip(block_v), clip(row_v))


def parse_tools(args, prog, allow_positional=False):
    """The --tool filter + the positional tools. Returns (order, rc) —
    order None on a usage error (the message printed)."""
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
            print('%s: unknown flag: %s' % (prog, a))
            return None, 2
        elif allow_positional:
            tools.append(a)
        else:
            print('%s: unknown flag: %s' % (prog, a))
            return None, 2
    if pending:
        print('%s: --tool needs a tool: %s, or all' % (prog, ', '.join(TOOLS)))
        return None, 2
    if tool_flag and tools:
        print('%s: --tool and the named tools refuse each other' % prog)
        return None, 2
    named = tool_flag or tools
    bad = sorted({t for t in named if t != 'all'} - set(TOOLS))
    if bad:
        print('%s: unknown tool: %s (%s, or all)'
              % (prog, ', '.join(bad), ', '.join(TOOLS)))
        return None, 2
    if 'all' in named:
        named = list(TOOLS)
    return [t for t in TOOLS if t in (named or TOOLS)], 0


def load_raw(order, prog):
    """The canon + the four registries (raw, whole JSON). A missing file
    or a parse failure exits 1."""
    canon_path = os.path.join(ROOT, 'shared', 'suite', 'options.json')
    try:
        with open(canon_path, encoding='utf-8') as f:
            canon = json.load(f)
    except (OSError, ValueError) as e:
        print('%s: shared/suite/options.json: %s' % (prog, e))
        raise SystemExit(1)
    raw = {}
    for tool in order:
        path = os.path.join(ROOT, 'apps', tool, 'lib', 'options.json')
        try:
            with open(path, encoding='utf-8') as f:
                raw[tool] = json.load(f)
        except (OSError, ValueError) as e:
            print('%s: %s: %s' % (prog, path, e))
            raise SystemExit(1)
    return raw, canon


def section_rows(raw, tool, section):
    return raw[tool].get(section) or []


# ---------------------------------------------------------------- family

def cell(row, field):
    if field == 'flag':
        return row['flag'] if row.get('flag') else '-'
    return row.get(field) or '-'


def knobs_of(path, tool):
    try:
        reg = json.load(open(path))
    except (OSError, ValueError):
        return None
    from common.settings.options import load_canon
    canon = load_canon()
    return [canon_fold(r, canon, 'options', tool)
            for r in (reg.get('options') or [])
            if isinstance(r, dict) and not r.get('node')]


def family(order):
    table = {}
    for tool in order:
        path = os.path.join(ROOT, 'apps', tool, 'lib', 'options.json')
        knobs = knobs_of(path, tool)
        if knobs is None:
            print('options_compare.py: no registry at %s' % path)
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


# ----------------------------------------------------------------- drift

def adoption(raw, canon, order):
    """The blocks' ref map per section: [(section, tag, key, tools)]."""
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


def drift(order):
    raw, canon = load_raw(order, 'options_compare.py')
    raw = {tool: {sec: raw[tool].get(sec) or [] for sec in SECTIONS}
           for tool in order}
    rows = folded(raw, canon, order)
    cands, drifts, singles = compare(rows, order)

    print('the option registries of %s against shared/suite/options.json'
          % ', '.join(order))
    print('')

    print('## canon — the blocks\' adoption (FAMILY = every tool named, '
          'DEAD = nobody refs it)')
    adoptions = adoption(raw, canon, order)
    kw = max([0] + [len(key) for _, tag, key, _ in adoptions])
    for section, tag, key, who in adoptions:
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


# ------------------------------------------------------------------ name

def key_rank(field):
    """The display order: the lint's canonical row rank, the unknown keys
    after, alphabetical."""
    from gates.options import KEY_RANK
    return (KEY_RANK.index(field), '') if field in KEY_RANK else (len(KEY_RANK), field)


def value_groups(rows, carriers, field):
    """The carriers grouped by the field's effective value; the tools
    without the field ride out (the family drift pass's own rule)."""
    groups = {}
    for t in carriers:
        if field in rows[t]:
            groups.setdefault(jv(rows[t][field]), []).append(t)
    return groups


def report(raw, canon, order, name, section, rows):
    """One section's full report over its pre-folded rows."""
    from gates.options import EXEMPT, GATED, SECTION_FIELD
    carriers = [t for t in order if t in rows]
    fields = sorted({f for t in carriers for f in rows[t]}
                    - {'name'} - set(BLOCK_KEYS), key=key_rank)
    drift = [f for f in fields
             if len(value_groups(rows, carriers, f)) > 1]
    gated_fields = GATED if section == 'options' else (SECTION_FIELD[section],)
    gated = [f for f in drift if f in gated_fields]
    only_marked = [t for t in carriers if rows[t].get('only')]
    raw_row = {t: next(r for r in raw[t].get(section) or []
                       if isinstance(r, dict) and r.get('name') == name)
               for t in carriers}
    ref_keys = sorted({raw_row[t].get('shared') for t in carriers
                       if raw_row[t].get('shared')})
    blocks = canon.get(section) or {}

    print('the %s `%s` across %s (the effective rows — the canon fold applied)'
          % (NOUN[section], name, ', '.join(carriers)))
    print('')

    print('## fields — the byte-identical field on one line, the drift '
          'one tool per line (* = off the majority)')
    if drift:
        print('  drifts: %s' % ', '.join(drift))
    fw = max([len('field')] + [len(f) for f in fields])
    tw = max(len(t) for t in carriers)
    for f in fields:
        present = [t for t in carriers if f in rows[t]]
        if f not in drift:
            tail = '' if len(present) == len(carriers) \
                else '  (only %s)' % ', '.join(present)
            print(('  %-*s  %s%s' % (fw, f, clip(rows[present[0]][f], 74),
                                     tail)).rstrip())
            continue
        groups = value_groups(rows, carriers, f)
        usual = max(groups, key=lambda v: len(groups[v]))
        print('  %s' % f)
        for t in carriers:
            if f not in rows[t]:
                print('    %-*s  -' % (tw, t))
                continue
            star = '*' if jv(rows[t][f]) != usual else ''
            print('    %-*s  %s%s' % (tw, t, clip(rows[t][f], 90), star))
    if not fields:
        print('  (no fields)')
    print('')

    print('## canon — shared/suite/options.json')
    if ref_keys:
        for key in ref_keys:
            block = blocks.get(key)
            ref_by = [t for t in carriers if raw_row[t].get('shared') == key]
            if block is None:
                print('  the rows ref %s/%s — no such block (the fold fails '
                      'loud)' % (section, key))
                continue
            print('  block %s/%s — refs: %s' % (section, key, ', '.join(ref_by)))
            devs, gaps = [], set()
            for t in ref_by:
                r = raw_row[t]
                if isinstance(block, dict):
                    devs.extend('%s: %s' % (t, dev_text(f, block[f], r[f], r))
                                for f in sorted(set(block) & set(r))
                                if r[f] != block[f])
                    gaps |= (set(r) - set(block)) - set(PLACEMENT) - set(BLOCK_KEYS)
                else:   # the plain-text block: the row's description field may contradict
                    if r.get(SECTION_FIELD[section]) not in (None, block):
                        devs.append('%s: %s' % (t, dev_text(
                            SECTION_FIELD[section], block,
                            r[SECTION_FIELD[section]], r)))
                    gaps |= (set(r) - set(PLACEMENT)) - set(BLOCK_KEYS) \
                        - {SECTION_FIELD[section]}
            for d in devs:
                print('    %s' % d)
            if gaps:
                print('    the block lacks: %s (the rows carry them — the '
                      'fold-up candidates)' % ', '.join(sorted(gaps)))
    else:
        print('  no block — every row spells the %s inline' % NOUN[section])
    orphan = name in blocks and name not in ref_keys
    if orphan:
        print('  a block %s/%s exists that no carrier refs (the orphan gate '
              'fails it — ref it or drop it)' % (section, name))
    print('')

    print('## move — what riding shared/suite/options.json takes')
    every = [f for f in fields
             if all(f in rows[t] for t in carriers)
             and len(value_groups(rows, carriers, f)) == 1]
    shape = [f for f in every if f not in PLACEMENT]
    place = [f for f in every if f in PLACEMENT]
    print('  the block could carry (byte-identical on every carrier): %s'
          % (', '.join(shape) or '-'))
    if place:
        print('  the console placements, byte-identical too — the house '
              'keeps them on the rows: %s' % ', '.join(place))
    stays = []
    for f in fields:
        if f in every:
            continue
        why = 'drifts' if f in drift else 'uneven across the carriers'
        stays.append('%s (%s)' % (f, why))
    if stays:
        print('  stays row-borne: %s' % ', '.join(stays))
    if gated:
        ex = EXEMPT.get((section, name), ())
        free = [f for f in gated if f not in ex]
        held = [f for f in gated if f in ex]
        if free:
            print('  the gated drift — align the rows or exempt it in '
                  'gates/options.py: %s' % ', '.join(free))
        if held:
            print('  the gated drift, already exempt: %s' % ', '.join(held))
    if only_marked:
        print('  the only mark pins %s — a canon ref refuses beside it '
              '(pick one)' % ', '.join(only_marked))
    block = blocks.get(name)
    must, twins = [], []
    for f in gated_fields:
        for v, ts in value_groups(rows, carriers, f).items():
            if len(ts) < 3:
                continue   # the lint's own floor: a twin of two never gates
            block_has = (jv(block.get(f)) == v) if isinstance(block, dict) \
                else (section != 'options' and block == v)
            inline = [t for t in ts if f in raw_row[t]]
            if not block_has:
                must.append('%s (%s)' % (f, ', '.join(ts)))
            elif inline:
                twins.append('%s (%s)' % (f, ', '.join(inline)))
    if must:
        print('  the must-ref will demand the block carry: %s (or the exempt)'
              % '; '.join(must))
    if twins:
        print('  the byte-equal inline twins to drop (the block speaks '
              'them): %s' % '; '.join(twins))
    print('')
    print('%d of %d tools carry the %s, %d of %d fields drift (%d gated), '
          'canon block: %s'
          % (len(carriers), len(order), NOUN[section], len(drift), len(fields),
             len(gated),
             ('yes — %s/%s' % (section, ref_keys[0])) if ref_keys
             else ('unref\'d %s/%s' % (section, name)) if orphan else 'no'))


def name_verb(order, name):
    raw, canon = load_raw(order, 'options_compare.py')
    found = []
    for section in SECTIONS:
        rows = {}
        for tool in order:
            for r in raw[tool].get(section) or []:
                if isinstance(r, dict) and r.get('name') == name:
                    rows[tool] = canon_fold(r, canon, section, tool)
                    break
        if rows:
            found.append((section, rows))
    if not found:
        print('options_compare.py: no registry rows %r in options, show or '
              'commands (%s)' % (name, ', '.join(order)))
        return 1
    for i, (section, rows) in enumerate(found):
        if i:
            print('')
        report(raw, canon, order, name, section, rows)
    return 0


# ------------------------------------------------------------------ main

def main():
    args = sys.argv[1:]
    if '-h' in args or '--help' in args:
        print(__doc__.strip())
        return 0
    verb = 'family'
    if args and args[0] in ('family', 'name', 'drift'):
        verb = args.pop(0)
    if verb == 'name':
        name = next((a for a in args if not a.startswith('--')), None)
        if not name:
            print('options_compare.py: name a flat registry name: '
                  'python3 dev/options_compare.py name <flat-name>')
            return 2
        args.remove(name)
    order, rc = parse_tools(args, 'options_compare.py',
                            allow_positional=(verb == 'family'))
    if order is None:
        return rc
    if verb == 'family':
        return family(order)
    if verb == 'drift':
        return drift(order)
    return name_verb(order, name)


if __name__ == '__main__':
    sys.exit(main())
