#!/usr/bin/env python3
"""The console-style cli client, one implementation for the family: the
signed wire session, the reconnect cycle, the keepalive thread, the
readline TAB completion and the typed-command loop with the confirm guards.
Every console render prints through the one pager door (page_out) — long
replies pause at a page (the more(1) keys), piped output prints whole,
and a too-small terminal refuses the tty edition. The per-tool bins keep
their prose and their registry wiring — the pools, the candidates ladder,
the welcome greeting and (for the fake) the verb-first loop — passed here
as a spec dict to run_client() — one ladder, three modes by the
invocation shape (command words one-shot, piped stdin batch, bare tty
console). Stdlib only."""
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

try:
    import termios
    import tty
except ImportError:   # no termios: the pause falls back to line input
    termios = None
    tty = None

from common.runtime.audit import AUDIT_FORWARD_FORMATS, AuditLog, audit_quote
from common.settings.config import parse_secret, resolve_target
from common.render.human import secs
from common.settings.options import command_path_pool, match_setting_path, render_word_sections, setting_path_pool
from common.render.texts import T
from common.wire.control import CLI_MIN_HEIGHT, CLI_MIN_WIDTH
from common.wire.wiresec import sign_request, verify_reply

KEEPALIVE_ENV = 'CLI_KEEPALIVE'   # ping interval in seconds; 0 = off
PAGE_ENV = 'CLI_PAGE_SIZE'        # lines per page; 0 = off, unset/blank = auto
MORE_SUFFIX = ' ...'              # the screen cap's tail marker (a space then three dots)

_SPEC = None   # the tool's specifics — set by run_client() before anything reads it
_keepalive_s = 0.0   # the parsed CLI_KEEPALIVE interval — run_client() sets it before session() runs
_page_size = None    # the pager: None = auto (the terminal height), 0 = off, N = fixed —
                     # set by run_client() (flag > env) and overridden by the session's `page` command


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
          pool_names, banner_name, hidden_settings=(), dump_gate=()):
    """The standard console's pool/describe/welcome furniture — one shape
    family-wide (the cache's dump-gated pools, generalized): the
    completion/list pools speak the CONSOLE spellings (the rows' live/alias
    paths — the words TAB offers and `?` lists; the cli translates them to
    the flat registry names when it sends — a not-yet-live knob never
    lists, the hidden and internal rows never list) and the welcome prints
    the family banner. The session-local `page` command joins the pool as
    the cli-side pin row (beside quit/ping — described, listed, completed;
    never a registry row: the wire would lie). The dump-gated rows (`request
    dump`, `request restore` and the `dump-interval` setting, plus the
    caller's dump_gate extras — the cache's `request/dump/with-cache`) list
    only while a dump path is configured: the welcome probes `show
    dump-path` first (there is nothing to dump into otherwise — the wire
    would answer the clean err). Returns (pool_names, describe_word,
    command_pool, setting_pool, welcome)."""
    commands = tuple(commands) + ('page',)   # the local pin row: the completer and the
    commands_help = dict(commands_help)      # listing know it, the wire never does
    commands_help['page'] = T('cli.page_help')
    describe_word = make_describe_word(nodes, commands_help, spellings)
    state = {'dump': False}
    gated = ('request/dump', 'request/restore') + tuple(dump_gate)
    global _marked_namespaces, _hidden_commands
    _hidden_commands = frozenset(hidden)
    _marked_namespaces = frozenset(
        prefix for h in _hidden_commands
        for prefix in h.split('/')[:-1] if prefix not in _hidden_commands)

    def command_pool():
        """The first words the daemon offers right now: the dump-gated
        rows ride the welcome's probe (they list only while a dump path is
        configured); the internal rows (the machinery's own words) and the
        other hidden rows never list — a namespace whose members hide
        lists marked (the * rule: `*request`), so the walk-in word stays
        discoverable."""
        pool = tuple(n for n in commands
                     if n not in internal
                     and (n not in hidden or (state['dump'] and n in gated)))
        return pool + tuple(sorted(w for w in _marked_namespaces if w not in pool))

    def setting_pool():
        """The show-branch pool: the console spellings (the hidden rows
        never list; the cli translates them to the flat registry names
        when it sends; a not-yet-live knob — a restart-marked row awaiting
        its live name — never lists either; the dump-interval knob's
        console spelling rides the dump gate)."""
        return tuple(n for n in pool_names
                     if n not in hidden_settings
                     and (n not in ('dump/interval', 'dump-interval') or state['dump']))

    def welcome(sock):
        """The first-connect greeting: probe the dump state (the
        dump-gated command/setting rows pool by it), then the console's
        two fixed lines — the daemon's name and the one-line navigation
        hint."""
        reply = exchange(sock, wire('show dump-path'))
        state['dump'] = bool(reply) and reply[3:].split('=', 1)[-1].strip() not in ('', 'off', 'none')
        page_out(T('banner.welcome') % banner_name)
        page_out(T('banner.hint'))

    return describe_word, command_pool, setting_pool, welcome


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
    page_out(T('cli.daemon_exit') % (m.group(1).strip() if m else T('cli.daemon_exit_fallback')))
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


def sectioned_rows(sections, desc, hint, marked=frozenset()):
    """The listing: a blank line, then each [section] header, its entries
    padded two spaces under it — the descriptions aligned to one column across all the sections.
    The render is the wire's describe_node's own (the ? output is the
    golden master — common/settings/options.py render_word_sections); the console
    adds the hint line. `marked` carries the namespace words the * rule
    lists marked — the bare word describes and completes, the render shows
    `*name` (the wire's node help answers the same mark)."""
    rows = render_word_sections([(label, [(('*' + w) if w in marked else w, desc(w)) for w in ws]) for label, ws in sections])
    if hint:
        rows.append('    ' + hint)
    return rows


_last_listed = None   # the completer is called several times per attempt;
                      # list each distinct buffer only once
_prompt = None        # the session's prompt; the completer re-echoes it after the list
_marked_namespaces = frozenset()   # the namespace words the * rule lists marked (*request)
_hidden_commands = frozenset()     # the hidden command paths — the walk-in listings mark their segments
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


def page_env():
    """The CLI_PAGE_SIZE override, parsed once at startup: unset or blank
    rides auto (the terminal height), a non-negative integer is the fixed
    page size (0 = off), anything else is the family's one-line refusal —
    SystemExit before the connect, never the bare int() traceback."""
    raw = os.environ.get(PAGE_ENV, '')
    if not raw.strip():
        return None
    if raw.strip().isdigit():
        return int(raw)
    raise SystemExit(T('cli.page_invalid') % raw)


def terminal_size():
    """The TRUE terminal size (columns, lines): os.get_terminal_size() on
    the stdout fd, the safe (24, 80) fallback when the ioctl fails. No
    environment in the path — the startup floors and the auto page size
    measure the terminal itself (ruling 10: no env, knob or flag says
    otherwise)."""
    try:
        return os.get_terminal_size(sys.__stdout__.fileno())
    except (OSError, ValueError, AttributeError):
        return os.terminal_size((24, 80))


def cap_line(line, width):
    """The screen cap: a line wider than the terminal shortens with
    ' ...' on the end — the tail lost on screen, still on the wire and in
    the audit. A width too narrow to carry the suffix prints the line
    as-is (unreachable above the cli_min_width floor, kept for the
    fallback shape). Counted in characters: the family's console texts
    are single-width."""
    if width < len(MORE_SUFFIX) + 1 or len(line) <= width:
        return line
    return line[:width - len(MORE_SUFFIX)] + MORE_SUFFIX


def page_plan(total, size):
    """The pager's pure arithmetic — the render plan for `total` lines at
    `size` lines per page: one (start, stop, more) per page, more=True
    marking the pause after it. total <= size is one page with no pause,
    the final page never pauses, size <= 0 (off) or no lines never pause.
    page_out walks the same shape live (a return key re-steps the next
    page to one line); the regtest pins this form with no tty."""
    plan = []
    idx = 0
    while 0 < size and idx < total:
        stop = min(idx + size, total)
        plan.append((idx, stop, stop < total))
        idx = stop
    return plan


def page_out(text, *, pause='gate', stream='out'):
    """The console's ONE output door — every session-path render prints
    through here. The gate: stdin AND stdout terminals. Off a terminal
    (a pipe, a script, a captured run) the text prints whole, byte-for-byte
    as before, and no pause can ever fire. On a terminal every line wears
    the screen cap (the ' ...' shortening) and a text taller than the page
    size pauses: space = the next page, return = one more line, q = stop
    the rest (the command already ran — only the rendering stops). The
    width is re-measured per call, so a resized window is honored; the
    line count stays logical (a truncated line counts once).
    pause='never' routes but exempts the pause — the TAB listing (readline
    owns the terminal) and the stderr diagnostics (a dead session must not
    prompt). stream='err' keeps the diagnostics on stderr. The prompts
    (input(), the confirm question) and the pre-prompt blank line are not
    output and stay outside the door."""
    out = sys.stderr if stream == 'err' else sys.stdout
    lines = text.split('\n')
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        for ln in lines:
            out.write(ln + '\n')
        return
    width = terminal_size().columns
    if width >= len(MORE_SUFFIX) + 1:
        lines = [cap_line(ln, width) for ln in lines]
    if _page_size is not None and _page_size == 0:
        size = 0                       # the session's page 0: the door stays, no pause
    elif _page_size is not None:
        size = _page_size              # a fixed page (flag > env > the page command)
    else:
        size = max(6, terminal_size().lines - 2)   # auto: the pause line + the returning prompt
    if pause == 'never' or size == 0 or len(lines) <= size:
        for ln in lines:
            out.write(ln + '\n')
        return
    idx, step = 0, size
    while True:
        for ln in lines[idx:idx + step]:
            out.write(ln + '\n')
        idx += step
        if idx >= len(lines):
            return
        out.write(T('cli.more_status') % (idx, len(lines)) + '\n')
        out.flush()
        key = _read_key()
        if key == 'q':
            return
        step = 1 if key in ('\r', '\n') else size   # return = one more line, space/other = the page


def _read_key():
    """One key at the pause, the terminal in cbreak: ' ' (and any other
    key) = the next page, return = one more line, q = stop the rest.
    ^C at the pause stops the rest too — it must NOT kill the session the
    way ^C at input() does. EOF = the same stop. termios restored before
    the next prompt. No termios: the line-input fallback (an empty line =
    the next page, q = the rest)."""
    if termios is None:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            return 'q'
        return 'q' if line.strip().lower() == 'q' else ' '
    fd = sys.stdin.fileno()
    saved = None
    try:
        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    except KeyboardInterrupt:
        return 'q'
    except (OSError, ValueError):
        return 'q'
    finally:
        if saved is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return ch if ch in ('\r', '\n') else (ch or 'q')


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
        hid = tuple(sorted({h[len(base) + 1:].split('/')[0] for h in _hidden_commands
                            if h.startswith(base + '/')}))   # the namespace's hidden rows walk in marked
        pool = tuple(pool) + tuple(s for s in hid if s not in pool)
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
        return [], hint, desc, [('values', [])], frozenset()
    matches = [w for w in pool if w.startswith(text.lower())]
    sections = _sections(head, len(done), matches, values_mode, base)
    # the * rule: a namespace word carrying hidden rows lists marked — the
    # bare word completes, the listing shows the mark (the wire's node help
    # answers the same rows marked)
    marked = frozenset(w for w in {x for _, ws in sections for x in ws}
                       if ((base + '/' + w) if base else w) in _marked_namespaces
                       or ((base + '/' + w) if base else w) in _hidden_commands)
    return matches, hint, desc, sections, marked

def complete(text, state):
    """TAB completer, console-style: extend the word silently while the common
    prefix grows (a single-match return inserts it — verified libedit adds no
    space and lists nothing); once the prefix is exhausted, print the options
    OURSELVES — one candidate per line with the short descriptions (editline
    column-packs or skips its own listings) — and yield no match so the
    editor just redraws the line."""
    global _last_listed
    matches, hint, desc, sections, marked = candidates(readline.get_line_buffer())
    if state >= len(matches):
        return None
    if len(matches) > 1:
        common = os.path.commonprefix(matches)
        if len(common) > len(text):
            return common if state == 0 else None
        buf = readline.get_line_buffer()
        if state == 0 and _last_listed != buf:
            _last_listed = buf
            rows = sectioned_rows(sections, desc, hint, marked)
            # the list, a blank line, then the prompt + line again — editline
            # does NOT redraw after the completer, so we do it ourselves;
            # pause='never': readline owns the terminal mid-completion
            page_out('\n' + '\n'.join(rows) + '\n', pause='never')
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
    matches, hint, desc, sections, marked = candidates(buf)
    rows = sectioned_rows(sections, desc, hint, marked)
    if not rows:
        page_out(T('cli.invalid_input'))
        return
    page_out('\n'.join(rows))


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
    page_out(T('cli.reconnecting') % args.reconnect)
    for attempt in range(1, args.reconnect + 1):
        try:
            s = connect_once(addr, is_unix, args.timeout)
        except OSError as e:
            page_out(T('cli.reconnect_attempt_failed') % (attempt, e))
            if audit:
                audit.event('RECONNECT', 'attempt=%d total=%d status=failed error=%s'
                            % (attempt, args.reconnect, audit_quote(e)))
            if attempt < args.reconnect:
                page_out(T('cli.reconnecting_in')
                         % (secs(args.reconnect_wait), attempt + 1, args.reconnect))
                time.sleep(args.reconnect_wait)
            continue
        if audit:
            audit.event('RECONNECT', 'attempt=%d total=%d status=ok' % (attempt, args.reconnect))
        page_out(T('cli.reconnected') % _SPEC['label'])
        return s
    page_out(T('cli.reconnect_failed'))
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
                        page_out(T('shared.auth_failed') % (reply or 'no reply'), stream='err', pause='never')
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
                    page_out(T('cli.connection_lost'), stream='err', pause='never')
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
        page_out('\n'.join([first.split(' ', 1)[1]] + rest))
    elif first.startswith('err '):
        page_out('\n'.join([T('shared.error_face') % first.split(' ', 1)[1]] + rest))
    elif first.startswith('note '):
        page_out('\n'.join([T('shared.plain_face') % first.split(' ', 1)[1]] + rest))
    elif first.startswith('bye'):
        page_out('\n'.join([T('shared.plain_face') % first] + rest))
    else:
        page_out(text)                 # an unheaded reply (the fake's own shapes) prints as-is


def typed_loop(sock, prompt, audit=None):
    """The typed-command loop. A dead connection (an exchange that raises
    ConnectionLost) surfaces out of the loop so the session can run its
    reconnect cycle; the clean exits return. The tool's spec tunes the
    renders: silent_ok(low) replies confirm silently, render(low, reply)
    prints a special table itself. Every reply prints through the pager
    door; the local `page` command tunes the session's page size here —
    never sent."""
    global _page_size
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
            page_out(T('cli.pong'))
            continue
        if low == 'page' or low.startswith('page '):
            # the session-local pager command — intercepted BEFORE the wire:
            # the daemon never learns of it, the registries have no row
            if audit:
                audit.command(cmd, 'local')
            arg = cmd[5:].strip() if len(cmd) > 5 else ''
            if not arg:
                pass                    # bare `page`: the state line below
            elif arg.lower() == 'auto':
                _page_size = None       # follow the terminal again
            elif arg.isdigit():
                _page_size = int(arg)   # 0 = off, N = fixed
            else:
                display('err ' + T('cli.page_bad') % arg)
                continue
            if _page_size is None:
                page_out(T('cli.page_state') % ('%d (auto)' % max(6, terminal_size().lines - 2)))
            elif _page_size == 0:
                page_out(T('cli.page_state') % '%d (off)' % _page_size)
            else:
                page_out(T('cli.page_state') % str(_page_size))
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
                page_out(T('shared.plain_face') % reply.split(' ', 1)[1])   # the startup-only knob: the note type, or the refused secret's fail — a note face, not a verdict
            elif reply.startswith('ok'):
                page_out(T('cli.changed'))   # the one ok face keeping the marker
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
                page_out(rest)             # the report rows (the command already said the name)
            elif '\n' not in body and '=' in body:
                page_out(body.split('=', 1)[1])   # show <setting>: the bare value
            else:
                page_out(body)
        elif low == 'inspect' and reply.startswith('ok inspect\n'):
            page_out('\n'.join(reply.splitlines()[1:]))   # the dump itself is the answer
        else:
            display(reply)


def confirm_shutdown(sock):
    """console-style [confirm]: RETURN or y/yes proceeds, anything else aborts."""
    try:
        ans = input(T('cli.confirm_shutdown'))
    except (EOFError, KeyboardInterrupt):
        print()
        page_out(T('cli.aborted'))
        return False
    if ans.strip().lower() not in ('', 'y', 'yes'):
        page_out(T('cli.aborted'))
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


def raw_out(reply):
    """The one-shot/batch face: the raw verdict head kept ('ok upstream=…',
    '% error: …', '% note') — the scriptable contract the healthchecks and
    the scripts read. Never paged, never capped: the pager door is the tty
    console's; this is the byte contract (ruling 3)."""
    if reply.startswith('err '):
        sys.stdout.write(T('shared.error_face') % reply[4:] + '\n')
    elif reply.startswith('note '):
        sys.stdout.write(T('shared.plain_face') % reply[5:] + '\n')
    else:
        sys.stdout.write(reply + '\n')
    sys.stdout.flush()


def _scripted(s, addr, commands, token):
    """The one-shot/batch command loop: the token handshake, each translated
    line through the one exchange, the raw faces, the daemon-exit bye
    short-circuit. A lost wire is the one-line refusal, rc 1 (the ctl's
    old fail-print folds here); a fail REPLY is not an error — rc 0, the
    landed contract. The CONNECT/DISCONNECT audit is the caller's. Returns
    the rc."""
    global _token, _require_reply_mac
    _token = token
    try:
        if token and not isinstance(addr, str):
            reply = exchange(s, json.dumps({'cmd': 'auth', 'token': token}, ensure_ascii=False))
            if not reply or not reply.startswith('ok'):
                page_out(T('shared.auth_failed') % (reply or 'no reply'), stream='err', pause='never')
                return 1
            _require_reply_mac = True   # the handshake holds: unsigned replies are fatal
        for cmd in commands:
            try:
                reply = exchange(s, wire(translate(cmd, _SPEC['spellings'])))
            except DaemonExit as e:
                page_out(T('ctl.daemon_exit_done') % str(e)[4:].replace('daemon-exit', 'daemon exit', 1))
                return 0
            if reply is None:
                page_out(T('cli.connection_lost'), stream='err', pause='never')
                return 1
            raw_out(reply)
    except ConnectionLost as e:
        page_out(str(e), stream='err', pause='never')
        return 1
    except OSError as e:
        page_out(T('cli.connection_failed') + ': %s' % e, stream='err', pause='never')
        return 1
    return 0


def run_client(spec):
    """The whole client ladder — ONE implementation, THREE modes by the
    invocation shape: command words = one-shot (the raw verdict head, rc
    0/1/2), bare with piped stdin = batch (the script lines run in order,
    the same raw faces), bare on a terminal = the console session (the
    banner, TAB/?, the keepalive thread, the reconnect cycle, the pager).
    The parser is the union — the console-only --reconnect/--page-size say
    so in their help and ride inert in the scripted modes; one exchange,
    one target/token/audit copy where two lived. The startup floors guard
    the console edition only."""
    global _SPEC, _keepalive_s, _page_size
    _SPEC = spec
    p = argparse.ArgumentParser(description='the client for the %s control server (TCP or unix socket): command words one-shot, piped stdin batch, bare terminal the console.' % spec['daemon_label'])
    p.add_argument('--control-port', default=None, help='control server target: unix socket path or TCP port on 127.0.0.1, auto-detected (env CTL when unset) — same flag as %s' % spec['self_note'])
    p.add_argument('command', nargs='*', help='one-shot control command, %s (bare: piped stdin batch-runs a script, a terminal opens the console)' % spec['command_help'])
    p.add_argument('--timeout', type=float, default=spec['timeout_s'], help='socket timeout in seconds')
    p.add_argument('--reconnect', type=int, default=spec['reconnect'], help='console only: when the connection dies (an unanswered ping, a reset, a timeout), retry this many times before giving up; 0 = off')
    p.add_argument('--reconnect-wait', type=float, default=spec['reconnect_wait'], help='console only: seconds between the reconnect attempts')
    p.add_argument('--control-token', default=None, help='control auth token for TCP (env CONTROL_TOKEN); a file:<path> value reads the first line of an owner-only 0600 file')
    p.add_argument('--audit-log', default=None, help="audit trail: a file path, - for stdout, or none for no local file (the forward carries the trail); the XDG state home when unset")
    p.add_argument('--audit-forward', default='none', metavar='TARGET',
                   help='also forward every audit line: none, syslog, syslog:/path, udp://host[:port] or tcp://host[:port] (the off-box copy, docs/SECURITY.md)')
    p.add_argument('--audit-forward-format', default='rfc5424', choices=AUDIT_FORWARD_FORMATS,
                   help="the remote forward's envelope: rfc5424 (the default) or cef — the local syslog forms keep the verbatim send")
    p.add_argument('--audit-max-mb', type=float, default=spec['audit_max_mb'], help='rotate the audit log at this size, 0 = off')
    p.add_argument('--audit-files', type=int, default=spec['audit_files'], help='rotated audit backups to keep')
    p.add_argument('--no-audit-log', action='store_true', help='disable the audit trail')
    p.add_argument('--page-size', type=int, default=None, metavar='N',
                   help='console pager: N lines per page (0 = off, empty = the terminal height; env CLI_PAGE_SIZE)')
    p.add_argument('--man', action='store_true', help='print the man page (roff) to stdout and exit (%s --man | man -l -)' % spec['cli_name'])
    args = p.parse_args()
    if args.man:
        sys.stdout.write(spec['cli_page'](p))
        raise SystemExit(0)

    _keepalive_s = keepalive_env(spec['keepalive_s'])
    _page_size = args.page_size if args.page_size is not None else page_env()

    # the mode decision — before the token/target ladder: a bare+tty
    # invocation is the console edition, bare + piped stdin batch-runs the
    # script, command words one-shot. The console's startup floors refuse
    # (one line, rc 1, never a traceback) BEFORE the connect; the
    # terminal's own size is the only say (no env, knob or flag sets or
    # waives one); the scripted modes never check.
    console = not args.command and sys.stdin.isatty()
    if console:
        size = terminal_size()
        if size.lines < CLI_MIN_HEIGHT:
            raise SystemExit(T('cli.min_height') % (size.lines, CLI_MIN_HEIGHT))
        if size.columns < CLI_MIN_WIDTH:
            raise SystemExit(T('cli.min_width') % (size.columns, CLI_MIN_WIDTH))

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
        page_out(T('shared.cannot_reach') % (label, e), stream='err', pause='never')
        raise SystemExit(1)
    if audit:
        audit.event('CONNECT', 'target=%s user=%s' % (audit_quote(label), getpass.getuser()))

    if not console:
        if args.command:   # one-shot: the words are the script
            commands = [' '.join(args.command)]
        else:              # batch: the piped script — comments and blanks stay comments
            commands = [line.strip() for line in sys.stdin
                        if line.strip() and not line.strip().startswith('#')]
            if not commands:
                p.error('no commands on stdin')
        try:
            rc = _scripted(s, addr, commands, token)
        finally:
            if audit:
                audit.event('DISCONNECT', 'target=%s' % audit_quote(label))
                audit.close()
            s.close()
        if rc:
            raise SystemExit(rc)
        return

    if readline:
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
