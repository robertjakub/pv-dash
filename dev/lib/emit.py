"""The emit-and-check doc writer: write the rendered page, or under
--check report the drift as a unified diff — one helper, all the
generators on it (the release's --check legs exit 1 when a file moved).
Stdlib only."""
import difflib
import os

from lib import REPO


def read(path):
    """The file's text, or None when missing (the first run has no page)."""
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return None


def emit(path, content, check, tag, rerun=None):
    """Write the file (or, under --check, report the drift). True = the
    file moved — the caller exits 1. `rerun` spells the regeneration
    command (the caller's own invocation path; the dev/ default)."""
    rel = os.path.relpath(path, REPO)
    cur = read(path)
    if cur == content:
        print('%s: %s current' % (tag, rel))
        return False
    if check:
        diff = '\n'.join(difflib.unified_diff((cur or '').splitlines(), content.splitlines(),
                                              'a/' + rel, 'b/' + rel, lineterm=''))
        if diff:
            print(diff)
        print('%s: %s is stale — re-run %s' % (tag, rel, rerun or ('python3 dev/%s.py' % tag)))
        return True
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(content)
    print('%s: wrote %s' % (tag, rel))
    return False
