#!/usr/bin/env python3
"""Cisco-style interactive CLI for the fake inverter's control server.

A session front-end on top of the line-protocol control socket: prompt with
the connected port, TAB completion and `?` in every position (with the short
descriptions from the shared command registry), `set` commands print only
the confirmation (never the status tail), `show <setting>` prints the bare
value, `show settings` one setting per line, and `shutdown` asks before it
stops the fake.

  python3 fake_cli.py --control-port 15599
  FAKE_CTL=15599 python3 fake_cli.py

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import argparse
import os
import re
import socket
import sys

try:
    import readline
except ImportError:
    readline = None

from lib.paths import resolve_control_target
from lib.settings import COMMAND_HELP, SETTING_BY_NAME, SETTING_NAMES, describe_value

HELP = """commands (TAB completes, ? lists the options + descriptions in any position):
""" + ''.join('  %-10s %s\n' % (n, d) for n, d in
              (('set', 'configure a setting (set soc auto, set scenario noon)'),
               ('unset', 'restore a setting to its configured value (unset pv, unset seed)'),
               ('show', 'print the bare value of a setting, or all of them'),
               ('status', 'effective register state + pins'),
               ('reset', 'clear all pins + the write overlay'),
               ('shutdown', 'stop the fake inverter (asks to confirm)'),
               ('quit', 'close the session'),
               ('?', 'this help'))) + '  help <setting>  the setting\'s description'


def prompt_for(target, is_unix):
    """fake-inverter:<port> > — the TCP control port, or the port embedded in
    the socket name (fake-inverter-5502.socket), else the socket name."""
    if is_unix:
        base = os.path.basename(target)
        if base.endswith('.socket'):
            base = base[:-len('.socket')]
        m = re.search(r'(\d+)$', base)
        return 'fake-inverter:%s > ' % (m.group(1) if m else base)
    return 'fake-inverter:%s > ' % target


def candidates(buf):
    """Valid next words for the buffer being completed or questioned:
    (matches, hint about the following word, describer of each word)."""
    end_space = buf.endswith(' ')
    parts = buf.split()
    text = '' if end_space else (parts[-1] if parts else '')
    done = parts if end_space else parts[:-1]
    head = done[0].lower() if done else ''
    if not done:
        pool, hint, desc = tuple(COMMAND_HELP), None, describe_word
    elif head == 'unset' and len(done) == 1:
        pool, hint, desc = SETTING_NAMES, None, describe_word
    elif head == 'set' and len(done) == 1:
        pool, hint, desc = SETTING_NAMES, None, describe_word
    elif head == 'show' and len(done) == 1:
        pool, hint, desc = SETTING_NAMES + ('settings',), None, describe_word
    elif head in ('set', 'unset') and len(done) == 2:
        s = SETTING_BY_NAME.get(done[1].lower())
        pool, hint = (s.values if s else []), (s.hint if s else None)
        desc = (lambda w, _n=done[1].lower(): describe_value(_n, w))
    else:
        return [], None, None
    return [w for w in pool if w.startswith(text.lower())], hint, desc


def describe_word(w):
    """The short description from the shared registry, if there is one."""
    if w in SETTING_BY_NAME:
        return SETTING_BY_NAME[w].help
    if w in COMMAND_HELP:
        return COMMAND_HELP[w]
    if w == 'settings':
        return 'every setting, one per line'
    return None


_last_listed = None   # the completer is called several times per attempt;
                      # list each distinct buffer only once
_prompt = 'fake-inverter > '   # the session's prompt; the completer re-echoes it after the list


def complete(text, state):
    """TAB completer, Cisco-style: extend the word silently while the common
    prefix grows (a single-match return inserts it — verified libedit adds no
    space and lists nothing); once the prefix is exhausted, print the options
    OURSELVES — one candidate per line with the short descriptions (editline
    column-packs or skips its own listings) — and yield no match so the
    editor just redraws the line."""
    global _last_listed
    matches, hint, desc = candidates(readline.get_line_buffer())
    if state >= len(matches):
        return None
    if len(matches) > 1:
        common = os.path.commonprefix(matches)
        if len(common) > len(text):
            return common if state == 0 else None
        buf = readline.get_line_buffer()
        if state == 0 and _last_listed != buf:
            _last_listed = buf
            rows = []
            for w in matches:
                d = desc(w) if desc else None
                rows.append('  %-12s %s' % (w, d) if d else '  %s' % w)
            if hint:
                rows.append('  ' + hint)
            # the list, a blank line, then the prompt + line again — editline
            # does NOT redraw after the completer, so we do it ourselves
            print('\n' + '\n'.join(rows) + '\n')
            sys.stdout.write(_prompt + buf)
            sys.stdout.flush()
        return None
    return matches[0]


def print_options(buf):
    """Cisco `?`: one candidate per line, with the short description."""
    matches, hint, desc = candidates(buf)
    if not matches:
        print('% Invalid input.')
        return
    for w in matches:
        d = desc(w) if desc else None
        print('  %-12s %s' % (w, d) if d else '  %s' % w)
    if hint:
        print('  ' + hint)


def main():
    p = argparse.ArgumentParser(description='Cisco-style CLI for the fake inverter control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/fake-inverter-5502.socket; env FAKE_CTL when unset) — same flag as the fake itself')
    p.add_argument('--timeout', type=float, default=5.0, help='socket timeout in seconds (default %(default)s)')
    args = p.parse_args()

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
    if readline and sys.stdin.isatty():
        readline.set_completer(complete)
        readline.set_completer_delims(' \t')
        if 'libedit' in (readline.__doc__ or ''):
            readline.parse_and_bind('bind ^I rl_complete')   # macOS libedit
        else:
            readline.parse_and_bind('tab: complete')         # GNU readline
    try:
        session(s, prompt_for(target, isinstance(addr, str)))
    finally:
        s.close()


def session(sock, prompt):
    """Read-execute loop: local commands first, everything else goes to the fake."""
    global _prompt
    _prompt = prompt
    while True:
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        cmd = line.strip()
        if not cmd:
            continue
        low = cmd.lower()
        if low in ('quit', 'exit', 'logout'):
            return
        if low in ('?', 'help'):
            print(HELP)
            continue
        if low.split()[0] == 'help' and len(low.split()) > 1:
            reply = exchange(sock, cmd)     # help <setting>: the registry answer
            if reply is None:
                return
            print(reply)
            continue
        if low.endswith('?'):
            print_options(low[:-1])
            continue
        if low == 'shutdown':
            if not confirm_shutdown(sock):
                continue
            return
        reply = exchange(sock, cmd)
        if reply is None:
            return
        if low.startswith(('set ', 'unset ')) and reply.startswith('ok'):
            print('ok')             # set/unset confirm silently
        elif low in ('show settings', 'show all') and reply.startswith('ok '):
            for row in format_settings(reply):
                print(row)
        elif low.startswith('show ') and reply.startswith('ok ') and '=' in reply:
            print(reply.split(' ', 1)[1].split('=', 1)[1])   # the bare value
        else:
            print(reply)


def format_settings(reply):
    """'ok k=v k=v ...' -> one aligned 'key value' per line."""
    pairs = [p.split('=', 1) for p in reply.split()[1:] if '=' in p]
    width = max(len(k) for k, _ in pairs)
    return ['  %-*s %s' % (width, k, v) for k, v in pairs]


def confirm_shutdown(sock):
    """Cisco-style [confirm]: RETURN or y/yes proceeds, anything else aborts."""
    try:
        ans = input('Proceed with shutdown? [confirm] ')
    except (EOFError, KeyboardInterrupt):
        print()
        print('% Aborted.')
        return False
    if ans.strip().lower() not in ('', 'y', 'yes'):
        print('% Aborted.')
        return False
    reply = exchange(sock, 'shutdown')
    if reply is not None:
        print(reply)
    return True   # 'bye shutdown' is out; the fake is stopping either way


def exchange(sock, cmd):
    """Send one command, return the reply; None = the connection is gone."""
    try:
        sock.sendall((cmd + '\n').encode())
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buf += chunk
    except OSError as e:
        print('control error: %s' % e, file=sys.stderr)
        raise SystemExit(1)
    return buf.decode('utf-8', 'replace').strip()


if __name__ == '__main__':
    main()
