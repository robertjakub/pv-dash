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
- **live-setting persistence policy** — a `set interval 5` survives until
  the next SIGHUP (which re-applies the config); `show settings` could mark
  the overridden settings, or SIGHUP could keep them (a policy decision,
  worth making explicitly).

## Done (the highlights; the git history has the details)

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
forwarded/refused write + the per-client READS tallies. The ops: the bin/
lib/ split (static constants in lib/static.json), the Docker image + the
compose service, the NixOS module with the rendered config, the control
options (`controlPort`/`controlToken`/`controlTokenFile` via
LoadCredential), the stress + fuzz suites.
