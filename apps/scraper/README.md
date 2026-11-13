# modbus-scraper

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time. So far verified only against simulated data (fake inverter,
> mock Prometheus), not against real hardware.

A dependency-free (Python stdlib only) Prometheus exporter that polls a
Modbus TCP inverter and exposes the `huawei_*_watts` metrics (the
`--metrics-prefix` default) the [dashboard](../dashboard/README.md)
expects, plus health gauges. The bundled profiles cover the Huawei
SUN2000 and the Deye hybrids. It can poll the inverter directly or
through the [modbus-cache](../cache/README.md) proxy (which it detects
automatically).
Modbus TCP must be enabled on the inverter / SDongle / EMMA (via
FusionSolar or the local setup), reachable at the inverter's LAN IP on TCP
port **502**, unit id **1**.

## How it works

- a poll loop reads the device profile's registers every `--modbus-interval`
  seconds (the register map — addresses, types, gains, function codes —
  comes from the profile **alone**; there are no register override knobs);
  the source ranges merge into as few **block reads** as the `--modbus-merge-gap`
  allows (a failed block splits to its sources — `show uplink` renders the
  plan and its latency);
- the reading passes **sanity caps** (`--max-kwp`, `--max-grid-kw`): bad
  data answers **HTTP 503** with `# Error collecting metrics from
  inverter` until a good poll, never silently wrong numbers;
- the exposition serves the profile- and compute-fed names (the
  `--metrics-prefix` prefix, default `huawei_`) and the fixed
  `scraper_*` self-observability gauges.

## Usage

```bash
python3 apps/scraper/bin/modbus-scraper.py --upstream 192.168.1.100:502
curl http://localhost:9350/metrics
```

By default the exporter **binds to 127.0.0.1:9350** (loopback only) — pass
`--listen 0.0.0.0:9350` when Prometheus scrapes from another host.
**Beyond loopback a token is mandatory**: a non-loopback listen without
`--auth-token` **refuses to start** (the audit's F13 — one clean line, no
traceback); the loopback default needs no token.

Add **`--dry-run`** to validate the configuration and print the effective
settings without binding the port or contacting the inverter. Exit codes:
`0` = valid; `1` = invalid (reason on stderr); `2` = command-line misuse.

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`modbus-cache`:

1. CLI flags (`--upstream`, `--listen`, …)
2. Environment variables — the same names, bare (no tool prefix):
   `CONFIG`, `UPSTREAM`, `MODBUS_UNIT`, `MODBUS_OFFSET`, `MODBUS_TIMEOUT`,
   `MODBUS_INTERVAL`, `LISTEN`, `MODBUS_PROFILE`, `LOG_LEVEL`, `AUTH_TOKEN`, … —
   the full twin set is the generated
   [`docker/env/modbus-scraper.env.example`](../../docker/env/modbus-scraper.env.example)
3. Config file — the set-grammar script (`set <name> <value>` lines) —
   `--config` picks the file (default: `$CONFIG`, then `modbus-scraper.conf` next
   to the script, then the subproject root's sample; missing file is fine)
4. Built-in defaults

Every setting is **sanitized and validated** before use — a malformed
config file is fatal, nonsense values abort with a clean one-line error
instead of failing later at runtime. The only soft spot is `timeout >
interval`: that logs a warning (polls run back-to-back) instead of failing.

`examples/modbus-scraper.conf` is a sample in the set grammar — GENERATED
(`dev/generators/examples.py`) from `lib/options.json`, every knob the
registry declares, every line commented at its default; `show config`
regenerates the script from the running scraper (secrets hidden):

```conf
# modbus-scraper configuration — every line is a set command in the CLI spelling
# (the live path as words; the flat dashed knob name reads too, for older files)
set modbus upstream 127.0.0.1:5502
set modbus unit 1
set modbus caps max-pv 6
set modbus caps max-grid 12
set system listen 127.0.0.1:9350
set modbus interval 10
set system log-level INFO
```

| Flag | Default | Meaning |
|---|---|---|
| `--upstream` | `127.0.0.1:5502` | the inverter's Modbus TCP endpoint `HOST:PORT` (`:5502` = `127.0.0.1:5502`) |
| `--modbus-unit` / `--modbus-offset` | `1` / `0` | Modbus unit id / added to register addresses (`-1` for gateways that need 0-based addressing) |
| `--modbus-auth` / `--modbus-auth-key` | `none` | the inverter's Modbus auth scheme (`suite` = the crypt handshake; `none` = no auth) + the shared key (**min 16 characters**, `file:<path>` welcome) — the peer's key must match; see [docs/specs/MODBUS.md](../../docs/specs/MODBUS.md) |
| `--modbus-profile` | the bundled `sun2000` profile | device profile JSON (a bare name resolves in `shared/profiles/`); live-swappable with `set modbus profile` |
| `--metrics-spec` | the bundled `metrics.json` | metrics spec JSON, sectioned `{inputs?, metrics, scraper?}` — merged in memory over the built-in `lib/metrics.json`; the JSON Schema ships as `schema/metrics.schema.json` |
| `--metrics-prefix` | `huawei` | the prefix on the **profile- and compute-fed** metric names; the bundled `scraper_*` names are fixed |
| `--max-kwp` / `--max-grid-kw` | `6` / `12` | the sanity caps in kW: above the cap → HTTP 503 + error log; `0` = off |
| `--modbus-read-delay` | `0.05` | seconds between consecutive device reads within a poll cycle (the slow-dongle pacing); `0` = no wait |
| `--modbus-merge-gap` | `8` | max register gap when merging the profile's source ranges into block reads (fewer round trips); `0` = read each range separately |
| `--grid-positive-import` | off | grid register positive means import |
| `--modbus-timeout` / `--modbus-interval` | `3` / `10` | Modbus timeout, seconds / seconds between Modbus polls |
| `--listen` | `127.0.0.1:9350` | exporter bind address `HOST:PORT` (loopback by default; beyond loopback `--auth-token` is mandatory, F13) |
| `--auth-token` | disabled | require `Authorization: Bearer <token>` on every request (`401` + `WWW-Authenticate` otherwise; compared timing-safe); the value may be `file:<path>` — **re-read on every SIGHUP**: rotate by rewriting the file and reloading |
| `--metrics-acl` | `any` | the clients allowed to **connect** to /metrics: `any`, `none`, comma-separated IPs/prefixes, `file:<path>` (the ip-prefix acl file — the grammar lives in [docs/specs/ACL.md](../../docs/specs/ACL.md)); checked at accept; live-settable |
| `--control-port` | `/tmp/modbus-scraper-<listen-port>.socket` | the JSON-lines control server target (unix socket path or TCP port), `0` = off |
| `--control-token` / `--control-ops-token` | off | the control tokens (a TCP control port refuses to start without the admin token, F5); `file:<path>` welcome |
| `--control-ops-verbs` | `show` | the read-only ops role's RBAC policy (`flush` is not a verb here — there is nothing to flush) |
| `--control-trust-uids` / `--control-socket-group` | none / off | the unix socket's extra trusted uids (`SO_PEERCRED`) / its 0660 group-accessible mode |
| `--control-log-replies` | off | DEBUG-log the full output of every control command (plainly: the command and its status); live: `set system log-replies` |
| `--dump-path` / `--dump-key` / `--dump-interval` / `--restore-on-start` | off | the sealed state dump (the live overrides; `request dump`/`restore`, every `--dump-interval` seconds) |
| `--audit-log` (+ `--audit-max-mb`, `--audit-daily`, `--audit-files`, `--no-audit-log`, `--audit-forward`, `--audit-forward-format`) | XDG state | the SCR audit trail: a file path, `-` for stdout (the docker/journald way) or `none` (no local file — the forward carries the trail); the forward mirrors every line onward (F10) |
| `--metrics-max-clients` / `--metrics-client-timeout` / `--metrics-max-conn-per-ip` | `64` / `300` / `0` | the HTTP caps (overflow gets an immediate `503 # rate limited`) — the cache's `metrics-*` spellings, shared with the cache's /metrics endpoint |
| `--log-level` / `--log-access` / `--local-time` | `INFO` / off / UTC | the log surface |
| `--config` / `--dry-run` / `--man` | — | the config file path / validate + print and exit / print the generated man page |

Register defaults follow Huawei's official *Solar Inverter Modbus Interface
Definitions* (Issue 04, 2023-01-10) — they live in the device profile, not
in flags:

- **32064** — input power, I32, unit kW with gain 1000 (raw values are
  watts); **37113** — meter power, I32, `> 0` = feed-in (without a meter
  the inverter alone cannot report grid power).
- Older **20200520** protocol: input power at **32089**, meter power at
  **37258** — point `--modbus-profile` at a profile carrying those addresses.
- Unit quirk: the inverter's `[Power meter collection]` copy of 37113 has
  been observed reporting **watts** (gain 1) while the meter-section table
  says kW (gain 1000). The bundled profile assumes watts; if grid power
  looks 1000× off the other way, set the entry's `scale` to 1000 in your
  profile copy.
- With a battery the derived home load is wrong while the battery
  charges/discharges — point the dashboard's `load` metric at a real meter
  register/exporter instead.

## Runtime control

### Signals

| Signal | Effect |
|---|---|
| `SIGHUP` | **Reload the configuration** without dropping the exporter: poll interval, caps, the device profile, auth token (+ file re-read = rotation), client limits, the Modbus auth scheme/key and the upstream take effect immediately. An invalid value keeps the previous settings. The listen address and `metrics.json` need a restart (`log-level` is live — `set system log-level`). |
| `SIGTERM` / `SIGINT` | **Graceful shutdown** with a session summary (duration + poll-error count). |

### The control server

The scraper runs the family's JSON-lines control server — **by default on
the unix socket `/tmp/modbus-scraper-<listen-port>.socket`** (`0` switches
it off, a TCP port number binds `127.0.0.1:PORT` instead). Talk to it with
**`modbus-scraper-cli`** (a symlink to the family's `apps/pvsuite-cli.py`
dispatcher — `pvsuite-cli scraper` or `pvsuite-cli modbus-scraper` spells the
same client, the tool from the word) — one client, three modes (command words
one-shot, piped stdin batch, a bare terminal the console):

```bash
python3 apps/scraper/bin/modbus-scraper-cli.py show upstream
printf 'set interval 5\nrequest poll now\n' | python3 apps/scraper/bin/modbus-scraper-cli.py
python3 apps/scraper/bin/modbus-scraper-cli.py            # bare on a terminal: TAB completes, ? lists
```

The console prints through a pager: a reply taller than the screen pauses
(`-- more --`) — space walks a page, return a line, `q` stops the rest
(`--page-size`/`CLI_PAGE_SIZE` set the size, 0 = off; the session-local
`page` command retunes it live; a terminal under 20 rows or 64 columns
refuses to start).

The wire (the signed frames, the peer-cred trusted peers, the read-only
ops role, the F5 token rule) is the family's — one paragraph per piece in
[docs/specs/ACL.md](../../docs/specs/ACL.md) (the control-plane row) and
[docs/SECURITY.md](../../docs/SECURITY.md); a token value never renders back
(`show <secret>` refuses). Every command and knob the wire answers —
command, settable (`set`/`clear`) or show-only — is tabled in
[MANUAL.md](MANUAL.md) (generated from the registry). The commands:

| Command | Effect |
|---|---|
| `set` / `clear` | the live settings: `modbus profile` (the map swaps live; `default` restores the bundled sun2000), `modbus interval`, `modbus timeout`, `modbus read-delay`, `modbus merge-gap` (the poll plan rebuilds), the `metrics limits` caps, `modbus caps max-pv`/`modbus caps max-grid`, `system log-access`, `system log-level`, `audit log-file`/`audit rotate …`/`audit forward`/`audit instance`/`audit disable` (the audit family swaps live), `modbus auth` (the scheme swaps live), `metrics acl`, `control ops verbs`/`control trust-uids`/`control socket-group`, `control port` (rebinds the listener live) — `system listen` (the serve address, `show listen` answers it) and the tokens/auth keys are startup-only: the set answers the restart note, pass them by flag/env/config |
| `show uplink` | the inverter link: session counters plus one row per poll block — status, latency, failures |
| `show uplink-sources` | the register map: one row per polled register — fc, register, the range that fetches it, source |
| `show connections` | the live HTTP clients of /metrics |
| `request poll now` | the loop wakes immediately |
| `request reload-config` | the SIGHUP path (the token file re-reads, so the bearer token rotates too) |
| `request restart` | the Modbus session drops; the next poll reconnects |
| `request reload` | the whole-daemon restart that keeps the sets: the live overrides save to `<config>.reload`, the process re-execs and re-applies them once (overridden secrets save as `*** SECRET REMOVED ***`, the reply names them) |
| `request dump` / `request restore` | the state dump (`--dump-path`): the live overrides as one `0600` JSON with an integrity hash; `--dump-key` seals it; the `--dump-interval` loop rewrites it live |
| `inspect` / `show version` / `show knobs` | the one-page dump for a bug report / the version / the knob registry |
| `shutdown` | gracefully stop the exporter |

## Metrics

| Metric | Meaning |
|---|---|
| `huawei_pv_generation_watts` | PV (inverter input) power |
| `huawei_grid_export_watts` / `huawei_grid_import_watts` | power exported to / imported from the grid (≥ 0) |
| `huawei_home_consumption_watts` | home load, derived as `PV − battery − net grid` |
| `huawei_grid_net_watts` | signed net grid power (debugging aid) |
| `huawei_battery_net_watts` | signed battery power, +charge/−discharge |
| `huawei_battery_charge_watts` / `huawei_battery_discharge_watts` | the split, ≥ 0, for stacked graphs |
| `huawei_battery_soc_percent` | battery state of charge |
| `scraper_up` / `scraper_modbus_errors_total` / `scraper_last_poll_timestamp_seconds` | poller health |
| `scraper_poll_duration_seconds` / `_mean` / `_max` | the last poll cycle's duration and its running mean/maximum |
| `scraper_cache_device_up` / `scraper_cache_age_seconds` / `scraper_cache_uptime_seconds` | modbus-cache diagnostics, **auto-detected**: exported only when the polled endpoint serves the cache's diag block. `device_up 0` / a growing age mean the device is down **behind the cache** |

Sign conventions and sanity caps:

- The grid register value is split into export/import by sign — by default
  **positive = export**; set `--grid-positive-import` if your device reports
  the opposite.
- Huawei power registers already report **watts** (their gain convention
  divides raw by 1000 to get kW); the decode — type and gain — comes from
  the device profile's per-entry `scale` alone.
- Caps are on by default: `--max-kwp 6` (6 kWp array) and `--max-grid-kw 12`
  (12 kW power line); the caps assume `max-kwp ≤ max-grid-kw` (a startup
  warning fires otherwise). A reading above a cap logs an error and serves
  **HTTP 503** until a good poll.
- **Negative PV readings always trigger the error** regardless of the cap
  settings — a negative inverter input would corrupt the derived home load.

## Alerting

The family's **alert rules pack** lives at
[`alerts/`](../../extras/alerts/README.md) — one rule file per watched exporter;
this exporter's half is [`alerts/scraper.yml`](../../extras/alerts/scraper.yml),
the cache's half (`alerts/cache.yml`) ships with the cache package. The
pack is the audit vocabulary's detection half (docs/SECURITY.md F16): every
alert names the audit events and the log lines it correlates with, so a
fired page tells the operator where the trail lives. Two groups, one per
exporter:

| Alert | Fires when | The trail says |
|---|---|---|
| `ScraperPollDown` | `scraper_up == 0` for 2m — the Modbus poll of the device is failing | the scraper log names the failure per cycle |
| `ScraperFreshnessGap` | the last successful poll is more than 120s behind — 12 lost cycles at the default 10s poll | the slow-dongle gauges tell a stall from an outage |
| `ScraperExceptionSpike` | `scraper_modbus_errors_total` grew by more than 30 in 10m — half the cycles failing at the default interval | the log names the Modbus exception code per failed poll |
| `CachePollDown` (the cache's `/metrics`) | `modbus_cache_poll_up == 0` for 2m | the cache serves its last known words; the uplink block counters show the failing block |
| `CacheAgeSpike` | the oldest cached word more than 300s old — reads succeed with stale data behind them | the `cache-ttl` budget is the knob |
| `CacheWriteRefusalBurst` | `modbus_cache_write_refused_total` grew by more than 3 in 5m — the write gate refusing in bursts | each refusal is a `WRITE-REFUSED` audit event (the client, the frame, the gate) |

The cache group stays silent until the cache's own `/metrics` endpoint is
scraped (an absent series never fires); the exporter's diag block
(`scraper_cache_device_up` / `scraper_cache_age_seconds`) mirrors two of
its shapes for setups that do not scrape the cache. The exporter's own
death (the scrape failing) is the collector's stock `up{job}` hygiene, not
this pack.

Wire-in: the demo image bakes the pack (`docker/prometheus.yml` sets
`rule_files:`); a NixOS Prometheus points `services.prometheus.ruleFiles`
at the packaged copy (`share/alerts.yml`, see
[nixos/README.md](../../nixos/README.md)); an external collector copies the file and
lists it under its own `rule_files:`. Thresholds assume the default 10 s
poll interval — tune them to yours.

## Device profile

*Where* the primary values live comes from a **device profile** — the same
shared schema the [fake inverter](../inverter/README.md) serves and the
[cache](../cache/README.md) polls; the shipped profiles live in the suite's
[`shared/profiles/`](../../shared/profiles/) data dir (`sun2000.json` by default); the
format is documented in [shared/profiles/README.md](../../shared/profiles/README.md).
Resolution: `--modbus-profile` flag, env `MODBUS_PROFILE`, config `set modbus profile`,
then the bundled copy; re-read on `SIGHUP`. The live control surface swaps
it at runtime: `set modbus profile <file-or-name>` loads the new map,
rebuilds the metric sources and rolls back cleanly when the profile lacks
the registers the power math depends on.

WHICH entries feed the metrics comes from **`metrics.json`** — the spec,
keyed by the exported metric name directly. An entry carries either a
**`profile`** field naming the device-profile register it is read from
(its `type`/`scale` drive the decode) or an **`expr`** — a computed metric
(`{expr, when?, help, type?}`) evaluated per poll over the declared
**inputs**. The grammar is a strict stdlib-safe whitelist (numbers, the
inputs, arithmetic, comparisons, the ternary, `abs`/`min`/`max`/`round`;
one compute metric cannot feed another); an unavailable input, a division
by zero or a non-finite result keeps the metric absent for that poll.

The spec is **sectioned** — `inputs` (the declared expression vocabulary),
`metrics` (the tree above), `scraper` (the exporter's own observability
specs, shipped separately in `apps/scraper/lib/metrics.json` and merged in over
the configured spec — a custom `--metrics-spec` only needs the sections it
cares about). The four **canonical** entries — the power math's inputs
(`pv_generation_watts`, `grid_net_watts`, `battery_net_watts`,
`battery_soc_percent`) — are built-in: always declared, always bound,
always fetched. Every profile-bound metric beyond them is read once per
poll, softly: a rejected read keeps its metric absent instead of failing
the poll. Metric names, help texts and types are loaded at startup from the
packaged `metrics.json` (the lib dir's default; a checkout resolves the
`apps/scraper/metrics.json` → `examples/` dev symlink) — point
`--metrics-spec` elsewhere (or `set metrics spec`) to rename metrics or
reword `# HELP` lines without touching the code; a missing or corrupt
spec fails cleanly at startup (one-line error, exit 1).
`show inputs` / `show inputs-metrics` (ctl/cli) render the declared inputs
and the exported metrics.

```
ok inputs
batt     [battery_net_watts]    Net battery power in watts (positive …
pv       [pv_generation_watts]  PV input power in watts (the …
```

## Battery

The energy balance always carries the battery term (battery support is
always on — the flag retired):

```
home = pv − batt − grid
```

Battery registers (defaults follow the same Huawei convention as the PV
register — they come from the device profile's `battery-power` and
`battery-soc` entries): **37001** battery power (I32 W, **positive =
charging**), **37004** state of charge (U16, percent×10). Charging midday
surplus reduces the home value; evening discharge covers the home load even
with PV at 0. The consistency checks adapt: exported power may exceed the
PV cap by the battery discharge (a battery feeding the grid is
legitimate), and a derived `home < 0` is rejected as inconsistent. A
device profile without the battery registers keeps the battery metrics
absent. The fake inverter emulates the battery for testing:
`python3 apps/inverter/bin/modbus-fake-inverter.py`.

## Logging and audit trail

Logging is `logging`-based with **UTC timestamps by default**
(`--local-time` switches): one startup line with the effective settings,
reachability changes and reloads at INFO/WARNING (every poll at DEBUG).
HTTP requests are quiet by default; **`--log-access`** logs every request
at INFO as an audit trail of who scraped what when. **Rejected requests
are always audited** regardless. Handled connection problems always log a
single line — the suite enforces that **no scenario produces a
traceback**. Under systemd (`JOURNAL_STREAM` set) log lines omit their own
timestamp — journald adds one.

The control commands (with their wire macs), the auth failures, the
reloads and the shutdowns land in the **SCR audit trail** (`--audit-log`,
the XDG state home by default — `dev/gates/audit_verify.py` walks it like
the others). `--audit-forward` mirrors every line — the per-writer
hash chain included — onward: `syslog` (the local socket auto-scan),
`syslog:/path` (an explicit socket), `udp://host[:514]` (RFC5426,
best-effort) or `tcp://host[:514]` (RFC6587 framing) — the **off-box
copy** (the F10 answer): a scheduled search at the collector can
chain-verify the extracted prefix/chain fields and alert on a break.
The remote envelope rides `--audit-forward-format` (`rfc5424`, the
default, or `cef` — the local forms keep the verbatim send). A send
failure notes once and the next event re-arms. `--audit-log none` turns
the local file off: with a forward spelled that is the **remote-only
mode** (the collector is the sole holder, the chain reseeds at GENESIS
per run), without one the audit is disabled (the state
`--no-audit-log` spells). Every line names its writer daemon in
`instance=<id>` — the control port when `--audit-instance` is unset
(unique per host by construction), the override when spelled; keep an
override unique among everything that shares one collector (the native
line and CEF carry no hostname) — the chain groups by the
(application, writer, instance) triple.

## Test inverter

The fake inverter lives in its own subproject:
[inverter/](../inverter/README.md) — a Modbus TCP server with day/static
demo values, battery + meter simulation, a runtime control server and
chaos injection. Both regression suites start it automatically.

## Security

The endpoint exposes **production values, not telemetry** — a week of it
is a home-occupancy profile (the privacy note, F15): the bearer token
mandatory beyond loopback (F13), the localhost bind by default, the
endpoint internal. The full story is
[docs/SECURITY.md](../../docs/SECURITY.md).

## Testing

Two standalone suites live in the suite root
[`dev/suites/`](../../dev/suites/) —
stdlib only, each starts its own fake inverter + exporters on scratch
ports and cleans up after itself:

```bash
dev/battery/battery.py scraper        # the scraper profile: the regtest, the fuzz, the
                                #   audit chain (the suites refuse without the
                                #   runner's PV_RUN_DIR)
```

Every scenario must end with the exporter serving correct metrics and
**zero tracebacks** in the logs.

## Source layout

```
apps/scraper/
├── bin/
│   ├── modbus-scraper.py  # CLI, logging setup, signal handling, the control wiring
│   └── modbus-scraper-cli.py     # console-style control session (a symlink to the family dispatcher, ../../pvsuite-cli.py)
├── examples/
│   ├── modbus-scraper.conf  # sample config in the set grammar
│   └── metrics.json         # the phase rows' + the compute expressions' specs
├── schema/
│   └── metrics.schema.json  # the metrics spec's JSON Schema (draft 2020-12)
└── lib/
    ├── defaults.json      # the static constants: diagnostics block, log levels (the protocol
    ├── metrics.json       # the built-in inputs + the four canonical metrics + the scraper_* specs
    ├── statics.py         #   limits live in shared/suite/protocol.json)
    ├── protocol.py        # Modbus TCP client (hardened framing)
    ├── config.py          # settings resolution + validation
    ├── metrics.py         # metrics.json loader
    ├── expr.py            # the compute expressions' evaluator (the derived metrics)
    ├── poller.py          # poll loop + sanity checks + cache diagnostics
    ├── server.py          # Prometheus exposition endpoint (auth, limits)
    ├── control.py         # JSON-lines control server (the cache's shape, mirrored)
    ├── options.json       # the knob registry
    ├── options.py         # its loader: the Option rows, the control-grammar vocabulary
    └── man.py             # the generated man pages' prose (common/render/manpage.py renders)
```

## License

The scraper (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
