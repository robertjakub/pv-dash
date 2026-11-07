"""Configuration plumbing shared by the Modbus tools (stdlib only): the
listen-address parser, the token-file loader and the device-profile
resolution (the shared profiles/ schema from the profiles/ subproject).

The per-tool ini loaders stay in the subprojects on purpose: they agree on
the shape (configparser, missing file fine, one [section]) but not on the
failure policy (the cache logs and continues, the scraper dies)."""
import ipaddress
import os

from common.modbus import AUTH_MIN_KEY


def check_token_file_mode(path, label='token-file'):
    """The token-file discipline (F12 in docs/AUDIT.md): a token file must
    be owner-only (0600) — a group- or world-accessible token file is
    refused before the read (a leaked file mode is a leaked token).
    os.stat follows symlinks, so a LoadCredential symlink is judged by its
    target."""
    try:
        st = os.stat(path)
    except OSError as e:
        raise SystemExit('cannot read %s %s: %s' % (label, path, e))
    mode = st.st_mode & 0o777
    if mode & 0o077:
        raise SystemExit('%s %s: mode %03o is group/world accessible — '
                         'a token file must be 0600, chmod 0600 %s'
                         % (label, path, mode, path))


def parse_listen(text):
    """HOST:PORT -> (host, port); a malformed value exits with a clean
    one-liner (the repo's config style — never a traceback)."""
    host, sep, port = text.rpartition(':')
    if not sep:
        raise SystemExit('--listen must be HOST:PORT, got %r' % text)
    try:
        port = int(port)
    except ValueError:
        raise SystemExit('--listen port must be a number, got %r' % port)
    if not 0 <= port <= 65535:
        raise SystemExit('--listen port out of range, got %d' % port)
    return host.strip('[]'), port


def parse_upstream(text, label='--upstream'):
    """The Modbus upstream endpoint HOST:PORT -> (host, port) — the shared
    knob of the cache and the scraper. ``:PORT`` = 127.0.0.1:PORT (the
    loopback shorthand); ``[v6]:PORT`` works like --listen. A malformed
    value exits with a clean one-liner."""
    host, sep, port = str(text).rpartition(':')
    if not sep:
        raise SystemExit('%s must be HOST:PORT, got %r — :PORT = 127.0.0.1:PORT' % (label, text))
    try:
        port = int(port)
    except ValueError:
        raise SystemExit('%s port must be a number, got %r' % (label, port))
    if not 1 <= port <= 65535:
        raise SystemExit('%s port out of range, got %d' % (label, port))
    host = host.strip('[]').strip()
    if not host:
        host = '127.0.0.1'
    return host, port


def is_loopback_host(host):
    """True when the listen host is loopback: the loopback addresses
    (127.0.0.0/8, ::1), 'localhost', or an empty bracket form of ::1. An
    empty string = all interfaces = NOT loopback; an unresolvable hostname
    is treated as not loopback (a name that resolves loopback is exotic —
    bind the address instead)."""
    t = (host or '').strip().strip('[]').lower()
    if not t or t == '0.0.0.0' or t == '::' or t == '*':
        return False
    if t == 'localhost':
        return True
    try:
        return ipaddress.ip_address(t).is_loopback
    except ValueError:
        return False


def parse_acl(text, label):
    """The connect ACL, one implementation for the family (the cache's
    Modbus/write surfaces, the fake's Modbus listener): 'any'/'*'/empty/None
    -> None (allow all); 'none' -> () (allow nobody); 'IP, CIDR, ...' ->
    tuple of networks. An empty tuple refuses every peer — the ACL's
    restrict-all mode."""
    if text is None:
        return None
    t = str(text).strip()
    if t in ('', 'any', '*'):
        return None
    if t.lower() == 'none':
        return ()
    nets = []
    for part in t.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError as e:
            raise SystemExit('%s: bad ACL entry %r (%s)' % (label, part, e))
    return tuple(nets)


def acl_text(acl):
    """The ACL normalized for `unset` to re-parse: 'any' | 'none' | the network list."""
    if acl is None:
        return 'any'
    if not acl:
        return 'none'
    return ','.join(str(n) for n in acl)


def acl_summary(acl):
    """The ACL for humans (the start log, show status, inspect): 'any' (no
    restriction), 'none' (everybody refused) or the network count."""
    if acl is None:
        return 'any'
    if not acl:
        return 'none'
    return '%d network(s)' % len(acl)


def load_token_file(path, label='token-file'):
    """The token from a file: the first line, whitespace-stripped (a systemd
    LoadCredential or a plain key file — anything but the rendered ini,
    which lands world-readable in the store). The file must be owner-only
    (0600) — group/world-accessible token files are refused (F12 in
    docs/AUDIT.md). Fails fast with a clean one-liner (so is a token that
    silently vanishes)."""
    check_token_file_mode(path, label)
    try:
        with open(path, encoding='utf-8') as fh:
            token = fh.readline().strip()
    except OSError as e:
        raise SystemExit('cannot read %s %s: %s' % (label, path, e))
    if not token:
        raise SystemExit('%s %s: the file is empty' % (label, path))
    return token


def parse_auth_type(text, label='auth', schemes=('suite',)):
    """The Modbus auth scheme: '' / none / off -> None (no auth at all —
    the default); one of `schemes` — the suite crypt handshake everywhere,
    and the cache's upstream leg also speaks the Waveshare gateway
    connection password; anything else fails fast with a clean one-liner."""
    t = (text or '').strip().lower()
    if t in ('', 'none', 'off'):
        return None
    if t in schemes:
        return t
    raise SystemExit('invalid %s = %r: use %s, or none/empty for no auth'
                     % (label, text, ' / '.join("'%s'" % s for s in schemes)))


def auth_key_floor_error(kind, key):
    """The scheme's floor on a handshake key, as a short error phrase or
    None when the key passes: 'suite' needs at least AUTH_MIN_KEY
    characters; 'waveshare' needs non-empty ASCII (the gateway password
    travels as raw bytes); None (a key set while the scheme is still
    undecided) is dormant material — anything non-empty goes, the
    scheme's floor bites when the scheme names it."""
    if not key:
        return 'cannot be empty'
    if kind == 'waveshare':
        try:
            key.encode('ascii')
        except UnicodeEncodeError:
            return 'must be ASCII (the Waveshare password travels as raw bytes)'
        return None
    if kind is None:
        return None
    if len(key) < AUTH_MIN_KEY:
        return 'must be at least %d characters, got %d' % (AUTH_MIN_KEY, len(key))
    return None


def check_auth_key(key, label='auth-key', kind='suite'):
    """The handshake key's floor (auth_key_floor_error) raised as a
    SystemExit. The kind is the resolved scheme: 'suite' — the default
    every suite-only leg means, 'waveshare', or None (dormant). An
    empty/None key is the no-auth state, fine."""
    if key is None:
        return None
    err = auth_key_floor_error(kind, key)
    if err:
        raise SystemExit('invalid %s: %s' % (label, err))
    return key


def parse_secret(raw, label='secret'):
    """One secret knob, two forms: the inline string, or ``file:<path>`` —
    the first line of an owner-only (0600) file, loaded by the shared
    load_token_file discipline (F12). The
    reference form is what a config file or an env var wants to carry: the
    material stays in the file, the config renders the reference (and the
    knob is secret-marked, so even the reference never renders back). A
    file: reference that cannot be read fails fast — a secret that
    silently vanishes is a misconfiguration, not a fallback to plaintext.
    The inline form passes through untouched (a key may contain any
    non-whitespace text; 'file:' as a literal KEY prefix is the one
    reserved spelling)."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if raw.startswith('file:'):
        return load_token_file(raw[len('file:'):].strip(), label)
    return raw


def _profile_candidates(name):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [os.path.join(here, 'profiles', name),                        # the bundled copy (the packaged share tree)
            os.path.join(here, 'profiles', 'profiles', name),            # the profiles/ subproject (the dev tree)
            os.path.join(os.path.dirname(here), 'profiles', name)]       # one up (an unpackaged suite tree)


def default_profile_path(name='sun2000.json'):
    """The bundled device profile (packaged next to the tool's share tree)
    or the shared profiles/ subproject at the repository root (dev tree)."""
    for candidate in _profile_candidates(name):
        if os.path.exists(candidate):
            return candidate
    return name


def resolve_profile_file(text):
    """A profile name (sun2000, deye -> the shared profiles/ subproject) or
    a JSON path, passed through."""
    t = (text or '').strip()
    if os.path.exists(t):
        return t
    if '/' not in t and not t.endswith('.json'):
        for candidate in _profile_candidates(t + '.json'):
            if os.path.exists(candidate):
                return candidate
    return t
