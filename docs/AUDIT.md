# Security audit — the pv-suite tree: /cache, /common, /dashboard, /docker, /inverter, /profiles, /scrape, /scripts (rev. 6)

Scope: the `cache/`, `scrape/` and `inverter/` subprojects plus the shared
`common/` package and the `docker/` images. Rev. 1 audited the post-refactor
tree after `2db6cfa` (absorbing the former per-subproject `secaudit.md`s);
rev. 2 re-audited at main after `84b4387` — the tree that carried the
state-persistence wave (`--dump-path`/restore, `lib/persist.py`), the
peer-cred control auth (`common/cred.py`, `--control-trust-uids`), the
F2–F8 fixes, the audit-vocabulary rename (`READS` → `REQUESTS`) and the
scraper's profile-`fc` awareness. **Rev. 3** re-audited the tree that added
three waves:

- the **demo-stack hardening and completion** (finding F7): the compose
  stack publishes nothing and wires the services onto one `internal: true`
  network; a Prometheus service joins the demo with the scrape/token story
  (the exporter's bearer token is generated into the shared config volume);
  the plain `docker run` examples bind to loopback only;
- the **token discipline** (findings F9, F12): token flags documented as
  the quick-test form (they land in `ps`), token files enforced owner-only
  (0600) at every loader;
- the **write-default hardening** (a posture change, not a finding): the
  cache's `write-acl` and `write-registers` default to **`none`** —
  the write path is closed even after `--allow-write` until the operator
  opens the ACL and the register allow-list — and both ACLs and the
  allow-list grew a `none` (restrict all) mode; `connect-acl` grew `none`
  too (its default stays `any`). The default poll/scrape cadence across
  the family is 10 s.

**Rev. 4 re-audits the tree that adds the caps-and-integrity waves on top:**

- the **fake's surface capped** (finding F11, closed as recommended): the
  inverter's Modbus listener got the cache's `--max-clients` /
  `--client-timeout` (both live-tunable, `show connections` to watch
  them), the read-count gate (exception 03 past the 125-register cap) and
  the trusted-LAN / not-security-first documentation;
- the **connection caps everywhere** (findings F11 and F13): every serving
  surface — the two Modbus listeners and all three `/metrics` endpoints —
  grew per-IP and total connection caps (`common/connlimit.py`, one
  implementation; the metrics masters are the live-settable
  `metrics-server`, the bind address `--metrics-listen HOST:PORT`); the
  scraper refuses a non-loopback `/metrics` listen without a token (F13);
- the **trail integrity** (finding F10): every audit entry carries a short
  chained hash — per writer prefix, restart-seeded, rotation-spanning —
  verified by `scripts/audit_verify.py`;
- the **dump trust** (finding F18): the cache's state dump is created 0600
  explicitly and integrity-hashed; the restore fails closed (a tampered,
  unsigned or group-writable dump refuses); the dump itself splits by
  content — settings only by default, the cached words on
  `request dump with-cache` / `--dump-with-cache`.

Method is unchanged: manual code review of every module (wire handling,
control servers, CLIs, config/token/dump loading, audit trail, metrics
endpoints, Nix/Docker deployment), against the NIS2 (EU 2022/2555, art.
21.2) and DORA (EU 2022/2554, art. 8–14) control checklists plus targeted
offline verification of the suspicious paths found. This rev. 4 pass added
a focused review of the new shared surfaces (`common/connlimit.py`, the
audit chain in `common/audit.py`, the hardened `cache/lib/persist.py`, the
gated HTTP servers) — no new findings; the removed `--metrics-port` flags
fail loudly at argparse (a silently-ignored flag would drop config). This
is a design-and-code audit, not a penetration test. The `inverter/` tool
is a test device simulator: its risk class is "developer/demo
infrastructure", not production OT — findings there are weighted
accordingly. Findings keep their numbers across revisions; the ones closed
stay listed in §3.1 with their fix and verification, open ones in §3.2
(as of this revision the next number was F20).

**Rev. 5 closes F19** (the release gate ordering, found by the rev. 4 walk
of `/scripts`): the GitHub release is the **workflow's** job — the
tag-triggered workflow's `release` job already gated on
`needs: [test, build]` — so the orchestrator's local cut becomes the
explicit opt-in (`--release`, printed with a bypass reminder), the local
verification defaults to the **full suite** (`--tests full`, was `quick`)
and the tag is **signed** (`git tag -s`) whenever a signing key exists
(the unsigned annotated tag is the documented fallback, so the trust-root
caveat stays visible). On the way the release flight itself got flight-
tested: the bump's old-version check no longer dies on `git grep`'s
no-matches exit code, and a dry-run prints the plan without pretending the
suites ran. This rev. 5 pass re-read `scripts/release.py` end to end and
the workflow — no new findings; the open set is unchanged.

**Rev. 6 closes the deferral: the audit now covers the whole pv-suite,
`/dashboard` included.** Three waves since rev. 5 were walked: the
**scraper's control plane** (the last family tool without one — the
JSON-lines server on the cache's pattern: the unix socket `0600` after
bind, the token'd TCP with the F5 refusal, peer-cred, the signed wire,
the SCR trail, `scraper_ctl`/`scraper_cli`), the **dashboard's control
plane** (the same family shape — the unix socket, the F5 refusal,
peer-cred, the signed wire, the DSH trail, `dashboard_ctl`/`dashboard_cli`)
and the **dashboard's HTTP surface** (the static page + the Prometheus
proxy: GET-only, the connection caps, the traversal-guarded static tree —
served **without authentication**, raised as **F21**). The walk also found
**F20**: the ctl/cli help and the READMEs promised the token-file env
vars (`MODBUS_CACHE_CONTROL_TOKEN_FILE`, `SCRAPER_CONTROL_TOKEN_FILE`,
`FAKE_CONTROL_TOKEN_FILE`/`FAKE_METRICS_TOKEN_FILE`,
`DASHBOARD_CONTROL_TOKEN_FILE`) and the clients never read them — a
documented control that does not exist; closed in the same wave (one
resolution shape family-wide). The release gate's suite list had drifted
from the repo's suite set (the full gate ran eight of the ten suites —
the inverter regtest and the audit-chain suite were missing); fixed here
and recorded in §4.

Method is unchanged: manual code review of every module (wire handling,
control servers, CLIs, config/token/dump loading, audit trail, metrics
and HTTP endpoints, Nix/Docker deployment), against the NIS2 (EU 2022/2555,
art. 21.2) and DORA (EU 2022/2554, art. 8–14) control checklists plus
targeted offline verification of the suspicious paths found. This rev. 6
pass re-read the four control servers against each other (one family
shape, four copies), the shared surfaces (`common/connlimit.py`'s gate on
the new HTTP server, the audit chain across the new DSH/SCR prefixes) and
the dashboard's `lib/config.py` resolution (fail-closed, the F12 modes on
every reload path). This is a design-and-code audit, not a penetration
test. The `inverter/` tool is a test device simulator: its risk class is
"developer/demo infrastructure", not production OT — findings there are
weighted accordingly. Findings keep their numbers across revisions; the
ones closed stay listed in §3.1 with their fix and verification, open
ones in §3.2 (next number: F22).

Scope: the whole tree, directory by directory — `/cache`, `/common`,
`/dashboard`, `/docker`, `/inverter`, `/profiles`, `/scrape` and
`/scripts` (the inventory in §1). `/tests` is the verification evidence,
not a runtime asset. Findings keep their numbers
across revisions; the ones closed stay listed in §3.1 with their fix and
verification, open ones in §3.2 (next number: F22).

## 1. Assets and trust boundaries

### The audited tree, directory by directory

| Directory | What | Trust boundary / controls | Findings |
|---|---|---|---|
| `/cache` | the Modbus caching proxy: bin/ (the daemon + the ctl/cli clients), lib/ (proxy, cache, upstream, control, metrics, persist, config, settings), man/, the ini sample, the NixOS module | the production-relevant surface: two listeners (Modbus TCP + control), the metrics endpoint, the state dump, the audit trail; the write path quadruple-gated (the parse gate, `allow-write`, `write-acl` none, `write-registers` none); the dump is config-equivalent trust at rest | F2–F5, F8, F18 closed here; F1 accepted |
| `/common` | the shared package every tool imports: `audit.py` (the append-only trail + the chained per-writer hashes), `config.py` (parse_listen, is_loopback_host, the profile resolution, the token loading + the 0600 enforcement), `connlimit.py` (the connection gates), `cred.py` (peer-cred), `protocol.py` (recv_exact, exception frames), `human.py`, `logutil.py`, `version.py` | trust amplifier: every tool inherits its guarantees (the fail-closed token modes, the wire discipline, the fold at the audit writer, the admit/release symmetry); a regression here is family-wide — the regtests + the audit-chain suite watch it | F10, F12 closed here |
| `/dashboard` | the web front: bin/ (the server + the ctl/cli clients), lib/ (the HTTP handler + the Prometheus proxy, the control server, config, settings, the static constants), static/, man/ | the viewer surface: GET-only HTTP — the static page (a realpath-guarded tree, 403 on escape) and the Prometheus proxy under `--prom-prefix` — with the family connection gate (`--max-clients`/`--client-timeout`/`--max-conn-per-ip`, extras 503); the JSON-lines control server in the family shape (the F5 refusal, peer-cred, the signed wire, the DSH trail, the socket `0600` after bind); **no HTTP authentication yet — F21** (binds `0.0.0.0` by default; the loopback/reverse-proxy deployment is documented) | F20 closed (the clients); F21 open |
| `/docker` | one alpine image per Modbus tool, the Prometheus image, the two entrypoints (the `/config` seeding + the token handoff), the compose demo | the network is the boundary: one `internal: true` network, nothing published on the host; the images run unprivileged (`pvsuite`, the `prometheus` user); root exists only for the volume seeding and drops before exec; the bundled `*.token` defaults materialize as random 0600 values | F7 closed; F17 open (the volume trust) |
| `/inverter` | the fake: bin/ (the daemon + the ctl/cli clients), lib/ (the simulator, the machines, control, metrics, inverter, profile), man/ | a test instrument on a trusted LAN: the Modbus surface capped (`max-clients`/`client-timeout`/`max-conn-per-ip`, live-settable), the read-count gate, the metrics endpoint optional (warns beyond loopback without a token); deliberately not security-first — documented as such | F11 closed; F1 accepted |
| `/profiles` | the device profiles (JSON data: sun2000 + three Deye variants) + the linter and the formatter bins | data, not code: the profiles decide what the tools read (and what the cache's write allow-list may touch); the loader validates every entry (the type/width/scale, the address bounds, clean `SystemExit` one-liners), the search path is closed (three fixed candidates, no CWD or `PATH` dependence), the linter checks the schema shape, the overlaps and the bounds — treat a profile file like config: the operator picks it | none (rev. 4 review: the loader, the linter, the formatter) |
| `/scrape` | the exporter: bin/ (the daemon + the ctl/cli clients), lib/ (server, scraper, poller, control, settings, config, statics), man/, the ini + the sample rules | the read-only consumer: one HTTP GET route set (bearer-gated, capped, the non-loopback refusal) + one outbound Modbus client (FC3/FC4 reads only); the family JSON-lines control server (rev. 6: the unix socket `0600` after bind, the token'd TCP with the F5 refusal, peer-cred, the signed wire, the SCR trail); the SIGHUP reload re-validates everything (the token-file modes too) | F13 closed; F14/F15/F16 open; F20 closed (the clients) |
| `/scripts` | `release.py` (the release orchestrator: the version sweep, the changelog rename, the verify, the tag, the push; the GH release is the workflow's job, the local cut is the opt-in `--release`) + `audit_verify.py` (the F10 chain verifier) | maintainer-local trust: the orchestrator guards the dirty tree and the main-only rule, verifies (the full suite + the nix build by default), then commits/tags/pushes; the verifier is offline and read-only; no runtime surface; the tag is the release's trust root, signed when a key exists — see F19 | F19 closed (rev. 5: the workflow cuts the release after the gate) |

`flake.nix` (the packaging: the packages, the overlay, the NixOS modules)
and `tests/` (the verification suites cited in §4) are part of the story
but hold no runtime trust of their own.

| Surface | cache/ | scrape/ | inverter/ | dashboard/ | Auth |
|---|---|---|---|---|---|
| Modbus TCP listener | `--listen`, default `127.0.0.1:15502` | n/a (outbound only) | `--host/--port`, default `127.0.0.1:5502` (Docker: `0.0.0.0`) | n/a | none (the Modbus protocol has none) |
| HTTP surface | the `/metrics` endpoint: `--metrics-server` (live-settable), off; binds `--metrics-listen` (default `127.0.0.1:9252`; `0.0.0.0` allowed, **the token is mandatory regardless**) | the exporter itself: `--listen`, default `127.0.0.1:9350` — two GET routes (`/`, `/metrics`), everything else a 404, `Cache-Control: no-store` | the `/metrics` endpoint: `--metrics-server`, off; binds `--metrics-listen` (default `127.0.0.1:9452`) | the page + the Prometheus proxy: `--bind`, default **`0.0.0.0`:8080** — GET-only, the static tree realpath-guarded (403 on escape), the proxy under `--prom-prefix` | bearer token (`hmac.compare_digest`): mandatory on the cache, mandatory beyond loopback on the scraper (F13's refusal), optional on the fake (test tool — a non-loopback bind without one logs a warning); **none on the dashboard (F21)** |
| control server (JSON lines) | unix socket `/tmp/modbus-cache-<port>.socket`, `chmod 0600` after bind (`0660` with `--control-socket-group`); `--control-port` = TCP on 127.0.0.1, **refuses to start without a token** | unix socket `/tmp/modbus-scraper-<listen-port>.socket`, `chmod 0600` after bind; `--control-port` = TCP on 127.0.0.1, **refuses to start without a token** | unix socket, `chmod 0600` after bind (`0660` with `--control-socket-group`); `--control-port` = TCP on 127.0.0.1 (exempt from the refusal — the F11 test-tool posture) | unix socket `/tmp/dashboard-<port>.socket`, `chmod 0600` after bind; `--control-port` = TCP on 127.0.0.1, **refuses to start without a token** | token on TCP (`hmac.compare_digest`), refused without; on unix a kernel-vouched peer (peer-cred: root, the daemon's own user, `--control-trust-uids`) skips the handshake; the signed wire (the full HMAC per frame) wherever a token is held |
| state dump | `--dump-path`: the live setting overrides and — with `--dump-with-cache`/`request dump with-cache` — the cached words (+ stamps), as one atomic JSON — see F18 | n/a | n/a | n/a | **created `0600` explicitly** (never the umask) + a sha256 integrity hash checked at restore (F18) |
| token files | `--control-token-file` / `--metrics-token-file` | `--auth-token-file` / `--control-token-file` | `--control-token-file` / `--metrics-token-file` | `--control-token-file` | **owner-only (0600) enforced** — a group/world-accessible token file refuses to start (F12); the env forms (`MODBUS_CACHE_CONTROL_TOKEN_FILE`, `SCRAPER_CONTROL_TOKEN_FILE`, `FAKE_CONTROL_TOKEN_FILE`/`FAKE_METRICS_TOKEN_FILE`, `DASHBOARD_CONTROL_TOKEN_FILE`) are honored by the daemons and the ctl/cli clients alike (F20 closed) |
| upstream connection | outbound to the inverter/SDongle | outbound poll to the inverter/SDongle (or the cache), every 10 s by default | n/a (it *is* the device) | outbound HTTP to the Prometheus (`--upstream`, default `http://localhost:9090`) | none (protocol-inherent); the Prometheus hop is plain HTTP too |
| audit trail | CACHE / CLI / CTL — XDG state home or stdout, append-only, rotated, control-character-folded (the shared `common/audit.py`) | SCR / CLI / CTL, same | INV / CLI / CTL, same | DSH / CLI / CTL, same | local file perms + the per-writer hash chain, verified by `scripts/audit_verify.py` (F10) |
| compose demo stack | the four services (`fake-inverter`, `modbus-cache`, `modbus-scraper`, `prometheus`) on one `internal: true` network (`pv-modbus`), **nothing published on the host**, no outbound route; one shared `config` volume (prometheus: read-only) with the generated 0600 `metrics.token` (F7) | | | | the internal network is the boundary; the exporter bearer-gated in the demo |

Deployment surfaces (docker/): all three Modbus images run the tool as the
unprivileged `pvsuite` user on alpine; the shared `entrypoint.sh` runs as
root **only** to seed the `/config` volume (bundled defaults copied in,
existing files kept, `*.token` defaults materialized as random 0600 values
— the bundled files are placeholders that are never copied) and drops to
`pvsuite` via `su-exec`. The Prometheus image follows the same pattern
(`entrypoint-prometheus.sh`: root copies the token from the volume, then
su-exec to the unprivileged `prometheus` user).

The scraper is the read-only consumer in the family: it polls the device (or
the cache) and exposes Prometheus metrics — no write path, no
state-changing verbs; its attack surface is one HTTP GET route set, the
JSON-lines control server (the family auth: rev. 6) and one outbound
Modbus client (FC3/FC4 reads only). The control verbs change the scraper's
own polling/log settings, not the device; the `set` vocabulary stops at
the exporter. The cache's write
path is the only state-changing Modbus surface and is gated four times
(the fail-closed parse gate, `--allow-write` — off by default,
`write-acl` — **none by default**, the register allow-list `write-registers`
— **none by default**; the latter two default to none, so enabling
`--allow-write` alone still refuses every write). The fake's write path
(FC06/16 → its overlay) is the intended demo feature, gated by
control-server access only.

## 2. Implemented controls (all modules)

- **Access control (NIS2 21.2(h), DORA art. 9)** — cache writes need four
  independent gates (the parse gate, `allow-write` — off by default,
  `write-acl` — **none by default**, and the register allow-list
  `write-registers` — **none by default**; the ACLs and the allow-list take
  `any`/`none`/an explicit list, `proxy.py:287,366-395`); control
  TCP requires the token before any command and a token-less TCP control
  refuses to start (F5) on every tool that serves one — the cache
  (`cache/bin/modbus_cache.py:243-247`, `cache/lib/control.py:141-148`,
  constant-time `hmac.compare_digest` at `:146`), the scraper
  (`scrape/lib/config.py`, asserted by the regtest) and the dashboard
  (`dashboard/lib/config.py:150`) — the fake stays exempt on purpose
  (F11's test-tool posture); on the unix sockets the peer-cred path
  authenticates the kernel-vouched peers without the secret
  (`cache/lib/control.py:110-126` and the family mirrors,
  `common/cred.py`) and everyone else still needs the token; wherever a
  token is held the wire is signed both directions (`common/wiresec.py` —
  the full payload HMAC per frame, mandatory over TCP, verify-if-present
  on unix); the cache's metrics endpoint is token-mandatory when enabled
  (`cache/bin/modbus_cache.py:252-256`, the gate at
  `cache/lib/metrics.py:161-175`); all non-Modbus listeners bind 127.0.0.1
  hard-coded — the dashboard is the documented exception (F21).
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
  `--auth-token-file` for LoadCredential-style files (`common/config.py` is
  the shared loader, and it **enforces the owner-only mode (0600)** —
  `check_token_file_mode`, F12's fix); the token-flag exposure (`ps` /
  `/proc/*/cmdline`) is documented in every README and man page (F9's fix);
  the Nix modules warn when a token would be rendered into the
  world-readable store ini (`cache/module.nix:402`, `scrape/module.nix:214`).
- **Logging / audit (NIS2 21.2(d)(f), DORA art. 11)** — append-only,
  flushed, thread-safe, size/daily-rotated trail (`common/audit.py` — one
  writer for the whole family); writes/refusals/auth-fails/control
  commands/lifecycle events recorded; control characters folded at the
  writer so one event is one physical line (F2's fix); audit falls back to
  stdout (journald) when the path is unwritable.
- **State dump handling** — written atomically (tmp + `os.replace`,
  `persist.py:35-39`), read defensively (format/version/row/bounds
  validation, a foreign or truncated file restores nothing,
  `persist.py:43-72`); the dump is **settings-only by default** (the
  words ride along on `request dump with-cache` / `--dump-with-cache`;
  the restore takes either shape); loading on start is gated behind
  `--restore-on-start` (the default is starting cold); restored words keep
  their original stamps so the ttl bounds any staleness; restored setting
  overrides go through the same validation as the live `set`
  (`cache/lib/control.py:711-726`) — the dump is config-equivalent trust
  (F18): created `0600`, integrity-hashed, restored only after the hash
  and the mode checks pass.
- **Supply chain (NIS2 21.2(d), DORA art. 28)** — stdlib-only, zero
  third-party dependencies, no transitive risk; Nix-pinned builds; the
  demo's Prometheus comes from the alpine package (pinned by the base
  image); the shared `common/` package narrows the review surface instead
  of widening it (one audit writer, one token loader, one wire core, one
  peer-cred helper).
- **Platform hardening (NIS2 21.2(a)(c))** — `DynamicUser`, `NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
  `RestrictAddressFamilies=AF_INET/AF_UNIX/AF_INET6`, `LoadCredential`
  (`cache/module.nix:435`); unix control sockets get explicit modes after
  bind, never the umask (F8's fix); Docker images run the unprivileged
  `pvsuite` user on alpine (Prometheus: the unprivileged `prometheus`
  user via su-exec), audit to stdout, the entrypoints drop root before
  exec; the compose demo stack is internal-only and publishes nothing
  (F7's fix).
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
  SIGHUP-rereadable, mode-enforced) is preferred over `--auth-token` and
  giving both is an error (`scrape/bin/modbus_scraper.py:89`);
  `--max-clients` (default 64) sheds excess HTTP clients with an immediate
  503 (`lib/server.py:119`) and `--client-timeout` kicks idle keep-alive
  connections — the fixed-rate poll loop (10 s by default) means request
  floods cannot reach the device (the metrics are a snapshot, not
  per-request fetches).
- **Dashboard HTTP surface (NIS2 21.2(h), DORA art. 9; rev. 6)** — the
  route set is GET-only and closed by construction: the static tree is
  served from one realpath-checked root (a resolved path escaping it
  answers 403, `dashboard/bin/dashboard.py` `static()`), everything else
  404s, and the Prometheus proxy rewrites one configurable prefix
  (`--prom-prefix`, default `/prom`) onto the upstream URL with the query
  string forwarded — no methods, no verbs, no state changes reach
  Prometheus through it; the family connection gate applies to the whole
  surface (`--max-clients` / `--client-timeout` / `--max-conn-per-ip`,
  extras an immediate 503, `common/connlimit.py`); the control commands
  (`shutdown`, `request reload`, the live caps) ride the JSON-lines
  control server with the family auth, not the HTTP side. **What is
  missing is authentication (F21)**: no bearer check on page or proxy,
  and the default bind is `0.0.0.0:8080` — the loopback / reverse-proxy
  deployment is documented, and the compose demo keeps the surface
  internal-only, but a bare `dashboard` run on anything beyond localhost
  exposes the production values it renders.

## 3. Findings

### 3.1 Closed (F2–F10, F11–F13, F18–F20; fixes verified, see §4)

Closed in rev. 2: F2, F3, F4, F5, F6, F8. Closed in rev. 3: F7, F9, F12. Closed in rev. 4: F11, F13, F10, F18. Closed in rev. 6: F20.

| # | Module | Was | Fix (where) |
|---|---|---|---|
| F2 | cache, inverter | MEDIUM — **audit-trail injection** (rev. 2): a control command embedding newlines (JSON `\u000a`) wrote a second, fully attacker-crafted physical trail line (a forged `AUDIT CACHE WRITE …` with an attacker-chosen stamp), undermining the integrity of the very artifact DORA art. 11 detection relies on. | The writer folds control characters in every detail line — one shared site covers the COMMAND echoes and any future writer (`common/audit.py event()`). Verified: the forged text stays inside the one wrapped COMMAND line (§4). |
| F3 | cache | LOW — **register allow-list failed open on unparseable writes** (rev. 2): a write frame too short to carry the address yielded `_write_target → None`, `_write_allowed(None) → True`, and after the first two gates the frame was forwarded upstream verbatim. | Fail closed: an unparseable write frame is refused with ILLEGAL_VALUE and audited as `WRITE-REFUSED` (`proxy.py:366-372`). Verified: FC6 with no address → `0x86/0x03`. |
| F4 | cache, inverter | LOW — **uncapped pre-auth control line buffer** (rev. 2): a client streaming bytes without a newline grew `buf` until the 300 s idle timeout — an unauthenticated local memory amplification on the unix socket. | Both control servers drop the connection past the 1 MB `MAX_LINE` (`cache/lib/control.py:33,191-193`, `inverter/lib/control.py:33,162-164`). Verified: a 1.1 MB newline-less stream is dropped. |
| F5 | cache, inverter | LOW — **token-less TCP control was fully unauthenticated** (rev. 2): `--control-port N` without a token left every control verb (including `set allow-write on` and `shutdown`) open to any local process able to reach 127.0.0.1; no rate limit on auth attempts either (AUTH-FAIL is audited, the compare is constant-time). | The cache refuses to start a TCP control port without a token — the unix socket needs none (`cache/bin/modbus_cache.py:243-247`); the inverter stays exempt (a test tool, F11). Verified: startup refusal, one line, rc 2. |
| F6 | cache | LOW — the cache's metrics endpoint, when enabled without `--metrics-token`, exposed register values, addresses and poll state to anyone who could reach it; no connect timeout on the handler (slowloris could pin threads). Closed rev. 2. | The token is mandatory when the port is set — the proxy refuses to start otherwise (`cache/bin/modbus_cache.py:254-257`); the handler socket times out after 5 s (`cache/lib/metrics.py:156`). Verified: startup refusal; the 401/200 flows unchanged. |
| F7 | docker (all services) | LOW — the compose stack published every listener on all host interfaces: the fake's Modbus (`5502`), the cache's Modbus (`15502`) **and the scraper's unauthenticated-by-default `/metrics` (`9350`)** — in the demo stack F13's exposure was materialized by default. Closed rev. 3, in two steps. | **Nothing is published.** Step one: every `ports:` entry dropped; the services wire onto one `internal: true` network (`pv-modbus`, explicitly named so collectors can attach — no host ports, no outbound route); every surface (Modbus, control, metrics, the Prometheus UI) is reachable only from inside the network — `docker compose exec`, or a collector container attached by name; the `docker run` examples bind to `127.0.0.1` only. Step two: the demo **Prometheus service with the scrape/token story** (`Dockerfile.prometheus`, `entrypoint-prometheus.sh`, `prometheus.yml`) — the exporter serves with a bearer token in the demo now (`SCRAPER_AUTH_TOKEN_FILE=/config/metrics.token`; the entrypoint materializes bundled `*.token` defaults as random 0600 values owned by pvsuite — the bundled placeholder is never copied) and Prometheus scrapes `modbus-scraper:9350` with `authorization.credentials_file`, reading its own 0600 copy of the same token. Verified: the resolved config carries zero published ports, the internal network and the token env (§4). |
| F8 | cache, inverter | LOW — the unix control socket's file mode was never set explicitly (rev. 2): `bind()` created it with the umask-derived mode, and a permissive umask (002/000) made it group/world-connectable, i.e. control access without a token. | Both control servers `chmod 0600` immediately after `bind()`; the cache takes `--control-socket-group` for `0660` — an opt-in, documented delegation to a local group (`cache/lib/control.py:78-86`, `inverter/lib/control.py:71-79`). Verified: the modes are observed `0600`/`0660` on the live sockets. |
| F9 | cache, inverter, scrape | INFO — tokens passed as `--control-token` / `--metrics-token` / `--auth-token` flags are visible in `ps` / `/proc/*/cmdline` to other local users. The token-file / env-var paths existed; nothing said the flag was the weak way. Closed rev. 3. | Documented in all three READMEs and the token-flag man pages: the flag form is for quick tests, prefer `--control-token-file` / `--metrics-token-file` / `--auth-token-file` (LoadCredential) or the env vars — and every `-file` help says the file must be owner-only 0600. The file path got hard in the same wave (F12). Verified: the README/man wording, `mandoc -Tlint` clean (§4). |
| F12 | cache, inverter, scrape | INFO — token files were not permission-checked: the shared `load_token_file` (`common/config.py`) accepted a group/world-readable token file silently. Closed rev. 3. (The `/tmp` control-socket half of the original finding stays covered by the Nix module's `PrivateTmp`; use `/run/<tool>/` under systemd.) | Fail closed: `check_token_file_mode` (`common/config.py`) stats the path before the read — any group/world bit (`0600` is the documented form) refuses to start with a one-liner (`chmod 0600`), on the daemons and the ctl/cli clients alike; the scraper's SIGHUP-reread loader runs the same check on every reload. The docker entrypoint seeds generated `*.token` files 0600. Verified: 0644/0640 refused, 0600 accepted, the regtests assert the refusal (§4). |
| F11 | inverter | INFO — the fake's Modbus surface had no client limit, no client timeout and no ACL — any LAN peer could hold threads or flood requests when bound beyond localhost — and a declared read count far above the payload (e.g. `0xFFFF` with a truncated frame) made the fake assemble an oversized reply / scan the range. Closed rev. 4, as the audit recommended: the mitigations + the honest docs, not a security redesign — a test instrument stays a test instrument (the metrics endpoint still serves without a token by design; no connect ACL — that is the deployment's segmentation job). | The cache's knobs, mirrored: **`--max-clients`** (refuse past the limit at accept, `inverter/lib/inverter.py`) and **`--client-timeout`** (shed silent clients) — both tunable live (`set max-clients` / `set client-timeout`, `unset` restores the configured value), **`show connections`** on the control server (peer, age, requests — plus `clients=` in the status report and the modbus row in `inspect`), and the **read-count gate** (count `0` or past the 125-register cap, or a span past the 16-bit space → exception 03, the cache's shape). Documented: the README's Security section and the man page's SECURITY block say the fake is a development tool, not security-first — run it on a trusted, LAN-isolated network. Verified: the new `tests/inverter-regtest.py` (§4). |
| F13 | scrape | MEDIUM — `/metrics` was unauthenticated by default (`--auth-token` unset → every request authorized): the loopback bind was the only control, and one flag exposed every register value; the rate limiter counted connections, not peers. Closed rev. 4: the refusal ships and the caps ship. | **Fail closed beyond loopback**: a non-loopback listen without `--auth-token`/`--auth-token-file` refuses to start with a one-liner (`refusing to expose /metrics beyond loopback without a token`, F13 in docs/AUDIT.md) — the SIGHUP reload runs the same check and keeps the previous settings; the loopback default needs no token (localhost dev stays friction-free). The demo stack has carried the token since F7. **Per-peer caps**: `--max-conn-per-ip` (0 = no limit) caps concurrent connections per peer IP with the immediate 503, next to the existing `--max-clients`/`--client-timeout`. Documented in the README (the refusal + the Prometheus `authorization.credentials_file` scrape example) and the man page. Verified: the refusal matrix and the per-IP 503 in `tests/scrape-regtest.py` (§4). |
| F10 | cache, scrape, inverter | INFO — the audit trail was append-only but not integrity-protected (no hash chain): a local administrator could rewrite it unnoticed. Closed rev. 4 with the honest boundary: the trail is now tamper-EVIDENT (any edited, reordered or deleted middle entry breaks the chain at verification); a determined local admin holding the algorithm can rechain, and trailing deletion leaves nothing to verify — journald forwarding stays the strong answer for the retention/immutability requirement. | **A chained hash per entry**: every line carries a short hash right after the event name — `<stamp> AUDIT <PREFIX> <EVENT> <12 hex> [detail]`, `sha256(prev | stamp | prefix | event + detail)` truncated, chained **per writer prefix** (CACHE / INV / CLI / CTL each chain their own lines, so interleaved writers in one file verify independently and a restarted writer seeds from its own tail, `common/audit.py`). **The verifier**: `scripts/audit_verify.py [FILE|-]...` (default: the family's XDG trails) walks a file and its rotated backups oldest-first, recomputes every chain, anchors at each prefix's first surviving entry, reports unsigned (pre-chain) lines and names the line where a chain breaks; exit 1 on any break. Documented: the trail's README sections + `common/audit.py`'s docstring. Verified: the new `tests/audit-chain.py` (§4). |
| F18 | cache | LOW — **the state dump was config-equivalent trust at rest, with an umask-derived mode**: `--dump-path`'s JSON carries the cached register values (production data) *and* the live setting overrides, and a restore re-applies any registered setting through the live validation — `allow-write` included. Whoever could write the dump file effectively held config trust; whoever could read it saw the values. Closed rev. 4. | **Fail closed, the F8/F12 pattern**: the dump is created **`0600` explicitly** (`os.open` + `fchmod` on the tmp before `os.replace` — never the umask, `cache/lib/persist.py`), and every dump carries a **sha256 integrity hash** of its canonical content — a restore recomputes it (`hmac.compare_digest`) and refuses an edited/truncated/foreign dump (`fails its integrity hash — nothing restored`) and an unsigned pre-hash dump (`dump again`); a **group/world-writable dump refuses outright** (`the dump holds config trust, chmod 0600`) — shrink the writer set to the owner. The exposure itself shrank too: by default the dump now carries **settings only** — the words ride along only on `request dump with-cache` or `--dump-with-cache` (the words are production data; keep them out unless the write-behind/restart story needs them). Documented as config-trust: own the dump like the ini; the hash catches corruption and casual tampering, not a local admin who rechashes (the F10 boundary). Verified: the mode/hash/tamper/unsigned/writable-refusal checks in `tests/cache-regtest.py` (§4). |
| F19 | scripts | LOW — **the release landed before the CI gate reported** (found rev. 4): `scripts/release.py` cut the GitHub release locally right after the tag push — the tag-triggered workflow's test+build jobs start only after the tag exists, so an unverified release could be published and a failing CI could not un-cut it; the local verification defaulted to `--tests quick` (two of the nine suites) and the annotated tag was unsigned. Closed rev. 5 as recommended. | **The defaults flipped**: the GitHub release is the **workflow's** job — `.github/workflows/release.yml`'s `release` job gates on `needs: [test, build]` (the suites + the four-package nix build) and cuts the GH release from the changelog section only after both report; the local cut is the explicit opt-in (`--release`, help + flight print name the bypass). **The local gate defaults to `--tests full`** (all ten suites as of rev. 6; `--tests quick` stays for a re-cut). **The tag is signed** (`git tag -s`) whenever a signing key exists — the unsigned annotated tag is the fallback and the flight prints why. Verified: the dry-run plan and the flight matrix in a scratch repo (§4). |
| F20 | cache, scrape, inverter, dashboard (the ctl/cli clients) | LOW — **the help promised a control the code did not have** (found rev. 6, re-checking the docs against the code): every ctl/cli `--control-token-file` help — and the man pages rendered from it — promised the env form (`MODBUS_CACHE_CONTROL_TOKEN_FILE`, `SCRAPER_CONTROL_TOKEN_FILE`, `FAKE_CONTROL_TOKEN_FILE`, `DASHBOARD_CONTROL_TOKEN_FILE`), and none of the eight clients read it; a script following the documented hardened path ran token-less and failed the handshake. The daemons were unaffected (their config resolution reads the env). Closed rev. 6, in the same wave. | One resolution shape family-wide, in every ctl/cli: `token_file = flag or env`, `token = flag or env`, both together the mutual-exclusion error, the file over the plain token, then the shared `load_token_file` (the F12 0600 gate applies to the env path too). The fake's daemon got the env form of `--control-token-file` / `--metrics-token-file` the same way (the other daemons resolved the env from the start). Documented: the READMEs' env lists and flag tables are true again; the closed TODO item (the token-file env honored) records the wave. Verified: the new env checks in all four affected suites + the live `fake_cli` / `dashboard_cli` smokes (§4, rev. 6). |

### 3.2 Open findings

| # | Module | Severity | Finding | Recommendation |
|---|---|---|---|---|
| F1 | cache, scrape, inverter | HIGH (accepted, protocol-inherent) | Modbus TCP carries no authentication and no encryption — listener and upstream alike. For the scraper this is outbound-only: it cannot be reached through the device, but a compromised inverter LAN segment can feed it bogus register values (sanity-capped by `--max-kwp` / `--max-grid-kw`). | Keep the listener off the WAN (the default binds 127.0.0.1), set the connect ACL on a LAN (`none` if no client should connect at all), keep `--allow-write` off unless needed — the write path now defaults fully closed (`write-acl`/`write-registers` none); the cache owning the device's single client slot is the mitigation. |
| F21 | dashboard | MEDIUM | **The HTTP surface serves without authentication and binds `0.0.0.0` by default** (found rev. 6, the first dashboard-covering audit): the page and the Prometheus proxy — the production values (generation, consumption, battery SoC, F15's privacy class) — answer any requester; the connection caps shape traffic but do not gate access. The control plane is family-hardened (the F5 refusal, the signed wire), the compose demo keeps the surface internal-only and the loopback / reverse-proxy deployments are documented — but the default run is the open one, and the family's own scraper refuses exactly this shape without a token (F13). | Mirror the scraper: a bearer check (`--auth-token` / `--auth-token-file`, constant-time) on page and proxy, and a loud startup warning (or the F13-style refusal) when binding beyond loopback without one; until it ships, run the dashboard on loopback or behind an authenticating reverse proxy. |
| F14 | scrape | LOW | No TLS on the HTTP endpoint (plain HTTP): the bearer token and the metrics travel in clear text. | Terminate TLS in a reverse proxy when anything beyond localhost needs the endpoint. |
| F15 | scrape | INFO | The metrics expose production values (generation, consumption, battery SoC) — a home-occupancy privacy consideration. | The bearer token (F13) + the localhost bind are the controls; treat the endpoint as internal. The dashboard renders the same values and inherits the consideration (F21). |
| F16 | scrape | INFO | No automated alerting yet (freshness gap, poll down, exception spikes — the rules pack is pending). | Ship the alert rules file with the NixOS module; NIS2 21.2(d) wants detection wired, not just logged. |
| F17 | docker | INFO | The `/config` volume holds the live ini files — anything a user puts there (e.g. a `control_token =` line) sits in plaintext on a docker volume, and the entrypoint seeds copies **once** (existing files are never refreshed): a fixed bundled default does not reach an existing volume until it is wiped. The generated `metrics.token` (F7) lives in the same volume — 0600 and root-owned-seeded, but not secret-backed. | Prefer token files outside the volume / `LoadCredential` / secret-backed mounts for anything sensitive; document `docker compose down -v` as the way to re-sync the volume with the bundled defaults. |

## 4. Verified evidence

### Rev. 2 (at `84b4387`)

- **F2 (injection → fold)** — rev. 1 reproduced the forged second line;
  rev. 2 verified the fix: the same command
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
- **F5/F6 (refusals)** — the rev. 2 evidence: the regtest started the cache
  with `--control-port` (no token) and with `--metrics-port` (no token):
  both exited non-zero with a one-line error, no traceback. The same
  refusal lives on under the rename (`--metrics-server` without a token —
  the regtest asserts it on every run).
- **F8 (socket modes)** — the regtest `os.stat`s the live unix control
  sockets: `0600` by default, `0660` with `--control-socket-group`.

### Rev. 3 (rev. 3's tree: the demo stack, the token discipline, the write defaults)

- **F7 (no host ports + the demo token)** — verified at the config level
  (the file review + a YAML parse; no docker host in the audit sandbox):
  the compose file carries no `ports:` on any service; all services attach
  to one `internal: true` network (`pv-modbus`); the scraper service sets
  `SCRAPER_AUTH_TOKEN_FILE=/config/metrics.token`; the entrypoint
  materializes bundled `*.token` defaults as random 0600 pvsuite-owned
  values (the pipeline verified: 24 urandom bytes → 48 hex chars) and the
  Prometheus entrypoint copies the token 0600 for the unprivileged
  `prometheus` user. Bring the stack up and confirm with `docker compose
  ps` (no published-port column), an empty host listener table for
  `5502`/`15502`/`9350`/`9090` and a 401 from a token-less `/metrics`
  request.
- **F9 (flag exposure → documented)** — the three READMEs carry the "a
  token flag lands in `ps`" note (prefer the `-file` variants or the env
  var; the flag form is for quick tests) and the token-flag man pages say
  the same (`mandoc -Tlint` clean). The file path is now the
  recommended-and-hardened route (0600 enforced, F12).
- **F12 (token-file modes → fail closed)** — `check_token_file_mode`
  (`common/config.py`) stats the path before the read; the audit sandbox
  verified the matrix directly: a 0644 file → `mode 644 is group/world
  accessible — a token file must be 0600`, a 0640 file → refused the same
  way, a 0600 file → the token loads, a missing file → the established
  `cannot read control-token-file` one-liner. Both regtests assert the
  refusal end-to-end (the cache with `--control-token-file` on a 0644 file,
  the scraper with `--auth-token-file` on a 0644 file — clean rc≠0, no
  traceback); the fuzz suite exercises the fake + ctl path with a 0600
  file. The SIGHUP-reread scraper loader re-runs the check on every
  reload.

- **The write-default hardening** (posture, not a finding) — the cache
  regtest's `none`-modes block asserts the new defaults end-to-end: the
  start log reads `connect acl: any, write acl: none, write allow-list:
  none`; with `--allow-write` on and everything else default, an FC6 write
  is refused `0x86/01` with the trail naming the write ACL;
  `set write-acl any` moves the refusal to the allow-list;
  `set write-registers any` lets the write pass; `unset write-acl` restores
  `none` and the refusal returns. `connect-acl none` rejects the connection
  at accept; `set connect-acl any` lets the client back in. The scraper's
  dry-run prints the 10 s default (`every 10s`); Prometheus's demo config
  scrapes at 10 s.

### Rev. 4 (rev. 4's tree)

- **F11 (the fake's soft edges → capped + documented)** — a new
  `tests/inverter-regtest.py` asserts the whole surface end-to-end: the
  count gate (a `0xFFFF` read, count 126, count 0 and a span past the
  16-bit space all answer exception `03` with the connection surviving; a
  125-register read at the cap still answers normally), `--max-clients 1`
  (the excess connection gets EOF at accept, the admitted client keeps
  serving, the refused peer is not tracked), `--client-timeout 1` (the
  silent client is shed in ~1 s; `set client-timeout 0` live keeps one
  connected), `show connections` (the peer with its request tally, `none`
  after the exits) and the listening line naming the policy (`client
  limit 1, client timeout 300s`). The README's Security section and the
  man page's SECURITY block document the trusted-LAN / not-security-first
  posture.
- **F10 (the trail → tamper-evident)** — `tests/audit-chain.py` verifies
  the chain and the verifier: two interleaved prefixes verify OK; an
  edited line, a deleted line and reordered lines are each detected at
  the right line with the right prefix (exit 1); legacy unsigned lines
  are reported, not failed; a restarted writer chains seamlessly from its
  own trail; a chain spanning rotated backups (`.3..1` + live, verified
  oldest-first) validates end to end; the fake's + ctl's real INV trail
  verifies after a live control session.
- **F13 (fail closed beyond loopback + the caps)** — the scraper's
  refusal matrix: a `--listen 0.0.0.0:PORT` dry-run without a token exits
  1 with the `refusing to expose /metrics beyond loopback without a
  token` one-liner, with `--auth-token` it validates, and the loopback
  default stays token-free; the per-IP cap answers 503 to a second
  simultaneous connection from one address (`tests/scrape-regtest.py`);
  the cache and the fake metrics 503 past `--metrics-max-clients`
  (asserted in both regtests), and the cache's Modbus per-IP gate refuses
  the second same-peer connection until `set max-conn-per-ip` raises it.
- **F18 (the state dump → owned trust at rest)** — the cache regtest
  asserts the whole story: the dump file is observed `0600` right after a
  `request dump` and carries the 64-hex integrity hash; a tampered dump
  (a flipped word) refuses with `fails its integrity hash — nothing
  restored`; an unsigned (pre-hash) dump refuses with `predates the
  integrity hash — dump again`; a group/world-writable dump (mode 646)
  refuses outright with `chmod 0600`; and after all three refusals the
  untouched dump still restores cleanly (91 words + the override).
- **The rev. 4 re-audit — the new shared surfaces** — a focused review of
  `common/connlimit.py` (the admit/release symmetry holds, including the
  live-set path), the audit chain in `common/audit.py` (the chain state
  under the lock, rotation-safe, the control-character fold intact) and
  the hardened `cache/lib/persist.py` (the hash over the canonical
  payload; the mode and the hash gates fire before anything restores) —
  no new findings; the removed `--metrics-port` flags fail loudly
  (argparse, rc 2) rather than being silently ignored.
- **The rev. 4 re-audit — the rest of the tree, directory by directory** —
  `/common`: every module re-read (config/token/cred/protocol/human/
  logutil/version — the fail-closed one-liners, the closed search paths,
  no dynamic imports or eval); `/profiles`: the loader, the linter and
  the formatter re-read (stdlib `json` only, per-entry validation with
  bounds, the three-candidate closed search path — no findings); 
  `/scripts`: `release.py` reviewed line by line — the dirty-tree and
  main-only guards, the idempotent bump/changelog/tag/release steps, no
  secret handling — **one finding: F19** (the release is cut locally
  before the CI gate reports); `/docker` and the three Modbus
  subprojects: covered by the rev. 2–4 findings above. All nine suites
  pass on the re-audited tree.

- The remaining open findings are established by code reading (file:line in
  the table), unchanged from rev. 2 where the cited files did not change.

### Rev. 5 (rev. 5's tree)

- **F19 (the gate ordering → the workflow cuts)** — the flipped defaults
  verified on a flight-tested scratch repo (the real script, a minimal
  tree, `--no-push`): the default flight prints the full-suite gate
  (`--tests full` is the default — all seven suites listed one by one in
  the dry-run), attempts the signed tag and falls back cleanly with the
  reason (`tagged 0.0.1 (annotated — no signing key: error: gpg failed to
  sign the data)` — the tag object materializes annotated), then closes
  with the handoff (`the GitHub release is the workflow's job; pass
  --release to cut it here`); no `gh release create` step runs. The
  opt-in `--release` path still follows the tag push and names the bypass
  (`--release cuts the GitHub release locally, before the CI gate
  reports`); `--no-release` is gone (argparse rejects it, rc 2). A
  dry-run prints the plan without running the suites (it used to die on
  the `ALL PASS` check), and the bump's old-version check treats `git
  grep`'s no-matches exit code as success (a fresh flight used to die
  there, mid-tree). The workflow (`.github/workflows/release.yml`) is
  unchanged and stays the gate: `release` `needs: [test, build]` — the
  seven suites + the fuzz budgets and the four-package nix build — cutting
  the GH release from the changelog section only after both report.

### Rev. 6 (this revision)

- **F20 (the promised env → honored)** — new checks in all four affected
  suites: `tests/cache-regtest.py` (cache_ctl honors
  `MODBUS_CACHE_CONTROL_TOKEN_FILE` against the token-file proxy; the
  token env + the token-file env is the clean mutual-exclusion error),
  `tests/scrape-regtest.py` (scraper_ctl and scraper_cli honor
  `SCRAPER_CONTROL_TOKEN_FILE` against the token'd TCP control; the env
  conflict), `tests/control-fuzz.py` §6c (fake_ctl honors
  `FAKE_CONTROL_TOKEN_FILE` against the token-file fake; the fake's
  dry-run honors `FAKE_METRICS_TOKEN_FILE`; the env/env and flag/env
  conflicts), `tests/dashboard-control-fuzz.py` §6b (dashboard_ctl honors
  `DASHBOARD_CONTROL_TOKEN_FILE`; the env conflict). Plus the live
  smokes: a real `fake_cli` and a `dashboard_cli` session authenticating
  and signing the wire with only the env file set.
- **The dashboard re-audit** — `dashboard/bin/dashboard.py`,
  `lib/control.py`, `lib/config.py`, `lib/settings.py` read end to end
  against the family shapes: the F5 refusal fires in the config
  resolution (`dashboard/lib/config.py:150`), the token compare is
  constant-time (`lib/control.py:145`), the pre-auth line buffer drops
  past 1 MiB (`:199`), the unix socket is `chmod 0600` after bind
  (`:86`), the peer-cred trust mirrors `common/cred.py`, the DSH prefix
  chains like the others, and the config resolution is fail-closed (the
  whitespace guard on the token, the F12 mode check on the file paths).
  The HTTP handler: GET-only, the static tree realpath-guarded (403 on
  escape), the proxy a plain GET forward with the query string, the
  family gate capping the surface. One finding: **F21** (no
  authentication, the `0.0.0.0` default) — recorded open; the family
  TODO's auth-story item is the same work.
- **The scraper control plane** — reviewed as the family mirror it is
  (the cache's shape: the same wire discipline, caps, audit vocabulary,
  the F5 refusal, peer-cred): no new findings beyond F20's client half;
  the regtest asserts the refusal and the signed wire end to end.
- **The release gate drift** — `scripts/release.py`'s `SUITES_FULL` ran
  eight of the ten suites (the inverter regtest and the audit-chain suite
  were missing from the gate while the CI item and this audit cite them):
  fixed — the full gate lists all ten and the `--tests` help says so.
- All ten suites pass on the re-audited tree; the man pages regenerated
  (`mandoc -Tlint` clean) — on the way a help slip in the dashboard's
  `--audit-log` (it said SCR; the trail is DSH) is fixed.

## 5. NIS2 / DORA mapping (all modules; cache is the production-relevant one)

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(a) risk-management policies | yes (scoped) | defaults-as-security documented (writes quadruple-gated with the ACL/allow-list defaulting to none, localhost binds, tokens mandatory on the control/metrics surfaces, token files 0600, dry-run); this audit is the written analysis |
| NIS2 21.2(b) incident handling | yes (scoped) | audit trail + journald retention, the trail tamper-evident (the per-writer hash chain, `scripts/audit_verify.py` — F10 closed); no automated alerting yet (F16) |
| NIS2 21.2(c) business continuity | yes | reconnect/backoff, per-leaf isolation, restart/reload/reset verbs, the gated write-behind dump for last-known values; daemons restart cleanly (regtests) |
| NIS2 21.2(d) supply chain | yes | stdlib-only, no third-party code, pinned Nix builds; the demo Prometheus from the pinned alpine package; the shared `common/` core |
| NIS2 21.2(f) effectiveness | partial | fuzz/stress/regression suites (self-contained); no CI enforcement yet |
| NIS2 21.2(g) cyber hygiene / crypto | partial | constant-time token compares, LoadCredential, owner-only token files enforced, no secrets in logs; no TLS (F1 — protocol-inherent, F14 — proxy) |
| NIS2 21.2(h) access control / MFA | yes (scoped) | the four write gates (two defaulting to none), ACLs with a restrict-all mode, token-mandatory control/metrics, the refusal of a non-loopback metrics listen without a token (F13), the token'd TCP control refusing to start without a token on all four control servers (the fake exempt — F11), per-IP + total connection caps on every serving surface, peer-cred on the unix sockets, the signed wire wherever a token is held; MFA not applicable to a machine protocol |
| DORA art. 8 ICT asset identification | yes | every option logged at start; `inspect` dumps the full state; the demo topology is documented (docker/README.md) |
| DORA art. 9-10 protection/prevention | yes | write gates, ACLs, capped framing, capped buffers, fail-closed writes, token-mandatory surfaces, the non-loopback refusal (F13), the per-IP + total connection caps, explicit socket + token-file modes, fail-fast validation; the dashboard's GET-only route set with the traversal guard (the auth gap aside — F21) |
| DORA art. 11 detection | yes (integrity restored, now evidenced); wiring pending | the audit trail's integrity is defensible again (F2 closed, fold at the writer) and evident per entry (the hash chain, F10 closed); auth-fail/refusal events; the alert rules pack is the remaining gap (F16) |
| DORA art. 12 BCP | partial | restart/reload/clear verbs, the dump/restore write-behind; no automated failover (single-device by design) |

Scraper deltas against the table above (rows where scrape matches are omitted):

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(b) incident handling | yes (scoped) | audit trail + unauthorized-request logging at WARNING; the alert pack is pending (F16) |
| NIS2 21.2(f) effectiveness | partial | the fuzz suite is the technical check; no CI enforcement yet |
| NIS2 21.2(g) crypto / hygiene | partial | constant-time bearer compare, owner-only token files, no secrets in logs; no TLS (F14 — terminate at a proxy) |
| NIS2 21.2(h) access control | yes (scoped) | bearer gate on the only route set + the non-loopback refusal without one (F13 closed), the per-IP + total connection caps; MFA not applicable to a machine protocol |
| DORA art. 9-10 protection/prevention | yes | default localhost bind (refusing to leave it without a token, F13), token gate, two-route whitelist, DoS caps on both the HTTP and the poll side |
| DORA art. 11 detection | partial | audit trail + WARNING-level unauthorized logs + the error-state 503 |
| DORA art. 12 BCP | yes | read-only, stateless, restart-clean; the data plane (Prometheus) holds the history |

Dashboard deltas against the main table (rows where the dashboard matches are omitted):

| Requirement | Status | Where |
|---|---|---|
| NIS2 21.2(b) incident handling | yes (scoped) | the DSH/CLI/CTL audit trail (chained, tamper-evident) + the control wire's macs; the alert pack is pending (F16) |
| NIS2 21.2(f) effectiveness | partial | `tests/dashboard-control-fuzz.py` covers the control wire; no CI enforcement yet |
| NIS2 21.2(g) cyber hygiene / crypto | partial | constant-time control-token compare, the signed control wire, owner-only token files, no secrets in logs; no TLS and no auth on the HTTP surface (F21; F14's proxy story applies) |
| NIS2 21.2(h) access control | partial | the control plane is family-hardened (the F5 refusal, peer-cred, the signed wire); the HTTP surface is the gap — no bearer gate, `0.0.0.0` default (F21); the connection caps shape traffic but do not gate access |
| DORA art. 9-10 protection/prevention | partial | the GET-only closed route set (the realpath-guarded static tree, the prefix-scoped proxy), the caps; the missing auth is the finding (F21) |
| DORA art. 11 detection | partial | the audit trail + the signed control wire; no request-level access log by default (`--log-access`) |
| DORA art. 12 BCP | yes | a stateless viewer: restart-clean, `request reload` re-reads the config, the data plane (Prometheus) holds the history |

## 6. Verdict

The posture is sound for the deployment class the tools target (an
operational/home LAN behind segmentation): refuse-by-default writes — now
closed by default even beyond `--allow-write`, since `write-acl` and
`write-registers` default to `none` — localhost binds by default
(the dashboard's HTTP surface is the recorded exception — F21),
token-mandatory control and metrics surfaces on the cache, the scraper
refusing a non-loopback metrics listen without a token, the token'd TCP
control refusing to start without a token on every server that serves one
(the fake exempt by documented posture), per-IP and total
connection caps on every serving surface, constant-time
token checks, kernel-vouched peer-cred on the unix control sockets,
length-disciplined wire parsing with capped buffers and fail-closed write
parsing, a real audit trail whose integrity survives hostile control
input and is now tamper-evident per entry (the chained inline hashes and
`scripts/audit_verify.py` — F10 closed), explicit socket modes and owner-only token
files instead of umask
hope, zero dependencies, hardened systemd units and unprivileged
containers whose entrypoints drop root before exec, and a compose demo
stack that publishes nothing on the host (one `internal: true` network;
the demo exporter serves with a generated bearer token and the demo
Prometheus scrapes it with the same 0600 file).

Per revision: rev. 1 named two findings that touched the audit control
itself (F2, F3) and three cheap control-channel gaps (F4/F5/F8); rev. 2
fixed and re-verified all five, together with F6. Rev. 3 closed F7 (the
compose stack publishes nothing — one internal network, plus the demo
Prometheus service with the scrape/token story), F9 (the token-flag
exposure documented everywhere) and F12 (token files fail closed unless
owner-only 0600), and hardened the write defaults on the way. Rev. 4
closed the rest of the actionable set: F11 (the fake's Modbus surface got
the cache's client cap/timeout, the `show connections` view and the
read-count gate — with the trusted-LAN posture documented instead of a
security redesign), F13 (the scraper refuses a non-loopback metrics
listen without a token; per-peer caps on every serving surface), F10 (the
audit trail is tamper-evident: a chained hash per entry, per writer
prefix, with `scripts/audit_verify.py` — the honest boundary: a
determined local admin holding the algorithm can rechain, so journald
forwarding stays the strong answer where the retention requirement is
strict) and F18 (the state dump created `0600` explicitly and
integrity-hashed — a restore fails closed on a tampered, unsigned or
group-writable file; the dump itself now carries settings only by
default, the words on `request dump with-cache` / `--dump-with-cache`).
This rev. 4 pass also walked the rest of the tree directory by directory
(the inventory in §1) and found one new LOW: **F19** — the release
orchestrator cuts the GitHub release before the tag-triggered CI gate
reports; flip the defaults (the workflow cuts the release, the local gate
runs the full suite, sign the tags when a key exists). Rev. 5 closed it as
recommended: the workflow's `release` job is the cutter (gated on
`needs: [test, build]`), the local cut is the explicit opt-in `--release`,
the local gate defaults to the full suite and the tag is signed whenever a
key exists. Rev. 6 closed the deferral — the audit now covers the whole
pv-suite: the scraper's and the dashboard's control planes joined the
family shape (no new findings there beyond F20), the walk found **F20**
LOW (the ctl/cli help promised the token-file env vars and the clients
never read them — a documented control that did not exist; honored
family-wide in the same wave) and **F21** MEDIUM (the dashboard's HTTP
surface serves page and proxy without authentication on the `0.0.0.0`
default bind — the caps and the closed route set shape traffic, the
bearer gate mirroring the scraper's is the recommendation), and the
release gate's suite list was corrected to all ten suites. The remaining
open set is otherwise the documented trust decisions and the
deployment stories: the state-dump trust is owned now (F18 closed) — the
dump file deserves the ini's care (the hash catches tampering, not a
local admin who rechashes). The inverter fake remains a test instrument
with deliberately soft edges — now capped and documented as such (F11
closed); the scraper's remaining
exposures stay operational, not architectural — terminate TLS at a proxy
when exposed (F14) and ship the alert rules (F16); the dashboard's HTTP
auth is the one open finding with code to write (F21). The accepted
exposure remains F1 (Modbus TCP itself) — mitigate with segmentation and
the write gates.

Re-run this audit after the dashboard's auth story (F21) or the TLS story
lands, after the multi-target / control-plane evolutions, or any new
listener or file format; at least yearly otherwise.
