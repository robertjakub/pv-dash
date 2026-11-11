#!/usr/bin/env python3
"""The console-style cli client, one implementation for the family: the
signed wire session, the reconnect cycle, the keepalive thread, the
readline TAB completion and the typed-command loop with the confirm guards.
The per-tool bins keep their prose and their registry wiring — the pools,
the candidates ladder, the welcome greeting and (for the fake) the
verb-first loop — passed here as a spec dict to run_cli(). Stdlib only."""
import argparse
import getpass
import json
import os
import re
import socket
import sys
import threading
import time

try:
    import readline
except ImportError:
    readline = None

from common.runtime.audit import AUDIT_FORWARD_FORMATS, AuditLog, audit_quote
from common.settings.config import parse_secret, resolve_target
from common.render.human import secs
from common.settings.options import command_path_pool, match_setting_path, render_word_sections, setting_path_pool
from common.render.texts import T
from common.wire.wiresec import sign_request, verify_reply

KEEPALIVE_ENV = 'CLI_KEEPALIVE'   # ping interval in seconds; 0 = off

_SPEC = None   # the tool's specifics — set by run_cli() before anything reads it
_keepalive_s = 0.0   # the parsed CLI_KEEPALIVE interval — run_cli() sets it before session() runs


def translate(cmd, spellings=None):
    """The typed line's knob words -> the flat registry names. The wire
    speaks the flattened options.json names (the daemon's match map takes
    no other spelling); the console accepts the rows' live/alias path
    spellings beside the flat names and translates here — the longest
    spelling that prefixes the words wins, the rest of the line (the
    value words) rides along. `spellings` is the tool's console-spelling
    map (the cli passes its spec's; the one-shot ctl passes the loader's
    SETTING_SPELLINGS — a piped config script's live-word lines translate
    the same way). Names no setting (the command paths, the node walks,
    the fake's `set register` words): the line passes through untouched."""
    parts = cmd.split()
    if len(parts) < 2:
        return cmd
    if parts[0].lower() not in ('set', 'clear', 'show', 'help'):
        return cmd
    key, rest = match_setting_path(parts[1:], spellings if spellings is not None else _SPEC['spellings'])
    if key is None:
        return cmd
    return ' '.join([parts[0], key] + list(rest))


class ConnectionLost(Exception):
    """The control connection is gone: EOF without a bye, a reset, a send
    failure or a reply timeout. The session decides: reconnect or exit."""


class DaemonExit(Exception):
    """The daemon sent its bye daemon-exit frame: print the notice and leave —
    there is nothing on the other end to reconnect to."""


def pools(commands, internal, hidden, spellings, nodes, commands_help,
          pool_names, banner_name):
    """The standard console's pool/describe/welcome furniture (the three
    simple cli bins' one shape; the cache's dump-gated pools keep their
    own): the completion/list pools speak the CONSOLE spellings (the rows'
    live/alias paths — the words TAB offers and `?` lists; the cli
    translates them to the flat registry names when it sends — a
    not-yet-live knob never lists, the hidden and internal rows never
    list) and the welcome prints the family banner. Returns (pool_names,
    describe_word, command_pool, setting_pool, welcome)."""
    names = tuple(n for n in pool_names if n not in hidden)
    describe_word = make_describe_word(nodes, commands_help, spellings)

    def command_pool():
        """The first words the daemon offers right now (the hidden and the
        internal rows never list)."""
        return tuple(n for n in commands if n not in hidden and n not in internal)

    def setting_pool():
        """The show-branch pool: the console spellings (the hidden rows
        never list)."""
        return names

    def welcome(sock):
        """The first-connect greeting: the console's two fixed lines — the
        daemon's name and the one-line navigation hint."""
        print(T('banner.welcome') % banner_name)
        print(T('banner.hint'))

    return names, describe_word, command_pool, setting_pool, welcome


def make_describe_word(nodes, commands_help, spellings):
    """The describer bound to one tool's registries — the golden order:
    a hierarchy node describes its namespace, a command row its help, a
    setting its own (looked up by any spelling — the flat name, the live
    path or the alias), then the walk-ons: a word both a settings
    namespace and a command one describes by the settings' first child
    (the alias-first-segment rule), a pure command namespace (`request`)
    by its first command child's help."""
    def describe_word(w):
        if w in nodes:
            return nodes[w].setting_help or nodes[w].help
        if w in commands_help:
            return commands_help[w]
        s = spellings.get(w)
        if s:
            mark = ' (the alias of %s)' % s.name if s.alias and w == s.alias else ''
            return s.help + mark
        walk = next((s for k, s in spellings.items() if k.startswith(w + '/')), None)
        if walk is not None:
            return walk.help
        return next((h for k, h in commands_help.items() if k.startswith(w + '/')), None)
    return describe_word


def daemon_exit_notice(text):
    """The '% daemon exit: ... — console closing' line, from the wire's JSON
    frame or the internal 'bye daemon-exit: ...' form — the frame decodes
    first, so the wire's unicode escapes never render raw."""
    raw = (text or '').strip()
    try:
        raw = json.loads(raw.splitlines()[-1]).get('text', raw)
    except (ValueError, IndexError, AttributeError):
        pass
    m = re.search(r'daemon-exit: (.*)', raw)
    print(T('cli.daemon_exit') % (m.group(1).strip() if m else T('cli.daemon_exit_fallback')))
    sys.stdout.flush()


def prompt_for(target, is_unix):
    """<tool>:<port> > — the TCP control port, or the port embedded in the
    socket name, else the socket name."""
    if is_unix:
        base = os.path.basename(target)
        if base.endswith('.socket'):
            base = base[:-len('.socket')]
        m = re.search(r'(\d+)$', base)
        return T('cli.prompt') % (_SPEC['prompt_word'], m.group(1) if m else base)
    return T('cli.prompt') % (_SPEC['prompt_word'], target)


def _sections(head, done_len, matches, values=False, base=''):
    """The listing groups: every word under its display group — a setting's
    row group (the full live name when the base path prefixes it, else the
    word; ungrouped words render bare — no header, the top of the listing),
    a hierarchy node's group (its `group`, else bare beside it), everything
    else bare (the report words, the commands)."""
    if values:
        return [('', matches)]   # bare: the value words need no [values] header — the
                                 # values branch is always the listing's sole section
    if head in ('set', 'clear', 'show') and done_len >= 1:
        return _grouped(matches, base)
    return [('', matches)]


def _grouped(matches, base):
    """The matches bucketed by their display group: the ungrouped rows —
    the knobs and the show commands without a group — take the '' bucket
    (no section header) and the listing renders them at the top; a
    namespace word (a hierarchy node, or the walk-on first segment of an
    aliased row) groups with the row it walks into; a word no row answers
    for rides the bare bucket too."""
    buckets = {}
    for w in matches:
        full = (base + '/' + w) if base else w
        s = _SPEC['spellings'].get(full) or _SPEC['spellings'].get(w)
        if s is not None:
            label = s.display_group
        else:
            n = _SPEC['nodes'].get(w)
            if n is not None:
                label = n.group or ''
            else:
                walk = next((s for k, s in _SPEC['spellings'].items() if k.startswith(w + '/')), None)
                label = walk.display_group if walk is not None else ''   # no group, bare
        buckets.setdefault(label, []).append(w)
    bare = buckets.pop('', None)
    secs = [('', sorted(bare, key=str.lower))] if bare else []
    return secs + [(label, sorted(ws, key=str.lower)) for label, ws in buckets.items()]


def sectioned_rows(sections, desc, hint):
    """The listing: a blank line, then each [section] header, its entries
    padded two spaces under it — the descriptions aligned to one column across all the sections.
    The render is the wire's describe_node's own (the ? output is the
    golden master — common/settings/options.py render_word_sections); the console
    adds the hint line."""
    rows = render_word_sections([(label, [(w, desc(w)) for w in ws]) for label, ws in sections])
    if hint:
        rows.append('    ' + hint)
    return rows


_last_listed = None   # the completer is called several times per attempt;
                      # list each distinct buffer only once
_prompt = None        # the session's prompt; the completer re-echoes it after the list
_token = None             # the control token: every frame is signed with it when set
_require_reply_mac = False   # True once the token handshake happened (TCP): unsigned replies are fatal

_send_lock = threading.Lock()   # the keepalive thread and exchange() share the wire
_stop_ping = threading.Event()


def keepalive_env(default_s):
    """The CLI_KEEPALIVE override, parsed once at startup: unset or blank
    rides the spec's default, a number is the ping interval (0 and the
    negatives keep the thread off), anything else is the family's one-line
    refusal — SystemExit before the connect, never the bare float()
    traceback deep in the session."""
    raw = os.environ.get(KEEPALIVE_ENV, '')
    if not raw.strip():
        return default_s
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(T('cli.keepalive_invalid') % raw)


def keepalive(sock, interval, audit=None):
    """Send signed pings while the user thinks, so the control server's idle
    timeout never drops a live session; any traffic resets that timer. A
    dead wire while the console sits at the prompt: if the daemon announced
    its exit, the bye frame is still pending — print the notice and leave
    (no reconnect against a dead daemon); an unannounced death is the main
    loop's business."""
    while not _stop_ping.wait(interval):
        try:
            with _send_lock:
                sock.sendall((json.dumps(sign_request(_token, 'ping') if _token else {'cmd': 'ping'},
                                         ensure_ascii=False) + '\n').encode())
        except OSError:
            try:
                sock.settimeout(1.0)   # an announced exit sent the bye before closing: give it a moment to land
                data = sock.recv(4096).decode('utf-8', 'replace')
            except OSError:
                data = ''
            finally:
                try:
                    sock.settimeout(_SPEC['timeout_s'])
                except OSError:
                    pass
            if 'daemon-exit' in data:
                daemon_exit_notice(data)
                if audit:
                    audit.event('DISCONNECT', 'reason=daemon-exit')
                    audit.close()
                os._exit(0)
            return   # unannounced: the main loop notices on the next command


def candidates(buf):
    """Valid next words for the buffer being completed or questioned — the
    golden ladder, one shape for the family: (matches, hint about the
    following word, describer of each word, the listing groups — the
    settings under their registry groups (ungrouped rows bare, no header),
    the values of one setting ([values]), the commands bare). The branches:
    the first position offers the commands (the spec's command_pool — the
    '/'-path rows walk segment-wise: `request` completes its children,
    `request flush` the leaf's own), set/clear walk the setting paths (the
    spec's setting_pool minus the show reports), show walks the
    setting paths including the reports. A live setting's name may be a
    '/'-path (`modbus/profile`): set/clear/show spell it as words — the
    completion offers the next segment until the path is whole, then the
    values."""
    end_space = buf.endswith(' ')
    parts = buf.split()
    text = '' if end_space else (parts[-1] if parts else '')
    done = parts if end_space else parts[:-1]
    head = done[0].lower() if done else ''
    values_mode = False
    base = ''
    if not done:
        # the first position walks the command paths segment-wise — the
        # settings' rule: `request` offers itself, then its children; a
        # slash never renders or inserts
        pool, hint, desc = command_path_pool(done, _SPEC['command_pool']()), None, _SPEC['describe']
    elif head in ('set', 'clear'):
        names = tuple(n for n in _SPEC['setting_pool']() if n not in _SPEC['show_lives'])
        by = {n: _SPEC['spellings'][n] for n in names if n in _SPEC['spellings']}   # the exact match obeys the pool:
        s, segs = setting_path_pool(done[1:], names, by)                            # a show report never offers a value
        if s is None:   # the hidden knobs (the secrets) never walk, but the typed whole path still describes
            s = _SPEC['spellings'].get('/'.join(w.lower() for w in done[1:]))
            if s is not None and s.show_report:
                s = None   # a show report never offers a value
        if s is not None:
            if head == 'clear':
                return [], '%s - %s' % (s.name, s.help), None, []   # the path is whole; clear takes no value — ? describes it
            values_mode = True
            pool = tuple(s.values)
            words = set(pool)
            rest = [p for p in s.value_shape.split('|') if p and p not in words]   # the shape's own words
            hint = '|'.join(rest) or None                                          # drop — the words spell them
            desc = lambda w, s=s: s.value_help.get(w, s.value_help.get(w.lower(), '')) or None
        else:
            base = '/'.join(w.lower() for w in done[1:])   # the path spelled so far — a segment's
            pool, hint = segs, None                        # description lives on the full live name
            desc = lambda w, base=base: _SPEC['describe']((base + '/' if base else '') + w)
    elif head == 'show':
        s, segs = setting_path_pool(done[1:], _SPEC['setting_pool'](), _SPEC['spellings'])
        base = '/'.join(w.lower() for w in done[1:])   # a segment's description lives on the full live name
        if s is None:   # the hidden knobs never walk, but the typed whole path still describes (the wire's help answers it)
            s = _SPEC['spellings'].get('/'.join(w.lower() for w in done[1:]))
        if s is not None:
            _, cont = setting_path_pool(done[1:] + [''], _SPEC['setting_pool'](), _SPEC['spellings'])
            if not cont:
                return [], '%s - %s' % (s.name, s.help), None, []   # the path is whole and childless; ? describes the report
            pool, hint = cont, None   # a namespace too: the report answers on Enter, TAB walks on
        else:
            pool, hint = segs, None
        desc = lambda w, base=base: _SPEC['describe']((base + '/' if base else '') + w)
    else:
        base = '/'.join(w.lower() for w in done)   # the command path spelled so far — a segment's
        pool, hint = command_path_pool(done, _SPEC['command_pool']()), None
        # the double-meaning node (the alias-first-segment rule): the
        # command word may also head the rows' alias/live paths — `write`
        # walks its command children AND the write-acl alias's next
        # segment; a whole live row answers with its values like set's
        # walk-on (a show report never offers a value)
        s, segs = setting_path_pool(done, _SPEC['setting_pool'](), _SPEC['spellings'])
        if s is not None and s.show_report:
            s = None
        if s is not None:
            values_mode = True
            pool = tuple(s.values)
            words = set(pool)
            rest = [p for p in s.value_shape.split('|') if p and p not in words]
            hint = '|'.join(rest) or None
            desc = lambda w, s=s: s.value_help.get(w, s.value_help.get(w.lower(), '')) or None
        else:
            pool = tuple(pool) + tuple(g for g in segs if g not in pool)
            desc = lambda w, base=base: _SPEC['describe']((base + '/' if base else '') + w)
    if pool is None:                      # a value shape with no completable words
        return [], hint, desc, [('values', [])]
    matches = [w for w in pool if w.startswith(text.lower())]
    return matches, hint, desc, _sections(head, len(done), matches, values_mode, base)

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
            print('\n' + '\n'.join(rows) + '\n')
            sys.stdout.write(_prompt + buf)
            sys.stdout.flush()
        return None
    # a single match: insert it with the trailing space so the NEXT tab moves
    # into the following word — editline does not add the space itself, and
    # without it tab-tab just re-completes the same word and never lists
    return matches[0] + ' '


def print_options(buf):
    """`<prefix>?`: one candidate per line, grouped into the registry's
    display groups (`# --- group ---` headers; the ungrouped words bare on
    top) plus [values]; a value shape with no completable words still shows
    its hint."""
    matches, hint, desc, sections = candidates(buf)
    rows = sectioned_rows(sections, desc, hint)
    if not rows:
        print(T('cli.invalid_input'))
        return
    for row in rows:
        print(row)


def connect_once(addr, is_unix, timeout):
    """One fresh socket to the control target; the caller owns the close."""
    s = socket.socket(socket.AF_UNIX if isinstance(addr, str) else socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(addr)
    return s


def reconnect(addr, is_unix, args, audit=None):
    """The wire died mid-session: up to --reconnect tries — the first one
    immediately, --reconnect-wait seconds between the tries — every
    attempt audited. Returns the new socket, or None when the tries run
    out."""
    print(T('cli.reconnecting') % args.reconnect)
    for attempt in range(1, args.reconnect + 1):
        try:
            s = connect_once(addr, is_unix, args.timeout)
        except OSError as e:
            print(T('cli.reconnect_attempt_failed') % (attempt, e))
            if audit:
                audit.event('RECONNECT', 'attempt=%d total=%d status=failed error=%s'
                            % (attempt, args.reconnect, audit_quote(e)))
            if attempt < args.reconnect:
                print(T('cli.reconnecting_in')
                      % (secs(args.reconnect_wait), attempt + 1, args.reconnect))
                time.sleep(args.reconnect_wait)
            continue
        if audit:
            audit.event('RECONNECT', 'attempt=%d total=%d status=ok' % (attempt, args.reconnect))
        print(T('cli.reconnected') % _SPEC['label'])
        return s
    print(T('cli.reconnect_failed'))
    if audit:
        audit.event('RECONNECT', 'total=%d status=gave-up' % args.reconnect)
    return None


def session(sock, prompt, audit=None, token=None, is_unix=False, addr=None, args=None):
    """Read-execute loop: local commands first, everything else goes to the
    daemon. A dead connection raises ConnectionLost out of the loop and is
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
                        print(T('shared.auth_failed') % (reply or 'no reply'), file=sys.stderr)
                        return 1
                    _require_reply_mac = True   # the handshake holds: unsigned replies are fatal
                if sys.stdin.isatty():
                    _SPEC['welcome'](sock)
                interval = _keepalive_s   # the env override parsed (and refused) once, at startup
                if interval > 0:
                    _stop_ping.clear()
                    threading.Thread(target=keepalive, args=(sock, interval, audit), daemon=True).start()
                return _SPEC['loop'](sock, prompt, audit)
            except DaemonExit as e:
                daemon_exit_notice(str(e))
                if audit:
                    audit.event('DISCONNECT', 'reason=daemon-exit')
                return
            except ConnectionLost:
                try:
                    sock.close()
                except OSError:
                    pass
                if not args.reconnect:
                    print(T('cli.connection_lost'), file=sys.stderr)
                    return 1
                sock = reconnect(addr, is_unix, args, audit)
                if sock is None:
                    return 1
    finally:
        _stop_ping.set()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def wire(cmd):
    """The JSON wire form of a typed command — token-signed when we hold
    the token (the server verifies every frame; the reply macs verify in
    exchange())."""
    return json.dumps(sign_request(_token, cmd) if _token else {'cmd': cmd}, ensure_ascii=False)


def display(text):
    """console-style: the face decides on the FIRST line's verdict head —
    an ok reply prints its message bare (quiet success; a bare `ok` with
    no message prints nothing), a failure prints '% error: <message>', a
    note prints '% <message>' (advice, not a verdict — the startup-only
    set's restart note), a bye notice keeps '% ' — and the continuation
    lines always stay raw (the multi-line tables keep their padding; no
    line-sniffing, so a table row starting with the words ok/err/note/bye
    never wears a marker)."""
    lines = text.splitlines()
    if not lines:
        return
    first, rest = lines[0], lines[1:]
    if first == 'ok':
        return                      # quiet success: no message, no marker
    if first.startswith('ok '):
        print('\n'.join([first.split(' ', 1)[1]] + rest))
    elif first.startswith('err '):
        print('\n'.join([T('shared.error_face') % first.split(' ', 1)[1]] + rest))
    elif first.startswith('note '):
        print('\n'.join([T('shared.plain_face') % first.split(' ', 1)[1]] + rest))
    elif first.startswith('bye'):
        print('\n'.join([T('shared.plain_face') % first] + rest))
    else:
        print(text)                 # an unheaded reply (the fake's own shapes) prints as-is


def typed_loop(sock, prompt, audit=None):
    """The typed-command loop. A dead connection (an exchange that raises
    ConnectionLost) surfaces out of the loop so the session can run its
    reconnect cycle; the clean exits return. The tool's spec tunes the
    renders: silent_ok(low) replies confirm silently, render(low, reply)
    prints a special table itself."""
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
        if cmd.startswith('#'):     # a config script pipes through: comments stay comments
            continue
        low = cmd.lower()
        if low in ('quit', 'exit', 'logout'):
            if audit:
                audit.command(cmd, 'local')
            return
        if low == 'ping':               # local: the wire pings belong to the keepalive thread
            print(T('cli.pong'))
            continue
        if low in ('?', 'help'):
            if audit:
                audit.command(cmd, 'local')
            print_options('')    # the word listing — the same rows TAB lists (the golden master)
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
        cmd = translate(cmd)   # the console's live/alias spellings -> the flat wire names
        low = cmd.lower()
        try:
            reply = exchange(sock, wire(cmd))
        except ConnectionLost:
            raise
        if reply is None:
            raise ConnectionLost(T('cli.closed_without_bye'))
        if low.startswith(('set ', 'clear ')):
            if reply.startswith('note ') or 'restart required' in reply:
                print(T('shared.plain_face') % reply.split(' ', 1)[1])   # the startup-only knob: the note type, or the refused secret's fail — a note face, not a verdict
            elif reply.startswith('ok'):
                print(T('cli.changed'))   # the one ok face keeping the marker
            else:
                display(reply)
        elif _SPEC['silent_ok'] and _SPEC['silent_ok'](low) and reply.startswith('ok'):
            pass                        # fully silent: the prompt returning is the confirm
        elif _SPEC['render'] and _SPEC['render'](low, reply):
            pass                        # the tool's special render answered
        elif (low.startswith('show ') or low == 'show') and reply.startswith('ok '):
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
            display(reply)


def confirm_shutdown(sock):
    """console-style [confirm]: RETURN or y/yes proceeds, anything else aborts."""
    try:
        ans = input(T('cli.confirm_shutdown'))
    except (EOFError, KeyboardInterrupt):
        print()
        print(T('cli.aborted'))
        return False
    if ans.strip().lower() not in ('', 'y', 'yes'):
        print(T('cli.aborted'))
        return False
    try:
        reply = exchange(sock, wire('shutdown'))
    except ConnectionLost:
        return True   # the wire died right after the confirm; the daemon is stopping either way
    if reply is not None:
        display(reply)
    return True   # 'bye shutdown' is out; the daemon is stopping either way


def exchange(sock, wire_text):
    """Send one JSON request (the wire_text = the JSON text), read one JSON
    reply; returns the internal 'ok ...'/'err ...' string; None = the
    connection is gone (EOF without a bye). Raises ConnectionLost on a send
    failure, a reply timeout or a reply that fails the mac check. Keep-alive
    pongs are absorbed: they can land before or after the reply we are
    actually waiting for (replies are strictly ordered on the wire)."""
    try:
        with _send_lock:
            if len(wire_text) > _SPEC['max_line_bytes']:
                # the client-side half of the daemon's line-cap guard: a
                # clean local verdict instead of the daemon dropping us
                return 'err %s' % (T('cli.command_too_long') % _SPEC['max_line_bytes'])
            sock.sendall((wire_text + '\n').encode())
        buf = b''
        while True:
            while b'\n' not in buf:
                if len(buf) > _SPEC['max_line_bytes']:
                    raise ConnectionLost(T('cli.reply_too_long') % _SPEC['max_line_bytes'])
                chunk = sock.recv(65536)
                if not chunk:
                    return None
                buf += chunk
            line, buf = buf.split(b'\n', 1)
            try:
                obj = json.loads(line.decode('utf-8', 'replace'))
            except ValueError:
                continue
            st = obj.get('status', 'fail')
            text = '%s %s' % ('err' if st == 'fail' else st, str(obj.get('text', '')))   # fail folds back: the internal string is the render hooks' currency
            mac = obj.get('mac')
            if _token and mac is not None and not verify_reply(_token, st,
                                                               str(obj.get('text', '')), mac):
                raise ConnectionLost(T('cli.mac_verify_failed'))
            if _token and mac is None and _require_reply_mac:
                raise ConnectionLost(T('shared.mac_missing'))
            if obj.get('status') == 'bye' and str(obj.get('text', '')).startswith('daemon-exit'):
                raise DaemonExit(text)
            if text.strip() == 'ok pong':
                continue
            if text.strip():
                return text.strip()
    except socket.timeout:
        raise ConnectionLost(T('cli.no_reply_timeout'))
    except OSError:
        raise ConnectionLost(T('cli.connection_failed'))


def run_cli(spec):
    """The whole cli ladder: the parser (the tool's name, socket, examples),
    the man page, the audit trail, the token parse, the connect, the CONNECT
    audit, the readline bootstrap and the session with its reconnect cycle."""
    global _SPEC, _keepalive_s
    _SPEC = spec
    p = argparse.ArgumentParser(description='console-style CLI for the %s (TCP or unix socket).' % spec['daemon_label'])
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (env CTL when unset) — same flag as %s' % spec['self_note'])
    p.add_argument('--timeout', type=float, default=spec['timeout_s'], help='socket timeout in seconds')
    p.add_argument('--reconnect', type=int, default=spec['reconnect'], help='when the connection dies (an unanswered ping, a reset, a timeout), retry this many times before giving up; 0 = off')
    p.add_argument('--reconnect-wait', type=float, default=spec['reconnect_wait'], help='seconds between the reconnect attempts')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env CONTROL_TOKEN); a file:<path> value reads the first line of an owner-only 0600 file')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path, - for stdout, or none for no local file (the forward carries the trail); the XDG state home when unset")
    p.add_argument('--audit-forward', default='none', metavar='TARGET',
                   help='also forward every audit line: none, syslog, syslog:/path, udp://host[:port] or tcp://host[:port] (the off-box copy, docs/SECURITY.md)')
    p.add_argument('--audit-forward-format', default='rfc5424', choices=AUDIT_FORWARD_FORMATS,
                   help="the remote forward's envelope: rfc5424 (the default) or cef — the local syslog forms keep the verbatim send")
    p.add_argument('--audit-max-mb', type=float, default=spec['audit_max_mb'], help='rotate the audit log at this size, 0 = off')
    p.add_argument('--audit-files', type=int, default=spec['audit_files'], help='rotated audit backups to keep')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    p.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (%s --man | man -l -)' % spec['cli_name'])
    args = p.parse_args()
    if args.man:
        sys.stdout.write(spec['cli_page'](p))
        raise SystemExit(0)

    _keepalive_s = keepalive_env(spec['keepalive_s'])

    token = args.control_token or os.environ.get('CONTROL_TOKEN')
    token = parse_secret(token, 'control-token')   # the inline form may be file:<path> — the same loader
    target = resolve_target(args.control_port, spec['ctl_socket'])
    if target.isdigit():
        if not 1 <= int(target) <= 65535:
            p.error('--control-port port out of range: %d' % int(target))
        addr, label = ('127.0.0.1', int(target)), '127.0.0.1:%s' % target
    else:
        addr, label = target, 'unix:%s' % target
    try:
        audit = None if args.no_audit_log else AuditLog(args.audit_log, spec.get('audit_tag', 'CLI'), app=spec['app'], writer='cli',
                                                        max_mb=args.audit_max_mb, files=args.audit_files,
                                                        forward=args.audit_forward,
                                                        forward_format=args.audit_forward_format,
                                                        instance=target if target.isdigit() else 'unix')
    except ValueError as e:
        p.error(str(e))

    try:
        s = connect_once(addr, isinstance(addr, str), args.timeout)
    except OSError as e:
        print(T('shared.cannot_reach') % (label, e), file=sys.stderr)
        raise SystemExit(1)
    if audit:
        audit.event('CONNECT', 'target=%s user=%s' % (audit_quote(label), getpass.getuser()))
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
            audit.event('DISCONNECT', 'target=%s' % audit_quote(label))
            audit.close()
    if rc:
        raise SystemExit(rc)
