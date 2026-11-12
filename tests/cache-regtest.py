#!/usr/bin/env python3
"""The thin wrapper: the real suite lives in tests/suites/cache-regtest.py — the
battery's suite names, the zz_ pgrep copy and the CI legs stay here."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))   # tests/lib — the harness home (run_path prepends the suite's own dir)
runpy.run_path(os.path.join(HERE, 'suites', 'cache-regtest.py'), run_name='__main__')
