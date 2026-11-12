# TODO (one file to rule them all)

Every **open** item lives here — grouped by theme. The tool-owned
themes bucket their items under `###` headings (`SCRAPER`,
`INVERTER`, `DASHBOARD`, `COMMON` — no tag where the heading carries
it), the spanning items keep the `[cache]` `[scraper]` `[inverter]`
`[dashboard]` `[common]` `[docker]` tags under `CROSS-TOOL` (untagged
means the whole family), and every other theme stays tag-per-item.
The per-subproject `TODO.md` files keep only the **Done/history**
records for their tool —
[cache](../cache/TODO.md), [scraper](../scraper/TODO.md),
[inverter](../inverter/TODO.md), [dashboard](../dashboard/TODO.md).
The **one-product sweep** (the consistency items — the same knobs, the
same words, the same env layer everywhere) rides as its own section
below; its verified-aligned ledger lives in
[history/family-unify.md](history/family-unify.md).

## The control plane (the grammar follow-through)

- **row the fake's write-emulation words** `[inverter]` — `register`,
  `coil`, `discrete` are set-only pseudo-settings the wire answers (the
  write-overlay emulation, `set register <addr>=<val>`) with no registry
  rows: the cli's special-case pin died with the internal-mark wave (the
  words stopped completing/describing — the wire, the suites and the
  overlay are untouched), and the registry should either gain their
  hidden command rows or the "set/show the registers" redesign (the
  product item below) subsumes them.
- **check the values against the hints** `[common]` `[cache]`
  `[scraper]` `[inverter]` `[dashboard]` — the value-shape hint's
  convention is the FULL shape (the free-form parts and the vocabulary
  words — `modbus/selection`'s `<file>|all|none`), but the rows drift:
  `modbus/profile`'s hint is `<file>` while its values carry `default`
  (the word missing from the hint), and the bool rows carry no hint at
  all while `modbus/auth` spells `suite|none` — walk every row in the
  four registries, align the hints (the missing value words in, the
  stale words out) and decide the bool rule once (a hint or not).

## The one-product sweep (the consistency follow-through)

The working assumption: **the family is one product** — a user moving
between the four tools (cache, scraper, inverter, dashboard) finds the
same knobs, the same words, the same refusals and the same env layer.
This section is the one-product sweep: what still breaks that promise,
with the per-tool truth and the unified outcome stated per item — a
wave that picks an item up moves it out (the landing, the Done
highlights below); the landed consistency legs live in
[family-drift.md](family-drift.md) (this sweep adds what its
name-intersection pass cannot see: the near-miss knob names, the
tool-absent rows, the live-run refusal texts).

Frame note from the re-verification (swept 2026-11-10, re-verified
2026-11-11): since the first sweep the wire speaks the **flat registry
names** (each row's `name` — `interval`, `max-conn-per-ip`) and the
rows' `live`/`alias` paths became **console spellings** the cli and
the ctls translate before sending (`common/wire/cli.py:35`); the knob
defaults moved into the registry rows. The items below spell the
console form where they name a user action, and the flat name where
they name the wire.

### The short list — the user gets silently bitten

1. **The scraper's live `system/listen` has no F13 floor** — the
   dashboard refuses the move beyond loopback (F21 template,
   `dashboard/lib/control.py:135`) and the cache guards its metrics
   endpoint (`cache/lib/control.py:176`, the live branch `:315-321`),
   but the scraper's restart preamble probe-binds and records the
   pending listen without ever asking `is_loopback_host` (the word
   does not appear in the file; the branch is
   `scraper/lib/control.py:175-182`), and the restart-state fold lands
   *after* `resolve_config()`'s startup F13 check
   (`scraper/bin/modbus-scraper.py:92` resolve — the check sits inside,
   `scraper/lib/config.py:104-106` — `:100-101` fold): a tokenless
   scraper can `set system listen 0.0.0.0:9350`, `request reload`, and
   serve beyond loopback with no token. The preamble's second key
   `'metrics-listen'` is dead — no row carries that flat name (the
   alias `metrics/listen` is a console spelling that translates to
   `listen`). Outcome: the F21 move-refusal template, verbatim, in the
   scraper's restart preamble.
2. **`AUTH_TOKEN` means two different secrets** — the /metrics bearer
   on the scraper (`scraper/lib/options.json:117`, flag `--auth-token`,
   console `metrics/auth/token`) and the page bearer on the dashboard
   (`dashboard/lib/options.json:38`, console `auth/token`), while the
   same /metrics bearer is `metrics-token`/`METRICS_TOKEN` on the
   cache (`cache/lib/options.json:165`), the inverter
   (`inverter/lib/options.json:216`) and the dashboard itself
   (`dashboard/lib/options.json:89`). The shipped stacks carry both
   meanings of the one variable: the scraper's `AUTH_TOKEN:
   file:/config/metrics.token` against the dashboard's
   `file:/config/page.token` (`docker/demo/compose.yaml:126,177`,
   `docker/prod/compose.yaml:98,141`). The modbus-auth rename dissolved
   only the third variable (`AUTH` is gone everywhere); this split
   stands. Migrating a token between tools changes the variable *and*
   the meaning. Outcome: the scraper's /metrics bearer renames to
   `metrics-token`/`METRICS_TOKEN`/`metrics/token`; `auth-token` keeps
   the page-serving meaning (breaking: the alias map carries
   `auth-token` one release).

### The knob plane — the same knob everywhere

- **the unit id, two spellings** `[scraper]` `[inverter]`
  — the cache joined the scraper's spelling (the `modbus-unit`/
  `--modbus-unit`/`MODBUS_UNIT` row, `cache/lib/options.json:11`),
  the inverter stays `unit` with no env twin and no live at all
  (`inverter/lib/options.json:50` — startup-only by absence). The
  range half landed: one shared tree gates every tool with a unit knob
  (`shared/suite/protocol.json` — 1..247, `unit_in_range`; start and
  reload validate, the Modbus servers refuse out-of-range ids in-band,
  `check_options.py` gates the check). What remains: the scraper's row
  still declares `min: 0, max: 255` and only its live set gates on it
  (`scraper/lib/control.py:306`) while start refuses `<1`. Outcome:
  one name, one flag, one env, live everywhere, the row bounds = the
  shared tree's range (the NixOS `unitId`/`modbusUnit` renames follow).
- **the listener caps, the console schemes** `[all]` — the flat names
  unified where the surfaces meet: the cache's metrics trio and the
  scraper's /metrics trio speak the same
  `metrics-max-clients`/`metrics-client-timeout`/`metrics-max-conn-per-ip`
  flat names (the cache is the master; the scraper's old bare spellings
  retired). The console paths still split: `limits/*` on the cache's
  Modbus listener vs `metrics/limits/*` on both metrics surfaces
  (`cache/lib/options.json:102-114`, `scraper:75-92`), and the inverter
  and dashboard keep the bare scheme (`inverter:149-158`,
  `dashboard:21-30`); the cache's own metrics leaf is
  `metrics/limits/timeout` while its socket leaf is
  `limits/client-timeout` (one family, two leaves, `:186` vs `:107`).
  Outcome: `<surface>/limits/{max-clients,client-timeout,max-conn-per-ip}`; the
  leaf is `client-timeout` everywhere.
- **the /metrics caps, four postures** `[scraper]` `[inverter]`
  `[dashboard]` — the cache has the full trio (defaults 64/5.0/0,
  `METRICS_*` envs, bounds, live, `cache/lib/options.json:179-195`);
  the scraper has **no rows at all** (its base trio *is* the /metrics
  trio); the inverter has the rows but no live, no env, no bounds
  (`env: null` + the F11 note, `inverter/lib/options.json:227-240`);
  the dashboard has envs but **defaults `metrics-max-clients` 16** vs
  64 (`dashboard/lib/options.json:102`) and no live/bounds. Outcome:
  the cache's row shape family-wide, default vector {64, 0, 5.0}, the
  scraper's always-on endpoint documented as the exception.
- **`metrics/listen` means two sockets** `[cache]` `[scraper]` — the
  cache's `metrics-listen` is the /metrics bind
  (`cache/lib/options.json:159`); the scraper's `listen` row carries
  `"alias": "metrics/listen"` (`scraper/lib/options.json:57`), so the
  console's `set metrics listen <addr>` translates to the flat `listen`
  and moves the *main* HTTP listen there. The worst
  same-words-different-socket in the family, now one translation step
  away. Outcome: the alias dies; `metrics/listen` is the /metrics bind
  only.
- **the access-audit trio, three names, one job** `[all]` —
  `audit-requests` (cache, `cache/lib/options.json:241`, an interval
  knob), `log-access` (scraper/dashboard, on/off), `log-queries`
  (dashboard only, no startup env, `dashboard/lib/options.json:153`);
  the inverter has none. The cache row's own `min: 1` contradicts its
  help's `0 = off` (`:230-233` vs the resolver's
  `must be >= 0 (0 = off)`, `cache/lib/config.py:330`; the live path
  maps `'0'` to off before the row gate ever sees it,
  `cache/lib/control.py:369`). Outcome: decide the family shape (an
  interval knob beats on/off), spell it once, give the inverter its
  row, fix the min/help.
- **`upstream`, one name, three layers** `[cache]` `[scraper]`
  `[dashboard]` — the env is `UPSTREAM` on the two Modbus tools and
  `PROM_URL` on the dashboard (`cache/lib/options.json:7`,
  `scraper:4`, `dashboard:7`); the cache marks it `restart: true`, the
  scraper says nothing; the dashboard has no live. Outcome: the env
  does not fork (`PROM_URL` at most a back-compat alias); the restart
  mark decided once.
- **the poll interval, two namespaces** `[cache]` `[scraper]` — same
  conv, same default 10.0, console `modbus/interval` vs
  `metrics/interval` (`cache/lib/options.json:43`,
  `scraper:161`). Outcome: `modbus/interval` in both (the knob polls
  the device on both tools).
- **near-miss console paths** `[scraper]` `[inverter]` — `max-kwp`
  consoles as `modbus/caps/max-pv` on the scraper and bare `max-kwp` on
  the inverter (hint `KW` vs `kW`, `scraper/lib/options.json:57` vs
  `inverter:57`); `connect-acl` consoles as `acl/connect` on the cache
  and bare on the inverter, whose help also omits the `file:<path>`
  form its sibling supports (`cache/lib/options.json:80` vs
  `inverter:138`). Outcome: the node-ful
  spelling wins each time.
- **the knob sweep's blind spots** `[common]` — `family_drift.py`
  still intersects by literal row name (`knobs_shared()`: **30** names
  present in all four today), so every near-miss pair above
  (`unit`/`modbus-unit`, `metrics-token`/`auth-token`) is never
  diffed; the tool-specific remainder names the absent rows but diffs
  nothing. The defaults half landed: the rows carry
  `default`/`min`/`max`/`live`, the sweep reads them, and
  `check_options.py`'s row quartet gates every default (see the
  gates). Outcome: a concept key (an explicit equivalence map) per
  row, so the near-misses enter the table.

### The word plane — the same words everywhere

- **eleven hardcoded copies of texts.json leaves** `[all]` —
  `common/wire/control.py:591` (the set-path restart note beside the
  clear path's `T()`), `:637` (reload failed, beside the leaf's use at
  `:1224`), the cache's whole dump/restore error set
  (`cache/lib/control.py:745-789`), the cache bin's sealed/skipped
  suffixes (`cache/bin/modbus-cache.py:88,218,327`), the scraper's
  ops-token listen line (`scraper/bin/modbus-scraper.py:117`), its
  hand-rolled `must be on or off` (`scraper/lib/control.py:283`) with
  a second copy on the fake (`inverter/lib/control.py:334`), the
  unknown-setting lines (`scraper/lib/control.py:289`,
  `cache/lib/control.py:437` — the leaf exists; the fake uses it), the
  fake's config head + comment (`inverter/lib/control.py:126-128`),
  and `cannot bind` spelled by hand in the four bins
  (`cache/bin/modbus-cache.py:369`, `scraper/bin/modbus-scraper.py:133`
  and `:267`, `inverter/bin/modbus-fake-inverter.py:395`,
  `dashboard/bin/dashboard.py:348`) plus two live refusals
  (`dashboard/lib/control.py:189`, `inverter/lib/control.py:323`).
  `lint_texts.py` cannot see a literal that equals a leaf. Outcome:
  the leaves win; the lint learns the literal-equals-leaf check.
- **the cache's dump/restore replies are a fourth dialect** —
  `ok dumped %d word(s), %d setting(s) to ...` vs the family's
  `ok dumped %d setting(s) to ...` (`cache/lib/control.py:767,788`;
  the family leaves render in the base, `common/wire/control.py:1261`,
  `:1277`). The override is deliberate and documented (the words ride
  along beside the settings, `cache/lib/control.py:736`). Keep the
  cache's extra count if the payload demands it, but reuse the family
  leaves for every error and suffix.
- **the fake's dialects** `[inverter]` — unknown tails answer the
  whole path unquoted where the family answers the first word quoted
  (`inverter/lib/control.py:544-552` vs
  `common/wire/control.py:665-682`); `inspect` folds `uptime` into
  `now` (`inverter/lib/control.py:611`) and drops the app name from
  `version` (`:602`, the family prefixes it, `cache/lib/control.py:556`);
  its `command_help` omits `inspect` (`:478`). The parse/refusal legs
  landed (the fake parses through `num`/`numi`/`on_off`). Documented
  as F11 colour — keep only what the docstring rules, align the rest.
- **one health word, two spellings** `[scraper]` `[dashboard]` — the
  `set` reply summary spells the upstream health `poll=ok|down` on the
  cache and scraper but `upstream_ok=` on the dashboard
  (`cache/lib/control.py:539`, `scraper:410`, `dashboard:279`).
  Outcome: one key.
- **the help one-liners** `[all]` — `help show/set/clear` differ (the
  cache names reports in the bracket, `cache/lib/options.json:321-324`,
  the other three show example knobs); `show knobs` is "the dictionary
  of all knobs" vs the inverter's "of the registry" (`:284` vs
  `inverter:313`); `show config` is "the effective configuration" vs
  the inverter's "the startup options"; the metrics-acl-table help is
  long on cache/scraper, short on inverter/dashboard; the inverter's
  `connect-acl` help says "the cache's connect-acl, mirrored" — a
  cross-tool reference in a user row (`inverter/lib/options.json:139`,
  it reached `inverter/lib/man.py:117` and `inverter/MANUAL.md:119`).
  Outcome: one line per verb, per-tool brackets only.
- **the knob descriptions, four voices** `[all]` — `control-port`
  alone has three dialects ("control server target..." /
  "JSON-lines control server target...", `cache/lib/options.json:119`
  vs `scraper:83`); `max-clients` describes a Modbus socket on two
  tools and an HTTP one on two (correct per tool, but the sentence
  templates should match); the audit sink rows say "audit trail" while
  the rotate rows say "audit log" (`cache/lib/options.json:199,219`,
  the same split on scraper/inverter), and the cache's setting-helps
  keep their own shapes (`:199`, `:225` where the other three agree);
  `metrics-token` carries two Bearer phrasings (`cache:167` vs
  `dashboard:91`); the scraper's man page has no `--metrics-token` to
  match the cache's cross-reference (its bearer is `--auth-token`,
  `scraper/lib/man.py:41`; the cache's help says "the same scheme the
  scraper speaks", `cache/lib/options.json:169`). Outcome: one
  template per concept, the surface noun as the only variable.
- **the restart-marker vocabularies** `[all]` — the same fact ships
  as `note restart required (startup-only knob)` (the wire leaf,
  `shared/suite/texts.json:82` — plus the set-path hand copy), `, restart` /
  `startup-only — pass it by flag/env/config (set/clear refuse)`
  (show knobs + help config via `control_command()`,
  `common/settings/options.py:390-408`),
  `*(restart)*` / `startup-only (secret)` (MANUAL.md,
  `scripts/gen_manual.py:143-146`), `restart: true` + the wire phrase
  (only the cache's man carries the trio now, `cache/lib/man.py:98-107`),
  and "restart to apply" (inverter/README.md:204). Outcome: a
  two-phrase lexicon in `shared/suite/texts.json`, every surface renders it,
  the marker rule ("the % changed exception") stays.
- **the scraper's man page still ships `unset`** `[scraper]` —
  `scraper/lib/man.py:70` reads `set/unset/show/help` and the
  generated page carries it (`scraper/man/modbus-scraper.1:254`); the
  other three say `set/clear`. The `--check` gate passes because the
  *source* is stale — it catches stale output, not stale prose. (The
  cli pages' `% changed` / `[confirm]` divergence stays open too — a
  docs nicety, not a lie.) Outcome: the source line, regenerate.
- **the cache's ops-token refusal renders the secret** `[cache]` —
  the validate `fail()` prints the value it looked up
  (`cache/lib/config.py:286-288`), and for `control-ops-token` that
  value *is* the token (`:432`): `--control-ops-token sekret` answers
  `invalid control-ops-token = 'sekret': ...` (verified live). The
  common `check_control_tokens()` the scraper and dashboard use
  renders no value. Outcome: the cache's `fail()` hides secret keys
  (the family's secret posture).
- **the rc discipline splits on the unsafe-config refusals** —
  the F13 start refusal exits 2 on cache/dashboard
  (`cache/bin/modbus-cache.py:156-160`,
  `dashboard/bin/dashboard.py:313-321`) and 1 on scraper/fake
  (`scraper/lib/config.py:104-105`, `inverter/bin/modbus-fake-inverter.py:277-280`);
  TCP-control-without-token exits 2 on the cache (`:149-153`) and 1 on
  scraper (the config validator, `:107-110`) and dashboard (its check
  moved into the validator too, `dashboard/lib/config.py:152-153`;
  verified live). Outcome: one rc for "the config is unsafe" — the
  evidence leans 2 (CLI-config mistakes), the fake's rc 1 stays its F11
  posture; also pick one *presentation* (the cache/dashboard log an
  ERROR line, the scraper/dashboard config paths print a bare
  `SystemExit(str)`).
- **`cannot serve on` leftovers** `[common]` — the code says
  `cannot bind` family-wide; two stale mentions survive: the dead
  seed in `docs/family-drift-seeds.json` and the
  `common/modbus/server.py:52` docstring ("the clean 'cannot serve'
  failure"). Outcome: the seed retires, the docstring says
  `cannot bind`.
- **the live F13 floor, three spellings** `[cache]` `[dashboard]`
  `[inverter]` — the cache prefixes "the metrics endpoint serves
  register values: ", the dashboard "the metrics endpoint serves the
  request counters: ", the fake sends the bare sentence
  (`cache/lib/control.py:318`, `dashboard/lib/control.py:176`,
  `inverter/lib/control.py:313`); the drift doc records the
  divergence. Outcome: the bare sentence, one `T()` leaf.
- **the metrics toggle's three-surface label** `[all]` — the knob/wire
  name is `metrics-server` (`cache/lib/options.json:154`,
  `dashboard:78`, `inverter:203`), the console spelling is
  `set metrics enable` (the live path `metrics/enable`), and the help
  prose says "the live `set metrics enable` toggle". The flat-wire
  wave made the name/console split principled; the near-miss — the
  live path disagreeing with the name — is untouched. Outcome: one
  label per surface, name and live path agreeing.
- **the mislabeled refusals' residue** — the label param landed, but
  the cache still mislabels `--metrics-listen`: `validate_config`
  calls `parse_listen` unlabeled (`cache/lib/config.py:316`) and fires
  before the bin's labeled call (`cache/bin/modbus-cache.py:155`), so
  `--metrics-listen nope` answers `--listen must be HOST:PORT`
  (verified live). And the control-port range check landed on the
  cache only: scraper/dashboard pass start validation and die later in
  the control thread with `OverflowError: bind()` (their validators
  guard only the token sentence, `scraper/lib/config.py:107-110`,
  `dashboard/lib/config.py:151-155`; verified live). Outcome: the
  labeled call and the range validator everywhere.
- **the startup validation, two shapes** — cache/scraper/dashboard
  say `invalid <key> = <val>: <rule>` (`cache/lib/config.py:286`,
  `scraper:59`, `dashboard:147`); the fake says `--flag <rule>, got %r`
  and collects every problem before exiting
  (`inverter/bin/modbus-fake-inverter.py:68-85,230-233`).
  Both legitimate — pick the family shape (the `invalid k = v` form
  reads better in logs) or document the fake's as F11.
- **the lenient-start policy is unstated** — a bad env/config value
  logs one ERROR line and defaults (rc 0, the Resolver's except,
  `common/settings/config.py:112-124`) while the same text over `set`
  refuses; a user's config typo starts a daemon on defaults. Outcome:
  state the policy in the READMEs/man SECURITY or AUDIT (and keep
  it), or fail fast.
- **the ctl exits 0 on a refused command** — a `fail` reply prints
  `% error: ...` and exits 0 (`common/wire/ctl.py:143-144`; the only
  nonzero exits are mac/auth/transport), pinned by the suite
  (`tests/cache-regtest.py:2351`); the ctl man's EXIT STATUS even
  promises "every command answered ok" (`common/render/manpage.py:46`).
  Outcome: decide (rc 1 when any reply is `fail`), reword EXIT STATUS.
- **the 401 bodies, three spellings** — `unauthorized\n` (scraper
  page, `scraper/lib/server.py:35`), `401 unauthorized\n` (common
  metrics, `common/serve/metrics_server.py:130`), the dashboard's long
  cookie-bootstrap sentence (`dashboard/bin/dashboard.py:58` — fine,
  it teaches the `?auth=` hop). Outcome: the common metrics pair wins
  on plain surfaces.
- **the spellings rule is unwritten, in its new shape** — the old
  flags-vs-live-paths rule died with the flat wire: the wire's grammar
  takes ONLY the flat registry name (the daemon's match map,
  `common/settings/options.py:749-765`), the console/cli/config files
  accept the rows' `live`/`alias` spellings beside it and translate
  (`common/wire/cli.py:35-54`), while startup refusals speak flags
  (`set --metrics-token (or file:<path>)`, `scraper/lib/config.py:104`)
  beside knob words (`audit-forward must be ...`,
  `common/runtime/audit.py:104`). No doc states the rule. Outcome:
  write it down (the wire speaks flat names, the console translates,
  startup speaks flags) next to the texts.
- **the control listener's three bind texts** — start bind failure
  is non-fatal by design (`control server cannot bind ... (use
  --control-port 0 to disable it)`, `shared/suite/texts.json:104`, rendered
  `common/wire/control.py:212`), the live rebind says
  `cannot bind control-port ...` (`shared/suite/texts.json:108`, the flat
  spelling now), the Modbus surfaces say `cannot bind`
  (`shared/suite/texts.json:70` + the hand copies above). Outcome: keep the
  non-fatal behaviour, document the three-tier story once.

### The env plane — the same env layer everywhere

- **the dashboard's man still sells `PORT`/`BIND`** `[dashboard]` —
  `dashboard/lib/man.py:136-138` (baked into the generated page,
  `dashboard/man/dashboard.1:314`) while the README and the config
  docstring were fixed — the last stale env claim of the first sweep.
  Outcome: the man prose follows the resolvers, regenerate.
- **"empty = unset" means empty string, not blank** — the shared
  Resolver tests `raw == ''` (`common/settings/config.py:112-119`)
  while `resolve_target`/`CONFIG` strip (`:18-22`,
  `common/runtime/daemon.py:48-51`): `LISTEN=' '` is *set* and fails
  validation. Uniform family-wide. Outcome: a docstring precision fix
  (or strip everywhere — pick one).

### The gates that keep it

- a **concept key** for the knob sweep (near-miss names, tool-absent
  rows) — without it every knob item above re-drifts silently.
  LANDED half: the defaults gate is the **row quartet**
  (`check_options.py:134-173`) — every non-secret flag knob's row
  carries its default or a named `NO_ROW_DEFAULT` reason, no secret
  row carries one, every default parses as the row's conv, the
  ops-verbs row's default pins the `default_ops_verbs` derivation —
  flanked by the unit-range and audit-bounds rows, and the sweep's
  field table reads the rows (`default`/`min`/`max`/`live`).
- the env examples are **GENERATED from the registries**
  (`scripts/gen_examples.py --check`): the full registry env-twin set per
  tool (50/39/34/38), grouped by the knob's namespace node, the image's
  own CMD/ENV values as the sample lines with the pin notes (the
  compose's environment pins marked per knob), the secrets' lines
  empty, the prometheus example's `PROM_*` names cross-checked against
  the entrypoint — the gate that replaced the "check_options (or
  family_drift) diffs the registry env twins against
  `docker/env/*.env.example`" open item;
- `lint_texts.py` flags a **literal that equals a leaf** after
  `%`-normalisation — still missing.
- the breaking renames (the scraper's `auth-token` → `metrics-token`,
  the unit unification) ship with the **alias map** (the rows' `alias`
  field) + the **migration note** (the CHANGELOG's Unreleased + the
  help surfaces) — still ungated (check_options checks the
  aliases' cleanliness only).

The verified-aligned ledger — the swept-and-closed alignments, do not
re-open — is the history half:
[history/family-unify.md](history/family-unify.md).

## The security wave (the audit follow-ups)

### COMMON

- **the RBAC rewrite** — the role gate decides on the head
  verb (`command_verb` = the first word, `common/wire/wiresec.py`) with the
  flat verb-set policies (`ROLE_POLICIES`); the request-namespace grammar
  (`request flush cache` — the flush/unset rename wave) already needs
  the "skip the prefix" rule patched into the extraction, and the
  per-child authority (the ops shift may `request flush`, never
  `request reload`) is policy-shaped, not extraction-shaped: rewrite the
  gate to decide on the command PATH — the leaf units with per-child
  policies (`request/flush` in the ops set, `request/reload` out) —
  instead of patching the head-word verb; the audit `role=` entries and
  the `--control-ops-verbs` validation follow the same units.
- **TLS on the audit forward** — the target grammar's `tls://`
  spelling (deliberately out of rev. 27): RFC5425 (TLS over the
  octet-count framing) with the client certificates needs a real TLS
  collector to test against (the suite cannot generate the certificates),
  so the anchor lives here until one exists; `tls://…` today gets the
  generic unknown-scheme refusal.

### CROSS-TOOL

- **the remaining audit findings** `[cache]` `[scraper]` `[inverter]`
  `[docker]` — the open set (per [SECURITY.md](SECURITY.md) rev. 28): F17
  (the volume secrets), F14 (TLS — the item below), F15 (INFO — the
  bearer token + the localhost bind are the controls, the scraper
  README carries the privacy note), F1 (accepted); re-run the audit
  after the TLS story (F14) lands, after the multi-target /
  control-plane evolutions, or any new listener or file format; at
  least yearly otherwise. The closed findings F2–F13, F16, F18–F23
  with their fix and verification:
  [history/AUDIT.md](history/AUDIT.md).
- **a connect ACL for the control plane** `[common]` `[cache]`
  `[scraper]` `[inverter]` `[dashboard]` — SKETCH (Nov 8, decided against
  for today): the control TCP bind is hardcoded `127.0.0.1`
  (`common/wire/control.py`'s `_open_sock`), so an IP gate would decide only
  on the one address that always matches — the local-user threat the
  plane actually has is answered by peer-cred (the unix socket) and the
  token + the signed wire + the ops RBAC (TCP). The item earns its place
  the moment the control port learns to bind beyond loopback: the control
  target grows the `HOST:PORT` spelling (the unix path stays; the default
  stays loopback; `parse_control_target` parses the host part on the
  daemon AND the ctl clients), and a beyond-loopback bind then ships with
  TWO hard companions, the same refusal shape the tokenless TCP already
  speaks: the admin token mandatory (it is today), and an explicit
  **`acl/control`** gate — the ip-prefix system grammar
  (`any|none|IP,...`) or `file:<path>` (the standalone acl file) — with
  `none` NOT the default but a REFUSAL to start until spelled (a remote
  control port without a spelled gate is a misprint, not a posture). The
  machinery is all built (parse_acl_value, IPGate, the acl-file warning
  parity, the `show acl/control/table` row, the connect-time check in the
  accept ladder beside the peer-cred/token checks, the refusals logged +
  audited like the Modbus ones); the unix sockets are untouched (peer-cred
  answers the uid question addresses cannot). The fake included: its
  tokenless-loopback TCP exemption (F11) rides on the bind staying
  loopback — a remote control bind on the fake takes the same companions.
  Re-run the audit when this lands (the remote-control surface is new
  F-item territory).
- **IPv6 on the serving surfaces (and the ACL boundary)** `[common]`
  `[cache]` `[scraper]` `[inverter]` `[docker]` — SKETCH (Nov 8): the
  ACL machinery already speaks both families (the ip-prefix matchers
  validate v6 strict-CIDR, `any` matches every address of either family,
  `is_loopback_host` knows `::1`/`[::1]`, and the CLIENT side is done —
  `socket.create_connection` dials whatever the name resolves, so
  `--upstream '[2001:db8::10]:502'` and a DNS-named v6 inverter work
  today). What does not: every LISTENING socket is hard
  `socket.AF_INET` (the Modbus listen, the control TCP, the metrics
  HTTP — a `[::1]:PORT` bind dies in the address-family error), and on a
  dual-stack socket the peers arrive v4-MAPPED (`::ffff:10.0.0.5`) —
  the ACL boundary would double-book the same client unless normalized.
  The wave: one shared `serve(host, port)`-shaped opener (AF_INET6 when
  the host parses v6, `V6ONLY` off for the dual-stack every-address
  bind, `on` for `::1`), the v4-mapped peer normalization at ONE shared
  helper (the connect/write ACL checks, the caps' per-IP keying, the
  logs/audit peer spellings — a v4 client on a dual-stack socket must
  stay `10.0.0.5` to the ACL, not `::ffff:10.0.0.5`), `parse_listen`'s
  bracketed grammar verified end to end, the regtest coverage on the
  `::1` pair (the v6 loopback works on Linux and macOS alike; the
  v4-mapped carve proof), and the doc pass (docs/common/ACL.md's family notes,
  the AUDIT posture rows, the NixOS `listenHost`'s v6 spelling + the
  dual-stack note — `openFirewall`'s v6 half is the deployment's
  ip6tables business). The docker compose network stays v4 (the demo's
  story); a v6 flag there is optional polish.
- **native TLS on the HTTP surfaces** `[scraper]` `[cache]` `[inverter]` —
  F14 says "terminate at a proxy"; an opt-in native path
  (`--metrics-cert`/`--metrics-key`, stdlib `ssl`) would make a
  proxy-less LAN install defensible: the bearer token stops travelling in
  clear text. The Modbus side stays F1 (accepted, protocol-inherent).
## The pipeline (CI, releases, supply chain)

- **schema every family JSON** `[common]` — `scripts/validate_json.py`
  speaks the draft-2020-12 core but only the shipped spec pairs meet it
  today (the drift sweep's schema/example pass). Give the family's
  remaining JSON artifacts schemas and one gate: `shared/suite/texts.json`,
  the four `options.json`/`defaults.json` pairs, the profiles' format
  (profile-lint checks it in code — a schema would let editors speak
  it) and the config-defaults placeholders; decide the surface (a lint
  script riding the release battery, a drift-sweep type or its own CI
  leg).
- **the CI** `[all]` — GitHub Actions: the ten suites + `nix flake check`
  (all four packages, all systems) on the push; the release workflow on
  the tag; the man pages linted (`mandoc -Tlint`) as a job; `promtool
  check metrics` on a sample exposition.
- **nightly long fuzz + a container smoke** `[all]` `[docker]` — the fuzz
  suites run short on push; a nightly workflow with big budgets
  (`cache-fuzz 10000`, `scrape-fuzz 10000`, `control-fuzz`, the stress
  suite) plus `docker compose up` (the Prometheus answers, no tracebacks
  in the logs).
- **the SBOM / supply-chain note** `[common]` — **done**: `scripts/gen_sbom.py`
  generates both [sbom/SBOM.md](sbom/SBOM.md) + `sbom/sbom.cdx.json` from
  the tree (the import scan gates the render — a foreign dependency fails
  the generation; the vendored ECharts version and its bundled zrender are
  read out of the shipped bundle itself), and the release workflow's `sbom`
  job runs `gen_sbom.py --check` (regenerate + diff), so the pair cannot go
  stale silently.
- **the release discipline** `[common]` — **done**: `scripts/release.py`
  (the orchestrator: the version sweep, the changelog rename, the
  flake.lock refresh, the verification, the commit, the annotated tag —
  signed when a key exists — and the push) plus the tag-triggered
  workflow, which is the release's cutter now (**F19 closed**,
  docs/SECURITY.md rev. 5): the local gate defaults to `--tests full`, the GH
  release is the workflow's `needs: [test, build]`-gated job and the local
  cut is the opt-in `--release`. Watch the first few flights, then retire
  the training wheels.

## The product (what the tools do next)

### SCRAPER

- **the multi-target scrape** — one process polling several
  inverters (per-target metrics with a unit/host label) for the
  two-string-roof households; the metrics endpoint and the audit are
  already per-process.

### INVERTER

- **the priced grid machine** — a tariff-aware import/export
  model on top of the `grid` setpoint (a price curve → the battery
  greedy/eco strategies).
- **the forecast curve** — the PV/cloud machines follow a
  day-ahead forecast file, so a demo runs repeatable weather instead of
  the RNG.
- **the battery ageing** — the SoH drift over the simulated
  days (the capacity shrinks a %/week of the simulated time) + the
  `battery_soh` gauge on /metrics.
- **the machine gauges on /metrics** — the state machines'
  internals as Prometheus gauges (cloud factor, outage state, per-string
  power, the battery's decision): dashboards and the scrape fuzzing could
  watch the machines, not just the registers they feed.
- **the frequency-based derate** — the machine already
  wanders ±0.2 Hz around `--grid-frequency`; beyond a deviation bound the
  output power should derate (exposed on /metrics too).
- **the multi-unit serve** — one process serving two Modbus
  units (the inverter + the meter as separate unit ids) for the
  gateway-style setups.
- **the user-defined scenarios** — scene files (the time +
  the pins + the machines) loadable with `set scenario <file>`; the audit
  trail of a manual session could *record* one.
- **set/show the registers (F1/2/3/4)** — the fake's control
  plane goes fc-aware: the pin verbs take a space qualifier
  (`set register [fc3|fc4] <addr> <value>`, `set coil [fc1|fc2] <addr>
  <0|1>` — the bare form keeps today's space; `discrete`/`input-register`
  the sugar spellings, one store per space) and a first-class
  `input-register` row (the flat name; the live `input/register` path
  under an `input` node) pins the input space — no wire write exists
  there, so its pins ride the dump/restore as a live override while
  register/coil/discrete stay undumped; `show registers` gains the fc
  column + per-space pin markers (today the overlay `*` misfires on fc4
  rows); reset/SIGUSR1/inspect count the fourth map; the suite drives
  `profiles/profiles/demo-fc4.json` for it.
- **the dongle latency profile** — a persistent slow-reply
  mode (the laggy-modem character: every response delayed, not dropped) to
  exercise modbus-read-delay and poll pacing against a realistic SDongle — the
  chaos `stall` is a one-shot, a real dongle is a lifestyle.

### DASHBOARD

- **the dashboard UI redesign** — battery support is always
  on now (the `--battery` knob retired family-wide, the served
  `config.js` always carries `battery: true`), but the front end still
  treats the battery as an add-on: the `batteryEnabled` gate (config.js +
  the `?battery=1` URL escape), the dimmed-node / "no battery detected"
  banner path, and the generation-first layout. Redesign the UI around
  the battery as a first-class, always-present citizen (the flow diagram,
  the KPI row, the energy split) — and reconsider the layout while in
  there.
- **the tariff / cost panels** — once the priced grid
  machine defines a price curve: import cost, export revenue, self-cost —
  the money view next to the energy view.
- **the forecast overlay** — when the fake grows the
  forecast curve and a real forecast source exists: the expected-PV curve
  behind the measured one, the underperformance visible without doing
  math.
- **the battery SoH panels** — when the ageing model lands,
  add the SoH gauge and let the capacity panels use the live value.
- **the cache gauges panels** — the cache's metrics endpoint
  exists (the `modbus_cache_*` gauges); chart the hit/miss ratio, the
  cache age and the poll health next to the generation panels.
- **the outage banner** — the inverter simulates grid
  outages and the meter goes dark; the dashboard could show a standing
  banner (and an annotation gap on the charts) instead of a silent zero
  flatline.
- **the event feed** — the audit vocabulary (writes,
  refusals, outages, reloads) as a dashboard side panel, instead of the
  journalctl detour.
- **the Prometheus annotations** — outages, reloads and
  (with the write console) manual pokes rendered as chart annotations,
  once the event feed exists.
- **the range picker** — the time-range control beyond the
  default window (presets + a from/to picker) on top of the existing query
  plumbing.
- **the German strings** — the i18n merge makes a third
  language cheap (`de: { ... }` in `i18n.js`, the switcher grows
  automatically).
- **the mobile pass** — the flow diagram and the header
  controls assume a desk-sized window; a small-screen layout (the chart
  full-width, the KPI row scrollable) makes the LAN page phone-friendly.

### COMMON

- **an ops `doctor` command per tool** — one shot: validate the
  config, check the token-file modes, probe the upstream (Modbus read),
  probe the metrics endpoint (auth + scrape), stat the dump/audit files,
  print the findings as one report — the "why is my scrape red" first
  stop.
- **the docs site** — **the scaffold is in** (`docs/book/`, the
  mdBook form: the READMEs/audit/TODO/changelog included via
  `{{#include}}`); what remains is the publishing: build + deploy the book
  on GH Pages in the CI item's workflow.

### CROSS-TOOL

- **the demo's write-poke conf** `[docker]` `[cache]` — the demo stack
  is complete (the four services + Prometheus, the dashboard renders
  it, the token story seeded); what remains of the old demo-stack item
  is the demo nicety: a seeded cache conf (or a ctl poke script) that
  turns `allow-write` on with a small register allow-list, so the
  write-through pokes land in the charts live — deliberately NOT the
  default (the demo README documents `allow-write` off).
- **the fault/alarm registers** `[inverter]` → `[cache]` `[scraper]`
  `[dashboard]` — device health words driven by the machines (an outage
  raises a fault, the derate a warning, the battery cap a SoC notice): the
  cache/scrape export them and the dashboard can banner a fault, not just
  a blackout.
- **the write console** `[dashboard]` `[cache]` — a guarded panel issuing
  single-register writes through the cache's allow-list (the write-through
  lands the value in the charts instantly): the ops poke, audited with the
  writer's identity.
- **a Modbus capture/replay tool** `[common]` `[inverter]` — a `pv-suite`
  sidecar that sits on a TCP connection and dumps the wire to a file (and
  replays it): debugging the poll planning, the write-through and the
  chaos behavior against real hardware traces without the hardware.
- **the hardware verification** `[cache]` `[scraper]` — everything is
  verified against the fake inverter, fuzzing and stress only; a real
  SUN2000/SDongle week (poll pacing, the dongle's single-client
  behaviour, real exception codes, the FC4 input registers, reconnect
  storms; the Deye profiles through the cache) is the last mile.
- **the REST API** — an HTTP/JSON face beside the ctl/cli, mostly
  control-plane and statistics: the control verbs over REST (GET a value,
  POST a set — the same `/`-path names, token + RBAC and audit story as
  the wire), the statistics read-only (the registry values, the tables,
  the audit summary); the Prometheus `/metrics` endpoints stay the one
  metrics format.


## Done (the highlights; the git history has the details)

- **the `-file` sibling removal** — `file:` is the one secret spelling
  (the reference landed in the same day's file-reference wave and fully
  subsumed the siblings): the `-file` flags, their `*_FILE` env twins and
  the `-file` config/live keys are gone on all four tools and the eight
  ctl/cli clients; the loader discipline (0600 F12, fail-fast, the
  SIGHUP re-read) is unchanged, the user-facing secret strings say "by
  flag/env, or as `file:<path>`", and the NixOS modules + the compose
  stack render the reference form. The audit wave is docs/SECURITY.md
  rev. 13.
- **the state machinery, family-wide** — the three remaining control
  servers gained `dump_settings`/`apply_dump_settings`, the settings
  state dump (common/settings/dump.py: 0600, integrity-hashed, fail-closed
  restore) with the `dump` node (`dump/path`, `dump/restore-on-start`,
  `request dump`/`request restore`, the shutdown dump), the whole-daemon
  `reload` (the cache's exec dance; the fake's state home was the XDG
  state home then — the config-file wave has since given the fake the
  family's config file), and the **secret lives**: the token pairs
  rotated on the wire at the time (the secrets-startup-only wave has
  since retired the live rotation — every secret knob passes by
  flag/env/config and a restart), the `show` verb refuses the
  secrets (the value renders nowhere), the secret defaults placeholders
  are gone (unset refuses).
- **the hierarchical control grammar** — the live names are `/`-paths
  spelled as words on the wire (`set modbus upstream <value>`, however
  deep; the alias rows answer a second spelling, the canonical renders);
  the config scripts speak the CLI spelling too (the word-index parser —
  values may carry spaces, an unknown name fails fast with the line
  number, the flat dashed names still read); a typed row dispatches
  itself (the conv parses, no `_apply`/`_get` branch); the registries
  dropped the `section` field — the display `group` is the one grouping,
  ungrouped rows render bare with no header, and the cli listings have no
  `[system]`/`[ungrouped]` buckets anymore; the consoles prefix every
  non-value reply line with `% ` (the show reports and tables stay bare
  values); the cache gained the whole-daemon `reload` (the overrides to
  `<config>.reload`, re-exec, re-apply once — the restart-marked knobs
  take their configured values) and the live control-plane rebind/token
  rotation; docs/SECURITY.md rev. 9 walked it (F23 raised and closed: the
  reload state file is 0600 explicitly).
- **the env-prefix retirement** — the env twins are the knobs' bare
  upper-snake names (`HOST`, `PORT`, `LISTEN`, `CTL`, `CONTROL_TOKEN`,
  ...) — the per-tool prefixes (`MCH_*`/`SCR_*`/`INV_*`/`DSH_*`) retired;
  the twins are scoped per deployment surface (the systemd unit, the
  compose service, the dev shell), so the shared names stay safe. The
  cache is retagged to its device-first tagline ("Modbus TCP caching
  proxy for single-client devices") and the metrics renames' last stale
  mentions are fixed (the scrape README's metrics table, the dashboard's
  `batteryFlag` default); the man pages rebuilt.
- **the rename + env-prefix wave** — the bins and clients carry their
  man-page names (the dash names: `modbus-cache.py`,
  `modbus-scraper*.py`, `modbus-fake-*.py`,
  `dashboard-*.py`); every env twin then wore its tool's prefix —
  `MCH_*` (cache), `SCR_*` (scraper), `INV_*` (fake), `DSH_*`
  (dashboard, the generic docker envs retired) — since retired by the
  bare-name wave (the record above); with the one short `*_CTL` form for the
  control port; the constants audit put `log_levels` in every tool's
  `lib/static.json` (and the metrics-endpoint defaults on the dashboard),
  and the scraper's register map now lives in the device profile alone —
  the register/scale knobs are gone and `set modbus profile` swaps the map
  live (a bad profile rolls back).
- **the config-format wave** — the ini is gone (the breaking wave): the
  config files speak the control grammar (`set <name> <value>` lines, `#`
  comments — a config file pipes through a ctl client), `show config`
  regenerates the script from the running daemon (secrets hidden),
  `help config` maps every knob to its control command, the bundled
  samples and the NixOS modules render the set grammar, and the
  **one-knob-one-source** registry (`lib/options.json` + its loader
  `lib/options.py` per tool on `common/settings/options.py`) +
  `scripts/check_options.py` gate the four
  surfaces against drift. Also closed in the wave: the RBAC verb policy
  (`--control-ops-verbs`), the dashboard's own /metrics endpoint, the
  metrics.json sections + `--metric-prefix` + the `scraper_*` renames
  (the `scraper` section since moved to `lib/metrics.json`, merged in
  memory over the configured spec),
  the poll-latency gauges, the shipped FC4 profile
  (`profiles/profiles/demo-fc4.json`) and the per-phase chain (the
  metrics + the dashboard's phase strip); the scrape README carries the
  F15 privacy note.
- **the read-only control role** — the former open item ("a second token
  granting only the show/clear verbs") shipped family-wide: every control
  server takes `--control-ops-token` and scopes its ops sessions to the
  show/clear verbs — the ops shift versus the admin key, both audited
  (`role=ops`/`role=admin` in the COMMAND entries). (The record's
  `--control-ops-token-file` spelling died with the `-file` removal —
  `file:` inside the plain token is the spelling.) The per-tool records name the flag/env forms; the audit wave
  is docs/SECURITY.md rev. 7 (F22 raised and closed with it).
- **the metrics endpoint wave** — the caps (max-clients/client-timeout/
  max-conn-per-ip) on every HTTP + Modbus surface, the fake's and the
  cache's endpoints live-togglable (`metrics-server` + `--metrics-listen`),
  the scraper refusing a non-loopback listen without a token (F13 closed).
- **the integrity wave** — the audit trails carry chained per-writer
  hashes verified by `scripts/audit_verify.py` (F10); the state dump is
  0600 + integrity-hashed with a fail-closed restore (F18); the dump
  splits by content (settings by default, with-cache on request).
- **the release tooling** — `scripts/release.py` + the tag-triggered
  release workflow (the pipeline item above is the operational follow-up).
- **the systemd unit hardening** — the three NixOS modules sandbox every
  service (`ProtectSystem=strict`, `PrivateDevices`, `ProtectHome`,
  `MemoryDenyWriteExecute`, `CapabilityBoundingSet=`,
  `RestrictAddressFamilies`, `SystemCallFilter`), verified with
  `systemd-analyze security` (a score per unit asserted by
  nixos/tests/hardening.nix); nixos/README.md documents the posture.
- **the token-file env honored** `[inverter]` — the help promised
  `CONTROL_TOKEN_FILE` / `METRICS_TOKEN_FILE`, the code never
  read them: both are honored now (the fake and the two clients — flag
  over env, the file over the plain token, both together the
  mutual-exclusion error). (Since retired by the `-file` sibling
  removal: there are no `*_FILE` twins — `file:<path>` inside the plain
  token value is the one spelling.)
- **the man pages** — one roff page per tool in each subproject's `man/`
  (`man/` per subproject; 14 pages: the three cache binaries,
  the three inverter binaries, the three scraper binaries, the dashboard
  server + its two clients, the two profile tools), installed by the Nix
  packages (`share/man/man1/`) and linted with `mandoc -Tlint`.
- **the demo stack, the Modbus chain** — `docker/compose.yaml`: the three
  alpine images (one Dockerfile per tool, unprivileged `pvsuite`, tools on
  `PATH`), the shared external `config` volume seeded by `entrypoint.sh`
  (bundled defaults copied in, existing files kept), the profiles +
  `common/` riding in as named build contexts.
- **the profile linter** — `profiles/bin/profile-lint.py`: the required
  keys and their family order, the register bounds, the type width, the
  fc, the per-entry ttl, the mappings vs a register word, the duplicate
  names, the same-fc overlaps, the terse-ASCII style; all four shipped
  profiles lint clean.
- **the profile formatter** — `profiles/bin/profile-format.py`: rewrites
  any profile into the sun2000.json layout in place — one mappings entry
  per line, one register per line, keys in the family order;
  content-preserving and idempotent (the sun2000 itself comes back
  byte-for-byte).
- **the common/ package** — the shared core extracted: version, audit,
  config plumbing, the Modbus wire core, the UTC log formatter; the suite
  talks one vocabulary — and the control plane followed (the ctl/cli
  clients, the metrics endpoint skeleton, the resolver pieces, the
  control-server base: one implementation each, the tools subclass or
  pass their spec).
- **the compute-expression wave** — the scraper's compute metrics are
  expression-fed: the spec's one merged `metrics` tree carries entries
  with `expr` (+ the optional `when` gate) or a `profile` binding (the
  field says what feeds it; the old `profile`/`compute` sections refuse),
  a stdlib-safe whitelist evaluator (`lib/expr.py`) compiles them once at
  startup and the poller evaluates per poll (an unavailable input or a
  failed eval keeps the metric absent); the "inputs" declaration and the
  four canonical metrics (the power math's inputs, always bound and
  fetched) ship in the built-in lib/metrics.json (merged into every spec;
  a spec's own section rewords the inputs, a double-bound register
  refuses), `show inputs` / `show inputs metrics` (normal
  registry rows) render the vocabulary and the exported metrics, the five
  classic compute metrics ride as the built-in eval-table defaults, and
  the default spec resolves from a source checkout's `examples/` (the
  packaging re-flattens it) — the double-`Metrics()` wart in the bin (the
  daemon exported the default spec over `--metrics-spec`) fell out of the
  same wave.

Per-tool **Done/history** lives in each subproject's own TODO.md
([cache](../cache/TODO.md), [scraper](../scraper/TODO.md),
[inverter](../inverter/TODO.md), [dashboard](../dashboard/TODO.md)).
