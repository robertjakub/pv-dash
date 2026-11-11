# The suite's shape (ARCHITECTURE.md)

One product, four tools: the modbus-cache proxy, the modbus-scraper
exporter, the modbus-fake-inverter and the dashboard — one shared core
(`common/`), one control-wire grammar, one option registry per tool.
This page is the map, not the specs: every doc filed by grain, one
home per story, the ledgers split current vs history.

## The shape

- **the data plane** — the fake serves the register profile; the cache
  proxies it (the write-through, the caps, the auth handshake); the
  scraper polls an upstream (the cache or a real device) and exports
  `/metrics` for the prometheus pull; the dashboard renders a
  `/metrics` source.
- **the control plane** — every tool serves the same wire
  (`common/wire/control.py`): the signed frames, the peer-cred trusted
  peers, the RBAC roles, the ctl/cli consoles speaking the one command
  spine (`common/control.py`).
- **the config plane** — the resolver ladder flag > env > config
  script > the registry row's default, one registry per tool
  (`<tool>/lib/options.json`), the knobs settable live or
  restart-marked, the secrets startup-only.

## The docs, filed by grain

| Grain | Home |
|---|---|
| the mechanism specs (the shared core) | [common/MODBUS.md](common/MODBUS.md) (the protocol, the profiles, the auth), [common/ACL.md](common/ACL.md) (the gates), [common/static-defaults.md](common/static-defaults.md) (the defaults ladder + the gate) |
| the security ledger | [SECURITY.md](SECURITY.md) — the findings, the posture, the NIS2/DORA map; the closed half in [history/AUDIT.md](history/AUDIT.md) |
| the ledgers (open vs history) | [TODO.md](TODO.md) + the per-tool TODOs' Done records; [family-unify.md](family-unify.md) + [history/family-unify.md](history/family-unify.md); the generated [family-drift.md](family-drift.md) + [history/family-drift.md](history/family-drift.md) |
| the generated family views | [OPTIONS.md](OPTIONS.md) (the knob census) beside family-drift.md — the generators + gates in [scripts/README.md](../scripts/README.md) |
| the release history | the root [CHANGELOG](../CHANGELOG.md) (Unreleased + current), [history/CHANGELOG.md](history/CHANGELOG.md) (the archive) |
| the workflow | [DOC-REDO.md](DOC-REDO.md) (the docs redo), [scripts/README.md](../scripts/README.md) (the gates + the editors) |
| the deployment | [docker/README.md](../docker/README.md) (the stacks, the env files, the secrets), [nixos/README.md](../nixos/README.md) (the one Nix reference) |
| the supply chain | [sbom/SBOM.md](sbom/SBOM.md) |
| the samples | [examples/](../examples/README.md) (the shared acl files the `file:` gates read) |

The per-tool surfaces live in the tools' own READMEs and MANUALs; the
book (`docs/book/`, built from `book/src/`) carries the reader tour,
this page beside the index.
