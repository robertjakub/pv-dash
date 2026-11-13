# extras — the operator-side packs

The home for content **nothing in the repo's build or runtime path
consumes**: the family emits, the external system consumes. Each child
dir is one integration pack, self-documented, versioned with the
surface it feeds (the audit-trail packs gate on docs/SECURITY.md's
grammar).

## The dirs

- [graylog/](graylog/) — the Graylog content pack for the audit trail:
  the syslog input, the `audit_*` parse, the GIM (Illuminate)
  normalization, the five dedicated streams and the four event
  definitions.
- [alerts/](alerts/) — the Prometheus rule pack, one file per watched
  exporter (`scraper.yml`, `cache.yml`); the watched exporters'
  packages ship their half (each as `share/alerts.yml`), the docker
  prometheus image bakes both.
- [examples/](examples/) — the suite-wide sample files, one copy each
  (the standalone acl pairs); every `package.nix` installs its packaged
  copy, no tool loads from here.

## The fenced dirs (NOT candidates)

- **shared/** — runtime data the tools load (the device profiles under
  `profiles/`, the texts/schema/tags under `suite/`, the schemas).
- **docker/** — build machinery: the Dockerfiles, the SBOM embeds
  their paths, the compose contexts reach into the sibling dirs.
- **tests/, scripts/, docs/** — the gates, the generators, the
  references.
