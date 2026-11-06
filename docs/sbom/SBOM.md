# SBOM — the software bill of materials

> Suite version **0.3.0** (the tree; `version_string()` appends `-<short
> git>` in a checkout). Machine-readable copy:
> [`sbom.cdx.json`](sbom.cdx.json) (CycloneDX 1.5). Regenerate nothing by
> hand when this changes — the document and the JSON move with the same
> commit.

The suite is **Python stdlib only** by design: no pip, no venv, no
requirements files, no vendored Python packages, no runtime network fetches.
The third-party surface is exactly three items wide: the **Python
interpreter**, the **container base images** (where docker is used) and one
**vendored browser library** (the dashboard's ECharts). Everything else is
first-party, licensed BSD-3-Clause.

## The claim, checked

Every `import` in the suite resolves to the Python standard library or to
first-party code (`common.*`, the subproject's own `lib.*`):

```bash
grep -rhE '^import |^from ' --include='*.py' common cache inverter scraper dashboard/bin dashboard/lib profiles/bin \
    | sed -E 's/^(import|from) ([a-zA-Z_0-9.]+).*/\2/' | sort -u
```

Every name in that list is stdlib (`argparse`, `collections`, `getpass`,
`glob`, `hashlib`, `hmac`, `http.server`, `ipaddress`, `json`, `logging`,
`math`, `mimetypes`, `os`, `random`, `re`, `signal`, `socket`, `struct`,
`subprocess`, `sys`, `textwrap`, `threading`, `time`, `urllib`) or
`common`/`lib`. Nothing else. No `requests`, no `pyserial`, no `prometheus_client`.

## Per subproject

| Subproject | First-party code | Third-party runtime | Notes |
|---|---|---|---|
| [`common/`](common/README.md) | the package (12 modules) | none — stdlib only | the shared core: audit, config, protocol, logutil, version |
| [`profiles/`](profiles/README.md) | 4 device-profile JSONs + 2 tools | none — stdlib only | data + linter/formatter |
| [`cache/`](cache/README.md) | `modbus-cache.py` + `lib/` (12 modules) + 2 control clients | none — stdlib only (+ `common`) | proxy daemon |
| [`inverter/`](inverter/README.md) | `modbus-fake-inverter.py` + `lib/` (13 modules) + 2 control clients | none — stdlib only (+ `common`) | simulator |
| [`scraper/`](scraper/README.md) | `modbus-scraper.py` + `lib/` (10 modules) | none — stdlib only (+ `common`) | exporter |
| [`dashboard/`](dashboard/README.md) | `bin/dashboard.py` + the static page | **Apache ECharts 5.5.1** (Apache-2.0, vendored at `static/vendor/echarts.min.js`) — the only third-party code in the suite | no CDN, fully offline |

## Runtime and deployment layers

- **Python** — any CPython 3 with the standard library; the suite does not
  pin a minor (the Nix and Docker builds each pin their own).
  - **Nix**: the interpreter comes from the pinned **nixpkgs**
    (`nixos-unstable` @ `1d060086d60cb76a40cf37109f979d88a5bd6396`,
    [`flake.lock`](flake.lock)); the packages are built as stdenv
    wrappers — no Python libraries are fetched.
  - **Docker**: base image `alpine:3.20`, `apk add --no-cache python3 bash
    su-exec` — that is the whole package set (plus the base's busybox
    layer). No pip. Licenses ride with the aports tree / the image acks.
- **The dashboard's browser runtime** — the page plus the vendored ECharts
  5.5.1; no CDN, no fonts, no analytics, no external requests at runtime.

## What is deliberately not in the SBOM

- Python third-party packages — there are none (the claim, checked, above).
- A JavaScript package tree — the page is served from `dashboard/static/`
  as-is; the only `.js` dependency is the vendored ECharts file.
- Compiler/toolchain artifacts — the Nix builds are stdenv wrappers, the
  docker images install the interpreter from the distro.

## Verification

```bash
# the import claim (above) — stdlib + common/lib only
grep -rhE '^import |^from ' --include='*.py' common cache inverter scraper dashboard/bin dashboard/lib profiles/bin | sort -u

# the container layer
docker build -t pv-sbom-check --build-context profiles=../profiles \
    --build-context scripts=../docker --build-context common=../common ../cache   # or the others
docker run --rm pv-sbom-check sh -c 'apk info -v | sort'                          # the apk set

# the nix pin
cat flake.lock

# the vendored exception
head -c 400 dashboard/static/vendor/echarts.min.js                            # the Apache-2.0 notice
```

For the NIS2/DORA supply-chain rows: the suite's "known-vulnerabilities"
surface is the Python interpreter, the alpine base and ECharts — track
those three upstream; everything else changes only by editing this repo.
