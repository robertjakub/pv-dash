# The modbus-scraper manual

A dependency-free (Python stdlib only) Prometheus exporter that polls a
Modbus device and exposes the metrics at /metrics. Part of the pv-suite
family.

## The family

- the scraper is the chain's poller: **Modbus in, Prometheus out** — through
  the cache (the usual shape: the cache multiplexes the device) or straight at
  the device when nothing else shares it.

    the device (the sun2000 — or the fake standing in)
         |  Modbus TCP :502
         v
    modbus-cache :15502 ---- the one client slot, multiplexed
         |
         v
    modbus-scraper :9350 /metrics
         |
         v
    prometheus ---- the alert pack (extras/alerts/)
         |
         v
    the dashboard :8080

    modbus-replay rides beside any Modbus hop: the tap in capture,
    the recorded device in replay, the dump tool rendering.

- every hop is optional: the scraper can poll the device straight (no cache),
  the dashboard can read a collector you already run, the fake can stand in
  for the device — and the suite auth can run on either Modbus hop
  independently (the peers must speak the same scheme with the same key).

## Run it

    python3 apps/scraper/bin/modbus-scraper.py --upstream 192.168.1.100:502
    curl http://localhost:9350/metrics

- the exporter **binds to 127.0.0.1:9350** (loopback only) — pass `--listen 0.0.0.0:9350`
  when Prometheus scrapes from another host. **Beyond loopback a token is
  mandatory**: a non-loopback listen without `--auth-token` **refuses to
  start** (one clean line, no traceback — the audit's F13); the loopback
  default needs no token.

- add **`--dry-run`** to validate the configuration and print the effective
  settings without binding the port or contacting the inverter. Exit codes:
  `0` = valid, `1` = invalid (reason on stderr), `2` = command-line misuse.

- settings resolve flag > env (the same names, bare — no tool prefix:
  `CONFIG`, `UPSTREAM`, `MODBUS_UNIT`, `LISTEN`, `AUTH_TOKEN`, … the full twin
  set is the generated `docker/env/modbus-scraper.env.example`) > config
  script (`--config` picks the file; the default hunt: `$CONFIG`, then
  `modbus-scraper.conf` next to the script, then the subproject root's sample
  — a missing file is fine) > built-in defaults.

- every setting is **sanitized and validated** before use — a malformed config
  file is fatal, nonsense values abort with a clean one-line error instead of
  failing later at runtime. The only soft spot is `timeout > interval`: that
  logs a warning (polls run back-to-back) instead of failing.

- the bundled `examples/modbus-scraper.conf` is a sample in the set grammar —
  GENERATED (`dev/generators/examples.py`) from `lib/options.json`, every knob
  the registry declares, every line commented at its default; `show config`
  regenerates the script from the running scraper (secrets hidden).

- the register map — addresses, types, gains, function codes — comes from the
  device profile **alone**; there are no register override knobs.

## How it works

The scraper is a loop and a page: the poller walks the device profile, the
exposition answers Prometheus — and `metrics.json` names everything that
appears.

- a poll loop reads the device profile's registers every `--modbus-interval`
  seconds; the source ranges merge into as few **block reads** as the
  `--modbus-merge-gap` allows (a failed block splits to its sources — `show uplink`
  renders the plan and its latency).

- the reading passes **sanity caps** (`--max-kwp`, `--max-grid-kw`): bad data
  answers **HTTP 503** with `# Error collecting metrics from inverter` until a
  good poll, never silently wrong numbers.

- the exposition serves the profile- and compute-fed names (the
  `--metrics-prefix` prefix, default `huawei_`) and the fixed `scraper_*`
  self-observability gauges.

## The control plane

- the cli ships beside the daemon (`bin/modbus-scraper-cli.py`, its own man
  page via `--man`) — the same client the suites drive; every word below is
  its spelling.

- it is one script for the family: the installed client names are **symlinks
  to `apps/pvsuite-cli.py`** and the tool comes from the name it was invoked
  as; a bare `pvsuite-cli` takes the tool as the first word (the daemon name
  or the short alias — `cache`, `scraper`, `inverter`; `dashboard` is its own
  alias), and a word that disagrees with the invocation name is refused.

- the control server is a JSON-lines listener: a unix socket (the default
  `/tmp/modbus-scraper-9350.socket`) or a TCP port on 127.0.0.1 — the
  `--control-port` flag, env `CTL`, `0` = off.

    python3 bin/modbus-scraper-cli.py --control-port 15509 request poll now
    python3 bin/modbus-scraper-cli.py

- the one-shot spelling runs one command per invocation (or a batch on stdin).

- the wire is **JSON lines**: one request per line, one reply per line — the
  reply's `status` face speaks `ok` / `fail` / `bye` (the closing) with a
  `note` where the row says one; the `auth` verb carries the token, and a
  signed wire authenticates each frame with an HMAC mac (the audit lines carry
  it beside the command).

- the **console** is the interactive session: `?` lists the words, TAB
  completes, `help <setting>` describes one, `help config` maps every knob to
  its control command, `show knobs` prints the dictionary.

- TCP control demands the token (`--control-token` / env `CONTROL_TOKEN`; the
  wire's `auth` verb carries it) and refuses to start without one; over the
  unix socket a trusted peer (root, the daemon's own user or
  `--control-trust-uids` — SO_PEERCRED) speaks without it.

- the optional ops token (`--control-ops-token`) scopes a session to the
  read-only verbs (the default: show). Every command is audited. The clients
  take `--control-port` (env `CTL`), `--timeout`, `--control-token`, the audit
  flags and `--man`; the cli adds `--reconnect` / `--reconnect-wait`.

- a knob's value resolves at start as flag > env > config script > default;
  the config file (the bundled `apps/scraper/examples/modbus-scraper.conf`)
  speaks the same grammar — `set <name> <value>` lines, `--dry-run` prints the
  effective settings.

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
| `help` | command (internal) | describe a word (help \<setting>) or map every knob (help config) |
| `inspect` | command | one pretty dump of everything (the state, the counters, the caps) |
| `ping` | command (internal) | keep-alive: answers pong |
| `quit` | command | close the session |
| `request` | namespace | the state machinery: the dump written and restored, the config re-read, the poll woken, the session dropped |
| `request dump` | command (hidden) | write the state dump: the live setting overrides, sealed (when the daemon has a dump path) |
| `request poll` | namespace | the poll loop's manual wake |
| `request poll now` | command | wake the poll loop immediately |
| `request reload` | command (hidden) | save the live overrides and restart the whole daemon (the config file and the flags are re-resolved) |
| `request reload-config` | command (hidden) | re-read the config file (the SIGHUP path) |
| `request restart` | command (hidden) | drop the Modbus session (reconnects on the next poll) |
| `request restore` | command (hidden) | re-apply a state dump's overrides (when the daemon has a dump path) |
| `set` | command | configure a setting live: set \<setting> \<value> |
| `show` | command | print a setting's live value, or a report |
| `shutdown` | command | stop the server (asks to confirm) |
| `clear` | command | restore a setting to its configured value: clear \<setting> |
## Knobs

The tables spell the knob's registry key — the one internal name the wire,
the replies and the dispatch take; the set / clear column spells the console
words (the live path as words — the config files and the state dumps speak
them; the flat registry name answers the same set everywhere, the clients
translate). The `default` column is the registry's built-in default (the
resolver's last rung after flag > env > config); the namespaces group them.

### modbus

the inverter Modbus settings

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `upstream` | `set modbus upstream` | settable | 127.0.0.1:5502 | `HOST:PORT` | `--upstream` / `UPSTREAM` | the inverter Modbus endpoint |
| `modbus-unit` | `set modbus unit` | settable | 1 | `ID` | `--modbus-unit` / `MODBUS_UNIT` | the Modbus unit id the session speaks |
| `modbus-offset` | `set modbus offset` | settable | 0 | `N` | `--modbus-offset` / `MODBUS_OFFSET` | added to register addresses |
| `modbus-auth` | `set modbus auth` | settable | none | `suite\|waveshare\|none` | `--modbus-auth` / `MODBUS_AUTH` | the auth scheme the scraper speaks to the device: suite (the crypt handshake), waveshare (the gateway connection password) or none |
| `modbus-auth-key` | — | startup-only (secret) | — | `KEY` | `--modbus-auth-key` / `MODBUS_AUTH_KEY` | the key the scraper presents: the suite handshake's shared key (min 16 characters) or the Waveshare gateway password (`file:<path>` reads an owner-only file) *(hidden)* |
| `modbus-timeout` | `set modbus timeout` | settable | 3.0 | `s` | `--modbus-timeout` / `MODBUS_TIMEOUT` | Modbus connect/read timeout in seconds |
| `modbus-read-delay` | `set modbus read-delay` | settable | 0.05 | `s` | `--modbus-read-delay` / `MODBUS_READ_DELAY` | seconds between consecutive device reads within a poll cycle |
| `modbus-merge-gap` | `set modbus merge-gap` | settable | 8 | `registers` | `--modbus-merge-gap` / `MODBUS_MERGE_GAP` | max register gap when merging the profile's source ranges into block reads; the plan rebuilds |
| `modbus-profile` | `set modbus profile` | settable | sun2000 | `\<file>` | `--modbus-profile` / `MODBUS_PROFILE` | device profile JSON (a bare name resolves in shared/profiles/) |
| `grid-positive-import` | `set modbus grid-positive-import` | settable | off | `on\|off` | `--grid-positive-import` / `GRID_POSITIVE_IMPORT` | grid register positive when importing |
| `modbus-interval` | `set modbus interval` | settable | 10.0 | `s` | `--modbus-interval` / `MODBUS_INTERVAL` | seconds between polls of the upstream |

### metrics

the Prometheus /metrics exposition: the listen address, the serving limits,
the bearer auth, the connect ACL, the spec and the prefix

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `metrics-spec` | `set metrics filter` | settable | — | `PATH\|-` | `--metrics-spec` / `METRICS_SPEC` | metrics spec JSON, sectioned: {inputs: {name: {help}}, metrics: {key: {profile?, expr?, when?, help, type?}}, scraper:...} — the metrics entries are register- (profile) or expression-fed (expr/when) over the declared inputs (show inputs), merged in memory over the built-in lib/metrics.json scraper_* block |
| `metrics-prefix` | `set metrics prefix` | settable | huawei | `PREFIX` | `--metrics-prefix` / `METRICS_PREFIX` | the prefix on the profile- and compute-fed metric names |
| `metrics-acl` | `set metrics acl` | settable | any | `any\|none\|IP,...\|file:\<path>` | `--metrics-acl` / `METRICS_ACL` | clients allowed to connect to /metrics: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### modbus/caps

the sanity caps the polled readings must pass: the PV array and the grid
ceilings

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `max-kwp` | `set modbus caps max-pv` | settable | 6.0 | `kW` | `--max-kwp` / `MAX_KWP` | maximum PV array kWp |
| `max-grid-kw` | `set modbus caps max-grid` | settable | 12.0 | `KW` | `--max-grid-kw` / `MAX_GRID_KW` | maximum grid kW, either direction |

### system

the daemon's own serving socket: the listen address

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `listen` | `set system listen` (the console also takes `set metrics listen`) | settable (restart) | 127.0.0.1:9350 | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |
| `local-time` | `set system local-time` | settable | off | `on\|off` | `--local-time` / `LOCAL_TIME` | log timestamps in the system time zone instead of UTC |
| `control-log-replies` | `set system log-replies` | settable | off | `on\|off` | `--control-log-replies` / — | DEBUG-log the full output of every control command (plainly: the command and its status log) |
| `log-access` | `set system log-access` | settable | off | `on\|off` | `--log-access` / `LOG_ACCESS` | log every HTTP request at INFO |
| `log-level` | `set system log-level` | settable | INFO | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |

### metrics/limits

the /metrics serving limits (the client caps and the idle timeouts)

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `metrics-max-clients` | `set metrics limits max-clients` | settable | 64 | `N` | `--metrics-max-clients` / `METRICS_MAX_CLIENTS` | maximum concurrent /metrics clients; extras get an immediate 503, 0 = unlimited |
| `metrics-client-timeout` | `set metrics limits timeout` | settable | 300.0 | `s` | `--metrics-client-timeout` / `METRICS_CLIENT_TIMEOUT` | seconds an idle /metrics client is kept before the socket times out, 0 = the built-in 5 s cap |
| `metrics-max-conn-per-ip` | `set metrics limits max-conn-per-ip` | settable | 0 | `N` | `--metrics-max-conn-per-ip` / `METRICS_MAX_CONN_PER_IP` | maximum concurrent /metrics connections from one peer IP, 0 = no per-IP limit |

### control

the control plane: the target, the tokens, the ops role's RBAC policy, the
trusted peers

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `control-port` | `set control port` | settable | — | `PATH\|PORT` | `--control-port` / `CTL` | control server target: unix socket path or TCP port on 127.0.0.1 |
| `control-token` | — | startup-only (secret) | — | `TOKEN` | `--control-token` / `CONTROL_TOKEN` | require a token on control connections: the client authenticates with {"cmd": "auth", "token":...}; over the unix socket a trusted peer (root, the daemon's own user or --control-trust-uids — SO_PEERCRED) skips the token (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-trust-uids` | `set control trust-uids` | settable | — | `UID,...` | `--control-trust-uids` / `CONTROL_TRUST_UIDS` | extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon's own user are always trusted |
| `control-socket-group` | `set control socket-group` | settable | off | `on\|off` | `--control-socket-group` / `CONTROL_SOCKET_GROUP` | leave the unix control socket group-accessible (chmod 0660 instead of the plain 0600) |

### control/ops

the read-only ops role: the second token that scopes its sessions to the
configured verbs (the default: show)

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `control-ops-token` | — | startup-only (secret) | — | `TOKEN` | `--control-ops-token` / `CONTROL_OPS_TOKEN` | a second, read-only control token: sessions authenticating with it may run its policy's verbs only (the default policy: show) (no set/clear, no request poll now, no request reload, no restart, no shutdown) — the ops shift against the admin key, both audited (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-ops-verbs` | `set control ops verbs` | settable | show | `VERB,...` | `--control-ops-verbs` / `CONTROL_OPS_VERBS` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated |

### metrics/auth

the /metrics bearer auth: the token the exposition endpoint requires

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `auth-token` | — | startup-only (secret) | — | `TOKEN` | `--auth-token` / `AUTH_TOKEN` | require Authorization: Bearer \<token> on all requests — startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |

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
| `show connections` | show-only | the live HTTP clients of /metrics: the gate counters, one row per peer IP |
| `show uplink` | show-only | the inverter link: session counters, per-block latency and errors |
| `show uplink-sources` | show-only | the register map: one row per polled register — fc, register, the range that fetches it, source |
| `show version` | show-only | the suite version |
| `show config` | show-only (hidden) | the effective configuration as a set-grammar script (the secret knobs render as *** SECRET REMOVED ***) |
| `show knobs` | show-only (hidden) | the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes |
| `show inputs` | show-only | the declared compute expression inputs (the reserved four and the spec's declared entries), each bracketed with the metric whose value it carries |
| `show inputs-metrics` | show-only | the exported metrics: one [section]-bracketed line per metric the exposition serves (the built-in scraper_* block included), sorted by name |
| `show metrics-acl-table` | show-only | the metrics ACL as its rule chain, one entry per line: allow 0.0.0.0/0 (any), deny 0.0.0.0/0 (none), the whitelist spelled out — or the ip-prefix acl file's own rules with their descs |
## Signals

| signal | effect |
|---|---|
| `SIGHUP` | reload the configuration without dropping the exporter: poll interval, caps, the device profile, the auth token (+ file re-read = rotation), client limits, the Modbus auth scheme/key and the upstream take effect immediately; an invalid value keeps the previous settings; the listen address and `metrics.json` need a restart (`log-level` is live — `set system log-level`) |
| `SIGTERM` / `SIGINT` | graceful shutdown with a session summary (duration + poll-error count) |

## Configuration

- the config file (`--config` picks it; the default hunt: `$CONFIG`, then
  `modbus-scraper.conf` next to the script, then the subproject root's sample
  — a missing file is fine) speaks the **set grammar** — one `set <name> <value>`
  per line, the control CLI's own spelling; a value resolves flag > env > this
  file > the row's default.

- the bundled `apps/scraper/examples/modbus-scraper.conf` is GENERATED from
  the registry (`dev/generators/examples.py`): every knob declared, every line
  commented at its default — copy it, uncomment what you change, point
  `--config` at it. The env-twin set rides the generated
  `docker/env/modbus-scraper.env.example`.

- a live scraper re-reads the file on `SIGHUP` (a broken file keeps the
  previous settings; the auth token's `file:` form re-reads too — that is the
  rotation story); `show config` regenerates the script from the running
  daemon (secrets hidden) and `--dry-run` prints the effective settings
  without binding anything.

## Runtime control

- the live layer: `set modbus profile <name|path>` swaps the register map at
  runtime (the metric sources rebuild, a profile lacking the power math's
  inputs rolls back cleanly), `set system log-level` is live; `clear <name>`
  returns the configured value, `show <name>` prints the live one, `show inputs`
  / `show inputs-metrics` render the spec.

- the poll cadence and the caps ride the config reload: `request reload-config`
  re-reads the file (the `SIGHUP` twin — interval, caps, the auth token's
  `file:` re-read, the upstream); the restart-marked rows (the listen address,
  the metrics spec) record a pending `set` and fold in on `request reload` or
  a restart.

- `request poll now` forces a poll off-schedule; `restart` restarts the
  exporter in place. Every command is audited once, by the server — the
  ops-token sessions ride the read-only verb policy (no set/clear, no `request poll now`,
  no reload, no restart, no shutdown).

    # live: swap the map, re-read the file, force a poll
    set modbus profile sun2000_full
    request reload-config
    request poll now

## Access control

- the `/metrics` endpoint: **beyond loopback a token is mandatory** — a
  non-loopback listen without `--auth-token` refuses to start (one clean line,
  no traceback — the F13 floor); beside the token the **metrics ACL**
  (`--metrics-acl`, live `set metrics acl`) gates the accept — `any`, `none`,
  a comma-separated IP/CIDR list, or `file:<path>` (the ip-prefix acl file;
  `show metrics-acl-table` renders the chain). An unauthenticated read answers
  401.

- the control plane: TCP control demands the token (`--control-token`, the
  wire's `auth` verb); the optional ops token (`--control-ops-token`) scopes a
  session to the read-only verbs — the ops shift against the admin key, both
  audited.

- the device leg: `--modbus-auth` picks what the scraper *speaks to the
  device* — `suite` (the PVA1 proof-of-key handshake, the key floor 16
  characters) or `waveshare` (the key presented as a Waveshare RS485-to-TCP
  gateway's connection password, non-empty ASCII) — and `--modbus-auth-key`
  carries the shared secret (`file:<path>` the shipped spelling). Scheme and
  key are live-settable; a key set with no scheme stays dormant, and going
  `suite` over a short standing password refuses at start and on the wire.

## Metrics

| metric | meaning |
|---|---|
| `huawei_pv_generation_watts` | PV (inverter input) power |
| `huawei_grid_export_watts` / `huawei_grid_import_watts` | power exported to / imported from the grid (≥ 0) |
| `huawei_home_consumption_watts` | home load, derived as `PV − battery − net grid` |
| `huawei_grid_net_watts` | signed net grid power (debugging aid) |
| `huawei_battery_net_watts` | signed battery power, +charge/−discharge |
| `huawei_battery_charge_watts` / `huawei_battery_discharge_watts` | the split, ≥ 0, for stacked graphs |
| `huawei_battery_soc_percent` | battery state of charge |
| `scraper_up` / `scraper_modbus_errors_total` / `scraper_last_poll_timestamp_seconds` | poller health |
| `scraper_poll_duration_seconds` / `_mean` / `_max` | the last poll cycle's duration and its running mean/maximum |
| `scraper_cache_device_up` / `scraper_cache_age_seconds` / `scraper_cache_uptime_seconds` | modbus-cache diagnostics, **auto-detected**: exported only when the polled endpoint serves the cache's diag block. `device_up 0` / a growing age mean the device is down **behind the cache** |

- the grid register value is split into export/import by sign — by default
  **positive = export**; set `--grid-positive-import` if your device reports
  the opposite.

- Huawei power registers already report **watts** (their gain convention
  divides raw by 1000 to get kW); the decode — type and gain — comes from the
  device profile's per-entry `scale` alone.

- caps are on by default: `--max-kwp 6` (6 kWp array) and `--max-grid-kw 12`
  (12 kW power line); the caps assume `max-kwp ≤ max-grid-kw` (a startup
  warning fires otherwise). A reading above a cap logs an error and serves
  **HTTP 503** until a good poll.

- **negative PV readings always trigger the error** regardless of the cap
  settings — a negative inverter input would corrupt the derived home load.

## Alerting

| alert | fires when | the trail says |
|---|---|---|
| `ScraperPollDown` | `scraper_up == 0` for 2m — the Modbus poll of the device is failing | the scraper log names the failure per cycle |
| `ScraperFreshnessGap` | the last successful poll is more than 120s behind — 12 lost cycles at the default 10s poll | the slow-dongle gauges tell a stall from an outage |
| `ScraperExceptionSpike` | `scraper_modbus_errors_total` grew by more than 30 in 10m — half the cycles failing at the default interval | the log names the Modbus exception code per failed poll |
| `CachePollDown` (the cache's `/metrics`) | `modbus_cache_poll_up == 0` for 2m | the cache serves its last known words; the uplink block counters show the failing block |
| `CacheAgeSpike` | the oldest cached word more than 300s old — reads succeed with stale data behind them | the `cache-ttl` budget is the knob |
| `CacheWriteRefusalBurst` | `modbus_cache_write_refused_total` grew by more than 3 in 5m — the write gate refusing in bursts | each refusal is a `WRITE-REFUSED` audit event (the client, the frame, the gate) |

- the family's **alert rules pack** lives at `extras/alerts/` — one rule file
  per watched exporter; this exporter's half is `alerts/scraper.yml`, the
  cache's half (`alerts/cache.yml`) ships with the cache package. The pack is
  the audit vocabulary's detection half (docs/SECURITY.md F16): every alert
  names the audit events and the log lines it correlates with, so a fired page
  tells the operator where the trail lives.

- the cache group stays silent until the cache's own `/metrics` endpoint is
  scraped (an absent series never fires); the exporter's diag block
  (`scraper_cache_device_up` / `scraper_cache_age_seconds`) mirrors two of its
  shapes for setups that do not scrape the cache. The exporter's own death
  (the scrape failing) is the collector's stock `up{job}` hygiene, not this
  pack.

- wire-in: the demo image bakes the pack (`docker/prometheus.yml` sets
  `rule_files:`); a NixOS Prometheus points `services.prometheus.ruleFiles` at
  the packaged copy (`share/alerts.yml`, see `nixos/README.md`); an external
  collector copies the file and lists it under its own `rule_files:`.
  Thresholds assume the default 10 s poll interval — tune them to yours.

## Battery

- the energy balance always carries the battery term (battery support is
  always on — the flag retired):

    home = pv − batt − grid

- battery registers (defaults follow the same Huawei convention as the PV
  register — they come from the device profile's `battery-power` and
  `battery-soc` entries): **37001** battery power (I32 W, **positive =
  charging**), **37004** state of charge (U16, percent×10).

- charging midday surplus reduces the home value; evening discharge covers the
  home load even with PV at 0.

- the consistency checks adapt: exported power may exceed the PV cap by the
  battery discharge (a battery feeding the grid is legitimate), and a derived
  `home < 0` is rejected as inconsistent. A device profile without the battery
  registers keeps the battery metrics absent.

- the fake inverter emulates the battery for testing: `python3 apps/inverter/bin/modbus-fake-inverter.py`.

## Tuning

- **the poll cadence** — `--modbus-interval` (the loop's sleep; the alert
  thresholds assume the default 10s) and `--modbus-timeout` (the
  per-transaction ceiling).

- **the slow dongle** — `--modbus-merge-gap` widens the address gap that still
  merges into one block read (fewer transactions per poll),
  `--modbus-read-delay` paces them; `show uplink` renders the block plan and
  its per-block latency — a stalled plan shows right there.

- **the sanity caps** — `--max-kwp` / `--max-grid-kw` are the bad-data fence
  (a reading above a cap answers HTTP 503 until a good poll, never silently
  wrong numbers); size them to the array and the power line (`max-kwp` ≤
  `max-grid-kw`, a startup warning otherwise).

- **the exposition** — `--metrics-prefix` renames the family (`huawei_` the
  default; the dashboard's `config.js` selectors must follow),
  `--metrics-spec` renames/rewords the individual metrics without touching the
  code.

## Audit logging

- logging is `logging`-based with **UTC timestamps by default**
  (`--local-time` switches): one startup line with the effective settings,
  reachability changes and reloads at INFO/WARNING (every poll at DEBUG). HTTP
  requests are quiet by default; **`--log-access`** logs every request at INFO
  as an audit trail of who scraped what when. **Rejected requests are always
  audited** regardless.

- handled connection problems always log a single line — the suite enforces
  that **no scenario produces a traceback**. Under systemd (`JOURNAL_STREAM`
  set) log lines omit their own timestamp — journald adds one.

- the control commands (with their wire macs), the auth failures, the reloads
  and the shutdowns land in the **SCR audit trail** (`--audit-log`, the XDG
  state home by default — `dev/gates/audit_verify.py` walks it like the
  others).

- `--audit-forward` mirrors every line — the hash chain included — onward:
  `syslog` (the local socket auto-scan), `syslog:/path` (an explicit socket),
  `udp://host[:514]` (RFC5426, best-effort) or `tcp://host[:514]` (RFC6587
  octet-count framing) — the **off-box copy**: an edited local trail breaks
  its chain, and a scheduled search at the collector can chain-verify the
  extracted prefix/chain fields and alert on a break; a line that left the box
  before an attacker arrived cannot be touched from it.

- the remote envelope rides `--audit-forward-format` (`rfc5424`, the default,
  or `cef` — the local syslog forms keep the verbatim send). A send failure
  notes once on stderr and the next event re-arms (the note carries the
  dropped count).

- `--audit-log none` turns the local file off: with a forward spelled that is
  the **remote-only mode** (the collector is the sole holder — no file, no XDG
  directory, the chain reseeds at GENESIS per run), without one the audit is
  disabled (the state `--no-audit-log` spells).

- the line names its writer — the daemon the `tag=daemon` role, the ctl and
  cli clients the shared `tag=cli` role — and carries an `instance=<id>` word:
  the **control port** when `--audit-instance` is unset (unique per host by
  construction), the override when spelled. Keep an override unique among
  everything that shares one collector; the chain groups by the (application,
  writer, instance) triple.

- the 12-hex token after the event name is the entry's **chained hash** (the
  audit's F10): any edit, deletion or reordering shows up as a chain break in
  `dev/gates/audit_verify.py` (run it on a trail file, the family's XDG
  trails, or a journald dump on stdin). **Every wire command is audited once,
  by the server** (with the client peer, the role, and the frame's mac when
  the wire is signed).

## Register maps (the register defaults)

- register defaults follow Huawei's official *Solar Inverter Modbus Interface
  Definitions* (Issue 04, 2023-01-10) — they live in the device profile, not
  in flags.

- **32064** — input power, I32, unit kW with gain 1000 (raw values are watts);
  **37113** — meter power, I32, `> 0` = feed-in (without a meter the inverter
  alone cannot report grid power).

- older **20200520** protocol: input power at **32089**, meter power at
  **37258** — point `--modbus-profile` at a profile carrying those addresses.

- unit quirk: the inverter's `[Power meter collection]` copy of 37113 has been
  observed reporting **watts** (gain 1) while the meter-section table says kW
  (gain 1000). The bundled profile assumes watts; if grid power looks 1000×
  off the other way, set the entry's `scale` to 1000 in your profile copy.

- with a battery the derived home load is wrong while the battery
  charges/discharges — point the dashboard's `load` metric at a real meter
  register/exporter instead.

## Register maps and the metrics spec

- *where* the primary values live comes from a **device profile** — the same
  shared schema the fake inverter serves and the cache polls; the shipped
  profiles live in the suite's `shared/profiles/` data dir (`sun2000.json` by
  default); the format is documented in `shared/profiles/README.md`.
  Resolution: `--modbus-profile` flag, env `MODBUS_PROFILE`, config `set modbus profile`,
  then the bundled copy; re-read on `SIGHUP`.

- the live control surface swaps the profile at runtime: `set modbus profile <file-or-name>`
  loads the new map, rebuilds the metric sources and rolls back cleanly when
  the profile lacks the registers the power math depends on.

- WHICH entries feed the metrics comes from **`metrics.json`** — the spec,
  keyed by the exported metric name directly. An entry carries either a
  **`profile`** field naming the device-profile register it is read from (its
  `type`/`scale` drive the decode) or an **`expr`** — a computed metric
  (`{expr, when?, help, type?}`) evaluated per poll over the declared
  **inputs**.

- the expr grammar is a strict stdlib-safe whitelist (numbers, the inputs,
  arithmetic, comparisons, the ternary, `abs`/`min`/`max`/`round`; one compute
  metric cannot feed another); an unavailable input, a division by zero or a
  non-finite result keeps the metric absent for that poll.

- the spec is **sectioned** — `inputs` (the declared expression vocabulary),
  `metrics` (the tree above), `scraper` (the exporter's own observability
  specs, shipped separately in `apps/scraper/lib/metrics.json` and merged in
  over the configured spec — a custom `--metrics-spec` only needs the sections
  it cares about). The JSON Schema ships as `schema/metrics.schema.json`
  (draft 2020-12).

- the four **canonical** entries — the power math's inputs
  (`pv_generation_watts`, `grid_net_watts`, `battery_net_watts`,
  `battery_soc_percent`) — are built-in: always declared, always bound, always
  fetched. Every profile-bound metric beyond them is read once per poll,
  softly: a rejected read keeps its metric absent instead of failing the poll.

- metric names, help texts and types are loaded at startup from the packaged
  `metrics.json` (the lib dir's default; a checkout resolves the
  `apps/scraper/metrics.json` → `examples/` dev symlink) — point
  `--metrics-spec` elsewhere (or `set metrics spec`) to rename metrics or
  reword `# HELP` lines without touching the code; a missing or corrupt spec
  fails cleanly at startup (one-line error, exit 1). `show inputs` / `show inputs-metrics`
  render the declared inputs and the exported metrics.

    ok inputs
    batt     [battery_net_watts]    Net battery power in watts (positive …
    pv       [pv_generation_watts]  PV input power in watts (the …

## Deployment

- **NixOS** — the module `nixos/modules/modbus-scraper.nix` renders the
  exporter as a hardened service (the options mapped in `nixos/README.md`, the
  packaging in `nixos/README.md`); the rendered config validates with
  `--dry-run` before a switch.

- **containers** — `docker/Dockerfile.modbus-scraper`, the demo and prod
  compose stacks beside it (`docker/README.md`); the env file
  (`docker/env/modbus-scraper.env.example`) carries the bare upper-snake
  twins.

- **systemd (plain)** — run it behind journald (`--audit-log -`), the token as
  a `LoadCredential=` file passed as `file:<path>` (the re-read on `SIGHUP` is
  the rotation story).

## The docs map

| document | what it carries |
|---|---|
| `docs/SECURITY.md` | the security posture and the F-findings the pages cite (F9 the secrets, F10 the audit chain, F11 the trusted-LAN test tool, F12 the secret files, F13 the token floors, F16 the alert pack, F18 the dump split, F21 the web face) |
| `docs/specs/ACL.md` | the ACL gate semantics — the rule chains, the ip-prefix grammar, the standalone acl files, the tools, and where each tool's support stops |
| `docs/specs/MODBUS.md` | the Modbus wire specs — the function-code support maps, the suite and Waveshare auth handshakes, the diagnostics block |
| `docs/DESIGN.md` | the design — the architecture, the decisions, the postures the tools share |
| `nixos/README.md` | the NixOS side — the option maps rebuilt from `module.nix`, the flake, the packages |
| `docker/README.md` | the container side — the images, the compose topologies (the demo and the prod split), the env examples |
| `shared/profiles/README.md` | the device profile format — the schema, the semantics, the shipped devices |
| `extras/alerts/` | the alert rules pack — one rule file per watched exporter, every alert naming the audit events it correlates with |
| `docs/book/` | the assembled book (these manuals gathered, the specs beside) |
| `docs/history/` | the wave records — how the suite got here, `front-page-split.md` among them |
| `docs/TODO.md` | the open items |
| `CHANGELOG.md` | the unreleased changes and the current release |

## The docs map

| this tool's documents | what they carry |
|---|---|
| `apps/scraper/README.md` | the front page — the description, the quick how-to, Security, License |
| `apps/scraper/lib/options.json` | the registry — the one row per knob (the tables above render from it) |
| `apps/scraper/lib/metrics.json` + `apps/scraper/metrics.json` | the shipped self-observability spec and the checkout's configurable spec (the loader merges it over the lib half) |
| `apps/scraper/schema/` | the JSON Schemas for the metrics spec (draft 2020-12) |
| `apps/scraper/examples/` | the GENERATED conf + the example metrics spec |
| `apps/scraper/man/` | the generated man page (`modbus-scraper --man` renders it) |
| `nixos/modules/modbus-scraper.nix` | the NixOS service module (the options mapped in `nixos/README.md`) |
| `docker/Dockerfile.modbus-scraper` + `docker/env/modbus-scraper.env.example` | the image and the deployment env (the topologies: `docker/README.md`) |

| document | what it carries |
|---|---|
| `docs/SECURITY.md` | the security posture and the F-findings the pages cite (F9 the secrets, F10 the audit chain, F11 the trusted-LAN test tool, F12 the secret files, F13 the token floors, F16 the alert pack, F18 the dump split, F21 the web face) |
| `docs/specs/ACL.md` | the ACL gate semantics — the rule chains, the ip-prefix grammar, the standalone acl files, the tools, and where each tool's support stops |
| `docs/specs/MODBUS.md` | the Modbus wire specs — the function-code support maps, the suite and Waveshare auth handshakes, the diagnostics block |
| `docs/DESIGN.md` | the design — the architecture, the decisions, the postures the tools share |
| `nixos/README.md` | the NixOS side — the option maps rebuilt from `module.nix`, the flake, the packages |
| `docker/README.md` | the container side — the images, the compose topologies (the demo and the prod split), the env examples |
| `shared/profiles/README.md` | the device profile format — the schema, the semantics, the shipped devices |
| `extras/alerts/` | the alert rules pack — one rule file per watched exporter, every alert naming the audit events it correlates with |
| `docs/book/` | the assembled book (these manuals gathered, the specs beside) |
| `docs/history/` | the wave records — how the suite got here, `front-page-split.md` among them |
| `docs/TODO.md` | the open items |
| `CHANGELOG.md` | the unreleased changes and the current release |

## Source layout

the subproject is flat and stdlib-only — one bin pair, one lib package, the
generated surfaces beside. The checkout launchers (`dev`, `dev-cli`) run the
exporter and the console straight from the tree against the shipped sample
config.

    apps/scraper/
    ├── bin/
    │   ├── modbus-scraper.py         # the daemon: the CLI, the logging, the
    │   │                            #   signal handling, the control wiring
    │   └── modbus-scraper-cli.py -> ../../pvsuite-cli.py
    │                                # the family client dispatcher: the tool
    │                                #   from the name it was invoked as
    ├── lib/
    │   ├── poller.py                 # the poll loop: the block reads, the sanity
    │   │                             #   caps, the store
    │   ├── protocol.py               # the Modbus TCP wire format, the limits
    │   ├── expr.py                   # the compute-expression evaluator (the
    │   │                             #   metrics spec's expr/when entries)
    │   ├── metrics.py                # the metrics spec (metrics.json), sectioned
    │   ├── server.py                 # the Prometheus exposition endpoint
    │   ├── control.py                # the JSON-lines control server
    │   ├── config.py                 # the set grammar: the config script, the
    │   │                             #   env, the flags
    │   ├── statics.py                # the protocol limits, the diag block it reads
    │   ├── options.py + options.json # the registry: the one row per knob
    │   ├── cli_spec.py               # the client SPEC (pvsuite-cli's per-tool half)
    │   └── man.py                    # the generated man pages
    ├── metrics.json                  # the shipped self-observability spec
    ├── schema/                       # the JSON Schemas (draft 2020-12)
    ├── examples/                     # the GENERATED conf + the example metrics spec
    ├── man/                          # the generated man page
    └── dev, dev-cli                  # the checkout launchers

the shared machinery lives in the suite's `common/` package (the control
spine, the Modbus client, the audit, the compute-expression evaluator) and
`shared/` (the texts, the schemas, the profiles) — `lib/` imports it by
path; the client dispatcher is the suite's `apps/pvsuite-cli.py`, one script
for all four ctl tools.

## Troubleshooting

- **it will not start** — the bind failures and the config errors answer one
  clean line + exit 1 (a non-loopback listen without `--auth-token` is the
  usual one — the F13 floor); `--dry-run` prints the effective settings
  without touching the ports.

- **HTTP 503 on /metrics** — the sanity caps refusing the last poll (bad data
  above `--max-kwp`/`--max-grid-kw`, a negative PV): the log names the
  offending reading; the page returns with the next good poll — never silently
  wrong numbers.

- **the poll is failing** — `scraper_up == 0`, the error counter climbing, the
  freshness gauge aging: the log names the Modbus exception code per failed
  poll; `show uplink` splits a device stall from an outage (the per-block
  latencies).

- **deeper** — `--log-level DEBUG` logs every poll's transactions; `SIGUSR2`
  dumps the thread stacks; the audit trail chain-verifies with
  `dev/gates/audit_verify.py`.

## Testing

- two standalone suites live in the suite root `dev/suites/` — stdlib only,
  each starts its own fake inverter + exporters on scratch ports and cleans up
  after itself. Every scenario must end with the exporter serving correct
  metrics and **zero tracebacks** in the logs.

- the fake inverter is the suites' workhorse — its own subproject and manual
  (`extras/manuals/fake-inverter.md`): the suites start it automatically;
  point the scraper at it by hand to debug the poll loop hardware-free.

    dev/battery/battery.py scraper        # the scraper profile: the regtest, the fuzz, the
                                    #   audit chain (the suites refuse without the
                                    #   runner's PV_RUN_DIR)

- the suites **always run through the battery runner**
  (`dev/battery/battery.py`) — it owns the run dir, the port slots and the
  tally, and a standalone suite run refuses (a hand-run collides across
  sessions). A new behavior ships with a check: a scenario that fails without
  it and names the registry rows it pins.

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.
