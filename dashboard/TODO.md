# TODO (dashboard — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[dashboard]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The secret-placeholder wave: an overridden secret rides the state dump /
the reload state file as `*** SECRET REMOVED ***` (the value never lands
in a file — the restore skips the placeholder and names it),
`show config` marks the configured secret rows the same way (the entry
passes the control server the secret rows' configured-ness), and the
placeholder refuses to parse as a value.

The state-machinery wave: `dump_settings`/`apply_dump_settings` land on
the control server — the **state dump** (`dump/path`,
`dump/restore-on-start` lives + the `--dump-path`/`--restore-on-start`
flags/env/NixOS options; `request dump`/`request restore` write and
re-apply the live overrides as one 0600 integrity-hashed JSON,
common/dump.py; the graceful shutdown dumps too), the **whole-daemon
`reload`** (the overrides save to `<config>.reload`, the process re-execs,
the fresh daemon re-applies them once and consumes the file — the ops
role may not reload), and the **secret lives**: `control/token`(-file),
`control/ops/token`(-file) and `metrics/token`(-file) rotate live (the
sessions re-auth; the F6 rule stands — the endpoint's token is mandatory
while it serves), the secret defaults placeholders are gone (unset
refuses) and **`show <secret>` refuses** — the value renders nowhere.

The show-settings retirement: `show settings` is gone — the per-setting
`show <setting>` and `show status`'s `overridden=` row carry the same
truth, the command answers `err unknown setting` (the registry row, the
daemon help lines, the man pages, the README and the suites follow).

The registry-folding wave: `lib/settings.py` is gone — the control
grammar's vocabulary rides the `lib/options.json` rows and `lib/options.py`
derives `SETTINGS`/`describe_setting` from them (the wire, the completions
and the word help unchanged).

The env-prefix retirement wave: the env twins are the bare upper-snake
names — the docker-documented generic set (`PORT`, `BIND`, `PROM_URL`,
`CONFIG_JS`, ...) IS the set now, no `DSH_` duplicates beside it; the
registry, the resolver, the ctl/cli clients, the docs and the man pages
follow. The shipped `config.js` `batteryFlag` selector asks for
`scraper_battery` (the metrics wave's rename, propagated — the retired
`huawei_battery` gauge no longer answers).

The declarative-registry wave: the knob rows (the name, the flag, the env
twin, the section, the live/secret markers and the descriptions) moved to
`lib/options.json` — `lib/options.py` loads them onto the common `Option`
rows and keeps the Python-side wiring (the control-grammar verb list, the
audit defaults and the log-level choices read from `static.json`) — and
`--help`/the man pages render from the registry now
(`common/options.py` `build_parser()`): the knob description lives exactly
once. The flags in `--help` order by the registry's sections; the texts,
types and defaults are unchanged; `scripts/check_options.py` gates as
before and the package ships the JSON next to the loader.

The rename + env-prefix wave: the bins carry the man-page names now
(`dashboard.py`, `dashboard-ctl.py`, `dashboard-cli.py`), and every env
twin wears the tool's prefix (`DSH_*`) — the generic docker envs
(`PORT`, `BIND`, `PROM_URL`, `PROM_PREFIX`, `STATIC_DIR`, `CONFIG_JS`,
`BATTERY`) are retired for `DSH_PORT`/`DSH_BIND`/`DSH_PROM_URL`/
`DSH_PROM_PREFIX`/`DSH_STATIC_DIR`/`DSH_CONFIG_JS`/`DSH_BATTERY` (the
compose stack, the Dockerfile and the docker README follow), the
control-port answering to the one short `DSH_CTL` for the daemon and the
clients alike. The constants audit: `log_levels` joined
`lib/static.json` (the metrics-endpoint defaults joined the shipped
defaults too — no hardcoded `127.0.0.1:9452`/16/5 literals in the config
resolution anymore) and every consumer reads the ladder from there.

The knob-dictionary wave: `show knobs` (the `help knobs` alias too) prints
the dictionary of all knobs — every registry knob under its section with
its flag, its env twin(s), its home section, the command that changes it
live (or the restart note for the startup-only ones) and the secret marker
on the tokens (`common/options.py` `knob_dictionary()`; the values stay in
`show config`, the command mapping in `help config`). The dashboard_ctl/cli
TAB completion and `show?` word-help offer the new `show` argument.

The waves: the config-format (the ini is gone — server.conf speaks the
set grammar, `show config` regenerates it, the nix module renders it),
the RBAC verb set (`--control-ops-verbs`), and **the dashboard's own
/metrics endpoint** (`--metrics-server`, off by default, a token
mandatory when on: the uptime, the request counters by status, the
proxied-query total, the client gate) with the live `set metrics-server`
toggle. The per-phase chain closed: config.js grew the
phaseVoltages/phaseCurrents selectors and the page renders a per-phase
health strip with the voltage-unbalance percentage.

The read-only control role: a second token
(`--control-ops-token`/`--control-ops-token-file`, ini
`control_ops_token`, env `DSH_CONTROL_OPS_TOKEN(_FILE)`) beside the
admin one, and its sessions run the show/clear verbs only — the reports
yes, `set`/`unset`/`request reload`/`shutdown` no (`err forbidden: …
needs the admin token`): the ops shift versus the admin key, both audited
(`role=ops`/`role=admin` in the DSH COMMAND entries, the denials
included), each session's frames mac'd with the key it authenticated
with. The NixOS module grew `controlOpsToken`/`controlOpsTokenFile` (the
ExecStart flags, the LoadCredential mount).

The token-file env honored: `DSH_CONTROL_TOKEN_FILE` does what the
clients' help always promised — the env form of `--control-token-file`
on `dashboard_ctl`/`dashboard_cli` (the daemon's config resolved it from
the start; flag over env, the file over the plain token, both together
the mutual-exclusion error).

The control plane (the family set is complete): the JSON-lines control
server on the scraper's pattern (the unix socket by default, the token'd
TCP with the F5 refusal, the peer-cred shortcut, the signed wire), the
live settings (the caps, the log surface, the battery flag), `show
status/connections/settings/version`, `inspect`, `request reload` (the
SIGHUP path), `shutdown` — with `dashboard_ctl`/`dashboard_cli` (the
one-shot and console clients), the DSH audit trail, the man-page
generator + `--man`, and the HTTP surface's connection gate
(`--max-clients`/`--client-timeout`/`--max-conn-per-ip`, refusals 503).
The NixOS module grew the matching options and joined the hardening VM
check; the docker image ships the ctl/cli; `tests/dashboard-control-fuzz.py`
covers the wire.

The read-only dashboard: the Prometheus proxy with the prefix rewrite and
the query API, the generation/consumption/battery/grid panels, the static
JSON constants (lib/static.json), the bin/ lib/ split, the NixOS module,
the Docker compose service.
