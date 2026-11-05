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
| [`profiles/`](profiles/README.md) | — | Shared device profiles (one JSON schema consumed by all three Modbus tools; [the format](profiles/README.md)): `name → register/type/scale` with per-entry descriptions — ships `sun2000`, `deye-sg03lp1`, `deye-sg04lp3` and `deye-sg05lp3`; the tools select what to fetch/scrape via their own files; a linter and a formatter keep them in shape |
| [`common/`](common/README.md) | — | The shared stdlib-only Python package (imported as `common`): version string, audit trail, config plumbing, Modbus wire core |

The tools speak one vocabulary: the fake inverter serves from a profile, the
cache fetches its selection from it, the scraper binds its metrics to it —
and the console tools (`*-ctl`, `*-cli`) share the family pattern (a
JSON-lines control server, a settings registry, an append-only audit trail,
a reconnecting console session).

## The flake

```bash
nix run .#dashboard          # the dashboard (server.py + static page)
nix run .#modbus-scraper -- --host <inverter-lan-ip> --listen 0.0.0.0:9350
nix run .#modbus-cache       # multiplex the inverter's single Modbus client
nix run .#modbus-fake-inverter   # fake inverter for development and testing
```

The flake also exposes the packages (`nix build .#<name>`), an overlay and
NixOS service modules (`services.dashboard`, `services.modbus-scraper`,
`services.modbus-cache`). Each subproject's README documents its own tool.

## Repo layout

```
pv-suite/
├── dashboard/    # the dashboard web UI + proxy server (package + NixOS module)
├── scrape/       # modbus-scraper exporter (package + NixOS module)
├── cache/        # modbus-cache proxy (package + NixOS module)
├── inverter/     # fake inverter + control clients (package, no service module)
├── profiles/     # shared device profiles + the linter/formatter ([the format](profiles/README.md))
├── common/       # the shared Python package (version, audit, config, wire core; [docs](common/README.md))
├── tests/        # the test suites, one or more per Modbus tool
├── scripts/      # release.py — the release orchestrator (bump, verify, tag, push, release)
├── docker/       # one alpine image per Modbus tool + the compose demo stack ([docs](docker/README.md))
├── flake.nix     # the suite entry point
├── docs/         # the family-level docs: the [security audit](docs/AUDIT.md), the
│                 #   [family-wide TODO](docs/TODO.md), the [SBOM](docs/sbom/SBOM.md)
├── CHANGELOG.md  # the release history (the suite versions as one, from common/version.py)
└── LICENSE       # BSD 3-Clause (whole suite)
```

## Testing

Every suite is standalone (stdlib only, scratch ports, self-cleaning) —
run them from the repo root:

```bash
python3 tests/cache-regtest.py        # the cache: the full functional battery
python3 tests/scrape-regtest.py      # the scraper + the fake's machines
python3 tests/cache-stress.py        # the cache: 100 clients / 15 s load
python3 tests/cache-fuzz.py [n]      # the cache: n hostile client frames
python3 tests/scrape-fuzz.py [n]     # the scraper: n hostile HTTP frames
python3 tests/cache-control-fuzz.py  # the cache: hostile JSON on the control server
python3 tests/control-fuzz.py        # the fake inverter: hostile JSON on the control server
```

Every scenario must end with the process under test alive and **zero
tracebacks** in the logs.

## Docker

The containers — one alpine image per Modbus tool plus the compose demo
stack (fake inverter → cache → scraper) — are documented in
[`docker/README.md`](docker/README.md).

## License

The whole suite is licensed under the **BSD 3-Clause License** — see the
`LICENSE` file. The bundled chart library in
`dashboard/src/static/vendor/echarts.min.js` is
[Apache ECharts](https://echarts.apache.org/) 5.5.1, licensed under the
**Apache License 2.0** (© the Apache Software Foundation); the license notice
is preserved in the vendored file.
