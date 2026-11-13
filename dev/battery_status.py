#!/usr/bin/env python3
"""The battery's live view, spelled from the dev/ tree root: the one
implementation lives at dev/battery/battery_status.py (the read-only
slot/run view beside the runner — the run ids, the pids, the live check
counts, the --watch loop) and this wrapper is a hand-off, not a copy —
os.execv replaces the process with the real view, so the argv, the exit
codes, the SIGPIPE silence and the Ctrl-C quit are the real one's. Stdlib
only, mode 644 (run via `python3 dev/battery_status.py`, no exec bits),
like the rest of the family."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(HERE, 'battery', 'battery_status.py')

if not os.path.isfile(REAL):
    sys.exit("battery_status: the real view is gone (dev/battery/battery_status.py)")
os.execv(sys.executable, [sys.executable, REAL] + sys.argv[1:])
