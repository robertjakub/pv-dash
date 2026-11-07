# The Modbus protocol — the wire the suite speaks

This is the reference for the Modbus implementation across the family: the
**scraper** (client), the **cache** (server toward its own clients *and*
client toward the inverter) and the **fake inverter** (server). The wire
core and the shared primitives live in the **`common/modbus`** package —
one implementation, stdlib only (`protocol.py` the wire core,
`client.py` the connect/reply ladders, `writes.py` the write shapes) —
and the per-tool layers stack on it (`scraper/lib/protocol.py`,
`cache/lib/upstream.py`, `cache/lib/proxy.py`, `inverter/lib/inverter.py`).
The dashboard never speaks Modbus.

One scheme, three shapes: every tool runs the same Modbus TCP dialect —
the same MBAP framing, the same exception rules, the same optional `suite`
auth handshake — with per-tool limits from each tool's `lib/static.json`.

---

## 1. Transport and framing

**Modbus TCP over TCP only** — no UDP, no serial/RTU, no CRC, no TLS.
Clients use `socket.create_connection`; servers `bind`/`listen`. Every
multi-byte field is **big-endian** (`struct` format `>`).

Each frame is the standard **MBAP header (7 bytes) + PDU**, read with
`recv_exact` (`common/modbus/protocol.py`), which loops until it has exactly
`n` bytes and raises `ConnectionError` on a closed peer:

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `txn` — transaction id | client-incremented `(txn + 1) & 0xFFFF`, starts at 1; servers echo it |
| 2 | 2 | `proto` — protocol id | must be `0`; nonzero → exception 03 (cache) or hard error (clients) |
| 4 | 2 | `length` | bytes following the field, i.e. **unit id + PDU**; accepted range `2 .. MAX_PDU + 2` |
| 6 | 1 | `unit` — unit id | the request's unit; servers echo it back |
| 7 | `length − 1` | PDU | function byte + data |

A bad `length` (out of bounds) means the reader **closes the connection
without replying** — the frame is not even parseable enough to answer.
`MAX_PDU` is 253 for the cache and scraper, **260** for the fake, so the
effective `length` ceiling is 255 vs 262. `MAX_COUNT` (registers per read)
is 125 everywhere.

Default endpoints: the real inverter on `:502`; the fake's Modbus listener
on `127.0.0.1:5502`; the cache's Modbus listener on `127.0.0.1:15502`; the
default upstream for scraper and cache is `127.0.0.1:5502`. (The scraper's
`--listen` port is its HTTP `/metrics` endpoint — not Modbus.)

---

## 2. The suite auth handshake (PVA1)

Implemented once in `common/modbus/protocol.py` (`auth_handshake_client` /
`auth_handshake_server`), shared by every tool. One round trip, client
speaks first: after the TCP connect and **before any Modbus frame**, the
client proves the shared key.

The proof (`auth_mac`):

```
HMAC-SHA256(key = key.encode('utf-8'),
            msg = b'pv-suite-modbus-auth\x01' + b'PVA1' + nonce)
```

No KDF, no salt, no clock — the key's UTF-8 bytes are used directly and
the fresh nonce is the only variable.

**The 52-byte client frame:**

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | magic `50 56 41 31` (`PVA1` — also the scheme version) |
| 4 | 16 | fresh nonce (`secrets.token_bytes(16)`) |
| 20 | 32 | the HMAC-SHA256 proof |

Sent in one `sendall` — no length prefix, no delimiter; the server reads
exactly 52 bytes. The server checks the magic and the MAC
(`hmac.compare_digest`) and answers **`OK`** (2 bytes; the session then
speaks plain Modbus) or **`ERR`** (3 bytes; the connection is dead —
the server logs `suite auth failed for <ip>:<port>, closing` and drops,
and a client that cannot prove the key never sees a frame).

Sequence:

1. TCP connect succeeds.
2. Client generates the nonce, computes the MAC, sends the 52 bytes.
3. Server reads exactly 52 bytes, checks magic + MAC.
4. Server replies `OK` or `ERR`.
5. Client on `OK` proceeds; on `ERR` raises `ModbusError('auth handshake
   rejected by the peer (key mismatch?)')`; on anything else
   `ModbusError('bad auth handshake reply')` (a plain server answers an
   MBAP exception frame instead of a verdict — the length check bites).
6. After `OK` the session is **plain Modbus TCP**: no encryption, no
   per-frame MAC, no session key. The handshake authenticates the
   connection; it is not Modbus security.

Failure handling: a failed proof fails the poll/connect like any other
device failure — the client closes and the next poll interval retries.
There is no retry count and no backoff at the Modbus layer.

**Direction per tool** (both cache legs use separate schemes and separate
keys, so a chain `scraper → cache → inverter` can authenticate each hop
independently):

| Tool | Knobs | Role |
|---|---|---|
| scraper | `modbus/auth` + `modbus/auth/key` | client toward the inverter |
| cache | `modbus/auth` + `modbus/auth/key` | server: its own clients must prove |
| cache | `modbus/auth-upstream` + `modbus/auth-upstream-key` | client toward the inverter |
| fake inverter | `modbus/auth` + `modbus/auth/key` | server: its clients must prove |

Security properties, stated plainly: the key is symmetric and the client
proves only — the server proves nothing to the client; the `OK`/`ERR`
verdict is cleartext and unauthenticated; the nonce is client-chosen and
not tracked server-side, so a captured 52-byte proof **can be replayed**
to any server holding the same key; traffic after `OK` is unauthenticated
and unencrypted. This is a connection gate for a trusted LAN, not a
transport security layer. Keys are secrets: min 16 characters (enforced at
start and on live `set`), never rendered back, loadable via `file:<path>`
from an owner-only `0600` file.

### The Waveshare connection password (`waveshare` — cache upstream only)

Implemented once in `common/modbus/protocol.py` (`waveshare_handshake_client`,
beside the suite pair). A Waveshare RS485-to-TCP gateway guards its serial
side with an optional connection password, and the cache's upstream leg
speaks it (`--auth-upstream waveshare`): after the TCP connect and before
any Modbus frame, the cache sends the shared auth-upstream-key as the
password itself — **raw ASCII bytes, no framing, no length prefix** — and
waits for the gateway's verdict:

1. TCP connect succeeds (the socket timeout is already armed).
2. Client `sendall(password.encode('ascii'))` — one write, no wrapper.
3. The gateway answers `OK` (the session then speaks plain Modbus TCP);
   anything else — a wrong password's rejection, a non-Waveshare peer's
   Modbus exception frame, silence (the socket timeout bites), an early
   EOF — raises `ModbusError('Waveshare TCP auth failed: …')` (a
   non-ASCII key never even reaches the wire: the config floors refuse
   it, and the handshake backs that up).
4. The reply is read in 2-byte chunks up to 16 bytes, stopping at the
   first `OK` — the verdict arrives inside a few bytes on a real gateway.

Failure handling is the suite discipline verbatim: the handshake runs on
every (re)connect, inside the exchange — a failed proof counts as an
exchange error (`errors`, `last_error`), the connector fails like any
other device failure, the socket drops and the next poll interval retries.
No retry count, no backoff at the Modbus layer. The scheme exists only on
the cache's upstream leg — the gateway firmware is the other side, and no
pv-suite tool ever demands a Waveshare password from its own clients.

---

## 3. Function codes

The one table is `FC_NAMES` (`common/modbus/protocol.py`); `describe_fc`
renders `FC6 (write single register)` or bare `FC<n>` for unlisted codes.

| FC | Name | Cache | Scraper | Fake |
|---|---|---|---|---|
| 1 | read coils | cached / forwarded | reads (`bit`, `fc: 1`) | serves the coil space |
| 2 | read discrete inputs | cached / forwarded | reads (`bit`, `fc: 2`) | serves the discrete-input space |
| 3 | read holding registers | cached / forwarded, diag block | reads | reads |
| 4 | read input registers | cached / forwarded (separate space) | reads | reads (the input space) |
| 5 | write single coil | gated + forwarded | — | writes (coil overlay; `0x0000`/`0xFF00` only) |
| 6 | write single register | gated + forwarded | — | writes (overlay) |
| 7 | read exception status | forwards | — | exception 01 |
| 8 | diagnostics | forwards | — | exception 01 |
| 11 | get comm event counter | forwards | — | exception 01 |
| 12 | get comm event log | forwards | — | exception 01 |
| 13 | program 484 | forwards | — | exception 01 |
| 14 | poll 484 | forwards | — | exception 01 |
| 15 | write multiple coils | gated + forwarded | — | writes (coil overlay) |
| 16 | write multiple registers | gated + forwarded | — | writes (overlay) |
| 17 | report slave id | forwards | — | exception 01 |
| 18 | program 884 | forwards | — | exception 01 |
| 19 | reset comm link 884 | forwards | — | exception 01 |
| 20 | read file record | forwards | — | exception 01 |
| 21 | write file record | forwards | — | exception 01 |
| 22 | mask write register | gated + forwarded | — | exception 01 |
| 23 | read/write multiple registers | gated + forwarded | — | exception 01 |
| 24 | read fifo queue | forwards | — | exception 01 |
| 43 | read device identification | forwards | — | exception 01 |

The cache's sets: `READ_FUNCS = (1, 2, 3, 4)` — the four address spaces,
each cached separately — and `WRITE_FUNCS = {5, 6, 15, 16, 22, 23}`
(`cache/lib/static.json`). Unknown codes forward untouched. The
scraper is **read-only** — it never issues writes (no write API — the
shared client exposes reads only); only the cache originates them (when
enabled), and the fake implements FC5/6/15/16 behind its write gate.

### The support classes — every standard FC, and what "support" means

Every standard function code is transported; none falls through
silently. Each code lands in exactly one class:

| Class | Codes | Meaning |
|---|---|---|
| **native reads** | 1, 2, 3, 4 | all three tools speak them natively — the fake serves all four address spaces, the cache caches all four, the scraper reads all four |
| **native writes** | 5, 6, 15, 16 | the fake implements them (write overlays, behind its gate); the cache gated-forwards them |
| **gated forward, native refusal** | 22, 23 | the cache gates and forwards them; the fake answers exception 01 (unimplemented there — nothing to gate) |
| **forward / named refusal** | 7, 8, 11–14, 17–21, 24, 43 | the cache forwards untouched (named in the log: `forwarded FC17 (report slave id), N byte(s)`); the fake names them (`describe_fc`) and refuses with exception 01 |
| **vendor / reserved** | 9, 10, 25–42, 44+ | the cache forwards bare (`FC<n>` — `FC_NAMES` has no standard name); the fake refuses with 01 |

Not implemented anywhere **by design**: the FC8 diagnostics
sub-functions, native FC43/MEI device identification, and the serial
RTU/ASCII transports — the family speaks Modbus TCP and forwards what it
does not itself serve. A tool "supports" a code when it terminates the
exchange itself; everything else rides the forward/refusal classes
above, so a client against the cache always gets an answer (a reply or
a named exception), never a dropped frame.

---

## 4. Reads (FC3 / FC4)

Request PDU — 5 bytes, `length = 6`:

```
B   H      H
FC  addr   count          # both big-endian
```

Response PDU:

```
B    B            N × 2 bytes
FC   byte_count   word0 word1 ...      # byte_count = count × 2
```

Client-side validation, in order (`scraper/lib/protocol.py` `_read`,
`cache/lib/upstream.py` `read`): header length bounds; `txn` matches the
outstanding one; `proto == 0`; `unit` matches the configured unit;
`func == fc + 0x80` → Modbus exception (the cache raises `DeviceError`
carrying `.code` so it can replay the device's code to its clients);
function byte matches; body ≥ 2 bytes; `byte_count == count × 2`; then
`count` big-endian words. The scraper's `read_i32` reads two registers
hi,lo and unpacks `>i`.

Worked example — read PV power (i32 at 32064 = `0x7D40`, 2 registers,
unit 1, txn 9):

```
request : 00 09 00 00 00 06 01 03 7d 40 00 02
reply   : 00 09 00 00 00 07 01 03 04 0f a0 00 00     (0x0FA0 = 4000 W)
exception (code 2): 00 09 00 00 00 03 01 83 02
```

Every read address carries the scraper's `modbus-offset` added on
(`scraper/lib/protocol.py` `_read`).

### The bit reads (FC1 / FC2)

Request PDU — identical shape to FC3/FC4 (5 bytes): `FC addr count`.
Response PDU — the bits **packed 8 per byte, LSB first**:

```
B    B            ceil(count / 8) bytes
FC   byte_count   packed bits          # byte_count = (count + 7) // 8
```

Bit `i` of the request span lives in byte `i >> 3`, bit position `i & 7`.
Read quantity: 1..2000 bits (the spec's `0x7D0`; `MAX_BITS` in each
tool's `lib/static.json`). The cache stores each bit as a 0/1 word in its
`(fc, addr)` map and repacks on reply; the scraper's `read_bits` returns
one 0/1 per address. The fake serves FC1 from its coil space (profile
`bit`/`fc: 1` entries + the FC5/FC15 writes + `set coil`), FC2 from the
discrete-input space (profile `bit`/`fc: 2` entries + `set discrete`).

---

## 5. Writes (FC5/6/15/16/22/23)

PDU shapes as validated by the shared parser (`common/modbus/writes.py` `describe_write`):

| FC | Request PDU | Response PDU |
|---|---|---|
| 5 write single coil | `05 addr(2) value(2)` — value `0x0000` or `0xFF00` | echo |
| 6 write single register | `06 addr(2) value(2)` | echo |
| 15 write multiple coils | `0F addr(2) count(2) bytecount(1) bits` (bytecount = `(count+7)//8`) | `0F addr(2) count(2)` |
| 16 write multiple registers | `10 addr(2) count(2) bytecount(1) words` (bytecount = `count×2`) | `10 addr(2) count(2)` |
| 22 mask write register | `16 addr(2) and(2) or(2)` | echo |
| 23 read/write multiple | `17 raddr(2) rcount(2) waddr(2) wcount(2) bytecount(1) words` — the **write** span is the second address pair | `17 bytecount(1) words` |

The fake inverter implements **FC5, FC6, FC15 and FC16** (into write
overlays on top of the simulated maps: FC6/16 the holding registers,
FC5/15 the coil space) — behind its write gate: `write/allow` off (the
default) refuses every write with exception 01 and audits
`WRITE-REFUSED`, `--allow-write` opens it (audited `WRITE`); the cache's
gate, mirrored. Every other write gets exception 01. A malformed write
shape (wrong length, inconsistent byte count) gets exception 03 —
FC5's coil value must be `0x0000` or `0xFF00` (the spec's rule; anything
else is exception 03), and FC15's byte count must equal
`(count + 7) // 8`.

The cache forwards writes only when **both** gates pass: `write/allow`
must be on *and* the client must pass the write ACL *and* the write span
must sit inside the register allow-list (`write/registers`) — both default
to closed; a bulk write (FC15/16) whose byte count disagrees with its
declared register count is refused at the cache itself (exception 03,
audited — the device never sees it). Every write outcome is audited:
`WRITE`, `WRITE-REFUSED`, `WRITE-REJECTED`, `WRITE-FAILED`. A successful
write-through invalidates the cached span: FC6/16/22/23 drop it in **both**
register spaces (holding and input — a device is free to mirror), FC5/15
drop the coil space (FC1).

---

## 6. Exceptions

The builder is `exception_frame` (`common/modbus/protocol.py`): a PDU of
`[func | 0x80, code]`, `length = 3`. Codes the suite generates
(`cache/lib/static.json`):

| Code | Name | When |
|---|---|---|
| 1 | ILLEGAL_FUNCTION | unsupported/unimplemented FC; writes disabled or denied |
| 2 | ILLEGAL_ADDRESS | address outside the legal/diag window; undefined register in the fake's strict mode |
| 3 | ILLEGAL_VALUE | malformed frame/count; nonzero protocol id |
| 11 (`0x0B`) | GATEWAY_FAILED | upstream unreachable, timed out or hostile |

**Cache server decision table** (`cache/lib/proxy.py`), in order: nonzero
`proto` or empty PDU → 03; write frame too short to carry an address →
03; writes disabled / client not on the write ACL / span outside the
allow-list → 01; FC15/16 byte count inconsistent with the register count
→ 03; FC1-FC4 PDU `< 5` bytes → 03; count outside `1..125` (registers) /
`1..2000` (bits) or `addr + count > 65536` → 03; FC3 inside the
diagnostics block → the synthesized reply (§7); FC3 touching ≥ 65000
outside the block or straddling it → 02; range with a remembered poll
failure → replay the device's exception code; range fully cached → cache
reply, no device contact; otherwise → forward, with an upstream failure
or hostile reply becoming 11. A bad MBAP `length` closes the connection
without a reply.

**Fake inverter decision table** (`inverter/lib/inverter.py`): bad
`length` → log and close; writes disabled (`write/allow` off — the
default) with a well-addressed write frame → 01, audited
`WRITE-REFUSED`; FC3/4 count outside `1..125` or address
overflow → 03; FC1/2 count outside `1..2000` → 03; strict mode with any
undefined register/bit → 02 (otherwise missing addresses read 0);
FC5 with a value outside `0x0000`/`0xFF00` → 03; FC5/6/15/16 with a
consistent shape → overlay write + echo (audited `WRITE`); an
implemented FC with a malformed shape — **including a frame too short
to carry its address** — → 03; any other FC → 01. The fake does **not**
validate the unit id — it serves any requested unit and echoes it back.
The cache's cached and diag replies echo the client's unit too; the
configured `modbus/unit` governs only its own poll reads.

Shared client error texts: `transaction id mismatch`,
`unexpected protocol id %d`, `reply from unit id %d, expected %d`,
`FC%d modbus exception, code %d`, `register count %d out of range`,
`connection closed by peer`, and the two handshake errors of §2.

---

## 7. The diagnostics block (registers 65000-65003)

Four synthesized words served by the cache on **FC3 only** — never
fetched, never cached, never forwarded (`cache/lib/proxy.py` `_diag`):

| Register | Word | Meaning |
|---|---|---|
| 65000 | 51966 (`0xCAFE`) | magic / cache presence |
| 65001 | 0 or 1 | last poll cycle had ≥ 1 successful upstream read |
| 65002 | seconds, clamped 65535 | age since the last successful upstream read (65535 = none yet) |
| 65003 | seconds, clamped 65535 | cache uptime |

A read straddling the block boundary, or starting beyond it, gets
exception 02. The scraper auto-detects the block by reading 65000..65003
and checking the magic; the fake always mocks `(0xCAFE, 1, 7, 4242)`.

---

## 8. Register types and device profiles

Values are **big-endian 16-bit registers**; the composite types are
`i16`/`u16` (1 register), `i32`/`u32` (2 registers, hi word first),
`i32swap`/`u32swap` (2 registers, **lo word first** — the swapped word
order some devices ship), `f32`/`f32swap` (an IEEE 754 single, 2
registers, hi/lo or lo/hi) and `bit` (1 address = one binary value on the
FC1/FC2 spaces). Scale semantics: wire = value × scale (a `bit` entry
serves `1` when the scaled value is nonzero; the decode divides by the
gain).

Device register maps live in `profiles/profiles/*.json`
(`sun2000.json`, `demo-fc4.json`, `deye-sg03lp1.json`,
`deye-sg04lp3.json`, `deye-sg05lp3.json`); the schema is
`profiles/README.md`. Per entry: `name`, `register`, `type`, optional
`fc` — word types `3` (default) or `4`, `bit` entries `1` (default) or
`2` — optional per-entry `ttl`, `scale`, `desc`. A
profile may carry a top-level `acl.write` tree — an allow/deny object
(sugar) or an ordered rule chain (`allow`/`deny`/`defer`, last matching
rule decides) — which the cache's write gate compiles to register ranges.

The cache merges adjacent ranges up to `merge-gap` addresses and 125
registers (2000 bits) per block, caches the four spaces in **separate
`(fc, addr)` maps**, and on a failed block bisects it in half within the
same cycle (single-leaf blocks are marked failed and their exception
replayed to clients).

---

## 9. Limits and defaults

| | cache | scraper | fake |
|---|---|---|---|
| `max_pdu` | 253 | 253 | 260 |
| `max_count` | 125 | 125 | 125 |
| register space | 65536 | 65535 | 65536 |
| unit id | 1..247 (validated at start) | 1..247 (validated at start) | 1 default, unvalidated |
| socket timeout | 3.0 s | 3.0 s | 3.0 s |
| client idle timeout | 300 s | — | 300 s |
| max clients | 64 | — | 64 |
| max conn per IP | 0 (off) | — | 0 (off) |
| listen backlog | 128 | — | 16 |
| poll interval | 10 s | 10 s | — |
| read delay between device reads | 0.05 s | — | — |
| cache TTL | 3 × poll interval | — | — |

Pacing and caps, not rate limiting: one serialized upstream connection;
`read-delay` sleeps between consecutive device reads in a healthy cycle
(after a failure the sweep runs unpaced); pass-through reads wait for a
free slot between poll reads; `max_clients` / per-IP caps gate the
listeners (`common/connlimit.py`); the connect ACL (`acl/connect`,
default any, `none` refuses all) filters before auth; audit `REQUESTS`
events are throttled to one per client per 300 s. The handshake read uses
the client idle timeout, so a silent plain client lingers until it drops.

---

## 10. Configuration surface

Precedence everywhere: **flag > env > config script > default**. The
config file speaks the set grammar; both the flat knob name and the live
path as words normalize to the canonical key.

| Knob | Flag | Env | Live path | Tools |
|---|---|---|---|---|
| `auth` | `--auth suite\|none` | `AUTH` | `modbus/auth` | all three |
| `auth-key` *(secret)* | `--auth-key` | `AUTH_KEY` | `modbus/auth/key` | all three |
| `auth-upstream` | `--auth-upstream suite\|waveshare\|none` | `AUTH_UPSTREAM` | `modbus/auth-upstream` | cache |
| `auth-upstream-key` *(secret)* | `--auth-upstream-key` | `AUTH_UPSTREAM_KEY` | `modbus/auth-upstream-key` | cache |
| `upstream` | `--upstream HOST:PORT` | `UPSTREAM` | `modbus/upstream` | cache, scraper |
| `unit` / `modbus-unit` | `--unit` / `--modbus-unit` | `UNIT` / `MODBUS_UNIT` | `modbus/unit` | cache, scraper, fake (flag only) |
| `timeout` | `--timeout` | `TIMEOUT` | `modbus/timeout` | cache, scraper |
| `offset` | `--modbus-offset` | `MODBUS_OFFSET` | `modbus/offset` | scraper |
| `allow-write` | `--allow-write` | `ALLOW_WRITE` | `write/allow` | cache, fake |
| `write-registers` | `--write-registers` | `WRITE_REGISTERS` | `write/registers` | cache |
| `connect-acl` | `--connect-acl` | `CONNECT_ACL` | `acl/connect` | cache, fake |
| `write-acl` | `--write-acl` | `WRITE_ACL` | `acl/write` | cache |

Validation: `parse_auth_type` accepts the leg's schemes — `suite`
everywhere, the cache's upstream leg also `waveshare` — or `none`/empty
for none; anything else exits with `use 'suite', or none/empty for no
auth` (the upstream leg names both: `use 'suite' / 'waveshare', …`)
(`common/config.py`). `check_auth_key` enforces the scheme's floor:
≥ 16 characters for `suite`, non-empty ASCII for `waveshare` (the
password travels as raw bytes), and a key set while no scheme is chosen
yet is dormant material — the floor bites when the scheme names it.
`parse_secret` takes an inline value or `file:<path>` (first line of an
owner-only `0600` file). Starting with a scheme and no key refuses at
start; the live `set` enforces the same (including going `suite` while a
short waveshare password stands as the key).

Secret behavior: the keys never render — `show modbus auth key` answers
`err modbus/auth/key is a secret — it never shows`; dumps render
`set <name> *** SECRET REMOVED ***`, and the parser and the wire `set`
refuse that placeholder back. Secrets cannot be `unset` — removing a key
takes a restart. Live rotation: setting a key closes the session so the
next exchange re-proves under the new material (the cache's inbound
scheme change does **not** drop standing sessions; they keep theirs).

Useful verbs (`modbus-*-ctl` / `modbus-*-cli`): `set modbus auth suite`,
`set modbus auth key <KEY|file:path>`, `set modbus auth-upstream …`,
`show modbus auth`, `show status` (reports `auth=` / `upstream_auth=` /
`modbus_auth=`), plus the ordinary `set modbus upstream/unit/timeout/
interval/...` rows. Startup logs name the schemes
(`client auth: suite, upstream auth: suite`).

---

## 11. Behaviors worth knowing

- **Unit ids are advisory server-side**: the cache and the fake both echo
  the client's unit without validating it; only the clients validate
  their own configured unit on replies.
- **The cache answers exceptions with the client's `proto` echoed** when
  it sent a nonzero one.
- **`Upstream.errors` counts transport failures only** — connect, send,
  recv, length, txn, proto inside `_exchange`. Unit/function/count and
  device exceptions raise outside the counter.
- **FC4 replies are cached too** on the way through, in their own space.
- **A 52-byte non-handshake client** against a server with auth disabled
  is read as an MBAP header, trips the length check, and the connection
  closes — the client sees `bad auth handshake reply`.
- **The handshake gate is conditional on a key existing**; startup
  validation prevents `suite` without a key, but the runtime gate itself
  checks both.
- **No Modbus TLS or encryption anywhere** — the `suite` handshake
  authenticates the connection, nothing more; the trust model is a
  trusted LAN.

---

## 12. Where the tests pin all this

`tests/cache-regtest.py` (framing helpers at the top; the suite-auth block
at the end — good key, wrong key, non-handshake `ERR`+EOF, both legs live,
key rotation, secret refusal), `tests/inverter-regtest.py` (server-side
handshake, silent client, bad magic, rotation), `tests/scrape-regtest.py`
(client-side handshake, wrong-key counters, live rotation recovery,
authed-vs-plain mismatch), `tests/cache-fuzz.py` (malformed MBAP lengths,
random PDUs, pipelined bursts, trickled frames), `tests/cache-stress.py`
(100 registers / 100 clients with pass-through and writes). The regtest
`PASS suite auth: ...` lines are the executable form of §2.

---

*Credits: the suite auth handshake is MK's design — see
[CONTRIBUTORS.md](CONTRIBUTORS.md). The per-tool behavior prose lives in
the [cache](../cache/README.md), [scraper](../scraper/README.md) and
[inverter](../inverter/README.md) READMEs; the knob table is
[OPTIONS.md](OPTIONS.md).*
