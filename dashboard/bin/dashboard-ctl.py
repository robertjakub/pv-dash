#!/usr/bin/env python3
"""Small client for the dashboard's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env CTL) and prints the replies. TCP servers with --control-token
require the token first ({"cmd": "auth", "token": ...}) — pass it with
--control-token or the CONTROL_TOKEN environment variable. With a
token configured the wire is HMAC-signed (the full sha256 of each frame,
common/wiresec.py): the client signs every command and verifies every
reply.

  python3 dashboard-ctl.py --control-port 15598 show status
  python3 dashboard-ctl.py --control-port 15598 request reload
  printf 'set battery on\\nshow status\\n' | python3 dashboard-ctl.py --control-port 15598

Commands (see the server's help): show <status|connections|version>,
set/unset, inspect, request reload, shutdown, quit.

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

import argparse
import getpass
import json
import os
import socket
import sys

from common.audit import AuditLog
from common.config import load_token_file
from common.wiresec import sign_request, verify_reply
from lib.config import resolve_control_target
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_TIMEOUT_S


def main():
    p = argparse.ArgumentParser(description='Send commands to the dashboard control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/dashboard-8080.socket; env CTL when unset) — same flag as the server itself')
    p.add_argument('command', nargs='*', help='control command, e.g. inspect, show status, set battery on, request reload, shutdown')
    p.add_argument('--timeout', type=float, default=CLI_TIMEOUT_S, help='socket timeout in seconds (default %(default)s)')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env CONTROL_TOKEN)')
    p.add_argument('--control-token-file', default=None, help='the token from a file (the first line; must be owner-only 0600); not for use with --control-token (env CONTROL_TOKEN_FILE)')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path or - for stdout; default: the XDG state home")
    p.add_argument('--audit-max-mb', type=float, default=AUDIT_MAX_MB, help='rotate the audit log at this size, 0 = off')
    p.add_argument('--audit-files', type=int, default=AUDIT_FILES, help='rotated audit backups to keep (default %(default)s)')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    p.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (dashboard-ctl --man | man -l -)')
    args = p.parse_args()
    if args.man:
        from lib.man import ctl_page
        sys.stdout.write(ctl_page(p))
        raise SystemExit(0)

    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'CTL', app='dashboard',
                                                    max_mb=args.audit_max_mb, files=args.audit_files)

    commands = [' '.join(args.command)] if args.command else None
    if not commands:
        if sys.stdin.isatty():
            p.error('no command given (pass it as arguments or pipe commands on stdin)')
        # the config scripts pipe through: comments (#) and blank lines stay comments
        commands = [line.strip() for line in sys.stdin
                    if line.strip() and not line.strip().startswith('#')]
        if not commands:
            p.error('no commands on stdin')

    token_file = args.control_token_file or os.environ.get('CONTROL_TOKEN_FILE')
    token = args.control_token or os.environ.get('CONTROL_TOKEN')
    if token and token_file:
        p.error('--control-token and --control-token-file are mutually exclusive')
    if token_file:
        token = load_token_file(token_file, 'control-token-file')
    target = resolve_control_target(args.control_port)
    if target.isdigit():
        if not 1 <= int(target) <= 65535:
            p.error('--control-port port out of range: %d' % int(target))
        addr, label = ('127.0.0.1', int(target)), '127.0.0.1:%s' % target
    else:
        addr, label = target, 'unix:%s' % target
    try:
        s = socket.socket(socket.AF_UNIX if isinstance(addr, str) else socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(args.timeout)
        s.connect(addr)
    except OSError as e:
        print('cannot reach control server at %s: %s' % (label, e), file=sys.stderr)
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
        sock.sendall((json.dumps(obj, ensure_ascii=False) + '\n').encode())
        buf = b''
        while b'\n' not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                return 'err', 'connection closed'
            buf += chunk
        # the first complete frame only: the daemon-exit bye can ride the
        # same segment as a shutdown reply (announce_exit) — it is not
        # part of the reply
        line, buf = buf.split(b'\n', 1)
        try:
            obj = json.loads(line.decode('utf-8', 'replace'))
        except ValueError:
            return 'err', 'malformed reply'
        st, tx = obj.get('status', 'err'), str(obj.get('text', ''))
        mac = obj.get('mac')
        if token and mac is not None and not verify_reply(token, st, tx, mac):
            print('the reply mac does not verify (tampered or corrupted frame)', file=sys.stderr)
            raise SystemExit(1)
        if token and mac is None and required_auth:
            print('the server did not sign the reply', file=sys.stderr)
            raise SystemExit(1)
        return st, tx

    try:
        if token and not isinstance(addr, str):
            st, tx = exchange(s, 'auth', token=token)
            if st != 'ok':
                print('control auth failed: %s' % tx, file=sys.stderr)
                raise SystemExit(1)
            required_auth = True   # the handshake holds: every reply from here is signed and verified
        for cmd in commands:
            st, tx = exchange(s, cmd)
            if st == 'bye' and tx.startswith('daemon-exit'):
                print('%% %s — done' % tx.replace('daemon-exit', 'daemon exit', 1))
                break
            print(('%s %s' % (st, tx)).rstrip())
    except OSError as e:
        print('control error: %s' % e, file=sys.stderr)
        raise SystemExit(1)
    finally:
        if audit:
            audit.event('DISCONNECT', 'target=%s' % label)
            audit.close()
        s.close()


if __name__ == '__main__':
    main()
