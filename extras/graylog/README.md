# graylog — the audit trail's Graylog support

The operator-side content for pointing Graylog at the family's audit
trail: which input to bind, how the line's KV words become fields, the
streams and dashboards worth drawing, and what to alert on. Nothing here
is loaded by any tool — `alerts/`' charter, Graylog flavour: the family
emits, Graylog consumes.

The trail it consumes is docs/SECURITY.md's: one KV line per event —
`<stamp> AUDIT application=<TAG> tag=<writer> instance=<id> type=<type>
hash=<12-hex> [message=<kv pairs>]` — carried **verbatim** inside every
forward envelope, so chain verification (scripts/audit_verify.py) works
identically at the collector. The `instance=` word names the writer
daemon — the control port when the tool's `--audit-instance` is unset,
the override when spelled — the per-instance grouping key at the
collector (two caches on different hosts may share a name only while
they never share a collector: the native line and CEF carry no
hostname).

## The shipped content pack

[pv-suite-content-pack.json](pv-suite-content-pack.json) imports as one
unit (System → Content packs → upload, then Install) and creates:

- **the input** — `pv-suite audit (syslog UDP)`, bound `0.0.0.0:1514`
  (unprivileged — never 514), full message stored; point the family at
  it: `--audit-forward udp://<graylog>:1514` (the default `rfc5424`
  format, the native line rides the envelope's message verbatim).
- **three pipeline rules + one pipeline** — `pv-suite audit kv` runs
  `key_value(msg, quote: "'", ignore_empty_values: true)` over the line
  and `set_fields(kv, prefix: "audit_")`: the outer words become
  `audit_application` / `audit_tag` / `audit_instance` / `audit_type` /
  `audit_hash`, the simple
  message pairs `audit_result` / `audit_peer` / `audit_reason` /
  `audit_wire` / ... ride beside them (the reserved-key rule in
  docs/SECURITY.md is what makes one flat namespace safe). `pv-suite audit
  cmd` picks the quoted value — `cmd='set pv 3000'` truncates under any
  space-split kv — into `audit_cmd`. `pv-suite audit gim` normalizes
  onto the Graylog Information Model (the next section). The pipeline
  connects to the Audit · all stream.
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
collected file (the cron), the same three-tier story as docs/SECURITY.md.

The pack was written against the content-pack v3 schema and verified by
inspection only (no Graylog on the dev machine) — a schema refusal on
your server names the entity; the fix rides this file.

## The GIM schema (the audit trail, normalized)

The **Graylog Information Model (GIM)** is the schema Graylog
Illuminate normalizes every log source onto: field names are
`entity_property` pairs (`source_ip`, `event_outcome`, `user_name`,
...) — the *entity* names the object the property belongs to
(source, destination, event, user, process, application, ...), the
*property* describes it. The Field Schema Reference (the Illuminate
docs, generated from the graylog-schema definitions) lists every
entity and field; the point is that the same question has one spelling
across sources — `source_ip` is the attacker's address whether the log
came from a firewall, auditd, or pv-suite, so dashboards, alerts and
Illuminate detections work unchanged.

The pack's `pv-suite audit gim` rule emits the GIM fields beside the
source-specific `audit_*` forms (both forms may be included — the
schema's own note for vendor-specific identifiers):

| the audit KV | the GIM field(s) | entity |
|---|---|---|
| `application=` | `application_name` | application |
| `instance=` | — (rides raw as `audit_instance` — the collector's per-instance grouping key) | application |
| `type=` | `event_action` (the word verbatim: start, command, auth-fail, ...) | event |
| `hash=` | `event_uid` (the chain hash — the event's unique id) | event |
| `result=` | `event_outcome` — `ok`/`bye`/`local` → `success`, `err` → `failure` | event |
| (derived) | `event_severity` + `event_severity_level` — informational/1 by default, medium/3 on an `err` result, high/4 for `auth-fail` | event |
| `reason=` | `event_error_code` (`unsigned` / `bad-mac`) | event |
| `uptime=` | `event_duration` (seconds) | event |
| `peer=` | `source_ip` + `source_port` (the `IP:port` split — the control plane binds loopback v4; a unix peer carries no colon and is skipped) | source |
| `target=` | `destination_ip` + `destination_port` (`unix:` targets skipped) | destination |
| `role=` | `user_name` (the authenticated RBAC principal) | user |
| `user=` | `user_name` (the OS user on the cli connect/disconnect trail) | user |
| `cmd=` | `user_command` (the control command the user invoked) | user |
| (constant) | `event_source_product` = `pv-suite` | event |

The severity pair follows the GIM scale (1 informational, 2 low,
3 medium, 4 high, 5 critical) — `event_severity` is the word,
`event_severity_level` the number.

**What the pack does not do:** Illuminate Core assigns message-type
codes and derives category/subcategory enrichment from them via its
lookup tables — that machinery is licensed content keyed to the shipped
processing packs. The pack emits the GIM field names directly instead;
an operator running Graylog Enterprise/Security can key their own
processing on them, and the audit-trail questions (who ran what from
where, did it succeed, how hard did the gates refuse) already answer in
the normalized spelling:

    event_source_product:pv-suite AND event_action:auth-fail
    event_outcome:failure AND event_severity:high
    user_name:ops AND event_action:command AND event_outcome:success

The `audit_*` fields stay the drill-down truth (the full KV pair set,
nothing lost to the mapping).

## The ingestion routes (pick one)

### 1. Syslog input + extractors — works today, no tool change

`--audit-forward udp://<graylog>:514` (or `tcp://`) with the default
`rfc5424` format, and a Graylog **Syslog UDP/TCP input**. The native line
rides the envelope's message verbatim; the KV words become fields through
one pipeline rule (or a matching extractor set) — the real rules ship in
the content pack above; hand-roll them only to move off the pack's
defaults.

The CEF format (`--audit-forward-format cef`) feeds Graylog's CEF input
the same way — the `cs1`/`cs2`/`cs3` extracted fields carry the chain hash,
the application tag and the instance for the collectors that prefer CEF.

### 2. GELF-native — the proposed third format (the tool change)`--audit-forward-format gelf` (the proposal): one JSON datagram per
event, the KV words as **native GELF fields** — no extractors, no
pipeline parsing, the streams and dashboards key directly:

```json
{"version": "1.1", "short_message": "command peer=10.0.0.9 cmd='set pv 3000' result=ok",
 "host": "pv-cache-1", "level": 4, "_application": "CACHE", "_tag": "daemon", "_instance": "15502",
 "_type": "command", "_hash": "1a07cac1f910", "_peer": "10.0.0.9",
 "_result": "ok", "timestamp": 1699699200.0}
```

Every `key=value` of the message becomes `_<key>` — the uniqueness rule
(docs/SECURITY.md) is what makes that mapping safe. Recommendation: **GELF
for Graylog** (the structured trail is the whole point of the KV
reformat), keep `rfc5424`/`cef` for the SIEMs that speak syslog.

## The streams

The rules below are spelled in the GELF route's `_`-fields; the shipped
pack's route-1 streams route on the raw `message` regex instead (the
StreamRouter runs before the pipelines — a stream rule on a pipeline-set
field never matches) and the same names wear the `audit_` prefix
(`audit_type`, `audit_peer`, `audit_application`, `audit_instance`, `audit_result`, `audit_reason`).

| stream | rule |
|---|---|
| Audit · all | `_exists_:_type` (every family audit line carries it) |
| Audit · commands | `_type:command` |
| Audit · security | `_type:auth-fail` OR `_type:write-refused` OR `_type:write-rejected` OR `_result:err` OR `_exists_:_reason` |
| Audit · lifecycle | `_type:start` OR `_type:shutdown` OR `_type:reload` OR `_type:restore` |
| Audit · writes | `_type:write` OR `_type:write-refused` (the forwarding edge) |

## The dashboards

- **Commands** — `_type:command` per `_application` (and `_instance`) over time, split by
  `_result` (the ok/err share), the top `_peer` values, the `cmd=` word
  cloud.
- **Security** — `_type:auth-fail` and `_result:err reason:*` per `_peer`
  and per `_application`/`_instance` (the unsigned/bad-mac attempts are the tamper signal),
  the write-refused per register range.
- **Lifecycle** — `_type:start` per `_application`/`_instance` (the restart count — a START
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
- **the restart churn** — `_type:start` > 3 in 15 minutes per `_application`/`_instance`
  (the crash loop).
- **the chain break** — NOT a Graylog search: the chain is stateful per
  writer tag, so the off-box verify is `scripts/audit_verify.py` over the
  collected file (the cron), and the collector pages on its FAIL line
  (docs/SECURITY.md's three-tier story).

## The layout (the alerts/ charter)

Shipped content lands here as the operators copy it: the pipeline rule +
the extractor JSON exports, the stream/dashboard definitions, the event
definitions — each as the Graylog UI's own export shape, versioned with
the trail grammar (docs/SECURITY.md gates the drift). The GELF format
proposal rides the tool's `--audit-forward-format` — its wave lands the
format, the README documents the input.
