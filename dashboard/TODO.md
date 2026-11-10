# TODO (dashboard — the Done/history records)

The open items live in the family-wide [TODO](../docs/TODO.md) (tagged
`[dashboard]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The external surfaces speak the console spellings (the flat wire's
completion): the one-shot ctl translates the live/alias words like the
cli's (`set auth token file:...`), `show config` renders the live
paths as words, `help config`/`show knobs` and the MANUAL + OPTIONS
tables spell the console words in their set columns, and the state
dumps + the reload state file key the live paths — the flat names read
beside them on restore. The wire itself stays flat; the bare-live rows
(`config-js`, `log-queries`, `prom-prefix` without a live) spell the
same either way.

The wire speaks the flattened registry names: the dispatch, the
dumps, the defaults and every reply key/render the options.json `name`
(`listen`, `auth-token`, `metrics-server`, `metrics-acl`) — the live
paths are the console spellings the cli translates before it sends,
and the raw wire refuses them. `show config`, `help config` and the
node/bare-show listings render the flat names; the old dumps restore
(the live-path keys fold on the way back in).

The README moved to the gated skeleton: `scripts/lint_readmes.py --check`
pins the `##` canon family-wide — the dashboard's `Features` retitled
`How it works` (the auto-refresh and the energy-integration detail folded
into the feature bullets) and the `Notes` section dissolved into the
homes that already owned its claims (Security's offline line, Usage's
static-mode CORS note).

The audit family live family-wide (the cache's shape): the sink and the
rotation knobs join the wire — `set audit log-file <path|-|none>` swaps
the trail, `set audit rotate max-size`/`set audit rotate files`
re-chain the rotation live, `set audit disable` is the kill switch
(`clear` restores the configured value, the defaults spell the raw
`-`/`none`, not the display words). `audit_params` rides the base
constructor now and the dump carries the shared `audit_dump_rows()` —
a state dump keeps a live `audit/rotate/daily` override where it
dropped it before.

The family-wide code sweep (the shared-live-knobs wave): the control
plane (the port rebind, the ops policy, the trusted peers, the socket
group), the audit family's seven swaps, the log level, the local-time
formatter swap and the dump pair ride ONE body in
`common/wire/control.py` (`apply_family_key`/`get_family_key` + the
`record_cfg` show-config state write + the one `_rebuild_audit`) — the
tool's `_apply`/`_get` copies died into the routing (the restart
preamble, the family handler, the tool's own branches). `KNOWN_VERBS`
derives from the registry's command rows (`known_verbs`; the default
ops policy derives with it — `clear` only where the grammar speaks
it), the ladder refusals compose `on_off` and the wire's refusal texts
compose `shared/texts.json` byte-honest (the suite pins kept their
bytes). The dashboard's live audit-forward/dump-path/dump-interval renders ride `show config` now (the write-back contract the other three kept), and the bin's 9353/16/0 fallback literals read `DEFAULTS` — the statics are the one home.

## Done (the highlights; the git history has the details)

The audit-forward targets wave (the off-box copy, the F10 finish line):
`--audit-forward` spells one target now — `syslog:/path` (an explicit
socket), `udp://host[:514]` (RFC5426, best-effort) and
`tcp://host[:514]` (RFC6587 octet-count framing) join the auto-scan;
the remote envelope rides `--audit-forward-format` (`rfc5424` or `cef`,
the native line verbatim + the prefix/chain as extracted fields so the
collector's search can chain-verify and alert on a break); a send
failure notes once and the next event re-arms lazily (the note carries
the dropped count); `--audit-log none` is the remote-only mode with a
forward spelled (the chain reseeds at GENESIS per run) and folds to the
audit disabled without one; the grammar validator is one function in
`common/runtime/audit.py` and the audit-chain suite gained the
collector harnesses (the framing, CEF, UDP, the re-arm, the
remote-only e2e).

The audit forwarding (`--audit-forward syslog`, the F10 follow-through):
the DSH trail can mirror every line — the per-writer hash chain
included — to the local syslog socket as it lands, journald picking them
up sealed: the journal copy survives the box, the sink stays the
authority. The machinery is shared (`common/runtime/audit.py`), the row
is live on the wire (`set audit forward syslog`, live `audit/forward`,
env `AUDIT_FORWARD`), a socket-less spelling refuses to start with the
family's one-clean-ERROR shape, and `set audit rotate daily` rebuilds
the running writer now (it updated the params but not the writer
before).

The audit-family wave (the bounds, the daily knob, the env twins, the
shared accept ladder): the audit rotation bounds are family-wide —
`audit-files` (min 1, max 100) and `audit-max-mb` (min 0, max 1048576)
carry bounds in all four registries with the constants living once in
`common/runtime/audit.py` (`AuditLog` validates, `check_options` cross-checks);
`set audit rotate files 0` refuses identically everywhere (the scraper
accepted it before). The `audit-daily` knob is one shape: this tool gains
the row (`--audit-daily`/`$AUDIT_DAILY`, live `audit/rotate/daily` — the
UTC-midnight trigger switches on the wire) and the audit `_apply`
branches write the config back (the live values rendered stale in
`show config` before); the defaults loop covers the live bool rows
(`unset audit disable`/`local-time`/`grid-positive-import` answered
`unknown setting` before); the audit rotation defaults leave the parser
(a static-wired default shadowed `$AUDIT_MAX_MB`/`$AUDIT_FILES` — the
env layer never fell through) and `$NO_AUDIT_LOG` lands (the everywhere
ruling). The Modbus accept ladder rides the shared `serve_modbus`
(common/modbus/server.py — the gate/ACL/limits/thread discipline + the
session opener one implementation; the refusal texts identical at both
Modbus faces by construction).

The serve-address wave (the family's one word): the dashboard trades its
`--bind`/`--port` pair for the canon knob — `--listen HOST:PORT`
(`$LISTEN`, live `system/listen`, hidden, restart-marked; the default
address keeps `127.0.0.1:8080`), `show system listen` answers, the
restart fold moves the pending value in before the binds, a `set` that
would move a tokenless page beyond loopback refuses at set time (the F21
shape), and the `system` node rows the namespace. The NixOS options are
`listenHost`/`listenPort` (the cache's shape).

The dump-interval wave (the family unification, the cache as the golden
master): the dashboard gains the cache's `dump-interval` knob —
`--dump-interval`/`$DUMP_INTERVAL`, live as `set dump-interval
<s|off>` — the write-behind rewrites the state dump on a timer (the
shared dumper loop on the control base parks while the interval is off,
a live set wakes it without a restart); a set/show/describe without a
dump path answers the family's `dump-interval needs a dump path` error,
the start resolve refuses an interval without a dump path, and the
SIGHUP/`request reload-config` path re-reads the configured interval.

The secrets-startup-only wave: every secret row (auth-token,
control-token, control-ops-token, metrics-token, dump-key) is
`restart`-marked and the wire refuses set/unset on it with the dump-key
answer — the page-token off/rotate dance and the tokenless-rebind-then-
tokenize flow respawn tokenized instances now; `help config` and
OPTIONS.md render the startup-only recipe.

The man-ladder wave: the page runs the family's one daemon ladder — it
gains ENVIRONMENT (the flags' twins, `PROM_URL` named as the upstream's)
and EXIT STATUS (the unified three-code block, the failed-bind rc 1
named), the ctl page gains EXAMPLES / ENVIRONMENT / EXIT STATUS, the
cli page EXIT STATUS; `common/render/manpage.py`'s LADDERS gate
(`page(kind=...)`) refuses a page that drifts. The ctl EXAMPLES are new
and their `printf` pipeline renders its `\n` for the first time.

The shared acl example/schema wave: the ip-prefix pair moves to the repo
root as the family's one shared copy — the dashboard's example + schema
copies die (`schema/` was all-new with the pair and empties out again),
`package.nix` installs from `../examples` + `../schema` (the packaged
`share/dashboard/` layout unchanged).

The battery-always-on wave: **`--battery`/`$BATTERY` are gone** (the live
`battery` with them) — the served `config.js` always carries the battery
panels (the injection is unconditional now), and the dashboard UI
redesign (the front end's batteryEnabled gate) is the open
[docs/TODO.md](../docs/TODO.md) item.

The docs restructure wave: the README re-laid on the family's one skeleton
and shortened (404 → ~300 lines) — the Files table folded into the Source
layout, the Control wall became the command table; the NixOS section
(the flake example + the stale option list — it predated the metrics
endpoint, the dump knobs and the auth-token pair) moved to
[docs/NIXOS.md](../docs/NIXOS.md); the Testing section ADDED (the
control-fuzz suite + the /config.js fuzz pin).

The metrics/acl family wave: the dashboard's own `/metrics` takes the
cache's **`metrics/acl` gate** — `--metrics-acl`/`$METRICS_ACL`, live
`set metrics acl` / `unset`, the table show `show metrics acl table`,
the `set metrics acl table` pointer — the accept-time IP gate checked
ahead of the caps (a client off the ACL is closed without a reply), the
inline grammar or `file:<path>` (the shipped example
`examples/acl-ip-prefix.json` + its JSON Schema
`schema/acl-ip-prefix.schema.json` — the schema/ dir is new here;
NixOS `metricsAcl`). The toggle's live name re-spells to the family form
**`metrics/enable`** (the wire spells `set metrics enable`; the knob
name and the flag stay flat), and the default metrics bind moves
`9452` → **`9353`** (the fake and the dashboard had shared 9452; the
family's /metrics defaults now count from the scraper's 9350 up).

The control-listener family wave: **the dashboard's control listener IS
the cache's** — the listener tier lifted into `common/wire/control.py` (one
implementation, four riders) and the control family goes live on the
wire: `control/port` rebinds the listener live (bind-first, the old loop
retires by identity, the sessions keep serving, `off` retires, `unset`
restores the configured target; a tokenless TCP bind still refuses — the
F5 posture now guards the live wire too, not only the start),
`control/ops/verbs` (the RBAC policy, the family spelling),
`control/trust-uids`, and a NEW **`control-socket-group`** knob
(`--control-socket-group`/`CONTROL_SOCKET_GROUP`, the live unix socket
re-modes 0600/0660 — the dashboard could not share its control socket
with a local group before); the dump/reload state carries the listener
and `show config` renders the live values. The per-tool
`resolve_control_target` wrapper died (the parsers unified in
`common/settings/config.py`, one signature — `listen_port` + the socket template).

The F21 closure: **the page takes a bearer token** — `--auth-token`
(`auth/token` live, a secret) gates every GET on the main listener
(page, static, config.js, the /prom proxy) constant-time; the
`?auth=<token>` bootstrap exchanges for an HttpOnly session cookie and
the raw Bearer header stays for scripts; the default `--bind` is
`127.0.0.1` and a token-less non-loopback bind refuses to start (the
scraper's F13 shape is the family's golden master). The demo compose
rides a generated `page.token`; the NixOS module gained
`authToken`/`authTokenFile`. The /metrics F6 posture moved to the F13
shape in the same sweep (docs/AUDIT.md rev. 20-21).

The F13 conformance: **the /metrics token is mandatory beyond loopback,
not whenever on** — the startup refusal, the live `metrics-server on`
and the live `metrics/token` off fire only for a non-loopback bind
without a token; the loopback default serves tokenless (the scraper's
F13 refusal is the family's golden master; F6's mandatory-when-on
retires — docs/AUDIT.md rev. 20 records the move on the closure).

The show-status removal: **`show status` is gone** (nothing replaces it) —
the registry row, the dispatch branch and the key=value report body die;
the per-setting `show <setting>`, `show config`, `inspect` and the
set/unset replies carry the same truths. The cli console greets with the
two fixed lines (the banner's status line rode the report).

The welcome-alignment wave: the console's greeting runs the cache's
segment order — the `client(s)` count moves behind `running for` (the
status line reads upstream, its health, `running for`, the trailing
count; the `upstream (yes)` health spelling keeps the dashboard's own
voice) — and the hint line is the family's one shape.

The status-face wave: the wire's reply status speaks **`ok` | `fail` |
`bye`** (the internal 'err' maps at the frame, the mac signs the wire
form), the console prints the ok messages bare and the failures as
**`% error: <message>`**, the set/unset pair confirms **`% changed`**, and
the wire's help branch speaks the commands (`help unset` describes the
row, `help request` lists the namespace, the unknown topic answers
`unknown command or setting <words> (try ?)`).

The request-namespace wave: the control grammar's commands are `/`-paths
spelled as words on the wire — `reload` renamed to `request reload` (the
exec dance; the bare spelling answers `err unknown command`) and the
config re-read (the SIGHUP path — a different action) rides on as
`request reload-config`; the registry's command rows drive the console
completion segment-wise and the RBAC verb is the word past the `request`
prefix. The console cli joined the family's golden ladder (the shared
candidates walk, the pools, the describe order) and every help surface —
`--help`, the man pages, the registry helps — stopped stating default
values (the README's flag/default tables are the reference).

The `-file` sibling removal: **`file:` is the one spelling** — the
dashboard's `--control-token-file`/`--control-ops-token-file`
`/--metrics-token-file` flags, their env twins and the live `-file` keys
are GONE (still experimental — behaviour may change). Every token knob
takes the inline string or a `file:<path>` reference (the same loader and
0600 discipline the siblings enforced, F12), the secret-error strings say
"by flag/env, or as `file:<path>`", and the NixOS module renders
`--control-token file:/run/credentials/...` (the option names stay).

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
shared seal in common/settings/dump.py, stdlib only), a restore fails closed on a
wrong or missing key — and on an unsealed dump under a configured key.

The secret-placeholder wave: an overridden secret rides the state dump /
the reload state file as `*** SECRET REMOVED ***` (the value never lands
in a file — the restore skips the placeholder and names it),
`show config` marks the configured secret rows the same way (the entry
passes the control server the secret rows' configured-ness), and the
placeholder refuses to parse as a value.

The state-machinery wave: `dump_settings`/`apply_dump_settings` land on
the control server — the **state dump** (`dump/path`,
`dump/restore-on-start` lives + the `--dump-path`/`--restore-on-start`
flags/env/NixOS options; `request dump`/`request restore` write and
re-apply the live overrides as one 0600 integrity-hashed JSON,
common/settings/dump.py; the graceful shutdown dumps too), the **whole-daemon
`reload`** (the overrides save to `<config>.reload`, the process re-execs,
the fresh daemon re-applies them once and consumes the file — the ops
role may not reload), and the **secret lives**: `control/token`(-file),
`control/ops/token`(-file) and `metrics/token`(-file) rotate live (the
sessions re-auth; the F6 rule stands — the endpoint's token is mandatory
while it serves), the secret defaults placeholders are gone (unset
refuses) and **`show <secret>` refuses** — the value renders nowhere.

The show-settings retirement: `show settings` is gone — the per-setting
`show <setting>` and `show status`'s `overridden=` row carry the same
truth, the command answers `err unknown setting` (the registry row, the
daemon help lines, the man pages, the README and the suites follow).

The registry-folding wave: `lib/settings.py` is gone — the control
grammar's vocabulary rides the `lib/options.json` rows and `lib/options.py`
derives `SETTINGS`/`describe_setting` from them (the wire, the completions
and the word help unchanged).

The env-prefix retirement wave: the env twins are the bare upper-snake
names — the docker-documented generic set (`PORT`, `BIND`, `PROM_URL`,
`CONFIG_JS`, ...) IS the set then, no `DSH_` duplicates beside it; the
registry, the resolver, the ctl/cli clients, the docs and the man pages
follow. (Since retired further: `PORT`/`BIND` died with the
`--listen` unification — the twin is `LISTEN`, the live path
`system/listen`.) The shipped `config.js` `batteryFlag` selector asks for
`scraper_battery` (the metrics wave's rename, propagated — the retired
`huawei_battery` gauge no longer answers).

The declarative-registry wave: the knob rows (the name, the flag, the env
twin, the section, the live/secret markers and the descriptions) moved to
`lib/options.json` — `lib/options.py` loads them onto the common `Option`
rows and keeps the Python-side wiring (the control-grammar verb list, the
audit defaults and the log-level choices read from `static.json`) — and
`--help`/the man pages render from the registry now
(`common/settings/options.py` `build_parser()`): the knob description lives exactly
once. The flags in `--help` order by the registry's sections; the texts,
types and defaults are unchanged; `scripts/check_options.py` gates as
before and the package ships the JSON next to the loader.

The rename + env-prefix wave: the bins carry the man-page names now
(`dashboard.py`, `dashboard-ctl.py`, `dashboard-cli.py`), and every env
twin wears the tool's prefix (`DSH_*`) — the generic docker envs
(`PORT`, `BIND`, `PROM_URL`, `PROM_PREFIX`, `STATIC_DIR`, `CONFIG_JS`,
`BATTERY`) are retired for `DSH_PORT`/`DSH_BIND`/`DSH_PROM_URL`/
`DSH_PROM_PREFIX`/`DSH_STATIC_DIR`/`DSH_CONFIG_JS`/`DSH_BATTERY` (the
compose stack, the Dockerfile and the docker README follow), the
control-port answering to the one short `DSH_CTL` for the daemon and the
clients alike. The constants audit: `log_levels` joined
`lib/static.json` (the metrics-endpoint defaults joined the shipped
defaults too — no hardcoded `127.0.0.1:9452`/16/5 literals in the config
resolution anymore) and every consumer reads the ladder from there.

The knob-dictionary wave: `show knobs` (the `help knobs` alias too) prints
the dictionary of all knobs — every registry knob under its section with
its flag, its env twin(s), its home section, the command that changes it
live (or the restart note for the startup-only ones) and the secret marker
on the tokens (`common/settings/options.py` `knob_dictionary()`; the values stay in
`show config`, the command mapping in `help config`). The dashboard_ctl/cli
TAB completion and `show?` word-help offer the new `show` argument.

The waves: the config-format (the ini is gone — server.conf speaks the
set grammar, `show config` regenerates it, the nix module renders it),
the RBAC verb set (`--control-ops-verbs`), and **the dashboard's own
/metrics endpoint** (`--metrics-server`, off by default, a token
mandatory when on: the uptime, the request counters by status, the
proxied-query total, the client gate) with the live `set metrics-server`
toggle. The per-phase chain closed: config.js grew the
phaseVoltages/phaseCurrents selectors and the page renders a per-phase
health strip with the voltage-unbalance percentage.

The read-only control role: a second token
(`--control-ops-token`/`--control-ops-token-file`, ini
`control_ops_token`, env `DSH_CONTROL_OPS_TOKEN(_FILE)`) beside the
admin one, and its sessions run the show/clear verbs only — the reports
yes, `set`/`unset`/`request reload`/`shutdown` no (`err forbidden: …
needs the admin token`): the ops shift versus the admin key, both audited
(`role=ops`/`role=admin` in the DSH COMMAND entries, the denials
included), each session's frames mac'd with the key it authenticated
with. The NixOS module grew `controlOpsToken`/`controlOpsTokenFile` (the
ExecStart flags, the LoadCredential mount).

The token-file env honored: `DSH_CONTROL_TOKEN_FILE` does what the
clients' help always promised — the env form of `--control-token-file`
on `dashboard_ctl`/`dashboard_cli` (the daemon's config resolved it from
the start; flag over env, the file over the plain token, both together
the mutual-exclusion error).
(Since retired: the env prefixes and the `*_FILE` twins died — the bare
env twin with `file:<path>` inside the plain value is the spelling.)


The control plane (the family set is complete): the JSON-lines control
server on the scraper's pattern (the unix socket by default, the token'd
TCP with the F5 refusal, the peer-cred shortcut, the signed wire), the
live settings (the caps, the log surface, the battery flag), `show
status/connections/settings/version`, `inspect`, `request reload` (the
SIGHUP path), `shutdown` — with `dashboard_ctl`/`dashboard_cli` (the
one-shot and console clients), the DSH audit trail, the man-page
generator + `--man`, and the HTTP surface's connection gate
(`--max-clients`/`--client-timeout`/`--max-conn-per-ip`, refusals 503).
The NixOS module grew the matching options and joined the hardening VM
check; the docker image ships the ctl/cli; `tests/dashboard-control-fuzz.py`
covers the wire.

The read-only dashboard: the Prometheus proxy with the prefix rewrite and
the query API, the generation/consumption/battery/grid panels, the static
JSON constants (lib/static.json), the bin/ lib/ split, the NixOS module,
the Docker compose service.
