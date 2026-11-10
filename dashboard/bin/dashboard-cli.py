#!/usr/bin/env python3
"""console-style interactive CLI for the dashboard's JSON-lines control server.

A session front-end on top of the control socket: prompt with the connected
port, TAB completion and `?` in every position, `show` commands print the
state lines, `set` commands print only the confirmation, and `shutdown`
asks before it stops the server.

The session itself (connect/disconnect, the local commands like quit and
the aborted shutdown) is appended to an audit log (default in the XDG state
home, prefix CLI; --audit-log to rename, --no-audit-log to turn it off);
the commands themselves are audited by the server (the peer is on its
side) — ping/pong keepalives are never logged. When the connection dies
mid-session (an unanswered ping, the server gone), the CLI retries:
--reconnect attempts, --reconnect-wait seconds apart.

  python3 dashboard-cli.py --control-port 15598
  CTL=15598 python3 dashboard-cli.py

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
from lib.options import ALIAS_NAMES, COMMANDS, COMMAND_HELP, COMMAND_HIDDEN, COMMAND_INTERNAL, HIDDEN_SETTINGS, LIVE_SETTINGS, NODE_BY_NAME, SETTING_BY_NAME, SETTING_NAMES, SHOW_LIVES
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_KEEPALIVE_S, CLI_MAX_LINE_BYTES_S, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S


POOL_NAMES = tuple(n for n in SETTING_NAMES + ALIAS_NAMES if n not in HIDDEN_SETTINGS
                   and (n in LIVE_SETTINGS or n in ALIAS_NAMES))   # a not-yet-live knob never lists

describe_word = cli.make_describe_word(NODE_BY_NAME, COMMAND_HELP, SETTING_BY_NAME)


def command_pool():
    """The first words the daemon offers right now (the hidden and the
    internal rows never list)."""
    return tuple(n for n in COMMANDS if n not in COMMAND_HIDDEN and n not in COMMAND_INTERNAL)


def setting_pool():
    """The show-branch pool: the live-named settings + the alias spellings
    (a not-yet-live knob never lists)."""
    return POOL_NAMES


def welcome(sock):
    """The first-connect greeting: the console's two fixed lines — the
    daemon's name and the one-line navigation hint."""
    print(T('banner.welcome') % 'dashboard')
    print(T('banner.hint'))


SPEC = dict(label='the dashboard', daemon_label='dashboard control server',
            cli_name='dashboard-cli', app='dashboard', self_note='the server itself',
            command_help='e.g. inspect, show config, set log-queries on, request reload-config, shutdown',
            prompt_word='dashboard', timeout_s=CLI_TIMEOUT_S, keepalive_s=CLI_KEEPALIVE_S,
            reconnect=CLI_RECONNECT, reconnect_wait=CLI_RECONNECT_WAIT_S,
            max_line_bytes=CLI_MAX_LINE_BYTES_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES,
            ctl_socket=DEFAULT_CONTROL_SOCKET, settings=SETTING_BY_NAME, nodes=NODE_BY_NAME,
            live_settings=LIVE_SETTINGS, show_lives=SHOW_LIVES,
            command_pool=command_pool, setting_pool=setting_pool,
            describe=describe_word,
            welcome=welcome, loop=cli.typed_loop,
            silent_ok=lambda low: low.startswith('request reload-config'),
            render=None, cli_page=cli_page)

if __name__ == '__main__':
    cli.run_cli(SPEC)
