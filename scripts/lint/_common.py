"""The lint members' shared core, one sibling beside them: the CLI
grammar (`lint` is the default verb and never writes, `format` is the
write verb, --check/--diff report the drift without the write, --check
bare stays the gate spelling), the terse-ASCII desc check, the
START:COUNT range matcher and the one-line-object render the acl and
profile linters both carry, and the --diff emission. The sibling import
is dual-mode — `lint._common` under the package, `_common` on the bare
run (the script's own dir is sys.path[0]) — because the scripts' own
`lib` package is contested (the cache's lib/ owns the name wherever the
cache root precedes scripts/ on the path; lint/acl.py executes with the
cache's binding under editor.py's window). Stdlib only."""
import difflib
import json
import sys


def grammar(args):
    """The lint/ CLI grammar -> (mode, check, diff, paths): mode is 'lint'
    (the default — report only, never writes), 'format' (the write verb;
    --check/--diff make it report/diff only) or 'usage' (lint beside a
    flag — the flags shape format; the usage line prints here).
    paths = the non-verb, non-flag arguments (the member's own flags ride
    in args for the caller to read)."""
    if 'lint' in args and ('--check' in args or '--diff' in args):
        print('usage: lint never writes — --check/--diff shape the format verb')
        return 'usage', False, False, []
    check, diff = '--check' in args, '--diff' in args
    paths = [a for a in args if a not in ('lint', 'format') and not a.startswith('--')]
    return ('format' if 'format' in args else 'lint'), check, diff, paths


def lint_desc(d, where):
    """The terse-ASCII desc check: present means a non-empty ASCII string."""
    if d is not None and (not isinstance(d, str) or not d.strip() or not d.isascii()):
        return ['%s: "desc" must be terse ASCII' % where]
    return []


def lint_ranges(v, where, max_registers):
    """The register matcher -> (issues, spans): the bare word 'any' (the
    whole space), one START:COUNT, or a list of them — the spans the
    matcher decides, for the overlap and dead-rule passes."""
    issues, out = [], []
    if isinstance(v, str):
        t = v.strip().lower()
        if t == 'any':
            return issues, [(t, (0, max_registers))]
        items = [t]
    elif isinstance(v, list):
        items = v
    else:
        return ['%s must be a range ("START:COUNT"), a list of ranges, or "any"' % where], out
    for x in items:
        if not isinstance(x, str) or x.strip().lower() == 'any':
            issues.append('%s: %r must be START:COUNT (the word any stands alone)'
                          % (where, x))
            continue
        t = x.strip().lower()
        try:
            s, c = (int(p) for p in t.split(':'))
        except ValueError:
            issues.append('%s: %r must be START:COUNT' % (where, x))
            continue
        if s < 0 or c < 1 or s + c > max_registers:
            issues.append('%s: range %d:%d out of bounds (0..%d)'
                          % (where, s, c, max_registers - 1))
            continue
        out.append((t, (s, s + c)))
    return issues, out


def fmt_one(entry, order):
    """One object on one line, keys in the family order, extras after."""
    keys = [k for k in order if k in entry] + [k for k in entry if k not in order]
    return json.dumps({k: entry[k] for k in keys})


def diff_dump(text, canon, rel):
    """The --diff spelling: the off-form file against its canonical render,
    the unified diff, no write."""
    sys.stdout.writelines(difflib.unified_diff(
        text.splitlines(True), canon.splitlines(True),
        rel, rel + ' (canonical)'))
