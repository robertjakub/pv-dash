#!/usr/bin/env python3
"""Helpers shared by the registry scripts (editor.py, set_group,
set_live, the lints): the surgical row-locator, the live-name rule and
the family order. Stdlib only."""
import json
import re

# the four tools, in the chain order the README tells: fake -> cache ->
# scraper, then the dashboard that renders the numbers
TOOLS = ('cache', 'scraper', 'inverter', 'dashboard')


def row_span(text, name):
    """The (start, end) char span of the option object with this name."""
    for m in re.finditer(r'"name"\s*:\s*"(.*?)"', text):
        if m.group(1) != name:
            continue
        brace = text.rfind('{', 0, m.start())
        while brace != -1:
            try:
                obj, end = json.JSONDecoder().raw_decode(text[brace:])
            except ValueError:
                obj, end = None, -1
            if isinstance(obj, dict) and obj.get('name') == name:
                return brace, brace + end
            brace = text.rfind('{', 0, brace)
    return None


def clean_path(text):
    """A live name is one clean word-path: every '/' segment a word."""
    return all(seg and not any(c.isspace() for c in seg) for seg in text.split('/'))
