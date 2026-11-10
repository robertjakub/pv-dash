# Scripts

The repo's tooling — everything `scripts/` carries: the option
registries' gates and editors, the generators, the release runner and
the drift workflow. All stdlib-only, mode 644 (the family's bins run
via `python3`, no exec bits), the shared plumbing seeded in
`scriptlib.py`. The tools' own stories live in their READMEs; this
directory's TODO section is separate from [docs/TODO.md](../docs/TODO.md)
— the scripts' debts stay with the scripts.

## The registries (read, gate, edit)

- **`check_options.py`** — the option gates, per tool: every live
  setting unique and word-path clean, every flag/env/secret/restart
  row honest, the show/commands vocabularies, the README-flag and the
  NixOS-option parity, the bundled configs naming registry options
  only. `python3 scripts/check_options.py` (the ten-suite battery's
  precondition).
- **`lint_options.py`** — lint + reformat the four
  `lib/options.json` registries: the canonical row order, the
  hand-formatted layout (edits must be surgical — the lint enforces
  it). `--check` for the gates.
- **`edit_options.py`** — the registry's terminal editor (two faces,
  one core): the row surgery the hand-formatting demands.
- **`set_group.py` / `set_live.py`** — the one-field surgical
  setters (an option row's `group` / `live`), riding `scriptlib.py`'s
  row-locator and the live-name rule.
- **`list_options.py`** — the knobs' one-line listing (the live
  names, the flags, the env twins — the merged-knob census view).

## The checks (the shipped artifacts)

- **`lint_acl.py`** — the acl gate-objects: the standalone
  `file:<path>` targets and the root `examples/` acl files; the typed
  rule chain's grammar. Bare run globs the root.
- **`validate_json.py`** — the JSON documents against a JSON Schema
  (stdlib only): the loader-valid ⊂ schema-valid contract.
- **`audit_verify.py`** — the audit trail's chained-hash verifier
  (the F10 chain: every line carries its hash right after the event
  name).
- **`family_drift.py`** — the drift workflow: the thirteen sweep
  types (the code, the surface, the knobs, the wire-text, the
  exit/refusal, the rendered surfaces, the NixOS parity, the
  docker/env, the suite coverage, the F-ledger, the statics, the
  schema/example, the secret surface) regenerate
  [docs/family-drift.md](../docs/family-drift.md); the verdict prose
  lives in the script's blocks. `--check` exits 1 when the doc is
  stale.

## The generators

- **`gen_man.py`** — the man pages from the live parsers + each
  tool's `lib/man.py` prose (`--man` renders through the bin; the
  shipped pages regenerate).
- **`gen_options.py`** — docs/OPTIONS.md from the registries (the
  one-table knob census).
- **`gen_manual.py`** — the four `<tool>/MANUAL.md` pages from the
  registries: every command, knob and show report the tool's control
  wire answers, the kind of each (command, settable — set/unset — or
  show-only; the startup-only knobs marked), the flag/env twin, the
  value shape. `--check` fails a stale page.
- **`gen_sbom.py`** — the CycloneDX 1.5 SBOM (docs/sbom/), the
  stdlib-only claim machine-checked.

## The release

- **`release.py`** — the orchestrator: the suites + the nix build
  gate first, the version bump, the CHANGELOG split maintenance
  (Unreleased + current in the root, the archive in
  docs/history/CHANGELOG.md), the tag + the GH release cut. Dry-run leaks
  the bump; re-run with `--tests none` after a mid-flight fix.

## Keeping it honest

```bash
python3 scripts/check_options.py && python3 scripts/lint_options.py --check
python3 scripts/family_drift.py            # regenerate the drift doc
python3 scripts/family_drift.py --check    # stale doc fails
```

## TODO (the scripts' own — separate from docs/TODO.md)

- **cleanup**
  - the prose-mangling class guard: the edit_options.py replace paths
    that produced the scraper's audit rows' "keeps)"/"rotations)"
    (docs/family-drift.md's knobs findings) get a render-and-diff
    guard — a row edit that changes sibling rows' text fails loud.
  - the exit-sweep's precision: `family_drift.py`'s refusal-text
    canon buckets the `SystemExit(variable)` sites properly (the
    nearest-text walk is linear over the enclosing block; make it the
    enclosing function's last literal).
  - the dropped riders: gen_man.py/gen_options.py regenerations ride
    release.py's flow explicitly (the `--tests none` re-run path
    should not skip the doc regens silently).
- **consolidate**
  - `scriptlib.py` grows: the tree-walk (the
    tools × lib/bin + common iteration) is re-implemented in
    `family_drift.py`'s `targets()`, `check_options.py` and
    `lint_options.py` — one walk, one home.
  - the registry loader: the rows/commands/show parse block is
    triplicated (check_options, lint_options, family_drift's knobs
    sweep) — one `load_registry(tool)` in scriptlib, the editors and
    the sweeps on it.
  - the doc-writer helper: the emit-and-check pattern (render, diff,
    exit 1 on stale) is family_drift.py's `--check` and
    gen_options/gen_sbom's shape — one helper, all generators on it.
- **drift check**
  - `family_drift.py --check` joins release.py's gates: a stale
    drift doc (or a regenerating sweep that would change it) fails
    the release the way the suites do.
  - the seed ledger (`family_drift.py --seeds` →
    docs/family-drift-seeds.json): every uncovered promise carries a
    stable ID + the suggested suite; `--check`'s growth gate fails
    when a NEW knob/command/canon phrase ships uncovered — the list
    may only shrink (the wave's proof).
  - the NixOS-parity and docker/env sweeps graduate from census to
    machine gate (the module.nix type/default vs the registry row;
    the env-file coverage vs the env twins) — the sweeps exist, the
    verdicts get asserted.
  - the coverage sweep's seeds get their graduation path into the
    test waves — the sweep prints them, a wave consumes them, the
    list shrinks.
