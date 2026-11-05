# TODO (dashboard — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[dashboard]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)
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
