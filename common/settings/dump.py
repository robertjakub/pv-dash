#!/usr/bin/env python3
"""The family's settings state dumps: the live setting overrides as one JSON
file — the write-behind that lets a daemon restart carry its overrides
instead of losing them (stdlib only). The cache's richer dump (the cached
words + their stamps beside the settings) lives in cache/lib/persist.py;
this is the settings-only shape the other tools dump. The reload state
files (`<config>.reload` — the whole-daemon reload's write-behind) ride the
same writer and reader: one shape, one seal for the family.

The file is written atomically (tmp + rename) and **explicitly 0600** (the
F8/F12 pattern — the dump is config-equivalent trust at rest: the settings
re-apply through the live validation, so the umask never gets a vote). Every
dump carries a sha256 integrity hash of its canonical content; a restore
recomputes it and refuses edited, truncated, foreign or pre-hash dumps (fail
closed — F18 in docs/AUDIT.md), and a group/world-writable dump is refused
outright: whoever can write the dump holds config trust, so the write bits
stay owner-only.

With a key (the startup-only dump-key knob — flag/env/config; the reload
re-exec re-resolves the same argv, so the key is identical on both sides)
the dump is **sealed**: the whole state rides as the `box` of a version-2
envelope, encrypted under a SHA-256-HMAC counter-mode keystream derived from
the key and authenticated by an HMAC-SHA256 over nonce+box (stdlib only —
no AES in the stdlib; the keys are HMAC-derived domain-separated off one
sha256 of the passphrase, the nonce is fresh per dump from `secrets`). The
mac is checked first: a wrong key reads as tampered content and fails
closed, never as garbage. A restore without the key refuses a sealed dump;
a restore WITH a key refuses an unsealed one (the v1 hash is unkeyed — the
moment the operator declares a key, plaintext dumps stop being trust at
rest). The boundary is the F10 one, upgraded by the seal: unsealed, the
hash catches corruption and casual tampering, not a local admin who
rechashes; sealed, the mac is keyed and the admin without the key cannot
forge — own the dump file like the config either way. An overridden secret
rides as SECRET_REMOVED — the knob renders, the value never lands in the
file; the restore skips the placeholder and names it."""

import hashlib
import hmac
import json
import os
import secrets
import struct
import time

FORMAT = 'pv-suite-state-dump'
VERSION = 1
SEALED_VERSION = 2
CIPHER = 'sha256-ctr'

# the placeholder a dump/restore and `show config` render for a secret
# knob: the key is public (the knob exists, the vocabulary describes it),
# the value never lands in a file or a report — the restore skips the
# placeholder (never applies it), the config parser refuses it (a rendered
# script pasted back must not poison the secret with a known constant).
SECRET_REMOVED = '*** SECRET REMOVED ***'


def dump_filter(overridden, raw, by_name):
    """The family-wide dump shape: the overridden settings sorted, as raw
    re-appliable values. The keys speak the CONSOLE spellings — the row's
    live path (`acl/write`, `modbus/auth`), the flat registry name only on
    a row without a live — the state files are external artifacts (the
    config files' rule); the readers fold both spellings back through
    option_by_live (the flat name rides beside the live path there). An
    overridden secret has no raw value (the raw dict carries none by
    construction) — it rides as SECRET_REMOVED, so the dump renders the
    knob without the value."""
    out = {}
    for k in sorted(overridden):
        s = by_name.get(k)
        key = (s.live or k) if s is not None else k
        if k in raw:
            out[key] = raw[k]
        else:
            if s is not None and getattr(s, 'secret', False):
                out[key] = SECRET_REMOVED
    return out


def payload_hash(state):
    """The canonical serialization's sha256 — the dump's integrity hash
    (the cache's richer dump shape rides the same hash, lib/persist.py)."""
    payload = json.dumps(state, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _seal_keys(key):
    """The passphrase -> (keystream key, mac key): one sha256 of the domain-
    tagged passphrase, then two HMAC-SHA256 derivations — the two domains
    never share a key (the standard split for one secret material)."""
    master = hashlib.sha256(b'pv-suite-state-dump\x00' + key.encode('utf-8')).digest()
    return (hmac.new(master, b'keystream', hashlib.sha256).digest(),
            hmac.new(master, b'mac', hashlib.sha256).digest())


def _keystream(key_enc, nonce, length):
    """The SHA-256-HMAC counter-mode keystream: one hmac per 32 bytes, the
    block counter big-endian after the nonce. Dumps are small — the cost
    is noise; no hand-rolled block cipher to get wrong."""
    out = bytearray()
    block = 0
    while len(out) < length:
        out.extend(hmac.new(key_enc, nonce + struct.pack('>I', block), hashlib.sha256).digest())
        block += 1
    return bytes(out[:length])


def seal(key, plaintext):
    """Encrypt one payload under key: a fresh 16-byte nonce (secrets — the
    same payload never seals to the same box twice), the CTR keystream
    XORed over it, the HMAC-SHA256 of nonce+box as the mac. Returns the
    json-ready envelope fields {cipher, nonce, mac, box} (hex strings)."""
    key_enc, key_mac = _seal_keys(key)
    nonce = secrets.token_bytes(16)
    box = bytes(p ^ k for p, k in zip(plaintext, _keystream(key_enc, nonce, len(plaintext))))
    return {'cipher': CIPHER, 'nonce': nonce.hex(),
            'mac': hmac.new(key_mac, nonce + box, hashlib.sha256).hexdigest(),
            'box': box.hex()}


def unseal(key, envelope):
    """The inverse of seal: the mac first (a wrong key is indistinguishable
    from tampered content — both fail closed, never as garbage), then the
    keystream off. Returns the plaintext bytes; raises ValueError on an
    unknown cipher or a mac mismatch."""
    if envelope.get('cipher') != CIPHER:
        raise ValueError('unsupported cipher %r (want %s)' % (envelope.get('cipher'), CIPHER))
    try:
        nonce = bytes.fromhex(envelope['nonce'])
        box = bytes.fromhex(envelope['box'])
        tag = envelope['mac']
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError('the sealed envelope is incomplete (%s)' % e)
    _key_enc, key_mac = _seal_keys(key)
    if not hmac.compare_digest(tag, hmac.new(key_mac, nonce + box, hashlib.sha256).hexdigest()):
        raise ValueError('fails its seal — the wrong dump-key, or edited content (nothing restored)')
    stream = _keystream(_key_enc, nonce, len(box))
    return bytes(p ^ k for p, k in zip(box, stream))


def _atomic_write(path, state):
    """The dump writer's shared dance: tmp + fchmod 0600 + rename (a
    pre-existing tmp keeps its mode on O_TRUNC — force it)."""
    tmp = '%s.tmp' % path
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
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


def write_dump(path, settings, key=None):
    """Dump the setting overrides to path, atomically, 0600, with the
    integrity hash — sealed under key when one is given (the version-2
    envelope: the whole state rides encrypted in `box`). Returns the dumped
    setting count."""
    state = {
        'format': FORMAT,
        'version': VERSION,
        'saved': time.time(),
        'settings': settings or {},
    }
    n = len(state['settings'])
    state['hash'] = payload_hash(state)
    if key:
        state = dict({'format': FORMAT, 'version': SEALED_VERSION},
                     **seal(key, json.dumps(state, sort_keys=True, separators=(',', ':')).encode('utf-8')))
    _atomic_write(path, state)
    return n


def open_dump(path, format_name, label, key=None):
    """The shared dump read (common/settings/dump.py and cache/lib/persist.py): the
    stat + the group/world-writable refusal, the parse, the format check,
    and the unseal when the envelope is the version-2 sealed shape. Returns
    the state dict (sealed: the inner; plain: the file's). Raises ValueError
    on a foreign/corrupt or group/world-writable file, a sealed dump without
    the key, or an unsealed dump when a key IS configured — the message
    becomes the err reply / the startup log line, nothing restores
    partially."""
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
    if not isinstance(state, dict) or state.get('format') != format_name:
        raise ValueError('%s is not a %s (format key missing)' % (path, label))
    if state.get('version') == SEALED_VERSION:
        if not key:
            raise ValueError('the dump %s is sealed — pass the key (dump-key: --dump-key, $DUMP_KEY '
                             'or the config file); nothing restored' % path)
        try:
            inner = unseal(key, state)
        except ValueError as e:
            raise ValueError('the dump %s %s' % (path, e))
        try:
            state = json.loads(inner.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as e:
            raise ValueError('the dump %s does not unseal to a state object (%s)' % (path, e))
        if not isinstance(state, dict) or state.get('format') != format_name:
            raise ValueError('%s unsealed to a foreign payload (format key missing)' % path)
    elif key:
        raise ValueError('the dump %s is not sealed but dump-key is configured — dump again '
                         'under the key (nothing restored)' % path)
    return state


def _validate_state(state, path):
    """The inner state's checks: the version, the integrity hash (recomputed
    — edited, truncated, foreign or pre-hash content refuses), the settings
    object. Returns the state with the hash popped off."""
    if state.get('version') != VERSION:
        raise ValueError('%s: unsupported dump version %r' % (path, state.get('version')))
    if not isinstance(state.get('hash'), str):
        raise ValueError('the dump %s predates the integrity hash — dump again (nothing restored)' % path)
    want = state.pop('hash')
    if not hmac.compare_digest(want, payload_hash(state)):
        raise ValueError('the dump %s fails its integrity hash (edited, truncated or foreign content) '
                         '— nothing restored' % path)
    settings = state.get('settings') or {}
    if not isinstance(settings, dict):
        raise ValueError('%s: the settings entry is not an object' % path)
    state['settings'] = settings
    return state


def read_dump_state(path, key=None):
    """Read a dump file: the full validated state ({settings, saved, ...} —
    the reload's staleness reads `saved`). Raises ValueError per open_dump
    plus the version/hash checks — the message becomes the err reply / the
    startup log line, nothing restores partially."""
    return _validate_state(open_dump(path, FORMAT, 'pv-suite state dump', key), path)


def read_dump(path, key=None):
    """Read a dump file: the settings {name: raw value}. Raises ValueError
    on a foreign/corrupt, unsigned, tampered or group/world-writable file,
    a sealed dump without the key or an unsealed dump under a configured
    key (the message becomes the err reply / the startup log line) —
    nothing restores partially."""
    return read_dump_state(path, key)['settings']
