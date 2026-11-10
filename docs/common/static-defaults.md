# The defaults

Every value knob's default lives in its registry row — the `default`
field of `lib/options.json`, editable with `scripts/edit_options.py`
(conv-typed: int/float/bool/str, the empty input clears to the None
ladder-end). The resolver ladder's last rung reads it: each tool's
`lib/statics.py` builds `DEFAULTS` off the loaded `OPTIONS` rows (the
name's underscore spelling), and `lib/config.py` ladders flag > env >
config > the row's default. The argparse-facing default stays unset —
a wired parser default would shadow the env/config layers (the flag
would never read unset); the parser carries only a non-negates bool's
native False.

`lib/defaults.json` keeps the NON-knob statics: the diagnostics block,
the log levels, the fake's solar times, cloud machines, load curve,
battery limits and scenarios, the bounds with no row of their own (the
fake's `time_scale_max`, the dashboard's `proxy_timeout_s`). The
`defaults` dict is gone from the file — the registry is the one home.

## What carries no default

- **A secret never takes a settable default** — its default is the
  None ladder-end, categorically (six on the cache — `auth-key`,
  `auth-upstream-key`, `control-token`, `control-ops-token`,
  `metrics-token`, `dump-key` — five on the scraper, five on the
  inverter, seven on the dashboard — its `static-dir` and `config-js`
  are startup-only secrets of the same shape: `secret`, `hidden`,
  `restart`, the values never ride the wire, the dump or the rows).
  The gate enforces it: a `default` on a secret row fails the tool —
  a shipped secret default would ride every install.
- **The fake's per-run `seed`** — a per-run choice, no default exists
  to ship (the gate's `NO_ROW_DEFAULT` map names it; the map sits
  empty otherwise).
- **The fake's control-only settings** — the pins and the machines
  (`pv`, `load`, `batt`, `grid`, `soc`, `mppt`, `cloud`, `scenario`,
  `battery-state`, `grid-outage`) take no startup layer at all: the
  config file refuses them, the wire sets them at runtime. Nothing
  for a row default to hold.

The empty-string defaults are the honest derived/off defaults: the
value spells the knob's own off semantics and the falsy chains resolve
it — `control-port` `""` (the socket derives from the listen port),
`metrics-spec` `""` (the built-in `lib/metrics.json` block), the
fake's `time` `""` (the clock runs), beside the older
`dump-path`/`control-trust-uids`/`audit-log` empties (the audit-log
the one dynamic default — no row can hold a per-user path, the falsy
chain resolves the XDG state home at start). `control-ops-verbs`
rides its row as the concrete csv (`show,flush` on the cache, `show`
elsewhere) — the registry's `default_ops_verbs` derivation stays the
one truth, the gate pins the row's default to it.

The min/max bounds on a row gate the LIVE dispatch, not the static
rung: the shipped default may sit below the live floor (the
dump-interval `0` against the row's live min `1` — 0 is the off). The
editor and the gate type-check a default; neither bounds-checks it.

The audit rotation bounds (`audit-max-mb`, `audit-files`) ride both
sides — the daemons' static rungs read the row defaults, the bounds
live in common/runtime/audit.py and the rows repeat them.

## The gate

`scripts/check_options.py` runs four rows per tool:

- **every non-secret flag knob's row carries its default** (or a
  `NO_ROW_DEFAULT` reason) — the static rung is explicit, never a
  silent None;
- **no secret row carries a default** — the None ladder-end,
  categorically (the ruling above);
- **every row default parses as the row's conv** — a str-typed int or
  a JSON NaN would poison the resolver and the renderers downstream;
- **the ops-verbs row's default matches the registry's
  `default_ops_verbs`** — the value the resolver reads and the
  derivation the prose renders cannot drift.
