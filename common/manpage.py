#!/usr/bin/env python3
"""The man-page builder shared by the family (the `--man` item in
docs/TODO.md): the pages are GENERATED, not hand-edited — the OPTIONS
section renders from the tool's argparse parser (the flags and their help
live once, so `--help` and the man page can never drift), the prose
sections are roff text kept next to the tool, and `--man` prints the page
to stdout (`modbus-cache --man | man -l -` works in a container with no man
pages installed). scripts/gen_man.py regenerates the shipped man/*.1 files
from the same builders. Stdlib only."""
import argparse
import textwrap


def esc(text):
    """The one roff escape that matters for help-derived prose: the literal
    hyphen ('\\-' — a plain '-' may render as the typographic dash)."""
    return text.replace('-', '\\-')


def wrap(text, width=72):
    """The roff body re-flows, so a hard wrap is pure formatting: keep the
    generated pages under the 80-column lint the hand-written pages hold."""
    return '\n'.join(textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False))


def _fmt_default(action):
    """The rendered default of an argparse action for the help text."""
    d = action.default
    if d is argparse.SUPPRESS or d is None:
        return None
    if d is True:
        return 'on'
    if d is False:
        return 'off'
    return str(d)


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
    the help text with the %(default)s interpolations applied (the repo's
    help strings carry them), the default named where set. Returns the roff
    text (the caller embeds it after .SH OPTIONS — usually straight from
    this function, which emits the heading itself)."""
    lines = ['.SH OPTIONS']
    for a in parser._actions:
        if any(o in skip for o in a.option_strings) or a.dest in ('help', 'man'):
            continue
        help_text = a.help or ''
        if '%(default)' in help_text:
            d = _fmt_default(a)
            help_text = help_text.replace('%(default)s', d if d is not None else 'none') \
                                  .replace('%(default)r', repr(a.default))
        else:
            d = _fmt_default(a)
            if d is not None:
                help_text = '%s (default: %s)' % (help_text, d)
        lines.append('.TP')
        lines.append(_flag_str(a))
        if help_text:
            lines.append(wrap(esc(help_text)))
    return '\n'.join(lines) + '\n'


def page(name_tail, name, section, date, source, manual, synopsis, description,
         options, extra_sections=(), see_also=None):
    """The whole roff page: .TH, .SH NAME (the name + the name_tail one-liner),
    .SH SYNOPSIS, .SH DESCRIPTION, the .SH OPTIONS blocks (from
    options_section), the extra .SH sections (raw roff pieces), .SH SEE ALSO."""
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
