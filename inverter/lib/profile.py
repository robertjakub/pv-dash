#!/usr/bin/env python3
"""Register-map profiles: which logical value lands on which register.

The simulator computes NAMED physical values (pv-power, device-temperature,
grid-power, battery-soc, ...); a profile maps each name onto a wire address
and an encoding. The shipped profiles/sun2000.json reproduces the classic
SUN2000/Meter/LUNA2000 layout byte for byte; a custom profile reuses the
names on different registers to emulate a different inverter, battery or
meter. Everything about an entry lives in the JSON — no hardcoded tables:

    {"description": "...", "registers": [
        {"name": "pv-power", "register": 40001, "type": "i32", "scale": 1, "desc": "PV power (W)"},
        {"name": "device-temperature", "register": 33136, "type": "i16", "scale": 10, "desc": "..."}
    ]}

Names left out of a profile are simply not served (read as 0, or rejected
in strict mode) — the register does not exist on this device. Coded
registers carry their value maps in the "mappings" tree
({register name: {code: word}}) — device-status, meter-mode, ...; the fake
serves the device-status codes from it. The 65000-65003 diagnostics block
is internal to the cache/scraper (the 0xCAFE magic is how they discover
each other); the fake always mocks it and no profile lists it. Types:
i16/u16 (one word) and i32/u32 (two words, hi/lo)."""
import json
import os

# The suite's shared device profiles live in the profiles/ subproject at the
# repository root; a packaged tool carries its own copy two levels up.
# Every profile there is addressable by its bare name (deye -> deye.json).


def _profile_candidates(name):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the inverter/
    return [os.path.join(here, 'profiles', name),                        # inverter/profiles (the embedded)
            os.path.join(os.path.dirname(here), 'profiles', name)]       # the repo profiles/ (the suite)


def resolve_profile(text):
    """A profile name (sun2000, deye-sg04lp3, ... -> the shared profiles/) or
    a JSON path, passed through."""
    t = (text or '').strip()
    if os.path.exists(t):
        return t
    if '/' not in t and not t.endswith('.json'):
        for candidate in _profile_candidates(t + '.json'):
            if os.path.exists(candidate):
                return candidate
    return t


def profile_label(path):
    """The short name for a profile from the profiles/ subproject, the path
    otherwise."""
    for candidate in _profile_candidates(os.path.basename(path)):
        if os.path.abspath(candidate) == os.path.abspath(path):
            return os.path.basename(path)[:-len('.json')] if path.endswith('.json') else path
    return path

# name -> (type, scale, doc); the type/scale are the defaults a profile
# entry may override. The addresses live in the profile JSON files.
def encode_value(regs, typ, addr, value, scale):
    """Encode one physical value at addr per the entry's type and scale."""
    raw = int(round(value * scale))
    if typ in ('i16', 'u16'):
        regs[addr] = raw & 0xFFFF
    elif typ in ('i32', 'u32'):
        regs[addr] = (raw >> 16) & 0xFFFF
        regs[addr + 1] = raw & 0xFFFF
    else:
        raise ValueError('unknown type %r' % typ)


class RegisterMap:
    """An ordered set of named entries: (name, addr, type, scale)."""

    def __init__(self, entries, path='<embedded>', description=None, mappings=None, descs=None):
        self.entries = entries   # [(name, addr, typ, scale)]
        self.descs = descs or {}  # name -> description (for show registers)
        self.path = path
        self.description = description or 'unnamed profile'
        # value maps for coded registers: [{register, values: {code: word}}]
        self.mappings = mappings or []
        self.status_map = {}
        active = standby = None
        for m in self.mappings:
            if m.get('register') == 'device-status':
                for code, word in m.get('values', {}).items():
                    if word in ('on-grid', 'normal'):
                        active = int(code)
                    elif word == 'standby':
                        standby = int(code)
        # a hybrid without a confirmed standby code stays 'normal' at night
        self.status_map = {'on-grid': active if active is not None else 512,
                           'standby': standby if standby is not None else
                                      (active if active is not None else 40960)}

    def encode(self, regs, values):
        """Write the named physical values into a plain {addr: word} dict;
        values missing or None are skipped (the register stays unset)."""
        for name, addr, typ, scale in self.entries:
            v = values.get(name)
            if v is None:
                continue
            encode_value(regs, typ, addr, v, scale)


def load_profile(path):
    """Load a profile JSON -> RegisterMap; clean one-line failures."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read register profile %s: %s' % (path, e))
    entries = data.get('registers') if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise SystemExit('register profile %s must contain a "registers" list' % path)
    seen = {}
    out = []
    for i, entry in enumerate(entries):
        label = 'register profile %s, entry %d' % (path, i + 1)
        if not isinstance(entry, dict) or 'name' not in entry:
            raise SystemExit('%s needs a "name"' % label)
        name = str(entry['name'])
        try:
            addr = int(entry['register'])
        except (KeyError, TypeError, ValueError):
            raise SystemExit('%s (%s) needs an integer "register"' % (label, name))
        typ = str(entry.get('type', ''))
        width = {'i16': 1, 'u16': 1, 'i32': 2, 'u32': 2}.get(typ)
        if width is None:
            raise SystemExit('%s (%s): needs a "type" i16/u16/i32/u32 (got %r)' % (label, name, entry.get('type')))
        try:
            scale = float(entry['scale'])
        except (KeyError, TypeError, ValueError):
            raise SystemExit('%s (%s): needs a numeric "scale"' % (label, name))
        if not 0 <= addr <= 65536 - width:
            raise SystemExit('%s (%s): register %d out of range' % (label, name, addr))
        if addr in seen:
            raise SystemExit('%s (%s): register %d already used by %s' % (label, name, addr, seen[addr]))
        seen[addr] = name
        out.append((name, addr, typ, scale))
    if not out:
        raise SystemExit('register profile %s: no entries' % path)
    description = data.get('description') if isinstance(data, dict) else None
    mappings = data.get('mappings') if isinstance(data, dict) else None
    if mappings is not None and not (isinstance(mappings, list) and
                                     all(isinstance(m, dict) and 'register' in m and 'values' in m
                                         for m in mappings)):
        raise SystemExit('register profile %s: "mappings" must be a list of '
                         '{"register": name, "values": {code: word}} objects' % path)
    descs = {str(e['name']): str(e.get('desc', '')).strip() for e in entries if isinstance(e, dict)}
    return RegisterMap(out, path=path,
                       description=str(description).strip() if description else None,
                       mappings=mappings, descs=descs)
