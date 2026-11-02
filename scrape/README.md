# Huawei SUN2000 Prometheus scraper

A dependency-free (Python stdlib only) Prometheus exporter that polls a Huawei
SUN2000 inverter over **Modbus TCP** and exposes the `huawei_*_watts` metrics
the [pv-dashboard](../README.md) expects, plus health gauges.

## Prerequisites

Modbus TCP must be enabled on the inverter / SDongle / EMMA (via FusionSolar or
the local setup), reachable at the inverter's LAN IP on TCP port **502**, unit
id **1**.

## Run

```bash
python3 scrape/src/scraper.py --host 192.168.1.100 --listen 0.0.0.0:9350
curl http://localhost:9350/metrics
```

Add a Prometheus scrape job — the job **name must be `sun2000`**, the
dashboard's default config selects `huawei_*_watts{job="sun2000"}`:

```yaml
scrape_configs:
  - job_name: sun2000
    scrape_interval: 10s          # match scrapeSec in the dashboard config
    static_configs:
      - targets: ['localhost:9350']
```

## Metrics

| Metric | Meaning |
|---|---|
| `huawei_pv_generation_watts` | PV (inverter input) power |
| `huawei_grid_export_watts` | power exported to the grid (≥ 0) |
| `huawei_grid_import_watts` | power imported from the grid (≥ 0) |
| `huawei_home_consumption_watts` | home load, derived as `PV − net grid` (− battery when enabled) |
| `huawei_grid_net_watts` | signed net grid power (debugging aid) |
| `huawei_up` | 1 if the last poll succeeded |
| `huawei_modbus_errors_total` / `huawei_last_poll_timestamp_seconds` | poller health |
| `huawei_battery` | 1 if battery support is enabled (always exported); the dashboard treats 0 / missing as "no battery" and dims its battery node |
| `huawei_battery_net_watts` | signed battery power, +charge/−discharge (`--battery` only) |
| `huawei_battery_charge_watts` / `huawei_battery_discharge_watts` | the split, ≥ 0, for stacked graphs (`--battery` only) |
| `huawei_battery_soc_percent` | battery state of charge (`--battery` only) |

Sign conventions and sanity caps:

- The grid register value is split into export/import by sign — by default
  **positive = export**; set `--grid-positive-import` if your device reports
  the opposite.
- Huawei power registers already report **watts** (their gain convention
  divides raw by 1000 to get kW), so both scales default to 1;
  `--scale` / `--grid-scale` exist for devices that report raw kW.
- Caps are on by default: `--max-kwp 6` (6 kWp array) and `--max-grid-kw 12`
  (12 kW power line). A reading above `max-kwp × 1000` W (register 32064),
  |grid power| above `max-grid-kw × 1000` W in **either direction**
  (register 37113), or exported power above the PV cap (with home load ≥ 0,
  every exported watt must come from the inverter — unless a battery covers
  it) means bad data: the exporter logs an error (`PV energy exceeds
  max_kwp: ...` / `Grid power exceeds max_grid_kw: ...`) and serves
  **HTTP 503** with `# Error collecting metrics from inverter` instead of
  metrics, until a good poll.
- **Negative PV readings always trigger the error** regardless of the cap
  settings — a negative inverter input is bogus data that would corrupt the
  derived home load.
- The caps assume `max-kwp ≤ max-grid-kw` (the line must carry the
  inverter's full output); a startup warning fires otherwise.

Metric names, help texts and types live in **`scrape/src/metrics.json`**
next to the script and are loaded at startup — edit it to rename metrics or
reword `# HELP` lines without touching the code.

## Configuration

Settings are resolved in this order (first hit wins), mirroring
`server.py`:

1. CLI flags (`--host`, `--listen`, …)
2. Environment variables — same names prefixed: `SUN2000_HOST`,
   `SUN2000_MODBUS_PORT`, `SUN2000_UNIT`, `SUN2000_MODBUS_OFFSET`,
   `SUN2000_TIMEOUT`, `SUN2000_PV_REGISTER`, `SUN2000_GRID_REGISTER`,
   `SUN2000_SCALE`, `SUN2000_GRID_SCALE`, `SUN2000_MAX_KWP`, `SUN2000_MAX_GRID_KW`,
   `SUN2000_BATTERY`, `SUN2000_BATTERY_REGISTER`, `SUN2000_BATTERY_SOC_REGISTER`,
   `SUN2000_GRID_POSITIVE_IMPORT`, `SUN2000_LISTEN`,
   `SUN2000_INTERVAL`, `SUN2000_LOG_LEVEL`
3. Config file (snake_case keys, `[scraper]` section) — `--config` picks the
   file (default: `scraper.ini` next to `scraper.py`; missing file is fine)
4. Built-in defaults

`scrape/src/scraper.ini` is a sample with the defaults:

```ini
[scraper]
host = 127.0.0.1
modbus_port = 5502
unit = 1
modbus_offset = 0
timeout = 3
pv_register = 32064
grid_register = 37113
scale = 1
grid_scale = 1
max_kwp = 6
max_grid_kw = 12
battery = false
battery_register = 37001
battery_soc_register = 37004
grid_positive_import = false
listen = 0.0.0.0:9350
interval = 5
log_level = INFO
```

Logging is `logging`-based: one startup line with the effective settings, then
only reachability changes at INFO/WARNING (every poll at DEBUG). Under systemd
(`JOURNAL_STREAM` set) log lines omit their own timestamp — journald adds one.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `scraper.ini` next to the script | config file path |
| `--host` | `127.0.0.1` | inverter/dongle Modbus TCP address |
| `--modbus-port` | `5502` | Modbus TCP port |
| `--unit` | `1` | Modbus unit id |
| `--modbus-offset` | `0` | added to register addresses (set `-1` for gateways that need 0-based addressing) |
| `--pv-register` | `32064` | signed 32-bit PV input power (I32, high word first) |
| `--grid-register` | `37113` | signed 32-bit grid/active power (positive = feed-in) |
| `--scale` | `1` | multiplier for the PV register raw value (raw is already W; set `1000` for kW devices) |
| `--grid-scale` | `1` | multiplier for the grid register raw value (W; set `1000` if your device reports kW) |
| `--max-kwp` | `6` | PV input power check against the array size: above `max-kwp × 1000` W → HTTP 503 + error log; `0` = off. Negative PV and export above the PV cap always error |
| `--max-grid-kw` | `12` | power line grid exchange check: \|grid power\| above `max-grid-kw × 1000` W (either direction) → HTTP 503 + error log; `0` = off |
| `--battery` | off | enable battery support (LUNA2000): battery term in the home derivation + battery metrics |
| `--battery-register` | `37001` | battery power register (I32 W, positive = charging); used when `--battery` is set |
| `--battery-soc-register` | `37004` | battery state of charge (U16, percent×10); used when `--battery` is set |
| `--grid-positive-import` | off | grid register positive means import |
| `--timeout` | `3` | Modbus connect/read timeout, seconds |
| `--listen` | `0.0.0.0:9350` | exporter bind address `HOST:PORT` |
| `--interval` | `5` | seconds between Modbus polls |
| `--log-level` | `INFO` | `DEBUG` logs every poll |

Register defaults follow Huawei's official *Solar Inverter Modbus Interface
Definitions* (Issue 04, 2023-01-10):

- **32064** — Input power, I32. Unit kW with gain 1000, i.e. raw values are watts.
- **37113** — [Power meter] Active power, I32, `> 0` = feed-in. Populated by
  the connected power meter (DTSU666 etc.); without a meter the inverter
  alone cannot report grid power.
- Older **20200520** protocol: input power at **32089**, meter power at
  **37258** — pass `--pv-register 32089 --grid-register 37258` there.
- Unit quirk: the inverter's `[Power meter collection]` copy of 37113 has
  been observed reporting **watts** (gain 1) while the meter-section table
  says kW (gain 1000). The defaults assume watts (`--grid-scale 1`); if
  grid power looks 1000× off the other way, pass `--grid-scale 1000`.
- With a battery (LUNA2000) the derived home load is wrong while the battery
  charges/discharges — point the dashboard's `load` metric at a real meter
  register/exporter instead.

## Fake inverter

`fake_inverter.py` is a Modbus TCP server with demo values for testing the
scraper (and the whole dashboard stack) without hardware. By default it
simulates a sunny day: bell-curve PV between 06:00 and 18:00 (peak 75 % of
`--max-kwp`), home load with morning and evening peaks — so the grid value
exports around noon and imports mornings/evenings. Energy counters grow
during the simulated day; raw values are watts / kWh×100 like the real map.

```bash
python3 scrape/src/fake_inverter.py                       # 127.0.0.1:5502 — scraper defaults just work
python3 scrape/src/fake_inverter.py --time 12:00          # frozen noon: ~4.5 kW PV, exporting
python3 scrape/src/fake_inverter.py --static              # constant PV 4000 W, grid -1500 W
python3 scrape/src/fake_inverter.py --static --battery    # the same, charging 1200 W at 65 %
python3 scrape/src/fake_inverter.py --port 15502 --log-level DEBUG
```

Served registers:

- **32064** / **32080** — PV power / power limit (I32 W)
- **37113** — grid power (I32 W, positive = feed-in)
- **37100+** — smart meter block: status, per-phase voltages/currents,
  reactive power, power factor, grid frequency, and 37119 exported /
  37121 imported kWh totals that grow through the simulated day
- **32089** — device status (512 on-grid / 40960 standby at night)
- **32087** — temperature (I16, °C×10); **32114** daily and **32106** total
  yield (U32, kWh×100)
- Unknown addresses read as 0, other functions get a Modbus exception

Also packaged as `sun2000-fake-inverter`.

## Battery (Huawei LUNA2000)

**Experimental — so far verified only against simulated data** (fake inverter /
mock Prometheus), not against real hardware.

When a battery is present, enable support with `--battery` (env
`SUN2000_BATTERY`, ini `battery = true`). The energy balance gains a battery
term and the home load derivation becomes:

```
home = pv − batt − grid      (without battery: home = pv − grid)
```

Battery registers (defaults follow the same Huawei convention as
`--pv-register`):

- **37001** — battery power, I32 W, **positive = charging**,
  negative = discharging
- **37004** — state of charge, U16, percent×10

Charging midday surplus reduces the home value; evening discharge covers the
home load even with PV at 0. The battery metrics —
`huawei_battery_net_watts` (signed, +charge/−discharge),
`huawei_battery_charge_watts` / `huawei_battery_discharge_watts`
(the split, ≥ 0, for stacked graphs) and `huawei_battery_soc_percent` —
are only exported when battery support is enabled; without it they are
absent from /metrics.

The consistency checks adapt:

- Exported power may exceed the PV cap by the battery discharge (a battery
  feeding the grid is legitimate).
- A derived `home < 0` is rejected as inconsistent data — with a battery,
  charging and export together cannot exceed the PV input.

The fake inverter can emulate the battery for testing:
`python3 scrape/src/fake_inverter.py --battery`.

## Nix

```bash
nix run .#sun2000-scraper -- --host 192.168.1.100
```

NixOS module (same flake, service runs with a dynamic user and systemd
hardening):

```nix
services.sun2000-scraper = {
  enable = true;
  inverterHost = "192.168.1.100";
  listenPort = 9350;
  battery = true;               # once the LUNA2000 is installed
};
```

Options: `enable`, `package`, `inverterHost`, `inverterPort` (502), `unitId`,
`modbusOffset`, `pvRegister`, `gridRegister`, `scale`, `gridScale`, `maxKwp`,
`maxGridKw`, `battery`, `batteryRegister`, `batterySocRegister`,
`gridPositiveImport`, `timeout`, `interval`, `listenHost`, `listenPort`,
`openFirewall`.

## License

The scraper (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
