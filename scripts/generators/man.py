#!/usr/bin/env python3
"""Regenerate the shipped man pages from the tools themselves: every bin is
run with --man (which prints its roff page to stdout via lib/man.py) and the
output lands in the tool's man/<page>.1 — the pages are GENERATED, never
hand-edited. Stdlib only.

  python3 scripts/generators/man.py   # from anywhere; the repo root is derived
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

# (tool, bin relative to the repo root, shipped page relative to the repo root)
TOOLS = (
    ('modbus-cache',         'cache/bin/modbus-cache.py',     'cache/man/modbus-cache.1'),
    ('modbus-cache-cli',     'cache/bin/modbus-cache-cli.py',        'cache/man/modbus-cache-cli.1'),
    ('modbus-fake-inverter', 'inverter/bin/modbus-fake-inverter.py', 'inverter/man/modbus-fake-inverter.1'),
    ('modbus-fake-cli',      'inverter/bin/modbus-fake-cli.py',      'inverter/man/modbus-fake-cli.1'),
    ('modbus-scraper',       'scraper/bin/modbus-scraper.py',  'scraper/man/modbus-scraper.1'),
    ('modbus-scraper-cli',   'scraper/bin/modbus-scraper-cli.py',     'scraper/man/modbus-scraper-cli.1'),
    ('dashboard',            'dashboard/bin/dashboard.py',    'dashboard/man/dashboard.1'),
    ('dashboard-cli',        'dashboard/bin/dashboard-cli.py', 'dashboard/man/dashboard-cli.1'),
)


def main():
    failures = []
    for tool, bin_rel, page_rel in TOOLS:
        run = subprocess.run([sys.executable, os.path.join(ROOT, bin_rel), '--man'],
                             capture_output=True, text=True, cwd=ROOT)
        if run.returncode != 0 or not run.stdout.startswith('.TH '):
            first_err = run.stderr.strip().splitlines()[-1] if run.stderr.strip() \
                else 'no output'
            print('man: %s: FAILED (exit %d): %s' % (tool, run.returncode, first_err))
            failures.append(tool)
            continue
        page = os.path.join(ROOT, page_rel)
        os.makedirs(os.path.dirname(page), exist_ok=True)
        with open(page, 'w') as f:
            f.write(run.stdout)
        print('man: %s -> %s' % (tool, page_rel))
    if failures:
        raise SystemExit('man: %d page(s) failed: %s' % (len(failures), ', '.join(failures)))


if __name__ == '__main__':
    main()
