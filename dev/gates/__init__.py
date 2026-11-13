"""The scripts' gates, one directory: acl.py (the acl gate
objects), options.py (the registries' canonical layout + the family
passes), profile.py (the device profiles — the schema lint + the
canonical format), readmes.py (the tool READMEs' skeleton) and texts.py
(the static-texts registry). Each runs standalone
(`python3 dev/gates/<stem>.py`) and imports as `gates.<stem>` — the
consumers (editor.py, family_drift.py, option_diff.py)
speak the package spelling. The NAME is uncontested: no tool imports
`gates` (the family's lib/ packages own `lib`, `gates` is free).

One CLI grammar: `lint` is the default verb — report only, never
writes; `format` rewrites in place where a renderer exists, with
`--check`/`--diff` reporting the drift without the write; `--check`
bare stays the CI gate spelling everywhere. The two members without a
renderer (readmes.py, texts.py) refuse `format` — their edits stay
human. The shared core rides the sibling `_common.py` (the grammar
parser, the terse-ASCII desc check, the START:COUNT range matcher, the
one-line-object render, the --diff emission), imported dual-mode —
`gates._common` under the package, `_common` on the bare run; the
scripts' own `lib` is contested, so the sibling import never touches
it. Stdlib only."""
