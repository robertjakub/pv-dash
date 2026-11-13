# manuals — the daemons' control-wire references

One generated page per daemon, named for the daemon it speaks to:
`modbus-cache.md`, `modbus-scraper.md`, `fake-inverter.md`,
`dashboard.md`. Each page tables every command, knob and show report
the daemon's control wire answers — the kind of each (command,
namespace, settable, startup-only, show-only), the flag and the env
twin, the value shape, the wire's own description.

The pages are **generated** by `dev/generators/manual.py` from the
per-tool registries (`apps/<tool>/lib/options.json`, the
one-knob-one-source rows):

    python3 dev/generators/manual.py          # render the four pages
    python3 dev/generators/manual.py --check  # exit 1 on a stale page

Edit the registry and re-run, never the markdown. The
[book](../../docs/book/) gathers the four for reading (its Manuals page
includes them); nothing in the suite loads this dir.
