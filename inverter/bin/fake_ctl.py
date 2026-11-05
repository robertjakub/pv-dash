#!/usr/bin/env python3
"""Small client for the fake inverter's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env FAKE_CTL) and prints the replies. TCP servers with --control-token
require the token first ({"cmd": "auth", "token": ...}) — pass it with
--control-token or the FAKE_CONTROL_TOKEN environment variable.

  python3 fake_ctl.py --control-port 15599 set pv 2500
  python3 fake_ctl.py --control-port 15599 status
  printf 'set pv 2500\\nset soc 30\\nstatus\\n' | python3 fake_ctl.py --control-port 15599

Commands (see the server's help): set <pv|load|batt|soc|cloud|time|scenario|
chaos|seed|battery|strict|static|max-kwp|battery-kwh|max-clients|
client-timeout|log-level> <value>, show <setting|status|connections|settings>,
status, reset, shutdown, quit.

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
from lib.paths import resolve_control_target
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_TIMEOUT_S






def main():
    p = argparse.ArgumentParser(description='Send commands to the fake inverter control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/fake-inverter-5502.socket; env FAKE_CTL when unset) — same flag as the fake itself')
    p.add_argument('command', nargs='*', help='control command, e.g. set pv 2500, set scenario noon, show settings, status, reset, shutdown')
    p.add_argument('--timeout', type=float, default=CLI_TIMEOUT_S, help='socket timeout in seconds (default %(default)s)')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env FAKE_CONTROL_TOKEN)')
    p.add_argument('--control-token-file', default=None, help='the token from a file (the first line; must be owner-only 0600); not for use with --control-token (env FAKE_CONTROL_TOKEN_FILE)')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path or - for stdout; default: the XDG state home")
    p.add_argument('--audit-max-mb', type=float, default=AUDIT_MAX_MB, help='rotate the audit log at this size, 0 = off')
    p.add_argument('--audit-files', type=int, default=AUDIT_FILES, help='rotated audit backups to keep (default %(default)s)')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    args = p.parse_args()

    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'CTL', app='fake-inverter',
                                                    max_mb=args.audit_max_mb, files=args.audit_files)

    commands = [' '.join(args.command)] if args.command else None
    if not commands:
        if sys.stdin.isatty():
            p.error('no command given (pass it as arguments or pipe commands on stdin)')
        commands = [line.strip() for line in sys.stdin if line.strip()]
        if not commands:
            p.error('no commands on stdin')

    if args.control_token and args.control_token_file:
        p.error('--control-token and --control-token-file are mutually exclusive')
    if args.control_token_file:
        token = load_token_file(args.control_token_file)
    else:
        token = args.control_token or os.environ.get('FAKE_CONTROL_TOKEN')
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

    def exchange(sock, cmd, **extra):
        """One JSON request, one JSON reply; returns (status, text)."""
        obj = {'cmd': cmd}
        obj.update(extra)
        sock.sendall((json.dumps(obj, ensure_ascii=False) + '\n').encode())
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = sock.recv(65536)
            if not chunk:
                return 'err', 'connection closed'
            buf += chunk
        try:
            obj = json.loads(buf.decode('utf-8', 'replace'))
            return obj.get('status', 'err'), str(obj.get('text', ''))
        except ValueError:
            return 'err', 'malformed reply'

    try:
        if token and not isinstance(addr, str):
            st, tx = exchange(s, 'auth', token=token)
            if st != 'ok':
                print('control auth failed: %s' % tx, file=sys.stderr)
                raise SystemExit(1)
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
