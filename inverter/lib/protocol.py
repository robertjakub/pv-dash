#!/usr/bin/env python3
"""Wire helpers shared by the fake's servers."""


def recv_exact(sock, n):
    """Read exactly n bytes or raise ConnectionError."""
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('client closed connection')
        buf += chunk
    return buf
