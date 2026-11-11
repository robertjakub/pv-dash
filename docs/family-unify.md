# The family-unified TODO (one product, swept 2026-11-10, re-verified 2026-11-11)

The working assumption: **the family is one product** — a user moving
between the four tools (cache, scraper, inverter, dashboard) finds the
same knobs, the same words, the same refusals and the same env layer.
This file is the one-product sweep: what still breaks that promise,
with the per-tool truth and the unified outcome stated per item. Open
items graduate to [TODO.md](TODO.md) when a wave picks them up; the
landed consistency legs live in [family-drift.md](family-drift.md)
(this sweep adds what its name-intersection pass cannot see: the
near-miss knob names, the tool-absent rows, the live-run refusal
texts).

Frame note from the re-verification: since the first sweep the wire
speaks the **flat registry names** (each row's `name` — `interval`,
`max-conn-per-ip`) and the rows' `live`/`alias` paths became **console
spellings** the cli and the ctls translate before sending
(`common/wire/cli.py:35`); the knob defaults moved into the registry
rows. The items below spell the console form where they name a user
action, and the flat name where they name the wire.

## The short list — the user gets silently bitten

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
2. **The cache's `metrics-token` has no config layer** — the bin reads
   flag/env only (`cache/bin/modbus-cache.py:154`); a config line
   `set metrics-token ...` parses (the word index takes both spellings,
   `common/settings/options.py:126-139`) and is silently dropped —
   `cache/lib/config.py` has no `metrics_token` key at all — while
   scraper (its bearer `auth_token`, `scraper/lib/config.py:249-250`),
   inverter (`resolve_args`, `inverter/lib/config.py:36-75`) and
   dashboard (`dashboard/lib/config.py:123-124`) resolve the token
   through the full ladder. `show config` cannot reveal the gap either
   (a secret row's `config_value` is `None`,
   `common/settings/options.py:378-379`). Outcome: resolve it in
   `cache/lib/config.py`, drop the bin-local read.
3. **`AUTH_TOKEN` means two different secrets** — the /metrics bearer
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

## The knob plane — the same knob everywhere

- **the unit id, three spellings** `[cache]` `[scraper]` `[inverter]`
  — cache `unit`/`--unit`/`UNIT` (`cache/lib/options.json:11`),
  scraper `modbus-unit`/`--modbus-unit`/`MODBUS_UNIT` (`:8`), the
  inverter `unit` with no env twin and no live at all
  (`inverter/lib/options.json:50` — startup-only by absence). The
  range half landed: one shared tree gates every tool with a unit knob
  (`common/modbus/protocol.json` — 1..247, `unit_in_range`; start and
  reload validate, the Modbus servers refuse out-of-range ids in-band,
  `check_options.py` gates the check). What remains: the scraper's row
  still declares `min: 0, max: 255` and only its live set gates on it
  (`scraper/lib/control.py:306`) while start refuses `<1`; the cache's
  live `set unit` is ungated entirely (`cache/lib/control.py:244`);
  docs/OPTIONS.md still lists `modbus-unit` and `unit` as two knobs
  (`:110`, `:132`) — both rendering the same console spelling
  `set modbus unit`. Outcome: one name, one flag, one env, live
  everywhere, the row bounds = the shared tree's range (the NixOS
  `unitId`/`modbusUnit` renames follow).
- **the listener caps, three console schemes** `[all]` —
  `max-clients`/`client-timeout`/`max-conn-per-ip` console as
  `limits/*` on the cache, `metrics/limits/*` on the scraper, and bare
  on the inverter and dashboard (`cache/lib/options.json:102-114`,
  `scraper:64-79`, `inverter:149-158`, `dashboard:21-30`); the cache's
  own metrics leaf is `metrics/limits/timeout` while its socket leaf
  is `limits/client-timeout` (one family, two leaves, `:186` vs
  `:107`). The wire speaks the bare flat names on every tool, so the
  drift hides behind the console spellings (docs/OPTIONS.md renders
  the union, `:89`). Outcome:
  `<surface>/limits/{max-clients,client-timeout,max-conn-per-ip}`; the
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
- **`local-time` and `log-access` skip the inverter** `[inverter]`
  — cache/scraper/dashboard carry both rows (the cache nests
  `system/log-access`, the only `system/` child besides `listen`
  (`cache/lib/options.json:239`); the dashboard's `local-time` is
  startup-only, `dashboard/lib/options.json:162`); the inverter logs
  too and has neither row. Outcome: both rows family-wide, live,
  top-level.
- **the access-audit trio, three names, one job** `[all]` —
  `requests-audit` (cache, `cache/lib/options.json:230`, an interval
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
  consoles as `caps/max-pv` on the scraper and bare `max-kwp` on the
  inverter (hint `KW` vs `kW`, `scraper/lib/options.json:47` vs
  `inverter:57`); `connect-acl` consoles as `acl/connect` on the cache
  and bare on the inverter, whose help also omits the `file:<path>`
  form its sibling supports (`cache/lib/options.json:80` vs
  `inverter:138`); the cache's `dump-interval` is the only dump child
  outside the `dump/` node (`:256`, beside `dump/path`, `dump/key`,
  `dump/with-cache`, `dump/restore-on-start`). Outcome: the node-ful
  spelling wins each time.
- **the NixOS render bugs** `[cache]` `[dashboard]` — the dashboard
  emits `--metrics-server` whenever `metricsServer` is set, including
  explicit `false` (the flag turns the endpoint ON,
  `nixos/modules/dashboard.nix:61`); the cache renders `set audit requests`
  with an empty value from an unset `requestsAudit`
  (`nixos/modules/modbus-cache.nix:87` — `toString null`, and the config parser
  refuses a valueless set line) and the metrics pair likewise
  (`:105-108`); the dashboard's metrics-token LoadCredential is passed
  even when undeclared (`:63` vs `:530`); `nixos/modules/modbus-cache.nix:341`
  documents `metricsServerToken` for options named `metricsToken`.
  Outcome: the bool semantics from the registry, guarded set lines,
  the doc names fixed; the inverter has no module.nix at all (68 rows
  — 59 knobs + 9 nodes — with no NixOS parity; accepted, but say so in
  the doc).
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

## The word plane — the same words everywhere

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
  `shared/texts.json:82` — plus the set-path hand copy), `, restart` /
  `startup-only — pass it by flag/env/config (set/clear refuse)`
  (show knobs + help config via `control_command()`,
  `common/settings/options.py:390-408`, and the OPTIONS.md generator's
  own copy of the strings, `scripts/gen_options.py:71-76`),
  `*(restart)*` / `startup-only (secret)` (MANUAL.md,
  `scripts/gen_manual.py:143-146`), `restart: true` + the wire phrase
  (only the cache's man carries the trio now, `cache/lib/man.py:98-107`),
  and "restart to apply" (inverter/README.md:204). Outcome: a
  two-phrase lexicon in `shared/texts.json`, every surface renders it,
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
  --control-port 0 to disable it)`, `shared/texts.json:104`, rendered
  `common/wire/control.py:212`), the live rebind says
  `cannot bind control-port ...` (`shared/texts.json:108`, the flat
  spelling now), the Modbus surfaces say `cannot bind`
  (`shared/texts.json:70` + the hand copies above). Outcome: keep the
  non-fatal behaviour, document the three-tier story once.

## The env plane — the same env layer everywhere

- **the cache's metrics-token ladder** — see short list item 2.
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

## The gates that keep it

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
  (`scripts/gen_env.py --check`): the full registry env-twin set per
  tool (50/39/34/36), grouped by the knob's namespace node, the image's
  own CMD/ENV values as the sample lines with the pin notes (the
  compose's environment pins marked per knob), the secrets' lines
  empty, the prometheus example's `PROM_*` names cross-checked against
  the entrypoint — the gate that replaced the "check_options (or
  family_drift) diffs the registry env twins against
  `docker/env/*.env.example`" open item;
- `lint_texts.py` flags a **literal that equals a leaf** after
  `%`-normalisation — still missing.
- the breaking renames (the scraper's `auth-token` → `metrics-token`,
  the unit unification) ship with the **alias map + the migration
  note** in docs/OPTIONS.md — still ungated (check_options checks the
  aliases' cleanliness only).

## Verified aligned (do not re-open)

The shared Resolver and its precedence on all four (flags > env >
config > the rows' static rung); the config-script grammar refusals
(one loader, rc 1, identical bytes); the needs-a-value and
restart-note/refusal texts; the auth-first/bad-token/unsigned/bad-mac
ladder; the RBAC refusal text and fail-closed roles; the dump/key
symmetric gate (one reader, `common/settings/dump.py:180`); the
F13↔F21 move-refusal template (the model); the write-refused line
cache↔fake; the control/audit/dump/listen registry blocks
field-for-field; `metrics-acl` + its table row; `log-level`,
`allow-write`, `modbus-auth`, `max-kwp`'s conv+default, `interval`'s
conv+default; all 23 secret rows' secret+hidden+restart posture; the
console banners and the whole ctl/cli UX (one code path); the
console↔flat translation (one `translate()` path behind the cli and
the ctls); the wire status alphabet `ok|fail|note|bye` (one producer,
`common/wire/control.py:447`); the help renderer, sorting and alias
marker; the empty-env unset rule in every resolver; no shared
env_file in any stack; every docker `ENV` line and compose key a real
registry twin.
