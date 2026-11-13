# Modbus Replay

> **Experimental — work in progress.** The whole pv-suite is still under
> active development: interfaces, file formats and behavior can still change
> at any time.

A dependency-free (Python stdlib only) Modbus TCP **capture/replay
sidecar**: it sits on the wire between a pv-suite client (the
[modbus-cache](../cache/README.md), the
[modbus-scraper](../scraper/README.md), any Modbus master) and the
device, dumps every frame to a trace file — and replays the trace later,
so the poll planning, the write-through and the chaos behavior debug
against real hardware traces without the hardware.

The sidecar has **no control plane**: no JSON-lines control server, no
`-cli` client, no runtime set/show — the debug surface is the Modbus
port, the trace file and the log. One daemon, one mode per run:

| Mode | Knobs | What happens |
|---|---|---|
| capture | `--upstream HOST:PORT` (+ `--capture FILE`) | every client is piped to the device; the wire dumps to the trace |
| replay | `--replay FILE` | the trace is served: recorded responses answer matching requests |

## How it works

**Capture mode is a pipe with a shadow copy.** Every accepted client is
paired with an upstream connection to the device; bytes flow as they
arrive, never held. A tap reassembles the MBAP frames from the piped
bytes (both directions) and appends one JSON record per frame to the
trace file — timestamps, direction, the raw frame, the decoded fields.
A frame the framing cannot parse still reaches the device and rides the
trace raw. Without `--capture` the proxy runs pass-through (the decoded
frames log at DEBUG only) — a quiet wire inspector.

```
  <client>───Modbus───> <replay>───Modbus───> <inverter>
   the cache/scraper      │   ▲                inverter-lan:5502
   (or any master)        │   └── the pipe: bytes flow as they arrive,
                          │       never held
                          ▼
                    [trace file]  <── the tap: one JSON record per
                                     frame, both directions, decoded
```

The trace is JSON lines, 0600 at rest (the wire carries values — and a
Waveshare capture carries the connection password raw; the trace belongs
with the secrets):

```
{"format":"pv-suite-modbus-trace","version":1,"started":"…","tool":"modbus-replay","mode":"capture","upstream":"inverter-lan:502"}
{"ts":1794588996.048,"dir":"req","conn":1,"peer":"127.0.0.1:64824","raw":"004d…","txn":77,"unit":1,"fc":3,"addr":32064,"count":2}
{"ts":1794588996.048,"dir":"rsp","conn":1,"peer":"inverter-lan:502","raw":"004d…","txn":77,"unit":1,"fc":3,"bytes":4}
```

`dir` speaks the client's view (`req` = client to device, `rsp` = the
device's answer, `raw` = the framing lost); exception responses record
their code (`"exc": 2`). The trace **appends across runs** — each run
stamps its header line, a multi-run file is a longer history — and
flushes per frame, so a killed capture leaves a readable trace.

**Replay mode serves the trace.** At start the daemon indexes every
recorded response under its request's identity — unit + function code +
PDU bytes, transaction ids aside (the replay speaks the client's own
ids) — and answers each incoming request with the most recent recorded
response, exception frames included: the device's truth, verbatim.

```
  <client>───Modbus───> <replay>                <inverter>
   the cache/scraper      │                      (absent —
   (or any master)        ▼                       on the bench)
                    [trace file]  ──> the recorded answers,
                                      byte-identical, the recorded
                                      latencies at --replay-speed
```

`--replay-speed` replays the recorded device latencies (the recorded
`rsp.ts − req.ts` gap: `1` = as captured, `N` = N times faster, `0` =
immediately). A request the trace never recorded answers per
`--replay-miss`: **`exception`** (the default — Modbus exception 11,
gateway target device failed to respond: a miss is loud in the client's
error counters) or **`zero`** (a zero-filled reply of the right shape —
reads answer zero data, writes answer their echoes, so a changed poll
plan keeps running and shows its shape). Either way the miss logs, with
the request spelled out — that log is the poll-planning debug.

Replay is a record, not a device: nothing accumulates. A write answers
its recorded response and a following read still reads what the
hardware read at capture time — the write-through behavior you are
debugging sees the recorded world, which is the point (compare the
client's behavior against the trace's truth, not against a simulation
of it).

## Usage

```bash
# capture: the cache's polls to the real device, the wire to a trace
python3 apps/modbus-replay/bin/modbus-replay.py --upstream inverter-lan:502 --capture sun2000-morning.jsonl
# pass-through inspector (no trace): the decoded frames at DEBUG
python3 apps/modbus-replay/bin/modbus-replay.py --upstream :502 --log-level DEBUG
# replay: the scraper debugs against the morning's trace, hardware-free
python3 apps/modbus-replay/bin/modbus-replay.py --replay sun2000-morning.jsonl
# the recorded device latencies, 10x faster than captured
python3 apps/modbus-replay/bin/modbus-replay.py --replay sun2000-morning.jsonl --replay-speed 10
```

Exit codes: `0` = ran (SIGTERM/SIGINT: the graceful shutdown); `1` =
invalid configuration or a failed bind (reason on stderr); `2` = CLI
misuse.

The daemon is a **sidecar, not a deployment**: no container image, no
Nix package, no service module — run it from a checkout
(`apps/modbus-replay/dev` is the launcher) or a plain `python3` line,
next to the tools it debugs.

## Configuration

The startup surface is the flags and their bare env twins: **flag > env >
the built-in defaults** — there is no config file (the sidecar has no
control plane either: every knob is a startup knob). The flags:

| Flag | Default | Meaning |
|---|---|---|
| `--listen` | `127.0.0.1:15503` | the Modbus TCP serve address `HOST:PORT` (`$LISTEN`) |
| `--upstream` | — | capture mode: the device's Modbus TCP endpoint `HOST:PORT` (`:PORT` = 127.0.0.1:PORT, `[v6]:PORT` works) (`$UPSTREAM`) |
| `--capture` | off | the trace file the wire dumps to (JSON lines, 0600; appends across runs) — without it the proxy runs pass-through (`$CAPTURE`) |
| `--replay` | — | replay mode: the trace file to serve (exactly one of `--upstream`/`--replay` per run) (`$REPLAY`) |
| `--replay-speed` | `0` | the recorded device latencies divided by N (`1` = as captured, N = N× faster; `0` = answer immediately) (`$REPLAY_SPEED`) |
| `--replay-miss` | `exception` | what an unmatched request answers: `exception` (exception 11) or `zero` (the zero-filled shape) (`$REPLAY_MISS`) |
| `--client-timeout` | `0` | kick a leg silent longer than N seconds (`0` = never) |
| `--modbus-timeout` | `3` | the capture legs' connect/read timeout in seconds |
| `--local-time` / `--log-level` | UTC / `INFO` | the log stamps in the system time zone / the verbosity (DEBUG decodes every frame; the client connects and disconnects always log at INFO) |
| `--man` | off | print the generated man page |

## Runtime control

There is none — that is the design. The sidecar has no control server,
no tokens, no runtime set/show: the capture posture is fixed at start
and the debug surface is the log and the trace file. The signals:

| Signal | Effect |
|---|---|
| `SIGHUP` | logged and ignored — there is no live layer to re-apply; restart to change the posture |
| `SIGTERM` / `SIGINT` | **Graceful shutdown** with a session summary (connections piped, frames both ways, bytes, undecoded flushes — or sessions served, answered, misses). `SIGUSR2` dumps the thread stacks (the family's faulthandler hook). |

## Security

> **The sidecar is a debug instrument — run it on a trusted, LAN-isolated
> network, next to the tools it debugs.** The Modbus surface speaks to
> any peer that can reach the port (no TLS, no connection gating — no
> connect ACL, no client caps; only `--client-timeout` kicks the
> silent). A bind past loopback is refused nothing but warned loudly —
> a five-line `!!` WARNING banner at start. There is no control plane
> to authenticate — nothing to token. The trace file holds the wire's
> values and names (and a Waveshare capture carries the connection
> password raw): traces write 0600 and belong with the secrets. The
> full family story is [docs/SECURITY.md](../../docs/SECURITY.md).

## Testing

The suite is [`dev/suites/replay-regtest.py`](../../dev/suites/replay-regtest.py)
— capture against the fake inverter, the trace's shape, the byte-identical
replay, the miss policies, the refusals:

```bash
dev/battery/battery.py replay    # the replay profile: the regtest (the suites refuse
                                 #   without the runner's PV_RUN_DIR)
```

Every scenario must end with the daemon alive and **zero tracebacks** in
the logs.

## Source layout

```
apps/modbus-replay/
├── bin/
│   └── modbus-replay.py    # CLI entry, the ladder, validation, wiring
├── lib/
│   ├── options.json        # the knob registry: the flags, the env twins
│   ├── options.py          # its loader (the canon fold, the protocol tree's timeout)
│   ├── config.py           # the resolution ladder (flag > env > default — no config file)
│   ├── statics.py          # static configuration loader (lib/defaults.json)
│   ├── trace.py            # the trace format: the writer, the MBAP tap, the replay index
│   ├── capture.py          # the capture proxy (the pipe + the tap)
│   ├── replay.py           # the replay server (the common face protocol over the index)
│   ├── man.py              # the generated man page's prose (common/render/manpage.py renders)
│   └── defaults.json       # the statics: the trace format identity, the miss codes
└── man/
    └── modbus-replay.1     # the generated man page
```

## License

modbus-replay is part of the pv-suite, licensed under the **BSD 3-Clause
License** — see the `LICENSE` file in the repository root.
