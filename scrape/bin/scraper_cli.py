#!/usr/bin/env python3
"""console-style interactive CLI for modbus-scraper's JSON-lines control server.

A session front-end on top of the control socket: prompt with the connected
port, TAB completion and `?` in every position (with the short descriptions
from the shared command registry), `set` commands print only the
confirmation, `show <setting>` prints the bare value, `show settings` one
setting per line, `show status` the key=value report, and `shutdown` asks
before it stops the scraper.

The session itself (connect/disconnect, the local commands like quit and
the aborted shutdown) is appended to an audit log (default in the XDG state
home, prefix CLI; --audit-log to rename, --no-audit-log to turn it off);
the commands themselves are audited by the server (the peer is on its
side) — ping/pong keepalives are never logged. When the connection dies
mid-session (an unanswered ping, the scraper gone), the CLI retries:
--reconnect attempts, --reconnect-wait seconds apart. With a token
configured the wire is HMAC-signed (the full sha256 of each frame,
common/wiresec.py): the console signs every command and verifies every
reply.

  python3 scraper_cli.py --control-port 15509
  SCRAPER_CTL=15509 python3 scraper_cli.py

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
import re
import socket
import sys
import threading
import time

try:
    import readline
except ImportError:
    readline = None

from common.audit import AuditLog
from common.config import load_token_file
from common.human import secs
from common.wiresec import sign_request, verify_reply
from lib.config import resolve_control_target
from lib.settings import COMMAND_HELP, COMMANDS, SETTING_BY_NAME, SETTING_NAMES, SHOW_VALUES, describe_value
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_KEEPALIVE_S, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S

KEEPALIVE_ENV = 'SCRAPER_CLI_KEEPALIVE'   # ping interval in seconds; 0 = off
DEFAULT_KEEPALIVE = CLI_KEEPALIVE_S     # well under the control server's idle timeout

HELP_ROWS = (
    ('set', 'configure a setting (set interval 5, set log-access on)'),
    ('unset', 'restore a setting to its configured value (unset interval, unset log-level)'),
    ('show', 'print a setting, the status report, or all of them'),
    ('poll now', 'wake the poll loop immediately'),
    ('request reload', 're-read the config (the SIGHUP path; the token file included)'),
    ('restart', 'drop the Modbus session (reconnects on the next poll)'),
    ('shutdown', 'stop the scraper (asks to confirm)'),
    ('quit', 'close the session'),
    ('?', 'this help'),
    ('help <setting>', "the setting's description"),
)

HELP = 'commands (TAB completes, ? lists the options + descriptions in any position):\n' \
     + '\n'.join('    %-*s %s' % (max(len(n) for n, _ in HELP_ROWS) + 1, n, d)
                 for n, d in HELP_ROWS)


class ConnectionLost(Exception):
    """The control connection is gone: EOF without a bye, a reset, a send
    failure or a reply timeout. The session decides: reconnect or exit."""


class DaemonExit(Exception):
    """The daemon sent its bye daemon-exit frame: print the notice and leave —
    there is nothing on the other end to reconnect to."""


def daemon_exit_notice(text):
    """The '% daemon exit: ... — console closing' line, from the wire's JSON
    frame or the internal 'bye daemon-exit: ...' form."""
    m = re.search(r'daemon-exit: ([^"\n]*)', text or '')
    print('\n%% daemon exit: %s — console closing' % (m.group(1).rstrip() if m else 'the daemon is gone'))
    sys.stdout.flush()


def prompt_for(target, is_unix):
    """scraper:<port> > — the TCP control port, or the port embedded in the
    socket name (modbus-scraper-9350.socket), else the socket name."""
    if is_unix:
        base = os.path.basename(target)
        if base.endswith('.socket'):
            base = base[:-len('.socket')]
        m = re.search(r'(\d+)$', base)
        return 'scraper:%s > ' % (m.group(1) if m else base)
    return 'scraper:%s > ' % target


def candidates(buf):
    """Valid next words for the buffer being completed or questioned:
    (matches, hint about the following word, describer of each word, the
    [settings]/[values]/[system] groups for the listing)."""
    end_space = buf.endswith(' ')
    parts = buf.split()
    text = '' if end_space else (parts[-1] if parts else '')
    done = parts if end_space else parts[:-1]
    head = done[0].lower() if done else ''
    if not done:
        pool, hint, desc = COMMANDS, None, describe_word
    elif head in ('set', 'unset') and len(done) == 1:
        pool, hint, desc = SETTING_NAMES, None, setting_help
    elif head == 'set' and len(done) == 2 and done[1].lower() in SETTING_BY_NAME:
        s = SETTING_BY_NAME[done[1].lower()]
        pool, hint = tuple(s.values), s.value_shape
        desc = lambda w, s=s: s.value_help.get(w, s.value_help.get(w.lower(), '')) or None
    elif head == 'request' and len(done) == 1:
        pool, hint, desc = ('reload',), None, describe_word
    elif head == 'poll' and len(done) == 1:
        pool, hint, desc = ('now',), None, describe_word
    elif head == 'show' and len(done) == 1:
        pool, hint, desc = SETTING_NAMES + ('status', 'connections', 'settings', 'version'), None, describe_word
    else:
        return [], None, None, []
    if pool is None:                      # a value shape with no completable words
        return [], hint, desc, [('values', [])]
    matches = [w for w in pool if w.startswith(text.lower())]
    return matches, hint, desc, _sections(head, len(done), matches)


def _sections(head, done_len, matches):
    """The listing groups: the real tunables ([settings]), the values of one
    setting ([values]), everything else ([system]: the report words, the
    commands)."""
    if done_len >= 2 and head in ('set', 'unset'):
        return [('values', matches)]
    if head in ('set', 'unset') and done_len == 1:
        return [('settings', matches)]
    if head == 'show' and done_len == 1:
        return [('settings', [w for w in matches if w in SETTING_BY_NAME]),
                ('system', [w for w in matches if w not in SETTING_BY_NAME])]
    return [('system', matches)]


def sectioned_rows(sections, desc, hint):
    """The listing: a blank line, then the [settings]/[values]/[system]
    header, its entries padded two spaces under it, descriptions aligned
    among themselves."""
    rows = []
    for label, words in sections:
        if not words:
            continue
        rows.append('')
        rows.append('  [%s]' % label)
        rows.extend('  ' + r for r in aligned_rows(words, desc, None))
    if hint:
        rows.append('    ' + hint)
    return rows


def describe_word(w):
    """The short description from the registry, if there is one."""
    return COMMAND_HELP.get(w) or dict(SHOW_VALUES).get(w) or setting_help(w)


def setting_help(name):
    s = SETTING_BY_NAME.get(name)
    return s.help if s else None


def aligned_rows(matches, desc, hint):
    """One candidate per line with the descriptions aligned to the longest
    described word. The hint line keeps its own indent."""
    width = max((len(w) for w in matches if desc(w)), default=0)
    rows = []
    for w in matches:
        d = desc(w)
        rows.append('  %-*s %s' % (width, w, d) if d else '  %s' % w)
    if hint:
        rows.append('  ' + hint)
    return rows


_last_listed = None   # the completer is called several times per attempt;
                      # list each distinct buffer only once
_prompt = 'scraper > '   # the session's prompt; the completer re-echoes it after the list
_token = None             # the control token: every frame is signed with it when set
_require_reply_mac = False   # True once the token handshake happened (TCP): unsigned replies are fatal

_send_lock = threading.Lock()   # the keepalive thread and exchange() share the wire
_stop_ping = threading.Event()


def keepalive(sock, interval, audit=None):
    """Send signed pings while the user thinks, so the control server's idle
    timeout never drops a live session; any traffic resets that timer. A
    dead wire while the console sits at the prompt: if the daemon announced
    its exit, the bye frame is still pending — print the notice and leave
    (no reconnect against a dead scraper); an unannounced death is the main
    loop's business."""
    while not _stop_ping.wait(interval):
        try:
            with _send_lock:
                sock.sendall((json.dumps(sign_request(_token, 'ping') if _token else {'cmd': 'ping'},
                                         ensure_ascii=False) + '\n').encode())
        except OSError:
            try:
                sock.setblocking(False)
                data = sock.recv(4096).decode('utf-8', 'replace')
            except OSError:
                data = ''
            finally:
                try:
                    sock.settimeout(CLI_TIMEOUT_S)
                except OSError:
                    pass
            if 'daemon-exit' in data:
                daemon_exit_notice(data)
                if audit:
                    audit.event('DISCONNECT', 'daemon exit')
                    audit.close()
                os._exit(0)
            return   # unannounced: the main loop notices on the next command


def complete(text, state):
    """TAB completer, console-style: extend the word silently while the common
    prefix grows (a single-match return inserts it — verified libedit adds no
    space and lists nothing); once the prefix is exhausted, print the options
    OURSELVES — one candidate per line with the short descriptions (editline
    column-packs or skips its own listings) — and yield no match so the
    editor just redraws the line."""
    global _last_listed
    matches, hint, desc, sections = candidates(readline.get_line_buffer())
    if state >= len(matches):
        return None
    if len(matches) > 1:
        common = os.path.commonprefix(matches)
        if len(common) > len(text):
            return common if state == 0 else None
        buf = readline.get_line_buffer()
        if state == 0 and _last_listed != buf:
            _last_listed = buf
            rows = sectioned_rows(sections, desc, hint)
            # the list, a blank line, then the prompt + line again — editline
            # does NOT redraw after the completer, so we do it ourselves
            print('\n'.join(rows) + '\n')
            sys.stdout.write(_prompt + buf)
            sys.stdout.flush()
        return None
    # a single match: insert it with the trailing space so the NEXT tab moves
    # into the following word — editline does not add the space itself, and
    # without it tab-tab just re-completes the same word and never lists
    return matches[0] + ' '


def print_options(buf):
    """`<prefix>?`: one candidate per line, grouped into the [settings] /
    [values] / [system] sections; a value shape with no completable words
    still shows its hint."""
    matches, hint, desc, sections = candidates(buf)
    rows = sectioned_rows(sections, desc, hint)
    if not rows:
        print('% Invalid input.')
        return
    for row in rows:
        print(row)


def main():
    p = argparse.ArgumentParser(description='console-style CLI for the modbus-scraper control server (TCP or unix socket).')
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (default: /tmp/modbus-scraper-9350.socket; env SCRAPER_CTL when unset) — same flag as the scraper itself')
    p.add_argument('--timeout', type=float, default=CLI_TIMEOUT_S, help='socket timeout in seconds (default %(default)s)')
    p.add_argument('--reconnect', type=int, default=CLI_RECONNECT, help='when the connection dies (an unanswered ping, a reset, a timeout), retry this many times before giving up; 0 = off (default %(default)s)')
    p.add_argument('--reconnect-wait', type=float, default=CLI_RECONNECT_WAIT_S, help='seconds between the reconnect attempts (default %(default)s)')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env SCRAPER_CONTROL_TOKEN)')
    p.add_argument('--control-token-file', default=None, help='the token from a file (the first line; must be owner-only 0600); not for use with --control-token (env SCRAPER_CONTROL_TOKEN_FILE)')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path or - for stdout; default: the XDG state home")
    p.add_argument('--audit-max-mb', type=float, default=AUDIT_MAX_MB, help='rotate the audit log at this size in MB, keeping 3 backups; 0 = off (default %(default)s)')
    p.add_argument('--audit-files', type=int, default=AUDIT_FILES, help='rotated audit backups to keep (default %(default)s)')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    p.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (modbus-scraper-cli --man | man -l -)')
    args = p.parse_args()
    if args.man:
        from lib.man import cli_page
        sys.stdout.write(cli_page(p))
        raise SystemExit(0)

    audit = None if args.no_audit_log else AuditLog(args.audit_log, 'CLI', app='modbus-scraper',
                                                    max_mb=args.audit_max_mb, files=args.audit_files)
    token_file = args.control_token_file or os.environ.get('SCRAPER_CONTROL_TOKEN_FILE')
    token = args.control_token or os.environ.get('SCRAPER_CONTROL_TOKEN')
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
        print('%% connection lost, reconnecting in %s (attempt %d of %d)'
              % (secs(args.reconnect_wait), attempt, args.reconnect))
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
        print('% reconnected to the scraper')
        return s
    print('control server unreachable after %d reconnect attempts' % args.reconnect, file=sys.stderr)
    if audit:
        audit.event('RECONNECT', 'gave up after %d attempts' % args.reconnect)
    return None


def session(sock, prompt, audit=None, token=None, is_unix=False, addr=None, args=None):
    """Read-execute loop: local commands first, everything else goes to the
    scraper. A dead connection raises ConnectionLost out of the loop and is
    met with the reconnect cycle (--reconnect); --reconnect 0 exits."""
    global _prompt, _token, _require_reply_mac
    _prompt = prompt
    _token = token
    try:
        while True:
            try:
                if token and not is_unix:
                    reply = exchange(sock, json.dumps({'cmd': 'auth', 'token': token}, ensure_ascii=False))
                    if not reply or not reply.startswith('ok'):
                        print('control auth failed: %s' % (reply or 'no reply'), file=sys.stderr)
                        return 1
                    _require_reply_mac = True   # the handshake holds: unsigned replies are fatal
                if sys.stdin.isatty():
                    welcome(sock)
                interval = float(os.environ.get(KEEPALIVE_ENV, '') or DEFAULT_KEEPALIVE)
                if interval > 0:
                    _stop_ping.clear()
                    threading.Thread(target=keepalive, args=(sock, interval, audit), daemon=True).start()
                return _loop(sock, prompt, audit)
            except DaemonExit as e:
                daemon_exit_notice(str(e))
                if audit:
                    audit.event('DISCONNECT', 'daemon exit')
                return
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
    """The JSON wire form of a typed command — token-signed when we hold
    the token (the server verifies every frame; the reply macs verify in
    exchange())."""
    return json.dumps(sign_request(_token, cmd) if _token else {'cmd': cmd}, ensure_ascii=False)


def welcome(sock):
    """The first-connect greeting: probe the status and introduce the scraper —
    the upstream, the poll health, the errors, how long it has been running —
    and the one-line navigation hint."""
    reply = exchange(sock, wire('show status'))
    if not reply or not reply.startswith('ok status'):
        return
    st = {}
    for line in reply.splitlines()[1:]:          # the key=value report rows
        if '=' in line:
            k, v = line.split('=', 1)
            st[k] = v
    print('% Welcome to the modbus-scraper console')
    print('%%   %s upstream | poll %s, last poll %s | %s error(s) | running for %s'
          % (st.get('upstream', '?'), st.get('poll', '?'), st.get('last_poll', '?'),
             st.get('errors', '?'), st.get('uptime', '?')))
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
        if low.startswith(('set ', 'unset ')):
            print('% ok' if reply.startswith('ok') else '% ' + reply)
        elif low in ('restart', 'poll now') and reply.startswith('ok'):
            print('ok')                 # confirm silently
        elif low.startswith('show ') and reply.startswith('ok '):
            body = reply.split(' ', 1)[1]
            head, _, rest = body.partition('\n')
            if rest and ' ' not in head and '=' not in head:
                print(rest)             # the report rows (the command already said the name)
            elif '\n' not in body and '=' in body:
                print(body.split('=', 1)[1])   # show <setting>: the bare value
            else:
                print(body)
        elif low == 'inspect' and reply.startswith('ok inspect\n'):
            print('\n'.join(reply.splitlines()[1:]))   # the dump itself is the answer
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
        return True   # the wire died right after the confirm; the scraper is stopping either way
    if reply is not None:
        print(reply)
    return True   # 'bye shutdown' is out; the scraper is stopping either way


def exchange(sock, wire_text):
    """Send one JSON request (the wire_text = the JSON text), read one JSON
    reply; returns the internal 'ok ...'/'err ...' string; None = the
    connection is gone (EOF without a bye). Raises ConnectionLost on a send
    failure, a reply timeout or a reply that fails the mac check. Keep-alive
    pongs are absorbed: they can land before or after the reply we are
    actually waiting for (replies are strictly ordered on the wire)."""
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
            mac = obj.get('mac')
            if _token and mac is not None and not verify_reply(_token, obj.get('status', 'err'),
                                                               str(obj.get('text', '')), mac):
                raise ConnectionLost('the reply mac does not verify — the wire was tampered with')
            if _token and mac is None and _require_reply_mac:
                raise ConnectionLost('the server did not sign the reply')
            if obj.get('status') == 'bye' and str(obj.get('text', '')).startswith('daemon-exit'):
                raise DaemonExit(text)
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
