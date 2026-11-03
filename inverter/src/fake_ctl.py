#!/usr/bin/env python3
"""Small client for the fake inverter's control server: sends one command (or
a batch from stdin) over TCP or a unix socket (--control-port, env FAKE_CTL)
and prints the replies.

  python3 fake_ctl.py --control-port 15599 set pv 2500
  python3 fake_ctl.py --control-port 15599 status
  printf 'set pv 2500\\nset soc 30\\nstatus\\n' | python3 fake_ctl.py --control-port 15599

Commands (see the server's help): set <pv|load|batt|soc|cloud|time|scenario|
chaos|seed|battery|strict|static|max-kwp|battery-kwh|log-level> <value>,
show <setting|settings>, status, reset, shutdown, quit.

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import argparse
import socket
import sys

from lib.paths import resolve_control_target



def read_reply(sock, first, rest):
    """Assemble a multi-line reply (show registers) up to the '.' terminator."""
    lines = [first] + rest.split('\n')
    while True:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[-1].strip() == '.':
            lines.pop()
            break
        chunk = sock.recv(65536)
        if not chunk:
            break
        lines += chunk.decode('utf-8', 'replace').split('\n')
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description='Send commands to the fake inverter control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/fake-inverter-5502.socket; env FAKE_CTL when unset) — same flag as the fake itself')
    p.add_argument('command', nargs='*', help='control command, e.g. set pv 2500, set scenario noon, show settings, status, reset, shutdown')
    p.add_argument('--timeout', type=float, default=5.0, help='socket timeout in seconds (default %(default)s)')
    args = p.parse_args()

    commands = [' '.join(args.command)] if args.command else None
    if not commands:
        if sys.stdin.isatty():
            p.error('no command given (pass it as arguments or pipe commands on stdin)')
        commands = [line.strip() for line in sys.stdin if line.strip()]
        if not commands:
            p.error('no commands on stdin')

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
    try:
        for cmd in commands:
            s.sendall((cmd + '\n').encode())
            buf = b''
            while not buf.endswith(b'\n'):
                chunk = s.recv(4096)
                if not chunk:
                    break   # server said goodbye and closed (e.g. after shutdown)
                buf += chunk
            first = buf.decode('utf-8', 'replace').split('\n', 1)[0].strip()
            if not first.startswith('ok registers'):
                print(buf.decode('utf-8', 'replace').strip())
                continue
            rest = buf.decode('utf-8', 'replace').split('\n', 1)[1] if b'\n' in buf else ''
            print(read_reply(s, first, rest))
    except OSError as e:
        print('control error: %s' % e, file=sys.stderr)
        raise SystemExit(1)
    finally:
        s.close()


if __name__ == '__main__':
    main()
