#!/usr/bin/env python3
"""The hand-written docs' link gate: every relative markdown link in the
docs resolves against the tree, every mdbook `{{#include}}` target
exists, and every repo-rooted path-shaped inline-code token in a CURRENT
doc names something that exists.

    python3 scripts/lint/links.py           # the findings report (the lint verb, the default)
    python3 scripts/lint/links.py --check   # the gate spelling, rc 1 on any finding

The two checks have different homes:

- the LINKS check runs everywhere — a broken link is broken navigation,
  the history records included;
- the TOKEN check runs on the current half only and skips
  docs/history/ and the per-tool TODO.md files — the history records
  keep their landed spellings (the convention since the scripts split).

The generated layer is excluded from both — docs/family-drift.md, the
four <tool>/MANUAL.md pages and docs/sbom/SBOM.md speak their
generators' constants (`scripts/generators/{manual,sbom}.py --check`
are their gates). Fenced code blocks are skipped (the tree diagrams and
the build snippets cite nothing). Run after any docs rewrite, beside
`check_options.py` and `lint/readmes.py` — the links rot the apps/ move
left behind is the class this gate exists for. Stdlib only."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import REPO

LINK = re.compile(r'\[([^\]]*)\]\(([^)\s]+)\)')
INCLUDE = re.compile(r'\{\{#include\s+([^}]+?)\}\}')
SPAN = re.compile(r'`([^`\n]+)`')
ROOTED = re.compile(r'^(apps|docs|shared|common|extras|docker|nixos|scripts|tests)/'
                    r'[A-Za-z0-9][A-Za-z0-9_./-]*$')
GENERATED = ('/MANUAL.md', 'docs/family-drift.md', 'docs/sbom/SBOM.md')
TOKEN_SKIP = ('docs/history/', )
TOKEN_SKIP_FILES = ('CHANGELOG.md', 'docs/docs-redo.md')


def md_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d != '.git']
        for name in filenames:
            if name.endswith('.md'):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def prose_lines(path):
    """The (number, line) pairs outside fenced code blocks."""
    fence = re.compile(r'^\s*(```|~~~)')
    inside = False
    for number, line in enumerate(read_lines(path), 1):
        if fence.match(line):
            inside = not inside
            continue
        if not inside:
            yield number, line


def read_lines(path):
    with open(path, encoding='utf-8') as f:
        return f.readlines()


def resolves(base, target):
    target = target.split('#', 1)[0]
    if not target or re.match(r'^(https?:|mailto:|{{)', target):
        return None
    full = os.path.normpath(os.path.join(base, target))
    return None if os.path.exists(full) else target


def findings():
    rows = []
    for path in md_files():
        rel = os.path.relpath(path, REPO)
        if any(rel.endswith(suffix) or rel == suffix for suffix in GENERATED):
            continue
        base = os.path.dirname(path)
        current_token_file = not any(part in rel for part in TOKEN_SKIP) \
            and not rel.endswith('/TODO.md') \
            and rel not in TOKEN_SKIP_FILES
        for number, line in prose_lines(path):
            for target in INCLUDE.findall(line):
                miss = resolves(base, target.strip())
                if miss:
                    rows.append((rel, number, 'include %s' % miss))
            for target in LINK.findall(line):
                miss = resolves(base, target[1])
                if miss:
                    rows.append((rel, number, 'link %s' % miss))
            if not current_token_file:
                continue
            for span in SPAN.findall(line):
                for word in span.split():
                    word = word.rstrip('.,;:)')
                    if ROOTED.match(word) and not os.path.exists(os.path.join(REPO, word)):
                        rows.append((rel, number, 'path %s' % word))
    return rows


def main():
    check = '--check' in sys.argv[1:]
    rows = findings()
    if not rows:
        print('links: OK — every link, include and rooted path resolves')
        return 0
    seen = set()
    for rel, number, what in rows:
        key = (rel, number, what)
        if key in seen:
            continue
        seen.add(key)
        print('%s:%d: %s misses' % (rel, number, what))
    print('links: %d finding(s) in the docs' % len(seen))
    return 1 if check else 0


if __name__ == '__main__':
    sys.exit(main())
