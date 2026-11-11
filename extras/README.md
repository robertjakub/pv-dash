# extras — the operator-side packs

The home for content **nothing in the repo's build or runtime path
consumes**: the family emits, the external system consumes. Each child
dir is one integration pack, self-documented, versioned with the
surface it feeds (the audit-trail packs gate on docs/AUDIT.md's
grammar).

## The dirs

- [graylog/](graylog/) — the Graylog content pack for the audit trail:
  the syslog input, the `audit_*` parse, the GIM (Illuminate)
  normalization, the five dedicated streams and the four event
  definitions.

## The candidates for the same home (the move is mechanical)

- **alerts/** — the Prometheus/Loki alert packs (the closest sibling
  under the charter). The move touches: the two package.nix installs
  (`${../alerts}` → share/<daemon>/alerts.yml), the docker prometheus
  build context (`../alerts`), NIXOS.md's ruleFiles paths, the
  shared/README's not-here line.
- **examples/** — the shared config samples at the root (the acl
  pairs). The loader has no examples/ fallback by design; the move
  touches docs/ACL.md and the lint/edit scripts' paths.

## The fenced dirs (NOT candidates)

- **profiles/** — runtime data: the fake loads it (`--profile`), the
  tests resolve it from `__file__`.
- **shared/** — runtime data the tools load (texts, schema, tags).
- **docker/** — build machinery: the Dockerfiles, the SBOM embeds
  their paths, the compose contexts reach into the sibling dirs.
- **tests/, scripts/, docs/** — the gates, the generators, the
  references.
