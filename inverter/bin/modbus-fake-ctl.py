#!/usr/bin/env python3
"""Small client for the fake inverter's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env CTL) and prints the replies. TCP servers with --control-token
require the token first ({"cmd": "auth", "token": ...}) — pass it with
--control-token or the CONTROL_TOKEN environment variable.

  python3 modbus-fake-ctl.py --control-port 15599 set pv 2500
  python3 modbus-fake-ctl.py --control-port 15599 show status
  printf 'set pv 2500\\nset soc 30\\nshow status\\n' | python3 modbus-fake-ctl.py --control-port 15599

Commands (see the server's help): set <setting> <value>, show
<setting|status|connections|registers|version|config|knobs>, reset,
request reload, shutdown, quit.

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.ctl import run_ctl
from lib.man import ctl_page
from lib.paths import resolve_control_target
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_TIMEOUT_S

if __name__ == '__main__':
    run_ctl(daemon='fake inverter', bin_name='modbus-fake-ctl', app='fake-inverter',
            self_note='the fake itself',
            command_help='e.g. set pv 2500, set scenario noon, show status, reset, shutdown',
            resolve=resolve_control_target, timeout_s=CLI_TIMEOUT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES, ctl_page=ctl_page)
