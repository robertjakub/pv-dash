#!/usr/bin/env python3
"""Small client for the dashboard's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env CTL) and prints the replies. TCP servers with --control-token
require the token first ({"cmd": "auth", "token": ...}) — pass it with
--control-token or the CONTROL_TOKEN environment variable.

  python3 dashboard-ctl.py --control-port 15598 show config
  python3 dashboard-ctl.py --control-port 15598 request reload-config
  printf 'set log-queries on\\nshow config\\n' | python3 dashboard-ctl.py --control-port 15598

Commands (see the server's help): show <connections|version>,
set/clear, inspect, request reload-config, request reload, shutdown, quit.

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.wire.ctl import run_ctl
from lib.config import DEFAULT_CONTROL_SOCKET
from lib.man import ctl_page
from lib.options import SETTING_SPELLINGS
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_MAX_LINE_BYTES_S, CLI_TIMEOUT_S

if __name__ == '__main__':
    run_ctl(daemon='dashboard', bin_name='dashboard-ctl', app='dashboard',
            self_note='the server itself',
            command_help='e.g. inspect, show config, set log-queries on, request reload-config, shutdown',
            ctl_socket=DEFAULT_CONTROL_SOCKET, timeout_s=CLI_TIMEOUT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES, ctl_page=ctl_page,
            max_line_bytes=CLI_MAX_LINE_BYTES_S, spellings=SETTING_SPELLINGS)
