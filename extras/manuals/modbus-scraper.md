# modbus-scraper

> **Experimental — work in progress.** Verified only against simulated
> data (the fake inverter, a mock Prometheus), not against real
> hardware.

`modbus-scraper` is the family's Prometheus exporter: a
dependency-free (Python stdlib only) Modbus TCP poller that reads a PV
inverter on a timer and serves the power metrics the dashboard expects
— PV generation, the grid exchange, the home consumption, the battery
— plus the exporter's health gauges, in the Prometheus text format at
`/metrics`. The binaries are `apps/scraper/bin/modbus-scraper.py` (the
daemon) and `apps/scraper/bin/modbus-scraper-cli.py` (the control
client). The bundled device profiles cover the Huawei SUN2000 and the
Deye hybrids; the tool polls the inverter directly or through the
[modbus-cache](../../apps/cache/README.md) proxy.

The shape is one loop and two surfaces. A poll thread wakes every
`--modbus-interval` seconds, walks the device profile's register map
in as few Modbus reads as the block planner can merge, sanity-checks
the readings, and stores the values. The exposition serves the latest
values to Prometheus; the JSON-lines control server — talked to with
`modbus-scraper-cli` — shows and steers the running daemon: the live
settings, an immediate poll, the config reload, the graceful
shutdown. Every setting resolves flag over env over config script
over built-in default; `SIGHUP` re-reads the config file without
dropping the exporter. The full reference is the daemon's `--help`,
the man pages
([apps/scraper/man/modbus-scraper.1](../../apps/scraper/man/modbus-scraper.1),
[apps/scraper/man/modbus-scraper-cli.1](../../apps/scraper/man/modbus-scraper-cli.1))
and the knob registry
[apps/scraper/lib/options.json](../../apps/scraper/lib/options.json).

## The family

```text
  the device (inverter / SDongle / EMMA)     modbus-replay (a recorded
        |                                    stand-in for the device)
        |  Modbus TCP :502, unit id 1            |
        +------------------+-------------------+
                           v
                 modbus-cache :15502
                           v
                 modbus-scraper :9350
                           v
                       Prometheus
                           v
                      the dashboard
```

The scraper sits at the consuming end of the Modbus chain: deployed,
it polls the [modbus-cache](../../apps/cache/README.md) — the proxy
that fans one device connection out to many readers, speaks the
suite's Modbus auth and carries the write ACL — not the device
directly. The cache is detected automatically from its synthesized
diagnostics block and adds the cache-health gauges (see
[Metrics](#metrics)). Every hop is optional: the exporter points at a
bare device just as happily (`--upstream 192.168.1.100:502`), and
`modbus-replay` stands in for the device with recorded traffic.

## How it works

- **The poll loop** — the planner (`common/modbus/blocks.py`) merges
  the profile's source ranges into as few Modbus block reads as
  `--modbus-merge-gap` allows; the `--modbus-read-delay` paces
  between blocks; a failed block splits to its leaves so one bad
  register cannot starve its neighbors; the ok replies slice back
  into the sources. The four hard sources — `pv-power`,
  `grid-power`, `battery-power`, `battery-soc` — are always fetched.
  The per-block tally feeds the `show uplink` report.
- **The device profile** — one JSON register table from
  `shared/profiles/` (`sun2000`, `sun2000_full`, the Deye hybrids),
  the same home the fake inverter serves from and the cache fetches
  from. A bare name resolves against the shared directory; a path
  passes through.
- **The metrics spec** — the sectioned JSON (`--metrics-spec`): the
  declared `inputs` vocabulary, the `metrics` tree (each entry
  register-fed via `profile` or derived via `expr` with an optional
  `when` presence gate) and the fixed `scraper` block. The spec
  merges in memory over the built-in
  [apps/scraper/lib/metrics.json](../../apps/scraper/lib/metrics.json).
  Expressions compile once at startup (`apps/scraper/lib/expr.py`) —
  a whitelist: arithmetic, comparisons, and/or/not, the ternary,
  `abs`/`min`/`max`/`round`, nothing else.
- **The `/metrics` page** — the latest values in the Prometheus text
  format, with the health gauges. A poll that fails the sanity caps
  (a negative PV reading, an array larger than `--max-kwp`, a grid
  line beyond `--max-grid-kw`, a negative home balance) marks the
  exposition `503` — the sensors are suspect, not the poller — and
  names the register in the log.

## Installing

### From the tree

Stdlib only — no pip, no venv:

```bash
python3 apps/scraper/bin/modbus-scraper.py --help
python3 apps/scraper/bin/modbus-scraper.py --man  # the generated man page
python3 apps/scraper/bin/modbus-scraper-cli.py --help
```

In a source checkout the dev wrapper `apps/scraper/dev` runs the
daemon against the shipped samples (the example config and metrics
spec, the audit trail on stdout); a checkout lacks the packaged-root
default spec, so pass `--metrics-spec` or use the wrapper.

### Nix / NixOS

The flake exports the package, the app and the NixOS module:

```bash
nix run .#modbus-scraper -- --upstream 192.168.1.100:502
```

The service module
([nixos/modules/modbus-scraper.nix](../../nixos/modules/modbus-scraper.nix))
declares `services.modbus-scraper`; the package recipe is
`nixos/pkgs/modbus-scraper/package.nix`. The options and the sandbox
posture are under [Deployment](#deployment); the packaging story is
[nixos/README.md](../../nixos/README.md).

### Docker

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-scraper -t modbus-scraper \
    --build-context shared=../shared \
    --build-context scripts=../docker --build-context common=../common \
    --build-context cli=../apps ../apps/scraper
# or: docker compose up -d modbus-scraper
```

The image runs as the unprivileged user `pvsuite`, binds
`0.0.0.0:9350` by its `CMD`, defaults `UPSTREAM` to the compose
stack's cache peer (`modbus-cache:15502`) and seeds `/config` with
the metrics spec on start — the volume copy is the one to edit. The
health check asks the control socket: `modbus-scraper-cli ping`.

## Quick start

A minimal run against a cache that is already up:

```bash
# start the exporter pointed at the cache's Modbus listener
python3 apps/scraper/bin/modbus-scraper.py --upstream 127.0.0.1:15502

# scrape the exposition (another terminal)
curl -s http://127.0.0.1:9350/metrics | grep huawei_pv_generation_watts
```

The second command shows a gauge:

```text
# HELP huawei_pv_generation_watts Current PV (inverter input) power in watts.
# TYPE huawei_pv_generation_watts gauge
huawei_pv_generation_watts 3480.0
```

By default the exporter binds `127.0.0.1:9350` — loopback only, no
token needed. Serving beyond loopback is a deliberate step: a
token-less non-loopback bind refuses to start, so a LAN-visible
deployment spells `--listen 0.0.0.0:9350 --auth-token file:/run/...`.
`--dry-run` validates a configuration and prints the effective
settings without binding or connecting — exit `0` valid, `1`
invalid, `2` misuse.

## Configuration

### How a setting resolves

Every knob resolves through the same ladder — the first source that
spells a value wins: the flag (`--upstream`), then the env twin (a
bare upper-snake name, no tool prefix: `UPSTREAM`, `LISTEN`,
`MODBUS_INTERVAL`, `CONTROL_TOKEN`, ...), then the config script
(`--config`), then the registry row's built-in default.

The config file speaks the control grammar: every line a
`set <name> <value>`, every comment a `#` comment — a runnable
script that pipes through the ctl clients unchanged, and
`show config` re-renders the running daemon's effective
configuration in the same grammar. The knob names are the live paths
as words, the same spelling the console takes. Without `--config`
the daemon looks for `modbus-scraper.conf` next to the script, then
in the subproject root (`$CONFIG` overrides the search).

### The knobs

The registry lives in
[apps/scraper/lib/options.json](../../apps/scraper/lib/options.json);
the live path is the knob's name on the wire and in the config file.

| knob | flag | env | default | live | what it does |
|---|---|---|---|---|---|
| `modbus/upstream` | `--upstream` | `UPSTREAM` | `127.0.0.1:5502` | yes | the inverter Modbus TCP endpoint HOST:PORT (`:5502` = loopback) |
| `modbus/unit` | `--modbus-unit` | `MODBUS_UNIT` | `1` | yes | the Modbus unit id the session speaks |
| `modbus/offset` | `--modbus-offset` | `MODBUS_OFFSET` | `0` | yes | added to register addresses |
| `modbus/auth` | `--modbus-auth` | `MODBUS_AUTH` | `none` | yes | the auth scheme toward the device: `suite`, `waveshare` or `none` |
| `modbus/auth/key` | `--modbus-auth-key` | `MODBUS_AUTH_KEY` | — | refused | the key presented to the device — the suite handshake's shared key (min 16 characters) or the Waveshare connection password |
| `modbus/timeout` | `--modbus-timeout` | `MODBUS_TIMEOUT` | `3` | yes | Modbus connect/read timeout in seconds |
| `modbus/read-delay` | `--modbus-read-delay` | `MODBUS_READ_DELAY` | `0.05` | yes | seconds between consecutive device reads within a poll cycle |
| `modbus/merge-gap` | `--modbus-merge-gap` | `MODBUS_MERGE_GAP` | `8` | yes | max register gap when merging source ranges into block reads; the poll plan rebuilds |
| `modbus/profile` | `--modbus-profile` | `MODBUS_PROFILE` | `sun2000` | yes | device profile JSON; a bare name resolves in `shared/profiles/` |
| `modbus/interval` | `--modbus-interval` | `MODBUS_INTERVAL` | `10` | yes | seconds between polls |
| `modbus/caps/max-pv` | `--max-kwp` | `MAX_KWP` | `6` | yes | maximum PV array kWp (the sanity ceiling) |
| `modbus/caps/max-grid` | `--max-grid-kw` | `MAX_GRID_KW` | `12` | yes | maximum grid kW, either direction (the sanity ceiling) |
| `modbus/grid-positive-import` | `--grid-positive-import` | `GRID_POSITIVE_IMPORT` | `off` | yes | the grid register reads positive when importing |
| `metrics/filter` | `--metrics-spec` | `METRICS_SPEC` | the packaged `metrics.json` | yes | the metrics spec JSON, merged over the built-in |
| `metrics/prefix` | `--metrics-prefix` | `METRICS_PREFIX` | `huawei` | yes | the prefix on the profile- and compute-fed metric names |
| `metrics/acl` | `--metrics-acl` | `METRICS_ACL` | `any` | yes | who may connect to `/metrics` |
| `metrics/auth/token` | `--auth-token` | `AUTH_TOKEN` | — | refused | the `/metrics` bearer token; a non-loopback bind refuses to start without one |
| `metrics/limits/max-clients` | `--metrics-max-clients` | `METRICS_MAX_CLIENTS` | `64` | yes | concurrent `/metrics` clients; extras get an immediate 503, `0` = unlimited |
| `metrics/limits/timeout` | `--metrics-client-timeout` | `METRICS_CLIENT_TIMEOUT` | `300` | yes | seconds an idle `/metrics` client is kept, `0` = the built-in 5 s cap |
| `metrics/limits/max-conn-per-ip` | `--metrics-max-conn-per-ip` | `METRICS_MAX_CONN_PER_IP` | `0` | yes | concurrent `/metrics` connections from one peer IP, `0` = no limit |
| `system/listen` | `--listen` | `LISTEN` | `127.0.0.1:9350` | pending | the exporter's bind address |
| `system/local-time` | `--local-time` | `LOCAL_TIME` | `off` | yes | log timestamps in the system time zone instead of UTC |
| `system/log-access` | `--log-access` | `LOG_ACCESS` | `off` | yes | log every HTTP request at INFO |
| `system/log-level` | `--log-level` | `LOG_LEVEL` | `INFO` | yes | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `system/log-replies` | `--control-log-replies` | — | `off` | yes | DEBUG-log the full output of every control command |
| `control/port` | `--control-port` | `CTL` | the unix socket | yes | control target: a unix socket path or a TCP port on 127.0.0.1, `0` = off |
| `control/token` | `--control-token` | `CONTROL_TOKEN` | — | refused | the admin control token; a TCP control port refuses to start without one |
| `control/trust-uids` | `--control-trust-uids` | `CONTROL_TRUST_UIDS` | — | yes | extra peer uids the unix socket trusts without the token (SO_PEERCRED) |
| `control/socket-group` | `--control-socket-group` | `CONTROL_SOCKET_GROUP` | `off` | yes | chmod 0660 the unix control socket instead of 0600 |
| `control/ops/token` | `--control-ops-token` | `CONTROL_OPS_TOKEN` | — | refused | the second, read-only ops control token |
| `control/ops/verbs` | `--control-ops-verbs` | `CONTROL_OPS_VERBS` | `show` | yes | the ops role's verb policy, comma-separated |
| `audit/log-file` | `--audit-log` | `AUDIT_LOG` | the XDG state home | yes | the audit file: a path, `-` for stdout, `none` for no local file |
| `audit/forward` | `--audit-forward` | `AUDIT_FORWARD` | `none` | yes | also forward every line: `syslog`, `syslog:/path`, `udp://host[:514]`, `tcp://host[:514]` |
| `audit/forward/format` | `--audit-forward-format` | `AUDIT_FORWARD_FORMAT` | `rfc5424` | yes | the remote forward's envelope: `rfc5424` or `cef` |
| `audit/instance` | `--audit-instance` | `AUDIT_INSTANCE` | the control port | yes | the audit lines' `instance=<id>` word — which daemon wrote the line |
| `audit/rotate/max-size` | `--audit-max-mb` | `AUDIT_MAX_MB` | `10` | yes | rotate the audit log at this size in MB, `0` = off |
| `audit/rotate/daily` | `--audit-daily` | `AUDIT_DAILY` | `off` | yes | also rotate the audit log at UTC midnight |
| `audit/rotate/files` | `--audit-files` | `AUDIT_FILES` | `3` | yes | rotated audit backups to keep |
| `audit/disable` | `--no-audit-log` | `NO_AUDIT_LOG` | `off` | yes | disable the audit trail entirely |
| `dump/path` | `--dump-path` | `DUMP_PATH` | — | yes | the state dump file: the live setting overrides |
| `dump/key` | `--dump-key` | `DUMP_KEY` | — | refused | the key that seals the state dumps and the reload's state file |
| `dump/interval` | `--dump-interval` | `DUMP_INTERVAL` | `0` | yes | seconds between automatic state dumps, `0` = on request and shutdown |
| `dump/restore-on-start` | `--restore-on-start` | `RESTORE_ON_START` | `off` | pending | load the state dump when the daemon starts (needs `--dump-path`) |

The live column: `yes` — a `set` on the control wire applies at
once; `pending` — the value validates and records, applying at the
next restart; `refused` — a startup-only secret, the wire refuses
`set`/`clear` and `show` on it.

### The config file

The shipped example
([apps/scraper/examples/modbus-scraper.conf](../../apps/scraper/examples/modbus-scraper.conf))
is generated from the registry — all 43 knobs, every line commented
— so it doubles as the knob reference. An excerpt:

```conf
# the inverter Modbus endpoint
# set modbus upstream 127.0.0.1:5502

# no auth (the default)
# set modbus auth none

# a secret — pass it as file:<path>, an owner-only 0600 file
# startup-only: a change applies on restart
# set modbus auth key file:/run/credentials/modbus-scraper/modbus-auth-key

# seconds between polls of the upstream
# set modbus interval 10
```

Uncomment a line to override that knob's default. The file is a
generated artifact — edit the registry and re-run
`dev/generators/examples.py`, never the file itself. The docker
image copies the conf to `/pv-suite/scraper/modbus-scraper.conf`,
its default `--config` target.

### Secrets

Five knobs are secrets: the Modbus auth key, the control token, the
ops token, the metrics bearer token and the dump key. The rules:

- the value takes the `file:<path>` reference — the first line of an
  owner-only 0600 file (a systemd LoadCredential rides as
  `file:/run/credentials/...`);
- a secret value never renders back — `show config` prints
  `*** SECRET REMOVED ***` in its place, the parser refuses the
  placeholder, and `show <secret>` refuses outright;
- secrets are startup-only: pass them by flag, env or config file
  and restart to change them — the control wire refuses
  `set`/`clear`.

## Runtime control

Signals: `SIGHUP` re-reads the config file (and the auth token file,
the rotation path for a `file:<path>` bearer token) and applies what
is live — the same path as `request reload-config`; a broken config
keeps the previous settings. `SIGTERM`/`SIGINT` shut down
gracefully.

The knobs divide three ways on a running daemon. Live knobs apply at
once — `set modbus interval 5` re-paces the poll loop on the spot,
and the poll plan rebuilds when the read delay or the merge gap
moves. Restart-marked non-secrets (the listen address,
restore-on-start) validate and record a pending value that the next
restart applies. Startup-only secrets refuse the live change. The
worked sequence:

```text
$ modbus-scraper-cli set modbus interval 5  # the live set: the loop re-paces
$ modbus-scraper-cli show modbus interval   # show prints the bare value: 5
$ modbus-scraper-cli request poll now       # the poller wakes on the spot
$ modbus-scraper-cli request reload-config  # the SIGHUP path: config re-reads
$ modbus-scraper-cli show config            # the effective settings as a script
```

The state dump pairs with the live sets: with `--dump-path`
configured, `request dump` writes the current overrides (0600,
integrity-hashed, sealed when `--dump-key` is set), `request
restore` re-applies them, `--restore-on-start` loads them at start —
a restart serves last-known values instead of cold misses.

## The control plane

`modbus-scraper-cli` is one client with three invocation shapes:
one-shot words (`modbus-scraper-cli show uplink` — the raw reply
prints, exit `0` ok, `1` connection error, `2` misuse), a piped
batch (stdin lines run in order), and the interactive console (a
bare terminal): the prompt carries the connected port, TAB
completion and `?` work in every position, replies page through the
pager (`--page-size`/`CLI_PAGE_SIZE`, `0` turns it off), and
`shutdown` asks before it stops the scraper. When the connection
dies mid-session the console retries (`--reconnect` attempts,
`--reconnect-wait` seconds apart).

The verbs: `set`/`clear`/`show` (the settings and the reports),
`inspect` (one pretty dump), `ping`, `help`, `shutdown`, `quit`, and
the `request` family — `request poll now`, `request reload-config`
(the SIGHUP path), `request reload` (the whole-daemon restart that
keeps the sets: the overrides save to a state file, the process
re-execs, the fresh daemon re-applies them once), `request restart`
(drop the Modbus session; it reconnects on the next poll),
`request dump`/`request restore`. The `show` reports: `show config`,
`show knobs`, `show version`, `show connections` (the live HTTP
clients), `show uplink` (the inverter link — session counters, one
row per poll block), `show uplink-sources` (the register map: fc,
register, the range that fetches it, source), `show inputs`,
`show inputs-metrics`, `show metrics-acl-table`.

The wire is the family's JSON lines: one command per line,
`{"cmd": ...}` in, `{"status": "ok|fail|note|bye", "text": ...}`
out. The default control target is the unix socket
`/tmp/modbus-scraper-9350.socket` — the template follows the listen
port; `--control-port` spells an explicit socket path, a TCP port on
127.0.0.1, or `0` (off). Over the unix socket a trusted peer — root,
the daemon's own user, or a uid in `--control-trust-uids` — skips
the token (SO_PEERCRED). A TCP control port without an admin token
refuses to start; with a token configured the wire is HMAC-signed —
every command and reply carries the full sha256 of its payload keyed
by the token (`common/wire/wiresec.py`) — and over TCP the signed
commands are mandatory. The client authenticates with
`{"cmd": "auth", "token":...}` or passes `--control-token` (env
`CONTROL_TOKEN`). The second, ops token (`--control-ops-token`)
authenticates into its policy's verbs only — the default policy is
`show` (no `set`/`clear`, no `request poll now`, no reload, no
restart, no shutdown); the ops shift runs against the admin key and
both roles are audited.

## Access control

Three legs, each verifiable from the man page:

- **The `/metrics` endpoint.** The bearer token (`--auth-token`) is
  compared timing-safe and is mandatory beyond loopback — a
  token-less non-loopback bind refuses to start. On top of it the
  connect ACL (`--metrics-acl`) decides who may connect at all:
  `any` (the default), `none` (refuse everyone), comma-separated
  IPs/prefixes like `10.0.0.7,10.48.0.0/16`, or `file:<path>` — the
  standalone ip-prefix ACL file, the gate object `{"type":
  "ip-prefix", "rules": [{"type": "allow"|"deny", "prefix": ...}]}`
  where the last matching rule decides and a client no rule decides
  refuses. The check runs at accept — a client off the ACL is closed
  without a reply. `show metrics-acl-table` renders the rule chain.
- **The control plane.** Loopback-only over TCP with a mandatory
  admin token, or a 0600 unix socket whose trusted peers skip the
  token; the read-only ops role scopes its sessions to its policy's
  verbs. Both roles, the auth failures and the reloads land in the
  audit trail.
- **The Modbus leg.** `suite` proves the shared key (min 16
  characters) with a crypt handshake right after every connect — 52
  bytes: magic, fresh nonce, HMAC-SHA256 proof; the peer answers
  `OK` and plain Modbus follows, or `ERR` and the connection fails
  (the poller keeps retrying). `waveshare` sends the key as a
  Waveshare RS485-to-TCP gateway's connection password (raw ASCII,
  right after every connect; the gateway's `OK` opens the session).
  Empty auth is no auth at all — an open Modbus device behind
  network isolation is the deployment's own boundary, and the
  cache's front legs (the suite auth, the write ACL) are the
  hardened shape (see
  [docs/specs/ACL.md](../../docs/specs/ACL.md),
  [docs/SECURITY.md](../../docs/SECURITY.md)).

## Metrics

Two families share the exposition:

- **The fixed `scraper_*` gauges** — the exporter's own
  observability, the prefix never configurable. The shipped block:
  `scraper_up` (1 when the last Modbus poll succeeded),
  `scraper_modbus_errors_total` (failed or rejected polls since
  start), `scraper_last_poll_timestamp_seconds`,
  `scraper_poll_duration_seconds` with `_mean_seconds` and
  `_max_seconds`, and — when a cache is detected in front of the
  device — `scraper_cache_device_up`, `scraper_cache_age_seconds`,
  `scraper_cache_uptime_seconds`, fed by the cache's synthesized
  diagnostics block.
- **The profile- and compute-fed gauges** — named
  `<metrics-prefix>_<key>`, the prefix defaulting to `huawei` (so
  `huawei_pv_generation_watts`, `huawei_battery_soc_percent`, ...).
  The built-in profile-fed four ride the hard sources; the compute
  entries derive per poll: the shipped sample spec carries the three
  phase-voltage/current/power triples (register-fed) and the five
  classic expressions — `max(grid, 0.0)` for export, `max(-grid,
  0.0)` for import, `pv - batt - grid` for home consumption, and the
  battery charge/discharge split. A compute entry's `when` gate
  keeps the metric out of the exposition on a poll where the
  expression decides false or an input is absent — the metric stays
  absent for that cycle instead of lying.

The spec structure — `inputs` (the declared expression vocabulary:
the reserved four `pv`, `grid`, `batt`, `soc` plus the spec's
profile keys), `metrics` (one entry per metric), `scraper` (the keys
are the exported names) — is pinned by the JSON Schema
[apps/scraper/schema/metrics.schema.json](../../apps/scraper/schema/metrics.schema.json);
the loader (`apps/scraper/lib/metrics.py`) stays the strict word and
checks what a schema cannot. The shipped sample lives at
[apps/scraper/examples/metrics.json](../../apps/scraper/examples/metrics.json);
`show inputs` and `show inputs-metrics` report the merged result
from a running daemon.

Prometheus scrapes the page on its own interval — the demo stack's
scrape config is
[docker/prometheus.yml](../../docker/prometheus.yml). An idle client
is kicked at `--metrics-client-timeout`; clients past the caps get
an immediate `503` (rate-limited body) rather than a queue. A poll
that fails the sanity caps answers `503` too.

## The audit trail

The control commands with their roles, the auth failures, the
reloads and the shutdowns land in the hash-chained audit trail — the
family's SCR format, one line per event with the chain word linking
it to the last. The sink is `--audit-log`: a file path (the default
home is `~/.local/state/modbus-scraper/audit.log`), `-` for stdout
(the docker/journald way), or `none` — no local file, which with a
forward spelled is the remote-only mode. `--no-audit-log` disables
the trail entirely.

`--audit-forward` mirrors every line — the per-writer hash chain
included — off-box: `syslog` (the local socket auto-scan),
`syslog:/path` (an explicit socket), `udp://host[:514]` (RFC5426,
best-effort) or `tcp://host[:514]` (RFC6587 framing). A scheduled
search at the collector can chain-verify the extracted fields and
alert on a break. The remote envelope is `--audit-forward-format`:
`rfc5424` (the default) or `cef`; the local syslog forms keep the
verbatim send. Every line names its writer in `instance=<id>` — the
control port when `--audit-instance` is unset (unique per host by
construction), the override when spelled; make an override unique
among everything that shares one collector, the chain groups by it.
A send failure notes once and the next event re-arms.

Rotation: `--audit-max-mb` (default 10 MB), `--audit-daily` (also at
UTC midnight), `--audit-files` (backups kept, default 3). The chain
story and the remote-only GENESIS reseed are
[docs/history/AUDIT.md](../../docs/history/AUDIT.md).

## Tuning

- **The poll interval** — `--modbus-interval`, default 10 seconds; a
  live knob (`set modbus interval 5` re-paces the running loop).
- **The bus pacing** — `--modbus-read-delay` (default 0.05 s between
  consecutive device reads within a poll cycle, `0` = no delay) and
  `--modbus-merge-gap` (default 8 registers — the max gap when
  merging source ranges into block reads, `0` = read the ranges
  separately). Either set rebuilds the poll plan live.
- **The session** — `--modbus-timeout` (default 3 s connect/read
  timeout) and `--modbus-unit` for devices addressed off unit 1.
- **The exposition caps** — `--metrics-max-clients` (default 64
  concurrent clients; extras get an immediate 503, `0` = unlimited),
  `--metrics-max-conn-per-ip` (default `0`, no per-IP limit),
  `--metrics-client-timeout` (default 300 s idle kick, `0` = the
  built-in 5 s slowloris cap).
- **The sanity caps** — `--max-kwp` (default 6 kWp) and
  `--max-grid-kw` (default 12 kW either direction): the ceilings the
  polled readings must pass; a reading beyond one marks the
  exposition 503 and names the register in the log. Both are live
  knobs (`set modbus caps max-pv ...`).

## Deployment

The NixOS module `services.modbus-scraper` options: `enable` and
`package` (the flake default); `settings` — the daemon's environment
verbatim, every entry rendered as `NAME=value` into the unit's
EnvironmentFile, the keys the bare env twins (`UPSTREAM`, `LISTEN`,
`MODBUS_INTERVAL`, ...), the secret env names refused there (the env
file lands in the world-readable nix store, and secrets never do);
the five credential options — `modbusAuthKeyFile`,
`controlTokenFile`, `controlOpsTokenFile`, `authTokenFile`,
`dumpKeyFile` — absolute paths outside the store (a store path is
refused), mounted via systemd LoadCredential and read by the daemon
as `file:/run/credentials/modbus-scraper/<name>`. This is the
token-file story: the secret itself never enters the store or the
unit file — only the `file:` pointer does. `user`/`group`: `null`
keeps the systemd DynamicUser; a name switches to a static account
the module creates — the family's shared identity is `pvsuite`, one
owner across the daemons for the state dumps and the control
sockets. `openFirewall` opens the listen port (for a Prometheus on
another host; the module warns when the bind is still loopback).

The systemd posture: `ExecReload` is `kill -HUP` (the config
reload), `Restart = on-failure`, `UMask 0077`, and the full sandbox
— `ProtectSystem = strict` with explicit `ReadWritePaths` derived
from the audit and dump paths, `PrivateTmp`, no home, no devices, an
empty `CapabilityBoundingSet`, only the AF_UNIX + INET socket
families. The module warns when `settings.CTL` sits under `/tmp`
(PrivateTmp hides it from the CLI outside) and suggests a path under
`/run/modbus-scraper/` — the unit then creates the RuntimeDirectory.

The docker image (`docker/Dockerfile.modbus-scraper`) runs the
daemon as `pvsuite`. The entrypoint seeds `/config` on start — the
volume copy of `metrics.json` (`METRICS_SPEC` is pinned there) is
the one to edit; existing files stay. The bundled conf loads as the
default `--config` target; the per-tool env file overrides it knob
by knob: copy
[docker/env/modbus-scraper.env.example](../../docker/env/modbus-scraper.env.example)
(the generated example — 42 env twins, every line commented, the
sample value the image itself runs) to `env/modbus-scraper.env` (the
demo stack) or `env/modbus-scraper-production.env` (the prod stack).
A flag beats the env: `docker run ... modbus-scraper --upstream
10.0.0.2:15502` on top. The compose stacks pin the auth knobs the
env file cannot carry: `AUTH_TOKEN=file:/run/pv-secrets/metrics-token`
(the operator's bearer, a compose secret the entrypoint stages) and
`MODBUS_AUTH_KEY=file:/run/pv-secrets/modbus-auth` — the stack's
Modbus hops ship authenticated. The secrets staging and both
topologies are [docker/README.md](../../docker/README.md).

## Troubleshooting

- **The bind fails.** The daemon exits `1` with the reason on stderr
  — a taken port is the common one. `--dry-run` does not bind, so it
  cannot catch this; the failure is the exporter's own.
- **The upstream refuses or times out.** The poller keeps retrying:
  `scraper_up` drops to `0`, `scraper_modbus_errors_total` climbs,
  `scraper_last_poll_timestamp_seconds` ages. With `suite` or
  `waveshare` auth a failed handshake fails the connect like any
  other device fault — check the key (min 16 characters, the same
  key the peer holds) before the cabling. `show uplink` shows the
  per-block failures; `request restart` drops the session so the
  next poll reconnects fresh.
- **The exposition answers 503.** Two flavors: the caps
  rate-limited body (too many concurrent clients — raise
  `--metrics-max-clients`) and the sanity 503 (the readings failed
  the caps — the register is named in the log; fix the device or
  widen `--max-kwp`/`--max-grid-kw`).
- **The metrics spec fails to load.** The loader refuses at startup
  (a SystemExit): a `profile` register the device profile does not
  define, an `expr`/`when` the whitelist grammar refuses to compile,
  a reserved input left undeclared, a register bound twice.
  `--dry-run` runs the same load before anything binds — the
  pre-flight for every config and spec edit.

## Testing

The suites covering the tool live in `dev/suites/`:
[scrape-regtest.py](../../dev/suites/scrape-regtest.py) (the
regression suite — the poller, the exposition, the control plane)
and [scrape-fuzz.py](../../dev/suites/scrape-fuzz.py) (the fuzz
suite). The battery runs both beside the family gates
(`check-options`, `links-check`, `lint-gates`, `audit-chain`) in the
scraper profile:

```bash
python3 dev/battery/battery.py scraper            # the commit set (~6 min)
python3 dev/battery/battery.py scrape-regtest scrape-fuzz  # explicit suites
python3 dev/battery/battery.py --depth full scraper     # the nightly depth
```

The suites always run through the battery — it owns the run dir, the
port slots and the tally, and concurrent batteries take disjoint
port spaces. The suite bodies are
[dev/suites/](../../dev/suites/README.md)-documented; the runner's
profiles and budgets are the header of
[dev/battery/battery.py](../../dev/battery/battery.py).

## The docs map

The tool's own documents:

| document | what it is |
|---|---|
| [apps/scraper/README.md](../../apps/scraper/README.md) | the front page: usage, the security summary, the license |
| [apps/scraper/lib/options.json](../../apps/scraper/lib/options.json) | the knob registry: flags, env twins, defaults, the live/secret/restart marks |
| [apps/scraper/examples/metrics.json](../../apps/scraper/examples/metrics.json) | the shipped sample metrics spec (the packaged root copy rides beside the lib) |
| [apps/scraper/schema/metrics.schema.json](../../apps/scraper/schema/metrics.schema.json) | the JSON Schema the spec must satisfy |
| [apps/scraper/examples/modbus-scraper.conf](../../apps/scraper/examples/modbus-scraper.conf) | the generated, all-commented config example — the full knob reference |
| [apps/scraper/man/modbus-scraper.1](../../apps/scraper/man/modbus-scraper.1) | the daemon's man page: every flag, the signals, the control verbs |
| [apps/scraper/man/modbus-scraper-cli.1](../../apps/scraper/man/modbus-scraper-cli.1) | the ctl client's man page: the modes, the pager, the reconnect |
| [nixos/modules/modbus-scraper.nix](../../nixos/modules/modbus-scraper.nix) | the NixOS service module and its sandbox |
| [docker/Dockerfile.modbus-scraper](../../docker/Dockerfile.modbus-scraper) | the image recipe |
| [docker/env/modbus-scraper.env.example](../../docker/env/modbus-scraper.env.example) | the generated env-file example (42 env twins) |

The family documents:

| document | what it is |
|---|---|
| [docs/SECURITY.md](../../docs/SECURITY.md) | the family's security story — the F-numbers, the threat model |
| [docs/specs/ACL.md](../../docs/specs/ACL.md) | the family's access-control map: the gates and the grammars |
| [docs/specs/MODBUS.md](../../docs/specs/MODBUS.md) | the Modbus support tables: the function codes, the types |
| [docs/specs/static-defaults.md](../../docs/specs/static-defaults.md) | the current-state defaults reference |
| [nixos/README.md](../../nixos/README.md) | the Nix packaging and the module story |
| [docker/README.md](../../docker/README.md) | the compose stacks, the secret staging, both topologies |
| [docs/book/](../../docs/book/src/index.md) | the mdBook — the family narrative that includes these pages |
