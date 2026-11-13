#!/usr/bin/env python3
"""The static-texts registry's gate, the options.py shape. The registry
(shared/suite/texts.json at the tree root) must parse; every leaf must be a string; every key
segment must be a clean lowercase word; every reference in the tree must
resolve; every key must be referenced somewhere (the orphan gate); and no
two leaves may share a value (one text, one home).

    python3 scripts/gates/texts.py             # the report (the lint verb, the default)
    python3 scripts/gates/texts.py --check     # the gate spelling, rc 1 on any failure

No format verb — the registry is hand-authored, the edits stay human.

A reference is a bare T call with a single quoted dotted key — the
consumer imports the loader as `from common.render.texts import T`. The suites
and the docs are not scanned: the suites pin the rendered bytes and never
call the loader, the docs quote it. Stdlib only."""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(REPO, 'shared', 'suite', 'texts.json')
SCAN_ROOTS = ['common',
              os.path.join('apps', 'cache', 'bin'), os.path.join('apps', 'cache', 'lib'),
              os.path.join('apps', 'scraper', 'bin'), os.path.join('apps', 'scraper', 'lib'),
              os.path.join('apps', 'inverter', 'bin'), os.path.join('apps', 'inverter', 'lib'),
              os.path.join('apps', 'dashboard', 'bin'), os.path.join('apps', 'dashboard', 'lib'),
              'scripts']
REF = re.compile(r"\bT\('([a-z0-9_.]+)'\)")
SEGMENT = re.compile(r'^[a-z0-9_]+$')


def leaves(node, prefix=''):
    """The flat dotted-key -> template map, with the shape gates on the way."""
    out = {}
    for k, v in node.items():
        if not SEGMENT.match(k):
            raise SystemExit('texts: unclean key segment %r' % k)
        path = '%s.%s' % (prefix, k) if prefix else k
        if isinstance(v, dict):
            out.update(leaves(v, path))
        elif isinstance(v, str):
            out[path] = v
        else:
            raise SystemExit('texts: %s: the leaf is not a string' % path)
    return out


def main():
    args = sys.argv[1:]
    if 'format' in args:
        print('usage: no format verb — the registry is hand-authored, the edits stay human')
        return 2
    try:
        with open(REGISTRY, encoding='utf-8') as f:
            texts = leaves(json.load(f))
    except (OSError, ValueError) as e:
        raise SystemExit('texts: the registry is unreadable: %s' % e)

    refs, files = set(), 0
    for root in SCAN_ROOTS:
        for dirpath, _dirs, names in os.walk(os.path.join(REPO, root)):
            for n in names:
                if not n.endswith('.py'):
                    continue
                files += 1
                with open(os.path.join(dirpath, n), encoding='utf-8') as f:
                    body = f.read()
                refs.update(REF.findall(body))

    bad = []
    unresolved = sorted(r for r in refs if r not in texts)
    if unresolved:
        bad.append('references with no key: %s' % ', '.join(unresolved))
    orphans = sorted(k for k in texts if k not in refs)
    if orphans:
        bad.append('keys nothing references: %s' % ', '.join(orphans))

    by_value = {}
    for k, v in texts.items():
        by_value.setdefault(v, []).append(k)
    dupes = {v: ks for v, ks in by_value.items() if len(ks) > 1}
    for v, ks in sorted(dupes.items()):
        bad.append('one text, two homes: %s <= %s' % (', '.join(ks), v))

    if bad:
        for b in bad:
            print('texts: ' + b)
        return 1
    print('texts: %d key(s), %d reference(s) across %d file(s) — clean'
          % (len(texts), len(refs), files))
    return 0


if __name__ == '__main__':
    sys.exit(main())
