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
    printf '%s %s pid=%s\n' "$(basename "$l")" "$state" "${pid:-none}"
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
