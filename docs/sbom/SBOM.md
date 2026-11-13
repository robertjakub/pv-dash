# SBOM — the software bill of materials

> Suite version **0.5.0** (the tree; `version_string()` appends `-<short
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
grep -rhE '^import |^from ' --include='*.py' common apps/cache apps/inverter apps/scraper apps/dashboard/bin apps/dashboard/lib \
    | sed -E 's/^(import|from) ([a-zA-Z_0-9.]+).*/\2/' | sort -u
```

Every name in that list is stdlib (`argparse`, `ast`, `collections`,
`faulthandler`, `getpass`, `glob`, `hashlib`, `hmac`, `http`, `ipaddress`,
`json`, `logging`, `math`, `mimetypes`, `operator`, `os`, `random`, `re`,
`readline`, `secrets`, `select`, `signal`, `socket`, `struct`, `subprocess`,
`sys`, `termios`, `textwrap`, `threading`, `time`, `tty`, `types`,
`unicodedata`, `urllib`) or `common`/`lib`. Nothing else. No `requests`, no
`pyserial`, no `prometheus_client`.

## Per subproject

| Subproject | First-party code | Third-party runtime | Notes |
|---|---|---|---|
| [`common/`](../../common/README.md) | the package (21 modules) | none — stdlib only | the shared core: audit, config, protocol, logutil, version |
| [`shared/profiles/`](../../shared/profiles/README.md) | 6 device-profile JSONs | none — stdlib only | data; the lint/format tool = `scripts/gates/profile.py` |
| [`apps/cache/`](../../apps/cache/README.md) | `modbus-cache.py` + `lib/` (11 modules) + 1 control clients | none — stdlib only (+ `common`) | proxy daemon |
| [`apps/inverter/`](../../apps/inverter/README.md) | `modbus-fake-inverter.py` + `lib/` (13 modules) + 1 control clients | none — stdlib only (+ `common`) | simulator |
| [`apps/scraper/`](../../apps/scraper/README.md) | `modbus-scraper.py` + `lib/` (11 modules) + 1 control clients | none — stdlib only (+ `common`) | exporter |
| [`apps/dashboard/`](../../apps/dashboard/README.md) | `bin/dashboard.py` + `lib/` (7 modules) + 1 control clients + the static page | **Apache ECharts 5.5.1** (Apache-2.0, vendored at `static/vendor/echarts.min.js`) — the only third-party code in the suite | no CDN, fully offline |

## Runtime and deployment layers

- **Python** — any CPython 3 with the standard library; the suite does not
  pin a minor (the Nix and Docker builds each pin their own).
  - **Nix**: the interpreter comes from the pinned **nixpkgs**
    (`nixos-unstable` @ `d4f25a3e562008648d45bcf2d70bcc7422cad84e`,
    [`flake.lock`](../../flake.lock)); the packages are built as stdenv
    wrappers — no Python libraries are fetched.
  - **Docker**: base image `alpine:3.20`, `apk add --no-cache python3 bash su-exec` —
    that is the whole package set (plus the base's busybox layer). No
    pip. Licenses ride with the aports tree / the image acks.
- **The dashboard's browser runtime** — the page plus the vendored ECharts
  5.5.1; no CDN, no fonts, no analytics, no external requests at runtime.

## What is deliberately not in the SBOM

- Python third-party packages — there are none (the claim, checked, above).
- A JavaScript package tree — the page is served from `dashboard/static/`
  as-is; the only `.js` dependency is the vendored ECharts file (whose
  bundle carries its own zrender 5.6.0, recorded in the CycloneDX copy).
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
docker build -t pv-sbom-check \
    --build-context shared=../shared --build-context common=../common \
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
