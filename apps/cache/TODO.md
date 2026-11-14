# TODO (cache — the Done/history records)

The open items live in the family-wide [TODO](../../docs/TODO.md) (tagged
`[cache]`); this file keeps the tool's shipped history.

## Done (the highlights; the git history has the details)

The manual moved to the operator packs, then retired (Nov 14): the
page is gone — the reference is the daemon's `--help` and the man page
(`modbus-cache --man`); the README points there.

pvsuite-cli: the tool's cli bin (`modbus-cache-cli.py`) became a symlink to
the family dispatcher `apps/pvsuite-cli.py` — the tool's SPEC half
(the pools, the labels, the defaults, the per-entry cache-all pager render)
moved to `lib/cli_spec.py`, and the dispatcher resolves the tool from
the invoked name or the first word (`pvsuite-cli cache` or the daemon
name; a word that disagrees with the invocation name is refused).
The console surface, the man page and the MANUAL render unchanged;
the Dockerfile copies the dispatcher via the new `cli` build context
and the nix package installs it by store path under the client's
name (the wrapper's argv[0] inference keeps working).

The help-canon wave moved the registry's family-wide texts to
shared/suite/options.json: 50 rows reference their canon block (`shared`:
"<name>") and the loader folds the block under the row's own fields —
the per-tool prose (the dump family's cached words, the ops role's
show,flush policy) stays inline as the override. The alignment restored
the audit-max-mb "keeping N backups" tail and adopted the trail wording;
the metrics-max-clients spelling settles on the /metrics form. lint_options
--check gates the fold three ways (the resolution, the must-ref, the
byte-for-byte drift with the named exemptions) and the editor speaks the
canon (the ref edits, the block-carried fields show marked (canon), the
p walk proposes the ref).

The console-pager wave put every cli render through one door
(common/wire/cli.py's page_out): a reply taller than the screen pauses at a
page (the cbreak `-- more --` reader, the more(1) keys — space/return/q),
`--page-size`/`CLI_PAGE_SIZE` set the size, the session-local `page` command
retunes it live (never sent — no registry row, audited local), a line wider
than the screen shortens with ` ...` (the wire keeps the tail), and a
terminal under 20 rows/64 columns refuses the tty edition before the connect
(cli_min_height/cli_min_width in shared/suite/wire.json; piped runs print
byte-for-byte and never check). The one-client wave retired the `-ctl` bin
into `modbus-cache-cli`: run_client's three modes by invocation shape (words
= one-shot with the raw verdict head, rc 0/1/2; piped stdin = batch; bare
tty = the console), the HEALTHCHECK and the README/nix spellings follow.
The regtest carries the pager pins (the pure arithmetic + the pty smoke: the
pause, the live page command, the floor refusals, the cap, the daemon audit
proving page never rode the wire) and the batch/console re-pins; the
console-only furniture (the confirm guard, the idle keepalive, the local ?
shapes) rides the pty helpers in tests/harness.py.

The NixOS settings wave inverted the module (nixos/modules/
modbus-cache.nix): the ~40 dedicated knob options are gone — one freeform
`settings` attrset renders verbatim `NAME=value` lines into the unit's
systemd EnvironmentFile (the keys are the bare env twins; restartIfChanged
now — EnvironmentFile is start-only, the SIGHUP ExecReload stays), the
secrets keep only the `<secret>File` credential options (authKeyFile,
authUpstreamKeyFile, controlTokenFile, controlOpsTokenFile, metricsTokenFile,
dumpKeyFile — absolute paths outside the store; the inline value options are
removed-option tombstones the eval refuses, and a `/nix/store/` source
errors too; a secret env name inside settings errors as well), the module
ships default-free (`package` via the flake's mkDefault wrapper — the
nixpkgs shape), the ReadWritePaths/ RuntimeDirectory derivations read
AUDIT_LOG/DUMP_PATH/CTL back out of settings, and the option tables moved
to nixos/README.md.

The external surfaces speak the console spellings (the flat wire's
completion): the one-shot ctl translates the live/alias words like the
cli's (`set acl connect any` rides the wire as `set connect-acl any` —
a piped config script's live-word lines work), `show config` renders
the live paths as words, `help config`/`show knobs` and the MANUAL +
OPTIONS tables spell the console words in their set columns, and the
state dumps + the reload state file key the live paths (`acl/write`) —
the flat names read beside them on restore. The wire itself stays flat
(the match map, the replies, the listings).

The wire speaks the flattened registry names: the dispatch, the
dumps, the defaults and every reply key/render the options.json `name`
(`interval`, `write-acl`) — the live paths and the alias are the
console spellings the cli translates before it sends, and the raw wire
refuses them. `show config`, `help config`, `show knobs` and the
node/bare-show listings render the flat names; the old dumps restore
(the live-path keys fold on the way back in).

The README moved to the gated skeleton: `scripts/lint_readmes.py --check`
pins the `##` canon family-wide, and the cache came to it — the
`Diagnostics registers` and `Register map (device profile)` sections
relocated into the feature slot (right after Runtime control), and the
flags table's `--profile` row links the map instead of pointing "see
above".

The audit family live family-wide (the template's role): the dump's
seven audit rows fold the shared `audit_dump_rows()` — one shape on all
four tools (the scraper/fake/dashboard gained the daily row) — and
`clear audit/log-file`'s default spells the apply-valid raw `-`/`none`
instead of the display words (`stdout`/`remote` re-applied as paths).

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
compose `shared/suite/texts.json` byte-honest (the suite pins kept their
bytes). The cache-specific keeps: the dump pair stays the proxy's (the dumper loop reads the proxy's homes), the metrics enable/caps branches stay (the proxy plumbing), and a live `set audit log-file -` spells stdout now (the raw spelling — the XDG fold was the drift).

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
`common/runtime/audit.py` (the wire, the argparse gates and the NixOS
module's check speak the same one-liner), the row pair is live
(`audit/forward`, `audit/forward-format`), and the audit-chain suite
gained the collector harnesses (the framing, CEF, UDP, the re-arm, the
remote-only e2e).

The config re-read joins the wire family-wide (`request/reload-config`,
the grammar follow-through): the SIGHUP body extracts into the bin's
`apply_reload` — the map swap, the override-marker clear and the RELOAD
audit — and the control server's `control.reloader` runs the same path
on the wire; the dump loop re-reads the configured interval on that
path now (the wake it was missing). The signal set rides the family's
shared watcher (`common/runtime/daemon.py`): SIGHUP + SIGUSR1 + the
graceful stop install from one call (the SIGTERM reason spells
`SIGTERM` now), the reload-failure audit riding the hook. The registry
row lands beside `request/reload`, `reload-config` joins KNOWN_VERBS
(the ops default stays show,clear), the ctl/cli helps + the man prose
+ the README rows follow, and the spine's reload-config reply catches
the resolvers' SystemExit (a broken config file answers
`err reload failed` instead of killing the session).

The audit forwarding (`--audit-forward syslog`, the F10 follow-through):
the trail can mirror every line — the per-writer hash chain included —
to the local syslog socket as it lands, journald picking them up sealed:
the journal copy survives the box, the sink stays the authority. The
machinery is shared (`common/runtime/audit.py`: the fail-loud
`SysLogHandler` subclass — the stdlib swallows send failures into a
per-event traceback —, the socket candidates, the one-note fail-stop),
the row is live on the wire (`set audit forward syslog`, live
`audit/forward`, env `AUDIT_FORWARD`), a socket-less spelling refuses to
start with the family's one-clean-ERROR shape, and the live audit swaps
now rebuild the running writer on every knob (the rotation sets updated
the params but not the writer before — this tool already rebuilt, the
family does now).

The alert rules pack: the cache contributes its side to the family's
pack ([`../../extras/alerts/cache.yml`](../../extras/alerts/cache.yml), the F16
closure — installed with this package as `share/alerts.yml`)
— and the missing metric landed first:
`modbus_cache_write_refused_total` on the cache's own /metrics counts the
gate refusals (allow-write off, the write ACL, the register allow-list, a
malformed frame) — each one a `WRITE-REFUSED` audit event. The pack's
`CacheWriteRefusalBurst` watches the burst, `CachePollDown` and
`CacheAgeSpike` the poll health; the group stays silent until the
endpoint is scraped.

The audit-family wave: the cache is the audit family's golden master and
stays it — the rotation bounds (`audit-files` 1..100, `audit-max-mb`
0..1048576) now live once in `common/runtime/audit.py` with the startup
fail-block reading them (was the hardcoded 0/1), and the Modbus accept
ladder rides the shared `serve_modbus` (common/modbus/server.py) — the
proxy keeps only its face hooks (the forwarding dispatch, the in-band
malformed answer, the REQUESTS unwind evidence); the refusal texts are
the family's one texts by construction.

The secrets-startup-only wave: every secret row (auth-key,
auth-upstream-key, control-token, control-ops-token, metrics-token,
dump-key) is `restart`-marked and the wire refuses set/unset on it with
the dump-key answer — the live rotation branches and their render-backs
are deleted, the floor checks (min-16, ops ≠ admin, F13) stood at start
already, and the set-advice errors point at flag/env/config + a restart;
the regtest respawns with the desired tokens instead of rotating (the
waveshare wrong-password matrix rides fresh instances); `help config`
renders the startup-only recipe.

The man-ladder wave: the page runs the family's one daemon ladder
(NAME … OPTIONS, SIGNALS, CONTROL, SECURITY, ENVIRONMENT, FILES, EXIT
STATUS, SEE ALSO) — the posture prose carves out of DESCRIPTION/CONTROL
into a new SECURITY (the F5 refusal, the signed wire, the ops token,
the secret rule, the write gate's audits, the IP gates, the dump seal,
the audit trail), the ctl page gains its ENVIRONMENT twins, the EXIT
STATUS row names the failed-bind rc 1, and `common/render/manpage.py`'s
LADDERS gate (`page(kind=...)`) refuses a page that drifts. The ctl
EXAMPLES' `printf` pipeline renders its `\n` for the first time.

The shared acl example/schema wave: the ip-prefix pair moves to the repo
root as the family's one shared copy (`examples/acl-ip-prefix.json` +
`schema/acl-ip-prefix.schema.json` — the four per-tool copies die);
`package.nix` installs from `../examples` + `../schema` (the packaged
`share/modbus-cache/` layout unchanged) and the regtest's `file:` rounds
read the root file.

The docs restructure wave: the README re-laid on the family's one skeleton
and shortened (965 → ~430 lines) — the Nix/NixOS section moved to
[docs/NIXOS.md (now nixos/README.md)](../../nixos/README.md) (the module's option list rebuilt from
`module.nix`: the README's had gone stale — it predated the metrics ACL,
the dump knobs and the control-plane options), and the family-wide
stories (the ACL grammar, the Modbus handshake, the audit chain
mechanics) now point at docs/specs/ACL.md / docs/specs/MODBUS.md / docs/SECURITY.md
instead of re-running them.

The metrics/acl family wave: the cache rides along — the default
metrics bind moves `9252` → **`9351`** (the family's /metrics defaults
count from the scraper's 9350 up; the fake and the dashboard join the
gate with the shared 9452 split), and `package.nix` now ships the three
`schema/*.schema.json` files beside the examples (they were the only
schemas not installed).

The control-listener family wave: the cache's listener tier — the live
`control/port` rebind family, the socket-mode discipline, the live
control knobs — lifts into `common/wire/control.py` as the family's ONE
implementation (the golden master gives the shape away; the private copy
sheds), the F5 refusal parameterizes as `TOKENLESS_TCP` (the fake opts
out — F11), and the ops-verbs live name re-spells to the family's
**`control/ops/verbs`** (the scraper's nested form; the knob name and
the config files stay flat — `set control ops verbs <list>` on the wire).

The F13 conformance: **the metrics token is mandatory beyond loopback,
not whenever on** — the startup refusal, the live `metrics/enable on`,
the live `metrics/token` off and the restart-marked `metrics/listen`'s
pending check all fire only for a non-loopback bind without a token; the
loopback default serves tokenless (the scraper's F13 refusal is the
family's golden master; F6's mandatory-when-on retires — docs/SECURITY.md
rev. 20 records the move on the closure).

The show-status removal: **`show status` is gone** (nothing replaces it) —
the registry row, the dispatch branch and the key=value report body die;
the per-setting `show <setting>`, `show config`, `inspect` and the
set/unset replies' state summary carry the same truths. The cli console
greets with the two fixed lines (the banner's status line rode the
report) and probes `show dump path` for the dump-gated completion pools.

The metrics/acl wave: **the /metrics endpoint takes the IP plane** —
`--metrics-acl` (env `METRICS_ACL`, config `metrics_acl`, NixOS
`metricsAcl`, live `set metrics acl` / `unset metrics acl`) migrates the
scraper's metrics/acl wave onto the cache's own exposition: the
`acl/connect` value grammar (`any` the default, `none`, the whitelist,
`file:<path>` the standalone ip-prefix acl file), checked at accept
beside the connection caps — a client off the ACL is closed without a
reply (logged `connection rejected: … not on the metrics ACL`), the file
gate re-resolves on every set/unset and on SIGHUP (a bad file keeps the
old gate standing; an inline set clears a standing file warning — the
shared `_resolve_ip_acl` resets the stash now, so `acl/connect` and
`acl/write` speak the same fresh-state semantics), a group/world-readable
file warns (the log, the audit trail's `ACL-FILE` event, the reply's
suffix), and **`show metrics acl table`** renders the gate as its chain.
The accept hooks ride the common MetricsServer
(`acl_allows`/`acl_refused` delegate to the instance — the defaults admit
every peer and close silently, the dashboard's endpoint untouched), and a
bad acl file at start refuses clean (SystemExit — was a traceback).

The show-config write-back wave: **`show config` speaks the live
overrides** — the `_apply` branches changed the running values but never
wrote back into the resolved config dict the render reads (only
unit/auth/timeout and the ACLs honoured the `show_config_cfg` contract),
so a live `set metrics enable on` rendered `set metrics enable false` in
the script while `show metrics enable` answered `on`. Every live branch
writes back now and `unset` restores the configured value through the
same branches; the metrics token resolves into the dict at start, so its
`*** SECRET REMOVED ***` row renders like the control token's. Two more
faces of the same drift: the `write-registers` `profile`/`file:<path>`
markers crashed `show config` (the renderer formatted the marker string
as a range list — the handler died mid-reply), and **`audit/requests`
was dead on the wire** (the live-rename wave rekeyed every branch to the
live names but missed this one: `set audit requests 120` answered
`err unknown setting`, `show audit requests` answered `?`, the unset
table and the dump key kept the dashed spelling) — the branches, the
unset default, the dump key and the README/man spellings take the live
name now.

The ip-prefix acl wave: **`acl/connect` and `acl/write` read
`file:<path>`** — the standalone ip-prefix acl gate (the shipped
`examples/acl-ip-prefix.json` shape: `"type": "ip-prefix"`, `prefix`
rules) evaluated in the connect and write logic as a chain — the last
matching rule decides, a client no rule decides refuses (the default deny
any; the matcher word `any` is the whole space, `0.0.0.0/0`). The
missing or bad file refuses the start and answers `err` on the wire with
the old gate standing, the spelling round-trips through the dumps and
`unset`, and a group/world-readable acl file warns (the log, the audit
trail's `ACL-FILE` event, the set/unset reply's suffix). The new
**`show acl connect table` / `show acl write table`** reports
(show-only) render either ACL as its chain, one entry per line: the
system forms spell the chain they implement — `allow 0.0.0.0/0` (any),
`deny 0.0.0.0/0` (none), `deny 0.0.0.0/0` then one `allow` line per
network (the whitelist) — and a file gate renders its own rules (the
gate desc as the `% ` line, the rule descs as aligned `# ` comments).

The acl whitelist wave: the device profile's write acl re-shapes to the
**typed rule chain** — `"acl": {"write": {"desc": ..., "rules": [...]}}`,
one `{"type": "allow"|"deny", "range": matcher}` object per rule (the
matchers keep their shapes: a `START:COUNT` range, a list of them, a
`{ "START:COUNT": "desc" }` map describing each entry, or the bare word
`any`/`none`; the terse-ASCII `desc` rides per gate, per rule and per map
entry) — and the chain is a **whitelist, said out loud**: the last
matching rule decides and a register no rule decides refuses (the default
deny any). The old spellings (the allow/deny object whose absent allow
was `any`, the `{"allow": ...}` chain keys) refuse to load; the shipped
`deye-sg05lp3` migrated in the same wave. The new **`show write registers
profile`** report (show-only — nothing to set) answers the write gate as
its chain: `allow any` / `deny any`, a range list as its whitelist (deny
any, then one `allow START:COUNT` line per range), and in profile mode
the profile's own rules — the gate's desc as the `% ` line, one
`allow|deny <range> # desc` line per range, the comments aligned. The set/unset verbs match the
knob rows only (`SET_BY_NAME`), so the report's live path never shadows a
knob value — `set write registers profile` keeps handing the knob the
word — and a bad `set write registers <value>` answers `err` now instead
of dropping the control session (the parser's SystemExit is a ValueError
on the wire). The wave's follow-up: the gate also reads from a
**standalone acl file** — `--write-registers file:<path>` (env, config
and the live `set` the same) — the file IS the gate object a profile
carries under `acl`/`write`, read and compiled at start and on every
`set` (a bad file refuses the start, answers `err` with the old gate
standing; the spelling round-trips through the dumps and `unset`, and
the show report renders the file's rules like the profile's).

The status-face wave: the wire's reply status speaks **`ok` | `fail` |
`bye`** — the internal 'err' verdicts map to `fail` at the frame (the mac
signs the wire form), the console prints the ok replies' messages **bare**
(quiet success — the `show`/`inspect` bodies already were) and the
failures as **`% error: <message>`** (was `% err …`); the set/unset pair
confirms **`% changed`** (the one ok face keeping the marker; the echo and
the status-summary tail stay discarded), the startup-only note keeps
`% restart required …`, the local `ping` answers bare `pong`, and the
`request clear cache`/`request restart` confirms went fully silent. The
wire's help branch speaks the commands now: `help unset` describes the
row, `help request` lists the namespace (the ? shape), the unknown topic
answers `unknown command or setting <words> (try ?)` — the registry's
command rows drive it (the `request/dump` node's placeholder prose landed
with it).

The request-namespace wave: the control grammar's commands are `/`-paths
spelled as words on the wire — `clear cache`/`reload`/`restart` renamed to
`request clear cache`/`request reload`/`request restart` (the bare
spellings answer `err unknown command`), the registry's command rows
(`request/dump`, `request/dump/with-cache`, `request/restore`,
`request/clear/cache`, `request/reload`, `request/restart`) drive the
console completion segment-wise, and the RBAC verb is the word past the
`request` prefix (the ops shift keeps the flush, never gains the dance).
The console cli joined the family's golden ladder (the shared candidates
walk, the pools, the describe order) and every help surface — `--help`,
the man pages, the registry helps — stopped stating default values (the
README's flag/default tables are the reference).

The `-file` sibling removal: **`file:` is the one spelling** — the
`--control-token-file`/`--control-ops-token-file`/`--metrics-token-file`
flags, their env twins and the `control/token-file`-style live keys are
GONE (still experimental — behaviour may change). Every token knob takes
the inline string or a `file:<path>` reference (the same loader and
0600 discipline the siblings enforced, F12), the secret-error strings
say "by flag/env, or as `file:<path>`", the NixOS module renders
`set control token file:/run/credentials/...` (the module option names
stay), and the bundled conf sample speaks the reference form.

The bit-space + float wave: the cache **polls, caches and serves FC1
(coils) and FC2 (discrete inputs) ranges** beside FC3/FC4 — a profile
`bit` entry (one address = one binary value) rides the same map, block
planner (merged per space, 2000 bits per read) and TTL machinery, a
forwarded FC1/FC2 read caches on the way through (bits stored as 0/1
words, packed 8-per-byte LSB-first on the wire), and the write-through
invalidation sweeps **both register spaces** for FC06/16/22/23 and the
coil space for FC05/15. A forwarded FC15/FC16 frame whose byte count lies
about its data is refused at the cache (exception 03, audited) instead of
reaching the device; the exported `READ_FUNCS` static is the actual read
dispatch now (the FC1-FC4 hardcode is gone); and the `--allow-write`
help text names all six write codes (FC05/06/15/16/22/23) it has gated
since the write-acl wave.

The Waveshare upstream-auth wave: **`--auth-upstream waveshare`** — the
cache presents the shared auth-upstream-key as a **Waveshare
RS485-to-TCP gateway's connection password** (the upstream-only scheme
beside suite/none): the password goes out raw (ASCII bytes, no framing)
right after every (re)connect and the gateway's `OK` opens the plain
Modbus session; anything else or silence (the socket timeout bounds the
wait) fails the exchange like any other upstream fault and the poller
retries. The handshake is `waveshare_handshake_client` in
`common/protocol.py`, beside the suite pair; the key's floor is the
scheme's (suite ≥ 16 characters, waveshare non-empty ASCII, a key with
no scheme yet dormant); the live `set` enforces the pair's invariant
(including refusing to go `suite` over a short standing key).

The profile write-acl wave: **`write-registers` speaks the device
profile** — the new `profile` value compiles the register gate out of the
profile's `"acl"`/`"write"` tree: an allow/deny object (the deny wins, an
absent allow is `any`) or an ordered rule chain (`allow`/`deny`
rules — a `START:COUNT` matcher, a list of them, a
`{ "START:COUNT": "desc" }` map describing each entry, or the bare word
`any`/`none`; an optional terse-ASCII `desc` per gate and rule) — the
chain reads top to bottom, the LAST matching rule decides and an
undecided register refuses (the default deny). The shipped `deye-sg05lp3` profile allows exactly the TOU schedule
slots (148–177) and the grid-start registers (127–128), each entry
described. The gate re-resolves when the profile swaps live and refuses a
profile without the section; `show write registers` answers `profile`
(the re-appliable spelling for the dumps and `unset`), the status, the
inspect and the start log render `profile (127:2,148:30)`.

The Modbus auth wave: the cache **speaks the `suite` scheme on both
legs** — `modbus/auth` + `modbus/auth/key` demand the crypt handshake from
its own clients (a failed proof is dropped before it ever sees a frame,
logged `suite auth failed for …, closing`) and
`modbus/auth-upstream` + `modbus/auth-upstream-key` present it to the
inverter (an `ERR` fails the exchange like any other upstream fault). The
handshake is one round trip after every connect: 52 bytes — the `PVA1`
magic, a fresh nonce, the HMAC-SHA256 proof of the shared key (min 16
characters, secret-marked, `file:` referenceable) — and the peer's `OK`
or `ERR` decides. The knobs are live (`set modbus auth …` gates the next
connection; `set modbus auth-upstream …` drops the session so the next
exchange re-proves), `show status` carries `auth=`/`upstream_auth=`.

The file-reference wave: every secret value takes the **`file:` form** —
`--dump-key file:/path` (env, config, the live `set` too) reads the first
line of an owner-only `0600` file by the same loader the `-file` sibling
knobs enforce (a systemd LoadCredential rides as `file:/run/credentials/...`):
the config carries the reference, never the material, and an unreadable
reference fails fast. A dump path without a key keeps the plaintext
posture **by design** — and warns: a `WARNING` at start and a
`(not sealed)` note on the `set dump path` reply.

The seal wave: the state dumps **encrypt under `dump/key`** when it is set
(`--dump-key`/`DUMP_KEY`/`set dump-key` — startup-only, restart-marked,
hidden: the key cannot drift between the writer and the re-exec'd reader):
the cached words and the settings ride a version-2 envelope's `box` (an
HMAC-SHA256 counter-mode keystream + the mac — the shared seal in
common/settings/dump.py, stdlib only), a restore fails closed on a wrong or missing
key — and on an unsealed dump under a configured key; the reload's state
file rides the shared writer/reader and seals under the same key.

The secret-placeholder wave: **the secret knobs render as
`*** SECRET REMOVED ***`** — the state dump (and the reload's state
file) carries an overridden secret's key with the placeholder value (the
value never lands in a file; the restore and the reload's fresh start
skip it and name it in the skipped list), `show config` renders every
configured secret row as `set <name> *** SECRET REMOVED ***` (the
trailing hidden-note line is gone — the placeholder line is the marker),
and the paste-back is gated both ways: the config parser refuses the
placeholder as a value and so does the wire `set` — a rendered script
piped back cannot poison a secret with a known constant.

The FC-awareness wave: **every function code is named** — the shared
`FC_NAMES`/`describe_fc()` table in common/protocol.py, the cache's
`describe_write()` covering all six write FCs (FC05/15/22/23 joined
FC06/16 — the coil bits, the mask write's and/or masks, FC23's write
span + read-back, the malformed shapes named per-FC), the named
`forwarded FC17 (report slave id), …` line for a frame with no cache
semantics (was silent), the named refusals and device rejects, and the
fake's rejects carrying the FC's name (a malformed FC06/16 answers
exception 03 with a malformed-frame note — the log said illegal
function for both). The fix riding along: **the write allow-list vets
FC23's WRITE span** — the second address pair; the read span riding
first was vetted instead, letting a frame write outside the list.

The show-refusal wave: **`show <secret>` refuses** — `show control/token`
(the ops token, the metrics token, the `-file` spellings) answers
`err <name> is a secret — it never shows` instead of the `<set>` guard's
placeholder: the value renders nowhere (the set reply keeps `<set>` as
the rotation's confirmation; the `?`/help still describes — the
vocabulary is public, the value is not).

The reload wave: the whole-daemon `reload` verb — the live overrides save
to `<config>.reload` (created **0600 explicitly**: the file is
config-equivalent trust at rest, docs/SECURITY.md rev. 9's F23), the process
re-execs with the same argv, the fresh start re-resolves the config (the
`restart: true` knobs take their configured values) and re-applies the
saved overrides once, consuming the file (a state older than two minutes
discards as stale). The bundled `modbus-cache.conf` rebuilt in the CLI
spelling (every line `set <path words> <value>`; the sample's
`set audit requests` line included), and the registry rows lost the
`section` field — the display `group` is the one grouping.

The control-plane/audit/dump live wave: the whole control family answers
the wire — `control/port` rebinds the listener live (bind-first, the old
loop retires by identity; `off` stops accepting while the sessions keep
serving), the admin and ops tokens rotate on the wire (the secrets answer
`<set>`, `unset` refuses, the dump never carries one), `control/ops/verbs`
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
`common/settings/config.py` `parse_upstream()`) — `--host`/`--port` and their
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
(`common/settings/options.py` `build_parser()`): the knob description lives exactly
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
on the tokens (`common/settings/options.py` `knob_dictionary()`; the values stay in
`show config`, the command mapping in `help config`). The cache_ctl/cli
TAB completion and `show?` word-help offer the new `show` argument.

The config-format wave: the ini is gone — the config file is a
set-grammar script now (every line a `set <name> <value>`, `#` comments
stay comments, the file pipes through cache_ctl unchanged), `show config`
regenerates it from the running daemon (the secrets hidden), `help config`
maps every knob to its control command, and the option registry
(lib/options.py on common/settings/options.py) files every knob under the shared
sections — scripts/check_options.py gates the flags/env/nix/README
surfaces against it. The RBAC verb set is live too: `--control-ops-verbs`
(default show,clear, validated at start; the wire spells it
`set control ops verbs`).

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
(Since retired: the env prefixes and the `*_FILE` twins died — the bare
env twin with `file:<path>` inside the plain value is the spelling.)


The **signed wire**: with a control token configured every command and
reply on the control socket carries the full sha256 HMAC of its payload
keyed by the token (`common/wire/wiresec.py`) — over TCP the signed commands
are mandatory (an unsigned or bad-mac frame is refused), on the unix
socket the mac is verify-if-present (the peer-cred trusted peers keep
speaking without the secret); the cache_ctl/cache_cli clients sign and
verify both directions, and the audit trail's COMMAND entries carry the
frame's mac (`wire=h…`). The man pages are generated now
(`common/render/manpage.py`: the OPTIONS section renders from the parser, the
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
