# tests/suites/ — the suite bodies

The real suite modules live here; `tests/<name>.py` are thin wrappers
(runpy, `__name__='__main__'`) so the battery's suite names, the zz_
pgrep copy and the CI legs never change. The wrapper pre-seeds
`tests/lib` onto sys.path — this dir (which run_path prepends) holds no
harness.

The boot is the import: each suite's first line is
`from harness import *` (the PV_RUN_DIR gate, the scratch, the check
accumulator, the frame builders — see `../lib/harness.py`).
