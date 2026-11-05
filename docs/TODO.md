# TODO (family-wide)

## Open

- **the rest of the demo stack** — the compose chain runs the three Modbus
  tools (fake inverter → cache → scraper) with the seeded `/config` volume;
  what is missing is the front and the storage: a **Prometheus** service
  scraping the exporter and a **dashboard** service rendering it — plus the
  demo config seeded into the volume (the cache's `allow-write` demo pokes,
  the dashboard's `battery: true`), so `docker compose up` and the whole
  story runs — the write-through pokes land in the charts live, the outages
  banner themselves, the audit trail narrates.
- **the audit-finding fixes** — the audit's prompt pair (F2 audit-trail
  injection, F3 the fail-open write allow-list) plus the cheap hardening
  gaps (F4 the uncapped pre-auth buffer, F5 the token-less TCP control, F8
  the socket mode, F12 the token-file perms) — see [AUDIT.md](AUDIT.md);
  each closes in a few lines, then re-run the audit.
- **the CI** — GitHub Actions: the seven suites + `nix flake check` (all
  four packages, all systems) on the push; the release workflow on the tag.
  (Tracked per subproject too; it lands here once for all.)
- **the hardware verification** — everything is verified against the fake
  inverter, fuzzing and stress only; a real SUN2000/SDongle week (poll
  pacing, the dongle's single-client behaviour, real exception codes, the
  FC4 input registers, reconnect storms) is the last mile. (Split per
  subproject: cache / scrape.)
- **the release discipline** — the version lives in `common/version.py`
  (`0.3.0`, `-<short git>` in a checkout) but nothing pins the process: a
  CHANGELOG.md, the tag → release workflow, and the flake.lock/`version`
  bump in the same commit.
- **the per-phase export** — the fake serves per-phase voltages/currents
  and the unbalanced home already; the scraper exports none of it and the
  dashboard shows none of it. A `phase` label on the metrics (or three
  suffixed registers) would close the loop fake → scrape → dashboard.
- **the SBOM / supply-chain note** — [sbom/SBOM.md](sbom/SBOM.md) + `sbom/sbom.cdx.json`
  state the stdlib-only claim per subproject (the machine-readable
  CycloneDX copy rides along); what remains is the automation: generate
  and check both in the release workflow, so the claim stays audited, not
  asserted.
- **the man pages** — every tool has `--help` and a README; a `--man` (or
  plain roff in each subproject) would make the packaged installs complete.

## Done (the highlights; the git history has the details)

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
