# modbus-cache

A dependency-free (Python stdlib only) **Modbus TCP caching proxy** for devices
that accept only a single client — Huawei SUN2000 inverters and their
SDongle/EMMA radios are limited to one Modbus TCP connection, so the
[sun2000-scraper](../scrape/README.md) cannot share them with anything else.

> **Experimental — so far verified only against simulated data**
> (fake inverter + regression/stress suites), not against real hardware.

The proxy owns that one upstream connection and multiplexes it:

- a background loop **polls the configured register ranges** from the inverter
  at a fixed interval into an in-memory cache;
- any number of clients connect to the proxy and are **served FC3 reads from
  the cache** — no per-client inverter traffic;
- reads **outside the cached ranges** (and any other function code: FC4,
  writes, …) are **polled from the inverter live**, answered, and — for FC3
  reads — **cached for `--cache-ttl`** like everything else; every
  forwarded read is logged with register, size and outcome. Such a read
  waits for a free slot between poll reads, at most one transaction + read
  delay. Every **write** (FC06 single / FC16 multiple registers) is also
  logged with register, value(s) and outcome — accepted, rejected by the
  device (with the Modbus exception code) or failed (upstream unreachable).

If the inverter is unreachable, cached reads keep serving the last known
values (the poller logs `serving cached values` and reconnects on its own),
while forwarded reads get a Modbus exception `0x0B` (gateway target failed).
Every cached register carries the time it was last fetched, and entries
older than `--cache-ttl` (default: **3× the poll interval**; `0` = never
expire) are refetched from the inverter on the next read — fresh data when
it is back, the `0x0B` exception when it is not.

When the inverter rejects a cached range itself (e.g. the block crosses an
undefined register — the device answers Modbus exception `02` for the whole
request), the cache remembers that **poll status** and answers client reads
in that range with the same exception until a poll succeeds again — no
repeated device hammering, and clients see the failure the device actually
reports.

## Register map

The proxy caches whatever the **register map** file lists —
`registers.json` next to the script by default (override with `--registers-file`,
env `MODBUS_CACHE_REGISTERS_FILE` or ini `registers_file`; read once at startup,
restart to apply). The shipped **`cache/src/registers.json` is an example**
with the standard SUN2000 monitoring registers — the gains and sign
conventions from Huawei's *Modbus Interface Definitions* are noted in the
entry names. Edit it or write your own. The NixOS module does not use the
example file: it renders its own `registers.json` into the Nix store from the
`registers` option and runs the service with that file.

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

## Run

```bash
python3 cache/src/modbus_cache.py --host 192.168.1.100 --listen 0.0.0.0:15502
```

The source is split into a `lib/` package next to the entry script:
`protocol` (wire format/errors), `config` (settings + register map),
`upstream` (inverter connection), `cache` (register cache + block plan),
`proxy` (poller + client handling); `modbus_cache.py` holds the CLI,
logging and signal handling.

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

**`SIGHUP` reloads the configuration and the register map** without dropping
client connections: the map is swapped atomically (added ranges are polled,
removed ones pruned), poll interval, read delay, merge gap, cache TTL and
upstream address/unit/timeout take effect immediately (the upstream socket
reconnects on the next read). A broken file keeps the previous settings —
the error is logged and the next `SIGHUP` retries. The listen address and
log level need a restart.

**Write support is disabled by default**: write requests (FC05/06/15/16)
are answered with a Modbus illegal-function exception (`0x86`/`0x90` +
code `01`) and never reach the inverter. Start with `--allow-write` (ini
`allow_write`, NixOS `services.modbus-cache.allowWrite`) to forward them.

**`SIGUSR1` cleans the cache**: all cached values, on-demand entries and
poll-status errors are dropped atomically (client connections stay up), the
next reads go to the inverter live and the poller repopulates immediately:

```bash
kill -USR1 $(pgrep -f modbus_cache.py)
```

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | inverter/dongle Modbus TCP address |
| `--port` | `5502` | inverter Modbus TCP port |
| `--unit` | `1` | Modbus unit id |
| `--timeout` | `3` | Modbus connect/read timeout, seconds |
| `--listen` | `0.0.0.0:15502` | proxy listen address |
| `--interval` | `10` | seconds between cache polls |
| `--read-delay` | `0.05` | seconds between consecutive inverter reads within a poll cycle (`0` = no wait) |
| `--merge-gap` | `8` | max register gap when merging ranges into block reads (`0` = read separately) |
| `--registers-file` | `registers.json` next to the script | JSON register map to cache (see above) |
| `--cache-ttl` | `3`× `--interval` | per-register cache TTL in seconds: older entries are refetched from the inverter (`0` = never expire) |
| `--allow-write` | disabled | forward write requests (FC05/06/15/16) to the inverter; disabled, they are refused with a Modbus illegal-function exception (env `MODBUS_CACHE_ALLOW_WRITE`, ini `allow_write` accept `true`/`false`) |
| `--log-level` | `INFO` | `DEBUG` logs per-client traffic |
| `--local-time` | UTC | log timestamps in the system time zone (env `MODBUS_CACHE_LOCAL_TIME`, ini `local_time`) |
| `--log-access` | DEBUG | log client connects/disconnects at `INFO` instead of `DEBUG` (env `MODBUS_CACHE_LOG_ACCESS`, ini `log_access`) |
| `--max-clients` | `0` (no limit) | refuse further connections past this many simultaneous clients (env `MODBUS_CACHE_MAX_CLIENTS`, ini `max_clients`) |
| `--client-timeout` | `0` (never) | disconnect clients silent for this many seconds — sheds connections from clients that died without closing (env `MODBUS_CACHE_CLIENT_TIMEOUT`, ini `client_timeout`) |
| `--connect-acl` | `any` | clients allowed to connect: `any` or comma-separated IPs/CIDR prefixes, IPv4 or IPv6 (env `MODBUS_CACHE_CONNECT_ACL`, ini `connect_acl`) |
| `--write-acl` | `any` | clients allowed to write — still requires `--allow-write` (env `MODBUS_CACHE_WRITE_ACL`, ini `write_acl`) |

`cache/src/modbus_cache.ini` is a sample with the defaults.

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
(unset = 3× `interval`), `listenHost`, `listenPort`, `logLevel`,
`openFirewall`. The service runs with a dynamic user and systemd hardening.

The module renders the **config INI and the register map into the store**
and runs the service with `--config`. A `nixos-rebuild switch` applies
changes with `systemctl reload` (SIGHUP): register map, poll interval,
cache TTL and the upstream address are picked up live, client connections
stay up. Changes to `listenHost`/`listenPort`/`logLevel` need a manual
`systemctl restart modbus-cache`.

## Audit logging

The proxy logs every audit-relevant event to stdout/stderr with UTC
timestamps by default (`--local-time` switches to the system time zone).
Under systemd, journald stores, seals and rotates these lines — point your
NIS2/DORA documentation at `journalctl -u modbus-cache` and keep a
retention policy (e.g. `/etc/systemd/journald.conf`:
`MaxRetentionSec=90day`). Modbus has no authentication, so the client's
source IP is the only identity there is (connect/disconnect events are
logged at `DEBUG` unless `--log-access` is set).

| Event | Log line |
|---|---|
| Forwarded write | `write: register 47415 = 99 (single register, unit 1)` |
| Write refused (support disabled) | `write: refused register … (write support disabled …)` |
| Device rejects a forwarded write | `write rejected by the device: … (modbus exception N)` |
| Device rejects a forwarded non-FC3 request | `forwarded FC22 rejected by the device (modbus exception N)` |
| Uncached read forwarded + cached | `read: registers … not cached, polling the device` / `… ok, cached …` |
| Device rejects a forwarded read | `read: registers … rejected by the device (modbus exception N)` |
| Config/register-map reload (`SIGHUP`) | `SIGHUP: reload requested` / `SIGHUP: reloaded 13 range(s) …` / `SIGHUP: reload failed …` |
| Cache clean (`SIGUSR1`) | `SIGUSR1: cache cleared (N register(s) dropped), repolling now` |
| Client connect/disconnect (`--log-access`) | `client connected: 10.0.0.5:51234` / `client … disconnected (…)` |
| Cache poll failed/recovered | `poll of … failed (modbus exception, code 2), serving cached values` |
| Startup / shutdown | `caching 13 range(s) …` / `shutdown: SIGTERM received, closing the listener` |

Useful filters:

```bash
journalctl -u modbus-cache --since today | grep 'write:'      # all write attempts
journalctl -u modbus-cache | grep -E 'SIGHUP|shutdown'        # lifecycle
```

## Access control

Both ACLs default to **`any`**. When set, they take a comma-separated list
of IPs and CIDR prefixes (IPv4 or IPv6, e.g.
`--connect-acl 127.0.0.1,10.48.3.0/24`); the config-file/env/NixOS forms
are `connect_acl`/`write_acl` (NixOS `connectAcl`/`writeAcl`).

- **Connect ACL** — who may connect at all; a rejected connection is
  closed at accept and logged (`connection rejected: … not on the connect ACL`).
- **Write ACL** — whose write requests are forwarded; everything else is
  refused with a Modbus illegal-function exception, logged with the client
  IP. Writing still requires `--allow-write`: effective write permission =
  `--allow-write` **and** client on the write ACL.

ACLs re-resolve on `SIGHUP` like every other setting; a malformed list
keeps the previous one.

## Security

No authentication is used on either side. Modbus TCP (as spoken by the
SUN2000 inverter and this proxy) has no auth, no encryption and no access
control — the proxy forwards writes, so **anyone who can reach the listen
port can read and write inverter registers** (write forwarding is off
until `--allow-write` is set). Keep the proxy on a trusted
LAN, bind `listenHost` to a private interface and don't expose it to the
internet. Memory/resource exhaustion is bounded the same way as buffer
overflows are impossible in Python, but connection resources are not
unlimited by default: `maxClients` caps simultaneous clients (each is a
thread) and `clientTimeout` reaps clients that died without closing —
e.g. `maxClients = 64; clientTimeout = 300;` are reasonable LAN values.

## License

The proxy (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the repo-root `LICENSE` file.
