# Security audit — modbus-scraper

Scope: the `scrape/` subproject at the current main (post `dc148f3`). Method:
manual code review against the NIS2 (EU 2022/2555, art. 21.2) and DORA (EU
2022/2554, art. 8–14) control checklists, with the fuzz suite as evidence.
This is a design-and-code audit, not a penetration test.

## 1. Assets and trust boundaries

| Surface | Default | Auth |
|---|---|---|
| HTTP `/metrics` listener (`--listen`) | `127.0.0.1:9350` | optional bearer token (`hmac.compare_digest`) |
| upstream device connection (`--host/--modbus-port`) | outbound to the inverter/SDongle | none (protocol-inherent) |

The scraper is the read-only consumer in the family: it polls the device
(or the cache) and exposes Prometheus metrics. It has no write path, no
control surface and no state-changing verbs — the attack surface is one
HTTP GET route and one outbound Modbus client.

## 2. Implemented controls

- **Authentication (NIS2 21.2(h), DORA art. 9)** — the whole route set is
  gated before dispatch: a missing/invalid bearer answers 401 with
  `WWW-Authenticate: Bearer realm="metrics"`, compared in constant time
  (`server.py:24-36`); the unauthorized attempts are logged at WARNING with
  the peer. `--auth-token-file` (LoadCredential-style) is preferred over
  `--auth-token`; giving both is an error (`scraper.py:64-68`).
- **Input validation / request surface (DORA art. 9)** — exactly two GET
  routes (`/`, `/metrics`), everything else is a 404; the exposition body is
  generated from the metrics registry (no user input reflected); the
  responses carry `Cache-Control: no-store`; HTTP/1.1 parsing stays inside
  the stdlib's limits. The profile/metrics-spec/config parsers fail with
  clean `SystemExit` messages on malformed input (`metrics.py:24-36`).
- **DoS posture** — `--max-clients` (64) sheds excess HTTP clients with an
  immediate 503 (`server.py:108-123`), `--client-timeout` kicks idle
  keep-alive connections, and the poller is a fixed-rate loop: request
  floods cannot reach the device (the metrics are a snapshot, not
  per-request fetches).
- **Logging / audit (NIS2 21.2(d)(f), DORA art. 11)** — an append-only
  audit trail with the gated rotation (size + optional daily, backups kept),
  UTC stamps, the lifecycle events; the unauthorized requests land in both
  the log (WARNING) and the access log when `--log-access` is set; the
  README points the NIS2/DORA retention documentation at journald.
- **Secrets handling** — the token is never logged (the startup line prints
  `auth: bearer|none`); `--auth-token-file` keeps it out of the process
  list and the store ini warning mirrors the cache's.
- **Supply chain (NIS2 21.2(d), DORA art. 28)** — stdlib-only: zero
  third-party dependencies; the release artifacts are the Nix build and the
  Docker image.
- **Platform hardening (NIS2 21.2(a)(c))** — the NixOS module: `DynamicUser`,
  `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`,
  `RestrictAddressFamilies=AF_INET/AF_INET6` (`module.nix:261-270`).
- **Resilience (NIS2 21.2(c), DORA art. 11-12)** — the reconnect cycle with
  backoff, the error-state 503 (a failed poll is signalled, not silently
  staled), the fuzz suite.

## 3. Findings

| # | Severity | Finding | Recommendation |
|---|---|---|---|
| F1 | MEDIUM | `/metrics` is unauthenticated by default (`--auth-token` unset → `authorized()` is always true). The listener binds 127.0.0.1 by default, but one flag (`0.0.0.0`-style listen or a port publish) exposes every register value — production data, not metadata. | Always set the token in the deployment; consider refusing to start when the listen host is not loopback and no token is configured. |
| F2 | HIGH (accepted, protocol-inherent) | The Modbus upstream has no authentication/encryption — inherent to the protocol. The scraper is outbound-only, so it cannot be reached through the device; a compromised inverter LAN segment can feed it bogus register values. | Network segmentation; the freshness/cap sanity checks (`--max-kwp`, `--max-grid-kw`) catch nonsense values; cross-check against the cache's own endpoint. |
| F3 | LOW | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics travel in clear text. | Terminate TLS in a reverse proxy when anything beyond localhost needs the endpoint; the auth story TODO covers the deployment guidance. |
| F4 | LOW | The audit trail is append-only but not integrity-protected (no hash chain/signature); a local administrator can rewrite it. | Forward to journald (sealed) or a remote collector — the README documents the retention path. |
| F5 | LOW | `address_string()` on an unauthenticated request resolves the peer (no DNS reverse lookup in the stdlib path — it returns the IP), so no lookup DoS; the rate limiter is per-connection, not per-IP. | Keep the listener off hostile networks; the 503 shed caps the harm. |
| F6 | INFO | The metrics expose production values (generation, consumption, battery SoC) — a privacy consideration for the home-occupancy inference. | The bearer token + the localhost bind are the controls; treat the endpoint as internal. |
| F7 | INFO | No automated alerting yet (the freshness gap, the poll down, the exception spikes — the shipped rules pack is in the TODO). | Ship the rules file with the NixOS module; NIS2 21.2(d) wants the detection wired, not just logged. |

## 4. NIS2 / DORA mapping

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(a) risk-management policies | partial | the README documents the auth/listen defaults; this audit is the written analysis |
| NIS2 21.2(b) incident handling | partial | the audit trail + the unauthorized-request logging; the alert pack is pending |
| NIS2 21.2(c) business continuity | yes | the reconnect cycle, the error-state 503, the clean restart (the regtest) |
| NIS2 21.2(d) supply chain | yes | stdlib-only, no third-party code, pinned Nix builds |
| NIS2 21.2(f) effectiveness | partial | the fuzz suite as the technical check; no CI enforcement yet (TODO) |
| NIS2 21.2(g) crypto / cyber hygiene | partial | constant-time bearer compare, no secrets in logs; no TLS (F3 — terminate at a proxy) |
| NIS2 21.2(h) access control / MFA | yes (scoped) | the bearer gate on the only route set; MFA is not applicable to a machine protocol |
| DORA art. 8 asset identification | yes | the startup line logs the full effective config; the metrics spec is declarative |
| DORA art. 9-10 protection/prevention | yes | the default localhost bind, the token gate, the request whitelist, the DoS caps |
| DORA art. 11 detection | partial | the audit + the WARNING-level unauthorized logs + the error-state 503 |
| DORA art. 12 BCP | yes | read-only service, stateless, restart-clean; the data plane (Prometheus) holds the history |

## 5. Verdict

A deliberately small, read-only, stdlib-only surface: two GET routes behind
a constant-time bearer check, DoS caps on both the HTTP and the poll side,
hardened systemd unit, zero dependencies. The material exposures are
operational, not architectural: set the token (F1), terminate TLS at a
proxy when exposed (F3), and ship the alert rules (F7) so detection matches
the logging. Re-run after the multi-target/alert-pack work or at least
yearly.
