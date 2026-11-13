#!/usr/bin/env python3
"""Render the family's example files from the registries — one generator
for both surfaces, one gate:

- `docker/env/<tool>.env.example` — the four tools' env files: every env
  twin the registry declares, grouped by its namespace node (the
  MANUAL.md knobs tables' bucketing), the sample value the image itself
  runs (the CMD flag or an ENV where one pins it, the built-in default
  otherwise) and the docker-surface notes (the compose pins, the
  CMD/ENV pins) as comment lines.
- `<tool>/examples/<conf>` — the four tools' example configuration
  scripts: every knob the registry declares (a flag or an env twin),
  every line commented, the value the row's default spells, the secrets
  in their file:<path> form. The grammar is the control grammar
  (common/settings/options.py): every line is a `set <name> <value>` —
  the live path as words, the same line pastes into the console or a
  ctl. The buckets follow the MANUAL.md knobs tables' rule: the longest
  node naming the row's live path, the startup-only rows (no live path)
  in the general bucket. The fake's demo machines (pv, load, batt,
  grid, soc, mppt, cloud, scenario, battery-state, grid-outage) are
  control-only set words — no flag, no env — so they never render.

The files are GENERATED: edit the registry — or this script's TOOLS/
DEMO/NOTES/INTRO for the per-surface facts — and re-run, never the
example file.

  python3 scripts/generators/examples.py          # render the eight files
  python3 scripts/generators/examples.py --check  # exit 1 when a shipped file drifts

The prometheus env example stays hand-written (its PROM_* knobs belong
to entrypoint-prometheus.sh, not a registry) — --check cross-checks its
PROM_* names against the entrypoint so no line promises a knob the
entrypoint does not read. The other example files (modbus-cache-filter.json,
metrics.json, config.js, the tokens, the acl jsons) stay hand-written
too — this script renders only the env files and the conf scripts.

Stdlib only."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # scripts/ — the common lib rides there
from lib import REPO
from lib.emit import emit
from lib.registry import folded as fold_rows, wired

# ---------------------------------------------------------------- the
# env files: the daemons in the manual.py chain order — the tool
# dir, the daemon name (the env-file stem IS the daemon name: the
# shipped env/<stem>.env.example), the intro paragraphs (the
# compose-consumption story the
# shared header does not carry), the DEMO sample values (the image's own
# — the CMD flag or an ENV where one pins the knob, else the registry
# default) and the per-knob docker notes — DEMO/NOTES keys are registry
# row names and every key is gated: an unknown key fails the run, a twin
# without its note renders bare.
CMD_PIN = ("the image's CMD pins this flag — the env file cannot beat it "
           "in docker (replace the CMD to move the bind); the twin serves "
           "the non-docker surfaces")
ENV_VOLUME = ("the image's ENV points it at the volume copy — the env "
              "file wins over an ENV")
UPSTREAM_ENV = ("the image's ENV carries this default (the compose "
                "stack's peer service) — the env file wins over an ENV")
SIGHUP_LIVE = ("the SIGHUP re-read re-applies it to a running container "
               "(keep-last-good)")
BOTH_LAYERS = 'a both-layers twin: the SIGHUP re-read applies it too'
SUITE_KEY_STACK = ("both compose stacks pin this to the stack's suite "
                   "key (the environment block — environment beats "
                   "env_file)")
SUITE_KEY_DEMO = ("the demo stack pins this to the stack's suite key "
                  "(environment beats env_file)")
# the prod stack's copy stems: the prod compose reads env/<prod>.env (the
# cache's REQUIRED, the scraper's optional) while the demo keeps
# env/<stem>.env — one generated example, two copy targets
PROD = {'cache': 'cache-production', 'scraper': 'scraper-production'}
ENV_TOOLS = (
    ('cache', 'modbus-cache', 'cache',
     ('Both compose stacks read the file (env_file: — the demo copy '
      'optional, the prod copy REQUIRED: UPSTREAM is the operator\'s '
      'decision there); where a stack\'s environment block pins a knob '
      '(environment beats env_file) the notes below mark it.',),
     {'upstream': 'modbus-fake-inverter:5502',
      'selection': '/config/selection.json',
      'listen': '0.0.0.0:15502',
      'audit-log': '-'},
     {'upstream': UPSTREAM_ENV,
      'selection': ENV_VOLUME,
      'listen': CMD_PIN,
      'audit-log': CMD_PIN,
      'modbus-auth': SUITE_KEY_STACK,
      'modbus-auth-key': SUITE_KEY_STACK,
      'modbus-auth-upstream': ('the demo stack pins this to the stack\'s suite '
                        'key; in prod the upstream credential is the '
                        'device\'s — this file is its edit surface'),
      'modbus-auth-upstream-key': ('the demo stack pins this to the stack\'s '
                            'suite key; in prod the upstream credential '
                            'is the device\'s — this file is its edit '
                            'surface')},
     ),
    ('scraper', 'modbus-scraper', 'scraper',
     ('Both compose stacks read the file (env_file:, required: false — '
      'no file = the image defaults); the stacks\' environment block '
      'pins the auth knobs the notes below mark.',),
     {'upstream': 'modbus-cache:15502',
      'metrics-spec': '/config/metrics.json',
      'listen': '0.0.0.0:9350',
      'auth-token': 'file:/config/metrics.token'},
     {'upstream': UPSTREAM_ENV,
      'metrics-spec': ENV_VOLUME,
      'listen': CMD_PIN,
      'modbus-auth': ('both compose stacks pin this to the stack\'s '
                      'suite key (the scraper proves it to the cache — '
                      'environment beats env_file)'),
      'modbus-auth-key': ('both compose stacks pin this to the stack\'s suite '
                   'key (the scraper proves it to the cache — '
                   'environment beats env_file)'),
      'auth-token': ('the compose stacks pin AUTH_TOKEN to the generated '
                     '/config/metrics.token (environment beats env_file) '
                     '— this line is the plain-docker spelling')},
     ),
    ('inverter', 'modbus-fake-inverter', 'modbus-fake-inverter',
     ('The demo compose reads the file (env_file:, required: false — no '
      'file = the image defaults); prod runs no fake service.',),
     {'listen': '0.0.0.0:5502',
      'audit-log': '-'},
     {'listen': CMD_PIN,
      'audit-log': CMD_PIN,
      'modbus-auth': SUITE_KEY_DEMO,
      'modbus-auth-key': SUITE_KEY_DEMO,
      'modbus-profile': BOTH_LAYERS,
      'log-level': BOTH_LAYERS,
      'chaos': SIGHUP_LIVE,
      'max-kwp': SIGHUP_LIVE,
      'strict': SIGHUP_LIVE,
      'time': SIGHUP_LIVE,
      'time-scale': SIGHUP_LIVE},
     ),
    ('dashboard', 'dashboard', 'dashboard',
     ('No compose stack reads this file — the plain-docker spelling: the '
      'stacks\' PROM_URL and page token are compose-level environment '
      'blocks (edit the compose or a docker-compose.override.yaml to '
      'move them).',),
     {'listen': '0.0.0.0:8080',
      'upstream': 'http://prometheus:9090',
      'config-js': '/config/config.js'},
     {'listen': CMD_PIN,
      'config-js': ENV_VOLUME,
      'auth-token': ('the compose stacks ride the generated '
                     '/config/page.token — this line is the '
                     'plain-docker spelling')},
     ),
)

# ------------------------------------------------------- the conf files:
# the four tools in the same chain order — the tool dir, the daemon
# name, the example conf's basename, the intro paragraphs (the
# consumption story the shared header does not carry) and the DEMO
# sample values (a knob the sample shape pins at a non-default value —
# rendered ACTIVE; everything else stays commented at its default).
# DEMO keys are registry row names and gated: an unknown key fails the
# run.
CONF_TOOLS = (
    ('cache', 'modbus-cache', 'modbus-cache.conf',
     ('The dev wrapper (`apps/cache/dev`) points --config here; the docker '
      'image copies the file to /pv-suite/cache/modbus-cache.conf — its '
      'default --config target — where the CMD flags and the env twins '
      'carry the deployment shape. Copy the file, uncomment what you '
      'change.',), {}),
    ('scraper', 'modbus-scraper', 'modbus-scraper.conf',
     ('The dev wrapper (`apps/scraper/dev`) points --config here; the docker '
      'image copies the file to /pv-suite/scraper/modbus-scraper.conf — '
      'its '
      'default --config target — where the CMD flags and the env twins '
      'carry the deployment shape. Copy the file, uncomment what you '
      'change.',), {}),
    ('inverter', 'modbus-fake-inverter', 'modbus-fake-inverter.conf',
     ('The dev wrapper (`apps/inverter/dev`) points --config here; the docker '
      'image copies the file to /pv-suite/inverter/'
      'modbus-fake-inverter.conf — the '
      'default --config target. The fake\'s demo machines (`set pv`, '
      '`set load`, `set batt`, `set grid`, `set soc`, `set mppt`, `set '
      'cloud`, `set scenario`, `set battery-state`, `set grid-outage`) '
      'are runtime set words — no flag, no env twin — so they never '
      'render in a config file. Copy the file, uncomment what you '
      'change.',), {}),
    ('dashboard', 'dashboard', 'dashboard.conf',
     ('The docker image copies the file to /pv-suite/dashboard/'
      'dashboard.conf — its default --config target — where the CMD flags '
      'carry the bind; the compose stacks\' PROM_URL and page token are '
      'compose-level environment. Copy the file, uncomment what you '
      'change.',), {}),
)

WIDTH = 74


def load(tool_dir):
    """The tool's wired rows (the import dance in lib/registry) — the raw
    registry default lands on static_default, the value_help/hint/values
    ride along — plus the folded raw rows: the env render's sample values
    read the raw JSON's default/conv, the canon refs resolve through the
    loader's own fold (the row's inline field wins)."""
    opts, _verbs, _shows, _mod = wired(tool_dir)
    rows = tuple(opts)
    return rows, {r['name']: r for r in fold_rows(tool_dir, 'options')}


def wrap(text):
    """Greedy wrap at WIDTH — the comment prose (%% is the texts'
    literal % escape: one un-escape for the render)."""
    text = text.replace('%%', '%')
    words, lines, line = text.split(), [], ''
    for w in words:
        if line and len(line) + 1 + len(w) > WIDTH:
            lines.append(line)
            line = w
        else:
            line = (line + ' ' + w) if line else w
    if line:
        lines.append(line)
    return lines


def comment(text):
    return '\n'.join('# ' + l for l in wrap(text))


def bucket_key(live, nodes):
    """The row's bucket: the longest node naming its live path's prefix
    (the MANUAL.md knobs tables' rule); a knob without a live path (or
    under no node) rides the general bucket."""
    best = ''
    for n in nodes:
        if live and (live == n.name or live.startswith(n.name + '/')) \
                and len(n.name) > len(best):
            best = n.name
    return best


# ------------------------------------------------------------- the env
# render

def env_value_of(opt, raw, demo):
    """The sample value: the DEMO override (the image's own) else the
    raw registry row's default — the wired row's static default answers
    when the raw row carries none (the protocol tree's splice: the
    `timeout` rows hand-copy no number) — bools render on|off, floats
    %g, an absent default renders empty (the secrets: pass a value or a
    file:<path>)."""
    if opt.name in demo:
        return demo[opt.name]
    d = raw.get('default', opt.static_default)
    if raw.get('conv') == 'bool':
        return 'on' if d in (True, 'on') else 'off'
    if d is None or d == '':
        return ''
    if isinstance(d, float):
        return '%g' % d
    return str(d)


def render_env(tool, daemon, stem, intro, demo, notes, rows, raw):
    twins = [o for o in rows if not o.node
             and [e for e in o.env_names() if e]]
    known = {o.name for o in twins}
    for key in demo:
        if key not in known:
            raise SystemExit('examples: %s DEMO key %r is no env twin'
                             % (tool, key))
    for key in notes:
        if key not in known:
            raise SystemExit('examples: %s NOTES key %r is no env twin'
                             % (tool, key))
    out = []
    w = out.append
    if stem in PROD:
        cp = ("cp env/%s.env.example env/%s.env (the demo stack) or "
              "env/%s.env (the prod stack) and edit."
              % (stem, stem, PROD[stem]))
    else:
        cp = "cp env/%s.env.example env/%s.env and edit." % (stem, stem)
    w(comment("The %s's env file — GENERATED by scripts/generators/examples.py "
              "from %s/lib/options.json (the one-knob-one-source rows): "
              "every env twin the registry declares is below — %d of "
              "them. Edit the registry and re-run the generator, never "
              "this file. %s A knob's value resolves flag > env > the "
              "bundled conf > built-in default — an env here overrides "
              "the image's conf knob by knob. Every line starts "
              "commented: the sample value is what the image itself "
              "runs (the CMD flag or an ENV where one pins it, the "
              "built-in default otherwise); a secret's line stays "
              "empty — pass it as file:<path>, an owner-only 0600 file "
              "(the F12 discipline)."
              % (daemon, tool, len(twins), cp)))
    for para in intro:
        w('')
        w(comment(para))
    nodes = [o for o in rows if o.node]
    order, buckets = [], {}
    for o in twins:
        b = bucket_key(o.live, nodes)
        if b not in buckets:
            order.append(b)
            buckets[b] = []
        buckets[b].append(o)
    for b in order:
        w('')
        w('# --- %s ---' % (b if b else 'general'))
        w('')
        for i, o in enumerate(buckets[b]):
            if i:
                w('')
            env = '/'.join(e for e in o.env_names() if e)
            w(comment(o.setting_help or o.help or env))
            if notes.get(o.name):
                w(comment(notes[o.name]))
            if o.secret:
                w(comment('a secret — pass it as file:<path>, an '
                          'owner-only 0600 file'))
            w('#%s=%s' % (env, env_value_of(o, raw.get(o.name, {}), demo)))
    out.append('')
    text = '\n'.join(out)
    for no, line in enumerate(text.splitlines(), 1):
        if len(line.encode('utf-8')) > 78:
            raise SystemExit('%s.env.example:%d: line over 78 bytes: %r'
                             % (tool, no, line))
    return text


# ------------------------------------------------------------- the conf
# render

def conf_words_of(opt):
    """The line's knob spelling: the live path as words (the console
    spelling — pastes into the console or a ctl), the flat registry
    name on a row without one."""
    return ' '.join(opt.live.split('/')) if opt.live else opt.name


def conf_value_of(opt, demo, daemon):
    """The sample value: the DEMO override, else the row's default —
    bools true/false (the config_value canon), floats %g, an absent
    default renders empty. A credential (a secret named *-token/*-key)
    spells its file:<path> form instead — a secret never renders
    inline."""
    if opt.name in demo:
        return demo[opt.name]
    if opt.secret and (opt.name.endswith('-token') or opt.name.endswith('-key')):
        return 'file:/run/credentials/%s/%s' % (daemon, opt.name)
    d = opt.static_default
    if d is None or d == '':
        return ''
    if opt.conv is bool:
        return 'true' if d else 'false'
    if isinstance(d, float):
        return '%g' % d
    return str(d)


def conf_note_of(opt, value):
    """The line's paren note: the value_help word for the rendered value
    (a bool's note is keyed by its on/off word), else the value shape —
    only where the row carries one."""
    vh = opt.value_help or {}
    note = vh.get(value)
    if note is None and opt.conv is bool:
        note = vh.get('on' if value == 'true' else 'off')
    if note is None and not value:
        note = opt.hint
    return note.replace('%%', '%') if note else ''


def render_conf(tool, daemon, name, intro, demo, rows):
    knobs = [o for o in rows if not o.node and (o.flag or any(o.env_names()))]
    for key in demo:
        if key not in {o.name for o in knobs}:
            raise SystemExit('examples: %s DEMO key %r is no knob'
                             % (tool, key))
    # the MANUAL.md knobs tables' bucketing: the longest node naming the
    # row's live path's prefix; a row without a live path (startup-only)
    # rides the general bucket
    nodes = [o for o in rows if o.node]
    order, buckets = [''], {'': []}
    for o in knobs:
        b = bucket_key(o.live, nodes)
        if b not in buckets:
            buckets[b] = []
            order.append(b)
        buckets[b].append(o)
    out = []
    w = out.append
    w(comment("The %s's example configuration — GENERATED by "
              "scripts/generators/examples.py from %s/lib/options.json (the "
              "one-knob-one-source rows): every knob the registry "
              "declares is below — %d of them, every line commented. "
              "Edit the registry and re-run the generator, never this "
              "file. %s" % (daemon, tool, len(knobs), ' '.join(intro))))
    w('')
    w(comment("The grammar is the control grammar: every line is a "
              "`set <name> <value>` — the live path as words, the same "
              "line pastes into the console or a ctl — and every "
              "comment stays a comment. A value resolves flag > env > "
              "this file > the row's default: anything left commented "
              "falls to the default the line spells. A secret's line "
              "spells the file:<path> form — pass it as an owner-only "
              "0600 file, never inline."))
    node_by_name = {n.name: n for n in nodes}
    for key in order:
        if not buckets.get(key):
            continue
        w('')
        if key:
            w('# --- %s ---' % key)
            w('')
            w(comment(node_by_name[key].setting_help
                      or node_by_name[key].help or key))
            w('')
        for i, o in enumerate(buckets[key]):
            if i:
                w('')
            w(comment(o.setting_help or o.help or o.name))
            if o.secret:
                w(comment('a secret — pass it as file:<path>, an '
                          'owner-only 0600 file'))
            if o.restart:
                w(comment('startup-only: a change applies on restart'))
            value = conf_value_of(o, demo, daemon)
            note = conf_note_of(o, value)
            if note:
                w(comment(note))
            line = '# set %s %s' % (conf_words_of(o), value) if value != '' \
                else '# set %s' % conf_words_of(o)
            w(line.rstrip())
    out.append('')
    text = '\n'.join(out)
    for no, line in enumerate(text.splitlines(), 1):
        if len(line.encode('utf-8')) > 96:   # a set line cannot wrap (the renamed
            # auth knobs' file: credential paths need the room); prose wraps at 74
            raise SystemExit('%s/examples/%s:%d: line over 96 bytes: %r'
                             % (tool, name, no, line))
    return text


def main(argv):
    check = '--check' in argv
    drift = False
    for tool, daemon, stem, intro, demo, notes in ENV_TOOLS:
        rows, raw = load(tool)
        page = render_env(tool, daemon, stem, intro, demo, notes, rows, raw)
        path = os.path.join(REPO, 'docker', 'env', '%s.env.example' % stem)
        drift = emit(path, page, check, 'examples',
                     rerun='python3 scripts/generators/examples.py') or drift
    for tool, daemon, name, intro, demo in CONF_TOOLS:
        rows, _ = load(tool)
        page = render_conf(tool, daemon, name, intro, demo, rows)
        path = os.path.join(REPO, 'apps', tool, 'examples', name)
        drift = emit(path, page, check, 'examples',
                     rerun='python3 scripts/generators/examples.py') or drift
    # the prometheus example stays hand-written; the gate reads it: every
    # PROM_* name it promises must be one the entrypoint resolves
    with open(os.path.join(REPO, 'docker', 'env',
                           'prometheus.env.example'), encoding='utf-8') as f:
        promised = re.findall(r'^#([A-Z][A-Z0-9_]*)=', f.read(), re.M)
    with open(os.path.join(REPO, 'docker', 'entrypoints',
                           'entrypoint-prometheus.sh'), encoding='utf-8') as f:
        entrypoint = f.read()
    unknown = [n for n in promised if n not in entrypoint]
    if unknown:
        raise SystemExit('examples: prometheus.env.example promises %s '
                         '— entrypoint-prometheus.sh reads none of them'
                         % ', '.join(unknown))
    if check:
        if drift:
            print('drift: %s' % ', '.join(drift))
            return 1
        print('examples up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
