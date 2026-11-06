# common — the code shared by the pv-suite subprojects

One stdlib-only Python package (imported as `common`) used by
[modbus-scraper](../scraper/README.md), [modbus-cache](../cache/README.md),
the [fake inverter](../inverter/README.md) and the [dashboard](../dashboard/README.md):

| module | what |
|---|---|
| `version.py` | the suite version string: `0.3.0`, or `0.3.0-<short git>` in a checkout |
| `options.py` | the family's option registry — one knob, one source: the `Option` rows (the flag, the env twin, the display group, the live `/`-path name, the control-grammar vocabulary), the argparse parser builder, the set-grammar config parser/renderer (the CLI spelling), the knob dictionary and the `Setting` rows the control grammar speaks |
| `wiresec.py` | the control wire's integrity layer: the full-HMAC frame signing/verification, the token auth, the RBAC roles (admin / the read-only ops shift) |
| `audit.py` | the append-only audit trail (`AuditLog`): `<stamp> AUDIT <PREFIX> <EVENT>`, the chained per-writer hashes, size/daily rotation, `-` = stdout |
| `config.py` | `parse_upstream`/`parse_listen`, the token loading (`load_token_file` — the first line of an **owner-only (0600)** file; `check_token_file_mode` refuses group/world-accessible token files, F12 in docs/AUDIT.md) and the device-profile resolution against the shared [profiles/](../profiles/README.md) |
| `connlimit.py` | the concurrent-connection gate: a total client cap and a per-peer-IP cap on every serving surface |
| `cred.py` | peer-credential lookup for the unix control sockets (`SO_PEERCRED`/`LOCAL_PEERCRED`) — the kernel-vouched trusted peers |
| `manpage.py` | the man-page builder: the pages are GENERATED from the argparse parsers (`--man` prints one; `scripts/gen_man.py` ships them) |
| `protocol.py` | the Modbus TCP wire core: `ModbusError`, `recv_exact`, `exception_frame` |
| `logutil.py` | `UtcFormatter` — UTC log timestamps |
| `human.py` | `secs` — human time for the command reports: ms/s/m/h/d, one unit, always two decimals |

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
diagnostics per tool) and the config-script loaders (each tool resolves its
own registry onto the common grammar).

## License

The `common/` package is licensed under the **BSD 3-Clause License** —
see the repo-root `LICENSE` file.
