#!/usr/bin/env python3
"""Human time formatting shared by the suite's control surfaces (stdlib only)."""


def secs(v):
    """Seconds as a human string: ms below a second, then s, m, h, d — one
    unit, always two decimal digits (90 -> '1.50m', 0.029 -> '29.00ms',
    0.0009 -> '0.90ms', 90000 -> '25.00h'). For the command reports and
    console output; the logs, the audit trail and the Prometheus endpoints
    keep raw seconds."""
    if v < 1:
        n, unit = v * 1000, 'ms'
    elif v < 60:
        n, unit = v, 's'
    elif v < 3600:
        n, unit = v / 60, 'm'
    elif v < 86400:
        n, unit = v / 3600, 'h'
    else:
        n, unit = v / 86400, 'd'
    return '%.2f%s' % (n, unit)
