# modbus-cache

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time. So far verified only against simulated data (fake inverter,
> fuzzing and regression/stress suites), not against real hardware.

A dependency-free (Python stdlib only) **Modbus TCP caching proxy** for
devices that accept only a single client — e.g. a Huawei SUN2000 inverter
and its SDongle/EMMA radio allow one Modbus TCP connection, so the
[modbus-scraper](../scraper/README.md) cannot share them with anything
else. Point the scraper (or any other Modbus client) at the proxy instead
of the inverter:

```bash
python3 cache/bin/modbus-cache.py --upstream 192.168.1.100:5502
python3 scraper/bin/modbus-scraper.py --upstream :15502
```

## How it works

The proxy owns the one upstream connection the device allows and multiplexes
it:

- a background loop **polls the configured register ranges** at a fixed
  interval into an in-memory cache;
- any number of clients are **served from the cache** (FC3/FC4 words, FC1/FC2
  bits); reads **outside the cached ranges are polled live**, answered and
  cached for `--cache-ttl` like everything else — any other function code is
  forwarded untouched;
- **writes** (FC05/06/15/16/22/23) are forwarded when enabled (see
  [Access control](#access-control)) and always logged with register,
  value(s) and outcome; a forwarded write drops the cached words it touched
  (per-register) and wakes the poller — the next read goes to the device,
  not the pre-write value. Register writes invalidate both word spaces
  (holding + input), coil writes the coil space;
- a synthesized **diagnostics block** (registers 65000–65003: device-up
  flag, cache age, uptime) lets clients tell live data from cache-served
  values — the scraper auto-detects it and exports it as `scraper_cache_*`
  gauges.

Resilience:

- **Inverter unreachable** — cached reads keep serving the last known
  values while forwarded reads get Modbus exception `0x0B`. Entries older
  than `--cache-ttl` are refetched on the next read.
- **Device rejects a range** — the cache remembers that poll status and
  answers client reads in the range with the same exception until a poll
  succeeds again: no repeated hammering, and clients see the failure the
  device actually reports.
- **Garbage from the device or from clients** — malformed frames, lying
  lengths, wrong ids, stalls, pipelined bursts: logged one-line and
  survived; a client cannot crash the proxy, only burn its own connection
  (fuzz- and soak-tested).

## Diagnostics registers

The cache synthesizes a 4-register block at **65000** from live poller
state — answered instantly, never forwarded, never cached, never part of a
profile (FC3 only):

| Register | Meaning |
|---|---|
| 65000 | magic `0xCAFE` (validity check for clients) |
| 65001 | `1` if the last completed poll cycle had at least one successful read |
| 65002 | seconds since the last successful device read (`65535` = none yet) |
| 65003 | cache process uptime in seconds |

Reads that straddle the block are rejected with exception `02`. Reply unit
ids are validated on every forwarded request before anything is cached.

## Register map (device profile)

The proxy caches the registers listed in the **device profile** — the same
shared schema the [fake inverter](../inverter/README.md) serves and the
[scraper](../scraper/README.md) scrapes; the shipped profiles live in the
suite's [`profiles/`](../profiles/) subproject (`sun2000.json` by default).
The format is documented in [profiles/README.md](../profiles/README.md).
Resolution: `--profile` flag, env `PROFILE`, config `set modbus profile`,
then the bundled copy; the file is re-read on `SIGHUP`.

- Entry `type` gives the width and the space: `i16`/`u16` (one word),
  `i32`/`u32` and the lo-word-first `i32swap`/`u32swap`, the IEEE 754
  `f32`/`f32swap` (two words each), `bit` (one address = one binary value).
- The optional **`fc`** field picks the address space: `3` (holding
  registers) or `4` (input registers) for the word types (`3` the default),
  `1` (coils, the bit default) or `2` (discrete inputs) for `bit` — the
  four spaces are cached and polled independently.
- The optional **`ttl`** field overrides the cache TTL per entry (seconds;
  `0` = never expire): a fast power word at 5s next to a nameplate word at
  1h, one poll cadence for both (`show cache all` marks the entries carrying
  one). The entry TTL **replaces** the global one in both directions — the
  global TTL is only the fallback, never a floor.

Which registers are actually **fetched** comes from a selection file —
`{"registers": ["pv-power", ...]}`, profile names only — resolved as
`--selection` flag, env `SELECTION`, config `set modbus selection`; the
default fetches **every** profile entry (`all`), and **`none`** empties the
map: every read forwards and nothing is stored. The shipped
`examples/selection.json` is the essential SUN2000 monitoring set. The
65000-65003 diagnostics block is never fetched — the cache synthesizes it.

For slow dongles the poller reads the map in as **few transactions as
possible**: ranges closer together than `--merge-gap` registers are merged
into one block read (never across a function-code boundary); a block that
fails is split in halves and the pieces are retried — the plan converges to
the largest blocks the device actually answers.

## Usage

By default the proxy **binds to 127.0.0.1:15502** (loopback only) — pass
`--listen 0.0.0.0:15502` when Modbus clients live on other hosts.

Add **`--dry-run`** to validate the configuration and the register map and
print the effective settings without binding the listen port or contacting
the inverter — handy for checking NixOS-rendered config files
(`--config /nix/store/…-modbus_cache.conf --dry-run`). Exit codes: `0` =
valid; `1` = invalid (reason on stderr, stdout stays clean); `2` =
command-line misuse.

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`modbus-scraper`:

1. CLI flags (`--upstream`, `--listen`, …)
2. Environment variables — the same names, bare (no tool prefix):
   `UPSTREAM`, `UNIT`, `TIMEOUT`, `LISTEN`, `INTERVAL`, `READ_DELAY`,
   `MERGE_GAP`, `PROFILE`, `SELECTION`, `TTL`, `ALLOW_WRITE`, … —
   `show knobs` prints every knob with its env twin
3. Config file (the set grammar: every line a `set <name> <value>` in the
   CLI spelling) — `--config` picks the file (default:
   `modbus_cache.conf` next to `modbus-cache.py`, then the subproject
   root's sample; a missing file is fine)

Every setting is validated before use — nonsense values abort with a clean
one-line error instead of failing later at runtime. Boolean config/env
values accept `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`.

| Flag | Default | Meaning |
|---|---|---|
| **Upstream** | | |
| `--upstream` | `127.0.0.1:5502` | the inverter's Modbus TCP endpoint `HOST:PORT` (`:5502` = `127.0.0.1:5502`) |
| `--unit` | `1` | Modbus unit id (1–247) |
| `--timeout` | `3` | Modbus connect/read timeout, seconds |
| `--profile` | the bundled `sun2000` profile | device profile JSON to cache (see above) |
| `--interval` | `10` | seconds between cache polls |
| `--cache-ttl` | 3× `--interval` | per-register cache TTL in seconds (`0` = never expire) |
| `--read-delay` | `0.05` | seconds between consecutive inverter reads within a poll cycle |
| `--merge-gap` | `8` | max register gap when merging ranges into block reads (`0` = read separately) |
| **Auth** | | |
| `--auth` / `--auth-key` | `none` | the auth scheme the cache's **own Modbus clients** must speak + the shared key (**min 16 characters**) — see [Modbus auth](#modbus-auth); the value may be `file:<path>` |
| `--auth-upstream` / `--auth-upstream-key` | `none` | the auth scheme **toward the upstream inverter** (`suite` or `waveshare`) + the key — see [Modbus auth](#modbus-auth) |
| **Write path** | | |
| `--allow-write` | disabled | forward write requests (FC05/06/15/16/22/23) to the inverter |
| `--write-registers` | `none` | register ranges a forwarded write may touch: comma-separated `START:COUNT`, `any`, `none`, `profile` (the device profile's acl gate), `file:<path>` (the standalone acl file) |
| `--connect-acl` | `any` | clients allowed to connect: `any`, `none`, comma-separated IPs/CIDR prefixes, `file:<path>` — see [Access control](#access-control) |
| `--write-acl` | `none` | clients allowed to write — still requires `--allow-write`; the same grammar as `--connect-acl` |
| **Control plane** | | |
| `--control-port` | unix socket | control server target: a TCP port on 127.0.0.1, a unix socket path, `0` = off |
| `--control-token` | none | require a token on control connections; a **TCP** control port refuses to start without one (F5); the value may be `file:<path>` |
| `--control-ops-token` | none | a **second, read-only control token**: its sessions run the `show`/`clear` verbs only; needs `--control-token`, must differ from it |
| `--control-ops-verbs` | `show,clear` | the read-only ops role's RBAC policy |
| `--control-trust-uids` | none | extra peer uids the unix control socket trusts without the token (`SO_PEERCRED`) |
| `--control-socket-group` | off | leave the unix control socket group-accessible (`0660` instead of `0600`) |
| **Persistence** | | |
| `--dump-path` | off | the state dump (write-behind) — see [Persistence](#persistence) |
| `--dump-key` | off | the key that **seals** the state dumps and the reload state file; startup-only; `file:<path>` welcome |
| `--dump-with-cache` | off | dump the cached words too (the default dump = settings only) |
| `--dump-interval` | `0` | seconds between the automatic state dumps, `0` = on request; live-settable |
| `--restore-on-start` | off | load the state dump when the daemon starts |
| **Metrics** | | |
| `--metrics-server` | off | serve the cache's own Prometheus `/metrics` endpoint — live-settable (`set metrics enable on/off`); **refuses to start beyond loopback without `--metrics-token`** (F13) |
| `--metrics-listen` | `127.0.0.1:9351` | the metrics bind address (`0.0.0.0:PORT` = every interface, token mandatory) |
| `--metrics-token` | off | `Authorization: Bearer <token>` on `/metrics`; mandatory beyond loopback (F13); `file:<path>` welcome |
| `--metrics-acl` | `any` | clients allowed to connect to `/metrics` (the connect-acl grammar); checked at accept |
| `--metrics-max-clients` / `--metrics-client-timeout` / `--metrics-max-conn-per-ip` | `64` / `5` / `0` | the metrics caps (extras get `503 # rate limited`) |
| **Limits** | | |
| `--max-clients` | `64` | refuse further connections past this many simultaneous clients (`0` = no limit) |
| `--client-timeout` | `300` | disconnect clients silent for this many seconds (`0` = never) |
| `--max-conn-per-ip` | `0` | per-peer-IP connection cap (`0` = no limit) |
| **Audit trail** | | |
| `--audit-log` | XDG state | the CACHE audit trail: a file path or `-` for stdout (docker logs / journald) — see [Audit logging](#audit-logging) |
| `--audit-max-mb` / `--audit-daily` / `--audit-files` / `--no-audit-log` | `10` / off / `3` / off | rotation at size / at UTC midnight / backups kept / the off switch |
| `--requests-audit` | `300` | audit one `REQUESTS` tally per client per this many seconds, `0` = off |
| **Logging** | | |
| `--log-level` | `INFO` | `DEBUG` adds per-client traffic and per-poll detail |
| `--log-access` | `DEBUG` | log client connects/disconnects at `INFO` |
| `--local-time` | UTC | log timestamps in the system time zone |
| `--man` | off | print the generated man page (roff) to stdout and exit |

The six **secret knobs** (`--auth-key`, `--auth-upstream-key`,
`--control-token`, `--control-ops-token`, `--metrics-token`, `--dump-key`)
never render back: the config file, the state dumps and the reload state
file carry the `*** SECRET REMOVED ***` placeholder where a value would
sit. Pass each one on every start — by flag, by env, or as `file:<path>`
(the first line of an owner-only `0600` file). A token passed as a flag
lands in `ps` — the file form is the shipped way (the audit's F9/F12).

`examples/modbus_cache.conf` is a sample in the set grammar; `show config`
regenerates the script from the running daemon (secrets hidden) and `help
config` maps every knob to its control command.

## Runtime control (signals)

| Signal | Effect |
|---|---|
| `SIGHUP` | **Reload the configuration and the register map** without dropping client connections: the map is swapped atomically, poll interval, read delay, merge gap, cache TTL, the ACLs (the `file:` gates re-read), limits and the upstream address/unit/timeout take effect immediately. A broken file keeps the previous settings. The listen address needs a restart (the registry's `restart: true` knobs record a live `set` and fold into the restarted process). |
| `SIGUSR1` | **Clean the cache**: all cached values, on-demand entries and poll-status errors are dropped atomically, the poller repopulates immediately. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown.** |

## Runtime control (`--control-port`)

A JSON-lines control server runs **by default on the unix socket
`/tmp/modbus-cache-<listen-port>.socket`** — pass a TCP port number to bind
`127.0.0.1:PORT` instead, or `0` to switch it off. Both the proxy and the
CLI tool resolve the target the same way: flag > the **`CTL`** environment
variable > the default socket.

One command per line, one reply per line: `{"cmd": …}` →
`{"status": "ok|fail|bye", "text": …}`. With `--control-token` set,
connections authenticate first (`{"cmd": "auth", "token": …}`) and the wire
is **signed**: every frame carries the full sha256 HMAC of its payload
keyed by the token — mandatory over TCP, verify-if-present over the unix
socket, where root, the daemon's own user and the `--control-trust-uids`
peers skip the handshake (`SO_PEERCRED`). The wire, the roles and the
secrets discipline are the family's — see
[docs/ACL.md](../docs/ACL.md) (the control-plane row) and the audit's F5/F9/F12
in [docs/AUDIT.md](../docs/AUDIT.md).

The **read-only ops role**: a daemon may carry a second token
(`--control-ops-token`) beside the admin one; its sessions may run the
`show`/`clear` verbs only — the ops shift can look, flush the cache, and
leave; steering needs the admin key. Both tokens are audited
(`role=ops`/`role=admin`), each session's frames are mac'd with the key it
authenticated with.

| Command | Effect |
|---|---|
| `set <setting> <value>` | configure a setting **live** — the poll plan, the write gates, the ACLs, the limits, the auth schemes/keys, `control port` (rebinds the listener live), the tokens (rotate live; the value never renders back), `audit log-file`/`audit rotate …`, `dump path`/`dump with-cache`/`dump restore-on-start` |
| `unset <setting>` | restore a setting to its **configured** startup value |
| `show <setting>` | the bare live value of one tunable (a **secret knob refuses to show**) |
| `help <setting>` | the registry description of one setting |
| `inspect` | one pretty dump of everything — the baton for a bug report |
| `show connections` | connected clients: peer, connection age, requests served |
| `show cache` / `show cache all` | cache contents / one row per profile range with values, ages, poll status |
| `show uplink` | the inverter link: session counters plus one row per poll block — status, latency, failures |
| `show write registers profile` | the write gate as its acl chain (show-only) |
| `show acl connect table` / `show acl write table` / `show metrics acl table` | the ACLs as their rule chains (show-only) |
| `request dump` / `request restore` | write the write-behind state / load it back — see [Persistence](#persistence) |
| `request clear cache` | drop all cached values (like SIGUSR1), repoll immediately |
| `request restart` | drop the upstream connection **and** the cache, repoll now |
| `request reload` | **restart the whole daemon with the configuration kept**: the live overrides save to `<config>.reload`, the process re-execs, the fresh daemon re-applies them once (the `restart: true` knobs take their configured values); the cache starts empty |
| `show version` / `show knobs` | the version / the whole knob registry |
| `shutdown` | gracefully stop the proxy (same as SIGTERM) |
| `help` / `?` / `quit` | the command reference / close the connection |

Live settings are runtime nudges — the config files stay the source of
truth: the next `SIGHUP` re-resolves the config wholesale and the file
always wins.

### `modbus-cache-ctl` — one-shot commands

```bash
python3 cache/bin/modbus-cache-ctl.py --control-port 15509 show modbus upstream
python3 cache/bin/modbus-cache-ctl.py --control-port 15509 clear cache
printf 'show cache\nclear cache\n' | python3 cache/bin/modbus-cache-ctl.py --control-port 15509
```

Same `--control-port` flag / `CTL` env as the proxy; a TCP token comes from
`--control-token` or `CONTROL_TOKEN` (the ops staff pass the read-only ops
token the same way). Exit codes: `0` = ok, `1` = connection/control error,
`2` = CLI misuse. Every invocation lands in the audit log.

### `modbus-cache-cli` — console-style session

An interactive front-end on the same socket (same flag/env resolution):

```
$ python3 cache/bin/modbus-cache-cli.py

%   Welcome to the modbus-cache console
%   TAB completes, ? lists the commands, quit leaves

cache:15502 > show cache
13 range(s), 88 word(s) cached, oldest 2.00s, ttl 30.00s, map v3, failed range(s) 0, hits 412, misses 9

cache:15502 > shutdown
Proceed with shutdown? [confirm] y
% bye shutdown
```

TAB completes commands, settings and their values; `set`/`unset` confirm
`% changed`, errors print `% error: <message>`, the ok replies print bare.
While idle the CLI sends wire pings (every 55 s, `CLI_KEEPALIVE` to tune);
when the connection dies it retries `--reconnect` times (default 3) with
`--reconnect-wait` seconds (default 10) and resumes on the first success.
The session is audited (prefix `CLI`), the commands are audited by the
server (prefix `CACHE`).

## Access control

The family-wide ACL map — the rule-chain semantics, the standalone acl
file, the tools and where every tool's support stops — lives in
[docs/ACL.md](../docs/ACL.md). The short form:

- **`--connect-acl`** defaults to `any` (who may connect is the listen
  bind's job — the default bind is loopback): `any` / `none` / a
  comma-separated list of IPs and CIDR prefixes / `file:<path>` (the
  standalone ip-prefix acl file).
- **`--write-acl`** defaults to `none` — clients allowed to write, still
  requires `--allow-write`; refused writes get a Modbus illegal-function
  exception, logged with the client IP, the connection stays up.
- **`--write-registers`** defaults to `none` — the ranges a forwarded write
  may touch; `profile` takes the gate from the device profile's `acl`/
  `write` chain, `file:<path>` from a standalone acl file. An example ships
  as `examples/acl-write-registers.json` (the deye policy, worked out).
- **`--metrics-acl`** defaults to `any` — who may connect to `/metrics`,
  the same grammar, checked at accept.
- Every acl file (the ip-prefix gate and the write gate) must be
  **owner-only `0600`**: a group/world-readable file warns in the log, the
  audit trail and the `set` reply suffix (the gate is config trust any
  local user could have loosened).
- The `show … table` reports render each gate as its chain, one
  `allow`/`deny` line per range, the descs included.
- ACLs re-resolve on `SIGHUP` like every other setting; a malformed list
  keeps the previous one.

Writing is therefore gated four times: the frame parse gate, `--allow-write`,
the client on the write ACL, every touched register inside the allow-list —
with `write-acl` and `write-registers` defaulting to `none`, enabling
`--allow-write` alone still refuses every write until the operator opens
those two deliberately.

## Modbus auth

Beyond the address-based ACLs the cache speaks the family's **`suite`**
Modbus auth — a proof-of-key handshake on the Modbus TCP wire itself (the
wire shape is specified in [docs/MODBUS.md](../docs/MODBUS.md)): the client
proves the shared key with one round trip after the TCP connect; the server
answers `OK` (plain Modbus follows) or `ERR` (the connection is dead — a
client that cannot prove the key never sees a frame).

The two legs are configured separately, with separate keys:

- **`--auth` / `--auth-key`** — the auth the cache's *own clients* must
  speak on the listen port. `none` (the default) = no auth at all.
- **`--auth-upstream` / `--auth-upstream-key`** — the auth the cache
  *presents* to the upstream inverter: `suite` handshakes after every
  (re)connect, `waveshare` presents the key as a **Waveshare RS485-to-TCP
  gateway's** connection password. The upstream-only scheme of the pair:
  the cache's own clients always speak `suite` or nothing.

Both keys are secrets (they never render back; `file:<path>` loads from an
owner-only `0600` file). The floor is the scheme's: the suite handshake
needs at least 16 characters, the Waveshare password non-empty ASCII — a
key set while no scheme is chosen is dormant material. Both knobs are
live-settable; the peer must speak the same scheme with the same key — the
fake inverter serves the server side, the scraper the client side, so a
chain scraper → cache → inverter can run suite auth on either hop
independently.

## Persistence

`--dump-path` turns on the **write-behind state dump**: the live setting
overrides and — when asked — the cached words (+ their original stamps), as
one JSON written atomically. **What lands in the file is split** (the
audit's F18): by default **settings only**; `request dump with-cache` or
`--dump-with-cache` includes the words; the restore takes either shape.
The dumps land every `--dump-interval` seconds (live-settable, `0` = off —
the default), on the **`request dump`** command, and on every graceful
shutdown. **`--restore-on-start`** opts in to loading the dump when the
daemon starts; the default is starting cold — **`request restore`** loads
it on demand.

**The dump is config-equivalent trust at rest** — and it is treated that
way:

- the file is created **`0600`** explicitly (never the umask);
- every dump carries a **sha256 integrity hash**; a restore **fails
  closed** on an edited/truncated/unsigned dump and refuses a
  group/world-writable file outright;
- with **`--dump-key`** the dump is **sealed**: the state rides encrypted
  under an HMAC-SHA256 counter-mode keystream, authenticated by an HMAC mac
  (stdlib only). The gate is symmetric — a restore without the key refuses
  a sealed dump, and a restore **with** a key refuses an unsealed one. The
  reload's state file seals under the same key — which is why the knob is
  startup-only;
- the key rides inline or as **`file:<path>`** (a systemd LoadCredential
  rides as `file:/run/credentials/...`); the same `file:` reference form
  works on every secret value. Without a key a dump path stays plaintext
  **by design** — and says so (a `WARNING` at start, a note on the
  `set dump path` reply).

## Metrics

`--metrics-server` (off by default, live-settable) serves the cache's own
Prometheus `/metrics` on `--metrics-listen` (default `127.0.0.1:9351`). The
bearer token is **mandatory beyond loopback** — a token-less non-loopback
bind refuses to start (the F13 posture); beside the token the endpoint
carries the **metrics ACL** (`--metrics-acl`, live `set metrics acl`),
checked at accept. The whole surface is live: `set metrics listen` rebinds
the endpoint, the `metrics limits` caps apply to the running gate, and
`set metrics token` rotates the credential without a restart (the value
never renders back; `set metrics token off` takes the endpoint tokenless on
the loopback listen). A scrape job reads it like any bearer endpoint —
`authorization: {type: Bearer, credentials_file: …}` in the job config (the
docker demo's `prometheus.yml` ships this wired).

The gauges: the hit/miss counters (`modbus_cache_hits_total` /
`modbus_cache_misses_total`), the poll health and age
(`modbus_cache_poll_up`, `modbus_cache_last_poll_age_seconds`,
`modbus_cache_age_seconds`), the map size (`modbus_cache_words` /
`modbus_cache_ranges`, the `fc` labels), `modbus_cache_clients`, the uptime
and the poll-cycle durations; the uplink exports the session state
(`modbus_cache_uplink_*` — up, connects/exchanges/errors, bytes, the last
error's age) and every poll block
(`modbus_cache_uplink_block_up{fc,start,count}`,
`…block_latency_seconds{,_mean,_max}`, `…block_fails_total`). Anything but
`/metrics` answers 404, an unauthenticated read 401.

## Audit logging

The proxy logs every audit-relevant event to stdout/stderr with UTC
timestamps by default (`--local-time` switches). Under systemd, journald
stores, seals and rotates these lines — point your NIS2/DORA documentation
at `journalctl -u modbus-cache`. Modbus has no authentication, so the
client's source IP is the only identity there is.

| Event | Log line |
|---|---|
| Forwarded write | `write: register 47415 = 99 (single register, unit 1)` |
| Write refused (disabled / ACL / device) | `write: refused register …` / `write rejected by the device: …` |
| Forwarded frame (no cache semantics) | `forwarded FC17 (report slave id), 0 byte(s) (unit 1)` |
| Uncached read forwarded + cached | `read: registers … not cached, polling the device` / `… ok, cached …` |
| Connection rejected (ACL / limit) | `connection rejected: 10.0.0.5:51234 not on the connect ACL` / `connection refused: client limit of N reached` |
| Reload / clean (`SIGHUP` / `SIGUSR1`) | `SIGHUP: reloaded 13 range(s) …` / `SIGUSR1: cache cleared (N register(s) dropped) …` |
| Poll failed/recovered | `poll of … failed (FC3 modbus exception, code 2), serving cached values` / `poll of … recovered` |
| Client connect/disconnect (`--log-access`) | `client connected: 10.0.0.5:51234` / `client … disconnected (…)` |
| Startup / shutdown | `caching 13 range(s) …` / `shutdown: SIGTERM received, closing the listener` |

On top of the operational log, the proxy and the CLI append to an
**append-only audit file** — one line per event, who/when/what/result, on
by default at the **XDG state home** (`~/.local/state/modbus-cache/audit.log`).
`--audit-log <file>` renames it, `--no-audit-log` turns it off,
`--audit-log -` sends it to stdout (the docker logs / journald way — the
NixOS module ships with it). Rotation: `--audit-max-mb 10` (the default),
`--audit-daily` (UTC midnight), `--audit-files 3`. The prefix names the
writer — `CACHE` (the proxy), `CLI` (modbus-cache-cli), `CTL`
(modbus-cache-ctl):

```
2026-11-04T07:16:40Z AUDIT CACHE START 4e1b92f0c7a3 version=0.4.2 upstream=192.168.1.100:5502 unit=1 listen=127.0.0.1:15502 control=unix:/tmp/modbus-cache-15502.socket profile=/nix/store/…-sun2000.json
2026-11-04T07:16:43Z AUDIT CACHE WRITE b2c4e17f90d8 register 47415 = 5 (single register, unit 1)
2026-11-04T07:17:12Z AUDIT CACHE COMMAND 09ab57d3f4e1 peer=127.0.0.1:54426 'clear cache' -> ok
2026-11-04T07:17:20Z AUDIT CACHE COMMAND 5c92f1b8d3a7 peer=127.0.0.1:54427 role=ops 'clear cache' wire=h1e6070592485 -> ok
2026-11-04T07:17:45Z AUDIT CACHE SHUTDOWN d94a1f07c3e2 SIGTERM received: uptime=65s clients=1 hits=412 misses=9
```

The 12-hex token after the event name is the entry's **chained hash** (the
audit's F10): any edit, deletion or reordering shows up as a chain break in
`scripts/audit_verify.py` (run it on this file, the family's XDG trails, or
a journald dump on stdin). **Every wire command is audited once, by the
server** (with the client peer, the role, and the frame's mac when the wire
is signed); the per-client **request accounting** rides the same trail (one
`REQUESTS` event per client per `--requests-audit` period, plus a final
tally on every disconnect). The trail is thread-safe and flushed per event.

Useful filters:

```bash
journalctl -u modbus-cache --since today | grep 'write:'      # all write attempts
journalctl -u modbus-cache | grep -E 'SIGHUP|shutdown'        # lifecycle
journalctl -u modbus-cache | grep -i 'not on'                 # ACL rejections
```

## Security

Modbus TCP (as spoken by the SUN2000 inverter and this proxy) has no auth,
no encryption and no access control — **anyone who can reach the listen
port can read** inverter registers. The proxy therefore **binds to
127.0.0.1 by default**; widen the bind deliberately, keep it on a trusted
LAN, and don't expose it to the internet. The ACLs add per-source control
within the LAN; for stricter isolation use the firewall. Writes are gated
four times and default closed (see [Access control](#access-control)).

`--max-clients` (default **64**) caps simultaneous clients (each is a
thread) and `--client-timeout` (default **300 s**) reaps clients that died
without closing. The control server binds loopback (TCP) or a `0600` unix
socket. Python is memory-safe, all request sizes bounds-checked and fuzzed.

## Testing

Four standalone suites live in the suite-root [`tests/`](../tests/) —
stdlib only, each starts its own fake inverter + proxy on scratch ports and
cleans up after itself:

```bash
python3 tests/cache-regtest.py        # the functional battery
python3 tests/cache-stress.py         # 100 clients / 15 s load + latency report
python3 tests/cache-fuzz.py [n]       # n client-garbage frames (default 3000)
python3 tests/cache-control-fuzz.py   # hostile JSON against the control server
```

Every scenario must end with the proxy alive and **zero tracebacks** in the
logs — the hostile-upstream phase proves that per mode, including recovery
when the device starts answering sanely again.

## Nix / NixOS

```bash
nix run .#modbus-cache -- --upstream 192.168.1.100:5502
```

The package ships three binaries (`modbus-cache`, `modbus-cache-ctl`,
`modbus-cache-cli`) plus the man pages under `share/man/man1/`. The
**`services.modbus-cache`** NixOS module — the option map, the secrets
discipline, the reload/restart story — is documented once in
[docs/NIXOS.md](../docs/NIXOS.md).

## Source layout

```
cache/
├── bin/
│   ├── modbus-cache.py  # CLI, logging setup, signal handling
│   ├── modbus-cache-ctl.py     # one-shot control client (args / piped commands)
│   └── modbus-cache-cli.py     # console-style interactive control session
├── examples/
│   ├── modbus_cache.conf    # sample config in the set grammar
│   ├── selection.json       # example selection: the essential monitoring set
│   └── acl-write-registers.json  # example acl file: the deye write policy
├── schema/                  # the JSON Schemas (draft 2020-12): the acl + selection files
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
    ├── control.py       # JSON-lines control server (token auth + the read-only ops role)
    └── man.py           # the man-page builder (the prose sections)
```

The shared pieces — the audit trail, the signed wire, the config/token
plumbing, the Modbus core, the version — live in the suite-root
[`common/`](../common/) package.

## License

The proxy (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the repo-root `LICENSE` file.
