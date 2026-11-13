#!/bin/sh
# Generate the compose stacks' three secrets into a target dir — the
# stack's secrets/ (docker/demo/secrets/ or docker/prod/secrets/, both
# gitignored): the suite key (modbus-auth) + the two bearer tokens
# (metrics-token for the exporter, page-token for the dashboard). Each
# file is 32 random bytes hex-encoded, 0600 — the F12 discipline in
# docs/SECURITY.md. The compose secrets story (the mounts, the staging,
# the rotation): docker/README.md.
#
# An existing secret is kept, never overwritten — rotation is an
# explicit operator act (delete the file, re-run, recreate the stack).
#
# Usage: sh docker/gen-secrets.sh docker/demo/secrets
set -eu

[ $# -eq 1 ] || { echo "usage: $0 <target-dir>" >&2; exit 2; }
dir=$1
mkdir -p "$dir"
umask 077
for name in modbus-auth metrics-token page-token; do
    dst="$dir/$name"
    if [ -e "$dst" ]; then
        echo "gen-secrets: keeping $dst"
    else
        od -An -N32 -tx1 /dev/urandom | tr -d ' \n' > "$dst"
        echo "gen-secrets: generated $dst"
    fi
done
