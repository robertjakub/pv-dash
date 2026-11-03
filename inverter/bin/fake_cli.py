#!/usr/bin/env python3
"""console-style interactive CLI for the fake inverter's control server.

A session front-end on top of the line-protocol control socket: prompt with
the connected port, TAB completion and `?` in every position (with the short
descriptions from the shared command registry), `set` commands print only
the confirmation (never the status tail), `show <setting>` prints the bare
value, `show settings` one setting per line, `show status` the key=value
report, and `shutdown` asks before it stops the fake.

The session itself (connect/disconnect, the local commands like quit and
the aborted shutdown) is appended to an audit log (default audit.log in
the current directory, prefix CLI; --audit-log to rename, --no-audit-log
to turn it off); the commands themselves are audited by the server (the
peer is on its side) — ping/pong keepalives are never logged.

  python3 fake_cli.py --control-port 15599
  FAKE_CTL=15599 python3 fake_cli.py

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the src/ — the lib/ lives next to bin/

import argparse
import getpass
import json
import os
import re
import socket
import sys
import threading

from lib.audit import AuditLog

try:
    import readline
except ImportError:
    readline = None

from lib.paths import resolve_control_target
from lib.settings import COMMAND_HELP, SETTING_BY_NAME, SETTING_NAMES, describe_value

KEEPALIVE_ENV = 'FAKE_CLI_KEEPALIVE'    # ping interval in seconds; 0 = off
DEFAULT_KEEPALIVE = 55.0                # well under the control server's idle timeout

HELP = """commands (TAB completes, ? lists the options + descriptions in any position):
""" + ''.join('  %-10s %s\n' % (n, d) for n, d in
              (('set', 'configure a setting (set soc auto, set scenario noon)'),
               ('unset', 'restore a setting to its configured value (unset pv, unset seed)'),
               ('show', 'print a setting, the status line, or all of them'),
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
        pool, hint, desc = SETTING_NAMES + ('register',), None, describe_word
    elif head == 'show' and len(done) == 1:
        pool, hint, desc = SETTING_NAMES + ('settings', 'status', 'registers', 'version'), None, describe_word
    elif head in ('set', 'unset') and len(done) == 2:
        s = SETTING_BY_NAME.get(done[1].lower())
        pool, hint = (s.values if s else []), (s.hint if s else None)
        desc = (lambda w, _n=done[1].lower(): describe_value(_n, w))
    else:
        return [], None, None
    return sorted(w for w in pool if w.startswith(text.lower())), hint, desc


def describe_word(w):
    """The short description from the shared registry, if there is one."""
    if w in SETTING_BY_NAME:
        return SETTING_BY_NAME[w].help
    if w in COMMAND_HELP:
        return COMMAND_HELP[w]
    if w == 'settings':
        return 'every setting, one per line'
    if w == 'register':
        return 'write a raw register (the same overlay as the FC16 writes)'
    if w == 'status':
        return 'the effective state report (key=value lines)'
    if w == 'registers':
        return "the loaded profile's register map with the current values"
    if w == 'version':
        return 'the fake-inverter version'
    return None


_last_listed = None   # the completer is called several times per attempt;
                      # list each distinct buffer only once
_prompt = 'fake-inverter > '   # the session's prompt; the completer re-echoes it after the list

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
    """console ?`: one candidate per line, with the short description."""
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
    p = argparse.ArgumentParser(description='console-style CLI for the fake inverter control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/fake-inverter-5502.socket; env FAKE_CTL when unset) — same flag as the fake itself')
    p.add_argument('--timeout', type=float, default=5.0, help='socket timeout in seconds (default %(default)s)')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env FAKE_CONTROL_TOKEN)')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path or - for stdout; default: the XDG state home")
    p.add_argument('--audit-max-mb', type=float, default=10.0, help='rotate the audit log at this size in MB, keeping 3 backups; 0 = off (default %(default)s)')
    p.add_argument('--audit-files', type=int, default=3, help='rotated audit backups to keep (default %(default)s)')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    args = p.parse_args()

    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'CLI')

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
    if readline and sys.stdin.isatty():
        readline.set_completer(complete)
        readline.set_completer_delims(' \t')
        if 'libedit' in (readline.__doc__ or ''):
            readline.parse_and_bind('bind ^I rl_complete')   # macOS libedit
        else:
            readline.parse_and_bind('tab: complete')         # GNU readline
    try:
        session(s, prompt_for(target, isinstance(addr, str)), audit, token, isinstance(addr, str))
    finally:
        if audit:
            audit.event('DISCONNECT', 'target=%s' % label)
            audit.close()
        s.close()


def session(sock, prompt, audit=None, token=None, is_unix=False):
    """Read-execute loop: local commands first, everything else goes to the fake."""
    global _prompt
    _prompt = prompt
    if token and not is_unix:
        reply = exchange(sock, json.dumps({'cmd': 'auth', 'token': token}, ensure_ascii=False))
        if not reply or not reply.startswith('ok'):
            print('control auth failed: %s' % (reply or 'no reply'), file=sys.stderr)
            raise SystemExit(1)
    if sys.stdin.isatty():
        welcome(sock)
    interval = float(os.environ.get(KEEPALIVE_ENV, '') or DEFAULT_KEEPALIVE)
    if interval > 0:
        threading.Thread(target=keepalive, args=(sock, interval), daemon=True).start()
    try:
        _loop(sock, prompt, audit)
    finally:
        _stop_ping.set()


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
    """The first-connect greeting: probe the status and introduce the device —
    the profile, how long the fake has been running, the grid/clock/battery
    state, and the one-line navigation hint."""
    reply = exchange(sock, wire('show status'))
    if not reply or not reply.startswith('ok status'):
        return
    st = dict(row.split('=', 1) for row in reply.split('\n')[1:] if '=' in row)
    print('% Welcome to the Fake Inverter console —')
    print('%%   %s' % st.get('profile', 'unknown profile'))
    print('%%   running for %s | %s clock | %s V grid | battery %s'
          % (human_uptime(st.get('uptime', '0')), st.get('timezone', 'utc'), st.get('grid_voltage', '230'),
             ('on (%s W, %s %%SoC)' % (st.get('battery', '?'), st.get('soc', '?')))
             if 'soc' in st else 'off'))
    print('%   TAB completes, ? lists the commands, help <setting> explains one, quit leaves')


def wire(cmd):
    """The JSON wire form of a typed command."""
    return json.dumps({'cmd': cmd}, ensure_ascii=False)


def _loop(sock, prompt, audit=None):
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
        if low == 'ping':               # local: the wire pings belong to the keepalive thread
            print('ok pong')
            continue                    # (and the audit skips ping/pong by design)
        if low in ('quit', 'exit', 'logout'):
            if audit:
                audit.command(cmd, 'local')
            return
        if low in ('?', 'help'):
            if audit:
                audit.command(cmd, 'local')
            print(HELP)
            continue
        if low.split()[0] == 'help' and len(low.split()) > 1:
            reply = exchange(sock, wire(cmd))     # help <setting>: the registry answer
            if reply is None:
                return
            display(reply)
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
        reply = exchange(sock, wire(cmd))
        if reply is None:
            return
        # the wire commands are the server's audit trail (it knows the peer)
        if low.startswith(('set ', 'unset ')) and reply.startswith('ok'):
            print('% ok')           # set/unset confirm silently
        elif low == 'show version' and reply.startswith('ok fake-inverter'):
            print(reply.split(' ', 1)[1])   # the bare version line
        elif low in ('show settings', 'show all') and reply.startswith('ok '):
            for row in format_settings(reply):
                print(row)
        elif low.startswith('show ') and reply.startswith('ok ') and '=' in reply and '\n' not in reply:
            print(reply.split(' ', 1)[1].split('=', 1)[1])   # the bare value
        else:
            display(reply)


def display(text):
    """console-style: the ok data speaks for itself (the rows/the tables/the
    values printed bare — no '% ok' noise); the error lines keep the '% '
    prefix so they are visible."""
    lines = text.splitlines()
    if not lines:
        return
    first = lines[0]
    if first.startswith('err'):
        print('\n'.join('% ' + l for l in lines))
        return
    if first.startswith('ok '):
        rest = lines[1:] if len(lines) > 1 else [first[3:]]
        print('\n'.join(rest))
        return
    print(text)


def format_settings(reply):
    """'ok k=v k=v ...' -> one aligned 'key value' per line."""
    pairs = [p.split('=', 1) for p in reply.split()[1:] if '=' in p]
    width = max(len(k) for k, _ in pairs)
    return ['  %-*s %s' % (width, k, v) for k, v in pairs]


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
    reply = exchange(sock, wire('shutdown'))
    if reply is not None:
        print(reply)
    return True   # 'bye shutdown' is out; the fake is stopping either way


def exchange(sock, wire):
    """Send one JSON request (the wire = the JSON text), read one JSON reply;
    returns the internal 'ok ...'/'err ...' string; None = the connection is
    gone. Keep-alive pongs are absorbed: they can land before or after the
    reply we are actually waiting for (replies are strictly ordered)."""
    try:
        with _send_lock:
            sock.sendall((wire + '\n').encode())
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
    except OSError as e:
        print('control error: %s' % e, file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
