#!/bin/sh
# The dev-side suite battery: profiles, per-tool selections and fuzz
# budgets — the ~5-minute loop per commit. Concurrent batteries take
# disjoint port spaces (the runner hands a slot; the suites shift their
# ports by SUITE_PORT_BASE), so parallel runs cannot kill each other.
# The release gates keep their own matrix (scripts/release.py); the
# nightly keeps the full budgets.
#
#   scripts/battery.sh                # commit: the fast set, cache-fuzz at 100 (~3 min) — parallel-safe
#   scripts/battery.sh common         # the spine's commit set (~4 min) — parallel-safe
#   scripts/battery.sh cache          # the cache's commit set: the regtest + the fuzzes (~5 min) — serial
#   scripts/battery.sh scraper        # the scraper's commit set (~6 min) — serial
#   scripts/battery.sh inverter       # the fake's commit set (~1 min) — serial
#   scripts/battery.sh dashboard      # the dashboard's commit set (~1 min) — serial
#   scripts/battery.sh quick          # all ten, the fuzzes at 300 (~3 min) — serial
#   scripts/battery.sh full           # all ten, the suite defaults — the nightly, serial
#   scripts/battery.sh <suite> ...    # explicit names, e.g. cache-regtest inverter-regtest
#   scripts/battery.sh --stop ...     # the flag may sit anywhere: the first FAILED suite ends the run — the tally marks the rest SKIPPED
#
# Every run works inside its own dedicated dir: /tmp/pvbattery/<run-id>/
# (the suites' /tmp scratch is rewritten into it, and TMPDIR points there
# too, so the tempfile users land inside the run dir as well — only the
# daemon-derived unix sockets stay at /tmp/modbus-*.socket, their paths
# are the daemons' own constants). The live handles: a run holding a
# port slot gets slots/slot<N> -> its run dir, so a concurrent battery
# reads `tail -f /tmp/pvbattery/slots/slot2/status.txt`. The link dies
# with the run — the exit trap frees it; a battery killed outright
# (SIGKILL, no trap) gets its link swept and its status.txt NOTE'd by
# the next start's housekeeping. Four port slots: four concurrent
# batteries max. The run dirs keep the newest 8 — the four a live
# battery can hold plus the newest history (the newest finished run is
# simply the newest dir — ls -1dt /tmp/pvbattery/2* | head -1) — and
# the eta history lives in eta/<profile>.txt.
#
# One suite at a time within a run; a suite's verdict = its own ALL PASS
# with no FAIL lines; the tally lands at the end of the status file, and
# the whole run archives to backups/<run-id>.tar.gz (the newest 32 kept —
# the green runs drop the tmp scratch after, the failed ones keep it to
# post-mortem).

cd "$(dirname "$0")/.." || exit 1
LOGROOT=/tmp/pvbattery
mkdir -p $LOGROOT/slots $LOGROOT/eta
# the one-time eta migration: the history files lived at the root as
# eta-<profile>.txt before the eta/ dir
for f in $LOGROOT/eta-*.txt; do
  [ -f "$f" ] || continue
  p=${f##*/eta-}; p=${p%.txt}
  [ -e "$LOGROOT/eta/$p.txt" ] || mv "$f" "$LOGROOT/eta/$p.txt"
  rm -f "$f"
done
# the housekeeping: the run dirs pile up fast (the stress dumps, the
# rewritten scratch — ~2G a busy day), so a start keeps the newest 8 and
# sweeps the rest — a dir whose owning pid is still alive is untouchable.
# A battery killed outright (SIGKILL, a dead machine) left a pid file no
# one removed: the next start NOTEs the cancellation into its status.txt
# and frees its slots/slot<N>.
for d in $LOGROOT/2*; do
  [ -f "$d/pid" ] || continue
  pid=$(cat "$d/pid" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && continue   # still running
  if [ -f "$d/status.txt" ] && ! grep -q 'NOTE battery canceled' "$d/status.txt"; then
    echo "NOTE battery canceled (the runner's pid is gone) at $(date '+%H:%M:%S') — no tally" >> "$d/status.txt"
  fi
  rm -f "$d/pid"
done
for l in $LOGROOT/slots/slot*; do
  [ -L "$l" ] || [ -d "$l" ] || continue   # a link (even dangling) or a pre-rename lock dir
  t=$(readlink "$l" 2>/dev/null)
  pid=''
  [ -f "$t/pid" ] && pid=$(cat "$t/pid" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && continue   # its owner still runs
  rm -rf "$l"
done
ls -1dt $LOGROOT/2* 2>/dev/null | tail -n +9 | while read -r d; do
  [ -d "$d" ] || continue
  pid=$(cat "$d/pid" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && continue   # a live run's dir is untouchable
  rm -rf "$d"
done
# the flags: --stop ends the battery at the first FAILED suite (the tally
# marks the rest SKIPPED); the flag may sit anywhere in the args
STOP=''
for a in "$@"; do
  [ "$a" = "--stop" ] && STOP=1
done
[ -n "$STOP" ] && set -- $(for a in "$@"; do [ "$a" != "--stop" ] && printf '%s\n' "$a"; done)
PROFILE="${1:-commit}"
RUNID="$(date +%Y%m%d-%H%M%S)-$PROFILE"
RUNDIR=$LOGROOT/$RUNID
mkdir -p "$RUNDIR/tmp"
echo $$ > "$RUNDIR/pid"   # the housekeeping's liveness marker (a live pid = untouchable, a dead one = canceled)
export PV_RUN_DIR="$RUNDIR/tmp"   # the suites' gate marker (a standalone run refuses)
export TMPDIR="$RUNDIR/tmp" TMP="$RUNDIR/tmp"   # the tempfile users land in the run dir — /tmp keeps only the daemon sockets
export PV_SUITE_PROFILE=$([ "$PROFILE" = full ] && echo full || echo quick)   # the suites' depth (quick default; full = the nightly depth)
rm -f $LOGROOT/latest $LOGROOT/current $LOGROOT/previous   # the retired spellings — the live view is slots/slot<N>, the finished one the newest dir
rm -rf $LOGROOT/links   # the pre-rename spelling of slots/
STATUS=$RUNDIR/status.txt

# the exit tail: a battery canceled before the tally (INT/TERM, or the
# runner dying early) leaves a NOTE in its status.txt; every exit frees
# the slots/slot<N> handle. A battery killed outright
# (SIGKILL — no trap runs) is noted and unlinked by the next start's
# housekeeping instead.
DONE=''
finish() {
  [ -n "$NOTED" ] && return
  NOTED=1
  if [ -z "$DONE" ] && [ -f "$STATUS" ]; then
    case "$1" in
      INT)  why='canceled (SIGINT)' ;;
      TERM) why='canceled (SIGTERM)' ;;
      *)    why='canceled (the runner exited early)' ;;
    esac
    echo "NOTE battery $why at $(date '+%H:%M:%S') — no tally" >> $STATUS
  fi
  rm -f "$RUNDIR/pid"
  [ -n "$SLOT" ] && rm -f "$LOGROOT/slots/slot$SLOT"
}
trap 'finish EXIT' EXIT
trap 'finish INT;  exit 130' INT
trap 'finish TERM; exit 143' TERM

say() { echo "$1"; echo "$1" >> $STATUS; }

# the perf stats: a suite's wall time (and the battery's) reads mm:ss over
# the minute, plain seconds under it
fmt() {
  [ "$1" -ge 60 ] && printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)) || printf '%ss' "$1"
}

# the batch estimate: the newest prior same-profile tally predicts the whole
# batch; every completed suite's actual sharpens the remaining eta
dursec() {  # '3m25s' | '45s' -> seconds
  case "$1" in
    *m*) m=${1%%m*}; rest=${1#*m}; printf '%s' $((m * 60 + ${rest%s})) ;;
    *)   printf '%s' "${1%s}" ;;
  esac
}

etatime() {  # seconds-from-now -> the wall clock (falls back to ~minutes)
  t=$(date -v+"$1"S '+%H:%M' 2>/dev/null) && printf '%s' "$t" || printf '~%dm' $(($1 / 60))
}

QUICK_ALL="cache-regtest inverter-regtest scrape-regtest audit-chain cache-stress cache-control-fuzz control-fuzz dashboard-control-fuzz cache-fuzz scrape-fuzz"

case "$PROFILE" in
  commit)    SUITES="cache-stress cache-fuzz cache-control-fuzz audit-chain control-fuzz dashboard-control-fuzz inverter-regtest scrape-fuzz"; BUDGET=100; PARALLEL=1; WLO=15545; WHI=15977 ;;
  common)    SUITES="audit-chain control-fuzz cache-control-fuzz dashboard-control-fuzz cache-fuzz scrape-fuzz"; BUDGET=100; PARALLEL=1; WLO=15545; WHI=15977 ;;
  cache)     SUITES="cache-regtest cache-fuzz cache-control-fuzz audit-chain"; BUDGET=100; PARALLEL=0 ;;
  inverter)  SUITES="inverter-regtest control-fuzz audit-chain"; BUDGET=100; PARALLEL=0 ;;
  scraper)   SUITES="scrape-regtest scrape-fuzz audit-chain"; BUDGET=100; PARALLEL=0 ;;
  dashboard) SUITES="dashboard-control-fuzz audit-chain"; BUDGET=100; PARALLEL=0 ;;
  quick)     SUITES=$QUICK_ALL; BUDGET=300; PARALLEL=0 ;;
  full)      SUITES=$QUICK_ALL; BUDGET=''; PARALLEL=0 ;;
  *)         SUITES="$*"; BUDGET=100; PARALLEL=0 ;;
esac

# the port-space slot: a concurrent battery takes one of four slots; its
# base is the slot's thousand-step port shift, and slots/slot<N> is a
# symlink to the run dir (the pid file inside says who owns it). The ln
# is the atomic grab — `-h` keeps BSD ln from following an existing
# dir-symlink destination (plain -s would land the link INSIDE the
# owner's run dir and report success), so the ln fails on any existing
# name; a slot whose target's pid is gone is stale and gets renamed out
# of the way first (rename is atomic, so two simultaneous reclaimers
# cannot both win).
SLOT=''
for n in 0 1 2 3; do
  d=$LOGROOT/slots/slot$n
  if ln -h -s "$RUNDIR" "$d" 2>/dev/null; then
    SLOT=$n; break
  fi
  t=$(readlink "$d" 2>/dev/null)
  pid=''
  [ -f "$t/pid" ] && pid=$(cat "$t/pid" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && continue   # its owner still runs
  corpse=$LOGROOT/slots/slot$n.stale.$$
  mv "$d" "$corpse" 2>/dev/null || continue   # someone else reclaimed it first
  if ln -h -s "$RUNDIR" "$d" 2>/dev/null; then
    SLOT=$n; rm -f "$corpse"; break
  fi
  rm -f "$corpse"
done
if [ "$PARALLEL" = 1 ] && [ -z "$SLOT" ]; then
  echo "battery: no free port-space slot (4 concurrent batteries max) — waiting one is fine, or run a serial profile"
  exit 1
fi
if [ -n "$SLOT" ]; then
  BASE=$((SLOT * 1000))
  export SUITE_PORT_BASE=$BASE
else
  BASE=0
fi
export PYTHONUNBUFFERED=1   # the daemons' stderr (their logs) must not sit in a lost block buffer

say "battery $RUNID (pid $$) profile=$PROFILE budget=${BUDGET:-suite defaults} slot=${SLOT:-none} base=$BASE"
say "suites: $SUITES"
TOTAL=$(echo $SUITES | wc -w | tr -d ' ')
N=0
BT0=$(date +%s)

# the eta: the prior history of the same profile predicts the batch; a
# suite without history goes partial instead of zeroing the whole batch,
# and every finished suite's actual lands in the file right away — an
# interrupted run keeps its finished suites
ETAFILE=$LOGROOT/eta/$PROFILE.txt   # the per-suite wall times, one '<suite> <seconds>' row each
REMAIN=; MISSING=0
for s in $SUITES; do
  d=$(awk -v s="$s" '$1 == s { print $2; exit }' "$ETAFILE" 2>/dev/null)
  if [ -n "$d" ]; then REMAIN=$(( ${REMAIN:-0} + d )); else MISSING=$((MISSING + 1)); fi
done
if [ -n "$REMAIN" ] && [ "$MISSING" -eq 0 ]; then
  say "estimate: ~$(fmt "$REMAIN") total, done ~$(etatime "$REMAIN") (the $PROFILE eta history)"
elif [ -n "$REMAIN" ]; then
  say "estimate: ~$(fmt "$REMAIN") for $((TOTAL - MISSING))/$TOTAL suites, done ~$(etatime "$REMAIN") (partial $PROFILE history)"
else
  say "estimate: none (no $PROFILE eta history yet)"
fi

# the quiet window: the parallel profiles wait only for daemons whose
# ports fall inside their own shifted range (the other slots' daemons
# live on disjoint ports and are none of this run's business); the serial
# profiles wait for any family daemon at all.
# the daemon port extraction: only the flag-anchored numbers (--listen
# 127.0.0.1:16591, --control-port 16592) count as ports — the paths and
# the pids carry digits too and must not read as one.
daemon_ports() {
  grep -oE '(:[0-9]{4,5}|port [0-9]{4,5})' | grep -oE '[0-9]{4,5}' | sort -u
}

window_busy() {
  local dout ports p
  dout=$(pgrep -fl '[m]odbus-cache.py|[m]odbus-scraper.py|[m]odbus-fake-inverter.py|bin/[d]ashboard.py' 2>/dev/null) || return 1
  dout=$(echo "$dout" | cut -d' ' -f2-)
  ports=$(echo "$dout" | daemon_ports)
  for p in $ports; do
    [ "$p" -ge "$WLO" ] && [ "$p" -le "$WHI" ] && return 0
  done
  return 1
}
name_busy() {
  pgrep -f '[m]odbus-cache.py|[m]odbus-scraper.py|[m]odbus-fake-inverter.py|bin/[d]ashboard.py' >/dev/null
}
quiet() {
  for i in $(seq 1 120); do
    if [ "$PARALLEL" = 1 ]; then
      # the parallel gate: only the daemons inside this run's own shifted
      # port window — the other slots' suites (and their zz_ copies) live on
      # disjoint ports and are none of this run's business
      window_busy && { sleep 15; continue; }
    else
      pgrep -f '[z]z_[a-z]*[.]py' >/dev/null && { sleep 15; continue; }
      name_busy && { sleep 15; continue; }
    fi
    break
  done
}

kill_daemons() {
  if [ "$PARALLEL" = 1 ]; then
    # the parallel runs kill only the daemons inside their own port window —
    # another slot's daemons live on disjoint ports and are untouchable
    local dout pid rest ports p
    dout=$(pgrep -fl '[m]odbus-cache.py|[m]odbus-scraper.py|[m]odbus-fake-inverter.py|bin/[d]ashboard.py' 2>/dev/null) || return 0
    echo "$dout" | cut -d' ' -f2- | while read -r pid rest; do
      ports=$(echo "$rest" | daemon_ports)
      for p in $ports; do
        [ "$p" -ge "$((WLO + BASE))" ] && [ "$p" -le "$((WHI + BASE))" ] && { kill -9 "$pid" 2>/dev/null; break; }
      done
    done
    return 0
  fi
  pkill -9 -f '[m]odbus-cache.py' 2>/dev/null
  pkill -9 -f '[m]odbus-scraper.py' 2>/dev/null
  pkill -9 -f '[m]odbus-fake-inverter.py' 2>/dev/null
  pkill -9 -f 'bin/[d]ashboard.py' 2>/dev/null
}

for s in $SUITES; do
  N=$((N + 1))
  [ -f "tests/$s.py" ] || { say "$(date '+%H:%M:%S') SKIP $N/$TOTAL $s (no such suite)"; continue; }
  quiet
  [ "$PARALLEL" = 1 ] || { kill_daemons; sleep 2; }
  [ -n "$REMAIN" ] && say "$(date '+%H:%M:%S') START $N/$TOTAL $s eta ${REMAIN}s ($(etatime "$REMAIN"))" \
                   || say "$(date '+%H:%M:%S') START $N/$TOTAL $s"
  cp "tests/$s.py" tests/zz_bx.py
  # the /tmp scratch moves into the run dir — EXCEPT the unix-socket paths:
  # the daemons derive /tmp/<family>-*.socket from their own constants in
  # common/ (modbus-cache, fake-inverter, dashboard...), so every .socket
  # path stays put and the default-socket checks stat the real thing (the
  # basename rides %-formatting — '%d' % (port + BASE) — so the exception
  # matches any non-slash basename, not just the literal ones)
  sed -i '' "s#/tmp/#$RUNDIR/tmp/#g; s#$RUNDIR/tmp/\([^/]*\.socket\)#/tmp/\1#g" tests/zz_bx.py
  t0=$(date +%s)
  if [ "$s" = "cache-fuzz" -o "$s" = "scrape-fuzz" ]; then
    # the fuzz budget + the mode: quick pools the basic shapes, full the
    # nightly spread (both fuzz suites take [iterations] [quick|full])
    FUZZPROF=quick; [ "$PROFILE" = full ] && FUZZPROF=full
    python3 tests/zz_bx.py "${BUDGET:-3000}" "$FUZZPROF" > "$RUNDIR/$s.log" 2>&1
  else
    python3 tests/zz_bx.py > "$RUNDIR/$s.log" 2>&1
  fi
  rc=$?
  ds=$(( $(date +%s) - t0 ))
  dur=$(fmt $ds)
  # the history row lands per-suite, right away — an interrupted run keeps
  # its finished suites (the row updates in place: the suite's old row is
  # filtered out, every other row rides along untouched — never a rewrite)
  { [ -f "$ETAFILE" ] && awk -v s="$s" '$1 != s' "$ETAFILE" 2>/dev/null; echo "$s $ds"; } > "$ETAFILE.n" && mv "$ETAFILE.n" "$ETAFILE"
  if [ -n "$REMAIN" ]; then
    r=$((REMAIN - ds))
    [ $r -ge 0 ] && REMAIN=$r || REMAIN=0
  fi
  if [ $rc -eq 0 ]; then
    say "$(date '+%H:%M:%S') SUITE $N/$TOTAL $s: PASS ($dur)"
  else
    say "$(date '+%H:%M:%S') SUITE $N/$TOTAL $s: FAILED ($dur)"
    tail -6 "$RUNDIR/$s.log"
    [ -n "$STOP" ] && { say "$(date '+%H:%M:%S') STOP --stop: the batch ends here"; break; }
  fi
done
[ "$PARALLEL" = 1 ] || kill_daemons
rm -f tests/zz_bx.py
BT1=$(date +%s)
say "=== TALLY $(date '+%H:%M:%S') (the battery: $(fmt $((BT1 - BT0))))"
fail=0
N=0
for s in $SUITES; do
  N=$((N + 1))
  if [ -n "$STOP" ] && [ ! -f "$RUNDIR/$s.log" ]; then
    say "$N/$TOTAL $s: SKIPPED (--stop)"
  elif grep -q "^ALL PASS" "$RUNDIR/$s.log" 2>/dev/null && ! grep -q "^FAIL" "$RUNDIR/$s.log" 2>/dev/null; then
    say "$N/$TOTAL $s: PASS"
  else
    fail=$((fail+1)); say "$N/$TOTAL $s: NOT-GREEN"
  fi
done
[ $fail -eq 0 ] && say "BATTERY: ALL PASS" || say "BATTERY: $fail NOT GREEN"

# the archive: the run's evidence (the status, the logs, the scratch) into
# one tarball under backups/ — the scratch is text and compresses hard; the
# green runs drop tmp/ after (nothing to post-mortem), the failed ones keep
# it live. The backups keep the newest 32 (the keep-8 housekeeping ages the
# run dirs separately)
BACKUPS=$LOGROOT/backups
mkdir -p $BACKUPS
COPYFILE_DISABLE=1 tar --exclude='._*' -czf "$BACKUPS/$RUNID.tar.gz" -C $LOGROOT $RUNID 2>/dev/null
[ $fail -eq 0 ] && rm -rf $RUNDIR/tmp
ls -1dt $BACKUPS/*.tar.gz 2>/dev/null | tail -n +33 | xargs rm -f 2>/dev/null
DONE=1   # the EXIT trap stays quiet — the run finished (the trap still frees the slot + the link)
