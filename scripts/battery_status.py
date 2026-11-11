#!/usr/bin/env python3
"""The battery's live view: the running slot links with their run ids and
owning pids, plus (after a blank line, its own block) the last non-live
run — finished or canceled. The read-only sibling of the battery runner —
nothing here mutates the battery state (the stale links stay for the next
battery start's housekeeping sweep). Stdlib only, like the rest of the
family.

The view reads once by default; --watch loops with the screen cleared per
tick (the watch-style header carries the interval), and --interval sets
the period in seconds (default 1)."""

import argparse
import datetime
import os
import pathlib
import re
import signal
import sys
import time

ROOT = os.environ.get('XDG_STATE_HOME', os.path.expanduser('~/.local/state')) + '/pvbattery'
if not os.path.isdir(ROOT):
    ROOT = '/tmp/pvbattery'
if not os.path.isdir(ROOT):
    sys.exit('no battery root (%s is gone and so is /tmp/pvbattery)' % ROOT)
ROOT = pathlib.Path(ROOT)


def fmt(sec):
    """mm:ss over the minute, plain seconds under — the runner's shape."""
    return '%dm%02ds' % (sec // 60, sec % 60) if sec >= 60 else '%ds' % sec


def age_of(path):
    """The (Xm Ys ago) age off the status file's mtime — say() appends on
    every row, so the mtime is when the last line landed (several row
    shapes carry no HH:MM:SS stamp of their own); None without a stat."""
    try:
        return max(0, int(datetime.datetime.now().timestamp()) - int(path.stat().st_mtime))
    except OSError:
        return None


def age_txt(sec):
    return '(%s ago)' % fmt(sec)


def last_line(status):
    """The status's last word, aged — a growing age is the tell a suite
    sits quiet too long."""
    rows = status.read_text().splitlines()[-1:] if status.exists() else []
    if not rows:
        return
    a = age_of(status)
    if a is not None:
        print('  %-9s %s %s' % ('last:', rows[0], age_txt(a)))
    else:
        print('  %-9s %s' % ('last:', rows[0]))


def grep_first(status, prefix):
    for line in status.read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def run_stamp(rid):
    """The run id's <YYYYMMDD>-<HHMMSS> head as an epoch — the elapsed
    wall time reads off it."""
    try:
        t = datetime.datetime.strptime(rid.split('-')[0] + '-' + rid.split('-')[1], '%Y%m%d-%H%M%S')
        return int(t.timestamp())
    except ValueError:
        return None


def render():
    slot_lines = sorted(p for p in (ROOT / 'slots').glob('slot*') if p.is_symlink()) if (ROOT / 'slots').is_dir() else []
    n = 0
    for link in slot_lines:
        d = pathlib.Path(os.path.realpath(link))
        pid = ''
        pidf = d / 'pid'
        if pidf.exists():
            pid = pidf.read_text().strip()
        running = False
        if pid:
            try:
                os.kill(int(pid), 0)
                running = True
            except (OSError, ValueError):
                running = False
        n += 1
        rid = d.name
        e = ''
        t0 = run_stamp(rid)
        if t0 is not None:
            e = fmt(max(0, int(datetime.datetime.now().timestamp()) - t0))
        print('%s %s pid=%s %s' % (link.name, 'RUNNING' if running else 'STALE', pid or 'none', rid))
        status = d / 'status.txt'
        if running and status.exists():
            hdr = grep_first(status, 'battery ')
            if hdr and ') ' in hdr:
                print('  %-9s %s' % ('run:', hdr.split(') ', 1)[1]))
            wv = grep_first(status, 'wave: ')
            if wv is not None:
                print('  %-9s %s' % ('wave:', wv))
            est = grep_first(status, 'estimate: ')
            if est is not None:
                print('  %-9s %s' % ('estimate:', est))
            # the live tally: the SUITE verdicts so far over the run's total
            # (the total rides the last START/SKIP's N/T; before the first
            # suite it falls back to the `suites:` row's word count)
            rows = status.read_text().splitlines()
            pas = sum(1 for l in rows if ': PASS (' in l)
            fail = sum(1 for l in rows if ': FAILED (' in l)
            skip = sum(1 for l in rows if ' SKIP ' in l)
            total = 0
            for l in rows:
                m = re.match(r'\S+ (?:START|SKIP) (\d+)/(\d+) ', l)
                if m:
                    total = int(m.group(2))
            if total == 0:
                s = grep_first(status, 'suites: ')
                total = max(0, (len(s.split()) - 1) if s else 0)
            line = '%d/%d done, %d pass, %d failed' % (pas + fail + skip, total, pas, fail)
            if skip:
                line += ', %d skipped' % skip
            if e:
                line += ', %s elapsed' % e
            print('  %-9s %s' % ('stats:', line))
            # the queued suite: the WAIT row (the runner wrote it on the first
            # busy poll) is the status's last word exactly while the runner
            # sits in the quiet window — the START row (or a cancellation
            # NOTE) replaces it the moment the wait ends
            if rows:
                tail = rows[-1]
                m = re.match(r'(\d\d:\d\d:\d\d) WAIT (.*)$', tail)
                if m:
                    try:
                        st = datetime.datetime.strptime(datetime.datetime.now().strftime('%Y-%m-%d ') + m.group(1), '%Y-%m-%d %H:%M:%S')
                        wl = fmt(max(0, int(datetime.datetime.now().timestamp()) - int(st.timestamp())))
                        print('  %-9s %s (%s so far)' % ('wait:', m.group(2), wl))
                    except ValueError:
                        print('  %-9s %s' % ('wait:', m.group(2)))
        print('  %-9s %s/status.txt' % ('status:', d))
        last_line(status)
    if n == 0:
        print('no batteries running (no slot links)')

    last = None
    for cand in sorted((p for p in ROOT.glob('2*') if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        if any(os.path.realpath(l) == str(cand) for l in slot_lines):
            continue
        last = cand
        break
    if last is not None:
        print()   # the break: the previous stopped run is its own block, not slot0's tail
        # the previous non-slotted run: its last word decides the label — the
        # TALLY line means it finished, a cancellation NOTE means the
        # runner died before it (SIGKILL leaves no trap), neither means it
        # never got far enough to say
        status = last / 'status.txt'
        rows = status.read_text() if status.exists() else ''
        if 'NOTE battery canceled' in rows:
            state = 'canceled'
        elif re.search(r'^=== TALLY ', rows, re.M):
            state = 'finished'
        else:
            state = 'no tally'
        print('previous slot: %s (%s)' % (last.name, state))
        last_line(status)


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # a piped view (| head, | grep) exits silently, no traceback
    ap = argparse.ArgumentParser(description="the battery's live view (read-only)")
    ap.add_argument('-w', '--watch', action='store_true',
                    help='loop with the screen cleared per tick (default: one show)')
    ap.add_argument('-i', '--interval', type=float, default=None, metavar='SECONDS',
                    help='the watch period in seconds (default 1; implies --watch)')
    a = ap.parse_args()
    interval = a.interval if a.interval is not None else 1.0
    if interval <= 0:
        sys.exit('battery_status: --interval must be a positive number of seconds')
    if not (a.watch or a.interval is not None):
        render()
        return
    try:
        while True:
            print('\033[H\033[2J', end='')   # home + clear — the watch redraw
            print('Every %gs: battery_status.py — %s (Ctrl-C quits)'
                  % (interval, time.strftime('%H:%M:%S')))
            print()
            render()
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
        sys.exit(0)


if __name__ == '__main__':
    main()
