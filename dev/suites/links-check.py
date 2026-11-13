#!/usr/bin/env python3
"""The docs' link gate as a suite: dev/gates/links.py — every relative
markdown link in the docs resolves, every mdbook include target exists,
every repo-rooted path token in a current doc names something that exists
— under the battery. The gate runs once for the whole family; the
findings list re-emits through the harness check() so the tally reads it
like any suite's.

  python3 dev/suites/links-check.py

Checks: ALL PASS (or a FAILURES list; exit 1).
"""
import os
import subprocess
import sys
import time

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'harness'))
from harness import *   # the boot: the gate, the NOTE stamp — the shared check accumulator

GATE = os.path.join(REPO, 'dev', 'gates', 'links.py')

try:
    r = subprocess.run([sys.executable, GATE, '--check'], capture_output=True, text=True, cwd=REPO)
except OSError as e:
    check('the links gate ran (dev/gates/links.py --check)', False, str(e))
else:
    tail = (r.stdout + r.stderr).strip().splitlines()
    check('the links gate ran (dev/gates/links.py --check)', r.returncode in (0, 1),
          'rc %d' % r.returncode)
    check('every docs link, include and rooted path resolves', r.returncode == 0,
          '; '.join(tail[-3:]))

print()
print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
