#!/usr/bin/env python3
"""Verify the audit trails' hash chains (docs/SECURITY.md F10): every entry
carries a short chained hash in its hash= token —
`<stamp> AUDIT application=<TAG> tag=<writer> instance=<id> type=<type>
hash=<hash> [<detail kv words>]` — chained to the writer's previous entry:
h = sha256(prev | stamp | tools | tag + instance + type + detail), 12 hex
chars, chained per (application, writer, instance) triple so interleaved
writers — and several instances of one tool — verify independently. The
validator speaks the current grammar only: a pre-KV line reads malformed.

  python3 dev/gates/audit_verify.py [FILE|- ...]      # default: the family's XDG trails
  python3 dev/gates/audit_verify.py -q ~/.local/state/modbus-cache/audit.log
  python3 dev/gates/audit_verify.py -v ~/.local/state/modbus-cache/audit.log   # the per-entry walk
  python3 dev/gates/audit_verify.py --verbose -       # --verbose, the same flag spelled long
  journalctl -u modbus-cache | python3 dev/gates/audit_verify.py -

-v/--verbose walks the trail per entry — one row each: the line number, the
chain key, the stamp, the type, the hash and the verdict (`anchored` — the
key's first visible entry (the older ones may have rotated away or belong to
a sibling file), `chained` — the recomputed hash links it to the previous
entry of the same key, `broken` — it does not, `unsigned` — no hash, or
`malformed` — not an audit line at all).

For a real file the rotated backups (FILE.1 .. FILE.16) are verified first
(oldest last-written first), so a chain that crossed a rotation still
validates end to end. Per entry: chained (recomputed and matched), unsigned
(no hash — a pre-chain line or one whose hash was stripped; reported, chain
state unchanged) or BROKEN (the recomputed hash does not match — the line,
its neighbours or its order were tampered with). Exit 0 = every chain holds,
1 = at least one broken/malformed entry.
"""
import os
import sys

here = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.runtime.audit import entry_body, entry_hash, parse_entry_hash, default_path

DEFAULT_TRAILS = ('modbus-cache', 'modbus-scraper', 'fake-inverter')


def split_line(line):
    """'<stamp> AUDIT application=<TAG> tag=<writer> instance=<id> ...' ->
    (stamp, key, tools) — the key names the writer's chain (the tool's tag +
    its role + its instance) and tools is the hash material's tag word. None
    (malformed) is the rest's business (the shared parsers)."""
    parts = line.split(' ')
    if len(parts) < 7 or parts[1] != 'AUDIT' or not parts[2].startswith('application=') \
            or not parts[4].startswith('instance='):
        return None
    tools = parts[2][12:]
    return parts[0], '%s:%s:%s' % (tools, parts[3][4:], parts[4][9:]), tools


def verify_stream(name, lines, quiet, verbose=False):
    """One file (or stdin): per-prefix chain walk. Returns (broken, unsigned, events).
    Each prefix's chain anchors at its first visible entry (the writer's older
    entries may have rotated away or belong to a sibling file) — continuity is
    verified from there onward. verbose prints one row per entry: the line
    number, the chain key, the stamp, the type, the hash and the verdict."""
    chains = {}                    # prefix -> last hash (None before the anchor)
    broken, unsigned, events = [], 0, 0
    for no, raw in enumerate(lines, 1):
        line = raw.rstrip('\n')
        if not line.strip():
            continue
        events += 1
        parsed = split_line(line)
        h = parse_entry_hash(line)
        if parsed is None:
            broken.append((no, '-', 'not an audit line (malformed)'))
            if verbose:
                print('     line %d — malformed' % no)
            continue
        stamp, key, tools = parsed
        if h is None:
            unsigned += 1
            if verbose:
                print('     line %d [%s] %s unsigned' % (no, key, stamp))
            continue
        prev = chains.get(key)
        broken_here = prev is not None and \
            entry_hash(prev, stamp, tools, entry_body(line)) != h
        if verbose:
            parts = line.split(' ')
            etype = parts[5][5:] if parts[5].startswith('type=') else parts[5]
            print('     line %d [%s] %s %s hash=%s %s'
                  % (no, key, stamp, etype, h,
                     'broken' if broken_here else ('anchored' if prev is None else 'chained')))
        if broken_here:
            broken.append((no, key, 'hash mismatch (the entry, its neighbours or the order were tampered with)'))
        chains[key] = h
    return broken, unsigned, events


def verify_path(path, quiet, verbose=False):
    """One path plus its rotated backups, oldest first. Returns (ok, summary)."""
    backups = ['%s.%d' % (path, i) for i in range(16, 0, -1) if os.path.exists('%s.%d' % (path, i))]
    ordered = backups + ([path] if os.path.exists(path) else [])
    if not ordered:
        return True, 'missing'
    lines = []
    for f in ordered:
        with open(f, encoding='utf-8', errors='replace') as fh:
            lines.extend(fh.readlines())
    if verbose and len(ordered) > 1:
        print('%s:' % path)
        for f in ordered:
            print('     backup %s' % f)
    broken, unsigned, events = verify_stream(path, lines, quiet, verbose)
    label = '%s%s' % (path, (' (+%d backup(s))' % len(backups)) if backups else '')
    if broken:
        print('FAIL %s — %d broken entr(y/ies):' % (label, len(broken)))
        for no, prefix, why in broken[:10]:
            print('     line %d [%s]: %s' % (no, prefix, why))
        return False, label
    if not quiet:
        note = ', %d unsigned' % unsigned if unsigned else ''
        print('OK   %s — %d entr(y/ies)%s' % (label, events, note))
    elif unsigned:
        print('OK   %s — %d entr(y/ies), %d unsigned' % (label, events, unsigned))
    return True, label


def main():
    argv = sys.argv[1:]
    verbose = '-v' in argv or '--verbose' in argv
    quiet = '-q' in argv and not verbose   # verbose wins: the walk answers both
    paths = [a for a in argv if a not in ('-q', '-v', '--verbose')]
    if not paths:
        paths = [default_path(app) for app in DEFAULT_TRAILS]
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            print('no audit trails found (tried the XDG state homes of %s)' % ', '.join(DEFAULT_TRAILS))
            return 0
    ok = True
    for path in paths:
        if path == '-':
            broken, unsigned, events = verify_stream('stdin', sys.stdin.readlines(), quiet, verbose)
            if broken:
                ok = False
                print('FAIL <stdin> — %d broken entr(y/ies):' % len(broken))
                for no, prefix, why in broken[:10]:
                    print('     line %d [%s]: %s' % (no, prefix, why))
            elif not quiet or unsigned:
                note = ', %d unsigned' % unsigned if unsigned else ''
                print('OK   <stdin> — %d entr(y/ies)%s' % (events, note))
        else:
            good, _ = verify_path(path, quiet, verbose)
            ok = ok and good
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
