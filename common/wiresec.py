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
permissions are the boundary).

A daemon may carry a **second token, the read-only ops role**
(ROLE_ADMIN / ROLE_OPS): the admin key keeps every verb, the ops key
authenticates into its policy's verbs only — by default the show/clear
verbs (ROLE_POLICIES, per daemon configurable with --control-ops-verbs) —
no set/unset, no request dump/restore or reload, no restart, no shutdown
(the ops shift can look, flush a cache, and leave; the admin key steers).
The gate is the command's head verb against the role's policy
(role_allows), the session's replies are mac'd with the key it
authenticated with, and the audit trail names the role on every COMMAND
entry (role_tag) — both keys audited, the denials included. Stdlib only."""
import hashlib
import hmac

# The control roles — the RBAC table: a role is a policy over the wire
# verbs. ROLE_ADMIN is the full-access key (None = every verb the server's
# grammar speaks); ROLE_OPS is the read-only shift, its policy the verb set
# below — configurable per daemon (--control-ops-verbs, a comma list
# validated against the tool's grammar at startup). The session verbs
# (help/?/ping/quit) are the housekeeping every role speaks: they touch
# nothing. A peer-cred trusted peer (SO_PEERCRED — the kernel vouches)
# counts as ROLE_ADMIN.
ROLE_ADMIN = 'admin'
ROLE_OPS = 'ops'
OPS_VERBS = frozenset(('show', 'clear'))
SESSION_VERBS = frozenset(('help', '?', 'ping', 'quit'))
ROLE_POLICIES = {
    ROLE_ADMIN: None,            # None = the full verb set
    ROLE_OPS: OPS_VERBS,         # the read-only shift's default policy
}


def command_verb(cmd):
    """The head verb of one command line (lowercased), '' when empty —
    the thing the role gate decides on. The `request` namespace is
    grammar, not authority: the verb is the first word PAST a leading
    `request` (`request clear cache` decides on `clear`, `request reload`
    on `reload`) — the ops policy keeps its per-action granularity."""
    parts = cmd.strip().split()
    if parts and parts[0].lower() == 'request':
        parts = parts[1:]
    return parts[0].lower() if parts else ''


def role_allows(role, cmd, ops_verbs=None):
    """True when the role may run this command: admin runs everything, ops
    its policy (the daemon's configured verb set, or the shared default) plus
    the session housekeeping. `None` = the session never authenticated
    because no token is configured (the filesystem/peer-cred boundary
    governs) — everything is allowed. An unknown role is denied everything
    but the housekeeping (fail closed)."""
    verb = command_verb(cmd)
    if verb in SESSION_VERBS:
        return True
    if role is None:
        return True
    policy = ROLE_POLICIES.get(role, frozenset())
    if policy is None:
        return True
    if role == ROLE_OPS and ops_verbs:
        policy = ops_verbs
    return verb in policy


def role_tag(role):
    """The audit-trail fragment naming the session's role: ' role=ops' —
    '' when the session spoke without a role (no token configured)."""
    return ' role=%s' % role if role else ''


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
