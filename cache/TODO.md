# TODO

## Open

- **FC4 input-register caching** — only FC3 (holding registers) is cached
  today; FC4 reads are forwarded live every time. The profile/selection
  format could grow an `fc` field so input-register ranges poll into the
  same cache (the Deye meters live behind FC4 on some models).
- **the control `set` commands** — the control server inspects and clears,
  but cannot *tune*: `set interval 5`, `set ttl 60`, `set merge-gap 4` over
  the JSON control socket would be the interactive counterpart of SIGHUP
  (same reload plumbing, partial settings, the audit trail records who).
- **the native metrics endpoint** — `--metrics-port` with the bearer token,
  like the fake inverter's: the cache's own hit/miss counters, poll health,
  cache age and client count as Prometheus gauges, without depending on the
  scraper's `huawei_cache_*` export path.
- **the write allow-listing per register range** — writes are gated by
  client ACL and the global `--allow-write`; a register-range allow-list
  (e.g. `--write-registers 47400:100`) would let an automation write its
  setpoints and nothing else.
- **the NixOS module control options** — the module cannot expose the
  control server: the default unix socket hides behind `PrivateTmp`. A
  `controlPort` (+ `controlToken`) option would publish it properly.
- **the per-client audit accounting** — the audit trail records the control
  commands and the writes; a periodic per-client read tally (rate-limited,
  e.g. one `READS` line per client per poll of minutes) would answer "who
  is hammering the cache" from the trail alone.
- **the CI** — GitHub Actions: the four suites + `nix flake check` on the
  push; the release workflow on the tag. (Family-wide, see the inverter's
  TODO.)
- **the hardware verification** — everything so far is verified against the
  fake inverter, fuzzing and stress only; a real SUN2000/SDongle session
  (poll pacing, the dongle's single-client behaviour, real exception codes)
  is the last mile. Also worth testing: the Deye profiles against the cache.

## Done (the highlights; the git history has the details)

The control surface: the JSON-lines transport, the TCP token auth, the
audit trail (CACHE/CLI/CTL prefixes, XDG state home, gated rotation), the
`show version` command, the one-shot `cache_ctl`, the console-style
`cache_cli` with the reconnect cycle and the welcome banner, the control
fuzzer. The cache core: device profiles + the selection file, the
merge-gap block planner with the fail-split convergence, per-leaf poll
status (no device hammering), the on-demand forwarding cache with the TTL,
the synthesized 65000-65003 diagnostics block, SIGHUP hot reload + SIGUSR1
cache clean, the connect/write ACLs, the audit of every forwarded/refused
write. The ops: the bin/ lib/ split, the Docker image + the compose
service, the NixOS module with the rendered config, the stress + fuzz
suites.
