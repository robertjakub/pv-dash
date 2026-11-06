# The knobs of the family (options.md)

One table comparing every knob of the four daemons — the name, the
function it files under and the control command that changes it on
a running daemon — with a mark per
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

| knob | function | live | cache | scraper | inverter | dashboard |
|---|---|---|---|---|---|---|
| `--allow-write` | device | `set allow-write` | ✓ live |  |  |  |
| `batt` (control-only) | device | `set batt` |  |  | ✓ live |  |
| `--battery` | device | `set battery` |  | ✓ | ✓ live |  |
| `--battery-kwh` | device | `set battery-kwh` |  |  | ✓ live |  |
| `battery-state` (control-only) | device | `set battery-state` |  |  | ✓ live |  |
| `--cache-ttl` | device | `set ttl` | ✓ live |  |  |  |
| `--chaos` | device | `set chaos` |  |  | ✓ live |  |
| `cloud` (control-only) | device | `set cloud` |  |  | ✓ live |  |
| `--connect-acl` | device | `set connect-acl` | ✓ live |  | ✓ live |  |
| `grid` (control-only) | device | `set grid` |  |  | ✓ live |  |
| `--grid-frequency` | device | `set grid-frequency` |  |  | ✓ live |  |
| `grid-outage` (control-only) | device | `set grid-outage` |  |  | ✓ live |  |
| `--grid-positive-import` | device | *(startup-only)* |  | ✓ |  |  |
| `--grid-voltage` | device | `set grid-voltage` |  |  | ✓ live |  |
| `--host` | device | *(startup-only)* |  |  | ✓ |  |
| `--interval` | device | `set interval` | ✓ live |  |  |  |
| `load` (control-only) | device | `set load` |  |  | ✓ live |  |
| `--max-grid-kw` | device | *(startup-only)* |  | ✓ |  |  |
| `--max-kwp` | device | `set max-kwp` |  | ✓ | ✓ live |  |
| `--merge-gap` | device | `set merge-gap` | ✓ live |  |  |  |
| `--metric-prefix` | device | *(startup-only)* |  | ✓ |  |  |
| `--metrics-spec` | device | *(startup-only)* |  | ✓ |  |  |
| `--modbus-offset` | device | *(startup-only)* |  | ✓ |  |  |
| `--modbus-unit` | device | *(startup-only)* |  | ✓ |  |  |
| `mppt` (control-only) | device | `set mppt` |  |  | ✓ live |  |
| `--no-battery` | device | *(startup-only)* |  |  | ✓ |  |
| `--port` | device | *(startup-only)* |  |  | ✓ |  |
| `--profile` | device | `set profile` | ✓ live | ✓ live | ✓ live |  |
| `pv` (control-only) | device | `set pv` |  |  | ✓ live |  |
| `--read-delay` | device | `set read-delay` | ✓ live |  |  |  |
| `scenario` (control-only) | device | `set scenario` |  |  | ✓ live |  |
| `--seed` | device | `set seed` |  |  | ✓ live |  |
| `--selection` | device | `set selection` | ✓ live |  |  |  |
| `soc` (control-only) | device | `set soc` |  |  | ✓ live |  |
| `--static` | device | `set static` |  |  | ✓ live |  |
| `--strict` | device | `set strict` |  |  | ✓ live |  |
| `--time` | device | `set time` |  |  | ✓ live |  |
| `--time-scale` | device | `set time-scale` |  |  | ✓ live |  |
| `--timeout` | device | `set timeout` | ✓ live | ✓ live |  |  |
| `--timezone` | device | `set timezone` |  |  | ✓ live |  |
| `--unit` | device | *(startup-only)* | ✓ |  | ✓ |  |
| `--upstream` | device | *(startup-only)* | ✓ | ✓ |  |  |
| `--write-acl` | device | `set write-acl` | ✓ live |  |  |  |
| `--write-registers` | device | `set write-registers` | ✓ live |  |  |  |
| `--battery` | serving | `set battery` |  |  |  | ✓ live |
| `--bind` | serving | *(startup-only)* |  |  |  | ✓ |
| `--config-js` | serving | *(startup-only)* |  |  |  | ✓ |
| `--listen` | serving | *(startup-only)* | ✓ | ✓ |  |  |
| `--local-time` | serving | *(startup-only)* | ✓ | ✓ |  |  |
| `--port` | serving | *(startup-only)* |  |  |  | ✓ |
| `--prom-prefix` | serving | *(startup-only)* |  |  |  | ✓ |
| `--static-dir` | serving | *(startup-only)* |  |  |  | ✓ |
| `--upstream` | serving | *(startup-only)* |  |  |  | ✓ |
| `--control-log-replies` | control plane | *(startup-only)* |  |  | ✓ |  |
| `--control-ops-token` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-ops-token-file` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-ops-verbs` | control plane | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| `--control-port` | control plane | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| `--control-socket-group` | control plane | *(startup-only)* | ✓ |  | ✓ |  |
| `--control-token` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-token-file` | control plane | *(startup-only)* | **✓** secret | **✓** secret | **✓** secret | **✓** secret |
| `--control-trust-uids` | control plane | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| `--auth-token` | own /metrics | *(startup-only)* |  | ✓ secret |  |  |
| `--auth-token-file` | own /metrics | *(startup-only)* |  | ✓ secret |  |  |
| `--metrics-client-timeout` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| `--metrics-listen` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| `--metrics-max-clients` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| `--metrics-max-conn-per-ip` | own /metrics | *(startup-only)* | ✓ |  | ✓ | ✓ |
| `--metrics-server` | own /metrics | `set metrics-server` | ✓ live |  | ✓ live | ✓ live |
| `--metrics-token` | own /metrics | *(startup-only)* | ✓ secret |  | ✓ secret | ✓ secret |
| `--metrics-token-file` | own /metrics | *(startup-only)* | ✓ secret |  | ✓ secret | ✓ secret |
| `--audit-daily` | audit trail | *(startup-only)* | ✓ |  | ✓ |  |
| `--audit-files` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| `--audit-log` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| `--audit-max-mb` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| `--no-audit-log` | audit trail | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| `--requests-audit` | audit trail | `set requests-audit` | ✓ live |  |  |  |
| `--client-timeout` | limits | `set client-timeout` | **✓** live | **✓** live | **✓** live | **✓** live |
| `--max-clients` | limits | `set max-clients` | **✓** live | **✓** live | **✓** live | **✓** live |
| `--max-conn-per-ip` | limits | `set max-conn-per-ip` | **✓** live | **✓** live | **✓** live | **✓** live |
| `--dump-interval` | persistence | `set dump-interval` | ✓ live |  |  |  |
| `--dump-path` | persistence | *(startup-only)* | ✓ |  |  |  |
| `--dump-with-cache` | persistence | *(startup-only)* | ✓ |  |  |  |
| `--restore-on-start` | persistence | *(startup-only)* | ✓ |  |  |  |
| `--interval` | logging | `set interval` |  | ✓ live |  |  |
| `--local-time` | logging | *(startup-only)* |  |  |  | ✓ |
| `--log-access` | logging | `set log-access` | ✓ | ✓ live |  | ✓ live |
| `--log-level` | logging | `set log-level` | **✓** live | **✓** live | **✓** live | **✓** live |
| `--log-queries` | logging | `set log-queries` |  |  |  | ✓ live |

Legend: ✓ = the tool has the knob (**bold** = all four do); the `live` column is the control command itself — `set <name>` over the control plane, the wire name the registry gives the knob (it can differ from the flag: the cache's `--cache-ttl` sets `ttl`); *(startup-only)* = no live form, a restart applies the knob; a cell's `live` mark says the tool takes the knob live (a cell without one = that tool applies the knob at startup only); `secret` = a token — never rendered inline by `show config` (the `-file` form is); *(control-only)* = a setting that lives on the control wire alone (the fake's pins and machines — no flag, no env, no config-file row). The knob descriptions stay in the registries — `--help`, the man pages, `show knobs` and `help config` render them per tool.
