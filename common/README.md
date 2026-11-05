# common — the code shared by the Modbus subprojects

One stdlib-only Python package (imported as `common`) used by
[modbus-scraper](../scrape/README.md), [modbus-cache](../cache/README.md)
and the [fake inverter](../inverter/README.md):

| module | what |
|---|---|
| `version.py` | the suite version string: `0.3.0`, or `0.3.0-<short git>` in a checkout |
| `audit.py` | the append-only audit trail (`AuditLog`): `<stamp> AUDIT <PREFIX> <EVENT>`, size/daily rotation, `-` = stdout |
| `config.py` | `parse_listen`, `load_token_file` and the device-profile resolution against the shared [profiles/](../profiles/README.md) |
| `protocol.py` | the Modbus TCP wire core: `ModbusError`, `recv_exact`, `exception_frame` |
| `logutil.py` | `UtcFormatter` — UTC log timestamps |

How `common` is found:

- **checkout** — the bin scripts put the repo root on `sys.path` (the same
  insert that exposes each subproject's `lib/`), and `common/` sits there
- **nix package** — each tool's `package.nix` installs `common/*.py` into
  `share/<tool>/common/`, next to `lib/`
- **docker image** — the tree is copied to `/pv-suite/common/` (the
  `common` named build context)

Deliberately *not* here (still per-tool): the control-server framework and
the metrics endpoints (textually diverged, tool-specific wording), the
static configuration (`static.json` / `statics.py` — different defaults and
diagnostics per tool) and the ini loaders (the cache logs and continues,
the scraper dies).

## License

The `common/` package is licensed under the **BSD 3-Clause License** —
see the repo-root `LICENSE` file.
