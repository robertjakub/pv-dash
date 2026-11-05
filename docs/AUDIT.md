# Security audit — modbus-cache, modbus-scraper & modbus-fake-inverter (rev. 2)

Scope: the `cache/`, `scrape/` and `inverter/` subprojects plus the shared
`common/` package and the `docker/` images, re-audited at main after
`84b4387` — the tree that carries the state-persistence wave
(`--dump-path`/restore, `lib/persist.py`), the peer-cred control auth
(`common/cred.py`, `--control-trust-uids`), the audit-finding fixes
(F2–F8), the audit-vocabulary rename (`READS` → `REQUESTS`) and the
scraper's profile-`fc` awareness. This document supersedes rev. 1 (the
post-refactor tree after `2db6cfa` + the `common/` extraction, which
absorbed the former per-subproject `cache/secaudit.md` and
`scrape/secaudit.md`). Method: manual code review of every module (wire
handling, control servers, CLIs, config/token/dump loading, audit trail,
metrics endpoints, Nix/Docker deployment), against the NIS2 (EU 2022/2555,
art. 21.2) and DORA (EU 2022/2554, art. 8–14) control checklists plus
targeted offline verification of the suspicious paths found. This is a
design-and-code audit, not a penetration test. The `inverter/` tool is a
test device simulator: its risk class is "developer/demo infrastructure",
not production OT — findings there are weighted accordingly. Findings keep
their numbers across revisions; the ones closed in this revision stay
listed in §3.1 with their fix and verification, new ones take the next
number (F18).

## 1. Assets and trust boundaries

| Surface | cache/ | scrape/ | inverter/ | Auth |
|---|---|---|---|---|
| Modbus TCP listener | `--listen`, default `127.0.0.1:15502` | n/a (outbound only) | `--host/--port`, default `127.0.0.1:5502` (Docker: `0.0.0.0`) | none (the Modbus protocol has none) |
| HTTP `/metrics` listener | n/a | `--listen`, default `127.0.0.1:9350` | n/a | bearer token, constant-time compare |
| control server (JSON lines) | unix socket `/tmp/modbus-cache-<port>.socket`, `chmod 0600` after bind (`0660` with `--control-socket-group`); `--control-port` = TCP on 127.0.0.1, **refuses to start without a token** | none (no control surface) | unix socket, `chmod 0600` after bind; `--control-port` = TCP on 127.0.0.1 | token on TCP (`hmac.compare_digest`), refused without; on unix a kernel-vouched peer (peer-cred: root, the daemon's own user, `--control-trust-uids`) skips the handshake |
| metrics endpoint | `--metrics-port`, off, 127.0.0.1, **refuses to start without `--metrics-token`** | the HTTP listener *is* the metrics surface | `--metrics-port`, off, 127.0.0.1 | bearer token (`hmac.compare_digest`); mandatory on the cache, optional on the fake (test tool) |
| state dump | `--dump-path`: the cached words (+ stamps) and the live setting overrides as one atomic JSON — see F18 | n/a | n/a | local file perms (umask-derived — F18) |
| upstream device connection | outbound to the inverter/SDongle | outbound poll to the inverter/SDongle (or the cache) | n/a (it *is* the device) | none (protocol-inherent) |
| audit trail | XDG state home or stdout, append-only, rotated, control-character-folded (the shared `common/audit.py`) | same | same | local file perms |

Deployment surfaces (docker/): all three images run the tool as the
unprivileged `pvsuite` user on alpine; the shared `entrypoint.sh` runs as
root **only** to seed the `/config` volume (bundled defaults copied in,
existing files kept, `chown pvsuite`) and drops to `pvsuite` via `su-exec`;
the compose stack publishes `5502`, `15502` and `9350` on all host
interfaces (finding F7) and shares one external `config` volume between the
three services.

The scraper is the read-only consumer in the family: it polls the device (or
the cache) and exposes Prometheus metrics — no write path, no control
surface, no state-changing verbs; its attack surface is one HTTP GET route
set plus one outbound Modbus client (FC3/FC4 reads only). The cache's write
path is the only state-changing Modbus surface and is triple-gated
(`--allow-write` off, write ACL, register allow-list — plus the fail-closed
refusal of unparseable write frames, F3). The fake's write path (FC06/16 →
its overlay) is the intended demo feature, gated by control-server access
only.

## 2. Implemented controls (all modules)

- **Access control (NIS2 21.2(h), DORA art. 9)** — cache writes need three
  independent gates plus the parse gate (`proxy.py:27,287,366-395`); control
  TCP requires the token before any command and the cache refuses to start
  a token-less TCP control (`cache/bin/modbus_cache.py:243-247`,
  `cache/lib/control.py:141-148`, constant-time `hmac.compare_digest` at
  `:146`); on the unix socket the peer-cred path authenticates the
  kernel-vouched peers without the secret (`cache/lib/control.py:110-126`,
  `common/cred.py`) and everyone else still needs the token; the cache's
  metrics endpoint is token-mandatory when enabled
  (`cache/bin/modbus_cache.py:252-256`, the gate at
  `cache/lib/metrics.py:161-175`); all non-Modbus listeners bind 127.0.0.1
  hard-coded.
- **Input validation (DORA art. 9)** — MBAP length capped (`2 <= length <=
  MAX_PDU + 2`) in every reader; read counts capped (`1 <= count <= 125`,
  address space bounds); the pre-auth control line buffer drops the
  connection past 1 MB in both control servers (F4's fix); unparseable
  write frames are refused, not forwarded (F3's fix); diagnostics-window
  reads validated; the fake rejects malformed frames with clean exceptions.
  Config/ACL/token/profile/dump parsers fail fast with one-line messages,
  never partial state.
- **Secrets handling** — tokens never logged (logged as `required on TCP` /
  `none`); `--control-token-file` / `--metrics-token-file` /
  `--auth-token-file` for LoadCredential-style files (`common/config.py:26`
  is the shared loader); the Nix modules warn when a token would be
  rendered into the world-readable store ini (`cache/module.nix:402`,
  `scrape/module.nix:214`).
- **Logging / audit (NIS2 21.2(d)(f), DORA art. 11)** — append-only,
  flushed, thread-safe, size/daily-rotated trail (`common/audit.py` — one
  writer for the whole family); writes/refusals/auth-fails/control
  commands/lifecycle events recorded; control characters folded at the
  writer so one event is one physical line (F2's fix); audit falls back to
  stdout (journald) when the path is unwritable.
- **State dump handling** — written atomically (tmp + `os.replace`,
  `persist.py:35-39`), read defensively (format/version/row/bounds
  validation, a foreign or truncated file restores nothing,
  `persist.py:43-72`); loading on start is gated behind
  `--restore-on-start` (the default is starting cold); restored words keep
  their original stamps so the ttl bounds any staleness; restored setting
  overrides go through the same validation as the live `set`
  (`cache/lib/control.py:711-726`) — the dump is config-equivalent trust
  (F18).
- **Supply chain (NIS2 21.2(d), DORA art. 28)** — stdlib-only, zero
  third-party dependencies, no transitive risk; Nix-pinned builds; the
  shared `common/` package narrows the review surface instead of widening
  it (one audit writer, one token loader, one wire core, one peer-cred
  helper).
- **Platform hardening (NIS2 21.2(a)(c))** — `DynamicUser`, `NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
  `RestrictAddressFamilies=AF_INET/AF_UNIX/AF_INET6`, `LoadCredential`
  (`cache/module.nix:435`); unix control sockets get explicit modes after
  bind, never the umask (F8's fix); Docker images run the unprivileged
  `pvsuite` user on alpine, audit to stdout, the entrypoint drops root
  before exec.
- **Resilience (NIS2 21.2(c))** — reconnect with split-on-failure polling,
  per-leaf fault isolation, write-through invalidation, `clear cache` /
  `restart` / `reset` verbs, `announce_exit` for connected consoles; the
  state dump is the write-behind for a gated restart; fuzz and stress
  suites exercise the wire paths.
- **Scrape access control / request surface (NIS2 21.2(h), DORA art. 9)** —
  the whole route set is gated before dispatch: a missing/invalid bearer
  answers 401 with `WWW-Authenticate: Bearer realm="metrics"`, compared in
  constant time (`scrape/lib/server.py:32,90`), and unauthorized attempts
  are logged at WARNING with the peer; exactly two GET routes (`/`,
  `/metrics`), everything else a 404; responses carry
  `Cache-Control: no-store`; `--auth-token-file` (LoadCredential-style,
  SIGHUP-rereadable) is preferred over `--auth-token` and giving both is an
  error (`scrape/bin/modbus_scraper.py:89`); `--max-clients` (default 64) sheds
  excess HTTP clients with an immediate 503 (`lib/server.py:119`) and
  `--client-timeout` kicks idle keep-alive connections — the fixed-rate poll
  loop means request floods cannot reach the device (the metrics are a
  snapshot, not per-request fetches).

## 3. Findings

### 3.1 Closed in this revision (F2–F8; fixes verified, see §4)

| # | Module | Was | Fix (where) |
|---|---|---|---|
| F2 | cache, inverter | MEDIUM — **audit-trail injection**: a control command embedding newlines (JSON `\u000a`) wrote a second, fully attacker-crafted physical trail line (a forged `AUDIT CACHE WRITE …` with an attacker-chosen stamp), undermining the integrity of the very artifact DORA art. 11 detection relies on. | The writer folds control characters in every detail line — one shared site covers the COMMAND echoes and any future writer (`common/audit.py event()`). Verified: the forged text stays inside the one wrapped COMMAND line (§4). |
| F3 | cache | LOW — **register allow-list failed open on unparseable writes**: a write frame too short to carry the address yielded `_write_target → None`, `_write_allowed(None) → True`, and after the first two gates the frame was forwarded upstream verbatim. | Fail closed: an unparseable write frame is refused with ILLEGAL_VALUE and audited as `WRITE-REFUSED` (`proxy.py:366-372`). Verified: FC6 with no address → `0x86/0x03`. |
| F4 | cache, inverter | LOW — **uncapped pre-auth control line buffer**: a client streaming bytes without a newline grew `buf` until the 300 s idle timeout — an unauthenticated local memory amplification on the unix socket. | Both control servers drop the connection past the 1 MB `MAX_LINE` (`cache/lib/control.py:33,191-193`, `inverter/lib/control.py:33,162-164`). Verified: a 1.1 MB newline-less stream is dropped. |
| F5 | cache, inverter | LOW — **token-less TCP control was fully unauthenticated**: `--control-port N` without a token left every control verb (including `set allow-write on` and `shutdown`) open to any local process able to reach 127.0.0.1; no rate limit on auth attempts either (AUTH-FAIL is audited, the compare is constant-time). | The cache refuses to start a TCP control port without a token — the unix socket needs none (`cache/bin/modbus_cache.py:243-247`); the inverter stays exempt (a test tool, F11). Verified: startup refusal, one line, rc 2. |
| F6 | cache | LOW — the cache's metrics endpoint, when enabled without `--metrics-token`, exposed register values, addresses and poll state to anyone who could reach it; no connect timeout on the handler (slowloris could pin threads). | The token is mandatory when the port is set — the proxy refuses to start otherwise (`cache/bin/modbus_cache.py:254-257`); the handler socket times out after 5 s (`cache/lib/metrics.py:156`). Verified: startup refusal; the 401/200 flows unchanged. |
| F8 | cache, inverter | LOW — the unix control socket's file mode was never set explicitly: `bind()` created it with the umask-derived mode, and a permissive umask (002/000) made it group/world-connectable, i.e. control access without a token. | Both control servers `chmod 0600` immediately after `bind()`; the cache takes `--control-socket-group` for `0660` — an opt-in, documented delegation to a local group (`cache/lib/control.py:78-86`, `inverter/lib/control.py:71-79`). Verified: the modes are observed `0600`/`0660` on the live sockets. |

### 3.2 Open findings

| # | Module | Severity | Finding | Recommendation |
|---|---|---|---|---|
| F1 | cache, scrape, inverter | HIGH (accepted, protocol-inherent) | Modbus TCP carries no authentication and no encryption — listener and upstream alike. For the scraper this is outbound-only: it cannot be reached through the device, but a compromised inverter LAN segment can feed it bogus register values (sanity-capped by `--max-kwp` / `--max-grid-kw`). | Keep the listener off the WAN (the default binds 127.0.0.1), set the connect ACL on a LAN, keep `--allow-write` off unless needed; the cache owning the device's single client slot is the mitigation. |
| F7 | docker (all three services) | LOW | docker/compose publishes every listener on all host interfaces: the fake's Modbus (`5502`), the cache's Modbus (`15502`) **and the scraper's unauthenticated-by-default `/metrics` (`9350`)** — in the demo stack F13's exposure is materialized by default. | Publish as `127.0.0.1:5502:5502` (etc.) by default or document the LAN exposure next to the compose example; ship the compose scrape/token story with the Prometheus service. |
| F9 | cache, inverter | INFO | Tokens passed as `--control-token` / `--metrics-token` flags are visible in `ps` / `/proc/*/cmdline` to other local users. The token-file / env-var paths exist and the Nix modules warn about the rendered-ini case. | Prefer `--control-token-file` (LoadCredential) or the env var in deployments; document the flag exposure in the READMEs. |
| F10 | cache, scrape, inverter | INFO | The audit trail is append-only but not integrity-protected (no hash chain / signature); a local administrator can rewrite it (applies to all three modules — one shared writer). The F2 fix removed the remote-forgery vector; the local-admin trust assumption remains. | Forward to journald (sealed) or a remote collector for the retention/immutability requirement. |
| F11 | inverter | INFO | The fake's Modbus surface has no client limit, no client timeout and no ACL — any LAN peer can hold threads or flood requests when bound beyond localhost. Its metrics endpoint also serves without a token by design. Acceptable for a test tool; the Docker CMD deliberately binds 0.0.0.0. | Document that the fake is for trusted/LAN-isolated networks; optionally add `--max-clients`/`--client-timeout` mirroring the cache. Also: a declared read count far above the payload (e.g. 0xFFFF with a truncated frame) makes the fake assemble an oversized reply / scan the range — cap `count` by the remaining frame as the cache does. |
| F12 | cache, inverter | INFO | `/tmp` control sockets have predictable names (pre-bind unlink); token files are not permission-checked — the shared `load_token_file` (`common/config.py:26-38`) accepts a group/world-readable token file silently. Re-verified this revision: still no `st_mode` check. | The Nix module's `PrivateTmp` isolates it; use `/run/<tool>/` under systemd. Warn when a token file is group/other-readable. |
| F13 | scrape | MEDIUM | `/metrics` is unauthenticated by default (`--auth-token` unset → every request is authorized). The listener binds 127.0.0.1 by default, but one flag (`0.0.0.0`-style listen or a published port) exposes every register value — production data, not metadata; the compose stack publishes it (F7). The rate limiter is per-connection, not per-IP. | Always set the token in the deployment; consider refusing to start when the listen host is not loopback and no token is configured (the cache's F5 pattern). |
| F14 | scrape | LOW | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics travel in clear text. | Terminate TLS in a reverse proxy when anything beyond localhost needs the endpoint. |
| F15 | scrape | INFO | The metrics expose production values (generation, consumption, battery SoC) — a home-occupancy privacy consideration. | The bearer token (F13) + the localhost bind are the controls; treat the endpoint as internal. |
| F16 | scrape | INFO | No automated alerting yet (freshness gap, poll down, exception spikes — the rules pack is pending). | Ship the alert rules file with the NixOS module; NIS2 21.2(d) wants detection wired, not just logged. |
| F17 | docker | INFO | The `/config` volume holds the live ini files — anything a user puts there (e.g. a `control_token =` line) sits in plaintext on a docker volume, and the entrypoint seeds copies **once** (existing files are never refreshed): a fixed bundled default does not reach an existing volume until it is wiped. | Prefer token files outside the volume / `LoadCredential` / secret-backed mounts for anything sensitive; document `docker compose down -v` as the way to re-sync the volume with the bundled defaults. |
| F18 | cache | LOW | **The state dump is config-equivalent trust at rest, with an umask-derived mode**: `--dump-path`'s JSON carries the cached register values (production data) *and* the live setting overrides, and a restore re-applies any registered setting through the live validation — `allow-write` included (`persist.py:35-39` writes the tmp file with the umask-derived mode; `control.py:711-726` re-applies the overrides). Whoever can write the dump file effectively holds config trust; whoever can read it sees the values. The dump path is operator-chosen (no search-path surprises) and loading on start is gated. | Create the dump with an explicit `0600` (chmod the tmp before `os.replace`, the F8 pattern); document the dump as config-trust (own it like the ini; a group-shared dump belongs under `--control-socket-group`-style decisions, not the umask). |

## 4. Verified evidence (this revision)

- **F2 (injection → fold)** — rev. 1 reproduced the forged second line; this
  revision verified the fix: the same command
  (`{"cmd": "show status\n2026-01-01T00:00:00Z AUDIT CACHE WRITE forged line"}`)
  now produces exactly one physical line, the forged text folded inside the
  quoted command of the `COMMAND` event — asserted by the cache regtest
  (the injected command answers a clean `err unknown command`, and every
  trail line carrying the forged text is the wrapped event, none is bare).
- **F3 (fail-open → fail closed)** — the cache regtest sends an FC6 frame
  with no address against a proxy with `--allow-write` on: refused with
  `0x86/0x03` (the pre-fix behavior forwarded it past the allow-list), and
  the trail carries the `WRITE-REFUSED` event with the "too short to carry
  a register address" detail.
- **F4 (cap)** — the regtest streams 1 MB + 64 KB without a newline at a
  token-authenticated TCP control: the server drops the connection (EOF or
  RST) instead of buffering until the idle timeout.
- **F5/F6 (refusals)** — the regtest starts the cache with `--control-port`
  (no token) and with `--metrics-port` (no token): both exit non-zero with
  a one-line error, no traceback.
- **F8 (socket modes)** — the regtest `os.stat`s the live unix control
  sockets: `0600` by default, `0660` with `--control-socket-group`.
- **F18 (dump)** — established by code reading this revision
  (`persist.py:35-39` — no explicit mode on the tmp; `control.py:711-726` —
  the restore re-applies registered settings): not yet fixed.
- **F12** — re-verified by reading: `load_token_file` still has no
  `st_mode` check (`common/config.py:26-38`).
- The remaining open findings are established by code reading (file:line in
  the table), unchanged from rev. 1 where the cited files did not change.

## 5. NIS2 / DORA mapping (all modules; cache is the production-relevant one)

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(a) risk-management policies | yes (scoped) | defaults-as-security documented (writes off, localhost binds, tokens mandatory on the control/metrics surfaces, dry-run); this audit is the written analysis |
| NIS2 21.2(b) incident handling | partial | audit trail + journald retention; no automated alerting yet (F16) |
| NIS2 21.2(c) business continuity | yes | reconnect/backoff, per-leaf isolation, restart/reload/reset verbs, the gated write-behind dump for last-known values; daemons restart cleanly (regtests) |
| NIS2 21.2(d) supply chain | yes | stdlib-only, no third-party code, pinned Nix builds; the shared `common/` core |
| NIS2 21.2(f) effectiveness | partial | fuzz/stress/regression suites (self-contained); no CI enforcement yet |
| NIS2 21.2(g) cyber hygiene / crypto | partial | constant-time token compares, LoadCredential, no secrets in logs; no TLS (F1 — protocol-inherent, F14 — proxy) |
| NIS2 21.2(h) access control / MFA | yes (scoped) | write triple-gate + parse gate, ACLs, token-mandatory control/metrics, peer-cred on the unix sockets; MFA not applicable to a machine protocol |
| DORA art. 8 ICT asset identification | yes | every option logged at start; `inspect` dumps the full state |
| DORA art. 9-10 protection/prevention | yes (cache; scrape: F13 pending) | write gates, ACLs, capped framing, capped buffers, fail-closed writes, token-mandatory surfaces, explicit socket modes, fail-fast validation |
| DORA art. 11 detection | yes (integrity restored); wiring pending | the audit trail's integrity is defensible again (F2 closed, fold at the writer); auth-fail/refusal events; the alert rules pack is the remaining gap (F16) |
| DORA art. 12 BCP | partial | restart/reload/clear verbs, the dump/restore write-behind; no automated failover (single-device by design) |

Scraper deltas against the table above (rows where scrape matches are omitted):

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(b) incident handling | partial | audit trail + unauthorized-request logging at WARNING; the alert pack is pending (F16) |
| NIS2 21.2(f) effectiveness | partial | the fuzz suite is the technical check; no CI enforcement yet |
| NIS2 21.2(g) crypto / hygiene | partial | constant-time bearer compare, no secrets in logs; no TLS (F14 — terminate at a proxy) |
| NIS2 21.2(h) access control | yes (scoped) | bearer gate on the only route set; MFA not applicable to a machine protocol |
| DORA art. 9-10 protection/prevention | yes (F13 pending) | default localhost bind, token gate, two-route whitelist, DoS caps on both the HTTP and the poll side |
| DORA art. 11 detection | partial | audit trail + WARNING-level unauthorized logs + the error-state 503 |
| DORA art. 12 BCP | yes | read-only, stateless, restart-clean; the data plane (Prometheus) holds the history |

## 6. Verdict

The posture is sound for the deployment class all three tools target (an
operational/home LAN behind segmentation): refuse-by-default writes, localhost
binds by default, token-mandatory control and metrics surfaces on the cache,
constant-time token checks, kernel-vouched peer-cred on the unix control
sockets, length-disciplined wire parsing with capped buffers and fail-closed
write parsing, a real audit trail whose integrity survives hostile control
input, explicit socket modes instead of umask hope, zero dependencies,
hardened systemd units and unprivileged containers whose entrypoint drops
root before exec.

Rev. 1 named two findings that touched the audit control itself (F2, F3) and
three cheap control-channel gaps (F4/F5/F8): all five are fixed and
re-verified in this revision, together with F6. The trust-boundary picture
is otherwise stable — the new state-dump surface adds one finding (F18,
small: an explicit `0600` on the dump closes it) and one documented trust
decision (a restored dump may re-apply setting overrides; the dump file
deserves the ini's care). The inverter fake remains a test instrument with
deliberately soft edges (F11); the scraper's material exposures stay
operational, not architectural — set the token (F13), terminate TLS at a
proxy when exposed (F14) and ship the alert rules (F16). The accepted
exposure remains F1 (Modbus TCP itself) — mitigate with segmentation and the
write gates.

Re-run this audit after the scrape control surface / multi-target
evolutions, the TLS story, or any new listener or file format; at least
yearly otherwise.
