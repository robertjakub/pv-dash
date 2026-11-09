#!/usr/bin/env python3
"""The family's static texts, one JSON home (shared/texts.json at the
tree root — the directory that contains common/, the same root in every
layout: the checkout, the installed share/<tool>/ tree, the image's
/pv-suite): the console's faces and reconnect ladder, the ctl's, the welcome
banners, the wire's fixed replies, the daemon bind/startup lines. The
dotted key resolves through the namespaces; the caller applies the
%-format — the format applies only when args ride the call (a template
whose %% must fold always rides args). A literal % inside a template
doubles. The gate is scripts/lint_texts.py: every reference in the tree
resolves, every key is referenced (the orphan gate), no two leaves share
a value. Stdlib only."""
import json
import os

_tree = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(_tree, 'shared', 'texts.json'), encoding='utf-8') as _f:
    TEXTS = json.load(_f)


def T(key, *args):
    """The dotted lookup with the loud miss — the error names the whole
    key, not the segment the walk died on."""
    node = TEXTS
    for part in key.split('.'):
        if not isinstance(node, dict) or part not in node:
            raise KeyError('texts: no such key %r' % key)
        node = node[part]
    return node % args if args else node
