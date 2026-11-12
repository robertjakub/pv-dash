# options-align — the key-alignment contract

Status: **landed** — the verdicts below mark `ok` as flown; the ledger at the bottom records the outcome.

The one-knob-one-source rule: a knob's fields live in the canon block
(`shared/options-help.json`) when they are family-true, in the row when they
are the tool's own; the row's inline field wins over the block; the lint's
`EXEMPT` table is the drift ledger's audit trail — every entry carries its
reason, every dead entry retires.

This doc proposes, for every knob the two reports flag, one of three
verdicts:

- **FOLD** — the rows already agree byte-for-byte; the block gains the
  field, nothing user-visible moves.
- **ALIGN** — the rows disagree only in wording or a bound; converge on the
  named text/value, then fold, then retire the exempt.
- **KEEP** — the drift is the tool's own semantics; the exempt stays.

Data: `scripts/options_drift.py` + `scripts/compare_options.py` +
the byte-compare behind this doc's tables (58 blocks, 42 family-wide,
0 dead; 236 knobs over 4 tools).

## 1. FOLD — the rows already agree

The block lacks the field; every carrying row folds the same bytes. Pure
block edit + thin-ref, no prose change, no rendered surface moves.

| knob | field | carriers | note | review |
|---|---|---|---|---|
| control-log-replies | help | all 4 | verified a no-op at fly — the block already speaks the help; the env twin stays dashboard-only (KEEP §3) | ok |
| control-ops-verbs | help | all 4 | verified a no-op at fly — the block already speaks the help; the `show,flush` default stays cache-only (KEEP §3) | ok |
| control-port | help | cache folds; scraper, inverter, dashboard keep the ctl-name tails | corrected at fly: the three tools' helps carry the per-tool `Talk to it with ...-ctl.py` hint — the generic JSON-lines text folded into the block, the cache dropped inline, the tails stay inline (legal overrides) | ok |
| dump-path | help | scraper, inverter, dashboard | the cache's dump-words help stays inline | ok |
| metrics-client-timeout | help | all 4 | verified a no-op at fly — the block already speaks the help; the scraper's 300 s default stays inline (KEEP §3) | ok |
| metrics-max-clients | help | all 4 | verified a no-op at fly — the block already speaks the help (the default and the value-help aligned in §2) | ok |
| restore-on-start | setting-help | all 4 | — | ok |
| show config / knobs | hidden | inverter, dashboard gain it | the block marks them hidden family-wide | ok |

## 2. ALIGN — converge the wording, then fold, then retire the exempt

The drift is spelling, not semantics. Each row names the proposed family
text (verbatim — this is the review surface).

| knob | field | today | proposed family text / shape | review |
|---|---|---|---|---|
| audit-log | help, setting-help | the CACHE/SCR tag prefixes + the spelled state-home paths ride the prose | both fields adopt the cache's de-tagged form; help says "the XDG state home when unset" instead of spelling the per-tool path | ok |
| audit-forward | help | the cache's help carries the full syslog grammar + the hash-chain note; the others differ | the cache's text is the superset — adopt it family-wide (the shorter tools' rows say nothing the long text contradicts) | ok |
| no-audit-log | help, setting-help | the tag prefixes | setting-help already agrees; help: "disable the audit trail" | ok |
| client-timeout | help, setting-help | "0 = never" tail + wording | the cache's generic forms: "disconnect clients silent for this long" / "disconnect clients silent for this many seconds, 0 = never" | ok |
| max-clients | help, setting-help | the Modbus-vs-HTTP wording | the cache's generic forms: "simultaneous client limit" / "refuse further connections past this many simultaneous clients, 0 = no limit" | ok |
| max-conn-per-ip | help, setting-help | same story as max-clients | the cache's generic forms (one row in the table — the same stack) | ok |
| metrics-server | help, setting-help | "the cache's own" / "the fake's" / "the dashboard's" | "the tool's own Prometheus /metrics endpoint" + the shared toggle/bind tail; the env twin folds too (METRICS_SERVER — the fake's no-env refusal wins); the dashboard's counter-list flavor drops | ok |
| metrics-token | help, setting-help | the endpoint nouns differ | the cache's form with a generic "/metrics endpoint" noun | ok |
| metrics-max-clients | default, value-help | dashboard caps at 16; the scraper's "0 = no limit" value-help is scraper-only | dashboard 16 → 64 (the family cap); the scraper's value-help folds family-wide | ok |
| metrics-max-conn-per-ip | value-help | scraper-only, generic | "0: no per-IP limit (the default)" folds family-wide | ok |
| modbus-auth | help, setting-help, value-help | the suite scheme's audience wording ("every client proves" vs "after every connect, prove") | the cache's value-help texts; the helps follow | ok |
| modbus-profile | values, value-help | the inverter lacks the values vocab; "bundled" vs "shipped" | values ["default"] family-wide; "the shipped sun2000 profile" (the file is shipped) | ok |
| modbus-interval | help, setting-help | "cache polls of the device" vs "polls of the inverter" | "seconds between polls" / "seconds between polls of the upstream" — the side is the tool's; then PROMOTE the block (the candidate list shrinks) | ok |
| modbus-timeout | help, setting-help | "upstream Modbus" vs bare | "Modbus connect/read timeout in seconds" family-wide; then PROMOTE the block | ok |
| restore-on-start | help | the daemon/fake/server noun + the env-note tail | "load the state dump when the daemon starts (needs --dump-path) — a restart serves last-known values instead of cold misses; without it the dump loads on demand" (the env note rides the block's env twin) | ok |
| max-kwp | min | the scraper bounds 0, the inverter unbounded | DROPPED at fly: the fake refuses `max-kwp <= 0` at start (`--max-kwp must be a positive kW value`) — 0 is no meaningful array size, the unbounded row stands | ok |
| show uplink / uplink-sources / request-poll-now / request/poll | — | the canon blocks exist, partial | nothing to align — the scraper-only shapes are the scraper's; KEEP | ok |

## 3. KEEP — the intentional drift (the exempt stays)

| knob | field(s) | why | review |
|---|---|---|---|
| upstream | env, hint, values, value-help, default, restart, check, live | two knobs sharing a flat name: the Modbus upstream vs the Prometheus URL | ok |
| auth-token | help, setting-help, live | the endpoints differ (all requests vs page+config.js+proxy, the `?auth` bootstrap) | ok |
| log-level | help, value-help | the DEBUG detail is the tool's own traffic story | ok |
| log-access | env, hidden, value-help, prose | the inverter reads no env (F11); the cache hides the row; whose access is audited differs | ok |
| local-time | value-help + the inverter's no-env | F11 | ok |
| metrics-listen | default, restart, env, prose | the ports are per-tool; the cache's reload note is the cache's | ok |
| metrics-client-timeout | default, value-help | the scraper serves a slow collector (300 s, the slowloris note) | ok |
| control-ops-token | help, setting-help | the cache's default policy is show,flush; the others' is show — the grammar backs it | ok |
| control-ops-verbs | default | same grammar story (not a gated field — recorded here for the reviewer) | ok |
| control-log-replies | env | the dashboard's env twin; the daemons read none | ok |
| listen | default | the per-tool ports | ok |
| modbus-auth-key | help, setting-help | the key's audience: the cache's clients vs the handshake | ok |
| modbus-merge-gap | max | RULED at review: max 100 family-wide — the block landed, the exempt keeps only the poll side's own setting-help | ok |
| connect-acl | values, value-help, live | the cache forwards (acl/connect), the fake's wording is the fake's | ok |
| allow-write | value-help, prose | the cache forwards, the fake accepts | ok |
| the cache's dump/control family | setting-help, help | the dump words name the cache — the cache's own prose (deviations list) | ok |
| the inverter's control tails | prose | the unix-only wording, the SO_PEERCRED tails | ok |
| the inverter's request-* nouns | help | the daemon vs the fake noun | ok |
| the inverter's no-env rows | env | F11 — local-time, log-access, the metrics caps ride the flags only | ok |

## 4. The node-namespace re-class

The candidate report lists five nodes as promotable — `metrics`,
`metrics/limits`, `modbus`, `system`, `write`. They are not: a namespace's
descr lists that tool's own children (the cache's metrics namespace has the
toggle, bind, token and caps; the scraper's has the spec and the prefix),
so one family text would be overridden by every row — dead weight. Verdict:
KEEP, and the drift report should classify namespace descrs as placement,
not promotion candidates (a one-line options_drift.py change, rides the
same wave).

## The fly order

1. Group 1 FOLD (block edits + thin refs), then Group 2 ALIGN (prose +
   bound edits in the rows), the compare gate re-checks after each group.
2. The blocks land in `shared/options-help.json`; the rows that ref nothing
   else become thin `{ "name": ..., "shared": ... }` refs.
3. The exempt retires ride the same commits: modbus-interval,
   modbus-timeout, no-audit-log, restore-on-start, client-timeout,
   max-clients, max-conn-per-ip, metrics-token, modbus-auth, modbus-profile
   — each only when its fields fully resolve.
4. Regenerate: `scripts/gen_manual.py`, `scripts/gen_examples.py` (the
   Manuals and the conf examples render the aligned prose).
5. Gates: `lint_options.py --check`, `check_options.py`, both regen
   `--check`s, `options_drift.py` (expected: blocks 58 → ~66, candidates
   8 → 0, 0 dead; the exempt count shrinks by the retirements).
6. Per-tool commits (the canon + lint edits ride the first), then the
   battery: `scripts/battery.sh` — the ten suites before any push.

## Out of scope

The 40 single-tool knobs (the inverter's simulation family, the cache's
cache plane, the dashboard's statics) — nothing to align against. The
placement keys (live paths, env twins, flags, ports) stay per-tool by
design. The docker/nixos packaging surfaces follow the registries
mechanically; no hand edits there.

## The landed ledger

Flown as proposed, with the corrections the tables above carry. The drift
report after the wave:

    60 canon blocks (42 family-wide, 0 dead), 21 deviating rows,
    16 block gaps, 6 candidates, 16 drifting, 45 single-tool
    (236 knobs over 4 tools)

- blocks 58 -> 60 (the modbus-interval and modbus-timeout canon blocks),
  gaps 35 -> 16, exempt entries retired 12 (metrics-server and
  metrics-token re-shaped, not dropped: the env-refusal exemption and the
  dashboard's F13 help override stay).
- the deviation count rose 17 -> 21 on purpose: the env twins now fold
  from the blocks, so the inverter's no-env refusals list as deviations —
  the inline-wins mechanism working, each one a KEEP row of §3.
- the 6 remaining candidates are §3/§4's KEEP rows (auth-token, the five
  node namespaces) — the report's promotion lens does not apply to them.
