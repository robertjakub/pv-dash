"""Configuration plumbing shared by the family (stdlib only): the
listen-address parser, the token-file loader, the device-profile
resolution (the shared profiles/ schema from the profiles/ subproject),
the set-grammar config-script loader, the resolver (the family's
precedence: CLI flags > env > config script > defaults) and the
control-token rules."""
import ipaddress
import json
import os

from common.modbus import AUTH_MIN_KEY


def resolve_target(explicit, default_socket):
    """The control server target for the daemon and its clients: the
    --control-port flag wins, then the CTL environment, then the tool's
    default unix socket."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get('CTL')
    if env and env.strip():
        return env.strip()
    return default_socket


def control_socket_path(listen_port, socket_template):
    """The tool's default control socket path: its template spelled with
    its serving port (/tmp is cleared on reboot, nothing lands in a
    working directory)."""
    return socket_template % int(listen_port)


def parse_control_target(text, listen_port, socket_template):
    """The control target from one flag/env/config value or live wire
    value: '' → the default unix socket for the serving port; '0' → None
    (off); digits → TCP port on 127.0.0.1; anything else → unix socket
    path. SystemExit on an out-of-range port."""
    t = (text or '').strip()
    if t == '0':
        return None
    if t.isdigit():
        p = int(t)
        if not 1 <= p <= 65535:
            raise SystemExit('invalid control-port %d: use 1..65535, a unix socket path, or 0 to disable' % p)
        return p
    if t:
        return t
    return control_socket_path(listen_port, socket_template)


def resolve_control_target(explicit, listen_port, socket_template):
    """--control-port flag > CTL environment > the tool's default socket
    (its template spelled with its serving port). One signature for the
    family — the daemons pass their serving port + template, the ctl/cli
    ladders take the computed default socket (ctl_socket)."""
    return resolve_target(explicit, control_socket_path(listen_port, socket_template))


def load_config_script(path, options):
    """The set-grammar config script: every line a `set <name> <value>` (or
    the bare `<name> <value>` shorthand), `#` comments stay comments — a
    config file pipes through a ctl client unchanged. Returns {key: raw-
    string value} with the dash names underscore-normalized (the resolver's
    keys). A missing file is no config at all; an unreadable one or a
    legacy ini file fails fast with the pointer to the new grammar. The
    tool's OPTIONS registry rows gate the grammar (the CLI spelling + the
    unknown-setting fail fast)."""
    from common.options import parse_config_script   # lazy: options sits above config in the layering
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except OSError as e:
        raise SystemExit('cannot read config file %s: %s' % (path, e))
    try:
        rows = parse_config_script(text, path, options)
    except ValueError as e:
        raise SystemExit(str(e))
    out = {}
    for name, value in rows:
        key = name.replace('-', '_')
        if key in out:
            raise SystemExit('%s: %s is set twice (the file applies top to bottom — say it once)'
                             % (path, name))
        out[key] = value
    return out


def str_to_bool(value):
    """The conv for a boolean knob's resolve(): the words true/yes/on/1."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('true', 'yes', 'on', '1'):
        return True
    if text in ('false', 'no', 'off', '0'):
        return False
    raise ValueError('not a boolean')


class Resolver:
    """The family's precedence for one effective-config dict: CLI flags >
    env > config script > defaults. An empty flag or env value counts as
    unset (the value falls through to the next layer); a bad value logs and
    falls back to the default (keep-last-good)."""

    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.logger = logger

    def resolve(self, cli_value, env_name, cfg_key, default, conv):
        raw = cli_value
        if raw is None or raw == '':
            raw = os.environ.get(env_name) if env_name else None
        if raw is None or raw == '':
            raw = self.cfg.get(cfg_key)
        if raw is None or raw == '':
            return default
        try:
            return conv(raw)
        except (TypeError, ValueError) as e:
            self.logger.error('invalid %s = %r: %s (using %r)', cfg_key, raw, e, default)
            return default

    def resolve_bool(self, cli_value, env_name, cfg_key, default):
        return self.resolve(cli_value, env_name, cfg_key, default, str_to_bool)


def check_token_chars(value, name):
    """The token charset rule: no whitespace, no control characters (a
    secret rides one wire frame and one header)."""
    if value and any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
        raise SystemExit('invalid %s: must not contain whitespace or control characters' % name)


def check_control_tokens(token, ops_token, sep=': '):
    """The control-token pairing rules: the read-only ops token supplements
    the admin token (never stands alone), and the two must differ (the same
    secret would hand every holder the role the server picks first)."""
    if ops_token:
        if not token:
            raise SystemExit('the read-only ops token supplements the admin token%s'
                             'set --control-token too' % sep)
        if ops_token == token:
            raise SystemExit('the ops token must differ from the admin token (the same secret would '
                             'hand every holder the role the server picks first)')


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
    """The ACL for humans (the start log, inspect): 'any' (no
    restriction), 'none' (everybody refused) or the network count."""
    if acl is None:
        return 'any'
    if not acl:
        return 'none'
    return '%d network(s)' % len(acl)


def acl_admits(acl, ip):
    """The IP ACL on one peer: None = the ACL is off (everybody allowed);
    () = nobody allowed (the 'none' mode); the networks = the whitelist
    (the ip must land in one network); an IPGate (the file's chain) = the
    last matching rule decides, no match denies. Bad addresses refuse."""
    if isinstance(acl, IPGate):
        return acl.allows(ip)
    if acl is None:
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a.version == n.version and a in n for n in acl)


def acl_file_warn(path):
    """The acl file's permission posture: group/world-READABLE is warned
    about, not refused (the file is config trust like the profile — but
    whoever can read it can also loosen the gate before the daemon reads
    it) — returns the one-line warning or None."""
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        return None
    if mode & 0o044:
        return 'the acl file %s is group/world-readable, mode %03o — chmod 0600' % (path, mode)
    return None


def _acl_desc(d, where):
    if d is not None and (not isinstance(d, str) or not d.strip() or not d.isascii()):
        raise SystemExit('%s: "desc" must be terse ASCII' % where)


def _prefix_matcher(v, where):
    """The IP-kind rule matcher: the bare word 'any' (every address), or a
    comma-separated string of IP addresses / IP prefixes — strict CIDR, a
    prefix with host bits set refuses (spell the network). Returns the
    value normalized (the items stripped, comma-joined)."""
    if not isinstance(v, str):
        raise SystemExit('%s must be "any" or a comma-separated IP/IP-prefix string' % where)
    t = v.strip()
    if t.lower() == 'any':
        return 'any'
    items = [x.strip() for x in t.split(',')]
    if not all(items):
        raise SystemExit('%s: empty item in the comma-separated prefix list' % where)
    fam = None
    for x in items:
        try:
            net = ipaddress.ip_network(x, strict=True)
        except ValueError:
            try:
                wide = ipaddress.ip_network(x, strict=False)
                hint = ' — spell the network %s' % wide.with_prefixlen
            except ValueError:
                hint = ''
            raise SystemExit('%s: %r must be an IP or IP/prefix%s' % (where, x, hint))
        if fam is None:
            fam = net.version
        elif net.version != fam:
            raise SystemExit('%s: the matcher mixes IPv4 and IPv6 (%s and %s)' % (where, items[0], x))
    return ','.join(items)


_GATE_TYPES = {'write-registers': 'range', 'ip-prefix': 'prefix'}


def _write_gate_object(gate, base, allow=('write-registers',)):
    """The acl gate OBJECT (what a device profile carries under
    "acl"/"write", what a standalone acl file is): an optional terse-ASCII
    "desc", the optional gate "type" and the ordered "rules" list — one
    {"type": "allow"|"deny", matcher-key: matcher} object per rule (+ an
    optional "desc" each). THE MATCHER KEY IS THE GRAMMAR: "range" is the
    register kind (a "START:COUNT" range or a list of them, or the bare
    word "any" — all registers), "prefix" is the IP kind (an IP or
    IP/prefix, comma-separated, or "any" — every address). The gate
    "type" names the schema — "write-registers" (range rules),
    "ip-prefix" (prefix rules) — and must agree with the rules' key when
    spelled; a typeless register gate reads as "write-registers" (the
    legacy shape), a typeless IP gate refuses. ONE GRAMMAR PER GATE: the
    first matcher key pins the gate, and a gate whose rules mix "range"
    and "prefix" refuses. `allow` says which gate types this reader
    takes (the wrong-typed file refuses with the name in the error). The
    chain is a whitelist: it reads top to bottom and the LAST matching
    rule decides, and a client/register no rule decides refuses — the
    default deny any. Returns (desc, rules), the rules as (verb,
    matcher, desc, where) tuples in chain order; `base` names the gate
    in the errors ('<profile> acl/write', 'acl file <path>')."""
    unknown = sorted(k for k in gate if k not in ('desc', 'type', 'rules'))
    if unknown:
        raise SystemExit('%s: unknown key(s) %s ("desc", the optional gate "type" and the '
                         '"rules" list — one {"type": "allow"|"deny", "range"|"prefix": ...} '
                         'object per rule)' % (base, ', '.join(unknown)))
    gate_type = gate.get('type')
    if gate_type is not None and gate_type not in _GATE_TYPES:
        raise SystemExit('%s: unknown gate "type" %r (write-registers | ip-prefix)'
                         % (base, gate_type))
    _acl_desc(gate.get('desc'), base)
    gate_rules = gate.get('rules')
    if not isinstance(gate_rules, list) or not gate_rules:
        raise SystemExit('%s: the "rules" list is missing or empty (a gate that '
                         'gates nothing is a config error — spell the whole-space deny as '
                         '[{"type": "deny", "range": "any"}])' % base)
    kind = None
    for i, rule in enumerate(gate_rules):
        where = '%s rule %d' % (base, i + 1)
        if not isinstance(rule, dict) or not rule:
            raise SystemExit('%s must be an object with a "type" (allow/deny) and a '
                             '"range" or "prefix"' % where)
        unknown = sorted(k for k in rule if k not in ('type', 'range', 'prefix', 'desc'))
        if unknown:
            raise SystemExit('%s: unknown key(s) %s (type/range-or-prefix/desc)'
                             % (where, ', '.join(unknown)))
        has = [k for k in ('range', 'prefix') if k in rule]
        if len(has) > 1:
            raise SystemExit('%s: the rule carries both "range" and "prefix" — one grammar '
                             'per gate (range matches registers, prefix matches IPs)' % where)
        if kind and has and has[0] != kind:
            raise SystemExit('%s: the gate mixes "range" and "prefix" rules — one grammar '
                             'per gate (range matches registers, prefix matches IPs)' % where)
        if has:
            kind = has[0]
    if gate_type and kind and _GATE_TYPES[gate_type] != kind:
        raise SystemExit('%s: the gate "type" %s matches by "%s" — the rules match by "%s"'
                         % (base, gate_type, _GATE_TYPES[gate_type], kind))
    eff = None
    if gate_type:
        eff = gate_type
        kind = _GATE_TYPES[gate_type]
    elif kind == 'range':
        eff = 'write-registers'   # the legacy shape: a typeless register gate
    elif kind == 'prefix':
        raise SystemExit('%s: the gate matches by "prefix" and carries no "type" — spell '
                         '"type": "ip-prefix"' % base)
    if eff is not None and eff not in allow:
        raise SystemExit('%s: the gate is the %s gate — this reader takes the %s gate'
                         % (base, eff, ' or '.join(allow)))
    rules = []   # (verb, matcher-value, desc, where) in chain order
    for i, rule in enumerate(gate_rules):
        where = '%s rule %d' % (base, i + 1)
        verb = rule.get('type')
        if verb not in ('allow', 'deny'):
            raise SystemExit('%s: "type" must be allow or deny, got %r' % (where, verb))
        _acl_desc(rule.get('desc'), where)
        if kind == 'prefix':
            if 'prefix' not in rule:
                raise SystemExit('%s: the rule needs a "prefix"' % where)
            rules.append((verb, _prefix_matcher(rule['prefix'], where), rule.get('desc'), where))
        else:
            if 'range' not in rule:
                raise SystemExit('%s: the rule needs a "range"' % where)
            rules.append((verb, rule['range'], rule.get('desc'), where))
    return gate.get('desc'), rules


def load_write_gate_file(path, label=None, allow=('write-registers',)):
    """The standalone acl file (the write-registers file:<path> reference,
    and the IP-kind knobs' file:<path> values — the cache's acl/connect +
    acl/write, the scraper's metrics/acl): the root object IS the gate —
    the same acl gate object a device profile carries under "acl"/"write"
    (see _write_gate_object). `allow` says which gate types the caller
    takes (the default gates registers; the IP kind's readers pass their
    own type, or all of them for the generic tools). Returns (desc,
    rules)."""
    label = label or 'acl file %s' % path
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit('cannot read acl file %s: %s' % (path, e))
    if not isinstance(data, dict):
        raise SystemExit('%s must be the acl gate object: {"desc": ..., "rules": '
                         '[{"type": "allow"|"deny", "range"|"prefix": ...}]} — the same '
                         'object a device profile carries under "acl"/"write"' % label)
    return _write_gate_object(data, label, allow)


ANY_NET = '0.0.0.0/0'   # the table spelling of the whole IPv4 space — the word 'any'


class IPGate:
    """The file-loaded ip-prefix gate (the IP-kind knobs' file:<path>
    value — the cache's acl/connect + acl/write, the scraper's
    metrics/acl): the rule chain reads top to bottom, the LAST matching
    rule decides, and a peer no rule decides is refused — the default deny
    any (the same whitelist reading the write-registers gate speaks). The
    matchers precompile to networks (the loader validated them strict);
    the bare word 'any' matches every address (any = 0.0.0.0/0, the whole
    space — both families)."""

    def __init__(self, reference, desc, rules):
        self.reference = reference   # the knob spelling 'file:<path>' — the re-appliable text
        self.desc = desc
        self.rules = rules           # (verb, matcher, desc, where) tuples in chain order
        self.compiled = []           # (verb, networks-or-None) — None = the 'any' wildcard
        for verb, matcher, _rdesc, _where in rules:
            if str(matcher).strip().lower() == 'any':
                self.compiled.append((verb, None))
            else:
                nets = [ipaddress.ip_network(x.strip(), strict=False)
                        for x in str(matcher).split(',') if x.strip()]
                self.compiled.append((verb, nets))

    def allows(self, ip):
        """The chain on one peer address: the last matching rule decides,
        no match denies."""
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        decided = False
        for verb, nets in self.compiled:
            if nets is None or any(a.version == n.version and a in n for n in nets):
                decided = verb == 'allow'
        return decided


def parse_acl_value(text, label):
    """The IP-kind acl knob's value grammar: the system words and the
    network lists ride parse_acl; a `file:<path>` value passes through as
    the reference (the daemon reads the standalone ip-prefix gate file — a
    bad file refuses at start, like the write-registers acl)."""
    t = (text or '').strip() if text is not None else None
    if t and t.startswith('file:'):
        return t
    return parse_acl(text, label)


def resolve_metrics_acl(val, label='metrics/acl'):
    """The metrics/acl knob value -> (gate, warn): the system words and
    the network lists ride parse_acl; 'file:<path>' loads the standalone
    ip-prefix acl file (the gate object the shared
    schema/acl-ip-prefix.schema.json describes — the chain reads top to
    bottom, the LAST matching rule decides, a client no rule decides
    refuses). The gate: None = any, () = none, the networks tuple, IPGate
    = the file chain. SystemExit on a bad value or file; a
    group/world-readable acl file warns (the (gate, warn) pair — chmod
    0600 silences it)."""
    t = (val or '').strip()
    if t.startswith('file:'):
        desc, rules = load_write_gate_file(t[5:], allow=('ip-prefix',))
        return IPGate(t, desc, rules), acl_file_warn(t[5:])
    return parse_acl(t, label), None


def acl_value_text(acl):
    """The IP-kind acl knob's value as its set-grammar text (what `unset`
    re-parses and show config renders): 'any', 'none', the network list —
    or the file: reference (a raw string value or the resolved IPGate)."""
    if isinstance(acl, IPGate):
        return acl.reference
    if isinstance(acl, str) and acl.startswith('file:'):
        return acl
    return acl_text(acl)


def acl_gate_summary(acl):
    """The IP-kind acl knob's gate for humans (the start log, inspect):
    the system forms as acl_summary spells them, the file gate
    as 'file:<path> (N rule(s))'."""
    if isinstance(acl, IPGate):
        return '%s (%d rule(s))' % (acl.reference, len(acl.rules))
    return acl_summary(acl)


def acl_table(acl):
    """The IP-kind acl knob's table show's lines (one entry per line): the
    system forms spell the chain they implement — 'allow 0.0.0.0/0' (any),
    'deny 0.0.0.0/0' (none), 'deny 0.0.0.0/0' + one 'allow <net>' line per
    network (the whitelist); a file gate renders its own rules — the gate
    desc as the '% ' line, the descs as aligned '# ' comments, the matcher
    'any' spelled 0.0.0.0/0, a comma list fanned out one entry per line."""
    if isinstance(acl, IPGate):
        lines = ['%% %s' % acl.desc] if acl.desc else []
        rows = []
        for verb, matcher, rdesc, _where in acl.rules:
            if str(matcher).strip().lower() == 'any':
                entries = [ANY_NET]
            else:
                entries = [x.strip() for x in str(matcher).split(',') if x.strip()]
            for entry in entries:
                rows.append(('%s %s' % (verb, entry), (rdesc or '').strip() or None))
        width = max((len(prefix) for prefix, d in rows if d), default=0)
        for prefix, d in rows:
            lines.append(('%s # %s' % (prefix.ljust(width), d)) if d else prefix.rstrip())
        return lines
    if acl is None:
        return ['allow %s' % ANY_NET]
    if not acl:
        return ['deny %s' % ANY_NET]
    return ['deny %s' % ANY_NET] + ['allow %s' % n for n in acl]


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
