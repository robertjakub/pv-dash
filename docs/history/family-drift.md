# The family-drift history — the landed legs

The wave record behind [family-drift.md](../family-drift.md): the main
doc keeps only the current findings (the open drift, the census, the
open remediation TODOs); every LANDED leg moves here — the finding,
the wave that closed it, the shape it landed in. Newest first. The
`--check` gate keeps the main doc's census honest; this file is the
judgement history the census replaces.

## The audit-family wave (Nov 9, 59431d7..d1dc2c4) — four legs landed

- **The accept ladder is one.** The surface sweep's drift — the accept
  discipline living in four bodies — closed with the extraction:
  `common/modbus/server.py`'s `serve_modbus` runs the discipline once
  (the client timeout -> `conn_gate.admit` -> the connect-ACL check ->
  the `max_clients` check -> the count under the lock -> the daemon
  thread -> the pre-serve failure unwind -> the `finally` close; the
  backlog unified at 128; the accept-error retry notices the
  `stopping` flag). The faces delegate (`Proxy.serve`, the fake's
  `serve`) and bring the face protocol's hooks: `listening`, `access`,
  `allowed`, `suite_key`, `on_frame`/`on_session`, `malformed`,
  `frame`, `on_disconnect`.
- **The session opener rides the same ladder.** `_session` registers
  the client under the lock, runs the suite handshake when armed
  (`auth_handshake_server`, the peer dropped before it ever sees a
  frame), counts the requests per frame, and the `finally`
  unregisters — the cache's audit trail `REQUESTS` event rides
  `on_disconnect`, the fake's counters ride `on_frame`/`on_session`.
- **The audit rotation bounds are family-wide.**
  `common/runtime/audit.py` holds the constants (`AUDIT_FILES` 1..100,
  `AUDIT_MAX_MB` 0..1048576), all four registries' rows repeat them,
  and `check_options` cross-checks the repetition — `set audit rotate
  files 0` refuses identically everywhere.
- **The `audit-daily` knob is one shape.** The live name
  `audit/rotate/daily` and the `$AUDIT_DAILY` env twin agree on all
  four, and the fake's live dispatch flips the same bit; the remaining
  audit rows (log/max-mb/files/disable) stay startup-only by posture —
  no live name, the env twin carries them.
- **The env layer completed under the env-or-note rule.** Every knob
  carries its env twin or an explicit `no-env` note, and
  `check_options` gates the pair. The no-env census at closing: the
  fake's 13 (the F11 simulator surface — env-less by posture, their
  flags reachable from the config file since the config-file wave),
  the dashboard's 1 (`log-queries` — the live toggle exists, the
  startup stays flag-only), the cache and the scraper none.

## The drift-sweep wave itself (Nov 9, b5d6321 + 4022437)

The workflow landed: the thirteen sweep types, the regenerated
doc (`--check` byte-compares a fresh render), the seed ledger
(docs/family-drift-seeds.json, the growth gate — a NEW uncovered
promise fails `--check`). The original eight landed code legs (the
code sweep's finds that folded on the spot): `common/daemon.py`;
`common/modbus/client.py` `ClientBase`; `common/connlimit.py`
`rate_limit_503`; `common/control.py` `rebuild_audit`;
`common/options.py` `parse_registry_sections` + `option_rows`;
`resolve_profile_file`; `payload_hash`; `acl_admits`.

## The prose catch-ups (the redo discipline)

- **42bcfad (Nov 9)** — the audit-family wave landed the four legs but
  never touched `family_drift.py`'s prose constants: the regenerated
  doc kept arguing for done work. The redo rewrote the constants
  (header, SURFACE_CENSUS, SURFACE_FINDINGS, KNOBS_FINDINGS,
  REMEDIATION). The lesson: a wave that lands a drift leg edits the
  script's editorial blocks in the same commit — the `--check` cannot
  catch a verdict that went stale, only a census that did.
- **d1c749d (Nov 9)** — the config-file wave's five editorial
  constants still argued the pre-config fake; the catch-up.
- **d3736b6 (Nov 9)** — the full-docs stale sweep (the drift `--check`
  was green — the staleness lived in the HAND-written docs:
  docs/ACL.md's surfaces table, docs/MODBUS.md's rotation prose, the
  READMEs). The method that worked: run ALL the generated gates first,
  then hunt retired vocabularies in the hand-written docs with
  targeted greps, verify each suspect against the registries + code
  before editing, and distinguish history records (point, don't
  rewrite) from present-tense claims (fix).

## The verification state (Nov 9, at the redo)

Every `--help`/`--man` byte-identical vs HEAD; `check_options` +
`lint_options --check` clean; the ten-suite battery green (the
cache/scrape regtests and the cache-fuzz legs needed one clean re-run
after the killed first battery's daemons squatted the suite ports —
the failures were port squatters, not code; the bind-note's clean
death told the story).

## The growth rule

A wave that lands a drift leg: (1) lands the code, (2) moves the
finding's verdict out of the script's `*_FINDINGS`/`REMEDIATION`
blocks (or rewords it to the current state), (3) appends the landed
leg HERE — the wave, the commit range, the shape, (4) regenerates the
main doc, (5) runs `family_drift.py --check` green. The main doc may
only shrink its findings; this file only grows.
