# The demo stack

> **These are example files for the DEMO.** The compose stack here wires
> the fake inverter end to end on one internal network — a self-contained
> demo, not a production recipe. Before running it against real hardware,
> adapt it: point the cache's `UPSTREAM` at the device
> (`env/cache.env`), publish only the ports your clients actually need
> (loopback first — see the F7 notes below), and size the collector's
> retention (`env/prometheus.env`). The production shape is the sibling
> [prod/](../prod/compose.yaml) stack — see
> [the parent README](../README.md).

The images are the parent directory's one per tool — the demo only wires
them: `compose.yaml` runs the fake inverter, the cache, the scraper, the
Prometheus collector (`../Dockerfile.prometheus`) and the dashboard on
one `internal: true` network.

```bash
cd docker/demo
docker compose up -d fake-inverter              # build + serve on the internal network
docker compose up -d modbus-cache               # + the cache proxy (upstream: fake-inverter)
docker compose up -d modbus-scraper             # + the exporter (upstream: modbus-cache)
docker compose up -d prometheus                 # + the scraper's Prometheus, scraping modbus-scraper:9350
docker compose up -d dashboard                  # + the dashboard, proxying the internal Prometheus
docker compose exec --user pvsuite fake-inverter fake-cli   # a console session on the control server
docker compose down
```

**Exactly one port is published on the host** — the dashboard's HTTP
interface, loopback-only (`127.0.0.1:8080:8080`): the front for the stack's
internal Prometheus, its `/prom` proxy aimed at `http://prometheus:9090` by
the compose's `PROM_URL`. Everything else stays closed (the audit's F7): the
services talk over one `internal: true` network (`pv-modbus` — no other host
ports, no outbound route), so the Modbus listeners, the exporter's
`/metrics` and the Prometheus UI are reachable only from inside that network.
`docker compose down` removes the network with the stack. (To browse the
Prometheus UI directly from the host as well, add
`ports: ["127.0.0.1:9090:9090"]` to the service in a
`docker-compose.override.yaml` — loopback-only, an explicit operator act.)

The env files, the env-or-volume split and the secrets story are the parent
README's — [the env files](../README.md#the-env-files-one-per-tool),
[env or the config volume?](../README.md#env-or-the-config-volume),
[the secrets story](../README.md#the-secrets-story).

## The demo stack's topology

One `internal: true` network (`pv-modbus`), nothing published on the host,
one shared `config` volume seeded by the entrypoints, and the two secrets
generated into that volume: the bearer token gating the exporter and the
suite key authenticating the Modbus hops (every connect proves it —
fake-inverter demands the handshake from the cache, the cache demands it
from the scraper and proves it upstream). The arrows are the traffic;
every listener binds inside the network only:

```text
        HOST - 127.0.0.1:8080 published (the dashboard's UI), nothing else
   ┌─────────────────────────────────────────────────────────────────────┐
   │                                                                     │
   │   internal network "pv-modbus"                                      │
   │   ┌──────────────────────────────────────────────────────────┐      │
   │   │                                                          │      │
   │   │  ┌──────────────┐  FC3/4 reads  ┌──────────────┐         │      │
   │   │  │fake-inverter │◄────10s poll──┤ modbus-cache │         │      │
   │   │  │  (the device)│────values────►│    15502     │         │      │
   │   │  └──────▲───────┘  + the suite └──────┬───────┘         │      │
   │   │         │ handshake on     10s poll   │                 │      │
   │   │         │ every connect    /metrics   │                 │      │
   │   │         │ (writes stay     (bearer    │                 │      │
   │   │         │ gated: allow-     token)    │                 │      │
   │   │         │ write off,                  │                 │      │
   │   │         │ write-acl/                  │                 │      │
   │   │         │ write-registers             │                 │      │
   │   │         │ none)                       │                 │      │
   │   │         └─────────────────────────────┘                 │      │
   │   │                                        │                 │      │
   │   │                                        ▼                 │      │
   │   │   Bearer token (0600) ──────► ┌──────────────┐           │      │
   │   │   Suite key (0600) ─────────► │modbus-scraper│           │      │
   │   │                               │    9350      │           │      │
   │   │                               └──────┬───────┘           │      │
   │   │                                      │ scrape 10s        │      │
   │   │                                      ▼                   │      │
   │   │                               ┌──────────────┐           │      │
   │   │                        9090   │  prometheus  │           │      │
   │   │              ┌───── /prom ────│ (TSDB volume)│           │      │
   │   │              │                └──────────────┘           │      │
   │   │              ▼                                           │      │
   │   │      ┌──────────────┐                                    │      │
   │   │      │  dashboard   │ 8080 ── the one published port     │      │
   │   │      └──────────────┘        (127.0.0.1 only)            │      │
   │   └──────────────────────────────────────────────────────────┘      │
   │                                                                     │
   │   shared "config" volume (/config): metrics.token, modbus-auth.     │
   │   token, the JSON specs, config.js - mounted by the Modbus          │
   │   services + the dashboard; prometheus reads it read-only           │
   │                                                                     │
   │   docker compose exec <service> ... - the way in                    │
   └─────────────────────────────────────────────────────────────────────┘
```

- **fake-inverter** — the device; its Modbus is the only "hardware" in the
  demo, and it demands the suite handshake on every connect (the shared
  generated key — the internal network is the boundary, the handshake is
  the proof).
- **modbus-cache** — the proxy: polls the fake every 10 s (proving the
  suite key upstream), owns the single client slot, serves reads from
  memory, demands the same key from its own clients; writes stay closed
  by default (`allow-write` off, `write-acl`/`write-registers` none).
- **modbus-scraper** — the exporter: polls the cache every 10 s (proving
  the suite key), serves `/metrics` with the bearer token.
- **prometheus** — scrapes the exporter every 10 s with the same token;
  its TSDB is the `prometheus-data` volume; its UI stays internal — the
  dashboard is the front.
- **dashboard** — the single-page app + its stdlib proxy server: the only
  published surface, loopback `127.0.0.1:8080:8080`; `/prom` proxies the
  internal Prometheus (`PROM_URL=http://prometheus:9090`), the static files
  and the served `config.js` come from the image (the `/config` copies for
  the live edits).
- **the `config` volume** — mounted by the three Modbus services and the
  dashboard (prometheus reads it read-only): the required file artifacts
  live there (the JSON specs, `config.js`); `/config/metrics.token` and
  `/config/modbus-auth.token` are the generated shared secrets.
- **the audit trails** — the tools audit to stdout in the demo, so `docker
  compose logs <service>` is the trail.

The volume is a compose-managed named volume: `docker compose down` keeps
it, `down -v` wipes it (reseeded with the required file artifacts on the
next `up`). Seeding happens **once per file** — a bundled-artifact fix
only reaches an existing volume after `down -v` (or a manual `/config`
edit).
