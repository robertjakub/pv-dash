# shared — the family's data, outside every package

The cross-tool data files, one copy each at the repo root — no package
owns them, and no package ever will: `common/` stays pure code (the
no-formal-package ruling — a plain sys.path package is always exactly
one level below its tree root, which is what the loader's walk leans on).

| path | what |
|---|---|
| `texts.json` | the family's static texts — the console's faces and reconnect ladder, the ctl's, the welcome banners, the wire's fixed replies, the daemon bind/startup lines — the one home `common/render/texts.py`'s dotted `T(key)` reads; `scripts/lint_texts.py --check` gates the references both ways (every reference resolves, every key referenced, no duplicated value) |
| `tags.json` | the audit trail's tool tags, one per tool — `{"cache": "CACHE", "scraper": "SCR", "inverter": "INV", "dashboard": "DSH"}`; `common/runtime/audit.py`'s `load_audit_tags(tool)` reads the tag and fails loud on a malformed file — the daemon's line speaks `application=CACHE tag=daemon`, the ctl and cli clients `application=CACHE tag=cli`, so a deployment renames its `CACHE`/`SCR`/`INV`/`DSH` tool tag in one place |
| `options-help.json` | the option registries' canon — per knob, the family-wide fields: a block may carry every row key but the three placement keys (`name` — the flat name IS the block's key; `only`; `shared` — the ref itself), so the prose, the wiring that agrees (`flag`, `env`, `conv`, `min`/`max`, the marks) and the tuning that agrees (`default`, the `alias`) ride together; a registry row references its block with `"shared": "<name>"` and the loader folds the block under the row's own fields (the row's inline field wins — the per-tool override). The `show`/`commands` sections are the flat word -> text maps the show/command rows fold from, or the same fold one shape up — a dict block carrying the row's fields (`internal`, `hidden`, ...). One edit updates every tool's --help, man page, wire help and docs. `scripts/lint_options.py --check` gates it both ways: every ref resolves, every block referenced, a block never wears a placement key or an unknown key, the ≥3-tool byte-identical text must ref, and the gated fields stay byte-identical across the four registries (or ride the lint's named exemption) |
| [`schema/`](schema/README.md) | the shared JSON Schemas (draft 2020-12) — a schema lives here when the file it describes is shared; today that is the standalone acl file's two gates (the [ip-prefix](../extras/examples/README.md) connect gate + the write-registers gate), validated by `scripts/validate_json.py` |

How the tree is found: the texts loader reads it one `shared/` segment
below the directory that contains `common/` — the same walk in every
layout:

- **checkout** — `<repo>/shared/`, beside `common/`
- **nix package** — each tool's `package.nix` installs `texts.json` and
  `tags.json` to `share/<tool>/shared/` (the acl schemas ride as the loose
  `*.schema.json` beside the tool — the packaged layout is
  unchanged)
- **docker image** — the `shared=` named build context copies the tree
  to `/pv-suite/shared/`

Deliberately *not* here: [`profiles/`](../profiles/README.md) (the
device profiles — one JSON format with a linter and a formatter of
their own) stays its own root dir, while
[`extras/examples/`](../extras/examples/README.md) (the sample files
the tools' `file:` gates point at) and
[`extras/alerts/`](../extras/alerts/README.md) (the Prometheus rule
pack — shipped by the watched exporters' packages, loaded by no tool)
live under `extras/` with the other operator-side packs; the
tool-local schemas stay in each tool's `schema/` dir.

## License

The `shared/` data is licensed under the **BSD 3-Clause License** — see
the repo-root `LICENSE` file.
