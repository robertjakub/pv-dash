#!/usr/bin/env python3
"""The replay face (stdlib only): a Modbus TCP server that answers from a
captured trace — the hardware trace without the hardware. The shared
accept ladder (common/modbus/server.py serve_modbus) runs family-wide —
here in its uncapped posture (no connect ACL, no client caps — any peer
that can reach the port is served; only --client-timeout kicks the
silent) — and the frame dispatch matches the request against the trace
index (lib/trace.py TraceIndex — unit + function code + PDU bytes,
transaction ids aside) and answers the most recent recorded response
under the client's own transaction id. A miss speaks the --replay-miss
policy: exception 11 (gateway target device failed to respond — a miss
is loud in the client's error counters) or a zero-filled reply of the
right shape (the poll plan keeps running and shows its shape). Either
way the miss logs — that log IS the poll-planning debug. The recorded
device latency (rsp.ts - req.ts) waits before the answer when
--replay-speed says so."""
import logging
import struct
import threading
import time

from common.modbus.protocol import exception_frame, frame, PROTOCOL
from common.modbus.server import serve_modbus
from common.serve.connlimit import ConnGate, limits_words
from .statics import EXC_GATEWAY, EXC_ILLEGAL, EXC_VALUE, MAX_PDU
from .trace import READ_FCS, SINGLE_WRITE_FCS, MULTI_WRITE_FCS

logger = logging.getLogger('modbus-replay')


def synth_zero(unit, pdu):
    """The zero-mode reply for one request PDU, shaped like the device's
    would be: reads carry the byte count + zero data, single writes echo
    (fc + addr + value), multiple writes answer fc + addr + count.
    Returns (reply_pdu, exc_code): a shaped reply rides (pdu, None); a
    read whose count is past the protocol tree's caps answers (None,
    EXC_VALUE); a function the shapes do not cover answers (None,
    EXC_ILLEGAL)."""
    if not pdu:
        return None, EXC_ILLEGAL
    fc = pdu[0]
    if fc in READ_FCS and len(pdu) >= 5:
        addr, count = struct.unpack('>HH', pdu[1:5])
        cap = PROTOCOL['max_bits'] if fc in (1, 2) else PROTOCOL['max_count']
        if count > cap:
            return None, EXC_VALUE   # past the family's read cap: illegal data value
        if fc in (3, 4):
            return struct.pack('>BB', fc, count * 2) + b'\x00' * (count * 2), None
        return struct.pack('>BB', fc, (count + 7) // 8) + b'\x00' * ((count + 7) // 8), None
    if fc in SINGLE_WRITE_FCS and len(pdu) >= 5:
        return pdu[:5], None     # the echo: fc + addr + value
    if fc in MULTI_WRITE_FCS and len(pdu) >= 5:
        return pdu[:5], None     # the echo: fc + addr + count
    return None, EXC_ILLEGAL


class ReplayServer:
    """The replay face over a TraceIndex — the face protocol
    common/modbus/server.py serves: the gates, the counters, and the
    frame dispatch that answers from the trace."""

    def __init__(self, index, replay_speed=0.0, replay_miss='exception',
                 client_timeout=0.0):
        self.index = index
        self.replay_speed = replay_speed
        self.replay_miss = replay_miss
        self.conn_gate = ConnGate(0, 0)           # the ladder's name (the face protocol) — uncapped
        self.max_clients = 0                       # the ladder's cap slot — no cap by design
        self.client_timeout = client_timeout
        self.client_count = 0
        self.client_lock = threading.Lock()
        self.clients = {}
        self.stopping = False
        self.max_pdu = MAX_PDU
        self.log = logger
        self.sessions = 0
        self.answered = 0
        self.misses = 0          # split below
        self.missed_exceptions = 0
        self.missed_zero = 0

    def access(self, fmt, *args):
        logger.info(fmt, *args)   # the connects/disconnects always speak at INFO

    def allowed(self, ip):
        return True   # no connect ACL: any peer that can reach the port

    def listening(self, host, port):
        caps = ' '.join(limits_words(self.max_clients, self.client_timeout,
                                     self.conn_gate.max_per_ip))
        logger.info('replay server on %s:%d — trace %s (%s, miss %s, speed %g%s)',
                    host, port, self.index.path, self.index.summary(),
                    self.replay_miss, self.replay_speed,
                    (', ' + caps) if caps else '')

    def suite_key(self):
        return None   # no suite auth: the replay speaks plain Modbus, the trace's truth

    def on_session(self):
        with self.client_lock:
            self.sessions += 1

    def on_frame(self):
        pass          # the counters move in frame()

    def malformed(self, addr, err):
        logger.info('malformed frame from %s:%d (%s), closing', *addr[:2], err)

    def on_disconnect(self, key, entry):
        pass          # the ladder already logged the disconnect

    def stop(self):
        self.stopping = True
        if self.listen_sock:
            try:
                self.listen_sock.close()
            except OSError:
                pass

    def summary(self):
        return ('%d session(s), %d answered from the trace, %d miss(es) '
                '(%d exception, %d zero-shaped)'
                % (self.sessions, self.answered, self.misses,
                   self.missed_exceptions, self.missed_zero))

    def frame(self, client, txn, proto, unit, pdu, addr):
        """The dispatch: the trace's answer for this request, or the miss
        policy's — under the client's own transaction id either way."""
        hit = self.index.answer(unit, pdu)
        if hit is None:
            self._miss(client, txn, unit, pdu, addr)
            return
        rsp_pdu, latency = hit
        if self.replay_speed > 0 and latency > 0:
            time.sleep(latency / self.replay_speed)
        client.sendall(frame(txn, unit, rsp_pdu))
        with self.client_lock:
            self.answered += 1
        logger.debug('answered %s from the trace (recorded latency %gms)',
                     _req_words(unit, pdu), latency * 1000.0)

    def _miss(self, client, txn, unit, pdu, addr):
        """The unmatched request: the policy's answer, the log line that
        names it (the poll-planning debug lives here)."""
        with self.client_lock:
            self.misses += 1
        if self.replay_miss == 'zero':
            shaped, code = synth_zero(unit, pdu)
            with self.client_lock:
                self.missed_zero += 1
            if shaped is not None:
                client.sendall(frame(txn, unit, shaped))
                logger.info('replay miss for %s (%s:%d) — zero-shaped reply',
                            _req_words(unit, pdu), *addr[:2])
                return
            client.sendall(exception_frame(txn, 0, unit, pdu[0] if pdu else 0, code))
            logger.info('replay miss for %s (%s:%d) — no zero shape, exception %d',
                        _req_words(unit, pdu), *addr[:2], code)
            return
        with self.client_lock:
            self.missed_exceptions += 1
        fc = pdu[0] if pdu else 0
        client.sendall(exception_frame(txn, 0, unit, fc, EXC_GATEWAY))
        logger.info('replay miss for %s (%s:%d) — exception %d',
                    _req_words(unit, pdu), *addr[:2], EXC_GATEWAY)


def _req_words(unit, pdu):
    """The request's words for the log/summary lines — the trace module's
    describe, exception frames included."""
    from .trace import describe_frame
    return describe_frame(unit, pdu)
