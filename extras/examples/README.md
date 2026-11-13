# Shared examples

The suite-wide sample files — one copy each, under `extras/`. A file
lives here when two or more tools ship it, or when the family's acl
tools and schemas treat it as a shared shape: the standalone acl files
are ONE format (the gate validator in `common/settings/config.py` reads
every kind), so both shipped gates live here — the write kind's only
consumer today is the cache. The cache's selection file lives here too —
one consumer, but its schema's home is the shared
[shared/schema/](../../shared/schema/README.md) dir. The tool-local
samples stay in each tool's
own `examples/` dir
(`cache/examples/`, `scraper/examples/`, `dashboard/examples/`). No
tool loads from this directory — the loaders resolve operator paths
(the flags, the env twins, the `file:` values); these files are the
samples, and every `package.nix` installs its packaged copy into
`share/<tool>/`.

## Files

- **`acl-ip-prefix.json`** — the standalone acl file: the ip-prefix
  connect gate. The chain reads top to bottom, the LAST matching rule
  decides, and a client no rule decides refuses (the default deny any);
  the matcher word `any` is the whole space (0.0.0.0/0 — both address
  families). Every tool's ip-prefix `file:` acl knob reads this shape —
  the cache's `acl/connect` + `acl/write`, the scraper's and the fake
  inverter's `metrics/acl`, the dashboard's `metrics-acl`
   ([docs/common/ACL.md](../../docs/specs/ACL.md) is the family-wide story).
- **`acl-write-registers.json`** — the standalone acl file:
  the write-registers gate (the deye policy, worked out — the
  clean-slate deny, the allows, the deny carves, the re-opens). The
  cache's `--write-registers file:<path>` reads this shape; the same
  object rides a device profile under `acl`/`write`.
- **`modbus-cache-filter.json`** — the cache's selection file: the
  essential SUN2000 fetch list (profile names only — the loader checks
  them against the device profile at load). The `--selection` flag, the
  `SELECTION` env twin and the config's `set modbus selection` all point
  at this shape;
  [shared/schema/modbus-cache-filter.schema.json](../../shared/schema/modbus-cache-filter.schema.json)
  is the schema.

## Keeping it honest

```bash
python3 scripts/lint/acl.py --check                       # lints the acl files (bare run)
python3 scripts/editor.py acl extras/examples/acl-ip-prefix.json  # the terminal editor
python3 scripts/validate_json.py shared/schema/modbus-cache-filter.schema.json \
    extras/examples/modbus-cache-filter.json              # the selection example vs its schema
```

The loader (`common/settings/config.py`'s `_write_gate_object` — one gate
validator for the family) stays the strict word;
[shared/schema/](../../shared/schema/README.md) carries the JSON Schema.
