# pv-suite

A family of dependency-free (Python stdlib only) home-PV tools around a
Huawei SUN2000 inverter, packaged together as one Nix flake:

| Subproject | Package / app | What it is |
|---|---|---|
| [`dashboard/`](dashboard/README.md) | `dashboard` | Single-page energy-flow dashboard fed by Prometheus, with a bundled stdlib-only proxy server and a NixOS module |
| [`scrape/`](scrape/README.md) | `modbus-scraper` | Huawei SUN2000 Prometheus exporter (Modbus TCP, stdlib only) with a NixOS module |
| [`cache/`](cache/README.md) | `modbus-cache` | **Experimental** Modbus TCP caching proxy that multiplexes the inverter's single client connection |
| [`inverter/`](inverter/README.md) | `modbus-fake-inverter` | **Experimental** fake SUN2000 + LUNA2000 + smart meter for testing the stack without hardware — with a runtime control server, Cisco-style CLI and chaos injection |

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
├── flake.nix     # the suite entry point
└── LICENSE       # BSD 3-Clause (whole suite)
```

## License

The whole suite is licensed under the **BSD 3-Clause License** — see the
`LICENSE` file. The bundled chart library in
`dashboard/src/static/vendor/echarts.min.js` is
[Apache ECharts](https://echarts.apache.org/) 5.5.1, licensed under the
**Apache License 2.0** (© the Apache Software Foundation); the license notice
is preserved in the vendored file.
