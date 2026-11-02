# modbus-cache

A dependency-free (Python stdlib only) **Modbus TCP caching proxy** for devices
that accept only a single client — Huawei SUN2000 inverters and their
SDongle/EMMA radios are limited to one Modbus TCP connection, so the
[sun2000-scraper](../scrape/README.md) cannot share them with anything else.

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
- **writes** (FC06 single / FC16 multiple registers) are forwarded when
  enabled (see [Access control](#access-control)) and always logged with
  register, value(s) and outcome.

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
- **Garbage from the device** (malformed frames, short bodies, disconnects) —
  the poller logs it and retries; it cannot be killed by bad input, and a
  device that starts answering again is picked up on the next cycle.
- **Garbage from clients** (random PDUs, lying MBAP lengths, wrong
  protocol/unit ids, pipelined bursts, truncated frames) — every request is
  answered (or the connection is closed for lying headers); malformed
  frames, fuzzing and soak-tested: a client cannot crash the proxy, only
  burn its own connection.

## Register map

The proxy caches whatever the **register map** file lists — `registers.json`
next to the script by default (override with `--registers-file`, env
`MODBUS_CACHE_REGISTERS_FILE` or ini `registers_file`; re-read on `SIGHUP`).
The shipped **`cache/src/registers.json` is an example** with the standard
SUN2000 monitoring registers — the gains and sign conventions from Huawei's
*Modbus Interface Definitions* are noted in the entry names. Edit it or write
your own. The NixOS module does not use the example file: it renders its own
`registers.json` into the Nix store from the `registers` option and runs the
service with that file.

The format:

```json
{
  "registers": [
    { "name": "PV input power (int32, /1000 kW)", "start": 32064, "count": 2 },
    { "start": 37113, "count": 2 }
  ]
}
```

- `start` — first register of the range; `count` — number of registers
  (1–125, the Modbus read limit)
- `name` is optional and only decorates the logs
- entries may also be plain `"START:COUNT"` strings
- reads outside the cached ranges are forwarded to the inverter live — an
  empty list turns the proxy into a pure pass-through

For slow dongles the poller reads the map in as **few transactions as
possible**: ranges closer together than `--merge-gap` registers (default 8)
are merged into one block read, which may also cover registers between the
listed ones (those are cached too). A block that fails — e.g. because it
spans an unmapped register — is split in halves and the pieces are retried;
the plan converges to the largest blocks the device actually answers.

## Usage

```bash
python3 cache/src/modbus_cache.py --host 192.168.1.100 --listen 0.0.0.0:15502
```

Add **`--dry-run`** to validate the configuration and the register map and
print the effective settings (poll plan, ACLs, limits) without binding the
listen port or contacting the inverter — handy for checking NixOS-rendered
config files (`--config /nix/store/…-modbus_cache.ini --dry-run`).
Exit codes: `0` = valid; `1` = invalid (reason on stderr, stdout stays
clean); `2` = command-line misuse.

Point the scraper (or any other Modbus client) at the proxy instead of the
inverter:

```bash
python3 scrape/src/scraper.py --host 127.0.0.1 --modbus-port 15502 --listen 0.0.0.0:9350
```

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`sun2000-scraper`:

1. CLI flags (`--host`, `--listen`, …)
2. Environment variables — same names prefixed: `MODBUS_CACHE_HOST`,
   `MODBUS_CACHE_PORT`, `MODBUS_CACHE_UNIT`, `MODBUS_CACHE_TIMEOUT`,
   `MODBUS_CACHE_LISTEN`, `MODBUS_CACHE_INTERVAL`, `MODBUS_CACHE_READ_DELAY`,
   `MODBUS_CACHE_MERGE_GAP`, `MODBUS_CACHE_REGISTERS_FILE`,
   `MODBUS_CACHE_TTL`, `MODBUS_CACHE_ALLOW_WRITE`, `MODBUS_CACHE_LOCAL_TIME`,
   `MODBUS_CACHE_LOG_ACCESS`, `MODBUS_CACHE_MAX_CLIENTS`,
   `MODBUS_CACHE_CLIENT_TIMEOUT`, `MODBUS_CACHE_CONNECT_ACL`,
   `MODBUS_CACHE_WRITE_ACL`, `MODBUS_CACHE_LOG_LEVEL`
3. Config file (snake_case keys, `[cache]` section) — `--config` picks the
   file (default: `modbus_cache.ini` next to `modbus_cache.py`; missing file
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
| `--listen` | `0.0.0.0:15502` | proxy listen address |
| `--registers-file` | `registers.json` next to the script | JSON register map to cache (see above) |
| `--interval` | `10` | seconds between cache polls |
| `--cache-ttl` | 3× `--interval` | per-register cache TTL in seconds: older entries are refetched from the inverter (`0` = never expire) |
| `--read-delay` | `0.05` | seconds between consecutive inverter reads within a poll cycle (`0` = no wait) |
| `--merge-gap` | `8` | max register gap when merging ranges into block reads (`0` = read separately) |
| **Behaviour toggles** | | |
| `--allow-write` | disabled | forward write requests (FC05/06/15/16) to the inverter; disabled, they are refused with a Modbus illegal-function exception (ini `allow_write`, env `MODBUS_CACHE_ALLOW_WRITE` accept `true`/`false`) |
| `--connect-acl` | `any` | clients allowed to connect: `any` or comma-separated IPs/CIDR prefixes, IPv4 or IPv6 — see [Access control](#access-control) |
| `--write-acl` | `any` | clients allowed to write — still requires `--allow-write` — see [Access control](#access-control) |
| **Limits** | | |
| `--max-clients` | `64` | refuse further connections past this many simultaneous clients (`0` = no limit) |
| `--client-timeout` | `300` | disconnect clients silent for this many seconds — sheds connections from clients that died without closing (`0` = never) |
| **Logging** | | |
| `--log-level` | `INFO` | `DEBUG` adds per-client traffic |
| `--log-access` | `DEBUG` | log client connects/disconnects at `INFO` instead of `DEBUG` |
| `--local-time` | UTC | log timestamps in the system time zone instead of UTC |

`cache/src/modbus_cache.ini` is a sample with the defaults. Boolean ini/env
values accept `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`.

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

## Access control

Both ACLs default to **`any`**. When set, they take a comma-separated list
of IPs and CIDR prefixes (IPv4 or IPv6, e.g.
`--connect-acl 127.0.0.1,10.48.3.0/24`); the config-file/env/NixOS forms
are `connect_acl`/`write_acl` (NixOS `connectAcl`/`writeAcl`).

- **Connect ACL** — who may connect at all; a rejected connection is closed
  at accept and logged (`connection rejected: … not on the connect ACL`).
  From the client's view the connection opens and immediately dies.
- **Write ACL** — whose write requests are forwarded; everything else is
  refused with a Modbus illegal-function exception, logged with the client
  IP and the attempted payload. The connection stays up and reads keep
  working. Writing still requires `--allow-write`: effective write
  permission = `--allow-write` **and** client on the write ACL.

ACLs re-resolve on `SIGHUP` like every other setting; a malformed list keeps
the previous one.

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

## Nix / NixOS

```bash
nix run .#modbus-cache -- --host 192.168.1.100
```

```nix
imports = [ inputs.pv-dash.nixosModules.modbus-cache ];

services.modbus-cache = {
  enable = true;
  inverterHost = "192.168.1.100";   # the inverter's LAN IP
  openFirewall = true;              # when clients run on another host
};
services.sun2000-scraper = {
  enable = true;
  inverterHost = "127.0.0.1";       # the proxy
  inverterPort = 15502;
};
```

Options: `inverterHost`, `inverterPort`, `unitId`, `timeout`, `interval`,
`readDelay`, `mergeGap`, `registers` (structured entries — the module renders
them to a `registers.json` in the store, defaulting to the shipped map),
`registersFile` (explicit JSON file replacing the rendered one), `cacheTtl`
(unset = 3× `interval`), `listenHost`, `listenPort`, `allowWrite`,
`connectAcl`, `writeAcl`, `maxClients`, `clientTimeout`, `logLevel`,
`localTime`, `logAccess`, `openFirewall`. Unset options keep the proxy
defaults. The service runs with a dynamic user and systemd hardening.

The module renders the **config INI and the register map into the store**
and runs the service with `--config`. A `nixos-rebuild switch` applies
changes with `systemctl reload` (SIGHUP): register map, poll interval, cache
TTL, ACLs, limits and the upstream address are picked up live, client
connections stay up. Changes to `listenHost`/`listenPort`/`logLevel` need a
manual `systemctl restart modbus-cache`.

## Security

No authentication is used on either side. Modbus TCP (as spoken by the
SUN2000 inverter and this proxy) has no auth, no encryption and no access
control — the proxy forwards writes, so **anyone who can reach the listen
port can read and write inverter registers** (write forwarding is off until
`--allow-write` is set). Keep the proxy on a trusted LAN, bind `listenHost`
to a private interface and don't expose it to the internet.

Python is memory-safe (no buffer overflows, all request sizes bounds-checked
and fuzzed), but connection resources are not unlimited:
`maxClients` (default **64**) caps simultaneous clients (each is a thread)
and `clientTimeout` (default **300 s**) reaps clients that died without
closing; set `0` to disable either. The ACLs add per-source control within
the LAN; for stricter isolation use the firewall (`openFirewall`).

## Source layout

```
cache/src/
├── modbus_cache.py      # CLI, logging setup, signal handling
├── modbus_cache.ini     # sample config
├── registers.json       # example register map (SUN2000 monitoring set)
└── lib/
    ├── protocol.py      # wire format, errors, frame helpers
    ├── config.py        # settings resolution + register map loading
    ├── upstream.py      # the shared inverter connection
    ├── cache.py         # register cache + block planner
    └── proxy.py         # poller + client handling
```

## License

The proxy (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the repo-root `LICENSE` file.
