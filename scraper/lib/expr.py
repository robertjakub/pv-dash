"""The compute-expression mini-evaluator (stdlib only).

The metrics spec's `compute` entries carry their formula as an "expr"
string over the poller's inputs (pv, grid, batt, soc, battery and every
profile-bound metric key); an optional "when" string gates the metric's
presence the same way. Expressions are compiled once at startup into a
closure tree and evaluated per poll.

The grammar is a whitelist: numeric literals, the input names, + - * / //
% **, comparisons (chainable), and/or/not, the ternary and abs/min/max/round
— nothing else (no attributes, no subscripts, no comprehensions, no calls
beyond the four). Anything else is a compile-time ExprError; the metrics
loader turns it into a startup SystemExit. At evaluation time an
unavailable input, a division by zero or a non-finite result raise
ExprAbsent — the metric stays absent for that cycle instead of lying.
"""
import ast
import math
import operator


class ExprError(ValueError):
    """A compile-time expression problem (bad syntax, a forbidden node, a
    shape the whitelist refuses) — fatal at spec load, never at poll time."""


class ExprAbsent(Exception):
    """An evaluation-time absence: an input the poll could not provide or a
    result no gauge should export — the metric stays absent for the cycle."""


def _pow(a, b):
    # a huge exponent computes before any isfinite check can see it
    if abs(b) > 100:
        raise ExprAbsent('** exponent out of range: %r' % b)
    return a ** b


_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
           ast.Mod: operator.mod, ast.Pow: _pow}
_CMPOPS = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
           ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCS = {'abs': (1, 1), 'min': (1, 8), 'max': (1, 8), 'round': (1, 2)}
_GRAMMAR = ('numbers, the inputs, + - * / // % **, comparisons, and/or/not, '
            'the ternary and abs/min/max/round')


def compile_expr(text, what='expression'):
    """Parse + whitelist one expression: (fn, names) — fn(inputs) evaluates,
    names collects the referenced inputs (the loader checks them against
    the available universe)."""
    try:
        tree = ast.parse(text, mode='eval')
    except (SyntaxError, ValueError) as e:
        raise ExprError('%s: cannot parse %r (%s)' % (what, text, e)) from None
    names = set()
    fn = _build(tree.body, what, names)
    return fn, names


def evaluate(fn, inputs):
    """One evaluation: a finite float, or ExprAbsent (an unavailable input,
    a division by zero, overflow, a non-finite result)."""
    value = fn(inputs)
    value = float(value)
    if not math.isfinite(value):
        raise ExprAbsent('non-finite result')
    return value


def _build(node, what, names):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            value = float(node.value)
        elif isinstance(node.value, (int, float)):
            value = float(node.value)
        else:
            raise ExprError('%s: %r — %s' % (what, node.value, _GRAMMAR))
        return lambda inputs: value

    if isinstance(node, ast.Name):
        names.add(node.id)
        key = node.id
        def fn(inputs, _key=key):
            try:
                return inputs[_key]
            except KeyError:
                raise ExprAbsent('input %r is not available this poll' % _key) from None
        return fn

    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            raise ExprError('%s: operator %r — %s' % (what, type(node.op).__name__, _GRAMMAR))
        left, right, op = _build(node.left, what, names), _build(node.right, what, names), _BINOPS[type(node.op)]
        return lambda inputs, _l=left, _r=right, _op=op: _op(_l(inputs), _r(inputs))

    if isinstance(node, ast.UnaryOp):
        operand = _build(node.operand, what, names)
        if isinstance(node.op, ast.USub):
            return lambda inputs, _v=operand: -_v(inputs)
        if isinstance(node.op, ast.UAdd):
            return lambda inputs, _v=operand: +_v(inputs)
        if isinstance(node.op, ast.Not):
            return lambda inputs, _v=operand: not _v(inputs)
        raise ExprError('%s: operator %r — %s' % (what, type(node.op).__name__, _GRAMMAR))

    if isinstance(node, ast.BoolOp):       # and/or: lazy — `battery and batt` with battery 0 never misses batt
        parts = [_build(v, what, names) for v in node.values]
        is_and = isinstance(node.op, ast.And)
        def fn(inputs, _parts=parts, _and=is_and):
            value = _parts[0](inputs)
            for part in _parts[1:]:
                if bool(value) != _and:
                    return value
                value = part(inputs)
            return value
        return fn

    if isinstance(node, ast.Compare):
        left = _build(node.left, what, names)
        pairs = [(_CMPOPS[type(op)], _build(c, what, names))
                 for op, c in zip(node.ops, node.comparators)]
        def fn(inputs, _l=left, _pairs=pairs):
            value = _l(inputs)
            for op, comp in _pairs:
                rhs = comp(inputs)
                if not op(value, rhs):
                    return False
                value = rhs
            return True
        return fn

    if isinstance(node, ast.IfExp):        # the ternary: lazy — the untaken branch never misses an input
        test, body, orelse = (_build(node.test, what, names), _build(node.body, what, names),
                              _build(node.orelse, what, names))
        return lambda inputs, _t=test, _b=body, _o=orelse: _b(inputs) if _t(inputs) else _o(inputs)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ExprError('%s: calls are limited to %s' % (what, ', '.join(sorted(_FUNCS))))
        if node.keywords:
            raise ExprError('%s: keyword arguments are not allowed' % what)
        low, high = _FUNCS[node.func.id]
        if not low <= len(node.args) <= high:
            raise ExprError('%s: %s() takes %d..%d arguments, got %d'
                            % (what, node.func.id, low, high, len(node.args)))
        args = [_build(a, what, names) for a in node.args]
        name = node.func.id
        def fn(inputs, _name=name, _args=args):
            values = [a(inputs) for a in _args]
            return {'abs': abs, 'min': min, 'max': max, 'round': round}[_name](*values)
        return fn

    raise ExprError('%s: %s is not allowed — %s'
                    % (what, type(node).__name__, _GRAMMAR))
