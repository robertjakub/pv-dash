# The modbus-replay manual

A dependency-free (Python stdlib only) Modbus TCP capture/replay sidecar: it
pipes the wire to a trace file in capture mode and serves the trace in
replay mode. Part of the pv-suite family.

- the daemon's own `--help` and the man page (`modbus-replay --man`) carry the
  startup surface; this page carries the full reference.

- **generated** from `lib/options.json` (the one-knob-one-source rows) by
  `dev/generators/manual.py` — edit the registry (or the REF data in the
  generator) and re-run, never this file.

## Run it

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
    # live: the conversations render off the running daemon's record feed
    python3 apps/modbus-replay/bin/modbus-replay-dump.py --socket
    # live: the feed saved to a trace file while it renders (the cache's feed too)
    python3 apps/modbus-replay/bin/modbus-replay-dump.py --socket --record live.pvmb

- exit codes: `0` = ran (SIGTERM/SIGINT: the graceful shutdown), `1` = invalid
  configuration or a failed bind (reason on stderr), `2` = CLI misuse.

- the daemon is a **sidecar, not a deployment**: no container image, no Nix
  package, no service module — run it from a checkout
  (`apps/modbus-replay/dev` is the launcher) or a plain `python3` line, next
  to the tools it debugs.

- the startup surface is the flags and their bare env twins: **flag > env >
  the built-in defaults** — there is no config file (the sidecar has no
  control plane either: every knob is a startup knob). The knobs table below
  IS the flags table.

## How it works

| mode | knobs | what happens |
|---|---|---|
| capture | `--upstream HOST:PORT` (+ `--capture FILE`) | every client is piped to the device; the wire dumps to the trace |
| replay | `--replay FILE` | the trace is served: recorded responses answer matching requests |

- **capture mode is a pipe with a shadow copy.** Every accepted client is
  paired with an upstream connection to the device; bytes flow as they arrive,
  never held. A tap reassembles the MBAP frames from the piped bytes (both
  directions) and appends one record per frame to the trace file — timestamps,
  direction, the raw frame bytes. A frame the framing cannot parse still
  reaches the device and rides the trace raw — the auth handshakes ride
  exactly there (below). Without `--capture` the proxy runs pass-through (the
  decoded frames log at DEBUG only) — a quiet wire inspector.

- **no control plane** — that is the design: no JSON-lines control server, no
  `-cli` client, no runtime set/show. The debug surface is the Modbus port,
  the trace file and the log; the capture posture is fixed at start.

## Knobs

The tables spell the knob's registry key — the one internal name the wire,
the replies and the dispatch take; the set / clear column spells the console
words (the live path as words — the config files and the state dumps speak
them; the flat registry name answers the same set everywhere, the clients
translate). The `default` column is the registry's built-in default (the
resolver's last rung after flag > env > config); the namespaces group them.

### general

| knob | set / clear | kind | default | value | flag / env | description |
|---|---|---|---|---|---|---|
| `listen` | — | startup-only | 127.0.0.1:15503 | `HOST:PORT` | `--listen` / `LISTEN` | listen address HOST:PORT *(hidden)* |
| `upstream` | — | startup-only | — | `HOST:PORT` | `--upstream` / `UPSTREAM` | the device's Modbus TCP endpoint HOST:PORT (`:5502` = 127.0.0.1:5502) — capture mode |
| `capture` | — | startup-only | — | `FILE` | `--capture` / `CAPTURE` | the trace file the wire dumps to (0600) |
| `dump-type` | — | startup-only | binary | `binary\|json` | `--dump-type` / `DUMP_TYPE` | the trace's shape: binary (the PVMB blocks) or json (the v1 lines) |
| `dump-socket` | — | startup-only | — | `PATH\|none` | `--dump-socket` / `DUMP_SOCKET` | the record feed's unix socket (the dump tools' live view) |
| `trace-max-mb` | — | startup-only | 0.0 | `MB` | `--trace-max-mb` / `TRACE_MAX_MB` | rotate the trace file at this size in MB; 0 = no size rotation |
| `trace-files` | — | startup-only | 3 | `N` | `--trace-files` / `TRACE_FILES` | rotated trace backups to keep |
| `replay` | — | startup-only | — | `FILE` | `--replay` / `REPLAY` | the trace file to serve — replay mode |
| `replay-speed` | — | startup-only | 0.0 | `N` | `--replay-speed` / `REPLAY_SPEED` | replay the recorded device latencies, N times as fast as captured |
| `replay-miss` | — | startup-only | exception | `exception\|zero` | `--replay-miss` / `REPLAY_MISS` | what an unmatched request answers: a poll the trace never recorded |
| `client-timeout` | — | startup-only | 300.0 | `s` | `--client-timeout` / `CLIENT_TIMEOUT` | disconnect clients silent for this long |
| `modbus-timeout` | — | startup-only | 3.0 | `s` | `--modbus-timeout` / `MODBUS_TIMEOUT` | Modbus connect/read timeout in seconds |
| `local-time` | — | startup-only | off | `on\|off` | `--local-time` / `LOCAL_TIME` | log timestamps in the system time zone instead of UTC |
| `log-level` | — | startup-only | INFO | `DEBUG\|INFO\|WARNING\|ERROR` | `--log-level` / `LOG_LEVEL` | log verbosity |
## The trace format

- the trace is 0600 at rest (the wire carries values — and a Waveshare capture
  carries the connection password raw; the trace belongs with the secrets).
  Two shapes, the same feature set — `--dump-type` picks what capture writes,
  every reader speaks both.

- **binary** (the default) — a `PVMB` file: one header block per run, then one
  length-framed, CRC-checked block per record. About half the bytes of the
  JSON spelling, no parser on the read path, and a torn tail costs one record
  instead of the file.

- **json** (the v1 spelling) — JSON lines: one record per frame, the decoded
  fields (`txn`, `fc`, `addr`, …) riding beside the raw hex — the
  `head`/`grep`/`jq` spelling.

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

- the record walk: the header at offset 0 anchors it; a mid-file `PVMB` block
  is a later run's header — the session boundary (the trace **appends across
  runs**, a multi-run file is a longer history; the conn ids restart each
  run). A block that runs past EOF is a torn tail: the walk keeps what parsed
  and notes the loss — a killed capture leaves a readable trace. A mid-file
  CRC failure resync-scans for the next header; the records between the tear
  and the re-anchor are lost with the tear. The JSON walk reads the same story
  line-wise: a torn line skips (noted), a later header line is the boundary. A
  foreign file or a future version refuses with a clean one-liner.

- **a capture left running grows unbounded** — `--trace-max-mb` rotates the
  trace at that size, keeping `--trace-files` backups (`0` = no size rotation,
  the default). At the size the backups shift (`trace.pvmb.1` ← `trace.pvmb.2`
  ← …, the oldest dropped), the file reopens fresh and stamps a new run
  header: the fresh capture keeps the plain name, and **every backup is a
  complete trace of its own** — any reader takes each for captured (the views,
  the converter, `--replay` serve one slice at a time). A record is the
  rotation boundary: a block never straddles two files. The dump tool's
  `--record` carries the same pair and rotates the same way (the recorder
  re-stamps a header of its own — the feed's posture, now).

    {"format":"pv-suite-modbus-trace","version":1,"started":"…","tool":"modbus-replay","mode":"capture","upstream":"inverter-lan:502"}
    {"ts":1794588996.048,"dir":"req","conn":1,"peer":"127.0.0.1:64824","raw":"004d…","txn":77,"unit":1,"fc":3,"addr":32064,"count":2}
    {"ts":1794588996.048,"dir":"rsp","conn":1,"peer":"inverter-lan:502","raw":"004d…","txn":77,"unit":1,"fc":3,"bytes":4}

- `dir` speaks the client's view (`req` = client to device, `rsp` = the
  device's answer, `raw` = the framing lost); exception responses record their
  code (`"exc": 2`).

| pair | json | binary | win |
|---|---|---|---|
| thin (12B + 14B frames) | ~270 B | ~107 B | ~2.5× |
| fat read reply (246B frame) | ~540 B | ~285 B | ~1.9× |

- the auth handshakes do not ride MBAP — the suite auth's PVA1 proof is a raw
  52-byte frame (magic + nonce + HMAC-SHA256), the Waveshare password raw
  ASCII, the verdicts raw `OK`/`ERR`. The tap peels and names them before the
  first clean frame — the conversations render the handshake whole (`PVA1 handshake proof`,
  `Waveshare password`, `auth verdict`) and the device's first real frame
  survives the verdict glue — and the bytes ride the trace verbatim as raw
  records either way: one more reason the trace is 0600 (a leaked trace can
  replay a PVA1 proof at any server holding the key).

- a worked example ships with the suite —
  `extras/examples/modbus-replay-trace.pvmb` (two sessions, both handshakes,
  the polls, the refused write, deterministic bytes; rendered by
  `modbus-replay-dump extras/examples/modbus-replay-trace.pvmb`).

## Replay mode

- at start the daemon indexes every recorded response under its request's
  identity — unit + function code + PDU bytes, transaction ids aside (the
  replay speaks the client's own ids) — and answers each incoming request with
  the most recent recorded response, exception frames included: the device's
  truth, verbatim.

- `--replay-speed` replays the recorded device latencies (the recorded `rsp.ts − req.ts`
  gap: `1` = as captured, `N` = N times faster, `0` = immediately).

- a request the trace never recorded answers per `--replay-miss`:
  **`exception`** (the default — Modbus exception 11, gateway target device
  failed to respond: a miss is loud in the client's error counters) or
  **`zero`** (a zero-filled reply of the right shape — reads answer zero data,
  writes answer their echoes, so a changed poll plan keeps running and shows
  its shape). Either way the miss logs, with the request spelled out — that
  log is the poll-planning debug.

- replay is a record, not a device: nothing accumulates. A write answers its
  recorded response and a following read still reads what the hardware read at
  capture time — the write-through behavior you are debugging sees the
  recorded world, which is the point (compare the client's behavior against
  the trace's truth, not against a simulation of it).

## The record feed and the dump tool

- every record the trace writer encodes also fans out to the **record feed** —
  `--dump-socket` binds a unix stream socket at the family's derived path
  (`/tmp/modbus-replay-<listen-port>.socket`, bound by default, the word
  `none` turns it off). The feed is read-only push in the binary record
  encoding verbatim — no verbs, no tokens, nothing a command could ride (the
  no-control-plane ruling stands); a slow subscriber is dropped, the FILE
  keeps every record. Capture mode pushes the real wire's records; **replay
  mode pushes the session it serves** — the requests, the recorded answers
  with the applied latencies, the misses as the frames they are.

- the reader face is its own bin, `bin/modbus-replay-dump.py` (its own man
  page): the three static views of a trace file (the summary, the answer index
  — per unique query, the recorded reply the replay will serve with the
  recorded latency and the ask count — and the conversations, the
  per-connection query→answer diagram — one block per connection naming both
  ends of the pipe, every packet line carrying its source host:port and its
  `#conn:txn` pairing key (the record's own `peer`, the MBAP transaction id —
  a device echoing a foreign id shows right there)), the converter (`--to json|binary -o OUT`
  — either shape reads, the other writes, the raw bytes the one truth: a
  binary→json→binary round trip lands byte-identical) and the live view
  (`--socket` — the feed renders realtime, every packet line naming its source
  host:port and its `#conn:txn` key; a request prints `pending`, its response
  completes the exchange; `^C` ends it clean).

- the value dumps ride only with `--values` (off by default on the live view,
  the file views always dump them); the dumps cap at 16 words a block — a
  poller's repeats keep the conversations readable; `--values-cap N|all`
  reshapes the cap (`all` the full block) wherever the values render, and the
  answer index dumps the whole block always.

- the live view also records: `--record FILE` saves the feed to a trace file
  while it renders — the received PVMB blocks land verbatim (0600, flushed and
  appended across recorder sessions, the feed's per-connect header the session
  boundary), a record in the file is byte-identical to the one the daemon's
  own `--capture` writes, and any reader takes the file for captured (the
  views, the converter, `--replay`) — `--trace-max-mb`/`--trace-files` rotate
  it the capture's way (the recorder re-stamps a header of its own on the
  shift). `--quiet` drops the per-record render — the recorder runs silent,
  the banners and the save tally stay.

- the feed is the family's one record contract: the cache's `trace-socket`
  subscribes the same way, so the cache's live wire records to a file with
  `--socket /tmp/modbus-cache-<listen-port>-trace.socket --record …`.

## Signals

| signal | effect |
|---|---|
| `SIGHUP` | logged and ignored — there is no live layer to re-apply; restart to change the posture |
| `SIGTERM` / `SIGINT` | graceful shutdown with a session summary (connections piped, frames both ways, bytes, undecoded flushes — or sessions served, answered, misses) |
| `SIGUSR2` | dumps the thread stacks (the family's faulthandler hook) |

## Testing

- the suite is `dev/suites/replay-regtest.py` — capture against the fake
  inverter, both trace shapes, the walk's torn-tail/resync story, the dump
  bin's views and converter, the record feed, the byte-identical replay, the
  miss policies, the refusals. Every scenario must end with the daemon alive
  and **zero tracebacks** in the logs.

    dev/battery/battery.py replay    # the replay profile: the regtest (the suites refuse
                                #   without the runner's PV_RUN_DIR)

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.
