# pv-suite

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A family of dependency-free (Python stdlib only) home-PV tools around a
Modbus TCP inverter — the shipped profiles cover the Huawei SUN2000 and
the Deye hybrids — packaged together as one Nix flake:

| Subproject | Package / app | What it is |
|---|---|---|
| [`dashboard/`](dashboard/README.md) | `dashboard` | Single-page energy-flow dashboard fed by Prometheus, with a bundled stdlib-only proxy server and a NixOS module |
| [`scraper/`](scraper/README.md) | `modbus-scraper` | Prometheus exporter for a Modbus TCP inverter (stdlib only) with a NixOS module |
| [`cache/`](cache/README.md) | `modbus-cache` | **Experimental** Modbus TCP caching proxy that multiplexes the inverter's single client connection |
| [`inverter/`](inverter/README.md) | `modbus-fake-inverter` | **Experimental** fake inverter + battery + smart meter for testing the stack without hardware — with a runtime control server, console-style CLI and chaos injection |
| [`profiles/`](profiles/README.md) | — | Shared device profiles (one JSON schema consumed by all three Modbus tools; [the format](profiles/README.md)): `name → register/type/scale` with per-entry descriptions — ships `sun2000`, `deye-sg03lp1`, `deye-sg04lp3` and `deye-sg05lp3`; a linter and a formatter keep them in shape |
| [`examples/`](examples/README.md) | — | The shared sample file the tools' `file:` acl gates point at — `acl-ip-prefix.json`, the ip-prefix connect policy every tool reads ([docs/ACL.md](docs/ACL.md)) |
| [`schema/`](schema/README.md) | — | The shared JSON Schemas (draft 2020-12) — `acl-ip-prefix.schema.json`, the standalone acl file's schema (the loader stays the strict word) |
| [`common/`](common/README.md) | — | The shared stdlib-only Python package (imported as `common`): the option registry (one knob, one source), the signed wire + RBAC, the audit trail, the config plumbing, the Modbus wire core, the man-page builder |

The tools speak one vocabulary: the fake inverter serves from a profile, the
cache fetches its selection from it, the scraper binds its metrics to it —
and the console tools (`*-ctl`, `*-cli`) share the family pattern (a
JSON-lines control server, a settings registry, an append-only audit trail,
a reconnecting console session — TAB/`?` complete and describe every word,
the registry's hierarchy nodes file the listings, the non-value reply lines
ride the `% ` prefix). Every knob of the four daemons, side by
side — name, the live `set` command, who has it: [OPTIONS.md](docs/OPTIONS.md)
(generated from the option registries).

## The flake

```bash
nix run .#dashboard          # the dashboard (bin/dashboard.py + static page)
nix run .#modbus-scraper -- --upstream <inverter-lan-ip>:502 --listen 0.0.0.0:9350
nix run .#modbus-cache       # multiplex the inverter's single Modbus client
nix run .#modbus-fake-inverter   # fake inverter for development and testing
```

The flake also exposes the packages (`nix build .#<name>`), an overlay and
the NixOS service modules (`services.dashboard`, `services.modbus-scraper`,
`services.modbus-cache`). **[docs/NIXOS.md](docs/NIXOS.md) is the one Nix
reference** — the modules, their option maps, the secrets discipline
(`LoadCredential`), the reload/restart story and the hardening check.

## Repo layout

```
pv-suite/
├── dashboard/    # the dashboard web UI + proxy server (package + NixOS module)
├── scraper/      # modbus-scraper exporter (package + NixOS module)
├── cache/        # modbus-cache proxy (package + NixOS module)
├── inverter/     # fake inverter + control clients (package, no service module)
├── profiles/     # shared device profiles + the linter/formatter ([the format](profiles/README.md))
├── common/       # the shared Python package (version, audit, config, wire core; [docs](common/README.md))
├── tests/        # the test suites, one or more per Modbus tool
├── scripts/      # the registry gates + editors (check/lint/gen/edit_options, set_group/set_live), gen_man.py, gen_sbom.py, release.py, audit_verify.py
├── docker/       # one alpine image per Modbus tool; the compose stacks:
│                 #   demo/ + prod/ ([docs](docker/README.md))
├── flake.nix     # the suite entry point
├── docs/         # the family-level docs: the [Nix reference](docs/NIXOS.md), the
│                 #   [security audit](docs/AUDIT.md), the
│                 #   [Modbus protocol reference](docs/MODBUS.md), the
│                 #   [ACL map](docs/ACL.md) (who may connect, whose writes forward,
│                 #   which registers a write may touch — family-wide), the
│                 #   [family-wide TODO](docs/TODO.md) (every open item, one file — the
│                 #   per-tool TODOs keep the Done history), the [SBOM](docs/sbom/SBOM.md),
│                 #   the [release-history archive](docs/CHANGELOG.md)
├── CHANGELOG.md  # Unreleased + the current release (the history lives in docs/CHANGELOG.md)
└── LICENSE       # BSD 3-Clause (whole suite)
```

## Testing

Every suite is standalone (stdlib only, scratch ports, self-cleaning) —
run them from the repo root:

```bash
python3 tests/cache-regtest.py        # the cache: the full functional battery
python3 tests/inverter-regtest.py    # the fake: the F11/F13 surface (client caps, timeouts, per-IP, the count gate)
python3 tests/scrape-regtest.py      # the scraper + the fake's machines
python3 tests/audit-chain.py         # the audit trails' hash chains + scripts/audit_verify.py
python3 tests/cache-stress.py        # the cache: 100 clients / 15 s load
python3 tests/cache-fuzz.py [n]      # the cache: n hostile client frames
python3 tests/scrape-fuzz.py [n]     # the scraper: n hostile HTTP frames
python3 tests/cache-control-fuzz.py  # the cache: hostile JSON on the control server
python3 tests/control-fuzz.py        # the fake inverter: hostile JSON on the control server
python3 tests/dashboard-control-fuzz.py  # the dashboard: hostile JSON on the control server
```

Every scenario must end with the process under test alive and **zero
tracebacks** in the logs.

## Docker

The containers — one alpine image per Modbus tool, plus the two compose
stacks: `docker/demo` (the fake inverter end to end, internal-network
only, nothing published on the host) and `docker/prod` (the production
shape: the three services against real hardware, no fake, your own
external collector) — are
documented in [`docker/README.md`](docker/README.md), the demo's
topology diagram included. Both stacks ship authenticated: the Modbus
hops prove a shared suite key (the PVA1/HMAC handshake, generated into
the config volume), the exporter's `/metrics` and the dashboard's page
ride generated bearer tokens. Every
`/metrics` surface ships with the caps (`--metrics-max-clients`,
`--metrics-client-timeout`, `--metrics-max-conn-per-ip`; the scraper's own
are `--max-clients`/`--client-timeout`/`--max-conn-per-ip`), every HTTP
surface refuses a non-loopback bind without a token (the F13 shape — the
scraper's refusal is the family's golden master; the dashboard's page
rides it too, F21), and the audit trails
carry a per-writer hash chain verified by `scripts/audit_verify.py` (F10).

## License

The whole suite is licensed under the **BSD 3-Clause License** — see the
`LICENSE` file. The bundled chart library in
`dashboard/static/vendor/echarts.min.js` is
[Apache ECharts](https://echarts.apache.org/) 5.5.1, licensed under the
**Apache License 2.0** (© the Apache Software Foundation); the license notice
is preserved in the vendored file.
