# TODO

## Open

- **the auth story** — the server binds `0.0.0.0` by default with no
  authentication on page or proxy; the README documents the loopback/
  reverse-proxy paths, but a bearer check mirroring the scraper's (or at
  least a loud startup note) belongs in the server itself before anything
  leaves localhost.
- **the cache gauges** — once the cache has its own metrics endpoint (the
  cache TODO), chart the hit/miss ratio, the cache age and the poll health
  next to the generation panels.
- **the outage banner** — the inverter simulates grid outages and the
  meter goes dark; the dashboard could show a standing banner (and an
  annotation gap on the charts) instead of a silent zero flatline.
- **the battery SoH** — when the inverter grows the battery-ageing model,
  add the SoH gauge and let the capacity panels use the live value.
- **the range picker** — the time-range control beyond the default window
  (presets + a from/to picker) on top of the existing query plumbing.
- **the write console** — a guarded panel issuing single-register writes
  through the cache's allow-list (the write-through lands the value in the
  charts instantly): the ops poke, audited with the writer's identity.
- **the event feed** — the audit vocabulary (writes, refusals, outages,
  reloads) as a dashboard side panel, instead of the journalctl detour.
- **the per-phase panels** — once the scraper exports the per-phase
  voltages/currents (the fake already simulates the unbalanced home):
  three-phase health at a glance, the unbalance visible.
- **the forecast overlay** — when the fake grows the forecast curve and a
  real forecast source exists: the expected-PV curve behind the measured
  one, the underperformance visible without doing math.
- **the tariff / cost panels** — when the priced grid machine (inverter
  TODO) defines a price curve: import cost, export revenue, self-cost —
  the money view next to the energy view.
- **the German strings** — the i18n merge makes a third language cheap
  (`de: { ... }` in `i18n.js`, the switcher grows automatically).
- **the mobile pass** — the flow diagram and the header controls assume a
  desk-sized window; a small-screen layout (the chart full-width, the KPI
  row scrollable) makes the LAN page phone-friendly.
- **the Prometheus annotations** — outages, reloads and (with the write
  console) manual pokes rendered as chart annotations, once the event feed
  exists to carry them.

## Done (the highlights; the git history has the details)

The read-only dashboard: the Prometheus proxy with the prefix rewrite and
the query API, the generation/consumption/battery/grid panels, the static
JSON constants (lib/static.json), the bin/ lib/ split, the NixOS module,
the Docker compose service.
