#!/usr/bin/env python3
"""Register-map profiles: which logical value lands on which register.

The simulator computes NAMED physical values (pv-power, device-temperature,
grid-power, battery-soc, ...); a profile maps each name onto a wire address
and an encoding. The shipped sun2000 profile (profiles/profiles/sun2000.json)
reproduces the classic SUN2000/Meter/LUNA2000 layout byte for byte; a custom
profile reuses the names on different registers to emulate a different
inverter, battery or meter. Everything about an entry lives in the JSON —
no hardcoded tables:

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
i16/u16 (one word), i32/u32 (two words, hi/lo), i32swap/u32swap (two
words, lo/hi), f32/f32swap (an IEEE 754 float, two words, hi/lo or lo/hi)
and bit (one address = one binary value, served on the coil/discrete
spaces). Each entry's "fc" picks its address space: 3 (holding registers)
or 4 (input registers) for the word types, 1 (coils, the default) or 2
(discrete inputs) for bit — the fake serves each space separately."""
import json
import os
import struct

from common.settings.config import resolve_profile_file

# The suite's shared device profiles live in the profiles/profiles/ data dir
# of the profiles/ subproject at the repository root; a packaged tool carries
# the JSON files flat, as a profiles/ dir of its own. Every profile there is
# addressable by its bare name (deye -> deye.json).


def _profile_candidates(name):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the inverter/
    up = os.path.dirname(here)
    return [os.path.join(here, 'profiles', name),            # the embedded copy (the nix share tree)
            os.path.join(up, 'profiles', name),              # the suite's data dir, flat (the docker image)
            os.path.join(up, 'profiles', 'profiles', name)]  # the dev tree (the subproject's data dir)


def resolve_profile(text):
    """A profile name (sun2000, deye-sg04lp3, ... -> the shared profiles/) or
    a JSON path, passed through. The fake's own candidate walk (the
    embedded lib/profiles copy first) rides the shared resolver."""
    return resolve_profile_file(text, _profile_candidates)


def profile_label(path):
    """The short name for a profile from the profiles/ subproject, the path
    otherwise."""
    for candidate in _profile_candidates(os.path.basename(path)):
        if os.path.abspath(candidate) == os.path.abspath(path):
            return os.path.basename(path)[:-len('.json')] if path.endswith('.json') else path
    return path

# name -> (type, scale, doc); the type/scale are the defaults a profile
# entry may override. The addresses live in the profile JSON files.
# The bit types answer on FC1/FC2 (one packed bit per address), the word
# types on FC3/FC4; a 32-bit type spans two consecutive addresses.
WIDTHS = {'i16': 1, 'u16': 1, 'i32': 2, 'u32': 2,
          'i32swap': 2, 'u32swap': 2, 'f32': 2, 'f32swap': 2, 'bit': 1}


def encode_value(regs, typ, addr, value, scale):
    """Encode one physical value at addr per the entry's type and scale."""
    if typ in ('f32', 'f32swap'):
        raw = struct.pack('>f', value * scale)
        hi, lo = raw[:2], raw[2:]
        if typ == 'f32swap':
            hi, lo = lo, hi
        regs[addr] = struct.unpack('>H', hi)[0]
        regs[addr + 1] = struct.unpack('>H', lo)[0]
        return
    raw = int(round(value * scale))
    if typ in ('i16', 'u16'):
        regs[addr] = raw & 0xFFFF
    elif typ == 'bit':
        regs[addr] = 1 if raw else 0
    elif typ in ('i32', 'u32'):
        regs[addr] = (raw >> 16) & 0xFFFF
        regs[addr + 1] = raw & 0xFFFF
    elif typ in ('i32swap', 'u32swap'):     # lo word first
        regs[addr] = raw & 0xFFFF
        regs[addr + 1] = (raw >> 16) & 0xFFFF
    else:
        raise ValueError('unknown type %r' % typ)


class RegisterMap:
    """An ordered set of named entries: (name, addr, type, scale, fc)."""

    def __init__(self, entries, path='<embedded>', description=None, mappings=None, descs=None):
        self.entries = entries   # [(name, addr, typ, scale, fc)]
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

    def encode(self, regs, values, fc=3):
        """Write the named physical values for one address space (fc) into
        a plain {addr: word} dict; values missing or None are skipped (the
        register stays unset)."""
        for name, addr, typ, scale, efc in self.entries:
            if efc != fc:
                continue
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
        width = WIDTHS.get(typ)
        if width is None:
            raise SystemExit('%s (%s): needs a "type" i16/u16/i32/u32/i32swap/u32swap/f32/f32swap/bit (got %r)'
                             % (label, name, entry.get('type')))
        try:
            fc = int(entry.get('fc', 1 if typ == 'bit' else 3))
        except (TypeError, ValueError):
            raise SystemExit('%s (%s): bad "fc" %r' % (label, name, entry.get('fc')))
        if fc not in ((1, 2) if typ == 'bit' else (3, 4)):
            raise SystemExit('%s (%s): "fc" must be %s, got %d'
                             % (label, name, '1 (coil) or 2 (discrete input)' if typ == 'bit'
                                else '3 (holding) or 4 (input)', fc))
        try:
            scale = float(entry['scale'])
        except (KeyError, TypeError, ValueError):
            raise SystemExit('%s (%s): needs a numeric "scale"' % (label, name))
        if not 0 <= addr <= 65536 - width:
            raise SystemExit('%s (%s): register %d out of range' % (label, name, addr))
        if (fc, addr) in seen:
            raise SystemExit('%s (%s): register %d already used by %s on fc%d'
                             % (label, name, addr, seen[(fc, addr)], fc))
        seen[(fc, addr)] = name
        out.append((name, addr, typ, scale, fc))
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
