# front-page-split — the READMEs' front page + the manuals as the reference

Status: **landed** (Nov 14 2026) — and the manuals half **dropped the
same day** (the pack `extras/manuals/`, the generator
`dev/generators/manual.py`, the book's Manuals page and every gate hook
retired; the reference went back to the daemon's `--help` and the man
pages). The split itself stands: the READMEs speak the front-page canon
(`dev/gates/readmes.py`), the reference lives elsewhere. This record
keeps the story and the survey as history.

The ruling: **the README is the front page, the manual is the reference.**
Every `apps/<tool>/README.md` had grown into a 300–580-line reference —
flags tables, signals, metrics, alerting, audit prose — while the
generated manuals (`extras/manuals/<daemon>.md`) tabled only the control
wire. Two defects followed: the reference was hand-maintained prose (the
exact rot class the registry waves exist to kill), and a newcomer could
not find the full story in one generated surface. The split gives each
surface one job:

- the **README**: the description, the quick how-to (`## Usage`), the
  security posture (`## Security`), the license (`## License`) — and
  nothing else. The active-development note (the experimental banner)
  rides the description block under the H1.
- the **manual**: everything else — Run it, How it works, Speaking to
  the daemon, the Commands/Knobs/Show-reports tables, Signals, the
  metrics, the alerting, the ACLs, the auth schemes, the persistence,
  the trace format, the audit trail, the testing — rendered as bullets
  and tables, no big paragraphs of text.

## The changes

1. **`dev/generators/manual.py` reworked.** The registry tables gain a
   **`default` column** (`static_default` off the wired rows — the flags
   reference IS the knobs table now; the secrets render `—`, the booleans
   the wire's `on`/`off` words). The intro/kinds prose became bullets and
   a kinds table. A per-tool **REF** data block (in the generator, the
   EXTRA_COMMANDS precedent) carries the old README reference sections —
   items are `('b', text)` bullets, `('t', heads, rows...)` tables,
   `('c', block)` code, `('p', text)` paragraphs. The REF containers are
   **lists** — the first authoring pass used nested tuples and lost an
   hour to a one-`)`-per-section imbalance the parser reported a hundred
   lines late.
2. **A fifth page: `extras/manuals/modbus-replay.md`.** The sidecar has
   no control plane by design, so the page renders the no-control-plane
   shape: no Commands, no Show reports, no Speaking section — the knobs
   table IS the flags table, beside Run it / How it works / The trace
   format / Replay mode / The record feed and the dump tool / Signals /
   Testing. The TOOLS entry carries `cli=None` as the marker (and the
   tool dir spells `modbus-replay` — the first pass keyed it `replay`
   and the registry loader looked at `apps/replay/lib`, a dir that does
   not exist).
3. **`wrap()` breaks only at an even backtick parity.** The old greedy
   wrap could split a code span across lines (`` `file:<path>` `` broken
   mid-span reads as a raw `<` on the continuation line — the
   raw_angle_guard's own defect class). The guard also skips four-space
   code-block lines now (cmark parses no HTML there; the moved snippets
   cite `<inverter-lan-ip>` shapes).
4. **The five READMEs rewritten** to the front-page canon (the manual
   link rides the description). All the moved content landed in the REF
   blocks — nothing the READMEs carried was dropped.
5. **The gates follow the split:**
   - `dev/gates/readmes.py` — the canon is Usage → Security → License,
     present exactly once, in order, **no other H2s**, License closes
     the page; it globs `apps/*/README.md` (the sidecar included — the
     old TOOLS list was four).
   - `check_options`' flag gate reads the generated manual pages
     (`SURFACES`' third element re-pointed; "the manual mentions every
     flag").
   - `links.py` skips the fifth generated page.
   - `family_drift.py`'s README-skeleton note text re-spelled.
   - `lint-gates.py`'s docstring wording ("the five MANUAL pages", the
     front-page canon).
6. **The support surfaces**: `extras/manuals/README.md` and the book's
   Manuals page carry five pages and the split's story.

## The canon question this settles

The request-namespace wave ruled "no defaults live in the help surfaces —
the READMEs are the reference". This wave moves that reference: the
manual's knobs table carries the defaults (from the registry rows, the
one source `check_options` pins), and the front-page READMEs stay
default-light on purpose. The rule's spirit survives — no defaults are
hand-copied anywhere; the rows carry them and the renderers speak.

## The gates

`generators/manual.py --check` current ×5; `readmes --check` green on
five READMEs; `check_options` ALL PASS with the manual flag gate; the
drift doc regenerated current; the lint-gates battery **ALL PASS**
(Nov 14, `dev/battery/battery.py lint-gates`, 1/1).

## Appendix — the five manuals' ladders (the Nov 14 survey, the full-documentation expansion)

The one-ladder rule as shipped — every page's heading chain, the Knobs'
`###` namespaces beside (no H4 ships anywhere: the knob tables carry the
rows, the namespaces are the last heading level):

- **modbus-cache** — The family · Run it · How it works · The control
  plane · Commands · Knobs (general, acl, modbus, system, control,
  control/ops, metrics, metrics/limits, audit, audit/rotate, dump, trace,
  limits, write) · Show reports · Signals · Configuration · Runtime
  control · Access control · Metrics · Tuning · Audit logging · Register
  maps · Diagnostics registers · Persistence · Trace feed · Deployment ·
  The docs map · Source layout · Troubleshooting · Testing
- **modbus-scraper** — The family · Run it · How it works · The control
  plane · Commands · Knobs (modbus, metrics, modbus/caps, system,
  metrics/limits, control, control/ops, metrics/auth, audit, audit/rotate,
  dump) · Show reports · Signals · Configuration · Runtime control ·
  Access control · Metrics · Alerting · Battery · Tuning · Audit logging ·
  Register maps (the register defaults) · Register maps and the metrics
  spec · Deployment · The docs map · Source layout · Troubleshooting ·
  Testing
- **fake-inverter** — The family · Run it · How it works · The control
  plane · Commands · Knobs (general, system, modbus, write, control,
  control/ops, metrics, audit, audit/rotate, dump) · Show reports ·
  Signals · Configuration · Runtime control · Access control · Metrics ·
  Audit logging · Register maps (the profile) · Served registers (the
  default profile) · Deployment · Chaos injection (`--chaos`) · The docs
  map · Source layout · Troubleshooting · Testing
- **dashboard** — The family · Run it · How it works · The control plane ·
  Commands · Knobs (general, system, auth, control, control/ops, metrics,
  audit, audit/rotate, dump) · Show reports · Configuration · Page
  configuration (config.js) · Runtime control · Access control · Behind a
  reverse proxy · Metrics · Audit logging · Register maps · Deployment ·
  The docs map · Source layout · Troubleshooting · Testing
- **modbus-replay** — The family · Run it · How it works · Knobs
  (general) · Signals · Configuration · Runtime control · Access control ·
  Metrics · Audit logging · Register maps · The trace format · Replay
  mode · The record feed and the dump tool · Deployment · The docs map ·
  Source layout · Troubleshooting · Testing

The shared spine every page walks: The family → Run it → How it works →
[The control plane → Commands → Knobs → Show reports] → Signals →
Configuration → Runtime control → Access control → Metrics → Audit
logging → Register maps → Deployment → The docs map → Source layout →
Troubleshooting → Testing, with the tool's own extras slotted between.
Three stories are spliced from one source (`FAMILY_SPLICES` in the
generator — told once, rendered everywhere): the audit-forward chain, the
battery-runner rule, the docs map. The expansion recovered the split's
one real loss (the cache's Diagnostics registers table, mined from the
pre-split README) and added the operator sections the READMEs never had
(The family, Tuning, Deployment, Troubleshooting).

## Not verified (the honest residue)

- The book build — mdbook is not installed here; the fifth include is
  verified by inspection only (the standing limitation).
- The anchors other docs might cite into the old README sections
  (`README.md#alerting` shapes): the links gate cannot see fragments;
  a grep found none at the wave time.

## Postscript — the manuals re-landed, hand-written (Nov 14 2026)

The pack returned by the user's call, a different shape: **hand-written
markdown, no generator and no gate hooks** — six book-style pages (one
per tool app, the ctl/cli covered inside; `pvsuite-cli` gets its own),
the pack README stating the contract (the reference stays the daemon's
`--help` and the generated man page; the manuals are the narrative, the
man page wins a disagreement), and the `extras/README.md` index line.
The generated pack's machinery (`dev/generators/manual.py`, the gate
hooks, the book include) stays retired — the ladders above were that
pack's; the hand-written pages walk one ladder of their own (The family
→ How it works → Installing → Quick start → Configuration → Runtime
control → The control plane → Access control → Metrics → The audit
trail → Tuning → Deployment → Troubleshooting → Testing → The docs
map), and the links gate reads them like any hand-written doc.
