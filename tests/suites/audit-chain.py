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

from harness import *   # the boot: the gate, the NOTE stamp — the shared check accumulator

V = os.path.join(REPO, 'scripts', 'audit_verify.py')
sys.path.insert(0, REPO)
from common.runtime.audit import AuditLog, entry_hash, GENESIS, audit_quote, audit_escape   # noqa: E402


def verify(*paths, rc=0, quiet=False, verbose=False, contain=None, absent=None):
    cmd = [sys.executable, V] + (['-v'] if verbose else []) + (['-q'] if quiet else []) + list(paths)
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    ok = r.returncode == rc
    if contain:
        ok = ok and all(c in out for c in contain)
    if absent:
        ok = ok and not any(a in out for a in absent)
    return ok, out


def main():
    tmp = tempfile.mkdtemp(prefix='audit_chain_')
    try:
        log = os.path.join(tmp, 'audit.log')

        # 1. two interleaved prefixes: every chain holds
        a = AuditLog(log, 'CACHE', instance='1')
        c = AuditLog(log, 'CLI', instance='1')
        a.event('START', 'version=test')
        c.event('CONNECT', 'target=127.0.0.1:1')
        a.event('COMMAND', "cmd='show version' result=ok")
        c.event('COMMAND', "cmd='quit' result=local")
        a.event('REQUESTS', 'clients=1 reads=3 writes=0')
        ok, out = verify(log, contain=['OK'])
        check('interleaved writers verify', ok, out)
        # the layout: the instance rides tag=, the hash its hash= token, the
        # detail's KV words ride bare after it (flat KV, no wrapper word)
        first = open(log).read().splitlines()[0].split(' ')
        check('layout: the instance word, the hash token, the bare detail words', len(first) >= 8 and first[1] == 'AUDIT'
              and first[2] == 'application=CACHE' and first[3] == 'tag=daemon' and first[4] == 'instance=1'
              and first[6].startswith('hash=') and len(first[6]) == 17
              and all(ch in '0123456789abcdef' for ch in first[6][5:])
              and first[7] == 'version=test', ' '.join(first[:8]))

        # 1b. the detail's empty-value rule: a KV word whose value is empty —
        # the bare `key=` token or the quoted empty (`key=''`) — is dropped
        # at the writer; a bare `=` stays (the write lines' prose)
        a2 = AuditLog(log, 'CACHE', instance='1')
        a2.event('COMMAND', "peer=1.2.3.4 reason= uptime=9s register 47415 = 5 x='' result=")
        first = open(log).read().splitlines()[-1]
        check('the detail drops an empty-valued word (bare or quoted empty), keeps the bare =',
              'peer=1.2.3.4 uptime=9s register 47415 = 5' in first
              and "x=''" not in first and 'reason=' not in first
              and not first.rstrip().endswith('result='), first)

        # 1c. the quoting rule: a value carrying a space rides one quoted
        # token (the builders' audit_quote) — the words stay parseable
        a2.event('COMMAND', "peer=%s cmd='show version' result=ok" % audit_quote('unix socket'))
        first = open(log).read().splitlines()[-1]
        check("a space value rides quoted (peer='unix socket')",
              "peer='unix socket' cmd='show version' result=ok" in first, first)

        # 1c2. the escape rule (logfmt-style): inside the quotes a `\`, ' or
        # " rides backslash-escaped; a bare value carries no escapes
        a2.event('COMMAND', "cmd='%s' result=ok" % audit_escape("set note it's \"fine\" \\ ok"))
        first = open(log).read().splitlines()[-1]
        check('an embedded quote/backslash rides escaped inside the quotes',
              "cmd='set note it\\'s \\\"fine\\\" \\\\ ok' result=ok" in first, first)
        check('a bare value carries no escapes', audit_quote("don't.sock") == "don't.sock",
              audit_quote("don't.sock"))

        # 1d. the reserved outer keys: a detail word spelling one never lands
        a2.event('COMMAND', "cmd='show version' type=forged tag=forged application=forged result=ok")
        first = open(log).read().splitlines()[-1]
        check('a detail word spelling a reserved outer key is dropped',
              'type=command' in first and 'tag=daemon' in first and 'application=CACHE' in first
              and 'forged' not in first, first)

        # 2. an edited line breaks the chain at that line
        lines = open(log).read().splitlines()
        lines[2] = lines[2].replace("'show version'", "'show secrets'")
        open(log, 'w').write('\n'.join(lines) + '\n')
        ok, out = verify(log, rc=1, contain=['line 3 [CACHE:daemon:1]: hash mismatch'])
        check('edited line detected (right line, right chain key)', ok, out)
        # 2b. the verbose walk: one row per entry — the verdict names the
        # break, the anchors and the chained links
        ok, out = verify(log, rc=1, verbose=True,
                         contain=['anchored', 'chained', 'broken',
                                  'line 3 [CACHE:daemon:1] ', 'hash mismatch'])
        check('the verbose walk names every entry and its verdict', ok, out)

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

        # 5. the pre-KV and pre-rename lines: the validator speaks the
        # current grammar only
        open(log, 'w').write(
            '2026-01-01T00:00:00Z AUDIT CACHE START version=old\n'
            '2026-01-01T00:00:01Z AUDIT CACHE COMMAND \'x\' -> ok\n'
            '2026-01-01T00:00:02Z AUDIT tools=CACHE tag=daemon type=command hash=0123456789abcdef\n')
        ok, out = verify(log, rc=1, contain=['3 broken', 'malformed'])
        check('pre-KV and pre-rename lines read malformed (the current grammar only)', ok, out)

        # 6. a restarted writer chains from its own trail (no false break)
        open(log, 'w').write('')
        a = AuditLog(log, 'CACHE', instance='1')
        a.event('START', 'v1')
        a.event('SHUTDOWN', 'clean')
        b = AuditLog(log, 'CACHE', instance='1')   # the "restart": a fresh writer, same key
        b.event('START', 'v2')
        ok, out = verify(log, contain=['OK'])
        check('restarted writer chains seamlessly', ok, out)

        # 6b. the instance word: two daemons of one tool share one file,
        # their chains verify independently (the triple key); an edit breaks
        # only its own group; an empty/None instance refuses
        open(log, 'w').write('')
        one = AuditLog(log, 'CACHE', instance='15020')
        two = AuditLog(log, 'CACHE', instance='15021')
        one.event('START', 'v1')
        two.event('START', 'v1')
        one.event('COMMAND', "cmd='a' result=ok")
        two.event('COMMAND', "cmd='b' result=ok")
        ok, out = verify(log, contain=['OK'])
        check('two instances of one tool verify independently', ok, out)
        lines = open(log).read().splitlines()
        lines[2] = lines[2].replace("'a'", "'X'")
        open(log, 'w').write('\n'.join(lines) + '\n')
        ok, out = verify(log, rc=1, contain=['CACHE:daemon:15020'])
        check('the break names the instance chain (the triple key)', ok, out)
        try:
            AuditLog(log, 'CACHE', instance=None)
            check('the instance word is required', False, 'no ValueError')
        except ValueError as e:
            check('the instance word is required', 'audit-instance must be 1-64' in str(e), str(e))

        if PROFILE == 'quick':
            raise QuickDone()   # quick: the core sections only
        # 7. rotation: the chain spans the backups (verified oldest-first)
        open(log, 'w').write('')
        a = AuditLog(log, 'CACHE', max_mb=0.000001, files=3, instance='1')   # ~every event rotates
        for i in range(6):
            a.event('COMMAND', 'batch-%d -> ok' % i)
        a.close()
        files = sorted(f for f in os.listdir(tmp) if f.startswith('audit.log'))
        ok, out = verify(log, rc=0, contain=['backup'])
        check('chain spans the rotated backups (files: %s)' % ','.join(files), ok, out)

        # 8. the real end-to-end trail: the fake's INV prefix over a control session
        flog = os.path.join(tmp, 'fake.log')
        fake = os.path.join(REPO, 'apps', 'inverter', 'bin', 'modbus-fake-inverter.py')
        ctl = os.path.join(REPO, 'apps', 'inverter', 'bin', 'modbus-fake-cli.py')
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
            fwd = AuditLog(log, 'CACHE', app='modbus-cache', forward='syslog', instance='1')
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
            fwd2 = AuditLog(log + '.x', 'CACHE', app='modbus-cache', forward='syslog:' + explicit_path, instance='1')
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
                AuditLog(log, 'CACHE', forward='syslog', instance='1')
                check('a socket-less syslog spelling refuses', False, 'no ValueError')
            except ValueError as e:
                check('a socket-less syslog spelling refuses', 'no local syslog socket' in str(e), str(e))
            try:
                AuditLog(log, 'CACHE', forward='udp', instance='1')
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
            SD-ELEMENT's application + chain hash and the hashed body — the
            envelope's extracted fields, exactly what a collector's
            chain-verifying search reads."""
            text = frame.decode('utf-8', 'replace')
            sd = text.split('[pvDash@1 ', 1)[1].split(']', 1)[0]
            app_tag = sd.split('application="')[1].split('"')[0]
            chain = sd.split('chain="')[1].split('"')[0]
            native = text.split('] ', 1)[1]
            parts = native.split(' ')
            if parts[2].startswith('application='):   # the KV line: the body carries tag= instance= type= + the detail words
                return parts[0], app_tag, chain, ' '.join(parts[3:6] + parts[7:])
            return parts[0], app_tag, chain, ' '.join(parts[3:4] + parts[5:])

        col = TcpCollector()
        try:
            tlog = os.path.join(tmp, 'tcp.log')
            w = AuditLog(tlog, 'CACHE', app='modbus-cache', forward='tcp://127.0.0.1:%d' % col.port, instance='1')
            w.event('COMMAND', "'show version' -> ok")
            deadline = time.time() + 10
            while not col.frames and time.time() < deadline:
                time.sleep(0.05)
            frame = col.frames[0].decode()
            stamp, prefix, chain, body = chain_of(col.frames[0])
            last = open(tlog).read().rstrip().splitlines()[-1]
            ok = (frame.startswith('<28>1 ') and frame.split(' ')[5] == 'command'
                  and '[pvDash@1 application="CACHE" role="daemon" instance="1" chain="' in frame
                  and frame.split('] ', 1)[1] == last
                  and chain == entry_hash(GENESIS, stamp, prefix, body))
            check('the tcp:// mirror: RFC6587 framing + the RFC5424 envelope + the chain in the SD', ok, frame[:160])

            # 9d. CEF: the additive wrapping, msg= verbatim, the severity table
            w2 = AuditLog(tlog + '.cef', 'CACHE', app='modbus-cache',
                          forward='tcp://127.0.0.1:%d' % col.port, forward_format='cef', instance='1')
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
                        and ' cs1Label=AuditChain cs1=' in cef \
                        and ' cs2Label=AuditApplication cs2=CACHE cs3Label=AuditInstance cs3=1 msg=' in cef \
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
            w3 = AuditLog(tlog + '.udp', 'CACHE', app='modbus-cache', forward='udp://127.0.0.1:%d' % uport, instance='1')
            w3.event('COMMAND', "'show version' -> ok")
            uframe = usock.recv(65536).decode()
            usock.close()
            check('the udp:// mirror: one datagram, the RFC5424 envelope',
                  uframe.startswith('<28>1 ') and '[pvDash@1 application="CACHE" role="daemon" instance="1" chain="' in uframe, uframe[:120])
        finally:
            col.down()

        # 9f. the lazy re-arm: a send failure notes once, the next event
        # re-opens, the success notes the dropped count
        err = io.StringIO()
        col2 = TcpCollector()
        try:
            rlog = os.path.join(tmp, 'rearm.log')
            wr = AuditLog(rlog, 'CACHE', app='modbus-cache', forward='tcp://127.0.0.1:%d' % col2.port, instance='1')
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
                wr2 = AuditLog('none', 'INV', app='fake-inverter', forward='tcp://127.0.0.1:%d' % col3.port, instance='1')
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
            wr3 = AuditLog('none', 'INV', app='fake-inverter', forward='tcp://127.0.0.1:%d' % col3.port, instance='1')
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
                wr4 = AuditLog('none', 'CACHE', app='modbus-cache', instance='1')
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
            ctl2 = os.path.join(REPO, 'apps', 'inverter', 'bin', 'modbus-fake-cli.py')
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
                    (b'application=INV tag=daemon instance=15988 type=start' in fr and b'version=' in fr)
                    and b'application=INV tag=daemon instance=15988 type=command' in b''.join(col3.frames)
                    for fr in col3.frames):
                time.sleep(0.1)
            events = []
            for fr in col3.frames:
                body_words = chain_of(fr)[3].split(' ')
                events.append(tuple(chain_of(fr)[1:3]) + (body_words[1], body_words[2]))
            check('the fake, remote-only: the INV trail arrives at the collector (the instance is its control port), no local state',
                  any(e[0] == 'INV' and e[3] == 'type=start' for e in events)
                  and any(e[0] == 'INV' and e[2] == 'instance=15988' and e[3] == 'type=command' for e in events)
                  and not os.path.exists(os.path.join(xdg, 'fake-inverter')))
        finally:
            col3.down()

        # 9i. the grammar gates: the remote/none spellings through the real bins
        fake = os.path.join(REPO, 'apps', 'inverter', 'bin', 'modbus-fake-inverter.py')
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
        r = subprocess.run([sys.executable, fake, '--static', '--dry-run', '--audit-instance', 'bad word'],
                           capture_output=True, text=True, timeout=15)
        check('a bad --audit-instance refuses (rc 1, no traceback)',
              r.returncode == 1 and 'audit-instance must be 1-64 characters' in r.stderr
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
