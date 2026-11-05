# TODO (scrape — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[scrape]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)
The rename + env-prefix wave: the bins carry the man-page names now
(`modbus-scraper.py`, `modbus-scraper-ctl.py`, `modbus-scraper-cli.py`),
and every env twin wears the tool's prefix (`SCR_*`), the control-port
answering to the one short `SCR_CTL` for the daemon and the clients
alike. The constants audit: `log_levels` joined `lib/static.json` and
every consumer reads the ladder from there.

The profile-is-the-register-map wave (breaking): the register knobs are
gone — `--pv-register`/`--grid-register`/`--battery-register`/
`--battery-soc-register`/`--scale`/`--grid-scale` (flags, envs, config
keys, NixOS options) existed because the spec predated the device
profile; the profile is the register map's single source now (addresses,
types, gains, function codes — the per-entry `scale` is the decode
divisor, validated finite > 0 at load). The live control surface gained
`set profile <file-or-name>` (`default` = the bundled sun2000 profile,
`unset` restores): the new map loads, the metric sources rebuild, and a
profile without the registers the power math needs rolls back with a
clean error (the regtest covers the swap, the rollback and the missing
file).

The knob-dictionary wave: `show knobs` (the `help knobs` alias too) prints
the dictionary of all knobs — every registry knob under its section with
its flag, its env twin(s), its home section, the command that changes it
live (or the restart note for the startup-only ones) and the secret marker
on the tokens (`common/options.py` `knob_dictionary()`; the values stay in
`show config`, the command mapping in `help config`). The scraper_ctl/cli
TAB completion and `show?` word-help offer the new `show` argument.

The config-format + metrics waves: the ini is gone (the config file is
a set-grammar script, `show config` regenerates it, the bundled
scraper.conf is the sample); the metrics spec is sectioned ([profile] /
[compute] / [scraper]) with `--metric-prefix` (default huawei) on the
profile- and compute-fed names and the bundled `scraper_*` gauges — the
cache-diag block included (`huawei_cache_*` -> `scraper_cache_*`) — plus
the poll-latency gauges (`scraper_poll_duration_seconds`, mean/max) and
the per-phase metrics. The RBAC verb set is live too (`--control-ops-verbs`).
The scraper section of the spec moved to `lib/metrics.json` (next to the
loader, installed with it) and the loader merges it in memory over the
configured spec — a custom `--metrics-spec` carries the profile/compute
entries alone and overrides the built-in `scraper_*` ones by name.

The read-only control role: a second token
(`--control-ops-token`/`--control-ops-token-file`, ini
`control_ops_token`, env `SCR_CONTROL_OPS_TOKEN(_FILE)`) beside the
admin one, and its sessions run the show/clear verbs only — the reports
yes, `set`/`unset`/`poll now`/`request reload`/`restart`/`shutdown` no
(`err forbidden: … needs the admin token`): the ops shift versus the
admin key, both audited (`role=ops`/`role=admin` in the SCR COMMAND
entries, the denials included), each session's frames mac'd with the key
it authenticated with. The NixOS module grew
`controlOpsToken`/`controlOpsTokenFile`.

The token-file env honored: `SCR_CONTROL_TOKEN_FILE` does what the
clients' help always promised — the env form of `--control-token-file`
on `scraper_ctl`/`scraper_cli` (the daemon's config resolved it from the
start; flag over env, the file over the plain token, both together the
mutual-exclusion error).

The control surface (the last family tool without one): the JSON-lines
control server on the cache's pattern (the unix socket by default, the
token'd TCP with the F5 refusal, the peer-cred shortcut, the idle-timeout +
line caps), **scraper_ctl**/**scraper_cli** (the family clients), the live
settings registry (`interval`, `timeout`, `max-clients`,
`client-timeout`, `max-conn-per-ip`, `log-access`, `log-level`), `poll
now`, `request reload` (the SIGHUP path), the Modbus session `restart`,
`show status`/`connections`/`settings`, `inspect`, the SCR audit trail
(the commands carry their wire macs) — and the **signed wire**: with a
control token configured every command and reply carries the full sha256
HMAC of its payload keyed by the token (`common/wiresec.py`), mandatory
over TCP, verified end-to-end by the token-holding clients.


The audit finding F13 closed (rev. 3): the non-loopback `/metrics` listen
refuses to start without a token, and the connection limits ship —
`--max-clients` (64, an immediate 503 past it), `--client-timeout`
(300 s idle keep-alives) and `--max-conn-per-ip` (per-peer IP, 0 = no
limit), all applied live on SIGHUP (the resource-limits block of the
regtest asserts the matrix).

The profile `fc` awareness: the scraper reads each spec-bound source with
the profile entry's function code (`fc: 4` = input registers, the default
3 = holding) — the wire layer packs and validates the code, and the
regtest proves both directions (an `fc: 4` source works against the
dual-code fake and fails against the FC3-only evil server). A shipped
profile with real input-register data still waits for a hardware capture
(the fake serves both codes, so nothing honest to ship there yet).

The Prometheus exporter: the profile-driven selection with the metrics
registry (the unit scaling, the string/phase splits), the static JSON
constants (lib/static.json), the bearer-token auth on /metrics with the
`--auth-token-file` option, the AUDIT trail with the thread-safe
rotation, the reconnect cycle, the scrape fuzz suite, the NixOS module,
the bin/ lib/ split (matching the cache and the inverter: the
`modbus-scraper` entry in bin/, the modules in lib/, the sample ini and
metrics.json at the subproject root) with lib/version — and the shared
core (the audit trail, the token loader, the wire helpers, the profile
resolution) moved to `common/`.
