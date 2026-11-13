# The pv-suite containers

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.
>
> **Verification needs a host with docker.** This tree's dev machine runs
> no daemon: the Dockerfiles, the entrypoints and the two compose stacks
> are static-checked (the generators' `--check` gates) and reviewed, never
> built or run where they are edited — verify changes here (build the
> images, bring both stacks up, watch the healthchecks) on a docker host;
> the suites cannot catch a broken compose.

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
  entrypoint runs as root only to seed the config volume, stage the
  compose secrets (0600 `pvsuite` copies under `/run/pv-secrets/`) and
  drops to `pvsuite` via `su-exec` — the tool never runs as root
- the tools symlinked onto `PATH` (the inverter image: `modbus-fake-inverter`,
  `modbus-fake-cli`; the cache image: `modbus-cache`,
  `modbus-cache-cli`; the scraper image: `modbus-scraper`,
  `modbus-scraper-cli`; the dashboard image:
  `dashboard`, `dashboard-cli`), `bash` for interactive
  runs; the `*-cli` names are symlinks to the family dispatcher
  (`pvsuite-cli.py`, copied to `/pv-suite` via the `cli` build context) —
  the client comes from the invoked name, `pvsuite-cli <tool>` spells the
  same thing when the plain script is on `PATH`
- a **HEALTHCHECK** on every image: the Modbus tools answer over their
  unix control socket (`<tool>-cli ping` / `show version` — the check
  runs as root, a trusted peer over SO_PEERCRED, so no token is needed;
  disabling the control plane with `CTL=0` fails the check — and so does
  a live `set control-port off` on a running container, by design; a
  later `set control-port <unix-path>` re-arms it), the
  Prometheus image probes `/-/ready` with busybox wget
- the shared [`profiles/`](../shared/profiles/README.md) JSON files copied
  flat to `/pv-suite/profiles/` (pure data, home `shared/profiles/`; the
  linter/formatter lives in `dev/gates/profile.py`) — the profile
  resolution finds them relative to the checkout layout
- the **config volume** (`/config`, `VOLUME` + `ENTRYPOINT
  pv-entrypoint`): the entrypoint seeds it with the **required file
  artifacts only** — the JSON specs (`selection.json`, `metrics.json`)
  and the served `config.js`; the bundled conf scripts are NOT copied
  there (each tool loads the image's own conf as the default layer).
  The secrets never touch the volume — the stacks mount them as
  compose secrets ([the secrets story](#the-secrets-story)). See
  [env or the config volume?](#env-or-the-config-volume) for the split:
  the env twins (and the per-tool env files) cover the knobs, the volume
  holds the file-shaped non-secrets.
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
sh ../gen-secrets.sh secrets                         # the three secrets, 0600
cp ../env/modbus-cache.env.example ../env/modbus-cache-production.env
$EDITOR ../env/modbus-cache-production.env           # UPSTREAM=192.168.1.100:5502 — the device
docker compose up -d                                # cache + scraper + dashboard
```

Three operator decisions, each called out in the compose file's comments:

- **the stack's secrets** — `sh ../gen-secrets.sh secrets` generates the
  three (the suite key + the two bearer tokens) into `prod/secrets/`
  (gitignored); the stack refuses to start without them — they are
  compose secrets ([the secrets story](#the-secrets-story)).
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
dashboard's 8080 + the exporter's 9350), the secrets operator-supplied
(see [the secrets story](#the-secrets-story)). The full shape, the topology
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

The four tool files are **GENERATED** (`dev/generators/examples.py --check`
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

- **`selection.json` and `metrics.json`** — JSON specs, not knobs: the
  `SELECTION`/`METRICS_SPEC` env twins only point at the files; edit them
  in the volume (they seed once, edits survive recreation)
- **`config.js`** — the dashboard's served front-end file (`CONFIG_JS`
  points at it), same story

The secrets are NOT in the volume — they lived there once (the
entrypoint generated the tokens on the first seed) and the audit's F17
moved them out: a named volume holds plaintext for every container and
outlives them, which is no home for a credential. The stacks mount the
operator's secret files as compose secrets instead —
[the secrets story](#the-secrets-story) carries the recipe.

Prefer the conf file after all? Point the tool at the volume —
`CONFIG=/config/modbus-cache.conf` (env) or a `--config` flag — and edit
the file there; the entrypoint keeps whatever is in the volume. A volume
carrying a legacy seeded conf (`modbus_cache.conf`, `scraper.conf`,
`server.conf` from an older image) is simply no longer loaded.

## The secrets story

**The stacks ship authenticated, both planes** (the audit's F13 closed
for the stacks; the F11 trusted-LAN posture stays the standalone
default). **The secrets are the operator's** — generated once per stack
by `docker/gen-secrets.sh`, mounted as compose secrets, never in the
config volume (the audit's F17 closed: the volume holds the non-secret
artifacts only; whoever can read a compose volume is root-equivalent,
but a credential should not sit in a long-lived plaintext store for
every mounted container to see):

```bash
sh docker/gen-secrets.sh docker/demo/secrets    # the demo stack's three
sh docker/gen-secrets.sh docker/prod/secrets    # the prod stack's three
```

Three files per stack, 0600 (32 random bytes, hex): **`modbus-auth`**
(the suite key), **`metrics-token`** (the exporter's bearer),
**`page-token`** (the dashboard's page bearer). The dirs are
gitignored. `docker compose up` refuses to start while one is missing
(the `secrets:` `file:` sources are required), and a tool handed an
unreadable file refuses in its usual fail-fast way (F12).

- **the mount + the staging** — compose mounts each service's secrets
  read-only at `/run/secrets/<name>`; non-swarm compose keeps the host
  file's owner, so the entrypoint (root only for setup, as ever) stages
  a private copy: `/run/pv-secrets/<name>`, 0600, owner pvsuite — the
  path the `file:` env pins speak
  (`MODBUS_AUTH_KEY=file:/run/pv-secrets/modbus-auth`,
  `AUTH_TOKEN=file:/run/pv-secrets/metrics-token|page-token`). The
  staging is ephemeral — it dies with the container and the host files
  never change owner.
- **the Modbus hops** — the suite handshake (the PVA1/HMAC-SHA256 crypt
  handshake, `MODBUS_AUTH=suite`): one shared key, the operator's
  `modbus-auth` secret, the same value on both sides of each hop. In the
  demo the fake demands it (server), the cache proves it upstream and
  demands it from its own clients; in prod the cache demands it (server)
  and the scraper proves it — the upstream side stays the device's
  credential (the operator's `MODBUS_UPSTREAM_AUTH*` in
  `env/modbus-cache-production.env`, or none for a device without
  auth). The `environment:` blocks pin scheme + `file:` reference;
  opening a hop is a compose edit (an explicit operator act, the F7
  shape). Standalone runs stay auth-less — pass `-e MODBUS_AUTH=suite
  -e MODBUS_AUTH_KEY=file:<your key file>` to mirror the stacks by hand.
- **the metrics hop** — the exporter never serves unauthenticated: the
  compose sets `AUTH_TOKEN=file:/run/pv-secrets/metrics-token` (the
  `file:` reference form). The Prometheus service reads the same secret
  (`Dockerfile.prometheus` + `entrypoint-prometheus.sh`: root copies
  `/run/secrets/metrics-token` to `/etc/prometheus/metrics.token`,
  0600, then drops to the unprivileged `prometheus` user via su-exec)
  and scrapes with `authorization: credentials_file` (`prometheus.yml`).
- **the dashboard's page** — token'd the same way (F21): the operator's
  `page-token` secret, staged 0600 for the server.
- **rotation** — delete the secret file, re-run `gen-secrets.sh`,
  recreate the services (`docker compose up -d --force-recreate`); the
  collector's copy (`authorization.credentials_file`) follows the same
  step. A running container keeps its staged copy until recreated.

Read the tokens from the host (the secrets are host files), then probe:

```bash
cat docker/demo/secrets/metrics-token
TOKEN=$(cat docker/demo/secrets/metrics-token)
docker compose exec modbus-scraper wget -qO- --header "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:9350/metrics
```

A token-less request gets a 401 with a `WWW-Authenticate: Bearer` challenge.
Give Prometheus for another stack the same value as
`authorization.credentials_file` (an owner-only file, F12) — or attach the
collector container to the stack's network and scrape
`modbus-scraper:9350` like the demo's in-stack service does.

Plain `docker run` (no compose): bind-mount the secret and pass the
`file:` reference —
`docker run -v "$PWD/secrets:/secrets:ro" -e AUTH_TOKEN=file:/secrets/metrics-token ...`
— with the one honest line: the bind mount keeps the host owner, so the
file must be readable by the container's `pvsuite` uid (make it 0444, or
chown it to uid 1000); the compose path (the entrypoint's staging) is
the tidy spelling.

**The config volume's trust model + the re-sync** (the other half of
F17): the volume holds live config in plaintext — the JSON specs and
`config.js`, non-secrets; anyone who can read the volume is
root-equivalent anyway. Seeding happens **once per file** — existing
files are never refreshed from the image (edits survive recreation; a
bundled-artifact fix only reaches an existing volume after a re-sync).
The re-syncs: the gentle one — delete the one stale file and restart
(`docker compose exec <service> rm /config/<file> && docker compose
restart <service>`) — or the full one, `docker compose down -v`, which
**in the demo also wipes `prometheus-data`** (the scrape history): the
per-file rm is the default advice. The NixOS deployment
([nixos/README.md](../nixos/README.md)) is the LoadCredential-shaped
sibling: systemd hands the units owner-only secret files and no volume
is involved.

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
required artifacts — nothing seeds there for the fake (the compose stacks
mount its server-side auth as a secret) — and stays open for future use.

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
(`METRICS_SPEC`) — edit the spec
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

Compose-only by design: it mounts the stack's `metrics-token` compose
secret (the token it scrapes with), needs `modbus-scraper` on the
network, and its entrypoint
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
(F21)** — the compose carries the operator's `page-token` secret (a
compose secret the entrypoint stages 0600); a plain run passes
`AUTH_TOKEN`.
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

The version reports as `0.5.1` inside the image (no git metadata; a checkout
shows `0.5.1-<short git>`).

## License

The containers (the Dockerfiles, the entrypoints and the compose stacks) are
licensed under the **BSD 3-Clause License** — see the repo-root `LICENSE`
file.
