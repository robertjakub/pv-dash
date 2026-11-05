#!/bin/sh
# pv-suite docker entrypoint: seed the config volume, then run the tool as
# the unprivileged pvsuite user.
#
# The image carries its bundled configs in /pv-suite/config-defaults; every
# file the config volume (/config) does not have yet is copied in on start —
# the bundled ones are the defaults, the copies in /config are the live ones
# (edit them there, they survive container recreation). Runs as root only for
# the seeding and drops to pvsuite via su-exec; the tool never runs as root.
set -eu

mkdir -p /config
umask_old=$(umask)
for src in /pv-suite/config-defaults/*; do
    [ -e "$src" ] || continue
    dst="/config/${src##*/}"
    if [ -e "$dst" ]; then
        echo "pv-entrypoint: keeping $dst"
    else
        case "$src" in
            *.token)
                # A token default is materialized, not copied: the first seed
                # generates a random value (the bundled file is a placeholder
                # and never reaches the volume). Owner-only 0600 — the F12
                # discipline in docs/AUDIT.md.
                umask 077
                od -An -N24 -tx1 /dev/urandom | tr -d ' \n' > "$dst"
                umask "$umask_old"
                ;;
            *)
                cp "$src" "$dst"
                ;;
        esac
        chown pvsuite:pvsuite "$dst"
        echo "pv-entrypoint: seeded $dst"
    fi
done

exec su-exec pvsuite "$@"
