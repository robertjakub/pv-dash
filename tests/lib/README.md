# tests/lib/ — the shared library

`harness.py` is the one implementation every tests/ script rides: the
PV_RUN_DIR gate (a standalone run refuses), the scratch under the
battery's run dir, the NOTE stamp, the check accumulator, the shared
daemon spawn (`start`/`kill_all`), the Modbus frame builders and the pty
trio. Each suite body seeds this dir onto sys.path in its first lines
(the two-line boot — see `../suites/README.md`) and keeps the bare
`from harness import *`.

The import IS the boot: the gate, the scratch and the stamp all run at
import time; the suite's own paths, port consts and thin frame wrappers
bind after and override. The siblings: `../suites/` (the suite bodies)
and `../battery/` (the runner).
