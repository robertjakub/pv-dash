#!/usr/bin/env python3
"""pvsuite-cli — the ONE client for the family's JSON-lines control servers.

One script, five spellings: the four installed client names are symlinks
to this file and the tool comes from the name it was invoked as
(modbus-cache-cli -> modbus-cache, modbus-scraper-cli -> modbus-scraper,
modbus-fake-cli -> modbus-fake-inverter, dashboard-cli -> dashboard),
while a bare pvsuite-cli takes the tool as the first word — the daemon
name (modbus-cache, modbus-scraper, modbus-fake-inverter, dashboard) or
the short alias (cache, scraper, inverter; dashboard is its own alias).
An explicit word that disagrees with the invocation name is refused.

Everything after the tool word is the familiar client: command words
one-shot, piped stdin batch, a bare terminal the console session (the
banner, TAB completion and `?` in every position, the keepalive thread,
the reconnect cycle, the pager). The tool's SPEC — its pools, defaults,
socket, labels, special renders — lives in the tool's own lib/cli_spec.py;
this file only resolves the tool and loads it. Only one tool's lib/ is
ever imported per invocation, so the shared lib/ package name never
collides.

  python3 apps/pvsuite-cli.py cache show config
  modbus-cache-cli --control-port 15509 show config
  CTL=15509 pvsuite-cli scraper ping

Exit codes: 0 = ok, 1 = connection/control error, 2 = CLI misuse.
"""
import os
import sys

# daemon name -> the app dir under apps/; the short alias IS the app dir
# name — the internal tool key everywhere (audit tags, the gates)
TOOLS = {
    'modbus-cache': 'cache',
    'modbus-scraper': 'scraper',
    'modbus-fake-inverter': 'inverter',
    'dashboard': 'dashboard',
}
ALIASES = {'cache': 'modbus-cache', 'scraper': 'modbus-scraper',
           'inverter': 'modbus-fake-inverter'}

# the installed client names: strip the optional .py, strip -cli, map the
# base — the fake's legacy client spells 'fake', the one row the map names
NAMES = {'modbus-cache': 'modbus-cache', 'modbus-scraper': 'modbus-scraper',
         'modbus-fake': 'modbus-fake-inverter', 'dashboard': 'dashboard'}


def _implied():
    """The tool the invocation name carries (None under a plain pvsuite-cli)."""
    base = os.path.basename(sys.argv[0])
    if base.endswith('.py'):
        base = base[:-3]
    if base.endswith('-cli'):
        base = base[:-4]
    return NAMES.get(base)


def main(argv):
    implied = _implied()
    explicit = None
    if argv:
        word = ALIASES.get(argv[0], argv[0])
        if word in TOOLS:
            explicit = word
            argv = argv[1:]
    if explicit is not None and implied is not None and explicit != implied:
        sys.stderr.write('pvsuite-cli: invoked as %s (the %s client) but the tool word says %s — pick one\n'
                         % (os.path.basename(sys.argv[0]), implied, explicit))
        raise SystemExit(2)
    tool = explicit or implied
    if tool is None:
        sys.stderr.write('usage: pvsuite-cli <tool> [flags] [command words]\n'
                         '  the tool: %s\n'
                         '  (or invoke the installed client names — modbus-cache-cli, modbus-scraper-cli,\n'
                         '   modbus-fake-cli, dashboard-cli — the tool comes from the name)\n'
                         % ', '.join(sorted(TOOLS)))
        raise SystemExit(2)
    apps = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.join(apps, TOOLS[tool]))   # the app dir — its lib/ (the repo layout)
    sys.path.insert(0, apps)                             # this script's dir — lib/ and common/ beside it (the package layout)
    sys.path.insert(0, os.path.dirname(apps))            # the repo root — the common/ package (the repo layout)
    from common.wire import cli
    from lib import cli_spec
    sys.argv = [sys.argv[0]] + argv
    cli.run_client(cli_spec.SPEC)


if __name__ == '__main__':
    main(sys.argv[1:])
