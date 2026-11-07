#!/usr/bin/env python3
"""The scraper's man pages, generated (common/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff. scripts/gen_man.py writes the shipped man/*.1 from these;
`modbus-scraper --man` (and the ctl/cli's --man) prints the same page."""
from common.manpage import esc, options_section, page

DATE = '2026-11-05'
VERSION = 'pv-suite 0.3.0'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The modbus-scraper(1) page: the OPTIONS from the parser, the prose
    from the README's poll/sanity/control story."""
    description = """\
Prometheus exporter for Huawei SUN2000 inverters (Modbus TCP, stdlib
only). Polls the inverter over Modbus TCP and serves the huawei_* metrics
the dashboard expects at /metrics in the Prometheus text format: the PV
generation, the grid exchange (import/export split), the home consumption
implied by the balance, the battery (optional) and the health gauges
(scraper_up, the error counter, the last poll age).
.PP
Every poll is sanity-checked: a negative PV reading, an array larger than
\\fB--max-kwp\\fR, a grid line beyond \\fB--max-grid-kw\\fR or a negative
home balance marks the exposition \\fB503\\fR (the sensors are suspect, not
the poller) and names the register in the log. A modbus-cache in front of
the device is detected automatically (its synthesized diagnostics block)
and adds the device-up / cache-age / cache-uptime gauges.
.PP
Modbus auth (\\fB--auth\\fR): with \\fBsuite\\fR the session proves the
shared key (\\fB--auth-key\\fR, min 16 characters) with a crypt handshake
right after every connect \\(em 52 bytes: magic, fresh nonce,
HMAC\\-SHA256 proof; the peer answers \\fBOK\\fR and plain Modbus follows,
or \\fBERR\\fR and the connection fails (the poller keeps retrying).
Empty auth (the default) = no auth at all.
.PP
The exposition endpoint is the tool's serving surface: the connection caps
(\\fB--max-clients\\fR total, \\fB--max-conn-per-ip\\fR per peer, extras
get an immediate 503), the idle keep-alive kick (\\fB--client-timeout\\fR)
and the bearer token (\\fB--auth-token\\fR/\\fB--auth-token-file\\fR). A
non-loopback listen without a token refuses to start (F13 in
docs/AUDIT.md).
.PP
The JSON-lines control server (\\fB--control-port\\fR, talked to with
\\fBmodbus-scraper-ctl\\fR(1) and \\fBmodbus-scraper-cli\\fR(1)) inspects
and steers the running exporter: the live settings, an immediate poll, the
config reload, the Modbus session restart, the graceful shutdown. With a
control token configured the wire is HMAC-signed: every command and reply
carries the full sha256 of its payload, keyed by the token
(common/wiresec.py) \\(em a token-holding client verifies both directions,
and over TCP the signed commands are mandatory. A second, read-only token
(\\fB--control-ops-token\\fR) authenticates into the show/clear verbs only
\\(em the ops shift against the admin key, both roles audited."""
    signals = """.SH SIGNALS
.TP
.B SIGHUP
re-read the config file (and the auth token file) and apply what is live
(the same path as the control server's request reload); a broken config
keeps the previous settings.
.TP
.BR SIGTERM ", " SIGINT
graceful shutdown."""
    control = """.SH CONTROL
The control server speaks JSON lines ({"cmd": "..."} ->
{"status": "ok|err|bye", "text": "..."}; TCP requires the token when
configured and refuses to start without one). Commands:
\\fBset\\fR/\\fBunset\\fR/\\fBshow\\fR/\\fBhelp\\fR (the settings: interval,
timeout, max-clients, client-timeout, max-conn-per-ip, log-access,
log-level \\(em and the token lives: control token, the ops token,
auth token, each rotating live, the value never rendering \\(em
\\fBshow <secret>\\fR refuses), \\fBshow status\\fR, \\fBshow connections\\fR
(the live HTTP clients), \\fBshow version\\fR, \\fBshow knobs\\fR
(the dictionary of the registry), \\fBpoll now\\fR,
\\fBinspect\\fR, \\fBrequest reload\\fR (the SIGHUP path),
\\fBreload\\fR (the whole-daemon restart that keeps the sets: the live
overrides save to a state file beside the config, the process re-execs,
the fresh daemon re-applies them once), with a dump path configured
(\\fB--dump-path\\fR): \\fBrequest dump\\fR / \\fBrequest restore\\fR
(the overrides as one 0600 integrity-hashed JSON; \\fB--dump-key\\fR
seals it \\(em the state rides encrypted, a restore refuses a wrong or
missing key; \\fB--restore-on-start\\fR
loads it at start), \\fBrestart\\fR, \\fBshutdown\\fR,
\\fBquit\\fR. See
.BR modbus-scraper-ctl (1)
and
.BR modbus-scraper-cli (1)."""
    security = """.SH SECURITY
The scraper reads an open Modbus device (no auth, no TLS — the inverter's
network isolation is the boundary) and serves /metrics: bind loopback by
default, set the bearer token when it must serve beyond loopback (a
non-loopback token-less start is refused, F13), and keep the connection
caps on. The control surface is loopback-only (TCP) or a 0600 unix socket;
a TCP control port without a token refuses to start (F5); with a token the
wire is signed and the commands/replies verify end to end; a second,
read-only ops token (\\fB--control-ops-token\\fR) scopes its sessions to
the show/clear verbs. The audit trail (default in the XDG state home,
prefix SCR) records the control commands with their roles, the auth
failures, the reloads and the shutdowns."""
    files = """.SH FILES
.TP
.I /tmp/modbus-scraper-<listen-port>.socket
the default control socket.
.TP
.I ~/.local/state/modbus-scraper/audit.log
the default audit trail."""
    return page(
        'Prometheus exporter for Huawei SUN2000 inverters (Modbus TCP, stdlib only)',
        'modbus-scraper', 1, DATE, VERSION, MANUAL,
        '.B modbus-scraper\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, security, files),
        see_also='.BR modbus-scraper-ctl (1),\n.BR modbus-scraper-cli (1),\n.BR modbus-cache (1),\n.BR modbus-fake-inverter (1)\n.PP\nscraper/README.md in the suite checkout \\(em the full documentation.')


def ctl_page(parser):
    description = """\
Sends one command (or a batch from stdin) to modbus-scraper's JSON-lines
control server over TCP or a unix socket, prints the replies, exits. The
one-shot sibling of \\fBmodbus-scraper-cli\\fR(1): no session, no
completion — the scriptable surface (the exit codes, one reply per
command). With a control token configured the wire is HMAC-signed: the
client signs every command and verifies every reply (the full sha256 of
the frame, keyed by the token)."""
    return page(
        "send commands to the modbus-scraper control server (one-shot / batch)",
        'modbus-scraper-ctl', 1, DATE, VERSION, MANUAL,
        '.B modbus-scraper-ctl\n.RI [ options ] " [command ...]"',
        description,
        options_section(parser),
        extra_sections=(),
        see_also='.BR modbus-scraper-cli (1),\n.BR modbus-scraper (1)')


def cli_page(parser):
    description = """\
A session front-end on top of modbus-scraper's JSON-lines control socket:
prompt with the connected port, TAB completion and \\fB?\\fR in every
position (with the short descriptions from the shared command registry),
\\fBset\\fR commands print only the confirmation, \\fBshow <setting>\\fR
prints the bare value, \\fBshow status\\fR the key=value report, and
\\fBshutdown\\fR asks before it stops the scraper. When the connection dies
mid-session the console
retries (\\fB--reconnect\\fR attempts, \\fB--reconnect-wait\\fR seconds
apart). With a control token configured the wire is HMAC-signed: the
console signs every command and verifies every reply."""
    env = """.SH ENVIRONMENT
.TP
.B CTL
the default control target for the clients.
.TP
.B CONTROL_TOKEN ", " CLI_KEEPALIVE
the TCP token and the idle-ping interval in seconds (0 = off)."""
    return page(
        "console-style session on the modbus-scraper control server",
        'modbus-scraper-cli', 1, DATE, VERSION, MANUAL,
        '.B modbus-scraper-cli\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(env,),
        see_also='.BR modbus-scraper-ctl (1),\n.BR modbus-scraper (1)')
