#!/usr/bin/env python3
"""console-style interactive CLI for modbus-cache's control server.

A session front-end on top of the line-protocol control socket: prompt with
the connected port, TAB completion and `?` in every position, `show`
commands print the state lines, `clear cache` and `restart` confirm with a
plain `ok`, and `shutdown` asks before it stops the proxy.

  python3 cache_cli.py --control-port 15509
  MODBUS_CACHE_CTL=15509 python3 cache_cli.py

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import argparse
import os
import re
import socket
import sys
import threading

try:
    import readline
except ImportError:
    readline = None

from lib.config import resolve_control_target

KEEPALIVE_ENV = 'CACHE_CLI_KEEPALIVE'   # ping interval in seconds; 0 = off
DEFAULT_KEEPALIVE = 55.0                # well under the control server's idle timeout

COMMANDS = ('show', 'clear', 'restart', 'shutdown', 'quit')

COMMAND_HELP = {
    'show': 'runtime state: show status | connections | cache',
    'clear': 'drop the cached registers, repoll now (clear cache)',
    'restart': 'restart the upstream session: connection + cache dropped, repoll',
    'shutdown': 'stop the proxy gracefully (asks to confirm)',
    'quit': 'close the session',
}

SHOW_VALUES = (
    ('status', 'one-line effective state: upstream, listen, clients, poll, counters'),
    ('connections', 'connected clients: peer, age, requests served'),
    ('cache', 'cache contents: ranges, words, freshness, hits/misses'),
)

SHOW_DESC = dict(SHOW_VALUES)

HELP = """commands (TAB completes, ? lists the options + descriptions in any position):
""" + ''.join('  %-10s %s\n' % (n, d) for n, d in COMMAND_HELP.items()) + '  ?          this help'


def prompt_for(target, is_unix):
    """cache:<port> > — the TCP control port, or the port embedded in the
    socket name (modbus-cache-15502.socket), else the socket name."""
    if is_unix:
        base = os.path.basename(target)
        if base.endswith('.socket'):
            base = base[:-len('.socket')]
        m = re.search(r'(\d+)$', base)
        return 'cache:%s > ' % (m.group(1) if m else base)
    return 'cache:%s > ' % target


def candidates(buf):
    """Valid next words for the buffer being completed or questioned:
    (matches, hint about the following word, describer of each word)."""
    end_space = buf.endswith(' ')
    parts = buf.split()
    text = '' if end_space else (parts[-1] if parts else '')
    done = parts if end_space else parts[:-1]
    head = done[0].lower() if done else ''
    if not done:
        pool, hint, desc = COMMANDS, None, describe_word
    elif head == 'show' and len(done) == 1:
        pool, hint, desc = tuple(SHOW_DESC), None, describe_word
    elif head == 'clear' and len(done) == 1:
        pool, hint, desc = ('cache',), None, describe_word
    else:
        return [], None, None
    return [w for w in pool if w.startswith(text.lower())], hint, desc


def describe_word(w):
    """The short description from the registry, if there is one."""
    return COMMAND_HELP.get(w) or SHOW_DESC.get(w)


_last_listed = None   # the completer is called several times per attempt;
                      # list each distinct buffer only once
_prompt = 'cache > '   # the session's prompt; the completer re-echoes it after the list

_send_lock = threading.Lock()   # the keepalive thread and exchange() share the wire
_stop_ping = threading.Event()


def keepalive(sock, interval):
    """Send pings while the user thinks, so the control server's idle timeout
    never drops a live session; any traffic resets that timer."""
    while not _stop_ping.wait(interval):
        try:
            with _send_lock:
                sock.sendall(b'ping\n')
        except OSError:
            return   # session is gone; the main thread will notice too


def complete(text, state):
    """TAB completer, console-style: extend the word silently while the common
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
                rows.append('  %-10s %s' % (w, d) if d else '  %s' % w)
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
    """console ?`: one candidate per line, with the short description."""
    matches, hint, desc = candidates(buf)
    if not matches:
        print('% Invalid input.')
        return
    for w in matches:
        d = desc(w) if desc else None
        print('  %-10s %s' % (w, d) if d else '  %s' % w)
    if hint:
        print('  ' + hint)


def main():
    p = argparse.ArgumentParser(description='console-style CLI for the modbus-cache control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/modbus-cache-15502.socket; env MODBUS_CACHE_CTL or CACHE_CTL when unset) — same flag as the proxy itself')
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
    """Read-execute loop: local commands first, everything else goes to the proxy."""
    global _prompt
    _prompt = prompt
    interval = float(os.environ.get(KEEPALIVE_ENV, '') or DEFAULT_KEEPALIVE)
    if interval > 0:
        threading.Thread(target=keepalive, args=(sock, interval), daemon=True).start()
    try:
        _loop(sock, prompt)
    finally:
        _stop_ping.set()


def _loop(sock, prompt):
    while True:
        try:
            print()                     # breathing room: every prompt on a fresh line
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
        if low == 'ping':               # local: the wire pings belong to the keepalive thread
            print('ok pong')
            continue
        if low in ('?', 'help'):
            print(HELP)
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
        if low.startswith(('clear ', 'restart')) and reply.startswith('ok'):
            print('ok')                 # confirm silently
        elif low.startswith('show ') and reply.startswith('ok '):
            print(reply.split(' ', 1)[1])
        else:
            print(reply)


def confirm_shutdown(sock):
    """console-style [confirm]: RETURN or y/yes proceeds, anything else aborts."""
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
    return True   # 'bye shutdown' is out; the proxy is stopping either way


def exchange(sock, cmd):
    """Send one command, return the reply; None = the connection is gone.
    Keep-alive pongs are absorbed: they can land before or after the reply
    we are actually waiting for (replies are strictly ordered on the wire)."""
    try:
        with _send_lock:
            sock.sendall((cmd + '\n').encode())
        buf = b''
        while True:
            while b'\n' not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    return None
                buf += chunk
            line, buf = buf.split(b'\n', 1)
            text = line.decode('utf-8', 'replace').strip()
            if text == 'ok pong':
                continue
            if text:
                return text
    except OSError as e:
        print('control error: %s' % e, file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
