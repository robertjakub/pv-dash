"""the dashboard's client SPEC — the per-tool half of pvsuite-cli.

The dispatcher (apps/pvsuite-cli.py) resolves the tool from the
invocation name or the first word, puts this app's root on sys.path and
loads SPEC from here: the pools over the registry's command and setting
rows and the dashboard's labels and defaults. Only one tool's lib/ is
ever imported per invocation, so the shared lib/ package name never
collides.
"""
from common.runtime.audit import load_audit_tags
from common.wire import cli
from common.render.texts import T
from lib.config import DEFAULT_CONTROL_SOCKET
from lib.man import cli_page
from lib.options import COMMANDS, COMMAND_HELP, COMMAND_HIDDEN, COMMAND_INTERNAL, HIDDEN_SETTINGS, NODE_BY_NAME, POOL_NAMES, SETTING_SPELLINGS, SHOW_LIVES
from lib.statics import AUDIT_FILES, AUDIT_MAX_MB, CLI_KEEPALIVE_S, CLI_MAX_LINE_BYTES_S, CLI_RECONNECT, CLI_RECONNECT_WAIT_S, CLI_TIMEOUT_S


describe_word, command_pool, setting_pool, welcome = cli.pools(
    COMMANDS, COMMAND_INTERNAL, COMMAND_HIDDEN, SETTING_SPELLINGS, NODE_BY_NAME, COMMAND_HELP,
    POOL_NAMES, 'dashboard', hidden_settings=HIDDEN_SETTINGS)


TAGS = load_audit_tags('dashboard')

SPEC = dict(audit_tag=TAGS, label='the dashboard', daemon_label='dashboard control server',
            cli_name='dashboard-cli', app='dashboard', self_note='the server itself',
            command_help='e.g. inspect, show config, set log-queries on, request reload-config, shutdown',
            prompt_word='dashboard', timeout_s=CLI_TIMEOUT_S, keepalive_s=CLI_KEEPALIVE_S,
            reconnect=CLI_RECONNECT, reconnect_wait=CLI_RECONNECT_WAIT_S,
            max_line_bytes=CLI_MAX_LINE_BYTES_S,
            audit_max_mb=AUDIT_MAX_MB, audit_files=AUDIT_FILES,
            ctl_socket=DEFAULT_CONTROL_SOCKET, spellings=SETTING_SPELLINGS, nodes=NODE_BY_NAME,
            show_lives=SHOW_LIVES,
            command_pool=command_pool, setting_pool=setting_pool,
            describe=describe_word,
            welcome=welcome, loop=cli.typed_loop,
            silent_ok=lambda low: low.startswith('request reload-config'),
            render=None, cli_page=cli_page)
