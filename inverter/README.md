# Fake Inverter Simulator

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) Modbus TCP server that plays an
inverter — with a battery, a smart meter and the modbus-cache diagnostics
block — so the [modbus-scraper](../scrape/README.md), the
[modbus-cache](../cache/README.md) and the whole [pv-suite](../README.md)
stack can be exercised without hardware.

Through **inverter profiles** it can emulate different devices: the shipped
default profile is the Huawei SUN2000 map, and Deye hybrid profiles are
included as well — see [profiles/README.md](../profiles/README.md).

It ships three tools:

| Tool | Purpose |
|---|---|
| `fake_inverter.py` | the server (also packaged as `modbus-fake-inverter`) |
| `fake_ctl.py` | one-shot / batch client for the runtime control server (`modbus-fake-ctl`) |
| `fake_cli.py` | console-style interactive session on the same control server (`modbus-fake-cli`) |

## Quick start

```bash
python3 inverter/src/fake_inverter.py                       # 127.0.0.1:5502 — scraper defaults just work
python3 inverter/src/fake_inverter.py --time 12:00          # frozen noon: ~4.5 kW PV, exporting
python3 inverter/src/fake_inverter.py --static              # constant PV 4000 W, grid -1500 W, battery charging 1200 W at 65 %
python3 inverter/src/fake_inverter.py --port 15502 --log-level DEBUG
```

## Simulation

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

### The three state machines

**PV (the sun).** A sine bell between 06:00 and 18:00, peaking at 75 % of
`--max-kwp`; night = 0 W. The cloud factor scales it in real time, so the
cloud machine modulates the sun itself.

**Battery.** The battery state machine (day simulation, battery on — the
default; `--no-battery` opts out):

- charges from the PV surplus, keeping a 300 W grid margin (max ±2500 W)
- covers the home deficit by discharging (150 W standby excluded)
- stops at the bounds: 100 % full, 10 % reserve floor

The SoC is **stateful**: it integrates the effective battery power with the
simulated clock. Moving the clock (`set time 18:00`) therefore acts as a
time-lapse control; a full battery holds the surplus for the grid; a drained
one lets the grid cover the home. `set soc <pct>` seeds the machine (unpinning
resumes from there); `reset` re-seeds the SoC from the simulated day.
`set battery-state charging|discharging` forces the machine to full charge or
discharge power regardless of the surplus (the SoC bounds still hold); `auto`
(or `unset battery-state`) hands the decision back to the machine.

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
`FAKE_PROFILE` pick it at start; `unset profile` returns to the configured
map.

## Served registers (the default profile)

- **32064** / **32080** — PV power / power limit (I32 W)
- **37113** — grid power (I32 W, positive = feed-in)
- **37100+** — smart meter block: status, per-phase voltages/currents,
  reactive power, power factor, grid frequency, and 37119 exported /
  37121 imported kWh totals that grow through the simulated day
- **32089** — device status (512 on-grid / 40960 standby at night)
- **32087** — temperature (I16, °C×10); **32114** daily and **32106** total
  yield (U32, kWh×100)
- **37001+** — battery block when the battery is on (the default; power, SoC, lifetime totals)
- **65000–65003** — modbus-cache diagnostics block (magic `0xCAFE`, always
  mocked — not in the profile), so the scraper's `huawei_cache_*`
  auto-detection can be exercised without a cache

All of the above addresses come from the profile — remap them freely. Other
function codes get a Modbus exception; writes (FC06/FC16) stick in an
overlay: computed registers are recomputed per poll, overlay values win
until cleared (`reset`, SIGUSR1 or shutdown).

## Runtime control

A line-protocol control server runs **by default on the unix socket
`/tmp/fake-inverter-<modbus-port>.socket`** — short, determinable, one
instance per Modbus port, stale files replaced, unlinked on shutdown, nothing
ever lands in the working directory. Pass a TCP port number to bind
`127.0.0.1:PORT` instead, or `0` to switch the control server off. Both tools
resolve the target the same way: flag > **`FAKE_CTL`** environment variable >
default socket.

One command per line, one reply per line (`ok …` / `err …` / `bye …`):

| Command | Effect |
|---|---|
| `set <setting> <value>` | configure a setting (below) |
| `unset <setting>` | restore the **configured startup value** of any setting (`unset pv` = auto, `unset time` = the `--time` flag, `unset chaos` = the `--chaos` probability, `unset seed` = back to a random RNG, `unset profile` = the configured map) |
| `show <setting>` | the setting's current value |
| `show settings` | every setting and its value |
| `show status` | one-line **effective** state (what the registers serve right now + what is pinned) |
| `show registers` | the loaded profile's register map, one register per line: `name \| register \| type`, columns aligned |
| `show version` | the fake-inverter version (`0.2.0`, or `0.2.0-<short git>` from a checkout) |
| `set scenario <name>` | apply a scenario preset (below) |
| `reset` | clear **all** pinned settings and the Modbus write overlay at once (like SIGUSR1, per-connection) |
| `shutdown` | gracefully stop the fake inverter (same as SIGTERM: session summary, control socket unlinked) |
| `help` / `help <setting>` | the command reference / one setting's description |
| `quit` | close the connection |

### Settings

| Setting | Values | Meaning |
|---|---|---|
| `pv` | `W` \| `auto` | pin the PV power |
| `load` | `W` \| `auto` | pin the home load |
| `batt` | `W` \| `auto` | pin the battery power, +charge/−discharge (the state machine integrates it into the SoC) |
| `soc` | `%` \| `auto` | pin the state of charge (also seeds the machine) |
| `cloud` | `0..1` \| `clear` \| `autumn` \| `spring` \| `winter` | scale the PV: a pinned factor, a clear sky (the default), or a cloud state machine |
| `time` | `HH:MM` \| `auto` | freeze / unfreeze the clock — clock jumps integrate the battery and move the clouds (time-lapse) |
| `scenario` | `morning` \| `noon` \| `evening` \| `night` \| `custom` | freeze the clock at a typical moment **and release the value pins** (08:30 / 12:00 / 19:30 / 23:00); manual pins turn it `custom`, `set scenario custom` releases everything again |
| `chaos` | `0..1` \| `off` | tune chaos injection live |
| `seed` | `N` | re-seed the chaos RNG |
| `battery` | `on` \| `off` | toggle the simulated battery (on by default) |
| `battery-state` | `auto` \| `charging` \| `discharging` | force the battery state machine at full power; `auto` lets it decide (the default) |
| `strict` | `on` \| `off` | reject undefined registers with exception 02 |
| `static` | `on` \| `off` | switch static demo values / day simulation |
| `max-kwp` | `kW` | PV array size (peak = 75 % of it) |
| `battery-kwh` | `kWh` | usable battery capacity |
| `profile` | `<file>` | swap the register-map profile live |
| `log-level` | `DEBUG\|INFO\|WARNING\|ERROR` | live log level |

The commands and settings — including their descriptions — live in one shared
registry (`src/lib/settings.py`) that both the control server and the CLIs
read, so the wire grammar, the help texts and the completions can never drift.

### `fake_ctl` — one-shot / batch client

```bash
python3 inverter/src/fake_ctl.py set pv 2500
python3 inverter/src/fake_ctl.py show settings
printf 'set pv 2500\nset soc 30\nshow status\n' | python3 inverter/src/fake_ctl.py --control-port 15599
```

Same `--control-port` flag / `FAKE_CTL` env as the fake itself; several
commands can be passed as arguments or piped on stdin (one reply per line).
Exit codes: `0` = ok, `1` = connection/control error, `2` = CLI misuse.

### `fake_cli` — console-style session

An interactive front-end on the same socket (same flag/env resolution): the
prompt shows the connected port, `set`/`unset` print only the `ok`
confirmation, `show <setting>` prints the bare value, `show settings` prints
one setting per line, and `shutdown` asks `Proceed with shutdown? [confirm]`
first — RETURN or `y` proceeds, anything else aborts with `% Aborted.`.
While it idles the CLI sends wire pings (every 55 s, `FAKE_CLI_KEEPALIVE` to
tune, `0` = off) so the control server's idle timeout never drops a live
session.

TAB completes commands, settings **and their values**, console-style: the word
is extended silently while the common prefix grows; once exhausted, the
options are listed **one candidate per line with their short descriptions**
from the shared registry. `?` in any position prints the same list without
completing; `help <setting>` shows the description on the wire, too.

```
$ python3 inverter/src/fake_cli.py

fake-inverter:5502 > set pv 2500
ok

fake-inverter:5502 > show soc
auto

fake-inverter:5502 > help soc
ok soc - pin the state of charge (seeds the machine), or auto (values: %|auto)

fake-inverter:5502 > shutdown
Proceed with shutdown? [confirm] y
bye shutdown
```

## Chaos injection (`--chaos`)

`--chaos 0.4` (probability, `--seed` for reproducibility) makes the fake
answer a fraction of requests hostile — garbage, short/lying MBAP lengths,
wrong transaction/unit ids, stalls, dropouts, raw exceptions — then drop the
connection. Unlike the regression suites' scripted EvilInverter this runs
unattended: point the scraper at it and watch `huawei_modbus_errors_total`
climb while `huawei_up` flips, with the fake never dying. Tune or disable
live via the control server (`set chaos off`).

## Signals

The fake mirrors the family (`modbus-scraper` / `modbus-cache`):

| Signal | Effect |
|---|---|
| `SIGHUP` | **Re-apply the `FAKE_*` environment layer** — all-or-nothing (invalid value keeps the previous settings). Flags are startup-only; the env is the reloadable layer. |
| `SIGUSR1` | **Reset the scenario**: all runtime pins, the cloud machine and the Modbus write overlay are dropped, the simulation continues. |
| `SIGTERM` / `SIGINT` | **Graceful shutdown** with a session summary (duration, connections, requests, chaos hits). |

Reloadable environment variables: `FAKE_CHAOS` (0..1), `FAKE_MAX_KWP`,
`FAKE_PROFILE` (register-map profile path), `FAKE_BATTERY`, `FAKE_STRICT`,
`FAKE_TIME` (`HH:MM` or `auto`), `FAKE_LOG_LEVEL` — boolean values accept
`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | bind address |
| `--port` | `5502` | Modbus TCP port |
| `--unit` | `1` | Modbus unit id served |
| `--max-kwp` | `6` | PV array size in kWp, peak = 75 % of it |
| `--time` | real clock | freeze simulated time `HH:MM` |
| `--static` | off | constant demo values instead of the day simulation |
| `--battery` | on | simulate a battery (the battery state machine runs; on by default) |
| `--no-battery` | | no battery values |
| `--battery-kwh` | `6.9` | usable battery capacity in kWh |
| `--profile` | `sun2000` | register-map profile: the built-in name or a JSON path (name → register + optional type/scale); `FAKE_PROFILE` when unset |
| `--strict` | off | reject undefined registers with exception 02 |
| `--control-port` | `/tmp/fake-inverter-<port>.socket` | control server target (unix socket or TCP port), `0` = off |
| `--control-log-replies` | off | DEBUG-log the full output of every control command, not just the command |
| `--chaos` | `0` | probability 0..1 that a request is answered hostile and dropped |
| `--seed` | random | chaos/cloud RNG seed for reproducible runs |
| `--dry-run` | off | validate the configuration, print the effective settings and exit (`0` = valid, `1` = invalid, `2` = CLI misuse) |
| `--log-level` | `INFO` | `DEBUG` adds per-client traffic and per-poll detail |

## Docker

The fake ships as an alpine container — stdlib-only, no pip, running as
the unprivileged `pvsuite` user with the tools on `PATH`. The files live
in [`docker/`](../docker/) (`Dockerfile.inverter` + `compose.yaml`; the
shared [`profiles/`](../profiles/README.md) directory is copied in):

```bash
cd docker
docker compose up -d fake-inverter              # build + serve on 0.0.0.0:5502
docker compose exec fake-inverter fake-cli      # console session on the control server
docker compose down
```

The version reports as `0.2.0` inside the image (no git metadata; a
checkout shows `0.2.0-<short git>`).

## Nix

```bash
nix run .#modbus-fake-inverter -- --static --control-port 15599
```

The flake exposes the package with three binaries (`modbus-fake-inverter`,
`modbus-fake-ctl`, `modbus-fake-cli`); there is no NixOS service module — the
fake is a test/demo tool, not a daemon you deploy.

## Source layout

```
inverter/src/
├── fake_inverter.py    # CLI entry, logging, wiring
├── fake_ctl.py         # control-server CLI client (one-shot / batch)
├── fake_cli.py         # console-style interactive control session
└── lib/
    ├── settings.py     # shared command/setting registry (grammar + descriptions)
    ├── profile.py      # register-map profiles: name registry, encoding, loading
    ├── simulator.py    # day curves, runtime overrides, named values, cloud machines
    ├── battery.py      # the battery state machine (SoC state, decision, integration)
    ├── inverter.py     # Modbus TCP server: FC3/FC06/FC16, strict mode, chaos
    ├── control.py      # line-protocol control server (set/unset/show, scenarios)
    ├── protocol.py     # wire helpers (recv_exact)
    ├── chaos.py        # seeded hostile-reply dice layer
    ├── signals.py      # SIGHUP/SIGUSR1/SIGTERM handling
    └── paths.py        # default control-socket path
```

## License

The fake inverter (source, Nix packaging) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
