# Huawei SUN2000 Prometheus scraper

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) Prometheus exporter that polls a Huawei
SUN2000 inverter over **Modbus TCP** and exposes the `huawei_*_watts` metrics
the [dashboard](../dashboard/README.md) expects, plus health gauges. It can poll the
inverter directly or through the [modbus-cache](../cache/README.md) proxy
(which it detects automatically).

## Prerequisites

Modbus TCP must be enabled on the inverter / SDongle / EMMA (via FusionSolar or
the local setup), reachable at the inverter's LAN IP on TCP port **502**, unit
id **1**.

## Run

```bash
python3 scraper/bin/modbus-scraper.py --upstream 192.168.1.100:502
curl http://localhost:9350/metrics
```

By default the exporter **binds to 127.0.0.1:9350** (loopback only) — pass
`--listen 0.0.0.0:9350` when Prometheus scrapes from another host.
**Beyond loopback a token is mandatory**: a non-loopback listen without
`--auth-token` **refuses to start** (the audit's F13 —
one clean line, no traceback); the loopback default needs no token.

Add **`--dry-run`** to validate the configuration and print the effective
settings without binding the port or contacting the inverter. Exit codes:
`0` = valid; `1` = invalid (reason on stderr); `2` = command-line misuse.

Add a Prometheus scrape job — the job **name must be `sun2000`**, the
dashboard's default config selects `huawei_*_watts{job="sun2000"}`:

```yaml
scrape_configs:
  - job_name: sun2000
    scrape_interval: 10s          # match scrapeSec in the dashboard config
    static_configs:
      - targets: ['localhost:9350']
```

(The docker demo stack ships this wired end-to-end: the `prometheus`
compose service scrapes `modbus-scraper:9350` over the internal network
with the generated token file — see [docker/README.md](../docker/README.md).)

**Authentication is disabled by default.** Set **`--auth-token <secret>`**
(config script `set auth-token`, env `AUTH_TOKEN`) to require
`Authorization: Bearer <token>` on every request — anything else gets `401`
with a `WWW-Authenticate: Bearer` challenge. The value may be a
**`file:<path>` reference** — the first line of an owner-only `0600` file
(NixOS: `authTokenFile`, mounted via `LoadCredential` and passed as
`file:/run/credentials/...`) — so the config carries the reference, never
the material; the file is re-read on every SIGHUP, so rotation is
`rewrite file` + `systemctl reload`.

> **The flag lands in `ps`.** A token passed as `--auth-token <secret>` is
> visible on the process command line — every local user can read it in
> `ps` output or `/proc/*/cmdline` (the audit's F9). Prefer the
> **`file:<path>` reference** — the file must be **owner-only (`0600`)**;
> group/world-accessible token files refuse to start (F12) — or the
> `AUTH_TOKEN` env var carrying the same `file:` reference. The flag form is for quick tests.

Pass the token to Prometheus with — the file form is the shipped way (one
secret per line, `0600`; `credentials:` with the literal secret works too):

```yaml
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/metrics.token
```

```bash
curl -H 'Authorization: Bearer <secret>' http://localhost:9350/metrics
```

## Metrics

The profile- and compute-fed names carry the `--metric-prefix` prefix (the
rows below show the default `huawei_`); the `scraper_*` self-observability
names are fixed.

| Metric | Meaning |
|---|---|
| `huawei_pv_generation_watts` | PV (inverter input) power |
| `huawei_grid_export_watts` | power exported to the grid (≥ 0) |
| `huawei_grid_import_watts` | power imported from the grid (≥ 0) |
| `huawei_home_consumption_watts` | home load, derived as `PV − net grid` (− battery when enabled) |
| `huawei_grid_net_watts` | signed net grid power (debugging aid) |
| `huawei_battery_net_watts` | signed battery power, +charge/−discharge (`--battery` only) |
| `huawei_battery_charge_watts` / `huawei_battery_discharge_watts` | the split, ≥ 0, for stacked graphs (`--battery` only) |
| `huawei_battery_soc_percent` | battery state of charge (`--battery` only) |
| `scraper_battery` | 1 if battery support is enabled (always exported); the dashboard treats 0 / missing as "no battery" and dims its battery node |
| `scraper_up` | 1 if the last poll succeeded |
| `scraper_modbus_errors_total` / `scraper_last_poll_timestamp_seconds` | poller health |
| `scraper_poll_duration_seconds` / `_mean` / `_max` | the last poll cycle's duration (the reads + the sanity checks) and its running mean/maximum |
| `scraper_cache_device_up` / `scraper_cache_age_seconds` / `scraper_cache_uptime_seconds` | modbus-cache diagnostics, **auto-detected**: exported only when the polled endpoint serves the cache's diag block (registers 65000–65003, magic-checked). `device_up 0` / a growing `age_seconds` mean the device is down **behind the cache** while the cache keeps serving last-known values |

Sign conventions and sanity caps:

- The grid register value is split into export/import by sign — by default
  **positive = export**; set `--grid-positive-import` if your device reports
  the opposite.
- Huawei power registers already report **watts** (their gain convention
  divides raw by 1000 to get kW); the decode — type and gain — comes from
  the device profile's per-entry `scale` alone, there are no scaler knobs.
- Caps are on by default: `--max-kwp 6` (6 kWp array) and `--max-grid-kw 12`
  (12 kW power line). A reading above `max-kwp × 1000` W (register 32064),
  |grid power| above `max-grid-kw × 1000` W in **either direction**
  (register 37113), or exported power above the PV cap (with home load ≥ 0,
  every exported watt must come from the inverter — unless a battery covers
  it) means bad data: the exporter logs an error (`PV energy exceeds
  max_kwp: ...` / `Grid power exceeds max_grid_kw: ...`) and serves
  **HTTP 503** with `# Error collecting metrics from inverter` instead of
  metrics, until a good poll.
- **Negative PV readings always trigger the error** regardless of the cap
  settings — a negative inverter input is bogus data that would corrupt the
  derived home load.
- The caps assume `max-kwp ≤ max-grid-kw` (the line must carry the
  inverter's full output); a startup warning fires otherwise.

## Device profile

*Where* the primary values live comes from a **device profile** — the same
shared schema the [fake inverter](../inverter/README.md) serves and the
[cache](../cache/README.md) polls; the shipped profiles live in the suite's
[`profiles/`](../profiles/) subproject (`sun2000.json` by default); the JSON
format is documented in [profiles/README.md](../profiles/README.md). WHICH entries feed the
register-backed metrics comes from **`metrics.json`** itself: an entry
carries a `profile` field naming the device-profile register it is read
from (`"huawei_pv_generation_watts": {"profile": "pv-power", ...}`); the
file is keyed by the exported metric name directly — no separate key layer.
The four **canonical** entries — the power math's inputs
(`pv_generation_watts`, `grid_net_watts`, `battery_net_watts`,
`battery_soc_percent`) — are built-in (**`lib/metrics.json`**): always
declared, always bound, always fetched (the compute inputs' sources); a
spec binding one of their registers a second time refuses at startup.
Entries without a `profile` field are expression-fed (an `expr` — below).
Each bound entry's `type`/`scale` drive the
decode — a `scale: 1` SoC is read as plain percent, a `scale: 10` one as
percent×10. The types: `i16`/`u16` (one word), `i32`/`u32` and the
lo-word-first `i32swap`/`u32swap`, the IEEE 754 `f32`/`f32swap` (two words
each), `bit` (one address read over FC1 coils / FC2 discrete inputs — the
metric is 0 or 1). Beyond the four power-math sources, every other
profile-bound metric (the phase rows, a bit flag, a float) is read once per
poll, softly: a rejected read keeps its metric absent instead of failing
the poll. A `profile` field pointing at a register the device profile
does not define leaves the metric absent (logged at startup). Profile resolution: `--profile`
flag, env `PROFILE`, config script `set modbus profile`, then the bundled copy;
re-read on `SIGHUP`. The register map itself — addresses, types, gains,
function codes — comes from the device profile **alone**: there are no
register override knobs. The live control surface swaps it at runtime:
`set modbus profile <file-or-name>` (a bare name resolves in `profiles/profiles/`,
`default` = the bundled sun2000 profile) loads the new map, rebuilds the
metric sources and rolls back cleanly when the profile lacks the registers
the power math depends on.

Metric names, help texts and types live in **`scraper/examples/metrics.json`**
(bundled next to the script in the package) and are loaded at startup — edit it to rename metrics or
reword `# HELP` lines without touching the code. The spec is **sectioned**:

- **`inputs`** — the declared expression vocabulary: `{name: {help}}` for
  every name a compute `expr`/`when` may reference. The reserved five —
  `pv`, `grid`, `batt` (0 while the battery flag is off), `soc` (absent
  while the battery flag is off) and `battery` (the 0/1 flag) — are
  declared in **`lib/metrics.json`** (merged into every spec; every
  reserved input must be declared there) and a spec's own "inputs"
  entries may reword them (never the wiring); the spec's own profile-fed
  keys stay referenceable without declaring them. `show inputs` (ctl/cli)
  lists the declared inputs only, each bracketed with the spec's own
  metric whose value it carries; **`show inputs metrics`** lists the
  exported metrics — one `[section]`-bracketed line per metric the
  exposition serves (the built-in `scraper_*` block included), sorted by
  name. Both reports share the aligned `name  [bracket]  help` shape and
  cap the help at a word-boundary 40 for display — the full text lives
  in the exposition (`# HELP`) and the docs.

  ```
  ok inputs
  batt     [battery_net_watts]    Net battery power in watts (positive …
  battery  [scraper_battery]      The battery flag (1 on, 0 off).
  pv       [pv_generation_watts]  PV input power in watts (the …

  ok inputs metrics
  huawei_battery_charge_watts  [compute]  Battery charging power in watts (0 when …
  huawei_battery_net_watts     [profile]  Battery net power in watts (positive …
  ```
- **`metrics`** — the metric tree, one entry per metric; the entry's own
  field says what feeds it. A **`profile`** field binds the device-profile
  register (above). An **`expr`** field derives the metric per poll —
  `{expr, when?, help, type?}`; `expr` (and `when`) are compiled once at
  startup and evaluated over the declared inputs — an unavailable input
  (`soc` with the battery off, a failed read), a division by zero or a
  non-finite result keeps the metric absent for that poll. The grammar is
  a strict whitelist: numbers, the inputs, `+ - * / // % **`, comparisons,
  `and`/`or`/`not`, the ternary and `abs`/`min`/`max`/`round` — one
  compute metric cannot feed another. The five classic compute metrics
  (the export/import split, home consumption, the charge/discharge split)
  are the built-in defaults under every spec that doesn't define them.
  The `section` the dashboards group by (`profile`/`compute`) derives
  from the field.
- **`scraper`** — the exporter's own observability specs, shipped
  separately in **`scraper/lib/metrics.json`** and merged in over the
  configured spec in memory at startup: a custom `--metrics-spec` only needs
  the sections it cares about, and its `scraper` entries —
  when it has any — override the built-ins by name. A missing or corrupt
  spec — or an expression/declaration that does not check out — fails
  cleanly at startup (one-line error, exit 1), never a traceback.

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`modbus-cache`:

1. CLI flags (`--upstream`, `--listen`, …)
2. Environment variables — the same names, bare (no tool prefix): `CONFIG`,
   `METRICS_SPEC`, `UPSTREAM`,
   `MODBUS_UNIT`, `MODBUS_OFFSET`,
   `TIMEOUT`, `PROFILE`, `METRIC_PREFIX`,
   `MAX_KWP`, `MAX_GRID_KW`,
   `BATTERY`,
   `GRID_POSITIVE_IMPORT`, `LISTEN`,
   `INTERVAL`, `LOCAL_TIME`, `LOG_ACCESS`,
   `LOG_LEVEL`, `AUTH_TOKEN`,
   `MAX_CLIENTS`, `CLIENT_TIMEOUT`
3. Config file — the set-grammar script (`set <name> <value>` lines) —
   `--config` picks the
   file (default: `$CONFIG`, then `scraper.conf` next to the script —
   the packaged layout — then the subproject root's sample; missing file is
   fine)
4. Built-in defaults

Every setting is **sanitized and validated** before use: whitespace is
stripped, hostnames/listen addresses are charset- and length-checked, all
numeric settings must be finite (`nan`/`inf` rejected), tokens must be free
of whitespace/control characters (file tokens capped at 8192 bytes, and a
token file must be owner-only — mode `0600` — a group/world-accessible one
refuses to start, F12), and a
**malformed config file is fatal** (it never silently falls back to
defaults). Nonsense values (negative intervals, out-of-range
registers/ports, bad unit ids, unknown log levels) abort with a clean
one-line error instead of failing later at runtime. The only soft spot is
`timeout > interval`: that logs a warning (polls run back-to-back) instead
of failing.

`scraper/examples/scraper.conf` is a sample in the set grammar (every line a
`set <name> <value>`, `#` comments stay comments — the file pipes through
`modbus-scraper-ctl` unchanged, and `show config` regenerates it from the running
scraper — the secret knobs render as `set <name> *** SECRET REMOVED ***`,
the value never does, and the parser refuses the placeholder):

```conf
# modbus-scraper configuration — every line is a set command (the CLI spelling)
set modbus upstream 127.0.0.1:5502
set modbus unit 1
set modbus offset 0
set modbus timeout 3
set caps max-pv 6
set caps max-grid 12
set modbus battery false
set modbus grid-positive-import false
set metrics listen 127.0.0.1:9350
set metrics interval 10
set metrics limits max-clients 64
set metrics limits timeout 300
set metrics limits max-conn-per-ip 0
set log-level INFO
```

## Runtime control (signals)

| Signal | Effect |
|---|---|
| `SIGHUP` | **Reload the configuration** without dropping the exporter: poll interval, caps, the device profile (the whole register map), battery flag, auth token (+ file re-read = rotation), client limits, the Modbus auth scheme/key and the upstream address/port/unit/timeout take effect immediately (the Modbus socket reconnects on the next poll). An invalid value keeps the previous settings — the error is logged and the next `SIGHUP` retries. The listen address, log level and `metrics.json` need a restart. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown**: the exporter stops, and the shutdown logs a session summary (duration + poll-error count). |

```bash
kill -HUP  $(pgrep -f scraper.py)   # reload the config
```

### The control server

The scraper runs the family's JSON-lines control server — **by default on
the unix socket `/tmp/modbus-scraper-<listen-port>.socket`** (`0` switches
it off, a TCP port number binds `127.0.0.1:PORT` instead, the socket path
is just a path). Talk to it with **`modbus-scraper-ctl`** (one-shot / batch) or
**`modbus-scraper-cli`** (the console session):

```bash
python3 scraper/bin/modbus-scraper-ctl.py show status
printf 'set metrics interval 5\npoll now\n' | python3 scraper/bin/modbus-scraper-ctl.py
python3 scraper/bin/modbus-scraper-cli.py            # TAB completes, ? lists
```

Commands: `set`/`unset` over the live settings (**`modbus profile`** (the
device profile: the register map swaps live, `default` restores the bundled
sun2000 profile), **`metrics interval`**,
**`modbus timeout`**, **`metrics limits max-clients`**, **`metrics limits timeout`**,
**`metrics limits max-conn-per-ip`**, **`caps max-pv`**/`caps max-grid`, **`log-access`**, **`log-level`**, **`modbus
auth`**/`modbus auth key` (the suite scheme + key toward the inverter; a
change drops the Modbus session — the next poll reconnects and handshakes)
— and the
**token lives**: `control token` and `control ops token` rotate the
control tokens live (the sessions re-auth), `metrics auth token` rotates the
/metrics bearer live; a token value never renders back — **`show <secret>`
refuses** (it is a secret: pass it by flag/env, or as `file:<path>`)),
`control socket-group` (re-modes the live unix socket `0600`/`0660`),
`show status` (the key=value report), `show connections` (the live HTTP
clients of /metrics), `poll now` (the loop wakes immediately), `request
reload-config` (the SIGHUP path — the token file re-reads, so the bearer
token rotates too), `request restart` (the Modbus session drops; the next
poll reconnects), `request reload` (**the whole-daemon restart that keeps
the sets**:
the live overrides save to a state file beside the config
(``<config>.reload``), the process re-execs, the fresh daemon re-resolves
the config file and re-applies the saved overrides once, then consumes the
state file — overridden secrets save as `*** SECRET REMOVED ***` (the
value never lands in the file), the reply names them), the state dump
(`--dump-path`): `request dump` /
`request restore` (the live overrides as one `0600` JSON with an
integrity hash — an overridden secret rides as `*** SECRET REMOVED ***`,
the restore skips the placeholder and names it;
`--restore-on-start` loads it at start; `--dump-key` seals the dump —
the state rides encrypted, a restore refuses a wrong or missing key;
a dump path without a key warns unsealed at start and on `set`),
`inspect`,
`show version`, `show knobs` (the dictionary of
the registry: every knob with its flag, its env twin, how it changes),
`shutdown`.

A **TCP control port refuses to start without a token** (the audit's F5 —
the same rule as the cache): `--control-token`
requires the token handshake (`{"cmd": "auth", "token": ...}`) on the first
frame; over the unix socket a kernel-vouched peer (root, the daemon's own
user or `--control-trust-uids` — `SO_PEERCRED`) skips the handshake.
Every token value also takes a `file:` reference — `--control-token
file:/path` reads the first line of an owner-only `0600` file (the same
loader disciplines every secret; a systemd LoadCredential rides as
`file:/run/credentials/...`).
**With a token configured the wire is signed**: every command and reply
carries the **full sha256 HMAC of its payload, keyed by the token** —
a token-holding client verifies nothing was injected or altered in flight,
and over TCP the signed commands are mandatory (the same wire the cache
and the fake speak). A **second, read-only token**
(`--control-ops-token`) authenticates into the
**`show`/`clear` verbs only** — no `set`/`unset`, no `poll now`, no
`request reload`, no `reload`, no `restart`, no `shutdown`: the ops shift
against the admin key. Denied commands answer `err forbidden: the ops token
runs the show/clear verbs only (<verb> needs the admin token)`; the SCR
trail's COMMAND entries name the session's role (`role=ops`/`role=admin`,
the denials included), and each session's frames are mac'd with the key it
authenticated with. The control commands (with their wire macs), the auth
failures, the reloads and the shutdowns land in the **SCR audit trail**
(`--audit-log`, the XDG state home by default — `scripts/audit_verify.py`
walks it like the others).

## What /metrics leaks (the privacy note, F15)

The endpoint exposes **production values, not telemetry**: the current PV
generation, the home consumption, the battery state of charge and the
per-phase voltages/currents. A week of that is a **home-occupancy
profile** — when the house is producing, when it draws, when nobody is
home. The controls are the **bearer token** (`--auth-token`, mandatory
beyond loopback — a token-less non-loopback bind refuses to start, F13)
and the **localhost bind** (the default). Treat the endpoint as internal:
do not publish it, and scope any reverse proxy that frontends it.

## Logging and audit trail

Logging is `logging`-based with **UTC timestamps by default** (`--local-time`
switches to the system time zone): one startup line with the effective
settings, reachability changes and reloads at INFO/WARNING (every poll at
DEBUG). HTTP requests are quiet by default; **`--log-access`** logs every
request at INFO (`127.0.0.1 - "GET /metrics" 200 1234 bytes`) as an audit
trail of who scraped what when. **Rejected requests are always audited**
regardless: unauthorized calls log a WARNING (client, path), rate-limit
rejections an INFO, and SIGTERM/SIGINT shutdowns log a session summary
(duration + poll-error count). Handled connection problems (client hangs
up, idle kick, poll-cycle crash) always log a single line — the suite
enforces that **no scenario produces a traceback**.

Under systemd (`JOURNAL_STREAM` set) log lines omit their own timestamp —
journald adds one.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `$CONFIG`, then `scraper.conf` next to the script, then the subproject root's | config file path (the set grammar) |
| `--metrics-spec` | `$METRICS_SPEC` or the bundled `metrics.json` | metrics spec JSON, sectioned: {inputs?, metrics (profile?/expr?/when?), scraper} — merged in memory over the built-in `lib/metrics.json` (the inputs declaration + the scraper_* block); the file's JSON Schema ships as `examples/metrics.schema.json` |
| `--upstream` | `127.0.0.1:5502` | the inverter's Modbus TCP endpoint `HOST:PORT` (`:5502` = `127.0.0.1:5502`) |
| `--modbus-unit` | `1` | Modbus unit id |
| `--modbus-offset` | `0` | added to register addresses (set `-1` for gateways that need 0-based addressing) |
| `--auth` | `none` | the inverter's Modbus auth scheme the session must speak: `suite` proves the shared key with a crypt handshake (magic + nonce + HMAC proof, the peer answers `OK`, or `ERR` and the connection fails — the poller keeps retrying) right after every connect; `none`/empty = no auth at all (config `set modbus auth`, env `AUTH`) |
| `--auth-key` | none | the shared key the suite handshake proves, **min 16 characters**; the value may be `file:<path>` — the first line of an owner-only `0600` file (config `set modbus auth key`, env `AUTH_KEY`) — the peer's key must match: the fake inverter serves its side with `--auth suite --auth-key …` |
| `--profile` | the bundled `sun2000` profile | device profile JSON (the shared profiles/ schema): the whole register map — addresses, types, gains, function codes; a bare name resolves in `profiles/profiles/`; live-swappable with `set modbus profile` |
| `--max-kwp` | `6` | PV input power check against the array size: above `max-kwp × 1000` W → HTTP 503 + error log; `0` = off. Negative PV and export above the PV cap always error |
| `--max-grid-kw` | `12` | power line grid exchange check: \|grid power\| above `max-grid-kw × 1000` W (either direction) → HTTP 503 + error log; `0` = off |
| `--battery` | off | enable battery support: battery term in the home derivation + battery metrics |
| `--metric-prefix` | `huawei` | the prefix on the **profile- and compute-fed** metric names (`<prefix>_pv_generation_watts`, ...); the bundled `scraper_*` names are fixed (env `METRIC_PREFIX`) |
| `--grid-positive-import` | off | grid register positive means import |
| `--timeout` | `3` | Modbus connect/read timeout, seconds |
| `--listen` | `127.0.0.1:9350` | exporter bind address `HOST:PORT` (loopback by default) |
| `--interval` | `10` | seconds between Modbus polls |
| `--log-level` | `INFO` | `DEBUG` logs every poll |
| `--log-access` | off | audit log: every HTTP request at INFO (client, path, status, size) |
| `--auth-token` | disabled | require `Authorization: Bearer <token>` on every request (`401` + `WWW-Authenticate` otherwise; token compared timing-safe); the value may be `file:<path>` — the first line of an owner-only `0600` file (**re-read on every SIGHUP** — rotate by rewriting the file and reloading), F12 |
| `--control-port` | `/tmp/modbus-scraper-<listen-port>.socket` | the JSON-lines control server target (unix socket path or TCP port on 127.0.0.1), `0` = off |
| `--control-token` | off | require the token auth handshake on control connections (the clients take `--control-token` / `CONTROL_TOKEN`); a TCP control port refuses to start without one (F5); the value may be `file:<path>` — the first line of an owner-only `0600` file, F12 |
| `--control-ops-token` | off | a second, **read-only** control token: its sessions run the `show`/`clear` verbs only (no `set`/`unset`, no `poll now`, no `request reload`, no `restart`, no `shutdown`) — needs `--control-token`, must differ from it; both roles audited (`CONTROL_OPS_TOKEN`) |
| `--control-ops-verbs` | `show,clear` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated, validated against the control grammar at start (`CONTROL_OPS_VERBS`) |
| `--control-trust-uids` | none | extra peer uids the unix control socket trusts without the token (`SO_PEERCRED`): comma-separated — root and the daemon's own user are always trusted (env `CONTROL_TRUST_UIDS`) |
| `--control-socket-group` | off | leave the unix control socket group-accessible (`chmod 0660` instead of the default `0600`): a local group may speak to the control without being the service user (config `set control socket-group`, env `CONTROL_SOCKET_GROUP`) |
| `--dump-path` | off | the state dump (write-behind): the live setting overrides — the tokens apart — as one JSON, created `0600` with an integrity hash, written on the `request dump` command and the graceful shutdown; loaded on start only with `--restore-on-start`, on demand with the `request restore` command (config `set dump path`, env `DUMP_PATH`) |
| `--dump-key` | off | the key that **seals** the state dumps and the reload's state file: the state rides encrypted (an HMAC-SHA256 counter-mode keystream, authenticated — a restore refuses a wrong or missing key, and a configured key refuses an unsealed dump); startup-only — the reload re-exec re-resolves the same key (config `set dump key`, env `DUMP_KEY`); the value may be `file:<path>` — the first line of an owner-only 0600 file, so the config carries the reference, never the material; a dump path without a key warns unsealed at start and on `set dump path` |
| `--restore-on-start` | off | load the state dump when the daemon starts (needs `--dump-path`) — the live overrides ride again instead of a cold start (config `set restore-on-start`, env `RESTORE_ON_START`) |
| `--audit-log` | the XDG state home | the SCR audit trail: a file path or `-` for stdout (the docker/journald way) |
| `--audit-max-mb` / `--audit-files` / `--no-audit-log` | `10` / `3` / off | the audit trail's rotation and the off switch |
| `--man` | off | print the generated man page (roff) to stdout and exit (`modbus-scraper --man \| man -l -`) |
| `--max-clients` | `64` | cap concurrent HTTP clients; overflow gets an immediate `503 # rate limited` (0 = unlimited) |
| `--client-timeout` | `300` | kick idle keep-alive clients after this many seconds (0 = off) |
| `--max-conn-per-ip` | `0` | cap concurrent HTTP connections from one peer IP; overflow gets an immediate `503 # rate limited` (0 = no per-IP limit) |
| `--local-time` | UTC | log timestamps in the system time zone |
| `--dry-run` | off | validate the config, print the effective settings and exit (`0` = valid, `1` = invalid, `2` = CLI misuse) |

Register defaults follow Huawei's official *Solar Inverter Modbus Interface
Definitions* (Issue 04, 2023-01-10) — they live in the device profile
(`profiles/profiles/sun2000.json`), not in flags:

- **32064** — Input power, I32. Unit kW with gain 1000, i.e. raw values are watts.
- **37113** — [Power meter] Active power, I32, `> 0` = feed-in. Populated by
  the connected power meter (DTSU666 etc.); without a meter the inverter
  alone cannot report grid power.
- Older **20200520** protocol: input power at **32089**, meter power at
  **37258** — point `--profile` at a profile carrying those addresses (or
  copy sun2000.json and edit the two).
- Unit quirk: the inverter's `[Power meter collection]` copy of 37113 has
  been observed reporting **watts** (gain 1) while the meter-section table
  says kW (gain 1000). The bundled profile assumes watts (gain 1); if grid
  power looks 1000× off the other way, set the entry's `scale` to 1000 in
  your profile copy.
- With a battery the derived home load is wrong while the battery
  charges/discharges — point the dashboard's `load` metric at a real meter
  register/exporter instead.

## Test inverter

The fake inverter lives in its own subproject: [inverter/](../inverter/README.md) — a Modbus TCP server with day/static demo values, battery + meter simulation, a runtime control server (`set`/`show` values, chaos injection) and the `modbus-fake-ctl` CLI. Both regression suites start it automatically.

## Battery

**Experimental — so far verified only against simulated data** (fake inverter /
mock Prometheus), not against real hardware.

When a battery is present, enable support with `--battery` (env
`BATTERY`, config script `set modbus battery true`). The energy balance gains a battery
term and the home load derivation becomes:

```
home = pv − batt − grid      (without battery: home = pv − grid)
```

Battery registers (defaults follow the same Huawei convention as the PV
register — they come from the device profile's `battery-power` and
`battery-soc` entries):

- **37001** — battery power, I32 W, **positive = charging**,
  negative = discharging
- **37004** — state of charge, U16, percent×10

Charging midday surplus reduces the home value; evening discharge covers the
home load even with PV at 0. The battery metrics —
`huawei_battery_net_watts` (signed, +charge/−discharge),
`huawei_battery_charge_watts` / `huawei_battery_discharge_watts`
(the split, ≥ 0, for stacked graphs) and `huawei_battery_soc_percent` —
are only exported when battery support is enabled; without it they are
absent from /metrics.

The consistency checks adapt:

- Exported power may exceed the PV cap by the battery discharge (a battery
  feeding the grid is legitimate).
- A derived `home < 0` is rejected as inconsistent data — with a battery,
  charging and export together cannot exceed the PV input.

The fake inverter can emulate the battery for testing:
`python3 inverter/bin/modbus-fake-inverter.py --battery`.

## Nix

```bash
nix run .#modbus-scraper -- --upstream 192.168.1.100:502
```

NixOS module (same flake, service runs with a dynamic user and systemd
hardening); the package installs the man page too (`man/modbus-scraper.1`
under `share/man/man1/`):

```nix
services.modbus-scraper = {
  enable = true;
  upstream = "192.168.1.100:502";  # the inverter's LAN IP (:PORT)
  listenHost = "0.0.0.0";          # only if Prometheus runs on another host
  listenPort = 9350;
  battery = true;                  # once a battery is installed
};
```

Options: `enable`, `package`, `upstream` (`HOST:PORT`, `:PORT` = loopback),
`modbusUnit`,
`modbusOffset`, `auth`/`authKey` (the suite scheme + shared key toward the
inverter; null = no auth), `pvRegister`, `gridRegister`, `scale`, `gridScale`, `maxKwp`,
`maxGridKw`, `battery`, `batteryRegister`, `batterySocRegister`,
`gridPositiveImport`, `timeout`, `interval`, `listenHost`, `listenPort`,
`logLevel`, `localTime`, `logAccess`, `maxClients`, `clientTimeout`, `authToken`, `authTokenFile`, `openFirewall`.

The module renders the **config INI into the store** and runs the service
with `--config`. A `nixos-rebuild switch` applies changes with
`systemctl reload` (SIGHUP): interval, caps, registers, battery flag, auth
token, the Modbus auth scheme/key and the upstream address are picked up
live. Changes to
`listenHost`/`listenPort`/`logLevel` need a manual
`systemctl restart modbus-scraper`.

## Testing

Three standalone suites live in the suite-root [`tests/`](../tests/) — stdlib only, each starts
its own fake inverter + exporters on scratch ports and cleans up after itself:

```bash
python3 tests/scrape-regtest.py   # the functional battery (values, export/import
                                  #   split, battery on/off, caps 503 + recovery,
                                  #   auth + token rotation, limits, diagnostics,
                                  #   SIGHUP, inverter death, hostile-inverter
                                  #   phase, dry-run exit codes — plus the fake's
                                  #   own control/machine coverage)
python3 tests/scrape-fuzz.py [n]  # n client-garbage HTTP frames (default 3000)
```

Every scenario must end with the exporter serving correct metrics and
**zero tracebacks** in the logs.

## Source layout

```
scraper/
├── bin/
│   ├── modbus-scraper.py  # CLI, logging setup, signal handling, the control wiring
│   ├── modbus-scraper-ctl.py     # one-shot / batch control client
│   └── modbus-scraper-cli.py     # console-style control session
├── examples/
│   ├── scraper.conf         # sample config in the set grammar (installed beside the script)
│   ├── metrics.json         # the phase rows' + the compute expressions' specs (the canonical four are built-in)
│   └── metrics.schema.json  # the metrics spec's JSON Schema (draft 2020-12 — the loader stays the strict word)
└── lib/
    ├── static.json        # the static constants: protocol limits, diagnostics block, defaults
    ├── metrics.json       # the built-in inputs declaration + the four canonical metrics + the scraper_* specs — always merged in over the configured spec
    ├── statics.py         # its loader (the STATIC dict + the named aliases)
    ├── protocol.py        # Modbus TCP client (hardened framing)
    ├── config.py          # settings resolution + validation
    ├── metrics.py         # metrics.json loader
    ├── poller.py          # poll loop + sanity checks + cache diagnostics
    ├── server.py          # Prometheus exposition endpoint (auth, limits)
    ├── control.py         # JSON-lines control server (the cache's shape, mirrored)
    ├── options.json       # the knob registry: the flags, the env twins, the live settings + their control vocabulary
    ├── options.py         # its loader: the Option rows, the control-grammar vocabulary, the wiring
    ├── man.py             # the generated man pages' prose (common/manpage.py renders)
    └── version.py         # the suite version
```

## License

The scraper (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
