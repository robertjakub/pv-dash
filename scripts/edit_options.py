#!/usr/bin/env python3
"""The registry's editor — two faces, one core:

  python3 scripts/edit_options.py [<project>]     the dialog (curses) on a tty
  python3 scripts/edit_options.py --line <project>  the line mode (also when piped)

The dialog: the knob index is the menu — arrows walk it, Enter opens the
row as a form; arrows walk the fields, Enter edits an editable one
(group, live, alias, setting-help, hint, the conv-typed default — the
static rung, a secret refused categorically — the marks: internal keeps a
command row off the cli (the wire answers), hidden hides the row
from the ?/TAB pools, restart marks the startup-only knob; value-help
opens its own key menu —
Enter edits a value's text, a adds a key, d deletes it), Esc leaves the
input line empty-handed, s saves the row (surgically: the touched row
re-renders in the house format, the rest of the file stays
byte-for-byte; parse-back guarded), c cancels back to the menu, q quits —
warned away while a row holds unsaved edits. The view-only fields (flag,
env, conv, help — the one-knob-one-source surfaces
render them elsewhere) show with the rest; edited fields are marked.
A live RENAME is a wave, not an edit: the daemon's _apply/defaults
dispatch keys the live name (docs/TODO.md). An alias is an edit: the
dispatch canonicalizes through the map, so a second spelling rides
alone.

Exit 0 = done, 1 = error. Stdlib only."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # the sibling lint_options (the canonical renderer, the drafts)

from lint_options import lint, proposals, render_registry

try:
    import readline
except ImportError:
    readline = None


PROJECTS = ('cache', 'scraper', 'inverter', 'dashboard')
INLINE = ('name', 'flag', 'env', 'conv', 'group', 'live', 'alias', 'negates')
EDITABLE = ('group', 'live', 'alias', 'setting-help', 'hint', 'value-help', 'default', 'hidden', 'restart')
SHOW_EDITABLE = ('group', 'live', 'alias', 'setting-help', 'hidden')   # the registry's `show` rows: the
                                                                       # bucket, the live hierarchy, the
                                                                       # alias, the word's description, the mark
CMD_EDITABLE = ('group', 'help', 'hidden', 'internal')   # the `commands` rows: the bucket, the
                                                         # description, the marks
BEFORE_HELP = ('setting-help', 'values', 'hint', 'value-help', 'default')

from scriptlib import clean_path, row_span   # the shared registry-editing helpers


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


class Editor:
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
        self.row = None
        self.pristine = None

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
        with open(self.path, 'w', encoding='utf-8') as f:
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
        with open(self.path, 'w', encoding='utf-8') as f:
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
        with open(self.path, 'w', encoding='utf-8') as f:
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

    def set_field(self, key, value):
        """One field edit with the gate rules; (ok, message)."""
        name = self.row['name']
        if key == 'name':
            return False, 'err the name is the row\'s identity — it does not edit'
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
        if self.row.get('node') and key not in ('setting-help', 'group'):
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
                return False, 'err %s carries no %s (nothing to clear)' % (name, key)
            del self.row[key]
        return True, 'ok %s.%s %s' % (name, key, '= %s' % json.dumps(value, ensure_ascii=False) if value
                                      else 'cleared')


# ---------------------------------------------------------------- the dialog

def dialog(editor, screen):
    """The curses face: the knob menu, the row form, the value-help key
    menu, the input line."""
    import curses

    import tui
    get_key = tui.get_key
    fit = tui.fit
    put = lambda y, x, text, attr=0: tui.put(screen, y, x, text, attr)
    frame = lambda title: tui.frame(screen, title)
    status = lambda msg, dim=False: tui.status(screen, msg, dim)
    input_line = lambda prompt, initial='': tui.input_line(screen, prompt, initial)
    confirm = lambda word: tui.confirm(screen, word)

    def draw_list(cursor, top, msg):
        screen.erase()
        note = ((' — view %s' % vmode) if vmode != 'all' else '') + \
               ((' — kind %s' % kmode) if kmode != 'all' else '') + \
               ((' — filter %r, order %s' % (filt, order)) if (filt or order != 'name') else '')
        frame('pv-dash registry editor — %s — %d of %d rows%s (v views, k kinds, o sorts, / filters, Enter edits, q quits)'
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
        status(msg or 'type / to filter, v view, k kind, o sort, Enter opens a row', dim=not msg)
        screen.refresh()
        return top

    def draw_form(fcursor, ftop, msg):
        """The row's fields: a leading * marks the editable ones (d clears
        the cursored one), 'edited' marks the fields off their pristine."""
        screen.erase()
        state = 'unsaved edits — s save, c cancel' if editor.dirty() else 'no changes'
        frame('%s — %s — Enter edits, p proposes, d clears, x deletes node, s save, c cancel, q quit' % (editor.row['name'], state))
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
            line = '  %s%-12s %s%s' % ('*' if key in editor.editable_set(editor.row) else ' ',
                                       key, shown(editor.row, key),
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
        """A bool field's pick: true|false from the menu, not the string — the
        arrows walk, Enter takes, Esc keeps the field as it is."""
        options = (('true', 'set the field true'),
                   ('false', 'clear the field (its absence = false)'))
        bcursor, msg = 0 if editor.row.get(key) in (True, None) else 1, ''
        while True:
            screen.erase()
            frame('%s of %s — Enter takes, Esc keeps the field as it is' % (key, editor.row['name']))
            for i, (word, what) in enumerate(options):
                put(2 + i, 0, '  %-6s %s' % (word, what), curses.A_REVERSE if i == bcursor else 0)
            status(msg)
            screen.refresh()
            k = get_key(screen)
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                bcursor = 1 - bcursor
            elif k in (10, 13, curses.KEY_ENTER):
                ok, msg = editor.set_field(key, options[bcursor][0])
                return msg
            elif k == 27:
                return 'unchanged (esc)'

    def edit_value(key):
        """The input line for one field; applies with the gate rules. A
        bool field's initial (and its empty accept) spell on/off. An
        empty field opens with the shared draft as its initial buffer —
        Enter accepts the proposal, typing overwrites it, Esc aborts."""
        was = editor.row.get(key, '')
        initial = ('true' if was else 'false') if isinstance(was, bool) else was
        if not was:
            initial = next((d for f, d, _ in proposals(editor.row) if f == key), initial)
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
        """The value-help key menu for the open row."""
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
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                cursor = max(0, min(len(view) - 1, cursor + (1 if k == curses.KEY_DOWN else -1)))
            elif k == curses.KEY_PPAGE:
                cursor = max(0, cursor - (curses.LINES - 6))
            elif k == curses.KEY_NPAGE:
                cursor = min(len(view) - 1, cursor + (curses.LINES - 6))
            elif k == curses.KEY_HOME:
                cursor = 0
            elif k == curses.KEY_END:
                cursor = len(view) - 1
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
                    draft = next((d for f, d, _ in proposals({'name': name.strip(), 'node': True})
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
            elif k in (10, 13, curses.KEY_ENTER):
                editor.open(view[cursor]['name'])
                fcursor, ftop, msg = 0, 0, ''
            elif k in (ord('q'), ord('Q')):
                if confirm('quit'):
                    return
                msg = 'stayed'
        else:
            ftop = draw_form(fcursor, ftop, msg)
            msg = ''
            k = get_key(screen)
            if k in (curses.KEY_UP, curses.KEY_DOWN):
                fcursor = max(0, min(len(row_keys(editor.row, editor.editable_set(editor.row))) - 1,
                                     fcursor + (1 if k == curses.KEY_DOWN else -1)))
            elif k in (10, 13, curses.KEY_ENTER):
                key = row_keys(editor.row, editor.editable_set(editor.row))[fcursor]
                if key not in editor.editable_set(editor.row):
                    msg = '%s is view-only (the registry renders it elsewhere)' % key
                elif key == 'value-help':
                    msg = vh_menu()
                elif key in ('hidden', 'restart', 'internal') or isinstance(editor.row.get(key), bool):
                    msg = bool_menu(key)   # a bool picks from the menu, not the string
                else:
                    msg = edit_value(key)
            elif k in (ord('d'), ord('D')):
                key = row_keys(editor.row, editor.editable_set(editor.row))[fcursor]
                if key not in editor.editable_set(editor.row):
                    msg = '%s is view-only (the registry renders it elsewhere)' % key
                else:
                    ok, msg = editor.set_field(key, '')   # the empty = the clear; a bool = false
                    if ok:
                        fcursor = min(fcursor, len(row_keys(editor.row, editor.editable_set(editor.row))) - 1)
            elif k in (ord('p'), ord('P')):   # the proposals: one prefilled edit per field
                prs = proposals(editor.row)
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


def dialog_wrapper(editor):
    """The curses terminal lifecycle (restored on any exit)."""
    import curses

    def run(screen):
        curses.curs_set(0)
        screen.keypad(True)
        dialog(editor, screen)
    curses.wrapper(run)


# ---------------------------------------------------------------- the lines

def show_row(editor, row):
    """The line-mode row view: every field aligned, the unwritten changes
    marked (edited)."""
    print()
    for key in row_keys(row):
        note = ''
        if editor.pristine is not None and row.get(key) != editor.pristine.get(key):
            note = '(edited)'
        print('    %-13s %s%s' % (key, shown(row, key), ('    %s' % note) if note else ''))
    print()


def line_mode(editor):
    """The line face: the same flow as the dialog, one prompt per step."""
    filt, order, vmode, kmode = '', 'name', 'all', 'all'
    editor.index_lines(filt, order, vmode, kmode)
    while True:
        try:
            line = input('name > ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line or line.startswith('#'):
            continue
        low = line.lower()
        if low in ('quit', 'exit'):
            return 0
        if low == 'list':
            editor.index_lines(filt, order, vmode, kmode)
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
            try:
                sub = input('%s%s > ' % (row['name'], mark)).strip()
            except (EOFError, KeyboardInterrupt):
                print()
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
        help_text = r.get('setting-help') or r.get('help') or ''
        print('  %-23s %-26s %-13s %s' % (r['name'], bucket, self.kind(r), help_text[:56]))
    print()


def edit_value_help(self, rest):
    """The line-mode value-help grammar: <KEY> <text> | -<KEY> | -."""
    name = self.row['name']
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


Editor.index_lines = index_lines
Editor.edit_value_help = edit_value_help


def main():
    args = [a for a in sys.argv[1:] if a != '--line']
    forced_line = '--line' in sys.argv[1:]
    if len(args) > 1 or (args and args[0] in ('-h', '--help')):
        print('usage: edit_options.py [--line] [<project>]   (%s)' % ' | '.join(PROJECTS))
        return 1
    project = args[0] if args else None
    if project is None and sys.stdin.isatty() and not forced_line:
        # the dialog can prompt for it before any terminal work: a plain input()
        try:
            line = input('project (%s): ' % ' | '.join(PROJECTS)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        project = line if line in PROJECTS else None
        if project is None:
            print('err one of: %s' % ', '.join(PROJECTS))
            return 1
    try:
        editor = Editor(project)
    except (OSError, ValueError) as e:
        print('edit_options.py: %s' % e)
        return 1
    if forced_line or not sys.stdin.isatty():
        if readline:
            readline.set_completer(LineCompleter(editor).complete)
            readline.set_completer_delims(' \t')
            if 'libedit' in (readline.__doc__ or ''):
                readline.parse_and_bind('bind ^I rl_complete')   # macOS libedit
            else:
                readline.parse_and_bind('tab: complete')
        code = line_mode(editor)
    else:
        dialog_wrapper(editor)
        code = 0
    exit_lint(editor)
    return code


def exit_lint(editor):
    """The exit hygiene: one lint pass on the way out — the nits report,
    and the canonical re-render when the file drifted (the row-splices
    keep their surroundings; this is the belt's suspenders)."""
    nits, canon = lint(editor.path)
    for nit in nits:
        print(nit)
    if canon is not None and canon != open(editor.path, encoding='utf-8').read():
        with open(editor.path, 'w', encoding='utf-8') as f:
            f.write(canon)
        print('lint: %s reformatted on exit' % os.path.basename(editor.path))


class LineCompleter:
    """The line-mode TAB completion: the knob names at the index prompt, the
    field commands at the row prompt (the editor flips the pool by state)."""

    def __init__(self, editor):
        self.editor = editor
        self.row_mode = False

    def complete(self, text, state):
        if self.row_mode:
            pool = list(EDITABLE) + ['save', 'cancel', 'show', 'quit']
        else:
            pool = [r['name'] for r in self.editor.rows] + ['list', 'quit']
        matches = [w for w in pool if w.startswith(text.lower())]
        return matches[state] if state < len(matches) else None


if __name__ == '__main__':
    sys.exit(main())
