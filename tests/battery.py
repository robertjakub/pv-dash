#!/usr/bin/env python3
"""The thin wrapper: the real runner lives in tests/battery/battery.py — the
docs spelling and release.py's call stay here (the runpy twin of the ten
suite wrappers). The status viewer: tests/battery_status.py; the killer:
tests/battery_kill.py."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))   # tests/lib — the harness home (run_path prepends the runner's own dir)
runpy.run_path(os.path.join(HERE, 'battery', 'battery.py'), run_name='__main__')
