# The family drift — the shared-code sweeps (regenerated)

The wave record: the sweep types over the four surfaces (cache,
scraper, inverter, dashboard) — what each sweeps, what it found,
and the verdicts. **A working paper, not a shipped doc**; the
landed legs ride their per-tool commits when the wave goes in.
Regenerate with `python3 scripts/family_drift.py`; the verdict
prose lives in this script (`*_FINDINGS`/`*_VERBS`/`*_CENSUS`)
so a re-run updates the facts and keeps the judgement.

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
11. **The statics sweep** — the four static.json blocks by
    key-path.
12. **The schema/example sweep** — the JSON Schemas vs the
    registries; the shipped examples re-parsed.
13. **The secret-surface sweep** — the secret rows and the
    posture markers.

**The wave's verification state** (Nov 9): every `--help`/`--man`
byte-identical vs HEAD; `check_options` + `lint_options --check` clean;
the ten-suite battery green (the cache/scrape regtests and the
cache-fuzz legs needed one clean re-run after the killed first
battery's daemons squatted the suite ports — the failures were port
squatters, not code; the bind-note's clean death told the story).

## The code sweep — the text-structural pass

Every per-tool `lib/*.py` and `bin/*.py` function, AST-normalized (the
line numbers and the local names collapse, the constant values stay),
compared two ways: the exact pass groups identical bodies (the
copy-paste twins), the similarity pass pairs cross-file bodies over the
0.72 ratio (the near-copies that already drifted).

**The exact pass**: 1 duplicate group(s) in >= 2 files.

- 22L `_load_options`: `scraper/lib/options.py:34`, `dashboard/lib/options.py:34`

**The similarity pass**: 50 cross-file pair(s) over the ratio
floor (30 of them the man-page prose, per-tool by
design); the top non-man pairs:

| ratio | pair |
|---|---|
| 1.00 | `scraper/lib/options.py:34` `_load_options` <-> `dashboard/lib/options.py:34` `_load_options` |
| 0.96 | `scraper/lib/control.py:146` `command` <-> `dashboard/lib/control.py:88` `command` |
| 0.94 | `scraper/lib/control.py:129` `command_help` <-> `dashboard/lib/control.py:221` `command_help` |
| 0.93 | `scraper/bin/modbus-scraper.py:45` `parse_args` <-> `dashboard/bin/dashboard.py:278` `parse_args` |
| 0.89 | `scraper/bin/modbus-scraper.py:237` `graceful_stop` <-> `dashboard/bin/dashboard.py:457` `graceful_stop` |
| 0.86 | `cache/lib/control.py:96` `command` <-> `dashboard/lib/control.py:88` `command` |
| 0.86 | `cache/bin/modbus-cache.py:48` `parse_args` <-> `scraper/bin/modbus-scraper.py:45` `parse_args` |
| 0.85 | `cache/lib/control.py:96` `command` <-> `scraper/lib/control.py:146` `command` |
| 0.85 | `cache/bin/modbus-cache.py:48` `parse_args` <-> `dashboard/bin/dashboard.py:278` `parse_args` |
| 0.83 | `cache/lib/options.py:24` `_load_options` <-> `scraper/lib/options.py:34` `_load_options` |
| 0.83 | `cache/lib/options.py:24` `_load_options` <-> `dashboard/lib/options.py:34` `_load_options` |
| 0.79 | `inverter/lib/control.py:140` `__init__` <-> `dashboard/lib/control.py:68` `__init__` |
| 0.79 | `cache/bin/modbus-cache.py:371` `watch_dump` <-> `common/control.py:697` `run_dump_interval` |
| 0.78 | `inverter/lib/signals.py:30` `__init__` <-> `common/modbus/client.py:20` `__init__` |
| 0.78 | `inverter/lib/control.py:544` `acl_table_report` <-> `dashboard/lib/control.py:512` `acl_table_report` |
| 0.76 | `scraper/lib/server.py:97` `relay` <-> `dashboard/bin/dashboard.py:175` `relay` |
| 0.75 | `inverter/lib/control.py:68` `handle` <-> `common/control.py:245` `handle` |
| 0.74 | `cache/lib/control.py:1028` `dump_state` <-> `common/control.py:634` `dump_state` |
| 0.74 | `cache/lib/config.py:115` `load_profile_write_gate` <-> `common/config.py:420` `load_write_gate_file` |
| 0.72 | `common/config.py:14` `resolve_target` <-> `common/daemon.py:44` `default_config_path` |

## The surface sweep — the listeners, the wire and the loops

The architectural pass: every listener the family opens, the wire tier
it speaks, the loop machinery behind it. The census is generated from
the tree; the verdicts are editorial.

The listener census (ten listeners):

| tool | surface | the class at it | the bind | the stack at it |
|---|---|---|---|---|
| inverter | Modbus TCP (the device) | `FakeInverter.serve` (lib/inverter.py) | backlog 16 | `conn_gate` -> connect ACL -> `max_clients` -> per-conn thread; the suite handshake in-handle; the chaos injector |
| cache | Modbus TCP (the client face) | `Proxy.serve` (lib/proxy.py) | backlog 128 | the same ladder; the write-gate layers in `respond()` (shape -> allow-write -> write ACL -> register gate); the requests audit |
| inverter | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | `common/metrics_server` — the snapshot() hook is the tool's |
| cache | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook |
| dashboard | /metrics | `MetricsServer` (lib/metrics.py) | the F13 floor | the common server; the snapshot() hook |
| scraper | /metrics (the exposition) | `Server` + `Handler` (lib/server.py) | the caps + the metrics/acl | its own Handler — the family's exposition shape (bearer, the spec render, the upstream relay) |
| dashboard | the page (static + proxy) | `Server` + `Handler` (bin/dashboard.py) | the caps | its own Handler — the cookies, the static tier, the /prom proxy, /config.js |
| all four | the control socket (unix, opt TCP) | `ControlServer` (common/control.py) | 0600/0660 | the one shared wire: the token/RBAC roles, the HMAC frames, the caps live here |

The findings:

- **The accept-ladder twins (the big one — found, not landed).** The
  cache's `Proxy.serve` and the fake's `FakeInverter.serve` carry the
  same ~35-line accept discipline near-verbatim: settimeout ->
  `conn_gate.admit` (the per-IP cap, the log text identical) -> the
  connect-ACL check (release + `connection rejected: ... not on the
  connect ACL`) -> the `max_clients` check (release + `connection
  refused: client limit ...`) -> the count under the lock -> the
  handler thread -> the pre-serve failure unwind -> the `finally`
  close. The deltas are three: the listen backlog (128 vs 16), the
  fake's outer retry loop (its SignalBox closes the listener and the
  loop must notice the `stopping` flag — the cache's accept never
  fails by decision), and where the auth material reads (the cache's
  live config dict vs the fake's ctor attrs). **The next leg**: a
  `common/modbus/server.py` accept ladder (gate, acl, max_clients,
  timeout, handle, stopping=None) — both serves shrink to ~10 lines
  and the log texts get one home.
- **The session opener twins (rides the same leg).** `handle()`'s
  first act is the same in both: register the client in the `clients`
  dict under the lock, run the suite handshake when armed
  (`auth_handshake_server`, the failure logs identical, the peer
  dropped before it ever sees a frame), count the requests per frame,
  and the `finally` unregisters (pop, count, `conn_gate.release`,
  close) — the cache adds the audit trail's `REQUESTS` event, the
  fake none (its audit rides the control plane).
- **The malformed-frame split (a difference to keep).** On an
  unparseable frame the fake logs and closes; the cache answers what
  it can in-band (`respond`'s proto/pdu guards -> exception frame)
  and closes silently on the hopeless MBAP. The cache is a proxy —
  its client deserves the protocol answer; the device just hangs up.
  A common ladder needs this as a policy hook, not a fold.
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

The verdict: one new landed-leg candidate (the Modbus accept ladder +
the session opener, worth ~50 lines net and one home for the family's
refusal texts); the rest of the surface drift is at parity or declined
with the reasons above.

## The knobs drift — the four registries side by side

The registry pass: `lib/options.json` x 4 diffed by name, by field and
by semantic family — the knob layer is the one source --help, the man
pages, the set grammar, the NixOS modules and the README checks read,
so a drifted row travels wide.

**The shape**: 208 knob rows across the
four registries; 24 names carry in all four:

`audit-files`, `audit-log`, `audit-max-mb`, `auth`, `client-timeout`, `control`, `control-ops-token`, `control-ops-verbs`, `control-port`, `control-socket-group`, `control-token`, `control-trust-uids`, `control/ops`, `dump`, `dump-interval`, `dump-key`, `dump-path`, `log-level`, `max-clients`, `max-conn-per-ip`, `metrics`, `metrics-acl`, `no-audit-log`, `restore-on-start`

**The tool-specific remainder** (by nature):

| tool | only-there knobs |
|---|---|
| cache | `acl`, `allow-write`, `audit`, `audit-daily`, `audit/rotate`, `auth-key`, `auth-upstream`, `auth-upstream-key`, `cache-ttl`, `connect-acl`, `dump-with-cache`, `interval`, `limits`, `listen`, `local-time`, `log-access`, `merge-gap`, `metrics-client-timeout`, `metrics-listen`, `metrics-max-clients`, `metrics-max-conn-per-ip`, `metrics-server`, `metrics-token`, `metrics/limits`, `modbus`, `profile`, `read-delay`, `requests-audit`, `selection`, `system`, `timeout`, `unit`, `upstream`, `write`, `write-acl`, `write-registers` |
| scraper | `audit`, `audit/rotate`, `auth-key`, `auth-token`, `caps`, `grid-positive-import`, `interval`, `listen`, `local-time`, `log-access`, `max-grid-kw`, `max-kwp`, `metric-prefix`, `metrics-spec`, `metrics/auth`, `metrics/limits`, `modbus`, `modbus-offset`, `modbus-unit`, `profile`, `timeout`, `upstream` |
| inverter | `allow-write`, `audit-daily`, `auth-key`, `batt`, `battery-kwh`, `battery-state`, `chaos`, `cloud`, `connect-acl`, `control-log-replies`, `grid`, `grid-frequency`, `grid-outage`, `grid-voltage`, `host`, `load`, `max-kwp`, `metrics-client-timeout`, `metrics-listen`, `metrics-max-clients`, `metrics-max-conn-per-ip`, `metrics-server`, `metrics-token`, `modbus`, `mppt`, `port`, `profile`, `pv`, `scenario`, `seed`, `soc`, `static`, `strict`, `time`, `time-scale`, `timezone`, `unit`, `write` |
| dashboard | `auth-token`, `bind`, `config-js`, `local-time`, `log-access`, `log-queries`, `metrics-client-timeout`, `metrics-listen`, `metrics-max-clients`, `metrics-max-conn-per-ip`, `metrics-server`, `metrics-token`, `port`, `prom-prefix`, `static-dir`, `upstream` |

**The shared knobs whose fields disagree** (9 of
24):

| knob | the drifted fields (cache / scraper / inverter / dashboard) |
|---|---|
| `audit-files` | env: c="AUDIT_FILES" | s="AUDIT_FILES" | i=null | d=null <br> live: c="audit/rotate/files" | s="audit/rotate/files" | i="·" | d="·" <br> min: c=1 | s="·" | i="·" | d="·" <br> max: c=100 | s="·" | i="·" | d="·" |
| `audit-log` | env: c="AUDIT_LOG" | s="AUDIT_LOG" | i=null | d=null <br> live: c="audit/log-file" | s="audit/log-file" | i="·" | d="·" |
| `audit-max-mb` | env: c="AUDIT_MAX_MB" | s="AUDIT_MAX_MB" | i=null | d=null <br> live: c="audit/rotate/max-size" | s="audit/rotate/max-size" | i="·" | d="·" <br> min: c=0 | s="·" | i="·" | d="·" <br> max: c=1048576 | s="·" | i="·" | d="·" |
| `auth` | flag: c="--auth" | s="--auth" | i="--auth" | d="·" <br> env: c="AUTH" | s="AUTH" | i="AUTH" | d="·" <br> conv: c="str" | s="str" | i="str" | d="·" <br> live: c="modbus/auth" | s="modbus/auth" | i="modbus/auth" | d="·" <br> values: c=["suite", "none"] | s=["suite", "none"] | i=["suite", "none"] | d="·" <br> node: c="·" | s="·" | i="·" | d=true |
| `client-timeout` | env: c="CLIENT_TIMEOUT" | s="CLIENT_TIMEOUT" | i=null | d="CLIENT_TIMEOUT" <br> live: c="limits/client-timeout" | s="metrics/limits/timeout" | i="client-timeout" | d="client-timeout" |
| `log-level` | env: c="LOG_LEVEL" | s="LOG_LEVEL" | i="LOG_LEVEL" | d=null |
| `max-clients` | env: c="MAX_CLIENTS" | s="MAX_CLIENTS" | i=null | d="MAX_CLIENTS" <br> live: c="limits/max-clients" | s="metrics/limits/max-clients" | i="max-clients" | d="max-clients" |
| `max-conn-per-ip` | env: c="MAX_CONN_PER_IP" | s="MAX_CONN_PER_IP" | i=null | d="MAX_CONN_PER_IP" <br> live: c="limits/max-conn-per-ip" | s="metrics/limits/max-conn-per-ip" | i="max-conn-per-ip" | d="max-conn-per-ip" |
| `no-audit-log` | env: c="NO_AUDIT_LOG" | s=null | i=null | d=null <br> live: c="audit/disable" | s="audit/disable" | i="·" | d="·" |

**The command vocabularies** (the wire words per tool):

- cache: `help`, `inspect`, `ping`, `quit`, `request`, `request/clear`, `request/clear/cache`, `request/dump`, `request/dump`, `request/dump/with-cache`, `request/reload`, `request/restart`, `request/restore`, `set`, `show`, `shutdown`, `unset`
- scraper: `help`, `inspect`, `ping`, `poll`, `poll/now`, `quit`, `request`, `request/dump`, `request/reload`, `request/reload-config`, `request/restart`, `request/restore`, `set`, `show`, `shutdown`, `unset`
- inverter: `exit`, `help`, `inspect`, `logout`, `ping`, `quit`, `request`, `request/dump`, `request/reload`, `request/restore`, `reset`, `set`, `show`, `shutdown`, `unset`
- dashboard: `help`, `inspect`, `ping`, `quit`, `request`, `request/dump`, `request/reload`, `request/reload-config`, `request/restore`, `set`, `show`, `shutdown`, `unset`

**The command deltas worth a ruling:**

- `request/clear/cache` + `request/dump/with-cache` — the cache only
  (the write-behind cadence and the flush verb are its nature).
- `request/reload-config` — the scraper and the dashboard (the cache's
  reload execs and re-reads in one, the fake's re-applies the env
  layer: no separate re-read surface).
- `request/restart` — absent on the fake (no config file to re-exec
  into; its restart-marked overrides still fold on a manual restart,
  the note stays true).
- `reset` (the SIGUSR1 scenario reset) + `exit`/`logout` — the fake's
  console verbs (F11).
- `poll/now` — the scraper's poll trigger.

The findings:

- **The live bounds ride the cache only.** The cache's `audit-files`
  (min 1, max 100) and `audit-max-mb` (min 0, max 1048576) are
  bound-gated at the live dispatch; the scraper's same-named rows
  carry NO bounds — its live `set audit rotate files 0` would be
  accepted where the cache refuses. The bounds should mirror (or the
  shared bounds move into common as the family's constants).
- **The `audit-daily` split.** Four shapes for one feature: the
  cache's `audit-daily` is live (`audit/rotate/daily`), the fake's is
  startup-only (no live name — F11, but its registry row exists), the
  scraper and the dashboard have no daily knob at all (the scraper's
  `audit/rotate` node help omits the midnight trigger accordingly).
  The common `AuditLog` supports daily for everyone; the switch is
  what drifted. Decide: family-wide live knob, or cache-only by
  design.
- **The env-twin gaps.** `$AUDIT_LOG/$AUDIT_MAX_MB/$AUDIT_FILES` on
  the cache and scraper only (the fake's and dashboard's audit knobs
  are config-only), `$NO_AUDIT_LOG` on the cache only, `$LOG_LEVEL`
  missing on the dashboard, and the F13 caps' env twins
  (`$MAX_CLIENTS`, `$MAX_CONN_PER_IP`, `$CLIENT_TIMEOUT`) missing on
  the fake (its env layer is the F11 short list). Probably design,
  worth a ruling: the env layer is the docker surface — a knob
  without its twin cannot be set from an env file.
- **The `auth` name collision.** The dashboard's `auth` is a NODE
  (the page's auth namespace), the other three's is the modbus auth
  enum (`suite|none`). One spelling, two meanings in the family's
  set-grammar space — legal (the registries are per-tool), but the
  merged-knob view (docs/OPTIONS.md) and any future family-wide
  grammar should note it.
- **The `listen` naming map.** The cache's serve face is live
  `system/listen` (restart-marked), the scraper's is
  `metrics/listen` (its whole HTTP surface IS the metrics surface),
  the dashboard binds via `bind`/`port` (no live name), the fake via
  `host`/`port` (argv only). The meanings line up per tool; the
  family lacks one word for "the address this daemon serves on".
- **`KNOWN_VERBS` is hand-maintained.** The RBAC vocabulary lives as
  a Python tuple in each `lib/options.py` beside the registry that
  defines the same verbs as rows — two homes for one truth (the
  commands-lint gates the registry, not the tuple). A drift here is
  silent: an ops policy accepting a verb the grammar refuses, or the
  reverse. Candidate: derive `KNOWN_VERBS` from the registry's
  command rows at load.

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

**The phrase canon**: 40 log phrase(s) shared by >= 2 tools;
77 tool-local. The canon (the lead clause, the tools that speak it):

| the lead clause | tools |
|---|---|
| `control: unset` | cache, dashboard, inverter, scraper |
| `acl file:` | cache, dashboard, inverter, scraper |
| `stopped` | cache, dashboard, inverter, scraper |
| `client` | dashboard, inverter, scraper |
| `connection rejected:` | cache, dashboard, inverter, scraper |
| `write:` | cache, inverter |
| `write: refused` | cache, inverter |
| `control client from` | common, inverter |
| `control: set` | cache, dashboard, inverter, scraper |
| `control: shutdown requested` | cache, dashboard, inverter, scraper |
| `shutdown:` | cache, dashboard, inverter, scraper |
| `the state dump` | cache, common, inverter |
| `state dumped to` | cache, common |
| `cannot bind` | common, dashboard, scraper |
| `sighup: reload failed ` | cache, common, inverter |
| `unhandled error serving` | dashboard, scraper |
| `dry-run: configuration is valid nothing was boun` | dashboard, inverter, scraper |
| `restore-on-start:` | dashboard, inverter, scraper |
| `control from` | common, inverter |
| `control: state dumped to` | cache, common |
| `control: state restored from` | cache, common |
| `control: the dump to` | cache, common |
| `sighup: reloaded` | cache, inverter |
| `error handling` | cache, inverter |
| `poll cycle crashed ` | cache, scraper |

The findings:

- **The audit vocabulary is tight** — the family speaks one event set;
  the tool-specific events are few and by nature. The matrix above is
  the canonical spelling list: a new event name should read it first.

## The exit-and-refusal sweep — the failure ladder

Every `SystemExit` site with its rc and its refusal text, compared for
the family canon: same cause, same code, same text shape.

**The rc summary** + **the distinct refusal texts** (the literal
message args — the family's refusal canon):

- rc 0 (the clean exits): 9; rc 1 (the binds): 16; rc 2 (the CLI mistakes): 6; 0 site(s) raising a variable (the message/`rc` computed —
  the common SystemExit(str) prints the message and exits 1).

The refusal texts (the literal SystemExit args, sorted):

- `"table" is not a metrics/acl value — the table is the show: show metrics acl table`
- `"table" is not an acl/connect value — the table is the show: show acl connect table`
- `"table" is not an acl/write value — the table is the show: show acl write table`
- `?`
- `allow-write must be on or off`
- `audit/disable must be on or off`
- `audit/rotate/daily must be on or off`
- `auth handshake rejected by the peer (key mismatch?)`
- `bad auth handshake reply`
- `battery-kwh must be a positive kWh value`
- `battery-state must be auto|charging|discharging`
- `connection closed by peer`
- `control/port cannot serve TCP without a token (F5 in docs/AUDIT.md): pass the token by flag/env/config and restart`
- `control/socket-group must be on or off`
- `dump-interval needs a dump path (set dump/path or --dump-path)`
- `dump/restore-on-start must be on or off`
- `dump/with-cache must be on or off`
- `fails its seal — the wrong dump/key, or edited content (nothing restored)`
- `grid-outage must be on|off|outage`
- `interval must be 0 < N <= 86400 seconds`
- `local-time must be on|off`
- `log-access must be on or off`
- `log-queries must be on or off`
- `max-kwp must be a positive kW value`
- `metrics enable must be on or off`
- `metrics-server must be on or off`
- `metrics/listen cannot move beyond loopback while the endpoint serves without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart`
- `mppt must be both|east|west|none`
- `no http server attached`
- `no log handler to re-format`
- `no modbus device attached`
- `no reply within the socket timeout`
- `non-finite result`
- `not a boolean`
- `refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart, or bind 127.0.0.1:PORT`
- `restart required (startup-only knob)`
- `short response: function byte only`
- `system/log-access must be on or off`
- `the Waveshare password must be ASCII`
- `the control connection closed without a bye`
- `the control connection failed`
- `the metrics endpoint serves register values: refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart, or bind metrics/listen on 127.0.0.1`
- `the metrics endpoint serves the request counters: refusing to expose /metrics beyond loopback without a token (F13 in docs/AUDIT.md) — pass metrics-token by flag/env/config and restart, or bind metrics/listen on 127.0.0.1`
- `the ops token must differ from the admin token (the same secret would hand every holder the role the server picks first)`
- `the reply mac does not verify — the wire was tampered with`
- `the server did not sign the reply`
- `time out of range (00:00-23:59)`
- `timeout must be 0 < N <= 60 seconds`
- `timezone must be utc|local`
- `transaction id mismatch`
- `write/allow must be on or off`

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

- cache: How it works -> Diagnostics registers -> Register map (device profile) -> Usage -> Configuration -> Runtime control (signals) -> Runtime control (`--control-port`) -> Access control -> Modbus auth -> Persistence -> Metrics -> Audit logging -> Security -> Testing -> Nix / NixOS -> Source layout -> License
- scraper: How it works -> Metrics -> Device profile -> Battery -> Configuration -> Runtime control (signals) -> What /metrics leaks (the privacy note, F15) -> Logging and audit trail -> Test inverter -> Testing -> Nix / NixOS -> Source layout -> License
- inverter: Simulation -> Served registers (the default profile) -> Internal registers (not in the profile) -> Usage -> Configuration -> Runtime control -> Chaos injection (`--chaos`) -> Signals -> Docker -> Audit trail -> Security -> Testing -> Nix / NixOS -> Source layout -> License
- dashboard: Features -> Run -> Configuration -> Control -> Behind a reverse proxy -> Metrics source -> Notes -> Security -> Testing -> Nix / NixOS -> Source layout -> License

The findings:

- **The man ladders line up** (the same section order, the tool's own
  sections appended at the tail) — the gen_man.py generator owns the
  shape; the drift risk is a hand-edited page, which this sweep
  flags by the .SH ladder changing.
- **The README skeleton** is the one-skeleton wave's shape (how it
  works -> usage -> configuration -> runtime control -> the features
  -> security -> testing -> nix -> source layout -> license); a
  tool that grows a section the others lack is the drift this
  catches.

## The NixOS-parity sweep — the modules vs the registries

Each `module.nix` option's type and default against the same knob's
registry row — the units drift (MB vs bytes, seconds vs ms) and the
missing options are what this finds. Heuristic parse: the type/default
LINES are quoted, the verdicts curated.

| tool | mkOption blocks |
|---|---|
| cache | 12 |
| scraper | 43 |
| inverter | no module.nix |
| dashboard | 42 |

**The module options NOT matching a registry knob name** (after
the kebab/camel normalization; the `*File` suffix is the NixOS
LoadCredential pattern, not a knob):

- cache: `unitId`
- scraper: `listenHost`, `listenPort`
- dashboard: `host`, `prometheusUrl`

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
| `docker/demo/compose.yaml` | `AUTH`, `AUTH_KEY`, `AUTH_TOKEN`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `BIND`, `DEMO`, `HMAC`, `JSON`, `PROM_URL`, `PVA1`, `README`, `REQUIRED`, `SAME` | 8080 |
| `docker/entrypoints/entrypoint-prometheus.sh` | `AUDIT`, `POST`, `PROM_ADMIN_API`, `PROM_ARGS`, `PROM_LIFECYCLE`, `PROM_RETENTION`, `TOKEN_DST`, `TOKEN_SRC`, `TSDB` | — |
| `docker/entrypoints/entrypoint.sh` | `AUDIT`, `JSON`, `README`, `REQUIRED` | — |
| `docker/env/cache.env.example` | `AUTH`, `AUTH_KEY`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `DEBUG`, `ERROR`, `HOST`, `INFO`, `INTERVAL`, `LOG_LEVEL`, `PORT`, `SERVER`, `UPSTREAM`, `WARNING` | — |
| `docker/env/dashboard.env.example` | `AUTH_TOKEN`, `BIND`, `PLAIN`, `PROM_URL` | — |
| `docker/env/fake.env.example` | `CHAOS`, `MAX_KWP`, `PROFILE`, `SIGHUP`, `STRICT`, `TIME`, `TIME_SCALE` | — |
| `docker/env/prometheus.env.example` | `POST`, `PROM_`, `PROM_ADMIN_API`, `PROM_LIFECYCLE`, `PROM_RETENTION`, `TSDB` | — |
| `docker/env/scraper.env.example` | `AUTH_TOKEN`, `DEBUG`, `ERROR`, `HOST`, `INFO`, `INTERVAL`, `LOG_LEVEL`, `METRIC_PREFIX`, `PORT`, `UPSTREAM`, `VALUE`, `WARNING` | — |
| `docker/prod/README.md` | `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `EDITOR`, `HOST`, `JSON`, `PORT`, `PROM_URL`, `README`, `UPSTREAM`, `YOUR` | 8080, 9350 |
| `docker/prod/compose.yaml` | `AUTH`, `AUTH_KEY`, `AUTH_TOKEN`, `AUTH_UPSTREAM`, `AUTH_UPSTREAM_KEY`, `BIND`, `CONTAINER`, `EDIT`, `EXTERNAL`, `HMAC`, `HOST`, `ONLY`, `PORT`, `PRODUCTION` … | 8080, 9350 |
| `docker/prometheus.yml` | `AUDIT` | — |

The findings:

- **The env-file twins are the docker surface's contract**: a
  registry env twin missing from every compose/env file means the
  knob is unreachable from the deployment — sometimes design (the
  demo needs fewer knobs), sometimes a gap. The split wave's wiring
  list (the prod = three services + the external collector, the
  demo's in-stack shapes) is the expected drift.
- **The published ports** should map 1:1 to the registry defaults
  (the 935x block) — a port in a compose file that no knob backs is
  the lie this sweep exists for.

## The suite-coverage sweep — the promises x the tests

Every live knob name, command word and canon log phrase grepped
against `tests/*.py` (word-bounded). Word-match honesty: the suites
are prose too — a name inside another word counts as covered; the
list is the TODO seed, not a verdict.

**The live knobs no suite mentions** (word-bounded grep):

- cache: `audit-daily`, `audit-files`, `audit-max-mb`, `control-ops-verbs`, `control-trust-uids`, `metrics-client-timeout`, `metrics-max-conn-per-ip`, `read-delay`, `requests-audit`
- scraper: `audit-files`, `audit-max-mb`, `control-ops-verbs`, `control-trust-uids`, `modbus-offset`
- inverter: `control-ops-verbs`, `control-trust-uids`
- dashboard: `control-ops-verbs`, `control-trust-uids`, `log-queries`

**The command words no suite mentions:**

- cache: every command exercised
- scraper: every command exercised
- inverter: `logout`
- dashboard: every command exercised

**The canon phrases no suite pins**: 23

**The graduation path**: the seeds carry stable IDs in
[docs/family-drift-seeds.json](family-drift-seeds.json) (43
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
| F2 | The writer folds control characters in every detail line | — |
| F3 | Fail closed: an unparseable write frame is refused with ILLEGAL_VALUE and audite | — |
| F4 | Both control servers drop the connection past the 1 MB `MAX_LINE` (`cache/lib/co | — |
| F5 | The cache refuses to start a TCP control port without a token | cache, common, dashboard, inverter, scraper |
| F6 | The token is mandatory when the port is set | — |
| F7 | Nothing is published | — |
| F8 | Both control servers `chmod 0600` immediately after `bind()`; the cache takes `- | cache, common |
| F9 | Documented in all three READMEs and the token-flag man pages: the flag form is f | — |
| F12 | Fail closed: `check_token_file_mode` (`common/config | cache, common |
| F11 | The cache's knobs, mirrored: `--max-clients` (refuse past the limit at accept, ` | common, inverter |
| F13 | Fail closed beyond loopback: a non-loopback listen without `--auth-token`/`--aut | cache, common, dashboard, inverter, scraper |
| F10 | A chained hash per entry: every line carries a short hash right after the event  | cache, common |
| F18 | Fail closed, the F8/F12 pattern: the dump is created `0600` explicitly (`os | cache, common |
| F19 | The defaults flipped: the GitHub release is the workflow's job | — |
| F20 | One resolution shape family-wide, in every ctl/cli: `token_file = flag or env`,  | — |
| F21 | The scraper's F13 shape, page-sized: the bearer token (`--auth-token`/`$AUTH_TOK | dashboard |
| F22 | A second, read-only token per control server (`--control-ops-token`/`--control-o | — |
| F23 | The F18 posture, one surface over: the state file's tmp is created `0600` explic | — |
| F1 | Modbus TCP carries no authentication and no encryption | — |
| F14 | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics trave | dashboard |
| F15 | The metrics expose production values (generation, consumption, battery SoC) | — |
| F16 | No automated alerting yet (freshness gap, poll down, exception spikes | — |
| F17 | The `/config` volume holds the live ini files | — |

The findings:

- **The cited-by column is the enforcement map**: an F whose only
  citations are the audit doc itself has no enforcement markers in
  the tree (either the F is enforced in code without a marker — add
  the marker — or it is not enforced — the ledger lies). The F-suffix
  convention (the code comments cite `F13 in docs/AUDIT.md`) is the
  family's traceability habit; the sweep keeps it honest.

## The statics sweep — the four static.json blocks

Every leaf key-path of the four `lib/static.json` files: the shared
paths whose values disagree, the only-there paths (the audit
defaults, the caps, the grid constants the loaders wire via
`static_defaults`).

100 leaf paths; 13 in all four; 0 shared with differing values.

The findings:

- **The static.json blocks are the tools' personalities** (the
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
| cache | `acl-write-registers.schema.json`, `selection.schema.json` |
| scraper | `metrics.schema.json` |
| inverter | none |
| dashboard | none |

**The shipped examples re-parsed** through the tools' own readers:

| example | the read |
|---|---|
| `cache/examples/acl-write-registers.json` | json ok |
| `cache/examples/modbus_cache.conf` | ok (31 setting line(s)) |
| `cache/examples/selection.json` | json ok |
| `scraper/examples/metrics.json` | json ok |
| `scraper/examples/scraper.conf` | ok (18 setting line(s)) |
| `dashboard/examples/server.conf` | ok (20 setting line(s)) |

The findings:

- **The shared pair is the pattern**: the ip-prefix acl's example +
  schema live ONCE at the root examples/ + schema/ (the four
  per-tool copies died in the shared-examples wave). The per-tool
  schema/ dirs that remain carry the tool-specific shapes.
- **The examples re-parse is the honest check**: a shipped example
  that the tool's own reader refuses is a broken promise shipped to
  every user who copies it. The table above is that check.

## The secret-surface sweep — the secret rows and their posture

Every `secret`-marked registry row with its live/restart/hidden
flags, and the secret-posture markers (`parse_secret`, the
`SECRET_REMOVED` placeholder, the `file:` scheme) across the tree.

21 secret-marked row(s):

| tool | knob | live | restart | hidden |
|---|---|---|---|---|
| cache | `auth-key` | yes | yes | yes |
| cache | `auth-upstream-key` | yes | yes | yes |
| cache | `control-token` | yes | yes | yes |
| cache | `control-ops-token` | yes | yes | yes |
| cache | `metrics-token` | yes | yes | yes |
| cache | `dump-key` | yes | yes | yes |
| scraper | `auth-key` | yes | yes | yes |
| scraper | `control-token` | yes | yes | yes |
| scraper | `control-ops-token` | yes | yes | yes |
| scraper | `auth-token` | yes | yes | yes |
| scraper | `dump-key` | yes | yes | yes |
| inverter | `auth-key` | yes | yes | yes |
| inverter | `control-token` | yes | yes | yes |
| inverter | `control-ops-token` | yes | yes | yes |
| inverter | `metrics-token` | yes | yes | yes |
| inverter | `dump-key` | yes | yes | yes |
| dashboard | `auth-token` | yes | yes | yes |
| dashboard | `control-token` | yes | yes | yes |
| dashboard | `control-ops-token` | yes | yes | yes |
| dashboard | `metrics-token` | yes | yes | yes |
| dashboard | `dump-key` | yes | yes | yes |

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

1. **The audit rotation bounds, family-wide** — `audit-files` (min 1,
   max 100) and `audit-max-mb` (min 0, max 1048576) carry bounds in
   all four registries; the constants live once in `common/` (the
   audit module's own). The user plane: `set audit rotate files 0`
   refuses identically everywhere. Today the scraper accepts it.

2. **The `audit-daily` knob, one shape** — the family-wide live knob
   `audit/rotate/daily`: the scraper and the dashboard gain the row,
   the fake's startup-only row gains its live name, the cache's
   (today the only live one) is the template. The user plane: the
   UTC-midnight trigger switches identically everywhere; the code
   plane: `rebuild_audit`'s `daily` rides the params everywhere (the
   common `AuditLog` already supports it).

3. **The env twins completed** — every knob reachable from an env
   file: `$AUDIT_LOG/$AUDIT_MAX_MB/$AUDIT_FILES` on the fake and the
   dashboard, `$NO_AUDIT_LOG` everywhere (or nowhere, one ruling),
   `$LOG_LEVEL` on the dashboard, the F13 caps' twins
   (`$MAX_CLIENTS/$MAX_CONN_PER_IP/$CLIENT_TIMEOUT`) on the fake.
   The user plane: the docker env files drive the whole surface; the
   code plane: the loaders read one env layer. A knob ruled
   env-free carries a registry note instead of a silent gap.

4. **The `auth` name collision resolved** — one spelling, one
   meaning: the dashboard's `auth` node (the page's namespace)
   renames (`page-auth/` or the rows re-home), or the modbus enum
   re-homes; the set grammar never maps one word to two meanings.
   Breaking change for the dashboard's live names — the TODO is the
   proposal + the migration note (the alias map carries the old
   spellings one release).

5. **The serve-address word** — the family answers one question with
   one word: `show system listen` prints the address the daemon
   serves on, everywhere. The cache's `system/listen` is the canon;
   the scraper's `metrics/listen` stays as the alias; the fake's
   `host`/`port` gain the live name (F11 keeps the argv defaults);
   the dashboard's `bind`/`port` gain theirs.

6. **`request/reload-config` family-wide** — the re-read-without-exec
   surface exists on the scraper and the dashboard; the cache gains
   it (its reload execs; a profile or selection edit deserves the
   lighter verb). The fake stays exempt — no config file, F11 — and
   the asymmetry gets the registry note.

7. **`KNOWN_VERBS` derived, not hand-maintained** — the loaders build
   the RBAC vocabulary from the registry's command rows (the
   hidden/internal flags included). One home; the silent drift
   (a policy accepting a verb the grammar refuses) dies.

8. **The accept-ladder extraction** — `common/modbus/server.py`: the
   gate -> ACL -> max-clients -> count -> thread discipline + the
   session opener (the clients register, the suite handshake, the
   `finally` unwind) with the malformed-frame policy hook (the
   cache answers in-band, the fake closes). The user plane: the
   identical refusal texts and logs at both Modbus faces; the code
   plane: the surface sweep's ~50-line net win.

9. **The coverage TODOs graduate** — the seeds carry stable IDs in
    docs/family-drift-seeds.json (`family_drift.py --seeds`, the
    suggested suite per seed); a test wave consumes entries, the
    regeneration drops them, the shrinkage is the wave's proof, and
    `--check` fails when a NEW promise ships uncovered (the list may
    only shrink).

10. **The parity gates wired** — the NixOS-parity and docker/env
    sweeps join `check_options`/the release gates as machine checks
    (the module.nix type/default vs the registry, the env-file
    coverage vs the env twins). The drift doc's `--check` already
    shows the pattern: a stale claim fails the gate.

Not-todo (the ruling recorded): the fake's `request/restart` verb
stays absent (no config to re-exec into — the fold on a manual
restart keeps the note true); the man-page prose and the HTTP
handlers stay per-tool by design; the malformed-frame split is the
proxy/device difference, kept.

