# The family drift — the shared-code sweeps (regenerated)

The wave record: the sweep types over the four surfaces (cache,
scraper, inverter, dashboard) — what each sweeps, what it found,
and the verdicts. **Ships in the repo, kept current by the
workflow**: the open findings wait in place, and `--check` fails
a stale page. Regenerate with `python3 scripts/family_drift.py`;
the verdict prose lives in this script (`*_FINDINGS`/`*_VERBS`/
`*_CENSUS`) so a re-run updates the facts and keeps the
judgement. This doc carries the CURRENT findings only — the
landed legs and the wave history live in
[history/family-drift.md](history/family-drift.md).

The sweep types:

1. **The code sweep** (text-structural) — AST-normalized function
   bodies, exact-hash grouped + pairwise similarity. Finds what
   should fold into `common/`.
2. **The surface sweep** (architectural) — the listeners, the wire
   tiers, the loop machinery. Finds the shapes that are the same
   but live in different bodies.
3. **The knobs sweep** (registry) — the four registries by name,
   by field, by family.
4. **The wire-text sweep** — the log/audit canon: the event names,
   the shared phrases, the near-misses.
5. **The exit-and-refusal sweep** — the SystemExit ladders, the rc
   discipline, the refusal texts.
6. **The rendered-surface sweep** — the man/`--help`/README section
   ladders diffed by structure.
7. **The NixOS-parity sweep** — the module.nix option types and
   defaults against the registries.
8. **The docker/env sweep** — the env twins and the published
   ports against the registries.
9. **The suite-coverage sweep** — the promises (knobs, commands,
   canon phrases) grepped against the tests.
10. **The F-ledger sweep** — docs/AUDIT.md's F-numbers vs the
    tree's enforcement markers.
11. **The statics sweep** — the four defaults.json blocks by
    key-path.
12. **The schema/example sweep** — the JSON Schemas vs the
    registries; the shipped examples re-parsed.
13. **The secret-surface sweep** — the secret rows and the
    posture markers.

## The code sweep — the text-structural pass

Every per-tool `lib/*.py` and `bin/*.py` function, AST-normalized (the
line numbers and the local names collapse, the constant values stay),
compared two ways: the exact pass groups identical bodies (the
copy-paste twins), the similarity pass pairs cross-file bodies over the
0.72 ratio (the near-copies that already drifted).

**The exact pass**: 1 duplicate group(s) in >= 2 files.

- 24L `_load_options`: `dashboard/lib/options.py:25`, `scraper/lib/options.py:26`

**The similarity pass**: 51 cross-file pair(s) over the ratio
floor (30 of them the man-page prose, per-tool by
design); the top non-man pairs:

| ratio | pair |
|---|---|
| 1.00 | `scraper/lib/options.py:26` `_load_options` <-> `dashboard/lib/options.py:25` `_load_options` |
| 0.94 | `scraper/lib/control.py:144` `command_help` <-> `dashboard/lib/control.py:109` `command_help` |
| 0.94 | `cache/lib/options.py:24` `_load_options` <-> `scraper/lib/options.py:26` `_load_options` |
| 0.94 | `cache/lib/options.py:24` `_load_options` <-> `dashboard/lib/options.py:25` `_load_options` |
| 0.93 | `scraper/bin/modbus-scraper.py:45` `parse_args` <-> `dashboard/bin/dashboard.py:279` `parse_args` |
| 0.89 | `scraper/bin/modbus-scraper.py:251` `graceful_stop` <-> `dashboard/bin/dashboard.py:483` `graceful_stop` |
| 0.88 | `cache/lib/options.py:24` `_load_options` <-> `inverter/lib/options.py:27` `_load_options` |
| 0.88 | `inverter/lib/options.py:27` `_load_options` <-> `dashboard/lib/options.py:25` `_load_options` |
| 0.88 | `scraper/lib/options.py:26` `_load_options` <-> `inverter/lib/options.py:27` `_load_options` |
| 0.86 | `cache/bin/modbus-cache.py:48` `parse_args` <-> `scraper/bin/modbus-scraper.py:45` `parse_args` |
| 0.85 | `cache/bin/modbus-cache.py:48` `parse_args` <-> `dashboard/bin/dashboard.py:279` `parse_args` |
| 0.82 | `cache/bin/modbus-cache.py:357` `watch_dump` <-> `common/wire/control.py:1227` `run_dump_interval` |
| 0.79 | `inverter/lib/control.py:155` `__init__` <-> `dashboard/lib/control.py:81` `__init__` |
| 0.78 | `inverter/lib/signals.py:78` `__init__` <-> `common/modbus/client.py:20` `__init__` |
| 0.78 | `inverter/lib/control.py:506` `acl_table_report` <-> `dashboard/lib/control.py:327` `acl_table_report` |
| 0.76 | `scraper/lib/server.py:97` `relay` <-> `dashboard/bin/dashboard.py:175` `relay` |
| 0.75 | `inverter/lib/control.py:66` `handle` <-> `common/wire/control.py:292` `handle` |
| 0.74 | `cache/lib/config.py:116` `load_profile_write_gate` <-> `common/settings/config.py:420` `load_write_gate_file` |
| 0.73 | `inverter/lib/control.py:517` `command_help` <-> `dashboard/lib/control.py:109` `command_help` |
| 0.73 | `scraper/lib/control.py:144` `command_help` <-> `inverter/lib/control.py:517` `command_help` |

## The surface sweep — the listeners, the wire and the loops

The architectural pass: every listener the family opens, the wire tier
it speaks, the loop machinery behind it. The census is generated from
the tree; the verdicts are editorial.

The listener census (ten listeners):

| tool | surface | the class at it | the bind | the stack at it |
|---|---|---|---|---|
| inverter | Modbus TCP (the device) | `serve_modbus` (common/modbus/server.py) under the fake's face object | backlog 128 | the shared ladder; the face's hooks carry the tool (the chaos injector, the counters) |
| cache | Modbus TCP (the client face) | `serve_modbus` (common/modbus/server.py) under the proxy's face object | backlog 128 | the shared ladder; the write-gate layers in `respond()` (shape -> allow-write -> write ACL -> register gate); the requests audit rides `on_disconnect` |
| inverter | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook is the tool's |
| cache | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook is the tool's |
| dashboard | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook is the tool's |
| scraper | /metrics (the exposition) | `Server` + `Handler` (lib/server.py) | the caps + the metrics/acl | its own Handler — the family's exposition shape (bearer, the spec render, the upstream relay) |
| dashboard | the page (static + proxy) | `Server` + `Handler` (bin/dashboard.py) | the caps | its own Handler — the cookies, the static tier, the /prom proxy, /config.js |
| all four | the control socket (unix, opt TCP) | `ControlServer` (common/wire/control.py) | 0600/0660 | the one shared wire: the token/RBAC roles, the HMAC frames, the caps live here |

The findings:

- **The face protocol's hooks.** The faces delegate (`Proxy.serve`,
  the fake's `serve`) into the one shared ladder and bring the face
  protocol's hooks: `listening`, `access`, `allowed`, `suite_key`,
  `on_frame`/`on_session`, `malformed`, `frame`, `on_disconnect` — the
  cache's audit trail `REQUESTS` event rides `on_disconnect`, the
  fake's counters ride `on_frame`/`on_session`. The backlog sits
  unified at 128, above every face's client limit.
- **The malformed-frame split (a policy hook, as ruled).** On an
  unparseable frame the `malformed(addr, err)` hook decides: the fake
  logs and closes; the cache answers what it can in-band
  (`respond`'s proto/pdu guards -> exception frame) and closes
  silently on the hopeless MBAP. The cache is a proxy — its client
  deserves the protocol answer; the device just hangs up. The hook
  keeps the difference without a fork.
- **The poll-loop skeleton (declined).** The cache's `poll_loop` and
  the scraper's are the same shape — `while True: try poll_once()
  except log-crashed; wait(interval) on a wake Event; clear` — with
  the deltas as the content (the cache's duration stats and the
  requests-audit timer; the scraper's clamped wait and the live
  interval re-read). A fold needs three hooks for two users; the
  shape is the doc's to keep, not the code's.
- **The /metrics tier (at parity).** The common server owns the
  401/404/200 ladder, the caps, the thread and the
  bind-in-caller's-context rule; the tools bring a `snapshot()` and
  name their realm and logger. No drift.
- **The control wire (at parity).** One `ControlServer` — the
  subclasses are grammars (`command`/`_apply`/`_get`) and their
  reports; the rebind family, the RBAC roles, the frame MAC and the
  fold/restore machinery live in the base. No drift.
- **The HTTP handlers (different by nature).** The scraper's
  exposition Handler and the dashboard's UI Handler both rhyme with
  the common metrics 401 (the bearer compare, the
  `WWW-Authenticate` realm) but route it through their own reply
  shapes — the exposition's `relay` and the page's session-aware
  ladder. Not foldable without losing the shapes that make each
  correct.

The verdict: the accept ladder and the session opener have one home
(the landed legs: [history/family-drift.md](history/family-drift.md));
the rest of the surface drift is at parity or declined with the
reasons above.

## The knobs drift — the four registries side by side

The registry pass: `lib/options.json` x 4 diffed by name, by field and
by semantic family — the knob layer is the one source --help, the man
pages, the set grammar, the NixOS modules and the README checks read,
so a drifted row travels wide.

**The shape**: 223 knob rows across the
four registries; 31 names carry in all four:

`audit`, `audit-daily`, `audit-files`, `audit-forward`, `audit-forward-format`, `audit-log`, `audit-max-mb`, `audit/rotate`, `auth`, `client-timeout`, `control`, `control-ops-token`, `control-ops-verbs`, `control-port`, `control-socket-group`, `control-token`, `control-trust-uids`, `control/ops`, `dump`, `dump-interval`, `dump-key`, `dump-path`, `listen`, `log-level`, `max-clients`, `max-conn-per-ip`, `metrics`, `metrics-acl`, `no-audit-log`, `restore-on-start`, `system`

**The tool-specific remainder** (by nature):

| tool | only-there knobs |
|---|---|
| cache | `acl`, `allow-write`, `auth-key`, `auth-upstream`, `auth-upstream-key`, `cache-ttl`, `connect-acl`, `dump-with-cache`, `interval`, `limits`, `local-time`, `log-access`, `merge-gap`, `metrics-client-timeout`, `metrics-listen`, `metrics-max-clients`, `metrics-max-conn-per-ip`, `metrics-server`, `metrics-token`, `metrics/limits`, `modbus`, `profile`, `read-delay`, `requests-audit`, `selection`, `timeout`, `unit`, `upstream`, `write`, `write-acl`, `write-registers` |
| scraper | `auth-key`, `auth-token`, `caps`, `grid-positive-import`, `interval`, `local-time`, `log-access`, `max-grid-kw`, `max-kwp`, `metric-prefix`, `metrics-spec`, `metrics/auth`, `metrics/limits`, `modbus`, `modbus-offset`, `modbus-unit`, `profile`, `timeout`, `upstream` |
| inverter | `allow-write`, `auth-key`, `batt`, `battery-kwh`, `battery-state`, `chaos`, `cloud`, `connect-acl`, `control-log-replies`, `grid`, `grid-frequency`, `grid-outage`, `grid-voltage`, `load`, `max-kwp`, `metrics-client-timeout`, `metrics-listen`, `metrics-max-clients`, `metrics-max-conn-per-ip`, `metrics-server`, `metrics-token`, `modbus`, `mppt`, `profile`, `pv`, `scenario`, `seed`, `soc`, `static`, `strict`, `time`, `time-scale`, `timezone`, `unit`, `write` |
| dashboard | `auth-token`, `config-js`, `local-time`, `log-access`, `log-queries`, `metrics-client-timeout`, `metrics-listen`, `metrics-max-clients`, `metrics-max-conn-per-ip`, `metrics-server`, `metrics-token`, `prom-prefix`, `static-dir`, `upstream` |

**The shared knobs whose fields disagree** (4 of
31 knobs, 9 drifted field(s)) — one row per
knob+field, the tools grouped by the value each carries:

| knob | field | the values (the tools carrying each) |
|---|---|---|
| `auth` | `flag` | `--auth` (cache, scraper, inverter) · `·` (dashboard) |
| `auth` | `env` | `AUTH` (cache, scraper, inverter) · `·` (dashboard) |
| `auth` | `conv` | `str` (cache, scraper, inverter) · `·` (dashboard) |
| `auth` | `live` | `modbus/auth` (cache, scraper, inverter) · `·` (dashboard) |
| `auth` | `values` | `['suite', 'none']` (cache, scraper, inverter) · `·` (dashboard) |
| `auth` | `node` | `·` (cache, scraper, inverter) · `True` (dashboard) |
| `client-timeout` | `live` | `limits/client-timeout` (cache) · `metrics/limits/timeout` (scraper) · `client-timeout` (inverter, dashboard) |
| `max-clients` | `live` | `limits/max-clients` (cache) · `metrics/limits/max-clients` (scraper) · `max-clients` (inverter, dashboard) |
| `max-conn-per-ip` | `live` | `limits/max-conn-per-ip` (cache) · `metrics/limits/max-conn-per-ip` (scraper) · `max-conn-per-ip` (inverter, dashboard) |

**The command vocabularies** (the wire words per tool):

- cache: `help`, `inspect`, `ping`, `quit`, `request`, `request/flush`, `request/flush/cache`, `request/dump`, `request/dump`, `request/dump/with-cache`, `request/reload`, `request/reload-config`, `request/restart`, `request/restore`, `set`, `show`, `shutdown`, `clear`
- scraper: `help`, `inspect`, `ping`, `poll`, `poll/now`, `quit`, `request`, `request/dump`, `request/reload`, `request/reload-config`, `request/restart`, `request/restore`, `set`, `show`, `shutdown`, `clear`
- inverter: `exit`, `help`, `inspect`, `logout`, `ping`, `quit`, `request`, `request/dump`, `request/reload`, `request/reload-config`, `request/restore`, `reset`, `set`, `show`, `shutdown`, `clear`
- dashboard: `help`, `inspect`, `ping`, `quit`, `request`, `request/dump`, `request/reload`, `request/reload-config`, `request/restore`, `set`, `show`, `shutdown`, `clear`

**The command deltas worth a ruling:**

- `request/clear/cache` + `request/dump/with-cache` — the cache only
  (the write-behind cadence and the flush verb are its nature).
- `request/restart` — absent on the fake (its reload execs and
  re-reads the conf already, so the verb would double it; the
  restart-marked overrides fold in the exec).
- `reset` (the SIGUSR1 scenario reset) + `exit`/`logout` — the fake's
  console verbs (F11).
- `poll/now` — the scraper's poll trigger.

The findings:

- **The `auth` name collision.** The dashboard's `auth` is a NODE
  (the page's auth namespace), the other three's is the modbus auth
  enum (`suite|none`). One spelling, two meanings in the family's
  set-grammar space — legal (the registries are per-tool), but the
  merged-knob view (docs/OPTIONS.md) and any future family-wide
  grammar should note it.
- **`KNOWN_VERBS` derives from the rows** (the landed leg): the
  loaders build the RBAC vocabulary from the registry's command rows
  (`known_verbs` in common/settings/options.py — the live path's
  first segment past `request`, the node rows out, the
  hidden/internal flags in, the console-eaten `exit`/`logout` out)
  and the default ops policy derives with it
  (`default_ops_verbs`: `clear` only where the grammar speaks it —
  the old family-wide `show,clear` accepted a verb three tools'
  wires refuse). One home; the drift class is dead.

The landed knob legs (the audit rotation bounds family-wide, the
`audit-daily` one shape, the env-or-note completion):
[history/family-drift.md](history/family-drift.md).

## The wire-text sweep — the log/audit canon

Every `logger.*` format string and every `audit.event` name,
inventoried per tool: the event names are the wire's vocabulary (the
regtests and the audit readers pin them), the log phrases are the
canon the operators grep for.

**The audit event names** (the wire's vocabulary):

| tool | events |
|---|---|
| cache | `ACL-FILE`, `RELOAD`, `REQUESTS`, `RESET`, `RESTORE`, `SHUTDOWN`, `START`, `WRITE`, `WRITE-FAILED`, `WRITE-REFUSED`, `WRITE-REJECTED` |
| scraper | `ACL-FILE`, `START` |
| inverter | `ACL-FILE`, `AUTH-FAIL`, `COMMAND`, `RELOAD`, `RESET`, `SHUTDOWN`, `START`, `WRITE`, `WRITE-REFUSED` |
| dashboard | `ACL-FILE`, `RELOAD`, `SHUTDOWN`, `START` |
| common | `AUTH-FAIL`, `COMMAND`, `CONNECT`, `DISCONNECT`, `RECONNECT`, `RELOAD` |

**The phrase canon**: 30 log phrase(s) shared by >= 2 tools;
83 tool-local. The canon (the lead clause, the tools that speak it):

| the lead clause | tools |
|---|---|
| `acl file:` | cache, dashboard, inverter, scraper |
| `stopped` | cache, dashboard, inverter, scraper |
| `write:` | cache, inverter |
| `write: refused` | cache, inverter |
| `control client from` | common, inverter |
| `client` | dashboard, scraper |
| `shutdown:` | cache, dashboard, inverter, scraper |
| `the state dump` | cache, common, inverter |
| `state dumped to` | cache, common |
| `connection rejected:` | common, scraper |
| `unhandled error serving` | dashboard, scraper |
| `dry-run: configuration is valid nothing was boun` | dashboard, inverter, scraper |
| `cannot bind` | dashboard, scraper |
| `restore-on-start:` | dashboard, inverter, scraper |
| `control from` | common, inverter |
| `control: state dumped to` | cache, common |
| `control: state restored from` | cache, common |
| `control: the dump to` | cache, common |
| `sighup: reloaded` | cache, inverter |
| `poll cycle crashed ` | cache, scraper |
| `state dumps:` | cache, common |
| `the read-only ops token supplements the admin to` | cache, inverter |
| `the ops token must differ from the admin token t` | cache, inverter |
| `cannot serve on` | cache, inverter |
| `the shutdown dump to` | cache, common |

The findings:

- **The audit vocabulary is tight** — the family speaks one event set;
  the tool-specific events are few and by nature. The matrix above is
  the canonical spelling list: a new event name should read it first.

## The exit-and-refusal sweep — the failure ladder

Every `SystemExit` site with its rc and its refusal text, compared for
the family canon: same cause, same code, same text shape.

**The rc summary** + **the distinct refusal texts** (the literal
message args — the family's refusal canon):

- rc 0 (the clean exits): 9; rc 1 (the binds): 20; rc 2 (the CLI mistakes): 6; 0 site(s) raising a variable (the message/`rc` computed —
  the common SystemExit(str) prints the message and exits 1).

The refusal texts (the literal SystemExit args, sorted):

- `"table" is not a metrics/acl value — the table is the show: show metrics acl table`
- `?`
- `auth handshake rejected by the peer (key mismatch?)`
- `bad auth handshake reply`
- `battery-kwh must be a positive kWh value`
- `battery-state must be auto|charging|discharging`
- `connection closed by peer`
- `fails its seal — the wrong dump/key, or edited content (nothing restored)`
- `grid-outage must be on|off|outage`
- `max-kwp must be a positive kW value`
- `metrics-server must be on or off`
- `metrics/listen cannot move beyond loopback while the endpoint serves without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart`
- `mppt must be both|east|west|none`
- `no http server attached`
- `no modbus device attached`
- `non-finite result`
- `not a boolean`
- `refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart, or bind 127.0.0.1:PORT`
- `short response: function byte only`
- `system/listen cannot move beyond loopback while the page serves without a token (F21 in docs/AUDIT.md) — pass auth-token by flag/env/config and restart`
- `the Waveshare password must be ASCII`
- `the metrics endpoint serves register values: refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart, or bind metrics/listen on 127.0.0.1`
- `the metrics endpoint serves the request counters: refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart, or bind metrics/listen on 127.0.0.1`
- `the ops token must differ from the admin token (the same secret would hand every holder the role the server picks first)`
- `time out of range (00:00-23:59)`
- `timezone must be utc|local`
- `transaction id mismatch`

The findings:

- **The rc discipline has one known, deliberate split**: the serving
  tools refuse a bad ops policy with rc 2 (argparse's convention for
  the CLI's own mistakes), the fake with rc 1 (its F11 posture — one
  error line, one exit). Everything else binds-fails rc 1 family-wide
  (the bind-note wave's `cannot bind` + SystemExit(1)).
- **The refusal texts carry the family's voice** — `refusing to`
  (the security floors: the /metrics loopback, the TCP-without-token,
  the token-shape), `cannot bind`, `needs`/`must` (the config
  validation). A new refusal should pick from these verbs; the exit
  sweep's nearest-text column is the review surface.

## The rendered-surface sweep — the man/help/README ladders

The artifacts the tools render, diffed by structure across the four:
the man pages' `.SH` section ladders, `--help`'s option groups, the
READMEs' `##` skeletons.

**The man-page `.SH` ladders** (RENDER FAILED = the render died):

- cache: NAME -> SYNOPSIS -> DESCRIPTION -> OPTIONS -> SIGNALS -> CONTROL -> SECURITY -> ENVIRONMENT -> FILES -> EXIT STATUS -> SEE ALSO
- scraper: NAME -> SYNOPSIS -> DESCRIPTION -> OPTIONS -> SIGNALS -> CONTROL -> SECURITY -> ENVIRONMENT -> FILES -> EXIT STATUS -> SEE ALSO
- inverter: NAME -> SYNOPSIS -> DESCRIPTION -> OPTIONS -> SIGNALS -> CONTROL -> SECURITY -> ENVIRONMENT -> FILES -> EXIT STATUS -> SEE ALSO
- dashboard: NAME -> SYNOPSIS -> DESCRIPTION -> OPTIONS -> SIGNALS -> CONTROL -> SECURITY -> ENVIRONMENT -> FILES -> EXIT STATUS -> SEE ALSO

**The README `##` skeletons:**

- cache: How it works -> Usage -> Configuration -> Runtime control -> Diagnostics registers -> Register map (device profile) -> Access control -> Modbus auth -> Persistence -> Metrics -> Audit logging -> Security -> Testing -> Nix / NixOS -> Source layout -> License
- scraper: How it works -> Usage -> Configuration -> Runtime control -> Metrics -> Alerting -> Device profile -> Battery -> Logging and audit trail -> Test inverter -> Security -> Testing -> Nix / NixOS -> Source layout -> License
- inverter: How it works -> Usage -> Configuration -> Runtime control -> Served registers (the default profile) -> Internal registers (not in the profile) -> Chaos injection (`--chaos`) -> Audit trail -> Security -> Testing -> Nix / NixOS -> Source layout -> License
- dashboard: How it works -> Usage -> Configuration -> Runtime control -> Behind a reverse proxy -> Metrics source -> Security -> Testing -> Nix / NixOS -> Source layout -> License

The skeleton verdict (`scripts/lint_readmes.py --check` gates it):

- cache: OK
- scraper: OK
- inverter: OK
- dashboard: OK

The findings:

- **The man ladders line up** (the same section order, the tool's own
  sections appended at the tail) — the gen_man.py generator owns the
  shape; the drift risk is a hand-edited page, which this sweep
  flags by the .SH ladder changing.
- **The README skeleton** is the one-skeleton wave's shape (how it
  works -> usage -> configuration -> runtime control -> the features
  -> security -> testing -> nix -> source layout -> license) and
  `scripts/lint_readmes.py --check` pins it: the canon H2s in order,
  the tool's own sections only in the slot between runtime control
  and security, and a `### Signals` block leading the Runtime-control
  H3s — this sweep prints the gate's verdict beside the ladders.

## The NixOS-parity sweep — the modules vs the registries

Each `module.nix` option's type and default against the same knob's
registry row — the units drift (MB vs bytes, seconds vs ms) and the
missing options are what this finds. Heuristic parse: the type/default
LINES are quoted, the verdicts curated.

| tool | mkOption blocks |
|---|---|
| cache | 12 |
| scraper | 46 |
| inverter | no module.nix |
| dashboard | 45 |

**The module options NOT matching a registry knob name** (after
the kebab/camel normalization; the `*File` suffix is the NixOS
LoadCredential pattern, not a knob):

- cache: `unitId`
- scraper: `listenHost`, `listenPort`
- dashboard: `listenHost`, `listenPort`, `prometheusUrl`

The findings:

- **check_options gates the presence** ("the NixOS module defines
  every option"); the TYPE and DEFAULT parity is not gated — the
  units drift (the audit's MB, the intervals' seconds) is where a
  Nix default and a registry default can silently disagree. The
  module option maps were rebuilt from the module.nix files in the
  docs restructure wave — this sweep is the machine check that keeps
  them honest.
- The parse is heuristic (the first type=/default= line in the
  option block) — the verdicts in the findings are editorial; the
  table is the starting point for the module review.

## The docker/env sweep — the env twins and the ports

`docker/**` text-scanned for the env-var names and the published
ports, matched against the registries' env twins and the default
binds. A knob without its env twin cannot be set from an env file; a
published port not backed by a registry default is a lie.

| file | env vars | published ports |
|---|---|---|
| `docker/Dockerfile.dashboard` | `AUTH_TOKEN`, `CONFIG_JS`, `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `PROM_URL`, `README`, `REQUIRED`, `SO_PEERCRED`, `VOLUME`, `WORKDIR` | 8080 |
| `docker/Dockerfile.fake-inverter` | `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `SO_PEERCRED`, `VOLUME`, `WORKDIR` | 5502 |
| `docker/Dockerfile.modbus-cache` | `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `README`, `REQUIRED`, `SELECTION`, `SO_PEERCRED`, `UPSTREAM`, `VOLUME`, `WORKDIR` | 15502 |
| `docker/Dockerfile.modbus-scraper` | `AUTH`, `AUTH_KEY`, `AUTH_TOKEN`, `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `METRICS_SPEC`, `README`, `REQUIRED`, `SO_PEERCRED`, `UPSTREAM`, `VOLUME` … | 9350 |
| `docker/Dockerfile.prometheus` | `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `VOLUME` | — |
| `docker/README.md` | `AUTH`, `AUTH_KEY`, `AUTH_TOKEN`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `CHAOS`, `CONFIG`, `CONFIG_JS`, `COPY`, `EDITOR`, `ENTRYPOINT`, `HEALTHCHECK`, `HMAC`, `HOST` … | 15502, 5502, 8080, 9350 |
| `docker/demo/README.md` | `DEMO`, `HOST`, `JSON`, `PROM_URL`, `README`, `TSDB`, `UPSTREAM` | 8080, 9090 |
| `docker/demo/compose.yaml` | `AUTH`, `AUTH_KEY`, `AUTH_TOKEN`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `DEMO`, `HMAC`, `JSON`, `LISTEN`, `PROM_URL`, `PVA1`, `README`, `REQUIRED`, `SAME` | 8080 |
| `docker/entrypoints/entrypoint-prometheus.sh` | `AUDIT`, `POST`, `PROM_ADMIN_API`, `PROM_ARGS`, `PROM_LIFECYCLE`, `PROM_RETENTION`, `TOKEN_DST`, `TOKEN_SRC`, `TSDB` | — |
| `docker/entrypoints/entrypoint.sh` | `AUDIT`, `JSON`, `README`, `REQUIRED` | — |
| `docker/env/cache.env.example` | `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `AUTH`, `AUTH_KEY`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `DEBUG`, `ERROR`, `HOST`, `INFO` … | — |
| `docker/env/dashboard.env.example` | `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `AUTH_TOKEN`, `INFO`, `LISTEN`, `LOG_LEVEL`, `NO_AUDIT_LOG`, `PLAIN`, `PROM_URL` | — |
| `docker/env/fake.env.example` | `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `CHAOS`, `CLIENT_TIMEOUT`, `LISTEN`, `MAX_CLIENTS`, `MAX_CONN_PER_IP`, `MAX_KWP`, `NO_AUDIT_LOG`, `PROFILE` … | — |
| `docker/env/prometheus.env.example` | `POST`, `PROM_`, `PROM_ADMIN_API`, `PROM_LIFECYCLE`, `PROM_RETENTION`, `TSDB` | — |
| `docker/env/scraper.env.example` | `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `AUTH_TOKEN`, `DEBUG`, `ERROR`, `HOST`, `INFO`, `INTERVAL`, `LOG_LEVEL`, `METRIC_PREFIX` … | — |
| `docker/prod/README.md` | `AUDIT`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `EDITOR`, `HOST`, `JSON`, `PORT`, `PROM_URL`, `README`, `UPSTREAM`, `YOUR` | 8080, 9350 |
| `docker/prod/compose.yaml` | `AUTH`, `AUTH_KEY`, `AUTH_TOKEN`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `CONTAINER`, `EDIT`, `EXTERNAL`, `HMAC`, `HOST`, `LISTEN`, `ONLY`, `PORT`, `PRODUCTION` … | 8080, 9350 |
| `docker/prometheus.yml` | `AUDIT` | — |

**The port map 1:1** — the registries back every port the docker
surface names (a port here that no knob backs is the lie this
sweep exists for):

| port | the knobs backing it | where the docker surface names it |
|---|---|---|
| 5502 | inverter:listen | docker/Dockerfile.fake-inverter EXPOSE |
| 8080 | dashboard:listen | docker/Dockerfile.dashboard EXPOSE; docker/demo/compose.yaml ports:; docker/prod/compose.yaml ports: |
| 9350 | scraper:listen | docker/Dockerfile.modbus-scraper EXPOSE; docker/prod/compose.yaml ports: |
| 9351 | cache:metrics-listen | — |
| 9352 | inverter:metrics-listen | — |
| 9353 | dashboard:metrics-listen | — |
| 15502 | cache:listen | docker/Dockerfile.modbus-cache EXPOSE |

The findings:

- **The env-file twins are the docker surface's contract**: a
  registry env twin missing from every compose/env file means the
  knob is unreachable from the deployment — sometimes design (the
  demo needs fewer knobs), sometimes a gap. The split wave's wiring
  list (the prod = three services + the external collector, the
  demo's in-stack shapes) is the expected drift.
- **The published ports map 1:1 to the registry defaults** (the
  935x block) — the port map above is the standing gate: every
  EXPOSE, every CMD `--listen` and every compose `ports:` container
  side names a port a listen knob backs. A port no knob backs is the
  lie this sweep exists for; the regeneration prints it and the
  `--check` fails on it.

## The suite-coverage sweep — the promises x the tests

Every live knob name, command word and canon log phrase grepped
against `tests/*.py` (word-bounded). Word-match honesty: the suites
are prose too — a name inside another word counts as covered; the
list is the TODO seed, not a verdict.

**The live knobs no suite mentions** (word-bounded grep):

- cache: every live knob named somewhere in the suites
- scraper: every live knob named somewhere in the suites
- inverter: every live knob named somewhere in the suites
- dashboard: every live knob named somewhere in the suites

**The command words no suite mentions:**

- cache: every command exercised
- scraper: every command exercised
- inverter: every command exercised
- dashboard: every command exercised

**The canon phrases no suite pins**: 17

**The graduation path**: the seeds carry stable IDs in
[docs/family-drift-seeds.json](family-drift-seeds.json) (17
open promise(s), the suggested suite per seed); a test wave
consumes entries, the regeneration drops them, the shrinkage is
the wave's proof; `--check` fails when a NEW promise ships
uncovered (the list may only shrink).

The findings:

- **The uncovered list is the TODO seed**, not a verdict: a knob can
  be covered by an alias spelling, a config-file set, or a
  family-wide suite the word-grep misses. The next test wave starts
  from this list.
- **The canon-phrase pins** are the regtests' strongest tool — a
  phrase in the canon no suite pins is a text free to drift.
- **The graduation path is the ledger** (docs/family-drift-seeds.json,
  `family_drift.py --seeds`): stable IDs, the suggested suite per
  seed, the counts as the shrink metric; the `--check` growth gate
  keeps the list honest — new promises ship covered or the gate
  fails.

## The F-ledger sweep — docs/AUDIT.md vs the tree

Each F-number's title from the audit doc, and which of the family's
files cite it — the promise ledger against the code.

| F | title | cited by |
|---|---|---|
| F1 | Modbus TCP carries no authentication and no encryption | — |
| F14 | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics trave | dashboard |
| F15 | The metrics expose production values (generation, consumption, battery SoC) | — |
| F17 | The `/config` volume holds live config in plaintext; the entrypoint seeds copies | — |

The findings:

- **The cited-by column is the enforcement map**: an F whose only
  citations are the audit doc itself has no enforcement markers in
  the tree (either the F is enforced in code without a marker — add
  the marker — or it is not enforced — the ledger lies). The F-suffix
  convention (the code comments cite `F13 in docs/AUDIT.md`) is the
  family's traceability habit; the sweep keeps it honest.

## The statics sweep — the four defaults.json blocks

Every leaf key-path of the four `lib/defaults.json` files: the shared
paths whose values disagree, the only-there paths (the audit
defaults, the caps, the grid constants the loaders wire via
`static_defaults`).

91 leaf paths; 16 in all four; 1 shared with differing values.

| key-path | per-tool values |
|---|---|
| `defaults.listen` | c: "127.0.0.1:15502" | s: "127.0.0.1:9350" | i: "127.0.0.1:5502" | d: "127.0.0.1:8080" |

The findings:

- **The defaults.json blocks are the tools' personalities** (the
  simulators' grid constants, the caps' defaults) — the drift that
  matters is the FAMILY defaults (the audit rotation, the log
  levels, the cap defaults) disagreeing: those wire through
  `static_defaults`/`choices` into the registries and the set
  grammar. The shared-path matrix is the ruling surface.

## The schema/example sweep — the derived sources

The JSON Schemas' properties against the registry rows, and every
shipped example re-parsed through the tool's own set-grammar reader
(not just name-checked).

| tool | schema files |
|---|---|
| cache | `selection.schema.json` |
| scraper | `metrics.schema.json` |
| inverter | none |
| dashboard | none |
| shared | `acl-ip-prefix.schema.json`, `acl-write-registers.schema.json` |

**The shipped examples re-parsed** through the tools' own readers:

| example | the read |
|---|---|
| `cache/examples/modbus_cache.conf` | ok (31 setting line(s)) |
| `cache/examples/selection.json` | json ok |
| `scraper/examples/metrics.json` | json ok |
| `scraper/examples/scraper.conf` | ok (18 setting line(s)) |
| `inverter/examples/inverter.conf` | ok (3 setting line(s)) |
| `dashboard/examples/server.conf` | ok (19 setting line(s)) |
| `examples/acl-ip-prefix.json` | json ok |
| `examples/acl-write-registers.json` | json ok |

The findings:

- **The shared pair is the pattern**: the standalone acl file's two
  gates (ip-prefix + write-registers) ship their example + schema ONCE
  at the root examples/ + shared/schema/ — the four per-tool ip-prefix
  copies died in the shared-examples wave, the cache-local write pair
  joined (one gate validator in common/settings/config.py reads both
  kinds). The per-tool schema/ dirs that remain carry the
  tool-specific shapes.
- **The examples re-parse is the honest check**: a shipped example
  that the tool's own reader refuses is a broken promise shipped to
  every user who copies it. The table above is that check.

## The secret-surface sweep — the secret rows and their posture

Every `secret`-marked registry row with its live/restart/hidden
posture, the table consolidated by knob — rows sharing a posture
merge, the tools column carries the coverage (a knob missing from a
tool is the visible gap). The secret-posture markers (`parse_secret`,
the `SECRET_REMOVED` placeholder, the `file:` scheme) across the
tree.

21 secret-marked row(s) across 7 knob(s), consolidated by posture:

| knob | tools | live | restart | hidden |
|---|---|---|---|---|
| `auth-key` | cache, inverter, scraper | yes | yes | yes |
| `auth-token` | dashboard, scraper | yes | yes | yes |
| `auth-upstream-key` | cache | yes | yes | yes |
| `control-ops-token` | all four | yes | yes | yes |
| `control-token` | all four | yes | yes | yes |
| `dump-key` | all four | yes | yes | yes |
| `metrics-token` | cache, dashboard, inverter | yes | yes | yes |

**The markers per tool** (the F-trust surface: the loader parses,
the dumps placeholder, the examples and configs reference):

| tool | parse_secret | SECRET_REMOVED | file: |
|---|---|---|---|
| cache | yes | yes | yes |
| scraper | yes | yes | yes |
| inverter | yes | yes | yes |
| dashboard | yes | yes | yes |

The findings:

- **The secret rows' posture should be uniform**: secret + restart
  (a secret never rides the reload state — the placeholder rule) +
  hidden (no live listing). A row that breaks the shape is the
  drift.
- **The markers' census** (`parse_secret`, `SECRET_REMOVED`,
  `file:`) is the F-trust surface: the loader parses, the dumps
  placeholder, the examples reference. A tool missing a marker is
  the story to chase.

## The remediation TODOs — the consistency rulings

The working assumption: **the family is one product** — a user moving
between the four tools finds the same knobs, the same words, the same
refusals and the same env layer; the code behind them lives once in
`common/`. Each TODO states the consistent outcome and the plane it
serves. Ordered by the user's exposure; the code plane rides along.
The landed legs (the audit rotation bounds, the `audit-daily` shape,
the env-or-note completion, the accept-ladder extraction):
[history/family-drift.md](history/family-drift.md).

1. **The `auth` name collision resolved** — one spelling, one
   meaning: the dashboard's `auth` node (the page's namespace)
   renames (`page-auth/` or the rows re-home), or the modbus enum
   re-homes; the set grammar never maps one word to two meanings.
   Breaking change for the dashboard's live names — the TODO is the
   proposal + the migration note (the alias map carries the old
   spellings one release).

3. **The coverage TODOs graduate** — the seeds carry stable IDs in
    docs/family-drift-seeds.json (`family_drift.py --seeds`, the
    suggested suite per seed); a test wave consumes entries, the
    regeneration drops them, the shrinkage is the wave's proof, and
    `--check` fails when a NEW promise ships uncovered (the list may
    only shrink).

4. **The parity gates wired** — the docker-ports gate LANDED (the
    sweep above: every EXPOSE/CMD/compose port rides a registry
    listen default); the remaining half is the NixOS-parity +
    env-file coverage as machine checks (the module.nix type/default
    vs the registry, the env-file coverage vs the env twins). The
    drift doc's `--check` already shows the pattern: a stale claim
    fails the gate.

Not-todo (the ruling recorded): the fake's `request/restart` verb
stays absent (its reload execs and re-reads the conf — the
config-file wave — so the verb would double the reload); the
man-page prose and the HTTP
handlers stay per-tool by design; the malformed-frame split is the
proxy/device difference, kept as the ladder's policy hook.

