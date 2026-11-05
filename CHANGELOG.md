# Changelog

The suite versions as one: the number lives in `common/version.py`
(`version_string()` appends `-<short git>` in a checkout). Dates are the
tagged commits'. The early tags (before 0.1.0) carried per-tool versions —
the dashboard, the scraper and the cache each numbered their own releases
before the repo restructured into one suite.

## Unreleased

### Added

- **cache** — the state persistence (the write-behind): `--dump-path` +
  `dump-interval` (a live setting, `0` = on request) dump the cached words
  (+ their stamps) and the live setting overrides as one atomic JSON — on
  the interval, on the new `request dump` command and on every graceful
  shutdown. Loading is gated: `--restore-on-start` opts in to loading the
  dump on start (the default is starting cold; `request restore` loads on
  demand) — a gated restart serves last-known values instead of cold
  misses; the words return as they were — the ttl bounds any staleness,
  the next map swap prunes. The dump commands (and the `dump-interval`
  setting) show up in the listings only when a dump path is configured.
  The NixOS module grew `dumpPath`/`dumpInterval`/`restoreOnStart` (the
  dump dir joins `ReadWritePaths`).
- **cache, fake-inverter** — the peer-cred auth on the unix control
  sockets: with a token configured, the kernel-vouched peers (root, the
  daemon's own user, `--control-trust-uids`) skip the token handshake
  (`SO_PEERCRED`, shared `common/cred.py`; the NixOS module carries
  `controlTrustUids`); TCP peers always authenticate.
- **cache** — the NixOS module grew the `selection` option: "all"/"none",
  a list of profile names (rendered into the selection JSON the
  `--selection` flag reads) or a path to one; the `profile` option
  description now speaks the current schema (no `"cache": true` marks).
- **cache** — `show uplink`: the inverter-link report for analysing the
  upstream connection — the session counters (state, connects, exchanges,
  bytes in/out, errors, last error) and one row per poll block with its
  status (`ok`/`ex N`/`error`/`pending`), latency (last/mean/max), failure
  count and last error. The metrics endpoint exports the same state as
  `modbus_cache_uplink_*` gauges (session counters + per-block
  up/latency/fails with `fc`/`start`/`count` labels).

### Changed

- **common** — `human.secs`: one human time formatter for every command
  surface in the suite (ms/s/m/h/d, one unit, always two decimals) — the
  control reports, the set/unset confirmations, the `show cache all` /
  `show uplink` tables and the console banners all speak it now (the logs,
  the audit trail and the Prometheus endpoints keep raw seconds).
- **cache** — `show cache all` carries the cached words' values too: a
  `values` column between `words` and `age` (`-` = the register is not
  cached yet).
- **cache** — **breaking**: the per-client audit tally renamed — the event
  is `REQUESTS` (it counts reads and writes alike, so `READS` lied), the
  flag `--requests-audit`, the ini key `requests_audit_s`, the env
  `MODBUS_CACHE_REQUESTS_AUDIT`, the live setting `requests-audit` (was
  `reads-audit`), the `show status` field `requests_audit` and the NixOS
  option `requestsAudit`. Anything grepping the trail for
  `AUDIT CACHE READS` must follow.
- **scrape** — the profile `fc` awareness: a spec-bound source is read
  with its profile entry's function code (`fc: 4` = input registers, the
  default 3 unchanged) — the schema field now flows profile → source →
  wire (packed, and validated in the reply).

### Security

- **cache, inverter** — the audit findings F2–F8 (docs/AUDIT.md) closed:
  the shared audit writer folds control characters, so an embedded `\n` in
  a control command can no longer forge a trail line (F2); an unparseable
  write frame (too short to carry an address) is refused with an
  illegal-value exception instead of being forwarded past the allow-list —
  fail closed (F3, cache); the pre-auth control line buffer drops the
  connection past 1 MB instead of growing for the idle timeout (F4, both
  control servers); a TCP control port without a token refuses to start —
  the unix socket needs none (F5, cache); the metrics endpoint refuses to
  start without a bearer token and its handler socket times out after 5 s
  (F6, cache); the unix control socket is `chmod 0600` after bind (not the
  umask), with `--control-socket-group` opting into `0660` (F8, the cache's
  option; the inverter takes the default).

## 0.3.0 — 2026-11-05

The control surface, the shared core and the docs redo.

### Added

- **cache** — the JSON-lines control server with TCP token auth and the
  audit trail, the one-shot `cache_ctl` and the console-style `cache_cli`
  (reconnect cycle, registry-driven TAB/? completions), the FC4
  input-register space (per-fc poll blocks, never merged across codes),
  the per-register write allow-list, the settings registry with live
  `set`/`unset`/`show settings`, `inspect`, the per-client READS tallies,
  write-through invalidation (a forwarded write drops exactly the cached
  words it touched and wakes the poller), the sectioned console listings
  and the daemon-exit announcement, the native metrics endpoint
  (`--metrics-port`, bearer token, the `modbus_cache_*` gauges),
  `selection none` (a pass-through proxy) and the per-entry profile TTL
  (`[ttl 5s]` in `show cache all`).
- **inverter** — the JSON-lines control transport with token auth, the
  audit everywhere (INV/CLI/CTL prefixes, rotation), the battery state
  machine (efficiency, self-discharge, the 80 % discharge cap, the
  temperature derate), the grid-outage machine (random blackouts, `outage`
  forces one), the live time-scale control, the CLI auto-reconnect, the
  own metrics endpoint, the static config in JSON.
- **profiles** — `bin/profile-format.py`: rewrites any profile into the
  canonical sun2000.json layout in place (content-preserving, idempotent).
- **man pages** — one roff page per tool (`man/*.1` per subproject, 11
  total), installed by the Nix packages.
- **docker** — the modbus-scraper image and compose service, the shared
  `entrypoint.sh` (seeds the config volume from the bundled defaults,
  existing files kept, drops to `pvsuite` via `su-exec`); the profiles and
  `common/` ride in as named build contexts.

### Changed

- **common/** — the shared stdlib-only package extracted: the audit trail
  (`AuditLog`, thread-safe write+flush+rotate), the token loader, the
  profile resolution, the Modbus wire core (`ModbusError`, `recv_exact`,
  `exception_frame`), the UTC log formatter and the version string — one
  implementation for the whole family.
- **scrape/** — restructured to the family layout: `bin/modbus_scraper.py`,
  the modules in `lib/`, `scraper.ini` and `metrics.json` at the subproject
  root.
- **profiles/** — the device JSONs moved under `profiles/profiles/`, the
  linter to `bin/profile-lint.py`.

### Docs

- **AUDIT.md** — the security audit (assets/trust boundaries, implemented
  controls, findings F1–F17 with the verified reproductions, the NIS2/DORA
  mapping); absorbs the former per-subproject `secaudit.md`s.
- **SBOM.md** — the software bill of materials: the stdlib-only claim
  stated and checked per subproject, the three-wide third-party surface
  (the interpreter, the alpine images, the vendored ECharts) and the
  machine-readable `sbom.cdx.json` (CycloneDX 1.5).
- all READMEs redone against the code (the stale paths, the rotted check
  counts, the compose volume semantics, the profiles' Tools section), the
  TODOs cleaned and refilled (root + the four subprojects), this
  CHANGELOG.

## 0.2.1 — 2026-11-03

The control surface release: the fake inverter's runtime control (the
settings registry, the scenarios), the battery state machine, the docker
images and the `tests/` reorganization (the suites live at the suite root,
one or more per Modbus tool).

## 0.2.0 — 2026-11-03

- **inverter** — register-map profiles: the fake serves named physical
  values mapped onto addresses by a JSON profile (the real device codes —
  the SUN2000 and the Deye hybrids ship).
- **cache** — the control server, the console CLI, the device profiles +
  the selection file.
- **scrape** — profile-driven metrics: the exported `huawei_*` values bind
  to profile register names (`metrics.json`), not hardcoded addresses.

## 0.1.0 — 2026-11-02

The repo restructures into **pv-suite**: the fake inverter splits out of
scrape into its own subproject, the dashboard gets the `dashboard/`
subproject, the suite versions as one.

## 0.0.6 — 2026-11-02

- **modbus-cache** — the experimental Modbus TCP caching proxy: exception/
  boundary hardening, ACLs, resource limits, `--dry-run`, validated
  settings, the client-limit/timeout defaults (64/300), the fuzz suites,
  the README.
- **modbus-scraper** — the cache-style rewrite: hardened framing, the
  cache-diagnostics auto-detection (`huawei_cache_*`), READMEs
  regenerated.

## 0.0.4 — 2026-11-01

The dashboard era. The tags start here — 0.0.1 (the initial dashboard
release), 0.0.2 (the Modbus TCP Prometheus exporter joins as
`sun2000-scraper`), 0.0.3 (dashboard battery support) and 0.0.4 (the
phone-fit static layout) numbered their tools individually.
