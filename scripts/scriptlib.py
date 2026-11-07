#!/usr/bin/env python3
"""Helpers shared by the registry-editing scripts (edit_options, set_group,
set_live): the surgical row-locator and the live-name rule. Stdlib only."""
import json
import re


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
