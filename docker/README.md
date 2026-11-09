# The pv-suite containers

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

> **These are example files for the DEMO.** The compose stack below wires
> the fake inverter end to end on one internal network — a self-contained
> demo, not a production recipe. Before running it against real hardware,
> adapt it: point the cache's `UPSTREAM` at the device
> (`env/cache.env`), publish only the ports your clients actually need
> (loopback first — see the F7 notes below), and size the collector's
> retention (`env/prometheus.env`).

The suite is stdlib-only, so the containers are trivial: `alpine` + `apk add
python3`, no pip, no venv, ~50 MB images. One Dockerfile per tool, named
after the tool's daemon — `Dockerfile.fake-inverter`,
`Dockerfile.modbus-cache`, `Dockerfile.modbus-scraper`,
`Dockerfile.dashboard` — plus `Dockerfile.prometheus` for the demo stack's
collector, and a `compose.yaml` wiring the demo stack. The pattern:

- an unprivileged **`pvsuite`** user (`adduser -D`, `COPY --chown`); the
  entrypoint runs as root only to seed the config volume and drops to
  `pvsuite` via `su-exec` — the tool never runs as root
- the tools symlinked onto `PATH` (the inverter image: `fake-inverter`,
  `fake-ctl`, `fake-cli`; the cache image: `modbus-cache`, `modbus-cache-ctl`,
  `modbus-cache-cli`; the scraper image: `modbus-scraper`,
  `modbus-scraper-ctl`, `modbus-scraper-cli`; the dashboard image:
  `dashboard`, `dashboard-ctl`, `dashboard-cli`), `bash` for interactive
  runs
- a **HEALTHCHECK** on every image: the Modbus tools answer over their
  unix control socket (`<tool>-ctl ping` / `show version` — the check
  runs as root, a trusted peer over SO_PEERCRED, so no token is needed;
  disabling the control plane with `CTL=0` fails the check — and so does
  a live `set control port off` on a running container, by design; a
  later `set control port <unix-path>` re-arms it), the
  Prometheus image probes `/-/ready` with busybox wget
- the shared [`profiles/`](../profiles/README.md) JSON files copied flat to
  `/pv-suite/profiles/` (the subproject's `bin/` tools stay out of the
  image) — the profile resolution finds them relative to the checkout layout
- the **config volume** (`/config`, `VOLUME` + `ENTRYPOINT
  pv-entrypoint`): the entrypoint seeds it with the **required file
  artifacts only** — the generated `metrics.token`, the JSON specs
  (`selection.json`, `metrics.json`) and the served `config.js`; the
  bundled conf scripts are NOT copied there (each tool loads the image's
  own conf as the default layer). See
  [env or the config volume?](#env-or-the-config-volume) for the split:
  the env twins (and the per-tool env files) cover the knobs, the volume
  holds the file-shaped artifacts.
- the build context = the subproject; the profiles, the entrypoint and the
  shared [`common/`](../common/README.md) package ride in as named build
  contexts (`additional_contexts` in the compose, `--build-context` for
  plain docker builds) — common lands at `/pv-suite/common/`, next to each
  tool's `lib/`

## The demo stack (compose)

All three Modbus services share the named `config` volume mounted at
`/config`; each container seeds it with its own required file artifacts on
start (the token, its JSON spec).
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

### The env files (one per tool)

Each image has its own env file, shipped as an example:
`env/cache.env.example`, `env/scraper.env.example`, `env/fake.env.example`,
`env/dashboard.env.example`, `env/prometheus.env.example` — `cp
env/<tool>.env.example env/<tool>.env` and edit. The names are the
**bare env twins** the tool's own docs speak (`UPSTREAM`, `INTERVAL`,
`TTL`, `PROFILE`, `METRIC_PREFIX`, `LOG_LEVEL`, …) — one file per tool,
so no namespacing is needed (the Prometheus file is the exception: its
`PROM_*` knobs belong to `entrypoint-prometheus.sh`, not a pv-suite
tool). Every line starts commented; the defaults live in the image.

The same file is consumed two ways:

```bash
cd docker
cp env/cache.env.example env/cache.env
$EDITOR env/cache.env                            # UPSTREAM=192.168.1.100:5502

docker run --rm -p 127.0.0.1:15502:15502 \
    --env-file env/cache.env modbus-cache        # plain docker: --env-file

docker compose up -d modbus-cache                # the stack: env_file: (required: false)
```

Compose reads the service's file via `env_file:` with `required: false`
(compose ≥ 2.24) — **no file means the image defaults**, so the stack runs
out of the box; when a file exists its values ride the tools' resolution
(**flag > env > the bundled conf > built-in defaults**) — an env value
overrides the image's bundled conf script, the same layering a plain
checkout has. Compose recreates a service when its env file changes. Two
knobs are compose-level by nature and stay in the compose file: the
dashboard's published port and its `PROM_URL` (the stack's
`environment:` block — environment beats env_file, so `scraper.env`'s
`AUTH_TOKEN` cannot override the stack's generated-token file
either; the token story stays the volume file, a plain-docker
`AUTH_TOKEN=file:...` in `scraper.env` is fine). The fake's simulation envs
(`CHAOS`, `MAX_KWP`, `STRICT`, `TIME`, `TIME_SCALE`) are its
SIGHUP layer, not startup: they reach a container when it is created with
them (compose recreates on the file change) or via
`docker compose kill -s HUP fake-inverter`.

### env or the config volume?

Both, on purpose — they split by shape. The bundled conf scripts are not
copied to the volume at all: each tool loads the image's own conf (the
default `--config` target) as the default layer, and the env files
override it knob by knob — the env file is the edit surface. The
`/config` volume stays for the things that are files by nature, not knobs:

- **the generated `metrics.token`** — one shared secret, produced once by
  the entrypoint (0600, owner pvsuite), read by the exporter and the
  stack's Prometheus; it must survive recreation unchanged and be the same
  value in two containers — and a secret in an env file would sit
  unencrypted in the project directory, ripe for committing (the F12
  discipline prefers owner-only files; the knobs accept `file:`
  references for exactly this)
- **`selection.json` and `metrics.json`** — JSON specs, not knobs: the
  `SELECTION`/`METRICS_SPEC` env twins only point at the files; edit them
  in the volume (they seed once, edits survive recreation)
- **`config.js`** — the dashboard's served front-end file (`CONFIG_JS`
  points at it), same story

Prefer the conf file after all? Point the tool at the volume —
`CONFIG=/config/modbus_cache.conf` (env) or a `--config` flag — and edit
the file there; the entrypoint keeps whatever is in the volume. A volume
carrying a legacy seeded conf (`modbus_cache.conf`, `scraper.conf`,
`server.conf` from an older image) is simply no longer loaded.

**The scraper/token story ships in the stack** (the audit's F13 closed for
the demo): the exporter never serves unauthenticated — the compose sets
`AUTH_TOKEN=file:/config/metrics.token` (the `file:` reference form), and the entrypoint
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
        HOST - 127.0.0.1:8080 published (the dashboard's UI), nothing else
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
   │   shared "config" volume (/config): metrics.token, the JSON         │
   │   specs, config.js - mounted by the Modbus services + the           │
   │   dashboard; prometheus reads it read-only                          │
   │                                                                     │
   │   docker compose exec <service> ... - the way in                    │
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
  dashboard (prometheus reads it read-only): the required file artifacts
  live there (the JSON specs, `config.js`); `/config/metrics.token` is the
  generated shared secret.
- **the audit trails** — the tools audit to stdout in the demo, so `docker
  compose logs <service>` is the trail.

The volume is a compose-managed named volume: `docker compose down` keeps
it, `down -v` wipes it (reseeded with the required file artifacts on the
next `up`). Seeding happens **once per file** — a bundled-artifact fix
only reaches an existing volume after `down -v` (or a manual `/config`
edit).

## The images, one by one

### fake-inverter (`Dockerfile.fake-inverter`)

The demo device for development and testing — see the
[fake inverter](../inverter/README.md):

```bash
cd docker
docker build -f ../docker/Dockerfile.fake-inverter -t fake-inverter \
    --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../inverter
docker run --rm -p 127.0.0.1:5502:5502 fake-inverter      # loopback-published, serves on 0.0.0.0:5502 in the container
docker run --rm -it fake-inverter bash                    # poke around as pvsuite
docker run --rm -p 127.0.0.1:5502:5502 fake-inverter \
    fake-inverter --profile deye-sg04lp3 --timezone local    # any flags via the CMD override
```

The fake has no file configs yet — its `/config` volume is there for
symmetry with the other two images and for future use.

### modbus-cache (`Dockerfile.modbus-cache`)

The caching proxy multiplexing the inverter's single Modbus client — see the
[cache](../cache/README.md). The bundled conf
(`/pv-suite/cache/modbus_cache.conf`, the default `--config` target) loads
from the image; the volume carries `/config/selection.json` (`SELECTION`)
— edit it there, it survives recreation; override the conf's knobs with
`env/cache.env` (or flags):

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-cache -t modbus-cache \
    --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../cache
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache    # upstream defaults to fake-inverter:5502 (the image's UPSTREAM env)
docker run --rm -it modbus-cache bash          # poke around as pvsuite
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache \
    modbus-cache --upstream 192.168.1.100:5502          # any flags via the CMD override
docker run --rm -p 127.0.0.1:15502:15502 \
    --env-file env/cache.env modbus-cache       # the peer via the env file (a --upstream flag beats it)
```

Without `-v` the volume is anonymous (thrown away with `--rm`); name it to
keep the configs: `docker run -v pv-suite-config:/config ...` — the same
named volume under all three tools keeps every config in one place.

### modbus-scraper (`Dockerfile.modbus-scraper`)

The Prometheus exporter — see the [scraper](../scraper/README.md). The
bundled conf (`/pv-suite/scraper/scraper.conf`, the default `--config`
target) loads from the image; the volume carries `/config/metrics.json`
(`METRICS_SPEC`) and the generated `/config/metrics.token` — edit the spec
there, it survives recreation; override the conf's knobs with
`env/scraper.env` (or flags):

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-scraper -t modbus-scraper \
    --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../scraper
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper    # upstream defaults to modbus-cache:15502 (the image's UPSTREAM env)
docker run --rm -it modbus-scraper bash        # poke around as pvsuite
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper \
    modbus-scraper --upstream 192.168.1.100:502        # any flags via the CMD override
docker run --rm -p 127.0.0.1:9350:9350 \
    --env-file env/scraper.env modbus-scraper   # the peer via the env file (a --upstream flag beats it)
```

Standalone runs stay token-less by default — the compose stack is what
wires the token (`AUTH_TOKEN=file:...`); pass
`-e AUTH_TOKEN=file:/config/metrics.token` by hand to mirror it.

### prometheus (`Dockerfile.prometheus`)

The demo stack's scraper — alpine + the prometheus package, no python.
The context is the `docker/` directory itself:

```bash
cd docker
docker build -t prometheus -f Dockerfile.prometheus .
```

Compose-only by design: it mounts the shared `config` volume (read-only)
for the token, needs `modbus-scraper` on the internal network, and its
entrypoint (`entrypoint-prometheus.sh`) drops root before the exec — see
[The demo stack](#the-demo-stack-compose). The UI serves on the internal
network only — the dashboard's proxy is the way in from the host.

The entrypoint takes three `PROM_*` knobs (ship them in
`env/prometheus.env` — see [the env files](#the-env-files-one-per-tool) —
or `-e` on a plain `docker run`):

- `PROM_RETENTION` — the TSDB retention, a prometheus duration
  (`15d`, `90d`, `1y`, …); the default keeps **90 days** of scrapes on
  the `prometheus-data` volume (prometheus's own default would be 15 days)
- `PROM_LIFECYCLE=on` — the lifecycle API: `POST /-/reload` after editing
  the config, `POST /-/quit` to stop the collector (it sits on the
  internal network only, and it can stop the collector — enable
  deliberately)
- `PROM_ADMIN_API=on` — the admin API (snapshots, delete_series):
  powerful and destructive; keep off unless a runbook needs it

### dashboard (`Dockerfile.dashboard`)

The static single-page app with its stdlib Prometheus proxy — see the
[dashboard](../dashboard/README.md). The bundled `server.conf`
(`/pv-suite/dashboard/server.conf`, the default `--config` target: port
8080) loads from the image; the CMD binds `0.0.0.0` (a published port
needs it) and **the page's bearer token is mandatory beyond loopback
(F21)** — the compose carries the generated `page.token` (the entrypoint
seeds it 0600 into the config volume); a plain run passes `AUTH_TOKEN`.
The volume carries `/config/config.js` (`CONFIG_JS`) — edit it there, it
survives recreation:

```bash
cd docker
docker build -f ../docker/Dockerfile.dashboard -t dashboard \
    --build-context scripts=../docker --build-context common=../common ../dashboard
docker run --rm -p 127.0.0.1:8080:8080 -e AUTH_TOKEN=dev-token dashboard
    # then open http://localhost:8080/?auth=dev-token (the bootstrap sets the cookie)
docker run --rm -it dashboard bash                  # poke around as pvsuite
docker run --rm -p 127.0.0.1:8080:8080 -e AUTH_TOKEN=dev-token -e PROM_URL=http://prometheus:9090 \
    dashboard                                       # the upstream via env (env beats server.conf)
```

The upstream defaults to `http://localhost:9090` (the bundled
`server.conf` leaves `upstream` commented); `PROM_URL` (env) or a
`--upstream` flag override it. In the compose stack the compose sets
`PROM_URL` to the internal `prometheus` service — the dashboard is the
stack's one published surface (`127.0.0.1:8080:8080`).

## The version inside the image

The version reports as `0.4.2` inside the image (no git metadata; a checkout
shows `0.4.2-<short git>`).

## License

The containers (the Dockerfiles, the entrypoint and the compose stack) are
licensed under the **BSD 3-Clause License** — see the repo-root `LICENSE`
file.
