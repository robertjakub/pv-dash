# tests/battery/ — the battery runner's home

The real runner lives here: `battery.py` (the profiles, the port slots,
the tally, the eta history), `battery_status.py` (the live status view)
and `battery_kill.py` (the slot killer — TERM the runner and its tree,
KILL what outlives the grace window). `tests/battery.py`,
`tests/battery_status.py` and `tests/battery_kill.py` are thin runpy
wrappers (the twin of the `tests/suites/` split) so the docs spelling
stays flat: `python3 tests/battery.py …`, `python3
tests/battery_status.py`, `python3 tests/battery_kill.py …`.
