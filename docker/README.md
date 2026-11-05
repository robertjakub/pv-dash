# The pv-suite containers

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

The suite is stdlib-only, so the containers are trivial: `alpine` + `apk add
python3`, no pip, no venv, ~50 MB images. One Dockerfile per tool —
`Dockerfile.inverter`, `Dockerfile.cache`, `Dockerfile.scraper`,
`Dockerfile.dashboard` — plus `Dockerfile.prometheus` for the demo stack's
collector, and a `compose.yaml` wiring the demo stack. The pattern:

- an unprivileged **`pvsuite`** user (`adduser -D`, `COPY --chown`); the
  entrypoint runs as root only to seed the config volume and drops to
  `pvsuite` via `su-exec` — the tool never runs as root
- the tools symlinked onto `PATH` (the inverter image: `fake-inverter`,
  `fake-ctl`, `fake-cli`; the cache image: `modbus-cache`, `modbus-cache-ctl`,
  `modbus-cache-cli`; the scraper image: `modbus-scraper`), `bash` for
  interactive runs
- the shared [`profiles/`](../profiles/README.md) JSON files copied flat to
  `/pv-suite/profiles/` (the subproject's `bin/` tools stay out of the
  image) — the profile resolution finds them relative to the checkout layout
- the **config volume** (`/config`, `VOLUME` + `ENTRYPOINT
  pv-entrypoint`): the image carries its bundled configs in
  `/pv-suite/config-defaults`; every file the volume does not have yet is
  copied in on start (existing ones stay) — the bundled ones are the
  defaults, the `/config` copies are the live ones (edit them there, they
  survive container recreation). The `ENV` vars point each tool at the
  volume copies.
- the build context = the subproject; the profiles, the entrypoint and the
  shared [`common/`](../common/README.md) package ride in as named build
  contexts (`additional_contexts` in the compose, `--build-context` for
  plain docker builds) — common lands at `/pv-suite/common/`, next to each
  tool's `lib/`

## The demo stack (compose)

All three Modbus services share the named `config` volume mounted at
`/config`; each container seeds it with its own bundled defaults on start.
`docker compose exec` sessions bypass the entrypoint and run as root — add
`--user pvsuite` to land as `pvsuite`.

```bash
cd docker
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
the compose's `DSH_PROM_URL`. Everything else stays closed (the audit's F7): the
services talk over one `internal: true` network (`pv-modbus` — no other host
ports, no outbound route), so the Modbus listeners, the exporter's
`/metrics` and the Prometheus UI are reachable only from inside that network.
`docker compose down` removes the network with the stack. (To browse the
Prometheus UI directly from the host as well, add
`ports: ["127.0.0.1:9090:9090"]` to the service in a
`docker-compose.override.yaml` — loopback-only, an explicit operator act.)

**The scrape/token story ships in the stack** (the audit's F13 closed for
the demo): the exporter never serves unauthenticated — the compose sets
`SCR_AUTH_TOKEN_FILE=/config/metrics.token`, and the entrypoint
generates that file into the volume on the first seed: a random value,
**0600, owner pvsuite** (bundled `*.token` defaults are placeholders that
are never copied — the generation is in `entrypoint.sh`; the token survives
container recreation with the volume). The Prometheus service reads its own
copy of the same file (`Dockerfile.prometheus` +
`entrypoint-prometheus.sh`: root copies `/config/metrics.token` to
`/etc/prometheus/metrics.token`, 0600, then drops to the unprivileged
`prometheus` user via su-exec) and scrapes with
`authorization: credentials_file` (`prometheus.yml`).

Read the token and the metrics from the inside:

```bash
docker compose exec modbus-scraper cat /config/metrics.token
TOKEN=$(docker compose exec modbus-scraper cat /config/metrics.token)
docker compose exec modbus-scraper wget -qO- --header "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:9350/metrics
```

A token-less request gets a 401 with a `WWW-Authenticate: Bearer` challenge.
Give Prometheus for another stack the same value as
`authorization.credentials_file` (an owner-only file, F12) — or attach the
collector container to the `pv-modbus` network and scrape
`modbus-scraper:9350` like the demo service does.

The poll chain is **fake-inverter → modbus-cache → scraper → Prometheus**:
the cache owns the inverter's single Modbus client and the exporter polls
the cache — which it auto-detects and reports with the `huawei_cache_*`
diagnostics metrics (`device_up 0` / a growing `age_seconds` mean the device
is down behind the cache while the cache keeps serving last-known values).

## The demo stack's topology

One `internal: true` network (`pv-modbus`), nothing published on the host,
one shared `config` volume seeded by the entrypoints, one bearer token
generated into that volume gating the exporter. The arrows are the traffic;
every listener binds inside the network only:

```text
        HOST — 127.0.0.1:8080 published (the dashboard's UI), nothing else
   ┌─────────────────────────────────────────────────────────────────────┐
   │                                                                     │
   │   internal network "pv-modbus"                                      │
   │   ┌──────────────────────────────────────────────────────────┐      │
   │   │                                                          │      │
   │   │  ┌──────────────┐  FC3/4 reads  ┌──────────────┐         │      │
   │   │  │fake-inverter │◄────10s poll──┤ modbus-cache │         │      │
   │   │  │  (the device)│────values────►│    15502     │         │      │
   │   │  └──────▲───────┘               └──────┬───────┘         │      │
   │   │         │ FC06/16 writes (gated; the   │ 10s poll        │      │
   │   │         │ write gates default closed:  │ /metrics        │      │
   │   │         │ allow-write off, write-acl/  │                 │      │
   │   │         │ write-registers none)        │                 │      │
   │   │         └──────────────────────────────┘                 │      │
   │   │                                        │                 │      │
   │   │                                        ▼                 │      │
   │   │   Bearer token (0600) ──────► ┌──────────────┐           │      │
   │   │                               │modbus-scraper│           │      │
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
   │   shared "config" volume (/config): the ini files + metrics.token,  │
   │   mounted by the Modbus services + the dashboard; prometheus ro     │
   │                                                                     │
   │   docker compose exec <service> …  — the way in                     │
   └─────────────────────────────────────────────────────────────────────┘
```

- **fake-inverter** — the device; its Modbus is the only "hardware" in the
  demo (no auth — the internal network is the boundary).
- **modbus-cache** — the proxy: polls the fake every 10 s, owns the single
  client slot, serves reads from memory; writes stay closed by default
  (`allow-write` off, `write-acl`/`write-registers` none).
- **modbus-scraper** — the exporter: polls the cache every 10 s, serves
  `/metrics` with the bearer token.
- **prometheus** — scrapes the exporter every 10 s with the same token;
  its TSDB is the `prometheus-data` volume; its UI stays internal — the
  dashboard is the front.
- **dashboard** — the single-page app + its stdlib proxy server: the only
  published surface, loopback `127.0.0.1:8080:8080`; `/prom` proxies the
  internal Prometheus (`DSH_PROM_URL=http://prometheus:9090`), the static files
  and the served `config.js` come from the image (the `/config` copies for
  the live edits).
- **the `config` volume** — mounted by the three Modbus services and the
  dashboard (prometheus reads it read-only): the config files are editable
  there; `/config/metrics.token` is the generated shared secret.
- **the audit trails** — the tools audit to stdout in the demo, so `docker
  compose logs <service>` is the trail.

The volume is a compose-managed named volume: `docker compose down` keeps
it, `down -v` wipes it (reseeded with the bundled defaults on the next
`up`). Seeding happens **once per file** — a bundled-default fix only
reaches an existing volume after `down -v` (or a manual `/config` edit).

## The images, one by one

### fake-inverter (`Dockerfile.inverter`)

The demo device for development and testing — see the
[fake inverter](../inverter/README.md):

```bash
cd docker
docker build -t fake-inverter --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../inverter
docker run --rm -p 127.0.0.1:5502:5502 fake-inverter      # loopback-published, serves on 0.0.0.0:5502 in the container
docker run --rm -it fake-inverter bash                    # poke around as pvsuite
docker run --rm -p 127.0.0.1:5502:5502 fake-inverter \
    fake-inverter --profile deye-sg04lp3 --no-battery    # any flags via the CMD override
```

The fake has no file configs yet — its `/config` volume is there for
symmetry with the other two images and for future use.

### modbus-cache (`Dockerfile.cache`)

The caching proxy multiplexing the inverter's single Modbus client — see the
[cache](../cache/README.md). The live configs are `/config/modbus_cache.conf`
and `/config/selection.json` (`MCH_CONFIG` /
`MCH_SELECTION`):

```bash
cd docker
docker build -t modbus-cache --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../cache
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache    # upstream defaults to the fake-inverter service name
docker run --rm -it modbus-cache bash          # poke around as pvsuite
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache \
    modbus-cache --host 192.168.1.100          # any flags via the CMD override
```

Without `-v` the volume is anonymous (thrown away with `--rm`); name it to
keep the configs: `docker run -v pv-suite-config:/config ...` — the same
named volume under all three tools keeps every config in one place.

### modbus-scraper (`Dockerfile.scraper`)

The Prometheus exporter — see the [scraper](../scrape/README.md). The live
configs are `/config/scraper.ini` and `/config/metrics.json`
(`SCR_CONFIG` / `SCR_METRICS_SPEC`):

```bash
cd docker
docker build -t modbus-scraper --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../scrape
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper    # upstream defaults to the modbus-cache service name (port 15502)
docker run --rm -it modbus-scraper bash        # poke around as pvsuite
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper \
    modbus-scraper --host 192.168.1.100        # any flags via the CMD override
```

Standalone runs stay token-less by default — the compose stack is what
wires the token (`SCR_AUTH_TOKEN_FILE`); pass
`-e SCR_AUTH_TOKEN_FILE=/config/metrics.token` by hand to mirror it.

### prometheus (`Dockerfile.prometheus`)

The demo stack's scraper — alpine + the prometheus package, no python.
The context is the `docker/` directory itself:

```bash
cd docker
docker build -t pv-prometheus -f Dockerfile.prometheus .
```

Compose-only by design: it mounts the shared `config` volume (read-only)
for the token, needs `modbus-scraper` on the internal network, and its
entrypoint (`entrypoint-prometheus.sh`) drops root before the exec — see
[The demo stack](#the-demo-stack-compose). The UI serves on the internal
network only — the dashboard's proxy is the way in from the host.

### dashboard (`Dockerfile.dashboard`)

The static single-page app with its stdlib Prometheus proxy — see the
[dashboard](../dashboard/README.md). The live configs are
`/config/server.conf` and `/config/config.js` (`--config /config/server.conf`,
`DSH_CONFIG_JS`):

```bash
cd docker
docker build -t pv-dashboard --build-context scripts=../docker ../dashboard
docker run --rm -p 127.0.0.1:8080:8080 pv-dashboard    # loopback-published, serves 0.0.0.0:8080 in the container
docker run --rm -it pv-dashboard bash                  # poke around as pvsuite
docker run --rm -p 127.0.0.1:8080:8080 -e DSH_PROM_URL=http://prometheus:9090 \
    pv-dashboard                                       # the upstream via env (env beats server.conf)
```

The upstream defaults to the bundled `server.conf`'s
`upstream = http://localhost:9090`; `DSH_PROM_URL` (env) or a `--upstream` flag
override it. In the compose stack the compose sets `DSH_PROM_URL` to the
internal `prometheus` service — the dashboard is the stack's one published
surface (`127.0.0.1:8080:8080`).

## The version inside the image

The version reports as `0.3.0` inside the image (no git metadata; a checkout
shows `0.3.0-<short git>`).

## License

The containers (the Dockerfiles, the entrypoint and the compose stack) are
licensed under the **BSD 3-Clause License** — see the repo-root `LICENSE`
file.
