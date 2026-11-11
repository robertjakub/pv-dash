# The production stack

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still
> change at any time.

**This is the production shape**: the three services — the cache, the
scraper, the dashboard — against real hardware. The same images the
demo stack runs; only the wiring differs:

- **no fake inverter** — the cache's `UPSTREAM` is the device, the
  operator's decision (the stack refuses to start without it)
- **no in-stack collector** — Prometheus is *yours*, external: it pulls
  `/metrics` from the exporter (the bearer token gates it); the
  dashboard's `/prom` proxy points at it
- **the network is not `internal: true`** — the cache dials the device
  on the LAN (the demo's closed network would cut the route out)
- **`env/cache.env` is required** — the demo's env files are optional
  (`required: false`, the image defaults stand); here the cache's file
  must exist

The secrets ship decided — the stack is authenticated out of the box
([the secrets story](../README.md#the-secrets-story)): the Modbus hops
prove the generated suite key on every connect, the exporter serves
with the generated bearer token, the dashboard's page is token'd (F21).

```bash
cd docker/prod
cp ../env/cache.env.example ../env/cache.env
$EDITOR ../env/cache.env                            # UPSTREAM=192.168.1.100:5502 — the device
docker compose up -d                                # cache + scraper + dashboard
docker compose exec --user pvsuite modbus-cache modbus-cache-cli   # a console session
docker compose down                                 # keeps the volume; down -v wipes it
```

## The operator's decisions

Each is called out in the compose file's comments:

- **the device address** — `env/cache.env` is **required** (no
  `required: false`): the image's default `UPSTREAM`
  (`fake-inverter:5502`) only ever resolves in the demo. Set
  `UPSTREAM=HOST:PORT` to the device.
- **the device's own auth** (optional) — if the device or its gateway
  speaks an auth scheme, set `AUTH_UPSTREAM=suite|waveshare` and
  `AUTH_UPSTREAM_KEY` in the same env file: the upstream credential is
  the device's, the env file is its edit surface. (The Waveshare
  spelling is cache-only — the gateway connection password.) A device
  without auth stays `none` — the stack's own hops are authenticated
  regardless.
- **your collector's way in** — the exporter's `/metrics` is published
  loopback-only (`127.0.0.1:9350:9350`) for a host-level collector: it
  scrapes with `authorization.credentials_file` — an owner-only copy of
  the token ([the secrets story](../README.md#the-secrets-story)). A
  container collector instead: delete the `9350` mapping and attach it
  to the `pv-suite` network (it scrapes `modbus-scraper:9350` like the
  demo's in-stack service does).
- **the dashboard's `PROM_URL`** — edit it in the compose file: your
  collector's base URL (the dashboard's `/prom` proxy target).

Everything else ships decided: the cache's server side and the
scraper's client side prove the stack's suite key on every Modbus
connect (opening a hop is a compose edit — an explicit operator act,
the F7 shape).

## The production topology

One compose network (`pv-suite`, **not** internal — the route out to
the device), two published ports on the host, both loopback-only (the
dashboard's UI + the exporter's `/metrics` for your collector), one
shared `config` volume seeded by the entrypoints, and the two secrets
generated into that volume: the bearer token gating the exporter and
the suite key authenticating the Modbus hops. The device and the
collector sit outside the network — the cache's client and the
collector's pull are the two routes through:

```text
        HOST - 127.0.0.1:8080 (the dashboard's UI) + 127.0.0.1:9350
        (/metrics for your collector) - both loopback-only, nothing else

          the device: real hardware -    ┌──────────────┐
          UPSTREAM=HOST:PORT lives in    │  inverter    │
          env/cache.env (the required    └──────┬───────┘
          file); its own auth, if any,          │
          rides AUTH_UPSTREAM there             │
                                                │
          FC3/4 reads, 10s poll - the           │
          suite handshake (or the               │
          waveshare password) if the            │
          device speaks one                     │
                                                │
   ┌────────────────────────────────────────────│───────────────────────┐
   │   ┌────────────────────────────────────────│────────────────┐      │
   │   │            compose network "pv-suite"  │                │      │
   │   │            - NOT internal (the         │                │      │
   │   │            cache's client is the       │                │      │
   │   │            route out)                  │                │      │
   │   │                                 ┌──────┴───────┐        │      │
   │   │ the cache demands the suite     │modbus-cache  │        │      │
   │   │ key server-side; the scraper    │    15502     │        │      │
   │   │ proves it on every connect      └──────┬───────┘        │      │
   │   │                                        │  10s poll      │      │
   │   │                                        │  /metrics      │      │
   │   │                                        │  (bearer token)│      │
   │   │    Suite key (0600) ────────►          ▼                │      │
   │   │    Bearer token (0600) ─────►   ┌──────────────┐        │      │
   │   │                                 │modbus-scraper│        │      │
   │   │                                 │    9350      │        │      │
   │   │                                 └──────┬───────┘        │      │
   │   │  ┌──────────────┐                      │ pull /metrics  │      │
   │   │  │  dashboard   │                      │ (bearer token) │      │
   │   │  └───────┬──────┘                      │                │      │
   │   └──────────│─────────────────────────────│────────────────┘      │
   │              │                             │                       │
   │              │                      ┌──────┴───────┐               │
   │              └──── /prom ───────►   │  prometheus  │               │
   │      your external collector -      └──────────────┘               │
   │      it pulls /metrics with the                                    │
   │                                                                    │
   │    shared "config" volume (/config): metrics.token,                │
   │    modbus-auth.token, the JSON specs, config.js -                  │
   │    mounted by the Modbus services + the dashboard;                 │
   │    prometheus reads it read-only                                   │
   │                                                                    │
   │    docker compose exec <service> ... - the way in                  │
   └────────────────────────────────────────────────────────────────────┘
```

- **the device** — real hardware, outside the network; its address (and
  its auth scheme, if any) live in the operator's `env/cache.env`.
- **modbus-cache** — the proxy: polls the device every 10 s (proving
  the suite key upstream when `AUTH_UPSTREAM` says so), owns the single
  client slot, serves reads from memory, demands the same key from its
  own clients; writes stay closed by default (`allow-write` off,
  `write-acl`/`write-registers` none).
- **modbus-scraper** — the exporter: polls the cache every 10 s
  (proving the suite key), serves `/metrics` with the bearer token.
- **dashboard** — the single-page app + its stdlib proxy server: one of
  the two published surfaces, loopback `127.0.0.1:8080:8080`; `/prom`
  proxies YOUR collector (`PROM_URL`), the static files and the served
  `config.js` come from the image (the `/config` copies for the live
  edits).
- **your collector** — external, not this stack's concern: anything
  that pulls `/metrics` (Prometheus or another pull collector). The
  demo's `Dockerfile.prometheus` is the reference wiring
  ([the images](../README.md#prometheus-dockerfileprometheus)). The
  **alert rules pack** ships at `extras/alerts/` in the repo, one file per
  watched exporter — the packaged copy sits at
  `share/modbus-scraper/alerts.yml` (the cache package carries
  `share/modbus-cache/alerts.yml`) — list them under your
  Prometheus's `rule_files:` and the audit vocabulary's alerts ride
  along (docs/AUDIT.md F16).
- **the `config` volume** — mounted by the three Modbus services and
  the dashboard: the required file artifacts live there (the JSON
  specs, `config.js`); `/config/metrics.token` and
  `/config/modbus-auth.token` are the generated shared secrets.
- **the audit trails** — the tools audit to stdout in the stacks, so
  `docker compose logs <service>` is the trail.

The volume is a compose-managed named volume: `docker compose down`
keeps it, `down -v` wipes it (reseeded with the required file
artifacts on the next `up`). Seeding happens **once per file** — a
bundled-artifact fix only reaches an existing volume after `down -v`
(or a manual `/config` edit).
