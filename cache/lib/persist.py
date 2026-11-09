#!/usr/bin/env python3
"""The cache's state dumps: the live setting overrides and (on request) the
cached registers (+ their stamps), as one JSON file — the write-behind that
lets a daemon restart serve last-known values instead of cold misses
(stdlib only). A dump is settings-only or full (with-cache); a restore
loads whatever the file carries (the words restore only if it has them).
The reload state file (`<config>.reload`) rides the settings-only shape —
the shared common/settings/dump.py writer and reader (write_state_dump/
read_state_dump).

The file is written atomically (tmp + rename) and **explicitly 0600** (the
F8/F12 pattern — the dump is config-equivalent trust at rest: the words are
production data and the settings re-apply through the live validation, so
the umask never gets a vote). Every dump carries a sha256 integrity hash of
its canonical content; a restore recomputes it and refuses edited,
truncated, foreign or pre-hash dumps (fail closed — F18 in docs/AUDIT.md),
and a group/world-writable dump is refused outright: whoever can write the
dump holds config trust, so the write bits stay owner-only.

With a key (the startup-only dump/key knob — flag/env/config; the reload
re-exec re-resolves the same argv, so the key is identical on both sides)
the dump is **sealed** via the shared seal (common/settings/dump.py): the whole
state — the words included — rides as the `box` of a version-2 envelope,
encrypted under an HMAC-SHA256 counter-mode keystream and authenticated by
an HMAC-SHA256 over nonce+box. The mac is checked first: a wrong key reads
as tampered content and fails closed, never as garbage. A restore without
the key refuses a sealed dump; a restore WITH a key refuses an unsealed
one (the v1 hash is unkeyed — the moment the operator declares a key,
plaintext dumps stop being trust at rest). The F10 boundary, upgraded by
the seal: unsealed, the hash catches corruption and casual tampering, not
a local admin who rechashes; sealed, the mac is keyed and the admin
without the key cannot forge — own the dump file like the config either
way.

A restore puts the words back as they were (their ttl bounds any
staleness); a later map swap prunes whatever the profile no longer names."""

import hmac
import json
import logging
import os
import time

from common.settings.dump import SEALED_VERSION, open_dump, payload_hash, seal
from common.settings.dump import write_dump as _state_write_dump
from common.settings.dump import read_dump_state as _state_read_dump_state

logger = logging.getLogger('modbus-cache')

FORMAT = 'modbus-cache-dump'
VERSION = 1


def write_state_dump(path, settings, key=None):
    """The reload state file: the settings-only dump shape — the shared
    common/settings/dump.py writer (the cache's richer shape with the words is
    write_dump's). Sealed when key is given."""
    return _state_write_dump(path, settings, key=key)


def read_state_dump(path, key=None):
    """The reload state file's read: the shared common/settings/dump.py reader —
    the full validated state ({settings, saved, ...}; the staleness reads
    `saved`). Sealed dumps refuse to open without the key."""
    return _state_read_dump_state(path, key=key)


def write_dump(path, cache, settings=None, with_cache=True, key=None):
    """Dump the setting overrides and — when with_cache — the cached words
    (+ stamps) to path, atomically, 0600, with the integrity hash — sealed
    under key when one is given (the version-2 envelope: the whole state,
    words included, rides encrypted in `box`).
    Returns the dumped word count (0 for a settings-only dump)."""
    state = {
        'format': FORMAT,
        'version': VERSION,
        'saved': time.time(),
        'map_version': cache.map_version,
        'registers': [],
        'settings': settings or {},
    }
    if with_cache:
        words, stamps = cache.snapshot()
        state['registers'] = [[fc, addr, word, stamps[(fc, addr)]]
                              for (fc, addr), word in sorted(words.items())]
    else:
        words = {}
    n = len(words)
    state['hash'] = payload_hash(state)
    if key:
        state = dict({'format': FORMAT, 'version': SEALED_VERSION},
                     **seal(key, json.dumps(state, sort_keys=True, separators=(',', ':')).encode('utf-8')))
    tmp = '%s.tmp' % path
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)   # a pre-existing tmp keeps its mode on O_TRUNC — force it
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(state, fh)
            fh.write('\n')
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    return n


def read_dump(path, key=None):
    """Read a dump file: (words {(fc, addr): word}, stamps {(fc, addr): ts},
    settings {name: raw value}). Raises ValueError on a foreign/corrupt,
    unsigned, tampered or group/world-writable file, a sealed dump without
    the key or an unsealed dump under a configured key (the message becomes
    the err reply / the startup log line) — nothing restores partially."""
    state = open_dump(path, FORMAT, 'modbus-cache dump', key)
    if state.get('version') != VERSION:
        raise ValueError('%s: unsupported dump version %r' % (path, state.get('version')))
    if not isinstance(state.get('hash'), str):
        raise ValueError('the dump %s predates the integrity hash — dump again (nothing restored)' % path)
    want = state.pop('hash')
    if not hmac.compare_digest(want, payload_hash(state)):
        raise ValueError('the dump %s fails its integrity hash (edited, truncated or foreign content) '
                         '— nothing restored' % path)
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
