#!/usr/bin/env python3
"""Small client for modbus-scraper's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env CTL) and prints the replies. TCP servers with --control-token
require the token first ({"cmd": "auth", "token": ...}) — pass it with
--control-token or the CONTROL_TOKEN environment variable. With a
token configured the wire is HMAC-signed (the full sha256 of each frame,
common/wiresec.py): the client signs every command and verifies every
reply.

  python3 modbus-scraper-ctl.py --control-port 15509 show status
  python3 modbus-scraper-ctl.py --control-port 15509 poll now
  printf 'set interval 5\\nshow status\\n' | python3 modbus-scraper-ctl.py --control-port 15509

Commands (see the server's help): show <status|connections|version>,
set/unset, poll now, request reload, restart, shutdown, quit.

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
    run_ctl(daemon='modbus-scraper', bin_name='modbus-scraper-ctl', app='modbus-scraper',
            self_note='the scraper itself',
            command_help='e.g. inspect, show status, set interval 5, poll now, request reload, restart, shutdown',
            resolve=resolve_control_target, timeout_s=CLI_TIMEOUT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES, ctl_page=ctl_page)
