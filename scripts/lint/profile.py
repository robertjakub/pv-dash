#!/usr/bin/env python3
"""The profiles' linter + formatter, one script beside the other linters
here: lint validates every device profile against the family schema and
the shared vocabulary — the shapes the cache/fake/scraper all trust: the
required keys and their order, the register bounds, the type width, the
fc, the per-entry ttl, the mappings, the write acl tree, the duplicate
names, the same-fc overlaps, the terse-ASCII style. format rewrites
profiles in place into the family shape — the sun2000.json layout: the
description first, then the acl tree, then the mappings one entry per
line, then one register per line, keys in the family order (name ->
register -> type -> scale -> desc, the extras after). The content is
untouched — names, addresses, types, scales, descs land byte-for-byte as
parsed. lint exits 1 when anything is off; format exits 1 when a file is
not valid JSON, and --check/--diff report the layout drift without
touching the files (rc 1 when anything is off-form).

  python3 scripts/lint/profile.py                  # lint profiles/profiles/*.json
  python3 scripts/lint/profile.py my.json          # lint specific files
  python3 scripts/lint/profile.py format my.json   # reformat files in place
  python3 scripts/lint/profile.py format --check   # the drift report only, rc 1 = off-form
  python3 scripts/lint/profile.py format --diff    # the unified diff, no write
"""
import glob
import json
import os
import sys

try:
    from lint._common import diff_dump, fmt_one, grammar, lint_desc, lint_ranges
except ImportError:   # the bare run — the script's own dir is sys.path[0]
    from _common import diff_dump, fmt_one, grammar, lint_desc, lint_ranges

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(REPO, 'apps', 'cache'), REPO):
    sys.path.insert(0, _p)

# `lib` is contested: the cache's own lib/ package (the statics here) and
# the scripts' common lib (lib/) both answer to it — and a process that
# imported a SIBLING lint module first already bound the scripts' lib (the
# import order inside lint/ is free). The same dance acl.py runs: save the
# bound package, fetch the cache's statics while the name is free, bind
# the saved package back.
_lib_saved = sys.modules.pop('lib', None)
for _k in [k for k in sys.modules if k.startswith('lib.')]:
    sys.modules.pop(_k)
from lib.statics import MAX_REGISTERS, REGISTERS_TYPE   # noqa: E402
if _lib_saved is not None:
    sys.modules['lib'] = _lib_saved

KEY_ORDER = ['name', 'register', 'type', 'scale', 'desc']
WIDTHS = {'i16': 1, 'u16': 1, 'i32': 2, 'u32': 2}
WORD_TYPES = ('i16', 'u16', 'i32', 'u32', 'i32swap', 'u32swap', 'f32', 'f32swap')


def lint_matcher(v, where):
    """One rule matcher: the shared range matcher's issues (the spans are
    the acl linter's dead-rule food)."""
    return lint_ranges(v, where, MAX_REGISTERS)[0]


def lint_acl(data, path):
    """The optional "acl" tree: keyed by access kind ("write" is the one
    the cache speaks). The gate is one object: an optional terse-ASCII
    "desc" and the ordered "rules" list — one {"type": "allow"|"deny",
    "range": matcher} object per rule (+ an optional "desc" each). Returns
    the issue list."""
    issues = []
    acl = data.get('acl')
    if not isinstance(acl, dict) or not acl:
        return ['"acl" must be a non-empty object keyed by the access kind']
    for kind, gate in acl.items():
        if kind != 'write':
            issues.append('"acl" kind %r is not known (the cache speaks "write")' % kind)
            continue
        base = '%s acl/write' % os.path.basename(path)
        if not isinstance(gate, dict):
            issues.append('%s must be an object: an optional "desc" and the "rules" list '
                          '(one {"type": "allow"|"deny", "range": ...} per rule)' % base)
            continue
        for k in gate:
            if k not in ('desc', 'rules'):
                issues.append('%s: unknown key %r ("desc" and the "rules" list)' % (base, k))
        issues.extend(lint_desc(gate.get('desc'), base))
        rules = gate.get('rules')
        if not isinstance(rules, list) or not rules:
            issues.append('%s: the "rules" list is missing or empty (a whole-space deny is '
                          '[{"type": "deny", "range": "any"}])' % base)
            continue
        for i, rule in enumerate(rules):
            where = '%s rule %d' % (base, i + 1)
            if not isinstance(rule, dict) or not rule:
                issues.append('%s must be an object with a "type" (allow/deny) and a "range"' % where)
                continue
            for k in rule:
                if k not in ('type', 'range', 'desc'):
                    issues.append('%s: unknown key %r (type/range/desc)' % (where, k))
            verb = rule.get('type')
            if verb not in ('allow', 'deny'):
                issues.append('%s: "type" must be allow or deny, got %r' % (where, verb))
            if 'range' not in rule:
                issues.append('%s: the rule needs a "range"' % where)
            else:
                issues.extend(lint_desc(rule.get('desc'), where))
                issues.extend(lint_matcher(rule['range'], where))
    return issues


def lint(path):
    """Lint one profile; returns (n_entries, issues)."""
    issues = []
    with open(path, encoding='utf-8') as fh:
        try:
            data = json.load(fh)
        except ValueError as e:
            return 0, ['not valid JSON: %s' % e]
    if not isinstance(data, dict):
        return 0, ['the top level must be an object']
    if not str(data.get('description', '')).strip():
        issues.append('"description" is missing or empty')
    entries = data.get('registers')
    if not isinstance(entries, list) or not entries:
        return 0, issues + ['"registers" must be a non-empty list']
    seen = {}      # name -> (fc, start, count)
    spans = []     # (fc, start, end, name)
    for i, e in enumerate(entries):
        where = '%s entry %d' % (os.path.basename(path), i + 1)
        name = e.get('name') if isinstance(e, dict) else None
        label = '%s (%s)' % (where, name) if name else where
        if not isinstance(e, dict):
            issues.append('%s: not an object' % label)
            continue
        # the keys, in the family's order
        keys = [k for k in e if k not in ('mappings',)]
        ordered = [k for k in KEY_ORDER if k in keys]
        rest = [k for k in keys if k not in KEY_ORDER]
        if keys != ordered + rest:
            issues.append('%s: keys not in the family order %s (got %s)'
                          % (label, ', '.join(ordered + rest), ', '.join(keys)))
        # the name: the shared vocabulary, terse ASCII
        if not name or not isinstance(name, str):
            issues.append('%s: "name" is missing' % label)
        elif not name.isascii() or name != name.strip():
            issues.append('%s: "name" is not terse ASCII' % label)
        # the register + the width
        start = e.get('register')
        typ = e.get('type', 'i32')
        if not isinstance(start, int) or isinstance(start, bool):
            issues.append('%s: "register" must be an integer' % label)
            continue
        width = WIDTHS.get(typ) or REGISTERS_TYPE.get(typ)
        if width is None:
            issues.append('%s: unknown "type" %r (i16/u16/i32/u32/i32swap/u32swap/f32/f32swap/bit)'
                          % (label, typ))
            continue
        if typ != typ.strip() or (typ not in WORD_TYPES and typ != 'bit'):
            issues.append('%s: odd "type" %r' % (label, typ))
        end = start + width
        if not 0 <= start <= MAX_REGISTERS - width:
            issues.append('%s: registers %d:%d out of range (0..%d)' % (label, start, end, MAX_REGISTERS))
        # fc: the word types read on FC3/FC4, bit on FC1/FC2 (the type's default)
        fc = e.get('fc', 1 if typ == 'bit' else 3)
        if fc not in ((1, 2) if typ == 'bit' else (3, 4)):
            issues.append('%s: "fc" must be %s, got %r'
                          % (label, '1 or 2 (the bit spaces)' if typ == 'bit' else '3 or 4', fc))
        # ttl
        ttl = e.get('ttl')
        if ttl is not None and (not isinstance(ttl, (int, float)) or isinstance(ttl, bool) or ttl < 0):
            issues.append('%s: "ttl" must be seconds >= 0, got %r' % (label, ttl))
        # desc
        desc = e.get('desc')
        if not isinstance(desc, str) or not desc.strip():
            issues.append('%s: "desc" is missing or empty' % label)
        elif not desc.isascii():
            issues.append('%s: "desc" is not ASCII' % label)
        # mappings: the codes must fit a register word
        for m in e.get('mappings') or []:
            if not isinstance(m, dict) or 'values' not in m:
                issues.append('%s: a "mappings" entry needs "values"' % label)
                continue
            for code, word in m['values'].items():
                if not isinstance(word, int) or isinstance(word, bool) or not 0 <= word <= 65535:
                    issues.append('%s: mapping %r does not fit a register word: %r' % (label, code, word))
        # duplicates + overlaps (per fc)
        if name:
            if name in seen:
                issues.append('%s: duplicate name %r (first at registers %d:%d)'
                              % (label, name, seen[name][1], seen[name][2]))
            else:
                seen[name] = (fc, start, width)
        spans.append((fc, start, end, name or '?'))
        for ofc, ostart, oend, oname in spans[:-1]:
            if ofc == fc and start < oend and ostart < end:
                issues.append('%s (%s): the range overlaps %s (%d:%d)'
                              % (label, name, oname, ostart, oend - ostart))
    if 'acl' in data:
        issues.extend(lint_acl(data, path))
    return len(entries), issues


def cmd_lint(paths):
    n_issues = 0
    for path in paths:
        n, issues = lint(path)
        print('%s: %d entr%s, %d issue(s)' % (os.path.relpath(path, REPO), n,
                                              'y' if n == 1 else 'ies', len(issues)))
        for issue in issues:
            print('  - %s' % issue)
            n_issues += 1
    print('lint: %d profile(s), %d issue(s)' % (len(paths), n_issues))
    return 1 if n_issues else 0


def fmt_array(items, order):
    if not items:
        return '[]'
    return '[\n' + ',\n'.join('    ' + fmt_one(i, order) for i in items) + '\n  ]'


def fmt_gate(gate, depth):
    """The acl gate: the optional desc, then the rule list one rule per
    line (keys in the family order type -> range -> desc); depth = the
    indent level of the gate itself."""
    pad, inner = '  ' * depth, '  ' * (depth + 1)
    keys = [k for k in ('desc', 'rules') if k in gate] \
        + [k for k in gate if k not in ('desc', 'rules')]
    rows = []
    for k in keys:
        if k == 'rules':
            rows.append('%s"rules": %s' % (inner, fmt_rules(gate['rules'], depth + 1)))
        else:
            rows.append('%s%s: %s' % (inner, json.dumps(k), json.dumps(gate[k])))
    return '{\n%s\n%s}' % (',\n'.join(rows), pad)


def fmt_rules(rules, depth):
    """The rule list: one rule per line, a bare [] when empty."""
    if not rules:
        return '[]'
    pad, inner = '  ' * depth, '  ' * (depth + 1)
    rows = ',\n'.join(inner + fmt_one(r, ['type', 'range', 'desc']) for r in rules)
    return '[\n%s\n%s]' % (rows, pad)


def fmt_acl(acl, depth):
    """The acl tree: one access kind per line, the gate rendered by fmt_gate."""
    pad, inner = '  ' * depth, '  ' * (depth + 1)
    rows = ',\n'.join('%s%s: %s' % (inner, json.dumps(k), fmt_gate(v, depth + 1))
                      for k, v in acl.items())
    return '{\n%s\n%s}' % (rows, pad)


def fmt_profile(data):
    if not isinstance(data, dict):
        return None
    body = []
    if 'description' in data:
        body.append('  "description": %s' % json.dumps(data['description']))
    if 'acl' in data:
        body.append('  "acl": %s' % fmt_acl(data['acl'], 1))
    if 'mappings' in data:
        body.append('  "mappings": %s' % fmt_array(data['mappings'], ['register', 'values']))
    if 'registers' in data:
        body.append('  "registers": %s' % fmt_array(data['registers'], KEY_ORDER))
    for k in data:
        if k not in ('description', 'acl', 'mappings', 'registers'):
            body.append('  %s: %s' % (json.dumps(k), json.dumps(data[k])))
    return '{\n' + ',\n'.join(body) + '\n}\n'


def cmd_format(paths, write=True, diff=False):
    """The format verb: rewrite in place (write), the drift report only
    (--check) or the unified diff (--diff) — the flags never touch the
    files, rc 1 when anything is off-form or invalid."""
    rc = 0
    for path in paths:
        rel = os.path.relpath(path, REPO)
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        try:
            data = json.loads(text)
        except ValueError as e:
            print('%s: not valid JSON: %s' % (rel, e))
            rc = 1
            continue
        new = fmt_profile(data)
        if new is None:
            print('%s: the top level must be an object' % rel)
            rc = 1
            continue
        if new == text:
            print('%s: already in shape' % rel)
            continue
        if write:
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(new)
            n = len(data.get('registers') or [])
            print('%s: reformatted (%d register%s)' % (rel, n, '' if n == 1 else 's'))
        else:
            print('%s: off the canonical layout' % rel)
            rc = 1
            if diff:
                diff_dump(text, new, rel)
    return rc


def main():
    mode, check, diff, paths = grammar(sys.argv[1:])
    if mode == 'usage':
        return 2
    paths = paths or sorted(glob.glob(os.path.join(REPO, 'profiles', 'profiles', '*.json')))
    if mode == 'format':
        return cmd_format(paths, write=not check and not diff, diff=diff)
    return cmd_lint(paths)


if __name__ == '__main__':
    sys.exit(main())
