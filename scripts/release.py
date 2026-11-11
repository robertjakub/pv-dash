#!/usr/bin/env python3
"""pv-suite release orchestrator.

One command per release: bump the version everywhere it lives, rename the
CHANGELOG's Unreleased section, (optionally) refresh flake.lock, verify
(the battery via scripts/battery.sh + the nix build), commit with the
expanded note, tag
(annotated, signed when a key exists — the bare X.Y.Z the suite has
always used) and push. The GitHub release is the tag-triggered workflow's
job (it gates on the suites + the nix build first — docs/SECURITY.md F19);
pass --release to cut it locally and skip that gate.

    python3 scripts/release.py 0.4.2               # the full flight
    python3 scripts/release.py 0.4.2 --dry-run     # everything but the landing
    python3 scripts/release.py 0.4.2 --tests quick # the two regtests only (via the runner, full depth)
    python3 scripts/release.py 0.4.2 --keep-lock   # keep the nixpkgs pin
    python3 scripts/release.py 0.4.2 --release     # cut the GH release locally

Re-releasing an already-bumped tree works (idempotent): the bump is a
no-op, the commit only happens if something changed, the tag/release
still go out. Stdlib only, like the rest of the family.
"""

import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / 'CHANGELOG.md'
ARCHIVE = ROOT / 'docs' / 'history' / 'CHANGELOG.md'
SUITES_QUICK = ['cache-regtest', 'scrape-regtest']   # the runner names — the `full` profile (battery.sh's QUICK_ALL) owns the ten

def run(cmd, **kw):
    print('  $ ' + ' '.join(str(c) for c in cmd))
    if kw.pop('dry', False):
        return subprocess.CompletedProcess(cmd, 0, '', '')
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit('release: %r failed:\n%s%s' % (' '.join(map(str, cmd)), r.stdout, r.stderr))
    return r


def sh(cmd, dry=False):
    r = run(cmd, dry=dry)
    return (r.stdout or '').strip()


def git(*args, dry=False):
    return sh(['git', *args], dry=dry)


def parse_version(text):
    if not re.fullmatch(r'\d+\.\d+\.\d+', text):
        sys.exit('release: the version must be X.Y.Z, got %r' % text)
    return text


def old_version():
    src = (ROOT / 'common' / 'runtime' / 'version.py').read_text()
    m = re.search(r"VERSION = '([^']+)'", src)
    if not m:
        sys.exit('release: cannot parse VERSION out of common/runtime/version.py')
    return m.group(1)


def version_sites(old):
    """Every file that mentions the old version, the two CHANGELOGs
    excluded (they keep the history; the archive legitimately carries the
    old version strings) — the same sweep a manual bump does."""
    r = run(['git', 'grep', '-l', '-F', old, '--', '.',
             ':!CHANGELOG.md', ':!docs/history/CHANGELOG.md'])
    return [pathlib.Path(line) for line in r.stdout.splitlines() if line.strip()]


def bump(old, new, dry):
    if old == new:
        print('release: the tree is already at %s (no bump)' % new)
        return
    rx = re.compile(r'(?<![\d.])' + re.escape(old) + r'(?![\d.])')
    for f in version_sites(old):
        p = ROOT / f
        p.write_text(rx.sub(new, p.read_text()))
        print('release: bumped %s' % f)
    if dry:
        return
    left = subprocess.run(['git', 'grep', '-l', '-F', old, '--', '.',
                           ':!CHANGELOG.md', ':!docs/history/CHANGELOG.md'],
                          cwd=ROOT, capture_output=True, text=True)
    if left.returncode not in (0, 1):  # 1 = no matches, the success case
        sys.exit('release: %r failed:\n%s%s' % ('git grep', left.stdout, left.stderr))
    left = left.stdout.strip()
    if left:
        sys.exit('release: the old version still appears in:\n' + left)


def changelog(new, dry):
    text = CHANGELOG.read_text()
    if re.search(r'^## %s\b' % re.escape(new), text, re.M):
        print('release: CHANGELOG already has the %s section' % new)
        return
    m = re.search(r'^## Unreleased\s*\n', text, re.M)
    if not m:
        sys.exit('release: CHANGELOG has neither %s nor an Unreleased section' % new)
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    text = text[:m.start()] + '## %s — %s\n' % (new, today) + text[m.end():]
    heads = list(re.finditer(r'^## ', text, re.M))
    if len(heads) > 1:
        # the split: the root file keeps the current release only — every
        # older release section moves to the top of the archive (the
        # archive is newest-first, the block slots in above its first
        # release heading)
        older = text[heads[1].start():].rstrip('\n') + '\n'
        if dry:
            n = len(re.findall(r'^## ', older, re.M))
            print('release: would move %d older release section(s) to %s'
                  % (n, ARCHIVE.relative_to(ROOT)))
        else:
            if not ARCHIVE.exists():
                sys.exit('release: %s is missing' % ARCHIVE.relative_to(ROOT))
            arc = ARCHIVE.read_text()
            a = re.search(r'^## ', arc, re.M)
            if not a:
                sys.exit('release: %s carries no release sections'
                         % ARCHIVE.relative_to(ROOT))
            ARCHIVE.write_text(arc[:a.start()] + older + '\n' + arc[a.start():])
            text = text[:heads[1].start()].rstrip('\n') + '\n'
            print('release: moved the older release section(s) to %s'
                  % ARCHIVE.relative_to(ROOT))
    CHANGELOG.write_text(text)
    print('release: CHANGELOG Unreleased -> %s (%s)' % (new, today))


def update_lock(dry, keep):
    if keep:
        print('release: keeping the flake.lock pin (--keep-lock)')
        return
    if not (ROOT / 'flake.lock').exists():
        return
    run(['nix', 'flake', 'update', '--flake', '.'], dry=dry)
    if not dry:
        rev = json.loads((ROOT / 'flake.lock').read_text())['nodes']['nixpkgs']['locked']['rev'][:12]
        print('release: nixpkgs pinned at %s' % rev)


def tests(which, dry, version):
    # the battery rides the runner: scripts/battery.sh owns the run dir,
    # the tally, the eta history and the failed-run backups, and its
    # rows stream live (a captured 27-minute silence serves nobody)
    if which == 'none':
        print('release: skipping the suites (--tests none)')
        return
    cmd = ['sh', 'scripts/battery.sh']   # the runner is 644 by the family's exec-bit rule — it rides sh
    if which == 'quick':
        cmd += ['--depth', 'full'] + SUITES_QUICK   # the recovery pair, still at the nightly depth
    else:
        cmd += ['full']                              # all ten at suite defaults
    cmd += ['--name', 'release %s' % version]
    print('release: the battery — ' + ' '.join(cmd))
    if dry:
        return
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit("release: the battery is NOT GREEN (rc=%d) — the run's status, logs and the "
                 "failed-run backup live in the newest ~/.local/state/pvbattery/<run-id>" % r.returncode)


def nix_build(dry, skip):
    if skip:
        print('release: skipping the nix build (--skip-nix)')
        return
    if not sh(['bash', '-c', 'command -v nix'], dry=dry):
        print('release: no nix on PATH, skipping the build')
        return
    print('release: nix build (all four packages)')
    run(['nix', 'build', '.#modbus-cache', '.#modbus-scraper',
         '.#modbus-fake-inverter', '.#dashboard', '--no-link'], dry=dry)


def notes_for(version):
    text = CHANGELOG.read_text()
    m = re.search(r'^## %s[^\n]*\n(.*?)(?=^## |\Z)' % re.escape(version), text, re.M | re.S)
    return m.group(1).strip() if m else None


def notes_pointer(version):
    """The release notes are the pointer now — the changes list lives in
    CHANGELOG.md; the notes name it at the tag."""
    remote = git('remote', 'get-url', 'origin')
    m = re.search(r'github\.com[:/]([^/]+)/(.+?)(?:\.git)?$', remote)
    if not m:
        return 'For the changes see the /CHANGELOG.md.'
    return ('For the changes see the [/CHANGELOG.md]'
            '(https://github.com/%s/%s/blob/%s/CHANGELOG.md).'
            % (m.group(1), m.group(2), version))


def main():
    ap = argparse.ArgumentParser(description='pv-suite release orchestrator')
    ap.add_argument('version', help='the version to release (X.Y.Z)')
    ap.add_argument('--dry-run', action='store_true', help='print the plan, touch nothing')
    ap.add_argument('--tests', choices=['quick', 'full', 'none'], default='full',
                    help='full = all ten suites (default), quick = the two regtests')
    ap.add_argument('--skip-nix', action='store_true', help='skip the nix build')
    ap.add_argument('--keep-lock', action='store_true', help='do not refresh flake.lock')
    ap.add_argument('--no-push', action='store_true', help='commit + tag locally, no push')
    ap.add_argument('--release', action='store_true',
                    help='cut the GitHub release locally (default: the tag-triggered '
                         'workflow cuts it after its CI gate — docs/SECURITY.md F19)')
    a = ap.parse_args()
    new = parse_version(a.version)
    old = old_version()
    dry = a.dry_run
    print('release: pv-suite %s -> %s%s' % (old, new, ' (dry-run)' if dry else ''))

    if git('status', '--porcelain'):
        sys.exit('release: the working tree is dirty — commit or stash first')
    if git('branch', '--show-current') != 'main':
        sys.exit('release: releases cut from main only')

    bump(old, new, dry)
    changelog(new, dry)
    update_lock(dry, a.keep_lock)
    tests(a.tests, dry, new)
    nix_build(dry, a.skip_nix)

    if git('status', '--porcelain', dry=dry):
        body = notes_for(new) or new
        git('add', '-A', dry=dry)
        git('commit', '-m',
            'release: pv-suite %s\n\n%s\n\n(the orchestrator: scripts/release.py — the version sites,\n'
            'the changelog rename, the verification, the tag and the push; the workflow cuts the release)'
            % (new, body), dry=dry)
    else:
        print('release: nothing to commit (the tree is already released)')

    if new in git('tag', '-l', dry=dry).split():
        print('release: the tag %s exists' % new)
    elif dry:
        print('release: tagged %s (annotated, signed when a key exists)' % new)
    else:
        signed = subprocess.run(['git', 'tag', '-s', new, '-m', 'pv-suite %s' % new],
                                cwd=ROOT, capture_output=True, text=True)
        if signed.returncode == 0:
            print('release: tagged %s (signed)' % new)
        else:
            git('tag', '-a', new, '-m', 'pv-suite %s' % new)
            why = next((l for l in signed.stderr.splitlines() if l.strip()), 'no reason printed')
            print('release: tagged %s (annotated — no signing key: %s)' % (new, why))

    if a.no_push:
        print('release: --no-push, done locally')
        return
    git('push', 'origin', 'main', dry=dry)
    git('push', 'origin', new, dry=dry)
    print('release: pushed main + the %s tag (the workflow gates the suites + the build, then cuts the release)' % new)

    if not a.release:
        print("release: no local cut — the GitHub release is the workflow's job; pass --release to cut it here")
        return
    print('release: --release cuts the GitHub release locally, before the CI gate reports')
    if not sh(['bash', '-c', 'command -v gh'], dry=dry):
        print('release: no gh on PATH, skipping the GitHub release (the workflow will cut it)')
        return
    body = notes_pointer(new)
    if not dry and new in sh(['gh', 'release', 'list', '--json', 'tagName', '--jq', '.[].tagName']).split():
        print('release: the GitHub release %s exists' % new)
        return
    run(['gh', 'release', 'create', new, '--title', 'pv-suite %s' % new,
         '--notes', body], dry=dry)
    print('release: GitHub release %s is out — fly me to the moon' % new)


if __name__ == '__main__':
    main()
