# TODO (family-wide)

## Open

- **the demo stack** — one compose file wiring fake inverter → cache →
  scrape → dashboard (+ Prometheus): `docker compose up` and the whole
  story runs — the write-through pokes land in the charts live, the
  outages banner themselves, the audit trail narrates.

## Done

- **the profile linter** — `tests/profile-lint.py`: the required keys and
  their family order, the register bounds, the type width, the fc, the
  per-entry ttl, the mappings vs a register word, the duplicate names, the
  same-fc overlaps, the terse-ASCII style; all four shipped profiles lint
  clean.

Everything per-subproject lives in its own TODO.md (the CI is tracked in
each and lands here once for all).
