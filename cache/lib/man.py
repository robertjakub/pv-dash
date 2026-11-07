#!/usr/bin/env python3
"""The cache proxy's man pages, generated (common/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff (ported from the original hand-written pages). scripts/gen_man.py
writes the shipped man/*.1 from these; `modbus-cache --man` (and the
ctl/cli's --man) prints the same page."""
from common.manpage import options_section, page

DATE = '2026-11-05'
VERSION = 'pv-suite 0.3.0'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The modbus-cache(1) page: the OPTIONS from the parser, the prose from
    the original page (the proxy story, the signals, the control grammar)."""
    description = """\
\\fBmodbus-cache\\fR owns the single Modbus TCP client connection a device
allows (Huawei SUN2000 inverters and their SDongle/EMMA radios accept
exactly one) and multiplexes it: a background loop polls the configured
register ranges into an in-memory cache, any number of clients are served
FC3/FC4 reads from the cache, reads outside the map and other function
codes are forwarded live, and writes (FC05/06/15/16/22/23) are forwarded
when explicitly enabled and audited. Every function code crossing the
wire is named in the log and the audit trail (all standard FCs, FC1
through FC43). A synthesized diagnostics block at registers
65000\\(en65003 lets clients tell cached data from live data.
.PP
Resilience: when the device dies, cached reads keep serving last-known
values and forwarded reads get exception 0x0B; when the device rejects a
range, the poll status is remembered instead of hammering it; garbage from
either side is answered one line at a time and never fatal. Verified
against the fake inverter, fuzzing and stress suites \\-\\- not against real
hardware."""
    signals = """.SH SIGNALS
.TP
.B SIGHUP
reload the configuration and the register map without dropping clients
(the file always wins over live settings; a broken file keeps the previous
state). The listen address and the log level need a restart.
.TP
.B SIGUSR1
clean the cache: all cached values, on-demand entries and poll-status
errors are dropped; the poller repopulates immediately.
.TP
.BR SIGTERM ", " SIGINT
graceful shutdown."""
    control = """.SH CONTROL
The control server speaks JSON lines: one request
\\fB{"cmd": "..."}\\fR per line, one reply
\\fB{"status": "ok|err|bye", "text": "..."}\\fR per line. Commands
(the settings registry drives the grammar):
.BR set ", " unset ", " show ", " help ,
the reports
.BR inspect ", " "show status" ", " "show connections" ,
.BR "show cache" " [all]" ", " "show uplink" ", " "show version" ,
the ops
.BR "request dump" ", " "request restore" ", " clear\\ cache ,
.BR reload ", " restart ", " shutdown ", " quit .
.RS
.IP \\(bu 2
.B set <setting> <value>
changes a setting live (modbus interval, cache ttl, modbus read-delay,
modbus merge-gap, write allow, write registers, limits max-clients,
limits client-timeout, modbus upstream, modbus unit, metrics enable,
metrics listen, the metrics limits caps, metrics token, requests-audit,
dump-interval, log-level, local-time, modbus profile, modbus selection,
acl connect, acl write, modbus timeout, control port, control token,
control ops-token, control ops-verbs, control trust-uids, control
socket-group, audit log-file, audit rotate max-size, audit disable,
dump path, dump with-cache); a SIGHUP re-applies the config
(the file always wins). A knob the registry marks
.B restart: true
answers the note
.B restart required (startup-only knob)
from set/unset \-\- the config (and a SIGHUP) changes it; show
renders the configured value (a secret knob refuses to show at all
\(em the value renders nowhere).
.IP \\(bu 2
.B show cache all
prints every cached entry: name, words, values, age, expiry, poll status.
.IP \\(bu 2
.B show uplink
analyses the inverter link: session counters (connects, exchanges, bytes,
errors) and one row per poll block with its status, latency (last/mean/max)
and last error.
.IP \\(bu 2
.B request dump
/ \\fBrequest restore\\fR: the write-behind state (the cached words + stamps,
the live setting overrides) to/from the \\fB--dump-path\\fR file; the startup
restore and the shutdown dump run the same path automatically. The dump
commands \\(em and the \\fBdump-interval\\fR setting \\(em show up in the
listings only when a dump path is configured.
.IP \\(bu 2
.B clear cache
/ SIGUSR1, \\fBrestart\\fR (drop the upstream + the cache, repoll),
\\fBreload\\fR (save the live overrides to a state file and re-exec the
whole daemon \\(em the fresh process re-resolves the config, so the
restart-marked knobs take their configured values, and the saved
overrides re-apply once; the cache starts empty),
\\fBshutdown\\fR (the same as SIGTERM).
.RE
.PP
A second, read-only token (\\fB--control-ops-token\\fR) authenticates
sessions into the show/clear verbs only \\(em no set/unset, no request
dump/restore, no reload, no restart, no shutdown \\(em the ops shift against the
admin key, both roles audited. A secret knob (control token, the ops
token, the metrics token \\(em either spelling) never renders: \\fBshow\\fR
answers \\fBerr <name> is a secret \\(em it never shows\\fR, \\fBunset\\fR
refuses \\(em pass the secret by flag/env/token-file.
.PP
See
.BR modbus-cache-ctl (1)
and
.BR modbus-cache-cli (1)
for the clients."""
    environment = """.SH ENVIRONMENT
.TP
.B CTL
default control target for the daemon's clients (flag \\fB--control-port\\fR
wins).
.TP
.B HOST ", " LISTEN ", " ALLOW_WRITE ", " ...
every flag has an environment twin of the same bare name (no tool
prefix); the flag wins over the env, the env over the config script."""
    files = """.SH FILES
.TP
.I /tmp/modbus-cache-<port>.socket
the default control socket (stale files replaced, unlinked on shutdown).
.TP
.I ~/.local/state/modbus-cache/audit.log
the default audit trail.
.TP
.I cache/modbus_cache.conf ", " cache/selection.json
the packaged sample config and the example selection."""
    exit_status = """.SH EXIT STATUS
.TP
.B 0
success (\\fB--dry-run\\fR: valid configuration).
.TP
.B 1
invalid configuration (reason on stderr; \\fB--dry-run\\fR only).
.TP
.B 2
command-line misuse."""
    return page(
        'Modbus TCP caching proxy for single-client devices',
        'modbus-cache', 1, DATE, VERSION, MANUAL,
        '.B modbus-cache\n.RI [ options ]\n.br\n.B modbus-cache \\-\\-dry-run\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, environment, files, exit_status),
        see_also='.BR modbus-cache-ctl (1),\n.BR modbus-cache-cli (1),\n.BR modbus-scraper (1),\n.BR modbus-fake-inverter (1)\n.PP\n\\fBcache/README.md\\fR in the suite checkout \\(em the full documentation.')


def ctl_page(parser):
    description = """\
Sends one control command (or a batch piped on stdin, one per line) to the
\\fBmodbus-cache\\fR JSON-lines control server and prints the replies on
stdout, one per line. Every invocation lands in the audit trail (prefix
\\fBCTL\\fR).
.PP
The command grammar is the daemon's: \\fBset\\fR/\\fBunset\\fR/\\fBshow\\fR/
\\fBhelp\\fR (the settings registry), \\fBinspect\\fR, \\fBshow status\\fR,
\\fBshow connections\\fR, \\fBshow cache\\fR [\\fBall\\fR], \\fBshow uplink\\fR,
\\fBshow version\\fR, \\fBshow knobs\\fR (the dictionary of the registry),
\\fBclear cache\\fR, \\fBrestart\\fR, \\fBshutdown\\fR,
\\fBquit\\fR. See
.BR modbus-cache (1)
CONTROL."""
    examples = """.SH EXAMPLES
.RS
.IP \\(bu 2
.B modbus-cache-ctl show status
.IP \\(bu 2
.B modbus-cache-ctl clear cache
.IP \\(bu 2
.B printf 'show cache\\\\nclear cache\\\\n' | modbus-cache-ctl
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
        'one-shot control client for the modbus-cache daemon',
        'modbus-cache-ctl', 1, DATE, VERSION, MANUAL,
        '.B modbus-cache-ctl\n.RI [ options ]\n.IB command " [args ...]"\n.br\n.B modbus-cache-ctl\n.RI [ options ]\n< commands',
        description,
        options_section(parser),
        extra_sections=(examples, exit_status),
        see_also='.BR modbus-cache (1),\n.BR modbus-cache-cli (1)')


def cli_page(parser):
    description = """\
An interactive console on the \\fBmodbus-cache\\fR JSON-lines control
server: on connect it probes the daemon and greets you with the upstream,
the poll health and the uptime; the prompt shows the connected port
(\\fBcache:15502 >\\fR). TAB completes commands, settings and values with
their descriptions (the listings group the settings under the registry's
own groups \\(em ungrouped rows render bare, no header \\(em, with
[values] beside);
\\fB?\\fR prints the same in any position; \\fBclear cache\\fR/\\fBrestart\\fR
confirm; \\fBshutdown\\fR asks \\fBProceed with shutdown? [confirm]\\fR first.
.PP
While idle the session sends wire pings every 55 s so the server's idle
timeout never drops it; when the connection dies anyway, the console
retries (default 3 times, 10 s apart) and resumes on the first success.
The session (connect/disconnect, local commands, an aborted shutdown) is
audited with the \\fBCLI\\fR prefix; the wire commands are audited once, by
the server."""
    environment = """.SH ENVIRONMENT
.TP
.B CLI_KEEPALIVE
idle ping interval, seconds (default \\fB55\\fR); \\fB0\\fR = off.
.TP
.B CTL ", " CONTROL_TOKEN
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
        'console-style control session for the modbus-cache daemon',
        'modbus-cache-cli', 1, DATE, VERSION, MANUAL,
        '.B modbus-cache-cli\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(environment, exit_status),
        see_also='.BR modbus-cache (1),\n.BR modbus-cache-ctl (1)')
