#!/usr/bin/env python3
"""The record feed's one home (stdlib only): the trace/socket + trace/sources
knobs' shared hub. The cache emits its wire records here — the client face's
served answers (provenance in the note), the upstream poller's block polls,
the forwarded exchanges, the byte-less auth marker — and the hub fans every
accepted record out to the feed socket in the family's PVMB encoding
(common/modbus/trace.py), where modbus-replay-dump --socket renders them
live. The sources knob is a whole-voice filter, never sampling: a dropped
voice is stated by the knob, a dropped frame would be a lie (the orphan is
the device-died signal). The socket knob speaks none (off — the built-in
default), default (the derived /tmp/modbus-cache-<listen-port>-trace.socket;
the -trace suffix is mandatory — the control plane owns the un-suffixed
path and the feed's bind unlinks first) or a path. Every control `set`
rebinds — ALL transitions, the same path included: close (the subscribers
see EOF, they re-subscribe), unlink, bind; the reload path (apply_config)
rebinds only on a value change — restoring the standing values on a SIGHUP
is not a set, the subscribers keep their stream."""
import logging
import os
import threading
import time

from common.modbus.trace import FeedSocket, TraceWriter
from .config import TRACE_SOCKET_TEMPLATE, parse_trace_socket, parse_trace_sources

logger = logging.getLogger('modbus-cache')

# the upstream face's conn space: UPSTREAM_CONN_BASE + the connection serial
# — the client face counts from 1, the feed's pairing key is (session, conn,
# txn) and the client's txn survives the forward verbatim, so the two spaces
# must never collide
UPSTREAM_CONN_BASE = 100000


class TraceHub:
    """The feed socket + the sources filter + the voice guards, one object
    the proxy's emit points and the control server's set/clear branches
    share."""

    def __init__(self, socket_val='none', sources='all', default_path=None, posture=None):
        """default_path: a zero-arg callable returning the derived socket path
        (the listen port's word — the hub resolves 'default' at bind time);
        posture: a zero-arg callable returning the run-header posture string
        (what the dump tool's banner shows)."""
        self._socket_val = parse_trace_socket(socket_val)
        self._sources_val = parse_trace_sources(sources)
        self._default_path = default_path
        self._posture = posture
        self._writer = None
        self._lock = threading.Lock()   # the rebind against the in-flight emits

    # --- the knob values ---

    def socket_val(self):
        return self._socket_val

    def sources_val(self):
        return self._sources_val

    def describe_socket(self):
        """The knob value for the wire: 'none', 'default (the derived path)'
        or the path."""
        if self._socket_val == 'none':
            return 'none'
        if self._socket_val == 'default':
            return 'default (%s)' % self._path()
        return self._socket_val

    def describe_sources(self):
        return self._sources_val

    def records(self):
        return self._writer.n if self._writer else 0

    def _path(self):
        return self._default_path() if self._default_path else TRACE_SOCKET_TEMPLATE % 0

    def _resolved(self, val):
        """The word -> the concrete path ('default' spelled out)."""
        return self._path() if val == 'default' else val

    # --- the bind/unbind ---

    def _bind(self, socket_val):
        """The feed for the value: close the standing one first (the
        subscribers see EOF and re-subscribe — every transition rebinds),
        then bind the new socket when the value is not none."""
        with self._lock:
            old, self._writer = self._writer, None
        if old is not None:
            old.close()
        if socket_val == 'none':
            return None
        writer = TraceWriter(None, dump_type='binary', feed=FeedSocket(self._resolved(socket_val),
                                                                       self._posture() if self._posture else 'modbus-cache'))
        with self._lock:
            self._writer = writer
        logger.info('the record feed on %s (sources %s)', self._resolved(socket_val),
                    self._sources_val)
        return writer

    def startup(self):
        """The start bind (the knob came from the config): nothing when off —
        the hub stays a no-op guard and the start log stays silent."""
        if self._socket_val != 'none':
            self._bind(self._socket_val)

    def set_socket(self, val):
        """The control set/clear path: parse, then rebind — every transition,
        the same value included (the subscriber's stream drops, the socket
        file is replaced). A bind that fails (a bad path) rolls the knob and
        the feed back to the standing value — the old feed stands; ValueError
        on a bad value or a failed bind."""
        parsed = parse_trace_socket(val)
        prev = self._socket_val
        self._socket_val = parsed
        try:
            self._bind(parsed)
        except OSError as e:
            self._socket_val = prev
            try:
                self._bind(prev)   # the old feed stands (it bound moments ago; a refusal here leaves the feed down)
            except OSError:
                pass
            raise ValueError('cannot bind the feed socket: %s' % e)
        return self.describe_socket()

    def set_sources(self, val):
        """The control set/clear path: the voice filter swaps atomically —
        no rebind, the socket and its subscribers keep their stream."""
        parsed = parse_trace_sources(val)
        self._sources_val = parsed
        if self._writer is not None and self._writer.feed is not None:
            logger.info('the record feed on %s (sources %s)',
                        self._writer.feed.path, parsed)
        return self.describe_sources()

    def apply_config(self, socket_val, sources):
        """The reload path (SIGHUP, the re-exec's config): swap the sources
        always, rebind the socket only on a value change — restoring the
        standing values is not a set."""
        parsed_sources = parse_trace_sources(sources)
        parsed_socket = parse_trace_socket(socket_val)
        sources_changed = parsed_sources != self._sources_val
        socket_changed = parsed_socket != self._socket_val
        self._sources_val = parsed_sources
        if sources_changed:
            self.set_sources(parsed_sources)   # the swap logs the feed's new voices
        if socket_changed:
            self._socket_val = parsed_socket
            self._bind(parsed_socket)

    def close(self):
        """The shutdown: the feed closed, the socket file unlinked."""
        with self._lock:
            old, self._writer = self._writer, None
        if old is None:
            return
        path = old.feed.path if old.feed is not None else None
        old.close()
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    # --- the emit point ---

    def emit(self, voice, kind, conn, peer, note, raw):
        """One wire record from one voice ('client' | 'upstream'): the
        sources guard first, then the writer (the feed fan-out; no file —
        the feed-only ruling). A None writer or a silenced voice is a
        no-op: every emit point in the proxy is one guard away."""
        if self._writer is None or (self._sources_val != 'all' and self._sources_val != voice):
            return
        self._writer.emit(round(time.time(), 6), kind, conn, peer, note, raw)
