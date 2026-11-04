#!/usr/bin/env python3
"""console-style interactive CLI for modbus-cache's JSON-lines control server.

A session front-end on top of the control socket: prompt with the connected
port, TAB completion and `?` in every position, `show` commands print the
state lines, `clear cache` and `restart` confirm with a plain `ok`, and
`shutdown` asks before it stops the proxy.

The session itself (connect/disconnect, the local commands like quit and
the aborted shutdown) is appended to an audit log (default in the XDG state
home, prefix CLI; --audit-log to rename, --no-audit-log to turn it off);
the commands themselves are audited by the server (the peer is on its
side) — ping/pong keepalives are never logged. When the connection dies
mid-session (an unanswered ping, the proxy gone), the CLI retries:
--reconnect attempts, --reconnect-wait seconds apart.

  python3 cache_cli.py --control-port 15509
  MODBUS_CACHE_CTL=15509 python3 cache_cli.py

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import argparse
import getpass
import json
import os
import re
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the checkout — the lib/ lives next to bin/

try:
    import readline
except ImportError:
    readline = None

from lib.audit import AuditLog
from lib.config import resolve_control_target

KEEPALIVE_ENV = 'CACHE_CLI_KEEPALIVE'   # ping interval in seconds; 0 = off
DEFAULT_KEEPALIVE = 55.0                # well under the control server's idle timeout

COMMANDS = ('show', 'clear', 'restart', 'shutdown', 'quit')

COMMAND_HELP = {
    'show': 'runtime state: show status | connections | cache | version',
    'clear': 'drop the cached registers, repoll now (clear cache)',
    'restart': 'restart the upstream session: connection + cache dropped, repoll',
    'shutdown': 'stop the proxy gracefully (asks to confirm)',
    'quit': 'close the session',
}

SHOW_VALUES = (
    ('status', 'one-line effective state: upstream, listen, clients, poll, counters'),
    ('connections', 'connected clients: peer, age, requests served'),
    ('cache', 'cache contents: ranges, words, freshness, hits/misses'),
    ('version', 'the modbus-cache version'),
)

SHOW_DESC = dict(SHOW_VALUES)

HELP = """commands (TAB completes, ? lists the options + descriptions in any position):
""" + ''.join('  %-10s %s\n' % (n, d) for n, d in COMMAND_HELP.items()) + '  ?          this help'


class ConnectionLost(Exception):
    """The control connection is gone: EOF without a bye, a reset, a send
    failure or a reply timeout. The session decides: reconnect or exit."""


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
                sock.sendall(b'{"cmd": "ping"}\n')
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
    p.add_argument('--reconnect', type=int, default=3, help='when the connection dies (an unanswered ping, a reset, a timeout), retry this many times before giving up; 0 = off (default %(default)s)')
    p.add_argument('--reconnect-wait', type=float, default=10.0, help='seconds between the reconnect attempts (default %(default)s)')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env MODBUS_CACHE_CONTROL_TOKEN)')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path or - for stdout; default: the XDG state home")
    p.add_argument('--audit-max-mb', type=float, default=10.0, help='rotate the audit log at this size in MB, keeping 3 backups; 0 = off (default %(default)s)')
    p.add_argument('--audit-files', type=int, default=3, help='rotated audit backups to keep (default %(default)s)')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    args = p.parse_args()

    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'CLI',
                                                    args.audit_max_mb, files=args.audit_files)
    token = args.control_token or os.environ.get('MODBUS_CACHE_CONTROL_TOKEN')
    target = resolve_control_target(args.control_port)
    if target.isdigit():
        if not 1 <= int(target) <= 65535:
            p.error('--control-port port out of range: %d' % int(target))
        addr, label = ('127.0.0.1', int(target)), '127.0.0.1:%s' % target
    else:
        addr, label = target, 'unix:%s' % target
    try:
        s = connect_once(addr, isinstance(addr, str), args.timeout)
    except OSError as e:
        print('cannot reach control server at %s: %s' % (label, e), file=sys.stderr)
        raise SystemExit(1)
    if audit:
        audit.event('CONNECT', 'target=%s user=%s' % (label, getpass.getuser()))
    if readline and sys.stdin.isatty():
        readline.set_completer(complete)
        readline.set_completer_delims(' \t')
        if 'libedit' in (readline.__doc__ or ''):
            readline.parse_and_bind('bind ^I rl_complete')   # macOS libedit
        else:
            readline.parse_and_bind('tab: complete')         # GNU readline
    try:
        rc = session(s, prompt_for(target, isinstance(addr, str)), audit, token,
                     isinstance(addr, str), addr, args)
    finally:
        if audit:
            audit.event('DISCONNECT', 'target=%s' % label)
            audit.close()
    if rc:
        raise SystemExit(rc)


def connect_once(addr, is_unix, timeout):
    """One fresh socket to the control target; the caller owns the close."""
    s = socket.socket(socket.AF_UNIX if isinstance(addr, str) else socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(addr)
    return s


def reconnect(addr, is_unix, args, audit=None):
    """The wire died mid-session: retry up to --reconnect times with
    --reconnect-wait seconds between the attempts; every attempt is
    audited. Returns the new socket, or None when the tries run out."""
    for attempt in range(1, args.reconnect + 1):
        print('%% connection lost, reconnecting in %gs (attempt %d of %d)'
              % (args.reconnect_wait, attempt, args.reconnect))
        try:
            time.sleep(args.reconnect_wait)
            s = connect_once(addr, is_unix, args.timeout)
        except OSError as e:
            print('%% reconnect attempt %d failed: %s' % (attempt, e))
            if audit:
                audit.event('RECONNECT', 'attempt %d of %d failed: %s' % (attempt, args.reconnect, e))
            continue
        if audit:
            audit.event('RECONNECT', 'attempt %d of %d ok' % (attempt, args.reconnect))
        print('% reconnected to the cache proxy')
        return s
    print('control server unreachable after %d reconnect attempts' % args.reconnect, file=sys.stderr)
    if audit:
        audit.event('RECONNECT', 'gave up after %d attempts' % args.reconnect)
    return None


def session(sock, prompt, audit=None, token=None, is_unix=False, addr=None, args=None):
    """Read-execute loop: local commands first, everything else goes to the
    proxy. A dead connection raises ConnectionLost out of the loop and is
    met with the reconnect cycle (--reconnect); --reconnect 0 exits."""
    global _prompt
    _prompt = prompt
    try:
        while True:
            try:
                if token and not is_unix:
                    reply = exchange(sock, json.dumps({'cmd': 'auth', 'token': token}, ensure_ascii=False))
                    if not reply or not reply.startswith('ok'):
                        print('control auth failed: %s' % (reply or 'no reply'), file=sys.stderr)
                        return 1
                if sys.stdin.isatty():
                    welcome(sock)
                interval = float(os.environ.get(KEEPALIVE_ENV, '') or DEFAULT_KEEPALIVE)
                if interval > 0:
                    _stop_ping.clear()
                    threading.Thread(target=keepalive, args=(sock, interval), daemon=True).start()
                return _loop(sock, prompt, audit)
            except ConnectionLost:
                try:
                    sock.close()
                except OSError:
                    pass
                if not args.reconnect:
                    print('connection lost', file=sys.stderr)
                    return 1
                sock = reconnect(addr, is_unix, args, audit)
                if sock is None:
                    return 1
    finally:
        _stop_ping.set()
        try:
            sock.close()
        except OSError:
            pass


def wire(cmd):
    """The JSON wire form of a typed command."""
    return json.dumps({'cmd': cmd}, ensure_ascii=False)


def human_uptime(seconds):
    """30s / 5m / 3h / 2d — one unit, no decimal digits."""
    s = int(seconds)
    if s >= 86400:
        return '%dd' % (s // 86400)
    if s >= 3600:
        return '%dh' % (s // 3600)
    if s >= 60:
        return '%dm' % (s // 60)
    return '%ds' % s


def welcome(sock):
    """The first-connect greeting: probe the status and introduce the proxy —
    the upstream, the poll health, how long it has been running — and the
    one-line navigation hint."""
    reply = exchange(sock, wire('show status'))
    if not reply or not reply.startswith('ok status'):
        return
    st = dict(p.split('=', 1)[0:2] for p in reply.split()[1:] if '=' in p)
    try:
        up = float(st.get('uptime', '0').rstrip('s'))
    except ValueError:
        up = 0.0
    print('% Welcome to the modbus-cache console')
    print('%%   %s upstream | poll %s, last poll %s | running for %s | %s client(s)'
          % (st.get('upstream', '?'), st.get('poll', '?'), st.get('last-poll', '?'),
             human_uptime(up), st.get('clients', '?')))
    print('%   TAB completes, ? lists the commands, quit leaves')


def _loop(sock, prompt, audit=None):
    """The typed-command loop. A dead connection (an exchange that raises
    ConnectionLost) surfaces out of the loop so the session can run its
    reconnect cycle; the clean exits return."""
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
            if audit:
                audit.command(cmd, 'local')
            return
        if low == 'ping':               # local: the wire pings belong to the keepalive thread
            print('ok pong')
            continue
        if low in ('?', 'help'):
            if audit:
                audit.command(cmd, 'local')
            print(HELP)
            continue
        if low.endswith('?'):
            if audit:
                audit.command(cmd, 'local')
            print_options(low[:-1])
            continue
        if low == 'shutdown':
            if not confirm_shutdown(sock):
                if audit:
                    audit.command('shutdown', 'aborted')
                continue
            if audit:
                audit.command('shutdown', 'ok')
            return
        try:
            reply = exchange(sock, wire(cmd))
        except ConnectionLost:
            raise
        if reply is None:
            raise ConnectionLost('the control connection closed without a bye')
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
    try:
        reply = exchange(sock, wire('shutdown'))
    except ConnectionLost:
        return True   # the wire died right after the confirm; the proxy is stopping either way
    if reply is not None:
        print(reply)
    return True   # 'bye shutdown' is out; the proxy is stopping either way


def exchange(sock, wire_text):
    """Send one JSON request (the wire_text = the JSON text), read one JSON
    reply; returns the internal 'ok ...'/'err ...' string; None = the
    connection is gone (EOF without a bye). Raises ConnectionLost on a send
    failure or a reply timeout. Keep-alive pongs are absorbed: they can land
    before or after the reply we are actually waiting for (replies are
    strictly ordered on the wire)."""
    try:
        with _send_lock:
            sock.sendall((wire_text + '\n').encode())
        buf = b''
        while True:
            while b'\n' not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    return None
                buf += chunk
            line, buf = buf.split(b'\n', 1)
            try:
                obj = json.loads(line.decode('utf-8', 'replace'))
            except ValueError:
                continue
            text = '%s %s' % (obj.get('status', 'err'), str(obj.get('text', '')))
            if text.strip() == 'ok pong':
                continue
            if text.strip():
                return text.strip()
    except socket.timeout:
        raise ConnectionLost('no reply within the socket timeout')
    except OSError:
        raise ConnectionLost('the control connection failed')


if __name__ == '__main__':
    main()
