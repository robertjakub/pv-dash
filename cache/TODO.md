# TODO

## Open

- **the native metrics endpoint** — `--metrics-port` with the bearer token,
  like the fake inverter's: the cache's own hit/miss counters, poll health,
  cache age and client count as Prometheus gauges, without depending on the
  scraper's `huawei_cache_*` export path.
- **the CI** — GitHub Actions: the four suites + `nix flake check` on the
  push; the release workflow on the tag. (Family-wide, see the inverter's
  TODO.)
- **the hardware verification** — everything so far is verified against the
  fake inverter, fuzzing and stress only; a real SUN2000/SDongle session
  (poll pacing, the dongle's single-client behaviour, real exception codes,
  the FC4 input registers on a real device) is the last mile. Also worth
  testing: the Deye profiles against the cache.
- **the scraper's FC4 awareness** — the profile schema now carries the `fc`
  field (the cache polls/caches FC4 independently); the scraper still reads
  everything with FC3 — a profile that marks an FC4 entry `scrape` needs
  the scraper to follow the field.
- **the per-entry TTL** — the profile entries could carry a `ttl` (the fast
  power registers 5s, the slow nameplate words 1h): one poll cadence, but
  `covers()` honors the per-entry expiry instead of the global factor.
- **the read-only control role** — a second token granting only the
  show/clear verbs (no `set`, no `shutdown`): the ops shift versus the
  admin key, both audited.
- **the peer-cred auth on the unix control socket** — SO_PEERCRED: a local
  systemd unit connects without a token, the socket name already does half
  the job.
- **the poll-latency gauges** — the last/mean poll cycle duration on the
  metrics endpoint once it lands (the control's `show status` carries the
  health; the trend belongs in Prometheus).

## Done (the highlights; the git history has the details)

The live-setting persistence policy, made explicit: a live `set` survives
until the next SIGHUP (the config file always wins on reload); `show
settings` marks the overridden values with a `*`, `show status` carries the
`overridden=` row, and the SIGHUP clears the markers. The write-through
invalidation: a forwarded FC06/16/22/23 write drops exactly the cached
words it touched (per-register, `Cache.invalidate`), wakes the poller, and
the next read goes to the device instead of serving the pre-write value
until the TTL.

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
welcome banner parsing the report.
