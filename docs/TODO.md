# TODO (family-wide)

## Open

- **the rest of the demo stack** — the compose chain runs the three Modbus
  tools (fake inverter → cache → scraper) with the seeded `/config` volume,
  and a **Prometheus** service scrapes the exporter over the internal
  network (the scrape/token story: a random bearer token generated into the
  volume, 0600); what is missing is the front: a **dashboard** service
  rendering the Prometheus — plus the demo config seeded into the volume
  (the cache's `allow-write` demo pokes, the dashboard's `battery: true`),
  so `docker compose up` and the whole story runs — the write-through pokes
  land in the charts live, the outages banner themselves, the audit trail
  narrates.
- **the remaining audit findings** — the open ones are documented trust
  decisions / deployment stories now:
  F16 (the alert-rules pack), F17/F14/F15/F1 — see
  [AUDIT.md](AUDIT.md); F2–F10, F11–F13 and F18 are closed and verified
  (§3.1/§4);
  re-run the audit after the scrape control surface, the TLS story or the
  dashboard service.
- **the CLI redone: hierarchical commands, one grammar for the family** —
  the control vocabulary grew organically per tool and it shows: flatten
  it into namespaces and make every tool speak the same shape —
  `set modbus-client max-per-ip 8` (the surface, then the knob) instead of
  the flat `set max-conn-per-ip`, `set metrics-server off` /
  `set metrics listen 0.0.0.0:9252` on all three control servers, the same
  verbs everywhere (set/unset/show/request/...), the same reply shapes.
  Also: **`show config`** — every setting printed in `set` format (one
  re-enterable block: `show config` pipes straight back into `cache_ctl`
  /`fake_ctl` after a restart), complementing the scriptable
  `show settings` key=value listing. Breaking: every script and unit file
  speaking the old flat grammar follows.
- **the verifiable control commands** — the control wire gets the audit
  trail's integrity idea: commands (and the replies?) carry a short hash
  (the trail's chained `h=` shape or an HMAC keyed by the control token)
  so a client can verify nothing was injected/altered between the CLI and
  the server — over plain TCP the token auth is the boundary today; this
  closes the last unauthenticated corner (the audit-trail line: the
  command the server logs should cryptographically match the command the
  client sent).
- **the CI** — GitHub Actions: the seven suites + `nix flake check` (all
  four packages, all systems) on the push; the release workflow on the tag.
  (Tracked per subproject too; it lands here once for all.)
- **the hardware verification** — everything is verified against the fake
  inverter, fuzzing and stress only; a real SUN2000/SDongle week (poll
  pacing, the dongle's single-client behaviour, real exception codes, the
  FC4 input registers, reconnect storms) is the last mile. (Split per
  subproject: cache / scrape.)
- **the release discipline** — **done**: `scripts/release.py` (the
  orchestrator: the version sweep, the changelog rename, the flake.lock
  refresh, the verification, the commit, the annotated tag, the push and
  the `gh release` from the changelog section) plus the tag-triggered
  workflow (`.github/workflows/release.yml`: the seven suites, the nix
  build, the GitHub release). What remains is operational: watch the
  first few flights, then retire the training wheels.
- **the per-phase export** — the fake serves per-phase voltages/currents
  and the unbalanced home already; the scraper exports none of it and the
  dashboard shows none of it. A `phase` label on the metrics (or three
  suffixed registers) would close the loop fake → scrape → dashboard.
- **the SBOM / supply-chain note** — [sbom/SBOM.md](sbom/SBOM.md) +
  `sbom/sbom.cdx.json` state the stdlib-only claim per subproject (the
  machine-readable CycloneDX copy rides along); what remains is the
  automation: generate and check both in the release workflow, so the
  claim stays audited, not asserted.
- **the man pages** — every tool has `--help` and a README; a `--man` (or
  plain roff in each subproject) would make the packaged installs complete.

## Done (the highlights; the git history has the details)

- **the release tooling** — `scripts/release.py` + the tag-triggered
  release workflow: the Open item above is the operational follow-up.
- **the man pages** — one roff page per tool in each subproject's `man/`
  (`src/man/` for the dashboard; 11 pages total: the three cache binaries,
  the three inverter binaries, the scraper, the dashboard server, the two
  profile tools), installed by the Nix packages (`share/man/man1/`) and
  linted with `mandoc -Tlint`.
- **the demo stack, the Modbus chain** — `docker/compose.yaml`: the three
  alpine images (one Dockerfile per tool, unprivileged `pvsuite`, tools on
  `PATH`), the shared external `config` volume seeded by `entrypoint.sh`
  (bundled defaults copied in, existing files kept), the profiles +
  `common/` riding in as named build contexts.
- **the profile linter** — `profiles/bin/profile-lint.py`: the required keys and
  their family order, the register bounds, the type width, the fc, the
  per-entry ttl, the mappings vs a register word, the duplicate names, the
  same-fc overlaps, the terse-ASCII style; all four shipped profiles lint
  clean.
- **the profile formatter** — `profiles/bin/profile-format.py`: rewrites any
  profile into the sun2000.json layout in place — one mappings entry per
  line, one register per line, keys in the family order; content-preserving
  and idempotent (the sun2000 itself comes back byte-for-byte).
- **the common/ package** — the shared core extracted: version, audit,
  config plumbing, the Modbus wire core, the UTC log formatter; the suite
  talks one vocabulary.

Everything per-subproject lives in its own TODO.md (cache, scrape,
inverter, dashboard).
