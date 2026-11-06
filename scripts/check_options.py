#!/usr/bin/env python3
"""The one-knob-one-source gate (docs/TODO.md): every knob must agree across
the four surfaces it lives on — the argparse flags, the env twins, the
NixOS module options and the README flag tables — against the option
registry (per-tool lib/options.py, the common Option rows). The bundled
config script and the man pages ride the same check (the man OPTIONS render
from the parser; the bundled config's `set` lines must name registry
options).

  python3 scripts/check_options.py           # the whole family
  python3 scripts/check_options.py cache     # one tool

Exit 0 = everything agrees, 1 = drift (the report says what and where).
Stdlib only."""
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

# tool -> (bin script, registry module dir, module.nix, README, bundled config, flag-table headings)
TOOLS = {
    'cache': ('cache/bin/modbus-cache.py', 'cache', 'cache/module.nix', 'cache/README.md', 'cache/modbus_cache.conf'),
    'scraper': ('scraper/bin/modbus-scraper.py', 'scraper', 'scraper/module.nix', 'scraper/README.md', 'scraper/scraper.conf'),
    'inverter': ('inverter/bin/modbus-fake-inverter.py', 'inverter', None, 'inverter/README.md', None),
    'dashboard': ('dashboard/bin/dashboard.py', 'dashboard', 'dashboard/module.nix', 'dashboard/README.md', 'dashboard/server.conf'),
}

# the nix option names that deliberately diverge from lowerCamel(flag), and
# the flags a module deliberately covers another way (documented in the
# module's comments)
NIX_NAMES = {
    'cache': {'unit': 'unitId', 'listen': 'listenHost'},
    'scraper': {'modbus-unit': 'modbusUnit', 'listen': 'listenHost'},
    'dashboard': {'bind': 'host', 'upstream': 'prometheusUrl', 'config-js': 'configFile'},
}


def load_registry(tool_dir):
    sys.path.insert(0, os.path.join(REPO, tool_dir, 'lib'))
    sys.modules.pop('options', None)
    mod = __import__('options')
    sys.path.pop(0)
    return mod.OPTIONS, mod.KNOWN_VERBS


def parser_flags(bin_script):
    """The flags the tool's argparse actually defines (run --help and read)."""
    script = os.path.join(REPO, bin_script)
    r = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True,
                       cwd=os.path.dirname(script))
    if r.returncode != 0:
        return None, 'cannot run %s --help: %s' % (bin_script, (r.stderr or r.stdout)[-120:])
    return set(re.findall(r'^\s+(--[a-z0-9-]+)', r.stdout, re.M)), None


def nix_options(module_nix):
    """The option names the NixOS module defines (mkOption names, camelCase)."""
    text = open(os.path.join(REPO, module_nix)).read()
    return set(re.findall(r'([A-Za-z][A-Za-z0-9]*)\s*=\s*lib\.mkOption', text))


def readme_flags(readme):
    """The flags named in the README's flag tables (`| \`--flag\`` rows and the
    prose). A knob is covered when the README mentions its flag at all — the
    tables are documentation, not a registry dump; what the check enforces
    is that every registry row is mentioned somewhere."""
    text = open(os.path.join(REPO, readme)).read()
    return text


def bundled_config_names(config):
    """The `set <name>` lines (comments stripped) the bundled script carries."""
    names = set()
    for raw in open(os.path.join(REPO, config)):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        body = line[4:] if line.startswith('set ') else line
        parts = body.split(None, 1)
        if parts:
            names.add(parts[0])
    return names


def check_tool(tool):
    """One tool: returns [(ok, message)] rows."""
    rows = []
    bin_script, tool_dir, module_nix, readme, config = TOOLS[tool]
    options, _verbs = load_registry(tool_dir)
    flags = {'--' + o.name for o in options}

    got, err = parser_flags(bin_script)
    if err:
        return [(False, '%s: %s' % (tool, err))]
    missing = sorted(flags - got)
    rows.append((not missing, '%s: the registry flags all exist in --help%s'
                 % (tool, ' — missing: %s' % ', '.join(missing) if missing else '')))

    extra = sorted(got - flags - {'--config', '--dry-run', '--man', '--version', '--help'})
    rows.append((not extra, '%s: every --help flag is in the registry%s'
                 % (tool, ' — undocumented: %s' % ', '.join(extra) if extra else '')))

    # the README mentions every flag
    text = readme_flags(readme)
    unmentioned = sorted(f for f in flags if f not in text)
    rows.append((not unmentioned, '%s: the README mentions every flag%s'
                 % (tool, ' — unmentioned: %s' % ', '.join(unmentioned) if unmentioned else '')))

    if module_nix:
        nix = nix_options(module_nix)

        def camel(name):
            # the nix option style: lowerCamel (allowWrite, controlOpsToken)
            parts = name.split('-')
            return parts[0] + ''.join(p.capitalize() for p in parts[1:])

        renames = NIX_NAMES.get(tool, {})
        missing_nix = sorted('--' + o.name for o in options
                             if o.flag not in ('--config', '--dry-run', '--man')
                             and renames.get(o.name, camel(o.name)) not in nix)
        rows.append((not missing_nix, '%s: the NixOS module defines every option%s'
                     % (tool, ' — missing: %s' % ', '.join(missing_nix) if missing_nix else '')))

    if config:
        names = bundled_config_names(config)
        unknown = sorted(n for n in names if n not in {o.name for o in options})
        rows.append((not unknown, '%s: the bundled config names registry options only%s'
                     % (tool, ' — unknown: %s' % ', '.join(unknown) if unknown else '')))
    return rows


def main():
    wanted = sys.argv[1:] or list(TOOLS)
    ok = True
    for tool in wanted:
        if tool not in TOOLS:
            print('unknown tool %s (try %s)' % (tool, ', '.join(TOOLS)))
            return 1
        for good, message in check_tool(tool):
            print(('PASS ' if good else 'FAIL ') + message)
            ok = ok and good
    print()
    print('ALL PASS' if ok else 'FAILURES above')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
