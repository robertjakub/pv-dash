# difference.md — the inverter vs. the cache control surface

The control-surface work (JSON-lines transport, token auth, audit trail,
CLI reconnect) was built for the fake inverter, then ported to modbus-cache.
This lists how the two implementations differ — what is shared verbatim,
what was adapted, what exists on only one side.

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
  `err bad token`.
- **Audit trail** — the same `AuditLog` class (copied, not imported): one
  `<UTC stamp> AUDIT <PREFIX> <EVENT> [detail]` line per event, append-only,
  flushed per event, thread-safe (one lock around write+flush+rotate —
  without it a concurrent rotation raced a writer into an ENOENT that
  killed client connections under load); XDG state home by default, `-` →
  stdout (no rotation by definition), unwritable path → stdout fallback;
  gated rotation (`--audit-max-mb` 10 MB default, `--audit-daily`,
  `--audit-files` 3).
- **Server-side command auditing** — every wire command is audited once, by
  the server (`COMMAND peer=… '<cmd>' -> ok|err`), with `AUTH-FAIL` on bad
  tokens; ping/pong keepalives are never audited.
- **CLI session auditing** — the CLIs audit their session (CONNECT /
  DISCONNECT with the target and user, RECONNECT attempts) plus the
  local-only events (quit, help, `?`, an aborted shutdown); they never
  audit the wire commands (the server owns those).
- **Reconnect protocol** (`cache_cli` ≡ `fake_cli`) — a dead wire raises
  `ConnectionLost`; the session retries `--reconnect` times (default 3),
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

## Adapted (same shape, different content)

| Aspect | inverter | cache |
|---|---|---|
| Audit prefixes | `INV` / `CLI` / `CTL` | `CACHE` / `CLI` / `CTL` |
| Audit default dir | `~/.local/state/fake-inverter/` | `~/.local/state/modbus-cache/` |
| Default control socket | `/tmp/fake-inverter-<modbus-port>.socket` | `/tmp/modbus-cache-<listen-port>.socket` |
| Env for the target | `FAKE_CTL` | `MODBUS_CACHE_CTL` (or short `CACHE_CTL`) |
| Env for the token | `FAKE_CONTROL_TOKEN` | `MODBUS_CACHE_CONTROL_TOKEN` |
| Server class | `ControlServer(simulator, chaos, target, fake=…)` — mutates the simulator state | `ControlServer(proxy, target, stopper=…)` — inspects/steers the poller |
| Where the target resolution lives | `lib/paths.py` | `lib/config.py` (`resolve_control_target`, shared by proxy + both CLIs) |
| Command dispatch | `set/unset/show <setting>`, registry-driven, per-setting parsers | whole-line verbs (`show status`, `clear cache`, `restart`), no settings registry |
| `show` output | settings registry: bare values, key=value reports, multi-line tables with the `.`-stripping in `framed` | one-line status/connections/cache strings (no multi-line replies, no `.` handling needed) |
| Welcome banner content | profile, uptime, clock zone, grid V, battery state | upstream, poll health, last-poll age, uptime, client count |
| `quit` on the wire | server replies `bye` and closes | server closes with **no reply** (the pre-port behaviour kept) |
| Handlers | signal handling via the `SignalBox` (env layer re-application on SIGHUP) | signal watchers installed by the entry point (full config re-resolution on SIGHUP) |

## Cache-only (no inverter counterpart)

- **Write auditing** — the proxy's audit trail records every forwarded
  `WRITE`, plus `WRITE-REFUSED` (support disabled / client off the write
  ACL), `WRITE-REJECTED` (device exception) and `WRITE-FAILED` (upstream
  session died). The inverter has no forwardable Modbus writes, so it has
  no equivalents — its register overlays are audited as control commands.
- **`clear cache` / `restart`** — cache-specific destructive commands
  (drop cached values / drop the upstream session + cache, repoll now);
  the inverter's nearest analogue is `reset` (pins + overlay).
- **SIGHUP semantics** — the cache re-resolves the *whole* config
  (registers, intervals, ACLs, upstream address) and swaps the map
  atomically; the inverter re-applies only its `FAKE_*` environment layer.
- **SIGUSR1 semantics** — clean the cache (the inverter: reset the
  scenario).
- **Diagnostics registers** — the synthesized 65000-65003 block
  (`0xCAFE`, device-up, cache age, uptime) is cache-only by definition.
- **Lifecycle audit details** — `START` records the upstream/listen/
  control/profile; `SHUTDOWN` records hits/misses alongside uptime and
  clients (the inverter records chaos hits instead).
- **`show version` reply** — `modbus-cache <version>` vs
  `fake-inverter <version>` (same `lib/version.py` copied; the git-descend
  depth differs by one directory level).

## Inverter-only (the cache has nothing like it)

- **The settings registry** (`lib/settings.py`): `set`/`unset`/`show
  <setting>` with per-setting validation, values, hints and `help
  <setting>` — the cache has no runtime-tunable settings yet (proposed in
  cache/TODO.md).
- **Scenario presets, `inspect` dump, the registers table, the status
  report** — simulator introspection.
- **The metrics server** (`--metrics-port` + bearer token) — the cache
  relies on the scraper's `huawei_cache_*` export (native endpoint
  proposed in cache/TODO.md).
- **Static config in JSON** (`lib/static.json`) — the inverter keeps its
  data file in `lib/`; the cache's user-facing samples (`modbus_cache.ini`,
  `selection.json`) sit at the subproject root instead — they are shipped
  defaults/examples a user copies, not library data.
- **`tests/control-fuzz.py` targets the inverter**; the cache's port lives
  as `tests/cache-control-fuzz.py` (same phases: malformed frames, 1 MB
  request, byte-by-byte assembly, frameless close, ping flood, token
  abuse, 20 parallel clients, still-serving check, clean shutdown).

## Layout parity (both subprojects now)

- `bin/` (the entry scripts, `sys.path` bootstrap to the checkout root) +
  `lib/` (the modules, data files, the sample config) — `src/` is gone
  from both.
- Both packages install flat (`share/<name>/*.py` + `lib/`) and ship three
  wrappers: `modbus-fake-{inverter,ctl,cli}` and
  `modbus-cache{-ctl,-cli}`.
- Both have a Dockerfile + a compose service (the cache's upstream
  defaults to the `fake-inverter` service name).

## Uncommitted inverter work with no cache bearing

The inverter's working tree (the priced-grid/battery/time-scale/
grid-outage wave: `simulator.py`, `battery.py`, `statics.py`, …) is
simulator physics and inverter-specific settings — nothing there is
control-protocol-generic, so the cache port is complete without it.
