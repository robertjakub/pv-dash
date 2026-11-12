# Fake Inverter Simulator

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) Modbus TCP server that plays an
inverter — with a battery, a smart meter and the modbus-cache diagnostics
block — so the [modbus-scraper](../scraper/README.md), the
[modbus-cache](../cache/README.md) and the whole [pv-suite](../README.md)
stack can be exercised without hardware. Through **inverter profiles** it
can emulate different devices: the shipped default profile is the
`sun2000` (Huawei SUN2000) map, and Deye hybrid profiles are included as
well — see
[profiles/README.md](../profiles/README.md).

It ships three tools:

| Tool | Purpose |
|---|---|
| `modbus-fake-inverter.py` | the server (also packaged as `modbus-fake-inverter`) |
| `modbus-fake-cli.py` | console-style interactive session on the same control server (`modbus-fake-cli`) |

## How it works

Everything integrates with a **simulated clock: UTC by default**
(`--timezone local` / `set timezone local` for the host wall clock) that
can run at **N× real speed** (`--time-scale N` / `set time-scale N`) —
every machine integrates over it, so a full simulated day takes 24/N real
hours and moving the clock (`set time 18:00`) acts as time-lapse control.

- **The day** — bell-curve PV between 06:00 and 18:00 (peak 75 % of
  `--max-kwp`), home load with morning and evening peaks (grid exports
  around noon, imports mornings/evenings), panel temperature following the
  ambient curve, energy counters growing through the day.
- **`--static`** replaces the day with constant demo values: PV 4000 W,
  home 4300 W, grid −1500 W, battery charging 1200 W at 65 % SoC. The
  runtime control pins the individual terms on top of either mode.
- **PV (two MPPT strings)** — string-1 = the **east** array (sine bell
  06:00–16:00), string-2 = the **west** array (08:00–18:00): together a
  double-shouldered day. `set mppt both|east|west|none` enables the
  strings; a dark string serves 0 V/0 A. The cloud factor scales the sun
  in real time; the day yield integrates the actual string curve.
- **Battery** (always on) — charges from the
  PV surplus (300 W grid margin, max ±2500 W), covers the home deficit by
  discharging, stops at 100 % full / the 10 % reserve floor. The SoC is
  **stateful**: it integrates the effective power with the simulated
  clock, with the realism folded in — 95 % charge efficiency, 0.01 %/h
  self-discharge, discharge capped at 80 % of the rating,
  temperature-derated (below 0 °C half power, below 10 °C 80 %, above
  40 °C 90 %, above 50 °C 70 %). `set soc <pct>` seeds the machine, `set
  battery-state charging|discharging` forces it, `auto`/`clear` hands the
  decision back; `--battery-kwh` sizes the pack.
- **Grid setpoint** — `set grid <W>` pins the grid line: the battery
  balances to hold it (`set grid 0` = zero-export home); `auto` returns to
  the plain pv − battery − home balance.
- **Clouds** — a pinned factor (`set cloud 0.7`), a clear sky (the
  default), or a mean-reverting random walk: `autumn` (passing clouds,
  0.05–0.95), `spring` (fair-weather cumulus, 0.02–0.80), `winter` (heavy
  overcast spells, 0.10–1.00). `reset` returns to a clear sky.
- **Grid voltage** — three independent mean-reverting walks around the
  nominal (±10 % by default, the phases wander differently);
  `--grid-voltage` (230 V, 120 supported — the currents double),
  `--grid-voltage-wander` (the ±fraction of the nominal, 0 = the flat
  grid) and the matching `set grid-voltage` / `set
  grid-voltage-wander`.
- **Grid outages** — `set grid-outage on` arms a two-state machine: the
  grid randomly drops (phases collapse, the inverter stands by — no
  harvest, no battery flow, the SoC holds) and comes back after a few
  moments. `set grid-outage outage` forces a blackout right now (the
  outage wins over the pins); `off` restores plain operation.
- **The unbalanced home** — three slow walks around 1/3 per phase (each
  clamped 22–44 %) distribute the load asymmetrically: the per-phase meter
  currents really differ; the inverter injection stays balanced.

### Inverter profiles

The fake doesn't hardcode any device layout: the simulator computes
**named physical values** (`pv-power`, `grid-power`, `battery-soc`, …)
and the **inverter profile** maps each name onto a register address and
encoding. The format, the semantics and the shipped devices are documented
once in [profiles/README.md](../profiles/README.md). `show registers`
prints the loaded profile as a table, `set modbus profile <name|path>` swaps it
live, `--modbus-profile` / `MODBUS_PROFILE` pick it at start; `clear modbus
profile` returns to the configured map.

## Usage

```bash
python3 inverter/bin/modbus-fake-inverter.py                       # 127.0.0.1:5502 — scraper defaults just work
python3 inverter/bin/modbus-fake-inverter.py --time 12:00          # frozen noon: ~4.5 kW PV, exporting
python3 inverter/bin/modbus-fake-inverter.py --static              # the classic static demo values
python3 inverter/bin/modbus-fake-inverter.py --listen 127.0.0.1:15502 --log-level DEBUG
python3 inverter/bin/modbus-fake-inverter.py --config inverter/examples/modbus-fake-inverter.conf --dry-run
```

Add **`--dry-run`** to validate the configuration and print the effective
settings. Exit codes: `0` = valid; `1` = invalid; `2` = CLI misuse.

The fake ships as an alpine container — stdlib-only, no pip, running as
the unprivileged `pvsuite` user with the tools on `PATH`
(`Dockerfile.fake-inverter` + `compose.yaml`; see
[`docker/README.md`](../docker/README.md)). The image loads its own
bundled conf (`/pv-suite/inverter/modbus-fake-inverter.conf`, the built-in
`--config` target) — the env file and the CMD flags override it. The
version reports as `0.4.3` inside the image (no git metadata; a checkout
shows `0.4.3-<short git>`).

## Configuration

The startup surface is the family's: **flag > env > config script > the
built-in defaults**. The config file (`--config PATH`, `$CONFIG`, then
`modbus-fake-inverter.conf` next to the script) speaks the **set grammar** — every
line a `set <name> <value>` in the CLI spelling, the same line pastes
into the console or `modbus-fake-cli` — and the bundled sample is
[examples/modbus-fake-inverter.conf](examples/modbus-fake-inverter.conf). The pins and the
machines (`pv`, `load`, `batt`, `grid`, `soc`, `mppt`, `cloud`,
`scenario`, `battery-state`, `grid-outage`) stay control-wire settings:
the config names one and the start refuses. The flags:

| Flag | Default | Meaning |
|---|---|---|
| `--listen` / `--unit` | `127.0.0.1:5502` / `1` | the Modbus TCP serve address `HOST:PORT` and the unit id served |
| `--modbus-profile` | `sun2000` | register-map profile: the built-in name or a JSON path (`MODBUS_PROFILE` when unset) |
| `--static` / `--battery-kwh` | off / `6.9` | static demo values / the battery's usable capacity in kWh |
| `--max-kwp` | `6` | PV array size in kWp (peak = 75 % of it) |
| `--grid-voltage` / `--grid-frequency` | `230` / `50` | nominal grid phase voltage (120 or 230) / frequency |
| `--grid-voltage-wander` / `--grid-frequency-wander` | `0.1` / `0.2` | the voltage machine's wander fraction (±10 % by default; 0 = the flat grid) / the frequency machine's clamp in Hz (±0.2 by default) |
| `--time` / `--time-scale` / `--timezone` | real clock / `1` / `utc` | freeze simulated time `HH:MM` / the N× time-lapse factor / the machines' clock |
| `--max-clients` / `--client-timeout` / `--max-conn-per-ip` | `64` / `300` / `0` | the Modbus caps (refuse past the count / kick the silent / per-IP cap; `0` = no limit; `$MAX_CLIENTS` / `$CLIENT_TIMEOUT` / `$MAX_CONN_PER_IP`) |
| `--connect-acl` | any | the Modbus clients allowed to connect: `any`, `none`, or a comma-separated IP/CIDR list — the family ACL map lives in [docs/common/ACL.md](../docs/common/ACL.md) |
| `--allow-write` | off | accept Modbus writes (FC05/06/15/16): a write lands in the write overlay, logged and audited; off = every write refused with exception 01 |
| `--modbus-auth` / `--modbus-auth-key` | `none` | the auth scheme the fake's Modbus clients must speak: `suite` = the crypt handshake (the scraper takes the matching `--modbus-auth suite --modbus-auth-key …`); the key is a secret, `file:<path>` welcome |
| `--metrics-server` / `--metrics-listen` | off / `127.0.0.1:9352` | the fake's own Prometheus `/metrics` (live-settable `set metrics-server on/off`; refuses to start beyond loopback without `--metrics-token` — the F13 shape) |
| `--metrics-token` / `--metrics-acl` | off / `any` | the /metrics bearer token (`file:<path>` welcome) / the connect ACL (the ip-prefix grammar) |
| `--metrics-max-clients` / `--metrics-client-timeout` / `--metrics-max-conn-per-ip` | `64` / `5` / `0` | the metrics caps |
| `--control-port` | `/tmp/fake-inverter-<port>.socket` | control server target (unix socket or TCP port), `0` = off |
| `--control-token` / `--control-ops-token` / `--control-ops-verbs` | off / off / `show` | the control tokens (a secret, `file:<path>` welcome) / the ops role's RBAC policy (`flush` is not a verb here) |
| `--control-trust-uids` / `--control-socket-group` / `--control-log-replies` | none / off / off | the extra trusted uids (`SO_PEERCRED`) / the socket's 0660 mode / DEBUG-log the full control output (plainly: the command and its status; live: `set system log-replies`) |
| `--log-access` / `--local-time` | off / UTC | the Modbus connects at INFO instead of DEBUG (live: `set system log-access`) / the log stamps in the system time zone (live: `set system local-time`) |
| `--dump-path` / `--dump-key` / `--dump-interval` / `--restore-on-start` | off | the sealed state dump (the pins, the machines — the tokens apart; every `--dump-interval` seconds) |
| `--chaos` / `--seed` | `0` / random | the chaos probability / the RNG seed — see [Chaos injection](#chaos-injection---chaos) |
| `--strict` | off | reject undefined registers with exception 02 |
| `--audit-log` (+ `--audit-max-mb`, `--audit-daily`, `--audit-files`, `--no-audit-log`, `--audit-forward`, `--audit-forward-format`) | XDG state | the audit trail: a file path, `-` for stdout (the docker logs / journald way) or `none` (no local file — the forward carries the trail) (`$AUDIT_LOG` / `$AUDIT_MAX_MB` / `$AUDIT_DAILY` / `$AUDIT_FILES` / `$NO_AUDIT_LOG` / `$AUDIT_FORWARD` / `$AUDIT_FORWARD_FORMAT`); the forward mirrors every line onward (F10) |
| `--config` / `--log-level` / `--man` | `modbus-fake-inverter.conf` / `INFO` / off | the config script (the set grammar, above) / the log surface / print the generated man page |

`SIGHUP` re-applies the **environment layer** (all-or-nothing — flags are
startup-only): `CHAOS` (0..1), `MAX_KWP`, `PROFILE`, `STRICT`,
`TIME`, `TIME_SCALE`, `LOG_LEVEL` — booleans accept
`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`. The same twins ride the
start in the ladder — `CHAOS=0.9` at creation is honored, SIGHUP retunes
a running fake.

## Runtime control

### Signals

| Signal | Effect |
|---|---|
| `SIGHUP` | **Re-apply the environment layer** — all-or-nothing (invalid value keeps the previous settings). Flags are startup-only; the env is the reloadable layer. |
| `SIGUSR1` | **Reset the scenario**: all runtime pins, the cloud machine and the Modbus write overlay are dropped, the simulation continues. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown** with a session summary (duration, connections, requests, chaos hits). |

A JSON-lines control server runs **by default on the unix socket
`/tmp/fake-inverter-<listen-port>.socket`** — pass a TCP port number to
bind `127.0.0.1:PORT` instead, or `0` to switch it off. Both tools resolve
the target the same way: flag > **`CTL`** environment variable > the
default socket. The target also **rebinds live** — `set control port` —
and on the fake a **tokenless TCP rebind succeeds** (the F11 test-tool
posture; every other tool in the family refuses it — F5). Every command
and knob the wire answers — command, settable (`set`/`clear`) or
show-only — is tabled in [MANUAL.md](MANUAL.md) (generated from the
registry).

The wire is the family's JSON lines (one request object per line, one
reply per line: `{"cmd": …}` → `{"status": "ok|fail|note|bye", "text": …}`;
ping/pong keepalive) with the family's security shape: connections
authenticate when `--control-token` is set, the signed frames carry the
full HMAC of their payload over TCP (verify-if-present on the unix
socket), the trusted peers (root, the daemon's own user,
`--control-trust-uids` — `SO_PEERCRED`) skip the token, and the
**read-only ops token** (`--control-ops-token`) authenticates into the
`show` verbs only — the fake has no `flush` verb; watching is what the ops
shift does here. Both roles are audited. The fake is a test tool: token
flags land in `ps`, so prefer the `file:<path>` reference — but the flag
form is legitimate here in a way it never is on the daemons.

| Command | Effect |
|---|---|
| `set <setting> <value>` / `clear <setting>` | configure a setting (below) / restore its **configured startup value** |
| `show <setting>` / `show knobs` | the setting's current value / the whole knob registry |
| `show connections` | the fake's live **Modbus** clients: peer, connection age, requests served |
| `show registers` | the loaded profile's register map: `name \| register \| type \| value` — the value = what the registers serve right now, `NaN` = not calculated; the overlay rows are marked `*` |
| `inspect` | one pretty dump of everything — the baton for a bug report |
| `set scenario <name>` | a scenario preset: `morning`/`noon`/`evening`/`night` freeze the clock at a typical moment **and release the value pins**; manual pins turn it `custom` |
| `reset` | clear **all** pinned settings, the write overlay and the pinned coils/discrete inputs at once (like SIGUSR1, per-connection) |
| `request reload` | **restart the whole fake with the pins kept**: the live overrides save beside the config script (`<config>.reload`), the process re-execs and re-applies them once |
| `request reload-config` | re-read the config file without the restart: the config's values (flag > env > config) re-apply over the running machines — the demo knobs, not the pins; a broken file keeps the previous settings |
| `request dump` / `request restore` | with `--dump-path` configured: write the live overrides to the state file (`0600`, integrity-hashed) / load them back; `--dump-key` seals it, `--restore-on-start` does it automatically, the `--dump-interval` loop rewrites it live |
| `show version` / `help` / `help <setting>` / `quit` / `shutdown` | the version / the reference / one setting's description / close / graceful stop (a confirm guard) |

| Setting | Values | Meaning |
|---|---|---|
| `system listen` | `HOST:PORT` | the address the fake serves Modbus on (`show listen` answers it; restart to apply — `--listen`/`LISTEN` at start) |
| `pv` / `load` / `batt` | `W` \| `auto` | pin the PV power / the home load / the battery power (+charge/−discharge — the state machine integrates it into the SoC) |
| `grid` | `W` \| `auto` | pin the **grid setpoint** (+export/−import): the battery balances to hold it (`set grid 0` = zero-export) |
| `soc` | `%` \| `auto` | pin the state of charge (also seeds the machine) |
| `mppt` | `both` \| `east` \| `west` \| `none` | the enabled PV strings |
| `cloud` | `0..1` \| `clear` \| `autumn` \| `spring` \| `winter` | scale the PV: a pinned factor, a clear sky, or a cloud state machine |
| `grid-voltage` / `grid-frequency` | `120`\|`230` / Hz | the nominals the wander machines walk around |
| `grid-voltage-wander` / `grid-frequency-wander` | fraction / Hz | the machines' wander range (0 = the flat grid/frequency) |
| `grid-outage` | `on` \| `off` \| `outage` | the grid-outage machine; `outage` forces one now |
| `timezone` / `time` / `time-scale` | `utc`\|`local` / `HH:MM`\|`auto` / `N`\|`auto` | the machines' clock / freeze-unfreeze it / the time-lapse factor |
| `scenario` | `morning` \| `noon` \| `evening` \| `night` \| `custom` | the presets (above) |
| `battery-state` | `auto`\|`charging`\|`discharging` | force the battery machine at full power (the battery is always on) |
| `chaos` / `seed` | `0..1`\|`off` / `N` | tune chaos injection live / re-seed the RNG |
| `strict` / `static` | `on` \| `off` | reject undefined registers (exception 02) / switch static values vs the day simulation |
| `max-kwp` / `battery-kwh` | kW / kWh | the array size / the usable battery capacity |
| `max-clients` / `client-timeout` / `max-conn-per-ip` / `connect-acl` | — | the Modbus caps + who may connect (the flags above, tunable live) |
| `allow-write` | `on` \| `off` | the write gate (off refuses every write with exception 01) |
| `modbus auth` / `modbus auth key` | `suite` \| `none` / key | the auth scheme + key (secrets: `show` and `clear` refuse them) |
| `metrics enable` / `metrics token` / `metrics acl` | — | the /metrics endpoint and its connect ACL (live); the bearer is startup-only — pass it by flag/env/config, `file:<path>` welcome |
| `control port` / `control token` / `control ops token` / `control ops verbs` / `control trust-uids` / `control socket-group` | — | the control plane's live knobs (the listener rebinds, the socket re-modes; the tokens are startup-only — the restart is the rotation) |
| `dump path` / `dump restore-on-start` / `dump-interval` | — | the state dump's file, its restore mark, the automatic rewrite interval |
| `register` / `coil` / `discrete` | `set register <addr> <value>` etc. | the write-overlay emulation: raw register / coil / discrete-input pins (`reset` clears, `show registers` marks them) |
| `profile` / `log-level` | `<file>` / level | swap the register-map profile live / the live log level (`set system log-level`) |

The commands and settings — including their descriptions — live in the one
option registry (`lib/options.json`) that both the control server and the
CLIs read, so the wire grammar, the help texts and the completions can
never drift.

### `modbus-fake-cli` — one-shot / batch / console

```bash
python3 inverter/bin/modbus-fake-cli.py set pv 2500
printf 'set pv 2500\nset soc 30\nshow pv\n' | python3 inverter/bin/modbus-fake-cli.py --control-port 15599
```

Same `--control-port` flag / `CTL` env as the fake itself; several
commands can be passed as arguments or piped on stdin. Exit codes: `0` =
ok, `1` = connection/control error, `2` = CLI misuse. Every invocation
lands in the audit log.

### `modbus-fake-cli` — console-style session

An interactive front-end on the same socket (same flag/env resolution):

```
$ python3 inverter/bin/modbus-fake-cli.py

%   Welcome to the fake-inverter console
%   TAB completes, ? lists the commands, quit leaves

fake-inverter:5502 > set pv 2500
% changed

fake-inverter:5502 > help soc
soc - pin the state of charge (seeds the machine), or auto (values: %|auto)

fake-inverter:5502 > shutdown
Proceed with shutdown? [confirm] y
% bye shutdown
```

TAB completes commands, settings **and their values** (one candidate per
line with the short descriptions from the shared registry); `?` prints the
same list anywhere. `set`/`clear` print the `% changed` confirmation, `show`
prints the bare value. Every reply prints through the console's pager: a
reply taller than the screen pauses (`-- more --`), space prints the next
page, return one more line, `q` stops the rest — `--page-size`/
`CLI_PAGE_SIZE` set the page size (0 = off), the session-local `page`
command retunes it live (never sent to the daemon), and a terminal smaller
than 20 rows or 64 columns refuses to start. While idle the CLI sends wire
pings (every 55 s, `CLI_KEEPALIVE` to tune); when the connection dies it
retries `--reconnect` times (default 3) with `--reconnect-wait` seconds
(default 10) and resumes on the first success (`--reconnect 0` = die on
loss).

## Served registers (the default profile)

- **32064** / **32080** — PV power / power limit (I32 W)
- **32016+** — the string block: per-string voltage/current (a dark string
  serves 0/0)
- **37113** — grid power (I32 W, positive = feed-in)
- **37100+** — smart meter block: status, per-phase voltages/currents, reactive
  power, power factor, grid frequency, and 37119 exported / 37121 imported
  kWh totals that grow through the simulated day
- **32089** — device status (512 on-grid / 40960 standby at night)
- **32087** — temperature (I16, °C×10); **32114** daily and **32106** total
  yield (U32, kWh×100)
- **37001+** — battery block (power, SoC, lifetime
  totals)

All of the above addresses come from the profile — remap them freely. The
profile's per-entry **`fc`** picks each entry's address space (`3` holding
/ `4` input for the word types, `1` coils / `2` discrete for `bit` — the
four spaces are served separately). Writes stick in overlays: the register
writes (FC06/FC16) overlay the holding registers, the coil writes
(FC05/FC15) the coil space (FC5 demands the spec values
`0x0000`/`0xFF00`); computed registers are recomputed per poll, overlay
values win until cleared (`reset`, SIGUSR1, shutdown). A malformed frame
on an implemented function code is answered with exception 03, never a
silent disconnect.

## Internal registers (not in the profile)

**65000–65003** — the modbus-cache diagnostics block (magic `0xCAFE`,
version, uptime, id): always mocked by the fake, never part of the
profile — it exists so the scraper's `scraper_cache_*` auto-detection can
be exercised without a cache. It is the only address range the fake
hardcodes.

## Chaos injection (`--chaos`)

`--chaos 0.4` (probability, `--seed` for reproducibility) makes the fake
answer a fraction of requests hostile — garbage, short/lying MBAP lengths,
wrong transaction/unit ids, stalls, dropouts, raw exceptions — then drop
the connection. Unlike the regression suites' scripted EvilInverter this
runs unattended: point the scraper at it and watch
`scraper_modbus_errors_total` climb while `scraper_up` flips, with the
fake never dying. Tune or disable live (`set chaos off`).

## Audit trail

The fake itself and both clients append to the **audit log** — on by
default at the **XDG state home**
(`~/.local/state/fake-inverter/audit.log`); `--audit-log <file>` renames
it, `--no-audit-log` turns it off, `--audit-log -` sends it to stdout (the
docker logs / journald way — the shipped Dockerfile runs with it). The
whole family is live-settable on the control wire (the cache's shape):
`set audit log-file <path|-|none>` swaps the sink, `set audit instance
<id>` renames the writer daemon (`none` returns to the derived control
port), `set audit rotate
max-size <MB>` and `set audit rotate files <N>` re-chain the rotation
live, `set audit rotate daily on/off` rides too and `set audit disable
on/off` is the kill switch (`clear <setting>` restores the configured
value); the env twins spell the same names upper-snake. `--audit-forward` mirrors
every line — the per-writer hash chain included — onward: `syslog` (the
local socket auto-scan), `syslog:/path` (an explicit socket),
`udp://host[:514]` (RFC5426, best-effort) or `tcp://host[:514]` (RFC6587
framing) — the **off-box copy** beside the file/stdout sink (the F10
answer); the remote envelope rides `--audit-forward-format` (`rfc5424`,
the default, or `cef`), a send failure notes once and the next event
re-arms. `--audit-log none` turns the local file off: with a forward
spelled that is the **remote-only mode** (the collector is the sole
holder, the chain reseeds at GENESIS per run), without one the audit is
disabled (the state `--no-audit-log` spells).
The line names its writer — the fake `application=INV tag=daemon`, the ctl and
cli clients the shared `application=INV tag=cli` role — and carries an
`instance=<id>` word naming the writer daemon: the **control port** when
`--audit-instance` is unset (unique per host by construction), the override
when spelled. Keep an override unique among everything that shares one
collector — the native line and CEF carry no hostname, so pooled trails
name their instances apart; the chain groups by the triple:

```
2026-11-03T20:10:06Z AUDIT application=INV tag=daemon instance=15991 type=start hash=3f9a21c04de7 version=0.4.3 modbus=127.0.0.1:5502 control=127.0.0.1:15991 profile=sun2000 description='…'
2026-11-03T20:10:07Z AUDIT application=INV tag=daemon instance=15991 type=command hash=9c41e2b7a058 peer=127.0.0.1:54425 cmd='set soc 40' result=ok
2026-11-03T20:10:07Z AUDIT application=INV tag=daemon instance=15991 type=command hash=3d82f6c05e19 peer=127.0.0.1:54426 role=ops cmd='show connections' wire=h4b91de207a86 result=ok
2026-11-03T20:10:08Z AUDIT application=INV tag=daemon instance=15991 type=reset hash=77b0c4e19d23 signal=SIGUSR1 pins=1 coils=0 overlay=0
2026-11-03T20:10:08Z AUDIT application=INV tag=daemon instance=15991 type=shutdown hash=5e2af8c30b61 reason=SIGTERM-received uptime=2s conns=0 requests=0 chaos_hits=0
```

The 12-hex token after the event name is the entry's **chained hash** (the
audit's F10): any edit, deletion or reordering shows up as a chain break
in `scripts/audit_verify.py`. **Every wire command is audited once, by the
server** (with the peer, the role, the mac); the clients audit their
session and the local-only events; the fake logs its lifecycle (`START`,
`RELOAD`, `RESET`, `SHUTDOWN`). ping/pong keepalives are never logged; the
file is flushed per event.

## Security

> **The fake is a development tool — run it on a trusted, LAN-isolated
> network.** It is deliberately *not* security-first design (the audit's
> F11). The full story — the caps, the optional `--modbus-auth suite`
> handshake, the supply-chain claim — is
> [docs/SECURITY.md](../docs/SECURITY.md).

## Testing

The fake is the suites' workhorse — it is exercised from the suite-root
[`tests/`](../tests/):

```bash
tests/battery.py inverter        # the inverter profile: the fake's regtest, the
                                 #   control fuzz, the audit chain (the suites refuse
                                 #   without the runner's PV_RUN_DIR)
```

Every scenario must end with the fake alive and **zero tracebacks** in the
logs.

## Source layout

```
inverter/
├── bin/
│   ├── modbus-fake-inverter.py    # CLI entry, logging, wiring
│   └── modbus-fake-cli.py         # console-style interactive control session
└── lib/
    ├── options.json    # the knob registry: the flags, the env twins, the live settings
    ├── options.py      # its loader: the Option rows, the control-grammar vocabulary
    ├── profile.py      # register-map profiles: name registry, encoding, loading
    ├── simulator.py    # day curves, runtime overrides, named values, cloud machines
    ├── battery.py      # the battery state machine (SoC state, decision, integration)
    ├── inverter.py     # Modbus TCP server: FC1-FC4 reads, writes behind the write gate, chaos
    ├── control.py      # JSON-lines control server (set/clear/show, scenarios)
    ├── metrics.py      # the fake's own Prometheus /metrics endpoint
    ├── audit.py        # the append-only audit trail (the KV lines, application=INV)
    ├── chaos.py        # seeded hostile-reply dice layer
    ├── signals.py      # SIGHUP/SIGUSR1/SIGTERM handling
    ├── statics.py      # static configuration loader (lib/defaults.json)
    ├── defaults.json   # the statics: solar times, cloud machines, battery limits
    └── paths.py        # default control-socket path
```

## License

The fake inverter (source, Nix packaging) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
