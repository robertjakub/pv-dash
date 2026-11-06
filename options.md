# The knobs of the family (options.md)

One table comparing every knob of the four daemons — the name, the
function it files under and the registry description — with a mark per
tool. **Generated** from the per-tool `lib/options.json` registries (the
one-knob-one-source rows) by `scripts/gen_options.py` — edit the
registries and re-run `python3 scripts/gen_options.py`, never this file.
The resolution order on every tool is flag > env > config script >
default; the bare `$NAME` env forms are the knob's upper-snake name.
Every bin also carries the CLI-only `--config`/`--dry-run`/`--man`
(plus `--version`/`--help`) — flags, not knobs, so they have no rows
here. The ctl/cli clients speak the control plane only
(`--control-port`, the token file/env pair) and are not compared.

Common to **all four** tools (15): `--audit-files`, `--audit-log`, `--audit-max-mb`, `--client-timeout`, `--control-ops-token`, `--control-ops-token-file`, `--control-ops-verbs`, `--control-port`, `--control-token`, `--control-token-file`, `--control-trust-uids`, `--log-level`, `--max-clients`, `--max-conn-per-ip`, `--no-audit-log`. The control-plane block is
shared nearly verbatim; the audit, limits and metrics blocks follow the
family shape with per-tool defaults.

| knob | function | description | cache | scraper | inverter | dashboard |
|---|---|---|---|---|---|---|
| `--allow-write` | device | forward write requests (FC05/06/15/16) to the inverter; default: refuse them with a Modbus illegal-function exception | ✓ live |  |  |  |
| `--battery` | device | enable battery support (default: config, $BATTERY or off) |  | ✓ | ✓ |  |
| `--battery-kwh` | device | usable battery capacity in kWh (default 6.9) |  |  | ✓ |  |
| `--cache-ttl` | device | per-register cache TTL: cached registers older than this are refetched from the inverter, 0 = never expire, serve last known values forever (default: config, $TTL or 3x interval) | ✓ live |  |  |  |
| `--chaos` | device | probability 0..1 that a request is answered hostile and dropped (default: off); seed with --seed for reproducibility |  |  | ✓ |  |
| `--connect-acl` | device | clients allowed to connect: "any", "none" (refuse everyone) or comma-separated IPs/prefixes like 10.0.0.7,10.48.0.0/16 (default: config, $CONNECT_ACL or any) | ✓ live |  | ✓ |  |
| `--grid-frequency` | device | nominal grid frequency in Hz (the machine wanders ±0.2 Hz around it, default 50) |  |  | ✓ |  |
| `--grid-positive-import` | device | grid register positive when importing (default: config, $GRID_POSITIVE_IMPORT or positive = export) |  | ✓ |  |  |
| `--grid-voltage` | device | nominal grid phase voltage in V (120 or 230; the per-phase machine wanders ±10 % around it, default 230) |  |  | ✓ |  |
| `--host` | device | bind address (default 127.0.0.1) |  |  | ✓ |  |
| `--interval` | device | seconds between cache polls (default: config, $INTERVAL or 10) | ✓ live |  |  |  |
| `--max-grid-kw` | device | maximum grid kW, either direction (default: config, $MAX_GRID_KW or 12; 0 = no checking) |  | ✓ |  |  |
| `--max-kwp` | device | maximum PV array kWp (default: config, $MAX_KWP or 6; 0 = no checking) |  | ✓ | ✓ |  |
| `--merge-gap` | device | max register gap when merging ranges into block reads, 0 = read ranges separately (default: config, $MERGE_GAP or 8) | ✓ live |  |  |  |
| `--metric-prefix` | device | the prefix on the profile- and compute-fed metric names (default: config, $METRIC_PREFIX or 'huawei'); the bundled scraper_* names are fixed |  | ✓ |  |  |
| `--metrics-spec` | device | metrics spec JSON, sectioned: {profile: {key: {help, profile?}}, compute: ..., scraper: ...} — merged in memory over the built-in lib/metrics.json scraper_* block (default: config, $METRICS_SPEC or the bundled metrics.json) |  | ✓ |  |  |
| `--modbus-offset` | device | added to register addresses (default: config, $MODBUS_OFFSET or 0) |  | ✓ |  |  |
| `--modbus-unit` | device | Modbus unit id (default: config, $MODBUS_UNIT or 1) |  | ✓ |  |  |
| `--no-battery` | device | no battery values |  |  | ✓ |  |
| `--port` | device | Modbus TCP port (default 5502) |  |  | ✓ |  |
| `--profile` | device | device profile JSON (the shared profiles/ schema) (default: config, $PROFILE or the bundled sun2000 profile) | ✓ live | ✓ live | ✓ |  |
| `--read-delay` | device | seconds between consecutive inverter reads within a poll cycle, 0 = no delay (default: config, $READ_DELAY or 0.05) | ✓ live |  |  |  |
| `--seed` | device | chaos RNG seed (default: random) |  |  | ✓ |  |
| `--selection` | device | selection JSON: {"registers": ["pv-power", ...]} — the profile names to fetch (default: config, $SELECTION or every profile entry) | ✓ live |  |  |  |
| `--static` | device | constant demo values instead of the day simulation |  |  | ✓ |  |
| `--strict` | device | reject reads of undefined registers with exception 02 (like the real device) |  |  | ✓ |  |
| `--time` | device | freeze simulated time HH:MM (default: real clock) |  |  | ✓ |  |
| `--time-scale` | device | the simulated clock speed: N times real time - every machine (the battery, the clouds, the voltages, the day counters) integrates over it, so a full simulated day takes 24/N real hours (default: 1 = real time) |  |  | ✓ |  |
| `--timeout` | device | Modbus connect/read timeout in seconds (default: config, $TIMEOUT or 3) | ✓ live | ✓ live |  |  |
| `--timezone` | device | clock the state machines integrate over (the PV bell, the home load, the clouds, the battery, the grid voltage): UTC (the default) or the local wall clock |  |  | ✓ |  |
| `--unit` | device | Modbus unit id (default: config, $UNIT or 1) | ✓ |  | ✓ |  |
| `--upstream` | device | the inverter Modbus TCP endpoint HOST:PORT (:5502 = 127.0.0.1:5502) (default: config, $UPSTREAM or 127.0.0.1:5502) | ✓ | ✓ |  |  |
| `--write-acl` | device | clients allowed to write (requires --allow-write): "any", "none" (refuse everyone) or comma-separated IPs/prefixes (default: config, $WRITE_ACL or none) | ✓ live |  |  |  |
| `--write-registers` | device | register ranges a (forwarded) write may touch: comma-separated START:COUNT, e.g. 47400:100,47600:100; "any" = unrestricted; "none" = no register writable (default: config, $WRITE_REGISTERS or none) | ✓ live |  |  |  |
| `--battery` | serving | enable battery support in the served config.js (default: config file, $BATTERY or off) |  |  |  | ✓ live |
| `--bind` | serving | address to bind (default: config file, $BIND or 0.0.0.0) |  |  |  | ✓ |
| `--config-js` | serving | config.js to serve at /config.js (default: config file, $CONFIG_JS or config.js next to the script) |  |  |  | ✓ |
| `--listen` | serving | listen address HOST:PORT (default: config, $LISTEN or 127.0.0.1:15502) | ✓ | ✓ |  |  |
| `--local-time` | serving | log timestamps in the system time zone instead of UTC | ✓ | ✓ |  |  |
| `--port` | serving | listen port (default: config file, $PORT or 8080) |  |  |  | ✓ |
| `--prom-prefix` | serving | path under which Prometheus is proxied (default: config file, $PROM_PREFIX or /prom); empty string proxies everything |  |  |  | ✓ |
| `--static-dir` | serving | directory to serve (default: config file, $STATIC_DIR or static next to the script) |  |  |  | ✓ |
| `--upstream` | serving | upstream Prometheus URL (default: config file, $PROM_URL or http://localhost:9090) |  |  |  | ✓ |
| `--control-log-replies` | control plane | DEBUG-log the full output of every control command (the default logs the command only) |  |  | ✓ |  |
| `--control-ops-token` | control plane | a second, read-only control token: sessions authenticating with it may run the show/clear verbs only (no set/unset, no request dump/restore, no restart, no shutdown) — the ops shift against the admin key, both audited (default: config, $CONTROL_OPS_TOKEN or none) | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-ops-token-file` | control plane | the read-only ops token from a file (the first line; must be owner-only 0600) — takes the place of --control-ops-token; giving both is an error (default: config, $CONTROL_OPS_TOKEN_FILE) | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-ops-verbs` | control plane | the read-only ops role's RBAC policy: the verbs its sessions may run, comma-separated (default: show,clear; validated against the control grammar at start) | **✓** | **✓** | **✓** | **✓** |
| `--control-port` | control plane | control server target: unix socket path or TCP port on 127.0.0.1 (default: config, $CTL or /tmp/modbus-cache-\<listen-port>.socket); 0 = off | **✓** | **✓** | **✓** | **✓** |
| `--control-socket-group` | control plane | leave the unix control socket group-accessible (chmod 0660 instead of the default 0600) (default: config, $CONTROL_SOCKET_GROUP) | ✓ |  | ✓ |  |
| `--control-token` | control plane | require a token on control connections: the client authenticates with {"cmd": "auth", "token": ...}; over the unix socket a trusted peer (root, the daemon's own user or --control-trust-uids — SO_PEERCRED) skips the token (default: config, $CONTROL_TOKEN or none) | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-token-file` | control plane | the token from a file (the first line; e.g. a systemd LoadCredential or a key file; must be owner-only 0600) — takes the place of --control-token; giving both is an error (default: config, $CONTROL_TOKEN_FILE) | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-trust-uids` | control plane | extra peer uids the unix control socket trusts without the token (SO_PEERCRED — a local systemd unit speaks without the secret); root and the daemon's own user are always trusted (default: config, $CONTROL_TRUST_UIDS or none) | **✓** | **✓** | **✓** | **✓** |
| `--auth-token` | own /metrics | require Authorization: Bearer \<token> on all requests (default: config, $AUTH_TOKEN or disabled) |  | ✓ secret |  |  |
| `--auth-token-file` | own /metrics | read the bearer token from this file instead (single line, trimmed; re-read on every SIGHUP — rotate by rewriting the file and reloading; must be owner-only 0600); mutually exclusive with --auth-token |  | ✓ secret |  |  |
| `--metrics-client-timeout` | own /metrics | seconds an idle /metrics client is kept before the socket times out, 0 = the built-in 5 s cap (default: config, $METRICS_CLIENT_TIMEOUT or 5) | ✓ |  | ✓ | ✓ |
| `--metrics-listen` | own /metrics | the metrics bind address HOST:PORT — 0.0.0.0:PORT serves every interface, a token is mandatory regardless (default: config, $METRICS_LISTEN or 127.0.0.1:9252) | ✓ |  | ✓ | ✓ |
| `--metrics-max-clients` | own /metrics | maximum concurrent HTTP clients on the /metrics endpoint; extras get an immediate 503, 0 = unlimited (default: config, $METRICS_MAX_CLIENTS or 64) | ✓ |  | ✓ | ✓ |
| `--metrics-max-conn-per-ip` | own /metrics | maximum concurrent /metrics connections from one peer IP, 0 = no per-IP limit (default: config, $METRICS_MAX_CONN_PER_IP or 0) | ✓ |  | ✓ | ✓ |
| `--metrics-server` | own /metrics | serve the cache's own Prometheus /metrics endpoint (the live set metrics-server toggle exists too); off by default (the default: config, $METRICS_SERVER or off) | ✓ live |  | ✓ | ✓ live |
| `--metrics-token` | own /metrics | require Authorization: Bearer \<token> on the /metrics endpoint (the same scheme the scraper speaks) | ✓ secret |  | ✓ secret | ✓ secret |
| `--metrics-token-file` | own /metrics | the metrics bearer token from a file (the first line; must be owner-only 0600) — takes the place of --metrics-token; giving both is an error (env METRICS_TOKEN_FILE) | ✓ secret |  | ✓ secret | ✓ secret |
| `--audit-daily` | audit trail | also rotate the audit log at UTC midnight (default: config, $AUDIT_DAILY) | ✓ |  | ✓ |  |
| `--audit-files` | audit trail | rotated audit backups to keep (default: config, $AUDIT_FILES or 3) | **✓** | **✓** | **✓** | **✓** |
| `--audit-log` | audit trail | CACHE audit trail: a file path or - for stdout (the docker/journald way); default: config, $AUDIT_LOG or ~/.local/state/modbus-cache/audit.log — the XDG state home | **✓** | **✓** | **✓** | **✓** |
| `--audit-max-mb` | audit trail | rotate the audit log at this size in MB, keeping N backups; 0 = no size rotation (default: config, $AUDIT_MAX_MB or 10) | **✓** | **✓** | **✓** | **✓** |
| `--no-audit-log` | audit trail | disable the CACHE audit trail (default: config, $NO_AUDIT_LOG) | **✓** | **✓** | **✓** | **✓** |
| `--requests-audit` | audit trail | audit one REQUESTS tally per client per this many seconds, 0 = off (default: config, $REQUESTS_AUDIT or 300) | ✓ live |  |  |  |
| `--client-timeout` | limits | disconnect clients silent for this many seconds, 0 = never (default: config, $CLIENT_TIMEOUT or 300) | **✓** live | **✓** live | **✓** | **✓** live |
| `--max-clients` | limits | refuse further connections past this many simultaneous clients, 0 = no limit (default: config, $MAX_CLIENTS or 64) | **✓** live | **✓** live | **✓** | **✓** live |
| `--max-conn-per-ip` | limits | refuse further connections from one peer IP past this many simultaneous connections, 0 = no per-IP limit (default: config, $MAX_CONN_PER_IP or 0) | **✓** live | **✓** live | **✓** | **✓** live |
| `--dump-interval` | persistence | seconds between the automatic state dumps, 0 = on request (the request dump command and the shutdown) (default: config, $DUMP_INTERVAL or 0) | ✓ live |  |  |  |
| `--dump-path` | persistence | the state dump (write-behind): the live setting overrides and — with --dump-with-cache — the cached words, as one JSON, written 0600 with an integrity hash (a restore refuses a tampered, unsigned or group-writable dump); dumped on shutdown, on the request dump command and every --dump-interval seconds; loaded on start only with --restore-on-start, on demand with the request restore command (default: config, $DUMP_PATH or none) | ✓ |  |  |  |
| `--dump-with-cache` | persistence | dump the cached words too: request dump and the --dump-interval loop write the words + the settings (the default off = settings only; request dump with-cache always includes them; the restore takes either shape) (default: config, $DUMP_WITH_CACHE or off) | ✓ |  |  |  |
| `--restore-on-start` | persistence | load the state dump when the daemon starts (needs --dump-path) — a restart serves last-known values instead of cold misses; default: start cold, load only on demand (default: config, $RESTORE_ON_START) | ✓ |  |  |  |
| `--interval` | logging | seconds between polls (default: config, $INTERVAL or 10) |  | ✓ live |  |  |
| `--local-time` | logging | log timestamps in the system time zone instead of UTC |  |  |  | ✓ |
| `--log-access` | logging | log client connects/disconnects at INFO instead of DEBUG | ✓ | ✓ live |  | ✓ live |
| `--log-level` | logging | log level (default: config, $LOG_LEVEL or INFO) | **✓** live | **✓** live | **✓** | **✓** live |
| `--log-queries` | logging | log proxied Prometheus queries at INFO level |  |  |  | ✓ live |

Legend: ✓ = the tool has the knob (**bold** = all four do); `live` = settable on a running daemon (`set <name> <value>` over the control plane); `secret` = a token — never rendered inline by `show config` (the `-file` form is). The description is the shared registry text (the same one `--help`, the man pages, `show knobs` and the bundled configs render), taken from the first tool that defines the knob and with its default filled in — where the tools word a knob differently, the tool's own `--help`/man page wins.
