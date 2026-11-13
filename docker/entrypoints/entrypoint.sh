#!/bin/sh
# pv-suite docker entrypoint: seed the config volume with the REQUIRED
# file artifacts, stage the compose secrets for the unprivileged user,
# then run the tool as pvsuite.
#
# The image carries only non-secret artifacts in /pv-suite/config-defaults
# (the JSON specs, the served config.js — never the bundled conf scripts:
# the tool loads the image's own conf and the per-tool env file overrides
# it, see docker/README.md); every file the config volume (/config) does
# not have yet is copied in on start — edit them there, they survive
# container recreation.
#
# The secrets never touch the volume: the compose stacks mount the
# operator-generated files as compose secrets (/run/secrets/<name> —
# docker/gen-secrets.sh generates them, the secrets story in
# docker/README.md carries the recipe and the rotation). Non-swarm
# compose keeps the bind mount's host owner, so the entrypoint stages a
# private copy for the tool's user: /run/pv-secrets/<name>, 0600
# pvsuite — the file:<path> env pins speak that path. The staging is
# ephemeral (it dies with the container; the host files never change
# owner). Runs as root only for the seeding + staging and drops to
# pvsuite via su-exec; the tool never runs as root.
set -eu

mkdir -p /config
umask_old=$(umask)
for src in /pv-suite/config-defaults/*; do
    [ -e "$src" ] || continue
    dst="/config/${src##*/}"
    if [ -e "$dst" ]; then
        echo "pv-entrypoint: keeping $dst"
    else
        cp "$src" "$dst"
        chown pvsuite:pvsuite "$dst"
        echo "pv-entrypoint: seeded $dst"
    fi
done

if [ -d /run/secrets ] && [ -n "$(ls /run/secrets 2>/dev/null)" ]; then
    umask 077
    mkdir -p /run/pv-secrets
    for src in /run/secrets/*; do
        [ -e "$src" ] || continue
        dst="/run/pv-secrets/${src##*/}"
        cp "$src" "$dst"
        chown pvsuite:pvsuite "$dst"
        echo "pv-entrypoint: staged $dst"
    done
    umask "$umask_old"
fi

exec su-exec pvsuite "$@"
