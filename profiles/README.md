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
  register bounds (0…65536 − width), the type width, `fc` ∈ {3, 4}, a
  numeric `ttl ≥ 0`, terse-ASCII `desc`s, the mappings vs a register word,
  duplicate names and same-fc register overlaps. Runs on
  `profiles/profiles/*.json` by default, or the files named on the command
  line; exits non-zero on the first issue found.
- **`profile-format.py`** — rewrites any profile in place into the
  canonical layout (the `sun2000.json` shape): description first, then the
  mappings, then the registers — one entry per line, keys in the family
  order. Content-preserving and idempotent.

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
  - `type` — `i16` / `u16` / `i32` / `u32` (a 32-bit type spans two registers)
  - `fc` — optional, the Modbus function code the entry is read with:
    `3` (holding registers, the default) or `4` (input registers). The
    fake serves the same map on both codes; the cache polls and caches the
    two spaces independently.
  - `ttl` — optional, the cache TTL override for the entry in seconds
    (`0` = never expire); absent = the cache's global TTL. A fast power
    word at 5s next to a nameplate word at 1h — one poll cadence for both.
  - `scale` — the wire gain: wire = value × scale (e.g. the sun2000
    temperatures ×10, the currents ×100)
  - `desc` — what the register holds

## Semantics

- **A name left out does not exist on this device**: reads as 0 (exception 02
  in strict mode). A device without, say, per-string data simply omits
  `string-1-voltage`.
- Every fact lives in the JSON — no hardcoded tables anywhere in the suite.
- A profile is addressed by bare name (this directory) or by path.

## Shipped profiles

| Profile | Device | Entries |
|---|---|---|
| `sun2000` | Huawei SUN2000 with meter and optional battery | 49 |
| `deye-sg03lp1` | Deye SUN single-phase hybrid (SG01/03LP1) | 14 |
| `deye-sg04lp3` | Deye SUN three-phase hybrid (SG04LP3) | 19 |
| `deye-sg05lp3` | Deye SUN three-phase hybrid (SUN-12K-SG05LP3-EU, full map) | 82 |

All shipped entries read on FC3 (holding registers) — the `fc: 4` input
space is supported by the schema, the linter and the cache, but no shipped
profile exercises it yet.

## License

The profiles and tools are licensed under the **BSD 3-Clause License** —
see the repo-root `LICENSE` file.
