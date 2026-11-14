# modbus-scraper

> **Experimental — work in progress.** Verified only against simulated
> data (the fake inverter, a mock Prometheus), not against real hardware.

A dependency-free (Python stdlib only) Prometheus exporter that polls a
Modbus TCP inverter and serves the power metrics the
[dashboard](../dashboard/README.md) expects plus health gauges at
`/metrics`. The bundled device profiles cover the Huawei SUN2000 and the
Deye hybrids; it can poll the inverter directly or through the
[modbus-cache](../cache/README.md) proxy (auto-detected). Modbus TCP must
be enabled on the inverter / SDongle / EMMA and reachable on TCP 502,
unit id 1.

The full reference — the control wire, every knob with its flag, env twin
and default, the signals, the metrics, the alerting, the audit trail — is
[the manual](../../extras/manuals/modbus-scraper.md) (generated from the
registry).

## Usage

```bash
python3 apps/scraper/bin/modbus-scraper.py --upstream 192.168.1.100:502
curl http://localhost:9350/metrics
```

- the exporter binds `127.0.0.1:9350` by default; `--listen 0.0.0.0:9350`
  serves the LAN — beyond loopback `--auth-token` is mandatory (a
  token-less non-loopback bind refuses to start);
- `--dry-run` validates the configuration and prints the effective
  settings (exit `0` = valid, `1` = invalid, `2` = misuse);
- settings resolve flag > env > config script (`--config`, the set
  grammar) > built-in defaults;
- live control rides the unix control socket — `modbus-scraper-cli`
  speaks one-shot words, piped batches or the console (`request poll
  now`, `set modbus interval 5`, …);
- `SIGHUP` reloads the configuration without dropping the exporter.

## Security

- the endpoint exposes production values, not telemetry — a week of it is
  a home-occupancy profile;
- loopback bind by default; the bearer token (mandatory beyond loopback,
  F13) is compared timing-safe and takes a `file:<path>` reference that
  re-reads on `SIGHUP` — the rotation path;
- the control wire is the family's signed JSON lines (a TCP control port
  refuses to start without the admin token, F5) and a token value never
  renders back;
- the control commands, auth failures and reloads land in the
  hash-chained SCR audit trail (`--audit-log`); `--audit-forward` mirrors
  every line off-box (F10).

The full story is [docs/SECURITY.md](../../docs/SECURITY.md).

## License

The scraper (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
