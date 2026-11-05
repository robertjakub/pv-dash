#!/usr/bin/env python3
"""The profile formatter: rewrite profiles/profiles/*.json into the family
shape — the sun2000.json layout: the description first, then the mappings
one entry per line, then one register per line, keys in the family order
(name -> register -> type -> scale -> desc, the extras after). The content
is untouched — names, addresses, types, scales, descs land byte-for-byte as
parsed. Exits 1 when a file is not valid JSON.

  python3 profiles/bin/profile-format.py            # format profiles/profiles/*.json
  python3 profiles/bin/profile-format.py my.json    # format specific files
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KEY_ORDER = ['name', 'register', 'type', 'scale', 'desc']


def fmt_entry(entry, order):
    """One object on one line, keys in the family order, extras after."""
    keys = [k for k in order if k in entry] + [k for k in entry if k not in order]
    return json.dumps({k: entry[k] for k in keys})


def fmt_array(items, order):
    if not items:
        return '[]'
    return '[\n' + ',\n'.join('    ' + fmt_entry(i, order) for i in items) + '\n  ]'


def fmt_profile(data):
    if not isinstance(data, dict):
        return None
    body = []
    if 'description' in data:
        body.append('  "description": %s' % json.dumps(data['description']))
    if 'mappings' in data:
        body.append('  "mappings": %s' % fmt_array(data['mappings'], ['register', 'values']))
    if 'registers' in data:
        body.append('  "registers": %s' % fmt_array(data['registers'], KEY_ORDER))
    for k in data:
        if k not in ('description', 'mappings', 'registers'):
            body.append('  %s: %s' % (json.dumps(k), json.dumps(data[k])))
    return '{\n' + ',\n'.join(body) + '\n}\n'


def main():
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, 'profiles', 'profiles', '*.json')))
    rc = 0
    for path in paths:
        rel = os.path.relpath(path, ROOT)
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
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(new)
        n = len(data.get('registers') or [])
        print('%s: reformatted (%d register%s)' % (rel, n, '' if n == 1 else 's'))
    return rc


if __name__ == '__main__':
    sys.exit(main())
