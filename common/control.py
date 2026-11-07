#!/usr/bin/env python3
"""The control server's shared base, one implementation for the family: the
wire tier (the unix/TCP listener with the 0600/0660 socket mode, the
peer-cred trusted peers, the token auth with the admin / read-only-ops
roles, the HMAC frame verification both ways), the buffered session
handler, the bye-frame announce ladder and the dump/reload family (the
write-behind dump, the restore, the whole-daemon reload with its re-exec
and the one-shot state file). The tool subclasses it with its grammar —
command()/_apply()/_get() — its registry rows and its reports; the class
attributes name the logger, the registry and the exit texts. Stdlib only."""
import hmac
import json
import logging
import os
import socket
import sys
import threading
import time

from common import dump as state
from common.cred import peer_uid
from common.dump import SECRET_REMOVED
from common.options import control_command, grouped_rows, knob_dictionary
from common.wiresec import ROLE_ADMIN, ROLE_OPS, OPS_VERBS, command_verb, proof_tag, role_allows, \
    role_tag, sign_reply, verify_request_mac


class ControlServer:
    """The family's control server. The subclass sets the class attributes:
    LOG (the daemon's logger), OPTIONS/SETTINGS (its registry), WHO (the
    show-knobs voice), EXIT_TEXT/RELOAD_TEXT (the bye-frame wording) and —
    for the fake, which has no config file — RELOAD_NEEDS_CONFIG = False and
    the XDG _reload_state_path override."""

    LOG = logging.getLogger('control')   # the subclass names its daemon's logger
    OPTIONS = ()                          # the registry rows — the subclass sets
    SETTINGS = {}                         # SETTING_BY_NAME — the subclass sets
    WHO = 'the daemon'                    # the show-knobs dictionary's voice
    EXIT_TEXT = 'the daemon is shutting down'
    RELOAD_TEXT = 'the daemon is reloading — the daemon restarts with the saved configuration'
    RELOAD_NEEDS_CONFIG = True            # the reload verb needs --config
    LINE_CAP = 1048576                    # the pre-auth line-buffer cap (drop past it)
    IDLE_TIMEOUT_S = 300                  # the control socket's idle timeout

    def __init__(self, target, reloader=None, stopper=None, audit=None, token=None,
                 defaults=None, trust_uids=None, socket_group=False, ops_token=None,
                 ops_verbs=None, config_path=None, dump_path=None,
                 restore_on_start=False, dump_key=None):
        self.reloader = reloader         # request reload: re-resolve the config, apply, returns the summary
        self.audit = audit               # the audit trail (common.audit), None = off
        self.token = token               # the TCP auth token (the admin role); None = no auth (the unix = the perms)
        self.ops_token = ops_token       # the read-only ops token (the ops role); None = off
        self.ops_verbs = frozenset(v.lower() for v in (ops_verbs or OPS_VERBS))   # the ops role's RBAC policy
        self.config_path = config_path   # the config script the daemon started from — the reload state lives beside it
        self.reload_pending = False      # a reload saved the state; the exec runs after the reply leaves the wire
        self.dump_path = dump_path or None   # the state dump file (the dump family)
        self.dump_restore = bool(restore_on_start)   # prospective-only: the START already chose
        self.dump_key = dump_key or None   # the dump seal key (startup-only: the reload re-exec re-resolves the same)
        self.is_unix = not isinstance(target, int) and not str(target).isdigit()
        self.port = None if self.is_unix else int(target)
        self.sockpath = str(target) if self.is_unix else None
        self.socket_group = bool(socket_group)   # chmod 0660 instead of 0600 on the unix socket
        self.trust_uids = trust_uids or frozenset()   # extra peer uids the unix socket trusts without the token
        self.stopper = stopper
        self.shutdown_pending = False
        self.defaults = defaults or {}   # setting -> configured startup value (what `unset` restores)
        self.overridden = set()          # settings changed live (`show status` carries the overridden= row)
        self.clients = set()             # the live control sockets (announce_exit)
        self.clients_lock = threading.Lock()
        self.started = time.monotonic()
        self.option_by_live = {o.live: o for o in self.OPTIONS if o.live}   # the row bounds' one home

    # --- the wire tier ---

    def start(self):
        self._restore_reload_state()   # a reload exec: the saved overrides re-apply once, the state file is consumed
        threading.Thread(target=self.serve, daemon=True).start()

    def describe(self):
        return 'unix:%s' % self.sockpath if self.is_unix else '127.0.0.1:%d' % self.port

    def cleanup(self):
        if self.is_unix and self.sockpath and os.path.exists(self.sockpath):
            try:
                os.unlink(self.sockpath)
            except OSError:
                pass

    def serve(self):
        srv = socket.socket(socket.AF_UNIX if self.is_unix else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if self.is_unix:
                if os.path.exists(self.sockpath):
                    self.LOG.warning('control socket %s exists, replacing it', self.sockpath)
                    os.unlink(self.sockpath)
                srv.bind(self.sockpath)
                # the mode is not left to the umask: 0600 = owner only
                os.chmod(self.sockpath, 0o660 if self.socket_group else 0o600)
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(('127.0.0.1', self.port))
            srv.listen(64)   # the backlog above the client limit: a connect burst must not RST
        except OSError as e:
            self.LOG.error('control server cannot bind %s: %s (use --control-port 0 to disable it)', self.describe(), e)
            return
        self.LOG.info('control server listening on %s%s',
                      self.describe(), (', token auth required on TCP' if self.token and not self.is_unix else '')
                      + (', read-only ops token accepted' if self.ops_token else ''))
        while True:
            try:
                client, addr = srv.accept()
                threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()
            except (OSError, RuntimeError) as e:
                self.LOG.error('control accept failed (%s), retrying', e)
                time.sleep(0.1)

    def handle(self, client, addr):
        who = self.peer(addr)
        self.LOG.debug('control client connected from %s', who)
        role = self.trusted_peer(client, who)   # the peer-cred shortcut = the admin role; TCP starts unauthenticated
        with self.clients_lock:
            self.clients.add(client)
        try:
            client.settimeout(self.IDLE_TIMEOUT_S)
            buf = b''
            while True:
                if b'\n' not in buf:      # buffered reads: a 1 MB frame must not
                    chunk = client.recv(65536)   # cost a syscall per byte
                    if not chunk:
                        break
                else:
                    chunk = b''
                buf += chunk
                if len(buf) > self.LINE_CAP:   # no newline = no frame: drop the amplifier
                    self.LOG.warning('control client from %s: the line exceeded %d bytes, dropping it', who, self.LINE_CAP)
                    break
                if b'\n' not in buf:
                    continue
                line, buf = buf.split(b'\n', 1)
                cmd, obj, reply, role = self.framed(line.decode('utf-8', 'replace').strip(), who, role)
                if cmd == 'auth':
                    ok = reply.startswith('ok')
                    if not ok and self.audit:
                        self.audit.event('AUTH-FAIL', 'peer=%s' % who)
                elif self.audit and cmd.lower() != 'ping':
                    self.audit.event('COMMAND', "peer=%s%s '%s'%s -> %s"
                                     % (who, role_tag(role), cmd, proof_tag(obj), reply.split(' ', 1)[0]))
                self.LOG.debug('control from %s: %s -> %s', who, cmd, reply)
                if obj is not None:
                    client.sendall((json.dumps(obj, ensure_ascii=False) + '\n').encode())
                if reply.startswith('bye'):
                    break
                if self.reload_pending:
                    break   # the reply is out — the post-loop hook re-execs
            if self.shutdown_pending and self.stopper:
                self.stopper('control command')   # reply is out, now really stop
            if self.reload_pending:
                self._exec_reload()               # reply is out, now really re-exec
        except (ConnectionError, OSError):
            pass
        except Exception as e:
            self.LOG.error('control handler crashed (%s)', e)
        finally:
            self.LOG.debug('control client from %s disconnected', who)
            with self.clients_lock:
                self.clients.discard(client)
            client.close()

    @staticmethod
    def peer(addr):
        """Where the client sits: an IP:port for TCP, the socket for unix."""
        if isinstance(addr, (tuple, list)) and len(addr) >= 2:
            return '%s:%d' % (addr[0], addr[1])
        return 'unix socket'

    def trusted_peer(self, client, who):
        """The peer-cred auth on the unix control socket: with a token
        configured, a peer the kernel vouches for — root, the daemon's own
        user or one of trust_uids — is authenticated without the token (a
        local systemd unit speaks without sharing the secret) and holds the
        admin role. TCP peers always need a token (admin or ops)."""
        if not (self.token and self.is_unix):
            return None
        uid = peer_uid(client)
        if uid is None:
            return None
        if uid == 0 or uid == os.getuid() or uid in self.trust_uids:
            self.LOG.debug('control client from %s: trusted peer uid %d, no token required', who, uid)
            return ROLE_ADMIN
        self.LOG.info('control client from %s: peer uid %d is not trusted, the token is required', who, uid)
        return None

    def session_key(self, role):
        """The hmac key of one session's role: the ops sessions sign and
        verify with the ops token, everything else (admin, trusted peer,
        pre-auth) with the admin token."""
        return self.ops_token if role == ROLE_OPS else self.token

    def auth_role(self, given):
        """Which role a presented token authenticates into (hmac.compare_digest
        against both keys): the admin token, the ops token, or None."""
        if isinstance(given, str):
            if self.token and hmac.compare_digest(given, self.token):
                return ROLE_ADMIN
            if self.ops_token and hmac.compare_digest(given, self.ops_token):
                return ROLE_OPS
        return None

    def framed(self, line, who, role):
        """One wire frame in, one out: parse {"cmd": ...}, gate the TCP auth,
        gate the ops role (show/clear only), verify the frame mac keyed by
        the session's token, run the command. Returns (cmd, reply-obj,
        internal-reply, role) — the role so the auth reply can promote the
        session. The text of a multi-line reply keeps its embedded newlines;
        the '.' terminator of the internal form is stripped (the JSON frame
        needs no framing)."""
        try:
            obj = json.loads(line) if line else {}
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or not isinstance(obj.get('cmd'), str):
            return '', {'status': 'err',
                        'text': 'malformed request: expected {"cmd": "<command>"} JSON'}, 'err malformed request', role
        cmd = obj['cmd']
        if self.token and cmd.lower() != 'auth' and role is None:
            return cmd, {'status': 'err', 'text': 'authenticate first: {"cmd": "auth", "token": "..."}'}, \
                'err authenticate first', role
        if cmd.lower() == 'auth':
            granted = self.auth_role(obj.get('token'))
            if granted:
                key = self.session_key(granted)
                reply = 'ok authenticated'
                return 'auth', {'status': 'ok', 'text': 'authenticated', 'mac': sign_reply(key, reply)}, reply, granted
            return 'auth', {'status': 'err', 'text': 'bad token'}, 'err bad token', role
        key = self.session_key(role)
        if key and obj.get('mac') is None and not self.is_unix:
            return cmd, {'status': 'err',
                         'text': 'unsigned command rejected: TCP commands carry the hmac-sha256 of the command, keyed by the token'}, \
                'err unsigned command', role
        if key and obj.get('mac') is not None and not verify_request_mac(key, cmd, obj.get('mac')):
            return cmd, {'status': 'err',
                         'text': 'the command mac does not verify (tampered or corrupted frame)'}, 'err bad command mac', role
        if not role_allows(role, cmd, self.ops_verbs):
            verb = command_verb(cmd) or cmd
            text = ('forbidden: the ops token runs the %s verbs only (%s needs the admin token)'
                    % ('/'.join(sorted(self.ops_verbs)), verb))
            reply = 'err ' + text
            reply_obj = {'status': 'err', 'text': text}
            if key:
                reply_obj['mac'] = sign_reply(key, reply)
            self.LOG.warning('control: ops session from %s denied %r (read-only role)', who, cmd)
            return cmd, reply_obj, reply, role
        reply = self.command(cmd)
        if reply is None:              # quit: no reply, just close
            return cmd, None, 'bye', role
        status, _, text = reply.partition(' ')
        reply_obj = {'status': status, 'text': text}
        if key:
            reply_obj['mac'] = sign_reply(key, reply)
        return cmd, reply_obj, reply, role

    def announce_exit(self, reason, text=None):
        """The daemon is going down: send every connected control client a
        bye frame (the consoles print the notice and exit instead of trying
        to reconnect to a dead daemon) and close their sockets. `text`
        replaces the shutdown wording (the reload speaks of restarting)."""
        frame = (json.dumps({'status': 'bye',
                             'text': text or 'daemon-exit: %s (%s)' % (self.EXIT_TEXT, reason)},
                            ensure_ascii=False)   # the frame is utf-8 like every other reply
                 + '\n').encode()
        with self.clients_lock:
            clients, self.clients = list(self.clients), set()
        for client in clients:
            try:
                client.sendall(frame)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass

    # --- the registry surfaces ---

    def config_mapping(self):
        """The knob -> control-command mapper (help config): every option of
        the registry under its display group (the row's `group`, ungrouped
        rows headerless), with the command that changes it on a running
        daemon — or the restart note when the knob is startup-only."""
        lines = ['ok config mapping']
        for key, rows in grouped_rows(self.OPTIONS):
            if key:
                lines.append('# --- %s ---' % key)
            for o in rows:
                lines.append('%-24s %s' % (o.name, control_command(o)))
        return '\n'.join(lines)

    def knobs_dictionary(self):
        """The dictionary of all knobs (show knobs): every option of the
        registry under its display group, with its flag, its env twin(s),
        the control command that changes it and the secret marker."""
        return knob_dictionary(self.OPTIONS, who=self.WHO)

    TYPED_CONVS = (int, float, str)       # the typed knobs the row's bounds gate

    def _gate_range(self, key, v, what=''):
        """The row's min/max (inclusive) — the registry is the one home for
        a knob's bounds; the branch parses and plumbs, the row gates."""
        opt = self.option_by_live.get(key)
        if opt is None or opt.conv not in self.TYPED_CONVS:
            return
        if (opt.min is not None and not v >= opt.min) or (opt.max is not None and not v <= opt.max):
            raise ValueError('%s must be %s..%s%s' % (key, opt.min, opt.max, (' ' + what) if what else ''))

    # --- the dump/reload family ---

    def apply_dump_settings(self, settings):
        """Re-apply the dumped overrides; returns (applied, failed-name-list).
        An unknown setting or a value the current config rejects is skipped,
        never fatal; a *** SECRET REMOVED *** placeholder (the dump renders
        an overridden secret's knob) is skipped and named — the secret keeps
        its current value."""
        applied, failed = 0, []
        for name, value in (settings or {}).items():
            if name not in self.SETTINGS:
                failed.append(name)
                continue
            if str(value) == SECRET_REMOVED:
                failed.append('%s (secret, not restored — re-pass by flag/env, or as file:<path>)' % name)
                continue
            try:
                self._apply(name, str(value))
                self.overridden.add(name)
                applied += 1
            except ValueError as e:
                failed.append('%s (%s)' % (name, e))
        return applied, failed

    def _reload_state_path(self):
        return self.config_path + '.reload' if self.config_path else None

    def _save_reload_state(self):
        """The overrides in their wire-parsable form (dump_settings) to the
        state file — the shared dump writer (sealed when dump/key is
        configured); the secrets ride as *** SECRET REMOVED *** (the value
        never lands in the file). Returns (settings, lost-secret-names);
        raises OSError on an unwritable home."""
        settings = self.dump_settings()
        lost = sorted(k for k in self.overridden if settings.get(k) == SECRET_REMOVED)
        state.write_dump(self._reload_state_path(), settings, key=self.dump_key)
        return settings, lost

    def _restore_reload_state(self):
        """One-shot, at start: a reload exec re-applies the saved overrides
        and consumes the state file — a later manual start stays pure (the
        config file and the flags alone). A state older than two minutes is
        stale (a failed start in between): discarded, never applied. The
        file is the shared dump shape — sealed when dump/key is configured
        (the re-exec re-resolves the same key)."""
        path = self._reload_state_path()
        if not path or not os.path.exists(path):
            return
        try:
            state_obj = state.read_dump_state(path, key=self.dump_key)
            if time.time() - state_obj.get('saved', 0) > 120:
                self.LOG.warning('reload: the state file %s is stale, discarding it', path)
                os.unlink(path)
                return
            applied, failed = self.apply_dump_settings(state_obj.get('settings'))
            os.unlink(path)
            self.LOG.info('reload: %d override(s) re-applied from %s%s', applied, path,
                          (' (%d skipped: %s)' % (len(failed), ', '.join(failed))) if failed else '')
            if self.audit:
                self.audit.event('RELOAD', 'restored %d override(s) from %s' % (applied, path))
        except (OSError, ValueError) as e:
            self.LOG.error('reload: the state file %s is unreadable (%s) — starting without it', path, e)

    def reload_daemon(self):
        """The `reload` verb: save the overrides, then restart the whole
        daemon. The fresh process re-resolves the config file — the
        startup-only knobs take their configured values — and start()
        re-applies the saved overrides once. The secrets never save (the
        dump rule): an overridden secret is named in the reply, to re-pass
        by flag/env, or as file:<path>."""
        if self.RELOAD_NEEDS_CONFIG and not self.config_path:
            return 'err reload needs a config path (start with --config)'
        try:
            settings, lost = self._save_reload_state()
        except OSError as e:
            self.LOG.error('control: reload could not save the overrides: %s', e)
            return 'err reload failed: %s' % e
        self.reload_pending = True
        self.LOG.info('control: reload — %d override(s) saved to %s, re-execing',
                      len(settings), self._reload_state_path())
        msg = 'ok reload: %s, the daemon restarts now' % (
            '%d override(s) saved' % len(settings) if settings else 'no overrides to save')
        if lost:
            msg += ' (%s: secret, not saved — re-pass by flag/env, or as file:<path>)' % ', '.join(lost)
        return msg

    def _exec_reload(self):
        """The reply is out (the session loop calls this after it): announce
        to the consoles and re-exec in place — the same argv re-resolves the
        config, the fresh daemon rebinds the control target (stale sockets
        are replaced) and restores the saved overrides."""
        if self.audit:
            self.audit.event('RELOAD', 'exec: the daemon re-execs (pid %d)' % os.getpid())
        self.announce_exit('reload', text='daemon-exit: %s' % self.RELOAD_TEXT)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(0.2)   # let the bye frames drain
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def dump_state(self):
        """The write-behind: the live setting overrides to the configured
        dump path (the `request dump` command and the graceful shutdown) —
        sealed when dump/key is configured."""
        if not self.dump_path:
            return 'err no dump path configured (set dump/path or --dump-path)'
        settings = self.dump_settings()
        try:
            n = state.write_dump(self.dump_path, settings, key=self.dump_key)
        except (OSError, ValueError) as e:
            self.LOG.error('control: the dump to %s failed: %s', self.dump_path, e)
            return 'err dump failed: %s' % e
        self.LOG.info('control: state dumped to %s (%d setting(s)%s)', self.dump_path, n,
                      ', sealed' if self.dump_key else '')
        return 'ok dumped %d setting(s) to %s%s' % (n, self.dump_path, ' (sealed)' if self.dump_key else '')

    def restore_state(self):
        """Load a dump back: the setting overrides re-apply (a sealed dump
        restores only under the configured dump/key)."""
        if not self.dump_path:
            return 'err no dump path configured (set dump/path or --dump-path)'
        if not os.path.exists(self.dump_path):
            return 'err no dump at %s yet (run dump first)' % self.dump_path
        try:
            settings = state.read_dump(self.dump_path, key=self.dump_key)
            applied, failed = self.apply_dump_settings(settings)
        except ValueError as e:
            return 'err restore failed: %s' % e
        self._after_restore()
        self.LOG.info('control: state restored from %s (%d setting(s))', self.dump_path, applied)
        return 'ok restored %d setting(s) from %s%s' % (
            applied, self.dump_path,
            ' (%d skipped: %s)' % (len(failed), ', '.join(failed)) if failed else '')

    def _after_restore(self):
        """The tool's post-restore nudge (the scraper wakes its poll loop)."""

    def shutdown_dump(self):
        """The graceful stop's write-behind: the overrides to the dump path
        (no reply — the log carries it; sealed when dump/key is set)."""
        if not self.dump_path:
            return
        try:
            n = state.write_dump(self.dump_path, self.dump_settings(), key=self.dump_key)
            self.LOG.info('state dumped to %s (%d setting(s)%s)', self.dump_path, n,
                          ', sealed' if self.dump_key else '')
        except (OSError, ValueError) as e:
            self.LOG.error('the shutdown dump to %s failed: %s', self.dump_path, e)
