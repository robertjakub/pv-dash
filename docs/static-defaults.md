# The defaults trees

Every value knob's default lives in its tool's `lib/defaults.json`
`defaults` tree — the resolver ladder's last rung reads the tree entry
by name (`DEFAULTS['key']`), and a gate keeps both directions honest.
No knob carries an inline literal default: a bool's native False sits
in the tree like any value knob's default, and a missing bool entry
fails the gate.

## The knobs outside the trees

Every settable default names its tree entry — the plain underscore
spelling of the flag name or one of the gate's `DEFAULT_KEYS` renames.
What stays out, by ruling:

- **A secret never takes a settable default** — its default is the
  None ladder-end, categorically (six on the cache — `auth-key`,
  `auth-upstream-key`, `control-token`, `control-ops-token`,
  `metrics-token`, `dump-key` — five on the scraper and the inverter,
  seven on the dashboard — its `static-dir` and `config-js` are
  startup-only secrets of the same shape: `secret`, `hidden`,
  `restart`, the values never ride the wire, the dump or the tree).
  The gate enforces it: a `defaults`-tree key naming a secret fails
  the tool even before a resolver could wire it — a shipped secret
  default would ride every install.
- **The fake's per-run `seed`** — a per-run choice, no default exists
  to ship (the gate's `NO_TREE_DEFAULT` map names it; the map sits
  empty otherwise).
- **The fake's control-only settings** — the pins and the machines
  (`pv`, `load`, `batt`, `grid`, `soc`, `mppt`, `cloud`, `scenario`,
  `battery-state`, `grid-outage`) take no startup layer at all: the
  config file refuses them, the wire sets them at runtime. Nothing
  for the tree to hold.

The empty-string entries are the honest derived/off defaults: the tree
value spells the knob's own off semantics and the falsy chains resolve
it — `control_port` `""` (the socket derives from the listen port),
`metrics_spec` `""` (the built-in `lib/metrics.json` block), the
fake's `time` `""` (the clock runs), beside the older
`dump_path`/`control_trust_uids`/`audit_log` empties (the audit-log
the one dynamic default — the tree cannot hold a per-user path, the
falsy chain resolves the XDG state home at start). `control_ops_verbs`
rides the tree as the concrete csv (`show,flush` on the cache, `show`
elsewhere) — the registry's `default_ops_verbs` derivation stays the
one truth, the gate pins the literal to it.

The audit rotation bounds (`audit_max_mb`, `audit_files`) ride both
sides — the daemons' static rungs read their tree entries, the client
scripts render the same entries.

## The gate

`scripts/check_options.py` runs four rows per tool:

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
- **the tree's `control_ops_verbs` matches the registry's
  `default_ops_verbs`** — the literal the resolver reads and the
  derivation the prose renders cannot drift.
- **no defaults-tree key names a secret** — the secret's default is
  None, never a settable default (the ruling above).
