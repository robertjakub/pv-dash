#!/usr/bin/env python3
"""The profile linter: validate every profiles/profiles/*.json against the
family schema and the shared vocabulary — the shapes the cache/fake/scraper
all trust. Checks: the required keys and their order, the register bounds,
the type width, the fc, the per-entry ttl, the mappings, the duplicate names,
the same-fc overlaps, the terse-ASCII style. Exits 1 when anything is off.

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
            issues.append('%s: unknown "type" %r (i16/u16/i32/u32)' % (label, typ))
            continue
        if typ != typ.strip() or typ not in ('i16', 'u16', 'i32', 'u32'):
            issues.append('%s: odd "type" %r' % (label, typ))
        end = start + width
        if not 0 <= start <= MAX_REGISTERS - width:
            issues.append('%s: registers %d:%d out of range (0..%d)' % (label, start, end, MAX_REGISTERS))
        # fc
        fc = e.get('fc', 3)
        if fc not in (3, 4):
            issues.append('%s: "fc" must be 3 or 4, got %r' % (label, fc))
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
