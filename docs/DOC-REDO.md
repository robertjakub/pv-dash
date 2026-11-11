# The docs redo — the workflow

How the doc set stays true: the current/history split, the generated
surfaces, and the redo procedure — the steps that catch stale or wrong
information before a release. Run it per wave, and as a full pass
whenever a wave landed doc ripples across tools.

## The doc families (current vs history)

Every doc family is TWO files: the current half answers "what is true
now" (the open findings, the live posture); the history half answers
"how did we get here" (the closed findings, the landed legs, the wave
walk).

| family | the current half | the history half |
|---|---|---|
| the security audit | [AUDIT.md](AUDIT.md) — the open findings, the implemented controls, the posture, the NIS2/DORA map | [history/AUDIT.md](history/AUDIT.md) — the closed findings with fix + verification, the per-revision walk |
| the family drift | [family-drift.md](family-drift.md) (GENERATED) — the census, the open findings, the open remediation | [history/family-drift.md](history/family-drift.md) — the landed legs, the prose catch-ups, the growth rule |
| the changelog | the root [CHANGELOG](../CHANGELOG.md) — Unreleased + the current release | [history/CHANGELOG.md](history/CHANGELOG.md) — the release archive (`scripts/release.py` maintains the split) |
| the TODOs | [TODO.md](TODO.md) — the open items only | the per-tool `TODO.md` files — the Done records, newest first |

Rules across all four families:

- A history record is never rewritten to the present tense. When a
  later wave changes its truth, the record gets a reversing POINTER
  ("since retired by ...", "since re-homed to ...") — the record stays
  the record.
- The current half only SHRINKS its findings (an open item leaves when
  closed — moved to the history half or the per-tool Done records);
  the history half only grows.
- The main docs link their history half; the history half links back.

## The generated docs (never hand-edit)

`docs/family-drift.md` (`scripts/family_drift.py`), `docs/OPTIONS.md`
(`scripts/gen_options.py`), the four `<tool>/MANUAL.md` pages
(`scripts/gen_manual.py --check`), the four tool env examples
(`docker/env/<tool>.env.example`, `scripts/gen_env.py --check`), the man
pages (`scripts/gen_man.py`), the SBOM pair (`scripts/gen_sbom.py
--check`), the seed ledger (`family_drift.py --seeds`). An editorial
change to a
generated doc lands in the GENERATOR's constants (the drift verdicts
live in `family_drift.py`'s `*_FINDINGS`/`*_VERBS`/`*_CENSUS` blocks),
then regenerates — a hand edit to the rendered page dies at the next
run, and `--check` fails a stale page.

## The redo procedure

1. **The gates first** (the machine truth, before any editorial
   judgement):

   ```bash
   python3 scripts/family_drift.py --check
   python3 scripts/check_options.py
   python3 scripts/lint_options.py --check
   python3 scripts/lint_texts.py
   python3 scripts/gen_manual.py --check
   python3 scripts/gen_env.py --check
   python3 scripts/gen_sbom.py --check
   python3 scripts/gen_man.py && mandoc -Tlint <tool>/man/*.1
   ```

   A red gate means the generated layer is stale — regenerate (and fix
   the generator's constants if the verdict prose moved), not the doc.

2. **The retired-vocabulary hunt** in the HAND-written docs (the
   READMEs, docs/common/ACL.md, docs/common/MODBUS.md, docs/NIXOS.md, docs/TODO.md,
   docs/AUDIT.md) — targeted greps for the vocabularies that died:
   retired commands (`show settings`), retired flags (`--host`,
   `--port`, the `-file` siblings), retired env prefixes
   (`MCH_`/`SCR_`/`INV_`/`DSH_`), retired paths (`scrape/`,
   `Dockerfile.cache`), retired postures (the live secret rotation,
   tokenless TCP on the serving tools), retired shapes (the ini
   config).

3. **Verify each suspect against the code** (the registries, the
   static.json defaults, the control.py branches) before editing — a
   doc claim that reads wrong may be the DOC being right and the code
   having drifted; that is a finding, not an edit.

4. **Split by record type**: history records (the per-tool TODO Done
   paragraphs, docs/history/*, the CHANGELOG's released halves) get
   pointers; present-tense claims get fixed. Status claims
   (an F-number open or closed, a knob live or startup-only) check
   against the authority doc — docs/AUDIT.md owns the F-status, the
   registries own the knobs.

5. **The line-number rule**: prose cites code by FILE + FUNCTION name
   (`proxy.py` `respond()`), never by line number — lines rot, names
   survive. The generators render line numbers where they are wanted
   (the drift doc's pairs); the hand-written docs do not.

6. **The landing discipline**: a wave's doc ripples ride the wave's
   commit (the README, the CHANGELOG Unreleased entry, the man prose,
   the per-tool TODO, the generator constants). A wave that lands a
   drift leg moves the finding to docs/history/family-drift.md in the
   same landing — the `--check` cannot catch a verdict that went
   stale, only a census that did.

7. **Regenerate + re-gate**: the generated docs rebuild, then every
   gate in step 1 runs green again. ALL green is the redo's proof.

## The prose discipline

Prose lines ≤ 80 characters (the tables and code blocks are exempt);
the man pages wrap at 72; strict cmark-gfm shape (the lint and the
book build watch it); the texts the code renders ride
shared/texts.json (`scripts/lint_texts.py`), not the docs.
