# TODO (inverter — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[inverter]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The metrics/acl family wave: the fake's own `/metrics` takes the cache's
**`metrics/acl` gate** — `--metrics-acl`/`$METRICS_ACL`, live `set
metrics acl` / `unset`, the table show `show metrics acl table`, the
`set metrics acl table` pointer — the accept-time IP gate checked ahead
of the caps (a client off the ACL is closed without a reply), the inline
grammar or `file:<path>` (the shipped example `examples/acl-ip-prefix.json`
+ its JSON Schema `schema/acl-ip-prefix.schema.json` — both dirs new
here). The toggle's live name re-spells to the family form
**`metrics/enable`** (the wire spells `set metrics enable`; the knob
name and the flag stay flat), and the default metrics bind moves
`9452` → **`9352`** (the fake and the dashboard had shared 9452; the
family's /metrics defaults now count from the scraper's 9350 up).

The control-listener family wave: **the fake's control listener IS the
cache's** — the listener tier lifted into `common/control.py` (one
implementation, four riders) and the control family goes live on the
wire: `control/port` rebinds the listener live (bind-first, the old loop
retires by identity, the sessions keep serving, `off` retires, `unset`
restores the configured target) — **tokenless TCP included** (the F11
posture, the family's F5 refusal parameterized away as
`TOKENLESS_TCP = 'allow'`), `control/ops/verbs` (the RBAC policy, the
family spelling), `control/trust-uids`, `control/socket-group` (the live
unix socket re-modes 0600/0660); the dump/reload state carries the
listener. The old lib/paths.py wrapper died (the parsers unified in
`common/config.py`, one signature — `listen_port` + the socket template).

The F13 conformance: **the metrics token is mandatory beyond loopback,
not warn-and-serve** — the startup check, the live `metrics-server on`
and the live `metrics/token` off all refuse a non-loopback bind without
a token; the loopback default serves tokenless (the scraper's F13
refusal is the family's golden master; the F11 softness stays on the
Modbus surface — the client caps, the count gate, the tokenless TCP
exemption).

The show-status removal: **`show status` is gone** (nothing replaces it) —
the registry row, the dispatch branch and the key=value report body die;
the per-setting `show <setting>`, `show config`, `inspect` (the machines'
readings, the pins, the modbus row) and the set/unset replies' state
summary carry the same truths. The cli console greets with the two fixed
lines (the banner's status line rode the report).

The welcome-alignment wave: the four consoles' greetings wear one shape —
the three lines' texts start at one column (the welcome line indents into
its own block), the fake greets as **`Welcome to the fake-inverter
console`** (was "the Fake Inverter") and its hint line drops the extra
`help <setting>` clause. The welcome's status line renders for the first
time: its
leading `%   ` rode the print format string unescaped, so `%   r` parsed
as a `%r` conversion and the banner died in a TypeError after two lines
(latent since the family wave — the same `%`-escape the status-face wave
hit in display(); only a TTY greets, and the suites never pty the cli).

The status-face wave: the wire's reply status speaks **`ok` | `fail` |
`bye`** (the internal 'err' maps at the frame, the mac signs the wire
form; the bare help return's 'commands:' pseudo-status died — the
vocabulary holds), the console prints the ok messages bare and the
failures as **`% error: <message>`**, the set/unset pair confirms
**`% changed`**, and the wire's help branch speaks the commands.

The request-namespace wave: the control grammar's commands are `/`-paths
spelled as words on the wire — `reload` renamed to `request reload` (the
bare spelling answers `err unknown command`; the dump/restore requests
keep their names as the hidden `request/dump`/`request/restore` rows),
the registry's command rows drive the console completion segment-wise,
and the RBAC verb is the word past the `request` prefix. The console cli
joined the family's golden ladder — the hand-rolled loop is gone (the
shared typed-command loop: the help verdict rides under `% ok`, the
listings keep the registry order, the values gain the shape hint) — and
every help surface — `--help`, the man pages, the registry helps —
stopped stating default values (the README's flag/default tables are the
reference).

The modbus-common wave: the fake's wire rides **`common/modbus`** with the
rest of the family — the MBAP framing (`read_frame`/`frame`/`check_head`),
the LSB-first bit packing (`pack_bits`/`unpack_bits` — the fake's hand
rolls were three of the family's four copies) and the write shapes
(`describe_write`) are the one implementation. **Its writes are gated like
the cache's now**: `--allow-write` (env `ALLOW_WRITE`, live `write/allow`,
off by default) accepts FC05/06/15/16 into the overlays — logged via the
shared `describe_write` and audited `WRITE`; off (the default) refuses
every write with exception 01 and audits `WRITE-REFUSED`. The control
verbs (`set register`/`set coil`/`set discrete`) are the control plane —
RBAC-gated, not Modbus writes, unchanged.

The `-file` sibling removal: **`file:` is the one spelling** — the fake's
`--control-token-file`/`--control-ops-token-file`/`--metrics-token-file`
flags, their env twins and the ctl/cli's `--control-token-file` are GONE
(still experimental — behaviour may change). Every token knob takes the
inline string or a `file:<path>` reference (the same loader and 0600
discipline the siblings enforced, F12), and the secret-error strings say
"by flag/env, or as `file:<path>`".

The bit-space + float wave: the fake **serves all four address spaces from
the profile's per-entry `fc`** — `3` holding / `4` input registers for the
word types, `1` coils / `2` discrete inputs for `bit` entries (the
"same map on both codes" shortcut is gone; an `fc: 4` entry is not served
on FC3) — reads FC1/FC2 from the coil/discrete maps (strict mode rejects
undefined bits with 02), and takes **FC05/FC15 coil writes** into a coil
overlay beside the FC06/FC16 register overlay (FC5 demands the spec values
`0x0000`/`0xFF00`). The control surface gains `set coil <addr> <0|1>` /
`set discrete <addr> <0|1>` (reset/SIGUSR1 clear the pins), and a frame
too short to carry its address is answered with exception 03 instead of a
silent disconnect. The profile encoder learned `f32`/`f32swap` and the
`i32swap`/`u32swap` word orders.

The Modbus auth wave: the fake **demands the `suite` handshake from its
Modbus clients when told** — `modbus/auth` + `modbus/auth/key`
(`--auth`/`AUTH`, `--auth-key`/`AUTH_KEY`): with `suite` every connecting
client speaks the crypt handshake first (52 bytes — the `PVA1` magic, a
fresh nonce, the HMAC-SHA256 proof of the shared key, min 16 characters,
secret-marked, `file:` referenceable) and the fake answers `OK` (plain
Modbus follows) or `ERR` and drops the client before it ever sees a
register (logged `suite auth failed for …, closing`). `none`/empty (the
default) = no auth at all — the trusted-LAN posture stands; the knobs are
live (`set modbus auth suite` gates the next connection).

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

The secret-placeholder wave: an overridden secret rides the state dump /
the reload state file as `*** SECRET REMOVED ***` (the value never lands
in a file — the restore skips the placeholder and names it) and
`show config` marks the configured secrets the same way (the startup
`startup_values` carries the placeholder from the resolved argv); the
placeholder refuses to parse as a value.

The state-machinery wave: `dump_settings`/`apply_dump_settings` land on
the control server — the **state dump** (`dump/path`,
`dump/restore-on-start` lives + the `--dump-path`/`--restore-on-start`
flags/env; `request dump`/`request restore` write and re-apply the live
overrides — the pins and the machines, the scenario applied first so the
pins land on top — as one 0600 integrity-hashed JSON, common/dump.py; the
graceful shutdown dumps too), the **whole-daemon `reload`** (the fake has
no config file — its reload state lives in the XDG state home beside the
audit trail; the overrides save, the process re-execs, the fresh fake
re-applies them once and consumes the file; the ops role may not reload),
and the **secret lives**: `control/token`(-file), `control/ops/token`
(-file) and `metrics/token`(-file) rotate live (the sessions re-auth;
dropping the control token entirely stays legal — the trusted-LAN
posture, F11), the secret defaults placeholders are gone (unset refuses)
and **`show <secret>` refuses** — the value renders nowhere.

The show-settings retirement: `show settings` (and its `show all`
spelling) is gone — the per-setting `show <setting>` and `show status`'s
`overridden=` row carry the same truth, the command answers
`err unknown setting` (the registry row, the daemon help lines, the man
pages, the README and the suites follow).

The registry-folding wave: `lib/settings.py` is gone — the pins and the
machines (`pv`, `load`, `batt`, `grid`, `soc`, `mppt`, `cloud`, `scenario`,
`battery-state`, `grid-outage`) ride the `lib/options.json` registry as
control-only rows (a live name, no flag) beside the live knobs, and
`lib/options.py` derives the control vocabulary from the same rows (the
wire, the completions and the word help unchanged).

The env-prefix retirement wave: the env layer is the bare upper-snake
names now (`CHAOS`, `MAX_KWP`, `BATTERY`, `STRICT`, `TIME`, `TIME_SCALE`,
`LOG_LEVEL`, `CTL`, the token twins, ...) — the SIGHUP reload reads the
same names; the registry, the docs and the man pages follow (the README
names the scraper's `scraper_cache_*` auto-detection and `scraper_up`).

The declarative-registry wave: the knob rows (the name, the flag, the env
twin, the section, the live/secret markers and the descriptions) moved to
`lib/options.json` — `lib/options.py` loads them onto the common `Option`
rows and keeps the Python-side wiring: the control-grammar verb list, the
CLI defaults read from `static.json` (the fake parses straight off the
argv — F11, no config file) and the choice vocabularies (the log-level
ladder, the timezone), the `--no-battery` negation included. `--help`/the
man pages render from the registry now (`common/options.py`
`build_parser()`): the knob description lives exactly once. The flags in
`--help` order by the registry's sections; the texts, types and defaults
are unchanged; `scripts/check_options.py` gates as before and the package
ships the JSON next to the loader.

The rename + env-prefix wave: the bins carry the man-page names now
(`modbus-fake-inverter.py`, `modbus-fake-ctl.py`, `modbus-fake-cli.py`),
and every env twin wears the tool's prefix (`INV_*` — the `FAKE_*` era
envs are gone). The constants audit: `log_levels` joined
`lib/static.json` and every consumer reads the ladder from there.

The knob-dictionary wave: `show knobs` (the `help knobs` alias too) prints
the dictionary of all knobs — every registry knob under its section with
its flag, its env twin(s) when it has one (the fake's INV_* layer), its
home section, the command that changes it live (or the restart note for
the startup-only ones) and the secret marker on the tokens
(`common/options.py` `knob_dictionary()`; the values stay in `show config`,
the command mapping in `help config`). The fake_ctl's TAB completion and
`show?` word-help offer the new `show` argument.

The RBAC verb set: `--control-ops-verbs` (default show,clear, validated
against the fake's grammar at start, live as `set control ops verbs`)
configures the read-only role's
policy; `show config` renders the argv that would restart the fake (the
option registry landed in lib/options.py; the fake carries no config file
— its startup surface stays the flags and the INV_* env layer).

The read-only control role: a second token
(`--control-ops-token`/`--control-ops-token-file`, env
`INV_CONTROL_OPS_TOKEN(_FILE)`) beside the admin one, and its sessions
run the show verbs only — the reports yes, `set`/`unset`/`reset`/
`shutdown` no (`err forbidden: … needs the admin token`; the fake has no
`clear` verb — watching is what the ops shift does here): the ops shift
versus the admin key, both audited (`role=ops`/`role=admin` in the INV
COMMAND entries, the denials included), each session's frames mac'd with
the key it authenticated with.

The token-file env vars honored: `INV_CONTROL_TOKEN_FILE` and
`INV_METRICS_TOKEN_FILE` do what the help always promised — the env form
of `--control-token-file` / `--metrics-token-file` on the fake and both
clients (flag over env, the file over the plain token, giving both is the
familiar mutual-exclusion error; F12's 0600 gate applies either way).

The **signed wire**: with a control token configured every command and
reply on the control socket carries the full sha256 HMAC of its payload
keyed by the token (`common/wiresec.py`) — over TCP the signed commands
are mandatory, on the unix socket the mac is verify-if-present; the
fake_ctl/fake_cli clients sign and verify both directions, and the audit
trail's COMMAND entries carry the frame's mac. The opt-in **connect ACL**
for the Modbus surface (`--connect-acl`, the cache's mirrored: any/none/
IP-CIDR list, the default stays `any` — the trusted-LAN posture; a live
setting, `show status` carries `connect_acl=`). The man pages are
generated now (`common/manpage.py`, `--man` prints the page,
scripts/gen_man.py regenerates the shipped files).


The control server aligned with the cache's (the metrics-renames round):
the metrics endpoint state reports on `show status` (`metrics=`) and
`inspect` (the shared `describe_metrics` one-liner, `off` when off), the
live `set metrics-server on` warns about a token-less listen beyond
loopback like the startup does, an unbindable control target logs and
keeps running, the legacy `.`-terminator strip is gone, and the unix
control socket grew the cache's `--control-socket-group` (0660 opt-in).

The audit finding F11 closed (rev. 3): the cache's client knobs mirrored
(`--max-clients` / `--client-timeout`, live-settable, `show connections`
to watch them), the per-IP connection cap (`--max-conn-per-ip`), the
read-count gate (exception 03 past the 125-register cap — a truncated
0xFFFF-count frame no longer makes the fake assemble an oversized reply)
and the trusted-LAN / not-security-first posture documented (the README's
Security section, the man page's SECURITY block). The metrics endpoint
grew the caps too (`--metrics-max-clients` / `--metrics-client-timeout` /
`--metrics-max-conn-per-ip`, the 503 past the cap) — F13's family round.

The FC06/FC16 write path: the fake accepts real write requests (the echo
+ the overlay the scrapers see, audited with the writer), which the
cache's gated writes exercise end-to-end.

The control surface: the JSON-lines transport, the TCP token auth, the
grid setpoint, the MPPT strings (the east/west), the grid-voltage machine,
the UTC clock, the per-phase loads, `set register` overlay writes, the
status report, the registers table with the live values, the INV/CLI/CTL
audit trail with the rotation, the battery realism (the efficiency, the
self-discharge, the 80 % discharge cap, the temperature derate), the
Docker + compose setup, the bin/ lib/ split, the fuzz suite. Also the own
metrics endpoint (`--metrics-server` + `--metrics-listen`, the /metrics
with the bearer auth like the scraper's), the grid-frequency machine
(`--grid-frequency`, the
±0.2 Hz wander), the `inspect` dump, the time-lapse factor
(`--time-scale` / `set time-scale` — the simulated clock at N× real
speed, so a demo watches a full day in minutes) and the grid-outage
machine (`set grid-outage on|off|outage` — random blackouts: the phases
collapse, the inverter stands by, the meter goes dark). The statics redo
(the grouped lib/static.json) and the `--control-token-file` /
`--metrics-token-file` options. The reports: `show status` and now
`show settings` as multi-line key=value tables; the fake inverter serves
the same register map over FC3 and FC4 (the cache's FC4 path has a
device-side counterpart). The console: the TAB/? listings split into
[settings]/[values]/[system] with the descriptions aligned, `set`/`unset`
confirm `% ok`, `show <setting>` prints the bare value — and the daemon
announces its exit (`bye daemon-exit`) so the console closes instead of
reconnecting. The shared core: the audit trail, the token loader and the
wire helpers moved to `common/` (one implementation for the whole family).
