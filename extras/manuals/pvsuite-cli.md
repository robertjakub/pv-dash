# pvsuite-cli

> **Experimental — work in progress.** Verified only against simulated
> data (the fake inverter, fuzzing and regression/stress suites), not
> against real hardware.

`pvsuite-cli` is the ONE client for the family's JSON-lines control
servers. One script, five spellings: the four installed client names are
symlinks to this file and the tool comes from the name it was invoked
as, while a bare `pvsuite-cli` takes the tool as the first word. The
control plane itself — the verbs, the tokens, the wire — is documented
in each daemon's manual (`extras/manuals/modbus-cache.md` and its
siblings); this page covers the client side: how the tool resolves, the
three invocation shapes, the console and the shared flags.

## The five spellings

The installed client names are the daemons' `-cli` siblings:

| invocation | controls |
|---|---|
| `modbus-cache-cli` | modbus-cache |
| `modbus-scraper-cli` | modbus-scraper |
| `modbus-fake-cli` | modbus-fake-inverter |
| `dashboard-cli` | dashboard |
| `pvsuite-cli <tool>` | any of the four, spelled on the line |

The name resolution strips an optional `.py` suffix and a `-cli`
suffix, then maps the base — `modbus-cache` to modbus-cache,
`modbus-scraper` to modbus-scraper, `modbus-fake` to
modbus-fake-inverter (the fake's legacy client spelling), `dashboard`
to dashboard.

A bare `pvsuite-cli` takes the tool word as the first argument — the
daemon name (`modbus-cache`, `modbus-scraper`, `modbus-fake-inverter`,
`dashboard`) or the short alias (`cache`, `scraper`, `inverter`;
`dashboard` is its own alias):

```bash
python3 apps/pvsuite-cli.py cache show config
CTL=15509 pvsuite-cli scraper ping
```

An explicit tool word that disagrees with the invocation name is
refused — invoked as `modbus-cache-cli` but told `scraper`, the client
exits 2 with `pick one` rather than guessing. The four daemon names are
also accepted as the first word of any installed client (the explicit
form wins only when it agrees).

## How it loads

Everything after the tool word is the familiar client; the tool's SPEC
— its pools, defaults, socket, labels, special renders — lives in the
tool's own `lib/cli_spec.py`. `pvsuite-cli` only resolves the tool and
loads it: one script, the tool word, then the shared client runner in
`common/wire/cli.py`. Only one tool's `lib/` is ever imported per
invocation, so the shared `lib/` package name never collides.

In the repo layout the script lives at `apps/pvsuite-cli.py` and the
installed client names are symlinks to it —
`modbus-cache-cli.py -> ../../pvsuite-cli.py` beside the daemon's bin,
its three siblings the same shape; the package and the images install
the same links.

## The three invocation shapes

One client, three modes by the invocation shape:

- **one-shot** — command words on the line:
  `modbus-cache-cli show config`. The raw verdict prints
  (`ok ...` / `fail ...`), exit 0 ok, 1 connection or control error,
  2 misuse;
- **piped batch** — a script on stdin, the lines run in order, the
  same raw faces. `#` comments and blank lines are stripped, so a
  config script pipes through unchanged;
- **the console** — a bare terminal opens the interactive session: on
  connect it probes the daemon and greets you with the state line, the
  prompt shows the connected port (`cache:15502 >`). TAB completes
  commands, settings and values with their descriptions (the settings
  group under the registry's own groups, `[values]` beside); `?`
  prints the same in any position; `set`/`clear` confirm `% changed`
  (errors print `% error: <message>`); `request flush cache` /
  `request restart` confirm silently; `shutdown` asks
  `Proceed with shutdown? [confirm]` first.

Console mechanics worth knowing:

- every reply prints through the pager — a text taller than the screen
  pauses at a page (space = the next page, return = one more line,
  `q` = stop the rendering; the command already ran);
- while idle the session sends wire pings so the server's idle timeout
  never drops it (`CLI_KEEPALIVE` seconds, `0` = off);
- when the connection dies anyway, the console retries
  (`--reconnect` attempts, `--reconnect-wait` seconds apart) and
  resumes on the first success;
- a terminal smaller than 20 rows or 64 columns refuses to start;
- the session itself (connect/disconnect, local commands, an aborted
  shutdown) is audited with the `CLI` prefix — the wire commands are
  audited once, by the server.

## Options and environment

The client flags (each daemon's ctl man page carries the same list):

| flag | env | what it does |
|---|---|---|
| `--control-port` | `CTL` | the control server target: a unix socket path or a TCP port on 127.0.0.1, auto-detected when unset |
| `--control-token` | `CONTROL_TOKEN` | the control auth token for TCP; a `file:<path>` value reads the first line of an owner-only 0600 file |
| `--timeout N` | — | the socket timeout in seconds |
| `--reconnect N` | — | console only: the reconnect attempts before giving up, `0` = off |
| `--reconnect-wait N` | — | console only: seconds between the reconnect attempts |
| `--page-size N` | `CLI_PAGE_SIZE` | the console pager's page size, `0` = off, empty = the terminal height; a session-local `page` command retunes it live |
| `--audit-log` | — | the client session's own audit trail: a file path, `-` for stdout, `none` for no local file |
| `--audit-forward` | — | also forward every audit line: `none`, `syslog`, `syslog:/path`, `udp://host[:port]`, `tcp://host[:port]` |
| `--audit-forward-format` | — | the remote forward's envelope: `rfc5424` (default) or `cef` |
| `--audit-max-mb N` | — | rotate the audit log at this size, `0` = off |
| `--audit-files N` | — | rotated audit backups to keep |
| `--no-audit-log` | — | disable the audit trail |

`CLI_KEEPALIVE` (the idle ping interval, seconds, `0` = off) has no
flag twin.

The unix control socket is the default transport and needs no token —
the kernel vouches for the peer. A TCP target (`CTL=15509` or
`--control-port 15509`) is the signed wire: a TCP listener refuses to
start without an admin token (the fake's trusted-LAN posture is the
family's F11 exemption), and the client must carry the matching
`--control-token`/`CONTROL_TOKEN`. The read-only ops token scopes a
session to its verbs — the client does not need to know the role; the
server gates each verb.

## Exit codes

| code | meaning |
|---|---|
| `0` | the command ran / the session ended cleanly |
| `1` | connection or control error |
| `2` | command-line misuse (an unknown tool word, a disagreeing invocation) |

## The docs map

| document | what it is |
|---|---|
| `apps/pvsuite-cli.py` | the resolver — one script, the tool word, the SPEC load |
| each tool's ctl man page | `apps/<tool>/man/<daemon>-cli.1` — the client flags and the console, rendered per tool |
| the daemon manuals | `extras/manuals/modbus-cache.md` and siblings — the verbs, the tokens, the wire, per daemon |
| `docs/SECURITY.md` | the family's security model, the tokens and the roles |

The per-tool verb lists, the setting pools and the example sequences
live in the daemon manuals — the client is one dispatcher; the voices
are the daemons'.
