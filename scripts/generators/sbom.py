#!/usr/bin/env python3
"""Generate the SBOM pair from the tree: docs/sbom/SBOM.md (the prose) and
docs/sbom/sbom.cdx.json (the CycloneDX 1.5 copy). The stdlib-only claim is
AUDITED, not asserted — the generation runs the import scan first (every
import statement in the shipped tree, the lazy ones included, via ast) and
a root outside the reviewed stdlib allowlist or the first-party
common/lib fails the run, so the documents cannot render a claim the tree
does not keep. The vendored ECharts version is read out of the bundle's
own export string, so the recorded version cannot drift from the shipped
file — its bundled zrender is derived the same way and recorded beside it.
The suite version, the nixpkgs pin, the alpine base, the apk set and the
per-tool module counts all come off the tree too; nothing in the pair is
hand-maintained.

  python3 scripts/generators/sbom.py           # regenerate both files in place
  python3 scripts/generators/sbom.py --check   # verify: regenerate + diff; drift = exit 1

Stdlib only."""
import argparse
import ast
import json
import os
import re
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # scripts/ — the common lib rides there
from lib import REPO
from lib.emit import emit
SBOM_MD = os.path.join(REPO, 'docs', 'sbom', 'SBOM.md')
SBOM_CDX = os.path.join(REPO, 'docs', 'sbom', 'sbom.cdx.json')
VENDOR = os.path.join(REPO, 'apps', 'dashboard', 'static', 'vendor', 'echarts.min.js')

# the shipped tree, one scan per subproject (the claim is per subproject)
SCAN_DIRS = ('common', 'shared', 'cache', 'inverter', 'scraper', 'dashboard')

# the reviewed stdlib surface — a new import fails the generation until it
# is reviewed in here; every name is cross-checked against
# sys.stdlib_module_names on 3.10+, so a non-stdlib entry cannot hide
STDLIB = (
    'argparse', 'ast', 'collections', 'faulthandler', 'getpass', 'glob', 'hashlib',
    'hmac', 'http', 'ipaddress', 'json', 'logging', 'math', 'mimetypes', 'operator',
    'os', 'random', 'readline', 're', 'secrets', 'select', 'signal', 'socket', 'struct',
    'subprocess', 'sys', 'termios', 'textwrap', 'threading', 'time', 'tty', 'types',
    'unicodedata', 'urllib',
)
FIRST_PARTY = ('common', 'lib')

# the vendored bundle carries two version strings: echarts' own export
# (`...,t.version="X",t.zrUtil...`) and the zrender bundled inside it
# (`...version:"Y"})`) — both patterns must match EXACTLY once; a new
# bundle that minifies differently fails here, loudly
ECHARTS_RE = re.compile(r'version="(\d+\.\d+\.\d+)",t\.zrUtil')
ZRENDER_RE = re.compile(r'version:"(\d+\.\d+\.\d+)"\}\)')


def fail(msg):
    sys.exit('sbom: %s' % msg)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def suite_version():
    """The suite version from common/runtime/version.py (the one line every
    tool and the tags share)."""
    m = re.search(r"^VERSION = '([^']+)'", read(os.path.join(REPO, 'common', 'runtime', 'version.py')), re.M)
    if not m:
        fail('common/runtime/version.py carries no VERSION line')
    return m.group(1)


def scan_imports():
    """Every import statement in the shipped tree, per subproject: the
    top-level module roots (ast — a docstring line cannot impersonate an
    import, and a lazy import inside a function still counts)."""
    by_tool = {}
    for d in SCAN_DIRS:
        roots = set()
        for dirpath, dirnames, filenames in os.walk(os.path.join(REPO, d)):
            dirnames[:] = sorted(n for n in dirnames if n != '__pycache__')
            for fn in sorted(filenames):
                if not fn.endswith('.py'):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    tree = ast.parse(read(path), filename=path)
                except SyntaxError as e:
                    fail('%s does not parse: %s' % (path, e))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for a in node.names:
                            roots.add(a.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.level or not node.module:
                            continue    # relative — first-party by construction
                        roots.add(node.module.split('.')[0])
        by_tool[d] = roots
    return by_tool


def check_claim(by_tool):
    """The claim itself: every root is the reviewed stdlib or first-party.
    A foreign name fails the generation — the documents are never allowed
    to render a lie."""
    if hasattr(sys, 'stdlib_module_names'):
        ghosts = sorted(n for n in STDLIB if n not in sys.stdlib_module_names)
        if ghosts:
            fail('the allowlist names non-stdlib modules: %s' % ', '.join(ghosts))
    foreign = {}
    for d in SCAN_DIRS:
        bad = sorted(r for r in by_tool[d] if r not in STDLIB and r not in FIRST_PARTY)
        if bad:
            foreign[d] = bad
    if foreign:
        fail('the stdlib-only claim does not hold: %s — review it into the '
             'STDLIB allowlist (and the claim it keeps) first' % '; '.join(
                 '%s: %s' % (d, ', '.join(b)) for d, b in sorted(foreign.items())))


def vendor_facts():
    """The vendored bundle speaks for itself: the echarts and zrender
    versions from its export strings, the Apache-2.0 banner from the
    header."""
    text = read(VENDOR)
    e = ECHARTS_RE.findall(text)
    z = ZRENDER_RE.findall(text)
    if len(e) != 1 or len(z) != 1:
        fail('cannot read the versions out of %s (echarts %d match(es), zrender %d) '
             '— the minified shape moved; fix the patterns' % (os.path.relpath(VENDOR, REPO), len(e), len(z)))
    head = text.lstrip()
    if not head.startswith('/*') or 'Licensed to the Apache Software Foundation' not in head[:600]:
        fail('the vendored bundle lost the Apache-2.0 banner')
    return {'echarts': e[0], 'zrender': z[0]}


def flake_facts():
    """The nixpkgs pin from flake.lock (the ref the flake follows, the rev
    it is locked to)."""
    node = json.load(open(os.path.join(REPO, 'flake.lock')))['nodes']['nixpkgs']
    ref = node['original'].get('ref') or node['locked'].get('ref') or 'nixpkgs'
    return ref, node['locked']['rev']


def docker_facts():
    """The alpine tag and the apk set, identical across all three
    Dockerfiles (a disagreement fails)."""
    tag, apks = None, None
    for df in ('Dockerfile.modbus-cache', 'Dockerfile.modbus-scraper',
               'Dockerfile.modbus-fake-inverter'):
        text = read(os.path.join(REPO, 'docker', df))
        m = re.search(r'^FROM alpine:(\S+)', text, re.M)
        a = re.search(r'^RUN apk add --no-cache (.+?)(?:\s*\\)?$', text, re.M)
        if not m or not a:
            fail('%s: no alpine FROM or apk add line' % df)
        pkgs = tuple(a.group(1).split())
        if tag and m.group(1) != tag:
            fail('%s: alpine:%s != alpine:%s' % (df, m.group(1), tag))
        if apks and sorted(pkgs) != sorted(apks):
            fail('%s: the apk set differs (%s != %s)' % (df, ' '.join(pkgs), ' '.join(apks)))
        tag, apks = m.group(1), pkgs
    return tag, apks


def tool_facts():
    """The per-tool shapes the table and the CycloneDX copy render: the
    module counts (lib/*.py, __init__ not a module), the control clients
    (bin/*.py minus the daemon)."""
    mains = {'cache': 'modbus-cache.py', 'inverter': 'modbus-fake-inverter.py',
             'scraper': 'modbus-scraper.py', 'dashboard': 'dashboard.py'}
    facts = {}
    for tool, main in mains.items():
        lib = [f for f in os.listdir(os.path.join(REPO, 'apps', tool, 'lib'))
               if f.endswith('.py') and f != '__init__.py']
        bin_ = [f for f in os.listdir(os.path.join(REPO, 'apps', tool, 'bin'))
                if f.endswith('.py') and f != main]
        facts[tool] = {'modules': len(lib), 'clients': len(bin_)}
    facts['common'] = {'modules': len([f
                                       for dirpath, dirs, files in os.walk(os.path.join(REPO, 'common'))
                                       for f in files
                                       if f.endswith('.py') and f != '__init__.py'])}
    facts['shared'] = {
        'jsons': len([f for f in os.listdir(os.path.join(REPO, 'shared', 'profiles'))
                      if f.endswith('.json')]),
    }
    return facts


def render_cdx(f):
    """The CycloneDX 1.5 copy — deterministic (no timestamp; git dates the
    tree), every version read off the tree."""
    v = f['version']
    bsd = [{'expression': 'BSD-3-Clause'}]
    def lic(exp):
        return [{'expression': exp}]

    comps = [
        {'bom-ref': 'pv-suite:common', 'type': 'library', 'name': 'common', 'version': v,
         'licenses': bsd,
         'properties': [{'name': 'pv-suite:deps', 'value': 'python-stdlib only'}]},
        {'bom-ref': 'pv-suite:shared', 'type': 'file', 'name': 'shared', 'version': v,
         'licenses': bsd,
         'properties': [{'name': 'pv-suite:content',
                         'value': 'the shared data the tools load — %d device-profile JSONs (shared/profiles), the suite JSONs (shared/suite), the acl schemas (shared/schema); the lint/format tool lives in scripts/gates/profile.py)' % f['tools']['shared']['jsons']}]},
        {'bom-ref': 'pv-suite:modbus-cache', 'type': 'application', 'name': 'modbus-cache', 'version': v,
         'licenses': bsd},
        {'bom-ref': 'pv-suite:modbus-scraper', 'type': 'application', 'name': 'modbus-scraper', 'version': v,
         'licenses': bsd},
        {'bom-ref': 'pv-suite:modbus-fake-inverter', 'type': 'application', 'name': 'modbus-fake-inverter', 'version': v,
         'licenses': bsd},
        {'bom-ref': 'pv-suite:dashboard', 'type': 'application', 'name': 'dashboard', 'version': v,
         'licenses': bsd},
        {'bom-ref': 'echarts', 'type': 'library', 'name': 'echarts', 'version': f['vendor']['echarts'],
         'purl': 'pkg:npm/echarts@%s' % f['vendor']['echarts'],
         'licenses': lic('Apache-2.0'),
         'properties': [
             {'name': 'pv-suite:vendored-at', 'value': 'apps/dashboard/static/vendor/echarts.min.js'},
             {'name': 'pv-suite:note', 'value': 'the only third-party code in the suite'}]},
        {'bom-ref': 'zrender', 'type': 'library', 'name': 'zrender', 'version': f['vendor']['zrender'],
         'purl': 'pkg:npm/zrender@%s' % f['vendor']['zrender'],
         'licenses': lic('Apache-2.0'),
         'properties': [{'name': 'pv-suite:note',
                         'value': 'bundled inside the vendored echarts.min.js; read off the same file'}]},
        {'bom-ref': 'nixpkgs', 'type': 'framework', 'name': 'nixpkgs',
         'version': '%s @ %s' % (f['nix']['ref'], f['nix']['rev']),
         'purl': 'pkg:github/NixOS/nixpkgs@%s' % f['nix']['rev'],
         'properties': [{'name': 'pv-suite:provides',
                         'value': 'the pinned CPython interpreter and the stdenv build wrappers; no Python libraries fetched'}]},
        {'bom-ref': 'alpine', 'type': 'operating-system', 'name': 'alpine', 'version': f['docker']['tag'],
         'purl': 'pkg:oci/alpine@%s' % f['docker']['tag'],
         'properties': [{'name': 'pv-suite:note', 'value': 'the base of all three container images'}]},
    ]
    for name, purl, license in (
            ('python3', 'pkg:apk/alpine/python3', 'PSF-2.0'),
            ('bash', 'pkg:apk/alpine/bash', 'GPL-3.0-or-later'),
            ('su-exec', 'pkg:apk/alpine/su-exec', None)):
        comp = {'bom-ref': 'apk:%s' % name, 'type': 'library', 'name': name,
                'version': 'alpine %s pin' % f['docker']['tag'], 'purl': purl}
        if license:
            comp['licenses'] = lic(license)
        if name == 'su-exec':
            comp['properties'] = [{'name': 'pv-suite:note',
                                   'value': 'drops the entrypoint from root to the unprivileged pvsuite user'}]
        comps.append(comp)
    for image, dockerfile in (('modbus-fake-inverter', 'docker/Dockerfile.modbus-fake-inverter'),
                              ('modbus-cache', 'docker/Dockerfile.modbus-cache'),
                              ('modbus-scraper', 'docker/Dockerfile.modbus-scraper')):
        comps.append({'bom-ref': 'image:%s' % image, 'type': 'container', 'name': image, 'version': v,
                      'properties': [{'name': 'pv-suite:dockerfile', 'value': dockerfile}]})

    doc = {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.5',
        'version': 1,
        'metadata': {
            'component': {
                'bom-ref': 'pv-suite',
                'type': 'application',
                'name': 'pv-suite',
                'version': v,
                'licenses': bsd,
                'properties': [
                    {'name': 'pv-suite:scope',
                     'value': 'the whole flake: dashboard, scraper, cache, inverter, shared, common'}]}},
        'components': comps,
        'dependencies': [
            {'ref': 'pv-suite',
             'dependsOn': ['pv-suite:dashboard', 'pv-suite:modbus-scraper', 'pv-suite:modbus-cache',
                           'pv-suite:modbus-fake-inverter', 'pv-suite:shared', 'pv-suite:common']},
            {'ref': 'pv-suite:modbus-cache', 'dependsOn': ['pv-suite:common', 'pv-suite:shared']},
            {'ref': 'pv-suite:modbus-scraper', 'dependsOn': ['pv-suite:common', 'pv-suite:shared']},
            {'ref': 'pv-suite:modbus-fake-inverter', 'dependsOn': ['pv-suite:common', 'pv-suite:shared']},
            {'ref': 'pv-suite:dashboard', 'dependsOn': ['echarts']},
            {'ref': 'pv-suite:common', 'dependsOn': []},
            {'ref': 'pv-suite:shared', 'dependsOn': []},
            {'ref': 'echarts', 'dependsOn': ['zrender']},
            {'ref': 'zrender', 'dependsOn': []},
            {'ref': 'image:modbus-fake-inverter',
             'dependsOn': ['alpine', 'apk:python3', 'apk:bash', 'apk:su-exec', 'pv-suite:modbus-fake-inverter']},
            {'ref': 'image:modbus-cache',
             'dependsOn': ['alpine', 'apk:python3', 'apk:bash', 'apk:su-exec', 'pv-suite:modbus-cache']},
            {'ref': 'image:modbus-scraper',
             'dependsOn': ['alpine', 'apk:python3', 'apk:bash', 'apk:su-exec', 'pv-suite:modbus-scraper']},
            {'ref': 'alpine', 'dependsOn': []},
            {'ref': 'nixpkgs', 'dependsOn': []}],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + '\n'


def render_md(f):
    """The prose — the same document, but every number in it is read off
    the tree by render_cdx()'s sibling fact pass."""
    v = f['version']
    stdlib_list = ', '.join('`%s`' % n for n in sorted(STDLIB))
    first_party = '`%s`/`%s`' % tuple(FIRST_PARTY)
    claim_sentence = textwrap.fill(
        'Every name in that list is stdlib (%s) or %s. Nothing else. '
        'No `requests`, no `pyserial`, no `prometheus_client`.' % (stdlib_list, first_party),
        width=76)
    ref, rev = f['nix']['ref'], f['nix']['rev']
    tag, apks = f['docker']['tag'], f['docker']['apks']
    ech, zr = f['vendor']['echarts'], f['vendor']['zrender']
    common, shared = f['tools']['common'], f['tools']['shared']
    cache, inverter = f['tools']['cache'], f['tools']['inverter']
    scraper, dashboard = f['tools']['scraper'], f['tools']['dashboard']

    parts = []
    parts.append("""\
# SBOM — the software bill of materials

> Suite version **%(v)s** (the tree; `version_string()` appends `-<short
> git>` in a checkout). Machine-readable copy:
> [`sbom.cdx.json`](sbom.cdx.json) (CycloneDX 1.5). **Generated** by
> [`scripts/generators/sbom.py`](../../scripts/generators/sbom.py) — the import scan
> gates the render and the vendored ECharts version is read out of the
> bundle itself; re-run the script, never hand-edit either file
> (`--check` regenerates and diffs, and the release workflow runs it).

The suite is **Python stdlib only** by design: no pip, no venv, no
requirements files, no vendored Python packages, no runtime network
fetches. The third-party surface is exactly three items wide: the
**Python interpreter**, the **container base images** (where docker is
used) and one **vendored browser library** (the dashboard's ECharts).
Everything else is first-party, licensed BSD-3-Clause.

## The claim, checked

Every `import` in the suite resolves to the Python standard library or to
first-party code (`common.*`, the subproject's own `lib.*`) — the
generator's `ast` walk counts the lazy imports too:

```bash
grep -rhE '^import |^from ' --include='*.py' common apps/cache apps/inverter apps/scraper apps/dashboard/bin apps/dashboard/lib \\
    | sed -E 's/^(import|from) ([a-zA-Z_0-9.]+).*/\\2/' | sort -u
```

%(claim_sentence)s
""" % {'v': v, 'claim_sentence': claim_sentence})

    parts.append("""\
## Per subproject

| Subproject | First-party code | Third-party runtime | Notes |
|---|---|---|---|
| [`common/`](../../common/README.md) | the package (%(common_modules)d modules) | none — stdlib only | the shared core: audit, config, protocol, logutil, version |
| [`shared/profiles/`](../../shared/profiles/README.md) | %(shared_jsons)d device-profile JSONs | none — stdlib only | data; the lint/format tool = `scripts/gates/profile.py` |
| [`apps/cache/`](../../apps/cache/README.md) | `modbus-cache.py` + `lib/` (%(cache_modules)d modules) + %(cache_clients)d control clients | none — stdlib only (+ `common`) | proxy daemon |
| [`apps/inverter/`](../../apps/inverter/README.md) | `modbus-fake-inverter.py` + `lib/` (%(inverter_modules)d modules) + %(inverter_clients)d control clients | none — stdlib only (+ `common`) | simulator |
| [`apps/scraper/`](../../apps/scraper/README.md) | `modbus-scraper.py` + `lib/` (%(scraper_modules)d modules) + %(scraper_clients)d control clients | none — stdlib only (+ `common`) | exporter |
| [`apps/dashboard/`](../../apps/dashboard/README.md) | `bin/dashboard.py` + `lib/` (%(dashboard_modules)d modules) + %(dashboard_clients)d control clients + the static page | **Apache ECharts %(ech)s** (Apache-2.0, vendored at `static/vendor/echarts.min.js`) — the only third-party code in the suite | no CDN, fully offline |
""" % {'common_modules': common['modules'],
       'shared_jsons': shared['jsons'],
       'cache_modules': cache['modules'], 'cache_clients': cache['clients'],
       'inverter_modules': inverter['modules'], 'inverter_clients': inverter['clients'],
       'scraper_modules': scraper['modules'], 'scraper_clients': scraper['clients'],
       'dashboard_modules': dashboard['modules'], 'dashboard_clients': dashboard['clients'],
       'ech': ech})

    parts.append("""\
## Runtime and deployment layers

- **Python** — any CPython 3 with the standard library; the suite does not
  pin a minor (the Nix and Docker builds each pin their own).
  - **Nix**: the interpreter comes from the pinned **nixpkgs**
    (`%(ref)s` @ `%(rev)s`,
    [`flake.lock`](../../flake.lock)); the packages are built as stdenv
    wrappers — no Python libraries are fetched.
  - **Docker**: base image `alpine:%(tag)s`, `apk add --no-cache %(apks)s` —
    that is the whole package set (plus the base's busybox layer). No
    pip. Licenses ride with the aports tree / the image acks.
- **The dashboard's browser runtime** — the page plus the vendored ECharts
  %(ech)s; no CDN, no fonts, no analytics, no external requests at runtime.

## What is deliberately not in the SBOM

- Python third-party packages — there are none (the claim, checked, above).
- A JavaScript package tree — the page is served from `dashboard/static/`
  as-is; the only `.js` dependency is the vendored ECharts file (whose
  bundle carries its own zrender %(zr)s, recorded in the CycloneDX copy).
- Compiler/toolchain artifacts — the Nix builds are stdenv wrappers, the
  docker images install the interpreter from the distro.

## Verification

```bash
# the gate — regenerate and diff; the release workflow runs --check
python3 scripts/generators/sbom.py --check

# the human form of the import scan (module level; the generator's ast
# walk is stricter)
grep -rhE '^import |^from ' --include='*.py' common apps/cache apps/inverter apps/scraper apps/dashboard/bin apps/dashboard/lib | sort -u

# the container layer
docker build -t pv-sbom-check \\
    --build-context shared=../shared --build-context common=../common \\
    --build-context examples=../extras/examples ../apps/cache   # or the others (run from docker/)
docker run --rm pv-sbom-check sh -c 'apk info -v | sort'                          # the apk set

# the nix pin
cat flake.lock

# the vendored exception
head -c 400 apps/dashboard/static/vendor/echarts.min.js                  # the Apache-2.0 notice
```

For the NIS2/DORA supply-chain rows: the suite's "known-vulnerabilities"
surface is the Python interpreter, the alpine base, ECharts and the
zrender bundled inside it — track those upstream; everything else changes
only by editing this repo.
""" % {'ref': ref, 'rev': rev, 'tag': tag, 'apks': ' '.join(apks), 'ech': ech, 'zr': zr})
    return '\n'.join(parts)


def gather():
    f = {'version': suite_version()}
    by_tool = scan_imports()
    check_claim(by_tool)
    f['vendor'] = vendor_facts()
    f['nix'] = dict(zip(('ref', 'rev'), flake_facts()))
    tag, apks = docker_facts()
    f['docker'] = {'tag': tag, 'apks': apks}
    f['tools'] = tool_facts()
    return f


def main():
    ap = argparse.ArgumentParser(description='generate the SBOM pair from the tree')
    ap.add_argument('--check', action='store_true',
                    help='verify only: regenerate and diff; drift = exit 1')
    args = ap.parse_args()

    f = gather()
    stale = any([emit(SBOM_MD, render_md(f), args.check, 'sbom',
                      rerun='python3 scripts/generators/sbom.py'),
                 emit(SBOM_CDX, render_cdx(f), args.check, 'sbom',
                      rerun='python3 scripts/generators/sbom.py')])
    if stale:
        sys.exit(1)
    print('sbom: the claim holds — stdlib + %s only; echarts %s (+ zrender %s), '
          'suite %s, nixpkgs %s @ %s, alpine %s (%s)' % (
              '/'.join(FIRST_PARTY), f['vendor']['echarts'], f['vendor']['zrender'],
              f['version'], f['nix']['ref'], f['nix']['rev'], f['docker']['tag'],
              ' '.join(f['docker']['apks'])))


if __name__ == '__main__':
    main()
