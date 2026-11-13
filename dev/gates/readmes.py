#!/usr/bin/env python3
"""The READMEs' skeleton gate: the four tool READMEs speak ONE `##` section
order (the one-skeleton wave's canon), and this lint keeps them speaking it.

    python3 dev/gates/readmes.py           # the findings report (the lint verb, the default)
    python3 dev/gates/readmes.py --check   # the gate spelling, rc 1 on any finding

No format verb — the READMEs are hand-wrapped prose, the edits stay human.

The canon — every tool README, in this order:

    How it works -> Usage -> Configuration -> Runtime control
    -> <the tool's own sections> -> Security -> Testing
    -> Source layout -> License

The rules: every canon section present exactly once and in canon order; a
section the canon does not name (the tool's feature/reference sections) is
allowed only in the slot between `Runtime control` and `Security`, any
names, any order; and inside `Runtime control` a `### Signals` block, when
the tool has one, leads the H3s (the cache/scraper/inverter shape).

Report only — the findings name the moves, the edits stay human (the
READMEs are hand-wrapped prose; a mechanical re-order is not worth the hunk
surgery). Run after any README rewrite, beside `check_options.py` (the
flags-mention gate — this one is the order gate). `family_drift.py` prints
the same verdict beside the `##` ladders it reports. Stdlib only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # dev/ — the common lib rides there
from lib import REPO, TOOLS   # the scripts' common lib


CANON = ('How it works', 'Usage', 'Configuration', 'Runtime control',
         'Security', 'Testing', 'Source layout', 'License')

SLOT_AFTER = 'Runtime control'   # the free-name slot opens here...
SLOT_BEFORE = 'Security'         # ...and closes here


def sections(path):
    """The `##` sections as (title, first line number) plus, per section,
    the ordered `###` titles inside it."""
    out, cur = [], None
    with open(path, encoding='utf-8') as f:
        for no, line in enumerate(f, 1):
            if line.startswith('## '):
                cur = {'title': line[3:].strip(), 'line': no, 'h3': []}
                out.append(cur)
            elif line.startswith('### ') and cur is not None:
                cur['h3'].append(line[4:].strip())
    return out


def readme_findings(rel):
    """The findings for one README as message strings (empty = clean)."""
    path = os.path.join(REPO, rel)
    secs = sections(path)
    found = []
    titles = [s['title'] for s in secs]

    # the canon sections: present exactly once, in canon order
    pos = {}
    for want in CANON:
        hits = [i for i, s in enumerate(secs) if s['title'] == want]
        if not hits:
            found.append('the canon section "%s" is missing' % want)
        elif len(hits) > 1:
            found.append('the canon section "%s" appears %d times' % (want, len(hits)))
        else:
            pos[want] = hits[0]
    seen = -1
    for want in CANON:
        if want not in pos:
            continue
        if pos[want] < seen:
            found.append('"%s" sits out of the canon order' % want)
        seen = pos[want]

    # the free-name sections: only in the slot between Runtime control and Security
    open_at = pos.get(SLOT_AFTER)
    close_at = pos.get(SLOT_BEFORE)
    for i, s in enumerate(secs):
        if s['title'] in CANON:
            continue
        if open_at is not None and close_at is not None and open_at < i < close_at:
            continue
        found.append('"%s" sits outside the feature slot (the canon leaves a'
                     ' tool\'s own sections only between "%s" and "%s")'
                     % (s['title'], SLOT_AFTER, SLOT_BEFORE))

    # inside Runtime control, ### Signals (when present) leads the H3s
    if open_at is not None:
        h3 = secs[open_at]['h3']
        if 'Signals' in h3 and h3[0] != 'Signals':
            found.append('the "### Signals" block must lead the H3s inside'
                         ' "Runtime control" (the family shape)')
    return found


def main():
    args = sys.argv[1:]
    if 'format' in args:
        print('usage: no format verb — the READMEs are hand-wrapped prose, the edits stay human')
        return 2
    bad = 0
    for t in TOOLS:
        rel = os.path.join('apps', t, 'README.md')
        for msg in readme_findings(rel):
            bad += 1
            print('readmes: %s: %s' % (rel, msg))
    if bad:
        print('readmes: %d finding(s) across %d READMEs' % (bad, len(TOOLS)))
        return 1
    print('readmes: OK — the %d tool READMEs speak the skeleton' % len(TOOLS))
    return 0


if __name__ == '__main__':
    sys.exit(main())
