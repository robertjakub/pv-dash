#!/usr/bin/env python3
"""The READMEs' skeleton gate: the tool READMEs speak the front-page split's
canon (docs/history/front-page-split.md), and this lint keeps them speaking
it.

    python3 dev/gates/readmes.py           # the findings report (the lint verb, the default)
    python3 dev/gates/readmes.py --check   # the gate spelling, rc 1 on any finding

No format verb — the READMEs are hand-wrapped prose, the edits stay human.

The canon — every tool README:

    <the H1 title + the description (the experimental note rides here)>
    -> Usage -> Security -> License

and NOTHING else: the README is the front page (the description, the quick
how-to, the security posture, the license); the tool's reference material —
how it works, the knobs, the signals, the metrics, the audit trail, the
testing — lives in the generated manual (`extras/manuals/<daemon>.md`,
`dev/generators/manual.py --check` gates it), and the README links to it.

The rules: every canon section present exactly once and in canon order;
no other `##` sections; `License` closes the page. Every apps/*/README.md
walks (the sidecar included — the gates glob the tree, not a tools list).

Report only — the findings name the moves, the edits stay human (the
READMEs are hand-wrapped prose; a mechanical re-order is not worth the hunk
surgery). Run after any README rewrite, beside `check_options.py` (the
flags-mention gate — its surface is the manual page now).
`family_drift.py` prints the same verdict beside the `##` ladders it
reports. Stdlib only."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # dev/ — the common lib rides there
from lib import REPO   # the scripts' common lib


CANON = ('Usage', 'Security', 'License')


def sections(path):
    """The `##` sections as (title, first line number)."""
    out = []
    with open(path, encoding='utf-8') as f:
        for no, line in enumerate(f, 1):
            if line.startswith('## '):
                out.append({'title': line[3:].strip(), 'line': no})
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

    # the front-page ruling: no other H2s — the reference material lives in
    # the generated manual
    for i, s in enumerate(secs):
        if s['title'] in CANON:
            continue
        found.append('"%s" is not front-page material (the canon leaves the'
                     ' H2s at Usage/Security/License only — the reference'
                     ' lives in the generated manual)' % s['title'])

    # License closes the page
    if 'License' in pos and pos['License'] != len(secs) - 1:
        found.append('"License" must close the page (the canon order)')
    return found


def main():
    args = sys.argv[1:]
    if 'format' in args:
        print('usage: no format verb — the READMEs are hand-wrapped prose, the edits stay human')
        return 2
    bad = 0
    readmes = sorted(glob.glob(os.path.join(REPO, 'apps', '*', 'README.md')))
    for path in readmes:
        rel = os.path.relpath(path, REPO)
        for msg in readme_findings(rel):
            bad += 1
            print('readmes: %s: %s' % (rel, msg))
    if bad:
        print('readmes: %d finding(s) across %d READMEs' % (bad, len(readmes)))
        return 1
    print('readmes: OK — the %d tool READMEs speak the front page' % len(readmes))
    return 0


if __name__ == '__main__':
    sys.exit(main())
