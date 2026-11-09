#!/usr/bin/env python3
"""Metric specs from metrics.json (stdlib only).

The spec is **sectioned** (docs/TODO.md — the metrics.json sections):

- `"metrics"` — the metric tree: one entry per metric, the entry's own
  field says what feeds it — `"profile"` names a device-profile register
  (profiles/profiles schema) the metric is read from, `"expr"` derives it
  per poll (over the declared inputs — pv, grid, batt, soc and
  every profile-bound metric key; an optional `"when"` gates the presence);
  compiled once at startup (lib/expr.py); the exported name is
  `<prefix>_<key>` with `--metric-prefix` (default `huawei`). The
  `section` a metric reports (`profile`/`compute`) derives from the field;
- `"scraper"` — the exporter's own observability, the bundled cache-diag
  gauges included; the keys ARE the exported names (`scraper_*` — the fixed
  scraper prefix, never the configurable one).

The `scraper` section ships in **lib/metrics.json** (next to this module)
and is always merged in: the configured spec (`--metrics-spec`, default
metrics.json — the packaged root; a source checkout passes the flag) carries
the `metrics` section, its `scraper` entries — when it has any — override
the built-ins by name. lib/metrics.json also carries the `inputs`
declaration (the reserved four's wording — every reserved input must be
declared there); the configured spec's own "inputs" entries reword it.
The merge happens in memory at startup; neither file
is modified. The five classic compute metrics (the pre-expr hardcoded math)
are the eval table's defaults under every spec that doesn't define them.
The legacy flat format (one dict of full names) is still accepted: its keys
are used verbatim. Stdlib only."""
import json
import os

from .expr import ExprError, compile_expr

_LIB = os.path.dirname(os.path.abspath(__file__))
BUILTIN_PATH = os.path.join(_LIB, 'metrics.json')
ROOT = os.path.dirname(_LIB)
DEFAULT_PATHS = [os.path.join(ROOT, 'metrics.json')]   # the packaged layout (flattened)
# the loader never reaches into examples/ on its own — a dev checkout
# symlinks the root file (gitignored) or passes --metrics-spec explicitly
# the reserved compute inputs' wiring: the poller's canonical reads — the
# name an expr/when may reference -> the canonical profile register the
# poller reads. The declarations'
# WORDING ships in lib/metrics.json's "inputs" section (merged into every
# spec); a spec's own "inputs" entries may reword it, never the wiring
RESERVED_INPUT_REGISTERS = {
    'pv':      'pv-power',
    'grid':    'grid-power',
    'batt':    'battery-power',
    'soc':     'battery-soc',
}
# the classic five: the eval table's defaults under every spec that doesn't
# define them (the pre-expr hardcoded math)
_COMPUTE_DEFAULTS = {
    'grid_export_watts':      ('max(grid, 0.0)',    None),
    'grid_import_watts':      ('max(-grid, 0.0)',   None),
    'home_consumption_watts': ('pv - batt - grid',  None),
    'battery_charge_watts':   ('max(batt, 0.0)',    None),
    'battery_discharge_watts': ('max(-batt, 0.0)',  None),
}


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
    spec's entry wins). The sections: "metrics" (the merged tree — the
    entry's "profile" or "expr" field says what feeds it, the section
    derives from the field) and "scraper" (the keys verbatim)."""
    if 'help' in next(iter(raw.values())):
        entries = {name: [spec, None] for name, spec in raw.items()}   # the legacy flat form
    else:
        entries = {}
        for section, specs in raw.items():
            if section in ('profile', 'compute'):
                raise SystemExit('metrics spec %s: the %r section is gone — the profile- and compute-fed '
                                 'entries live in one "metrics" tree (the entry\'s "profile" or "expr" '
                                 'field says which it is)' % (path, section))
            if not isinstance(specs, dict):
                raise SystemExit('metrics spec %s: the %r section must be an object of metric specs'
                                 % (path, section))
            for key, spec in specs.items():
                if section == 'scraper':
                    name, entry_section = key, 'scraper'
                elif section == 'metrics':
                    if 'profile' in spec and 'expr' in spec:
                        raise SystemExit('metrics spec %s: %r carries "profile" and "expr" — one or the other'
                                         % (path, key))
                    name, entry_section = '%s_%s' % (prefix, key), ('profile' if 'profile' in spec else 'compute')
                else:
                    raise SystemExit('metrics spec %s: unknown section %r (the sections are: "inputs", '
                                     '"metrics", "scraper")' % (path, section))
                if name in entries:
                    raise SystemExit('metrics spec %s: %r appears twice (section %s)' % (path, name, section))
                entries[name] = [spec, entry_section]
    for name, (spec, _section) in entries.items():
        spec.setdefault('type', 'gauge')
        if 'help' not in spec:
            raise SystemExit('metrics spec %s: %r has no "help"' % (path, name))
    return entries


class Metrics:
    """specs: exported metric name -> {help, type, expr?, when?, profile?};
    by_profile: the profile register name -> the metric name it feeds;
    profile_inputs: the profile register name -> the expression input name
    (the spec key); compute: the expression-fed metrics in spec order —
    {name: (fn, when_fn)} compiled by lib/expr.py; section: the spec
    section a metric came from (the dashboards and the alert rules group by
    it). The specs are the in-memory merge of the configured spec and
    lib/metrics.json (the built-in scraper_* block) — the configured file's
    entries win by name."""

    def __init__(self, path=None, prefix='huawei'):
        self.prefix = prefix or 'huawei'
        path = path or _default_path()
        raw = _read(path)
        declared = raw.pop('inputs', None)   # the configured spec's declared vocabulary, not a metric section
        builtin = _read(BUILTIN_PATH)
        builtin_declared = builtin.pop('inputs', None)   # the built-in spec's declarations (the shipped wording)
        entries = _entries(raw, path, self.prefix)
        for name, value in _entries(builtin, BUILTIN_PATH, self.prefix).items():
            entries.setdefault(name, value)
        self.specs = {name: value[0] for name, value in entries.items()}
        self.names = dict(self.specs)                  # the keys ARE the metric names
        self.section = {name: value[1] for name, value in entries.items()}
        self.help = {name: spec['help'] for name, spec in self.specs.items()}
        self.type = {name: spec['type'] for name, spec in self.specs.items()}
        self.by_profile = {}
        for name, spec in self.specs.items():
            if 'profile' not in spec:
                continue
            register = spec['profile']
            if register in self.by_profile:
                raise SystemExit('metrics spec: the register %r is bound twice (%s and %s) — the power inputs\' '
                                 'canonical metrics are built-in (lib/metrics.json) and not re-bindable'
                                 % (register, self.by_profile[register], name))
            self.by_profile[register] = name
        self.profile_inputs = {}
        for name, spec in self.specs.items():
            if 'profile' not in spec:
                continue
            key = name[len(self.prefix) + 1:] if name.startswith(self.prefix + '_') else name
            if key in RESERVED_INPUT_REGISTERS:
                raise SystemExit('metrics spec %s: profile key %r collides with the reserved compute input %r'
                                 % (path, key, key))
            self.profile_inputs[spec['profile']] = key
        # the declared expression vocabulary: lib/metrics.json's "inputs"
        # section is the base (every reserved input must be declared there —
        # the wiring's invariant), the configured spec's entries reword it;
        # the profile keys may be declared too. Each entry: {register: the
        # canonical profile register the poller reads, help: the rendered
        # help} — the report brackets an input with the metric whose value
        # it carries
        register_of = dict(RESERVED_INPUT_REGISTERS)
        register_of.update({key: register for register, key in self.profile_inputs.items()})
        self.inputs = {}
        for source, section_path in ((builtin_declared, BUILTIN_PATH), (declared, path)):
            if source is None:
                continue
            if not isinstance(source, dict) or not source:
                raise SystemExit('metrics spec %s: the "inputs" section must be a non-empty object of {name: {help}}' % section_path)
            for iname, decl in source.items():
                if not isinstance(decl, dict) or not isinstance(decl.get('help'), str) or not decl['help'].strip():
                    raise SystemExit('metrics spec %s: the input %r declares no "help" string' % (section_path, iname))
                if iname not in register_of:
                    raise SystemExit('metrics spec %s: the "inputs" section declares %r, which is not an input '
                                     '(the inputs are: %s — the reserved four and the spec\'s profile keys)'
                                     % (section_path, iname, ', '.join(sorted(register_of))))
                self.inputs[iname] = {'register': register_of[iname], 'help': decl['help']}
        undeclared = sorted(name for name in RESERVED_INPUT_REGISTERS if name not in self.inputs)
        if undeclared:
            raise SystemExit('metrics spec %s: the reserved input(s) %s are not declared in the "inputs" section'
                             % (BUILTIN_PATH, ', '.join(undeclared)))
        self.compute, compiled = {}, {}
        for name, spec in self.specs.items():
            if self.section.get(name) != 'compute':
                continue
            if 'profile' in spec:
                raise SystemExit('metrics spec %s: %r (compute) carries "profile" — compute entries are expression-fed, not register-fed'
                                 % (path, name))
            compiled[name] = _compile(name, spec, path)
        # the classic five under every spec that doesn't define them (the
        # pre-expr hardcoded math): poller-side defaults — they ride the
        # eval table only, not the spec listing (the exposition falls back
        # to name-as-help, exactly the old rendering)
        for key, (expr, when) in _COMPUTE_DEFAULTS.items():
            name = '%s_%s' % (self.prefix, key)
            if name not in compiled:
                compiled[name] = _compile(name, {'expr': expr, 'when': when}, 'the built-in compute defaults')
        available = sorted(register_of)
        for name, (_fn, _when, refs) in compiled.items():
            unknown = sorted(refs - set(available))
            if unknown:
                raise SystemExit('metrics spec %s: %r references unknown input(s) %s '
                                 '(the compute inputs are: %s — and one compute metric cannot feed another)'
                                 % (path, name, ', '.join(unknown), ', '.join(available)))
        self.compute = {name: (fn, when) for name, (fn, when, _refs) in compiled.items()}

    def section_of(self, name):
        """The spec section a metric came from (None = the legacy flat form)."""
        return self.section.get(name)


def _default_path():
    """The packaged root only — the error names it when it's absent (a
    checkout passes --metrics-spec or arranges the root file itself; the
    loader never reaches into examples/ on its own)."""
    for path in DEFAULT_PATHS:
        if os.path.exists(path):
            return path
    raise SystemExit('no default metrics spec found (tried %s) — reinstall the package or pass --metrics-spec'
                     % ' and '.join(DEFAULT_PATHS))


def _compile(name, spec, path):
    """One compute entry -> (fn, when_fn, referenced inputs); the "expr" is
    required, the "when" gate optional — both compile-checked at startup."""
    what = 'metrics spec %s: %r' % (path, name)
    text = spec.get('expr')
    if not isinstance(text, str) or not text.strip():
        raise SystemExit('metrics spec %s: %r (compute) has no "expr" — compute entries are expression-fed' % (path, name))
    try:
        fn, names = compile_expr(text, what)
        when, when_names = None, set()
        if spec.get('when') is not None:
            when, when_names = compile_expr(spec['when'], what + ' (when)')
    except ExprError as e:
        raise SystemExit(str(e))
    return fn, when, names | when_names
