#!/usr/bin/env python3
"""The thin wrapper: the real viewer lives in tests/battery/battery_status.py —
the docs spelling stays here (the runpy twin of the ten suite wrappers)."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))   # tests/lib — the harness home (run_path prepends the viewer's own dir)
runpy.run_path(os.path.join(HERE, 'battery', 'battery_status.py'), run_name='__main__')
