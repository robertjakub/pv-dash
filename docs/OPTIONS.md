# The knobs of the family (OPTIONS.md)

One alphabetical table of every knob and every show command of the
four daemons — the kind,
the name, the group it renders under, and the control command that
changes it (or answers with the report) on a running daemon — with a mark per
tool. **Generated** from the per-tool `lib/options.json` registries (the
one-knob-one-source rows) by `scripts/gen_options.py` — edit the
registries and re-run `python3 scripts/gen_options.py`, never this file.
The resolution order on every tool is flag > env > config script >
default; the bare `$NAME` env forms are the knob's upper-snake name.
Every bin also carries the CLI-only `--config`/`--dry-run`/`--man`
(plus `--version`/`--help`) — flags, not knobs, so they have no rows
here. The ctl/cli clients speak the control plane only
(`--control-port`, the token file/env pair) and are not compared.

Common to **all four** tools (23): `audit-files`, `audit-log`, `audit-max-mb`, `auth`, `client-timeout`, `control`, `control-ops-token`, `control-ops-verbs`, `control-port`, `control-socket-group`, `control-token`, `control-trust-uids`, `control/ops`, `dump`, `dump-key`, `dump-path`, `log-level`, `max-clients`, `max-conn-per-ip`, `metrics`, `metrics-acl`, `no-audit-log`, `restore-on-start`. The control-plane block is
shared nearly verbatim; the audit, limits and metrics blocks follow the
family shape with per-tool defaults. The show commands `config`, `connections`, `knobs`, `metrics-acl-table`, `version` ride
on all four too (the per-tool extras carry their own rows below).

| kind | name | group | live | cache | scraper | inverter | dashboard |
|---|---|---|---|---|---|---|---|
| c | `acl` |  | *(startup-only)* | ✓ |  |  |  |
| k | `allow-write` |  | `set write allow` | ✓ live |  | ✓ live |  |
| c | `audit` |  | *(startup-only)* | ✓ | ✓ |  |  |
| k | `audit-daily` |  | `set audit rotate daily` | ✓ live |  | ✓ |  |
| k | `audit-files` |  | `set audit rotate files` | **✓** live | **✓** live | **✓** | **✓** |
| k | `audit-log` |  | `set audit log-file` | **✓** live | **✓** live | **✓** | **✓** |
| k | `audit-max-mb` |  | `set audit rotate max-size` | **✓** live | **✓** live | **✓** | **✓** |
| c | `audit/rotate` |  | *(startup-only)* | ✓ | ✓ |  |  |
| k | `auth` |  | `set modbus auth` | **✓** live | **✓** live | **✓** live | **✓** |
| k | `auth-key` |  | `startup-only — pass it by flag/env/config (set/unset refuse)` | ✓ live+secret | ✓ live+secret | ✓ live+secret |  |
| k | `auth-token` |  | `startup-only — pass it by flag/env/config (set/unset refuse)` |  | ✓ live+secret |  | ✓ live+secret |
| k | `auth-upstream` |  | `set modbus auth-upstream` | ✓ live |  |  |  |
| k | `auth-upstream-key` |  | `startup-only — pass it by flag/env/config (set/unset refuse)` | ✓ live+secret |  |  |  |
| c | `batt` |  | `set batt` |  |  | ✓ live |  |
| k | `battery-kwh` |  | `set battery-kwh` |  |  | ✓ live |  |
| c | `battery-state` |  | `set battery-state` |  |  | ✓ live |  |
| k | `bind` |  | *(startup-only)* |  |  |  | ✓ |
| s | `cache` |  | `show cache` | ✓ |  |  |  |
| s | `cache-all` |  | `show cache-all` | ✓ hidden |  |  |  |
| k | `cache-ttl` |  | `set cache ttl` | ✓ live |  |  |  |
| c | `caps` |  | *(startup-only)* |  | ✓ |  |  |
| k | `chaos` |  | `set chaos` |  |  | ✓ live |  |
| k | `client-timeout` |  | `set client-timeout`, `set limits client-timeout`, `set metrics limits timeout` | **✓** live | **✓** live | **✓** live | **✓** live |
| c | `cloud` |  | `set cloud` |  |  | ✓ live |  |
| s | `config` |  | `show config` | **✓** | **✓** | **✓** hidden | **✓** hidden |
| k | `config-js` |  | *(startup-only)* |  |  |  | ✓ |
| k | `connect-acl` |  | `set acl connect`, `set connect-acl` | ✓ live |  | ✓ live |  |
| s | `connect-acl-table` |  | `show connect-acl-table` | ✓ |  |  |  |
| s | `connections` |  | `show connections` | **✓** | **✓** | **✓** | **✓** |
| c | `control` |  | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `control-log-replies` |  | *(startup-only)* |  |  | ✓ |  |
| k | `control-ops-token` |  | `startup-only — pass it by flag/env/config (set/unset refuse)` | **✓** live+secret | **✓** live+secret | **✓** live+secret | **✓** live+secret |
| k | `control-ops-verbs` |  | `set control ops verbs` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `control-port` |  | `set control port` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `control-socket-group` |  | `set control socket-group` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `control-token` |  | `startup-only — pass it by flag/env/config (set/unset refuse)` | **✓** live+secret | **✓** live+secret | **✓** live+secret | **✓** live+secret |
| k | `control-trust-uids` |  | `set control trust-uids` | **✓** live | **✓** live | **✓** live | **✓** live |
| c | `control/ops` |  | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| c | `dump` |  | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `dump-interval` |  | `set dump-interval` | ✓ live |  |  |  |
| k | `dump-key` |  | `startup-only — pass it by flag/env/config (set/unset refuse)` | **✓** live+secret | **✓** live+secret | **✓** live+secret | **✓** live+secret |
| k | `dump-path` |  | `set dump path` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `dump-with-cache` |  | `set dump with-cache` | ✓ live |  |  |  |
| c | `grid` |  | `set grid` |  |  | ✓ live |  |
| k | `grid-frequency` |  | `set grid-frequency` |  |  | ✓ live |  |
| c | `grid-outage` |  | `set grid-outage` |  |  | ✓ live |  |
| k | `grid-positive-import` |  | `set modbus grid-positive-import` |  | ✓ live |  |  |
| k | `grid-voltage` |  | `set grid-voltage` |  |  | ✓ live |  |
| k | `host` |  | *(startup-only)* |  |  | ✓ |  |
| s | `inputs` |  | `show inputs` |  | ✓ |  |  |
| s | `inputs-metrics` |  | `show inputs-metrics` |  | ✓ |  |  |
| k | `interval` |  | `set metrics interval`, `set modbus interval` | ✓ live | ✓ live |  |  |
| s | `knobs` |  | `show knobs` | **✓** | **✓** | **✓** hidden | **✓** hidden |
| c | `limits` |  | *(startup-only)* | ✓ |  |  |  |
| k | `listen` |  | `set metrics listen, restart`, `set system listen, restart` | ✓ live | ✓ live |  |  |
| c | `load` |  | `set load` |  |  | ✓ live |  |
| k | `local-time` |  | `set local-time` | ✓ live | ✓ live |  | ✓ |
| k | `log-access` |  | `set log-access`, `set system log-access` | ✓ live | ✓ live |  | ✓ live |
| k | `log-level` |  | `set log-level` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `log-queries` |  | `set log-queries` |  |  |  | ✓ live |
| k | `max-clients` |  | `set limits max-clients`, `set max-clients`, `set metrics limits max-clients` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `max-conn-per-ip` |  | `set limits max-conn-per-ip`, `set max-conn-per-ip`, `set metrics limits max-conn-per-ip` | **✓** live | **✓** live | **✓** live | **✓** live |
| k | `max-grid-kw` |  | `set caps max-grid` |  | ✓ live |  |  |
| k | `max-kwp` |  | `set caps max-pv`, `set max-kwp` |  | ✓ live | ✓ live |  |
| k | `merge-gap` |  | `set modbus merge-gap` | ✓ live |  |  |  |
| k | `metric-prefix` |  | `set metrics prefix` |  | ✓ live |  |  |
| c | `metrics` |  | *(startup-only)* | **✓** | **✓** | **✓** | **✓** |
| k | `metrics-acl` |  | `set metrics acl` | **✓** live | **✓** live | **✓** live | **✓** live |
| s | `metrics-acl-table` |  | `show metrics-acl-table` | **✓** | **✓** | **✓** | **✓** |
| k | `metrics-client-timeout` |  | `set metrics limits timeout` | ✓ live |  | ✓ | ✓ |
| k | `metrics-listen` |  | `set metrics listen, restart` | ✓ live |  | ✓ | ✓ |
| k | `metrics-max-clients` |  | `set metrics limits max-clients` | ✓ live |  | ✓ | ✓ |
| k | `metrics-max-conn-per-ip` |  | `set metrics limits max-conn-per-ip` | ✓ live |  | ✓ | ✓ |
| k | `metrics-server` |  | `set metrics enable` | ✓ live |  | ✓ live | ✓ live |
| k | `metrics-spec` |  | `set metrics filter` |  | ✓ live |  |  |
| k | `metrics-token` |  | `startup-only — pass it by flag/env/config (set/unset refuse)` | ✓ live+secret |  | ✓ live+secret | ✓ live+secret |
| c | `metrics/auth` |  | *(startup-only)* |  | ✓ |  |  |
| c | `metrics/limits` |  | *(startup-only)* | ✓ | ✓ |  |  |
| c | `modbus` |  | *(startup-only)* | ✓ | ✓ | ✓ |  |
| k | `modbus-offset` |  | `set modbus offset` |  | ✓ live |  |  |
| k | `modbus-unit` |  | `set modbus unit` |  | ✓ live |  |  |
| c | `mppt` |  | `set mppt` |  |  | ✓ live |  |
| k | `no-audit-log` |  | `set audit disable` | **✓** live | **✓** live | **✓** | **✓** |
| k | `port` |  | *(startup-only)* |  |  | ✓ | ✓ |
| k | `profile` |  | `set modbus profile`, `set profile` | ✓ live | ✓ live | ✓ live |  |
| k | `prom-prefix` |  | *(startup-only)* |  |  |  | ✓ |
| c | `pv` |  | `set pv` |  |  | ✓ live |  |
| k | `read-delay` |  | `set modbus read-delay` | ✓ live |  |  |  |
| s | `registers` |  | `show registers` |  |  | ✓ |  |
| k | `requests-audit` |  | `set audit requests` | ✓ live |  |  |  |
| k | `restore-on-start` |  | `set dump restore-on-start, restart` | **✓** live | **✓** live | **✓** live | **✓** live |
| c | `scenario` |  | `set scenario` |  |  | ✓ live |  |
| k | `seed` |  | `set seed` |  |  | ✓ live |  |
| k | `selection` |  | `set modbus selection` | ✓ live |  |  |  |
| c | `soc` |  | `set soc` |  |  | ✓ live |  |
| k | `static` |  | `set static` |  |  | ✓ live |  |
| k | `static-dir` |  | *(startup-only)* |  |  |  | ✓ |
| k | `strict` |  | `set strict` |  |  | ✓ live |  |
| c | `system` |  | *(startup-only)* | ✓ |  |  |  |
| k | `time` |  | `set time` |  |  | ✓ live |  |
| k | `time-scale` |  | `set time-scale` |  |  | ✓ live |  |
| k | `timeout` |  | `set modbus timeout` | ✓ live | ✓ live |  |  |
| k | `timezone` |  | `set timezone` |  |  | ✓ live |  |
| k | `unit` |  | `set modbus unit` | ✓ live |  | ✓ |  |
| s | `uplink` |  | `show uplink` | ✓ |  |  |  |
| k | `upstream` |  | `set modbus upstream` | ✓ live | ✓ live |  | ✓ |
| s | `version` |  | `show version` | **✓** | **✓** | **✓** | **✓** |
| c | `write` |  | *(startup-only)* | ✓ |  | ✓ |  |
| k | `write-acl` |  | `set acl write` | ✓ live |  |  |  |
| s | `write-acl-table` |  | `show write-acl-table` | ✓ |  |  |  |
| k | `write-registers` |  | `set write registers` | ✓ live |  |  |  |
| s | `write-registers-profile` |  | `show write-registers-profile` | ✓ |  |  |  |

Legend: `k` = a knob — the flag/env/config-file rows; `c` = control-only — a setting that lives on the control wire alone (the fake's pins and machines — no flag, no env, no config-file row); `s` = a show command — a report the wire answers with (`show <name>`; not a knob, nothing to set, the registry's `show` section); ✓ = the tool has the row (**bold** = all four do); the `live` column is the control command itself — `set <name>` over the control plane, the wire name the registry gives the knob (it can differ from the flag: the cache's `cache-ttl` sets `ttl`) — a show row spells `show <name>`; *(startup-only)* = no live form, a restart applies the knob; a trailing `, restart` = the knob is startup-only too — the set records the value (the wire answers the restart note), the restart applies it; every secret is restart-marked and renders `startup-only — pass it by flag/env/config` — the wire refuses set/unset on it outright; a cell's `live` mark says the tool takes the knob live (a cell without one = that tool applies the knob at startup only); `group` = the row's display bucket — the tool's surfaces file the knob under it (blank = ungrouped, rendered bare); `hidden` = the command stays out of the wire's listings (it still answers); `secret` = a token — `show config` and the dumps render the knob as `*** SECRET REMOVED ***` (the value never does; the `-file` form renders the same placeholder when the row is set). The knob descriptions stay in the registries — `--help`, the man pages, `show knobs` and `help config` render them per tool.
