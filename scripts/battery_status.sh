#!/bin/sh
# the battery's live view: the running slot links with their status.txt
# paths and the owning pids, plus the newest finished run. The read-only
# sibling of scripts/battery.sh — nothing here mutates the battery state
# (the stale links stay for the next battery start's housekeeping sweep).
ROOT=${XDG_STATE_HOME:-$HOME/.local/state}/pvbattery
[ -d "$ROOT" ] || ROOT=/tmp/pvbattery
if [ ! -d "$ROOT" ]; then
    echo "no battery root ($ROOT is gone and so is /tmp/pvbattery)"
    exit 1
fi

n=0
for l in $ROOT/slots/slot*; do
    [ -L "$l" ] || continue
    d=$(readlink "$l" 2>/dev/null)
    pid=''
    [ -f "$d/pid" ] && pid=$(cat "$d/pid" 2>/dev/null)
    n=$((n + 1))
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        state=RUNNING
    else
        state=STALE
    fi
    # the elapsed wall time, read off the run id's <YYYYMMDD>-<HHMMSS>
    # head (the same mm:ss-over-the-minute shape battery.sh prints)
    e=''
    rid=${d##*/}
    sd=${rid%%-*}
    st=${rid#*-}; st=${st%%-*}
    e0=$(date -j -f '%Y%m%d-%H%M%S' "$sd-$st" +%s 2>/dev/null)
    [ -n "$e0" ] && e=$(( $(date +%s) - e0 ))
    [ -n "$e" ] && [ "$e" -lt 0 ] && e=0
    [ -n "$e" ] && { [ "$e" -ge 60 ] && e=$(printf '%dm%02ds' $((e / 60)) $((e % 60))) || e="${e}s"; }
    printf '%s %s pid=%s\n' "$(basename "$l")" "$state" "${pid:-none}"
    if [ "$state" = RUNNING ]; then
        # the launch config rides the battery header line (the run id and
        # pid prefix is stripped — both already sit on the slot line above)
        hdr=$(grep -m1 '^battery ' "$d/status.txt" 2>/dev/null)
        [ -n "$hdr" ] && printf '  run:    %s\n' "${hdr#*) }"
        # the run's own start estimate (battery.sh wrote it into status.txt);
        # the last line below carries the sharpened remaining eta
        est=$(grep -m1 '^estimate: ' "$d/status.txt" 2>/dev/null)
        [ -n "$est" ] && printf '  %s\n' "$est"
        # the live tally: the SUITE verdicts so far over the run's total
        # (the total rides the last START/SKIP's N/T; before the first
        # suite it falls back to the `suites:` row's word count)
        pass=$(grep -c ': PASS (' "$d/status.txt" 2>/dev/null)
        fail=$(grep -c ': FAILED (' "$d/status.txt" 2>/dev/null)
        skip=$(grep -c ' SKIP ' "$d/status.txt" 2>/dev/null)
        total=$(awk '$2 == "START" || $2 == "SKIP" { split($3, a, "/"); t = a[2] } END { print t + 0 }' "$d/status.txt" 2>/dev/null)
        [ "$total" -eq 0 ] && total=$(( $(grep -m1 '^suites: ' "$d/status.txt" 2>/dev/null | wc -w | tr -d ' ') - 1 ))
        [ "$total" -lt 0 ] && total=0
        line="  stats:  $((pass + fail + skip))/$total done, $pass pass, $fail failed"
        [ "$skip" -gt 0 ] && line="$line, $skip skipped"
        [ -n "$e" ] && line="$line, $e elapsed"
        printf '%s\n' "$line"
    fi
    printf '  status: %s/status.txt\n' "$d"
    last=$(tail -1 "$d/status.txt" 2>/dev/null)
    [ -n "$last" ] && printf '  last:   %s\n' "$last"
done
[ $n -eq 0 ] && echo 'no batteries running (no slot links)'

newest=$(ls -1dt $ROOT/2* 2>/dev/null | head -1)
if [ -n "$newest" ]; then
    for l in $ROOT/slots/slot*; do
        [ -L "$l" ] || continue
        [ "$(readlink "$l" 2>/dev/null)" = "$newest" ] && newest=''
    done
    if [ -n "$newest" ]; then
        printf 'newest finished: %s/status.txt\n' "$newest"
        last=$(tail -1 "$newest/status.txt" 2>/dev/null)
        [ -n "$last" ] && printf '  last:   %s\n' "$last"
    fi
fi
