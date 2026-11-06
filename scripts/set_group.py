#!/usr/bin/env python3
"""Set (or clear) an option row's `group` in a lib/options.json registry.

  python3 scripts/set_group.py <project> <name> <group>

`<project>` is the tool's directory under the repo root — the registry
resolves to <repo root>/<project>/lib/options.json (cache, scraper,
inverter, dashboard); `<name>` is the row's option name (the exact "name"
value, e.g. cache-ttl); `<group>` is the display group — one clean word,
no whitespace (the check_options gate) — or `-` to clear it (the row then
renders ungrouped — bare, no header — on the cli listings). The edit is
surgical: the file's hand-wrapped formatting outside the touched row is
preserved byte-for-byte.

Exit 0 = written, 1 = error. Stdlib only."""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def row_span(text, name):
    """The (start, end) char span of the option object with this name."""
    for m in re.finditer(r'"name"\s*:\s*"(.*?)"', text):
        if m.group(1) != name:
            continue
        brace = text.rfind('{', 0, m.start())
        while brace != -1:
            try:
                obj, end = json.JSONDecoder().raw_decode(text[brace:])
            except ValueError:
                obj, end = None, -1
            if isinstance(obj, dict) and obj.get('name') == name:
                return brace, brace + end
            brace = text.rfind('{', 0, brace)
    return None


def main():
    args = sys.argv[1:]
    if len(args) != 3:
        print('usage: set_group.py <project> <name> <group>   (- clears the group)')
        return 1
    project, name, group = args
    path = os.path.join(ROOT, project, 'lib', 'options.json')

    if group != '-' and (not group or any(c.isspace() for c in group)):
        print('set_group.py: group must be one clean word, got %r' % group)
        return 1

    try:
        text = open(path).read()
    except OSError as e:
        print('set_group.py: %s' % e)
        return 1

    span = row_span(text, name)
    if span is None:
        print('set_group.py: no option named %r in %s' % (name, path))
        return 1
    start, end = span
    row = text[start:end]

    if group == '-':
        new_row, n = re.subn(r',?\s*"group"\s*:\s*"[^"]*"', '', row, count=1)
        if not n:
            print('set_group.py: %s carries no group (nothing to clear)' % name)
            return 1
        was = re.search(r'"group"\s*:\s*"([^"]*)"', row).group(1)
        print('%s: group cleared (was %s)' % (name, was))
    elif '"group"' in row:
        was = re.search(r'"group"\s*:\s*"([^"]*)"', row).group(1)
        new_row = re.sub(r'"group"\s*:\s*"[^"]*"', '"group": "%s"' % group, row, count=1)
        if was == group:
            print('%s: group already %s' % (name, group))
            return 0
        print('%s: group %s -> %s' % (name, was, group))
    else:
        new_row, n = re.subn(r'("conv"\s*:\s*"[^"]*")\s*,',
                             r'\1, "group": "%s",' % group, row, count=1)
        if not n:
            print('set_group.py: %s has no "conv" key to anchor the insert' % name)
            return 1
        print('%s: group = %s' % (name, group))

    new_text = text[:start] + new_row + text[end:]
    json.loads(new_text)   # never write what we cannot parse back
    with open(path, 'w') as f:
        f.write(new_text)
    print('changing group for %s to %s in %s' % (name, group, project))
    return 0


if __name__ == '__main__':
    sys.exit(main())
