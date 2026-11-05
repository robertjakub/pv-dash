#!/usr/bin/env python3
"""The dashboard's man pages, generated (common/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff. scripts/gen_man.py writes the shipped man/*.1 from these;
`dashboard --man` (and the ctl/cli's --man) prints the same page."""
from common.manpage import page, options_section

DATE = '2026-11-05'
VERSION = 'pv-suite 0.3.0'
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
/config.js (the SOLAR_CONFIG object; \\fB--battery\\fR injects the battery
panels).
.PP
The HTTP surface is the tool's serving surface: the connection caps
(\\fB--max-clients\\fR total, \\fB--max-conn-per-ip\\fR per peer, extras
get an immediate 503), the idle keep-alive kick (\\fB--client-timeout\\fR).
The README documents the loopback/reverse-proxy paths \\(em the server
speaks plain HTTP with no authentication on page or proxy yet (the auth
story in docs/TODO.md): bind the loopback or put a proxy in front.
.PP
The JSON-lines control server (\\fB--control-port\\fR, talked to with
\\fBdashboard-ctl\\fR(1) and \\fBdashboard-cli\\fR(1)) inspects and steers
the running server: the live settings (the caps, the log surface, the
battery flag), the config reload, the graceful shutdown. With a control
token configured the wire is HMAC-signed: every command and reply carries
the full sha256 of its payload, keyed by the token (common/wiresec.py)
\\(em a token-holding client verifies both directions, and over TCP the
signed commands are mandatory. A second, read-only token
(\\fB--control-ops-token\\fR) authenticates into the show/clear verbs only
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
{"status": "ok|err|bye", "text": "..."}; TCP requires the token when
configured and refuses to start without one). Commands:
\\fBset\\fR/\\fBunset\\fR/\\fBshow\\fR/\\fBhelp\\fR (the settings: max-clients,
client-timeout, max-conn-per-ip, log-access, log-queries, battery,
log-level), \\fBshow status\\fR, \\fBshow connections\\fR (the live HTTP
clients), \\fBshow settings\\fR, \\fBshow version\\fR, \\fBshow knobs\\fR
(the dictionary of the registry), \\fBinspect\\fR,
\\fBrequest reload\\fR, \\fBshutdown\\fR, \\fBquit\\fR. See
.BR dashboard-ctl (1)
and
.BR dashboard-cli (1)."""
    security = """.SH SECURITY
The server speaks plain HTTP and has no authentication on the page or the
proxy yet (the auth story in docs/TODO.md): bind the loopback (the NixOS
module's default) or publish the port loopback-only and put an
authenticating reverse proxy in front for anything beyond localhost. The
control surface is loopback-only (TCP) or a 0600 unix socket; a TCP
control port without a token refuses to start (F5); with a token the wire
is signed and the commands/replies verify end to end; a second, read-only
ops token (\\fB--control-ops-token\\fR) scopes its sessions to the
show/clear verbs. The audit trail (default in the XDG state home, prefix
DSH) records the control commands with their roles, the auth failures, the
reloads and the shutdowns."""
    files = """.SH FILES
.TP
.I /tmp/dashboard-<port>.socket
the default control socket.
.TP
.I ~/.local/state/dashboard/audit.log
the default audit trail."""
    return page(
        'Static single-page home PV monitoring dashboard with a Prometheus proxy',
        'dashboard', 1, DATE, VERSION, MANUAL,
        '.B dashboard\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, security, files),
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
    return page(
        "send commands to the dashboard control server (one-shot / batch)",
        'dashboard-ctl', 1, DATE, VERSION, MANUAL,
        '.B dashboard-ctl\n.RI [ options ] " [command ...]"',
        description,
        options_section(parser),
        extra_sections=(),
        see_also='.BR dashboard-cli (1),\n.BR dashboard (1)')


def cli_page(parser):
    description = """\
A session front-end on top of the dashboard's JSON-lines control socket:
prompt with the connected port, TAB completion and \\fB?\\fR in every
position (with the short descriptions from the shared command registry),
\\fBset\\fR commands print only the confirmation, \\fBshow <setting>\\fR
prints the bare value, \\fBshow settings\\fR one setting per line,
\\fBshow status\\fR the key=value report, and \\fBshutdown\\fR asks before
it stops the server. When the connection dies mid-session the console
retries (\\fB--reconnect\\fR attempts, \\fB--reconnect-wait\\fR seconds
apart). With a control token configured the wire is HMAC-signed: the
console signs every command and verifies every reply."""
    env = """.SH ENVIRONMENT
.TP
.B DSH_CTL
the default control target for the clients.
.TP
.B DSH_CONTROL_TOKEN ", " DSH_CLI_KEEPALIVE
the TCP token and the idle-ping interval in seconds (0 = off)."""
    return page(
        "console-style session on the dashboard control server",
        'dashboard-cli', 1, DATE, VERSION, MANUAL,
        '.B dashboard-cli\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(env,),
        see_also='.BR dashboard-ctl (1),\n.BR dashboard (1)')
