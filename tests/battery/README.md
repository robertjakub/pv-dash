# tests/battery/ — the battery runner's home

The real runner lives here: `battery.py` (the profiles, the port slots,
the tally, the eta history) and `battery_status.py` (the live status
view). `tests/battery.py` and `tests/battery_status.py` are thin runpy
wrappers (the twin of the `tests/suites/` split) so the docs spelling
stays flat: `python3 tests/battery.py …`.
