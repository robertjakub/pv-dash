# The fake-inverter manual (MANUAL.md)

A dependency-free (Python stdlib only) Modbus TCP server that plays an
inverter — the battery, the smart meter, the diagnostics — for the family to
develop and test against. Part of the pv-suite family. The daemon's own
`--help` and the man page (`modbus-fake-inverter --man`) carry the startup
surface; this page carries the control wire. **Generated** from
`lib/options.json` (the one-knob-one-source rows) by `scripts/gen_manual.py`
— edit the registry and re-run, never this file.

## Speaking to the daemon

The control server is a JSON-lines listener: a unix socket (the default
`/tmp/fake-inverter-5502.socket`) or a TCP port on 127.0.0.1 — the
`--control-port` flag, env `CTL`, `0` = off. Two clients speak it:

    python3 bin/modbus-fake-ctl.py --control-port 15599 show registers
    python3 bin/modbus-fake-cli.py

- the **ctl** runs one command per invocation (or a batch on stdin);
- the **cli** is the interactive console: `?` lists the words, TAB completes,
  `help <setting>` describes one, `help config` maps every knob to its control
  command, `show knobs` prints the dictionary.

The fake keeps its trusted-LAN posture (F11): control works over TCP without
a token too; over the unix socket a trusted peer (root, the daemon's own
user or `--control-trust-uids` — SO_PEERCRED) always speaks without one.

The optional ops token (`--control-ops-token`) scopes a session to the
read-only verbs (the default: show). Every command is audited. The clients
take `--control-port` (env `CTL`), `--timeout`, `--control-token`, the audit
flags and `--man`; the cli adds `--reconnect` / `--reconnect-wait`.

A knob's value resolves at start as flag > env > config script > default;
the config file (the bundled `inverter/examples/modbus-fake-inverter.conf`)
speaks the same grammar — `set <name> <value>` lines in the registry's flat
keys, `--dry-run` prints the effective settings. No defaults live in these
tables: `show config` prints the effective values, the READMEs are the
reference.

The kinds — every row of the tables below carries one:

- **command** — a one-shot action, no value.
- **namespace** — a word that groups deeper words: the console walk lists its
  children, `help <namespace>` describes them.
- **settable** — the knob is live: `set <name> <value>` applies at once (the
  flat registry name; the console also completes the row's live/alias path
  spellings and translates), `clear <name>` returns the configured value,
  `show <name>` prints the live value. *(restart)* — the set records a pending
  value and `request reload` applies it. *(secret)* — the value never renders
  back (show answers err); pass it by flag/env or as `file:<path>`. *(hidden)*
  — never lists in the ?/TAB pools; the wire still answers.
- **startup-only** — flag/env/config at start, a restart applies a change; the
  wire has no set/clear/show for it (it renders in `show config` only). Every
  secret is startup-only now (the tokens, the auth keys, the dump key): the
  wire refuses set/clear outright, the value passes by flag/env/config or as
  `file:<path>` and a restart applies it.
- **show-only** — a runtime report: `show <report>` answers, nothing to set.

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
| `request reload` | command | save the live overrides and restart the whole daemon (the flags and the env are re-resolved) |
| `request reload-config` | command | re-read the config file (the values re-apply over the running machines) |
| `request restore` | command (hidden) | re-apply a state dump's overrides (when the fake has a dump path) |
| `reset` | command | clear all pins + the write overlay |
| `set` | command | configure a setting (set soc auto, set scenario noon) |
| `show` | command | print a setting's live value, or a report |
| `shutdown` | command | stop the server (asks to confirm) |
| `clear` | command | restore a setting to its configured value (clear pv, clear seed) |
| `set register \<addr> \<value>` | command | the Modbus write emulation: plant a register value in the write overlay — reads answer it, reset clears it |
| `set coil \<addr> \<0\|1>` | command | the write emulation: plant a coil value (the coil space, FC1/FC5/FC15 see it, reset clears it) |
| `set discrete \<addr> \<0\|1>` | command | the write emulation: plant a discrete-input value (the discrete space, FC2 sees it, reset clears it) |

## Knobs

The tables spell the knob's registry key — the one internal name the wire,
the replies and the dispatch take; the set / clear column spells the console
words (the live path as words — the config files and the state dumps speak
them; the flat registry name answers the same set everywhere, the ctls
translate). The namespaces group them.

### general

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `pv` | `set pv` | settable | `W\|auto` | — / — | pin the PV power in W, or auto |
| `load` | `set load` | settable | `W\|auto` | — / — | pin the home load in W, or auto |
| `batt` | `set batt` | settable | `W\|auto` | — / — | pin the battery power in W (+charge/-discharge), or auto |
| `grid` | `set grid` | settable | `W\|auto` | — / — | pin the grid power in W (+export/-import), or auto; the battery balances |
| `soc` | `set soc` | settable | `%\|auto` | — / — | pin the state of charge (seeds the machine), or auto |
| `mppt` | `set mppt` | settable | `both\|east\|west\|none` | — / — | enabled PV strings: string-1 = the east array, string-2 = the west |
| `cloud` | `set cloud` | settable | `0..1\|clear\|autumn\|spring\|winter` | — / — | scale the PV: 0 = clear, 1 = dark, clear, or a cloud machine |
| `scenario` | `set scenario` | settable | `morning\|noon\|evening\|night\|custom` | — / — | preset scene; releases the value pins |
| `battery-state` | `set battery-state` | settable | `auto\|charging\|discharging` | — / — | force the battery state machine, or auto |
| `grid-outage` | `set grid-outage` | settable | `on\|off\|outage` | — / — | the grid-outage machine: random blackouts over the simulated clock |
| `unit` | — | startup-only | `ID` | `--unit` / — | modbus unit id served |
| `max-kwp` | `set max-kwp` | settable | `kW` | `--max-kwp` / `MAX_KWP` | PV array size (peak = 75 % of it) |
| `timezone` | `set timezone` | settable | `utc\|local` | `--timezone` / — | clock the state machines integrate over: UTC or the local wall clock |
| `time` | `set time` | settable | `HH:MM\|auto` | `--time` / `TIME` | freeze the clock HH:MM (jumps integrate the battery), or auto |
| `time-scale` | `set time-scale` | settable | `N\|1` | `--time-scale` / `TIME_SCALE` | the simulated clock speed: N× real time — the machines integrate over it |
| `static` | `set static` | settable | `on\|off` | `--static` / — | constant demo values instead of the day simulation |
| `battery-kwh` | `set battery-kwh` | settable | `kWh` | `--battery-kwh` / — | usable battery capacity |
| `strict` | `set strict` | settable | `on\|off` | `--strict` / `STRICT` | reject undefined registers with exception 02 |
| `chaos` | `set chaos` | settable | `0..1\|off` | `--chaos` / `CHAOS` | hostile-reply probability; off = disable |
| `grid-voltage` | `set grid-voltage` | settable | `V` | `--grid-voltage` / — | nominal grid phase voltage; the machine wanders ±10 % per phase |
| `grid-voltage-wander` | `set grid-voltage-wander` | settable | `fraction` | `--grid-voltage-wander` / — | the per-phase voltage machine's wander range (a fraction of the nominal; 0 = the flat grid) |
| `grid-frequency` | `set grid-frequency` | settable | `Hz` | `--grid-frequency` / — | nominal grid frequency; the machine wanders around it |
| `grid-frequency-wander` | `set grid-frequency-wander` | settable | `Hz` | `--grid-frequency-wander` / — | the frequency machine's clamp in Hz around the nominal; 0 = the flat frequency |
| `seed` | `set seed` | settable | `N` | `--seed` / — | re-seed the chaos RNG |
| `connect-acl` | `set connect-acl` | settable | `any\|none\|IP,...\|file:\<path>` | `--connect-acl` / `CONNECT_ACL` | the Modbus clients allowed to connect (the cache's connect-acl, mirrored: "any", "none", or a comma-separated IP/CIDR list) |
| `max-clients` | `set max-clients` | settable | `N` | `--max-clients` / `MAX_CLIENTS` | simultaneous Modbus client limit |
| `client-timeout` | `set client-timeout` | settable | `s` | `--client-timeout` / `CLIENT_TIMEOUT` | disconnect Modbus clients silent for this long |
| `max-conn-per-ip` | `set max-conn-per-ip` | settable | `N` | `--max-conn-per-ip` / `MAX_CONN_PER_IP` | simultaneous Modbus connections from one peer IP |
| `metrics-listen` | — | startup-only | `HOST:PORT` | `--metrics-listen` / — | the metrics bind address HOST:PORT |
| `metrics-max-clients` | — | startup-only | `N` | `--metrics-max-clients` / — | maximum concurrent /metrics clients; extras get an immediate 503, 0 = unlimited |
| `metrics-client-timeout` | — | startup-only | `s` | `--metrics-client-timeout` / — | seconds an idle /metrics client is kept before the socket times out, 0 = the built-in 5 s cap |
| `metrics-max-conn-per-ip` | — | startup-only | `N` | `--metrics-max-conn-per-ip` / — | maximum concurrent /metrics connections from one peer IP, 0 = no per-IP limit |

### system

the daemon's own serving socket: the Modbus listen address

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `listen` | `set system listen` | settable (restart) | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |
| `log-access` | `set system log-access` | settable | `on\|off` | `--log-access` / — | log client connects/disconnects at INFO instead of DEBUG |
| `local-time` | `set system local-time` | settable | `on\|off` | `--local-time` / — | log timestamps in the system time zone instead of UTC |
| `control-log-replies` | `set system log-replies` | settable | `on\|off` | `--control-log-replies` / — | DEBUG-log the full output of every control command (plainly: the command and its status log) |
| `log-level` | `set system log-level` | settable | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |

### modbus

the Modbus session the fake serves: the auth scheme its clients must speak

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `modbus-profile` | `set modbus profile` | settable | `\<file>` | `--modbus-profile` / `MODBUS_PROFILE` | inverter profile (JSON: name -> register + optional type/scale) |
| `modbus-auth` | `set modbus auth` | settable | `suite\|none` | `--modbus-auth` / `MODBUS_AUTH` | the auth scheme the fake's Modbus clients must speak: suite (the crypt handshake) or none |
| `modbus-auth-key` | — | startup-only (secret) | `KEY` | `--modbus-auth-key` / `MODBUS_AUTH_KEY` | the suite handshake's shared key, min 16 characters (`file:<path>` reads an owner-only file) *(hidden)* |

### write

the Modbus writes the fake accepts from its clients

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `allow-write` | `set write allow` | settable | `on\|off` | `--allow-write` / `ALLOW_WRITE` | accept Modbus writes (FC05/06/15/16) from clients; off = every write refused |

### control

the control plane: the tokens, the ops role's RBAC policy, the trusted peers

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `control-port` | `set control port` | settable | `PATH\|PORT` | `--control-port` / `CTL` | control server target: unix socket path |
| `control-token` | — | startup-only (secret) | `TOKEN` | `--control-token` / `CONTROL_TOKEN` | require a token on control connections: the client authenticates with {"cmd": "auth", "token":...}; over the unix socket a trusted peer (root, the daemon's own user or --control-trust-uids — SO_PEERCRED) skips the token (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-trust-uids` | `set control trust-uids` | settable | `UID,...` | `--control-trust-uids` / `CONTROL_TRUST_UIDS` | extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon's own user are always trusted (env CONTROL_TRUST_UIDS) |
| `control-socket-group` | `set control socket-group` | settable | `on\|off` | `--control-socket-group` / `CONTROL_SOCKET_GROUP` | leave the unix control socket group-accessible (chmod 0660 instead of the plain 0600): a local group may speak to the control without being the service user |

### control/ops

the read-only ops role: the second token that scopes its sessions to the
configured verbs (the default: show)

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `control-ops-token` | — | startup-only (secret) | `TOKEN` | `--control-ops-token` / `CONTROL_OPS_TOKEN` | a second, read-only control token: sessions authenticating with it may run its policy's verbs only (the default policy: show) (no set/clear, no reset, no shutdown) — the ops shift against the admin key, both audited (env CONTROL_OPS_TOKEN) (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-ops-verbs` | `set control ops verbs` | settable | `VERB,...` | `--control-ops-verbs` / `CONTROL_OPS_VERBS` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated |

### metrics

the fake's /metrics endpoint's auth and access: the bearer token the scrape
presents and the client ACL checked at accept

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `metrics-server` | `set metrics enable` | settable | `on\|off` | `--metrics-server` / — | the fake's own Prometheus /metrics endpoint (needs a token beyond loopback; the address is --metrics-listen) |
| `metrics-token` | — | startup-only (secret) | `TOKEN` | `--metrics-token` / `METRICS_TOKEN` | require Authorization: Bearer \<token> on the /metrics endpoint (the same scheme the scraper speaks) — startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `metrics-acl` | `set metrics acl` | settable | `any\|none\|IP,...\|file:\<path>` | `--metrics-acl` / `METRICS_ACL` | clients allowed to connect to /metrics: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### audit

the INV audit trail: the sink, the forwarding, the rotation, the kill switch

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `audit-log` | `set audit log-file` | settable | `PATH\|-\|none` | `--audit-log` / `AUDIT_LOG` | INV audit trail: a file path or - for stdout (the docker/journald way); `none` = no local file (the forward carries the trail); the XDG state home when unset |
| `audit-forward` | `set audit forward` | settable | `none\|syslog\|syslog:/PATH\|udp://HOST\|tcp://HOST` | `--audit-forward` / `AUDIT_FORWARD` | also forward every audit line: the local syslog mirror or a remote collector (the off-box copy) |
| `audit-forward-format` | `set audit forward format` (the console also takes `set audit forward-format`) | settable | `rfc5424\|cef` | `--audit-forward-format` / `AUDIT_FORWARD_FORMAT` | the remote forward's envelope: RFC5424 (the default) or CEF — the local syslog forms keep the verbatim send |
| `audit-instance` | `set audit instance` | settable | `ID` | `--audit-instance` / `AUDIT_INSTANCE` | the audit lines' instance word: the writer daemon's identity — the control port when unset, the override when spelled |
| `no-audit-log` | `set audit disable` | settable | `on\|off` | `--no-audit-log` / `NO_AUDIT_LOG` | disable the INV audit trail |

### audit/rotate

the audit trail's rotation: the size trigger, the UTC-midnight trigger and
the backup count

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `audit-max-mb` | `set audit rotate max-size` | settable | `MB` | `--audit-max-mb` / `AUDIT_MAX_MB` | rotate the audit trail at this size in MB, keeping N backups; 0 = no size rotation |
| `audit-daily` | `set audit rotate daily` | settable | `on\|off` | `--audit-daily` / `AUDIT_DAILY` | also rotate the audit trail at UTC midnight |
| `audit-files` | `set audit rotate files` | settable | `N` | `--audit-files` / `AUDIT_FILES` | rotated audit backups to keep |

### dump

the state dump: the live overrides' file, the restore-on-start

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `dump-path` | `set dump path` | settable | `\<file>` | `--dump-path` / `DUMP_PATH` | the state dump file: the live overrides, written on request dump, the graceful shutdown and every dump-interval |
| `dump-key` | — | startup-only (secret) | `TEXT` | `--dump-key` / `DUMP_KEY` | the key that seals the state dumps (the reload's state file too) (`file:<path>` reads an owner-only file) *(hidden)* |
| `dump-interval` | `set dump interval` | settable | `s\|off` | `--dump-interval` / `DUMP_INTERVAL` | seconds between the automatic state dumps (the live setting overrides) |
| `restore-on-start` | `set dump restore-on-start` | settable (restart) | `on\|off` | `--restore-on-start` / `RESTORE_ON_START` | the dump loads on start (off: on demand with request restore) |

## Show reports

| report | kind | description |
|---|---|---|
| `show connections` | show-only | connected clients: peer, age, requests served |
| `show metrics-acl-table` | show-only | the metrics ACL as its rule chain, one entry per line (the metrics/acl report) |
| `show registers` | show-only | the loaded profile's register map with the current values |
| `show version` | show-only | the fake-inverter version |
| `show config` | show-only (hidden) | the effective configuration as a set-grammar script (the secret knobs render as *** SECRET REMOVED ***) |
| `show knobs` | show-only (hidden) | the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes |

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.

