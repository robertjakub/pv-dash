# TODO (one file to rule them all)

Every **open** item lives here — grouped by theme, each tagged
`[cache]` `[scraper]` `[inverter]` `[dashboard]` `[common]` `[docker]`
(untagged = the whole family). The per-subproject `TODO.md` files keep only
the **Done/history** records for their tool.

## The next breaking wave (the interface evolution)

- **the CLI redone: hierarchical commands, one grammar for the family**
  `[common]` `[cache]` `[inverter]` `[scraper]` — the control vocabulary
  grew organically per tool and it shows: flatten it into namespaces and
  make every tool speak the same shape — `set modbus-client max-per-ip 8`
  (the surface, then the knob) instead of the flat `set max-conn-per-ip`,
  `set metrics-server off` / `set metrics listen 0.0.0.0:9252` on all
  three control servers, the same verbs everywhere
  (set/unset/show/request/...), the same reply shapes. Breaking: every
   script and unit file speaking the old flat grammar follows. (The ground
   work stands now — Nov 2026: the registry `live` name is a `/`-path
   spelled as words on the wire — the daemon dispatch keys the live name,
   `_apply`/`_get`/`defaults` follow the rename — and every row may carry
   a display `group` — the cli `?`/TAB listings group by it alone,
   `[ungrouped]` when a row carries none; the first group rows are filed
   (the `upstream` knobs) and the first paths too (the scraper's
   `limits/max-conn-per-ip`; the cache's `write/allow` + `write/registers`
   under the new `write` node — the dispatch, the dump keys and the unset
   defaults rekeyed, the config scripts keeping the flat names) — and a
   row may carry an `alias`, a second wire spelling for the same knob
   (the cache's `write/acl` — the dispatch canonicalizes, the consoles
   complete both spellings, the node's namespace help lists the aliased
   child) — and a typed row (`int`/`float`/`str`)
   dispatches itself now: the conv parses, the config key takes the
   value, no `_apply`/`_get` branch needed (the branches stay for the
   range gates and the runtime plumbing; the `unset` defaults generate
   from the rows) — the renames below are still open.)

## The security wave (the audit follow-ups)

- **the remaining audit findings** `[cache]` `[scraper]` `[inverter]`
  `[docker]` — all documented trust decisions / deployment stories now
  (F19 closed rev. 5 — the workflow cuts the release after the CI gate,
  see the release-discipline item): F16 (the alert-rules pack — the rules
  item below), F17 (the volume secrets), F14 (TLS — the item below), F15
  (closed — the README privacy note), F1 (accepted) — see
  [AUDIT.md](AUDIT.md); F2–F10, F11–F13, F18 and F19 are closed and
  verified (§3.1/§4); re-run the audit after the scraper control surface,
  the TLS story or the dashboard service (the dashboard is the next audit
  wave).
- **native TLS on the HTTP surfaces** `[scraper]` `[cache]` `[inverter]` —
  F14 says "terminate at a proxy"; an opt-in native path
  (`--metrics-cert`/`--metrics-key`, stdlib `ssl`) would make a
  proxy-less LAN install defensible: the bearer token stops travelling in
  clear text. The Modbus side stays F1 (accepted, protocol-inherent).
- **a connect ACL for the fake's Modbus** `[inverter]` — F11 closed
  without one (a test tool, trusted LAN); an opt-in `--connect-acl`
  mirroring the cache's would let the paranoid demo the ACL story end to
  end without touching the fake's soft-edge posture.
- **the audit trail forwarding** `[common]` — F10's strong answer as an
  option: `--audit-forward syslog` (stdlib `SysLogHandler`, journald picks
  it up sealed) next to the file/stdout sinks; the hash chains + the
  forwarding together close the retention/immutability story properly.
- **the systemd unit hardening review** `[common]` — the NixOS modules
  ship `PrivateTmp`; a full sandbox pass (`ProtectSystem=strict`,
  `PrivateDevices`, `ProtectHome`, `RestrictAddressFamilies`,
  `CapabilityBoundingSet=`) per service, verified with
  `systemd-analyze security` (a score per unit in the NixOS test).

## The pipeline (CI, releases, supply chain)

- **the CI** `[all]` — GitHub Actions: the ten suites + `nix flake check`
  (all four packages, all systems) on the push; the release workflow on
  the tag; the man pages linted (`mandoc -Tlint`) as a job; `promtool
  check metrics` on a sample exposition.
- **nightly long fuzz + a container smoke** `[all]` `[docker]` — the fuzz
  suites run short on push; a nightly workflow with big budgets
  (`cache-fuzz 10000`, `scrape-fuzz 10000`, `control-fuzz`, the stress
  suite) plus `docker compose up` (the Prometheus answers, no tracebacks
  in the logs).
- **the SBOM / supply-chain note** `[common]` —
  [sbom/SBOM.md](sbom/SBOM.md) + `sbom/sbom.cdx.json` state the
  stdlib-only claim per subproject (the machine-readable CycloneDX copy
  rides along); what remains is the automation: generate and check both in
  the release workflow, so the claim stays audited, not asserted. Also: a
  check that the vendored ECharts copy (the dashboard's one vendor)
  matches its recorded version.
- **the release discipline** `[common]` — **done**: `scripts/release.py`
  (the orchestrator: the version sweep, the changelog rename, the
  flake.lock refresh, the verification, the commit, the annotated tag —
  signed when a key exists — and the push) plus the tag-triggered
  workflow, which is the release's cutter now (**F19 closed**,
  docs/AUDIT.md rev. 5): the local gate defaults to `--tests full`, the GH
  release is the workflow's `needs: [test, build]`-gated job and the local
  cut is the opt-in `--release`. Watch the first few flights, then retire
  the training wheels.

## The product (what the tools do next)

- **the rest of the demo stack** `[docker]` `[dashboard]` — the compose
  chain runs the three Modbus tools (fake inverter → cache → scraper) with
  the seeded `/config` volume, and a **Prometheus** service scrapes the
  exporter over the internal network (the scraper/token story: a random
  bearer token generated into the volume, 0600); what is missing is the
  front: a **dashboard** service rendering the Prometheus — plus the demo
  config seeded into the volume (the cache's `allow-write` demo pokes, the
  dashboard's `battery: true`), so `docker compose up` and the whole story
  runs — the write-through pokes land in the charts live, the outages
  banner themselves, the audit trail narrates.
- **the alert rules pack** `[scraper]` `[cache]` — a shipped Prometheus
  rules file next to the exporter: the freshness gap, the poll down, the
  exception-code spikes, the write-refusal bursts (F16) — the cache
  contributes its side (poll down, age spikes, write refusals); the pages
  write themselves from the audit vocabulary.
- **the multi-target scrape** `[scraper]` — one process polling several
  inverters (per-target metrics with a unit/host label) for the
  two-string-roof households; the metrics endpoint and the audit are
  already per-process.
- **the priced grid machine** `[inverter]` — a tariff-aware import/export
  model on top of the `grid` setpoint (a price curve → the battery
  greedy/eco strategies).
- **the tariff / cost panels** `[dashboard]` — once the priced grid
  machine defines a price curve: import cost, export revenue, self-cost —
  the money view next to the energy view.
- **the forecast curve** `[inverter]` — the PV/cloud machines follow a
  day-ahead forecast file, so a demo runs repeatable weather instead of
  the RNG.
- **the forecast overlay** `[dashboard]` — when the fake grows the
  forecast curve and a real forecast source exists: the expected-PV curve
  behind the measured one, the underperformance visible without doing
  math.
- **the battery ageing** `[inverter]` — the SoH drift over the simulated
  days (the capacity shrinks a %/week of the simulated time) + the
  `battery_soh` gauge on /metrics.
- **the battery SoH panels** `[dashboard]` — when the ageing model lands,
  add the SoH gauge and let the capacity panels use the live value.
- **the machine gauges on /metrics** `[inverter]` — the state machines'
  internals as Prometheus gauges (cloud factor, outage state, per-string
  power, the battery's decision): dashboards and the scrape fuzzing could
  watch the machines, not just the registers they feed.
- **the frequency-based derate** `[inverter]` — the machine already
  wanders ±0.2 Hz around `--grid-frequency`; beyond a deviation bound the
  output power should derate (exposed on /metrics too).
- **the multi-unit serve** `[inverter]` — one process serving two Modbus
  units (the inverter + the meter as separate unit ids) for the
  gateway-style setups.
- **the fault/alarm registers** `[inverter]` → `[cache]` `[scraper]`
  `[dashboard]` — device health words driven by the machines (an outage
  raises a fault, the derate a warning, the battery cap a SoC notice): the
  cache/scrape export them and the dashboard can banner a fault, not just
  a blackout.
- **the user-defined scenarios** `[inverter]` — scene files (the time +
  the pins + the machines) loadable with `set scenario <file>`; the audit
  trail of a manual session could *record* one.
- **the dongle latency profile** `[inverter]` — a persistent slow-reply
  mode (the laggy-modem character: every response delayed, not dropped) to
  exercise read-delay and poll pacing against a realistic SDongle — the
  chaos `stall` is a one-shot, a real dongle is a lifestyle.
- **the dashboard's auth story** `[dashboard]` — the server binds
  `0.0.0.0` by default with no authentication on page or proxy; the README
  documents the loopback/reverse-proxy paths, but a bearer check mirroring
  the scraper's (or at least a loud startup note) belongs in the server
  itself before anything leaves localhost — the audit raised the same gap
  as **F21** (docs/AUDIT.md, rev. 6); close them together.
- **the cache gauges panels** `[dashboard]` — the cache's metrics endpoint
  exists (the `modbus_cache_*` gauges); chart the hit/miss ratio, the
  cache age and the poll health next to the generation panels.
- **the outage banner** `[dashboard]` — the inverter simulates grid
  outages and the meter goes dark; the dashboard could show a standing
  banner (and an annotation gap on the charts) instead of a silent zero
  flatline.
- **the write console** `[dashboard]` `[cache]` — a guarded panel issuing
  single-register writes through the cache's allow-list (the write-through
  lands the value in the charts instantly): the ops poke, audited with the
  writer's identity.
- **the event feed** `[dashboard]` — the audit vocabulary (writes,
  refusals, outages, reloads) as a dashboard side panel, instead of the
  journalctl detour.
- **the Prometheus annotations** `[dashboard]` — outages, reloads and
  (with the write console) manual pokes rendered as chart annotations,
  once the event feed exists.
- **the range picker** `[dashboard]` — the time-range control beyond the
  default window (presets + a from/to picker) on top of the existing query
  plumbing.
- **the German strings** `[dashboard]` — the i18n merge makes a third
  language cheap (`de: { ... }` in `i18n.js`, the switcher grows
  automatically).
- **the mobile pass** `[dashboard]` — the flow diagram and the header
  controls assume a desk-sized window; a small-screen layout (the chart
  full-width, the KPI row scrollable) makes the LAN page phone-friendly.
- **an ops `doctor` command per tool** `[common]` — one shot: validate the
  config, check the token-file modes, probe the upstream (Modbus read),
  probe the metrics endpoint (auth + scrape), stat the dump/audit files,
  print the findings as one report — the "why is my scrape red" first
  stop.
- **a Modbus capture/replay tool** `[common]` `[inverter]` — a `pv-suite`
  sidecar that sits on a TCP connection and dumps the wire to a file (and
  replays it): debugging the poll planning, the write-through and the
  chaos behavior against real hardware traces without the hardware.
- **the hardware verification** `[cache]` `[scraper]` — everything is
  verified against the fake inverter, fuzzing and stress only; a real
  SUN2000/SDongle week (poll pacing, the dongle's single-client
  behaviour, real exception codes, the FC4 input registers, reconnect
  storms; the Deye profiles through the cache) is the last mile.
- **the docs site** `[common]` — **the scaffold is in** (`docs/book/`, the
  mdBook form: the READMEs/audit/TODO/changelog included via
  `{{#include}}`); what remains is the publishing: build + deploy the book
  on GH Pages in the CI item's workflow.


## Done (the highlights; the git history has the details)

- **the env-prefix retirement** — the env twins are the knobs' bare
  upper-snake names (`HOST`, `PORT`, `LISTEN`, `CTL`, `CONTROL_TOKEN`,
  ...) — the per-tool prefixes (`MCH_*`/`SCR_*`/`INV_*`/`DSH_*`) retired;
  the twins are scoped per deployment surface (the systemd unit, the
  compose service, the dev shell), so the shared names stay safe. The
  cache is retagged to its device-first tagline ("Modbus TCP caching
  proxy for single-client devices") and the metrics renames' last stale
  mentions are fixed (the scrape README's metrics table, the dashboard's
  `batteryFlag` default); the man pages rebuilt.
- **the rename + env-prefix wave** — the bins and clients carry their
  man-page names (the dash names: `modbus-cache.py`,
  `modbus-cache-ctl.py`, `modbus-scraper*.py`, `modbus-fake-*.py`,
  `dashboard-*.py`); every env twin wears its tool's prefix — `MCH_*`
  (cache), `SCR_*` (scraper), `INV_*` (fake), `DSH_*` (dashboard, the
  generic docker envs retired) — with the one short `*_CTL` form for the
  control port; the constants audit put `log_levels` in every tool's
  `lib/static.json` (and the metrics-endpoint defaults on the dashboard),
  and the scraper's register map now lives in the device profile alone —
  the register/scale knobs are gone and `set profile` swaps the map live
  (a bad profile rolls back).
- **the config-format wave** — the ini is gone (the breaking wave): the
  config files speak the control grammar (`set <name> <value>` lines, `#`
  comments — a config file pipes through a ctl client), `show config`
  regenerates the script from the running daemon (secrets hidden),
  `help config` maps every knob to its control command, the bundled
  samples and the NixOS modules render the set grammar, and the
  **one-knob-one-source** registry (`lib/options.json` + its loader
  `lib/options.py` per tool on `common/options.py`) +
  `scripts/check_options.py` gate the four
  surfaces against drift. Also closed in the wave: the RBAC verb policy
  (`--control-ops-verbs`), the dashboard's own /metrics endpoint, the
  metrics.json sections + `--metric-prefix` + the `scraper_*` renames
  (the `scraper` section since moved to `lib/metrics.json`, merged in
  memory over the configured spec),
  the poll-latency gauges, the shipped FC4 profile
  (`profiles/profiles/demo-fc4.json`) and the per-phase chain (the
  metrics + the dashboard's phase strip); the scrape README carries the
  F15 privacy note.
- **the read-only control role** — the former open item ("a second token
  granting only the show/clear verbs") shipped family-wide: every control
  server takes `--control-ops-token`/`--control-ops-token-file` and scopes
  its ops sessions to the show/clear verbs — the ops shift versus the
  admin key, both audited (`role=ops`/`role=admin` in the COMMAND
  entries). The per-tool records name the flag/env forms; the audit wave
  is docs/AUDIT.md rev. 7 (F22 raised and closed with it).
- **the metrics endpoint wave** — the caps (max-clients/client-timeout/
  max-conn-per-ip) on every HTTP + Modbus surface, the fake's and the
  cache's endpoints live-togglable (`metrics-server` + `--metrics-listen`),
  the scraper refusing a non-loopback listen without a token (F13 closed).
- **the integrity wave** — the audit trails carry chained per-writer
  hashes verified by `scripts/audit_verify.py` (F10); the state dump is
  0600 + integrity-hashed with a fail-closed restore (F18); the dump
  splits by content (settings by default, with-cache on request).
- **the release tooling** — `scripts/release.py` + the tag-triggered
  release workflow (the pipeline item above is the operational follow-up).
- **the token-file env honored** `[inverter]` — the help promised
  `CONTROL_TOKEN_FILE` / `METRICS_TOKEN_FILE`, the code never
  read them: both are honored now (the fake and the two clients — flag
  over env, the file over the plain token, both together the
  mutual-exclusion error).
- **the man pages** — one roff page per tool in each subproject's `man/`
  (`man/` per subproject; 11 pages total: the three cache binaries,
  the three inverter binaries, the scraper, the dashboard server, the two
  profile tools), installed by the Nix packages (`share/man/man1/`) and
  linted with `mandoc -Tlint`.
- **the demo stack, the Modbus chain** — `docker/compose.yaml`: the three
  alpine images (one Dockerfile per tool, unprivileged `pvsuite`, tools on
  `PATH`), the shared external `config` volume seeded by `entrypoint.sh`
  (bundled defaults copied in, existing files kept), the profiles +
  `common/` riding in as named build contexts.
- **the profile linter** — `profiles/bin/profile-lint.py`: the required
  keys and their family order, the register bounds, the type width, the
  fc, the per-entry ttl, the mappings vs a register word, the duplicate
  names, the same-fc overlaps, the terse-ASCII style; all four shipped
  profiles lint clean.
- **the profile formatter** — `profiles/bin/profile-format.py`: rewrites
  any profile into the sun2000.json layout in place — one mappings entry
  per line, one register per line, keys in the family order;
  content-preserving and idempotent (the sun2000 itself comes back
  byte-for-byte).
- **the common/ package** — the shared core extracted: version, audit,
  config plumbing, the Modbus wire core, the UTC log formatter; the suite
  talks one vocabulary.

Per-tool **Done/history** lives in each subproject's own TODO.md
([cache](../cache/TODO.md), [scraper](../scraper/TODO.md),
[inverter](../inverter/TODO.md), [dashboard](../dashboard/TODO.md)).
