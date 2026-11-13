#!/usr/bin/env python3
"""The scraper's man pages, generated (common/render/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff. scripts/generators/man.py writes the shipped man/*.1 from these;
`modbus-scraper --man` (and the ctl/cli's --man) prints the same page."""
from common.render.manpage import EXIT_STATUS_CLI, EXIT_STATUS_DAEMON, options_section, page

DATE = '2026-11-05'
VERSION = 'pv-suite 0.4.3'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The modbus-scraper(1) page: the OPTIONS from the parser, the prose
    from the README's poll/sanity/control story."""
    description = """\
Prometheus exporter for PV inverters (Modbus TCP, stdlib
only). Polls the inverter over Modbus TCP and serves the huawei_* metrics
the dashboard expects at /metrics in the Prometheus text format: the PV
generation, the grid exchange (import/export split), the home consumption
implied by the balance, the battery and the health gauges
(scraper_up, the error counter, the last poll age).
.PP
Every poll is sanity-checked: a negative PV reading, an array larger than
\\fB--max-kwp\\fR, a grid line beyond \\fB--max-grid-kw\\fR or a negative
home balance marks the exposition \\fB503\\fR (the sensors are suspect, not
the poller) and names the register in the log. A modbus-cache in front of
the device is detected automatically (its synthesized diagnostics block)
and adds the device-up / cache-age / cache-uptime gauges.
.PP
Modbus auth (\\fB--modbus-auth\\fR): with \\fBsuite\\fR the session proves the
shared key (\\fB--modbus-auth-key\\fR, min 16 characters) with a crypt handshake
right after every connect \\(em 52 bytes: magic, fresh nonce,
HMAC\\-SHA256 proof; the peer answers \\fBOK\\fR and plain Modbus follows,
or \\fBERR\\fR and the connection fails (the poller keeps retrying).
Empty auth = no auth at all.
.PP
The exposition endpoint is the tool's serving surface: the connection caps
(\\fB--metrics-max-clients\\fR total, \\fB--metrics-max-conn-per-ip\\fR per peer,
extras get an immediate 503), the idle keep-alive kick
(\\fB--metrics-client-timeout\\fR)
and the bearer token (\\fB--auth-token\\fR, the value a token or a
\\fBfile:<path>\\fR reference). A
non-loopback listen without a token refuses to start (F13 in
docs/SECURITY.md).
.PP
The JSON-lines control server (\\fB--control-port\\fR, talked to with
\\fBmodbus-scraper-cli\\fR(1)) inspects
and steers the running exporter: the live settings, an immediate poll, the
config reload, the Modbus session restart, the graceful shutdown. With a
control token configured the wire is HMAC-signed: every command and reply
carries the full sha256 of its payload, keyed by the token
(common/wire/wiresec.py) \\(em a token-holding client verifies both directions,
and over TCP the signed commands are mandatory. A second, read-only token
(\\fB--control-ops-token\\fR) authenticates into its policy's verbs
only (the default policy: show) \(em the ops shift against the admin
key, both roles audited."""
    signals = """.SH SIGNALS
.TP
.B SIGHUP
re-read the config file (and the auth token file) and apply what is live
(the same path as the control server's request reload-config); a broken
config keeps the previous settings.
.TP
.BR SIGTERM ", " SIGINT
graceful shutdown."""
    control = """.SH CONTROL
The control server speaks JSON lines ({"cmd": "..."} ->
{"status": "ok|fail|note|bye", "text": "..."}; TCP requires the token when
configured and refuses to start without one). Commands:
\\fBset\\fR/\\fBclear\\fR/\\fBshow\\fR/\\fBhelp\\fR (the settings: modbus
interval, modbus timeout, the modbus read delay, the modbus merge gap (the
poll plan rebuilds), the modbus caps sanity pair max-pv/max-grid, the
metrics limits caps, log-access, log-level, control socket-group (re-modes
the live unix socket
0600/0660) \\(em and the startup-only secrets: control token, the ops
token, metrics auth token \\(em the wire refuses set/clear, the value
never rendering \\(em \\fBshow <secret>\\fR refuses), \\fBshow uplink\\fR
(the inverter link: session counters \\(em connects, exchanges, bytes,
errors \\(em plus one row per poll block: status, latency, failures;
the cache's gold report over the scraper's fetch; \\fBshow
uplink-sources\\fR spells the register map instead \\(em one row per
polled register: fc, register, the range that fetches it, source),
\\fBshow connections\\fR
(the live HTTP clients), \\fBshow version\\fR, \\fBshow knobs\\fR
(the dictionary of the registry), \\fBrequest poll now\\fR,
\\fBinspect\\fR, \\fBrequest reload-config\\fR (the SIGHUP path),
\\fBrequest reload\\fR (the whole-daemon restart that keeps the sets: the
live overrides save to a state file beside the config, the process
re-execs, the fresh daemon re-applies them once), with a dump path
configured (\\fB--dump-path\\fR): \\fBrequest dump\\fR / \\fBrequest
restore\\fR (the overrides as one 0600 integrity-hashed JSON;
\\fB--dump-key\\fR seals it \\(em the state rides encrypted, a restore
refuses a wrong or missing key; \\fB--restore-on-start\\fR loads it at
start, \\fB--dump-interval\\fR rewrites it on a timer),
\\fBrequest restart\\fR, \\fBshutdown\\fR,
\\fBquit\\fR. See
.BR modbus-scraper-cli (1)."""
    security = """.SH SECURITY
The scraper reads an open Modbus device (no auth, no TLS — the inverter's
network isolation is the boundary) and serves /metrics: bind loopback,
set the bearer token when it must serve beyond loopback (a
non-loopback token-less start is refused, F13), and keep the connection
caps on. The control surface is loopback-only (TCP) or a 0600 unix socket;
a TCP control port without a token refuses to start (F5); with a token the
wire is signed and the commands/replies verify end to end; a second,
read-only ops token (\\fB--control-ops-token\\fR) scopes its sessions to
its policy's verbs (the default policy: show). The audit trail (in the
XDG state home when
\\fB--audit-log\\fR is unset, prefix SCR) records the control commands
with their roles, the auth failures, the reloads and the shutdowns. With
\\fB--audit-forward\\fR every line \\(em the per\\-writer hash chain
included \\(em is mirrored onward: \\fBsyslog\\fR (the local socket
auto\\-scan), \\fBsyslog:/path\\fR (an explicit socket),
\\fBudp://host[:514]\\fR (RFC5426, best\\-effort) or
\\fBtcp://host[:514]\\fR (RFC6587 framing) \\(em the off\\-box copy
(F10): a scheduled search at the collector can chain\\-verify the
extracted prefix/chain fields and alert on a break. The remote envelope
rides \\fB--audit-forward-format\\fR (\\fBrfc5424\\fR, the default, or
\\fBcef\\fR); the local forms keep the verbatim send. Every line names
its writer daemon in \\fBinstance=<id>\\fR \\(em the control port when
\\fB--audit-instance\\fR is unset (unique per host by construction), the
override when spelled (1\\-64 characters, letters, digits, . _ : @ \\-);
make an override unique among everything that shares one collector: the
chain groups by it. A send failure
notes once and the next event re\\-arms. \\fB--audit-log none\\fR turns
the local file off: with a forward spelled that is the remote\\-only
mode (the collector is the sole holder, the chain reseeds at GENESIS
per run), without one the audit is disabled (the state
\\fB--no-audit-log\\fR spells)."""
    files = """.SH FILES
.TP
.I /tmp/modbus-scraper-<listen-port>.socket
the control socket used when \\fB--control-port\\fR is unset.
.TP
.I ~/.local/state/modbus-scraper/audit.log
the audit trail when \\fB--audit-log\\fR is unset."""
    environment = """.SH ENVIRONMENT
.TP
.B CTL
control target for the daemon's clients when the flag is unset (flag
\\fB--control-port\\fR wins).
.TP
.B UPSTREAM ", " LISTEN ", " INTERVAL ", " AUTH_TOKEN ", " ...
every flag has an environment twin of the same bare name (no tool
prefix); the flag wins over the env, the env over the config script."""
    exit_status = EXIT_STATUS_DAEMON
    return page(
        'Prometheus exporter for PV inverters (Modbus TCP, stdlib only)',
        'modbus-scraper', 1, DATE, VERSION, MANUAL,
        '.B modbus-scraper\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, security, environment, files, exit_status),
        kind='daemon',
        see_also='.BR modbus-scraper-cli (1),\n.BR modbus-cache (1),\n.BR modbus-fake-inverter (1)\n.PP\nscraper/README.md in the suite checkout \\(em the full documentation.')



def cli_page(parser):
    description = """\
One client, three modes by the invocation shape: command words one-shot
(\\fBmodbus-scraper-cli\\fR show config\\fR \\(em the raw verdict head prints,
exit 0 ok, 1 connection error, 2 misuse), piped stdin batch (the script lines
run in order, the same raw faces), a bare terminal the interactive console.
.PP
A session front-end on top of modbus-scraper's JSON-lines control socket:
prompt with the connected port, TAB completion and \\fB?\\fR in every
position (with the short descriptions from the shared command registry),
\\fBset\\fR commands print only the confirmation, \\fBshow <setting>\\fR
prints the bare value, \\fBinspect\\fR dumps the state, and
\\fBshutdown\\fR asks before it stops the scraper. When the connection dies
mid-session the console
retries (\\fB--reconnect\\fR attempts, \\fB--reconnect-wait\\fR seconds
apart). With a control token configured the wire is HMAC-signed: the
console signs every command and verifies every reply.
.PP
Every reply prints through the console's pager: a text taller than the
screen pauses at a page \\(em space prints the next page, return one more
line, \\fBq\\fR stops the rest (the command already ran; only the
rendering stops). \\fB--page-size\\fR/\\fBCLI_PAGE_SIZE\\fR set the page
size (\\fB0\\fR = off, empty = the terminal height); a session-local
\\fBpage\\fR command retunes it live (never sent to the daemon); a
terminal smaller than 20 rows or 64 columns refuses to start."""
    env = """.SH ENVIRONMENT
.TP
.B CTL
the control target when \\fB--control-port\\fR is unset.
.TP
.B CONTROL_TOKEN ", " CLI_KEEPALIVE
the TCP token and the idle-ping interval in seconds (0 = off).
.TP
.B CLI_PAGE_SIZE
the console pager's page size, lines; \\fB0\\fR = off, empty = the
terminal height."""
    exit_status = EXIT_STATUS_CLI
    return page(
        "console-style session on the modbus-scraper control server",
        'modbus-scraper-cli', 1, DATE, VERSION, MANUAL,
        '.B modbus-scraper-cli\n.RI [ options ]\n.IB command " [args ...]"',
        description,
        options_section(parser),
        extra_sections=(env, exit_status),
        kind='cli',
        see_also='.BR modbus-scraper (1)')
