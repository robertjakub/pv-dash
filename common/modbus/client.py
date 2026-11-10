"""The shared Modbus TCP client ladders (stdlib only): the connect +
auth-handshake and reply-validation sequences both client legs speak —
the scraper's ModbusTCP polls through them, the cache's Upstream wraps
them behind its own serialized connection. The error texts are pinned by
the regtests; change them with the suites in hand. The per-tool limits
come from each tool's lib/defaults.json."""
import socket

from .protocol import (DeviceError, ModbusError, auth_handshake_client,
                       recv_exact, waveshare_handshake_client)


class ClientBase:
    """The client-leg plumbing both Modbus TCP clients share: the endpoint
    fields, the close, the recv wrapper (OSError -> ModbusError) and the
    reconnect-on-connect (the auth handshake armed). The subclass keeps
    its own extras (the scraper's offset/apply, the cache's counters) and
    its read ladders."""

    def __init__(self, host, port, unit, timeout, auth=None, auth_key=None):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.auth = auth          # None = no auth | 'suite' = the crypt handshake
                                  # | 'waveshare' = the Waveshare gateway connection password
        self.auth_key = auth_key  # the shared key the handshake proves
        self.sock = None
        self.txn = 0

    def after_connect(self):
        """The subclass's post-connect hook (the cache's session counters)."""

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _connect(self):
        self.close()
        self.sock = open_socket(self.host, self.port, self.timeout, self.auth, self.auth_key)
        self.after_connect()

    def _recv_exact(self, n):
        try:
            return recv_exact(self.sock, n)
        except OSError as e:
            raise ModbusError(str(e))


def open_socket(host, port, timeout, auth=None, auth_key=None):
    """One TCP connect, then the armed auth handshake: 'suite' proves the
    shared key with the crypt handshake, 'waveshare' sends the gateway
    password raw. A failed handshake fails the connect like any other."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    if auth == 'suite' and auth_key:
        auth_handshake_client(sock, auth_key)
    elif auth == 'waveshare' and auth_key:
        waveshare_handshake_client(sock, auth_key)
    return sock


def check_reply(txn, proto, unit, body, want_txn, want_unit, fc):
    """The reply validation ladder both client legs run, in order: the
    transaction id, the protocol id, the unit id, the device's exception
    (DeviceError carries its code), the function byte, the body's shape.
    Raises ModbusError; the MBAP head's own bounds and the byte-count
    check are the caller's (check_head, and a text that names the space)."""
    if txn != want_txn:
        raise ModbusError('transaction id mismatch')
    if proto != 0:
        raise ModbusError('unexpected protocol id %d' % proto)
    if unit != want_unit:
        raise ModbusError('reply from unit id %d, expected %d' % (unit, want_unit))
    func = body[0]
    if func == fc + 0x80:
        code = body[1] if len(body) > 1 else -1
        raise DeviceError('FC%d modbus exception, code %d' % (fc, code), code)
    if func != fc:
        raise ModbusError('unexpected function byte 0x%02x' % func)
    if len(body) < 2:
        raise ModbusError('short response: function byte only')


def check_data_bytes(got, want, noun='data'):
    """The reply's data-byte count against the expected one — 'data' for
    the bit replies, 'register' for the cache's word reads."""
    if got != want:
        raise ModbusError('expected %d %s bytes, got %d' % (want, noun, got))
