# TODO (cache — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[cache]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The show-refusal wave: **`show <secret>` refuses** — `show control/token`
(the ops token, the metrics token, the `-file` spellings) answers
`err <name> is a secret — it never shows` instead of the `<set>` guard's
placeholder: the value renders nowhere (the set reply keeps `<set>` as
the rotation's confirmation; the `?`/help still describes — the
vocabulary is public, the value is not).

The reload wave: the whole-daemon `reload` verb — the live overrides save
to `<config>.reload` (created **0600 explicitly**: the file is
config-equivalent trust at rest, docs/AUDIT.md rev. 9's F23), the process
re-execs with the same argv, the fresh start re-resolves the config (the
`restart: true` knobs take their configured values) and re-applies the
saved overrides once, consuming the file (a state older than two minutes
discards as stale). The bundled `modbus_cache.conf` rebuilt in the CLI
spelling (every line `set <path words> <value>`; the sample's
`set audit requests` line included), and the registry rows lost the
`section` field — the display `group` is the one grouping.

The control-plane/audit/dump live wave: the whole control family answers
the wire — `control/port` rebinds the listener live (bind-first, the old
loop retires by identity; `off` stops accepting while the sessions keep
serving), the admin and ops tokens rotate on the wire (the secrets answer
`<set>`, `unset` refuses, the dump never carries one), `control/ops-verbs`
re-validates the RBAC policy, `control/trust-uids` and
`control/socket-group` retune the unix socket; `audit/log-file` moves the
CACHE trail with the chain continuing from the file's tail,
`audit/rotate/*` rebuild the rotation, `audit/disable` kills it;
`dump/path` arms `request dump` on a running daemon,
`dump/with-cache`/`dump/restore-on-start` flip beside it — the `control`,
`audit` and `dump` nodes describe the namespaces.

The namespace-alignment wave: the wire vocabulary follows the scraper's —
the live names are paths (`modbus/interval`, `cache/ttl`,
`limits/client-timeout`, ... beside the landed `write/*`/`acl/*` paths;
the `modbus` node describes the namespace) and the upstream endpoint +
the unit id are live-settable (`set modbus upstream HOST:PORT` re-targets
and drops the session); the dump's override keys and the unset defaults
rekey, the config scripts and the flags keep the flat registry names.

The show-settings retirement: `show settings` is gone — the per-setting
`show <setting>` and `show status`'s `overridden=` row carry the same
truth, the command answers `err unknown setting` (the registry row, the
daemon help lines, the man pages, the README and the suites follow; the
dump's settings section stays).

The write-path wave: the write knobs spell as paths on the wire —
`allow-write` is `write/allow`, `write-registers` is `write/registers`
(`set write allow on`, `show write registers`; the new `write` node
carries the namespace) — the dispatch, the dump's override keys and the
unset defaults rekey, the config scripts keep the flat registry names.

The registry-folding wave: `lib/settings.py` is gone — the control
grammar's vocabulary (the live settings' short descriptions, the value
words, the shape hints, the per-value notes) rides the same
`lib/options.json` rows as the flags/envs, and `lib/options.py` derives
`SETTINGS`/`describe_setting` from them (the wire, the completions and the
word help unchanged).

The upstream-knob wave: the inverter endpoint is the one
`--upstream HOST:PORT` knob now (`:5502` = 127.0.0.1:5502, the shared
`common/config.py` `parse_upstream()`) — `--host`/`--port` and their
`HOST`/`PORT` env twins retire (the flag, the env, the config key
`set upstream`, the NixOS option `upstream`, the docker CMD, the bundled
conf sample); the resolved config keeps the derived `host`/`port` keys,
so `show status`, the start log and the audit trail read unchanged.

The env-prefix retirement + the retag wave: the env twins drop the tool
prefixes — `HOST`, `PORT`, `TTL`, `CTL`, ... (the knob's bare upper-snake
name; `--help` renders the `$NAME` forms) — the twins are set per
deployment surface (a systemd unit, a compose service, a dev shell), so
the shared names stay safe. The tool is retagged: the docstring and
`--help`/the man DESCRIPTION say "Modbus TCP caching proxy for
single-client devices" now (the bundled sun2000 profile stays the shipped
example), and the `/metrics` docstring + the README rows name the
scraper's `scraper_cache_*` path (the metrics wave's rename, propagated).

The declarative-registry wave: the knob rows (the name, the flag, the env
twin, the section, the live/secret markers and the descriptions) moved to
`lib/options.json` — `lib/options.py` loads them onto the common `Option`
rows and keeps the Python-side wiring (the control-grammar verb list, the
config-key renames, the log-level choices read from `static.json`) — and
`--help`/the man pages render from the registry now
(`common/options.py` `build_parser()`): the knob description lives exactly
once. The flags in `--help` order by the registry's sections; the texts,
types and defaults are unchanged; `scripts/check_options.py` gates as
before and the package ships the JSON next to the loader.

The rename + env-prefix wave: the bins carry the man-page names now
(`modbus-cache.py`, `modbus-cache-ctl.py`, `modbus-cache-cli.py` — the
docs and the package descriptions follow), and every env twin wears the
tool's prefix (`MCH_*`), the control-port answering to the one short
`MCH_CTL` for the daemon and the clients alike (the long/short duplicate
reads are gone). The constants audit: `log_levels` joined
`lib/static.json` and every consumer (the argparse choices, the config
validation, the live `set log-level`) reads the ladder from there.

The knob-dictionary wave: `show knobs` (the `help knobs` alias too) prints
the dictionary of all knobs — every registry knob under its section with
its flag, its env twin(s), its home section, the command that changes it
live (or the restart note for the startup-only ones) and the secret marker
on the tokens (`common/options.py` `knob_dictionary()`; the values stay in
`show config`, the command mapping in `help config`). The cache_ctl/cli
TAB completion and `show?` word-help offer the new `show` argument.

The config-format wave: the ini is gone — the config file is a
set-grammar script now (every line a `set <name> <value>`, `#` comments
stay comments, the file pipes through cache_ctl unchanged), `show config`
regenerates it from the running daemon (the secrets hidden), `help config`
maps every knob to its control command, and the option registry
(lib/options.py on common/options.py) files every knob under the shared
sections — scripts/check_options.py gates the flags/env/nix/README
surfaces against it. The RBAC verb set is live too: `--control-ops-verbs`
(default show,clear, validated at start).

The read-only control role: a second token
(`--control-ops-token`/`--control-ops-token-file`, ini `control_ops_token`,
env `MCH_CONTROL_OPS_TOKEN(_FILE)`) beside the admin one, and its
sessions run the show/clear verbs only — `show status`/`show cache`/
`clear cache` yes, `set`/`unset`/`request dump`/`restore`/`restart`/
`shutdown` no (`err forbidden: … needs the admin token`): the ops shift
versus the admin key, both audited (the CACHE trail's COMMAND entries
carry `role=ops`/`role=admin`, the denials included) and each session's
frames mac'd with the key it authenticated with. An ops token without the
admin token (or equal to it) refuses to start; the NixOS module grew
`controlOpsToken`/`controlOpsTokenFile` (the ini render, the
LoadCredential mount, the warnings).

The token-file env honored: `MCH_CONTROL_TOKEN_FILE` does what
the clients' help always promised — the env form of
`--control-token-file` on `cache_ctl`/`cache_cli` (the daemon's config
resolved it from the start; flag over env, the file over the plain
token, both together the mutual-exclusion error).

The **signed wire**: with a control token configured every command and
reply on the control socket carries the full sha256 HMAC of its payload
keyed by the token (`common/wiresec.py`) — over TCP the signed commands
are mandatory (an unsigned or bad-mac frame is refused), on the unix
socket the mac is verify-if-present (the peer-cred trusted peers keep
speaking without the secret); the cache_ctl/cache_cli clients sign and
verify both directions, and the audit trail's COMMAND entries carry the
frame's mac (`wire=h…`). The man pages are generated now
(`common/manpage.py`: the OPTIONS section renders from the parser, the
prose lives in lib/man.py, `--man` prints the page, scripts/gen_man.py
regenerates the shipped files) and the NixOS module's sandbox got the full
hardening pass (tests/hardening.nix scores it with systemd-analyze
security).


The state persistence (the write-behind): `--dump-path` turns on the state
dump — the cached words (+ their original stamps) and the live setting
overrides, one atomically-written JSON; the dumps land every
`dump-interval` (a live setting, 0 = on request), on the `request dump`
command and on every graceful shutdown; loading is gated —
`--restore-on-start` opts in to loading the dump on start (the default is
starting cold; the `request restore` command loads it on demand) — a
gated restart serves last-known values instead of cold misses (the words
return as they were: the ttl bounds any staleness, the next map swap
prunes what the profile no longer names).

The peer-cred auth on the unix control socket: with a token configured, a
peer the kernel vouches for (root, the daemon's own user, or the extra
`--control-trust-uids` — `SO_PEERCRED` on Linux, `LOCAL_PEERCRED` on the
BSDs/macOS) skips the token handshake — a local systemd unit speaks
without the secret; TCP peers always authenticate.

The NixOS module caught up with the flag surface: a `selection` option
("all"/"none", a list of profile names the module renders into the
selection JSON, or a path to one) and the `profile` description speaking
the current schema (name/register/type/fc/ttl — no `"cache": true`
marks).

The per-entry TTL: the profile entries carry an optional `ttl` (seconds,
`0` = never expire) — `covers()` honors it per word, the global TTL stays
the fallback, the selection filter carries it, and `show cache all` marks
the entries (`[ttl 5s]`).

The native metrics endpoint: `--metrics-server` + `--metrics-listen` with
the bearer token (the scraper's scheme) serving the `modbus_cache_*` gauges — the hit/miss
counters, the poll health + age, the cache age, the words/ranges/clients,
and the last/mean/max poll-cycle durations — plus `--metrics-token-file`,
the `metrics=` rows in `show status`/`inspect`.

The live-setting persistence policy, made explicit: a live `set` survives
until the next SIGHUP (the config file always wins on reload); `show
settings` marks the overridden values with a `*`, `show status` carries the
`overridden=` row, and the SIGHUP clears the markers. The write-through
invalidation: a forwarded FC06/16/22/23 write drops exactly the cached
words it touched (per-register, `Cache.invalidate`), wakes the poller, and
the next read goes to the device instead of serving the pre-write value
until the TTL. The registry grew to 15 tunables (profile/selection live
map swaps, the ACLs, the upstream timeout) — `--selection none` empties
the map: every read forwards, nothing is stored. The reports: `show cache
all` (per-entry age/expires/status), the `connect-acl`/`timeout`/
`overridden=` rows in `show status`, the `selection`/`write-registers` rows
in `inspect`; the SIGHUP reload honors the selection file, and `set
profile default` resolves again. The console: the TAB/? listings split
into [settings]/[values]/[system] with the descriptions aligned, `set`/
`unset` confirm `% ok` (errors `% err`), `show <setting>` prints the bare
value, the reports print without the `ok` header, and the daemon
announces its exit (`bye daemon-exit`) so the console closes instead of
reconnecting.

The control surface: the JSON-lines transport, the TCP token auth (token
or token file), the audit trail (CACHE/CLI/CTL prefixes, XDG state home,
gated rotation, thread-safe), the settings registry with the live
`set`/`unset`/`show settings`/`help <setting>` grammar (the inverter's
pattern, poller tunables), the `status` summaries in the set/unset replies,
the `inspect` dump and the `show version` command, the one-shot
`cache_ctl`, the console-style `cache_cli` with the reconnect cycle, the
welcome banner and the registry-driven completions, the control fuzzer.
The cache core: device profiles + the selection file + the FC4
input-register space (per-fc poll blocks, never merged across codes), the
merge-gap block planner with the fail-split convergence, per-leaf poll
status (no device hammering), the on-demand forwarding cache with the TTL,
the synthesized 65000-65003 diagnostics block, SIGHUP hot reload + SIGUSR1
cache clean, the connect/write ACLs, the per-register write allow-list
(`--write-registers START:COUNT,...`), the audit of every
forwarded/refused write + the per-client REQUESTS tallies. The reports: the
multi-line `show status`/`show settings` (one stable key=value per line,
the inverter's shape) and the CLI that strips the header word. The ops:
the bin/ lib/ split (static constants in lib/static.json), the Docker
image + the compose service, the NixOS module with the rendered config,
the control options (`controlPort`/`controlToken`/`controlTokenFile` via
LoadCredential), the stress + fuzz suites. The console: the settings in
the TAB/? completion (set/unset/show all list the tunables, the value
positions show the shapes and hints), the libedit tab-tab fix and the
welcome banner parsing the report. The shared core: the audit trail, the
token loader, the wire helpers and the profile resolution moved to
`common/` (one implementation for the whole family).
