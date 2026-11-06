# The knobs of the family (options.md)

One alphabetical table of every knob of the four daemons — the kind,
the name, the group it renders under, and the control command that
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

| kind | name | group | live | cache | scraper | inverter | dashboard |
|---|---|---|---|---|---|---|---|
| c | `acl` |  | *(startup-only)* | ✓ |  |  |  |
| k | `allow-write` |  | `set write allow` | ✓ live |  |  |  |
| c | `audit` |  | *(startup-only)* | ✓ |  |  |  |
| k | `audit-daily` |  | `set audit rotate daily` | ✓ live |  | ✓ |  |
| k | `audit-files` |  | `set audit rotate files` | **✓** live | **✓** | **✓** | **✓** |
| k | `audit-log` |  | `set audit log-file` | **✓** live | **✓** | **✓** | **✓** |
| k | `audit-max-mb` |  | `set audit rotate max-size` | **✓** live | **✓** | **✓** | **✓** |
| k | `auth-token` |  | *(startup-only)* |  | ✓ secret |  |  |
| k | `auth-token-file` |  | *(startup-only)* |  | ✓ secret |  |  |
| c | `batt` |  | `set batt` |  |  | ✓ live |  |
| k | `battery` |  | `set battery` |  | ✓ | ✓ live | ✓ live |
| k | `battery-kwh` |  | `set battery-kwh` |  |  | ✓ live |  |
| c | `battery-state` |  | `set battery-state` |  |  | ✓ live |  |
| k | `bind` |  | *(startup-only)* |  |  |  | ✓ |
| k | `cache-ttl` |  | `set cache ttl` | ✓ live |  |  |  |
| k | `chaos` |  | `set chaos` |  |  | ✓ live |  |
| k | `client-timeout` |  | `set client-timeout`, `set limits client-timeout` | **✓** live | **✓** live | **✓** live | **✓** live |
| c | `cloud` |  | `set cloud` |  |  | ✓ live |  |
| k | `config-js` |  | *(startup-only)* |  |  |  | ✓ |
| k | `connect-acl` |  | `set acl connect`, `set connect-acl` | ✓ live |  | ✓ live |  |
| c | `control` |  | *(startup-only)* | ✓ |  |  |  |
| k | `control-log-replies` |  | *(startup-only)* |  |  | ✓ |  |
| k | `control-ops-token` |  | `set control ops token` | **✓** live+secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-ops-token-file` |  | `set control ops token-file` | **✓** live+secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-ops-verbs` |  | `set control ops-verbs` | **✓** live | **✓** | **✓** | **✓** |
| k | `control-port` |  | `set control port` | **✓** live | **✓** | **✓** | **✓** |
| k | `control-socket-group` |  | `set control socket-group` | ✓ live |  | ✓ |  |
| k | `control-token` |  | `set control token` | **✓** live+secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-token-file` |  | `set control token-file` | **✓** live+secret | **✓** secret | **✓** secret | **✓** secret |
| k | `control-trust-uids` |  | `set control trust-uids` | **✓** live | **✓** | **✓** | **✓** |
| c | `dump` |  | *(startup-only)* | ✓ |  |  |  |
| k | `dump-interval` |  | `set dump-interval` | ✓ live |  |  |  |
| k | `dump-path` |  | `set dump path` | ✓ live |  |  |  |
| k | `dump-with-cache` |  | `set dump with-cache` | ✓ live |  |  |  |
| c | `grid` |  | `set grid` |  |  | ✓ live |  |
| k | `grid-frequency` |  | `set grid-frequency` |  |  | ✓ live |  |
| c | `grid-outage` |  | `set grid-outage` |  |  | ✓ live |  |
| k | `grid-positive-import` |  | *(startup-only)* |  | ✓ |  |  |
| k | `grid-voltage` |  | `set grid-voltage` |  |  | ✓ live |  |
| k | `host` |  | *(startup-only)* |  |  | ✓ |  |
| k | `interval` |  | `set interval`, `set modbus interval` | ✓ live | ✓ live |  |  |
| c | `limits` |  | *(startup-only)* | ✓ | ✓ |  |  |
| k | `listen` |  | *(startup-only)* | ✓ | ✓ |  |  |
| c | `load` |  | `set load` |  |  | ✓ live |  |
| k | `local-time` |  | `set local-time` | ✓ live | ✓ |  | ✓ |
| k | `log-access` |  | `set log-access` | ✓ | ✓ live |  | ✓ live |
| k | `log-level` |  | `set log-level` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `log-queries` |  | `set log-queries` |  |  |  | ✓ live |
| k | `max-clients` | `limits` | `set limits max-clients`, `set max-clients` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `max-conn-per-ip` | `limits` | `set limits max-conn-per-ip`, `set max-conn-per-ip` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `max-grid-kw` |  | *(startup-only)* |  | ✓ |  |  |
| k | `max-kwp` |  | `set max-kwp` |  | ✓ | ✓ live |  |
| k | `merge-gap` |  | `set modbus merge-gap` | ✓ live |  |  |  |
| k | `metric-prefix` |  | *(startup-only)* |  | ✓ |  |  |
| k | `metrics-client-timeout` |  | `set metrics limits timeout` | ✓ live |  | ✓ | ✓ |
| k | `metrics-listen` |  | `set metrics listen` | ✓ live |  | ✓ | ✓ |
| k | `metrics-max-clients` |  | `set metrics limits max-clients` | ✓ live |  | ✓ | ✓ |
| k | `metrics-max-conn-per-ip` |  | `set metrics limits max-conn-per-ip` | ✓ live |  | ✓ | ✓ |
| k | `metrics-server` |  | `set metrics-server`, `set metrics enable` | ✓ live |  | ✓ live | ✓ live |
| k | `metrics-spec` |  | *(startup-only)* |  | ✓ |  |  |
| k | `metrics-token` |  | `set metrics token` | ✓ live+secret |  | ✓ secret | ✓ secret |
| k | `metrics-token-file` |  | `set metrics token-file` | ✓ live+secret |  | ✓ secret | ✓ secret |
| c | `modbus` |  | *(startup-only)* | ✓ | ✓ |  |  |
| k | `modbus-offset` |  | `set modbus offset` |  | ✓ live |  |  |
| k | `modbus-unit` | `modbus` | `set modbus unit` |  | ✓ live |  |  |
| c | `mppt` |  | `set mppt` |  |  | ✓ live |  |
| k | `no-audit-log` |  | `set audit disable` | **✓** live | **✓** | **✓** | **✓** |
| k | `no-battery` |  | *(startup-only)* |  |  | ✓ |  |
| k | `port` |  | *(startup-only)* |  |  | ✓ | ✓ |
| k | `profile` |  | `set modbus profile`, `set profile` | ✓ live | ✓ live | ✓ live |  |
| k | `prom-prefix` |  | *(startup-only)* |  |  |  | ✓ |
| c | `pv` |  | `set pv` |  |  | ✓ live |  |
| k | `read-delay` |  | `set modbus read-delay` | ✓ live |  |  |  |
| k | `requests-audit` |  | `set audit requests` | ✓ live |  |  |  |
| k | `restore-on-start` |  | `set dump restore-on-start` | ✓ live |  |  |  |
| c | `scenario` |  | `set scenario` |  |  | ✓ live |  |
| k | `seed` |  | `set seed` |  |  | ✓ live |  |
| k | `selection` |  | `set modbus selection` | ✓ live |  |  |  |
| c | `soc` |  | `set soc` |  |  | ✓ live |  |
| k | `static` |  | `set static` |  |  | ✓ live |  |
| k | `static-dir` |  | *(startup-only)* |  |  |  | ✓ |
| k | `strict` |  | `set strict` |  |  | ✓ live |  |
| k | `time` |  | `set time` |  |  | ✓ live |  |
| k | `time-scale` |  | `set time-scale` |  |  | ✓ live |  |
| k | `timeout` |  | `set modbus timeout`, `set timeout` | ✓ live | ✓ live |  |  |
| k | `timezone` |  | `set timezone` |  |  | ✓ live |  |
| k | `unit` |  | `set modbus unit` | ✓ live |  | ✓ |  |
| k | `upstream` | `upstream` | `set modbus upstream` | ✓ live | ✓ live |  | ✓ |
| c | `write` |  | *(startup-only)* | ✓ |  |  |  |
| k | `write-acl` |  | `set acl write` | ✓ live |  |  |  |
| k | `write-registers` |  | `set write registers` | ✓ live |  |  |  |

Legend: `k` = a knob — the flag/env/config-file rows; `c` = control-only — a setting that lives on the control wire alone (the fake's pins and machines — no flag, no env, no config-file row); ✓ = the tool has the knob (**bold** = all four do); the `live` column is the control command itself — `set <name>` over the control plane, the wire name the registry gives the knob (it can differ from the flag: the cache's `cache-ttl` sets `ttl`); *(startup-only)* = no live form, a restart applies the knob; a cell's `live` mark says the tool takes the knob live (a cell without one = that tool applies the knob at startup only); `group` = the row's display bucket — the tool's surfaces file the knob under it (blank = ungrouped, rendered bare); `secret` = a token — never rendered inline by `show config` (the `-file` form is). The knob descriptions stay in the registries — `--help`, the man pages, `show knobs` and `help config` render them per tool.
