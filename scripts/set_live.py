#!/usr/bin/env python3
"""Set (or clear) an option row's `live` field in a lib/options.json registry.

  python3 scripts/set_live.py <project> <name> <live>

`<project>` is the tool's directory under the repo root — the registry
resolves to <repo root>/<project>/lib/options.json (cache, scraper,
inverter, dashboard); `<name>` is the row's option name (the exact "name"
value, e.g. cache-ttl); `<live>` is the control-grammar name the knob is
set/spelled under on the wire — one clean word-path, no whitespace
(`a/b/c` spells `set a b c <value>`; the check_options gate) — or `-` to
clear it so the knob becomes startup-only (restart required). The edit is
surgical: the file's hand-wrapped formatting outside the touched row is
preserved byte-for-byte. A live RENAME is a wave, not an edit: the
daemon's `_apply`/defaults dispatch keys the flat live name, so the
control.py branches, the dump settings and the suites follow (see
docs/TODO.md's hierarchical item).

Exit 0 = written, 1 = error. Stdlib only."""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from scriptlib import clean_path, row_span   # the shared registry-editing helpers


def main():
    args = sys.argv[1:]
    if len(args) != 3:
        print('usage: set_live.py <project> <name> <live>   (- clears the field)')
        return 1
    project, name, live = args
    path = os.path.join(ROOT, project, 'lib', 'options.json')

    if live != '-' and not clean_path(live):
        print('set_live.py: live must be one clean word-path, got %r' % live)
        return 1

    try:
        text = open(path).read()
    except OSError as e:
        print('set_live.py: %s' % e)
        return 1

    span = row_span(text, name)
    if span is None:
        print('set_live.py: no option named %r in %s' % (name, path))
        return 1
    start, end = span
    row = text[start:end]

    if live == '-':
        was = re.search(r'"live"\s*:\s*"([^"]*)"', row)
        if not was:
            print('set_live.py: %s carries no live field (nothing to clear)' % name)
            return 1
        new_row, n = re.subn(r',?\s*"live"\s*:\s*"[^"]*"', '', row, count=1)
        print('%s: live cleared (was %s)' % (name, was.group(1)))
    elif '"live"' in row:
        was = re.search(r'"live"\s*:\s*"([^"]*)"', row).group(1)
        new_row = re.sub(r'"live"\s*:\s*"[^"]*"', '"live": "%s"' % live, row, count=1)
        if was == live:
            print('%s: live already %s' % (name, live))
            return 0
        print('%s: live %s -> %s' % (name, was, live))
    else:
        pat = r'("group"\s*:\s*"[^"]*")\s*,' if '"group"' in row else r'("conv"\s*:\s*"[^"]*")\s*,'
        new_row, n = re.subn(pat, r'\1, "live": "%s",' % live, row, count=1)
        if not n:
            print('set_live.py: %s has no "conv"/"group" key to anchor the insert' % name)
            return 1
        print('%s: live = %s' % (name, live))

    new_text = text[:start] + new_row + text[end:]
    json.loads(new_text)   # never write what we cannot parse back
    with open(path, 'w') as f:
        f.write(new_text)
    print('changing live for %s to %s in %s' % (name, live, project))
    return 0


if __name__ == '__main__':
    sys.exit(main())
