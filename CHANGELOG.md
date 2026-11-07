# Changelog

The suite versions as one: the number lives in `common/version.py`
(`version_string()` appends `-<short git>` in a checkout). Dates are the
tagged commits'. The early tags (before 0.1.0) carried per-tool versions —
the dashboard, the scraper and the cache each numbered their own releases
before the repo restructured into one suite.

# Changelog

## Unreleased

### Added

- **docker** — **each image gets its own env file, and the config volume
  shrinks to the required file artifacts**: the env examples ship as
  `docker/env/cache.env.example`, `env/scraper.env.example`,
  `env/fake.env.example`, `env/dashboard.env.example` — cp one to
  `env/<tool>.env` and edit. The names are the **bare env twins** the
  tools' own docs speak (`UPSTREAM`, `INTERVAL`, `TTL`, `PROFILE`,
  `METRIC_PREFIX`, `AUTH_TOKEN_FILE`, `LOG_LEVEL`, the fake's SIGHUP-layer
  `CHAOS`/`MAX_KWP`/`BATTERY`/`STRICT`/`TIME`/`TIME_SCALE`) — one file per
  tool, so no namespacing, and the same file is consumed two ways:
  `docker run --env-file env/<tool>.env <image>` for plain docker and the
  compose stack's per-service `env_file:` (`required: false` — compose
  ≥ 2.24; no file = the image defaults, the stack runs out of the box).
  An env value rides the tools' resolution (**flag > env > the bundled
  conf > built-in defaults** — an empty value is treated as unset by every
  resolver, the fake's SIGHUP layer skips falsy ones), so it overrides the
  image's bundled conf script knob by knob; compose recreates a service
  when its env file changes. The conf scripts leave
  `/pv-suite/config-defaults` — **never seeded into `/config`**: each tool
  loads the image's own conf via the built-in default `--config` target
  (`/pv-suite/<tool>/<conf>`), and the `CONFIG=/config/<conf>` envs (cache,
  scraper) and the dashboard's `--config /config/server.conf` CMD flag are
  gone with them; a legacy volume conf from an older image is simply no
  longer loaded (point `CONFIG` at it to keep the file-editing workflow).
  `/config` now seeds only what env twins cannot carry: the generated
  `metrics.token` (one shared secret, two containers, survives
  recreation), the JSON specs (`selection.json`, `metrics.json`) and the
  served `config.js`. Two knobs stay compose-level by nature: the
  dashboard's published port and its `PROM_URL` (`environment:` beats
  `env_file`). The cache's and scraper's `--upstream` defaults move from
  the CMD flags to image `ENV` (`UPSTREAM=fake-inverter:5502` /
  `UPSTREAM=modbus-cache:15502`) — a CMD flag would pin the peer past
  every env forever, while the env keeps the plain `docker run` default.
  The README gains the env-files section and the env-or-volume split,
  `.gitignore` the `docker/env/*.env` live copies.

- **profiles** — **the write allow-list speaks the device profile**:
  the cache's `write-registers` knob takes the new value **`profile`** —
  the register gate compiles out of the device profile's `"acl"` tree
  instead of a hand-spelled range list. The profile schema gains the
  optional top-level `"acl"` object keyed by access kind, `"write"` is the
  one the cache speaks: the gate is either an object with optional
  `allow`/`deny` (+ a terse-ASCII `desc`), or an ordered rule list — one
  `{"allow"|"deny"|"defer": matcher}` object per rule (+ an optional
  `desc` each); a matcher is a `START:COUNT` range, a list of them, a
  `{ "START:COUNT": "desc" }` map describing each entry, or the bare word
  `any` (all registers) / `none`. The chain reads top to
  bottom and **the last matching rule decides**; `defer` matches but
  resets the decision back to refused, and an undecided register refuses
  (the default deny) — the object form is the sugar for the chain
  "allow, deny" (the deny wins; an absent allow is `any`, so a deny-only
  gate carves its ranges out of everything). The shipped `deye-sg05lp3`
  profile carries the first gate — `{"allow": ["127:2", "148:30"]}`: the
  TOU schedule slots (148–177) and the grid-start registers (127–128) —
  `set write-registers profile` with that profile refuses every write
  outside those two spans. The gate re-resolves when the profile swaps
  live (`set modbus profile ...`), refusing a profile without an
  `acl`/`write` section (a gate that is not there would be silent);
  `show write registers` answers `profile`, the status/inspect/start-log
  render `profile (127:2,148:30)`, the dumps and `unset` keep the
  re-appliable `profile` spelling. The profile linter validates the tree,
  the formatter carries it canonically (description → acl → mappings →
  registers), the profiles and cache READMEs, the man prose and the
  OPTIONS table follow.

- **everywhere** — **Modbus auth: the `suite` scheme**: the Modbus TCP
  peers can now demand (and present) a proof-of-key handshake — one round
  trip after the TCP connect and before any Modbus frame. The client sends
  52 bytes: the 4-byte magic `PVA1`, a fresh 16-byte nonce and the
  HMAC-SHA256 of the domain-tagged magic+nonce keyed by the shared key
  (stdlib only); the server recomputes the proof and answers `OK` (plain
  Modbus follows) or `ERR` (the connection is dead — the poller/upstream
  treats it like any failed connect and retries). Empty auth (the default)
  = no auth at all. Two knob pairs (`suite` or `none`; the keys min 16
  characters, secret-marked — they never render back — and `file:<path>`
  referenceable, live-settable): the **scraper** speaks the client side to
  the inverter (`modbus/auth` + `modbus/auth/key` — `--auth`, `AUTH`,
  `--auth-key`, `AUTH_KEY`); the **fake inverter** demands it from its
  clients (the same `modbus/auth` pair); the **cache** runs both legs —
  `modbus/auth` + `modbus/auth/key` gate its own clients (a failed proof
  is dropped before it ever sees a frame) and
  `modbus/auth-upstream` + `modbus/auth-upstream-key` (`--auth-upstream`,
  `AUTH_UPSTREAM`, `--auth-upstream-key`, `AUTH_UPSTREAM_KEY`) authenticate
  it toward the inverter. The handshake lives in `common/protocol.py`
  (one implementation for the family); `show status` carries
  `auth=`/`upstream_auth=` (cache) and `modbus_auth=` (scraper); the
  NixOS modules gain `auth`/`authKey` (scraper) and
  `auth`/`authKey`/`authUpstream`/`authUpstreamKey` (cache); the regtests
  pin the good-key round trip, the wrong-key `ERR`, the plain-client drop
  and the live `set` on all three shapes.

### Security

- **everywhere** — **the state dumps seal under a key (`dump/key`)**: the
  dump/restore data — the live setting overrides, and on the cache the
  cached words — can ride encrypted at rest. A new startup-only secret
  knob `dump/key` (`--dump-key`, env `DUMP_KEY`, config `set dump-key`;
  restart-marked — the wire answers the restart note, so the key cannot
  drift between the writer and the reader of a sealed file) seals every
  state file as a version-2 envelope (`cipher: sha256-ctr`): the whole
  state rides as the `box`, encrypted under an HMAC-SHA256 counter-mode
  keystream derived from the key and authenticated by an HMAC-SHA256 over
  nonce+box (stdlib only — no AES in the stdlib; the nonce is fresh per
  dump, and the mac is checked first: a wrong key reads as tampered
  content and fails closed, never as garbage). The gate is symmetric: a
  restore without the key refuses a sealed dump, and a restore WITH a key
  refuses an unsealed one (the plain hash is unkeyed — the moment the
  operator declares a key, plaintext stops being trust at rest). The
  reload's state files (`<config>.reload`, the fake's XDG home) migrate
  onto the shared dump writer/reader (the `when` key is `saved` now) and
  seal under the same key — the re-exec re-resolves the same argv, so the
  fresh daemon reads what the dying one wrote. No key = the old posture
  stands (0600 plaintext + the integrity hash). The registries carry the
  row (hidden, secret — `show dump key` refuses, `show config` marks it),
  the NixOS modules gain `dumpKey`, the SBOM allowlist gains `secrets`,
  and the regtests pin the sealed round-trip, the wrong-key/missing-key/
  unsealed refusals and the keyed reload on all three shapes (the fake's
  pins, the cache's words, the scraper's env twin).
- **everywhere** — **one secret knob, two forms: the `file:` reference**:
  every secret value now takes either the inline string or
  `file:<path>` — the first line of an owner-only `0600` file, loaded by
  the same discipline the `-file` sibling knobs enforce (F12; a systemd
  LoadCredential rides as `file:/run/credentials/...`). `--dump-key
  file:/path` (env `DUMP_KEY=file:...`, config `set dump key file:...`)
  is the headline, and the same acceptance lands on `--control-token`,
  `--control-ops-token`, `--auth-token` and `--metrics-token` (flag, env,
  config and the live `set` — a `file:` token re-reads on reload, so
  rotating the file rotates the token). The config file carries the
  reference, never the material; a reference that cannot be read fails
  fast (a secret that silently vanishes is a misconfiguration, not a
  fallback to plaintext). The `-file` siblings stay — same loader, same
  discipline, the explicit-path spelling. Plaintext dumps stay the
  no-key posture **by design**, and now say so: a `WARNING` at start and
  a `(not sealed — set dump/key to encrypt at rest)` note on the
  `set dump path` reply wherever a dump path is live without a key.

### Docs

- **OPTIONS.md** — **the registries' `show` section rides the table**: the
  nine show commands render as `s` rows beside the knobs (status/
  connections/version/config/knobs on all four, the cache's
  `cache`/`cache-all`/`uplink`, the fake's `registers`), the live column
  spells `show <name>` (not a knob — nothing to set), the hidden rows
  (`config`/`knobs`/`cache-all`/the cache's `status`) carry the `hidden`
  mark, and the legend explains the new kind; `gen_options.py` merges the
  show rows into the one alphabetical run (the name spaces don't collide).

### Added

- **common** — **the SBOM is generated, not asserted**: `scripts/gen_sbom.py`
  renders both `docs/sbom/SBOM.md` and `docs/sbom/sbom.cdx.json` from the
  tree, and the release workflow gains the `sbom` job running
  `gen_sbom.py --check` (regenerate + diff), so the stdlib-only claim
  stays audited — the generation runs the import scan first (an `ast`
  walk over the six shipped subprojects, the lazy imports included) and
  any root outside the reviewed stdlib allowlist or first-party
  `common`/`lib` fails the run, the vendored ECharts version is read out
  of `dashboard/static/vendor/echarts.min.js`'s own export string (its
  bundled zrender 5.6.0 is now a CycloneDX component too — the recorded
  version cannot drift from the shipped file; the stale-doc diff is what
  the check reports), and the suite version, the nixpkgs pin, the alpine
  base, the apk set and the per-tool module counts all come off the tree
  (the CycloneDX copy drops its hand-written timestamp — deterministic
  output, git dates it — and the docs/sbom links point at the real
  paths now).

- **cache / inverter / common** — **all FC codes awareness**: the family
  names every Modbus function code it sees. The one table lives in
  common/protocol.py (`FC_NAMES` + `describe_fc()` — every standard FC,
  1–24 and 43; the vendor blocks stay bare `FC<n>`), the cache's
  `describe_write()` learns FC05/15/22/23 (the coil values as 0/1 bits,
  the mask write's and/or masks, FC23's write span + read-back — a
  malformed shape names the FC and says so), a forwarded frame with no
  cache semantics logs `forwarded FC17 (report slave id), 0 byte(s)
  (unit 1)` instead of passing silently, the device-reject and refusal
  lines carry the named form, and the fake's rejects name the FC too
  (`rejected FC5 (write single coil) from … (illegal function)`; a
  malformed FC06/16 answers exception 03 with a malformed-frame note —
  the log used to say illegal function for both).

### Fixed

- **cache** — **the write allow-list vets FC23's WRITE span**: the
  request's second address pair (read addr/count rides first, write
  second) — `_write_target()` took the read span, so a read/write
  multiple-registers frame with the read span inside the allow-list and
  the written span outside was forwarded, and the write-through
  invalidation dropped the same wrong span. The gate refuses it 0x97/01
  now and the invalidation drops exactly the written words; the regtest
  pins both halves.

### Added

- **scraper / inverter / dashboard** — **the state machinery is
  family-wide**: `dump_settings`/`apply_dump_settings` on all three
  control servers (the overrides serialize to raw, re-appliable wire
  values; the secrets ride as `*** SECRET REMOVED ***` — the value never
  lands), the **state dump**
  (the `dump` node with the `dump/path` and `dump/restore-on-start`
  lives, `--dump-path`/`--restore-on-start` flags, env twins, NixOS
  options; `request dump` writes the overrides as one 0600
  integrity-hashed JSON — common/dump.py, the F18 posture — and the
  graceful shutdown dumps too; `request restore` re-applies,
  `--restore-on-start` does it at start), and the **whole-daemon
  `reload`** (the cache's verb, landed beside it: the overrides save to
  `<config>.reload` — the fake has no config file, its state home is the
  XDG state home beside its audit trail — the process re-execs, the fresh
  daemon re-applies the saved overrides once and consumes the file; the
  ops role may not reload). The **secret lives land too** (the registries
  carry the six hidden rows each): `control/token`/`control/token-file`
  and `control/ops/token`/`control/ops/token-file` rotate the control
  tokens live (the sessions re-auth, the ops token must differ from the
  admin token on the wire), the scraper's `auth/token`(-file) rotates the
  /metrics bearer live (a non-loopback listen refuses to go tokenless —
  F13), the metrics/token pair on the fake and the dashboard (F6: the
  endpoint's token is mandatory while it serves); the `control` node rows
  file the namespace, the secret defaults placeholders are deleted from
  the bins (unset refuses — the metrics/token treatment), and the
  regtests pin the rotations, the refusals, the dump/restore and the
  reload exec.

### Changed

- **everywhere** — **the secret knobs render as `*** SECRET REMOVED ***`
  in the dump/restore and `show config`**: an overridden secret rides in
  the state dump (and the reload's state file) as the placeholder — the
  knob is public, the value never lands in a file (the dump stays 0600 +
  integrity-hashed; the restore and the reload's fresh start SKIP the
  placeholder — the secret keeps its current value — and name it
  `(secret, not restored — re-pass by flag/env/token-file)` in the
  skipped list, the reload reply keeps naming the lost secrets),
  `show config` renders every configured secret row as
  `set <name> *** SECRET REMOVED ***` (the trailing hidden-note line is
  gone — the placeholder line IS the marker), and the paste-back is
  gated: the config parser refuses the placeholder as a value
  (`*** SECRET REMOVED *** is not a value — pass the secret by
  flag/env/token-file`) and so does the wire `set` — a rendered script
  piped back cannot poison a secret with a known constant. The dashboard's
  entry passes the control server the secret rows' configured-ness (its
  `show config` marks the placeholders too), the fake's `startup_values`
  marks them from the resolved argv, the shared
  `SECRET_REMOVED`/`dump_filter` live in common/dump.py, and the
  registries' show-config rows, the READMEs, the book's config chapter,
  options.md's legend and the man prose follow.

- **scraper / cache** — **the client-side modbus errors name the
  function code that failed**: `FC4 modbus exception, code 1` (was
  `modbus exception, code 1`) — the scraper's `inverter … unreachable`
  warnings and the cache's `poll of … failed` lines carry the failing
  read's FC (an fc4-marked source on an FC3-only device reads as such
  now).

- **everywhere** — **the show verb refuses the secrets**: `show
  control/token` (the ops token, `metrics/token`, `auth/token`, the
  `-file` spellings) answers `err <name> is a secret — it never shows
  (pass it by flag/env/token-file)` instead of the `<set>` guard's
  placeholder — a secret's value renders nowhere, on any tool (the set
  reply keeps `<set>` as the rotation's confirmation; the `?`/help still
  describes the knob — the vocabulary is public, the value is not).

### Added

- **everywhere** — **the registries drop the `section` field; the display
  `group` is the one grouping**: a row's `group` files it in show config,
  show knobs, help config and the cli ?/TAB listings; a row without one
  renders ungrouped — bare, no header, at the top of the listing (the
  `[system]` and `[ungrouped]` buckets are gone from the consoles
  entirely, and the registry rows that carried `group: system` dropped
  it). The dictionaries render a raw `# --- group ---` header per real
  group and nothing for the bare block; options.md's table loses the
  function column (the merged table keys by knob name; the group and the
  live command carry the story). check_options's bundled-config gate
  parses through the registries' word index now (a CLI-spelled sample
  line resolves to its knob — the node words are no longer false
  unknowns), and the editor's add-node flow no longer asks for a section.
- **cache** — **the control plane, the audit trail and the state dump are
  live**: the control rows carry their path lives and the dispatch answers
  them — `control/port` rebinds the listener (the new socket binds before
  the old closes, a failed bind leaves the listener untouched; `off`
  retires it, the running sessions keep their threads; a TCP rebind needs
  the token — F5), `control/token` and `control/ops/token` (either the
  value or the `-file` spelling) rotate without a restart — the value
  never renders back (`show` answers `<set>`, `unset` refuses, the dump
  carries no secret), and the ops token must differ from the admin token
  on the wire too; `control/ops-verbs` re-validates against the grammar,
  `control/trust-uids` swaps the trusted peer set, `control/socket-group`
  re-modes the live unix socket; `audit/log-file` moves the CACHE trail
  (the fresh writer re-chains from the file's own tail),
  `audit/rotate/{max-size,daily,files}` rebuild the rotation,
  `audit/disable` is the kill switch; `dump/path` lands the dump target on
  a running daemon (`request dump` works without a restart now),
  `dump/with-cache` and `dump/restore-on-start` flip alongside. The
  `control`, `audit` and `dump` node rows file the namespaces (`show
  control` describes them), the unset defaults rekey to the path
  spellings (the secret rows carry no entry), and a dump of an override
  set holding a secret skips it instead of crashing the session. The
  regtest pins the rebind, the rotations, the audit swap and the dump
  path.
- **everywhere** — **the startup-only knobs join the set space, marked
  `restart`**: a registry row may carry `"restart": true` — the mark and
  the no-live state agree both ways (check_options gates it). The knobs
  complete in the console set/unset pools now; `show <knob>` renders the
  configured value (the secrets answer `<set>`/`off` — the value never
  renders back); a set/unset attempt answers the note
  `% restart required (startup-only knob)` — the config (and a SIGHUP)
  changes them. edit_options.py toggles the mark like `hidden` (the
  show/command rows refuse it — it is an option-row mark).
- **everywhere** — **the config file speaks the CLI spelling**: a config
  line names its knob the way the console does — the live path as words
  (`set modbus upstream <value>`) — and `show config` renders the same,
  so its output really does pipe straight back through the ctl client
  (the flat dashed knob name — `set upstream <value>`, every older
  file's form — reads too; both normalize to the canonical name, and an
  unknown name now fails fast with the line number instead of dying
  silently in the resolver). The shipped confs flip to the path
  spelling (value-identical; the scraper's and the dashboard's flat
  lives keep their flat lines) and gain the missing `no-audit-log`
  default; the cache's also documents the metrics token pair.
- **cache** — **`reload` restarts the whole daemon and keeps the sets**:
  the new control verb saves the live overrides to a state file beside
  the config (`<config>.reload`, the dump-settings form — the secrets
  never land there), replies, then re-execs in place with the same argv;
  the fresh daemon re-resolves the config file (the `restart: true`
  knobs take their configured values — the workflow the restart mark
  wanted), re-applies the saved overrides once at control start and
  consumes the state file (a state older than two minutes is stale and
  is discarded — a later manual start stays pure). The cache starts
  empty; an overridden secret is named in the reply, to re-pass by
  flag/env/token-file. The ops role may not reload (the wiresec table
  already named it); the console word-help and the man page carry the
  verb.
- **everywhere** — **the knob dictionary says how a restart-marked knob
  changes**: `control_command` appends `, restart` to the live recipe
  (`set modbus upstream <value>, restart`) — `show knobs` and
  `help config` render the suffix for every registry row marked
  `restart: true`; the no-live startup knobs keep the
  `restart required (startup-only knob)` note.
- **everywhere** — **the console `?` describes a typed hidden leaf
  instead of lying**: the ?-walk resolves the exact typed path against
  the full registry (a hidden knob's `help`/`show <path> ?` describes —
  the wire always answered it), while the segment walk and the listings
  stay visible-only (the secrets never list); the set/unset fallback is
  knob-gated, so a show report never offers a value.
- **everywhere** — **the registries' control prose and value shapes are
  complete**: every knob carries its setting-help and a hint or an on/off
  vocabulary — the console value completion never falls back to a bare
  `value` line (the audit/dump rows' prose filled beside the metrics').
- **cache** — **the metrics knobs are live**: the seven metrics rows carry
  their path lives (`metrics/enable`, `metrics/listen`, `metrics/token`,
  `metrics/token-file`, `metrics/limits/{max-clients,timeout,
  max-conn-per-ip}`) and the dispatch answers them — enable stops/starts
  the endpoint (the F6 token gate stands), listen rebinds (the old
  address closes, the new serves; the bind is probed first), the limits
  trio applies to the running gate and the handler caps, and the token
  rotates without a restart (the value never renders back — `show`
  answers `<set>`, `unset` refuses: set the new one; the dump and the
  unset defaults carry no secret). The TODO placeholder helps are real
  prose now and the limit rows carry min/max; the regtest pins the caps,
  the rotation and the rebind.
- **scripts** — **the editor toggles the hidden mark on every row kind — the
  knobs can hide now**: edit_options.py's option-row form gains the
  `hidden` field (the same on/off toggle the show and command rows had —
  on = the cli ?/TAB pools drop the row, the wire still answers it; off =
  the mark cleared; a hierarchy node refuses). The list view follows: the
  kind mark rides bare on a hidden row (the `*` = the cli-visible — a
  hidden knob leaves the `live` view for `other`), and `hidden` filters
  in the `/`-needle as before.

- **everywhere** — **a row may carry an `alias` — a second spelling for the
  same knob on the wire**: the cache's write-acl answers as `write/acl`
  beside its live `acl/write` — `set|unset|show|help write acl <value>`
  resolves the alias and renders the CANONICAL name in the reply
  (`ok acl/write=any`; the dump keys and the unset defaults keep the
  canonical too). The consoles complete and list both
  spellings — `show write ?` walks into the aliased row, and the alias's
  first word groups and describes through the row it walks into (the
  node's rule) — and the node's namespace help (`show write`/`help
  write`) lists the aliased child, the line marked `(the alias of
  acl/write)`; `help config`/`show knobs` name the alias beside the
  command (`set acl write <value> (alias: write acl)`). One clean
  word-path, unique in the setting space (check_options gates it; the
  loader keeps the first row on a collision); edit_options.py edits the
  field (the option, the show and the control-only rows).
- **everywhere** — **the custom show words ride the registries, and a row
  may hide**: the `show` verb's non-knob views (`show status`,
  `show connections`, ...) file in each registry's `show` section
  (options.json — the word, the ?/TAB description, the `hidden` mark);
  the loaders read them into SHOW_WORDS/SHOW_HIDDEN/SHOW_VALUES and the
  clis pool from them — no cli hardcodes a show word. An option row may
  carry `"hidden": true` — a live knob that answers on the wire but
  never lists in the ?/TAB pools (the completion pools drop it;
  `show <setting>` still answers on the wire).
  `config`/`knobs` are the hidden show words family-wide. check_options
  gates both: a hidden option carries a live name, every show word is a
  clean unique word with a description.
- **everywhere** — **the registries learn hierarchy nodes**: a row may be a
  bare node — no flag/env/conv/live, a `name` that is a live-path prefix
  (`modbus`), the namespace's `setting-help`. The nodes are help-only:
  `help modbus` answers the namespace (the row's setting-help, then one
  line per child live path — the path suffix as the word), while
  `show config`, `show knobs` and `--help` ride them out (they are not
  knobs); check_options gates them (a node describes its namespace and
  has a live child). The scraper files the first one (`modbus` over
  `modbus/upstream`, `modbus/unit`, `modbus/offset`).
- **everywhere** — **the registry learns to group and the grammar to spell
  paths**: an option row may carry a `group` — the finer display bucket the
  surfaces file the knob under (until now the shared sections were the only
  grouping); `show config`, `show knobs` and `help config` bucket under the
  row's group (the section when it carries none, registry first-appearance
  order; a section key keeps its long title, a bare group key renders raw),
  and the console `?`/TAB listings group the settings the same way. And the
  control-grammar `live` name is a `/`-path now — `inverter/profile` spells
  as its words on the wire (`set|unset|show|help inverter profile <value>`;
  however deep: `a/b/c` → `set a b c <value>`), the consoles complete it
  segment by segment, and the knob -> command renderers (help config, show
  knobs, the knob table's live column) print the spaced form. No registry
  row carries a group or a path yet — the renames land in the hierarchical
  grammar wave (docs/TODO.md); every surface behaves exactly as before
  until then.
- **everywhere** — **the env twins drop the tool prefixes**: every
  environment variable is the knob's bare upper-snake name now — `HOST`,
  `PORT`, `LISTEN`, `INTERVAL`, `CTL`, `CONTROL_TOKEN`, `LOG_LEVEL`, ...
  (until now every twin wore its tool's prefix: `MCH_HOST`,
  `SCR_MODBUS_PORT`, `INV_CHAOS`, `DSH_PROM_URL`; the docker-documented
  generic set — the dashboard's `PORT`/`BIND`/`PROM_URL`/... — keeps its
  names unchanged). The different tools sharing a shell can now reach for
  the same name (`HOST` means the cache's device and the scraper's device
  alike) — the accepted trade: the twins are set per deployment surface
  (a systemd unit's `Environment=`, a compose service, a dev shell), never
  in one shared scope; the flags, the config scripts and the control
  grammar are untouched. The registries (`lib/options.json`), the
  resolvers, the ctl/cli clients, the docs, the man pages and the test
  suites follow; `--help` renders the bare `$NAME` forms. (The `HOST`/
  `PORT`/`MODBUS_PORT`/`UNIT` twins are gone again later in this same
  unreleased cycle — the inverter endpoint became the one `--upstream`
  knob and the scraper's unit id `MODBUS_UNIT`.)
- **everywhere** — **the knobs move to declarative data**: the option
  registries are `lib/options.json` files now — one row per knob carrying
  the set-grammar name, the flag, the env twin(s), the section, the
  live-settable name, the secret marker **and the knob's description**
  (until now that help text led a second life in the bins' `parse_args`),
  and the per-tool `lib/options.py` loads the rows onto the common `Option`
  vocabulary and keeps the Python-side wiring: the control-grammar verb
  list, the static.json-wired CLI defaults (the fake parses straight off
  the argv) and the choice vocabularies (log-level; the fake's timezone),
  the `--no-battery` negation included. `--help` and the man pages render
  **from the registry** (`common/options.py` `build_parser()` — the types,
  the choices, the defaults; the CLI-only `--config`/`--dry-run`/`--man`
  stay in the bins) — the description has exactly one home. `show knobs`,
  `show config`, `help config`, the bundled configs, the NixOS modules and
  `scripts/check_options.py` read the same rows as before; the flags in
  `--help`/the man OPTIONS now follow the registry's section grouping (the
  texts, types and defaults are unchanged), and the packages ship the new
  JSON next to the loader.
- **everywhere** — **`show knobs`, the dictionary of all knobs**: every
  control server answers `show knobs` (the `help knobs` alias too) with
  the whole option registry under its section — one row per knob with the
  set-grammar/config name, the argparse flag, the env twin(s), the home
  section, the command that changes it live (or the restart note for the
  startup-only knobs) and a `, secret` marker on the tokens
  (`common/options.py` `knob_dictionary()` — registry data only, no values
  render, so the secrets are named, never shown; `show config` stays the
  values view, `help config` the command mapper). The ctl/cli clients'
  TAB completion and `show?` word-help offer the new `show` argument; the
  RBAC read path covers it as is (`show` is an ops verb).
- **everywhere (the family)** — **a read-only control role**: every
  control server accepts a second token
  (`--control-ops-token`/`--control-ops-token-file`, ini + env twins:
  `MCH_CONTROL_OPS_TOKEN(_FILE)`, `SCR_CONTROL_OPS_TOKEN(_FILE)`,
  `INV_CONTROL_OPS_TOKEN(_FILE)`, `DSH_CONTROL_OPS_TOKEN(_FILE)`)
  beside the admin one, and sessions authenticating with it may run the
  **`show`/`clear` verbs only** — no `set`/`unset`, no `request
  dump`/`restore`/`reload`, no `poll now`, no `restart`, no `shutdown`:
  the ops shift versus the admin key. The gate is the command's head verb
  (`common/wiresec.py`: `ROLE_ADMIN`/`ROLE_OPS`, `role_allows`); the
  session verbs (`help`/`?`/`ping`/`quit`) every role speaks; a denied
  command answers `err forbidden: the ops token runs the show/clear verbs
  only (<verb> needs the admin token)`. Both audited: the COMMAND audit
  entries name the session's role (`role=ops`/`role=admin`, the denials
  included), and each session's frames are mac'd with the key it
  authenticated with — an ops client verifies its own replies against the
  ops token. The peer-cred trusted peers hold the admin role. A role-less
  config is unchanged. Misconfigurations fail fast: an ops token without
  the admin token, or one equal to it, refuses to start. The ops coverage
  landed in the control suites (the fake, the cache — `clear cache`
  honored, steering denied —, the dashboard) and scrape-regtest §6c;
  the NixOS modules grew `controlOpsToken`/`controlOpsTokenFile`
  (the cache's and scraper's ini rendering + the dashboard's ExecStart
  flags, the LoadCredential mounts included). Audit rev. 7 raised and
  closed **F22** (the control plane had no role separation — one token,
  one capability) with this wave.
- **everywhere** — **one knob, one source**: every knob of every tool lives
  once in an option registry (per-tool `lib/options.py`, the shared
  `common/options.py` vocabulary) — the name, the flag, the env twin(s),
  the **section** it files under (device / serving / control plane /
  metrics / audit / limits / persistence / logging), whether it is
  live-settable (the knob -> control-command mapper) and whether it is a
  secret. Built on it: the **configuration file** below, the **`show
  config`** control command (the effective configuration as a set-grammar
  script — the output pipes straight back into a config file or through a
  ctl client; the secrets never render), **`help config`** (the mapper:
  every knob and the command that changes it live, or the restart note for
  the startup-only ones), the sectioned README/config surfaces and
  **`scripts/check_options.py`** — the gate that the four surfaces (the
  flags, the env names, the NixOS module options, the README tables, plus
  the bundled config scripts) agree with the registry.
- **everywhere** — **the configuration format (breaking)**: the ini format
  is gone. The config file is a **set-grammar script** now — every line a
  `set <name> <value>`, every comment a `#` comment, one vocabulary from
  the CLI to the file to the control wire; a config file runs through a
  ctl client unchanged (the clients strip comments/blank lines locally)
  and `show config` regenerates it. A legacy ini file fails with a clean
  pointer to the new form (never silently ignored). The bundled configs
  are the rewritten samples (`modbus_cache.conf`, `scraper.conf`,
  `server.conf`) and the NixOS modules render the set grammar
  (`pkgs.writeText` line lists, dash names).
- **everywhere** — **RBAC on the control plane**: the roles are a policy
  table now (`common/wiresec.py` `ROLE_POLICIES` — admin = the full verb
  set, ops = the read-only shift), and the ops role's verb set is
  configurable per daemon (`--control-ops-verbs show,clear`, ini + env
  twins, validated against the tool's control grammar at start; an empty
  or unknown verb list refuses to start). The session verbs
  (`help`/`?`/`ping`/`quit`) stay open to every role; unknown roles fail
  closed.
- **dashboard** — **its own Prometheus /metrics endpoint** (the last
  family tool without one): `--metrics-server` (off by default, **a
  bearer token is mandatory when on** — the F6 posture), `--metrics-listen`
  (default `127.0.0.1:9452`), the token flags + the client caps like the
  cache's endpoint; serves the self-observability (the uptime, the request
  counters by status class, the proxied-query total, the client gate, the
  version) — not the PV values. Live-settable (`set metrics-server
  on/off`). The cache's and the fake's existing endpoints are unchanged.
- **dashboard** — **the per-phase chain closed**: the phase voltage/current
  selectors land in `config.js` (`phaseVoltages`/`phaseCurrents` — the
  `<prefix>_phase_{a,b,c}_*` metrics), and the page renders a per-phase
  health strip (the volts/amps per phase plus the voltage-unbalance
  percentage, highlighted when it leaves the 2 % band). Optional: omit the
  selectors, lose the strip.
- **scrape** — **the metrics.json sections**: the spec files its metrics
  now — `[profile]` (register-fed), `[compute]` (derived by the poller),
  `[scraper]` (the exporter's own gauges **and the bundled cache-diag
  block**, `scraper_*` named) — and **`--metric-prefix`** (default
  `huawei`, env `SCR_METRIC_PREFIX`) prefixes the profile- and
  compute-fed names; the bundled `scraper_*` names are fixed. The
  renames: `huawei_cache_*` -> `scraper_cache_*`, `huawei_battery` ->
  `scraper_battery`, `huawei_up` -> `scraper_up`,
  `huawei_modbus_errors_total` -> `scraper_modbus_errors_total`,
  `huawei_last_poll_timestamp_seconds` -> `scraper_last_poll_timestamp_seconds`
  (the dashboard's default selectors and the regtest follow; a custom
  legacy flat spec keeps working for the profile/compute metrics). The
  `scraper` section moves to **`lib/metrics.json`** (next to the loader,
  installed with it) and is merged in memory over the configured spec —
  a custom spec carries only the `profile`/`compute` entries it wants,
  its `scraper` entries override the built-ins by name, neither file is
  rewritten.
- **scrape** — **the poll-latency gauges**: `scraper_poll_duration_seconds`
  (+ mean/max) — a slow dongle shows up on /metrics before the freshness
  gap does. The cache has carried its `modbus_cache_poll_duration_*`
  gauges since the metrics wave.
- **scrape** — **the shipped FC4 profile**: `profiles/profiles/demo-fc4.json`
  (lint-clean, the family key order) marks every register as input
  registers (`fc: 4`) — the shipped data the fc4 regtests lacked; the
  fake serves both function codes, the cache caches fc3/fc4 separately,
  the scraper reads per-entry fc.
- **docs** — **the mdBook scaffold** (`docs/book/`): the suite's
  documentation navigable — the SUMMARY includes the READMEs, the audit,
  the TODO and the changelog (`{{#include}}`, rebuilt with `mdbook build
  docs/book`; the only tooling the book adds — the suite stays
  stdlib-only).
- **docs** — the scraper README's **"what /metrics leaks" privacy note**
  (F15): the endpoint exposes production values (generation, consumption,
  battery SoC, the per-phase voltages) — a home-occupancy consideration;
  the token + the localhost bind are the controls.

- **dashboard** — **the control plane** (the family set is complete now):
  the JSON-lines control server on the scraper's pattern — the unix socket
  `/tmp/dashboard-<port>.socket` by default (`--control-port`, `0` = off),
  the token'd TCP with the F5 refusal, the peer-cred trusted-peer shortcut,
  the signed wire. The live settings (`max-clients`, `client-timeout`,
  `max-conn-per-ip`, `log-access`, `log-queries`, `battery`, `log-level` —
  set/unset/show), `show status`/`show connections` (the live HTTP clients
  per peer IP), `show settings`, `inspect`, `request reload` (the SIGHUP
  path — the listen address/port are bound and stay), `shutdown`. Plus
  **`dashboard-ctl`** / **`dashboard-cli`** (the family's one-shot and
  console clients) and the **DSH audit trail**. The HTTP surface grew the
  family's **connection gate** (`--max-clients`, `--client-timeout`,
  `--max-conn-per-ip` — the refusals answer 503; `show connections` reads
  the gate). The NixOS module grew the matching options (`ExecReload`, the
  /run socket directory, the credentials mount included) and joins the
  hardening VM check; the docker image ships the ctl/cli. Also fixed:
  `--control-port 0` (the documented disable value) hit the token refusal —
  on the scraper too.
- **scrape** — **the control plane** (the last family tool without one):
  the JSON-lines control server on the cache's pattern — the unix socket
  `/tmp/modbus-scraper-<listen-port>.socket` by default (`--control-port`,
  `0` = off), the token'd TCP with the **F5 refusal** (a TCP control port
  without a token does not start), the peer-cred trusted-peer shortcut
  (`SO_PEERCRED`, `--control-trust-uids`), the line/cap discipline of the
  family's servers. The live settings (`interval`, `timeout`,
  `max-clients`, `client-timeout`, `max-conn-per-ip`, `log-access`,
  `log-level` — set/unset/show, `show settings` one key=value per line
  with the override markers), `show status`/`show connections` (the live
  HTTP clients via the connection gate's new snapshot), `poll now` (the
  poll loop wakes immediately), `request reload` (the SIGHUP path — the
  token file re-reads, so the bearer token rotates too), the Modbus
  session `restart`, `inspect`, `shutdown`. Plus **`modbus-scraper-ctl`** /
  **`modbus-scraper-cli`** (the family's one-shot and console clients, the token
  handshake + the signed wire included) and the **SCR audit trail**
  (`--audit-log/-max-mb/-files/--no-audit-log`; `scripts/audit_verify.py`
  already walked the scraper's path). The NixOS module grew
  `controlPort`/`controlToken`/`controlTokenFile`/`controlTrustUids` +
  `auditLog`/`auditMaxMb`/`auditFiles` (the credentials mount and the
  /run socket directory included).
- **common** — **the signed control wire** (`common/wiresec.py`): with a
  control token configured, every command and reply on the JSON-lines
  control sockets of the family's four tools carries the **full sha256 HMAC of
  its payload, keyed by the token** — the token auth proves who is
  speaking once, the mac proves it for every frame: a token-holding client
  verifies nothing was injected or altered in flight (the verifiable
  commands item in docs/TODO.md). Over TCP the signed commands are
  mandatory (unsigned/bad-mac frames refused); on the unix sockets the mac
  is verify-if-present, so the peer-cred trusted peers keep speaking
  without the secret; without a token nothing changes. The ctl/cli
  clients (cache, fake, scraper, dashboard — eight of them) sign and
  verify both directions and treat a bad reply mac as a dropped wire; the
  servers' audit COMMAND entries carry the frame's mac (`wire=h…`) — the
  command the server logs cryptographically matches the command the
  client sent.
- **common** — **the man pages are generated** (`common/manpage.py` +
  `scripts/gen_man.py`): every tool and client gained **`--man`** (print
  the roff page to stdout — `modbus-cache --man | man -l -` works in a
  container with no man pages installed), the OPTIONS sections render from
  the tools' argparse parsers (the flags and their help live once —
  `--help` and the man page cannot drift), the prose lives in per-tool
  `lib/man.py`, and the shipped `man/*.1` files (now 12: the scraper's and
  the dashboard's ctl/cli pages are new) are the generator's output,
  regenerated with `python3 scripts/gen_man.py`.
- **fake-inverter** — **`--connect-acl`**: the Modbus connect ACL the
  cache's audit story uses, mirrored (any/`none`/a comma-separated IP/CIDR
  list, env `INV_CONNECT_ACL`, a live setting, `show status` carries
  `connect_acl=`, the rejections logged). **The default stays `any`** —
  the fake's trusted-LAN posture is unchanged; the flag exists so the ACL
  story can be demoed end to end without touching the real cache.
- **nix** — **the systemd unit hardening pass** on all three NixOS
  modules: `PrivateDevices`, `CapabilityBoundingSet = ""` (empty),
  `ProtectKernelModules`/`ProtectKernelLogs`/`ProtectClock`/
  `ProtectHostname`/`ProtectProc=invisible`, `RestrictNamespaces`,
  `RestrictRealtime`, `RestrictSUIDSGID`, `LockPersonality`,
  `MemoryDenyWriteExecute`, `SystemCallArchitectures=native`,
  `SystemCallFilter=@system-service`, `UMask=0077` on top of the existing
  ProtectSystem=strict/PrivateTmp/ProtectHome. The scraper and the cache
  keep `AF_UNIX` in `RestrictAddressFamilies` — the default control target
  is a unix socket, and the filter without it silently broke that surface
  (found in the pass). Verified by the new **`hardening` flake check**
  (tests/hardening.nix): a NixOS VM boots both units, asserts every knob
  from the live unit config and scores each with `systemd-analyze
  security` (the check fails above 2.0 exposure).

- **cache** — the state persistence (the write-behind): `--dump-path` +
  `dump-interval` (a live setting, `0` = on request) dump the cached words
  (+ their stamps) and the live setting overrides as one atomic JSON — on
  the interval, on the new `request dump` command and on every graceful
  shutdown. Loading is gated: `--restore-on-start` opts in to loading the
  dump on start (the default is starting cold; `request restore` loads on
  demand) — a gated restart serves last-known values instead of cold
  misses; the words return as they were — the ttl bounds any staleness,
  the next map swap prunes. The dump commands (and the `dump-interval`
  setting) show up in the listings only when a dump path is configured.
  The NixOS module grew `dumpPath`/`dumpInterval`/`restoreOnStart` (the
  dump dir joins `ReadWritePaths`).
- **cache, fake-inverter** — the peer-cred auth on the unix control
  sockets: with a token configured, the kernel-vouched peers (root, the
  daemon's own user, `--control-trust-uids`) skip the token handshake
  (`SO_PEERCRED`, shared `common/cred.py`; the NixOS module carries
  `controlTrustUids`); TCP peers always authenticate.
- **docker** — the demo Prometheus service (`Dockerfile.prometheus`:
  alpine + the prometheus package, unprivileged via su-exec;
  `entrypoint-prometheus.sh`: the token handoff, root only for the copy;
  `prometheus.yml`): scrapes `modbus-scraper:9350` over the internal
  network with `authorization.credentials_file` — the scrape/token story
  ships with the stack now (still not the full demo: the dashboard service
  is pending).
- **cache** — the NixOS module grew the `selection` option: "all"/"none",
  a list of profile names (rendered into the selection JSON the
  `--selection` flag reads) or a path to one; the `profile` option
  description now speaks the current schema (no `"cache": true` marks).
- **cache** — `show uplink`: the inverter-link report for analysing the
  upstream connection — the session counters (state, connects, exchanges,
  bytes in/out, errors, last error) and one row per poll block with its
  status (`ok`/`ex N`/`error`/`pending`), latency (last/mean/max), failure
  count and last error. The metrics endpoint exports the same state as
  `modbus_cache_uplink_*` gauges (session counters + per-block
  up/latency/fails with `fc`/`start`/`count` labels).
- **common, scripts** — the audit trails are **tamper-evident** now (the
  audit finding F10, docs/AUDIT.md): every entry carries a short chained
  hash right after the event name — `<stamp> AUDIT <PREFIX> <EVENT> <12
  hex> [detail]`, `sha256(prev | stamp | prefix | event + detail)`, chained
  **per writer prefix** so the interleaved writers (CACHE/INV/CLI/CTL in one
  file) verify independently and a restarted writer seeds from its own
  trail. The new `scripts/audit_verify.py` walks a trail (default: the
  family's XDG audit logs; `-` reads stdin) and its rotated backups
  oldest-first, recomputes every chain, reports unsigned (pre-chain) lines
  and names the line where an edit, a deletion or a reordering broke it
  (exit 1). The honest boundary is documented with the finding: a
  determined local admin holding the algorithm can rechain — journald
  forwarding stays the strong answer where retention is strict.
- **common** — the shared connection gate (`common/connlimit.py`):
  `ConnGate` counts concurrent connections in total and per peer IP (both
  caps 0 = off, refusals never count) and `GatedHTTPServer` is the HTTP
  shape of it — one implementation behind the family's serving surfaces.
- **cache, inverter** — the metrics endpoints grew the caps
  (`--metrics-max-clients`, default 64, an immediate `503 # rate limited`
  past it; `--metrics-client-timeout`, default 5 s, `0` = the built-in
  cap; `--metrics-max-conn-per-ip`, default 0 = no per-IP limit) and both
  Modbus listeners grew **`--max-conn-per-ip`** (default 0 = no per-IP
  limit; a live setting next to `max-clients`/`client-timeout`).
- **fake-inverter** — the control server catches up with the cache's:
  `show status` carries a `metrics=` field and `inspect` an endpoint line
  (the shared `describe_metrics` one-liner, `off` when the endpoint is
  off — the fake maintained the string and reported it nowhere), the live
  `set metrics-server on` holds the documented posture (a token-less
  listen beyond loopback logs the same warning the startup prints), an
  unbindable control target logs a one-liner and keeps the fake running
  instead of dying in the serve thread, the legacy `.`-terminator strip
  is gone (the JSON frames never carried one) and the unix control socket
  grew **`--control-socket-group`** (the cache's F8 opt-in: `chmod 0660`
  instead of the default `0600`, a local group may speak to the control).
- **scrape** — **`--max-conn-per-ip`** (default 0 = no per-IP limit):
  concurrent connections from one peer IP get the same immediate 503 as
  the total `--max-clients` cap; applied live on SIGHUP like the rest.
- **tests** — the new `tests/audit-chain.py` asserts the hash chain and
  the verifier end-to-end (interleaved prefixes, the tamper matrix, the
  restart seeding, the rotation span, a live INV trail).
- **docs** — the audit reissued as **rev. 4** (docs/AUDIT.md): the whole
  tree audited directory by directory (cache, common, docker, inverter,
  profiles, scrape, scripts — the dashboard deferred to the next audit
  wave), the scope tells the four waves, the closed table carries the
  per-revision bookkeeping (rev. 2: F2–F8; rev. 3: F7/F9/F12; rev. 4:
  F10/F11/F13/F18), the evidence splits accordingly and the re-audit
  note records the focused review of the new shared surfaces. The walk
  found **one new LOW finding: F19** — the release orchestrator cuts the
  GitHub release locally before the tag-triggered CI gate reports; the
  fix is a defaults flip (the workflow cuts the release, the local gate
  runs the full suite, sign the tags).

### Changed

- **everywhere** — **the consoles prefix every non-value line with `% `**:
  the ok/err verdicts, the bye notices and the local echoes (`% ok pong`,
  the clear/restart/reload confirms, the shutdown's `% bye shutdown`) all
  carry the prefix now — the show reports, the tables and the bare values
  are the values and print bare (the fake's console already spoke this
  rule; the other three follow, and its `help <setting>` no longer prints
  the verdict twice). The README transcripts and the man prose follow.

- **cache** — **the wire vocabulary aligns with the scraper's namespaces**:
  the live names are paths now — `modbus/interval`, `modbus/read-delay`,
  `modbus/merge-gap`, `modbus/profile`, `modbus/selection`,
  `modbus/upstream`, `modbus/unit`, `cache/ttl`,
  `limits/client-timeout` (`set modbus interval 2`, `show cache ttl`;
  the new `modbus` node describes the namespace) — beside the landed
  `write/*`, `limits/max-*` and `acl/*` paths. **The upstream endpoint and
  the unit id are live-settable**: `set modbus upstream HOST:PORT`
  re-targets the inverter and drops the session (the next exchange dials
  the new endpoint), `set modbus unit N` likewise. The replies render the
  paths (`ok modbus/interval=2.00s`), the dump's override keys and the
  unset defaults rekey, the config scripts and the flags keep the flat
  registry names; the regtest and the control fuzz speak the path forms.

- **everywhere** — **`show settings` is gone**: the one-line-per-setting
  listing retires (no longer in use) — a per-setting `show <setting>`
  and `show status`'s `overridden=` row carry the same truth, and the
  command answers `err unknown setting` now. The registry rows drop the
  word (the ?/TAB pools follow), the daemon help lines lose the
  `settings` view, and the man pages, the READMEs and the suites
  follow; the `overridden` tracking and the dump's settings section
  stay (the SIGHUP/reload marker clearing rides `show status`).

- **cache** — **the write knobs spell as paths**: `allow-write` is
  `write/allow` and `write-registers` is `write/registers` on the wire —
  `set|unset|show|help write allow <on|off>`, `write registers
  <START:COUNT,...|any|none>` (the new `write` node carries the namespace
  — `show write ?` lists the two children, `help write` describes it);
  the replies render the path (`ok write/allow=on`), the dispatch, the
  dump's override keys and the unset defaults rekey (a pre-rename dump's
  write overrides restore as skipped — re-set them), the config scripts
  keep the flat registry names, and cache-regtest speaks the path forms.

- **everywhere** — **a `/`-path live name dispatches now**: the wire resolves
  the path (`set limits max-conn-per-ip <value>` — the registry's `live`
  spells as its words) and the daemon dispatches it — the control.py
  `_apply`/`_get` branches and the bin's `defaults` dict key the **live
  name** (the family rule all along: the cache's `cache-ttl` knob already
  dispatched as `ttl`). Until now a path resolved on the wire and then
  fell through the dispatch (`show` answered the `_get` fallback `?`).
  The first rename rides in: the scraper's `max-conn-per-ip` is
  `limits/max-conn-per-ip` — the set/unset/show replies render the path
  (`ok limits/max-conn-per-ip=2`), `show settings` lists it under the
  same live name. And the dispatch drives itself now: a registry row
  with a typed conv (`int`/`float`/`str`) needs no `_apply`/`_get`
  branch at all — the conv parses the value, the row's config key takes
  it, and the bin's `unset` defaults generate from the same rows; the
  row's `min`/`max` (inclusive bounds) gate the value in the same
  breath, so validation lives in the registry too (the branches stay
  for the runtime plumbing a bare config write cannot reach — the
  client, the gate, the logger — and shrink to a `_typed` call plus the
  plumbing; the bool/choice knobs keep theirs). The scraper's
  `modbus-unit` rides it live as `modbus/unit` (`set modbus unit 5`
  applies through the client's `apply(unit=...)` branch, the 0..255
  gate reads off the row; a future typed row dispatches with the JSON
  row alone). A row may also name a `check` — the tool's validator for
  the value's shape: it validates (the clean one-liner becomes the err
  reply), normalizes (`set modbus upstream :5502` stores
  `127.0.0.1:5502`) and hands back the config keys derived from the
  knob (the scraper's upstream updates `host`/`modbus_port` with it —
  the status line stays truthful). The bounds are family-wide now: the
  four registries carry `min`/`max` on every ranged live row (19 rows)
  and all four control servers gate through the same `_gate_range`
  helper (NaN included — a `nan` value is rejected like any other
  out-of-bounds one); the branch keeps the parse, the plumbing and the
  message's unit, the row owns the numbers.

- **everywhere** — **the console listings group by the `group` field
  alone**: the cli `?`/TAB listings bucket a setting under its registry
  `group`, and a row that carries none renders under `[ungrouped]`
  (until now the section filled in — `[device]/[serving]/...`;
  `Setting.display_group` holds the rule, `setting_groups()` the
  grouping). The `[values]`/`[system]` groups stay the callers'; the
  daemon-side surfaces (`show config`, `show knobs`, `help config`)
  keep the section fallback for their groupless rows. (The Added entry
  "the registry learns to group" above said the console listings group
  "the same way" as the daemon surfaces — they split here.)

- **everywhere** — **the sections render as their registry names**: the
  console `?`/TAB listings group the settings under the registry's own
  section heads — `[device]`, `[serving]`, `[control]`, `[metrics]`,
  `[limits]`, `[audit]`, `[persistence]`, `[logging]` (until now one flat
  `[settings]` group; `[values]`/`[system]` unchanged) — instead of the
  translated titles; the knob table (options.md) renders the same raw
  section keys in its function column. `Setting` carries its section and
  `common/options.py` `section_groups()` does the grouping; the long
  titles stay where they were already at home (`show config`, `show
  knobs`, `help config`).

- **everywhere** — **the control grammar's vocabulary folds into the option
  registry (one place to have all knobs)**: `lib/settings.py` is gone —
  its `SETTINGS` (the live settings' short descriptions, the completable
  value words, the value-shape hints and the per-value notes) now rides the
  same `lib/options.json` rows as the flags/envs/sections
  (`setting-help`/`values`/`hint`/`value-help` beside `live`), and
  `lib/options.py` derives the wire vocabulary from them
  (`SETTINGS`/`SETTING_BY_NAME`/`SETTING_NAMES` +
  `describe_setting`/`describe_value`, the shared
  `common/options.py` `Setting`/`settings_of()`/`make_describe()`); the
  ctl/cli clients and the control servers import the same names from
  `lib/options.py` now. The fake's **control-only settings** (the pins and
  the machines — `pv`, `load`, `batt`, `grid`, `soc`, `mppt`, `cloud`,
  `scenario`, `battery-state`, `grid-outage`) ride the registry as flagless
  rows (a live name, no flag/env) — until now they existed only in the
  hand-listed settings module; `show knobs` renders them with a
  `(control-only)` marker. The wire grammar, the completions and the word
  help are unchanged (the fake's device section lists the pins first, so
  its help output keeps its shape); check_options.py grows the drift gate
  (the live names unique, every live row carries its description, the
  control-only rows flag/env/secret-free) and options.md renders the
  control-only rows (89 knobs now).
- **scraper** — **breaking: the subproject directory is `scraper/`** (was
  `scrape/`): the flake's package/module paths, the docker build context
  and the image layout, the mdBook include, the SBOM, the cross-README
  links and the man pages' rendered paths follow; the test-suite
  filenames keep their historical `tests/scrape-*.py` names and the
  binary stays `modbus-scraper`.
- **cache, scraper** — **breaking: the inverter endpoint is one
  `--upstream HOST:PORT` knob** (the shared `common/config.py`
  `parse_upstream()`): `--host` and `--port` retire on the cache,
  `--host`/`--modbus-port` on the scraper, flags, env twins and config
  keys alike — `HOST`/`PORT`/`MODBUS_PORT` give way to `UPSTREAM`
  (a config `set upstream 127.0.0.1:5502`, the NixOS option
  `upstream`, the docker CMDs), and **`:PORT` = 127.0.0.1:PORT** (the
  loopback shorthand; `[v6]:PORT` parses like `--listen`). The resolved
  config keeps its derived `host`/`port` keys — `show status`, the start
  log and the audit trails report the same fields as before. Anything
  scripting the retired flags/envs must follow.
- **scraper** — **breaking: `--unit` is `--modbus-unit`** (env `UNIT` →
  `MODBUS_UNIT`, config `set modbus-unit`, the NixOS option `modbusUnit`):
  the Modbus unit id wears the modbus- prefix its siblings on the flag
  line already carry (`--modbus-port`'s place is taken by `--upstream`,
  so the family stays grep-able). Anything scripting `--unit` must
  follow.
- **everywhere** — **breaking: every environment twin carries the tool's
  prefix now** — `MCH_*` (the cache), `SCR_*` (the scraper), `INV_*` (the
  fake inverter), `DSH_*` (the dashboard) — and each control-port answers
  to the one short form (`MCH_CTL`/`SCR_CTL`/`INV_CTL`/`DSH_CTL`, the
  daemons and the ctl/cli clients agree; no more long/short duplicates).
  The dashboard retires the generic docker envs (`PORT`, `BIND`, `PROM_URL`,
  `PROM_PREFIX`, `STATIC_DIR`, `CONFIG_JS`, `BATTERY`) for
  `DSH_PORT`/`DSH_BIND`/`DSH_PROM_URL`/`DSH_PROM_PREFIX`/
  `DSH_STATIC_DIR`/`DSH_CONFIG_JS`/`DSH_BATTERY` — the compose stack, the
  docker docs and the compose's Prometheus wiring follow. Anything
  scripting the old names must follow.
  (Reversed later in this same unreleased cycle — the prefix retirement
  above ships the twins as the bare names; this entry is kept for the
  wave's own story.)
- **cache** — **retagged: "Modbus TCP caching proxy for single-client
  devices"** (the man page's NAME has said so; the sources follow): the
  module docstring and the `--help`/man DESCRIPTION lead with the
  device-first story (any single-client Modbus TCP device — an inverter or
  its SDongle/EMMA radio — the bundled sun2000 profile stays the shipped
  example), not the Huawei-specific one.
- **everywhere** — the bins are renamed to match their man pages (the
  family's dash names): `cache/bin/modbus_cache.py` → **`modbus-cache.py`**,
  the `*_ctl.py`/`*_cli.py` clients likewise (`modbus-cache-ctl.py`,
  `modbus-cache-cli.py`, `modbus-scraper*.py`, `modbus-fake-*.py`,
  `dashboard-*.py`) — the man page, the bin and the installed entrypoint
  share one name now; the nix packages, the docker images and the docs
  follow.
- **scrape** — **breaking: the register-map config is gone** —
  `--pv-register`/`--grid-register`/`--battery-register`/
  `--battery-soc-register`/`--scale`/`--grid-scale` (flags, envs, config
  keys, NixOS options) existed because the spec predates the device
  profile; the device profile is the register map's single source now
  (addresses, types, gains, function codes — its per-entry `scale` is the
  decode divisor, validated finite > 0 at load). The live control surface
  gained **`set profile <file-or-name>`** (`default` = the bundled sun2000
  profile, `unset` restores the configured one): the new register map
  loads, the metric sources rebuild and a profile without the registers
  the power math needs rolls back with a clean error.
- **everywhere** — the log levels are a static constant: every tool's
  `lib/static.json` carries **`log_levels`** (`DEBUG`/`INFO`/`WARNING`/
  `ERROR`) and every consumer reads it from there (the argparse choices,
  the config validation, the live `set log-level` completion and check)
  — nothing hardcodes the ladder anymore.
- **dashboard** — the bin+lib layout like the rest of the family: `src/`
  splits into `bin/` (`server.py` → **`bin/dashboard.py`**) and `lib/`
  (the statics loader), with `config.js`, `server.ini` and `man/` promoted
  to the subproject root (the dev checkout resolves them from the script's
  parent; the installed package stays flattened); `package.nix` builds from
  the subproject root now. No behavior change beyond the paths.
- **cache** — **breaking**: the state dump splits by content — by default
  it dumps **settings only**; **`request dump with-cache`** includes the
  cached words, and the new **`--dump-with-cache`** flag flips the plain
  `request dump`, the `--dump-interval` loop **and the shutdown dump** to
  the full shape (the default off = settings only — the words are
  production data, keep them out of the file unless the
  write-behind/restart story needs them). The restore takes either shape
  and loads whatever the file carries. Pair `--restore-on-start` with
  `--dump-with-cache` for the words to survive the restart.
- **cache, inverter** — **breaking**: the metrics endpoint renames — the
  master switch is **`--metrics-server`** (off by default, **live-settable**
  `set metrics-server on/off`), and **`--metrics-port`** becomes
  **`--metrics-listen HOST:PORT`** (default `127.0.0.1:9252` on the cache,
  `127.0.0.1:9452` on the fake) — `0.0.0.0:PORT` serves every interface
  (the cache's token is mandatory regardless; the fake warns when bound
  beyond loopback without one). Anything scripting `--metrics-port N`
  follows.
- **scrape** — the metrics surface is the tool by design (always on); the
  connection limits are `--max-clients` (64), `--client-timeout` (300 s)
  and `--max-conn-per-ip` (0 = no per-IP limit) — no master switch.
- **cache** — **breaking**: the write path defaults fully closed —
  `write-acl` and `write-registers` now default to **`none`** (was `any`):
  enabling `--allow-write` alone refuses every write until the operator
  opens the write ACL and the register allow-list (in the config or live
  with `set`). Both settings (and `connect-acl`, whose default stays
  `any`) grew the **`none`** mode — restrict all: `write-acl none` refuses
  every client's writes, `write-registers none` refuses every write
  regardless of the client, `connect-acl none` rejects every connection at
  accept.
- **scrape** — the default poll interval is **10 s** (was 5) — matching
  the cache's poll default, the demo Prometheus's scrape interval and the
  dashboard's `scrapeSec`; the cache already polled at 10 s.
- **common** — `human.secs`: one human time formatter for every command
  surface in the suite (ms/s/m/h/d, one unit, always two decimals) — the
  control reports, the set/unset confirmations, the `show cache all` /
  `show uplink` tables and the console banners all speak it now (the logs,
  the audit trail and the Prometheus endpoints keep raw seconds).
- **cache** — `show cache all` carries the cached words' values too: a
  `values` column between `words` and `age` (`-` = the register is not
  cached yet).
- **cache** — **breaking**: the per-client audit tally renamed — the event
  is `REQUESTS` (it counts reads and writes alike, so `READS` lied), the
  flag `--requests-audit`, the ini key `requests_audit_s`, the env
  `MODBUS_CACHE_REQUESTS_AUDIT`, the live setting `requests-audit` (was
  `reads-audit`), the `show status` field `requests_audit` and the NixOS
  option `requestsAudit`. Anything grepping the trail for
  `AUDIT CACHE READS` must follow.
- **scrape** — the profile `fc` awareness: a spec-bound source is read
  with its profile entry's function code (`fc: 4` = input registers, the
  default 3 unchanged) — the schema field now flows profile → source →
  wire (packed, and validated in the reply).

### Fixed

- **cache** — **the reload state file saves `0600` explicitly (F23,
  docs/AUDIT.md rev. 9)**: the whole-daemon `reload`'s
  `<config>.reload` handoff is config-equivalent trust at rest (whoever
  writes it injects overrides into the fresh start) and was created with
  an umask-derived mode — the tmp file is created 0600 now, the F18
  posture, one surface over; the regtest stats the saved mode.
- **everywhere** — **the set/unset pools no longer offer the show reports**:
  the show words live in the setting space (one pool machinery), but the
  set/unset completions drew from the same space unchecked — `set config ?`
  and `set connections ?` offered a value slot the daemon then refused
  (`set config 5` → `err unknown setting config`), and `set ?` listed the
  reports beside the knobs. The four consoles pool set/unset from the live
  knobs only now — the exact-match obeys the pool (a report never offers a
  value), while `show` keeps the whole space (the reports and the
  namespaces still walk and describe).
- **cache** — **`set modbus timeout` was dead on the wire**: the live-path
  wave rekeyed every `_apply`/`_get`/dump/defaults branch but left the
  timeout flat — `set timeout 5` and `set modbus timeout 5` both answered
  `err unknown setting` (no suite covered the knob). The branches, the
  defaults key and the dump key carry `modbus/timeout` now (the range gate
  keeps the row's 0 < N <= 60), the README set-table and the man prose
  spell `modbus timeout`, and the regtest pins set/unset/show/range.
- **cache** — **`local-time` is a live setting now**: the row carried a
  live name with no branch — `set local-time on` answered `err unknown
  setting`. The toggle is wired (the log handlers' formatters swap live:
  UtcFormatter ⇄ the system-zone Formatter, per handler's own format), the
  row carries the on/off values and the per-value notes, the defaults/dump
  keys follow (`unset local-time` restores the configured zone), and the
  regtest pins set/unset/show/validation.

- **everywhere** — **the control servers take a connect burst**: the listen
  backlog is 64 now (was 16) — on macOS/BSD a burst past the backlog gets
  RST (the client sees a broken pipe before it sends); the 20-parallel-
  client control fuzz tripped it.

- **everywhere** — **the console listing breaks the line before the list**:
  the TAB listing printed at the cursor — the first row landed beside the
  echoed prompt+buffer and its description column shifted by the prompt's
  length (the rows behind it kept their own column) — the list starts on a
  fresh line now and every description sits in one column.

- **everywhere** — **the console descriptions for the path-named settings**: a
  knob whose live name is a `/`-path (`limits/max-clients`) spelled as its
  words described nothing in the cli `?`/TAB listings — the describer
  resolved the bare segment (`max-clients`) against the registry's full live
  names and dropped the column (the cache's `show limits ?` listed
  `max-clients`/`max-conn-per-ip` bare; the scraper console carried the
  base-path-aware describer, the cache/dashboard/fake consoles match it
  now). A whole path's `?` describes the setting instead of `% Invalid
  input.` (`show limits max-clients ?` prints `limits/max-clients -
  simultaneous client limit`; `unset`'s too) — and the fake falls in line:
  `unset <setting> ?` no longer offers the value words (the grammar takes
  the name only) and its `?` renders the hint line like the family. The
  cache's `limits` node rides a real namespace description (the lint
  placeholder rode the row).

- **inverter** — the fake's control server now tracks the live-overridden
  settings like the family (cache/scraper/dashboard had it, the fake did
  not): `set` marks the setting, `unset`/`reset` release it again
  (`reset` releases the pins, the cloud/outage/battery machines and the
  scenario — the knobs it actually restores), `show settings` renders the
  `*` on an overridden value (`soc=50*`) and `show status` carries the
  family's `overridden=` row. The set/unset shape the console renders is
  one rule now: a knob with a `live` field renders in the cli's set/unset
  listings, `set <name> <value>` changes the value, `unset <name>` returns
  the configured startup value.

- **scraper** — the `show status`/`inspect` uptime mixed the clocks (wall
  `time.time()` minus a monotonic start): a running scraper reported
  `uptime 20763.07d` — the epoch rendered in days. Both lines read
  `time.monotonic() - started` now (the cache/fake/dashboard shape); the
  `last_poll ... ago` fields keep the wall clock on purpose (the epoch
  stamp feeds the gauge).

- **the family** — the scraper renames (`huawei_cache_*` ->
  `scraper_cache_*`, `huawei_up` -> `scraper_up`, `huawei_battery` ->
  `scraper_battery` — the metrics wave) had left stale mentions behind:
  the cache's `/metrics` docstring and README rows, the docker README, the
  inverter README (the diag-block note, the chaos chapter), the scrape
  README's metrics table (now split into the prefixed profile/compute rows
  and the fixed `scraper_*` rows — the poll-duration gauges included) and
  its ini-era `[scraper] section` config wording, and the dashboard's
  shipped `config.js` default `batteryFlag` selector (the UI's battery
  toggle asked for the retired `huawei_battery` gauge). The man pages are
  rebuilt from the fixed prose.
- **dashboard** — the `--config` help (and the `default_config_path`
  docstring) still said **`server.ini`** — the ini format is gone and the
  sample is `server.conf`: the help names the set grammar and the right
  file now (the man page follows the parser).
- **the family** — the help promised the token-file env vars, the client
  code never read them (the audit's F20, docs/AUDIT.md rev. 6): the ctl/cli
  clients honor their `--control-token-file` env form now —
  **`MCH_CONTROL_TOKEN_FILE`** (`modbus-cache-ctl`, `modbus-cache-cli`),
  **`SCR_CONTROL_TOKEN_FILE`** (`modbus-scraper-ctl`, `modbus-scraper-cli`),
  **`DSH_CONTROL_TOKEN_FILE`** (`dashboard-ctl`, `dashboard-cli`) and
  **`INV_CONTROL_TOKEN_FILE`** (`modbus-fake-ctl`, `modbus-fake-cli`) — and the fake
  itself honors `INV_CONTROL_TOKEN_FILE` /
  **`INV_METRICS_TOKEN_FILE`** (the env form of `--control-token-file` /
  `--metrics-token-file`; the other daemons resolved the env from the
  start). One resolution shape everywhere: the flag wins over the env, the
  file over the plain token, both together the usual mutual-exclusion
  error, the F12 0600 gate on every path.
- **inverter** — the fake's daemon took no env for its token files (its
  config had no resolution layer): covered by the family fix above.
- **scripts** — the release gate's full suite list had drifted:
  `--tests full` ran eight of the ten suites (the inverter regtest and the
  audit-chain suite were missing) — the gate lists all ten now.
- **dashboard** — the `--audit-log` help said SCR (the scraper's trail
  prefix); the trail is DSH.

### Docs

- **everywhere** — **options.md, the knob comparison table**: every knob of
  the four daemons in one table — the name, the function it files under
  (device/serving/control plane/own /metrics/limits/audit trail/
  persistence/logging), the registry description and a ✓ mark per tool
  (**bold** = common to all four, `live`/`secret` marked) — generated from
  the per-tool `lib/options.json` registries by the new
  `scripts/gen_options.py` (edit the registries, re-run, never the
  markdown). The table's first render flushed two registry helps: the
  cache's `--restore-on-start` still cited the dead ini key
  (`ini restore_on_start`) and the dashboard's `--no-audit-log` said
  "SCR audit trail" — both reworded to the family's default style (the
  `--help`/man pages follow the registry).
- this wave's docs: the READMEs updated family-wide (the config grammar —
  the ini is gone —, `show config`/`help config`, the RBAC verbs flag, the
  dashboard's metrics/audit rows, the scrape privacy note), the man pages
  regenerated (mandoc -Tlint clean), the TODOs follow, the mdBook scaffold
  (`docs/book/`); **docs/AUDIT.md rev. 8** records the wave (no new
  findings). **docs/AUDIT.md rev. 6** — the audit covers the whole pv-suite (the
  dashboard's deferral closed): the scraper's and the dashboard's control
  planes walked (no new findings beyond F20), the dashboard's HTTP surface
  audited for the first time — **F21** raised (no auth on page/proxy, the
  `0.0.0.0` default bind; the family TODO's auth-story item is the same
  work) — the assets/surfaces inventory and the NIS2/DORA mapping extended
  to the dashboard, and the release-gate drift recorded (fixed above).

### Security

- **scripts** — the audit finding F19 (docs/AUDIT.md, rev. 5) closed: the
  release no longer lands before the CI gate reports. The GitHub release
  is the tag-triggered workflow's job (`needs: [test, build]` — the suites
  + the nix build — then the cut from the changelog section); the
  orchestrator's local cut becomes the explicit opt-in (**`--release`**,
  printed with the bypass reminder; `--no-release` is gone). The local
  gate defaults to **`--tests full`** (was `quick`), and the tag is
  **signed** (`git tag -s`) whenever a signing key exists — the unsigned
  annotated tag is the fallback, with the reason printed. Flight-tested on
  the way: a fresh bump no longer dies on `git grep`'s no-matches exit
  code, and a dry-run prints the plan without pretending the suites ran.
- **cache** — the audit finding F18 (docs/AUDIT.md) closed: the state
  dump is owned trust at rest — created **`0600` explicitly** (never the
  umask) and carrying a **sha256 integrity hash** of its canonical
  content; a restore **fails closed**: an edited, truncated or unsigned
  dump refuses with a one-liner, and a group/world-writable dump refuses
  outright (whoever can write the dump holds config trust — own the file
  like the ini, `chmod 0600`). The hash catches corruption and casual
  tampering, not a local admin who rechashes (the same boundary as the
  audit trail's chains). The regtest asserts the mode, the hash and all
  three refusals.
- **cache, inverter** — the audit findings F2–F8 (docs/AUDIT.md) closed:
  the shared audit writer folds control characters, so an embedded `\n` in
  a control command can no longer forge a trail line (F2); an unparseable
  write frame (too short to carry an address) is refused with an
  illegal-value exception instead of being forwarded past the allow-list —
  fail closed (F3, cache); the pre-auth control line buffer drops the
  connection past 1 MB instead of growing for the idle timeout (F4, both
  control servers); a TCP control port without a token refuses to start —
  the unix socket needs none (F5, cache); the metrics endpoint refuses to
  start without a bearer token and its handler socket times out after 5 s
  (F6, cache); the unix control socket is `chmod 0600` after bind (not the
  umask), with `--control-socket-group` opting into `0660` (F8, the cache's
  option; the inverter takes the default).
- **docker** — the audit finding F7 (docs/AUDIT.md) closed: the compose
  stack publishes nothing on the host — the services talk over one
  `internal: true` network (`pv-modbus`, no outbound route), so the Modbus
  listeners, the exporter's `/metrics` and the Prometheus UI are reachable
  only from inside the network (`docker compose exec`, or a collector
  container attached to the network by name); the plain `docker run`
  examples bind their published ports to `127.0.0.1` now. The demo
  exporter serves with a bearer token — the entrypoint generates
  `/config/metrics.token` into the volume on the first seed (0600; bundled
  `*.token` defaults are placeholders, never copied) and Prometheus scrapes
  with the same value.
- **cache, inverter, scrape** — the audit findings F9 and F12
  (docs/AUDIT.md) closed: a token passed as `--control-token` /
  `--metrics-token` / `--auth-token` lands in `ps` / `/proc/*/cmdline` —
  the READMEs and the token-flag man pages now say prefer the `-file`
  variants (LoadCredential) or the env vars, the flag form is for quick
  tests (F9). Token files must be owner-only (`0600`): a group- or
  world-accessible token file refuses to start with a one-line
  `chmod 0600` error — the shared loader (`check_token_file_mode` in
  `common/config.py`) covers the cache, the fake and the ctl/cli clients,
  the scraper's SIGHUP-reread loader re-checks on every reload (F12); the
  docker entrypoint seeds generated token files 0600. The regtests assert
  the refusal.
- **inverter** — the audit finding F11 (docs/AUDIT.md) closed as
  recommended — capped and documented, not redesigned: the fake's Modbus
  listener grew **`--max-clients`** (refuse past the limit at accept,
  default 64, `0` = no limit) and **`--client-timeout`** (shed silent
  clients, default 300 s, `0` = never) mirroring the cache — both tunable
  live (`set max-clients` / `set client-timeout`, `unset` restores the
  configured value) and watched via the new **`show connections`** control
  command (peer, connection age, requests served; `clients=` joined the
  `show status` fields and `inspect` carries the modbus row). A declared
  read count past the 125-register cap (`0`, `0xFFFF`, a span past the
  16-bit space) now answers exception 03 — the cache's gate — instead of
  assembling an oversized reply. The README's Security section and the man
  page's SECURITY block document the posture: the fake is a development
  tool, not security-first design — run it on a trusted, LAN-isolated
  network. Verified by the new `tests/inverter-regtest.py`. The two suites
  that predate the earlier fixes caught up in the same sweep: the
  cache-control fuzzer authenticates now (its token-less TCP control port
  predates the F5 startup refusal) and the cache stress proxy opens its
  write path explicitly (`--write-acl any --write-registers any` — the
  write defaults are none).
- **scrape** — the audit finding F13 (docs/AUDIT.md) closed: a non-loopback
  `/metrics` listen without `--auth-token`/`--auth-token-file` **refuses to
  start** with a one-liner (`refusing to expose /metrics beyond loopback
  without a token`) — the SIGHUP reload runs the same check and keeps the
  previous settings; the loopback default needs no token (localhost dev
  stays friction-free) and the docker demo has carried the token since F7.
  The README documents the refusal and the Prometheus scrape job with
  `authorization.credentials_file`. (The cache's metrics endpoint already
  refused to start without a token and binds loopback only — F6; the
  fake's is loopback-only by construction with the optional token.)

### Docs

- **everywhere** — **options.md is docs/OPTIONS.md now**: the generated
  knob comparison table sits beside the other family-level docs, name
  upper-cased to match its siblings (AUDIT.md, SBOM.md) — `gen_options.py`
  writes the new path and the README's link follows; no content change
  beyond the regeneration.

## 0.3.0 — 2026-11-05

The control surface, the shared core and the docs redo.

### Added

- **cache** — the JSON-lines control server with TCP token auth and the
  audit trail, the one-shot `cache_ctl` and the console-style `cache_cli`
  (reconnect cycle, registry-driven TAB/? completions), the FC4
  input-register space (per-fc poll blocks, never merged across codes),
  the per-register write allow-list, the settings registry with live
  `set`/`unset`/`show settings`, `inspect`, the per-client READS tallies,
  write-through invalidation (a forwarded write drops exactly the cached
  words it touched and wakes the poller), the sectioned console listings
  and the daemon-exit announcement, the native metrics endpoint
  (`--metrics-port`, bearer token, the `modbus_cache_*` gauges),
  `selection none` (a pass-through proxy) and the per-entry profile TTL
  (`[ttl 5s]` in `show cache all`).
- **inverter** — the JSON-lines control transport with token auth, the
  audit everywhere (INV/CLI/CTL prefixes, rotation), the battery state
  machine (efficiency, self-discharge, the 80 % discharge cap, the
  temperature derate), the grid-outage machine (random blackouts, `outage`
  forces one), the live time-scale control, the CLI auto-reconnect, the
  own metrics endpoint, the static config in JSON.
- **profiles** — `bin/profile-format.py`: rewrites any profile into the
  canonical sun2000.json layout in place (content-preserving, idempotent).
- **man pages** — one roff page per tool (`man/*.1` per subproject, 11
  total), installed by the Nix packages.
- **docker** — the modbus-scraper image and compose service, the shared
  `entrypoint.sh` (seeds the config volume from the bundled defaults,
  existing files kept, drops to `pvsuite` via `su-exec`); the profiles and
  `common/` ride in as named build contexts.

### Changed

- **common/** — the shared stdlib-only package extracted: the audit trail
  (`AuditLog`, thread-safe write+flush+rotate), the token loader, the
  profile resolution, the Modbus wire core (`ModbusError`, `recv_exact`,
  `exception_frame`), the UTC log formatter and the version string — one
  implementation for the whole family.
- **scrape/** — restructured to the family layout: `bin/modbus-scraper.py`,
  the modules in `lib/`, `scraper.ini` and `metrics.json` at the subproject
  root.
- **profiles/** — the device JSONs moved under `profiles/profiles/`, the
  linter to `bin/profile-lint.py`.

### Docs

- **AUDIT.md** — the security audit (assets/trust boundaries, implemented
  controls, findings F1–F17 with the verified reproductions, the NIS2/DORA
  mapping); absorbs the former per-subproject `secaudit.md`s.
- **SBOM.md** — the software bill of materials: the stdlib-only claim
  stated and checked per subproject, the three-wide third-party surface
  (the interpreter, the alpine images, the vendored ECharts) and the
  machine-readable `sbom.cdx.json` (CycloneDX 1.5).
- all READMEs redone against the code (the stale paths, the rotted check
  counts, the compose volume semantics, the profiles' Tools section), the
  TODOs cleaned and refilled (root + the four subprojects), this
  CHANGELOG.

## 0.2.1 — 2026-11-03

The control surface release: the fake inverter's runtime control (the
settings registry, the scenarios), the battery state machine, the docker
images and the `tests/` reorganization (the suites live at the suite root,
one or more per Modbus tool).

## 0.2.0 — 2026-11-03

- **inverter** — register-map profiles: the fake serves named physical
  values mapped onto addresses by a JSON profile (the real device codes —
  the SUN2000 and the Deye hybrids ship).
- **cache** — the control server, the console CLI, the device profiles +
  the selection file.
- **scrape** — profile-driven metrics: the exported `huawei_*` values bind
  to profile register names (`metrics.json`), not hardcoded addresses.

## 0.1.0 — 2026-11-02

The repo restructures into **pv-suite**: the fake inverter splits out of
scrape into its own subproject, the dashboard gets the `dashboard/`
subproject, the suite versions as one.

## 0.0.6 — 2026-11-02

- **modbus-cache** — the experimental Modbus TCP caching proxy: exception/
  boundary hardening, ACLs, resource limits, `--dry-run`, validated
  settings, the client-limit/timeout defaults (64/300), the fuzz suites,
  the README.
- **modbus-scraper** — the cache-style rewrite: hardened framing, the
  cache-diagnostics auto-detection (`huawei_cache_*`), READMEs
  regenerated.

## 0.0.4 — 2026-11-01

The dashboard era. The tags start here — 0.0.1 (the initial dashboard
release), 0.0.2 (the Modbus TCP Prometheus exporter joins as
`sun2000-scraper`), 0.0.3 (dashboard battery support) and 0.0.4 (the
phone-fit static layout) numbered their tools individually.
