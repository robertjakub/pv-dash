# modbus-cache

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) **Modbus TCP caching proxy** for devices
that accept only a single client — Huawei SUN2000 inverters and their
SDongle/EMMA radios are limited to one Modbus TCP connection, so the
[modbus-scraper](../scrape/README.md) cannot share them with anything else.

> **Experimental — so far verified only against simulated data**
> (fake inverter, fuzzing and regression/stress suites), not against real
> hardware.

## How it works

The proxy owns the one upstream connection the device allows and multiplexes
it:

- a background loop **polls the configured register ranges** from the inverter
  at a fixed interval into an in-memory cache;
- any number of clients connect to the proxy and are **served FC3 reads from
  the cache** — no per-client inverter traffic;
- reads **outside the cached ranges** (and any other function code: FC4,
  writes, …) are **polled from the inverter live**, answered, and — for FC3
  reads — **cached for `--cache-ttl`** like everything else. Such a read
  waits for a free slot between poll reads, at most one transaction + read
  delay;
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
[scraper](../scrape/README.md) scrapes; the shipped profiles live in the
suite's [`profiles/`](../profiles/) subproject (`sun2000.json` by default).
The profile JSON format is documented in
[profiles/README.md](../profiles/README.md).
Resolution: `--profile` flag, env `MODBUS_CACHE_PROFILE`, ini `profile`,
then the bundled copy; the file is re-read on `SIGHUP`. Entry `type`
(i16/u16/i32/u32) gives the word width, `name` decorates the poll logs, and
the optional **`fc`** field picks the address space: `3` (holding
registers, the default) or `4` (input registers) — the two spaces are
cached and polled independently, and both are served from the cache on
their own function code. The optional **`ttl`** field overrides the cache
TTL per entry (seconds; `0` = never expire) — a fast power word at 5s next
to a nameplate word at 1h, one poll cadence for both; `show cache all`
marks the entries carrying one (`[ttl 5s]`). The entry TTL **replaces** the
global one in both directions: a lower entry TTL shortens the freshness, a
higher one lengthens it — the global TTL is only the fallback for the
entries without their own, never a floor.

Which registers are actually **fetched** comes from a selection file —
`{"registers": ["pv-power", "grid-power", ...]}`, profile names only —
resolved as `--selection` flag, env `MODBUS_CACHE_SELECTION`, ini
`selection`; the default fetches **every** profile entry (`all`), and
**`none`** empties the map: every read forwards to the inverter and nothing
is stored (a pass-through proxy, the cache gauges go quiet). The shipped
**`selection.json`** (in the subproject root) is an example — the essential
SUN2000 monitoring
set (the classic 13-range map, by name). Reads outside the selected set are
forwarded to the inverter (FC3 and FC4 alike — a forwarded FC4 read is
cached on its way through, under its own function code). The 65000-65003
diagnostics
block is not a device register — it never appears in a profile and is never
fetched: the cache synthesizes it from its own poller state (FC3 only).

For slow dongles the poller reads the map in as **few transactions as
possible**: ranges closer together than `--merge-gap` registers (default 8)
are merged into one block read, which may also cover registers between the
listed ones (those are cached too) — never across the FC3/FC4 boundary. A
block that fails — e.g. because it spans an unmapped register — is split in
halves and the pieces are retried; the plan converges to the largest blocks
the device actually answers.

## Usage

```bash
python3 cache/bin/modbus_cache.py --host 192.168.1.100
```

By default the proxy **binds to 127.0.0.1:15502** (loopback only) — pass
`--listen 0.0.0.0:15502` when Modbus clients live on other hosts.

Add **`--dry-run`** to validate the configuration and the register map and
print the effective settings (poll plan, ACLs, limits) without binding the
listen port or contacting the inverter — handy for checking NixOS-rendered
config files (`--config /nix/store/…-modbus_cache.ini --dry-run`).
Exit codes: `0` = valid; `1` = invalid (reason on stderr, stdout stays
clean); `2` = command-line misuse.

Point the scraper (or any other Modbus client) at the proxy instead of the
inverter:

```bash
python3 scrape/bin/modbus_scraper.py --host 127.0.0.1 --modbus-port 15502
```
The scraper auto-detects the diagnostics block and exports it as
`huawei_cache_*` Prometheus gauges — device-down-behind-cache becomes visible
downstream instead of flowing through as fresh data.

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`modbus-scraper`:

1. CLI flags (`--host`, `--listen`, …)
2. Environment variables — same names prefixed: `MODBUS_CACHE_HOST`,
   `MODBUS_CACHE_PORT`, `MODBUS_CACHE_UNIT`, `MODBUS_CACHE_TIMEOUT`,
   `MODBUS_CACHE_LISTEN`, `MODBUS_CACHE_INTERVAL`, `MODBUS_CACHE_READ_DELAY`,
   `MODBUS_CACHE_MERGE_GAP`, `MODBUS_CACHE_PROFILE`,
   `MODBUS_CACHE_TTL`, `MODBUS_CACHE_ALLOW_WRITE`, `MODBUS_CACHE_LOCAL_TIME`,
   `MODBUS_CACHE_LOG_ACCESS`, `MODBUS_CACHE_MAX_CLIENTS`,
   `MODBUS_CACHE_CLIENT_TIMEOUT`, `MODBUS_CACHE_CONNECT_ACL`,
   `MODBUS_CACHE_WRITE_ACL`, `MODBUS_CACHE_WRITE_REGISTERS`,
   `MODBUS_CACHE_LOG_LEVEL`, `MODBUS_CACHE_CONTROL_TOKEN`,
   `MODBUS_CACHE_CONTROL_TOKEN_FILE`, `MODBUS_CACHE_CONTROL_TRUST_UIDS`,
   `MODBUS_CACHE_DUMP_PATH`, `MODBUS_CACHE_DUMP_INTERVAL`,
   `MODBUS_CACHE_AUDIT_LOG`,
   `MODBUS_CACHE_AUDIT_MAX_MB`, `MODBUS_CACHE_AUDIT_DAILY`,
   `MODBUS_CACHE_AUDIT_FILES`, `MODBUS_CACHE_NO_AUDIT_LOG`,
   `MODBUS_CACHE_REQUESTS_AUDIT`
3. Config file (snake_case keys, `[cache]` section) — `--config` picks the
   file (default: `modbus_cache.ini` next to `modbus_cache.py` — the
   packaged layout — then the subproject root's sample; a missing file
   is fine)

Every setting is validated before use — nonsense values (negative intervals,
out-of-range ports, bad unit ids, malformed ACLs, unknown log levels) abort
with a clean one-line error instead of failing later at runtime.

| Flag | Default | Meaning |
|---|---|---|
| **Upstream** | | |
| `--host` | `127.0.0.1` | inverter/dongle Modbus TCP address |
| `--port` | `5502` | inverter Modbus TCP port |
| `--unit` | `1` | Modbus unit id (1–247) |
| `--timeout` | `3` | Modbus connect/read timeout, seconds |
| **Proxy** | | |
| `--listen` | `127.0.0.1:15502` | proxy listen address `HOST:PORT` (loopback by default) |
| `--profile` | the bundled `sun2000` profile | device profile JSON to cache (see above) |
| `--interval` | `10` | seconds between cache polls |
| `--cache-ttl` | 3× `--interval` | per-register cache TTL in seconds: older entries are refetched from the inverter (`0` = never expire) |
| `--read-delay` | `0.05` | seconds between consecutive inverter reads within a poll cycle (`0` = no wait) |
| `--merge-gap` | `8` | max register gap when merging ranges into block reads (`0` = read separately) |
| **Behaviour toggles** | | |
| `--allow-write` | disabled | forward write requests (FC05/06/15/16/22/23) to the inverter; disabled, they are refused with a Modbus illegal-function exception (ini `allow_write`, env `MODBUS_CACHE_ALLOW_WRITE` accept `true`/`false`) |
| `--write-registers` | `none` | register ranges a forwarded write may touch: comma-separated `START:COUNT`, e.g. `47400:100,47600:100` — every touched register must land inside a range, anything else is refused with a Modbus illegal-function exception; `any` = every register writable, `none` = no register writable (the default) (ini `write_registers`, env `MODBUS_CACHE_WRITE_REGISTERS`) |
| `--connect-acl` | `any` | clients allowed to connect: `any`, `none` (refuse everyone) or comma-separated IPs/CIDR prefixes, IPv4 or IPv6 — see [Access control](#access-control) |
| `--write-acl` | `none` | clients allowed to write — still requires `--allow-write`; `none` = no client writes (the default) — see [Access control](#access-control) |
| `--control-token` | none | require a token on **control** connections: the client authenticates with `{"cmd": "auth", "token": "..."}` before anything else; over the unix socket a trusted peer (root, the daemon's own user or `--control-trust-uids` — `SO_PEERCRED`) skips the handshake; a **TCP** control port refuses to start without a token — see [Runtime control](#runtime-control---control-port) (ini `control_token`, env `MODBUS_CACHE_CONTROL_TOKEN`) |
| `--control-token-file` | none | the token from a file (the first line; a systemd `LoadCredential` or a key file, **owner-only `0600`** — a group/world-accessible token file refuses to start, F12) — instead of `--control-token`, giving both is an error (ini `control_token_file`, env `MODBUS_CACHE_CONTROL_TOKEN_FILE`) |
| `--control-socket-group` | off | leave the unix control socket group-accessible (`chmod 0660` instead of the default `0600`): a local group may speak to the control without being the service user (ini `control_socket_group`, env `MODBUS_CACHE_CONTROL_SOCKET_GROUP`) |
| `--control-trust-uids` | none | extra peer uids the unix control socket trusts without the token (`SO_PEERCRED`): a comma-separated uid list — a local systemd unit speaks without the secret; root and the daemon's own user are always trusted (ini `control_trust_uids`, env `MODBUS_CACHE_CONTROL_TRUST_UIDS`) |
| **Persistence** | | |
| `--dump-path` | off | the state dump (write-behind): the cached words + their stamps and the live setting overrides as one JSON — written on shutdown, by the `request dump` command and every `--dump-interval` seconds; loaded on start only with `--restore-on-start`, on demand with the `request restore` command (ini `dump_path`, env `MODBUS_CACHE_DUMP_PATH`) |
| `--dump-interval` | `0` | seconds between the automatic state dumps, `0` = on request (the `request dump` command and the shutdown); needs `--dump-path`; live-settable (`set dump-interval`, ini `dump_interval`, env `MODBUS_CACHE_DUMP_INTERVAL`) |
| **Audit trail** | | |
| `--audit-log` | XDG state | the CACHE audit trail: a file path or `-` for stdout (docker logs / journald); default `~/.local/state/modbus-cache/audit.log` — see [Audit logging](#audit-logging) |
| `--audit-max-mb` | `10` | rotate the audit log at this size, keeping `--audit-files` backups; `0` = off |
| `--audit-daily` | off | also rotate the audit log at UTC midnight |
| `--audit-files` | `3` | rotated audit backups to keep |
| `--no-audit-log` | off | disable the audit trail |
| `--requests-audit` | `300` | audit one `REQUESTS` tally per client per this many seconds (who is hammering the cache), `0` = off (ini `requests_audit_s`, env `MODBUS_CACHE_REQUESTS_AUDIT`) |
| **Metrics** | | |
| `--metrics-port` | off | serve the cache's own Prometheus `/metrics` on `127.0.0.1:PORT` (the hit/miss counters, the poll health and age, the poll-cycle durations, the client count — no dependency on the scraper's `huawei_cache_*` path); **refuses to start without `--metrics-token`/`--metrics-token-file`** |
| `--metrics-token` | off | require `Authorization: Bearer <token>` on the metrics endpoint (the same scheme as the scraper's `--auth-token`); mandatory when `--metrics-port` is set |
| `--metrics-token-file` | off | the metrics bearer token from a file (the first line; owner-only `0600`, F12) — instead of `--metrics-token`, giving both is an error |
| **Limits** | | |
| `--max-clients` | `64` | refuse further connections past this many simultaneous clients (`0` = no limit) |
| `--client-timeout` | `300` | disconnect clients silent for this many seconds — sheds connections from clients that died without closing (`0` = never) |
| `--max-conn-per-ip` | `0` | refuse further connections from one peer IP past this many simultaneous connections (`0` = no per-IP limit) |
| **Logging** | | |
| `--log-level` | `INFO` | `DEBUG` adds per-client traffic and per-poll detail |
| `--log-access` | `DEBUG` | log client connects/disconnects at `INFO` instead of `DEBUG` |
| `--local-time` | UTC | log timestamps in the system time zone instead of UTC |

`cache/modbus_cache.ini` is a sample with the defaults. Boolean ini/env
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
| `SIGHUP` | **Reload the configuration and the register map** without dropping client connections: the map is swapped atomically (added ranges are polled, removed ones pruned), poll interval, read delay, merge gap, cache TTL, ACLs, client limits and the upstream address/unit/timeout take effect immediately (the upstream socket reconnects on the next read). A broken file or an invalid value keeps the previous settings — the error is logged and the next `SIGHUP` retries. The listen address and log level need a restart. |
| `SIGUSR1` | **Clean the cache**: all cached values, on-demand entries and poll-status errors are dropped atomically (client connections stay up), the next reads go to the inverter live and the poller repopulates immediately. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown**: the listener is closed and the shutdown is logged. |

```bash
kill -HUP  $(pgrep -f modbus_cache.py)   # reload config + register map
kill -USR1 $(pgrep -f modbus_cache.py)   # clean the cache
```

## Runtime control (`--control-port`)

A JSON-lines control server runs **by default on the unix socket
`/tmp/modbus-cache-<listen-port>.socket`** — short, determinable, stale
files replaced, nothing ever lands in the working directory. Pass a TCP port
number to bind `127.0.0.1:PORT` instead, or `0` to switch the control server
off. Both the proxy and the CLI tool resolve the target the same way: flag >
**`MODBUS_CACHE_CTL`** (or the short **`CACHE_CTL`**, like the fake
inverter's `FAKE_CTL`) environment variable > default socket.

One command per line, one reply per line. Every request and reply is one
JSON object: the request = `{"cmd": "<command>"}`, the reply =
`{"status": "ok|err|bye", "text": "…"}`. **With `--control-token` set,
connections must authenticate first** — `{"cmd": "auth", "token": "..."}` —
on both transports. Over the unix socket the kernel vouches for the peer
(`SO_PEERCRED`): root, the daemon's own user and the extra
`--control-trust-uids` uids skip the handshake, so a local systemd unit
speaks without sharing the secret; TCP peers always need the token. Without
a token the unix socket relies on filesystem permissions.

> **A token flag lands in `ps`.** Tokens passed as `--control-token` /
> `--metrics-token <secret>` are visible on the process command line — every
> local user can read them in `ps` output or `/proc/*/cmdline` (the audit's
> F9; the same applies to the ctl/cli clients). Prefer the **`-file`**
> variants — the file must be **owner-only (`0600`)**: group/world-accessible
> token files refuse to start (F12) — or the `MODBUS_CACHE_CONTROL_TOKEN` /
> `MODBUS_CACHE_METRICS_TOKEN` env vars. The flag form is for quick tests.

| Command | Effect |
|---|---|
| `set <setting> <value>` | configure a setting **live**: `interval`, `ttl`, `read-delay`, `merge-gap` (the poll plan rebuilds), `allow-write`, `write-registers`, `max-clients`, `client-timeout`, `max-conn-per-ip`, `requests-audit`, `dump-interval`, `log-level`, `profile`/`selection` (the register map swaps atomically), `connect-acl`, `write-acl`, `timeout` — the reply carries the compact state summary |
| `unset <setting>` | restore a setting to its **configured** startup value (what the flag/env/ini said at start) |
| `show <setting>` | the bare live value of one tunable |
| `show settings` | every tunable with its live value — one stable `key=value` line per setting (scriptable); a value set live carries a `*`, and a SIGHUP re-applies the config (the file always wins) and clears the markers — see [Live settings](#live-settings) |
| `help <setting>` | the registry description of one setting |
| `inspect` | one pretty multi-line dump of everything — version, upstream, listen/control, profile, cache state, poll plan, counters, the write gate, the audit sink: the baton for a bug report |
| `show status` | the **effective state report**: one stable `key=value` line per field (`upstream`, `unit`, `listen`, `control`, `uptime`, `poll`, `last_poll`, `interval`, `ttl`, `merge_gap`, `ranges`, `fc4_ranges`, `map_version`, `hits`, `misses`, `clients`, `writes`, `write_allow_list`, `requests_audit`, `dump`, `profile`, `selection`) — scriptable |
| `show connections` | connected clients: peer, connection age, requests served |
| `show cache` | cache contents: ranges, cached words, oldest entry, TTL, map version, failed ranges, hit/miss counters |
| `show cache all` | every cached entry, one row per profile range: name, words cached, their values (`-` = not cached), age of the oldest, when it expires, poll status (`ok`/`partial`/`empty`/`failed (ex N)`) |
| `show uplink` | the inverter link: session counters (state, connects, exchanges, bytes in/out, errors, last error) plus one row per poll block — status (`ok`/`ex N`/`error`/`pending`), latency (last/mean/max), failure count, last error |
| `request dump` | write the cached words (+ their stamps) and the live setting overrides to the `--dump-path` file — the write-behind state, see [Persistence](#persistence); the dump commands (and the `dump-interval` setting) show up in the listings only when a dump path is configured |
| `request restore` | load the dump back: the words return with their original stamps (their TTL bounds any staleness) and the overrides re-apply — what the startup restore does automatically |
| `show version` | the modbus-cache version |
| `clear cache` | drop all cached values (like SIGUSR1), repoll immediately |
| `restart` | drop the upstream connection **and** the cache, repoll now — for recovering from a wedged inverter session |
| `shutdown` | gracefully stop the proxy (same as SIGTERM: listener closed, control socket unlinked) |
| `help` / `?` | one-line command reference |
| `quit` | close the connection |

### Live settings

Every `set` applies immediately and keeps working until the daemon stops —
**or** the next `SIGHUP`, which re-resolves the config (flags, env, ini) and
re-applies it wholesale: the file always wins on reload. A setting changed
live is marked with a `*` in `show settings` (`interval=5s*`) and listed in
`show status`'s `overridden=` row; `unset <setting>` restores the configured
value and clears the mark. This makes the policy explicit: live settings are
runtime nudges, the config files stay the source of truth.

### `cache_ctl` — one-shot commands

A small client for scripts and quick pokes: one command as arguments (or a
batch piped on stdin), the replies on stdout, done.

```bash
python3 cache/bin/cache_ctl.py --control-port 15509 show status
python3 cache/bin/cache_ctl.py --control-port 15509 clear cache
printf 'show cache\nclear cache\n' | python3 cache/bin/cache_ctl.py --control-port 15509
```

Same `--control-port` flag / `MODBUS_CACHE_CTL` env as the proxy itself; the
TCP token comes from `--control-token` or `MODBUS_CACHE_CONTROL_TOKEN`.
Exit codes: `0` = ok, `1` = connection/control error, `2` = CLI misuse.
Every invocation lands in the audit log (below, prefix `CTL`).

### `cache_cli` — console-style session

An interactive front-end on the same socket (same flag/env resolution): on
the first connect (a TTY) it probes the status and greets you —

```
$ python3 cache/bin/cache_cli.py

% Welcome to the modbus-cache console
%   192.168.1.100:5502 upstream | poll ok, last poll 2.00s | running for 1.00h | 1 client(s)
%   TAB completes, ? lists the commands, quit leaves

cache:15502 > show status
ok status
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
ok

cache:15502 > shutdown
Proceed with shutdown? [confirm] y
bye shutdown
```

The prompt shows the connected port, TAB completes commands with their
descriptions (`show <TAB>` lists the tunables plus status/connections/cache/
settings/version, `?` does the same in any position), `clear cache` and
`restart` confirm with a plain
`ok`, and `shutdown` asks `Proceed with shutdown? [confirm]` first — RETURN
or `y` proceeds, anything else aborts with `% Aborted.`. While it idles the
CLI sends wire pings (every 55 s, `CACHE_CLI_KEEPALIVE` to tune, `0` = off)
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
with `--control-token` or the `MODBUS_CACHE_CONTROL_TOKEN` env — the same
token the proxy was started with.

## Access control

**`connect-acl` defaults to `any`** (who may connect is the listen bind's
job — the default bind is loopback); **`write-acl` and `write-registers`
default to `none`** — the write path is closed even before `--allow-write`
enters the picture. Both ACLs take a comma-separated list of IPs and CIDR
prefixes (IPv4 or IPv6, e.g. `--connect-acl 127.0.0.1,10.48.3.0/24`), or
the two words `any` (no restriction) and `none` (refuse every peer —
restrict all); the config-file/env/NixOS forms are
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
  client, `any` lifts the register check entirely.

Writing is therefore gated four times: `--allow-write` **and** the client
on the write ACL **and** every touched register inside the allow-list
(and the frame parse gate first) — with `write-acl` and `write-registers`
defaulting to `none`, enabling `--allow-write` alone still refuses every
write until the operator opens those two deliberately (in the config or
live with `set`).

ACLs re-resolve on `SIGHUP` like every other setting; a malformed list keeps
the previous one.

## Write-through invalidation

A forwarded write lands on the device, and the cache immediately drops the
cached words it touched (per-register — the rest of the cache stays warm)
and wakes the poller. The next read of the written range goes to the device
instead of serving the pre-write value until the TTL expires. Coils (FC05/15)
are not cached and need no invalidation.

## Persistence

`--dump-path` turns on the **write-behind state dump**: the cached words
(+ their original stamps, so freshness carries over — the poll ranges, the
bridged gaps and the on-demand entries alike) and the live setting
overrides, as one human-readable JSON — written atomically (tmp + rename).
The dumps land in three ways: every `--dump-interval` seconds (live-settable
`set dump-interval`, `0` = off — the default: on request), on the
**`request dump`** command, and on every
graceful shutdown. Loading is gated: **`--restore-on-start`** opts in to
loading the dump when the daemon starts (a restart serves last-known
values instead of cold misses); the default is starting cold — the
**`request restore`** command loads it on demand. Either way the words
return as they were —
their TTL bounds any staleness, and the next map swap prunes what the
profile no longer names — and the setting overrides re-apply through the
same gate a `set` speaks (`interval=2.00s` survives the restart, a moved
profile file is skipped with a note). With `selection none` the word-restore
is a no-op (the cache stays empty by design). The dump commands (and the
`dump-interval` setting) show up in the listings — the completions, `?`,
`help`, `show settings` — only when a dump path is configured.

## Metrics

`--metrics-port` (off by default) serves the cache's own Prometheus
`/metrics` on `127.0.0.1:PORT` — the self-observability without the
scraper's `huawei_cache_*` export path: `modbus_cache_hits_total` /
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
`--metrics-token` / `--metrics-token-file` set, requests need
`Authorization: Bearer <token>` — the same scheme the scraper's exporter
speaks; anything but `/metrics` answers 404, an unauthenticated read 401.
The endpoint is **loopback-only** and capped: `--metrics-max-clients`
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
| Device rejects a forwarded non-FC3 request | `forwarded FC22 rejected by the device (modbus exception N)` |
| Uncached read forwarded + cached | `read: registers … not cached, polling the device` / `… ok, cached …` |
| Device rejects a forwarded read | `read: registers … rejected by the device (modbus exception N)` |
| Connection rejected (ACL) | `connection rejected: 10.0.0.5:51234 not on the connect ACL` |
| Connection refused (limit) | `connection refused: client limit of N reached (…)` |
| Config/register-map reload (`SIGHUP`) | `SIGHUP: reload requested` / `SIGHUP: reloaded 13 range(s) …` / `SIGHUP: reload failed …` |
| Cache clean (`SIGUSR1`) | `SIGUSR1: cache cleared (N register(s) dropped), repolling now` |
| Cache poll failed/recovered | `poll of … failed (modbus exception, code 2), serving cached values` / `poll of … recovered` |
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

The prefix names the writer — `CACHE` (the proxy), `CLI` (cache_cli) and
`CTL` (cache_ctl):

```
2026-11-04T07:16:40Z AUDIT CACHE START 4e1b92f0c7a3 version=0.3.0 upstream=192.168.1.100:5502 unit=1 listen=127.0.0.1:15502 control=unix:/tmp/modbus-cache-15502.socket profile=/nix/store/…-sun2000.json
2026-11-04T07:16:43Z AUDIT CACHE WRITE b2c4e17f90d8 register 47415 = 5 (single register, unit 1)
2026-11-04T07:17:02Z AUDIT CACHE AUTH-FAIL 6f3d84a1e2c9 peer=127.0.0.1:54425
2026-11-04T07:17:12Z AUDIT CACHE COMMAND 09ab57d3f4e1 peer=127.0.0.1:54426 'clear cache' -> ok
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
server** (`AUDIT CACHE COMMAND`, with the client peer — it knows the who);
the CLI audits its session (CONNECT/DISCONNECT, the local-only events like
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
                                  #   phase, JSON control + token auth/token-file +
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
nix run .#modbus-cache -- --host 192.168.1.100
```

The package ships three binaries: `modbus-cache` (the proxy),
`modbus-cache-ctl` (one-shot control commands) and `modbus-cache-cli` (the
console-style control session), plus the man pages
(`man/modbus-cache.1`, `-ctl.1`, `-cli.1`) under `share/man/man1/`.

```nix
imports = [ inputs.pv-dash.nixosModules.modbus-cache ];

services.modbus-cache = {
  enable = true;
  inverterHost = "192.168.1.100";   # the inverter's LAN IP
  listenHost = "0.0.0.0";           # only when Modbus clients live on other hosts
  openFirewall = true;              # together with a non-loopback listenHost
};
services.modbus-scraper = {
  enable = true;
  inverterHost = "127.0.0.1";       # the proxy
  inverterPort = 15502;
};
```

Options: `inverterHost`, `inverterPort`, `unitId`, `timeout`, `interval`,
`readDelay`, `mergeGap`, `profile` (device-profile JSON path; null = the
bundled `sun2000` profile), `cacheTtl` (unset = 3× `interval`),
`listenHost`, `listenPort`, `allowWrite`, `writeRegisters` (the
START:COUNT allow-list, `any` or `none`; null = the proxy default
`none`), `connectAcl` (`any`/`none`/prefixes; null = `any`),
`writeAcl` (`any`/`none`/prefixes; null = the proxy default `none`),
`maxClients`, `clientTimeout`, `logLevel`, `localTime`,
`logAccess`, `openFirewall`, `auditLog` (null = the trail goes to
**stdout**, which journald captures — the hardened service cannot write
the XDG state home), `auditMaxMb`, `auditDaily`, `auditFiles`, `requestsAudit`
(null = 300 s), `controlPort` (a TCP port on 127.0.0.1 or a unix socket
path — use one under `/run/modbus-cache/`, `/tmp` is private to the
service), `controlToken` (**world-readable in the store ini** — prefer the
file), `controlTokenFile` (mounted via systemd `LoadCredential`). Unset
options keep the proxy defaults. The service runs with a dynamic user and
systemd hardening.

The module renders the **config INI and the register map into the store**
and runs the service with `--config`. A `nixos-rebuild switch` applies
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
│   ├── modbus_cache.py  # CLI, logging setup, signal handling
│   ├── cache_ctl.py     # one-shot control client (args / piped commands)
│   └── cache_cli.py     # console-style interactive control session
├── modbus_cache.ini     # sample config (the default --config target)
├── selection.json       # example selection: the essential monitoring set
└── lib/
    ├── static.json      # the static constants: protocol limits, diagnostics block, defaults
    ├── statics.py       # its loader (the STATIC dict + the named aliases)
    ├── protocol.py      # wire format, errors, frame helpers
    ├── config.py        # settings resolution + device-profile loading
    ├── upstream.py      # the shared inverter connection
    ├── cache.py         # register cache + block planner
    ├── proxy.py         # poller + client handling
    ├── control.py       # JSON-lines control server (inspect/show/clear/restart/shutdown, token auth)
    ├── audit.py         # the append-only audit trail (AUDIT CACHE/CLI/CTL lines)
    └── version.py       # the suite version
```

## License

The proxy (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the repo-root `LICENSE` file.
