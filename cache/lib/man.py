#!/usr/bin/env python3
"""The cache proxy's man pages, generated (common/render/manpage.py): the OPTIONS
sections render from the tools' argparse parsers, the prose sections live
here as roff (ported from the original hand-written pages). scripts/gen_man.py
writes the shipped man/*.1 from these; `modbus-cache --man` (and the
ctl/cli's --man) prints the same page."""
from common.render.manpage import EXIT_STATUS_CLI, EXIT_STATUS_DAEMON, options_section, page

DATE = '2026-11-05'
VERSION = 'pv-suite 0.4.3'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The modbus-cache(1) page: the OPTIONS from the parser, the prose from
    the original page (the proxy story, the signals, the control grammar)."""
    description = """\
\\fBmodbus-cache\\fR owns the single Modbus TCP client connection a device
allows (e.g. a Huawei SUN2000 inverter and its SDongle/EMMA radio accept
exactly one) and multiplexes it: a background loop polls the configured
register ranges into an in-memory cache, any number of clients are served
FC3/FC4 reads from the cache, reads outside the map and other function
codes are forwarded live, and writes (FC05/06/15/16/22/23) are forwarded
when explicitly enabled and audited \\(em gated by a register allow-list
(\\fB--write-registers\\fR) that spells its ranges directly, takes the
device profile's \\fBacl\\fR/\\fBwrite\\fR gate (the ordered rule chain:
one \\fBtype\\fR allow/deny and a \\fBrange\\fR per rule \\(em the last
matching rule decides, a register no rule decides refuses, the word
\\fBany\\fR = all registers), or reads a standalone acl file
(\\fBfile:<path>\\fR \\(em the same gate object a profile carries under
write-acl, compiled at start and on every set). Every function code crossing the
wire is named in the log and the audit trail (all standard FCs, FC1
through FC43). A synthesized diagnostics block at registers
65000\\(en65003 lets clients tell cached data from live data.
.PP
Modbus auth (\\fB--modbus-auth\\fR): with \\fBsuite\\fR the cache's own clients
prove a shared key (\\fB--modbus-auth-key\\fR, min 16 characters) with a crypt
handshake right after every connect \\(em 52 bytes: magic, fresh nonce,
HMAC\\-SHA256 proof; the cache answers \\fBOK\\fR (plain Modbus follows)
or \\fBERR\\fR (the client is dropped before it ever sees a frame).
\\fB--modbus-auth-upstream\\fR/\\fB--modbus-auth-upstream-key\\fR do the same toward
the inverter: an \\fBERR\\fR fails the exchange like any other upstream
fault and the poller retries. The upstream leg also speaks
\\fB--modbus-auth-upstream waveshare\\fR for a Waveshare RS485\\-to\\-TCP
gateway: the shared key goes out as the gateway's connection password
(raw ASCII, right after every connect) and the gateway's \\fBOK\\fR opens
the plain Modbus session \\(em anything else fails the exchange like any
other upstream fault. Empty auth = no auth at all.
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
\\fB{"status": "ok|fail|note|bye", "text": "..."}\\fR per line. Commands
(the settings registry drives the grammar):
.BR set ", " clear ", " show ", " help ,
the reports
.BR inspect ", " "show connections" ,
.BR "show cache" " [all]" ", " "show write-registers-table" ,
.BR "show uplink" ", " "show uplink-sources" ", " "show version" ,
.BR "show connect-acl-table" ", " "show write-acl-table" ,
.BR "show metrics-acl-table" ,
the ops
.BR "request dump" ", " "request restore" ", " "request flush cache" ,
.BR "request reload" ", " "request reload-config" ", " "request restart" ", " shutdown ", " quit .
.RS
.IP \\(bu 2
.B set <setting> <value>
changes a setting live (modbus-interval, cache-ttl, modbus-read-delay,
modbus-merge-gap, allow-write, write-registers, max-clients,
client-timeout, upstream, modbus-unit, metrics-server,
metrics-listen, the metrics caps, metrics-acl,
audit-requests, dump-interval, log-level, local-time, modbus-profile,
selection, connect-acl, write-acl, modbus-timeout, modbus-auth,
modbus-auth-upstream, control-port, control-ops-verbs, control-trust-uids,
control-socket-group, audit-log, audit-forward, audit-max-mb,
no-audit-log, dump-path, dump-with-cache); a SIGHUP \\(em or the wire's
\\fBrequest reload-config\\fR \\(em re-applies the config
(the file always wins). A knob the registry marks
.B restart: true
answers the note
.B restart required (startup-only knob)
from set/clear \\-\\- the set records the value (show renders it; the
whole-daemon reload folds it into the fresh process before the binds),
the config (and a SIGHUP) changes it too. Every secret in the registry
is restart-marked (the tokens, the auth keys, dump-key) and refuses
set/clear outright: a secret never rides the reload state (a secret knob
refuses to show at all \\-\\- the value renders nowhere) \\-\\- it passes
by flag/env/config and a restart.
.IP \\(bu 2
.B show cache-all
prints every cached entry: name, words, values, age, expiry, poll status.
.IP \\(bu 2
.B show uplink
analyses the inverter link: session counters (connects, exchanges, bytes,
errors) and one row per poll block with its status, latency (last/mean/max)
and last error.
.B show uplink-sources
spells the register map: one row per polled register \\(em its fc,
register address, the range that fetches it and the source name (the
health columns stay the blocks').
.IP \\(bu 2
.B show write-registers-table
renders the write gate as its acl chain (show-only): \\fBallow any\\fR /
\\fBdeny any\\fR, a range list as its whitelist (deny any, then one allow
line per range), and in profile or file mode the gate's own rules \\(em
the gate's desc as the % line, then one allow/deny line per range with
its desc, the comments aligned.
.IP \\(bu 2
.B show acl connect table
/ \\fBshow write-acl-table\\fR / \\fBshow metrics-acl-table\\fR render the
IP ACL as its chain, one
entry per line (show-only): \\fBallow 0.0.0.0/0\\fR (any), \\fBdeny
0.0.0.0/0\\fR (none), \\fBdeny 0.0.0.0/0\\fR then one \\fBallow\\fR line
per network (the whitelist) \\(em and in file mode the ip-prefix gate's
own rules, the gate desc as the % line, the rule descs as aligned
comments.
.IP \\(bu 2
.B request dump
/ \\fBrequest restore\\fR: the write-behind state (the cached words + stamps,
the live setting overrides) to/from the \\fB--dump-path\\fR file; the startup
restore and the shutdown dump run the same path automatically. An overridden
secret rides as \\fB*** SECRET REMOVED ***\\fR \\(em the knob renders, the
value never lands in the file, the restore skips the placeholder and names
it. With \\fB--dump-key\\fR the dump is sealed: the state rides encrypted
(an HMAC\\-SHA256 counter\\-mode keystream, authenticated \\(em a restore
refuses a wrong or missing key). The dump
commands \\(em and the \\fBdump-interval\\fR setting \\(em show up in the
listings only when a dump path is configured.
.IP \\(bu 2
.B request flush cache
/ SIGUSR1, \\fBrequest restart\\fR (drop the upstream + the cache, repoll),
\\fBrequest reload\\fR (save the live overrides to a state file and re-exec the
whole daemon \\(em the fresh process re-resolves the config, so the
restart-marked knobs take their configured values, and the saved
overrides re-apply once; the cache starts empty),
\\fBrequest reload-config\\fR (re-read the config file without the
restart \\(em the same re-apply as a SIGHUP; a broken file keeps the
previous settings),
\\fBshutdown\\fR (the same as SIGTERM).
.RE
.PP
See
.BR modbus-cache-cli (1)
for the client."""
    security = """.SH SECURITY
The control surface is loopback-only (TCP) or a 0600 unix socket; a TCP
control-port without a token refuses to start (F5); with a token the
wire is signed and the commands/replies verify end to end; a second,
read-only ops token (\\fB--control-ops-token\\fR) authenticates sessions
into its policy's verbs only \\(em the default policy: show,flush \\(em
no set/clear, no request dump/restore, no request reload, no request
restart, no shutdown \\(em
the ops shift against the admin key, both roles audited. A secret knob
(control token, the ops token, the metrics token, modbus auth key, dump
key) never shows its value: \\fBshow\\fR answers \\fBerr <name> is a
secret \\(em it never shows\\fR, \\fBclear\\fR refuses \\(em pass the
secret by flag/env, or as \\fBfile:<path>\\fR; \\fBshow config\\fR and the
dumps render the knob as \\fB*** SECRET REMOVED ***\\fR (the config
parser refuses the placeholder \\(em it is never a value).
.PP
The Modbus port is read-only until the write gate says otherwise:
writes ride \\fB--write-registers\\fR (the direct ranges, the profile's
write-acl chain or a \\fBfile:<path>\\fR acl) and every accepted or
refused write lands in the audit trail (WRITE / WRITE\\-REFUSED). The
\\fB--connect-acl\\fR IP gate (connect-acl) filters who may connect at
all; the metrics endpoint carries the family's one /metrics stack (F13):
a token-less non-loopback bind refuses to start, the metrics-acl IP
gate narrows who reaches the endpoint, the caps bound the concurrency.
With \\fB--dump-key\\fR the state file is sealed (an HMAC\\-SHA256
counter\\-mode keystream, authenticated \\(em a restore refuses a wrong
or missing key). The audit trail (in the XDG state home when
\\fB--audit-log\\fR is unset, prefix CACHE) records the control commands
with their roles, the auth failures, the writes and the reloads. With
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
    environment = """.SH ENVIRONMENT
.TP
.B CTL
control target for the daemon's clients when the flag is unset (flag
\\fB--control-port\\fR wins).
.TP
.B LISTEN ", " INTERVAL ", " ALLOW_WRITE ", " ...
every flag has an environment twin of the same bare name (no tool
prefix — the exceptions spell their own: `--control-port`'s is `CTL`,
`--cache-ttl`'s `TTL`); the flag wins over the env, the env over the
config script."""
    files = """.SH FILES
.TP
.I /tmp/modbus-cache-<port>.socket
the control socket used when \\fB--control-port\\fR is unset (stale files
replaced, unlinked on shutdown).
.TP
.I ~/.local/state/modbus-cache/audit.log
the audit trail when \\fB--audit-log\\fR is unset.
.TP
.I cache/examples/modbus-cache.conf ", " extras/examples/modbus-cache-filter.json ,
.I extras/examples/acl-write-registers.json
the packaged sample config, the example selection and the example acl
file in the shared examples home (the deye write policy for \\fB--write-registers
file:<path>\\fR \\(em
a group/world-readable acl file warns in the log, the audit trail
(ACL-FILE) and on the set/clear reply; chmod 0600 silences it)."""
    exit_status = EXIT_STATUS_DAEMON
    return page(
        'Modbus TCP caching proxy for single-client devices',
        'modbus-cache', 1, DATE, VERSION, MANUAL,
        '.B modbus-cache\n.RI [ options ]\n.br\n.B modbus-cache \\-\\-dry-run\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, control, security, environment, files, exit_status),
        kind='daemon',
        see_also='.BR modbus-cache-cli (1),\n.BR modbus-scraper (1),\n.BR modbus-fake-inverter (1)\n.PP\n\\fBcache/README.md\\fR in the suite checkout \\(em the full documentation.')



def cli_page(parser):
    description = """\
One client, three modes by the invocation shape: command words one-shot
(\\fBmodbus-cache-cli\\fR show config\\fR \\(em the raw verdict head prints,
exit 0 ok, 1 connection error, 2 misuse), piped stdin batch (the script lines
run in order, the same raw faces), a bare terminal the interactive console.
.PP
An interactive console on the \\fBmodbus-cache\\fR JSON-lines control
server: on connect it probes the daemon and greets you with the upstream,
the poll health and the uptime; the prompt shows the connected port
(\\fBcache:15502 >\\fR). TAB completes commands, settings and values with
their descriptions (the listings group the settings under the registry's
own groups \\(em ungrouped rows render bare, no header \\(em, with
[values] beside);
\\fB?\\fR prints the same in any position; \\fBset\\fR/\\fBclear\\fR confirm
\\fB% changed\\fR (the errors print \\fB% error: <message>\\fR, the ok
replies' messages print bare);
\\fBrequest flush cache\\fR/\\fBrequest restart\\fR
confirm silently; \\fBshutdown\\fR asks
\\fBProceed with shutdown? [confirm]\\fR first.
.PP
Every reply prints through the console's pager: a text taller than the
screen pauses at a page \\(em space prints the next page, return one more
line, \\fBq\\fR stops the rest (the command already ran; only the
rendering stops). \\fB--page-size\\fR/\\fBCLI_PAGE_SIZE\\fR set the page
size (\\fB0\\fR = off, empty = the terminal height); a session-local
\\fBpage\\fR command retunes it live (never sent to the daemon); a
terminal smaller than 20 rows or 64 columns refuses to start.
.PP
While idle the session sends wire pings so the server's idle
timeout never drops it; when the connection dies anyway, the console
retries (\\fB--reconnect\\fR attempts, \\fB--reconnect-wait\\fR seconds
apart) and resumes on the first success.
The session (connect/disconnect, local commands, an aborted shutdown) is
audited with the \\fBCLI\\fR prefix; the wire commands are audited once, by
the server."""
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
        'console-style control session for the modbus-cache daemon',
        'modbus-cache-cli', 1, DATE, VERSION, MANUAL,
        '.B modbus-cache-cli\n.RI [ options ]\n.IB command " [args ...]"',
        description,
        options_section(parser),
        extra_sections=(environment, exit_status),
        kind='cli',
        see_also='.BR modbus-cache (1)')
