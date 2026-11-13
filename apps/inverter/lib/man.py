#!/usr/bin/env python3
"""The fake inverter's man pages, generated (common/render/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff (ported from the original hand-written pages). dev/generators/man.py
writes the shipped man/*.1 from these; `modbus-fake-inverter --man` (and the
ctl/cli's --man) prints the same page."""
from common.render.manpage import EXIT_STATUS_CLI, EXIT_STATUS_DAEMON, options_section, page

DATE = '2026-11-05'
VERSION = 'pv-suite 0.5.1'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The modbus-fake-inverter(1) page: the OPTIONS from the parser, the
    prose from the original page (the day simulation, the machines, the
    control grammar, the trusted-LAN security posture)."""
    description = """\
A stdlib-only Modbus TCP server that plays an inverter \\(em with a
battery, a smart meter, the modbus-cache diagnostics block and the
pv-suite's register-map profiles \\(em so the scraper, the cache and the
whole stack can be exercised without hardware. The shipped default
profile is the sun2000 (Huawei SUN2000) map; Deye hybrids are included.
This is a test instrument:
synthetic data only, no state worth protecting beyond its LAN segment.
The startup surface is the family's: the flags, the bare env twins and
the set-grammar config file (\\fB--config\\fR, every line a
`set <name> <value>` \\(em the bundled sample is
\\fBinverter/examples/modbus-fake-inverter.conf\\fR) \\(em flag > env > config >
default.
.PP
It simulates a sunny day: a double-shouldered PV curve over
two MPPT strings (east/west), a home load with morning/evening peaks, a
battery state machine (95 % charge efficiency, self-discharge, an 80 %
discharge cap, temperature derating), per-phase grid voltages and load
shares (mean-reverting wanderers), a grid-frequency machine, and a grid
outage machine (random blackouts). All machines integrate with a simulated
clock \\(em UTC unless told otherwise, freezable (\\fB--time\\fR) and scalable
(\\fB--time-scale\\fR for time-lapse). \\fB--static\\fR replaces the day with
constant demo values. The profile's per-entry \\fBfc\\fR picks each
entry's address space (FC3 holding / FC4 input registers, FC1 coils /
FC2 discrete inputs for \\fBbit\\fR entries); writes land in overlays
the scrapers read (FC06/FC16 the registers, FC05/FC15 the coils, plus
\\fBset coil\\fR/\\fBset discrete\\fR on the control socket);
\\fB--chaos\\fR answers a fraction of requests hostile.
.PP
Modbus auth (\\fB--modbus-auth\\fR): with \\fBsuite\\fR the fake's clients prove
a shared key (\\fB--modbus-auth-key\\fR, min 16 characters) with a crypt
handshake right after every connect \\(em 52 bytes: magic, fresh nonce,
HMAC\\-SHA256 proof; the fake answers \\fBOK\\fR (plain Modbus follows) or
\\fBERR\\fR (the client is dropped before it ever sees a register).
Empty auth = no auth at all \\(em the trusted-LAN posture
stands. The writes are gated like the cache's (\\fB--allow-write\\fR):
off = every Modbus write (FC05/06/15/16) is refused with
exception 01 and audited WRITE\\-REFUSED; on = a write lands in the
overlay, audited WRITE."""
    signals = """.SH SIGNALS
.TP
.B SIGHUP
re-apply the environment layer (all-or-nothing).
.TP
.B SIGUSR1
reset the scenario: runtime pins, the cloud machine, the write overlay
and the pinned coils/discrete inputs
are dropped.
.TP
.BR SIGTERM ", " SIGINT
graceful shutdown with a session summary."""
    control = """.SH CONTROL
The control server speaks JSON lines
(\\fB{"cmd": "..."}\\fR -> \\fB{"status": "ok|fail|note|bye", "text": "..."}\\fR;
TCP requires the token when configured). Commands: \\fBset\\fR/\\fBclear\\fR/
\\fBshow\\fR/\\fBhelp\\fR (the settings: pv, load, batt, grid, grid-voltage,
grid-frequency, grid-outage, soc, mppt, cloud, timezone, time, time-scale,
scenario, chaos, seed, battery-state, strict, static, max-kwp,
battery-kwh, max-clients, client-timeout, max-conn-per-ip,
metrics-server, metrics-acl, register, coil, discrete,
log-level, modbus auth, modbus profile (the suite
scheme; the key
\\(em modbus auth key \\(em is a startup-only secret: \\fBshow\\fR refuses
it, the wire refuses set/clear) \\(em and the token lives: control token,
the ops token, metrics token, each startup-only, the value never
rendering \\(em \\fBshow <secret>\\fR refuses),
\\fBshow connections\\fR (the live Modbus clients: peer,
age, requests), \\fBshow registers\\fR,
\\fBshow version\\fR, \\fBshow knobs\\fR (the dictionary of the registry),
\\fBinspect\\fR, \\fBreset\\fR, \\fBrequest reload\\fR (the whole-daemon restart
that keeps the pins: the overrides save to a state file beside the config
script, the process re-execs, the
fresh fake re-applies them once), \\fBrequest reload-config\\fR (re-read
the config file without the restart: the config's values re-apply over
the running machines \\(em the demo knobs, not the pins), with a dump
path configured
(\\fB--dump-path\\fR): \\fBrequest dump\\fR / \\fBrequest restore\\fR (the
overrides as one 0600 integrity-hashed JSON; \\fB--dump-key\\fR seals it
\\(em the state rides encrypted, a restore refuses a wrong or missing key;
\\fB--restore-on-start\\fR
loads it at start, \\fB--dump-interval\\fR rewrites it on a timer),
\\fBshutdown\\fR,
\\fBquit\\fR. A second, read-only token (\\fB--control-ops-token\\fR)
authenticates into the show verbs only \\(em the ops shift against the
admin key, both roles audited. The control listener rides the family's
live rebind: \\fBset control-port\\fR (a unix path, a TCP port on
127.0.0.1, or off) swaps the socket without dropping the connected
sessions \\(em tokenless TCP included, the F11 test-tool posture \\(em and
the family's control knobs all set live: \\fBcontrol ops verbs\\fR (the
read-only role's policy), \\fBcontrol trust-uids\\fR (the peer-cred
list), \\fBcontrol socket-group\\fR (0660 instead of 0600, the live
socket re-modes). See
.BR modbus-fake-cli (1)."""
    security = """.SH SECURITY
The fake is a development/test instrument, not a security-first design
(the audit's F11): the Modbus surface speaks by default to any peer that
can reach the port \\(em no TLS; the opt-in \\fB--connect-acl\\fR IP gate
(the cache's connect-acl, mirrored: \\fBany\\fR/\\fBnone\\fR/the
IP/CIDR list, live-settable) filters who may connect at all, and the
optional \\fB--auth suite\\fR
shared-key handshake authenticates clients when a demo wants it \\(em and
the metrics endpoint
speaks the family's F13 shape: it refuses to start beyond loopback
without a token (the loopback bind serves tokenless), and the
\\fB--metrics-acl\\fR IP gate narrows who reaches the endpoint at all
(the metrics-acl: \\fBany\\fR/\\fBnone\\fR/the IP/prefix list or
\\fBfile:<path>\\fR, checked at accept \\(em a client off the ACL is
closed without a reply). Run it on a trusted,
LAN-isolated network, next to the tools it is meant to serve.
\\fB--max-clients\\fR/\\fB--client-timeout\\fR cap runaway connections and
the read-count gate keeps a malformed frame from assembling an oversized
reply. The control surface can still carry the family's read-only ops
token (\\fB--control-ops-token\\fR) when the ops shift only ever watches;
the unix control socket is 0600, or 0660 with
\\fB--control-socket-group\\fR (a local group shares it). The audit
trail (prefix INV, the XDG state home when \\fB--audit-log\\fR is
unset) forwards like the family's: \\fB--audit-forward\\fR spells the
target \\(em \\fBsyslog\\fR (the local socket auto\\-scan),
\\fBsyslog:/path\\fR, \\fBudp://host[:514]\\fR or
\\fBtcp://host[:514]\\fR (the off\\-box copy; the remote envelope rides
\\fB--audit-forward-format\\fR = \\fBrfc5424\\fR|\\fBcef\\fR) \\(em a
send failure notes once and the next event re\\-arms. Every line names
its writer daemon in \\fBinstance=<id>\\fR \\(em the control port when
\\fB--audit-instance\\fR is unset (unique per host by construction), the
override when spelled (1\\-64 characters, letters, digits, . _ : @ \\-);
make an override unique among everything that shares one collector: the
chain groups by it;
\\fB--audit-log none\\fR turns the local file off (with a forward
spelled: the remote\\-only mode; without one: the audit disabled)."""
    environment = """.SH ENVIRONMENT
.TP
.B CHAOS ", " MAX_KWP ", " PROFILE ,
.B STRICT ", " TIME ", " TIME_SCALE ", " LOG_LEVEL
the demo layer: the start reads it too (flag > env > the config script)
and SIGHUP re-applies it (keep-last-good).
.TP
.B CTL
the control target when \\fB--control-port\\fR is unset.
.TP
.B LISTEN ", " MAX_CLIENTS ", " CONTROL_TOKEN ", " ...
every flag has an environment twin of the same bare name (no tool
prefix); the flag wins over the env, the env over the config script.
.TP
.B CONTROL_TOKEN ", " CLI_KEEPALIVE
the clients' TCP token and idle-ping interval.
.TP
.B CONFIG
the config script when \\fB--config\\fR is unset."""
    files = """.SH FILES
.TP
.I modbus-fake-inverter.conf
the config script (the set grammar) \\(em next to the binary when
\\fB--config\\fR is unset (the image ships it at
/pv\\-suite/inverter/modbus\\-fake\\-inverter.conf).
.TP
.I /tmp/fake-inverter-<port>.socket
the control socket used when \\fB--control-port\\fR is unset.
.TP
.I ~/.local/state/fake-inverter/audit.log
the audit trail when \\fB--audit-log\\fR is unset."""
    exit_status = EXIT_STATUS_DAEMON
    return page(
        'simulated PV inverter for testing the pv-suite stack',
        'modbus-fake-inverter', 1, DATE, VERSION, MANUAL,
        '.B modbus-fake-inverter\n.RI [ options ]\n.br\n.B modbus-fake-inverter \\-\\-static\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, security, environment, files, exit_status),
        kind='daemon',
        see_also='.BR modbus-fake-cli (1),\n.BR modbus-cache (1),\n.BR modbus-scraper (1)\n.PP\n\\fBinverter/README.md\\fR in the suite checkout \\(em the full documentation,\nincluding the state machines.')



def cli_page(parser):
    description = """\
One client, three modes by the invocation shape: command words one-shot
(\\fBmodbus-fake-cli\\fR show config\\fR \\(em the raw verdict head prints,
exit 0 ok, 1 connection error, 2 misuse), piped stdin batch (the script lines
run in order, the same raw faces), a bare terminal the interactive console.
.PP
An interactive console on the \\fBmodbus-fake-inverter\\fR JSON-lines
control server; the prompt shows the
connected port (\\fBfake-inverter:5502 >\\fR). TAB completes commands,
settings and their values (the listings group the settings under the
registry's own groups \\(em ungrouped rows render bare, no header \\(em, with
[values] beside, descriptions aligned); \\fB?\\fR prints
the same in any position; \\fBhelp <setting>\\fR explains one; \\fBshutdown\\fR
asks \\fBProceed with shutdown? [confirm]\\fR first.
.PP
Every reply prints through the console's pager: a text taller than the
screen pauses at a page \\(em space prints the next page, return one more
line, \\fBq\\fR stops the rest (the command already ran; only the
rendering stops). \\fB--page-size\\fR/\\fBCLI_PAGE_SIZE\\fR set the page
size (\\fB0\\fR = off, empty = the terminal height); a session-local
\\fBpage\\fR command retunes it live (never sent to the daemon); a
terminal smaller than 20 rows or 64 columns refuses to start.
.PP
While idle the session sends wire pings; when the connection
dies, the console retries (\\fB--reconnect\\fR attempts,
\\fB--reconnect-wait\\fR seconds apart) and resumes on the
first success. The session is audited with the \\fBCLI\\fR prefix; the wire
commands are audited once, by the server."""
    environment = """.SH ENVIRONMENT
.TP
.B CLI_KEEPALIVE
idle ping interval, seconds; \\fB0\\fR = off.
.TP
.B CLI_PAGE_SIZE
the console pager's page size, lines; \\fB0\\fR = off, empty = the
terminal height.
.TP
.B CTL ", " CONTROL_TOKEN
the control target and TCP token when the flags are unset."""
    exit_status = EXIT_STATUS_CLI
    return page(
        'console-style control session for the fake inverter',
        'modbus-fake-cli', 1, DATE, VERSION, MANUAL,
        '.B modbus-fake-cli\n.RI [ options ]\n.IB command " [args ...]"',
        description,
        options_section(parser),
        extra_sections=(environment, exit_status),
        kind='cli',
        see_also='.BR modbus-fake-inverter (1)')
