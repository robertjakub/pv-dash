# modbus-cache

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) **Modbus TCP caching proxy** for devices
that accept only a single client — Huawei SUN2000 inverters and their
SDongle/EMMA radios are limited to one Modbus TCP connection, so the
[modbus-scraper](../scraper/README.md) cannot share them with anything else.

> **Experimental — so far verified only against simulated data**
> (fake inverter, fuzzing and regression/stress suites), not against real
> hardware.

## How it works

The proxy owns the one upstream connection the device allows and multiplexes
it:

- a background loop **polls the configured register ranges** from the inverter
  at a fixed interval into an in-memory cache;
- any number of clients connect to the proxy and are **served FC3/FC4
  register reads and FC1/FC2 bit reads from the cache** — no per-client
  inverter traffic;
- reads **outside the cached ranges** are **polled from the inverter live**,
  answered, and **cached for `--cache-ttl`** like everything else (FC3/FC4
  words and FC1/FC2 bits alike) — as is any other function code (writes,
  FC17, vendor codes), forwarded untouched. Such a read waits for a free
  slot between poll reads, at most one transaction + read delay;
- **writes** (FC05/06/15/16/22/23) are forwarded when enabled (see
  [Access control](#access-control)) and always logged with register,
  value(s) and outcome;
- a synthesized **diagnostics block** (registers 65000–65003: device-up flag,
  cache age, uptime) lets clients tell live data from cache-served values —
  see [Diagnostics registers](#diagnostics-registers).

Resilience:

- **Inverter unreachable** — cached reads keep serving the last known values
  (the poller logs `serving cached values` and reconnects on its own), while
  forwarded reads get a Modbus exception `0x0B` (gateway target failed).
  Every cached register carries the time it was last fetched; entries older
  than `--cache-ttl` (default: **3× the poll interval**; `0` = never expire)
  are refetched on the next read — fresh data when the device is back, the
  `0x0B` exception when it is not.
- **Device rejects a range** (e.g. a poll block crosses an undefined register
  — the device answers Modbus exception `02` for the whole request) — the
  cache remembers that **poll status** and answers client reads in that range
  with the same exception until a poll succeeds again: no repeated device
  hammering, and clients see the failure the device actually reports.
- **Garbage from the device** (malformed frames, short bodies, disconnects,
  lying lengths, wrong transaction/unit ids, stalls) — the poller logs it
  one-line and retries; it cannot be killed by bad input, and a device that
  starts answering again is picked up on the next cycle.
- **Garbage from clients** (random PDUs, lying MBAP lengths, wrong
  protocol/unit ids, pipelined bursts, truncated frames) — every request is
  answered (or the connection is closed for lying headers); malformed
  frames, fuzzing and soak-tested: a client cannot crash the proxy, only
  burn its own connection.

## Register map (device profile)

The proxy caches the registers listed in the **device profile** — the same
shared schema the [fake inverter](../inverter/README.md) serves and the
[scraper](../scraper/README.md) scrapes; the shipped profiles live in the
suite's [`profiles/`](../profiles/) subproject (`sun2000.json` by default).
The profile JSON format is documented in
[profiles/README.md](../profiles/README.md).
Resolution: `--profile` flag, env `PROFILE`, config `set modbus profile`,
then the bundled copy; the file is re-read on `SIGHUP`. Entry `type` gives
the width and the space: `i16`/`u16` (one word), `i32`/`u32` and the
lo-word-first `i32swap`/`u32swap`, the IEEE 754 `f32`/`f32swap` (two words
each), `bit` (one address = one binary value); `name` decorates the poll
logs, and the optional **`fc`** field picks the address space: `3`
(holding registers) or `4` (input registers) for the word types (`3` the
default), `1` (coils, the bit default) or `2` (discrete inputs) for `bit` —
the four spaces are cached and polled independently, and each is served
from the cache on its own function code. The optional **`ttl`** field
overrides the cache
TTL per entry (seconds; `0` = never expire) — a fast power word at 5s next
to a nameplate word at 1h, one poll cadence for both; `show cache all`
marks the entries carrying one (`[ttl 5s]`). The entry TTL **replaces** the
global one in both directions: a lower entry TTL shortens the freshness, a
higher one lengthens it — the global TTL is only the fallback for the
entries without their own, never a floor.

Which registers are actually **fetched** comes from a selection file —
`{"registers": ["pv-power", "grid-power", ...]}`, profile names only —
resolved as `--selection` flag, env `SELECTION`, config
`set modbus selection`; the default fetches **every** profile entry (`all`), and
**`none`** empties the map: every read forwards to the inverter and nothing
is stored (a pass-through proxy, the cache gauges go quiet). The shipped
**`selection.json`** (in `examples/`) is an example — the essential
SUN2000 monitoring
set (the classic 13-range map, by name). Reads outside the selected set are
forwarded to the inverter (any FC1-FC4 read is cached on its way through,
under its own function code). The 65000-65003 diagnostics
block is not a device register — it never appears in a profile and is never
fetched: the cache synthesizes it from its own poller state (FC3 only).

For slow dongles the poller reads the map in as **few transactions as
possible**: ranges closer together than `--merge-gap` registers (default 8)
are merged into one block read, which may also cover registers between the
listed ones (those are cached too) — never across a function-code boundary
(a bit block never swallows a register range). A
block that fails — e.g. because it spans an unmapped register — is split in
halves and the pieces are retried; the plan converges to the largest blocks
the device actually answers.

## Usage

```bash
python3 cache/bin/modbus-cache.py --upstream 192.168.1.100:5502
```

By default the proxy **binds to 127.0.0.1:15502** (loopback only) — pass
`--listen 0.0.0.0:15502` when Modbus clients live on other hosts.

Add **`--dry-run`** to validate the configuration and the register map and
print the effective settings (poll plan, ACLs, limits) without binding the
listen port or contacting the inverter — handy for checking NixOS-rendered
config files (`--config /nix/store/…-modbus_cache.conf --dry-run`).
Exit codes: `0` = valid; `1` = invalid (reason on stderr, stdout stays
clean); `2` = command-line misuse.

Point the scraper (or any other Modbus client) at the proxy instead of the
inverter:

```bash
python3 scraper/bin/modbus-scraper.py --upstream :15502
```
The scraper auto-detects the diagnostics block and exports it as
`scraper_cache_*` Prometheus gauges — device-down-behind-cache becomes visible
downstream instead of flowing through as fresh data.

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`modbus-scraper`:

1. CLI flags (`--upstream`, `--listen`, …)
2. Environment variables — the same names, bare (no tool prefix): `UPSTREAM`,
   `UNIT`, `TIMEOUT`, `LISTEN`, `INTERVAL`, `READ_DELAY`, `MERGE_GAP`,
   `PROFILE`, `SELECTION`, `TTL`, `ALLOW_WRITE`, `CONNECT_ACL`,
   `WRITE_ACL`, `WRITE_REGISTERS`, `AUTH`, `AUTH_KEY`, `AUTH_UPSTREAM`,
   `AUTH_UPSTREAM_KEY`, `MAX_CLIENTS`, `CLIENT_TIMEOUT`,
   `MAX_CONN_PER_IP`, `METRICS_SERVER`, `METRICS_LISTEN`, `METRICS_TOKEN`,
   `METRICS_MAX_CLIENTS`, `METRICS_CLIENT_TIMEOUT`,
   `METRICS_MAX_CONN_PER_IP`, `LOG_LEVEL`, `LOG_ACCESS`, `LOCAL_TIME`,
   `CONTROL_TOKEN`, `CONTROL_OPS_TOKEN`, `CONTROL_OPS_VERBS`,
   `CONTROL_SOCKET_GROUP`, `CONTROL_TRUST_UIDS`, `DUMP_PATH`,
   `DUMP_KEY`, `DUMP_INTERVAL`, `DUMP_WITH_CACHE`, `RESTORE_ON_START`,
   `AUDIT_LOG`, `AUDIT_MAX_MB`, `AUDIT_DAILY`, `AUDIT_FILES`,
   `NO_AUDIT_LOG`, `REQUESTS_AUDIT` — `show knobs` prints every knob with
   its env twin
3. Config file (the set grammar: every line a `set <name> <value>` in the
    CLI spelling) — `--config` picks the
   file (default: `modbus_cache.conf` next to `modbus-cache.py` — the
   packaged layout — then the subproject root's sample; a missing file
   is fine)

Every setting is validated before use — nonsense values (negative intervals,
out-of-range ports, bad unit ids, malformed ACLs, unknown log levels) abort
with a clean one-line error instead of failing later at runtime.

| Flag | Default | Meaning |
|---|---|---|
| **Upstream** | | |
| `--upstream` | `127.0.0.1:5502` | the inverter's Modbus TCP endpoint `HOST:PORT` (`:5502` = `127.0.0.1:5502`) |
| `--unit` | `1` | Modbus unit id (1–247) |
| `--timeout` | `3` | Modbus connect/read timeout, seconds |
| `--auth` | `none` | the auth scheme the cache's **own Modbus clients** must speak: `suite` demands the crypt handshake (magic + nonce + HMAC proof of the shared key) right after every connect — the cache answers `OK` and the session speaks plain Modbus, or `ERR` and the client is dropped before it ever sees a frame; `none`/empty = no auth at all — see [Modbus auth](#modbus-auth) (config `set modbus auth`, env `AUTH`) |
| `--auth-key` | none | the shared key the cache's clients prove with the suite handshake, **min 16 characters**; the value may be `file:<path>` — the first line of an owner-only `0600` file (config `set modbus auth key`, env `AUTH_KEY`) |
| `--auth-upstream` | `none` | the auth scheme **toward the upstream inverter**: `suite` proves the shared key with the same handshake after every connect — the peer answers `OK`, or `ERR` and the connection fails (the poller keeps retrying); `waveshare` presents the shared key as the Waveshare TCP connection password after every connect (the gateway answers `OK`, or anything else and the connection fails); `none`/empty = no auth at all — see [Modbus auth](#modbus-auth) (config `set modbus auth-upstream`, env `AUTH_UPSTREAM`) |
| `--auth-upstream-key` | none | the key the cache presents to the upstream inverter — the suite handshake's shared key (**min 16 characters**) or the Waveshare gateway password (non-empty ASCII); the value may be `file:<path>` (config `set modbus auth-upstream-key`, env `AUTH_UPSTREAM_KEY`) |
| **Proxy** | | |
| `--listen` | `127.0.0.1:15502` | proxy listen address `HOST:PORT` (loopback by default) |
| `--profile` | the bundled `sun2000` profile | device profile JSON to cache (see above) |
| `--interval` | `10` | seconds between cache polls |
| `--cache-ttl` | 3× `--interval` | per-register cache TTL in seconds: older entries are refetched from the inverter (`0` = never expire) |
| `--read-delay` | `0.05` | seconds between consecutive inverter reads within a poll cycle (`0` = no wait) |
| `--merge-gap` | `8` | max register gap when merging ranges into block reads (`0` = read separately) |
| **Behaviour toggles** | | |
| `--allow-write` | disabled | forward write requests (FC05/06/15/16/22/23) to the inverter; disabled, they are refused with a Modbus illegal-function exception (config `set write allow`, env `ALLOW_WRITE` accepts `true`/`false`) |
| `--write-registers` | `none` | register ranges a forwarded write may touch: comma-separated `START:COUNT`, e.g. `47400:100,47600:100` — every touched register must land inside a range, anything else is refused with a Modbus illegal-function exception; `any` = every register writable, `none` = no register writable (the default), `profile` = the device profile's `acl`/`write` gate (the ordered rule chain — one `type` allow/deny and a `range` per rule, a whitelist: the last matching rule decides, a register no rule decides refuses; `any` = all registers), `file:<path>` = the standalone acl file — the same gate object a profile carries under `acl`/`write`, read and compiled at start and on every set (config `set write registers`, env `WRITE_REGISTERS`) |
| `--connect-acl` | `any` | clients allowed to connect: `any`, `none` (refuse everyone), comma-separated IPs/CIDR prefixes (IPv4 or IPv6), or `file:<path>` — the standalone ip-prefix acl file — see [Access control](#access-control) |
| `--write-acl` | `none` | clients allowed to write — still requires `--allow-write`; `none` = no client writes (the default); the same grammar as `--connect-acl` (`any`/`none`/the list/`file:<path>`) — see [Access control](#access-control) |
| `--control-token` | none | require a token on **control** connections: the client authenticates with `{"cmd": "auth", "token": "..."}` before anything else; over the unix socket a trusted peer (root, the daemon's own user or `--control-trust-uids` — `SO_PEERCRED`) skips the handshake; a **TCP** control port refuses to start without a token — see [Runtime control](#runtime-control---control-port) (config `set control token`, env `CONTROL_TOKEN`) |
| `--control-ops-token` | none | a **second, read-only control token**: sessions authenticating with it may run the `show`/`clear` verbs only — no `set`/`unset`, no `request dump`/`restore`, no `request reload`, no `request restart`, no `shutdown` — the ops shift against the admin key, both audited (`role=ops`/`role=admin` in the CACHE trail); needs `--control-token` and must differ from it — see [Runtime control](#runtime-control---control-port) (config `set control ops token`, env `CONTROL_OPS_TOKEN`; the value may be `file:<path>` — the first line of an owner-only `0600` file, F12) |
| `--control-ops-verbs` | `show,clear` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated, validated against the control grammar at start (config `set control ops-verbs`, env `CONTROL_OPS_VERBS`) |
| `--control-socket-group` | off | leave the unix control socket group-accessible (`chmod 0660` instead of the default `0600`): a local group may speak to the control without being the service user (config `set control socket-group`, env `CONTROL_SOCKET_GROUP`) |
| `--control-trust-uids` | none | extra peer uids the unix control socket trusts without the token (`SO_PEERCRED`): a comma-separated uid list — a local systemd unit speaks without the secret; root and the daemon's own user are always trusted (config `set control trust-uids`, env `CONTROL_TRUST_UIDS`) |
| **Persistence** | | |
| `--dump-path` | off | the state dump (write-behind): the live setting overrides and — with `--dump-with-cache` — the cached words + their stamps, as one JSON, created `0600` with an integrity hash — written on shutdown, by the `request dump` command and every `--dump-interval` seconds; loaded on start only with `--restore-on-start`, on demand with the `request restore` command (config `set dump path`, env `DUMP_PATH`) |
| `--dump-key` | off | the key that **seals** the state dumps and the reload's state file: the state rides encrypted (an HMAC-SHA256 counter-mode keystream, authenticated — a restore refuses a wrong or missing key, and a configured key refuses an unsealed dump); startup-only — the reload re-exec re-resolves the same key (config `set dump key`, env `DUMP_KEY`); the value may be `file:<path>` — the first line of an owner-only 0600 file, so the config carries the reference, never the material; a dump path without a key warns unsealed at start and on `set dump path` |
| `--dump-with-cache` | off | dump the cached words too: the `request dump` command and the `--dump-interval` loop write the words + the settings (the default off = settings only; `request dump with-cache` always includes them; the restore takes either shape) (config `set dump with-cache`, env `DUMP_WITH_CACHE`) |
| `--dump-interval` | `0` | seconds between the automatic state dumps, `0` = on request (the `request dump` command and the shutdown); needs `--dump-path`; live-settable (config `set dump-interval`, env `DUMP_INTERVAL`) |
| **Audit trail** | | |
| `--audit-log` | XDG state | the CACHE audit trail: a file path or `-` for stdout (docker logs / journald); default `~/.local/state/modbus-cache/audit.log` — see [Audit logging](#audit-logging) |
| `--audit-max-mb` | `10` | rotate the audit log at this size, keeping `--audit-files` backups; `0` = off |
| `--audit-daily` | off | also rotate the audit log at UTC midnight |
| `--audit-files` | `3` | rotated audit backups to keep |
| `--no-audit-log` | off | disable the audit trail |
| `--requests-audit` | `300` | audit one `REQUESTS` tally per client per this many seconds (who is hammering the cache), `0` = off (config `set audit requests`, env `REQUESTS_AUDIT`) |
| **Metrics** | | |
| `--metrics-server` | off | serve the cache's own Prometheus `/metrics` endpoint (the hit/miss counters, the poll health and age, the poll-cycle durations, the client count — no dependency on the scraper's `scraper_cache_*` path); **live-settable** (`set metrics enable on/off`) and **refuses to start without `--metrics-token`** (config `set metrics enable`, env `METRICS_SERVER`) |
| `--metrics-listen` | `127.0.0.1:9252` | the metrics bind address `HOST:PORT` — `0.0.0.0:PORT` serves every interface, **a token is mandatory regardless** (config `set metrics listen`, env `METRICS_LISTEN`) |
| `--metrics-token` | off | require `Authorization: Bearer <token>` on the metrics endpoint (the same scheme as the scraper's `--auth-token`); mandatory when `--metrics-server` is on; the value may be `file:<path>` — the first line of an owner-only `0600` file, F12 |
| **Limits** | | |
| `--max-clients` | `64` | refuse further connections past this many simultaneous clients (`0` = no limit) |
| `--client-timeout` | `300` | disconnect clients silent for this many seconds — sheds connections from clients that died without closing (`0` = never) |
| `--max-conn-per-ip` | `0` | refuse further connections from one peer IP past this many simultaneous connections (`0` = no per-IP limit) |
| **Logging** | | |
| `--log-level` | `INFO` | `DEBUG` adds per-client traffic and per-poll detail |
| `--man` | off | print the generated man page (roff) to stdout and exit (`modbus-cache --man \| man -l -`); the shipped pages are the same generator's output |
| `--log-access` | `DEBUG` | log client connects/disconnects at `INFO` instead of `DEBUG` |
| `--local-time` | UTC | log timestamps in the system time zone instead of UTC |

`cache/examples/modbus_cache.conf` is a sample in the set grammar (every line a
`set <name> <value>` in the CLI spelling, `#` comments stay comments — the
config file pipes through `modbus-cache-ctl` unchanged, and `show config`
regenerates it from the running daemon — the secret knobs render as
`set <name> *** SECRET REMOVED ***`, the value never does, and the parser
refuses the placeholder (pass the secret by flag/env, or as `file:<path>`);
`show knobs` prints the whole
registry — every knob with its flag, its env twin and how it changes,
`help config` maps them to their control commands). Boolean config/env
values accept `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`.

## Diagnostics registers

The cache synthesizes a 4-register diagnostics block at **65000** from live
poller state — it is answered instantly, never forwarded, never cached:

| Register | Meaning |
|---|---|
| 65000 | magic `0xCAFE` (validity check for clients) |
| 65001 | `1` if the last completed poll cycle had at least one successful read, else `0` |
| 65002 | seconds since the last successful device read (`65535` = none yet); grows while the device is down |
| 65003 | cache process uptime in seconds |

Reads that straddle the block are rejected with exception `02`; reads past it
behave like any other uncached register. Reply unit ids are validated on
every forwarded request before anything is cached.

## Runtime control (signals)

| Signal | Effect |
|---|---|
| `SIGHUP` | **Reload the configuration and the register map** without dropping client connections: the map is swapped atomically (added ranges are polled, removed ones pruned), poll interval, read delay, merge gap, cache TTL, the ACLs (the `file:` gates re-read), client limits and the upstream address/unit/timeout take effect immediately (the upstream socket reconnects on the next read). A broken file or an invalid value keeps the previous settings — the error is logged and the next `SIGHUP` retries. The listen address needs a restart (the registry's `restart: true` knobs — the listen, the metrics bind, the upstream, restore-on-start — record a live `set` and fold into the restarted process before it binds). |
| `SIGUSR1` | **Clean the cache**: all cached values, on-demand entries and poll-status errors are dropped atomically (client connections stay up), the next reads go to the inverter live and the poller repopulates immediately. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown**: the listener is closed and the shutdown is logged. |

```bash
kill -HUP  $(pgrep -f modbus-cache.py)   # reload config + register map
kill -USR1 $(pgrep -f modbus-cache.py)   # clean the cache
```

## Runtime control (`--control-port`)

A JSON-lines control server runs **by default on the unix socket
`/tmp/modbus-cache-<listen-port>.socket`** — short, determinable, stale
files replaced, nothing ever lands in the working directory. Pass a TCP port
number to bind `127.0.0.1:PORT` instead, or `0` to switch the control server
off. Both the proxy and the CLI tool resolve the target the same way: flag >
the **`CTL`** environment variable > the default socket.

One command per line, one reply per line. Every request and reply is one
JSON object: the request = `{"cmd": "<command>"}`, the reply =
`{"status": "ok|fail|bye", "text": "…"}` — `ok` (the command ran, `text`
is its output), `fail` (the command refused, `text` is the error message),
`bye` (the unsolicited daemon-exit notice). **With `--control-token` set,
connections must authenticate first** — `{"cmd": "auth", "token": "..."}` —
on both transports. Over the unix socket the kernel vouches for the peer
(`SO_PEERCRED`): root, the daemon's own user and the extra
`--control-trust-uids` uids skip the handshake, so a local systemd unit
speaks without sharing the secret; TCP peers always need the token. Without
a token the unix socket relies on filesystem permissions.

**With a token configured the wire is signed**: every command and reply
carries the **full sha256 HMAC of its payload, keyed by the token**
(`"mac": …` next to the payload — `common/wiresec.py`). The token auth
proves who is speaking once; the mac proves it for every frame — a client
holding the token verifies nothing was injected or altered in flight, and
over TCP the signed commands are mandatory (an unsigned or bad-mac frame is
refused; on the unix socket the mac is verify-if-present so the trusted
peers keep speaking without the secret). The audit trail's COMMAND entries
carry the frame's mac (`wire=h…`) — the command the server logs
cryptographically matches the command the client sent.

**The read-only ops role**: a daemon may carry a second token
(`--control-ops-token`, or its `file:<path>` form) beside the admin one.
Sessions authenticating with the ops token may run the **`show`/`clear`
verbs only** — no `set`/`unset`, no `request dump`/`restore`, no `request reload`, no `request restart`,
no `shutdown` (the ops shift can look, flush the cache, and leave; steering
needs the admin key). The gate is the command's head verb; a denied command
answers `err forbidden: the ops token runs the show/clear verbs only (<verb>
needs the admin token)`. Both tokens are audited: the CACHE trail's COMMAND
entries name the session's role (`role=ops`/`role=admin`, the denials
included), and each session's frames are mac'd with the key it
authenticated with — an ops client verifies its own replies against the ops
token, an admin client against the admin token. The peer-cred trusted peers
(`SO_PEERCRED`) hold the admin role.

> **A token flag lands in `ps`.** Tokens passed as `--control-token` /
> `--control-ops-token` / `--metrics-token <secret>` are visible on the
> process command line — every
> local user can read them in `ps` output or `/proc/*/cmdline` (the audit's
> F9; the same applies to the ctl/cli clients). Prefer the **`file:<path>`**
> form — the first line of an owner-only file; the file must be
> **owner-only (`0600`)**: group/world-accessible
> token files refuse to start (F12) — or the `CONTROL_TOKEN` /
> `METRICS_TOKEN` env vars. The flag form is for quick tests.

| Command | Effect |
|---|---|
| `set <setting> <value>` | configure a setting **live**: `modbus interval`, `cache ttl`, `modbus read-delay`, `modbus merge-gap` (the poll plan rebuilds), `write allow`, `write registers` (`any`/`none`/the ranges/`profile`/`file:<path>` — the device profile's acl, re-resolved when the profile swaps), `limits max-clients`, `limits client-timeout`, `limits max-conn-per-ip`, `modbus upstream`, `modbus unit`, `metrics enable`, `metrics listen` (rebinds live), `metrics limits max-clients`/`metrics limits timeout`/`metrics limits max-conn-per-ip`, `metrics token` (rotate live; the value never renders back), `requests-audit`, `dump-interval`, `log-level`, `local-time`, `modbus profile`/`modbus selection` (the register map swaps atomically), `acl connect`, `acl write` (the IP ACLs: `any`/`none`/the networks/`file:<path>` — a file gate re-reads on every set), `modbus timeout`, `modbus auth`/`modbus auth key` and `modbus auth-upstream`/`modbus auth-upstream-key` (the auth schemes and keys, both legs — the upstream leg speaks suite or waveshare), `control port` (rebinds the listener live), `control token` and `control ops token` (rotate live; the value never renders back), `control ops-verbs`, `control trust-uids`, `control socket-group` (re-modes the live socket), `audit log-file` (the trail moves, the chain continues from the file's tail), `audit rotate max-size`/`audit rotate daily`/`audit rotate files`, `audit disable`, `dump path` (arms `request dump` without a restart), `dump with-cache`, `dump restore-on-start` — the reply carries the compact state summary |
| `unset <setting>` | restore a setting to its **configured** startup value (what the flag/env/config said at start) |
| `set`/`unset` a startup-only knob | the registry's `restart: true` rows answer the note: `% restart required (startup-only knob)` — the config (and a SIGHUP, or a restart) changes them; `show <knob>` renders the configured value (a **secret knob refuses to show** — the value renders nowhere) |
| `show <setting>` | the bare live value of one tunable |
| `help <setting>` | the registry description of one setting |
| `inspect` | one pretty multi-line dump of everything — version, upstream, listen/control, profile, cache state, poll plan, counters, the write gate, the audit sink: the baton for a bug report |
| `show status` | the **effective state report**: one stable `key=value` line per field (`upstream`, `unit`, `listen`, `control`, `uptime`, `poll`, `last_poll`, `interval`, `ttl`, `merge_gap`, `ranges`, `fc4_ranges`, `map_version`, `hits`, `misses`, `clients`, `writes`, `write_allow_list`, `requests_audit`, `dump`, `profile`, `selection`) — scriptable |
| `show connections` | connected clients: peer, connection age, requests served |
| `show cache` | cache contents: ranges, cached words, oldest entry, TTL, map version, failed ranges, hit/miss counters |
| `show cache all` | every cached entry, one row per profile range: name, words cached, their values (`-` = not cached), age of the oldest, when it expires, poll status (`ok`/`partial`/`empty`/`failed (ex N)`) |
| `show write registers profile` | the write gate as its acl chain (show-only — nothing to set): `allow any` / `deny any`, a range list as its whitelist (`deny any`, then one `allow START:COUNT` line per range), and in profile mode the device profile's own rules — the gate's `desc` as a `% ` line, then one `allow\|deny <range> # desc` line per range, the comments aligned |
| `show acl connect table` | the connect ACL as its rule chain, one entry per line (show-only): `allow 0.0.0.0/0` (any), `deny 0.0.0.0/0` (none), the whitelist spelled out (`deny 0.0.0.0/0`, then one `allow` line per network) — or the ip-prefix acl file's own rules (the gate `desc` as the `% ` line, the descs as aligned `# ` comments) |
| `show acl write table` | the write ACL as its rule chain, one entry per line — the `show acl connect table` report for `acl/write` |
| `show uplink` | the inverter link: session counters (state, connects, exchanges, bytes in/out, errors, last error) plus one row per poll block — status (`ok`/`ex N`/`error`/`pending`), latency (last/mean/max), failure count, last error |
| `request dump` | write the live setting overrides — and, with `--dump-with-cache` (or the `with-cache` suffix: `request dump with-cache`), the cached words (+ their stamps) — to the `--dump-path` file; the write-behind state, see [Persistence](#persistence); the dump commands (and the `dump-interval` setting) show up in the listings only when a dump path is configured |
| `request restore` | load the dump back: the words return with their original stamps (their TTL bounds any staleness) and the overrides re-apply — what the startup restore does automatically |
| `show version` | the modbus-cache version |
| `show knobs` | the dictionary of all knobs: every registry knob — its flag, its env twin(s), the command that changes it live (or the restart note), a `secret` marker on the tokens |
| `request clear cache` | drop all cached values (like SIGUSR1), repoll immediately |
| `request restart` | drop the upstream connection **and** the cache, repoll now — for recovering from a wedged inverter session |
| `request reload` | **restart the whole daemon with the configuration kept**: the live overrides save to a state file beside the config (`<config>.reload`), the process re-execs with the same argv, the fresh daemon re-resolves the config file (so the `restart: true` knobs take their configured values) and re-applies the saved overrides once, then consumes the state file. The cache starts empty; overridden secrets save as `*** SECRET REMOVED ***` (the value never lands in the file) — the reply names them, to re-pass by flag/env, or as `file:<path>`. The ops role may not request reload |
| `shutdown` | gracefully stop the proxy (same as SIGTERM: listener closed, control socket unlinked) |
| `help` / `?` | one-line command reference |
| `quit` | close the connection |

### Live settings

Every `set` applies immediately and keeps working until the daemon stops —
**or** the next `SIGHUP`, which re-resolves the config (flags, env, the config file) and
re-applies it wholesale: the file always wins on reload. A setting changed
live is listed in `show status`'s `overridden=` row; `unset <setting>`
restores the configured value and clears the entry. This makes the policy
explicit: live settings are
runtime nudges, the config files stay the source of truth.

### `modbus-cache-ctl` — one-shot commands

A small client for scripts and quick pokes: one command as arguments (or a
batch piped on stdin), the replies on stdout, done.

```bash
python3 cache/bin/modbus-cache-ctl.py --control-port 15509 show status
python3 cache/bin/modbus-cache-ctl.py --control-port 15509 clear cache
printf 'show cache\nclear cache\n' | python3 cache/bin/modbus-cache-ctl.py --control-port 15509
```

Same `--control-port` flag / `CTL` env as the proxy itself; the
TCP token comes from `--control-token` or `CONTROL_TOKEN` —
the ops staff pass the **read-only ops token** the same way and the server
assigns the `show`/`clear` role to what the token opens.
Exit codes: `0` = ok, `1` = connection/control error, `2` = CLI misuse.
Every invocation lands in the audit log (below, prefix `CTL`).

### `modbus-cache-cli` — console-style session

An interactive front-end on the same socket (same flag/env resolution): on
the first connect (a TTY) it probes the status and greets you —

```
$ python3 cache/bin/modbus-cache-cli.py

%   Welcome to the modbus-cache console
%   192.168.1.100:5502 upstream | poll ok, last poll 2.00s | running for 1.00h | 1 client(s)
%   TAB completes, ? lists the commands, quit leaves

cache:15502 > show status
upstream=192.168.1.100:5502
unit=1
listen=127.0.0.1:15502
control=unix:/tmp/modbus-cache-15502.socket
uptime=1.00h
poll=ok
last_poll=2.00s
interval=10.00s
ttl=30.00s
merge_gap=8
ranges=13
fc4_ranges=0
map_version=0
hits=412
misses=9
clients=1
writes=disabled
write_allow_list=any
requests_audit=5.00m

cache:15502 > clear cache

cache:15502 > shutdown
Proceed with shutdown? [confirm] y
% bye shutdown
```

The prompt shows the connected port, TAB completes commands with their
descriptions (`show <TAB>` lists the tunables plus status/connections/cache/
version, `?` does the same in any position), `request clear cache` and
`request restart` confirm silently (the prompt returning is the
confirmation), `set`/`unset` confirm `% changed`, and `shutdown` asks
`Proceed with shutdown? [confirm]` first — RETURN
or `y` proceeds, anything else aborts with `% Aborted.`. The errors print
`% error: <message>`, the notes and the bye notices keep the `% ` prefix;
the ok replies print their message bare (quiet success) — the `show`
reports and the tables are the values and print
bare. While it idles the
CLI sends wire pings (every 55 s, `CLI_KEEPALIVE` to tune, `0` = off)
so the control server's idle timeout never drops a live session. When the
connection dies anyway (the proxy was killed, the socket went dark), the
CLI retries **`--reconnect` times (default 3)** with **`--reconnect-wait`
seconds (default 10)** between the attempts, printing the progress and
resuming the session on the first success; every attempt lands in the audit
trail (`RECONNECT`). `--reconnect 0` restores the old die-on-loss behaviour.
The session itself (connect/disconnect, the local commands, an aborted
shutdown) is appended to the CLI's own audit trail (prefix `CLI`,
`--audit-log` / `--no-audit-log`); the commands themselves are audited by
the server (prefix `CACHE`, with the client peer). TCP targets authenticate
with `--control-token` or the `CONTROL_TOKEN` env — the same
token the proxy was started with.

## Access control

The family-wide ACL map — the rule-chain semantics, the standalone acl
file, the tools and where every tool's support stops — lives in
[docs/ACL.md](../docs/ACL.md).

**`connect-acl` defaults to `any`** (who may connect is the listen bind's
job — the default bind is loopback); **`write-acl` and `write-registers`
default to `none`** — the write path is closed even before `--allow-write`
enters the picture. Both ACLs take a comma-separated list of IPs and CIDR
prefixes (IPv4 or IPv6, e.g. `--connect-acl 127.0.0.1,10.48.3.0/24`), or
the two words `any` (no restriction) and `none` (refuse every peer —
restrict all), or **`file:<path>`** — the standalone ip-prefix acl file
described below; the config-file/env/NixOS forms are
`connect_acl`/`write_acl`/`write_registers` (NixOS
`connectAcl`/`writeAcl`/`writeRegisters`).

- **Connect ACL** — who may connect at all; `none` rejects every connection
  at accept (logged: `connection rejected: … not on the connect ACL`). From
  the client's view the connection opens and immediately dies.
- **Write ACL** — whose write requests are forwarded; everything else is
  refused with a Modbus illegal-function exception, logged with the client
  IP and the attempted payload. The connection stays up and reads keep
  working. `none` (the default) refuses every client's writes.
- **Write registers** (`write-registers`) — the ranges a forwarded write
  may touch; `none` (the default) refuses every write regardless of the
  client, `any` lifts the register check entirely. **`profile`** takes the
  gate from the device profile: the profile's `"acl"` → `"write"` gate —
  an optional terse-ASCII `desc` and the ordered `rules` list, one
  `{"type": "allow"|"deny", "range": "START:COUNT"|[...]|"any"}`
  object per rule, each rule optionally described by a terse-ASCII
  `desc` (per gate or per rule; a rule's `desc` speaks for every range
  in its list). The chain
  is a whitelist: it reads top to bottom, **the last matching rule
  decides**, and a register no rule decides refuses (the default deny
  any).   `deye-sg05lp3`, for example, allows only the TOU schedule slots
  (148–177) and the grid-start registers (127–128). A profile without an
  `acl`/`write` section refuses the `profile` value (a gate that is not
  there would be silent). **`file:<path>`** takes the gate from a
  standalone acl file instead — the file IS the gate object a profile
  carries under `acl`/`write` (the same `desc` + `rules` shape, the same
  whitelist semantics), read and compiled at start and on every `set`; a
  missing or bad file refuses the start and answers `err` on the wire
  with the old gate standing, and the spelling round-trips through the
  dumps and `unset`. An example ships as
  `cache/examples/acl-write-registers.json` (the
  deye policy, worked out: the clean-slate deny, the allows, the deny
  carves and the re-opens — every matcher form). **A group/world-readable
  acl file warns** (the gate is config trust any local user could have
  loosened: chmod 0600) — in the log, the audit trail's `ACL-FILE`
  event, and as the suffix of the `set`/`unset` reply; a `0600` file is
  silent. `show write registers profile` answers the gate
   back as its chain — one `allow`/`deny` line per range, the profile's
   descs included (the file's rules render the same way).

**The connect and write ACLs read the same standalone acl files**:
`--connect-acl file:<path>` / `--write-acl file:<path>` (and their `set`
spellings) load the gate whose root object is the
`"type": "ip-prefix"` gate — the shipped `examples/acl-ip-prefix.json`:
an optional terse-ASCII `desc`, the ordered `rules` list, one
`{"type": "allow"|"deny", "prefix": "any"|IP|IP/prefix, ...}`
object per rule (comma-separated prefixes fan out), each rule optionally
described. The chain reads top to bottom, **the last matching rule
decides**, and a client no rule decides refuses (the default deny any);
the matcher word `any` is the whole space — `0.0.0.0/0`. The file is read
at start and on every `set`/`unset`: a missing or bad file refuses the
start and answers `err` on the wire with the old gate standing, the
spelling round-trips through the dumps and `unset`, and a
group/world-readable file warns exactly like the write-registers acl
file (the log, the audit trail's `ACL-FILE` event, the set/unset reply's
suffix; a `0600` file is silent). **`show acl connect table` /
`show acl write table`** (show-only) render either ACL as its chain, one
entry per line: the system forms spell the chain they implement —
`allow 0.0.0.0/0` (any), `deny 0.0.0.0/0` (none), `deny 0.0.0.0/0` then
one `allow` line per network (the whitelist) — and a file gate renders
its own rules, the gate desc as the `%` line, the rule descs as aligned
`#` comments.

Writing is therefore gated four times: `--allow-write` **and** the client
on the write ACL **and** every touched register inside the allow-list
(and the frame parse gate first) — with `write-acl` and `write-registers`
defaulting to `none`, enabling `--allow-write` alone still refuses every
write until the operator opens those two deliberately (in the config or
live with `set`). For FC23 (read/write multiple registers) the touched
registers are the written span — the request's second address pair; the
read span riding first is not vetted. A bulk write whose byte count lies
about its data (FC15/16) never reaches the device: the cache answers
exception 03 itself and audits the refusal. The coil writes (FC05/15) are
gated by the same address ranges as the register writes — the coil space
shares the numeric range.

ACLs re-resolve on `SIGHUP` like every other setting; a malformed list keeps
the previous one.

## Modbus auth

Beyond the address-based ACLs the cache speaks the family's **`suite`**
Modbus auth — a proof-of-key handshake on the Modbus TCP wire itself, one
round trip after the TCP connect and before any Modbus frame:

- the client sends 52 bytes: the 4-byte magic `PVA1`, a fresh 16-byte nonce
  and the HMAC-SHA256 of the domain-tagged magic+nonce keyed by the shared
  key (stdlib only — the same HMAC discipline the state dumps seal with);
- the server recomputes the proof and answers **`OK`** (the session then
  speaks plain Modbus TCP) or **`ERR`** (the connection is dead — a client
  that cannot prove the key never sees a frame, and a client of a wrongly
  configured peer fails its connect exactly like a down device).

The two legs are configured separately, with separate keys:

- **`--auth` / `--auth-key`** — the auth the cache's *own clients* must
  speak on the listen port (the server side): with `--auth suite`, every
  connecting client handshakes first; a failed proof is logged
  (`suite auth failed for …, closing`) and dropped. `none`/empty (the
  default) = no auth at all.
- **`--auth-upstream` / `--auth-upstream-key`** — the auth the cache
  *presents* to the upstream inverter (the client side): with
  `--auth-upstream suite`, every (re)connect handshakes first; an `ERR`
  fails the poll cycle like any other upstream failure and the poller
  retries. `--auth-upstream waveshare` speaks to a **Waveshare
  RS485-to-TCP gateway** instead: the gateway guards its serial side with
  an optional connection password, and the cache presents the shared
  auth-upstream-key as exactly that — the password goes out raw (ASCII
  bytes, no framing) right after every (re)connect, and the gateway's
  `OK` opens the plain Modbus session; anything else (or nothing — a
  wrong password gets the connection dropped) fails the poll cycle and
  the poller retries. The upstream-only scheme of the pair: the cache's
  own clients always speak `suite` or nothing.

Both keys are secrets (enforced at start and on the live `set`; they
never render back, and `file:<path>` references load from an owner-only
`0600` file). The floor is the scheme's: the suite handshake needs at
least 16 characters, the Waveshare gateway password needs non-empty
ASCII — a key set while no scheme is chosen yet is dormant material, and
the floor bites when the scheme names it. Both knobs are live-settable:
`set modbus auth suite` gates the next connection (standing sessions
keep theirs), and `set modbus auth-upstream …` drops the upstream session
so the next exchange re-proves under the new material. The peer must
speak the same scheme with the same key — the fake inverter serves the
server side (`--auth suite --auth-key …`) and the scraper speaks the
client side (`--auth suite --auth-key …`), so a chain
scraper → cache → inverter can run suite auth on either hop
independently.

## Write-through invalidation

A forwarded write lands on the device, and the cache immediately drops the
cached words it touched (per-register — the rest of the cache stays warm)
and wakes the poller. The next read of the written range goes to the device
instead of serving the pre-write value until the TTL expires. The register
writes (FC06/16/22/23) drop the touched span in **both** register spaces
(holding and input — a device is free to mirror); the coil writes (FC05/15)
drop the touched span in the coil space (FC1), which a profile's `bit`
entries may cache.

## Persistence

`--dump-path` turns on the **write-behind state dump**: the live setting
overrides and — when asked — the cached words (+ their original stamps, so
freshness carries over — the poll ranges, the bridged gaps and the
on-demand entries alike), as one human-readable JSON — written atomically
(tmp + rename). **What lands in the file is split** (F18: the words are
production data, the settings are config): by default **settings only**;
**`request dump with-cache`** includes the words, and **`--dump-with-cache`**
flips the plain `request dump` and the `--dump-interval` loop to the full
shape (the shutdown dump follows the flag too). The restore takes either
shape — it loads whatever the file carries. An overridden **secret** rides
as `*** SECRET REMOVED ***` — the knob renders, the value never lands in
the file; the restore skips the placeholder (the secret keeps its current
value) and names it. The dumps land in three ways:
every `--dump-interval` seconds (live-settable
`set dump-interval`, `0` = off — the default: on request), on the
**`request dump`** command, and on every
graceful shutdown. Loading is gated: **`--restore-on-start`** opts in to
loading the dump when the daemon starts (a restart serves last-known
values instead of cold misses — pair it with `--dump-with-cache` so the
words ride along); the default is starting cold — the
**`request restore`** command loads it on demand. Either way the words
return as they were —
their TTL bounds any staleness, and the next map swap prunes what the
profile no longer names — and the setting overrides re-apply through the
same gate a `set` speaks (`interval=2.00s` survives the restart, a moved
profile file is skipped with a note). With `selection none` the word-restore
is a no-op (the cache stays empty by design). The dump commands (and the
`dump-interval` setting) show up in the listings — the completions, `?`,
`help` — only when a dump path is configured.

**The dump is config-equivalent trust at rest** (the audit's F18) — and it
is treated that way: the file is created **`0600`** explicitly (never the
umask; the words are production data and the settings re-apply through the
live validation), every dump carries a **sha256 integrity hash** of its
canonical content, and a restore **fails closed**: an edited, truncated or
unsigned dump refuses with a one-liner (`fails its integrity hash` /
`predates the integrity hash`), and a group/world-writable dump refuses
outright — whoever can write the dump holds config trust, so own the file
like the config file (`chmod 0600`). The honest boundary, same as the audit
trail's: the hash catches corruption and casual tampering, not a local
admin who rechashes.

With **`--dump-key`** set, the dump is **sealed**: the whole state — words
included — rides encrypted under an HMAC-SHA256 counter-mode keystream
derived from the key and authenticated by an HMAC-SHA256 mac (stdlib only
— no AES in the stdlib; the nonce is fresh per dump, so the same state
never seals to the same box twice). The mac is checked first: a wrong key
reads as tampered content and fails closed (`fails its seal`), never as
garbage. The gate is symmetric — a restore without the key refuses a
sealed dump, and a restore **with** a key refuses an unsealed one (the
plain hash is unkeyed; the moment the operator declares a key, plaintext
stops being trust at rest). The reload's state file seals under the same
key — the re-exec re-resolves the same flag/env/config key, so the fresh
daemon reads what the dying one wrote. That is also why the knob is
startup-only: `set dump key` answers the restart note — the key cannot
drift between the writer and the reader of a sealed file.

The key rides inline or **as a reference**: `--dump-key file:/path` (env
`DUMP_KEY=file:...`, config `set dump key file:...`) reads the first line
of an owner-only `0600` file — a systemd LoadCredential rides as
`file:/run/credentials/...`. One knob, two forms: the config file then
carries the reference, never the material (and a reference that cannot be
read fails the start — a key that silently vanishes is a misconfiguration,
not a fallback to plaintext). The same `file:` reference form works on
every secret value: `--control-token file:/path`, `set metrics token
file:/path` — one spelling, the same loader and 0600 discipline everywhere. Without a key a dump path stays plaintext **by design** — and
says so: a `WARNING` at start and a `(not sealed — set dump/key to encrypt
at rest)` note on the `set dump path` reply.

## Metrics

`--metrics-server` (off by default, live-settable `set metrics enable
on/off`) serves the cache's own Prometheus `/metrics` on the
`--metrics-listen HOST:PORT` address (default `127.0.0.1:9252`; `0.0.0.0`
serves every interface) — the self-observability without the
scraper's `scraper_cache_*` export path. The whole surface is live
now: `set metrics listen` rebinds the endpoint (the old address
closes, the new one serves), the `metrics limits` caps apply to the
running gate (`max-clients` 503s past the cap, `timeout` kicks the
idle, `max-conn-per-ip` sheds one peer), and `set metrics token`
rotates the credential without a restart (the value may be `file:<path>`
— the first line of an owner-only `0600` file) — the
token never renders back (`show metrics token` **refuses** — it is a
secret; `unset` refuses too: set the new one). The gauges:
`modbus_cache_hits_total` /
`modbus_cache_misses_total`, `modbus_cache_poll_up` +
`modbus_cache_last_poll_age_seconds`, `modbus_cache_age_seconds` (the
oldest cached word), `modbus_cache_words` / `modbus_cache_ranges` (the
`fc` labels), `modbus_cache_clients`, the uptime and the poll-cycle
durations (`modbus_cache_poll_duration_seconds{,_mean,_max}`). The
uplink exports the session state — `modbus_cache_uplink_up`,
`modbus_cache_uplink_{connects,exchanges,errors}_total`,
`modbus_cache_uplink_bytes_total{dir=in|out}`,
`modbus_cache_uplink_last_error_age_seconds` — and every poll block as
`modbus_cache_uplink_block_up{fc,start,count}`,
`modbus_cache_uplink_block_latency_seconds{,_mean,_max}` (absent while
the block fails) and `modbus_cache_uplink_block_fails_total` (see
`show uplink`). With
`--metrics-token` set, requests need
`Authorization: Bearer <token>` — the same scheme the scraper's exporter
speaks; anything but `/metrics` answers 404, an unauthenticated read 401.
The endpoint is capped on every bind (the token stays mandatory regardless): `--metrics-max-clients`
(default 64; extras get an immediate `503 # rate limited`),
`--metrics-client-timeout` (default 5 s; 0 = the same built-in cap) and
`--metrics-max-conn-per-ip` (default 0 = no per-IP limit). A scrape job
reads it like any bearer endpoint — `authorization: {type: Bearer,
credentials_file: /etc/prometheus/metrics.token}` in the job config (the
docker demo's `prometheus.yml` ships this wired).

## Audit logging

The proxy logs every audit-relevant event to stdout/stderr with UTC
timestamps by default (`--local-time` switches to the system time zone).
Under systemd, journald stores, seals and rotates these lines — point your
NIS2/DORA documentation at `journalctl -u modbus-cache` and keep a retention
policy (e.g. `/etc/systemd/journald.conf`: `MaxRetentionSec=90day`). Modbus
has no authentication, so the client's source IP is the only identity there
is (connect/disconnect events are logged at `DEBUG` unless `--log-access`
is set).

| Event | Log line |
|---|---|
| Forwarded write | `write: register 47415 = 99 (single register, unit 1)` |
| Write refused (support disabled) | `write: refused register … (write support disabled …)` |
| Write refused (ACL) | `write: refused register … (client 10.0.0.5 not on the write ACL)` |
| Device rejects a forwarded write | `write rejected by the device: … (modbus exception N)` |
| Forwarded frame with no cache semantics (FC07/08/17/…) | `forwarded FC17 (report slave id), 0 byte(s) (unit 1)` |
| Device rejects a forwarded frame with no cache semantics | `forwarded FC17 (report slave id) rejected by the device (modbus exception N)` |
| Uncached read forwarded + cached | `read: registers … not cached, polling the device` / `… ok, cached …` |
| Device rejects a forwarded read | `read: registers … rejected by the device (modbus exception N)` |
| Connection rejected (ACL) | `connection rejected: 10.0.0.5:51234 not on the connect ACL` |
| Connection refused (limit) | `connection refused: client limit of N reached (…)` |
| Config/register-map reload (`SIGHUP`) | `SIGHUP: reload requested` / `SIGHUP: reloaded 13 range(s) …` / `SIGHUP: reload failed …` |
| Cache clean (`SIGUSR1`) | `SIGUSR1: cache cleared (N register(s) dropped), repolling now` |
| Cache poll failed/recovered | `poll of … failed (FC3 modbus exception, code 2), serving cached values` / `poll of … recovered` |
| Client connect/disconnect (`--log-access`) | `client connected: 10.0.0.5:51234` / `client … disconnected (…)` |
| Startup / shutdown | `caching 13 range(s) …` / `shutdown: SIGTERM received, closing the listener` |

Useful filters:

```bash
journalctl -u modbus-cache --since today | grep 'write:'      # all write attempts
journalctl -u modbus-cache | grep -E 'SIGHUP|shutdown'        # lifecycle
journalctl -u modbus-cache | grep -i 'not on'                 # ACL rejections
```

### The audit trail

On top of the operational log, the proxy and the CLI append to an
**append-only audit file** — one line per event, who/when/what/result, on
by default at the **XDG state home**
(`~/.local/state/modbus-cache/audit.log`, NOT the working directory: a
packaged install has a read-only one). `--audit-log <file>` renames it,
`--no-audit-log` turns it off. **`--audit-log -` sends the trail to
stdout, not stderr** — the audit is data, not an error, and stdout keeps it
in the single ordered stream the service manager captures (docker logs,
journald); the NixOS module ships with it (a hardened service cannot write
the state home anyway). `--audit-files N` (the default 3) sets how many
rotated backups the file sink keeps; the stdout sink never rotates. If the
audit file cannot be opened, the trail falls back to stdout rather than
vanishing. **Rotation is gated**: `--audit-max-mb 10` (the default) rotates
at 10 MB keeping 3 backups (`audit.log.1..3`), `--audit-daily` additionally
rotates at UTC midnight, `--audit-max-mb 0` = unbounded.

The prefix names the writer — `CACHE` (the proxy), `CLI` (modbus-cache-cli) and
`CTL` (modbus-cache-ctl):

```
2026-11-04T07:16:40Z AUDIT CACHE START 4e1b92f0c7a3 version=0.4.2 upstream=192.168.1.100:5502 unit=1 listen=127.0.0.1:15502 control=unix:/tmp/modbus-cache-15502.socket profile=/nix/store/…-sun2000.json
2026-11-04T07:16:43Z AUDIT CACHE WRITE b2c4e17f90d8 register 47415 = 5 (single register, unit 1)
2026-11-04T07:17:02Z AUDIT CACHE AUTH-FAIL 6f3d84a1e2c9 peer=127.0.0.1:54425
2026-11-04T07:17:12Z AUDIT CACHE COMMAND 09ab57d3f4e1 peer=127.0.0.1:54426 'clear cache' -> ok
2026-11-04T07:17:20Z AUDIT CACHE COMMAND 5c92f1b8d3a7 peer=127.0.0.1:54427 role=ops 'clear cache' wire=h1e6070592485 -> ok
2026-11-04T07:17:24Z AUDIT CACHE COMMAND e7d04c62f9b1 peer=127.0.0.1:54428 role=ops 'shutdown' wire=h8b21cf6403de -> err
2026-11-04T07:17:30Z AUDIT CACHE REQUESTS 71d0c93be8f5 peer=127.0.0.1:54425 requests=412 (last 300s: 380)
2026-11-04T07:17:30Z AUDIT CLI CONNECT 3a8e5f1c2d94 target=127.0.0.1:15502 user=oom
2026-11-04T07:17:45Z AUDIT CACHE REQUESTS cc17e5b2a4f8 peer=127.0.0.1:54425 requests=412 connected=342s
2026-11-04T07:17:45Z AUDIT CACHE SHUTDOWN d94a1f07c3e2 SIGTERM received: uptime=65s clients=1 hits=412 misses=9
2026-11-04T07:18:02Z AUDIT CTL CONNECT 58c3f9e21b70 target=unix:/tmp/modbus-cache-15502.socket user=oom
```

The 12-hex token after the event name is the entry's **chained hash** (the
audit's F10): each entry hashes the writer's previous entry into its own —
any edit, deletion or reordering in the middle of a prefix's trail shows up
as a chain break in `scripts/audit_verify.py` (run it on this file, the
family's XDG trails, or a journald dump on stdin).

UTC stamps, the command as entered and its outcome — the structured
who-when-what evidence trail. **Every wire command is audited once, by the
server** (`AUDIT CACHE COMMAND`, with the client peer — it knows the who,
and the role — the ops shift against the admin key — plus the frame's mac
when the wire is signed); the denied ops attempts are in the trail too.
The CLI audits its session (CONNECT/DISCONNECT, the local-only events like
an aborted `shutdown`, RECONNECT attempts). The proxy audits its lifecycle
(`START`, `RELOAD`, `RESET`, `SHUTDOWN`), every forwarded/refused/rejected
write, the per-client REQUESTS
tallies and the TCP control `AUTH-FAIL`s. ping/pong keepalives are never
logged; the file is flushed per event, so a crash keeps everything up to
the last command. The trail is **thread-safe** (one writer lock around the
write+flush+rotate cycle) — the proxy's client threads audit every
forwarded write concurrently. The per-client **request accounting** (reads
and writes alike) runs on the same trail: one `REQUESTS` event per client
per `--requests-audit` period (default 300 s — who is hammering the cache)
plus a final tally on every disconnect (`REQUESTS peer=… requests=812
connected=342s`).

The operational log above keeps mirroring the events at INFO; the audit
file is the structured evidence trail, not a duplicate of it.

## Testing

Four standalone suites live in the suite-root [`tests/`](../tests/) — stdlib only, each starts its
own fake inverter + proxy on scratch ports and cleans up after itself:

```bash
python3 tests/cache-regtest.py    # the functional battery (cache + FC4, forwarding,
                                  #   writes/refusals/allow-list, diagnostics registers,
                                  #   device death, poll status, reloads, live
                                  #   set/unset settings, inspect, hostile-upstream
                                  #   phase, JSON control + token auth (inline or
                                  #   file:<path>) +
                                  #   audit trail + ctl/cli clients)
python3 tests/cache-stress.py     # 100 clients / 15 s load + latency report
python3 tests/cache-fuzz.py [n]   # n client-garbage frames (default 3000)
python3 tests/cache-control-fuzz.py   # hostile JSON against the control server
```

Every scenario must end with the proxy alive and **zero tracebacks** in the
logs — the hostile-upstream phase (garbage replies, short bodies, lying
lengths, wrong transaction/unit ids, stalls, junk tails) proves that per
mode, including recovery when the device starts answering sanely again.

## Nix / NixOS

```bash
nix run .#modbus-cache -- --upstream 192.168.1.100:5502
```

The package ships three binaries: `modbus-cache` (the proxy),
`modbus-cache-ctl` (one-shot control commands) and `modbus-cache-cli` (the
console-style control session), plus the man pages
(`man/modbus-cache.1`, `-ctl.1`, `-cli.1`) under `share/man/man1/`.

```nix
imports = [ inputs.pv-dash.nixosModules.modbus-cache ];

services.modbus-cache = {
  enable = true;
  upstream = "192.168.1.100:5502";  # the inverter's LAN IP (:PORT)
  listenHost = "0.0.0.0";           # only when Modbus clients live on other hosts
  openFirewall = true;              # together with a non-loopback listenHost
};
services.modbus-scraper = {
  enable = true;
  upstream = "127.0.0.1:15502";     # the proxy
};
```

Options: `upstream` (`HOST:PORT`, `:PORT` = loopback), `unitId`, `timeout`,
`interval`,
`readDelay`, `mergeGap`, `profile` (device-profile JSON path; null = the
bundled `sun2000` profile), `cacheTtl` (unset = 3× `interval`),
`listenHost`, `listenPort`, `allowWrite`, `writeRegisters` (the
START:COUNT allow-list, `any`, `none`, `profile` (the device profile's
acl gate) or `file:<path>` (the standalone acl file); null = the proxy
default `none`), `connectAcl` (`any`/`none`/prefixes or `file:<path>`;
null = `any`),
`writeAcl` (`any`/`none`/prefixes or `file:<path>`; null = the proxy
default `none`),
`auth`/`authKey` (the suite scheme + key the cache's clients must speak;
null = no auth), `authUpstream`/`authUpstreamKey` (the scheme + key toward
the inverter — suite or waveshare; null = no auth),
`maxClients`, `clientTimeout`, `logLevel`, `localTime`,
`logAccess`, `openFirewall`, `auditLog` (null = the trail goes to
**stdout**, which journald captures — the hardened service cannot write
the XDG state home), `auditMaxMb`, `auditDaily`, `auditFiles`, `requestsAudit`
(null = 300 s), `controlPort` (a TCP port on 127.0.0.1 or a unix socket
path — use one under `/run/modbus-cache/`, `/tmp` is private to the
service), `controlToken` (**world-readable in the store config** — prefer the
file), `controlTokenFile` (mounted via systemd `LoadCredential`). Unset
options keep the proxy defaults. The service runs with a dynamic user and
systemd hardening.

The module renders the **config script (the set grammar) and the register
map into the store** and runs the service with `--config`. A `nixos-rebuild switch` applies
changes with `systemctl reload` (SIGHUP): register map, poll interval, cache
TTL, ACLs, limits and the upstream address are picked up live, client
connections stay up. Changes to `listenHost`/`listenPort`/`logLevel` need a
manual `systemctl restart modbus-cache`.

## Security

Modbus TCP (as spoken by the SUN2000 inverter and this proxy) has no auth,
no encryption and no access control — the proxy forwards writes, so **anyone
who can reach the listen port can read** inverter registers (writes are
gated four times and default closed: `--allow-write` is off, `write-acl`
and `write-registers` are `none`). The proxy therefore **binds
to 127.0.0.1 by default**; widen `listenHost` deliberately, keep it on a
trusted LAN, and don't expose it to the internet. The connect/write ACLs add
per-source control within the LAN; for stricter isolation use the firewall
(`openFirewall`, with a non-loopback bind).

Python is memory-safe (no buffer overflows, all request sizes bounds-checked
and fuzzed), but connection resources are not unlimited:
`maxClients` (default **64**) caps simultaneous clients (each is a thread)
and `clientTimeout` (default **300 s**) reaps clients that died without
closing; set `0` to disable either. The control server binds loopback
(TCP) or a world-0600 unix socket; a TCP control port can additionally
require the token handshake (`--control-token`, see
[Runtime control](#runtime-control---control-port)).

## Source layout

```
cache/
├── bin/
│   ├── modbus-cache.py  # CLI, logging setup, signal handling
│   ├── modbus-cache-ctl.py     # one-shot control client (args / piped commands)
│   └── modbus-cache-cli.py     # console-style interactive control session
├── examples/
│   ├── modbus_cache.conf    # sample config in the set grammar (installed beside the script)
│   ├── selection.json       # example selection: the essential monitoring set
│   ├── acl-write-registers.json  # example acl file: the deye write policy, worked out (--write-registers file:...)
│   └── acl-ip-prefix.json   # example acl file: the connect/write IP policy (--connect-acl file:... / --write-acl file:...)
├── man/                     # the generated man pages (scripts/gen_man.py)
├── module.nix               # the NixOS service module
├── package.nix              # the package (the bins, the libs, the examples, the man pages)
└── lib/
    ├── static.json      # the static constants: protocol limits, diagnostics block, defaults
    ├── statics.py       # its loader (the STATIC dict + the named aliases)
    ├── options.json     # the registry: one row per knob (the flags, the env twins, the help)
    ├── options.py       # its loader + the control-grammar wiring
    ├── config.py        # settings resolution + device-profile/acl-gate loading
    ├── upstream.py      # the shared inverter connection
    ├── cache.py         # register cache + block planner
    ├── proxy.py         # poller + client handling
    ├── metrics.py       # the Prometheus /metrics endpoint (the cache's gauges)
    ├── persist.py       # the state dump writer/reader (the seal, the integrity hash)
    ├── control.py       # JSON-lines control server (inspect/show/clear/restart/shutdown, token auth + the read-only ops role)
    └── man.py           # the man-page builder (the prose sections)
```

The shared pieces — the audit trail, the signed wire, the config/token
plumbing, the Modbus core, the version — live in the suite-root
[`common/`](../common/) package.

## License

The proxy (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the repo-root `LICENSE` file.
