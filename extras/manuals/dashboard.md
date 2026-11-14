# dashboard

> **Experimental — work in progress.**

The dashboard is the family's one human surface: a small HTTP server,
bundled with the pv-suite tree and dependency-free (Python stdlib only),
that serves a single-page home PV monitoring page — the energy flow
diagram, the energy summary and the chart — and proxies the page's
Prometheus queries to a real Prometheus upstream. The browser never
talks to Prometheus directly; every query rides the server's `/prom`
proxy, so the collector stays behind the dashboard's bind address.

The server is one HTML document, one stylesheet, a handful of JavaScript
files and a proxy. The static app reads its configuration from
`/config.js` (the `SOLAR_CONFIG` object — the metric selectors, the
scrape interval, the language) and polls the proxied Prometheus query
API on an interval. Battery support is always enabled — the battery
panels are always on, the old switch retired — and the per-phase
voltage and current chains render a three-phase health strip when the
selectors are configured.

Everything the server does beyond serving the page — the connection
caps, the log surface, the config reload, the graceful shutdown — is
steered over the family's signed JSON-lines control wire with
`dashboard-cli`, and every control command lands in the hash-chained
audit trail. `SIGHUP` re-reads the config file. The flag, env and
default reference is `--help` and the generated man page
(`dashboard --man`).

## The family

```text
device (SUN2000 inverter)
   |
   v
modbus-cache :15502 <---- modbus-replay (the capture/replay sidecar,
   |                       standing in for the device while debugging)
   v
modbus-scraper :9350 ---> Prometheus :9090 ---> dashboard :8080
```

Every hop is optional — the scraper can poll the device directly, and
Prometheus can be any collector that answers the query API — but the
shaped deployment is the diagram, and the dashboard sits at the
read-only end of the chain: it speaks Prometheus's query API on the way
out and the family's control plane on the way in, and it never touches
Modbus. The [modbus-scraper](../../apps/scraper/README.md) serves
exactly the metrics the page expects — the Prometheus job name must be
`sun2000`, the name the selectors filter on.

## How it works

One process, three surfaces: the page, the proxy, the control socket.

- The static surface serves the app from `static/` (or
  `--static-dir`): `index.html`, `app.js`, `boot.js`, `i18n.js`,
  `style.css` and the vendored `vendor/echarts.min.js` (Apache ECharts
  5.5.1). One HTML document — there is nothing to navigate.
- The front-end configuration is served at `/config.js`: the server
  renders whatever `--config-js` names (the shipped sample is
  `examples/config.js`) as the `SOLAR_CONFIG` object — the metric
  selectors, the phase chains, the scrape and refresh intervals.
- The proxy forwards every request under `--prom-prefix` (the default
  `/prom`) to the upstream Prometheus (`--upstream`, env `PROM_URL`),
  with a fixed 30-second proxy timeout; an empty prefix proxies
  everything. The browser's queries never leave the dashboard's origin.
- The control socket — a unix socket at `/tmp/dashboard-<port>.socket`
  by default — speaks the family's JSON-lines wire and carries the live
  settings, the reload and the shutdown.
- When `--metrics-server` is on, a fourth surface appears: the
  dashboard's own Prometheus endpoint on `--metrics-listen` (see
  [Metrics](#metrics)).
- The repo also ships `screenshots/demo.png` — a rendered capture of
  the page, used by the README, not served by the daemon.

A request's walk: the connection caps and the bearer gate first
(loopback serves tokenless), then the route — a static file from the
static dir, `/config.js` rendered from the configured sample, or
`/prom/...` proxied upstream with the fixed 30-second timeout. The
page is one document: on load it fetches `/config.js`, then polls the
proxied query API on its interval and redraws the flow diagram, the
summary and the chart — the vendored ECharts doing the drawing.

## Source layout

The subproject, entry by entry:

```text
apps/dashboard/
├── bin/
│   ├── dashboard.py            # the daemon: the HTTP server, the proxy, the signal handling
│   └── dashboard-cli.py        # the control client (a symlink to the family's
│                               #   pvsuite-cli, apps/pvsuite-cli.py)
├── lib/
│   ├── control.py              # the JSON-lines control server
│   ├── metrics.py              # the /metrics endpoint
│   ├── config.py               # the config script, the env layer, the resolution ladder
│   ├── options.json            # the knob registry — one row per knob
│   ├── options.py              # the registry loader
│   ├── statics.py              # the shipped defaults for the static surface
│   ├── defaults.json           # the packaged defaults
│   ├── man.py                  # the man pages' prose (the pages render from it)
│   └── cli_spec.py             # the client SPEC — the per-tool half of pvsuite-cli
├── static/                     # the served page: index.html, app.js, boot.js, i18n.js,
│                               #   style.css, vendor/echarts.min.js (Apache ECharts 5.5.1)
├── examples/                   # the generated example conf + the shipped config.js sample
├── man/                        # the shipped man pages
├── screenshots/                # demo.png — used by the README, not served
├── dev, dev-cli                # the dev wrappers
└── README.md                   # the front page
```

The client page ([pvsuite-cli.md](pvsuite-cli.md)) covers the console
half; the served page lives in `static/` (`--static-dir` moves it).

## Installing

### From the tree

The tool runs straight from a checkout — Python 3, stdlib only:

```bash
python3 apps/dashboard/bin/dashboard.py --help
python3 apps/dashboard/bin/dashboard.py --man   # the generated man page
```

The bins are plain files run with `python3` — no exec bits, no install
step; the man pages ship generated under `apps/dashboard/man/`.

### Nix / NixOS

The package lives at `nixos/pkgs/dashboard/package.nix` and the service
module at `nixos/modules/dashboard.nix`, documented in
[nixos/README.md](../../nixos/README.md) and [Deployment](#deployment);
on NixOS, `services.dashboard.enable = true;` is the whole adoption.

### Docker

The image recipe is `docker/Dockerfile.dashboard` (alpine, the
unprivileged `pvsuite` user, the shared entrypoint) and the demo pairs
it with `Dockerfile.prometheus`. The image's env-file sample is
`docker/env/dashboard.env.example`; the compose stacks are documented
in [docker/README.md](../../docker/README.md).

## Quick start

The minimal run needs nothing but a reachable Prometheus — the defaults
bind loopback and assume the collector at `http://localhost:9090`:

```bash
# the collector upstream, the page on loopback
python3 apps/dashboard/bin/dashboard.py

# or through the env twin (the flags spell --listen/--upstream)
PROM_URL=http://pi:9090 python3 apps/dashboard/bin/dashboard.py
```

Open `http://localhost:8080`. The page polls `/prom` every `scrapeSec`
seconds (10 in the shipped sample) and redraws the flow diagram, the
energy summary and the chart. The Prometheus job name must be
`sun2000` — the shipped sample `config.js` selects the scraper's
`huawei_*` metrics with `{job="sun2000"}` matchers. Before anything
binds beyond loopback, read [Access control](#access-control): a
token-less non-loopback bind refuses to start.

## Configuration

### How a setting resolves

Every knob resolves along the family's one ladder: the CLI flag wins
over the environment twin, the environment wins over the config script,
and the config script wins over the registry's built-in default. The
env names are bare upper-snake words (`LISTEN`, `PROM_URL`,
`AUTH_TOKEN`, ...). The config file is a set-grammar script: every line
is a `set <name> <value>` — the live path as words, the same line
pastes into the console or a `dashboard-cli` batch — and every comment
is a `#` comment. `show config` re-renders the effective script; secret
values never render back (`*** SECRET REMOVED ***`).

The file search order for `--config` is the `CONFIG` env, then
`dashboard.conf` next to the script, then the subproject root.
`--dry-run` validates the configuration, prints the effective settings
and exits without binding anything.

### The knobs

The registry below is mined from the generated man page and
`apps/dashboard/lib/options.json` — the one-knob-one-source rows. The
live column: **live** — settable on the control wire now; **restart** —
a live `set` records the pending value, the restart applies it;
**start** — startup-only, the wire refuses to set it.

| knob (live path) | flag | env | default | live | what it does |
|---|---|---|---|---|---|
| `system/listen` | `--listen` | `LISTEN` | `127.0.0.1:8080` | restart | the page's bind address |
| `upstream` | `--upstream` | `PROM_URL` | `http://localhost:9090` | start | upstream Prometheus URL |
| `prom-prefix` | `--prom-prefix` | `PROM_PREFIX` | `/prom` | start | path under which Prometheus is proxied; empty proxies everything |
| `static-dir` | `--static-dir` | `STATIC_DIR` | the package's `static/` | start | directory to serve |
| `config-js` | `--config-js` | `CONFIG_JS` | — | start | config.js to serve at `/config.js` |
| `max-clients` | `--max-clients` | `MAX_CLIENTS` | `64` | live | refuse further connections past this many clients, 0 = no limit |
| `client-timeout` | `--client-timeout` | `CLIENT_TIMEOUT` | `300` | live | disconnect clients silent for this many seconds, 0 = never |
| `max-conn-per-ip` | `--max-conn-per-ip` | `MAX_CONN_PER_IP` | `0` | live | per-peer-IP connection cap, 0 = no limit |
| `auth/token` | `--auth-token` | `AUTH_TOKEN` | — | start | the page's bearer token, mandatory beyond loopback; `?auth=` bootstraps the session cookie |
| `control/port` | `--control-port` | `CTL` | `/tmp/dashboard-8080.socket` | live | unix socket path or TCP port on 127.0.0.1; 0 = off |
| `control/token` | `--control-token` | `CONTROL_TOKEN` | — | start | the admin control token; TCP control without one refuses to start |
| `control/ops/token` | `--control-ops-token` | `CONTROL_OPS_TOKEN` | — | start | the second, read-only control token |
| `control/ops/verbs` | `--control-ops-verbs` | `CONTROL_OPS_VERBS` | `show` | live | the ops role's RBAC policy, comma-separated verbs |
| `control/trust-uids` | `--control-trust-uids` | `CONTROL_TRUST_UIDS` | — | live | extra peer uids the unix socket trusts without the token |
| `control/socket-group` | `--control-socket-group` | `CONTROL_SOCKET_GROUP` | off | live | leave the unix socket group-accessible (0660 instead of 0600) |
| `system/log-replies` | `--control-log-replies` | `CONTROL_LOG_REPLIES` | off | live | DEBUG-log the full output of every control command |
| `metrics/enable` | `--metrics-server` | `METRICS_SERVER` | off | live | serve the dashboard's own Prometheus `/metrics` endpoint |
| `metrics-listen` | `--metrics-listen` | `METRICS_LISTEN` | `127.0.0.1:9353` | start | the metrics bind address |
| `metrics/token` | `--metrics-token` | `METRICS_TOKEN` | — | start | the `/metrics` bearer token, mandatory beyond loopback |
| `metrics/acl` | `--metrics-acl` | `METRICS_ACL` | `any` | live | clients allowed on `/metrics`: `any`, `none`, IPs/prefixes, `file:<path>` |
| `metrics-max-clients` | `--metrics-max-clients` | `METRICS_MAX_CLIENTS` | `64` | start | concurrent `/metrics` client cap, extras get 503, 0 = unlimited |
| `metrics-client-timeout` | `--metrics-client-timeout` | `METRICS_CLIENT_TIMEOUT` | `5` | start | idle `/metrics` client kick, 0 = the built-in 5 s cap |
| `metrics-max-conn-per-ip` | `--metrics-max-conn-per-ip` | `METRICS_MAX_CONN_PER_IP` | `0` | start | per-IP `/metrics` cap, 0 = no limit |
| `audit/log-file` | `--audit-log` | `AUDIT_LOG` | the XDG state home | live | the audit trail: a path, `-` for stdout, `none` = no local file |
| `audit/forward` | `--audit-forward` | `AUDIT_FORWARD` | `none` | live | mirror every audit line: `syslog`, `syslog:/path`, `udp://`, `tcp://` |
| `audit/forward/format` | `--audit-forward-format` | `AUDIT_FORWARD_FORMAT` | `rfc5424` | live | the remote envelope: `rfc5424` or `cef` |
| `audit/instance` | `--audit-instance` | `AUDIT_INSTANCE` | the control port | live | the audit lines' `instance=<id>` writer word |
| `audit/rotate/max-size` | `--audit-max-mb` | `AUDIT_MAX_MB` | `10` | live | rotate the audit log at this size in MB, 0 = off |
| `audit/rotate/daily` | `--audit-daily` | `AUDIT_DAILY` | off | live | also rotate the audit log at UTC midnight |
| `audit/rotate/files` | `--audit-files` | `AUDIT_FILES` | `3` | live | rotated audit backups to keep |
| `audit/disable` | `--no-audit-log` | `NO_AUDIT_LOG` | off | live | disable the audit trail entirely |
| `system/log-level` | `--log-level` | `LOG_LEVEL` | `INFO` | live | DEBUG logs every request and the gate decisions |
| `log-queries` | `--log-queries` | `LOG_QUERIES` | off | live | log proxied Prometheus queries at INFO |
| `system/log-access` | `--log-access` | `LOG_ACCESS` | off | live | log every HTTP request at INFO |
| `system/local-time` | `--local-time` | `LOCAL_TIME` | off | live | log timestamps in the system time zone instead of UTC |
| `dump/path` | `--dump-path` | `DUMP_PATH` | — | live | the state dump file for the live overrides |
| `dump/key` | `--dump-key` | `DUMP_KEY` | — | start | the key that seals the state dumps and the reload's state file |
| `dump/interval` | `--dump-interval` | `DUMP_INTERVAL` | `0` | live | seconds between automatic state dumps, 0 = on request |
| `dump/restore-on-start` | `--restore-on-start` | `RESTORE_ON_START` | off | restart | load the state dump when the daemon starts |

### The config file

The shipped example is
[dashboard.conf](../../apps/dashboard/examples/dashboard.conf) —
generated from the registry, every knob declared, every line commented.
Copy it, uncomment what changes, and point `--config` at it; an excerpt:

```conf
# upstream Prometheus URL
# set upstream http://localhost:9090

# simultaneous client limit
# set max-clients 64

# --- auth ---

# a secret — pass it as file:<path>, an owner-only 0600 file
# set auth token file:/run/credentials/dashboard/auth-token
```

### Secrets

Every secret knob — the page token, the two control tokens, the metrics
token, the dump key, and the two startup paths `static-dir` and
`config-js` — takes the `file:<path>` form: the value is read as the
first line of an owner-only 0600 file (a systemd `LoadCredential` rides
as `file:/run/credentials/...`). A secret's value never renders back —
`show <secret>` refuses, `show config` spells the placeholder, and the
wire refuses `set`/`clear` on the startup-only secrets: they change by
flag/env/config and a restart, there is no live rotation.

## Runtime control

Two signals: `SIGHUP` re-reads the config file and applies what is live
(the same path as the control server's `request reload-config`; the
listen address and port are bound and stay), and `SIGTERM`/`SIGINT`
shut the daemon down gracefully — the consoles get the daemon-exit
frame.

The knobs divide three ways. Live knobs apply the moment the wire
accepts the `set`. Restart-marked knobs (the listen address,
`dump/restore-on-start`) record the pending value and apply it on the
next restart — the reload path re-applies recorded pendings once the
fresh daemon is up. Startup-only knobs — every secret — refuse the live
`set` outright. With `--dump-path` configured the live overrides save
to the state dump (`request dump`, the graceful shutdown, every
`--dump-interval` seconds); `request reload` saves them, re-execs and
re-applies them once; `--restore-on-start` loads them at start,
`request restore` on demand.

One worked console sequence — the same lines work one-shot, piped as a
batch, or interactively:

```text
$ python3 apps/dashboard/bin/dashboard-cli.py
dashboard:8080 > set log-queries on
% changed
dashboard:8080 > show max-clients
64
dashboard:8080 > request reload-config
ok
```

## Persistence

The dashboard holds no history — the Prometheus upstream keeps the
series — and the dump family carries the part of a restart the page
would feel: the live setting overrides. With `--dump-path` configured,
`request dump` writes them as one JSON document, `--dump-interval`
writes on a cadence, the graceful shutdown writes a final dump, and
`--restore-on-start` loads it at start.

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

## The control plane

`dashboard-cli` is the client: one-shot command words
(`dashboard-cli show config` — exit 0 ok, 1 connection error, 2
misuse), a piped stdin batch (the script lines run in order), or a bare
terminal for the interactive console — prompt with the connected port,
TAB completion and `?` in every position, a pager for tall replies
(`--page-size`/`CLI_PAGE_SIZE`), a reconnect loop when the connection
dies (`--reconnect`, `--reconnect-wait`), and the target auto-detected
to the default unix socket when `--control-port` (env `CTL`) is unset.

The verbs are the family's: `set`/`clear`/`show` over the settings
(the caps, the log surface, the metrics ACL, the control knobs, the
audit and dump knobs), `show connections`, `show version`, `show
knobs`, `show metrics-acl-table`, `show config`, `inspect`, `ping`,
`request reload-config` (the SIGHUP path), `request reload` (the
whole-daemon restart that keeps the sets), `request dump`/`request
restore` (with a dump path configured), `help`, `shutdown`, `quit`.

The wire is JSON lines — `{"cmd": "..."}` in, one
`{"status": "ok|fail|note|bye", "text": "..."}` reply out. With a
control token configured every frame carries the full sha256 HMAC of
its payload keyed by the token (`common/wire/wiresec.py`): the client
verifies both directions, and over TCP the signed commands are
mandatory. TCP control without an admin token refuses to start (F5);
over the unix socket a trusted peer — root, the daemon's own user, or
the `--control-trust-uids` list (SO_PEERCRED) — skips the token
handshake. The read-only ops token (`--control-ops-token`) scopes its
sessions to its policy's verbs (the default policy: `show`; no
`set`/`clear`, no reload, no shutdown) — both roles audited. The
command string folds to the grammar's printable 8-bit before the
server decides on it (NFKD, then the printable-ascii range only).

## Access control

The page's auth is the F13 shape with the F21 gate closed: the bearer
token (`--auth-token`, constant-time compared) is mandatory beyond
loopback — a token-less non-loopback bind refuses to start — and the
loopback bind serves tokenless. A request carrying `?auth=<token>`
exchanges it for an HttpOnly session cookie; the raw `Authorization:
Bearer` header stays for scripts. TLS terminates at an authenticating
reverse proxy — plain HTTP carries the token in the clear, so anything
beyond localhost rides the proxy (the F14 answer).

The HTTP surface has no per-request authorization beyond that bearer
gate: a client holding the token reads the page, the proxy and
`/metrics`. There is no role model, no per-path ACL and no multi-user
story on the HTTP side today — the audit's open F21 item. Bind the page
to loopback or behind an authenticating reverse proxy.

The control plane is the strongly-authenticated half: the unix socket
is 0600 (0660 with `--control-socket-group`), TCP control refuses to
start token-less (F5), the wire is HMAC-signed when a token is set, and
the ops role scopes its sessions to its RBAC policy. The dashboard's
own `/metrics` endpoint speaks the family's F13 posture: when
`--metrics-server` is on, a token is mandatory beyond loopback — a
token-less non-loopback metrics bind refuses to start (F13) — and the
`--metrics-acl` gate checks the peer IP at accept — a client off the
ACL is closed without a reply, `show metrics-acl-table` the table.

## Metrics

With `--metrics-server` on, the daemon serves its own Prometheus
endpoint at `--metrics-listen` (default `127.0.0.1:9353` — the family's
935x band). The gauges are self-observability, not the PV values — the
page and the proxy already serve those:

```text
dashboard_uptime_seconds              the process uptime
dashboard_requests_total              HTTP requests by status class (2xx/4xx/5xx)
dashboard_prom_queries_total          proxied Prometheus queries
dashboard_upstream_ok                 1 = the last proxied query reached upstream
dashboard_clients                     active HTTP clients (the family gate)
dashboard_max_clients                 the configured total client cap
```

Point any Prometheus at the endpoint and the dashboard's health joins
the same scrape it feeds; the toggle is live (`set metrics enable on`
serves the endpoint without a restart — the caps themselves are
startup-only).

## The audit trail

Every control command with its role, every auth failure, every reload
and every shutdown lands in the hash-chained audit trail — each line
carries the chain hash of its predecessor, so tampering shows.
`--audit-log` names the file (the default is the XDG state home,
`~/.local/state/dashboard/audit.log`, lines prefixed `DSH`); `-` logs
to stdout (the docker/journald way) and `none` turns the local file off
— with a forward spelled that is the remote-only mode, without one the
audit is disabled (`--no-audit-log` spells the same state).

`--audit-forward` mirrors every line — the hash chain included — to a
second sink: `syslog` (the local socket auto-scan), `syslog:/path` (an
explicit socket), `udp://host[:514]` (RFC5426, best-effort) or
`tcp://host[:514]` (RFC6587 framing). A scheduled search at the
collector can chain-verify the forwarded lines and alert on a break.
The remote envelope rides `--audit-forward-format` (`rfc5424`, the
default, or `cef`); the local syslog forms keep the verbatim send; a
send failure notes once and the next event re-arms.

Rotation: `--audit-max-mb` (10 MB default) rotates at size,
`--audit-daily` adds a UTC-midnight trigger, `--audit-files` keeps the
backups (3 default). Every line names its writer daemon in
`instance=<id>` — the control port when `--audit-instance` is unset,
the override when spelled; make an override unique among everything
sharing one collector, the chain groups by it.

## Tuning

The connection surface carries the family's gate: `--max-clients`
totals the simultaneous clients (extras get an immediate 503),
`--max-conn-per-ip` caps one peer IP, and `--client-timeout` kicks
idle keep-alive connections after the silence window (0 = never). The
same three shapes exist for the `/metrics` endpoint with the
`metrics-` prefix; the proxy timeout is a fixed 30 seconds — a static,
not a knob. Verbosity is a knob too: `--log-queries` and
`--log-access` turn the request-level logs on, `--log-level DEBUG` adds
the gate decisions and the proxy detail; on the client side,
`dashboard-cli --timeout` bounds the socket wait and `CLI_KEEPALIVE`
spaces the idle pings.

## Deployment

### The NixOS module

`services.dashboard` wraps the daemon in the family's hardened unit:

- `enable` — the switch; `package` — the dashboard package.
- `settings` — the daemon's environment, every entry rendered verbatim
  as `NAME=value` into the systemd `EnvironmentFile` (the bare
  upper-snake env twins; the generated
  `docker/env/dashboard.env.example` documents the key list). The
  secret env names are refused here — the env file lands in the
  world-readable nix store.
- `solarConfig` — the `SOLAR_CONFIG` attrset, rendered into a store
  `config.js` the module points `CONFIG_JS` at (a `settings.CONFIG_JS`
  path takes precedence).
- `staticDir` — override the packaged `static/` assets;
  `openFirewall` — the port hole for direct LAN access.
- The credential options — `authTokenFile`, `controlTokenFile`,
  `controlOpsTokenFile`, `metricsTokenFile`, `dumpKeyFile` — mount the
  secrets via systemd `LoadCredential` (absolute paths outside the
  store, refused otherwise) and carry them as `file:` pointers.
- `user`/`group` — the service account (`pvsuite` is the family's
  shared identity); null keeps the systemd `DynamicUser`.

The unit itself: `ExecReload` sends `SIGHUP`, `Restart = on-failure`,
and the sandbox is the full pass — read-only filesystem, no `/home`,
private `/tmp`, no device nodes, the empty capability bounding set,
`AF_UNIX` + INET address families only (the unix control socket needs
`AF_UNIX` to bind at all), the `@system-service` call filter. A `CTL`
under `/tmp` warns — `PrivateTmp` hides it; the module suggests
`/run/dashboard/`.

### Docker

The image (`docker/Dockerfile.dashboard`) runs as the unprivileged
`pvsuite` user and binds `0.0.0.0:8080` (the `CMD` flag; a published
port needs the token — the F21 rule holds in-container). The bundled
`dashboard.conf` loads via the built-in default `--config` target
(`/pv-suite/dashboard/dashboard.conf`); env overrides it knob by knob.
`CONFIG_JS` points at the config volume (`/config`, seeded on start,
edits survive recreation). The healthcheck is `dashboard-cli ping` over
the unix control socket — the check runs as root, a trusted peer over
SO_PEERCRED, so no token is needed. Build and run:

```bash
cd docker
docker build -f ../docker/Dockerfile.dashboard -t dashboard \
    --build-context scripts=../docker --build-context common=../common \
    --build-context shared=../shared --build-context cli=../apps ../apps/dashboard
docker run --rm -p 127.0.0.1:8080:8080 -e PROM_URL=http://prometheus:9090 dashboard
```

The env file (`docker/env/dashboard.env.example`) is the plain-docker
spelling — the compose stacks do not read it: the stacks' `PROM_URL`
and the page token are compose-level environment, and the page secret
rides the compose secret staged at `/run/pv-secrets/page-token`. The
published port stays loopback-only; the demo pairing with Prometheus is
`Dockerfile.prometheus` and the compose stacks under `docker/demo/` and
`docker/prod/`.

## Troubleshooting

- **The daemon exits 1 with a cannot-bind error.** The page's
  `LISTEN` address is taken — one `cannot bind` ERROR line on stderr,
  no traceback, exit 1. The failed bind answers with a reason, and
  `--dry-run` (exit 0 valid, 1 invalid, 2 misuse) validates the whole
  configuration without binding anything.
- **The page loads but the panels stay empty.** The upstream is
  unreachable or the job name is wrong. The proxy answers, so the
  browser sees no error — check `dashboard_upstream_ok` on the metrics
  endpoint (`0` = the last query missed), run with `--log-queries on`
  to see the proxied queries and their statuses, and confirm the
  Prometheus job is `sun2000`.
- **`/config.js` fails to load.** `CONFIG_JS` names a path the daemon
  cannot read — a startup-only knob, so the fix is flag/env/config and
  a restart; a missing file breaks the page's bootstrap.
- **A token-less non-loopback bind refuses to start.** That is the F21
  gate: bind loopback, or pass `--auth-token` (a `file:<path>` value
  from an owner-only 0600 file). The same refusal guards the metrics
  bind beyond loopback without `--metrics-token` (F13) and a TCP
  control port without `--control-token` (F5).
- **The console answers `connection refused`.** The control target is
  wrong — the default unix socket is `/tmp/dashboard-8080.socket` (the
  page port in the name); under a NixOS `PrivateTmp` sandbox it must
  live under `/run/dashboard/`.
## Testing

The dashboard's fuzz suite is
[dashboard-control-fuzz.py](../../dev/suites/dashboard-control-fuzz.py)
— malformed, hostile and degenerate JSON-line requests against the
control server: every request must draw a well-formed reply frame (or a
clean close) and the daemon must stay alive and serving afterwards. The
family's `check-options`, `links-check`, `lint-gates` and `audit-chain`
suites cover the registry rows, the docs and the audit chain. The
suites always run through the battery runner — never standalone — the
runner owns the run dir, the port slots and the tally:

```bash
python3 dev/battery/battery.py dashboard   # the dashboard's commit set
```

## The docs map

| document | what it holds |
|---|---|
| [apps/dashboard/README.md](../../apps/dashboard/README.md) | the tool's README — usage, security, license |
| [apps/dashboard/lib/options.json](../../apps/dashboard/lib/options.json) | the knob registry — the one-knob-one-source rows |
| [apps/dashboard/examples/dashboard.conf](../../apps/dashboard/examples/dashboard.conf) | the generated config example — every knob, all commented |
| [apps/dashboard/examples/config.js](../../apps/dashboard/examples/config.js) | the shipped front-end config sample, served at `/config.js` |
| [apps/dashboard/man/dashboard.1](../../apps/dashboard/man/dashboard.1) | the daemon's generated man page |
| [apps/dashboard/man/dashboard-cli.1](../../apps/dashboard/man/dashboard-cli.1) | the ctl client's generated man page |
| [nixos/modules/dashboard.nix](../../nixos/modules/dashboard.nix) | the NixOS service module |
| [docker/Dockerfile.dashboard](../../docker/Dockerfile.dashboard) | the image recipe |
| [docker/env/dashboard.env.example](../../docker/env/dashboard.env.example) | the generated env-file sample |
| [apps/dashboard/static/](../../apps/dashboard/static/) | the served frontend — the page, the app, the vendored ECharts |
| [docs/SECURITY.md](../../docs/SECURITY.md) | the family's security model — the tokens, the gates, the audit |
| [docs/specs/ACL.md](../../docs/specs/ACL.md) | the access-control spec — the gate types and grammars |
| [nixos/README.md](../../nixos/README.md) | the NixOS adoption — modules, packages, tests |
| [docker/README.md](../../docker/README.md) | the container topologies — demo and prod stacks |
| [docs/book/src/index.md](../../docs/book/src/index.md) | the book — the family rendered as chapters |

## License

The dashboard code (server, page, Nix packaging) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file. The bundled chart
library `static/vendor/echarts.min.js` is
[Apache ECharts](https://echarts.apache.org/) 5.5.1, licensed under the
**Apache License 2.0** (© the Apache Software Foundation); the license
notice is preserved in the vendored file.
