#!/usr/bin/env python3
"""Regression test for the audit trail's hash chain (docs/SECURITY.md F10):
every entry carries a short hash right after the event name, chaining to the
writer's previous entry,
and scripts/audit_verify.py detects tampering (an edited
line, a deleted line, reordered lines), passes legit trails (restarts chain
seamlessly, rotation spans the backups), and reports legacy unsigned lines
without failing them.

  python3 tests/audit-chain.py

Checks: ALL PASS (or a FAILURES list; exit 1).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

if not os.environ.get('PV_RUN_DIR'):   # the battery sets it (scripts/battery.sh)
    sys.exit('suite: run through scripts/battery.sh (the run dir + the port slot; '
             'a standalone run shares /tmp scratch and collides across sessions)')
print('NOTE started at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))

PROFILE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ('quick', 'full') \
    else os.environ.get('PV_SUITE_PROFILE', 'quick')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(REPO, 'scripts', 'audit_verify.py')
sys.path.insert(0, REPO)
from common.runtime.audit import AuditLog, entry_hash, GENESIS   # noqa: E402

FAILURES = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' — ' + str(detail) if detail and not ok else ''))
    if not ok:
        FAILURES.append(name)


def verify(*paths, rc=0, quiet=False, contain=None, absent=None):
    cmd = [sys.executable, V] + ([] if not quiet else ['-q']) + list(paths)
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    ok = r.returncode == rc
    if contain:
        ok = ok and all(c in out for c in contain)
    if absent:
        ok = ok and not any(a in out for a in absent)
    return ok, out


class QuickDone(Exception):
    pass


def main():
    tmp = tempfile.mkdtemp(prefix='audit_chain_')
    try:
        log = os.path.join(tmp, 'audit.log')

        # 1. two interleaved prefixes: every chain holds
        a = AuditLog(log, 'CACHE')
        c = AuditLog(log, 'CLI')
        a.event('START', 'version=test')
        c.event('CONNECT', 'target=127.0.0.1:1')
        a.event('COMMAND', "cmd='show version' result=ok")
        c.event('COMMAND', "cmd='quit' result=local")
        a.event('REQUESTS', 'clients=1 reads=3 writes=0')
        ok, out = verify(log, contain=['OK'])
        check('interleaved writers verify', ok, out)
        # the layout: the hash sits right after the event name, no decoration
        first = open(log).read().splitlines()[0].split(' ')
        check('layout: the hash rides its hash= token, the detail its message=', len(first) >= 7 and first[1] == 'AUDIT'
              and first[2] == 'tools=CACHE' and first[3] == 'tag=daemon'
              and first[5].startswith('hash=') and len(first[5]) == 17
              and all(ch in '0123456789abcdef' for ch in first[5][5:])
              and first[6] == 'message=version=test', ' '.join(first[:7]))

        # 2. an edited line breaks the chain at that line
        lines = open(log).read().splitlines()
        lines[2] = lines[2].replace("'show version'", "'show secrets'")
        open(log, 'w').write('\n'.join(lines) + '\n')
        ok, out = verify(log, rc=1, contain=['line 3 [CACHE:daemon]: hash mismatch'])
        check('edited line detected (right line, right prefix)', ok, out)

        # 3. a deleted line breaks the chain
        lines = open(log).read().splitlines()
        del lines[2]
        open(log, 'w').write('\n'.join(lines) + '\n')
        ok, out = verify(log, rc=1)
        check('deleted line detected', ok, out)

        # 4. reordered lines break the chain
        lines = open(log).read().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        open(log, 'w').write('\n'.join(lines) + '\n')
        ok, out = verify(log, rc=1)
        check('reordered lines detected', ok, out)

        # 5. the pre-KV lines: the validator speaks the current grammar only
        open(log, 'w').write(
            '2026-01-01T00:00:00Z AUDIT CACHE START version=old\n'
            '2026-01-01T00:00:01Z AUDIT CACHE COMMAND \'x\' -> ok\n')
        ok, out = verify(log, rc=1, contain=['2 broken', 'malformed'])
        check('pre-KV lines read malformed (the current grammar only)', ok, out)

        # 6. a restarted writer chains from its own trail (no false break)
        open(log, 'w').write('')
        a = AuditLog(log, 'CACHE')
        a.event('START', 'v1')
        a.event('SHUTDOWN', 'clean')
        b = AuditLog(log, 'CACHE')          # the "restart": a fresh instance, same prefix
        b.event('START', 'v2')
        ok, out = verify(log, contain=['OK'])
        check('restarted writer chains seamlessly', ok, out)

        if PROFILE == 'quick':
            raise QuickDone()   # quick: the core sections only
        # 7. rotation: the chain spans the backups (verified oldest-first)
        open(log, 'w').write('')
        a = AuditLog(log, 'CACHE', max_mb=0.000001, files=3)   # ~every event rotates
        for i in range(6):
            a.event('COMMAND', 'batch-%d -> ok' % i)
        a.close()
        files = sorted(f for f in os.listdir(tmp) if f.startswith('audit.log'))
        ok, out = verify(log, rc=0, contain=['backup'])
        check('chain spans the rotated backups (files: %s)' % ','.join(files), ok, out)

        # 8. the real end-to-end trail: the fake's INV prefix over a control session
        flog = os.path.join(tmp, 'fake.log')
        fake = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
        ctl = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py')
        proc = subprocess.Popen([sys.executable, fake, '--static', '--listen', '127.0.0.1:15977',
                                 '--control-port', '15978', '--audit-log', flog],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.0)
            subprocess.run([sys.executable, ctl, '--control-port', '15978', '--audit-log', flog,
                            'set', 'pv', '2000'], capture_output=True, text=True, timeout=15)
            subprocess.run([sys.executable, ctl, '--control-port', '15978', '--audit-log', flog,
                            'quit'], capture_output=True, text=True, timeout=15)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        ok, out = verify(flog, contain=['OK'])
        check('the fake + ctl trail verifies end-to-end', ok, out)

        # 9. the syslog forwarding (audit/forward = syslog, F10): the mirror
        # carries the tag + the finished line (chain hash included), a send
        # failure stops the mirroring quietly, a socket-less spelling refuses
        import io
        import socket as sockmod
        import threading
        from contextlib import redirect_stderr

        import common.runtime.audit as audit_mod
        ssock_path = os.path.join(tmp, 'syslog.sock')
        ssock = sockmod.socket(sockmod.AF_UNIX, sockmod.SOCK_DGRAM)
        ssock.bind(ssock_path)
        ssock.settimeout(5)
        saved_sockets = audit_mod.SYSLOG_SOCKETS
        audit_mod.SYSLOG_SOCKETS = (ssock_path,)
        try:
            fwd = AuditLog(log, 'CACHE', app='modbus-cache', forward='syslog')
            fwd.event('COMMAND', "'show version' -> ok")
            data = ssock.recv(65536).decode('utf-8')
            import re
            mirrored = re.sub(r'^<\d+>', '', data).rstrip('\x00')   # the PRI + the NUL journald strips
            with open(log) as fh:
                last = fh.read().rstrip().splitlines()[-1]
            check('the syslog mirror carries the tag + the finished line (chain hash included)',
                  mirrored == 'modbus-cache: %s' % last, '%r vs %r' % (mirrored, last))

            # 9b. the explicit socket (syslog:/path): the same mirror without
            # the auto-scan — and the socket-type probe (a stream-only
            # listener is served by a stream handler)
            ssock.close()
            os.unlink(ssock_path)
            explicit_path = os.path.join(tmp, 'explicit.sock')
            esock = sockmod.socket(sockmod.AF_UNIX, sockmod.SOCK_DGRAM)
            esock.bind(explicit_path)
            esock.settimeout(5)
            fwd2 = AuditLog(log + '.x', 'CACHE', app='modbus-cache', forward='syslog:' + explicit_path)
            fwd2.event('COMMAND', "'show version' -> ok")
            data = esock.recv(65536).decode('utf-8')
            mirrored = re.sub(r'^<\d+>', '', data).rstrip('\x00')
            with open(log + '.x') as fh:
                last = fh.read().rstrip().splitlines()[-1]
            check('the explicit syslog:/path mirror carries the finished line',
                  mirrored == 'modbus-cache: %s' % last, '%r vs %r' % (mirrored, last))
            esock.close()
            os.unlink(explicit_path)

            err = io.StringIO()
            with redirect_stderr(err):
                fwd.event('COMMAND', "'set pv 2000' -> ok")
                fwd.event('COMMAND', "'quit' -> bye")
            ok, out = verify(log, contain=['OK'])
            check('a send failure stops the forwarding (one note, the trail keeps the chain)',
                  ok and fwd._syslog is None and 'forwarding stopped' in err.getvalue(),
                  err.getvalue())

            audit_mod.SYSLOG_SOCKETS = ()
            try:
                AuditLog(log, 'CACHE', forward='syslog')
                check('a socket-less syslog spelling refuses', False, 'no ValueError')
            except ValueError as e:
                check('a socket-less syslog spelling refuses', 'no local syslog socket' in str(e), str(e))
            try:
                AuditLog(log, 'CACHE', forward='udp')
                check('a foreign forward spelling refuses', False, 'no ValueError')
            except ValueError as e:
                check('a foreign forward spelling refuses', 'must be none, syslog' in str(e), str(e))
        finally:
            audit_mod.SYSLOG_SOCKETS = saved_sockets

        # 9c. the remote targets (the F10 finish line): a TCP collector
        # speaks RFC6587 (the octet-count framing), the envelope is RFC5424
        # with the chain riding the SD-ELEMENT and the native line verbatim
        # in the MSG; CEF wraps additively; UDP is best-effort; a dead
        # collector re-arms lazily; the remote-only mode leaves no local
        # file and reseeds at GENESIS
        class TcpCollector:
            """A minimal octet-count collector: one thread accepts the
            forwarders' connections, one reader per connection parses the
            `<len> ` frames into self.frames."""

            def __init__(self, port=None):
                # no SO_REUSEADDR on the first bind: the ephemeral port is
                # this process's alone; the up() rebind below keeps it (the
                # TIME_WAIT pairs on the same port)
                self.srv = sockmod.socket()
                self.srv.bind(('127.0.0.1', port or 0))
                self.srv.listen(64)
                self.port = self.srv.getsockname()[1]
                self.frames = []
                self.conns = []
                self._run = True
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()

            def _loop(self):
                while self._run:
                    try:
                        c, _ = self.srv.accept()
                    except OSError:
                        return
                    self.conns.append(c)
                    threading.Thread(target=self._read, args=(c,), daemon=True).start()

            def _read(self, c):
                c.settimeout(10)
                buf = b''
                while True:
                    try:
                        chunk = c.recv(65536)
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf += chunk
                    while b' ' in buf:
                        raw, rest = buf.split(b' ', 1)
                        if not raw.isdigit():
                            return
                        if len(rest) < int(raw):
                            break
                        self.frames.append(rest[:int(raw)])
                        buf = rest[int(raw):]

            def down(self):
                self._run = False
                for c in self.conns:
                    try:
                        c.close()
                    except OSError:
                        pass
                self.srv.close()
                self._thread.join(5)

            def up(self):   # the same port again — the re-arm's connect succeeds
                self.__init__(self.port)

        def chain_of(frame):
            """The pieces of one remote frame: the native line's stamp, the
            SD-ELEMENT's prefix + chain hash and the hashed body — the
            envelope's extracted fields, exactly what a collector's
            chain-verifying search reads."""
            text = frame.decode('utf-8', 'replace')
            sd = text.split('[pvDash@1 ', 1)[1].split(']', 1)[0]
            prefix = sd.split('prefix="')[1].split('"')[0]
            chain = sd.split('chain="')[1].split('"')[0]
            native = text.split('] ', 1)[1]
            parts = native.split(' ')
            if parts[2].startswith('tools='):   # the KV line: the body carries tag= type= message=
                return parts[0], prefix, chain, ' '.join(parts[3:5] + parts[6:])
            return parts[0], prefix, chain, ' '.join(parts[3:4] + parts[5:])

        col = TcpCollector()
        try:
            tlog = os.path.join(tmp, 'tcp.log')
            w = AuditLog(tlog, 'CACHE', app='modbus-cache', forward='tcp://127.0.0.1:%d' % col.port)
            w.event('COMMAND', "'show version' -> ok")
            deadline = time.time() + 10
            while not col.frames and time.time() < deadline:
                time.sleep(0.05)
            frame = col.frames[0].decode()
            stamp, prefix, chain, body = chain_of(col.frames[0])
            last = open(tlog).read().rstrip().splitlines()[-1]
            ok = (frame.startswith('<28>1 ') and frame.split(' ')[5] == 'command'
                  and '[pvDash@1 prefix="CACHE" role="daemon" chain="' in frame
                  and frame.split('] ', 1)[1] == last
                  and chain == entry_hash(GENESIS, stamp, prefix, body))
            check('the tcp:// mirror: RFC6587 framing + the RFC5424 envelope + the chain in the SD', ok, frame[:160])

            # 9d. CEF: the additive wrapping, msg= verbatim, the severity table
            w2 = AuditLog(tlog + '.cef', 'CACHE', app='modbus-cache',
                          forward='tcp://127.0.0.1:%d' % col.port, forward_format='cef')
            w2.event('COMMAND', "'show version' -> ok")
            w2.event('COMMAND', "cmd='set x\\\\1=y' result=err")
            deadline = time.time() + 10
            while len(col.frames) < 3 and time.time() < deadline:
                time.sleep(0.05)
            okc, oke = False, False
            last_cef = open(tlog + '.cef').read().rstrip().splitlines()[0]   # the CEF writer's own first row
            esc = last_cef.replace('\\', '\\\\').replace('=', '\\=')   # the CEF msg= escaping: the backslash first, then the =
            for fr in col.frames[1:]:
                cef = fr.decode('utf-8', 'replace')
                if 'CEF:0|pv-dash|modbus-cache|' in cef and '|command|command|4| rt=' in cef \
                        and ' cs1Label=AuditChain cs1=' in cef and ' cs2Label=AuditPrefix cs2=CACHE msg=' in cef \
                        and cef.split('msg=', 1)[1] == esc:
                    okc = True
                if '|command|command|7|' in cef and 'msg=' in cef and r'\\\\1\=y' in cef.split('msg=', 1)[1]:
                    oke = True
            check('the CEF envelope: the header fields + cs1/cs2 + the msg verbatim', okc, b''.join(col.frames).decode('utf-8', 'replace'))
            check('the CEF severity table (err = 7) + the backslash/equals escaping', oke)

            # 9e. UDP: one datagram per line, best-effort (RFC5426)
            usock = sockmod.socket(sockmod.AF_INET, sockmod.SOCK_DGRAM)
            usock.bind(('127.0.0.1', 0))
            uport = usock.getsockname()[1]
            usock.settimeout(10)
            w3 = AuditLog(tlog + '.udp', 'CACHE', app='modbus-cache', forward='udp://127.0.0.1:%d' % uport)
            w3.event('COMMAND', "'show version' -> ok")
            uframe = usock.recv(65536).decode()
            usock.close()
            check('the udp:// mirror: one datagram, the RFC5424 envelope',
                  uframe.startswith('<28>1 ') and '[pvDash@1 prefix="CACHE" role="daemon" chain="' in uframe, uframe[:120])
        finally:
            col.down()

        # 9f. the lazy re-arm: a send failure notes once, the next event
        # re-opens, the success notes the dropped count
        err = io.StringIO()
        col2 = TcpCollector()
        try:
            rlog = os.path.join(tmp, 'rearm.log')
            wr = AuditLog(rlog, 'CACHE', app='modbus-cache', forward='tcp://127.0.0.1:%d' % col2.port)
            with redirect_stderr(err):
                wr.event('COMMAND', 'one -> ok')
                col2.down()
                wr.event('COMMAND', 'two -> ok')    # the buffered send may still pass
                wr.event('COMMAND', 'three -> ok')  # the RST lands — the stop note
                wr.event('COMMAND', 'four -> ok')   # the rearm: the connect refuses (the collector is down)
                col2.up()
                wr.event('COMMAND', 'five -> ok')   # the rearm connects — the re-armed note
            notes = err.getvalue()
            deadline = time.time() + 10
            while len(col2.frames) < 1 and time.time() < deadline:
                time.sleep(0.05)
            check('a dead collector: the fail-stop note, then the lazy re-arm with the dropped count',
                  notes.count('forwarding stopped') == 1
                  and notes.count('re-armed after') == 1
                  and 're-armed after ' in notes and 're-arming on the next event' in notes
                  and len(col2.frames) == 1, notes)
        finally:
            col2.down()

        # 9g. the remote-only mode: no local file, the lines arrive, the
        # chain reseeds at GENESIS (per run — the restart is a documented
        # discontinuity the collector's alert whitelists)
        col3 = TcpCollector()
        try:
            never = os.path.join(tmp, 'never', 'audit.log')
            rlog2 = os.path.join(tmp, 'remote.log')
            with redirect_stderr(io.StringIO()) as rerr:
                wr2 = AuditLog('none', 'INV', app='fake-inverter', forward='tcp://127.0.0.1:%d' % col3.port)
            wr2.event('START', 'version=test')
            wr2.event('COMMAND', 'x -> ok')
            deadline = time.time() + 10
            while len(col3.frames) < 2 and time.time() < deadline:
                time.sleep(0.05)
            s1, p1, h1, b1 = chain_of(col3.frames[0])
            s2, p2, h2, b2 = chain_of(col3.frames[1])
            check('the remote-only mode: no local file, the lines arrive, the chain runs',
                  not os.path.exists(never) and wr2.path == 'none'
                  and h1 == entry_hash(GENESIS, s1, p1, b1) and h2 == entry_hash(h1, s2, p2, b2),
                  b''.join(col3.frames).decode('utf-8', 'replace'))
            wr3 = AuditLog('none', 'INV', app='fake-inverter', forward='tcp://127.0.0.1:%d' % col3.port)
            wr3.event('START', 'version=test2')   # the "restart": the fresh writer reseeds
            deadline = time.time() + 10
            while len(col3.frames) < 3 and time.time() < deadline:
                time.sleep(0.05)
            s3, p3, h3, b3 = chain_of(col3.frames[2])
            check('the restart reseeds at GENESIS (the collector sees the discontinuity)',
                  h3 == entry_hash(GENESIS, s3, p3, b3), col3.frames[2][:120])
            # 9h. the full-off fold: none without a forward = --no-audit-log's state
            err2 = io.StringIO()
            with redirect_stderr(err2):
                wr4 = AuditLog('none', 'CACHE', app='modbus-cache')
            wr4.event('COMMAND', 'x -> ok')
            check('none without a forward folds to the audit disabled (the warn line)',
                  wr4.disabled and not os.path.exists(os.path.join(tmp, 'none'))
                  and 'the audit is disabled' in err2.getvalue(), err2.getvalue())

            # 9i. the real bins, remote-only end to end: the fake's trail
            # lands at the collector, no XDG state dir is created
            xdg = os.path.join(tmp, 'xdg-e2e')
            flog2 = os.path.join(tmp, 'fake-e2e.log')
            proc = subprocess.Popen([sys.executable, fake, '--static', '--listen', '127.0.0.1:15987',
                                     '--control-port', '15988', '--audit-log', 'none',
                                     '--audit-forward', 'tcp://127.0.0.1:%d' % col3.port],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    env=dict(os.environ, XDG_STATE_HOME=xdg))
            ctl2 = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-ctl.py')
            try:
                time.sleep(1.2)
                subprocess.run([sys.executable, ctl2, '--control-port', '15988', 'set', 'pv', '2000'],
                               capture_output=True, text=True, timeout=15)
                subprocess.run([sys.executable, ctl2, '--control-port', '15988', 'quit'],
                               capture_output=True, text=True, timeout=15)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            deadline = time.time() + 10
            while time.time() < deadline and not any(
                    (b'tools=INV tag=daemon type=start' in fr and b'version=' in fr) and b'tools=INV tag=daemon type=command' in b''.join(col3.frames)
                    for fr in col3.frames):
                time.sleep(0.1)
            events = [tuple(chain_of(fr)[1:3]) + (chain_of(fr)[3].split(' ')[1],) for fr in col3.frames]
            check('the fake, remote-only: the INV trail arrives at the collector, no local state',
                  any(e[0] == 'INV' and e[2] == 'type=start' for e in events)
                  and any(e[0] == 'INV' and e[2] == 'type=command' for e in events)
                  and not os.path.exists(os.path.join(xdg, 'fake-inverter')))
        finally:
            col3.down()

        # 9i. the grammar gates: the remote/none spellings through the real bins
        fake = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
        r = subprocess.run([sys.executable, fake, '--static', '--dry-run', '--audit-forward', 'bogus'],
                           capture_output=True, text=True, timeout=15)
        check('a bad --audit-forward answers with one clean ERROR line (rc 1, no traceback)',
              r.returncode == 1 and 'audit-forward must be none, syslog, syslog:/path' in r.stderr
              and 'Traceback' not in r.stderr, r.stderr)
        r = subprocess.run([sys.executable, fake, '--static', '--dry-run', '--audit-forward', 'syslog:/no/such/socket'],
                           capture_output=True, text=True, timeout=15)
        check('a missing explicit syslog socket refuses (rc 1, no traceback)',
              r.returncode == 1 and 'does not exist' in r.stderr and 'Traceback' not in r.stderr, r.stderr)
        r = subprocess.run([sys.executable, fake, '--static', '--dry-run', '--audit-forward', 'udp://host:0'],
                           capture_output=True, text=True, timeout=15)
        check('a bad port refuses with the grammar one-liner',
              r.returncode == 1 and 'udp://host[:port] or tcp://host[:port]' in r.stderr, r.stderr)
        r = subprocess.run([sys.executable, fake, '--static', '--dry-run', '--audit-forward-format', 'gelf'],
                           capture_output=True, text=True, timeout=15)
        check('a bad format refuses (rc 1, no traceback)',
              r.returncode == 1 and 'audit-forward-format must be one of rfc5424, cef' in r.stderr
              and 'Traceback' not in r.stderr, r.stderr)
        r = subprocess.run([sys.executable, fake, '--static', '--dry-run', '--audit-log', 'none'],
                           env=dict(os.environ, XDG_STATE_HOME=os.path.join(tmp, 'xdg')),
                           capture_output=True, text=True, timeout=15)
        check('--audit-log none without a forward: the start warns, the fold disables (rc 0)',
              r.returncode == 0 and 'the audit is disabled' in r.stderr, r.stderr)

        # 10. exit code and stdin
        r = subprocess.run([sys.executable, V, os.path.join(tmp, 'missing.log')],
                           capture_output=True, text=True)
        check('a missing file does not crash the verifier', r.returncode == 0, r.stdout + r.stderr)
    except QuickDone:
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print('NOTE finished at ' + time.strftime('%Y-%m-%d %H:%M:%S %z'))
    print()
    if FAILURES:
        print('FAILURES (%d): %s' % (len(FAILURES), ', '.join(FAILURES)))
        raise SystemExit(1)
    print('ALL PASS')


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print()
        print('INTERRUPTED')
        raise SystemExit(130)
    except Exception as e:
        print('FAIL suite crashed: %s: %s' % (type(e).__name__, e))
        if FAILURES:
            print('FAILURES: %s' % FAILURES)
