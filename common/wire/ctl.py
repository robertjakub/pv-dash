#!/usr/bin/env python3
"""The ctl client, one implementation for the family: one command (or a
batch from stdin) over TCP or a unix socket, the replies printed. The
per-tool bins keep only their docstring, the lib imports and the constants
this ladder takes — the daemon name, the default socket, the command
examples, the man page. Stdlib only."""
import argparse
import getpass
import json
import os
import socket
import sys

from common.runtime.audit import AUDIT_FORWARD_FORMATS, AuditLog
from common.settings.config import parse_secret, resolve_target
from common.render.texts import T
from common.wire.cli import translate
from common.wire.wiresec import sign_request, verify_reply


def run_ctl(daemon, bin_name, app, self_note, command_help,
            ctl_socket, timeout_s, audit_max_mb, audit_files, ctl_page,
            max_line_bytes, spellings=None, audit_tag='CTL'):
    """The whole ctl ladder: the parser (the tool's name, socket, examples),
    the batch stdin strip (comments and blanks stay comments), the token
    parse, the connect, the CONNECT audit, the signed exchange closure, the
    auth handshake and the command loop (the daemon-exit bye short-circuits
    it). `ctl_socket` is the tool's default control socket path — the
    --control-port flag and the CTL environment override it. `spellings`
    is the tool's console-spelling map (lib.options SETTING_SPELLINGS):
    the console's live/alias knob spellings translate to the flat registry
    names here exactly as the interactive cli's — a config script's
    live-word lines pipe through the ctl unchanged (the bundled confs'
    claim). `audit_tag` is the trail's tool tag (shared/tags.json) — the
    client writes it with the cli writer role (tag=cli)."""

    p = argparse.ArgumentParser(description='Send commands to the %s control server (TCP or unix socket).' % daemon)
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (env CTL when unset) — same flag as %s' % self_note)
    p.add_argument('command', nargs='*', help='control command, %s' % command_help)
    p.add_argument('--timeout', type=float, default=timeout_s, help='socket timeout in seconds')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env CONTROL_TOKEN); a file:<path> value reads the first line of an owner-only 0600 file')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path, - for stdout, or none for no local file (the forward carries the trail); the XDG state home when unset")
    p.add_argument('--audit-forward', default='none', metavar='TARGET',
                   help='also forward every audit line: none, syslog, syslog:/path, udp://host[:port] or tcp://host[:port] (the off-box copy, docs/SECURITY.md)')
    p.add_argument('--audit-forward-format', default='rfc5424', choices=AUDIT_FORWARD_FORMATS,
                   help="the remote forward's envelope: rfc5424 (the default) or cef — the local syslog forms keep the verbatim send")
    p.add_argument('--audit-max-mb', type=float, default=audit_max_mb, help='rotate the audit log at this size, 0 = off')
    p.add_argument('--audit-files', type=int, default=audit_files, help='rotated audit backups to keep')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    p.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (%s --man | man -l -)' % bin_name)
    args = p.parse_args()
    if args.man:
        sys.stdout.write(ctl_page(p))
        raise SystemExit(0)

    commands = [' '.join(args.command)] if args.command else None
    if not commands:
        if sys.stdin.isatty():
            p.error('no command given (pass it as arguments or pipe commands on stdin)')
        # the config scripts pipe through: comments (#) and blank lines stay comments
        commands = [line.strip() for line in sys.stdin
                    if line.strip() and not line.strip().startswith('#')]
        if not commands:
            p.error('no commands on stdin')

    token = args.control_token or os.environ.get('CONTROL_TOKEN')
    token = parse_secret(token, 'control-token')   # the inline form may be file:<path> — the same loader
    target = resolve_target(args.control_port, ctl_socket)
    if target.isdigit():
        if not 1 <= int(target) <= 65535:
            p.error('--control-port port out of range: %d' % int(target))
        addr, label = ('127.0.0.1', int(target)), '127.0.0.1:%s' % target
    else:
        addr, label = target, 'unix:%s' % target
    try:
        audit = None if args.no_audit_log else AuditLog(args.audit_log, audit_tag, app=app, writer='cli',
                                                        max_mb=args.audit_max_mb, files=args.audit_files,
                                                        forward=args.audit_forward,
                                                        forward_format=args.audit_forward_format,
                                                        instance=target if target.isdigit() else 'unix')
    except ValueError as e:
        p.error(str(e))

    try:
        s = socket.socket(socket.AF_UNIX if isinstance(addr, str) else socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(args.timeout)
        s.connect(addr)
    except OSError as e:
        print(T('shared.cannot_reach') % (label, e), file=sys.stderr)
        raise SystemExit(1)
    if audit:
        audit.event('CONNECT', 'target=%s user=%s' % (label, getpass.getuser()))
    required_auth = False   # set once the token handshake happened (the reply mac is then mandatory)

    def exchange(sock, cmd, **extra):
        """One JSON request (token-signed when we hold the token), one JSON
        reply (mac-verified the same way); returns (status, text). A bad or
        — once the token handshake happened — missing reply mac is fatal:
        the wire was tampered with or the server predates the signing."""
        obj = sign_request(token, cmd) if token else {'cmd': cmd}
        obj.update(extra)
        wire = (json.dumps(obj, ensure_ascii=False) + '\n').encode()
        if len(wire) > max_line_bytes:
            # the client-side half of the daemon's line-cap guard: a clean
            # local verdict instead of the daemon dropping the connection
            return 'fail', T('ctl.command_too_long') % max_line_bytes
        sock.sendall(wire)
        buf = b''
        while b'\n' not in buf:
            if len(buf) > max_line_bytes:
                return 'fail', T('ctl.reply_too_long') % max_line_bytes
            chunk = sock.recv(65536)
            if not chunk:
                return 'fail', T('ctl.connection_closed')
            buf += chunk
        # the first complete frame only: the daemon-exit bye can ride the
        # same segment as a shutdown reply (announce_exit) — it is not
        # part of the reply
        line, buf = buf.split(b'\n', 1)
        try:
            obj = json.loads(line.decode('utf-8', 'replace'))
        except ValueError:
            return 'fail', T('ctl.malformed_reply')
        st, tx = obj.get('status', 'fail'), str(obj.get('text', ''))
        mac = obj.get('mac')
        if token and mac is not None and not verify_reply(token, st, tx, mac):
            print(T('ctl.mac_verify_failed'), file=sys.stderr)
            raise SystemExit(1)
        if token and mac is None and required_auth:
            print(T('shared.mac_missing'), file=sys.stderr)
            raise SystemExit(1)
        return st, tx

    try:
        if token and not isinstance(addr, str):
            st, tx = exchange(s, 'auth', token=token)
            if st != 'ok':
                print(T('shared.auth_failed') % tx, file=sys.stderr)
                raise SystemExit(1)
            required_auth = True   # the handshake holds: every reply from here is signed and verified
        for cmd in commands:
            st, tx = exchange(s, translate(cmd, spellings))
            if st == 'bye' and tx.startswith('daemon-exit'):
                print(T('ctl.daemon_exit_done') % tx.replace('daemon-exit', 'daemon exit', 1))
                break
            if st == 'fail':
                print(T('shared.error_face') % tx)
            elif st == 'note':
                print(T('shared.plain_face') % tx)   # a note, not a verdict: the startup-only set landed as the configured value
            else:
                print(('%s %s' % (st, tx)).rstrip())
    except OSError as e:
        print(T('ctl.control_error') % e, file=sys.stderr)
        raise SystemExit(1)
    finally:
        if audit:
            audit.event('DISCONNECT', 'target=%s' % label)
            audit.close()
        s.close()
