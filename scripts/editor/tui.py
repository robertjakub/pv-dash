#!/usr/bin/env python3
"""The registry editors' shared curses primitives (editor.py): the
ESC/^C key decoding, the drawing helpers and the input line — the
dialogs stay per-script, these never care what is on the screen. Stdlib only."""
import curses

INTR = -2   # the ^C speak: getch raises KeyboardInterrupt — the surfaces answer INTR, no traceback


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


def put(screen, y, x, text, attr=0):
    text = text[:curses.COLS - 1]
    screen.addstr(y, x, text, attr)


def fit(top, cursor, lines, height):
    if cursor < top:
        top = cursor
    if cursor >= top + height:
        top = cursor - height + 1
    return max(0, min(top, max(0, len(lines) - height)))


def frame(screen, title):
    screen.attron(curses.A_REVERSE)
    put(screen, 0, 0, ' ' + title)
    screen.attroff(curses.A_REVERSE)


def status(screen, msg, dim=False):
    put(screen, curses.LINES - 2, 0, (msg or '').ljust(curses.COLS - 1)[:curses.COLS - 1],
        curses.A_DIM if dim else 0)


def input_line(screen, prompt, initial=''):
    """The bottom input line: type, backspace, delete; the arrows move
    the (now visible) cursor, Home/End jump to the ends; Enter accepts,
    Esc or ^C returns None."""
    buf, pos = initial, len(initial)
    vis = False
    try:
        vis = bool(curses.curs_set(1))
    except curses.error:
        pass
    try:
        while True:
            put(screen, curses.LINES - 1, 0, (' ' + prompt + buf), curses.A_BOLD)
            screen.clrtoeol()   # a shorter buffer must not leave its tail on screen
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


def confirm(screen, word):
    """The y/n gate: ONE key — y acks, any other key (n, esc, ...)
    declines. No Enter."""
    put(screen, curses.LINES - 1, 0, ' %s? [y/N] ' % word, curses.A_BOLD)
    screen.clrtoeol()
    screen.refresh()
    yes = get_key(screen) in (ord('y'), ord('Y'))
    put(screen, curses.LINES - 1, 0, ' ' * (curses.COLS - 1))
    screen.clrtoeol()
    return yes
