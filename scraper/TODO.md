# TODO (scraper — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[scraper]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The man-ladder wave: the page runs the family's one daemon ladder — it
gains ENVIRONMENT (the bare-twin catch-all beside the clients' CTL) and
EXIT STATUS (the unified three-code block, the failed-bind rc 1 named),
the ctl page gains EXAMPLES / ENVIRONMENT / EXIT STATUS, the cli page
EXIT STATUS; `common/manpage.py`'s LADDERS gate (`page(kind=...)`)
refuses a page that drifts. The ctl EXAMPLES are new and their
`printf` pipeline renders its `\n` for the first time.

The shared acl example/schema wave: the ip-prefix pair moves to the repo
root as the family's one shared copy (`examples/acl-ip-prefix.json` +
`schema/acl-ip-prefix.schema.json`) — the scraper's copies die,
`package.nix` installs from `../examples` + `../schema`, the module's
`metricsAclFile` description points at the root example and the regtest's
`file:` round reads it.

The battery-always-on wave: **`--battery`/`$BATTERY` are gone** (the live
`modbus/battery` with them) — the battery reads happen on every poll, the
battery metrics always export (a device profile without the battery
registers keeps them absent), the `when: battery` gates and the
`scraper_battery` gauge die (the reserved compute inputs are four now:
`pv`, `grid`, `batt`, `soc`).

The docs restructure wave: the README re-laid on the family's one skeleton
and shortened (587 → ~330 lines) — the Nix/NixOS section moved to
[docs/NIXOS.md](../docs/NIXOS.md) (the README's option list still carried
the RETIRED register/scale options — `pvRegister`, `gridRegister`,
`scale`, `gridScale`, `batteryRegister`, `batterySocRegister` — and the
stale "config INI" claim; both died with the move, the list is rebuilt
from `module.nix`), and the control-server wall became the command table
with the wire story pointed at the family docs.

The control-listener family wave: the scraper's private copy of the
listener tier (the live rebind family its control-port wave carried)
folds back into `common/control.py` — ONE implementation for the four
tools, the cache's golden master lifted; nothing changes on the wire.

The show-status removal: **`show status` is gone** (nothing replaces it) —
the registry row, the dispatch branch and the key=value report body die;
the per-setting `show <setting>`, `show config`, `inspect` and the
set/unset replies' state summary carry the same truths. The cli console
greets with the two fixed lines (the banner's status line rode the
report).

The metrics/acl wave: the /metrics listener takes the connect-ACL half
of the story — `--metrics-acl` (env `METRICS_ACL`, config `metrics_acl`,
NixOS `metricsAcl`/`metricsAclFile`, live `set metrics acl` /
`unset metrics acl`) takes the cache's acl/connect value grammar (`any`
the default, `none`, the comma-separated IP/prefix whitelist,
`file:<path>` — the standalone ip-prefix acl file) and checks it at
accept ahead of the connection caps (the ACL first, then the caps): a
client off the ACL is closed without a reply (nothing was parsed to
answer) and
logged `connection rejected: … not on the metrics ACL`. The gate
re-resolves on every set/unset and SIGHUP (a bad file keeps the old gate
standing), a group/world-readable acl file warns (the log, the audit
trail's `ACL-FILE` event, the `set` reply's suffix), `show metrics acl
table` renders the chain (the three fixed chains inline, a file gate's
own rules behind the `% ` desc header) and `set metrics acl table`
answers the pointer to the report. The gate machinery is the family's
one implementation (common/config.py's IP-gate half, common/connlimit.py's
`acl_allows`/`acl_refused` accept hooks — the cache migrated onto both
the same day); the shipped example is `examples/acl-ip-prefix.json`, its
JSON Schema `schema/acl-ip-prefix.schema.json` (`scripts/lint_acl.py`'s
bare run globs the scraper's acl files too), and F13's non-loopback
refusal stands on top of the gate (the ACL layers the who over the what,
docs/AUDIT.md rev. 19).

The re-namespace completion: the wire settings speak the family's path
shapes (`set metrics interval`, `set modbus timeout`, `set metrics limits …`,
`set caps max-pv`, `set audit …`, `set metrics auth token`) — the flat
dashed names still read in config files — and the deadwood the re-spell
exposed got wired: the bool knobs (`modbus battery`, `modbus
grid-positive-import`, `local-time`) answer set/show/dump, the audit
family is live the cache's way (`audit/log-file` moves the trail and the
fresh writer re-chains from the file's tail, the rotation rows re-render,
`audit/disable` kills the trail on the shared AuditLog), the dump carries
every live row, and the display groups hand their filing to the node walk.

The control-socket-group mirror: the scraper gains the cache's
`--control-socket-group` (env `CONTROL_SOCKET_GROUP`, config `set control
socket-group`) — the unix control socket opts into `0660` so a local group
may speak to the control without being the service user, and the live set
re-modes the socket.

The welcome-alignment wave: the console's greeting runs the cache's
segment order — the `error(s)` count moves behind `running for` (the
status line reads upstream, poll health, `running for`, the trailing
count) — and the hint line is the family's one shape.

The status-face wave: the wire's reply status speaks **`ok` | `fail` |
`bye`** (the internal 'err' maps at the frame, the mac signs the wire
form), the console prints the ok messages bare and the failures as
**`% error: <message>`**, the set/unset pair confirms **`% changed`**, and
the wire's help branch speaks the commands (`help unset` describes the
row, `help request` lists the namespace, the unknown topic answers
`unknown command or setting <words> (try ?)`).

The request-namespace wave: the control grammar's commands are `/`-paths
spelled as words on the wire — `poll now` re-spells as the path row
`poll/now`, `reload`/`restart` renamed to `request reload`/
`request restart`, and the config re-read (the SIGHUP path — a different
action from the exec dance) rides on as `request reload-config`; the bare
spellings answer `err unknown command`. The registry's command rows drive
the console completion segment-wise and the RBAC verb is the word past the
`request` prefix. The console cli joined the family's golden ladder (the
shared candidates walk, the pools, the describe order) and every help
surface — `--help`, the man pages, the registry helps — stopped stating
default values (the README's flag/default tables are the reference).

The `-file` sibling removal: **`file:` is the one spelling** —
`--control-token-file`/`--control-ops-token-file`/`--auth-token-file`,
their env twins and the `auth/token-file`-style live keys are GONE (still
experimental — behaviour may change). Every token knob takes the inline
string or a `file:<path>` reference (the same loader and 0600 discipline
the siblings enforced, F12 — the auth token's SIGHUP re-read included),
the secret-error strings say "by flag/env, or as `file:<path>`", the
NixOS module renders `set auth-token file:...` (the option names stay),
and the compose stack passes `AUTH_TOKEN=file:/config/metrics.token`.

The bit-space + float wave: the scraper's client gained **`read_bits`**
(FC1 coils / FC2 discrete inputs — the reply's packed bits decoded
LSB-first) and the decode table gained the **lo-word-first
`i32swap`/`u32swap`** orders and the **IEEE 754 `f32`/`f32swap`** pairs —
a profile entry's `type` picks the decode, its `fc` the space (`bit`
defaults to FC1, the word types to FC3). The poller now also reads **every
profile-bound metric source beyond the four power-math rows** (the spec's
phase rows were declared but silently never read) — softly: a rejected
extra read keeps its metric absent instead of failing the poll.

The Modbus auth wave: the scraper **speaks the `suite` scheme to the
inverter** — `modbus/auth` + `modbus/auth/key` (`--auth`/`AUTH`,
`--auth-key`/`AUTH_KEY`): with `suite` every (re)connect handshakes first
(52 bytes — the `PVA1` magic, a fresh nonce, the HMAC-SHA256 proof of the
shared key, min 16 characters, secret-marked, `file:` referenceable) and
the peer's `OK` opens the session, its `ERR` fails the poll like any down
device. The knobs are live (`set modbus auth suite` drops the session —
the next poll reconnects and handshakes), `show status` carries
`modbus_auth=`.

The file-reference wave: every secret value takes the **`file:` form** —
`--dump-key file:/path` (env, config, the live `set` too) reads the first
line of an owner-only `0600` file by the same loader the `-file` sibling
knobs enforce (a systemd LoadCredential rides as `file:/run/credentials/...`):
the config carries the reference, never the material, and an unreadable
reference fails fast. A dump path without a key keeps the plaintext
posture **by design** — and warns: a `WARNING` at start and a
`(not sealed)` note on the `set dump path` reply.

The seal wave: the state dumps and the reload state file **encrypt under
`dump/key`** when it is set (`--dump-key`/`DUMP_KEY`/`set dump-key` —
startup-only, restart-marked, hidden: the key cannot drift between the
writer and the re-exec'd reader): the whole state rides a version-2
envelope's `box` (an HMAC-SHA256 counter-mode keystream + the mac — the
shared seal in common/dump.py, stdlib only), a restore fails closed on a
wrong or missing key — and on an unsealed dump under a configured key.

The secret-placeholder wave: the state dump and the reload state file
carry an overridden secret's key as `*** SECRET REMOVED ***` (the value
never lands in a file — the restore skips the placeholder and names it),
`show config` renders the configured secret rows the same way, and the
placeholder refuses to parse (the config parser and the wire `set` both
point at flag/env/token-file).

The FC-awareness wave: the client's modbus errors **name the function
code that failed** — an fc4-marked source on an FC3-only device now logs
`inverter … unreachable: FC4 modbus exception, code 1` instead of a bare
`modbus exception, code 1` (the shared `FC_NAMES`/`describe_fc()` table
lives in common/protocol.py; the cache's upstream client carries the
same shape).

The state-machinery wave: `dump_settings`/`apply_dump_settings` land on
the control server — the **state dump** (`dump/path`, `dump/restore-on-start`
lives + the `--dump-path`/`--restore-on-start` flags/env/NixOS options;
`request dump`/`request restore` write and re-apply the live overrides as
one 0600 integrity-hashed JSON — common/dump.py; the graceful shutdown
dumps too), the **whole-daemon `reload`** (the overrides save to
`<config>.reload`, the process re-execs, the fresh daemon re-applies them
once and consumes the file — the ops role may not reload), and the
**secret lives**: `control/token`(-file), `control/ops/token`(-file) and
`auth/token`(-file) rotate live (the sessions re-auth; a non-loopback
listen refuses to go tokenless, F13), the secret defaults placeholders
are gone (unset refuses) and **`show <secret>` refuses** — the value
renders nowhere.

The show-settings retirement: `show settings` is gone — the per-setting
`show <setting>` and `show status`'s `overridden=` row carry the same
truth, the command answers `err unknown setting` (the registry row, the
daemon help lines, the man pages, the README and the suites follow).

The registry-folding wave: `lib/settings.py` is gone — the control
grammar's vocabulary rides the `lib/options.json` rows and `lib/options.py`
derives `SETTINGS`/`describe_setting` from them (the wire, the completions
and the word help unchanged).

The upstream-knob + directory wave: the subproject is `scraper/` now (was
`scrape/` — the flake, the docker context, the book include and the
cross-links follow; the suites keep their `tests/scrape-*.py` names), the
inverter endpoint is the one `--upstream HOST:PORT` knob (`:5502` =
127.0.0.1:5502, the shared `common/config.py` `parse_upstream()`) —
`--host`/`--modbus-port` and their `HOST`/`MODBUS_PORT` env twins retire —
and `--unit` is `--modbus-unit` (env `MODBUS_UNIT`, config `set
modbus-unit`, the NixOS option `modbusUnit`). The resolved config keeps
the derived `host`/`modbus_port` keys, so `show status`, the reload audit
and the Prometheus story read unchanged.

The env-prefix retirement wave: the env twins are the bare upper-snake
names (`CONFIG`, `MODBUS_PORT`, `METRIC_PREFIX`, `AUTH_TOKEN`, ...) — the
registry, the resolver, the ctl/cli clients, the docs and the man pages
follow. The README's metrics table documents the sectioned reality now
(the prefixed profile/compute rows vs the fixed `scraper_*` rows — the
poll-duration gauges included), its ini-era `[scraper] section` config
wording is gone, and the man DESCRIPTION names `scraper_up`.

The declarative-registry wave: the knob rows (the name, the flag, the env
twin, the section, the live/secret markers and the descriptions) moved to
`lib/options.json` — `lib/options.py` loads them onto the common `Option`
rows and keeps the Python-side wiring (the control-grammar verb list, the
audit defaults and the log-level choices read from `static.json`) — and
`--help`/the man pages render from the registry now
(`common/options.py` `build_parser()`): the knob description lives exactly
once. The flags in `--help` order by the registry's sections; the texts,
types and defaults are unchanged; `scripts/check_options.py` gates as
before and the package ships the JSON next to the loader.

The rename + env-prefix wave: the bins carry the man-page names now
(`modbus-scraper.py`, `modbus-scraper-ctl.py`, `modbus-scraper-cli.py`),
and every env twin wears the tool's prefix (`SCR_*`), the control-port
answering to the one short `SCR_CTL` for the daemon and the clients
alike. The constants audit: `log_levels` joined `lib/static.json` and
every consumer reads the ladder from there.

The profile-is-the-register-map wave (breaking): the register knobs are
gone — `--pv-register`/`--grid-register`/`--battery-register`/
`--battery-soc-register`/`--scale`/`--grid-scale` (flags, envs, config
keys, NixOS options) existed because the spec predated the device
profile; the profile is the register map's single source now (addresses,
types, gains, function codes — the per-entry `scale` is the decode
divisor, validated finite > 0 at load). The live control surface gained
`set profile <file-or-name>` (`default` = the bundled sun2000 profile,
`unset` restores): the new map loads, the metric sources rebuild, and a
profile without the registers the power math needs rolls back with a
clean error (the regtest covers the swap, the rollback and the missing
file).

The knob-dictionary wave: `show knobs` (the `help knobs` alias too) prints
the dictionary of all knobs — every registry knob under its section with
its flag, its env twin(s), its home section, the command that changes it
live (or the restart note for the startup-only ones) and the secret marker
on the tokens (`common/options.py` `knob_dictionary()`; the values stay in
`show config`, the command mapping in `help config`). The scraper_ctl/cli
TAB completion and `show?` word-help offer the new `show` argument.

The config-format + metrics waves: the ini is gone (the config file is
a set-grammar script, `show config` regenerates it, the bundled
scraper.conf is the sample); the metrics spec is sectioned ([profile] /
[compute] / [scraper]) with `--metric-prefix` (default huawei) on the
profile- and compute-fed names and the bundled `scraper_*` gauges — the
cache-diag block included (`huawei_cache_*` -> `scraper_cache_*`) — plus
the poll-latency gauges (`scraper_poll_duration_seconds`, mean/max) and
the per-phase metrics (the `profile`/`compute` sections since merged into
the one `metrics` tree — the compute-expression wave below). The RBAC
verb set is live too (`--control-ops-verbs`).
The scraper section of the spec moved to `lib/metrics.json` (next to the
loader, installed with it) and the loader merges it in memory over the
configured spec — a custom `--metrics-spec` carries the profile/compute
entries alone and overrides the built-in `scraper_*` ones by name.

The read-only control role: a second token
(`--control-ops-token`/`--control-ops-token-file`, ini
`control_ops_token`, env `SCR_CONTROL_OPS_TOKEN(_FILE)`) beside the
admin one, and its sessions run the show/clear verbs only — the reports
yes, `set`/`unset`/`poll now`/`request reload`/`restart`/`shutdown` no
(`err forbidden: … needs the admin token`): the ops shift versus the
admin key, both audited (`role=ops`/`role=admin` in the SCR COMMAND
entries, the denials included), each session's frames mac'd with the key
it authenticated with. The NixOS module grew
`controlOpsToken`/`controlOpsTokenFile`.

The token-file env honored: `SCR_CONTROL_TOKEN_FILE` does what the
clients' help always promised — the env form of `--control-token-file`
on `scraper_ctl`/`scraper_cli` (the daemon's config resolved it from the
start; flag over env, the file over the plain token, both together the
mutual-exclusion error).

The control surface (the last family tool without one): the JSON-lines
control server on the cache's pattern (the unix socket by default, the
token'd TCP with the F5 refusal, the peer-cred shortcut, the idle-timeout +
line caps), **scraper_ctl**/**scraper_cli** (the family clients), the live
settings registry (`interval`, `timeout`, `max-clients`,
`client-timeout`, `max-conn-per-ip`, `log-access`, `log-level`), `poll
now`, `request reload` (the SIGHUP path), the Modbus session `restart`,
`show status`/`connections`/`settings`, `inspect`, the SCR audit trail
(the commands carry their wire macs) — and the **signed wire**: with a
control token configured every command and reply carries the full sha256
HMAC of its payload keyed by the token (`common/wiresec.py`), mandatory
over TCP, verified end-to-end by the token-holding clients.


The audit finding F13 closed (rev. 3): the non-loopback `/metrics` listen
refuses to start without a token, and the connection limits ship —
`--max-clients` (64, an immediate 503 past it), `--client-timeout`
(300 s idle keep-alives) and `--max-conn-per-ip` (per-peer IP, 0 = no
limit), all applied live on SIGHUP (the resource-limits block of the
regtest asserts the matrix).

The profile `fc` awareness: the scraper reads each spec-bound source with
the profile entry's function code (`fc: 4` = input registers, the default
3 = holding) — the wire layer packs and validates the code, and the
regtest proves both directions (an `fc: 4` source works against the
dual-code fake and fails against the FC3-only evil server). A shipped
profile with real input-register data still waits for a hardware capture
(the fake serves both codes, so nothing honest to ship there yet).

The compute-expression wave: the spec's one merged `metrics` tree carries
one entry per metric — the entry's own field says what feeds it (a
`profile` binding, or `expr` + the optional `when` presence gate over the
declared inputs) — compiled once at startup by the stdlib-safe whitelist
evaluator (`lib/expr.py`) and evaluated per poll; an unavailable input
(`soc` with the battery flag off, a failed read), a division by zero or a
non-finite result keeps the metric absent for that poll (the former
`profile`/`compute` sections refuse at startup). The "inputs" declaration
AND the four canonical metrics (the power math's inputs) ship in the
built-in `lib/metrics.json` — merged into every spec, always bound and
fetched; a spec's own "inputs" section rewords the wording, a register
bound twice refuses; an unknown name
(referenced or declared) is a clean startup error. `show inputs` lists
the declared inputs and `show inputs metrics` the exported metrics
(normal registry rows, the aligned `name  [bracket]  help` shape, the
help capped at 40 for display). The five
classic compute metrics (the export/import split, home consumption, the
charge/discharge split) ride as the built-in eval-table defaults under
every spec that doesn't define them, and the default spec is the packaged
root's `metrics.json` only — the loader never reaches into `examples/`
itself (a dev checkout symlinks the root file — gitignored — or passes
`--metrics-spec`) — the
double-`Metrics()` wart in the bin (the daemon exported the default spec
over `--metrics-spec`) fell out of the same wave.

The Prometheus exporter: the profile-driven selection with the metrics
registry (the unit scaling, the string/phase splits), the static JSON
constants (lib/static.json), the bearer-token auth on /metrics with the
`--auth-token-file` option, the AUDIT trail with the thread-safe
rotation, the reconnect cycle, the scrape fuzz suite, the NixOS module,
the bin/ lib/ split (matching the cache and the inverter: the
`modbus-scraper` entry in bin/, the modules in lib/, the sample ini and
metrics.json at the subproject root) with lib/version — and the shared
core (the audit trail, the token loader, the wire helpers, the profile
resolution) moved to `common/`.
