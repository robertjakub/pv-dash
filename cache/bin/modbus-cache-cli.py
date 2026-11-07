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

  python3 modbus-cache-cli.py --control-port 15509
  CTL=15509 python3 modbus-cache-cli.py

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common import cli
from common.options import setting_path_pool
from lib.config import resolve_control_target
from lib.man import cli_page
from lib.options import ALIAS_NAMES, COMMANDS, COMMAND_GROUPS, COMMAND_HELP, COMMAND_HIDDEN, HIDDEN_SETTINGS, LIVE_SETTINGS, NODE_BY_NAME, SETTING_BY_NAME, SETTING_NAMES, SHOW_LIVES
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_KEEPALIVE_S, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S

SESSION = {'probed': False, 'dump': False}

HELP_PINS = (
    ('help <setting>', "the setting's description"),
    ('?', 'this help'),
)
HELP = cli.help_text(COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN, HELP_PINS)


def command_pool():
    """The first words the daemon offers right now (the hidden rows never list)."""
    if SESSION['dump']:
        return tuple(n for n in COMMANDS if n not in COMMAND_HIDDEN)
    return tuple(n for n in COMMANDS if n != 'request' and n not in COMMAND_HIDDEN)


def setting_pool():
    """The words the daemon offers right now (the hidden rows never list;
    an aliased row completes and lists under its second spelling too;
    a not-yet-live knob — a restart-marked row awaiting its live name —
    never lists either)."""
    return tuple(n for n in SETTING_NAMES + ALIAS_NAMES
                 if n not in HIDDEN_SETTINGS and (n in LIVE_SETTINGS or n in ALIAS_NAMES)
                 and (n != 'dump-interval' or SESSION['dump']))


def settable_pool():
    """The set/unset tunables: the live knobs only — the show reports
    (`connections`, `config`, ...) answer `show`, no `set` takes them."""
    return tuple(n for n in setting_pool() if n not in SHOW_LIVES)


def describe_word(w):
    """The short description from the registry, if there is one."""
    if w in NODE_BY_NAME:
        return NODE_BY_NAME[w].setting_help or NODE_BY_NAME[w].help
    return COMMAND_HELP.get(w) or setting_help(w)


def setting_help(name):
    s = SETTING_BY_NAME.get(name)
    if s:
        return s.help
    walk = next((s for k, s in SETTING_BY_NAME.items() if k.startswith(name + '/')), None)
    return walk.help if walk else None   # a namespace walk-on (an alias's first segment)


def candidates(buf):
    """Valid next words for the buffer being completed or questioned:
    (matches, hint about the following word, describer of each word, the
    listing groups — the settings under their registry groups
    (ungrouped rows bare, no header), the values of one setting
    ([values])). A live setting's name may be a '/'-path
    (`inverter/profile`): set/unset/show spell it as words — the completion
    offers the next segment until the path is whole, then the values."""
    end_space = buf.endswith(' ')
    parts = buf.split()
    text = '' if end_space else (parts[-1] if parts else '')
    done = parts if end_space else parts[:-1]
    head = done[0].lower() if done else ''
    values_mode = False
    if not done:
        pool, hint, desc = command_pool(), None, describe_word
    elif head in ('set', 'unset'):
        names = settable_pool()
        by = {n: SETTING_BY_NAME[n] for n in names if n in SETTING_BY_NAME}   # the exact match obeys the pool:
        s, segs = setting_path_pool(done[1:], names, by)                      # a show report never offers a value
        if s is None:   # the hidden knobs (the secrets) never walk, but the typed whole path still describes
            s = SETTING_BY_NAME.get('/'.join(w.lower() for w in done[1:]))
            if s is not None and s.name not in LIVE_SETTINGS - SHOW_LIVES:
                s = None   # a show report never offers a value
        if s is not None:
            if head == 'unset':
                return [], '%s - %s' % (s.name, s.help), None, []   # the path is whole; unset takes no value — ? describes it
            values_mode = True
            pool, hint = tuple(s.values), s.value_shape
            desc = lambda w, s=s: s.value_help.get(w, s.value_help.get(w.lower(), '')) or None
        else:
            base = '/'.join(w.lower() for w in done[1:])   # the path spelled so far — a segment's
            pool, hint = segs, None                        # description lives on the full live name
            desc = lambda w, base=base: describe_word((base + '/' if base else '') + w)
    elif head == 'request' and len(done) == 1:
        pool, hint, desc = (('dump', 'restore') if SESSION['dump'] else ()), None, describe_word
    elif head == 'show':
        s, segs = setting_path_pool(done[1:], setting_pool(), SETTING_BY_NAME)
        base = '/'.join(w.lower() for w in done[1:])   # a segment's description lives on the full live name
        if s is None:   # the hidden knobs never walk, but the typed whole path still describes (the wire's help answers it)
            s = SETTING_BY_NAME.get('/'.join(w.lower() for w in done[1:]))
        if s is not None:
            _, cont = setting_path_pool(done[1:] + [''], setting_pool(), SETTING_BY_NAME)
            if not cont:
                return [], '%s - %s' % (s.name, s.help), None, []   # the path is whole and childless; ? describes the report
            pool, hint = cont, None   # a namespace too: the report answers on Enter, TAB walks on
        else:
            pool, hint = segs, None
        desc = lambda w, base=base: describe_word((base + '/' if base else '') + w)
    elif head == 'clear' and len(done) == 1:
        pool, hint, desc = ('cache',), None, describe_word
    else:
        return [], None, None, []
    if pool is None:                      # a value shape with no completable words
        return [], hint, desc, [('values', [])]
    matches = [w for w in pool if w.startswith(text.lower())]
    return matches, hint, desc, cli._sections(head, len(done), matches, values_mode,
                                              base='/'.join(w.lower() for w in done[1:]))


def welcome(sock):
    """The first-connect greeting: probe the status and introduce the proxy —
    the upstream, the poll health, how long it has been running — and the
    one-line navigation hint."""
    reply = cli.exchange(sock, cli.wire('show status'))
    if not reply or not reply.startswith('ok status'):
        return
    st = {}
    for line in reply.splitlines()[1:]:          # the key=value report rows
        if '=' in line:
            k, v = line.split('=', 1)
            st[k] = v
    SESSION['probed'] = True
    SESSION['dump'] = st.get('dump', 'off') != 'off'
    print('% Welcome to the modbus-cache console')
    print('%%   %s upstream | poll %s, last poll %s | running for %s | %s client(s)'
          % (st.get('upstream', '?'), st.get('poll', '?'), st.get('last_poll', '?'),
             st.get('uptime', '?'), st.get('clients', '?')))
    print('%   TAB completes, ? lists the commands, quit leaves')


def _render_special(low, reply):
    """The cache's special render: the per-entry cache-all table prints bare
    (the loop's shared branches cover the rest)."""
    if low == 'show cache-all' and reply.startswith('ok cache-all\n'):
        print('\n'.join(reply.splitlines()[1:]))   # the per-entry table itself
        return True
    return False


SPEC = dict(label='the cache proxy', daemon_label='modbus-cache control server',
            cli_name='modbus-cache-cli', app='modbus-cache', self_note='the proxy itself',
            socket_default='/tmp/modbus-cache-15502.socket',
            command_help='e.g. inspect, show status, show cache, clear cache, restart, shutdown',
            prompt_word='cache', timeout_s=CLI_TIMEOUT_S, keepalive_s=CLI_KEEPALIVE_S,
            reconnect=CLI_RECONNECT, reconnect_wait=CLI_RECONNECT_WAIT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES,
            resolve=resolve_control_target, settings=SETTING_BY_NAME, nodes=NODE_BY_NAME,
            help=HELP, welcome=welcome, candidates=candidates, loop=cli.typed_loop,
            silent_ok=lambda low: low.startswith(('clear ', 'restart')),
            render=_render_special, cli_page=cli_page)

if __name__ == '__main__':
    cli.run_cli(SPEC)
