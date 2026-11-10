# The static.json defaults sweep (2026-11-10)

Every value knob's default lives in its tool's `lib/static.json`
`defaults` tree — the resolver ladder's last rung reads the tree entry
by name (`DEFAULTS['key']`), and a gate keeps both directions honest.
Before the sweep the trees carried only part of the defaults: the rest
sat as inline literals in the resolvers, two of them shadowing live
layers (the audit-forward-format row default hid the env twin and the
config line on all four tools; the dashboard's loader-side listen
default hid the `LISTEN` env), and the cache's and fake's trees held a
`metrics_server` entry nothing read.

Landed as 60b3770..09ddea0 (six per-tool commits: cache, scraper,
inverter, dashboard, scripts, docs), with the follow-up that defined
the cache's two remaining derived defaults later the same day
(4ff32a1..04dd50f): `modbus/auth-upstream` defaults to the explicit
`none` (the tree's `auth_upstream` entry — `parse_auth_type` still
normalizes it to `None`) and `cache/ttl` defaults to the flat 30 s
(the tree's `cache_ttl` entry — the 3 × interval `cache_ttl_factor`
derivation and its tree key are gone).

## What entered the trees

- **cache** — `connect_acl`, `write_acl`, `metrics_acl`,
  `write_registers`, `selection`, `audit_forward`,
  `audit_forward_format`, `dump_interval`, and the follow-up's
  `auth_upstream` (`"none"`) + `cache_ttl` (30.0).
- **scraper** — `modbus_offset`, `metric_prefix`, `audit_forward`,
  `audit_forward_format`, `dump_interval`.
- **dashboard** — `audit_forward`, `audit_forward_format`,
  `dump_interval` (and the `static_defaults` listen shadow deleted from
  `dashboard/lib/options.py`).
- **inverter** — `timezone`, `connect_acl`, `audit_forward`,
  `audit_forward_format` (the `STATIC_DEFAULTS` map reads the tree).

The dead `metrics_server: false` entries left the cache's and the
fake's trees — the bool native False is the family default.

## The knobs outside the trees

A flag knob's default is either a `defaults`-tree key or one of the
no-entry shapes below; `scripts/check_options.py` fails the tool when
neither holds. Three classes stay out deliberately:

| Tool | Named no-entry — the reason each | Bools (native False) | Secrets (None) |
|---|---|---|---|
| all four | `auth` — empty = no auth · `control-port` — derives from the listen port · `control-ops-verbs` — the registry's `default_ops_verbs` · `control-trust-uids` — empty = nobody trusted · `audit-log` — empty = the XDG state home · `dump-path` — empty = the state dump is off | | |
| cache | + `profile` — the bundled profile resolves next to the bin | `allow-write`, `local-time`, `control-socket-group`, `metrics-server`, `audit-daily`, `no-audit-log`, `log-access`, `dump-with-cache`, `restore-on-start` | `auth-key`, `auth-upstream-key`, `control-token`, `control-ops-token`, `metrics-token`, `dump-key` |
| scraper | + `metrics-spec` — empty = the built-in `lib/metrics.json` block · `profile` — the bundled profile resolves next to the bin | `grid-positive-import`, `local-time`, `control-socket-group`, `audit-daily`, `no-audit-log`, `log-access`, `restore-on-start` | `auth-key`, `control-token`, `control-ops-token`, `auth-token`, `dump-key` |
| inverter | + `profile` — the bin's bundled sun2000 profile · `seed` — a per-run choice · `time` — empty = the clock runs · `grid-voltage` / `grid-frequency` — the tree's `grid` block (`voltage_v` / `frequency_hz`), read via `statics.GRID` | `static`, `strict`, `allow-write`, `control-socket-group`, `control-log-replies`, `metrics-server`, `audit-daily`, `no-audit-log`, `restore-on-start` | `auth-key`, `control-token`, `control-ops-token`, `metrics-token`, `dump-key` |
| dashboard | + `static-dir`, `config-js` — resolve next to the script | `control-socket-group`, `metrics-server`, `audit-daily`, `no-audit-log`, `log-queries`, `log-access`, `local-time`, `restore-on-start` | `auth-token`, `control-token`, `control-ops-token`, `metrics-token`, `dump-key` |

The classes are enforced differently: the named no-entry knobs must
appear in the gate's `NO_TREE_DEFAULT` map (the common six in
`_COMMON_NO_TREE_DEFAULT`, the per-tool extras beside them), while the
bools and the secrets pass the coverage gate without a reason — the
converter (`o.conv is bool`) and the `o.secret` mark identify them.

## The gate

`scripts/check_options.py` gained two rows per tool:

- **every static.json defaults key is read by lib/** — a dead letter
  fails: a tree entry nothing resolves is a lie waiting to rot. The
  scan reads `DEFAULTS['k']` / `DEFAULTS.get('k')` shapes across the
  tool's `lib/*.py`.
- **every flag knob's default is a defaults-tree key or a named
  no-entry** — the plain underscore spelling of the flag name, one of
  the `DEFAULT_KEYS` renames (`timeout` → `timeout_s`,
  `interval` → `interval_s`, `read-delay` → `read_delay_s`,
  `client-timeout` → `client_timeout_s`,
  `metrics-client-timeout` → `metrics_client_timeout_s`,
  `requests-audit` → `requests_audit_s`), or a `NO_TREE_DEFAULT`
  reason.

## Verified

`check_options.py` ALL PASS (83 rows), `lint_options.py --check`,
`lint_texts.py --check`, `gen_man.py --check` (the man pages byte-stable
— `Option.default` feeds `build_parser` alone, no report surface), the
`family_drift.py` regeneration, and the battery suites (the one
cache-regtest `set merge-gap` failure was the first-suite flake — the
audit trail shows the set replied ok, and the lone clean re-run passed).
Live probes: `AUDIT_FORWARD_FORMAT=cef` resolves on all four,
`LISTEN=0.0.0.0:9999` on the dashboard, and the follow-up's
`AUTH_UPSTREAM=none` / `TTL` ladder verified through `resolve_config`.
