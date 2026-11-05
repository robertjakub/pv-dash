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
python3 scrape/bin/modbus_scraper.py --host 192.168.1.100
curl http://localhost:9350/metrics
```

By default the exporter **binds to 127.0.0.1:9350** (loopback only) — pass
`--listen 0.0.0.0:9350` when Prometheus scrapes from another host.
**Beyond loopback a token is mandatory**: a non-loopback listen without
`--auth-token`/`--auth-token-file` **refuses to start** (the audit's F13 —
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
(ini `auth_token`, env `SCRAPER_AUTH_TOKEN`) to require
`Authorization: Bearer <token>` on every request — anything else gets `401`
with a `WWW-Authenticate: Bearer` challenge. Keep the token out of the
world-readable Nix store with **`--auth-token-file`** (NixOS: `authTokenFile`) —
the file is re-read on every SIGHUP, so rotation is `rewrite file` +
`systemctl reload`.

> **The flag lands in `ps`.** A token passed as `--auth-token <secret>` is
> visible on the process command line — every local user can read it in
> `ps` output or `/proc/*/cmdline` (the audit's F9). Prefer
> **`--auth-token-file`** — the file must be **owner-only (`0600`)**;
> group/world-accessible token files refuse to start (F12) — or the
> `SCRAPER_AUTH_TOKEN` env var. The flag form is for quick tests.

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

| Metric | Meaning |
|---|---|
| `huawei_pv_generation_watts` | PV (inverter input) power |
| `huawei_grid_export_watts` | power exported to the grid (≥ 0) |
| `huawei_grid_import_watts` | power imported from the grid (≥ 0) |
| `huawei_home_consumption_watts` | home load, derived as `PV − net grid` (− battery when enabled) |
| `huawei_grid_net_watts` | signed net grid power (debugging aid) |
| `huawei_up` | 1 if the last poll succeeded |
| `huawei_modbus_errors_total` / `huawei_last_poll_timestamp_seconds` | poller health |
| `huawei_battery` | 1 if battery support is enabled (always exported); the dashboard treats 0 / missing as "no battery" and dims its battery node |
| `huawei_battery_net_watts` | signed battery power, +charge/−discharge (`--battery` only) |
| `huawei_battery_charge_watts` / `huawei_battery_discharge_watts` | the split, ≥ 0, for stacked graphs (`--battery` only) |
| `huawei_battery_soc_percent` | battery state of charge (`--battery` only) |
| `huawei_cache_device_up` / `huawei_cache_age_seconds` / `huawei_cache_uptime_seconds` | modbus-cache diagnostics, **auto-detected**: exported only when the polled endpoint serves the cache's diag block (registers 65000–65003, magic-checked). `device_up 0` / a growing `age_seconds` mean the device is down **behind the cache** while the cache keeps serving last-known values |

Sign conventions and sanity caps:

- The grid register value is split into export/import by sign — by default
  **positive = export**; set `--grid-positive-import` if your device reports
  the opposite.
- Huawei power registers already report **watts** (their gain convention
  divides raw by 1000 to get kW), so both scales default to 1;
  `--scale` / `--grid-scale` exist for devices that report raw kW.
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
register-backed metrics comes from **`metrics.json`** (the subproject root)
itself: an entry
carries a `profile` field naming the device-profile register it is read
from (`"huawei_pv_generation_watts": {"profile": "pv-power", ...}`); the
file is keyed by the exported metric name directly — no separate key layer.
Entries without a `profile` field are derived by the poller (home,
export/import split, ...). Each bound entry's `type`/`scale` drive the
decode — a `scale: 1` SoC is read as plain percent, a `scale: 10` one as
percent×10. A `profile` field pointing at a register the device profile
does not define leaves the metric absent (logged at startup). Profile resolution: `--profile`
flag, env `SCRAPER_PROFILE`, ini `profile`, then the bundled copy; re-read
on `SIGHUP`. The explicit register flags (`--pv-register`,
`--grid-register`, `--battery-register`, `--battery-soc-register`,
`--scale`, `--grid-scale`) override the profile when set.

Metric names, help texts and types live in **`scrape/metrics.json`**
next to the script and are loaded at startup — edit it to rename metrics or
reword `# HELP` lines without touching the code. A missing or corrupt spec
fails cleanly at startup (one-line error, exit 1), never a traceback.

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`modbus-cache`:

1. CLI flags (`--host`, `--listen`, …)
2. Environment variables — same names prefixed: `SCRAPER_CONFIG`,
   `SCRAPER_METRICS_SPEC`, `SCRAPER_HOST`,
   `SCRAPER_MODBUS_PORT`, `SCRAPER_UNIT`, `SCRAPER_MODBUS_OFFSET`,
   `SCRAPER_TIMEOUT`, `SCRAPER_PV_REGISTER`, `SCRAPER_GRID_REGISTER`,
   `SCRAPER_SCALE`, `SCRAPER_GRID_SCALE`, `SCRAPER_MAX_KWP`, `SCRAPER_MAX_GRID_KW`,
   `SCRAPER_BATTERY`, `SCRAPER_BATTERY_REGISTER`, `SCRAPER_BATTERY_SOC_REGISTER`,
   `SCRAPER_GRID_POSITIVE_IMPORT`, `SCRAPER_LISTEN`,
   `SCRAPER_INTERVAL`, `SCRAPER_LOCAL_TIME`, `SCRAPER_LOG_ACCESS`,
   `SCRAPER_LOG_LEVEL`, `SCRAPER_AUTH_TOKEN`, `SCRAPER_AUTH_TOKEN_FILE`,
   `SCRAPER_MAX_CLIENTS`, `SCRAPER_CLIENT_TIMEOUT`
3. Config file (snake_case keys, `[scraper]` section) — `--config` picks the
   file (default: `$SCRAPER_CONFIG`, then `scraper.ini` next to the script —
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

`scrape/scraper.ini` is a sample with the defaults:

```ini
[scraper]
host = 127.0.0.1
modbus_port = 5502
unit = 1
modbus_offset = 0
timeout = 3
pv_register = 32064
grid_register = 37113
scale = 1
grid_scale = 1
max_kwp = 6
max_grid_kw = 12
battery = false
battery_register = 37001
battery_soc_register = 37004
grid_positive_import = false
listen = 127.0.0.1:9350
interval = 10
max_clients = 64
client_timeout = 300
max_conn_per_ip = 0
log_level = INFO
```

## Runtime control (signals)

| Signal | Effect |
|---|---|
| `SIGHUP` | **Reload the configuration** without dropping the exporter: poll interval, scales, caps, register addresses, battery flag, auth token (+ file re-read = rotation), client limits and the upstream address/port/unit/timeout take effect immediately (the Modbus socket reconnects on the next poll). An invalid value keeps the previous settings — the error is logged and the next `SIGHUP` retries. The listen address, log level and `metrics.json` need a restart. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown**: the exporter stops, and the shutdown logs a session summary (duration + poll-error count). |

```bash
kill -HUP  $(pgrep -f scraper.py)   # reload the config
```

### The control server

The scraper runs the family's JSON-lines control server — **by default on
the unix socket `/tmp/modbus-scraper-<listen-port>.socket`** (`0` switches
it off, a TCP port number binds `127.0.0.1:PORT` instead, the socket path
is just a path). Talk to it with **`scraper_ctl`** (one-shot / batch) or
**`scraper_cli`** (the console session):

```bash
python3 scrape/bin/scraper_ctl.py show status
printf 'set interval 5\npoll now\n' | python3 scrape/bin/scraper_ctl.py
python3 scrape/bin/scraper_cli.py            # TAB completes, ? lists
```

Commands: `set`/`unset` over the live settings (**`interval`**,
**`timeout`**, **`max-clients`**, **`client-timeout`**,
**`max-conn-per-ip`**, **`log-access`**, **`log-level`** — `show settings`
lists them one `key=value` per line, `*` = live-overridden),
`show status` (the key=value report), `show connections` (the live HTTP
clients of /metrics), `poll now` (the loop wakes immediately), `request
reload` (the SIGHUP path — the token file re-reads, so the bearer token
rotates too), `restart` (the Modbus session drops; the next poll
reconnects), `inspect`, `show version`, `shutdown`.

A **TCP control port refuses to start without a token** (the audit's F5 —
the same rule as the cache): `--control-token`/`--control-token-file`
require the token handshake (`{"cmd": "auth", "token": ...}`) on the first
frame; over the unix socket a kernel-vouched peer (root, the daemon's own
user or `--control-trust-uids` — `SO_PEERCRED`) skips the handshake.
**With a token configured the wire is signed**: every command and reply
carries the **full sha256 HMAC of its payload, keyed by the token** —
a token-holding client verifies nothing was injected or altered in flight,
and over TCP the signed commands are mandatory (the same wire the cache
and the fake speak). The control commands (with their wire macs), the auth
failures, the reloads and the shutdowns land in the **SCR audit trail**
(`--audit-log`, the XDG state home by default — `scripts/audit_verify.py`
walks it like the others).

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
| `--config` | `$SCRAPER_CONFIG`, then `scraper.ini` next to the script, then the subproject root's | config file path |
| `--metrics-spec` | `$SCRAPER_METRICS_SPEC` or the bundled `metrics.json` | metrics spec JSON: metric name → {help, type, profile?} |
| `--host` | `127.0.0.1` | inverter/dongle Modbus TCP address |
| `--modbus-port` | `5502` | Modbus TCP port |
| `--unit` | `1` | Modbus unit id |
| `--modbus-offset` | `0` | added to register addresses (set `-1` for gateways that need 0-based addressing) |
| `--pv-register` | `32064` | signed 32-bit PV input power (I32, high word first) |
| `--grid-register` | `37113` | signed 32-bit grid/active power (positive = feed-in) |
| `--scale` | `1` | multiplier for the PV register raw value (raw is already W; set `1000` for kW devices) |
| `--grid-scale` | `1` | multiplier for the grid register raw value (W; set `1000` if your device reports kW) |
| `--max-kwp` | `6` | PV input power check against the array size: above `max-kwp × 1000` W → HTTP 503 + error log; `0` = off. Negative PV and export above the PV cap always error |
| `--max-grid-kw` | `12` | power line grid exchange check: \|grid power\| above `max-grid-kw × 1000` W (either direction) → HTTP 503 + error log; `0` = off |
| `--battery` | off | enable battery support: battery term in the home derivation + battery metrics |
| `--battery-register` | `37001` | battery power register (I32 W, positive = charging); used when `--battery` is set |
| `--battery-soc-register` | `37004` | battery state of charge (U16, percent×10); used when `--battery` is set |
| `--grid-positive-import` | off | grid register positive means import |
| `--timeout` | `3` | Modbus connect/read timeout, seconds |
| `--listen` | `127.0.0.1:9350` | exporter bind address `HOST:PORT` (loopback by default) |
| `--interval` | `10` | seconds between Modbus polls |
| `--log-level` | `INFO` | `DEBUG` logs every poll |
| `--log-access` | off | audit log: every HTTP request at INFO (client, path, status, size) |
| `--auth-token` | disabled | require `Authorization: Bearer <token>` on every request (`401` + `WWW-Authenticate` otherwise; token compared timing-safe) |
| `--auth-token-file` | disabled | read the bearer token from a file instead (single line, trimmed; **re-read on every SIGHUP** — rotate by rewriting the file and reloading; **owner-only `0600`** — a group/world-accessible token file refuses to start, F12); mutually exclusive with `--auth-token` |
| `--control-port` | `/tmp/modbus-scraper-<listen-port>.socket` | the JSON-lines control server target (unix socket path or TCP port on 127.0.0.1), `0` = off |
| `--control-token` | off | require the token auth handshake on control connections (the clients take `--control-token` / `SCRAPER_CONTROL_TOKEN`); a TCP control port refuses to start without one (F5) |
| `--control-token-file` | off | the control token from a file (the first line; a key file or a systemd `LoadCredential`, **owner-only `0600`** — a group/world-accessible token file refuses to start, F12), instead of `--control-token`; giving both is an error |
| `--control-trust-uids` | none | extra peer uids the unix control socket trusts without the token (`SO_PEERCRED`): comma-separated — root and the daemon's own user are always trusted (env `SCRAPER_CONTROL_TRUST_UIDS`) |
| `--audit-log` | the XDG state home | the SCR audit trail: a file path or `-` for stdout (the docker/journald way) |
| `--audit-max-mb` / `--audit-files` / `--no-audit-log` | `10` / `3` / off | the audit trail's rotation and the off switch |
| `--man` | off | print the generated man page (roff) to stdout and exit (`modbus-scraper --man \| man -l -`) |
| `--max-clients` | `64` | cap concurrent HTTP clients; overflow gets an immediate `503 # rate limited` (0 = unlimited) |
| `--client-timeout` | `300` | kick idle keep-alive clients after this many seconds (0 = off) |
| `--max-conn-per-ip` | `0` | cap concurrent HTTP connections from one peer IP; overflow gets an immediate `503 # rate limited` (0 = no per-IP limit) |
| `--local-time` | UTC | log timestamps in the system time zone |
| `--dry-run` | off | validate the config, print the effective settings and exit (`0` = valid, `1` = invalid, `2` = CLI misuse) |

Register defaults follow Huawei's official *Solar Inverter Modbus Interface
Definitions* (Issue 04, 2023-01-10):

- **32064** — Input power, I32. Unit kW with gain 1000, i.e. raw values are watts.
- **37113** — [Power meter] Active power, I32, `> 0` = feed-in. Populated by
  the connected power meter (DTSU666 etc.); without a meter the inverter
  alone cannot report grid power.
- Older **20200520** protocol: input power at **32089**, meter power at
  **37258** — pass `--pv-register 32089 --grid-register 37258` there.
- Unit quirk: the inverter's `[Power meter collection]` copy of 37113 has
  been observed reporting **watts** (gain 1) while the meter-section table
  says kW (gain 1000). The defaults assume watts (`--grid-scale 1`); if
  grid power looks 1000× off the other way, pass `--grid-scale 1000`.
- With a battery the derived home load is wrong while the battery
  charges/discharges — point the dashboard's `load` metric at a real meter
  register/exporter instead.

## Test inverter

The fake inverter lives in its own subproject: [inverter/](../inverter/README.md) — a Modbus TCP server with day/static demo values, battery + meter simulation, a runtime control server (`set`/`show` values, chaos injection) and the `fake_ctl` CLI. Both regression suites start it automatically.

## Battery

**Experimental — so far verified only against simulated data** (fake inverter /
mock Prometheus), not against real hardware.

When a battery is present, enable support with `--battery` (env
`SCRAPER_BATTERY`, ini `battery = true`). The energy balance gains a battery
term and the home load derivation becomes:

```
home = pv − batt − grid      (without battery: home = pv − grid)
```

Battery registers (defaults follow the same Huawei convention as
`--pv-register`):

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
`python3 inverter/bin/fake_inverter.py --battery`.

## Nix

```bash
nix run .#modbus-scraper -- --host 192.168.1.100
```

NixOS module (same flake, service runs with a dynamic user and systemd
hardening); the package installs the man page too (`man/modbus-scraper.1`
under `share/man/man1/`):

```nix
services.modbus-scraper = {
  enable = true;
  inverterHost = "192.168.1.100";
  listenHost = "0.0.0.0";        # only if Prometheus runs on another host
  listenPort = 9350;
  battery = true;               # once a battery is installed
};
```

Options: `enable`, `package`, `inverterHost`, `inverterPort` (502), `unitId`,
`modbusOffset`, `pvRegister`, `gridRegister`, `scale`, `gridScale`, `maxKwp`,
`maxGridKw`, `battery`, `batteryRegister`, `batterySocRegister`,
`gridPositiveImport`, `timeout`, `interval`, `listenHost`, `listenPort`,
`logLevel`, `localTime`, `logAccess`, `maxClients`, `clientTimeout`, `authToken`, `authTokenFile`, `openFirewall`.

The module renders the **config INI into the store** and runs the service
with `--config`. A `nixos-rebuild switch` applies changes with
`systemctl reload` (SIGHUP): interval, caps, registers, battery flag, auth
token and the upstream address are picked up live. Changes to
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
scrape/
├── bin/
│   ├── modbus_scraper.py  # CLI, logging setup, signal handling, the control wiring
│   ├── scraper_ctl.py     # one-shot / batch control client
│   └── scraper_cli.py     # console-style control session
├── scraper.ini            # sample config (the default --config target)
├── metrics.json           # metric names / HELP / TYPE specs
└── lib/
    ├── static.json        # the static constants: protocol limits, diagnostics block, defaults
    ├── statics.py         # its loader (the STATIC dict + the named aliases)
    ├── protocol.py        # Modbus TCP client (hardened framing)
    ├── config.py          # settings resolution + validation
    ├── metrics.py         # metrics.json loader
    ├── poller.py          # poll loop + sanity checks + cache diagnostics
    ├── server.py          # Prometheus exposition endpoint (auth, limits)
    ├── control.py         # JSON-lines control server (the cache's shape, mirrored)
    ├── settings.py        # the live-settings registry (the control grammar's single source)
    ├── man.py             # the generated man pages' prose (common/manpage.py renders)
    └── version.py         # the suite version
```

## License

The scraper (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
