# modbus-fake-inverter

> **Experimental — work in progress.**

`modbus-fake-inverter` is a dependency-free (Python standard library only)
Modbus TCP server that plays an inverter — with a battery, a smart meter
and the modbus-cache diagnostics block — so the `modbus-scraper`, the
`modbus-cache` and the whole pv-suite stack can be exercised without
hardware. Through **inverter profiles** it emulates different devices: the
shipped default profile is the `sun2000` (Huawei SUN2000) map, and Deye
hybrid profiles are included as well. The companion `modbus-fake-cli` is
the console client for the fake's control wire.

It simulates a sunny day: a double-shouldered PV curve over two MPPT
strings (east/west), a home load with morning and evening peaks, a battery
state machine, wandering grid voltages and frequency, a cloud layer and a
grid-outage machine that drops the grid at random. Every machine
integrates over a simulated clock — UTC by default, freezable and
scalable, so a full simulated day can pass in minutes. `--static` replaces
the day with constant demo values; `--chaos` answers a fraction of
requests hostile to test error paths.

The tool is one file, `apps/inverter/bin/modbus-fake-inverter.py`, run
with `python3`. The startup surface is the family's: flags, bare
environment twins and a set-grammar config file, resolving flag > env >
config > built-in default. At runtime the scenario is driven over a JSON
control socket — pin the PV, the load, the battery, the SoC, the clouds,
inject chaos — and `SIGHUP` re-applies the environment layer.

## The family

```text
   the device (hardware, or the fake)  --Modbus TCP-->  modbus-cache :15502
                                                            |
                                                            v
                                                    modbus-scraper :9350
                                                            |
                                                            v
                                                      prometheus --> dashboard

   modbus-fake-inverter :5502   (this tool — stands in for the device)
   modbus-replay                (the recorded-traffic sibling, beside it)
```

The fake sits at the device-shaped end of the ladder: it answers Modbus
TCP the way a SUN2000-class inverter does, so the cache's upstream, the
scraper's poll and the whole metrics chain have something real-shaped to
talk to. Every hop is optional — the fake alone with its `modbus-fake-cli`
console is a complete test bench, and the fake is also the device under
every other tool's regression suite in CI and development.

## How it works

A simulator computes named physical values (PV power, battery SoC, grid
voltages, device status, ...); a device profile maps each name onto a wire
address and an encoding; the Modbus server serves the assembled map. The
pieces, each in its own module under `apps/inverter/lib/`:

- **The day simulator** — the PV bell over two MPPT strings, the
  home-load curve, the cloud machines (`autumn` quick swings, `spring`
  fair-weather cumulus, `winter` heavy overcast), the grid voltage and
  frequency wanderers, and the grid-outage machine (a two-state Markov
  chain over the simulated clock). Scaling time moves every machine at
  once.
- **The battery machine** — charges the PV surplus while keeping a grid
  margin, covers the home deficit from storage: 95 % charge efficiency,
  self-discharge, an 80 % discharge cap, temperature derating. The SoC is
  stateful — it integrates over the simulated clock, so a time jump
  really moves it.
- **The device profile** — a JSON register map from `shared/profiles/`
  (`sun2000`, the exhaustive `sun2000_full`, the Deye hybrids,
  `demo-fc4`). Each entry carries its type (`i16`/`u16`, `i32`/`u32` and
  the swap forms, `f32` floats, `bit` for the coil/discrete spaces) and
  its `fc` — the address space it lives in (FC3 holding, FC4 input, FC1
  coils, FC2 discrete inputs); coded registers carry their value maps in
  the profile's `mappings` tree. Names the profile leaves out are not
  served — read as 0, or rejected with exception 02 in `--strict` mode.
  The 65000-65003 diagnostics block (the cache/scraper 0xCAFE magic) is
  always mocked.
- **The write overlays** — FC06/FC16 writes land on the holding-register
  overlay, FC05/FC15 writes on the coil overlay, behind the
  `--allow-write` gate; `set register`/`set coil`/`set discrete` on the
  control socket do the same by hand. The overlays are what the scrapers
  read back.
- **Chaos, the clock, the demo values** — `--chaos P` answers a request
  with probability P hostile and drops it; the hostile replies come in
  eight modes (`garbage`, `short`, `lying`, `txn`, `unit`, `stall`,
  `dropout`, `exception`), seeded by `--seed`. `--time-scale N` runs the
  simulated clock N times real time (a full day in 24/N real hours,
  capped at a day per minute); `--time HH:MM` freezes it; `--static`
  serves the classic constant demo values (PV 4000 W, the battery
  charging at 1200 W) instead of the day simulation.

The tick order matters for what a client sees: each pass of the
simulated clock recomputes the machines, the profile layer maps every
name onto its address, and a read answers the overlay first, the
simulated value second, and nothing (0, or exception 02 under
`--strict`) where the profile has no entry.

## The register map

The profile is the fake's served truth: a JSON register map from
[shared/profiles/](../../shared/profiles/) (a bare name) or a path —
`sun2000` the default, the exhaustive `sun2000_full`, the three Deye
hybrids (`deye-sg03lp1`, `deye-sg04lp3`, `deye-sg05lp3`), `demo-fc4`.
Each entry maps a logical name onto a wire address and carries the
`fc` — the address space it lives in (FC3 holding / FC4 input words,
FC1 coils / FC2 discrete inputs) — the `type` (`u16`/`i16`, `u32`/`i32`
and the word-swapped forms, `f32`, `bit`), a terse `desc` and, for
coded registers, the value map in the profile's `mappings` tree; the
profile's `acl` tree is the typed write gate the cache can point its
register allow-list at.

Serving walks the table: the simulator produces the named values, the
profile layer encodes each onto its address in its type, and the
server answers reads out of the assembled map. A name the profile
leaves out is not served — it reads as 0, or refuses with exception 02
under `--strict`. The write overlays sit on top: an accepted Modbus
write (or `set register`/`set coil`/`set discrete`) pins its value and
the overlay wins over the simulation wherever the profile reads the
address. The 65000–65003 diagnostics block (the cache/scraper 0xCAFE
magic) is always mocked, whatever the profile says.

The round trip is the point of the shared profile home: the cache and
the scraper decode the fake's words with the same profile entries that
encoded them, so a value survives the ladder — what the simulator
computed is what the metrics serve. One JSON home for the whole suite
([shared/profiles/README.md](../../shared/profiles/README.md)), the
lint at [dev/gates/profile.py](../../dev/gates/profile.py).

## Source layout

The subproject, entry by entry:

```text
apps/inverter/
├── bin/
│   ├── modbus-fake-inverter.py  # the daemon: the flags, the config load, the serving loop
│   └── modbus-fake-cli.py       # the console-style control session (a symlink to the
│                                #   family's pvsuite-cli, apps/pvsuite-cli.py)
├── lib/
│   ├── simulator.py             # the day: the PV curves, the clouds, the grid wanderers,
│   │                            #   the outage machine, the runtime overrides
│   ├── battery.py               # the battery state machine (the SoC integrates)
│   ├── chaos.py                 # the seeded hostile-reply dice layer
│   ├── profile.py               # the register-map profiles: name -> address, encoding
│   ├── inverter.py              # the Modbus TCP server: the reads, the write overlays
│   ├── signals.py               # the SIGHUP env layer, the SIGUSR1 reset, the shutdown
│   ├── metrics.py               # the /metrics endpoint
│   ├── control.py               # the JSON-lines control server
│   ├── config.py                # the config script, the env layer, the resolution ladder
│   ├── options.json             # the knob registry — one row per knob
│   ├── options.py               # the registry loader
│   ├── statics.py               # the numbers a demo device is born with
│   ├── defaults.json            # the packaged defaults
│   ├── man.py                   # the man pages' prose (the pages render from it)
│   └── cli_spec.py              # the client SPEC — the per-tool half of pvsuite-cli
├── examples/
│   └── modbus-fake-inverter.conf  # the generated all-commented example configuration
├── man/                         # the shipped man pages
├── dev, dev-cli                 # the dev wrappers: the daemon on the example conf, its console
└── README.md                    # the front page
```

The client page ([pvsuite-cli.md](pvsuite-cli.md)) covers the console
half; the daemon's surfaces live in the modules above.

## Installing

### From the tree

The tool runs from the checkout with `python3`, nothing to build:

```bash
python3 apps/inverter/bin/modbus-fake-inverter.py --help
python3 apps/inverter/bin/modbus-fake-cli.py --help
```

`apps/inverter/bin/modbus-fake-cli.py` is a symlink onto the family's
client dispatcher (`apps/pvsuite-cli.py`). Two shell wrappers serve the
development loop: `apps/inverter/dev` starts the daemon against the
shipped example conf with the audit trail on stdout, and
`apps/inverter/dev-cli` opens the console against that daemon's default
socket.

### Nix / NixOS

The Nix package lives at
`nixos/pkgs/modbus-fake-inverter/package.nix`: it installs the daemon and
the client as `modbus-fake-inverter` / `modbus-fake-cli`, the man pages,
the shared profiles and the example conf. There is no NixOS service module
for the fake — the modules under `nixos/modules/` cover the cache, the
scraper and the dashboard — so a NixOS host runs the binary in a custom
unit or straight from the package.

### Docker

The image recipe is `docker/Dockerfile.modbus-fake-inverter`: Alpine 3.20,
Python stdlib only, running as the unprivileged `pvsuite` user. The
default command binds every interface and audits to stdout:

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-fake-inverter -t modbus-fake-inverter \
    --build-context shared=../shared \
    --build-context scripts=../docker --build-context common=../common \
    --build-context cli=../apps ../apps/inverter
docker run --rm -p 127.0.0.1:5502:5502 modbus-fake-inverter
```

The image loads its bundled conf from
`/pv-suite/inverter/modbus-fake-inverter.conf` (the default `--config`
target); the demo compose stack overlays the env file
`docker/env/modbus-fake-inverter.env.example`, and the prod compose runs
no fake service. The `HEALTHCHECK` runs `modbus-fake-cli show version`
over the unix control socket.

## Quick start

Terminal one — the fake with defaults serves `127.0.0.1:5502`. Terminal
two — drive the scenario, read the served registers over the control
wire, then run the family ladder against the fake; the cache's and the
scraper's defaults already point at the fake's port:

```bash
python3 apps/inverter/bin/modbus-fake-inverter.py            # terminal one
python3 apps/inverter/bin/modbus-fake-cli.py set pv 2500     # terminal two
python3 apps/inverter/bin/modbus-fake-cli.py show registers
python3 apps/cache/bin/modbus-cache.py &     # :5502 upstream, serves :15502
python3 apps/scraper/bin/modbus-scraper.py & # scrapes :15502, /metrics on :9350
curl -s http://127.0.0.1:9350/metrics | grep fake_inverter_power_watts
```

`show registers` prints the loaded profile's register map with the
current values — the same words a real Modbus client would read.
`--dry-run` validates a configuration and prints the effective settings
without binding anything (exit 0 = valid, 1 = invalid, 2 = misuse).

## Configuration

### How a setting resolves

Every knob resolves flag > environment > config script > built-in
default. The environment names are bare upper-snake twins of the knob
names with no tool prefix (`MAX_KWP`, `TIME_SCALE`, `CONNECT_ACL`,
`CONTROL_TOKEN`, ...). The config script is a set-grammar file — every
line a `set <name> <value>`, comments start with `#` — the same grammar
the control console speaks; `show config` re-renders the effective
script. `--config` spells the file explicitly; unset, the start searches
`$CONFIG`, then `modbus-fake-inverter.conf` next to the script, then the
subproject root.

### The knobs

One table, mined from the registry (`apps/inverter/lib/options.json`) and
the man page. The first block is the fake's own demo layer — the runtime
pins and machines; the rest is the family serving surface. The **live**
column says whether the knob accepts a live `set` over the control wire
(`yes`) or applies on restart only (`restart`); the live path is the
`set` word (a namespace path spells as words: `set modbus auth suite`).

| knob (live path) | flag | env | default | live | what it does |
|---|---|---|---|---|---|
| pv (`pv`) | — | — | auto | yes | pin the PV power in W, or auto |
| load (`load`) | — | — | auto | yes | pin the home load in W, or auto |
| batt (`batt`) | — | — | auto | yes | pin the battery power in W (+charge/-discharge), or auto |
| grid (`grid`) | — | — | auto | yes | pin the grid setpoint in W (+export/-import); the battery balances |
| soc (`soc`) | — | — | auto | yes | pin the state of charge (seeds the machine), or auto |
| mppt (`mppt`) | — | — | both | yes | enabled PV strings: `both`, `east`, `west`, `none` |
| cloud (`cloud`) | — | — | clear | yes | scale the PV: 0 = clear, 1 = dark, or `autumn`/`spring`/`winter` |
| scenario (`scenario`) | — | — | custom | yes | preset scene (`morning`/`noon`/`evening`/`night`); releases the value pins |
| battery-state (`battery-state`) | — | — | auto | yes | force the machine: `charging` or `discharging`, or auto |
| grid-outage (`grid-outage`) | — | — | off | yes | the blackout machine: `on`, `off`, or force `outage` now |
| listen (`system listen`) | `--listen` | `LISTEN` | 127.0.0.1:5502 | restart | the Modbus listen address HOST:PORT |
| unit (`unit`) | `--unit` | — | 1 | restart | the Modbus unit id served (1..247) |
| modbus-profile (`modbus profile`) | `--modbus-profile` | `MODBUS_PROFILE` | sun2000 | yes | device profile JSON; a bare name resolves in `shared/profiles/` |
| max-kwp (`max-kwp`) | `--max-kwp` | `MAX_KWP` | 6.0 | yes | PV array size in kWp; peak = 75 % of it |
| timezone (`timezone`) | `--timezone` | — | utc | yes | the clock the machines integrate over: `utc` or `local` |
| time (`time`) | `--time` | `TIME` | auto | yes | freeze the simulated clock HH:MM (jumps integrate the battery) |
| time-scale (`time-scale`) | `--time-scale` | `TIME_SCALE` | 1.0 | yes | simulated clock speed: N× real time, capped at a day per minute |
| static (`static`) | `--static` | — | off | yes | constant demo values instead of the day simulation |
| battery-kwh (`battery-kwh`) | `--battery-kwh` | — | 6.9 | yes | usable battery capacity in kWh |
| strict (`strict`) | `--strict` | `STRICT` | off | yes | reject undefined registers with exception 02 |
| chaos (`chaos`) | `--chaos` | `CHAOS` | 0.0 | yes | hostile-reply probability 0..1 |
| seed (`seed`) | `--seed` | — | random | yes | re-seed the chaos RNG |
| grid-voltage (`grid-voltage`) | `--grid-voltage` | — | 230.0 | yes | nominal phase voltage (120 or 230); the setpoint overrides the machine |
| grid-voltage-wander (`grid-voltage-wander`) | `--grid-voltage-wander` | — | 0.1 | yes | the per-phase wander as a fraction of the nominal (0 = flat) |
| grid-frequency (`grid-frequency`) | `--grid-frequency` | — | 50.0 | yes | nominal grid frequency; the setpoint overrides the machine |
| grid-frequency-wander (`grid-frequency-wander`) | `--grid-frequency-wander` | — | 0.2 | yes | the frequency machine's clamp in Hz (0 = flat) |
| modbus-auth (`modbus auth`) | `--modbus-auth` | `MODBUS_AUTH` | none | yes | the scheme the fake's clients must speak: `suite` or none |
| modbus-auth-key (`modbus auth key`) | `--modbus-auth-key` | `MODBUS_AUTH_KEY` | unset | restart | the suite handshake's shared key, min 16 chars — a secret |
| connect-acl (`connect-acl`) | `--connect-acl` | `CONNECT_ACL` | any | yes | the Modbus peers allowed to connect: `any`/`none`/IP,CIDR,... |
| allow-write (`write allow`) | `--allow-write` | `ALLOW_WRITE` | off | yes | accept Modbus writes (FC05/06/15/16); off = exception 01 |
| max-clients (`max-clients`) | `--max-clients` | `MAX_CLIENTS` | 64 | yes | refuse connections past this many simultaneous clients (0 = no limit) |
| client-timeout (`client-timeout`) | `--client-timeout` | `CLIENT_TIMEOUT` | 300 | yes | disconnect clients silent this many seconds (0 = never) |
| max-conn-per-ip (`max-conn-per-ip`) | `--max-conn-per-ip` | `MAX_CONN_PER_IP` | 0 | yes | simultaneous connections from one peer IP (0 = no limit) |
| control-port (`control port`) | `--control-port` | `CTL` | the unix socket | yes | control target: unix path or TCP port on 127.0.0.1; 0 = off |
| control-token (`control token`) | `--control-token` | `CONTROL_TOKEN` | unset | restart | the admin token on control connections — a secret |
| control-ops-token (`control ops token`) | `--control-ops-token` | `CONTROL_OPS_TOKEN` | unset | restart | the read-only ops token — a secret |
| control-ops-verbs (`control ops verbs`) | `--control-ops-verbs` | `CONTROL_OPS_VERBS` | show | yes | the ops role's verb policy, comma-separated |
| control-trust-uids (`control trust-uids`) | `--control-trust-uids` | `CONTROL_TRUST_UIDS` | unset | yes | extra peer uids the unix socket trusts without the token |
| control-socket-group (`control socket-group`) | `--control-socket-group` | `CONTROL_SOCKET_GROUP` | off | yes | chmod the unix socket 0660 instead of 0600 |
| metrics-server (`metrics enable`) | `--metrics-server` | — | off | yes | serve the fake's own /metrics endpoint |
| metrics-listen (`metrics-listen`) | `--metrics-listen` | — | 127.0.0.1:9352 | restart | the /metrics bind address; a token is mandatory beyond loopback |
| metrics-token (`metrics token`) | `--metrics-token` | `METRICS_TOKEN` | unset | restart | the /metrics bearer token — a secret |
| metrics-acl (`metrics acl`) | `--metrics-acl` | `METRICS_ACL` | any | yes | the /metrics client gate: `any`/`none`/prefixes/`file:<path>` |
| metrics-max-clients (`metrics-max-clients`) | `--metrics-max-clients` | — | 64 | restart | concurrent /metrics clients past which extras get 503 |
| metrics-client-timeout (`metrics-client-timeout`) | `--metrics-client-timeout` | — | 5 | restart | idle /metrics client timeout (0 = the built-in 5 s cap) |
| metrics-max-conn-per-ip (`metrics-max-conn-per-ip`) | `--metrics-max-conn-per-ip` | — | 0 | restart | concurrent /metrics connections from one peer IP |
| audit-log (`audit log-file`) | `--audit-log` | `AUDIT_LOG` | the XDG state home | yes | the audit trail: a path, `-` for stdout, `none` for off |
| audit-forward (`audit forward`) | `--audit-forward` | `AUDIT_FORWARD` | none | yes | forward the trail: `syslog`, `syslog:/path`, `udp://`, `tcp://` |
| audit-forward-format (`audit forward format`) | `--audit-forward-format` | `AUDIT_FORWARD_FORMAT` | rfc5424 | yes | the remote envelope: `rfc5424` or `cef` |
| audit-instance (`audit instance`) | `--audit-instance` | `AUDIT_INSTANCE` | the control port | yes | the audit lines' `instance=<id>` writer word |
| audit-max-mb (`audit rotate max-size`) | `--audit-max-mb` | `AUDIT_MAX_MB` | 10 | yes | rotate the audit log at this size in MB (0 = off) |
| audit-daily (`audit rotate daily`) | `--audit-daily` | `AUDIT_DAILY` | off | yes | also rotate at UTC midnight |
| audit-files (`audit rotate files`) | `--audit-files` | `AUDIT_FILES` | 3 | yes | rotated audit backups to keep |
| no-audit-log (`audit disable`) | `--no-audit-log` | `NO_AUDIT_LOG` | off | yes | disable the audit trail entirely |
| log-level (`system log-level`) | `--log-level` | `LOG_LEVEL` | INFO | yes | verbosity; DEBUG adds client traffic and per-poll detail |
| log-access (`system log-access`) | `--log-access` | — | off | yes | log connects/disconnects at INFO instead of DEBUG |
| local-time (`system local-time`) | `--local-time` | — | off | yes | log timestamps in the system zone instead of UTC |
| control-log-replies (`system log-replies`) | `--control-log-replies` | — | off | yes | DEBUG-log every control command's full output |
| dump-path (`dump path`) | `--dump-path` | `DUMP_PATH` | unset | yes | the state dump file (the live overrides as one JSON) |
| dump-key (`dump key`) | `--dump-key` | `DUMP_KEY` | unset | restart | the key that seals the dumps and the reload state file — a secret |
| dump-interval (`dump interval`) | `--dump-interval` | `DUMP_INTERVAL` | 0 | yes | seconds between automatic dumps (0 = request and shutdown) |
| restore-on-start (`dump restore-on-start`) | `--restore-on-start` | `RESTORE_ON_START` | off | restart | load the state dump at start (needs a dump path) |
| config | `--config` | `CONFIG` | the search path | — | the set-grammar config script |
| dry-run | `--dry-run` | — | — | — | validate, print the effective settings, exit |

The dash-marked env cells are the F11 posture: the demo layer's own knobs
ride the flags only, so an environment variable can never pin a demo by
accident. The seven knobs the SIGHUP environment layer re-applies to a
running daemon are `CHAOS`, `MAX_KWP`, `MODBUS_PROFILE`, `STRICT`, `TIME`,
`TIME_SCALE` and `LOG_LEVEL` — all-or-nothing, keep-last-good.

### The config file

The shipped sample, `apps/inverter/examples/modbus-fake-inverter.conf`,
is generated from the knob registry — all 52 knobs, every line commented,
so a configuration is the subset uncommented. A pasteable line is a
control line: `set modbus auth suite` in the file does exactly what the
same words do in the console. The demo machines (`pv`, `load`, `batt`,
`grid`, `soc`, `mppt`, `cloud`, `scenario`, `battery-state`,
`grid-outage`) are runtime set words with no flag, no env and no config
line — they never render in a config file. A rendered secret line reads
`set control token *** SECRET REMOVED ***`; pasting such a line back
refuses to parse — pass the secret by flag, env or as `file:<path>`.

### Secrets

Five knobs are secrets: `control-token`, `control-ops-token`,
`metrics-token`, `modbus-auth-key` and `dump-key`. Every one takes the
`file:<path>` form — the first line of an owner-only 0600 file (a systemd
`LoadCredential` rides as `file:/run/credentials/...`); a bare flag value
lands in `ps`, so the file form is the disciplined one. Every one is
startup-only: the wire refuses a live `set`/`clear`, and `show` refuses
the knob — the value never renders back.

## Runtime control

Signals mirror the family:

- `SIGHUP` re-applies the environment layer, all-or-nothing
  (keep-last-good): the seven demo-layer env twins above — the fake's
  re-configure path for a running daemon.
- `SIGUSR1` resets the scenario: the runtime pins, the cloud machine, the
  write overlay and the pinned coils/discrete inputs are dropped; the
  simulation continues.
- `SIGTERM`/`SIGINT` shut down gracefully with a session summary, writing
  the state dump when a dump path is configured.

The same reset is the `reset` control verb, which reports what it
cleared. The register pseudo-setting is the Modbus-write emulation by
hand: `set register ADDR VAL` puts a value into the holding-register
overlay the scrapers read, `set coil ADDR VAL` and `set discrete ADDR
VAL` pin the bit spaces; the rows have no live knobs of their own —
`reset` clears them.

A worked console sequence, one-shot form:

```text
$ python3 apps/inverter/bin/modbus-fake-cli.py set scenario noon
$ python3 apps/inverter/bin/modbus-fake-cli.py set pv 2500
$ python3 apps/inverter/bin/modbus-fake-cli.py set register 32064 1500
ok register 32064=1500 (the write overlay, the scrapers read it)
$ python3 apps/inverter/bin/modbus-fake-cli.py show config
$ python3 apps/inverter/bin/modbus-fake-cli.py request reload-config
$ python3 apps/inverter/bin/modbus-fake-cli.py reset
```

`set scenario noon` freezes the simulated clock at 12:00 and releases the
value pins; `show config` prints the effective set-grammar script
(secrets rendered as removed); `request reload-config` re-reads the
config file over the running machines without a restart. A bare terminal
command opens the interactive console with the same verbs.

## Persistence

The simulation is stateful — the battery's SoC integrates, the pins and
overlays accumulate — and the dump family is how a demo survives a
restart. `--dump-path` names the file: the live setting overrides (the
values a `set` pinned over the machines) as one JSON document.
`request dump` writes on demand, `--dump-interval` on a cadence, the
graceful shutdown writes a final dump (the session summary rides the
log), and `--restore-on-start` loads it at start.

The file writes atomically and 0600, and every dump carries a sha256
integrity hash of its content — edited, truncated or foreign files
refuse to restore, and a group- or world-writable dump is refused
outright. `--dump-key` seals the file with the family's shared seal —
the version-2 envelope: HMAC-SHA256 keystream encryption, an HMAC over
nonce+box, the mac checked first — and the gate is symmetric: a
restore without the key refuses a sealed dump, a restore with the key
refuses an unsealed one. `request reload` rides the same machinery:
the overrides save to a state file, the process re-execs, the fresh
daemon re-applies them once.

The clock itself is not persisted: a restart re-derives the day from
the pinned or wall time (`--time`, `--time-scale`) — and a restored
`soc` pin re-seeds the battery machine where the dump left it.

## The control plane

`modbus-fake-cli` is one client with three invocation shapes: command
words one-shot (`modbus-fake-cli show config`), a piped stdin batch (the
script lines run in order), or a bare terminal, which opens the
interactive console — the prompt shows the connected target, TAB
completes commands, settings and values, `?` prints the listings, and
long replies page. The session is audited with the `CLI` prefix.

The wire is JSON lines: the client sends `{"cmd": "..."}`, the server
answers `{"status": "ok|fail|note|bye", "text": "..."}`. With a token
configured, every frame carries a full sha256 HMAC — the family's signed
control wire. The verbs: `set`, `clear`, `show` (the settings, plus
`show connections`, `show registers`, `show config`, `show version`,
`show knobs`, `show metrics-acl-table`), `help`, `inspect` (one pretty
dump of everything), `ping`, `reset`, `request dump` / `request restore`
(the state machinery, needs a dump path), `request reload` (the
whole-daemon restart that keeps the pins: the overrides save to a state
file, the process re-execs and re-applies them), `request reload-config`,
`shutdown` (the console asks for confirmation) and `quit`.

The default target is the unix socket
`/tmp/fake-inverter-5502.socket` — the listen port spliced into the
family's socket template. `--control-port` spells a different unix path
or a TCP port on 127.0.0.1; `0` turns the listener off. Over TCP the
token is required when configured; over the unix socket a trusted peer
(root, the daemon's own user, or the `--control-trust-uids` list —
`SO_PEERCRED`) speaks without the token. The socket is 0600, or 0660 with
`--control-socket-group`. A second, read-only token
(`--control-ops-token`) authenticates into the verbs its policy allows —
the default policy is `show` only (`--control-ops-verbs`); both roles are
audited. The listener rebinds live: `set control-port` swaps the socket
without dropping the connected sessions.

## Access control

The fake is a development tool — run it on a trusted, LAN-isolated
network. It is deliberately *not* security-first design (the audit's F11,
the test-tool exemption every other tool refuses): the Modbus surface
speaks by default to any peer that can reach the port, and the fake keeps
its tokenless-TCP control posture. No TLS anywhere. Do not expose it
beyond a lab segment. What does exist, opt-in:

- **The connect ACL** — `--connect-acl` (`any` the default, `none`, or a
  comma-separated IP/CIDR list, live-settable) filters who may connect to
  the Modbus port at all. The cache's connect-acl, mirrored.
- **The Modbus auth leg** — `--modbus-auth suite` demands a crypt
  handshake right after every connect: 52 bytes (magic, fresh nonce,
  HMAC-SHA256 proof of `--modbus-auth-key`, min 16 characters); the fake
  answers `OK` (plain Modbus follows) or `ERR` and drops the client
  before it ever sees a register. Empty auth means no auth at all. The
  leg in detail is [Modbus auth](#modbus-auth).
- **The write gate** — `--allow-write` off (the default) refuses every
  Modbus write with exception 01 and audits WRITE-REFUSED; on, a write
  lands in the overlay, audited WRITE.
- **The metrics shape** — the fake's own /metrics endpoint refuses to
  start beyond loopback without a token (F13), and `--metrics-acl`
  narrows who reaches the endpoint; the check runs at accept, a client
  off the ACL is closed without a reply.
- **The caps** — `--max-clients`, `--client-timeout` and
  `--max-conn-per-ip` cap runaway connections; a read-count gate keeps a
  malformed frame from assembling an oversized reply.

The full family story — the caps, the supply-chain claim — is
`docs/SECURITY.md`.

## Modbus auth

The fake's leg is the server side of the family's suite handshake.
With `--modbus-auth suite`, every client proves the shared key right
after every connect — the 52-byte frame: the protocol magic, a fresh
nonce, an HMAC-SHA256 proof — and the fake answers `OK` (plain Modbus
follows) or `ERR` (the client drops before it ever sees a register).
The key's floor is 16 characters; the key itself (`--modbus-auth-key`)
is a secret — passed as `file:<path>`, startup-only, never rendering.
The handshake authenticates the session; the traffic after it is plain
Modbus, no TLS. An unset scheme is no auth at all — the F11 posture.

## Metrics

The fake carries its own Prometheus endpoint, off by default: start it
with `--metrics-server` (or `set metrics enable` live), bound to
`--metrics-listen` (`127.0.0.1:9352` by default). It serves the
simulator's state and the server's counters in the Prometheus text
format: `fake_inverter_power_watts{kind="pv"|"load"|"grid"|"battery"}`
(the simulated powers in W, grid +export), `fake_inverter_soc_percent`,
`fake_inverter_grid_phase_volts{phase="a"|"b"|"c"}`,
`fake_inverter_grid_hz`, `fake_inverter_grid_outage` (1 while the
simulated grid is down), `fake_inverter_time_scale`,
`fake_inverter_uptime_seconds`, `fake_inverter_chaos_hits_total`, and
`fake_inverter_modbus_requests_total` /
`fake_inverter_modbus_connections_total`. `--metrics-token` demands
`Authorization: Bearer <token>` (the same scheme the scraper speaks);
`--metrics-acl` checks the peer at accept; the caps answer 503 past
`--metrics-max-clients` clients.

## The audit trail

The audit trail is on by default at the XDG state home
(`~/.local/state/fake-inverter/audit.log`), prefixed `INV`. `--audit-log`
spells a file, `-` for stdout (the docker/journald way) or `none` to turn
the local file off (with a forward spelled, that is the remote-only
mode). `--audit-forward` also forwards every line: `syslog` (the local
socket auto-scan), `syslog:/path`, `udp://host[:514]` (RFC5426,
best-effort) or `tcp://host[:514]` (RFC6587 framing); the remote envelope
is `--audit-forward-format` (`rfc5424` the default, or `cef`), and the
off-box copy carries the per-writer hash chain, so a scheduled search at
the collector can alert on a chain break. Every line names its writer in
`instance=<id>` — the control port when `--audit-instance` is unset, the
override when spelled; make an override unique among everything sharing
one collector. Rotation is `--audit-max-mb` (size), `--audit-daily` (UTC
midnight) and `--audit-files` (backups kept). The WRITE, WRITE-REFUSED
and COMMAND events land here like the family's. The client keeps its own
trail with the `CLI` prefix, same knobs; the wire commands are audited
once, by the server.

## Tuning

The scenario knobs are the operator-facing tuning surface — everything a
demo needs to fake a different day or a different device:

- **The array** — `--max-kwp` sizes the PV (peak = 75 % of it); `set
  mppt east` watches only the morning string, `west` only the afternoon
  one, `none` zeroes the PV.
- **The battery** — `--battery-kwh` sets the usable capacity; `set soc`
  seeds the machine; `set battery-state charging` forces full-power
  charge or discharge for a battery-heavy demo.
- **The sky and the grid** — `set cloud autumn|spring|winter` (or a
  0..1 factor) shades the PV; `--grid-voltage 120` flips to a split-phase
  nominal; the wander knobs flatten or loosen the grid machines; `set
  grid-outage on` runs the blackout machine, `outage` forces the blackout
  now.
- **The clock** — `--time 12:00` freezes noon; `--time-scale 60` runs a
  full day in 24 real minutes; `set scenario evening` is the one-word
  preset. Freezing and jumping integrate the battery, so the clock is the
  time-lapse control.
- **The misbehavior** — `--chaos 0.1 --seed 7` makes one request in ten
  fail reproducibly, for testing every client's error path; `--strict`
  makes undefined registers refuse instead of reading 0.

## Deployment

**Docker.** The env file `docker/env/modbus-fake-inverter.env.example`
lists every env twin the registry declares, each commented with its
image-default value. It is read at container creation, and because a
value resolves flag > env > config > default, an env line beats the
bundled conf knob by knob (the image's CMD flags, `--listen` and
`--audit-log`, cannot be beaten by the env file — replace the CMD to move
those binds). The SIGHUP layer is the live half: `docker kill -s HUP
<container>` re-applies the environment layer to the running daemon, so
the demo-layer twins retune a running container without recreating it.
The `/config` volume exists for symmetry with the other images; the fake
ships no required file artifacts there.

**Nix / NixOS.** The package
(`nixos/pkgs/modbus-fake-inverter/package.nix`) installs both binaries,
the man pages, the profiles and the examples; there is no service module,
so a NixOS host writes its own unit. The family's systemd posture is
worth copying: secrets as `LoadCredential=` files passed as
`file:/run/credentials/...`, `--control-trust-uids` letting the local
unit speak over the unix socket without the token, `--audit-log -` for
journald, `ExecReload=/bin/kill -HUP $MAINPID` to drive the environment
layer, and `Restart=on-failure`.

## Troubleshooting

- **The bind fails** — an address already in use answers with one
  `cannot bind HOST:PORT: reason` ERROR line and exit status 1, no
  traceback. Another fake (or the real device) holds the port; pick
  another with `--listen`.
- **The start refuses early** — the validator answers one-line failures
  (unit id out of range, non-positive kWp, a chaos value above 1, a
  control socket path too long, ...) with exit status 1; flag misuse
  exits 2. `--dry-run` separates the two without binding anything.
- **Reads return exception 02** — `--strict` is on and the profile does
  not serve that address. Drop the flag, or pick a profile that carries
  the register.
- **Reads intermittently fail or hang** — chaos is on (`set chaos off`
  to stop it), or the grid-outage machine is running (`show
  grid-outage`). Both are features; `SIGUSR1` or `reset` clears the pins.
- **The numbers never move** — the clock is frozen (`--time`, or a
  scenario preset pinned it; `set time auto` resumes the real clock), or
  `--static` is serving the constant demo values (`set static off`).
- **The register write lands but nothing changes downstream** — the
  overlay wins over the simulation only where the profile reads it;
  `show registers` is the truth the scrapers see.
- **The console will not connect** — the default socket follows the
  listen port (`/tmp/fake-inverter-5502.socket` for the default bind);
  over TCP, a configured token must be presented (`--control-token` or
  `CONTROL_TOKEN`).

## Testing

Two suites in `dev/suites/` exercise the fake directly:

- `dev/suites/inverter-regtest.py` — the daemon's regression: the
  machines, the registers, the auth legs, the ACL, the write gate, the
  sealed dumps, the secret rendering, the signed wire, the live rebind.
- `dev/suites/control-fuzz.py` — the control wire under hostile input:
  malformed JSON lines, oversized frames, the token/HMAC path, the
  one-shot and console clients.

The fake is also the device for the rest of the family's suites —
`cache-regtest.py`, `cache-fuzz.py`, `cache-control-fuzz.py`,
`cache-stress.py`, `scrape-regtest.py`, `scrape-fuzz.py`,
`replay-regtest.py` and `audit-chain.py` all stand the fake in as the
upstream device, so a fake regression shows up four suites away.

The suites always run through the battery runner, never standalone — the
runner owns the run dir and the port slots:

```bash
python3 dev/battery/battery.py inverter    # the fake's commit set (~1 min)
```

The `inverter` profile runs `check-options`, `links-check`,
`lint-gates`, `inverter-regtest`, `control-fuzz` and `audit-chain`;
`dev/battery/battery.py full` is the nightly, all ten suites at full
depth.

## The docs map

| document | what it holds |
|---|---|
| `apps/inverter/README.md` | the tool's front page: usage, the security posture, the license |
| `apps/inverter/lib/options.json` | the knob registry: flags, env twins, defaults, live paths, secrets |
| `apps/inverter/examples/modbus-fake-inverter.conf` | the generated config sample — all 52 knobs, commented |
| `apps/inverter/man/modbus-fake-inverter.1` | the daemon's man page (also `modbus-fake-inverter --man`) |
| `apps/inverter/man/modbus-fake-cli.1` | the client's man page |
| `apps/inverter/dev`, `apps/inverter/dev-cli` | the dev wrappers: the daemon on the example conf, its console |
| `nixos/pkgs/modbus-fake-inverter/package.nix` | the Nix package (no service module) |
| `docker/Dockerfile.modbus-fake-inverter` | the image recipe |
| `docker/env/modbus-fake-inverter.env.example` | the container env sample, generated from the registry |
| `shared/profiles/README.md` | the device profiles the fake serves: format, lint, format gate |
| `docs/SECURITY.md` | the family's security claims and the F11/F13 posture |
| `docs/specs/ACL.md` | the ACL grammar the connect and metrics gates speak |
| `docs/specs/MODBUS.md` | the family's Modbus support tables |
| `nixos/README.md` | the NixOS deployment story for the family |
| `docker/README.md` | the images, the compose topologies |
| `docs/book/src/fake.md` | the book's chapter on the fake |

## License

The fake inverter (source, Nix packaging) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository
root.
