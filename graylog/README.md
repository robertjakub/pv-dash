# graylog — the audit trail's Graylog support

The operator-side content for pointing Graylog at the family's audit
trail: which input to bind, how the line's KV words become fields, the
streams and dashboards worth drawing, and what to alert on. Nothing here
is loaded by any tool — `alerts/`' charter, Graylog flavour: the family
emits, Graylog consumes.

The trail it consumes is docs/AUDIT.md's: one KV line per event —
`<stamp> AUDIT tools=<TAG> tag=<writer> type=<type> hash=<12-hex>
[message=<kv pairs>]` — carried **verbatim** inside every forward
envelope, so chain verification (scripts/audit_verify.py) works
identically at the collector.

## The shipped content pack

[pv-suite-content-pack.json](pv-suite-content-pack.json) imports as one
unit (System → Content packs → upload, then Install) and creates:

- **the input** — `pv-suite audit (syslog UDP)`, bound `0.0.0.0:1514`
  (unprivileged — never 514), full message stored; point the family at
  it: `--audit-forward udp://<graylog>:1514` (the default `rfc5424`
  format, the native line rides the envelope's message verbatim).
- **two pipeline rules + one pipeline** — `pv-suite audit kv` runs
  `key_value(msg, quote: "'", ignore_empty_values: true)` over the line
  and `set_fields(kv, prefix: "audit_")`: the outer words become
  `audit_tools` / `audit_tag` / `audit_type` / `audit_hash`, the simple
  message pairs `audit_result` / `audit_peer` / `audit_reason` /
  `audit_wire` / ... ride beside them (the reserved-key rule in
  docs/AUDIT.md is what makes one flat namespace safe). `pv-suite audit
  cmd` picks the quoted value — `cmd='set pv 3000'` truncates under any
  space-split kv — into `audit_cmd`. The pipeline connects to the
  Audit · all stream.
- **five streams** — Audit · all / commands / security / lifecycle /
  writes. The rules key on the RAW `message` with REGEX (` type=command
  ` and friends), not on the audit_* fields: the StreamRouter runs
  before the pipeline processors, so a stream rule on a pipeline-set
  field would never match. The dashboards and event definitions use the
  audit_* fields — those exist by index time.
- **four event definitions** — the alerts table below as aggregation-v1
  definitions (the auth-fail surge and the wire-policy refusals HIGH,
  the write refusals and the restart churn NORMAL). **No notifications
  are attached** — create your notifier and select it per definition.

The chain verification stays off-box: the pack does not watch the
chain — the off-box verify is scripts/audit_verify.py over the
collected file (the cron), the same three-tier story as docs/AUDIT.md.

The pack was written against the content-pack v3 schema and verified by
inspection only (no Graylog on the dev machine) — a schema refusal on
your server names the entity; the fix rides this file.

## The ingestion routes (pick one)

### 1. Syslog input + extractors — works today, no tool change

`--audit-forward udp://<graylog>:514` (or `tcp://`) with the default
`rfc5424` format, and a Graylog **Syslog UDP/TCP input**. The native line
rides the envelope's message verbatim; the KV words become fields through
one pipeline rule (or a matching extractor set) — the real rules ship in
the content pack above; hand-roll them only to move off the pack's
defaults.

The CEF format (`--audit-forward-format cef`) feeds Graylog's CEF input
the same way — the `cs1`/`cs2` extracted fields carry the chain hash and
the tool tag for the collectors that prefer CEF.

### 2. GELF-native — the proposed third format (the tool change)`--audit-forward-format gelf` (the proposal): one JSON datagram per
event, the KV words as **native GELF fields** — no extractors, no
pipeline parsing, the streams and dashboards key directly:

```json
{"version": "1.1", "short_message": "command peer=10.0.0.9 cmd='set pv 3000' result=ok",
 "host": "pv-cache-1", "level": 4, "_tools": "CACHE", "_tag": "daemon",
 "_type": "command", "_hash": "1a07cac1f910", "_peer": "10.0.0.9",
 "_result": "ok", "timestamp": 1699699200.0}
```

Every `key=value` of the message becomes `_<key>` — the uniqueness rule
(docs/AUDIT.md) is what makes that mapping safe. Recommendation: **GELF
for Graylog** (the structured trail is the whole point of the KV
reformat), keep `rfc5424`/`cef` for the SIEMs that speak syslog.

## The streams

The rules below are spelled in the GELF route's `_`-fields; the shipped
pack's route-1 streams route on the raw `message` regex instead (the
StreamRouter runs before the pipelines — a stream rule on a pipeline-set
field never matches) and the same names wear the `audit_` prefix
(`audit_type`, `audit_peer`, `audit_tools`, `audit_result`, `audit_reason`).

| stream | rule |
|---|---|
| Audit · all | `_exists_:_type` (every family audit line carries it) |
| Audit · commands | `_type:command` |
| Audit · security | `_type:auth-fail` OR `_type:write-refused` OR `_type:write-rejected` OR `_result:err` OR `_exists_:_reason` |
| Audit · lifecycle | `_type:start` OR `_type:shutdown` OR `_type:reload` OR `_type:restore` |
| Audit · writes | `_type:write` OR `_type:write-refused` (the forwarding edge) |

## The dashboards

- **Commands** — `_type:command` per `_tools` over time, split by
  `_result` (the ok/err share), the top `_peer` values, the `cmd=` word
  cloud.
- **Security** — `_type:auth-fail` and `_result:err reason:*` per `_peer`
  and per `_tools` (the unsigned/bad-mac attempts are the tamper signal),
  the write-refused per register range.
- **Lifecycle** — `_type:start` per `_tools` (the restart count — a START
  without a preceding SHUTDOWN is a crash), the `uptime=` distribution at
  `type:shutdown`.

## The alerts (the Graylog event definitions)

- **auth-fail surge** — `_type:auth-fail` > N in 5 minutes from one
  `_peer` (the brute-force signal).
- **the wire-policy refusals** — `_exists_:_reason` at all: a signed
  surface seeing unsigned or badly-signed frames is an attack in progress,
  not noise.
- **the write-refused** — any (the write ACL doing its job is worth a
  look, not necessarily a page).
- **the restart churn** — `_type:start` > 3 in 15 minutes per `_tools`
  (the crash loop).
- **the chain break** — NOT a Graylog search: the chain is stateful per
  writer tag, so the off-box verify is `scripts/audit_verify.py` over the
  collected file (the cron), and the collector pages on its FAIL line
  (docs/AUDIT.md's three-tier story).

## The layout (the alerts/ charter)

Shipped content lands here as the operators copy it: the pipeline rule +
the extractor JSON exports, the stream/dashboard definitions, the event
definitions — each as the Graylog UI's own export shape, versioned with
the trail grammar (docs/AUDIT.md gates the drift). The GELF format
proposal rides the tool's `--audit-forward-format` — its wave lands the
format, the README documents the input.
