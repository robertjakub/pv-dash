# The pv-suite containers

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

The suite is stdlib-only, so the containers are trivial: `alpine` + `apk add
python3`, no pip, no venv, ~50 MB images. One Dockerfile per tool, named
after the tool's daemon — `Dockerfile.modbus-cache`,
`Dockerfile.modbus-fake-inverter`, `Dockerfile.modbus-scraper`,
`Dockerfile.dashboard` — plus `Dockerfile.prometheus` for the demo
stack's collector, and the stack wiring in two compose projects:

- **[demo/](demo/README.md)** — the self-contained demo: the fake inverter
  wired end to end on one `internal: true` network. A starting point to
  read and adapt — not a production recipe.
- **[prod/](prod/README.md)** — the production shape: the same four
  services against real hardware, no fake — see
  [the production stack](#the-production-stack-prod) below.

The images are identical in both — the split is the wiring, not the
artifacts. The pattern:

- an unprivileged **`pvsuite`** user (`adduser -D`, `COPY --chown`); the
  entrypoint runs as root only to seed the config volume and drops to
  `pvsuite` via `su-exec` — the tool never runs as root
- the tools symlinked onto `PATH` (the inverter image: `modbus-fake-inverter`,
  `modbus-fake-cli`; the cache image: `modbus-cache`,
  `modbus-cache-cli`; the scraper image: `modbus-scraper`,
  `modbus-scraper-cli`; the dashboard image:
  `dashboard`, `dashboard-cli`), `bash` for interactive
  runs
- a **HEALTHCHECK** on every image: the Modbus tools answer over their
  unix control socket (`<tool>-cli ping` / `show version` — the check
  runs as root, a trusted peer over SO_PEERCRED, so no token is needed;
  disabling the control plane with `CTL=0` fails the check — and so does
  a live `set control-port off` on a running container, by design; a
  later `set control-port <unix-path>` re-arms it), the
  Prometheus image probes `/-/ready` with busybox wget
- the shared [`profiles/`](../shared/profiles/README.md) JSON files copied
  flat to `/pv-suite/profiles/` (pure data, home `shared/profiles/`; the
  linter/formatter lives in `scripts/gates/profile.py`) — the profile
  resolution finds them relative to the checkout layout
- the **config volume** (`/config`, `VOLUME` + `ENTRYPOINT
  pv-entrypoint`): the entrypoint seeds it with the **required file
  artifacts only** — the generated `metrics.token`, the generated
  `modbus-auth.token`, the JSON specs (`selection.json`, `metrics.json`)
  and the served `config.js`; the bundled conf scripts are NOT copied
  there (each tool loads the image's own conf as the default layer). See
  [env or the config volume?](#env-or-the-config-volume) for the split:
  the env twins (and the per-tool env files) cover the knobs, the volume
  holds the file-shaped artifacts.
- the build context = the subproject; the entrypoint, the shared
  [`common/`](../common/README.md) package and the shared data (the
  profiles among it) ride in as named build
  contexts (`additional_contexts` in the compose, `--build-context` for
  plain docker builds) — common lands at `/pv-suite/common/`, next to each
  tool's `lib/`

## The production stack (prod/)

`prod/compose.yaml` runs the three services against real hardware — the
cache, the scraper, the dashboard (no fake, **no in-stack collector**):
your Prometheus is external and pulls the exporter's `/metrics`:

```bash
cd docker/prod
cp ../env/modbus-cache.env.example ../env/modbus-cache-production.env
$EDITOR ../env/modbus-cache-production.env           # UPSTREAM=192.168.1.100:5502 — the device
docker compose up -d                                # cache + scraper + dashboard
```

Three operator decisions, each called out in the compose file's comments:

- **the device address** — `env/modbus-cache-production.env` is
  **required** here (no `required: false`): the stack refuses to start
  without it, because the image's default `UPSTREAM`
  (`modbus-fake-inverter:5502`) only ever resolves in the demo. Set
  `UPSTREAM=HOST:PORT` to the device.
- **the device's auth** (optional) — if the device or its gateway speaks
  an auth scheme, set `MODBUS_UPSTREAM_AUTH=suite|waveshare` and
  `MODBUS_UPSTREAM_AUTH_KEY` in the same env file: the upstream credential is
  the device's, the env file is its edit surface. (The Waveshare spelling
  is cache-only — the gateway connection password.)
- **your collector's way in** — the exporter's `/metrics` is published
  loopback-only (`127.0.0.1:9350:9350`) for a host-level collector; a
  container collector instead: delete the mapping and attach it to the
  `pv-suite` network. The dashboard's `PROM_URL` (edit in the compose)
  points its `/prom` proxy at your collector.

Everything else ships decided — two loopback ports published (the
dashboard's 8080 + the exporter's 9350), the secrets generated (see
[the secrets story](#the-secrets-story)). The full shape, the topology
diagram and the volume notes: [prod/README.md](prod/README.md).

## The demo stack (demo/)

The demo wires the fake inverter end to end on one `internal: true`
network — the self-contained tour: the same three services, the demo's
own in-stack Prometheus collector, plus the fake as the device. Its
blockquote, usage and topology diagram:
[demo/README.md](demo/README.md).

## The env files (one per tool)

Each image has its own env file, shipped as an example:
`env/modbus-cache.env.example`, `env/modbus-scraper.env.example`,
`env/modbus-fake-inverter.env.example`, `env/dashboard.env.example`,
`env/prometheus.env.example` — `cp env/<tool>.env.example
env/<tool>.env` and edit. The compose stacks
copy-name the files per stack: the demo reads `env/<tool>.env`, prod reads
`env/<tool>-production.env` (the cache's and the scraper's — the cache's
required there), so one checkout runs both stacks without the copies
colliding on knobs like `UPSTREAM`. The names are
**bare env twins** the tool's own docs speak (`UPSTREAM`, `MODBUS_INTERVAL`,
`TTL`, `MODBUS_PROFILE`, `METRICS_PREFIX`, `LOG_LEVEL`, …) — one file per tool,
so no namespacing is needed (the Prometheus file is the exception: its
`PROM_*` knobs belong to `entrypoint-prometheus.sh`, not a pv-suite
tool). Every line starts commented; the defaults live in the image.

The four tool files are **GENERATED** (`scripts/generators/examples.py --check`
gates the drift) from the per-tool registries (`lib/options.json`): the
registry's full env-twin set, grouped by the knob's namespace node, the
sample value the image itself runs (the CMD flag or an ENV where one
pins it — those lines carry the pin note), the compose's environment
pins marked per knob and the secrets' lines empty (`file:<path>` is the
discipline). Edit the registry and re-run the generator — never the
file.

The same file is consumed two ways:

```bash
cd docker
cp env/modbus-cache.env.example env/modbus-cache.env
$EDITOR env/modbus-cache.env                     # UPSTREAM=192.168.1.100:5502

docker run --rm -p 127.0.0.1:15502:15502 \
    --env-file env/modbus-cache.env modbus-cache  # plain docker: --env-file

cd demo && docker compose up -d modbus-cache     # the demo stack: env_file: (required: false)
cd ../prod && docker compose up -d modbus-cache  # the prod stack: env_file: (modbus-cache-production.env, required)
```

Compose reads the service's file via `env_file:` relative to the stack's
own directory (`../env/<tool>.env` in the demo, `../env/<tool>-production.env`
in prod) — in the demo with `required: false` (compose ≥ 2.24; no file =
the image defaults, so the demo runs out of the box), in prod with the
cache's file **required** ([the production
stack](#the-production-stack-prod)). When a file
exists its values ride the tools' resolution (**flag > env > the bundled
conf > built-in defaults**) — an env value overrides the image's bundled
conf script, the same layering a plain checkout has. Compose recreates a
service when its env file changes. The stack-level knobs are compose
level by nature and stay in the compose files: the dashboard's published
port and its `PROM_URL`, the exporter's bearer token and the Modbus
suite key (the `environment:` blocks — environment beats env_file, so
the env files cannot override the stacks' auth story; a plain-docker
`AUTH_TOKEN=file:...` or `MODBUS_AUTH=suite` in the env file is fine for
standalone runs). The fake's simulation envs (`CHAOS`, `MAX_KWP`,
`STRICT`, `TIME`, `TIME_SCALE`) are ordinary env twins — they apply at
start (flag > env > the image's bundled conf) and SIGHUP re-applies
them: retune a running fake with
`docker compose kill -s HUP modbus-fake-inverter`.

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
- **the generated `modbus-auth.token`** — the same story for the Modbus
  plane: the suite handshake's shared key, the same value on both sides
  of each hop
- **`selection.json` and `metrics.json`** — JSON specs, not knobs: the
  `SELECTION`/`METRICS_SPEC` env twins only point at the files; edit them
  in the volume (they seed once, edits survive recreation)
- **`config.js`** — the dashboard's served front-end file (`CONFIG_JS`
  points at it), same story

Prefer the conf file after all? Point the tool at the volume —
`CONFIG=/config/modbus-cache.conf` (env) or a `--config` flag — and edit
the file there; the entrypoint keeps whatever is in the volume. A volume
carrying a legacy seeded conf (`modbus_cache.conf`, `scraper.conf`,
`server.conf` from an older image) is simply no longer loaded.

## The secrets story

**The stacks ship authenticated, both planes** (the audit's F13 closed
for the stacks; the F11 trusted-LAN posture stays the standalone
default):

- **the Modbus hops** — the suite handshake (the PVA1/HMAC-SHA256 crypt
  handshake, `MODBUS_AUTH=suite`): one shared key, generated into the volume as
  `/config/modbus-auth.token` on the first seed (random, 0600, owner
  pvsuite — the same mechanism as the tokens; whichever Modbus container
  seeds first generates, the rest keep). In the demo the fake demands it
  (server), the cache proves it upstream and demands it from its own
  clients; in prod the cache demands it (server) and the scraper proves
  it — the upstream side stays the device's credential (the operator's
  `MODBUS_UPSTREAM_AUTH*` in `env/modbus-cache-production.env`, or none
  for a device without auth). The `environment:` blocks pin scheme +
  `file:` reference;
  opening a hop is a compose edit (an explicit operator act, the F7
  shape). Standalone runs stay auth-less — pass `-e MODBUS_AUTH=suite -e
  MODBUS_AUTH_KEY=file:/config/modbus-auth.token` on a shared named volume to
  mirror the stacks by hand.
- **the metrics hop** — the exporter never serves unauthenticated: the
  compose sets `AUTH_TOKEN=file:/config/metrics.token` (the `file:`
  reference form), the entrypoint generates that file into the volume on
  the first seed (random, 0600, owner pvsuite — bundled `*.token`
  defaults are placeholders that are never copied; the token survives
  container recreation with the volume). The Prometheus service reads
  its own copy of the same file (`Dockerfile.prometheus` +
  `entrypoint-prometheus.sh`: root copies `/config/metrics.token` to
  `/etc/prometheus/metrics.token`, 0600, then drops to the unprivileged
  `prometheus` user via su-exec) and scrapes with
  `authorization: credentials_file` (`prometheus.yml`).
- **the dashboard's page** — token'd the same way (F21): the entrypoint
  materializes a random 0600 `/config/page.token` on the first seed.

Read the tokens from the inside:

```bash
docker compose exec modbus-scraper cat /config/metrics.token
TOKEN=$(docker compose exec modbus-scraper cat /config/metrics.token)
docker compose exec modbus-scraper wget -qO- --header "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:9350/metrics
```

A token-less request gets a 401 with a `WWW-Authenticate: Bearer` challenge.
Give Prometheus for another stack the same value as
`authorization.credentials_file` (an owner-only file, F12) — or attach the
collector container to the stack's network and scrape
`modbus-scraper:9350` like the demo's in-stack service does.

The poll chain is **device → modbus-cache → scraper → your collector**:
the cache owns the device's single Modbus client and the exporter polls
the cache — which it auto-detects and reports with the `scraper_cache_*`
diagnostics metrics (`device_up 0` / a growing `age_seconds` mean the device
is down behind the cache while the cache keeps serving last-known values).

## The images, one by one

### modbus-fake-inverter (`Dockerfile.modbus-fake-inverter`)

The demo device for development and testing — see the
[fake inverter](../apps/inverter/README.md):

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-fake-inverter -t modbus-fake-inverter \
    --build-context shared=../shared \
    --build-context scripts=../docker --build-context common=../common ../inverter
docker run --rm -p 127.0.0.1:5502:5502 modbus-fake-inverter   # loopback-published, serves on 0.0.0.0:5502 in the container
docker run --rm -it modbus-fake-inverter bash              # poke around as pvsuite
docker run --rm -p 127.0.0.1:5502:5502 modbus-fake-inverter \
    modbus-fake-inverter --modbus-profile deye-sg04lp3 --timezone local    # any flags via the CMD override
```

The bundled conf (`/pv-suite/inverter/modbus-fake-inverter.conf`, the default
`--config` target) loads from the image; its `/config` volume carries no
conf — just the generated suite key (the compose stacks point the
server-side auth at it) — and stays open for future use.

### modbus-cache (`Dockerfile.modbus-cache`)

The caching proxy multiplexing the inverter's single Modbus client — see the
[cache](../apps/cache/README.md). The bundled conf
(`/pv-suite/cache/modbus-cache.conf`, the default `--config` target) loads
from the image; the volume carries `/config/selection.json` (`SELECTION`)
— edit it there, it survives recreation; override the conf's knobs with
`env/modbus-cache.env` (or flags):

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-cache -t modbus-cache \
    --build-context shared=../shared \
    --build-context scripts=../docker --build-context common=../common ../cache
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache    # upstream defaults to modbus-fake-inverter:5502 (the image's UPSTREAM env)
docker run --rm -it modbus-cache bash          # poke around as pvsuite
docker run --rm -p 127.0.0.1:15502:15502 modbus-cache \
    modbus-cache --upstream 192.168.1.100:5502          # any flags via the CMD override
docker run --rm -p 127.0.0.1:15502:15502 \
    --env-file env/modbus-cache.env modbus-cache  # the peer via the env file (a --upstream flag beats it)
```

Without `-v` the volume is anonymous (thrown away with `--rm`); name it to
keep the configs: `docker run -v pv-suite-config:/config ...` — the same
named volume under all three tools keeps every config in one place.

### modbus-scraper (`Dockerfile.modbus-scraper`)

The Prometheus exporter — see the [scraper](../apps/scraper/README.md). The
bundled conf (`/pv-suite/scraper/modbus-scraper.conf`, the default `--config`
target) loads from the image; the volume carries `/config/metrics.json`
(`METRICS_SPEC`) and the generated `/config/metrics.token` — edit the spec
there, it survives recreation; override the conf's knobs with
`env/modbus-scraper.env` (or flags):

```bash
cd docker
docker build -f ../docker/Dockerfile.modbus-scraper -t modbus-scraper \
    --build-context shared=../shared \
    --build-context scripts=../docker --build-context common=../common ../scraper
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper    # upstream defaults to modbus-cache:15502 (the image's UPSTREAM env)
docker run --rm -it modbus-scraper bash        # poke around as pvsuite
docker run --rm -p 127.0.0.1:9350:9350 modbus-scraper \
    modbus-scraper --upstream 192.168.1.100:502        # any flags via the CMD override
docker run --rm -p 127.0.0.1:9350:9350 \
    --env-file env/modbus-scraper.env modbus-scraper  # the peer via the env file (a --upstream flag beats it)
```

Standalone runs stay token-less and auth-less by default — the compose
stacks are what wire the secrets (`AUTH_TOKEN=file:...`,
`MODBUS_AUTH=suite`); pass the env pairs by hand to mirror them.

### prometheus (`Dockerfile.prometheus`)

The demo stack's collector — alpine + the prometheus package, no
python. Production brings its own collector (the prod stack ships
none) — this image is the reference wiring for pulling the exporter's
`/metrics` with the bearer token. The context is the `docker/`
directory itself; the **alert rules pack** rides in as the `alerts`
build context (the family's `extras/alerts/` tree, one file per watched
exporter, baked to `/etc/prometheus/alerts/` — the pack's
`rule_files:` entry is in `prometheus.yml`):

```bash
cd docker
docker build -t prometheus -f Dockerfile.prometheus \
    --build-context alerts=../extras/alerts .
```

Compose-only by design: it mounts the shared `config` volume (read-only)
for the token, needs `modbus-scraper` on the network, and its entrypoint
(`entrypoint-prometheus.sh`) drops root before the exec — see
[the secrets story](#the-secrets-story). The UI serves on the compose
network only — the dashboard's proxy is the way in from the host.

The entrypoint takes three `PROM_*` knobs (ship them in
`env/prometheus.env` — see [the env files](#the-env-files-one-per-tool) —
or `-e` on a plain `docker run`):

- `PROM_RETENTION` — the TSDB retention, a prometheus duration
  (`15d`, `90d`, `1y`, …); the default keeps **90 days** of scrapes on
  the `prometheus-data` volume (prometheus's own default would be 15 days)
- `PROM_LIFECYCLE=on` — the lifecycle API: `POST /-/reload` after editing
  the config, `POST /-/quit` to stop the collector (it sits on the
  compose network only, and it can stop the collector — enable
  deliberately)
- `PROM_ADMIN_API=on` — the admin API (snapshots, delete_series):
  powerful and destructive; keep off unless a runbook needs it

### dashboard (`Dockerfile.dashboard`)

The static single-page app with its stdlib Prometheus proxy — see the
[dashboard](../apps/dashboard/README.md). The bundled `dashboard.conf`
(`/pv-suite/dashboard/dashboard.conf`, the default `--config` target: port
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
    dashboard                                       # the upstream via env (env beats dashboard.conf)
```

The upstream defaults to `http://localhost:9090` (the bundled
`dashboard.conf` leaves `upstream` commented); `PROM_URL` (env) or a
`--upstream` flag override it. In the compose stacks the compose sets
`PROM_URL=http://prometheus:9090` (the in-stack collector) — the
dashboard is the stack's one human surface, published loopback-only.

## The version inside the image

The version reports as `0.5.0` inside the image (no git metadata; a checkout
shows `0.5.0-<short git>`).

## License

The containers (the Dockerfiles, the entrypoints and the compose stacks) are
licensed under the **BSD 3-Clause License** — see the repo-root `LICENSE`
file.
