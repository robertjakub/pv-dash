# The dashboard manual (MANUAL.md)

A single-page dashboard for home PV monitoring, fed by Prometheus: it serves
the page and proxies the upstream queries. Part of the pv-suite family. The
daemon's own `--help` and the man page (`dashboard --man`) carry the startup
surface; this page carries the control wire. **Generated** from
`lib/options.json` (the one-knob-one-source rows) by `scripts/gen_manual.py`
— edit the registry and re-run, never this file.

## Speaking to the daemon

The control server is a JSON-lines listener: a unix socket (the default
`/tmp/dashboard-8080.socket`) or a TCP port on 127.0.0.1 — the
`--control-port` flag, env `CTL`, `0` = off. Two clients speak it:

    python3 bin/dashboard-ctl.py --control-port 15598 request reload-config
    python3 bin/dashboard-cli.py

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
the config file (the bundled `dashboard/examples/dashboard.conf`) speaks the
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
| `quit` | command | close the session |
| `request` | namespace | the state machinery: the dump written and restored, the daemon reloaded |
| `request dump` | command (hidden) | write the state dump: the live setting overrides, sealed (when the daemon has a dump path) |
| `request reload` | command | save the live overrides and restart the whole daemon (the config file and the flags are re-resolved) |
| `request reload-config` | command | re-read the config file (the SIGHUP path) |
| `request restore` | command (hidden) | re-apply a state dump's overrides (when the daemon has a dump path) |
| `set` | command | configure a setting (set log-queries on, set metrics enable on) |
| `show` | command | print a setting's live value, or a report |
| `shutdown` | command | stop the dashboard server (asks to confirm) |
| `clear` | command | restore a setting to its configured value (clear log-queries, clear system log-level) |

## Knobs

The tables spell the knob's registry key — the one internal name the wire,
the replies and the dispatch take; the set / clear column spells the console
words (the live path as words — the config files and the state dumps speak
them; the flat registry name answers the same set everywhere, the ctls
translate). The namespaces group them.

### general

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `upstream` | — | startup-only | `URL` | `--upstream` / `PROM_URL` | upstream Prometheus URL |
| `prom-prefix` | — | startup-only | `PREFIX` | `--prom-prefix` / `PROM_PREFIX` | path under which Prometheus is proxied |
| `static-dir` | — | startup-only (secret) | `PATH` | `--static-dir` / `STATIC_DIR` | directory to serve (startup-only: flag/env/config and restart) *(hidden)* |
| `config-js` | — | startup-only (secret) | `PATH` | `--config-js` / `CONFIG_JS` | config.js to serve at /config.js (startup-only: flag/env/config and restart) *(hidden)* |
| `max-clients` | `set max-clients` | settable | `N` | `--max-clients` / `MAX_CLIENTS` | simultaneous HTTP clients (static pages + the proxy); extras get an immediate 503 |
| `client-timeout` | `set client-timeout` | settable | `s` | `--client-timeout` / `CLIENT_TIMEOUT` | kick idle keep-alive HTTP clients after this long |
| `max-conn-per-ip` | `set max-conn-per-ip` | settable | `N` | `--max-conn-per-ip` / `MAX_CONN_PER_IP` | simultaneous HTTP connections from one peer IP |
| `metrics-listen` | — | startup-only | `HOST:PORT` | `--metrics-listen` / `METRICS_LISTEN` | the metrics bind address HOST:PORT |
| `metrics-max-clients` | — | startup-only | `N` | `--metrics-max-clients` / `METRICS_MAX_CLIENTS` | maximum concurrent /metrics clients; extras get an immediate 503, 0 = unlimited |
| `metrics-client-timeout` | — | startup-only | `s` | `--metrics-client-timeout` / `METRICS_CLIENT_TIMEOUT` | seconds an idle /metrics client is kept before the socket times out, 0 = the built-in 5 s cap |
| `metrics-max-conn-per-ip` | — | startup-only | `N` | `--metrics-max-conn-per-ip` / `METRICS_MAX_CONN_PER_IP` | maximum concurrent /metrics connections from one peer IP, 0 = no per-IP limit |
| `log-queries` | `set log-queries` | settable | `on\|off` | `--log-queries` / `LOG_QUERIES` | log the proxied Prometheus queries at INFO |

### system

the daemon's own serving socket: the page's listen address

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `listen` | `set system listen` | settable (restart) | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |
| `control-log-replies` | `set system log-replies` | settable | `on\|off` | `--control-log-replies` / `CONTROL_LOG_REPLIES` | DEBUG-log the full output of every control command (plainly: the command and its status log) |
| `log-level` | `set system log-level` | settable | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |
| `log-access` | `set system log-access` | settable | `on\|off` | `--log-access` / `LOG_ACCESS` | log every HTTP request at INFO |
| `local-time` | `set system local-time` | settable | `on\|off` | `--local-time` / `LOCAL_TIME` | log timestamps in the system time zone instead of UTC |

### auth

the page's auth: the bearer token the browser presents — the `?auth=<token>`
query bootstraps the session cookie

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `auth-token` | — | startup-only (secret) | `TOKEN` | `--auth-token` / `AUTH_TOKEN` | require Authorization: Bearer \<token> on the page, config.js and the proxy — mandatory beyond loopback; the `?auth=<token>` query bootstraps the session cookie; startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |

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
| `control-ops-token` | — | startup-only (secret) | `TOKEN` | `--control-ops-token` / `CONTROL_OPS_TOKEN` | a second, read-only control token: sessions authenticating with it may run its policy's verbs only (the default policy: show) (no set/clear, no request reload, no shutdown) — the ops shift against the admin key, both audited (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `control-ops-verbs` | `set control ops verbs` | settable | `VERB,...` | `--control-ops-verbs` / `CONTROL_OPS_VERBS` | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated |

### metrics

the dashboard's /metrics endpoint's auth and access: the bearer token the
scrape presents and the client ACL checked at accept

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `metrics-server` | `set metrics enable` | settable | `on\|off` | `--metrics-server` / `METRICS_SERVER` | the dashboard's own Prometheus /metrics endpoint (needs a token beyond loopback; the address is --metrics-listen) |
| `metrics-token` | — | startup-only (secret) | `TOKEN` | `--metrics-token` / `METRICS_TOKEN` | require Authorization: Bearer \<token> on the /metrics endpoint — mandatory beyond loopback; startup-only (pass it by flag/env/config); the value never renders back (`file:<path>` = the token from an owner-only file) *(hidden)* |
| `metrics-acl` | `set metrics acl` | settable | `any\|none\|IP,...\|file:\<path>` | `--metrics-acl` / `METRICS_ACL` | clients allowed to connect to /metrics: "any", "none", comma-separated IPs/prefixes, or file:\<path> (the ip-prefix acl file) |

### audit

the DSH audit trail: the sink, the forwarding, the rotation, the kill switch

| knob | set / clear | kind | value | flag / env | description |
|---|---|---|---|---|---|
| `audit-log` | `set audit log-file` | settable | `PATH\|-\|none` | `--audit-log` / `AUDIT_LOG` | DSH audit trail: a file path or - for stdout (the docker/journald way); `none` = no local file (the forward carries the trail); the XDG state home when unset |
| `audit-forward` | `set audit forward` | settable | `none\|syslog\|syslog:/PATH\|udp://HOST\|tcp://HOST` | `--audit-forward` / `AUDIT_FORWARD` | also forward every audit line: the local syslog mirror or a remote collector (the off-box copy) |
| `audit-forward-format` | `set audit forward format` (the console also takes `set audit forward-format`) | settable | `rfc5424\|cef` | `--audit-forward-format` / `AUDIT_FORWARD_FORMAT` | the remote forward's envelope: RFC5424 (the default) or CEF — the local syslog forms keep the verbatim send |
| `audit-instance` | `set audit instance` | settable | `ID` | `--audit-instance` / `AUDIT_INSTANCE` | the audit lines' instance word: the writer daemon's identity — the control port when unset, the override when spelled |
| `no-audit-log` | `set audit disable` | settable | `on\|off` | `--no-audit-log` / `NO_AUDIT_LOG` | disable the DSH audit trail |

### audit/rotate

the audit trail's rotation: the size trigger, the UTC-midnight trigger and
the backup count

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
| `dump-interval` | `set dump interval` | settable | `s\|off` | `--dump-interval` / `DUMP_INTERVAL` | seconds between the automatic state dumps (the live setting overrides) |
| `restore-on-start` | `set dump restore-on-start` | settable (restart) | `on\|off` | `--restore-on-start` / `RESTORE_ON_START` | the dump loads on start (off: on demand with request restore) |

## Show reports

| report | kind | description |
|---|---|---|
| `show connections` | show-only | the live HTTP clients: the gate counters, one row per peer IP |
| `show metrics-acl-table` | show-only | the metrics ACL as its rule chain, one entry per line (the metrics/acl report) |
| `show version` | show-only | the dashboard version |
| `show config` | show-only (hidden) | the effective configuration as a set-grammar script (the secret knobs render as *** SECRET REMOVED ***) |
| `show knobs` | show-only (hidden) | the dictionary of all knobs: every knob, its flag, its env twin, its section, how it changes |

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.

