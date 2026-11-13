# tests/battery/ — the battery runner's home

The real runner lives here: `battery.py` (the profiles, the port slots,
the tally, the eta history), `battery_status.py` (the live status view)
and `battery_kill.py` (the slot killer — TERM the runner and its tree,
KILL what outlives the grace window). The docs spelling is the nested
path: `python3 tests/battery/battery.py …`, `python3
tests/battery_status` under `tests/battery/` likewise — `tests/` root
holds no loose scripts (the suites live in `../suites/`, the harness in
`../harness/`).
