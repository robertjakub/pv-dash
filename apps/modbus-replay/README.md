# Modbus Replay

> **Experimental — work in progress.**

A dependency-free (Python stdlib only) Modbus TCP **capture/replay
sidecar**: it sits on the wire between a pv-suite client (the
[modbus-cache](../cache/README.md), the
[modbus-scraper](../scraper/README.md), any Modbus master) and the
device, dumps every frame to a trace file — and replays the trace later,
so the poll planning, the write-through and the chaos behavior debug
against real hardware traces without the hardware. A sidecar, not a
deployment: no container image, no Nix package, no service module — run
it from a checkout next to the tools it debugs.

The full reference — the modes, the trace format (both shapes), the dump
tool, every flag with its env twin and default — is the daemon's `--help`
and the man page (`modbus-replay --man`).

## Usage

```bash
# capture: the cache's polls to the real device, the wire to a trace
python3 apps/modbus-replay/bin/modbus-replay.py --upstream inverter-lan:502 --capture sun2000-morning.pvmb
# replay: the scraper debugs against the morning's trace, hardware-free
python3 apps/modbus-replay/bin/modbus-replay.py --replay sun2000-morning.pvmb
# the reader face: the summary, the answer index, the conversations
python3 apps/modbus-replay/bin/modbus-replay-dump.py sun2000-morning.pvmb
# live: the conversations render off the running daemon's record feed
python3 apps/modbus-replay/bin/modbus-replay-dump.py --socket
```

- one daemon, one mode per run: `--upstream` (+ `--capture FILE`) pipes
  to the device while the wire dumps to the trace; `--replay FILE`
  serves the recorded answers instead;
- without `--capture` the proxy runs pass-through — a quiet wire
  inspector (the decoded frames log at DEBUG);
- there is no control plane: no control server, no `-cli` client, no
  runtime set/show — the debug surface is the Modbus port, the trace
  file and the log (exit `0` = ran, `1` = invalid config or failed
  bind, `2` = misuse).

## Security

> **The sidecar is a debug instrument — run it on a trusted,
> LAN-isolated network, next to the tools it debugs.**

- the Modbus surface speaks to any peer that can reach the port (no TLS,
  no connect ACL, no client caps; a bind past loopback is warned loudly);
- the trace holds the wire's values and names — a Waveshare capture
  carries the connection password raw, a suite-auth capture the PVA1
  proof: traces write `0600` and belong with the secrets;
- the record feed is read-only push on a unix socket — no verbs, no
  tokens, nothing a command could ride.

The full family story is [docs/SECURITY.md](../../docs/SECURITY.md).

## License

modbus-replay is part of the pv-suite, licensed under the **BSD 3-Clause
License** — see the `LICENSE` file in the repository root.
