# TODO

## Open

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
- **the auth story** — the proxy endpoints are open on the LAN; a
  reverse-proxy doc (or a bearer check mirroring the scraper's) before
  exposing anything beyond localhost.

## Done (the highlights; the git history has the details)

The read-only dashboard: the Prometheus proxy with the prefix rewrite and
the query API, the generation/consumption/battery/grid panels, the static
JSON constants (lib/static.json), the bin/ lib/ split, the NixOS module,
the Docker compose service.
