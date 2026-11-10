# The modbus-scraper manual (MANUAL.md)

A dependency-free (Python stdlib only) Prometheus exporter that polls a
Modbus device and exposes the metrics at /metrics. Part of the pv-suite
family. The daemon's own `--help` and the man page (`modbus-scraper --man`)
carry the startup surface; this page carries the control wire. **Generated**
from `lib/options.json` (the one-knob-one-source rows) by
`scripts/gen_manual.py` — edit the registry and re-run, never this file.

## Speaking to the daemon

The control server is a JSON-lines listener: a unix socket (the default
`/tmp/modbus-scraper-9350.socket`) or a TCP port on 127.0.0.1 — the
`--control-port` flag, env `CTL`, `0` = off. Two clients speak it:

    python3 bin/modbus-scraper-ctl.py --control-port 15509 poll now
    python3 bin/modbus-scraper-cli.py

- the **ctl** runs one command per invocation (or a batch on stdin);
- the **cli** is the interactive console: `?` lists the words, TAB completes,
  `help <setting>` describes one, `help config` maps every knob to its control
  command, `show knobs` prints the dictionary.

TCP control demands the token (`--control-token` / env `CONTROL_TOKEN`; the
wire's `auth` verb carries it) and refuses to start without one; over the
unix socket a trusted peer (root, the daemon's own user or
`--control-trust-uids` — SO_PEERCRED) speaks without it.

The optional ops token (`--control-ops-token`) scopes a session to the
read-only verbs (the default: show). Every command is audited. The clients
take `--control-port` (env `CTL`), `--timeout`, `--control-token`, the audit
flags and `--man`; the cli adds `--reconnect` / `--reconnect-wait`.

A knob's value resolves at start as flag > env > config script > default;
the config file (the bundled `scraper/examples/scraper.conf`) speaks the
same grammar — `set <name> <value>` lines in the registry's flat keys,
`--dry-run` prints the effective settings. No defaults live in these tables:
`show config` prints the effective values, the READMEs are the reference.

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
| `help` | command (internal) | describe a word (help \<setting>) or map every knob (help config) |
| `inspect` | command | one pretty dump of everything (the state, the counters, the caps) |
| `ping` | command (internal) | keep-alive: answers pong |
| `poll` | namespace | the poll loop's manual wake |
| `poll now` | command | wake the poll loop immediately |
| `quit` | command | close the session |
| `request` | namespace | the state machinery: the dump written and restored, the config re-read, the session dropped |
| `request dump` | command | write the state dump: the live setting overrides, sealed (when the daemon has a dump path) |
| `request reload` | command | save the live overrides and restart the whole daemon (the config file and the flags are re-resolved) |
| `request reload-config` | command | re-read the config file (the SIGHUP path) |
| `request restart` | command | drop the Modbus session (reconnects on the next poll) |
| `request restore` | command | re-apply a state dump's overrides (when the daemon has a dump path) |
| `set` | command | configure a setting (set metrics interval 5, set log-access on) |
| `show` | command | print a setting's live value, or a report |
| `shutdown` | command | stop the scraper (asks to confirm) |
| `clear` | command | restore a setting to its configured value (clear metrics interval, clear log-level) |

## Knobs

The tables spell the knob's registry key — the one internal name the wire,
the replies and the dispatch take; the set / clear column spells the console
words (the live path as words — the config files and the state dumps speak
them; the flat registry name answers the same set everywhere, the ctls
translate). The namespaces group them.

### general

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `local-time` | `set local-time` | settable | `on\|off` | `--local-time` / `LOCAL_TIME` | log timestamps in the system time zone instead of UTC |
| `log-access` | `set log-access` | settable | `on\|off` | `--log-access` / `LOG_ACCESS` | log every HTTP request at INFO |
| `log-level` | `set log-level` | settable | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |
| `dump-interval` | `set dump-interval` | settable | `s\|off` | `--dump-interval` / `DUMP_INTERVAL` | seconds between the automatic state dumps (the live setting overrides) |

### modbus

the inverter Modbus settings

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `upstream` | `set modbus upstream` | settable | `HOST:PORT` | `--upstream` / `UPSTREAM` | the inverter Modbus endpoint |
| `modbus-unit` | `set modbus unit` | settable | `ID` | `--modbus-unit` / `MODBUS_UNIT` | Modbus unit ID |
| `modbus-offset` | `set modbus offset` | settable | `N` | `--modbus-offset` / `MODBUS_OFFSET` | added to register addresses |
| `modbus-auth` | `set modbus auth` | settable | `suite\|none` | `--modbus-auth` / `MODBUS_AUTH` | the auth settings: the Modbus scheme the poll session speaks (modbus auth — suite or none) and the bearer token the metrics endpoint requires (auth token) |
| `auth-key` | — | startup-only (secret) | `KEY` | `--auth-key` / `AUTH_KEY` | the suite handshake's shared key, min 16 characters (`file:<path>` reads an owner-only file) *(hidden)* |
| `timeout` | `set modbus timeout` | settable | `s` | `--timeout` / `TIMEOUT` | Modbus connect/read timeout |
| `profile` | `set modbus profile` | settable | `\<file>` | `--profile` / `PROFILE` | device profile JSON: the registers the metrics read (a bare name resolves in profiles/profiles/) |
| `grid-positive-import` | `set modbus grid-positive-import` | settable | `on\|off` | `--grid-positive-import` / `GRID_POSITIVE_IMPORT` | grid register positive when importing |

### metrics

the Prometheus /metrics exposition: the listen address, the poll interval,
the serving limits, the bearer auth, the connect ACL, the spec and the
prefix

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `metrics-spec` | `set metrics filter` | settable | `PATH\|-` | `--metrics-spec` / `METRICS_SPEC` | metrics spec JSON, sectioned: {inputs: {name: {help}}, metrics: {key: {profile?, expr?, when?, help, type?}}, scraper:...} — the metrics entries are register- (profile) or expression-fed (expr/when) over the declared inputs (show inputs), merged in memory over the built-in lib/metrics.json scraper_* block |
| `metric-prefix` | `set metrics prefix` | settable | `PREFIX` | `--metric-prefix` / `METRIC_PREFIX` | the prefix on the profile- and compute-fed metric names |
| `metrics-acl` | `set metrics acl` | settable | `any\|none\|IP,...\|file:\<path>` | `--metrics-acl` / `METRICS_ACL` | clients allowed to connect to /metrics: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |
| `interval` | `set metrics interval` | settable | `s` | `--interval` / `INTERVAL` | seconds between polls of the inverter |

### caps

the display caps the percentages clamp to: the PV array and the grid
ceilings

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `max-kwp` | `set caps max-pv` | settable | `KW` | `--max-kwp` / `MAX_KWP` | maximum PV array kWp |
| `max-grid-kw` | `set caps max-grid` | settable | `KW` | `--max-grid-kw` / `MAX_GRID_KW` | maximum grid kW, either direction |

### system

the daemon's own serving socket: the listen address

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `listen` | `set system listen` (the console also takes `set metrics listen`) | settable (restart) | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |

### metrics/limits

the /metrics serving limits (the client caps and the idle timeouts)

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `max-clients` | `set metrics limits max-clients` | settable | `N` | `--max-clients` / `MAX_CLIENTS` | simultaneous HTTP clients on /metrics; extras get an immediate 503 |
| `client-timeout` | `set metrics limits timeout` | settable | `s` | `--client-timeout` / `CLIENT_TIMEOUT` | kick idle keep-alive HTTP clients after this long |
| `max-conn-per-ip` | `set metrics limits max-conn-per-ip` | settable | `N` | `--max-conn-per-ip` / `MAX_CONN_PER_IP` | simultaneous HTTP connections from one peer IP |

### control

the control plane: the tokens, the ops role's RBAC policy, the trusted peers

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `control-port` | `set control port` | settable | `PATH\|PORT` | `--control-port` / `CTL` | JSON-lines control server target: unix socket path |
| `control-token` | — | startup-only (secret) | `TOKEN` | `--control-token` / `CONTROL_TOKEN` | require a token on control connections: the client authenticates with {"cmd": "auth", "token":...}; over the unix socket a trusted peer (root, the daemon's own user or --control-trust-uids — SO_PEERCRED) skips the token (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-trust-uids` | `set control trust-uids` | settable | `UID,...` | `--control-trust-uids` / `CONTROL_TRUST_UIDS` | extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon's own user are always trusted |
| `control-socket-group` | `set control socket-group` | settable | `on\|off` | `--control-socket-group` / `CONTROL_SOCKET_GROUP` | leave the unix control socket group-accessible (chmod 0660 instead of the plain 0600) |

### control/ops

the read-only ops role: the second token that scopes its sessions to the
configured verbs (the default: show)

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `control-ops-token` | — | startup-only (secret) | `TOKEN` | `--control-ops-token` / `CONTROL_OPS_TOKEN` | a second, read-only control token: sessions authenticating with it may run its policy's verbs only (the default policy: show) (no set/clear, no poll now, no request reload, no restart, no shutdown) — the ops shift against the admin key, both audited (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-ops-verbs` | `set control ops verbs` | settable | `VERB,...` | `--control-ops-verbs` / `CONTROL_OPS_VERBS` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated |

### metrics/auth

the /metrics bearer auth: the token the exposition endpoint requires

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `auth-token` | — | startup-only (secret) | `TOKEN` | `--auth-token` / `AUTH_TOKEN` | require Authorization: Bearer \<token> on all requests — startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |

### audit

the SCR audit trail: the sink, the forwarding, the rotation, the kill switch

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `audit-log` | `set audit log-file` | settable | `PATH\|-\|none` | `--audit-log` / `AUDIT_LOG` | SCR audit trail: a file path or - for stdout (the docker/journald way); `none` = no local file (the forward carries the trail); default: the XDG state home (~/.local/state/modbus-scraper/audit.log) |
| `audit-forward` | `set audit forward` | settable | `none\|syslog\|syslog:/PATH\|udp://HOST\|tcp://HOST` | `--audit-forward` / `AUDIT_FORWARD` | also forward every audit line: the local syslog mirror or a remote collector (the off-box copy) |
| `audit-forward-format` | `set audit forward format` (the console also takes `set audit forward-format`) | settable | `rfc5424\|cef` | `--audit-forward-format` / `AUDIT_FORWARD_FORMAT` | the remote forward's envelope: RFC5424 (the default) or CEF — the local syslog forms keep the verbatim send |
| `no-audit-log` | `set audit disable` | settable | `on\|off` | `--no-audit-log` / `NO_AUDIT_LOG` | disable the SCR audit trail |

### audit/rotate

the audit trail's rotation: the size trigger and the backup count

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `audit-max-mb` | `set audit rotate max-size` | settable | `MB` | `--audit-max-mb` / `AUDIT_MAX_MB` | rotate the audit log at this size in MB, keeping N backups; 0 = no size rotation |
| `audit-daily` | `set audit rotate daily` | settable | `on\|off` | `--audit-daily` / `AUDIT_DAILY` | also rotate the audit log at UTC midnight |
| `audit-files` | `set audit rotate files` | settable | `N` | `--audit-files` / `AUDIT_FILES` | rotated audit backups to keep |

### dump

the state dump: the live overrides' file, the restore-on-start

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `dump-path` | `set dump path` | settable | `\<file>` | `--dump-path` / `DUMP_PATH` | the state dump file: the live overrides, written on request dump, the graceful shutdown and every dump-interval |
| `dump-key` | — | startup-only (secret) | `TEXT` | `--dump-key` / `DUMP_KEY` | the key that seals the state dumps (the reload's state file too) (`file:<path>` reads an owner-only file) *(hidden)* |
| `restore-on-start` | `set dump restore-on-start` | settable (restart) | `on\|off` | `--restore-on-start` / `RESTORE_ON_START` | the dump loads on start (off: on demand with request restore) |

## Show reports

| report | kind | description |
|---|---|---|
| `show connections` | show-only | the live HTTP clients of /metrics: the gate counters, one row per peer IP |
| `show version` | show-only | the modbus-scraper version |
| `show config` | show-only | the effective configuration as a set-grammar script (the secret knobs render as *** SECRET REMOVED ***) |
| `show knobs` | show-only | the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes |
| `show inputs` | show-only | the declared compute expression inputs (the reserved four and the spec's declared entries), each bracketed with the metric whose value it carries |
| `show inputs-metrics` | show-only | the exported metrics: one [section]-bracketed line per metric the exposition serves (the built-in scraper_* block included), sorted by name |
| `show metrics-acl-table` | show-only | the metrics ACL as its rule chain, one entry per line: allow 0.0.0.0/0 (any), deny 0.0.0.0/0 (none), the whitelist spelled out — or the ip-prefix acl file's own rules with their descs |

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.

