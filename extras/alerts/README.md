# alerts — the family's Prometheus rule pack

The detection half of the audit vocabulary ([docs/AUDIT.md](../docs/AUDIT.md)
F16): one rule file per watched exporter, every alert naming the audit
events and the log lines it correlates with, so a fired page tells the
operator where the trail lives. No tool loads these files — the consumer
is the Prometheus collector; each watched exporter's package ships its
half (the same ruling shape as [`profiles/`](../profiles/README.md) and
[`extras/examples/`](../extras/examples/README.md), the other dirs no tool
owns).

| file | watches | group |
|---|---|---|
| [`scraper.yml`](scraper.yml) | the modbus-scraper's own poll story — the `scraper_*` gauges: poll down, the freshness gap, the exception bursts | `pv-suite-scraper` |
| [`cache.yml`](cache.yml) | the modbus-cache's side — the `modbus_cache_*` gauges: poll down, age spikes, the write-refusal bursts | `pv-suite-cache` |

The cache's `/metrics` endpoint is off by default and `cache.yml` stays
SILENT until a collector scrapes it — an absent series never fires; the
scraper's diag block (`scraper_cache_device_up` / `scraper_cache_age_seconds`)
mirrors two of the shapes for setups that do not scrape the cache. The
exporter's own death (the scrape itself failing) is the collector's stock
`up{job}` gauge and its scrape-failure hygiene, not this pack: this pack
watches the poll and the gates.

## Install map

| surface | where |
|---|---|
| nix — `modbus-scraper` | `share/modbus-scraper/alerts.yml` (this pack's `scraper.yml`) |
| nix — `modbus-cache` | `share/modbus-cache/alerts.yml` (this pack's `cache.yml`) — the cache-only install carries its half |
| docker — the demo image | both files baked to `/etc/prometheus/alerts/` ([Dockerfile.prometheus](../docker/Dockerfile.prometheus), the `alerts` build context) |
| production | your own collector — list the packaged copy(es) under its `rule_files:` |

Wire-in: the demo's [`prometheus.yml`](../docker/prometheus.yml) sets
`rule_files: [/etc/prometheus/alerts/*.yml]`; a NixOS Prometheus lists the
packaged copies — [NIXOS.md](../docs/NIXOS.md). Thresholds assume the
default 10 s poll interval — tune them to yours.

## License

The `alerts/` pack is licensed under the **BSD 3-Clause License** — see
the repo-root `LICENSE` file.
