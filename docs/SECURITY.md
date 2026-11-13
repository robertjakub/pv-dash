# Security — the pv-suite tree (rev. 31)

This is the family's **one security document**: the posture, the trust
boundaries, the implemented controls, the per-tool stories, the audit
findings and the supply-chain claim. The mechanism references of their own
stay separate and are linked where they answer a security question —
[common/ACL.md](specs/ACL.md) (the ACL grammar), [sbom/SBOM.md](sbom/SBOM.md)
(the supply chain), [../nixos/README.md](../nixos/README.md) (the NixOS
hardening and the option map).

Scope: the `apps/cache/`, `apps/scraper/`, `apps/inverter/` and `apps/dashboard/` subprojects plus
the shared `common/` package, `shared/`, `docker/` and `scripts/`. Method:
manual code review of every module (wire handling, control servers, CLIs,
config/token/dump loading, audit trail, metrics endpoints, Nix/Docker
deployment) against the NIS2 (EU 2022/2555, art. 21.2) and DORA
(EU 2022/2554, art. 8–14) control checklists, plus targeted offline
verification of the suspicious paths found. This is a design-and-code audit,
not a penetration test. The `apps/inverter/` fake is a test device simulator —
its risk class is "developer/demo infrastructure", not production OT;
findings there are weighted accordingly. Findings keep their numbers across
revisions; the open ones are in § 8.1 — every closed finding's fix and
verification, and the per-revision walk, live in
[history/AUDIT.md](history/AUDIT.md) (next number: F24). Rev. 28 is the
consolidation: docs/AUDIT.md became this file and absorbed the four tool
READMEs' Security sections; the F-ledger itself is unchanged since rev. 27.

## 1. Reporting a finding

Found something? Open a security advisory on the repository (the GitHub
Security tab) instead of a public issue. The suite is homelab-grade and
answers are best-effort; the audit re-runs after every new listener or file
format, and at least yearly otherwise (§ 11).

## 2. The posture in one screen

- **Refuse by default** — writes quadruple-gated and closed; TCP control
  refuses to start without a token; every HTTP surface refuses a
  non-loopback bind without a token (the fake exempt by posture, § 5).
- **Loopback by default** — every listener binds 127.0.0.1; widening the
  bind is a deliberate act.
- **Authenticating** — bearer tokens (constant-time), the signed wire
  (HMAC both directions wherever a token is held), peer-cred on the unix
  control sockets, the read-only ops role, the PVA1 suite handshake on the
  Modbus hops.
- **Capped** — per-IP and total connection caps on every serving surface,
  MBAP/read-count/line bounds, the wire paths fuzzed.
- **Accountable** — the append-only, hash-chained audit trail with the
  off-box forward; secrets never log and never render.
- **Hard to ship wrong** — stdlib only, 0600 token files enforced by the
  shared loader, explicit socket modes, hardened systemd units,
  unprivileged containers that drop root before exec.

## 3. Assets and trust boundaries

| Directory | What | Trust boundary / controls | Findings |
|---|---|---|---|
| `/cache` | the Modbus caching proxy: the daemon + the cli client, the proxy/cache/upstream/control/metrics/persist/config libs, man/, the sample conf (the NixOS module lives in `nixos/modules/`) | the production-relevant surface: two listeners (Modbus TCP + control), `/metrics`, the state dump, the audit trail; the write path quadruple-gated (the parse gate, `allow-write` off, `write-acl` none, `write-registers` none); `acl/connect`/`acl/write`/`metrics/acl` IP gates (the inline grammar or the standalone ip-prefix acl file); the dump is config-equivalent trust at rest | F2–F5, F8, F18, F23 closed here; F1 accepted |
| `/common` | the shared package: `runtime/audit.py` (the append-only trail + the chained hashes), `settings/config.py` (listen/profile resolution, token loading + the 0600 gate, the shared IP-gate half), `serve/connlimit.py` (the caps + the `acl_allows`/`acl_refused` hooks), `wire/cred.py` (peer-cred), `wire/wiresec.py` (the RBAC roles), `modbus/protocol.py`, `render/human.py`, `runtime/logutil.py`, `runtime/version.py` | trust amplifier: every tool inherits its guarantees; a regression is family-wide — the regtests + the audit-chain suite watch it | F10, F12 closed here |
| `/dashboard` | the web front: the server + the cli client, the HTTP handler + the Prometheus proxy, the control server, config, static/ | the viewer surface: GET-only HTTP (the realpath-guarded static tree, the proxy under `--prom-prefix`) with the family connection gate and the bearer token mandatory beyond loopback (F21, the `?auth=` cookie bootstrap); the family control server (the F5 refusal, peer-cred, the signed wire, the DSH trail); the default bind loopback; its own `/metrics` rides the family stack | F20, F21 closed |
| `/docker` | one alpine image per tool, the Prometheus image, the two entrypoints, the compose demo | the network is the boundary: one `internal: true` network, nothing published on the host; the images run unprivileged (`pvsuite`, `prometheus`); root exists only for the volume seeding and drops before exec; the bundled `*.token` defaults materialize as random 0600 values | F7 closed; F17 open |
| `/inverter` | the fake: the daemon + the cli client, the simulator/machines/control/metrics libs, man/ | a test instrument on a trusted LAN: the Modbus surface capped (`max-clients`/`client-timeout`/`max-conn-per-ip`, live-settable) and connect-ACL'd (inline grammar only), the read-count gate, `/metrics` optional on the family stack; the family control listener (tokenless TCP by posture — F11); deliberately not security-first, documented as such | F11 closed; F1 accepted |
| `/profiles` | the device profiles (JSON data: sun2000 + sun2000_full + demo-fc4 + three Deye variants), home `shared/profiles/` in the tree | data, not code: the loader validates every entry (type/width/scale, bounds), the search path is closed, the linter checks schema/overlaps/bounds — treat a profile file like config | none |
| `/scraper` | the exporter: the daemon + the cli client, the server/scraper/poller/control/config libs, man/, the sample conf (the alert rules pack lives in `extras/alerts/`) | the read-only consumer: one HTTP GET route set (bearer-gated, capped, `metrics/acl`, the non-loopback refusal) + one outbound Modbus client (FC3/FC4 reads only); the family control server; the SIGHUP reload re-validates everything | F13, F16, F20 closed; F14 open |
| `/scripts` | `release.py` (the release orchestrator) + `audit_verify.py` (the F10 chain verifier) | maintainer-local trust: the dirty-tree and main-only guards, the full-suite verify, then commit/tag/push; the GH release is the workflow's job; the tag is the trust root, signed when a key exists | F19 closed |

`flake.nix` (the packaging, the NixOS modules) and `tests/` (the
verification suites cited in §4) are part of the story but hold no runtime
trust of their own.

| Surface | apps/cache/ | apps/scraper/ | apps/inverter/ | apps/dashboard/ | Auth |
|---|---|---|---|---|---|
| Modbus TCP listener | `--listen`, default `127.0.0.1:15502`; `connect-acl` on top | n/a (outbound only) | `--listen`, default `127.0.0.1:5502` (Docker `0.0.0.0:5502`); the connect-acl (inline grammar only) | n/a | none (protocol-inherent, F1) |
| HTTP surface | `/metrics`: `--metrics-server` (live-settable), off; `--metrics-listen` default `127.0.0.1:9351`; `metrics/acl` at accept | the exporter: `--listen` default `127.0.0.1:9350`, two GET routes (`/`, `/metrics`), `Cache-Control: no-store`, `metrics/acl` at accept | `/metrics`: `--metrics-server`, off, default `127.0.0.1:9352`; `metrics/acl` at accept | page + proxy: `--listen` default `127.0.0.1:8080`, GET-only, the realpath-guarded static tree; own `/metrics` default `127.0.0.1:9353` | bearer token (`hmac.compare_digest`) mandatory beyond loopback on every HTTP surface (F13/F21); the loopback bind serves tokenless; `metrics/acl` sits at accept ahead of the caps — never instead of the token |
| control server (JSON lines) | unix `/tmp/modbus-cache-<port>.socket`, `0600` after bind (`0660` with `--control-socket-group`); `--control-port` = TCP on 127.0.0.1, **refuses to start without a token** | unix `/tmp/modbus-scraper-<port>.socket`, same | unix socket, same; the TCP control exempt (F11 — a tokenless rebind succeeds live) | unix `/tmp/dashboard-<port>.socket`, same; **refuses tokenless TCP** | ONE listener tier for the family (`common/wire/control.py`): token on TCP (refused without — at start AND on the live rebind), peer-cred on unix (root, the daemon's own user, `--control-trust-uids`), the signed wire wherever a token is held, the live `control/port` rebind (bind-first, the failed bind rolls back, the sessions keep serving) |
| state dump | `--dump-path`: the setting overrides (plus the cached words on `with-cache`) as one atomic JSON | n/a | n/a | n/a | created `0600` explicitly + a sha256 integrity hash, fail-closed restore (F18); sealed under `dump/key` when set |
| token files | every secret knob takes `file:<path>` | same | same | same | owner-only (0600) enforced at the shared loader (F12); the bare `-file` siblings are gone — `file:` is the one spelling |
| upstream connection | outbound to the inverter/SDongle | outbound poll (the device or the cache), every 10 s by default | n/a (it *is* the device) | outbound HTTP to Prometheus (`--upstream`, default `http://localhost:9090`) | none (protocol-inherent) |
| audit trail | CACHE / CLI / CTL — XDG state home or stdout, append-only, rotated, control-character-folded | SCR / CLI / CTL, same | INV / CLI / CTL, same | DSH / CLI / CTL, same | the per-writer hash chain, verified by `scripts/audit_verify.py` (F10); the opt-in forward mirrors every line to the local syslog or the off-box collector (the `udp://`/`tcp://` grammar, the RFC5424/CEF envelopes, the remote-only mode) |
| compose demo stack | five services on one `internal: true` network, **nothing published on the host**, one shared `config` volume, the generated 0600 `metrics.token` | | | | the internal network is the boundary; the exporter bearer-gated in the demo (F7) |

Deployment (docker/): all three Modbus images run the tool as the
unprivileged `pvsuite` user on alpine; the shared entrypoint runs as root
**only** to seed the `/config` volume (bundled defaults copied in, existing
files kept, `*.token` materialized as random 0600 values) and drops to
`pvsuite` via `su-exec`; the Prometheus image follows the same pattern.

The scraper is the read-only consumer: no write path, no state-changing
verbs — its attack surface is one HTTP GET route set, the control server
(the family auth) and one outbound Modbus client (FC3/FC4 reads only); the
control verbs stop at the exporter. The cache's write path is the only
state-changing Modbus surface and is gated four times (the fail-closed parse
gate; `--allow-write` off by default; `write-acl` — **none by default**; the
register allow-list `write-registers` — **none by default**), so enabling
`--allow-write` alone still refuses every write. The fake's write path is
the intended demo feature, gated by control-server access only.

## 4. Implemented controls (all modules)

- **Access control** — the four independent write gates
  (`proxy.py` `respond()`); control TCP requires the token and a token-less
  TCP control refuses to start (F5) on every tool that serves one (the fake
  exempt on purpose, F11) — the ONE guard the family's live rebinds call
  (`common/wire/control.py` `refuse_tokenless_rebind`/`refuse_token_drop`); the
  peer-cred path authenticates kernel-vouched peers without the secret
  (`common/wire/control.py` `trusted_peer`, `common/wire/cred.py`);
  wherever a token is held the
  wire is signed both directions (`common/wire/wiresec.py`, constant-time
  `hmac.compare_digest`); the read-only ops role scopes its sessions to
  its policy's verbs (the default derives from the registry's command
  rows: show, plus clear where the grammar speaks it), gated once in
  `role_allows`, audited
  `role=ops`/`role=admin` (F22); `metrics-acl` at accept ahead of the caps
  (`common/serve/connlimit.py` hooks, `common/settings/config.py`
  `acl_admits`); all
  non-Modbus listeners default 127.0.0.1 and speak the F13 token shape
  beyond it.
- **Input validation** — MBAP length capped in every reader; read counts
  capped (1–125, address bounds); the pre-auth control line buffer drops
  the connection past 1 MB (F4); unparseable write frames refused, not
  forwarded (F3); config/ACL/token/profile/dump parsers fail fast with
  one-line messages, never partial state.
- **Secrets handling** — tokens never logged; every secret value takes
  `file:<path>` (the shared loader enforces owner-only 0600, F12; the bare
  `-file` siblings are gone); the token-flag `ps` exposure documented
  in every README and man page (F9); the Nix modules warn when a token
  would render into the world-readable store; all secrets are
  startup-only (a secret never takes a live set — the restart is the
  rotation).
- **Logging / audit** — append-only, flushed, thread-safe, size/daily
  rotated (`common/runtime/audit.py` — one writer family-wide);
  writes, refusals,
  auth-fails, control commands and lifecycle events recorded; control
  characters folded at the writer so one event is one physical line (F2);
  an empty-valued word never lands — a `key=` token with no value, bare or
  quoted-empty (`key=''`), is dropped at the writer (the pair is absent, not
  empty);
  falls back to stdout (journald). The line grammar is FLAT KV:
  `<stamp> AUDIT application=<TAG> tag=<writer> instance=<id> type=<type>
  hash=<12-hex> [<detail kv words>]` —
  `application=<TAG>` is always uppercase and names the tool (the daemon's own tag
  from `shared/suite/tags.json`), `tag=` names the writer — the daemon's own
  `daemon` or the ctl and cli clients' shared `cli` —, `instance=` names the
  writer's daemon (the control port when `--audit-instance` is unset, the
  override when spelled; the clients spell their target's port), and every
  word after `hash=` is the event's detail — `key=value` pairs, no wrapper
  word (a value carrying a space wears single quotes around the WHOLE value —
  `cmd='set pv 3000'`, `peer='unix socket'`; the builders' `audit_quote`; inside
  the quotes `\`, `'` and `"` ride backslash-escaped — `it\'s`, the builders'
  `audit_escape`, one un-escape rule for the parsers; a bare (unquoted) value
  carries no escapes; a
  free-text phrase rides as the quoted VALUE of a named key — `reason=`,
  `error=`, `warn=` — there is no generic prose slot), the
  command's `result=ok|err|bye|local|aborted` and — when the exchange was
  signed — its `wire=h<12-hex>` mac proof ride beside it, and the wire-policy
  refusals name themselves (`reason=unsigned` / `reason=bad-mac`). The keys
  are unique: the five outer words (`application`/`tag`/`instance`/`type`/`hash`)
  are reserved — a detail word spelling one never lands (the writer drops it) —
  and no key repeats.
  The outer keys:

  | key | value |
  |---|---|
  | `application=` | the tool's tag, always uppercase — the `shared/suite/tags.json` spelling (`CACHE` / `SCR` / `INV` / `DSH`) |
  | `tag=` | the writer role: `daemon` (the service's own trail) or `cli` (the ctl and cli clients, one role) |
  | `instance=` | the writer daemon's identity: the control port (the derived default) or the `--audit-instance` override — the chain groups by it |
  | `type=` | the event type, lowercase — see the table below |
  | `hash=` | the entry's chained hash (12 hex) |

  The detail keys per type (every type speaks KV — no key repeats; a value
  carrying a space rides single-quoted):

  | type | message keys |
  |---|---|
  | `start` | `version`, `upstream` (the fake: `modbus`), `unit`, `listen`, `control`, `profile` (the cache and the fake), `description` (the fake) |
  | `shutdown` | `reason` (`control-command`, `sigterm`, …), `uptime` — plus the tool's counters: `clients`/`hits`/`misses` (the cache), `errors` (the scraper), `conns`/`requests`/`chaos_hits` (the fake) |
  | `command` | `peer`, `role` (the session's RBAC role, when authenticated), `cmd` (single-quoted), `wire` (the frame mac's 12-hex head, when signed), `result` (`ok`/`err`/`bye`), `reason` (the wire-policy refusals only: `unsigned` / `bad-mac`) |
  | `connect` / `disconnect` | `target`, `user` (the clients' session trail); the keepalive watcher's daemon-exit disconnect spells `reason=daemon-exit` |
  | `reconnect` | `attempt`, `total`, `status` (`ok`/`failed`/`gave-up`), `error` (when failed) |
  | `auth-fail` | `peer` |
  | `requests` | `peer`, `requests`, `window`, `recent` (the cache's per-window evidence) |
  | `write` | `fc`, the target (`register`/`coil` or the `registers=`/`coils=` `addr:count` span), `value`/`values`, the mask write's `and`/`or`, the FC23 `read` span, `unit` — `common/modbus/writes.py write_kv` |
  | `write-refused` | the write's words plus `reason` (`too-short`/`write-disabled`/`not-on-write-acl`/`outside-allow-list`/`malformed-frame`), `client` (the ACL refusal), `error` (the shape error) |
  | `write-rejected` | the write's words plus `exception` (the device's modbus exception code) |
  | `write-failed` | the write's words plus `error` (the transport failure) |
  | `reset` | `signal` (`SIGUSR1`), `dropped` (the cache) / `pins`, `coils`, `overlay` (the fake) |
  | `reload` | `result` (`ok`/`err`), `error` (when err); the payload keys: `ranges`+`profile` (the cache), `settings`+`changed` (the fake), `upstream` (the scraper, the dashboard), `restored`+`file` (the state-file restore), `action=exec`+`pid` (the re-exec) |
  | `restore` | `file`, `words`, `settings` (the cache's state dump) |
  | `acl-file` | `warn` (the file's permission posture, single-quoted) |
- **Audit forwarding** — the trail's defense is three tiers: the local
  chain (the file of record, per-writer hashes, `scripts/audit_verify.py`),
  the local journald mirror and **the off-box copy** — `--audit-forward`
  spells one target: `none`, `syslog` (the local socket auto-scan),
  `syslog:/path` (an explicit socket, must exist at bind), `udp://host[:514]`
  (RFC5426 datagrams, best-effort — drops show as the per-prefix chain-hash
  gaps at the collector) or `tcp://host[:514]` (RFC6587 octet-count
  framing). The remote envelope rides `--audit-forward-format` (`rfc5424` —
  the default — or `cef` as an additive wrapping); both carry the native
  line verbatim (the chain verifies identically at the collector) and the
  prefix + chain hash as extracted fields (`[pvDash@1 …]` / `cs1`/`cs2`),
  so a scheduled search can run the chain-verify logic off-box and **alert
  on a chain break** — tamper-evidence becomes one that pages you. A send
  failure closes the mirror with one stderr note and the next event re-arms
  lazily (no threads, no buffers). Startup gates split: grammar errors and
  a missing explicit socket are hard (ERROR + rc 1), a remote target that
  does not resolve or refuses is soft (a warn, the lazy re-arm carries it —
  boot ordering never blocks the Modbus surface). `--audit-log none` turns
  the local file off: with a forward spelled that is the **remote-only
  mode** (the collector is the sole holder — no file, no XDG directory, the
  chain reseeds at GENESIS per run), without one the audit is disabled (the
  state `--no-audit-log` spells). TLS transport is deliberately out (the
  docs/TODO.md anchor).
- **State dump handling** — written atomically, read defensively (a foreign
  or truncated file restores nothing); settings-only by default (the words
  on `with-cache`); restored overrides re-validate through the live
  dispatch; created `0600` explicitly + the integrity hash, fail-closed
  (F18); the reload state files ride the same writer/reader at 0600
  explicit (F23); sealed under `dump/key` when set (a wrong key
  fails closed as tampered; a keyed restore refuses an unsealed dump and
  vice versa).
- **Supply chain** — stdlib-only, zero third-party dependencies; Nix-pinned
  builds; the shared `common/` package narrows the review surface instead
  of widening it.
- **Platform hardening** — systemd `DynamicUser` (or the named static
  account — the family's shared `pvsuite` identity), `NoNewPrivileges`,
  `ProtectSystem=strict`, `PrivateTmp`, `LoadCredential`; explicit socket
  modes after bind, never the umask (F8); unprivileged containers, root
  dropped before exec; the compose demo internal-only and publishes nothing
  (F7).
- **Resilience** — reconnect with split-on-failure polling, per-leaf fault
  isolation, write-through invalidation, `flush cache`/`restart`/`reset`
  verbs; the state dump as the write-behind for a gated restart; fuzz and
  stress suites exercise the wire paths.
- **Scraper request surface** — a missing/invalid bearer answers 401 with
  `WWW-Authenticate: Bearer`, compared constant-time, logged at WARNING;
  exactly two GET routes, everything else a 404; `Cache-Control: no-store`;
  `--metrics-max-clients` sheds excess clients with 503; the fixed-rate poll loop
  means request floods cannot reach the device.
- **Dashboard HTTP surface** — GET-only and closed by construction: the
  static tree served from one realpath-checked root (403 on escape), the
  proxy a plain GET forward onto the upstream, the family connection gate
  over the whole surface; the bearer token on page and proxy (the header,
  the session cookie, the `?auth=<token>` bootstrap), the default bind
  `127.0.0.1`, a token-less non-loopback bind refuses to start (F21).

## 5. The four tools

**modbus-cache** — the production-relevant surface. Modbus TCP as spoken by
the SUN2000 inverter has no auth, no encryption and no access control:
anyone who can reach the listen port can read. The proxy therefore binds
127.0.0.1 by default; widen the bind deliberately, keep it on a trusted
LAN, and don't expose it to the internet. The ACLs add per-source control
within the LAN; for stricter isolation use the firewall. The write path is
gated four times and defaults fully closed — enabling `--allow-write`
alone still refuses every write (§ 3, § 4).

**modbus-scraper** — the privacy note is the scraper's security story
(F15): the endpoint exposes production values, not telemetry — the current
PV generation, the home consumption, the battery state of charge and the
per-phase voltages/currents. A week of that is a home-occupancy profile —
when the house is producing, when it draws, when nobody is home. The
controls are the bearer token (mandatory beyond loopback — a token-less
non-loopback bind refuses to start, F13) and the localhost bind (the
default). Treat the endpoint as internal: do not publish it, and scope any
reverse proxy that frontends it.

**dashboard** — the F21 story is the bind's: loopback is open, the LAN
needs the bearer token (a token-less non-loopback bind refuses to start),
and TLS terminates at an authenticating reverse proxy. The page is fully
offline (the vendored ECharts is the one dependency) and the audit trail
records the control plane; static-only deployments expose the bare page —
put auth in front.

**modbus-fake-inverter** — a test instrument on a trusted LAN, deliberately
*not* security-first design (F11): the Modbus surface speaks to any peer
that can reach the port, `/metrics` serves without a token unless
`--metrics-token` is set, and the control plane is plain-text by posture —
a demo harness. The blunt mitigations are shipped: the caps, the
read-count gate against oversized replies, the optional `--modbus-auth
suite` handshake and the `--metrics-acl` IP gate for demos that want them.
Synthetic data only — nothing served is measured from a real device; there
is no PII and no production telemetry to protect.

## 6. Deployment hardening

The docker images run the tools as the unprivileged `pvsuite` user on
alpine; the shared entrypoint runs as root **only** to seed the `/config`
volume (bundled defaults copied in, existing files kept, `*.token`
materialized as random 0600 values) and drops to `pvsuite` via `su-exec` —
root exists for the seeding, never for the exec. The compose demo sits on
one `internal: true` network and publishes nothing on the host; the prod
stack fronts real hardware with your own external collector. The
topologies and the env-file rules: [../docker/README.md](../docker/README.md).

The NixOS modules sandbox every service (`DynamicUser` — or the named static
account, the family's shared `pvsuite` identity — plus `NoNewPrivileges`,
`ProtectSystem=strict`, `PrivateTmp`, `LoadCredential` and the
`SystemCallFilter`/`RestrictAddressFamilies` set), verified with
`systemd-analyze security` (a score per unit asserted by
`nixos/tests/hardening.nix`); the option map, the secrets discipline and the
reload/restart story: [../nixos/README.md](../nixos/README.md).

## 7. Supply chain and ACLs

The suite is **Python stdlib only** — no pip, no venv, no vendored Python
packages, no runtime network fetches. The third-party surface is exactly
three items wide: the Python interpreter, the container base images (where
docker is used) and the dashboard's vendored ECharts. The machine-readable
claim (CycloneDX), import-scan-gated and release-checked:
[sbom/SBOM.md](sbom/SBOM.md).

The two ACL planes — who may reach a listener (the IP plane) and which
registers a forwarded write may touch (the register plane) — speak one
gate-object schema with two matcher kinds; the grammar, the per-tool knobs
and the enforcement map: [common/ACL.md](specs/ACL.md). The control-plane
auth is NOT an ACL: the tokens, the RBAC ops role and the `trust-uids`
list decide who may drive the control socket (§ 4), and the Modbus
`modbus-auth` handshake is a wire-level proof between peers
([common/MODBUS.md](specs/MODBUS.md)).

## 8. Findings

### 8.1 Open findings

| # | Module | Severity | Finding | Recommendation |
|---|---|---|---|---|
| F1 | cache, scrape, inverter | HIGH (accepted, protocol-inherent) | Modbus TCP carries no authentication and no encryption — listener and upstream alike; a compromised inverter LAN segment can feed the scraper bogus register values (sanity-capped). | keep the listener off the WAN (the default binds 127.0.0.1), set the connect ACL on a LAN, keep `--allow-write` off (the write path defaults fully closed). |
| F14 | scrape | LOW | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics travel in clear text. | terminate TLS in a reverse proxy when anything beyond localhost needs the endpoint. |
| F15 | scrape | INFO | The metrics expose production values (generation, consumption, battery SoC) — a home-occupancy privacy consideration. | the bearer token (F13) + the localhost bind are the controls; treat the endpoint as internal. |
| F17 | docker | INFO | The `/config` volume holds live config in plaintext; the entrypoint seeds copies once (existing files are never refreshed); the generated `metrics.token` lives in the same volume. | prefer token files outside the volume / `LoadCredential` / secret-backed mounts; document `docker compose down -v` as the re-sync. |

### 8.2 Closed

Every closed finding — F2–F13, F16, F18–F23 — with its fix, its
verification and the per-revision walk (rev. 1–31):
[history/AUDIT.md](history/AUDIT.md).

## 9. Verification

All ten suites print ALL PASS on the revised tree; `nix flake check`,
`scripts/check_options.py` + `scripts/lint/options.py --check` clean; the
man pages regenerate (`mandoc -Tlint` clean). The per-finding verification
and the per-revision walk-throughs: [history/AUDIT.md](history/AUDIT.md).

## 10. NIS2 / DORA mapping (all modules; cache is the production-relevant one)

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(a) risk-management policies | yes (scoped) | defaults-as-security documented (the quadruple-gated writes, localhost binds, tokens mandatory on control/metrics, 0600 token files); this audit is the written analysis |
| NIS2 21.2(b) incident handling | yes (scoped) | the audit trail + journald retention, tamper-evident (F10 closed), the off-box forward + the alert rules pack riding the exporter — the detection is wired, not just logged (F16 closed) |
| NIS2 21.2(c) business continuity | yes | reconnect/backoff, per-leaf isolation, restart/reload/reset verbs, the gated write-behind dump |
| NIS2 21.2(d) supply chain | yes | stdlib-only, pinned Nix builds; the shared `common/` core |
| NIS2 21.2(f) effectiveness | partial | fuzz/stress/regression suites; the suites run in the tag-triggered release workflow's matrix, no push/PR CI yet |
| NIS2 21.2(g) cyber hygiene / crypto | partial | constant-time compares, LoadCredential, owner-only token files, no secrets in logs; no TLS (F1 protocol-inherent, F14 proxy) |
| NIS2 21.2(h) access control / MFA | yes (scoped) | the four write gates (two defaulting to none), the ACLs with restrict-all modes, token-mandatory control (the fake exempt, F11), the metrics token mandatory beyond loopback (F13), the `metrics/acl` accept-time IP gate, per-IP + total caps on every serving surface, peer-cred, the signed wire, the read-only ops role (F22); MFA not applicable to a machine protocol |
| DORA art. 8 ICT asset identification | yes | every option logged at start; `inspect` dumps the full state; the demo topology documented |
| DORA art. 9–10 protection/prevention | yes | the write gates, ACLs, capped framing/buffers, fail-closed writes, token-mandatory surfaces, the caps, explicit socket + token-file modes, fail-fast validation; the dashboard's GET-only route set with the traversal guard and the bearer gate (F21) |
| DORA art. 11 detection | yes | the trail's integrity defensible (F2) and evident per entry (F10); auth-fail/refusal events; the alert rules pack wired (F16 closed) |
| DORA art. 12 BCP | partial | restart/reload/clear verbs, the dump/restore write-behind; no automated failover (single-device by design) |

Scraper deltas (rows where scrape matches are omitted): incident handling —
unauthorized-request logging at WARNING; effectiveness — the fuzz suite,
the release workflow's matrix legs; crypto/hygiene — the constant-time
bearer compare, no TLS
(F14); access control — the bearer gate + the non-loopback refusal (F13),
`metrics/acl`, the caps; DORA 9–10 — the localhost default, the two-route
whitelist, DoS caps on both the HTTP and poll sides; DORA 11 — yes (the
alert rules pack rides the exporter, F16 closed); DORA 12 — yes (read-only,
stateless, restart-clean; Prometheus holds the history).

Dashboard deltas (rows where the dashboard matches are omitted): incident
handling — the DSH trail (chained) + the wire macs; effectiveness —
`tests/dashboard-control-fuzz.py`, the release workflow's matrix legs;
crypto/hygiene — the
constant-time compares (control + page/metrics bearers), the signed wire,
no TLS (F14); access control — the family-hardened control plane + the
bearer gate on the HTTP surface (F21); DORA 9–10 — partial (the closed
route set, the caps, the bearer gate; no TLS); DORA 11 — partial (no
request-level access log by default, `--log-access`); DORA 12 — yes (a
stateless viewer, restart-clean; Prometheus holds the history).

## 11. Verdict

The posture is sound for the deployment class the tools target (an
operational/home LAN behind segmentation): refuse-by-default writes (closed
by default even beyond `--allow-write`), localhost binds by default with the
F13 token shape beyond loopback on every HTTP surface, `metrics/acl` at
accept ahead of the caps, token-mandatory TCP control (the fake exempt by
documented posture), per-IP and total connection caps on every serving
surface, constant-time token checks, peer-cred on the unix control sockets,
length-disciplined wire parsing with capped buffers, a tamper-evident audit
trail with the off-box forward, explicit socket modes and owner-only token
files instead of umask
hope, zero dependencies, hardened systemd units and unprivileged containers
whose entrypoints drop root before exec, and a compose demo stack that
publishes nothing.

The remaining open set is the documented trust decisions and deployment
stories: F1 accepted (Modbus TCP itself — mitigate with segmentation and
the write gates); F14/F17 operational (TLS at a proxy, the volume
story); F15 informational. Re-run this audit after
the TLS story (F14) lands, after the multi-target / control-plane
evolutions, or any new listener or file format; at least yearly otherwise.
