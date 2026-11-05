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

exec su-exec prometheus:prometheus prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/prometheus
