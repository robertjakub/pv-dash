# modbus-replay

> **Experimental — work in progress.**

modbus-replay is a dependency-free (Python stdlib only) Modbus TCP
capture/replay sidecar: a debug instrument with two faces over one
trace format. The capture face sits on the wire between a pv-suite
client — the modbus-cache, the modbus-scraper, any Modbus master — and
the device, pipes the bytes as they flow, and dumps every frame in
both directions to a trace file. The replay face serves the recorded
trace back later as a stand-in device, so the poll planning, the
write-through and the chaos behavior debug against real hardware
traces without the hardware. The sidecar is a tool run beside the
family, not a deployment: it ships no container image, no Nix package
and no service module — it runs from a checkout, next to the tools it
debugs.

The two faces are one daemon per run, exactly one mode each run: the
capture mode pipes every client to the device while a shadow copy of
the wire lands in the trace (the binary PVMB blocks by default, the
JSON v1 lines on request); the replay mode matches every incoming
request against the recorded ones and answers the recorded response —
the device's own bytes, exceptions included. Whatever one mode writes,
the other reads, and the reader tool `modbus-replay-dump` reads it
too: it renders the trace's three views, converts between the two
shapes and follows the running capture live. A run that captures
nothing still serves: without a trace file the capture proxy is a
quiet wire inspector, and the record feed pushes every frame to the
subscribed viewers as it lands.

The full reference for both binaries is their `--help` and their man
pages — `modbus-replay --man | man -l -` prints each one. This page
is the tour; the man pages are the tables.

## The family

The pv-suite ladder runs device to dashboard:

```text
  device :502  <-->  modbus-cache :15502  <-->  modbus-scraper :9350
                                                          |
                                                          v
                                                     prometheus
                                                          |
                                                          v
                                                      dashboard

  modbus-replay :15503 stands beside the ladder:

    capture face:   client  <-->  modbus-replay  <-->  device
                    (the bytes pipe through untouched while the
                    wire dumps to a trace file)

    replay face:    client  <-->  modbus-replay
                    (a recorded trace answers in the device's
                    place — the stand-in device)
```

The sidecar rides beside the ladder rather than in it. Point the
cache or the scraper at a replay instead of the device and a
morning's traffic debugs offline — the poll planning, the
write-through and the failure paths exercise against the recorded
answers, in a demo or a regression run, with no hardware on the
network. Sit the capture face between a client and the real device
and the same wire that serves production records itself for later.

## How it works

One daemon, one mode per run, one trace format through both. The
surface is deliberately small: flags and their bare env twins at
start, the Modbus port, the trace file, the record feed and the log —
there is no control plane and no config file.

- The capture face (`apps/modbus-replay/lib/capture.py`) is a pipe
  with a shadow copy. Every accepted client is paired with its own
  upstream connection to the device, one pump thread per direction;
  the MBAP tap reassembles the frames from the piped bytes without
  ever holding them — the pipe's first job is to move bytes, the
  trace is the shadow copy. A frame the framing cannot parse still
  reaches the device and rides the trace raw; the auth handshakes
  (the PVA1 proof, the Waveshare password, their verdicts) peel and
  name the same way, the raw bytes riding verbatim. Without
  `--capture` the proxy runs pass-through and the decoded frames log
  at DEBUG only — a wire inspector.
- The replay face (`apps/modbus-replay/lib/replay.py`) serves the
  trace. Every incoming request is matched against the recorded ones
  on unit + function code + PDU bytes (transaction ids aside — the
  replay speaks the client's own ids) and answers the most recent
  recorded response, exception frames included: the device's truth,
  verbatim. Writes answer their recorded responses too — the trace is
  a record, not a device: nothing accumulates, a write followed by a
  read still reads what the hardware read at capture time.
- The trace format is the family's one trace home
  (`common/modbus/trace.py`): the binary PVMB blocks by default — one
  magic + version + started + posture header block per run, then one
  length-framed, CRC-checked record block per frame — or the JSON v1
  lines (`"format": "pv-suite-modbus-trace"`, one record per frame,
  the decoded fields beside the raw hex) per `--dump-type json`. The
  capture appends across runs, each run stamping its header; the
  replay reads both shapes, the first bytes picking the walk; a
  foreign file or a future version refuses, a torn tail keeps what
  parsed.
- The second binary, `modbus-replay-dump`
  (`apps/modbus-replay/bin/modbus-replay-dump.py`), is the trace's
  reader face. The static views render the summary line, the answer
  index (one line per unique query: the recorded reply the replay
  will serve, the recorded latency, the ask count) and the
  conversations (the per-connection query-to-answer diagram, unpaired
  records marked in place). The converter rewrites either shape as
  the other (`--to json|binary -o OUT`, a round trip lands
  byte-identical). The live view (`--socket`) subscribes the running
  daemon's record feed and renders the conversations realtime — and
  can record the feed to a trace file (`--record`) any reader takes
  for captured.

## Installing

### From the tree

The sidecar lives in the checkout and runs from it — Python 3 with
the standard library only, no packages to install:

```bash
python3 apps/modbus-replay/bin/modbus-replay.py --help
python3 apps/modbus-replay/bin/modbus-replay-dump.py --help
```

The binaries self-wire their imports (the subproject's `lib/` and the
repo root's `common/`), so the working directory does not matter —
the checkout does. The `--version` flag prints the suite version; the
`--man` flag prints the man page in roff for `man -l -`.

### Nix / NixOS

There is no Nix package and no NixOS service module for the sidecar —
the family's packaging deliberately stops at the four deployed tools.
Run it from the tree like any other checkout script.

### Docker

There is no Dockerfile for the sidecar either. The images under
`docker/` cover the cache, the scraper, the fake inverter, the
dashboard and Prometheus; a debug instrument that rides next to the
operator has no image. The same reasoning keeps it out of the systemd
posture: no unit files ship.

## Quick start

The repo ships a worked trace,
`extras/examples/modbus-replay-trace.pvmb` — two capture sessions
against a SUN2000-shaped device, the PVA1 and Waveshare handshakes
included. Inspect it first; no device and no network needed:

```bash
python3 apps/modbus-replay/bin/modbus-replay-dump.py \
    extras/examples/modbus-replay-trace.pvmb
```

The render opens with the summary, then the answer index, then the
conversations — the real thing, abridged:

```text
extras/examples/modbus-replay-trace.pvmb: 22 request(s), 5 response(s)
indexed (0 orphan(s)), 1 unit(s) [1], FC1,FC3,FC4,FC6, span 60.06s in
2 session(s)

--- the answer index (5 unique queries) ---
FC3 (read holding registers) unit 1 addr 32064 count 2 -> FC3 (read
holding registers) unit 1 4 data byte(s) (2 register(s))  latency
12.3ms  asked 5x
      32064:  0190 00f0
```

Serve the same trace as a stand-in device:

```bash
python3 apps/modbus-replay/bin/modbus-replay.py \
    --replay extras/examples/modbus-replay-trace.pvmb
```

The replay binds `127.0.0.1:15503` and answers every recorded query
with the recorded bytes. Point any Modbus master at it — the family's
cache, for instance:

```bash
python3 apps/cache/bin/modbus-cache.py --upstream 127.0.0.1:15503
```

Capturing a trace of the operator's own runs the ladder the other way
round. Three terminals: the stand-in device, the capture proxy, the
poller. The fake inverter stands in for the hardware:

```bash
# terminal 1 - the device
python3 apps/inverter/bin/modbus-fake-inverter.py \
    --listen 127.0.0.1:5502

# terminal 2 - the capture proxy: pipe to the device, dump the wire
python3 apps/modbus-replay/bin/modbus-replay.py \
    --listen 127.0.0.1:15503 \
    --upstream 127.0.0.1:5502 \
    --capture morning.pvmb

# terminal 3 - the poller, through the proxy
python3 apps/cache/bin/modbus-cache.py --upstream 127.0.0.1:15503
```

The cache now talks to the fake through the sidecar, `morning.pvmb`
grows one record per frame in both directions, and the record feed
pushes each record live. In a fourth terminal the conversations
render as they land:

```bash
python3 apps/modbus-replay/bin/modbus-replay-dump.py --socket
```

Stop the capture with ^C — the shutdown summary counts the accepted
pairs, the frames and the bytes — then replay `morning.pvmb` the same
way the shipped example was replayed above.

## Configuration

### How a setting resolves

Every knob resolves the family ladder's first half: flag, then env,
then the built-in default — the config-script layer is absent because
there is no config file and no control plane to set one. The env
names are the bare upper-snake twins of the flags (`REPLAY_SPEED`
for `--replay-speed`), read once at start. A flag left unset never
shadows the env layer: the defaults stay out of the parser and the
ladder resolves in `apps/modbus-replay/lib/config.py`.

There are no secret knobs — nothing on the surface authenticates or
unseals anything. The secret-bearing artifact is the trace file
itself (see the access-control notes below): it writes `0600` and
belongs with the secrets.

### The knobs

The daemon's registry (`apps/modbus-replay/lib/options.json`) drives
the parser and the man page; every row is a startup knob, none is
live. The defaults below are the built-ins the ladder falls to:

| Knob | Flag | Env | Default | Live | What it does |
|---|---|---|---|---|---|
| listen | `--listen` | `LISTEN` | `127.0.0.1:15503` | startup | the listen address HOST:PORT |
| upstream | `--upstream` | `UPSTREAM` | — | startup | the device's Modbus TCP endpoint HOST:PORT (`:5502` means 127.0.0.1:5502, `[v6]:PORT` works); capture mode's device leg; exactly one of `--upstream`/`--replay` |
| capture | `--capture` | `CAPTURE` | — | startup | the trace file the wire dumps to (0600); appends across runs; without it the capture proxy runs pass-through; needs `--upstream` |
| dump-type | `--dump-type` | `DUMP_TYPE` | `binary` | startup | the trace's shape: the binary PVMB blocks or `json` (the v1 lines for head/grep/jq) |
| dump-socket | `--dump-socket` | `DUMP_SOCKET` | `/tmp/modbus-replay-<listen-port>.socket` | startup | the record feed's unix socket — read-only push to the subscribed viewers; `none` binds no feed |
| trace-max-mb | `--trace-max-mb` | `TRACE_MAX_MB` | `0` | startup | rotate the trace at this size in MB; 0 = no size rotation (the capture appends unbounded) |
| trace-files | `--trace-files` | `TRACE_FILES` | `3` | startup | rotated backups to keep (the `.1` .. `.N` shift; each backup a complete trace) |
| replay | `--replay` | `REPLAY` | — | startup | the trace file to serve — replay mode; exactly one of `--upstream`/`--replay` |
| replay-speed | `--replay-speed` | `REPLAY_SPEED` | `0` | startup | replay the recorded device latencies: the recorded gap divided by N (1 = as captured); 0 = answer immediately |
| replay-miss | `--replay-miss` | `REPLAY_MISS` | `exception` | startup | what an unmatched request answers: `exception` (exception 11, loud in the client's error counters) or `zero` (a zero-filled reply of the right shape) |
| client-timeout | `--client-timeout` | `CLIENT_TIMEOUT` | `300` | startup | disconnect clients silent for this many seconds; 0 = never |
| modbus-timeout | `--modbus-timeout` | `MODBUS_TIMEOUT` | `3` | startup | Modbus connect/read timeout in seconds |
| local-time | `--local-time` | `LOCAL_TIME` | `off` | startup | log timestamps in the system time zone instead of UTC |
| log-level | `--log-level` | `LOG_LEVEL` | `INFO` | startup | the log verbosity: DEBUG decodes every frame into the log |

The dump tool reads its flags only — its man page's ENVIRONMENT
section says so. The first argument is the trace file (either shape;
the first bytes pick the walk):

| Flag | What it does |
|---|---|
| `--socket` `[PATH]` | the live view: subscribe a record feed and render the conversations realtime; bare `--socket` spells the derived default `/tmp/modbus-replay-<listen-port>.socket` — any family feed subscribes (the cache's trace-socket included) |
| `--record` `FILE` | the live view saves the feed to this trace file while it renders — the blocks land verbatim (0600, appended across sessions), a trace any reader takes for captured; rides `--socket` |
| `--trace-max-mb` `MB` | rotate the recorded trace at this size, keeping N backups; rides `--record` |
| `--trace-files` `N` | rotated backups to keep for the recorded trace; rides `--trace-max-mb` |
| `--quiet` | the recorder runs silent — no per-record render, the banners and the save tally stay |
| `--values` | the live view also dumps the values under the completed exchanges (off by default — a busy feed stays one line a frame; the file views dump the values always) |
| `--values-cap` `N\|all` | the word cap for the values dumps that cap — the default 16 keeps the diagram readable, `all` dumps the whole block (the answer index dumps the full block always) |
| `--to` `json\|binary` | convert the trace to the other shape (with `-o OUT`) — the raw bytes are the one truth, a round trip lands byte-identical |
| `-o`, `--out` `OUT` | the converted trace's path (0600) |
| `--man` | print the man page (roff) to stdout and exit |

## Runtime control

There is no console and no ctl: the sidecar ships no control plane,
so no command sequence exists to run against a live daemon. The
debug surface is the Modbus port, the trace file, the record feed and
the log; the dump tool's views are the read-back.

Signals are the whole runtime story:

- `SIGHUP` — logged and ignored: the sidecar has no live layer to
  re-apply, the capture posture is fixed at start. Restart to change
  a knob.
- `SIGTERM`, `SIGINT` — graceful shutdown with a session summary (the
  accepted pairs, the frames, the bytes; the trace closes flushed),
  exit 0.

Every knob in the tables above is a startup knob; the family's live
`set`/`clear` wire does not reach here by design — nothing to control,
the trace is the record.

## The control plane

The honest answer is the absence: no control server, no control
socket, no ctl/cli pair, no tokens, no JSON-lines wire. The option
registry's control-grammar half stays empty by design. The record
feed is the closest thing to a runtime interface, and it is a
read-only push on a unix socket — no verbs, no tokens, nothing a
command could ride; a subscriber that cannot keep up is dropped (the
trace file has everything). The audit habit ends here too — the
trace IS the record (every frame, both directions, timestamped), and
a second accounting of the same wire would only drift from it.

## Access control

The sidecar is a debug instrument: run it on a trusted, LAN-isolated
network, next to the tools it debugs. The Modbus surface speaks to
any peer that can reach the port — no TLS, no connect ACL, no client
caps, none of the family's auth legs (`--modbus-auth` does not ride
here; the capture only names the handshakes it sees go past). The
only gate is `--client-timeout`, which kicks the silent. A listen
past loopback (127.0.0.1, ::1, localhost) is refused nothing but
warned loudly: the start logs a five-line WARNING banner naming the
shared bind and what it exposes.

The posture that matters is the trace file: it writes `0600` and
holds the wire's values and names — a Waveshare capture carries the
connection password raw, a suite-auth capture the PVA1 proof, and a
leaked trace can replay it at any server holding the key. Traces
belong with the secrets. The recorded files (`--record`) ride the
same posture. The family story is `docs/SECURITY.md`.

## Tuning

The timing knobs shape how faithfully the replay imitates the capture
and how patient the faces are:

- `--replay-speed` — the recorded device latency (the response
  timestamp minus the request's) waits before the answer, divided by
  N: `1` replays the latencies as captured, `N` runs the replay N
  times faster than the capture, `0` (the default) answers
  immediately.
- `--replay-miss` — the miss policy is the poll-planning debug:
  `exception` answers exception 11 (gateway target device failed to
  respond), loud in the client's error counters; `zero` synthesizes a
  zero-filled reply of the right shape so a changed poll plan keeps
  running and shows its shape — reads answer zero data, single
  writes echo, multiple writes answer the address/count echo. Either
  way the miss logs.
- `--client-timeout` — the only kick: a client silent this many
  seconds disconnects (300 by default, `0` never). The capture pipe
  itself never times a leg — a slow device surfaces through the
  client's own timeout, as any device hiccup would.
- `--modbus-timeout` — the Modbus connect/read timeout in seconds
  (the family tree's 3 s default).

The disk knobs shape a long capture: an unbounded trace is a disk
hazard, so `--trace-max-mb` rotates the file at a size, keeping
`--trace-files` backups — the backups shift (`.1` <- `.2` <- ... <-
`.N`, the oldest dropped), the file reopens fresh and stamps a new
run header. Every backup is a complete trace of its own and a record
never straddles two files. The same pair rides the dump tool's
`--record`. For visibility, `--log-level DEBUG` decodes every frame,
both directions, into the log.

## Deployment

The honest state: no Nix package, no NixOS service module, no
Dockerfile, no shipped systemd units. The sidecar is a checkout
instrument — the operator runs it next to the tools it debugs, for
as long as the debug session lasts, and stops it with a signal. For
the long-running capture that must stay, `--trace-max-mb` bounds the
disk and the rotation keeps every backup a complete trace; the trace
files belong with the secrets wherever they land.

The exit posture is the family's: exit `0` ran (the graceful
shutdown), `1` invalid configuration or a failed bind (reason on one
stderr line), `2` command-line misuse.

## Troubleshooting

- Startup refusals (exit `1`, one line each): `--upstream` and
  `--replay` together, neither of them, `--capture` without
  `--upstream`, the rotation knobs without a trace file, `--replay`
  naming a file that is not there. Fix the spelled problem and run
  again — there is no `--dry-run`; the validation is the start.
- `cannot bind 127.0.0.1:15503` — another daemon holds the port
  (often a previous capture). Pick another `--listen` port; the
  record feed's derived socket path follows the port, so the viewers
  stay in step.
- The five-line WARNING banner at start — the listen address is not
  loopback. The sidecar authenticates nothing; if sharing the bind
  is not the point, go back to `127.0.0.1`.
- A killed capture leaves a readable trace — the walk keeps what a
  torn tail parsed and resyncs at the next run header; a mid-file
  CRC failure resync-scans forward. `modbus-replay-dump` renders the
  remainder and the converter converts as far as it parsed.
- `framing lost — raw bytes only` lines in the conversations —
  records the MBAP framing could not parse (a poisoned head flushes
  and resyncs). The bytes reached the device anyway; the tap never
  holds the pipe.
- The replay answers exception 11 — the miss log names the poll the
  trace never recorded. Expected when the poll plan changed after
  the capture; rerun the capture or spell `--replay-miss zero` to
  see the new plan's shape.
- The live view ends with `the feed closed` — the daemon stopped, or
  this viewer could not keep up and was dropped. The trace file has
  everything; the file views never wait.
- The dump refuses a combination (exit `1`) — `--values` on a file
  view (the file views dump the values always), `--record` without
  `--socket`, `--to` without `-o`, a trace and a socket at once. The
  refusal names the shape that is wanted.

## Testing

The suite is `dev/suites/replay-regtest.py`: the capture pipe records
both directions in both shapes, the walk keeps what a torn tail
leaves, the dump bin renders the three views and converts between the
shapes, the record feed pushes live, the replay answers
byte-identical under the client's own transaction ids, the miss
policies speak, the ladder's refusals hold and the pass-through runs
without a trace. The device it captures against is the family's fake
inverter.

The suites run through the battery runner, never standalone:

```bash
python3 dev/battery/battery.py replay
```

The `replay` profile runs the gate lints beside the regtest
(`check-options`, `links-check`, `lint-gates`, then
`replay-regtest`); the suite rides the `commit`, `quick` and `full`
profiles too. The runner hands the run its own directory and port
slot, so a concurrent battery cannot kill it.

## The docs map

| Document | What it holds |
|---|---|
| [apps/modbus-replay/README.md](../../apps/modbus-replay/README.md) | the tool's own reference: the modes, the trace format's byte layout, the security posture |
| [apps/modbus-replay/man/modbus-replay.1](../../apps/modbus-replay/man/modbus-replay.1) | the daemon's man page — the flags, the env twins, the signals, the files, the exit statuses |
| [apps/modbus-replay/man/modbus-replay-dump.1](../../apps/modbus-replay/man/modbus-replay-dump.1) | the reader's man page — the views, the converter, the live view, the recorder |
| [apps/modbus-replay/lib/capture.py](../../apps/modbus-replay/lib/capture.py) | the capture face: the pipe, the pumps, the tap |
| [apps/modbus-replay/lib/replay.py](../../apps/modbus-replay/lib/replay.py) | the replay face: the index match, the latencies, the miss policy |
| [apps/modbus-replay/lib/trace.py](../../apps/modbus-replay/lib/trace.py) | the sidecar's trace face — it re-exports the family home `common/modbus/trace.py` |
| [apps/modbus-replay/lib/options.json](../../apps/modbus-replay/lib/options.json) | the knob registry the parser and the man page render |
| [extras/examples/modbus-replay-trace.pvmb](../../extras/examples/modbus-replay-trace.pvmb) | the shipped example trace |
| [dev/generators/trace_example.py](../../dev/generators/trace_example.py) | the example trace's generator (`--check` pins the default render) |
| [dev/suites/replay-regtest.py](../../dev/suites/replay-regtest.py) | the capture/replay suite |
| [docs/SECURITY.md](../../docs/SECURITY.md) | the family security story |
| [docs/specs/MODBUS.md](../../docs/specs/MODBUS.md) | the Modbus wire spec the family speaks |
| [docs/book/src/replay.md](../../docs/book/src/replay.md) | the book chapter (it includes the tool README) |
| [docs/book/src/security.md](../../docs/book/src/security.md) | the book's security chapter |
| [docs/book/src/config.md](../../docs/book/src/config.md) | the family configuration story — the ladder this tool rides the first half of |
| [docs/book/src/common.md](../../docs/book/src/common.md) | the shared code the sidecar rides (the serve ladder, the trace writer) |
