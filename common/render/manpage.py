#!/usr/bin/env python3
"""The man-page builder shared by the family (the `--man` item in
docs/TODO.md): the pages are GENERATED, not hand-edited — the OPTIONS
section renders from the tool's argparse parser (the flags and their help
live once, so `--help` and the man page can never drift), the prose
sections are roff text kept next to the tool, and `--man` prints the page
to stdout (`modbus-cache --man | man -l -` works in a container with no man
pages installed). dev/generators/man.py regenerates the shipped man/*.1 files
from the same builders. Stdlib only.

The family's one section ladder per page class (the LADDERS table): a
daemon page carries SIGNALS, CONTROL, SECURITY, ENVIRONMENT, FILES,
EXIT STATUS (in that order) after OPTIONS, a ctl page EXAMPLES,
ENVIRONMENT, EXIT STATUS, a cli page ENVIRONMENT, EXIT STATUS —
page(kind=...) asserts the page conforms, so a missing, extra or
misordered section fails the build instead of shipping."""
import textwrap

LADDERS = {
    'daemon': ('SIGNALS', 'CONTROL', 'SECURITY', 'ENVIRONMENT', 'FILES',
               'EXIT STATUS'),
    'ctl': ('EXAMPLES', 'ENVIRONMENT', 'EXIT STATUS'),
    'cli': ('ENVIRONMENT', 'EXIT STATUS'),
}


def esc(text):
    """The one roff escape that matters for help-derived prose: the literal
    hyphen ('\\-' — a plain '-' may render as the typographic dash)."""
    return text.replace('-', '\\-')


# the EXIT STATUS blocks, verbatim across the four tools' pages (the
# per-tool man.py files splice them into their ctl/cli/daemon pages)
EXIT_STATUS_DAEMON = """.SH EXIT STATUS
.TP
.B 0
success (\\fB--dry-run\\fR: valid configuration).
.TP
.B 1
invalid configuration or a failed bind (reason on stderr).
.TP
.B 2
command-line misuse."""

EXIT_STATUS_CTL = """.SH EXIT STATUS
.TP
.B 0
every command answered \\fBok\\fR.
.TP
.B 1
connection or control error.
.TP
.B 2
command-line misuse."""

EXIT_STATUS_CLI = """.SH EXIT STATUS
.TP
.B 0
the session ended cleanly.
.TP
.B 1
connection or control error.
.TP
.B 2
command-line misuse."""


def wrap(text, width=72):
    """The roff body re-flows, so a hard wrap is pure formatting: keep the
    generated pages under the 80-column lint the hand-written pages hold.
    A wrapped line that would start with the roff control character (a
    leading '.' or ''') takes the \\& no-control prefix — a wrapped
    sentence must not grow a macro."""
    out = []
    for line in textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False):
        if line[0] in ('.', "'"):
            line = '\\&' + line
        out.append(line)
    return '\n'.join(out)


def _flag_str(action):
    """'.BI \\-\\-flag " TYPE"' / '.B \\-\\-flag' / the positional form."""
    opts = [o.replace('-', '\\-') for o in action.option_strings]
    if not opts:
        return '.B %s' % action.dest
    flag = opts[0] if len(opts) == 1 else ', '.join(opts)
    if action.nargs == 0 or action.type is None:
        return '.B %s' % flag
    shape = getattr(action.type, '__name__', 'VAL')
    if shape in ('int', 'float'):
        shape = 'N'
    elif shape == 'str':
        shape = 'VAL'
    return '.BI %s " %s"' % (flag, shape)


def options_section(parser, skip=('-h', '--help', '--man')):
    """The .SH OPTIONS blocks from the argparse parser: one .TP per action,
    the help text as-is (the help strings carry no defaults — the READMEs
    are the defaults reference). Returns the roff
    text (the caller embeds it after .SH OPTIONS — usually straight from
    this function, which emits the heading itself)."""
    lines = ['.SH OPTIONS']
    for a in parser._actions:
        if any(o in skip for o in a.option_strings) or a.dest in ('help', 'man'):
            continue
        help_text = a.help or ''
        lines.append('.TP')
        lines.append(_flag_str(a))
        if help_text:
            lines.append(wrap(esc(help_text)))
    return '\n'.join(lines) + '\n'


def page(name_tail, name, section, date, source, manual, synopsis, description,
         options, extra_sections=(), see_also=None, kind=None):
    """The whole roff page: .TH, .SH NAME (the name + the name_tail one-liner),
    .SH SYNOPSIS, .SH DESCRIPTION, the .SH OPTIONS blocks (from
    options_section), the extra .SH sections (raw roff pieces), .SH SEE ALSO.
    kind ('daemon' | 'ctl' | 'cli') gates the page against its LADDERS entry:
    every extra section must open with .SH and the whole set must match the
    class ladder exactly (the family's one shape; prose stays per-tool, the
    ladder does not)."""
    heads = []
    for piece in extra_sections:
        head = piece.split('\n', 1)[0]
        if not head.startswith('.SH '):
            raise ValueError('%s: an extra section must open with .SH, got %r'
                             % (name, head[:40]))
        heads.append(head[4:].strip())
    if kind is not None and tuple(heads) != LADDERS[kind]:
        raise ValueError('%s: the %s page carries %s, the ladder is %s'
                         % (name, kind, ', '.join(heads) or 'no sections',
                            ', '.join(LADDERS[kind])))
    out = [
        '.TH %s %s "%s" "%s" "%s"' % (name.upper(), section, date, source, manual),
        '.SH NAME',
        wrap('%s \\- %s' % (name, name_tail)),
        '.SH SYNOPSIS',
        synopsis,
        '',
        '.SH DESCRIPTION',
        description,
        '',
        options,
        '',
    ]
    for piece in extra_sections:
        out.append(piece)
        out.append('')
    if see_also:
        out.append('.SH SEE ALSO')
        out.append(see_also)
    return '\n'.join(out).rstrip('\n') + '\n'
