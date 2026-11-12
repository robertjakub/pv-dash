# The modbus-cache manual (MANUAL.md)

A dependency-free (Python stdlib only) Modbus TCP caching proxy for
single-client devices: it polls the inverter once and serves every client
from the cache. Part of the pv-suite family. The daemon's own `--help` and
the man page (`modbus-cache --man`) carry the startup surface; this page
carries the control wire. **Generated** from `lib/options.json` (the
one-knob-one-source rows) by `scripts/gen_manual.py` — edit the registry and
re-run, never this file.

## Speaking to the daemon

The control server is a JSON-lines listener: a unix socket (the default
`/tmp/modbus-cache-15502.socket`) or a TCP port on 127.0.0.1 — the
`--control-port` flag, env `CTL`, `0` = off. Two clients speak it:

    python3 bin/modbus-cache-ctl.py --control-port 15509 request flush cache
    python3 bin/modbus-cache-cli.py

- the **ctl** runs one command per invocation (or a batch on stdin);
- the **cli** is the interactive console: `?` lists the words, TAB completes,
  `help <setting>` describes one, `help config` maps every knob to its control
  command, `show knobs` prints the dictionary.

TCP control demands the token (`--control-token` / env `CONTROL_TOKEN`; the
wire's `auth` verb carries it) and refuses to start without one; over the
unix socket a trusted peer (root, the daemon's own user or
`--control-trust-uids` — SO_PEERCRED) speaks without it.

The optional ops token (`--control-ops-token`) scopes a session to the
read-only verbs (the default: show,flush). Every command is audited. The
clients take `--control-port` (env `CTL`), `--timeout`, `--control-token`,
the audit flags and `--man`; the cli adds `--reconnect` /
`--reconnect-wait`.

A knob's value resolves at start as flag > env > config script > default;
the config file (the bundled `cache/examples/modbus-cache.conf`) speaks the
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
| `request reload` | command | save the live overrides and restart the whole daemon (the restart-marked knobs take their configured values) |
| `request reload-config` | command | re-read the config file (the SIGHUP path) |
| `request restart` | command (hidden) | restart the upstream session: connection + cache dropped, repoll |
| `request restore` | command (hidden) | re-apply a state dump's overrides (when the daemon has a dump path) |
| `set` | command | configure a setting live: set \<setting> \<value> |
| `show` | command | runtime state: show \<setting\|connections\|cache\|uplink\|version\|knobs> |
| `shutdown` | command | stop the proxy gracefully (asks to confirm) |
| `clear` | command | restore a setting to its configured value: clear \<setting> |

## Knobs

The tables spell the knob's registry key — the one internal name the wire,
the replies and the dispatch take; the set / clear column spells the console
words (the live path as words — the config files and the state dumps speak
them; the flat registry name answers the same set everywhere, the ctls
translate). The namespaces group them.

### general

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `cache-ttl` | `set cache ttl` | settable | `s\|off` | `--cache-ttl` / `TTL` | per-register cache TTL: older entries are refetched |

### acl

the access-control lists: who may connect, who may write

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `connect-acl` | `set acl connect` | settable | `any\|none\|IP,...\|file:\<path>` | `--connect-acl` / `CONNECT_ACL` | clients allowed to connect: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |
| `write-acl` | `set acl write` (the console also takes `set write acl`) | settable | `any\|none\|IP,...\|file:\<path>` | `--write-acl` / `WRITE_ACL` | clients allowed to write (requires allow-write): "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### modbus

the Modbus sessions: the inverter endpoint, the unit id, the poll plan, the
map, the auth schemes both directions

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `upstream` | `set modbus upstream` | settable (restart) | `HOST:PORT` | `--upstream` / `UPSTREAM` | the inverter Modbus TCP endpoint HOST:PORT (`:5502` = 127.0.0.1:5502) |
| `unit` | `set modbus unit` | settable | `ID` | `--unit` / `UNIT` | the Modbus unit id the session speaks |
| `timeout` | `set modbus timeout` | settable | `s` | `--timeout` / `TIMEOUT` | upstream Modbus connect/read timeout in seconds |
| `modbus-auth` | `set modbus auth` | settable | `suite\|none` | `--modbus-auth` / `MODBUS_AUTH` | the auth scheme the cache's own Modbus clients must speak: suite (the crypt handshake) or none |
| `modbus-auth-key` | — | startup-only (secret) | `KEY` | `--modbus-auth-key` / `MODBUS_AUTH_KEY` | the suite handshake's shared key for the cache's clients, min 16 characters (`file:<path>` reads an owner-only file) *(hidden)* |
| `modbus-auth-upstream` | `set modbus auth-upstream` | settable | `suite\|waveshare\|none` | `--modbus-auth-upstream` / `MODBUS_UPSTREAM_AUTH` | the auth scheme the cache speaks to the upstream inverter: suite (the crypt handshake), waveshare (the gateway connection password) or none |
| `modbus-auth-upstream-key` | — | startup-only (secret) | `KEY` | `--modbus-auth-upstream-key` / `MODBUS_UPSTREAM_AUTH_KEY` | the key the cache presents upstream: the suite handshake's shared key (min 16 characters) or the Waveshare gateway password (`file:<path>` reads an owner-only file) *(hidden)* |
| `interval` | `set modbus interval` | settable | `s` | `--interval` / `INTERVAL` | seconds between cache polls of the device |
| `read-delay` | `set modbus read-delay` | settable | `s` | `--read-delay` / `READ_DELAY` | seconds between consecutive device reads within a poll cycle |
| `merge-gap` | `set modbus merge-gap` | settable | `registers` | `--merge-gap` / `MERGE_GAP` | max register gap when merging ranges into block reads; the plan rebuilds |
| `profile` | `set modbus profile` | settable | `\<file>` | `--profile` / `PROFILE` | device profile JSON: the register ranges to cache (a bare name resolves in profiles/profiles/) |
| `selection` | `set modbus selection` | settable | `\<file>\|all\|none` | `--selection` / `SELECTION` | selection JSON: which profile names to fetch ("all" = every entry, "none" = cache nothing) |

### system

the daemon's own socket and client log: the listen address, the access-log
verbosity

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `listen` | `set system listen` | settable (restart) | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |
| `local-time` | `set system local-time` | settable | `on\|off` | `--local-time` / `LOCAL_TIME` | log timestamps in the system time zone instead of UTC |
| `control-log-replies` | `set system log-replies` | settable | `on\|off` | `--control-log-replies` / — | DEBUG-log the full output of every control command (plainly: the command and its status log) |
| `log-level` | `set system log-level` | settable | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |
| `log-access` | `set system log-access` | settable | `on\|off` | `--log-access` / `LOG_ACCESS` | log client connects/disconnects at INFO instead of DEBUG *(hidden)* |

### control

the control plane: the target, the tokens, the ops role's RBAC policy, the
trusted peers

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `control-port` | `set control port` | settable | `PATH\|PORT` | `--control-port` / `CTL` | control server target: unix socket path or TCP port on 127.0.0.1 |
| `control-token` | — | startup-only (secret) | `TOKEN` | `--control-token` / `CONTROL_TOKEN` | require a token on control connections: the client authenticates with {"cmd": "auth", "token":...}; over the unix socket a trusted peer (root, the daemon's own user or --control-trust-uids — SO_PEERCRED) skips the token (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-trust-uids` | `set control trust-uids` | settable | `UID,...` | `--control-trust-uids` / `CONTROL_TRUST_UIDS` | extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon's own user are always trusted |
| `control-socket-group` | `set control socket-group` | settable | `on\|off` | `--control-socket-group` / `CONTROL_SOCKET_GROUP` | leave the unix control socket group-accessible (chmod 0660 instead of the plain 0600) |

### control/ops

the read-only ops role: the second token that scopes its sessions to the
configured verbs (the default: show,flush)

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `control-ops-token` | — | startup-only (secret) | `TOKEN` | `--control-ops-token` / `CONTROL_OPS_TOKEN` | a second, read-only control token: sessions authenticating with it may run its policy's verbs only (the default policy: show,flush) (no set/clear, no request poll now, no request dump/restore, no restart, no shutdown) — the ops shift against the admin key, both audited (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-ops-verbs` | `set control ops verbs` | settable | `VERB,...` | `--control-ops-verbs` / `CONTROL_OPS_VERBS` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated |

### metrics

the cache's own Prometheus /metrics endpoint: the toggle, the bind address,
the bearer token and the connection caps

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `metrics-server` | `set metrics enable` | settable | `on\|off` | `--metrics-server` / `METRICS_SERVER` | the cache's own Prometheus /metrics endpoint (needs a token beyond loopback; the address is --metrics-listen) |
| `metrics-listen` | `set metrics listen` | settable (restart) | `HOST:PORT` | `--metrics-listen` / `METRICS_LISTEN` | the metrics bind address HOST:PORT — the set records the value, the restart (request reload) applies it |
| `metrics-token` | — | startup-only (secret) | `TOKEN` | `--metrics-token` / `METRICS_TOKEN` | the metrics bearer token (Authorization: Bearer) — startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `metrics-acl` | `set metrics acl` | settable | `any\|none\|IP,...\|file:\<path>` | `--metrics-acl` / `METRICS_ACL` | clients allowed to connect to /metrics: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### metrics/limits

the metrics endpoint's connection caps: the simultaneous-client and per-IP
limits

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `metrics-max-clients` | `set metrics limits max-clients` | settable | `N` | `--metrics-max-clients` / `METRICS_MAX_CLIENTS` | simultaneous HTTP clients on /metrics; extras get an immediate 503 |
| `metrics-client-timeout` | `set metrics limits timeout` | settable | `s` | `--metrics-client-timeout` / `METRICS_CLIENT_TIMEOUT` | seconds an idle /metrics client is kept before the socket times out, 0 = the built-in 5 s cap |
| `metrics-max-conn-per-ip` | `set metrics limits max-conn-per-ip` | settable | `N` | `--metrics-max-conn-per-ip` / `METRICS_MAX_CONN_PER_IP` | maximum concurrent /metrics connections from one peer IP, 0 = no per-IP limit |

### audit

the CACHE audit trail: the sink, the forwarding, the rotation, the kill
switch

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `audit-log` | `set audit log-file` | settable | `PATH\|-\|none` | `--audit-log` / `AUDIT_LOG` | the audit trail's file: a path, - for stdout, none = no local file (the forward carries the trail), empty = the XDG state home |
| `audit-forward` | `set audit forward` | settable | `none\|syslog\|syslog:/PATH\|udp://HOST\|tcp://HOST` | `--audit-forward` / `AUDIT_FORWARD` | also forward every audit line: the local syslog mirror or a remote collector (the off-box copy) |
| `audit-forward-format` | `set audit forward format` (the console also takes `set audit forward-format`) | settable | `rfc5424\|cef` | `--audit-forward-format` / `AUDIT_FORWARD_FORMAT` | the remote forward's envelope: RFC5424 (the default) or CEF — the local syslog forms keep the verbatim send |
| `audit-instance` | `set audit instance` | settable | `ID` | `--audit-instance` / `AUDIT_INSTANCE` | the audit lines' instance word: the writer daemon's identity — the control port when unset, the override when spelled |
| `no-audit-log` | `set audit disable` | settable | `on\|off` | `--no-audit-log` / `NO_AUDIT_LOG` | disable the audit trail entirely |
| `requests-audit` | `set audit requests` | settable | `s\|off` | `--requests-audit` / `REQUESTS_AUDIT` | audit one REQUESTS tally per client per this many seconds |

### audit/rotate

the audit trail's rotation: the size trigger, the UTC-midnight trigger and
the backup count

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `audit-max-mb` | `set audit rotate max-size` | settable | `MB` | `--audit-max-mb` / `AUDIT_MAX_MB` | rotate the audit trail at this size in MB, 0 = no size rotation |
| `audit-daily` | `set audit rotate daily` | settable | `on\|off` | `--audit-daily` / `AUDIT_DAILY` | also rotate the audit trail at UTC midnight |
| `audit-files` | `set audit rotate files` | settable | `N` | `--audit-files` / `AUDIT_FILES` | the rotated audit backups kept |

### dump

the state dump: the path, the cache words, the restore-on-start

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `dump-path` | `set dump path` | settable | `\<file>` | `--dump-path` / `DUMP_PATH` | the state dump file: written behind, on request dump and every dump-interval |
| `dump-key` | — | startup-only (secret) | `TEXT` | `--dump-key` / `DUMP_KEY` | the key that seals the state dumps (the words and the settings, the reload's state file too) (`file:<path>` reads an owner-only file) *(hidden)* |
| `dump-with-cache` | `set dump with-cache` | settable | `on\|off` | `--dump-with-cache` / `DUMP_WITH_CACHE` | the dump carries the cached register words too |
| `dump-interval` | `set dump interval` | settable | `s\|off` | `--dump-interval` / `DUMP_INTERVAL` | seconds between the automatic state dumps (the cached words + the setting overrides) |
| `restore-on-start` | `set dump restore-on-start` | settable (restart) | `on\|off` | `--restore-on-start` / `RESTORE_ON_START` | the dump loads on start (off: on demand with request restore) |

### limits

the connection caps: the simultaneous-client and per-IP limits

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `max-clients` | `set limits max-clients` | settable | `N` | `--max-clients` / `MAX_CLIENTS` | simultaneous client limit |
| `client-timeout` | `set limits client-timeout` | settable | `s` | `--client-timeout` / `CLIENT_TIMEOUT` | disconnect clients silent for this long |
| `max-conn-per-ip` | `set limits max-conn-per-ip` | settable | `N` | `--max-conn-per-ip` / `MAX_CONN_PER_IP` | simultaneous connections from one peer IP |

### write

the write gates: the forwarding toggle and the register ranges

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `allow-write` | `set write allow` | settable | `on\|off` | `--allow-write` / `ALLOW_WRITE` | forward write requests (FC05/06/15/16/22/23) to the device |
| `write-registers` | `set write registers` | settable | `START:COUNT,...\|any\|none\|profile\|file:\<path>` | `--write-registers` / `WRITE_REGISTERS` | the address ranges a write may touch (FC06/16/22/23 registers, FC05/15 coils): START:COUNT,... or the device profile's acl |

## Show reports

| report | kind | description |
|---|---|---|
| `show connections` | show-only | connected clients: peer, age, requests served |
| `show cache` | show-only | cache contents: ranges, words, freshness, hits/misses |
| `show cache-all` | show-only (hidden) | every cached range-entry: its words, age, expiry and status |
| `show uplink` | show-only | the inverter link: session counters, per-block latency and errors |
| `show uplink-sources` | show-only | the register map: one row per polled register — fc, register, the range that fetches it, source |
| `show version` | show-only | the modbus-cache version |
| `show config` | show-only | the effective configuration as a set-grammar script (the secret knobs render as *** SECRET REMOVED ***) |
| `show knobs` | show-only | the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes |
| `show write-registers-table` | show-only | the write-registers gate as its acl chain: one allow/deny line per range (the profile's rules with their descs when the knob rides profile) |
| `show connect-acl-table` | show-only | the connect ACL as its rule chain, one entry per line: allow 0.0.0.0/0 (any), deny 0.0.0.0/0 (none), the whitelist spelled out — or the ip-prefix acl file's own rules with their descs |
| `show write-acl-table` | show-only | the write ACL as its rule chain, one entry per line (the acl/connect/table report for acl/write) |
| `show metrics-acl-table` | show-only | the metrics ACL as its rule chain, one entry per line: allow 0.0.0.0/0 (any), deny 0.0.0.0/0 (none), the whitelist spelled out — or the ip-prefix acl file's own rules with their descs |

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.

