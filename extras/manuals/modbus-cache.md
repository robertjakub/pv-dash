# The modbus-cache manual

A dependency-free (Python stdlib only) Modbus TCP caching proxy for
single-client devices: it polls the inverter once and serves every client
from the cache. Part of the pv-suite family.

## The family

- the cache is the chain's multiplexer: **one client slot at the device** (the
  inverter accepts one Modbus TCP client), any number of Modbus clients behind
  it — the scraper polls through it, the write tools and the debug sessions
  share the slot, the replay taps the hop.

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

    python3 apps/cache/bin/modbus-cache.py --upstream 192.168.1.100:5502

- the proxy binds `127.0.0.1:15502` (loopback only) — `--listen 0.0.0.0:15502`
  serves the LAN.

- `--dry-run` validates the configuration and the register map and prints the
  effective settings without binding the listen port or contacting the
  inverter — handy for checking NixOS-rendered config files (`--config /nix/store/…-modbus-cache.conf --dry-run`).
  Exit codes: `0` = valid, `1` = invalid (reason on stderr, stdout stays
  clean), `2` = command-line misuse.

- settings resolve flag > env (the bare upper-snake twins) > config script >
  default; boolean config/env values accept `true`/`false`, `1`/`0`,
  `yes`/`no`, `on`/`off`; every setting is validated before use — nonsense
  values abort with a clean one-line error instead of failing later at
  runtime.

- the six secret knobs (`--modbus-auth-key`, `--modbus-auth-upstream-key`,
  `--control-token`, `--control-ops-token`, `--metrics-token`, `--dump-key`)
  never render back: the config file, the state dumps and the reload state
  file carry the `*** SECRET REMOVED ***` placeholder. Pass each one on every
  start — by flag, by env, or as `file:<path>` (the first line of an
  owner-only `0600` file; a flag value lands in `ps` — the file form is the
  shipped way, the F9/F12 posture).

- the bundled `examples/modbus-cache.conf` is GENERATED
  (`dev/generators/examples.py`) — every knob the registry declares, every
  line commented at its default; `show config` regenerates the script from the
  running daemon (secrets hidden) and `help config` maps every knob to its
  control command.

## How it works

- a background loop **polls the configured register ranges** at a fixed
  interval into an in-memory cache.

- any number of clients are **served from the cache** (FC3/FC4 words, FC1/FC2
  bits); reads outside the cached ranges are polled live, answered and cached
  for `--cache-ttl` like everything else — any other function code is
  forwarded untouched.

- **writes** (FC05/06/15/16/22/23) are forwarded when enabled (the four gates,
  `Access control` below) and always logged with register, value(s) and
  outcome; a forwarded write drops the cached words it touched (per-register)
  and wakes the poller — the next read goes to the device, not the pre-write
  value. Register writes invalidate both word spaces (holding + input), coil
  writes the coil space.

- a synthesized **diagnostics block** (registers 65000–65003: device-up flag,
  cache age, uptime) lets clients tell live data from cache-served values —
  the scraper auto-detects it and exports it as `scraper_cache_*` gauges.

- **inverter unreachable** — cached reads keep serving the last known values
  while forwarded reads get Modbus exception `0x0B`. Entries older than
  `--cache-ttl` are refetched on the next read.

- **device rejects a range** — the cache remembers that poll status and
  answers client reads in the range with the same exception until a poll
  succeeds again: no repeated hammering, and clients see the failure the
  device actually reports.

- **garbage from the device or from clients** — malformed frames, lying
  lengths, wrong ids, stalls, pipelined bursts: logged one-line and survived;
  a client cannot crash the proxy, only burn its own connection (fuzz- and
  soak-tested).

## The control plane

- the cli ships beside the daemon (`bin/modbus-cache-cli.py`, its own man page
  via `--man`) — the same client the suites drive; every word below is its
  spelling.

- the control server is a JSON-lines listener: a unix socket (the default
  `/tmp/modbus-cache-15502.socket`) or a TCP port on 127.0.0.1 — the
  `--control-port` flag, env `CTL`, `0` = off.

    python3 bin/modbus-cache-cli.py --control-port 15509 request flush cache
    python3 bin/modbus-cache-cli.py

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
  read-only verbs (the default: show,flush). Every command is audited. The
  clients take `--control-port` (env `CTL`), `--timeout`, `--control-token`,
  the audit flags and `--man`; the cli adds `--reconnect` /
  `--reconnect-wait`.

- a knob's value resolves at start as flag > env > config script > default;
  the config file (the bundled `apps/cache/examples/modbus-cache.conf`) speaks
  the same grammar — `set <name> <value>` lines, `--dry-run` prints the
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
| `inspect` | command | one pretty dump of everything (the status, the map, the counters, the write gate) |
| `ping` | command (internal) | keep-alive: answers pong |
| `quit` | command | close the session |
| `request` | namespace | the state machinery: the dump written and restored, the cache dropped, the poll woken, the daemon reloaded |
| `request flush` | namespace | drop the cached registers and repoll now |
| `request flush cache` | command | drop the cached registers, repoll now (request flush cache) |
| `request poll` | namespace | the poll loop's manual wake |
| `request poll now` | command | wake the poll loop immediately |
| `request dump` | namespace (hidden) | the state dump: the live overrides written sealed (with-cache carries the cached register words too) |
| `request dump with-cache` | command (hidden) | the dump carries the cached register words too |
| `request reload` | command (hidden) | save the live overrides and restart the whole daemon (the restart-marked knobs take their configured values) |
| `request reload-config` | command (hidden) | re-read the config file (the SIGHUP path) |
| `request restart` | command (hidden) | restart the upstream session: connection + cache dropped, repoll |
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

### general

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `cache-ttl` | `set cache ttl` | settable | 30.0 | `s\|off` | `--cache-ttl` / `TTL` | per-register cache TTL: older entries are refetched |

### acl

the access-control lists: who may connect, who may write

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `connect-acl` | `set acl connect` | settable | any | `any\|none\|IP,...\|file:\<path>` | `--connect-acl` / `CONNECT_ACL` | clients allowed to connect: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |
| `write-acl` | `set acl write` (the console also takes `set write acl`) | settable | none | `any\|none\|IP,...\|file:\<path>` | `--write-acl` / `WRITE_ACL` | clients allowed to write (requires allow-write): "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### modbus

the Modbus sessions: the inverter endpoint, the unit id, the poll plan, the
map, the auth schemes both directions

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `upstream` | `set modbus upstream` | settable (restart) | 127.0.0.1:5502 | `HOST:PORT` | `--upstream` / `UPSTREAM` | the inverter Modbus TCP endpoint HOST:PORT (`:5502` = 127.0.0.1:5502) |
| `modbus-unit` | `set modbus unit` | settable | 1 | `ID` | `--modbus-unit` / `MODBUS_UNIT` | the Modbus unit id the session speaks |
| `modbus-timeout` | `set modbus timeout` | settable | 3.0 | `s` | `--modbus-timeout` / `MODBUS_TIMEOUT` | Modbus connect/read timeout in seconds |
| `modbus-auth` | `set modbus auth` | settable | none | `suite\|none` | `--modbus-auth` / `MODBUS_AUTH` | the Modbus auth scheme: suite (the crypt handshake) or none |
| `modbus-auth-key` | — | startup-only (secret) | — | `KEY` | `--modbus-auth-key` / `MODBUS_AUTH_KEY` | the suite handshake's shared key for the cache's clients, min 16 characters (`file:<path>` reads an owner-only file) *(hidden)* |
| `modbus-auth-upstream` | `set modbus auth-upstream` | settable | none | `suite\|waveshare\|none` | `--modbus-auth-upstream` / `MODBUS_UPSTREAM_AUTH` | the auth scheme the cache speaks to the upstream inverter: suite (the crypt handshake), waveshare (the gateway connection password) or none |
| `modbus-auth-upstream-key` | — | startup-only (secret) | — | `KEY` | `--modbus-auth-upstream-key` / `MODBUS_UPSTREAM_AUTH_KEY` | the key the cache presents upstream: the suite handshake's shared key (min 16 characters) or the Waveshare gateway password (`file:<path>` reads an owner-only file) *(hidden)* |
| `modbus-interval` | `set modbus interval` | settable | 10.0 | `s` | `--modbus-interval` / `MODBUS_INTERVAL` | seconds between polls of the upstream |
| `modbus-read-delay` | `set modbus read-delay` | settable | 0.05 | `s` | `--modbus-read-delay` / `MODBUS_READ_DELAY` | seconds between consecutive device reads within a poll cycle |
| `modbus-merge-gap` | `set modbus merge-gap` | settable | 8 | `registers` | `--modbus-merge-gap` / `MODBUS_MERGE_GAP` | max register gap when merging ranges into block reads; the plan rebuilds |
| `modbus-profile` | `set modbus profile` | settable | sun2000 | `\<file>` | `--modbus-profile` / `MODBUS_PROFILE` | device profile JSON (a bare name resolves in shared/profiles/) |
| `selection` | `set modbus selection` | settable | all | `\<file>\|all\|none` | `--selection` / `SELECTION` | selection JSON: which profile names to fetch ("all" = every entry, "none" = cache nothing) |

### system

the daemon's own socket and client log: the listen address, the access-log
verbosity

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `listen` | `set system listen` | settable (restart) | 127.0.0.1:15502 | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |
| `local-time` | `set system local-time` | settable | off | `on\|off` | `--local-time` / `LOCAL_TIME` | log timestamps in the system time zone instead of UTC |
| `control-log-replies` | `set system log-replies` | settable | off | `on\|off` | `--control-log-replies` / — | DEBUG-log the full output of every control command (plainly: the command and its status log) |
| `log-level` | `set system log-level` | settable | INFO | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |
| `log-access` | `set system log-access` | settable | off | `on\|off` | `--log-access` / `LOG_ACCESS` | log client connects/disconnects at INFO instead of DEBUG *(hidden)* |

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
configured verbs (the default: show,flush)

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `control-ops-token` | — | startup-only (secret) | — | `TOKEN` | `--control-ops-token` / `CONTROL_OPS_TOKEN` | a second, read-only control token: sessions authenticating with it may run its policy's verbs only (the default policy: show,flush) (no set/clear, no request poll now, no request dump/restore, no restart, no shutdown) — the ops shift against the admin key, both audited (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-ops-verbs` | `set control ops verbs` | settable | show,flush | `VERB,...` | `--control-ops-verbs` / `CONTROL_OPS_VERBS` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated |

### metrics

the cache's own Prometheus /metrics endpoint: the toggle, the bind address,
the bearer token and the connection caps

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `metrics-server` | `set metrics enable` | settable | off | `on\|off` | `--metrics-server` / `METRICS_SERVER` | the tool's own Prometheus /metrics endpoint (needs a token beyond loopback; the address is --metrics-listen) |
| `metrics-listen` | `set metrics listen` | settable (restart) | 127.0.0.1:9351 | `HOST:PORT` | `--metrics-listen` / `METRICS_LISTEN` | the metrics bind address HOST:PORT — the set records the value, the restart (request reload) applies it |
| `metrics-token` | — | startup-only (secret) | — | `TOKEN` | `--metrics-token` / `METRICS_TOKEN` | the metrics bearer token (Authorization: Bearer) — startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `metrics-acl` | `set metrics acl` | settable | any | `any\|none\|IP,...\|file:\<path>` | `--metrics-acl` / `METRICS_ACL` | clients allowed to connect to /metrics: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### metrics/limits

the metrics endpoint's connection caps: the simultaneous-client and per-IP
limits

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `metrics-max-clients` | `set metrics limits max-clients` | settable | 64 | `N` | `--metrics-max-clients` / `METRICS_MAX_CLIENTS` | maximum concurrent /metrics clients; extras get an immediate 503, 0 = unlimited |
| `metrics-client-timeout` | `set metrics limits timeout` | settable | 5.0 | `s` | `--metrics-client-timeout` / `METRICS_CLIENT_TIMEOUT` | seconds an idle /metrics client is kept before the socket times out, 0 = the built-in 5 s cap |
| `metrics-max-conn-per-ip` | `set metrics limits max-conn-per-ip` | settable | 0 | `N` | `--metrics-max-conn-per-ip` / `METRICS_MAX_CONN_PER_IP` | maximum concurrent /metrics connections from one peer IP, 0 = no per-IP limit |

### audit

the audit trail: the sink, the forwarding, the rotation, the kill switch

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `audit-log` | `set audit log-file` | settable | — | `PATH\|-\|none` | `--audit-log` / `AUDIT_LOG` | the audit trail's file: a path, - for stdout, none = no local file (the forward carries the trail), empty = the XDG state home |
| `audit-forward` | `set audit forward` | settable | none | `none\|syslog\|syslog:/PATH\|udp://HOST\|tcp://HOST` | `--audit-forward` / `AUDIT_FORWARD` | also forward every audit line: the local syslog mirror or a remote collector (the off-box copy) |
| `audit-forward-format` | `set audit forward format` (the console also takes `set audit forward-format`) | settable | rfc5424 | `rfc5424\|cef` | `--audit-forward-format` / `AUDIT_FORWARD_FORMAT` | the remote forward's envelope: RFC5424 (the default) or CEF — the local syslog forms keep the verbatim send |
| `audit-instance` | `set audit instance` | settable | — | `ID` | `--audit-instance` / `AUDIT_INSTANCE` | the audit lines' instance word: the writer daemon's identity — the control port when unset, the override when spelled |
| `no-audit-log` | `set audit disable` | settable | off | `on\|off` | `--no-audit-log` / `NO_AUDIT_LOG` | disable the audit trail entirely |
| `audit-requests` | `set audit requests` | settable | 300 | `s\|off` | `--audit-requests` / `AUDIT_REQUESTS` | audit one REQUESTS tally per client per this many seconds |

### audit/rotate

the audit trail's rotation: the size trigger, the UTC-midnight trigger and
the backup count

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `audit-max-mb` | `set audit rotate max-size` | settable | 10.0 | `MB` | `--audit-max-mb` / `AUDIT_MAX_MB` | rotate the audit trail at this size in MB, keeping N backups; 0 = no size rotation |
| `audit-daily` | `set audit rotate daily` | settable | off | `on\|off` | `--audit-daily` / `AUDIT_DAILY` | also rotate the audit trail at UTC midnight |
| `audit-files` | `set audit rotate files` | settable | 3 | `N` | `--audit-files` / `AUDIT_FILES` | rotated audit backups to keep |

### dump

the state dump: the path, the cache words, the restore-on-start

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `dump-path` | `set dump path` | settable | — | `\<file>` | `--dump-path` / `DUMP_PATH` | the state dump file: written behind, on request dump and every dump-interval |
| `dump-key` | — | startup-only (secret) | — | `TEXT` | `--dump-key` / `DUMP_KEY` | the key that seals the state dumps (the words and the settings, the reload's state file too) (`file:<path>` reads an owner-only file) *(hidden)* |
| `dump-with-cache` | `set dump with-cache` | settable | off | `on\|off` | `--dump-with-cache` / `DUMP_WITH_CACHE` | the dump carries the cached register words too |
| `dump-interval` | `set dump interval` | settable | 0.0 | `s\|off` | `--dump-interval` / `DUMP_INTERVAL` | seconds between the automatic state dumps (the live setting overrides) |
| `restore-on-start` | `set dump restore-on-start` | settable (restart) | off | `on\|off` | `--restore-on-start` / `RESTORE_ON_START` | the dump loads on start (off: on demand with request restore) |

### trace

the wire trace: the record feed socket and the voices it carries

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `trace-socket` | `set trace socket` | settable | none | `default\|none\|PATH` | `--trace-socket` / `TRACE_SOCKET` | the record feed's unix socket: default, a path, or none (off; the built-in default) |
| `trace-sources` | `set trace sources` | settable | all | `all\|client\|upstream` | `--trace-sources` / `TRACE_SOURCES` | the wire voices the record feed carries: all, client or upstream |

### limits

the connection caps: the simultaneous-client and per-IP limits

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `max-clients` | `set limits max-clients` | settable | 64 | `N` | `--max-clients` / `MAX_CLIENTS` | simultaneous client limit |
| `client-timeout` | `set limits client-timeout` | settable | 300.0 | `s` | `--client-timeout` / `CLIENT_TIMEOUT` | disconnect clients silent for this long |
| `max-conn-per-ip` | `set limits max-conn-per-ip` | settable | 0 | `N` | `--max-conn-per-ip` / `MAX_CONN_PER_IP` | simultaneous connections from one peer IP |

### write

the write gates: the forwarding toggle and the register ranges

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `allow-write` | `set write allow` | settable | off | `on\|off` | `--allow-write` / `ALLOW_WRITE` | forward write requests (FC05/06/15/16/22/23) to the device |
| `write-registers` | `set write registers` | settable | none | `START:COUNT,...\|any\|none\|profile\|file:\<path>` | `--write-registers` / `WRITE_REGISTERS` | the address ranges a write may touch (FC06/16/22/23 registers, FC05/15 coils): START:COUNT,... or the device profile's acl |
## Show reports

| report | kind | description |
|---|---|---|
| `show connections` | show-only | connected clients: peer, age, requests served |
| `show cache` | show-only | cache contents: ranges, words, freshness, hits/misses |
| `show cache-all` | show-only (hidden) | every cached range-entry: its words, age, expiry and status |
| `show uplink` | show-only | the inverter link: session counters, per-block latency and errors |
| `show uplink-sources` | show-only | the register map: one row per polled register — fc, register, the range that fetches it, source |
| `show version` | show-only | the suite version |
| `show config` | show-only (hidden) | the effective configuration as a set-grammar script (the secret knobs render as *** SECRET REMOVED ***) |
| `show knobs` | show-only (hidden) | the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes |
| `show write-registers-table` | show-only | the write-registers gate as its acl chain: one allow/deny line per range (the profile's rules with their descs when the knob rides profile) |
| `show connect-acl-table` | show-only | the connect ACL as its rule chain, one entry per line: allow 0.0.0.0/0 (any), deny 0.0.0.0/0 (none), the whitelist spelled out — or the ip-prefix acl file's own rules with their descs |
| `show write-acl-table` | show-only | the write ACL as its rule chain, one entry per line (the acl/connect/table report for acl/write) |
| `show metrics-acl-table` | show-only | the metrics ACL as its rule chain, one entry per line: allow 0.0.0.0/0 (any), deny 0.0.0.0/0 (none), the whitelist spelled out — or the ip-prefix acl file's own rules with their descs |
## Signals

| signal | effect |
|---|---|
| `SIGHUP` | reload the configuration and the register map without dropping client connections (the wire twin is `request reload-config`): the map is swapped atomically, poll interval, read delay, merge gap, cache TTL, the ACLs (the `file:` gates re-read), limits and the upstream address/unit/timeout take effect immediately; a broken file keeps the previous settings; the listen address needs a restart (the registry's restart-marked knobs record a live `set` and fold into the restarted process) |
| `SIGUSR1` | clean the cache: all cached values, on-demand entries and poll-status errors are dropped atomically, the poller repopulates immediately |
| `SIGTERM` / `SIGINT` | graceful shutdown |

## Configuration

- the config file (`--config PATH`, env `CONFIG`) speaks the **set grammar** —
  one `set <name> <value>` per line, the control CLI's own spelling, the same
  line pastes into the console or a ctl; a value resolves flag > env > this
  file > the row's default, anything left commented falls to the default the
  line spells.

- the bundled `apps/cache/examples/modbus-cache.conf` is GENERATED from the
  registry (`dev/generators/examples.py`): every knob declared, every line
  commented at its default — copy it, uncomment what you change, point
  `--config` at it. The dev wrapper (`apps/cache/dev`) and the docker image
  both ride it as their default `--config` target.

    # per-register cache TTL: older entries are refetched
    # set cache ttl 30

    # the inverter Modbus TCP endpoint HOST:PORT (`:5502` = 127.0.0.1:5502)
    # set modbus upstream 127.0.0.1:5502

- a live daemon re-reads the file on `SIGHUP` / `request reload-config` — a
  broken file keeps the previous settings; the restart-marked knobs record a
  pending `set` and fold into the restarted process. `show config` regenerates
  the script from the running daemon (secrets hidden) and `--dry-run` prints
  the effective settings without binding anything.

- the secrets never live in the file: every secret row carries the `*** SECRET REMOVED ***`
  placeholder — pass them by flag, env, or `file:<path>` (the first line of an
  owner-only `0600` file).

## Runtime control

- the live layer: every `settable` row applies at once (`set <name> <value>`),
  `clear <name>` returns the configured value, `show <name>` prints the live
  one — the caps, the ACLs, the trace socket, the audit sinks and the poll
  plan rotate live; the console completes the row's live/alias path spellings.

- the **restart-marked** rows record a pending `set` and fold into the
  restarted process on `request reload` (or a plain restart); the
  **startup-only** rows (every secret, the listen address) answer a restart
  only. `show config` spells each row's shape, and regenerates the config
  script from the running daemon (secrets hidden).

- the request verbs: `request reload-config` re-reads the config file (the
  `SIGHUP` twin), `request dump` / `request dump with-cache` write the state
  dump, `request restore` loads it, `clear cache` is the `SIGUSR1` twin,
  `restart` restarts the daemon in place.

- every command is audited once, by the server (the peer, the role, the
  frame's mac when the wire is signed); the ops-token sessions ride the
  read-only verb policy.

    # live: retune, inspect, re-read the file
    set cache ttl 30
    show cache-all
    request reload-config

## Access control

- the family-wide ACL map — the rule-chain semantics, the standalone acl file,
  the tools and where every tool's support stops — lives in
  `docs/specs/ACL.md`; the four gates' knobs (`--connect-acl`, `--write-acl`,
  `--write-registers`, `--metrics-acl`) sit in the knobs table below with
  their defaults and the inline grammar.

- writing is gated four times: the frame parse gate, `--allow-write`, the
  client on the write ACL, every touched register inside the allow-list — with
  `write-acl` and `write-registers` defaulting to `none`, enabling
  `--allow-write` alone still refuses every write until the operator opens
  those two deliberately.

- a worked write-gate example ships as
  `extras/examples/acl-write-registers.json` (the deye policy, worked out).

- beyond the address-based ACLs the cache speaks the family's **`suite`**
  Modbus auth — a proof-of-key handshake on the Modbus TCP wire itself (the
  wire shape is specified in `docs/specs/MODBUS.md`): the client proves the
  shared key with one round trip after the TCP connect; the server answers
  `OK` (plain Modbus follows) or `ERR` (the connection is dead — a client that
  cannot prove the key never sees a frame).

- the two legs are configured separately, with separate keys: `--modbus-auth`
  / `--modbus-auth-key` — the auth the cache's *own clients* must speak on the
  listen port (`none` the default, or `suite`); `--modbus-auth-upstream` /
  `--modbus-auth-upstream-key` — the auth the cache *presents* to the upstream
  inverter (`suite` handshakes after every (re)connect, `waveshare` presents
  the key as a **Waveshare RS485-to-TCP gateway's** connection password).

- both keys are restart-marked secrets (a `set` records pending until `request reload`
  applies it; they never render back; `file:<path>` loads an owner-only `0600`
  file). The floor is the scheme's: the suite handshake needs at least 16
  characters, the Waveshare password non-empty ASCII — a key set while no
  scheme is chosen is dormant material.

- both schemes are live-settable; the peer must speak the same scheme with the
  same key — the fake inverter serves the server side, the scraper the client
  side, so a chain scraper → cache → inverter can run suite auth on either hop
  independently.

## Metrics

- `--metrics-server` (off by default, live-settable) serves the cache's own
  Prometheus `/metrics` on `--metrics-listen` (default `127.0.0.1:9351`).

- the bearer token is **mandatory beyond loopback** — a token-less
  non-loopback bind refuses to start (the F13 posture); beside the token the
  endpoint carries the **metrics ACL** (`--metrics-acl`, live `set metrics acl`),
  checked at accept; an unauthenticated read answers 401, anything but
  `/metrics` answers 404.

- the caps are live (the `metrics limits` values apply to the running gate);
  `set metrics listen` records the bind and the restart applies it; the token
  is startup-only — pass it by flag/env/config (or as `file:<path>`, which
  re-reads on the SIGHUP re-resolve); the value never renders back.

- a scrape job reads it like any bearer endpoint — `authorization: {type: Bearer, credentials_file: …}`
  in the job config (the docker demo's `prometheus.yml` wires the job for the
  exporter this way).

| gauge | meaning |
|---|---|
| `modbus_cache_hits_total` / `modbus_cache_misses_total` | the hit/miss counters |
| `modbus_cache_write_refused_total` | every refused write is a `WRITE-REFUSED` audit event |
| `modbus_cache_poll_up` / `modbus_cache_last_poll_age_seconds` / `modbus_cache_age_seconds` | the poll health and the age |
| `modbus_cache_words` / `modbus_cache_ranges` (the `fc` labels) | the map size |
| `modbus_cache_clients` | the connected clients |
| `modbus_cache_uptime_seconds` / the poll-cycle durations | the uptime and the last cycle's timing |
| `modbus_cache_uplink_*` | the upstream session state (up, connects/exchanges/errors, bytes, the last error's age) and every poll block (`…block_up{fc,start,count}`, `…block_latency_seconds{,_mean,_max}`, `…block_fails_total`) |

- the alert rules pack (`extras/alerts/cache.yml`, the F16 closure) watches
  this endpoint's poll down, the age spikes and the write-refusal bursts — the
  cache-only install ships its half (`share/alerts.yml`).

## Tuning

- **the poll cadence** — `--modbus-interval` (the loop's sleep, the wall the
  cache ages against) and `--modbus-timeout` (the per-transaction ceiling;
  `timeout` above `interval` just means polls run back-to-back).

- **the slow dongle** — `--modbus-merge-gap` widens the address gap that still
  merges into one block read (fewer transactions, bigger replies),
  `--modbus-read-delay` paces the blocks (the breathing room some RS485-to-TCP
  gateways need); a block the device refuses splits in halves and retries —
  the plan converges to the largest blocks the device actually answers (`show uplink`
  renders the plan and its latency).

- **the freshness budget** — `--cache-ttl` is the global staleness ceiling, an
  entry's **`ttl`** field **replaces** it per register (a fast power word at
  5s next to a nameplate word at 1h, one poll cadence for both); the
  diagnostics block's 65002 tells the clients how old the words actually are.

- **the clients** — `--max-clients` / `--max-conn-per-ip` cap the fan-out,
  `--client-timeout` reaps the stalls (every refused or reaped connection is a
  logged, audited event).

## Audit logging

- the proxy logs every audit-relevant event to stdout/stderr with UTC
  timestamps by default (`--local-time` switches). Under systemd, journald
  stores, seals and rotates these lines — point your NIS2/DORA documentation
  at `journalctl -u modbus-cache`. Modbus has no authentication, so the
  client's source IP is the only identity there is.

| event | log line |
|---|---|
| forwarded write | `write: register 47415 = 99 (single register, unit 1)` |
| write refused (disabled / ACL / device) | `write: refused register …` / `write rejected by the device: …` |
| forwarded frame (no cache semantics) | `forwarded FC17 (report slave id), 0 byte(s) (unit 1)` |
| uncached read forwarded + cached | `read: registers … not cached, polling the device` / `… ok, cached …` |
| connection rejected (ACL / limit) | `connection rejected: 10.0.0.5:51234 not on the connect ACL` / `connection refused: client limit of N reached` |
| reload / clean (`SIGHUP` / `SIGUSR1`) | `SIGHUP: reloaded 13 range(s) …` / `SIGUSR1: cache cleared (N register(s) dropped) …` |
| poll failed/recovered | `poll of … failed (FC3 modbus exception, code 2), serving cached values` / `poll of … recovered` |
| client connect/disconnect (`--log-access`) | `client connected: 10.0.0.5:51234` / `client … disconnected (…)` |
| startup / shutdown | `caching 13 range(s) …` / `shutdown: SIGTERM received, closing the listener`) |

- on top of the operational log, the proxy and the CLI append to an
  **append-only audit file** — one line per event, who/when/what/result, on by
  default at the XDG state home (`~/.local/state/modbus-cache/audit.log`).
  `--audit-log <file>` renames it, `--no-audit-log` turns it off, `--audit-log -`
  sends it to stdout (the docker logs / journald way — the NixOS module ships
  with it). Rotation: `--audit-max-mb 10` (the default), `--audit-daily` (UTC
  midnight), `--audit-files 3`.

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

    2026-11-04T07:16:40Z AUDIT application=CACHE tag=daemon instance=15502 type=start hash=4e1b92f0c7a3 version=0.5.1 upstream=192.168.1.100:5502 unit=1 listen=127.0.0.1:15502 control=unix:/tmp/modbus-cache-15502.socket profile=/nix/store/…-sun2000.json
    2026-11-04T07:16:43Z AUDIT application=CACHE tag=daemon instance=15502 type=write hash=b2c4e17f90d8 fc=6 register=47415 value=5 unit=1
    2026-11-04T07:17:12Z AUDIT application=CACHE tag=daemon instance=15502 type=command hash=09ab57d3f4e1 peer=127.0.0.1:54426 cmd='clear cache' result=ok
    2026-11-04T07:17:45Z AUDIT application=CACHE tag=daemon instance=15502 type=shutdown hash=d94a1f07c3e2 reason=SIGTERM-received uptime=65s clients=1 hits=412 misses=9

- the per-client **request accounting** rides the same trail (one `REQUESTS`
  event per client per `--audit-requests` period, plus a final tally on every
  disconnect). The trail is thread-safe and flushed per event.

    journalctl -u modbus-cache --since today | grep 'write:'      # all write attempts
    journalctl -u modbus-cache | grep -E 'SIGHUP|shutdown'        # lifecycle
    journalctl -u modbus-cache | grep -i 'not on'                 # ACL rejections

## Register maps

- the proxy caches the registers listed in the **device profile** — the same
  shared schema the fake inverter serves and the scraper scrapes; the shipped
  profiles live in the suite's `shared/profiles/` data dir (`sun2000.json` by
  default); the format is documented in `shared/profiles/README.md`.
  Resolution: `--modbus-profile` flag, env `MODBUS_PROFILE`, config `set modbus profile`,
  then the bundled copy; the file is re-read on `SIGHUP`.

- entry `type` gives the width and the space: `i16`/`u16` (one word),
  `i32`/`u32` and the lo-word-first `i32swap`/`u32swap`, the IEEE 754
  `f32`/`f32swap` (two words each), `bit` (one address = one binary value).

- the optional **`fc`** field picks the address space: `3` (holding registers)
  or `4` (input registers) for the word types (`3` the default), `1` (coils,
  the bit default) or `2` (discrete inputs) for `bit` — the four spaces are
  cached and polled independently.

- the optional **`ttl`** field overrides the cache TTL per entry (seconds; `0`
  = never expire): a fast power word at 5s next to a nameplate word at 1h, one
  poll cadence for both (`show cache-all` marks the entries carrying one). The
  entry TTL **replaces** the global one in both directions — the global TTL is
  only the fallback, never a floor.

- which registers are actually **fetched** comes from a selection file —
  `{"registers": ["pv-power", ...]}`, profile names only — resolved as
  `--selection` flag, env `SELECTION`, config `set modbus selection`; the
  default fetches **every** profile entry (`all`), and **`none`** empties the
  map: every read forwards and nothing is stored. The shipped
  `extras/examples/modbus-cache-filter.json` is the essential SUN2000
  monitoring set. The 65000–65003 diagnostics block is never fetched — the
  cache synthesizes it.

- for slow dongles the poller reads the map in as **few transactions as
  possible**: ranges closer together than `--modbus-merge-gap` registers are
  merged into one block read (never across a function-code boundary); a block
  that fails is split in halves and the pieces are retried — the plan
  converges to the largest blocks the device actually answers.

## Diagnostics registers

- the cache synthesizes a 4-register block at **65000** from live poller state
  — answered instantly, never forwarded, never cached, never part of a profile
  (FC3 only): the clients tell live data from cache-served values, and the
  scraper auto-detects the block and exports it as the `scraper_cache_*`
  gauges.

| register | meaning |
|---|---|
| **65000** | magic `0xCAFE` (the validity check for clients) |
| **65001** | `1` if the last completed poll cycle had at least one successful read, else `0` |
| **65002** | seconds since the last successful device read (`65535` = none yet) |
| **65003** | the cache process' uptime in seconds |

- reads that straddle the block are rejected with exception `02` (illegal data
  address) — read the four words whole. Reply unit ids are validated on every
  forwarded request before anything is cached.

## Persistence

- `--dump-path` turns on the **write-behind state dump**: the live setting
  overrides and — when asked — the cached words (+ their original stamps), as
  one JSON written atomically. **What lands in the file is split** (the
  audit's F18): by default **settings only**; `request dump with-cache` or
  `--dump-with-cache` includes the words; the restore takes either shape.

- the dumps land every `--dump-interval` seconds (live-settable, `0` = off —
  the default), on the **`request dump`** command, and on every graceful
  shutdown. **`--restore-on-start`** opts in to loading the dump when the
  daemon starts; the default is starting cold — **`request restore`** loads it
  on demand.

- the file is created **`0600`** explicitly (never the umask); every dump
  carries a **sha256 integrity hash**; a restore **fails closed** on an
  edited/truncated/unsigned dump and refuses a group/world-writable file
  outright.

- with **`--dump-key`** the dump is **sealed**: the state rides encrypted
  under an HMAC-SHA256 counter-mode keystream, authenticated by an HMAC mac
  (stdlib only). The gate is symmetric — a restore without the key refuses a
  sealed dump, and a restore **with** a key refuses an unsealed one. The
  reload's state file seals under the same key — which is why the knob is
  startup-only.

- the key rides inline or as **`file:<path>`** (a systemd LoadCredential rides
  as `file:/run/credentials/...`); the same `file:` reference form works on
  every secret value. Without a key a dump path stays plaintext **by design**
  — and says so (a `WARNING` at start, a note on the `set dump path` reply).

## Trace feed

- `--trace-socket` binds the record feed's unix stream socket (`default` = the
  derived `/tmp/modbus-cache-<listen-port>-trace.socket`, a path, or `none` =
  off; live-settable, `set trace-socket`): every wire record fans out to the
  connected `modbus-replay-dump --socket` (the same PVMB protocol
  modbus-replay's feed speaks); binds `0600`.

- `--trace-sources` picks the wire voices the feed carries: `all`, `client`
  (the served answers + their provenance) or `upstream` (the poller's polls +
  the forwards) — whole voices on/off, never sampling; live-settable.

- the feed's records carry a `conn` id pairing each request with its reply,
  and the two wire faces count in **disjoint spaces**: the client face numbers
  its sessions from 1 (one id per client connection), the upstream face rides
  `100000 + <connection serial>` — so `conn=100001` is the device
  conversation's first incarnation, `conn=100002` the same after a reconnect.
  The split exists because a forwarded request keeps the client's own
  transaction id: one conn space would make the dump tool pair the device's
  reply with the client's request instead of keeping the two stories apart.

- the client face's records state the provenance in the `note` (`served from cache`,
  `forwarded — device reply`, `refused: …`, `diag registers`); the device's
  true bytes appear as the upstream conversation beside them, and the upstream
  auth handshake rides byte-less (`PVA1 handshake (bytes withheld)` — no
  proof, no password).

## Deployment

- **NixOS** — the module `nixos/modules/modbus-cache.nix` renders the daemon
  as a hardened service (the options mapped in `docs/NIXOS.md`, the packaging
  in `nixos/README.md`): the env file, the state dirs and the secret `*File`
  options ride the module; the rendered config validates with `--dry-run`
  before a switch.

- **containers** — `docker/Dockerfile.modbus-cache` (stdlib-only, the
  unprivileged user), the demo and prod compose stacks beside it
  (`docker/README.md`); the image loads its bundled conf as the default
  `--config` target — the env file (`docker/env/modbus-cache.env.example`) and
  the CMD flags carry the deployment shape.

- **systemd (plain)** — run it behind journald (`--audit-log -` rides the
  NixOS module; journald stores, seals and rotates), the secrets as
  `LoadCredential=` files passed as `file:<path>`.

## The docs map

| document | what it carries |
|---|---|
| `docs/SECURITY.md` | the security posture and the F-findings the pages cite (F9 the secrets, F10 the audit chain, F11 the trusted-LAN test tool, F12 the secret files, F13 the token floors, F16 the alert pack, F18 the dump split, F21 the web face) |
| `docs/specs/ACL.md` | the ACL gate semantics — the rule chains, the ip-prefix grammar, the standalone acl files, the tools, and where each tool's support stops |
| `docs/specs/MODBUS.md` | the Modbus wire specs — the function-code support maps, the suite and Waveshare auth handshakes, the diagnostics block |
| `docs/NIXOS.md` | the NixOS option maps, rebuilt from `module.nix` |
| `nixos/README.md` | the packaging side — the flake, the modules, the packages |
| `docker/README.md` | the container side — the images, the compose topologies (the demo and the prod split), the env examples |
| `shared/profiles/README.md` | the device profile format — the schema, the semantics, the shipped devices |
| `extras/alerts/` | the alert rules pack — one rule file per watched exporter, every alert naming the audit events it correlates with |
| `docs/book/` | the assembled book (these manuals gathered, the specs beside) |
| `docs/history/` | the wave records — how the suite got here, `front-page-split.md` among them |
| `docs/TODO.md` | the open items |
| `CHANGELOG.md` | the unreleased changes and the current release |

## Source layout

- `bin/modbus-cache.py` — the daemon; `bin/modbus-cache-cli.py` — the
  one-shot/interactive client; `lib/` — the daemon's modules (the cache core,
  the control server, the config/registry wiring);
  `examples/modbus-cache.conf` — the generated sample; `man/` — the generated
  man page; `dev` / `dev-cli` — the checkout launchers (the sys.path and the
  default `--config` target).

- the shared machinery lives in the suite's `common/` package (the control
  spine, the Modbus client/server, the audit, the manpage generator) and
  `shared/` (the texts, the schemas, the profiles) — `lib/` imports it by
  path; nothing is packaged separately.

## Troubleshooting

- **it will not start** — every bind failure answers one `cannot bind` line +
  exit 1 (the port taken? `ss -ltnp | grep 15502`); every configuration error
  aborts with a clean one-line error before anything binds — `--dry-run`
  prints the effective settings without touching the ports.

- **clients refused** — the log names the gate: `not on the connect ACL`, the
  client limit reached, the write gates' `WRITE-REFUSED` (the audit trail
  carries the client, the frame, the gate per refusal).

- **stale or dead data** — the diagnostics block's 65001/65002 and the
  `modbus_cache_poll_up` / `modbus_cache_last_poll_age_seconds` gauges tell a
  poll failure from a slow one; the log names the failing block and the
  exception code per cycle.

- **deeper** — `--log-level DEBUG` logs every frame both ways; `SIGUSR2` dumps
  the thread stacks (the family's faulthandler hook); the audit trail
  chain-verifies with `dev/gates/audit_verify.py`.

## Testing

- four standalone suites live in the suite root `dev/suites/` — stdlib only,
  each starts its own fake inverter + proxy on scratch ports and cleans up
  after itself. Every scenario must end with the proxy alive and **zero
  tracebacks** in the logs — the hostile-upstream phase proves that per mode,
  including recovery when the device starts answering sanely again.

    dev/battery/battery.py cache              # the cache profile: the regtest, the two fuzzes,
                                        #   the audit chain (the stress suite rides quick/full)
    dev/battery/battery.py cache-regtest      # one suite — every run needs the runner (the suites
                                        #   refuse without the runner's PV_RUN_DIR)

- the suites **always run through the battery runner**
  (`dev/battery/battery.py`) — it owns the run dir, the port slots and the
  tally, and a standalone suite run refuses (a hand-run collides across
  sessions). A new behavior ships with a check: a scenario that fails without
  it and names the registry rows it pins.

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.
