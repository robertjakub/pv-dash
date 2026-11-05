# TODO (inverter — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[inverter]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The audit finding F11 closed (rev. 3): the cache's client knobs mirrored
(`--max-clients` / `--client-timeout`, live-settable, `show connections`
to watch them), the per-IP connection cap (`--max-conn-per-ip`), the
read-count gate (exception 03 past the 125-register cap — a truncated
0xFFFF-count frame no longer makes the fake assemble an oversized reply)
and the trusted-LAN / not-security-first posture documented (the README's
Security section, the man page's SECURITY block). The metrics endpoint
grew the caps too (`--metrics-max-clients` / `--metrics-client-timeout` /
`--metrics-max-conn-per-ip`, the 503 past the cap) — F13's family round.

The FC06/FC16 write path: the fake accepts real write requests (the echo
+ the overlay the scrapers see, audited with the writer), which the
cache's gated writes exercise end-to-end.

The control surface: the JSON-lines transport, the TCP token auth, the
grid setpoint, the MPPT strings (the east/west), the grid-voltage machine,
the UTC clock, the per-phase loads, `set register` overlay writes, the
status report, the registers table with the live values, the INV/CLI/CTL
audit trail with the rotation, the battery realism (the efficiency, the
self-discharge, the 80 % discharge cap, the temperature derate), the
Docker + compose setup, the bin/ lib/ split, the fuzz suite. Also the own
metrics endpoint (`--metrics-server` + `--metrics-listen`, the /metrics
with the bearer auth like the scraper's), the grid-frequency machine
(`--grid-frequency`, the
±0.2 Hz wander), the `inspect` dump, the time-lapse factor
(`--time-scale` / `set time-scale` — the simulated clock at N× real
speed, so a demo watches a full day in minutes) and the grid-outage
machine (`set grid-outage on|off|outage` — random blackouts: the phases
collapse, the inverter stands by, the meter goes dark). The statics redo
(the grouped lib/static.json) and the `--control-token-file` /
`--metrics-token-file` options. The reports: `show status` and now
`show settings` as multi-line key=value tables; the fake inverter serves
the same register map over FC3 and FC4 (the cache's FC4 path has a
device-side counterpart). The console: the TAB/? listings split into
[settings]/[values]/[system] with the descriptions aligned, `set`/`unset`
confirm `% ok`, `show <setting>` prints the bare value — and the daemon
announces its exit (`bye daemon-exit`) so the console closes instead of
reconnecting. The shared core: the audit trail, the token loader and the
wire helpers moved to `common/` (one implementation for the whole family).
