#!/usr/bin/env python3
"""The cache's state dumps: the cached registers (+ their stamps) and the
live setting overrides, as one JSON file — the write-behind that lets a
daemon restart serve last-known values instead of cold misses (stdlib only).

The file is written atomically (tmp + rename) and read defensively: a
truncated or foreign file restores nothing. A restore puts the words back
as they were (their ttl bounds any staleness); a later map swap prunes
whatever the profile no longer names."""

import json
import logging
import os
import time

logger = logging.getLogger('modbus-cache')

FORMAT = 'modbus-cache-dump'
VERSION = 1


def write_dump(path, cache, settings=None):
    """Dump the cache (words + stamps) and the setting overrides to path,
    atomically. Returns the dumped word count."""
    words, stamps = cache.snapshot()
    state = {
        'format': FORMAT,
        'version': VERSION,
        'saved': time.time(),
        'map_version': cache.map_version,
        'registers': [[fc, addr, word, stamps[(fc, addr)]]
                      for (fc, addr), word in sorted(words.items())],
        'settings': settings or {},
    }
    tmp = '%s.tmp' % path
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(state, fh)
        fh.write('\n')
    os.replace(tmp, path)
    return len(words)


def read_dump(path):
    """Read a dump file: (words {(fc, addr): word}, stamps {(fc, addr): ts},
    settings {name: raw value}). Raises ValueError on a foreign/corrupt
    file (the message becomes the err reply / the startup log line)."""
    try:
        with open(path, encoding='utf-8') as fh:
            state = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError('cannot read the dump %s: %s' % (path, e))
    if not isinstance(state, dict) or state.get('format') != FORMAT:
        raise ValueError('%s is not a modbus-cache dump (format key missing)' % path)
    if state.get('version') != VERSION:
        raise ValueError('%s: unsupported dump version %r' % (path, state.get('version')))
    words, stamps = {}, {}
    regs = state.get('registers')
    if not isinstance(regs, list):
        raise ValueError('%s: the registers entry is not a list' % path)
    for row in regs:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError('%s: bad register row %r' % (path, row))
        fc, addr, word, ts = row
        if fc not in (3, 4) or not 0 <= addr <= 0xFFFF or not isinstance(word, int) \
                or not isinstance(ts, (int, float)):
            raise ValueError('%s: bad register row %r' % (path, row))
        words[(fc, addr)] = word
        stamps[(fc, addr)] = float(ts)
    settings = state.get('settings') or {}
    if not isinstance(settings, dict):
        raise ValueError('%s: the settings entry is not an object' % path)
    return words, stamps, settings
