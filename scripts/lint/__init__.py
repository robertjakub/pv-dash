"""The scripts' linters, one directory: lint_acl.py (the acl gate
objects), lint_options.py (the registries' canonical layout + the family
passes), lint_readmes.py (the tool READMEs' skeleton) and lint_texts.py
(the static-texts registry). Each runs standalone
(`python3 scripts/lint/<stem>.py`) and imports as `lint.<stem>` — the
consumers (editor.py, family_drift.py, option_diff.py)
speak the package spelling. The NAME is uncontested: no tool imports
`lint` (the family's lib/ packages own `lib`, `lint` was free). Stdlib
only."""
