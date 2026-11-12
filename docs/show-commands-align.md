# registry-align — the show + commands sections (and the options residual)

Status: **landed** — flown as proposed (the pending verdicts took their proposed calls; request-restart stays KEEP). The same contract as
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
| request-dump, request-restore, request-reload-config | KEEP | the inverter's help says "the fake" where the blocks say "the daemon" | the fake nouns are the fake's truth (options-align §3 carry-over); the exempts stay | ok |
| request-restart | QUESTION | the cache hides the row (`hidden: true`), the scraper shows it ("drop the Modbus session (reconnects on the next poll)"); no canon block | propose KEEP — the scraper's visibility may be deliberate (its restart is the mild session drop); flip to ALIGN (hide family-wide) if not | ok |
| request-reload | KEEP | the per-tool parentheticals say what re-resolves (the restart-marked knobs / the config file and flags / the flags and env) | the reloaders genuinely differ; no block | ok |
| request (node), clear, inspect, set | KEEP | the tool's own machinery words and examples | the exempts stay | ok |

## the options residual (for completeness)

The key-alignment wave took the options section as far as the canon goes.
The six remaining "candidates" in the drift report are §3/§4's KEEP rows —
`auth-token` (the endpoints differ) and the five node namespaces (metrics,
metrics/limits, modbus, system, write — a namespace descr lists the tool's
own children). The seventeen KEEP exemptions stand. Nothing further moves
without changing tool semantics.

## the fly order

1. The two `show` blocks land in shared/options-help.json; the four
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
