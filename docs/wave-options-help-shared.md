# The help-canon wave — the shared options-help texts

Status: DRAFT (Nov 12, 2026) — nothing landed, nothing committed. This file is
the wave's plan; it dies when the wave lands (the record moves to the per-tool
TODOs and the CHANGELOG).

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

1. **One canon text, one home.** The prose that is family-wide identical
   moves to `shared/options-help.json`; the rows reference it and the loader
   substitutes. One edit updates every tool's --help, man page, wire help and
   docs.
2. **Per-tool wording stays inline.** No %-templates in the registries. The
   audit prefix ("the CACHE audit trail"), the Modbus-vs-HTTP semantics, the
   per-tool endpoint differences all stay plain strings in the tool's own
   rows — readable in place, as the registries are today.
3. **The drift gate.** lint_options grows the family-wide pass: a text field
   of a same-named knob must be byte-identical across every registry that
   carries the knob, or the (name, field) rides the lint's named exemption
   list (each exemption with its reason). Accidental drift fails CI.
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
    "control-token": { "setting-help": "…", "help": "…", "hint": "TOKEN" },
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
the row's own fields override the block per field, so a row that shares its
setting-help but worders its long help keeps the `help` inline):

```json
{ "name": "control-token", "flag": "--control-token", "env": "CONTROL_TOKEN",
  "conv": "str", "live": "control/token", "shared": "control-token",
  "secret": true, "hidden": true, "restart": true }
```

Rules:

- Everything the knob SAYS rides the canon: `setting-help`, `help`,
  `value-help`, `hint`, `values`. Everything the knob IS stays per-row:
  `flag`, `env`, `conv`, `default`, `live`/`alias`, `secret`/`hidden`/
  `restart`/`node`, `min`/`max`, `check`, `group`, `no-env`.
- `values` is the one grammar-adjacent canon field: `row_value` matches its
  words at every layer and the ?/TAB pools offer them, so a shared list must
  be byte-identical everywhere (it is today — all 14 cross-tool lists agree);
  a tool narrowing its list drops the ref or overrides the field inline (the
  override replaces the whole list). `hint` is display prose in
  shape-spelling — `row_value` never validates against it.
- A ref names any canon key (the `exit`/`logout` command rows ref `quit`'s
  block) — but a block must be referenced by ≥1 row (the orphan gate).
- Refs land where the text is canon (≥3 tools byte-identical). Two-tool
  identities may stay inline — the lint enforces equality, not the ref.

## The mechanism

`common/settings/options.py` is the one funnel — `load_registry()` reads the
JSON, `option_rows()`/`parse_registry_sections()` build the rows. The
resolution lands there, once for the family:

- load `shared/options-help.json` at the tree root (the
  `common/render/texts.py` `_tree` walk — three `dirname`s up from the
  module file; the loaders import flat, so the walk is spelled locally, not
  imported from the render module);
- a row carrying `shared` folds its missing canon fields (`setting-help`/
  `help`/`value-help`/`hint`/`values`) from the block; a row field wins; an
  unknown key fails LOUD (ValueError naming the row and the key — the
  registries are lint-gated, a typo must never load as silence);
- `option_rows()` then builds the Option rows exactly as today — everything
  downstream (build_parser/--help, the man pages, `show knobs`,
  `help config`, the clis' describe, the Setting vocabulary,
  check_options/gen_man/gen_options/gen_examples) inherits the substitution
  because they all read the loaded rows.

Execution item: enumerate every reader that parses `options.json` RAW
(bypassing `load_registry`) — each must resolve refs too, or be shown to
route through the loaders.

## The gates

- **lint_options.py --check** gains two passes: (a) the resolution pass
  (every `shared` key resolves, every block referenced, no block both
  byte-duplicating another and unreferenced); (b) the family drift pass —
  load all four registries (it already imports the loaders' space), for each
  name in ≥2 registries compare `setting-help`/`help`/`value-help`/`hint`/
  `values` byte for byte, fail on a difference not in the EXEMPT list.
- The EXEMPT list lives in the lint with per-entry reasons (the intentional
  drift named below). A newly drifted knob fails; un-drifting one means
  deleting its exemption.
- family_drift.py gains the sweep type for the human report (the --check
  verdict stays lint_options') — the split may fold at execution if the
  lint's output suffices.
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
- `scripts:` the lint passes + the exemptions + the family_drift sweep.
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

- The whole-row `"shared"` field vs per-field refs (`help-ref`,
  `setting-help-ref`) — whole-row proposed (fewer keys per row, the
  family-wide rows are family-wide in ALL their prose); per-field is the
  fallback if a row needs asymmetric sharing more often than the census
  suggests.
- The gate home: lint_options (the CI gate) + a family_drift sweep (the
  report) — or lint_options alone.
- Whether the ≥3-identical rule ("must ref") is enforced or advisory.
- The gate's reach: the SAYS fields are ruled; widening it to what the knob
  IS — `flag`/`env`/`live`/`alias`/`min`/`max`/`secret`/`hidden`/`restart`
  byte-equality or exemption — is proposed, not ruled (the census says
  `flag` 46/46 and the marks all identical, `min` 14/14 with one `max` drift,
  `live` 36/42 with six structural drifts, eight env-gap knobs; the
  exemptions would carry the intentional ones — `upstream`'s `PROM_URL`, the
  cache's namespaced lives).
