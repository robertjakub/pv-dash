#!/usr/bin/env python3
"""The thin wrapper: the real killer lives in tests/battery/battery_kill.py —
the docs spelling stays flat (the runpy twin of the runner and status
wrappers). The slots/slot<N> links under the battery state home name the
live runs."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))   # tests/lib — the harness home (run_path prepends the killer's own dir)
runpy.run_path(os.path.join(HERE, 'battery', 'battery_kill.py'), run_name='__main__')
