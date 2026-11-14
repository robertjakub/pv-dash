# modbus-cache

> **Experimental — work in progress.** Verified only against simulated
> data (the fake inverter, fuzzing and regression/stress suites), not
> against real hardware.

`modbus-cache` is the suite's Modbus TCP caching proxy: a
dependency-free (Python stdlib only) daemon that owns the single Modbus
TCP client connection a device allows and multiplexes it for any number
of local clients. Two binaries live under `apps/cache/bin/` —
`modbus-cache.py`, the daemon, and `modbus-cache-cli.py`, the console
client for the daemon's control server. Both install under their short
names, `modbus-cache` and `modbus-cache-cli`.

The problem the proxy solves is the single-client device. A Huawei
SUN2000 inverter and its SDongle/EMMA radio accept exactly one Modbus
TCP connection, so the [modbus-scraper](../../apps/scraper/README.md)
that polls the device cannot share it with anything else — a second
client either waits forever or disturbs the first.

The proxy breaks that lock in one hop: point the clients at the cache
instead of the inverter. The cache holds the device's one connection,
a background poller keeps an in-memory copy of the interesting
registers fresh, and every connected client is served from that copy —
reads inside the register map answer from the cache, reads outside the
map and other function codes forward live, and writes forward only
through an explicitly opened, audited gate. The full reference is the
daemon's `--help` and the generated man page (`modbus-cache --man`);
this page is the operator's tour through the same ground.

## The family

```text
  the device :5502 (its one Modbus TCP client)
      ^   the one connection the cache owns
      |
  modbus-cache :15502  <---  any other Modbus client (a test
      |                       harness, a second exporter,
      v                       modbus-replay beside the chain)
  modbus-scraper :9350
      |
      v
  prometheus :9090  --->  dashboard :8080
```

The cache sits between the device and everything that reads it. The
chain above is the common shape, and every hop is optional — the
scraper can point at the device directly when nothing else shares it,
and any plain Modbus client can use the cache without Prometheus or
the dashboard being present.
[modbus-replay](../../apps/modbus-replay/README.md) runs beside the
chain rather than in it: it subscribes to the cache's trace feed,
dumps the wire records and replays them later against the fake
inverter.

## How it works

One background poller fronts one in-memory cache dictionary. At start
the daemon builds a register map — the device profile (the default
`sun2000`, or any JSON in the shared profiles/ schema spelled by
`--modbus-profile`) narrowed by `--selection` — and merges the map's
ranges into block reads. The poller walks the blocks every
`--modbus-interval` seconds and stores the words with a per-register
timestamp; a cached register older than `--cache-ttl` is refetched
before it is served again.

- **Serves** — FC3/FC4 reads that fall inside the map answer from the
  cache, immediately, without touching the device.
- **Forwards** — reads outside the map and every other function code
  cross to the device live; the client still sees one Modbus server.
- **Diagnostics** — a synthesized block at registers 65000–65003 lets
  a client tell cached data from live data.
- **Resilience** — when the device dies, cached reads keep serving
  last-known values and forwarded reads answer exception 0x0B; a
  range the device rejects has its poll status remembered instead of
  being hammered; garbage from either side is answered one line at a
  time and is never fatal.

The write path (FC05/06/15/16/22/23) is gated four times, in order:
the frame must parse as a write at all; `--allow-write` must be on (it
is off by default — without it writes refuse with a Modbus
illegal-function exception); the client's IP must sit on the write ACL
(`--write-acl`, default `none` — refuse everyone); and every register
the write touches must fall inside the allow-list
(`--write-registers`, default `none` — nothing writable). Enabling
`--allow-write` alone still refuses every write, and every accepted or
refused write lands in the audit trail.

The Modbus auth legs are optional on both sides, and speak the
family's suite handshake: after every connect the peer proves a shared
key (min 16 characters) with a 52-byte frame — magic, fresh nonce, an
HMAC-SHA256 proof — and the other side answers `OK` (plain Modbus
follows) or `ERR` (the session drops before a frame is served).
`--modbus-auth suite` demands this of the cache's own clients;
`--modbus-auth-upstream suite` proves the cache's key toward the
device. The `waveshare` upstream leg instead sends the key as the
gateway's connection password (raw ASCII right after every connect);
the gateway's `OK` opens the plain Modbus session. An upstream auth
failure fails the exchange like any other upstream fault and the
poller retries.

## Installing

### From the tree

The tree needs nothing but Python 3 — run the binaries where they sit:

```bash
python3 apps/cache/bin/modbus-cache.py --upstream 192.168.1.100:5502
python3 apps/cache/bin/modbus-cache-cli.py show version
```

A dev wrapper, `apps/cache/dev`, starts the daemon against the shipped
example configuration, and `apps/cache/dev-cli` starts the client
against it; extra flags pass through.

### Nix / NixOS

```bash
nix run .#modbus-cache        # the flake app
nix build .#modbus-cache      # the package (nixos/pkgs/modbus-cache/package.nix)
```

The NixOS service module (`nixos/modules/modbus-cache.nix`) provides
`services.modbus-cache`; see [nixos/README.md](../../nixos/README.md)
and [Deployment](#deployment).

### Docker

The image builds from
[docker/Dockerfile.modbus-cache](../../docker/Dockerfile.modbus-cache)
(alpine, stdlib-only, the unprivileged `pvsuite` user):

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-cache -t modbus-cache \
    --build-context shared=../shared \
    --build-context examples=../extras/examples \
    --build-context scripts=../docker --build-context common=../common \
    --build-context cli=../apps ../apps/cache
```

The compose stacks in [docker/README.md](../../docker/README.md)
build and wire the same image; the env-file surface is
[the generated example](../../docker/env/modbus-cache.env.example).

## Quick start

A minimal run against a device at 192.168.1.100:5502, with the scraper
as the first consumer:

```bash
# pre-flight: validate the configuration and the register map; nothing
# binds, nothing connects (exit 0 = valid, 1 = invalid, 2 = misuse)
python3 apps/cache/bin/modbus-cache.py --dry-run --upstream 192.168.1.100:5502

# start the proxy: binds 127.0.0.1:15502, polls the device every 10 s
python3 apps/cache/bin/modbus-cache.py --upstream 192.168.1.100:5502

# a second terminal: the control client answers over the unix socket
python3 apps/cache/bin/modbus-cache-cli.py show version
python3 apps/cache/bin/modbus-cache-cli.py show cache

# point the scraper at the proxy instead of the inverter
python3 apps/scraper/bin/modbus-scraper.py --upstream :15502
```

The proxy binds loopback by default; `--listen 0.0.0.0:15502` serves
the LAN. The scraper's `:15502` spelling means 127.0.0.1:15502. The
daemon logs to stderr and writes its audit trail to
`~/.local/state/modbus-cache/audit.log` when `--audit-log` is unset;
if the device goes away, the cache keeps serving last-known values.

## Configuration

### How a setting resolves

Every knob is one registry row in `apps/cache/lib/options.json`, and
the value sources win in a fixed order: flag, then environment, then
the config script (`--config`, the set grammar), then the row's
built-in default. The env twins are bare upper-snake names with no
tool prefix — `UPSTREAM`, `LISTEN`, `TTL`, `CONTROL_TOKEN` — and the
exceptions spell their own: `--cache-ttl`'s twin is `TTL`,
`--control-port`'s is `CTL`, `--modbus-auth-upstream`'s is
`MODBUS_UPSTREAM_AUTH`. `--dry-run` prints the effective settings,
which makes the order observable without starting the daemon.

### The knobs

The table is the daemon's full registry; the live path is the name the
set grammar and the control wire speak (`set cache ttl 30`). The live
column reads: **live** — a `set` applies immediately; **restart** — a
`set` records the value and answers the note `restart required
(startup-only knob)`; a restart, `request reload` or the config file
applies it; **secret** — startup-only, `set`/`clear` refuse outright,
the value never renders.

| knob (live path) | flag | env | default | live | what it does |
|---|---|---|---|---|---|
| `modbus/upstream` | `--upstream` | `UPSTREAM` | `127.0.0.1:5502` | restart | the device endpoint HOST:PORT (`:5502` = loopback) |
| `modbus/unit` | `--modbus-unit` | `MODBUS_UNIT` | `1` | live | the Modbus unit id |
| `modbus/timeout` | `--modbus-timeout` | `MODBUS_TIMEOUT` | `3` | live | connect/read timeout, seconds |
| `modbus/auth` | `--modbus-auth` | `MODBUS_AUTH` | `none` | live | the clients' auth scheme: `suite` or `none` |
| `modbus/auth/key` | `--modbus-auth-key` | `MODBUS_AUTH_KEY` | (unset) | secret | the suite handshake's shared key, min 16 chars |
| `modbus/auth-upstream` | `--modbus-auth-upstream` | `MODBUS_UPSTREAM_AUTH` | `none` | live | the upstream scheme: `suite`, `waveshare`, `none` |
| `modbus/auth-upstream-key` | `--modbus-auth-upstream-key` | `MODBUS_UPSTREAM_AUTH_KEY` | (unset) | secret | the key presented upstream |
| `modbus/interval` | `--modbus-interval` | `MODBUS_INTERVAL` | `10` | live | seconds between polls |
| `modbus/read-delay` | `--modbus-read-delay` | `MODBUS_READ_DELAY` | `0.05` | live | seconds between device reads in one cycle, 0 = none |
| `modbus/merge-gap` | `--modbus-merge-gap` | `MODBUS_MERGE_GAP` | `8` | live | max register gap merged into block reads, 0 = separate |
| `modbus/profile` | `--modbus-profile` | `MODBUS_PROFILE` | `sun2000` | live | device profile JSON (a bare name resolves in shared/profiles/) |
| `modbus/selection` | `--selection` | `SELECTION` | `all` | live | selection JSON: which profile names to fetch |
| `cache/ttl` | `--cache-ttl` | `TTL` | `30` | live | per-register TTL, `0`/`off` = never expire |
| `write/allow` | `--allow-write` | `ALLOW_WRITE` | `off` | live | forward writes at all (gate one) |
| `write/registers` | `--write-registers` | `WRITE_REGISTERS` | `none` | live | ranges a write may touch: `START:COUNT,...`, `any`, `none`, `profile`, `file:<path>` |
| `acl/connect` | `--connect-acl` | `CONNECT_ACL` | `any` | live | clients allowed to connect: IPs/prefixes, `any`, `none`, `file:<path>` |
| `acl/write` | `--write-acl` | `WRITE_ACL` | `none` | live | clients allowed to write (needs allow-write) |
| `system/listen` | `--listen` | `LISTEN` | `127.0.0.1:15502` | restart | the Modbus listen address HOST:PORT |
| `system/local-time` | `--local-time` | `LOCAL_TIME` | `off` | live | log timestamps in the system zone instead of UTC |
| `system/log-level` | `--log-level` | `LOG_LEVEL` | `INFO` | live | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `system/log-access` | `--log-access` | `LOG_ACCESS` | `off` | live | client connects/disconnects at INFO instead of DEBUG |
| `system/log-replies` | `--control-log-replies` | — | `off` | live | DEBUG-log every control command's full output |
| `limits/max-clients` | `--max-clients` | `MAX_CLIENTS` | `64` | live | refuse connections past this many clients, 0 = no limit |
| `limits/client-timeout` | `--client-timeout` | `CLIENT_TIMEOUT` | `300` | live | drop clients silent this long, 0 = never |
| `limits/max-conn-per-ip` | `--max-conn-per-ip` | `MAX_CONN_PER_IP` | `0` | live | per-IP connection cap, 0 = no limit |
| `control/port` | `--control-port` | `CTL` | (unix socket) | live | control target: unix path or TCP port on 127.0.0.1, 0 = off |
| `control/token` | `--control-token` | `CONTROL_TOKEN` | (unset) | secret | the admin control token; TCP refuses to start without one |
| `control/ops/token` | `--control-ops-token` | `CONTROL_OPS_TOKEN` | (unset) | secret | the read-only ops token |
| `control/ops/verbs` | `--control-ops-verbs` | `CONTROL_OPS_VERBS` | `show,flush` | live | the ops role's verb policy |
| `control/trust-uids` | `--control-trust-uids` | `CONTROL_TRUST_UIDS` | (unset) | live | extra uids the unix socket trusts without the token |
| `control/socket-group` | `--control-socket-group` | `CONTROL_SOCKET_GROUP` | `off` | live | the unix socket chmod 0660 instead of 0600 |
| `metrics/enable` | `--metrics-server` | `METRICS_SERVER` | `off` | live | serve the cache's own /metrics endpoint |
| `metrics/listen` | `--metrics-listen` | `METRICS_LISTEN` | `127.0.0.1:9351` | restart | the metrics bind address |
| `metrics/token` | `--metrics-token` | `METRICS_TOKEN` | (unset) | secret | the /metrics bearer token (mandatory beyond loopback) |
| `metrics/acl` | `--metrics-acl` | `METRICS_ACL` | `any` | live | the /metrics IP gate, checked at accept |
| `metrics/limits/max-clients` | `--metrics-max-clients` | `METRICS_MAX_CLIENTS` | `64` | live | /metrics client cap, extras get 503 |
| `metrics/limits/timeout` | `--metrics-client-timeout` | `METRICS_CLIENT_TIMEOUT` | `5` | live | idle /metrics client timeout, 0 = the built-in 5 s cap |
| `metrics/limits/max-conn-per-ip` | `--metrics-max-conn-per-ip` | `METRICS_MAX_CONN_PER_IP` | `0` | live | /metrics per-IP cap |
| `audit/log-file` | `--audit-log` | `AUDIT_LOG` | (XDG state home) | live | a path, `-` for stdout, `none` for remote-only |
| `audit/forward` | `--audit-forward` | `AUDIT_FORWARD` | `none` | live | `syslog`, `syslog:/path`, `udp://host[:514]`, `tcp://host[:514]` |
| `audit/forward/format` | `--audit-forward-format` | `AUDIT_FORWARD_FORMAT` | `rfc5424` | live | the remote envelope: `rfc5424` or `cef` |
| `audit/instance` | `--audit-instance` | `AUDIT_INSTANCE` | (control port) | live | the lines' `instance=<id>` writer word |
| `audit/rotate/max-size` | `--audit-max-mb` | `AUDIT_MAX_MB` | `10` | live | rotate the audit log at this size in MB, 0 = off |
| `audit/rotate/daily` | `--audit-daily` | `AUDIT_DAILY` | `off` | live | also rotate at UTC midnight |
| `audit/rotate/files` | `--audit-files` | `AUDIT_FILES` | `3` | live | rotated backups to keep |
| `audit/disable` | `--no-audit-log` | `NO_AUDIT_LOG` | `off` | live | disable the audit trail entirely |
| `audit/requests` | `--audit-requests` | `AUDIT_REQUESTS` | `300` | live | one REQUESTS tally per client per this many seconds, 0 = off |
| `dump/path` | `--dump-path` | `DUMP_PATH` | (unset) | live | the state dump file (write-behind) |
| `dump/key` | `--dump-key` | `DUMP_KEY` | (unset) | secret | seals the dumps and the reload state file |
| `dump/with-cache` | `--dump-with-cache` | `DUMP_WITH_CACHE` | `off` | live | the dump carries the cached words too |
| `dump/interval` | `--dump-interval` | `DUMP_INTERVAL` | `0` | live | seconds between automatic dumps, 0 = on request |
| `dump/restore-on-start` | `--restore-on-start` | `RESTORE_ON_START` | `off` | restart | load the dump when the daemon starts |
| `trace/socket` | `--trace-socket` | `TRACE_SOCKET` | `none` | live | the record-feed unix socket: `default`, a path, `none` |
| `trace/sources` | `--trace-sources` | `TRACE_SOURCES` | `all` | live | the feed's voices: `all`, `client`, `upstream` |

### The config file

`--config` points at a set-grammar script: every line is a
`set <name> <value>` in the live paths, comments start with `#`, and
anything left commented falls to the row's default. The shipped sample
(excerpted below) is generated — one commented line per registry row,
54 of them — at `apps/cache/examples/modbus-cache.conf`; copy it and
uncomment what changes:

```conf
# The modbus-cache's example configuration — GENERATED by
# dev/generators/examples.py from cache/lib/options.json: every knob
# the registry declares is below — 54 of them, every line commented.

# The grammar is the control grammar: every line is a `set <name>
# <value>` — the live path as words, the same line pastes into the
# console or a ctl. A value resolves flag > env > this file > the
# row's default. A secret's line spells the file:<path> form.

# per-register cache TTL: older entries are refetched
# set cache ttl 30

# the inverter Modbus TCP endpoint HOST:PORT
# startup-only: a change applies on restart
# set modbus upstream 127.0.0.1:5502

# a secret — pass it as file:<path>, an owner-only 0600 file
# startup-only: a change applies on restart
# set control token file:/run/credentials/modbus-cache/control-token
```

`show config` on the control wire re-renders the effective state as
the same grammar — the file the daemon would write back. When the flag
is unset the config search path is `$CONFIG`, then a
`modbus-cache.conf` next to the script, then the subproject root.

### Secrets

The registry marks six knobs secret: the admin control token, the ops
token, the metrics token, the two Modbus auth keys and the dump key. A
secret never renders — `show` answers `err <name> is a secret — it
never shows`, `show config` and the state dumps render the row as
`*** SECRET REMOVED ***`, and the config parser refuses that
placeholder as a value. A secret is startup-only: `set`/`clear` refuse
outright, the value passes by flag, env or config file, and a restart
applies it.

Every secret takes `file:<path>` — the first line of an owner-only
0600 file, the shipped way (the loader enforces the 0600 mode; a
systemd LoadCredential rides as `file:/run/credentials/...`).

## Runtime control

Three signals, no restarts for the common work:

- **SIGHUP** — reload the configuration and the register map without
  dropping clients; the file always wins over live settings, a broken
  file keeps the previous state. The listen address and the log level
  need a restart.
- **SIGUSR1** — clean the cache: cached values, on-demand entries and
  poll-status errors drop, the poller repopulates immediately.
- **SIGTERM / SIGINT** — graceful shutdown (a final dump when
  `--dump-path` is set).

The knob classes from the [table](#the-knobs): live knobs apply at the
`set`; restart-marked knobs (`modbus/upstream`, `system/listen`,
`metrics/listen`, `dump/restore-on-start`) record the pending value
and answer the note; `request reload` saves the live overrides and
re-execs the whole daemon, so the recorded knobs take their configured
values (the cache starts empty). Secret knobs refuse `set`/`clear`.
`request reload-config` re-reads the config file without the restart —
the same re-apply as a SIGHUP.

One worked sequence on the console:

```text
$ python3 apps/cache/bin/modbus-cache-cli.py
cache:15502 > set cache ttl 15
% changed
cache:15502 > show cache
ok ranges=2 words=88 hits=411 misses=6
cache:15502 > request flush cache
cache:15502 > shutdown
Proceed with shutdown? [confirm]
confirm
$
```

The prompt shows the connected port; `set`/`clear` confirm
`% changed`, errors print `% error: <message>`, `request flush cache`
confirms silently, `shutdown` asks first. The `show cache` line above
is illustrative — the report's shape is the registry's.

## The control plane

`modbus-cache-cli` is one client with three invocation shapes: command
words one-shot (`modbus-cache-cli show config` — the raw verdict
prints, exit 0 ok, 1 connection error, 2 misuse), a piped stdin batch
(the script lines run in order), and a bare terminal for the
interactive console. The client auto-detects the daemon's unix socket;
`--control-port` or `CTL` spell the target explicitly. The console
greets with the upstream, the poll health and the uptime, TAB
completes commands, settings and values, a pager breaks long replies,
and idle keepalive pings keep the session alive
(`--reconnect`/`--reconnect-wait` re-arm a dropped one).

The wire is the family's signed JSON lines: one request
`{"cmd": "..."}` per line, one reply
`{"status": "ok|fail|note|bye", "text": "..."}` per line. With a token
held, every frame carries a full sha256 HMAC both directions, so
commands and replies verify end to end. The verbs:

- `set <setting> <value>`, `clear <setting>`, `show <setting>`,
  `show config`, `show knobs`, `help`, `ping`, `quit`, `shutdown`;
- the reports — `inspect` (one pretty dump of everything), `show
  connections`, `show cache` and `show cache-all` (every entry with
  age, expiry, poll status), `show uplink` (session counters, one row
  per poll block with latency and last error), `show uplink-sources`
  (the register map), `show version`, and the ACL chains `show
  write-registers-table`, `show connect-acl-table`, `show
  write-acl-table`, `show metrics-acl-table`;
- the ops — `request dump`, `request restore`, `request flush cache`,
  `request poll now`, `request restart` (drop the upstream session
  and the cache, repoll), `request reload`, `request reload-config`.

The transport is a unix socket by default —
`/tmp/modbus-cache-<port>.socket` after the listen port, so the
default daemon's is `/tmp/modbus-cache-15502.socket` — bound 0600,
stale files replaced, unlinked on shutdown (`--control-socket-group`
leaves it 0660). Over the socket a trusted peer skips the token: root,
the daemon's own user, or the extra uids in `--control-trust-uids`
(SO_PEERCRED). `--control-port` instead binds a TCP port on 127.0.0.1,
and a TCP control plane refuses to start without the admin token — the
tokenless-TCP refusal is family posture (F5).

Tokens and roles: the admin token (or a trusted unix peer) is the full
role. `--control-ops-token` defines a second, read-only ops role whose
sessions may run its policy's verbs only — `--control-ops-verbs`,
default `show,flush` — no `set`/`clear`, no `request dump`/`restore`,
no `request reload`, no `request restart`, no `shutdown`. The client
authenticates with `{"cmd": "auth", "token": ...}` (`--control-token`,
env `CONTROL_TOKEN`; a `file:<path>` value reads the token from an
owner-only file). Both roles' commands land in the audit trail; the
client's own session events ride the `CLI` prefix, the wire commands
are audited once by the server.

## Access control

The write gate stack, in the order a write meets it:

1. the frame parse gate — a malformed write never reaches the gates;
2. `write/allow` (`--allow-write`, off) — the master switch;
3. `acl/write` (`--write-acl`, `none`) — the client's IP must sit on
   this gate: `any`/`none`, comma-separated IPs and prefixes, or
   `file:<path>`;
4. `write/registers` (`--write-registers`, `none`) — the register
   allow-list: comma-separated `START:COUNT` ranges
   (`47400:100,47600:100`), `any`, `none`, `profile` (the device
   profile's `acl`/`write` gate), or `file:<path>`.

The register gate is a typed rule chain — `{"type": "allow"|"deny",
"range": "START:COUNT"}` per rule — where the last matching rule
decides, a register no rule decides refuses, and the word `any` means
all registers. The standalone file is the same gate object a profile
carries — the worked example `extras/examples/acl-write-registers.json`
against `shared/schema/acl-write-registers.schema.json`. An acl file
that is group- or world-readable warns in the log, in the audit trail
(`ACL-FILE`) and on the `set`/`clear` reply; chmod 0600 silences it.
`show write-registers-table` renders the compiled chain, one
allow/deny line per range.

The connect ACL (`acl/connect`, `--connect-acl`, default `any`)
filters who may connect at all — the same inline grammar or a
standalone ip-prefix file, `{"type": "ip-prefix", "rules": [{"type":
"allow"|"deny", "prefix": ...}]}`: last match decides, a client no
rule decides refuses. The example and schema live at
`extras/examples/acl-ip-prefix.json` and
`shared/schema/acl-ip-prefix.schema.json`. `show connect-acl-table`
renders the chain.

The Modbus auth legs close the protocol itself: `--modbus-auth suite`
makes the cache's clients prove a shared key with the handshake after
every connect, and `--modbus-auth-upstream suite|waveshare` does the
same toward the device. Both keys are secret knobs — pass them as
`file:<path>`. The family-wide grammar is
[docs/specs/ACL.md](../../docs/specs/ACL.md); the security story is
[docs/SECURITY.md](../../docs/SECURITY.md).

## Metrics

The cache carries the family's one /metrics stack on its own port.
`--metrics-server` (off by default) serves Prometheus text on
`--metrics-listen`, default `127.0.0.1:9351`. A token is mandatory
beyond loopback — a token-less non-loopback bind refuses to start
(F13) — answered against `--metrics-token` with
`Authorization: Bearer <token>`. The `metrics/acl` IP gate checks the
peer at accept (a client off the ACL is closed without a reply), and
the caps bound the endpoint: `metrics/limits/max-clients` (extras get
an immediate 503), `metrics/limits/timeout` (the slowloris cap, 0 =
the built-in 5 s) and `metrics/limits/max-conn-per-ip`.

The gauges are the `modbus_cache_*` family: the process
(`modbus_cache_uptime_seconds`), the cache itself
(`modbus_cache_hits_total`, `modbus_cache_misses_total`,
`modbus_cache_words`, `modbus_cache_ranges` by fc,
`modbus_cache_age_seconds` for the oldest word), the poll
(`modbus_cache_poll_up`, `modbus_cache_last_poll_age_seconds`,
`modbus_cache_poll_duration_seconds` with mean and max), the clients
(`modbus_cache_clients`), the write gate
(`modbus_cache_write_refused_total`) and the uplink
(`modbus_cache_uplink_up`, `modbus_cache_uplink_connects_total`,
`modbus_cache_uplink_exchanges_total`,
`modbus_cache_uplink_errors_total`,
`modbus_cache_uplink_bytes_total` by direction, plus the per-block
`modbus_cache_uplink_block_up` / `_block_latency_seconds` /
`_block_fails_total` series labeled `fc`, `start`, `count`). The alert
pair that watches them ships in
[extras/alerts/cache.yml](../../extras/alerts/cache.yml).

## The audit trail

Every control command with its role, every auth failure, every
accepted or refused write, the reloads and the CLI's own session
events land in an append-only, hash-chained trail — the cache's lines
carry the `CACHE` prefix, the client's the `CLI` prefix. `--audit-log`
spells the sink: a file path, `-` for stdout (the docker/journald
way), or `none` to turn the local file off (with a forward spelled,
that is the remote-only mode). Unset, the trail lands in the XDG state
home, `~/.local/state/modbus-cache/audit.log`. Rotation rides
`--audit-max-mb` (default 10), `--audit-daily` (UTC midnight) and
`--audit-files` (default 3); `--audit-requests` folds per-client
request counts into one REQUESTS tally per interval instead of a line
per command.

The chain is per writer and verifiable offline —
[dev/gates/audit_verify.py](../../dev/gates/audit_verify.py) walks a
trail and alerts on a break. `--audit-forward` mirrors every line,
chain included, off-box: `syslog` (the local socket auto-scan),
`syslog:/path` (an explicit socket), `udp://host[:514]` (RFC5426,
best-effort) or `tcp://host[:514]` (RFC6587 framing);
`--audit-forward-format` picks the remote envelope, `rfc5424` (the
default) or `cef`. Every line names its writer in `instance=<id>` —
the control port when `--audit-instance` is unset, the override when
spelled; make an override unique among everything that shares one
collector. A send failure notes once and the next event re-arms.
`--no-audit-log` disables the trail entirely.

## Tuning

The slow-device knobs:

- `modbus/merge-gap` (`--modbus-merge-gap`, 8) — how wide a register
  gap the poll plan merges into one block read; 0 reads each range
  separately. Lower it for a device that chokes on wide reads.
- `modbus/read-delay` (`--modbus-read-delay`, 0.05) — seconds between
  consecutive device reads within one poll cycle; 0 disables the
  wait. Raise it for a slow dongle.
- `modbus/timeout` (`--modbus-timeout`, 3) — the connect/read timeout
  of the upstream session.
- `modbus/interval` (`--modbus-interval`, 10) — seconds between poll
  cycles; `request poll now` wakes the loop immediately.
- `cache/ttl` (`--cache-ttl`, 30) — how long a cached register serves
  before the next read refetches it; `off` serves last-known values
  forever.

The caps, all live-settable: `limits/max-clients` (64),
`limits/client-timeout` (300, idle clients) and
`limits/max-conn-per-ip` (0, no per-IP limit) bound the Modbus port;
the `metrics/limits/*` trio bounds /metrics the same way. The state
dump cadence rides `dump/interval` (0 = on request and at shutdown)
and `dump/restore-on-start` turns a restart into last-known values
instead of cold misses.

## Deployment

### NixOS

`services.modbus-cache.enable = true` is the floor. The module's
options:

- `settings` — the daemon's environment as bare env twins
  (`UPSTREAM = "192.168.1.100:5502";`), rendered verbatim into a
  systemd EnvironmentFile; an absent key leaves the daemon default.
  The six secret env names are refused here — the env file renders
  into the world-readable nix store.
- the `<secret>File` options — `modbusAuthKeyFile`,
  `modbusAuthUpstreamKeyFile`, `controlTokenFile`,
  `controlOpsTokenFile`, `metricsTokenFile`, `dumpKeyFile` — absolute
  paths outside the store, mounted via LoadCredential and read by the
  daemon as `file:/run/credentials/modbus-cache/<name>`.
- `user`/`group` — null keeps the DynamicUser; a name (the family's
  shared identity is `pvsuite`) switches to a static account the
  module creates. `openFirewall` opens the listen port.

The unit ships the full hardening pass (ProtectSystem strict, an empty
CapabilityBoundingSet, only the AF_UNIX/INET socket families),
re-loads with SIGHUP, and warns on the known foot-guns: a control
socket under /tmp (PrivateTmp hides it), `openFirewall` with a
loopback bind, a root user. The option map is
[nixos/README.md](../../nixos/README.md).

### Docker

The image's ENV pins the compose defaults —
`UPSTREAM=modbus-fake-inverter:5502` (the stack's fake service; a
production edit points it at the real device) and
`SELECTION=/config/selection.json` — and the CMD runs `modbus-cache
--listen 0.0.0.0:15502 --audit-log -`. The entrypoint seeds `/config`
(the selection file survives recreation there), then drops to
`pvsuite`. The bundled conf loads from the image's default `--config`
target, and the per-tool env file overrides it knob by knob:

```bash
cp docker/env/modbus-cache.env.example docker/env/modbus-cache.env
# the demo stack reads the plain copy; the prod stack requires
# env/modbus-cache-production.env — UPSTREAM is the operator's
# decision there
```

Every line of the env example ships commented at the value the image
itself runs; a secret's line stays empty — pass it as `file:<path>`.
The HEALTHCHECK runs `modbus-cache-cli show version` over the daemon's
unix socket as a trusted peer (no token), so `CTL=0` fails the check.
The topologies are drawn in [docker/README.md](../../docker/README.md).

## Troubleshooting

- **The daemon exits 1 with a bind error on stderr** — a port is
  taken: the EADDRINUSE case prints one `cannot bind` error line and
  exits 1, no traceback. Free the port or move the bind.
- **The control plane refuses to start** — a TCP `--control-port`
  without `--control-token` refuses (F5). Bind the unix socket (the
  default) or pass a token.
- **The metrics endpoint refuses to start** — a non-loopback
  `--metrics-listen` without `--metrics-token` refuses (F13).
- **Connections refused that should serve** — the caps
  (`limits/max-clients`, `limits/max-conn-per-ip`) and the connect
  ACL (`acl/connect`) both reject at accept; `show connections` and
  `show connect-acl-table` name the state. A metrics client past
  `metrics/limits/max-clients` gets an immediate 503.
- **A restore refuses the dump** — a tampered, unsigned or
  group-writable dump is refused outright; a dump written under a
  `--dump-key` refuses to restore with a wrong or missing key, and a
  configured key refuses an unsealed dump. Pass the same key (a
  `file:<path>` works). A dump path without a key warns at start.
- **A set answers `restart required (startup-only knob)`** — the knob
  is restart-marked; the value is recorded (it shows), and a restart,
  `request reload` or the config file applies it.
- **A set answers `err ... is a secret`** — secrets refuse
  `set`/`clear` by design; pass the value by flag, env or config, or
  restart.
- **Writes refuse with an illegal-function exception** — the gate
  stack is closed by default; open it deliberately (the
  [Access control](#access-control) order) and watch
  `show write-registers-table` and the WRITE-REFUSED audit lines.
- **Pre-flight** — `--dry-run` validates the configuration and the
  register map, prints the effective settings, and binds nothing:
  exit 0 valid, 1 invalid, 2 misuse.

## Testing

The suites that cover the cache live in `dev/suites/`:
[cache-regtest.py](../../dev/suites/cache-regtest.py) (the regression
walk: the poll plan, the gates, the control wire, the dump/restore),
[cache-stress.py](../../dev/suites/cache-stress.py) (many clients,
caps, slow-device paths),
[cache-fuzz.py](../../dev/suites/cache-fuzz.py)
(garbage and hostile frames against the Modbus face),
[cache-control-fuzz.py](../../dev/suites/cache-control-fuzz.py) (the
same against the control wire), plus the family-wide
[audit-chain.py](../../dev/suites/audit-chain.py) and
[control-fuzz.py](../../dev/suites/control-fuzz.py).

The suites run through the battery runner — never standalone; the
runner owns the run dir, the port slots and the tally:

```bash
python3 dev/battery/battery.py cache            # the cache commit set:
                                                # regtest + fuzzes (~5 min)
python3 dev/battery/battery.py cache-regtest    # explicit suite names
```

Concurrent batteries take disjoint port slots, so a second run cannot
kill the first; the live status view is
[dev/battery/battery_status.py](../../dev/battery/battery_status.py).

## The docs map

The tool's own documents first, then the family's:

| document | what it holds |
|---|---|
| [apps/cache/README.md](../../apps/cache/README.md) | the tool's README: usage, the security posture, the license |
| [apps/cache/lib/options.json](../../apps/cache/lib/options.json) | the knob registry — one row per knob: flag, env, live path, marks |
| [apps/cache/examples/modbus-cache.conf](../../apps/cache/examples/modbus-cache.conf) | the generated all-commented example configuration |
| [apps/cache/man/modbus-cache.1](../../apps/cache/man/modbus-cache.1) | the daemon's man page (`modbus-cache --man`) |
| [apps/cache/man/modbus-cache-cli.1](../../apps/cache/man/modbus-cache-cli.1) | the client's man page: the flags, the env twins, the console |
| [nixos/modules/modbus-cache.nix](../../nixos/modules/modbus-cache.nix) | the NixOS service module |
| [nixos/pkgs/modbus-cache/package.nix](../../nixos/pkgs/modbus-cache/package.nix) | the package build |
| [docker/Dockerfile.modbus-cache](../../docker/Dockerfile.modbus-cache) | the image |
| [docker/env/modbus-cache.env.example](../../docker/env/modbus-cache.env.example) | the generated env-file example |
| [docs/SECURITY.md](../../docs/SECURITY.md) | the one security document: the posture, the boundaries, the findings |
| [docs/specs/ACL.md](../../docs/specs/ACL.md) | the ACL grammar the IP gates and the register gate speak |
| [docs/specs/MODBUS.md](../../docs/specs/MODBUS.md) | the Modbus support spec: the function codes, the auth handshake |
| [extras/examples/README.md](../../extras/examples/README.md) | the shared example files, the acl pair included |
| [nixos/README.md](../../nixos/README.md) | the Nix tree: the packages, the modules, the hardening |
| [docker/README.md](../../docker/README.md) | the images, the entrypoints, the two compose stacks |
| [docs/book/](../../docs/book/) | the mdBook render of the suite's documentation |
| [extras/manuals/pvsuite-cli.md](../../extras/manuals/pvsuite-cli.md) | the one client: the name resolution, the shapes, the console |
