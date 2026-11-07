"""pv-suite common: the code shared by the Modbus subprojects (cache,
scrape, inverter) — stdlib only.

One package, imported as `common` from everywhere:
- the checkout: the bin scripts put the repo root on sys.path (the same
  insert that exposes each subproject's lib/), and common/ sits there too
- the nix packages: common/*.py lands in share/<tool>/common/, next to lib/
- the docker images: the common/ tree is copied to /pv-suite/common/

Modules:
- version  — the suite version string (0.4.0 or 0.4.0-<short git>)
- audit    — the append-only audit trail (AuditLog)
- config   — ini/env/CLI plumbing shared by the tools (listen parser,
             token files, device-profile resolution)
- protocol — the Modbus TCP wire core (errors, recv_exact, exception frames)
- logutil  — the UTC log formatter

Deliberately NOT here (still per-tool): the control-server framework and
the metrics endpoints (textually diverged, tool-specific wording), the
static configuration (static.json/statics.py — different defaults and
diagnostics per tool) and the ini loaders (lenient vs fatal).
"""
