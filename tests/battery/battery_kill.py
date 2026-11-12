#!/usr/bin/env python3
"""battery_kill.py — kill a running battery slot. The slots/slot<N> links
under the battery state home (~/.local/state/pvbattery) name the live
runs (the pid file inside each run dir is the liveness marker, the same
tell battery_status.py reads). TERM comes first: the runner's own signal
handler writes the cancellation NOTE into status.txt, frees the pid file
and the slot link, and exits — the runner's whole descendant tree (the
suite copy and the daemons it spawned, collected BEFORE the first
signal: once the runner dies its orphans reparent and parentage can
never find them again) TERMed alongside. Whatever outlives the grace
window gets KILLed; a runner that needed the KILL never ran its handler,
so the killer NOTEs the status and frees the link itself — the same end
state a TERMed run leaves (a stale link left behind anyway is the next
battery start's slot reclaim, as ever).

    python3 tests/battery/battery_kill.py            # every live slot
    python3 tests/battery/battery_kill.py 2 slot3    # the named slot(s) only

No live battery is exit 0 (nothing to kill); an unknown slot name is the
one error. Stdlib only, like the rest of tests/battery/."""

import argparse
import os
import pathlib
import re
import signal
import subprocess
import sys
import time

HOME_ROOT = os.environ.get('XDG_STATE_HOME', os.path.expanduser('~/.local/state')) + '/pvbattery'
ROOT = pathlib.Path(HOME_ROOT)
SLOTDIR = ROOT / 'slots'
GRACE = 8.0   # the TERM -> KILL window (seconds)


def state(pid):
    """The process state's first letter ('Z' = exited but unreaped — a
    zombie is dead for every purpose here; '' = ps finds nobody)."""
    try:
        r = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                           capture_output=True, text=True)
    except OSError:
        return ''
    return r.stdout.strip()[:1]


def alive(pid):
    return state(pid) not in ('', 'Z')


def descendants(pid):
    """The whole tree below pid, breadth-first over pgrep -P — the suite
    copy and the daemons it spawned. Collected before any signal lands:
    once the runner dies its orphans reparent and parentage never finds
    them again."""
    out, frontier = [], [pid]
    while frontier:
        kids = []
        for p in frontier:
            r = subprocess.run(['pgrep', '-P', str(p)], capture_output=True, text=True)
            kids += [int(x) for x in r.stdout.split() if x.isdigit()]
        kids = [k for k in kids if k not in out and k != pid]
        out += kids
        frontier = kids
    return out


def term_all(pids):
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass


def kill_all(pids):
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass


def note_killed(d):
    """The tail a SIGKILLed runner can no longer write — the NOTE keeps
    battery_status.py's 'canceled' label, the pid file and the slot link
    go the way its finish() would have left them."""
    try:
        with open(d / 'status.txt', 'a') as fh:
            fh.write('NOTE battery canceled (SIGKILL) at %s — no tally\n' % time.strftime('%H:%M:%S'))
    except OSError:
        pass
    try:
        (d / 'pid').unlink()
    except OSError:
        pass


def free_link(link, d):
    """The link goes only while it still names THIS run dir (a concurrent
    battery may have reclaimed the name)."""
    try:
        if os.path.realpath(link) == str(d):
            link.unlink()
    except OSError:
        pass


def kill_slot(link):
    """TERM the runner + its tree, KILL the survivors — (report, ok)."""
    name = link.name
    d = pathlib.Path(os.path.realpath(link))
    try:
        pid = int((d / 'pid').read_text().strip())
    except (OSError, ValueError):
        return '%s: no live battery (stale link)' % name, True
    if not alive(pid):
        return '%s: no live battery (stale link)' % name, True
    tree = descendants(pid)
    term_all([pid] + tree)   # the runner first: its handler does the status tail and stops the next suite's spawn
    end = time.time() + GRACE
    while time.time() < end and alive(pid):
        time.sleep(0.25)
    hard = [p for p in [pid] + tree if alive(p)]
    kill_all(hard)
    time.sleep(0.5)   # a beat: the KILL lands (or the reaper turns the corpse a zombie — state() reads that dead)
    gone = not alive(pid)
    if gone and pid in hard:
        note_killed(d)
        free_link(link, d)
    tail = 'the tree of %d reaped' % len(tree) if tree else 'no tree'
    if not gone:
        return '%s %s (pid %d): STILL ALIVE — the KILL did not land' % (name, d.name, pid), False
    if hard:
        return '%s %s (pid %d): KILL — gone (%s; TERM ignored — the status NOTE\'d, the link freed)' \
            % (name, d.name, pid, tail), True
    return '%s %s (pid %d): TERM — gone (%s)' % (name, d.name, pid, tail), True


def main():
    ap = argparse.ArgumentParser(
        description='kill a running battery slot (TERM the runner and its tree, KILL the survivors)')
    ap.add_argument('slots', nargs='*', metavar='SLOT',
                    help='slot number or slotN name (default: every live slot)')
    a = ap.parse_args()
    if not SLOTDIR.is_dir():
        sys.exit('battery_kill: no slots dir under %s (no battery ever ran here)' % ROOT)
    want = []
    for s in a.slots:
        if re.fullmatch(r'\d+', s):
            want.append('slot' + s)
        elif re.fullmatch(r'slot\d+', s):
            want.append(s)
        else:
            sys.exit("battery_kill: a slot is slotN or a number (got '%s')" % s)
    links = {p.name: p for p in SLOTDIR.iterdir()
             if p.is_symlink() and re.fullmatch(r'slot\d+', p.name)}
    missing = [n for n in want if n not in links]
    if missing:
        sys.exit('battery_kill: no such slot link (%s)' % ', '.join(missing))
    targets = [links[n] for n in want] if want else [links[n] for n in sorted(links)]
    rows = [kill_slot(link) for link in targets]
    if not want and not any(ok for _, ok in rows):
        print('no batteries running (no live slot links)')
        return
    for row, _ in rows:
        print(row)
    sys.exit(0 if all(ok for _, ok in rows) else 1)


if __name__ == '__main__':
    main()
