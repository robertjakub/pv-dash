#!/bin/sh
# The demo Prometheus's entrypoint: wait for the metrics bearer token in
# the shared config volume (the modbus-scraper's entrypoint seeds it —
# a random value, 0600, owner pvsuite), copy it for the prometheus user
# (0600 — the token-file discipline, F12 in docs/AUDIT.md), then exec
# prometheus unprivileged via su-exec. Runs as root only for that
# handoff; prometheus never runs as root.
set -eu

TOKEN_SRC=/config/metrics.token
TOKEN_DST=/etc/prometheus/metrics.token

i=0
while [ ! -f "$TOKEN_SRC" ] && [ "$i" -lt 60 ]; do
    i=$((i + 1))
    sleep 0.5
done
if [ ! -f "$TOKEN_SRC" ]; then
    echo "pv-prometheus-entrypoint: no $TOKEN_SRC in the config volume — " \
         "start the modbus-scraper service once so its entrypoint seeds the token" >&2
    exit 1
fi

umask 077
cp "$TOKEN_SRC" "$TOKEN_DST"
chown prometheus:prometheus "$TOKEN_DST" /prometheus

# The knobs the env file (env/prometheus.env) or a docker -e can set —
# PROM_RETENTION (the TSDB retention, a prometheus duration: 15d, 90d,
# 1y, ...; default 90d), PROM_LIFECYCLE=on (the lifecycle API: POST
# /-/reload after editing prometheus.yml, POST /-/quit) and
# PROM_ADMIN_API=on (the admin API: snapshots, delete_series — powerful
# and destructive, keep off unless a runbook needs it). The endpoints
# sit on the internal network only, and the lifecycle API can stop the
# collector: enable deliberately. An empty value means unset.
PROM_ARGS="--config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus"
PROM_RETENTION="${PROM_RETENTION:-90d}"
PROM_ARGS="$PROM_ARGS --storage.tsdb.retention.time=$PROM_RETENTION"
if [ "${PROM_LIFECYCLE:-}" = "on" ]; then
    PROM_ARGS="$PROM_ARGS --web.enable-lifecycle"
fi
if [ "${PROM_ADMIN_API:-}" = "on" ]; then
    PROM_ARGS="$PROM_ARGS --web.enable-admin-api"
fi

exec su-exec prometheus:prometheus prometheus $PROM_ARGS
