#!/usr/bin/env python3
"""modbus-replay's man page, generated (common/render/manpage.py): the
OPTIONS section renders from the tool's argparse parser, the prose
sections live here as roff. dev/generators/man.py writes the shipped
man/modbus-replay.1 from this; `modbus-replay --man` prints the same
page. The page class is 'sidecar' — the daemon ladder without the
CONTROL section: the sidecar has no control plane."""
from common.render.manpage import options_section, page

DATE = '2026-11-13'
VERSION = 'pv-suite 0.5.1'
MANUAL = 'User Commands'


def daemon_page(parser):
    """The modbus-replay(1) page: the OPTIONS from the parser, the prose
    from the sidecar's own story (the capture/replay pair, the trace
    format, the no-control-plane posture)."""
    description = """\\
A stdlib-only Modbus TCP capture/replay sidecar: it sits on the wire
between a pv-suite client (the cache, the scraper, any Modbus master)
and the device, dumps every frame to a trace file \\(em and replays the
trace later, so the poll planning, the write-through and the chaos
behavior debug against real hardware traces without the hardware.
Exactly one mode per run: \\fB--upstream\\fR (capture) or \\fB--replay\\fR.
The startup surface is the flags and their bare env twins \\(em flag >
env > the built-in defaults; there is no config file.
.PP
Capture mode is a pipe with a shadow copy: every client that connects
is paired with an upstream connection to the device, bytes flow as they
arrive, and the MBAP frames both directions reassemble into the trace
file (\\fB--capture\\fR, 0600 \\(em one record per frame with timestamps,
direction and the raw bytes; the binary PVMB blocks by default, the
JSON v1 lines per \\fB--dump-type json\\fR; the trace appends across
runs, each run stamping its header). A frame the framing cannot parse
still reaches the device and rides the trace raw \\(em the tap never
holds the pipe; the auth handshakes (the PVA1 proof, the Waveshare
password, their verdicts) peel and name the same way \\(em the raw
bytes ride verbatim. Without \\fB--capture\\fR the proxy runs
pass-through and the decoded frames log at DEBUG only.
.PP
Every record also fans out to the record feed (\\fB--dump-socket\\fR,
bound by default at the derived
/tmp/modbus\\-replay\\-<listen\\-port>.socket): a unix socket, read-only
push, the binary encoding verbatim \\(em modbus\\-replay\\-dump(1)
subscribes and renders the conversations live.
.PP
Replay mode serves the trace: every incoming request is matched against
the recorded ones (unit + function code + PDU bytes, transaction ids
aside \\(em the replay speaks the client's own ids) and answers the most
recent recorded response, exception frames included \\(em the device's
truth, verbatim. \\fB--replay-speed\\fR replays the recorded device
latencies (1 = as captured, N = N times faster, 0 = immediately).
A request the trace never recorded answers per \\fB--replay-miss\\fR:
exception 11 (the default \\(em a miss is loud in the client's error
counters) or a zero-filled reply of the right shape (a changed poll
plan keeps running and shows its shape); either way the miss logs.
Writes answer their recorded responses \\(em the trace is a record, not
a device: nothing accumulates, a write followed by a read still reads
what the hardware read at capture time."""
    signals = """.SH SIGNALS
.TP
.B SIGHUP
logged and ignored \\(em the sidecar has no live layer to re-apply;
the capture posture is fixed at start (restart to change it).
.TP
.BR SIGTERM ", " SIGINT
graceful shutdown with a session summary (the trace closes flushed)."""
    security = """.SH SECURITY
The sidecar is a debug instrument: run it on a trusted, LAN-isolated
network, next to the tools it debugs. The Modbus surface speaks to any
peer that can reach the port \\(em no TLS and no connection gating
(there is no connect ACL and no client caps \\(em only
\\fB--client-timeout\\fR kicks the silent). A listen past loopback
(127.0.0.1, ::1, localhost) is therefore refused nothing but warned
loudly: the start logs a five\\-line WARNING banner naming the shared
bind and what it exposes. There is no control plane:
no tokens, no control socket, nothing to authenticate \\(em the
record feed is a read\\-only push (no verbs, no tokens, nothing a
command could ride), not a listener that answers. The trace
file holds the wire's values and names \\(em and a capture of a
Waveshare gateway carries the connection password raw, a suite\\-auth
capture the PVA1 proof (a leaked trace can replay it at any server
holding the key) \\(em so traces
write 0600 and belong with the secrets; the audit habit ends here too
\\(em the trace IS the record (every frame, both directions,
timestamped), a second accounting of the same wire would only drift
from it."""
    environment = """.SH ENVIRONMENT
.TP
.B UPSTREAM ", " CAPTURE ", " REPLAY ", " REPLAY_SPEED ", " REPLAY_MISS ", " DUMP_TYPE ", " DUMP_SOCKET
the mode knobs: capture (the device endpoint + the trace out) or replay
(the trace in) with its speed and miss policy, the trace's shape
(binary \\(em the default \\(em or the v1 JSON lines) and the record
feed's socket (the default derives from the listen port; \\fBnone\\fR
binds no feed) \\(em the start reads them too (flag > env)."""
    files = """.SH FILES
.TP
.I the trace (--capture / --replay)
the wire dump: 0600, one record per frame \\(em the binary PVMB blocks
by default (the magic
.BR PVMB , version 1; the byte layout lives in the README) or the JSON
v1 lines ("format": "pv\\-suite\\-modbus\\-trace", version 1) per
\\fB--dump-type json\\fR \\(em the capture side appends, the replay side
reads both shapes; a foreign file or a future version refuses
(re\\-capture), a torn tail keeps what parsed.
.TP
.I /tmp/modbus\\-replay\\-<listen\\-port>.socket
the record feed (\\fB--dump-socket\\fR): the records push to the
connected modbus\\-replay\\-dump(1) viewers, read\\-only, best effort."""
    exit_status = """.SH EXIT STATUS
.TP
.B 0
success (SIGTERM/SIGINT: the graceful shutdown).
.TP
.B 1
invalid configuration or a failed bind (reason on stderr).
.TP
.B 2
command-line misuse."""
    return page(
        'capture and replay a Modbus TCP wire trace',
        'modbus-replay', 1, DATE, VERSION, MANUAL,
        '.B modbus-replay\n.RI [ options ]\n.br\n.B modbus-replay \\-\\-upstream inverter-lan:502 \\-\\-capture trace.pvmb\n.RI [ options ]\n.br\n.B modbus-replay \\-\\-replay trace.pvmb\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, security, environment, files, exit_status),
        kind='sidecar',
        see_also='.BR modbus-replay-dump (1),\n.BR modbus-cache (1),\n.BR modbus-scraper (1),\n.BR modbus-fake-inverter (1)\n.PP\n\\fBapps/modbus-replay/README.md\\fR in the suite checkout \\(em the full\ndocumentation, the trace format\'s byte layout included.')


def dump_page(parser):
    """The modbus-replay-dump(1) page: the reader face's own page \\(em
    the three views, the converter, the live view; the sidecar ladder
    (no CONTROL \\(em the feed is read-only push, not a control plane)."""
    description = """\\
The trace's reader face \\(em the ctl/cli sibling shape, minus the
control plane (there is nothing to control: the trace is the record).
Both trace shapes read the same \\(em the binary
.B PVMB
blocks (the capture default) or the JSON v1 lines; the first bytes
pick the walk. The byte layout lives in the tool's README.
.PP
The static views (no flags): the summary line (what the trace holds),
the answer index \\(em one line per unique (unit, request PDU): the
query, the recorded reply the replay will serve (the read data's hex
words included), the recorded latency, the ask count \\(em and the
conversations \\(em the per\\-connection query\\->answer diagram: one
block per connection with the client's peer, one line per exchange
(request \\-> response, both frame numbers, the recorded latency), the
concurrent connections named, the unpaired records marked in place
(no answer recorded / orphan / the raw handshake lines).
.PP
The converter (\\fB--to json|binary \\-o OUT\\fR): either shape reads,
the other writes \\(em the raw bytes are the one truth (the JSON side
re\\-derives the decoded echo, never copies it), so a
binary\\->json\\->binary round trip lands byte\\-identical; the run
boundaries re\\-stamp, a torn tail converts as far as it parsed, the
crc recomputes.
.PP
The live view (\\fB--socket\\fR [PATH]): the daemon's record feed
(\\fB--dump-socket\\fR) pushes every record as it lands \\(em the
conversations render realtime; a request prints pending, its response
completes the exchange with the latency. Bare \\fB--socket\\fR spells
the derived default (/tmp/modbus\\-replay\\-<listen\\-port>.socket)."""
    signals = """.SH SIGNALS
.TP
.BR SIGTERM ", " SIGINT
the live view ends cleanly \\(em no traceback, a zero exit; the file
views never wait."""
    security = """.SH SECURITY
The trace is 0600 at rest and belongs with the secrets: the wire
carries values and names, a Waveshare capture carries the connection
password raw, a suite\\-auth capture the PVA1 proof (a leaked trace
can replay it at any server holding the key). The record feed is a
read\\-only push on a unix socket \\(em no verbs, no tokens, nothing a
command could ride; a subscriber that cannot keep up is dropped (the
trace file has everything)."""
    environment = """.SH ENVIRONMENT
.TP
.B none
the dump reads its flags only \\(em the daemon's env twins (DUMP_TYPE,
DUMP_SOCKET) live on
.BR modbus-replay (1)."""
    files = """.SH FILES
.TP
.I the trace file
the wire dump: 0600 \\(em the binary PVMB blocks (the capture default)
or the JSON v1 lines (\\fB--dump-type json\\fR); both shapes read the
same.
.TP
.I /tmp/modbus\\-replay\\-<listen\\-port>.socket
the daemon's record feed (\\fB--dump-socket\\fR) \\(em bare
\\fB--socket\\fR spells this default."""
    exit_status = """.SH EXIT STATUS
.TP
.B 0
success (the live view: ^C ends it cleanly).
.TP
.B 1
a refusal \\(em a foreign trace, a missing source, a bad combination
(reason on stderr).
.TP
.B 2
command-line misuse."""
    return page(
        'read, convert and follow a Modbus wire trace',
        'modbus-replay-dump', 1, DATE, VERSION, MANUAL,
        '.B modbus-replay-dump\n.B trace\n.RI [ options ]\n.br\n.B modbus-replay-dump \\-\\-to json \\-o trace.jsonl trace.pvmb\n.br\n.B modbus-replay-dump \\-\\-socket\n.RI [ path ]',
        description,
        options_section(parser),
        extra_sections=(signals, security, environment, files, exit_status),
        kind='sidecar',
        see_also='.BR modbus-replay (1)\n.PP\n\\fBapps/modbus-replay/README.md\\fR in the suite checkout \\(em the\ntrace format\'s byte layout, the feed\'s story.')
