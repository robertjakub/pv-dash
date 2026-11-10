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
#   scripts/battery.sh quick          # all ten, the fuzzes at 300 (~13 min) — serial
#   scripts/battery.sh full           # all ten, the suite defaults (~40 min) — the nightly, serial
#   scripts/battery.sh <suite> ...    # explicit names, e.g. cache-regtest inverter-regtest
#
# Every run works inside its own dedicated dir: /tmp/pvbattery/<run-id>/
# (the suites' /tmp scratch is rewritten into it, except the daemon-derived
# unix sockets, which stay at /tmp/modbus-*.socket — their paths are the
# daemons' own constants). The live status: /tmp/pvbattery/latest/ is a
# symlink to the current run — `tail -f /tmp/pvbattery/latest/status.txt`.
#
# One suite at a time within a run; a suite's verdict = its own ALL PASS
# with no FAIL lines; the tally lands at the end of the status file.

cd "$(dirname "$0")/.." || exit 1
LOGROOT=/tmp/pvbattery
mkdir -p $LOGROOT/slots
PROFILE="${1:-commit}"
RUNID="$(date +%Y%m%d-%H%M%S)-$PROFILE"
RUNDIR=$LOGROOT/$RUNID
mkdir -p "$RUNDIR/tmp"
ln -sfn "$RUNDIR" $LOGROOT/latest
STATUS=$RUNDIR/status.txt

say() { echo "$1"; echo "$1" >> $STATUS; }

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

# the port-space slot: a concurrent battery takes a free slot; its base is
# the slot's thousand-step port shift. A slot whose owning pid is gone is
# stale and gets reclaimed.
SLOT=''
for n in 0 1 2 3 4 5 6 7; do
  d=$LOGROOT/slots/slot$n
  if mkdir "$d" 2>/dev/null; then
    SLOT=$n; echo $$ > "$d/pid"; break
  fi
  pid=$(cat "$d/pid" 2>/dev/null)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
    rmdir "$d" 2>/dev/null && mkdir "$d" 2>/dev/null && { SLOT=$n; echo $$ > "$d/pid"; break; }
  fi
done
if [ "$PARALLEL" = 1 ] && [ -z "$SLOT" ]; then
  echo "battery: no free port-space slot (8 concurrent batteries max) — waiting one is fine, or run a serial profile"
  exit 1
fi
if [ -n "$SLOT" ]; then
  BASE=$((SLOT * 1000))
  export SUITE_PORT_BASE=$BASE
else
  BASE=0
fi
export PYTHONUNBUFFERED=1   # the daemons' stderr (their logs) must not sit in a lost block buffer
trap 'rmdir $LOGROOT/slots/slot$SLOT 2>/dev/null' EXIT INT TERM

say "battery $RUNID (pid $$) profile=$PROFILE budget=${BUDGET:-suite defaults} slot=${SLOT:-none} base=$BASE"
say "suites: $SUITES"

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
  [ -f "tests/$s.py" ] || { say "$(date '+%H:%M:%S') SKIP $s (no such suite)"; continue; }
  quiet
  [ "$PARALLEL" = 1 ] || { kill_daemons; sleep 2; }
  say "$(date '+%H:%M:%S') START $s"
  cp "tests/$s.py" tests/zz_bx.py
  # the /tmp scratch moves into the run dir — EXCEPT the unix-socket paths:
  # the daemons derive /tmp/<family>-*.socket from their own constants in
  # common/ (modbus-cache, fake-inverter, dashboard...), so every .socket
  # path stays put and the default-socket checks stat the real thing
  sed -i '' "s#/tmp/#$RUNDIR/tmp/#g; s#$RUNDIR/tmp/\([a-z0-9.-]*\.socket\)#/tmp/\1#g" tests/zz_bx.py
  if [ -n "$BUDGET" ] && [ "$s" = "cache-fuzz" -o "$s" = "scrape-fuzz" ]; then
    python3 tests/zz_bx.py "$BUDGET" > "$RUNDIR/$s.log" 2>&1
  else
    python3 tests/zz_bx.py > "$RUNDIR/$s.log" 2>&1
  fi
  if [ $? -eq 0 ]; then
    say "$(date '+%H:%M:%S') SUITE $s: PASS"
  else
    say "$(date '+%H:%M:%S') SUITE $s: FAILED"
    tail -6 "$RUNDIR/$s.log"
  fi
done
[ "$PARALLEL" = 1 ] || kill_daemons
rm -f tests/zz_bx.py
say "=== TALLY $(date '+%H:%M:%S')"
fail=0
for s in $SUITES; do
  if grep -q "^ALL PASS" "$RUNDIR/$s.log" 2>/dev/null && ! grep -q "^FAIL" "$RUNDIR/$s.log" 2>/dev/null; then
    say "$s: PASS"
  else
    fail=$((fail+1)); say "$s: NOT-GREEN"
  fi
done
[ $fail -eq 0 ] && say "BATTERY: ALL PASS" || say "BATTERY: $fail NOT GREEN"
