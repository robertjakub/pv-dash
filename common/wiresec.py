#!/usr/bin/env python3
"""The control wire's integrity layer, shared by the family's control servers
and their ctl/cli clients (the verifiable-commands item in docs/TODO.md):
when a control token is configured, every command and every reply carries a
**full sha256 HMAC** (64 hex characters, the audit trail's chained h= is the
short form) keyed by the token —

  request: {"cmd": "<command>", "mac": <hmac-sha256(token, cmd)>}
  reply:   {"status": "...", "text": "<reply text>", "mac": <hmac-sha256(token, "<status> <text>">)}

so a token-holding client verifies nothing was injected or altered in
flight (the token auth proves who is speaking once; the mac proves it for
every frame after that — the command the server logs is the command the
client sent). Over TCP with a token the mac is mandatory: unsigned command
frames are refused. Over the unix socket it is verify-if-present — a
peer-cred trusted peer speaks without holding the token (SO_PEERCRED is the
boundary there), and a tamper attempt still fails the check. Without a
token there is nothing to key: the wire stays unsigned (the filesystem
permissions are the boundary). Stdlib only."""
import hashlib
import hmac


def frame_mac(token, payload):
    """The full sha256 HMAC (64 hex characters) of one frame's payload,
    keyed by the control token. payload = the command string, or the
    reply's internal '<status> <text>' form."""
    return hmac.new(token.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()


def sign_request(token, cmd):
    """The wire form of one command: {"cmd": ..., "mac": ...}."""
    return {'cmd': cmd, 'mac': frame_mac(token, cmd)}


def sign_reply(token, reply):
    """Sign the reply in the server's internal '<status> <text>' form; the
    mac rides the JSON frame next to its status/text fields."""
    return frame_mac(token, reply)


def verify_request_mac(token, cmd, mac):
    """True when the command frame's mac verifies (a missing mac is the
    caller's policy question, a bad one is always fatal)."""
    if not isinstance(mac, str):
        return False
    return hmac.compare_digest(mac, frame_mac(token, cmd))


def verify_reply(token, status, text, mac):
    """True when the reply frame's mac verifies: the mac covers the reply's
    '<status> <text>' form — both fields, not just the body."""
    if not isinstance(mac, str):
        return False
    return hmac.compare_digest(mac, frame_mac(token, '%s %s' % (status, text)))


def proof_tag(obj):
    """The audit-trail fragment naming the frame's mac: ' wire=h<12 hex>' —
    the command the server logs cryptographically matches the command the
    client sent; '' when the frame was unsigned."""
    mac = obj.get('mac') if isinstance(obj, dict) else None
    return ' wire=h%s' % mac[:12] if isinstance(mac, str) else ''
