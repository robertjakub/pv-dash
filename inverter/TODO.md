# TODO

## Open

- **the priced grid machine** — a tariff-aware import/export model on top
  of the `grid` setpoint (a price curve → the battery greedy/eco
  strategies).
- **the user-defined scenarios** — scene files (the time + the pins + the
  machines) loadable with `set scenario <file>`; the audit trail of a
  manual session could *record* one.
- **the fake's own metrics** — DONE (`--metrics-port`, the /metrics with
  the bearer auth like the scraper's; the frequency-based derate and the
  SoH gauges are still to come).
- **the multi-unit serve** — one process serving two Modbus units (the
  inverter + the meter as separate unit ids) for the gateway-style setups.
- **the battery ageing** — the SoH drift over the simulated days (the
  capacity shrinks a %/week of the simulated time).
- **the grid-frequency machine** — DONE as the machine + the base setting
  (`--grid-frequency`, the ±0.2 Hz wander); the frequency-based derate is
  still open.
- **`inspect` command** — DONE (`inspect` = the pretty dump of everything).
- **the CI** — GitHub Actions: the six suites + `nix flake check` on the
  push; the release workflow on the tag.

## Done (the highlights; the git history has the details)

The control surface: the JSON-lines transport, the TCP token auth, the
grid setpoint, the MPPT strings (the east/west), the grid-voltage machine,
the UTC clock, the per-phase loads, `set register` overlay writes, the
status report, the registers table with the live values, the INV/CLI/CTL
audit trail with the rotation, the battery realism (the efficiency, the
self-discharge, the 80 % discharge cap, the temperature derate), the
Docker + compose setup, the bin/ lib/ split, the fuzz suite.
