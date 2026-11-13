"""The scripts' common lib: the repo-root paths, the flat registry
helpers, the tree-walk (walk.py), the registry loaders (registry.py) and
the emit-and-check doc writer (emit.py) — one home for the plumbing the
scripts re-carried. Stdlib only.

The NAME: the family's per-tool lib/ directories are regular packages
(apps/cache, apps/inverter, apps/scraper carry an __init__.py) and own `lib` wherever a
tool root precedes scripts/ on sys.path — editor.py imports the cache's
lib.config beside the scripts' helpers and opens the house's
one-module-named-`lib`-at-a-time dance around its imports. Everywhere
else scripts/ scans first (a script's own directory is sys.path[0]) and
`import lib` binds THIS package; importing it also puts the repo root on
sys.path (the common/ package and the tools' loaders import from
there)."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO = os.path.dirname(SCRIPTS)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# the four tools, in the chain order the README tells: fake -> cache ->
# scraper, then the dashboard that renders the numbers
TOOLS = ('cache', 'scraper', 'inverter', 'dashboard')


def row_span(text, name):
    """The (start, end) char span of the option object with this name."""
    for m in re.finditer(r'"name"\s*:\s*"(.*?)"', text):
        if m.group(1) != name:
            continue
        brace = text.rfind('{', 0, m.start())
        while brace != -1:
            try:
                obj, end = json.JSONDecoder().raw_decode(text[brace:])
            except ValueError:
                obj, end = None, -1
            if isinstance(obj, dict) and obj.get('name') == name:
                return brace, brace + end
            brace = text.rfind('{', 0, brace)
    return None


def clean_path(text):
    """A live name is one clean word-path: every '/' segment a word."""
    return all(seg and not any(c.isspace() for c in seg) for seg in text.split('/'))
