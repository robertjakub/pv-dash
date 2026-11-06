# TODO (inverter — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[inverter]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)
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
against the fake's grammar at start) configures the read-only role's
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
