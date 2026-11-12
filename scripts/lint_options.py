#!/usr/bin/env python3
"""Lint and reformat the option registries (lib/options.json, all tools).

One canonical layout, so the hand styles stop diverging:

  - the JSON object's top-level keys keep their original order;
  - the `options` and `show` rows keep their registry order;
  - every row's keys render in the canonical rank (name first, then the
    wire surfaces, the vocabulary, the bounds, the marks — the unknown
    keys after, alphabetical);
  - a row renders on ONE line when it fits in 118 columns, else every
    key on its own continuation line;
  - two-space indent per level, the rows at four, the continuations at
    six, the trailing newline.

The lint (beyond scripts/check_options.py's grammar checks): unknown
keys, missing names/descriptions, duplicate names, the `only` mark —
a known tool, the file's own tool, never beside `shared` (the canon
ref is the family-wide mark; `only` pins the knob tool-exclusive) —
and — the big one — a row that does not read back as the canonical
form. The shared/options-help.json is the fifth file under the gate: a
block may carry every row key but the three placement keys (`name` —
the flat name IS the block's key; `only`; `shared` — the ref itself),
no unknown keys, a show/commands dict block speaks its section's
description field, and the file itself renders in the canonical layout
(the sections and blocks in their landed order, a block's fields in the
row rank).

  python3 scripts/lint_options.py             # reformat in place + report
  python3 scripts/lint_options.py --check     # report only, exit 1 if off-form
  python3 scripts/lint_options.py --diff      # show the unified diff, no write
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scriptlib import TOOLS

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)   # the canon fold rides the loader's own implementation
WIDTH = 118

KEY_RANK = ('name', 'flag', 'env', 'no-env', 'conv', 'shared', 'only', 'group', 'live', 'alias', 'negates',
            'setting-help', 'values', 'hint', 'value-help', 'default', 'help',
            'min', 'max', 'check', 'secret', 'internal', 'hidden', 'restart', 'node')
KNOWN = set(KEY_RANK)

# the help-canon wave: the gated fields (what the knob SAYS + what the knob
# IS) the family passes compare, and the (section, name, field) exemptions —
# the intentional drift, each with its reason
GATED = ('setting-help', 'help', 'value-help', 'hint', 'values',
         'flag', 'env', 'min', 'max', 'secret', 'hidden', 'restart')
SECTION_FIELD = {'show': 'setting-help', 'commands': 'help'}

EXEMPT = {
    ('commands', 'inspect'): ('help',),  # the tool's own dump contents
    ('commands', 'request'): ('help',),  # the tool's own verb list
    ('commands', 'request-dump'): ('help',),  # the daemon vs the fake noun
    ('commands', 'request-reload'): ('help',),  # the reload's per-tool resolution note
    ('commands', 'request-reload-config'): ('help',),  # the fake's values re-apply note
    ('commands', 'request-restart'): ('help',),  # the upstream restart vs the session drop
    ('commands', 'request-restore'): ('help',),  # the daemon vs the fake noun
    ('commands', 'show'): ('help',),  # the cache's report list
    ('options', 'allow-write'): ('help', 'setting-help', 'value-help',),  # the cache forwards, the fake accepts
    ('options', 'auth-token'): ('help', 'setting-help',),  # the endpoints differ
    ('options', 'connect-acl'): ('help', 'setting-help', 'value-help',),  # the mirror wording stays local (the hint/values aligned)
    ('options', 'control'): ('setting-help',),  # the cache's control plane names the target first
    ('options', 'control-log-replies'): ('env',),  # the dashboard's env twin; the daemons read none
    ('options', 'control-ops-token'): ('help', 'setting-help',),  # the cache's show,flush policy
    ('options', 'control-port'): ('help', 'setting-help',),  # the inverter's unix-only wording; the helps carry the tool's ctl name
    ('options', 'control-socket-group'): ('help', 'setting-help',),  # the fake's why-tail
    ('options', 'control-trust-uids'): ('help', 'setting-help',),  # the fake's env note tail
    ('options', 'control/ops'): ('setting-help',),  # the cache's ops role names the second token
    ('options', 'dump'): ('setting-help',),  # the cache's dump words (the cached knobs' prose names the cache)
    ('options', 'dump-interval'): ('setting-help',),  # the cache's dump words
    ('options', 'dump-key'): ('help', 'setting-help',),  # the cache's dump words; the scraper's semicolon fixed via the block
    ('options', 'dump-path'): ('help', 'setting-help',),  # the cache's dump words
    ('options', 'local-time'): ('env',),  # the fake reads no env twin
    ('options', 'log-access'): ('env', 'help', 'setting-help', 'value-help',),  # connects/disconnects vs HTTP requests
    ('options', 'log-level'): ('help', 'value-help',),  # the DEBUG detail differs per tool
    ('options', 'max-kwp'): ('help', 'setting-help',),  # the cap vs the simulation prose (the hint aligned to kW)
    ('options', 'metrics'): ('setting-help',),  # the per-tool /metrics prose
    ('options', 'metrics-client-timeout'): ('env',),  # the fake reads no env twin
    ('options', 'metrics-listen'): ('env', 'help', 'setting-help',),  # the cache's reload note; the fake reads no env twin
    ('options', 'metrics-max-clients'): ('env',),  # the fake reads no env twin
    ('options', 'metrics-max-conn-per-ip'): ('env',),  # the fake reads no env twin
    ('options', 'metrics-token'): ('help',),  # the dashboard's F13 bind note stays inline
    ('options', 'metrics-server'): ('env',),  # the fake reads no env twin
    ('options', 'metrics/limits'): ('setting-help',),  # the caps prose differs per side
    ('options', 'modbus'): ('setting-help',),  # the session side differs (client upstream vs served fake)
    ('options', 'modbus-auth-key'): ('help', 'setting-help',),  # the key's audience differs (the cache's clients vs the handshake)
    ('options', 'modbus-merge-gap'): ('max', 'setting-help',),  # the register spaces differ (the max 100 vs 125 too)
    ('options', 'system'): ('setting-help',),  # the socket's per-tool purpose
    ('options', 'upstream'): ('env', 'help', 'hint', 'setting-help',),  # the Modbus upstream vs the Prometheus URL
    ('options', 'write'): ('setting-help',),  # the write gates differ per side
    ('show', 'connections'): ('setting-help',),  # the per-tool clients (Modbus peers vs HTTP vs pages)
}


def draft_hint(row):
    """The hint the name and the conv suggest — a draft, the human's to
    keep or overwrite. None when nothing honest suggests itself."""
    name = row['name'].lower()
    conv = row.get('conv', 'str')
    if conv == 'bool':
        return None
    if conv == 'int':
        if name.endswith(('-mb', 'mb')):
            return 'MB'
        if 'unit' in name or name.endswith(('-id', 'id')):
            return 'ID'
        if name.startswith(('max-', 'min-')) or any(w in name for w in ('count', 'clients', 'limit', 'port')):
            return 'N'
    if conv == 'float' and '-mb' not in name and any(w in name for w in ('timeout', 'interval', 'delay', 'ttl', 'audit', 'keepalive')):
        return 's'
    if conv == 'str':
        if any(w in name for w in ('upstream', 'listen', 'address', 'host')):
            return 'HOST:PORT'
        if any(w in name for w in ('profile', 'selection', 'path', 'file')):
            return '<file>'
    return None


def draft_setting_help(row):
    """A visible placeholder when the control-help carries no description
    of its own — prose stays the human's, the TODO keeps the gap loud."""
    if row.get('setting-help'):
        return None
    return 'TODO: describe %s for the control help' % (row.get('live') or row['name'])


def draft_value_help(row):
    """A TODO note per completable value, when enough values exist and
    none carry notes yet. Two (on/off) are self-evident; a vocabulary is
    not."""
    vals = row.get('values') or ()
    if not vals or row.get('value-help') or len(vals) < 3:
        return None
    return {w: 'TODO: when does one pick %s?' % w for w in vals}


def draft_shared(row, canon):
    """The canon key the row's prose already spells: the options block whose
    setting-help or help byte-matches the row's. The flip's mechanical
    helper — the editor's p walk offers it one Enter at a time. None when
    the row refs already, is a node, or speaks its own prose everywhere."""
    if not canon or row.get('shared') or row.get('node'):
        return None
    for key, block in (canon.get('options') or {}).items():
        if not isinstance(block, dict):
            continue
        for f in ('setting-help', 'help'):
            if row.get(f) and block.get(f) == row[f]:
                return key
    return None


def proposals(row, canon=None):
    """The fields this row could draft: [(field, draft, why)] — the
    read-only --propose report's and the editor's prefills' shared
    source. Nothing here writes itself into a registry."""
    out = []
    d = draft_setting_help(row)
    if d:
        out.append(('setting-help', d, 'the control help carries no description'))
    d = draft_hint(row)
    if d and not row.get('hint'):
        out.append(('hint', d, 'the name and the conv suggest the shape'))
    d = draft_value_help(row)
    if d:
        out.append(('value-help', d, 'the completable values lack notes'))
    d = draft_shared(row, canon)
    if d:
        out.append(('shared', d, "the row's prose rides the canon block %s" % d))
    return out


def render_value(v, head=0):
    """One value: the scalars verbatim JSON, the collections with spaced
    braces/brackets. A collection whose inline form overflows the width
    on its pair's line expands to a hanging indent two past the opening
    brace (head = the characters already on that line)."""
    if isinstance(v, dict) and v:
        items = ['%s: %s' % (json.dumps(k, ensure_ascii=False), render_value(x, head))
                 for k, x in v.items()]
        inline = '{ ' + ', '.join(items) + ' }'
        if head + len(inline) <= WIDTH:
            return inline
        hang = ' ' * (head + 2)
        return '{ ' + (',\n' + hang).join(items) + ' }'
    if isinstance(v, list) and v:
        items = [render_value(x, head) for x in v]
        inline = '[ ' + ', '.join(items) + ' ]'
        if head + len(inline) <= WIDTH:
            return inline
        hang = ' ' * (head + 2)
        return '[ ' + (',\n' + hang).join(items) + ' ]'
    return json.dumps(v, ensure_ascii=False)


def render_pairs(pairs, ind):
    """The body of one row: the key-pairs greedily packed onto lines up to
    WIDTH (a multi-line value packs by its first line), the continuations
    indented two past the row."""
    cont = ind + '  '
    lines, cur = [], ''
    for k, v in pairs:
        key_part = '%s: ' % json.dumps(k, ensure_ascii=False)
        own_head = len(cont) + len(key_part)   # the value's own continuation line
        piece = key_part + render_value(v, own_head)
        cand = (cur + ', ' + piece) if cur else piece
        first = cand.split('\n')[0]
        if cur and len(cont) + len(first) + 2 > WIDTH:
            lines.append(cur)
            cur = piece
        else:
            cur = cand
    lines.append(cur)
    if len(lines) == 1:
        return '%s{ %s }' % (ind, lines[0])
    body = ',\n'.join([ind + '{ ' + lines[0]] + ['%s%s' % (cont, l) for l in lines[1:]])
    return body + ' }'   # the close rides the last pair's line


def render_row(row, ind):
    rank = {k: i for i, k in enumerate(KEY_RANK)}
    keys = sorted(row, key=lambda k: (rank.get(k, len(KEY_RANK)), k))
    return render_pairs([(k, row[k]) for k in keys], ind)


def render_registry(meta):
    """The canonical text of one parsed registry (the row bools normalized
    to the JSON booleans first — see normalize_bools)."""
    normalize_bools(meta)
    parts = []
    for key, rows in meta.items():
        if not isinstance(rows, list):
            parts.append('  %s: %s' % (json.dumps(key, ensure_ascii=False), json.dumps(rows, ensure_ascii=False)))
            continue
        if not rows:
            parts.append('  %s: []' % json.dumps(key, ensure_ascii=False))
            continue
        parts.append('  %s: [\n%s\n  ]' % (json.dumps(key, ensure_ascii=False),
                                           ',\n'.join(render_row(r, '    ') for r in rows)))
    return '{\n' + ',\n'.join(parts) + '\n}\n'


BOOL_KEYS = frozenset(('secret', 'internal', 'hidden', 'restart', 'node'))


def normalize_bools(meta):
    """The row bools to the JSON booleans in place: 'on'/'off' load fine
    (common/settings/options.py as_bool) but the file's canonical form is
    true/false — the render coerces, so --check flags a string-bool row
    and the write mode fixes it."""
    for rows in meta.values():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            _norm_row_bools(r)


def _norm_row_bools(r):
    for k in BOOL_KEYS:
        if r.get(k) == 'on':
            r[k] = True
        elif r.get(k) == 'off':
            r[k] = False


def render_canon(canon):
    """The canonical text of shared/options-help.json — the registries' one
    render, one shape up: the file's sections and blocks keep their landed
    order (the orphan gate keys on it), a dict block's fields render in the
    row rank (the block bools normalized — the flat show/commands strings
    render bare), two-space indent per level, the trailing newline."""
    out = {}
    for section, blocks in canon.items():
        out_blocks = {}
        for key, block in blocks.items():
            if isinstance(block, dict):
                _norm_row_bools(block)
                rank = {k: i for i, k in enumerate(KEY_RANK)}
                block = {k: block[k] for k in sorted(block, key=lambda k: rank.get(k, len(KEY_RANK)))}
            out_blocks[key] = block
        out[section] = out_blocks
    return json.dumps(out, ensure_ascii=False, indent=2) + '\n'


def lint(path):
    """The nits + the canonical text for one registry; (nits, text)."""
    nits = []
    with open(path, encoding='utf-8') as f:
        text = f.read()
    try:
        meta = json.loads(text)
    except ValueError as e:
        return ['%s: does not parse: %s' % (path, e)], None
    names = set()
    for key, rows in meta.items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                nits.append('%s: %s: a row that is not an object' % (path, key))
                continue
            if 'name' not in r:
                nits.append('%s: %s: a row without a name' % (path, key))
            elif r['name'] in names:
                nits.append('%s: %s: the name %r repeats' % (path, key, r['name']))
            else:
                names.add(r['name'])
            unknown = sorted(set(r) - KNOWN)
            if unknown:
                nits.append('%s: %s: unknown key(s) %s' % (path, key, ', '.join(unknown)))
            if 'only' in r:
                own_tool = path.split(os.sep)[-3]
                only = r['only']
                if only not in TOOLS:
                    nits.append('%s: %s: the only mark %r is not one of %s'
                                % (path, key, only, ', '.join(TOOLS)))
                elif only != own_tool:
                    nits.append('%s: %s: the only mark %r names another tool\'s registry'
                                % (path, key, only))
                if r.get('shared'):
                    nits.append('%s: %s: %r carries only and shared — the canon ref is the '
                                'family-wide mark, pick one' % (path, key, r.get('name')))
            if key == 'show' and not r.get('setting-help') and not r.get('shared'):
                nits.append('%s: show: %r carries no description' % (path, r.get('name')))

    # the namespace discipline: a knob's '/'-prefix with no node row is an
    # implicit namespace the wire's show cannot describe — the canonical
    # text gains the node row (the path-named, no-live spelling: no
    # Setting, so set never reaches it; a TODO setting-help the prose
    # fills); a node row with no live children at all — even hidden count
    # — is an orphan: the nit asks to remove it
    rows = meta.get('options') or []
    lives = [r['live'] for r in rows if isinstance(r, dict) and r.get('live')]
    node_paths = {r['name'] for r in rows if isinstance(r, dict) and r.get('node')}
    show_lives = {(r.get('live') or r['name']) for r in meta.get('show') or []
                  if isinstance(r, dict)}
    prefixes = set()
    for lv in lives:
        segs = lv.split('/')
        for i in range(1, len(segs)):
            prefixes.add('/'.join(segs[:i]))
    missing = sorted(p for p in prefixes
                     if p not in node_paths and p not in lives and p not in show_lives)
    all_names = {r['name'] for r in rows if isinstance(r, dict)}
    orphans = sorted(n for n in node_paths
                     if not any(lv.startswith(n + '/') for lv in lives))
    for n in orphans:
        nits.append('%s: the node %r has no live children (even hidden count) — remove it' % (path, n))
    for p in missing:
        if p in all_names:
            # the node's name must be its path (the prefix tests key on it) —
            # a knob squatting the name blocks the file: the human calls it
            nits.append('%s: the namespace %r has no node row and the name is taken by a knob — '
                        'rename the knob or file the node by hand' % (path, p))
            continue
        i = next(i for i, r in enumerate(rows)
                 if isinstance(r, dict) and r.get('live') and r['live'].startswith(p + '/'))
        rows.insert(i, {'name': p, 'setting-help': 'TODO: need update', 'node': True})

    # the commands' tree speaks the same discipline: a command live's
    # '/'-prefix with no node row gains one (the row's `help` carries the
    # namespace's word-help — the walk-on borrows it; the node itself is no
    # command word: never in the pools, never in the ? listing), a node
    # with no live children — even hidden count — is an orphan
    cmd_rows = meta.get('commands') or []
    cmd_lives = [r['live'] for r in cmd_rows if isinstance(r, dict) and r.get('live')]
    cmd_nodes = {r['name'] for r in cmd_rows if isinstance(r, dict) and r.get('node')}
    cmd_prefixes = set()
    for lv in cmd_lives:
        segs = lv.split('/')
        for i in range(1, len(segs)):
            cmd_prefixes.add('/'.join(segs[:i]))
    for n in sorted(n for n in cmd_nodes
                    if not any(lv.startswith(n + '/') for lv in cmd_lives)):
        nits.append('%s: the command node %r has no live children (even hidden count) — remove it' % (path, n))
    for p in sorted(p for p in cmd_prefixes if p not in cmd_nodes):
        i = next(i for i, r in enumerate(cmd_rows)
                 if isinstance(r, dict) and r.get('live') and r['live'].startswith(p + '/'))
        cmd_rows.insert(i, {'name': p, 'help': 'TODO: need update', 'node': True})

    if nits:
        return nits, None
    canon = render_registry(meta)
    if canon != text:
        nits.append('%s: off the canonical layout' % path)
    return nits, canon


def _canon_text(v):
    """The byte-for-byte compare form of one field's value (sorts keys, keeps
    the bool/number distinction)."""
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def family_lint():
    """The help-canon wave's family-wide passes over all four registries:

    (a) the RESOLUTION pass — every row's `shared` key resolves to a canon
        block of its section, every block is referenced by >=1 row, no
        options block carries `name` (the flat name is the block's key), no
        two blocks byte-duplicate each other;
    (b) the MUST-REF pass — a gated field carried byte-identical INLINE by
        >=3 tools with no canon block speaking it fails (the exempt list
        applies; two-tool identities may stay inline); where the block DOES
        speak it, the byte-equal inline twins are named for dropping;
    (c) the DRIFT pass — the gated fields of the same-named rows compare
        byte-for-byte on the EFFECTIVE rows (the fold applied, the row
        overrides won), a difference not in the exempt list fails.

    Returns the nits; main() prints them and exits 1."""
    from common.settings.options import canon_fold
    try:
        with open(os.path.join(REPO, 'shared', 'options-help.json'), encoding='utf-8') as f:
            canon = json.load(f)
    except (OSError, ValueError) as e:
        return ['shared/options-help.json: does not parse: %s' % e]
    metas = {}
    for tool in TOOLS:
        with open(os.path.join(REPO, tool, 'lib', 'options.json'), encoding='utf-8') as f:
            metas[tool] = json.load(f)
    nits = []
    # (a) the resolution pass
    BLOCK_KEYS = frozenset(('name', 'only', 'shared'))
    CANON_KNOWN = KNOWN - BLOCK_KEYS
    for section, blocks in canon.items():
        field = SECTION_FIELD.get(section)
        for key, block in blocks.items():
            if isinstance(block, dict):
                bad = sorted(BLOCK_KEYS & set(block))
                if bad:
                    nits.append('the canon block %s/%s carries %s — never a block field '
                                '(the name is the block\'s key, only/shared are the row\'s '
                                'placement marks)' % (section, key, ', '.join(map(repr, bad))))
                unknown = sorted(set(block) - CANON_KNOWN)
                if unknown:
                    nits.append('the canon block %s/%s: unknown key(s) %s'
                                % (section, key, ', '.join(unknown)))
                if section != 'options' and field not in block:
                    nits.append('the canon block %s/%s speaks no %s'
                                % (section, key, field))
            elif section == 'options':
                nits.append('the canon block %s/%s is not an object — the options '
                            'blocks carry the row fields' % (section, key))
            refs = sum(1 for t in TOOLS
                       for r in (metas[t].get(section) or [])
                       if isinstance(r, dict) and r.get('shared') == key)
            if not refs:
                nits.append('the canon block %s/%s is never referenced (the orphan gate)'
                            % (section, key))
    seen_blocks = {}
    for section, blocks in canon.items():
        for key, block in blocks.items():
            mark = _canon_text(block)
            if mark in seen_blocks:
                nits.append('the canon blocks %s/%s and %s byte-duplicate each other'
                            % (seen_blocks[mark], key, section))
            else:
                seen_blocks[mark] = '%s/%s' % (section, key)
    for section in ('options', 'show', 'commands'):
        for t in TOOLS:
            for r in metas[t].get(section) or []:
                key = r.get('shared')
                if key is not None and key not in (canon.get(section) or {}):
                    nits.append('%s: the %s row %r refs the unknown canon key %r'
                                % (t, section, r['name'], key))
    # (a2) the exclusivity pass — an `only` mark pins the knob to its one
    # tool: no other registry may row the same name in the same section
    seated = {}
    for t in TOOLS:
        for section in ('options', 'show', 'commands'):
            for r in metas[t].get(section) or []:
                seated.setdefault((section, r['name']), []).append(t)
    for t in TOOLS:
        for section in ('options', 'show', 'commands'):
            for r in metas[t].get(section) or []:
                if r.get('only') is None:
                    continue
                peers = [x for x in seated.get((section, r['name']), []) if x != t]
                if peers:
                    nits.append('%s: the %s row %r marks only=%s but %s also rows the name'
                                % (t, section, r['name'], r['only'], ', '.join(peers)))
    # (b) + (c): the effective rows per name
    for section in ('options', 'show', 'commands'):
        field_names = GATED if section == 'options' else (SECTION_FIELD[section],)
        by_name = {}
        for t in TOOLS:
            for r in metas[t].get(section) or []:
                eff = canon_fold(r, canon, section, t)
                by_name.setdefault(r['name'], []).append((t, r, eff))
        for name, rows in sorted(by_name.items()):
            if len(rows) < 2:
                continue
            for f in field_names:
                vals = {}
                for t, orig, eff in rows:
                    if f in eff:
                        vals.setdefault(_canon_text(eff[f]), []).append(t)
                if len(vals) > 1 and f not in EXEMPT.get((section, name), ()):
                    nits.append('the family drift: %s %s.%s differs — %s'
                                % (section, name, f,
                                   ' | '.join('%s: %s' % (', '.join(ts), v[:44])
                                              for v, ts in sorted(vals.items()))))
                block = (canon.get(section) or {}).get(name)
                for v, ts in vals.items():
                    if len(ts) < 3:
                        continue
                    if isinstance(block, dict):
                        block_has = _canon_text(block.get(f)) == v
                    else:
                        block_has = section != 'options' and block == json.loads(v)
                    if (section, name) in EXEMPT and f in EXEMPT.get((section, name), ()):
                        continue
                    if not block_has:
                        nits.append('the must-ref: %s %s.%s is byte-identical inline on %s — '
                                    'ref the canon block (or exempt)' % (section, name, f, ', '.join(ts)))
                    elif any(f in orig for t, orig, eff2 in rows if _canon_text(eff2.get(f)) == v):
                        nits.append('the must-ref: %s %s.%s rides the canon block — drop the '
                                    'byte-equal inline twins (%s)'
                                    % (section, name, f, ', '.join(ts)))
    return nits


def main():
    check, diff, propose = ('--check' in sys.argv[1:], '--diff' in sys.argv[1:],
                            '--propose' in sys.argv[1:])
    write = not check and not diff and not propose
    if propose:
        from common.settings.options import load_canon
        canon = load_canon()
        for tool in TOOLS:
            path = os.path.join(REPO, tool, 'lib', 'options.json')
            try:
                meta = json.load(open(path, encoding='utf-8'))
            except ValueError as e:
                print('%s: does not parse: %s' % (path, e))
                continue
            for key in meta:
                if not isinstance(meta[key], list):
                    continue
                for r in meta[key]:
                    for field, draft, why in proposals(r, canon):
                        print('%s %s/%s: %s — propose %s\n    %s' %
                              (tool, key, r['name'], why, field,
                               json.dumps(draft, ensure_ascii=False)))
        return 0
    bad = False
    for tool in TOOLS:
        path = os.path.join(REPO, tool, 'lib', 'options.json')
        nits, canon = lint(path)
        for nit in [n for n in nits if 'canonical' not in n]:
            print(nit)
            bad = True
        if canon is None:
            bad = True
            continue
        disk = open(path, encoding='utf-8').read()
        if canon == disk:
            continue
        if write:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(canon)
            print('%s: reformatted' % path)
        else:
            print('%s: off the canonical layout' % path)
            bad = True
            if diff:
                import difflib
                sys.stdout.writelines(difflib.unified_diff(
                    disk.splitlines(True), canon.splitlines(True),
                    path, path + ' (canonical)'))
    canon_path = os.path.join(REPO, 'shared', 'options-help.json')
    try:
        with open(canon_path, encoding='utf-8') as f:
            canon_disk = f.read()
        canon_text = render_canon(json.loads(canon_disk))
    except (OSError, ValueError) as e:
        print('shared/options-help.json: does not parse: %s' % e)
        bad = True
    else:
        if canon_text == canon_disk:
            pass
        elif write:
            with open(canon_path, 'w', encoding='utf-8') as f:
                f.write(canon_text)
            print('shared/options-help.json: reformatted')
        else:
            print('shared/options-help.json: off the canonical layout')
            bad = True
            if diff:
                import difflib
                sys.stdout.writelines(difflib.unified_diff(
                    canon_disk.splitlines(True), canon_text.splitlines(True),
                    canon_path, canon_path + ' (canonical)'))
    family = family_lint()
    for nit in family:
        print(nit)
        bad = True
    if bad:
        sys.exit(1)
    print('lint: the four registries and the canon file clean and canonical '
          '(the family passes too)')


if __name__ == '__main__':
    main()
