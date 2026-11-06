# Changelog

The suite versions as one: the number lives in `common/version.py`
(`version_string()` appends `-<short git>` in a checkout). Dates are the
tagged commits'. The early tags (before 0.1.0) carried per-tool versions —
the dashboard, the scraper and the cache each numbered their own releases
before the repo restructured into one suite.

# Changelog

## Unreleased

### Added

- **everywhere** — **the env twins drop the tool prefixes**: every
  environment variable is the knob's bare upper-snake name now — `HOST`,
  `PORT`, `LISTEN`, `INTERVAL`, `CTL`, `CONTROL_TOKEN`, `LOG_LEVEL`, ...
  (until now every twin wore its tool's prefix: `MCH_HOST`,
  `SCR_MODBUS_PORT`, `INV_CHAOS`, `DSH_PROM_URL`; the docker-documented
  generic set — the dashboard's `PORT`/`BIND`/`PROM_URL`/... — keeps its
  names unchanged). The different tools sharing a shell can now reach for
  the same name (`HOST` means the cache's device and the scraper's device
  alike) — the accepted trade: the twins are set per deployment surface
  (a systemd unit's `Environment=`, a compose service, a dev shell), never
  in one shared scope; the flags, the config scripts and the control
  grammar are untouched. The registries (`lib/options.json`), the
  resolvers, the ctl/cli clients, the docs, the man pages and the test
  suites follow; `--help` renders the bare `$NAME` forms. (The `HOST`/
  `PORT`/`MODBUS_PORT`/`UNIT` twins are gone again later in this same
  unreleased cycle — the inverter endpoint became the one `--upstream`
  knob and the scraper's unit id `MODBUS_UNIT`.)
- **everywhere** — **the knobs move to declarative data**: the option
  registries are `lib/options.json` files now — one row per knob carrying
  the set-grammar name, the flag, the env twin(s), the section, the
  live-settable name, the secret marker **and the knob's description**
  (until now that help text led a second life in the bins' `parse_args`),
  and the per-tool `lib/options.py` loads the rows onto the common `Option`
  vocabulary and keeps the Python-side wiring: the control-grammar verb
  list, the static.json-wired CLI defaults (the fake parses straight off
  the argv) and the choice vocabularies (log-level; the fake's timezone),
  the `--no-battery` negation included. `--help` and the man pages render
  **from the registry** (`common/options.py` `build_parser()` — the types,
  the choices, the defaults; the CLI-only `--config`/`--dry-run`/`--man`
  stay in the bins) — the description has exactly one home. `show knobs`,
  `show config`, `help config`, the bundled configs, the NixOS modules and
  `scripts/check_options.py` read the same rows as before; the flags in
  `--help`/the man OPTIONS now follow the registry's section grouping (the
  texts, types and defaults are unchanged), and the packages ship the new
  JSON next to the loader.
- **everywhere** — **`show knobs`, the dictionary of all knobs**: every
  control server answers `show knobs` (the `help knobs` alias too) with
  the whole option registry under its section — one row per knob with the
  set-grammar/config name, the argparse flag, the env twin(s), the home
  section, the command that changes it live (or the restart note for the
  startup-only knobs) and a `, secret` marker on the tokens
  (`common/options.py` `knob_dictionary()` — registry data only, no values
  render, so the secrets are named, never shown; `show config` stays the
  values view, `help config` the command mapper). The ctl/cli clients'
  TAB completion and `show?` word-help offer the new `show` argument; the
  RBAC read path covers it as is (`show` is an ops verb).
- **everywhere (the family)** — **a read-only control role**: every
  control server accepts a second token
  (`--control-ops-token`/`--control-ops-token-file`, ini + env twins:
  `MCH_CONTROL_OPS_TOKEN(_FILE)`, `SCR_CONTROL_OPS_TOKEN(_FILE)`,
  `INV_CONTROL_OPS_TOKEN(_FILE)`, `DSH_CONTROL_OPS_TOKEN(_FILE)`)
  beside the admin one, and sessions authenticating with it may run the
  **`show`/`clear` verbs only** — no `set`/`unset`, no `request
  dump`/`restore`/`reload`, no `poll now`, no `restart`, no `shutdown`:
  the ops shift versus the admin key. The gate is the command's head verb
  (`common/wiresec.py`: `ROLE_ADMIN`/`ROLE_OPS`, `role_allows`); the
  session verbs (`help`/`?`/`ping`/`quit`) every role speaks; a denied
  command answers `err forbidden: the ops token runs the show/clear verbs
  only (<verb> needs the admin token)`. Both audited: the COMMAND audit
  entries name the session's role (`role=ops`/`role=admin`, the denials
  included), and each session's frames are mac'd with the key it
  authenticated with — an ops client verifies its own replies against the
  ops token. The peer-cred trusted peers hold the admin role. A role-less
  config is unchanged. Misconfigurations fail fast: an ops token without
  the admin token, or one equal to it, refuses to start. The ops coverage
  landed in the control suites (the fake, the cache — `clear cache`
  honored, steering denied —, the dashboard) and scrape-regtest §6c;
  the NixOS modules grew `controlOpsToken`/`controlOpsTokenFile`
  (the cache's and scraper's ini rendering + the dashboard's ExecStart
  flags, the LoadCredential mounts included). Audit rev. 7 raised and
  closed **F22** (the control plane had no role separation — one token,
  one capability) with this wave.
- **everywhere** — **one knob, one source**: every knob of every tool lives
  once in an option registry (per-tool `lib/options.py`, the shared
  `common/options.py` vocabulary) — the name, the flag, the env twin(s),
  the **section** it files under (device / serving / control plane /
  metrics / audit / limits / persistence / logging), whether it is
  live-settable (the knob -> control-command mapper) and whether it is a
  secret. Built on it: the **configuration file** below, the **`show
  config`** control command (the effective configuration as a set-grammar
  script — the output pipes straight back into a config file or through a
  ctl client; the secrets never render), **`help config`** (the mapper:
  every knob and the command that changes it live, or the restart note for
  the startup-only ones), the sectioned README/config surfaces and
  **`scripts/check_options.py`** — the gate that the four surfaces (the
  flags, the env names, the NixOS module options, the README tables, plus
  the bundled config scripts) agree with the registry.
- **everywhere** — **the configuration format (breaking)**: the ini format
  is gone. The config file is a **set-grammar script** now — every line a
  `set <name> <value>`, every comment a `#` comment, one vocabulary from
  the CLI to the file to the control wire; a config file runs through a
  ctl client unchanged (the clients strip comments/blank lines locally)
  and `show config` regenerates it. A legacy ini file fails with a clean
  pointer to the new form (never silently ignored). The bundled configs
  are the rewritten samples (`modbus_cache.conf`, `scraper.conf`,
  `server.conf`) and the NixOS modules render the set grammar
  (`pkgs.writeText` line lists, dash names).
- **everywhere** — **RBAC on the control plane**: the roles are a policy
  table now (`common/wiresec.py` `ROLE_POLICIES` — admin = the full verb
  set, ops = the read-only shift), and the ops role's verb set is
  configurable per daemon (`--control-ops-verbs show,clear`, ini + env
  twins, validated against the tool's control grammar at start; an empty
  or unknown verb list refuses to start). The session verbs
  (`help`/`?`/`ping`/`quit`) stay open to every role; unknown roles fail
  closed.
- **dashboard** — **its own Prometheus /metrics endpoint** (the last
  family tool without one): `--metrics-server` (off by default, **a
  bearer token is mandatory when on** — the F6 posture), `--metrics-listen`
  (default `127.0.0.1:9452`), the token flags + the client caps like the
  cache's endpoint; serves the self-observability (the uptime, the request
  counters by status class, the proxied-query total, the client gate, the
  version) — not the PV values. Live-settable (`set metrics-server
  on/off`). The cache's and the fake's existing endpoints are unchanged.
- **dashboard** — **the per-phase chain closed**: the phase voltage/current
  selectors land in `config.js` (`phaseVoltages`/`phaseCurrents` — the
  `<prefix>_phase_{a,b,c}_*` metrics), and the page renders a per-phase
  health strip (the volts/amps per phase plus the voltage-unbalance
  percentage, highlighted when it leaves the 2 % band). Optional: omit the
  selectors, lose the strip.
- **scrape** — **the metrics.json sections**: the spec files its metrics
  now — `[profile]` (register-fed), `[compute]` (derived by the poller),
  `[scraper]` (the exporter's own gauges **and the bundled cache-diag
  block**, `scraper_*` named) — and **`--metric-prefix`** (default
  `huawei`, env `SCR_METRIC_PREFIX`) prefixes the profile- and
  compute-fed names; the bundled `scraper_*` names are fixed. The
  renames: `huawei_cache_*` -> `scraper_cache_*`, `huawei_battery` ->
  `scraper_battery`, `huawei_up` -> `scraper_up`,
  `huawei_modbus_errors_total` -> `scraper_modbus_errors_total`,
  `huawei_last_poll_timestamp_seconds` -> `scraper_last_poll_timestamp_seconds`
  (the dashboard's default selectors and the regtest follow; a custom
  legacy flat spec keeps working for the profile/compute metrics). The
  `scraper` section moves to **`lib/metrics.json`** (next to the loader,
  installed with it) and is merged in memory over the configured spec —
  a custom spec carries only the `profile`/`compute` entries it wants,
  its `scraper` entries override the built-ins by name, neither file is
  rewritten.
- **scrape** — **the poll-latency gauges**: `scraper_poll_duration_seconds`
  (+ mean/max) — a slow dongle shows up on /metrics before the freshness
  gap does. The cache has carried its `modbus_cache_poll_duration_*`
  gauges since the metrics wave.
- **scrape** — **the shipped FC4 profile**: `profiles/profiles/demo-fc4.json`
  (lint-clean, the family key order) marks every register as input
  registers (`fc: 4`) — the shipped data the fc4 regtests lacked; the
  fake serves both function codes, the cache caches fc3/fc4 separately,
  the scraper reads per-entry fc.
- **docs** — **the mdBook scaffold** (`docs/book/`): the suite's
  documentation navigable — the SUMMARY includes the READMEs, the audit,
  the TODO and the changelog (`{{#include}}`, rebuilt with `mdbook build
  docs/book`; the only tooling the book adds — the suite stays
  stdlib-only).
- **docs** — the scraper README's **"what /metrics leaks" privacy note**
  (F15): the endpoint exposes production values (generation, consumption,
  battery SoC, the per-phase voltages) — a home-occupancy consideration;
  the token + the localhost bind are the controls.

- **dashboard** — **the control plane** (the family set is complete now):
  the JSON-lines control server on the scraper's pattern — the unix socket
  `/tmp/dashboard-<port>.socket` by default (`--control-port`, `0` = off),
  the token'd TCP with the F5 refusal, the peer-cred trusted-peer shortcut,
  the signed wire. The live settings (`max-clients`, `client-timeout`,
  `max-conn-per-ip`, `log-access`, `log-queries`, `battery`, `log-level` —
  set/unset/show), `show status`/`show connections` (the live HTTP clients
  per peer IP), `show settings`, `inspect`, `request reload` (the SIGHUP
  path — the listen address/port are bound and stay), `shutdown`. Plus
  **`dashboard-ctl`** / **`dashboard-cli`** (the family's one-shot and
  console clients) and the **DSH audit trail**. The HTTP surface grew the
  family's **connection gate** (`--max-clients`, `--client-timeout`,
  `--max-conn-per-ip` — the refusals answer 503; `show connections` reads
  the gate). The NixOS module grew the matching options (`ExecReload`, the
  /run socket directory, the credentials mount included) and joins the
  hardening VM check; the docker image ships the ctl/cli. Also fixed:
  `--control-port 0` (the documented disable value) hit the token refusal —
  on the scraper too.
- **scrape** — **the control plane** (the last family tool without one):
  the JSON-lines control server on the cache's pattern — the unix socket
  `/tmp/modbus-scraper-<listen-port>.socket` by default (`--control-port`,
  `0` = off), the token'd TCP with the **F5 refusal** (a TCP control port
  without a token does not start), the peer-cred trusted-peer shortcut
  (`SO_PEERCRED`, `--control-trust-uids`), the line/cap discipline of the
  family's servers. The live settings (`interval`, `timeout`,
  `max-clients`, `client-timeout`, `max-conn-per-ip`, `log-access`,
  `log-level` — set/unset/show, `show settings` one key=value per line
  with the override markers), `show status`/`show connections` (the live
  HTTP clients via the connection gate's new snapshot), `poll now` (the
  poll loop wakes immediately), `request reload` (the SIGHUP path — the
  token file re-reads, so the bearer token rotates too), the Modbus
  session `restart`, `inspect`, `shutdown`. Plus **`modbus-scraper-ctl`** /
  **`modbus-scraper-cli`** (the family's one-shot and console clients, the token
  handshake + the signed wire included) and the **SCR audit trail**
  (`--audit-log/-max-mb/-files/--no-audit-log`; `scripts/audit_verify.py`
  already walked the scraper's path). The NixOS module grew
  `controlPort`/`controlToken`/`controlTokenFile`/`controlTrustUids` +
  `auditLog`/`auditMaxMb`/`auditFiles` (the credentials mount and the
  /run socket directory included).
- **common** — **the signed control wire** (`common/wiresec.py`): with a
  control token configured, every command and reply on the JSON-lines
  control sockets of the family's four tools carries the **full sha256 HMAC of
  its payload, keyed by the token** — the token auth proves who is
  speaking once, the mac proves it for every frame: a token-holding client
  verifies nothing was injected or altered in flight (the verifiable
  commands item in docs/TODO.md). Over TCP the signed commands are
  mandatory (unsigned/bad-mac frames refused); on the unix sockets the mac
  is verify-if-present, so the peer-cred trusted peers keep speaking
  without the secret; without a token nothing changes. The ctl/cli
  clients (cache, fake, scraper, dashboard — eight of them) sign and
  verify both directions and treat a bad reply mac as a dropped wire; the
  servers' audit COMMAND entries carry the frame's mac (`wire=h…`) — the
  command the server logs cryptographically matches the command the
  client sent.
- **common** — **the man pages are generated** (`common/manpage.py` +
  `scripts/gen_man.py`): every tool and client gained **`--man`** (print
  the roff page to stdout — `modbus-cache --man | man -l -` works in a
  container with no man pages installed), the OPTIONS sections render from
  the tools' argparse parsers (the flags and their help live once —
  `--help` and the man page cannot drift), the prose lives in per-tool
  `lib/man.py`, and the shipped `man/*.1` files (now 12: the scraper's and
  the dashboard's ctl/cli pages are new) are the generator's output,
  regenerated with `python3 scripts/gen_man.py`.
- **fake-inverter** — **`--connect-acl`**: the Modbus connect ACL the
  cache's audit story uses, mirrored (any/`none`/a comma-separated IP/CIDR
  list, env `INV_CONNECT_ACL`, a live setting, `show status` carries
  `connect_acl=`, the rejections logged). **The default stays `any`** —
  the fake's trusted-LAN posture is unchanged; the flag exists so the ACL
  story can be demoed end to end without touching the real cache.
- **nix** — **the systemd unit hardening pass** on all three NixOS
  modules: `PrivateDevices`, `CapabilityBoundingSet = ""` (empty),
  `ProtectKernelModules`/`ProtectKernelLogs`/`ProtectClock`/
  `ProtectHostname`/`ProtectProc=invisible`, `RestrictNamespaces`,
  `RestrictRealtime`, `RestrictSUIDSGID`, `LockPersonality`,
  `MemoryDenyWriteExecute`, `SystemCallArchitectures=native`,
  `SystemCallFilter=@system-service`, `UMask=0077` on top of the existing
  ProtectSystem=strict/PrivateTmp/ProtectHome. The scraper and the cache
  keep `AF_UNIX` in `RestrictAddressFamilies` — the default control target
  is a unix socket, and the filter without it silently broke that surface
  (found in the pass). Verified by the new **`hardening` flake check**
  (tests/hardening.nix): a NixOS VM boots both units, asserts every knob
  from the live unit config and scores each with `systemd-analyze
  security` (the check fails above 2.0 exposure).

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
- **docker** — the demo Prometheus service (`Dockerfile.prometheus`:
  alpine + the prometheus package, unprivileged via su-exec;
  `entrypoint-prometheus.sh`: the token handoff, root only for the copy;
  `prometheus.yml`): scrapes `modbus-scraper:9350` over the internal
  network with `authorization.credentials_file` — the scrape/token story
  ships with the stack now (still not the full demo: the dashboard service
  is pending).
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
- **common, scripts** — the audit trails are **tamper-evident** now (the
  audit finding F10, docs/AUDIT.md): every entry carries a short chained
  hash right after the event name — `<stamp> AUDIT <PREFIX> <EVENT> <12
  hex> [detail]`, `sha256(prev | stamp | prefix | event + detail)`, chained
  **per writer prefix** so the interleaved writers (CACHE/INV/CLI/CTL in one
  file) verify independently and a restarted writer seeds from its own
  trail. The new `scripts/audit_verify.py` walks a trail (default: the
  family's XDG audit logs; `-` reads stdin) and its rotated backups
  oldest-first, recomputes every chain, reports unsigned (pre-chain) lines
  and names the line where an edit, a deletion or a reordering broke it
  (exit 1). The honest boundary is documented with the finding: a
  determined local admin holding the algorithm can rechain — journald
  forwarding stays the strong answer where retention is strict.
- **common** — the shared connection gate (`common/connlimit.py`):
  `ConnGate` counts concurrent connections in total and per peer IP (both
  caps 0 = off, refusals never count) and `GatedHTTPServer` is the HTTP
  shape of it — one implementation behind the family's serving surfaces.
- **cache, inverter** — the metrics endpoints grew the caps
  (`--metrics-max-clients`, default 64, an immediate `503 # rate limited`
  past it; `--metrics-client-timeout`, default 5 s, `0` = the built-in
  cap; `--metrics-max-conn-per-ip`, default 0 = no per-IP limit) and both
  Modbus listeners grew **`--max-conn-per-ip`** (default 0 = no per-IP
  limit; a live setting next to `max-clients`/`client-timeout`).
- **fake-inverter** — the control server catches up with the cache's:
  `show status` carries a `metrics=` field and `inspect` an endpoint line
  (the shared `describe_metrics` one-liner, `off` when the endpoint is
  off — the fake maintained the string and reported it nowhere), the live
  `set metrics-server on` holds the documented posture (a token-less
  listen beyond loopback logs the same warning the startup prints), an
  unbindable control target logs a one-liner and keeps the fake running
  instead of dying in the serve thread, the legacy `.`-terminator strip
  is gone (the JSON frames never carried one) and the unix control socket
  grew **`--control-socket-group`** (the cache's F8 opt-in: `chmod 0660`
  instead of the default `0600`, a local group may speak to the control).
- **scrape** — **`--max-conn-per-ip`** (default 0 = no per-IP limit):
  concurrent connections from one peer IP get the same immediate 503 as
  the total `--max-clients` cap; applied live on SIGHUP like the rest.
- **tests** — the new `tests/audit-chain.py` asserts the hash chain and
  the verifier end-to-end (interleaved prefixes, the tamper matrix, the
  restart seeding, the rotation span, a live INV trail).
- **docs** — the audit reissued as **rev. 4** (docs/AUDIT.md): the whole
  tree audited directory by directory (cache, common, docker, inverter,
  profiles, scrape, scripts — the dashboard deferred to the next audit
  wave), the scope tells the four waves, the closed table carries the
  per-revision bookkeeping (rev. 2: F2–F8; rev. 3: F7/F9/F12; rev. 4:
  F10/F11/F13/F18), the evidence splits accordingly and the re-audit
  note records the focused review of the new shared surfaces. The walk
  found **one new LOW finding: F19** — the release orchestrator cuts the
  GitHub release locally before the tag-triggered CI gate reports; the
  fix is a defaults flip (the workflow cuts the release, the local gate
  runs the full suite, sign the tags).

### Changed

- **everywhere** — **the sections render as their registry names**: the
  console `?`/TAB listings group the settings under the registry's own
  section heads — `[device]`, `[serving]`, `[control]`, `[metrics]`,
  `[limits]`, `[audit]`, `[persistence]`, `[logging]` (until now one flat
  `[settings]` group; `[values]`/`[system]` unchanged) — instead of the
  translated titles; the knob table (options.md) renders the same raw
  section keys in its function column. `Setting` carries its section and
  `common/options.py` `section_groups()` does the grouping; the long
  titles stay where they were already at home (`show config`, `show
  knobs`, `help config`).

- **everywhere** — **the control grammar's vocabulary folds into the option
  registry (one place to have all knobs)**: `lib/settings.py` is gone —
  its `SETTINGS` (the live settings' short descriptions, the completable
  value words, the value-shape hints and the per-value notes) now rides the
  same `lib/options.json` rows as the flags/envs/sections
  (`setting-help`/`values`/`hint`/`value-help` beside `live`), and
  `lib/options.py` derives the wire vocabulary from them
  (`SETTINGS`/`SETTING_BY_NAME`/`SETTING_NAMES` +
  `describe_setting`/`describe_value`, the shared
  `common/options.py` `Setting`/`settings_of()`/`make_describe()`); the
  ctl/cli clients and the control servers import the same names from
  `lib/options.py` now. The fake's **control-only settings** (the pins and
  the machines — `pv`, `load`, `batt`, `grid`, `soc`, `mppt`, `cloud`,
  `scenario`, `battery-state`, `grid-outage`) ride the registry as flagless
  rows (a live name, no flag/env) — until now they existed only in the
  hand-listed settings module; `show knobs` renders them with a
  `(control-only)` marker. The wire grammar, the completions and the word
  help are unchanged (the fake's device section lists the pins first, so
  its help output keeps its shape); check_options.py grows the drift gate
  (the live names unique, every live row carries its description, the
  control-only rows flag/env/secret-free) and options.md renders the
  control-only rows (89 knobs now).
- **scraper** — **breaking: the subproject directory is `scraper/`** (was
  `scrape/`): the flake's package/module paths, the docker build context
  and the image layout, the mdBook include, the SBOM, the cross-README
  links and the man pages' rendered paths follow; the test-suite
  filenames keep their historical `tests/scrape-*.py` names and the
  binary stays `modbus-scraper`.
- **cache, scraper** — **breaking: the inverter endpoint is one
  `--upstream HOST:PORT` knob** (the shared `common/config.py`
  `parse_upstream()`): `--host` and `--port` retire on the cache,
  `--host`/`--modbus-port` on the scraper, flags, env twins and config
  keys alike — `HOST`/`PORT`/`MODBUS_PORT` give way to `UPSTREAM`
  (a config `set upstream 127.0.0.1:5502`, the NixOS option
  `upstream`, the docker CMDs), and **`:PORT` = 127.0.0.1:PORT** (the
  loopback shorthand; `[v6]:PORT` parses like `--listen`). The resolved
  config keeps its derived `host`/`port` keys — `show status`, the start
  log and the audit trails report the same fields as before. Anything
  scripting the retired flags/envs must follow.
- **scraper** — **breaking: `--unit` is `--modbus-unit`** (env `UNIT` →
  `MODBUS_UNIT`, config `set modbus-unit`, the NixOS option `modbusUnit`):
  the Modbus unit id wears the modbus- prefix its siblings on the flag
  line already carry (`--modbus-port`'s place is taken by `--upstream`,
  so the family stays grep-able). Anything scripting `--unit` must
  follow.
- **everywhere** — **breaking: every environment twin carries the tool's
  prefix now** — `MCH_*` (the cache), `SCR_*` (the scraper), `INV_*` (the
  fake inverter), `DSH_*` (the dashboard) — and each control-port answers
  to the one short form (`MCH_CTL`/`SCR_CTL`/`INV_CTL`/`DSH_CTL`, the
  daemons and the ctl/cli clients agree; no more long/short duplicates).
  The dashboard retires the generic docker envs (`PORT`, `BIND`, `PROM_URL`,
  `PROM_PREFIX`, `STATIC_DIR`, `CONFIG_JS`, `BATTERY`) for
  `DSH_PORT`/`DSH_BIND`/`DSH_PROM_URL`/`DSH_PROM_PREFIX`/
  `DSH_STATIC_DIR`/`DSH_CONFIG_JS`/`DSH_BATTERY` — the compose stack, the
  docker docs and the compose's Prometheus wiring follow. Anything
  scripting the old names must follow.
  (Reversed later in this same unreleased cycle — the prefix retirement
  above ships the twins as the bare names; this entry is kept for the
  wave's own story.)
- **cache** — **retagged: "Modbus TCP caching proxy for single-client
  devices"** (the man page's NAME has said so; the sources follow): the
  module docstring and the `--help`/man DESCRIPTION lead with the
  device-first story (any single-client Modbus TCP device — an inverter or
  its SDongle/EMMA radio — the bundled sun2000 profile stays the shipped
  example), not the Huawei-specific one.
- **everywhere** — the bins are renamed to match their man pages (the
  family's dash names): `cache/bin/modbus_cache.py` → **`modbus-cache.py`**,
  the `*_ctl.py`/`*_cli.py` clients likewise (`modbus-cache-ctl.py`,
  `modbus-cache-cli.py`, `modbus-scraper*.py`, `modbus-fake-*.py`,
  `dashboard-*.py`) — the man page, the bin and the installed entrypoint
  share one name now; the nix packages, the docker images and the docs
  follow.
- **scrape** — **breaking: the register-map config is gone** —
  `--pv-register`/`--grid-register`/`--battery-register`/
  `--battery-soc-register`/`--scale`/`--grid-scale` (flags, envs, config
  keys, NixOS options) existed because the spec predates the device
  profile; the device profile is the register map's single source now
  (addresses, types, gains, function codes — its per-entry `scale` is the
  decode divisor, validated finite > 0 at load). The live control surface
  gained **`set profile <file-or-name>`** (`default` = the bundled sun2000
  profile, `unset` restores the configured one): the new register map
  loads, the metric sources rebuild and a profile without the registers
  the power math needs rolls back with a clean error.
- **everywhere** — the log levels are a static constant: every tool's
  `lib/static.json` carries **`log_levels`** (`DEBUG`/`INFO`/`WARNING`/
  `ERROR`) and every consumer reads it from there (the argparse choices,
  the config validation, the live `set log-level` completion and check)
  — nothing hardcodes the ladder anymore.
- **dashboard** — the bin+lib layout like the rest of the family: `src/`
  splits into `bin/` (`server.py` → **`bin/dashboard.py`**) and `lib/`
  (the statics loader), with `config.js`, `server.ini` and `man/` promoted
  to the subproject root (the dev checkout resolves them from the script's
  parent; the installed package stays flattened); `package.nix` builds from
  the subproject root now. No behavior change beyond the paths.
- **cache** — **breaking**: the state dump splits by content — by default
  it dumps **settings only**; **`request dump with-cache`** includes the
  cached words, and the new **`--dump-with-cache`** flag flips the plain
  `request dump`, the `--dump-interval` loop **and the shutdown dump** to
  the full shape (the default off = settings only — the words are
  production data, keep them out of the file unless the
  write-behind/restart story needs them). The restore takes either shape
  and loads whatever the file carries. Pair `--restore-on-start` with
  `--dump-with-cache` for the words to survive the restart.
- **cache, inverter** — **breaking**: the metrics endpoint renames — the
  master switch is **`--metrics-server`** (off by default, **live-settable**
  `set metrics-server on/off`), and **`--metrics-port`** becomes
  **`--metrics-listen HOST:PORT`** (default `127.0.0.1:9252` on the cache,
  `127.0.0.1:9452` on the fake) — `0.0.0.0:PORT` serves every interface
  (the cache's token is mandatory regardless; the fake warns when bound
  beyond loopback without one). Anything scripting `--metrics-port N`
  follows.
- **scrape** — the metrics surface is the tool by design (always on); the
  connection limits are `--max-clients` (64), `--client-timeout` (300 s)
  and `--max-conn-per-ip` (0 = no per-IP limit) — no master switch.
- **cache** — **breaking**: the write path defaults fully closed —
  `write-acl` and `write-registers` now default to **`none`** (was `any`):
  enabling `--allow-write` alone refuses every write until the operator
  opens the write ACL and the register allow-list (in the config or live
  with `set`). Both settings (and `connect-acl`, whose default stays
  `any`) grew the **`none`** mode — restrict all: `write-acl none` refuses
  every client's writes, `write-registers none` refuses every write
  regardless of the client, `connect-acl none` rejects every connection at
  accept.
- **scrape** — the default poll interval is **10 s** (was 5) — matching
  the cache's poll default, the demo Prometheus's scrape interval and the
  dashboard's `scrapeSec`; the cache already polled at 10 s.
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

### Fixed

- **scraper** — the `show status`/`inspect` uptime mixed the clocks (wall
  `time.time()` minus a monotonic start): a running scraper reported
  `uptime 20763.07d` — the epoch rendered in days. Both lines read
  `time.monotonic() - started` now (the cache/fake/dashboard shape); the
  `last_poll ... ago` fields keep the wall clock on purpose (the epoch
  stamp feeds the gauge).

- **the family** — the scraper renames (`huawei_cache_*` ->
  `scraper_cache_*`, `huawei_up` -> `scraper_up`, `huawei_battery` ->
  `scraper_battery` — the metrics wave) had left stale mentions behind:
  the cache's `/metrics` docstring and README rows, the docker README, the
  inverter README (the diag-block note, the chaos chapter), the scrape
  README's metrics table (now split into the prefixed profile/compute rows
  and the fixed `scraper_*` rows — the poll-duration gauges included) and
  its ini-era `[scraper] section` config wording, and the dashboard's
  shipped `config.js` default `batteryFlag` selector (the UI's battery
  toggle asked for the retired `huawei_battery` gauge). The man pages are
  rebuilt from the fixed prose.
- **dashboard** — the `--config` help (and the `default_config_path`
  docstring) still said **`server.ini`** — the ini format is gone and the
  sample is `server.conf`: the help names the set grammar and the right
  file now (the man page follows the parser).
- **the family** — the help promised the token-file env vars, the client
  code never read them (the audit's F20, docs/AUDIT.md rev. 6): the ctl/cli
  clients honor their `--control-token-file` env form now —
  **`MCH_CONTROL_TOKEN_FILE`** (`modbus-cache-ctl`, `modbus-cache-cli`),
  **`SCR_CONTROL_TOKEN_FILE`** (`modbus-scraper-ctl`, `modbus-scraper-cli`),
  **`DSH_CONTROL_TOKEN_FILE`** (`dashboard-ctl`, `dashboard-cli`) and
  **`INV_CONTROL_TOKEN_FILE`** (`modbus-fake-ctl`, `modbus-fake-cli`) — and the fake
  itself honors `INV_CONTROL_TOKEN_FILE` /
  **`INV_METRICS_TOKEN_FILE`** (the env form of `--control-token-file` /
  `--metrics-token-file`; the other daemons resolved the env from the
  start). One resolution shape everywhere: the flag wins over the env, the
  file over the plain token, both together the usual mutual-exclusion
  error, the F12 0600 gate on every path.
- **inverter** — the fake's daemon took no env for its token files (its
  config had no resolution layer): covered by the family fix above.
- **scripts** — the release gate's full suite list had drifted:
  `--tests full` ran eight of the ten suites (the inverter regtest and the
  audit-chain suite were missing) — the gate lists all ten now.
- **dashboard** — the `--audit-log` help said SCR (the scraper's trail
  prefix); the trail is DSH.

### Docs

- **everywhere** — **options.md, the knob comparison table**: every knob of
  the four daemons in one table — the name, the function it files under
  (device/serving/control plane/own /metrics/limits/audit trail/
  persistence/logging), the registry description and a ✓ mark per tool
  (**bold** = common to all four, `live`/`secret` marked) — generated from
  the per-tool `lib/options.json` registries by the new
  `scripts/gen_options.py` (edit the registries, re-run, never the
  markdown). The table's first render flushed two registry helps: the
  cache's `--restore-on-start` still cited the dead ini key
  (`ini restore_on_start`) and the dashboard's `--no-audit-log` said
  "SCR audit trail" — both reworded to the family's default style (the
  `--help`/man pages follow the registry).
- this wave's docs: the READMEs updated family-wide (the config grammar —
  the ini is gone —, `show config`/`help config`, the RBAC verbs flag, the
  dashboard's metrics/audit rows, the scrape privacy note), the man pages
  regenerated (mandoc -Tlint clean), the TODOs follow, the mdBook scaffold
  (`docs/book/`); **docs/AUDIT.md rev. 8** records the wave (no new
  findings). **docs/AUDIT.md rev. 6** — the audit covers the whole pv-suite (the
  dashboard's deferral closed): the scraper's and the dashboard's control
  planes walked (no new findings beyond F20), the dashboard's HTTP surface
  audited for the first time — **F21** raised (no auth on page/proxy, the
  `0.0.0.0` default bind; the family TODO's auth-story item is the same
  work) — the assets/surfaces inventory and the NIS2/DORA mapping extended
  to the dashboard, and the release-gate drift recorded (fixed above).

### Security

- **scripts** — the audit finding F19 (docs/AUDIT.md, rev. 5) closed: the
  release no longer lands before the CI gate reports. The GitHub release
  is the tag-triggered workflow's job (`needs: [test, build]` — the suites
  + the nix build — then the cut from the changelog section); the
  orchestrator's local cut becomes the explicit opt-in (**`--release`**,
  printed with the bypass reminder; `--no-release` is gone). The local
  gate defaults to **`--tests full`** (was `quick`), and the tag is
  **signed** (`git tag -s`) whenever a signing key exists — the unsigned
  annotated tag is the fallback, with the reason printed. Flight-tested on
  the way: a fresh bump no longer dies on `git grep`'s no-matches exit
  code, and a dry-run prints the plan without pretending the suites ran.
- **cache** — the audit finding F18 (docs/AUDIT.md) closed: the state
  dump is owned trust at rest — created **`0600` explicitly** (never the
  umask) and carrying a **sha256 integrity hash** of its canonical
  content; a restore **fails closed**: an edited, truncated or unsigned
  dump refuses with a one-liner, and a group/world-writable dump refuses
  outright (whoever can write the dump holds config trust — own the file
  like the ini, `chmod 0600`). The hash catches corruption and casual
  tampering, not a local admin who rechashes (the same boundary as the
  audit trail's chains). The regtest asserts the mode, the hash and all
  three refusals.
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
- **docker** — the audit finding F7 (docs/AUDIT.md) closed: the compose
  stack publishes nothing on the host — the services talk over one
  `internal: true` network (`pv-modbus`, no outbound route), so the Modbus
  listeners, the exporter's `/metrics` and the Prometheus UI are reachable
  only from inside the network (`docker compose exec`, or a collector
  container attached to the network by name); the plain `docker run`
  examples bind their published ports to `127.0.0.1` now. The demo
  exporter serves with a bearer token — the entrypoint generates
  `/config/metrics.token` into the volume on the first seed (0600; bundled
  `*.token` defaults are placeholders, never copied) and Prometheus scrapes
  with the same value.
- **cache, inverter, scrape** — the audit findings F9 and F12
  (docs/AUDIT.md) closed: a token passed as `--control-token` /
  `--metrics-token` / `--auth-token` lands in `ps` / `/proc/*/cmdline` —
  the READMEs and the token-flag man pages now say prefer the `-file`
  variants (LoadCredential) or the env vars, the flag form is for quick
  tests (F9). Token files must be owner-only (`0600`): a group- or
  world-accessible token file refuses to start with a one-line
  `chmod 0600` error — the shared loader (`check_token_file_mode` in
  `common/config.py`) covers the cache, the fake and the ctl/cli clients,
  the scraper's SIGHUP-reread loader re-checks on every reload (F12); the
  docker entrypoint seeds generated token files 0600. The regtests assert
  the refusal.
- **inverter** — the audit finding F11 (docs/AUDIT.md) closed as
  recommended — capped and documented, not redesigned: the fake's Modbus
  listener grew **`--max-clients`** (refuse past the limit at accept,
  default 64, `0` = no limit) and **`--client-timeout`** (shed silent
  clients, default 300 s, `0` = never) mirroring the cache — both tunable
  live (`set max-clients` / `set client-timeout`, `unset` restores the
  configured value) and watched via the new **`show connections`** control
  command (peer, connection age, requests served; `clients=` joined the
  `show status` fields and `inspect` carries the modbus row). A declared
  read count past the 125-register cap (`0`, `0xFFFF`, a span past the
  16-bit space) now answers exception 03 — the cache's gate — instead of
  assembling an oversized reply. The README's Security section and the man
  page's SECURITY block document the posture: the fake is a development
  tool, not security-first design — run it on a trusted, LAN-isolated
  network. Verified by the new `tests/inverter-regtest.py`. The two suites
  that predate the earlier fixes caught up in the same sweep: the
  cache-control fuzzer authenticates now (its token-less TCP control port
  predates the F5 startup refusal) and the cache stress proxy opens its
  write path explicitly (`--write-acl any --write-registers any` — the
  write defaults are none).
- **scrape** — the audit finding F13 (docs/AUDIT.md) closed: a non-loopback
  `/metrics` listen without `--auth-token`/`--auth-token-file` **refuses to
  start** with a one-liner (`refusing to expose /metrics beyond loopback
  without a token`) — the SIGHUP reload runs the same check and keeps the
  previous settings; the loopback default needs no token (localhost dev
  stays friction-free) and the docker demo has carried the token since F7.
  The README documents the refusal and the Prometheus scrape job with
  `authorization.credentials_file`. (The cache's metrics endpoint already
  refused to start without a token and binds loopback only — F6; the
  fake's is loopback-only by construction with the optional token.)

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
- **scrape/** — restructured to the family layout: `bin/modbus-scraper.py`,
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
