#!/usr/bin/env python3
"""The one-knob-one-source gate as a suite: scripts/check_options.py — the
option registry against the four surfaces (the argparse flags, the env twins,
the NixOS module options, the README flag tables), the bundled config's set
lines and the man pages, the control-grammar vocabulary — under the battery.
The gate runs once for the whole family; its own PASS/FAIL rows re-emit
through the harness check(), one row each, so the tally reads them like any
suite's (the gate's detail never prints at the column — a captured FAIL can
never pose as a check row).

  python3 tests/check-options.py

Checks: ALL PASS (or a FAILURES list; exit 1).
"""
import os
import subprocess
import sys
import time

from harness import *   # the boot: the gate, the NOTE stamp — the shared check accumulator

GATE = os.path.join(REPO, 'scripts', 'check_options.py')

try:
    r = subprocess.run([sys.executable, GATE], capture_output=True, text=True, cwd=REPO)
except OSError as e:
    check('the gate ran (scripts/check_options.py)', False, str(e))
else:
    rows = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(('PASS ', 'FAIL '))]
    check('the gate ran (scripts/check_options.py)', r.returncode in (0, 1) and bool(rows),
          'rc %d%s' % (r.returncode, '' if rows else ' — no PASS/FAIL rows in the output'))
    for row in rows:
        check(row[5:], row.startswith('PASS '))

print()
print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
print('\n%s' % ('ALL PASS' if not failures else 'FAILURES: %s' % failures))
sys.exit(1 if failures else 0)
