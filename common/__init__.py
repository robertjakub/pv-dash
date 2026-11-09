"""pv-suite common: the code shared by the Modbus subprojects (cache,
scrape, inverter, dashboard) — stdlib only.

One package, imported as `common` from everywhere:
- the checkout: the bin scripts put the repo root on sys.path (the same
  insert that exposes each subproject's lib/), and common/ sits there too
- the nix packages: common/ lands in share/<tool>/common/ (the flat
  modules, every functional subdir), next to lib/
- the docker images: the common/ tree is copied to /pv-suite/common/

Subpackages:
- render/   — the human-facing rendering: the static texts (the T()
              loader — shared/texts.json at the tree root), the
              man-page builder, the time formats
- runtime/  — the process scaffolding + the trail: the daemon-bin ladder,
              the audit trail writer, the UTC log stamps, the version
- settings/ — the settings plane: the option registry (one knob, one
              source), the config plumbing (the resolver, the token
              loading, the profiles), the state dumps + the seal
- wire/     — the signed control wire, both ends: the ControlServer base
              (the wire tier, the RBAC roles, the live rebind, the
              family's command() walk) + the ctl/cli clients
- serve/    — the serving-surface gates and faces: the connection caps,
              the gated Prometheus text-endpoint skeleton
- modbus/   — the Modbus TCP implementation: the wire core, the client
              ladders, the shared accept ladder, the write shapes

Deliberately NOT here (still per-tool): the command grammars
(command/_apply/_get — each tool's verbs and _apply branches), the
status/inspect reports (tool-specific wording), the metrics endpoints
(snapshot()/render() over the common skeleton) and the config-script
loaders (each tool resolves its own registry onto the common grammar).
"""
