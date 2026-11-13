#!/usr/bin/env python3
"""Modbus Replay: a Modbus TCP capture/replay sidecar — a debug instrument
that sits on the wire between a pv-suite client (the cache, the scraper,
any Modbus master) and the device. Capture mode (--upstream) pipes every
client to the device and dumps both directions to a trace file (--capture,
JSON lines, 0600 — one record per frame with timestamps and the decoded
fields); replay mode (--replay) serves the trace back: every request is
matched against the recorded ones and answered with the most recent
recorded response, so the poll planning, the write-through and the chaos
behavior debug against real hardware traces without the hardware. Exactly
one mode per run.

The sidecar has no control plane (no JSON-lines control server, no ctl/cli
pair — the debug surface is the Modbus port, the trace file and the log).
The startup surface is the flags and their bare env twins — flag > env >
the built-in defaults; there is no config file.
Signals: SIGHUP is logged and ignored (the posture is fixed at start —
there is no live layer), SIGTERM/SIGINT shut down with a session summary.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(here))))   # the repo root — the common/ package

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

import logging

from common.settings.config import is_loopback_host, parse_listen, parse_upstream
from common.runtime.daemon import install_signal_handlers, setup_logging
from common.settings.options import build_parser
from common.runtime.version import version_string
from lib.capture import CaptureProxy
from lib.config import resolve_args
from lib.options import OPTIONS
from lib.replay import ReplayServer
from lib.trace import TraceIndex, TraceWriter
from common.modbus.server import serve_modbus

logger = logging.getLogger('modbus-replay')


def validate(args):
    """Clean one-line failures instead of ugly bind errors (family convention)."""
    problems = []
    try:
        listen_host, listen_port = parse_listen(args.listen)
    except SystemExit as e:
        problems.append(str(e))
        listen_host = listen_port = None
    capture = bool(args.upstream)
    replay = bool(args.replay)
    if capture and replay:
        problems.append('--upstream and --replay are two modes — exactly one per run '
                        '(capture pipes to the device, replay serves the trace)')
    if not capture and not replay:
        problems.append('pick a mode: --upstream HOST:PORT (capture the wire, --capture '
                        'FILE records it) or --replay FILE (serve a trace)')
    if args.capture and not capture:
        problems.append('--capture records the capture mode\'s wire — it needs --upstream, not --replay')
    if capture:
        try:
            parse_upstream(args.upstream)
        except SystemExit as e:
            problems.append(str(e))
    if replay and not os.path.isfile(args.replay):
        problems.append('--replay %s: no such trace file (capture one first: '
                        '--upstream HOST:PORT --capture FILE)' % args.replay)
    return problems


def main():
    import faulthandler
    import signal as _sig
    faulthandler.register(_sig.SIGUSR2)
    if '--version' in sys.argv:
        print(version_string())
        raise SystemExit(0)
    p = build_parser(OPTIONS, description='Modbus Replay: a Modbus TCP capture/replay sidecar — '
                     'capture the wire between a client and the device to a trace file, replay the '
                     'trace later: the poll planning, the write-through and the chaos behavior debug '
                     'against real hardware traces without the hardware.')
    p.add_argument('--man', action='store_true',
                   help='print the man page (roff) to stdout and exit (modbus-replay --man | man -l -)')
    args = p.parse_args()
    if args.man:
        from lib.man import daemon_page
        sys.stdout.write(daemon_page(p))
        raise SystemExit(0)
    # the ladder (lib/config.py): flag > env > the static defaults —
    # written back onto args, every knob the same way
    resolve_args(args)
    setup_logging({'level': args.log_level, 'local_time': args.local_time})
    problems = validate(args)
    if problems:
        for problem in problems:
            logger.error(problem)
        raise SystemExit(1)
    listen_host, listen_port = parse_listen(args.listen)
    if not is_loopback_host(listen_host):
        # the sidecar authenticates nothing and gates nothing — a shared
        # bind is a decision the operator must have made on purpose
        bar = '!' * 66
        logger.warning(bar)
        logger.warning('!! WARNING: the listen address %s is NOT loopback.', args.listen)
        logger.warning('!! The sidecar speaks PLAIN UNAUTHENTICATED Modbus to any peer')
        logger.warning('!! that reaches this port — and a capture traces the wire with')
        logger.warning('!! its secrets included. There is no connect ACL, no tokens, no')
        logger.warning('!! gating. Bind 127.0.0.1 unless sharing it is what you mean.')
        logger.warning(bar)
    # the mode: capture (the upstream pair + the optional trace writer)
    # or replay (the trace index) — validate() pinned exactly one
    if args.replay:
        index = TraceIndex(args.replay)   # a foreign or empty trace refuses here, clean one-liner
        face = ReplayServer(index, replay_speed=args.replay_speed, replay_miss=args.replay_miss,
                            client_timeout=args.client_timeout)
    else:
        upstream_host, upstream_port = parse_upstream(args.upstream)
        face = CaptureProxy(upstream_host, upstream_port, None, args.modbus_timeout,
                            client_timeout=args.client_timeout)
    if args.capture:   # the writer opens before serving (a trace file is a side effect)
        try:
            face.writer = TraceWriter(args.capture, args.upstream)
        except OSError as e:
            logger.error('cannot open the trace %s: %s', args.capture, e)
            raise SystemExit(1)

    def graceful(reason):
        logger.info('%s: shutting down', reason)
        face.stop()   # flips stopping, closes the listener — the accept loops return

    install_signal_handlers(graceful_stop=graceful)
    if hasattr(_sig, 'SIGHUP'):
        def on_hup(signum, frame_):
            logger.info('SIGHUP: nothing to reload (the sidecar has no live layer) — ignoring')
        _sig.signal(_sig.SIGHUP, on_hup)
    try:
        if args.replay:
            serve_modbus(face, listen_host, listen_port)
        else:
            face.serve(listen_host, listen_port)
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        if face.stopping:
            pass   # the signal watcher closed the listener; the summary logs below
        else:
            logger.error('cannot bind %s:%d: %s', listen_host, listen_port, e)
            raise SystemExit(1)
    logger.info('%s summary: %s', 'capture' if not args.replay else 'replay', face.summary())


if __name__ == '__main__':
    main()
