#!/usr/bin/env python3
"""The family's settings state dumps: the live setting overrides as one JSON
file — the write-behind that lets a daemon restart carry its overrides
instead of losing them (stdlib only). The cache's richer dump (the cached
words + their stamps beside the settings) lives in cache/lib/persist.py;
this is the settings-only shape the other tools dump.

The file is written atomically (tmp + rename) and **explicitly 0600** (the
F8/F12 pattern — the dump is config-equivalent trust at rest: the settings
re-apply through the live validation, so the umask never gets a vote). Every
dump carries a sha256 integrity hash of its canonical content; a restore
recomputes it and refuses edited, truncated, foreign or pre-hash dumps (fail
closed — F18 in docs/AUDIT.md), and a group/world-writable dump is refused
outright: whoever can write the dump holds config trust, so the write bits
stay owner-only. The boundary is the F10 one: the hash catches corruption
and casual tampering, not a local admin who rechashes — own the dump file
like the config."""

import hashlib
import hmac
import json
import os
import time

FORMAT = 'pv-suite-state-dump'
VERSION = 1


def _payload_hash(state):
    """The canonical serialization's sha256 — the dump's integrity hash."""
    payload = json.dumps(state, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def write_dump(path, settings):
    """Dump the setting overrides to path, atomically, 0600, with the
    integrity hash. Returns the dumped setting count."""
    state = {
        'format': FORMAT,
        'version': VERSION,
        'saved': time.time(),
        'settings': settings or {},
    }
    state['hash'] = _payload_hash(state)
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
    return len(state['settings'])


def read_dump(path):
    """Read a dump file: the settings {name: raw value}. Raises ValueError
    on a foreign/corrupt, unsigned, tampered or group/world-writable file
    (the message becomes the err reply / the startup log line) — nothing
    restores partially."""
    try:
        st = os.stat(path)
    except OSError as e:
        raise ValueError('cannot read the dump %s: %s' % (path, e))
    if st.st_mode & 0o022:
        raise ValueError('the dump %s is group/world-writable (mode %03o) — restore refused: '
                         'the dump holds config trust, chmod 0600 %s' % (path, st.st_mode & 0o777, path))
    try:
        with open(path, encoding='utf-8') as fh:
            state = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError('cannot read the dump %s: %s' % (path, e))
    if not isinstance(state, dict) or state.get('format') != FORMAT:
        raise ValueError('%s is not a pv-suite state dump (format key missing)' % path)
    if state.get('version') != VERSION:
        raise ValueError('%s: unsupported dump version %r' % (path, state.get('version')))
    if not isinstance(state.get('hash'), str):
        raise ValueError('the dump %s predates the integrity hash — dump again (nothing restored)' % path)
    want = state.pop('hash')
    if not hmac.compare_digest(want, _payload_hash(state)):
        raise ValueError('the dump %s fails its integrity hash (edited, truncated or foreign content) '
                         '— nothing restored' % path)
    settings = state.get('settings') or {}
    if not isinstance(settings, dict):
        raise ValueError('%s: the settings entry is not an object' % path)
    return settings
