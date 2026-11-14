# manuals — the daemons' references

One generated page per tool, named for the daemon:
`modbus-cache.md`, `modbus-scraper.md`, `fake-inverter.md`,
`dashboard.md`, `modbus-replay.md`. The front-page split
(docs/history/front-page-split.md) made the page the tool's FULL
reference — the READMEs carry the front page only (description, quick
how-to, security, license) — so each page tables the registry surface
(every command, knob and show report the control wire answers, the kind
of each, the flag and the env twin, the default, the value shape) and
walks one canonical ladder of reference sections — Run it, How it
works, The control plane, the Commands/Knobs/Show-reports tables,
Signals, Configuration, Runtime control, Access control, Metrics, Audit
logging, Register maps, Source layout, Testing — with the tool's own
extras (the persistence, the trace feed, the alerting, the chaos)
slotted beside; a topic a tool honestly lacks renders as its one-line
absence. Bullets and tables, no big paragraphs of text. The replay page
is the no-control-plane shape: the registry knobs as the flags table,
no commands or show reports.

The pages are **generated** by `dev/generators/manual.py` from the
per-tool registries (`apps/<tool>/lib/options.json`, the
one-knob-one-source rows) plus the per-tool REF data in the generator:

    python3 dev/generators/manual.py          # render the five pages
    python3 dev/generators/manual.py --check  # exit 1 on a stale page

Edit the registry (or the REF data) and re-run, never the markdown. The
[book](../../docs/book/) gathers the five for reading (its Manuals page
includes them); nothing in the suite loads this dir.
