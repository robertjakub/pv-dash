# Changelog

The suite versions as one: the number lives in `common/runtime/version.py`
(`version_string()` appends `-<short git>` in a checkout). Dates are the
tagged commits'. The early tags (before 0.1.0) carried per-tool versions —
the dashboard, the scraper and the cache each numbered their own releases
before the repo restructured into one suite.

This file keeps **Unreleased and the current release** only — the release
history (0.4.0 and older) lives in [docs/CHANGELOG.md](docs/CHANGELOG.md).

## 0.4.3 — 2026-11-11
### Changed

- **scripts** — **battery_status is python**: the read-only view moves
  from the sh twin to a stdlib script (the BSD-only `date -j`/`stat -f`
  spellings and the awk/grep field parsing die — the ages read off the
  status file's mtime, the run stamp off the run id, one rendering pass)
  with the shape kept: the aligned label column, the aged `last:` rows,
  the RUNNING block's run/wave/estimate/stats rows, the newest run's
  canceled/finished/no-tally classification. One deliberate behavior
  fix: the newest block FALLS THROUGH to the newest non-slotted run —
  the sh's single candidate made the block vanish entirely whenever a
  live battery owned the newest dir. The runner's START rows join the
  shape too: `eta 207s` renders `eta 3m27s` (the eta history files keep
  their raw-seconds rows for the predictions).

- **tests** — **the suites resolve their scratch from the battery's run
  dir**: every `/tmp/reg_*`-style literal (328 across the nine suites)
  becomes `os.path.join(SCRATCH, …)` off
  `SCRATCH = os.environ['PV_RUN_DIR']` at each suite's gate — the
  per-battery tmp the runner already owns, so the failed-run backups and
  the keep-8 housekeeping sweep the scratch with the run and `/tmp`
  keeps only the daemon-derived unix sockets (the daemons' own
  constants, the suites check those real paths); the runner's copy-time
  `/tmp/` sed retires — the zz_ copy stays for the pgrep tell alone.

- **scripts** — **battery_status ages and aligns its rows**: the
  `last:` row (the slot block's and the newest run's) carries an
  `(Xm Ys ago)` age read off the status file's mtime — say() appends on
  every row and several row shapes carry no HH:MM:SS stamp of their own,
  so the growing age is the tell a suite sits quiet too long; every
  label under `slot<N>` pads to one column (`run:`/`wave:`/`estimate:`/
  `stats:`/`wait:`/`status:`/`last:` — `estimate:` is the longest at 9).

- **scripts** — **the release battery rides the runner**: release.py's
  tests() no longer spawns the suites bare — the legs are
  `scripts/battery.sh full` (the ten at suite defaults) and, for the
  `--tests quick` recovery pair, `--depth full cache-regtest
  scrape-regtest`; the run dir, the tally, the eta history and the
  failed-run backups are the runner's, the battery's rows stream live
  into the release log (a captured 27-minute silence serves nobody), and
  the verdict keys off the runner's new machine exit (0 green, 1 red —
  the tally text stays the human record). The runner gains `--depth
  quick|full` (explicit suite names at the nightly depth — the
  PV_SUITE_PROFILE export and the fuzzes' full spread follow it). The
  break that surfaced it: the fuzz suites' `[iterations] [quick|full]`
  argv outlived release.py's bare `python3 tests/cache-fuzz.py full` leg
  — the 0.4.3 flight died on `int('full')` mid-bump, before its commit.

- **the family** — **the Modbus socket timeout's default lives in the
  protocol tree**: `common/modbus/protocol.json` carries `socket_timeout`
  (3.0 s) and the cache's and scraper's `modbus timeout` knobs ride it —
  the lib/options.py loaders splice the tree's value over the row's
  static default (`apply_socket_timeout` beside `unit_in_range`), the
  registries hand-copy no number, and `check_options` pins the splice
  (the row's default must equal the tree's). The knob's ladder is
  unchanged — flag > env > config > the tree's default, live-settable as
  before; the fake stays server-side (no socket timeout — its face
  timeout is the client idle knob). **docs/common/MODBUS.md is redone**:
  the §9 limits table speaks the post-unification truth and names every
  cell's knob (the fake's 260-PDU/65535-space/unvalidated-unit cells and
  the §1 255-vs-262 drift story are gone), the doubled FC tables are one
  support map (the drifting `file.py:line` refs dropped, the reserved
  row widened to FC13/18/19), §6/§11 say the out-of-range unit ids are
  refused in-band (they claimed the fake never validates — the tree wave
  made it refuse), and the socket timeout's home is documented;
  `common/README.md`'s tree row gains `socket_timeout`. The retired
  OPTIONS.md's dangling references are cleaned (the four per-tool TODO
  records, scripts/README.md's census note, the Unreleased entries).
- **the family** — **the audit line is FLAT KV: the `message=` wrapper word
  is gone.** The detail's KV words ride bare after `hash=` — every word on
  the line is a `key=value` pair (`<stamp> AUDIT application=… tag=…
  instance=… type=… hash=… fc=6 register=47415 value=5 unit=1`). The five
  outer words (`application`/`tag`/`instance`/`type`/`hash`) are reserved —
  the writer drops a detail word spelling one (the boundary the wrapper
  used to give, now enforced at the writer); an empty detail attaches no
  words. **Migrating:** the outer words keep their positions, so
  `scripts/audit_verify.py` and the remote envelopes work unchanged and
  older trails still verify (the hash material is the line's own words) —
  parsers and greps keying on the literal `message=` move to the detail
  keys directly; the graylog kv extractor now sees them as fields
  (`audit_fc`, `audit_register`, …) beside the mapped ones.
- **the family** — **every audit event type now speaks KV** (the pending
  prose pass): the write family describes itself as `fc=`/`register=`/
  `value=`/`unit=` words (`common/modbus/writes.py write_kv` — the logs
  keep the human form), the refusals add `reason=`
  (`too-short`/`write-disabled`/`not-on-write-acl`/`outside-allow-list`/
  `malformed-frame`) with `client=`/`error=`/`exception=` where they
  apply;   `reset` counts `signal=`/`dropped=` (the cache) and
  `pins=`/`coils=`/`overlay=` (the fake); `reload` carries
  `result=`/`error=` (the family's ok/err verdict) plus its payload keys
  (`ranges`+`profile`, `settings`+`changed`, `upstream`, `restored`+`file`,
  `action=exec`+`pid`); `restore` speaks `file=`/`words=`/`settings=`; `reconnect`
  `attempt=`/`total=`/`status=`; the keepalive daemon-exit disconnect
  `reason=daemon-exit`; `acl-file` spells `warn=`; `requests` gains
  `window=`/`recent=`; the fake's START trails `description=` instead of
  a prose tail and the scraper's START spells `unit=`. The breaker:
  trails written by the previous grammar still VERIFY (the chain hashes
  the line as written) — parsers keyed on the old prose shapes need the
  new keys; the graylog pack's GIM mappings key the generic words
  (`type=`/`result=`/`peer=`/…) and hold unchanged.
- **the family** — the audit detail's KV words tighten: a value carrying a
  space now wears single quotes around the WHOLE value (the builders'
  `audit_quote` — the wire's `peer='unix socket'`, the ctl and cli
  `target='unix:…'`, the user-spelled `control=`/`listen=`/`profile=`
  paths), and an explicitly-quoted empty value (`key=''`) reads the same as
  the bare `key=` token — dropped at the writer (an absent pair, not an
  empty one; a bare `=` stays). Inside the quoted values a `\`, `'` and `"`
  ride backslash-escaped (logfmt-style — `audit_escape`; `cmd='set note
  it\'s fine'` can no longer break the quoting), a bare (unquoted) value
  carries no escapes. The trailing empty `message=` lines in old
  rotated backups predate the writer's guard and stay as written. The
  graylog content pack revs to 3 to follow — the `pv-suite audit cmd`
  rule captures across the escaped quotes and unescapes (`\\(.)` →
  `$1`), the kv extractor's bare words ride unchanged.
- **the audit line's `tools=` word renames to
  `application=` and every line gains an `instance=<id>` word** naming the
  writer daemon: the control port when `--audit-instance`/`AUDIT_INSTANCE`
  is unset (unique per host by construction), the override when spelled
  (1-64 characters, letters/digits/`. _ : @ -`; live-settable as
  `audit/instance`, the raw `none`/clear returns to the derived port; the
  ctl and cli clients spell their target's port). The chain key widens to
  the (application, writer, instance) triple — two daemons of one tool
  sharing a trail now verify independently instead of reading as a chain
  break — and the remote envelopes carry the word too (the RFC5424
  SD-ELEMENT's `instance=`, CEF's `cs3Label=AuditInstance`). The forwarded
  `prefix=` SD param and the CEF `AuditPrefix` label rename to
  `application=`/`AuditApplication` with the native word. **Migrating:**
  trails written by the previous grammar read malformed under
  `scripts/audit_verify.py` (the validator speaks the current grammar
  only, as at the KV rename); the Graylog content pack revs to 2 (the
  stream rule keys on ` AUDIT application=`, the GIM rule maps
  `audit_application`, the restart-churn alert groups per application).
- **an out-of-bounds audit rotation env/flag refuses at
  start now** (`AUDIT_FILES`/`AUDIT_MAX_MB` and their flags): the row
  bounds are a spelled configuration error — the one-line refusal, no
  fallback to the default (a value the wire refuses is a value no layer
  keeps; a PARSE stumble still keeps last good, the live
  `set audit-files` semantics unchanged); the argparse flag layer
  carries the row's message now ('argument --unit: unit must be
  1..247, got 300') instead of the bare 'invalid value' wrapper
- **nixos** — **the service modules invert to one freeform `settings` +
  credentials-only secrets** (the settings wave): the ~40 dedicated per-knob
  options are gone
  — `settings` is a freeform string attrset rendered verbatim as
  `NAME=value` into the unit's systemd `EnvironmentFile` (the keys are the
  daemon's bare env twins, unvalidated — the generated docker/env examples
  are the key list), and the units flip `restartIfChanged` (EnvironmentFile
  is start-only; ExecReload keeps the SIGHUP surface). The secrets keep ONE
  dedicated option each, the `<secret>File` form — an absolute path string
  outside the store, mounted via LoadCredential — while the inline value
  options are removed-option tombstones the eval REFUSES ("secrets may not
  be rendered into the world-readable nix store") and a `/nix/store/`-based
  `<secret>File` errors the same way; the module also refuses a secret env
  name inside `settings` (the store env file is world-readable). The
  dashboard renames its old `settings` (the SOLAR_CONFIG attrset) to
  **`solarConfig`** (its `configFile` folds in), keeps **`staticDir`**
  dedicated (the Exec pins the package's own `share/dashboard/static` by
  default), and gains the two missing env twins (`LOG_QUERIES`,
  `CONTROL_LOG_REPLIES` — the registry's last `no-env` rows). The modules
  ship default-free (`package` has no in-repo default — the nixpkgs shape)
  and the flake's `nixosModules` wrappers carry the defaults via `mkDefault`;
  tests/hardening.nix names the packages explicitly and fixes its phantom
  `port` option (`listenPort` now spelled through settings). The gates
  follow: check_options' NIX gate inverts (the structural options + every
  secret row's `*File`, nothing else — NIX_NAMES retired) and
  family_drift's NIXOS sweep shrinks to the structural check;
  nixos/README.md's module story and the three option tables rebuilt.
  **Migrating:** every old option becomes a `settings.<ENV_TWIN>` string
  (`upstream = "..."` → `settings.UPSTREAM = "..."`, `listenHost` +
  `listenPort` → `settings.LISTEN = "HOST:PORT"`), every `<secret> = "value"`
  becomes `<secret>File = "/absolute/path"`, the dashboard's `settings`
  attrset moves to `solarConfig`.
- **docker** — **the env files split by stack copy**: the prod stack reads
  `env/<tool>-production.env` (the cache's REQUIRED —
  `cp ../env/cache.env.example ../env/cache-production.env` — the
  scraper's optional) while the demo keeps `env/<tool>.env`, so one
  checkout runs both stacks without the copies colliding on knobs like
  `UPSTREAM` (the image default `fake-inverter:5502` is the demo's peer;
  the prod copy points at the device). Still ONE generated example per
  tool — the knobs are identical, the header's cp line and the cache
  intro name both copy targets (`gen_examples.py` renders them); the prod
  compose's `env_file:` paths and the docker READMEs follow.

- **docs** — **docs/TODO.md's open items bucket per tool**: the product
  and the security wave group their items under `### SCRAPER` /
  `INVERTER` / `DASHBOARD` / `COMMON` headings (the tag drops where the
  heading carries it) with the spanning items keeping their `[tool]`
  tags under `### CROSS-TOOL`; the comparison themes (the control
  plane, the one-product sweep, the pipeline) stay tag-per-item.
- **docs** — **the family-wide stale-docs sweep**: the pre-KV audit
  transcripts in the cache's and the fake's READMEs rewritten to the
  KV line (`tools=/tag=/type=/hash=/message=`, the `-> ok` arrow
  gone) and the writer-prefix vocabulary re-worded (the shared `cli`
  role, the ctl/cli trails); the secrets-era leftovers fixed (the
  cache README's "the whole surface is live" metrics sentence — the
  listen set is restart-pending and the token startup-only; the
  fake's "the tokens rotate" rows; ACL.md's control row claiming the
  tokens set live; the dashboard's kill switch spelled the canonical
  `set audit disable`); the `extras/examples/` re-home's missed
  pointers repaired (the root README's row + the repo-layout block,
  DESIGN.md's filing table, ACL.md, the cache README, the two usage
  lines in the examples/schema READMEs); nixos/README.md's restart
  list drops the live log level and its option tables carry the
  renamed `modbusAuth`; MODBUS.md speaks set/clear and its
  configuration table's console spellings normalize to the
  registries' live words (`modbus upstream`, `write allow`,
  `acl connect`, …); common/README.md's audit.py row spells the KV
  line shape; the landed items leave docs/TODO.md (the cache's
  metrics-token ladder, the inverter's log-access/local-time rows,
  the dump-interval near-miss clause) and the scraper's env list
  points at the generated env example instead of a stale closed
  list; the per-tool TODOs' dead `docs/NIXOS.md` links repoint and
  the F16 history row carries its re-home pointer; the regeneration
  the waves skipped caught up (the man pages' docs/SECURITY.md
  re-point, the env examples' log-level namespace move).
- **docs** — **the doc set consolidates (one home per story)**: the
  design doc (`docs/DESIGN.md` — the shape in one screen, every doc
  filed by grain, and the docs redo fused in — the map and the redo
  were two indexes of the same set) rides the book beside the index
  with the OPTIONS include page, and the root README's docs/ tree
  slims to it; family-unify retires into the TODO — the one-product
  sweep rides as TODO.md's own theme section (the short list, the
  three planes, the gates that keep it, verbatim), the verified-aligned
  ledger stays the history half (`docs/history/family-unify.md`) and
  the current/history split rule holds; the generated-docs
  inventory hands to scripts/README.md (which gains the missing
  gen_env.py bullet + the page/generator/gate table); the
  MODBUS.md citation repair (the pre-move `docs/ACL.md` spelling); the
  cache README's access-control section collapses its three tellings
  to their homes (the flag table owns the defaults + the inline
  grammar, docs/common/ACL.md owns the family rules) — the ACL.md
  pointer and the cache's four-gates shape stay; the shipped
  knob-table page retires — the knob census's one home is
  `scripts/list_options.py` (the superset: options/show/commands
  rows), the per-tool MANUALs stay the reference, and the only
  generated page without a `--check` gate is gone (gen_options.py
  with it).

- **nixos** — **the Nix tree gets its own home under `nixos/`**: the four
  `package.nix` files move to `nixos/pkgs/<tool>/` (flat, one dir per
  package), the three service modules flatten to `nixos/modules/<tool>.nix`
  (`modbus-scraper.nix`, `modbus-cache.nix`, `dashboard.nix`), and
  `docs/NIXOS.md` becomes **`nixos/README.md`** beside them — the one Nix
  reference living next to the tree it describes. The flake's overlay
  becomes `overlays.pv-suite` (= `default`) carrying **all four packages**
  (the dashboard-only `overlays.dashboard` retires). The per-tool READMEs'
  `## Nix / NixOS` sections retire (the lint_readmes canon loses the
  heading), the flake's packages/overlay/nixosModules and the hardening VM
  test follow the new paths, the modules' `package` defaults point at
  `../pkgs/<tool>/package.nix`, and the check_options/family_drift gates
  read the modules from the new home.

- **everywhere** — **`log-level` joins the system/ namespace and the wire's
  node listings speak the console's own words**: the last flat logging knob
  moves to `system/log-level` (the live word is `set system log-level`; the
  flat `set log-level` spelling still reads on the wire and in config
  files — the regtests' stale root/listing pins repaired to the daemon
  truth). `show <node>` and `help <node>` (describe_node) now key the
  knobs' live/alias walk words — the `?` face's golden master, byte for
  byte: `show system` spells `log-replies` like `show system ?`, the
  cache's bare `show` folds `cache-ttl` into the `show cache` report's own
  word, the scraper's folds `inputs-metrics` into `inputs` — the flat
  names stay the wire's answers (the ctls translate the console words when
  they send), and an exact word (a show report's own `cache`) outranks a
  walk-on in the listing exactly as the cli's describe resolves it.

- **everywhere** — **the control exchange's DEBUG line slims, and the
  logging knobs gather family-wide under the system/ namespace**: the
  daemons' debug exchange line carries the command and the outcome status
  only (`show config -> ok`) — the reply text stays on the client's
  console and joins the line only with the reply-log toggle on. The
  toggle is registry-driven on all four tools (the flag
  `--control-log-replies`, the live word `set system log-replies` the
  ctls and config files translate, the dumps and the reload state carry
  it, `show config` renders it); the fake's `log_exchange` override died
  into the base. `local-time` and `log-access` move to
  `system/local-time` / `system/log-access` and go live everywhere (the
  dashboard's local-time was startup-only, the cache's log-access
  unhides), and the fake gains both rows — its Modbus connects now log
  at DEBUG by default, `set system log-access on` raises them to INFO.
  **The audit trail's writer tags ride one `shared/tags.json`** (the
  texts loader's tree walk; one tag per tool —
  `{"cache": "CACHE", "scraper": "SCR", "inverter": "INV",
  "dashboard": "DSH"}`) — the daemon's line speaks it as `tools=<TAG>`,
  the clients answer with the cli writer role; a deployment renames its
  line tag in one place; a
  malformed file refuses to start. **check_options guards the env
  surface**: no
  tool-tagged env twin (`MCH_*`/`CACHE_*`/…, the retired era — the one
  control env stays the common `CTL`) may return in a registry row or a
  tool's own code. The NixOS modules, READMEs, the MANUALs
  and the man pages follow.   **The audit line itself is KV now**:
  `<stamp> AUDIT tools=<TAG> tag=<writer> type=<type> hash=<12-hex>
  [message=<kv pairs>]` —
  `tools=<TAG>` the always-uppercase tool tag (one per tool in
  shared/tags.json), `tag=daemon|cli` the writer role (the CTL/CLI tag
  split is gone — one client role beside the daemon's, the per-writer
  chain keys on the pair), the `message=` tail rule (its value runs to
  end-of-line), the command's `cmd='…'`/`result=ok|err|…` words replacing
  the `'…' -> ok` arrow form, `reason=unsigned|bad-mac` naming the
  wire-policy refusals, the SHUTDOWN prose heads folded into `reason=`;
  the verifier reads the pre-KV lines beside the new ones (the rotated
  trails verify across the upgrade) and the RFC5424/CEF envelopes'
  extracted fields follow the line's own words. The coverage rider:
  cache-regtest rounds the
  metrics per-IP cap live (`metrics/limits/max-conn-per-ip`) — the drift
  ledger's straggler promise.

- **everywhere** — **every knob's value is judged by its registry row at
  every layer** (the row-driven validation): a row's `conv`, `choices`,
  `min`/`max` and the named `check` validators now gate the flag parser
  (`build_parser` types through `row_value` — a refused flag reads
  `argument --unit: invalid unit value: '999'`), the env and config layers
  (the `Resolver` takes the row and judges the whole contract, keep-last-good
  as before — a value the wire refuses no longer lands from a file), the
  wire's typed fallback (the scraper's `_typed` generalized into the base's
  `apply_typed_key` — a row with no hand branch still validates and records;
  the four tools' `_apply` ladders end on it) and the dump restore (which
  re-applies through `_apply`, so it inherits all of it). The restart fold
  refuses a garbage restore-on-start instead of silently reading False.
  Row fills: the cache's unit/timeout/interval bounds, the scraper's unit
  row now the Modbus range 1..247 (matching the startup's own check — a
  live-accepted 0 or 248 could not survive a restart), max-kwp/max-grid-kw
  minimums, the timeout/interval caps, the dashboard's metrics caps. The
  scraper's `profile`, `metrics-spec` and `metric-prefix` sets rebuild live
  now (the map, the spec and the exported names swap under the poller's
  lock, a bad file rolls back) instead of the silent cfg write. The fake
  accepts the documented `--time auto` at start, applies `--timezone`
  (it resolved and never applied), and a lowercase LOG_LEVEL rides as its
  canonical word instead of the AttributeError traceback; the cache runs
  the token-charset check the family already had; the dashboard's PROM_URL
  must be an http(s) URL with a host and PROM_PREFIX a clean URL path.
  The lint follows: `check_options` resolves every row `check` against the
  tool's CHECKS registry and pins the bounds' sanity (numeric rows only,
  min <= max, no bool bounds).

- **scripts** — **`editor.py` replaces `edit_options.py` and
  `edit_acl.py`** (the one combined terminal editor, the word
  subcommands): the two old editors are gone, every reference
  (the READMEs, the ACL + defaults docs, the lints' and helpers'
  docstrings) points at `editor.py options` / `editor.py acl` now.
  With the merge, the options dialog's `default` field edits for
  real (a conv-typed int/float default no longer crashes the input
  line), `l` lints the file from the list or the form (a `lint` word
  at the line-mode prompt), and the two faces share the shapes —
  the prompts, the completers, the bindings, the pick menus and the
  list walk (Home/End/PgUp/PgDn everywhere).

- **everywhere** — **the external surfaces speak the console spellings**
  (the flat-wire wave's completion): the one-shot ctl translates the
  console's live/alias knob spellings to the flat registry names exactly
  as the interactive cli's — `set acl connect any` through a *-ctl rides
  the wire as `set connect-acl any`, and a piped config script's
  live-word lines work (the bundled confs' paste-through-ctl claim is
  true now). `show config` renders the live paths as words (the config
  files' own spelling — the output pipes back through the console, a ctl
  or a config file), `help config` / `show knobs` and the generated
  MANUAL.md tables spell the console words in their set
  columns (the knob column keeps the flat registry key — the
  identifier), and the state dumps + the reload state files key the live
  paths (`acl/write`, `modbus/interval`) — the flat names read beside
  them on restore and the restart fold folds both, so every era's state
  file still restores. The wire itself stays flat: the daemon's match
  map, the replies, the pointer errors and the bare-show/node listings
  answer the flattened options.json names only.

- **everywhere** — **the wire speaks the flattened registry names
  (breaking)**: every knob's one internal name is now its options.json
  `name` (the flat dashed key — `interval`, `max-conn-per-ip`,
  `write-acl`), and the same flat name is the wire grammar: set/clear/
  show/help take it, the replies render it (`ok interval=2.00s`), the
  restart folds and the bins' configured-value tables (`clear`'s restore
  base) key it, and the bare-show and node listings render it (the
  namespace walk survives as the prose hierarchy — `show audit rotate`
  still answers, listing the flat names). The row's `live` path and
  `alias` become the CONSOLE spellings: the cli completes and accepts
  them beside the flat names and translates to the flat name before it
  sends (`set limits max-conn-per-ip 9` rides the wire as
  `set max-conn-per-ip 9`; the alias `set write acl any` as
  `set write-acl any`) — the wire itself refuses the path words (the
  console and the ctls translate; the config files read both spellings).
  Old state dumps restore: a pre-flat dump's live-path keys fold through
  the registry on the way back in. The acl-table pointer errors, the
  audit-forward grammar text, the F5 tokenless line and the dump-family
  texts spell the flat names; docs/common/MODBUS.md's table column
  re-heads to the console spelling, docs/common/ACL.md and the four
  READMEs follow the flat forms, the man pages + MANUAL.md
  regenerate, the ten suites speak the flat wire. Closes the family-TODO
  item "internally key on the flattened name, not the live".

- **everywhere** — **the family code sweep: the stale code out, the
  similar code into `common/`**: the dead symbols die (the nine
  functions, the unreachable ops-token/rc-2 branches, the orphaned
  `DEFAULT_*` aliases, the unused imports, the `show and clear` prose
  rows and the `unset`-era comments) and the shared shapes land once —
  `registry_view()` (the per-tool lookup tables; the alias fold the
  dashboard and the fake missed — `set audit forward-format` answers
  there now), the statics fold (`load_static_json`/`static_defaults` +
  the clients' wire constants off `common/wire/control.py`), the man
  pages' EXIT STATUS blocks, the fake's `handle()` fork (the base's
  `log_exchange` + `stopper` hooks), the `metric()` exposition helper
  (the 47 hand-paired HELP/TYPE sets render structurally; the fake's
  grid-frequency HELP name mismatch fixed onto the sampled
  `fake_inverter_grid_hz`), the audit start (`audit_params_of` +
  `build_audit`), the base-able control helpers (`clear_overrides` on
  the base — the reload called a method only the subclasses defined —
  the dump tails, the command_help tails, the two connections
  readers, the bind probe), `scripts/tui.py` (the editors' shared
  curses primitives; `edit_options` gains the ^C treatment) and the
  cli pools factory. The wire stops lying: the fake's bad numbers
  answer the family's `must be <what>, got %r` (the Python exception
  text no longer leaks) and bad bools refuse (`on_off`), the scraper's
  `invalid modbus-unit = None` renders the value. Docs follow: the
  shared-layer specs group under `docs/common/` (the ACL map, the
  Modbus reference, the defaults ladder — moved, the links
  re-pointed), the READMEs' flag/default/verb tables match the
  registries, the demo/prod stacks' `AUTH` → `MODBUS_AUTH` (the env
  nothing read — the Modbus hops ship authenticated as documented),
  the man pages + MANUALs regenerate.

- **everywhere** — **the knob defaults move into the registry rows**
  (the one-knob-one-source closure): every non-secret flag knob's
  `lib/options.json` row carries its `default` now — conv-typed JSON,
  edited with `edit_options.py` (the conv-typed parse, the secret
  refused categorically), validated by `check_options` (presence, the
  conv type, the secret ban, and the ops-verbs row pinned to the
  `default_ops_verbs` derivation). The resolvers' last rungs read the
  rows: each `lib/statics.py` builds `DEFAULTS` off the loaded
  `OPTIONS` (`o.static_default` — the argparse-facing default stays
  unset so the flag reads unset), `lib/config.py` reads the
  row-spelled keys (the `DEFAULT_KEYS` rename map dies —
  `DEFAULTS['timeout']`, `DEFAULTS['interval']`, `DEFAULTS['profile']`
  …), and the inverter's manual 45-line `STATIC_DEFAULTS` dict is a
  one-line derivation. `lib/defaults.json` keeps the non-knob statics
  only (the `defaults` dict is gone; the fake's `time_scale_max` and
  the dashboard's `proxy_timeout_s` re-home to the top level — bounds
  with no row of their own). Breaking for the tree readers only: the
  `defaults` key no longer exists in the four files.
- **everywhere** — **the defaults sweep closes: every settable default
  now names its tree entry** — `control_port` `""` (the socket derives
  from the listen port) family-wide, the scraper's `metrics_spec` `""`
  (the built-in `lib/metrics.json` block), the fake's `time` `""` (the
  clock runs) and family-wide `control_ops_verbs` (the concrete csv —
  `show,flush` on the cache, `show` elsewhere; the registry's
  `default_ops_verbs` derivation stays the one truth and a new
  `check_options` row pins the tree literal to it, so the two cannot
  drift). The fake's per-run `seed` stays the one defaultless knob (a
  per-run choice — the gate's `NO_TREE_DEFAULT` map names it and sits
  empty otherwise); the secrets keep the outright ban. The resolvers'
  last rungs read the entries (`DEFAULTS['control_port']` et al.); the
  graduated no-entry reasons left the map, `docs/static-defaults.md`
  is redone to the closed truth and `docs/family-drift.md`'s statics
  matrices carry the four new leaf paths.
- **inverter** — **the grid wander values are knobs and the grid
  quartet graduates into the tree**: `--grid-voltage-wander` (the
  per-phase machine's ±fraction, 0.1 by default, 0 = the flat grid)
  and `--grid-frequency-wander` (the frequency machine's ±Hz clamp,
  0.2 by default) — no env twins (F11, the grid simulator rides the
  flags), live-settable. The defaults.json's `grid` block dies: the
  four flat entries (`grid_voltage`, `grid_voltage_wander`,
  `grid_frequency`, `grid_frequency_wander`) are the rungs' reads,
  `statics.GRID` is gone, and the meter snapshot reports the live
  nominal frequency.
- **cache, scraper, inverter** — **the auth knob is `modbus-auth`**
  (`--modbus-auth` / `MODBUS_AUTH`; the wire spelling stays
  `modbus/auth`) and its default graduates into the trees as
  `"modbus_auth": "none"` — the explicit off; the NixOS modules'
  option is `modbusAuth` and their config lines spell
  `set modbus-auth …` (the old bare `set auth …` lines never matched
  the wire grammar). Breaking: the `--auth` flag and the `AUTH` env
  are gone.
- **dashboard** — **`static-dir` and `config-js` are startup-only
  secrets** (secret, hidden, restart; lives `static-dir`/`config-js`):
  the wire refuses set/show (flag/env/config and restart — the
  dump-key shape), the vocabulary walk never lists them, the
  show-config tree renders the placeholder and the config fold
  re-resolves them at the restart.
- **everywhere** — **four more defaults graduate into the trees**: the
  three Modbus tools' `modbus_profile` `"sun2000"` (the bin's and the
  resolvers' `default_profile_path()` literals die — the bare name
  resolves through the shared profiles/ walk), and family-wide
  `control_trust_uids` `""` (nobody trusted), `dump_path` `""` (the
  state dump off) and `audit_log` `""` (the XDG state home's
  audit.log — the one dynamic default the tree cannot hold verbatim);
  every rung names its tree entry and the gate's `NO_TREE_DEFAULT`
  map shrinks to the common three plus the per-tool extras.
- **cache, inverter** — **two registry renames (breaking on the wire)**:
  the cache's `show write-registers-profile` report is now
  **`write-registers-table`** (live `write/registers/table` — the
  `write-acl-table` naming; the knob's `profile` value and the
  `set write registers profile` spelling stay), and the inverter's
  profile knob's live path moves from the bare `profile` to
  **`modbus/profile`** (the show-config tree nests it under the modbus
  section; the flag/env stay — a pre-rename dump's `profile` key no
  longer restores).
- **everywhere** — **the defaults.json defaults trees carry every value
  knob's default, and a gate keeps them honest**: the resolvers' last
  rung names the tree entry it resolves instead of an inline literal —
  the cache's connect/write/metrics ACLs, the write-register and
  selection words, the audit forward pair and the dump interval; the
  scraper's Modbus offset, metric prefix, the audit forward pair and
  the dump interval; the dashboard's audit forward pair and dump
  interval; the fake's connect ACL, the audit forward pair, the
  timezone. The dead `metrics_server` entries left the cache's and
  the fake's trees (the bool native False is the default), and
  `check_options.py` gains the static-defaults gates: every defaults
  key some lib/ module reads (a dead letter fails), every flag knob's
  default a tree key or a named no-entry (the bool native, the
  empty/derived shapes), and no tree key names a secret — a secret
  never takes a settable default (its default is the None ladder-end,
  banned outright). A later pass put every bool's native False in the
  trees too — the store_true flags resolved their False inline before —
  and the coverage gate dropped its bool-converter exemption, so a bool
  without its tree entry fails like any other knob. The ctl/cli
  connection knobs left the `defaults` tree for the **shared, flat**
  `common/wire/defaults.json` (the cli
  console's keepalive/reconnect pair, the ctl+cli per-command timeout —
  the daemons never read them; the `statics.py` aliases read the shared
  tree, the four per-tool sections are gone). The control session's
  idle cap joined the shared tree as
  `cli_idle_timeout_s`: the shared `ControlServer` reads
  it for `CLI_IDLE_TIMEOUT_S` (was the hardcoded 300 — the
  cache's/scraper's/dashboard's tree entries were dead), the four
  tools' `statics.py` aliases unify to the `CLI_*` names, and the
  per-tool `control_idle_timeout_s` entries are gone. The pre-auth
  line cap joined too as `cli_max_line_bytes_s` (was the
  per-tool `control` section's `line_cap_bytes`, dead on three of four
  daemons) — and the **ctl/cli now enforce the cap at both client
  ends**: an over-long command fails with clean local text instead of
  the daemon dropping the connection, and the reply read refuses to
  accumulate past the cap.
  The cache's
  `cache/ttl` default is
  the flat 30 s (was 3 × the poll interval — the tree's
  `cache_ttl_factor` is gone) and `modbus/auth-upstream`'s default is
  the explicit `none` — both now name their tree entries like the rest.

- **everywhere** — **the four tool READMEs speak the one skeleton, and a
  gate keeps them speaking it**: `scripts/lint_readmes.py --check` pins
  the `##` canon (how it works → usage → configuration → runtime control
  → the tool's own sections in the feature slot → security → testing →
  Nix / NixOS → source layout → license) with a `### Signals` block
  leading the Runtime-control H3s; `family_drift.py` prints the verdict
  beside the ladders it reports. The READMEs came to the canon: the
  scraper gained `Usage` (split from `How it works`) and `Security` (the
  F15 privacy note is the security story), the inverter's `Simulation`
  retitled `How it works` (its `Signals` H2 folded into Runtime control,
  its Docker story into `Usage`), the dashboard's `Features` retitled
  (the `Notes` dissolved into the bullets that already owned their
  claims), and the register/profile reference sections (the cache's two,
  the scraper's four, the fake's two) sit inside the feature slot.

- **everywhere** — **the audit family's sink + rotation knobs are live
  settable on all four tools** (the cache's shape, the family handler):
  `set audit log-file` (the sink swap — a path, `-` for stdout, `none`
  for the remote-only/off fold), `set audit rotate max-size` and
  `set audit rotate files` (the rotation re-chains live), `set audit
  disable` (the kill switch) — the fake and the dashboard catch up with
  the cache and the scraper (`clear <setting>` restores the configured
  value). The state dumps carry the audit rows from ONE shared
  `audit_dump_rows()` shape family-wide — a dump written by the scraper,
  the fake or the dashboard now keeps a live `audit/rotate/daily`
  override (it was silently dropped before), and the trail swap keeps
  the path's case on every tool (the fake's lowercased value spelling).

- **everywhere** — **BREAKING: the wire verbs rename** — `unset <setting>`
  becomes **`clear <setting>`** (restore the configured value) and the
  cache's flush becomes **`request flush cache`** (was `request clear
  cache`). The RBAC vocabulary derives with the rows: the ops default
  policy is `show,flush` on the cache (was `show,clear`) and `show`
  elsewhere; a stored `show,clear` policy now VALIDATES but names
  `clear` — the setting-reset — not the flush: re-spell it `show,flush`
  (the release note; the ops shift's flush rides `flush`, its denial of
  the setting-reset is unchanged). The audit trail's COMMAND verb spells
  `clear`/`flush` from the rename on; the ctl/cli completion and the
  word-help follow the registries.

- **everywhere** — **the family-wide documentation regeneration and the
  stale sweep**: every generated surface re-emitted (the
  generated knob census was two waves stale — the audit-forward pair was missing from the
  common-knob census, 29 -> 31), the three tools' `--control-ops-verbs`
  default rows speak the derived policy (`show` — the READMEs claimed
  the family's old `show,clear`; the cache keeps it), the ops-role
  prose (the registries' control-ops-token rows, the control module
  docstrings, the man prose, the wiresec module doc, AUDIT.md's F22
  paragraph) scopes the ops shift to "its policy's verbs" instead of
  the show/clear spelling, and the scraper's set row lists
  `control ops verbs`/`control trust-uids` as the settable knobs they
  now are.

- **everywhere** — **the family-wide code sweep**: the shared live
  knobs (the control plane — the port rebind, the ops policy, the
  trusted peers, the socket group; the audit family's seven swaps;
  the log level; the local-time formatter swap; the dump pair) ride
  ONE body in `common/wire/control.py` now (`apply_family_key`/
  `get_family_key` + the `record_cfg` show-config state write + the
  one `_rebuild_audit`; the four `lib/control.py` copies died — the
  scraper shed ~220 lines, the cache ~190, the dashboard ~130, the
  fake ~110) — the tools' `_apply` route the restart preamble, the
  family handler, then their own branches. `KNOWN_VERBS` derives
  from the registry's command rows (`known_verbs` — the RBAC
  vocabulary is the grammar's rows, one home; the console-eaten
  `exit`/`logout` ride out) and the default ops policy derives with
  it (`default_ops_verbs`: `flush` only where the grammar speaks it —
  the cache starts at `show,flush`, the other three at `show`).
  The wire's refusal texts (the unknown/needs-a-value family, the
  restart-required pair, the secret refusals, the ops-policy
  one-liner, the audit-grammar pair, the interval/timeout ranges,
  the suite-auth key demand, cannot-bind) compose
  `shared/texts.json` — byte-honest transport, the suite pins keep
  their bytes. The drift doc's knobs-deltas table speaks the drift
  (the tools grouped by the value each carries), the docker sweep
  grows the port-map gate (every EXPOSE/CMD/compose port rides a
  registry listen default) and the secret sweep carries the
  per-tool markers verdict.

- **shared** — **the write-acl pair joins the shared homes**:
  `examples/acl-write-registers.json` + `shared/schema/acl-write-registers.schema.json`
  leave the cache tree — the standalone acl file format is family-wide
  (one gate validator in `common/settings/config.py`, the two acl tools,
  the connect kind TODO joins the same format), so the pair ships once,
  beside the ip-prefix pair. The schema's `$id` + description re-point
  and name the shared loader; every `package.nix` installs via the
  `${../examples}`/`${../shared}` interpolations (the packaged `share/`
  layout unchanged); the cache image COPYs the example from the new
  `examples=` named build context (both compose stacks carry it); the
  drift sweep's schema/example tables walk the shared homes.

- **everywhere** — **the control wire's verb walk is one implementation**:
  the family's `command()` grammar (the help/topic ladder, the
  quit/ping keepalives, the set/clear pair, the show reports and the
  show walk, the request namespace, shutdown) rides the base in
  `common/control.py` — the four per-tool `command()` copies die. The
  tool differences are hooks now: the `SHOW_REPORTS` dict (the tool's
  own show words), `command_tool` (poll now, reset, `request flush
  cache`/`restart`, the cache's `request dump with-cache`), the fake's
  Modbus-write set words (`command_set_special`) and its pin
  bookkeeping (`_after_set`), the show-walk tail and the unknown-word
  spellings, and `RELOAD_CONFIG = False` on the cache and the fake (the
  `request reload-config` row decision stays open in docs/TODO.md).
  The cache reads its live dump path through a `dump_path` property (the
  proxy's value is the one home), `fold_listen` lives in
  `common/daemon.py`, the cache answers an empty `{"cmd": ""}` with
  `err empty command` (its own copy crashed the session) and the fake's
  `clear` of a value that fails to re-apply now answers `err` instead of
  dropping the session.
- **common** — the one registry load the four `lib/options.py` share
  (`load_registry`: the rows, the `show`/`commands` sections, the
  choices/defaults wired per tool) and the metrics endpoints'
  `acl_refused` (the one `connection rejected` log line rides the base —
  the cache's, the fake's and the dashboard's overrides die).

- **everywhere** — **the audit rotation bounds are family-wide**:
  `audit-files` (min 1, max 100) and `audit-max-mb` (min 0, max 1048576)
  carry bounds in all four registries, and the constants live once in
  `common/audit.py` (the audit module's own — `AuditLog` validates, the
  registries repeat, `check_options` cross-checks that they never drift).
  `set audit rotate files 0` refuses identically everywhere
  (`audit/rotate/files must be 1..100 backups`) — the scraper accepted it
  before; the startup planes (flag/env/config) refuse with the clean
  one-liner on all four.

- **common** — **the Modbus accept ladder is one implementation**
  (`common/modbus/server.py` `serve_modbus`): the gate → ACL →
  max-clients → count → thread discipline and the session opener (the
  clients register, the suite handshake, the finally unwind) run shared
  for the cache and the fake — the identical refusal texts and logs at
  both Modbus faces by construction, not convention; the malformed-frame
  policy stays the face's (the cache answers malformed PDUs in-band, the
  fake logs and closes). The fake's Modbus listener backlogs 128 now (it
  listened 16 under a 64 default client limit — the macOS RST shape the
  control servers already learned). The surface sweep nets ~50 lines.

- **everywhere** — **the secret knobs are startup-only, family wide**:
  every secret row (the control tokens, the ops tokens, the metrics
  tokens, the Modbus auth keys, the dashboard's page token, `dump/key`)
  takes the dump-key shape — `live` + `restart` + `hidden` + `secret` —
  and the wire **refuses `set`/`clear`** on it
  (`restart required (startup-only knob)`) before any dispatch: a secret
  never rides the reload state, so it has no pending form — it passes by
  flag/env/config (`file:<path>` included) and a restart, where the
  resolution and the floors (min-16, the scheme-aware key floor,
  ops ≠ admin, the F13 token-mandatory binds) already check it. The live
  rotation branches and their `<set>`/`<set>`-render backs are deleted;
  `help config`/`show knobs` render the secrets
  `startup-only — pass it by flag/env/config (set/clear refuse)` instead
  of a set recipe; the scraper's SIGHUP/`request reload-config` path
  still re-reads the `file:` references, and the dump/reload state files
  are unchanged (the SECRET_REMOVED placeholder can no longer occur —
  no secret can be overridden). The regtests respawn daemons with the
  desired tokens instead of rotating them live.

- **everywhere** — **the /metrics listener is ONE stack, family wide**:
  the fake's and dashboard's own `/metrics` take the cache's
  **`metrics/acl`** (`--metrics-acl`, env `METRICS_ACL`, live `set
  metrics acl` / `clear metrics acl`, the table show `show metrics acl
  table`, the `set metrics acl table` pointer) — the same value grammar
  (`any` the default, `none`, the comma-separated whitelist,
  `file:<path>` the standalone ip-prefix acl file), checked at **accept,
  ahead of the caps**: a client off the ACL is closed without a reply
  and logged `connection rejected: … not on the metrics ACL`; a bad file
  errs with the old gate standing, a group/world-readable acl file warns
  (the log, the audit trail's `ACL-FILE` event, the `set` reply's
  suffix). `common/config.py` gains `resolve_metrics_acl` (the one
  `(gate, warn)` resolver, lifted from the scraper). The shipped example
  + its JSON Schema copy to all four tools:
  `inverter/examples/` + `inverter/schema/` and `dashboard/schema/` are
  new dirs, `dashboard/examples/acl-ip-prefix.json` joins its existing
  examples; the cache's `package.nix` now installs its three
  `schema/*.schema.json` files too (the scraper's were the only ones
  shipped).

- **scraper** — **the legacy flat-spec wire-name fallback retires from
  the exposition**: the poll gauges always render their fixed
  `scraper_*` names (the built-in `scraper` section of
  `lib/metrics.json` merges into every spec, so the `huawei_up`-style
  fallback branches in `lib/server.py` were unreachable dead code); the
  flat-spec acceptance in the loader itself stays (keys verbatim).

- **everywhere** — **the family's data moves out of the package into
  `shared/`**: `texts.json` leaves `common/render/` for the new root
  `shared/` home (the loader reads it one `shared/` segment below the
  directory that contains `common/` — the same walk in the checkout,
  the installed `share/<tool>/` tree and the image's `/pv-suite`;
  `common/` stays pure `.py`), the shared acl schema follows
  (`shared/schema/`), the four `package.nix` installs `shared/texts.json`
  beside `common/` and re-point the schema at `${../shared}/schema`, the
  Dockerfiles + both compose stacks carry the `shared=` named context,
  `shared/README.md` joins, the root README's tree row follows and
  docs/TODO.md gains the schema-every-JSON item.

- **everywhere** — **the ip-prefix acl example + schema are one shared
  pair at the repo root** (`examples/acl-ip-prefix.json` +
  `shared/schema/acl-ip-prefix.schema.json`): the four per-tool copies
  die (the
  fake's `examples/`/`schema/` dirs held only the pair and empty out,
  the dashboard's `schema/` with them),   the four `package.nix` installs
  re-point (`${../examples}`, `${../shared}/schema`) with the packaged
  `share/<tool>/` layout unchanged, `scripts/lint_acl.py`'s bare run
  globs the root `examples/` too, the regtests' `file:` rounds read
  the root file, and the two dirs grow READMEs.

- **everywhere** — **the `--battery` knob retires, battery support is
  always on**: the fake's `--battery`/`--no-battery` pair (and its
  `BATTERY` env twin — the flag and the SIGHUP reload block), the
  scraper's `--battery` (`BATTERY`, live `modbus/battery`, the
  `scraper_battery` gauge and the reserved `battery` compute input — the
  reserved inputs are four now: `pv`, `grid`, `batt`, `soc`) and the
  dashboard's `--battery` (`BATTERY`, live `battery`) are gone; the
  battery registers/metrics/panels simply always serve (a device profile
  without the battery registers keeps the battery metrics absent), the
  fake's battery state machine runs unconditionally and the served
  `config.js` always carries the battery panels. `--battery-kwh` (the
  pack size) stays.

- **everywhere** — **the /metrics default binds renumber from 9350 up,
  one per tool**: the scraper keeps `9350` (its own listen IS the
  /metrics), the cache `9252` → **`9351`**, the fake `9452` → **`9352`**,
  the dashboard `9452` → **`9353`** — the fake and the dashboard SHARED
  `9452` until now (a co-located stack would have collided). The fake's
  and dashboard's metrics toggle live name re-spells to the family form
  **`metrics/enable`** (the cache's spelling; the knob name
  `metrics-server`, the config files and the flag stay flat — the wire
  spells `set metrics enable on/off`).

- **everywhere** — **the control listener is ONE implementation, family
  wide** (the cache's golden master lifted into `common/control.py`):
  `control/port` rebinds the listener live on all four tools (bind-first,
  the failed bind rolls back, the old loop retires by identity, the
  connected sessions keep serving, `off` retires while the sessions keep
  serving, `clear` restores the configured target); the F5 refusal (a
  tokenless TCP control bind) now also guards the **live** rebind, not
  just the start — the fake opts out by posture (`TOKENLESS_TCP =
  'allow'`, F11: a tokenless TCP rebind succeeds there, the regtest pins
  the inverse proof). The fake's `control-port`, `control-ops-verbs`,
  `control-trust-uids`, `control-socket-group` go live (they were
  startup-only); the **dashboard** gains the whole live control family
  (`control/port`, `control/ops/verbs`, `control/trust-uids`) and a NEW
  **`--control-socket-group`**/`CONTROL_SOCKET_GROUP` knob (0660 instead
  of the plain 0600 — the cache's and scraper's alone until now; NixOS
  `controlSocketGroup`). The ops-verbs live name re-spells to the family
  form **`control/ops/verbs`** (the cache's `control/ops-verbs` included;
  the knob name, the config files and the flag stay flat) — the wire
  spells `set control ops verbs <list>`. The four per-tool
  `resolve_control_target`/`parse_control_target` wrappers unify into
  `common/config.py` (one signature: `listen_port` + the socket
  template); the dump/reload state carries the listener on every tool.
  The docker note: a live `set control port off` on a container daemon
  fails the image's HEALTHCHECK by design (it probes the control socket;
  `CTL=0` fails the check).

- **cache** — **`metrics/acl`** (`--metrics-acl`, env `METRICS_ACL`,
  config `metrics_acl`, NixOS `metricsAcl`, live `set metrics acl` /
  `clear metrics acl`): the scraper's metrics/acl wave migrates to the
  cache's own /metrics endpoint — the same value grammar (`any` the
  default, `none`, the comma-separated whitelist, `file:<path>` the
  standalone ip-prefix acl file), checked at **accept** beside the
  connection caps: a client off the ACL is closed without a reply and
  logged `connection rejected: … not on the metrics ACL`. The gate
  re-resolves on every `set`/`clear` and on SIGHUP (a bad file keeps the
  old gate standing; an inline set clears a standing file warning), the
  group/world-readable file warns (the log, the audit trail's `ACL-FILE`
  event, the `set` reply's suffix), **`show metrics acl table`** renders
  the gate as its chain and `set metrics acl table` answers the pointer
  to the report. The accept hooks ride the common MetricsServer now
  (`acl_allows`/`acl_refused` delegate to the instance — the defaults
  admit every peer and close silently, so the dashboard's endpoint is
  untouched).

- **scraper** — **`metrics/acl`** (`--metrics-acl`, env `METRICS_ACL`,
  config `metrics_acl`, NixOS `metricsAcl`/`metricsAclFile`, live `set
  metrics acl` / `clear metrics acl`): one IP-kind gate on the /metrics
  listener doing what the cache's `acl/connect` does on the Modbus
  listener — the value grammar (`any` the default, `none`,
  a comma-separated `IP,IP/prefix, ...` whitelist, `file:<path>` the
  standalone ip-prefix acl file, the shipped
`examples/acl-ip-prefix.json` shape). The check runs at **accept**,
ahead of the connection caps (the ACL first, then the caps): a client
off the ACL is closed without a reply — nothing was parsed to answer — and
  logged `connection rejected: … not on the metrics ACL`. The acl file
  re-resolves on every `set`/`clear` and on SIGHUP (a bad file keeps the
  old gate standing), a group/world-readable file warns (the log, the
  audit trail's `ACL-FILE` event, the `set` reply's suffix), and the
  **`show metrics acl table`** report (show-only) renders the gate as its
  chain — the inline forms as the three fixed chains (`allow 0.0.0.0/0` /
  `deny 0.0.0.0/0` / the whitelist spelled out), a file gate as its own
  rules behind the `% ` desc header with the aligned `# ` comments; `set
  metrics acl table` answers the pointer to the report. The gate
  machinery (`IPGate`, the gate-object validator, the table renderer) is
  one implementation for the family now — `common/config.py` — and the
  ip-prefix example + its JSON Schema ship in the scraper's tree
  (`scraper/examples/acl-ip-prefix.json`,
  `scraper/schema/acl-ip-prefix.schema.json`).

- **scripts** — **`scripts/validate_json.py`**: a stdlib-only JSON Schema
  validator for the shipped spec files (`scraper/schema/`, `cache/schema/`)
  — the draft-2020-12 keyword set the schemas speak (`type`/`enum`/`const`,
  the object/array/string/number bounds, `pattern`/`propertyNames`,
  `allOf`/`anyOf`/`oneOf`/`not`, local `#/...` `$ref` into `$defs`),
  `SCHEMA [FILE|- ...]` argv with `-` the stdin, one error line per
  distinct cause at its JSON pointer (the `oneOf` candidates that `$ref`
  one subschema dedupe to one line), exit 0 every document validates / 1 a
  document failed or would not parse / 2 bad usage or an unusable schema.

- **docs** — **`docs/ACL.md`**: the family-wide ACL map — the one
  rule-chain semantics (the typed gate object, the two matcher kinds, the
  last matching rule deciding, the default deny any), the standalone acl
  file and its tools, the per-tool support (the cache's full story — the
  connect/write IP ACLs and the register gate, the fake's connect-ACL
  mirror in the system grammar, the scraper and the dashboard's deliberate
  no-ACL posture), the system forms spelled as the chains they implement,
  and the boundary to the neighbouring gates that are not ACLs (the suite
  auth, the control-plane RBAC, the connection caps). The book gains the
  `acl.md` page; the audit re-runs at **rev. 18** (the ACL wave walked:
  the posture rows updated — the cache's IP-gated Modbus plane, the
  fake's connect-ACL'd mirror — the F11 closure annotated, the
  control-plane ACL recorded as decided-against-while-loopback), and the
  READMEs/`MODBUS.md` carry the `file:` spellings and the table shows
  (the fake's man SECURITY block drops its stale "no ACL" claim).

- **cache** — the connect and write ACLs read the **ip-prefix acl file**:
  `--connect-acl file:<path>` / `--write-acl file:<path>` (env, config
  and the live `set` the same) load the standalone gate whose root is
  `{"type": "ip-prefix", "rules": [{"type": "allow"|"deny", "prefix":
  "any"|IP|IP/prefix}]}` (the shipped `examples/acl-ip-prefix.json`
  shape) — the chain evaluates in the connect/write logic with the last
  matching rule deciding and a client no rule deciding refused (the
  default deny any; the matcher word `any` is the whole space,
  `0.0.0.0/0`). A missing or bad file refuses the start and answers
  `err` on the wire with the old gate standing, the spelling
  round-trips through the dumps and `clear`, and a group/world-readable
  acl file warns (the log, the audit trail's `ACL-FILE` event, the
  set/clear reply's suffix). The **`show acl connect table` /
  `show acl write table`** reports (show-only) render either ACL as its
  chain, one entry per line: the system forms spell the chain they
  implement — `allow 0.0.0.0/0` (any), `deny 0.0.0.0/0` (none), `deny
  0.0.0.0/0` then one `allow` line per network (the whitelist) — and a
  file gate renders its own rules (the gate desc as the `% ` line, the
  rule descs as aligned `# ` comments). A `set acl connect table` /
  `set acl write table` (the show word typed into the set verb) answers
  the pointer to the report instead of the network-parser error. The
  example **JSON Schemas** ship under each tool's `schema/` dir (draft
  2020-12): `cache/schema/acl-ip-prefix.schema.json` +
  `acl-write-registers.schema.json` + `selection.schema.json`, and the
  scraper's spec gains `scraper/schema/metrics.schema.json` (the
  sectioned form, the legacy flat form, the scraper section's
  mapping-fed shape).

- **profiles** — the **`sun2000_full`** profile: the Huawei SUN2000 full
  register map — 645 numeric registers from the newest official Modbus
  documentation (the SUN2000MA V200R024 Modbus Interface Definitions
  (V3.0) Issue 06, 2025, for the inverter + battery sections, cross-checked
  against the Solar Inverter (SUN2000-L1) Modbus Interface Definitions
  Issue 04 for the meter block 37100-37138 and the optimizer rows): the
  30000 nameplate block, the 32000 realtime block (per-string voltages and
  currents, powers, temperatures, alarms), the 35000 inspection block, the
  37000-38900 LUNA2000 battery blocks (both storage units, the per-pack
  SOC/power/temperature rows, the parallel-system rows), the 37100 smart
  meter block, the optimizer counters, and the 40000-48219 grid-code,
  scheduling and battery-config knobs. The string and multidata rows
  (model name, SN, versions, the curve/TOU period blobs) have no profile
  type and stay out. Fixes against the small `sun2000` (the drift is
  tabulated in `profiles/README.md`): 32066-32068 are the grid line
  voltages (x10), not phase powers; 32080 is the measured AC active
  power, 32078 today's peak; 32086 is the inverter efficiency (the
  shipped insulation row sat on it — the resistance lives at 32088,
  kohm); 37003 is the battery bus voltage (x10), not an efficiency;
  37760 is the system SOC (the reserve knob is 47102); the 37125
  meter-mode mapping re-codes to the docs' `{0: single-phase,
  1: three-phase}`; the PV words, the power factors, the meter frequency
  and the meter energy registers retype to the docs' signed forms. The
  four canonical names (`pv-power`, `grid-power`, `battery-power`,
  `battery-soc`) keep their addresses and scales.

- **cache** — the write gate reads from a **standalone acl file**:
  `--write-registers file:<path>` (env `WRITE_REGISTERS`, config and the
  live `set write registers file:<path>` the same) — the file IS the gate
  object a device profile carries under `acl`/`write` (`{"desc": ...,
  "rules": [{"type": "allow"|"deny", "range": "START:COUNT"}]}`), resolved
  and compiled exactly like the `profile` value: a missing or bad file
  refuses the start, the wire answers `err` with the old gate standing,
  the spelling is the re-appliable dump form, and the
  `show write registers profile` report renders the file's rules like the
   profile's. An example ships as
  `cache/examples/acl-write-registers.json` — the deye
  policy worked out: the clean-slate deny, the allows (the plain range,
  the list), the deny carves and the re-opens —
  and **a group/world-readable acl file warns**: in the log, the audit
  trail's `ACL-FILE` event, and as the suffix of the `set`/`clear` reply
  (the write gate is config trust any local user could have loosened —
  chmod 0600 silences it).

- **cache** — the **`show write registers profile`** report (show-only —
  nothing to set): the write gate answered as its acl chain — `allow any`
  / `deny any`, a range list as its whitelist (`deny any`, then one
  `allow START:COUNT` line per range), and in profile mode the device
  profile's own rules (the gate's `desc` as the `% ` line, then one
  `allow|deny <range> # desc` line per range, the comments aligned). The set/clear verbs match
  the knob rows only, so the report's live path never shadows the knob
  value `profile` — `set write registers profile` keeps setting the knob.

- **scraper** — the cache's **`--control-socket-group`** mirrors over: the
  unix control socket stays `0600` by default and the flag (env
  `CONTROL_SOCKET_GROUP`, config `set control socket-group`) opts into
  `0660` — a local group may speak to the control without being the service
  user; `set control socket-group` re-modes the live socket.

- **scraper** — **`control/port` rebinds the listener live** (`set control
  port` / `clear control port`): the cache's control listener logic ports
  over. The live set swaps the unix/TCP listener by identity — bind-first
  (a failed bind leaves the old listener untouched, the attrs roll back),
  the old accept loop retires, the connected sessions keep serving their
  replies; `off` stops accepting while the sessions keep serving (a later
  set re-enables); a re-set of the running target answers without bouncing
  the socket. The F5 rule holds on the live wire: a TCP rebind without the
  admin token refuses, and `control/token` only drops from a TCP listener
  that is already retired. `show control port` renders the live state
  (`off` when retired — previously the raw configured string), the
  dump/reload state carries an overridden target, and the socket-group
  re-mode only touches a live listener's socket.

- **everywhere** — **the gate's refusal closes with a FIN, not an RST**:
  the cap-503 and the metrics-acl refusals answer before any handler read
  the request — the peer's bytes sat unread in the kernel buffer and the
  close() fired a TCP RST that could overtake the refusal reply in the
  client's receive buffer (the client read the reset, the reply lost —
  the scraper regtest's `metrics acl order` check flaked 3 runs of 4).
  The shared GatedHTTPServer gains `_refuse_close`: half-close so the
  reply drains, then a bounded drain of what the peer sent (a 0.5s wall
  clock, a 0.2s quiet-gap recv timeout, a 1 MiB byte cap — a hostile
  peer must not pin the accept loop), then close. The scraper's
  exposition, the cache's /metrics, the dashboard's server and the
  common metrics skeleton's refusal paths all ride it.

- **scraper** — **the compute metrics are expression-fed**: the spec's
  `metrics` tree (one merged section — the entry's own field says what
  feeds it) carries compute entries with an **`expr`** (and an optional
  **`when`** presence gate) over the poll's inputs, compiled once at
  startup and evaluated per poll (a stdlib-safe whitelist evaluator —
  numbers, the inputs, `+ - * / // % **`, comparisons, `and`/`or`/`not`,
  the ternary and `abs`/`min`/`max`/round`; no attributes, no subscripts,
  one compute metric cannot feed another). An unavailable input (`soc`
  with the battery flag off, a failed read), a division by zero or a
  non-finite result keeps the metric absent for that poll. The
  **`inputs` section declares the vocabulary**: `{name: {help}}` — the
  reserved five (`pv`, `grid`, `batt`, `soc`, `battery`) are declared in
  the built-in **`lib/metrics.json`** (merged into every spec; every
  reserved input must be declared there) with their fixed semantics (the
  sanity checks, the sign flips, the battery-off rules), the spec's own
  "inputs" entries may reword them, the spec's own profile-fed keys are
  inputs too, and an unknown name — referenced or declared — is a clean
  startup error. The
  five classic compute metrics (the export/import split, home consumption,
  the charge/discharge split — `when: battery` keeps the pair absent while
  the battery flag is off) are the built-in eval-table defaults under
  every spec that doesn't define them. The four **canonical metrics** (the
  power math's inputs — `pv_generation_watts`, `grid_net_watts`,
  `battery_net_watts`, `battery_soc_percent`) move into the built-in
  **`lib/metrics.json`** too: always declared, always bound, always
  fetched — the compute inputs' sources — and a spec binding one of their
  registers a second time refuses at startup. The **`show inputs`** report
  lists
  the declared inputs (the reserved five and the spec's declared entries —
  the profile-fed keys stay referenceable without declaring them), each
  bracketed with the spec's own metric whose value it carries, and the
  **`show inputs metrics`** report lists the exported metrics (one
  `[section]`-bracketed line per metric the exposition serves, sorted by
  name); both share the aligned `name  [bracket]  help` shape and cap the
  help at a word-boundary 40 for display (the full text lives in the
  exposition and the docs). The live **`set metrics prefix` re-builds the
  spec** (and the sources) and wakes the poll — the exported names carried
  the startup prefix while the knob claimed live before. The former
  `profile`/`compute` sections are gone — their entries live in
  the one `metrics` tree, and an old-section spec refuses at startup.

- **scraper** — **the default spec resolves from a source checkout**: the
  loader tries the packaged root, then the checkout's `examples/metrics.json`
  (the examples wave moved the bundled sample there, which left a bare
  `python3 ./modbus-scraper.py` failing) — the error names every candidate
  tried.

- **everywhere** — **the control wire's reply status gains `note`** (besides
  `ok` | `fail` | `bye`): the verdict of a command that ran and whose effect
  waits. A `set`/`clear` of a restart-marked knob no longer refuses — the
  value is validated and **recorded as the configured value** (`show` renders
  it, the state dump and the reload state carry it) and the daemon answers
  **`note restart required (startup-only knob)`**; the consoles and the ctl
  one-shot render it with the **`% <message>`** face (a note, not a verdict).
  The whole-daemon reload makes the note true: the fresh process folds the
  reload state's restart-marked overrides into the startup config **before
  any socket binds** (the cache's `system/listen`, `metrics/listen`,
  `modbus/upstream`). A restart-marked *secret* (`dump/key`) still refuses
  outright — a secret never rides the reload state, so a recorded one could
  not survive the restart it promises. The restart-marked rows speak the
  CONFIGURED value now (was: the live rebind on `metrics/listen` — the row
  marked restart again in `dda97b9`); the audit rev. 17 entry follows.

- **everywhere** — **the /metrics token posture is the F13 shape
  family-wide** (the scraper's refusal is the golden master): the cache's,
  the dashboard's and the fake's own endpoints serve tokenless on the
  loopback bind and **refuse a non-loopback bind without a token** — at
  start, on the live enable and on the live `metrics/token` unset (off
  works on the loopback listen now; beyond loopback it refuses); the
  cache's restart-marked `metrics/listen` refuses the pending move beyond
  loopback while the endpoint serves tokenless. The fake retires its
  non-loopback warning (F11's softness stays on the Modbus surface). The
  F6 mandatory-when-on rule retires — the loopback bind is the auth, the
  trust the tokenless unix control socket already assumes;
  docs/AUDIT.md rev. 20 records the move on the F6 closure.

- **dashboard** — **the page takes a bearer token; F21 closes** (the
  audit's rev. 21): `--auth-token`/`$AUTH_TOKEN` (config `auth-token`,
  live `set auth token`, `file:<path>` rides, a secret — it never
  renders) gates every GET on the main listener — the page, the static
  tree, `config.js`, the `/prom` proxy — constant-time, three
  credentials: the `Authorization: Bearer` header, the `auth` session
  cookie (HttpOnly, SameSite=Strict), and the **`?auth=<token>`
  bootstrap** that exchanges the query token for the cookie (stripped
  from the path before anything logs or forwards). The default
  `--bind` is **`127.0.0.1`** now and **a token-less non-loopback bind
  refuses to start** — the loopback dev stays friction-free; the NixOS
  module gains `authToken`/`authTokenFile` (LoadCredential), the demo
  compose binds wide in-container with a generated `page.token` (the
  entrypoint seeds it 0600), the plain-docker env example documents the
  exposure path. Breaking: a `0.0.0.0` bare start now needs the token.

- **cache, scraper, inverter, dashboard** — **`show status` is removed**
  (breaking): the key=value state report dies family-wide — the registry
  rows, the dispatch branches and the `status_report()` bodies are gone.
  Nothing replaces it: the per-setting `show <setting>` reads each value
  back, `show config` renders the effective script, `inspect` is the
  one-page dump (the machines' readings, the pins, the counters included),
  and the set/clear replies carry the compact state summary. The cli
  consoles greet with the two fixed lines now (the banner's status line
  rode the report; the cache's dump-gated completion pools probe
  `show dump path` instead).

- **cache, scraper, dashboard** — **the shipped examples move into
  `examples/` subdirs** (the sample confs, the JSON specs, the token
  placeholder — `cache/examples/`, `scraper/examples/`,
  `dashboard/examples/`): the loaders keep their search paths (in the
  package and the images the files still install beside the scripts, so
  the default `--config`/spec targets stand) — a bare checkout now passes
  `--config`/`$CONFIG` (or the spec/selection/acl paths) explicitly, the
  root no longer pretends to be live config. The packaging, the Dockerfile
  COPYs, the regtests, the lint's bundled-config legs, the book include
  and the docs follow.

- **scraper** — **the wire settings re-spell to the family's path shapes**:
  `set interval` is `set metrics interval`, `set timeout`/`set profile` are
  `set modbus timeout`/`set modbus profile`, the serving caps ride
  `set metrics limits …`, the display caps `set caps max-pv`/`caps max-grid`,
  the audit family `set audit log-file`/`audit rotate …`/`audit disable`,
  the bearer `set metrics auth token` (the flat dashed names still read in
  config files), `--listen` joins the restart-marked knobs, and the display
  groups hand their filing to the node walk (family-wide — the registries
  carry no group fields, `show knobs` renders one headerless dictionary and
  `show <node>`/`?` describe each namespace). The deadwood rows the re-spell
  exposed got their support finished: the bool knobs (`modbus battery`,
  `modbus grid-positive-import`, `local-time`) gained the live set/show/dump
  paths (`local-time` had carried a live name since the note wave and never
  answered either), the audit family is live now the cache's way
  (`audit/log-file` moves the trail — the fresh writer re-chains from the
  file's tail — the rotation rows re-render, `audit/disable` flips the
  kill switch on the shared AuditLog), and the dump carries every live row.

- **everywhere** — **the four console greetings wear one shape** (the
  cache's): the three lines' texts start at one column — the welcome
  line indents into its own block (`%   Welcome to the modbus-cache
  console`), the welcome names the daemon like the prompt does
  (`Welcome to the fake-inverter console` — was "the Fake Inverter
  console"), the status line's segments run in the cache's order —
  upstream, poll health, `running for`, the trailing count — so the
  scraper's `error(s)` and the dashboard's `client(s)` move behind
  `running for` (the dashboard keeps its `upstream (yes)` health
  spelling), and the hint line is the same `TAB completes, ? lists the
  commands, quit leaves` everywhere (the fake's extra `help <setting>`
  clause drops). The fake's README sample follows.

- **scraper, dashboard, inverter** — **`dump/restore-on-start` wears the
  restart mark** (the cache's flip rides `59689b0`): the knob was
  prospective-only (the branch's own comment — the START behaviour this
  session already chose stands), so the set records the pending value and
  answers **`note restart required (startup-only knob)`**; the three
  control planes port the cache's record flow (the gate narrows to the
  secrets, the `_apply` record branch, the `_get` configured-value shadow
  out, the dump overlay, and the mains' pre-decision fold).

- **everywhere** — **the control wire folds the command to the grammar's
  printable 8-bit before it decides** (common/wiresec.py
  `sanitize_command`, in the shared base's frame ladder after the mac
  gate): NFKD so an accented letter loses its mark (`shöw` runs as
  `show`, `m³` as `m3`), then the printable-ascii range only — control
  bytes, DEL and the scripts that do not decompose go. The frame mac
  still certifies the client's exact bytes; the fold is what the role
  gate and the command run. A command that folds away entirely answers
  like the unknown command it is. The dashboard fuzz suite pins the fold
  with a signed utf-8 command on the authenticated session; the
  dashboard man page's control-wire paragraph follows.

- **scripts** — **the GitHub release notes point at the changelog**: the
  body is the one line `For the changes see the /CHANGELOG.md.` (linked
  at the tag) — the changes list stays where it lives, in `CHANGELOG.md`;
  the workflow's extract-the-changelog-section step retires and the local
  `--release` cut speaks the same pointer (the 0.4.0 body — 97 KB of
  pasted section — re-cut by hand).

- **everywhere** — **the shared-code sweep folds the family's doubled
  code back into `common/`**: the new `common/daemon.py` carries the
  daemon-bin scaffolding the four entry scripts carried as near-copies
  (the log setup, the default config path, the SIGHUP/SIGTERM watcher
  threads, the restart-marked fold — the cache's three tool branches
  ride an `extra` hook — the ops-verb policy check and the dump-posture
  line; the cache keeps its `os._exit`-restart installer, the fake its
  SignalBox); `common/modbus` gains `ClientBase` (the connect/close/recv
  plumbing both client legs shared — the cache's session counters ride
  `after_connect`); `GatedHTTPServer` learns the 503 refusal shape
  (`rate_limit_503` + the opt-in `RATE_LIMIT_503`/`gate_log` attrs —
  the metrics servers' silent close untouched); `common/control.py`
  gains the shared `rebuild_audit` (the daily-rotation drift between
  the cache's and the scraper's copies unifies on `prm.get('daily')`);
  `common/options.py` gains `parse_registry_sections` + `option_rows`
  (the four `lib/options.py` loaders shed their ~500 copied parse/build
  lines; two latent drifts fix no-op: the bool-native default skips
  `negates` rows family-wide, and `negates` passes through all four
  loaders); `resolve_profile_file` takes the caller's candidate walk
  (the fake's embedded-copy-first list rides the shared resolver); the
  dump integrity hash is the public `payload_hash`; the fake's
  connect-ACL check calls the shared `acl_admits`.
  `scripts/family_drift.py` joins as the drift workflow — thirteen
  sweep types (the code/surface/knobs passes plus the wire-text, the
  exit/refusal, the rendered-surface, the NixOS-parity, the
  docker/env, the suite-coverage, the F-ledger, the statics, the
  schema/example and the secret-surface sweeps) regenerate the drift
  working paper. Net −719/+318 across 23 files; every
  `--help`/`--man` byte-identical, the option gates clean, the
  ten-suite battery green.

### Added

- **extras** — **the audit trail's Graylog content pack lands under
  `extras/graylog/`** (the new extras/ home for the operator-side packs
  nothing in the build or runtime path consumes):
  `pv-suite-content-pack.json` imports as one unit — the syslog UDP
  input on 1514, three pipeline rules + one pipeline (the `audit_*` KV
  parse, the quoted `cmd=` pick, the **GIM normalization** — the
  Graylog Information Model field names from the Illuminate schema:
  `event_action`/`event_uid`/`event_outcome`/`event_severity(+level)`/
  `event_error_code`/`event_duration`, `source_ip`+`source_port`,
  `destination_ip`+`destination_port`, `user_name`, `user_command`,
  `application_name`, with the source-specific `audit_*` forms staying
  beside), the five dedicated Audit streams routing on the raw message
  (remove_matches pulls the trail out of the Default stream) and the
  four event definitions (no notifications attached); the README
  carries the import steps and the GIM mapping table, the chain verify
  stays off-box in audit_verify, and the pack is verified by inspection
  only (no Graylog on the dev machine). **`extras/` also takes in
  `alerts/` and the root `examples/`** (the other operator-side packs —
  the packages' `../extras/...` installs, the docker build contexts,
  the docker/NIXOS/shared/scripts README pointers and lint_acl's glob
  follow; the tool-local `examples/` dirs stay with their tools).

- **everywhere** — **the example configuration scripts are GENERATED
  from the registries** (`scripts/gen_examples.py`; `--check` gates the
  drift — the env generator absorbed the surface, `gen_env.py` is
  gone): every knob the registry declares is in the file now
  (52/41/52/39 — the hand files carried ~30 each), every line
  commented at its default, the console's live-path spelling on each
  `set` line (the file pastes into a ctl unchanged), the buckets under
  the namespace nodes' help, the restart-marked and secret rows marked,
  the credentials in their `file:/run/credentials/<daemon>/<knob>` form
  (a secret never renders inline) and the fake's control-only demo
  machines documented out. The hand files' active lines all spelled
  registry defaults (two pinned a stale ops-verbs policy) — the docker
  images' effective config is unchanged.

- **docker** — **the env examples are GENERATED from the registries**
  (`scripts/gen_examples.py`; `--check` gates the drift): every env twin the
  four registries declare is in the file now (50/39/34/36 — the hand
  files carried 13/12/18/11), grouped by the knob's namespace node the
  MANUAL.md knobs tables speak, the sample value the image itself runs
  (the CMD flag or an ENV where one pins the knob — `LISTEN`/
  `AUDIT_LOG` carry the pinned-by-the-CMD note, `UPSTREAM`/`SELECTION`/
  `METRICS_SPEC`/`CONFIG_JS` the image-ENV one), the compose stacks'
  environment pins marked per knob (the suite keys, the generated
  tokens), the secrets' lines empty with the `file:<path>` discipline,
  and the dashboard's example gains the twins header it never had. The
  prometheus example stays hand-written (its `PROM_*` knobs belong to
  `entrypoint-prometheus.sh`) — the check cross-checks its names
  against the entrypoint.

- **tests** — **the battery learns quick/full and tells time**: every
  suite takes a `quick|full` profile (`PV_SUITE_PROFILE` — the runner
  exports it per its own profile, the release verification pins `full`)
  — quick runs each suite's core sections and the whole ten finish in
  ~3 minutes, full keeps the nightly depth (the seal, the auth
  handshake, the metrics parity, the rotation and syslog rounds, the
  wide fuzz pools). The suite logs open with `NOTE started at`, close
  with a blank line, `NOTE finished at` and the one verdict, and the
  runner predicts the batch: the per-suite wall times live in
  `eta-<profile>.txt` (rewritten at every tally), the header prints
  the estimate, and every START line carries
  `eta <seconds> (HH:MM)` refined by each actual. The backup archives
  drop the macOS `._` members and a `previous` link names the run
  before `latest`.

- **everywhere** — **a wedged daemon dumps its threads on `SIGUSR2`**:
  every daemon's `main()` registers `faulthandler` for `SIGUSR2` — one
  signal later stderr carries every thread's stack, and the daemon keeps
  running. The dump writes straight to fd 2 (no logging machinery), so it
  answers even when the logging lock is held by a stuck thread. The
  ctl/cli tools are one-shot and skip it.

- **alerts** — **the alert rules pack re-homed to `alerts/`, split per
  exporter**: the F16 pack leaves the scraper tree — one rule file per
  watched exporter (`alerts/scraper.yml`, `alerts/cache.yml`,
  alerts/README.md carries the story + the install map), and each
  exporter's package installs its own half
  (`share/modbus-scraper/alerts.yml`, `share/modbus-cache/alerts.yml`),
  so a cache-only install now carries the cache group. The demo
  Prometheus image bakes both files (the `alerts` build context rides
  `../alerts`; `rule_files:` globs `/etc/prometheus/alerts/*.yml`);
  docs/NIXOS.md lists both packaged copies under `ruleFiles`.

- **common** — **the audit-forward targets (the off-box copy, the F10
  finish line)**: `--audit-forward` spells one target now — `none`,
  `syslog` (the local socket auto-scan), `syslog:/path` (an explicit
  socket, must exist at bind), `udp://host[:514]` (RFC5426 datagrams,
  best-effort) or `tcp://host[:514]` (RFC6587 octet-count framing). The
  remote envelope rides the new `--audit-forward-format` (`rfc5424`, the
  default, or `cef` as an additive wrapping) — both carry the native
  line verbatim plus the prefix + chain hash as extracted fields
  (`[pvDash@1 …]` / `cs1`/`cs2`), so a scheduled search at the collector
  can chain-verify the off-box copy and alert on a break. A send failure
  notes once and the next event re-arms lazily (no threads, no buffers;
  the re-armed note carries the dropped count). `--audit-log none` turns
  the local file off: with a forward spelled that is the remote-only
  mode (the collector is the sole holder, the chain reseeds at GENESIS
  per run), without one the audit is disabled (the state
  `--no-audit-log` spells). The knob stays live family-wide
  (`audit/forward`, `audit/forward-format`); the NixOS modules grew
  `auditForward` (grammar-checked) + `auditForwardFormat`; the
  audit-chain suite grew the collector harnesses (the TCP framing, CEF,
  UDP, the re-arm cycle, the remote-only e2e).

- **common** — **the audit trail forwarding** (`--audit-forward syslog`):
  every trail can mirror its lines to the local syslog socket as they
  land — stdlib `SysLogHandler` on `/dev/log` (or its macOS/journal
  siblings), daemon facility, the bin name as the tag, journald picking
  every line up sealed. The F10 answer, built in: the file sink stays the
  authority (the chain lives there — `scripts/audit_verify.py` walks it
  unchanged), the mirror carries the finished line with its hash, a send
  failure stops the mirroring with one stderr note, and a socket-less
  spelling refuses to start with the family's one-clean-ERROR shape. The
  knob is family-wide (`audit/forward`, live: `set audit forward syslog`,
  `$AUDIT_FORWARD`, the dump/reload story carries it, the ctl/cli clients
  take the flag too), the NixOS modules grew `auditForward`, and the
  audit-chain suite pins the mirror, the fail-stop and the refusals.
  Superseded in shape by the targets entry above (the same knob, the
  full grammar).

- **scraper** — **the alert rules pack ships next to the exporter** (the
  F16 closure): `scraper/alerts.yml`, six alerts in two groups, the
  audit vocabulary's detection half — every annotation names the audit
  events and the log lines the fired page correlates with (the
  `WRITE-REFUSED` events, the SCR/CACHE trails), so detection is wired,
  not just logged. The scraper's group is its poll story
  (`ScraperPollDown`, `ScraperFreshnessGap`, `ScraperExceptionSpike`);
  the cache contributes its side (`CachePollDown`, `CacheAgeSpike`,
  `CacheWriteRefusalBurst`) on a new `modbus_cache_write_refused_total`
  counter on the cache's own /metrics (every gate refusal counts —
  allow-write off, the write ACL, the register allow-list, a malformed
  frame; each is a `WRITE-REFUSED` audit event) and stays silent until
  that endpoint is scraped. The demo image bakes the pack
  (`rule_files:` in `prometheus.yml`, the `alerts` build context), the
  scraper package installs it (`share/modbus-scraper/alerts.yml`),
  docs/NIXOS.md shows the `services.prometheus.ruleFiles` wiring; the
  thresholds assume the default 10 s poll interval.

- **everywhere** — **`request/reload-config` answers family-wide**: the
  config re-read without the exec (the surface the request-namespace
  wave named) now speaks on all four. The cache and the fake gain their
  reloaders (the scraper and the dashboard had it): the cache's
  `apply_reload` is the SIGHUP body extracted — the map swaps atomically,
  the override markers clear, and the dump loop now re-reads the
  configured interval on that path (the wake it was missing) — and the
  fake's re-applies the demo knobs (chaos, peak, strict, time, time-scale,
  profile, log level) over the running machines from the re-resolved
  ladder, the machine pins keeping their markers. The shared tail lives
  once in the control base (`reloaded()`: the markers drop — wholesale,
  or the `applied` keys — and the dump-interval loop re-reads with the
  parked dumper waking), the shared SIGHUP watcher in
  `common/runtime/daemon.py` gained the SIGUSR1 hook and the
  reload-failure audit hook so the cache adopts it wholesale, and the
  spine's reload-config reply catches the resolvers' `SystemExit` now (a
  broken config file answers `err reload failed` instead of killing the
  session). The verb joins `KNOWN_VERBS` on the two tools that lacked it
  (the ops default is then `show,clear` — the verb-rename wave below
  re-derives both: the cache `show,flush`, the fake `show`), the rows
  land beside
  `request/reload` in both registries, and the ctls' helps, the READMEs,
  the man pages and the MANUALs follow.

- **common** — **the flat package organizes into functional subdirs**: the
  17 flat modules split into five subpackages beside the existing
  `modbus/` — `render/` (the static texts + JSON, the man-page builder,
  the time formats), `runtime/` (the daemon-bin ladder, the audit trail,
  the UTC log stamps, the version — whose repo-root walk gained one
  dirname), `settings/` (the option registry, the config plumbing, the
  state dumps + the seal), `wire/` (the ControlServer base + the family
  `command()` walk, the HMAC frames, the peer-cred, both ctl/cli clients)
  and `serve/` (the connection caps, the gated Prometheus skeleton). No
  shim modules — the ~175 import lines spell the full submodule path
  (`from common.wire.control import ControlServer`), the doc prose paths
  swept, the four `package.nix` install every subdir (the modbus
  pattern), `gen_sbom`'s module count walks the package recursively (21
  modules now — `modbus/` was never counted before) and `lint_texts`
  reads the JSON in `render/`. One commit, the common-split precedent
  (ab387d4): a coupled move cannot bisect. Byte-identical `--help`/`--man`
  for all twelve bins, the family chain smoke green (ctl ×4, the metrics
  401→200 gate, the sealed dump round-trip, the cli pty connect), all
  gates + ten suites green.

- **inverter** — **the fake takes the family's config file**: `--config`
  (`$CONFIG`, then `inverter.conf` next to the script) reads the set
  grammar — every line a `set <name> <value>` in the CLI spelling — and
  the bundled sample is `inverter/examples/inverter.conf`; the ladder is
  the family's flag > env > config > the static defaults
  (`inverter/lib/config.py` `resolve_args` writes the effective values
  back onto the args namespace, and the CLI defaults left the parser —
  a static-wired default would shadow the lower layers). The demo twins
  (`CHAOS`, `MAX_KWP`, `STRICT`, `TIME`, `TIME_SCALE`) are ordinary env
  twins now: they apply at start and SIGHUP re-applies them (the
  SIGHUP-only posture is retired, the scrape-regtest check reworked);
  the declared-but-dead twins (`LOG_LEVEL`, `ALLOW_WRITE`,
  `CONTROL_SOCKET_GROUP`, `DUMP_PATH`, `DUMP_INTERVAL`,
  `RESTORE_ON_START`, `METRICS_ACL`) resolve at start too. The pins and
  the machines stay control-wire settings — a config line naming one
  refuses the start. `request reload` saves the reload state beside the
  config script (`RELOAD_NEEDS_CONFIG` true family-wide; the state home
  stays the `--config ''` fallback) and the dry-run line names the
  config path. The image ships the conf (`Dockerfile.fake-inverter`
  COPYs `examples/inverter.conf` onto the built-in target),
  `package.nix` installs it, the man page regenerates (the CONFIG env,
  the conf in FILES) and the MANUAL prose carries the conf story (the
  other three MANUALs' stale bundled-conf paths fixed in the regen).

- **common** — **the static texts are one JSON home** (`common/texts.json`,
  loaded by the new `common/texts.py`): the console's faces and reconnect
  ladder, the ctl's, the four welcome banners, the wire's fixed replies
  (the auth/mac/forbidden family, the reload/dump/restore heads, the
  restart note, the show-config comment) and the daemon bind/startup lines
  resolve through the dotted `T(key)` — byte-identical renders, no text
  changed. The gate `scripts/lint_texts.py --check` fails an unresolved
  reference, an orphan key and a duplicated value (one text, one home);
  the four `package.nix` and the four Dockerfiles ship the JSON beside the
  common modules. The wire's status tokens (`ok`/`err`/`note`/`bye`,
  `daemon-exit`, the `*** SECRET REMOVED ***` placeholder) keep their
  grammar homes — the prose moved, the protocol did not.

- **everywhere** — **the `audit-daily` knob is one shape, family-wide**:
  the UTC-midnight audit-rotation trigger is a live knob on all four —
  the scraper and the dashboard gain the row
  (`--audit-daily`/`$AUDIT_DAILY`, live `audit/rotate/daily`), the fake
  inverter's startup-only row gains its live name (the control learns the
  audit_params + the rebuild, swapping both writers — the control's
  COMMAND trail and the fake's WRITE trail), and the cache's (the only
  live one) stays the template. `set audit rotate daily on/off` switches
  the trigger identically everywhere; the common `rebuild_audit` already
  rode the params.

- **everywhere** — **the env twins are complete**: every knob the docker
  env files need is reachable from an env file. The fake inverter gains
  `$AUDIT_LOG`/`$AUDIT_MAX_MB`/`$AUDIT_FILES`/`$AUDIT_DAILY`/
  `$NO_AUDIT_LOG` and the F13 caps' twins `$MAX_CLIENTS`/
  `$CLIENT_TIMEOUT`/`$MAX_CONN_PER_IP` — and `$LISTEN` finally works (the
  row has declared the env since the serve-address wave; no code read
  it); the dashboard's audit knobs reach the env layer and the config
  script at all (they were flag-only — a config-script
  `set audit log-file …` parsed and was silently ignored) and `log-level`
  gains `$LOG_LEVEL`; `$NO_AUDIT_LOG` is family-wide (the everywhere
  ruling — a journald-only deployment disables the file trail from the
  env file). A knob ruled env-free carries the registry's `no-env` note
  instead of a silent gap (the fake's F11 flags-first demo knobs, the
  dashboard's `log-queries`), rendered in the env-free footnote
  and gated: `check_options` fails a flag row with neither an env twin
  nor a note.

- **everywhere** — **the serve-address word is family-wide**: `show system
  listen` prints the address the daemon serves on, on all four. The cache's
  `system/listen` is the canon; the scraper's listen knob re-spells to it
  (`metrics/listen` stays as the alias — the wire, the config grammar and
  the state files accept both spellings, the canonical one renders), with
  the restart fold that was missing (a `set` + `request reload` now really
  rebinds). The fake inverter and the dashboard trade their custom serve
  knobs for the same knob — the fake's `--host`/`--port` and the
  dashboard's `--bind`/`--port` retire for `--listen HOST:PORT`
  (`$LISTEN`, live `system/listen`, hidden, restart-marked — the argv
  defaults keep their addresses: `127.0.0.1:5502` and `127.0.0.1:8080`);
  the dashboard's `set system listen` refuses a pending move beyond
  loopback while the page serves tokenless (the F21 shape at set time).
  The NixOS module options are `listenHost`/`listenPort` rendering one
  `--listen` (the cache's shape), the docker CMDs and the compose
  `LISTEN` env follow, and the MANUALs, the man pages and the
  drift census ride along.

- **everywhere** — **the `dump-interval` knob is family-wide** (the cache
  was the only holder): the scraper, the fake inverter and the dashboard
  gain the cache's `dump-interval` — `--dump-interval`/`$DUMP_INTERVAL`,
  live as `set dump-interval <s|off>` — and the state dump rewrites
  itself on a timer: the dumper loop parks on the control base while the
  interval is off and a live set wakes it without a restart (the cache's
  golden shape, shared now as `run_dump_interval`); a
  set/show/describe without a dump path answers the family's
  `dump-interval needs a dump path (set dump/path or --dump-path)`, the
  start resolution refuses an interval without a dump path, and the
  SIGHUP/`request reload-config` path re-reads the configured interval
  (the scraper and the dashboard; the fake's SIGHUP layer does not touch
  the dump family — the dump-path parity). The dump-path rows' help
  spells the timer; the MANUALs, the man pages and the
  modules' `dumpInterval` option follow.

- **docker** — **the stacks split by wiring, and both ship
  authenticated**: the new `docker/prod/compose.yaml` is the production
  shape — the same three service images the demo runs (cache + scraper +
  dashboard), no fake, **no in-stack collector** (your Prometheus is
  external and pulls the exporter's `/metrics` — the loopback `9350`
  publish for a host-level collector, or attach it to the network; the
  dashboard's `PROM_URL` points its `/prom` proxy at it), a
  **non-internal** network (`pv-suite`,
  the cache dials the device on the LAN), the cache's `env/cache.env`
  **required** (UPSTREAM is the operator's decision — the image default
  only ever resolves in the demo), the device's own auth
  (`AUTH_UPSTREAM`/`AUTH_UPSTREAM_KEY`, suite or the cache-only
  waveshare) the env file's, and two published ports (the dashboard's
  loopback 8080 + the exporter's loopback 9350). The Modbus hops ship
  authenticated in BOTH stacks now:
  one shared suite key (`/config/modbus-auth.token`, generated into the
  volume on the first seed by whichever Modbus image seeds first — the
  same mechanism as the tokens, a `*.token` placeholder in the fake's,
  cache's and scraper's `config-defaults/`) proven by the PVA1/HMAC
  handshake on every connect — the fake demands it (server), the cache
  proves it upstream and demands it from its own clients, the scraper
  proves it; the `environment:` blocks pin scheme + `file:` reference
  (environment beats env_file — opening a hop is a compose edit, the F7
   shape). The collector (`Dockerfile.prometheus`,
   `entrypoint-prometheus.sh`, `prometheus.yml`) serves the demo stack
   from `docker/` — the reference wiring a prod collector mirrors; the
   demo wiring lives in `docker/demo/` (`compose.yaml` —
  the build contexts re-point one level out — plus its README with the
  demo blockquote + topology); the four tool Dockerfiles and the env
  examples stay at `docker/`, the two entrypoints move to
  `docker/entrypoints/` (the five Dockerfiles' COPY paths + build
  comments carry the prefix) — demo and
  production run identical images, the split is the wiring. The
  READMEs follow: `docker/README.md` turns production-facing (the
  secrets-story section joins), `docker/demo/README.md` carries the demo
  blockquote + the topology, `docker/prod/README.md` the production
  shape (its own topology: the device outside the network, the cache's
  client the one route out).

### Fixed

- **scripts** — **cache-regtest's write-allow-list audit expectations
  speak the flat-KV grammar**: the fc23 refusal row greps
  `fc=23 registers=47999:1 read=47415:2 values=5 unit=1
  reason=outside-allow-list` and the trail check wants
  `reason=outside-allow-list` beside `type=write`/`type=write-refused`
  (the old `message=`-wrapper prose greps died with the audit flat-KV
  wave). The staleness hid since that wave: quick depth raises
  QuickDone before the section, and the direct full runs grepped
  `/tmp/reg_audit_fc4.log` — an append file still carrying a pre-wave
  prose line — so only the release battery's fresh run-dir trails (the
  runner's isolation) exposed it.

- **scripts** — **release.py's version read path follows the runtime/
  split**: `old_version()` still read the flat `common/version.py` home
  the common/ subdir wave (b10995d) had moved into
  `common/runtime/version.py`, so the next release run would have died
  on a FileNotFoundError before its first bump (verified: the read
  resolves 0.4.2 through the new path).

- **everywhere** — **`CLI_KEEPALIVE` is validated**: a non-float value
  raised an uncaught ValueError traceback inside the cli session (the
  enclosing try caught only DaemonExit/ConnectionLost). The env is
  parsed once at startup, before the connect — a bad value is the
  family's one-line refusal (`invalid CLI_KEEPALIVE '…': must be a
  number of seconds (0 = off)`, exit 1) on every console that
  documents the knob, and a blank value now counts as unset (the
  resolver's rule) instead of crashing the float().

- **cache** — **the metrics-token knob resolves through the full ladder**:
  the config layer was missing — a config line `set metrics-token …`
  parsed and was silently dropped (the bin read the flag/env pair only),
  so a token standing in the config file never reached the F13 gate (a
  tokenless non-loopback /metrics refused to start despite the knob's own
  flag/env/config claim). `resolve_config` carries `metrics_token` now
  (flag > env > config, the `file:` form works from every layer), the
  bin's local flag/env read and the post-hoc show-config injection are
  gone — the key rides the resolved dict and the secret placeholder rule
  renders as before.

- **cache, scraper, inverter** — **the Modbus protocol limits are one
  tree**: `common/modbus/protocol.json` (max_pdu **253**, max_registers
  **65536**, max_count 125, max_bits 2000, unit_id_range 1..247) —
  the scraper's 65535 and the fake's 260 PDU were per-tool drift, and
  the cache's top-level `unit_id_range` met the scraper's
  `protocol`-nested one. The cache's `defaults.json` keeps only its own
  `protocol` block (the FC policy + the exception codes), and **every
  tool with a unit knob checks the configured unit against the shared
  range** (the fake's hardcoded 1..247 check reads the tree now — its
  message the family's wording); the cache's and the fake's Modbus
  server faces refuse **out-of-range unit ids in-band** (exception 03 —
  0 is the broadcast id, 248-255 reserved, neither reaches a server);
  `check_options.py` gates the check. The cache's FC policy and
  exception codes joined the shared tree — its `defaults.json`'s
  `protocol` section is gone. So did its `register_types` tree, as
  `registers_type` (the nine type→words entries — the shared tree is
  the one home; the cache's `statics.py`/`config.py` speak
  `REGISTERS_TYPE`).
- **cache, scraper** — **the bool env twins run when the flag is
  absent**: the unguarded `resolve_bool(args.flag, …)` call passed the
  store_true `False` as a given value, the resolver's first layer saw
  the flag set and the env never fell through (`LOCAL_TIME=1`,
  `AUDIT_DAILY=1` and their siblings were dead unless the flag itself
  was given). The call sites pass `or None` now — the flag-absent
  `False` means unset, the env and config layers run, the tree's
  `false` backs the ladder end.
- **everywhere** — **the `audit-forward-format` env and config layers
  come alive on all four tools**: the registry row baked
  `"default": "rfc5424"` onto the flag, so `AUDIT_FORWARD_FORMAT` and
  the config line never fell through (the resolver's first layer saw
  the flag set). The default is the resolver's static rung now — the
  flag layer starts empty, the tree entry backs it
  (`AUDIT_FORWARD_FORMAT=cef` resolves on all four).
- **dashboard** — **the `LISTEN` env is honored again**: the loader
  wired the static listen default onto the flag, the flag was never
  empty and the env layer never ran (the compose `LISTEN:` lines only
  worked because the image CMD pins the flag); the static-defaults
  wiring is gone, the resolver's static rung owns the default.

- **scraper** — **every audit live-set crashed the control handler**
  (`control handler crashed ('disabled')`, the connection closed): the
  subclass wired `audit_params` before `super().__init__()` and the
  base wiped it to `{}` — the family's rebuild read the missing keys.
  `audit_params` rides the base constructor now (the cache's
  post-super proxy alias keeps its shape), so `set audit forward`,
  `set audit rotate …` and `set audit log-file` answer on the scraper
  like on the other three.
- **scraper** — **the registry's two live rows answer**: `set control
 ops verbs` and `set control trust uids` hit no `_apply` branch and
 answered `unknown setting` while the registry marked them live
 (the ops policy and the trusted peers are settable family-wide
 now, through the shared handler).
- **cache** — **a live `set audit log-file -` spells stdout**: the
  cache folded `-`/`stdout` to the XDG state home on the live path
  (the start resolver and the scraper keep `-` raw — AuditLog's
  reading); the raw spelling is the family's.
- **dashboard** — **the live audit-forward/dump-path/dump-interval
  renders ride `show config`** (the show-config-write-back contract
  the other three tools kept — the startup values record them now).
- **dashboard** — **a live `metrics/enable on` honors the configured
  caps**: the control's re-enable read the static `DEFAULT_METRICS_CAPS`,
  silently dropping the startup-configured `--metrics-max-clients`/
  `--metrics-client-timeout`/`--metrics-max-conn-per-ip` (the cache's
  `p.metrics_caps` reading is the family's golden shape — the entry now
  carries the tuple, the rebind and the describe line consume it). The
  dashboard's and the fake's own `/metrics` endpoints take the cache's
  two-hook shape (the `snapshot()` state dict + the `render()` consumer;
  the fake's private `_uptime()` retires into its snapshot), and the
  drift census's three `/metrics` rows read as the one shape they are.
- **tests** — **control-fuzz waits the ports it drives**: the
  SUITE_PORT_BASE rewrite pointed the token/reference/ops sections'
  startup waits at the plain server's already-bound port, so every
  check raced its fresh daemon's python startup and answered
  connection-refused (latent since the battery runner landed; the
  family's startup-weight growth widened the window past losing).
  Each section waits its own daemon's control port now, the cache and
  dashboard fuzzers' shape.

- **tests** — **the suites always run through the battery**: every suite
  refuses a standalone invocation (`PV_RUN_DIR` — the marker
  `scripts/battery.sh` exports; the release verification and the CI
  matrix set it for their legs) — the standalone runs shared /tmp
  scratch across sessions and collided. The battery gained the perf
  stats (per-suite wall time + the battery total in the tally), the
  keep-4 run-dir housekeeping (a busy day piled ~2G), the dead-slot
  scrub with a working `rm -rf` reclaim (the `rmdir` never removed a
  non-empty slot dir — the slots only ever accumulated), and the
  socket-exception rewrite now covers the %-formatted socket names
  (inverter-regtest's mode checks and the dashboard's rebind wait
  crashed on the run-dir rewrite). control-fuzz and
  cache-control-fuzz dial the ports they spawn (the SUITE_PORT_BASE
  sweep had left the token/reference/ops sections raw — the checks
  raced fresh daemons and answered connection-refused), and the three
  regtests took their `SUITE_PORT_BASE` blocks (cache-regtest's
  describe/audit pins included).

- **common** — **the device profiles resolve again from the settings
  subdir**: the common/ subdir split left `_profile_candidates` climbing
  one dirname short (`here` stayed `common/` where the module had moved
  to `common/settings/`) — the bundled profiles fell through to the bare
  name and every bare-name `--config` profile refused ("cannot read
  device profile sun2000.json": the scrape-regtest "never came up", the
  fuzz pairs' connection-refused aborts). The walk climbs to the tree
  root; the packaged share-tree and the one-up suite-tree candidates
  keep their order.

- **scraper** — **a live `modbus/offset` set reaches the client**: the
  registry row said live, but the poller's `apply()` had no `offset=`
  plumbing — a live set wrote the config and changed nothing (the poll
  kept the start offset until a reload). `apply()` takes the offset and
  the `_apply` branch mirrors `modbus/unit`; the row carries the
  ±100000 bounds (the parity with the start-path check).

- **scraper, inverter, dashboard** — **the declared env twins that never
  worked**: the scraper's `$AUDIT_MAX_MB`/`$AUDIT_FILES` were shadowed by
  their static-wired argparse defaults (the resolver never falls through
  a truthy flag value — the rotation defaults leave the parser and ladder
  like every knob); the fake inverter's `$LISTEN` was declared since the
  serve-address wave and read by nothing (the bin ladders
  flag > env > static now); the dashboard's audit knobs were flag-only
  (a config-script `set audit log-file …` was silently ignored). With
  them, the scraper's `clear audit disable`/`local-time`/
  `grid-positive-import` stop answering `unknown setting` (the defaults
  loop covers the live bool rows) and the scraper's audit knobs render
  their live values in `show config` (the `_apply` branches write the
  config back — the stale start values were rendered before).

- **cache, scraper, inverter, dashboard** — **the help surfaces stop
  advertising the removed `show status` word**: the `show` verb's one-line
  help (the `?`/`help` reply and the registry's command row) spelled
  `status` on all four tools; the word dies with the show-status removal
  and the line reads the truth now. With it, the inverter's, scraper's and
  dashboard's registries lose the stray `s)` tails an `edit_options`
  replace path left in the audit/limits/metrics rows ("bind addresss)",
  "rotated audit backups to keeps)", "0 = no size rotations)", ...) — the
  drift doc's knobs finding and its TODO item 1 close with them (the man
  pages re-rendered through).

- **cache, scraper, inverter, dashboard** — **a busy bind answers with one
  line, not a traceback**: a listener dying on `EADDRINUSE` exits with one
  `cannot bind <host>:<port>: <why>` ERROR line, exit 1 — the scraper's
  /metrics bind was unguarded (an OSError traceback) and takes the fold,
  and the shared MetricsServer binds in the caller's context now
  (`start()` = bind, then the serving thread; the failure stashes in
  `bind_error`), so the live `set metrics-server on` on the cache, the
  fake and the dashboard answers the busy port as the err reply instead
  of unrolling a traceback from the serving thread.

- **cache** — **`show config` speaks the live overrides**: the `_apply`
  branches wrote their values into the live objects but never back into
  the resolved config dict the render reads (the `show_config_cfg`
  contract only some branches honoured — unit/auth/timeout and the ACLs),
  so a live `set metrics enable on` rendered `set metrics enable false`
  in the script while `show metrics enable` answered `on`. Every live
  branch writes back now (metrics enable/token/limits, cache ttl, modbus
  interval/read-delay/merge-gap, the limits caps, write allow/registers,
  control port/token/ops/verbs/trust-uids/socket-group, the audit
  path/rotation/disable pair, requests audit, the dump trio, local-time,
  log-access, log-level) and `clear` restores the configured startup
  value through the same branches. The metrics token resolves into the
  config dict at start now too — its `*** SECRET REMOVED ***` row renders
  (the control token's did, the metrics token's never did).

- **cache** — **the `write-registers` `profile`/`file:<path>` markers
  crashed `show config`** (the handler died mid-reply: the renderer
  formatted the marker string as a range list) — the markers render as
  themselves now, the same way `show write registers` spells them.

- **cache** — **`audit/requests` was dead on the wire**: the
  live-rename wave rekeyed the `_apply`/`_get`/dump branches to the live
  names but missed this one (still keyed the dashed `requests-audit`) —
  `set audit requests 120` answered `err unknown setting` and
  `show audit requests` answered `?`; the branches, the dump key and the
  README/man spellings take the live name now.

### Docs

- **docs** — **the Unreleased section consolidates to one block per
  type**: the waves had each appended their own heading (six Changed,
  three Fixed, two Added, two Docs rode the one release section); the
  entries gather under the first heading of their type in
  first-appearance order (Changed, Added, Fixed, Docs), every bullet
  byte-identical and each type's newest-on-top order preserved, and the
  released sections stay untouched (0.4.2 was already one block per
  type, the archive is history).

- **docs** — **AUDIT.md is SECURITY.md (rev. 28) — the one security
  document**: the audit (the F-ledger unchanged since rev. 27) absorbs the
  four tool READMEs' Security sections (which shrink to pointers under the
  same `## Security` heading), a reporting-a-finding note, the one-screen
  posture and the deployment-hardening + supply-chain/ACL summaries beside
  the links (ACL.md, SBOM.md, nixos/README.md stay the mechanism
  references); the citations follow the rename — the wire texts and the
  refusal strings (`shared/texts.json`, the four `control.py`s, the bins),
  the docstrings, the scripts (family_drift's F-ledger sweep reads the new
  path), the extras packs, the book page — and `history/AUDIT.md` gains
  the rev. 28 row.
- **docs** — **AUDIT.md condensed to the current state (rev. 24)**: the
  revision history (rev. 1–24), the closed findings' fix/verification
  detail and the per-finding evidence move to the new
  [AUDIT-history.md](docs/AUDIT-history.md); AUDIT.md keeps the posture,
  the trust boundaries, the controls, the open findings, the closed
  registry and the NIS2/DORA mapping — the docs/TODO pointer re-pointed.
- **everywhere** — **the four `<tool>/MANUAL.md` pages land**: every
  command, knob and show report each tool's control wire answers, the
  kind of each — command, settable (`set`/`clear`, the restart-marked
  knobs noted, the secrets flagged) or show-only (the startup-only
  knobs included) — with the flag/env twin, the value shape and the
  description, one page per tool. GENERATED from the registries by the
  new `scripts/gen_manual.py` (`--check` fails a stale page); the four
  READMEs' control sections point at them.

- **everywhere** — **the family speaks Modbus TCP inverters, not a
  vendor**: the root, scraper, cache, inverter and dashboard README
  intros, the scraper's bin docstring + parser description and the
  man-page title drop the "Huawei SUN2000" definition framing (the
  devices ride on as the shipped-profile examples — the bundled profiles
  cover the Huawei SUN2000 and the Deye hybrids); the
  register-convention citations and the profile descriptions keep the
  provenance, the `huawei_` metric-prefix default stays.

- **everywhere** — **the docs restructure**: all Nix/NixOS documentation
  moved out of the per-tool READMEs into [docs/NIXOS.md](docs/NIXOS.md)
  (the flake and its outputs, the shared module story — the set-grammar
  render, the reload/restart split, the LoadCredential secrets, the
  control-socket paths, the hardening — the three modules' option maps
  REBUILT from the `module.nix` files, whose README lists had gone stale:
  the scraper's still carried the retired register options and the
  "config INI" claim, the cache's predated the metrics ACL and the dump
  knobs — the packages, the fake's no-module note); the four tool READMEs
  re-laid on ONE skeleton (how it works → usage → configuration → runtime
  control → the feature sections → security → testing → nix → source
  layout → license) and shortened — the family-wide stories (the ACL
  grammar, the Modbus handshake, the audit chain mechanics) now point at
  [docs/ACL.md](docs/ACL.md) / [docs/MODBUS.md](docs/MODBUS.md) /
  [docs/AUDIT.md](docs/AUDIT.md) instead of re-running them, the fake and
  the dashboard gain the Testing sections they never had; the profiles
  README tightened on the same shape. The **CHANGELOG split**: the root
  file keeps Unreleased + the current release (0.4.2), the release
  history (0.4.0 and older) moved verbatim to
  [docs/CHANGELOG.md](docs/CHANGELOG.md) (the book's changelog page
  includes both); `scripts/release.py` maintains the split — a release
  moves the superseded release section(s) to the archive and the
  version-sweep's pathspec excludes it.

- **everywhere** — **the man pages carry one section ladder per page
  class**: the daemon pages all run NAME, SYNOPSIS, DESCRIPTION,
  OPTIONS, SIGNALS, CONTROL, SECURITY, ENVIRONMENT, FILES, EXIT STATUS,
  SEE ALSO (the cache's posture prose carves out of DESCRIPTION/CONTROL
  into a new SECURITY; the scraper and the dashboard gain ENVIRONMENT +
  EXIT STATUS, the fake EXIT STATUS), the ctl pages gain the missing
  EXAMPLES / ENVIRONMENT / EXIT STATUS (the cache and the fake had the
  exit codes but no env twins, the scraper and the dashboard had none
  of the three), the cli pages gain EXIT STATUS where missing;
  `common/manpage.py` grows the LADDERS table — `page(kind=...)`
  refuses a page that misses, adds or misorders a section (the prose
  stays per-tool, the ladder does not) — the four ctl EXAMPLES'
  `printf` pipelines render their `\n` for the first time (`\\n` ate a
  character and printed a `0` — latent since the pages were ported),
  and the cache page's three over-long `.BR`/`.I` rows rewrap.
