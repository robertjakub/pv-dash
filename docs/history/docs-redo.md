# docs-redo — the full documentation wave proposal

Status: **landed** — the Nov 13 audit's work order, flown Nov 13 (the
per-surface commits end at the CHANGELOG's Unreleased "The docs redo
flies" entry). Three sweeps read every hand-written doc against the
tree (the tool READMEs and TODOs, the support READMEs, the family
ledgers), plus an automated path-token resolution pass over all of it.
Every finding below was re-verified by hand before entry; the spot-check
also DISCARDED five agent findings — `docker/prod/README.md`'s
`AUTH_TOKEN` is the dashboard's genuine env twin
(`apps/dashboard/lib/options.json` `auth-token`), the `docker/demo`
"ctl" wording does not exist, `extras/README.md`'s "every package"
quote does not reproduce, SECURITY's closed enumeration is complete
(F19 lives inside F18–F23; F14/F15/F17 are the open set) and
`scripts/README`'s lib block already listed `registry.py`. Two more
died at fly: the dashboard image DOES ship a HEALTHCHECK
(`docker/Dockerfile.dashboard` — `dashboard-cli ping`), and the unix
control-socket story is the containers' truth (the healthchecks speak
it in-container). The ledger's additions at fly: the four
`docker/README.md` tool links, DESIGN's `common/control.py` + man-page
gate paths, SECURITY's `ctl/cli` client rows, nixos/README's
`tests/hardening.nix` cite, the four Dockerfile build headers' `../apps`
depth, and the examples generator's latent `', '.join(bool)` crash. The
suite-name lesson: the battery's zz_ copy runs `tests/<name>.py`, so
the profile spelling, the wrapper and the runpy's join arg must agree —
the first battery run NOT-GREENed the twin twice on a name the profiles
spelled one way and the files another.

The machine truth first: every gate ran green at the audited tree —
`family_drift --check`, `check_options`, `lint/{options,readmes,texts,acl}`,
`generators/{manual,examples,sbom} --check`. **Every finding below is
hand-prose rot no gate sees.** That is the wave's second product: a gate
that sees it (§ "The links gate").

## The root causes

1. **The apps/ move re-pointed prose, not links.** 42d6830 fixed path
   spellings in prose but left the four tool READMEs' relative links at
   the pre-move depth — `../` where `../../` is now needed. ~40 broken
   links, all resolving one level short (`apps/apps/…`, `apps/docs/…`).
2. **The one-client wave retired the `-ctl` bins; the MANUAL generator
   never heard.** `scripts/generators/manual.py` (the per-tool tuples,
   the `*-ctl` entries) still renders "Two clients speak it" and a
   `*-ctl.py` example into all four MANUAL intros.
3. **Enumerations rot.** Counts, ranges and inventories written as prose
   drift from the tree they describe (§ ledger rows marked `count`).
4. **TODO.md keeps landed work.** Items closed by later waves still sit
   in the open sections, with their (now-fixed) evidence.

## The findings ledger

### apps/<tool>/README.md (the link sweep)

Every row is a relative link resolving one level short; the fix is
uniform (`../` → `../../` for repo-root targets, `../<tool>/` for
sibling tools). Lines per file:

| file | lines |
|---|---|
| apps/cache/README.md | 11, 184, 185, 281–284, 320, 335, 420, 508, 512, 554 |
| apps/scraper/README.md | 10, 13, 61, 93, 104, 165–166, 218–219, 245, 252–255, 354, 364, 368 |
| apps/inverter/README.md | 9–10, 15, 82, 103, 131, 379, 384 |
| apps/dashboard/README.md | 9, 155, 258, 276, 283 |

The four per-tool `TODO.md` files carry the same defect once each (the
`../nixos/README.md` pointer — cache 193, scraper 241, inverter 216,
dashboard 199).

### apps/<tool>/README.md (the factual fixes)

| file:line | claim | truth | fix |
|---|---|---|---|
| dashboard 156 | `--metrics-max-clients` default `16` | the canon row's `64` (check_options gates flag PRESENCE in READMEs, not values) | re-pin to the canon default |
| inverter 148 | the SIGHUP env layer lists `PROFILE` | the registry's env twin is `MODBUS_PROFILE` (`lib/signals.py` reads it) | re-spell |
| cache 353 | "Both knobs are live-settable" | both key rows are restart-marked secrets (startup-only); only the two scheme knobs are live | narrow the sentence to the scheme knobs |
| cache 530, scraper 384, inverter 398, dashboard 306 | the source-layout blocks open at the pre-move depth (`cache/`, `scraper/`…) and list dead files | the tree is `apps/<tool>/`; `scraper`'s block lists `lib/version.py` (dead — the version lives in `common/runtime/version.py`); the inverter's lists `audit.py` + `paths.py` (dead — `common/runtime/audit.py`, no such file); the dashboard's names a root-level `dashboard.conf` (the sample is `examples/dashboard.conf`) | rebuild the four blocks off the real trees |
| scraper 283 | "the `scraper/metrics.json` → `examples/` dev symlink" | the symlink lives at `apps/scraper/metrics.json` now | re-point |
| scraper 406 | (same block) — covered above | | |

### The MANUALs (generated — fix the generator, regenerate)

| finding | truth |
|---|---|
| all four intros render a `*-ctl.py` example and "Two clients speak it" | the `-ctl` bins retired into the `-cli` (the per-tool TODO records it); `scripts/generators/manual.py`'s four tuples hardcode the dead name (the `'-ctl'` entries) | drop the ctl entry from the tuples + the intro's two-client sentence; regenerate; `--check` re-renders |
| cache MANUAL `dump-interval` row renders "(the cached words + the setting overrides)" | the README's dump contract says the default dump is settings-only, `--dump-with-cache` opts the words in | fix the registry row's help, regenerate (the generator renders the row verbatim) |

### Support READMEs

| file:line | claim | truth | fix |
|---|---|---|---|
| scripts/README.md 216 | `family_drift.py --seeds` generates the seed ledger | the script takes only `--check`; the seeds ledger is a data file the sweep reads | drop the flag spelling |
| scripts/README.md 57 | `list_options.py --nodes` | the script takes `--tool`/`--sort` only | drop the flag spelling |
| nixos/README.md 128, 176 | the scraper + cache option tables name `authKeyFile` | the modules define `modbusAuthKeyFile` | re-spell both rows |
| root README 68, 120 | "one alpine image per Modbus tool" | four images exist; the dashboard is not a Modbus tool but has one | "one alpine image per tool" |

### The family docs

| file:line | claim | truth | fix |
|---|---|---|---|
| SECURITY.md 58 | the module row lists eight bare `common/*.py` paths | all eight moved into the subpackages (`common/runtime/audit.py`, `common/settings/config.py`, `common/serve/connlimit.py`, `common/wire/cred.py`, `common/modbus/protocol.py`, `common/render/human.py`, `common/runtime/logutil.py`, `common/runtime/version.py`); the row also omits `common/wire/wiresec.py` (the RBAC half the doc leans on at 107/176) | re-spell the row |
| SECURITY.md 79 | "four services on one `internal: true` network" | five (`docker/demo/compose.yaml`: fake, cache, scraper, prometheus, dashboard) | fix the count |
| SECURITY.md 60 | "one alpine image per Modbus tool" | four images | same fix as the root README |
| TODO.md 269–275 | the scraper's man page "still ships `unset`" — an OPEN item | fixed: `lib/man.py` reads `set/clear/show/help`; no `set/unset` anywhere | close the item (move to the Done record with a pointer) |
| TODO.md 127–136 | the metrics-caps postures: the scraper "no rows at all", the dashboard "defaults 16", the inverter "no bounds" | landed: the scraper has the trio; the dashboard's row is a thin ref to the canon 64; the bounds ride the canon rows | close the three postures, keep whatever of the item's goal remains |
| TODO.md 108–110 | the scraper's `modbus-unit` row "declares min 0 max 255" | the row is a thin ref now (no bounds of its own) | drop the sentence; the item's one-name goal stays open |
| TODO.md 178–179 | "`knobs_shared()`: 30 names in all four today" | 34 (recomputed in-process) | re-pin or drop the number (the drift doc owns counts) |
| TODO.md 333–345 | cites `common/wire/ctl.py:143-144` | no such file — one client path in `common/wire/cli.py` | re-point (file + function, per the line-number rule) |
| TODO.md 744 | "`lib/static.json`" | no such file — `lib/statics.py` | re-spell |
| TODO.md 797–806 | "13 pages" of man + "docker/compose.yaml" | 8 pages (2 bins × 4 tools); the composes live in `docker/demo|prod/` | fix both |
| TODO.md 445, 451 | "per SECURITY.md rev. 28"; the closed list omits F19 | rev. 31; F19 | re-pin |
| TODO.md passim | dozens of `:line` code cites | DESIGN.md's line-number rule: cite file + function | sweep the load-bearing ones; leave the rest to rot naturally |
| ACL.md 121–126 | "`examples/acl-ip-prefix.json`", "`cache/schema/` for selection" | `extras/examples/acl-ip-prefix.json`; `shared/schema/modbus-cache-filter.schema.json` (the per-tool schema dir died with the shared-homes wave) | re-point both |
| MODBUS.md 435, 477 | the fake's unit knob spelled `--modbus-unit` | the fake's row is `unit` / `--unit` (no env); the doc's own line 361 agrees | fix the fake column + the table row |
| MODBUS.md 400–402 | the profile inventory lists five | six — `sun2000_full.json` missing | add it |
| SBOM.md 65, 90 | `dashboard/static/…` | `apps/dashboard/static/…` | re-point |
| SBOM.md 83 | the docker build snippet (`--build-context scripts=… ../cache`) | broken: `../cache` resolves inside docs/, and the snippet omits the `shared` + `examples` contexts the Dockerfile documents | rebuild the snippet off the Dockerfile header |
| CHANGELOG.md 11–12 + history/CHANGELOG.md 3 | the archive boundary "0.4.0 and older" | the archive starts at 0.4.2 | "0.4.2 and older" in both |
| history/AUDIT.md 1 | the title "rev. 1–28" | the table runs to rev. 31 | fix the range |
| history/AUDIT.md 35 | the alerts pack "since re-homed to `alerts/…`" | `extras/alerts/…` | re-point the reversing pointer |

### The book

| finding | fix |
|---|---|
| book/src/changelog.md includes the root CHANGELOG AND the full archive — a 4,200+ line page | include the root file only; link the archive |
| everything else (the thin include-wrappers, the paths) verified current | — |

## The structural changes

1. **`docs/common/` → `docs/specs/`.** The dir name collides with the
   `common/` package it documents (docs/common/ACL.md vs common/README.md
   in one breath confuses every newcomer). The three specs + their README
   move; the ~10 pointers repoint (root README ×2, DESIGN.md, the tool
   READMEs' fixed links ride the same wave, docs/TODO.md, the lint glob
   prose). The specs themselves are current (one MODBUS unit row aside).
2. **The two align docs join the history home.** `docs/options-align.md`
   and `docs/show-commands-align.md` open with "Status: **landed**" —
   they are the key-alignment waves' contracts and ledgers, not current
   truth. The repo's own two-file rule puts records in `docs/history/`;
   the docs root keeps only current-truth files. They move as-is (the
   records are the records); DESIGN.md's ledger row gains the pointer.
3. **The book slims** (the changelog page, above).
4. **Considered and declined: `extras/manuals/`.** The MANUALs stay
   `apps/<tool>/MANUAL.md` — they are per-tool generated surfaces, the
   sibling of the man pages and the examples (DESIGN.md's grain rule),
   and extras/ is the operator-pack home, not a product-doc home.
   Discoverability goes through the book instead: a "Manuals" page with
   four thin includes rides this wave.

## The links gate

New `scripts/lint/links.py --check`, the wave's first landing — it proves
itself by going red on the tree before the fixes:

- every relative markdown link in the hand-written docs (the READMEs,
  docs/**, the per-tool TODOs — the generated layer excluded) must
  resolve against the tree;
- path-shaped inline-code tokens get the same check where a base dir
  makes them unambiguous;
- it joins the redo's step-1 gate block in DESIGN.md, scripts/README's
  lint table, and the battery as a leg (the check-options pattern: stdlib
  only, no ports, the runpy twin).

`check_options` taught the lesson: presence gates cannot catch value rot,
and no gate at all cannot catch link rot. One gate per rot class.

## The execution order

Per-surface commits, the wave's ripples riding each (the landing
discipline):

1. **scripts/** — `lint/links.py` (+ the battery twin, the README row,
   the DESIGN.md gate block). Red on the tree.
2. **apps/** ×4 — the link sweeps + the factual fixes (one commit per
   tool, the per-tool TODO pointer riding each).
3. **scripts/generators/manual.py** — the ctl tuples + the intro prose;
   the MANUALs regenerate; the cache registry's dump-interval help fix
   rides the same commit (its render follows).
4. **scripts/ + nixos/ + docker/ + root** — the support README fixes
   (flags, option tables, healthcheck, image wording).
5. **docs/** — SECURITY, TODO (the closures + the re-points), ACL,
   MODBUS, SBOM, the CHANGELOG boundaries, history/AUDIT's title +
   pointer.
6. **the structure** — the `docs/specs/` rename (git mv, clean renames),
   the two align docs to `docs/history/`, the book slim + the Manuals
   page; every pointer repoints.
7. **the close** — every gate green (now including the links gate),
   `tests/battery.py`, the CHANGELOG Unreleased entries (Added: the links
   gate + the book page; Changed: the specs rename + the history moves +
   the fixes), this doc's status flips to landed and it moves to
   `docs/history/`.

## Not verified (the honest residue)

- SECURITY.md §9's "all ten suites ALL PASS" — needs a battery run (the
  landing close runs it anyway).
- The book build — mdbook is not installed here; the includes verified by
  inspection only (the standing limitation).
- scraper README's "metrics filter needs a restart" and the SIGHUP
  token re-read — code paths not traced; the links gate does not cover
  semantics.
