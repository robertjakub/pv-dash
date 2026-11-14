# manuals — the daemons' references

One generated page per tool, named for the daemon:
`modbus-cache.md`, `modbus-scraper.md`, `fake-inverter.md`,
`dashboard.md`, `modbus-replay.md`. The front-page split
(docs/history/front-page-split.md) made the page the tool's FULL
reference — the READMEs carry the front page only (description, quick
how-to, security, license) — so each page tables the registry surface
(every command, knob and show report the control wire answers, the kind
of each, the flag and the env twin, the default, the value shape) and
walks one canonical ladder of reference sections — The family, Run it,
How it works, The control plane, the Commands/Knobs/Show-reports tables,
Signals, Configuration, Runtime control, Access control, Metrics, Audit
logging, Register maps, Tuning, Diagnostics registers, Deployment, The
docs map (the links into `docs/SECURITY.md`, `docs/specs/ACL.md`,
`docs/DESIGN.md`, `nixos/README.md` and the rest), Source layout,
Troubleshooting, Testing —
with the tool's own extras (the persistence, the trace feed, the
alerting, the chaos, the reverse proxy, the page configuration) slotted
beside; a topic a tool honestly lacks renders as its one-line absence.
Prose where it reads, bullets where they scan, tables where they pin —
and the source layout is an annotated tree. The family-wide stories (the
audit forward, the runner rule, the docs map) are spliced from one
source in the generator — told once, rendered everywhere. The replay
page is the no-control-plane shape: the registry knobs as the flags
table, no commands or show reports.

The pages are **generated** by `dev/generators/manual.py` from the
per-tool registries (`apps/<tool>/lib/options.json`, the
one-knob-one-source rows) plus the per-tool REF data in the generator:

    python3 dev/generators/manual.py          # render the five pages
    python3 dev/generators/manual.py --check  # exit 1 on a stale page

Edit the registry (or the REF data) and re-run, never the markdown. The
[book](../../docs/book/) gathers the five for reading (its Manuals page
includes them); nothing in the suite loads this dir.
