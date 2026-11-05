# Security audit — modbus-cache, modbus-scraper & modbus-fake-inverter

Scope: the `cache/`, `scrape/` and `inverter/` subprojects plus the shared
`common/` package and the `docker/` images, at the post-refactor working tree
(main after `2db6cfa` + the `common/` extraction, the scrape bin+lib layout
and the compose demo stack). This document supersedes and absorbs the former
per-subproject `cache/secaudit.md` and `scrape/secaudit.md`. Method: manual
code review of every module (wire handling, control servers, CLIs, config/token
loading, audit trail, Nix/Docker deployment), against the NIS2 (EU 2022/2555,
art. 21.2) and DORA (EU 2022/2554, art. 8–14) control checklists plus targeted
offline verification of the suspicious paths found — re-verified against the
refactored tree after the `common/` extraction. This is a design-and-code
audit, not a penetration test. The `inverter/` tool is a test device
simulator: its risk class is "developer/demo infrastructure", not production
OT — findings there are weighted accordingly.

## 1. Assets and trust boundaries

| Surface | cache/ | scrape/ | inverter/ | Auth |
|---|---|---|---|---|
| Modbus TCP listener | `--listen`, default `127.0.0.1:15502` | n/a (outbound only) | `--host/--port`, default `127.0.0.1:5502` (Docker: `0.0.0.0`) | none (the Modbus protocol has none) |
| HTTP `/metrics` listener | n/a | `--listen`, default `127.0.0.1:9350` | n/a | optional bearer token (constant-time compare) |
| control server (JSON lines) | unix socket `/tmp/modbus-cache-<port>.socket`; `--control-port` = TCP on 127.0.0.1 | none (no control surface) | unix socket `/tmp/fake-inverter-<port>.socket`; `--control-port` = TCP on 127.0.0.1 | token on TCP (`hmac.compare_digest`), none needed on unix |
| metrics endpoint | `--metrics-port`, off, 127.0.0.1 | the HTTP listener *is* the metrics surface | `--metrics-port`, off, 127.0.0.1 | optional bearer token (`hmac.compare_digest`) |
| upstream device connection | outbound to the inverter/SDongle | outbound poll to the inverter/SDongle (or the cache) | n/a (it *is* the device) | none (protocol-inherent) |
| audit trail | XDG state home or stdout, append-only, rotated (the shared `common/audit.py`) | same | same | local file perms |

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
plus one outbound Modbus client. The cache's write path is the only
state-changing Modbus surface and is triple-gated (`--allow-write` off, write
ACL, register allow-list). The fake's write path (FC06/16 → its overlay) is
the intended demo feature, gated by control-server access only.

## 2. Implemented controls (all modules)

- **Access control (NIS2 21.2(h), DORA art. 9)** — cache writes need three
  independent gates (`proxy.py:337-357`); control TCP requires the token
  before any command (`cache/lib/control.py:112-119`, `inverter/lib/control.py:81-88`,
  constant-time `hmac.compare_digest`); metrics requires the bearer token when
  set (`cache/lib/metrics.py:101-106`, `inverter/lib/metrics.py:102-107`,
  `scrape/lib/server.py:30,90`); all non-Modbus listeners bind 127.0.0.1
  hard-coded.
- **Input validation (DORA art. 9)** — MBAP length capped (`2 <= length <=
  MAX_PDU + 2`) in every reader; read counts capped (`1 <= count <= 125`,
  address space bounds); diagnostics-window reads validated; the fake rejects
  malformed frames with clean exceptions. Config/ACL/token/profile parsers
  fail fast with one-line `SystemExit` messages, never partial state.
- **Secrets handling** — tokens never logged (logged as `required on TCP` /
  `none`); `--control-token-file` / `--metrics-token-file` /
  `--auth-token-file` for LoadCredential-style files (`common/config.py:26`
  is the shared loader); the Nix module warns when a token would be
  rendered into the world-readable store ini (`cache/module.nix:311`).
- **Logging / audit (NIS2 21.2(d)(f), DORA art. 11)** — append-only, flushed,
  thread-safe, size/daily-rotated trail (`common/audit.py` — one writer for
  the whole family since the refactor); writes/refusals/auth-fails/control
  commands/lifecycle events recorded; audit falls back to stdout (journald)
  when the path is unwritable.
- **Supply chain (NIS2 21.2(d), DORA art. 28)** — stdlib-only, zero
  third-party dependencies, no transitive risk; Nix-pinned builds; the
  shared `common/` package narrows the review surface instead of widening
  it (one audit writer, one token loader, one wire core).
- **Platform hardening (NIS2 21.2(a)(c))** — `DynamicUser`, `NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
  `RestrictAddressFamilies=AF_INET/AF_INET6`, `LoadCredential`
  (`cache/module.nix:331-347`); Docker images run the unprivileged `pvsuite`
  user on alpine, audit to stdout, the entrypoint drops root before exec.
- **Resilience (NIS2 21.2(c))** — reconnect with split-on-failure polling,
  per-leaf fault isolation, write-through invalidation, `clear cache` /
  `restart` / `reset` verbs, `announce_exit` for connected consoles; fuzz and
  stress suites exercise the wire paths.
- **Scrape access control / request surface (NIS2 21.2(h), DORA art. 9)** —
  the whole route set is gated before dispatch: a missing/invalid bearer
  answers 401 with `WWW-Authenticate: Bearer realm="metrics"`, compared in
  constant time (`scrape/lib/server.py:30,90`), and unauthorized attempts
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

| # | Module | Severity | Finding | Recommendation |
|---|---|---|---|---|
| F1 | cache, scrape, inverter | HIGH (accepted, protocol-inherent) | Modbus TCP carries no authentication and no encryption — listener and upstream alike. For the scraper this is outbound-only: it cannot be reached through the device, but a compromised inverter LAN segment can feed it bogus register values (sanity-capped by `--max-kwp` / `--max-grid-kw`). | Keep the listener off the WAN (the default binds 127.0.0.1), set the connect ACL on a LAN, keep `--allow-write` off unless needed; the cache owning the device's single client slot is the mitigation. |
| F2 | cache, inverter | MEDIUM | **Audit-trail injection**: a control command may embed newlines (JSON `\u000a`), and the server logs the raw command — one event writes two physical lines, the second fully attacker-crafted, e.g. a forged `AUDIT CACHE WRITE …` line with an attacker-chosen timestamp. Re-verified against the refactored tree: `{"cmd": "show status\n2026-… AUDIT CACHE WRITE …"}` still produces the forged line. This undermines the integrity of the very artifact DORA art. 11 detection relies on. | Sanitize before writing: fold control characters (`' '.join(cmd.split())` or escape) where the COMMAND events are built (`cache/lib/control.py:174`, `inverter/lib/control.py:149`) and in the `%r` echo of unknown commands (`cache/lib/control.py:272`). Defense in depth got cheaper with the refactor: the writer itself is now one shared site — reject/escape `\n`/`\r` in `common/audit.py` `event()` detail. |
| F3 | cache | LOW | **Register allow-list fails open on unparseable writes**: a write frame too short to carry the address (`len(pdu) < 5`) yields `_write_target → None`, and `_write_allowed(None)` returns True (`proxy.py:261`) — after the `--allow-write` and write-ACL gates pass, the frame is forwarded upstream verbatim. Re-verified against the refactored tree. The read-side `len(pdu) < 5` check (`proxy.py:359`) covers FC3/FC4 only, not the write funcs. | Fail closed: when the target cannot be parsed (`target is None`), refuse with ILLEGAL_VALUE instead of forwarding (`proxy.py:351`). |
| F4 | cache, inverter | LOW | **Pre-auth control line buffer is uncapped**: a client streaming bytes without a newline grows `buf` until the 300 s idle timeout (`cache/lib/control.py:146-164`, `inverter/lib/control.py:121-140`). TCP-only (127.0.0.1), but on the unix socket it is an unauthenticated local memory-amplification. | Cap `buf` (drop the connection past ~1 MB) in both `handle()` loops. |
| F5 | cache, inverter | LOW | **TCP control without a token is fully unauthenticated**: `--control-port N` without `--control-token` leaves every control verb (including `set allow-write on` and `shutdown`) open to any local process able to reach 127.0.0.1. There is also no rate limit on auth attempts (AUTH-FAIL is audited, the compare is constant-time). | Either refuse to serve TCP control without a token, or log a loud warning at start; consider a small auth-failure delay/limit. The default (unix socket) is the safe path. |
| F6 | cache | LOW | The cache's metrics endpoint, when enabled without `--metrics-token`, exposes register values, addresses and poll state to anyone who can reach it. No connect timeout on the handler either (slowloris can pin threads). | Default is off and 127.0.0.1; make the token mandatory when the port is set; set a socket timeout on the metrics handler. |
| F7 | docker (all three services) | LOW | docker/compose publishes every listener on all host interfaces: the fake's Modbus (`5502`), the cache's Modbus (`15502`) **and the scraper's unauthenticated-by-default `/metrics` (`9350`)** — in the demo stack F13's exposure is materialized by default. | Publish as `127.0.0.1:5502:5502` (etc.) by default or document the LAN exposure next to the compose example; ship the compose scrape/token story with the Prometheus service. |
| F8 | cache, inverter | LOW | The unix control socket's file mode is never set explicitly — `bind()` creates it with the umask-derived mode. Default umasks (022) are safe (connect needs the write bit), but a permissive umask (002/000) makes it group/world-connectable, i.e. control access without a token. | `os.chmod(sockpath, 0o600)` immediately after `bind()` in both control servers. |
| F9 | cache, inverter | INFO | Tokens passed as `--control-token` / `--metrics-token` flags are visible in `ps` / `/proc/*/cmdline` to other local users. The token-file / env-var paths exist and the Nix module warns about the rendered-ini case. | Prefer `--control-token-file` (LoadCredential) or the env var in deployments; document the flag exposure in the READMEs. |
| F10 | cache, scrape, inverter | INFO | The audit trail is append-only but not integrity-protected (no hash chain / signature); a local administrator can rewrite it (applies to all three modules — one shared writer since the refactor). | Forward to journald (sealed) or a remote collector for the retention/immutability requirement. |
| F11 | inverter | INFO | The fake's Modbus surface has no client limit, no client timeout and no ACL — any LAN peer can hold threads or flood requests when bound beyond localhost. Acceptable for a test tool; the Docker CMD deliberately binds 0.0.0.0. | Document that the fake is for trusted/LAN-isolated networks; optionally add `--max-clients`/`--client-timeout` mirroring the cache. Also: a declared read count far above the payload (e.g. 0xFFFF with a truncated frame) makes the fake assemble an oversized reply / scan the range — cap `count` by the remaining frame as the cache does. |
| F12 | cache, inverter | INFO | `/tmp` control sockets have predictable names (pre-bind unlink); token files are not permission-checked — the shared `load_token_file` (`common/config.py:26`) accepts a group/world-readable token file silently. | The Nix module's `PrivateTmp` isolates it; use `/run/<tool>/` under systemd. Warn when a token file is group/other-readable. |
| F13 | scrape | MEDIUM | `/metrics` is unauthenticated by default (`--auth-token` unset → every request is authorized). The listener binds 127.0.0.1 by default, but one flag (`0.0.0.0`-style listen or a published port) exposes every register value — production data, not metadata; the compose stack publishes it (F7). The rate limiter is per-connection, not per-IP. | Always set the token in the deployment; consider refusing to start when the listen host is not loopback and no token is configured. |
| F14 | scrape | LOW | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics travel in clear text. | Terminate TLS in a reverse proxy when anything beyond localhost needs the endpoint. |
| F15 | scrape | INFO | The metrics expose production values (generation, consumption, battery SoC) — a home-occupancy privacy consideration. | The bearer token (F13) + the localhost bind are the controls; treat the endpoint as internal. |
| F16 | scrape | INFO | No automated alerting yet (freshness gap, poll down, exception spikes — the rules pack is pending). | Ship the alert rules file with the NixOS module; NIS2 21.2(d) wants detection wired, not just logged. |
| F17 | docker | INFO | The `/config` volume holds the live ini files — anything a user puts there (e.g. a `control_token =` line) sits in plaintext on a docker volume, and the entrypoint seeds copies **once** (existing files are never refreshed): a fixed bundled default does not reach an existing volume until it is wiped. | Prefer token files outside the volume / `LoadCredential` / secret-backed mounts for anything sensitive; document `docker compose down -v` as the way to re-sync the volume with the bundled defaults. |

## 4. Verified evidence

- **F2 (injection)** — reproduced offline against `common/audit.py` +
  `cache/lib/control.py:174`'s exact formatting path (re-run after the
  refactor): one COMMAND event produced two physical audit lines, the second
  starting with the forged `2026-01-01T00:00:00Z AUDIT CACHE WRITE …` stamp.
- **F3 (fail-open)** — reproduced offline against the refactored
  `cache/lib/proxy.py`: `_write_target(b'\x10\x00\x00') → None`,
  `_write_allowed(None) → True` (proxy.py:261) while a well-formed
  out-of-range write correctly returns False; a short write frame that
  passes the first two gates is therefore forwarded upstream.
- **F4/F8/F12/F6-timeout** — established by targeted reading of the
  refactored files: no `len(buf)` cap, no `chmod` after `bind()`, no
  `st_mode` check in `load_token_file`, no `settimeout` in the cache metrics
  handler.
- The remaining findings are established by code reading (file:line above).

## 5. NIS2 / DORA mapping (all modules; cache is the production-relevant one)

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(a) risk-management policies | partial | defaults-as-security documented (writes off, localhost binds, dry-run); this audit is the written analysis |
| NIS2 21.2(b) incident handling | partial | audit trail + journald retention; no automated alerting yet |
| NIS2 21.2(c) business continuity | yes | reconnect/backoff, per-leaf isolation, restart/reload/reset verbs; daemons restart cleanly (regtests) |
| NIS2 21.2(d) supply chain | yes | stdlib-only, no third-party code, pinned Nix builds; the shared `common/` core |
| NIS2 21.2(f) effectiveness | partial | fuzz/stress/regression suites (seven, self-contained); no CI enforcement yet |
| NIS2 21.2(g) cyber hygiene / crypto | partial | constant-time token compares, LoadCredential, no secrets at rest; no TLS (F1 — protocol-inherent) |
| NIS2 21.2(h) access control / MFA | yes (scoped) | write triple-gate, ACLs, control/metrics tokens; MFA not applicable to a machine protocol |
| DORA art. 8 ICT asset identification | yes | every option logged at start; `inspect` dumps the full state |
| DORA art. 9-10 protection/prevention | yes (F2/F3/F4/F13 pending) | write gates, ACLs, capped framing, fail-fast validation |
| DORA art. 11 detection | partial | audit trail + auth-fail/refusal events (F2 weakens integrity until fixed); metrics gauges as monitoring hooks |
| DORA art. 12 BCP | partial | restart/reload/clear verbs; no automated failover (single-device by design) |

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
operational/home LAN behind segmentation): refuse-by-default writes,
localhost-binds by default, constant-time token checks, length-disciplined
wire parsing, a real audit trail, zero dependencies, hardened systemd units
and unprivileged containers whose entrypoint drops root before exec. The
`common/` extraction narrowed the shared surface (one audit writer, one
token loader, one wire core) without moving anything off-loopback — the
trust boundaries of section 1 are unchanged. The inverter fake is a test
instrument and carries no state worth protecting beyond its LAN segment.
The scraper is deliberately small, read-only and stdlib-only (two GET routes
behind a constant-time bearer check, DoS caps on both the HTTP and the poll
side); its material exposures are operational, not architectural — set the
token (F13), terminate TLS at a proxy when exposed (F14) and ship the alert
rules (F16) so detection matches the logging.

Two findings deserve prompt fixes because they touch the audit control
itself: **F2** (audit-trail injection via newline-bearing control commands —
re-verified after the refactor, and cheaper to fix now that the writer is
the shared `common/audit.py`) and **F3** (the register allow-list failing
open on unparseable write frames — re-verified; make the gate fail closed).
F4/F5/F8 are small hardening gaps in the control channel that close in a few
lines each; F17 documents the docker config-volume semantics so secrets and
stale defaults are a documented choice, not a surprise. The accepted
exposure remains F1 (Modbus TCP itself) — mitigate with segmentation and the
write gates. Re-run this audit after the fixes and the planned per-entry-TTL
follow-ups, read-only-control-role, peer-cred auth and scrape multi-target
evolutions, or at least yearly.
