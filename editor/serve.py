#!/usr/bin/env python3
"""The registries' one-page web editor (editor/index.html + this server).

Serves the page and a small JSON API over the stdlib http.server. Every
save re-renders the touched file through scripts/lint_options.py's
canonical renderers and re-lints it in place — a hard finding restores
the previous bytes — so the files stay lint-clean however the page edits
them. Renames and new rows stay a hand wave; the page edits the fields
of the rows the registries already carry.

  python3 editor/serve.py [--host 127.0.0.1] [--port 8765]

Endpoints:
  GET  /          the page
  GET  /api/registry   the four tool registries + shared/options.json, parsed
  POST /api/save      {edits: [{tool, section, name, set: {k: v}, del: [k]}]}
  POST /api/lint      the lint_options --check + check_options reports

PV_EDITOR_ROOT points the API at another checkout (the page always
serves from this file's directory).
"""
import json
import os
import subprocess
import sys
import threading
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('PV_EDITOR_ROOT') or os.path.dirname(HERE)
for _p in (REPO, os.path.join(REPO, 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lint_options as lo  # noqa: E402
from scriptlib import TOOLS  # noqa: E402

SECTIONS = ('options', 'show', 'commands')
SECTION_FIELD = dict(lo.SECTION_FIELD)
SHARED_PATH = os.path.join(REPO, 'shared', 'options.json')
PAGE_PATH = os.path.join(HERE, 'index.html')
SAVE_LOCK = threading.Lock()


def tool_path(tool):
    return os.path.join(REPO, tool, 'lib', 'options.json')


def registry():
    files = {}
    for tool in TOOLS:
        path = tool_path(tool)
        with open(path, encoding='utf-8') as f:
            files[tool] = {'path': os.path.relpath(path, REPO), 'sections': json.load(f)}
    with open(SHARED_PATH, encoding='utf-8') as f:
        files['shared'] = {'path': 'shared/options.json', 'sections': json.load(f)}
    return {'tools': list(TOOLS), 'sections': list(SECTIONS), 'key_rank': list(lo.KEY_RANK),
            'section_field': SECTION_FIELD, 'files': files}


def apply_one(meta, edit, path):
    tool, sec, name = edit['tool'], edit['section'], edit['name']
    sets, dels = edit.get('set') or {}, edit.get('del') or []
    if 'name' in sets:
        return '%s: renaming %r is a wave — edit the name by hand' % (path, name)
    if tool == 'shared':
        blocks = meta.get(sec)
        if not isinstance(blocks, dict) or name not in blocks:
            return '%s: the canon block %s/%s is missing' % (path, sec, name)
        block = blocks[name]
        if isinstance(block, dict):
            for k in dels:
                block.pop(k, None)
            for k, v in sets.items():
                block[k] = v
            return None
        field = SECTION_FIELD.get(sec)
        if set(sets) == {field} and isinstance(sets[field], str) and not dels:
            blocks[name] = sets[field]
            return None
        return '%s: the canon block %s/%s is the bare %s string — edit that field alone' % (path, sec, name, field)
    rows = [r for r in (meta.get(sec) or []) if isinstance(r, dict) and r.get('name') == name]
    if len(rows) != 1:
        return '%s: %s: %d rows named %r' % (path, sec, len(rows), name)
    row = rows[0]
    for k in dels:
        row.pop(k, None)
    for k, v in sets.items():
        row[k] = v
    return None


def render(meta, path):
    if path == SHARED_PATH:
        return lo.render_canon(meta)
    return lo.render_registry(meta)


def apply_edits(edits):
    errors, warnings, saved = [], [], []
    groups = {}
    for e in edits:
        tool, sec, name = e.get('tool'), e.get('section'), e.get('name')
        if tool == 'shared':
            path = SHARED_PATH
        elif tool in TOOLS:
            path = tool_path(tool)
        else:
            errors.append('unknown tool %r' % (tool,))
            continue
        if sec not in SECTIONS or not name:
            errors.append('bad edit target %r' % (e,))
            continue
        groups.setdefault(path, []).append(e)
    with SAVE_LOCK:
        for path, group in groups.items():
            file_errors = []
            try:
                with open(path, encoding='utf-8') as f:
                    backup = f.read()
                meta = json.loads(backup)
            except (OSError, ValueError) as ex:
                errors.append('%s: %s' % (os.path.relpath(path, REPO), ex))
                continue
            for e in group:
                err = apply_one(meta, e, os.path.relpath(path, REPO))
                if err:
                    file_errors.append(err)
            if file_errors:
                errors.extend(file_errors)
                continue
            text = render(meta, path)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            if path != SHARED_PATH:
                nits, canon = lo.lint(path)
                hard = [n for n in nits if 'canonical' not in n]
                if hard:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(backup)
                    errors.extend(hard)
                    continue
                if canon is not None and canon != text:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(canon)
            saved.append(os.path.relpath(path, REPO))
        if saved:
            warnings.extend(lo.family_lint())
    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'saved': saved}


def run_lint():
    outs, ok = [], True
    for script, args in (('scripts/lint_options.py', ['--check']), ('scripts/check_options.py', [])):
        p = subprocess.run([sys.executable, os.path.join(REPO, script)] + args,
                           capture_output=True, text=True, cwd=REPO)
        ok = ok and p.returncode == 0
        outs.append('$ python3 %s %s\n%s%s' % (script, ' '.join(args), p.stdout, p.stderr))
    return {'ok': ok, 'text': '\n'.join(outs).strip() + '\n'}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            with open(PAGE_PATH, 'rb') as f:
                self._send(200, f.read(), 'text/html; charset=utf-8')
        elif self.path == '/api/registry':
            self._send(200, json.dumps(registry(), ensure_ascii=False).encode('utf-8'))
        else:
            self._send(404, b'{"error": "not found"}')

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n)
        if self.path == '/api/save':
            try:
                payload = json.loads(body or b'{}')
                out = apply_edits(payload.get('edits') or [])
            except Exception as ex:  # noqa: BLE001 — the page reports, the server survives
                out = {'ok': False, 'errors': ['%s: %s' % (type(ex).__name__, ex)],
                       'warnings': [], 'saved': []}
            self._send(200, json.dumps(out, ensure_ascii=False).encode('utf-8'))
        elif self.path == '/api/lint':
            self._send(200, json.dumps(run_lint(), ensure_ascii=False).encode('utf-8'))
        else:
            self._send(404, b'{"error": "not found"}')

    def log_message(self, fmt, *args):
        pass


def main():
    ap = ArgumentParser(description='the registries\' one-page web editor')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print('registry editor: http://%s:%d/ — repo %s' % (a.host, a.port, REPO))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
