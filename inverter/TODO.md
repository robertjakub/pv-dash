# TODO

## Open

- **the priced grid machine** — a tariff-aware import/export model on top
  of the `grid` setpoint (a price curve → the battery greedy/eco
  strategies).
- **the user-defined scenarios** — scene files (the time + the pins + the
  machines) loadable with `set scenario <file>`; the audit trail of a
  manual session could *record* one.
- **the dongle latency profile** — a persistent slow-reply mode (the
  laggy-modem character: every response delayed, not dropped) to exercise
  read-delay and poll pacing against a realistic SDongle — the chaos
  `stall` is a one-shot, a real dongle is a lifestyle.
- **the machine gauges on /metrics** — the state machines' internals as
  Prometheus gauges (cloud factor, outage state, per-string power, the
  battery's decision): dashboards and the scrape fuzzing could watch the
  machines, not just the registers they feed.
- **the fake's client limits** — mirror the cache's `--max-clients` /
  `--client-timeout` on the Modbus surface, and cap a declared read count
  by the remaining frame (a truncated 0xFFFF-count frame makes the fake
  assemble an oversized reply today — docs/AUDIT.md F11).
- **the token-file env honored** — the clients' help promises
  `FAKE_CONTROL_TOKEN_FILE`, the code never reads it: honor it (like
  `FAKE_CONTROL_TOKEN`) or drop the claim from the help. Same check for
  `FAKE_METRICS_TOKEN_FILE`.
- **the frequency-based derate** — the machine already wanders ±0.2 Hz
  around `--grid-frequency`; beyond a deviation bound the output power
  should derate (exposed on /metrics too).
- **the battery ageing** — the SoH drift over the simulated days (the
  capacity shrinks a %/week of the simulated time) + the `battery_soh`
  gauge on /metrics.
- **the multi-unit serve** — one process serving two Modbus units (the
  inverter + the meter as separate unit ids) for the gateway-style setups.
- **the fault/alarm registers** — device health words driven by the
  machines (an outage raises a fault, the derate a warning, the battery
  cap a SoC notice): the cache/scrape export them and the dashboard can
  banner a fault, not just a blackout.
- **the forecast curve** — the PV/cloud machines follow a day-ahead
  forecast file, so a demo runs repeatable weather instead of the RNG.
- **the CI** — GitHub Actions: the six suites + `nix flake check` on the
  push; the release workflow on the tag. (Family-wide, see the root
  [TODO](../docs/TODO.md).)

## Done (the highlights; the git history has the details)

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
