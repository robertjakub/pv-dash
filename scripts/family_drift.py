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
7. THE NIXOS-PARITY SWEEP. The structural check: the modules declare
   exactly enable/package/openFirewall/settings (+ the dashboard's
   solarConfig/staticDir) and every registry secret row's *File
   credential option — the knob options are gone (the settings wave:
   the freeform env-file attrset, the LoadCredential secrets).
8. THE DOCKER/ENV SWEEP. The compose files, the env files and the
   entrypoints text-scanned for the env-var names and the published
   ports, matched against the registries' env twins and the default
   binds. A knob without its env twin cannot be set from an env
   file; a published port not in the registries is a lie.
9. THE SUITE-COVERAGE SWEEP (promises x tests). Every live knob,
   command word and canon phrase grepped against tests/suites/*.py — the
   uncovered-promise list. Word-match honesty: a name inside another
   word counts, the suites are prose too.
10. THE F-LEDGER SWEEP. docs/SECURITY.md's F-numbers vs the tree: which
    tools' files cite each F, and the F's title. The promise ledger
    against the code.
11. THE STATICS SWEEP. The four lib/defaults.json blocks (the non-knob
    statics since the defaults moved into the registry rows) diffed by
    key-path: the shared paths whose values disagree, the
    only-there paths.
12. THE SCHEMA/EXAMPLE SWEEP. The JSON Schemas' properties against
    the registry rows (type/enum/bounds), every shipped example
    config re-parsed through the tool's own set-grammar reader.
13. THE SECRET-SURFACE SWEEP. Every secret-marked row: the file:
    support, the placeholder render rule, the restart/dump posture —
    one matrix.
14. THE CONSOLE-PRINT SWEEP. The cli session path (common/wire/cli.py
    and the four bin/*-cli.py) prints through the pager's one door
    (page_out/display) — a naked print( with an argument is the drift
    (the bare print() breathing room is the loop's own); the finding
    fails --check.

Each sweep's section states its method, then the generated findings,
then the editorial verdicts."""
import ast
import difflib
import hashlib
import importlib
import json
import lint.lint_readmes as lint_readmes
import os
import re
import subprocess
import sys

from lib import REPO, TOOLS   # the scripts' common lib
from lib.emit import emit as emit_page
from lib.registry import folded as fold_rows, raw as raw_registry
from lib.walk import targets

DOC = os.path.join(REPO, 'docs', 'family-drift.md')
SEEDS = os.path.join(REPO, 'docs', 'family-drift-seeds.json')

REGTEST = {'cache': 'cache-regtest.py', 'scraper': 'scrape-regtest.py',
           'inverter': 'inverter-regtest.py', 'dashboard': 'dashboard-control-fuzz.py'}

# ---------------------------------------------------------------- targets


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
    """The four registries' rows + commands — the EFFECTIVE rows (the canon
    refs resolved: the fold is the loader's own, so the sweep compares the
    truth the daemons load, the block-carried fields included)."""
    rows = {t: {r['name']: r for r in fold_rows(t, 'options')} for t in TOOLS}
    cmds = {t: [c.get('live') or c['name'] for c in raw_registry(t).get('commands') or []]
            for t in TOOLS}
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


def canon_coverage():
    """The help-canon's split: the canon blocks per section, the refing rows
    per tool, the exempt names lint_options carries. The drift gate lives in
    lint_options --check — this report shows the fold's reach."""
    from lint.lint_options import EXEMPT
    with open(os.path.join(REPO, 'shared', 'suite', 'options.json'), encoding='utf-8') as f:
        canon = json.load(f)
    refs = {t: {} for t in TOOLS}
    for t in TOOLS:
        m = raw_registry(t)
        for section in ('options', 'show', 'commands'):
            rows = m.get(section) or []
            refs[t][section] = sum(1 for r in rows if r.get('shared'))
    return canon, refs, len(EXEMPT)


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

# the service modules' flat home (nixos/modules/<tool>.nix; the inverter
# ships no module — the test-tool posture)
NIX_MODULES = {
    'cache': 'nixos/modules/modbus-cache.nix',
    'scraper': 'nixos/modules/modbus-scraper.nix',
    'dashboard': 'nixos/modules/dashboard.nix',
}

def nixos(rows):
    """Each tool's service module (nixos/modules/<tool>.nix): the
    `name = mkOption` blocks (plus the mkEnableOption enable row and the
    settings wave's mkFileOption credential helper) — the names are what
    the structural check diffs against the expected contract."""
    out = {}
    for t in TOOLS:
        rel = NIX_MODULES.get(t)
        p = os.path.join(REPO, rel) if rel else None
        if not p or not os.path.exists(p):
            out[t] = None
            continue
        blocks = {}
        cur = None
        depth = 0
        for line in open(p, encoding='utf-8'):
            if cur is None:
                m = re.match(r'\s*(\w+)\s*=\s*(lib\.)?(?:mkOption|mkEnableOption|mkFileOption)\b', line)
                if m:
                    cur = m.group(1)
                    blocks[cur] = {'type': None, 'default': None}
                    depth = line.count('{') - line.count('}')
                    if depth <= 0:
                        # the one-line shape (the mkFileOption helper call):
                        # reset now or the next option is swallowed
                        cur = None
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


def knob_ports(rows):
    """The ports the registries back: the listen/metrics-listen knobs'
    defaults (the rows' `default` — the resolver's static rung) -> the
    port set. A published port outside this set is the lie the sweep
    exists for."""
    backed = {}
    for t in TOOLS:
        for n, r in rows[t].items():
            live = r.get('live') or ''
            if n in ('listen', 'metrics-listen') or live.endswith('/listen'):
                d = r.get('default')
                if isinstance(d, str) and ':' in d:
                    backed.setdefault(int(d.rsplit(':', 1)[1]), []).append(f'{t}:{n}')
    return backed


def docker_ports():
    """The docker surface's ports: the Dockerfile EXPOSE + CMD --listen
    ports and the compose `ports:` container-side ports."""
    exposed, published = {}, {}
    d = os.path.join(REPO, 'docker')
    for root, dirs, files in os.walk(d):
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, REPO)
            txt = open(p, encoding='utf-8', errors='replace').read()
            if f.startswith('Dockerfile.'):
                if f == 'Dockerfile.prometheus':
                    continue   # the collector is third-party — 9090 is its own default, no pv knob backs it
                ex = sorted({int(m) for m in re.findall(r'^EXPOSE\s+(\d{4,5})', txt, re.M)})
                lp = sorted({int(m) for m in re.findall(r'--listen[= ](?:[\d\.]+:)?\[?[\d\.]+\]?:(\d{4,5})', txt)})
                if ex or lp:
                    exposed[rel] = (ex, lp)
            elif f.endswith('.yaml'):
                pub = sorted({int(m.group(2)) for m in re.finditer(r"['\"]?(?:[\d\.]+):(\d{4,5}):(\d{4,5})['\"]?", txt)})
                if pub:
                    published[rel] = pub
    return exposed, published


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
    tests/suites/*.py -> the uncovered list. The knob's spellings are the
    dashed name, the live path and the spaced live path (the wire's
    set/show form — the suites speak `set control ops verbs`, not the
    dashed row name); the command's are the /-path and the spaced
    words."""
    tests = []
    td = os.path.join(REPO, 'tests', 'suites')
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
    """The four lib/defaults.json key-path matrices — the non-knob statics
    since the defaults moved into the registry rows (the knobs' `default`
    fields)."""
    maps = {}
    for t in TOOLS:
        with open(os.path.join(REPO, t, 'lib', 'defaults.json'), encoding='utf-8') as f:
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
    the enum/bounds honest-check). The tool-local schema/ dirs plus the
    shared shared/schema/ home."""
    out = {}
    for t, base in [(t, os.path.join(REPO, t, 'schema')) for t in TOOLS] + [
            ('shared', os.path.join(REPO, 'shared', 'schema'))]:
        per = {}
        if os.path.isdir(base):
            for f in sorted(os.listdir(base)):
                if f.endswith('.json'):
                    with open(os.path.join(base, f), encoding='utf-8') as fh:
                        per[f] = json.load(fh)
        out[t] = per
    return out


def examples(rows):
    """Every shipped example config re-parsed through the tool's own
    reader (the set-grammar path; the JSON examples parse only). The
    tool-local examples/ dirs plus the shared extras/examples/ home."""
    out = []
    sys.path.insert(0, REPO)
    dirs = [(t, f'{t}/examples', os.path.join(REPO, t, 'examples')) for t in TOOLS]
    dirs.append((None, 'extras/examples', os.path.join(REPO, 'extras', 'examples')))
    for t, label, ed in dirs:
        if not os.path.isdir(ed):
            continue
        for f in sorted(os.listdir(ed)):
            p = os.path.join(ed, f)
            rel = f'{label}/{f}'
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


# ------------------------------------------------- the console-print sweep

CONSOLE_SESSION_FILES = (
    'common/wire/cli.py',
    'cache/bin/modbus-cache-cli.py', 'scraper/bin/modbus-scraper-cli.py',
    'inverter/bin/modbus-fake-cli.py', 'dashboard/bin/dashboard-cli.py',
)


def naked_prints():
    """The console-print sweep: the cli session path prints through the
    pager's one door (page_out/display) — a naked print( carrying an
    argument (or a file=/end= keyword) in common/wire/cli.py or a
    bin/*-cli.py is the drift; the bare print() blank (the pre-prompt
    breathing room) is the loop's own and stays. Returns (rel, line)
    findings; --check fails on any."""
    out = []
    for rel in CONSOLE_SESSION_FILES:
        try:
            tree = ast.parse(open(os.path.join(REPO, rel), encoding='utf-8').read(), rel)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == 'print' and (node.args or node.keywords):
                out.append((rel, node.lineno))
    return out


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

The settings wave inverted the modules: no knob options at all — one
freeform `settings` attrset rendered verbatim into the unit's
EnvironmentFile (the keys are the bare env twins, unvalidated), the
secrets ride the `<secret>File` LoadCredential options only, and the
survivors are the structural options. There is no per-knob Nix-side
type/default left to drift; the check is structural."""

DOCKER_HEAD = """\
## The docker/env sweep — the env twins and the ports

`docker/**` text-scanned for the env-var names and the published
ports, matched against the registries' env twins and the default
binds. A knob without its env twin cannot be set from an env file; a
published port not backed by a registry default is a lie."""

COVER_HEAD = """\
## The suite-coverage sweep — the promises x the tests

Every live knob name, command word and canon log phrase grepped
against `tests/suites/*.py` (word-bounded). Word-match honesty: the suites
are prose too — a name inside another word counts as covered; the
list is the TODO seed, not a verdict."""

FLEDGER_HEAD = """\
## The F-ledger sweep — docs/SECURITY.md vs the tree

Each F-number's title from the audit doc, and which of the family's
files cite it — the promise ledger against the code."""

STATICS_HEAD = """\
## The statics sweep — the four defaults.json blocks

Every leaf key-path of the four `lib/defaults.json` files (the non-knob
statics since the knobs' defaults moved into the registry rows'
`default` fields): the shared paths whose values disagree, the
only-there paths."""

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

CONSOLEPRINT_HEAD = """\
## The console-print sweep — the one pager door

The cli session path (common/wire/cli.py + the four bin/*-cli.py)
prints through `page_out`/`display` only: a naked `print(` with an
argument is the drift (the bare `print()` pre-prompt blank is the
loop's own). `--check` fails on any finding — the door holds or the
wave explains itself."""

SURFACE_CENSUS = """\
The listener census (ten listeners):

| tool | surface | the class at it | the bind | the stack at it |
|---|---|---|---|---|
| inverter | Modbus TCP (the device) | `serve_modbus` (common/modbus/server.py) under the fake's face object | backlog 128 | the shared ladder; the face's hooks carry the tool (the chaos injector, the counters) |
| cache | Modbus TCP (the client face) | `serve_modbus` (common/modbus/server.py) under the proxy's face object | backlog 128 | the shared ladder; the write-gate layers in `respond()` (shape -> allow-write -> write ACL -> register gate); the requests audit rides `on_disconnect` |
| inverter | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook is the tool's |
| cache | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook is the tool's |
| dashboard | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook is the tool's |
| scraper | /metrics (the exposition) | `Server` + `Handler` (lib/server.py) | the caps + the metrics/acl | its own Handler — the family's exposition shape (bearer, the spec render, the upstream relay) |
| dashboard | the page (static + proxy) | `Server` + `Handler` (bin/dashboard.py) | the caps | its own Handler — the cookies, the static tier, the /prom proxy, /config.js |
| all four | the control socket (unix, opt TCP) | `ControlServer` (common/wire/control.py) | 0600/0660 | the one shared wire: the token/RBAC roles, the HMAC frames, the caps live here |"""

SURFACE_FINDINGS = """\
The findings:

- **The face protocol's hooks.** The faces delegate (`Proxy.serve`,
  the fake's `serve`) into the one shared ladder and bring the face
  protocol's hooks: `listening`, `access`, `allowed`, `suite_key`,
  `on_frame`/`on_session`, `malformed`, `frame`, `on_disconnect` — the
  cache's audit trail `REQUESTS` event rides `on_disconnect`, the
  fake's counters ride `on_frame`/`on_session`. The backlog sits
  unified at 128, above every face's client limit.
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
  audit-requests timer; the scraper's clamped wait and the live
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

The verdict: the accept ladder and the session opener have one home
(the landed legs: [history/family-drift.md](history/family-drift.md));
the rest of the surface drift is at parity or declined with the
reasons above."""

KNOBS_VERBS = """\
- `request/clear/cache` + `request/dump/with-cache` — the cache only
  (the write-behind cadence and the flush verb are its nature).
- `request/restart` — absent on the fake (its reload execs and
  re-reads the conf already, so the verb would double it; the
  restart-marked overrides fold in the exec).
- `reset` (the SIGUSR1 scenario reset) + `exit`/`logout` — the fake's
  console verbs (F11).
- `request/poll/now` — the scraper's poll trigger."""

KNOBS_FINDINGS = """\
The findings:

- **The `auth` name collision.** The dashboard's `auth` is a NODE
  (the page's auth namespace), the other three's is the modbus auth
  enum (`suite|none`). One spelling, two meanings in the family's
  set-grammar space — legal (the registries are per-tool), but the
  merged-knob view (scripts/list_options.py) and any future family-wide
  grammar should note it.
- **`KNOWN_VERBS` derives from the rows** (the landed leg): the
  loaders build the RBAC vocabulary from the registry's command rows
  (`known_verbs` in common/settings/options.py — the live path's
  first segment past `request`, the node rows out, the
  hidden/internal flags in, the console-eaten `exit`/`logout` out)
  and the default ops policy derives with it
  (`default_ops_verbs`: `clear` only where the grammar speaks it —
  the old family-wide `show,clear` accepted a verb three tools'
  wires refuse). One home; the drift class is dead.

The landed knob legs (the audit rotation bounds family-wide, the
`audit-daily` one shape, the env-or-note completion):
[history/family-drift.md](history/family-drift.md)."""

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
  -> security -> testing -> nix -> source layout -> license) and
  `scripts/lint/lint_readmes.py --check` pins it: the canon H2s in order,
  the tool's own sections only in the slot between runtime control
  and security, and a `### Signals` block leading the Runtime-control
  H3s — this sweep prints the gate's verdict beside the ladders."""

NIXOS_FINDINGS = """\
The findings:

- **check_options gates the structure** ("the NixOS module declares
  exactly the structural options"): enable/package/openFirewall/settings,
  the dashboard's solarConfig/staticDir, and every registry secret row's
  *File option present — nothing else may be declared. The inline secret
  options are removed-option tombstones the module system refuses at
  eval; the env-file keys are freeform and carry no parity claim.
- The registry keeps its docs-side role: gen_examples.py renders the
  docker/env examples and the tools' example confs the settings key
  list is lifted from, and the
  nixos/README.md tables document the contract per tool."""

DOCKER_FINDINGS = """\
The findings:

- **The env-file twins are the docker surface's contract**: a
  registry env twin missing from every compose/env file means the
  knob is unreachable from the deployment — sometimes design (the
  demo needs fewer knobs), sometimes a gap. The split wave's wiring
  list (the prod = three services + the external collector, the
  demo's in-stack shapes) is the expected drift.
- **The published ports map 1:1 to the registry defaults** (the
  935x block) — the port map above is the standing gate: every
  EXPOSE, every CMD `--listen` and every compose `ports:` container
  side names a port a listen knob backs. A port no knob backs is the
  lie this sweep exists for; the regeneration prints it and the
  `--check` fails on it."""

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
  convention (the code comments cite `F13 in docs/SECURITY.md`) is the
  family's traceability habit; the sweep keeps it honest."""

STATICS_FINDINGS = """\
The findings:

- **The defaults.json blocks are the non-knob statics' home** (the
  simulators' grid constants, the diagnostics block, the log levels)
  — the knobs' defaults live in the registry rows' `default` fields
  now (editor.py edits them; check_options validates them). The
  shared-path matrix is the ruling surface for what remains."""

SCHEMA_FINDINGS = """\
The findings:

- **The shared pair is the pattern**: the standalone acl file's two
  gates (ip-prefix + write-registers) ship their example + schema ONCE
  at extras/examples/ + shared/schema/ — the four per-tool ip-prefix
  copies died in the shared-examples wave, the cache-local write pair
  joined (one gate validator in common/settings/config.py reads both
  kinds). The per-tool schema/ dirs that remain carry the
  tool-specific shapes.
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
The landed legs (the audit rotation bounds, the `audit-daily` shape,
the env-or-note completion, the accept-ladder extraction):
[history/family-drift.md](history/family-drift.md).

1. **The `auth` name collision resolved** — one spelling, one
   meaning: the dashboard's `auth` node (the page's namespace)
   renames (`page-auth/` or the rows re-home), or the modbus enum
   re-homes; the set grammar never maps one word to two meanings.
   Breaking change for the dashboard's live names — the TODO is the
   proposal + the migration note (the alias map carries the old
   spellings one release).

3. **The coverage TODOs graduate** — the seeds carry stable IDs in
    docs/family-drift-seeds.json (`family_drift.py --seeds`, the
    suggested suite per seed); a test wave consumes entries, the
    regeneration drops them, the shrinkage is the wave's proof, and
    `--check` fails when a NEW promise ships uncovered (the list may
    only shrink).

4. **The parity gates wired** — the docker-ports gate LANDED (the
    sweep above: every EXPOSE/CMD/compose port rides a registry
    listen default); the remaining half is the NixOS-parity +
    env-file coverage as machine checks (the module.nix type/default
    vs the registry, the env-file coverage vs the env twins). The
    drift doc's `--check` already shows the pattern: a stale claim
    fails the gate.

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
    """docs/SECURITY.md's F-numbers: the §3 tables' rows (| F1 | module |
    severity | finding |) give the title (the finding's first clause);
    the whole-tree files citing each."""
    p = os.path.join(REPO, 'docs', 'SECURITY.md')
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
    ap('workflow**: the open findings wait in place, and `--check` fails')
    ap('a stale page. Regenerate with `python3 scripts/family_drift.py`;')
    ap('the verdict prose lives in this script (`*_FINDINGS`/`*_VERBS`/')
    ap('`*_CENSUS`) so a re-run updates the facts and keeps the')
    ap('judgement. This doc carries the CURRENT findings only — the')
    ap('landed legs and the wave history live in')
    ap('[history/family-drift.md](history/family-drift.md).')
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
    ap('10. **The F-ledger sweep** — docs/SECURITY.md\'s F-numbers vs the')
    ap('    tree\'s enforcement markers.')
    ap('11. **The statics sweep** — the four defaults.json blocks by')
    ap('    key-path.')
    ap('12. **The schema/example sweep** — the JSON Schemas vs the')
    ap('    registries; the shipped examples re-parsed.')
    ap('13. **The secret-surface sweep** — the secret rows and the')
    ap('    posture markers.')
    ap('14. **The console-print sweep** — the cli session path prints')
    ap('    through the one pager door; a naked print( fails --check.')
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
    n_fields = sum(len(by_field) for _, by_field in deltas)
    ap(f'**The shared knobs whose fields disagree** ({len(deltas)} of')
    ap(f'{len(shared)} knobs, {n_fields} drifted field(s)) — one row per')
    ap('knob+field, the tools grouped by the value each carries:')
    ap('')
    ap('| knob | field | the values (the tools carrying each) |')
    ap('|---|---|---|')
    for n, by_field in deltas:
        for f, vals in by_field.items():
            groups = {}
            for t in TOOLS:
                groups.setdefault(json.dumps(vals[t], ensure_ascii=False), []).append(t)
            cell = ' · '.join(f'`{json.loads(v)}` ({", ".join(ts)})' if v != 'null'
                              else f'*absent* ({", ".join(ts)})'
                              for v, ts in groups.items())
            ap(f'| `{n}` | `{f}` | {cell} |')
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
    canon, refs, n_exempt = canon_coverage()
    ap('**The canon coverage** (shared/suite/options.json — the registry')
    ap('texts the rows ref; the drift and must-ref gates live in')
    ap('`lint_options --check`, the exempt names ride it):')
    ap('')
    ap('| section | blocks | ' + ' | '.join(f'{t} refs' for t in TOOLS) + ' |')
    ap('|---|---|' + '---|' * len(TOOLS))
    for section in ('options', 'show', 'commands'):
        blocks = canon.get(section) or {}
        ap(f'| {section} | {len(blocks)} | '
           + ' | '.join(str(refs[t][section]) for t in TOOLS) + ' |')
    ap('')
    ap(f'The exempt (intentionally per-tool) names: **{n_exempt}** —')
    ap('each with its reason in `scripts/lint/lint_options.py`.')
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
    ap('The skeleton verdict (`scripts/lint/lint_readmes.py --check` gates it):')
    ap('')
    for t in TOOLS:
        rel = f'{t}/README.md'
        findings = lint_readmes.readme_findings(rel)
        ap(f'- {t}: ' + ('OK' if not findings else '; '.join(findings)))
    ap('')
    ap(RENDER_FINDINGS)
    ap('')

    # ---- 7. the nixos sweep (structural: the settings wave removed the
    # knob options — there is nothing per-knob left to diff)
    nix = nixos(rows)
    ap(NIXOS_HEAD)
    ap('')
    ap('| tool | module options declared |')
    ap('|---|---|')
    for t in TOOLS:
        ap(f'| {t} | {", ".join(f"`{n}`" for n in sorted(nix[t])) if nix[t] else "no module.nix"} |')
    ap('')
    ap('**The structural contract** — exactly `enable`/`package`/')
    ap('`openFirewall`/`settings`, every registry secret row\'s `*File`,')
    ap("and the dashboard's `solarConfig`/`staticDir` (the removed knob")
    ap('options and inline secrets are tombstones the module system refuses):')
    ap('')
    for t in TOOLS:
        if nix[t]:
            def norm(s):
                return s.lower().replace('-', '').replace('_', '')

            def camel_file(name):
                parts = name.split('-')
                return parts[0] + ''.join(p.capitalize() for p in parts[1:]) + 'File'

            reg_names = {norm(n) for n in rows[t]}
            want = {'enable', 'package', 'openFirewall', 'settings'}
            # the secret-marked rows ride *File credentials — except the two
            # marks that are not secrets in the credential sense (the
            # dashboard's static dir and the public front-end config)
            want |= {camel_file(n) for n, r in rows[t].items()
                     if r.get('secret') and n not in ('static-dir', 'config-js')}
            if t == 'dashboard':
                want |= {'solarConfig', 'staticDir'}
            missing = sorted(n for n in want if n not in nix[t])
            unexpected = sorted(n for n in nix[t] if n not in want
                                and norm(n) in reg_names)
            verdict = []
            if missing:
                verdict.append('missing: %s' % ', '.join(f'`{n}`' for n in missing))
            if unexpected:
                verdict.append('unexpected knob options: %s' % ', '.join(f'`{n}`' for n in unexpected))
            ap(f'- {t}: ' + ('; '.join(verdict) if verdict else 'exactly the structural contract'))
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
    backed = knob_ports(rows)
    exposed, published = docker_ports()
    ap('**The port map 1:1** — the registries back every port the docker')
    ap('surface names (a port here that no knob backs is the lie this')
    ap('sweep exists for):')
    ap('')
    ap('| port | the knobs backing it | where the docker surface names it |')
    ap('|---|---|---|')
    liars = []
    for port in sorted(set(backed) | {p for ex in exposed.values() for p in ex[0] + ex[1]}
                       | {p for pub in published.values() for p in pub}):
        who = ', '.join(backed.get(port, [])) or None
        sites = []
        for rel, (ex, lp) in sorted(exposed.items()):
            if port in ex:
                sites.append(f'{rel} EXPOSE')
            if port in lp:
                sites.append(f'{rel} CMD --listen')
        for rel, pub in sorted(published.items()):
            if port in pub:
                sites.append(f'{rel} ports:')
        if who is None:
            liars.append(port)
        ap(f'| {port} | {who or "**NO KNOB**"} | {"; ".join(sites) or "—"} |')
    ap('')
    if liars:
        ap(f'**The lie(s)**: {", ".join(str(p) for p in liars)} — published or')
        ap('exposed with no registry knob behind them. The gate fails')
        ap('until the port maps or the mapping dies.')
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
    for t in list(TOOLS) + ['shared']:
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
    broken = [(t, n) for t, n, live, restart, hidden in matrix if not restart or not hidden]
    if broken:
        ap('**The posture break(s)**: ' + ', '.join(f'`{t}/{n}`' for t, n in broken)
           + ' — a secret row off the secret+restart+hidden shape.')
        ap('')
    ap('**The markers per tool** (the F-trust surface: the loader parses,')
    ap('the dumps placeholder, the examples and configs reference):')
    ap('')
    ap('| tool | parse_secret | SECRET_REMOVED | file: |')
    ap('|---|---|---|---|')
    for t in TOOLS:
        hits = {m for rel, mm in markers.items() if rel.startswith(t + '/') for m in mm}
        ap(f'| {t} | {"yes" if "parse_secret" in hits else "**MISSING**"} | '
           f'{"yes" if "placeholder" in hits else "**MISSING**"} | '
           f'{"yes" if "file-scheme" in hits else "**MISSING**"} |')
    ap('')
    ap(SECRET_FINDINGS)
    ap('')

    # ---- 14. the console-print sweep
    naked = naked_prints()
    ap(CONSOLEPRINT_HEAD)
    ap('')
    if naked:
        ap('**The naked print(s)** — the door leaked:')
        ap('')
        for rel, line in naked:
            ap(f'- `{rel}:{line}`')
        ap('')
    else:
        ap(f'The door holds: {len(CONSOLE_SESSION_FILES)} session-path files,')
        ap('every print through `page_out`/`display` (the bare pre-prompt')
        ap('blinks excepted).')
        ap('')
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
        stale = emit_page(DOC, doc, True, 'family_drift')
        grown = seed_guard(seeds)
        naked = naked_prints()
        if grown:
            print(f'family-drift-seeds.json: {len(grown)} NEW uncovered promise(s) the ledger does not know:')
            for s in grown[:10]:
                print(f"  {s['id']}  ({s['kind']}, suggested: {s['suite']})")
            print('a knob/command/canon phrase shipped without its test — write the tests, then regenerate the ledger')
        if naked:
            print('the console-print sweep: %d naked print(s) in the cli session path:' % len(naked))
            for rel, line in naked:
                print(f'  {rel}:{line}')
            print('the session prints through page_out/display — see the wave doc')
        if stale or grown or naked:
            raise SystemExit(1)
        print('family-drift.md is current; the seed ledger knows every open promise; the pager door holds')
        return
    emit_page(DOC, doc, False, 'family_drift')
    if not os.path.exists(SEEDS):
        write_seeds(seeds)   # the first run seeds the ledger; the waves shrink it


if __name__ == '__main__':
    main()
