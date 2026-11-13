# Changelog

The suite versions as one: the number lives in `common/runtime/version.py`
(`version_string()` appends `-<short git>` in a checkout). Dates are the
tagged commits'. The early tags (before 0.1.0) carried per-tool versions —
the dashboard, the scraper and the cache each numbered their own releases
before the repo restructured into one suite.

This file keeps **Unreleased and the current release** only — the release
history (0.4.2 and older) lives in [docs/history/CHANGELOG.md](docs/history/CHANGELOG.md).

## Unreleased
### Added

- **`apps/modbus-replay`, the capture/replay sidecar** — a Modbus TCP
  debug instrument that sits on the wire between a pv-suite client and
  the device: capture mode pipes every client upstream and dumps both
  directions to a JSON-lines trace (0600, one record per frame with
  timestamps, the raw bytes and the decoded fields — appends across
  runs, flushes per frame), replay mode serves the trace back (every
  request matched on unit + function code + PDU bytes, the most recent
  recorded response under the client's own transaction id, the recorded
  device latencies replayable at `--replay-speed`, the misses loud —
  exception 11 — or zero-shaped per `--replay-miss`), so the poll
  planning, the write-through and the chaos behavior debug against real
  hardware traces without the hardware. The sidecar deliberately stands
  outside the family's deployment and gate shapes: no control plane (no
  ctl/cli pair, no tokens — the man ladder grew the `sidecar` page
  class), no docker image, no Nix package, no service module, no audit
  trail — the trace IS the record — no connection gating (no connect
  ACL, no client caps — only `--client-timeout` kicks the silent) and
  no config file (the knobs are the flags and their bare env twins,
  flag > env > default). The registry
  (lib/options.json) still drives the parser and the man page the
  family's way; the suite is `dev/suites/replay-regtest.py` (the
  battery's new `replay` profile; it rides `commit`/`quick`/`full` too).

### Docs

- **The four manuals move to `extras/manuals/<daemon>.md`** — the
  per-tool `MANUAL.md` pages become the daemon-named `modbus-cache.md`,
  `modbus-scraper.md`, `fake-inverter.md` and `dashboard.md` under the
  operator packs (the docs redo's per-tool ruling reversed):
  `dev/generators/manual.py` renders them there (`--check` gates
  them), the book's Manuals page and the root + per-tool READMEs'
  links re-point, the links gate's generated-layer exclusion follows.

### Security

- **The compose stacks' secrets leave the config volume** (the audit's
  F17 closed, docs/SECURITY.md rev. 32) — the three secrets (the
  Modbus suite key `modbus-auth`, the exporter's `metrics-token`, the
  dashboard's `page-token`) are operator-supplied now: generate the
  stack's files with the new `docker/gen-secrets.sh` (three 0600
  hex-words under `docker/{demo,prod}/secrets/`, gitignored), compose
  mounts them read-only as secrets at `/run/secrets/<name>`, and the
  entrypoint stages private 0600 `pvsuite` copies at
  `/run/pv-secrets/<name>` — the path the stacks' `file:` env pins
  speak (the bind mounts keep the host owner, so the staging keeps the
  F12 discipline without touching it). The bundled `*.token`
  placeholders and the entrypoint's token materialization retired (the
  images carry non-secret artifacts only); the demo Prometheus reads
  the secret mount instead of the config volume; the `file:` knobs
  themselves are unchanged. The volume's seed-once semantics and the
  two re-syncs (the gentle per-file rm, `docker compose down -v` — in
  the demo wiping `prometheus-data` too) are documented as the trust
  model; the NixOS deployment stays the LoadCredential-shaped
  alternative.

## 0.5.1 — 2026-11-13
### Changed

- **The tooling and the verification consolidate under one `dev/` root**
  — `scripts/` is `dev/` and the tests tree folds in beside it
  (`tests/battery/` → `dev/battery/`, `tests/suites/` → `dev/suites/`,
  `tests/harness/` → `dev/harness/`): one root, filed by role — the
  gates, the generators, the editor, the dev lib, the suites, the
  battery and the harness — with one README and one TODO section. The
  subdir depths are unchanged, so every `__file__` repo-walk keeps
  working; the wave is spellings. The sweeps: the CI legs
  (`python3 dev/suites/${{ matrix.suite }}`, the sbom gate), the
  battery's profile strings, the lint-gates' GATES table, the drift
  sweep's coverage greps, the suites' docstring self-paths, the current
  docs' rooted-path tokens (the history records, the per-tool TODOs'
  wave-record lines and the CHANGELOG keep their landed spellings — the
  house rule), the family-drift report and the SBOM pair regenerate.
  The battery's live view returns as the dev-root hand-off:
  `python3 dev/battery_status.py` (the execv wrapper — the argv, the
  exit codes and the signals ride; the real view at
  `dev/battery/battery_status.py` is the only implementation).

- **The tests tree files the harness under its own name** — `tests/lib/`
  is `tests/harness/` (the module was always `harness` — the suites seed
  the dir onto sys.path and `from harness import *`, so the dir name
  never entered module resolution; the contested `lib` name the filing
  docs danced around is gone from tests/). The thirteen suites' boot
  lines and the suites'/battery's/harness's READMEs follow the new home;
  the suites' stale pre-filing docstring self-paths spell
  `tests/suites/<name>.py` now. The scripts/-tree `battery_status.py`
  execv hand-off is dropped before it ever landed: the live view spells
  only `python3 tests/battery/battery_status.py`, and scripts/README
  carries no battery section (scripts/ returns to its committed shape).

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

### Fixed

- **The cache regtest's restore-precondition check no longer races the
  poller** — `request restore: the clear emptied the cache first`
  flushed and immediately inspected, and on a slow machine the two
  control round-trips crossed the 2s poll boundary: the inspect caught
  fresh words (0.57ms old) that the poller had legitimately refilled
  after a flush that HAD emptied the cache — the release battery lost
  the check once at full depth (523/524) while everything around it
  stayed green. The interval quiesces to 120s across the flush→show
  pair and returns to 2s before the restore, so no refill can land in
  the window.
