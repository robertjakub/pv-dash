# Inverter profiles

One device-profile home for the whole suite: the fake inverter serves from
it, the cache fetches its selection from it, the scraper binds its metrics
to it. Every consumer resolves a bare name (`sun2000`, `deye-sg04lp3`)
against the JSON files in this subproject's `profiles/` data dir
(`profiles/profiles/` from the repository root) first, then its own packaged
copy.

The subproject: `profiles/` — the device-profile JSON files; `bin/` — the
linter (`profile-lint.py`: the schema and style checks) and the formatter
(`profile-format.py`: rewrites any profile into the sun2000.json shape).

## Tools

Two standalone tools keep the profiles in shape (stdlib only, no
dependencies — `python3 profiles/bin/<tool>.py` from the repo root):

- **`profile-lint.py`** — the schema and style checks: valid JSON, the
  top-level shape, a non-empty `description`, the required keys and their
  family order (`name` → `register` → `type` → `scale` → `desc`), the
  register bounds (0…65536 − width), the type width, `fc` ∈ {3, 4} for the
  word types and {1, 2} for `bit`, a numeric `ttl ≥ 0`, terse-ASCII `desc`s,
  the mappings vs a register word, the write acl tree, duplicate names and
  same-fc register overlaps. Runs on
  `profiles/profiles/*.json` by default, or the files named on the command
  line; exits non-zero on the first issue found.
- **`profile-format.py`** — rewrites any profile in place into the
  canonical layout (the `sun2000.json` shape): description first, then the
  acl tree, then the mappings, then the registers — one entry per line,
  keys in the family order. Content-preserving and idempotent.

```bash
python3 profiles/bin/profile-lint.py                    # lint all shipped profiles
python3 profiles/bin/profile-lint.py my-device.json     # lint one file
python3 profiles/bin/profile-format.py profiles/profiles/deye-sg03lp1.json
```

## Format

One JSON object per device:

```json
{
  "description": "Huawei SUN2000 with meter and optional battery",
  "acl": {
    "write": {
      "rules": [
        {"type": "allow", "range": "32089:1", "desc": "the inverter on/off switch"}
      ]
    }
  },
  "mappings": [
    {"register": "device-status", "values": {"512": "on-grid", "40960": "standby"}}
  ],
  "registers": [
    {"name": "pv-power", "register": 32064, "type": "i32", "scale": 1,
     "desc": "PV power, all strings (W)"}
  ]
}
```

- **`description`** — one line, what device this profile emulates.
- **`acl`** — the optional access-control tree, keyed by access kind.
  **`write`** is the one the cache speaks: the gate is one object — an
  optional terse-ASCII `desc` and the ordered **`rules`** list, one
  `{"type": "allow"|"deny", "range": matcher}` object per rule, each with
  an optional `desc`. A matcher is a `START:COUNT` range or a list of
  them, or the bare word `any` (all registers). The chain is a
  **whitelist**: it reads top to bottom and **the last matching rule
  decides**; a register no rule decides refuses (the default deny any).
  The cache's `write-registers profile` value compiles the chain into the
  register ranges a forwarded write may touch, and its
  `show write registers profile` answers the chain back, one
  `allow`/`deny` line per range (see the cache README); a profile without
  the `acl` section simply offers no profile gate.
- **`mappings`** — optional list for coded registers: one
  `{"register": <name>, "values": {code: word}}` object per coded register.
  The values are the **real device's** codes (the sun2000:
  512 = on-grid / 40960 = standby; the Deye: 1 = self-checking / 2 = normal /
  3 = fault). The fake inverter serves the mapped codes; the tools can
  resolve a code back to its word.
- **`registers`** — the register map: one entry per register, **one register
  per line**, keys in the order `name` → `register` → `type` → `scale` →
  `desc`, terse ASCII descriptions:
  - `name` — the suite-wide register name (the shared vocabulary across the
    fake, the cache and the scraper; e.g. `pv-power`, `battery-soc`)
  - `register` — the start address (decimal)
  - `type` — `i16` / `u16` (one word), `i32` / `u32` (two words, hi/lo),
    `i32swap` / `u32swap` (two words, lo/hi — the swapped word order some
    devices ship), `f32` / `f32swap` (an IEEE 754 float, two words, hi/lo
    or lo/hi), or `bit` (one address = one binary value on the coil or
    discrete-input space)
  - `fc` — optional, the Modbus function code the entry is read with; the
    type picks the legal pair and the default: the word types read on `3`
    (holding registers, the default) or `4` (input registers), a `bit`
    entry reads on `1` (coils, the default) or `2` (discrete inputs). The
    fake serves the four spaces separately (an `fc: 4` entry is not served
    on FC3); the cache polls and caches the four spaces independently, and
    the scraper reads a source-bound entry with the entry's code.
  - `ttl` — optional, the cache TTL override for the entry in seconds
    (`0` = never expire); absent = the cache's global TTL. A fast power
    word at 5s next to a nameplate word at 1h — one poll cadence for both.
  - `scale` — the wire gain: wire = value × scale (e.g. the sun2000
    temperatures ×10, the currents ×100); a `bit` entry serves `1` when
    the scaled value is nonzero
  - `desc` — what the register holds

## Semantics

- **A name left out does not exist on this device**: reads as 0 (exception 02
  in strict mode). A device without, say, per-string data simply omits
  `string-1-voltage`.
- **The write acl chain reads top to bottom, the last matching rule
  decides**; an undecided register refuses (the default deny any — the
  chain is a whitelist). Worked examples:
  - `[{"type": "allow", "range": "47400:100"}, {"type": "deny", "range": "47442:1"}]` —
    47400–47499 writable, 47442 refuses: the deny carves the one register
    out of the allowed range.
  - `[{"type": "allow", "range": "any"}, {"type": "deny", "range": "148:30"}, {"type": "allow", "range": "148:1"}]` —
    everything writable except 149–177: the opening `any` grants the
    whole space, the deny carves the span out, the last rule re-opens
    148.
  - `[{"type": "deny", "range": "any"}, {"type": "allow", "range": "148:30"}]` —
    only 148–177 writable: the opening deny-any clears the slate,
    everything else matches no deciding rule and refuses.
- Every fact lives in the JSON — no hardcoded tables anywhere in the suite.
- A profile is addressed by bare name (this directory) or by path.

## Shipped profiles

| Profile | Device | Entries |
|---|---|---|
| `sun2000` | Huawei SUN2000 with meter and optional battery | 49 |
| `sun2000_full` | Huawei SUN2000 full map: inverter + LUNA2000 + meter | 645 |
| `deye-sg03lp1` | Deye SUN single-phase hybrid (SG01/03LP1) | 14 |
| `deye-sg04lp3` | Deye SUN three-phase hybrid (SG04LP3) | 19 |
| `deye-sg05lp3` | Deye SUN three-phase hybrid (SUN-12K-SG05LP3-EU) | 88 |

All shipped entries read on FC3 (holding registers) — the `fc: 4` input
space is supported end to end (the schema, the linter, the cache and the
scraper; the regtest exercises it), but no shipped profile carries real
input-register data yet — that waits for a hardware capture.

## The sun2000 drift (the small profile vs the full map)

`sun2000` (49 rows) predates the newest Huawei documentation;
`sun2000_full` is built from it — the SUN2000MA Modbus Interface
Definitions (V3.0) Issue 06 (2025) for the inverter and battery blocks,
the Solar Inverter (L1) definitions Issue 04 for the meter block and the
optimizer rows, cross-checked against the wlcrs/huawei-solar-lib register
map. Every `sun2000` address survives in the full map (22 of the 49 rows
byte-identical), but 27 rows drift:

**Reinterpreted** — the shipped row names the wrong signal:

| Registers | shipped `sun2000` | `sun2000_full` | what the docs say |
|---|---|---|---|
| 32066-32068 | `output-power-a/b/c` (W, x1) | `grid-voltage-ab/bc/ca` (V, x10) | grid line voltages; the phase powers live at 32133-32137 |
| 32078 | `pv-dc-total` | `peak-power-today` | today's peak active power (W) |
| 32080 | `pv-limit` | `active-power` | the measured AC active power; the limits live at 42023/42405 |
| 32086 | `device-insulation` (x1) | `inverter-efficiency` (% x100) | efficiency — the insulation resistance is 32088 (kohm), which the shipped profile lacked |
| 37003 | `battery-efficiency` (x1) | `battery-bus-voltage` (V x10) | battery bus voltage |
| 37760 | `battery-soc-reserve` | `battery-soc-system` | the system SOC; the reserve knob is 47102 `battery-backup-soc` |

**Renamed only** — the same wire, the docs' words: 32069-32071
`output-voltage-a/b/c` → `grid-voltage-a/b/c`, 32072/32074/32076
`output-current-a/b/c` → `grid-current-a/b/c`.

**Retyped** — the docs say signed where the shipped profile reads
unsigned: 32016-32019 (the PV words), 32084 and 37117 (the power
factors), 37118 (the frequency), 37119 and 37121 (the meter energy
registers). The wire bytes are unchanged; only the decode of the high
bit moves.

**Re-coded** — `meter-mode` (37125) maps `{0: single-phase,
1: three-phase}` per both docs; the shipped `{1: CT, 2: direct
connection}` matches no doc issue.

**Reworded** — four descs: the temperature register's doc name (internal
temperature), the battery-power sign convention (+ = charging), the
meter type, and 37786's missing `x100` marker.

The rest of the full map — the nameplate words, the inspection block,
the alarm words, the battery packs, the parallel-system rows and the
42000-48219 config knobs — is coverage the small profile never
attempted.

## License

The profiles and tools are licensed under the **BSD 3-Clause License** —
see the repo-root `LICENSE` file.
