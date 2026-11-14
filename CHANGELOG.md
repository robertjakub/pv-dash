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

- **the front-page split: the READMEs slim to the front page** — every
  `apps/<tool>/README.md` now carries the description, the quick how-to,
  Security and License and nothing else (the active-development note
  rides the description); the tool's full reference is the daemon's
  `--help` and the generated man page (`<daemon> --man`), and the README
  points there. `dev/gates/readmes.py` pins the front-page canon (Usage
  -> Security -> License, no other H2s, License closes; it globs
  `apps/*/README.md`, the sidecar included). The generated manuals
  experiment (`extras/manuals/<daemon>.md`, `dev/generators/manual.py`)
  landed and was dropped within this window — it never shipped in a
  release; the record lives in docs/history/front-page-split.md (the
  pack re-landed hand-written later in the window — the Added entry
  below).

### Added

- **the manuals pack re-landed, hand-written (`extras/manuals/`)** — the
  book-style operator documentation, one page per tool app:
  `modbus-cache.md`, `modbus-scraper.md`, `modbus-fake-inverter.md`,
  `dashboard.md`, `modbus-replay.md` (the ctl/cli binaries covered
  inside each) and `pvsuite-cli.md` (the one client behind the four
  installed `-cli` names), plus the pack README and the
  `extras/README.md` index line. GitHub-flavored markdown, hard-wrapped
  prose, one section ladder per page (the family, how it works,
  installing, quick start, configuration with the full knob table mined
  from the registry, runtime control, the control plane, access
  control, metrics, the audit trail, tuning, deployment,
  troubleshooting, testing, the docs map). Nothing generated and no
  gate hooks: the reference stays the daemon's `--help` and the
  generated man page (`<daemon> --man`) — the manuals distill them and
  the man page wins a disagreement; the links gate reads the pages like
  any hand-written doc.

- **modbus-scraper: the Waveshare TCP auth on the device leg
  (`--modbus-auth waveshare`)** — the scraper now connects straight to a
  Waveshare RS485-to-TCP gateway: after every connect it sends the shared
  `--modbus-auth-key` as the gateway's connection password (raw ASCII, no
  framing) and waits for the verdict — `OK` opens the plain Modbus
  session, anything else (a rejection, a non-Waveshare peer's exception
  frame, silence, an early EOF) fails the connect like any other device
  fault and the poller keeps retrying. The handshake itself is the cache's
  upstream-leg implementation, already shared in `common/modbus/client.py`
  (`waveshare_handshake_client`) — the scraper's leg now names the scheme
  (the knob values are `suite|waveshare|none`, live via
  `set modbus/auth waveshare`), the key floor is scheme-aware (min 16
  characters for `suite`, non-empty ASCII for `waveshare`; a key set with
  no scheme yet stays dormant and going `suite` over a short standing
  password refuses at start and on the live set), and the key row speaks
  both schemes. The registry row's scheme surfaces override the shared
  canon inline (the cache's server-side `modbus/auth` and the fake stay
  suite-only — no pv-suite tool demands a Waveshare password from its own
  clients); the man page, the README row, the NixOS key-file option
  description and docs/specs/MODBUS.md (the waveshare subsection, the
  support map, the knob table) follow, and the scrape-regtest proves the
  password path against a stand-in gateway (the good and the wrong
  password, the reconnect re-proof, the live scheme dance, the dry-run
  floors).
- **modbus-replay: the trace rotates at a size (`--trace-max-mb` /
  `--trace-files`)** — an unbounded capture is a disk hazard (a capture
  proxy can sit in-line for days), so the writer now answers the audit
  log's rotation story: at `--trace-max-mb` the backups shift
  (`.1 <- .2 <- … <- .N`, the oldest dropped per `--trace-files`), the
  file reopens fresh (still 0600) and stamps a new run header — the
  fresh capture keeps the plain name, every backup is a complete trace
  of its own (any reader takes each for captured), and a record is the
  rotation boundary (a block never straddles two files). `0` = no size
  rotation, the default — nothing moves unless the knob is spelled.
  The dump tool's `--record` carries the same pair and rotates the same
  way (the recorder re-stamps a header of its own — the feed's posture,
  now); the knobs refuse without their file (`--capture` / `--record`),
  the bounds mirror the audit pair's (0..1048576 MB, 1..100 backups),
  and the rotation is format-free — no version bump, the shared writer
  (`common/modbus/trace.py`) grew the knob, both tools ride it.
- **The cache's record feed (`--trace-socket` / `--trace-sources`) — the
  wire trace live** — the cache emits every Modbus record it serves and
  exchanges to a unix feed socket in the same PVMB protocol
  modbus-replay's record feed speaks: `modbus-replay-dump --socket`
  renders the cache's traffic live with zero consumer changes, and the
  records carry what a wire-side capture cannot — the provenance (the
  note names `served from cache`, `forwarded — device reply`,
  `refused: …`, `diag registers` per answer; `peer` stays the
  conversation partner on both records). Four voices: the client face
  (every served request and answer), the upstream poller (the
  background block polls, own conn space — 100000 + the connection
  serial, so the feed's (session, conn, txn) pairing never cross-pairs
  a client request with the device's reply — the client's txn survives
  the forward verbatim), the upstream forwards and the byte-less auth
  marker (`PVA1 handshake (bytes withheld)` — the cache knows its own
  handshake, no proof or password ever rides). `--trace-socket`:
  `none` (the built-in default — off), `default` (the derived
  `/tmp/modbus-cache-<listen-port>-trace.socket`; the `-trace` suffix
  is mandatory — the control plane owns the un-suffixed path and the
  bind unlinks first) or a path; the socket binds 0600 and EVERY
  `set trace-socket` rebinds — all transitions, the same path
  included: close (the subscribers see EOF, they re-subscribe), unlink,
  bind. `--trace-sources`: `all` / `client` / `upstream` — whole
  voices on/off, never sampling (a dropped voice is stated by the
  knob, a dropped frame would be a lie: the orphan is the
  device-died signal). Feed-only — no trace file on the cache (the
  seal ruling owns state files). The trace machinery lifted to
  `common/modbus/trace.py` (the format identity into the protocol
  tree's `trace` section — one tree, no per-tool drift; the FeedSocket
  chmods 0600 at bind, so the replay's own feed stops being
  umask-dependent); the replay's lib keeps `FrameTap` + `TraceIndex`
  and re-exports the shared module.

- **`apps/modbus-replay`, the capture/replay sidecar** — a Modbus TCP
  debug instrument that sits on the wire between a pv-suite client and
  the device: capture mode pipes every client upstream and dumps both
  directions to a trace file (0600, one record per frame — the binary
  PVMB blocks by default: one magic+version+posture header block per
  run, then length-framed CRC-checked records, big-endian, the raw
  frame bytes verbatim; `--dump-type json` keeps the v1 JSON lines
  with the decoded fields riding beside the raw hex; every reader
  speaks both, the trace appends across runs, flushes per record, and
  a torn tail costs one record — the reader resyncs at the next run
  header instead of refusing), replay mode serves the trace back (every
  request matched on unit + function code + PDU bytes, the most recent
  recorded response under the client's own transaction id, the recorded
  device latencies replayable at `--replay-speed`, the misses loud —
  exception 11 — or zero-shaped per `--replay-miss`), so the poll
  planning, the write-through and the chaos behavior debug against real
  hardware traces without the hardware. The auth handshakes (the PVA1
  proof, the Waveshare password, the verdicts) ride the trace verbatim
  as named raw records (the tap peels them before the first clean
  frame — the handshake renders whole, the device's first frame
  survives the verdict glue); the record feed (`--dump-socket`, bound
  by default at the derived `/tmp/modbus-replay-<port>.socket`) pushes
  every record to the connected dump tools live — capture the real
  wire, replay the session it serves — read-only, best effort. The
  reader face is its own bin, `bin/modbus-replay-dump.py` (its own man
  page): the summary, the answer index (per unique query: the recorded
  reply, the latency, the ask count), the conversations (the
  per-connection query→answer diagram, both ends named, every packet
  line carrying its source host:port and its #conn:txn pairing key), the
  converter
  (`--to json|binary -o OUT` — the raw bytes the one truth, a
  binary→json→binary round trip byte-identical) and the live view
  (`--socket`, the value dumps gated behind `--values` — off by
  default). The sidecar deliberately stands
  outside the family's deployment and gate shapes: no control plane (no
  ctl/cli pair, no tokens — the man ladder grew the `sidecar` page
  class; the feed is read-only push, not a listener that answers), no
  docker image, no Nix package, no service module, no audit
  trail — the trace IS the record — no connection gating (no connect
  ACL, no client caps — only `--client-timeout` kicks the silent) and
  no config file (the knobs are the flags and their bare env twins,
  flag > env > default). The registry
  (lib/options.json) still drives the parser and the man page the
  family's way; the example trace ships at
  extras/examples/modbus-replay-trace.pvmb (generated, `--check`
  gated); the suite is `dev/suites/replay-regtest.py` (the
  battery's `replay` profile; it rides `commit`/`quick`/`full` too).

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

- **The cache regtest's trace section runs green at full depth for the
  first time** — the section sits past the quick profile's QuickDone and
  had never executed until a full battery ran it: the trace drain wedged
  forever (the poller voice emits a record every poll at
  `--modbus-interval 1`, so the feed never goes quiet and the drain's
  quiet-gap wait never ended — two full-battery runs died with minutes
  of zero output at the same check). The drain now bounds itself at 4s
  AND frames the stream block-by-block — the cumulative buffer always
  ends on a record boundary, so the checks' flat-index arithmetic holds
  (a torn tail used to hide records that later counted as new). The
  checks meet the real record layout: the client/upstream records carry
  the full MBAP frame (the FC at byte 7, the address at bytes 8:10 —
  the landed indexes were off by one), the refusal check speaks the
  ctl's `% error:` face, the sources-filter window takes one in-flight
  poll cycle of grace (the apply is asynchronous), the rebind EOF checks
  drain until the close (the accept loop's header may beat the rebind),
  the TRA handshake marker re-triggers through the live
  `modbus/auth-upstream` dance (the first upstream connect may ride
  before the subscriber), and the forward block's `txn = ...` local no
  longer shadows the global `txn()` helper (the flat module rebinds it
  for good — armed the moment the forward check first passed). The
  daemon side: `FeedSocket.close()` unlinks the socket file —
  `set trace-socket none` leaves no stale inode behind (the rebind's
  bind unlinked first, the close never did).

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
