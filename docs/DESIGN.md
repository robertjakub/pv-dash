# The suite's design (DESIGN.md)

One product, four tools: the modbus-cache proxy, the modbus-scraper
exporter, the modbus-fake-inverter and the dashboard — one shared core
(`common/`), one control-wire grammar, one option registry per tool.
This page is the map and the maintenance in one: the shape, every doc
filed by grain (one home per story, the ledgers split current vs
history), and the redo that keeps the doc set true — run it per wave,
and as a full pass whenever a wave landed doc ripples across tools.

## The shape

- **the data plane** — the fake serves the register profile; the cache
  proxies it (the write-through, the caps, the auth handshake); the
  scraper polls an upstream (the cache or a real device) and exports
  `/metrics` for the prometheus pull; the dashboard renders a
  `/metrics` source.
- **the control plane** — every tool serves the same wire
  (`common/wire/control.py`): the signed frames, the peer-cred trusted
  peers, the RBAC roles, the ctl/cli consoles speaking the one command
  spine (`common/control.py`).
- **the config plane** — the resolver ladder flag > env > config
  script > the registry row's default, one registry per tool
  (`<tool>/lib/options.json`), the knobs settable live or
  restart-marked, the secrets startup-only.

## The docs, filed by grain

| Grain | Home |
|---|---|
| the mechanism specs (the shared core) | [common/MODBUS.md](common/MODBUS.md) (the protocol, the profiles, the auth), [common/ACL.md](common/ACL.md) (the gates), [common/static-defaults.md](common/static-defaults.md) (the defaults ladder + the gate) |
| the security ledger | [SECURITY.md](SECURITY.md) — the open findings, the posture, the NIS2/DORA map; the closed half in [history/AUDIT.md](history/AUDIT.md) (the closed findings with fix + verification, the per-revision walk) |
| the ledgers (open vs history) | [TODO.md](TODO.md) — the open items (the one-product sweep rides as its section) + the per-tool `TODO.md` Done records; [history/family-unify.md](history/family-unify.md) — the sweep's verified-aligned ledger (do not re-open); the generated [family-drift.md](family-drift.md) (the census + the open findings) + [history/family-drift.md](history/family-drift.md) (the landed legs) |
| the release history | the root [CHANGELOG](../CHANGELOG.md) (Unreleased + the current release), [history/CHANGELOG.md](history/CHANGELOG.md) (the archive — `scripts/release.py` maintains the split) |
| the maintenance | this page's redo (below), [scripts/README.md](../scripts/README.md) (the gates + the editors) |
| the deployment | [docker/README.md](../docker/README.md) (the stacks, the env files, the secrets), [nixos/README.md](../nixos/README.md) (the one Nix reference) |
| the supply chain | [sbom/SBOM.md](sbom/SBOM.md) |
| the operator packs | [extras/](../extras/README.md) — the [alert rules](../extras/alerts/README.md) (one file per watched exporter), the [shared sample files](../extras/examples/README.md) the `file:` acl gates point at, the [graylog pack](../extras/graylog/README.md) |

The per-tool surfaces live in the tools' own READMEs and MANUALs; the
book (`docs/book/`, built from `book/src/`) carries the reader tour,
this page beside the index.

The ledger rules (every doc family is TWO files — the current half
answers "what is true now", the history half "how did we get here"):

- A history record is never rewritten to the present tense. When a
  later wave changes its truth, the record gets a reversing POINTER
  ("since retired by ...", "since re-homed to ...") — the record stays
  the record.
- The current half only SHRINKS its findings (an open item leaves when
  closed — moved to the history half or the per-tool Done records);
  the history half only grows.
- The main docs link their history half; the history half links back.

The generated pages — the drift doc + the seed ledger, the four
MANUALs, the four env examples, the man pages, the SBOM pair —
are inventoried with their generators and gates in the generators
section of [scripts/README.md](../scripts/README.md). An editorial
change to a generated doc lands in the GENERATOR's constants (the
drift verdicts live in `family_drift.py`'s
`*_FINDINGS`/`*_VERBS`/`*_CENSUS` blocks), then regenerates — a hand
edit to the rendered page dies at the next run, and `--check` fails a
stale page.

## The docs redo

The procedure that catches stale or wrong information before a
release.

1. **The gates first** (the machine truth, before any editorial
   judgement):

   ```bash
   python3 scripts/family_drift.py --check
   python3 scripts/check_options.py
   python3 scripts/lint_options.py --check
   python3 scripts/lint_texts.py
   python3 scripts/gen_manual.py --check
   python3 scripts/gen_examples.py --check
   python3 scripts/gen_sbom.py --check
   python3 scripts/gen_man.py && mandoc -Tlint <tool>/man/*.1
   ```

   A red gate means the generated layer is stale — regenerate (and fix
   the generator's constants if the verdict prose moved), not the doc.

2. **The retired-vocabulary hunt** in the HAND-written docs (the
   READMEs, docs/DESIGN.md, docs/common/, nixos/README.md,
   docs/TODO.md, docs/SECURITY.md) — targeted
   greps for the vocabularies that died:
   retired commands (`show settings`), retired flags (`--host`,
   `--port`, the `-file` siblings), retired env prefixes
   (`MCH_`/`SCR_`/`INV_`/`DSH_`), retired paths (`scrape/`,
   `Dockerfile.cache`), retired postures (the live secret rotation,
   tokenless TCP on the serving tools), retired shapes (the ini
   config).

3. **Verify each suspect against the code**    (the registries, the
   `lib/defaults.json` statics, the control.py branches) before editing — a
   doc claim that reads wrong may be the DOC being right and the code
   having drifted; that is a finding, not an edit.

4. **Split by record type**: history records (the per-tool TODO Done
   paragraphs, docs/history/*, the CHANGELOG's released halves) get
   pointers; present-tense claims get fixed. Status claims
   (an F-number open or closed, a knob live or startup-only) check
   against the authority doc — docs/SECURITY.md owns the F-status, the
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
