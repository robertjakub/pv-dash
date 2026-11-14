"""The registry loaders: the raw lib/options.json read, the wired
lib/options.py rows (the one-module-named-`options`-at-a-time import
dance) and the canon fold through the loader's own implementation — one
home for the parse block the gates, the generators and the sweeps
re-carried. Stdlib only."""
import json
import os
import sys

from lib import REPO

# tool -> (bin script, nixos module, manual page, bundled config) — the
# per-tool surfaces the gates check the registry against (the tool dir
# IS the key; the fake answers no NixOS module). The third element is the
# GENERATED manual page (extras/manuals/, dev/generators/manual.py) — the
# front-page split moved the flags reference out of the READMEs (the
# readmes.py gate pins the front-page canon)
SURFACES = {
    'cache': ('apps/cache/bin/modbus-cache.py', 'nixos/modules/modbus-cache.nix',
              'extras/manuals/modbus-cache.md', 'apps/cache/examples/modbus-cache.conf'),
    'scraper': ('apps/scraper/bin/modbus-scraper.py', 'nixos/modules/modbus-scraper.nix',
                'extras/manuals/modbus-scraper.md', 'apps/scraper/examples/modbus-scraper.conf'),
    'inverter': ('apps/inverter/bin/modbus-fake-inverter.py', None,
                 'extras/manuals/fake-inverter.md', 'apps/inverter/examples/modbus-fake-inverter.conf'),
    'dashboard': ('apps/dashboard/bin/dashboard.py', 'nixos/modules/dashboard.nix',
                  'extras/manuals/dashboard.md', 'apps/dashboard/examples/dashboard.conf'),
}


def raw(tool_dir):
    """The raw lib/options.json rows — the sections' row order and the raw
    marks (the loaders key by live word and drop the node rows; some
    surfaces want both)."""
    with open(os.path.join(REPO, 'apps', tool_dir, 'lib', 'options.json'), encoding='utf-8') as f:
        return json.load(f)


def wired(tool_dir):
    """The tool's wired rows: the import dance, one module named `options`
    at a time — returns (OPTIONS, KNOWN_VERBS, SHOW_OPTIONS, mod); the
    module rides for the surfaces beyond the trio (the SHOW_WORDS
    vocabulary)."""
    sys.path.insert(0, os.path.join(REPO, 'apps', tool_dir, 'lib'))
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
