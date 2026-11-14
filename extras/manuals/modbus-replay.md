# The modbus-replay manual

A dependency-free (Python stdlib only) Modbus TCP capture/replay sidecar: it
pipes the wire to a trace file in capture mode and serves the trace in
replay mode. Part of the pv-suite family.

## The family

- the replay is the debug sidecar: **it taps the chain's Modbus hops**
  (capture — the wire keeps flowing, the trace grows beside it) **or stands in
  for the device** (replay — the client debugs against the recorded hardware).

    the device (the sun2000 — or the fake standing in)
         |  Modbus TCP :502
         v
    modbus-cache :15502 ---- the one client slot, multiplexed
         |
         v
    modbus-scraper :9350 /metrics
         |
         v
    prometheus ---- the alert pack (extras/alerts/)
         |
         v
    the dashboard :8080

    modbus-replay rides beside any Modbus hop: the tap in capture,
    the recorded device in replay, the dump tool rendering.

- every hop is optional: the scraper can poll the device straight (no cache),
  the dashboard can read a collector you already run, the fake can stand in
  for the device — and the suite auth can run on either Modbus hop
  independently (the peers must speak the same scheme with the same key).

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

The sidecar is two faces over one trace format: capture pipes and taps,
replay indexes and answers — the raw frames the one truth either way.

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
## Signals

| signal | effect |
|---|---|
| `SIGHUP` | logged and ignored — there is no live layer to re-apply; restart to change the posture |
| `SIGTERM` / `SIGINT` | graceful shutdown with a session summary (connections piped, frames both ways, bytes, undecoded flushes — or sessions served, answered, misses) |
| `SIGUSR2` | dumps the thread stacks (the family's faulthandler hook) |

## Configuration

- there is no config file — the sidecar's posture is fixed at start: **flag >
  env (the bare upper-snake twins) > the built-in defaults**, the knobs table
  below IS the flags table. A wrapper script (or the `apps/modbus-replay/dev`
  launcher) is where a standing posture lives.

## Runtime control

- none — the no-control-plane ruling: no control server, no cli, no
  set/show/clear, nothing to reload. The posture is fixed at start; a change
  is a restart with different flags (`SIGHUP` is logged and ignored). The
  observability face is `modbus-replay-dump` — the views, the live feed, the
  recorder.

## Access control

- nothing to gate, by design: the Modbus port forwards bytes between client
  and device, and the record feed is a read-only binary push — no verbs, no
  tokens, nothing a command could ride (the no-control-plane ruling). The
  trace file is created `0600` and belongs with the secrets — a Waveshare
  capture carries the connection password raw, and a leaked trace can replay a
  PVA1 proof at any server holding the key.

## Metrics

- none — the sidecar publishes no `/metrics`; the dump tool is the
  observability face (the summary, the answer index, the conversations, the
  live view).

## Audit logging

- no audit file, no hash chain — the sidecar takes no commands, so there is
  nothing to repudiate: the trace IS the record (every frame verbatim,
  `0600`), and the lifecycle rides the log (the startup posture line, the
  shutdown's session summary, `SIGUSR2`'s thread stacks).

## Register maps

- register-agnostic — no profile, no types, no gains: the replay serves
  recorded bytes by request identity (unit + function code + PDU), the raw
  frames are the one truth. The dump tool decodes for reading only.

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

## Deployment

- none by design — the sidecar is a checkout tool: run it from a checkout
  (`apps/modbus-replay/dev` is the launcher) or a plain `python3` line, next
  to the tools it debugs. No container image, no Nix package, no NixOS module,
  no service unit — a deployment would defeat the sidecar (it debugs
  deployments, it is not one).

## The docs map

| document | what it carries |
|---|---|
| `docs/SECURITY.md` | the security posture and the F-findings the pages cite (F9 the secrets, F10 the audit chain, F11 the trusted-LAN test tool, F12 the secret files, F13 the token floors, F16 the alert pack, F18 the dump split, F21 the web face) |
| `docs/specs/ACL.md` | the ACL gate semantics — the rule chains, the ip-prefix grammar, the standalone acl files, the tools, and where each tool's support stops |
| `docs/specs/MODBUS.md` | the Modbus wire specs — the function-code support maps, the suite and Waveshare auth handshakes, the diagnostics block |
| `docs/DESIGN.md` | the design — the architecture, the decisions, the postures the tools share |
| `nixos/README.md` | the NixOS side — the option maps rebuilt from `module.nix`, the flake, the packages |
| `docker/README.md` | the container side — the images, the compose topologies (the demo and the prod split), the env examples |
| `shared/profiles/README.md` | the device profile format — the schema, the semantics, the shipped devices |
| `extras/alerts/` | the alert rules pack — one rule file per watched exporter, every alert naming the audit events it correlates with |
| `docs/book/` | the assembled book (these manuals gathered, the specs beside) |
| `docs/history/` | the wave records — how the suite got here, `front-page-split.md` among them |
| `docs/TODO.md` | the open items |
| `CHANGELOG.md` | the unreleased changes and the current release |

## The docs map

| this tool's documents | what they carry |
|---|---|
| `apps/modbus-replay/README.md` | the front page — the description, the quick how-to, Security, License |
| `apps/modbus-replay/lib/options.json` | the registry — the one row per knob (the knobs table renders from it) |
| `apps/modbus-replay/man/` | the generated man pages (`modbus-replay --man`, `modbus-replay-dump --man`) |
| `extras/examples/modbus-replay-trace.pvmb` | the worked example trace — two sessions, both handshakes, the refused write (rendered by the dump tool) |

| document | what it carries |
|---|---|
| `docs/SECURITY.md` | the security posture and the F-findings the pages cite (F9 the secrets, F10 the audit chain, F11 the trusted-LAN test tool, F12 the secret files, F13 the token floors, F16 the alert pack, F18 the dump split, F21 the web face) |
| `docs/specs/ACL.md` | the ACL gate semantics — the rule chains, the ip-prefix grammar, the standalone acl files, the tools, and where each tool's support stops |
| `docs/specs/MODBUS.md` | the Modbus wire specs — the function-code support maps, the suite and Waveshare auth handshakes, the diagnostics block |
| `docs/DESIGN.md` | the design — the architecture, the decisions, the postures the tools share |
| `nixos/README.md` | the NixOS side — the option maps rebuilt from `module.nix`, the flake, the packages |
| `docker/README.md` | the container side — the images, the compose topologies (the demo and the prod split), the env examples |
| `shared/profiles/README.md` | the device profile format — the schema, the semantics, the shipped devices |
| `extras/alerts/` | the alert rules pack — one rule file per watched exporter, every alert naming the audit events it correlates with |
| `docs/book/` | the assembled book (these manuals gathered, the specs beside) |
| `docs/history/` | the wave records — how the suite got here, `front-page-split.md` among them |
| `docs/TODO.md` | the open items |
| `CHANGELOG.md` | the unreleased changes and the current release |

## Source layout

the sidecar is flat and stdlib-only — two bins, one lib package, the
generated man pages beside; the checkout launcher (`dev`) runs it straight
from the tree. No container image, no Nix package, no NixOS module — a
deployment would defeat the sidecar (it debugs deployments, it is not one).

    apps/modbus-replay/
    ├── bin/
    │   ├── modbus-replay.py          # the daemon: capture, pass-through, replay — the
    │   │                            #   CLI, the tap wiring, the signal handling
    │   └── modbus-replay-dump.py     # the reader face: the views, the converter, the
    │                                #   live view, the recorder
    ├── lib/
    │   ├── capture.py                # the capture face: the pipe + the shadow copy
    │   ├── replay.py                 # the replay face: the answer index, the miss
    │   │                            #   policies, the recorded latencies
    │   ├── trace.py                  # the trace face: the FrameTap (the MBAP
    │   │                            #   reassembler), the PVMB writer, the walk
    │   ├── statics.py                # the trace format's identity, the miss codes
    │   │                            #   (lib/defaults.json)
    │   ├── options.py + options.json # the registry: the one row per knob
    │   ├── config.py                 # the env layer + the flags (no config file)
    │   └── man.py                    # the generated man pages
    ├── man/                          # the generated man pages (the daemon + the dump)
    └── dev                           # the checkout launcher

the family's `common/` package (the trace writer, the record encoding) is
imported by path from the checkout — the sidecar shares no service packaging
with the tools it debugs.

## Troubleshooting

- **it will not start** — the bind failures and the flag refusals answer one
  clean line + exit 1 (capture and replay are mutually exclusive, a knob
  without its file refuses); `--help` and the man page carry the startup
  surface.

- **the trace looks torn** — a killed capture leaves a readable file: the walk
  keeps what parsed and notes the loss (the section above); a mid-file CRC
  failure resyncs at the next run header — the records between the tear and
  the re-anchor are lost with the tear.

- **replay answers exception 11** — a request the trace never recorded (the
  miss): the log spells the request — that is the poll-planning debug;
  `--replay-miss zero` keeps a changed poll plan running instead.

- **the dump shows nothing on the live view** — the feed socket path is the
  derived `/tmp/modbus-replay-<listen-port>.socket` (the cache's feed spells
  its own); a slow subscriber is dropped by design, the file keeps every
  record.

- **deeper** — `--log-level DEBUG` logs the framing decisions; `SIGUSR2` dumps
  the thread stacks.

## Testing

- the suite is `dev/suites/replay-regtest.py` — capture against the fake
  inverter, both trace shapes, the walk's torn-tail/resync story, the dump
  bin's views and converter, the record feed, the byte-identical replay, the
  miss policies, the refusals. Every scenario must end with the daemon alive
  and **zero tracebacks** in the logs.

    dev/battery/battery.py replay    # the replay profile: the regtest (the suites refuse
                                #   without the runner's PV_RUN_DIR)

- the suites **always run through the battery runner**
  (`dev/battery/battery.py`) — it owns the run dir, the port slots and the
  tally, and a standalone suite run refuses (a hand-run collides across
  sessions). A new behavior ships with a check: a scenario that fails without
  it and names the registry rows it pins.

The ?/TAB pools, `show knobs` and `help config` all render from the same
rows this page was generated from.
