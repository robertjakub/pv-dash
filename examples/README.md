# Shared examples

The suite-wide sample files — one copy each, at the repo root. A file
lives here when two or more tools ship it; the tool-local samples stay in
each tool's own `examples/` dir (`cache/examples/`, `scraper/examples/`,
`dashboard/examples/`). No tool loads from this directory — the loaders
resolve operator paths (the flags, the env twins, the `file:` values);
these files are the samples, and every `package.nix` installs its packaged
copy into `share/<tool>/`.

## Files

- **`acl-ip-prefix.json`** — the standalone acl file: the ip-prefix
  connect gate. The chain reads top to bottom, the LAST matching rule
  decides, and a client no rule decides refuses (the default deny any);
  the matcher word `any` is the whole space (0.0.0.0/0 — both address
  families). Every tool's `file:` acl knob reads this shape — the cache's
  `acl/connect` + `acl/write`, the scraper's and the fake inverter's
  `metrics/acl`, the dashboard's `metrics-acl`
  ([docs/ACL.md](../docs/ACL.md) is the family-wide story).

## Keeping it honest

```bash
python3 scripts/lint_acl.py --check                       # lints the whole dir (bare run)
python3 scripts/edit_acl.py examples/acl-ip-prefix.json   # the terminal editor
```

The loader (`common/settings/config.py`'s `_write_gate_object` — one gate
validator for the family) stays the strict word;
[shared/schema/](../schema/README.md) carries the JSON Schema.
