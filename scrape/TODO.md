# TODO

## Open

- **the profile `fc` awareness** — the schema carries the `fc` field (the
  cache polls/caches FC4 independently); the scraper still reads every
  marked register with FC3 — a profile that marks an FC4 entry `scrape`
  needs the scraper to follow the field (the read layer already knows
  FC3/FC4, this is the plan + payload plumbing).
- **the multi-target scrape** — one process polling several inverters
  (per-target metrics with a unit/host label) for the two-string-roof
  households; the metrics endpoint and the audit are already per-process.
- **the poll-latency gauges** — last/max poll cycle duration as Prometheus
  gauges, so a slow dongle shows up in dashboards before the freshness
  gap does.
- **the hardware soak** — everything is verified against the fake inverter
  and the fuzzers; a real SDongle week (reconnect storms, the dongle's
  single-client behaviour, real exception codes) is the last mile.
- **the CI** — GitHub Actions: the regtest + fuzz suites + `nix flake
  check` on the push; the release workflow on the tag. (Family-wide, see
  the inverter's TODO.)

## Done (the highlights; the git history has the details)

The Prometheus exporter: the profile-driven selection with the metrics
registry (the unit scaling, the string/phase splits), the static JSON
constants (lib/static.json), the bearer-token auth on /metrics with the
`--auth-token-file` option, the AUDIT trail with the thread-safe
rotation, the reconnect cycle, the scrape fuzz suite, the NixOS module.
