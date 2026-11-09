#!/usr/bin/env python3
"""Regression test for the audit trail's hash chain (docs/AUDIT.md F10):
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(REPO, 'scripts', 'audit_verify.py')
sys.path.insert(0, REPO)
from common.runtime.audit import AuditLog   # noqa: E402

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


def main():
    tmp = tempfile.mkdtemp(prefix='audit_chain_')
    try:
        log = os.path.join(tmp, 'audit.log')

        # 1. two interleaved prefixes: every chain holds
        a = AuditLog(log, 'CACHE')
        c = AuditLog(log, 'CLI')
        a.event('START', 'version=test')
        c.event('CONNECT', 'target=127.0.0.1:1')
        a.event('COMMAND', "'show version' -> ok")
        c.event('COMMAND', "'quit' -> local")
        a.event('REQUESTS', 'clients=1 reads=3 writes=0')
        ok, out = verify(log, contain=['OK'])
        check('interleaved writers verify', ok, out)
        # the layout: the hash sits right after the event name, no decoration
        first = open(log).read().splitlines()[0].split(' ')
        check('layout: hash inline after the event (no h=)', len(first) >= 5 and first[1] == 'AUDIT'
              and len(first[4]) == 12 and all(ch in '0123456789abcdef' for ch in first[4])
              and first[5] == 'version=test', ' '.join(first[:6]))

        # 2. an edited line breaks the chain at that line
        lines = open(log).read().splitlines()
        lines[2] = lines[2].replace("'show version'", "'show secrets'")
        open(log, 'w').write('\n'.join(lines) + '\n')
        ok, out = verify(log, rc=1, contain=['line 3 [CACHE]: hash mismatch'])
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

        # 5. legacy unsigned lines: reported, not failed
        open(log, 'w').write(
            '2026-01-01T00:00:00Z AUDIT CACHE START version=old\n'
            '2026-01-01T00:00:01Z AUDIT CACHE COMMAND \'x\' -> ok\n')
        ok, out = verify(log, contain=['2 entr', '2 unsigned'])
        check('legacy unsigned lines reported, not failed', ok, out)

        # 6. a restarted writer chains from its own trail (no false break)
        open(log, 'w').write('')
        a = AuditLog(log, 'CACHE')
        a.event('START', 'v1')
        a.event('SHUTDOWN', 'clean')
        b = AuditLog(log, 'CACHE')          # the "restart": a fresh instance, same prefix
        b.event('START', 'v2')
        ok, out = verify(log, contain=['OK'])
        check('restarted writer chains seamlessly', ok, out)

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
            import time
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
            ok, out = verify(log, contain=['OK'])
            check('the sink stays the authority (the mirrored trail verifies)', ok, out)

            ssock.close()
            os.unlink(ssock_path)
            err = io.StringIO()
            with redirect_stderr(err):
                fwd.event('COMMAND', "'set pv 2000' -> ok")
                fwd.event('COMMAND', "'quit' -> bye")
            ok, out = verify(log, contain=['OK'])
            check('a send failure stops the forwarding (one note, the trail keeps the chain)',
                  ok and fwd._syslog is None and 'syslog forwarding stopped' in err.getvalue(),
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
                check('a foreign forward spelling refuses', 'must be one of' in str(e), str(e))
        finally:
            audit_mod.SYSLOG_SOCKETS = saved_sockets

        fake = os.path.join(REPO, 'inverter', 'bin', 'modbus-fake-inverter.py')
        r = subprocess.run([sys.executable, fake, '--static', '--dry-run', '--audit-forward', 'bogus'],
                           capture_output=True, text=True, timeout=15)
        check('a bad --audit-forward answers with one clean ERROR line (rc 1, no traceback)',
              r.returncode == 1 and 'audit-forward must be one of syslog, none' in r.stderr
              and 'Traceback' not in r.stderr, r.stderr)

        # 10. exit code and stdin
        r = subprocess.run([sys.executable, V, os.path.join(tmp, 'missing.log')],
                           capture_output=True, text=True)
        check('a missing file does not crash the verifier', r.returncode == 0, r.stdout + r.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print('FAILURES (%d): %s' % (len(FAILURES), ', '.join(FAILURES)))
        raise SystemExit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
