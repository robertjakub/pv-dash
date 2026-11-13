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
file (\\fB--capture\\fR, JSON lines, 0600 \\(em one record per frame with
timestamps, direction and the decoded fields; the trace appends across
runs, each run stamping its header line). A frame the framing cannot
parse still reaches the device and rides the trace raw \\(em the tap
never holds the pipe. Without \\fB--capture\\fR the proxy runs
pass-through and the decoded frames log at DEBUG only.
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
sidecar's whole surface is the Modbus port and the files. The trace
file holds the wire's values and names \\(em and a capture of a
Waveshare gateway carries the connection password raw \\(em so traces
write 0600 and belong with the secrets; the audit habit ends here too
\\(em the trace IS the record (every frame, both directions,
timestamped), a second accounting of the same wire would only drift
from it."""
    environment = """.SH ENVIRONMENT
.TP
.B UPSTREAM ", " CAPTURE ", " REPLAY ", " REPLAY_SPEED ", " REPLAY_MISS
the mode knobs: capture (the device endpoint + the trace out) or replay
(the trace in) with its speed and miss policy \\(em the start reads
them too (flag > env).
.TP
.B LISTEN ", " CLIENT_TIMEOUT ", " MODBUS_TIMEOUT ", " LOG_LEVEL ", " ...
every flag has an environment twin of the same bare name (no tool
prefix); the flag wins over the env."""
    files = """.SH FILES
.TP
.I the trace (--capture / --replay)
the wire dump: JSON lines, 0600, one record per frame
("format": "pv\\-suite\\-modbus\\-trace", version 1) \\(em the capture
side appends, the replay side reads; the format version mismatches
refuse (re\\-capture)."""
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
        '.B modbus-replay\n.RI [ options ]\n.br\n.B modbus-replay \\-\\-upstream inverter-lan:502 \\-\\-capture trace.jsonl\n.RI [ options ]\n.br\n.B modbus-replay \\-\\-replay trace.jsonl\n.RI [ options ]',
        description,
        options_section(parser),
        extra_sections=(signals, security, environment, files, exit_status),
        kind='sidecar',
        see_also='.BR modbus-cache (1),\n.BR modbus-scraper (1),\n.BR modbus-fake-inverter (1)\n.PP\n\\fBapps/modbus-replay/README.md\\fR in the suite checkout \\(em the full\ndocumentation, the trace format included.')
