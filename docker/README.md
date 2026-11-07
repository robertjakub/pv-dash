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
  volume copies (and carry the demo stack's default upstream peers). See
  [env or the config volume?](#env-or-the-config-volume) for the split:
  the env twins (and the compose `.env`) cover the knobs, the volume holds
  the file-shaped artifacts.
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
the compose's `PROM_URL`. Everything else stays closed (the audit's F7): the
services talk over one `internal: true` network (`pv-modbus` — no other host
ports, no outbound route), so the Modbus listeners, the exporter's
`/metrics` and the Prometheus UI are reachable only from inside that network.
`docker compose down` removes the network with the stack. (To browse the
Prometheus UI directly from the host as well, add
`ports: ["127.0.0.1:9090:9090"]` to the service in a
`docker-compose.override.yaml` — loopback-only, an explicit operator act.)

### The .env overrides

The compose file interpolates a `.env` from this directory —
`cp .env.example .env` and edit (a different file: `docker compose
--env-file other.env ...`). The example carries the deployment-shaped
knobs: the poll chain's upstreams (`CACHE_UPSTREAM` — point the cache at a
real inverter; `SCRAPER_UPSTREAM`), the cadence (`POLL_INTERVAL`,
`CACHE_TTL`), the fake's device profile (`FAKE_PROFILE`), the exporter's
token file (`SCRAPER_TOKEN_FILE`) and its metric prefix, the dashboard's
published port (`DASHBOARD_PORT`) and `PROM_URL`, and one `LOG_LEVEL` for
the two file-config pollers. The names are compose-side keys, mapped onto
the services' bare-name env twins one service at a time — `UPSTREAM` alone
would be ambiguous (it names a different peer per tool). Every default
stays while the line is commented; the tools treat an empty env value as
unset, so commenting a line out is always safe.

The values land as plain env twins — flag > env > config script > default —
so a `.env` setting beats the seeded `/config` conf file, and a
`--upstream` CMD override beats it in turn. Anything beyond the curated
set (the control-plane tokens, the write gates, the state dump): add the
env mapping to a `docker-compose.override.yaml` (it layers over
compose.yaml) instead of editing the compose file.

### env or the config volume?

Both, on purpose — they split by shape. The `.env` covers what an env twin
can carry (every knob has one; the env beats the conf file in the
resolution). The `/config` volume stays because the things it holds are
files by nature, not knobs:

- **the generated `metrics.token`** — one shared secret, produced once by
  the entrypoint (0600, owner pvsuite), read by the exporter and the
  stack's Prometheus; it must survive recreation unchanged and be the same
  value in two containers — and a secret in `.env` would sit unencrypted
  in the project directory, ripe for committing (the F12 discipline
  prefers owner-only files; the knobs accept `file:` references for
  exactly this)
- **`selection.json` and `metrics.json`** — JSON specs, not knobs: the
  `SELECTION`/`METRICS_SPEC` env twins only point at the files
- **`config.js`** — the dashboard's served front-end file (`CONFIG_JS`
  points at it)

The three conf scripts stay seeded for the edit-a-file workflow; with a
`.env` in play they are simply overridden and inert.

**The scraper/token story ships in the stack** (the audit's F13 closed for
the demo): the exporter never serves unauthenticated — the compose sets
`AUTH_TOKEN_FILE=/config/metrics.token`, and the entrypoint
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
the cache — which it auto-detects and reports with the `scraper_cache_*`
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
   │   shared "config" volume (/config): the conf scripts, the JSON     │
   │   specs, config.js + metrics.token — mounted by the Modbus         │
   │   services + the dashboard; prometheus reads it read-only          │
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
  internal Prometheus (`PROM_URL=http://prometheus:9090`), the static files
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
and `/config/selection.json` (`CONFIG` /
`SELECTION`):

```bash
cd docker
docker build -t modbus-cache --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../cache
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache    # upstream defaults to fake-inverter:5502 (the image's UPSTREAM env)
docker run --rm -it modbus-cache bash          # poke around as pvsuite
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache \
    modbus-cache --upstream 192.168.1.100:5502          # any flags via the CMD override
docker run --rm -p 127.0.0.1:15502:15502 \
    -e UPSTREAM=192.168.1.100:5502 modbus-cache         # the peer via env (a --upstream flag beats it)
```

Without `-v` the volume is anonymous (thrown away with `--rm`); name it to
keep the configs: `docker run -v pv-suite-config:/config ...` — the same
named volume under all three tools keeps every config in one place.

### modbus-scraper (`Dockerfile.scraper`)

The Prometheus exporter — see the [scraper](../scraper/README.md). The live
configs are `/config/scraper.conf` and `/config/metrics.json`
(`CONFIG` / `METRICS_SPEC`):

```bash
cd docker
docker build -t modbus-scraper --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../scraper
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper    # upstream defaults to modbus-cache:15502 (the image's UPSTREAM env)
docker run --rm -it modbus-scraper bash        # poke around as pvsuite
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper \
    modbus-scraper --upstream 192.168.1.100:502        # any flags via the CMD override
docker run --rm -p 127.0.0.1:9350:9350 \
    -e UPSTREAM=192.168.1.100:15502 modbus-scraper     # the peer via env (a --upstream flag beats it)
```

Standalone runs stay token-less by default — the compose stack is what
wires the token (`AUTH_TOKEN_FILE`); pass
`-e AUTH_TOKEN_FILE=/config/metrics.token` by hand to mirror it.

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
`CONFIG_JS`):

```bash
cd docker
docker build -t pv-dashboard --build-context scripts=../docker ../dashboard
docker run --rm -p 127.0.0.1:8080:8080 pv-dashboard    # loopback-published, serves 0.0.0.0:8080 in the container
docker run --rm -it pv-dashboard bash                  # poke around as pvsuite
docker run --rm -p 127.0.0.1:8080:8080 -e PROM_URL=http://prometheus:9090 \
    pv-dashboard                                       # the upstream via env (env beats server.conf)
```

The upstream defaults to the bundled `server.conf`'s
`upstream = http://localhost:9090`; `PROM_URL` (env) or a `--upstream` flag
override it. In the compose stack the compose sets `PROM_URL` to the
internal `prometheus` service — the dashboard is the stack's one published
surface (`127.0.0.1:8080:8080`).

## The version inside the image

The version reports as `0.3.0` inside the image (no git metadata; a checkout
shows `0.3.0-<short git>`).

## License

The containers (the Dockerfiles, the entrypoint and the compose stack) are
licensed under the **BSD 3-Clause License** — see the repo-root `LICENSE`
file.
