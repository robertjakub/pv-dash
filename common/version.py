"""The suite version, one line per tool: 0.3.0, or 0.3.0-<short git> when
run from a checkout (the tags update VERSION; the packages carry it)."""
import os
import subprocess

VERSION = '0.3.0'


def version_string():
    v = VERSION
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../common -> the repo root
        rev = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=root,
                             capture_output=True, text=True, timeout=2).stdout.strip()
        if rev:
            v += '-' + rev
    except (OSError, subprocess.SubprocessError):
        pass
    return v
