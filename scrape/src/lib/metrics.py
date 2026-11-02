#!/usr/bin/env python3
"""Metric names, help texts and types from metrics.json (stdlib only)."""
import json
import os

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'metrics.json')


class Metrics:
    """Metric specs: `names` maps the logical key to the exported metric name."""

    def __init__(self, path=None):
        path = path or DEFAULT_PATH
        try:
            with open(path, encoding='utf-8') as fh:
                specs = json.load(fh)
        except FileNotFoundError:
            raise SystemExit('metrics spec %s not found (reinstall the package or pass --metrics-spec)' % path)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise SystemExit('metrics spec %s is not valid JSON: %s' % (path, e))
        for spec in specs.values():
            spec.setdefault('type', 'gauge')
        self.specs = specs
        self.names = {key: spec['name'] for key, spec in specs.items()}
        self.help = {spec['name']: spec['help'] for spec in specs.values()}
        self.type = {spec['name']: spec['type'] for spec in specs.values()}
