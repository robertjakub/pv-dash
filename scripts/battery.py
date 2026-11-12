#!/usr/bin/env python3
"""The battery runner: profiles, per-tool selections and fuzz budgets —
the ~5-minute loop per commit. Concurrent batteries take disjoint port
spaces (the runner hands a slot; the suites shift their ports by
SUITE_PORT_BASE), so parallel runs cannot kill each other. The release's
local battery rides this runner too (release.py's `full` profile); the
CI release workflow keeps its own per-suite matrix legs; the nightly
keeps the full budgets.

    scripts/battery.py                # commit: the fast set, cache-fuzz at 100 (~3 min) — parallel-safe
    scripts/battery.py common         # the spine's commit set (~4 min) — parallel-safe
    scripts/battery.py cache          # the cache's commit set: the regtest + the fuzzes (~5 min) — serial
    scripts/battery.py scraper        # the scraper's commit set (~6 min) — serial
    scripts/battery.py inverter       # the fake's commit set (~1 min) — serial
    scripts/battery.py dashboard      # the dashboard's commit set (~1 min) — serial
    scripts/battery.py quick          # all ten, the fuzzes at 300 (~3 min) — serial
    scripts/battery.py full           # all ten, the suite defaults — the nightly, serial
    scripts/battery.py <suite> ...    # explicit names, e.g. cache-regtest inverter-regtest
    scripts/battery.py --depth full <suite> ...  # explicit names at the nightly depth (the regtests' full profile + the fuzzes' full spread) — the release's recovery pair rides this
    scripts/battery.py --stop ...     # the flag may sit anywhere: the first FAILED suite ends the run — the tally marks the rest SKIPPED
    scripts/battery.py --name <label> ...  # label the run with the wave/chat that asked for it — the flag may sit anywhere: the status carries a `wave:` line (the battery_status.py view shows it)

Every run works inside its own dedicated dir: <root>/<run-id>/ where the
root is ~/.local/state/pvbattery (XDG_STATE_HOME respected — the state
home the family's audit trails already use). The suites resolve their
/tmp scratch literals from PV_RUN_DIR — the run dir's tmp — and TMPDIR
points there too, so the tempfile users land inside the run dir as well;
only the daemon-derived unix sockets stay at /tmp/modbus-*.socket, their
paths are the daemons' own constants. The live handles: a run holding a
port slot gets slots/slot<N> -> its run dir, so a concurrent battery
reads `tail -f ~/.local/state/pvbattery/slots/slot2/status.txt`. The
link dies with the run — the exit handler frees it; a battery killed
outright (SIGKILL, no handler) gets its link swept and its status.txt
NOTE'd by the next start's housekeeping. Four port slots: four
concurrent batteries max. The run dirs keep the newest 8 — the four a
live battery can hold plus the newest history (the newest finished run
is simply the newest dir) — and the eta history lives in
eta/<profile>.txt.

One suite at a time within a run; a suite's verdict = its own ALL PASS
with no FAIL lines; the tally lands at the end of the status file, and
the whole run archives to backups/<run-id>.tar.gz (the newest 32 kept —
the green runs drop the tmp scratch after, the failed ones keep it to
post-mortem)."""

import datetime
import atexit
import glob
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
HOME_ROOT = os.environ.get('XDG_STATE_HOME', os.path.expanduser('~/.local/state')) + '/pvbattery'

# the one-time /tmp migration: the battery lived at /tmp/pvbattery until
# the state home (the reboot and the periodic cleaners ate the eta history
# and the failed-run backups there)
if os.path.isdir('/tmp/pvbattery'):
    os.makedirs(HOME_ROOT, exist_ok=True)
    for d in glob.glob('/tmp/pvbattery/2*') + ['/tmp/pvbattery/eta', '/tmp/pvbattery/backups']:
        dst = os.path.join(HOME_ROOT, os.path.basename(d.rstrip('/')))
        if os.path.isdir(d) and not os.path.exists(dst):
            os.rename(d, dst)
LOGROOT = pathlib.Path(HOME_ROOT)
os.makedirs(LOGROOT / 'slots', exist_ok=True)
os.makedirs(LOGROOT / 'eta', exist_ok=True)
# the one-time eta migration: the history files lived at the root as
# eta-<profile>.txt before the eta/ dir
for f in glob.glob(str(LOGROOT / 'eta-*.txt')):
    p = f[len(str(LOGROOT)) + 1:]
    prof = p[len('eta-'):-len('.txt')]
    dst = LOGROOT / 'eta' / (prof + '.txt')
    if not dst.exists():
        os.rename(f, dst)

# the keep-8 housekeeping: the newest 8 run dirs, a live run's dir
# untouchable (the pid file is the liveness marker)
for d in sorted((p for p in LOGROOT.glob('2*') if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[8:]:
    pid = ''
    pidf = d / 'pid'
    if pidf.exists():
        pid = pidf.read_text().strip()
    if pid:
        try:
            os.kill(int(pid), 0)
            continue   # a live run's dir is untouchable
        except (OSError, ValueError):
            pass
    shutil.rmtree(d, ignore_errors=True)

# the flags: --stop ends the battery at the first FAILED suite (the tally
# marks the rest SKIPPED); --name labels the run with the wave/chat that
# asked for it; --depth overrides the suites' depth for explicit names
# (quick | full — full is the nightly depth the `full` profile implies).
# All flags may sit anywhere in the args.
STOP = False
NAME = ''
DEPTH = ''
ARGS = []
argv = sys.argv[1:]
i = 0
while i < len(argv):
    a = argv[i]
    if a == '--stop':
        STOP = True
    elif a == '--name':
        if i + 1 < len(argv):
            NAME = argv[i + 1]
            i += 1
    elif a.startswith('--name='):
        NAME = a[len('--name='):]
    elif a == '--depth':
        if i + 1 < len(argv):
            DEPTH = argv[i + 1]
            i += 1
    elif a.startswith('--depth='):
        DEPTH = a[len('--depth='):]
    else:
        ARGS.append(a)
    i += 1
if DEPTH and DEPTH not in ('quick', 'full'):
    sys.exit("battery: --depth must be quick or full (got '%s')" % DEPTH)
# the label is prose, not a filename (the run id keeps its plain
# <date>-<profile> shape) — one line, whitespace collapsed and trimmed,
# 64 chars max; a label that trims away to nothing is no label
NAME = re.sub(r'\s+', ' ', NAME).strip()[:64].strip()

PROFILE = ARGS[0] if ARGS else 'commit'
PROFILES = {
    'commit':    ('cache-stress cache-fuzz cache-control-fuzz audit-chain control-fuzz dashboard-control-fuzz inverter-regtest scrape-fuzz', 100, 1, 15545, 15977),
    'common':    ('audit-chain control-fuzz cache-control-fuzz dashboard-control-fuzz cache-fuzz scrape-fuzz', 100, 1, 15545, 15977),
    'cache':     ('cache-regtest cache-fuzz cache-control-fuzz audit-chain', 100, 0, None, None),
    'inverter':  ('inverter-regtest control-fuzz audit-chain', 100, 0, None, None),
    'scraper':   ('scrape-regtest scrape-fuzz audit-chain', 100, 0, None, None),
    'dashboard': ('dashboard-control-fuzz audit-chain', 100, 0, None, None),
    'quick':     ('cache-regtest inverter-regtest scrape-regtest audit-chain cache-stress cache-control-fuzz control-fuzz dashboard-control-fuzz cache-fuzz scrape-fuzz', 300, 0, None, None),
    'full':      ('cache-regtest inverter-regtest scrape-regtest audit-chain cache-stress cache-control-fuzz control-fuzz dashboard-control-fuzz cache-fuzz scrape-fuzz', '', 0, None, None),
}
if PROFILE in PROFILES:
    SUITES = PROFILES[PROFILE][0].split()
    BUDGET, PARALLEL = PROFILES[PROFILE][1], PROFILES[PROFILE][2]
    WLO, WHI = PROFILES[PROFILE][3], PROFILES[PROFILE][4]
else:
    SUITES = ARGS
    BUDGET, PARALLEL, WLO, WHI = 100, 0, None, None

# the port-space slot: a concurrent battery takes one of four slots; its
# base is the slot's thousand-step port shift, and slots/slot<N> is a
# symlink to the run dir (the pid file inside says who owns it). The
    # os.symlink is the atomic grab — it fails on any existing name; a
# slot whose target's pid is gone is stale and gets renamed out of the
# way first (rename is atomic, so two simultaneous reclaimers cannot
# both win).
RUNID = '%s-%s' % (time.strftime('%Y%m%d-%H%M%S'), PROFILE)
RUNDIR = LOGROOT / RUNID
os.makedirs(RUNDIR / 'tmp')
(RUNDIR / 'pid').write_text('%d\n' % os.getpid())
os.environ['PV_RUN_DIR'] = str(RUNDIR / 'tmp')   # the suites' gate marker (a standalone run refuses)
os.environ['TMPDIR'] = os.environ['TMP'] = str(RUNDIR / 'tmp')   # the tempfile users land in the run dir — /tmp keeps only the daemon sockets
os.environ['PV_SUITE_PROFILE'] = DEPTH or ('full' if PROFILE == 'full' else 'quick')   # the suites' depth (quick default; full = the nightly depth; --depth overrides for explicit names)
os.environ['PYTHONUNBUFFERED'] = '1'   # the daemons' stderr (their logs) must not sit in a lost block buffer

SLOT = ''
for n in range(4):
    link = LOGROOT / 'slots' / ('slot%d' % n)
    try:
        os.symlink(RUNDIR, link)
        SLOT = str(n)
        break
    except FileExistsError:
        t = os.readlink(link)
        pid = ''
        try:
            pid = (pathlib.Path(t) / 'pid').read_text().strip()
        except OSError:
            pass
        if pid:
            try:
                os.kill(int(pid), 0)
                continue   # its owner still runs
            except (OSError, ValueError):
                pass
        corpse = LOGROOT / 'slots' / ('slot%d.stale.%d' % (n, os.getpid()))
        try:
            os.rename(link, corpse)   # someone else may reclaim it first
        except OSError:
            continue
        try:
            os.symlink(RUNDIR, link)
            SLOT = str(n)
            os.unlink(corpse)
            break
        except OSError:
            pass
        try:
            os.unlink(corpse)
        except OSError:
            pass
if PARALLEL and SLOT == '':
    print('battery: no free port-space slot (4 concurrent batteries max) — waiting one is fine, or run a serial profile')
    sys.exit(1)
BASE = int(SLOT) * 1000 if SLOT else 0
if SLOT:
    os.environ['SUITE_PORT_BASE'] = str(BASE)

STATUS = RUNDIR / 'status.txt'
DONE = 0
NOTED = 0


def finish(why):
    """The exit tail: a battery canceled before the tally (INT/TERM, or
    the runner dying early) leaves a NOTE in its status.txt; every exit
    frees the slots/slot<N> handle. A battery killed outright (SIGKILL —
    no handler runs) is noted and unlinked by the next start's
    housekeeping instead."""
    global NOTED
    if NOTED:
        return
    NOTED = 1
    if why != 'EXIT' or not DONE:
        label = {'INT': 'canceled (SIGINT)', 'TERM': 'canceled (SIGTERM)'}.get(
            why, 'canceled (the runner exited early)')
        with open(STATUS, 'a') as fh:
            fh.write('NOTE battery %s at %s — no tally\n' % (label, time.strftime('%H:%M:%S')))
    try:
        (RUNDIR / 'pid').unlink()
    except OSError:
        pass
    if SLOT:
        try:
            (LOGROOT / 'slots' / ('slot%s' % SLOT)).unlink()
        except OSError:
            pass


def on_signal(num, frame):
    finish({signal.SIGINT: 'INT', signal.SIGTERM: 'TERM'}.get(num, 'EXIT'))
    sys.exit(130 if num == signal.SIGINT else 143)


signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)
atexit.register(finish, 'EXIT')   # the early-exit NOTE + the slot free on any unwound exit


def status_rows():
    return STATUS.read_text().splitlines() if STATUS.exists() else []


def say(row):
    print(row)
    with open(STATUS, 'a') as fh:
        fh.write(row + '\n')


def fmt(sec):
    return '%dm%02ds' % (sec // 60, sec % 60) if sec >= 60 else '%ds' % sec


def etatime(sec):
    """seconds-from-now -> the wall clock (falls back to ~minutes)"""
    t = datetime.datetime.now() + datetime.timedelta(seconds=sec)
    return t.strftime('%H:%M')


say('battery %s (pid %d) profile=%s budget=%s slot=%s base=%d'
    % (RUNID, os.getpid(), PROFILE, BUDGET if BUDGET != '' else 'suite defaults', SLOT or 'none', BASE))
if NAME:
    say('wave: %s' % NAME)
say('suites: %s' % ' '.join(SUITES))
TOTAL = len(SUITES)
BT0 = time.time()

# the eta: the prior history of the same profile predicts the whole
# batch; a suite without history goes partial instead of zeroing the
# whole batch, and every finished suite's actual lands in the file right
# away — an interrupted run keeps its finished suites
ETAFILE = LOGROOT / 'eta' / ('%s.txt' % PROFILE)


def eta_of(suite):
    """the suite's own historical wall time (seconds) — None without a row"""
    if not ETAFILE.exists():
        return None
    for row in ETAFILE.read_text().splitlines():
        parts = row.split()
        if parts and parts[0] == suite:
            return int(parts[1])
    return None


remain = {s: eta_of(s) for s in SUITES}
known = [v for v in remain.values() if v is not None]
if known and len(known) == TOTAL:
    say('estimate: ~%s total, done ~%s (the %s eta history)'
        % (fmt(sum(known)), etatime(sum(known)), PROFILE))
elif known:
    say('estimate: ~%s for %d/%d suites, done ~%s (partial %s history)'
        % (fmt(sum(known)), len(known), TOTAL, etatime(sum(known)), PROFILE))
else:
    say('estimate: none (no %s eta history yet)' % PROFILE)

# the quiet window: the parallel profiles wait only for daemons whose
# ports fall inside their own window (the other slots' daemons live on
# disjoint ports and are none of this run's business); the serial
# profiles wait for any family daemon at all.
# the daemon port extraction: only the flag-anchored numbers (--listen
# 127.0.0.1:16591, --control-port 16592) count as ports — the paths and
# the pids carry digits too and must not read as one.
FAMILY_PGREP = '[m]odbus-cache.py|[m]odbus-scraper.py|[m]odbus-fake-inverter.py|bin/[d]ashboard.py'


def family_daemons():
    r = subprocess.run(['pgrep', '-fl', FAMILY_PGREP], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    out = []
    for row in r.stdout.splitlines():
        parts = row.split(None, 1)
        if len(parts) == 2:
            out.append((parts[0], parts[1]))
    return out


def daemon_ports(cmdline):
    pairs = re.findall(r':(\d{4,5})\b|port (\d{4,5})\b', cmdline)
    return sorted({int(a or b) for a, b in pairs})


def window_busy():
    for pid, cmdline in family_daemons():
        for p in daemon_ports(cmdline):
            if WLO is not None and WLO <= p <= WHI:
                return True
    return False


def name_busy():
    return subprocess.run(['pgrep', '-f', FAMILY_PGREP], capture_output=True).returncode == 0


waited = []


def w_note(n, total, s):
    """the one-time WAIT row: on the first busy poll the queued suite says
    it sits on the quiet window — battery_status.py reads the row while it
    is the status's last word, and the START row retires it when the wait
    ends"""
    if waited:
        return
    waited.append(1)
    say('%s WAIT %d/%d %s — the quiet window: family daemons still hold the ports'
        % (time.strftime('%H:%M:%S'), n, total, s))


def quiet(n, total, s):
    waited.clear()
    for _ in range(120):
        if PARALLEL:
            if window_busy():
                w_note(n, total, s)
                time.sleep(15)
                continue
        else:
            if subprocess.run(['pgrep', '-f', '[z]z_[a-z]*[.]py'], capture_output=True).returncode == 0:
                w_note(n, total, s)
                time.sleep(15)
                continue
            if name_busy():
                w_note(n, total, s)
                time.sleep(15)
                continue
        break


def kill_daemons():
    if PARALLEL:
        # the parallel runs kill only the daemons inside their own shifted
        # port window — another slot's daemons live on disjoint ports and
        # are untouchable
        for pid, cmdline in family_daemons():
            for p in daemon_ports(cmdline):
                if WLO is not None and (WLO + BASE) <= p <= (WHI + BASE):
                    try:
                        os.kill(int(pid), 9)
                    except (OSError, ValueError):
                        pass
                    break
        return
    for pat in ('[m]odbus-cache.py', '[m]odbus-scraper.py',
                '[m]odbus-fake-inverter.py', 'bin/[d]ashboard.py'):
        subprocess.run(['pkill', '-9', '-f', pat], capture_output=True)


for i, s in enumerate(SUITES, 1):
    n, total = i, TOTAL
    if not (REPO / 'tests' / (s + '.py')).exists():
        say('%s SKIP %d/%d %s (no such suite)' % (time.strftime('%H:%M:%S'), n, total, s))
        continue
    quiet(n, total, s)
    if not PARALLEL:
        kill_daemons()
        time.sleep(2)
    se = remain[s]
    if se is not None:
        say('%s START %d/%d %s eta %s (%s)' % (time.strftime('%H:%M:%S'), n, total, s, fmt(se), etatime(se)))
    else:
        say('%s START %d/%d %s' % (time.strftime('%H:%M:%S'), n, total, s))
    # the copy exists so a suite's processes carry the zz_ name the quiet
    # window and the housekeeping greps — the suites resolve their scratch
    # from PV_RUN_DIR themselves
    zz = REPO / 'tests' / 'zz_bx.py'
    shutil.copy(REPO / 'tests' / (s + '.py'), zz)
    t0 = time.time()
    if s in ('cache-fuzz', 'scrape-fuzz'):
        # the fuzz budget + the mode: quick pools the basic shapes, full
        # the nightly spread (both fuzz suites take [iterations]
        # [quick|full]) — the spread follows the depth (the full profile,
        # or --depth full)
        fuzzprof = os.environ['PV_SUITE_PROFILE']
        r = subprocess.run(['python3', 'tests/zz_bx.py', str(BUDGET or 3000), fuzzprof],
                           cwd=REPO, stdout=open(RUNDIR / (s + '.log'), 'w'), stderr=subprocess.STDOUT)
    else:
        r = subprocess.run(['python3', 'tests/zz_bx.py'], cwd=REPO,
                           stdout=open(RUNDIR / (s + '.log'), 'w'), stderr=subprocess.STDOUT)
    rc = r.returncode
    ds = int(time.time() - t0)
    dur = fmt(ds)
    if rc == 0:
        # the history row lands per-suite on a PASS only — a failed leg's
        # duration is noise (a hang or a crash predicts nothing); the row
        # updates in place, but only when the new actual EXCEEDS the old:
        # the eta predicts, a warm-cache fast run must not shrink it and
        # under-estimate the batch — a slow run raising it is the safe
        # direction
        old = ETAFILE.read_text().splitlines() if ETAFILE.exists() else []
        prev = next((int(x.split()[1]) for x in old if x.split() and x.split()[0] == s), None)
        rows = [x for x in old if x.split() and x.split()[0] != s]
        rows.append('%s %d' % (s, ds if prev is None or ds > prev else prev))
        ETAFILE.write_text('\n'.join(rows) + '\n')
        say('%s SUITE %d/%d %s: PASS (%s)' % (time.strftime('%H:%M:%S'), n, total, s, dur))
    else:
        say('%s SUITE %d/%d %s: FAILED (%s)' % (time.strftime('%H:%M:%S'), n, total, s, dur))
        log = (RUNDIR / (s + '.log')).read_text().splitlines()
        for row in log[-6:]:
            print(row)
        if STOP:
            say('%s STOP --stop: the batch ends here' % time.strftime('%H:%M:%S'))
            break
if not PARALLEL:
    kill_daemons()
try:
    (REPO / 'tests' / 'zz_bx.py').unlink()
except OSError:
    pass
BT1 = time.time()
say('=== TALLY %s (the battery: %s)' % (time.strftime('%H:%M:%S'), fmt(int(BT1 - BT0))))
fail = 0
for i, s in enumerate(SUITES, 1):
    log = RUNDIR / (s + '.log')
    if STOP and not log.exists():
        say('%d/%d %s: SKIPPED (--stop)' % (i, TOTAL, s))
    elif log.exists() and any(re.match(r'^ALL PASS', x) for x in log.read_text().splitlines()) \
            and not any(re.match(r'^FAIL', x) for x in log.read_text().splitlines()):
        say('%d/%d %s: PASS' % (i, TOTAL, s))
    else:
        fail += 1
        say('%d/%d %s: NOT-GREEN' % (i, TOTAL, s))
if fail == 0:
    say('BATTERY: ALL PASS')
else:
    say('BATTERY: %d NOT GREEN' % fail)

# the archive: the run's evidence (the status, the logs, the scratch) into
# one tarball under backups/ — the scratch is text and compresses hard;
# the green runs drop tmp/ after (nothing to post-mortem), the failed ones
# keep it live. The backups keep the newest 32 (the keep-8 housekeeping
# ages the run dirs separately)
BACKUPS = LOGROOT / 'backups'
os.makedirs(BACKUPS, exist_ok=True)
archive = BACKUPS / (RUNID + '.tar.gz')
with tarfile.open(archive, 'w:gz') as tf:
    for path in sorted(RUNDIR.rglob('*')):
        if path.name.startswith('._'):
            continue   # the macOS resource-fork members are excluded
        tf.add(path, arcname=str(path.relative_to(LOGROOT)))
if fail == 0:
    shutil.rmtree(RUNDIR / 'tmp', ignore_errors=True)
for old in sorted(BACKUPS.glob('*.tar.gz'), key=lambda p: p.stat().st_mtime)[:-32]:
    old.unlink(missing_ok=True)
DONE = 1   # the exit handler stays quiet — the run finished (the slot is still freed)
sys.exit(0 if fail == 0 else 1)
