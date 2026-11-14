# dev/

The repo's tooling and verification — everything `dev/` carries: the
option registries' gates and editors, the linters, the generators, the
release runner, the drift workflow and the test suites with their battery
runner. All stdlib-only, mode 644 (the family's bins run via `python3`,
no exec bits), the shared plumbing in [`lib/`](#the-common-lib), the
linters in [`gates/`](#the-checks), the generators in
[`generators/`](#the-generators), the verification in
[`suites/`](#the-verification) under the
[`battery/`](#the-battery) runner. The tools' own stories live in their
READMEs; this directory's TODO section is separate from
[docs/TODO.md](../docs/TODO.md) — the dev debts stay with the dev tree.

## The common lib

- **`lib/`** — the scripts' own package: `lib/__init__.py` carries the
  flat helpers (the four-tool chain, the registries' row-locator, the
  live-name rule) and puts the repo root on sys.path at import (the
  per-script `REPO = dirname(dirname(…))` dances died with it);
  `lib/registry.py` is the one loader home (the wired `lib/options.py`
  rows — the one-module-named-`options`-at-a-time dance — the raw
  `options.json` read and the loader's own canon fold, the per-tool
  SURFACES map); `lib/walk.py` is the one tree-walk (every per-tool
  lib/bin module + every common module); `lib/emit.py` is the
  emit-and-check doc writer (render, write or diff, exit 1 on stale —
  the generators' `--check` rides it). The NAME is contested: the
  per-tool `lib/` packages own `lib` wherever a tool root precedes
  `dev/` on sys.path, so the editor opens the house's
  one-module-named-`lib`-at-a-time dance around its imports — the rule
  is documented in `lib/__init__.py`.

## The registries (read, gate, edit)

- **`gates/check_options.py`** — the option gates, per tool: every live
  setting unique and word-path clean, every flag/env/secret/restart
  row honest, the show/commands vocabularies, the README-flag and the
  NixOS-option parity, the row defaults present and conv-typed (a
  secret carries none), the ops-verbs default pinned to the
  derivation, the bundled configs naming registry options
   only. `python3 dev/gates/check_options.py` — and a battery suite
   itself:
   [dev/suites/check-options.py](../dev/suites/check-options.py)
   runs the gate first in every profile and re-emits its rows.
- **[`gates/options.py`](gates/options.py)** — lint + reformat the four
  `lib/options.json` registries: the canonical row order, the
  hand-formatted layout (edits must be surgical — the lint enforces
  it). `--check` for the gates; `format` is the write verb.
- **[`editor/editor.py`](editor/editor.py)** — the combined terminal
  editor, word subcommands:
  `options [<project>]` (the registry's dialog + line mode, the
  row surgery the hand-formatting demands) and `acl [--type <t>]
  <file>` (the standalone gate's editor — the loader-gated save,
  the SIGINT-blocked writes, the ^C-safe dialogs). The one-field
  surgical setters (`set_group.py` / `set_live.py`) retired — the
  dialog edits every field they did.
- **`list_options.py`** — the knobs' one-line listing, one flat table
  with the tool as the first column (the live names, the flags, the
  env twins — the merged-knob census view; the hierarchy-node rows
  stay hidden; `--sort` orders by knob name,
  `--hide` drops whole sections / `--show` keeps only them, comma
  separated, `--tool` names the tools comma separated with `all`
  the default). The census's one home — the registries are the truth,
  this is the cross-tool view
  on demand.
- **[`options_compare.py`](options_compare.py)** — the registries'
  compare tools, one script, three lenses:
  `family` (the default) groups the knob rows by flat name and checks
  the four identity fields (the flat name, the live path, the env twin,
  the flag) — identical in every tool that carries the knob = the
  common candidates (the shared-definition list); any drift prints as a
  per-tool table, one line per field, `*` on the drifted values, the
  drifting fields named on the knob's header line; the single-tool
  knobs and the near-misses (one live path answering to several flat
  names, an alias only some tools carry) follow as notes. `drift` puts
  every knob in its FOLDED form (the loader's own `canon_fold`) against
  the canon: the canon blocks' adoption census (FAMILY / partial /
  DEAD), the rows that contradict their own block (the inline-wins
  overrides) beside the block gaps (the fold-up candidates), the
  promotion list (the whole shape agreeing, still inline) and the
  shape-field drifts that block a shared definition;
  `live`/`alias`/`node`/`no-env`/`group` are the per-tool console
  placements and never gate a match. `name <flat>` is the deep diff on
  one registry name across the three sections (options, show, commands
  — the canon's own three): the EFFECTIVE rows per tool (the loader's
  own `canon_fold`), the byte-identical field on one line and the drift
  one tool per line (`*` on the off-majority values), the canon state
  (the block, the refs, the inline-wins deviations, the block gaps) and
  the move verdict — what riding shared/suite/options.json takes: the
  fields the block could carry (byte-identical on every carrier), the
  console placements the house keeps on the rows, the gated drift with
  its exempt status, and the must-ref / byte-equal-twins predictions.
  The name verdict re-uses `gates/options.py`'s own
  GATED/EXEMPT/SECTION_FIELD/KEY_RANK and the loader's `canon_fold` —
  it can never drift from the gates it predicts. Report only — the form
  gates live in `gates/options.py`.
  `python3 dev/options_compare.py name <flat-name>`; `--tool` names
  the tools comma separated with `all` the default.

## The checks (the shipped artifacts)

The gates live in [`gates/`](gates) — one directory, everything that
exits 1 on red (the registry and prose lints, the structural gates, the
verifiers):

- **[`gates/acl.py`](gates/acl.py)** — the acl gate-objects: the standalone
  `file:<path>` targets and the `extras/examples/` acl files; the typed
  rule chain's grammar. Bare run lints the root; `format` is the write
  verb.
- **[`gates/profile.py`](gates/profile.py)** — the device profiles: the
  schema + style lint (the default verb) and `format`, the canonical
  in-place rewrite (`--check`/`--diff` report the drift without writing).
  Bare run lints `shared/profiles/*.json`.
- **`gates/validate_json.py`** — the JSON documents against a JSON Schema
  (stdlib only): the loader-valid ⊂ schema-valid contract.
- **[`gates/links.py`](gates/links.py)** — the hand-written docs' link
  gate: every relative markdown link and mdbook include target
  resolves, and every repo-rooted path token in a current doc names
  something that exists (the history records keep their landed
  spellings — the token check skips `docs/history/` and the per-tool
  TODOs; the links check runs everywhere). Bare run reports,
  `--check` is the gate spelling — and a battery suite itself:
  [dev/suites/links-check.py](../dev/suites/links-check.py) rides
  every profile beside check-options. The family's other rc-1 gates
  ride the `lint-gates` suite the same way (one check() row each): the
  acl/options/readmes/texts/profile lints, the manual/examples/sbom
  `--check`s and the drift doc's `--check` —
  [dev/suites/lint-gates.py](../dev/suites/lint-gates.py).
- **`gates/audit_verify.py`** — the audit trail's chained-hash verifier
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
- **[`gates/readmes.py`](gates/readmes.py)** — the four tool READMEs' skeleton gate: the
  `##` canon in order (how it works → usage → configuration → runtime
  control → the tool's own sections in the feature slot → security →
  testing → Nix / NixOS → source layout → license) and a `### Signals`
  block leading the Runtime-control H3s. Report only — the findings
  name the moves, the edits stay human. `--check` is the gate
  spelling; `family_drift.py` prints the same verdict beside the
  ladders.

## The generators

The four live in [`generators/`](generators) — one directory, the
shipped-artifact renderers apart from the gates:

- **`generators/man.py`** — the man pages from the live parsers + each
  tool's `lib/man.py` prose (`--man` renders through the bin; the
  shipped pages regenerate).
  tool's control wire answers, the kind of each (command, settable —
  set/clear — or show-only; the startup-only knobs marked), the
  flag/env twin, the value shape. `--check` fails a stale page.
- **`generators/examples.py`** — the family's example files from the
  registries, one generator + `--check` for both surfaces: the four
  docker env examples (`docker/env/<tool>.env.example` — the full
  env-twin set per tool, grouped by the knob's namespace node, the
  image's own CMD/ENV values as the sample lines, the secrets' lines
  empty) and the four tools' example configuration scripts
  (`<tool>/examples/<conf>` — every knob the registry declares, every
  line commented at its default, the secrets in their `file:<path>`
  form). `--check` fails a drifted example.
- **`generators/sbom.py`** — the CycloneDX 1.5 SBOM (docs/sbom/), the
  stdlib-only claim machine-checked.

The generated pages and their gates (never hand-edit — an editorial
change lands in the generator's constants, then regenerates; a hand
edit to the rendered page dies at the next run):

| Page | Generator | Gate |
|---|---|---|
| [docs/family-drift.md](../docs/family-drift.md) + the seed ledger | `family_drift.py` | `--check` |
| `docker/env/<tool>.env.example` (×4) + `<tool>/examples/*.conf` (×4) | `generators/examples.py` | `--check` |
| `<tool>/man/*.1` (×4) | `generators/man.py` | `mandoc -Tlint` |
| [docs/sbom/](../docs/sbom/SBOM.md) (the SBOM pair) | `generators/sbom.py` | `--check` |

## The verification

The suites always run through the battery — one implementation each, no
twins:

- **`battery/`** — the battery runner's home: `battery.py` (the
  profiles, the port slots, the tally, the eta history),
  `battery_status.py` (the read-only live view — the run ids, the pids,
  the live check counts, the `--watch` loop) and `battery_kill.py` (the
  slot killer — TERM the runner and its tree, KILL what outlives the
  grace window). The spellings: `python3 dev/battery/battery.py …`,
  `python3 dev/battery/battery_status.py` — or the dev-root hand-off
  `python3 dev/battery_status.py` (the execv wrapper: the argv, the exit
  codes and the signals ride; the real view is the only implementation).

- **`suites/`** — the suite bodies, one file per battery suite. Each
  body's first lines seed the harness home onto sys.path and boot from
  it — the bare `from harness import *`; the import IS the boot: the
  PV_RUN_DIR gate (a standalone run refuses), the scratch under the
  battery's run dir, the NOTE stamp, the check accumulator, the shared
  daemon spawn (`start`/`kill_all`), the Modbus frame builders and the
  pty trio. The battery resolves `dev/suites/<name>.py` straight off
  the profile strings, and the CI legs run
  `python3 dev/suites/<name>.py` — one spelling everywhere, renames
  cannot desynchronize.

- **`harness/`** — `harness.py`, the one implementation every suite
  rides. The dir carries the module's own name, so the per-tool `lib/`
  packages can never shadow it.

## The release

- **`release.py`** — the orchestrator: the battery (dev/battery/battery.py
  `full` — the runner owns the run dir, the tally and the failed-run
  backups; the `--tests quick` pair rides `--depth full`) + the nix build
  gate first, the version bump, the CHANGELOG split maintenance
  (Unreleased + current in the root, the archive in
  docs/history/CHANGELOG.md), the tag + the GH release cut. Dry-run leaks
  the bump; re-run with `--tests none` after a mid-flight fix.

## Keeping it honest

```bash
python3 dev/gates/check_options.py && python3 dev/gates/options.py --check
python3 dev/gates/readmes.py --check    # the READMEs' skeleton gate
python3 dev/family_drift.py            # regenerate the drift doc
python3 dev/family_drift.py --check    # stale doc fails
```

## TODO (the dev tree's own — separate from docs/TODO.md)

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
  - the dropped riders: man.py's regeneration rides
    release.py's flow explicitly (the `--tests none` re-run path
    should not skip the doc regens silently).
- **consolidate**
  - *(closed — the dev/lib wave)*: the tree-walk is `lib/walk.py`'s
    one `targets()`, the registry parse block is `lib/registry.py`'s
    loaders, the emit-and-check pattern is `lib/emit.py`'s.
- **drift check**
  - `family_drift.py --check` joins release.py's gates: a stale
    drift doc (or a regenerating sweep that would change it) fails
    the release the way the suites do.
  - the seed ledger (docs/family-drift-seeds.json, the drift sweep's
    data): every uncovered promise carries a
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
