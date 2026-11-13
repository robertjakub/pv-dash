# tests/suites/ — the suite bodies

The real suite modules live here — one file per battery suite, no
twins. Each body's first lines seed the harness home onto sys.path and
boot from it:

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'lib'))
    from harness import *

(the seed exists because this dir holds no `lib/` of its own — the
per-tool `lib` packages must never shadow `tests/lib`). The battery
resolves `tests/suites/<name>.py` straight off the profile strings, the
zz_ pgrep copy copies the body, and the CI legs run
`python3 tests/suites/<name>.py` — one spelling everywhere, renames
cannot desynchronize.
