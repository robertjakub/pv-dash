# TODO (dashboard — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[dashboard]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The token-file env honored: `DASHBOARD_CONTROL_TOKEN_FILE` does what the
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
