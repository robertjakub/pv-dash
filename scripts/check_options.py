#!/usr/bin/env python3
"""The one-knob-one-source gate (docs/TODO.md): every knob must agree across
the four surfaces it lives on — the argparse flags, the env twins, the
NixOS module options and the README flag tables — against the option
registry (per-tool lib/options.py, the common Option rows). The bundled
config script and the man pages ride the same check (the man OPTIONS render
from the parser; the bundled config's `set` lines must name registry
options); the control-grammar vocabulary rides the rows too (every live
name unique and one word-path, every `group` a clean word).

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

from common.runtime.audit import AUDIT_FILES_MAX, AUDIT_FILES_MIN, AUDIT_MAX_MB_MAX, AUDIT_MAX_MB_MIN

# tool -> (bin script, registry module dir, module.nix, README, bundled config, flag-table headings)
TOOLS = {
    'cache': ('cache/bin/modbus-cache.py', 'cache', 'cache/module.nix', 'cache/README.md', 'cache/examples/modbus_cache.conf'),
    'scraper': ('scraper/bin/modbus-scraper.py', 'scraper', 'scraper/module.nix', 'scraper/README.md', 'scraper/examples/scraper.conf'),
    'inverter': ('inverter/bin/modbus-fake-inverter.py', 'inverter', None, 'inverter/README.md', 'inverter/examples/inverter.conf'),
    'dashboard': ('dashboard/bin/dashboard.py', 'dashboard', 'dashboard/module.nix', 'dashboard/README.md', 'dashboard/examples/server.conf'),
}

# the nix option names that deliberately diverge from lowerCamel(flag), and
# the flags a module deliberately covers another way (documented in the
# module's comments)
NIX_NAMES = {
    'cache': {'unit': 'unitId', 'listen': 'listenHost'},
    'scraper': {'modbus-unit': 'modbusUnit', 'listen': 'listenHost'},
    'dashboard': {'listen': 'listenHost', 'upstream': 'prometheusUrl', 'config-js': 'configFile'},
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


def bundled_config_names(config, options):
    """The registry names the bundled script's set lines resolve to — the
    CLI spelling (`set modbus upstream <value>`) via the same word-index
    parser the daemons load their configs with (a line no registry word
    answers raises ValueError)."""
    from common.settings.options import parse_config_script
    text = open(os.path.join(REPO, config)).read()
    return {name for name, _ in parse_config_script(text, config, options)}


def check_tool(tool):
    """One tool: returns [(ok, message)] rows."""
    rows = []
    bin_script, tool_dir, module_nix, readme, config = TOOLS[tool]
    options, _verbs = load_registry(tool_dir)
    flags = {'--' + o.name for o in options if o.flag}   # control-only settings carry no flag

    # the control grammar's vocabulary rides the same rows: every live name
    # unique and one spellable word-path (a '/'-path spells as its words on
    # the wire — whitespace could never parse), its short description
    # present, the control-only rows flag/env/secret-free
    live_names = [o.live for o in options if o.live]
    dupes = sorted({n for n in live_names if live_names.count(n) > 1})
    rows.append((not dupes, '%s: every live setting name is unique%s'
                 % (tool, ' — duplicated: %s' % ', '.join(dupes) if dupes else '')))
    spaced = sorted(o.live for o in options if o.live and any(c.isspace() for c in o.live))
    rows.append((not spaced, '%s: every live name is one word-path, no whitespace%s'
                 % (tool, ' — bad: %s' % ', '.join(spaced) if spaced else '')))
    bad_groups = sorted(o.name for o in options if o.group is not None
                        and (not isinstance(o.group, str) or not o.group
                             or any(c.isspace() for c in o.group)))
    rows.append((not bad_groups, '%s: every option group is a clean word%s'
                 % (tool, ' — bad rows: %s' % ', '.join(bad_groups) if bad_groups else '')))
    no_help = sorted('--' + o.name for o in options if o.live and not (o.setting_help or o.help))
    rows.append((not no_help, '%s: every live setting carries its description%s'
                 % (tool, ' — missing: %s' % ', '.join(no_help) if no_help else '')))
    bad_control_only = sorted(o.name for o in options
                              if not o.node and not o.flag and (o.env or o.secret or not o.live))
    rows.append((not bad_control_only, '%s: the control-only settings are flag/env/secret-free and live%s'
                 % (tool, ' — bad rows: %s' % ', '.join(bad_control_only) if bad_control_only else '')))
    # the env layer: a flag row reaches for an env twin or carries the
    # no-env note (the ruled-env-free reason) — a silent gap fails here
    unnoted = sorted(o.name for o in options if o.flag and not o.node and not o.env and not o.no_env)
    rows.append((not unnoted, '%s: every flag row carries an env twin or a no-env note%s'
                 % (tool, ' — unnoted: %s' % ', '.join(unnoted) if unnoted else '')))
    # the audit rotation bounds are the audit module's one constants — the
    # registries repeat them (the _gate_range reads the rows), never drift
    bad_bounds = sorted(o.name for o in options
                        if o.name == 'audit-files' and (o.min, o.max) != (AUDIT_FILES_MIN, AUDIT_FILES_MAX)
                        or o.name == 'audit-max-mb' and (o.min, o.max) != (AUDIT_MAX_MB_MIN, AUDIT_MAX_MB_MAX))
    rows.append((not bad_bounds, '%s: the audit rotation rows carry the common bounds (files %d..%d, max-mb %d..%d)%s'
                 % (tool, AUDIT_FILES_MIN, AUDIT_FILES_MAX, AUDIT_MAX_MB_MIN, AUDIT_MAX_MB_MAX,
                    ' — off: %s' % ', '.join(bad_bounds) if bad_bounds else '')))
    # the hierarchy nodes: a setting-help and at least one live child each
    bad_nodes = sorted(o.name for o in options if o.node
                       and (not (o.setting_help or o.help)
                            or not any(x.live and x.live.startswith(o.name + '/') for x in options)))
    rows.append((not bad_nodes, '%s: every hierarchy node describes its namespace and has a live child%s'
                 % (tool, ' — bad rows: %s' % ', '.join(bad_nodes) if bad_nodes else '')))
    # the hidden rows: a hidden knob is a wire-only listing mark — the pools
    # hide it either way (a flat row is a transient: the registry pass grants
    # its live name); a node row has no wire face to hide
    bad_hidden = sorted(o.name for o in options if o.hidden and o.node)
    rows.append((not bad_hidden, '%s: every hidden option carries a live name%s'
                 % (tool, ' — bad rows: %s' % ', '.join(bad_hidden) if bad_hidden else '')))
    # the restart knobs: the mark is a behavior mark, independent of the live
    # name (a live-named knob may still answer the restart note) — it rides
    # option rows only, never a node/show/command row
    bad_restart = sorted(o.name for o in options
                         if o.restart and (o.node or not o.flag))
    rows.append((not bad_restart, '%s: every restart mark rides an option knob%s'
                 % (tool, ' — bad rows: %s' % ', '.join(bad_restart) if bad_restart else '')))
    # the registry's `show` section: the custom show words — clean unique
    # words, a description each
    mod = sys.modules['options']
    show_words = list(mod.SHOW_WORDS)
    show_dupes = sorted({w for w in show_words if show_words.count(w) > 1})
    show_spaced = sorted(w for w in show_words if any(c.isspace() for c in w))
    show_bare = sorted(w for w, d in mod.SHOW_VALUES if not d)
    show_bad = sorted(set(show_dupes) | set(show_spaced) | set(show_bare))
    rows.append((not show_bad, '%s: every show word is a clean unique word with a description%s'
                 % (tool, ' — bad: %s' % ', '.join(show_bad) if show_bad else '')))
    # the show rows may spell the live hierarchy (else the live = the word):
    # a clean word-path, unique against the knobs' and each other's — two
    # rows on one live name would shadow in the shared setting space
    show_opts = list(getattr(mod, 'SHOW_OPTIONS', ()))
    show_lives = [o.live for o in show_opts]
    knob_lives = {o.live for o in options if o.live}
    live_bad = sorted({n for n in show_lives if any(c.isspace() for c in n)}
                      | {n for n in show_lives if show_lives.count(n) > 1}
                      | {n for n in show_lives if n in knob_lives})
    rows.append((not live_bad, '%s: every show live name is a clean word-path unique in the setting space%s'
                 % (tool, ' — bad: %s' % ', '.join(live_bad) if live_bad else '')))
    # the alias: a second spelling for the same knob on the wire — one clean
    # word-path, unique in the shared setting space (no live name, no other
    # alias answers twice; the canonical live name renders in the replies)
    every = list(options) + show_opts
    alias_rows = [(o.name, o.alias) for o in every if o.alias]
    taken = {o.live for o in every if o.live}
    alias_names = [a for _, a in alias_rows]
    alias_bad = sorted({n for n, a in alias_rows if any(c.isspace() for c in a)}
                       | {n for n, a in alias_rows if a in taken}
                       | {a for a in alias_names if alias_names.count(a) > 1})
    rows.append((not alias_bad, '%s: every alias is a clean word-path unique in the setting space%s'
                 % (tool, ' — bad: %s' % ', '.join(alias_bad) if alias_bad else '')))
    # the control commands: '/'-paths spelled as words on the wire
    # (`request/flush/cache` is `request flush cache`) — one clean word-path
    # each, unique in the command space, a description each
    cmd_words = list(mod.COMMANDS)
    cmd_dupes = sorted({w for w in cmd_words if cmd_words.count(w) > 1})
    cmd_spaced = sorted(w for w in cmd_words if any(c.isspace() for c in w))
    cmd_bare = sorted(w for w in cmd_words if not mod.COMMAND_HELP.get(w))
    cmd_bad = sorted(set(cmd_dupes) | set(cmd_spaced) | set(cmd_bare))
    rows.append((not cmd_bad, '%s: every command row is a clean unique word-path with a description%s'
                 % (tool, ' — bad: %s' % ', '.join(cmd_bad) if cmd_bad else '')))

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
                             if o.flag and o.flag not in ('--config', '--dry-run', '--man')
                             and renames.get(o.name, camel(o.name)) not in nix)
        rows.append((not missing_nix, '%s: the NixOS module defines every option%s'
                     % (tool, ' — missing: %s' % ', '.join(missing_nix) if missing_nix else '')))

    if config:
        try:
            names = bundled_config_names(config, options)
        except ValueError as e:
            rows.append((False, '%s: the bundled config does not parse against the registry: %s' % (tool, e)))
        else:
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
