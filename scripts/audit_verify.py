#!/usr/bin/env python3
"""Verify the audit trails' hash chains (docs/AUDIT.md F10): every entry
carries a short hash right after the event name —
`<stamp> AUDIT <PREFIX> <EVENT> <hash> [detail]` — chained to the writer's
previous entry: h = sha256(prev | stamp | prefix | event + detail), 12 hex
chars, chained per writer prefix (CACHE / INV / CLI / CTL) so interleaved
writers verify independently.

  python3 scripts/audit_verify.py [FILE|- ...]      # default: the family's XDG trails
  python3 scripts/audit_verify.py -q ~/.local/state/modbus-cache/audit.log
  journalctl -u modbus-cache | python3 scripts/audit_verify.py -

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
sys.path.insert(0, os.path.dirname(here))   # the repo root — the common/ package

from common.runtime.audit import HASH_LEN, entry_body, entry_hash, parse_entry_hash, default_path

DEFAULT_TRAILS = ('modbus-cache', 'modbus-scraper', 'fake-inverter')


def split_line(line):
    """'<stamp> AUDIT <PREFIX> ...' -> (stamp, prefix) or None (the rest is
    read positionally by the shared parsers)."""
    parts = line.split(' ')
    if len(parts) < 3 or parts[1] != 'AUDIT':
        return None
    return parts[0], parts[2]


def verify_stream(name, lines, quiet):
    """One file (or stdin): per-prefix chain walk. Returns (broken, unsigned, events).
    Each prefix's chain anchors at its first visible entry (the writer's older
    entries may have rotated away or belong to a sibling file) — continuity is
    verified from there onward."""
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
            continue
        stamp, prefix = parsed
        if h is None:
            unsigned += 1
            continue
        prev = chains.get(prefix)
        if prev is not None:
            want = entry_hash(prev, stamp, prefix, entry_body(line))
            if want != h:
                broken.append((no, prefix, 'hash mismatch (the entry, its neighbours or the order were tampered with)'))
        chains[prefix] = h
    return broken, unsigned, events


def verify_path(path, quiet):
    """One path plus its rotated backups, oldest first. Returns (ok, summary)."""
    backups = ['%s.%d' % (path, i) for i in range(16, 0, -1) if os.path.exists('%s.%d' % (path, i))]
    ordered = backups + ([path] if os.path.exists(path) else [])
    if not ordered:
        return True, 'missing'
    lines = []
    for f in ordered:
        with open(f, encoding='utf-8', errors='replace') as fh:
            lines.extend(fh.readlines())
    broken, unsigned, events = verify_stream(path, lines, quiet)
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
    quiet = '-q' in sys.argv
    paths = [a for a in sys.argv[1:] if a != '-q']
    if not paths:
        paths = [default_path(app) for app in DEFAULT_TRAILS]
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            print('no audit trails found (tried the XDG state homes of %s)' % ', '.join(DEFAULT_TRAILS))
            return 0
    ok = True
    for path in paths:
        if path == '-':
            broken, unsigned, events = verify_stream('stdin', sys.stdin.readlines(), quiet)
            if broken:
                ok = False
                print('FAIL <stdin> — %d broken entr(y/ies):' % len(broken))
                for no, prefix, why in broken[:10]:
                    print('     line %d [%s]: %s' % (no, prefix, why))
            elif not quiet or unsigned:
                note = ', %d unsigned' % unsigned if unsigned else ''
                print('OK   <stdin> — %d entr(y/ies)%s' % (events, note))
        else:
            good, _ = verify_path(path, quiet)
            ok = ok and good
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
