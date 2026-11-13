# tests/suites/ — the suite bodies

The real suite modules live here — one file per battery suite, no
twins. Each body's first lines seed the harness home onto sys.path and
boot from it:

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'harness'))
    from harness import *

(the seed exists because this dir holds no copy of the module — and the
`harness` name is the dir's own, so the per-tool `lib` packages can
never shadow it). The battery
resolves `tests/suites/<name>.py` straight off the profile strings, the
zz_ pgrep copy copies the body, and the CI legs run
`python3 tests/suites/<name>.py` — one spelling everywhere, renames
cannot desynchronize.
