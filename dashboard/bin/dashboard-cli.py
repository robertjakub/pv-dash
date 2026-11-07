#!/usr/bin/env python3
"""console-style interactive CLI for the dashboard's JSON-lines control server.

A session front-end on top of the control socket: prompt with the connected
port, TAB completion and `?` in every position (with the short descriptions
from the shared command registry), `set` commands print only the
confirmation, `show <setting>` prints the bare value,
`show status` the key=value report, and `shutdown` asks
before it stops the server.

The session itself (connect/disconnect, the local commands like quit and
the aborted shutdown) is appended to an audit log (default in the XDG state
home, prefix CLI; --audit-log to rename, --no-audit-log to turn it off);
the commands themselves are audited by the server (the peer is on its
side) — ping/pong keepalives are never logged. When the connection dies
mid-session (an unanswered ping, the server gone), the CLI retries:
--reconnect attempts, --reconnect-wait seconds apart. With a token
configured the wire is HMAC-signed (the full sha256 of each frame,
common/wiresec.py): the console signs every command and verifies every
reply.

  python3 dashboard-cli.py --control-port 15598
  CTL=15598 python3 dashboard-cli.py

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

HELP_PINS = (
    ('help <setting>', "the setting's description"),
    ('?', 'this help'),
)
HELP = cli.help_text(COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN, HELP_PINS)


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
        pool, hint, desc = tuple(n for n in COMMANDS if n not in COMMAND_HIDDEN), None, describe_word
    elif head in ('set', 'unset'):
        names = tuple(n for n in POOL_NAMES if n not in SHOW_LIVES)   # the show reports answer show, never set/unset
        by = {n: SETTING_BY_NAME[n] for n in names if n in SETTING_BY_NAME}
        s, segs = setting_path_pool(done[1:], names, by)
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
        pool, hint, desc = ('dump', 'reload', 'restore'), None, describe_word
    elif head == 'show':
        s, segs = setting_path_pool(done[1:], POOL_NAMES, SETTING_BY_NAME)
        base = '/'.join(w.lower() for w in done[1:])   # a segment's description lives on the full live name
        if s is None:   # the hidden knobs never walk, but the typed whole path still describes (the wire's help answers it)
            s = SETTING_BY_NAME.get('/'.join(w.lower() for w in done[1:]))
        if s is not None:
            _, cont = setting_path_pool(done[1:] + [''], POOL_NAMES, SETTING_BY_NAME)
            if not cont:
                return [], '%s - %s' % (s.name, s.help), None, []   # the path is whole and childless; ? describes the report
            pool, hint = cont, None   # a namespace too: the report answers on Enter, TAB walks on
        else:
            pool, hint = segs, None
        desc = lambda w, base=base: describe_word((base + '/' if base else '') + w)
    else:
        return [], None, None, []
    if pool is None:                      # a value shape with no completable words
        return [], hint, desc, [('values', [])]
    matches = [w for w in pool if w.startswith(text.lower())]
    return matches, hint, desc, cli._sections(head, len(done), matches, values_mode,
                                              base='/'.join(w.lower() for w in done[1:]))


def welcome(sock):
    """The first-connect greeting: probe the status and introduce the
    dashboard — the upstream, its health, the clients, how long it has been
    running — and the one-line navigation hint."""
    reply = cli.exchange(sock, cli.wire('show status'))
    if not reply or not reply.startswith('ok status'):
        return
    st = {}
    for line in reply.splitlines()[1:]:          # the key=value report rows
        if '=' in line:
            k, v = line.split('=', 1)
            st[k] = v
    print('% Welcome to the dashboard console')
    print('%%   %s upstream (%s) | %s client(s) | running for %s'
          % (st.get('upstream', '?'), st.get('upstream_ok', '?'), st.get('clients', '?'),
             st.get('uptime', '?')))
    print('%   TAB completes, ? lists the commands, quit leaves')


POOL_NAMES = tuple(n for n in SETTING_NAMES + ALIAS_NAMES if n not in HIDDEN_SETTINGS
                   and (n in LIVE_SETTINGS or n in ALIAS_NAMES))   # a not-yet-live knob never lists

SPEC = dict(label='the dashboard', daemon_label='dashboard control server',
            cli_name='dashboard-cli', app='dashboard', self_note='the server itself',
            socket_default='/tmp/dashboard-8080.socket',
            command_help='e.g. inspect, show status, set battery on, request reload, shutdown',
            prompt_word='dashboard', timeout_s=CLI_TIMEOUT_S, keepalive_s=CLI_KEEPALIVE_S,
            reconnect=CLI_RECONNECT, reconnect_wait=CLI_RECONNECT_WAIT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES,
            resolve=resolve_control_target, settings=SETTING_BY_NAME, nodes=NODE_BY_NAME,
            help=HELP, welcome=welcome, candidates=candidates, loop=cli.typed_loop,
            silent_ok=lambda low: low == 'request reload',
            render=None, cli_page=cli_page)

if __name__ == '__main__':
    cli.run_cli(SPEC)
