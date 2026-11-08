# ACLs — who may connect, whose writes forward, which registers a write may touch

This is the reference for the ACL support across the family: what the rule
chain says, where it is enforced, and which surfaces speak it. The story
has two planes. The **IP plane** decides who may reach a Modbus listener at
all and whose write frames forward — the `acl/connect` and `acl/write`
knobs. The **register plane** decides which registers a forwarded write may
touch — the `write-registers` knob and the device profiles' embedded
`acl`/`write` gate. Both planes speak ONE gate-object schema with TWO
matcher kinds (registers, IP prefixes), one loader validates both, and the
standalone acl file is the same object whether a knob points at it with
`file:<path>` or a profile carries it embedded.

The control-plane auth is NOT an ACL: the tokens, the RBAC ops role and the
`trust-uids` list decide who may drive the control socket, and the suite
auth (`modbus/auth`) is a wire-level proof between Modbus peers. Those
stories live in docs/AUDIT.md and docs/MODBUS.md; the Related section
below maps the boundary.

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
register kind, every address for the IP kind (both address families; the
table shows spell it `0.0.0.0/0`).

The gate `type` names the schema, not the daemon surface, and must agree
with the rules' key when spelled: a typeless register gate reads as
`write-registers` (the legacy shape — every existing profile and file keeps
working), a typeless prefix gate refuses (say the type), and a gate whose
rules mix `range` and `prefix` refuses (one grammar per gate). One loader
validates the object — `cache/lib/config.py`'s `_write_gate_object` — and
each consumer pins the kind it takes (`allow=('write-registers',)` or
`allow=('ip-prefix',)`): a file of the wrong kind is a clean, named refusal,
not a mis-compiled gate.

## The standalone acl file

`file:<path>` on a consuming knob points at a file whose root object IS the
gate (the same object a profile carries under `acl`/`write`). The file is
read at start and on every `set`/`unset`:

- a missing or bad file **refuses the start** and answers `err` on the wire
  **with the old gate standing** — a broken edit never widens a running
  daemon;
- the `file:<path>` spelling is the re-appliable form — it round-trips
  through `unset`, the state dumps and `show config`;
- a **group/world-readable acl file warns** (the gate is config trust any
  local user could have loosened): in the log, the audit trail's
  `ACL-FILE` event, and as the suffix of the `set`/`unset` reply. A `0600`
  file is silent.

Two tools keep the files honest — `scripts/lint_acl.py` (the loader's
schema plus what the loader cannot say: a no-op rule, a dead rule —
everything it decides a later rule re-decides — and the canonical layout)
and `scripts/edit_acl.py` (the dialog and the line mode, `--type` seeds a
fresh gate and migrates a typeless one). Both speak both kinds; the
embedded profile gates belong to `profiles/bin/profile-lint.py`. The
shipped examples: `cache/examples/acl-write-registers.json` (the deye
register policy: the clean-slate deny, the allows, the deny carves, the
re-opens) and `cache/examples/acl-ip-prefix.json` (the same shape for
IPs). The ip-prefix file's **JSON Schema** ships beside it
(`cache/examples/acl-ip-prefix.schema.json`, draft 2020-12) — the
schema-valid-files-are-maybe-loader-refused direction is the honest one:
the loader stays the strict word (it additionally refuses the host-bit
prefix spellings and the malformed v6); wire it into an editor by
`"$schema"` pattern-matching for live feedback while editing.

## modbus-cache — the full story

The cache consumes both planes, both matcher kinds, both spellings
(embedded and file):

| knob | the gate | the check |
|---|---|---|
| `acl/connect` | the IP kind | who may open the Modbus connection at all — the accept check on the listen port (`connection rejected: … not on the connect ACL`) |
| `acl/write` | the IP kind | whose write frames forward — the client half of the write path (refused 86/1, `WRITE-REFUSED` audited, the connection stays up) |
| `write-registers` | the register kind | which registers a forwarded write may touch — the register half (the profile's `acl`/`write` gate, or the standalone file, or an inline `START:COUNT` list) |

The two IP knobs speak one value grammar: `any`, `none`, a comma-separated
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
A `set acl connect table` (the show word typed into the set verb) answers
the pointer to the report.

A forwarded write passes **four gates**: the frame parses, `--allow-write`
is on, the client is on the write ACL, and every touched register is inside
the write-registers allow-list. `acl/write` and `write-registers` default
to `none` — enabling `--allow-write` alone still refuses every write until
both are opened deliberately. The IP ACLs re-resolve on SIGHUP like every
setting; the file gates resolve **before** the state swaps, so a bad file
keeps the previous settings wholesale.

The forms: `--connect-acl` / `--write-acl` / `--write-registers` (env
`CONNECT_ACL` / `WRITE_ACL` / `WRITE_REGISTERS`, the config-file spellings
`connect_acl` / `write_acl` / `write_registers`, NixOS
`connectAcl` / `writeAcl` / `writeRegisters`), live via
`set acl connect|acl/write|write registers <value>`.

## modbus-fake-inverter — the mirror, system grammar only

The fake's Modbus listener speaks the **connect ACL only**, mirrored from
the cache: `--connect-acl` (env `CONNECT_ACL`, live
`set connect-acl <value>`) takes `any` (the default — the trusted-LAN
posture), `none`, or the comma-separated IP/CIDR list, evaluated with the
same whitelist semantics (the ip must land in one network). The refusals
log `connection rejected: … not on the connect ACL`, and the fake's ctl/cli
carry the knob like the cache's. The fake takes NO `file:` gates and no
chains — a test instrument on a trusted LAN keeps its soft-edge posture
(F11 in docs/AUDIT.md); its write gate is `--allow-write` alone (off = every
Modbus write refused), with no IP write-acl and no register allow-list.

## modbus-scraper and the dashboard — no ACL surface

The scraper is a client, not a listener: it owns the one connection
upstream and exposes no Modbus surface to gate. Its exposure is the metrics
endpoint and the control socket — the token, the caps and the bind are that
story (docs/AUDIT.md, F5/F6). The dashboard consumes the scraper's metrics
and carries no ACL surface either. If a deployment needs the metrics
endpoint IP-gated, terminate at a reverse proxy (F14's answer) — the family
deliberately does not grow a per-request IP ACL on the HTTP surfaces.

## Related — the neighbouring gates that are not ACLs

- **the suite auth** (`modbus/auth`, `modbus/auth-upstream`) — the
  PVA1/HMAC-SHA256 handshake on the Modbus wire itself: a proof of key
  between peers, orthogonal to the address gates (both stack). docs/MODBUS.md.
- **the control-plane auth** — the admin token, the read-only ops token and
  its verb set (the RBAC roles), the `trust-uids` peer-cred path, the
  signed wire. docs/AUDIT.md.
- **the connection caps** — `max-clients`, `client-timeout`,
  `max-conn-per-ip` (and the metrics triple): the DoS posture, applied
  beside the connect ACL, never instead of it.
