#!/usr/bin/env python3
"""Small client for modbus-cache's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env CTL) and prints the replies. TCP servers with --control-token
require the token first ({"cmd": "auth", "token": ...}) — pass it with
--control-token or the CONTROL_TOKEN environment variable.

  python3 modbus-cache-ctl.py --control-port 15509 show status
  python3 modbus-cache-ctl.py --control-port 15509 clear cache
  printf 'show cache\\nclear cache\\n' | python3 modbus-cache-ctl.py --control-port 15509

Commands (see the server's help): show <status|connections|cache|version>,
clear cache, restart, shutdown, quit.

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.ctl import run_ctl
from lib.config import resolve_control_target
from lib.man import ctl_page
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_TIMEOUT_S

if __name__ == '__main__':
    run_ctl(daemon='modbus-cache', bin_name='modbus-cache-ctl', app='modbus-cache',
            self_note='the proxy itself',
            command_help='e.g. inspect, show status, show cache, clear cache, restart, shutdown',
            resolve=resolve_control_target, timeout_s=CLI_TIMEOUT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES, ctl_page=ctl_page)
