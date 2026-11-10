# ACLs — who may connect, whose writes forward, which registers a write may touch

This is the reference for the ACL support across the family: what the rule
chain says, where it is enforced, and which surfaces speak it. The story
has two planes. The **IP plane** decides who may reach a listener — the
Modbus listeners' `acl/connect`, the /metrics expositions' `metrics/acl`
(all four tools' /metrics listeners), and the cache's `acl/write` for
the write frames already inside. The **register plane** decides which
registers a forwarded write may touch — the `write-registers` knob and
the device profiles'
embedded `acl`/`write` gate. Both planes speak ONE gate-object schema with
TWO matcher kinds (registers, IP prefixes); one loader validates both, and
the standalone acl file is the same object whether a knob points at it
with `file:<path>` or a profile carries it embedded.

The control-plane auth is NOT an ACL: the tokens, the RBAC ops role and
the `trust-uids` list decide who may drive the control socket, and the
suite auth (`modbus/auth`) is a wire-level proof between Modbus peers.
Those stories live in docs/AUDIT.md and docs/MODBUS.md; the Related
section below maps the boundary.

## The surfaces (the family at a glance)

| tool | knob | kind | default | the inline grammar | enforced |
|---|---|---|---|---|---|
| modbus-cache | `acl/connect` | IP | `any` | `any\|none\|IP,...\|file:` | accept on the Modbus listen port |
| modbus-cache | `acl/write` | IP | `none` | `any\|none\|IP,...\|file:` | the write-frame forward |
| modbus-cache | `metrics/acl` | IP | `any` | `any\|none\|IP,...\|file:` | accept on the /metrics port |
| modbus-cache | `write-registers` | register | `none` | `START:COUNT,...\|any\|none\|profile\|file:` | the register gate on forwarded writes |
| modbus-fake-inverter | `connect-acl` | IP | `any` | `any\|none\|IP,...` (no `file:`) | accept on the Modbus listen port |
| modbus-fake-inverter | `metrics/acl` | IP | `any` | `any\|none\|IP,...\|file:` | accept on the /metrics port |
| modbus-scraper | `metrics/acl` | IP | `any` | `any\|none\|IP,...\|file:` | accept on the /metrics port |
| dashboard | `metrics/acl` | IP | `any` | `any\|none\|IP,...\|file:` | accept on the /metrics port |
| dashboard | — | — | — | — | the page carries no ACL by decision — the bearer token + the loopback default stand in (F21 closed, rev. 21) |

## The listeners (the serving surfaces)

Eleven listeners across the four tools: six carry an IP-kind ACL, every
serving surface carries the connection caps, the control sockets are
loopback + token by decision, and every HTTP surface speaks the F13
token shape beyond the loopback (the page's F21 closed it — rev. 21).

| tool | listener | the default bind | the stack at it |
|---|---|---|---|
| cache | the Modbus mirror | `127.0.0.1:15502` | `acl/connect` (accept, ahead of the caps) → the caps → the suite auth; the write path then adds `--allow-write` + `acl/write` + `write-registers` |
| all four | control | unix \| TCP `127.0.0.1` | ONE listener for the family (`common/wire/control.py`'s tier, lifted from the cache): the TCP bind refuses without the admin token (F5 — the fake exempt, F11's test-tool posture); the ops RBAC, the signed wire, peer-cred on unix; the socket `0600`/`0660`; the target rebinds live (`set control port` — bind-first, the sessions keep serving), the tokens, the ops policy, the trust uids and the socket-group all set live |
| all four | /metrics | the scraper always on at `127.0.0.1:9350`; the cache, fake and dashboard off at `9351`/`9352`/`9353` | ONE stack for the family: the token mandatory beyond loopback (F13's refusal) → `metrics/acl` (the inline grammar or `file:<path>`, checked at accept — a client off the ACL is closed without a reply) → the caps |
| fake | the Modbus listener | `:5502` | `connect-acl` (the system grammar, no `file:`) → the caps → the suite auth; `--allow-write` |
| dashboard | the page + the config proxy | `127.0.0.1:8080` | the bearer token (`auth/token`, F21 closed — the `?auth=` bootstrap sets the session cookie, the header for scripts; a token-less non-loopback bind refuses to start) — GET-only, the realpath guard, the cap gate |

The defaults come from each tool's `statics.py`; the authoritative
per-surface detail is docs/AUDIT.md's surfaces table.

## The rule chain (the one semantics)

The gate object: an optional terse-ASCII `desc`, the optional gate-level
`type`, and the ordered `rules` list — one
`{"type": "allow"|"deny", matcher: ..., "desc": ...}` object per rule
(`desc` rides per gate and per rule; a rule's desc speaks for every entry
in its matcher). THE MATCHER KEY IS THE GRAMMAR:

| kind | gate `type` | the matcher (`range` / `prefix`) |
|---|---|---|
| the register kind | `write-registers` | `any` \| a `START:COUNT` range \| a comma-separated list of them |
| the IP kind | `ip-prefix` | `any` \| an IP \| an IP/prefix length \| a comma-separated list of those |

The chain is a whitelist, said out loud: it reads top to bottom, **the last
matching rule decides**, and a register or client no rule decides refuses
(the default deny any). `any` is the whole space — every register for the
register kind, every address of either family for the IP kind (the table
shows spell it `0.0.0.0/0`).

The gate `type` names the schema, not the daemon surface, and must agree
with the rules' key when spelled: a typeless register gate reads as
`write-registers` (the legacy shape — every existing profile and file keeps
working), a typeless prefix gate refuses (say the type), and a gate whose
rules mix `range` and `prefix` refuses (one grammar per gate). One loader
validates the object — `_write_gate_object` in `common/settings/config.py`, one
gate validator for the family — and each consumer pins the kind it takes
(`allow=('write-registers',)` or `allow=('ip-prefix',)`): a file of the
wrong kind is a clean, named refusal, not a mis-compiled gate.

The listener gates are **accept-time checks that run ahead of the
connection caps** (the ACL first, then the caps): an off-ACL peer is
closed without a reply — nothing was parsed to answer — and never counts
against a cap; a cap refusal is only ever answered to a peer the ACL
admitted. The forward gates (`acl/write`, `write-registers`) are
per-frame checks on the already-accepted connection and do not touch the
caps at all.

The IP matchers speak both address families — the strict-CIDR validation
takes v4 and v6 spellings, `any` matches both. The shipped listeners are
IPv4 today (every listening socket is `AF_INET`); the v6 listening
surface and its v4-mapped-peer normalization are sketched in
docs/TODO.md's security section.

## The standalone acl file

`file:<path>` on a consuming knob points at a file whose root object IS
the gate (the same object a profile carries under `acl`/`write`). The
file is read at start and on every `set`/`clear`:

- a missing or bad file **refuses the start** and answers `err` on the
  wire **with the old gate standing** — a broken edit never widens a
  running daemon;
- the `file:<path>` spelling is the re-appliable form — it round-trips
  through `clear`, the state dumps and `show config`;
- a **group/world-readable acl file warns** (the gate is config trust any
  local user could have loosened): in the log, the audit trail's
  `ACL-FILE` event, and as the suffix of the `set`/`clear` reply. A `0600`
  file is silent.

Two tools keep the files honest — `scripts/lint_acl.py` (the loader's
schema plus what the loader cannot say: a no-op rule, a dead rule —
everything it decides a later rule re-decides — and the canonical layout)
and `scripts/edit_acl.py` (the dialog and the line mode, `--type` seeds a
fresh gate and migrates a typeless one). Both speak both kinds; the
embedded profile gates belong to `profiles/bin/profile-lint.py`. The
shipped examples — one shared copy each at the repo root:
`examples/acl-write-registers.json` (the deye register policy: the
clean-slate deny, the allows, the deny carves, the re-opens) and
`examples/acl-ip-prefix.json` (every tool's ip-prefix gate). The
**JSON Schemas** ship beside them (`shared/schema/acl-ip-prefix.schema.json`
+ `shared/schema/acl-write-registers.schema.json` at the root,
`cache/schema/` for selection, `scraper/schema/` for metrics —
draft 2020-12) — schema-valid can still be
loader-refused (the strict-CIDR host-bit spellings, the range bounds), so
the loader stays the strict word; wire them into an editor by `$schema`
pattern-matching for live feedback while editing.

## modbus-cache — both planes, both spellings

The cache consumes both planes, both matcher kinds, both spellings
(embedded and file) — four gates on one forwarded write:

1. the frame parses;
2. `--allow-write` is on;
3. the client is on the `acl/write` IP gate (refused 86/1, the
   `WRITE-REFUSED` audit event, the connection stays up);
4. every touched register is inside the `write-registers` allow-list.

`acl/write` and `write-registers` default to `none` — enabling
`--allow-write` alone still refuses every write until both are opened
deliberately. The three IP knobs (`acl/connect`, `acl/write`,
`metrics/acl`) speak one value grammar: `any`, `none`, a comma-separated
`IP,IP/prefix, ...` list, or `file:<path>` (the ip-prefix acl file — a
typeless or wrong-kind file refuses). The inline forms are the compact
spellings of three fixed chains, and the table shows render exactly that,
one entry per line:

| value | the chain it spells | the evaluation |
|---|---|---|
| `any` | `allow 0.0.0.0/0` | every peer allowed |
| `none` | `deny 0.0.0.0/0` | every peer refused |
| `IP,...` | `deny 0.0.0.0/0`, then one `allow` line per network | the whitelist: a peer landing in one network allowed, everyone else refused |

The deny carves (the re-opens, the guest-VLAN exclusions — a deny rule
re-deciding what an earlier allow opened) ride the **files**; the inline
grammar stays the three fixed chains. `show acl connect table` and
`show acl write table` render either form as its chain — a file gate
renders its own rules behind the `% ` desc header, the comments aligned —
and `show write registers profile` does the same for the register gate.
`show metrics acl table` is the third report, same renderer. A `set acl
connect table` (the show word typed into the set verb) answers the
pointer to the report.

The IP ACLs re-resolve on SIGHUP like every setting; the file gates
resolve **before** the state swaps, so a bad file keeps the previous
settings wholesale.

The forms: `--connect-acl` / `--write-acl` / `--write-registers` /
`--metrics-acl` (env `CONNECT_ACL` / `WRITE_ACL` / `WRITE_REGISTERS` /
`METRICS_ACL`, the config-file spellings `connect_acl` / `write_acl` /
`write_registers` / `metrics_acl`, NixOS `connectAcl` / `writeAcl` /
`writeRegisters` / `metricsAcl` — one str option each, `file:` rides
inline), live via `set acl connect|acl/write|metrics acl|write registers
<value>`.

## modbus-fake-inverter — the mirror, system grammar only

The fake's Modbus listener speaks the **connect ACL only**, mirrored from
the cache: `--connect-acl` (env `CONNECT_ACL`, live `set connect-acl
<value>`) takes `any` (the default — the trusted-LAN posture), `none`, or
the comma-separated IP/CIDR list, evaluated with the same whitelist
semantics (the ip must land in one network). The refusals log `connection
rejected: … not on the connect ACL`, and the fake's ctl/cli carry the
knob like the cache's. The fake takes NO `file:` gates and no chains — a
test instrument on a trusted LAN keeps its soft-edge posture (F11 in
docs/AUDIT.md); its write gate is `--allow-write` alone (off = every
Modbus write refused), with no IP write-acl and no register allow-list.
Its /metrics listener is the family's other gate — `metrics/acl`, the
full grammar with `file:` included (the /metrics row above).

## modbus-scraper — the metrics listener, IP kind

The scraper serves one listener beyond the control socket — the /metrics
exposition — and one IP-kind gate covers it: `metrics/acl` on the HTTP
listener, the same gate the cache's `acl/connect` runs on its Modbus
listener (the cache's, fake's and dashboard's own /metrics endpoints
speak it too). The check is
the shared accept ladder: ahead of the connection caps, an off-ACL
client is closed without a reply (`connection rejected: … not on the
metrics ACL`).

The Modbus leg is outgoing and needs no gate. The scraper is a client:
it dials the inverter or the cache's mirror (`--upstream`, live
`modbus/upstream`), and an acl gates listeners, not clients — on that
leg the scraper is the peer the server's connect gate decides about (the
cache's `acl/connect`, the fake's mirror of it), and what it presents is
the suite-auth key (`modbus/auth` + `modbus/auth/key`, the PVA1
handshake — docs/MODBUS.md). The poll's reads need no register gate:
the register plane is write-only, and the poller sends no write (it
speaks `read_registers`/`read_bits`), so there is nothing read-side for
an acl to decide.

`--metrics-acl` (env `METRICS_ACL`, live `set metrics acl <value>` /
`clear metrics acl`, config `metrics_acl`, NixOS `metricsAcl` +
`metricsAclFile` — the split options, the file rides a LoadCredential
mount) takes the same one value grammar as the cache's IP knobs. The acl
file re-resolves on every `set`/`clear` and on SIGHUP, a bad file keeps
the old gate standing, and a group/world-readable file warns (the log,
the audit trail's `ACL-FILE` event, the `set` reply's suffix). The chain
renders as `show metrics acl table` — the three fixed chains for the
inline forms, the file gate's own rules behind the `% ` desc header — and
a `set metrics acl table` (the show word typed into the set verb) answers
the pointer to the report.

The gate never replaces the bearer: `--auth-token`'s request-time check
and F13's non-loopback refusal stand on top of it — the ACL decides who
may connect, the token decides whether the scrape authenticates (an
ACL'd but tokenless non-loopback listen still refuses to start;
docs/AUDIT.md).

The control socket is NOT this gate — see below.

## the control plane — loopback binds, no IP gate

Every control TCP bind is hardcoded `127.0.0.1`
(`common/wire/control.py`'s `_open_sock` — the one listener tier all four
tools ride, live-rebindable via `set control/port`, the target parsers
unified in `common/settings/config.py`; the unix sockets are peer-cred), so
no control surface carries an IP gate — an IP filter on loopback decides
on the one address that always matches. The plane's admission story is
the tokens + the signed wire + the RBAC roles (docs/AUDIT.md, F5). An
explicit `acl/control` gate is sketched in docs/TODO.md's security
section and earns its place the moment the control target learns to bind
beyond loopback — until then the fake's tokenless-loopback TCP exemption
(F11) rides on the same bind.

## Related — the neighbouring gates that are not ACLs

- **the suite auth** (`modbus/auth`, `modbus/auth-upstream`) — the
  PVA1/HMAC-SHA256 handshake on the Modbus wire itself: a proof of key
  between peers, orthogonal to the address gates (both stack).
  docs/MODBUS.md.
- **the control-plane auth** — the admin token, the read-only ops token
  and its verb set (the RBAC roles), the `trust-uids` peer-cred path, the
  signed wire. docs/AUDIT.md.
- **the bearer token** — the request-time auth on the HTTP surfaces: the
  cache's /metrics, the scraper's, the dashboard's own /metrics and the
  fake's (all mandatory beyond loopback — F13's refusal; the loopback
  bind serves tokenless), and the dashboard's page + proxy (the same
  shape, F21 closed rev. 21 — the `?auth=` bootstrap sets the session
  cookie, the raw header stays for scripts). The accept-time
   ACL decides who may connect, the bearer decides whether the request
   authenticates — both stack, neither replaces the other
   (docs/AUDIT.md).
- **the connection caps** — `max-clients`, `client-timeout`,
  `max-conn-per-ip` (and the metrics triple): the DoS posture, applied
  beside the connect ACL, never instead of it — and always answered
  after it.
