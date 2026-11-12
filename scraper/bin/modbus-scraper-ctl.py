#!/usr/bin/env python3
"""Small client for modbus-scraper's JSON-lines control server: sends one
command (or a batch from stdin) over TCP or a unix socket (--control-port,
env CTL) and prints the replies. TCP servers with --control-token
require the token first ({"cmd": "auth", "token": ...}) — pass it with
--control-token or the CONTROL_TOKEN environment variable.

  python3 modbus-scraper-ctl.py --control-port 15509 show config
  python3 modbus-scraper-ctl.py --control-port 15509 request poll now
  printf 'set interval 5\\nshow config\\n' | python3 modbus-scraper-ctl.py --control-port 15509

Commands (see the server's help): show <connections|version>,
set/clear, request poll now, request reload-config, request reload, request restart,
shutdown, quit.

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys
here = os.path.dirname(os.path.realpath(__file__))   # .../bin (realpath: the image symlinks the entry onto PATH)
sys.path.insert(0, os.path.dirname(here))    # the subproject root — the lib/ lives next to bin/
sys.path.insert(0, os.path.dirname(os.path.dirname(here)))   # the repo root — the common/ package

from common.runtime.audit import load_audit_tags
from common.wire.ctl import run_ctl
from lib.config import DEFAULT_CONTROL_SOCKET
from lib.man import ctl_page
from lib.options import SETTING_SPELLINGS
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_MAX_LINE_BYTES_S, CLI_TIMEOUT_S

TAGS = load_audit_tags('scraper')

if __name__ == '__main__':
    run_ctl(daemon='modbus-scraper', bin_name='modbus-scraper-ctl', app='modbus-scraper',
            self_note='the scraper itself',
            command_help='e.g. inspect, show config, set interval 5, request poll now, request reload, request restart, shutdown',
            ctl_socket=DEFAULT_CONTROL_SOCKET, timeout_s=CLI_TIMEOUT_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES, ctl_page=ctl_page,
            max_line_bytes=CLI_MAX_LINE_BYTES_S, spellings=SETTING_SPELLINGS,
            audit_tag=TAGS)
