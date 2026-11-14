# Fake Inverter Simulator

> **Experimental — work in progress.**

A dependency-free (Python stdlib only) Modbus TCP server that plays an
inverter — with a battery, a smart meter and the modbus-cache diagnostics
block — so the [modbus-scraper](../scraper/README.md), the
[modbus-cache](../cache/README.md) and the whole [pv-suite](../../README.md)
stack can be exercised without hardware. Through **inverter profiles** it
emulates different devices: the shipped default profile is the `sun2000`
(Huawei SUN2000) map, and Deye hybrid profiles are included as well — see
[shared/profiles/README.md](../../shared/profiles/README.md).

The full reference — the simulated machines, every knob with its flag and
env twin, the runtime pins, the chaos injection, the served registers and
the audit trail — is the daemon's `--help` and the man page
(`modbus-fake-inverter --man`).

## Usage

```bash
python3 apps/inverter/bin/modbus-fake-inverter.py                       # 127.0.0.1:5502 — scraper defaults just work
python3 apps/inverter/bin/modbus-fake-inverter.py --time 12:00          # frozen noon: ~4.5 kW PV, exporting
python3 apps/inverter/bin/modbus-fake-inverter.py --static              # the classic static demo values
python3 apps/inverter/bin/modbus-fake-inverter.py --config apps/inverter/examples/modbus-fake-inverter.conf --dry-run
```

- `--dry-run` validates the configuration and prints the effective
  settings (exit `0` = valid, `1` = invalid, `2` = misuse);
- a simulated clock drives every machine — UTC by default, `--time-scale
  N` runs a full day in 24/N real hours, `set time 18:00` is the
  time-lapse control;
- runtime control (pin the PV, the load, the battery, the SoC, the
  clouds, the grid setpoint, inject chaos) rides the unix control socket
  — `modbus-fake-cli` speaks one-shot words, piped batches or the
  console (`set pv 2500`, `set soc 30`, `set scenario noon`, …);
- `SIGHUP` re-applies the environment layer; `SIGUSR1` resets the
  scenario.

## Security

> **The fake is a development tool — run it on a trusted, LAN-isolated
> network.** It is deliberately *not* security-first design (the audit's
> F11).

- the Modbus surface speaks to any peer that can reach the port; the
  optional `--modbus-auth suite` handshake is the one gate;
- the fake keeps its tokenless-TCP control posture (F11, the test-tool
  exemption every other tool refuses);
- the tokens take `file:<path>` references anyway (a flag lands in
  `ps`); the audit trail is on by default at the XDG state home.

The full story — the caps, the supply-chain claim — is
[docs/SECURITY.md](../../docs/SECURITY.md).

## License

The fake inverter (source, Nix packaging) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file in the repository root.
