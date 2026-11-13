# modbus-replay — done records

The open items live in the family-wide [docs/TODO.md](../../docs/TODO.md);
this file keeps the tool's done/history records, newest first.

## 2026-11-13 — the sidecar lands (`apps/modbus-replay`)

The capture/replay wave: a Modbus TCP sidecar that pipes the wire between
a client and the device and dumps both directions to a JSON-lines trace
(0600, appends across runs, per-frame flush), then serves the trace back
— every request matched on unit + FC + PDU bytes (transaction ids aside),
answered with the most recent recorded response, the recorded device
latencies replayable (`--replay-speed`), the misses loud (exception 11)
or zero-shaped (`--replay-miss zero`). The tool is deliberately OUTSIDE
the family's deployment shapes: no control plane (no ctl/cli pair, no
tokens — the man ladder grew the `sidecar` page class for it), no docker
image, no Nix package, no service module, no audit trail (the trace
IS the record — a second accounting of the same wire would only drift
from it), no connection gating (no connect ACL, no client caps — only
`--client-timeout` kicks the silent), no config file and no `--dry-run`
(the knobs are the flags and their bare env twins, flag > env >
default — and the surface is small enough to just run; a bind past
loopback warns loudly instead). The
registry (lib/options.json) still drives the surfaces the family's
registries drive: the parser and the man page.
The suite is `dev/suites/replay-regtest.py` (the battery's `replay`
profile; it rides `commit`/`quick`/`full` too).
