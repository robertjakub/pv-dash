#!/usr/bin/env python3
"""Small client for modbus-cache's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env MODBUS_CACHE_CTL / CACHE_CTL) and prints the replies. TCP servers with
--control-token require the token first ({"cmd": "auth", "token": ...}) —
pass it with --control-token or the MODBUS_CACHE_CONTROL_TOKEN environment
variable.

  python3 cache_ctl.py --control-port 15509 show status
  python3 cache_ctl.py --control-port 15509 clear cache
  printf 'show cache\\nclear cache\\n' | python3 cache_ctl.py --control-port 15509

Commands (see the server's help): show <status|connections|cache|version>,
clear cache, restart, shutdown, quit.

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
from lib.config import resolve_control_target


def main():
    p = argparse.ArgumentParser(description='Send commands to the modbus-cache control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/modbus-cache-15502.socket; env MODBUS_CACHE_CTL or CACHE_CTL when unset) — same flag as the proxy itself')
    p.add_argument('command', nargs='*', help='control command, e.g. inspect, show status, show cache, clear cache, restart, shutdown')
    p.add_argument('--timeout', type=float, default=5.0, help='socket timeout in seconds (default %(default)s)')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env MODBUS_CACHE_CONTROL_TOKEN)')
    p.add_argument('--control-token-file', default=None, help='the token from a file (the first line); not for use with --control-token (env MODBUS_CACHE_CONTROL_TOKEN_FILE)')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path or - for stdout; default: the XDG state home")
    p.add_argument('--audit-max-mb', type=float, default=10.0, help='rotate the audit log at this size, 0 = off')
    p.add_argument('--audit-files', type=int, default=3, help='rotated audit backups to keep (default %(default)s)')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    args = p.parse_args()

    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'CTL', app='modbus-cache',
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
        token = load_token_file(args.control_token_file, 'control-token-file')
    else:
        token = args.control_token or os.environ.get('MODBUS_CACHE_CONTROL_TOKEN')
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
