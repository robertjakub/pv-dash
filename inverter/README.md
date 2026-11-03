# Fake Huawei SUN2000 inverter

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) Modbus TCP server that plays a Huawei
SUN2000 inverter — with a LUNA2000 battery, a smart meter and the
modbus-cache diagnostics block — so the
[modbus-scraper](../scrape/README.md), the
[modbus-cache](../cache/README.md) and the whole
[pv-suite](../README.md) stack can be exercised without hardware.

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
python3 inverter/src/fake_inverter.py --static              # constant PV 4000 W, grid -1500 W
python3 inverter/src/fake_inverter.py --static --battery    # the same, charging 1200 W at 65 %
python3 inverter/src/fake_inverter.py --port 15502 --log-level DEBUG
```

## Simulation

By default it simulates a sunny day: bell-curve PV between 06:00 and 18:00
(peak 75 % of `--max-kwp`), home load with morning and evening peaks — so the
grid exports around noon and imports in the mornings/evenings. Panel
temperature follows the ambient curve + sun heating. Energy counters grow
during the simulated day. Raw wire values are watts / kWh×100 like the real
map.

The battery in the day simulation is **not a fixed value**: with `--battery`
the LUNA2000 runs the state machine described below. The familiar fixed
1200 W at 65 % SoC belongs exclusively to `--static` mode, where the classic
demo values replace the day simulation (PV 4000 W, home 4300 W, grid
−1500 W; static battery: charging 1200 W at 65 %).

### Battery state machine (day simulation)

- charges from the PV surplus, keeping a 300 W grid margin (max ±2500 W)
- covers the home deficit by discharging (150 W standby excluded)
- stops at the bounds: 100 % full, 10 % reserve floor

The SoC is **stateful**: it integrates the effective battery power with the
simulated clock. Moving the clock (`set time 18:00`) therefore acts as a
time-lapse control; a full battery holds the surplus for the grid; a drained
one lets the grid cover the home. `set soc <pct>` seeds the machine (unpinning
resumes from there); `reset` re-seeds the SoC from the simulated day.

### Cloud machines (`set cloud autumn|winter`)

Besides a pinned factor (`set cloud 0.7`) and a clear sky (`auto`), the cloud
cover can be a small state machine — a mean-reverting random walk over the
simulated clock:

| Mode | Character |
|---|---|
| `autumn` | passing clouds, quick swings (factor mostly 0.05–0.95 around a 0.45 mean) |
| `winter` | heavy overcast spells, slow breaks (mostly 0.10–1.00 around a 0.75 mean) |

Like the battery, the machine integrates with the simulated clock: clock
jumps move the clouds (time-lapse), a frozen clock freezes them. `reset`
returns to a clear sky.

### Register-map profiles

The fake doesn't hardcode the SUN2000 layout: the simulator computes **named
physical values** (`pv-power`, `device-temperature`, `grid-power`,
`battery-soc`, …) and a **profile** maps each name onto a register address
and encoding. The shipped default `src/profiles/sun2000.json` (description
"SUN2000 with optional LUNA2000 battery and meter") reproduces the classic
layout byte for byte.

A custom profile reuses the names on different registers to emulate a
different inverter/battery/meter — optional per-entry `type`
(`i16/u16/i32/u32`) and `scale` override the encoding:

```json
{
  "description": "SUN2000 with optional LUNA2000 battery and meter",
  "registers": [
    {"name": "pv-power", "register": 32064, "type": "i32", "scale": 1,
     "desc": "PV power, all strings (W)"},
    {"name": "device-temperature", "register": 32087, "type": "i16",
     "scale": 10, "desc": "device temperature (C x10)"}
  ]
}
```

Every fact about an entry lives in the JSON (register, type, scale, desc) —
no hardcoded tables.

**A name left out of the profile does not exist on this device**: the fake
serves it like any unknown register — reads as 0, or exception 02 in strict
mode. A device that doesn't expose, say, `string-1-voltage` (a Fibaro-style
setup without per-string data) simply omits it — the same applies to a
profile name the fake cannot simulate. Overlapping registers and unreadable
files fail with a clean one-line error. The 65000-65003 diagnostics block is
**not part of any profile** (it is not a device register): it is internal to
the cache/scraper discovery (the 0xCAFE magic), and the fake always mocks
it.

The profile carries a `description` (shown in the logs, the dry-run and
`show profile`), a `desc` per entry (what the value means) and a
**`mappings`** list for coded registers —
`[{"register": "device-status", "values": {"512": "on-grid", "40960": "standby"}}, ...]` —
the REAL device's codes (the sun2000: 512 = on-grid / 40960 = standby; the
Deye: 1 = self-checking / 2 = normal / 3 = fault), and the fake serves the
codes from it — a hybrid without a confirmed standby code stays `normal`
around the clock; the consumers
select what to fetch/scrape from the same file via their own configs (the
cache's selection list, the scraper's metrics spec). Four profiles ship in the suite's [`profiles/`](../profiles/) subproject:
**`sun2000`** (the classic layout), **`deye-sg03lp1`** (a Deye SUN
single-phase hybrid — real Deye addresses, SoC as plain percent, no
`pv-limit`/`meter` registers it doesn't have), **`deye-sg04lp3`** and
**`deye-sg05lp3`** (Deye SUN three-phase hybrids — the 6xx register block,
three grid phases, daily/total battery counters). The `device-status`
entries carry their value map in the `desc` (e.g. sun2000: 512 = on-grid,
40960 = standby). Every profile there is addressable by name:
`--profile sun2000`, `FAKE_PROFILE=deye-sg03lp1`, `set profile
deye-sg05lp3`; any other value is a JSON path. Swap live via the control server (`set profile
my-device.json`), restore the configured one with `unset profile`; `show
profile` reports the active map's description and name/path.

## Served registers (the default profile)

- **32064** / **32080** — PV power / power limit (I32 W)
- **37113** — grid power (I32 W, positive = feed-in)
- **37100+** — smart meter block: status, per-phase voltages/currents,
  reactive power, power factor, grid frequency, and 37119 exported /
  37121 imported kWh totals that grow through the simulated day
- **32089** — device status (512 on-grid / 40960 standby at night)
- **32087** — temperature (I16, °C×10); **32114** daily and **32106** total
  yield (U32, kWh×100)
- **37001+** — battery block when `--battery` (power, SoC, lifetime totals)
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
| `status` | one-line **effective** state (what the registers serve right now + what is pinned) |
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
| `cloud` | `0..1` \| `auto` \| `autumn` \| `winter` | scale the PV: a pinned factor, a clear sky, or a cloud state machine |
| `time` | `HH:MM` \| `auto` | freeze / unfreeze the clock — clock jumps integrate the battery and move the clouds (time-lapse) |
| `scenario` | `morning` \| `noon` \| `evening` \| `night` \| `custom` | freeze the clock at a typical moment **and release the value pins** (08:30 / 12:00 / 19:30 / 23:00); manual pins turn it `custom`, `set scenario custom` releases everything again |
| `chaos` | `0..1` \| `off` | tune chaos injection live |
| `seed` | `N` | re-seed the chaos RNG |
| `battery` | `on` \| `off` | toggle the simulated LUNA2000 |
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
printf 'set pv 2500\nset soc 30\nstatus\n' | python3 inverter/src/fake_ctl.py --control-port 15599
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
| `--battery` | off | simulate a LUNA2000 battery |
| `--battery-kwh` | `6.9` | usable battery capacity in kWh |
| `--profile` | `sun2000` | register-map profile: the built-in name or a JSON path (name → register + optional type/scale); `FAKE_PROFILE` when unset |
| `--strict` | off | reject undefined registers with exception 02 |
| `--control-port` | `/tmp/fake-inverter-<port>.socket` | control server target (unix socket or TCP port), `0` = off |
| `--chaos` | `0` | probability 0..1 that a request is answered hostile and dropped |
| `--seed` | random | chaos/cloud RNG seed for reproducible runs |
| `--dry-run` | off | validate the configuration, print the effective settings and exit (`0` = valid, `1` = invalid, `2` = CLI misuse) |
| `--log-level` | `INFO` | `DEBUG` adds per-client traffic and per-poll detail |

## Nix

```bash
nix run .#modbus-fake-inverter -- --static --battery --control-port 15599
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
