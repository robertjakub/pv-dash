# pv-suite

The stdlib-only family of PV tools: a Modbus TCP caching proxy, a
Prometheus exporter, a fake inverter to test the stack against, and a
static dashboard — one shared `common/` package, one control grammar, one
audit vocabulary.

This book includes the tools' own READMEs (they stay the primary
documentation; the book makes them navigable — the docs-site TODO item's
mdBook stop-gap). Build it with `mdbook build docs/book` (the `mdbook`
binary is the only tooling the book adds; the suite itself stays
stdlib-only).

{{#include ../../../README.md}}
