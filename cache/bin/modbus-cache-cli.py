#!/usr/bin/env python3
"""console-style interactive CLI for modbus-cache's JSON-lines control server.

A session front-end on top of the control socket: prompt with the connected
port, TAB completion and `?` in every position, `show` commands print the
state lines, `request flush cache` and `request restart` confirm with a
plain `ok`, and `shutdown` asks before it stops the proxy.

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

from common.wire import cli
from common.render.texts import T
from lib.config import DEFAULT_CONTROL_SOCKET
from lib.man import cli_page
from lib.options import COMMANDS, COMMAND_HELP, COMMAND_HIDDEN, COMMAND_INTERNAL, HIDDEN_SETTINGS, NODE_BY_NAME, POOL_NAMES, SETTING_SPELLINGS, SHOW_LIVES
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_KEEPALIVE_S, CLI_MAX_LINE_BYTES_S, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S

SESSION = {'dump': False}


DUMP_GATED = ('request/dump', 'request/dump/with-cache', 'request/restore')


def command_pool():
    """The first words the daemon offers right now: the dump node's request
    children ride the dump gate (they list only while the dump node is on);
    the internal rows (the machinery's own words) and the other hidden
    rows never list."""
    return tuple(n for n in COMMANDS
                 if n not in COMMAND_INTERNAL
                 and (n not in COMMAND_HIDDEN or (SESSION['dump'] and n in DUMP_GATED)))


def setting_pool():
    """The words the daemon offers right now (the hidden rows never list;
    the console spellings list — the cli translates them to the flat
    registry names when it sends; a not-yet-live knob — a restart-marked
    row awaiting its live name — never lists either)."""
    return tuple(n for n in POOL_NAMES
                 if n not in HIDDEN_SETTINGS
                 and (n != 'dump-interval' or SESSION['dump']))


describe_word = cli.make_describe_word(NODE_BY_NAME, COMMAND_HELP, SETTING_SPELLINGS)


def welcome(sock):
    """The first-connect greeting: probe the dump state (the dump-gated
    command/setting rows pool by it) and print the navigation hint."""
    reply = cli.exchange(sock, cli.wire('show dump-path'))
    val = reply[3:].split('=', 1)[-1].strip() if reply and reply.startswith('ok ') else ''
    SESSION['dump'] = val not in ('', 'off', 'none')
    print(T('banner.welcome') % 'modbus-cache')
    print(T('banner.hint'))


def _render_special(low, reply):
    """The cache's special render: the per-entry cache-all table prints bare
    (the loop's shared branches cover the rest)."""
    if low == 'show cache-all' and reply.startswith('ok cache-all\n'):
        print('\n'.join(reply.splitlines()[1:]))   # the per-entry table itself
        return True
    return False


SPEC = dict(label='the cache proxy', daemon_label='modbus-cache control server',
            cli_name='modbus-cache-cli', app='modbus-cache', self_note='the proxy itself',
            command_help='e.g. inspect, show config, show cache, request flush cache, request reload-config, request restart, shutdown',
            prompt_word='cache', timeout_s=CLI_TIMEOUT_S, keepalive_s=CLI_KEEPALIVE_S,
            reconnect=CLI_RECONNECT, reconnect_wait=CLI_RECONNECT_WAIT_S,
            max_line_bytes=CLI_MAX_LINE_BYTES_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES,
            ctl_socket=DEFAULT_CONTROL_SOCKET, spellings=SETTING_SPELLINGS, nodes=NODE_BY_NAME,
            show_lives=SHOW_LIVES,
            command_pool=command_pool, setting_pool=setting_pool,
            describe=describe_word,
            welcome=welcome, loop=cli.typed_loop,
            silent_ok=lambda low: low.startswith(('request flush', 'request restart')),
            render=_render_special, cli_page=cli_page)

if __name__ == '__main__':
    cli.run_cli(SPEC)
