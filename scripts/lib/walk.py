"""The one tree-walk: every per-tool lib/bin module + every common module,
as (where, relpath, abspath) — `where` is the tool or 'common'. One walk,
one home; the sweeps ride it instead of re-walking. Stdlib only."""
import os

from lib import REPO, TOOLS


def targets():
    out = []
    for t in TOOLS:
        for sub in ('lib', 'bin'):
            d = os.path.join(REPO, 'apps', t, sub)
            for f in sorted(os.listdir(d)):
                if f.endswith('.py'):
                    out.append((t, f'apps/{t}/{sub}/' + f, os.path.join(d, f)))
    d = os.path.join(REPO, 'common')
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        for f in sorted(files):
            if f.endswith('.py'):
                p = os.path.join(root, f)
                out.append(('common', os.path.relpath(p, REPO), p))
    return out
