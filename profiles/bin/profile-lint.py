#!/usr/bin/env python3
"""The profile linter: validate every profiles/profiles/*.json against the
family schema and the shared vocabulary — the shapes the cache/fake/scraper
all trust. Checks: the required keys and their order, the register bounds,
the type width, the fc, the per-entry ttl, the mappings, the write acl
tree, the duplicate names, the same-fc overlaps, the terse-ASCII style.
Exits 1 when anything is off.

  python3 profiles/bin/profile-lint.py            # lint profiles/profiles/*.json
  python3 profiles/bin/profile-lint.py my.json    # lint specific files
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'cache'))

from lib.statics import MAX_REGISTERS, REGISTER_TYPES   # noqa: E402

KEY_ORDER = ['name', 'register', 'type', 'scale', 'desc']
WIDTHS = {'i16': 1, 'u16': 1, 'i32': 2, 'u32': 2}
WORD_TYPES = ('i16', 'u16', 'i32', 'u32', 'i32swap', 'u32swap', 'f32', 'f32swap')


def lint_matcher(v, where):
    """One rule matcher: 'any'/'none', START:COUNT (a string, a list or a
    {"START:COUNT": "desc"} map)."""
    issues = []
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ('any', 'none'):
            return issues
        items = [t]
    elif isinstance(v, dict):
        for k, d in v.items():
            t = str(k).strip().lower()
            if t in ('any', 'none'):
                continue
            try:
                start, count = (int(x) for x in t.split(':'))
            except ValueError:
                issues.append('%s: %r must be START:COUNT' % (where, k))
                continue
            if start < 0 or count < 1 or start + count > MAX_REGISTERS:
                issues.append('%s: range %d:%d out of bounds (0..%d)'
                              % (where, start, count, MAX_REGISTERS - 1))
            if not isinstance(d, str) or not d.strip() or not d.isascii():
                issues.append("%s entry %r: the description must be terse ASCII" % (where, k))
        return issues
    elif isinstance(v, list):
        items = v
    else:
        return ['%s must be a range, a list of ranges, a {"START:COUNT": "desc"} map, '
                '"any" or "none"' % where]
    for x in items:
        if not isinstance(x, str) or x.strip().lower() in ('any', 'none'):
            issues.append('%s: %r must be START:COUNT (the words any/none stand alone)'
                          % (where, x))
            continue
        try:
            start, count = (int(t) for t in x.strip().lower().split(':'))
        except ValueError:
            issues.append('%s: %r must be START:COUNT' % (where, x))
            continue
        if start < 0 or count < 1 or start + count > MAX_REGISTERS:
            issues.append('%s: range %d:%d out of bounds (0..%d)'
                          % (where, start, count, MAX_REGISTERS - 1))
    return issues


def lint_desc(d, where):
    if d is not None and (not isinstance(d, str) or not d.strip() or not d.isascii()):
        return ['%s: "desc" must be terse ASCII' % where]
    return []


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
        width = WIDTHS.get(typ) or REGISTER_TYPES.get(typ)
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


def main():
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, 'profiles', 'profiles', '*.json')))
    n_issues = 0
    for path in paths:
        n, issues = lint(path)
        print('%s: %d entr%s, %d issue(s)' % (os.path.relpath(path, ROOT), n,
                                              'y' if n == 1 else 'ies', len(issues)))
        for issue in issues:
            print('  - %s' % issue)
            n_issues += 1
    print('lint: %d profile(s), %d issue(s)' % (len(paths), n_issues))
    return 1 if n_issues else 0


if __name__ == '__main__':
    sys.exit(main())
