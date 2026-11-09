#!/usr/bin/env python3
"""Peer-credential lookup for the suite's unix control sockets (stdlib only):
the kernel-vouched peer (SO_PEERCRED on Linux, LOCAL_PEERCRED on the
BSDs/macOS) is authenticated without a token — a local systemd unit speaks
without the secret."""
import socket
import struct


def peer_uid(sock):
    """The peer's uid over a unix socket: SO_PEERCRED (Linux) or the
    LOCAL_PEERCRED xucred (macOS/BSD); None when neither answers."""
    try:
        return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    except (AttributeError, OSError, struct.error):
        pass
    try:
        data = sock.getsockopt(getattr(socket, 'SOL_LOCAL', 0), getattr(socket, 'LOCAL_PEERCRED', 0x001), 12)
        version, uid = struct.unpack('Ii', data[:8])
        return uid if version == 0 else None
    except (AttributeError, OSError, struct.error):
        return None


def parse_trust_uids(text, label='control-trust-uids'):
    """''/None -> None (the defaults only: root + the daemon's own uid);
    '0,65534' -> frozenset({0, 65534}) — extra peer uids the unix control
    socket trusts without the token."""
    if text is None or str(text).strip() in ('', 'any', 'none'):
        return None
    uids = set()
    for part in str(text).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            uid = int(part)
        except ValueError:
            raise SystemExit('%s: entries must be uids, got %r' % (label, part))
        if not 0 <= uid <= 0xFFFFFFFF:
            raise SystemExit('%s: uid %d out of range' % (label, uid))
        uids.add(uid)
    return frozenset(uids)
