# pv-suite

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A family of dependency-free (Python stdlib only) home-PV tools around a
Modbus TCP inverter — the shipped profiles cover the Huawei SUN2000 and
the Deye hybrids — packaged together as one Nix flake:

| Subproject | Package / app | What it is |
|---|---|---|
| [`apps/dashboard/`](apps/dashboard/README.md) | `dashboard` | Single-page energy-flow dashboard fed by Prometheus, with a bundled stdlib-only proxy server and a NixOS module |
| [`apps/scraper/`](apps/scraper/README.md) | `modbus-scraper` | Prometheus exporter for a Modbus TCP inverter (stdlib only) with a NixOS module |
| [`apps/cache/`](apps/cache/README.md) | `modbus-cache` | **Experimental** Modbus TCP caching proxy that multiplexes the inverter's single client connection |
| [`apps/inverter/`](apps/inverter/README.md) | `modbus-fake-inverter` | **Experimental** fake inverter + battery + smart meter for testing the stack without hardware — with a runtime control server, console-style CLI and chaos injection |
| [`extras/`](extras/README.md) | — | The operator-side packs nothing in the suite loads: the alert rules (`alerts/`, one file per watched exporter), the shared sample files the tools' `file:` acl gates point at (`examples/` — `acl-ip-prefix.json`, [docs/specs/ACL.md](docs/specs/ACL.md)) and the Graylog content pack (`graylog/`) |
| [`shared/`](shared/README.md) | — | The family's shared data, outside every package — the device profiles ([`shared/profiles/`](shared/profiles/README.md), one JSON schema consumed by all three Modbus tools: `name → register/type/scale` with per-entry descriptions; ships `sun2000`, `sun2000_full`, `demo-fc4`, `deye-sg03lp1`, `deye-sg04lp3` and `deye-sg05lp3`, a linter and a formatter keep them in shape), `texts.json` (the static texts `common/render/texts.py`'s `T()` reads) and [`shared/schema/`](shared/schema/README.md) (the shared JSON Schemas, draft 2020-12 — `acl-ip-prefix.schema.json`, the standalone acl file's schema (the loader stays the strict word)) |
| [`common/`](common/README.md) | — | The shared stdlib-only Python package (imported as `common`), six functional subpackages: `render/` (texts, man pages), `runtime/` (daemon ladder, audit, version), `settings/` (the option registry — one knob, one source — config plumbing, dumps), `wire/` (the signed wire + RBAC, both ctl/cli ends), `serve/` (the gates + metrics skeleton), `modbus/` (the wire core) |

The tools speak one vocabulary: the fake inverter serves from a profile, the
cache fetches its selection from it, the scraper binds its metrics to it —
and the client tool (`*-cli`: one-shot words, piped batch, the console) shares the family pattern (a
JSON-lines control server, a settings registry, an append-only audit trail,
a reconnecting console session — TAB/`?` complete and describe every word,
the registry's hierarchy nodes file the listings, the non-value reply lines
ride the `% ` prefix). Every knob lives in its registry
(`apps/<tool>/lib/options.json`); the per-tool [MANUAL.md](apps/cache/MANUAL.md)
tables render it (generated, `--check`-gated), and
`python3 scripts/list_options.py` is the cross-tool census on demand.

## The flake

```bash
nix run .#dashboard          # the dashboard (bin/dashboard.py + static page)
nix run .#modbus-scraper -- --upstream <inverter-lan-ip>:502 --listen 0.0.0.0:9350
nix run .#modbus-cache       # multiplex the inverter's single Modbus client
nix run .#modbus-fake-inverter   # fake inverter for development and testing
```

The flake also exposes the packages (`nix build .#<name>`), an overlay and
the NixOS service modules (`services.dashboard`, `services.modbus-scraper`,
`services.modbus-cache`). **[nixos/README.md](nixos/README.md) is the one Nix
reference** — the modules, their option maps, the secrets discipline
(`LoadCredential`), the reload/restart story and the hardening check.

## Repo layout

```
pv-suite/
├── apps/          # the four tools — one self-contained dir each:
│   ├── dashboard/  #   the dashboard web UI + proxy server
│   ├── scraper/    #   modbus-scraper exporter
│   ├── cache/      #   modbus-cache proxy
│   └── inverter/   #   fake inverter + control clients (test/demo tool)
├── nixos/        # the Nix tree: the packages (pkgs/<tool>/), the service
│                 #   modules (modules/<tool>.nix) and the [Nix reference](nixos/README.md)
├── shared/       # the family's shared data: profiles/, schema/, suite/ ([docs](shared/README.md))
├── common/       # the shared Python package — render/ runtime/ settings/ wire/ serve/ modbus/ ([docs](common/README.md))
├── tests/        # the battery runner (tests/battery/ behind the
│                 #   tests/battery/battery.py runner) + the suites, one or more per Modbus tool
├── scripts/      # the tooling, filed by role: editor/ (the registry
│                 #   editor + its curses primitives), family_drift.py,
│                 #   release.py, list_options.py, options_compare.py
│                 #   (the three compare lenses)
│   ├── gates/    # everything rc-1-on-red: the lints (acl/options/readmes/
│   │             #   texts/links/profile) + check_options/validate_json/audit_verify
│   ├── lib/      # the scripts' common lib (the loaders, the registry, the tree-walk, emit)
│   └── generators/  # the four generators: man/manual/examples/sbom
├── docker/       # one alpine image per tool; the compose stacks:
│                 #   demo/ + prod/ ([docs](docker/README.md))
├── extras/       # the operator-side packs: alerts/, examples/, graylog/ ([docs](extras/README.md))
├── flake.nix     # the suite entry point
├── docs/         # the family-level docs, filed by grain in the
│                 #   [design doc](docs/DESIGN.md) (the shape + the docs redo): the
│                 #   [security doc](docs/SECURITY.md), the
│                 #   [Modbus protocol reference](docs/specs/MODBUS.md), the
│                 #   [ACL map](docs/specs/ACL.md), the
│                 #   [family-wide TODO](docs/TODO.md) (every open item — the one-product
│                 #   sweep rides as its section), the
│                 #   [SBOM](docs/sbom/SBOM.md) and the history home
│                 #   ([docs/history/](docs/history) — the audit/changelog/drift/unify
│                 #   archives behind the current halves)
├── CHANGELOG.md  # Unreleased + the current release (the history lives in docs/history/CHANGELOG.md)
└── LICENSE       # BSD 3-Clause (whole suite)
```

## Testing

The suites always run through the battery — `tests/battery/battery.py` owns the
run dir (the suites' /tmp scratch rewrites into it), the port-space slot
(concurrent batteries take disjoint port spaces), the daemon reaping
between suites and the tally; a suite run outside it refuses (the marker
env `PV_RUN_DIR` — the standalone runs share /tmp scratch and collide
across sessions). The release verification and the CI matrix set the same
marker for their legs.

```bash
tests/battery/battery.py                    # the commit loop: the fast set, the fuzz budgets at 100 (~3 min)
tests/battery/battery.py quick              # all ten, the fuzz budgets at 300 (~3 min) — the pre-push loop
tests/battery/battery.py full               # all ten, the suite defaults — the nightly
tests/battery/battery.py cache              # the cache's commit set (~5 min); scraper, inverter, dashboard, common likewise
tests/battery/battery.py control-fuzz       # named suite(s) — e.g. the one you are iterating on
```

The ten suites (stdlib only, scratch ports, self-cleaning; each prints
ALL PASS or a FAILURES list):

- `cache-regtest` — the cache: the full functional battery
- `inverter-regtest` — the fake: the F11/F13 surface (client caps, timeouts, per-IP, the count gate)
- `scrape-regtest` — the scraper + the fake's machines
- `audit-chain` — the audit trails' hash chains + `scripts/gates/audit_verify.py`
- `cache-stress` — the cache: 100 clients / 15 s load
- `cache-fuzz` [n] / `scrape-fuzz` [n] — n hostile client / HTTP frames
- `cache-control-fuzz` / `control-fuzz` / `dashboard-control-fuzz` — hostile JSON on the control servers

Every scenario must end with the process under test alive and **zero
tracebacks** in the logs.

## Docker

The containers — one alpine image per tool, plus the two compose
stacks: `docker/demo` (the fake inverter end to end, internal-network
only, nothing published on the host) and `docker/prod` (the production
shape: the three services against real hardware, no fake, your own
external collector) — are
documented in [`docker/README.md`](docker/README.md), the demo's
topology diagram included. Both stacks ship authenticated: the Modbus
hops prove a shared suite key (the PVA1/HMAC handshake, generated into
the config volume), the exporter's `/metrics` and the dashboard's page
ride generated bearer tokens — the family's whole security story (the
posture, the caps, the audit trail and its F-ledger) is
[docs/SECURITY.md](docs/SECURITY.md).

## License

The whole suite is licensed under the **BSD 3-Clause License** — see the
`LICENSE` file. The bundled chart library in
`dashboard/static/vendor/echarts.min.js` is
[Apache ECharts](https://echarts.apache.org/) 5.5.1, licensed under the
**Apache License 2.0** (© the Apache Software Foundation); the license notice
is preserved in the vendored file.
