#!/usr/bin/env python3
"""Lint and reformat the standalone write-acl files — the json a cache
--write-registers file:<path> points at (cache/examples/acl-write-registers.json is
the shipped example; scripts/edit_acl.py edits one). A device profile's
embedded acl/write gate belongs to profiles/bin/profile-lint.py +
profile-format.py. The connect acl is the planned second kind
(docs/TODO.md) — the lint speaks the write gate until it lands.

The root of the file IS the gate object: an optional terse-ASCII "desc"
and the ordered "rules" list — one {"type": "allow"|"deny", "range":
matcher} object per rule (+ an optional "desc" each); a matcher is a
"START:COUNT" range, a list of them, or the bare word "any". The chain
is a whitelist: it reads top to bottom, the LAST matching rule decides,
and a register no rule decides refuses (the default deny any).

The lint: the loader's schema (cache/lib/config.py's _write_gate_object —
the old spellings refuse as unknown keys, a gate that gates nothing is a
config error, the whole-space deny is [{"type": "deny", "range": "any"}])
plus what the loader cannot say: a matcher that decides a register twice,
a rule that decides nothing (an empty list), and — the big one — a DEAD
rule: every register it decides a later rule re-decides, so it never
speaks (the last match wins). When the checks find nothing, the file is
handed to the real loader as the final word.

The canonical layout, so hand styles stop diverging: two-space indent,
the "desc" first, the rules one per line (keys type -> range -> desc,
the unknown keys after), the matchers inline, the trailing newline. The
content is untouched — descs, ranges and their spellings land
byte-for-byte as parsed.

  python3 scripts/lint_acl.py                # the shipped example(s)
  python3 scripts/lint_acl.py my.json        # lint + reformat in place
  python3 scripts/lint_acl.py --check        # report only, exit 1 if off-form
  python3 scripts/lint_acl.py --diff         # show the unified diff, no write
"""
import difflib
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(REPO, 'cache'), REPO):
    sys.path.insert(0, _p)

from lib.config import load_write_gate_file   # noqa: E402
from lib.statics import MAX_REGISTERS         # noqa: E402


def lint_desc(d, where):
    if d is not None and (not isinstance(d, str) or not d.strip() or not d.isascii()):
        return ['%s: "desc" must be terse ASCII' % where]
    return []


def parse_range(t, where, issues):
    """'START:COUNT' -> the (start, end) span, or None (said)."""
    try:
        s, c = (int(x) for x in t.split(':'))
    except ValueError:
        issues.append('%s: %r must be START:COUNT' % (where, t))
        return None
    if s < 0 or c < 1 or s + c > MAX_REGISTERS:
        issues.append('%s: range %d:%d out of bounds (0..%d)'
                      % (where, s, c, MAX_REGISTERS - 1))
        return None
    return (s, s + c)


def lint_matcher(v, where):
    """One rule matcher -> (issues, [(label, span)]): the spans the
    matcher decides, for the overlap and dead-rule passes."""
    issues = []
    out = []
    if isinstance(v, str):
        t = v.strip().lower()
        if t == 'any':
            return issues, [(t, (0, MAX_REGISTERS))]
        r = parse_range(t, where, issues)
        if r:
            out.append((t, r))
        return issues, out
    if isinstance(v, list):
        for x in v:
            t = str(x).strip().lower() if isinstance(x, str) else None
            if t == 'any' or t is None:
                issues.append('%s: %r must be START:COUNT (the word any stands alone)'
                              % (where, x))
                continue
            r = parse_range(t, where, issues)
            if r:
                out.append((t, r))
        return issues, out
    return (['%s must be a range ("START:COUNT"), a list of ranges, or "any"' % where], out)


def lint_gate(gate, base):
    """The gate object -> the issue list; the no-op and dead-rule passes
    ride the per-rule decision masks (a rule is dead when the union of
    the LATER rules' masks covers its own — the last match wins)."""
    issues = []
    if not isinstance(gate, dict):
        return issues + ['%s must be the gate object: {"desc": ..., "rules": '
                         '[{"type": "allow"|"deny", "range": "START:COUNT"}]}' % base]
    unknown = sorted(k for k in gate if k not in ('desc', 'rules'))
    if unknown:
        issues.append('%s: unknown key(s) %s ("desc" and the "rules" list — one '
                      '{"type": "allow"|"deny", "range": ...} object per rule)'
                      % (base, ', '.join(unknown)))
    issues += lint_desc(gate.get('desc'), base)
    rules = gate.get('rules')
    if not isinstance(rules, list) or not rules:
        return issues + ['%s: the "rules" list is missing or empty (a gate that gates nothing '
                         'is a config error — spell the whole-space deny as '
                         '[{"type": "deny", "range": "any"}])' % base]
    masks = []
    for i, rule in enumerate(rules):
        where = '%s rule %d' % (base, i + 1)
        if not isinstance(rule, dict) or not rule:
            issues.append('%s must be an object with a "type" (allow/deny) and a "range"' % where)
            masks.append(None)
            continue
        unknown = sorted(k for k in rule if k not in ('type', 'range', 'desc'))
        if unknown:
            issues.append('%s: unknown key(s) %s (type/range/desc)' % (where, ', '.join(unknown)))
        verb = rule.get('type')
        if verb not in ('allow', 'deny'):
            issues.append('%s: "type" must be allow or deny, got %r' % (where, verb))
        if 'range' not in rule:
            issues.append('%s: the rule needs a "range"' % where)
            masks.append(None)
            continue
        issues += lint_desc(rule.get('desc'), where)
        m_issues, spans = lint_matcher(rule['range'], where)
        issues += m_issues
        for j in range(len(spans)):
            for k in range(j + 1, len(spans)):
                (la, (s0, e0)), (lb, (s1, e1)) = spans[j], spans[k]
                if s0 < e1 and s1 < e0:
                    issues.append('%s: the matcher decides registers twice (%s and %s overlap)'
                                  % (where, la, lb))
        if m_issues:
            masks.append(None)
            continue
        mask = 0
        for _label, (s, e) in spans:
            mask |= ((1 << (e - s)) - 1) << s
        masks.append(mask)
    for i, m in enumerate(masks):
        if m == 0:
            issues.append('%s rule %d: the rule is a no-op — an empty list decides '
                          'nothing (drop it, or spell the whole-space deny as "any")'
                          % (base, i + 1))
    later = 0
    for i in range(len(masks) - 1, -1, -1):
        m = masks[i]
        if m and m & later == m:
            issues.append('%s rule %d: the rule is dead — every register it decides a later '
                          'rule re-decides (the last match wins)' % (base, i + 1))
        later |= m or 0
    return issues


def label(path):
    """The display name: repo-relative when the file lives in the repo,
    absolute otherwise."""
    rel = os.path.relpath(path, REPO)
    return rel if not rel.startswith('..') else os.path.abspath(path)


def lint_file(path):
    """One standalone acl file -> (n_rules, issues, text, canonical)."""
    rel = label(path)
    base = 'acl file %s' % rel
    try:
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except OSError as e:
        return 0, ['%s: cannot read: %s' % (base, e)], None, None
    try:
        data = json.loads(text)
    except ValueError as e:
        return 0, ['%s: not valid JSON: %s' % (base, e)], None, None
    issues = []
    if not isinstance(data, dict):
        return 0, ['%s: the root must be the gate object: {"desc": ..., "rules": [...]}'
                   % base], text, None
    if 'acl' in data:
        issues.append('%s: the root IS the gate — an "acl" key is the full-profile shape and '
                      'refuses (move the gate object up, or lint the profile with '
                      'profile-lint.py)' % base)
    rules = data.get('rules')
    n_rules = len(rules) if isinstance(rules, list) else 0
    issues += lint_gate(data, base)
    if not issues:
        try:
            load_write_gate_file(path, base)
        except SystemExit as e:
            issues.append('%s: the loader refuses: %s' % (base, e))
    return n_rules, issues, text, fmt_gate(data)


def fmt_rule(rule):
    """One rule on one line, keys in the family order, extras after."""
    keys = [k for k in ('type', 'range', 'desc') if k in rule] \
        + [k for k in rule if k not in ('type', 'range', 'desc')]
    return json.dumps({k: rule[k] for k in keys})


def fmt_gate(gate):
    """The canonical file: the desc first, then the rule list one rule
    per line, the unknown keys after — two-space indent, trailing \\n."""
    keys = [k for k in ('desc', 'rules') if k in gate] \
        + [k for k in gate if k not in ('desc', 'rules')]
    rows = []
    for k in keys:
        if k == 'rules' and isinstance(gate['rules'], list) and gate['rules']:
            rows.append('  "rules": [\n%s\n  ]' % ',\n'.join('    ' + fmt_rule(r)
                                                             for r in gate['rules']))
        else:
            rows.append('  %s: %s' % (json.dumps(k), json.dumps(gate[k])))
    return '{\n' + ',\n'.join(rows) + '\n}\n'


def main():
    args = sys.argv[1:]
    check, diff = '--check' in args, '--diff' in args
    write = not check and not diff
    paths = [a for a in args if not a.startswith('--')]
    if not paths:
        paths = sorted(glob.glob(os.path.join(REPO, 'cache', '**', 'write-acl.json'),
                                 recursive=True))
        if not paths:
            print('no write-acl file under cache/ — pass the path(s)')
            return 1
    bad = False
    for path in paths:
        rel = label(path)
        n_rules, issues, text, canon = lint_file(path)
        print('%s: %d rule(s), %d issue(s)' % (rel, n_rules, len(issues)))
        for issue in issues:
            print('  - %s' % issue)
            bad = True
        if canon is None:
            bad = True
            continue
        if canon == text:
            continue
        if write:
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(canon)
            print('%s: reformatted' % rel)
        else:
            print('%s: off the canonical layout' % rel)
            bad = True
            if diff:
                sys.stdout.writelines(difflib.unified_diff(
                    text.splitlines(True), canon.splitlines(True),
                    rel, rel + ' (canonical)'))
    print('lint: %d file(s), %s' % (len(paths), 'issues above' if bad else 'all clean'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
