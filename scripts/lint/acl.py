#!/usr/bin/env python3
"""Lint and reformat the standalone acl files — the json a cache acl
option's file:<path> points at (extras/examples/acl-write-registers.json
is the shipped write example, extras/examples/acl-ip-prefix.json the
shared IP-kind one — both under extras/examples/; scripts/editor.py acl
edits one). A device profile's
embedded acl/write gate belongs to the sibling profile.py (lint +
format, one script).

The root of the file IS the gate object: an optional terse-ASCII "desc"
and the ordered "rules" list — one {"type": "allow"|"deny", matcher-key:
matcher} object per rule (+ an optional "desc" each). THE MATCHER KEY IS
THE KIND: "range" is the register kind (a "START:COUNT" range, a list of
them, or the bare word "any"), "prefix" is the IP kind (an IP or IP/prefix,
comma-separated, or "any"). The gate "type" names the schema —
"write-registers" (range rules) or "ip-prefix" (prefix rules) — and must
agree with the rules' key when spelled. ONE GRAMMAR PER GATE: the first
matcher key pins
the file, and a file whose rules mix "range" and "prefix" refuses. The
chain is a whitelist: it reads top to bottom, the LAST matching rule
decides, and a client/register no rule decides refuses (the default deny
any).

The lint: the loader's schema (common/settings/config.py's
_write_gate_object —
the old spellings refuse as unknown keys, a gate that gates nothing is a
config error, the whole-space deny is [{"type": "deny", "range": "any"}]
for registers, "prefix": "any" for IPs) plus what the loader cannot say:
a matcher that decides a register/address twice, a rule that decides
nothing (an empty list), and — the big one — a DEAD rule: everything it
decides a later rule re-decides, so it never speaks (the last match
wins). The register kind rides the decision bitmasks; the IP kind rides
family-tagged address intervals (v4 and v6 share no number line; "any"
is the '*' family both fall inside). When the checks find nothing, the
file is handed to the real loader as the final word (both kinds allowed —
the daemon's readers pin their own).

The canonical layout, so hand styles stop diverging: two-space indent,
the "desc" first, the rules one per line (keys type -> range/prefix ->
desc, the unknown keys after), the matchers inline, the trailing newline.
The content is untouched — descs, matchers and their spellings land
byte-for-byte as parsed.

  python3 scripts/lint/acl.py                # lint the shipped example(s)
  python3 scripts/lint/acl.py my.json        # lint one file
  python3 scripts/lint/acl.py format my.json # reformat in place
  python3 scripts/lint/acl.py format --check # the drift report only, rc 1 = off-form
  python3 scripts/lint/acl.py format --diff  # show the unified diff, no write
"""
import glob
import ipaddress
import json
import os
import sys

try:
    from lint._common import diff_dump, fmt_one, grammar, lint_desc, lint_ranges
except ImportError:   # the bare run — the script's own dir is sys.path[0]
    from _common import diff_dump, fmt_one, grammar, lint_desc, lint_ranges

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(REPO, 'apps', 'cache'), REPO):
    sys.path.insert(0, _p)

# `lib` is contested: the cache's own lib/ package (the gate loader here)
# and the scripts' common lib (lib/) both answer to it — and a process that
# imported a SIBLING lint module first already bound the scripts' lib (the
# import order inside lint/ is free). The house's
# one-module-named-`lib`-at-a-time dance: save the bound package, fetch the
# cache's loader while the name is free, bind the saved package back.
_lib_saved = sys.modules.pop('lib', None)
for _k in [k for k in sys.modules if k.startswith('lib.')]:
    sys.modules.pop(_k)
from lib.config import _GATE_TYPES, load_write_gate_file   # noqa: E402
from lib.statics import MAX_REGISTERS         # noqa: E402
if _lib_saved is not None:
    sys.modules['lib'] = _lib_saved


def lint_matcher(v, where, kind='range'):
    """One rule matcher -> (issues, spans): the spans the matcher
    decides, for the overlap and dead-rule passes. The register kind's
    span is the (start, end) half-open pair; the IP kind's is the
    (family, lo, hi) inclusive triple — family-tagged, for v4 and v6
    share no number line."""
    if kind == 'prefix':
        return lint_prefix_matcher(v, where)
    return lint_ranges(v, where, MAX_REGISTERS)


def lint_prefix_matcher(v, where):
    """The IP-kind matcher -> (issues, spans): the bare word 'any' (the
    '*' family — every address), or a comma-separated string of IP
    addresses / IP prefixes, strict CIDR (host bits set refuse, one
    family per matcher); the spans the family-tagged inclusive address
    intervals the matcher decides."""
    issues = []
    if not isinstance(v, str):
        return ['%s must be "any" or a comma-separated IP/IP-prefix string' % where], []
    t = v.strip()
    if t.lower() == 'any':
        return issues, [(t, ('*', 0, (1 << 128) - 1))]
    spans = []
    fam = None
    first = None
    for x in [s.strip() for s in t.split(',')]:
        if not x:
            issues.append('%s: empty item in the comma-separated prefix list' % where)
            continue
        try:
            net = ipaddress.ip_network(x, strict=True)
        except ValueError:
            try:
                wide = ipaddress.ip_network(x, strict=False)
                issues.append('%s: %r has host bits set — spell the network %s'
                              % (where, x, wide.with_prefixlen))
            except ValueError:
                issues.append('%s: %r must be an IP or IP/prefix' % (where, x))
            continue
        if fam is None:
            fam = net.version
            first = x
        elif net.version != fam:
            issues.append('%s: the matcher mixes IPv4 and IPv6 (%s and %s)' % (where, first, x))
            continue
        lo = int(net.network_address)
        spans.append((x, (str(net.version), lo, lo + net.num_addresses - 1)))
    for j in range(len(spans)):
        for k in range(j + 1, len(spans)):
            (la, (_, s0, e0)), (lb, (_, s1, e1)) = spans[j], spans[k]
            if s0 <= e1 and s1 <= e0:
                issues.append('%s: the matcher decides addresses twice (%s and %s overlap)'
                              % (where, la, lb))
    return issues, spans


def _merge_intervals(spans):
    """[(family, lo, hi)] -> the disjoint merged union; touching
    intervals join, families never mix ('*' merges with '*' only)."""
    out = []
    for fam, lo, hi in sorted(spans, key=lambda s: (s[0], s[1], s[2])):
        if out and out[-1][0] == fam and lo <= out[-1][2] + 1:
            out[-1] = (fam, out[-1][1], max(out[-1][2], hi))
        else:
            out.append((fam, lo, hi))
    return out


def _prefix_dead(masks, base):
    """The IP kind's dead-rule pass: a rule is dead when every address
    interval it decides is re-decided by the union of the LATER rules'
    (the last match wins). An 'any' rule is dead only when the later
    union covers both families whole."""
    def covered(fam, lo, hi, union):
        if fam == '*':
            return (covered('4', 0, (1 << 32) - 1, union)
                    and covered('6', 0, (1 << 128) - 1, union))
        return any((lf == fam or lf == '*') and llo <= lo and hi <= lhi
                   for lf, llo, lhi in union)
    issues = []
    later = []
    for i in range(len(masks) - 1, -1, -1):
        spans = masks[i]
        if spans:
            if all(covered(fam, lo, hi, later) for _l, (fam, lo, hi) in spans):
                issues.append('%s rule %d: the rule is dead — every address it decides a later '
                              'rule re-decides (the last match wins)' % (base, i + 1))
            later = _merge_intervals(later + [s for _l, s in spans])
    return issues


def lint_gate(gate, base):
    """The gate object -> the issue list. The matcher key pins the kind:
    "range" the registers, "prefix" the addresses — a file mixing the
    two keys is the finding (one kind per gate). The no-op and dead-rule
    passes ride the per-rule decisions (a rule is dead when the union of
    the LATER rules' decisions covers its own — the last match wins):
    the register kind as decision bitmasks, the IP kind as merged
    family-tagged address intervals."""
    issues = []
    if not isinstance(gate, dict):
        return issues + ['%s must be the gate object: {"desc": ..., "type": ..., "rules": '
                         '[{"type": "allow"|"deny", "range"|"prefix": ...}]}' % base]
    unknown = sorted(k for k in gate if k not in ('desc', 'type', 'rules'))
    if unknown:
        issues.append('%s: unknown key(s) %s ("desc", the optional gate "type" and the '
                      '"rules" list — one {"type": "allow"|"deny", "range"|"prefix": ...} '
                      'object per rule)' % (base, ', '.join(unknown)))
    gate_type = gate.get('type')
    if gate_type is not None and gate_type not in _GATE_TYPES:
        issues.append('%s: unknown gate "type" %r (write-registers | ip-prefix)'
                      % (base, gate_type))
        gate_type = None
    issues += lint_desc(gate.get('desc'), base)
    rules = gate.get('rules')
    if not isinstance(rules, list) or not rules:
        return issues + ['%s: the "rules" list is missing or empty (a gate that gates nothing '
                         'is a config error — spell the whole-space deny as '
                         '[{"type": "deny", "range": "any"}], or "prefix": "any" for the '
                         'IP kind)' % base]
    kind = None
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        has = [k for k in ('range', 'prefix') if k in rule]
        if len(has) > 1:
            issues.append('%s rule %d: the rule carries both "range" and "prefix" — one kind '
                          'per gate (range matches registers, prefix matches IPs)'
                          % (base, i + 1))
        elif has and kind and has[0] != kind:
            issues.append('%s: the rules mix "range" and "prefix" — one kind per gate '
                          '(range matches registers, prefix matches IPs)' % base)
        elif has:
            kind = has[0]
    if gate_type in _GATE_TYPES:
        want = _GATE_TYPES[gate_type]
        if kind and want != kind:
            issues.append('%s: the gate "type" %s matches by "%s" — the rules match by "%s"'
                          % (base, gate_type, want, kind))
        elif not kind:
            kind = want   # a typed gate: the rules must match by the type's key
    elif not gate_type and kind == 'prefix':
        issues.append('%s: the gate matches by "prefix" and carries no "type" — spell '
                      '"type": "ip-prefix"' % base)
    masks = []
    for i, rule in enumerate(rules):
        where = '%s rule %d' % (base, i + 1)
        if not isinstance(rule, dict) or not rule:
            issues.append('%s must be an object with a "type" (allow/deny) and a '
                          '"range" or "prefix"' % where)
            masks.append(None)
            continue
        unknown = sorted(k for k in rule if k not in ('type', 'range', 'prefix', 'desc'))
        if unknown:
            issues.append('%s: unknown key(s) %s (type/range-or-prefix/desc)'
                          % (where, ', '.join(unknown)))
        verb = rule.get('type')
        if verb not in ('allow', 'deny'):
            issues.append('%s: "type" must be allow or deny, got %r' % (where, verb))
        has = [k for k in ('range', 'prefix') if k in rule]
        if len(has) > 1:   # the both-keys finding already fired — no grammar to run
            masks.append(None)
            continue
        key = has[0] if has else None
        if key is None:
            issues.append('%s: the rule needs a %s'
                          % (where, '"prefix"' if kind == 'prefix' else '"range"'))
            masks.append(None)
            continue
        issues += lint_desc(rule.get('desc'), where)
        m_issues, spans = lint_matcher(rule[key], where, key)
        issues += m_issues
        if kind and key != kind:   # the mixed-in rule: the scan's finding covers it
            masks.append(None)
            continue
        if key == 'prefix':   # the overlap pass ran in the matcher lint
            masks.append(None if m_issues else spans)
            continue
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
    if kind != 'prefix':
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
    else:
        issues += _prefix_dead(masks, base)
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
        return 0, ['%s: the root must be the gate object: {"desc": ..., "type": ..., '
                   '"rules": [...]}' % base], text, None
    if 'acl' in data:
        issues.append('%s: the root IS the gate — an "acl" key is the full-profile shape and '
                      'refuses (move the gate object up, or lint the profile with '
                      'profile.py)' % base)
    rules = data.get('rules')
    n_rules = len(rules) if isinstance(rules, list) else 0
    issues += lint_gate(data, base)
    if not issues:
        try:
            load_write_gate_file(path, base, allow=tuple(_GATE_TYPES))
        except SystemExit as e:
            issues.append('%s: the loader refuses: %s' % (base, e))
    return n_rules, issues, text, fmt_gate(data)


def fmt_rule(rule):
    """One rule on one line, keys in the family order, extras after."""
    return fmt_one(rule, ('type', 'range', 'prefix', 'desc'))


def fmt_gate(gate):
    """The canonical file: the desc, the gate type, then the rule list
    one rule per line, the unknown keys after — two-space indent,
    trailing \\n."""
    keys = [k for k in ('desc', 'type', 'rules') if k in gate] \
        + [k for k in gate if k not in ('desc', 'type', 'rules')]
    rows = []
    for k in keys:
        if k == 'rules' and isinstance(gate['rules'], list) and gate['rules']:
            rows.append('  "rules": [\n%s\n  ]' % ',\n'.join('    ' + fmt_rule(r)
                                                             for r in gate['rules']))
        else:
            rows.append('  %s: %s' % (json.dumps(k), json.dumps(gate[k])))
    return '{\n' + ',\n'.join(rows) + '\n}\n'


def main():
    mode, check, diff, paths = grammar(sys.argv[1:])
    if mode == 'usage':
        return 2
    write = mode == 'format' and not check and not diff
    if not paths:
        paths = sorted(p for p in glob.glob(os.path.join(REPO, 'extras', 'examples', '**', 'acl-*.json'),
                                            recursive=True)
                       + glob.glob(os.path.join(REPO, 'apps', 'cache', '**', 'acl-*.json'),
                                            recursive=True)
                       + glob.glob(os.path.join(REPO, 'apps', 'scraper', '**', 'acl-*.json'),
                                   recursive=True)
                       + glob.glob(os.path.join(REPO, 'apps', 'inverter', '**', 'acl-*.json'),
                                   recursive=True)
                       + glob.glob(os.path.join(REPO, 'apps', 'dashboard', '**', 'acl-*.json'),
                                   recursive=True)
                       if not p.endswith('.schema.json'))   # the JSON Schemas OF the acl files lint nothing
        if not paths:
            print('no acl-*.json file under extras/examples/, apps/cache/, apps/scraper/, apps/inverter/ or apps/dashboard/ — pass the path(s)')
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
                diff_dump(text, canon, rel)
    print('lint: %d file(s), %s' % (len(paths), 'issues above' if bad else 'all clean'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
