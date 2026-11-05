# TODO (scrape — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[scrape]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

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
