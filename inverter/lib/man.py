#!/usr/bin/env python3
"""The fake inverter's man pages, generated (common/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff (ported from the original hand-written pages). scripts/gen_man.py
writes the shipped man/*.1 from these; `modbus-fake-inverter --man` (and the
ctl/cli's --man) prints the same page."""
from common.manpage import options_section, page

DATE = '2026-11-05'
VERSION = 'pv-suite 0.3.0'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The modbus-fake-inverter(1) page: the OPTIONS from the parser, the
    prose from the original page (the day simulation, the machines, the
    control grammar, the trusted-LAN security posture)."""
    description = """\
A stdlib-only Modbus TCP server that plays an inverter \\(em with a
battery, a smart meter, the modbus-cache diagnostics block and the
pv-suite's register-map profiles \\(em so the scraper, the cache and the
whole stack can be exercised without hardware. The default profile is the
Huawei SUN2000 map; Deye hybrids are included. This is a test instrument:
synthetic data only, no state worth protecting beyond its LAN segment.
.PP
By default it simulates a sunny day: a double-shouldered PV curve over
two MPPT strings (east/west), a home load with morning/evening peaks, a
battery state machine (95 % charge efficiency, self-discharge, an 80 %
discharge cap, temperature derating), per-phase grid voltages and load
shares (mean-reverting wanderers), a grid-frequency machine, and a grid
outage machine (random blackouts). All machines integrate with a simulated
clock \\(em UTC by default, freezable (\\fB--time\\fR) and scalable
(\\fB--time-scale\\fR for time-lapse). \\fB--static\\fR replaces the day with
constant demo values. Writes (FC06/FC16) land in an overlay the scrapers
read; \\fB--chaos\\fR answers a fraction of requests hostile."""
    signals = """.SH SIGNALS
.TP
.B SIGHUP
re-apply the \\fBFAKE_*\\fR environment layer (all-or-nothing).
.TP
.B SIGUSR1
reset the scenario: runtime pins, the cloud machine and the write overlay
are dropped.
.TP
.BR SIGTERM ", " SIGINT
graceful shutdown with a session summary."""
    control = """.SH CONTROL
The control server speaks JSON lines
(\\fB{"cmd": "..."}\\fR -> \\fB{"status": "ok|err|bye", "text": "..."}\\fR;
TCP requires the token when configured). Commands: \\fBset\\fR/\\fBunset\\fR/
\\fBshow\\fR/\\fBhelp\\fR (the settings: pv, load, batt, grid, grid-voltage,
grid-frequency, grid-outage, soc, mppt, cloud, timezone, time, time-scale,
scenario, chaos, seed, battery, battery-state, strict, static, max-kwp,
battery-kwh, max-clients, client-timeout, max-conn-per-ip, metrics-server,
register, profile, log-level),
\\fBshow status\\fR, \\fBshow connections\\fR (the live Modbus clients: peer,
age, requests), \\fBshow settings\\fR, \\fBshow registers\\fR,
\\fBshow version\\fR, \\fBinspect\\fR, \\fBreset\\fR, \\fBshutdown\\fR,
\\fBquit\\fR. See
.BR modbus-fake-ctl (1)
and
.BR modbus-fake-cli (1)."""
    security = """.SH SECURITY
The fake is a development/test instrument, not a security-first design
(the audit's F11): the Modbus surface speaks to any peer that can reach
the port \\(em no TLS, no auth, no ACL \\(em and the metrics endpoint
serves without a token unless one is configured. Run it on a trusted,
LAN-isolated network, next to the tools it is meant to serve.
\\fB--max-clients\\fR/\\fB--client-timeout\\fR cap runaway connections and
the read-count gate keeps a malformed frame from assembling an oversized
reply."""
    environment = """.SH ENVIRONMENT
.TP
.B FAKE_CHAOS ", " FAKE_MAX_KWP ", " FAKE_PROFILE ", " FAKE_BATTERY ,
.B FAKE_STRICT ", " FAKE_TIME ", " FAKE_TIME_SCALE ", " FAKE_LOG_LEVEL
the SIGHUP-reloadable layer.
.TP
.B FAKE_CTL
the default control target for the clients.
.TP
.B FAKE_CONTROL_TOKEN ", " FAKE_CLI_KEEPALIVE
the clients' TCP token and idle-ping interval."""
    files = """.SH FILES
.TP
.I /tmp/fake-inverter-<port>.socket
the default control socket.
.TP
.I ~/.local/state/fake-inverter/audit.log
the default audit trail."""
    return page(
        'simulated PV inverter for testing the pv-suite stack',
        'modbus-fake-inverter', 1, DATE, VERSION, MANUAL,
        '.B modbus-fake-inverter\n.RI [ options ]\n.br\n.B modbus-fake-inverter \\-\\-static\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, security, environment, files),
        see_also='.BR modbus-fake-ctl (1),\n.BR modbus-fake-cli (1),\n.BR modbus-cache (1),\n.BR modbus-scraper (1)\n.PP\n\\fBinverter/README.md\\fR in the suite checkout \\(em the full documentation,\nincluding the state machines.')


def ctl_page(parser):
    description = """\
Sends one control command (or a batch piped on stdin, one per line) to the
\\fBmodbus-fake-inverter\\fR JSON-lines control server and prints the
replies on stdout, one per line. Every invocation lands in the audit trail
(prefix \\fBCTL\\fR).
.PP
The command grammar is the fake's: \\fBset\\fR/\\fBunset\\fR/\\fBshow\\fR/
\\fBhelp\\fR (the 26-setting registry), \\fBshow status\\fR,
\\fBshow connections\\fR (the live Modbus clients: peer, age, requests),
\\fBshow settings\\fR, \\fBshow registers\\fR, \\fBshow version\\fR,
\\fBinspect\\fR, \\fBreset\\fR, \\fBshutdown\\fR, \\fBquit\\fR. See
.BR modbus-fake-inverter (1)
CONTROL."""
    examples = """.SH EXAMPLES
.RS
.IP \\(bu 2
.B modbus-fake-ctl set pv 2500
.IP \\(bu 2
.B modbus-fake-ctl show settings
.IP \\(bu 2
.B printf 'set pv 2500\\\\nset soc 30\\\\nshow status\\\\n' | modbus-fake-ctl
.RE"""
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
        'one-shot control client for the fake inverter',
        'modbus-fake-ctl', 1, DATE, VERSION, MANUAL,
        '.B modbus-fake-ctl\n.RI [ options ]\n.IB command " [args ...]"\n.br\n.B modbus-fake-ctl\n.RI [ options ]\n< commands',
        description,
        options_section(parser),
        extra_sections=(examples, exit_status),
        see_also='.BR modbus-fake-inverter (1),\n.BR modbus-fake-cli (1)')


def cli_page(parser):
    description = """\
An interactive console on the \\fBmodbus-fake-inverter\\fR JSON-lines
control server: on connect it probes the fake and greets you with the
profile, the uptime, the clock and the battery state; the prompt shows the
connected port (\\fBfake-inverter:5502 >\\fR). TAB completes commands,
settings and their values (the listings split into
[settings]/[values]/[system] with aligned descriptions); \\fB?\\fR prints
the same in any position; \\fBhelp <setting>\\fR explains one; \\fBshutdown\\fR
asks \\fBProceed with shutdown? [confirm]\\fR first.
.PP
While idle the session sends wire pings every 55 s; when the connection
dies, the console retries (default 3 times, 10 s apart) and resumes on the
first success. The session is audited with the \\fBCLI\\fR prefix; the wire
commands are audited once, by the server."""
    environment = """.SH ENVIRONMENT
.TP
.B FAKE_CLI_KEEPALIVE
idle ping interval, seconds (default \\fB55\\fR); \\fB0\\fR = off.
.TP
.B FAKE_CTL ", " FAKE_CONTROL_TOKEN
the default control target and TCP token."""
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
        'console-style control session for the fake inverter',
        'modbus-fake-cli', 1, DATE, VERSION, MANUAL,
        '.B modbus-fake-cli\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(environment, exit_status),
        see_also='.BR modbus-fake-inverter (1),\n.BR modbus-fake-ctl (1)')
