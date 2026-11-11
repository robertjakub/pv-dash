#!/usr/bin/env python3
"""Render docker/env/<tool>.env.example — the four pv-suite tools' env
files — from the per-tool registries (lib/options.json via lib/options.py,
the one-knob-one-source rows): every env twin the registry declares,
grouped by its namespace node (the MANUAL.md knobs tables' bucketing),
the sample value the image itself runs (the CMD flag or an ENV where one
pins it, the built-in default otherwise) and the docker-surface notes
(the compose pins, the CMD/ENV pins) as comment lines. The files are
GENERATED: edit the registry — or this script's DEMO/NOTES/INTRO for the
docker-surface facts — and re-run, never the env file.

  python3 scripts/gen_env.py          # render the four files
  python3 scripts/gen_env.py --check  # exit 1 when a shipped file drifts

The prometheus example stays hand-written (its PROM_* knobs belong to
entrypoint-prometheus.sh, not a registry) — --check cross-checks its
PROM_* names against the entrypoint so no line promises a knob the
entrypoint does not read.

Stdlib only."""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

# the daemons in the gen_manual.py chain order: the tool dir, the daemon
# name, the env-file stem (the shipped env/<stem>.env.example — the
# fake's file spells fake, the tool dir is inverter), the intro
# paragraphs (the compose-consumption story the shared header does not
# carry), the DEMO sample values (the image's own — the CMD flag or an
# ENV where one pins the knob, else the registry default) and the
# per-knob docker notes — DEMO/NOTES keys are registry row names and
# every key is gated: an unknown key fails the run, a twin without its
# note renders bare.
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
TOOLS = (
    ('cache', 'modbus-cache', 'cache',
     ('Both compose stacks read the file (env_file: — the demo copy '
      'optional, the prod copy REQUIRED: UPSTREAM is the operator\'s '
      'decision there); where a stack\'s environment block pins a knob '
      '(environment beats env_file) the notes below mark it.',),
     {'upstream': 'fake-inverter:5502',
      'selection': '/config/selection.json',
      'listen': '0.0.0.0:15502',
      'audit-log': '-'},
     {'upstream': UPSTREAM_ENV,
      'selection': ENV_VOLUME,
      'listen': CMD_PIN,
      'audit-log': CMD_PIN,
      'modbus-auth': SUITE_KEY_STACK,
      'auth-key': SUITE_KEY_STACK,
      'auth-upstream': ('the demo stack pins this to the stack\'s suite '
                        'key; in prod the upstream credential is the '
                        'device\'s — this file is its edit surface'),
      'auth-upstream-key': ('the demo stack pins this to the stack\'s '
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
      'auth-key': ('both compose stacks pin this to the stack\'s suite '
                   'key (the scraper proves it to the cache — '
                   'environment beats env_file)'),
      'auth-token': ('the compose stacks pin AUTH_TOKEN to the generated '
                     '/config/metrics.token (environment beats env_file) '
                     '— this line is the plain-docker spelling')},
     ),
    ('inverter', 'fake-inverter', 'fake',
     ('The demo compose reads the file (env_file:, required: false — no '
      'file = the image defaults); prod runs no fake service.',),
     {'listen': '0.0.0.0:5502',
      'audit-log': '-'},
     {'listen': CMD_PIN,
      'audit-log': CMD_PIN,
      'modbus-auth': SUITE_KEY_DEMO,
      'auth-key': SUITE_KEY_DEMO,
      'profile': BOTH_LAYERS,
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

WIDTH = 74


def load(tool_dir):
    """gen_manual.py's import dance: one module named `options` at a
    time — the tool's wired rows, plus the raw registry rows: the wired
    Option carries no default (the bins wire their own), the sample
    values read the raw JSON's default/conv (the row quartet's source)."""
    sys.path.insert(0, os.path.join(REPO, tool_dir, 'lib'))
    sys.modules.pop('options', None)
    mod = __import__('options')
    rows = tuple(mod.OPTIONS)
    sys.modules.pop('options', None)
    sys.path.pop(0)
    with open(os.path.join(REPO, tool_dir, 'lib', 'options.json'),
              encoding='utf-8') as f:
        meta = json.load(f)
    return rows, {r['name']: r for r in meta['options']}


def wrap(text):
    """Greedy wrap at WIDTH — the comment prose."""
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


def value_of(opt, raw, demo):
    """The sample value: the DEMO override (the image's own) else the
    raw registry row's default — bools render on|off, floats %g, an
    absent default renders empty (the secrets: pass a value or a
    file:<path>)."""
    if opt.name in demo:
        return demo[opt.name]
    d = raw.get('default')
    if raw.get('conv') == 'bool':
        return 'on' if d in (True, 'on') else 'off'
    if d is None or d == '':
        return ''
    if isinstance(d, float):
        return '%g' % d
    return str(d)


def bucket_key(opt, nodes):
    """The row's bucket: the longest node naming its live path's prefix
    (the MANUAL.md knobs tables' rule); a knob without a live path (or
    under no node) rides the general bucket."""
    best = ''
    for n in nodes:
        if opt.live and (opt.live == n.name or opt.live.startswith(n.name + '/')) \
                and len(n.name) > len(best):
            best = n.name
    return best


def render(tool, daemon, stem, intro, demo, notes, rows, raw):
    twins = [o for o in rows if not o.node
             and [e for e in o.env_names() if e]]
    known = {o.name for o in twins}
    for key in demo:
        if key not in known:
            raise SystemExit('gen_env: %s DEMO key %r is no env twin'
                             % (tool, key))
    for key in notes:
        if key not in known:
            raise SystemExit('gen_env: %s NOTES key %r is no env twin'
                             % (tool, key))
    out = []
    w = out.append
    if stem in PROD:
        cp = ("cp env/%s.env.example env/%s.env (the demo stack) or "
              "env/%s.env (the prod stack) and edit."
              % (stem, stem, PROD[stem]))
    else:
        cp = "cp env/%s.env.example env/%s.env and edit." % (stem, stem)
    w(comment("The %s's env file — GENERATED by scripts/gen_env.py from "
              "%s/lib/options.json (the one-knob-one-source rows): every "
              "env twin the registry declares is below — %d of them. "
              "Edit the registry and re-run the generator, never this "
              "file. %s A knob's value resolves flag > env > the bundled "
              "conf > built-in default — an env here overrides the "
              "image's conf knob by knob. Every line starts commented: "
              "the sample value is what the image itself runs (the CMD "
              "flag or an ENV where one pins it, the built-in default "
              "otherwise); a secret's line stays empty — pass it as "
              "file:<path>, an owner-only 0600 file (the F12 discipline)."
              % (daemon, tool, len(twins), cp)))
    for para in intro:
        w('')
        w(comment(para))
    nodes = [o for o in rows if o.node]
    order, buckets = [], {}
    for o in twins:
        b = bucket_key(o, nodes)
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
            w('#%s=%s' % (env, value_of(o, raw.get(o.name, {}), demo)))
    out.append('')
    text = '\n'.join(out)
    for no, line in enumerate(text.splitlines(), 1):
        if len(line) > 78:
            raise SystemExit('%s.env.example:%d: line over 78 bytes: %r'
                             % (tool, no, line))
    return text


def main(argv):
    check = '--check' in argv
    drift = []
    for tool, daemon, stem, intro, demo, notes in TOOLS:
        rows, raw = load(tool)
        page = render(tool, daemon, stem, intro, demo, notes, rows, raw)
        path = os.path.join(REPO, 'docker', 'env', '%s.env.example' % stem)
        if check:
            with open(path, encoding='utf-8') as f:
                if f.read() != page:
                    drift.append(path)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(page)
            print('wrote %s' % path)
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
        raise SystemExit('gen_env: prometheus.env.example promises %s — '
                         'entrypoint-prometheus.sh reads none of them'
                         % ', '.join(unknown))
    if check:
        if drift:
            print('drift: %s' % ', '.join(drift))
            return 1
        print('env examples up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
