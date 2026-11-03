#!/usr/bin/env python3
"""Metric specs from metrics.json (stdlib only).

The file is keyed by the exported metric name itself; an entry with a
"profile" field is register-fed — the field names the device-profile
register (profiles/sun2000.json schema) the metric is read from. Entries
without one are derived by the poller (home, export/import split, ...)."""
import json
import os

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'metrics.json')


class Metrics:
    """specs: metric name -> {help, type, profile?}; by_profile: the
    profile register name -> the metric name it feeds."""

    def __init__(self, path=None):
        path = path or DEFAULT_PATH
        try:
            with open(path, encoding='utf-8') as fh:
                specs = json.load(fh)
        except FileNotFoundError:
            raise SystemExit('metrics spec %s not found (reinstall the package or pass --metrics-spec)' % path)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise SystemExit('metrics spec %s is not valid JSON: %s' % (path, e))
        for name, spec in specs.items():
            spec.setdefault('type', 'gauge')
            if 'help' not in spec:
                raise SystemExit('metrics spec %s: %r has no "help"' % (path, name))
        self.specs = specs
        self.names = dict(specs)                       # the keys ARE the metric names
        self.help = {name: spec['help'] for name, spec in specs.items()}
        self.type = {name: spec['type'] for name, spec in specs.items()}
        self.by_profile = {spec['profile']: name for name, spec in specs.items() if 'profile' in spec}
