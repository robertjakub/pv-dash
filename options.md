# The knobs of the family (options.md)

One alphabetical table of every knob of the four daemons — the kind,
the name, the function it files under and the control command that
changes it on a running daemon — with a mark per
tool. **Generated** from the per-tool `lib/options.json` registries (the
one-knob-one-source rows) by `scripts/gen_options.py` — edit the
registries and re-run `python3 scripts/gen_options.py`, never this file.
The resolution order on every tool is flag > env > config script >
default; the bare `$NAME` env forms are the knob's upper-snake name.
Every bin also carries the CLI-only `--config`/`--dry-run`/`--man`
(plus `--version`/`--help`) — flags, not knobs, so they have no rows
here. The ctl/cli clients speak the control plane only
(`--control-port`, the token file/env pair) and are not compared.

Common to **all four** tools (15): `audit-files`, `audit-log`, `audit-max-mb`, `client-timeout`, `control-ops-token`, `control-ops-token-file`, `control-ops-verbs`, `control-port`, `control-token`, `control-token-file`, `control-trust-uids`, `log-level`, `max-clients`, `max-conn-per-ip`, `no-audit-log`. The control-plane block is
shared nearly verbatim; the audit, limits and metrics blocks follow the
family shape with per-tool defaults.

| kind | name | function | live | cache | scraper | inverter | dashboard |
|---|---|---|---|---|---|---|---|
| k | `allow-write` | device | `set allow-write` | ✓ live |  |  |  |
| k | `audit-daily` | audit trail | *(startup-only)* | ✓ |  | ✓ |  |
| k | `audit-files` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `audit-log` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `audit-max-mb` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `auth-token` | own /metrics | *(startup-only)* |  | ✓ secret |  |  |
| k | `auth-token-file` | own /metrics | *(startup-only)* |  | ✓ secret |  |  |
| c | `batt` | device | `set batt` |  |  | ✓ live |  |
| k | `battery` | device | `set battery` |  | ✓ | ✓ live |  |
| k | `battery` | serving | `set battery` |  |  |  | ✓ live |
| k | `battery-kwh` | device | `set battery-kwh` |  |  | ✓ live |  |
| c | `battery-state` | device | `set battery-state` |  |  | ✓ live |  |
| k | `bind` | serving | *(startup-only)* |  |  |  | ✓ |
| k | `cache-ttl` | device | `set ttl` | ✓ live |  |  |  |
| k | `chaos` | device | `set chaos` |  |  | ✓ live |  |
| k | `client-timeout` | limits | `set client-timeout` | **✓** live | **✓** live | **✓** live | **✓** live |
| c | `cloud` | device | `set cloud` |  |  | ✓ live |  |
| k | `config-js` | serving | *(startup-only)* |  |  |  | ✓ |
| k | `connect-acl` | device | `set connect-acl` | ✓ live |  | ✓ live |  |
| k | `control-log-replies` | control plane | *(startup-only)* |  |  | ✓ |  |
| k | `control-ops-token` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-ops-token-file` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-ops-verbs` | control plane | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `control-port` | control plane | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `control-socket-group` | control plane | *(startup-only)* | ✓ |  | ✓ |  |
| k | `control-token` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-token-file` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-trust-uids` | control plane | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `dump-interval` | persistence | `set dump-interval` | ✓ live |  |  |  |
| k | `dump-path` | persistence | *(startup-only)* | ✓ |  |  |  |
| k | `dump-with-cache` | persistence | *(startup-only)* | ✓ |  |  |  |
| c | `grid` | device | `set grid` |  |  | ✓ live |  |
| k | `grid-frequency` | device | `set grid-frequency` |  |  | ✓ live |  |
| c | `grid-outage` | device | `set grid-outage` |  |  | ✓ live |  |
| k | `grid-positive-import` | device | *(startup-only)* |  | ✓ |  |  |
| k | `grid-voltage` | device | `set grid-voltage` |  |  | ✓ live |  |
| k | `host` | device | *(startup-only)* |  |  | ✓ |  |
| k | `interval` | device | `set interval` | ✓ live |  |  |  |
| k | `interval` | logging | `set interval` |  | ✓ live |  |  |
| k | `listen` | serving | *(startup-only)* | ✓ | ✓ |  |  |
| c | `load` | device | `set load` |  |  | ✓ live |  |
| k | `local-time` | serving | *(startup-only)* | ✓ | ✓ |  |  |
| k | `local-time` | logging | *(startup-only)* |  |  |  | ✓ |
| k | `log-access` | logging | `set log-access` | ✓ | ✓ live |  | ✓ live |
| k | `log-level` | logging | `set log-level` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `log-queries` | logging | `set log-queries` |  |  |  | ✓ live |
| k | `max-clients` | limits | `set max-clients` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `max-conn-per-ip` | limits | `set max-conn-per-ip` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `max-grid-kw` | device | *(startup-only)* |  | ✓ |  |  |
| k | `max-kwp` | device | `set max-kwp` |  | ✓ | ✓ live |  |
| k | `merge-gap` | device | `set merge-gap` | ✓ live |  |  |  |
| k | `metric-prefix` | device | *(startup-only)* |  | ✓ |  |  |
| k | `metrics-client-timeout` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| k | `metrics-listen` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| k | `metrics-max-clients` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| k | `metrics-max-conn-per-ip` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| k | `metrics-server` | own /metrics | `set metrics-server` | ✓ live |  | ✓ live | ✓ live |
| k | `metrics-spec` | device | *(startup-only)* |  | ✓ |  |  |
| k | `metrics-token` | own /metrics | *(startup-only)* | ✓ secret |  | ✓ secret | ✓ secret |
| k | `metrics-token-file` | own /metrics | *(startup-only)* | ✓ secret |  | ✓ secret | ✓ secret |
| k | `modbus-offset` | device | *(startup-only)* |  | ✓ |  |  |
| k | `modbus-unit` | device | *(startup-only)* |  | ✓ |  |  |
| c | `mppt` | device | `set mppt` |  |  | ✓ live |  |
| k | `no-audit-log` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `no-battery` | device | *(startup-only)* |  |  | ✓ |  |
| k | `port` | device | *(startup-only)* |  |  | ✓ |  |
| k | `port` | serving | *(startup-only)* |  |  |  | ✓ |
| k | `profile` | device | `set profile` | ✓ live | ✓ live | ✓ live |  |
| k | `prom-prefix` | serving | *(startup-only)* |  |  |  | ✓ |
| c | `pv` | device | `set pv` |  |  | ✓ live |  |
| k | `read-delay` | device | `set read-delay` | ✓ live |  |  |  |
| k | `requests-audit` | audit trail | `set requests-audit` | ✓ live |  |  |  |
| k | `restore-on-start` | persistence | *(startup-only)* | ✓ |  |  |  |
| c | `scenario` | device | `set scenario` |  |  | ✓ live |  |
| k | `seed` | device | `set seed` |  |  | ✓ live |  |
| k | `selection` | device | `set selection` | ✓ live |  |  |  |
| c | `soc` | device | `set soc` |  |  | ✓ live |  |
| k | `static` | device | `set static` |  |  | ✓ live |  |
| k | `static-dir` | serving | *(startup-only)* |  |  |  | ✓ |
| k | `strict` | device | `set strict` |  |  | ✓ live |  |
| k | `time` | device | `set time` |  |  | ✓ live |  |
| k | `time-scale` | device | `set time-scale` |  |  | ✓ live |  |
| k | `timeout` | device | `set timeout` | ✓ live | ✓ live |  |  |
| k | `timezone` | device | `set timezone` |  |  | ✓ live |  |
| k | `unit` | device | *(startup-only)* | ✓ |  | ✓ |  |
| k | `upstream` | device | *(startup-only)* | ✓ | ✓ |  |  |
| k | `upstream` | serving | *(startup-only)* |  |  |  | ✓ |
| k | `write-acl` | device | `set write-acl` | ✓ live |  |  |  |
| k | `write-registers` | device | `set write-registers` | ✓ live |  |  |  |

Legend: `k` = a knob — the flag/env/config-file rows; `c` = control-only — a setting that lives on the control wire alone (the fake's pins and machines — no flag, no env, no config-file row); ✓ = the tool has the knob (**bold** = all four do); the `live` column is the control command itself — `set <name>` over the control plane, the wire name the registry gives the knob (it can differ from the flag: the cache's `cache-ttl` sets `ttl`); *(startup-only)* = no live form, a restart applies the knob; a cell's `live` mark says the tool takes the knob live (a cell without one = that tool applies the knob at startup only); `secret` = a token — never rendered inline by `show config` (the `-file` form is). The knob descriptions stay in the registries — `--help`, the man pages, `show knobs` and `help config` render them per tool.
