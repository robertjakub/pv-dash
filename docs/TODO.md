# TODO (one file to rule them all)

Every **open** item lives here — grouped by theme, each tagged
`[cache]` `[scraper]` `[inverter]` `[dashboard]` `[common]` `[docker]`
(untagged = the whole family). The per-subproject `TODO.md` files keep
only the **Done/history** records for their tool —
[cache](../cache/TODO.md), [scraper](../scraper/TODO.md),
[inverter](../inverter/TODO.md), [dashboard](../dashboard/TODO.md).

## The control plane (the grammar follow-through)

- **row the fake's write-emulation words** `[inverter]` — `register`,
  `coil`, `discrete` are set-only pseudo-settings the wire answers (the
  write-overlay emulation, `set register <addr>=<val>`) with no registry
  rows: the cli's special-case pin died with the internal-mark wave (the
  words stopped completing/describing — the wire, the suites and the
  overlay are untouched), and the registry should either gain their
  hidden command rows or the "set/show the registers" redesign (the
  product item below) subsumes them.
- **check the values against the hints** `[common]` `[cache]`
  `[scraper]` `[inverter]` `[dashboard]` — the value-shape hint's
  convention is the FULL shape (the free-form parts and the vocabulary
  words — `modbus/selection`'s `<file>|all|none`), but the rows drift:
  `modbus/profile`'s hint is `<file>` while its values carry `default`
  (the word missing from the hint), and the bool rows carry no hint at
  all while   `modbus/auth` spells `suite|none` — walk every row in the
  four registries, align the hints (the missing value words in, the
  stale words out) and decide the bool rule once (a hint or not).

## The security wave (the audit follow-ups)

- **the remaining audit findings** `[cache]` `[scraper]` `[inverter]`
  `[docker]` — the open set (per [SECURITY.md](SECURITY.md) rev. 28): F17
  (the volume secrets), F14 (TLS — the item below), F15 (INFO — the
  bearer token + the localhost bind are the controls, the scraper
  README carries the privacy note), F1 (accepted); re-run the audit
  after the TLS story (F14) lands, after the multi-target /
  control-plane evolutions, or any new listener or file format; at
  least yearly otherwise. The closed findings F2–F13, F16, F18–F23
  with their fix and verification:
  [history/AUDIT.md](history/AUDIT.md).
- **the RBAC rewrite** `[common]` — the role gate decides on the head
  verb (`command_verb` = the first word, `common/wire/wiresec.py`) with the
  flat verb-set policies (`ROLE_POLICIES`); the request-namespace grammar
  (`request flush cache` — the flush/unset rename wave) already needs
  the "skip the prefix" rule patched into the extraction, and the
  per-child authority (the ops shift may `request flush`, never
  `request reload`) is policy-shaped, not extraction-shaped: rewrite the
  gate to decide on the command PATH — the leaf units with per-child
  policies (`request/flush` in the ops set, `request/reload` out) —
  instead of patching the head-word verb; the audit `role=` entries and
  the `--control-ops-verbs` validation follow the same units.
- **a connect ACL for the control plane** `[common]` `[cache]`
  `[scraper]` `[inverter]` `[dashboard]` — SKETCH (Nov 8, decided against
  for today): the control TCP bind is hardcoded `127.0.0.1`
  (`common/wire/control.py`'s `_open_sock`), so an IP gate would decide only
  on the one address that always matches — the local-user threat the
  plane actually has is answered by peer-cred (the unix socket) and the
  token + the signed wire + the ops RBAC (TCP). The item earns its place
  the moment the control port learns to bind beyond loopback: the control
  target grows the `HOST:PORT` spelling (the unix path stays; the default
  stays loopback; `parse_control_target` parses the host part on the
  daemon AND the ctl clients), and a beyond-loopback bind then ships with
  TWO hard companions, the same refusal shape the tokenless TCP already
  speaks: the admin token mandatory (it is today), and an explicit
  **`acl/control`** gate — the ip-prefix system grammar
  (`any|none|IP,...`) or `file:<path>` (the standalone acl file) — with
  `none` NOT the default but a REFUSAL to start until spelled (a remote
  control port without a spelled gate is a misprint, not a posture). The
  machinery is all built (parse_acl_value, IPGate, the acl-file warning
  parity, the `show acl/control/table` row, the connect-time check in the
  accept ladder beside the peer-cred/token checks, the refusals logged +
  audited like the Modbus ones); the unix sockets are untouched (peer-cred
  answers the uid question addresses cannot). The fake included: its
  tokenless-loopback TCP exemption (F11) rides on the bind staying
  loopback — a remote control bind on the fake takes the same companions.
  Re-run the audit when this lands (the remote-control surface is new
  F-item territory).
- **IPv6 on the serving surfaces (and the ACL boundary)** `[common]`
  `[cache]` `[scraper]` `[inverter]` `[docker]` — SKETCH (Nov 8): the
  ACL machinery already speaks both families (the ip-prefix matchers
  validate v6 strict-CIDR, `any` matches every address of either family,
  `is_loopback_host` knows `::1`/`[::1]`, and the CLIENT side is done —
  `socket.create_connection` dials whatever the name resolves, so
  `--upstream '[2001:db8::10]:502'` and a DNS-named v6 inverter work
  today). What does not: every LISTENING socket is hard
  `socket.AF_INET` (the Modbus listen, the control TCP, the metrics
  HTTP — a `[::1]:PORT` bind dies in the address-family error), and on a
  dual-stack socket the peers arrive v4-MAPPED (`::ffff:10.0.0.5`) —
  the ACL boundary would double-book the same client unless normalized.
  The wave: one shared `serve(host, port)`-shaped opener (AF_INET6 when
  the host parses v6, `V6ONLY` off for the dual-stack every-address
  bind, `on` for `::1`), the v4-mapped peer normalization at ONE shared
  helper (the connect/write ACL checks, the caps' per-IP keying, the
  logs/audit peer spellings — a v4 client on a dual-stack socket must
  stay `10.0.0.5` to the ACL, not `::ffff:10.0.0.5`), `parse_listen`'s
  bracketed grammar verified end to end, the regtest coverage on the
  `::1` pair (the v6 loopback works on Linux and macOS alike; the
  v4-mapped carve proof), and the doc pass (docs/common/ACL.md's family notes,
  the AUDIT posture rows, the NixOS `listenHost`'s v6 spelling + the
  dual-stack note — `openFirewall`'s v6 half is the deployment's
  ip6tables business). The docker compose network stays v4 (the demo's
  story); a v6 flag there is optional polish.
- **native TLS on the HTTP surfaces** `[scraper]` `[cache]` `[inverter]` —
  F14 says "terminate at a proxy"; an opt-in native path
  (`--metrics-cert`/`--metrics-key`, stdlib `ssl`) would make a
  proxy-less LAN install defensible: the bearer token stops travelling in
  clear text. The Modbus side stays F1 (accepted, protocol-inherent).
- **TLS on the audit forward** `[common]` — the target grammar's `tls://`
  spelling (deliberately out of rev. 27): RFC5425 (TLS over the
  octet-count framing) with the client certificates needs a real TLS
  collector to test against (the suite cannot generate the certificates),
  so the anchor lives here until one exists; `tls://…` today gets the
  generic unknown-scheme refusal.
## The pipeline (CI, releases, supply chain)

- **schema every family JSON** `[common]` — `scripts/validate_json.py`
  speaks the draft-2020-12 core but only the shipped spec pairs meet it
  today (the drift sweep's schema/example pass). Give the family's
  remaining JSON artifacts schemas and one gate: `shared/texts.json`,
  the four `options.json`/`static.json` pairs, the profiles' format
  (profile-lint checks it in code — a schema would let editors speak
  it) and the config-defaults placeholders; decide the surface (a lint
  script riding the release battery, a drift-sweep type or its own CI
  leg).
- **the CI** `[all]` — GitHub Actions: the ten suites + `nix flake check`
  (all four packages, all systems) on the push; the release workflow on
  the tag; the man pages linted (`mandoc -Tlint`) as a job; `promtool
  check metrics` on a sample exposition.
- **nightly long fuzz + a container smoke** `[all]` `[docker]` — the fuzz
  suites run short on push; a nightly workflow with big budgets
  (`cache-fuzz 10000`, `scrape-fuzz 10000`, `control-fuzz`, the stress
  suite) plus `docker compose up` (the Prometheus answers, no tracebacks
  in the logs).
- **the SBOM / supply-chain note** `[common]` — **done**: `scripts/gen_sbom.py`
  generates both [sbom/SBOM.md](sbom/SBOM.md) + `sbom/sbom.cdx.json` from
  the tree (the import scan gates the render — a foreign dependency fails
  the generation; the vendored ECharts version and its bundled zrender are
  read out of the shipped bundle itself), and the release workflow's `sbom`
  job runs `gen_sbom.py --check` (regenerate + diff), so the pair cannot go
  stale silently.
- **the release discipline** `[common]` — **done**: `scripts/release.py`
  (the orchestrator: the version sweep, the changelog rename, the
  flake.lock refresh, the verification, the commit, the annotated tag —
  signed when a key exists — and the push) plus the tag-triggered
  workflow, which is the release's cutter now (**F19 closed**,
  docs/SECURITY.md rev. 5): the local gate defaults to `--tests full`, the GH
  release is the workflow's `needs: [test, build]`-gated job and the local
  cut is the opt-in `--release`. Watch the first few flights, then retire
  the training wheels.

## The product (what the tools do next)

- **the dashboard UI redesign** `[dashboard]` — battery support is always
  on now (the `--battery` knob retired family-wide, the served
  `config.js` always carries `battery: true`), but the front end still
  treats the battery as an add-on: the `batteryEnabled` gate (config.js +
  the `?battery=1` URL escape), the dimmed-node / "no battery detected"
  banner path, and the generation-first layout. Redesign the UI around
  the battery as a first-class, always-present citizen (the flow diagram,
  the KPI row, the energy split) — and reconsider the layout while in
  there.

- **the demo's write-poke conf** `[docker]` `[cache]` — the demo stack
  is complete (the four services + Prometheus, the dashboard renders
  it, the token story seeded); what remains of the old demo-stack item
  is the demo nicety: a seeded cache conf (or a ctl poke script) that
  turns `allow-write` on with a small register allow-list, so the
  write-through pokes land in the charts live — deliberately NOT the
  default (the demo README documents `allow-write` off).
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
- **set/show the registers (F1/2/3/4)** `[inverter]` — the fake's control
  plane goes fc-aware: the pin verbs take a space qualifier
  (`set register [fc3|fc4] <addr> <value>`, `set coil [fc1|fc2] <addr>
  <0|1>` — the bare form keeps today's space; `discrete`/`input-register`
  the sugar spellings, one store per space) and a first-class
  `input-register` row (the flat name; the live `input/register` path
  under an `input` node) pins the input space — no wire write exists
  there, so its pins ride the dump/restore as a live override while
  register/coil/discrete stay undumped; `show registers` gains the fc
  column + per-space pin markers (today the overlay `*` misfires on fc4
  rows); reset/SIGUSR1/inspect count the fourth map; the suite drives
  `profiles/profiles/demo-fc4.json` for it.
- **the dongle latency profile** `[inverter]` — a persistent slow-reply
  mode (the laggy-modem character: every response delayed, not dropped) to
  exercise read-delay and poll pacing against a realistic SDongle — the
  chaos `stall` is a one-shot, a real dongle is a lifestyle.
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
- **the REST API** — an HTTP/JSON face beside the ctl/cli, mostly
  control-plane and statistics: the control verbs over REST (GET a value,
  POST a set — the same `/`-path names, token + RBAC and audit story as
  the wire), the statistics read-only (the registry values, the tables,
  the audit summary); the Prometheus `/metrics` endpoints stay the one
  metrics format.


## Done (the highlights; the git history has the details)

- **the `-file` sibling removal** — `file:` is the one secret spelling
  (the reference landed in the same day's file-reference wave and fully
  subsumed the siblings): the `-file` flags, their `*_FILE` env twins and
  the `-file` config/live keys are gone on all four tools and the eight
  ctl/cli clients; the loader discipline (0600 F12, fail-fast, the
  SIGHUP re-read) is unchanged, the user-facing secret strings say "by
  flag/env, or as `file:<path>`", and the NixOS modules + the compose
  stack render the reference form. The audit wave is docs/SECURITY.md
  rev. 13.
- **the state machinery, family-wide** — the three remaining control
  servers gained `dump_settings`/`apply_dump_settings`, the settings
  state dump (common/settings/dump.py: 0600, integrity-hashed, fail-closed
  restore) with the `dump` node (`dump/path`, `dump/restore-on-start`,
  `request dump`/`request restore`, the shutdown dump), the whole-daemon
  `reload` (the cache's exec dance; the fake's state home was the XDG
  state home then — the config-file wave has since given the fake the
  family's config file), and the **secret lives**: the token pairs
  rotated on the wire at the time (the secrets-startup-only wave has
  since retired the live rotation — every secret knob passes by
  flag/env/config and a restart), the `show` verb refuses the
  secrets (the value renders nowhere), the secret defaults placeholders
  are gone (unset refuses).
- **the hierarchical control grammar** — the live names are `/`-paths
  spelled as words on the wire (`set modbus upstream <value>`, however
  deep; the alias rows answer a second spelling, the canonical renders);
  the config scripts speak the CLI spelling too (the word-index parser —
  values may carry spaces, an unknown name fails fast with the line
  number, the flat dashed names still read); a typed row dispatches
  itself (the conv parses, no `_apply`/`_get` branch); the registries
  dropped the `section` field — the display `group` is the one grouping,
  ungrouped rows render bare with no header, and the cli listings have no
  `[system]`/`[ungrouped]` buckets anymore; the consoles prefix every
  non-value reply line with `% ` (the show reports and tables stay bare
  values); the cache gained the whole-daemon `reload` (the overrides to
  `<config>.reload`, re-exec, re-apply once — the restart-marked knobs
  take their configured values) and the live control-plane rebind/token
  rotation; docs/SECURITY.md rev. 9 walked it (F23 raised and closed: the
  reload state file is 0600 explicitly).
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
  `dashboard-*.py`); every env twin then wore its tool's prefix —
  `MCH_*` (cache), `SCR_*` (scraper), `INV_*` (fake), `DSH_*`
  (dashboard, the generic docker envs retired) — since retired by the
  bare-name wave (the record above); with the one short `*_CTL` form for the
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
  `lib/options.py` per tool on `common/settings/options.py`) +
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
  server takes `--control-ops-token` and scopes its ops sessions to the
  show/clear verbs — the ops shift versus the admin key, both audited
  (`role=ops`/`role=admin` in the COMMAND entries). (The record's
  `--control-ops-token-file` spelling died with the `-file` removal —
  `file:` inside the plain token is the spelling.) The per-tool records name the flag/env forms; the audit wave
  is docs/SECURITY.md rev. 7 (F22 raised and closed with it).
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
- **the systemd unit hardening** — the three NixOS modules sandbox every
  service (`ProtectSystem=strict`, `PrivateDevices`, `ProtectHome`,
  `MemoryDenyWriteExecute`, `CapabilityBoundingSet=`,
  `RestrictAddressFamilies`, `SystemCallFilter`), verified with
  `systemd-analyze security` (a score per unit asserted by
  tests/hardening.nix); nixos/README.md documents the posture.
- **the token-file env honored** `[inverter]` — the help promised
  `CONTROL_TOKEN_FILE` / `METRICS_TOKEN_FILE`, the code never
  read them: both are honored now (the fake and the two clients — flag
  over env, the file over the plain token, both together the
  mutual-exclusion error). (Since retired by the `-file` sibling
  removal: there are no `*_FILE` twins — `file:<path>` inside the plain
  token value is the one spelling.)
- **the man pages** — one roff page per tool in each subproject's `man/`
  (`man/` per subproject; 14 pages: the three cache binaries,
  the three inverter binaries, the three scraper binaries, the dashboard
  server + its two clients, the two profile tools), installed by the Nix
  packages (`share/man/man1/`) and linted with `mandoc -Tlint`.
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
  talks one vocabulary — and the control plane followed (the ctl/cli
  clients, the metrics endpoint skeleton, the resolver pieces, the
  control-server base: one implementation each, the tools subclass or
  pass their spec).
- **the compute-expression wave** — the scraper's compute metrics are
  expression-fed: the spec's one merged `metrics` tree carries entries
  with `expr` (+ the optional `when` gate) or a `profile` binding (the
  field says what feeds it; the old `profile`/`compute` sections refuse),
  a stdlib-safe whitelist evaluator (`lib/expr.py`) compiles them once at
  startup and the poller evaluates per poll (an unavailable input or a
  failed eval keeps the metric absent); the "inputs" declaration and the
  four canonical metrics (the power math's inputs, always bound and
  fetched) ship in the built-in lib/metrics.json (merged into every spec;
  a spec's own section rewords the inputs, a double-bound register
  refuses), `show inputs` / `show inputs metrics` (normal
  registry rows) render the vocabulary and the exported metrics, the five
  classic compute metrics ride as the built-in eval-table defaults, and
  the default spec resolves from a source checkout's `examples/` (the
  packaging re-flattens it) — the double-`Metrics()` wart in the bin (the
  daemon exported the default spec over `--metrics-spec`) fell out of the
  same wave.

Per-tool **Done/history** lives in each subproject's own TODO.md
([cache](../cache/TODO.md), [scraper](../scraper/TODO.md),
[inverter](../inverter/TODO.md), [dashboard](../dashboard/TODO.md)).
