#!/usr/bin/env python3
"""console-style interactive CLI for the fake inverter's control server.

A session front-end on top of the JSON-lines control socket: prompt with
the connected port, TAB completion and `?` in every position (with the short
descriptions from the shared command registry), `set` commands print only
the confirmation (never the status tail), `show <setting>` prints the bare
value, `show status` the key=value report, and `shutdown` asks before it
stops the fake.

The session itself (connect/disconnect, the local commands like quit and
the aborted shutdown) is appended to an audit log (default audit.log in
the current directory, prefix CLI; --audit-log to rename, --no-audit-log
to turn it off); the commands themselves are audited by the server (the
peer is on its side) — ping/pong keepalives are never logged. When the
connection dies mid-session (an unanswered ping, the server gone), the
CLI retries: --reconnect attempts, --reconnect-wait seconds apart.

  python3 modbus-fake-cli.py --control-port 15599
  CTL=15599 python3 modbus-fake-cli.py

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common import cli
from common.options import setting_path_pool
from lib.man import cli_page
from lib.options import ALIAS_NAMES, COMMANDS, COMMAND_GROUPS, COMMAND_HELP, COMMAND_HIDDEN, HIDDEN_SETTINGS, LIVE_SETTINGS, SETTING_BY_NAME, SETTING_NAMES, SHOW_LIVES, NODE_BY_NAME, describe_value
from lib.paths import resolve_control_target
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_KEEPALIVE_S, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, \
    CLI_TIMEOUT_S

HELP_PINS = (
    ('help <setting>', "the setting's description"),
    ('?', 'this help'),
)
HELP = cli.help_text(COMMAND_HELP, COMMAND_GROUPS, COMMAND_HIDDEN, HELP_PINS)

LIVE_POOL = tuple(n for n in SETTING_NAMES + ALIAS_NAMES   # the show branch's pool: the live-named
                  if n not in HIDDEN_SETTINGS              # settings + the alias spellings; a
                  and (n in LIVE_SETTINGS or n in ALIAS_NAMES))   # not-yet-live knob never lists


def describe_word(w):
    """The short description from the shared registry, if there is one."""
    if w in SETTING_BY_NAME:
        return SETTING_BY_NAME[w].help
    if w in COMMAND_HELP:
        return COMMAND_HELP[w]
    if w == 'register':
        return 'write a raw register (the same overlay as the FC16 writes)'
    if w == 'inspect':
        return 'one pretty dump of everything (the status, the machines, the overlay)'
    walk = next((s for k, s in SETTING_BY_NAME.items() if k.startswith(w + '/')), None)
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
        names = tuple(n for n in SETTING_NAMES + ALIAS_NAMES
                      if n not in HIDDEN_SETTINGS and n not in SHOW_LIVES
                      and (n in LIVE_SETTINGS or n in ALIAS_NAMES)) \
            + (('register',) if head == 'set' else ())
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
            pool, hint = tuple(s.values), s.hint
            desc = (lambda w, _n=s.name: describe_value(_n, w))
        else:
            base = '/'.join(w.lower() for w in done[1:])   # the path spelled so far — a segment's
            pool, hint = segs, None                        # description lives on the full live name
            desc = lambda w, base=base: describe_word((base + '/' if base else '') + w)
    elif head == 'show':
        s, segs = setting_path_pool(done[1:], LIVE_POOL, SETTING_BY_NAME)
        base = '/'.join(w.lower() for w in done[1:])   # a segment's description lives on the full live name
        if s is None:   # the hidden knobs never walk, but the typed whole path still describes (the wire's help answers it)
            s = SETTING_BY_NAME.get('/'.join(w.lower() for w in done[1:]))
        if s is not None:
            _, cont = setting_path_pool(done[1:] + [''], LIVE_POOL, SETTING_BY_NAME)
            if not cont:
                return [], '%s - %s' % (s.name, s.help), None, []   # the path is whole and childless; ? describes the report
            pool, hint = cont, None   # a namespace too: the report answers on Enter, TAB walks on
        else:
            pool, hint = segs, None
        desc = lambda w, base=base: describe_word((base + '/' if base else '') + w)
    else:
        return [], None, None, []
    matches = sorted(w for w in pool if w.startswith(text.lower()))
    return matches, hint, desc, cli._sections(head, len(done), matches, values_mode,
                                              base='/'.join(w.lower() for w in done[1:]))


def welcome(sock):
    """The first-connect greeting: probe the status and introduce the device —
    the profile, how long the fake has been running, the grid/clock/battery
    state, and the one-line navigation hint."""
    reply = cli.exchange(sock, cli.wire('show status'))
    if not reply or not reply.startswith('ok status'):
        return
    st = dict(row.split('=', 1) for row in reply.split('\n')[1:] if '=' in row)
    print('% Welcome to the Fake Inverter console')
    print('%%   %s' % st.get('profile', 'unknown profile'))
    print('%   running for %s | %s clock | %s V grid | battery %s'
          % (st.get('uptime', '?'), st.get('timezone', 'utc'), st.get('grid_voltage', '230'),
             ('on (%s W, %s %%SoC)' % (st.get('battery', '?'), st.get('soc', '?')))
             if 'soc' in st else 'off'))
    print('%   TAB completes, ? lists the commands, help <setting> explains one, quit leaves')


_DONE = object()    # a local command handled inside _dispatch: leave the loop


def _loop(sock, prompt, audit=None):
    """The typed-command loop. A dead connection (an exchange that returns
    None or raises ConnectionLost) surfaces as ConnectionLost so the session
    can run its reconnect cycle; the clean exits return."""
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
        try:
            reply = _dispatch(sock, cmd, audit)
        except cli.ConnectionLost:
            raise
        if reply is _DONE:
            return
        if reply is None:
            raise cli.ConnectionLost('the control connection closed without a bye')
        if not reply:
            continue                 # a local command: _dispatch already printed
        if cmd.lower().startswith(('set ', 'unset ')) and 'restart required' in reply:
            print('% ' + reply.split(' ', 1)[1])   # the startup-only note: a note, not a verdict
        elif cmd.lower().startswith(('set ', 'unset ')) and reply.startswith('ok'):
            print('% ok')           # set/unset confirm silently
        elif cmd.lower() == 'show version' and reply.startswith('ok fake-inverter'):
            print(reply.split(' ', 1)[1])   # the bare version line
        elif cmd.lower().startswith('show ') and reply.startswith('ok ') and '=' in reply and '\n' not in reply:
            print(reply.split(' ', 1)[1].split('=', 1)[1])   # the bare value
        elif cmd.lower().startswith('show ') and reply.startswith('ok ') and '\n' in reply:
            head, _, rest = reply[3:].partition('\n')
            if ' ' not in head and '=' not in head:
                print(rest)         # the report rows (the command already said the name)
            else:
                cli.display(reply)
        elif cmd.lower() == 'inspect' and reply.startswith('ok inspect\n'):
            print('\n'.join(reply.splitlines()[1:]))   # the dump itself is the answer
        else:
            cli.display(reply)


def _dispatch(sock, cmd, audit=None):
    """One typed command: the local ones handled here, the wire ones sent to
    the fake. Returns the reply text, _DONE (leave the loop) or None (the
    connection is gone)."""
    low = cmd.lower()
    if low == 'ping':               # local: the wire pings belong to the keepalive thread
        print('% ok pong')
        return ''
    if low in ('quit', 'exit', 'logout'):
        if audit:
            audit.command(cmd, 'local')
        return _DONE
    if low in ('?', 'help'):
        if audit:
            audit.command(cmd, 'local')
        print(HELP)
        return ''
    if low.split()[0] == 'help' and len(low.split()) > 1:
        reply = cli.exchange(sock, cli.wire(cmd))     # help <setting>: the registry answer
        if reply is None:
            return None
        if reply.startswith('ok '):
            print(reply.split(' ', 1)[1])   # the help body — the answer itself
        else:
            cli.display(reply)
        return ''   # printed here — the loop must not print the verdict again
    if low.endswith('?'):
        if audit:
            audit.command(cmd, 'local')
        cli.print_options(low[:-1])
        return ''
    if low == 'shutdown':
        if not cli.confirm_shutdown(sock):
            if audit:
                audit.command('shutdown', 'aborted')
            return ''
        if audit:
            audit.command('shutdown', 'ok')
        return _DONE
    return cli.exchange(sock, cli.wire(cmd))


SPEC = dict(label='the fake inverter', daemon_label='fake inverter control server',
            cli_name='modbus-fake-cli', app='fake-inverter', self_note='the fake itself',
            socket_default='/tmp/fake-inverter-5502.socket',
            command_help='e.g. set pv 2500, set scenario noon, show status, reset, shutdown',
            prompt_word='fake-inverter', timeout_s=CLI_TIMEOUT_S, keepalive_s=CLI_KEEPALIVE_S,
            reconnect=CLI_RECONNECT, reconnect_wait=CLI_RECONNECT_WAIT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES,
            resolve=resolve_control_target, settings=SETTING_BY_NAME, nodes=NODE_BY_NAME,
            help=HELP, welcome=welcome, candidates=candidates, loop=_loop,
            silent_ok=None, render=None, cli_page=cli_page)

if __name__ == '__main__':
    cli.run_cli(SPEC)
