# pv-suite

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A family of dependency-free (Python stdlib only) home-PV tools around a
Huawei SUN2000 inverter, packaged together as one Nix flake:

| Subproject | Package / app | What it is |
|---|---|---|
| [`dashboard/`](dashboard/README.md) | `dashboard` | Single-page energy-flow dashboard fed by Prometheus, with a bundled stdlib-only proxy server and a NixOS module |
| [`scrape/`](scrape/README.md) | `modbus-scraper` | Huawei SUN2000 Prometheus exporter (Modbus TCP, stdlib only) with a NixOS module |
| [`cache/`](cache/README.md) | `modbus-cache` | **Experimental** Modbus TCP caching proxy that multiplexes the inverter's single client connection |
| [`inverter/`](inverter/README.md) | `modbus-fake-inverter` | **Experimental** fake inverter + battery + smart meter for testing the stack without hardware — with a runtime control server, console-style CLI and chaos injection |
| [`profiles/`](profiles/) | — | Shared device profiles (one JSON schema consumed by all three Modbus tools; [the format](profiles/README.md)): `name → register/type/scale` with per-entry descriptions — ships `sun2000`, `deye-sg03lp1`, `deye-sg04lp3` and `deye-sg05lp3`; the tools select what to fetch/scrape via their own files |

## The flake

```bash
nix run .#dashboard          # the dashboard (server.py + static page)
nix run .#modbus-scraper -- --host <inverter-lan-ip> --listen 0.0.0.0:9350
nix run .#modbus-cache          # multiplex the inverter's single Modbus client
nix run .#modbus-fake-inverter  # fake inverter for development and testing
```

The flake also exposes the packages (`nix build .#<name>`), an overlay and
NixOS service modules (`services.dashboard`, `services.modbus-scraper`,
`services.modbus-cache`). Each subproject's README documents its own tool.

## Repo layout

```
pv-suite/
├── dashboard/    # the dashboard web UI + proxy server (package + NixOS module)
├── scrape/       # modbus-scraper exporter (package + NixOS module + tests)
├── cache/        # modbus-cache proxy (package + NixOS module + tests)
├── inverter/     # fake inverter, control clients (package, tests)
├── profiles/     # shared inverter profiles ([the format](profiles/README.md))
├── tests/        # the test suites, one per Modbus tool
├── flake.nix     # the suite entry point
├── docker/       # Dockerfile.inverter + compose.yaml (the fake-inverter image)
└── LICENSE       # BSD 3-Clause (whole suite)
```

## Docker

The suite is stdlib-only, so the containers are trivial: `alpine` + `apk add
python3`, no pip, no venv, ~50 MB images. `docker/` holds the files
(`Dockerfile.inverter`, `compose.yaml`) — the pattern:

- an unprivileged **`pvsuite`** user (`adduser -D`, `COPY --chown`, `USER`)
- the three inverter tools symlinked onto `PATH`
  (`fake-inverter`, `fake-ctl`, `fake-cli`), `bash` for interactive runs
- the shared [`profiles/`](profiles/README.md) directory copied alongside —
  the profile resolution finds it relative to the checkout layout
- the build context = `inverter/`, the profiles ride in as a named
  build context (`additional_contexts` in the compose, `--build-context`
  for plain docker builds)

```bash
cd docker
docker compose up -d fake-inverter              # build + serve on 0.0.0.0:5502
docker compose exec fake-inverter fake-cli      # a console session on the control server
docker compose down
```

Or without compose:

```bash
cd docker
docker build -t fake-inverter --build-context profiles=../profiles ../inverter
docker run --rm -p 5502:5502 fake-inverter
docker run --rm -it fake-inverter bash          # poke around as pvsuite
```

The same pattern extends to the scraper and the cache: swap the `COPY`/`CMD`
lines for their `src/` trees. The version reports as `0.2.0` inside the
image (no git metadata; a checkout shows `0.2.0-<short git>`).

## License

The whole suite is licensed under the **BSD 3-Clause License** — see the
`LICENSE` file. The bundled chart library in
`dashboard/src/static/vendor/echarts.min.js` is
[Apache ECharts](https://echarts.apache.org/) 5.5.1, licensed under the
**Apache License 2.0** (© the Apache Software Foundation); the license notice
is preserved in the vendored file.
