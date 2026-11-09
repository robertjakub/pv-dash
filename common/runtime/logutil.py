"""Logging plumbing shared by the tools (stdlib only)."""
import logging
import time


class UtcFormatter(logging.Formatter):
    converter = staticmethod(time.gmtime)
