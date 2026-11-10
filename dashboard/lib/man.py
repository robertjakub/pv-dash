#!/usr/bin/env python3
"""The dashboard's man pages, generated (common/render/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff. scripts/gen_man.py writes the shipped man/*.1 from these;
`dashboard --man` (and the ctl/cli's --man) prints the same page."""
from common.render.manpage import page, options_section

DATE = '2026-11-05'
VERSION = 'pv-suite 0.4.2'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The dashboard(1) page: the OPTIONS from the parser, the prose from
    the README's serving/proxy/control story."""
    description = """\
Static single-page home PV monitoring dashboard (energy flow diagram,
energy summary and chart) fed by Prometheus through the bundled
stdlib-only proxy: the browser loads the static app from the server, the
app's queries go to \\fB/prom\\fR and are proxied to the upstream
Prometheus (\\fB--upstream\\fR). The front-end configuration is served as
/config.js (the SOLAR_CONFIG object; the battery panels are always on
\\(em battery support is always enabled).
.PP
The HTTP surface is the tool's serving surface: the connection caps
(\\fB--max-clients\\fR total, \\fB--max-conn-per-ip\\fR per peer, extras
get an immediate 503), the idle keep-alive kick (\\fB--client-timeout\\fR),
the bearer token (\\fB--auth-token\\fR \\(em mandatory beyond loopback:
a token-less non-loopback bind refuses to start, F21; the `?auth=` query
bootstraps the session cookie). The default bind is the loopback.
.PP
The JSON-lines control server (\\fB--control-port\\fR, talked to with
\\fBdashboard-ctl\\fR(1) and \\fBdashboard-cli\\fR(1)) inspects and steers
the running server: the live settings (the caps, the log surface), the
config reload, the graceful shutdown. With a control
token configured the wire is HMAC-signed: every command and reply carries
the full sha256 of its payload, keyed by the token (common/wire/wiresec.py)
\\(em a token-holding client verifies both directions, and over TCP the
signed commands are mandatory. The command string folds to the grammar's
printable 8-bit before the server decides on it (NFKD, then the
printable-ascii range only \\(em \\fBshöw\\fR runs as \\fBshow\\fR); the mac
still certifies the client's exact bytes. A second, read-only token
(\\fB--control-ops-token\\fR) authenticates into its policy's verbs
only (the default policy: show)
\\(em the ops shift against the admin key, both roles audited."""
    signals = """.SH SIGNALS
.TP
.B SIGHUP
re-read the config file and apply what is live (the same path as the
control server's request reload); the listen address and port are bound
and stay.
.TP
.BR SIGTERM ", " SIGINT
graceful shutdown (the connected consoles get the daemon-exit frame)."""
    control = """.SH CONTROL
The control server speaks JSON lines ({"cmd": "..."} ->
{"status": "ok|fail|bye", "text": "..."}; TCP requires the token when
configured and refuses to start without one). Commands:
\\fBset\\fR/\\fBunset\\fR/\\fBshow\\fR/\\fBhelp\\fR (the settings: max-clients,
client-timeout, max-conn-per-ip, log-access, log-queries,
log-level, metrics acl \\(em the /metrics IP gate at accept, the table
show \\fBshow metrics acl table\\fR \\(em and the startup-only secrets:
control token, the ops token, metrics token \\(em the wire refuses
set/unset, the value never rendering \\(em
\\fBshow <secret>\\fR refuses), \\fBshow connections\\fR
(the live HTTP clients), \\fBshow version\\fR, \\fBshow knobs\\fR
(the dictionary of the registry), \\fBinspect\\fR,
\\fBrequest reload-config\\fR (the SIGHUP path), \\fBrequest reload\\fR (the
whole-daemon restart that keeps the sets: the live overrides save to a
state file beside the config, the process re-execs, the fresh daemon
re-applies them once), with a dump path configured (\\fB--dump-path\\fR):
\\fBrequest dump\\fR / \\fBrequest restore\\fR (the overrides as one 0600
integrity-hashed JSON; \\fB--dump-key\\fR seals it \\(em the state rides
encrypted, a restore refuses a wrong or missing key;
\\fB--restore-on-start\\fR loads it at start, \\fB--dump-interval\\fR
rewrites it on a timer),
\\fBshutdown\\fR, \\fBquit\\fR. The control listener rides the family's
live rebind: \\fBset control port\\fR (a unix path, a TCP port on
127.0.0.1, or off) swaps the socket without dropping the connected
sessions \\(em a tokenless TCP bind still refuses (F5) \\(em and the
family's control knobs all set live: \\fBcontrol ops verbs\\fR (the
read-only role's policy), \\fBcontrol trust-uids\\fR (the peer-cred
list), \\fBcontrol socket-group\\fR (0660 instead of 0600, the live
socket re-modes). See
.BR dashboard-ctl (1)
and
.BR dashboard-cli (1)."""
    security = """.SH SECURITY
The page and the proxy speak the F13 shape (F21 closed): the bearer token
(\\fB--auth-token\\fR, constant-time) is mandatory beyond loopback \\(em a
token-less non-loopback bind refuses to start \\(em and the loopback bind
serves tokenless; the `?auth=<token>` query exchanges for an HttpOnly
session cookie, the raw Bearer header stays for scripts. The dashboard's
own /metrics endpoint (when \\fB--metrics-server\\fR serves it) speaks the
family's one stack: the F13 refusal, the \\fB--metrics-acl\\fR IP gate at
accept (a client off the ACL is closed without a reply), the caps.
Terminate TLS at
an authenticating reverse proxy for anything beyond localhost (plain HTTP
carries the token in the clear \\(em the F14 answer). The
control surface is loopback-only (TCP) or a 0600 unix socket (0660 with
\\fB--control-socket-group\\fR); a TCP
control port without a token refuses to start (F5); with a token the wire
is signed and the commands/replies verify end to end; a second, read-only
ops token (\\fB--control-ops-token\\fR) scopes its sessions to its
policy's verbs (the default policy: show). The audit trail (in the XDG
state home when
\\fB--audit-log\\fR is unset, prefix DSH) records the control commands with
their roles, the auth failures, the reloads and the shutdowns. With
\\fB--audit-forward\\fR every line \\(em the per\\-writer hash chain
included \\(em is mirrored onward: \\fBsyslog\\fR (the local socket
auto\\-scan), \\fBsyslog:/path\\fR (an explicit socket),
\\fBudp://host[:514]\\fR (RFC5426, best\\-effort) or
\\fBtcp://host[:514]\\fR (RFC6587 framing) \\(em the off\\-box copy
(F10): a scheduled search at the collector can chain\\-verify the
extracted prefix/chain fields and alert on a break. The remote envelope
rides \\fB--audit-forward-format\\fR (\\fBrfc5424\\fR, the default, or
\\fBcef\\fR); the local forms keep the verbatim send. A send failure
notes once and the next event re\\-arms. \\fB--audit-log none\\fR turns
the local file off: with a forward spelled that is the remote\\-only
mode (the collector is the sole holder, the chain reseeds at GENESIS
per run), without one the audit is disabled (the state
\\fB--no-audit-log\\fR spells)."""
    files = """.SH FILES
.TP
.I /tmp/dashboard-<port>.socket
the control socket used when \\fB--control-port\\fR is unset.
.TP
.I ~/.local/state/dashboard/audit.log
the audit trail when \\fB--audit-log\\fR is unset."""
    environment = """.SH ENVIRONMENT
.TP
.B CTL
control target for the daemon's clients when the flag is unset (flag
\\fB--control-port\\fR wins).
.TP
.B PORT ", " BIND ", " PROM_URL ", " AUTH_TOKEN ", " ...
the flags' environment twins (bare names; the Prometheus upstream's
twin is \\fBPROM_URL\\fR); the flag wins over the env, the env over the
config script."""
    exit_status = """.SH EXIT STATUS
.TP
.B 0
success (\\fB--dry-run\\fR: valid configuration).
.TP
.B 1
invalid configuration or a failed bind (reason on stderr).
.TP
.B 2
command-line misuse."""
    return page(
        'Static single-page home PV monitoring dashboard with a Prometheus proxy',
        'dashboard', 1, DATE, VERSION, MANUAL,
        '.B dashboard\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, security, environment, files, exit_status),
        kind='daemon',
        see_also='.BR dashboard-ctl (1),\n.BR dashboard-cli (1),\n.BR modbus-scraper (1),\n.BR modbus-cache (1),\n.BR modbus-fake-inverter (1)\n.PP\ndashboard/README.md in the suite checkout \\(em the full documentation.')


def ctl_page(parser):
    description = """\
Sends one command (or a batch from stdin) to the dashboard's JSON-lines
control server over TCP or a unix socket, prints the replies, exits. The
one-shot sibling of \\fBdashboard-cli\\fR(1): no session, no completion
\\(em the scriptable surface (the exit codes, one reply per command). With
a control token configured the wire is HMAC-signed: the client signs every
command and verifies every reply (the full sha256 of the frame, keyed by
the token)."""
    examples = """.SH EXAMPLES
.RS
.IP \\(bu 2
.B dashboard-ctl show version
.IP \\(bu 2
.B dashboard-ctl request reload-config
.IP \\(bu 2
.B printf 'inspect\\enshow version\\en' | dashboard-ctl
.RE"""
    environment = """.SH ENVIRONMENT
.TP
.B CTL ", " CONTROL_TOKEN
the control target and the TCP token when the flags are unset."""
    exit_status = """.SH EXIT STATUS
.TP
.B 0
every command answered \\fBok\\fR.
.TP
.B 1
connection or control error.
.TP
.B 2
command-line misuse."""
    return page(
        "send commands to the dashboard control server (one-shot / batch)",
        'dashboard-ctl', 1, DATE, VERSION, MANUAL,
        '.B dashboard-ctl\n.RI [ options ] " [command ...]"',
        description,
        options_section(parser),
        extra_sections=(examples, environment, exit_status),
        kind='ctl',
        see_also='.BR dashboard-cli (1),\n.BR dashboard (1)')


def cli_page(parser):
    description = """\
A session front-end on top of the dashboard's JSON-lines control socket:
prompt with the connected port, TAB completion and \\fB?\\fR in every
position (with the short descriptions from the shared command registry),
\\fBset\\fR commands print only the confirmation, \\fBshow <setting>\\fR
prints the bare value, \\fBinspect\\fR dumps the state, and
\\fBshutdown\\fR asks before it stops the server. When the connection dies
mid-session the console
retries (\\fB--reconnect\\fR attempts, \\fB--reconnect-wait\\fR seconds
apart). With a control token configured the wire is HMAC-signed: the
console signs every command and verifies every reply."""
    env = """.SH ENVIRONMENT
.TP
.B CTL
the control target when \\fB--control-port\\fR is unset.
.TP
.B CONTROL_TOKEN ", " CLI_KEEPALIVE
the TCP token and the idle-ping interval in seconds (0 = off)."""
    exit_status = """.SH EXIT STATUS
.TP
.B 0
the session ended cleanly.
.TP
.B 1
connection or control error.
.TP
.B 2
command-line misuse."""
    return page(
        "console-style session on the dashboard control server",
        'dashboard-cli', 1, DATE, VERSION, MANUAL,
        '.B dashboard-cli\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(env, exit_status),
        kind='cli',
        see_also='.BR dashboard-ctl (1),\n.BR dashboard (1)')
