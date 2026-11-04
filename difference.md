# difference.md — the inverter vs. the cache subprojects

The two tools grew from one family pattern: a JSON-lines control server,
a settings registry driving set/unset, an append-only audit trail and a
console-style CLI with reconnect. This document lists how the
implementations stand side by side — what is shared, what was adapted to
each tool's nature, what exists on only one side.

## Shared verbatim (the family pattern)

- **JSON-lines framing** — one request per line `{"cmd": "<command>"}`, one
  reply per line `{"status": "ok|err|bye", "text": "…"}`; a non-dict or
  non-`cmd` payload is answered `err malformed request: expected {"cmd":
  "<command>"} JSON` and the connection stays up.
- **Token auth on TCP only** — when `--control-token` is set, the first
  command on a TCP connection must be `{"cmd": "auth", "token": "…"}`;
  compared with `hmac.compare_digest`; wrong token → `err bad token`,
  missing auth → `err authenticate first`. Unix sockets skip auth (the
  filesystem permissions are the gate). A token-less `auth` is always
  `err bad token`. Both tools (and every CLI client) also take the token
  from a file — `--control-token-file` / `*_CONTROL_TOKEN_FILE`, the first
  line of a key file or a systemd `LoadCredential`; mutually exclusive
  with the inline token.
- **Audit trail** — the same `AuditLog` class (copied, not imported): one
  `<UTC stamp> AUDIT <PREFIX> <EVENT> [detail]` line per event, append-only,
  flushed per event, thread-safe (one lock around write+flush+rotate —
  without it a concurrent rotation races a writer into an ENOENT); XDG
  state home by default, `-` → stdout (no rotation by definition),
  unwritable path → stdout fallback; gated rotation (`--audit-max-mb`
  10 MB default, `--audit-daily`, `--audit-files` 3).
- **Server-side command auditing** — every wire command is audited once, by
  the server (`COMMAND peer=… '<cmd>' -> ok|err`), with `AUTH-FAIL` on bad
  tokens; ping/pong keepalives are never audited.
- **CLI session auditing** — the CLIs audit their session (CONNECT /
  DISCONNECT with the target and user, RECONNECT attempts) plus the
  local-only events (quit, help, `?`, an aborted shutdown); they never
  audit the wire commands (the server owns those).
- **The settings registry** (`lib/settings.py`, mirrored) — every setting
  with its description, completable values and value hints; the control
  server and the console CLI read from the same file, so the wire grammar,
  the help texts and the completions can never drift.
- **`set` / `unset` / `show <setting>` / `show settings` / `help
  <setting>`** — the same reply shapes: `set` applies a validated value and
  answers `ok key=value <state summary>`; `unset` restores the **configured
  startup value** (what the flag/env/ini said at start); a bad value is a
  friendly one-line `err` (never a Python message); `show settings` is one
  space-separated `key=value` line (scriptable).
- **Reconnect protocol** (`cache_cli` ≡ `fake_cli`) — a dead wire raises
  ConnectionLost; the session retries `--reconnect` times (default 3),
  `--reconnect-wait` seconds apart (default 10), re-running the token
  handshake on each fresh socket; `--reconnect 0` = die on loss. Every
  attempt is audited and printed as `% connection lost, reconnecting …`.
- **Keepalive** — wire pings every 55 s while idle (`*_CLI_KEEPALIVE` env,
  `0` = off), pongs absorbed by the reply reader (replies are ordered, the
  pong can land before or after the awaited reply).
- **Buffered frame reads** — 64 KB `recv` chunks split on `\n` (a 1 MB
  frame must not cost a syscall per byte); the accept backlog is 16.
- **Shutdown hand-off** — a `shutdown` command flips a pending flag; the
  stopper runs after the reply left the wire.
- **Config resolution chain** — flag > `MODBUS_CACHE_*`/`FAKE_*` env >
  ini > defaults (the audit/token settings ride the same chain as
  everything else).
- **Exit codes** — 0 = ok, 1 = connection/control error, 2 = CLI misuse.
- **Welcome-on-TTY** — both CLIs greet only on an interactive stdin; piped
  runs (tests) get clean output.
- **Static constants** — both keep them in `lib/static.json` (loaded by
  `lib/statics.py`) in the same grouped shape: the protocol limits, the
  diagnostics block and every shipped default (flags, CLIs, audit
  rotation, keepalives, idle timeouts) — plus each tool's own physics:
  the inverter's solar times, load curve, grid nominals/wander, cloud and
  outage machines, battery limits; the cache's register-type word map.
- **bin/ lib/ layout** — the entry scripts in `bin/` (with the sys.path
  bootstrap for the dev checkout), the modules + data files in `lib/`;
  both packages install flat and ship three wrappers
  (`modbus-fake-{inverter,ctl,cli}`, `modbus-cache{-ctl,-cli}`); both have
  a Dockerfile + a compose service.

## Adapted (same shape, different content)

| Aspect | inverter | cache |
|---|---|---|
| Audit prefixes | `INV` / `CLI` / `CTL` | `CACHE` / `CLI` / `CTL` |
| Audit default dir | `~/.local/state/fake-inverter/` | `~/.local/state/modbus-cache/` |
| Default control socket | `/tmp/fake-inverter-<modbus-port>.socket` | `/tmp/modbus-cache-<listen-port>.socket` |
| Env for the target | `FAKE_CTL` | `MODBUS_CACHE_CTL` (or short `CACHE_CTL`) |
| Env for the token | `FAKE_CONTROL_TOKEN` (+ `_FILE` for the file form) | `MODBUS_CACHE_CONTROL_TOKEN` (or short `CACHE_CTL`; + `_FILE` for the file form) |
| Server class | `ControlServer(simulator, chaos, target, fake=…)` — mutates the simulator state | `ControlServer(proxy, target, stopper=…, defaults=…)` — inspects/steers the poller |
| Where the target resolution lives | `lib/paths.py` | `lib/config.py` (`resolve_control_target`, shared by proxy + both CLIs) |
| What the settings tune | the simulation: `pv/load/batt/soc` pins, `cloud/time/time-scale/grid-outage/scenario`, chaos, `strict/static`, `profile` | the proxy: `interval`, `ttl`, `read-delay`, `merge-gap` (the poll plan rebuilds live), `allow-write`, `write-registers`, `max-clients`, `client-timeout`, `reads-audit`, `log-level` |
| `status` in the replies | the simulated state: `pv=…W load=…W batt=…W soc=…% cloud=… chaos=…` | the poller state: `upstream=… interval=… ttl=… poll=ok hits=… misses=… clients=…` |
| `show settings` / `show status` | `ok settings` / `ok status` followed by one stable `key=value` line per field (scriptable) | the same multi-line shape (`ok settings` / `ok status` + one `key=value` per line) |
| Welcome banner content | profile, uptime, clock zone, grid V, battery state | upstream, poll health, last-poll age, uptime, client count |
| `quit` on the wire | server replies `bye` and closes | server closes with **no reply** (the pre-port behaviour kept) |
| SIGHUP semantics | re-applies the `FAKE_*` environment layer (keep-last-good) | re-resolves the whole config (registers, intervals, ACLs, the write allow-list) and swaps the map atomically |
| SIGUSR1 semantics | reset the scenario (pins + overlay cleared) | clean the cache, repoll now |

## Cache-only (no inverter counterpart)

- **FC4 input-register caching** — the profile entries carry an optional
  `fc` (3|4) field; the cache polls, caches and serves the two address
  spaces independently (blocks never merge across codes); a forwarded FC4
  read is cached on its way through. The fake serves the same map on both
  codes; the diagnostics block stays FC3-only. The scraper does not follow
  `fc` yet (cache/TODO.md).
- **Write gating and write auditing** — `--allow-write` (tunable live),
  the client `--write-acl`, the per-register `--write-registers
  START:COUNT,...` allow-list; every forwarded `WRITE`, `WRITE-REFUSED`,
  `WRITE-REJECTED` (device exception) and `WRITE-FAILED` (the session
  died) is audited. The inverter has no forwardable Modbus writes — its
  register overlays are audited as control commands.
- **The per-client READS accounting** — one audited `READS` tally per
  client per `--reads-audit` period (default 300 s) plus a final tally on
  every disconnect. The inverter's clients are single-user CLIs — nothing
  to tally.
- **`clear cache` / `restart`** — cache-specific destructive commands
  (drop cached values / drop the upstream session + cache, repoll now);
  the inverter's nearest analogue is `reset` (pins + overlay).
- **Diagnostics registers** — the synthesized 65000-65003 block
  (`0xCAFE`, device-up, cache age, uptime) is cache-only by definition.
- **Lifecycle audit details** — `START` records the upstream/listen/
  control/profile; `SHUTDOWN` records hits/misses alongside uptime and
  clients (the inverter records chaos hits instead).
- **`show version` reply** — `modbus-cache <version>` vs
  `fake-inverter <version>` (same `lib/version.py` copied; the git-descend
  depth differs by one directory level).
- **The NixOS module** — the cache ships one (`module.nix`: the rendered
  ini, the audit/control/write options, the LoadCredential token, the
  hardened dynamic user); the inverter has no module.

## Inverter-only (the cache has nothing like it)

- **The simulation settings** — the value pins (`pv/load/batt/grid/soc`),
  the state machines (clouds, grid voltage/frequency/outage, battery,
  MPPT), the scenario presets, `reset`, the `set register` write overlay.
- **The simulator introspection** — `show registers` (the live table with
  the overlay marks), the pinned-values section of `inspect`, the chaos
  counters.
- **The metrics server** (`--metrics-port` + bearer token) — the cache
  relies on the scraper's `huawei_cache_*` export (native endpoint
  proposed in cache/TODO.md).
- **The chaos injection** — seeded hostile replies (`--chaos`, `--seed`),
  audited `chaos_hits`.
- **`tests/control-fuzz.py` targets the inverter**; the cache's port lives
  as `tests/cache-control-fuzz.py` (same phases: malformed frames, 1 MB
  request, byte-by-byte assembly, frameless close, ping flood, token
  abuse, 20 parallel clients, still-serving check, clean shutdown).

## The suites

| | inverter | cache |
|---|---|---|
| functional regression | (the scrape/inverter phases of tests/scrape-regtest.py) | tests/cache-regtest.py — 98 checks |
| load | — | tests/cache-stress.py — 100 clients / 15 s |
| garbage frames | tests/scrape-fuzz.py (the client side) | tests/cache-fuzz.py |
| control-protocol fuzz | tests/control-fuzz.py | tests/cache-control-fuzz.py |
