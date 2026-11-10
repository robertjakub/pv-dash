# The family-unified TODO (one product, swept 2026-11-10)

The working assumption: **the family is one product** — a user moving
between the four tools (cache, scraper, inverter, dashboard) finds the
same knobs, the same words, the same refusals and the same env layer.
This file is the one-product sweep: what still breaks that promise,
with the per-tool truth and the unified outcome stated per item. Open
items graduate to [TODO.md](TODO.md) when a wave picks them up; the
landed consistency legs live in [family-drift.md](family-drift.md)
(this sweep adds what its name-intersection pass cannot see: the
near-miss knob names, the tool-absent rows, the `defaults.json`
defaults, the live-run refusal texts).

## The short list — the user gets silently bitten

1. **The scraper's live `system/listen` has no F13 floor** — the
   dashboard refuses the move beyond loopback (F21 template,
   `dashboard/lib/control.py:155`) and the cache guards its metrics
   endpoint (`cache/lib/control.py:198`), but the scraper's restart
   preamble probe-binds and records the pending listen without asking
   `is_loopback_host` (`scraper/lib/control.py:194-208`), and the
   restart-state fold lands *after* `resolve_config()`'s startup F13
   check (`scraper/bin/modbus-scraper.py:93` resolve, `:101` fold) —
   a tokenless scraper can `set system/listen 0.0.0.0:9350`,
   `request reload`, and serve beyond loopback with no token.
   Outcome: the F21 move-refusal template, verbatim, in the scraper's
   restart preamble.
2. **`audit-forward-format` ignores its env and config layers on all
   four tools** — every registry row declared `AUDIT_FORWARD_FORMAT`
   *and* baked `"default": "rfc5424"` into the row
   (`cache/lib/options.json:206`, `scraper:138`, `inverter:232`,
   `dashboard:119`), `build_parser` put the default on the flag
   (`common/settings/options.py:119-121`), so the resolver's first
   layer never fell through: the env twin and the config line were
   dead (verified live on cache/scraper/inverter). Outcome: LANDED
   2026-11-10, the defaults.json defaults sweep — the row default is
   gone; the default is the resolver's static rung, the tree's
   `audit_forward_format` entry (`DEFAULTS['audit_forward_format']` on
   cache/scraper/dashboard; the fake's
   `STATIC_DEFAULTS['audit-forward-format']` reads the same entry —
   without it the ladder would end at `None` and `AuditLog` refuses
   the start, `common/runtime/audit.py:369`). Verified live:
   `AUDIT_FORWARD_FORMAT=cef` resolves on all four.
3. **The dashboard's `LISTEN` env is dead** — its loader injected
   `static_defaults = {'listen': defaults['listen']}`
   (`dashboard/lib/options.py:42`), the flag was never empty, the env
   layer never ran (verified: `LISTEN=0.0.0.0:9999` honored by the
   other three, ignored by the dashboard). The compose files set
   `LISTEN: 0.0.0.0:8080` (`docker/demo/compose.yaml:176`,
   `docker/prod/compose.yaml:140`) and only worked because the image
   CMD pins the flag. Outcome: LANDED 2026-11-10, the defaults.json
   defaults sweep — the `static_defaults` wiring is gone, the
   resolver's static rung (`DEFAULT_LISTEN`) owns the default; the
   env resolves again.
4. **The cache's `metrics-token` has no config layer** — the bin
   reads flag/env only (`cache/bin/modbus-cache.py:162`); a config
   line `set metrics-token ...` parses and is silently dropped, while
   scraper/inverter/dashboard resolve the token through the full
   ladder. Outcome: resolve it in `cache/lib/config.py`, drop the
   bin-local read.
5. **`AUTH_TOKEN` means two different secrets** — the /metrics bearer
   on the scraper (`scraper/lib/options.json:116`, live
   `metrics/auth/token`) and the page bearer on the dashboard
   (`dashboard/lib/options.json:36`, live `auth/token`), while the
   same /metrics bearer is `metrics-token`/`METRICS_TOKEN` on the
   cache, inverter and dashboard. Migrating a token between tools
   changes the variable *and* the meaning. Outcome: the scraper's
   /metrics bearer renames to `metrics-token`/`METRICS_TOKEN`/
   `metrics/token`; `auth-token` keeps the user-facing-serving
   meaning (breaking: the alias map carries `auth-token` one release).

## The knob plane — the same knob everywhere

- **the unit id, three spellings** `[cache]` `[scraper]` `[inverter]`
  — cache `unit`/`--unit`/`UNIT` (`cache/lib/options.json:10`),
  scraper `modbus-unit`/`--modbus-unit`/`MODBUS_UNIT` (`:8`), the
  inverter `unit` with no env twin (`inverter/lib/options.json:50`);
  only the scraper carries the `0..255` bounds; the inverter's is
  startup-only while the other two live on `modbus/unit`;
  docs/OPTIONS.md lists `modbus-unit` and `unit` as two knobs.
  Outcome: one name, one flag, one env, live `modbus/unit`, bounds
  everywhere (the NixOS `unitId`/`modbusUnit` renames follow).
- **the listener caps, three live-path schemes** `[all]` —
  `max-clients`/`client-timeout`/`max-conn-per-ip` live as
  `limits/*` on the cache, `metrics/limits/*` on the scraper, and
  bare on the inverter and dashboard; the cache's own metrics leaf is
  `metrics/limits/timeout` while its socket leaf is
  `limits/client-timeout` (one family, two leaves). Outcome:
  `<surface>/limits/{max-clients,client-timeout,max-conn-per-ip}`;
  the leaf is `client-timeout` everywhere.
- **the /metrics caps, four postures** `[scraper]` `[inverter]`
  `[dashboard]` — the cache has the full trio (defaults 64/0/5.0,
  `METRICS_*` envs, bounds, live); the scraper has **no rows at all**
  (its caps are the base trio); the inverter has the rows but no
  live, no env, no bounds (`env: null` + the F11 note); the dashboard
  has envs but **defaults `metrics_max_clients` 16** vs 64
  (`dashboard/lib/defaults.json:16`) and no live/bounds. Outcome: the
  cache's row shape family-wide, default vector {64, 0, 5.0}, the
  scraper's always-on endpoint documented as the exception.
- **`metrics/listen` means two sockets** `[cache]` `[scraper]` — the
  cache's `metrics/listen` is the /metrics bind; the scraper's
  `listen` carries `"alias": "metrics/listen"`
  (`scraper/lib/options.json:53`), so `set metrics-listen` moves the
  *main* HTTP listen there. The worst same-words-different-socket in
  the family. Outcome: the alias dies; `metrics/listen` is the
  /metrics bind only.
- **`local-time` and `log-access` skip the inverter** `[inverter]`
  — cache/scraper/dashboard carry both rows (the dashboard's
  `local-time` is startup-only; the cache nests `system/log-access`,
  the only `system/` child besides `listen`); the inverter logs too
  and has neither. Outcome: both rows family-wide, live, top-level.
- **the access-audit trio, three names, one job** `[all]` —
  `requests-audit` (cache, `audit/requests`, per-client tally with an
  interval), `log-access` (scraper/dashboard, on/off),
  `log-queries` (dashboard only, no env); the inverter has none. The
  cache row's own `min: 1` contradicts its help's `0 = off`
  (`cache/lib/options.json:224`, `cache/lib/config.py:353`).
  Outcome: decide the family shape (an interval knob beats on/off),
  spell it once, give the inverter its row, fix the min/help.
- **`upstream`, one name, three layers** `[cache]` `[scraper]`
  `[dashboard]` — the env is `UPSTREAM` on the two Modbus tools and
  `PROM_URL` on the dashboard; the cache marks it `restart: true`,
  the scraper says nothing; the dashboard has no live. Outcome: the
  env does not fork (`PROM_URL` at most a back-compat alias); the
  restart mark decided once.
- **the poll interval, two namespaces** `[cache]` `[scraper]` — same
  conv, same default 10.0, live `modbus/interval` vs
  `metrics/interval` (`cache/lib/options.json:40`,
  `scraper:155`). Outcome: `modbus/interval` in both (the knob polls
  the device on both tools).
- **near-miss live paths** `[scraper]` `[inverter]` — `max-kwp`
  lives as `caps/max-pv` on the scraper and bare `max-kwp` on the
  inverter (hint `KW` vs `kW`); `profile` lives as `modbus/profile`
  on cache/scraper and bare on the inverter; `connect-acl` lives as
  `acl/connect` on the cache and bare on the inverter (whose help
  also omits the `file:<path>` form its sibling supports); the
  cache's `dump-interval` is the only dump child outside the `dump/`
  node. Outcome: the node-ful spelling wins each time.
- **the stale prose rows** `[all]` — every `control` node said
  `(the default: show and clear)` while the derived default is
  `show,flush` on the cache and `show` elsewhere (the
  `default_ops_verbs` derivation): four false sentences in the
  registries, `cache/README.md` and `scripts/gen_manual.py`'s literal.
  The inverter's `log-level` row had **no help** (an empty `.TP`
  rendered in its man page), and its `battery-kwh` `no-env` note
  blamed a `BATTERY` SIGHUP env no code reads. Outcome: LANDED
  2026-11-10, the family-sweep wave — the rows/gen_manual speak the
  derived default (the generator now derives it from the registry),
  the log-level help is in, the BATTERY note is F11-honest; the
  scraper's `auth` node bearer prose stays (the auth-token rename is
  short-list item 5).
- **the NixOS render bugs** `[cache]` `[dashboard]` — the dashboard
  emits `--metrics-server` for `metricsServer = false` (the flag
  turns the endpoint ON, `dashboard/module.nix:73`); the cache
  renders `set metrics-listen null` and `set requests-audit null`
  from null defaults (`cache/module.nix:106,87`); the dashboard's
  metrics-token LoadCredential is passed even when undeclared
  (`:76-78` vs `:533`); `cache/module.nix:341` documents
  `metricsServerToken` for options named `metricsToken`. Outcome:
  the bool semantics from the registry, null-guarded set lines, the
  doc names fixed; the inverter has no module.nix at all (66 rows
  with no NixOS parity — accepted, but say so in the doc).
- **the knob sweep's blind spots** `[common]` —
  `family_drift.py` compares only the 31 names present in all four,
  so every near-miss pair above (`unit`/`modbus-unit`,
  `metrics-token`/`auth-token`) and every tool-absent row never
  enters the table; the effective defaults live in `lib/defaults.json`
  and no gate reads them (the dashboard's 16 survived exactly there).
  Outcome: a concept key (an explicit equivalence map) per row, and
  the sweep reads `defaults.json → defaults`.

## The word plane — the same words everywhere

- **eleven hardcoded copies of texts.json leaves** `[all]` —
  `common/wire/control.py:574` (the set-path restart note beside the
  clear path's `T()`), `:623` (reload failed), the cache's whole
  dump/restore error set (`cache/lib/control.py:791-824`), the
  cache bin's sealed/skipped suffixes (`:88,230,347`), the scraper's
  ops-token listen line (`scraper/bin/modbus-scraper.py:130`), its
  `must be on or off` (`scraper/lib/control.py:309`), the unknown
  settings (`:315`, `cache/lib/control.py:458`), the fake's config
  head + comment (`inverter/lib/control.py:180-182`), and the
  `cannot bind` string four tools spell by hand. `lint_texts.py`
  cannot see a literal that equals a leaf. Outcome: the leaves win;
  the lint learns the literal-equals-leaf check.
- **the cache's dump/restore replies are a fourth dialect** —
  `ok dumped %d word(s), %d setting(s) to ...` vs the family's
  `ok dumped %d setting(s) to ...` (`cache/lib/control.py:802,823`).
  Keep the cache's extra count if the payload demands it, but reuse
  the family leaves for every error and suffix.
- **the fake's dialects** `[inverter]` — unknown tails answer the
  whole path unquoted where the family answers the first word quoted
  (`inverter/lib/control.py:590-597` vs
  `common/wire/control.py:656,668`); `inspect` folds `uptime` into
  `now` and drops the app name from `version`
  (`inverter/lib/control.py:653,662`); its `command_help` omits
  `inspect`. Documented as F11 colour — keep only what the docstring
  rules, align the rest.
- **one health word, two spellings** `[scraper]` `[dashboard]` — the
  `set` reply summary spells the upstream health `poll=ok|down` on
  the cache and scraper but `upstream_ok=` on the dashboard.
  Outcome: one key.
- **the help one-liners** `[all]` — `help show/set/clear` differ
  (the cache names reports in the bracket, the other three show
  example knobs); `show knobs` is "the dictionary of all knobs" vs
  the inverter's "of the registry"; `show config` is "the effective
  configuration" vs the inverter's "the startup options"; the
  metrics-acl-table help is long on cache/scraper, short on
  inverter/dashboard; the inverter's `connect-acl` help says "the
  cache's connect-acl, mirrored" — a cross-tool reference in a user
  row. Outcome: one line per verb, per-tool brackets only.
- **the knob descriptions, four voices** `[all]` — `control-port`
  alone has three dialects ("control server target..." /
  "JSON-lines control server target..."); `max-clients` describes a
  Modbus socket on two tools and an HTTP one on two (correct per
  tool, but the sentence templates should match); `audit-log`,
  `audit-files`, `metrics-token` each split "audit trail/audit log"
  and two Bearer phrasings; the scraper's man page has no
  `--metrics-token` to match the cache's cross-reference. Outcome:
  one template per concept, the surface noun as the only variable.
- **the restart-marker vocabularies** `[all]` — the same fact ships
  as `note restart required (startup-only knob)` (wire),
  `, restart` / `startup-only — pass it by flag/env/config`
  (show knobs, help config, OPTIONS.md), `*(restart)*` /
  `startup-only (secret)` (MANUAL.md), `restart: true` + "startup-only
  secret" (man pages), and "restart to apply" (inverter README).
  Outcome: a two-phrase lexicon in `shared/texts.json`, every surface
  renders it, the marker rule ("the % changed exception") stays.
- **the man pages lag the wire** `[all]` — all four described the
  wire as `{"status": "ok|fail|bye"}` (the `note` status missing),
  `unset` survived in the four `lib/man.py` prose sources and the
  ctl docstrings, and the READMEs repeated the retired spellings.
  Outcome: LANDED 2026-11-10, the family-sweep wave — the sources
  speak `ok|fail|note|bye` + `set/clear`, the pages regenerate (the
  `--check` gates only catch stale *output*, not stale *prose
  sources* — the redo hunts the sources). The cli pages' `% changed` /
  `[confirm]` mentions stay open (a docs nicety, not a lie).
- **the dashboard's dead live branch** `[dashboard]` `[common]` —
  the registry has no live for the dashboard's `local-time`, but the
  shared `apply_family_key`/`get_family_key` carry a live branch for
  it: RESOLVED by verification (the family-sweep wave) — the branch
  is LIVE for the cache and the scraper (their rows carry
  `live: local-time`); only the dashboard's row has no live. Not
  dead — the item becomes the knob-plane question of the dashboard's
  row joining (the local-time/log-access knob item above).
- **the rc discipline splits on the unsafe-config refusals** —
  the F13 start refusal exits 2 on cache/dashboard
  (`cache/bin/modbus-cache.py:168`, `dashboard/bin/dashboard.py:318`)
  and 1 on scraper/fake; TCP-control-without-token exits 2 on the
  cache (`bin:161`) and 1 on scraper/dashboard (verified live, same
  text). Outcome: one rc for "the config is unsafe" — the evidence
  leans 2 (CLI-config mistakes), the fake's rc 1 stays its F11
  posture; also pick one *presentation* (the cache/dashboard log an
  ERROR line, the scraper/dashboard config path prints a bare
  `SystemExit(str)`).
- **`cannot serve on` vs `cannot bind`** `[cache]` `[inverter]` — the Modbus listeners answered `cannot serve on ...` where
  every other listener says `cannot bind`. Outcome: LANDED
  2026-11-10, the family-sweep wave — `cannot bind` family-wide
  (nothing pinned the old text).
- **the live F13 floor, three spellings** `[cache]` `[dashboard]`
  `[inverter]` — the cache prefixes "the metrics endpoint serves
  register values: ", the dashboard "serves the request counters: ",
  the fake sends the bare sentence (`cache/lib/control.py:339`,
  `dashboard/lib/control.py:195`, `inverter/lib/control.py:354`).
  Outcome: the bare sentence, one `T()` leaf.
- **the ops-token sentence, three spellings + dead code** — the
  common loader says `the read-only ops token supplements the admin
  token: set --control-token too`; the cache's validate_config wraps
  it and its bin carried two unreachable rc-2 branches
  (validate_config fires first). Outcome: LANDED 2026-11-10, the
  family-sweep wave — the dead branches die (the common sentence
  stands; the wrap-vs-plain spelling stays the cache's).
- **the value-parse refusals, four voices** — the spine's canon is
  `<live-name> must be <what>, got %r` (the `_apply` parsers): the
  fake leaked Python's own exception text to the wire and console
  (`could not convert string to float: 'abc'`) and **silently coerced
  bad bools** (`set strict maybe` → `ok strict=off`); the scraper's
  `_typed` dropped `, got %r`. Outcome: LANDED 2026-11-10, the
  family-sweep wave — the fake parses through `num`/`numi` and refuses
  bools through `on_off` (its `strict`/`static` included), the
  scraper's `_typed` carries the canon. The metrics toggle label
  spelling (`metrics enable` / `metrics-server` / `metrics/enable`) —
  one label — stays open.
- **the mislabeled refusals** — the scraper rendered
  `invalid modbus-unit = None` (the fail closure looked up a key that
  does not exist); the shared listen validator hardcoded the
  `--listen` label so `--metrics-listen nope` answered
  `--listen must be HOST:PORT`; a `--control-port 99999` on
  scraper/dashboard answered the *token* sentence (the isdigit
  tokenless check preceded the range check). Outcome: LANDED
  2026-11-10, the family-sweep wave — the label param, the key fix
  and the valid-port scope; 99999 answers the range validator.
- **the startup validation, two shapes** — cache/scraper/dashboard
  say `invalid <key> = <val>: <rule>`; the fake says
  `--flag <rule>, got %r` and collects every problem before exiting.
  Both legitimate — pick the family shape (the `invalid k = v` form
  reads better in logs) or document the fake's as F11.
- **the lenient-start policy is unstated** — a bad env/config value
  warns and defaults (rc 0, `common/settings/config.py:121`) while
  the same text over `set` refuses; a user's config typo starts a
  daemon on defaults with one WARNING. Outcome: state the policy in
  the READMEs/man SECURITY or AUDIT (and keep it), or fail fast.
- **the ctl exits 0 on a refused command** — a `fail` reply prints
  `% error: ...` and exits 0 (verified); scripts cannot tell a
  refused command from a served one. Outcome: decide (rc 1 when any
  reply is `fail`), document it in EXIT STATUS.
- **the 401 bodies, three spellings** — `unauthorized\n` (scraper
  page), `401 unauthorized\n` (common metrics), the dashboard's long
  cookie-bootstrap sentence (fine — it teaches the `?auth=` hop).
  Outcome: the common metrics pair wins on plain surfaces.
- **the scheme spellings rule is unwritten** — audit-forward/format
  refuse with flags at start (`audit-forward must be none, syslog,
  ...`) and with live paths on the wire (`audit/forward must be ...`,
  `common/wire/control.py:783`). Same rule F5/F13 follow. Outcome:
  write the rule down (startup prose speaks flags, the wire speaks
  live paths) next to the texts.
- **the control listener's three bind texts** — start bind failure
  is non-fatal by design (`control server cannot bind ... (use
  --control-port 0 to disable it)`, `common/wire/control.py:201`),
  the live rebind says `cannot bind control/port ...` (`:272`), the
  Modbus surfaces say `cannot bind`. Outcome: keep the non-fatal
  behaviour, document the three-tier story once.

## The env plane — the same env layer everywhere

- **the baked default kills two layers, family-wide** — see short
  list item 2 (`audit-forward-format`): the only registry row with a
  non-null string default, and it silences env + config on all four.
  Outcome: the row default goes null; `build_parser` never bakes
  string defaults.
- **the dashboard's LISTEN shadow** — see short list item 3; the
  loader's own comment states the rule its next line breaks
  (`dashboard/lib/options.py:38-43`).
- **the cache's metrics-token ladder** — see short list item 4.
- **the image CMDs pin what the env files advertise** — every
  Dockerfile CMD carries `--listen` (and the cache/fake add
  `--audit-log -`), so `LISTEN`/`AUDIT_LOG` in
  `docker/env/{cache,fake,scraper}.env.example` are inert in the
  images; the Dockerfiles' own comments forbid exactly this for
  `UPSTREAM` (`docker/Dockerfile.modbus-cache:59-62`). Outcome: the
  container defaults move to `ENV` like `UPSTREAM`, or the example
  lines carry a "pinned by the image CMD" note.
- **the fake's env example lags** `[inverter]` — `LOG_LEVEL` was
  missing entirely and the SIGHUP block listed five of the re-read
  envs. Outcome: LANDED 2026-11-10, the family-sweep wave — the
  example gains `#LOG_LEVEL=INFO` and the both-layers notes
  (`PROFILE`/`LOG_LEVEL`), the SIGHUP block honest.
- **the stale env claims in docs** — the cache man advertises a
  `HOST` twin no resolver reads (`cache/lib/man.py:212`); the
  dashboard man/README/docstring still sell `PORT`/`BIND`
  (`dashboard/lib/man.py:136`, `dashboard/README.md:125-127`,
  `dashboard/lib/config.py:6-8`); docs/OPTIONS.md generalizes "the
  bare `$NAME` upper-snake" without the real exceptions
  (`control-port`→`CTL`, `cache-ttl`→`TTL`, dashboard
  `upstream`→`PROM_URL`) and calls `--config` CLI-only while every
  tool honors `$CONFIG` (`common/runtime/daemon.py:47-51`).
  Outcome: the claims match the resolvers; regenerate the pages.
- **the stale `*_FILE` honored records** — five TODO records
  celebrated `CONTROL_TOKEN_FILE`/`METRICS_TOKEN_FILE` twins the
  `-file`-removal wave deleted, and a sixth claimed the removed
  `--control-ops-token-file` flag. Outcome: LANDED 2026-11-10, the
  family-sweep wave — the records carry the reversing pointer (the
  bare env twin with `file:<path>` inside the plain value).
- **the env examples are samples that read as the contract** —
  coverage is 13/50 (cache), 12/39 (scraper), 17/34 (fake), 11/36
  (dashboard) twins; whole blocks (control, dump, ACLs, secrets) are
  absent; headers say "the names are the tool's bare env twins";
  no gate reads the files (`check_options.py` never looks at
  `docker/env/*`). No file lies (every `NAME=` is a real twin).
  Outcome: generate the common block from the registries, or one
  honest header line ("sample, not exhaustive — `show knobs` lists
  all N"), and a coverage gate.
- **the dev wrappers wore prefixes again** — the `dev`/`dev-cli`
  wrappers invented `CACHE_CTL`/`CACHE_UPSTREAM` and siblings,
  violating the bare-name rule. Outcome: LANDED 2026-11-10, the
  family-sweep wave — the wrappers pass the bare twins (`CTL`,
  `UPSTREAM`) through; the dev shell is a surface like any other.
- **`CLI_KEEPALIVE` is unvalidated** — a non-float raises an
  uncaught ValueError traceback (`common/wire/cli.py:356`), unlike
  the family's one-line refusals; documented in two READMEs only.
  Outcome: the one-liner treatment, everywhere it is documented.
- **"empty = unset" means empty string, not blank** — the shared
  Resolver tests `raw == ''` (`common/settings/config.py:112-119`)
  while `resolve_target`/`CONFIG` strip: `LISTEN=' '` is *set* and
  fails validation. Uniform family-wide. Outcome: a docstring
  precision fix (or strip everywhere — pick one).

- **a path marked secret** `[dashboard]` — the registry marks
  `static-dir` and `config-js` `secret: true`
  (`dashboard/lib/options.json`): a directory/file PATH is not a
  secret, but the marking renders them `*** SECRET REMOVED ***` in
  `show config` and refuses their `clear`. Deliberate path privacy or
  a copy-paste — needs a product ruling before touching (the sweep
  left it standing).

## The gates that keep it

- a **concept key** for the knob sweep (near-miss names, tool-absent
  rows) — without it every knob item above re-drifts silently.
- the sweep reads **`defaults.json` defaults** (the dashboard's 16 vs
  64 class) — the tree-honesty half is the **static-defaults gate**
  (`check_options.py`, LANDED 2026-11-10 with the defaults sweep):
  every defaults key some lib/ module reads (a dead letter fails),
  every flag knob's default a tree key or a named no-entry.
- `check_options.py` (or family_drift) diffs the **registry env twins
  against `docker/env/*.env.example`** and the image CMD/ENV lines.
- `lint_texts.py` flags a **literal that equals a leaf** after
  `%`-normalisation.
- the breaking renames (the scraper's `auth-token` → `metrics-token`,
  the unit unification) ship with the **alias map + the migration
  note** in docs/OPTIONS.md, per the `auth` collision ruling.

## Verified aligned (do not re-open)

The shared Resolver and its precedence on all four; the config-script
grammar refusals (one loader, rc 1, identical bytes); the needs-a-value
and restart-note/refusal texts; the auth-first/bad-token/unsigned/bad-mac
ladder; the RBAC refusal text and fail-closed roles; the dump/key
symmetric gate (one reader); the F13↔F21 move-refusal template (the
model); the write-refused line cache↔fake; the control/audit/dump/listen
registry blocks field-for-field; `metrics-acl` + its table row;
`log-level`, `allow-write`, `auth`, `auth-key`, `max-kwp`'s conv+default,
`interval`'s conv+default; all 21 secret rows' secret+hidden+restart
posture; the console banners and the whole ctl/cli UX (one code path);
the wire status alphabet `ok|fail|note|bye` (one producer); the help
renderer, sorting and alias marker; the empty-env unset rule in every
resolver; no shared env_file in any stack; every docker `ENV` line and
compose key a real registry twin.
