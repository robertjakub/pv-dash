# Changelog

The suite versions as one: the number lives in `common/runtime/version.py`
(`version_string()` appends `-<short git>` in a checkout). Dates are the
tagged commits'. The early tags (before 0.1.0) carried per-tool versions —
the dashboard, the scraper and the cache each numbered their own releases
before the repo restructured into one suite.

This file keeps **Unreleased and the current release** only — the release
history (0.4.2 and older) lives in [docs/history/CHANGELOG.md](docs/history/CHANGELOG.md).

## Unreleased
### Changed

- **The four cli clients fold into one `pvsuite-cli`** — the per-tool
  `modbus-cache-cli` / `modbus-scraper-cli` / `modbus-fake-cli` /
  `dashboard-cli` bins were four 60-line copies of the same SPEC
  skeleton over `common/wire/cli.py`; one dispatcher
  (`apps/pvsuite-cli.py`) carries the resolution now: the tool comes
  from the invoked name (the installed `*-cli` names stay, as symlinks
  to the dispatcher — the fake's legacy name spells the tool through the
  map) or from the first word (`pvsuite-cli cache|scraper|inverter|dashboard`
  or the daemon name; an explicit word that disagrees with the invocation
  name is refused). The per-tool SPEC — the pools, the labels, the
  defaults, the special renders — moved into each tool's
  `lib/cli_spec.py`; only one tool's `lib/` is ever imported per
  invocation, so the shared `lib` package name never collides. The
  console surface is unchanged (the same prompts, completions, audit and
  exit codes — the SPEC fields are the old bins', verbatim). Packaging
  rides: the four Dockerfiles copy the dispatcher via a new `cli` build
  context (the compose stacks carry it), the nix packages install it by
  its store path under the client's name (the makeWrapper's argv[0]
  inference keeps working), the man pages and MANUALs render unchanged
  from the same per-tool `lib/man.py`, and the drift sweep's
  console-print file list names the dispatcher.

- **The apps/ tree carries no `*.token` examples** — the dashboard's
  `examples/page.token` placeholder is deleted (the only one under
  apps/: the cache, the scraper and the fake-inverter Dockerfiles
  already create theirs at build time), and the dashboard Dockerfile
  follows the family shape (`RUN echo placeholder >
  config-defaults/page.token` instead of copying the file out of
  apps/). No behavior change: the entrypoint materializes any
  `*.token` in config-defaults as a random 0600 value on the first
  seed (the bundled content never reaches the volume), so
  `/config/page.token` — the compose stacks' `AUTH_TOKEN` target —
  seeds exactly as before. The docker README's seeded-artifacts list
  gained the missing `page.token`.

- **The docker env examples carry the full tool names** —
  `docker/env/cache.env.example` → `docker/env/modbus-cache.env.example`,
  `docker/env/scraper.env.example` → `docker/env/modbus-scraper.env.example`:
  every file now spells `<tool>.env.example` exactly (the generator's
  "the env-file stem IS the daemon name" comment finally true for all
  four). The cp hints, the compose `env_file:` paths and the prod
  `-production` copies follow (`env/modbus-cache.env`,
  `env/modbus-scraper.env`, `env/modbus-cache-production.env`,
  `env/modbus-scraper-production.env`) — an operator's copied env files
  need the same rename (`required: false` keeps a stale demo copy
  silently unread; the prod stack refuses to start without its
  renamed file).

## 0.5.0 — 2026-11-13
### Added

- **The docs' links gate** — `scripts/lint/links.py` walks the
  hand-written docs (the generated layer excluded — the MANUALs, the
  drift doc and the SBOM speak their generators' constants) and checks
  three rot classes: every relative markdown link resolves (the
  history records included), every mdbook `{{#include}}` target
  exists, and every repo-rooted path-shaped inline-code token in a
  current doc names something that exists (the history records and the
  per-tool TODO Done records keep their landed spellings; fenced code
  blocks are skipped). It went red on the tree at birth — 60 findings,
  the apps/ move's one-level-short relative links chief among them —
  the class no gate saw (`check_options` gates flag presence in the
  READMEs, `lint/readmes.py` pins the heading canon; neither resolves
  a path). The battery twin rides the check-options pattern:
  `tests/suites/link-check.py` + the runpy wrapper, `links-check`
  leading beside check-options in every profile, the release matrix
  leg with it. The family's remaining rc-1 gates ride beside it as the
  `lint-gates` suite (one check() row each): the acl/options/readmes/
  texts/profile lints, the manual/examples/sbom `--check`s and the
  drift doc's `--check` — every rc-1-on-red check the battery had no
  leg for.

- **The book's Manuals page** — the four generated `<tool>/MANUAL.md`
  pages gather on one book page by `{{#include}}` beside a SUMMARY row
  (the manuals-home ruling: the pages stay per-tool beside their
  registries — the `extras/manuals/` move declined, the operator-pack
  contract holds), and the book's changelog page stops including the
  1671-line archive (the root CHANGELOG only + a link).

- **The scripts/lint/ split** — the four linters move from `scripts/` to
  `scripts/lint/` (`lint_acl.py`, `lint_options.py`, `lint_readmes.py`,
  `lint_texts.py` — the package docstring carries the rule; `lint` was an
  uncontested name, no tool imports it). The linters are IMPORTED, unlike
  the generators: the consumers speak the package spelling
  (`editor.py`'s two imports ride its existing `lib` dance window,
  `family_drift.py`, `option_diff.py`); each mover carries the one
  `sys.path` insert the deeper directory demands and the docstring
  invocations re-point. The drift report's rendered strings re-point
  (docs/family-drift.md regenerated), and the live
  docs' `scripts/lint_*` mentions follow (docs/DESIGN.md,
  docs/SECURITY.md, common/README.md, the scripts README's bullets +
  honest block).

- **The scripts/generators/ split** — the four generators move from
  `scripts/` to `scripts/generators/` (`gen_man.py`, `gen_manual.py`,
  `gen_examples.py`, `gen_sbom.py` — the shipped-artifact renderers
  apart from the gates; `family_drift.py` stays a check). Each mover
  carries the one `sys.path` insert the deeper directory demands; the
  rendered constants speak the new path (the MANUAL.md footers, the env
  examples' and the example confs' GENERATED headers, the SBOM prose's
  link + re-run line), `lib/emit.py`'s stale report takes the caller's
  re-run command, release.yml's SBOM `--check` leg re-points, and the
  live docs' `scripts/gen_*` mentions follow (the per-tool TODO history
  records keep their landed spellings). The man pages, the MANUAL pages,
  the examples and the SBOM pair regenerated — the man pages' diff also
  carries the help-prose catch-up the registries' canon wave had left
  unregenerated.

- **The scripts/lib package** — `scripts/scriptlib.py` grows into
  `scripts/lib/`, the scripts' common lib (the scripts README's TODO
  consolidate list): the flat helpers (`TOOLS`, the row-locator, the
  live-name rule) re-home in `lib/__init__.py` beside `registry.py` (one
  loader home — the wired-rows import dance, the raw `options.json` read
  and the loader's own canon fold, plus the per-tool SURFACES map),
  `walk.py` (the one tree-walk — `family_drift.py`'s `targets()`
  re-homed) and `emit.py` (the emit-and-check doc writer — the
  generators' `--check` rides one helper; the stale report prints a
  unified diff now). The eleven `scriptlib` importers speak
  `from lib import …` and the per-script repo-root path dances die
  (importing the package puts the repo root on sys.path). `lib` is a
  contested name — the per-tool `lib/` packages own it wherever a tool
  root precedes `scripts/` on the path — so `editor.py` opens the house's
  one-module-named-`lib`-at-a-time dance around its imports (the cache's
  gate loader binds first, the window re-binds the scripts' package); the
  rule is documented in `lib/__init__.py`.

- **The tests/lib split** — `tests/harness.py` moves to
  `tests/lib/harness.py` (the third dir of the tests split, the
  suites/battery twin): the twelve wrappers pre-seed `tests/lib` onto
  sys.path, the suite bodies keep the bare `from harness import *`, the
  harness's REPO walk gains the lib/ depth; tests/lib/README.md lands
  and the suites README's pointer follows. The harness then absorbs the
  wire layer the suites carried as private copies — `wait_port`,
  `connect`, `QuickDone`, the `FAILURES` accumulator alias and the
  control-wire clients (`wire_mac`, `signed_wire`, `control_roundtrip`
  with the auth_ports/token parameters, `ops_control_roundtrip`,
  `authed_roundtrip`): the three control-fuzz suites bind thin wrappers
  (which of their ports speak the handshake, the default ops port), six
  suites drop their QuickDone copies, five the FAILURES alias, and the
  hashlib/hmac/socket imports prune where the copies died.

- **The floor blocks + the hidden ruling** — the `inspect` and `request`
  commands gain canon blocks speaking the family floor (the tools keep
  their richer inline tails); the request `restart`/`reload*` commands
  hide family-wide (the canon blocks carry the floor helps + `hidden`,
  the per-tool parentheticals stay inline). The console's / mark (a
  namespace word carrying hidden rows listing marked, the gate
  criterion joining as a second source) flew and retired within this
  cycle: the hidden rows never list again — the pools' rule (the typed
  path still answers; `help request` over a fully-hidden namespace
  answers the node one-liner), and the `gate` flag is gone from the
  canon and the registries.
- **the canon renames to `shared/options.json`** — it carries the
  wiring and the marks, not only the help; every reference moves with
  the rename (the loader, the lints, the editor, the four nix
  packages, the docs).

- **The show/commands canon wave (docs/show-commands-align.md)** — the
  `show` section's last two drifts fold: `metrics-acl-table` speaks the
  long rule-chain spell family-wide (the "(the metrics/acl report)"
  pointer drops) and `version` answers "the suite version" (the per-tool
  nouns were the suite's own words apart — common/runtime/version.py
  numbers one suite). The `set` and `clear` commands speak the cache's
  grammar forms family-wide (`set <setting> <value>` / `clear <setting>`
  — the per-tool example tails drop; the ?-walk and TAB walk the real
  knobs). Four new commands/show blocks (64 canon blocks, 46
  family-wide, 0 dead), four exemptions retired; the commands section's
  remaining drift is the tools' own truth (the fake nouns, the reload
  parentheticals, the inspect dumps) and stays.

- **The key-alignment wave (docs/options-align.md)** — the four option
  registries align on the canon blocks: the audit helps de-tagged (the
  CACHE/SCR/INV/DSH prefixes and the spelled state-home paths drop), the
  client caps speak the cache's generic forms, the metrics-server prose
  names "the tool's own" endpoint (its `$METRICS_SERVER` env twin folds —
  the fake's no-env refusal stays), modbus-auth speaks one scheme text,
  modbus-profile gains the `values` vocab ("the shipped sun2000 profile"),
  restore-on-start loses the daemon/fake/server nouns, control-port and
  dump-path fold the generic forms (the per-tool ctl-name hints stay
  inline). Two new canon blocks: `modbus-interval`, `modbus-timeout` —
  their rows thin-ref. `show config`/`show knobs` hide family-wide. The
  dashboard's `metrics-max-clients` caps at the family 64 (was 16). Twelve
  dead exemptions retired; the block gaps fall 35 → 16, the canon grows to
  60 blocks (42 family-wide, 0 dead).

- The registry's `only` mark — a row may name its one tool
  (`"only": "scraper"`) to pin the knob tool-exclusive: the lint gates
  the mark to a known tool in the file's own registry, refuses it beside
  `shared` (the canon ref is the family-wide mark) and the family pass
  fails any other registry rowing the same name. Unmarked rows stay free
  to grow family-wide; the mark records the deliberate exclusion.
- **tests/battery/battery_kill.py** — the slot killer beside the runner
  and the status view (no wrapper — the docs spelling is
  `python3 tests/battery/battery_kill.py …`): the slots/slot<N> links
  name the live runs; TERM lands first so the runner's own handler
  NOTEs the status and frees the link, the runner's whole descendant
  tree (the suite copy + the daemons it spawned) is collected before
  the first signal and TERMed alongside, and what outlives the grace
  window gets KILLed (the killer NOTEs the status and frees the link
  itself — the same end state a TERMed run leaves). Names take `2` or
  `slot2`; no names = every live slot; nothing live is exit 0.
- **The NixOS modules grow the account pair** — `user`/`group` on all three
  service modules: null (the default) keeps the systemd `DynamicUser`; a
  name renders `User=`/`Group=` instead, and the module creates the account
  (a system user, no login) unless the host already defines the same
  `users.users` entry. `pvsuite`/`pvsuite` is the family's shared identity —
  one owner across the three daemons for the state dumps and the control
  sockets. A `group` without `user` refuses at eval (a group alone would run
  the daemon as root), naming `root` warns, and the modules now install the
  package (the daemon, the `*-cli` client, the man pages) into
  `environment.systemPackages` — the ctl surface is spoken through the cli,
  which fixes the hardening VM test's long-latent
  `/run/current-system/sw/bin/<tool>-cli` calls (no module had ever put the
  cli on the system path, and the tests/nixos/ → nixos/tests/ move had left
  the file's `../nixos/...` self-imports pointing at a nonexistent
  `nixos/nixos/` — CI's `nix flake check --no-build` never caught either).
  The hardening test gains a second node running the cache under
  `pvsuite`/`pvsuite` (User/Group/DynamicUser asserted, the RuntimeDirectory
  owned by the account, the ctl speaking through it).

### Changed

- **The tooling re-files: no wrappers, one gates home** — `tests/`
  root dissolves: the fifteen thin runpy wrappers (`tests/<name>.py`,
  the twin of the ten-plus suites and the two runner entries) die and
  each suite body seeds `tests/lib` itself (the two-line boot — the
  dir must hold no `lib/` of its own, the per-tool `lib` packages never
  shadow the harness); the battery resolves `tests/suites/<name>.py`
  straight off the profile strings (the exists-check + the zz_ pgrep
  copy source), the release matrix legs run
  `python3 tests/suites/<name>.py`, and release.py calls
  `tests/battery/battery.py` — `tests/` root is three directories
  (suites, lib, battery) and the killer's no-wrapper exception becomes
  the universal rule. The gates join one home beside them:
  `scripts/lint/` becomes `scripts/gates/` and absorbs the three root
  gates (`check_options.py`, `validate_json.py`, `audit_verify.py`) —
  everything rc-1-on-red in one dir, the generators and the drift
  workflow stay apart, and the importers re-spell (editor.py's two,
  family_drift.py, option_diff.py; the absorbed gates carry the
  deeper-dir sys.path insert the lints already had). The suites' gate
  argvs, the gate docstrings, the schema descriptions, the graylog
  pack, the module docstrings that name a gate path and the READMEs
  follow; the links gate caught the 29-token tail the hand sweep
  missed (apps READMEs' audit_verify, the specs' suite paths,
  shared/README's trio) — the gate proving its own worth on the wave
  that moved it.

- **The docs redo flies** — the full audit's work order
  (docs/history/docs-redo.md): `docs/common/` becomes `docs/specs/`
  (the dir name collided with the `common/` package it documents; the
  three mechanism specs + their README move as one git-mv home, every
  current pointer re-points, the CHANGELOG's released halves keep
  their landed spellings), the two landed alignment contracts
  (`options-align.md`, `show-commands-align.md`) join
  `docs/history/` (the docs root keeps only current-truth files), and
  every hand-written surface's stale facts fix: the four tool READMEs'
  ~45 relative links re-depth (the apps/ move's uncaught ripple) plus
  their dead source-layout rows and the wrong defaults (the
  dashboard's `--metrics-max-clients` speaks the canon 64, the
  fake's SIGHUP layer spells `MODBUS_PROFILE`), the MANUAL generator
  speaks the one-client truth (the retired `-ctl` bin names drop from
  the four intros), nixos/README's option tables spell
  `modbusAuthKeyFile`, SECURITY's module row spells the subpackaged
  homes and the demo stack counts five services, TODO's landed items
  close out and its dead cites re-point, MODBUS's fake unit row spells
  `--unit` and the profile inventory gains `sun2000_full`, ACL's
  example/schema paths resolve, the SBOM generator's constants and the
  four Dockerfile build headers gain the apps/ depth, the CHANGELOG
  boundary says 0.4.2 and older in both halves, history/AUDIT's title
  runs to rev. 31 — and the examples generator's `--check` drops its
  latent `', '.join(bool)` crash. Verified: `lint/links.py --check`
  green (every link, include and rooted path resolves), all ten gates
  green, the battery ALL PASS.

- **The device profiles fold into `shared/`** — `profiles/profiles/` +
  the README move to `shared/profiles/` and the root `profiles/` dir
  retires (it had been pure data since the lint/ merge took its tools;
  the undecided long game from the shared/ wave closes). The dev-tree
  candidate in both profile walks (`common/settings/config.py`'s shared
  resolver and the fake's own `apps/inverter/lib/profile.py` list)
  re-points at `<tree>/shared/profiles/` — the packaged layouts are
  unchanged, the tools still carry the JSONs flat as `profiles/` beside
  their lib. The three Modbus `package.nix` install lines read the JSONs
  from `../../../shared/profiles`; the docker images COPY them off the
  existing `shared=` named context and the separate `profiles=`
  build context dies (the three Dockerfile headers, the demo and prod
  composes' `additional_contexts`, docker/README's recipes). The SBOM
  speaks the shared data as one component (`pv-suite:profiles` →
  `pv-suite:shared`, the scan dir follows, the pair regenerated). The
  registry help string ("a bare name resolves in shared/profiles/")
  re-renders the MANUAL pages, the conf examples and the env examples;
  the README table/tree, shared/README (the boundary ruling drops the
  profiles exception), extras/README, common/README, docs/SECURITY.md,
  docs/common/MODBUS.md and the scripts README follow. Verified: the
  lint gates + the battery runner green, the nix builds read the new
  path.

- **The lint/ directory speaks one CLI grammar** — profile.py's, all
  five members: `lint` is the default verb and never writes (acl.py's
  and options.py's write-by-default bare runs retire — the write is the
  explicit `format` verb, `format --check`/`--diff` report the canonical
  drift without touching the files), `--check` bare stays the CI gate
  spelling everywhere, and the two members without a renderer
  (readmes.py, texts.py) refuse `format` — their edits stay human. The
  mains return their rc (options.py's `sys.exit(1)` fold, readmes.py's
  findings summary prints to stdout); no consumer of the old spellings
  existed outside the docs' `--check` gates, which all keep working. The
  common code hoists into the sibling `scripts/lint/_common.py` — the
  grammar parser, the terse-ASCII desc check, the START:COUNT range
  matcher (acl.py's spans return folded with profile.py's issues-only
  one), the one-line-object render and the --diff emission — imported
  dual-mode (`lint._common` under the package, `_common` on the bare
  run): the scripts' own `lib` is contested and lint/acl.py executes
  with the cache's binding under editor.py's window, so the sibling
  import never touches it; the contested-lib dances stay local (two
  members, their comments are the value).

- **The profiles' two tools merge into one — and re-home to the lint/
  directory** — `profiles/bin/profile-lint.py` + `profile-format.py`
  become `scripts/lint/profile.py` beside the other linters (lint +
  format, one script: the lint verb is the default and `format` rewrites
  in place — the old invocations keep their behavior and exit codes;
  `format --check`/`--diff` report the canonical-layout drift without
  the write, the acl.py grammar). `profiles/` becomes pure data: the
  hand-written `man/` pair drops (its prose lives in the profiles
  README), the empty `bin/` goes, and the docker images' story is
  untouched (they only ever copied `profiles/profiles/`). The merge
  heals two stale spots the old linter had carried — `lib.statics`'s
  renamed `REGISTER_TYPES` → `REGISTERS_TYPE` import and the missing
  repo-root `sys.path` entry its `common.*` imports need (the old
  script died on both against the current cache lib); the contested-`lib`
  dance runs acl.py's, so the module imports cleanly as `lint.profile`.
  The six shipped profiles lint clean and the format round-trip is
  byte-identical. The SBOM pair regenerates (profiles = the JSONs, the
  tool's row re-points) and the pointers follow (scripts/lint/acl.py,
  docs/common/ACL.md, docs/TODO.md, the scripts README).

- **The four tool trees move under `apps/`** — `cache/`, `scraper/`,
  `inverter/` and `dashboard/` become `apps/cache/`, `apps/scraper/`,
  `apps/inverter/` and `apps/dashboard/`; the repo root now separates the
  products (`apps/`), the shared code (`common/`, `shared/`) and the
  support trees (docker, docs, nixos, profiles, scripts, tests, extras).
  No behavior change: the eight bins' repo-root sys.path bootstrap gains
  one dirname, the scripts' resolvers (scripts/lib/registry.py, walk.py,
  the linters and the generators) carry the `apps/` segment, the suites'
  daemon paths follow, the compose build contexts re-anchor
  (`context: ../../apps/<tool>`, `dockerfile: ../../docker/…`), the Nix
  packages' `src` moves (`lib.cleanSource ../../../apps/<tool>`) and the
  docker image layout is untouched (`/pv-suite/<tool>/` inside the
  container is the image's own). The generated surfaces regenerate (the
  eight man pages, the four MANUAL.md pages, the example confs, the SBOM
  pair, docs/family-drift.md); the READMEs, the book pages and the docs
  re-point; the battery's quick profile passes all green, and the full
  nightly's failures reproduce on the pre-move tree (the similarity-pass
  wave's own — not the move's).

- **The similarity pass's common blocks move home** — the AST similarity
  sweep (scripts/family_drift.py's own pair pass, cross-tool over the four
  libs) pointed the wave and the top pairs moved: the Modbus session
  counters (`exchanges`/`connects`/`errors`/`last_error*`/
  `connected_since`/`bytes_in`/`bytes_out`), `after_connect` and
  `_exchange` hoist into `common/modbus/client.py` `ClientBase` (the
  scraper's docstring had marked the hoist "a move, not a rename" — the
  MBAP head check reads the base's `MAX_PDU` off the protocol tree), the
  per-block `show uplink` tally lands in `common/modbus/blocks.py`
  `block_stat` (the cache's Proxy and the scraper's Scraper kept 0.97-twin
  bodies; `DeviceError`'s exception code is the one pinned spelling), and
  the four `lib/options.py` loaders' shared glue — the defaults.json/
  choices/KNOWN_VERBS fill (`load_options_module`) and the fourteen-line
  registry-view unpack (`unpack_registry_view`) — rides
  `common/settings/options.py`. The drift report regenerates (36 → 32
  cross-file pairs, the four top rows gone); --help/--man byte-identical
  across the eight bins, the lint/generator gates green.

- **The lint/generator stems drop their prefixes** — the eight movers wear
  the directory as the family name: `scripts/lint/`'s `lint_acl.py`,
  `lint_options.py`, `lint_readmes.py`, `lint_texts.py` become `acl.py`,
  `options.py`, `readmes.py`, `texts.py`, and `scripts/generators/`'s
  `gen_man.py`, `gen_manual.py`, `gen_examples.py`, `gen_sbom.py` become
  `man.py`, `manual.py`, `examples.py`, `sbom.py`. The self-references
  follow (the docstring invocations, the message prefixes, `lib/emit.py`'s
  tags + re-run hints), the importers re-point (`editor.py`,
  `family_drift.py`, `option_diff.py`), the rendered constants re-point and
  the generated layer regenerates (the MANUAL footers, the env examples'
  and the example confs' GENERATED headers, the SBOM prose's link + re-run
  line; the man pages byte-identical), release.yml's SBOM `--check` leg
  follows, the drift doc regenerates and the live docs' mentions re-point
  (the scripts README, the tool READMEs' generator lines, the common/shared
  READMEs, the schemas' lint notes, the docs pages; the history records
  keep their landed spellings).

- **BREAKING: the inverter's profile knob speaks the cache's spelling** —
  `profile` becomes `modbus-profile` (the flag `--modbus-profile`, the
  `$MODBUS_PROFILE` env twin, the config-file key, the state-dump keys and
  the defaults follow; the live path `modbus/profile` and the console words
  `set modbus profile …` are unchanged). One flat name per knob across the
  three tools — the cache is the master, the scraper's poll knobs wore the
  prefix first. A stored dump keyed by the old name restores SKIPPED, a
  legacy config line answers unknown setting.

- **BREAKING: the scraper's three /metrics limit knobs speak the cache's
  spellings** — `max-clients`/`client-timeout`/`max-conn-per-ip` become
  `metrics-max-clients`/`metrics-client-timeout`/`metrics-max-conn-per-ip`
  (flags, `$METRICS_*` env twins and the config-script keys follow; the
  wire's `set metrics limits …` paths, the state-dump keys and the defaults
  64/300/0 are unchanged). One flat name per knob across the two tools —
  the cache is the master.

- **BREAKING: the four `*-ctl` clients retire into `*-cli`** — one client
  per tool, the invocation shape picks the mode: command words one-shot
  (`modbus-cache-cli show config` — the raw verdict head prints, exit
  `0` ok / `1` connection error / `2` misuse), piped stdin batch (the
  script lines run in order, the same raw faces), a bare terminal the
  console session. No compat shim; the migration spell is
  `modbus-cache-ctl <command>` → `modbus-cache-cli <command>` (same flags,
  same envs, byte-identical replies — the HEALTHCHECKs, the nix wrappers
  and the docker PATH follow). The console keeps its faces (quiet `ok`,
  the confirm guards, the pager); the one-shot/batch keep the raw bytes
  and audit CONNECT/DISCONNECT only.

- **the registry texts wear one canon** — the family-wide option texts
  (`setting-help`, `help`, `value-help`, `hint`, `values`, and the wiring
  that agrees: `flag`, `env`, `conv`, `min`/`max`, the marks) move to
  `shared/options.json`; a registry row references its block with
  `"shared": "<name>"` and the loader folds the block under the row's own
  fields (the inline field wins — the per-tool override). One edit updates
  every tool's --help, man page, wire help and docs. The accidental
  wording drift aligns to one canon per knob (the audit rotation rows
  speak "the audit trail", the scraper's /metrics caps speak the cache's
  spellings, the fake's `connect-acl` takes the full value grammar, the
  `modbus-unit`/`max-kwp` hints settle). `lint_options --check` gates it
  three ways — every ref resolves (and every block referenced), a
  ≥3-tool byte-identical text must ref, and the gated fields compare
  byte-for-byte across the four registries (the intentional drift rides
  the lint's named exemption list); `family_drift` reports the coverage,
  and `editor.py options` speaks the canon (the ref edits, the
  block-carried fields show marked `(canon)`, the `p` walk proposes the
  ref). The blocks then unify the rest of the row: a block may carry
  every row key but the three placement keys (`name` — the flat name IS
  the block's key; `only`; `shared` — the ref itself), and the carried-
  unanimous fields moved in — the 27 `default`s and the one `alias` ride
  the blocks, the show/commands blocks speak dict blocks (`internal`,
  `hidden` ride beside the description), the raw readers (`gen_manual`)
  resolve the refs, and the manual pages' command tables speak the
  block-carried descriptions their empty cells had lost. Every script is
  aware of the five files: the registries and the canon file route through
  the loaders or fold the refs explicitly (`compare_options`,
  `list_options`, `gen_examples`, `gen_manual`, `family_drift`'s sweeps —
  whose reports read the effective rows now, and the new
  `options_drift` report: the knobs in their folded form against the
  canon — the blocks' adoption census, the inline-wins deviations, the
  block gaps, the promotion list and the shape-field drifts; and the
  new `option_diff` deep diff — one flat name, every tool, every
  section (options, show, commands): the effective rows field by field,
  the canon state and the move verdict that re-uses the lint's own
  gates), the
  linter and the raw editors stay raw by design, `lint_options` renders
  the canon file in the canonical layout (the sections and blocks in
  their landed order, a block's fields in the row rank) beside the four
  registries.

- **the canon sweep's next six names ride the blocks** —
  `modbus-unit`/`modbus-read-delay` (the options rows),
  `uplink`/`uplink-sources` (the show rows) and
  `request-poll-now`/`request/poll` (the command rows) fold from
  `shared/options.json` (the first two-tool partial blocks), and
  `shutdown` joins them family-wide: the four helps align to
  "stop the server (asks to confirm)" and the lint's `shutdown`
  exemption retires. The MANUALs, the man pages and `family_drift`'s
  canon table regenerate (options 43 blocks, show 4, commands 10; the
  exempt count 58 → 57).

- **the docker names speak the daemon** — the fake inverter's image,
  compose service and env file rename to the daemon's own:
  `Dockerfile.modbus-fake-inverter`, service/image `modbus-fake-inverter`
  (the in-image PATH symlinks `modbus-fake-inverter`/`modbus-fake-cli`),
  `env/modbus-fake-inverter.env(.example)`; the cache image's default
  `UPSTREAM` follows the demo peer (`modbus-fake-inverter:5502`) and the
  SBOM's container refs follow. The compose spells become
  `docker compose exec modbus-fake-inverter modbus-fake-cli` and
  `docker compose kill -s HUP modbus-fake-inverter`.

- **the battery runner moves into tests/** — `scripts/battery.py` +
  `battery_status.py` become `tests/battery/battery.py` +
  `battery_status.py` behind thin runpy wrappers `tests/battery.py` /
  `tests/battery_status.py` (the twin of the suite wrappers: the real
  bodies in a subdir, the docs spelling stays flat). The spelling
  everywhere is `python3 tests/battery.py …` — release.py's call, the
  harness refusal message, the five READMEs, docs/options-align.md and
  the suites' docstrings (which still said the retired
  `scripts/battery.sh`); scripts/ keeps the gates + editors only.

- **the shared suite JSONs get a dedicated subdir** — `shared/options.json`,
  `texts.json` and `tags.json` become `shared/suite/{options,texts,tags}.json`
  (`shared/schema/` stays put — the schemas keep their own home and
  README). The loaders re-pin (`common/render/texts.py`,
  `common/settings/options.py`, `common/runtime/audit.py` — the tree-root
  walk now joins the `suite` segment), the lints and the editor
  follow, the four `package.nix` files install the trio to
  `share/<tool>/shared/suite/` and the four Dockerfiles COPY
  `suite/texts.json` to `shared/suite/`; the docs and the per-tool TODOs
  re-spell. The packaged and in-image layouts mirror the checkout again —
  the loaders' walk is unchanged in shape, one segment deeper.

- **the protocol + wire constants join shared/suite/** —
  `common/modbus/protocol.json` becomes `shared/suite/protocol.json` and
  `common/wire/defaults.json` becomes `shared/suite/wire.json` (the
  domain-named home: options / texts / tags / protocol / wire; the four
  `<tool>/lib/defaults.json` statics keep their name and their
  module-relative loads). The two loaders swap beside-the-module opens
  for the tree-root walk (`common/modbus/protocol.py`,
  `common/wire/control.py`), the four `package.nix` files install the
  pair into `share/<tool>/shared/suite/`, and the four Dockerfiles COPY
  them into `/pv-suite/shared/suite/` — which also fixes the images'
  latent absence (the `*.py` COPY globs never carried the two JSONs
  beside their modules, so an in-image import would have died on the
  open). MODBUS.md, the tree notes, the TODOs and the READMEs re-spell;
  the protocol.json row moves from common/README's wire table into the
  shared/README table it belongs in.

### Changed

- **The three compare tools combine into
  `scripts/options_compare.py`** — `compare_options.py`,
  `option_diff.py` and `options_drift.py` were the key-alignment
  waves' three lenses over the registries (the four identity fields,
  the one-name deep diff, the whole-family canon report) with three
  copies of the `--tool` parser, the loader and the field tuples; one
  script carries them as the verbs `family` (the default — the bare
  run keeps the old spelling's shape), `name <flat>` and `drift`, the
  shared `--tool` grammar and the loader deduped, the reports'
  rendered shapes unchanged. The merge repairs what the apps/ move
  broke and nothing noticed: the three tools still resolved
  `<root>/<tool>/lib/options.json` from before the tools moved under
  apps/ — every invocation since died rc 1 on a missing registry; the
  combined script spells `apps/<tool>/lib/options.json` and the
  family lens folds with the tool's own name (the old call passed the
  whole registry path as the canon label). The scripts README's three
  rows collapse into one.

- **The editor moves into its own home** — `scripts/editor.py` +
  `scripts/tui.py` (the shared curses primitives) become
  `scripts/editor/{editor,tui}.py`: the boot's ROOT walk gains the
  third dirname and the sys.path inserts spell the same three homes
  (the repo root, `scripts/` for the lib-and-gates imports, the cache
  root for the one-module-named-`lib` dance), `tui` resolves off the
  script's own dir, and the invocation spelling is
  `python3 scripts/editor/editor.py` — the docs (the specs' two
  editor mentions, the examples README's acl edit, the gate docstring,
  the root tree) follow. The battery's clean-slot re-run on the
  compare-tools commit caught nothing here — the editor has no suite,
  its proof is the boot (the usage render runs the whole import chain).

### Removed

- **`scripts/set_group.py` + `scripts/set_live.py`** — the one-field
  surgical setters (an option row's `group` / `live`), the pre-editor
  era's row surgery. `scripts/editor.py`'s registry dialog edits every
  field they did (`EDITABLE` carries `group` and `live` beside the
  rest) and the compare tools remain for the reads; the scripts README's
  row and the root README's tree line follow.

### Added

- **the four CLIs** — **the console pager**: every console reply prints
  through one door (`page_out`), a text taller than the screen pauses at
  a page (`-- more --`, space = the next page, return = one more line,
  `q` = stop the rest — the command already ran, only the rendering
  stops), `--page-size` / `CLI_PAGE_SIZE` set the page size (`0` = off,
  unset = the terminal height), and the session-local `page` command
  retunes it live (bare = the state, `page N`, `page auto` — never sent
  to the daemon, no registry row); a line wider than the screen shortens
  with ` ...` on the end (the wire and the audit keep the tail), and a
  terminal smaller than 20 rows (`cli_min_height`) or 64 columns
  (`cli_min_width`) refuses the tty edition before the connect — piped
  and scripted runs print whole, byte-for-byte, and never check.

- **scraper** — **`show uplink` + the cache's block poll plan**: the
  profile's source ranges merge into as few Modbus reads as possible
  (`--merge-gap` / `MERGE_GAP`, live `modbus/merge-gap`, default 8,
  `0` = read each range separately — the planner hoisted from the cache to
  `common/modbus/blocks.py`, the cache imports it back unchanged; a failed
  block splits to its leaves so one bad register cannot starve its pooled
  neighbors, and the plan rebuilds live on `set modbus profile`,
  `metrics filter`/`prefix` and `modbus merge-gap`), and the wire gains
  `show uplink` — the cache's gold inverter-link report over the
  scraper's fetch: the session counters (connects, exchanges, bytes,
  errors — the `ModbusTCP` client now keeps the cache's `Upstream`
  counter block) plus one row per poll block with status, latency
  (last/mean/max), failures and last error; **`show uplink-sources`**
  (both tools) spells the register map — one row per polled register
  with its fc, register address, the range that fetches it and the
  source name — while plain `show uplink` stays the lean block-health
  table; `inspect` carries the poll plan. Also fixes the
  fresh-start dump crash:
  the read-delay wave left `read_delay` unresolved in the startup config,
  so any `request dump`/reload state save killed the control session
  (KeyError) — the knob resolves now and `show read-delay`/`clear
  read-delay` answer the configured value.

### Changed

- **cache, scraper** — **breaking: the five poll knobs wear the modbus-
  prefix on the flat spellings** (the flag, the env twin, the config-file
  key, the raw-wire `set <name>` spelling and the resolved key follow;
  the live paths are already `modbus/...`, so the console spellings —
  `set modbus interval`, `set modbus read-delay` — are unchanged):
  `--interval` is `--modbus-interval` (env `INTERVAL` -> `MODBUS_INTERVAL`),
  `--timeout` is `--modbus-timeout` (`TIMEOUT` -> `MODBUS_TIMEOUT`),
  `--read-delay` is `--modbus-read-delay` (`READ_DELAY` ->
  `MODBUS_READ_DELAY`), `--merge-gap` is `--modbus-merge-gap`
  (`MERGE_GAP` -> `MODBUS_MERGE_GAP`) and `--profile` is
  `--modbus-profile` (`PROFILE` -> `MODBUS_PROFILE`) — the flat spellings
  join their `modbus-*` siblings (`modbus-unit`, `modbus-offset`,
  `modbus-auth`); the resolved keys `interval`/`timeout`/`read_delay`/
  `merge_gap`/`profile` -> `modbus_interval`/`modbus_timeout`/
  `modbus_read_delay`/`modbus_merge_gap`/`modbus_profile`, the dump/state
  keys follow the flat names. Anything scripting the old spellings must
  follow; a stored dump carrying an old name's override restores skipped,
  never fatal.
- **cache** — **breaking: `--unit` is `--modbus-unit`** (env `UNIT` →
  `MODBUS_UNIT`, config `set modbus-unit`, the resolved `unit` →
  `modbus_unit`, the dump/state keys follow): the Modbus unit id wears
  the modbus- prefix its siblings on the flag line already carry — the
  cache joins the scraper's spelling (the docs/TODO item's console
  spelling is one knob now). Anything scripting `--unit`/`UNIT`/
  `set unit` must follow.
- **scraper** — **the metrics prefix knob respells plural**:
  `metric-prefix` -> `metrics-prefix` (the flag `--metric-prefix` ->
  `--metrics-prefix`, the env `METRIC_PREFIX` -> `METRICS_PREFIX`, the
  config-file key and the resolved `metric_prefix` -> `metrics_prefix`) —
  the flat spellings follow the live node's own plural (the sibling
  `metrics-spec`, the live path `metrics/prefix`: `set metrics prefix`
  unchanged, the default `huawei` unchanged). A stored dump carrying the
  old name's override restores skipped, never fatal.

- **everywhere** — **`show knobs` renders one flattened table**: the
  group sections (`# --- group ---`) retire — the rows sort by knob name
  under a `knob / flag / env / change` header, and the columns pad to the
  data's own widths (the uplink report's rule; the fixed 23/26/30 gutters
  misaligned on the long flag/env twins). The `help knobs` twin and every
  dictionary pin follow; the substring pins survive untouched.

- **cache** — **the per-client REQUESTS tally knob renames**:
  `requests-audit` -> `audit-requests` (the flag `--requests-audit` ->
  `--audit-requests`, the env `REQUESTS_AUDIT` -> `AUDIT_REQUESTS`; the
  live path stays `audit/requests` — `set audit requests` unchanged —
  and the internal `requests_audit_s` config key stays) — the name now
  reads beside the audit family it joins (`audit-log`, `audit-forward`,
  `audit-requests`). The README's flag row + audit-trail prose, the man
  page and the generated surfaces follow; a stored dump keyed
  `requests-audit` restores SKIPPED (the reply names the new knob) and
  a config file's `set requests-audit` line answers unknown setting —
  re-set once under the new name.

- **cache, scraper** — **the register map consoles as words**: the
  `uplink-sources` show row's live path re-keys to `uplink/sources` —
  `show uplink sources` spells the register map from the ctl/cli (the
  translate layer resolves the words beside the lean `show uplink`
  report; the flat wire word `show uplink-sources` and the
  `ok uplink-sources` replies stay, and the root ? listing folds the
  word into `uplink`'s walk-on — the `cache/all` and `inputs/metrics`
  precedent). The two regtests' root-listing pins drop the dashed word,
  the ctl words-spelling pins land and the caps pins' raw-wire spellings
  go flat (the wire takes the flat names; the words spellings are the
  ctl/cli's translate layer).

- **scraper** — **the sanity caps re-home under modbus**: the live paths
  re-key `metrics/caps/max-pv` -> `modbus/caps/max-pv` and
  `metrics/caps/max-grid` -> `modbus/caps/max-grid` (`set modbus caps
  max-pv 7`, `show modbus caps` walks the node — the `metrics caps`
  spelling answers unknown setting; the flat names `max-kwp`/
  `max-grid-kw` and the flags/env/config keys stay) — the caps police
  the polled readings (a breach fails the poll, /metrics answers 503),
  so the poll side owns them; the re-home retires the dead "the display
  caps the percentages clamp to" prose (nothing clamps — the caps always
  rejected readings), the `modbus/caps` node lands with honest help and
  the metrics node's help drops the display caps. The README's conf
  example + set/clear row, the man prose and the generated surfaces
  follow.

- **cache, scraper, fake inverter — BREAKING: the suite-auth knobs rename**
  (the flag/env twins follow the knob names, the family's `--modbus-*`
  shape): `auth-key` → `modbus-auth-key` (`--auth-key`/`AUTH_KEY` →
  `--modbus-auth-key`/`MODBUS_AUTH_KEY`), and the cache's upstream pair
  `auth-upstream` → `modbus-auth-upstream` (`--auth-upstream`/`AUTH_UPSTREAM`
  → `--modbus-auth-upstream`/`MODBUS_UPSTREAM_AUTH`) and
  `auth-upstream-key` → `modbus-auth-upstream-key`
  (`--auth-upstream-key`/`AUTH_UPSTREAM_KEY` →
  `--modbus-auth-upstream-key`/`MODBUS_UPSTREAM_AUTH_KEY`). The live paths
  stay (`modbus auth key`, `modbus auth-upstream{,-key}` — the console
  spellings parse); the config file, the dumps and the reload state file
  key the new names — **a stored dump's `auth-upstream` override restores
  skipped** (the secrets never ride a dump); the NixOS credential options
  rename with them (`authKeyFile` → `modbusAuthKeyFile`,
  `authUpstreamKeyFile` → `modbusAuthUpstreamKeyFile`, the LoadCredential
  names follow). The flags/envs/config keys re-spell across the three
  registries, the bins, the docker env/compose files and the docs.

- **everywhere** — **the dev launchers stream the audit trail**: every
  `dev` script passes `--audit-log -` — the audit trail rides the dev
  terminal's stdout (the scraper's led the shape; the cache's, fake's and
  dashboard's follow).

- **scraper** — **the cache's read-delay paces the poll, and the poll
  interval joins modbus**: the scraper learns `read-delay`
  (`--read-delay` / `READ_DELAY`, live `modbus/read-delay` — the cache's
  gold shape: seconds between consecutive device reads within a poll
  cycle, the wait before every read but the first, a failed read sweeps
  the next one unpaced; default 0.05, range 0..60, `0` = no wait) and the
  poll interval's live path re-keys `metrics/interval` ->
  `modbus/interval` (`set modbus interval 10` — the query interval is a
  modbus affair; the flat `interval` spelling still resolves). THE
  STATE-FILE MIGRATION: the dump/reload settings key the console
  spellings — a stored dump's `metrics/interval` override restores
  SKIPPED (the reply names it); re-set it once. The README's flag row +
  conf example + set/clear row, the man prose and the suite pins follow.

- **scraper** — **the caps namespace joins metrics**: the display caps'
  live paths re-key `caps/max-pv` -> `metrics/caps/max-pv` and
  `caps/max-grid` -> `metrics/caps/max-grid` (`set metrics caps max-pv 7`,
  `show metrics caps` walks the node — the old `caps` spelling answers
  unknown setting; the flat names `max-kwp`/`max-grid-kw` and the
  flags/env/config keys stay) — the caps clamp the /metrics percentages,
  so the exposition namespace owns them; the `caps` node retires, the
  `metrics/caps` node lands, the metrics node's help names the display
  caps. The README's conf example + set/clear row, the man prose (its
  stale `set/unset` verb spelling fixed to `set/clear` — a leftover from
  the family's unset->clear rename) and the generated surfaces follow.

- **everywhere** — **the ?/TAB pools speak the cache's golden shape**: the
  shared cli `pools()` gains the dump gate — `request dump`, `request
  restore` and the `dump-interval` knob list only while a dump path is
  configured (the welcome probes `show dump-path` first; the cache's
  `request/dump/with-cache` rides the gate's extras param, and the gate
  now keys the console spelling `dump/interval` — the cache's own pool had
  gated the flat name its pool never carried). The cache's cli adopts the
  shared implementation (its private pools retire); the scraper's, fake's
  and dashboard's gain the gate; the scraper's and dashboard's
  `request-dump`/`request-restore` rows take the hidden flag (the fake's
  already rode it) so the wire's `help request` lists the visible children
  only; the spine's `show_root_hidden` default carries the
  dump-interval gate (the cache's override retires); the three simple
  clis' dead `ALIAS_NAMES` imports prune. The suite pins follow (the
  scraper's and the dashboard-fuzz's `help request` expectations).

- **everywhere** — **the dump-interval knob speaks the wire path**: the
  scraper's, fake's and dashboard's `dump-interval` rows take the cache's
  golden live path `dump/interval` (`set dump interval 30` / `show dump
  interval` — the flat `dump-interval` spelling still resolves; the cache
  already rode the path); the MANUALs' wire column, the bundled confs' set
  lines and the generated surfaces re-render. The cache's `dump/with-cache`
  pair (the knob + the hidden `request dump with-cache`) stays cache-only
  by design — the only modbus-cache feature.

- **scraper + cache** — **the poll-now nudge joins the request namespace**:
  the scraper's `poll now` becomes `request poll now` (the registry row's
  live path `poll/now` re-keys to `request/poll/now` — the flat name
  `poll-now` and the RBAC verb `poll` stay, the orphan `poll` node retires,
  the old spelling answers unknown command) and the cache learns the same
  command: `request poll now` sets the proxy's poll-wake event (the handle
  the flush/restart branches already set — the wait between the cycles
  fires now). The `request/poll` node rows land on both registries (the
  lint's auto-node ask, the real help prose in), the ops-token prose names
  the excluded verb, the ctl/cli help strings + the man/MANUAL surfaces +
  the regtest pins follow (the scraper's suite pins the renamed wire call
  and the ops refusal, the cache's suite pins the new command + the canon
  log line both tools speak).

- **scraper** — **the shipped `metrics.token` placeholder retires**:
  `scraper/examples/metrics.token` is gone — the docker image creates the
  placeholder in `config-defaults/` with the same `RUN echo` the suite key
  uses (the entrypoint still materializes a random `/config/metrics.token`
  on the first seed, 0600; the compose stacks' `AUTH_TOKEN`/
  prometheus wire-in unchanged).

- **cache** — **the selection example and its schema join the shared
  homes**: `cache/examples/modbus-cache-filter.json` moves to
  `extras/examples/` and `cache/schema/selection.schema.json` becomes
  `shared/schema/modbus-cache-filter.schema.json` (the cache's
  `schema/` dir retires; the docker image and the nix package install
  the pair from the shared build contexts, the runtime
  `/config/selection.json` name unchanged). `cache/dev` drops its
  `--selection` line — the daemon default (every profile entry) is the
  dev shape; pass `--selection extras/examples/modbus-cache-filter.json`
  to slim it. family_drift's suite-coverage sweep follows the
  tests/suites/ move (it still grepped the thin wrappers — every knob
  read as uncovered).

- **tests** — **the suite bodies move under `tests/suites/`**: the ten
  graduated suites' real modules live there; `tests/<name>.py` become
  thin wrappers (`runpy`, `__name__='__main__'`) so the battery's suite
  names, the zz_ pgrep copy and the CI legs never change — the wrapper
  pre-seeds `tests/` onto sys.path (run_path prepends the suite's own
  dir, the harness home rides in front of it). tests/ is the python
  entry layer (the wrappers + harness.py); the lone nix file moved out
  to `nixos/tests/hardening.nix` where the testers.nixosTest convention
  lives. Validated: the full battery on the moved set — 9/10 green and
  one leg lost to the cross-session pkill contention (the concurrent
  battery's serial pre-suite sweep kills family daemons globally, not
  slot-scoped), the solo cache-regtest rerun ALL PASS 3m27s.

- **scripts** — **the battery runner is python**: `scripts/battery.py`
  replaces the sh twin — the same CLI (the profiles, the explicit
  suite names, `--stop`/`--name`/`--depth`), the same state home
  (the run dirs, the slots, the eta history, the backups), the same
  status.txt/eta row shapes `battery_status.py` parses, and the same
  machine exit (0 green / 1 red). The port kills the sh class of
  hazards the night demonstrated twice: the interpreter loads whole at
  start, so editing the file under a live battery can no longer shift a
  running shell's parse offset, and the BSD-only `date -j`/`stat -f`/
  `ln -h` spellings go (os.symlink's atomic grab, datetime stamps) —
  the runner is NixOS-portable now. The START rows carry the suite's
  OWN historical eta (`eta 3m27s`, its own finish clock) — the batch
  estimate stays on the `estimate:` row; the eta history is one JSON
  home, `pvbattery/eta.json` (profile → suite → the slowest observed
  seconds, updated on a PASS only — a failed leg's duration is noise),
  the per-profile `.txt` files the sh runner kept migrate into it once. release.py's battery leg
  invokes the python runner; the suites-side contracts (PV_RUN_DIR,
  SUITE_PORT_BASE, PV_SUITE_PROFILE, the zz_ copy's pgrep tell) are
  unchanged.

- **scripts** — **battery_status watches and renames the tail block**:
  `--watch` loops with the screen cleared per tick behind a watch-style
  header (`Every 1s: battery_status.py — HH:MM:SS (Ctrl-C quits)`),
  `--interval <s>` sets the period (default 1, implies `--watch`) —
  the default stays one show; and the newest-run block's labels say
  **`previous`** (`previous finished:` / `previous canceled:` /
  `previous run (no tally):`) — with the fall-through it names the
  previous stopped run, not the newest dir, and `previous` keeps the
  block head off the `last:` row's word.

- **tests** — **the suites create their scratch dir at the gate**:
  `os.makedirs(SCRATCH, exist_ok=True)` beside the SCRATCH binding —
  the CI matrix legs set `PV_RUN_DIR=/tmp/pvbattery-ci`, a fixed path
  nothing makes: the pre-sweep suites only read the marker and never
  wrote inside it, the SCRATCH sweep made every scratch file land in
  it, and a fresh runner's first open would have FileNotFoundError'd.
  The battery's run dir always pre-existed; the CI shape is the one
  that needs the create (validated in the CI shape: a bare, non-
  existent PV_RUN_DIR, cache-control-fuzz quick, ALL PASS).

### Removed

- **the `editor/` web editor** — `editor/serve.py` +
  `editor/index.html`, the registries' one-page browser editor (the
  four registries + the suite options JSON over a stdlib API, the save
  re-rendering through `lint_options`) — dies whole, `PV_EDITOR_ROOT`
  with it. It never rode a release; `scripts/editor.py` (the terminal
  editor) stays the one editor, and the lint package's consumers list
  and the CHANGELOG's own lint-split entry drop the mentions.
