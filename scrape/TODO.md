# TODO

## Open

- **the audit-finding fixes** — the scraper's own: F13 refuse to start when
  the listen host is not loopback and no token is configured (and make the
  rate limiter per-IP, not per-connection), F14 the TLS recipe (a shipped
  reverse-proxy example for anything beyond localhost), F15 a short "what
  /metrics leaks" privacy note in the README, F16 the alert rules pack
  below. See [AUDIT.md](../docs/AUDIT.md).
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
- **the alert rules pack** — a shipped Prometheus rules file next to the
  exporter: the freshness gap, the poll down, the exception-code spikes,
  the write-refusal bursts — the pages write themselves from the audit
  vocabulary. (The family pack: the cache and the dashboard contribute
  their sides.)
- **the control surface** — the only family tool without one: the JSON-lines
  control server + `scraper_ctl`/`scraper_cli` on the cache's pattern
  (`set interval` live, `show status`, the poll state) — the SIGHUP story
  is the blunt instrument today.
- **the per-phase export** — the fake serves per-phase voltages/currents
  and the unbalanced home; the scraper exports none of it. A `phase` label
  (or three suffixed metrics) closes the loop fake → scrape → dashboard.
- **the hardware soak** — everything is verified against the fake inverter
  and the fuzzers; a real SDongle week (reconnect storms, the dongle's
  single-client behaviour, real exception codes) is the last mile.
- **the CI** — GitHub Actions: the regtest + fuzz suites + `nix flake
  check` on the push; the release workflow on the tag. (Family-wide, see
  the root [TODO](../docs/TODO.md).)

## Done (the highlights; the git history has the details)

The Prometheus exporter: the profile-driven selection with the metrics
registry (the unit scaling, the string/phase splits), the static JSON
constants (lib/static.json), the bearer-token auth on /metrics with the
`--auth-token-file` option, the AUDIT trail with the thread-safe
rotation, the reconnect cycle, the scrape fuzz suite, the NixOS module,
the bin/ lib/ split (matching the cache and the inverter: the
`modbus-scraper` entry in bin/, the modules in lib/, the sample ini and
metrics.json at the subproject root) with lib/version — and the shared
core (the audit trail, the token loader, the wire helpers, the profile
resolution) moved to `common/`.
