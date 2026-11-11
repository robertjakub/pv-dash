# Security-audit history — the pv-suite tree (rev. 1–28)

The per-revision record behind [SECURITY.md](../SECURITY.md): the revision history,
the closed findings with their fix and verification. Findings keep their
numbers across revisions; the current state lives in SECURITY.md.

## 1. Revision history

| Rev | Wave / tree | Outcome |
|---|---|---|
| 1 | the post-refactor tree (`2db6cfa`; absorbed the per-subproject `secaudit.md`s) | the baseline walk |
| 2 | at `84b4387`: state persistence, peer-cred control auth, the audit-vocabulary rename | closed F2–F6, F8 |
| 3 | demo-stack hardening, token discipline, write-default hardening | closed F7, F9, F12; `write-acl`/`write-registers` default `none` |
| 4 | connection caps + integrity waves | closed F10, F11, F13, F18; found F19 |
| 5 | the release-gate reorder | closed F19 (the workflow cuts the release; `--tests full` default; signed tags) |
| 6 | full-suite coverage: the scraper + dashboard control planes, the dashboard HTTP | closed F20; raised F21; the release gate fixed to all ten suites |
| 7 | the least-privilege control plane | closed F22 (the read-only ops token) |
| 8 | set-grammar configs, the RBAC policy table, the dashboard's own `/metrics` | no new findings |
| 9 | hierarchical control grammar + the whole-daemon reload | closed F23 (the reload state file 0600) |
| 10 | the state machinery family-wide | `show <secret>` refuses family-wide |
| 11 | the seal wave | `dump/key` encrypts the state dumps and the reload state files (v2 envelope, HMAC-SHA256 CTR) |
| 12 | the file-reference wave | every secret takes `file:<path>` (`parse_secret`); the unsealed-dump warning |
| 13 | the `-file` sibling removal | `file:` is the one spelling |
| 14 | the modbus-common move | one Modbus implementation; the fake's writes gated by default |
| 15 | the common-split | the wire tier moved byte-for-byte into `common/` |
| 16 | the wire vocabulary | the frame speaks `ok`/`fail`/`bye`; the mac covers the wire form |
| 17 | the note face | restart-marked sets record the configured value (`note`); secrets still refuse outright |
| 18 | the ACL wave on the Modbus plane | standalone ip-prefix acl files on `acl/connect`/`acl/write`; docs/ACL.md |
| 19 | the metrics exposure plane | `metrics/acl` on both `/metrics` endpoints — accept-time, ahead of the caps |
| 20 | the metrics token posture | the F13 refusal shape family-wide (the loopback bind is the auth) |
| 21 | the family completion | the fake's `/metrics` conform; F21 closed (the dashboard's bearer gate, the loopback default) |
| 22 | the control-listener unification | ONE listener tier in `common/control.py`; the private copies shed |
| 23 | the metrics-stack unification | one metrics stack on all four tools; the default binds renumbered 9350–9353 |
| 24 | the secrets-startup-only wave | the live secret rotation retired family-wide (see SECURITY.md) |
| 25 | the alert rules pack | F16 closed — the detection half of the audit vocabulary ships with the exporter (`scraper/alerts.yml`; the cache side on a new `modbus_cache_write_refused_total` counter; the pack since re-homed to `alerts/scraper.yml` + `alerts/cache.yml`) |
| 26 | the audit trail forwarding | `--audit-forward syslog` mirrors every finished line — the per-writer hash chain included — to the local syslog socket (`FailLoudSysLogHandler`, the bin name the tag; journald picks the lines up sealed); the sink stays the authority (a send failure stops the mirroring with one stderr note, never the trail); a socket-less spelling refuses to start |
| 27 | the audit-forward targets (the F10 finish line) | the target grammar `none` / `syslog` / `syslog:/path` / `udp://host[:514]` (RFC5426) / `tcp://host[:514]` (RFC6587); the envelope rides `--audit-forward-format` (`rfc5424`/`cef`) carrying the native line verbatim + the prefix and chain hash as extracted fields — the chain verifies off-box and a chain break can page; `--audit-log none` + a forward is the remote-only mode (the collector the sole holder, the chain reseeds per run); grammar errors and a missing explicit socket refuse hard, an unresolvable remote target warns with the lazy re-arm; TLS deliberately out (the docs/TODO.md anchor) |
| 28 | the docs consolidation (no re-audit) | docs/AUDIT.md became docs/SECURITY.md — the family's one security document: the reporting note, the one-screen posture, the four tools' stories (absorbed from the tool READMEs' Security sections, which became pointers), the deployment-hardening and supply-chain/ACL summaries beside the links; the F-ledger unchanged since rev. 27 |

## 2. Closed findings (fix and verification)

| # | Module | Was | Fix (where) |
|---|---|---|---|
| F2 | cache, inverter | MEDIUM — audit-trail injection: a newline in a control command wrote a second, attacker-crafted physical trail line. | the writer folds control characters in every detail line — one shared site covers all writers (`common/audit.py event()`). |
| F3 | cache | LOW — the register allow-list failed open on unparseable write frames (forwarded verbatim). | fail closed: refused with ILLEGAL_VALUE, audited `WRITE-REFUSED` (`proxy.py:366-372`). |
| F4 | cache, inverter | LOW — uncapped pre-auth control line buffer: unauthenticated local memory amplification. | both control servers drop the connection past the 1 MB `MAX_LINE`. |
| F5 | cache, inverter | LOW — token-less TCP control was fully unauthenticated (every verb, `shutdown` included). | TCP control refuses to start without a token (the fake exempt, F11); the refusal also guards the live rebind (`common/control.py`). |
| F6 | cache | LOW — the metrics endpoint without a token exposed register values; no handler timeout (slowloris). | the token mandatory when enabled; the handler socket times out. (Rev. 20 moved the posture to the F13 shape — mandatory beyond loopback only.) |
| F7 | docker | LOW — the compose stack published every listener on all host interfaces. | nothing published: one `internal: true` network; the demo Prometheus service with the scrape/token story; the `docker run` examples bind loopback only. |
| F8 | cache, inverter | LOW — the unix control socket's mode was umask-derived. | `chmod 0600` immediately after bind; `--control-socket-group` for 0660. |
| F9 | cache, inverter, scrape | INFO — token flags are visible in `ps` / `/proc/*/cmdline`. | documented everywhere: the flag form is for quick tests; prefer `file:`/env. |
| F10 | cache, scrape, inverter | INFO — the audit trail was append-only but not integrity-protected. | a chained hash per entry, per writer prefix, + `scripts/audit_verify.py`; tamper-EVIDENT (a determined local admin can rechain — journald stays the strong answer). |
| F11 | inverter | INFO — the fake's Modbus surface: no client limit/timeout/ACL, oversized replies on a declared count above the payload. | capped (`--max-clients`/`--client-timeout` live, `show connections`, the read-count gate) + the trusted-LAN posture documented, not a security redesign. |
| F12 | cache, inverter, scrape | INFO — token files were not permission-checked. | fail closed: `check_token_file_mode` refuses any group/world-readable file, daemons and ctl/cli clients alike. |
| F13 | scrape | MEDIUM — `/metrics` unauthenticated by default; the loopback bind the only control. | fail closed beyond loopback: a non-loopback listen without a token refuses to start; per-peer caps (`--max-conn-per-ip`). |
| F16 | scrape | INFO — no automated alerting yet (freshness gap, poll down, exception spikes). | the shipped alert rules pack (`scraper/alerts.yml`, rev. 25): six alerts in two groups — the scraper's poll story and the cache's side (poll down, age spikes, the write-refusal bursts on a new `modbus_cache_write_refused_total` counter on the cache's /metrics); the annotations quote the audit vocabulary (a fired page names the WRITE-REFUSED events and the log lines to grep); the demo image bakes it (`rule_files:`), the Nix package installs it (`share/modbus-scraper/alerts.yml`), docs/NIXOS.md shows the `services.prometheus.ruleFiles` wiring; the cache group stays silent until the cache's own /metrics is scraped. |
| F18 | cache | LOW — the state dump was config-equivalent trust at rest with an umask-derived mode. | created `0600` explicitly + a sha256 integrity hash, fail-closed restore; settings-only by default. |
| F19 | scripts | LOW — the release landed before the CI gate reported (the local cut, `--tests quick`, unsigned tag). | the workflow cuts the GH release (`needs: [test, build]`); the local cut is the opt-in `--release`; `--tests full` default; signed tags. |
| F20 | cache, scrape, inverter, dashboard (the ctl/cli clients) | LOW — the help promised token-file env vars the clients never read. | one resolution shape family-wide: `flag or env`, the mutual-exclusion error, the F12 gate on both paths. |
| F21 | dashboard | MEDIUM — the HTTP surface served without authentication and bound `0.0.0.0` by default. | the bearer token on page and proxy (header, HttpOnly cookie, the `?auth=` bootstrap), the default bind `127.0.0.1`, a token-less non-loopback bind refuses to start. |
| F22 | cache, scrape, inverter, dashboard + common | LOW — the control plane had no role separation (one token, full power). | a second, read-only ops token per server (`--control-ops-token`): show/clear verbs only, gated in `common/wiresec.py` `role_allows`, both keys audited with the denials in the trail; ops-without-admin or ops==admin refuses. |
| F23 | cache | LOW — the reload state file was config-equivalent trust at rest with an umask-derived mode. | created `0600` explicitly (the F18 posture); the secrets never save; every restored value re-validates; a 120 s staleness discard. |

## 3. Verified evidence

All ten suites print ALL PASS on the audited trees; `nix flake check`,
`scripts/check_options.py` + `scripts/lint_options.py --check` clean; the
man pages regenerate (`mandoc -Tlint` clean).

- **F2** — the cache regtest: the forged command answers a clean error and
  every trail line carrying the forged text is the one wrapped COMMAND
  event.
- **F3** — an FC6 frame with no address answers `0x86/0x03` and the trail
  carries `WRITE-REFUSED`.
- **F4** — a 1 MB+ newline-less stream at the TCP control is dropped
  (EOF/RST), not buffered.
- **F5/F6/F13/F21** — the refusal matrices: startup refusals exit non-zero
  with a one-liner, no traceback; the 401/bearer/cookie/`?auth=` flows and
  the per-IP 503 asserted in the scrape and dashboard suites.
- **F7** — the resolved compose config: zero published ports, the internal
  network, the token env (config-level; no docker host in the audit
  sandbox).
- **F8/F12** — the live sockets observed `0600`/`0660`; the token-file mode
  matrix (0644/0640 refused, 0600 accepted, missing file the established
  one-liner) in both regtests.
- **F10** — `tests/audit-chain.py`: interleaved prefixes verify OK;
  edited/deleted/reordered lines detected at the right line (exit 1);
  unsigned lines reported; rotation-spanning chains verify oldest-first.
- **F11** — `tests/inverter-regtest.py`: the count gate, the client
  cap/timeout, `show connections`.
- **F18/F23** — the dump/restore round-trips: `0600` observed, the
  tampered/unsigned/group-writable refusals, the reload state file mode
  check on a permissive umask.
- **F19** — the release flight on a scratch repo: the full-suite gate, the
  signed-tag attempt with the documented fallback, no local
  `gh release create` by default.
- **F20** — the env checks in all four affected suites + the live
  `fake_cli`/`dashboard_cli` smokes.
- **F22** — the ops matrices in the four control suites (show ok, steering
  denied, the ops-keyed macs, the `role=` trail lines).
- **Sealing (rev. 11/12)** — the sealed round-trip and the
  no-plaintext-at-rest check on all three state shapes; the
  wrong-key/missing-key/unsealed-under-key refusals; the `file:` key
  round-trip and the SIGHUP re-read.
