# The pv-suite containers

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

The suite is stdlib-only, so the containers are trivial: `alpine` + `apk add
python3`, no pip, no venv, ~50 MB images. One Dockerfile per Modbus tool —
`Dockerfile.inverter`, `Dockerfile.cache`, `Dockerfile.scraper` — plus a
`compose.yaml` wiring the demo stack. The pattern:

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

All three services share the named `config` volume mounted at `/config`;
each container seeds it with its own bundled defaults on start. `docker
compose exec` sessions bypass the entrypoint and run as root — add
`--user pvsuite` to land as `pvsuite`.

```bash
cd docker
docker compose up -d fake-inverter              # build + serve on 0.0.0.0:5502
docker compose up -d modbus-cache               # + the cache proxy on 0.0.0.0:15502 (upstream: fake-inverter)
docker compose up -d modbus-scraper             # + the exporter on 0.0.0.0:9350 (upstream: modbus-cache)
docker compose exec --user pvsuite fake-inverter fake-cli   # a console session on the control server
docker compose down
```

The poll chain is **fake-inverter → modbus-cache → scraper**: the cache owns
the inverter's single Modbus client and the exporter polls the cache — which
it auto-detects and reports with the `huawei_cache_*` diagnostics metrics
(`device_up 0` / a growing `age_seconds` mean the device is down behind the
cache while the cache keeps serving last-known values).

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
docker run --rm -p 5502:5502 fake-inverter               # serves on 0.0.0.0:5502
docker run --rm -it fake-inverter bash                   # poke around as pvsuite
docker run --rm -p 5502:5502 fake-inverter \
    fake-inverter --profile deye-sg04lp3 --no-battery    # any flags via the CMD override
```

The fake has no file configs yet — its `/config` volume is there for
symmetry with the other two images and for future use.

### modbus-cache (`Dockerfile.cache`)

The caching proxy multiplexing the inverter's single Modbus client — see the
[cache](../cache/README.md). The live configs are `/config/modbus_cache.ini`
and `/config/selection.json` (`MODBUS_CACHE_CONFIG` /
`MODBUS_CACHE_SELECTION`):

```bash
cd docker
docker build -t modbus-cache --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../cache
docker run --rm -p 15502:15502 modbus-cache    # upstream defaults to the fake-inverter service name
docker run --rm -it modbus-cache bash          # poke around as pvsuite
docker run --rm -p 15502:15502 modbus-cache \
    modbus-cache --host 192.168.1.100          # any flags via the CMD override
```

Without `-v` the volume is anonymous (thrown away with `--rm`); name it to
keep the configs: `docker run -v pv-suite-config:/config ...` — the same
named volume under all three tools keeps every config in one place.

### modbus-scraper (`Dockerfile.scraper`)

The Prometheus exporter — see the [scraper](../scrape/README.md). The live
configs are `/config/scraper.ini` and `/config/metrics.json`
(`SCRAPER_CONFIG` / `SCRAPER_METRICS_SPEC`):

```bash
cd docker
docker build -t modbus-scraper --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../scrape
docker run --rm -p 9350:9350 modbus-scraper    # upstream defaults to the modbus-cache service name (port 15502)
docker run --rm -it modbus-scraper bash        # poke around as pvsuite
docker run --rm -p 9350:9350 modbus-scraper \
    modbus-scraper --host 192.168.1.100        # any flags via the CMD override
```

## The version inside the image

The version reports as `0.3.0` inside the image (no git metadata; a checkout
shows `0.3.0-<short git>`).

## License

The containers (the Dockerfiles, the entrypoint and the compose stack) are
licensed under the **BSD 3-Clause License** — see the repo-root `LICENSE`
file.
