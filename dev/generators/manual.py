#!/usr/bin/env python3
"""Render extras/manuals/<daemon>.md — one page per daemon: every command,
knob and show report its control wire answers, the kind of each
(command, namespace, settable — set/clear — or show-only), the flag and
the env twin, the default, the value shape and the description — from
the per-tool registries (lib/options.json via lib/options.py, the
one-knob-one-source rows) — plus the reference sections the front-page
READMEs no longer carry (the run-it lines, how it works, the signals,
the metrics, the audit trail, the testing). The files are GENERATED:
edit the registry or the REF data below and re-run, never the markdown.

  python3 dev/generators/manual.py          # render the five pages
  python3 dev/generators/manual.py --check  # exit 1 when a shipped page drifts

Stdlib only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # dev/ — the common lib rides there
from lib import REPO
from lib.emit import emit
from lib.registry import folded as fold_rows, raw as raw_registry, wired

# the daemons in the chain order the README tells: fake -> cache -> scraper,
# then the dashboard that renders the numbers, then the replay sidecar —
# the tool dir, the daemon name, the bin whose --man carries the startup
# surface, the one-line blurb, the cli bin (None = the no-control-plane
# sidecar), the default control socket, the one-shot example (port +
# command, the bins' docstrings' own), whether TCP control refuses to
# start without a token (F5; the fake is the F11 exempt) and the bundled
# config script (the bundled sample's checkout path, examples/; None for
# the replay — no config file)
TOOLS = (
    ('cache', 'modbus-cache', 'modbus-cache',
     'A dependency-free (Python stdlib only) Modbus TCP caching proxy for '
     'single-client devices: it polls the inverter once and serves every '
     'client from the cache.',
     'modbus-cache-cli', '/tmp/modbus-cache-15502.socket',
     '15509', 'request flush cache', True, 'apps/cache/examples/modbus-cache.conf'),
    ('scraper', 'modbus-scraper', 'modbus-scraper',
     'A dependency-free (Python stdlib only) Prometheus exporter that polls '
     'a Modbus device and exposes the metrics at /metrics.',
     'modbus-scraper-cli', '/tmp/modbus-scraper-9350.socket',
     '15509', 'request poll now', True, 'apps/scraper/examples/modbus-scraper.conf'),
    ('inverter', 'fake-inverter', 'modbus-fake-inverter',
     'A dependency-free (Python stdlib only) Modbus TCP server that plays '
     'an inverter — the battery, the smart meter, the diagnostics — for '
     'the family to develop and test against.',
     'modbus-fake-cli', '/tmp/fake-inverter-5502.socket',
     '15599', 'show registers', False, 'apps/inverter/examples/modbus-fake-inverter.conf'),
    ('dashboard', 'dashboard', 'dashboard',
     'A single-page dashboard for home PV monitoring, fed by Prometheus: '
     'it serves the page and proxies the upstream queries.',
     'dashboard-cli', '/tmp/dashboard-8080.socket',
     '15598', 'request reload-config', True, 'apps/dashboard/examples/dashboard.conf'),
    ('modbus-replay', 'modbus-replay', 'modbus-replay',
     'A dependency-free (Python stdlib only) Modbus TCP capture/replay '
     'sidecar: it pipes the wire to a trace file in capture mode and '
     'serves the trace in replay mode.',
     None, None, None, None, False, None),
)

# the wire words no registry row carries (the registries' own audit's
# finding): the fake's Modbus write emulation — a `set` form that plants a
# value in the write overlay instead of steering a knob
EXTRA_COMMANDS = {
    'inverter': (
        ('set register <addr> <value>',
         'the Modbus write emulation: plant a register value in the write '
         'overlay — reads answer it, reset clears it'),
        ('set coil <addr> <0|1>',
         'the write emulation: plant a coil value (the coil space, '
         'FC1/FC5/FC15 see it, reset clears it)'),
        ('set discrete <addr> <0|1>',
         'the write emulation: plant a discrete-input value (the discrete '
         'space, FC2 sees it, reset clears it)'),
    ),
}

# the reference sections the front-page READMEs no longer carry — the
# front-page split (docs/history/front-page-split.md): the README speaks
# description, usage, security, license; the manual carries the rest, as
# bullets and tables. Per tool: `run` (the run-it section), `how` (how it
# works) and `tail` (the sections after the registry tables). One item
# kind per tuple: ('b', text) a bullet, ('p', text) a wrapped paragraph,
# ('c', block) an indented code block, ('t', head, ...) a table (the
# first tuple the headers, the rest the rows). The containers are LISTS —
# the bracket/paren mix keeps the closes readable.
REF = {
    'cache': {
        'family': [
            ('b', 'the cache is the chain\'s multiplexer: **one client slot '
                  'at the device** (the inverter accepts one Modbus TCP '
                  'client), any number of Modbus clients behind it — the '
                  'scraper polls through it, the write tools and the debug '
                  'sessions share the slot, the replay taps the hop.'),
        ],
        'run': [
            ('c', 'python3 apps/cache/bin/modbus-cache.py --upstream 192.168.1.100:5502'),
            ('b', 'the proxy binds `127.0.0.1:15502` (loopback only) — '
                  '`--listen 0.0.0.0:15502` serves the LAN.'),
            ('b', '`--dry-run` validates the configuration and the register map '
                  'and prints the effective settings without binding the listen '
                  'port or contacting the inverter — handy for checking '
                  'NixOS-rendered config files (`--config /nix/store/…-modbus-cache.conf '
                  '--dry-run`). Exit codes: `0` = valid, `1` = invalid (reason on '
                  'stderr, stdout stays clean), `2` = command-line misuse.'),
            ('b', 'settings resolve flag > env (the bare upper-snake twins) > '
                  'config script > default; boolean config/env values accept '
                  '`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`; every setting '
                  'is validated before use — nonsense values abort with a clean '
                  'one-line error instead of failing later at runtime.'),
            ('b', 'the six secret knobs (`--modbus-auth-key`, '
                  '`--modbus-auth-upstream-key`, `--control-token`, '
                  '`--control-ops-token`, `--metrics-token`, `--dump-key`) never '
                  'render back: the config file, the state dumps and the reload '
                  'state file carry the `*** SECRET REMOVED ***` placeholder. '
                  'Pass each one on every start — by flag, by env, or as '
                  '`file:<path>` (the first line of an owner-only `0600` file; a '
                  'flag value lands in `ps` — the file form is the shipped way, '
                  'the F9/F12 posture).'),
            ('b', 'the bundled `examples/modbus-cache.conf` is GENERATED '
                  '(`dev/generators/examples.py`) — every knob the registry '
                  'declares, every line commented at its default; `show config` '
                  'regenerates the script from the running daemon (secrets '
                  'hidden) and `help config` maps every knob to its control '
                  'command.'),
        ],
        'how': [
            ('p', 'The proxy is a background poller in front of a dictionary: '
                  'one thread polls the device on the configured cadence, '
                  'every client is answered from memory, writes cut through '
                  'with the cache invalidation behind them — and the whole '
                  'story survives a hostile peer on either side.'),
            ('b', 'a background loop **polls the configured register ranges** at '
                  'a fixed interval into an in-memory cache.'),
            ('b', 'any number of clients are **served from the cache** (FC3/FC4 '
                  'words, FC1/FC2 bits); reads outside the cached ranges are '
                  'polled live, answered and cached for `--cache-ttl` like '
                  'everything else — any other function code is forwarded '
                  'untouched.'),
            ('b', '**writes** (FC05/06/15/16/22/23) are forwarded when enabled '
                  '(the four gates, `Access control` below) and always logged '
                  'with register, value(s) and outcome; a forwarded write drops '
                  'the cached words it touched (per-register) and wakes the '
                  'poller — the next read goes to the device, not the pre-write '
                  'value. Register writes invalidate both word spaces (holding '
                  '+ input), coil writes the coil space.'),
            ('b', 'a synthesized **diagnostics block** (registers 65000–65003: '
                  'device-up flag, cache age, uptime) lets clients tell live '
                  'data from cache-served values — the scraper auto-detects it '
                  'and exports it as `scraper_cache_*` gauges.'),
            ('b', '**inverter unreachable** — cached reads keep serving the last '
                  'known values while forwarded reads get Modbus exception '
                  '`0x0B`. Entries older than `--cache-ttl` are refetched on the '
                  'next read.'),
            ('b', '**device rejects a range** — the cache remembers that poll '
                  'status and answers client reads in the range with the same '
                  'exception until a poll succeeds again: no repeated '
                  'hammering, and clients see the failure the device actually '
                  'reports.'),
            ('b', '**garbage from the device or from clients** — malformed '
                  'frames, lying lengths, wrong ids, stalls, pipelined bursts: '
                  'logged one-line and survived; a client cannot crash the '
                  'proxy, only burn its own connection (fuzz- and soak-tested).'),
        ],
        'tail': [
            ('Signals', [
                ('t', ('signal', 'effect'),
                 ('`SIGHUP`', 'reload the configuration and the register map '
                  'without dropping client connections (the wire twin is '
                  '`request reload-config`): the map is swapped atomically, '
                  'poll interval, read delay, merge gap, cache TTL, the ACLs '
                  '(the `file:` gates re-read), limits and the upstream '
                  'address/unit/timeout take effect immediately; a broken file '
                  'keeps the previous settings; the listen address needs a '
                  'restart (the registry\'s restart-marked knobs record a live '
                  '`set` and fold into the restarted process)'),
                 ('`SIGUSR1`', 'clean the cache: all cached values, on-demand '
                  'entries and poll-status errors are dropped atomically, the '
                  'poller repopulates immediately'),
                 ('`SIGTERM` / `SIGINT`', 'graceful shutdown')),
            ]),
            ('Register maps', [
                ('b', 'the proxy caches the registers listed in the **device '
                      'profile** — the same shared schema the fake inverter '
                      'serves and the scraper scrapes; the shipped profiles live '
                      'in the suite\'s `shared/profiles/` data dir (`sun2000.json` '
                      'by default); the format is documented in '
                      '`shared/profiles/README.md`. Resolution: `--modbus-profile` '
                      'flag, env `MODBUS_PROFILE`, config `set modbus profile`, '
                      'then the bundled copy; the file is re-read on `SIGHUP`.'),
                ('b', 'entry `type` gives the width and the space: `i16`/`u16` '
                      '(one word), `i32`/`u32` and the lo-word-first '
                      '`i32swap`/`u32swap`, the IEEE 754 `f32`/`f32swap` (two '
                      'words each), `bit` (one address = one binary value).'),
                ('b', 'the optional **`fc`** field picks the address space: `3` '
                      '(holding registers) or `4` (input registers) for the word '
                      'types (`3` the default), `1` (coils, the bit default) or '
                      '`2` (discrete inputs) for `bit` — the four spaces are '
                      'cached and polled independently.'),
                ('b', 'the optional **`ttl`** field overrides the cache TTL per '
                      'entry (seconds; `0` = never expire): a fast power word at '
                      '5s next to a nameplate word at 1h, one poll cadence for '
                      'both (`show cache-all` marks the entries carrying one). '
                      'The entry TTL **replaces** the global one in both '
                      'directions — the global TTL is only the fallback, never a '
                      'floor.'),
                ('b', 'which registers are actually **fetched** comes from a '
                      'selection file — `{"registers": ["pv-power", ...]}`, '
                      'profile names only — resolved as `--selection` flag, env '
                      '`SELECTION`, config `set modbus selection`; the default '
                      'fetches **every** profile entry (`all`), and **`none`** '
                      'empties the map: every read forwards and nothing is '
                      'stored. The shipped `extras/examples/modbus-cache-filter.json` '
                      'is the essential SUN2000 monitoring set. The 65000–65003 '
                      'diagnostics block is never fetched — the cache '
                      'synthesizes it.'),
                ('b', 'for slow dongles the poller reads the map in as **few '
                      'transactions as possible**: ranges closer together than '
                      '`--modbus-merge-gap` registers are merged into one block '
                      'read (never across a function-code boundary); a block '
                      'that fails is split in halves and the pieces are retried '
                      '— the plan converges to the largest blocks the device '
                      'actually answers.'),
            ]),
            ('Access control', [
                ('b', 'the family-wide ACL map — the rule-chain semantics, the '
                      'standalone acl file, the tools and where every tool\'s '
                      'support stops — lives in `docs/specs/ACL.md`; the four '
                      'gates\' knobs (`--connect-acl`, `--write-acl`, '
                      '`--write-registers`, `--metrics-acl`) sit in the knobs '
                      'table below with their defaults and the inline grammar.'),
                ('b', 'writing is gated four times: the frame parse gate, '
                      '`--allow-write`, the client on the write ACL, every '
                      'touched register inside the allow-list — with '
                      '`write-acl` and `write-registers` defaulting to `none`, '
                      'enabling `--allow-write` alone still refuses every write '
                      'until the operator opens those two deliberately.'),
                ('b', 'a worked write-gate example ships as '
                      '`extras/examples/acl-write-registers.json` (the deye '
                      'policy, worked out).'),
                ('b', 'beyond the address-based ACLs the cache speaks the '
                      'family\'s **`suite`** Modbus auth — a proof-of-key '
                      'handshake on the Modbus TCP wire itself (the wire shape '
                      'is specified in `docs/specs/MODBUS.md`): the client '
                      'proves the shared key with one round trip after the TCP '
                      'connect; the server answers `OK` (plain Modbus follows) '
                      'or `ERR` (the connection is dead — a client that cannot '
                      'prove the key never sees a frame).'),
                ('b', 'the two legs are configured separately, with separate '
                      'keys: `--modbus-auth` / `--modbus-auth-key` — the auth '
                      'the cache\'s *own clients* must speak on the listen port '
                      '(`none` the default, or `suite`); '
                      '`--modbus-auth-upstream` / `--modbus-auth-upstream-key` — '
                      'the auth the cache *presents* to the upstream inverter '
                      '(`suite` handshakes after every (re)connect, '
                      '`waveshare` presents the key as a **Waveshare '
                      'RS485-to-TCP gateway\'s** connection password).'),
                ('b', 'both keys are restart-marked secrets (a `set` records '
                      'pending until `request reload` applies it; they never '
                      'render back; `file:<path>` loads an owner-only `0600` '
                      'file). The floor is the scheme\'s: the suite handshake '
                      'needs at least 16 characters, the Waveshare password '
                      'non-empty ASCII — a key set while no scheme is chosen is '
                      'dormant material.'),
                ('b', 'both schemes are live-settable; the peer must speak the '
                      'same scheme with the same key — the fake inverter serves '
                      'the server side, the scraper the client side, so a chain '
                      'scraper → cache → inverter can run suite auth on either '
                      'hop independently.'),
            ]),
            ('Persistence', [
                ('b', '`--dump-path` turns on the **write-behind state dump**: '
                      'the live setting overrides and — when asked — the cached '
                      'words (+ their original stamps), as one JSON written '
                      'atomically. **What lands in the file is split** (the '
                      'audit\'s F18): by default **settings only**; `request '
                      'dump with-cache` or `--dump-with-cache` includes the '
                      'words; the restore takes either shape.'),
                ('b', 'the dumps land every `--dump-interval` seconds '
                      '(live-settable, `0` = off — the default), on the '
                      '**`request dump`** command, and on every graceful '
                      'shutdown. **`--restore-on-start`** opts in to loading the '
                      'dump when the daemon starts; the default is starting '
                      'cold — **`request restore`** loads it on demand.'),
                ('b', 'the file is created **`0600`** explicitly (never the '
                      'umask); every dump carries a **sha256 integrity hash**; '
                      'a restore **fails closed** on an edited/truncated/'
                      'unsigned dump and refuses a group/world-writable file '
                      'outright.'),
                ('b', 'with **`--dump-key`** the dump is **sealed**: the state '
                      'rides encrypted under an HMAC-SHA256 counter-mode '
                      'keystream, authenticated by an HMAC mac (stdlib only). '
                      'The gate is symmetric — a restore without the key '
                      'refuses a sealed dump, and a restore **with** a key '
                      'refuses an unsealed one. The reload\'s state file seals '
                      'under the same key — which is why the knob is '
                      'startup-only.'),
                ('b', 'the key rides inline or as **`file:<path>`** (a systemd '
                      'LoadCredential rides as `file:/run/credentials/...`); '
                      'the same `file:` reference form works on every secret '
                      'value. Without a key a dump path stays plaintext **by '
                      'design** — and says so (a `WARNING` at start, a note on '
                      'the `set dump path` reply).'),
            ]),
            ('Trace feed', [
                ('b', '`--trace-socket` binds the record feed\'s unix stream '
                      'socket (`default` = the derived '
                      '`/tmp/modbus-cache-<listen-port>-trace.socket`, a path, '
                      'or `none` = off; live-settable, `set trace-socket`): '
                      'every wire record fans out to the connected '
                      '`modbus-replay-dump --socket` (the same PVMB protocol '
                      'modbus-replay\'s feed speaks); binds `0600`.'),
                ('b', '`--trace-sources` picks the wire voices the feed carries: '
                      '`all`, `client` (the served answers + their provenance) '
                      'or `upstream` (the poller\'s polls + the forwards) — '
                      'whole voices on/off, never sampling; live-settable.'),
                ('b', 'the feed\'s records carry a `conn` id pairing each '
                      'request with its reply, and the two wire faces count in '
                      '**disjoint spaces**: the client face numbers its '
                      'sessions from 1 (one id per client connection), the '
                      'upstream face rides `100000 + <connection serial>` — so '
                      '`conn=100001` is the device conversation\'s first '
                      'incarnation, `conn=100002` the same after a reconnect. '
                      'The split exists because a forwarded request keeps the '
                      'client\'s own transaction id: one conn space would make '
                      'the dump tool pair the device\'s reply with the client\'s '
                      'request instead of keeping the two stories apart.'),
                ('b', 'the client face\'s records state the provenance in the '
                      '`note` (`served from cache`, `forwarded — device reply`, '
                      '`refused: …`, `diag registers`); the device\'s true bytes '
                      'appear as the upstream conversation beside them, and the '
                      'upstream auth handshake rides byte-less (`PVA1 handshake '
                      '(bytes withheld)` — no proof, no password).'),
            ]),
            ('Metrics', [
                ('b', '`--metrics-server` (off by default, live-settable) '
                      'serves the cache\'s own Prometheus `/metrics` on '
                      '`--metrics-listen` (default `127.0.0.1:9351`).'),
                ('b', 'the bearer token is **mandatory beyond loopback** — a '
                      'token-less non-loopback bind refuses to start (the F13 '
                      'posture); beside the token the endpoint carries the '
                      '**metrics ACL** (`--metrics-acl`, live `set metrics '
                      'acl`), checked at accept; an unauthenticated read '
                      'answers 401, anything but `/metrics` answers 404.'),
                ('b', 'the caps are live (the `metrics limits` values apply to '
                      'the running gate); `set metrics listen` records the bind '
                      'and the restart applies it; the token is startup-only — '
                      'pass it by flag/env/config (or as `file:<path>`, which '
                      're-reads on the SIGHUP re-resolve); the value never '
                      'renders back.'),
                ('b', 'a scrape job reads it like any bearer endpoint — '
                      '`authorization: {type: Bearer, credentials_file: …}` in '
                      'the job config (the docker demo\'s `prometheus.yml` '
                      'wires the job for the exporter this way).'),
                ('t', ('gauge', 'meaning'),
                 ('`modbus_cache_hits_total` / `modbus_cache_misses_total`',
                  'the hit/miss counters'),
                 ('`modbus_cache_write_refused_total`',
                  'every refused write is a `WRITE-REFUSED` audit event'),
                 ('`modbus_cache_poll_up` / `modbus_cache_last_poll_age_seconds`'
                  ' / `modbus_cache_age_seconds`',
                  'the poll health and the age'),
                 ('`modbus_cache_words` / `modbus_cache_ranges` (the `fc` '
                  'labels)', 'the map size'),
                 ('`modbus_cache_clients`', 'the connected clients'),
                 ('`modbus_cache_uptime_seconds` / the poll-cycle durations',
                  'the uptime and the last cycle\'s timing'),
                 ('`modbus_cache_uplink_*`',
                  'the upstream session state (up, connects/exchanges/errors, '
                  'bytes, the last error\'s age) and every poll block '
                  '(`…block_up{fc,start,count}`, `…block_latency_seconds{,_mean,'
                  '_max}`, `…block_fails_total`)')),
                ('b', 'the alert rules pack (`extras/alerts/cache.yml`, the F16 '
                      'closure) watches this endpoint\'s poll down, the age '
                      'spikes and the write-refusal bursts — the cache-only '
                      'install ships its half (`share/alerts.yml`).'),
            ]),
            ('Audit logging', [
                ('b', 'the proxy logs every audit-relevant event to stdout/'
                      'stderr with UTC timestamps by default (`--local-time` '
                      'switches). Under systemd, journald stores, seals and '
                      'rotates these lines — point your NIS2/DORA '
                      'documentation at `journalctl -u modbus-cache`. Modbus '
                      'has no authentication, so the client\'s source IP is '
                      'the only identity there is.'),
                ('t', ('event', 'log line'),
                 ('forwarded write',
                  '`write: register 47415 = 99 (single register, unit 1)`'),
                 ('write refused (disabled / ACL / device)',
                  '`write: refused register …` / `write rejected by the device: …`'),
                 ('forwarded frame (no cache semantics)',
                  '`forwarded FC17 (report slave id), 0 byte(s) (unit 1)`'),
                 ('uncached read forwarded + cached',
                  '`read: registers … not cached, polling the device` / `… ok, '
                  'cached …`'),
                 ('connection rejected (ACL / limit)',
                  '`connection rejected: 10.0.0.5:51234 not on the connect ACL` /'
                  ' `connection refused: client limit of N reached`'),
                 ('reload / clean (`SIGHUP` / `SIGUSR1`)',
                  '`SIGHUP: reloaded 13 range(s) …` / `SIGUSR1: cache cleared '
                  '(N register(s) dropped) …`'),
                 ('poll failed/recovered',
                  '`poll of … failed (FC3 modbus exception, code 2), serving '
                  'cached values` / `poll of … recovered`'),
                 ('client connect/disconnect (`--log-access`)',
                  '`client connected: 10.0.0.5:51234` / `client … disconnected '
                  '(…)`'),
                 ('startup / shutdown',
                  '`caching 13 range(s) …` / `shutdown: SIGTERM received, '
                  'closing the listener`)')),
                ('b', 'on top of the operational log, the proxy and the CLI '
                      'append to an **append-only audit file** — one line per '
                      'event, who/when/what/result, on by default at the XDG '
                      'state home (`~/.local/state/modbus-cache/audit.log`). '
                      '`--audit-log <file>` renames it, `--no-audit-log` turns '
                      'it off, `--audit-log -` sends it to stdout (the docker '
                      'logs / journald way — the NixOS module ships with it). '
                      'Rotation: `--audit-max-mb 10` (the default), '
                      '`--audit-daily` (UTC midnight), `--audit-files 3`.'),
                ('fam', 'audit_forward'),
                ('c', '2026-11-04T07:16:40Z AUDIT application=CACHE tag=daemon '
                      'instance=15502 type=start hash=4e1b92f0c7a3 version=0.5.1 '
                      'upstream=192.168.1.100:5502 unit=1 listen=127.0.0.1:15502 '
                      'control=unix:/tmp/modbus-cache-15502.socket '
                      'profile=/nix/store/…-sun2000.json\n'
                      '2026-11-04T07:16:43Z AUDIT application=CACHE tag=daemon '
                      'instance=15502 type=write hash=b2c4e17f90d8 fc=6 '
                      'register=47415 value=5 unit=1\n'
                      '2026-11-04T07:17:12Z AUDIT application=CACHE tag=daemon '
                      'instance=15502 type=command hash=09ab57d3f4e1 '
                      "peer=127.0.0.1:54426 cmd='clear cache' result=ok\n"
                      '2026-11-04T07:17:45Z AUDIT application=CACHE tag=daemon '
                      'instance=15502 type=shutdown hash=d94a1f07c3e2 '
                      'reason=SIGTERM-received uptime=65s clients=1 hits=412 '
                      'misses=9'),
                ('b', 'the per-client **request accounting** rides the same '
                      'trail (one `REQUESTS` event per client per '
                      '`--audit-requests` period, plus a final tally on every '
                      'disconnect). The trail is thread-safe and flushed per '
                      'event.'),
                ('c', "journalctl -u modbus-cache --since today | grep 'write:'"
                      "      # all write attempts\n"
                      'journalctl -u modbus-cache | grep -E \'SIGHUP|shutdown\''
                      '        # lifecycle\n'
                      "journalctl -u modbus-cache | grep -i 'not on'                 "
                      "# ACL rejections"),
            ]),
            ('Testing', [
                ('b', 'four standalone suites live in the suite root '
                      '`dev/suites/` — stdlib only, each starts its own fake '
                      'inverter + proxy on scratch ports and cleans up after '
                      'itself. Every scenario must end with the proxy alive '
                      'and **zero tracebacks** in the logs — the '
                      'hostile-upstream phase proves that per mode, including '
                      'recovery when the device starts answering sanely again.'),
                ('c', 'dev/battery/battery.py cache              # the cache profile: the regtest, the two fuzzes,\n'
                      '                                    #   the audit chain (the stress suite rides quick/full)\n'
                      'dev/battery/battery.py cache-regtest      # one suite — every run needs the runner (the suites\n'
                      '                                    #   refuse without the runner\'s PV_RUN_DIR)'),
                ('fam', 'runner'),
            ]),
            ('Diagnostics registers', [
                ('b', 'the cache synthesizes a 4-register block at **65000** '
                      'from live poller state — answered instantly, never '
                      'forwarded, never cached, never part of a profile '
                      '(FC3 only): the clients tell live data from '
                      'cache-served values, and the scraper auto-detects '
                      'the block and exports it as the `scraper_cache_*` '
                      'gauges.'),
                ('t', ('register', 'meaning'),
                 ('**65000**', 'magic `0xCAFE` (the validity check for clients)'),
                 ('**65001**', '`1` if the last completed poll cycle had at '
                  'least one successful read, else `0`'),
                 ('**65002**', 'seconds since the last successful device read '
                  '(`65535` = none yet)'),
                 ('**65003**', 'the cache process\' uptime in seconds')),
                ('b', 'reads that straddle the block are rejected with '
                      'exception `02` (illegal data address) — read the four '
                      'words whole. Reply unit ids are validated on every '
                      'forwarded request before anything is cached.'),
            ]),
            ('Tuning', [
                ('b', '**the poll cadence** — `--modbus-interval` (the loop\'s '
                      'sleep, the wall the cache ages against) and '
                      '`--modbus-timeout` (the per-transaction ceiling; '
                      '`timeout` above `interval` just means polls run '
                      'back-to-back).'),
                ('b', '**the slow dongle** — `--modbus-merge-gap` widens the '
                      'address gap that still merges into one block read '
                      '(fewer transactions, bigger replies), '
                      '`--modbus-read-delay` paces the blocks (the breathing '
                      'room some RS485-to-TCP gateways need); a block the '
                      'device refuses splits in halves and retries — the plan '
                      'converges to the largest blocks the device actually '
                      'answers (`show uplink` renders the plan and its '
                      'latency).'),
                ('b', '**the freshness budget** — `--cache-ttl` is the global '
                      'staleness ceiling, an entry\'s **`ttl`** field '
                      '**replaces** it per register (a fast power word at 5s '
                      'next to a nameplate word at 1h, one poll cadence for '
                      'both); the diagnostics block\'s 65002 tells the clients '
                      'how old the words actually are.'),
                ('b', '**the clients** — `--max-clients` / '
                      '`--max-conn-per-ip` cap the fan-out, '
                      '`--client-timeout` reaps the stalls (every refused or '
                      'reaped connection is a logged, audited event).'),
            ]),
            ('Deployment', [
                ('b', '**NixOS** — the module `nixos/modules/modbus-cache.nix` '
                      'renders the daemon as a hardened service (the options '
                      'mapped in `nixos/README.md`, the packaging in '
                      '`nixos/README.md`): the env file, the state dirs and '
                      'the secret `*File` options ride the module; the '
                      'rendered config validates with `--dry-run` before a '
                      'switch.'),
                ('b', '**containers** — `docker/Dockerfile.modbus-cache` '
                      '(stdlib-only, the unprivileged user), the demo and '
                      'prod compose stacks beside it (`docker/README.md`); '
                      'the image loads its bundled conf as the default '
                      '`--config` target — the env file '
                      '(`docker/env/modbus-cache.env.example`) and the CMD '
                      'flags carry the deployment shape.'),
                ('b', '**systemd (plain)** — run it behind journald '
                      '(`--audit-log -` rides the NixOS module; journald '
                      'stores, seals and rotates), the secrets as '
                      '`LoadCredential=` files passed as `file:<path>`.'),
            ]),
            ('Troubleshooting', [
                ('b', '**it will not start** — every bind failure answers one '
                      '`cannot bind` line + exit 1 (the port taken? `ss -ltnp '
                      '| grep 15502`); every configuration error aborts with '
                      'a clean one-line error before anything binds — '
                      '`--dry-run` prints the effective settings without '
                      'touching the ports.'),
                ('b', '**clients refused** — the log names the gate: `not on '
                      'the connect ACL`, the client limit reached, the write '
                      'gates\' `WRITE-REFUSED` (the audit trail carries the '
                      'client, the frame, the gate per refusal).'),
                ('b', '**stale or dead data** — the diagnostics block\'s '
                      '65001/65002 and the `modbus_cache_poll_up` / '
                      '`modbus_cache_last_poll_age_seconds` gauges tell a '
                      'poll failure from a slow one; the log names the '
                      'failing block and the exception code per cycle.'),
                ('b', '**deeper** — `--log-level DEBUG` logs every frame both '
                      'ways; `SIGUSR2` dumps the thread stacks (the '
                      'family\'s faulthandler hook); the audit trail '
                      'chain-verifies with `dev/gates/audit_verify.py`.'),
            ]),
            ('The docs map', [
                ('fam', 'docs'),
            ]),
            ('Configuration', [
                ('b', 'the config file (`--config PATH`, env `CONFIG`) speaks '
                      'the **set grammar** — one `set <name> <value>` per '
                      'line, the control CLI\'s own spelling, the same line '
                      'pastes into the console or a ctl; a value resolves '
                      'flag > env > this file > the row\'s default, anything '
                      'left commented falls to the default the line spells.'),
                ('b', 'the bundled `apps/cache/examples/modbus-cache.conf` is '
                      'GENERATED from the registry (`dev/generators/examples.'
                      'py`): every knob declared, every line commented at its '
                      'default — copy it, uncomment what you change, point '
                      '`--config` at it. The dev wrapper (`apps/cache/dev`) '
                      'and the docker image both ride it as their default '
                      '`--config` target.'),
                ('c', '# per-register cache TTL: older entries are refetched\n'
                      '# set cache ttl 30\n'
                      '\n'
                      '# the inverter Modbus TCP endpoint HOST:PORT (`:5502` '
                      '= 127.0.0.1:5502)\n'
                      '# set modbus upstream 127.0.0.1:5502'),
                ('b', 'a live daemon re-reads the file on `SIGHUP` / `request '
                      'reload-config` — a broken file keeps the previous '
                      'settings; the restart-marked knobs record a pending '
                      '`set` and fold into the restarted process. `show '
                      'config` regenerates the script from the running daemon '
                      '(secrets hidden) and `--dry-run` prints the effective '
                      'settings without binding anything.'),
                ('b', 'the secrets never live in the file: every secret row '
                      'carries the `*** SECRET REMOVED ***` placeholder — '
                      'pass them by flag, env, or `file:<path>` (the first '
                      'line of an owner-only `0600` file).'),
            ]),
            ('Source layout', [
                ('p', 'the subproject is flat and stdlib-only — one bin pair, '
                      'one lib package, the generated surfaces beside. The '
                      'checkout launchers (`dev`, `dev-cli`) run the daemon '
                      'and the console straight from the tree against the '
                      'shipped sample config (the packaged-root defaults do '
                      'not exist in a source tree — the loader never reaches '
                      'into examples/ on its own; the audit rides stdout so '
                      'the dev terminal streams it).'),
                ('c', 'apps/cache/\n'
                      '├── bin/\n'
                      '│   ├── modbus-cache.py           # the daemon: the CLI, the logging, the\n'
                      '│   │                            #   signal handling, the control wiring\n'
                      '│   └── modbus-cache-cli.py -> ../../pvsuite-cli.py\n'
                      '│                                # the family client dispatcher: the tool\n'
                      '│                                #   from the name it was invoked as\n'
                      '├── lib/\n'
                      '│   ├── proxy.py                  # the poller thread, the client handling,\n'
                      '│   │                             #   the forwarding, the reload\n'
                      '│   ├── cache.py                  # the in-memory cache, the poll block planner\n'
                      '│   │                             #   (the four address spaces)\n'
                      '│   ├── upstream.py               # the ONE Modbus upstream connection, shared\n'
                      '│   ├── config.py                 # the set grammar: the config script, the env,\n'
                      '│   │                             #   the flags, the register map\n'
                      '│   ├── control.py                # the JSON-lines control server\n'
                      '│   ├── metrics.py                # the /metrics endpoint (the F13 gate)\n'
                      '│   ├── persist.py                # the state dumps (the write-behind)\n'
                      '│   ├── tracefeed.py              # the record feed\'s hub (trace-socket/-sources)\n'
                      '│   ├── statics.py                # the protocol limits, the diag block\n'
                      '│   │                             #   (lib/defaults.json)\n'
                      '│   ├── options.py + options.json # the registry: the one row per knob\n'
                      '│   ├── cli_spec.py               # the client SPEC (pvsuite-cli\'s per-tool half)\n'
                      '│   └── man.py                    # the generated man pages\n'
                      '├── examples/modbus-cache.conf    # the GENERATED sample (every knob, commented)\n'
                      '├── man/                          # the generated man page\n'
                      '└── dev, dev-cli                  # the checkout launchers (the daemon + the\n'
                      '                                 #   console against the example conf)'),
                ('p', 'the shared machinery lives in the suite\'s `common/` '
                      'package (the control spine, the Modbus client/server, '
                      'the audit, the manpage generator) and `shared/` (the '
                      'texts, the schemas, the profiles) — `lib/` imports it '
                      'by path; nothing is packaged separately. The client '
                      'dispatcher is the suite\'s `apps/pvsuite-cli.py`, one '
                      'script for all four ctl tools.'),
            ]),
            ('The docs map', [
                ('t', ('this tool\'s documents', 'what they carry'),
                 ('`apps/cache/README.md`', 'the front page — the description, '
                  'the quick how-to, Security, License'),
                 ('`apps/cache/lib/options.json`', 'the registry — the one row '
                  'per knob (the tables above render from it)'),
                 ('`apps/cache/examples/modbus-cache.conf`', 'the GENERATED '
                  'sample configuration (the Configuration section quotes it)'),
                 ('`apps/cache/man/`', 'the generated man page (`modbus-cache '
                  '--man` renders it)'),
                 ('`nixos/modules/modbus-cache.nix`', 'the NixOS service module '
                  '(the options mapped in `nixos/README.md`)'),
                 ('`docker/Dockerfile.modbus-cache` + '
                  '`docker/env/modbus-cache.env.example`', 'the image and the '
                  'deployment env (the topologies: `docker/README.md`)')),
                ('fam', 'docs'),
            ]),
            ('Runtime control', [
                ('b', 'the live layer: every `settable` row applies at once '
                      '(`set <name> <value>`), `clear <name>` returns the '
                      'configured value, `show <name>` prints the live one — '
                      'the caps, the ACLs, the trace socket, the audit sinks '
                      'and the poll plan rotate live; the console completes '
                      'the row\'s live/alias path spellings.'),
                ('b', 'the **restart-marked** rows record a pending `set` and '
                      'fold into the restarted process on `request reload` '
                      '(or a plain restart); the **startup-only** rows (every '
                      'secret, the listen address) answer a restart only. '
                      '`show config` spells each row\'s shape, and '
                      'regenerates the config script from the running daemon '
                      '(secrets hidden).'),
                ('b', 'the request verbs: `request reload-config` re-reads '
                      'the config file (the `SIGHUP` twin), `request dump` / '
                      '`request dump with-cache` write the state dump, '
                      '`request restore` loads it, `clear cache` is the '
                      '`SIGUSR1` twin, `restart` restarts the daemon in '
                      'place.'),
                ('b', 'every command is audited once, by the server (the '
                      'peer, the role, the frame\'s mac when the wire is '
                      'signed); the ops-token sessions ride the read-only '
                      'verb policy.'),
                ('c', '# live: retune, inspect, re-read the file\n'
                      'set cache ttl 30\n'
                      'show cache-all\n'
                      'request reload-config'),
            ]),
        ],
    },
    'scraper': {
        'family': [
            ('b', 'the scraper is the chain\'s poller: **Modbus in, '
                  'Prometheus out** — through the cache (the usual shape: '
                  'the cache multiplexes the device) or straight at the '
                  'device when nothing else shares it.'),
        ],
        'run': [
            ('c', 'python3 apps/scraper/bin/modbus-scraper.py --upstream 192.168.1.100:502\n'
                  'curl http://localhost:9350/metrics'),
            ('b', 'the exporter **binds to 127.0.0.1:9350** (loopback only) — '
                  'pass `--listen 0.0.0.0:9350` when Prometheus scrapes from '
                  'another host. **Beyond loopback a token is mandatory**: a '
                  'non-loopback listen without `--auth-token` **refuses to '
                  'start** (one clean line, no traceback — the audit\'s F13); '
                  'the loopback default needs no token.'),
            ('b', 'add **`--dry-run`** to validate the configuration and print '
                  'the effective settings without binding the port or '
                  'contacting the inverter. Exit codes: `0` = valid, `1` = '
                  'invalid (reason on stderr), `2` = command-line misuse.'),
            ('b', 'settings resolve flag > env (the same names, bare — no tool '
                  'prefix: `CONFIG`, `UPSTREAM`, `MODBUS_UNIT`, `LISTEN`, '
                  '`AUTH_TOKEN`, … the full twin set is the generated '
                  '`docker/env/modbus-scraper.env.example`) > config script '
                  '(`--config` picks the file; the default hunt: `$CONFIG`, '
                  'then `modbus-scraper.conf` next to the script, then the '
                  'subproject root\'s sample — a missing file is fine) > '
                  'built-in defaults.'),
            ('b', 'every setting is **sanitized and validated** before use — a '
                  'malformed config file is fatal, nonsense values abort with '
                  'a clean one-line error instead of failing later at runtime. '
                  'The only soft spot is `timeout > interval`: that logs a '
                  'warning (polls run back-to-back) instead of failing.'),
            ('b', 'the bundled `examples/modbus-scraper.conf` is a sample in '
                  'the set grammar — GENERATED (`dev/generators/examples.py`) '
                  'from `lib/options.json`, every knob the registry declares, '
                  'every line commented at its default; `show config` '
                  'regenerates the script from the running scraper (secrets '
                  'hidden).'),
            ('b', 'the register map — addresses, types, gains, function codes '
                  '— comes from the device profile **alone**; there are no '
                  'register override knobs.'),
        ],
        'how': [
            ('p', 'The scraper is a loop and a page: the poller walks the '
                  'device profile, the exposition answers Prometheus — and '
                  '`metrics.json` names everything that appears.'),
            ('b', 'a poll loop reads the device profile\'s registers every '
                  '`--modbus-interval` seconds; the source ranges merge into '
                  'as few **block reads** as the `--modbus-merge-gap` allows '
                  '(a failed block splits to its sources — `show uplink` '
                  'renders the plan and its latency).'),
            ('b', 'the reading passes **sanity caps** (`--max-kwp`, '
                  '`--max-grid-kw`): bad data answers **HTTP 503** with '
                  '`# Error collecting metrics from inverter` until a good '
                  'poll, never silently wrong numbers.'),
            ('b', 'the exposition serves the profile- and compute-fed names '
                  '(the `--metrics-prefix` prefix, default `huawei_`) and the '
                  'fixed `scraper_*` self-observability gauges.'),
        ],
        'tail': [
            ('Signals', [
                ('t', ('signal', 'effect'),
                 ('`SIGHUP`', 'reload the configuration without dropping the '
                  'exporter: poll interval, caps, the device profile, the '
                  'auth token (+ file re-read = rotation), client limits, the '
                  'Modbus auth scheme/key and the upstream take effect '
                  'immediately; an invalid value keeps the previous settings; '
                  'the listen address and `metrics.json` need a restart '
                  '(`log-level` is live — `set system log-level`)'),
                 ('`SIGTERM` / `SIGINT`', 'graceful shutdown with a session '
                  'summary (duration + poll-error count)')),
            ]),
            ('Register maps (the register defaults)', [
                ('b', 'register defaults follow Huawei\'s official *Solar '
                      'Inverter Modbus Interface Definitions* (Issue 04, '
                      '2023-01-10) — they live in the device profile, not in '
                      'flags.'),
                ('b', '**32064** — input power, I32, unit kW with gain 1000 '
                      '(raw values are watts); **37113** — meter power, I32, '
                      '`> 0` = feed-in (without a meter the inverter alone '
                      'cannot report grid power).'),
                ('b', 'older **20200520** protocol: input power at **32089**, '
                      'meter power at **37258** — point `--modbus-profile` at '
                      'a profile carrying those addresses.'),
                ('b', 'unit quirk: the inverter\'s `[Power meter collection]` '
                      'copy of 37113 has been observed reporting **watts** '
                      '(gain 1) while the meter-section table says kW (gain '
                      '1000). The bundled profile assumes watts; if grid power '
                      'looks 1000× off the other way, set the entry\'s `scale` '
                      'to 1000 in your profile copy.'),
                ('b', 'with a battery the derived home load is wrong while the '
                      'battery charges/discharges — point the dashboard\'s '
                      '`load` metric at a real meter register/exporter '
                      'instead.'),
            ]),
            ('Metrics', [
                ('t', ('metric', 'meaning'),
                 ('`huawei_pv_generation_watts`', 'PV (inverter input) power'),
                 ('`huawei_grid_export_watts` / `huawei_grid_import_watts`',
                  'power exported to / imported from the grid (≥ 0)'),
                 ('`huawei_home_consumption_watts`',
                  'home load, derived as `PV − battery − net grid`'),
                 ('`huawei_grid_net_watts`',
                  'signed net grid power (debugging aid)'),
                 ('`huawei_battery_net_watts`',
                  'signed battery power, +charge/−discharge'),
                 ('`huawei_battery_charge_watts` / '
                  '`huawei_battery_discharge_watts`',
                  'the split, ≥ 0, for stacked graphs'),
                 ('`huawei_battery_soc_percent`', 'battery state of charge'),
                 ('`scraper_up` / `scraper_modbus_errors_total` / '
                  '`scraper_last_poll_timestamp_seconds`', 'poller health'),
                 ('`scraper_poll_duration_seconds` / `_mean` / `_max`',
                  'the last poll cycle\'s duration and its running mean/'
                  'maximum'),
                 ('`scraper_cache_device_up` / `scraper_cache_age_seconds` / '
                  '`scraper_cache_uptime_seconds`',
                  'modbus-cache diagnostics, **auto-detected**: exported only '
                  'when the polled endpoint serves the cache\'s diag block. '
                  '`device_up 0` / a growing age mean the device is down '
                  '**behind the cache**')),
                ('b', 'the grid register value is split into export/import by '
                      'sign — by default **positive = export**; set '
                      '`--grid-positive-import` if your device reports the '
                      'opposite.'),
                ('b', 'Huawei power registers already report **watts** (their '
                      'gain convention divides raw by 1000 to get kW); the '
                      'decode — type and gain — comes from the device '
                      'profile\'s per-entry `scale` alone.'),
                ('b', 'caps are on by default: `--max-kwp 6` (6 kWp array) and '
                      '`--max-grid-kw 12` (12 kW power line); the caps assume '
                      '`max-kwp ≤ max-grid-kw` (a startup warning fires '
                      'otherwise). A reading above a cap logs an error and '
                      'serves **HTTP 503** until a good poll.'),
                ('b', '**negative PV readings always trigger the error** '
                      'regardless of the cap settings — a negative inverter '
                      'input would corrupt the derived home load.'),
            ]),
            ('Alerting', [
                ('t', ('alert', 'fires when', 'the trail says'),
                 ('`ScraperPollDown`', '`scraper_up == 0` for 2m — the Modbus '
                  'poll of the device is failing',
                  'the scraper log names the failure per cycle'),
                 ('`ScraperFreshnessGap`',
                  'the last successful poll is more than 120s behind — 12 lost '
                  'cycles at the default 10s poll',
                  'the slow-dongle gauges tell a stall from an outage'),
                 ('`ScraperExceptionSpike`',
                  '`scraper_modbus_errors_total` grew by more than 30 in 10m — '
                  'half the cycles failing at the default interval',
                  'the log names the Modbus exception code per failed poll'),
                 ('`CachePollDown` (the cache\'s `/metrics`)',
                  '`modbus_cache_poll_up == 0` for 2m',
                  'the cache serves its last known words; the uplink block '
                  'counters show the failing block'),
                 ('`CacheAgeSpike`',
                  'the oldest cached word more than 300s old — reads succeed '
                  'with stale data behind them',
                  'the `cache-ttl` budget is the knob'),
                 ('`CacheWriteRefusalBurst`',
                  '`modbus_cache_write_refused_total` grew by more than 3 in '
                  '5m — the write gate refusing in bursts',
                  'each refusal is a `WRITE-REFUSED` audit event (the client, '
                  'the frame, the gate)')),
                ('b', 'the family\'s **alert rules pack** lives at '
                      '`extras/alerts/` — one rule file per watched exporter; '
                      'this exporter\'s half is `alerts/scraper.yml`, the '
                      'cache\'s half (`alerts/cache.yml`) ships with the cache '
                      'package. The pack is the audit vocabulary\'s detection '
                      'half (docs/SECURITY.md F16): every alert names the '
                      'audit events and the log lines it correlates with, so '
                      'a fired page tells the operator where the trail lives.'),
                ('b', 'the cache group stays silent until the cache\'s own '
                      '`/metrics` endpoint is scraped (an absent series never '
                      'fires); the exporter\'s diag block '
                      '(`scraper_cache_device_up` / `scraper_cache_age_seconds`) '
                      'mirrors two of its shapes for setups that do not scrape '
                      'the cache. The exporter\'s own death (the scrape '
                      'failing) is the collector\'s stock `up{job}` hygiene, '
                      'not this pack.'),
                ('b', 'wire-in: the demo image bakes the pack '
                      '(`docker/prometheus.yml` sets `rule_files:`); a NixOS '
                      'Prometheus points `services.prometheus.ruleFiles` at '
                      'the packaged copy (`share/alerts.yml`, see '
                      '`nixos/README.md`); an external collector copies the '
                      'file and lists it under its own `rule_files:`. '
                      'Thresholds assume the default 10 s poll interval — tune '
                      'them to yours.'),
            ]),
            ('Register maps and the metrics spec', [
                ('b', '*where* the primary values live comes from a **device '
                      'profile** — the same shared schema the fake inverter '
                      'serves and the cache polls; the shipped profiles live '
                      'in the suite\'s `shared/profiles/` data dir '
                      '(`sun2000.json` by default); the format is documented '
                      'in `shared/profiles/README.md`. Resolution: '
                      '`--modbus-profile` flag, env `MODBUS_PROFILE`, config '
                      '`set modbus profile`, then the bundled copy; re-read on '
                      '`SIGHUP`.'),
                ('b', 'the live control surface swaps the profile at runtime: '
                      '`set modbus profile <file-or-name>` loads the new map, '
                      'rebuilds the metric sources and rolls back cleanly when '
                      'the profile lacks the registers the power math depends '
                      'on.'),
                ('b', 'WHICH entries feed the metrics comes from '
                      '**`metrics.json`** — the spec, keyed by the exported '
                      'metric name directly. An entry carries either a '
                      '**`profile`** field naming the device-profile register '
                      'it is read from (its `type`/`scale` drive the decode) '
                      'or an **`expr`** — a computed metric (`{expr, when?, '
                      'help, type?}`) evaluated per poll over the declared '
                      '**inputs**.'),
                ('b', 'the expr grammar is a strict stdlib-safe whitelist '
                      '(numbers, the inputs, arithmetic, comparisons, the '
                      'ternary, `abs`/`min`/`max`/`round`; one compute metric '
                      'cannot feed another); an unavailable input, a division '
                      'by zero or a non-finite result keeps the metric absent '
                      'for that poll.'),
                ('b', 'the spec is **sectioned** — `inputs` (the declared '
                      'expression vocabulary), `metrics` (the tree above), '
                      '`scraper` (the exporter\'s own observability specs, '
                      'shipped separately in `apps/scraper/lib/metrics.json` '
                      'and merged in over the configured spec — a custom '
                      '`--metrics-spec` only needs the sections it cares '
                      'about). The JSON Schema ships as '
                      '`schema/metrics.schema.json` (draft 2020-12).'),
                ('b', 'the four **canonical** entries — the power math\'s '
                      'inputs (`pv_generation_watts`, `grid_net_watts`, '
                      '`battery_net_watts`, `battery_soc_percent`) — are '
                      'built-in: always declared, always bound, always '
                      'fetched. Every profile-bound metric beyond them is read '
                      'once per poll, softly: a rejected read keeps its metric '
                      'absent instead of failing the poll.'),
                ('b', 'metric names, help texts and types are loaded at '
                      'startup from the packaged `metrics.json` (the lib '
                      'dir\'s default; a checkout resolves the '
                      '`apps/scraper/metrics.json` → `examples/` dev symlink) '
                      '— point `--metrics-spec` elsewhere (or `set metrics '
                      'spec`) to rename metrics or reword `# HELP` lines '
                      'without touching the code; a missing or corrupt spec '
                      'fails cleanly at startup (one-line error, exit 1). '
                      '`show inputs` / `show inputs-metrics` render the '
                      'declared inputs and the exported metrics.'),
                ('c', 'ok inputs\n'
                      'batt     [battery_net_watts]    Net battery power in '
                      'watts (positive …\n'
                      'pv       [pv_generation_watts]  PV input power in watts '
                      '(the …'),
            ]),
            ('Battery', [
                ('b', 'the energy balance always carries the battery term '
                      '(battery support is always on — the flag retired):'),
                ('c', 'home = pv − batt − grid'),
                ('b', 'battery registers (defaults follow the same Huawei '
                      'convention as the PV register — they come from the '
                      'device profile\'s `battery-power` and `battery-soc` '
                      'entries): **37001** battery power (I32 W, **positive = '
                      'charging**), **37004** state of charge (U16, '
                      'percent×10).'),
                ('b', 'charging midday surplus reduces the home value; evening '
                      'discharge covers the home load even with PV at 0.'),
                ('b', 'the consistency checks adapt: exported power may exceed '
                      'the PV cap by the battery discharge (a battery feeding '
                      'the grid is legitimate), and a derived `home < 0` is '
                      'rejected as inconsistent. A device profile without the '
                      'battery registers keeps the battery metrics absent.'),
                ('b', 'the fake inverter emulates the battery for testing: '
                      '`python3 apps/inverter/bin/modbus-fake-inverter.py`.'),
            ]),
            ('Audit logging', [
                ('b', 'logging is `logging`-based with **UTC timestamps by '
                      'default** (`--local-time` switches): one startup line '
                      'with the effective settings, reachability changes and '
                      'reloads at INFO/WARNING (every poll at DEBUG). HTTP '
                      'requests are quiet by default; **`--log-access`** logs '
                      'every request at INFO as an audit trail of who scraped '
                      'what when. **Rejected requests are always audited** '
                      'regardless.'),
                ('b', 'handled connection problems always log a single line — '
                      'the suite enforces that **no scenario produces a '
                      'traceback**. Under systemd (`JOURNAL_STREAM` set) log '
                      'lines omit their own timestamp — journald adds one.'),
                ('b', 'the control commands (with their wire macs), the auth '
                      'failures, the reloads and the shutdowns land in the '
                      '**SCR audit trail** (`--audit-log`, the XDG state home '
                      'by default — `dev/gates/audit_verify.py` walks it like '
                      'the others).'),
                ('fam', 'audit_forward'),
            ]),
            ('Testing', [
                ('b', 'two standalone suites live in the suite root '
                      '`dev/suites/` — stdlib only, each starts its own fake '
                      'inverter + exporters on scratch ports and cleans up '
                      'after itself. Every scenario must end with the exporter '
                      'serving correct metrics and **zero tracebacks** in the '
                      'logs.'),
                ('b', 'the fake inverter is the suites\' workhorse — its own '
                      'subproject and manual '
                      '(`extras/manuals/fake-inverter.md`): the suites start '
                      'it automatically; point the scraper at it by hand to '
                      'debug the poll loop hardware-free.'),
                ('c', 'dev/battery/battery.py scraper        # the scraper profile: the regtest, the fuzz, the\n'
                      '                                #   audit chain (the suites refuse without the\n'
                      '                                #   runner\'s PV_RUN_DIR)'),
                ('fam', 'runner'),
            ]),
            ('Tuning', [
                ('b', '**the poll cadence** — `--modbus-interval` (the loop\'s '
                      'sleep; the alert thresholds assume the default 10s) '
                      'and `--modbus-timeout` (the per-transaction ceiling).'),
                ('b', '**the slow dongle** — `--modbus-merge-gap` widens the '
                      'address gap that still merges into one block read '
                      '(fewer transactions per poll), `--modbus-read-delay` '
                      'paces them; `show uplink` renders the block plan and '
                      'its per-block latency — a stalled plan shows right '
                      'there.'),
                ('b', '**the sanity caps** — `--max-kwp` / `--max-grid-kw` '
                      'are the bad-data fence (a reading above a cap answers '
                      'HTTP 503 until a good poll, never silently wrong '
                      'numbers); size them to the array and the power line '
                      '(`max-kwp` ≤ `max-grid-kw`, a startup warning '
                      'otherwise).'),
                ('b', '**the exposition** — `--metrics-prefix` renames the '
                      'family (`huawei_` the default; the dashboard\'s '
                      '`config.js` selectors must follow), `--metrics-spec` '
                      'renames/rewords the individual metrics without '
                      'touching the code.'),
            ]),
            ('Deployment', [
                ('b', '**NixOS** — the module `nixos/modules/modbus-scraper.nix` '
                      'renders the exporter as a hardened service (the '
                      'options mapped in `nixos/README.md`, the packaging in '
                      '`nixos/README.md`); the rendered config validates with '
                      '`--dry-run` before a switch.'),
                ('b', '**containers** — `docker/Dockerfile.modbus-scraper`, '
                      'the demo and prod compose stacks beside it '
                      '(`docker/README.md`); the env file '
                      '(`docker/env/modbus-scraper.env.example`) carries the '
                      'bare upper-snake twins.'),
                ('b', '**systemd (plain)** — run it behind journald '
                      '(`--audit-log -`), the token as a `LoadCredential=` '
                      'file passed as `file:<path>` (the re-read on '
                      '`SIGHUP` is the rotation story).'),
            ]),
            ('Troubleshooting', [
                ('b', '**it will not start** — the bind failures and the '
                      'config errors answer one clean line + exit 1 '
                      '(a non-loopback listen without `--auth-token` is the '
                      'usual one — the F13 floor); `--dry-run` prints the '
                      'effective settings without touching the ports.'),
                ('b', '**HTTP 503 on /metrics** — the sanity caps refusing '
                      'the last poll (bad data above `--max-kwp`/'
                      '`--max-grid-kw`, a negative PV): the log names the '
                      'offending reading; the page returns with the next '
                      'good poll — never silently wrong numbers.'),
                ('b', '**the poll is failing** — `scraper_up == 0`, the '
                      'error counter climbing, the freshness gauge aging: '
                      'the log names the Modbus exception code per failed '
                      'poll; `show uplink` splits a device stall from an '
                      'outage (the per-block latencies).'),
                ('b', '**deeper** — `--log-level DEBUG` logs every poll\'s '
                      'transactions; `SIGUSR2` dumps the thread stacks; the '
                      'audit trail chain-verifies with '
                      '`dev/gates/audit_verify.py`.'),
            ]),
            ('The docs map', [
                ('fam', 'docs'),
            ]),
            ('Configuration', [
                ('b', 'the config file (`--config` picks it; the default hunt: '
                      '`$CONFIG`, then `modbus-scraper.conf` next to the '
                      'script, then the subproject root\'s sample — a missing '
                      'file is fine) speaks the **set grammar** — one '
                      '`set <name> <value>` per line, the control CLI\'s own '
                      'spelling; a value resolves flag > env > this file > '
                      'the row\'s default.'),
                ('b', 'the bundled `apps/scraper/examples/modbus-scraper.conf` '
                      'is GENERATED from the registry (`dev/generators/'
                      'examples.py`): every knob declared, every line '
                      'commented at its default — copy it, uncomment what you '
                      'change, point `--config` at it. The env-twin set rides '
                      'the generated `docker/env/modbus-scraper.env.example`.'),
                ('b', 'a live scraper re-reads the file on `SIGHUP` (a broken '
                      'file keeps the previous settings; the auth token\'s '
                      '`file:` form re-reads too — that is the rotation '
                      'story); `show config` regenerates the script from the '
                      'running daemon (secrets hidden) and `--dry-run` prints '
                      'the effective settings without binding anything.'),
            ]),
            ('Access control', [
                ('b', 'the `/metrics` endpoint: **beyond loopback a token is '
                      'mandatory** — a non-loopback listen without '
                      '`--auth-token` refuses to start (one clean line, no '
                      'traceback — the F13 floor); beside the token the '
                      '**metrics ACL** (`--metrics-acl`, live `set metrics '
                      'acl`) gates the accept — `any`, `none`, a '
                      'comma-separated IP/CIDR list, or `file:<path>` (the '
                      'ip-prefix acl file; `show metrics-acl-table` renders '
                      'the chain). An unauthenticated read answers 401.'),
                ('b', 'the control plane: TCP control demands the token '
                      '(`--control-token`, the wire\'s `auth` verb); the '
                      'optional ops token (`--control-ops-token`) scopes a '
                      'session to the read-only verbs — the ops shift against '
                      'the admin key, both audited.'),
                ('b', 'the device leg: `--modbus-auth` picks what the scraper '
                      '*speaks to the device* — `suite` (the PVA1 proof-of-key '
                      'handshake, the key floor 16 characters) or `waveshare` '
                      '(the key presented as a Waveshare RS485-to-TCP '
                      'gateway\'s connection password, non-empty ASCII) — and '
                      '`--modbus-auth-key` carries the shared secret '
                      '(`file:<path>` the shipped spelling). Scheme and key '
                      'are live-settable; a key set with no scheme stays '
                      'dormant, and going `suite` over a short standing '
                      'password refuses at start and on the wire.'),
            ]),
            ('Source layout', [
                ('p', 'the subproject is flat and stdlib-only — one bin pair, '
                      'one lib package, the generated surfaces beside. The '
                      'checkout launchers (`dev`, `dev-cli`) run the exporter '
                      'and the console straight from the tree against the '
                      'shipped sample config.'),
                ('c', 'apps/scraper/\n'
                      '├── bin/\n'
                      '│   ├── modbus-scraper.py         # the daemon: the CLI, the logging, the\n'
                      '│   │                            #   signal handling, the control wiring\n'
                      '│   └── modbus-scraper-cli.py -> ../../pvsuite-cli.py\n'
                      '│                                # the family client dispatcher: the tool\n'
                      '│                                #   from the name it was invoked as\n'
                      '├── lib/\n'
                      '│   ├── poller.py                 # the poll loop: the block reads, the sanity\n'
                      '│   │                             #   caps, the store\n'
                      '│   ├── protocol.py               # the Modbus TCP wire format, the limits\n'
                      '│   ├── expr.py                   # the compute-expression evaluator (the\n'
                      '│   │                             #   metrics spec\'s expr/when entries)\n'
                      '│   ├── metrics.py                # the metrics spec (metrics.json), sectioned\n'
                      '│   ├── server.py                 # the Prometheus exposition endpoint\n'
                      '│   ├── control.py                # the JSON-lines control server\n'
                      '│   ├── config.py                 # the set grammar: the config script, the\n'
                      '│   │                             #   env, the flags\n'
                      '│   ├── statics.py                # the protocol limits, the diag block it reads\n'
                      '│   ├── options.py + options.json # the registry: the one row per knob\n'
                      '│   ├── cli_spec.py               # the client SPEC (pvsuite-cli\'s per-tool half)\n'
                      '│   └── man.py                    # the generated man pages\n'
                      '├── metrics.json                  # the shipped self-observability spec\n'
                      '├── schema/                       # the JSON Schemas (draft 2020-12)\n'
                      '├── examples/                     # the GENERATED conf + the example metrics spec\n'
                      '├── man/                          # the generated man page\n'
                      '└── dev, dev-cli                  # the checkout launchers'),
                ('p', 'the shared machinery lives in the suite\'s `common/` '
                      'package (the control spine, the Modbus client, the '
                      'audit, the compute-expression evaluator) and `shared/` '
                      '(the texts, the schemas, the profiles) — `lib/` '
                      'imports it by path; the client dispatcher is the '
                      'suite\'s `apps/pvsuite-cli.py`, one script for all '
                      'four ctl tools.'),
            ]),
            ('The docs map', [
                ('t', ('this tool\'s documents', 'what they carry'),
                 ('`apps/scraper/README.md`', 'the front page — the description, '
                  'the quick how-to, Security, License'),
                 ('`apps/scraper/lib/options.json`', 'the registry — the one row '
                  'per knob (the tables above render from it)'),
                 ('`apps/scraper/lib/metrics.json` + `apps/scraper/metrics.json`',
                  'the shipped self-observability spec and the checkout\'s '
                  'configurable spec (the loader merges it over the lib half)'),
                 ('`apps/scraper/schema/`', 'the JSON Schemas for the metrics '
                  'spec (draft 2020-12)'),
                 ('`apps/scraper/examples/`', 'the GENERATED conf + the example '
                  'metrics spec'),
                 ('`apps/scraper/man/`', 'the generated man page '
                  '(`modbus-scraper --man` renders it)'),
                 ('`nixos/modules/modbus-scraper.nix`', 'the NixOS service module '
                  '(the options mapped in `nixos/README.md`)'),
                 ('`docker/Dockerfile.modbus-scraper` + '
                  '`docker/env/modbus-scraper.env.example`', 'the image and the '
                  'deployment env (the topologies: `docker/README.md`)')),
                ('fam', 'docs'),
            ]),
            ('Runtime control', [
                ('b', 'the live layer: `set modbus profile <name|path>` swaps '
                      'the register map at runtime (the metric sources '
                      'rebuild, a profile lacking the power math\'s inputs '
                      'rolls back cleanly), `set system log-level` is live; '
                      '`clear <name>` returns the configured value, '
                      '`show <name>` prints the live one, `show inputs` / '
                      '`show inputs-metrics` render the spec.'),
                ('b', 'the poll cadence and the caps ride the config reload: '
                      '`request reload-config` re-reads the file (the '
                      '`SIGHUP` twin — interval, caps, the auth token\'s '
                      '`file:` re-read, the upstream); the restart-marked '
                      'rows (the listen address, the metrics spec) record a '
                      'pending `set` and fold in on `request reload` or a '
                      'restart.'),
                ('b', '`request poll now` forces a poll off-schedule; '
                      '`restart` restarts the exporter in place. Every '
                      'command is audited once, by the server — the '
                      'ops-token sessions ride the read-only verb policy '
                      '(no set/clear, no `request poll now`, no reload, no '
                      'restart, no shutdown).'),
                ('c', '# live: swap the map, re-read the file, force a poll\n'
                      'set modbus profile sun2000_full\n'
                      'request reload-config\n'
                      'request poll now'),
            ]),
        ],
    },
    'inverter': {
        'family': [
            ('b', 'the fake stands in for the device: **the whole chain '
                  'debugs against it without hardware** — the scraper '
                  'polls it, the cache fronts it, the replay captures and '
                  'replays it, the suites start it automatically.'),
        ],
        'run': [
            ('c', 'python3 apps/inverter/bin/modbus-fake-inverter.py                       '
                  '# 127.0.0.1:5502 — scraper defaults just work\n'
                  'python3 apps/inverter/bin/modbus-fake-inverter.py --time 12:00          '
                  '# frozen noon: ~4.5 kW PV, exporting\n'
                  'python3 apps/inverter/bin/modbus-fake-inverter.py --static              '
                  '# the classic static demo values\n'
                  'python3 apps/inverter/bin/modbus-fake-inverter.py --listen 127.0.0.1:15502 '
                  '--log-level DEBUG\n'
                  'python3 apps/inverter/bin/modbus-fake-inverter.py --config '
                  'apps/inverter/examples/modbus-fake-inverter.conf --dry-run'),
            ('b', 'add **`--dry-run`** to validate the configuration and print '
                  'the effective settings. Exit codes: `0` = valid, `1` = '
                  'invalid, `2` = CLI misuse.'),
            ('b', 'the startup surface is the family\'s: **flag > env > config '
                  'script > the built-in defaults**. The config file '
                  '(`--config PATH`, `$CONFIG`, then '
                  '`modbus-fake-inverter.conf` next to the script) speaks the '
                  '**set grammar** — every line a `set <name> <value>` in the '
                  'CLI spelling, the same line pastes into the console or '
                  '`modbus-fake-cli` — and the bundled sample is '
                  '`examples/modbus-fake-inverter.conf`.'),
            ('b', 'the pins and the machines (`pv`, `load`, `batt`, `grid`, '
                  '`soc`, `mppt`, `cloud`, `scenario`, `battery-state`, '
                  '`grid-outage`) stay control-wire settings: the config names '
                  'one and the start refuses.'),
            ('b', '`SIGHUP` re-applies the **environment layer** '
                  '(all-or-nothing — flags are startup-only): `CHAOS` (0..1), '
                  '`MAX_KWP`, `MODBUS_PROFILE`, `STRICT`, `TIME`, '
                  '`TIME_SCALE`, `LOG_LEVEL` — booleans accept '
                  '`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`. The same '
                  'twins ride the start in the ladder — `CHAOS=0.9` at '
                  'creation is honored, SIGHUP retunes a running fake.'),
                ('b', 'the fake ships as an alpine container — stdlib-only, no '
                  'pip, running as the unprivileged `pvsuite` user with the '
                  'tools on `PATH` (`docker/Dockerfile.modbus-fake-inverter` + '
                  '`compose.yaml`; see `docker/README.md`). The image loads '
                  'its own bundled conf '
                  '(`/pv-suite/inverter/modbus-fake-inverter.conf`, the '
                  'built-in `--config` target) — the env file and the CMD '
                  'flags override it. The version reports as `0.5.1` inside '
                  'the image (no git metadata; a checkout shows '
                  '`0.5.1-<short git>`).'),
        ],
        'how': [
            ('p', 'The fake is a simulator behind a Modbus server: the '
                  'machines compute named physical values over a simulated '
                  'clock, the profile maps them onto registers, the control '
                  'wire pins and steers — and the chaos layer makes it a '
                  'sparring partner instead of a punching bag.'),
            ('b', 'everything integrates with a **simulated clock: UTC by '
                  'default** (`--timezone local` / `set timezone local` for '
                  'the host wall clock) that can run at **N× real speed** '
                  '(`--time-scale N` / `set time-scale N`) — every machine '
                  'integrates over it, so a full simulated day takes 24/N '
                  'real hours and moving the clock (`set time 18:00`) acts as '
                  'time-lapse control.'),
            ('b', '**the day** — bell-curve PV between 06:00 and 18:00 (peak '
                  '75 % of `--max-kwp`), home load with morning and evening '
                  'peaks (grid exports around noon, imports mornings/'
                  'evenings), panel temperature following the ambient curve, '
                  'energy counters growing through the day.'),
            ('b', '**`--static`** replaces the day with constant demo values: '
                  'PV 4000 W, home 4300 W, grid −1500 W, battery charging '
                  '1200 W at 65 % SoC. The runtime control pins the '
                  'individual terms on top of either mode.'),
            ('b', '**PV (two MPPT strings)** — string-1 = the **east** array '
                  '(sine bell 06:00–16:00), string-2 = the **west** array '
                  '(08:00–18:00): together a double-shouldered day. '
                  '`set mppt both|east|west|none` enables the strings; a dark '
                  'string serves 0 V/0 A. The cloud factor scales the sun in '
                  'real time; the day yield integrates the actual string '
                  'curve.'),
            ('b', '**battery (always on)** — charges from the PV surplus (300 '
                  'W grid margin, max ±2500 W), covers the home deficit by '
                  'discharging, stops at 100 % full / the 10 % reserve floor. '
                  'The SoC is **stateful**: it integrates the effective power '
                  'with the simulated clock, with the realism folded in — '
                  '95 % charge efficiency, 0.01 %/h self-discharge, discharge '
                  'capped at 80 % of the rating, temperature-derated (below '
                  '0 °C half power, below 10 °C 80 %, above 40 °C 90 %, above '
                  '50 °C 70 %). `set soc <pct>` seeds the machine, '
                  '`set battery-state charging|discharging` forces it, '
                  '`auto`/`clear` hands the decision back; `--battery-kwh` '
                  'sizes the pack.'),
            ('b', '**grid setpoint** — `set grid <W>` pins the grid line: the '
                  'battery balances to hold it (`set grid 0` = zero-export '
                  'home); `auto` returns to the plain pv − battery − home '
                  'balance.'),
            ('b', '**clouds** — a pinned factor (`set cloud 0.7`), a clear '
                  'sky (the default), or a mean-reverting random walk: '
                  '`autumn` (passing clouds, 0.05–0.95), `spring` '
                  '(fair-weather cumulus, 0.02–0.80), `winter` (heavy '
                  'overcast spells, 0.10–1.00). `reset` returns to a clear '
                  'sky.'),
            ('b', '**grid voltage** — three independent mean-reverting walks '
                  'around the nominal (±10 % by default, the phases wander '
                  'differently); `--grid-voltage` (230 V, 120 supported — the '
                  'currents double), `--grid-voltage-wander` (the ±fraction '
                  'of the nominal, 0 = the flat grid) and the matching '
                  '`set grid-voltage` / `set grid-voltage-wander`.'),
            ('b', '**grid outages** — `set grid-outage on` arms a two-state '
                  'machine: the grid randomly drops (phases collapse, the '
                  'inverter stands by — no harvest, no battery flow, the SoC '
                  'holds) and comes back after a few moments. '
                  '`set grid-outage outage` forces a blackout right now (the '
                  'outage wins over the pins); `off` restores plain '
                  'operation.'),
            ('b', '**the unbalanced home** — three slow walks around 1/3 per '
                  'phase (each clamped 22–44 %) distribute the load '
                  'asymmetrically: the per-phase meter currents really '
                  'differ; the inverter injection stays balanced.'),
        ],
        'tail': [
            ('Register maps (the profile)', [
                ('b', 'the fake doesn\'t hardcode any device layout: the '
                      'simulator computes **named physical values** '
                      '(`pv-power`, `grid-power`, `battery-soc`, …) and the '
                      '**inverter profile** maps each name onto a register '
                      'address and encoding. The format, the semantics and '
                      'the shipped devices are documented once in '
                      '`shared/profiles/README.md`.'),
                ('b', '`show registers` prints the loaded profile as a table, '
                      '`set modbus profile <name|path>` swaps it live, '
                      '`--modbus-profile` / `MODBUS_PROFILE` pick it at start; '
                      '`clear modbus profile` returns to the configured map.'),
            ]),
            ('Signals', [
                ('t', ('signal', 'effect'),
                 ('`SIGHUP`', 're-apply the environment layer — '
                  'all-or-nothing (an invalid value keeps the previous '
                  'settings); flags are startup-only, the env is the '
                  'reloadable layer'),
                 ('`SIGUSR1`', 'reset the scenario: all runtime pins, the '
                  'cloud machine and the Modbus write overlay are dropped, '
                  'the simulation continues'),
                 ('`SIGTERM` / `SIGINT`', 'graceful shutdown with a session '
                  'summary (duration, connections, requests, chaos hits)')),
            ]),
            ('Served registers (the default profile)', [
                ('t', ('register', 'meaning'),
                 ('**32064** / **32080**', 'PV power / power limit (I32 W)'),
                 ('**32016+**', 'the string block: per-string voltage/current '
                  '(a dark string serves 0/0)'),
                 ('**37113**', 'grid power (I32 W, positive = feed-in)'),
                 ('**37100+**', 'smart meter block: status, per-phase '
                  'voltages/currents, reactive power, power factor, grid '
                  'frequency; **37119** exported / **37121** imported kWh '
                  'totals grow through the simulated day'),
                 ('**32089**', 'device status (512 on-grid / 40960 standby at '
                  'night)'),
                 ('**32087** / **32114** / **32106**', 'temperature (I16, '
                  '°C×10) / daily and total yield (U32, kWh×100)'),
                 ('**37001+**', 'battery block (power, SoC, lifetime totals)')),
                ('b', 'all of the above addresses come from the profile — '
                      'remap them freely. The profile\'s per-entry **`fc`** '
                      'picks each entry\'s address space (`3` holding / `4` '
                      'input for the word types, `1` coils / `2` discrete for '
                      '`bit` — the four spaces are served separately).'),
                ('b', 'writes stick in overlays: the register writes '
                      '(FC06/FC16) overlay the holding registers, the coil '
                      'writes (FC05/FC15) the coil space (FC5 demands the '
                      'spec values `0x0000`/`0xFF00`); computed registers are '
                      'recomputed per poll, overlay values win until cleared '
                      '(`reset`, SIGUSR1, shutdown). A malformed frame on an '
                      'implemented function code is answered with exception '
                      '03, never a silent disconnect.'),
                ('b', '**65000–65003** — the modbus-cache diagnostics block '
                      '(magic `0xCAFE`, version, uptime, id): always mocked '
                      'by the fake, never part of the profile — it exists so '
                      'the scraper\'s `scraper_cache_*` auto-detection can be '
                      'exercised without a cache. The only address range the '
                      'fake hardcodes.'),
            ]),
            ('Chaos injection (`--chaos`)', [
                ('b', '`--chaos 0.4` (probability, `--seed` for '
                      'reproducibility) makes the fake answer a fraction of '
                      'requests hostile — garbage, short/lying MBAP lengths, '
                      'wrong transaction/unit ids, stalls, dropouts, raw '
                      'exceptions — then drop the connection.'),
                ('b', 'unlike the regression suites\' scripted EvilInverter '
                      'this runs unattended: point the scraper at it and '
                      'watch `scraper_modbus_errors_total` climb while '
                      '`scraper_up` flips, with the fake never dying. Tune or '
                      'disable live (`set chaos off`).'),
            ]),
            ('Audit logging', [
                ('b', 'the fake itself and both clients append to the **audit '
                      'log** — on by default at the **XDG state home** '
                      '(`~/.local/state/fake-inverter/audit.log`); '
                      '`--audit-log <file>` renames it, `--no-audit-log` '
                      'turns it off, `--audit-log -` sends it to stdout (the '
                      'docker logs / journald way — the shipped Dockerfile '
                      'runs with it).'),
                ('b', 'the whole family is live-settable on the control wire '
                      '(the cache\'s shape): `set audit log-file '
                      '<path|-|none>` swaps the sink, `set audit instance '
                      '<id>` renames the writer daemon (`none` returns to the '
                      'derived control port), `set audit rotate max-size '
                      '<MB>` and `set audit rotate files <N>` re-chain the '
                      'rotation live, `set audit rotate daily on/off` rides '
                      'too and `set audit disable on/off` is the kill switch '
                      '(`clear <setting>` restores the configured value); the '
                      'env twins spell the same names upper-snake.'),
                ('fam', 'audit_forward'),
                ('c', '2026-11-03T20:10:06Z AUDIT application=INV tag=daemon '
                      'instance=15991 type=start hash=3f9a21c04de7 '
                      'version=0.5.1 modbus=127.0.0.1:5502 control=127.0.0.1:15991 '
                      "profile=sun2000 description='…'\n"
                      '2026-11-03T20:10:07Z AUDIT application=INV tag=daemon '
                      'instance=15991 type=command hash=9c41e2b7a058 '
                      "peer=127.0.0.1:54425 cmd='set soc 40' result=ok\n"
                      '2026-11-03T20:10:08Z AUDIT application=INV tag=daemon '
                      'instance=15991 type=reset hash=77b0c4e19d23 '
                      'signal=SIGUSR1 pins=1 coils=0 overlay=0\n'
                      '2026-11-03T20:10:08Z AUDIT application=INV tag=daemon '
                      'instance=15991 type=shutdown hash=5e2af8c30b61 '
                      'reason=SIGTERM-received uptime=2s conns=0 requests=0 '
                      'chaos_hits=0'),
                ('b', 'the clients audit their session and the local-only '
                      'events; the fake logs its lifecycle (`START`, '
                      '`RELOAD`, `RESET`, `SHUTDOWN`); ping/pong keepalives '
                      'are never logged; the file is flushed per event.'),
            ]),
            ('Testing', [
                ('b', 'the fake is the suites\' workhorse — it is exercised '
                      'from the suite root `dev/suites/`. Every scenario must '
                      'end with the fake alive and **zero tracebacks** in the '
                      'logs.'),
                ('c', 'dev/battery/battery.py inverter        # the inverter profile: the fake\'s regtest, the\n'
                      '                                  #   control fuzz, the audit chain (the suites refuse\n'
                      '                                  #   without the runner\'s PV_RUN_DIR)'),
                ('fam', 'runner'),
            ]),
            ('Deployment', [
                ('b', '**containers** — the fake\'s deployment is the alpine '
                      'image (`docker/Dockerfile.modbus-fake-inverter`): '
                      'stdlib-only, the unprivileged `pvsuite` user, the '
                      'bundled conf as the default `--config` target; the '
                      'demo compose stack runs it beside the cache and the '
                      'scraper (`docker/README.md`), the env file '
                      '(`docker/env/modbus-fake-inverter.env.example`) and '
                      'the CMD flags carry the shape.'),
                ('b', '**NixOS** — no service module for the fake by design '
                      '(a test tool does not ship as infrastructure); point '
                      '`--modbus-profile` at a `shared/profiles/` copy and '
                      'run it from the checkout or the container.'),
            ]),
            ('Troubleshooting', [
                ('b', '**errors climbing on the scraper** — with `--chaos` on '
                      'that is the fake working as intended: '
                      '`scraper_modbus_errors_total` climbs while '
                      '`scraper_up` flips and the fake never dies; tune or '
                      'disable live (`set chaos off`, `--seed` pins a '
                      'run).'),
                ('b', '**reads answer yesterday\'s writes** — the write '
                      'overlay: register/coil writes stick until `reset` '
                      '(or `SIGUSR1`, or the shutdown) — the audit trail\'s '
                      '`type=reset` event names what was dropped.'),
                ('b', '**a pin refuses at start** — the demo machines are '
                      'runtime set words: the config file and the flags '
                      'carry the registry knobs only; drive the pins over '
                      'the control wire.'),
                ('b', '**deeper** — `--log-level DEBUG` logs every frame both '
                      'ways; `SIGUSR2` dumps the thread stacks; the audit '
                      'trail chain-verifies with '
                      '`dev/gates/audit_verify.py`.'),
            ]),
            ('The docs map', [
                ('fam', 'docs'),
            ]),
            ('Configuration', [
                ('b', 'the config file (`--config PATH`, `$CONFIG`, then '
                      '`modbus-fake-inverter.conf` next to the script) speaks '
                      'the **set grammar** — every line a `set <name> <value>` '
                      'in the CLI spelling, the same line pastes into the '
                      'console or `modbus-fake-cli`; a value resolves flag > '
                      'env > this file > the row\'s default, and `--dry-run` '
                      'prints the effective settings.'),
                ('b', 'the bundled `apps/inverter/examples/modbus-fake-inverter'
                      '.conf` is GENERATED from the registry '
                      '(`dev/generators/examples.py`): every knob declared, '
                      'every line commented at its default — copy it, '
                      'uncomment what you change, point `--config` at it.'),
                ('b', 'the pins and the machines (`set pv`, `set load`, '
                      '`set batt`, `set grid`, `set soc`, `set mppt`, '
                      '`set cloud`, `set scenario`, `set battery-state`, '
                      '`set grid-outage`) are runtime set words — no flag, no '
                      'env twin, no config line: the file names one and the '
                      'start refuses. They exist to be driven live.'),
                ('b', '`SIGHUP` re-applies the **environment layer** '
                      '(all-or-nothing — flags are startup-only): a config '
                      'change to a knob rides the reload; the machine pins '
                      'never do (they are runtime state by design).'),
            ]),
            ('Access control', [
                ('b', 'the fake is the family\'s **trusted-LAN test tool '
                      '(F11)**: control works over TCP without a token too '
                      '(`--control-token` is still honored when the wire is '
                      'not yours); over the unix socket a trusted peer (root, '
                      'the daemon\'s own user or `--control-trust-uids` — '
                      'SO_PEERCRED) always speaks without one. Bind it to '
                      'loopback when in doubt.'),
                ('b', 'the Modbus leg: `--connect-acl` (`any` / `none` / a '
                      'comma-separated IP/CIDR list / `file:<path>`) gates '
                      'which Modbus clients may connect at all, and '
                      '`--modbus-auth suite` (+ `--modbus-auth-key`, min 16 '
                      'characters, `file:<path>` the shipped spelling) makes '
                      'the fake the **server side** of the suite handshake — '
                      'a client that cannot prove the key never sees a '
                      'frame.'),
                ('b', 'writes are the point: the register/coil overlay is the '
                      'feature, so there is no write ACL — every write the '
                      'overlay takes lands in the audit trail instead '
                      '(`type=command` / the `reset` events).'),
                ('b', 'the fake\'s own `/metrics` (`--metrics-server`) carries '
                      'the family posture: a bearer token beyond loopback '
                      '(`--metrics-token`) and the metrics ACL '
                      '(`--metrics-acl`).'),
            ]),
            ('Metrics', [
                ('b', 'the power numbers are **not** metrics here — they are '
                      'Modbus registers (the profile above) the scraper '
                      'exports; point the scraper at the fake and the '
                      'dashboard at the scraper.'),
                ('b', 'the fake does carry the family\'s own `/metrics` stack '
                      '(`--metrics-server` / `--metrics-listen`, off by '
                      'default) for its self-observability — the token and '
                      'the ACL ride as in Access control.'),
            ]),
            ('Source layout', [
                ('p', 'the subproject is flat and stdlib-only — one bin pair, '
                      'one lib package, the generated surfaces beside. The '
                      'checkout launchers (`dev`, `dev-cli`) run the fake and '
                      'the console straight from the tree.'),
                ('c', 'apps/inverter/\n'
                      '├── bin/\n'
                      '│   ├── modbus-fake-inverter.py    # the daemon: the CLI, the simulator wiring, the\n'
                      '│   │                             #   signal handling, the control server\n'
                      '│   └── modbus-fake-cli.py -> ../../pvsuite-cli.py\n'
                      '│                                # the family client dispatcher: the tool\n'
                      '│                                #   from the name it was invoked as\n'
                      '├── lib/\n'
                      '│   ├── simulator.py               # the simulated day (or frozen/static): the curves,\n'
                      '│   │                             #   the runtime overrides, the pins\n'
                      '│   ├── inverter.py                # the Modbus TCP server: FC3/FC4 + FC1/FC2 from the\n'
                      '│   │                             #   simulator, the write overlays\n'
                      '│   ├── profile.py                 # the register-map profiles: the named value ->\n'
                      '│   │                             #   the address + encoding\n'
                      '│   ├── battery.py                 # the battery state machine (the surplus, the\n'
                      '│   │                             #   deficit, the SoC integration)\n'
                      '│   ├── chaos.py                   # the seeded chaos layer (garbage, stalls, drops)\n'
                      '│   ├── signals.py                 # the family signal handling (SIGHUP the env layer,\n'
                      '│   │                             #   SIGUSR1 the reset, SIGUSR2 the stacks)\n'
                      '│   ├── metrics.py                 # the fake\'s own /metrics (off by default)\n'
                      '│   ├── control.py                 # the JSON-lines control server (the pins, the\n'
                      '│   │                             #   machines, the reset)\n'
                      '│   ├── config.py                  # the set grammar: the config script, the env, the\n'
                      '│   │                             #   flags\n'
                      '│   ├── statics.py                 # the demo device\'s born-with numbers\n'
                      '│   │                             #   (lib/defaults.json)\n'
                      '│   ├── options.py + options.json  # the registry: the one row per knob\n'
                      '│   ├── cli_spec.py                # the client SPEC (pvsuite-cli\'s per-tool half)\n'
                      '│   └── man.py                     # the generated man pages\n'
                      '├── examples/modbus-fake-inverter.conf\n'
                      '│                                 # the GENERATED sample (every knob, commented)\n'
                      '├── man/                           # the generated man page\n'
                      '└── dev, dev-cli                   # the checkout launchers'),
                ('p', 'the shared machinery lives in the suite\'s `common/` '
                      'package (the control spine, the Modbus server, the '
                      'audit, the manpage generator) and `shared/` (the '
                      'texts, the schemas, the profiles) — `lib/` imports it '
                      'by path; the client dispatcher is the suite\'s '
                      '`apps/pvsuite-cli.py`, one script for all four ctl '
                      'tools.'),
            ]),
            ('The docs map', [
                ('t', ('this tool\'s documents', 'what they carry'),
                 ('`apps/inverter/README.md`', 'the front page — the description, '
                  'the quick how-to, Security, License'),
                 ('`apps/inverter/lib/options.json`', 'the registry — the one row '
                  'per knob (the tables above render from it)'),
                 ('`apps/inverter/examples/modbus-fake-inverter.conf`', 'the '
                  'GENERATED sample configuration'),
                 ('`apps/inverter/man/`', 'the generated man page '
                  '(`modbus-fake-inverter --man` renders it)'),
                 ('`shared/profiles/`', 'the device profiles the fake serves '
                  '(the format: `shared/profiles/README.md`)'),
                 ('`docker/Dockerfile.modbus-fake-inverter` + '
                  '`docker/env/modbus-fake-inverter.env.example`', 'the image '
                  'and the deployment env (the topologies: `docker/README.md`)')),
                ('fam', 'docs'),
            ]),
            ('Runtime control', [
                ('b', 'the fake IS runtime control — the demo machines are '
                      'runtime set words with no startup surface: '
                      '`set pv|load|batt|grid|soc|mppt|cloud|scenario|'
                      'battery-state|grid-outage` pin the simulation live, '
                      '`auto` / `clear <pin>` hands the decision back to the '
                      'day, `set time 18:00` is time-lapse control, '
                      '`set time-scale N` runs the clock N× real speed.'),
                ('b', 'the write emulation is runtime too: '
                      '`set register <addr> <value>` plants a holding-register '
                      'value, `set coil <addr> <0|1>` a coil — reads answer '
                      'the overlay until `reset` (or `SIGUSR1`) drops every '
                      'pin, the cloud machine and the overlay together.'),
                ('b', 'the registry knobs ride the family ladder: the '
                      'settable rows apply at once, the restart-marked record '
                      'a pending `set` and fold in on `request reload`, the '
                      'secrets never render back; every command is audited '
                      'once, by the server.'),
                ('c', '# live: freeze the evening, cloud it over, seed the SoC\n'
                      'set time 18:00\n'
                      'set cloud 0.7\n'
                      'set soc 40\n'
                      'reset'),
            ]),
        ],
    },
    'dashboard': {
        'family': [
            ('b', 'the dashboard is the chain\'s face: **the browser\'s '
                  'window onto the scraper\'s numbers** — Prometheus '
                  'behind it, the energy math in the page, the proxy '
                  'keeping the collector off the wire.'),
        ],
        'run': [
            ('c', 'python3 bin/dashboard.py                          # upstream http://localhost:9090\n'
                  'python3 bin/dashboard.py --listen 127.0.0.1:8080 --upstream '
                  'http://192.168.1.50:9090\n'
                  'PROM_URL=http://pi:9090 python3 bin/dashboard.py  # via env\n'
                  '# open http://localhost:8080'),
            ('b', 'the server **binds to `127.0.0.1:8080`** (loopback only) — '
                  'pass `--listen 0.0.0.0:8080` to serve the LAN. The page and '
                  'the proxy speak the family\'s F13 shape (the audit\'s F21): '
                  'a **bearer token is mandatory beyond loopback** — a '
                  'token-less non-loopback bind refuses to start. Set '
                  '`--auth-token` (or `file:<path>`); the browser opens '
                  '`http://host:8080/?auth=<token>` once — the exchange sets '
                  'an HttpOnly session cookie — and scripts send '
                  '`Authorization: Bearer <token>`. On the loopback bind the '
                  'token is optional. Beyond localhost, still terminate TLS '
                  'at an authenticating proxy (below).'),
            ('b', '**static-only mode:** any web server works '
                  '(`python3 -m http.server 8080 -d static`), but then set '
                  '`prometheusUrl` in `config.js` to the direct Prometheus '
                  'URL — the browser fetches it directly, which requires CORS '
                  'to be allowed.'),
            ('b', 'the server\'s settings resolve CLI > env (the bare '
                  'upper-snake twins: `LISTEN`, `PROM_URL`, `PROM_PREFIX`, '
                  '`STATIC_DIR`, `CONFIG_JS`, `AUTH_TOKEN`, the caps, '
                  '`LOG_ACCESS`, `CTL`, `CONTROL_TOKEN`, …) > '
                  '`dashboard.conf` (the set grammar — every line a '
                  '`set <name> <value>`; the bundled sample is '
                  '`examples/dashboard.conf`) > defaults.'),
            ('b', '`--prom-prefix \'\'` (empty) proxies *every* unmatched path '
                  'to Prometheus. The HTTP surface carries the family\'s '
                  'connection caps (`--max-clients`, `--max-conn-per-ip`, '
                  '`--client-timeout`) — all live-settable through the '
                  'control server.'),
        ],
        'how': [
            ('p', 'The page is one HTML document served by a small Python '
                  'server that also proxies Prometheus — the flow diagram, '
                  'the energy math and the CSV export live in the browser; '
                  'the server adds the auth, the caps and the control wire.'),
            ('b', '**flow diagram** — live PV / Load / Grid nodes with '
                  'animated energy particles (orange = solar, violet = grid '
                  'import; speed and particle rate follow the power). Grid '
                  'value is computed as **export − import** from the '
                  'configured `gridExport` / `gridImport` metrics: '
                  '**negative = import, positive = export**.'),
            ('b', '**energy summary** — generated by PV, consumed by '
                  'appliances, self-consumption vs fed-to-grid, with '
                  'percentage bars, an energy table and a zoomable '
                  'time-series chart. Energy (kWh) is integrated from '
                  '`avg_over_time(<metric>[<step>s])` buckets, so every raw '
                  'sample inside a bucket contributes — spikes are not lost; '
                  'the step is always a multiple of `scrapeSec`.'),
            ('b', '**auto-refresh** — selectable in the header (30 s / 1 min '
                  '/ 5 min / 30 min / custom); a switch refreshes the flow '
                  'diagram, chart and table together.'),
            ('b', '**CSV export** — energy in **watt-hours** (integrated from '
                  'every Prometheus bucket in the period — same math as the '
                  'table) for PV Yield, Home, Grid Export and Grid Import, '
                  'zero-filled over the full period: hourly (day view), daily '
                  '(month view), monthly (year view), per-year for "All '
                  'time", plus an hourly detailed export for a whole month. '
                  'ISO 8601 timestamps.'),
            ('b', '**battery** — `battery: true` in `config.js` joins a '
                  'Battery node to the flow diagram (teal particles: up = '
                  'discharging, down = charging, a SoC % line), splits the '
                  'energy three-way (PV / battery / grid) and adds the CSV '
                  'columns. Without a working battery selector (missing '
                  'metric or a constant `0`), the node dims and a warning '
                  'banner appears.'),
            ('b', '**theme** (dark / light / system) and **language** (EN / '
                  'PL; add a language as `de: { ... }` in `i18n.js` — it '
                  'appears in the switcher automatically) in the header, '
                  'persisted in localStorage.'),
            ('b', 'if Prometheus is unreachable, the page switches to **DEMO '
                  'DATA** so you can preview the layout.'),
        ],
        'tail': [
            ('Page configuration (config.js)', [
                ('b', 'all settings live in `config.js` (the shipped example '
                      'is `examples/config.js`, served at `/config.js`; '
                      'relocate with `--config-js`, `$CONFIG_JS` or '
                      '`set config-js <file>` in `dashboard.conf` — if the '
                      'override file is missing, `/config.js` 404s and the '
                      'page boots with built-in defaults).'),
                ('c', 'const SOLAR_CONFIG = {\n'
                      '  prometheusUrl: \'/prom\',\n'
                      '  battery: true,\n'
                      '  metrics: {\n'
                      '    pv: \'huawei_pv_generation_watts{job="sun2000"}\',\n'
                      '    gridExport: \'huawei_grid_export_watts{job="sun2000"}\',\n'
                      '    gridImport: \'huawei_grid_import_watts{job="sun2000"}\',\n'
                      '    load: \'huawei_home_consumption_watts{job="sun2000"}\',\n'
                      '    battery: \'huawei_battery_net_watts{job="sun2000"}\',\n'
                      '    batterySoC: \'huawei_battery_soc_percent{job="sun2000"}\'\n'
                      '  },\n'
                      '  scrapeSec: 10,\n'
                      '  smoothMin: 30,\n'
                      '  refreshSec: 30,\n'
                      '  defaultLang: \'en\',\n'
                      '  enableAllTime: false\n'
                      '};'),
                ('t', ('key', 'meaning'),
                 ('`prometheusUrl`', '`/prom` (the same-origin proxy) or a '
                  'direct Prometheus URL'),
                 ('`metrics`', 'the full metric selectors — label matchers are '
                  'passed through to PromQL; values always in **watts**. '
                  '`gridExport` = export power (≥ 0); with `gridImport` set, '
                  'the net grid value is `export − import`'),
                 ('`battery`', 'the battery panels\' master switch (the '
                  'selectors: `metrics.battery` signed W / '
                  '`metrics.batterySoC` %; an optional `metrics.batteryFlag` '
                  'present-flag for exporters that have one)'),
                 ('`scrapeSec`', 'the Prometheus scrape interval in seconds '
                  '(bucket size)'),
                 ('`smoothMin`', 'display smoothing window in minutes '
                  '(0 = raw)'),
                 ('`refreshSec`', 'the default auto-refresh interval (the '
                  'header combo overrides; 0 = off)'),
                 ('`defaultLang`', 'the default UI language (`en`/`pl`)'),
                 ('`enableAllTime`', 'show the "All time" selector (for a '
                  'long-retention backend); `?all` also works'),
                 ('`liveSec` / `chartSec`', 'the flow-diagram / chart-panel '
                  'refresh intervals')),
                ('b', 'URL params (`?prom=…&gridExport=…&grid=…&gridImport=…'
                      '&pv=…&load=…&battery=1&batteryMetric=…&batterySoC=…'
                      '&batteryFlag=…&scrape=…&smooth=…&refresh=…&lang=…'
                      '&demoHour=…&consent=0`) override `config.js` for quick '
                      'testing. `config.js` and `i18n.js` locations are '
                      'configurable (`?config=<path>` / `?i18n=<path>`); a '
                      'failed load falls back to the files next to the page, '
                      'then to the built-in defaults.'),
            ]),
            ('Behind a reverse proxy', [
                ('b', 'the dashboard only makes same-origin GET requests — any '
                      'proxy works.'),
                ('b', '**A. proxy → dashboard.py** (keeps Prometheus hidden): '
                      'run `bin/dashboard.py --listen 127.0.0.1:8080` so only '
                      'the proxy reaches it.'),
                ('c', 'location / { proxy_pass http://127.0.0.1:8080; }   '
                      '# nginx\n'
                      '\n'
                      'solar.example.com { reverse_proxy 127.0.0.1:8080 }  '
                      '# Caddy'),
                ('b', '**B. the proxy serves the static files and routes '
                      '`/prom` to Prometheus itself:**'),
                ('c', 'root /var/www/dashboard;\n'
                      'location /prom/ { proxy_pass http://127.0.0.1:9090/; }'
                      '  # trailing slash strips prefix'),
                ('b', '`prometheusUrl: \'/prom\'` works in both cases. Mount '
                      'at the root (or strip the prefix); add auth at the '
                      'proxy if exposed to the internet.'),
            ]),
            ('Metrics', [
                ('b', 'the page expects PV inverter metrics in Prometheus '
                      '(`huawei_*_watts` — the scraper\'s `--metrics-prefix` '
                      'default). The `scraper/` subproject ships a '
                      'dependency-free Python exporter that polls the inverter '
                      'over Modbus TCP and serves exactly those metrics — see '
                      '`../scraper/README.md`.'),
                ('c', 'python3 apps/scraper/bin/modbus-scraper.py --upstream '
                      '<inverter-lan-ip>:502 --listen 0.0.0.0:9350\n'
                      '\n'
                      '# prometheus.yml — the job name must be "sun2000" (the '
                      'dashboard filters on it)\n'
                      'scrape_configs:\n'
                      '  - job_name: sun2000\n'
                      '    scrape_interval: 10s          # match scrapeSec in '
                      'config.js\n'
                      '    static_configs:\n'
                      '      - targets: [\'localhost:9350\']'),
                ('b', 'the inverter accepts only one Modbus TCP client — the '
                      '`cache/` subproject is an **experimental** caching '
                      'proxy that multiplexes that one connection so the '
                      'scraper can share it with other tools '
                      '(`../cache/README.md`).'),
            ]),
            ('Testing', [
                ('b', 'the dashboard profile rides the battery runner; the '
                      '`/config.js` fuzz pin rides the same suite (a bogus '
                      'override file must not crash the server). The scenario '
                      'must end with the server alive and **zero tracebacks** '
                      'in the logs.'),
                ('c', 'dev/battery/battery.py dashboard             # the dashboard profile: the control fuzz +\n'
                      '                                       #   the audit chain (the suites refuse without\n'
                      '                                       #   the runner\'s PV_RUN_DIR)'),
                ('fam', 'runner'),
            ]),
            ('Deployment', [
                ('b', '**NixOS** — the module `nixos/modules/dashboard.nix` '
                      'renders the server as a hardened service (the options '
                      'mapped in `nixos/README.md`): the listen, the upstream, '
                      'the page token (`*File`), `staticDir` and '
                      '`solarConfig` ride the module — the static assets can '
                      'ship straight from the store.'),
                ('b', '**containers** — `docker/Dockerfile.dashboard`, the '
                      'demo compose stack (the dashboard + prometheus + the '
                      'scraper) and the prod split beside it '
                      '(`docker/README.md`); the env file '
                      '(`docker/env/dashboard.env.example`) carries the '
                      'bind, the upstream and the page token.'),
                ('b', '**static-only** — any web server works '
                  '(`python3 -m http.server 8080 -d static`): set '
                  '`prometheusUrl` to the direct Prometheus URL and allow '
                  'the CORS — the control plane and the audit are a '
                  '`dashboard.py` feature (the static face alone has '
                  'neither).'),
            ]),
            ('Troubleshooting', [
                ('b', '**the page says DEMO DATA** — Prometheus is '
                      'unreachable from the server: check `--prom-url` / '
                      '`PROM_URL` (the proxy targets it, not the browser — '
                      'unless `config.js` names a direct URL, which then '
                      'needs the CORS).'),
                ('b', '**the page boots with defaults** — `/config.js` 404ed: '
                      'the `--config-js` override file is missing (the '
                      'section above); the fuzz pin guarantees a bogus '
                      'override never crashes the server.'),
                ('b', '**the auth dance fails** — the `?auth=<token>` '
                      'exchange sets the session cookie once; a rejected '
                      'exchange means the token mismatched (the audit trail '
                      'carries the auth failure), scripts must send '
                      '`Authorization: Bearer` on every request.'),
                ('b', '**connections dropped** — the caps '
                      '(`--max-clients`, `--max-conn-per-ip`) refuse and log '
                      'beyond their limits; the /metrics pair has its own '
                      'two.'),
                ('b', '**deeper** — `--log-level DEBUG`, `SIGUSR2`\'s thread '
                      'stacks, the audit trail chain-verifying with '
                      '`dev/gates/audit_verify.py`.'),
            ]),
            ('The docs map', [
                ('fam', 'docs'),
            ]),
            ('Configuration', [
                ('b', 'the daemon\'s config file (`--config PATH`, env '
                      '`CONFIG`) speaks the **set grammar** — one '
                      '`set <name> <value>` per line, the control CLI\'s own '
                      'spelling; a value resolves CLI > env (the bare '
                      'upper-snake twins) > this file > the row\'s default.'),
                ('b', 'the bundled `apps/dashboard/examples/dashboard.conf` is '
                      'GENERATED from the registry (`dev/generators/examples.'
                      'py`): every knob declared, every line commented at its '
                      'default — copy it, uncomment what you change, point '
                      '`--config` at it. The docker image rides it as its '
                      'default `--config` target; the caps and the listen '
                      'address are live-settable through the control server.'),
                ('b', 'the PAGE has its own config — `config.js`, served at '
                      '`/config.js` and covered in its own section below: the '
                      'daemon conf configures the server, `config.js` '
                      'configures what the browser renders.'),
            ]),
            ('Access control', [
                ('b', 'the page and the proxy speak the family\'s F13 shape: '
                      'a **bearer token is mandatory beyond loopback** — a '
                      'token-less non-loopback bind refuses to start. The '
                      'browser opens `http://host:8080/?auth=<token>` once — the '
                      'exchange sets an HttpOnly session cookie — and scripts '
                      'send `Authorization: Bearer <token>`; on the loopback '
                      'bind the token is optional.'),
                ('b', 'the HTTP surface carries the family\'s connection caps '
                      '— `--max-clients` (64), `--max-conn-per-ip`, and the '
                      '`/metrics` pair (`--metrics-max-clients`, '
                      '`--metrics-max-conn-per-ip`) — all live-settable '
                      'through the control server.'),
                ('b', 'the dashboard\'s own `/metrics` (the scraper-feeding '
                      'stack) carries the same posture: the token '
                      '(`--metrics-token`) and the metrics ACL '
                      '(`--metrics-acl`, live `set metrics acl`) beyond '
                      'loopback.'),
                ('b', 'beyond localhost, still terminate TLS at an '
                      'authenticating proxy — see `Behind a reverse proxy` '
                      'below.'),
            ]),
            ('Audit logging', [
                ('b', 'the dashboard writes the family\'s audit trail — one '
                      'line per event, who/when/what/result, on by default at '
                      'the XDG state home; `--audit-log <file>` renames it, '
                      '`-` sends it to stdout (the journald way), `none` with '
                      'a forward spelled is the remote-only mode, and '
                      '`--no-audit-log` disables entirely. Rotation: '
                      '`--audit-max-mb`, `--audit-daily`, `--audit-files`.'),
                ('fam', 'audit_forward'),
            ]),
            ('Register maps', [
                ('b', 'none — the dashboard owns no Modbus registers and no '
                      'device profile: it renders Prometheus series. The '
                      'metric selectors live in `config.js` (its own section '
                      'below); the registers themselves are the scraper\'s '
                      'and the cache\'s business.'),
            ]),
            ('Source layout', [
                ('p', 'the subproject is flat and stdlib-only — the page '
                      'itself is static files, the server is one lib package, '
                      'the generated surfaces beside. The checkout launchers '
                      '(`dev`, `dev-cli`) run the server and the console '
                      'straight from the tree.'),
                ('c', 'apps/dashboard/\n'
                      '├── bin/\n'
                      '│   ├── dashboard.py               # the server: the page host, the Prometheus\n'
                      '│   │                             #   proxy, the /metrics, the control wiring, the\n'
                      '│   │                             #   signal handling\n'
                      '│   └── dashboard-cli.py -> ../../pvsuite-cli.py\n'
                      '│                                # the family client dispatcher: the tool\n'
                      '│                                #   from the name it was invoked as\n'
                      '├── static/                       # the page: index.html, app.js, boot.js,\n'
                      '│                                #   i18n.js, style.css, the vendored ECharts\n'
                      '├── lib/\n'
                      '│   ├── control.py                 # the JSON-lines control server\n'
                      '│   ├── metrics.py                 # the server\'s own /metrics (the F13 gate)\n'
                      '│   ├── config.py                  # the set grammar: the config script, the env,\n'
                      '│   │                              #   the flags\n'
                      '│   ├── statics.py                 # the static server + proxy defaults\n'
                      '│   │                              #   (lib/defaults.json)\n'
                      '│   ├── options.py + options.json  # the registry: the one row per knob\n'
                      '│   ├── cli_spec.py                # the client SPEC (pvsuite-cli\'s per-tool half)\n'
                      '│   └── man.py                     # the generated man pages\n'
                      '├── examples/                      # the GENERATED dashboard.conf + the example config.js\n'
                      '├── screenshots/                   # the README\'s captures\n'
                      '├── man/                           # the generated man page\n'
                      '└── dev, dev-cli                   # the checkout launchers'),
                ('p', 'the shared machinery lives in the suite\'s `common/` '
                      'package (the control spine, the audit, the manpage '
                      'generator) and `shared/` (the texts, the schemas) — '
                      '`lib/` imports it by path; the client dispatcher is '
                      'the suite\'s `apps/pvsuite-cli.py`, one script for all '
                      'four ctl tools.'),
            ]),
            ('The docs map', [
                ('t', ('this tool\'s documents', 'what they carry'),
                 ('`apps/dashboard/README.md`', 'the front page — the description, '
                  'the quick how-to, Security, License'),
                 ('`apps/dashboard/lib/options.json`', 'the registry — the one row '
                  'per knob (the tables above render from it)'),
                 ('`apps/dashboard/static/`', 'the page itself (the UI, the '
                  'i18n, the charts)'),
                 ('`apps/dashboard/examples/`', 'the GENERATED dashboard.conf + '
                  'the example config.js (the Page configuration section '
                  'quotes it)'),
                 ('`apps/dashboard/man/`', 'the generated man page '
                  '(`dashboard --man` renders it)'),
                 ('`nixos/modules/dashboard.nix`', 'the NixOS service module '
                  '(the options mapped in `nixos/README.md`)'),
                 ('`docker/Dockerfile.dashboard` + `docker/env/dashboard.env.'
                  'example`', 'the image and the deployment env (the '
                  'topologies: `docker/README.md`)')),
                ('fam', 'docs'),
            ]),
            ('Runtime control', [
                ('b', 'the live layer: the connection caps (`set max-clients`, '
                      '`set max-conn-per-ip`), the metrics ACL, the audit '
                      'sinks and the rotation are settable rows applying at '
                      'once; `clear <name>` returns the configured value, '
                      '`show <name>` prints the live one.'),
                ('b', 'the restart-marked rows (the listen address) record a '
                      'pending `set` and fold in on `request reload` (or a '
                      'restart); the secrets are startup-only — they never '
                      'render back, a restart applies them.'),
                ('b', 'every command is audited once, by the server (the '
                      'peer, the role, the mac); the ops-token sessions ride '
                      'the read-only verb policy (no set/clear, no '
                      '`request reload`, no shutdown).'),
                ('c', '# live: widen the door, re-read the file\n'
                      'set max-clients 128\n'
                      'set max-conn-per-ip 8\n'
                      'request reload'),
            ]),
        ],
    },
    'modbus-replay': {
        'family': [
            ('b', 'the replay is the debug sidecar: **it taps the chain\'s '
                  'Modbus hops** (capture — the wire keeps flowing, the '
                  'trace grows beside it) **or stands in for the device** '
                  '(replay — the client debugs against the recorded '
                  'hardware).'),
        ],
        'run': [
            ('c', '# capture: the cache\'s polls to the real device, the wire '
                  'to a trace\n'
                  'python3 apps/modbus-replay/bin/modbus-replay.py --upstream '
                  'inverter-lan:502 --capture sun2000-morning.pvmb\n'
                  '# a capture left running: rotate the trace at 100 MB, keep '
                  '5 backups\n'
                  'python3 apps/modbus-replay/bin/modbus-replay.py --upstream '
                  'inverter-lan:502 --capture sun2000.pvmb --trace-max-mb 100 '
                  '--trace-files 5\n'
                  '# pass-through inspector (no trace): the decoded frames at '
                  'DEBUG\n'
                  'python3 apps/modbus-replay/bin/modbus-replay.py --upstream '
                  ':502 --log-level DEBUG\n'
                  '# replay: the scraper debugs against the morning\'s trace, '
                  'hardware-free\n'
                  'python3 apps/modbus-replay/bin/modbus-replay.py --replay '
                  'sun2000-morning.pvmb\n'
                  '# the recorded device latencies, 10x faster than captured\n'
                  'python3 apps/modbus-replay/bin/modbus-replay.py --replay '
                  'sun2000-morning.pvmb --replay-speed 10\n'
                  '# the reader face: the summary, the answer index, the '
                  'conversations\n'
                  'python3 apps/modbus-replay/bin/modbus-replay-dump.py '
                  'sun2000-morning.pvmb\n'
                  '# live: the conversations render off the running daemon\'s '
                  'record feed\n'
                  'python3 apps/modbus-replay/bin/modbus-replay-dump.py '
                  '--socket\n'
                  '# live: the feed saved to a trace file while it renders '
                  '(the cache\'s feed too)\n'
                  'python3 apps/modbus-replay/bin/modbus-replay-dump.py '
                  '--socket --record live.pvmb'),
            ('b', 'exit codes: `0` = ran (SIGTERM/SIGINT: the graceful '
                  'shutdown), `1` = invalid configuration or a failed bind '
                  '(reason on stderr), `2` = CLI misuse.'),
            ('b', 'the daemon is a **sidecar, not a deployment**: no container '
                  'image, no Nix package, no service module — run it from a '
                  'checkout (`apps/modbus-replay/dev` is the launcher) or a '
                  'plain `python3` line, next to the tools it debugs.'),
            ('b', 'the startup surface is the flags and their bare env twins: '
                  '**flag > env > the built-in defaults** — there is no config '
                  'file (the sidecar has no control plane either: every knob '
                  'is a startup knob). The knobs table below IS the flags '
                  'table.'),
        ],
        'how': [
            ('p', 'The sidecar is two faces over one trace format: capture '
                  'pipes and taps, replay indexes and answers — the raw '
                  'frames the one truth either way.'),
            ('t', ('mode', 'knobs', 'what happens'),
             ('capture', '`--upstream HOST:PORT` (+ `--capture FILE`)',
              'every client is piped to the device; the wire dumps to the '
              'trace'),
             ('replay', '`--replay FILE`',
              'the trace is served: recorded responses answer matching '
              'requests')),
            ('b', '**capture mode is a pipe with a shadow copy.** Every '
                  'accepted client is paired with an upstream connection to '
                  'the device; bytes flow as they arrive, never held. A tap '
                  'reassembles the MBAP frames from the piped bytes (both '
                  'directions) and appends one record per frame to the trace '
                  'file — timestamps, direction, the raw frame bytes. A frame '
                  'the framing cannot parse still reaches the device and rides '
                  'the trace raw — the auth handshakes ride exactly there '
                  '(below). Without `--capture` the proxy runs pass-through '
                  '(the decoded frames log at DEBUG only) — a quiet wire '
                  'inspector.'),
            ('b', '**no control plane** — that is the design: no JSON-lines '
                  'control server, no `-cli` client, no runtime set/show. The '
                  'debug surface is the Modbus port, the trace file and the '
                  'log; the capture posture is fixed at start.'),
        ],
        'tail': [
            ('The trace format', [
                ('b', 'the trace is 0600 at rest (the wire carries values — '
                      'and a Waveshare capture carries the connection password '
                      'raw; the trace belongs with the secrets). Two shapes, '
                      'the same feature set — `--dump-type` picks what capture '
                      'writes, every reader speaks both.'),
                ('b', '**binary** (the default) — a `PVMB` file: one header '
                      'block per run, then one length-framed, CRC-checked '
                      'block per record. About half the bytes of the JSON '
                      'spelling, no parser on the read path, and a torn tail '
                      'costs one record instead of the file.'),
                ('b', '**json** (the v1 spelling) — JSON lines: one record per '
                      'frame, the decoded fields (`txn`, `fc`, `addr`, …) '
                      'riding beside the raw hex — the `head`/`grep`/`jq` '
                      'spelling.'),
                ('c', 'header block (one per run — the anchor):\n'
                      "  0   4   magic  b'PVMB'\n"
                      '  4   1   version (1)\n'
                      '  5   1   reserved (0)\n'
                      '  6   8   started (u64 epoch seconds)\n'
                      '  14  2   upstream_len (u16)\n'
                      '  16  N   upstream (utf-8 — the recorded posture '
                      'string)\n'
                      '  +4  4   crc32 over bytes 0 .. 16+N\n'
                      '\n'
                      'record block (one per frame):\n'
                      '  0   4   body_len (u32) — the body\'s length; the '
                      'skip unit\n'
                      '  4   8   ts (f64 epoch — the wall clock, the trace\'s '
                      'own domain)\n'
                      '  12  1   kind (0=req, 1=rsp, 2=raw c2d, 3=raw d2c)\n'
                      '  13  4   conn (u32 — the proxy leg pair)\n'
                      "  17  1   peer_len (u8) + N peer (utf-8 'ip:port')\n"
                      '  ..  1   note_len (u8) + N note\n'
                      '  ..  2   raw_len (u16) + N raw (the MBAP frame, '
                      'verbatim)\n'
                      '  ..  4   crc32 over the body (ts .. raw)'),
                ('b', 'the record walk: the header at offset 0 anchors it; a '
                      'mid-file `PVMB` block is a later run\'s header — the '
                      'session boundary (the trace **appends across runs**, a '
                      'multi-run file is a longer history; the conn ids '
                      'restart each run). A block that runs past EOF is a torn '
                      'tail: the walk keeps what parsed and notes the loss — a '
                      'killed capture leaves a readable trace. A mid-file CRC '
                      'failure resync-scans for the next header; the records '
                      'between the tear and the re-anchor are lost with the '
                      'tear. The JSON walk reads the same story line-wise: a '
                      'torn line skips (noted), a later header line is the '
                      'boundary. A foreign file or a future version refuses '
                      'with a clean one-liner.'),
                ('b', '**a capture left running grows unbounded** — '
                      '`--trace-max-mb` rotates the trace at that size, keeping '
                      '`--trace-files` backups (`0` = no size rotation, the '
                      'default). At the size the backups shift '
                      '(`trace.pvmb.1` ← `trace.pvmb.2` ← …, the oldest '
                      'dropped), the file reopens fresh and stamps a new run '
                      'header: the fresh capture keeps the plain name, and '
                      '**every backup is a complete trace of its own** — any '
                      'reader takes each for captured (the views, the '
                      'converter, `--replay` serve one slice at a time). A '
                      'record is the rotation boundary: a block never '
                      'straddles two files. The dump tool\'s `--record` '
                      'carries the same pair and rotates the same way (the '
                      'recorder re-stamps a header of its own — the feed\'s '
                      'posture, now).'),
                ('c', '{"format":"pv-suite-modbus-trace","version":1,'
                      '"started":"…","tool":"modbus-replay","mode":"capture",'
                      '"upstream":"inverter-lan:502"}\n'
                      '{"ts":1794588996.048,"dir":"req","conn":1,'
                      '"peer":"127.0.0.1:64824","raw":"004d…","txn":77,'
                      '"unit":1,"fc":3,"addr":32064,"count":2}\n'
                      '{"ts":1794588996.048,"dir":"rsp","conn":1,'
                      '"peer":"inverter-lan:502","raw":"004d…","txn":77,'
                      '"unit":1,"fc":3,"bytes":4}'),
                ('b', '`dir` speaks the client\'s view (`req` = client to '
                      'device, `rsp` = the device\'s answer, `raw` = the '
                      'framing lost); exception responses record their code '
                      '(`"exc": 2`).'),
                ('t', ('pair', 'json', 'binary', 'win'),
                 ('thin (12B + 14B frames)', '~270 B', '~107 B', '~2.5×'),
                 ('fat read reply (246B frame)', '~540 B', '~285 B', '~1.9×')),
                ('b', 'the auth handshakes do not ride MBAP — the suite auth\'s '
                      'PVA1 proof is a raw 52-byte frame (magic + nonce + '
                      'HMAC-SHA256), the Waveshare password raw ASCII, the '
                      'verdicts raw `OK`/`ERR`. The tap peels and names them '
                      'before the first clean frame — the conversations render '
                      'the handshake whole (`PVA1 handshake proof`, `Waveshare '
                      'password`, `auth verdict`) and the device\'s first real '
                      'frame survives the verdict glue — and the bytes ride '
                      'the trace verbatim as raw records either way: one more '
                      'reason the trace is 0600 (a leaked trace can replay a '
                      'PVA1 proof at any server holding the key).'),
                ('b', 'a worked example ships with the suite — '
                      '`extras/examples/modbus-replay-trace.pvmb` (two '
                      'sessions, both handshakes, the polls, the refused '
                      'write, deterministic bytes; rendered by '
                      '`modbus-replay-dump '
                      'extras/examples/modbus-replay-trace.pvmb`).'),
            ]),
            ('Replay mode', [
                ('b', 'at start the daemon indexes every recorded response '
                      'under its request\'s identity — unit + function code + '
                      'PDU bytes, transaction ids aside (the replay speaks the '
                      'client\'s own ids) — and answers each incoming request '
                      'with the most recent recorded response, exception '
                      'frames included: the device\'s truth, verbatim.'),
                ('b', '`--replay-speed` replays the recorded device latencies '
                      '(the recorded `rsp.ts − req.ts` gap: `1` = as captured, '
                      '`N` = N times faster, `0` = immediately).'),
                ('b', 'a request the trace never recorded answers per '
                      '`--replay-miss`: **`exception`** (the default — Modbus '
                      'exception 11, gateway target device failed to respond: '
                      'a miss is loud in the client\'s error counters) or '
                      '**`zero`** (a zero-filled reply of the right shape — '
                      'reads answer zero data, writes answer their echoes, so '
                      'a changed poll plan keeps running and shows its shape). '
                      'Either way the miss logs, with the request spelled out '
                      '— that log is the poll-planning debug.'),
                ('b', 'replay is a record, not a device: nothing accumulates. '
                      'A write answers its recorded response and a following '
                      'read still reads what the hardware read at capture time '
                      '— the write-through behavior you are debugging sees '
                      'the recorded world, which is the point (compare the '
                      'client\'s behavior against the trace\'s truth, not '
                      'against a simulation of it).'),
            ]),
            ('The record feed and the dump tool', [
                ('b', 'every record the trace writer encodes also fans out to '
                      'the **record feed** — `--dump-socket` binds a unix '
                      'stream socket at the family\'s derived path '
                      '(`/tmp/modbus-replay-<listen-port>.socket`, bound by '
                      'default, the word `none` turns it off). The feed is '
                      'read-only push in the binary record encoding verbatim — '
                      'no verbs, no tokens, nothing a command could ride (the '
                      'no-control-plane ruling stands); a slow subscriber is '
                      'dropped, the FILE keeps every record. Capture mode '
                      'pushes the real wire\'s records; **replay mode pushes '
                      'the session it serves** — the requests, the recorded '
                      'answers with the applied latencies, the misses as the '
                      'frames they are.'),
                ('b', 'the reader face is its own bin, '
                      '`bin/modbus-replay-dump.py` (its own man page): the '
                      'three static views of a trace file (the summary, the '
                      'answer index — per unique query, the recorded reply the '
                      'replay will serve with the recorded latency and the ask '
                      'count — and the conversations, the per-connection '
                      'query→answer diagram — one block per connection naming '
                      'both ends of the pipe, every packet line carrying its '
                      'source host:port and its `#conn:txn` pairing key (the '
                      'record\'s own `peer`, the MBAP transaction id — a '
                      'device echoing a foreign id shows right there)), the '
                      'converter (`--to json|binary -o OUT` — either shape '
                      'reads, the other writes, the raw bytes the one truth: '
                      'a binary→json→binary round trip lands byte-identical) '
                      'and the live view (`--socket` — the feed renders '
                      'realtime, every packet line naming its source host:port '
                      'and its `#conn:txn` key; a request prints `pending`, '
                      'its response completes the exchange; `^C` ends it '
                      'clean).'),
                ('b', 'the value dumps ride only with `--values` (off by '
                      'default on the live view, the file views always dump '
                      'them); the dumps cap at 16 words a block — a poller\'s '
                      'repeats keep the conversations readable; '
                      '`--values-cap N|all` reshapes the cap (`all` the full '
                      'block) wherever the values render, and the answer index '
                      'dumps the whole block always.'),
                ('b', 'the live view also records: `--record FILE` saves the '
                      'feed to a trace file while it renders — the received '
                      'PVMB blocks land verbatim (0600, flushed and appended '
                      'across recorder sessions, the feed\'s per-connect '
                      'header the session boundary), a record in the file is '
                      'byte-identical to the one the daemon\'s own `--capture` '
                      'writes, and any reader takes the file for captured '
                      '(the views, the converter, `--replay`) — '
                      '`--trace-max-mb`/`--trace-files` rotate it the '
                      'capture\'s way (the recorder re-stamps a header of its '
                      'own on the shift). `--quiet` drops the per-record '
                      'render — the recorder runs silent, the banners and the '
                      'save tally stay.'),
                ('b', 'the feed is the family\'s one record contract: the '
                      'cache\'s `trace-socket` subscribes the same way, so '
                      'the cache\'s live wire records to a file with '
                      '`--socket /tmp/modbus-cache-<listen-port>-trace.socket '
                      '--record …`.'),
            ]),
            ('Signals', [
                ('t', ('signal', 'effect'),
                 ('`SIGHUP`', 'logged and ignored — there is no live layer to '
                  're-apply; restart to change the posture'),
                 ('`SIGTERM` / `SIGINT`', 'graceful shutdown with a session '
                  'summary (connections piped, frames both ways, bytes, '
                  'undecoded flushes — or sessions served, answered, '
                  'misses)'),
                 ('`SIGUSR2`', 'dumps the thread stacks (the family\'s '
                  'faulthandler hook)')),
            ]),
            ('Testing', [
                ('b', 'the suite is `dev/suites/replay-regtest.py` — capture '
                      'against the fake inverter, both trace shapes, the '
                      'walk\'s torn-tail/resync story, the dump bin\'s views '
                      'and converter, the record feed, the byte-identical '
                      'replay, the miss policies, the refusals. Every scenario '
                      'must end with the daemon alive and **zero tracebacks** '
                      'in the logs.'),
                ('c', 'dev/battery/battery.py replay    # the replay profile: the regtest (the suites refuse\n'
                      '                            #   without the runner\'s PV_RUN_DIR)'),
                ('fam', 'runner'),
            ]),
            ('Deployment', [
                ('b', 'none by design — the sidecar is a checkout tool: run '
                  'it from a checkout (`apps/modbus-replay/dev` is the '
                  'launcher) or a plain `python3` line, next to the tools '
                  'it debugs. No container image, no Nix package, no '
                  'NixOS module, no service unit — a deployment would '
                  'defeat the sidecar (it debugs deployments, it is not '
                  'one).'),
            ]),
            ('Troubleshooting', [
                ('b', '**it will not start** — the bind failures and the '
                      'flag refusals answer one clean line + exit 1 '
                      '(capture and replay are mutually exclusive, a knob '
                      'without its file refuses); `--help` and the man page '
                      'carry the startup surface.'),
                ('b', '**the trace looks torn** — a killed capture leaves a '
                      'readable file: the walk keeps what parsed and notes '
                      'the loss (the section above); a mid-file CRC failure '
                      'resyncs at the next run header — the records between '
                      'the tear and the re-anchor are lost with the tear.'),
                ('b', '**replay answers exception 11** — a request the trace '
                      'never recorded (the miss): the log spells the request '
                      '— that is the poll-planning debug; `--replay-miss '
                      'zero` keeps a changed poll plan running instead.'),
                ('b', '**the dump shows nothing on the live view** — the feed '
                      'socket path is the derived '
                      '`/tmp/modbus-replay-<listen-port>.socket` (the cache\'s '
                      'feed spells its own); a slow subscriber is dropped by '
                      'design, the file keeps every record.'),
                ('b', '**deeper** — `--log-level DEBUG` logs the framing '
                      'decisions; `SIGUSR2` dumps the thread stacks.'),
            ]),
            ('The docs map', [
                ('fam', 'docs'),
            ]),
            ('Configuration', [
                ('b', 'there is no config file — the sidecar\'s posture is '
                      'fixed at start: **flag > env (the bare upper-snake '
                      'twins) > the built-in defaults**, the knobs table '
                      'below IS the flags table. A wrapper script (or the '
                      '`apps/modbus-replay/dev` launcher) is where a standing '
                      'posture lives.'),
            ]),
            ('Access control', [
                ('b', 'nothing to gate, by design: the Modbus port forwards '
                      'bytes between client and device, and the record feed '
                      'is a read-only binary push — no verbs, no tokens, '
                      'nothing a command could ride (the no-control-plane '
                      'ruling). The trace file is created `0600` and belongs '
                      'with the secrets — a Waveshare capture carries the '
                      'connection password raw, and a leaked trace can '
                      'replay a PVA1 proof at any server holding the key.'),
            ]),
            ('Metrics', [
                ('b', 'none — the sidecar publishes no `/metrics`; the dump '
                      'tool is the observability face (the summary, the '
                      'answer index, the conversations, the live view).'),
            ]),
            ('Audit logging', [
                ('b', 'no audit file, no hash chain — the sidecar takes no '
                      'commands, so there is nothing to repudiate: the trace '
                      'IS the record (every frame verbatim, `0600`), and the '
                      'lifecycle rides the log (the startup posture line, '
                      'the shutdown\'s session summary, `SIGUSR2`\'s thread '
                      'stacks).'),
            ]),
            ('Register maps', [
                ('b', 'register-agnostic — no profile, no types, no gains: '
                      'the replay serves recorded bytes by request identity '
                      '(unit + function code + PDU), the raw frames are the '
                      'one truth. The dump tool decodes for reading only.'),
            ]),
            ('Source layout', [
                ('p', 'the sidecar is flat and stdlib-only — two bins, one '
                      'lib package, the generated man pages beside; the '
                      'checkout launcher (`dev`) runs it straight from the '
                      'tree. No container image, no Nix package, no NixOS '
                      'module — a deployment would defeat the sidecar (it '
                      'debugs deployments, it is not one).'),
                ('c', 'apps/modbus-replay/\n'
                      '├── bin/\n'
                      '│   ├── modbus-replay.py          # the daemon: capture, pass-through, replay — the\n'
                      '│   │                            #   CLI, the tap wiring, the signal handling\n'
                      '│   └── modbus-replay-dump.py     # the reader face: the views, the converter, the\n'
                      '│                                #   live view, the recorder\n'
                      '├── lib/\n'
                      '│   ├── capture.py                # the capture face: the pipe + the shadow copy\n'
                      '│   ├── replay.py                 # the replay face: the answer index, the miss\n'
                      '│   │                            #   policies, the recorded latencies\n'
                      '│   ├── trace.py                  # the trace face: the FrameTap (the MBAP\n'
                      '│   │                            #   reassembler), the PVMB writer, the walk\n'
                      '│   ├── statics.py                # the trace format\'s identity, the miss codes\n'
                      '│   │                            #   (lib/defaults.json)\n'
                      '│   ├── options.py + options.json # the registry: the one row per knob\n'
                      '│   ├── config.py                 # the env layer + the flags (no config file)\n'
                      '│   └── man.py                    # the generated man pages\n'
                      '├── man/                          # the generated man pages (the daemon + the dump)\n'
                      '└── dev                           # the checkout launcher'),
                ('p', 'the family\'s `common/` package (the trace writer, the '
                      'record encoding) is imported by path from the '
                      'checkout — the sidecar shares no service packaging '
                      'with the tools it debugs.'),
            ]),
            ('The docs map', [
                ('t', ('this tool\'s documents', 'what they carry'),
                 ('`apps/modbus-replay/README.md`', 'the front page — the description, '
                  'the quick how-to, Security, License'),
                 ('`apps/modbus-replay/lib/options.json`', 'the registry — the one row '
                  'per knob (the knobs table renders from it)'),
                 ('`apps/modbus-replay/man/`', 'the generated man pages '
                  '(`modbus-replay --man`, `modbus-replay-dump --man`)'),
                 ('`extras/examples/modbus-replay-trace.pvmb`', 'the worked '
                  'example trace — two sessions, both handshakes, the '
                  'refused write (rendered by the dump tool)')),
                ('fam', 'docs'),
            ]),
            ('Runtime control', [
                ('b', 'none — the no-control-plane ruling: no control server, '
                      'no cli, no set/show/clear, nothing to reload. The '
                      'posture is fixed at start; a change is a restart with '
                      'different flags (`SIGHUP` is logged and ignored). The '
                      'observability face is `modbus-replay-dump` — the views, '
                      'the live feed, the recorder.'),
            ]),
        ],
    },
}

WIDTH = 76

# the shipped shape, on every page: the composition map the front-page
# split took off the READMEs (the docker topologies' plain rendering) —
# the per-tool 'family' lead rides first, the map follows
FAMILY_MAP = [
    ('c', 'the device (the sun2000 — or the fake standing in)\n'
          '     |  Modbus TCP :502\n'
          '     v\n'
          'modbus-cache :15502 ---- the one client slot, multiplexed\n'
          '     |\n'
          '     v\n'
          'modbus-scraper :9350 /metrics\n'
          '     |\n'
          '     v\n'
          'prometheus ---- the alert pack (extras/alerts/)\n'
          '     |\n'
          '     v\n'
          'the dashboard :8080\n'
          '\n'
          'modbus-replay rides beside any Modbus hop: the tap in capture,\n'
          'the recorded device in replay, the dump tool rendering.'),
    ('b', 'every hop is optional: the scraper can poll the device straight '
          '(no cache), the dashboard can read a collector you already run, '
          'the fake can stand in for the device — and the suite auth can '
          'run on either Modbus hop independently (the peers must speak '
          'the same scheme with the same key).'),
]

# the audit-forward story, told once (the cache's wording, genericized —
# the per-tool tails splice it; the F10 answer)
FAMILY_AUDIT_FORWARD = [
    ('b', '`--audit-forward` mirrors every line — the hash chain included — '
          'onward: `syslog` (the local socket auto-scan), `syslog:/path` '
          '(an explicit socket), `udp://host[:514]` (RFC5426, best-effort) '
          'or `tcp://host[:514]` (RFC6587 octet-count framing) — the '
          '**off-box copy**: an edited local trail breaks its chain, and a '
          'scheduled search at the collector can chain-verify the extracted '
          'prefix/chain fields and alert on a break; a line that left the '
          'box before an attacker arrived cannot be touched from it.'),
    ('b', 'the remote envelope rides `--audit-forward-format` (`rfc5424`, '
          'the default, or `cef` — the local syslog forms keep the verbatim '
          'send). A send failure notes once on stderr and the next event '
          're-arms (the note carries the dropped count).'),
    ('b', '`--audit-log none` turns the local file off: with a forward '
          'spelled that is the **remote-only mode** (the collector is the '
          'sole holder — no file, no XDG directory, the chain reseeds at '
          'GENESIS per run), without one the audit is disabled (the state '
          '`--no-audit-log` spells).'),
    ('b', 'the line names its writer — the daemon the `tag=daemon` role, '
          'the ctl and cli clients the shared `tag=cli` role — and carries '
          'an `instance=<id>` word: the **control port** when '
          '`--audit-instance` is unset (unique per host by construction), '
          'the override when spelled. Keep an override unique among '
          'everything that shares one collector; the chain groups by the '
          '(application, writer, instance) triple.'),
    ('b', 'the 12-hex token after the event name is the entry\'s **chained '
          'hash** (the audit\'s F10): any edit, deletion or reordering '
          'shows up as a chain break in `dev/gates/audit_verify.py` (run '
          'it on a trail file, the family\'s XDG trails, or a journald '
          'dump on stdin). **Every wire command is audited once, by the '
          'server** (with the client peer, the role, and the frame\'s mac '
          'when the wire is signed).'),
]

# the suites' runner rule, told once (the per-tool Testing sections splice it)
FAMILY_RUNNER = [
    ('b', 'the suites **always run through the battery runner** '
          '(`dev/battery/battery.py`) — it owns the run dir, the port '
          'slots and the tally, and a standalone suite run refuses (a '
          'hand-run collides across sessions). A new behavior ships with '
          'a check: a scenario that fails without it and names the '
          'registry rows it pins.'),
]

# the suite's document map, told once — the F-numbers the pages cite live
# in the security postures, the ACL grammar in its spec, the module
# options in the NixOS map
FAMILY_DOCS = [
    ('t', ('document', 'what it carries'),
     ('`docs/SECURITY.md`', 'the security posture and the F-findings the '
      'pages cite (F9 the secrets, F10 the audit chain, F11 the '
      'trusted-LAN test tool, F12 the secret files, F13 the token '
      'floors, F16 the alert pack, F18 the dump split, F21 the web '
      'face)'),
     ('`docs/specs/ACL.md`', 'the ACL gate semantics — the rule chains, '
      'the ip-prefix grammar, the standalone acl files, the tools, and '
      'where each tool\'s support stops'),
     ('`docs/specs/MODBUS.md`', 'the Modbus wire specs — the function-code '
      'support maps, the suite and Waveshare auth handshakes, the '
      'diagnostics block'),
     ('`docs/DESIGN.md`', 'the design — the architecture, the decisions, '
      'the postures the tools share'),
     ('`nixos/README.md`', 'the NixOS side — the option maps rebuilt from '
      '`module.nix`, the flake, the packages'),
     ('`docker/README.md`', 'the container side — the images, the compose '
      'topologies (the demo and the prod split), the env examples'),
     ('`shared/profiles/README.md`', 'the device profile format — the '
      'schema, the semantics, the shipped devices'),
     ('`extras/alerts/`', 'the alert rules pack — one rule file per '
      'watched exporter, every alert naming the audit events it '
      'correlates with'),
     ('`docs/book/`', 'the assembled book (these manuals gathered, the '
      'specs beside)'),
     ('`docs/history/`', 'the wave records — how the suite got here, '
      '`front-page-split.md` among them'),
     ('`docs/TODO.md`', 'the open items'),
      ('`CHANGELOG.md`', 'the unreleased changes and the current release')),
]

FAMILY_SPLICES = {
    'audit_forward': FAMILY_AUDIT_FORWARD,
    'runner': FAMILY_RUNNER,
    'docs': FAMILY_DOCS,
}

# the reference sections' canonical ladder — every page walks it in this
# order (the tool's own extras slot between by their keys; an unknown
# title rides at the tail in its authored order). The one-ladder rule:
# the same topics in the same order on every page, present or honestly
# absent.
SECTION_ORDER = {
    'Signals': 0,
    'Configuration': 10,
    'Page configuration (config.js)': 12,
    'Runtime control': 15,
    'Access control': 20,
    'Behind a reverse proxy': 25,
    'Metrics': 30,
    'Alerting': 35,
    'Battery': 40,
    'Audit logging': 50,
    'Register maps': 60,
    'Register maps (the profile)': 61,
    'Served registers (the default profile)': 62,
    'Register maps (the register defaults)': 63,
    'Register maps and the metrics spec': 64,
    'Diagnostics registers': 65,
    'Persistence': 70,
    'Tuning': 45,
    'Trace feed': 80,
    'The trace format': 85,
    'Replay mode': 86,
    'The record feed and the dump tool': 87,
    'Deployment': 88,
    'Chaos injection (`--chaos`)': 90,
    'The docs map': 92,
    'Source layout': 95,
    'Troubleshooting': 97,
    'Testing': 100,
}


def load(tool_dir):
    """The tool's wired rows (the import dance in lib/registry) plus the raw
    registry (the commands/show sections' row order and flags — the loader
    keys them by live word and drops the node rows, the page wants both)."""
    opts, _verbs, shows, _mod = wired(tool_dir)
    meta = raw_registry(tool_dir)
    # the commands table reads the raw rows' marks (internal/hidden/live) —
    # the show/commands sections' canon refs resolve here too (the fold is
    # the loader's own, the row's inline field wins)
    for section in ('show', 'commands'):
        meta[section] = fold_rows(tool_dir, section, meta)
    return tuple(opts), tuple(shows), meta


def wrap(text):
    """Greedy wrap at WIDTH — the prose paragraphs; the tables never wrap
    (one row per line). A break never lands inside a code span: the backtick
    parity must be even at the break (a span straddling the wrap would read
    as a raw `<` on the continuation line — the guard's class of defect)."""
    words, lines, line = text.split(), [], ''
    parity, legal = 0, set()
    for i, w in enumerate(words):
        parity += w.count('`')
        if parity % 2 == 0:
            legal.add(i)          # a break after word i keeps the spans whole
    for i, w in enumerate(words):
        if line and len(line) + 1 + len(w) > WIDTH and (i - 1) in legal:
            lines.append(line)
            line = w
        else:
            line = (line + ' ' + w) if line else w
    if line:
        lines.append(line)
    return '\n'.join(lines)


def bullet(text):
    """A wrapped list item: `- ` on the first line, the continuation lines
    at the two-space content indent cmark gives a `- ` bullet."""
    lines = wrap(text).split('\n')
    return '- ' + lines[0] + ('' if len(lines) == 1 else
                              '\n' + '\n'.join('  ' + l for l in lines[1:]))


def esc(text):
    """One table cell: a bare `<` outside a code span would parse as HTML
    and swallow the word (`<file>`) — backslash-escape it (no code-span
    imbalance: the registry text stays verbatim); the pipes escaped last
    (GFM's rule — a `|` ends the cell even inside backticks)."""
    import re
    parts = text.split('`')
    for i, part in enumerate(parts):
        if i % 2 == 0:
            parts[i] = part.replace('<', '\\<')
    return '`'.join(parts).replace('|', '\\|')


def shape(opt):
    """The value-shape cell: the row's hint, else its completable words,
    else the conv's plain shape."""
    if opt.hint:
        return opt.hint
    if opt.values:
        return '|'.join(opt.values)
    return {'bool': 'on|off', 'int': 'N', 'float': 'N'}.get(opt.conv, 'TEXT')


def knob_kind(opt):
    """The kind cell of a knob row: settable (the restart and the secret
    markers) or startup-only (the secret dump-key refuses outright — its
    set/clear/show all answer the restart error)."""
    if not opt.live:
        kind = 'startup-only'
        if opt.secret:
            kind += ' (secret)'
        return kind
    if opt.restart:
        kind = 'settable (restart)'
        if opt.secret:
            kind = 'startup-only (secret)'
        return kind
    kind = 'settable'
    if opt.secret:
        kind += ' (secret)'
    return kind


def fmt_default(opt):
    """The default cell: the registry row's built-in default (the
    resolver's last rung) — the secrets carry none by rule (the row's
    default is None, categorically)."""
    d = opt.static_default
    if d is None or opt.secret:
        return '—'
    if d is True:
        return 'on'
    if d is False:
        return 'off'
    text = str(d)
    return text if text.strip() else '—'


def knob_row(opt):
    """One knob table row: the registry key, the console spelling a running
    daemon takes (the live path as words — the config files and the dumps
    speak it; the flat registry name answers the same set/clear/show words
    on the wire and the clients translate), the kind, the built-in
    default, the value shape, the flag / env twins and the description
    (the setting-help — the wire's own wording)."""
    set_cell = '—'
    kind = knob_kind(opt)
    if opt.live and not kind.startswith('startup-only'):
        set_cell = '`set %s`' % ' '.join(opt.live.split('/'))
        if opt.alias:
            set_cell += ' (the console also takes `set %s`)' % ' '.join(opt.alias.split('/'))
    flag = '`%s`' % opt.flag if opt.flag else '—'
    envs = '/'.join('`%s`' % e for e in opt.env_names() if e) or '—'
    desc = opt.setting_help or opt.help
    marks = ''
    if opt.hidden:
        marks = ' *(hidden)*'
    return '| `%s` | %s | %s | %s | `%s` | %s / %s | %s%s |' % (
        esc(opt.name), esc(set_cell), esc(kind), esc(fmt_default(opt)),
        esc(shape(opt)), flag, envs, esc(desc), marks)


def knobs_section(rows):
    """The knobs tables: the flat knobs first (no namespace — the general
    bucket), then one table per namespace node in registry first-appearance
    order, the rows in registry order (the file order every surface
    renders). A knob belongs to the longest node naming its live path's
    prefix; a startup-only knob (no live path) always rides the general
    bucket."""
    nodes = [o for o in rows if o.node]
    buckets = {'': []}
    for o in rows:
        if o.node:
            continue
        best = ''
        for n in nodes:
            if o.live and (o.live == n.name or o.live.startswith(n.name + '/')) \
                    and len(n.name) > len(best):
                best = n.name
        buckets.setdefault(best, []).append(o)
    out = ['## Knobs', '',
           wrap('The tables spell the knob\'s registry key — the one internal '
                'name the wire, the replies and the dispatch take; the set / '
                'clear column spells the console words (the live path as '
                'words — the config files and the state dumps speak them; '
                'the flat registry name answers the same set everywhere, '
                'the clients translate). The `default` column is the '
                'registry\'s built-in default (the resolver\'s last rung '
                'after flag > env > config); the namespaces group '
                'them.'), '']
    order = [''] + [n.name for n in nodes if n.name in buckets]
    by_name = {n.name: n for n in nodes}
    for i, key in enumerate(order):
        if not buckets.get(key):
            continue
        if i:
            out.append('')
        if key:
            node = by_name[key]
            out.append('### %s' % key)
            out.append('')
            out.append(wrap(node.setting_help or node.help or ''))
            out.append('')
        else:
            out.append('### general')
            out.append('')
        out.append('| knob | set / clear | kind | default | value | '
                   'flag / env | description |')
        out.append('|---|---|---|---|---|---|---|')
        out.extend(knob_row(o) for o in buckets[key])
    return out


def commands_section(meta, tool):
    """The commands table: the registry's rows in file order (the nodes
    render as namespace rows at their position), the fake's rowless write
    emulation appended. Rows spelling the same wire words merge into one
    (the cache's `request dump`: the namespace node and the hidden leaf
    command) — the kinds joined, the namespace's fuller description kept.
    Empty (no rows, no extras) renders nothing — the replay's page."""
    rows = []
    for r in meta.get('commands') or []:
        wire = (r.get('live') or r['name']).replace('/', ' ')
        node = (r.get('node') == True or r.get('node') == 'on')
        internal = (r.get('internal') == True or r.get('internal') == 'on')
        hidden = (r.get('hidden') == True or r.get('hidden') == 'on')
        rows.append((wire, node, internal, hidden, r.get('help', '')))
    merged = []
    for wire, node, internal, hidden, help in rows:
        for i, (m_wire, m_node, m_int, m_hid, m_help) in enumerate(merged):
            if m_wire == wire:
                marks = [m for m, on in (('internal', m_int or internal),
                                         ('hidden', m_hid or hidden)) if on]
                kind = ('namespace' if m_node or node else 'command')
                if m_node and not node:
                    kind = 'namespace + command'
                if marks:
                    kind += ' (%s)' % ', '.join(marks)
                merged[i] = (m_wire, m_node or node, m_int or internal,
                             m_hid or hidden,
                             m_help if (m_node or not node) else help)
                break
        else:
            merged.append((wire, node, internal, hidden, help))
    extras = EXTRA_COMMANDS.get(tool, ())
    if not merged and not extras:
        return []
    out = ['## Commands', '',
           '| command | kind | description |', '|---|---|---|']
    for wire, node, internal, hidden, help in merged:
        marks = [m for m, on in (('internal', internal), ('hidden', hidden)) if on]
        kind = 'namespace' if node else 'command'
        if marks:
            kind += ' (%s)' % ', '.join(marks)
        out.append('| `%s` | %s | %s |' % (esc(wire), esc(kind), esc(help)))
    for wire, desc in extras:
        out.append('| `%s` | command | %s |' % (esc(wire), esc(desc)))
    return out


def show_section(shows):
    """The show reports table: the registry's `show` rows — the flat
    wire word (the live path is the console spelling, the cli translates
    it). Empty renders nothing."""
    if not shows:
        return []
    out = ['## Show reports', '',
           '| report | kind | description |', '|---|---|---|']
    for o in shows:
        wire = o.name
        kind = 'show-only' + (' (hidden)' if o.hidden else '')
        out.append('| `show %s` | %s | %s |' % (esc(wire), esc(kind), esc(o.setting_help or o.help)))
    return out


def render_items(out, items):
    """The REF items: ('b', text) a bullet, ('p', text) a wrapped
    paragraph, ('c', block) an indented code block, ('t', head, ...) a
    table (the first tuple the headers, the rest the rows), ('fam', key)
    a family-wide splice (FAMILY_SPLICES — the story told once, rendered
    in place)."""
    for item in items:
        kind = item[0]
        if kind == 'fam':
            render_items(out, FAMILY_SPLICES[item[1]])
            continue
        if kind == 'b':
            out.append(bullet(item[1]))
        elif kind == 'p':
            out.append(wrap(item[1]))
        elif kind == 'c':
            for line in item[1].splitlines():
                out.append(('    ' + line) if line.strip() else '')
        elif kind == 't':
            heads = item[1]
            out.append('| ' + ' | '.join(esc(h) for h in heads) + ' |')
            out.append('|' + '---|' * len(heads))
            for row in item[2:]:
                out.append('| ' + ' | '.join(esc(c) for c in row) + ' |')
        else:
            raise SystemExit('unknown REF item kind %r' % (kind,))
        out.append('')


def tidy(lines):
    """Collapse repeated blank lines, strip the leading/trailing blanks —
    the render appends loose blanks; the page carries exactly one between
    blocks."""
    out = []
    for line in lines:
        if line == '' and (not out or out[-1] == ''):
            continue
        out.append(line)
    while out and out[-1] == '':
        out.pop()
    return out


def speaking_section(cli, sock, port, example, token_mandatory, conf,
                     ops_default):
    """The `The control plane` section: the control target, the one
    client's three modes, the token rules, the ops role and the config
    ladder — bullets (the front-page split's no-big-paragraphs ruling)."""
    out = ['## The control plane', '']
    out.append(bullet('the cli ships beside the daemon (`bin/%s.py`, its own '
                      'man page via `--man`) — the same client the suites '
                      'drive; every word below is its spelling.' % cli))
    out.append('')
    out.append(bullet('it is one script for the family: the installed client '
                      'names are **symlinks to `apps/pvsuite-cli.py`** and '
                      'the tool comes from the name it was invoked as; a '
                      'bare `pvsuite-cli` takes the tool as the first word '
                      '(the daemon name or the short alias — `cache`, '
                      '`scraper`, `inverter`; `dashboard` is its own alias), '
                      'and a word that disagrees with the invocation name is '
                      'refused.'))
    out.append('')
    out.append(bullet('the control server is a JSON-lines listener: a unix '
                      'socket (the default `%s`) or a TCP port on 127.0.0.1 — '
                      'the `--control-port` flag, env `CTL`, `0` = off.' % sock))
    out.append('')
    out.append('    python3 bin/%s.py --control-port %s %s' % (cli, port, example))
    out.append('    python3 bin/%s.py' % cli)
    out.append('')
    out.append(bullet('the one-shot spelling runs one command per invocation '
                      '(or a batch on stdin).'))
    out.append('')
    out.append(bullet('the wire is **JSON lines**: one request per line, one '
                      'reply per line — the reply\'s `status` face speaks '
                      '`ok` / `fail` / `bye` (the closing) with a `note` '
                      'where the row says one; the `auth` verb carries the '
                      'token, and a signed wire authenticates each frame '
                      'with an HMAC mac (the audit lines carry it beside '
                      'the command).'))
    out.append('')
    out.append(bullet('the **console** is the interactive session: `?` lists '
                      'the words, TAB completes, `help <setting>` describes '
                      'one, `help config` maps every knob to its control '
                      'command, `show knobs` prints the dictionary.'))
    out.append('')
    if token_mandatory:
        out.append(bullet('TCP control demands the token (`--control-token` / '
                          'env `CONTROL_TOKEN`; the wire\'s `auth` verb '
                          'carries it) and refuses to start without one; over '
                          'the unix socket a trusted peer (root, the daemon\'s '
                          'own user or `--control-trust-uids` — SO_PEERCRED) '
                          'speaks without it.'))
    else:
        out.append(bullet('the fake keeps its trusted-LAN posture (F11): '
                          'control works over TCP without a token too; over '
                          'the unix socket a trusted peer (root, the daemon\'s '
                          'own user or `--control-trust-uids` — SO_PEERCRED) '
                          'always speaks without one.'))
    out.append('')
    out.append(bullet('the optional ops token (`--control-ops-token`) scopes '
                      'a session to the read-only verbs (the default: %s). '
                      'Every command is audited. The clients take '
                      '`--control-port` (env `CTL`), `--timeout`, '
                      '`--control-token`, the audit flags and `--man`; the '
                      'cli adds `--reconnect` / `--reconnect-wait`.'
                      % ops_default))
    out.append('')
    if conf:
        out.append(bullet("a knob's value resolves at start as flag > env > "
                          'config script > default; the config file (the '
                          'bundled `%s`) speaks the same grammar — '
                          '`set <name> <value>` lines, `--dry-run` prints the '
                          'effective settings.' % conf))
    out.append('')
    out.append(wrap('The kinds — every row of the tables below carries one:'))
    out.append('')
    out.append('| kind | meaning |')
    out.append('|---|---|')
    out.append('| command | a one-shot action, no value |')
    out.append('| namespace | a word that groups deeper words: the console '
               'walk lists its children, `help <namespace>` describes them |')
    out.append('| settable | the knob is live: `set <name> <value>` applies '
               'at once (the flat registry name; the console also completes '
               "the row's live/alias path spellings and translates), "
               '`clear <name>` returns the configured value, `show <name>` '
               'prints the live value. *(restart)* — the set records a '
               'pending value and `request reload` applies it. *(secret)* — '
               'the value never renders back (show answers err); pass it by '
               'flag/env or as `file:<path>`. *(hidden)* — never lists in '
               'the ?/TAB pools; the wire still answers |')
    out.append('| startup-only | flag/env/config at start, a restart applies '
               'a change; the wire has no set/clear/show for it (it renders '
               'in `show config` only). Every secret is startup-only now '
               '(the tokens, the auth keys, the dump key): the wire refuses '
               'set/clear outright, the value passes by flag/env/config or '
               'as `file:<path>` and a restart applies it |')
    out.append('| show-only | a runtime report: `show <report>` answers, '
               'nothing to set |')
    out.append('')
    return out


def render(tool, daemon, daemon_bin, blurb, cli, sock, port, example,
           token_mandatory, conf, rows, shows, meta):
    """The page: the intro (the blurb), then Run it, How it works, The
    control plane, the registry tables — commands, knobs, show reports —
    then the reference sections: the canonical ladder (Configuration,
    Access control, Metrics, Audit logging, Register maps, Source layout,
    Testing) with the tool's own extras riding beside, bullets and
    tables — the one-ladder rule enforced here, in the render, not per
    hand."""
    out = []
    w = out.append
    w('# The %s manual' % daemon)
    w('')
    w(wrap('%s Part of the pv-suite family.' % blurb))
    w('')
    ref = REF[tool]
    if 'family' in ref:
        w('## The family')
        w('')
        render_items(out, list(ref['family']) + FAMILY_MAP)
    w('## Run it')
    w('')
    render_items(out, ref['run'])
    w('## How it works')
    w('')
    render_items(out, ref['how'])
    if cli:
        from common.settings.options import default_ops_verbs, known_verbs
        ops_default = default_ops_verbs(known_verbs(tuple(
            r['name'] for r in meta.get('commands') or [])))
        out.extend(speaking_section(cli, sock, port, example,
                                    token_mandatory, conf, ops_default))
    out.extend(commands_section(meta, tool))
    out.extend(knobs_section(rows))
    out.extend(show_section(shows))
    tail = sorted(ref['tail'], key=lambda t: SECTION_ORDER.get(t[0], 500))
    for title, items in tail:
        w('## %s' % title)
        w('')
        render_items(out, items)
    w(wrap('The ?/TAB pools, `show knobs` and `help config` all render from '
           'the same rows this page was generated from.'))
    w('')
    return '\n'.join(tidy(out)) + '\n'


def raw_angle_guard(text, path):
    """The cmark guard: a `<` outside a code span parses as HTML and
    vanishes (`<file>`). Fail loud — esc() escapes the table cells and the
    REF bullets keep theirs inside code spans, so a hit means a shape the
    escaper missed. Indented (four-space) lines are code blocks — cmark
    parses no HTML there, the guard skips them."""
    import re
    for no, line in enumerate(text.splitlines(), 1):
        if line.startswith('    '):
            continue
        for i, part in enumerate(line.split('`')):
            if i % 2 == 0 and re.search(r'(?<!\\)<', part):
                raise SystemExit('%s:%d: a raw < outside a code span: %r' % (path, no, part.strip()))


def main(argv):
    check = '--check' in argv
    drift = False
    for tool, daemon, daemon_bin, blurb, cli, sock, port, example, token_mandatory, conf in TOOLS:
        rows, shows, meta = load(tool)
        page = render(tool, daemon, daemon_bin, blurb, cli, sock, port,
                      example, token_mandatory, conf, rows, shows, meta)
        raw_angle_guard(page, daemon)
        path = os.path.join(REPO, 'extras', 'manuals', daemon + '.md')
        drift = emit(path, page, check, 'manual',
                     rerun='python3 dev/generators/manual.py') or drift
    if check:
        if drift:
            return 1
        print('manual pages up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))


