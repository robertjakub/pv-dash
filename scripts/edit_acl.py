#!/usr/bin/env python3
"""The standalone write-acl file's editor — two faces, one core:

  python3 scripts/edit_acl.py <file>           the dialog (curses) on a tty
  python3 scripts/edit_acl.py --line <file>    the line mode (also when piped)

The file is the write gate object (--write-registers file:<path>): an
optional terse-ASCII "desc" and the ordered "rules" list — one
{"type": "allow"|"deny", "range": matcher} object per rule. The chain is
a whitelist that reads top to bottom, the LAST matching rule decides,
and a register no rule decides refuses — so the editor's move/drop are
semantic edits, not cosmetics. The matcher grammar on the edit line:
any | START:COUNT | a,b,c (the list form). A path that does not exist
starts from the seeded whole-space deny and the file lands on the
first save (0600); quitting first leaves nothing behind.

Save is loader-gated: cache/lib/config.py's _write_gate_object (the
schema is the daemon's, not the editor's) refuses the write, and the
landed file is always the canonical layout (scripts/lint_acl.py's
renderer — content byte-for-byte as edited). The lint's no-op / dead
rule / overlap findings warn but never block — the loader accepts them.
The connect acl is the planned second kind (docs/TODO.md) — the editor
speaks the write gate until it lands.

The dialog: the rule list is the menu (Enter opens the rule form, a
adds a rule seeded to the whole-space deny, d drops, +/- nudge the rule
down/up one slot, m jumps to a position, v flips allow/deny, g edits
the gate desc, l shows the lint findings, s saves, q quits — warned
while unsaved edits stand); the rule form walks
type/range/desc (Enter edits, Esc/c keeps the edits and returns, s
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
from lib.config import _write_gate_object   # the loader's own gate validator  # noqa: E402

try:
    import readline
except ImportError:
    readline = None

# ^C: getch raises KeyboardInterrupt — get_key speaks it as this key and
# each surface gives it its meaning (the notice, the back, the cancel).
INTR = -2


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


def parse_matcher_text(text):
    """The edit-line grammar -> (matcher, error). The bare word, one
    START:COUNT, or a comma list of them."""
    t = text.strip()
    if t.lower() == 'any':
        return t.lower(), None
    items = [x.strip() for x in t.split(',')]
    if len(items) > 1:
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
    file write SIGINT-blocked so ^C cannot truncate it). A path
    that does not exist starts from the seeded whole-space deny — the
    file lands (0600, the acl trust posture) on the first save; quitting
    first leaves nothing behind."""

    def __init__(self, path):
        self.path = path
        self.rel = label(path)
        self.fresh = not os.path.exists(path)
        if self.fresh:
            self.gate = {'rules': [{'type': 'deny', 'range': 'any'}]}
        else:
            with open(path, encoding='utf-8') as f:
                self.text = f.read()
            self.gate = json.loads(self.text)
            if not isinstance(self.gate, dict):
                raise ValueError('%s: the root must be the gate object: {"desc": ..., '
                                 '"rules": [...]}' % self.rel)
            if 'acl' in self.gate:
                raise ValueError('%s: the root IS the gate — an "acl" key is the full-profile '
                                 'shape (move the gate object up, or edit the profile with '
                                 'scripts/edit_options.py)' % self.rel)
        self.pristine = json.loads(json.dumps(self.gate))
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
        issues, _spans = lint_matcher(m, where)
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

    def set_range(self, n, text):
        rules = self.rules()
        if not 1 <= n <= len(rules):
            return False, 'err no rule %d (%d rule(s))' % (n, len(rules))
        m, err = parse_matcher_text(text)
        if err:
            return False, 'err %s' % err
        bad = self._validate_matcher(m, 'rule %d' % n)
        if bad:
            return False, 'err %s' % bad[0]
        if rules[n - 1].get('range') == m:
            return False, 'rule %d already carries that range' % n
        rules[n - 1]['range'] = m
        return True, 'ok rule %d range %s' % (n, show_matcher(m))

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
        m, err = parse_matcher_text(matcher_text)
        if err:
            return False, 'err %s' % err
        n = before if before is not None else len(self.rules()) + 1
        bad = self._validate_matcher(m, 'rule %d' % n)
        if bad:
            return False, 'err %s' % bad[0]
        rule = {'type': verb, 'range': m}
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
                           '"range": "any"}])')
        gone = rules.pop(n - 1)
        return True, 'ok rule %d dropped (%s %s)' % (n, gone.get('type'), show_matcher(gone.get('range')))

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
            _write_gate_object(self.gate, 'acl file %s' % self.rel)
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
        self.__init__(self.path)
        return True, 'ok back to the disk state (%d rule(s))' % len(self.rules())


def report(ed):
    """The gate as the editor shows it: the desc header, one numbered
    line per rule (the show report's aligned shape, with numbers)."""
    desc = ed.gate.get('desc')
    print('# %s' % desc if desc else '# (no gate desc)')
    for i, r in enumerate(ed.rules()):
        print('  %2d  %-5s  %-34s  %s'
              % (i + 1, r.get('type', '?'), show_matcher(r.get('range')), r.get('desc') or ''))
    print()


HELP = ('show — the gate, one rule per line',
        'add <allow|deny> <matcher> [desc...] — a rule appended',
        'insert <n> <allow|deny> <matcher> [desc...] — a rule before rule n',
        'type <n> <allow|deny> — flip a rule',
        'range <n> <any|START:COUNT|a,b,c>',
        'desc <n> <text...> (- clears)',
        'gatedesc <text...> (- clears)',
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
            for h in HELP:
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
        elif cmd in ('type', 'range', 'desc', 'move', 'drop'):
            words = rest.split(None, 1)
            try:
                n = int(words[0])
            except (ValueError, IndexError):
                print('err %s <n> ...' % cmd)
                continue
            arg = words[1].strip() if len(words) > 1 else ''
            if cmd == 'type':
                ok, msg = ed.set_type(n, arg.lower())
            elif cmd == 'range':
                if not arg:
                    print('err range <n> <any|START:COUNT|a,b,c>')
                    continue
                ok, msg = ed.set_range(n, arg)
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
        elif cmd == 'save':
            ok, msg = ed.save()
            print(msg)
        elif cmd == 'reload':
            ok, msg = ed.reload()
            print(msg)
        else:
            print('err unknown command %r (help lists them)' % cmd)


class Completer:
    """The line-mode TAB completion: the commands at the top level,
    allow/deny after add/insert/type."""

    CMDS = ('show', 'add', 'insert', 'type', 'range', 'desc', 'gatedesc', 'move',
            'drop', 'lint', 'save', 'reload', 'help', 'quit')

    def __init__(self, ed):
        self.ed = ed

    def complete(self, text, state):
        buf = readline.get_line_buffer()
        words = buf.split()
        if not words or (len(words) == 1 and not buf.endswith(' ')):
            pool = list(self.CMDS)
        elif words[0] in ('add', 'insert', 'type') and len(words) <= 2 and not buf.endswith(' '):
            pool = ['allow', 'deny']
        else:
            return None
        matches = [w for w in pool if w.startswith(text.lower())]
        return matches[state] if state < len(matches) else None


def dialog(ed, screen):
    """The curses face: the rule list, the rule form, the input line."""
    import curses

    FIELDS = ('type', 'range', 'desc')

    def get_key(screen):
        """One key, with the ESC sequences decoded BY HAND — this box's
        curses delivers `\x1b[B` as three separate reads and keypad(True)
        never fires (ESC, '[', 'B'); a lone Esc waits ~30 ms and comes
        back as 27 (the cancel). A ^C — getch raises KeyboardInterrupt —
        comes back as INTR; the surfaces speak it, no traceback."""
        try:
            k = screen.getch()
            if k != 27:
                return k
            try:
                screen.nodelay(True)
                seq = []
                while len(seq) < 4:
                    c = get_key(screen)
                    if c == INTR:
                        return INTR
                    if c == -1:
                        curses.napms(30)
                        c = get_key(screen)
                        if c == -1:
                            break
                    seq.append(c)
                    if len(seq) >= 2 and seq[0] != ord('['):
                        break
            finally:
                screen.nodelay(False)
        except KeyboardInterrupt:
            return INTR
        table = {('[', 'A'): curses.KEY_UP, ('[', 'B'): curses.KEY_DOWN,
                 ('[', 'C'): curses.KEY_RIGHT, ('[', 'D'): curses.KEY_LEFT,
                 ('[', 'H'): curses.KEY_HOME, ('[', 'F'): curses.KEY_END}
        if len(seq) >= 2 and (chr(seq[0]), chr(seq[1]) if seq[1] < 256 else '') in table:
            return table[(chr(seq[0]), chr(seq[1]))]
        if len(seq) >= 3 and seq[0] == ord('['):
            return {ord('5'): curses.KEY_PPAGE, ord('6'): curses.KEY_NPAGE,
                    ord('3'): curses.KEY_DC, ord('1'): curses.KEY_HOME,
                    ord('4'): curses.KEY_END}.get(seq[1], seq[2])
        if not seq:
            return 27
        return seq[0]

    def put(y, x, text, attr=0):
        text = text[:curses.COLS - 1]
        screen.addstr(y, x, text, attr)

    def fit(top, cursor, lines, height):
        if cursor < top:
            top = cursor
        if cursor >= top + height:
            top = cursor - height + 1
        return max(0, min(top, max(0, len(lines) - height)))

    def frame(title):
        screen.attron(curses.A_REVERSE)
        put(0, 0, ' ' + title)
        screen.attroff(curses.A_REVERSE)

    def status(msg, dim=False):
        put(curses.LINES - 2, 0, (msg or '').ljust(curses.COLS - 1)[:curses.COLS - 1],
            curses.A_DIM if dim else 0)

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
                             show_matcher(r.get('range')), r.get('desc') or ''), 0))
        if not rules:
            lines.append(('  (no rules — a adds the first)', curses.A_DIM))
        screen.erase()
        note = ' — unsaved edits (s saves)' if ed.dirty() else ''
        lm, lm_dim = lint_msg()
        frame('pv-dash acl editor — %s — %d rule(s)%s (Enter edits, a adds, d drops, '
              '+/- move, m to position, v flips, g gate desc, l lint, s save, q quit)'
              % (ed.path, len(rules), note))
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
        ftop = fit(ftop, fcursor, FIELDS, height)
        for j, key in enumerate(FIELDS):
            mark = ''
            if i >= len(pr):
                mark = '   [new]'
            elif rule.get(key) != pr[i].get(key):
                mark = '   [edited]'
            shown = render_matcher(rule.get('range', '')) if key == 'range' else (rule.get('desc') or '-')
            if key == 'type':
                shown = rule.get('type', '-')
            put(2 + j, 0, '  *%-6s %s%s' % (key, shown, mark),
                curses.A_REVERSE if j == fcursor else 0)
        status(msg)
        screen.refresh()
        return ftop

    def input_line(prompt, initial=''):
        """The bottom input line: type, backspace, delete; the arrows move
        the (now visible) cursor, Home/End jump to the ends; Enter accepts,
        Esc returns None."""
        buf, pos = initial, len(initial)
        vis = False
        try:
            vis = bool(curses.curs_set(1))
        except curses.error:
            pass
        try:
            while True:
                put(curses.LINES - 1, 0, (' ' + prompt + buf), curses.A_BOLD)
                screen.clrtoeol()
                try:
                    screen.move(curses.LINES - 1, min(1 + len(prompt) + pos, curses.COLS - 1))
                except curses.error:
                    pass
                screen.refresh()
                k = get_key(screen)
                if k in (10, 13, curses.KEY_ENTER):
                    return buf
                if k in (27, INTR):
                    return None
                if k in (curses.KEY_BACKSPACE, 127, 8):
                    if pos:
                        buf = buf[:pos - 1] + buf[pos:]
                        pos -= 1
                elif k == curses.KEY_LEFT:
                    pos = max(0, pos - 1)
                elif k == curses.KEY_RIGHT:
                    pos = min(len(buf), pos + 1)
                elif k == curses.KEY_HOME:
                    pos = 0
                elif k == curses.KEY_END:
                    pos = len(buf)
                elif k == curses.KEY_DC:
                    buf = buf[:pos] + buf[pos + 1:]
                elif k >= 32:
                    buf = buf[:pos] + chr(k) + buf[pos:]
                    pos += 1
        finally:
            if vis:
                curses.curs_set(0)

    def confirm(word):
        """The y/n gate: ONE key — y acks, any other key (n, esc, ...)
        declines. No Enter."""
        put(curses.LINES - 1, 0, ' %s? [y/N] ' % word, curses.A_BOLD)
        screen.clrtoeol()
        screen.refresh()
        yes = get_key(screen) in (ord('y'), ord('Y'))
        put(curses.LINES - 1, 0, ' %s? [y/N] %s' % (word, 'y' if yes else 'n'), curses.A_BOLD)
        screen.clrtoeol()
        return yes

    def verb_menu():
        """The type pick: allow|deny from the menu, the arrows walk, Enter
        takes, Esc keeps the field as it is."""
        n = ed.rule + 1
        options = (('allow', 'the rule allows the range'),
                   ('deny', 'the rule refuses the range'))
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
        if key == 'range':
            initial = render_matcher(rule.get('range', ''))
            text = input_line('range %d: ' % n, initial)
            if text is None:
                return 'unchanged (esc)'
            _ok, msg = ed.set_range(n, text)
            return msg
        initial = rule.get('desc') or ''
        text = input_line('desc %d: ' % n, initial)
        if text is None:
            return 'unchanged (esc)'
        _ok, msg = ed.set_desc(n, text.strip())
        return msg

    cursor, top, msg = 0, 0, ('new file — the seeded deny-any gate, s saves' if ed.fresh else '')
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
                fcursor = max(0, min(len(FIELDS) - 1, fcursor + (1 if k == curses.KEY_DOWN else -1)))
            elif k in (10, 13, curses.KEY_ENTER):
                key = FIELDS[fcursor]
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
    args = [a for a in sys.argv[1:] if a != '--line']
    forced_line = '--line' in sys.argv[1:]
    if len(args) > 1 or (args and args[0] in ('-h', '--help')):
        print('usage: edit_acl.py [--line] <acl-file>')
        return 1
    path = args[0] if args else None
    if path is None:
        if forced_line or not sys.stdin.isatty():
            print('usage: edit_acl.py [--line] <acl-file>')
            return 1
        try:
            path = input('acl file: ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not path:
            return 1
    try:
        ed = Editor(path)
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
