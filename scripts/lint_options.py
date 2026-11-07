#!/usr/bin/env python3
"""Lint and reformat the option registries (lib/options.json, all tools).

One canonical layout, so the hand styles stop diverging:

  - the JSON object's top-level keys keep their original order;
  - the `options` and `show` rows keep their registry order;
  - every row's keys render in the canonical rank (name first, then the
    wire surfaces, the vocabulary, the bounds, the marks — the unknown
    keys after, alphabetical);
  - a row renders on ONE line when it fits in 118 columns, else every
    key on its own continuation line;
  - two-space indent per level, the rows at four, the continuations at
    six, the trailing newline.

The lint (beyond scripts/check_options.py's grammar checks): unknown
keys, missing names/descriptions, duplicate names, and — the big one —
a row that does not read back as the canonical form.

  python3 scripts/lint_options.py             # reformat in place + report
  python3 scripts/lint_options.py --check     # report only, exit 1 if off-form
  python3 scripts/lint_options.py --diff      # show the unified diff, no write
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = ('cache', 'scraper', 'inverter', 'dashboard')
WIDTH = 118

KEY_RANK = ('name', 'flag', 'env', 'conv', 'group', 'live', 'alias', 'negates',
            'setting-help', 'values', 'hint', 'value-help', 'default', 'help',
            'min', 'max', 'check', 'secret', 'internal', 'hidden', 'restart', 'node')
KNOWN = set(KEY_RANK)


def draft_hint(row):
    """The hint the name and the conv suggest — a draft, the human's to
    keep or overwrite. None when nothing honest suggests itself."""
    name = row['name'].lower()
    conv = row.get('conv', 'str')
    if conv == 'bool':
        return None
    if conv == 'int':
        if name.endswith(('-mb', 'mb')):
            return 'MB'
        if 'unit' in name or name.endswith(('-id', 'id')):
            return 'ID'
        if name.startswith(('max-', 'min-')) or any(w in name for w in ('count', 'clients', 'limit', 'port')):
            return 'N'
    if conv == 'float' and '-mb' not in name and any(w in name for w in ('timeout', 'interval', 'delay', 'ttl', 'audit', 'keepalive')):
        return 's'
    if conv == 'str':
        if any(w in name for w in ('upstream', 'listen', 'address', 'host')):
            return 'HOST:PORT'
        if any(w in name for w in ('profile', 'selection', 'path', 'file')):
            return '<file>'
    return None


def draft_setting_help(row):
    """A visible placeholder when the control-help carries no description
    of its own — prose stays the human's, the TODO keeps the gap loud."""
    if row.get('setting-help'):
        return None
    return 'TODO: describe %s for the control help' % (row.get('live') or row['name'])


def draft_value_help(row):
    """A TODO note per completable value, when enough values exist and
    none carry notes yet. Two (on/off) are self-evident; a vocabulary is
    not."""
    vals = row.get('values') or ()
    if not vals or row.get('value-help') or len(vals) < 3:
        return None
    return {w: 'TODO: when does one pick %s?' % w for w in vals}


def proposals(row):
    """The fields this row could draft: [(field, draft, why)] — the
    read-only --propose report's and the editor's prefills' shared
    source. Nothing here writes itself into a registry."""
    out = []
    d = draft_setting_help(row)
    if d:
        out.append(('setting-help', d, 'the control help carries no description'))
    d = draft_hint(row)
    if d and not row.get('hint'):
        out.append(('hint', d, 'the name and the conv suggest the shape'))
    d = draft_value_help(row)
    if d:
        out.append(('value-help', d, 'the completable values lack notes'))
    return out


def render_value(v, head=0):
    """One value: the scalars verbatim JSON, the collections with spaced
    braces/brackets. A collection whose inline form overflows the width
    on its pair's line expands to a hanging indent two past the opening
    brace (head = the characters already on that line)."""
    if isinstance(v, dict) and v:
        items = ['%s: %s' % (json.dumps(k, ensure_ascii=False), render_value(x, head))
                 for k, x in v.items()]
        inline = '{ ' + ', '.join(items) + ' }'
        if head + len(inline) <= WIDTH:
            return inline
        hang = ' ' * (head + 2)
        return '{ ' + (',\n' + hang).join(items) + ' }'
    if isinstance(v, list) and v:
        items = [render_value(x, head) for x in v]
        inline = '[ ' + ', '.join(items) + ' ]'
        if head + len(inline) <= WIDTH:
            return inline
        hang = ' ' * (head + 2)
        return '[ ' + (',\n' + hang).join(items) + ' ]'
    return json.dumps(v, ensure_ascii=False)


def render_pairs(pairs, ind):
    """The body of one row: the key-pairs greedily packed onto lines up to
    WIDTH (a multi-line value packs by its first line), the continuations
    indented two past the row."""
    cont = ind + '  '
    lines, cur = [], ''
    for k, v in pairs:
        key_part = '%s: ' % json.dumps(k, ensure_ascii=False)
        own_head = len(cont) + len(key_part)   # the value's own continuation line
        piece = key_part + render_value(v, own_head)
        cand = (cur + ', ' + piece) if cur else piece
        first = cand.split('\n')[0]
        if cur and len(cont) + len(first) + 2 > WIDTH:
            lines.append(cur)
            cur = piece
        else:
            cur = cand
    lines.append(cur)
    if len(lines) == 1:
        return '%s{ %s }' % (ind, lines[0])
    body = ',\n'.join([ind + '{ ' + lines[0]] + ['%s%s' % (cont, l) for l in lines[1:]])
    return body + ' }'   # the close rides the last pair's line


def render_row(row, ind):
    rank = {k: i for i, k in enumerate(KEY_RANK)}
    keys = sorted(row, key=lambda k: (rank.get(k, len(KEY_RANK)), k))
    return render_pairs([(k, row[k]) for k in keys], ind)


def render_registry(meta):
    """The canonical text of one parsed registry (the row bools normalized
    to the JSON booleans first — see normalize_bools)."""
    normalize_bools(meta)
    parts = []
    for key, rows in meta.items():
        if not isinstance(rows, list):
            parts.append('  %s: %s' % (json.dumps(key, ensure_ascii=False), json.dumps(rows, ensure_ascii=False)))
            continue
        if not rows:
            parts.append('  %s: []' % json.dumps(key, ensure_ascii=False))
            continue
        parts.append('  %s: [\n%s\n  ]' % (json.dumps(key, ensure_ascii=False),
                                           ',\n'.join(render_row(r, '    ') for r in rows)))
    return '{\n' + ',\n'.join(parts) + '\n}\n'


BOOL_KEYS = frozenset(('secret', 'internal', 'hidden', 'restart', 'node'))


def normalize_bools(meta):
    """The row bools to the JSON booleans in place: 'on'/'off' load fine
    (common/options.py as_bool) but the file's canonical form is
    true/false — the render coerces, so --check flags a string-bool row
    and the write mode fixes it."""
    for rows in meta.values():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            for k in BOOL_KEYS:
                if r.get(k) == 'on':
                    r[k] = True
                elif r.get(k) == 'off':
                    r[k] = False


def lint(path):
    """The nits + the canonical text for one registry; (nits, text)."""
    nits = []
    with open(path, encoding='utf-8') as f:
        text = f.read()
    try:
        meta = json.loads(text)
    except ValueError as e:
        return ['%s: does not parse: %s' % (path, e)], None
    names = set()
    for key, rows in meta.items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                nits.append('%s: %s: a row that is not an object' % (path, key))
                continue
            if 'name' not in r:
                nits.append('%s: %s: a row without a name' % (path, key))
            elif r['name'] in names:
                nits.append('%s: %s: the name %r repeats' % (path, key, r['name']))
            else:
                names.add(r['name'])
            unknown = sorted(set(r) - KNOWN)
            if unknown:
                nits.append('%s: %s: unknown key(s) %s' % (path, key, ', '.join(unknown)))
            if key == 'show' and not r.get('setting-help'):
                nits.append('%s: show: %r carries no description' % (path, r.get('name')))

    # the namespace discipline: a knob's '/'-prefix with no node row is an
    # implicit namespace the wire's show cannot describe — the canonical
    # text gains the node row (the path-named, no-live spelling: no
    # Setting, so set never reaches it; a TODO setting-help the prose
    # fills); a node row with no live children at all — even hidden count
    # — is an orphan: the nit asks to remove it
    rows = meta.get('options') or []
    lives = [r['live'] for r in rows if isinstance(r, dict) and r.get('live')]
    node_paths = {r['name'] for r in rows if isinstance(r, dict) and r.get('node')}
    show_lives = {(r.get('live') or r['name']) for r in meta.get('show') or []
                  if isinstance(r, dict)}
    prefixes = set()
    for lv in lives:
        segs = lv.split('/')
        for i in range(1, len(segs)):
            prefixes.add('/'.join(segs[:i]))
    missing = sorted(p for p in prefixes
                     if p not in node_paths and p not in lives and p not in show_lives)
    all_names = {r['name'] for r in rows if isinstance(r, dict)}
    orphans = sorted(n for n in node_paths
                     if not any(lv.startswith(n + '/') for lv in lives))
    for n in orphans:
        nits.append('%s: the node %r has no live children (even hidden count) — remove it' % (path, n))
    for p in missing:
        if p in all_names:
            # the node's name must be its path (the prefix tests key on it) —
            # a knob squatting the name blocks the file: the human calls it
            nits.append('%s: the namespace %r has no node row and the name is taken by a knob — '
                        'rename the knob or file the node by hand' % (path, p))
            continue
        i = next(i for i, r in enumerate(rows)
                 if isinstance(r, dict) and r.get('live') and r['live'].startswith(p + '/'))
        rows.insert(i, {'name': p, 'setting-help': 'TODO: describe %s for the control help' % p,
                        'node': True})

    if nits:
        return nits, None
    canon = render_registry(meta)
    if canon != text:
        nits.append('%s: off the canonical layout' % path)
    return nits, canon


def main():
    check, diff, propose = ('--check' in sys.argv[1:], '--diff' in sys.argv[1:],
                            '--propose' in sys.argv[1:])
    write = not check and not diff and not propose
    if propose:
        for tool in TOOLS:
            path = os.path.join(REPO, tool, 'lib', 'options.json')
            try:
                meta = json.load(open(path, encoding='utf-8'))
            except ValueError as e:
                print('%s: does not parse: %s' % (path, e))
                continue
            for key in meta:
                if not isinstance(meta[key], list):
                    continue
                for r in meta[key]:
                    for field, draft, why in proposals(r):
                        print('%s %s/%s: %s — propose %s\n    %s' %
                              (tool, key, r['name'], why, field,
                               json.dumps(draft, ensure_ascii=False)))
        return 0
    bad = False
    for tool in TOOLS:
        path = os.path.join(REPO, tool, 'lib', 'options.json')
        nits, canon = lint(path)
        for nit in [n for n in nits if 'canonical' not in n]:
            print(nit)
            bad = True
        if canon is None:
            bad = True
            continue
        disk = open(path, encoding='utf-8').read()
        if canon == disk:
            continue
        if write:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(canon)
            print('%s: reformatted' % path)
        else:
            print('%s: off the canonical layout' % path)
            bad = True
            if diff:
                import difflib
                sys.stdout.writelines(difflib.unified_diff(
                    disk.splitlines(True), canon.splitlines(True),
                    path, path + ' (canonical)'))
    if bad:
        sys.exit(1)
    print('lint: all four registries clean and canonical')


if __name__ == '__main__':
    main()
