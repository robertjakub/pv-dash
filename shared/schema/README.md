# Shared JSON Schemas

Draft-2020-12 schemas for the suite-wide sample files — one copy each,
under `shared/` (the family's shared-data home). The tool-local schemas
stay in each tool's `schema/` dir
(`scraper/schema/` for the metrics spec). A schema lives here when the
file it describes is shared: today that is the standalone acl file's
two gates — the [ip-prefix](../../extras/examples/README.md) connect gate and the
write-registers gate — whose `$id`s point here, and the cache's
selection file (the fetch list the modbus-cache `--selection` knob
reads).

## The contract

**Loader-valid ⊆ schema-valid.** The loader is the strict word: a
loader-refused file can still be schema-valid (a prefix with host bits
set, a malformed v6 spelling) — the schema is the editor's lint, not the
daemon. Wire an editor in by `$schema` pattern-matching for live
feedback while editing.

## Validate

```bash
python3 scripts/validate_json.py shared/schema/acl-ip-prefix.schema.json extras/examples/acl-ip-prefix.json
python3 scripts/validate_json.py shared/schema/acl-write-registers.schema.json extras/examples/acl-write-registers.json
python3 scripts/validate_json.py shared/schema/modbus-cache-filter.schema.json extras/examples/modbus-cache-filter.json
```

The repo's own stdlib-only checker speaks the draft-2020-12 core the
repo's schemas use — `jsonschema` is not a dependency.
