# Security audit — modbus-cache

Scope: the `cache/` subproject at the current main (post `dc148f3`). Method:
manual code review against the NIS2 (EU 2022/2555, art. 21.2) and DORA (EU
2022/2554, art. 8–14) control checklists, plus the suite's own fuzz/stress
suites as evidence. This is a design-and-code audit, not a penetration test.

## 1. Assets and trust boundaries

| Surface | Default | Auth |
|---|---|---|
| Modbus TCP listener (`--listen`) | `127.0.0.1:15502` | none (the Modbus protocol has none) |
| control server (JSON lines) | unix socket `/tmp/modbus-cache-<port>.socket`; `--control-port` = TCP on 127.0.0.1 | token on TCP (`hmac.compare_digest`), none needed on unix |
| metrics endpoint (`--metrics-port`) | off | optional bearer token (`hmac.compare_digest`) |
| upstream device connection | outbound to the inverter/SDongle | none (protocol-inherent) |

The clients: the dashboard never touches the cache directly; the scraper
pulls registers either through the cache or from the device. The write path
is the only state-changing surface and is triple-gated.

## 2. Implemented controls

- **Access control (NIS2 21.2(h), DORA art. 9)** — writes are refused unless
  three independent gates open: `--allow-write` (off by default), the client
  on the write ACL, the target registers on the write allow-list
  (`proxy.py:322-340`). The connect ACL gates the listener itself
  (`proxy.py:289-299` area). Control TCP requires an authenticated token
  before any command (`control.py:112-119`, constant-time compare); the
  metrics endpoint requires the bearer token when set (`metrics.py:99-108`,
  constant-time compare).
- **Input validation (DORA art. 9)** — the Modbus framing caps the declared
  length (`2 <= length <= MAX_PDU + 2`, `proxy.py:311`), so a hostile length
  field cannot allocate unbounded buffers; `proto` and the address space are
  checked before any work (`proxy.py:333-352`); the write payload is
  re-derived, not trusted. The control line protocol is auth-first and
  length-disciplined (buffered `recv(65536)` chunks, an idle timeout
  `CONTROL_IDLE_TIMEOUT_S` sheds silent clients). Profile, selection, ACL
  and token-file parsers fail with clean `SystemExit` messages (no partial
  state).
- **Logging / audit (NIS2 21.2(d)(f), DORA art. 11)** — every
  forwarded/refused/rejected/failed write, every control command (with
  peer), every AUTH-FAIL, the per-client READS tallies and the
  START/RELOAD/RESET/SHUTDOWN lifecycle land in the append-only audit trail
  (CACHE/CLI/CTL prefixes), size + optional daily rotation, thread-safe,
  flushed per write. The README points the NIS2/DORA retention documentation
  at journald (`journalctl -u modbus-cache`).
- **Secrets handling** — tokens never appear in logs or audit lines (logged
  as `required on TCP`/`none`); token files (e.g. systemd LoadCredential)
  are preferred over flags; the NixOS module warns when a token is rendered
  into the world-readable store ini.
- **Supply chain (NIS2 21.2(d), DORA art. 28)** — stdlib-only: zero
  third-party dependencies, no transitive risk; the version is stamped from
  the git revision; the release artifacts are the Nix build and the Docker
  image.
- **Platform hardening (NIS2 21.2(a)(c))** — the NixOS module runs with
  `DynamicUser`, `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`,
  `PrivateTmp`, `RestrictAddressFamilies=AF_INET/AF_INET6`
  (`module.nix:331-347`); secrets via `LoadCredential`. Docker/compose
  mirrors the split.
- **Resilience (NIS2 21.2(c), DORA art. 11-12)** — reconnect with backoff,
  per-leaf poll status (a failed range does not hammer the device nor poison
  unrelated reads), write-through invalidation, `clear cache`/`restart`
  control verbs, SIGUSR1 cache clean, `announce_exit` for the connected
  clients; the fuzz + stress suites exercise the paths.

## 3. Findings

| # | Severity | Finding | Recommendation |
|---|---|---|---|
| F1 | HIGH (accepted, protocol-inherent) | Modbus TCP carries no authentication and no encryption — upstream and listener alike. Anyone who reaches the listener reads the registers; the upstream trusts whoever owns the dongle's port. | Keep the listener off the WAN (the default binds 127.0.0.1), set the connect ACL on a LAN, keep writes off unless a client needs them. The upstream device is single-client by design — the cache owning that connection is the mitigation. Document the segmentation. |
| F2 | MEDIUM | The control TCP token travels in clear text (no TLS on the JSON-lines channel). | Keep the TCP control bound to 127.0.0.1 or front it with an SSH tunnel/stunnel; prefer the unix socket (the default) for local automation. |
| F3 | LOW | The control pre-auth line buffer is uncapped: a client that streams bytes without a newline grows `buf` until the idle timeout closes the socket (`control.py:154-164`). TCP-only, localhost-bound by default. | Cap `buf` (drop the connection past ~1 MB) in `handle()`. |
| F4 | LOW | The connect/write ACLs are IP-based — spoofable on an L2 LAN (ARP). | Treat them as coarse segmentation, not identity; firewall the listener; the write gates stack on top. |
| F5 | LOW | The audit trail is append-only but not integrity-protected (no hash chain or signature); a local administrator can rewrite it. | Forward to journald (sealed) or a remote collector for the retention/immutability requirement — the README documents the journald path. |
| F6 | LOW | The metrics endpoint, when enabled without `--metrics-token`, exposes register values, addresses and the poll state to anyone who can reach it. | Default is off and 127.0.0.1; make the token mandatory in your deployment when the port is set. |
| F7 | INFO | The default unix control socket lives under `/tmp` with a predictable name (pre-bind unlink; the Nix module's PrivateTmp isolates it, and the module warns to use `/run/modbus-cache/`). | Use `/run/modbus-cache/` under systemd. |
| F8 | INFO | No MFA and no per-request rate limiting on Modbus reads. MFA is not applicable to a machine protocol (the control/metrics tokens are bearer secrets); read floods are absorbed by the cache and capped by `--max-clients`/`--client-timeout`. | Document the control-token distribution as the privileged access process (NIS2 21.2(h) applies to the org's remote access, not this LAN protocol). |

## 4. NIS2 / DORA mapping

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(a) risk-management policies | partial | the README documents the defaults-as-security (writes off, localhost binds); this audit is the written analysis |
| NIS2 21.2(b) incident handling | partial | the audit trail + journald retention give the evidence base; no automated alerting yet (see scrape/TODO alert pack) |
| NIS2 21.2(c) business continuity | yes | reconnect/backoff, per-leaf isolation, restart/reload verbs, announce_exit; the daemon restarts cleanly (the regtest) |
| NIS2 21.2(d) supply chain | yes | stdlib-only, no third-party code, pinned release builds (Nix) |
| NIS2 21.2(f) effectiveness | partial | the fuzz + stress suites are the technical checks; no CI enforcement yet (TODO) |
| NIS2 21.2(g) cyber hygiene / crypto | partial | constant-time token compares, no secrets at rest outside LoadCredential; no TLS (F1/F2 — the protocol's limit) |
| NIS2 21.2(h) access control / MFA | yes (scoped) | least-privilege write gates, ACLs, tokens; MFA not applicable to a machine protocol |
| DORA art. 8 ICT asset identification | yes | every option logged at start (`caching …` line), inspect dumps the full state |
| DORA art. 9-10 protection/prevention | yes | F1 mitigations, the write triple-gate, the ACLs, the input validation |
| DORA art. 11 detection | partial | the audit trail + the auth-fail/refusal events; the metrics gauges give the monitoring hooks |
| DORA art. 12 BCP | partial | restart/reload/clear verbs; no automated failover (single-device by design) |

## 5. Verdict

The posture is sound for its deployment class (a LAN/home or an operational
LAN behind segmentation): refuse-by-default writes, localhost binds,
constant-time token checks, capped wire parsing, a real audit trail, zero
dependencies and systemd hardening. The remaining exposure concentrates in
F1 (the Modbus protocol itself) — mitigate with segmentation and the write
gates, and in F2/F3 — cheap to close (a tunnel, a buffer cap). Re-run this
audit after the per-entry-TTL/metrics evolutions or at least yearly.
