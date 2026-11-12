# The help-canon wave — the shared options-help texts

Status: LANDED (Nov 12, 2026) — the canon file, the loader fold, the four
registry flips (50/44/49/47 rows), the three lint passes (the resolution,
the must-ref, the drift with the 58 named exemptions), the family_drift
canon-coverage subsection and the editor's canon face. The phases fused in
execution: the refs and the aligned wording landed together (the
byte-neutrality of the bare flip proven off-tree against git HEAD — 0
effective-text diffs — before the alignment went on; 29 diffs, each an
alignment-list item). The phase-1/phase-2 commit split died here; the
static proof replaced it. This file dies when the wave lands (the record
moves to the per-tool TODOs and the CHANGELOG).

## The finding

The four registries (cache/scraper/inverter/dashboard `lib/options.json`,
~330 rows, ~700 text fields across `help`, `setting-help`, `value-help`,
`hint` and `values`) carry their wording per tool. The census (a one-shot
script over the four JSON files):

- **~100 strings are byte-identical across ≥2 tools** — 41 `setting-help`,
  40 `help`, 19 `value-help` entries. Eleven `setting-help` texts and nine
  `help` texts are identical across all four tools (the control-token block,
  the audit rotation triple, the forward-format pair, `listen`, `local-time`,
  `restore-on-start`, `dump-interval`, the `ping`/`quit`/`help` command
  helps, ...).
- **42 same-named knobs carry DIFFERENT wording per tool.** Two classes:
  - *Intentional drift* — the knobs genuinely differ: `client-timeout`
    (Modbus vs HTTP), `control-ops-token` (the cache's ops policy is
    `show,flush`, the rest `show`), the dump family (the cache carries the
    cached words), `upstream` (Modbus endpoint vs Prometheus URL), the audit
    node rows (the CACHE/SCR/INV/DSH prefixes), `allow-write` (the cache
    forwards, the fake accepts), ...
  - *Accidental drift* — the same meaning, worded twice: `audit-daily`
    ("rotate the audit **trail**" vs "the audit **log**"), `audit-files`
    ("the rotated audit backups kept" vs "rotated audit backups to keep"),
    `audit-max-mb` (the cache's setting-help lost the "keeping N backups"),
    the scraper's `audit/rotate` node (its setting-help omits the
    UTC-midnight trigger its own `audit-daily` row implements), `modbus-unit`
    ("the Modbus unit id the session speaks" vs "Modbus unit ID"),
    `control-port` (three spellings), `metrics-max-clients` (three spellings),
    the inverter's `knobs` show row ("the dictionary of the registry" vs
    "the dictionary of all knobs"). The scraper's `metrics-acl` long help
    lacks the "checked at accept — a client off the ACL is closed without a
    reply" tail the other three carry — verify the scraper's accept behavior,
    then align or exempt.
- **The shape/vocabulary fields agree far better.** 32 of the 35 same-named
  knobs carrying a `hint` are byte-identical (the three drifts:
  `connect-acl` — the cache spells `any|none|IP,...|file:<path>`, the
  inverter's mirror row says bare `<acl>`; `max-kwp` — `KW` vs `kW`, casing;
  `upstream` — intentional, `URL` vs `HOST:PORT`), and all 14 cross-tool
  `values` lists are byte-identical — but two gaps: the inverter's
  `connect-acl` and the cache's/dashboard's `upstream` carry no `values`
  where a sibling tool does (the inverter's `set connect-acl <TAB>` completes
  nothing).

The accidental class is the wave's reason to exist: nothing polices the
wording today. lint_options pins the layout, check_options pins the surfaces,
family_drift sweeps structure — no gate compares TEXT across the four
registries.

## The ruling

1. **One canon row, one home.** Every family-wide field moves to
   `shared/options-help.json` — the prose and, where the tools agree, the
   wiring (`flag`, `env`, the marks, the bounds); the rows reference the
   block and the loader substitutes. One edit updates every tool's --help,
   man page, wire help and docs.
2. **Per-tool wording stays inline.** No %-templates in the registries. The
   audit prefix ("the CACHE audit trail"), the Modbus-vs-HTTP semantics, the
   per-tool endpoint differences all stay plain strings in the tool's own
   rows — readable in place, as the registries are today.
3. **The drift gate.** lint_options grows the family-wide pass: a gated field
   of a same-named knob must be byte-identical across every registry where
   both rows carry it, or the (name, field) rides the lint's named exemption
   list (each exemption with its reason). Accidental drift fails CI. The
   gated fields run in two tiers: what the knob SAYS (`setting-help`, `help`,
   `value-help`, `hint`, `values`) and what the knob IS (`flag`, `env`,
   `min`, `max`, `secret`, `hidden`, `restart`). `live`, `alias`, `conv` and
   the other per-tool fields stay ungated — the gate never compares them;
   the block may still carry them, and the row overrides where the tool's
   own spelling differs.
4. **Byte-neutral mechanism, deliberate wording.** Phase 1 (the refs) renders
   byte-identical to today everywhere. Phase 2 (the alignment of the
   accidental drift) changes wording ONCE, canon chosen by hand, man pages
   regenerated, the suite pins that carry the old wording updated with it.

## The shape

`shared/options-help.json` — one file at the tree root (the shared/ walk:
same root in the checkout, the installed share/<tool>/ tree, the image's
/pv-suite; shared/README.md gains the paragraph):

```json
{
  "options": {
    "control-token": { "flag": "--control-token", "env": "CONTROL_TOKEN",
                       "setting-help": "…", "help": "…", "hint": "TOKEN" },
    "control-trust-uids": { "setting-help": "…", "help": "…", "hint": "UID,..." },
    "metrics-acl": { "setting-help": "…", "hint": "any|none|IP,...|file:<path>",
                     "values": ["any", "none"],
                     "value-help": { "any": "…", "none": "…" } }
  },
  "show":    { "config": "the effective configuration as a set-grammar script …" },
  "commands": { "ping": "keep-alive: answers pong", "quit": "close the session" }
}
```

The row side — one new optional field, **`"shared": "<key>"`** (whole-row;
the row's own fields override the block per field — the override is the
tool's escape hatch: carry a field inline and it wins, so a row that shares
its setting-help but worders its long help keeps the `help` inline, and a
tool narrows its own `values` or spells its own `hint` the same way):

```json
{ "name": "control-token", "conv": "str", "live": "control/token",
  "shared": "control-token", "secret": true, "hidden": true, "restart": true }
```

(`flag`/`env` ride the block; the tool's own wiring — `conv`, `live` — and
its marks stay inline. The marks could ride the block too; carrying them
inline is the same override rule.)

Rules:

- The block carries every field but the three placement keys — `name`
  (the flat name is the block's key), `only` (the tool-exclusive mark, a
  block is family-wide by definition) and `shared` (the ref itself); the
  fold and the lint gate all three. The gate freezes the subset the family
  must agree on:
  what the knob SAYS (`setting-help`/`help`/`value-help`/`hint`/`values`)
  and what the knob IS (`flag`/`env`/`min`/`max`/`secret`/`hidden`/
  `restart`) — byte-identical or exempt. The rest (`live`/`alias`, `conv`,
  `default`, `no-env`, `check`, `negates`, `group`, `node`) is foldable but
  ungated: the block may carry it, and the row overrides where the tool's
  own spelling differs (the census's six `live` differences are structural,
  not drift — the cache's namespaced walk spellings stay the cache's).
- `values` is the one grammar-adjacent canon field: `row_value` matches its
  words at every layer and the ?/TAB pools offer them, so a shared list must
  be byte-identical everywhere (it is today — all 14 cross-tool lists agree);
  a tool narrowing its list drops the ref or overrides the field inline (the
  override replaces the whole list). `hint` is display prose in
  shape-spelling — `row_value` never validates against it.
- A ref names any canon key (the `exit`/`logout` command rows ref `quit`'s
  block) — but a block must be referenced by ≥1 row (the orphan gate).
- Refs land where the text is canon (≥3 tools byte-identical) — ENFORCED:
  the lint fails a three-tool identity left inline (the exempt list
  applies). Two-tool identities may stay inline — the gate there is
  equality, not the ref.

## The row keys

Every field an `options.json` row may carry, what it does, and its tier.
gated = foldable (the `shared` block) AND gate-frozen byte-identical;
foldable = the block may carry it, the gate never compares it; the key =
`name` itself — never a block field.

| key | carries | tier |
| --- | --- | --- |
| `name` | the registry key — the config/set-grammar key and the wire's FLAT name (dashes included); the replies, the dump keys and the defaults speak it | the key (never a block field) |
| `flag` | the argparse flag (`--client-timeout`); absent on a control-only row | gated |
| `env` | the environment twin (a name, or a list of fallbacks); absent where a `no-env` ruling says so | gated |
| `no-env` | why a flag row carries NO env twin (the F11 findings' prose) | foldable |
| `conv` | the value shape `row_value` converts through: `str`/`int`/`float`/`bool` — the row's "type" | foldable |
| `default` | the resolver's static rung, the ladder's last layer (flag > env > config > default); the argparse default stays unset so the env/config layers read | foldable (the override keeps the tool's own tuning) |
| `live` | the '/'-path CONSOLE spelling of the live setting (`modbus/profile` — the cli spells it as words and translates to the flat name before it sends); absent = startup-only | foldable |
| `alias` | a second console spelling answering the same knob (`audit/forward-format`) | foldable |
| `group` | the optional display bucket the ?/TAB and knob listings file the row under; absent = bare, ungrouped | foldable |
| `secret` | the token mark: `show config` renders `*** SECRET REMOVED ***`, the value never renders back; with `restart` the wire refuses `set`/`clear` outright | gated |
| `hidden` | the pool mark: never lists in ?/TAB; the typed path still answers | gated |
| `restart` | the startup-only mark: a live `set` records pending, the restart note answers, `request reload` applies it | gated |
| `negates` | the boolean knob this row switches off — the `--no-x` store_false form of an `--x` flag | foldable |
| `min`/`max` | the inclusive bounds the live dispatch gates typed values with (a failure rides `RowBounds`) | gated |
| `values` | the documented value words: `row_value` matches case-insensitively and returns the canonical spelling; the ?/TAB pools complete them (the log-level's ride the defaults.json choices wiring) | gated |
| `hint` | the value-shape string (`N`, `s`, `HOST:PORT`) rendered after the words; display prose — `row_value` never validates against it | gated |
| `value-help` | the per-value notes (word → description) the console's word-help answers with | gated |
| `help` | the long help: `--help` and the generated man pages render it | gated |
| `setting-help` | the short description: the wire help, the listings and `show knobs` answer with it | gated |
| `check` | the named shape validator in the tool's CHECKS registry — the wire dispatcher passes it, the startup layers re-run their own parsers | foldable |
| `node` | the hierarchy mark: no flag/env/conv/live — the row names a live-path prefix and carries its `setting-help` (the namespace's word-help) | foldable (structural) |
| `shared` | (proposed) the canon key in `shared/options-help.json`; the row's inline fields win per field | the fold |

The `show`/`commands` section rows carry the smaller vocabulary: `name`,
`setting-help` (the show reports — keyed by the FLAT word, a report answers
`show <word>`, never a set/clear target) and `name`, `help`, `live` (the wire
word), `node` (the namespace's word-help), `group`, `hidden`, `internal`
(the wire answers, the cli never offers or lists it) for the commands.

## The mechanism

`common/settings/options.py` is the one funnel — `load_registry()` reads the
JSON, `option_rows()`/`parse_registry_sections()` build the rows. The
resolution lands there, once for the family:

- load `shared/options-help.json` at the tree root (the
  `common/render/texts.py` `_tree` walk — three `dirname`s up from the
  module file; the loaders import flat, so the walk is spelled locally, not
  imported from the render module);
- a row carrying `shared` folds the block's fields — every field but `name`
  — into itself; a row field wins (the override); an unknown key fails LOUD
  (ValueError naming the row and the key — the registries are lint-gated, a
  typo must never load as silence);
- `option_rows()` then builds the Option rows exactly as today — everything
  downstream (build_parser/--help, the man pages, `show knobs`,
  `help config`, the clis' describe, the Setting vocabulary,
  check_options/gen_man/gen_options/gen_examples) inherits the substitution
  because they all read the loaded rows.

Execution item: enumerate every reader that parses `options.json` RAW
(bypassing `load_registry`) — each must resolve refs too, or be shown to
route through the loaders. CLOSED Nov 12 (the awareness census, all five
registries + the canon file): through the loaders — `check_options`, the
daemons, the clis; the explicit fold — `gen_examples` (the options rows),
`gen_manual` (the show/commands rows), `compare_options`, `list_options`,
`family_drift`'s knobs sweep (the effective rows: the report's secret
census reads the block-carried marks now); raw BY DESIGN — `lint_options`
(the layout linter; it gates the canon blocks AND the canon file's own
layout), the `editor` (the raw-surface editor, the canon display beside),
`set_group`/`set_live` (the surgical field editors — the fields they edit
stay inline by ruling); no registry reads — `gen_sbom`, `release`. The
packaging ships the canon file (all four `package.nix` install lines, the
docker `shared=` context — a packaged tree without it fails loud at the
fold).

## The editor

`scripts/editor.py`'s options face edits the RAW rows (the file, not the
loaded registry), so the canon touches it as one new field plus the
canon-aware display:

- `OptionsEditor.__init__` loads `shared/options-help.json`'s `options`
  section into `self.canon` — an absent file loads `{}` (the editor never
  crashes on the pre-wave tree, the acl face untouched).
- `INLINE` gains `shared` (after `conv`) — the ref renders on the identity
  line of `render_row` and ranks first-line in `row_keys`; `EDITABLE` gains
  `shared` — the form's `*`, the line mode's field gate and the TAB pool
  follow. The `show`/`commands` rows stay out (the canon's `show`/
  `commands` sections are the wave's later face).
- `set_field`'s `shared` branch: the clear (`-`) deletes the ref — the row
  speaks inline again; a set resolves against `self.canon`, an unknown key
  errs naming the file and the available keys; on success the status line
  names the inline twins the block byte-carries (the drop candidates). A
  node row may ref too (the node gate gains `shared` beside
  `setting-help`/`group`).
- The canon-aware display: `effective(row, key)` — a refing row shows the
  block's value with a ` (canon)` mark in the form and the line mode's
  `show_row`, and the index's help column falls through to the block's
  text; the view filter matches the ref key. Editing a canon field lays the
  inline override (the status says so); `d` on a canon-only field says the
  canon speaks. The value-help menu seeds the inline dict from the block
  before an edit — the override replaces the WHOLE dict, and an edit that
  silently drops the block's other pairs is a bug.
- The `p` rider (lint_options' `proposals()`, the editor's draft walk): a
  row whose SAYS fields byte-match a canon block gets the `shared: <key>`
  proposal — Phase 1's row flips turn mechanical, one Enter per row.
- Untouched: `render_row` (the INLINE rank covers the placement), the lint
  report (the new passes ride lint_options), the save machinery (`shared`
  is just a field — the stamp guard, the parse-back, the splice), the
  completer (EDITABLE-derived).

## The gates

- **lint_options.py --check** gains three passes: (a) the resolution pass
  (every `shared` key resolves, every block referenced, no block both
  byte-duplicating another and unreferenced); (b) the must-ref pass — where
  ≥3 tools carry byte-identical text inline with no canon ref, the lint
  fails (the exempt list applies; two-tool identities may stay inline);
  (c) the family drift pass —
  load all four registries (it already imports the loaders' space), for each
  name in ≥2 registries compare, byte for byte, the SAYS tier
  (`setting-help`/`help`/`value-help`/`hint`/`values`) and the IS tier
  (`flag`/`env`/`min`/`max`/`secret`/`hidden`/`restart`), failing on a
  difference not in the EXEMPT list. The pass compares the EFFECTIVE rows —
  the fold applied, the row overrides won — so block-carried fields are equal
  among refing rows by construction, and an inline override must still match
  the siblings or ride an exemption. A field one row does not carry does not
  drift (the env gaps are the tools' own no-env rulings — the gate compares
  where both rows carry the field). The gate's census baseline: `flag` 46/46,
  `min` 14/14, `max` 13/14 (the `modbus-merge-gap` exemption or alignment),
  the marks 6/6, 7/7, 8/8, `env` 44/45 (the `upstream` `PROM_URL`
  exemption); the SAYS tier's numbers live in The finding.
- The EXEMPT list lives in the lint with per-entry reasons (the intentional
  drift named below). A newly drifted knob fails; un-drifting one means
  deleting its exemption.
- family_drift.py gains the canon-coverage sweep type — the human report
  shows, per gated field, the shared/inline/exempt split across the family
  (the --check verdict stays lint_options').
- Suites: Phase 1 must pass the ten suites UNCHANGED (their pinned help
  strings render byte-identical). Phase 2 updates the pins it deliberately
  rewords.

## The exemptions (intentional drift, stays local)

`audit`/`no-audit-log` (the CACHE/SCR/INV/DSH prefixes), `client-timeout`,
`max-clients`, `max-conn-per-ip` (Modbus vs HTTP semantics), `control`,
`control/ops`, `control-ops-token` (the cache's `show,flush` policy),
`control-port` (until aligned — cache spells the TCP target), `dump`,
`dump-path`, `dump-key`, `dump-interval` (the cache's cached words),
`upstream` (Prometheus URL on the dashboard), `metrics`, `metrics-server`,
`metrics-token`, `auth-token` (the endpoints differ), `log-access`
(connects/disconnects vs HTTP requests), `allow-write`, `write`,
`connect-acl` (the fake's mirror wording — the prose stays local; its hint
and `values` align, see below), `max-kwp` (cap vs simulation — the prose
stays local; the hint aligns to `kW`),
`modbus`, `modbus-auth`, `modbus-timeout`, `modbus-interval`,
`modbus-merge-gap`, `modbus-profile` (cache the map, scraper the sources),
`system` (the socket's purpose), `metrics-listen` (the cache carries the
reload note), `metrics/limits`, `metrics-max-clients` (until aligned).

## The alignment list (Phase 2 canon choices, applied family-wide)

`audit-daily` ("the audit trail" — trail is the noun the rotation rows
speak), `audit-files` ("rotated audit backups to keep"), `audit-max-mb`
setting-help (restore "keeping N backups"), the scraper's `audit/rotate`
node (add the UTC-midnight trigger), `modbus-unit` ("the Modbus unit id the
session speaks"), `control-port` (one spelling for the four), `metrics-max-clients`
("maximum concurrent /metrics clients; extras get an immediate 503"),
the inverter's `knobs` show row, the scraper's `metrics-acl` accept tail
(verify the behavior first), the `client-timeout` `0` value-help triplet
(one "never" wording), the `connect-acl` hint and `values` (the inverter's
mirror row takes the cache's `any|none|IP,...|file:<path>` and its
`any`/`none` words — today `set connect-acl <TAB>` completes nothing there),
the `max-kwp` hint casing (`kW` — the scraper spells `KW`), the `upstream`
`values` gap (the scraper's list to cache+dashboard, or exempt — decide at
execution).

## The commits

- `shared:` the canon file (+ the README paragraph; package.nix install
  lines gain the file — enumerate at execution; the docker shared= context
  carries the dir already).
- `common:` the loader resolution + the loud miss.
- `cache:` `scraper:` `inverter:` `dashboard:` the row flips (Phase 1), one
  commit per tool; the alignment edits ride the tool's Phase 2 commit.
- `scripts:` the lint passes + the exemptions + the family_drift sweep +
  the editor's canon face (the shared field, the (canon) display, the `p`
  rider).
- `docs:` the man pages regenerated, the CHANGELOG Unreleased entries, the
  per-tool TODO records, docs/TODO.md's item removed when closed,
  docs/family-drift.md's regenerated table.

## Verification

`python3 scripts/check_options.py`; `python3 scripts/lint_options.py --check`;
the ten suites via scripts/battery.sh (Phase 1: pins untouched; Phase 2: pins
updated with the canon); `python3 scripts/gen_man.py` + `mandoc -Tlint` clean;
`python3 scripts/gen_examples.py --check`; `python3 scripts/family_drift.py`;
`nix flake check`.

## Open decisions

- The whole-row `"shared"` field vs per-field refs — RULED Nov 12: whole-row,
  the local row overrides per field.
- The gate's reach — RULED Nov 12: the gated set is what the knob SAYS
  (`setting-help`/`help`/`value-help`/`hint`/`values`) plus what the knob IS
  (`flag`/`env`/`min`/`max`/`secret`/`hidden`/`restart`); the block carries
  every field but `name`, and `live`/`alias`/`conv`/`default`/`no-env`/
  `check`/`negates`/`group`/`node` are foldable but ungated — the gate never
  compares them, the row overrides where the tool's own spelling differs.
- The gate home — RULED Nov 12: lint_options owns the --check verdict;
  family_drift gains the canon-coverage sweep type for the report.
- The ≥3-identical rule — RULED Nov 12: enforced (the must-ref pass; the
  exempt list applies).

## The execution notes

- `conv` rides the canon too (the user's Nov 12 close-out call): 37 of the
  41 option blocks carry it — the foldable-but-ungated tier in action, the
  gate never compares it, the byte-equal inline conv folds away. The env
  faces that read the raw JSON's conv (gen_examples' sample values) resolve
  the refs through the loader's own fold — the raw-reader enumeration grew
  by one.
- The upstream `values` gap resolved to EXEMPT: the scraper's `[":5502"]`
  list is its own (a port-shorthand the other tools' semantics do not
  share), the cache/dashboard rows carry no `values` (a gap does not
  drift).
- `control-port`: the three TCP tools' setting-help aligned to the cache's
  spelling (the block); the inverter's unix-only wording stays (exempt),
  and the helps carry each tool's ctl name (exempt).
- `dump-key`: the scraper's missing semicolon was a typo — the help
  aligned to the inverter/dashboard text and rides the block; the cache's
  "the words and the settings" phrasing stays (its dump carries the cached
  words).
- The two-tool alignments stay inline (no block): `modbus-unit` (the
  scraper adopts the cache's spelling), `max-kwp`'s `kW` hint, the
  inverter's `connect-acl` hint + `values` (the TAB pool completes now).
- The audit-max-mb canon restores "keeping N backups" family-wide — the
  cache's lost tail was the drift the wave's census caught.
- The unification pass (the user's Nov 12 ruling: the block carries every
  row key but name/only/shared) hoisted the carried-unanimous fields — 27
  `default`s and the `audit-forward-format` `alias` into the options
  blocks, `internal`/`hidden` into four command dict blocks (help, ping,
  request-dump, request-restore) — the rows keep the per-tool wiring
  (`live` stays inline: the raw namespace lints read it) and the byte-
  effective rows proved unchanged before the write. `gen_manual`'s raw
  commands read resolves the refs now, which fixed the pages' empty
  command-description cells (the block-carried helps the raw read lost).
