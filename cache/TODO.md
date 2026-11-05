# TODO

## Open

- **the audit-finding fixes** — the cache owns the audit's prompt pair and
  most of the cheap gaps: F2 the audit-trail injection (fold the control
  characters — the writer is now the shared `common/audit.py`, the two
  control servers fold their COMMAND echoes), F3 the write allow-list
  failing open on unparseable frames (fail closed), F4 the uncapped
  pre-auth control buffer, F5 the token-less TCP control (refuse or warn),
  F6 the metrics endpoint (token mandatory when enabled + a handler
  timeout), F8 the socket mode (`chmod 0600` after bind). See
  [AUDIT.md](../docs/AUDIT.md); each closes in a few lines, then re-run the
  audit.
- **the CI** — GitHub Actions: the four suites + `nix flake check` on the
  push; the release workflow on the tag. (Family-wide, see the root
  [TODO](../docs/TODO.md).)
- **the hardware verification** — everything so far is verified against the
  fake inverter, fuzzing and stress only; a real SUN2000/SDongle session
  (poll pacing, the dongle's single-client behaviour, real exception codes,
  the FC4 input registers on a real device) is the last mile. Also worth
  testing: the Deye profiles against the cache.
- **the cache persistence** — an optional state file (write-behind) so a
  daemon restart serves last-known values instead of cold misses: the
  device-down story survives the restart, not just the reconnect.
- **the scraper's FC4 awareness** — the profile schema now carries the `fc`
  field (the cache polls/caches FC4 independently); the scraper still reads
  everything with FC3 — a profile that marks an FC4 entry `scrape` needs
  the scraper to follow the field. Related gap: no shipped profile
  exercises `fc: 4` yet (the linter and the cache are ready, the data
  isn't).
- **the read-only control role** — a second token granting only the
  show/clear verbs (no `set`, no `shutdown`): the ops shift versus the
  admin key, both audited.
- **the peer-cred auth on the unix control socket** — SO_PEERCRED: a local
  systemd unit connects without a token, the socket name already does half
  the job.
- **the module gaps** — the NixOS module has no `selection` option (the
  `--selection` flag/env exist), and its `profile` option description still
  speaks of `"cache": true` marks from an older schema — refresh both.
- **the alert rules** — the cache's own gauges (poll down, age spikes,
  write-refusal bursts) belong in the family's shipped Prometheus rules
  pack (the scraper's TODO grows the file; the cache contributes rules).

## Done (the highlights; the git history has the details)

The per-entry TTL: the profile entries carry an optional `ttl` (seconds,
`0` = never expire) — `covers()` honors it per word, the global TTL stays
the fallback, the selection filter carries it, and `show cache all` marks
the entries (`[ttl 5s]`).

The native metrics endpoint: `--metrics-port` with the bearer token (the
scraper's scheme) serving the `modbus_cache_*` gauges — the hit/miss
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
forwarded/refused write + the per-client READS tallies. The reports: the
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
