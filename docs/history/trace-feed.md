# trace-feed — the cache speaks the replay's record feed

Status: **landed** (Nov 13 2026). The ask: a live socket-based wire
trace on modbus-cache, speaking the same protocol modbus-replay's
record feed already speaks — `modbus-replay-dump --socket` renders the
cache's traffic live with zero consumer changes. The draft (this file,
before the flight) proposed four commits; three flew — the two cache
commits (the knobs, the emit points) landed as one per-tool commit,
the family's per-tool discipline beats a broken intermediate.

## Why the cache at all

modbus-replay capture mode already traces any cache leg — insert it in
the wire, subscribe the feed. But the pipe sees bytes only. The cache
knows **provenance**: hit vs forwarded vs diag vs refused, and which
exception the device actually sent. That is the one story the sidecar
cannot tell, and it rode the record's existing `note` slot — no format
bump, no new kind.

## The rulings (as flown)

1. **Feed-only, no trace file.** No `--capture` sibling on the cache —
   a cache trace file would collide with the seal ruling (dump/key
   seals every state file) and the ask is live. A sealed file is a
   later ruling if wanted.
2. **Same wire format, byte for byte.** The PVMB record (ts, kind,
   conn, peer, note, raw) is generic already;
   `common/modbus/trace.py` is the family's one home now — the format
   identity rides the protocol tree's `trace` section
   (shared/suite/protocol.json), the replay's lib keeps `FrameTap` +
   `TraceIndex` and re-exports the shared module.
3. **The knobs are `trace-socket` + `trace-sources`** (the registry's
   dash spelling — the draft's `trace/socket` slash was the node-path
   filing, the console words take the dashes; the `live` paths are
   trace/socket + trace/sources):
   - `trace-socket`: `none` (the built-in default — off, the
     production face opens no wire dump nobody asked for) | `default`
     (the derived `/tmp/modbus-cache-<listen-port>-trace.socket`) | a
     path. The `-trace` suffix is **mandatory**: the control plane
     owns `/tmp/modbus-cache-%d.socket`
     (apps/cache/lib/config.py:26) and the feed's bind unlinks first —
     the un-suffixed spelling would unlink the control wire.
   - `trace-sources`: `all` (the default) | `client` (the client face
     only) | `upstream` (the upstream face only: the poller, the
     forwards, the auth marker). Whole voices on/off, never sampling —
     a dropped voice is stated by the knob, a dropped frame would be a
     lie (the orphan is the device-died signal). The source set is
     **closed**: the control wire, /metrics, the state dumps and the
     audit forward are not Modbus and already watched; diag rides the
     client face (a `diag` word splits it out only if a monitor's
     polling ever drowns it).
   - A failed bind rolls the knob and the feed back to the standing
     value — the old feed stands; the wire answers err.
4. **Live rebind for ALL transitions.** Every `set trace-socket`
   rebuilds the feed — none ↔ default ↔ path ↔ another path, the same
   path included, no no-op case: close (the subscribers see EOF, they
   re-subscribe — best-effort viewers), unlink, bind; `none` just
   closes. The reload path (SIGHUP, apply_config) rebinds only on a
   value change — restoring the standing values is not a set. The
   socket chmods **0600 at bind** — the chmod went into the shared
   FeedSocket, so the replay's own
   `/tmp/modbus-replay-<port>.socket` stops being umask-dependent.
5. **All four voices on.** The auth handshake emits a byte-less marker
   — the cache knows exactly where its handshakes run
   (`common/modbus/client.py:100`), unlike the replay's dumb pipe tap,
   so no PVA1 proof and no waveshare password ever rides the feed.
6. **The upstream conn ids live in their own space**
   (`UPSTREAM_CONN_BASE` 100000 + the connection serial; the client
   face counts its sessions from 1). The feed's pairing key is
   `(session, conn, txn)` and the client's txn survives the forward
   verbatim — colliding conn numbers would cross-pair a client request
   with the device's reply.
7. **`peer` names the conversation partner, not the byte producer.**
   Client-face records carry the client's endpoint on req AND rsp; the
   note carries the producer (`served from cache`, `forwarded — device
   reply`, `forwarded — upstream failed`, `refused: …`,
   `served from last poll (the device rejects: exception N)`,
   `diag registers`). The device's true bytes appear as the upstream
   voice's own conversation. kind stays wire-true: req = arrived,
   rsp = sent.

## The voices — the emit-point map (as flown)

| voice | where | records |
|---|---|---|
| client face | `Proxy.respond()` (apps/cache/lib/proxy.py `_rsp`), `Proxy.malformed` | req (the client's frame) + rsp (the answer the cache served): cache hit, forwarded miss, diag, failed-leaf exception, the five write refusals, the unit/shape in-band exceptions; the malformed MBAP head rides as the byte-less marker (the bytes are read_frame's already — `malformed MBAP — bytes withheld`) |
| upstream, poller voice | `Upstream.read` (apps/cache/lib/upstream.py) | the background block polls (note `poll`), the device's exceptions — peer = the device endpoint, own conn space; a failed exchange rides no reply record (the orphan = the device died) |
| upstream, forward voice | `Upstream.forward` | the uncached reads and the writes verbatim — the client's own txn survives, so the client-face request pairs by eye; the device's verdict; the `GATEWAY_FAILED` silence (an orphan, documented, not synthesized) |
| the auth marker | `Upstream.after_connect` | one byte-less raw record, note `PVA1 handshake (bytes withheld)` / `waveshare password (bytes withheld)` — the conversations view still shows the handshake happened |

## The poller voice's volume — the answer that closed the question

One req+rsp pair per poll-plan pool per cycle: `2 × pools / interval`
records a second, steady state (~0.2-0.4/s small profile, ~1-2/s
sun2000_full at interval 10s). The split-sweep burst roughly doubles it
while a device dies. There is **no limiting**: every req/rsp of the
selected voices logs, no sampling, no rate limiter — the ceiling that
matters is the consumer's (the 1s slow-subscriber drop; the daemon
never backpressures; no file). The volume answer is the sources knob.

## The gates that caught the wave

- the SBOM gate refused `zlib` in common (the lifted encoder) —
  reviewed into the stdlib allowlist, the pair regenerated
- the options layout lint re-rendered the new rows canonically
  (`dev/gates/options.py format`)
- the drift ledger demanded the knob's test before the wave could call
  itself swept (`knob:cache:trace-sources` → the cache-regtest section)
- the regtest's pinned root ?-listing gained `trace` (the node lists)

## The cache-regtest section (the flown checks)

the derived `-trace` path exists and is 0600 · the PVMB header peek ·
the posture names the cache · the poller voice's own conn space · the
hit names `served from cache` with the client as the peer on both
records · the forward carries the client's own txn upstream ·
`forwarded — device reply` · the write refusal and the diag notes ·
the sources walk (client silences the poller, upstream silences the
client face, `bogus` refuses, all restores) · the rebind walk (none →
default → none → default, the same-path set rebinds, the subscribers
see EOF) · the control plane answers beside the feed throughout · the
suite-auth upstream session: the byte-less marker, zero PVA1 bytes.

## The landed ledger

`common/modbus/trace.py` (the lift + the 0600 FeedSocket), the replay
rewired, the cache's two knobs + the ~13 emit points, the regtest
section, the docs regen (the man page, the MANUAL, the README's trace
rows, the conf + env examples, the SBOM pair, the drift ledger), the
CHANGELOG entry. The draft died with the flight (this file is the
record).
