#!/usr/bin/env python3
"""The family's terminal editor — one tool, two faces, word subcommands:

  python3 scripts/editor.py options [<project>]               the registry's dialog (curses) on a tty
  python3 scripts/editor.py options --line <project>          the registry's line mode (also when piped)
  python3 scripts/editor.py acl [--type <t>] [--line] <file>  the standalone acl file's editor

The options face edits a tool's lib/options.json registry. The
dialog: the knob index is the menu — arrows walk it, Enter opens the
row as a form; arrows walk the fields, Enter edits an editable one
(group, live, alias, setting-help, hint, the conv-typed default — the
static rung, a secret refused categorically — the marks: internal keeps a
command row off the cli (the wire answers), hidden hides the row
from the ?/TAB pools, restart marks the startup-only knob; value-help
opens its own key menu —
Enter edits a value's text, a adds a key, d deletes it), Esc leaves the
input line empty-handed, s saves the row (surgically: the touched row
re-renders in the house format, the rest of the file stays
byte-for-byte; parse-back guarded), c cancels back to the menu, l lints
the file (from the list or the form — the findings warn, never block),
q quits — warned away while a row holds unsaved edits. The view-only fields (flag,
env, conv, help — the one-knob-one-source surfaces
render them elsewhere) show with the rest; edited fields are marked.
A live RENAME is a console-surface edit (the wire keys the flat
registry name; the suites' pool/listing pins follow). An alias is an
edit: the cli translates it through the spellings map, so a second
spelling rides alone. The shared ref edits to a canon key of
shared/suite/options.json (resolved against the file, the node rows
included; the clear speaks inline again); a block-carried field shows
the block's text marked (canon), editing it lays the inline override,
and the value-help menu seeds the block's pairs first — the override
replaces the whole dict. The face rides the acl editor's golden-master
shapes: every file write runs with SIGINT blocked (a ^C cannot
truncate it), a ^C speaks through the surfaces (no traceback), and the
exit runs one lint pass — with the canonical re-render when the file
drifted.

The acl face edits the standalone acl gate object: an optional
terse-ASCII "desc", the optional gate "type" and the ordered "rules"
list — one {"type": "allow"|"deny", matcher-key: matcher} object per
rule. THE MATCHER KEY IS THE GRAMMAR: "range" matches registers (any |
START:COUNT | a,b,c), "prefix" matches addresses (any | ip | ip/bits |
comma-separated) — one grammar per gate, a file mixing the two keys
refuses. The gate "type" names the schema — write-registers (range
rules) or ip-prefix (prefix rules) — and must agree with the rules'
key when spelled. The editor speaks the file's grammar (the edit
command and the form field say range or prefix); --type seeds a fresh
file with the typed whole-space deny and lands the type on the first
save, migrates a typeless file by adding the key (an edit, saved with
s), and refuses a mismatch with what the file already is. A path that
does not exist starts from the seeded whole-space deny (write-registers
unless --type says otherwise) and the file lands on the first save
(0600); quitting first leaves nothing behind.

Save is loader-gated: common/settings/config.py's _write_gate_object (the
schema is the daemon's, not the editor's) refuses the write, and the
landed file is always the canonical layout (scripts/lint/acl.py's
renderer — content byte-for-byte as edited). The lint's no-op / dead
rule / overlap findings warn but never block — the loader accepts them.

The acl dialog: the rule list is the menu (Enter opens the rule form, a
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
import contextlib
import json
import os
import signal
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, 'scripts'), os.path.join(ROOT, 'apps', 'cache')):
    sys.path.insert(0, _p)

# `lib` is a contested name: the cache's own lib/ package (the gate loader
# below) and the scripts' common lib (scripts/lib) both answer to it, and
# the cache root precedes scripts/ on the path. The house's
# one-module-named-`lib`-at-a-time dance: the cache's bindings land first,
# the window re-binds `lib` to the scripts' package for the scripts-side
# imports, then the cache's module object binds back.

from lint.acl import fmt_gate, label, lint_desc, lint_gate, lint_matcher   # noqa: E402
from lib.config import _GATE_TYPES, _write_gate_object   # the loader's own gate validator  # noqa: E402

_lib_cache = sys.modules.pop('lib')                       # — the window opens
for _k in [k for k in sys.modules if k.startswith('lib.')]:
    sys.modules.pop(_k)
_cache_root = os.path.join(ROOT, 'apps', 'cache')   # acl's own inserts ride along — every copy out
sys.path[:] = [p for p in sys.path if p != _cache_root]
from lint.options import lint, proposals, render_registry   # noqa: E402
from lib import clean_path, row_span   # the scripts' common registry-editing helpers  # noqa: E402
sys.path.insert(0, _cache_root)
sys.modules['lib'] = _lib_cache                           # — the window closes

try:
    import readline
except ImportError:
    readline = None

from tui import INTR   # ^C: getch raises KeyboardInterrupt — get_key speaks it as
                       # this key and each surface gives it its meaning


# ---------------------------------------------------------------- the shared shapes

@contextlib.contextmanager
def blocked_sigint():
    """The file write's ^C guard: SIGINT blocked for the body — a ^C
    cannot truncate the file mid-write; it lands whole or not at all."""
    mask = None
    if hasattr(signal, 'pthread_sigmask'):
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGINT])
    try:
        yield
    finally:
        if mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def setup_readline(completer):
    """The line mode's TAB completion (the macOS libedit spelling too)."""
    if not readline:
        return
    readline.set_completer(completer.complete)
    readline.set_completer_delims(' \t')
    if 'libedit' in (readline.__doc__ or ''):
        readline.parse_and_bind('bind ^I rl_complete')   # macOS libedit
    else:
        readline.parse_and_bind('tab: complete')


def read_line(prompt):
    """One stripped console line; None on EOF/^C — the callers quit 0
    with no traceback (the line modes' and the prompts' shared read)."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def complete_word(pool, text, state):
    """The two completers' shared tail: the case-folded prefix matches,
    one per state."""
    matches = [w for w in pool if w.startswith(text.lower())]
    return matches[state] if state < len(matches) else None


def dialog_bindings(screen):
    """The seven tui bindings both dialogs open with (the dialogs stay
    per-face, the shapes are one)."""
    import tui
    return (tui.get_key, tui.fit,
            lambda y, x, text, attr=0: tui.put(screen, y, x, text, attr),
            lambda title: tui.frame(screen, title),
            lambda msg, dim=False: tui.status(screen, msg, dim),
            lambda prompt, initial='': tui.input_line(screen, prompt, initial),
            lambda word: tui.confirm(screen, word))


def pick_menu(screen, title, options, initial, apply):
    """The pick menu three edits share (a bool field's true/false, a
    rule's allow/deny, a fresh gate's type): the arrows walk, Enter
    takes — apply(word) speaks the outcome message — Esc/^C keeps the
    field as it is."""
    import curses

    import tui
    bcursor = initial
    while True:
        screen.erase()
        tui.frame(screen, title)
        width = max(len(w) for w, _ in options)
        for i, (word, what) in enumerate(options):
            tui.put(screen, 2 + i, 0, '  %-*s %s' % (width, word, what),
                    curses.A_REVERSE if i == bcursor else 0)
        tui.status(screen, '')
        screen.refresh()
        k = tui.get_key(screen)
        if k in (curses.KEY_UP, curses.KEY_DOWN):
            bcursor = (bcursor + (1 if k == curses.KEY_DOWN else -1)) % len(options)
        elif k in (10, 13, curses.KEY_ENTER):
            return apply(options[bcursor][0])
        elif k == INTR:
            return 'unchanged (^C)'
        elif k == 27:
            return 'unchanged (esc)'


def walk(k, cursor, count, page):
    """The four key loops' shared list walk: the arrows one row, the
    pages one screen, Home/End the ends — the new cursor, or None when
    k is not a walk key (the caller keeps its own state then)."""
    import curses

    if k in (curses.KEY_UP, curses.KEY_DOWN):
        return max(0, min(count - 1, cursor + (1 if k == curses.KEY_DOWN else -1)))
    if k == curses.KEY_PPAGE:
        return max(0, cursor - page)
    if k == curses.KEY_NPAGE:
        return min(max(0, count - 1), cursor + page)
    if k == curses.KEY_HOME:
        return 0
    if k == curses.KEY_END:
        return max(0, count - 1)
    return None


def dialog_wrapper(dialog, ed):
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


# ---------------------------------------------------------------- the options face

PROJECTS = ('cache', 'scraper', 'inverter', 'dashboard')
INLINE = ('name', 'flag', 'env', 'conv', 'shared', 'only', 'group', 'live', 'alias', 'negates')
EDITABLE = ('shared', 'group', 'live', 'alias', 'setting-help', 'hint', 'value-help', 'default', 'hidden', 'restart')
SHOW_EDITABLE = ('shared', 'group', 'live', 'alias', 'setting-help', 'hidden')   # the registry's `show` rows: the
                                                                                 # canon ref, the bucket, the live
                                                                                 # hierarchy, the alias, the word's
                                                                                 # description, the mark
CMD_EDITABLE = ('shared', 'group', 'help', 'hidden', 'internal')   # the `commands` rows: the canon ref,
                                                                   # the bucket, the description, the marks
BEFORE_HELP = ('setting-help', 'values', 'hint', 'value-help', 'default')


def render_row(row):
    """The row in the house format: the identity/grammar keys inline on the
    first line (canonical order), every remaining field its own line, the
    value-help one pair per line aligned at the brace, the row closing
    ` }` on the last line. New keys land at their canonical spots
    (group/live/negates after conv, the setting vocabulary before help)."""
    rank = {k: i for i, k in enumerate(INLINE)}
    rank.update({k: 100 + i for i, k in enumerate(BEFORE_HELP)})
    rank['internal'] = 105   # the marks after the setting vocabulary (internal
    rank['hidden'] = 106     # before hidden — the lint rank)
    rank['help'] = 999
    keys = sorted(row.keys(), key=lambda k: rank.get(k, 50))   # stable: the row's own order kept inside a rank

    first = [k for k in keys if k in INLINE]
    rest = [k for k in keys if k not in INLINE]
    if rest:
        lines = ['{ ' + ', '.join('"%s": %s' % (k, json.dumps(row[k], ensure_ascii=False)) for k in first) + ',']
    else:
        lines = ['{ ' + ', '.join('"%s": %s' % (k, json.dumps(row[k], ensure_ascii=False)) for k in first)]
    i = 0
    while i < len(rest):
        key = rest[i]
        last = i == len(rest) - 1
        v = row[key]
        if key == 'values' and i + 1 < len(rest) and rest[i + 1] == 'hint':
            # the house pairs the value words with their shape hint on one line
            pair = '"values": %s, "hint": %s' % (json.dumps(v, ensure_ascii=False),
                                                 json.dumps(row['hint'], ensure_ascii=False))
            if len('      ' + pair) <= 116:
                lines.append('      %s%s' % (pair, '' if last else ','))
                i += 2
                continue
        i += 1
        if key == 'value-help' and v:
            head = '      "value-help": { '
            pad = ' ' * len(head)
            pairs = ['"%s": %s' % (pk, json.dumps(pv, ensure_ascii=False)) for pk, pv in v.items()]
            if len(pairs) == 1 and len(head + pairs[0] + ' }' + ('' if last else ',')) <= 116:
                lines.append(head + pairs[0] + ' }' + ('' if last else ','))
            else:
                for j, pair in enumerate(pairs):
                    last_pair = j == len(pairs) - 1
                    lines.append((head if not j else pad) + pair + (' }' if last_pair else ','))
                if not last:
                    lines[-1] += ','
        else:
            lines.append('      "%s": %s%s' % (key, json.dumps(v, ensure_ascii=False), '' if last else ','))
    if rest:
        lines[-1] += ' }'
    return '\n'.join(lines)


def row_kind(row):
    """The row's kind: a hierarchy node (a live-path prefix, help-only) or
    a knob (the flag/env twin exists) or control-only (wire-settable only,
    no flag) — `*` marks the cli-visible ones (the live name rides the
    bucket column beside; a hidden row rides bare — the wire answers it,
    the ?/TAB pools never list it); a node can only be `node*` by
    hand-editing — the editor refuses live on a node, a live node is a
    registry bug."""
    kind = 'node' if row.get('node') else ('knob' if row.get('flag') else 'control-only')
    return kind + ('*' if row.get('live') and not row.get('hidden') else '')


ORDERS = ('name', 'kind', 'live', 'group', 'registry')
VIEWS = ('all', 'live', 'other')   # the view gate: everything / the '*' rows / the rest
KINDS = ('knob', 'control-only', 'node', 'show', 'cmd')   # the kind gate: the row_kind families
KCYCLE = ('all',) + KINDS   # the dialog's kind cycle (all → knob → ... → cmd → all)


def view_rows(rows, filt='', order='name', kind=row_kind, vmode='all', kmode='all'):
    """The rows as listed: gated by the view first — `live` keeps the '*'
    rows (the cli-visible ones: the live-settable knobs and the listing
    show/cmd words), `other` the rest (the startup-only, the hidden, the
    bare nodes) — then by the kind (the row_kind family, star or not:
    knob/control-only/node/show/cmd) — then filtered (the substring over
    the name, the live path, the kind, the bucket and the descriptions)
    and ordered: by name (the default), kind/live/group, or the registry
    order."""
    if vmode == 'live':
        rows = [r for r in rows if kind(r).endswith('*')]
    elif vmode == 'other':
        rows = [r for r in rows if not kind(r).endswith('*')]
    if kmode != 'all':
        rows = [r for r in rows if kind(r).rstrip('*') == kmode]
    if filt:
        q = filt.lower()
        rows = [r for r in rows
                if q in r['name'].lower()
                or q in (r.get('live') or '').lower()
                or q in (r.get('alias') or '').lower()
                or q in (r.get('shared') or '').lower()
                or q in kind(r)
                or (r.get('live') and 'live' in q)   # `live` = the live-settable ones
                or (r.get('hidden') and 'hidden' in q)   # `hidden` = the wire-only ones
                or q in (r.get('group') or '').lower()
                or q in (r.get('setting-help') or r.get('help') or '').lower()]
    if order != 'registry':
        key = {'name': lambda r: r['name'],
               'kind': lambda r: (kind(r), r['name']),
               'live': lambda r: (r.get('live') or '', r['name']),
               'group': lambda r: (r.get('group') or '', r['name'])}[order]
        rows = sorted(rows, key=key)
    return rows


def bucket_of(editor, r):
    """The list view's bucket column: the live path when the row has one,
    else the group — the section never fills in (the cli listings group by
    the group field alone) — else the family mark (cmd/show), '-' on a
    bare option row."""
    if r.get('live'):
        return r['live']
    if r.get('group'):
        return r['group']
    if editor.is_cmd(r):
        return 'cmd'
    if editor.is_show(r):
        return 'show'
    return '-'


def row_keys(row, editable=EDITABLE):
    """The row's field names in the canonical display order — the editable
    set always present (an absent one renders '-' and edits into being)."""
    keys = list(row.keys()) + [k for k in editable if k not in row]
    rank = {k: i for i, k in enumerate(INLINE)}
    rank.update({k: 100 + i for i, k in enumerate(BEFORE_HELP)})
    rank['internal'] = 105   # the marks after the setting vocabulary (every kind;
    rank['hidden'] = 106     # internal before hidden — the lint rank)
    rank['restart'] = 107
    rank['help'] = 999
    return sorted(keys, key=lambda k: rank.get(k, 50))


def shown(row, key):
    """The printable form of one field's value."""
    v = row.get(key)
    if v is None:
        return '-'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, dict):
        return ', '.join(v) if v else '-'
    if isinstance(v, list):
        return ', '.join(v)
    return v


class OptionsEditor:
    def __init__(self, project):
        self.project = project
        self.path = os.path.join(ROOT, project, 'lib', 'options.json')
        self.stamp = self._stamp()
        with open(self.path, encoding='utf-8') as f:
            self.text = f.read()
        meta = json.loads(self.text)
        self.rows = meta['options']
        self.show = meta.get('show') or []           # the `show` rows (the registry's `show` section)
        self.show_names = {r['name'] for r in self.show}
        self.cmds = meta.get('commands') or []       # the `commands` rows (the wire's verb list)
        self.cmd_names = {r['name'] for r in self.cmds}
        self.canon = self._load_canon()
        self.row = None
        self.pristine = None

    def _load_canon(self):
        """shared/suite/options.json — the `shared` field's ref target; an
        absent or broken file reads as no canon (the editor never crashes on
        the pre-wave tree, a ref just fails to resolve)."""
        try:
            with open(os.path.join(ROOT, 'shared', 'suite', 'options.json'), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def canon_block(self, row):
        """The row's canon block (the section's flat text — or the dict
        block carrying the row's fields — on the show/command faces), or
        None when the row carries no ref."""
        section = 'show' if self.is_show(row) else ('commands' if self.is_cmd(row) else 'options')
        return (self.canon.get(section) or {}).get(row.get('shared') or '')

    def effective(self, row, key):
        """(value, from_canon): the row's inline field, else — when the row
        refs a block carrying it — the block's answer (the fold's, shown
        marked `canon`). The show/commands blocks speak the description
        field flat or as a dict block carrying the row's fields."""
        if key in row:
            return row[key], False
        block = self.canon_block(row)
        if block is None:
            return None, False
        section = 'show' if self.is_show(row) else ('commands' if self.is_cmd(row) else 'options')
        if isinstance(block, dict):
            if key in block:
                return block[key], True
            return None, False
        if section == 'options':
            return None, False
        return (block, True) if key == ('setting-help' if section == 'show' else 'help') \
            else (None, False)

    def _stamp(self):
        st = os.stat(self.path)
        return (st.st_mtime_ns, st.st_size)

    def add_node(self, name, desc):
        """A brand-new hierarchy node: the minimal row (the name, the node
        mark, the description) appended to `options`, the file
        rewritten in the canonical layout. (ok, message)."""
        if any(r['name'] == name for r in self.rows + self.show + self.cmds):
            return False, 'err the name %r is taken' % name
        row = {'name': name, 'node': True, 'setting-help': desc}
        meta = json.loads(self.text)
        meta.setdefault('options', []).append(row)
        new_text = render_registry(meta)
        if self._stamp() != self.stamp:
            return False, 'err %s changed underneath — quit, reopen, retry' % os.path.basename(self.path)
        with blocked_sigint(), open(self.path, 'w', encoding='utf-8') as f:
            f.write(new_text)
        self.stamp = self._stamp()
        self.__init__(self.project)   # the fresh parse: the rows, the show-names, the marks
        return True, 'ok the node %s added' % name

    def delete_node(self):
        """The open hierarchy-node row removed from the registry (the file
        rewritten in the canonical layout; only nodes delete — the caller
        gates). (ok, message)."""
        name = self.row['name']
        if not self.row.get('node'):
            return False, 'err %s is not a hierarchy node — only nodes delete' % name
        meta = json.loads(self.text)
        kept = [r for r in meta['options'] if not (r.get('node') and r['name'] == name)]
        if len(kept) == len(meta['options']):
            return False, 'err the node %s is not in the registry (%s)' % (name, os.path.basename(self.path))
        meta['options'] = kept
        new_text = render_registry(meta)
        if self._stamp() != self.stamp:
            return False, 'err %s changed underneath — quit, reopen, retry' % os.path.basename(self.path)
        with blocked_sigint(), open(self.path, 'w', encoding='utf-8') as f:
            f.write(new_text)
        self.stamp = self._stamp()
        self.__init__(self.project)   # the fresh parse: the row is gone
        return True, 'ok the node %s deleted' % name

    def is_show(self, r):
        """True when the row belongs to the registry's `show` section."""
        return r['name'] in self.show_names

    def is_cmd(self, r):
        """True when the row belongs to the registry's `commands` section."""
        return r['name'] in self.cmd_names

    def kind(self, r):
        """The listing's kind mark: show for the `show` rows — starred
        when the word lists (hidden false/absent), bare when the row
        hides from the ?/TAB pools — row_kind's node/knob*/control-only
        for the option rows (the same hidden rule: a hidden knob is
        wire-only, the pools never list it)."""
        if self.is_cmd(r):
            return 'cmd' + ('*' if not r.get('hidden') else '')
        if self.is_show(r):
            return 'show' + ('*' if not r.get('hidden') else '')
        return row_kind(r)

    def by_name(self):
        by = {r['name']: r for r in self.rows}
        by.update({r['name']: r for r in self.show})
        by.update({r['name']: r for r in self.cmds})
        return by

    def open(self, name):
        """Open a row for editing: the in-memory copy plus its pristine
        baseline (cancel restores it). The `show` and `commands` rows open
        too."""
        for i, r in enumerate(self.rows + self.show + self.cmds):
            if r['name'] == name:
                self.pristine = json.loads(json.dumps(r))
                self.row = r
                return
        self.row = None

    def editable_set(self, row):
        """The fields one may edit: the `show` rows carry the live
        hierarchy, the bucket, the word's description and the hidden mark;
        the `commands` rows the bucket, the description and the mark; the
        option rows the vocabulary plus the marks (hidden — the wire-only
        toggle, every kind but a node; restart — the startup-only knob)."""
        if self.is_cmd(row):
            return CMD_EDITABLE
        return SHOW_EDITABLE if self.is_show(row) else EDITABLE

    def dirty(self):
        """The open row holds unwritten changes."""
        return self.row is not None and self.row != self.pristine

    def write_row(self):
        """Splice the edited row into the text; (ok, message)."""
        name = self.row['name']
        if not self.dirty():
            return False, 'nothing to write (%s is as it reads on disk)' % name
        changed = sorted(k for k in set(self.row) | set(self.pristine)
                         if self.row.get(k) != self.pristine.get(k))
        span = row_span(self.text, name)
        if span is None:
            return False, 'err the row vanished (%s)' % name
        start, end = span
        raw = self.text[:start] + render_row(self.row) + self.text[end:]
        try:
            meta = json.loads(raw)   # never write what we cannot parse back
        except ValueError as e:
            return False, 'err the edit does not re-parse: %s' % e
        new_text = render_registry(meta)
        if self._stamp() != self.stamp:
            return False, ('err %s changed underneath (another editor wrote it) — '
                           'quit, reopen and redo the edit' % os.path.basename(self.path))
        with blocked_sigint(), open(self.path, 'w', encoding='utf-8') as f:
            f.write(new_text)
        self.stamp = self._stamp()
        self.text = new_text
        self.pristine = json.loads(json.dumps(self.row))
        return True, 'ok %s written (%s)' % (name, ', '.join(changed))

    def cancel(self):
        """Discard the row's edits back to its pristine form."""
        for i, r in enumerate(self.rows):
            if r['name'] == self.pristine['name']:
                self.rows[i] = self.pristine
                break
        self.row = None

    def set_shared(self, value):
        """The canon ref: a key of shared/suite/options.json in the row's own
        section; the clear deletes the ref — the row speaks inline again.
        The tool's own wiring (conv, live, default, ...) and any field the
        block does not speak stay inline; on success the status names the
        inline twins the block byte-carries (the drop candidates)."""
        name = self.row['name']
        text = (value or '').strip()
        if not text:
            if 'shared' not in self.row:
                return False, 'err %s carries no shared ref (nothing to clear)' % name
            del self.row['shared']
            return True, 'ok %s.shared cleared (the row speaks inline again)' % name
        section = 'show' if self.is_show(self.row) else ('commands' if self.is_cmd(self.row) else 'options')
        block = (self.canon.get(section) or {}).get(text)
        if block is None:
            keys = ', '.join(sorted((self.canon.get(section) or {}))) or 'none yet'
            return False, 'err no canon key %r in shared/suite/options.json (%s: %s)' % (text, section, keys)
        if isinstance(block, dict):
            bad = sorted({'name', 'only', 'shared'} & set(block))
            if bad:
                return False, ('err the canon block %r carries %s — never a block field '
                               '(the name is the block\'s key, only/shared are the row\'s '
                               'placement marks)' % (text, ', '.join(map(repr, bad))))
        self.row['shared'] = text
        twins = []
        if isinstance(block, dict):
            twins = sorted(k for k, v in block.items()
                           if k in self.row and json.dumps(self.row[k], ensure_ascii=False, sort_keys=True)
                           == json.dumps(v, ensure_ascii=False, sort_keys=True))
        elif isinstance(block, str):
            field = 'setting-help' if section == 'show' else 'help'
            twins = [field] if field in self.row else []
        note = ' (the block also speaks: %s — clear them to fold)' % ', '.join(twins) if twins else ''
        return True, 'ok %s.shared = %s%s' % (name, text, note)

    def set_field(self, key, value):
        """One field edit with the gate rules; (ok, message)."""
        name = self.row['name']
        if key == 'name':
            return False, 'err the name is the row\'s identity — it does not edit'
        if key == 'shared':
            return self.set_shared(value)
        if key in ('hidden', 'restart', 'internal'):   # the bool marks — hidden on the knobs, the
            # show rows and the command rows too; internal: command rows
            # only; restart: option rows only. The editor writes true/false
            # only (the loaders also read the wire's on/off spelling).
            if key == 'restart' and self.is_show(self.row):   # show rows and the command rows too;
                return False, 'err %s is a show row — only %s edit' % (name, ' | '.join(SHOW_EDITABLE))   # restart: option rows only
            if key == 'restart' and self.is_cmd(self.row):
                return False, 'err %s is a command row — only %s edit' % (name, ' | '.join(CMD_EDITABLE))
            if key == 'internal' and not self.is_cmd(self.row):
                return False, 'err internal is a command-row mark — %s is not one' % name
            if self.row.get('node'):
                return False, 'err %s is a hierarchy node — only its setting-help and group edit' % name
            v = (value or 'false').lower()   # the empty = the clear = false
            if v not in ('true', 'false'):
                return False, 'err %s must be true or false' % key
            if v == 'true':
                self.row[key] = True
                return True, 'ok %s.%s true%s' % (name, key, '' if key == 'restart' else ' (the pools drop it, the wire answers)')
            if key not in self.row:
                return False, '%s: %s already false' % (name, key)
            del self.row[key]   # false = the field's absence
            return True, 'ok %s.%s false (the mark cleared)' % (name, key)
        if self.is_show(self.row):
            if key not in SHOW_EDITABLE:
                return False, 'err %s is a show row — only %s edit' % (name, ' | '.join(SHOW_EDITABLE))
        if self.is_cmd(self.row):
            if key not in CMD_EDITABLE:
                return False, 'err %s is a command row — only %s edit' % (name, ' | '.join(CMD_EDITABLE))
        if self.row.get('node') and key not in ('setting-help', 'group', 'shared'):
            return False, 'err %s is a hierarchy node — only its setting-help and group edit' % name
        if key == 'default':
            # the static rung (the resolver's last ladder layer): conv-typed
            # JSON — int/float/bool/str, never a spelling — the empty input
            # clears (the None ladder-end); a secret refuses one outright
            # (its default is None, categorically); min/max stay off the
            # check (the static rung may sit below the live floor — the
            # dump-interval 0 against the row's live min 1)
            if self.row.get('secret'):
                return False, 'err %s is a secret — its default is the None ladder-end, categorically' % name
            text = (value or '').strip()
            conv = self.row.get('conv', 'str')
            was = self.row.get(key)
            if not text:
                if key not in self.row:
                    return False, 'err %s carries no default (nothing to clear)' % name
                del self.row[key]
                return True, 'ok %s.default cleared (the None ladder-end)' % name
            try:
                if conv == 'bool':
                    v = {'true': True, 'on': True, 'false': False, 'off': False}[text.lower()]
                elif conv == 'int':
                    v = int(text)
                elif conv == 'float':
                    v = float(text)
                    if v != v or v in (float('inf'), float('-inf')):
                        raise ValueError('not finite')
                else:
                    v = text
            except (KeyError, ValueError):
                return False, 'err %s.default must parse as %s (got %r)' % (name, conv, text)
            if v == was and type(v) is type(was):
                return False, '%s: default already %r' % (name, was)
            self.row[key] = v
            return True, 'ok %s.default = %s' % (name, json.dumps(v, ensure_ascii=False))
        if value:
            if key == 'group' and (any(c.isspace() for c in value) or '/' in value):
                return False, 'err group must be one clean word'
            if key == 'live' and not clean_path(value):
                return False, 'err live must be one clean word-path'
            if key == 'alias' and not clean_path(value):
                return False, 'err alias must be one clean word-path'
        was = self.row.get(key)
        if value == (was or ''):
            return False, '%s: %s already %r' % (name, key, was)
        _, canon_carries = self.effective(self.row, key)   # the pre-edit answer: the field
        was_canon_only = was is None and canon_carries      # absent inline, the block speaking
        if value:
            if isinstance(was, bool):   # a bool field stores a bool, whatever the spelling
                v = value.lower()
                if v not in ('true', 'false'):
                    return False, 'err %s must be true or false' % key
                self.row[key] = v == 'true'
            else:
                self.row[key] = value
        else:
            if key not in self.row:
                _, from_canon = self.effective(self.row, key)
                if from_canon:
                    return False, 'err %s carries no inline %s — the canon block speaks; edit to override' % (name, key)
                return False, 'err %s carries no %s (nothing to clear)' % (name, key)
            del self.row[key]
        note = ' (the inline override of the canon block)' if was_canon_only else ''
        return True, 'ok %s.%s %s%s' % (name, key, '= %s' % json.dumps(value, ensure_ascii=False) if value
                                        else 'cleared', note)

    def index_lines(self, filt='', order='name', vmode='all', kmode='all'):
        """The line-mode knob index: the name, its live-or-group bucket, the
        kind, the setting-help — viewed, kind-gated, filtered and ordered
        like the dialog. The `show` rows list beside the knobs (their
        bucket: show)."""
        rows = view_rows(self.rows + self.show + self.cmds, filt, order, self.kind, vmode, kmode)
        note = ((' — view %s' % vmode) if vmode != 'all' else '') + \
               ((' — kind %s' % kmode) if kmode != 'all' else '') + \
               ((' — filter %r, order %s' % (filt, order)) if (filt or order != 'name') else '')
        print('# %s — %d of %d rows%s (type a name to edit it, quit leaves)'
              % (self.path, len(rows), len(self.rows) + len(self.show) + len(self.cmds), note))
        for r in rows:
            bucket = bucket_of(self, r)
            sval, _ = self.effective(r, 'setting-help')
            hval, _ = self.effective(r, 'help')
            help_text = sval or hval or ''
            print('  %-23s %-26s %-13s %s' % (r['name'], bucket, self.kind(r), help_text[:56]))
        print()

    def seed_value_help(self):
        """The inline value-help dict seeded from the canon block — the
        override replaces the WHOLE dict, so an edit that lands without the
        seed would drop the block's other pairs silently."""
        block = self.canon_block(self.row)
        if 'value-help' not in self.row and isinstance(block, dict) and block.get('value-help'):
            self.row['value-help'] = dict(block['value-help'])
            return True
        return False

    def edit_value_help(self, rest):
        """The line-mode value-help grammar: <KEY> <text> | -<KEY> | -."""
        name = self.row['name']
        self.seed_value_help()
        vh = dict(self.row.get('value-help') or {})
        if rest == '-':
            if not vh:
                return False, 'err %s carries no value-help (nothing to clear)' % name
            gone = len(vh)
            self.row['value-help'] = {}
            return True, 'ok %s.value-help cleared (%d entr%s gone)' % (name, gone, 'y' if gone == 1 else 'ies')
        if rest.startswith('-'):
            key = rest[1:]
            if key not in vh:
                return False, 'err no value-help for %r' % key
            del vh[key]
            self.row['value-help'] = vh
            return True, 'ok %s.value-help %s removed (%d left)' % (name, key, len(vh))
        parts = rest.split(None, 1)
        if len(parts) != 2 or not parts[0] or any(c.isspace() for c in parts[0]) or parts[0].startswith('-'):
            return False, 'err value-help needs <KEY> <text> (-<KEY> removes, - clears)'
        key, text = parts
        vh[key] = text
        self.row['value-help'] = vh
        return True, 'ok %s.value-help %s = %s' % (name, key, json.dumps(text, ensure_ascii=False))


def options_dialog(editor, screen):
    """The curses face: the knob menu, the row form, the value-help key
    menu, the input line."""
    import curses

    get_key, fit, put, frame, status, input_line, confirm = dialog_bindings(screen)

    def draw_list(cursor, top, msg):
        screen.erase()
        note = ((' — view %s' % vmode) if vmode != 'all' else '') + \
               ((' — kind %s' % kmode) if kmode != 'all' else '') + \
               ((' — filter %r, order %s' % (filt, order)) if (filt or order != 'name') else '')
        frame('pv-dash registry editor — %s — %d of %d rows%s (v views, k kinds, o sorts, '
              '/ filters, l lint, Enter edits, q quits)'
              % (editor.path, len(view), len(editor.rows) + len(editor.show), note))
        height = curses.LINES - 4
        top = fit(top, cursor, view, height)
        for i in range(height):
            idx = top + i
            if idx >= len(view):
                break
            r = view[idx]
            bucket = bucket_of(editor, r)
            line = '  %-23s %-26s %-13s %s' % (r['name'], bucket, editor.kind(r),
                                               (r.get('setting-help') or r.get('help') or ''))
            put(2 + i, 0, line, curses.A_REVERSE if idx == cursor else 0)
        status(msg or 'type / to filter, v view, k kind, o sort, l lint, Enter opens a row', dim=not msg)
        screen.refresh()
        return top

    def draw_form(fcursor, ftop, msg):
        """The row's fields: a leading * marks the editable ones (d clears
        the cursored one), 'edited' marks the fields off their pristine."""
        screen.erase()
        state = 'unsaved edits — s save, c cancel' if editor.dirty() else 'no changes'
        frame('%s — %s — Enter edits, p proposes, d clears, l lint, x deletes node, '
              's save, c cancel, q quit' % (editor.row['name'], state))
        keys = row_keys(editor.row, editor.editable_set(editor.row))
        height = curses.LINES - 4
        ftop = fit(ftop, fcursor, keys, height)
        for i in range(height):
            idx = ftop + i
            if idx >= len(keys):
                break
            key = keys[idx]
            marks = []
            if editor.row.get(key) != editor.pristine.get(key):   # absent-absent = not edited
                marks.append('edited')
            val, is_canon = editor.effective(editor.row, key)
            if is_canon:
                marks.append('canon')
            line = '  %s%-12s %s%s' % ('*' if key in editor.editable_set(editor.row) else ' ',
                                       key, shown({key: val}, key) if val is not None else '-',
                                       ('   [%s]' % '; '.join(marks)) if marks else '')
            put(2 + i, 0, line, curses.A_REVERSE if idx == fcursor else 0)
        status(msg)
        screen.refresh()
        return ftop

    def draw_vh(keys, vcursor, vtop, msg):
        screen.erase()
        frame('value-help of %s — Enter edits a text, a adds, d deletes, Esc back' % editor.row['name'])
        height = curses.LINES - 4
        vtop = fit(vtop, vcursor, keys, height)
        for i in range(height):
            idx = vtop + i
            if idx >= len(keys):
                break
            k = keys[idx]
            put(2 + i, 0, '  %-23s %s' % (k, editor.row['value-help'][k]),
                curses.A_REVERSE if idx == vcursor else 0)
        status(msg)
        screen.refresh()
        return vtop

    def bool_menu(key):
        """A bool field's pick: true|false from the menu, not the string —
        the arrows walk, Enter takes, Esc keeps the field as it is."""
        return pick_menu(
            screen, '%s of %s — Enter takes, Esc keeps the field as it is' % (key, editor.row['name']),
            (('true', 'set the field true'),
             ('false', 'clear the field (its absence = false)')),
            0 if editor.row.get(key) in (True, None) else 1,
            lambda word: editor.set_field(key, word)[1])

    def lint_report():
        """The `l` report: the file's lint findings on one status line —
        the same pass the exit runs; the findings warn, never block."""
        nits, _canon = lint(editor.path)
        if not nits:
            return 'lint: clean'
        found = [n.replace(editor.path + ': ', '') for n in nits]
        return ' | '.join(found[:2]) + (' | ...' if len(found) > 2 else '')

    def edit_value(key):
        """The input line for one field; applies with the gate rules. A
        bool field's initial (and its empty accept) spell on/off. An
        empty field opens with the shared draft as its initial buffer —
        Enter accepts the proposal, typing overwrites it, Esc aborts.
        A conv-typed default (int/float) spells its own value back."""
        was = editor.row.get(key, '')
        initial = ('true' if was else 'false') if isinstance(was, bool) else was
        if not isinstance(initial, str):   # the conv-typed default edits as its own spelling
            initial = str(initial)
        if not was:
            initial = next((d for f, d, _ in proposals(editor.row, editor.canon) if f == key), initial)
        text = input_line('%s: ' % key, initial)
        if text is None:
            return 'unchanged (esc)'
        text = text.strip()
        if isinstance(was, bool) and not text:
            text = 'false'
        ok, msg = editor.set_field(key, text)
        return msg

    def confirm_quit():
        return confirm('quit discarding')

    def vh_menu():
        """The value-help key menu for the open row (the canon pairs seed the
        inline dict — the override replaces the whole dict)."""
        editor.seed_value_help()
        vcursor, vtop, msg = 0, 0, ''
        while True:
            keys = list(editor.row.get('value-help') or {})
            if vcursor >= len(keys):
                vcursor = max(0, len(keys) - 1)
            vtop = draw_vh(keys, vcursor, vtop, msg)
            msg = ''
            k = get_key(screen)
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                vcursor = max(0, min(len(keys) - 1, vcursor + (1 if k == curses.KEY_DOWN else -1)))
            elif k in (10, 13, curses.KEY_ENTER):
                if keys:
                    key = keys[vcursor]
                    text = input_line('value-help %s: ' % key, editor.row['value-help'].get(key, '') or 'TODO: when does one pick %s?' % key)
                    if text is not None and text.strip() and text.strip() != editor.row['value-help'].get(key):
                        vh = dict(editor.row.get('value-help') or {})
                        vh[key] = text.strip()
                        editor.row['value-help'] = vh
                        msg = 'ok value-help %s = %s' % (key, text.strip())
            elif k in (ord('a'), ord('A')):
                name = input_line('new value key: ', '')
                if name is None:
                    continue
                if not name.strip() or any(c.isspace() for c in name.strip()) or name.strip().startswith('-'):
                    msg = 'err the value key must be one word'
                    continue
                text = input_line('value-help %s: ' % name.strip(), 'TODO: when does one pick %s?' % name.strip())
                if text is not None and text.strip():
                    vh = dict(editor.row.get('value-help') or {})
                    vh[name.strip()] = text.strip()
                    editor.row['value-help'] = vh
                    msg = 'ok value-help %s added' % name.strip()
            elif k in (ord('d'), ord('D')):
                if keys:
                    vh = dict(editor.row.get('value-help') or {})
                    gone = keys[vcursor]
                    del vh[gone]
                    editor.row['value-help'] = vh
                    msg = 'ok value-help %s removed (%d left)' % (gone, len(vh))
            elif k == INTR:
                return ''
            elif k == 27:
                return ''

    cursor, top, msg = 0, 0, ''
    fcursor, ftop = 0, 0
    filt, order, vmode, kmode = '', 'name', 'all', 'all'
    view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
    while True:
        if editor.row is None:
            cursor = min(cursor, len(view) - 1)
            top = draw_list(cursor, top, msg)
            msg = ''
            k = get_key(screen)
            moved = walk(k, cursor, len(view), curses.LINES - 6)
            if moved is not None:
                cursor = moved
            elif k == ord('/'):
                q = input_line('filter (empty clears): ', filt)
                if q is None:
                    msg = ''
                else:
                    filt = q.strip()
                    view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
                    cursor = 0
                    msg = '' if not filt or view else 'no row matches %r' % filt
            elif k in (ord('a'), ord('A')):   # add a hierarchy node
                name = input_line('new node name: ', '')
                if name is None:
                    msg = ''
                elif not name.strip() or any(c.isspace() for c in name.strip()) or '/' in name.strip():
                    msg = 'err the node name must be one clean word'
                else:
                    draft = next((d for f, d, _ in proposals({'name': name.strip(), 'node': True}, editor.canon)
                                  if f == 'setting-help'), '')
                    desc = input_line('setting-help: ', draft)   # the draft = the ack-inline
                    if desc is None:
                        msg = ''
                    elif not desc.strip():
                        msg = 'err the node needs its description'
                    else:
                        ok, msg = editor.add_node(name.strip(), desc.strip())
                        if ok:
                            view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
                            names = [r['name'] for r in view]
                            new_name = name.strip()
                            cursor = names.index(new_name) if new_name in names else min(cursor, max(0, len(names) - 1))
            elif k == ord('o'):
                order = ORDERS[(ORDERS.index(order) + 1) % len(ORDERS)]
                view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
                cursor = 0
                msg = 'order: %s' % order
            elif k in (ord('v'), ord('V')):
                vmode = VIEWS[(VIEWS.index(vmode) + 1) % len(VIEWS)]
                view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
                cursor = 0
                msg = 'view: %s (all, live, other)' % vmode
            elif k in (ord('k'), ord('K')):
                kmode = KCYCLE[(KCYCLE.index(kmode) + 1) % len(KCYCLE)]
                view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
                cursor = 0
                msg = 'kind: %s (%s)' % (kmode, ' | '.join(KCYCLE))
            elif k in (ord('l'), ord('L')):   # the file's lint findings, list or form
                msg = lint_report()
            elif k in (10, 13, curses.KEY_ENTER):
                editor.open(view[cursor]['name'])
                fcursor, ftop, msg = 0, 0, ''
            elif k == INTR:
                msg = '^C — q quits'
            elif k in (ord('q'), ord('Q')):
                if confirm('quit'):
                    return
                msg = 'stayed'
        else:
            ftop = draw_form(fcursor, ftop, msg)
            msg = ''
            k = get_key(screen)
            fkeys = row_keys(editor.row, editor.editable_set(editor.row))
            moved = walk(k, fcursor, len(fkeys), curses.LINES - 6)
            if moved is not None:
                fcursor = moved
            elif k in (10, 13, curses.KEY_ENTER):
                key = fkeys[fcursor]
                if key not in editor.editable_set(editor.row):
                    msg = '%s is view-only (the registry renders it elsewhere)' % key
                elif key == 'value-help':
                    msg = vh_menu()
                elif key in ('hidden', 'restart', 'internal') or isinstance(editor.row.get(key), bool):
                    msg = bool_menu(key)   # a bool picks from the menu, not the string
                else:
                    msg = edit_value(key)
            elif k in (ord('d'), ord('D')):
                key = fkeys[fcursor]
                if key not in editor.editable_set(editor.row):
                    msg = '%s is view-only (the registry renders it elsewhere)' % key
                else:
                    ok, msg = editor.set_field(key, '')   # the empty = the clear; a bool = false
                    if ok:
                        fcursor = min(fcursor, len(row_keys(editor.row, editor.editable_set(editor.row))) - 1)
            elif k in (ord('p'), ord('P')):   # the proposals: one prefilled edit per field
                prs = proposals(editor.row, editor.canon)
                if not prs:
                    msg = 'nothing to propose for %s — the fields carry their drafts, or the shape is not derivable' % editor.row['name']
                for f, d, why in prs:
                    keys = row_keys(editor.row, editor.editable_set(editor.row))
                    if f not in keys:
                        continue
                    fcursor = keys.index(f)
                    msg = edit_value(f)   # the draft prefilled; the ack = the Enter
                    if 'unchanged' in msg:
                        break   # Esc stops the walk, the rest stays as it is
            elif k in (ord('l'), ord('L')):   # the file's lint findings, list or form
                msg = lint_report()
            elif k in (ord('s'), ord('S')):
                name = editor.row['name']
                if editor.dirty() and not confirm('save %s' % name):
                    msg = 'not saved — the row stays open'
                else:
                    ok, msg = editor.write_row()
                    if ok:
                        editor.row = None
                        view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
                        names = [r['name'] for r in view]
                        cursor = names.index(name) if name in names else min(cursor, max(0, len(names) - 1))
            elif k == 27:   # Esc = the cancel, straight — c keeps the confirm
                editor.cancel()
                msg = 'cancelled'
            elif k in (ord('x'), ord('X')):   # the node-delete (the nodes only)
                name = editor.row['name']
                if not editor.row.get('node'):
                    msg = 'err only a hierarchy node deletes — %s is a %s' % (name, editor.kind(editor.row))
                elif confirm('delete the node %s' % name):
                    ok, msg = editor.delete_node()
                    if ok:
                        editor.row = None
                        view = view_rows(editor.rows + editor.show + editor.cmds, filt, order, editor.kind, vmode, kmode)
                        cursor = min(cursor, max(0, len(view) - 1))
                        ftop = 0
                else:
                    msg = 'kept — nothing deleted'
            elif k in (ord('c'), ord('C')):
                if editor.dirty() and not confirm('discard the edits to %s' % editor.row['name']):
                    msg = 'kept the edits — s saves, c cancels'
                else:
                    editor.cancel()
                    msg = 'cancelled'
            elif k == INTR:
                msg = '^C — c cancels, s saves'
            elif k in (ord('q'), ord('Q')):
                if editor.dirty():
                    if confirm_quit():
                        editor.cancel()
                        return
                    msg = 'kept the edits — s saves, c cancels'
                else:
                    if confirm('quit'):
                        return
                    msg = 'stayed'


def show_row(editor, row):
    """The line-mode row view: every field aligned, the unwritten changes
    marked (edited), the block-carried fields marked (canon)."""
    print()
    for key in row_keys(row):
        val, is_canon = editor.effective(row, key)
        note = ''
        if editor.pristine is not None and row.get(key) != editor.pristine.get(key):
            note = '(edited)'
        elif is_canon:
            note = '(canon)'
        print('    %-13s %s%s' % (key, shown({key: val}, key) if val is not None else '-',
                                  ('    %s' % note) if note else ''))
    print()


def options_line_mode(editor):
    """The line face: the same flow as the dialog, one prompt per step."""
    filt, order, vmode, kmode = '', 'name', 'all', 'all'
    editor.index_lines(filt, order, vmode, kmode)
    while True:
        line = read_line('name > ')
        if line is None:
            return 0
        if not line or line.startswith('#'):
            continue
        low = line.lower()
        if low in ('quit', 'exit'):
            return 0
        if low == 'list':
            editor.index_lines(filt, order, vmode, kmode)
            continue
        if low == 'lint':
            nits, _canon = lint(editor.path)
            for nit in nits:
                print('  - %s' % nit.replace(editor.path + ': ', ''))
            print('lint: %d finding(s)' % len(nits) if nits else 'lint: clean')
            continue
        if low.startswith('filter'):
            filt = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ''
            editor.index_lines(filt, order, vmode, kmode)
            continue
        if low.startswith('view'):
            arg = line.split(None, 1)[1].strip().lower() if len(line.split(None, 1)) > 1 else ''
            if not arg:
                vmode = VIEWS[(VIEWS.index(vmode) + 1) % len(VIEWS)]
            elif arg in VIEWS:
                vmode = arg
            else:
                print('err view is one of %s' % ', '.join(VIEWS))
                continue
            editor.index_lines(filt, order, vmode, kmode)
            continue
        if low.startswith('kind'):
            arg = line.split(None, 1)[1].strip().lower() if len(line.split(None, 1)) > 1 else ''
            if not arg:
                kmode = KCYCLE[(KCYCLE.index(kmode) + 1) % len(KCYCLE)]
            elif arg in KINDS:
                kmode = arg
            elif arg == 'all':
                kmode = 'all'
            else:
                print('err kind is one of %s' % ' | '.join(KCYCLE))
                continue
            editor.index_lines(filt, order, vmode, kmode)
            continue
        if low.startswith('sort'):
            arg = line.split(None, 1)[1].strip().lower() if len(line.split(None, 1)) > 1 else ''
            if not arg:
                order = ORDERS[(ORDERS.index(order) + 1) % len(ORDERS)]
            elif arg in ORDERS:
                order = arg
            else:
                print('err sort order is one of %s' % ', '.join(ORDERS))
                continue
            editor.index_lines(filt, order, vmode, kmode)
            continue
        row = editor.by_name().get(line.split()[0])
        if row is None:
            print('err no option named %r (list shows the index)' % line.split()[0])
            continue
        editor.open(row['name'])
        print('editing %s — edit the hinted fields, save writes and returns, '
              'cancel discards, quit leaves' % row['name'])
        show_row(editor, editor.row)
        warned = False
        while True:
            mark = '*' if editor.dirty() else ''
            sub = read_line('%s%s > ' % (row['name'], mark))
            if sub is None:
                editor.cancel()
                break
            if not sub:
                continue
            if sub.lower() == 'quit':
                if editor.dirty() and not warned:
                    print('err unsaved edits — save, cancel, or quit again to discard')
                    warned = True
                    continue
                return 0
            warned = False
            parts = sub.split(None, 1)
            field = parts[0].lower()
            if field == 'show':
                show_row(editor, editor.row)
            elif field in ('save', 'write'):
                ok, msg = editor.write_row()
                print(msg)
                if ok:
                    editor.index_lines(filt, order, vmode, kmode)
                    break
            elif field in ('cancel', 'list'):
                editor.cancel()
                break
            elif field not in editor.editable_set(editor.row):
                print('err unknown field %r (edit: %s | show | save | cancel | quit)'
                      % (field, ' | '.join(EDITABLE)))
            else:
                rest = parts[1].strip() if len(parts) > 1 else ''
                if field == 'value-help':
                    ok, msg = editor.edit_value_help(rest)
                else:
                    ok, msg = editor.set_field(field, '' if rest == '-' else rest)
                print(msg)


class OptionsCompleter:
    """The line-mode TAB completion: the knob names at the index prompt, the
    field commands at the row prompt (the editor flips the pool by state)."""

    def __init__(self, editor):
        self.editor = editor
        self.row_mode = False

    def complete(self, text, state):
        if self.row_mode:
            pool = list(EDITABLE) + ['save', 'cancel', 'show', 'quit']
        else:
            pool = [r['name'] for r in self.editor.rows] + ['list', 'lint', 'quit']
        return complete_word(pool, text, state)


def exit_lint(editor):
    """The exit hygiene: one lint pass on the way out — the nits report,
    and the canonical re-render when the file drifted (the row-splices
    keep their surroundings; this is the belt's suspenders)."""
    nits, canon = lint(editor.path)
    for nit in nits:
        print(nit)
    if canon is not None and canon != open(editor.path, encoding='utf-8').read():
        with blocked_sigint(), open(editor.path, 'w', encoding='utf-8') as f:
            f.write(canon)
        print('lint: %s reformatted on exit' % os.path.basename(editor.path))


def options_main(raw):
    forced_line = '--line' in raw
    args = [a for a in raw if a != '--line']
    if len(args) > 1 or (args and args[0] in ('-h', '--help')):
        print('usage: editor.py options [--line] [<project>]   (%s)' % ' | '.join(PROJECTS))
        return 1
    project = args[0] if args else None
    if project is None and sys.stdin.isatty() and not forced_line:
        # the dialog can prompt for it before any terminal work: a plain input()
        line = read_line('project (%s): ' % ' | '.join(PROJECTS))
        if line is None:
            return 0
        line = line.lower()
        project = line if line in PROJECTS else None
        if project is None:
            print('err one of: %s' % ', '.join(PROJECTS))
            return 1
    try:
        editor = OptionsEditor(project)
    except (OSError, ValueError) as e:
        print('editor.py options: %s' % e)
        return 1
    if forced_line or not sys.stdin.isatty():
        setup_readline(OptionsCompleter(editor))
        code = options_line_mode(editor)
    else:
        dialog_wrapper(options_dialog, editor)
        code = 0
    exit_lint(editor)
    return code


# ---------------------------------------------------------------- the acl face (the golden master)

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


class AclEditor:
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
                                 'scripts/editor.py)' % self.rel)
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
        try:
            with blocked_sigint():
                if self.fresh:   # the first landing: 0600 (the acl trust posture)
                    fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        f.write(new_text)
                else:
                    with open(self.path, 'w', encoding='utf-8') as f:
                        f.write(new_text)
        except OSError as e:
            return False, 'err cannot write %s: %s' % (self.rel, e)
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


def acl_report(ed):
    """The gate as the editor shows it: the desc header, one numbered
    line per rule (the show report's aligned shape, with numbers)."""
    desc = ed.gate.get('desc')
    print('# %s' % desc if desc else '# (no gate desc)')
    for i, r in enumerate(ed.rules()):
        print('  %2d  %-5s  %-34s  %s'
              % (i + 1, r.get('type', '?'), show_matcher(r.get(ed.kind)), r.get('desc') or ''))
    print()


def acl_help_lines(kind):
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


def acl_line_mode(ed):
    print('# %s — %d rule(s), %d lint issue(s)%s (help lists the commands)'
          % (ed.path, len(ed.rules()), len(ed.issues()),
             ' — NEW, the file lands on save' if ed.fresh else ''))
    while True:
        line = read_line('acl > ')
        if line is None:
            return 0
        if not line or line.startswith('#'):
            continue
        low = line.lower()
        if low in ('quit', 'exit'):
            if ed.dirty():
                print('err unsaved edits — save, reload, or quit again to discard')
                again = read_line('acl > ')
                if again is None:
                    return 0
                if again.lower() not in ('quit', 'exit'):
                    continue
            return 0
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ''
        if cmd == 'help' or line == '?':
            for h in acl_help_lines(ed.kind):
                print('  %s' % h)
        elif cmd == 'show':
            acl_report(ed)
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
                acl_report(ed)
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
                acl_report(ed)
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


class AclCompleter:
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
        return complete_word(pool, text, state)


def acl_dialog(ed, screen):
    """The curses face: the rule list, the rule form, the input line."""
    import curses

    get_key, fit, put, frame, status, input_line, confirm = dialog_bindings(screen)

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
        return pick_menu(
            screen, 'the gate type — Enter takes, Esc keeps the gate as it is',
            (('write-registers', 'the registers gate — the rules match by range'),
             ('ip-prefix', 'the IP gate — the rules match by prefix')),
            0 if ed.gate.get('type') == 'write-registers' else 1,
            lambda word: ed.set_gate_type(word)[1])

    def verb_menu():
        """The type pick: allow|deny from the menu, the arrows walk, Enter
        takes, Esc keeps the field as it is."""
        n = ed.rule + 1
        what = 'registers' if ed.kind == 'range' else 'addresses'
        return pick_menu(
            screen, 'type of rule %d — Enter takes, Esc keeps the field as it is' % n,
            (('allow', 'the rule allows the %s' % what),
             ('deny', 'the rule refuses the %s' % what)),
            0 if ed.rules()[ed.rule].get('type') == 'allow' else 1,
            lambda word: ed.set_type(n, word)[1])

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
            moved = walk(k, cursor, len(ed.rules()), curses.LINES - 6)
            if moved is not None:
                cursor = moved
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
            moved = walk(k, fcursor, len(fields()), curses.LINES - 6)
            if moved is not None:
                fcursor = moved
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


def acl_main(raw):
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
        print('usage: editor.py acl [--type write-registers|ip-prefix] [--line] <acl-file>')
        return 1
    if gate_type is not None and gate_type not in _GATE_TYPES:
        print('editor.py acl: unknown gate type %r (write-registers | ip-prefix)' % gate_type)
        return 1
    path = args[0] if args else None
    if path is None:
        if forced_line or not sys.stdin.isatty():
            print('usage: editor.py acl [--type write-registers|ip-prefix] [--line] <acl-file>')
            return 1
        path = read_line('acl file: ')
        if path is None:
            return 0
        if not path:
            return 1
    try:
        ed = AclEditor(path, gate_type)
    except (OSError, ValueError) as e:
        print('editor.py acl: %s' % e)
        return 1
    if forced_line or not sys.stdin.isatty():
        setup_readline(AclCompleter(ed))
        return acl_line_mode(ed)
    dialog_wrapper(acl_dialog, ed)
    return 0


# ---------------------------------------------------------------- the dispatch

USAGE = ('usage: editor.py options [--line] [<project>]   (%s)\n'
         '       editor.py acl [--type write-registers|ip-prefix] [--line] <acl-file>'
         % ' | '.join(PROJECTS))


def main():
    raw = sys.argv[1:]
    face = raw[0] if raw else None
    if face not in ('options', 'acl'):
        if face is None and sys.stdin.isatty():
            face = read_line('face (options | acl): ')
            if face is None:
                return 0
            face = face.lower()
        if face not in ('options', 'acl'):
            print(USAGE)
            return 1
    args = raw[1:]
    if face == 'acl':
        return acl_main(args)
    return options_main(args)


if __name__ == '__main__':
    sys.exit(main())
