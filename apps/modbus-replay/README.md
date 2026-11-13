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
bytes (both directions) and appends one record per frame to the trace
file — timestamps, direction, the raw frame bytes. A frame the framing
cannot parse still reaches the device and rides the trace raw — the
auth handshakes ride exactly there (below). Without `--capture` the
proxy runs pass-through (the decoded frames log at DEBUG only) — a
quiet wire inspector.

```
  <client>───Modbus───> <replay>───Modbus───> <inverter>
   the cache/scraper      │   ▲                inverter-lan:5502
   (or any master)        │   └── the pipe: bytes flow as they arrive,
                          │       never held
                          ▼
                    [trace file]  <── the tap: one record per
                                     frame, both directions
```

### The trace format

The trace is 0600 at rest (the wire carries values — and a Waveshare
capture carries the connection password raw; the trace belongs with the
secrets). Two shapes, feature the same — `--dump-type` picks what
capture writes, every reader speaks both:

- **binary** (the default) — a `PVMB` file: one header block per run,
  then one length-framed, CRC-checked block per record. About half the
  bytes of the JSON spelling, no parser on the read path, and a torn
  tail costs one record instead of the file.
- **json** (the v1 spelling) — JSON lines: one record per frame, the
  decoded fields (`txn`, `fc`, `addr`, …) riding beside the raw hex —
  the `head`/`grep`/`jq` spelling.

The binary layout, big-endian throughout (MBAP's own order; `crc32` is
zlib's):

```text
header block (one per run — the anchor):
  0   4   magic  b'PVMB'
  4   1   version (1)
  5   1   reserved (0)
  6   8   started (u64 epoch seconds)
  14  2   upstream_len (u16)
  16  N   upstream (utf-8 — the recorded posture string)
  +4  4   crc32 over bytes 0 .. 16+N

record block (one per frame):
  0   4   body_len (u32) — the body's length; the skip unit
  4   8   ts (f64 epoch — the wall clock, the trace's own domain)
  12  1   kind (0=req, 1=rsp, 2=raw c2d, 3=raw d2c)
  13  4   conn (u32 — the proxy leg pair)
  17  1   peer_len (u8) + N peer (utf-8 'ip:port')
  ..  1   note_len (u8) + N note
  ..  2   raw_len (u16) + N raw (the MBAP frame, verbatim)
  ..  4   crc32 over the body (ts .. raw)
```

The record walk: the header at offset 0 anchors it; a mid-file `PVMB`
block is a later run's header — the session boundary (the trace
**appends across runs**, a multi-run file is a longer history; the
conn ids restart each run). A block that runs past EOF is a torn tail:
the walk keeps what parsed and notes the loss — a killed capture leaves
a readable trace. A mid-file CRC failure resync-scans for the next
header; the records between the tear and the re-anchor are lost with
the tear. The JSON walk reads the same story line-wise: a torn line
skips (noted), a later header line is the boundary. A foreign file or
a future version refuses with a clean one-liner.

**A capture left running grows unbounded** — `--trace-max-mb` rotates
the trace at that size, keeping `--trace-files` backups (`0` = no size
rotation, the default). At the size the backups shift
(`trace.pvmb.1 ← trace.pvmb.2 ← …`, the oldest dropped), the file
reopens fresh and stamps a new run header: the fresh capture keeps the
plain name, and **every backup is a complete trace of its own** — any
reader takes each for captured (the views, the converter, `--replay`
serve one slice at a time). A record is the rotation boundary: a block
never straddles two files. The dump tool's `--record` carries the same
pair and rotates the same way (the recorder re-stamps a header of its
own — the feed's posture, now).

The json spelling's records (the decoded echo is its readability sugar —
the binary carries the frame once and re-derives on read; the converter
never copies the echo):

```json
{"format":"pv-suite-modbus-trace","version":1,"started":"…","tool":"modbus-replay","mode":"capture","upstream":"inverter-lan:502"}
{"ts":1794588996.048,"dir":"req","conn":1,"peer":"127.0.0.1:64824","raw":"004d…","txn":77,"unit":1,"fc":3,"addr":32064,"count":2}
{"ts":1794588996.048,"dir":"rsp","conn":1,"peer":"inverter-lan:502","raw":"004d…","txn":77,"unit":1,"fc":3,"bytes":4}
```

`dir` speaks the client's view (`req` = client to device, `rsp` = the
device's answer, `raw` = the framing lost); exception responses record
their code (`"exc": 2`).

The auth handshakes do not ride MBAP — the suite auth's PVA1 proof is
a raw 52-byte frame (magic + nonce + HMAC-SHA256), the Waveshare
password raw ASCII, the verdicts raw `OK`/`ERR`. The tap peels and
names them before the first clean frame — the conversations render the
handshake whole (`PVA1 handshake proof`, `Waveshare password`,
`auth verdict`) and the device's first real frame survives the verdict
glue — and the bytes ride the trace verbatim as raw records either
way: one more reason the trace is 0600 (a leaked trace can replay a
PVA1 proof at any server holding the key).

The sizes, the same FC3 poll pair (count 2):

| pair | json | binary | win |
|------|------|--------|-----|
| thin (12B + 14B frames) | ~270 B | ~107 B | ~2.5× |
| fat read reply (246B frame) | ~540 B | ~285 B | ~1.9× |

A worked example ships with the suite —
[extras/examples/modbus-replay-trace.pvmb](../../extras/examples/modbus-replay-trace.pvmb)
(two sessions, both handshakes, the polls, the refused write,
deterministic bytes; rendered by
`modbus-replay-dump extras/examples/modbus-replay-trace.pvmb`).

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

### The record feed and the dump tool

Every record the trace writer encodes also fans out to the **record
feed** — `--dump-socket` binds a unix stream socket at the family's
derived path (`/tmp/modbus-replay-<listen-port>.socket`,
`/tmp/modbus-replay-15503.socket` at the default listen; bound by
default, the word `none` turns it off). The feed is read-only push in
the binary record encoding verbatim — no verbs, no tokens, nothing a
command could ride (the no-control-plane ruling stands); a slow
subscriber is dropped, the FILE keeps every record. Capture mode
pushes the real wire's records; **replay mode pushes the session it
serves** — the requests, the recorded answers with the applied
latencies, the misses as the frames they are.

The reader face is its own bin,
[`bin/modbus-replay-dump.py`](bin/modbus-replay-dump.py) (its own man
page): the three static views of a trace file (the summary, the answer
index — per unique query, the recorded reply the replay will serve
with the recorded latency and the ask count — and the conversations,
the per-connection query→answer diagram — one block per connection
naming both ends of the pipe, every packet line carrying its source
host:port and its `#conn:txn` pairing key (the record's own `peer`, the
MBAP transaction id — a device echoing a foreign id shows right
there)), the converter
(`--to json|binary -o OUT` — either shape reads, the other writes, the
raw bytes the one truth: a binary→json→binary round trip lands
byte-identical) and the live view (`--socket` — the feed renders
realtime, every packet line naming its source host:port and its
`#conn:txn` key; a request prints `pending`, its response completes the
exchange; the value dumps ride only with `--values` — off by default,
the file views always dump them; `^C` ends it clean). The live view
also records: `--record FILE` saves the feed to a trace file while it
renders — the received PVMB blocks land verbatim (0600, flushed and
appended across recorder sessions, the feed's per-connect header the
session boundary), a record in the file is byte-identical to the one
the daemon's own `--capture` writes, and any reader takes the file for
captured (the views, the converter, `--replay`) — `--trace-max-mb`/
`--trace-files` rotate it the capture's way (the recorder re-stamps a
header of its own on the shift). `--quiet` drops the
per-record render — the recorder runs silent, the banners and the save
tally stay. The feed is the family's one record contract: the cache's
`trace-socket` subscribes the same way, so the cache's live wire
records to a file with
`--socket /tmp/modbus-cache-<listen-port>-trace.socket --record …`. The value dumps
under the lines cap at 16 words a block — a poller's repeats keep the
conversations readable; `--values-cap N|all` reshapes the cap (`all`
the full block) wherever the values render, and the answer index dumps
the whole block always.

## Usage

```bash
# capture: the cache's polls to the real device, the wire to a trace
python3 apps/modbus-replay/bin/modbus-replay.py --upstream inverter-lan:502 --capture sun2000-morning.pvmb
# a capture left running: rotate the trace at 100 MB, keep 5 backups
python3 apps/modbus-replay/bin/modbus-replay.py --upstream inverter-lan:502 --capture sun2000.pvmb --trace-max-mb 100 --trace-files 5
# pass-through inspector (no trace): the decoded frames at DEBUG
python3 apps/modbus-replay/bin/modbus-replay.py --upstream :502 --log-level DEBUG
# replay: the scraper debugs against the morning's trace, hardware-free
python3 apps/modbus-replay/bin/modbus-replay.py --replay sun2000-morning.pvmb
# the recorded device latencies, 10x faster than captured
python3 apps/modbus-replay/bin/modbus-replay.py --replay sun2000-morning.pvmb --replay-speed 10
# the reader face: the summary, the answer index, the conversations
python3 apps/modbus-replay/bin/modbus-replay-dump.py sun2000-morning.pvmb
# the conversations uncapped: the whole value block under every exchange
python3 apps/modbus-replay/bin/modbus-replay-dump.py sun2000-morning.pvmb --values-cap all
# convert between the shapes (the raw bytes are the one truth)
python3 apps/modbus-replay/bin/modbus-replay-dump.py sun2000-morning.pvmb --to json -o sun2000-morning.jsonl
# live: the conversations render off the running daemon's record feed
python3 apps/modbus-replay/bin/modbus-replay-dump.py --socket
# live: the feed saved to a trace file while it renders (the cache's feed too)
python3 apps/modbus-replay/bin/modbus-replay-dump.py --socket --record live.pvmb
python3 apps/modbus-replay/bin/modbus-replay-dump.py --socket /tmp/modbus-cache-15502-trace.socket --record cache-live.pvmb --quiet
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
| `--capture` | off | the trace file the wire dumps to (0600; the binary PVMB blocks by default, the v1 JSON lines per `--dump-type`; appends across runs) — without it the proxy runs pass-through (the record feed still carries the frames) (`$CAPTURE`) |
| `--dump-type` | `binary` | the trace's shape capture writes: `binary` (the PVMB blocks — every reader speaks both) or `json` (the v1 lines for a capture that wants `head`/`grep`/`jq`) (`$DUMP_TYPE`) |
| `--dump-socket` | `/tmp/modbus-replay-<listen-port>.socket` | the record feed's unix socket: the records push to the connected `modbus-replay-dump --socket` viewers (read-only, best effort); `none` binds no feed (`$DUMP_SOCKET`) |
| `--trace-max-mb` | `0` | rotate the trace file at this size in MB, keeping N backups (`0` = no size rotation — the capture appends unbounded) (`$TRACE_MAX_MB`) |
| `--trace-files` | `3` | the size rotation's backups to keep (`.1 .. .N`, the oldest dropped; each a complete trace) (`$TRACE_FILES`) |
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
> to authenticate — nothing to token (the record feed is read-only
> push on a unix socket: no verbs, no tokens, nothing a command could
> ride). The trace file holds the wire's values and names (a Waveshare
> capture carries the connection password raw, a suite-auth capture the
> PVA1 proof — a leaked trace can replay it): traces write 0600 and
> belong with the secrets. The
> full family story is [docs/SECURITY.md](../../docs/SECURITY.md).

## Testing

The suite is [`dev/suites/replay-regtest.py`](../../dev/suites/replay-regtest.py)
— capture against the fake inverter, both trace shapes, the walk's
torn-tail/resync story, the dump bin's views and converter, the record
feed, the byte-identical replay, the miss policies, the refusals:

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
│   ├── modbus-replay.py        # CLI entry, the ladder, validation, wiring
│   └── modbus-replay-dump.py   # the reader face: the views, the converter, the feed
├── lib/
│   ├── options.json            # the knob registry: the flags, the env twins
│   ├── options.py              # its loader (the canon fold, the protocol tree's timeout)
│   ├── config.py               # the resolution ladder (flag > env > default — no config file)
│   ├── statics.py              # static configuration loader (lib/defaults.json)
│   ├── trace.py                # the trace format: the writers (both shapes), the MBAP tap,
│   │                           #   the record feed, the replay index
│   ├── capture.py              # the capture proxy (the pipe + the tap)
│   ├── replay.py               # the replay server (the common face protocol over the index)
│   ├── man.py                  # the generated man pages' prose (common/render/manpage.py renders)
│   └── defaults.json           # the statics: the trace formats' identity, the miss codes
└── man/
    ├── modbus-replay.1         # the generated man page
    └── modbus-replay-dump.1    # the reader face's page
```

## License

modbus-replay is part of the pv-suite, licensed under the **BSD 3-Clause
License** — see the `LICENSE` file in the repository root.
