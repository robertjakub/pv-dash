"""Configuration plumbing shared by the Modbus tools (stdlib only): the
listen-address parser, the token-file loader and the device-profile
resolution (the shared profiles/ schema from the profiles/ subproject).

The per-tool ini loaders stay in the subprojects on purpose: they agree on
the shape (configparser, missing file fine, one [section]) but not on the
failure policy (the cache logs and continues, the scraper dies)."""
import os


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


def load_token_file(path, label='control-token-file'):
    """The token from a file: the first line, whitespace-stripped (a systemd
    LoadCredential or a plain key file — anything but the rendered ini,
    which lands world-readable in the store). Fails fast with a clean
    one-liner (so is a token that silently vanishes)."""
    try:
        with open(path, encoding='utf-8') as fh:
            token = fh.readline().strip()
    except OSError as e:
        raise SystemExit('cannot read %s %s: %s' % (label, path, e))
    if not token:
        raise SystemExit('%s %s: the file is empty' % (label, path))
    return token


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
