# Fake Inverter Simulator

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) Modbus TCP server that plays an
inverter — with a battery, a smart meter and the modbus-cache diagnostics
block — so the [modbus-scraper](../scraper/README.md), the
[modbus-cache](../cache/README.md) and the whole [pv-suite](../README.md)
stack can be exercised without hardware.

Through **inverter profiles** it can emulate different devices: the shipped
default profile is the Huawei SUN2000 map, and Deye hybrid profiles are
included as well — see [profiles/README.md](../profiles/README.md).

It ships three tools:

| Tool | Purpose |
|---|---|
| `modbus-fake-inverter.py` | the server (also packaged as `modbus-fake-inverter`) |
| `modbus-fake-ctl.py` | one-shot / batch client for the runtime control server (`modbus-fake-ctl`) |
| `modbus-fake-cli.py` | console-style interactive session on the same control server (`modbus-fake-cli`) |

## Quick start

```bash
python3 inverter/bin/modbus-fake-inverter.py                       # 127.0.0.1:5502 — scraper defaults just work
python3 inverter/bin/modbus-fake-inverter.py --time 12:00          # frozen noon: ~4.5 kW PV, exporting
python3 inverter/bin/modbus-fake-inverter.py --static              # constant PV 4000 W, grid -1500 W, battery charging 1200 W at 65 %
python3 inverter/bin/modbus-fake-inverter.py --port 15502 --log-level DEBUG
```

## Simulation

All the state machines integrate with a **simulated clock: UTC by default**
(`--timezone local` / `set timezone local` for the host wall clock; the
frozen `--time`/`set time` clock is zone-independent). The clock can also
run at **N× real speed** (`--time-scale N` / `set time-scale N`): every
machine — the battery, the clouds, the voltages, the day counters —
integrates over it, so a full simulated day takes 24/N real hours
(x1 = real time; `set time-scale auto` returns there).

By default it simulates a sunny day: bell-curve PV between 06:00 and 18:00
(peak 75 % of `--max-kwp`), home load with morning and evening peaks — so the
grid exports around noon and imports in the mornings/evenings. Panel
temperature follows the ambient curve + sun heating. Energy counters grow
during the simulated day. The battery state machine decides
charge/discharge every tick (battery on by default, `--no-battery` opts
out) — described below. Raw wire values are watts / kWh×100 like the
default profile's map.

`--static` replaces the day simulation with constant demo values: PV
4000 W, home 4300 W, grid −1500 W, battery charging 1200 W at 65 % SoC —
the classic numbers, useful for screenshots and the load tests. The
runtime control (`set pv`, `set load`, …) pins the individual terms on
top of either mode.

### The state machines

**PV (the sun, two MPPT strings).** The array is two strings with an
east/west orientation — string-1 = the **east** array (sine bell 06:00–16:00,
peaking late morning), string-2 = the **west** array (08:00–18:00, peaking
early afternoon). Each carries half the array; together they make a
double-shouldered day with a high midday plateau. `set mppt
both|east|west|none` enables/assigns the strings (`both` = the default);
a dark string serves 0 V/0 A, `none` = PV 0. The cloud factor scales the
sun in real time. The day yield integrates the actual string curve.

**Battery.** The battery state machine (day simulation, battery on — the
default; `--no-battery` opts out):

- charges from the PV surplus, keeping a 300 W grid margin (max ±2500 W)
- covers the home deficit by discharging (150 W standby excluded)
- stops at the bounds: 100 % full, 10 % reserve floor

The SoC is **stateful**: it integrates the effective battery power with the
simulated clock — charge/discharge really moves the %SoC, with the realism
folded in:

- the **charge efficiency** is 95 % (5 % losses on the way in)
- the **self-discharge** is 0.01 %/h
- the **discharge is capped at 80 % of the rating** — a 10 kW battery can
  output at most 8 kW to the home (the full rating charges)
- the power is **temperature-derated**: the deep cold (below 0 °C) allows
  half power, below 10 °C 80 %, above 40 °C 90 %, above 50 °C 70 % (the
  battery follows the site temperature model) Moving the clock (`set time 18:00`) therefore
acts as a time-lapse control; a full battery holds the surplus for the
grid; a drained one lets the grid cover the home. `set soc <pct>` seeds the machine (unpinning
resumes from there); `reset` re-seeds the SoC from the simulated day.
`set battery-state charging|discharging` forces the machine to full charge or
discharge power regardless of the surplus (the SoC bounds still hold); `auto`
(or `unset battery-state`) hands the decision back to the machine.

**Grid setpoint.** `set grid <W>` pins the grid line: the battery balances —
it charges or discharges whatever holds the grid at the pinned power, so
`set grid 0` is a zero-export home (the surplus charges, the deficit
discharges, the battery limits let the residual spill to the grid). `auto`
(or `unset grid`) returns the grid to the plain pv − battery − home balance.

**Clouds.** A pinned factor (`set cloud 0.7`), a clear sky (`set cloud clear`
— the default state, shown as `cloud=clear`), or a small state machine — a
mean-reverting random walk over the simulated clock:

| Mode | Character |
|---|---|
| `autumn` | passing clouds, quick swings (factor mostly 0.05–0.95 around a 0.45 mean) |
| `spring` | fair-weather cumulus, brief dips (mostly 0.02–0.80 around a 0.25 mean) |
| `winter` | heavy overcast spells, slow breaks (mostly 0.10–1.00 around a 0.75 mean) |

Like the battery, the machines integrate with the simulated clock: clock
jumps move the clouds (time-lapse), a frozen clock freezes them. `reset`
returns to a clear sky.

**Grid voltage.** The grid-side phase voltages come from a small state
machine: three independent mean-reverting walks around the nominal voltage,
clamped to ±10 % — the phases wander differently (an unbalanced grid). It
integrates with the simulated clock like everything else (time-lapse moves
it, a frozen clock freezes it). The nominal comes from `--grid-voltage`
(default 230 V, `120` supported — the currents double to carry the same
power) and `set grid-voltage 120|230` at runtime; the output- and
meter-voltage/current registers follow per phase.

**Grid outages.** `set grid-outage on` arms a two-state machine over the
simulated clock: the grid randomly drops (the phases collapse to 0 V, the
frequency and the meter read 0, the inverter stands by — no harvest, no
battery flow, no export, the SoC holds, the strings keep their
open-circuit voltage) and comes back after a few moments. The hazards
(fail per simulated hour, repair per simulated minute) live in
`lib/static.json`; the machine is seeded like everything else and the
time-lapse factor speeds it up. `set grid-outage outage` forces a blackout
right now (the demo switch — the outage wins over the pins);
`set grid-outage off` restores plain operation (`auto` = the machine
decides, like `on`); `reset` and SIGUSR1 drop the machine like the clouds.

**The unbalanced home.** The home load is not split into symmetric thirds:
three slow mean-reverting walks around 1/3 per phase (each clamped to
22–44 %, renormalised) distribute the load asymmetrically — the per-phase
meter currents really differ. The inverter injection stays balanced; the
meter sees the net per-phase power.

### Inverter profiles

The fake doesn't hardcode any device layout: the simulator computes **named
physical values** (`pv-power`, `device-temperature`, `grid-power`,
`battery-soc`, …) and the **inverter profile** maps each name onto a register
address and encoding. The profile JSON format, the semantics (an omitted name
does not exist) and the shipped devices (the Huawei SUN2000 default, the Deye
hybrids) are documented once in
[profiles/README.md](../profiles/README.md).

`show registers` prints the loaded profile as a table (name, register,
description), `set profile <name|path>` swaps it live, `--profile` /
`PROFILE` pick it at start; `unset profile` returns to the configured
map.

## Served registers (the default profile)

- **32064** / **32080** — PV power / power limit (I32 W)
- **32016+** — the string block: per-string voltage/current (the MPPT
  strings; a dark string serves 0/0)
- **37113** — grid power (I32 W, positive = feed-in)
- **37100+** — smart meter block: status, per-phase voltages/currents (the
  unbalanced home), reactive power, power factor, grid frequency (the
  frequency machine), and 37119 exported / 37121 imported kWh totals that
  grow through the simulated day
- **32089** — device status (512 on-grid / 40960 standby at night)
- **32087** — temperature (I16, °C×10); **32114** daily and **32106** total
  yield (U32, kWh×100)
- **37001+** — battery block when the battery is on (the default; power, SoC, lifetime totals)

All of the above addresses come from the profile — remap them freely. The
profile's per-entry **`fc`** picks each entry's address space: `3` (holding
registers, the default) or `4` (input registers) for the word types, `1`
(coils, the `bit` default) or `2` (discrete inputs) for `bit` entries — the
fake serves the four spaces separately (an entry marked `fc: 4` is not
served on FC3). Bit entries serve `1` when the named value (× `scale`,
rounded) is nonzero. Function codes the fake does not serve get a Modbus
exception; writes stick in overlays: computed registers are recomputed per
poll, overlay values win until cleared (`reset`, SIGUSR1, or shutdown).
The register writes (FC06/FC16) overlay the holding registers; the coil
writes (FC05/FC15) overlay the coil space (FC1) — FC5 demands the
spec values `0x0000`/`0xFF00` (else exception 03). A malformed frame on an
implemented function code — including one too short to carry its address —
is answered with exception 03, never a silent disconnect.

## Internal registers (not in the profile)

**65000–65003** — the modbus-cache diagnostics block (magic `0xCAFE`,
version, uptime, id): always mocked by the fake, never part of the profile —
it exists so the scraper's `scraper_cache_*` auto-detection can be exercised
without a cache. It is also the only address range the fake hardcodes.

## Runtime control

A JSON-lines control server runs **by default on the unix socket
`/tmp/fake-inverter-<modbus-port>.socket`** — short, determinable, one
instance per Modbus port, stale files replaced, unlinked on shutdown, nothing
ever lands in the working directory. Pass a TCP port number to bind
`127.0.0.1:PORT` instead, or `0` to switch the control server off. Both tools
resolve the target the same way: flag > **`CTL`** environment variable >
default socket.

The wire is **JSON lines** (stdlib `json` only): one request object per
line, one reply object per line. The request is `{"cmd": "<command>"}`, the
reply is `{"status": "ok" | "err" | "bye", "text": "<reply text>"}` — a
multi-line reply (`show status`, `show registers`) keeps its newlines inside
`text`, no framing terminator needed. `{"cmd": "ping"}` answers
`{"status": "ok", "text": "pong"}` (the keepalive). **Connections need a
token when `--control-token <secret>` is set**: the first request must be
`{"cmd": "auth", "token": "..."}`. Over the unix socket the kernel vouches
for the peer (`SO_PEERCRED`): root, the daemon's own user and the extra
**`--control-trust-uids`** uids skip the handshake — a local systemd unit
speaks without the secret; TCP peers always need the token. **With a token
configured the wire is signed**: every command and reply carries the full
sha256 HMAC of its payload, keyed by the token (`"mac": …`,
`common/wiresec.py`) — a token-holding client verifies nothing was injected
or altered in flight, and over TCP the signed commands are mandatory (on
the unix socket the mac is verify-if-present, so the trusted peers keep
speaking without the secret). A **second, read-only token**
(`--control-ops-token`) authenticates into the
**`show` verbs only** — no `set`/`unset`, no `reset`, no `shutdown`: the
ops shift against the admin key (the fake has no `clear` verb — watching is
what the ops shift does here). Denied commands answer `err forbidden: the
ops token runs the show/clear verbs only (<verb> needs the admin token)`;
the INV trail's COMMAND entries name the session's role
(`role=ops`/`role=admin`, the denials included), and each session's frames
are mac'd with the key it authenticated with. The clients
take `--control-token`
/ **`CONTROL_TOKEN`** — the value may be a **`file:<path>` reference**
(the first line of a key file or a systemd
`LoadCredential`, owner-only `0600`) — and authenticate automatically (the ops staff pass the
read-only ops token the same way):

> **A token flag lands in `ps`.** Tokens passed as `--control-token <secret>` /
> `--metrics-token <secret>` are visible on the process command line — every
> local user can read them in `ps` output or `/proc/*/cmdline` (the audit's
> F9; the clients included). Prefer the **`file:<path>` reference form** —
> the file must be **owner-only (`0600`)**: group/world-accessible
> token files refuse to start (F12) — or the `CONTROL_TOKEN` env var
> carrying the same `file:` reference.
> The flag form is for quick tests (the fake is a test tool — F11).

| Command | Effect |
|---|---|
| `set <setting> <value>` | configure a setting (below) |
| `unset <setting>` | restore the **configured startup value** of any setting (`unset pv` = auto, `unset time` = the `--time` flag, `unset chaos` = the `--chaos` probability, `unset seed` = back to a random RNG, `unset profile` = the configured map) |
| `show <setting>` | the setting's current value |
| `show knobs` | the dictionary of all knobs: every registry knob under its display group (ungrouped rows bare) — its flag, its env twin(s) when it has one, the command that changes it live (or the restart note) |
| `show status` | the **effective state report**: one stable `key=value` line per field (`pv`, `load`, `grid`, `mppt`, `grid_voltage`, `grid_outage`, `battery`, `soc`, `battery_state`, `cloud`, `clock`, `time_scale`, `uptime`, `clients`, `chaos`, `chaos_hits`, `pinned`, `profile`, `metrics`, `timezone`) — scriptable |
| `show connections` | the fake's live **Modbus** clients: peer, connection age, requests served (`none` when idle) — the cache's `show connections`, pointed at the simulator |
| `inspect` | one pretty dump of everything: the version, the profile, the overlay, the machines' live readings, the pins, the metrics endpoint state — the baton for a bug report |
| `show registers` | the loaded profile's register map, one register per line: `name \| register \| type \| value`, columns aligned; the value = what the registers serve right now, `NaN` = not calculated (e.g. the battery block with the battery off) |
| `show version` | the fake-inverter version (`0.4.0`, or `0.4.0-<short git>` from a checkout) |
| `set scenario <name>` | apply a scenario preset (below) |
| `reset` | clear **all** pinned settings, the Modbus write overlay and the pinned coils/discrete inputs at once (like SIGUSR1, per-connection) |
| `request reload` | **restart the whole fake with the pins kept**: the live overrides save to a state file (the XDG state home — the fake has no config file), the process re-execs with the same argv, the fresh fake re-applies the saved overrides once, then consumes the state file. Overridden secrets save as `*** SECRET REMOVED ***` (the value never lands in the file) — the reply names them |
| `request dump` / `request restore` | with `--dump-path` configured: write the live overrides to the state file (`0600`, integrity-hashed) / load them back (the pins re-apply) — an overridden secret rides as `*** SECRET REMOVED ***`, the restore skips the placeholder and names it; `--dump-key` seals the dump (the state rides encrypted, a restore refuses a wrong or missing key; a dump path without a key warns unsealed at start and on `set`); `--restore-on-start` does the restore automatically at start |
| `shutdown` | gracefully stop the fake inverter (same as SIGTERM: session summary, control socket unlinked) |
| `help` / `help <setting>` | the command reference / one setting's description |
| `quit` | close the connection |

### Settings

| Setting | Values | Meaning |
|---|---|---|
| `pv` | `W` \| `auto` | pin the PV power |
| `load` | `W` \| `auto` | pin the home load |
| `batt` | `W` \| `auto` | pin the battery power, +charge/−discharge (the state machine integrates it into the SoC) |
| `grid` | `W` \| `auto` | pin the **grid setpoint** (+export/−import): the battery balances to hold it (`set grid 0` = zero-export) |
| `grid-voltage` | `120` \| `230` | nominal grid phase voltage (V); the per-phase machine wanders ±10 % around it |
| `grid-frequency` | Hz | nominal grid frequency (Hz); the machine wanders ±0.2 Hz around it |
| `grid-outage` | `on` \| `off` \| `outage` | the grid-outage machine: random blackouts over the simulated clock (the phases collapse, the inverter stands by); `outage` forces one now |
| `soc` | `%` \| `auto` | pin the state of charge (also seeds the machine) |
| `mppt` | `both` \| `east` \| `west` \| `none` | enabled PV strings: string-1 = the east array (the morning peak), string-2 = the west array (the afternoon peak); `both` = the default, `none` = PV 0 |
| `cloud` | `0..1` \| `clear` \| `autumn` \| `spring` \| `winter` | scale the PV: a pinned factor, a clear sky (the default), or a cloud state machine |
| `timezone` | `utc` \| `local` | clock the state machines integrate over: UTC (the default) or the host wall clock |
| `time` | `HH:MM` \| `auto` | freeze / unfreeze the clock — clock jumps integrate the battery and move the clouds (time-lapse) |
| `time-scale` | `N` \| `1` \| `auto` | the time-lapse factor: the simulated clock runs N× real time — the battery, the clouds, the voltages and the day counters all integrate over it (a full simulated day takes 24/N real hours); `auto` = x1 |
| `scenario` | `morning` \| `noon` \| `evening` \| `night` \| `custom` | freeze the clock at a typical moment **and release the value pins** (08:30 / 12:00 / 19:30 / 23:00); manual pins turn it `custom`, `set scenario custom` releases everything again |
| `chaos` | `0..1` \| `off` | tune chaos injection live |
| `seed` | `N` | re-seed the chaos RNG |
| `battery` | `on` \| `off` | toggle the simulated battery (on by default) |
| `battery-state` | `auto` \| `charging` \| `discharging` | force the battery state machine at full power; `auto` lets it decide (the default) |
| `strict` | `on` \| `off` | reject undefined registers with exception 02 |
| `static` | `on` \| `off` | switch static demo values / day simulation |
| `max-kwp` | `kW` | PV array size (peak = 75 % of it) |
| `battery-kwh` | `kWh` | usable battery capacity |
| `max-clients` | `N` (`0` = no limit) | the simultaneous Modbus client limit — refuse further connections past it (`--max-clients`/`FAKE`-flag startup value, tunable live) |
| `client-timeout` | seconds (`0` = never) | disconnect Modbus clients silent for this long — sheds connections from clients that died without closing (`--client-timeout` startup value, tunable live) |
| `max-conn-per-ip` | `N` (`0` = no limit) | the per-peer-IP Modbus connection limit (`--max-conn-per-ip` startup value, tunable live) |
| `connect-acl` | `any` \| `none` \| IP/CIDR list | the Modbus connect ACL (`--connect-acl` startup value, tunable live): who may connect to the Modbus surface at all |
| `write/allow` | `on` \| `off` | the write gate (`--allow-write` startup value, tunable live): whether the fake accepts Modbus writes (FC05/06/15/16) from its clients — off refuses every write with exception 01 |
| `modbus auth` / `modbus auth key` | `suite` \| `none` / key | the auth scheme the fake's Modbus clients must speak (`--auth` startup value, tunable live): `suite` demands the crypt handshake (magic + nonce + HMAC proof of the shared key) right after every connect and drops the client on `ERR`/anything else; `none`/empty = no auth at all — the key is a secret: **`show` refuses it**, `unset` refuses it |
| `metrics-server` | `on`/`off` | the fake's own `/metrics` endpoint (default off; the address is `--metrics-listen`, tunable live); a token-less listen beyond loopback logs a warning |
| `control token` | `<token>` \| `off` | rotate the **admin control token** live (the sessions re-auth); `off` drops the token entirely (the trusted-LAN posture, F11). A secret: **`show` refuses it**, `unset` refuses it — pass it by flag/env, or as `file:<path>` |
| `control ops token` | `<token>` \| `off` | rotate the **read-only ops token** live (must differ from the admin token); `off` signs the ops shift out |
| `metrics token` | `<token>` \| `off` | rotate the **/metrics bearer token** live; `off` serves tokenless (F11) |
| `dump path` / `dump restore-on-start` | `<file>` / `on`\|`off` | the state dump's file (the pins, the machines — the tokens apart) and the restore-on-start mark (prospective: the running session's start already chose) |
| `register` | `addr value` | `set register <addr> <value>` — write a raw register into the **write overlay** (the same store the FC06/FC16 writes use, so the scrapers read it); `reset` clears it, `show registers` marks the rows with `*` |
| `coil` | `addr 0\|1` | `set coil <addr> <0|1>` — pin a coil in the coil space (what FC1 reads and FC5/FC15 write); `reset` clears the pins |
| `discrete` | `addr 0\|1` | `set discrete <addr> <0|1>` — pin a discrete input (what FC2 reads); `reset` clears the pins |
| `profile` | `<file>` | swap the register-map profile live |
| `log-level` | `DEBUG\|INFO\|WARNING\|ERROR` | live log level |

The commands and settings — including their descriptions — live in the one
option registry (`lib/options.json` + its loader `lib/options.py`) that both
the control server and the CLIs read, so the wire grammar, the help texts
and the completions can never drift (the control-only pins and machines ride
the same rows — no flag, just the live name).

### `modbus-fake-ctl` — one-shot / batch client

```bash
python3 inverter/bin/modbus-fake-ctl.py set pv 2500
printf 'set pv 2500\nset soc 30\nshow status\n' | python3 inverter/bin/modbus-fake-ctl.py --control-port 15599
```

Same `--control-port` flag / `CTL` env as the fake itself; several
commands can be passed as arguments or piped on stdin (one reply per line).
Exit codes: `0` = ok, `1` = connection/control error, `2` = CLI misuse.
Every invocation lands in the audit log (below).

### `modbus-fake-cli` — console-style session

An interactive front-end on the same socket (same flag/env resolution): on
the first connect it probes the status and greets you —

```
% Welcome to the Fake Inverter console
%   SUN2000 with optional LUNA2000 battery and meter
%   running for 30 s | utc clock | 230 V grid | battery on
%   TAB completes, ? lists the commands, help <setting> explains one, quit leaves
```

The prompt shows the connected port, `set`/`unset` print only the `% ok`
confirmation, `show <setting>` prints the bare value, and `shutdown` asks
`Proceed with shutdown? [confirm]`
first — RETURN or `y` proceeds, anything else aborts with `% Aborted.`.
While it idles the CLI sends wire pings (every 55 s, `CLI_KEEPALIVE` to
tune, `0` = off) so the control server's idle timeout never drops a live
session. When the connection dies anyway (the fake was killed, the port went
dark), the CLI doesn't fold: it retries **`--reconnect` times (default 3)**
with **`--reconnect-wait` seconds (default 10)** between the attempts,
printing the progress and resuming the session on the first success; every
attempt lands in the audit trail (`RECONNECT`). `--reconnect 0` restores the
old die-on-loss behaviour.

TAB completes commands, settings **and their values**, console-style: the word
is extended silently while the common prefix grows; once exhausted, the
options are listed **one candidate per line with their short descriptions**
from the shared registry. `?` in any position prints the same list without
completing; `help <setting>` shows the description on the wire, too.

```
$ python3 inverter/bin/modbus-fake-cli.py

fake-inverter:5502 > set pv 2500
% ok

fake-inverter:5502 > show soc
auto

fake-inverter:5502 > help soc
soc - pin the state of charge (seeds the machine), or auto (values: %|auto)

fake-inverter:5502 > shutdown
Proceed with shutdown? [confirm] y
% bye shutdown
```

## Chaos injection (`--chaos`)

`--chaos 0.4` (probability, `--seed` for reproducibility) makes the fake
answer a fraction of requests hostile — garbage, short/lying MBAP lengths,
wrong transaction/unit ids, stalls, dropouts, raw exceptions — then drop the
connection. Unlike the regression suites' scripted EvilInverter this runs
unattended: point the scraper at it and watch `scraper_modbus_errors_total`
climb while `scraper_up` flips, with the fake never dying. Tune or disable
live via the control server (`set chaos off`).

## Signals

The fake mirrors the family (`modbus-scraper` / `modbus-cache`):

| Signal | Effect |
|---|---|
| `SIGHUP` | **Re-apply the environment layer** — all-or-nothing (invalid value keeps the previous settings). Flags are startup-only; the env is the reloadable layer. |
| `SIGUSR1` | **Reset the scenario**: all runtime pins, the cloud machine and the Modbus write overlay are dropped, the simulation continues. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown** with a session summary (duration, connections, requests, chaos hits). |

Reloadable environment variables: `CHAOS` (0..1), `MAX_KWP`,
`PROFILE` (register-map profile path), `BATTERY`, `STRICT`,
`TIME` (`HH:MM` or `auto`), `TIME_SCALE` (N× real time),
`LOG_LEVEL` — boolean values accept
`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | bind address |
| `--port` | `5502` | Modbus TCP port |
| `--unit` | `1` | Modbus unit id served |
| `--grid-voltage` | `230` | nominal grid phase voltage (V, 120 or 230); the per-phase machine wanders ±10 % around it |
| `--grid-frequency` | `50` | nominal grid frequency (Hz); the machine wanders ±0.2 Hz around it |
| `--metrics-server` | off | serve the fake's own Prometheus `/metrics` endpoint — **live-settable** (`set metrics-server on/off`; the token-less-beyond-loopback warning holds on both paths) |
| `--metrics-listen` | `127.0.0.1:9452` | the metrics bind address `HOST:PORT` (`0.0.0.0:PORT` serves every interface — mind the values) |
| `--metrics-token` | off | require `Authorization: Bearer <token>` on the metrics endpoint (the same scheme as the scraper's `--auth-token`); the value may be `file:<path>` — the first line of an owner-only `0600` file, F12 |
| `--metrics-max-clients` | `64` | cap concurrent HTTP clients on the metrics endpoint; extras get an immediate `503 # rate limited` (`0` = unlimited) |
| `--metrics-client-timeout` | `5` | seconds an idle metrics client is kept before the socket times out (`0` = the same built-in 5 s cap) |
| `--metrics-max-conn-per-ip` | `0` | cap concurrent metrics connections from one peer IP (`0` = no per-IP limit) |
| `--audit-log` | XDG state | the audit trail: a file path or `-` for stdout (docker logs / journald) |
| `--audit-max-mb` | `10` | rotate the audit log at this size, keeping 3 backups; `0` = off |
| `--audit-daily` | off | also rotate the audit log at UTC midnight |
| `--max-kwp` | `6` | PV array size in kWp, peak = 75 % of it |
| `--max-clients` | `64` | refuse further Modbus connections past this many simultaneous clients (`0` = no limit) |
| `--client-timeout` | `300` | disconnect Modbus clients silent for this many seconds (`0` = never) — sheds connections from clients that died without closing |
| `--max-conn-per-ip` | `0` | refuse further Modbus connections from one peer IP past this many simultaneous connections (`0` = no per-IP limit) |
| `--connect-acl` | any | the Modbus clients allowed to connect (the cache's `connect-acl`, mirrored): `"any"` (the default — the trusted-LAN posture), `"none"`, or a comma-separated list of IPs and CIDR prefixes, e.g. `127.0.0.1,10.48.0.0/16` (env `CONNECT_ACL`; live-settable, `show status` carries `connect_acl=`) |
| `--allow-write` | off | accept Modbus writes (FC05/06/15/16) from the fake's clients: a write lands in the write overlay, logged and audited `WRITE` like the cache's forwarded ones; off (the default) = every write is refused with exception 01 and audited `WRITE-REFUSED` — the cache's write gate, mirrored (env `ALLOW_WRITE`; live-settable, `set write allow`) |
| `--auth` | `none` | the auth scheme the fake's Modbus clients must speak: `suite` demands the crypt handshake (magic + nonce + HMAC proof of the shared key) right after every connect — the fake answers `OK` and the session speaks plain Modbus, or `ERR` and the client is dropped before it ever sees a register; `none`/empty = no auth at all (env `AUTH`; live-settable, `set modbus auth`) — see the fake's settings table |
| `--auth-key` | none | the shared key the fake's clients prove with the suite handshake, **min 16 characters**; the value may be `file:<path>` — the first line of an owner-only `0600` file (env `AUTH_KEY`); the scraper takes the matching `--auth suite --auth-key …` |
| `--timezone` | `utc` | clock the state machines integrate over (`utc` or `local`) |
| `--time` | real clock | freeze simulated time `HH:MM` (zone-independent) |
| `--time-scale` | `1` | the simulated clock speed: N× real time — a full simulated day takes 24/N real hours (`set time-scale` tunes it live) |
| `--static` | off | constant demo values instead of the day simulation |
| `--battery` | on | simulate a battery (the battery state machine runs; on by default) |
| `--no-battery` | | no battery values |
| `--battery-kwh` | `6.9` | usable battery capacity in kWh |
| `--profile` | `sun2000` | register-map profile: the built-in name or a JSON path (name → register + optional type/scale); `PROFILE` when unset |
| `--strict` | off | reject undefined registers with exception 02 |
| `--control-port` | `/tmp/fake-inverter-<port>.socket` | control server target (unix socket or TCP port), `0` = off |
| `--control-token` | off | require the token auth handshake on control connections (the clients take `--control-token` / `CONTROL_TOKEN`; the value may be `file:<path>` — the first line of an owner-only `0600` file, F12) |
| `--control-ops-token` | off | a second, **read-only** control token: its sessions run the `show` verbs only (no `set`/`unset`, no `reset`, no `shutdown`) — needs `--control-token`, must differ from it; both roles audited (`CONTROL_OPS_TOKEN`) |
| `--control-ops-verbs` | `show,clear` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated, validated against the control grammar at start (`CONTROL_OPS_VERBS`) |
| `--control-trust-uids` | none | extra peer uids the unix control socket trusts without the token (`SO_PEERCRED`): comma-separated — root and the daemon's own user are always trusted (env `CONTROL_TRUST_UIDS`) |
| `--control-socket-group` | off | leave the unix control socket group-accessible (`chmod 0660` instead of the default `0600`): a local group may speak to the control without being the service user |
| `--control-log-replies` | off | DEBUG-log the full output of every control command, not just the command |
| `--dump-path` | off | the state dump (write-behind): the live setting overrides — the pins, the machines, the tokens apart — as one JSON, created `0600` with an integrity hash, written on the `request dump` command and the graceful shutdown; loaded on start only with `--restore-on-start`, on demand with the `request restore` command (env `DUMP_PATH`) |
| `--dump-key` | off | the key that **seals** the state dumps and the reload's state file: the state rides encrypted (an HMAC-SHA256 counter-mode keystream, authenticated — a restore refuses a wrong or missing key, and a configured key refuses an unsealed dump); startup-only — the reload re-exec re-resolves the same key (env `DUMP_KEY`); the value may be `file:<path>` — the first line of an owner-only 0600 file (the same `file:` form works on every secret value — `--control-token file:/path`, `--metrics-token file:/path`) |
| `--restore-on-start` | off | load the state dump when the fake starts (needs `--dump-path`) — the live overrides ride again instead of a cold start (env `RESTORE_ON_START`) |
| `--chaos` | `0` | probability 0..1 that a request is answered hostile and dropped |
| `--seed` | random | chaos/cloud RNG seed for reproducible runs |
| `--dry-run` | off | validate the configuration, print the effective settings and exit (`0` = valid, `1` = invalid, `2` = CLI misuse) |
| `--log-level` | `INFO` | `DEBUG` adds per-client traffic and per-poll detail |
| `--man` | off | print the generated man page (roff) to stdout and exit (`modbus-fake-inverter --man \| man -l -`); the shipped pages are the same generator's output |

## Docker

The fake ships as an alpine container — stdlib-only, no pip, running as
the unprivileged `pvsuite` user with the tools on `PATH`. Build + run
(`Dockerfile.fake-inverter` + `compose.yaml`; the shared
[`profiles/`](../profiles/README.md) directory is copied in):
[`docker/README.md`](../docker/README.md).

The version reports as `0.4.0` inside the image (no git metadata; a
checkout shows `0.4.0-<short git>`).

### Audit trail

The fake itself and both clients append to the **audit log** — on by
default everywhere, at the **XDG state home**
(`~/.local/state/fake-inverter/audit.log`, NOT the working directory: a
packaged install has a read-only one). `--audit-log <file>` renames it,
`--no-audit-log` turns it off. **`--audit-log -` sends the trail to
stdout, not stderr** — the audit is data, not an error, and stdout keeps it
in the single ordered stream the service manager captures (docker logs,
journald); the shipped Dockerfile runs with it. `--audit-files N` (the
default 3) sets how many rotated backups the file sink keeps; the stdout
sink never rotates. If the audit file
cannot be opened, the trail falls back to stdout rather than vanishing. **Rotation is gated**: `--audit-max-mb 10`
(the default) rotates at 10 MB keeping 3 backups (`audit.log.1..3`),
`--audit-daily` additionally rotates at UTC midnight, `--audit-max-mb 0`
= unbounded. One line per event; the prefix names the writer — `INV`
(the fake), `CLI` (modbus-fake-cli), `CTL` (modbus-fake-ctl):

```
2026-11-03T20:10:06Z INV START 3f9a21c04de7 version=0.4.0 modbus=127.0.0.1:5502 control=127.0.0.1:15991 profile=sun2000: ...
2026-11-03T20:10:07Z AUDIT INV COMMAND 9c41e2b7a058 peer=127.0.0.1:54425 'set soc 40' -> ok
2026-11-03T20:10:07Z AUDIT INV COMMAND 3d82f6c05e19 peer=127.0.0.1:54426 role=ops 'show status' wire=h4b91de207a86 -> ok
2026-11-03T20:10:08Z INV RESET 77b0c4e19d23 SIGUSR1: 1 pin(s), 0 overlay register(s) cleared
2026-11-03T20:10:08Z INV SHUTDOWN 5e2af8c30b61 SIGTERM: uptime=2s conns=0 requests=0 chaos_hits=0
2026-11-03T18:44:10Z CLI CONNECT a01f65c3924b target=127.0.0.1:15731 user=oom
2026-11-03T18:44:10Z AUDIT CLI COMMAND c8812a4f0d37 'quit' -> local
2026-11-03T18:44:10Z CLI DISCONNECT 22b7d90e5f14 target=127.0.0.1:15731
```

The 12-hex token after the event name is the entry's **chained hash** (the
audit's F10): each entry hashes the writer's previous entry into its own —
any edit, deletion or reordering in the middle of a prefix's trail shows up
as a chain break in `scripts/audit_verify.py` (run it on this file, the
family's XDG trails, or a journald dump on stdin).

UTC stamps, the command as entered and its outcome (`ok` / `err`) — the
structured who-when-what evidence trail. **Every wire command is
audited once, by the server** (`AUDIT INV COMMAND`, with the client peer — it
knows the who, and the role — the ops shift against the admin key — plus
the frame's mac when the wire is signed; the denied ops attempts are in the
trail too); the clients audit their session (the CONNECT/the
DISCONNECT) and the local-only events (`quit`, an aborted `shutdown`).
The fake logs its lifecycle too: `START`, `RELOAD` (SIGHUP), `RESET`
(SIGUSR1) and `SHUTDOWN` (a restart = the SHUTDOWN + the next START).
ping/pong keepalives are never logged; the file is flushed per event, so
a crash keeps everything up to the last command.

The operational log (stdout — journald/docker capture it) keeps mirroring
the commands at the INFO level; the audit file is the structured evidence
trail, not a duplicate of it.

## Security

Honest scope of a demo device:

> **The fake is a development tool — run it on a trusted, LAN-isolated
> network.** It is deliberately *not* security-first design: the Modbus
> surface speaks to any peer that can reach the port (no TLS, no ACL — that
> is what the real device's network isolation is for; the optional
> `--auth suite` shared-key handshake authenticates clients when a demo
> wants it), and its
> Prometheus `/metrics` serves without a token unless `--metrics-token` is
> set. The audit (F11) accepts exactly this for a test instrument and asks
> for the blunt mitigations only: **`--max-clients` / `--client-timeout`**
> cap runaway connections (both tunable live via the control server,
> `show connections` watches them), the read-count gate keeps a malformed
> frame from making the fake assemble an oversized reply, and the
> documentation says the quiet part out loud — keep the fake on the demo
> LAN, next to the tools it is meant to serve.

- **Minimal supply chain.** Every tool is Python standard library only — the
  SBOM is two lines (python + alpine in the container). No pip, no vendored
  code, nothing to audit beyond the stdlib.
- **The control surface is plain-text by design** — a demo harness: the TCP
  control server binds `127.0.0.1` only, and `--control-token` adds a
  token-auth handshake (the clients authenticate with
  `CONTROL_TOKEN` / `--control-token`, the value a bare token or a
  `file:<path>` reference — the first line of a key file or a
  `LoadCredential`, owner-only `0600`); over the unix
  socket a kernel-vouched peer (root, the daemon's own user or
  `--control-trust-uids` — `SO_PEERCRED`) skips the token. The container
  runs as the unprivileged `pvsuite` user. Do not expose the control port
  to untrusted networks.
- **Auditable by default.** The fake and the CLIs keep the append-only
  audit trail above (who, when, what, result) — the logging evidence on
  unless explicitly disabled.
- **Synthetic data only.** Nothing served is measured from a real device;
  there is no PII and no production telemetry to protect.

## Nix

```bash
nix run .#modbus-fake-inverter -- --static --control-port 15599
```

The flake exposes the package with three binaries (`modbus-fake-inverter`,
`modbus-fake-ctl`, `modbus-fake-cli`) and their man pages
(`man/modbus-fake-inverter.1`, `-ctl.1`, `-cli.1` under
`share/man/man1/`); there is no NixOS service module — the
fake is a test/demo tool, not a daemon you deploy.

## Source layout

```
inverter/bin/
├── modbus-fake-inverter.py    # CLI entry, logging, wiring
├── modbus-fake-ctl.py         # control-server CLI client (one-shot / batch)
├── modbus-fake-cli.py         # console-style interactive control session
└── lib/
    ├── options.json    # the knob registry: the flags, the env twins, the live settings + their control vocabulary
    ├── options.py      # its loader: the Option rows, the control-grammar vocabulary, the wiring
    ├── profile.py      # register-map profiles: name registry, encoding, loading
    ├── simulator.py    # day curves, runtime overrides, named values, cloud machines
    ├── battery.py      # the battery state machine (SoC state, decision, integration)
    ├── inverter.py     # Modbus TCP server: FC1-FC4 reads, FC05/06/15/16 writes behind the write gate, strict mode, chaos
    ├── control.py      # JSON-lines control server (set/unset/show, scenarios)
    ├── metrics.py      # the fake's own Prometheus /metrics endpoint
    ├── audit.py        # the append-only audit trail (AUDIT INV/CLI/CTL lines)
    ├── chaos.py        # seeded hostile-reply dice layer
    ├── signals.py      # SIGHUP/SIGUSR1/SIGTERM handling
    ├── statics.py      # static configuration loader (lib/static.json)
    ├── static.json     # the statics: solar times, cloud machines, battery limits
    └── paths.py        # default control-socket path
```

## License

The fake inverter (source, Nix packaging) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
