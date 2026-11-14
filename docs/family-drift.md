# The family drift — the shared-code sweeps (regenerated)

The wave record: the sweep types over the four surfaces (cache,
scraper, inverter, dashboard) — what each sweeps, what it found,
and the verdicts. **Ships in the repo, kept current by the
workflow**: the open findings wait in place, and `--check` fails
a stale page. Regenerate with `python3 dev/family_drift.py`;
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
10. **The F-ledger sweep** — docs/SECURITY.md's F-numbers vs the
    tree's enforcement markers.
11. **The statics sweep** — the four defaults.json blocks by
    key-path.
12. **The schema/example sweep** — the JSON Schemas vs the
    registries; the shipped examples re-parsed.
13. **The secret-surface sweep** — the secret rows and the
    posture markers.
14. **The console-print sweep** — the cli session path prints
    through the one pager door; a naked print( fails --check.

## The code sweep — the text-structural pass

Every per-tool `lib/*.py` and `bin/*.py` function, AST-normalized (the
line numbers and the local names collapse, the constant values stay),
compared two ways: the exact pass groups identical bodies (the
copy-paste twins), the similarity pass pairs cross-file bodies over the
0.72 ratio (the near-copies that already drifted).

**The exact pass**: 2 duplicate group(s) in >= 2 files.

- 28L `main`: `apps/scraper/bin/modbus-scraper-cli.py:58`, `apps/inverter/bin/modbus-fake-cli.py:58`, `apps/dashboard/bin/dashboard-cli.py:58`, `apps/cache/bin/modbus-cache-cli.py:58`
- 8L `_implied`: `apps/scraper/bin/modbus-scraper-cli.py:48`, `apps/inverter/bin/modbus-fake-cli.py:48`, `apps/dashboard/bin/dashboard-cli.py:48`, `apps/cache/bin/modbus-cache-cli.py:48`

**The similarity pass**: 37 cross-file pair(s) over the ratio
floor (12 of them the man-page prose, per-tool by
design); the top non-man pairs:

| ratio | pair |
|---|---|
| 1.00 | `apps/cache/bin/modbus-cache-cli.py:58` `main` <-> `apps/scraper/bin/modbus-scraper-cli.py:58` `main` |
| 1.00 | `apps/cache/bin/modbus-cache-cli.py:58` `main` <-> `apps/inverter/bin/modbus-fake-cli.py:58` `main` |
| 1.00 | `apps/cache/bin/modbus-cache-cli.py:58` `main` <-> `apps/dashboard/bin/dashboard-cli.py:58` `main` |
| 1.00 | `apps/inverter/bin/modbus-fake-cli.py:58` `main` <-> `apps/dashboard/bin/dashboard-cli.py:58` `main` |
| 1.00 | `apps/scraper/bin/modbus-scraper-cli.py:58` `main` <-> `apps/inverter/bin/modbus-fake-cli.py:58` `main` |
| 1.00 | `apps/scraper/bin/modbus-scraper-cli.py:58` `main` <-> `apps/dashboard/bin/dashboard-cli.py:58` `main` |
| 0.96 | `apps/cache/lib/options.py:23` `_load_options` <-> `apps/scraper/lib/options.py:25` `_load_options` |
| 0.93 | `apps/scraper/bin/modbus-scraper.py:46` `parse_args` <-> `apps/dashboard/bin/dashboard.py:277` `parse_args` |
| 0.93 | `apps/cache/lib/options.py:23` `_load_options` <-> `apps/dashboard/lib/options.py:24` `_load_options` |
| 0.93 | `apps/scraper/lib/options.py:25` `_load_options` <-> `apps/dashboard/lib/options.py:24` `_load_options` |
| 0.90 | `apps/scraper/bin/modbus-scraper.py:241` `graceful_stop` <-> `apps/dashboard/bin/dashboard.py:474` `graceful_stop` |
| 0.86 | `apps/cache/bin/modbus-cache.py:49` `parse_args` <-> `apps/scraper/bin/modbus-scraper.py:46` `parse_args` |
| 0.85 | `apps/cache/lib/options.py:23` `_load_options` <-> `apps/inverter/lib/options.py:27` `_load_options` |
| 0.85 | `apps/scraper/lib/options.py:25` `_load_options` <-> `apps/inverter/lib/options.py:27` `_load_options` |
| 0.85 | `apps/inverter/lib/options.py:27` `_load_options` <-> `apps/dashboard/lib/options.py:24` `_load_options` |
| 0.85 | `apps/cache/bin/modbus-cache.py:49` `parse_args` <-> `apps/dashboard/bin/dashboard.py:277` `parse_args` |
| 0.83 | `apps/inverter/lib/control.py:96` `__init__` <-> `apps/dashboard/lib/control.py:73` `__init__` |
| 0.82 | `apps/cache/bin/modbus-cache.py:355` `watch_dump` <-> `common/wire/control.py:1380` `run_dump_interval` |
| 0.78 | `apps/cache/lib/control.py:826` `uplink_report` <-> `apps/scraper/lib/control.py:481` `uplink_report` |
| 0.78 | `apps/inverter/lib/control.py:466` `acl_table_report` <-> `apps/dashboard/lib/control.py:296` `acl_table_report` |

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
  audit-requests timer; the scraper's clamped wait and the live
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

**The shape**: 239 knob rows across the
four registries; 34 names carry in all four:

`audit`, `audit-daily`, `audit-files`, `audit-forward`, `audit-forward-format`, `audit-instance`, `audit-log`, `audit-max-mb`, `audit/rotate`, `control`, `control-log-replies`, `control-ops-token`, `control-ops-verbs`, `control-port`, `control-socket-group`, `control-token`, `control-trust-uids`, `control/ops`, `dump`, `dump-interval`, `dump-key`, `dump-path`, `listen`, `local-time`, `log-access`, `log-level`, `metrics`, `metrics-acl`, `metrics-client-timeout`, `metrics-max-clients`, `metrics-max-conn-per-ip`, `no-audit-log`, `restore-on-start`, `system`

**The tool-specific remainder** (by nature):

| tool | only-there knobs |
|---|---|
| cache | `acl`, `allow-write`, `audit-requests`, `cache-ttl`, `client-timeout`, `connect-acl`, `dump-with-cache`, `limits`, `max-clients`, `max-conn-per-ip`, `metrics-listen`, `metrics-server`, `metrics-token`, `metrics/limits`, `modbus`, `modbus-auth`, `modbus-auth-key`, `modbus-auth-upstream`, `modbus-auth-upstream-key`, `modbus-interval`, `modbus-merge-gap`, `modbus-profile`, `modbus-read-delay`, `modbus-timeout`, `modbus-unit`, `selection`, `trace`, `trace-socket`, `trace-sources`, `upstream`, `write`, `write-acl`, `write-registers` |
| scraper | `auth-token`, `grid-positive-import`, `max-grid-kw`, `max-kwp`, `metrics-prefix`, `metrics-spec`, `metrics/auth`, `metrics/limits`, `modbus`, `modbus-auth`, `modbus-auth-key`, `modbus-interval`, `modbus-merge-gap`, `modbus-offset`, `modbus-profile`, `modbus-read-delay`, `modbus-timeout`, `modbus-unit`, `modbus/caps`, `upstream` |
| inverter | `allow-write`, `batt`, `battery-kwh`, `battery-state`, `chaos`, `client-timeout`, `cloud`, `connect-acl`, `grid`, `grid-frequency`, `grid-frequency-wander`, `grid-outage`, `grid-voltage`, `grid-voltage-wander`, `load`, `max-clients`, `max-conn-per-ip`, `max-kwp`, `metrics-listen`, `metrics-server`, `metrics-token`, `modbus`, `modbus-auth`, `modbus-auth-key`, `modbus-profile`, `mppt`, `pv`, `scenario`, `seed`, `soc`, `static`, `strict`, `time`, `time-scale`, `timezone`, `unit`, `write` |
| dashboard | `auth`, `auth-token`, `client-timeout`, `config-js`, `log-queries`, `max-clients`, `max-conn-per-ip`, `metrics-listen`, `metrics-server`, `metrics-token`, `prom-prefix`, `static-dir`, `upstream` |

**The shared knobs whose fields disagree** (8 of
34 knobs, 13 drifted field(s)) — one row per
knob+field, the tools grouped by the value each carries:

| knob | field | the values (the tools carrying each) |
|---|---|---|
| `control-log-replies` | `env` | *absent* (cache, scraper, inverter) · `CONTROL_LOG_REPLIES` (dashboard) |
| `control-ops-verbs` | `default` | `show,flush` (cache) · `show` (scraper, inverter, dashboard) |
| `listen` | `default` | `127.0.0.1:15502` (cache) · `127.0.0.1:9350` (scraper) · `127.0.0.1:5502` (inverter) · `127.0.0.1:8080` (dashboard) |
| `local-time` | `env` | `LOCAL_TIME` (cache, scraper, dashboard) · *absent* (inverter) |
| `log-access` | `env` | `LOG_ACCESS` (cache, scraper, dashboard) · *absent* (inverter) |
| `log-access` | `hidden` | `True` (cache) · `·` (scraper, inverter, dashboard) |
| `metrics-client-timeout` | `env` | `METRICS_CLIENT_TIMEOUT` (cache, scraper, dashboard) · *absent* (inverter) |
| `metrics-client-timeout` | `live` | `metrics/limits/timeout` (cache, scraper) · `·` (inverter, dashboard) |
| `metrics-client-timeout` | `default` | `5.0` (cache, inverter, dashboard) · `300.0` (scraper) |
| `metrics-max-clients` | `env` | `METRICS_MAX_CLIENTS` (cache, scraper, dashboard) · *absent* (inverter) |
| `metrics-max-clients` | `live` | `metrics/limits/max-clients` (cache, scraper) · `·` (inverter, dashboard) |
| `metrics-max-conn-per-ip` | `env` | `METRICS_MAX_CONN_PER_IP` (cache, scraper, dashboard) · *absent* (inverter) |
| `metrics-max-conn-per-ip` | `live` | `metrics/limits/max-conn-per-ip` (cache, scraper) · `·` (inverter, dashboard) |

**The command vocabularies** (the wire words per tool):

- cache: `help`, `inspect`, `ping`, `quit`, `request`, `request/flush`, `request/flush/cache`, `request/poll`, `request/poll/now`, `request/dump`, `request/dump`, `request/dump/with-cache`, `request/reload`, `request/reload-config`, `request/restart`, `request/restore`, `set`, `show`, `shutdown`, `clear`
- scraper: `help`, `inspect`, `ping`, `quit`, `request`, `request/dump`, `request/poll`, `request/poll/now`, `request/reload`, `request/reload-config`, `request/restart`, `request/restore`, `set`, `show`, `shutdown`, `clear`
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
- `request/poll/now` — the scraper's poll trigger.

The findings:

- **The `auth` name collision.** The dashboard's `auth` is a NODE
  (the page's auth namespace), the other three's is the modbus auth
  enum (`suite|none`). One spelling, two meanings in the family's
  set-grammar space — legal (the registries are per-tool), but the
  merged-knob view (dev/list_options.py) and any future family-wide
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

**The canon coverage** (shared/suite/options.json — the registry
texts the rows ref; the drift and must-ref gates live in
`lint/options --check`, the exempt names ride it):

| section | blocks | cache refs | scraper refs | inverter refs | dashboard refs |
|---|---|---|---|---|---|
| options | 48 | 48 | 41 | 42 | 39 |
| show | 7 | 7 | 6 | 5 | 4 |
| commands | 16 | 16 | 16 | 13 | 13 |

The exempt (intentionally per-tool) names: **40** —
each with its reason in `dev/gates/options.py`.

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
| inverter | `ACL-FILE`, `RELOAD`, `RESET`, `SHUTDOWN`, `START`, `WRITE`, `WRITE-REFUSED` |
| dashboard | `ACL-FILE`, `RELOAD`, `SHUTDOWN`, `START` |
| common | `AUTH-FAIL`, `COMMAND`, `CONNECT`, `DISCONNECT`, `RECONNECT`, `RELOAD` |

**The phrase canon**: 25 log phrase(s) shared by >= 2 tools;
90 tool-local. The canon (the lead clause, the tools that speak it):

| the lead clause | tools |
|---|---|
| `acl file:` | cache, dashboard, inverter, scraper |
| `stopped` | cache, dashboard, inverter, scraper |
| `write:` | cache, inverter |
| `write: refused` | cache, inverter |
| `cannot bind` | cache, dashboard, inverter, scraper |
| `client` | dashboard, scraper |
| `shutdown:` | cache, dashboard, inverter, scraper |
| `the state dump` | cache, common, inverter |
| `state dumped to` | cache, common |
| `connection rejected:` | common, scraper |
| `unhandled error serving` | dashboard, scraper |
| `dry-run: configuration is valid nothing was boun` | dashboard, inverter, scraper |
| `restore-on-start:` | dashboard, inverter, scraper |
| `control: state dumped to` | cache, common |
| `control: state restored from` | cache, common |
| `control: request poll now the loop wakes immedia` | cache, scraper |
| `control: the dump to` | cache, common |
| `poll plan:` | cache, scraper |
| `sighup: reloaded` | cache, inverter |
| `poll cycle crashed ` | cache, scraper |
| `state dumps:` | cache, common |
| `the shutdown dump to` | cache, common |
| `the periodic dump to` | cache, common |
| `rejected` | common, inverter |
| `sighup: reload failed ` | common, inverter |

The findings:

- **The audit vocabulary is tight** — the family speaks one event set;
  the tool-specific events are few and by nature. The matrix above is
  the canonical spelling list: a new event name should read it first.

## The exit-and-refusal sweep — the failure ladder

Every `SystemExit` site with its rc and its refusal text, compared for
the family canon: same cause, same code, same text shape.

**The rc summary** + **the distinct refusal texts** (the literal
message args — the family's refusal canon):

- rc 0 (the clean exits): 8; rc 1 (the binds): 11; rc 2 (the CLI mistakes): 12; 0 site(s) raising a variable (the message/`rc` computed —
  the common SystemExit(str) prints the message and exits 1).

The refusal texts (the literal SystemExit args, sorted):

- `"table" is not a metrics-acl value — the table is the show: show metrics-acl-table`
- `?`
- `auth handshake rejected by the peer (key mismatch?)`
- `bad auth handshake reply`
- `battery-kwh must be a positive kWh value`
- `battery-state must be auto|charging|discharging`
- `connection closed by peer`
- `fails its seal — the wrong dump-key, or edited content (nothing restored)`
- `grid-outage must be on|off|outage`
- `listen cannot move beyond loopback while the page serves without a token (F21 in docs/SECURITY.md) — pass auth-token by flag/env/config and restart`
- `max-kwp must be a positive kW value`
- `metrics-listen cannot move beyond loopback while the endpoint serves without a token (F13 in docs/SECURITY.md) — pass metrics-token by flag/env/config and restart`
- `metrics-server must be on or off`
- `mppt must be both|east|west|none`
- `must be an http:// or https:// URL with a host`
- `no http server attached`
- `no modbus device attached`
- `non-finite result`
- `not a boolean`
- `refusing to expose /metrics beyond loopback without a token (F13 in docs/SECURITY.md) — pass metrics-token by flag/env/config and restart, or bind 127.0.0.1:PORT`
- `short response: function byte only`
- `the Waveshare password must be ASCII`
- `the metrics endpoint serves register values: refusing to expose /metrics beyond loopback without a token (F13 in docs/SECURITY.md) — pass metrics-token by flag/env/config and restart, or bind metrics-listen on 127.0.0.1`
- `the metrics endpoint serves the request counters: refusing to expose /metrics beyond loopback without a token (F13 in docs/SECURITY.md) — pass metrics-token by flag/env/config and restart, or bind metrics-listen on 127.0.0.1`
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

- cache: Usage -> Security -> License
- scraper: Usage -> Security -> License
- inverter: Usage -> Security -> License
- dashboard: Usage -> Security -> License

The skeleton verdict (`dev/gates/readmes.py --check` gates it):

- cache: OK
- scraper: OK
- inverter: OK
- dashboard: OK

The findings:

- **The man ladders line up** (the same section order, the tool's own
  sections appended at the tail) — the man.py generator owns the
  shape; the drift risk is a hand-edited page, which this sweep
  flags by the .SH ladder changing.
- **The README skeleton** is the front-page split's shape (the
  description under the H1, then usage -> security -> license, and
  nothing else) and `dev/gates/readmes.py --check` pins it: the canon
  H2s in order, no other H2s — the tool's own reference material lives
  in the daemon's --help and the generated man page, which this sweep
  prints the gate's verdict beside.

## The NixOS-parity sweep — the modules vs the registries

The settings wave inverted the modules: no knob options at all — one
freeform `settings` attrset rendered verbatim into the unit's
EnvironmentFile (the keys are the bare env twins, unvalidated), the
secrets ride the `<secret>File` LoadCredential options only, and the
survivors are the structural options. There is no per-knob Nix-side
type/default left to drift; the check is structural.

| tool | module options declared |
|---|---|
| cache | `controlOpsTokenFile`, `controlTokenFile`, `dumpKeyFile`, `enable`, `group`, `metricsTokenFile`, `modbusAuthKeyFile`, `modbusAuthUpstreamKeyFile`, `openFirewall`, `package`, `settings`, `user` |
| scraper | `authTokenFile`, `controlOpsTokenFile`, `controlTokenFile`, `dumpKeyFile`, `enable`, `group`, `modbusAuthKeyFile`, `openFirewall`, `package`, `settings`, `user` |
| inverter | no module.nix |
| dashboard | `authTokenFile`, `controlOpsTokenFile`, `controlTokenFile`, `dumpKeyFile`, `enable`, `group`, `metricsTokenFile`, `openFirewall`, `package`, `settings`, `solarConfig`, `staticDir`, `user` |

**The structural contract** — exactly `enable`/`package`/
`openFirewall`/`settings` + the account pair `user`/`group`, every
registry secret row's `*File`, and the dashboard's
`solarConfig`/`staticDir` (the removed knob options and inline
secrets are tombstones the module system refuses):

- cache: exactly the structural contract
- scraper: exactly the structural contract
- dashboard: exactly the structural contract

The findings:

- **check_options gates the structure** ("the NixOS module declares
  exactly the structural options"): enable/package/openFirewall/settings,
  the dashboard's solarConfig/staticDir, and every registry secret row's
  *File option present — nothing else may be declared. The inline secret
  options are removed-option tombstones the module system refuses at
  eval; the env-file keys are freeform and carry no parity claim.
- The registry keeps its docs-side role: examples.py renders the
  docker/env examples and the tools' example confs the settings key
  list is lifted from, and the
  nixos/README.md tables document the contract per tool.

## The docker/env sweep — the env twins and the ports

`docker/**` text-scanned for the env-var names and the published
ports, matched against the registries' env twins and the default
binds. A knob without its env twin cannot be set from an env file; a
published port not backed by a registry default is a lie.

| file | env vars | published ports |
|---|---|---|
| `docker/Dockerfile.dashboard` | `AUTH_TOKEN`, `CONFIG_JS`, `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `PROM_URL`, `README`, `REQUIRED`, `SO_PEERCRED`, `VOLUME`, `WORKDIR` | 8080 |
| `docker/Dockerfile.modbus-cache` | `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `README`, `REQUIRED`, `SELECTION`, `SO_PEERCRED`, `UPSTREAM`, `VOLUME`, `WORKDIR` | 15502 |
| `docker/Dockerfile.modbus-fake-inverter` | `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `SO_PEERCRED`, `VOLUME`, `WORKDIR` | 5502 |
| `docker/Dockerfile.modbus-scraper` | `AUTH`, `AUTH_TOKEN`, `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `METRICS_SPEC`, `MODBUS_AUTH_KEY`, `README`, `REQUIRED`, `SO_PEERCRED`, `UPSTREAM`, `VOLUME` … | 9350 |
| `docker/Dockerfile.prometheus` | `COPY`, `ENTRYPOINT`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `VOLUME` | — |
| `docker/README.md` | `AUTH_TOKEN`, `CHAOS`, `CONFIG`, `CONFIG_JS`, `COPY`, `EDITOR`, `ENTRYPOINT`, `GENERATED`, `HEALTHCHECK`, `HMAC`, `HOST`, `JSON`, `LICENSE`, `LOG_LEVEL` … | 15502, 5502, 8080, 9350 |
| `docker/demo/README.md` | `DEMO`, `HOST`, `JSON`, `PROM_URL`, `README`, `TSDB`, `UPSTREAM` | 8080, 9090 |
| `docker/demo/compose.yaml` | `AUTH_TOKEN`, `BEFORE`, `DEMO`, `HMAC`, `JSON`, `LISTEN`, `MODBUS_AUTH`, `MODBUS_AUTH_KEY`, `MODBUS_UPSTREAM_AUTH`, `MODBUS_UPSTREAM_AUTH_KEY`, `OUTSIDE`, `PROM_URL`, `PVA1`, `README` … | 8080 |
| `docker/entrypoints/entrypoint-prometheus.sh` | `POST`, `PROM_ADMIN_API`, `PROM_ARGS`, `PROM_LIFECYCLE`, `PROM_RETENTION`, `README`, `SECURITY`, `TOKEN_DST`, `TOKEN_SRC`, `TSDB` | — |
| `docker/entrypoints/entrypoint.sh` | `JSON`, `README`, `REQUIRED` | — |
| `docker/env/dashboard.env.example` | `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_INSTANCE`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `AUTH_TOKEN`, `CLIENT_TIMEOUT`, `CONFIG_JS`, `CONTROL_LOG_REPLIES`, `CONTROL_OPS_TOKEN`, `CONTROL_OPS_VERBS`, `CONTROL_SOCKET_GROUP` … | — |
| `docker/env/modbus-cache.env.example` | `ALLOW_WRITE`, `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_INSTANCE`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `AUDIT_REQUESTS`, `CLIENT_TIMEOUT`, `CONNECT_ACL`, `CONTROL_OPS_TOKEN`, `CONTROL_OPS_VERBS`, `CONTROL_SOCKET_GROUP` … | — |
| `docker/env/modbus-fake-inverter.env.example` | `ALLOW_WRITE`, `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_INSTANCE`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `CHAOS`, `CIDR`, `CLIENT_TIMEOUT`, `CONNECT_ACL`, `CONTROL_OPS_TOKEN`, `CONTROL_OPS_VERBS` … | — |
| `docker/env/modbus-scraper.env.example` | `AUDIT_DAILY`, `AUDIT_FILES`, `AUDIT_FORWARD`, `AUDIT_FORWARD_FORMAT`, `AUDIT_INSTANCE`, `AUDIT_LOG`, `AUDIT_MAX_MB`, `AUTH_TOKEN`, `CONTROL_OPS_TOKEN`, `CONTROL_OPS_VERBS`, `CONTROL_SOCKET_GROUP`, `CONTROL_TOKEN`, `CONTROL_TRUST_UIDS`, `DUMP_INTERVAL` … | — |
| `docker/env/prometheus.env.example` | `POST`, `PROM_`, `PROM_ADMIN_API`, `PROM_LIFECYCLE`, `PROM_RETENTION`, `TSDB` | — |
| `docker/gen-secrets.sh` | `README`, `SECURITY` | — |
| `docker/prod/README.md` | `EDITOR`, `HOST`, `JSON`, `MODBUS_UPSTREAM_AUTH`, `MODBUS_UPSTREAM_AUTH_KEY`, `PORT`, `PROM_URL`, `README`, `SECURITY`, `UPSTREAM`, `YOUR` | 8080, 9350 |
| `docker/prod/compose.yaml` | `AUTH`, `AUTH_TOKEN`, `CONTAINER`, `EDIT`, `EXTERNAL`, `HMAC`, `HOST`, `LISTEN`, `MODBUS_AUTH`, `MODBUS_AUTH_KEY`, `MODBUS_UPSTREAM_AUTH`, `MODBUS_UPSTREAM_AUTH_KEY`, `ONLY`, `OUTSIDE` … | 8080, 9350 |
| `docker/prometheus.yml` | `SECURITY` | — |

**The port map 1:1** — the registries back every port the docker
surface names (a port here that no knob backs is the lie this
sweep exists for):

| port | the knobs backing it | where the docker surface names it |
|---|---|---|
| 5502 | inverter:listen | docker/Dockerfile.modbus-fake-inverter EXPOSE |
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
against `dev/suites/*.py` (word-bounded). Word-match honesty: the suites
are prose too — a name inside another word counts as covered; the
list is the TODO seed, not a verdict.

**The live knobs no suite mentions** (word-bounded grep):

- cache: every live knob named somewhere in the suites
- scraper: every live knob named somewhere in the suites
- inverter: every live knob named somewhere in the suites
- dashboard: `static-dir`

**The command words no suite mentions:**

- cache: every command exercised
- scraper: every command exercised
- inverter: every command exercised
- dashboard: every command exercised

**The canon phrases no suite pins**: 11

**The graduation path**: the seeds carry stable IDs in
[docs/family-drift-seeds.json](family-drift-seeds.json) (12
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

## The F-ledger sweep — docs/SECURITY.md vs the tree

Each F-number's title from the audit doc, and which of the family's
files cite it — the promise ledger against the code.

| F | title | cited by |
|---|---|---|
| F1 | Modbus TCP carries no authentication and no encryption | — |
| F14 | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics trave | apps |
| F15 | The metrics expose production values (generation, consumption, battery SoC) | — |

The findings:

- **The cited-by column is the enforcement map**: an F whose only
  citations are the audit doc itself has no enforcement markers in
  the tree (either the F is enforced in code without a marker — add
  the marker — or it is not enforced — the ledger lies). The F-suffix
  convention (the code comments cite `F13 in docs/SECURITY.md`) is the
  family's traceability habit; the sweep keeps it honest.

## The statics sweep — the four defaults.json blocks

Every leaf key-path of the four `lib/defaults.json` files (the non-knob
statics since the knobs' defaults moved into the registry rows'
`default` fields): the shared paths whose values disagree, the
only-there paths.

35 leaf paths; 1 in all four; 0 shared with differing values.

The findings:

- **The defaults.json blocks are the non-knob statics' home** (the
  simulators' grid constants, the diagnostics block, the log levels)
  — the knobs' defaults live in the registry rows' `default` fields
  now (editor.py edits them; check_options validates them). The
  shared-path matrix is the ruling surface for what remains.

## The schema/example sweep — the derived sources

The JSON Schemas' properties against the registry rows, and every
shipped example re-parsed through the tool's own set-grammar reader
(not just name-checked).

| tool | schema files |
|---|---|
| cache | none |
| scraper | `metrics.schema.json` |
| inverter | none |
| dashboard | none |
| shared | `acl-ip-prefix.schema.json`, `acl-write-registers.schema.json`, `modbus-cache-filter.schema.json` |

**The shipped examples re-parsed** through the tools' own readers:

| example | the read |
|---|---|
| `apps/cache/examples/modbus-cache.conf` | parse failed: No module named 'cache' |
| `apps/scraper/examples/metrics.json` | json ok |
| `apps/scraper/examples/modbus-scraper.conf` | parse failed: No module named 'scraper' |
| `apps/inverter/examples/modbus-fake-inverter.conf` | parse failed: No module named 'inverter' |
| `apps/dashboard/examples/dashboard.conf` | parse failed: No module named 'dashboard' |
| `extras/examples/acl-ip-prefix.json` | json ok |
| `extras/examples/acl-write-registers.json` | json ok |
| `extras/examples/modbus-cache-filter.json` | json ok |

The findings:

- **The shared pair is the pattern**: the standalone acl file's two
  gates (ip-prefix + write-registers) ship their example + schema ONCE
  at extras/examples/ + shared/schema/ — the four per-tool ip-prefix
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

23 secret-marked row(s) across 9 knob(s), consolidated by posture:

| knob | tools | live | restart | hidden |
|---|---|---|---|---|
| `auth-token` | dashboard, scraper | yes | yes | yes |
| `config-js` | dashboard | yes | yes | yes |
| `control-ops-token` | all four | yes | yes | yes |
| `control-token` | all four | yes | yes | yes |
| `dump-key` | all four | yes | yes | yes |
| `metrics-token` | cache, dashboard, inverter | yes | yes | yes |
| `modbus-auth-key` | cache, inverter, scraper | yes | yes | yes |
| `modbus-auth-upstream-key` | cache | yes | yes | yes |
| `static-dir` | dashboard | yes | yes | yes |

**The markers per tool** (the F-trust surface: the loader parses,
the dumps placeholder, the examples and configs reference):

| tool | parse_secret | SECRET_REMOVED | file: |
|---|---|---|---|
| cache | **MISSING** | **MISSING** | **MISSING** |
| scraper | **MISSING** | **MISSING** | **MISSING** |
| inverter | **MISSING** | **MISSING** | **MISSING** |
| dashboard | **MISSING** | **MISSING** | **MISSING** |

The findings:

- **The secret rows' posture should be uniform**: secret + restart
  (a secret never rides the reload state — the placeholder rule) +
  hidden (no live listing). A row that breaks the shape is the
  drift.
- **The markers' census** (`parse_secret`, `SECRET_REMOVED`,
  `file:`) is the F-trust surface: the loader parses, the dumps
  placeholder, the examples reference. A tool missing a marker is
  the story to chase.

## The console-print sweep — the one pager door

The cli session path (common/wire/cli.py + the four bin/*-cli.py)
prints through `page_out`/`display` only: a naked `print(` with an
argument is the drift (the bare `print()` pre-prompt blank is the
loop's own). `--check` fails on any finding — the door holds or the
wave explains itself.

The door holds: 2 session-path files,
every print through `page_out`/`display` (the bare pre-prompt
blinks excepted).


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

