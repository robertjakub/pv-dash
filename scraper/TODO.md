# TODO (scraper — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[scraper]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

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
the per-phase metrics. The RBAC verb set is live too (`--control-ops-verbs`).
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
