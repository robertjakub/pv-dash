# common — the code shared by the pv-suite subprojects

One stdlib-only Python package (imported as `common`) used by
[modbus-scraper](../scraper/README.md), [modbus-cache](../cache/README.md),
the [fake inverter](../inverter/README.md) and the [dashboard](../dashboard/README.md):

| module | what |
|---|---|
| `version.py` | the suite version string: `0.4.2`, or `0.4.2-<short git>` in a checkout |
| `options.py` | the family's option registry — one knob, one source: the `Option` rows (the flag, the env twin, the display group, the live `/`-path name, the control-grammar vocabulary), the one registry loader the four `lib/options.py` share (`load_registry` — the rows, the `show`/`commands` sections, the choices/defaults wired per tool), the argparse parser builder, the set-grammar config parser/renderer (the CLI spelling), the knob dictionary, the golden `config_value` (the set-grammar form of one knob's effective value over the tool's renames + formatters), the `Setting` rows the control grammar speaks and the command-namespace listing (`describe_command_node` — the wire's `help <command node>`, the `?` shape over the registries' `commands` rows) |
| `texts.py` | the family's static texts, one JSON home (`texts.json` beside the loader): the console's faces and reconnect ladder, the ctl's, the welcome banners, the wire's fixed replies, the daemon bind/startup lines — the dotted `T(key)` resolves, the caller applies the `%`-format; `scripts/lint_texts.py --check` gates the references both ways (every reference resolves, every key referenced, no duplicated value) |
| `wiresec.py` | the control wire's integrity layer: the full-HMAC frame signing/verification, the token auth, the RBAC roles (admin / the read-only ops shift) |
| `ctl.py` | the ctl client, one ladder for the family: one command or a stdin batch, the signed exchange, the auth handshake, the daemon-exit bye — the four `*-ctl` bins keep only their prose and constants |
| `control.py` | the control server's base: the wire tier (the unix/TCP listener with the 0600/0660 mode, the peer-cred trusted peers, the admin/ops roles, the HMAC frame verification — the reply status speaks `ok`/`fail`/`bye`, the internal `err` maps at the frame and the mac signs the wire form) **plus the listener's live-rebind family** (rev. 22: `set control/port` swaps the socket bind-first, the old loop retires by identity, the sessions keep serving; the F5 refusal guards the live wire through `refuse_tokenless_rebind`/`refuse_token_drop` — `TOKENLESS_TCP = 'allow'` exempts, the fake's F11 posture), the buffered session handler, the bye-frame announce ladder, the registry surfaces (help config / show knobs / the golden `show config` — the resolved startup dict over the `CFG_KEYS`/`CFG_FORMATTERS` wiring each tool's registry passes), the dump/reload family (the write-behind dump, the restore, the whole-daemon reload with its re-exec) **and the family's `command()` walk** — the whole wire verb grammar once: the help/topic ladder, the set/unset pair, the show walk and the request namespace, with the tool hooks (`SHOW_REPORTS`, `command_tool`, `command_set_special`, `_after_set`, the show-walk tail and the unknown-word spellings; `RELOAD_CONFIG = False` keeps the cache's and the fake's reload-config row decision open) — the four tools subclass it with their `_apply`/`_get` branches, their registry rows and their reports |
| `cli.py` | the console-style cli client, one implementation: the signed session with its reconnect cycle, the keepalive thread, the readline TAB completion and the typed-command loop with the confirm guards — the four `*-cli` bins keep their pools, candidates ladder, welcome and (the fake) its verb-first loop, passed as a spec dict |
| `audit.py` | the append-only audit trail (`AuditLog`): `<stamp> AUDIT <PREFIX> <EVENT>`, the chained per-writer hashes, size/daily rotation, `-` = stdout |
| `config.py` | `parse_upstream`/`parse_listen`, the token loading (`load_token_file` — the first line of an **owner-only (0600)** file; `check_token_file_mode` refuses group/world-accessible token files, F12 in docs/AUDIT.md) and the device-profile resolution against the shared [profiles/](../profiles/README.md); plus the family's resolver pieces — the set-grammar config-script loader (`load_config_script`), the precedence object (`Resolver`: flags > env > config > defaults), the control-target machinery (`resolve_target`, and the unified `parse_control_target`/`resolve_control_target` — one signature, the tool's `listen_port` + its socket template as the arguments), `str_to_bool` and the control-token pairing/charset rules |
| `connlimit.py` | the concurrent-connection gate: a total client cap and a per-peer-IP cap on every serving surface |
| `metrics_server.py` | the gated Prometheus text-endpoint skeleton: the bearer 401, the /metrics-only 404, the connlimit gate's immediate 503, the acl_allows/acl_refused hooks (the refusal logs the one `connection rejected` line on the tool's logger and closes without a reply), the thread start/stop — the cache's, the fake's and the dashboard's endpoints subclass it with their snapshot()/render() |
| `cred.py` | peer-credential lookup for the unix control sockets (`SO_PEERCRED`/`LOCAL_PEERCRED`) — the kernel-vouched trusted peers |
| `manpage.py` | the man-page builder: the pages are GENERATED from the argparse parsers (`--man` prints one; `scripts/gen_man.py` ships them) |
| `modbus/` | the Modbus TCP implementation, one package for the family: `protocol.py` (the wire core — the `ModbusError`/`DeviceError` types, `recv_exact`, the MBAP `frame`/`check_head`/`read_frame` helpers, `exception_frame`, the bit `pack_bits`/`unpack_bits`, the `FC_NAMES` table, the suite auth + Waveshare handshakes), with the shared client ladders and the write shapes layered beside it |
| `logutil.py` | `UtcFormatter` — UTC log timestamps |
| `human.py` | `secs` — human time for the command reports: ms/s/m/h/d, one unit, always two decimals |

How `common` is found:

- **checkout** — the bin scripts put the repo root on `sys.path` (the same
  insert that exposes each subproject's `lib/`), and `common/` sits there
- **nix package** — each tool's `package.nix` installs `common/*.py` and
  `texts.json` into `share/<tool>/common/`, next to `lib/`
- **docker image** — the tree is copied to `/pv-suite/common/` (the
  `common` named build context)

Deliberately *not* here (still per-tool): the `_apply`/`_get` branches
(each tool's own verb semantics behind the common `command()` walk) and
the status/inspect reports (tool-specific wording), the metrics endpoints
(snapshot()/render() over the common skeleton — tool-specific gauge
wording), the static configuration (`static.json` / `statics.py` —
different defaults and diagnostics per tool) and the config-script
loaders (each tool resolves its own registry onto the common grammar).

## License

The `common/` package is licensed under the **BSD 3-Clause License** —
see the repo-root `LICENSE` file.
