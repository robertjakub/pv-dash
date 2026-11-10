# The defaults sweep (2026-11-10)

Every value knob's default lives in its tool's `lib/defaults.json`
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
derivation and its tree key are gone). A second follow-up put **every
bool's native False in the trees too** (the store_true flags resolved
their False inline before) and the coverage gate dropped its
bool-converter exemption — a bool without its tree entry fails like
any other knob.

## What entered the trees

- **cache** — `connect_acl`, `write_acl`, `metrics_acl`,
  `write_registers`, `selection`, `audit_forward`,
  `audit_forward_format`, `dump_interval`, the follow-up's
  `auth_upstream` (`"none"`) + `cache_ttl` (30.0), and the nine bools
  (`allow_write`, `local_time`, `log_access`, `metrics_server`,
  `audit_daily`, `no_audit_log`, `dump_with_cache`,
  `restore_on_start`, `control_socket_group`).
- **scraper** — `modbus_offset`, `metric_prefix`, `audit_forward`,
  `audit_forward_format`, `dump_interval`, and the seven bools
  (`grid_positive_import`, `local_time`, `log_access`,
  `control_socket_group`, `audit_daily`, `no_audit_log`,
  `restore_on_start`).
- **dashboard** — `audit_forward`, `audit_forward_format`,
  `dump_interval` (and the `static_defaults` listen shadow deleted from
  `dashboard/lib/options.py`), plus the six bools
  (`local_time`, `metrics_server`, `audit_daily`, `no_audit_log`,
  `control_socket_group`, `restore_on_start` — `log_queries` and
  `log_access` were already tree entries).
- **inverter** — `timezone`, `connect_acl`, `audit_forward`,
  `audit_forward_format`, and the nine bools (`static`, `strict`,
  `allow_write`, `control_socket_group`, `control_log_replies`,
  `metrics_server`, `audit_daily`, `no_audit_log`,
  `restore_on_start` — the `STATIC_DEFAULTS` map reads the tree).

The sweep's dead `metrics_server: false` removal (the cache's and the
fake's) was undone by the bools' follow-up — the entries are back, now
read by the resolvers' static rungs like every other tree key.

## The knobs outside the trees

A flag knob's default is either a `defaults`-tree key or one of the
no-entry shapes below; `scripts/check_options.py` fails the tool when
neither holds. One class stays out by named reason (the secrets are
banned outright, after the table) — the bools started there and moved
in: the follow-up put every bool's native False in the tree too (the
store_true flag absent resolves False through the tree entry like any
value knob), and the coverage gate dropped its bool-converter
exemption, so a bool without its tree entry fails.

| Tool | Named no-entry — the reason each |
|---|---|
| all four | `auth` — empty = no auth · `control-port` — derives from the listen port · `control-ops-verbs` — the registry's `default_ops_verbs` · `control-trust-uids` — empty = nobody trusted · `audit-log` — empty = the XDG state home · `dump-path` — empty = the state dump is off |
| cache | + `profile` — the bundled profile resolves next to the bin |
| scraper | + `metrics-spec` — empty = the built-in `lib/metrics.json` block · `profile` — the bundled profile resolves next to the bin |
| inverter | + `profile` — the bin's bundled sun2000 profile · `seed` — a per-run choice · `time` — empty = the clock runs · `grid-voltage` / `grid-frequency` — the tree's `grid` block (`voltage_v` / `frequency_hz`), read via `statics.GRID` |
| dashboard | + `static-dir`, `config-js` — resolve next to the script |

The secrets are absent from the table by ruling: **a secret never
takes a settable default** — its default is the None ladder-end,
categorically (six on the cache — `auth-key`, `auth-upstream-key`,
`control-token`, `control-ops-token`, `metrics-token`, `dump-key` —
five on the other three). The gate enforces it: a `defaults`-tree key
naming a secret fails the tool even before a resolver could wire it —
a shipped secret default would ride every install.

The enforcement is one rule plus two outs: every flag knob's default
names its tree entry; the named no-entry knobs must appear in the
gate's `NO_TREE_DEFAULT` map (the common six in
`_COMMON_NO_TREE_DEFAULT`, the per-tool extras beside them); the
secrets fail the outright ban.

The audit rotation bounds (`audit_max_mb`, `audit_files`) ride both
sides — the daemons configure from them, the client scripts render
them — so they are daemon defaults and stay out of the trees
too.

## The gate

`scripts/check_options.py` gained three rows per tool:

- **every defaults.json defaults key is read by lib/** — a dead letter
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
  reason. The bools take no exemption: a missing bool entry fails
  (proven on a doctored tree that dropped `allow_write`).
- **no defaults-tree key names a secret** — the secret's default is
  None, never a settable default (the ruling above; proven to fail on
  a doctored tree).

## Verified

`check_options.py` ALL PASS (87 rows — the secret-ban row included,
proven to fail on a doctored `auth_key` tree entry), `lint_options.py --check`,
`lint_texts.py --check`, `gen_man.py --check` (the man pages byte-stable
— `Option.default` feeds `build_parser` alone, no report surface), the
`family_drift.py` regeneration, and the battery suites (the one
cache-regtest `set merge-gap` failure was the first-suite flake — the
audit trail shows the set replied ok, and the lone clean re-run passed).
Live probes: `AUDIT_FORWARD_FORMAT=cef` resolves on all four,
`LISTEN=0.0.0.0:9999` on the dashboard, and the follow-up's
`AUTH_UPSTREAM=none` / `TTL` ladder verified through `resolve_config`.
