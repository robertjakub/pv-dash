# common — the code shared by the pv-suite subprojects

One stdlib-only Python package (imported as `common`) used by
[modbus-scraper](../scraper/README.md), [modbus-cache](../cache/README.md),
the [fake inverter](../inverter/README.md) and the [dashboard](../dashboard/README.md),
organized into functional subpackages. The shared layer's behavior specs
live in [docs/common/](../docs/common/README.md) — the Modbus reference,
the ACL map, the defaults ladder:

## `render/` — the human-facing rendering

| module | what |
|---|---|
| `texts.py` | the family's static texts, one JSON home (`shared/texts.json` at the tree root — the directory that contains `common/`, the same walk in every layout): the console's faces and reconnect ladder, the ctl's, the welcome banners, the wire's fixed replies, the daemon bind/startup lines — the dotted `T(key)` resolves, the caller applies the `%`-format; `scripts/lint_texts.py --check` gates the references both ways (every reference resolves, every key referenced, no duplicated value) |
| `manpage.py` | the man-page builder: the pages are GENERATED from the argparse parsers (`--man` prints one; `scripts/gen_man.py` ships them) |
| `human.py` | `secs` — human time for the command reports: ms/s/m/h/d, one unit, always two decimals |

## `runtime/` — the process scaffolding + the cross-cutting trail

| module | what |
|---|---|
| `daemon.py` | the daemon-bin scaffolding the family's entry scripts shared as near-copies: the log setup, the default config path, the SIGHUP/SIGTERM watcher threads, the restart-marked state fold, the ops-verb policy check and the dump-posture log line |
| `audit.py` | the append-only audit trail (`AuditLog`): `<stamp> AUDIT <PREFIX> <EVENT>`, the chained per-writer hashes, size/daily rotation, `-` = stdout |
| `logutil.py` | `UtcFormatter` — UTC log timestamps |
| `version.py` | the suite version string: `0.4.2`, or `0.4.2-<short git>` in a checkout |

## `settings/` — the settings plane: one knob, one source

| module | what |
|---|---|
| `options.py` | the family's option registry — one knob, one source (docs/TODO.md): every knob of every tool lives here ONCE as an `Option` row (the flag, the env twin, the display group, the live `/`-path name, the control-grammar vocabulary), the argparse parser builder, the set-grammar config parser/renderer, the knob dictionary, the golden `config_value`, the `Setting` rows the control grammar speaks and the command-namespace listing (`describe_command_node` — the wire's `help <command node>`) |
| `config.py` | `parse_upstream`/`parse_listen`, the token loading (`load_token_file` — the first line of an **owner-only (0600)** file; `check_token_file_mode` refuses group/world-accessible token files, F12 in docs/SECURITY.md) and the device-profile resolution against the shared [profiles/](../profiles/README.md); plus the family's resolver pieces — the set-grammar config-script loader (`load_config_script`), the precedence object (`Resolver`: flags > env > config > defaults), the control-target machinery (`resolve_target`, the unified `parse_control_target`/`resolve_control_target` — one signature), `str_to_bool` and the control-token pairing/charset rules |
| `dump.py` | the family's settings state dumps: the live setting overrides as one JSON file — the write-behind that lets a daemon restart carry its overrides instead of losing them; the shared seal (the version-2 envelope, the HMAC-CTR + mac — a dump path without a key warns, a key refuses an unsealed dump) |

## `wire/` — the signed control wire, both ends

The wire's own defaults tree is `defaults.json` beside the modules — a
flat `cli_*` tree (the timeout/keepalive/reconnect cluster, the
session's idle cap and the line cap; one home for the family, the
tools' `statics.py` alias it).

| module | what |
|---|---|
| `control.py` | the control server's base: the wire tier (the unix/TCP listener with the 0600/0660 mode, the peer-cred trusted peers, the admin/ops roles, the HMAC frame verification — the reply status speaks `ok`/`fail`/`note`/`bye`), the listener's live-rebind family (rev. 22: `set control/port` swaps the socket bind-first, the failed bind rolls back, the sessions keep serving; the F5 refusal guards the live wire through `refuse_tokenless_rebind`/`refuse_token_drop`), the buffered session handler, the registry surfaces (help config / show knobs / the golden `show config`), the family's `command()` walk (the spine: the help/topic ladder, the set/clear pair, the show reports, the request namespace — the subclasses ride the hooks) and the dump/reload family — the four tools subclass it with their grammar wiring and their reports |
| `wiresec.py` | the control wire's integrity layer: the full-HMAC frame signing/verification, the token auth, the RBAC roles (admin / the read-only ops shift) |
| `cred.py` | peer-credential lookup for the unix control sockets (`SO_PEERCRED`/`LOCAL_PEERCRED`) — the kernel-vouched trusted peers |
| `protocol.json` | the Modbus family's one shared tree: the protocol limits (max_pdu/max_count/max_bits/max_registers), the unit range, the read/write FC policy, the exception codes and the registers' type->words map — the three Modbus tools' `statics.py` project it |
| `ctl.py` | the ctl client, one ladder for the family: one command or a stdin batch, the signed exchange, the auth handshake, the daemon-exit bye — the four `*-ctl` bins keep only their prose and constants |
| `cli.py` | the console-style cli client, one implementation: the signed session with its reconnect cycle, the keepalive thread, the readline TAB completion and the typed-command loop with the confirm guards — the four `*-cli` bins keep their pools, candidates ladder, welcome and (the fake) its verb-first loop, passed as a spec dict |

## `serve/` — the serving-surface gates and faces

| module | what |
|---|---|
| `connlimit.py` | the concurrent-connection gate: a total client cap and a per-peer-IP cap on every serving surface |
| `metrics_server.py` | the gated Prometheus text-endpoint skeleton: the bearer 401, the /metrics-only 404, the connlimit gate's immediate 503, the thread start/stop — the cache's, the fake's and the dashboard's endpoints subclass it with their snapshot()/render() |

## `modbus/` — the Modbus TCP implementation

| module | what |
|---|---|
| `protocol.py` | the wire core: the `ModbusError`/`DeviceError` types, `recv_exact`, the MBAP `frame`/`check_head`/`read_frame` helpers, `exception_frame`, the bit `pack_bits`/`unpack_bits`, the `FC_NAMES` table, the suite auth + Waveshare handshakes |
| `client.py` | the shared client ladders: the connect + auth-handshake and reply-validation sequences both client legs speak |
| `server.py` | the shared Modbus-TCP accept ladder and session opener — the family's two Modbus faces (the cache and the fake inverter) ride it with their face objects |
| `writes.py` | the shared write shapes: the human description, the touched span and the consistency check for every write function code |

How `common` is found:

- **checkout** — the bin scripts put the repo root on `sys.path` (the same
  insert that exposes each subproject's `lib/`), and `common/` sits there
- **nix package** — each tool's `package.nix` installs the flat modules and
  every functional subdir into `share/<tool>/common/`, next to `lib/`
- **docker image** — the tree is copied to `/pv-suite/common/` (the
  `common` named build context)

Deliberately *not* here (still per-tool): the command grammars
(`command`/`_apply`/`_get` — each tool's verbs and `_apply` branches) and
the status/inspect reports (tool-specific wording), the metrics endpoints
(snapshot()/render() over the common skeleton — tool-specific gauge
wording), the static configuration (`defaults.json` / `statics.py` —
different defaults and diagnostics per tool) and the config-script
loaders (each tool resolves its own registry onto the common grammar).

## License

The `common/` package is licensed under the **BSD 3-Clause License** —
see the repo-root `LICENSE` file.
