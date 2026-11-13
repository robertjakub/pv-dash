# dev/battery/ — the battery runner's home

The real runner lives here: `battery.py` (the profiles, the port slots,
the tally, the eta history), `battery_status.py` (the live status view)
and `battery_kill.py` (the slot killer — TERM the runner and its tree,
KILL what outlives the grace window). The docs spelling is the nested
path: `python3 dev/battery/battery.py …`, `python3
dev/battery_status` under `dev/battery/` likewise — `tests/` root
holds no loose scripts (the suites live in `../suites/`, the harness in
`../harness/`).
