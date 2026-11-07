# DRAFT wave — the commands rows speak live (the `live` + `group` fields)

Status: LANDED Nov 7 2026 — the four loaders speak live AND the internal
names flattened to the family's dashed spelling (section 4's shape is
real: `request-dump` + `live: request/dump`, `poll-now` +
`live: poll/now`, … — every row spells its live, the wire is
byte-identical). The draft stands as the record. RIDER, same landing:
the commands rows may carry an `internal` flag (the machinery's own
words — the wire answers, the cli never offers or lists them) and
`ping` joins every registry as the first internal row (the cache's and
the fake's rows are new — their wire always answered `ok pong`; the
scraper's and the dashboard's rows leave the ? listing), `help` follows
it internal everywhere (the audit's one gap — the session verbs
help/?/ping/quit were already wiresec's RBAC-exempt SESSION_VERBS, the
rows make the registry say so), and the fake's register/coil/discrete
cli pin died with its spec plumbing (the rowing question filed in
docs/TODO.md's control-plane section). FOLLOW-UP, same day: the cli
faces spell the '/'-paths as words — the ? listing renders `request
clear cache` (the options' dictionary rule) and the first TAB position
walks the command paths segment-wise (a slash never renders or
inserts). SECOND FOLLOW-UP: the lint files the namespaces — the missing
node rows auto-add (the path-named, no-live spelling, a TODO
setting-help), the childless nodes are asked to be removed, and a knob
may carry the double meaning (the scraper's `auth` knob is now its
`auth/` namespace's node).

---

## 1) the fields

| field | today | after |
|-------|-------|-------|
| `name` | the wire spelling ('/'-path, the loaders key everything by it) | INTERNAL — the registry key only (the file-wide uniqueness stays lint's); never typed, never rendered; free to be dashed/anything in a later rename |
| `live` | does not exist | OPTIONAL — the wire spelling as a '/'-path (`request/clear/cache` is `request clear cache`); absent → the row's `name` (the show rows' `r.get('live') or r['name']` fallback). Every row today falls back — **zero wire change** |
| `group` | read by the loaders (`r.get('group', '')`) but carried by no row | unchanged machinery, now first-class like the show rows' — `word_groups` buckets the cli `?`/help listings under it, `''` = the bare top |
| `hidden` | truthy | unchanged |

## 2) the loaders (×4 — one shape, indentation per file)

The four identical blocks (cache/lib/options.py:61-68; scraper 4-space
body) become:

```python
        # the control commands: the registries' `commands` rows (the wire's
        # verb list — the console help, the completion pools and the editor
        # read these). The wire spells the row's `live` — the show rows'
        # fallback (the live when the row spells one, else the name); the
        # name is the registry key, never typed. The maps key by the wire
        # word.
        cmd_rows = meta.get('commands') or []
        commands, cmd_help, cmd_groups, cmd_hidden = [], {}, {}, set()
        for r in cmd_rows:
            w = r.get('live') or r['name']
            commands.append(w)
            cmd_help[w] = r.get('help', '')
            cmd_groups[w] = r.get('group', '')
            if r.get('hidden'):
                cmd_hidden.add(w)
        COMMANDS = tuple(commands)
        COMMAND_HELP = cmd_help
        COMMAND_GROUPS = cmd_groups
        COMMAND_HIDDEN = frozenset(cmd_hidden)
```

(Explicit loop — the genexp-scoping lesson. The module-level empties at
the loaders' tails stay as-is.)

## 3) the consumers — who moves, who doesn't

- **The four clis** — `command_pool()`/`HELP`/`describe_word` ride the
  four exports, which are now live-keyed: the TAB pools, the `?` listing
  buckets and the describes speak live for free. NO bin edits.
- **The ctls** — no registry import (prose only): nothing.
- **The four control.py dispatches** — word-keyed (`low == 'request
  dump'`); the fallback preserves every current spelling. Zero change.
  **The rule**: a row whose `live` differs from its `name`'s words is a
  RENAME wave — the control.py dispatch strings and the ten suites follow
  (set_live.py's docstring warning, now for commands).
- **check_options.py** — the commands gate (clean unique word-path with a
  description) reads `mod.COMMANDS`, live-derived: self-covers. No script
  change. Two rows must not share a live (the dict keys would silently
  collapse) — the existing dupes gate catches it.
- **lint_options.py** — `live`/`group` are already KNOWN + ranked
  (name → group → live → … → help → hidden): a commands row carrying them
  re-renders canonically as-is. No script change. (The --propose
  drafters stay advisory, as today.)

## 4) the registries — no row content changes required

(Superseded at landing: the names flattened to the dashed spelling, every
slash row now spells its `live` — see the status above.)

Every current name already IS the wire spelling (the request-namespace
wave put them there); the fields land as machinery. The shape a later row
may spell (the name freed, the wire kept):

```json
{
    "name": "poll-now",
    "live": "poll/now",
    "help": "wake the poll loop immediately"
}
```

A row with a listing bucket:

```json
{
    "name": "request/dump",
    "group": "state",
    "help": "write the state dump: the live setting overrides, sealed (when the daemon has a dump path)",
    "hidden": "on"
}
```

Group VALUES for the command rows are NOT proposed here (the show rows
carry none either) — the machinery accepts them the day the listings
should bucket. The hand-formatted quirks (`"hidden": "on"` beside
`"hidden": true` in the cache) stay — surgical edits only.

## 5) doc ripples

- The four `lib/options.py` header docstrings + the loader comment block
  (the diff above) — the only prose that describes the commands rows.
- CHANGELOG Unreleased (Changed — the mechanism note).
- docs/OPTIONS.md — gen_options.py does not consume the commands section:
  no regen.
- The man pages, the READMEs — no user-visible change: untouched.
- The per-tool TODOs — mechanism-only wave: skipped per convention.
- This draft file.

## 6) verification + commit

- `python3 scripts/check_options.py` + `python3 scripts/lint_options.py
  --check` (the unchanged rows must re-render byte-for-byte).
- The TEN suites — no wire change, the pools/help render identically; the
  suites type the wire words and stay untouched.
- `nix flake check`.
- Commit: one `everywhere:` commit — the four loaders are one shape ×4,
  no per-tool deltas; the CHANGELOG entry rides it (this draft's landing
  note with it).
