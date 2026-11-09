#!/usr/bin/env python3
"""The family-drift workflow: run the sweeps, regenerate
docs/family-drift.md (stdlib only).

    python3 scripts/family_drift.py            # regenerate the doc
    python3 scripts/family_drift.py --check    # exit 1 if it would change

The doc ships — the census sections are generated
from the tree, the verdict prose (the land/decline calls) lives in this
script's EDITORIAL blocks so a re-run updates the facts and keeps the
judgement.

The sweep types — what we are sweeping:

1. THE CODE SWEEP (text-structural). Every per-tool `lib/*.py` and
   `bin/*.py` function is AST-normalized (the line numbers and the
   local names collapse; the constant VALUES stay) and compared two
   ways: the exact pass groups identical bodies by hash (the
   copy-paste twins), the similarity pass pairs cross-file bodies by
   SequenceMatcher ratio (the near-copies that already drifted).
   Finds what should fold into `common/` — or documents what did.
2. THE SURFACE SWEEP (architectural). The listeners the family opens
   (every bind/serve point: the Modbus TCP faces, the /metrics
   expositions, the page, the control sockets), the wire tier each
   speaks, the loop machinery behind them (the accept ladders, the
   session openers, the poll loops, the reload/apply paths). Finds
   shapes that are the same but live in different bodies — invisible
   to the code sweep because the bodies differ in their surroundings.
3. THE KNOBS SWEEP (registry). The four `lib/options.json` registries
   diffed by name, by field and by semantic family. The knob layer is
   the one source --help, the man pages, the set grammar, the NixOS
   modules and the README checks read — a drifted row travels wide.
4. THE WIRE-TEXT SWEEP (the log/audit canon). Every logger call's
   format string and every audit.event() name, inventoried per tool:
   the event-name matrix, the phrase canon (the texts two or more
   tools share), the near-misses (the phrases that rhyme but no
   longer match). Finds the same event spelled two ways and the
   prose-mangling class before it reaches --help.
5. THE EXIT-AND-REFUSAL SWEEP (the failure ladder). Every
   SystemExit site with its rc and its refusal text, every exception
   frame code, the err/fail wire statuses — compared for the family
   canon: same cause, same code, same text shape.
6. THE RENDERED-SURFACE SWEEP. The artifacts the tools RENDER diffed
   by structure: the man pages' section ladders, --help's option
   groups, the README skeletons. Catches a section that grew on one
   tool and not the others.
7. THE NIXOS-PARITY SWEEP. Each module.nix option (type, default)
   against the same knob's registry row — the units drift (MB vs
   bytes) and the missing options are what this finds.
8. THE DOCKER/ENV SWEEP. The compose files, the env files and the
   entrypoints text-scanned for the env-var names and the published
   ports, matched against the registries' env twins and the default
   binds. A knob without its env twin cannot be set from an env
   file; a published port not in the registries is a lie.
9. THE SUITE-COVERAGE SWEEP (promises x tests). Every live knob,
   command word and canon phrase grepped against tests/*.py — the
   uncovered-promise list. Word-match honesty: a name inside another
   word counts, the suites are prose too.
10. THE F-LEDGER SWEEP. docs/AUDIT.md's F-numbers vs the tree: which
    tools' files cite each F, and the F's title. The promise ledger
    against the code.
11. THE STATICS SWEEP. The four lib/static.json blocks diffed by
    key-path: the shared paths whose values disagree, the
    only-there paths.
12. THE SCHEMA/EXAMPLE SWEEP. The JSON Schemas' properties against
    the registry rows (type/enum/bounds), every shipped example
    config re-parsed through the tool's own set-grammar reader.
13. THE SECRET-SURFACE SWEEP. Every secret-marked row: the file:
    support, the placeholder render rule, the restart/dump posture —
    one matrix.

Each sweep's section states its method, then the generated findings,
then the editorial verdicts."""
import ast
import difflib
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = ('cache', 'scraper', 'inverter', 'dashboard')
DOC = os.path.join(REPO, 'docs', 'family-drift.md')
SEEDS = os.path.join(REPO, 'docs', 'family-drift-seeds.json')

REGTEST = {'cache': 'cache-regtest.py', 'scraper': 'scrape-regtest.py',
           'inverter': 'inverter-regtest.py', 'dashboard': 'dashboard-control-fuzz.py'}

# ---------------------------------------------------------------- targets


def targets():
    """Every per-tool lib/bin module + every common module, as (where,
    relpath, abspath) — `where` is the tool or 'common'."""
    out = []
    for t in TOOLS:
        for sub in ('lib', 'bin'):
            d = os.path.join(REPO, t, sub)
            for f in sorted(os.listdir(d)):
                if f.endswith('.py'):
                    out.append((t, f'{t}/{sub}/' + f, os.path.join(d, f)))
    d = os.path.join(REPO, 'common')
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        for f in sorted(files):
            if f.endswith('.py'):
                p = os.path.join(root, f)
                out.append(('common', os.path.relpath(p, REPO), p))
    return out


# --------------------------------------------------------- the code sweep


def _norm(fn):
    """The body's structure with the line numbers collapsed: Constants
    keep their VALUES (the log texts are the pinned surface), names
    collapse to N (the local naming is not the drift)."""
    toks = []
    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Constant):
            toks.append('K:' + repr(node.value))
        elif isinstance(node, ast.Name):
            toks.append('N')
        elif isinstance(node, ast.Attribute):
            toks.append('A:' + node.attr)
        else:
            toks.append(type(node).__name__)
    return toks


def _funcs(min_lines=8):
    """Every function >= min_lines as (where, rel, name, line, nlines,
    tokens)."""
    out = []
    for where, rel, path in targets():
        try:
            tree = ast.parse(open(path, encoding='utf-8').read(), path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nlines = (node.end_lineno or 0) - node.lineno + 1
                if nlines >= min_lines:
                    out.append((where, rel, node.name, node.lineno, nlines, _norm(node)))
    return out


def code_exact():
    """The exact pass: identical normalized bodies in >= 2 files."""
    groups = {}
    for where, rel, name, line, nlines, toks in _funcs():
        h = hashlib.sha1('\n'.join(toks).encode()).hexdigest()[:12]
        groups.setdefault(h, []).append((nlines, rel, name, line))
    out = []
    for h, locs in groups.items():
        if len(set(l[1] for l in locs)) >= 2 and max(l[0] for l in locs) >= 4:
            out.append(sorted(locs, reverse=True))
    return sorted(out, key=lambda g: -g[0][0])


def code_similar(min_ratio=0.72):
    """The similarity pass: cross-file pairs over the ratio floor."""
    funcs = [f for f in _funcs() if len(f[5]) >= 6]
    pairs = []
    for i in range(len(funcs)):
        for j in range(i + 1, len(funcs)):
            a, b = funcs[i], funcs[j]
            if a[1] == b[1]:
                continue
            r = difflib.SequenceMatcher(None, a[5], b[5]).ratio()
            if r >= min_ratio and max(a[4], b[4]) >= 10:
                pairs.append((r, (a[1], a[3], a[2], a[4]), (b[1], b[3], b[2], b[4])))
    return sorted(pairs, key=lambda p: (-p[0], p[1][0]))


# ------------------------------------------------------- the knobs sweep

FIELDS = ('flag', 'env', 'conv', 'live', 'group', 'default', 'values',
          'min', 'max', 'secret', 'hidden', 'restart', 'node')


def knobs():
    """The four registries' rows + commands."""
    rows, cmds = {}, {}
    for t in TOOLS:
        with open(os.path.join(REPO, t, 'lib', 'options.json'), encoding='utf-8') as f:
            m = json.load(f)
        rows[t] = {r['name']: r for r in m['options']}
        cmds[t] = [c.get('live') or c['name'] for c in m.get('commands') or []]
    return rows, cmds


def knobs_shared(rows):
    """The knob names present in all four."""
    return sorted(n for n in set().union(*[set(r) for r in rows.values()])
                  if all(n in rows[t] for t in TOOLS))


def knobs_deltas(rows, names):
    """The shared knobs whose fields disagree across the tools."""
    out = []
    for n in names:
        by_field = {}
        for f in FIELDS:
            vals = {t: rows[t][n].get(f, '·') for t in TOOLS}
            if len(set(json.dumps(v, sort_keys=True) for v in vals.values())) > 1:
                by_field[f] = vals
        if by_field:
            out.append((n, by_field))
    return out


# ------------------------------------------------------- the wire-text sweep


def wire_texts():
    """Every logger.* format string + audit.event name, per tool file.
    Returns (events: {tool: set(names)}, logs: [(tool, rel, line,
    level, text)])."""
    events, logs = {}, []
    for where, rel, path in targets():
        try:
            tree = ast.parse(open(path, encoding='utf-8').read(), path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            fname = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else '')
            arg0 = node.args[0]
            text = arg0.value if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str) else None
            if fname == 'event' and isinstance(f, ast.Attribute) and text:
                if isinstance(node.func.value, ast.Name) and node.func.value.id.endswith('audit') \
                        or (isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'audit'):
                    events.setdefault(where, set()).add(text)
            elif fname in ('debug', 'info', 'warning', 'error') and text:
                logs.append((where, rel, node.lineno, fname, text))
    return events, logs


def wire_canon(logs, min_tools=2):
    """The phrase canon: the log texts' leading clause grouped across
    tools (the first sentence-ish chunk, lowercased, %s-normalized)."""
    def lead(text):
        chunk = text.split('%')[0].strip().lower()
        return re.sub(r'[^a-z0-9 :\-/\.]', '', chunk)[:48]
    groups = {}
    for where, rel, line, level, text in logs:
        groups.setdefault(lead(text), []).append((where, rel, line, text))
    canon = {k: v for k, v in groups.items()
             if len(set(x[0] for x in v)) >= min_tools and k}
    solo = {k: v for k, v in groups.items()
            if len(set(x[0] for x in v)) == 1 and k}
    return canon, solo


# ------------------------------------------------- the exit/refusal sweep

REFUSE_WORDS = ('refus', 'cannot ', 'needs ', 'without ', 'must ', 'invalid ', 'refusing')


def exits():
    """Every SystemExit site, deduped (the raise form and the bare-call
    form are one site): (rel, line, rc, enclosing-fn, the nearest
    preceding literal text carrying a refusal word)."""
    out = []
    for where, rel, path in targets():
        try:
            src = open(path, encoding='utf-8').read()
            tree = ast.parse(src, path)
        except SyntaxError:
            continue
        seen = set()
        for node in ast.walk(tree):
            call = None
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                call = node.exc
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == 'SystemExit':
                call = node
            if call is None:
                continue
            key = (rel, node.lineno)
            if key in seen:
                continue
            seen.add(key)
            a0 = call.args[0] if call.args else None
            rc = a0.value if isinstance(a0, ast.Constant) else '?'
            text = None
            if not isinstance(rc, str):
                for b in ast.walk(_enclosing_node(tree, node)):
                    if isinstance(b, ast.Call) and b.lineno < node.lineno and b.args:
                        x = b.args[0]
                        if isinstance(x, ast.Constant) and isinstance(x.value, str) \
                                and any(w in x.value for w in REFUSE_WORDS):
                            text = x.value
            out.append((rel, node.lineno, rc, _enclosing(tree, node.lineno), text))
    return out


def _enclosing_node(tree, node):
    best = tree
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.lineno <= node.lineno <= (n.end_lineno or 0):
            best = n
    return best


def _enclosing(tree, lineno):
    n = _enclosing_node(tree, ast.parse('pass')) if False else None
    best = '<module>'
    for x in ast.walk(tree):
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and x.lineno <= lineno <= (x.end_lineno or 0):
            best = x.name
    return best


# --------------------------------------------------- the rendered sweep


def rendered():
    """The man pages' .SH ladders + --help's section headers + the
    README skeletons, per tool."""
    mans, helps, readmes = {}, {}, {}
    bins = {'cache': 'cache/bin/modbus-cache.py', 'scraper': 'scraper/bin/modbus-scraper.py',
            'inverter': 'inverter/bin/modbus-fake-inverter.py', 'dashboard': 'dashboard/bin/dashboard.py'}
    for t, b in bins.items():
        try:
            man = subprocess.run([sys.executable, os.path.join(REPO, b), '--man'],
                                 capture_output=True, text=True, timeout=60,
                                 cwd=os.path.dirname(os.path.join(REPO, b))).stdout
            mans[t] = re.findall(r'^\.SH "?(.*?)"?$', man, re.M)
        except (OSError, subprocess.TimeoutExpired):
            mans[t] = None
        try:
            h = subprocess.run([sys.executable, os.path.join(REPO, b), '--help'],
                               capture_output=True, text=True, timeout=60,
                               cwd=os.path.dirname(os.path.join(REPO, b))).stdout
            helps[t] = [l[:-1].strip() for l in h.splitlines() if l.endswith(':')]
        except (OSError, subprocess.TimeoutExpired):
            helps[t] = None
    for t in TOOLS:
        p = os.path.join(REPO, t, 'README.md')
        if os.path.exists(p):
            readmes[t] = [l[3:].strip() for l in open(p, encoding='utf-8') if l.startswith('## ')]
    return mans, helps, readmes


# ------------------------------------------------------- the nixos sweep

NIX_TYPE = {'str': ('str', 'lines', 'nullOr', 'enum', 'path', 'either', 'coercedTo'),
            'int': ('ints', 'types.int', 'signedInterval'),
            'float': ('float', 'number'),
            'bool': ('bool',)}


def nixos(rows):
    """Each tool's module.nix: the `name = mkOption` blocks (nested
    under options.services.<tool>) with their type/default lines, then
    compared with the registry rows by name."""
    out = {}
    for t in TOOLS:
        p = os.path.join(REPO, t, 'module.nix')
        if not os.path.exists(p):
            out[t] = None
            continue
        blocks = {}
        cur = None
        depth = 0
        for line in open(p, encoding='utf-8'):
            if cur is None:
                m = re.match(r'\s*(\w+)\s*=\s*(lib\.)?mkOption\b', line)
                if m:
                    cur = m.group(1)
                    blocks[cur] = {'type': None, 'default': None}
                    depth = line.count('{') - line.count('}')
                continue
            depth += line.count('{') - line.count('}')
            if blocks[cur]['type'] is None and re.search(r'\btype\s*=', line):
                blocks[cur]['type'] = line.strip()
            if blocks[cur]['default'] is None and re.search(r'\bdefault\s*=', line) \
                    and 'defaultText' not in line:
                blocks[cur]['default'] = line.strip()
            if depth <= 0:
                cur = None
        out[t] = blocks
    return out


# ----------------------------------------------------- the docker sweep


def docker_env():
    """Text-scan docker/**: the env-var names (UPPER_SNAKE tokens) and
    the published ports per compose/env file."""
    found = {}
    d = os.path.join(REPO, 'docker')
    for root, dirs, files in os.walk(d):
        for f in sorted(files):
            if not f.endswith(('.yaml', '.yml', '.env', '.conf', '')):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, REPO)
            txt = open(p, encoding='utf-8', errors='replace').read()
            envs = sorted(set(re.findall(r'\b([A-Z][A-Z0-9_]{3,})\b', txt))
                          - {'HTTP', 'PATH', 'TZ', 'UTC', 'YAML', 'TCP'})
            ports = sorted(set(
                [m.group(2) for m in re.finditer(r'["\']?(?:[\d\.]+):(\d{4,5}):(\d{4,5})["\']?', txt)] +
                [m.group(1) for m in re.finditer(r'["\']?(\d{4,5}):(\d{4,5})["\']?', txt)]))
            found[rel] = (envs, ports)
    return found


# --------------------------------------------------- the coverage sweep


def coverage(rows, cmds, canon):
    """Every live knob / command word / canon phrase grepped against
    tests/*.py -> the uncovered list. The knob's spellings are the
    dashed name, the live path and the spaced live path (the wire's
    set/show form — the suites speak `set control ops verbs`, not the
    dashed row name); the command's are the /-path and the spaced
    words."""
    tests = []
    td = os.path.join(REPO, 'tests')
    for f in sorted(os.listdir(td)):
        if f.endswith('.py') and not f.startswith('zz_'):
            tests.append((f, open(os.path.join(td, f), encoding='utf-8', errors='replace').read()))
    blob = '\n'.join(t for _, t in tests)
    live = {t: [n for n, r in rows[t].items() if r.get('live')] for t in TOOLS}
    spellings = lambda w: (w, w.replace('/', ' '))   # the wire's two spellings:
                                                     # the /-path and the spaced words
    def knob_spell(n, r):
        lv = r.get('live') or n
        return (n, lv, lv.replace('/', ' '))
    uncovered = {t: sorted(n for n, r in rows[t].items() if r.get('live')
                 and not any(s in blob for s in knob_spell(n, r))) for t in TOOLS}
    cmd_missing = {t: sorted(w for w in cmds[t]
                             if not any(s in blob for s in spellings(w))) for t in TOOLS}
    phrase_unpinned = sorted(k for k in canon
                             if k not in blob and not any(p in blob for _, _, _, p in canon[k]))
    return uncovered, cmd_missing, phrase_unpinned, {t: len(tests) and len(live[t]) for t in TOOLS}


# ------------------------------------------------------ the statics sweep


def statics():
    """The four lib/static.json key-path matrices."""
    maps = {}
    for t in TOOLS:
        with open(os.path.join(REPO, t, 'lib', 'static.json'), encoding='utf-8') as f:
            flat = {}
            def walk(obj, prefix):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        walk(v, f'{prefix}.{k}' if prefix else k)
                else:
                    flat[prefix] = obj
            walk(json.load(f), '')
            maps[t] = flat
    return maps


# ---------------------------------------------- the schema/example sweep


def schemas(rows):
    """The JSON Schemas' properties vs the registry rows (the type and
    the enum/bounds honest-check)."""
    out = {}
    for t in TOOLS:
        sd = os.path.join(REPO, t, 'schema')
        per = {}
        if os.path.isdir(sd):
            for f in sorted(os.listdir(sd)):
                if f.endswith('.json'):
                    with open(os.path.join(sd, f), encoding='utf-8') as fh:
                        per[f] = json.load(fh)
        out[t] = per
    return out


def examples(rows):
    """Every shipped example config re-parsed through the tool's own
    reader (the set-grammar path; the JSON examples parse only)."""
    out = []
    sys.path.insert(0, REPO)
    for t in TOOLS:
        ed = os.path.join(REPO, t, 'examples')
        if not os.path.isdir(ed):
            continue
        for f in sorted(os.listdir(ed)):
            p = os.path.join(ed, f)
            rel = f'{t}/examples/{f}'
            if f.endswith('.conf'):
                try:
                    from common.settings.options import parse_config_script
                    o = importlib.import_module(f'{t}.lib.options')
                    parsed = parse_config_script(open(p, encoding='utf-8').read(), rel,
                                                 options=o.OPTIONS)
                    knob_names = {opt.name for opt in o.OPTIONS}
                    bad = sorted({name for name, _v in parsed if name not in knob_names})
                    out.append((rel, 'ok (%d setting line(s))' % len(parsed) if not bad
                                else 'unknown setting: ' + ', '.join(bad[:4])))
                except Exception as e:
                    out.append((rel, f'parse failed: {e}'))
            elif f.endswith('.json'):
                try:
                    json.load(open(p, encoding='utf-8'))
                    out.append((rel, 'json ok'))
                except Exception as e:
                    out.append((rel, f'invalid json: {e}'))
    return out


# ---------------------------------------------------- the secret sweep


def secrets(rows):
    """The secret-marked rows + the family's secret posture markers."""
    matrix = []
    for t in TOOLS:
        for n, r in rows[t].items():
            if r.get('secret'):
                matrix.append((t, n, bool(r.get('live')), bool(r.get('restart')), bool(r.get('hidden'))))
    markers = {}
    for where, rel, path in targets():
        txt = open(path, encoding='utf-8', errors='replace').read()
        hits = {}
        if 'parse_secret' in txt:
            hits['parse_secret'] = txt.count('parse_secret')
        if 'SECRET_REMOVED' in txt:
            hits['placeholder'] = True
        if 'file:' in txt:
            hits['file-scheme'] = True
        if hits:
            markers[rel] = hits
    return matrix, markers


# ------------------------------------------------------ the doc emitter

CODE_HEAD = """\
## The code sweep — the text-structural pass

Every per-tool `lib/*.py` and `bin/*.py` function, AST-normalized (the
line numbers and the local names collapse, the constant values stay),
compared two ways: the exact pass groups identical bodies (the
copy-paste twins), the similarity pass pairs cross-file bodies over the
0.72 ratio (the near-copies that already drifted)."""

SURFACE_HEAD = """\
## The surface sweep — the listeners, the wire and the loops

The architectural pass: every listener the family opens, the wire tier
it speaks, the loop machinery behind it. The census is generated from
the tree; the verdicts are editorial."""

KNOBS_HEAD = """\
## The knobs drift — the four registries side by side

The registry pass: `lib/options.json` x 4 diffed by name, by field and
by semantic family — the knob layer is the one source --help, the man
pages, the set grammar, the NixOS modules and the README checks read,
so a drifted row travels wide."""

VERIFICATION = """\
**The wave's verification state** (Nov 9): every `--help`/`--man`
byte-identical vs HEAD; `check_options` + `lint_options --check` clean;
the ten-suite battery green (the cache/scrape regtests and the
cache-fuzz legs needed one clean re-run after the killed first
battery's daemons squatted the suite ports — the failures were port
squatters, not code; the bind-note's clean death told the story)."""

WIRE_HEAD = """\
## The wire-text sweep — the log/audit canon

Every `logger.*` format string and every `audit.event` name,
inventoried per tool: the event names are the wire's vocabulary (the
regtests and the audit readers pin them), the log phrases are the
canon the operators grep for."""

EXIT_HEAD = """\
## The exit-and-refusal sweep — the failure ladder

Every `SystemExit` site with its rc and its refusal text, compared for
the family canon: same cause, same code, same text shape."""

RENDER_HEAD = """\
## The rendered-surface sweep — the man/help/README ladders

The artifacts the tools render, diffed by structure across the four:
the man pages' `.SH` section ladders, `--help`'s option groups, the
READMEs' `##` skeletons."""

NIXOS_HEAD = """\
## The NixOS-parity sweep — the modules vs the registries

Each `module.nix` option's type and default against the same knob's
registry row — the units drift (MB vs bytes, seconds vs ms) and the
missing options are what this finds. Heuristic parse: the type/default
LINES are quoted, the verdicts curated."""

DOCKER_HEAD = """\
## The docker/env sweep — the env twins and the ports

`docker/**` text-scanned for the env-var names and the published
ports, matched against the registries' env twins and the default
binds. A knob without its env twin cannot be set from an env file; a
published port not backed by a registry default is a lie."""

COVER_HEAD = """\
## The suite-coverage sweep — the promises x the tests

Every live knob name, command word and canon log phrase grepped
against `tests/*.py` (word-bounded). Word-match honesty: the suites
are prose too — a name inside another word counts as covered; the
list is the TODO seed, not a verdict."""

FLEDGER_HEAD = """\
## The F-ledger sweep — docs/AUDIT.md vs the tree

Each F-number's title from the audit doc, and which of the family's
files cite it — the promise ledger against the code."""

STATICS_HEAD = """\
## The statics sweep — the four static.json blocks

Every leaf key-path of the four `lib/static.json` files: the shared
paths whose values disagree, the only-there paths (the audit
defaults, the caps, the grid constants the loaders wire via
`static_defaults`)."""

SCHEMA_HEAD = """\
## The schema/example sweep — the derived sources

The JSON Schemas' properties against the registry rows, and every
shipped example re-parsed through the tool's own set-grammar reader
(not just name-checked)."""

SECRET_HEAD = """\
## The secret-surface sweep — the secret rows and their posture

Every `secret`-marked registry row with its live/restart/hidden
posture, the table consolidated by knob — rows sharing a posture
merge, the tools column carries the coverage (a knob missing from a
tool is the visible gap). The secret-posture markers (`parse_secret`,
the `SECRET_REMOVED` placeholder, the `file:` scheme) across the
tree."""

SURFACE_CENSUS = """\
The listener census (ten listeners):

| tool | surface | the class at it | the bind | the stack at it |
|---|---|---|---|---|
| inverter | Modbus TCP (the device) | `serve_modbus` (common/modbus/server.py) under the fake's face object | backlog 128 | the shared ladder; the face's hooks carry the tool (the chaos injector, the counters) |
| cache | Modbus TCP (the client face) | `serve_modbus` (common/modbus/server.py) under the proxy's face object | backlog 128 | the shared ladder; the write-gate layers in `respond()` (shape -> allow-write -> write ACL -> register gate); the requests audit rides `on_disconnect` |
| inverter | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | `common/serve/metrics_server` — the snapshot() hook is the tool's |
| cache | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook |
| dashboard | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook |
| scraper | /metrics (the exposition) | `Server` + `Handler` (lib/server.py) | the caps + the metrics/acl | its own Handler — the family's exposition shape (bearer, the spec render, the upstream relay) |
| dashboard | the page (static + proxy) | `Server` + `Handler` (bin/dashboard.py) | the caps | its own Handler — the cookies, the static tier, the /prom proxy, /config.js |
| all four | the control socket (unix, opt TCP) | `ControlServer` (common/wire/control.py) | 0600/0660 | the one shared wire: the token/RBAC roles, the HMAC frames, the caps live here |"""

SURFACE_FINDINGS = """\
The findings:

- **The accept ladder is one (landed — the audit-family wave).**
  `common/modbus/server.py`'s `serve_modbus` runs the discipline
  once: the client timeout -> `conn_gate.admit` (the per-IP cap,
  counts always, enforces only when capped) -> the connect-ACL check
  (release + `connection rejected: ... not on the connect ACL`) ->
  the `max_clients` check (release + `connection refused: client
  limit ...`) -> the count under the lock -> the daemon thread -> the
  pre-serve failure unwind -> the `finally` close. The backlog sits
  unified at 128 — above every face's client limit, a burst past a
  short backlog RSTs on macOS/BSD before the client sends — and the
  accept-error retry notices the `stopping` flag (the SignalBox
  close). The faces delegate (`Proxy.serve`, the fake's `serve`) and
  bring the face protocol's hooks: `listening`, `access`, `allowed`,
  `suite_key`, `on_frame`/`on_session`, `malformed`, `frame`,
  `on_disconnect`.
- **The session opener rides the same ladder (landed).** `_session`
  registers the client in the `clients` dict under the lock, runs the
  suite handshake when armed (`auth_handshake_server`, the failure
  logs identical, the peer dropped before it ever sees a frame),
  counts the requests per frame, and the `finally` unregisters (pop,
  count, `conn_gate.release`, close) — the cache's audit trail
  `REQUESTS` event rides `on_disconnect`, the fake's counters ride
  `on_frame`/`on_session`.
- **The malformed-frame split (a policy hook, as ruled).** On an
  unparseable frame the `malformed(addr, err)` hook decides: the fake
  logs and closes; the cache answers what it can in-band
  (`respond`'s proto/pdu guards -> exception frame) and closes
  silently on the hopeless MBAP. The cache is a proxy — its client
  deserves the protocol answer; the device just hangs up. The hook
  keeps the difference without a fork.
- **The poll-loop skeleton (declined).** The cache's `poll_loop` and
  the scraper's are the same shape — `while True: try poll_once()
  except log-crashed; wait(interval) on a wake Event; clear` — with
  the deltas as the content (the cache's duration stats and the
  requests-audit timer; the scraper's clamped wait and the live
  interval re-read). A fold needs three hooks for two users; the
  shape is the doc's to keep, not the code's.
- **The /metrics tier (at parity).** The common server owns the
  401/404/200 ladder, the caps, the thread and the
  bind-in-caller's-context rule; the tools bring a `snapshot()` and
  name their realm and logger. No drift.
- **The control wire (at parity).** One `ControlServer` — the
  subclasses are grammars (`command`/`_apply`/`_get`) and their
  reports; the rebind family, the RBAC roles, the frame MAC and the
  fold/restore machinery live in the base. No drift.
- **The HTTP handlers (different by nature).** The scraper's
  exposition Handler and the dashboard's UI Handler both rhyme with
  the common metrics 401 (the bearer compare, the
  `WWW-Authenticate` realm) but route it through their own reply
  shapes — the exposition's `relay` and the page's session-aware
  ladder. Not foldable without losing the shapes that make each
  correct.

The verdict: the accept-ladder leg is landed (the family's refusal
texts and the session opener have one home); the rest of the surface
drift is at parity or declined with the reasons above."""

KNOBS_VERBS = """\
- `request/clear/cache` + `request/dump/with-cache` — the cache only
  (the write-behind cadence and the flush verb are its nature).
- `request/reload-config` — the scraper and the dashboard (the
  cache's and the fake's reload exec and re-read in one — the fake's
  conf rides the exec since the config-file wave).
- `request/restart` — absent on the fake (its reload execs and
  re-reads the conf already, so the verb would double it; the
  restart-marked overrides fold in the exec).
- `reset` (the SIGUSR1 scenario reset) + `exit`/`logout` — the fake's
  console verbs (F11).
- `poll/now` — the scraper's poll trigger."""

KNOBS_FINDINGS = """\
The findings:

- **The audit rotation bounds are family-wide (landed — the
  audit-family wave).** `common/runtime/audit.py` holds the constants
  (`AUDIT_FILES` 1..100, `AUDIT_MAX_MB` 0..1048576), all four
  registries' rows repeat them, and `check_options` cross-checks the
  repetition — `set audit rotate files 0` refuses identically
  everywhere.
- **The `audit-daily` knob is one shape (landed).** The live name
  `audit/rotate/daily` and the `$AUDIT_DAILY` env twin agree on all
  four, and the fake's live dispatch flips the same bit; its
  remaining audit rows (log/max-mb/files/disable) stay startup-only
  by posture — no live name, the env twin carries them.
- **The env layer is complete under the env-or-note rule (landed).**
  Every knob carries its env twin or an explicit `no-env` note, and
  `check_options` gates the pair. The no-env census: the fake's 13
  (the F11 simulator surface — env-less by posture, their flags
  reachable from the config file since the config-file wave), the
  dashboard's 1 (`log-queries` — the live toggle exists, the startup
  stays flag-only), the cache and the scraper none; the nodes and
  the command rows are env-free by nature.
- **The `auth` name collision.** The dashboard's `auth` is a NODE
  (the page's auth namespace), the other three's is the modbus auth
  enum (`suite|none`). One spelling, two meanings in the family's
  set-grammar space — legal (the registries are per-tool), but the
  merged-knob view (docs/OPTIONS.md) and any future family-wide
  grammar should note it.
- **`KNOWN_VERBS` is hand-maintained.** The RBAC vocabulary lives as
  a Python tuple in each `lib/options.py` beside the registry that
  defines the same verbs as rows — two homes for one truth (the
  commands-lint gates the registry, not the tuple). A drift here is
  silent: an ops policy accepting a verb the grammar refuses, or the
  reverse. Candidate: derive `KNOWN_VERBS` from the registry's
  command rows at load."""

WIRE_FINDINGS = """\
The findings:

- **The audit vocabulary is tight** — the family speaks one event set;
  the tool-specific events are few and by nature. The matrix above is
  the canonical spelling list: a new event name should read it first."""

EXIT_FINDINGS = """\
The findings:

- **The rc discipline has one known, deliberate split**: the serving
  tools refuse a bad ops policy with rc 2 (argparse's convention for
  the CLI's own mistakes), the fake with rc 1 (its F11 posture — one
  error line, one exit). Everything else binds-fails rc 1 family-wide
  (the bind-note wave's `cannot bind` + SystemExit(1)).
- **The refusal texts carry the family's voice** — `refusing to`
  (the security floors: the /metrics loopback, the TCP-without-token,
  the token-shape), `cannot bind`, `needs`/`must` (the config
  validation). A new refusal should pick from these verbs; the exit
  sweep's nearest-text column is the review surface."""

RENDER_FINDINGS = """\
The findings:

- **The man ladders line up** (the same section order, the tool's own
  sections appended at the tail) — the gen_man.py generator owns the
  shape; the drift risk is a hand-edited page, which this sweep
  flags by the .SH ladder changing.
- **The README skeleton** is the one-skeleton wave's shape (how it
  works -> usage -> configuration -> runtime control -> the features
  -> security -> testing -> nix -> source layout -> license); a
  tool that grows a section the others lack is the drift this
  catches."""

NIXOS_FINDINGS = """\
The findings:

- **check_options gates the presence** ("the NixOS module defines
  every option"); the TYPE and DEFAULT parity is not gated — the
  units drift (the audit's MB, the intervals' seconds) is where a
  Nix default and a registry default can silently disagree. The
  module option maps were rebuilt from the module.nix files in the
  docs restructure wave — this sweep is the machine check that keeps
  them honest.
- The parse is heuristic (the first type=/default= line in the
  option block) — the verdicts in the findings are editorial; the
  table is the starting point for the module review."""

DOCKER_FINDINGS = """\
The findings:

- **The env-file twins are the docker surface's contract**: a
  registry env twin missing from every compose/env file means the
  knob is unreachable from the deployment — sometimes design (the
  demo needs fewer knobs), sometimes a gap. The split wave's wiring
  list (the prod = three services + the external collector, the
  demo's in-stack shapes) is the expected drift.
- **The published ports** should map 1:1 to the registry defaults
  (the 935x block) — a port in a compose file that no knob backs is
  the lie this sweep exists for."""

COVER_FINDINGS = """\
The findings:

- **The uncovered list is the TODO seed**, not a verdict: a knob can
  be covered by an alias spelling, a config-file set, or a
  family-wide suite the word-grep misses. The next test wave starts
  from this list.
- **The canon-phrase pins** are the regtests' strongest tool — a
  phrase in the canon no suite pins is a text free to drift.
- **The graduation path is the ledger** (docs/family-drift-seeds.json,
  `family_drift.py --seeds`): stable IDs, the suggested suite per
  seed, the counts as the shrink metric; the `--check` growth gate
  keeps the list honest — new promises ship covered or the gate
  fails."""

FLEDGER_FINDINGS = """\
The findings:

- **The cited-by column is the enforcement map**: an F whose only
  citations are the audit doc itself has no enforcement markers in
  the tree (either the F is enforced in code without a marker — add
  the marker — or it is not enforced — the ledger lies). The F-suffix
  convention (the code comments cite `F13 in docs/AUDIT.md`) is the
  family's traceability habit; the sweep keeps it honest."""

STATICS_FINDINGS = """\
The findings:

- **The static.json blocks are the tools' personalities** (the
  simulators' grid constants, the caps' defaults) — the drift that
  matters is the FAMILY defaults (the audit rotation, the log
  levels, the cap defaults) disagreeing: those wire through
  `static_defaults`/`choices` into the registries and the set
  grammar. The shared-path matrix is the ruling surface."""

SCHEMA_FINDINGS = """\
The findings:

- **The shared pair is the pattern**: the ip-prefix acl's example +
  schema live ONCE at the root examples/ + shared/schema/ (the four
  per-tool copies died in the shared-examples wave). The per-tool
  schema/ dirs that remain carry the tool-specific shapes.
- **The examples re-parse is the honest check**: a shipped example
  that the tool's own reader refuses is a broken promise shipped to
  every user who copies it. The table above is that check."""

SECRET_FINDINGS = """\
The findings:

- **The secret rows' posture should be uniform**: secret + restart
  (a secret never rides the reload state — the placeholder rule) +
  hidden (no live listing). A row that breaks the shape is the
  drift.
- **The markers' census** (`parse_secret`, `SECRET_REMOVED`,
  `file:`) is the F-trust surface: the loader parses, the dumps
  placeholder, the examples reference. A tool missing a marker is
  the story to chase."""

REMEDIATION = """\
## The remediation TODOs — the consistency rulings

The working assumption: **the family is one product** — a user moving
between the four tools finds the same knobs, the same words, the same
refusals and the same env layer; the code behind them lives once in
`common/`. Each TODO states the consistent outcome and the plane it
serves. Ordered by the user's exposure; the code plane rides along.

Landed (the audit-family wave): the audit rotation bounds
family-wide (the constants in `common/runtime/audit.py`, every registry
repeating them, `check_options` cross-checking); the `audit-daily`
knob one shape (the live `audit/rotate/daily` + the `$AUDIT_DAILY`
twin on all four); the env twins completed (the env-or-note rule —
a knob carries its twin or an explicit `no-env` note, the gate
enforces); the accept-ladder extraction (`common/modbus/server.py`
`serve_modbus` — the discipline, the session opener and the
malformed-frame policy hook with it).

1. **The `auth` name collision resolved** — one spelling, one
   meaning: the dashboard's `auth` node (the page's namespace)
   renames (`page-auth/` or the rows re-home), or the modbus enum
   re-homes; the set grammar never maps one word to two meanings.
   Breaking change for the dashboard's live names — the TODO is the
   proposal + the migration note (the alias map carries the old
   spellings one release).

2. **`request/reload-config` family-wide** — the re-read-without-exec
   surface exists on the scraper and the dashboard; the remaining two
   are the cache and the fake. The fake grew its config story (its
   reload execs and the conf re-reads in the new process) but has no
   reload-config row — the row decision open (a reloader of its own,
   or the family row answering `err no reloader configured`); the
   cache has the config script but no reloader wiring at all.

3. **`KNOWN_VERBS` derived, not hand-maintained** — the loaders build
   the RBAC vocabulary from the registry's command rows (the
   hidden/internal flags included). One home; the silent drift
   (a policy accepting a verb the grammar refuses) dies.

4. **The coverage TODOs graduate** — the seeds carry stable IDs in
    docs/family-drift-seeds.json (`family_drift.py --seeds`, the
    suggested suite per seed); a test wave consumes entries, the
    regeneration drops them, the shrinkage is the wave's proof, and
    `--check` fails when a NEW promise ships uncovered (the list may
    only shrink).

5. **The parity gates wired** — the NixOS-parity and docker/env
    sweeps join `check_options`/the release gates as machine checks
    (the module.nix type/default vs the registry, the env-file
    coverage vs the env twins). The drift doc's `--check` already
    shows the pattern: a stale claim fails the gate.

Not-todo (the ruling recorded): the fake's `request/restart` verb
stays absent (its reload execs and re-reads the conf — the
config-file wave — so the verb would double the reload); the
man-page prose and the HTTP
handlers stay per-tool by design; the malformed-frame split is the
proxy/device difference, kept as the ladder's policy hook."""


def seed_list(rows, cmds, canon):
    """The work order: every uncovered promise as a stable-ID seed
    (kind, tool, name, the suggested suite). The graduation path's
    currency — the sweep prints them, a test wave consumes them, the
    list shrinks."""
    uncovered, cmd_missing, phrase_unpinned, _ = coverage(rows, cmds, canon)
    seeds = []
    for t in TOOLS:
        for n in uncovered[t]:
            seeds.append({'id': f'knob:{t}:{n}', 'kind': 'knob', 'tool': t,
                          'name': n, 'suite': REGTEST[t]})
        for w in cmd_missing[t]:
            seeds.append({'id': f'cmd:{t}:{w}', 'kind': 'command', 'tool': t,
                          'name': w, 'suite': REGTEST[t]})
    for k in phrase_unpinned:
        h = hashlib.sha1(k.encode()).hexdigest()[:8]
        tools = ', '.join(sorted(set(x[0] for x in canon[k])))
        seeds.append({'id': f'phrase:{h}', 'kind': 'canon-phrase', 'tool': tools,
                      'name': k, 'suite': 'the emitting tool\'s regtest'})
    return seeds


def write_seeds(seeds):
    """The ledger: the seeds file carries the counts + the IDs — a wave
    consumes entries (the tests land), the next regeneration drops
    them, the shrinkage is the wave's proof. The growth gate reads the
    committed file: a seed PRESENT here and ABSENT there is new
    uncovered promise (exit 1); the reverse is the shrink (write)."""
    with open(SEEDS, 'w', encoding='utf-8') as f:
        json.dump({'seeds': seeds,
                   'counts': {'total': len(seeds),
                              'knob': sum(1 for s in seeds if s['kind'] == 'knob'),
                              'command': sum(1 for s in seeds if s['kind'] == 'command'),
                              'canon-phrase': sum(1 for s in seeds if s['kind'] == 'canon-phrase')}},
                  f, indent=1, ensure_ascii=False)
        f.write('\n')


def seed_guard(fresh):
    """The growth gate: a seed in the FRESH list that the committed
    ledger does not know = a new promise shipped uncovered -> rc 1.
    The fresh list being SHORTER is the shrink — the ledger updates."""
    try:
        known = {s['id'] for s in json.load(open(SEEDS, encoding='utf-8'))['seeds']}
    except (OSError, KeyError, ValueError):
        return None   # no ledger yet — the first write seeds it
    grown = [s for s in fresh if s['id'] not in known]
    if grown:
        return grown
    return None


def f_ledger():
    """docs/AUDIT.md's F-numbers: the §3 tables' rows (| F1 | module |
    severity | finding |) give the title (the finding's first clause);
    the whole-tree files citing each."""
    p = os.path.join(REPO, 'docs', 'AUDIT.md')
    fs = {}
    order = []
    for line in open(p, encoding='utf-8', errors='replace'):
        m = re.match(r'\|\s*(F\d+)\s*\|', line)
        if m and m.group(1) not in fs:
            cells = [c.strip() for c in line.split('|')[1:-1]]
            finding = cells[3] if len(cells) >= 4 else ''
            title = finding.split('—')[0].split('.')[0].strip().replace('**', '')
            fs[m.group(1)] = title[:80]
            order.append(m.group(1))
    cited = {}
    for where, rel, path in targets():
        txt = open(path, encoding='utf-8', errors='replace').read()
        for num in order:
            if re.search(r'\b' + num + r'\b', txt):
                cited.setdefault(num, set()).add(rel.split('/')[0])
    return [(num, fs[num], ', '.join(sorted(cited.get(num, set())))) for num in order]


def emit():
    """The full doc: the header + the thirteen sweep sections."""
    lines = []
    ap = lines.append
    ap('# The family drift — the shared-code sweeps (regenerated)')
    ap('')
    ap('The wave record: the sweep types over the four surfaces (cache,')
    ap('scraper, inverter, dashboard) — what each sweeps, what it found,')
    ap('and the verdicts. **Ships in the repo, kept current by the')
    ap('workflow**: the landed legs ride their per-tool commits, the')
    ap('open findings wait in place, and `--check` fails a stale page.')
    ap('Regenerate with `python3 scripts/family_drift.py`; the verdict')
    ap('prose lives in this script (`*_FINDINGS`/`*_VERBS`/`*_CENSUS`)')
    ap('so a re-run updates the facts and keeps the judgement.')
    ap('')
    ap('The sweep types:')
    ap('')
    ap('1. **The code sweep** (text-structural) — AST-normalized function')
    ap('   bodies, exact-hash grouped + pairwise similarity. Finds what')
    ap('   should fold into `common/`.')
    ap('2. **The surface sweep** (architectural) — the listeners, the wire')
    ap('   tiers, the loop machinery. Finds the shapes that are the same')
    ap('   but live in different bodies.')
    ap('3. **The knobs sweep** (registry) — the four registries by name,')
    ap('   by field, by family.')
    ap('4. **The wire-text sweep** — the log/audit canon: the event names,')
    ap('   the shared phrases, the near-misses.')
    ap('5. **The exit-and-refusal sweep** — the SystemExit ladders, the rc')
    ap('   discipline, the refusal texts.')
    ap('6. **The rendered-surface sweep** — the man/`--help`/README section')
    ap('   ladders diffed by structure.')
    ap('7. **The NixOS-parity sweep** — the module.nix option types and')
    ap('   defaults against the registries.')
    ap('8. **The docker/env sweep** — the env twins and the published')
    ap('   ports against the registries.')
    ap('9. **The suite-coverage sweep** — the promises (knobs, commands,')
    ap('   canon phrases) grepped against the tests.')
    ap('10. **The F-ledger sweep** — docs/AUDIT.md\'s F-numbers vs the')
    ap('    tree\'s enforcement markers.')
    ap('11. **The statics sweep** — the four static.json blocks by')
    ap('    key-path.')
    ap('12. **The schema/example sweep** — the JSON Schemas vs the')
    ap('    registries; the shipped examples re-parsed.')
    ap('13. **The secret-surface sweep** — the secret rows and the')
    ap('    posture markers.')
    ap('')
    ap(VERIFICATION)
    ap('')

    # ---- 1. the code sweep
    ap(CODE_HEAD)
    ap('')
    ex = code_exact()
    ap(f'**The exact pass**: {len(ex)} duplicate group(s) in >= 2 files.')
    ap('')
    for g in ex[:12]:
        ap(f'- {g[0][0]}L `{g[0][2]}`: ' + ', '.join(f'`{rel}:{line}`' for _, rel, name, line in g))
    if len(ex) > 12:
        ap(f'- … and {len(ex) - 12} more small group(s)')
    ap('')
    sim = code_similar()
    top = [p for p in sim if 'man.py' not in p[1][0] and 'man.py' not in p[2][0]]
    ap(f'**The similarity pass**: {len(sim)} cross-file pair(s) over the ratio')
    ap(f'floor ({len(sim) - len(top)} of them the man-page prose, per-tool by')
    ap('design); the top non-man pairs:')
    ap('')
    ap('| ratio | pair |')
    ap('|---|---|')
    for r, a, b in top[:20]:
        ap(f'| {r:.2f} | `{a[0]}:{a[1]}` `{a[2]}` <-> `{b[0]}:{b[1]}` `{b[2]}` |')
    ap('')

    # ---- 2. the surface sweep
    ap(SURFACE_HEAD)
    ap('')
    ap(SURFACE_CENSUS)
    ap('')
    ap(SURFACE_FINDINGS)
    ap('')

    # ---- 3. the knobs sweep
    rows, cmds = knobs()
    shared = knobs_shared(rows)
    ap(KNOBS_HEAD)
    ap('')
    ap(f'**The shape**: {sum(len(r) for r in rows.values())} knob rows across the')
    ap(f'four registries; {len(shared)} names carry in all four:')
    ap('')
    ap('`' + '`, `'.join(shared) + '`')
    ap('')
    ap('**The tool-specific remainder** (by nature):')
    ap('')
    ap('| tool | only-there knobs |')
    ap('|---|---|')
    for t in TOOLS:
        only = sorted(n for n in rows[t] if not all(n in rows[o] for o in TOOLS))
        ap(f'| {t} | {", ".join(f"`{n}`" for n in only)} |')
    ap('')
    deltas = knobs_deltas(rows, shared)
    ap(f'**The shared knobs whose fields disagree** ({len(deltas)} of')
    ap(f'{len(shared)}):')
    ap('')
    ap('| knob | the drifted fields (cache / scraper / inverter / dashboard) |')
    ap('|---|---|')
    for n, by_field in deltas:
        parts = ['%s: %s' % (f, ' | '.join(f'{t[0]}={json.dumps(vals[t], ensure_ascii=False)}' for t in TOOLS))
                 for f, vals in by_field.items()]
        ap(f'| `{n}` | {" <br> ".join(parts)} |')
    ap('')
    ap('**The command vocabularies** (the wire words per tool):')
    ap('')
    for t in TOOLS:
        ap(f'- {t}: ' + ', '.join(f'`{w}`' for w in cmds[t]))
    ap('')
    ap('**The command deltas worth a ruling:**')
    ap('')
    ap(KNOBS_VERBS)
    ap('')
    ap(KNOBS_FINDINGS)
    ap('')

    # ---- 4. the wire-text sweep
    events, logs = wire_texts()
    canon, solo = wire_canon(logs)
    ap(WIRE_HEAD)
    ap('')
    ap('**The audit event names** (the wire\'s vocabulary):')
    ap('')
    ap('| tool | events |')
    ap('|---|---|')
    for t in TOOLS + ('common',):
        if events.get(t):
            ap(f'| {t} | {", ".join(f"`{e}`" for e in sorted(events[t]))} |')
    ap('')
    ap(f'**The phrase canon**: {len(canon)} log phrase(s) shared by >= 2 tools;')
    ap(f'{len(solo)} tool-local. The canon (the lead clause, the tools that speak it):')
    ap('')
    ap('| the lead clause | tools |')
    ap('|---|---|')
    for k in sorted(canon, key=lambda k: -len(canon[k]))[:25]:
        ts = ', '.join(sorted(set(x[0] for x in canon[k])))
        ap(f'| `{k}` | {ts} |')
    ap('')
    ap(WIRE_FINDINGS)
    ap('')

    # ---- 5. the exit/refusal sweep
    ex_sites = exits()
    ap(EXIT_HEAD)
    ap('')
    ap('**The rc summary** + **the distinct refusal texts** (the literal')
    ap('message args — the family\'s refusal canon):')
    ap('')
    rcs = {'0': 0, '1': 0, '2': 0}
    var_sites = 0
    texts = set()
    for rel, line, rc, fn, text in ex_sites:
        if isinstance(rc, bool) or isinstance(rc, int):
            rcs[str(rc)] += 1
        elif isinstance(rc, str):
            texts.add(rc)
        else:
            var_sites += 1
    ap(f'- rc 0 (the clean exits): {rcs["0"]}; rc 1 (the binds): {rcs["1"]};'
       f' rc 2 (the CLI mistakes): {rcs["2"]};'
       f' {var_sites} site(s) raising a variable (the message/`rc` computed —')
    ap('  the common SystemExit(str) prints the message and exits 1).')
    ap('')
    ap('The refusal texts (the literal SystemExit args, sorted):')
    ap('')
    for tx in sorted(texts):
        ap(f'- `{tx}`')
    ap('')
    ap(EXIT_FINDINGS)
    ap('')

    # ---- 6. the rendered sweep
    mans, helps, readmes = rendered()
    ap(RENDER_HEAD)
    ap('')
    ap('**The man-page `.SH` ladders** (RENDER FAILED = the render died):')
    ap('')
    for t in TOOLS:
        sh = mans.get(t)
        ap(f'- {t}: ' + (' -> '.join(sh) if sh else 'RENDER FAILED'))
    ap('')
    ap('**The README `##` skeletons:**')
    ap('')
    for t in TOOLS:
        ap(f'- {t}: ' + (' -> '.join(readmes.get(t) or ['NO README'])))
    ap('')
    ap(RENDER_FINDINGS)
    ap('')

    # ---- 7. the nixos sweep
    nix = nixos(rows)
    ap(NIXOS_HEAD)
    ap('')
    ap('| tool | mkOption blocks |')
    ap('|---|---|')
    for t in TOOLS:
        ap(f'| {t} | {len(nix[t]) if nix[t] else "no module.nix"} |')
    ap('')
    ap('**The module options NOT matching a registry knob name** (after')
    ap('the kebab/camel normalization; the `*File` suffix is the NixOS')
    ap('LoadCredential pattern, not a knob):')
    ap('')
    for t in TOOLS:
        if nix[t]:
            def norm(s):
                return s.lower().replace('-', '').replace('_', '')
            reg_names = {norm(n) for n in rows[t]}
            orphan = sorted(n for n in nix[t]
                            if norm(n) not in reg_names and not n.endswith('File')
                            and n not in ('package', 'enable', 'openFirewall', 'configFile', 'settings'))
            ap(f'- {t}: ' + (', '.join(f'`{n}`' for n in orphan) or 'every option is a knob or plumbing'))
    ap('')
    ap(NIXOS_FINDINGS)
    ap('')

    # ---- 8. the docker sweep
    de = docker_env()
    ap(DOCKER_HEAD)
    ap('')
    ap('| file | env vars | published ports |')
    ap('|---|---|---|')
    for rel in sorted(de):
        envs, ports = de[rel]
        ap(f'| `{rel}` | {", ".join(f"`{e}`" for e in envs[:14])}'
           f'{" …" if len(envs) > 14 else ""} | {", ".join(ports) or "—"} |')
    ap('')
    ap(DOCKER_FINDINGS)
    ap('')

    # ---- 9. the coverage sweep
    uncovered, cmd_missing, phrase_unpinned, _ = coverage(rows, cmds, canon)
    seeds = seed_list(rows, cmds, canon)
    ap(COVER_HEAD)
    ap('')
    ap('**The live knobs no suite mentions** (word-bounded grep):')
    ap('')
    for t in TOOLS:
        if uncovered[t]:
            ap(f'- {t}: ' + ', '.join(f'`{n}`' for n in uncovered[t]))
        else:
            ap(f'- {t}: every live knob named somewhere in the suites')
    ap('')
    ap('**The command words no suite mentions:**')
    ap('')
    for t in TOOLS:
        if cmd_missing[t]:
            ap(f'- {t}: ' + ', '.join(f'`{w}`' for w in cmd_missing[t]))
        else:
            ap(f'- {t}: every command exercised')
    ap('')
    ap(f'**The canon phrases no suite pins**: {len(phrase_unpinned)}')
    ap('')
    ap('**The graduation path**: the seeds carry stable IDs in')
    ap(f'[docs/family-drift-seeds.json](family-drift-seeds.json) ({len(seeds)}')
    ap('open promise(s), the suggested suite per seed); a test wave')
    ap('consumes entries, the regeneration drops them, the shrinkage is')
    ap('the wave\'s proof; `--check` fails when a NEW promise ships')
    ap('uncovered (the list may only shrink).')
    ap('')
    ap(COVER_FINDINGS)
    ap('')

    # ---- 10. the F-ledger sweep
    ap(FLEDGER_HEAD)
    ap('')
    fs = f_ledger()
    ap('| F | title | cited by |')
    ap('|---|---|---|')
    for num, title, cited in fs:
        ap(f'| {num} | {title} | {cited or "—"} |')
    ap('')
    ap(FLEDGER_FINDINGS)
    ap('')

    # ---- 11. the statics sweep
    maps = statics()
    ap(STATICS_HEAD)
    ap('')
    allpaths = sorted(set().union(*[set(m) for m in maps.values()]))
    shared_paths = [p for p in allpaths if all(p in maps[t] for t in TOOLS)]
    drift_paths = [p for p in shared_paths
                   if len(set(json.dumps(maps[t][p], sort_keys=True) for t in TOOLS)) > 1]
    ap(f'{len(allpaths)} leaf paths; {len(shared_paths)} in all four;'
       f' {len(drift_paths)} shared with differing values.')
    ap('')
    if drift_paths:
        ap('| key-path | per-tool values |')
        ap('|---|---|')
        for p in drift_paths[:20]:
            ap(f'| `{p}` | ' + ' | '.join(f'{t[0]}: {json.dumps(maps[t][p], ensure_ascii=False)}' for t in TOOLS) + ' |')
        ap('')
    ap(STATICS_FINDINGS)
    ap('')

    # ---- 12. the schema/example sweep
    ap(SCHEMA_HEAD)
    ap('')
    schemas_ = schemas(rows)
    ap('| tool | schema files |')
    ap('|---|---|')
    for t in TOOLS:
        per = schemas_[t] or {}
        ap(f'| {t} | {", ".join(f"`{f}`" for f in sorted(per)) or "none"} |')
    ap('')
    exs = examples(rows)
    ap('**The shipped examples re-parsed** through the tools\' own readers:')
    ap('')
    ap('| example | the read |')
    ap('|---|---|')
    for rel, verdict in exs:
        ap(f'| `{rel}` | {verdict} |')
    ap('')
    ap(SCHEMA_FINDINGS)
    ap('')

    # ---- 13. the secret sweep
    matrix, markers = secrets(rows)
    ap(SECRET_HEAD)
    ap('')
    groups = {}
    for t, n, live, restart, hidden in matrix:
        groups.setdefault((n, live, restart, hidden), []).append(t)
    ap(f'{len(matrix)} secret-marked row(s) across {len(groups)} knob(s), consolidated by posture:')
    ap('')
    ap('| knob | tools | live | restart | hidden |')
    ap('|---|---|---|---|---|')
    for (n, live, restart, hidden), ts in sorted(groups.items()):
        tools = 'all four' if len(ts) == len(TOOLS) else ', '.join(sorted(ts))
        ap(f'| `{n}` | {tools} | {"yes" if live else "no"} | {"yes" if restart else "no"} | {"yes" if hidden else "no"} |')
    ap('')
    ap(SECRET_FINDINGS)
    ap('')

    # ---- the remediation TODOs
    ap(REMEDIATION)
    ap('')
    return '\n'.join(lines) + '\n'


def main():
    doc = emit()
    rows, cmds = knobs()
    events, logs = wire_texts()
    canon, _solo = wire_canon(logs)
    seeds = seed_list(rows, cmds, canon)
    if '--seeds' in sys.argv:
        write_seeds(seeds)
        print(f'seed ledger: {len(seeds)} open promise(s) -> {os.path.relpath(SEEDS, REPO)}')
        return
    if '--check' in sys.argv:
        try:
            cur = open(DOC, encoding='utf-8').read()
        except OSError:
            cur = None
        stale = cur != doc
        grown = seed_guard(seeds)
        if stale:
            print('family-drift.md is stale (scripts/family_drift.py regenerates)')
        if grown:
            print(f'family-drift-seeds.json: {len(grown)} NEW uncovered promise(s) the ledger does not know:')
            for s in grown[:10]:
                print(f"  {s['id']}  ({s['kind']}, suggested: {s['suite']})")
            print('a knob/command/canon phrase shipped without its test — write the tests, then regenerate the ledger')
        if stale or grown:
            raise SystemExit(1)
        print('family-drift.md is current; the seed ledger knows every open promise')
        return
    with open(DOC, 'w', encoding='utf-8') as f:
        f.write(doc)
    if not os.path.exists(SEEDS):
        write_seeds(seeds)   # the first run seeds the ledger; the waves shrink it
    print('regenerated', os.path.relpath(DOC, REPO))


if __name__ == '__main__':
    main()
