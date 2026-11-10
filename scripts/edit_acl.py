#!/usr/bin/env python3
"""The standalone acl file's editor — two faces, one core:

  python3 scripts/edit_acl.py                  <file>   the dialog (curses) on a tty
  python3 scripts/edit_acl.py --type <t>       <file>   name the gate on a fresh file
  python3 scripts/edit_acl.py --line           <file>   the line mode (also when piped)

The file is the acl gate object: an optional terse-ASCII "desc", the
optional gate "type" and the ordered "rules" list — one {"type":
"allow"|"deny", matcher-key: matcher} object per rule. THE MATCHER KEY
IS THE GRAMMAR: "range" matches registers (any | START:COUNT | a,b,c),
"prefix" matches addresses (any | ip | ip/bits | comma-separated) — one
grammar per gate, a file mixing the two keys refuses. The gate "type"
names the schema — write-registers (range rules) or ip-prefix (prefix
rules) — and must agree with the rules' key when spelled. The editor
speaks the file's grammar (the edit command and the form field say
range or prefix); --type seeds a fresh file with the typed whole-space
deny and lands the type on the first save, migrates a
typeless file by adding the key (an edit, saved with s), and refuses a
mismatch with what the file already is. A path that does not exist
starts from the seeded whole-space deny (write-registers unless --type
says otherwise) and the file lands on the first save (0600); quitting
first leaves nothing behind.

Save is loader-gated: common/settings/config.py's _write_gate_object (the
schema is the daemon's, not the editor's) refuses the write, and the
landed file is always the canonical layout (scripts/lint_acl.py's
renderer — content byte-for-byte as edited). The lint's no-op / dead
rule / overlap findings warn but never block — the loader accepts them.

The dialog: the rule list is the menu (Enter opens the rule form, a
adds a rule seeded to the whole-space deny, d drops, +/- nudge the rule
down/up one slot, m jumps to a position, v flips allow/deny, g edits
the gate desc, t picks the fresh file's gate type (a saved file keeps
its type), l shows the lint findings, s saves, q quits — warned
while unsaved edits stand); the rule form walks
type/range|prefix/desc (Enter edits, Esc/c keeps the edits and returns, s
saves and returns). ^C
never leaves a traceback: it cancels the input line, backs out of the
form, or shows the quit notice on the list — q stays the quit path,
and the save's file write runs with SIGINT blocked. The
line mode speaks the same grammar one prompt per step. Exit 0 = done,
1 = error. Stdlib only."""
import json
import os
import signal
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, 'scripts'), os.path.join(ROOT, 'cache')):
    sys.path.insert(0, _p)

from lint_acl import fmt_gate, label, lint_desc, lint_gate, lint_matcher   # noqa: E402
from lib.config import _GATE_TYPES, _write_gate_object   # the loader's own gate validator  # noqa: E402

try:
    import readline
except ImportError:
    readline = None

from tui import INTR   # ^C: getch raises KeyboardInterrupt — get_key speaks it as
                       # this key and each surface gives it its meaning


def show_matcher(v):
    """The matcher as the list view shows it: the list comma-joined, the
    words bare."""
    if isinstance(v, list):
        return ', '.join(str(x) for x in v)
    return str(v)


def render_matcher(v):
    """The matcher as the edit line takes it back: the list comma-joined."""
    if isinstance(v, list):
        return ', '.join(str(x) for x in v)
    return str(v)


def parse_matcher_text(text, kind):
    """The edit-line grammar -> (matcher, error). The bare word, one
    item, or a comma list of them — the register kind's items
    START:COUNT (the canonical form the JSON list), the IP kind's items
    an IP or IP/prefix (the canonical form one comma-joined string)."""
    t = text.strip()
    if t.lower() == 'any':
        return t.lower(), None
    items = [x.strip() for x in t.split(',')]
    if len(items) > 1 or kind == 'prefix':
        if not all(items):
            return None, 'the matcher has an empty item in the comma list'
        if kind == 'prefix':
            return ','.join(items), None
        for x in items:
            try:
                int(x.split(':')[0]), int(x.split(':')[1])
            except (ValueError, IndexError):
                return None, '%r must be START:COUNT (the comma list is the list form)' % x
        return items, None
    try:
        int(t.split(':')[0]), int(t.split(':')[1])
    except (ValueError, IndexError):
        return None, 'the matcher is any | START:COUNT | a,b,c'
    return t, None


def split_matcher(rest):
    """'<matcher> [desc...]': a bare word or comma list never carries
    spaces — the first word is the matcher."""
    parts = rest.strip().split(None, 1)
    return (parts[0], parts[1].strip()) if len(parts) > 1 else (rest.strip(), '')


class Editor:
    """The file's working gate: the edits land in memory, save writes
    (loader-gated, canonical, stamp-guarded, parse-back guarded, the
    file write SIGINT-blocked so ^C cannot truncate it). The grammar key
    (range/prefix) is sniffed from the rules — one grammar per gate, a
    mixed file refuses to open. A path that does not exist starts from
    the seeded whole-space deny, typed write-registers unless --type
    says otherwise — the file lands (0600, the acl trust posture) on the
    first save; quitting first leaves nothing behind. --type on a
    typeless file adds the key (an edit, saved with s); a mismatch with
    what the file already is refuses."""

    def __init__(self, path, gate_type=None):
        self.path = path
        self.rel = label(path)
        self._type_arg = gate_type
        if gate_type is not None and gate_type not in _GATE_TYPES:
            raise ValueError('unknown gate type %r (write-registers | ip-prefix)' % gate_type)
        self.fresh = not os.path.exists(path)
        if self.fresh:
            self.kind = _GATE_TYPES[gate_type or 'write-registers']
            self.gate = {'type': gate_type or 'write-registers',
                         'rules': [{'type': 'deny', self.kind: 'any'}]}
        else:
            with open(path, encoding='utf-8') as f:
                self.text = f.read()
            self.gate = json.loads(self.text)
            if not isinstance(self.gate, dict):
                raise ValueError('%s: the root must be the gate object: {"desc": ..., '
                                 '"type": ..., "rules": [...]}' % self.rel)
            if 'acl' in self.gate:
                raise ValueError('%s: the root IS the gate — an "acl" key is the full-profile '
                                 'shape (move the gate object up, or edit the profile with '
                                 'scripts/edit_options.py)' % self.rel)
            declared = self.gate.get('type')
            if declared is not None and declared not in _GATE_TYPES:
                raise ValueError('%s: unknown gate type %r (write-registers | ip-prefix)'
                                 % (self.rel, declared))
            kind = None
            for i, rule in enumerate(self.rules()):
                has = [k for k in ('range', 'prefix') if k in rule] \
                    if isinstance(rule, dict) else []
                if len(has) > 1 or (kind and has and has[0] != kind):
                    raise ValueError('%s: the rules mix "range" and "prefix" — one grammar '
                                     'per gate (rule %d; range matches registers, prefix '
                                     'matches IPs)' % (self.rel, i + 1))
                if has:
                    kind = has[0]
            if declared is not None and kind and _GATE_TYPES[declared] != kind:
                raise ValueError('%s: the gate type %s matches by "%s" — the rules match '
                                 'by "%s"' % (self.rel, declared, _GATE_TYPES[declared], kind))
            if gate_type is not None and declared is not None and gate_type != declared:
                raise ValueError('%s: the file is the %s gate — --type %s refuses'
                                 % (self.rel, declared, gate_type))
            self.kind = _GATE_TYPES[declared] if declared else (kind or 'range')
        self.pristine = json.loads(json.dumps(self.gate))
        if not self.fresh and self._type_arg is not None \
                and self.gate.get('type') is None:
            self.gate['type'] = self._type_arg   # the migration edit — lands with the save
            self.kind = _GATE_TYPES[self._type_arg]
        self.rule = None
        self.stamp = self._stamp()

    def _stamp(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def rules(self):
        return self.gate.get('rules') or []

    def issues(self):
        return lint_gate(self.gate, 'acl file %s' % self.rel)

    def dirty(self):
        return self.fresh or self.gate != self.pristine

    def _validate_matcher(self, m, where):
        issues, _spans = lint_matcher(m, where, self.kind)
        return issues

    def set_gate_desc(self, text):
        if not text or text == '-':
            if 'desc' not in self.gate:
                return False, 'the gate carries no desc (nothing to clear)'
            del self.gate['desc']
            return True, 'ok the gate desc cleared'
        bad = lint_desc(text, 'the gate')
        if bad:
            return False, 'err %s' % bad[0]
        if text == self.gate.get('desc'):
            return False, 'the gate desc already %r' % text
        self.gate['desc'] = text
        return True, 'ok the gate desc set'

    def set_type(self, n, verb):
        rules = self.rules()
        if not 1 <= n <= len(rules):
            return False, 'err no rule %d (%d rule(s))' % (n, len(rules))
        if verb not in ('allow', 'deny'):
            return False, 'err the type must be allow or deny'
        if rules[n - 1].get('type') == verb:
            return False, 'rule %d is already %s' % (n, verb)
        rules[n - 1]['type'] = verb
        return True, 'ok rule %d is now %s' % (n, verb)

    def set_gate_type(self, gate_type):
        """The GATE type (the schema kind) — a fresh file's choice: the
        flip re-seeds the whole-space deny in the new grammar (the rules
        added before the flip were edits to the OLD grammar's seed, and
        a matcher does not convert across grammars). A saved file keeps
        its type — --type on open migrates a typeless one, it never
        re-types a typed one."""
        if gate_type not in _GATE_TYPES:
            return False, 'err the type must be write-registers or ip-prefix'
        if not self.fresh:
            return False, ('err the gate type is the saved file\'s — only a fresh file '
                           'flips it (--type on open migrates a typeless one)')
        if self.gate.get('type') == gate_type:
            return False, 'the gate is already the %s type' % gate_type
        key = _GATE_TYPES[gate_type]
        self.gate = {'type': gate_type, 'rules': [{'type': 'deny', key: 'any'}]}
        self.kind = key
        return True, ('ok the gate type %s — the rules re-seeded to the whole-space deny'
                      % gate_type)

    def set_matcher(self, n, text):
        rules = self.rules()
        if not 1 <= n <= len(rules):
            return False, 'err no rule %d (%d rule(s))' % (n, len(rules))
        m, err = parse_matcher_text(text, self.kind)
        if err:
            return False, 'err %s' % err
        bad = self._validate_matcher(m, 'rule %d' % n)
        if bad:
            return False, 'err %s' % bad[0]
        if rules[n - 1].get(self.kind) == m:
            return False, 'rule %d already carries that %s' % (n, self.kind)
        rules[n - 1][self.kind] = m
        return True, 'ok rule %d %s %s' % (n, self.kind, show_matcher(m))

    def set_desc(self, n, text):
        rules = self.rules()
        if not 1 <= n <= len(rules):
            return False, 'err no rule %d (%d rule(s))' % (n, len(rules))
        if not text or text == '-':
            if 'desc' not in rules[n - 1]:
                return False, 'rule %d carries no desc (nothing to clear)' % n
            del rules[n - 1]['desc']
            return True, 'ok rule %d desc cleared' % n
        bad = lint_desc(text, 'rule %d' % n)
        if bad:
            return False, 'err %s' % bad[0]
        if rules[n - 1].get('desc') == text:
            return False, 'rule %d desc already %r' % (n, text)
        rules[n - 1]['desc'] = text
        return True, 'ok rule %d desc set' % n

    def add(self, verb, matcher_text, desc=None, before=None):
        if verb not in ('allow', 'deny'):
            return False, 'err the type must be allow or deny (got %r)' % verb
        m, err = parse_matcher_text(matcher_text, self.kind)
        if err:
            return False, 'err %s' % err
        n = before if before is not None else len(self.rules()) + 1
        bad = self._validate_matcher(m, 'rule %d' % n)
        if bad:
            return False, 'err %s' % bad[0]
        rule = {'type': verb, self.kind: m}
        if desc:
            bad = lint_desc(desc, 'rule %d' % n)
            if bad:
                return False, 'err %s' % bad[0]
            rule['desc'] = desc
        rules = self.gate.setdefault('rules', [])
        rules.insert(n - 1, rule)
        return True, 'ok rule %d added (%s %s)' % (n, verb, show_matcher(m))

    def drop(self, n):
        rules = self.rules()
        if not 1 <= n <= len(rules):
            return False, 'err no rule %d (%d rule(s))' % (n, len(rules))
        if len(rules) == 1:
            return False, ('err the last rule cannot drop — a gate that gates nothing is a '
                           'config error (spell the whole-space deny as [{"type": "deny", '
                           '"%s": "any"}])' % self.kind)
        gone = rules.pop(n - 1)
        return True, 'ok rule %d dropped (%s %s)' % (n, gone.get('type'),
                                                     show_matcher(gone.get(self.kind)))

    def move(self, n, pos):
        rules = self.rules()
        if not 1 <= n <= len(rules):
            return False, 'err no rule %d (%d rule(s))' % (n, len(rules))
        if not 1 <= pos <= len(rules):
            return False, 'err the position must be 1..%d' % len(rules)
        if n == pos:
            return False, 'rule %d is already at %d' % (n, pos)
        rule = rules.pop(n - 1)
        rules.insert(pos - 1, rule)
        return True, 'ok rule %d moved to %d' % (n, pos)

    def save(self):
        issues = self.issues()
        try:
            _write_gate_object(self.gate, 'acl file %s' % self.rel,
                               allow=(self.gate.get('type'),) if self.gate.get('type')
                               else tuple(_GATE_TYPES))
        except SystemExit as e:
            return False, 'err the loader refuses the save: %s' % e
        new_text = fmt_gate(self.gate)
        try:
            json.loads(new_text)
        except ValueError as e:
            return False, 'err the edit does not re-parse: %s' % e
        if self._stamp() != self.stamp:
            return False, ('err %s changed underneath — quit, reopen and redo the edit'
                           % os.path.basename(self.path))
        mask = None
        if hasattr(signal, 'pthread_sigmask'):
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGINT])
        try:
            if self.fresh:   # the first landing: 0600 (the acl trust posture)
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(new_text)
            else:
                with open(self.path, 'w', encoding='utf-8') as f:
                    f.write(new_text)
        except OSError as e:
            return False, 'err cannot write %s: %s' % (self.rel, e)
        finally:
            if mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        self.stamp = self._stamp()
        self.text = new_text
        note = ' — new file (0600)' if self.fresh else ''
        if not note and issues:
            note = ' — lint: %d warning(s), lint shows them' % len(issues)
        self.fresh = False
        self.pristine = json.loads(json.dumps(self.gate))
        return True, 'ok saved (%d rule(s))%s' % (len(self.rules()), note)

    def reload(self):
        self.__init__(self.path, self._type_arg)
        return True, 'ok back to the disk state (%d rule(s))' % len(self.rules())


def report(ed):
    """The gate as the editor shows it: the desc header, one numbered
    line per rule (the show report's aligned shape, with numbers)."""
    desc = ed.gate.get('desc')
    print('# %s' % desc if desc else '# (no gate desc)')
    for i, r in enumerate(ed.rules()):
        print('  %2d  %-5s  %-34s  %s'
              % (i + 1, r.get('type', '?'), show_matcher(r.get(ed.kind)), r.get('desc') or ''))
    print()


def help_lines(kind):
    matcher = 'any|START:COUNT|a,b,c' if kind == 'range' else 'any|ip|ip/bits|a,b,c'
    return ('show — the gate, one rule per line',
            'add <allow|deny> <matcher> [desc...] — a rule appended',
            'insert <n> <allow|deny> <matcher> [desc...] — a rule before rule n',
            'type <n> <allow|deny> — flip a rule',
            '%s <n> <%s>' % (kind, matcher),
            'desc <n> <text...> (- clears)',
            'gatedesc <text...> (- clears)',
            'gatetype <write-registers|ip-prefix> — the fresh file\'s gate (a saved file keeps its type)',
            'move <n> <pos> — the chain reads top to bottom, the last match decides',
            'drop <n>',
            'lint — the issue report (the warnings never block the save)',
            'save — loader-gated write, the canonical layout',
            'reload — discard the edits, back to the disk state',
            'quit')


def line_mode(ed):
    print('# %s — %d rule(s), %d lint issue(s)%s (help lists the commands)'
          % (ed.path, len(ed.rules()), len(ed.issues()),
             ' — NEW, the file lands on save' if ed.fresh else ''))
    while True:
        try:
            line = input('acl > ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line or line.startswith('#'):
            continue
        low = line.lower()
        if low in ('quit', 'exit'):
            if ed.dirty():
                print('err unsaved edits — save, reload, or quit again to discard')
                try:
                    again = input('acl > ').strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 0
                if again not in ('quit', 'exit'):
                    continue
            return 0
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ''
        if cmd == 'help' or line == '?':
            for h in help_lines(ed.kind):
                print('  %s' % h)
        elif cmd == 'show':
            report(ed)
        elif cmd == 'lint':
            issues = ed.issues()
            for issue in issues:
                print('  - %s' % issue)
            print('lint: %d issue(s)' % len(issues) if issues else 'lint: clean')
        elif cmd in ('add', 'insert'):
            body, before = rest, None
            if cmd == 'insert':
                words = body.split(None, 1)
                try:
                    before = int(words[0])
                    body = words[1]
                except (ValueError, IndexError):
                    print('err insert <n> <allow|deny> <matcher> [desc...]')
                    continue
            words = body.split(None, 1)
            if len(words) < 2 or words[0].lower() not in ('allow', 'deny'):
                print('err %s %s<allow|deny> <matcher> [desc...]'
                      % (cmd, '<n> ' if cmd == 'insert' else ''))
                continue
            matcher, desc = split_matcher(words[1])
            ok, msg = ed.add(words[0].lower(), matcher, desc or None, before=before)
            print(msg)
            if ok:
                report(ed)
        elif cmd in ('type', 'desc', 'move', 'drop') or cmd == ed.kind:
            words = rest.split(None, 1)
            try:
                n = int(words[0])
            except (ValueError, IndexError):
                print('err %s <n> ...' % cmd)
                continue
            arg = words[1].strip() if len(words) > 1 else ''
            if cmd == 'type':
                ok, msg = ed.set_type(n, arg.lower())
            elif cmd == ed.kind:
                if not arg:
                    what = 'any|START:COUNT|a,b,c' if ed.kind == 'range' \
                        else 'any|ip|ip/bits|a,b,c'
                    print('err %s <n> <%s>' % (ed.kind, what))
                    continue
                ok, msg = ed.set_matcher(n, arg)
            elif cmd == 'desc':
                ok, msg = ed.set_desc(n, arg)
            elif cmd == 'move':
                try:
                    ok, msg = ed.move(n, int(arg))
                except ValueError:
                    ok, msg = False, 'err move <n> <pos>'
            else:
                ok, msg = ed.drop(n)
            print(msg)
            if ok and cmd in ('drop', 'move'):
                report(ed)
        elif cmd == 'gatedesc':
            ok, msg = ed.set_gate_desc(rest)
            print(msg)
        elif cmd == 'gatetype':
            ok, msg = ed.set_gate_type(rest.strip())
            print(msg)
        elif cmd == 'save':
            ok, msg = ed.save()
            print(msg)
        elif cmd == 'reload':
            ok, msg = ed.reload()
            print(msg)
        else:
            print('err unknown command %r (help lists them)' % cmd)


class Completer:
    """The line-mode TAB completion: the commands at the top level
    (the grammar's word for the matcher command), allow/deny after
    add/insert/type."""

    CMDS = ('show', 'add', 'insert', 'type', 'range', 'desc', 'gatedesc', 'gatetype',
            'move', 'drop', 'lint', 'save', 'reload', 'help', 'quit')

    def __init__(self, ed):
        self.ed = ed
        self.cmds = tuple(ed.kind if c == 'range' else c for c in self.CMDS)

    def complete(self, text, state):
        buf = readline.get_line_buffer()
        words = buf.split()
        if not words or (len(words) == 1 and not buf.endswith(' ')):
            pool = list(self.cmds)
        elif words[0] in ('add', 'insert', 'type') and len(words) <= 2 and not buf.endswith(' '):
            pool = ['allow', 'deny']
        else:
            return None
        matches = [w for w in pool if w.startswith(text.lower())]
        return matches[state] if state < len(matches) else None


def dialog(ed, screen):
    """The curses face: the rule list, the rule form, the input line."""
    import curses

    import tui
    get_key = tui.get_key
    fit = tui.fit
    put = lambda y, x, text, attr=0: tui.put(screen, y, x, text, attr)
    frame = lambda title: tui.frame(screen, title)
    status = lambda msg, dim=False: tui.status(screen, msg, dim)
    input_line = lambda prompt, initial='': tui.input_line(screen, prompt, initial)
    confirm = lambda word: tui.confirm(screen, word)

    def fields():
        """The form's field rows — the matcher row speaks the CURRENT
        grammar's key (the gate type can flip mid-session on a fresh
        file; the label and the routing must follow)."""
        return ('type', ed.kind, 'desc')

    def edited_mark(i):
        pr = ed.pristine.get('rules') or []
        rules = ed.rules()
        if i >= len(pr):
            return '*'
        return '*' if pr[i] != rules[i] else ' '

    def lint_msg():
        issues = ed.issues()
        if not issues:
            return 'lint: clean', True
        return 'lint: %d issue(s) — %s' % (len(issues), issues[0]), False

    def draw_list(cursor, top, msg):
        rules = ed.rules()
        lines = [(' %s' % (ed.gate.get('desc') or '(no gate desc)'), curses.A_DIM), (' ', 0)]
        rule_at = {}
        for i, r in enumerate(rules):
            rule_at[len(lines)] = i
            lines.append(('  %s%-3d %-5s %-34s %s'
                          % (edited_mark(i), i + 1, r.get('type', '?'),
                             show_matcher(r.get(ed.kind)), r.get('desc') or ''), 0))
        if not rules:
            lines.append(('  (no rules — a adds the first)', curses.A_DIM))
        screen.erase()
        note = ' — unsaved edits (s saves)' if ed.dirty() else ''
        lm, lm_dim = lint_msg()
        frame('pv-dash acl editor — %s — %d rule(s)%s (Enter edits, a adds, d drops, '
              '+/- move, m to position, v flips, g gate desc, t gate type%s, l lint, '
              's save, q quit)'
              % (ed.path, len(rules), note, '' if ed.fresh else ' (saved)'))
        height = curses.LINES - 4
        top = fit(top, cursor, lines, height)
        for i in range(height):
            idx = top + i
            if idx >= len(lines):
                break
            text, attr = lines[idx]
            if rule_at.get(idx) is not None:
                attr = curses.A_REVERSE if rule_at[idx] == cursor else 0
            put(2 + i, 0, text, attr)
        status(msg or lm, dim=not msg and lm_dim)
        screen.refresh()
        return top

    def draw_form(fcursor, ftop, msg):
        """The rule's three fields: a leading * marks the edited ones (off
        the pristine snapshot), 'new' marks a rule the session added."""
        screen.erase()
        i = ed.rule
        rule = ed.rules()[i]
        state = 'unsaved edits' if ed.dirty() else 'no changes'
        frame('rule %d — %s — Enter edits, Esc/c keeps and returns, s saves and returns'
              % (i + 1, state))
        pr = (ed.pristine.get('rules') or [])
        height = curses.LINES - 4
        ftop = fit(ftop, fcursor, fields(), height)
        for j, key in enumerate(fields()):
            mark = ''
            if i >= len(pr):
                mark = '   [new]'
            elif rule.get(key) != pr[i].get(key):
                mark = '   [edited]'
            shown = render_matcher(rule.get(ed.kind, '')) if key == ed.kind \
                else (rule.get('desc') or '-')
            if key == 'type':
                shown = rule.get('type', '-')
            put(2 + j, 0, '  *%-6s %s%s' % (key, shown, mark),
                curses.A_REVERSE if j == fcursor else 0)
        status(msg)
        screen.refresh()
        return ftop

    def gate_type_menu():
        """The GATE type pick (a fresh file only): write-registers |
        ip-prefix from the menu, the arrows walk, Enter takes (the rules
        re-seed to the new grammar's whole-space deny), Esc keeps."""
        options = (('write-registers', 'the registers gate — the rules match by range'),
                   ('ip-prefix', 'the IP gate — the rules match by prefix'))
        bcursor = 0 if ed.gate.get('type') == 'write-registers' else 1
        while True:
            screen.erase()
            frame('the gate type — Enter takes, Esc keeps the gate as it is')
            for i, (word, what) in enumerate(options):
                put(2 + i, 0, '  %-16s %s' % (word, what),
                    curses.A_REVERSE if i == bcursor else 0)
            status('')
            screen.refresh()
            k = get_key(screen)
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                bcursor = 1 - bcursor
            elif k in (10, 13, curses.KEY_ENTER):
                _ok, msg = ed.set_gate_type(options[bcursor][0])
                return msg
            elif k == INTR:
                return 'unchanged (^C)'
            elif k == 27:
                return 'unchanged (esc)'

    def verb_menu():
        """The type pick: allow|deny from the menu, the arrows walk, Enter
        takes, Esc keeps the field as it is."""
        n = ed.rule + 1
        what = 'registers' if ed.kind == 'range' else 'addresses'
        options = (('allow', 'the rule allows the %s' % what),
                   ('deny', 'the rule refuses the %s' % what))
        bcursor = 0 if ed.rules()[ed.rule].get('type') == 'allow' else 1
        while True:
            screen.erase()
            frame('type of rule %d — Enter takes, Esc keeps the field as it is' % n)
            for i, (word, what) in enumerate(options):
                put(2 + i, 0, '  %-5s %s' % (word, what), curses.A_REVERSE if i == bcursor else 0)
            status('')
            screen.refresh()
            k = get_key(screen)
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                bcursor = 1 - bcursor
            elif k in (10, 13, curses.KEY_ENTER):
                ok, msg = ed.set_type(n, options[bcursor][0])
                return msg
            elif k == INTR:
                return 'unchanged (^C)'
            elif k == 27:
                return 'unchanged (esc)'

    def edit_field(key):
        n = ed.rule + 1
        rule = ed.rules()[ed.rule]
        if key == ed.kind:
            initial = render_matcher(rule.get(key, ''))
            text = input_line('%s %d: ' % (key, n), initial)
            if text is None:
                return 'unchanged (esc)'
            _ok, msg = ed.set_matcher(n, text)
            return msg
        initial = rule.get('desc') or ''
        text = input_line('desc %d: ' % n, initial)
        if text is None:
            return 'unchanged (esc)'
        _ok, msg = ed.set_desc(n, text.strip())
        return msg

    cursor, top, msg = 0, 0, ('new file — the seeded %s gate (t flips the type), s saves'
                              % ed.gate.get('type') if ed.fresh else '')
    fcursor, ftop = 0, 0
    while True:
        if ed.rule is None:
            cursor = min(cursor, max(0, len(ed.rules()) - 1))
            top = draw_list(cursor, top, msg)
            msg = ''
            k = get_key(screen)
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                cursor = max(0, min(len(ed.rules()) - 1, cursor + (1 if k == curses.KEY_DOWN else -1)))
            elif k == curses.KEY_PPAGE:
                cursor = max(0, cursor - (curses.LINES - 6))
            elif k == curses.KEY_NPAGE:
                cursor = min(max(0, len(ed.rules()) - 1), cursor + (curses.LINES - 6))
            elif k in (10, 13, curses.KEY_ENTER):
                if ed.rules():
                    ed.rule = cursor
                    fcursor, ftop, msg = 0, 0, ''
                else:
                    msg = 'no rules — a adds the first'
            elif k in (ord('a'), ord('A')):
                ok, msg = ed.add('deny', 'any')
                if ok:
                    ed.rule = len(ed.rules()) - 1
                    fcursor, ftop = 1, 0
            elif k == ord('d') and not ed.rules():
                msg = 'no rules — a adds the first'
            elif k == ord('d'):
                if len(ed.rules()) == 1:
                    msg = 'err the last rule cannot drop (the gate would gate nothing)'
                elif confirm('drop rule %d' % (cursor + 1)):
                    ok, msg = ed.drop(cursor + 1)
                    cursor = min(cursor, max(0, len(ed.rules()) - 1))
                else:
                    msg = 'kept'
            elif k in (ord('+'), ord('-')):
                if not ed.rules():
                    msg = 'no rules — a adds the first'
                else:
                    pos = cursor + 2 if k == ord('+') else cursor
                    if not 1 <= pos <= len(ed.rules()):
                        msg = 'the rule is already %s' % ('last' if k == ord('+') else 'first')
                    else:
                        ok, msg = ed.move(cursor + 1, pos)
                        if ok:
                            cursor = pos - 1
            elif k in (ord('m'), ord('M')):
                if ed.rules():
                    pos = input_line('move rule %d to (1..%d): ' % (cursor + 1, len(ed.rules())),
                                     str(cursor + 1))
                    if pos is not None:
                        try:
                            ok, msg = ed.move(cursor + 1, int(pos))
                        except ValueError:
                            ok, msg = False, 'err a number, 1..%d' % len(ed.rules())
                        if ok:
                            cursor = pos - 1
                else:
                    msg = 'no rules'
            elif k in (ord('v'), ord('V')):
                if ed.rules():
                    rule = ed.rules()[cursor]
                    ok, msg = ed.set_type(cursor + 1, 'deny' if rule.get('type') == 'allow' else 'allow')
                else:
                    msg = 'no rules'
            elif k in (ord('g'), ord('G')):
                text = input_line('gate desc: ', ed.gate.get('desc') or '')
                if text is not None:
                    ok, msg = ed.set_gate_desc(text.strip())
            elif k in (ord('t'), ord('T')):
                msg = gate_type_menu()
            elif k in (ord('l'), ord('L')):
                issues = ed.issues()
                msg = 'lint: clean' if not issues else ' | '.join(issues[:2]) + \
                    (' | ...' if len(issues) > 2 else '')
            elif k in (ord('s'), ord('S')):
                if ed.dirty() and not confirm('save'):
                    msg = 'not saved'
                else:
                    ok, msg = ed.save()
            elif k == INTR:
                msg = '^C — q quits%s' % (' (s saves first)' if ed.dirty() else '')
            elif k in (ord('q'), ord('Q')):
                if ed.dirty():
                    if confirm('quit discarding'):
                        return
                    msg = 'kept the edits — s saves'
                else:
                    if confirm('quit'):
                        return
                    msg = 'stayed'
        else:
            ftop = draw_form(fcursor, ftop, msg)
            msg = ''
            k = get_key(screen)
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                fcursor = max(0, min(len(fields()) - 1, fcursor + (1 if k == curses.KEY_DOWN else -1)))
            elif k in (10, 13, curses.KEY_ENTER):
                key = fields()[fcursor]
                if key == 'type':
                    msg = verb_menu()
                else:
                    msg = edit_field(key)
            elif k == 27 or k in (ord('c'), ord('C')):
                ed.rule = None
                msg = 'back (the edits keep)'
            elif k == INTR:
                ed.rule = None
                msg = '^C — back (the edits keep)'
            elif k in (ord('s'), ord('S')):
                if ed.dirty() and not confirm('save'):
                    msg = 'not saved'
                else:
                    ok, msg = ed.save()
                ed.rule = None   # the form is done either way — the list speaks the outcome


def dialog_wrapper(ed):
    """The curses terminal lifecycle (restored on any exit); a ^C outside
    the key loops (mid-redraw, a save's tail) quits with the notice, not
    a traceback."""
    import curses

    def run(screen):
        curses.curs_set(0)
        screen.keypad(True)
        dialog(ed, screen)
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        print('^C — quit')


def main():
    raw = sys.argv[1:]
    forced_line = '--line' in raw
    gate_type, args = None, []
    i = 0
    while i < len(raw):
        a = raw[i]
        if a == '--type':
            i += 1
            gate_type = raw[i] if i < len(raw) else ''
        elif a.startswith('--type='):
            gate_type = a.split('=', 1)[1]
        elif a != '--line':
            args.append(a)
        i += 1
    if gate_type == '' or (args and args[0] in ('-h', '--help')) or len(args) > 1:
        print('usage: edit_acl.py [--type write-registers|ip-prefix] [--line] <acl-file>')
        return 1
    if gate_type is not None and gate_type not in _GATE_TYPES:
        print('edit_acl.py: unknown gate type %r (write-registers | ip-prefix)' % gate_type)
        return 1
    path = args[0] if args else None
    if path is None:
        if forced_line or not sys.stdin.isatty():
            print('usage: edit_acl.py [--type write-registers|ip-prefix] [--line] <acl-file>')
            return 1
        try:
            path = input('acl file: ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not path:
            return 1
    try:
        ed = Editor(path, gate_type)
    except (OSError, ValueError) as e:
        print('edit_acl.py: %s' % e)
        return 1
    if forced_line or not sys.stdin.isatty():
        if readline:
            readline.set_completer(Completer(ed).complete)
            readline.set_completer_delims(' \t')
            if 'libedit' in (readline.__doc__ or ''):
                readline.parse_and_bind('bind ^I rl_complete')
            else:
                readline.parse_and_bind('tab: complete')
        return line_mode(ed)
    dialog_wrapper(ed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
