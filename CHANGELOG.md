# Changelog

The suite versions as one: the number lives in `common/version.py`
(`version_string()` appends `-<short git>` in a checkout). Dates are the
tagged commits'. The early tags (before 0.1.0) carried per-tool versions —
the dashboard, the scraper and the cache each numbered their own releases
before the repo restructured into one suite.

This file keeps **Unreleased and the current release** only — the release
history (0.4.0 and older) lives in [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Unreleased
### Added

- **everywhere** — **the serve-address word is family-wide**: `show system
  listen` prints the address the daemon serves on, on all four. The cache's
  `system/listen` is the canon; the scraper's listen knob re-spells to it
  (`metrics/listen` stays as the alias — the wire, the config grammar and
  the state files accept both spellings, the canonical one renders), with
  the restart fold that was missing (a `set` + `request reload` now really
  rebinds). The fake inverter and the dashboard trade their custom serve
  knobs for the same knob — the fake's `--host`/`--port` and the
  dashboard's `--bind`/`--port` retire for `--listen HOST:PORT`
  (`$LISTEN`, live `system/listen`, hidden, restart-marked — the argv
  defaults keep their addresses: `127.0.0.1:5502` and `127.0.0.1:8080`);
  the dashboard's `set system listen` refuses a pending move beyond
  loopback while the page serves tokenless (the F21 shape at set time).
  The NixOS module options are `listenHost`/`listenPort` rendering one
  `--listen` (the cache's shape), the docker CMDs and the compose
  `LISTEN` env follow, and the MANUALs, the man pages, OPTIONS.md and the
  drift census ride along.

- **everywhere** — **the `dump-interval` knob is family-wide** (the cache
  was the only holder): the scraper, the fake inverter and the dashboard
  gain the cache's `dump-interval` — `--dump-interval`/`$DUMP_INTERVAL`,
  live as `set dump-interval <s|off>` — and the state dump rewrites
  itself on a timer: the dumper loop parks on the control base while the
  interval is off and a live set wakes it without a restart (the cache's
  golden shape, shared now as `run_dump_interval`); a
  set/show/describe without a dump path answers the family's
  `dump-interval needs a dump path (set dump/path or --dump-path)`, the
  start resolution refuses an interval without a dump path, and the
  SIGHUP/`request reload-config` path re-reads the configured interval
  (the scraper and the dashboard; the fake's SIGHUP layer does not touch
  the dump family — the dump-path parity). The dump-path rows' help
  spells the timer; the MANUALs, the man pages, OPTIONS.md and the
  modules' `dumpInterval` option follow.

- **docker** — **the stacks split by wiring, and both ship
  authenticated**: the new `docker/prod/compose.yaml` is the production
  shape — the same three service images the demo runs (cache + scraper +
  dashboard), no fake, **no in-stack collector** (your Prometheus is
  external and pulls the exporter's `/metrics` — the loopback `9350`
  publish for a host-level collector, or attach it to the network; the
  dashboard's `PROM_URL` points its `/prom` proxy at it), a
  **non-internal** network (`pv-suite`,
  the cache dials the device on the LAN), the cache's `env/cache.env`
  **required** (UPSTREAM is the operator's decision — the image default
  only ever resolves in the demo), the device's own auth
  (`AUTH_UPSTREAM`/`AUTH_UPSTREAM_KEY`, suite or the cache-only
  waveshare) the env file's, and two published ports (the dashboard's
  loopback 8080 + the exporter's loopback 9350). The Modbus hops ship
  authenticated in BOTH stacks now:
  one shared suite key (`/config/modbus-auth.token`, generated into the
  volume on the first seed by whichever Modbus image seeds first — the
  same mechanism as the tokens, a `*.token` placeholder in the fake's,
  cache's and scraper's `config-defaults/`) proven by the PVA1/HMAC
  handshake on every connect — the fake demands it (server), the cache
  proves it upstream and demands it from its own clients, the scraper
  proves it; the `environment:` blocks pin scheme + `file:` reference
  (environment beats env_file — opening a hop is a compose edit, the F7
   shape). The collector (`Dockerfile.prometheus`,
   `entrypoint-prometheus.sh`, `prometheus.yml`) serves the demo stack
   from `docker/` — the reference wiring a prod collector mirrors; the
   demo wiring lives in `docker/demo/` (`compose.yaml` —
  the build contexts re-point one level out — plus its README with the
  demo blockquote + topology); the four tool Dockerfiles and the env
  examples stay at `docker/`, the two entrypoints move to
  `docker/entrypoints/` (the five Dockerfiles' COPY paths + build
  comments carry the prefix) — demo and
  production run identical images, the split is the wiring. The
  READMEs follow: `docker/README.md` turns production-facing (the
  secrets-story section joins), `docker/demo/README.md` carries the demo
  blockquote + the topology, `docker/prod/README.md` the production
  shape (its own topology: the device outside the network, the cache's
  client the one route out).

### Changed

- **everywhere** — **the secret knobs are startup-only, family wide**:
  every secret row (the control tokens, the ops tokens, the metrics
  tokens, the Modbus auth keys, the dashboard's page token, `dump/key`)
  takes the dump-key shape — `live` + `restart` + `hidden` + `secret` —
  and the wire **refuses `set`/`unset`** on it
  (`restart required (startup-only knob)`) before any dispatch: a secret
  never rides the reload state, so it has no pending form — it passes by
  flag/env/config (`file:<path>` included) and a restart, where the
  resolution and the floors (min-16, the scheme-aware key floor,
  ops ≠ admin, the F13 token-mandatory binds) already check it. The live
  rotation branches and their `<set>`/`<set>`-render backs are deleted;
  `help config`/`show knobs`/OPTIONS.md render the secrets
  `startup-only — pass it by flag/env/config (set/unset refuse)` instead
  of a set recipe; the scraper's SIGHUP/`request reload-config` path
  still re-reads the `file:` references, and the dump/reload state files
  are unchanged (the SECRET_REMOVED placeholder can no longer occur —
  no secret can be overridden). The regtests respawn daemons with the
  desired tokens instead of rotating them live.

- **everywhere** — **the /metrics listener is ONE stack, family wide**:
  the fake's and dashboard's own `/metrics` take the cache's
  **`metrics/acl`** (`--metrics-acl`, env `METRICS_ACL`, live `set
  metrics acl` / `unset metrics acl`, the table show `show metrics acl
  table`, the `set metrics acl table` pointer) — the same value grammar
  (`any` the default, `none`, the comma-separated whitelist,
  `file:<path>` the standalone ip-prefix acl file), checked at **accept,
  ahead of the caps**: a client off the ACL is closed without a reply
  and logged `connection rejected: … not on the metrics ACL`; a bad file
  errs with the old gate standing, a group/world-readable acl file warns
  (the log, the audit trail's `ACL-FILE` event, the `set` reply's
  suffix). `common/config.py` gains `resolve_metrics_acl` (the one
  `(gate, warn)` resolver, lifted from the scraper). The shipped example
  + its JSON Schema copy to all four tools:
  `inverter/examples/` + `inverter/schema/` and `dashboard/schema/` are
  new dirs, `dashboard/examples/acl-ip-prefix.json` joins its existing
  examples; the cache's `package.nix` now installs its three
  `schema/*.schema.json` files too (the scraper's were the only ones
  shipped).

### Changed

- **scraper** — **the legacy flat-spec wire-name fallback retires from
  the exposition**: the poll gauges always render their fixed
  `scraper_*` names (the built-in `scraper` section of
  `lib/metrics.json` merges into every spec, so the `huawei_up`-style
  fallback branches in `lib/server.py` were unreachable dead code); the
  flat-spec acceptance in the loader itself stays (keys verbatim).

- **everywhere** — **the ip-prefix acl example + schema are one shared
  pair at the repo root** (`examples/acl-ip-prefix.json` +
  `schema/acl-ip-prefix.schema.json`): the four per-tool copies die (the
  fake's `examples/`/`schema/` dirs held only the pair and empty out,
  the dashboard's `schema/` with them), the four `package.nix` installs
  re-point (`${../examples}`, `${../schema}`) with the packaged
  `share/<tool>/` layout unchanged, `scripts/lint_acl.py`'s bare run
  globs the root `examples/` too, the regtests' `file:` rounds read
  the root file, and the two dirs grow READMEs.

- **everywhere** — **the `--battery` knob retires, battery support is
  always on**: the fake's `--battery`/`--no-battery` pair (and its
  `BATTERY` env twin — the flag and the SIGHUP reload block), the
  scraper's `--battery` (`BATTERY`, live `modbus/battery`, the
  `scraper_battery` gauge and the reserved `battery` compute input — the
  reserved inputs are four now: `pv`, `grid`, `batt`, `soc`) and the
  dashboard's `--battery` (`BATTERY`, live `battery`) are gone; the
  battery registers/metrics/panels simply always serve (a device profile
  without the battery registers keeps the battery metrics absent), the
  fake's battery state machine runs unconditionally and the served
  `config.js` always carries the battery panels. `--battery-kwh` (the
  pack size) stays.

- **everywhere** — **the /metrics default binds renumber from 9350 up,
  one per tool**: the scraper keeps `9350` (its own listen IS the
  /metrics), the cache `9252` → **`9351`**, the fake `9452` → **`9352`**,
  the dashboard `9452` → **`9353`** — the fake and the dashboard SHARED
  `9452` until now (a co-located stack would have collided). The fake's
  and dashboard's metrics toggle live name re-spells to the family form
  **`metrics/enable`** (the cache's spelling; the knob name
  `metrics-server`, the config files and the flag stay flat — the wire
  spells `set metrics enable on/off`).

- **everywhere** — **the control listener is ONE implementation, family
  wide** (the cache's golden master lifted into `common/control.py`):
  `control/port` rebinds the listener live on all four tools (bind-first,
  the failed bind rolls back, the old loop retires by identity, the
  connected sessions keep serving, `off` retires while the sessions keep
  serving, `unset` restores the configured target); the F5 refusal (a
  tokenless TCP control bind) now also guards the **live** rebind, not
  just the start — the fake opts out by posture (`TOKENLESS_TCP =
  'allow'`, F11: a tokenless TCP rebind succeeds there, the regtest pins
  the inverse proof). The fake's `control-port`, `control-ops-verbs`,
  `control-trust-uids`, `control-socket-group` go live (they were
  startup-only); the **dashboard** gains the whole live control family
  (`control/port`, `control/ops/verbs`, `control/trust-uids`) and a NEW
  **`--control-socket-group`**/`CONTROL_SOCKET_GROUP` knob (0660 instead
  of the plain 0600 — the cache's and scraper's alone until now; NixOS
  `controlSocketGroup`). The ops-verbs live name re-spells to the family
  form **`control/ops/verbs`** (the cache's `control/ops-verbs` included;
  the knob name, the config files and the flag stay flat) — the wire
  spells `set control ops verbs <list>`. The four per-tool
  `resolve_control_target`/`parse_control_target` wrappers unify into
  `common/config.py` (one signature: `listen_port` + the socket
  template); the dump/reload state carries the listener on every tool.
  The docker note: a live `set control port off` on a container daemon
  fails the image's HEALTHCHECK by design (it probes the control socket;
  `CTL=0` fails the check).

- **cache** — **`metrics/acl`** (`--metrics-acl`, env `METRICS_ACL`,
  config `metrics_acl`, NixOS `metricsAcl`, live `set metrics acl` /
  `unset metrics acl`): the scraper's metrics/acl wave migrates to the
  cache's own /metrics endpoint — the same value grammar (`any` the
  default, `none`, the comma-separated whitelist, `file:<path>` the
  standalone ip-prefix acl file), checked at **accept** beside the
  connection caps: a client off the ACL is closed without a reply and
  logged `connection rejected: … not on the metrics ACL`. The gate
  re-resolves on every `set`/`unset` and on SIGHUP (a bad file keeps the
  old gate standing; an inline set clears a standing file warning), the
  group/world-readable file warns (the log, the audit trail's `ACL-FILE`
  event, the `set` reply's suffix), **`show metrics acl table`** renders
  the gate as its chain and `set metrics acl table` answers the pointer
  to the report. The accept hooks ride the common MetricsServer now
  (`acl_allows`/`acl_refused` delegate to the instance — the defaults
  admit every peer and close silently, so the dashboard's endpoint is
  untouched).

- **scraper** — **`metrics/acl`** (`--metrics-acl`, env `METRICS_ACL`,
  config `metrics_acl`, NixOS `metricsAcl`/`metricsAclFile`, live `set
  metrics acl` / `unset metrics acl`): one IP-kind gate on the /metrics
  listener doing what the cache's `acl/connect` does on the Modbus
  listener — the value grammar (`any` the default, `none`,
  a comma-separated `IP,IP/prefix, ...` whitelist, `file:<path>` the
  standalone ip-prefix acl file, the shipped
`examples/acl-ip-prefix.json` shape). The check runs at **accept**,
ahead of the connection caps (the ACL first, then the caps): a client
off the ACL is closed without a reply — nothing was parsed to answer — and
  logged `connection rejected: … not on the metrics ACL`. The acl file
  re-resolves on every `set`/`unset` and on SIGHUP (a bad file keeps the
  old gate standing), a group/world-readable file warns (the log, the
  audit trail's `ACL-FILE` event, the `set` reply's suffix), and the
  **`show metrics acl table`** report (show-only) renders the gate as its
  chain — the inline forms as the three fixed chains (`allow 0.0.0.0/0` /
  `deny 0.0.0.0/0` / the whitelist spelled out), a file gate as its own
  rules behind the `% ` desc header with the aligned `# ` comments; `set
  metrics acl table` answers the pointer to the report. The gate
  machinery (`IPGate`, the gate-object validator, the table renderer) is
  one implementation for the family now — `common/config.py` — and the
  ip-prefix example + its JSON Schema ship in the scraper's tree
  (`scraper/examples/acl-ip-prefix.json`,
  `scraper/schema/acl-ip-prefix.schema.json`).

- **scripts** — **`scripts/validate_json.py`**: a stdlib-only JSON Schema
  validator for the shipped spec files (`scraper/schema/`, `cache/schema/`)
  — the draft-2020-12 keyword set the schemas speak (`type`/`enum`/`const`,
  the object/array/string/number bounds, `pattern`/`propertyNames`,
  `allOf`/`anyOf`/`oneOf`/`not`, local `#/...` `$ref` into `$defs`),
  `SCHEMA [FILE|- ...]` argv with `-` the stdin, one error line per
  distinct cause at its JSON pointer (the `oneOf` candidates that `$ref`
  one subschema dedupe to one line), exit 0 every document validates / 1 a
  document failed or would not parse / 2 bad usage or an unusable schema.

- **docs** — **`docs/ACL.md`**: the family-wide ACL map — the one
  rule-chain semantics (the typed gate object, the two matcher kinds, the
  last matching rule deciding, the default deny any), the standalone acl
  file and its tools, the per-tool support (the cache's full story — the
  connect/write IP ACLs and the register gate, the fake's connect-ACL
  mirror in the system grammar, the scraper and the dashboard's deliberate
  no-ACL posture), the system forms spelled as the chains they implement,
  and the boundary to the neighbouring gates that are not ACLs (the suite
  auth, the control-plane RBAC, the connection caps). The book gains the
  `acl.md` page; the audit re-runs at **rev. 18** (the ACL wave walked:
  the posture rows updated — the cache's IP-gated Modbus plane, the
  fake's connect-ACL'd mirror — the F11 closure annotated, the
  control-plane ACL recorded as decided-against-while-loopback), and the
  READMEs/`MODBUS.md` carry the `file:` spellings and the table shows
  (the fake's man SECURITY block drops its stale "no ACL" claim).

- **cache** — the connect and write ACLs read the **ip-prefix acl file**:
  `--connect-acl file:<path>` / `--write-acl file:<path>` (env, config
  and the live `set` the same) load the standalone gate whose root is
  `{"type": "ip-prefix", "rules": [{"type": "allow"|"deny", "prefix":
  "any"|IP|IP/prefix}]}` (the shipped `examples/acl-ip-prefix.json`
  shape) — the chain evaluates in the connect/write logic with the last
  matching rule deciding and a client no rule deciding refused (the
  default deny any; the matcher word `any` is the whole space,
  `0.0.0.0/0`). A missing or bad file refuses the start and answers
  `err` on the wire with the old gate standing, the spelling
  round-trips through the dumps and `unset`, and a group/world-readable
  acl file warns (the log, the audit trail's `ACL-FILE` event, the
  set/unset reply's suffix). The **`show acl connect table` /
  `show acl write table`** reports (show-only) render either ACL as its
  chain, one entry per line: the system forms spell the chain they
  implement — `allow 0.0.0.0/0` (any), `deny 0.0.0.0/0` (none), `deny
  0.0.0.0/0` then one `allow` line per network (the whitelist) — and a
  file gate renders its own rules (the gate desc as the `% ` line, the
  rule descs as aligned `# ` comments). A `set acl connect table` /
  `set acl write table` (the show word typed into the set verb) answers
  the pointer to the report instead of the network-parser error. The
  example **JSON Schemas** ship under each tool's `schema/` dir (draft
  2020-12): `cache/schema/acl-ip-prefix.schema.json` +
  `acl-write-registers.schema.json` + `selection.schema.json`, and the
  scraper's spec gains `scraper/schema/metrics.schema.json` (the
  sectioned form, the legacy flat form, the scraper section's
  mapping-fed shape).

- **profiles** — the **`sun2000_full`** profile: the Huawei SUN2000 full
  register map — 645 numeric registers from the newest official Modbus
  documentation (the SUN2000MA V200R024 Modbus Interface Definitions
  (V3.0) Issue 06, 2025, for the inverter + battery sections, cross-checked
  against the Solar Inverter (SUN2000-L1) Modbus Interface Definitions
  Issue 04 for the meter block 37100-37138 and the optimizer rows): the
  30000 nameplate block, the 32000 realtime block (per-string voltages and
  currents, powers, temperatures, alarms), the 35000 inspection block, the
  37000-38900 LUNA2000 battery blocks (both storage units, the per-pack
  SOC/power/temperature rows, the parallel-system rows), the 37100 smart
  meter block, the optimizer counters, and the 40000-48219 grid-code,
  scheduling and battery-config knobs. The string and multidata rows
  (model name, SN, versions, the curve/TOU period blobs) have no profile
  type and stay out. Fixes against the small `sun2000` (the drift is
  tabulated in `profiles/README.md`): 32066-32068 are the grid line
  voltages (x10), not phase powers; 32080 is the measured AC active
  power, 32078 today's peak; 32086 is the inverter efficiency (the
  shipped insulation row sat on it — the resistance lives at 32088,
  kohm); 37003 is the battery bus voltage (x10), not an efficiency;
  37760 is the system SOC (the reserve knob is 47102); the 37125
  meter-mode mapping re-codes to the docs' `{0: single-phase,
  1: three-phase}`; the PV words, the power factors, the meter frequency
  and the meter energy registers retype to the docs' signed forms. The
  four canonical names (`pv-power`, `grid-power`, `battery-power`,
  `battery-soc`) keep their addresses and scales.

- **cache** — the write gate reads from a **standalone acl file**:
  `--write-registers file:<path>` (env `WRITE_REGISTERS`, config and the
  live `set write registers file:<path>` the same) — the file IS the gate
  object a device profile carries under `acl`/`write` (`{"desc": ...,
  "rules": [{"type": "allow"|"deny", "range": "START:COUNT"}]}`), resolved
  and compiled exactly like the `profile` value: a missing or bad file
  refuses the start, the wire answers `err` with the old gate standing,
  the spelling is the re-appliable dump form, and the
  `show write registers profile` report renders the file's rules like the
   profile's. An example ships as
  `cache/examples/acl-write-registers.json` — the deye
  policy worked out: the clean-slate deny, the allows (the plain range,
  the list), the deny carves and the re-opens —
  and **a group/world-readable acl file warns**: in the log, the audit
  trail's `ACL-FILE` event, and as the suffix of the `set`/`unset` reply
  (the write gate is config trust any local user could have loosened —
  chmod 0600 silences it).

- **cache** — the **`show write registers profile`** report (show-only —
  nothing to set): the write gate answered as its acl chain — `allow any`
  / `deny any`, a range list as its whitelist (`deny any`, then one
  `allow START:COUNT` line per range), and in profile mode the device
  profile's own rules (the gate's `desc` as the `% ` line, then one
  `allow|deny <range> # desc` line per range, the comments aligned). The set/unset verbs match
  the knob rows only, so the report's live path never shadows the knob
  value `profile` — `set write registers profile` keeps setting the knob.

- **scraper** — the cache's **`--control-socket-group`** mirrors over: the
  unix control socket stays `0600` by default and the flag (env
  `CONTROL_SOCKET_GROUP`, config `set control socket-group`) opts into
  `0660` — a local group may speak to the control without being the service
  user; `set control socket-group` re-modes the live socket.

- **scraper** — **`control/port` rebinds the listener live** (`set control
  port` / `unset control port`): the cache's control listener logic ports
  over. The live set swaps the unix/TCP listener by identity — bind-first
  (a failed bind leaves the old listener untouched, the attrs roll back),
  the old accept loop retires, the connected sessions keep serving their
  replies; `off` stops accepting while the sessions keep serving (a later
  set re-enables); a re-set of the running target answers without bouncing
  the socket. The F5 rule holds on the live wire: a TCP rebind without the
  admin token refuses, and `control/token` only drops from a TCP listener
  that is already retired. `show control port` renders the live state
  (`off` when retired — previously the raw configured string), the
  dump/reload state carries an overridden target, and the socket-group
  re-mode only touches a live listener's socket.

- **everywhere** — **the gate's refusal closes with a FIN, not an RST**:
  the cap-503 and the metrics-acl refusals answer before any handler read
  the request — the peer's bytes sat unread in the kernel buffer and the
  close() fired a TCP RST that could overtake the refusal reply in the
  client's receive buffer (the client read the reset, the reply lost —
  the scraper regtest's `metrics acl order` check flaked 3 runs of 4).
  The shared GatedHTTPServer gains `_refuse_close`: half-close so the
  reply drains, then a bounded drain of what the peer sent (a 0.5s wall
  clock, a 0.2s quiet-gap recv timeout, a 1 MiB byte cap — a hostile
  peer must not pin the accept loop), then close. The scraper's
  exposition, the cache's /metrics, the dashboard's server and the
  common metrics skeleton's refusal paths all ride it.

- **scraper** — **the compute metrics are expression-fed**: the spec's
  `metrics` tree (one merged section — the entry's own field says what
  feeds it) carries compute entries with an **`expr`** (and an optional
  **`when`** presence gate) over the poll's inputs, compiled once at
  startup and evaluated per poll (a stdlib-safe whitelist evaluator —
  numbers, the inputs, `+ - * / // % **`, comparisons, `and`/`or`/`not`,
  the ternary and `abs`/`min`/`max`/round`; no attributes, no subscripts,
  one compute metric cannot feed another). An unavailable input (`soc`
  with the battery flag off, a failed read), a division by zero or a
  non-finite result keeps the metric absent for that poll. The
  **`inputs` section declares the vocabulary**: `{name: {help}}` — the
  reserved five (`pv`, `grid`, `batt`, `soc`, `battery`) are declared in
  the built-in **`lib/metrics.json`** (merged into every spec; every
  reserved input must be declared there) with their fixed semantics (the
  sanity checks, the sign flips, the battery-off rules), the spec's own
  "inputs" entries may reword them, the spec's own profile-fed keys are
  inputs too, and an unknown name — referenced or declared — is a clean
  startup error. The
  five classic compute metrics (the export/import split, home consumption,
  the charge/discharge split — `when: battery` keeps the pair absent while
  the battery flag is off) are the built-in eval-table defaults under
  every spec that doesn't define them. The four **canonical metrics** (the
  power math's inputs — `pv_generation_watts`, `grid_net_watts`,
  `battery_net_watts`, `battery_soc_percent`) move into the built-in
  **`lib/metrics.json`** too: always declared, always bound, always
  fetched — the compute inputs' sources — and a spec binding one of their
  registers a second time refuses at startup. The **`show inputs`** report
  lists
  the declared inputs (the reserved five and the spec's declared entries —
  the profile-fed keys stay referenceable without declaring them), each
  bracketed with the spec's own metric whose value it carries, and the
  **`show inputs metrics`** report lists the exported metrics (one
  `[section]`-bracketed line per metric the exposition serves, sorted by
  name); both share the aligned `name  [bracket]  help` shape and cap the
  help at a word-boundary 40 for display (the full text lives in the
  exposition and the docs). The live **`set metrics prefix` re-builds the
  spec** (and the sources) and wakes the poll — the exported names carried
  the startup prefix while the knob claimed live before. The former
  `profile`/`compute` sections are gone — their entries live in
  the one `metrics` tree, and an old-section spec refuses at startup.

- **scraper** — **the default spec resolves from a source checkout**: the
  loader tries the packaged root, then the checkout's `examples/metrics.json`
  (the examples wave moved the bundled sample there, which left a bare
  `python3 ./modbus-scraper.py` failing) — the error names every candidate
  tried.

- **everywhere** — **the control wire's reply status gains `note`** (besides
  `ok` | `fail` | `bye`): the verdict of a command that ran and whose effect
  waits. A `set`/`unset` of a restart-marked knob no longer refuses — the
  value is validated and **recorded as the configured value** (`show` renders
  it, the state dump and the reload state carry it) and the daemon answers
  **`note restart required (startup-only knob)`**; the consoles and the ctl
  one-shot render it with the **`% <message>`** face (a note, not a verdict).
  The whole-daemon reload makes the note true: the fresh process folds the
  reload state's restart-marked overrides into the startup config **before
  any socket binds** (the cache's `system/listen`, `metrics/listen`,
  `modbus/upstream`). A restart-marked *secret* (`dump/key`) still refuses
  outright — a secret never rides the reload state, so a recorded one could
  not survive the restart it promises. The restart-marked rows speak the
  CONFIGURED value now (was: the live rebind on `metrics/listen` — the row
  marked restart again in `dda97b9`); the audit rev. 17 entry follows.

### Changed

- **everywhere** — **the /metrics token posture is the F13 shape
  family-wide** (the scraper's refusal is the golden master): the cache's,
  the dashboard's and the fake's own endpoints serve tokenless on the
  loopback bind and **refuse a non-loopback bind without a token** — at
  start, on the live enable and on the live `metrics/token` unset (off
  works on the loopback listen now; beyond loopback it refuses); the
  cache's restart-marked `metrics/listen` refuses the pending move beyond
  loopback while the endpoint serves tokenless. The fake retires its
  non-loopback warning (F11's softness stays on the Modbus surface). The
  F6 mandatory-when-on rule retires — the loopback bind is the auth, the
  trust the tokenless unix control socket already assumes;
  docs/AUDIT.md rev. 20 records the move on the F6 closure.

- **dashboard** — **the page takes a bearer token; F21 closes** (the
  audit's rev. 21): `--auth-token`/`$AUTH_TOKEN` (config `auth-token`,
  live `set auth token`, `file:<path>` rides, a secret — it never
  renders) gates every GET on the main listener — the page, the static
  tree, `config.js`, the `/prom` proxy — constant-time, three
  credentials: the `Authorization: Bearer` header, the `auth` session
  cookie (HttpOnly, SameSite=Strict), and the **`?auth=<token>`
  bootstrap** that exchanges the query token for the cookie (stripped
  from the path before anything logs or forwards). The default
  `--bind` is **`127.0.0.1`** now and **a token-less non-loopback bind
  refuses to start** — the loopback dev stays friction-free; the NixOS
  module gains `authToken`/`authTokenFile` (LoadCredential), the demo
  compose binds wide in-container with a generated `page.token` (the
  entrypoint seeds it 0600), the plain-docker env example documents the
  exposure path. Breaking: a `0.0.0.0` bare start now needs the token.

- **cache, scraper, inverter, dashboard** — **`show status` is removed**
  (breaking): the key=value state report dies family-wide — the registry
  rows, the dispatch branches and the `status_report()` bodies are gone.
  Nothing replaces it: the per-setting `show <setting>` reads each value
  back, `show config` renders the effective script, `inspect` is the
  one-page dump (the machines' readings, the pins, the counters included),
  and the set/unset replies carry the compact state summary. The cli
  consoles greet with the two fixed lines now (the banner's status line
  rode the report; the cache's dump-gated completion pools probe
  `show dump path` instead).

- **cache, scraper, dashboard** — **the shipped examples move into
  `examples/` subdirs** (the sample confs, the JSON specs, the token
  placeholder — `cache/examples/`, `scraper/examples/`,
  `dashboard/examples/`): the loaders keep their search paths (in the
  package and the images the files still install beside the scripts, so
  the default `--config`/spec targets stand) — a bare checkout now passes
  `--config`/`$CONFIG` (or the spec/selection/acl paths) explicitly, the
  root no longer pretends to be live config. The packaging, the Dockerfile
  COPYs, the regtests, the lint's bundled-config legs, the book include
  and the docs follow.

- **scraper** — **the wire settings re-spell to the family's path shapes**:
  `set interval` is `set metrics interval`, `set timeout`/`set profile` are
  `set modbus timeout`/`set modbus profile`, the serving caps ride
  `set metrics limits …`, the display caps `set caps max-pv`/`caps max-grid`,
  the audit family `set audit log-file`/`audit rotate …`/`audit disable`,
  the bearer `set metrics auth token` (the flat dashed names still read in
  config files), `--listen` joins the restart-marked knobs, and the display
  groups hand their filing to the node walk (family-wide — the registries
  carry no group fields, `show knobs` renders one headerless dictionary and
  `show <node>`/`?` describe each namespace). The deadwood rows the re-spell
  exposed got their support finished: the bool knobs (`modbus battery`,
  `modbus grid-positive-import`, `local-time`) gained the live set/show/dump
  paths (`local-time` had carried a live name since the note wave and never
  answered either), the audit family is live now the cache's way
  (`audit/log-file` moves the trail — the fresh writer re-chains from the
  file's tail — the rotation rows re-render, `audit/disable` flips the
  kill switch on the shared AuditLog), and the dump carries every live row.

- **everywhere** — **the four console greetings wear one shape** (the
  cache's): the three lines' texts start at one column — the welcome
  line indents into its own block (`%   Welcome to the modbus-cache
  console`), the welcome names the daemon like the prompt does
  (`Welcome to the fake-inverter console` — was "the Fake Inverter
  console"), the status line's segments run in the cache's order —
  upstream, poll health, `running for`, the trailing count — so the
  scraper's `error(s)` and the dashboard's `client(s)` move behind
  `running for` (the dashboard keeps its `upstream (yes)` health
  spelling), and the hint line is the same `TAB completes, ? lists the
  commands, quit leaves` everywhere (the fake's extra `help <setting>`
  clause drops). The fake's README sample follows.

- **scraper, dashboard, inverter** — **`dump/restore-on-start` wears the
  restart mark** (the cache's flip rides `59689b0`): the knob was
  prospective-only (the branch's own comment — the START behaviour this
  session already chose stands), so the set records the pending value and
  answers **`note restart required (startup-only knob)`**; the three
  control planes port the cache's record flow (the gate narrows to the
  secrets, the `_apply` record branch, the `_get` configured-value shadow
  out, the dump overlay, and the mains' pre-decision fold).

- **everywhere** — **the control wire folds the command to the grammar's
  printable 8-bit before it decides** (common/wiresec.py
  `sanitize_command`, in the shared base's frame ladder after the mac
  gate): NFKD so an accented letter loses its mark (`shöw` runs as
  `show`, `m³` as `m3`), then the printable-ascii range only — control
  bytes, DEL and the scripts that do not decompose go. The frame mac
  still certifies the client's exact bytes; the fold is what the role
  gate and the command run. A command that folds away entirely answers
  like the unknown command it is. The dashboard fuzz suite pins the fold
  with a signed utf-8 command on the authenticated session; the
  dashboard man page's control-wire paragraph follows.

- **scripts** — **the GitHub release notes point at the changelog**: the
  body is the one line `For the changes see the /CHANGELOG.md.` (linked
  at the tag) — the changes list stays where it lives, in `CHANGELOG.md`;
  the workflow's extract-the-changelog-section step retires and the local
  `--release` cut speaks the same pointer (the 0.4.0 body — 97 KB of
  pasted section — re-cut by hand).

- **everywhere** — **the shared-code sweep folds the family's doubled
  code back into `common/`**: the new `common/daemon.py` carries the
  daemon-bin scaffolding the four entry scripts carried as near-copies
  (the log setup, the default config path, the SIGHUP/SIGTERM watcher
  threads, the restart-marked fold — the cache's three tool branches
  ride an `extra` hook — the ops-verb policy check and the dump-posture
  line; the cache keeps its `os._exit`-restart installer, the fake its
  SignalBox); `common/modbus` gains `ClientBase` (the connect/close/recv
  plumbing both client legs shared — the cache's session counters ride
  `after_connect`); `GatedHTTPServer` learns the 503 refusal shape
  (`rate_limit_503` + the opt-in `RATE_LIMIT_503`/`gate_log` attrs —
  the metrics servers' silent close untouched); `common/control.py`
  gains the shared `rebuild_audit` (the daily-rotation drift between
  the cache's and the scraper's copies unifies on `prm.get('daily')`);
  `common/options.py` gains `parse_registry_sections` + `option_rows`
  (the four `lib/options.py` loaders shed their ~500 copied parse/build
  lines; two latent drifts fix no-op: the bool-native default skips
  `negates` rows family-wide, and `negates` passes through all four
  loaders); `resolve_profile_file` takes the caller's candidate walk
  (the fake's embedded-copy-first list rides the shared resolver); the
  dump integrity hash is the public `payload_hash`; the fake's
  connect-ACL check calls the shared `acl_admits`.
  `scripts/family_drift.py` joins as the drift workflow — thirteen
  sweep types (the code/surface/knobs passes plus the wire-text, the
  exit/refusal, the rendered-surface, the NixOS-parity, the
  docker/env, the suite-coverage, the F-ledger, the statics, the
  schema/example and the secret-surface sweeps) regenerate the drift
  working paper. Net −719/+318 across 23 files; every
  `--help`/`--man` byte-identical, the option gates clean, the
  ten-suite battery green.

### Fixed

- **cache, scraper, inverter, dashboard** — **the help surfaces stop
  advertising the removed `show status` word**: the `show` verb's one-line
  help (the `?`/`help` reply and the registry's command row) spelled
  `status` on all four tools; the word dies with the show-status removal
  and the line reads the truth now. With it, the inverter's, scraper's and
  dashboard's registries lose the stray `s)` tails an `edit_options`
  replace path left in the audit/limits/metrics rows ("bind addresss)",
  "rotated audit backups to keeps)", "0 = no size rotations)", ...) — the
  drift doc's knobs finding and its TODO item 1 close with them (the man
  pages re-rendered through).

- **cache, scraper, inverter, dashboard** — **a busy bind answers with one
  line, not a traceback**: a listener dying on `EADDRINUSE` exits with one
  `cannot bind <host>:<port>: <why>` ERROR line, exit 1 — the scraper's
  /metrics bind was unguarded (an OSError traceback) and takes the fold,
  and the shared MetricsServer binds in the caller's context now
  (`start()` = bind, then the serving thread; the failure stashes in
  `bind_error`), so the live `set metrics-server on` on the cache, the
  fake and the dashboard answers the busy port as the err reply instead
  of unrolling a traceback from the serving thread.

- **cache** — **`show config` speaks the live overrides**: the `_apply`
  branches wrote their values into the live objects but never back into
  the resolved config dict the render reads (the `show_config_cfg`
  contract only some branches honoured — unit/auth/timeout and the ACLs),
  so a live `set metrics enable on` rendered `set metrics enable false`
  in the script while `show metrics enable` answered `on`. Every live
  branch writes back now (metrics enable/token/limits, cache ttl, modbus
  interval/read-delay/merge-gap, the limits caps, write allow/registers,
  control port/token/ops/verbs/trust-uids/socket-group, the audit
  path/rotation/disable pair, requests audit, the dump trio, local-time,
  log-access, log-level) and `unset` restores the configured startup
  value through the same branches. The metrics token resolves into the
  config dict at start now too — its `*** SECRET REMOVED ***` row renders
  (the control token's did, the metrics token's never did).

- **cache** — **the `write-registers` `profile`/`file:<path>` markers
  crashed `show config`** (the handler died mid-reply: the renderer
  formatted the marker string as a range list) — the markers render as
  themselves now, the same way `show write registers` spells them.

- **cache** — **`audit/requests` was dead on the wire**: the
  live-rename wave rekeyed the `_apply`/`_get`/dump branches to the live
  names but missed this one (still keyed the dashed `requests-audit`) —
  `set audit requests 120` answered `err unknown setting` and
  `show audit requests` answered `?`; the branches, the dump key and the
  README/man spellings take the live name now.

### Docs

- **docs** — **AUDIT.md condensed to the current state (rev. 24)**: the
  revision history (rev. 1–24), the closed findings' fix/verification
  detail and the per-finding evidence move to the new
  [AUDIT-history.md](docs/AUDIT-history.md); AUDIT.md keeps the posture,
  the trust boundaries, the controls, the open findings, the closed
  registry and the NIS2/DORA mapping — the docs/TODO pointer re-pointed.
- **everywhere** — **the four `<tool>/MANUAL.md` pages land**: every
  command, knob and show report each tool's control wire answers, the
  kind of each — command, settable (`set`/`unset`, the restart-marked
  knobs noted, the secrets flagged) or show-only (the startup-only
  knobs included) — with the flag/env twin, the value shape and the
  description, one page per tool. GENERATED from the registries by the
  new `scripts/gen_manual.py` (`--check` fails a stale page); the four
  READMEs' control sections point at them.

- **everywhere** — **the family speaks Modbus TCP inverters, not a
  vendor**: the root, scraper, cache, inverter and dashboard README
  intros, the scraper's bin docstring + parser description and the
  man-page title drop the "Huawei SUN2000" definition framing (the
  devices ride on as the shipped-profile examples — the bundled profiles
  cover the Huawei SUN2000 and the Deye hybrids); the
  register-convention citations and the profile descriptions keep the
  provenance, the `huawei_` metric-prefix default stays.

- **everywhere** — **the docs restructure**: all Nix/NixOS documentation
  moved out of the per-tool READMEs into [docs/NIXOS.md](docs/NIXOS.md)
  (the flake and its outputs, the shared module story — the set-grammar
  render, the reload/restart split, the LoadCredential secrets, the
  control-socket paths, the hardening — the three modules' option maps
  REBUILT from the `module.nix` files, whose README lists had gone stale:
  the scraper's still carried the retired register options and the
  "config INI" claim, the cache's predated the metrics ACL and the dump
  knobs — the packages, the fake's no-module note); the four tool READMEs
  re-laid on ONE skeleton (how it works → usage → configuration → runtime
  control → the feature sections → security → testing → nix → source
  layout → license) and shortened — the family-wide stories (the ACL
  grammar, the Modbus handshake, the audit chain mechanics) now point at
  [docs/ACL.md](docs/ACL.md) / [docs/MODBUS.md](docs/MODBUS.md) /
  [docs/AUDIT.md](docs/AUDIT.md) instead of re-running them, the fake and
  the dashboard gain the Testing sections they never had; the profiles
  README tightened on the same shape. The **CHANGELOG split**: the root
  file keeps Unreleased + the current release (0.4.2), the release
  history (0.4.0 and older) moved verbatim to
  [docs/CHANGELOG.md](docs/CHANGELOG.md) (the book's changelog page
  includes both); `scripts/release.py` maintains the split — a release
  moves the superseded release section(s) to the archive and the
  version-sweep's pathspec excludes it.

### Docs

- **everywhere** — **the man pages carry one section ladder per page
  class**: the daemon pages all run NAME, SYNOPSIS, DESCRIPTION,
  OPTIONS, SIGNALS, CONTROL, SECURITY, ENVIRONMENT, FILES, EXIT STATUS,
  SEE ALSO (the cache's posture prose carves out of DESCRIPTION/CONTROL
  into a new SECURITY; the scraper and the dashboard gain ENVIRONMENT +
  EXIT STATUS, the fake EXIT STATUS), the ctl pages gain the missing
  EXAMPLES / ENVIRONMENT / EXIT STATUS (the cache and the fake had the
  exit codes but no env twins, the scraper and the dashboard had none
  of the three), the cli pages gain EXIT STATUS where missing;
  `common/manpage.py` grows the LADDERS table — `page(kind=...)`
  refuses a page that misses, adds or misorders a section (the prose
  stays per-tool, the ladder does not) — the four ctl EXAMPLES'
  `printf` pipelines render their `\n` for the first time (`\\n` ate a
  character and printed a `0` — latent since the pages were ported),
  and the cache page's three over-long `.BR`/`.I` rows rewrap.

## 0.4.2 — 2026-11-08
### Changed

- **everywhere** — **the control wire's reply status speaks `ok` | `fail` |
  `bye`** (breaking): the servers' internal `err` verdicts map to `fail` at
  the frame and the reply mac signs the wire form; the console prints the
  ok replies' messages **bare** (quiet success — the `% ` marker rides the
  non-ok faces only) and the failures as **`% error: <message>`** (was
  `% err …`); the `set`/`unset` pair confirms **`% changed`** (the one ok
  face keeping the marker), the other silent confirms (`request clear
  cache`, `request restart`, `poll now`, `request reload-config`) went
  fully silent, the local `ping` answers bare `pong`; **the wire's help
  branch speaks the commands** — `help unset` describes the registry's
  command row, `help request` lists the namespace (the `?` shape),
  `help request reload` describes the deep path, and the unknown topic
  answers `unknown command or setting <words> (try ?)` (was
  `err unknown setting <words> (try help)`).
- **everywhere** — **the node listing mimics the `?` output byte for
  byte — the console's listing is the golden master**: a hierarchy
  node's wire help (`show audit`, `show audit rotate`) renders the
  node's own children as the next words — the console's sectioned render
  exactly (the aligned one-column rows, the display groups' `[section]`
  blocks, no head line of its own; the depth rides the walk — the
  flattened `rotate/max-size` rows are gone from `show audit`). The
  wire's node help answers multi-word paths on every tool and on both
  verbs that describe nodes (`show control ops`, `show metrics limits`,
  `help audit` — the cache, dashboard and fake help branches gain the
  node describe the scraper's already had); the bare `show` answers the
  walk's first position the same way (every visible top-level word — the
  namespaces, the knobs, the show reports; the cache's dump-gated
  `dump-interval` lists only while the dump node is on, the console's
  session gate); a node whose every child is
  hidden falls back to its own `name - help` line. The hidden rows (the
  secrets) never list — the pools' rule, the typed path still answers
  (`show modbus auth key` keeps refusing as a secret). The alias marking
  (`(the alias of acl/write)`) rides the console's word-help now too —
  one shape, both surfaces. The console's `?`/`help` at the empty prompt
  print the word listing itself now — the same rows TAB lists (the
  internal machinery's words never list; the command tree's descr rides
  its row) — and the expanded command-reference block (the header line,
  the full-path rows, the pinned syntax) retires with its renderer. The
  command tree speaks its own descr: a
  `commands` row may carry `node` (the name = the tree path —
  `request`, `request/clear`, `poll`) and its `help` carries the
  namespace's word-help (the walk-on borrows the row instead of the
  first child); the lint files the missing command namespaces the same
  way it files the settings'. The render is one function
  (`render_word_sections`) shared by the console's `?`/TAB listings and
  the wire's `describe_node`.

### Fixed

- **everywhere** — **the cli reconnect tries before it waits**: the first
  attempt runs immediately after the loss (a daemon that is already back
  answers on the spot), the announced `--reconnect-wait` sleep only sits
  between the tries; when every try fails the console says
  **`% error: reconnect failed, exiting`** and exits 1 (was: a bare
  stderr note and a `NoneType.close` traceback from the session
  teardown).

- **cache** — **the metrics listen rebinds live again**: the system/
  namespace wave dropped a stray `restart` mark on the metrics-listen
  row, so `set metrics listen …` answered restart-required and the
  regtest's live-rebind check died — the row's own setting-help, the
  `_apply` rebind branch and the regtest all speak live.

- **fake** — **the wire keeps a path's case**: `set dump path /srv/State/…`
  stored and echoed the lowercased value (the simulator pins' `_apply`
  lowers its value words up front and the path knob rode it) — the dump
  landed wherever the lowercase spelling pointed. The knob keeps the raw
  spelling now; the keywords still answer case-insensitively.

