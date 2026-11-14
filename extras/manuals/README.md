# manuals — the book-style operator pages

Full documentation, book style: one page per tool app, written to be
read front to back — the family picture, how it works, every knob, the
control plane, the access model, deployment, troubleshooting. The pages
are **hand-written markdown** and nothing in the repo's build or
runtime path consumes them (the `extras/` convention).

## The pages

- [modbus-cache.md](modbus-cache.md) — the Modbus TCP caching proxy for
  single-client devices (the daemon + `modbus-cache-cli`).
- [modbus-scraper.md](modbus-scraper.md) — the Modbus poller that turns
  register reads into Prometheus `/metrics` (the daemon +
  `modbus-scraper-cli`).
- [modbus-fake-inverter.md](modbus-fake-inverter.md) — the simulator
  standing in for a device: profiles, the battery machine, scenarios,
  chaos, scaled time (the daemon + `modbus-fake-cli`).
- [dashboard.md](dashboard.md) — the one-page UI and its small HTTP
  server over Prometheus (the daemon + `dashboard-cli`).
- [modbus-replay.md](modbus-replay.md) — capture a device's traffic,
  replay it as a stand-in server (+ `modbus-replay-dump`).
- [pvsuite-cli.md](pvsuite-cli.md) — the ONE client behind the four
  installed `-cli` names: the tool resolution, the invocation shapes,
  the console.

## The contract with the reference

The normative reference stays the daemon's `--help` and the generated
man page (`<daemon> --man`, the shipped `man/*.1`): the manuals distill
those pages and the knob registries (`apps/<tool>/lib/options.json`)
into the narrative — when a manual and a man page disagree, the man
page wins and the manual gets fixed.

## The gates

The tree's links gate (`dev/gates/links.py`) walks these pages like any
hand-written doc: every relative link resolves and every rooted
path-shaped inline-code token names something that exists. Nothing else
consumes them — no generator, no book include, no README pointer is
required.
