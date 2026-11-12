# tests/lib/ — the shared library

`harness.py` is the one implementation every tests/ script rides: the
PV_RUN_DIR gate (a standalone run refuses), the scratch under the
battery's run dir, the NOTE stamp, the check accumulator, the shared
daemon spawn (`start`/`kill_all`), the Modbus frame builders and the pty
trio. The wrapper pre-seeds this dir onto sys.path — the suite bodies
keep the bare `from harness import *`.

The import IS the boot: the gate, the scratch and the stamp all run at
import time; the suite's own paths, port consts and thin frame wrappers
bind after and override. The siblings: `../suites/` (the suite bodies)
and `../battery/` (the runner).
