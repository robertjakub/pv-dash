# modbus-replay — done records

The open items live in the family-wide [docs/TODO.md](../../docs/TODO.md);
this file keeps the tool's done/history records, newest first.

## 2026-11-13 — the values cap, reshapeable (--values-cap N|all)

The value dumps under the lines always capped at 16 words a block — the
conversations showed two 8-word lines and `…(+N more)` on a wider read
(a 38-register poll rendered 16 words + `(+22 more)`), the answer index
dumped the full block. The split stays (the ruling): all values once in
the index — one block per unique query, whatever the ask count — and a
peek in the conversations, whose job is the flow diagram; a poller's
repeats would turn it into a wall of hexdumps. What the reader lacked
was the escape hatch. Now `--values-cap N|all` reshapes the cap
wherever the values render: the conversations (the file views, no
companion flag needed — they dump by default) and the live view's
`--values` dump (where `--values-cap` without `--values` refuses — the
cap shapes the dump, it turns nothing on). `all` dumps the whole block;
an integer ≥ 1 spells the cap; anything else refuses at the parse (rc
2, the CLI misuse — the shape renders as `.BI --values-cap " N|all"` on
the man page, `common/render/manpage.py` now honors a typed flag's
explicit metavar, which moved no other row). The default 16 rides one
constant (`DEFAULT_VALUES_CAP` beside `DEFAULT_FEED`); the answer index
stays uncapped on purpose (it is the reference render — capping it
would degrade its job). The suite captures a 20-register read against
the fake and pins the default cap (+4 more, the index's third line
present), `all` (the marker gone), `8` (+12 more), both parse refusals,
the live companion refusal, the live view capped at 4 on the wide read
(+16 more), and the summary/loopback/feed posture for the new capture.

## 2026-11-13 — the dump's views name each packet's source

The trace records always carried the packet's own `peer` (the client
on the c2d/req records, the device on the d2c/rsp records), but the
reader face rendered it only in the conversations head (`client ...`)
— the answer's source never showed, the per-packet lines said only
`req`/`rsp`/`raw`. Now: every packet line in the conversations and the
live view carries its source host:port ahead of the direction word
(`127.0.0.1:54321  req  FC3 ...`), the conversations
head names BOTH ends of the pipe (`conn 1  client 127.0.0.1:54321
device inverter-lan:502` — the device from the block's d2c records,
falling back to the run header's upstream posture), and the live
view's block head labels the end its opening record actually speaks
for (`device ...` when a d2c record opens the block — it used to label
the device a client). The answer index stays peer-free on purpose (it
folds every connection's asks into one line — the winner's peer would
be an accident of ordering). No format change: `peer` rode both shapes
from day one, the converter passes it through verbatim. The live view
also gained the `--values` knob: the value dumps (the address-prefixed
words, the bit strings) ride only with it — OFF by default, a busy
feed stays one line a frame (the file views dump the values always;
`--values` on a file view refuses with a one-liner). The suite checks
the sources on the shipped example, the captured trace (both ends in
the head, the answer's src on the rsp line), the live view (the srcs,
the values hidden by default and back under `--values`) and the file
refusal.

The pairing question ("two clients on the relay — is the conversation
the correct one?") got the honest audit plus the hardening: two
clients never cross-paired BY CONSTRUCTION (each accepted client gets
its own upstream connection and its own conn id; a response can only
arrive on the socket pair that carried its request; the index keys by
(session, conn) — the dump groups by the same key). The soft spot was
PIPELINING within one connection: the index kept only the most recent
open request per conn, so a client with two outstanding requests
(Modbus/TCP allows it, the MBAP txn id exists for it) mispaired — the
first response orphaned in the conversations, the replay answers still
correct (the index keys by query identity). Now the pairing is
txn-aware: a response pairs with its request by the MBAP transaction
id within their connection, the most recent still-open request
standing in for a device that echoes a foreign id. The suite gained
the two-client section: two sockets interleaved (fc3/fc4/fc3-32003/fc6
across the conns), the pipelining probe (two requests sent before
either answer is read), the independent walk asserting every response
rode its request's conn + txn, and the dump's conversations keeping
the clients in their own blocks with zero orphans.

The pairing key then went on-screen: every packet line in the
conversations and the live view carries its `#conn:txn` token after the
source (`127.0.0.1:54321  2/7711  req  FC3 ...` — the txn re-derived
from the raw frame's MBAP head, `-` for the raw records: the
handshakes, the framing lost). The pair shows both halves' keys, so a
device that echoes a foreign txn id exposes itself right on the line
(`2/7711 req ... -> ... 2/99 rsp`); the answer index stays key-free
(the replay renumbers the txns, the winner's would be an accident of
ordering).

## 2026-11-13 — the capture face never times a leg (the flapping-scraper bugfix)

The capture proxy armed BOTH pump legs with the modbus-timeout as a
recv timeout — the client leg took it whenever `--client-timeout`
stayed unset (the else-branch), the upstream leg carried it always —
so either pump's recv timeout ended the pair modbus-timeout (3s) into
the client's first silence. A scraper polling every 10s lost its pair
between every poll: the next read hit EOF (`connection closed by
peer` — one `reachable`, one `unreachable`, the transition-only
logging hides the flapping), re-dialed, and the capture's conn #
climbed one per poll with each pair serving exactly one cycle. The
face's own contract ("only --client-timeout kicks the silent") and the
shared ladder's order (common/modbus/server.py sets a timeout only
when client_timeout is truthy) both said the code was wrong. Now: the
client leg takes a timeout ONLY from `--client-timeout` (300s default,
0 = never), the upstream leg runs untimed (`settimeout(None)`) — the
pipe never times a leg; a device that stops answering surfaces through
the CLIENT's own modbus timeout (the scraper's read raises, the
scraper hangs up, the pair ends), a device that dies mid-answer still
EOFs the d2c pump. Found against a live rig (scraper → capture → a
second proxy → real hardware) and reproduced locally at exact
+3.000s; the diagnosis trap: the piped bytes were identical to the
direct run's and the direct connection lived — the kick lived in the
capture's legs, not the path. The suite gained the poll-gap section
(the regression both ways): the pair survives a 2.5s idle past a 1s
`--modbus-timeout` on one connection (the reply asserted minus the txn
echo — the pipe echoes the client's txn per exchange) and
`--client-timeout 1` ends a silent pair (a request in flight would
race the kick — the check stays silent on purpose).

## 2026-11-13 — the trace goes binary (`TRACE-BINARY.md`'s wave, twelve rulings)

The binary-trace wave: the trace gains a binary shape BESIDE the JSON
one (rulings taken in `TRACE-BINARY.md`, the draft dissolved into these
surfaces on landing). `--dump-type binary|json` (env `DUMP_TYPE`,
default **binary**) picks what capture writes: the binary PVMB file —
one magic+version+started+posture header block per run, then one
length-framed CRC-checked record block per frame (big-endian, f64 ts,
the raw frame bytes verbatim; the decoded fields re-derive on read —
the frame is the one truth, the JSON's echo is its readability sugar
and the v1 shape stays frozen); every reader speaks both shapes (the
first bytes pick the walk), nothing breaks. The walk keeps what a torn
tail leaves (the JSON walk skips torn lines instead of refusing the
file — the old hard `not JSON` refusal died), the multi-run headers
are the session boundaries, a mid-file CRC failure resync-scans to the
next header. The auth handshakes (the PVA1 proof — a real `auth_mac`
in the example — the Waveshare password, the raw verdicts) export as
named raw records: the tap peels them before the first clean frame
(fixing the OK-glue: the device's first frame used to flush into the
verdict's raw record, lost from the index) and the pump's finally
flushes the residual buffer (a short `ERR` verdict plus EOF is traced
now). The reader face is its own bin, `bin/modbus-replay-dump.py` (its
own man page, its own argparse — no registry knob): the summary, the
answer index (per unique query: the recorded reply the replay will
serve, the data words as hex, the latency, the ask count), the
conversations (the per-connection query→answer diagram, the overlap
notes, the unpaired marked in place), the converter (`--to
json|binary -o OUT` — the raw bytes the one truth, a
binary→json→binary round trip byte-identical) and the live view: the
record feed (`--dump-socket`, bound by DEFAULT at the family's derived
`/tmp/modbus-replay-<listen-port>.socket`, `none` refuses) pushes
every record to the connected dump tools in the binary encoding
verbatim — capture the real wire, replay the session it serves —
read-only push (no verbs, no tokens: the no-control-plane ruling
stands), best-effort (a slow subscriber drops, the file keeps
everything). The example trace ships at
extras/examples/modbus-replay-trace.pvmb (generated by
`dev/generators/trace_example.py`, `--exchanges N` renders longer bench
samples, `--check` pins the default render, the lint-gates suite gates
it). The README's trace section is the format's byte-layout reference
now; the suite grew both shapes' checks, the torn/resync story, the
converter's round trips and the live feed.

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
