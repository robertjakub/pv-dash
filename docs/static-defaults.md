# The defaults trees

Every value knob's default lives in its tool's `lib/defaults.json`
`defaults` tree — the resolver ladder's last rung reads the tree entry
by name (`DEFAULTS['key']`), and a gate keeps both directions honest.
No knob carries an inline literal default: a bool's native False sits
in the tree like any value knob's default, and a missing bool entry
fails the gate.

## The knobs outside the trees

A flag knob's default is either a `defaults`-tree key or one of the
no-entry shapes below; `scripts/check_options.py` fails the tool when
neither holds.

| Tool | Named no-entry — the reason each |
|---|---|
| all four | `control-port` — derives from the listen port · `control-ops-verbs` — the registry's `default_ops_verbs` |
| scraper | + `metrics-spec` — empty = the built-in `lib/metrics.json` block |
| inverter | + `seed` — a per-run choice · `time` — empty = the clock runs · `grid-voltage` / `grid-frequency` — the tree's `grid` block (`voltage_v` / `frequency_hz`), read via `statics.GRID` |

The secrets are absent from the table by ruling: **a secret never
takes a settable default** — its default is the None ladder-end,
categorically (six on the cache — `auth-key`, `auth-upstream-key`,
`control-token`, `control-ops-token`, `metrics-token`, `dump-key` —
five on the scraper and the inverter, six on the dashboard — its
`static-dir` and `config-js` are startup-only secrets of the same
shape: `secret`, `hidden`, `restart`, the values never ride the wire,
the dump or the tree). The gate enforces it: a `defaults`-tree key
naming a secret fails the tool even before a resolver could wire it —
a shipped secret default would ride every install.

The enforcement is one rule plus two outs: every flag knob's default
names its tree entry; the named no-entry knobs must appear in the
gate's `NO_TREE_DEFAULT` map (the common two in
`_COMMON_NO_TREE_DEFAULT`, the per-tool extras beside them); the
secrets fail the outright ban.

The audit rotation bounds (`audit_max_mb`, `audit_files`) ride both
sides — the daemons' static rungs read their tree entries, the client
scripts render the same entries.

### The graduation ledger — the proposals for what remains

The empty-string convention is the pattern: the tree value spells the
knob's own off/derived semantics, the falsy chains resolve it exactly
as the inline literals did, the rung names the entry. The shipped
examples: `control_trust_uids` `""` = nobody trusted, `dump_path` `""`
= the state dump is off, `audit_log` `""` = the XDG state home's
audit.log (the one dynamic default — the tree cannot hold a per-user
path, the falsy chain resolves it at start), and the three Modbus
tools' `modbus_profile` `"sun2000"` plus `modbus_auth` `"none"` (the
bare names, resolved through the shared profiles/ walk and
`parse_auth_type`'s fold to `None`).

| Knob | Proposal | Ruling |
|---|---|---|
| `control-port` (all four) | `"control_port": ""` — the empty = the derived socket (the template against the listen port; the one derived default the tree cannot hold verbatim, the audit-log shape) | TODO |
| `control-ops-verbs` (all four) | `"control_ops_verbs": "<the concrete csv>"` — the registry keeps the parse/validate; a gate row would diff the tree's literal against `default_ops_verbs` so the two cannot drift | TODO — needs the drift-diff gate row first |
| `metrics-spec` (scraper) | `"metrics_spec": ""` — the empty = the built-in `lib/metrics.json` block | TODO |
| `time` (inverter) | `"time": ""` — the empty = the clock runs | TODO |
| `seed` (inverter) | — | STAYS OUT — a per-run choice; no default exists to ship |
| `grid-voltage`, `grid-frequency` (inverter) | — | BACKED — the tree's `grid` block (`voltage_v` / `frequency_hz`) via `statics.GRID`; the row only documents the indirect read |
| `static-dir`, `config-js` (dashboard) | — | STAYS OUT — startup-only secrets of the `dump-key` shape; the outright ban holds (a shipped path default would ride every install) |

## The gate

`scripts/check_options.py` runs three rows per tool:

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
  `requests-audit` → `requests_audit_s`,
  `profile` → `modbus_profile`), or a `NO_TREE_DEFAULT` reason. The
  bools take no exemption: a missing bool entry fails.
- **no defaults-tree key names a secret** — the secret's default is
  None, never a settable default (the ruling above).
