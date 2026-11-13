#!/usr/bin/env python3
"""The capture face (stdlib only): a Modbus TCP proxy that pipes every
client to the device and taps the wire into the trace writer. One
connection pair (client leg + upstream leg) per accepted client, one
pump thread per direction, the tap (lib/trace.py FrameTap) reassembling
the MBAP frames from the piped bytes without ever holding them — the
pipe's first job is to move the bytes, the trace is the shadow copy.
There is no connection gating (no ACL, no caps — any peer that can
reach the port is piped; --client-timeout kicks the silent legs); an
upstream that will not connect (or dies mid-session) ends the pair —
the client's own reconnect logic re-dials and opens a fresh pair, like
any device hiccup it is part of the trace."""
import logging
import socket
import threading
import time

from common.serve.connlimit import limits_words
from .trace import FrameTap, describe_frame

logger = logging.getLogger('modbus-replay')

CHUNK = 65536


class CaptureProxy:
    """The capture proxy: serve(host, port) runs the accept ladder until
    stopping; every client gets an upstream connection and two pump
    threads (client->device, device->client). Counters feed the shutdown
    summary; the frames land in the trace writer (when one is set) and
    decode into the DEBUG log."""

    def __init__(self, upstream_host, upstream_port, writer, modbus_timeout,
                 client_timeout=0.0):
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.writer = writer
        self.modbus_timeout = modbus_timeout
        self.client_timeout = client_timeout
        self.stopping = False
        self.listen_sock = None
        self.conns = 0            # accepted pairs
        self.frames = {'c2d': 0, 'd2c': 0}
        self.bytes_piped = {'c2d': 0, 'd2c': 0}
        self.undecoded = 0
        self.count_lock = threading.Lock()
        self.pumps = []           # the live pump sockets (the stop closes them)
        self.pumps_lock = threading.Lock()

    def access(self, fmt, *args):
        logger.info(fmt, *args)   # the connects/disconnects always speak at INFO

    def listening(self, host, port):
        caps = ' '.join(limits_words(0, self.client_timeout, 0))
        trace = ('trace %s' % self.writer.path) if (self.writer and self.writer.path) \
            else ('the feed only, no trace file' if self.writer
                  else 'pass-through, no trace')
        logger.info('capture proxy on %s:%d -> %s:%d (%s%s)', host, port,
                    self.upstream_host, self.upstream_port, trace,
                    (', ' + caps) if caps else '')

    def stop(self):
        self.stopping = True
        with self.pumps_lock:
            socks = list(self.pumps)
            self.pumps = []
        for s in socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        if self.listen_sock:
            try:
                self.listen_sock.close()
            except OSError:
                pass
        if self.writer:
            self.writer.close()   # the feed's subscribers + the file's flush

    def summary(self):
        return ('%d connection(s) piped, %d/%d frame(s) sent/recv, '
                '%d/%d byte(s) sent/recv, %d undecodable'
                % (self.conns, self.frames['c2d'], self.frames['d2c'],
                   self.bytes_piped['c2d'], self.bytes_piped['d2c'],
                   self.undecoded))

    def serve(self, host, port):
        """The accept ladder: bind, listen, pair every client with an
        upstream connection, pump both directions."""
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(64)
        self.listen_sock = srv
        self.listening(host, port)
        while not self.stopping:
            try:
                client, addr = srv.accept()
            except OSError:
                if self.stopping:
                    return
                logger.error('accept failed, retrying')
                time.sleep(0.1)
                continue
            try:
                upstream = socket.create_connection(
                    (self.upstream_host, self.upstream_port), timeout=self.modbus_timeout)
                upstream.settimeout(self.modbus_timeout or None)
            except OSError as e:
                logger.info('upstream %s:%d refused the pair (%s) — closing %s:%d',
                            self.upstream_host, self.upstream_port, e, *addr[:2])
                client.close()
                continue
            if self.client_timeout:
                client.settimeout(self.client_timeout)
            else:
                client.settimeout(self.modbus_timeout or None)
            with self.count_lock:
                self.conns += 1
                conn_id = self.conns
            self.access('client %s:%d paired with the device (conn %d)',
                        addr[0], addr[1], conn_id)
            threading.Thread(target=self._pair, daemon=True,
                             args=(client, upstream, addr, conn_id)).start()

    def _pair(self, client, upstream, addr, conn_id):
        """One connection pair: two pump threads, joined from here — when
        either leg ends, both die (the pair is one session)."""
        peer = '%s:%d' % addr[:2]
        device = '%s:%d' % (self.upstream_host, self.upstream_port)
        legs = [
            (client, upstream, 'c2d', peer),
            (upstream, client, 'd2c', device),
        ]
        done = threading.Event()

        def pump(sock_in, sock_out, flow, peer_name):
            tap = FrameTap(flow)
            try:
                while not self.stopping:
                    chunk = sock_in.recv(CHUNK)
                    if not chunk:
                        break
                    sock_out.sendall(chunk)
                    with self.count_lock:
                        self.bytes_piped[flow] += len(chunk)
                    for frame, parsed, note in tap.feed(chunk):
                        self._tap_record(flow, conn_id, peer_name, frame, parsed, note)
            except (OSError, ValueError):
                pass   # the transport died or the peer reset — the pair ends
            finally:
                for frame, parsed, note in tap.flush():
                    self._tap_record(flow, conn_id, peer_name, frame, parsed, note)
                done.set()
                try:
                    sock_out.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        threads = [threading.Thread(target=pump, daemon=True, args=leg) for leg in legs]
        with self.pumps_lock:
            self.pumps.extend((client, upstream))
        for t in threads:
            t.start()
        done.wait()   # either direction ends the pair
        self.stop_pair(client, upstream, addr, conn_id)

    def stop_pair(self, client, upstream, addr, conn_id):
        self.access('client %s:%d disconnected (conn %d)', addr[0], addr[1], conn_id)
        with self.pumps_lock:
            for s in (client, upstream):
                try:
                    self.pumps.remove(s)
                except ValueError:
                    pass
        for s in (client, upstream):
            try:
                s.close()
            except OSError:
                pass

    def _tap_record(self, flow, conn_id, peer, frame, parsed, note=None):
        """One reassembled frame (or one undecodable flush) from the tap:
        into the trace writer and the DEBUG log. The screen labels are
        the client's view — c2d is what the client SENT, d2c what it
        RECV'd (the trace's req/rsp say the same)."""
        label = 'sent' if flow == 'c2d' else 'recv'
        if parsed is None:
            self.undecoded += 1
            if self.writer:
                self.writer.record(flow, conn_id, peer, frame, note=note)
            logger.debug('conn %d %s %d byte(s) of unframed wire (%s)',
                         conn_id, label, len(frame), note or 'raw')
            return
        with self.count_lock:
            self.frames[flow] += 1
        direction = flow
        unit, pdu = parsed[1], parsed[2]
        dec = {'txn': parsed[0]}
        from .trace import decode_frame
        dec.update(decode_frame(pdu, unit, is_request=(flow == 'c2d')))
        if self.writer:
            self.writer.record(direction, conn_id, peer, frame, dec=dec)
        logger.debug('conn %d %s %s', conn_id, label,
                     describe_frame(unit, pdu, is_request=(flow == 'c2d')))
