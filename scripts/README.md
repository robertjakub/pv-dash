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
  NixOS-option parity, the row defaults present and conv-typed (a
  secret carries none), the ops-verbs default pinned to the
  derivation, the bundled configs naming registry options
  only. `python3 scripts/check_options.py` (the ten-suite battery's
  precondition).
- **`lint_options.py`** — lint + reformat the four
  `lib/options.json` registries: the canonical row order, the
  hand-formatted layout (edits must be surgical — the lint enforces
  it). `--check` for the gates.
- **`editor.py`** — the combined terminal editor, word subcommands:
  `options [<project>]` (the registry's dialog + line mode, the
  row surgery the hand-formatting demands) and `acl [--type <t>]
  <file>` (the standalone gate's editor — the loader-gated save,
  the SIGINT-blocked writes, the ^C-safe dialogs).
- **`set_group.py` / `set_live.py`** — the one-field surgical
  setters (an option row's `group` / `live`), riding `scriptlib.py`'s
  row-locator and the live-name rule.
- **`list_options.py`** — the knobs' one-line listing, one flat table
  with the tool as the first column (the live names, the flags, the
  env twins — the merged-knob census view; the hierarchy-node rows
  stay hidden unless `--nodes`, `--sort` orders by knob name,
  `--hide` drops whole sections / `--show` keeps only them, comma
  separated, `--tool` names the tools comma separated with `all`
  the default). The census's one home — the registries are the truth,
  this is the cross-tool view
  on demand.
- **`compare_options.py`** — the knobs compared across the tools: the
  rows grouped by their flat name, the four identity fields checked
  (the flat name, the live path, the env twin, the flag) — identical
  in every tool that carries the knob = the common candidates (the
  shared-definition list); any drift prints as a per-tool table, one
  line per field, `*` on the drifted values, the drifting fields
  named on the knob's header line; the single-tool knobs and the
  near-misses (one live path answering to several flat names, an
  alias only some tools carry) follow as notes. `--tool` names the
  tools comma separated with `all` the default.
- **`options_drift.py`** — the knobs compared against the canon: every
  knob in its FOLDED form (the loader's own `canon_fold`), the canon
  blocks' adoption census (FAMILY / partial / DEAD), the rows that
  contradict their own block (the inline-wins overrides) beside the
  block gaps (the fold-up candidates), the promotion list (the whole
  shape agreeing, still inline) and the shape-field drifts that block a
  shared definition; `live`/`alias`/`node`/`no-env`/`group` are the
  per-tool console placements and never gate a match. Report only —
  the form gates live in `lint_options.py`, the tool-vs-tool identity
  fields in `compare_options.py`. `--tool` names the tools comma
  separated with `all` the default.
- **`option_diff.py`** — one flat name, every tool, every section: the
  deep diff beside the family-scale pair (`compare_options.py` the
  identity fields, `options_drift.py` the whole family). The search
  walks the registry's three sections (options, show, commands — the
  canon's own three) and every one that rows the name reports: the
  EFFECTIVE rows per tool (the loader's own `canon_fold`), the
  byte-identical field on one line and the drift one tool per line
  (`*` on the off-majority values), the canon state (the block, the
  refs, the inline-wins deviations, the block gaps) and the move
  verdict — what riding shared/options.json takes: the fields the
  block could carry (byte-identical on every carrier), the console
  placements the house keeps on the rows, the gated drift with its
  exempt status, and the must-ref / byte-equal-twins predictions. The
  verdict re-uses `lint_options.py`'s own GATED/EXEMPT/SECTION_FIELD/
  KEY_RANK and the loader's `canon_fold` — it can never drift from the
  gates it predicts. `python3 scripts/option_diff.py <flat-name>`;
  `--tool` names the tools comma separated with `all` the default.

## The checks (the shipped artifacts)

- **`lint_acl.py`** — the acl gate-objects: the standalone
  `file:<path>` targets and the `extras/examples/` acl files; the typed
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
- **`lint_readmes.py`** — the four tool READMEs' skeleton gate: the
  `##` canon in order (how it works → usage → configuration → runtime
  control → the tool's own sections in the feature slot → security →
  testing → Nix / NixOS → source layout → license) and a `### Signals`
  block leading the Runtime-control H3s. Report only — the findings
  name the moves, the edits stay human. `--check` is the gate
  spelling; `family_drift.py` prints the same verdict beside the
  ladders.

## The generators

- **`gen_man.py`** — the man pages from the live parsers + each
  tool's `lib/man.py` prose (`--man` renders through the bin; the
  shipped pages regenerate).
- **`gen_manual.py`** — the four `<tool>/MANUAL.md` pages from the
  registries: every command, knob and show report the tool's control
  wire answers, the kind of each (command, settable — set/clear — or
  show-only; the startup-only knobs marked), the flag/env twin, the
  value shape. `--check` fails a stale page.
- **`gen_examples.py`** — the family's example files from the
  registries, one generator + `--check` for both surfaces: the four
  docker env examples (`docker/env/<tool>.env.example` — the full
  env-twin set per tool, grouped by the knob's namespace node, the
  image's own CMD/ENV values as the sample lines, the secrets' lines
  empty) and the four tools' example configuration scripts
  (`<tool>/examples/<conf>` — every knob the registry declares, every
  line commented at its default, the secrets in their `file:<path>`
  form). `--check` fails a drifted example.
- **`gen_sbom.py`** — the CycloneDX 1.5 SBOM (docs/sbom/), the
  stdlib-only claim machine-checked.

The generated pages and their gates (never hand-edit — an editorial
change lands in the generator's constants, then regenerates; a hand
edit to the rendered page dies at the next run):

| Page | Generator | Gate |
|---|---|---|
| [docs/family-drift.md](../docs/family-drift.md) + the seed ledger | `family_drift.py` | `--check` |
| `<tool>/MANUAL.md` (×4) | `gen_manual.py` | `--check` |
| `docker/env/<tool>.env.example` (×4) + `<tool>/examples/*.conf` (×4) | `gen_examples.py` | `--check` |
| `<tool>/man/*.1` (×4) | `gen_man.py` | `mandoc -Tlint` |
| [docs/sbom/](../docs/sbom/SBOM.md) (the SBOM pair) | `gen_sbom.py` | `--check` |

## The release

- **`release.py`** — the orchestrator: the battery (tests/battery.py
  `full` — the runner owns the run dir, the tally and the failed-run
  backups; the `--tests quick` pair rides `--depth full`) + the nix build
  gate first, the version bump, the CHANGELOG split maintenance
  (Unreleased + current in the root, the archive in
  docs/history/CHANGELOG.md), the tag + the GH release cut. Dry-run leaks
  the bump; re-run with `--tests none` after a mid-flight fix.

## Keeping it honest

```bash
python3 scripts/check_options.py && python3 scripts/lint_options.py --check
python3 scripts/lint_readmes.py --check    # the READMEs' skeleton gate
python3 scripts/family_drift.py            # regenerate the drift doc
python3 scripts/family_drift.py --check    # stale doc fails
```

## TODO (the scripts' own — separate from docs/TODO.md)

- **cleanup**
  - the prose-mangling class guard: the editor.py replace paths
    (the ones that produced the scraper's audit rows'
    "keeps)"/"rotations)" (docs/family-drift.md's knobs findings) get a
    render-and-diff guard — a row edit that changes sibling rows' text
    fails loud.
  - the exit-sweep's precision: `family_drift.py`'s refusal-text
    canon buckets the `SystemExit(variable)` sites properly (the
    nearest-text walk is linear over the enclosing block; make it the
    enclosing function's last literal).
  - the dropped riders: gen_man.py's regeneration rides
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
    gen_sbom's shape — one helper, all generators on it.
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
