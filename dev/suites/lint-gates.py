#!/usr/bin/env python3
"""The lint gates as a suite: the registry and prose lints + the
generators' staleness checks + the drift doc gate — every rc-1-on-red
check the battery had no leg for — under the battery, one check() row
per gate:

  lint/acl.py --check          the acl gate-objects
  lint/options.py --check      the four registries' canonical layout
  lint/readmes.py --check      the tool READMEs' front-page canon
  lint/texts.py                the rendered texts vs texts.json
  lint/profile.py --check      the shared device profiles
  generators/manual.py --check   the five MANUAL pages
  generators/examples.py --check the env + conf examples
  generators/trace_example.py --check  the example trace
  generators/sbom.py --check     the SBOM pair
  family_drift.py --check      the generated drift doc

  python3 dev/suites/lint-gates.py

Checks: ALL PASS (or a FAILURES list; exit 1).
"""
import os
import subprocess
import sys
import time

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'harness'))
from harness import *   # the boot: the gate, the NOTE stamp — the shared check accumulator

GATES = (
    ('lint/acl --check', ('dev/gates/acl.py', '--check')),
    ('lint/options --check', ('dev/gates/options.py', '--check')),
    ('lint/readmes --check', ('dev/gates/readmes.py', '--check')),
    ('lint/texts', ('dev/gates/texts.py',)),
    ('lint/profile --check', ('dev/gates/profile.py', '--check')),
    ('generators/manual --check', ('dev/generators/manual.py', '--check')),
    ('generators/examples --check', ('dev/generators/examples.py', '--check')),
    ('generators/trace_example --check', ('dev/generators/trace_example.py', '--check')),
    ('generators/sbom --check', ('dev/generators/sbom.py', '--check')),
    ('family_drift --check', ('dev/family_drift.py', '--check')),
)

for name, argv in GATES:
    try:
        r = subprocess.run([sys.executable] + list(argv), capture_output=True,
                           text=True, cwd=REPO)
    except OSError as e:
        check('the gate ran (%s)' % name, False, str(e))
        continue
    tail = (r.stdout + r.stderr).strip().splitlines()
    check('the gate ran (%s)' % name, r.returncode == 0,
          'rc %d%s' % (r.returncode, ': ' + '; '.join(tail[-2:]) if r.returncode else ''))

print()
print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
