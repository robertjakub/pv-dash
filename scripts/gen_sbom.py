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

  python3 scripts/gen_sbom.py           # regenerate both files in place
  python3 scripts/gen_sbom.py --check   # verify: regenerate + diff; drift = exit 1

Stdlib only."""
import argparse
import ast
import difflib
import json
import os
import re
import sys
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SBOM_MD = os.path.join(REPO, 'docs', 'sbom', 'SBOM.md')
SBOM_CDX = os.path.join(REPO, 'docs', 'sbom', 'sbom.cdx.json')
VENDOR = os.path.join(REPO, 'dashboard', 'static', 'vendor', 'echarts.min.js')

# the shipped tree, one scan per subproject (the claim is per subproject)
SCAN_DIRS = ('common', 'profiles', 'cache', 'inverter', 'scraper', 'dashboard')

# the reviewed stdlib surface — a new import fails the generation until it
# is reviewed in here; every name is cross-checked against
# sys.stdlib_module_names on 3.10+, so a non-stdlib entry cannot hide
STDLIB = (
    'argparse', 'collections', 'getpass', 'glob', 'hashlib', 'hmac', 'http',
    'ipaddress', 'json', 'logging', 'math', 'mimetypes', 'os', 'random',
    'readline', 're', 'signal', 'socket', 'struct', 'subprocess', 'sys',
    'textwrap', 'threading', 'time', 'urllib',
)
FIRST_PARTY = ('common', 'lib')

# the vendored bundle carries two version strings: echarts' own export
# (`...,t.version="X",t.zrUtil...`) and the zrender bundled inside it
# (`...version:"Y"})`) — both patterns must match EXACTLY once; a new
# bundle that minifies differently fails here, loudly
ECHARTS_RE = re.compile(r'version="(\d+\.\d+\.\d+)",t\.zrUtil')
ZRENDER_RE = re.compile(r'version:"(\d+\.\d+\.\d+)"\}\)')


def fail(msg):
    sys.exit('gen_sbom: %s' % msg)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def suite_version():
    """The suite version from common/version.py (the one line every tool
    and the tags share)."""
    m = re.search(r"^VERSION = '([^']+)'", read(os.path.join(REPO, 'common', 'version.py')), re.M)
    if not m:
        fail('common/version.py carries no VERSION line')
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
    for df in ('Dockerfile.cache', 'Dockerfile.scraper', 'Dockerfile.inverter'):
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
        lib = [f for f in os.listdir(os.path.join(REPO, tool, 'lib'))
               if f.endswith('.py') and f != '__init__.py']
        bin_ = [f for f in os.listdir(os.path.join(REPO, tool, 'bin'))
                if f.endswith('.py') and f != main]
        facts[tool] = {'modules': len(lib), 'clients': len(bin_)}
    facts['common'] = {'modules': len([f for f in os.listdir(os.path.join(REPO, 'common'))
                                       if f.endswith('.py') and f != '__init__.py'])}
    facts['profiles'] = {
        'jsons': len([f for f in os.listdir(os.path.join(REPO, 'profiles', 'profiles'))
                      if f.endswith('.json')]),
        'tools': len([f for f in os.listdir(os.path.join(REPO, 'profiles', 'bin'))
                      if f.endswith('.py')]),
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
        {'bom-ref': 'pv-suite:profiles', 'type': 'file', 'name': 'profiles', 'version': v,
         'licenses': bsd,
         'properties': [{'name': 'pv-suite:content',
                         'value': '%d device-profile JSONs + profile-lint.py + profile-format.py (stdlib only)' % f['tools']['profiles']['jsons']}]},
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
             {'name': 'pv-suite:vendored-at', 'value': 'dashboard/static/vendor/echarts.min.js'},
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
    for image, dockerfile in (('fake-inverter', 'docker/Dockerfile.inverter'),
                              ('modbus-cache', 'docker/Dockerfile.cache'),
                              ('modbus-scraper', 'docker/Dockerfile.scraper')):
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
                     'value': 'the whole flake: dashboard, scraper, cache, inverter, profiles, common'}]}},
        'components': comps,
        'dependencies': [
            {'ref': 'pv-suite',
             'dependsOn': ['pv-suite:dashboard', 'pv-suite:modbus-scraper', 'pv-suite:modbus-cache',
                           'pv-suite:modbus-fake-inverter', 'pv-suite:profiles', 'pv-suite:common']},
            {'ref': 'pv-suite:modbus-cache', 'dependsOn': ['pv-suite:common', 'pv-suite:profiles']},
            {'ref': 'pv-suite:modbus-scraper', 'dependsOn': ['pv-suite:common', 'pv-suite:profiles']},
            {'ref': 'pv-suite:modbus-fake-inverter', 'dependsOn': ['pv-suite:common', 'pv-suite:profiles']},
            {'ref': 'pv-suite:dashboard', 'dependsOn': ['echarts']},
            {'ref': 'pv-suite:common', 'dependsOn': []},
            {'ref': 'pv-suite:profiles', 'dependsOn': []},
            {'ref': 'echarts', 'dependsOn': ['zrender']},
            {'ref': 'zrender', 'dependsOn': []},
            {'ref': 'image:fake-inverter',
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
    common, profiles = f['tools']['common'], f['tools']['profiles']
    cache, inverter = f['tools']['cache'], f['tools']['inverter']
    scraper, dashboard = f['tools']['scraper'], f['tools']['dashboard']

    parts = []
    parts.append("""\
# SBOM — the software bill of materials

> Suite version **%(v)s** (the tree; `version_string()` appends `-<short
> git>` in a checkout). Machine-readable copy:
> [`sbom.cdx.json`](sbom.cdx.json) (CycloneDX 1.5). **Generated** by
> [`scripts/gen_sbom.py`](../../scripts/gen_sbom.py) — the import scan
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
grep -rhE '^import |^from ' --include='*.py' common cache inverter scraper dashboard/bin dashboard/lib profiles/bin \\
    | sed -E 's/^(import|from) ([a-zA-Z_0-9.]+).*/\\2/' | sort -u
```

%(claim_sentence)s
""" % {'v': v, 'claim_sentence': claim_sentence})

    parts.append("""\
## Per subproject

| Subproject | First-party code | Third-party runtime | Notes |
|---|---|---|---|
| [`common/`](../../common/README.md) | the package (%(common_modules)d modules) | none — stdlib only | the shared core: audit, config, protocol, logutil, version |
| [`profiles/`](../../profiles/README.md) | %(profiles_jsons)d device-profile JSONs + %(profiles_tools)d tools | none — stdlib only | data + linter/formatter |
| [`cache/`](../../cache/README.md) | `modbus-cache.py` + `lib/` (%(cache_modules)d modules) + %(cache_clients)d control clients | none — stdlib only (+ `common`) | proxy daemon |
| [`inverter/`](../../inverter/README.md) | `modbus-fake-inverter.py` + `lib/` (%(inverter_modules)d modules) + %(inverter_clients)d control clients | none — stdlib only (+ `common`) | simulator |
| [`scraper/`](../../scraper/README.md) | `modbus-scraper.py` + `lib/` (%(scraper_modules)d modules) + %(scraper_clients)d control clients | none — stdlib only (+ `common`) | exporter |
| [`dashboard/`](../../dashboard/README.md) | `bin/dashboard.py` + `lib/` (%(dashboard_modules)d modules) + %(dashboard_clients)d control clients + the static page | **Apache ECharts %(ech)s** (Apache-2.0, vendored at `static/vendor/echarts.min.js`) — the only third-party code in the suite | no CDN, fully offline |
""" % {'common_modules': common['modules'],
       'profiles_jsons': profiles['jsons'], 'profiles_tools': profiles['tools'],
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
python3 scripts/gen_sbom.py --check

# the human form of the import scan (module level; the generator's ast
# walk is stricter)
grep -rhE '^import |^from ' --include='*.py' common cache inverter scraper dashboard/bin dashboard/lib profiles/bin | sort -u

# the container layer
docker build -t pv-sbom-check --build-context profiles=../profiles \\
    --build-context scripts=../docker --build-context common=../common ../cache   # or the others
docker run --rm pv-sbom-check sh -c 'apk info -v | sort'                          # the apk set

# the nix pin
cat flake.lock

# the vendored exception
head -c 400 dashboard/static/vendor/echarts.min.js                            # the Apache-2.0 notice
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


def emit(path, content, check):
    """Write the file (or, under --check, report the drift). True = the
    file moved."""
    rel = os.path.relpath(path, REPO)
    if os.path.exists(path) and read(path) == content:
        print('gen_sbom: %s current' % rel)
        return False
    if check:
        diff = '\n'.join(difflib.unified_diff(read(path).splitlines(), content.splitlines(),
                                              'a/' + rel, 'b/' + rel, lineterm=''))
        print(diff)
        print('gen_sbom: %s is stale — re-run python3 scripts/gen_sbom.py' % rel)
        return True
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(content)
    print('gen_sbom: wrote %s' % rel)
    return False


def main():
    ap = argparse.ArgumentParser(description='generate the SBOM pair from the tree')
    ap.add_argument('--check', action='store_true',
                    help='verify only: regenerate and diff; drift = exit 1')
    args = ap.parse_args()

    f = gather()
    stale = any([emit(SBOM_MD, render_md(f), args.check),
                 emit(SBOM_CDX, render_cdx(f), args.check)])
    if stale:
        sys.exit(1)
    print('gen_sbom: the claim holds — stdlib + %s only; echarts %s (+ zrender %s), '
          'suite %s, nixpkgs %s @ %s, alpine %s (%s)' % (
              '/'.join(FIRST_PARTY), f['vendor']['echarts'], f['vendor']['zrender'],
              f['version'], f['nix']['ref'], f['nix']['rev'], f['docker']['tag'],
              ' '.join(f['docker']['apks'])))


if __name__ == '__main__':
    main()
