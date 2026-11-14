# The fake-inverter manual

A dependency-free (Python stdlib only) Modbus TCP server that plays an
inverter — the battery, the smart meter, the diagnostics — for the family to
develop and test against. Part of the pv-suite family.

- the daemon's own `--help` and the man page (`modbus-fake-inverter --man`)
  carry the startup surface; this page carries the full reference.

- **generated** from `lib/options.json` (the one-knob-one-source rows) by
  `dev/generators/manual.py` — edit the registry (or the REF data in the
  generator) and re-run, never this file.

## Run it

    python3 apps/inverter/bin/modbus-fake-inverter.py                       # 127.0.0.1:5502 — scraper defaults just work
    python3 apps/inverter/bin/modbus-fake-inverter.py --time 12:00          # frozen noon: ~4.5 kW PV, exporting
    python3 apps/inverter/bin/modbus-fake-inverter.py --static              # the classic static demo values
    python3 apps/inverter/bin/modbus-fake-inverter.py --listen 127.0.0.1:15502 --log-level DEBUG
    python3 apps/inverter/bin/modbus-fake-inverter.py --config apps/inverter/examples/modbus-fake-inverter.conf --dry-run

- add **`--dry-run`** to validate the configuration and print the effective
  settings. Exit codes: `0` = valid, `1` = invalid, `2` = CLI misuse.

- the startup surface is the family's: **flag > env > config script > the
  built-in defaults**. The config file (`--config PATH`, `$CONFIG`, then
  `modbus-fake-inverter.conf` next to the script) speaks the **set grammar** —
  every line a `set <name> <value>` in the CLI spelling, the same line pastes
  into the console or `modbus-fake-cli` — and the bundled sample is
  `examples/modbus-fake-inverter.conf`.

- the pins and the machines (`pv`, `load`, `batt`, `grid`, `soc`, `mppt`,
  `cloud`, `scenario`, `battery-state`, `grid-outage`) stay control-wire
  settings: the config names one and the start refuses.

- `SIGHUP` re-applies the **environment layer** (all-or-nothing — flags are
  startup-only): `CHAOS` (0..1), `MAX_KWP`, `MODBUS_PROFILE`, `STRICT`,
  `TIME`, `TIME_SCALE`, `LOG_LEVEL` — booleans accept `true`/`false`, `1`/`0`,
  `yes`/`no`, `on`/`off`. The same twins ride the start in the ladder —
  `CHAOS=0.9` at creation is honored, SIGHUP retunes a running fake.

- the fake ships as an alpine container — stdlib-only, no pip, running as the
  unprivileged `pvsuite` user with the tools on `PATH`
  (`Dockerfile.fake-inverter` + `compose.yaml`; see `docker/README.md`). The
  image loads its own bundled conf
  (`/pv-suite/inverter/modbus-fake-inverter.conf`, the built-in `--config`
  target) — the env file and the CMD flags override it. The version reports as
  `0.5.1` inside the image (no git metadata; a checkout shows `0.5.1-<short git>`).

## How it works

- everything integrates with a **simulated clock: UTC by default**
  (`--timezone local` / `set timezone local` for the host wall clock) that can
  run at **N× real speed** (`--time-scale N` / `set time-scale N`) — every
  machine integrates over it, so a full simulated day takes 24/N real hours
  and moving the clock (`set time 18:00`) acts as time-lapse control.

- **the day** — bell-curve PV between 06:00 and 18:00 (peak 75 % of
  `--max-kwp`), home load with morning and evening peaks (grid exports around
  noon, imports mornings/evenings), panel temperature following the ambient
  curve, energy counters growing through the day.

- **`--static`** replaces the day with constant demo values: PV 4000 W, home
  4300 W, grid −1500 W, battery charging 1200 W at 65 % SoC. The runtime
  control pins the individual terms on top of either mode.

- **PV (two MPPT strings)** — string-1 = the **east** array (sine bell
  06:00–16:00), string-2 = the **west** array (08:00–18:00): together a
  double-shouldered day. `set mppt both|east|west|none` enables the strings; a
  dark string serves 0 V/0 A. The cloud factor scales the sun in real time;
  the day yield integrates the actual string curve.

- **battery (always on)** — charges from the PV surplus (300 W grid margin,
  max ±2500 W), covers the home deficit by discharging, stops at 100 % full /
  the 10 % reserve floor. The SoC is **stateful**: it integrates the effective
  power with the simulated clock, with the realism folded in — 95 % charge
  efficiency, 0.01 %/h self-discharge, discharge capped at 80 % of the rating,
  temperature-derated (below 0 °C half power, below 10 °C 80 %, above 40 °C 90
  %, above 50 °C 70 %). `set soc <pct>` seeds the machine, `set battery-state charging|discharging`
  forces it, `auto`/`clear` hands the decision back; `--battery-kwh` sizes the
  pack.

- **grid setpoint** — `set grid <W>` pins the grid line: the battery balances
  to hold it (`set grid 0` = zero-export home); `auto` returns to the plain pv
  − battery − home balance.

- **clouds** — a pinned factor (`set cloud 0.7`), a clear sky (the default),
  or a mean-reverting random walk: `autumn` (passing clouds, 0.05–0.95),
  `spring` (fair-weather cumulus, 0.02–0.80), `winter` (heavy overcast spells,
  0.10–1.00). `reset` returns to a clear sky.

- **grid voltage** — three independent mean-reverting walks around the nominal
  (±10 % by default, the phases wander differently); `--grid-voltage` (230 V,
  120 supported — the currents double), `--grid-voltage-wander` (the ±fraction
  of the nominal, 0 = the flat grid) and the matching `set grid-voltage` /
  `set grid-voltage-wander`.

- **grid outages** — `set grid-outage on` arms a two-state machine: the grid
  randomly drops (phases collapse, the inverter stands by — no harvest, no
  battery flow, the SoC holds) and comes back after a few moments. `set grid-outage outage`
  forces a blackout right now (the outage wins over the pins); `off` restores
  plain operation.

- **the unbalanced home** — three slow walks around 1/3 per phase (each
  clamped 22–44 %) distribute the load asymmetrically: the per-phase meter
  currents really differ; the inverter injection stays balanced.

## Speaking to the daemon

- the control server is a JSON-lines listener: a unix socket (the default
  `/tmp/fake-inverter-5502.socket`) or a TCP port on 127.0.0.1 — the
  `--control-port` flag, env `CTL`, `0` = off.

    python3 bin/modbus-fake-cli.py --control-port 15599 show registers
    python3 bin/modbus-fake-cli.py

- the one-shot spelling runs one command per invocation (or a batch on stdin).

- the **console** is the interactive session: `?` lists the words, TAB
  completes, `help <setting>` describes one, `help config` maps every knob to
  its control command, `show knobs` prints the dictionary.

- the fake keeps its trusted-LAN posture (F11): control works over TCP without
  a token too; over the unix socket a trusted peer (root, the daemon's own
  user or `--control-trust-uids` — SO_PEERCRED) always speaks without one.

- the optional ops token (`--control-ops-token`) scopes a session to the
  read-only verbs (the default: show). Every command is audited. The clients
  take `--control-port` (env `CTL`), `--timeout`, `--control-token`, the audit
  flags and `--man`; the cli adds `--reconnect` / `--reconnect-wait`.

- a knob's value resolves at start as flag > env > config script > default;
  the config file (the bundled
  `apps/inverter/examples/modbus-fake-inverter.conf`) speaks the same grammar
  — `set <name> <value>` lines, `--dry-run` prints the effective settings.

The kinds — every row of the tables below carries one:

| kind | meaning |
|---|---|
| command | a one-shot action, no value |
| namespace | a word that groups deeper words: the console walk lists its children, `help <namespace>` describes them |
| settable | the knob is live: `set <name> <value>` applies at once (the flat registry name; the console also completes the row's live/alias path spellings and translates), `clear <name>` returns the configured value, `show <name>` prints the live value. *(restart)* — the set records a pending value and `request reload` applies it. *(secret)* — the value never renders back (show answers err); pass it by flag/env or as `file:<path>`. *(hidden)* — never lists in the ?/TAB pools; the wire still answers |
| startup-only | flag/env/config at start, a restart applies a change; the wire has no set/clear/show for it (it renders in `show config` only). Every secret is startup-only now (the tokens, the auth keys, the dump key): the wire refuses set/clear outright, the value passes by flag/env/config or as `file:<path>` and a restart applies it |
| show-only | a runtime report: `show <report>` answers, nothing to set |

## Commands

| command | kind | description |
|---|---|---|
| `exit` | command (hidden) | close the session |
| `help` | command (internal) | describe a word (help \<setting>) or map every knob (help config) |
| `inspect` | command | one pretty dump of everything: the status, the machines, the overlay |
| `logout` | command (hidden) | close the session |
| `ping` | command (internal) | keep-alive: answers pong |
| `quit` | command | close the session |
| `request` | namespace | the state machinery: the dump written and restored, the fake restarted |
| `request dump` | command (hidden) | write the state dump: the live setting overrides, sealed (when the fake has a dump path) |
| `request reload` | command (hidden) | save the live overrides and restart the whole daemon (the flags and the env are re-resolved) |
| `request reload-config` | command (hidden) | re-read the config file (the values re-apply over the running machines) |
| `request restore` | command (hidden) | re-apply a state dump's overrides (when the fake has a dump path) |
| `reset` | command | clear all pins + the write overlay |
| `set` | command | configure a setting live: set \<setting> \<value> |
| `show` | command | print a setting's live value, or a report |
| `shutdown` | command | stop the server (asks to confirm) |
| `clear` | command | restore a setting to its configured value: clear \<setting> |
| `set register \<addr> \<value>` | command | the Modbus write emulation: plant a register value in the write overlay — reads answer it, reset clears it |
| `set coil \<addr> \<0\|1>` | command | the write emulation: plant a coil value (the coil space, FC1/FC5/FC15 see it, reset clears it) |
| `set discrete \<addr> \<0\|1>` | command | the write emulation: plant a discrete-input value (the discrete space, FC2 sees it, reset clears it) |
## Knobs

The tables spell the knob's registry key — the one internal name the wire,
the replies and the dispatch take; the set / clear column spells the console
words (the live path as words — the config files and the state dumps speak
them; the flat registry name answers the same set everywhere, the clients
translate). The `default` column is the registry's built-in default (the
resolver's last rung after flag > env > config); the namespaces group them.

### general

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `pv` | `set pv` | settable | — | `W\|auto` | — / — | pin the PV power in W, or auto |
| `load` | `set load` | settable | — | `W\|auto` | — / — | pin the home load in W, or auto |
| `batt` | `set batt` | settable | — | `W\|auto` | — / — | pin the battery power in W (+charge/-discharge), or auto |
| `grid` | `set grid` | settable | — | `W\|auto` | — / — | pin the grid power in W (+export/-import), or auto; the battery balances |
| `soc` | `set soc` | settable | — | `%\|auto` | — / — | pin the state of charge (seeds the machine), or auto |
| `mppt` | `set mppt` | settable | — | `both\|east\|west\|none` | — / — | enabled PV strings: string-1 = the east array, string-2 = the west |
| `cloud` | `set cloud` | settable | — | `0..1\|clear\|autumn\|spring\|winter` | — / — | scale the PV: 0 = clear, 1 = dark, clear, or a cloud machine |
| `scenario` | `set scenario` | settable | — | `morning\|noon\|evening\|night\|custom` | — / — | preset scene; releases the value pins |
| `battery-state` | `set battery-state` | settable | — | `auto\|charging\|discharging` | — / — | force the battery state machine, or auto |
| `grid-outage` | `set grid-outage` | settable | — | `on\|off\|outage` | — / — | the grid-outage machine: random blackouts over the simulated clock |
| `unit` | — | startup-only | 1 | `ID` | `--unit` / — | modbus unit id served |
| `max-kwp` | `set max-kwp` | settable | 6.0 | `kW` | `--max-kwp` / `MAX_KWP` | PV array size (peak = 75 % of it) |
| `timezone` | `set timezone` | settable | utc | `utc\|local` | `--timezone` / — | clock the state machines integrate over: UTC or the local wall clock |
| `time` | `set time` | settable | — | `HH:MM\|auto` | `--time` / `TIME` | freeze the clock HH:MM (jumps integrate the battery), or auto |
| `time-scale` | `set time-scale` | settable | 1.0 | `N\|1` | `--time-scale` / `TIME_SCALE` | the simulated clock speed: N× real time — the machines integrate over it |
| `static` | `set static` | settable | off | `on\|off` | `--static` / — | constant demo values instead of the day simulation |
| `battery-kwh` | `set battery-kwh` | settable | 6.9 | `kWh` | `--battery-kwh` / — | usable battery capacity |
| `strict` | `set strict` | settable | off | `on\|off` | `--strict` / `STRICT` | reject undefined registers with exception 02 |
| `chaos` | `set chaos` | settable | 0.0 | `0..1\|off` | `--chaos` / `CHAOS` | hostile-reply probability; off = disable |
| `grid-voltage` | `set grid-voltage` | settable | 230.0 | `V` | `--grid-voltage` / — | nominal grid phase voltage; the machine wanders ±10 % per phase |
| `grid-voltage-wander` | `set grid-voltage-wander` | settable | 0.1 | `fraction` | `--grid-voltage-wander` / — | the per-phase voltage machine's wander range (a fraction of the nominal; 0 = the flat grid) |
| `grid-frequency` | `set grid-frequency` | settable | 50.0 | `Hz` | `--grid-frequency` / — | nominal grid frequency; the machine wanders around it |
| `grid-frequency-wander` | `set grid-frequency-wander` | settable | 0.2 | `Hz` | `--grid-frequency-wander` / — | the frequency machine's clamp in Hz around the nominal; 0 = the flat frequency |
| `seed` | `set seed` | settable | — | `N` | `--seed` / — | re-seed the chaos RNG |
| `connect-acl` | `set connect-acl` | settable | any | `any\|none\|IP,...\|file:\<path>` | `--connect-acl` / `CONNECT_ACL` | the Modbus clients allowed to connect (the cache's connect-acl, mirrored: "any", "none", or a comma-separated IP/CIDR list) |
| `max-clients` | `set max-clients` | settable | 64 | `N` | `--max-clients` / `MAX_CLIENTS` | simultaneous client limit |
| `client-timeout` | `set client-timeout` | settable | 300.0 | `s` | `--client-timeout` / `CLIENT_TIMEOUT` | disconnect clients silent for this long |
| `max-conn-per-ip` | `set max-conn-per-ip` | settable | 0 | `N` | `--max-conn-per-ip` / `MAX_CONN_PER_IP` | simultaneous connections from one peer IP |
| `metrics-listen` | — | startup-only | 127.0.0.1:9352 | `HOST:PORT` | `--metrics-listen` / — | the metrics bind address HOST:PORT |
| `metrics-max-clients` | — | startup-only | 64 | `N` | `--metrics-max-clients` / — | maximum concurrent /metrics clients; extras get an immediate 503, 0 = unlimited |
| `metrics-client-timeout` | — | startup-only | 5.0 | `s` | `--metrics-client-timeout` / — | seconds an idle /metrics client is kept before the socket times out, 0 = the built-in 5 s cap |
| `metrics-max-conn-per-ip` | — | startup-only | 0 | `N` | `--metrics-max-conn-per-ip` / — | maximum concurrent /metrics connections from one peer IP, 0 = no per-IP limit |

### system

the daemon's own serving socket: the Modbus listen address

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `listen` | `set system listen` | settable (restart) | 127.0.0.1:5502 | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |
| `log-access` | `set system log-access` | settable | off | `on\|off` | `--log-access` / — | log client connects/disconnects at INFO instead of DEBUG |
| `local-time` | `set system local-time` | settable | off | `on\|off` | `--local-time` / — | log timestamps in the system time zone instead of UTC |
| `control-log-replies` | `set system log-replies` | settable | off | `on\|off` | `--control-log-replies` / — | DEBUG-log the full output of every control command (plainly: the command and its status log) |
| `log-level` | `set system log-level` | settable | INFO | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |

### modbus

the Modbus session the fake serves: the auth scheme its clients must speak

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `modbus-profile` | `set modbus profile` | settable | sun2000 | `\<file>` | `--modbus-profile` / `MODBUS_PROFILE` | device profile JSON (a bare name resolves in shared/profiles/) |
| `modbus-auth` | `set modbus auth` | settable | none | `suite\|none` | `--modbus-auth` / `MODBUS_AUTH` | the Modbus auth scheme: suite (the crypt handshake) or none |
| `modbus-auth-key` | — | startup-only (secret) | — | `KEY` | `--modbus-auth-key` / `MODBUS_AUTH_KEY` | the suite handshake's shared key, min 16 characters (`file:<path>` reads an owner-only file) *(hidden)* |

### write

the Modbus writes the fake accepts from its clients

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `allow-write` | `set write allow` | settable | off | `on\|off` | `--allow-write` / `ALLOW_WRITE` | accept Modbus writes (FC05/06/15/16) from clients; off = every write refused |

### control

the control plane: the target, the tokens, the ops role's RBAC policy, the
trusted peers

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `control-port` | `set control port` | settable | — | `PATH\|PORT` | `--control-port` / `CTL` | control server target: unix socket path |
| `control-token` | — | startup-only (secret) | — | `TOKEN` | `--control-token` / `CONTROL_TOKEN` | require a token on control connections: the client authenticates with {"cmd": "auth", "token":...}; over the unix socket a trusted peer (root, the daemon's own user or --control-trust-uids — SO_PEERCRED) skips the token (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-trust-uids` | `set control trust-uids` | settable | — | `UID,...` | `--control-trust-uids` / `CONTROL_TRUST_UIDS` | extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon's own user are always trusted |
| `control-socket-group` | `set control socket-group` | settable | off | `on\|off` | `--control-socket-group` / `CONTROL_SOCKET_GROUP` | leave the unix control socket group-accessible (chmod 0660 instead of the plain 0600): a local group may speak to the control without being the service user |

### control/ops

the read-only ops role: the second token that scopes its sessions to the
configured verbs (the default: show)

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `control-ops-token` | — | startup-only (secret) | — | `TOKEN` | `--control-ops-token` / `CONTROL_OPS_TOKEN` | a second, read-only control token: sessions authenticating with it may run its policy's verbs only (the default policy: show) (no set/clear, no reset, no shutdown) — the ops shift against the admin key, both audited (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-ops-verbs` | `set control ops verbs` | settable | show | `VERB,...` | `--control-ops-verbs` / `CONTROL_OPS_VERBS` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated |

### metrics

the fake's /metrics endpoint's auth and access: the bearer token the scrape
presents and the client ACL checked at accept

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `metrics-server` | `set metrics enable` | settable | off | `on\|off` | `--metrics-server` / — | the tool's own Prometheus /metrics endpoint (needs a token beyond loopback; the address is --metrics-listen) |
| `metrics-token` | — | startup-only (secret) | — | `TOKEN` | `--metrics-token` / `METRICS_TOKEN` | the metrics bearer token (Authorization: Bearer) — startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `metrics-acl` | `set metrics acl` | settable | any | `any\|none\|IP,...\|file:\<path>` | `--metrics-acl` / `METRICS_ACL` | clients allowed to connect to /metrics: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### audit

the audit trail: the sink, the forwarding, the rotation, the kill switch

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `audit-log` | `set audit log-file` | settable | — | `PATH\|-\|none` | `--audit-log` / `AUDIT_LOG` | the audit trail's file: a path, - for stdout, none = no local file (the forward carries the trail), empty = the XDG state home |
| `audit-forward` | `set audit forward` | settable | none | `none\|syslog\|syslog:/PATH\|udp://HOST\|tcp://HOST` | `--audit-forward` / `AUDIT_FORWARD` | also forward every audit line: the local syslog mirror or a remote collector (the off-box copy) |
| `audit-forward-format` | `set audit forward format` (the console also takes `set audit forward-format`) | settable | rfc5424 | `rfc5424\|cef` | `--audit-forward-format` / `AUDIT_FORWARD_FORMAT` | the remote forward's envelope: RFC5424 (the default) or CEF — the local syslog forms keep the verbatim send |
| `audit-instance` | `set audit instance` | settable | — | `ID` | `--audit-instance` / `AUDIT_INSTANCE` | the audit lines' instance word: the writer daemon's identity — the control port when unset, the override when spelled |
| `no-audit-log` | `set audit disable` | settable | off | `on\|off` | `--no-audit-log` / `NO_AUDIT_LOG` | disable the audit trail entirely |

### audit/rotate

the audit trail's rotation: the size trigger, the UTC-midnight trigger and
the backup count

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `audit-max-mb` | `set audit rotate max-size` | settable | 10.0 | `MB` | `--audit-max-mb` / `AUDIT_MAX_MB` | rotate the audit trail at this size in MB, keeping N backups; 0 = no size rotation |
| `audit-daily` | `set audit rotate daily` | settable | off | `on\|off` | `--audit-daily` / `AUDIT_DAILY` | also rotate the audit trail at UTC midnight |
| `audit-files` | `set audit rotate files` | settable | 3 | `N` | `--audit-files` / `AUDIT_FILES` | rotated audit backups to keep |

### dump

the state dump: the live overrides' file, the restore-on-start

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `dump-path` | `set dump path` | settable | — | `\<file>` | `--dump-path` / `DUMP_PATH` | the state dump file: the live overrides, written on request dump, the graceful shutdown and every dump-interval |
| `dump-key` | — | startup-only (secret) | — | `TEXT` | `--dump-key` / `DUMP_KEY` | the key that seals the state dumps (the reload's state file too) (`file:<path>` reads an owner-only file) *(hidden)* |
| `dump-interval` | `set dump interval` | settable | 0.0 | `s\|off` | `--dump-interval` / `DUMP_INTERVAL` | seconds between the automatic state dumps (the live setting overrides) |
| `restore-on-start` | `set dump restore-on-start` | settable (restart) | off | `on\|off` | `--restore-on-start` / `RESTORE_ON_START` | the dump loads on start (off: on demand with request restore) |
## Show reports

| report | kind | description |
|---|---|---|
| `show connections` | show-only | connected clients: peer, age, requests served |
| `show metrics-acl-table` | show-only | the metrics ACL as its rule chain, one entry per line: allow 0.0.0.0/0 (any), deny 0.0.0.0/0 (none), the whitelist spelled out — or the ip-prefix acl file's own rules with their descs |
| `show registers` | show-only | the loaded profile's register map with the current values |
| `show version` | show-only | the suite version |
| `show config` | show-only (hidden) | the effective configuration as a set-grammar script (the secret knobs render as *** SECRET REMOVED ***) |
| `show knobs` | show-only (hidden) | the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes |
## Inverter profiles

- the fake doesn't hardcode any device layout: the simulator computes **named
  physical values** (`pv-power`, `grid-power`, `battery-soc`, …) and the
  **inverter profile** maps each name onto a register address and encoding.
  The format, the semantics and the shipped devices are documented once in
  `shared/profiles/README.md`.

- `show registers` prints the loaded profile as a table, `set modbus profile <name|path>`
  swaps it live, `--modbus-profile` / `MODBUS_PROFILE` pick it at start;
  `clear modbus profile` returns to the configured map.

## Signals

| signal | effect |
|---|---|
| `SIGHUP` | re-apply the environment layer — all-or-nothing (an invalid value keeps the previous settings); flags are startup-only, the env is the reloadable layer |
| `SIGUSR1` | reset the scenario: all runtime pins, the cloud machine and the Modbus write overlay are dropped, the simulation continues |
| `SIGTERM` / `SIGINT` | graceful shutdown with a session summary (duration, connections, requests, chaos hits) |

## Served registers (the default profile)

| register | meaning |
|---|---|
| **32064** / **32080** | PV power / power limit (I32 W) |
| **32016+** | the string block: per-string voltage/current (a dark string serves 0/0) |
| **37113** | grid power (I32 W, positive = feed-in) |
| **37100+** | smart meter block: status, per-phase voltages/currents, reactive power, power factor, grid frequency; **37119** exported / **37121** imported kWh totals grow through the simulated day |
| **32089** | device status (512 on-grid / 40960 standby at night) |
| **32087** / **32114** / **32106** | temperature (I16, °C×10) / daily and total yield (U32, kWh×100) |
| **37001+** | battery block (power, SoC, lifetime totals) |

- all of the above addresses come from the profile — remap them freely. The
  profile's per-entry **`fc`** picks each entry's address space (`3` holding /
  `4` input for the word types, `1` coils / `2` discrete for `bit` — the four
  spaces are served separately).

- writes stick in overlays: the register writes (FC06/FC16) overlay the
  holding registers, the coil writes (FC05/FC15) the coil space (FC5 demands
  the spec values `0x0000`/`0xFF00`); computed registers are recomputed per
  poll, overlay values win until cleared (`reset`, SIGUSR1, shutdown). A
  malformed frame on an implemented function code is answered with exception
  03, never a silent disconnect.

- **65000–65003** — the modbus-cache diagnostics block (magic `0xCAFE`,
  version, uptime, id): always mocked by the fake, never part of the profile —
  it exists so the scraper's `scraper_cache_*` auto-detection can be exercised
  without a cache. The only address range the fake hardcodes.

## Chaos injection (`--chaos`)

- `--chaos 0.4` (probability, `--seed` for reproducibility) makes the fake
  answer a fraction of requests hostile — garbage, short/lying MBAP lengths,
  wrong transaction/unit ids, stalls, dropouts, raw exceptions — then drop the
  connection.

- unlike the regression suites' scripted EvilInverter this runs unattended:
  point the scraper at it and watch `scraper_modbus_errors_total` climb while
  `scraper_up` flips, with the fake never dying. Tune or disable live (`set chaos off`).

## Audit trail

- the fake itself and both clients append to the **audit log** — on by default
  at the **XDG state home** (`~/.local/state/fake-inverter/audit.log`);
  `--audit-log <file>` renames it, `--no-audit-log` turns it off, `--audit-log -`
  sends it to stdout (the docker logs / journald way — the shipped Dockerfile
  runs with it).

- the whole family is live-settable on the control wire (the cache's shape):
  `set audit log-file <path|-|none>` swaps the sink, `set audit instance <id>`
  renames the writer daemon (`none` returns to the derived control port), `set audit rotate max-size <MB>`
  and `set audit rotate files <N>` re-chain the rotation live, `set audit rotate daily on/off`
  rides too and `set audit disable on/off` is the kill switch (`clear <setting>`
  restores the configured value); the env twins spell the same names
  upper-snake.

- `--audit-forward` mirrors every line — the per-writer hash chain included —
  onward: `syslog` (the local socket auto-scan), `syslog:/path` (an explicit
  socket), `udp://host[:514]` (RFC5426, best-effort) or `tcp://host[:514]`
  (RFC6587 framing) — the **off-box copy** beside the file/stdout sink (the
  F10 answer); the remote envelope rides `--audit-forward-format` (`rfc5424`,
  the default, or `cef`), a send failure notes once and the next event
  re-arms.

- `--audit-log none` turns the local file off: with a forward spelled that is
  the **remote-only mode** (the collector is the sole holder, the chain
  reseeds at GENESIS per run), without one the audit is disabled (the state
  `--no-audit-log` spells).

- the line names its writer — the fake `application=INV tag=daemon`, the ctl
  and cli clients the shared `application=INV tag=cli` role — and carries an
  `instance=<id>` word naming the writer daemon: the **control port** when
  `--audit-instance` is unset (unique per host by construction), the override
  when spelled. Keep an override unique among everything that shares one
  collector — the native line and CEF carry no hostname, so pooled trails name
  their instances apart; the chain groups by the triple.

    2026-11-03T20:10:06Z AUDIT application=INV tag=daemon instance=15991 type=start hash=3f9a21c04de7 version=0.5.1 modbus=127.0.0.1:5502 control=127.0.0.1:15991 profile=sun2000 description='…'
    2026-11-03T20:10:07Z AUDIT application=INV tag=daemon instance=15991 type=command hash=9c41e2b7a058 peer=127.0.0.1:54425 cmd='set soc 40' result=ok
    2026-11-03T20:10:08Z AUDIT application=INV tag=daemon instance=15991 type=reset hash=77b0c4e19d23 signal=SIGUSR1 pins=1 coils=0 overlay=0
    2026-11-03T20:10:08Z AUDIT application=INV tag=daemon instance=15991 type=shutdown hash=5e2af8c30b61 reason=SIGTERM-received uptime=2s conns=0 requests=0 chaos_hits=0

- the 12-hex token after the event name is the entry's **chained hash** (the
  audit's F10): any edit, deletion or reordering shows up as a chain break in
  `dev/gates/audit_verify.py`. **Every wire command is audited once, by the
  server** (with the peer, the role, the mac); the clients audit their session
  and the local-only events; the fake logs its lifecycle (`START`, `RELOAD`,
  `RESET`, `SHUTDOWN`). ping/pong keepalives are never logged; the file is
  flushed per event.

## Testing

- the fake is the suites' workhorse — it is exercised from the suite root
  `dev/suites/`. Every scenario must end with the fake alive and **zero
  tracebacks** in the logs.

    dev/battery/battery.py inverter        # the inverter profile: the fake's regtest, the
                                      #   control fuzz, the audit chain (the suites refuse
                                      #   without the runner's PV_RUN_DIR)

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.
