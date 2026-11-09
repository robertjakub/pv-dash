# shared — the family's data, outside every package

The cross-tool data files, one copy each at the repo root — no package
owns them, and no package ever will: `common/` stays pure code (the
no-formal-package ruling — a plain sys.path package is always exactly
one level below its tree root, which is what the loader's walk leans on).

| path | what |
|---|---|
| `texts.json` | the family's static texts — the console's faces and reconnect ladder, the ctl's, the welcome banners, the wire's fixed replies, the daemon bind/startup lines — the one home `common/render/texts.py`'s dotted `T(key)` reads; `scripts/lint_texts.py --check` gates the references both ways (every reference resolves, every key referenced, no duplicated value) |
| [`schema/`](schema/README.md) | the shared JSON Schemas (draft 2020-12) — a schema lives here when the file it describes is shared; today that is the standalone acl file's [ip-prefix gate](../examples/README.md), validated by `scripts/validate_json.py` |

How the tree is found: the texts loader reads it one `shared/` segment
below the directory that contains `common/` — the same walk in every
layout:

- **checkout** — `<repo>/shared/`, beside `common/`
- **nix package** — each tool's `package.nix` installs `texts.json` to
  `share/<tool>/shared/` (the acl schema rides as the loose
  `acl-ip-prefix.schema.json` beside the tool — the packaged layout is
  unchanged)
- **docker image** — the `shared=` named build context copies the tree
  to `/pv-suite/shared/`

Deliberately *not* here: [`profiles/`](../profiles/README.md) (the
device profiles — one JSON format with a linter and a formatter of
their own) and [`examples/`](../examples/README.md) (the sample files
the tools' `file:` gates point at) stay their own root dirs; the
tool-local schemas stay in each tool's `schema/` dir.

## License

The `shared/` data is licensed under the **BSD 3-Clause License** — see
the repo-root `LICENSE` file.
