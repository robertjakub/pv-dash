#!/usr/bin/env python3
"""Metric specs from metrics.json (stdlib only).

The spec is **sectioned** (docs/TODO.md — the metrics.json sections):

- `"profile"` — register-fed: the entry names a device-profile register
  (profiles/profiles schema) the metric is read from; the exported name is
  `<prefix>_<key>` with `--metric-prefix` (default `huawei`);
- `"compute"` — derived by the poller from the profile reads (home,
  export/import split, the charge/discharge split); `<prefix>_<key>` too;
- `"scraper"` — the exporter's own observability, the bundled cache-diag
  gauges included; the keys ARE the exported names (`scraper_*` — the fixed
  scraper prefix, never the configurable one).

The `scraper` section ships in **lib/metrics.json** (next to this module)
and is always merged in: the configured spec (`--metrics-spec`, default
metrics.json at the subproject root) carries the `profile`/`compute`
sections, its `scraper` entries — when it has any — override the built-ins
by name. The merge happens in memory at startup; neither file is modified.
The legacy flat format (one dict of full names) is still accepted: its keys
are used verbatim. Stdlib only."""
import json
import os

BUILTIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'metrics.json')
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'metrics.json')

SECTION_PREFIX = {'profile': 'prefixed', 'compute': 'prefixed', 'scraper': 'scraper'}


def _read(path):
    """Parse one spec file — the missing/corrupt/non-object errors exit 1."""
    try:
        with open(path, encoding='utf-8') as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise SystemExit('metrics spec %s not found (reinstall the package or pass --metrics-spec)' % path)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SystemExit('metrics spec %s is not valid JSON: %s' % (path, e))
    if not isinstance(raw, dict) or not raw:
        raise SystemExit('metrics spec %s must be a non-empty JSON object' % path)
    return raw


def _entries(raw, path, prefix):
    """One spec file -> {exported name: [spec, section]}, help/type checked;
    duplicates inside one file are fatal (across the files the configured
    spec's entry wins)."""
    if 'help' in next(iter(raw.values())):
        entries = {name: [spec, None] for name, spec in raw.items()}   # the legacy flat form
    else:
        entries = {}
        for section, specs in raw.items():
            if not isinstance(specs, dict):
                raise SystemExit('metrics spec %s: the %r section must be an object of metric specs'
                                 % (path, section))
            for key, spec in specs.items():
                name = '%s_%s' % (prefix, key) if SECTION_PREFIX.get(section) == 'prefixed' else key
                if name in entries:
                    raise SystemExit('metrics spec %s: %r appears twice (section %s)' % (path, name, section))
                entries[name] = [spec, section]
    for name, (spec, _section) in entries.items():
        spec.setdefault('type', 'gauge')
        if 'help' not in spec:
            raise SystemExit('metrics spec %s: %r has no "help"' % (path, name))
    return entries


class Metrics:
    """specs: exported metric name -> {help, type, profile?}; by_profile: the
    profile register name -> the metric name it feeds; section: the spec
    section a metric came from (the dashboards and the alert rules group by
    it). The specs are the in-memory merge of the configured spec and
    lib/metrics.json (the built-in scraper_* block) — the configured file's
    entries win by name."""

    def __init__(self, path=None, prefix='huawei'):
        self.prefix = prefix or 'huawei'
        path = path or DEFAULT_PATH
        entries = _entries(_read(path), path, self.prefix)
        for name, value in _entries(_read(BUILTIN_PATH), BUILTIN_PATH, self.prefix).items():
            entries.setdefault(name, value)
        self.specs = {name: value[0] for name, value in entries.items()}
        self.names = dict(self.specs)                  # the keys ARE the metric names
        self.section = {name: value[1] for name, value in entries.items()}
        self.help = {name: spec['help'] for name, spec in self.specs.items()}
        self.type = {name: spec['type'] for name, spec in self.specs.items()}
        self.by_profile = {spec['profile']: name for name, spec in self.specs.items() if 'profile' in spec}

    def section_of(self, name):
        """The spec section a metric came from (None = the legacy flat form)."""
        return self.section.get(name)
