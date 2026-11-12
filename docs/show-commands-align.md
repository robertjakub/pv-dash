# registry-align — the show + commands sections (and the options residual)

Status: **landed** — flown as proposed (the pending verdicts took their proposed calls; request-restart's KEEP later flipped by ruling — see the commands table). The same contract as
[options-align.md](options-align.md) (FOLD / ALIGN / KEEP), applied to the
registry's other two sections. The byte-compare behind the tables ran after
the key-alignment wave landed (60 canon blocks, 42 family-wide, 0 dead).

## show

| knob | verdict | today | proposal | review |
|---|---|---|---|---|
| metrics-acl-table | ALIGN | the cache's and the scraper's rows speak the long rule-chain spell (byte-identical); the inverter's and the dashboard's carry the pointer "(the metrics/acl report)" | a `show` canon block with the long spell — self-describing help beats the pointer; the pointer rows fold it; the exempt retires | ok |
| version | ALIGN | "the modbus-cache version" / "the modbus-scraper version" / "the fake-inverter version" / "the dashboard version" | "the suite version" — the suite versions are one (common/runtime/version.py); the daemon's own name rides the banner already; a `show` canon block; the exempt retires | ok |
| connections | KEEP | the cache's and the inverter's texts agree ("connected clients: peer, age, requests served"), the scraper's and the dashboard's speak the HTTP gate counters | a partial fold would carry the exempt anyway — not worth a half-dead block; the exempt stays | ok |
| config / knobs | — | done in the key-alignment wave (the blocks carry the descrs + `hidden`) | nothing | ok |
| uplink / uplink-sources | — | partial (cache, scraper), the rows agree, the canon blocks exist | nothing movable — the inverter and the dashboard lack the uplink | ok |

## commands

| knob | verdict | today | proposal | review |
|---|---|---|---|---|
| help, ping, quit, show, shutdown, request-poll-now, request/poll | — | on the canon, the rows agree | nothing | ok |
| request-dump, request-restore, request-reload-config | KEEP → flown further | the inverter's help says "the fake" where the blocks say "the daemon" | the fake nouns are the fake's truth (options-align §3 carry-over); the exempts stay | ok |
| request-restart | QUESTION → ALIGN — flown | the cache hid the row, the scraper showed it; no canon block | the user's ruling (Nov 12): hidden family-wide — a canon block {the upstream-session floor help, hidden}; the scraper's session-drop help stays inline (the exempt stands) | ok |
| request-reload | KEEP → ALIGN — flown | the per-tool parentheticals say what re-resolves (the restart-marked knobs / the config file and flags / the flags and env) | the user's ruling: hidden family-wide — a canon block {the daemon-restart floor help, hidden}; the parentheticals stay inline (the exempt stands) | ok |
| request (node), inspect | KEEP — flown further | the tool's own machinery words and dump contents | floor blocks landed (options-align's ledger): inspect + request speak the family floor, the tools keep their tails | ok |
| the / rule | RETIRED — flown and retired the same day | the hidden rows never listed in ?/TAB; a namespace whose every member hides vanished from the root ? (the fake's request); the settings walk kept its hidden knobs invisible with no signal | the console's / rule (a namespace word carrying hidden rows lists `request/`/`dump/` marked, the walk-ins list the hidden rows marked, the gate criterion joins as a second mark source) — retired by ruling: the hidden rows never list again (the pools' rule; the typed path still answers), a namespace whose every member hides falls back to its node descr (`help request` answers the node one-liner), the gate flag is gone from the canon and the registries | retired |
| clear, set | ALIGN — flown | the three tools carried per-tool examples where the cache's row teaches the grammar | the cache's grammar forms are the family texts (`set <setting> <value>` / `clear <setting>`) — two new commands blocks, the example tails drop (the ?-walk and TAB walk the real knobs), both exemptions retired | ok |

## the options residual (for completeness)

The key-alignment wave took the options section as far as the canon goes.
The six remaining "candidates" in the drift report are §3/§4's KEEP rows —
`auth-token` (the endpoints differ) and the five node namespaces (metrics,
metrics/limits, modbus, system, write — a namespace descr lists the tool's
own children). The seventeen KEEP exemptions stand. Nothing further moves
without changing tool semantics.

## the fly order

1. The two `show` blocks land in shared/suite/options.json; the four
   metrics-acl-table rows and four version rows thin-ref (the block text
   replaces every inline descr).
2. The `('show', 'metrics-acl-table')` and `('show', 'version')`
   exemptions retire — only when the rows fully resolve.
3. Gates: `lint_options.py --check`, `check_options.py`, the regen
   `--check`s, `options_drift.py`, then the per-tool commits and the
   battery before any push.

## The landed ledger

    62 canon blocks (44 family-wide, 0 dead) — the show section's
    metrics-acl-table and version blocks landed; the two show exemptions
    retired; the MANUALs and the conf examples render the long spell and
    "the suite version" family-wide.
