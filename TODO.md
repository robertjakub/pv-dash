# TODO (family-wide)

## Open

- **the demo stack** — one compose file wiring fake inverter → cache →
  scrape → dashboard (+ Prometheus): `docker compose up` and the whole
  story runs — the write-through pokes land in the charts live, the
  outages banner themselves, the audit trail narrates.
- **the profile linter** — `tests/profile-lint.py`: overlapping ranges,
  the type width vs the register count, the fc validity, the
  cache/scrape flags sanity — `profiles/` is the shared subproject, the
  lint rides with the CI.

Everything per-subproject lives in its own TODO.md (the CI is tracked in
each and lands here once for all).
