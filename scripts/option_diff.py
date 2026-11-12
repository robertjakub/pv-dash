#!/usr/bin/env python3
"""One flat name, every tool, every field, every section — the deep diff
on one registry name. compare_options.py compares the four identity
fields across the whole family, options_drift.py reports the whole
family at once; this one answers the two questions a single name's canon
move asks. The search walks the registry's three sections — options,
show, commands, the canon's own three — and every one that rows the name
gets the full report (`clear` is a commands row: the commands report
answers):

- what differs — the row's EFFECTIVE form per tool (the loader's canon
  fold applied — the truth the daemons load), every field on one line,
  the drifting fields spelled per tool, `*` marking the off-majority
  values;
- what a move to shared/options.json takes — the canon state (the
  block, the refs, the inline-wins deviations, the row-borne fields the
  block lacks) and the verdict: the fields the block could carry
  (byte-identical on every carrier), the console placements the house
  keeps on the rows, and the gated drift the family lint refuses
  without an EXEMPT entry (the exempt ones named as already carried).

The verdict re-uses lint_options.py's own GATED/EXEMPT/KEY_RANK and the
loader's canon_fold — it can never drift from the gates it predicts.

  python3 scripts/option_diff.py modbus-unit          # one knob, all tools
  python3 scripts/option_diff.py clear                # a commands row
  python3 scripts/option_diff.py upstream --tool cache,scraper

Exit 0 = printed; rc 1 = a missing registry/canon file, a bad canon ref,
or a name no section rows; rc 2 = a missing name or a bad --tool.
Stdlib only."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scriptlib import TOOLS
from lint_options import EXEMPT, GATED, KEY_RANK, SECTION_FIELD
from common.settings.options import canon_fold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = ('options', 'show', 'commands')
NOUN = {'options': 'knob', 'show': 'show row', 'commands': 'commands row'}
PLACEMENT = ('live', 'alias', 'node', 'no-env', 'group')
BLOCK_KEYS = ('name', 'only', 'shared')


def jv(v):
    """A field value as a comparable/displayable token."""
    return json.dumps(v, ensure_ascii=False, sort_keys=True) if not isinstance(v, str) else v


def clip(v, cap=60):
    """A value for display — long help texts cut to one line's worth."""
    text = jv(v)
    return text if len(text) <= cap else text[:cap - 1] + '…'


def key_rank(field):
    """The display order: the lint's canonical row rank, the unknown keys
    after, alphabetical."""
    return (KEY_RANK.index(field), '') if field in KEY_RANK else (len(KEY_RANK), field)


def load(order):
    """The canon + the four registries (raw, whole JSON). A missing file
    or a parse failure exits 1."""
    canon_path = os.path.join(ROOT, 'shared', 'options.json')
    try:
        with open(canon_path, encoding='utf-8') as f:
            canon = json.load(f)
    except (OSError, ValueError) as e:
        print('option_diff.py: shared/options.json: %s' % e)
        raise SystemExit(1)
    raw = {}
    for tool in order:
        path = os.path.join(ROOT, tool, 'lib', 'options.json')
        try:
            with open(path, encoding='utf-8') as f:
                raw[tool] = json.load(f)
        except (OSError, ValueError) as e:
            print('option_diff.py: %s: %s' % (path, e))
            raise SystemExit(1)
    return raw, canon


def folded(raw, canon, order, name, section):
    """The effective row per tool that carries the name in the section
    ({tool: row}); the loader's own fold — a bad ref fails loud here too."""
    rows = {}
    for tool in order:
        for r in raw[tool].get(section) or []:
            if isinstance(r, dict) and r.get('name') == name:
                rows[tool] = canon_fold(r, canon, section, tool)
                break
    return rows


def dev_text(field, block_v, row_v, row):
    """One deviation line's body; the env-free rows (env: null + a no-env
    note) get their own wording — the refusal is the design, not a typo."""
    if field == 'env' and row_v is None and row.get('no-env'):
        return 'env: the block says %s — the row refuses it (no-env: %s)' \
            % (jv(block_v), jv(row['no-env']))
    return '%s: block %s vs row %s' % (field, clip(block_v), clip(row_v))


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

    print('## canon — shared/options.json')
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

    print('## move — what riding shared/options.json takes')
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
                  'lint_options.py: %s' % ', '.join(free))
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


def main():
    args = sys.argv[1:]
    if '-h' in args or '--help' in args:
        print(__doc__.strip())
        return 0
    tool_flag, tools, pending, name = [], [], None, None
    for a in args:
        if pending == '--tool':
            tool_flag.extend(s.strip() for s in a.split(',') if s.strip())
            pending = None
        elif a == '--tool':
            pending = a
        elif a.startswith('--tool='):
            tool_flag.extend(s.strip() for s in a[7:].split(',') if s.strip())
        elif a.startswith('--'):
            print('option_diff.py: unknown flag: %s' % a)
            return 2
        elif name is None:
            name = a
        else:
            print('option_diff.py: one flat name at a time: %r and %r' % (name, a))
            return 2
    if pending:
        print('option_diff.py: --tool needs a tool: %s, or all' % ', '.join(TOOLS))
        return 2
    bad = sorted(set(tool_flag) - set(TOOLS))
    if bad:
        print('option_diff.py: unknown tool: %s (%s, or all)'
              % (', '.join(bad), ', '.join(TOOLS)))
        return 2
    if not name:
        print('option_diff.py: name a flat registry name: '
              'python3 scripts/option_diff.py <flat-name>')
        return 2
    order = [t for t in TOOLS if not tool_flag or t in tool_flag]
    raw, canon = load(order)
    try:
        found = [(s, folded(raw, canon, order, name, s)) for s in SECTIONS]
    except ValueError as e:
        print('option_diff.py: %s' % e)
        return 1
    found = [(s, rows) for s, rows in found if rows]
    if not found:
        print('option_diff.py: no registry rows %r in options, show or '
              'commands (%s)' % (name, ', '.join(order)))
        return 1
    for i, (section, rows) in enumerate(found):
        if i:
            print('')
        report(raw, canon, order, name, section, rows)
    return 0


if __name__ == '__main__':
    sys.exit(main())
