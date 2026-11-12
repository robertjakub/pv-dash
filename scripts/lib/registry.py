"""The registry loaders: the raw lib/options.json read, the wired
lib/options.py rows (the one-module-named-`options`-at-a-time import
dance) and the canon fold through the loader's own implementation — one
home for the parse block the gates, the generators and the sweeps
re-carried. Stdlib only."""
import json
import os
import sys

from lib import REPO

# tool -> (bin script, nixos module, README, bundled config) — the
# per-tool surfaces the gates check the registry against (the tool dir
# IS the key; the fake answers no NixOS module)
SURFACES = {
    'cache': ('cache/bin/modbus-cache.py', 'nixos/modules/modbus-cache.nix',
              'cache/README.md', 'cache/examples/modbus-cache.conf'),
    'scraper': ('scraper/bin/modbus-scraper.py', 'nixos/modules/modbus-scraper.nix',
                'scraper/README.md', 'scraper/examples/modbus-scraper.conf'),
    'inverter': ('inverter/bin/modbus-fake-inverter.py', None,
                 'inverter/README.md', 'inverter/examples/modbus-fake-inverter.conf'),
    'dashboard': ('dashboard/bin/dashboard.py', 'nixos/modules/dashboard.nix',
                  'dashboard/README.md', 'dashboard/examples/dashboard.conf'),
}


def raw(tool_dir):
    """The raw lib/options.json rows — the sections' row order and the raw
    marks (the loaders key by live word and drop the node rows; some
    surfaces want both)."""
    with open(os.path.join(REPO, tool_dir, 'lib', 'options.json'), encoding='utf-8') as f:
        return json.load(f)


def wired(tool_dir):
    """The tool's wired rows: the import dance, one module named `options`
    at a time — returns (OPTIONS, KNOWN_VERBS, SHOW_OPTIONS, mod); the
    module rides for the surfaces beyond the trio (the SHOW_WORDS
    vocabulary)."""
    sys.path.insert(0, os.path.join(REPO, tool_dir, 'lib'))
    sys.modules.pop('options', None)
    mod = __import__('options')
    sys.path.pop(0)
    out = (mod.OPTIONS, mod.KNOWN_VERBS, getattr(mod, 'SHOW_OPTIONS', ()), mod)
    sys.modules.pop('options', None)
    return out


def folded(tool_dir, section='options', meta=None):
    """The section's raw rows through the loader's own canon_fold (the
    row's inline field wins over its shared block). `meta` passes an
    already-read registry so the callers composing several sections read
    the file once."""
    from common.settings.options import canon_fold, load_canon
    canon = load_canon()
    if meta is None:
        meta = raw(tool_dir)
    return [canon_fold(r, canon, section, tool_dir) for r in meta.get(section) or []]
