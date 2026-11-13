#!/usr/bin/env python3
"""Validate JSON documents against a JSON Schema file. Stdlib only.

  python3 scripts/validate_json.py SCHEMA [FILE|- ...]
  python3 scripts/validate_json.py shared/schema/modbus-cache-filter.schema.json extras/examples/modbus-cache-filter.json
  python3 scripts/validate_json.py scraper/schema/metrics.schema.json apps/scraper/examples/metrics.json
  python3 scripts/validate_json.py shared/schema/acl-write-registers.schema.json extras/examples/acl-write-registers.json
  cat doc.json | python3 scripts/validate_json.py shared/schema/acl-ip-prefix.schema.json -

The keyword set is the draft-2020-12 core the repo's schemas speak
(shared/schema/, apps/scraper/schema, apps/cache/schema): "type", "enum", "const", "properties",
"required", "additionalProperties", "patternProperties", "propertyNames",
"items" (both the mapping and the draft-07 tuple form), "minItems",
"maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "minimum",
"maximum", "exclusiveMinimum"/"exclusiveMaximum" (both the draft-04 boolean
and the numeric form), "multipleOf", "minProperties", "maxProperties",
"allOf", "anyOf", "oneOf", "not" and "$ref" — local "#/..." pointers only,
into "$defs" or "definitions" or wherever the pointer lands. Unknown
keywords are ignored per the spec; "$schema" is read and never refused. A
boolean is a schema (true: anything passes, false: nothing does). The
combinators report the losing candidates' own errors underneath theirs.

One document per file, "-" is stdin. Errors print per file, the instance
location as a JSON pointer. Exit 0 = every document validates, 1 = at
least one document failed (or would not parse), 2 = bad usage or the
schema file is unreadable/unusable.
"""
import json
import re
import sys
from urllib.parse import unquote


class SchemaError(Exception):
    """The schema (or a $ref into it) is unusable — reported as exit 2."""


def type_name(value):
    """The JSON type of a parsed value, the way "type" spells it."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    return 'object' if isinstance(value, dict) else 'array'


def check_type(name, value):
    """One "type" match — the JSON Schema rule that 1.0 is an integer."""
    if name == 'integer':
        return ((isinstance(value, int) and not isinstance(value, bool))
                or (isinstance(value, float) and value.is_integer()))
    if name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == 'string':
        return isinstance(value, str)
    if name == 'boolean':
        return isinstance(value, bool)
    if name == 'null':
        return value is None
    if name == 'object':
        return isinstance(value, dict)
    if name == 'array':
        return isinstance(value, list)
    raise SchemaError('unknown "type" %r' % name)


def same(a, b):
    """JSON equality — a boolean is never 1 (True == 1 in Python)."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def pointer_join(pointer, key):
    """One step deeper: the key escaped per the JSON pointer rules."""
    return '%s/%s' % (pointer, str(key).replace('~', '~0').replace('/', '~1'))


def resolve_ref(root, ref):
    """A local '#/...' reference into the schema document ('#' is the root)."""
    if not ref.startswith('#'):
        raise SchemaError('only local "#/..." $refs are supported (not %r)' % ref)
    node = root
    for token in ref[1:].split('/'):
        if not token:
            continue
        token = unquote(token).replace('~1', '/').replace('~0', '~')
        if isinstance(node, list):
            try:
                node = node[int(token)]
            except (ValueError, IndexError):
                raise SchemaError('the $ref %r does not resolve' % ref)
        elif isinstance(node, dict):
            if token not in node:
                raise SchemaError('the $ref %r does not resolve' % ref)
            node = node[token]
        else:
            raise SchemaError('the $ref %r walks into a scalar' % ref)
    return node


def pattern_hits(pattern, text):
    """re.search with the schema's pattern; a bad pattern is a schema nit."""
    try:
        return re.search(pattern, text) is not None
    except re.error as e:
        raise SchemaError('the "pattern" %r does not compile: %s' % (pattern, e))


def validate(value, schema, pointer, root, errors, stack=()):
    """One schema against one value; the errors append as (pointer, message).
    A "type" miss stops that schema's remaining keywords — the rest read
    nonsense against a value of the wrong shape."""
    if schema is True:
        return
    if schema is False:
        errors.append((pointer, 'the schema refuses every value here'))
        return
    if not isinstance(schema, dict):
        raise SchemaError('a schema that is neither an object nor a boolean')
    mark = (id(schema), pointer)
    if mark in stack:
        raise SchemaError('a circular $ref at %s' % (pointer or '/'))
    stack = stack + (mark,)

    if schema.get('$ref') is not None:
        validate(value, resolve_ref(root, schema['$ref']), pointer, root, errors, stack)

    t = schema.get('type')
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(check_type(n, value) for n in names):
            errors.append((pointer, 'expected %s, got %s'
                           % (' or '.join('"%s"' % n for n in names), type_name(value))))
            return

    if 'const' in schema and not same(value, schema['const']):
        errors.append((pointer, '%s is not the constant %s'
                       % (json.dumps(value), json.dumps(schema['const']))))
    vals = schema.get('enum')
    if isinstance(vals, list) and not any(same(value, v) for v in vals):
        errors.append((pointer, '%s is not one of %s'
                       % (json.dumps(value), json.dumps(vals))))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get('minimum')
        maximum = schema.get('maximum')
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append((pointer, '%s is below the minimum %s' % (value, minimum)))
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append((pointer, '%s is above the maximum %s' % (value, maximum)))
        for key, ok in (('exclusiveMinimum', lambda v, b: v > b),
                        ('exclusiveMaximum', lambda v, b: v < b)):
            excl = schema.get(key)
            if isinstance(excl, bool):        # the draft-04 modifier on minimum/maximum
                base = minimum if key == 'exclusiveMinimum' else maximum
                if excl and isinstance(base, (int, float)) and not ok(value, base):
                    errors.append((pointer, '%s must be %s %s (%s)'
                                   % (value, 'above' if key == 'exclusiveMinimum' else 'below',
                                      base, key)))
            elif isinstance(excl, (int, float)) and not ok(value, excl):
                errors.append((pointer, '%s breaks %s %s' % (value, key, excl)))
        mult = schema.get('multipleOf')
        if isinstance(mult, (int, float)) and mult > 0:
            q = value / mult
            if abs(q - round(q)) > 1e-9:
                errors.append((pointer, '%s is not a multiple of %s' % (value, mult)))

    if isinstance(value, str):
        for key, op in (('minLength', lambda n, b: n < b), ('maxLength', lambda n, b: n > b)):
            bound = schema.get(key)
            if isinstance(bound, int) and op(len(value), bound):
                errors.append((pointer, 'the %d-character string breaks %s %d'
                               % (len(value), key, bound)))
        pattern = schema.get('pattern')
        if isinstance(pattern, str) and not pattern_hits(pattern, value):
            errors.append((pointer, '%s does not match the pattern %r'
                           % (json.dumps(value), pattern)))

    if isinstance(value, list):
        for key, op in (('minItems', lambda n, b: n < b), ('maxItems', lambda n, b: n > b)):
            bound = schema.get(key)
            if isinstance(bound, int) and op(len(value), bound):
                errors.append((pointer, 'the %d-item array breaks %s %d'
                               % (len(value), key, bound)))
        items = schema.get('items')
        if isinstance(items, list):           # the draft-07 tuple form
            for i, sub in enumerate(items):
                if i < len(value):
                    validate(value[i], sub, pointer_join(pointer, i), root, errors, stack)
        elif items is not None:
            for i, item in enumerate(value):
                validate(item, items, pointer_join(pointer, i), root, errors, stack)
        if schema.get('uniqueItems') is True:
            for i in range(len(value)):
                if any(same(value[i], value[j]) for j in range(i + 1, len(value))):
                    errors.append((pointer_join(pointer, i), 'repeats an earlier item (uniqueItems)'))
                    break

    if isinstance(value, dict):
        for key, op in (('minProperties', lambda n, b: n < b), ('maxProperties', lambda n, b: n > b)):
            bound = schema.get(key)
            if isinstance(bound, int) and op(len(value), bound):
                errors.append((pointer, 'the %d-key object breaks %s %d'
                               % (len(value), key, bound)))
        for key in schema.get('required') or []:
            if isinstance(key, str) and key not in value:
                errors.append((pointer, 'the required key %r is missing' % key))
        props = schema.get('properties')
        patterns = schema.get('patternProperties')
        names = schema.get('propertyNames')
        for key, item in value.items():
            here = pointer_join(pointer, key)
            if names is not None:
                key_errors = []
                validate(key, names, here, root, key_errors, stack)
                errors.extend(key_errors)
            sub = props.get(key) if isinstance(props, dict) else None
            if sub is None and isinstance(patterns, dict):
                for pat, psub in patterns.items():
                    if pattern_hits(pat, key):
                        sub = psub
                        break
            if sub is not None:
                validate(item, sub, here, root, errors, stack)
        extra = schema.get('additionalProperties')
        if extra is not None:
            for key, item in value.items():
                if isinstance(props, dict) and key in props:
                    continue
                if isinstance(patterns, dict) and any(pattern_hits(p, key) for p in patterns):
                    continue
                here = pointer_join(pointer, key)
                if extra is False:
                    errors.append((here, 'the key %r is not allowed here' % key))
                else:
                    validate(item, extra, here, root, errors, stack)

    for key in ('allOf', 'anyOf', 'oneOf'):
        subs = schema.get(key)
        if not isinstance(subs, list):
            continue
        tries = []
        for sub in subs:
            sub_errors = []
            validate(value, sub, pointer, root, sub_errors, stack)
            tries.append(sub_errors)
        good = [i for i, sub_errors in enumerate(tries) if not sub_errors]
        if key == 'allOf':
            for i, sub_errors in enumerate(tries):
                for p, msg in sub_errors:
                    errors.append((p, 'allOf[%d]: %s' % (i, msg)))
            continue
        if key == 'anyOf' and not good:
            errors.append((pointer, 'matched none of the %d anyOf schemas' % len(subs)))
        if key == 'oneOf':
            if not good:
                errors.append((pointer, 'matched none of the %d oneOf schemas' % len(subs)))
            elif len(good) > 1:
                errors.append((pointer, 'matched %d of the oneOf schemas (%s), expected exactly one'
                               % (len(good), ', '.join('oneOf[%d]' % i for i in good))))
        if not good:                          # the losers' own errors, underneath
            for i, sub_errors in enumerate(tries):
                for p, msg in sub_errors:
                    errors.append((p, '%s[%d]: %s' % (key, i, msg)))

    if schema.get('not') is not None:
        sub_errors = []
        validate(value, schema['not'], pointer, root, sub_errors, stack)
        if not sub_errors:
            errors.append((pointer, 'the schema under "not" matched'))


def load_json(path):
    """One parsed document: ('doc', value) or ('error', message)."""
    try:
        if path == '-':
            return 'doc', json.load(sys.stdin)
        with open(path, encoding='utf-8') as f:
            return 'doc', json.load(f)
    except (OSError, ValueError) as e:
        return 'error', '%s: unreadable or does not parse: %s' % (path, e)


COMBINATOR_TAG = re.compile(r'^(?:oneOf|anyOf|allOf)\[\d+\]: ')


def core_message(msg):
    """The message with the candidate tags ('oneOf[0]: ') stripped: candidates
    that $ref one subschema report the same leaf failure under several tags,
    and the print dedupes on the core, so it shows once."""
    while True:
        stripped = COMBINATOR_TAG.sub('', msg, count=1)
        if stripped == msg:
            return msg
        msg = stripped


def main(argv):
    args = list(argv)
    if '-h' in args or '--help' in args:
        print(__doc__.strip())
        return 0
    quiet = '-q' in args or '--quiet' in args
    args = [a for a in args if a not in ('-q', '--quiet')]
    if len(args) < 2:
        print('usage: validate_json.py [-q] SCHEMA [FILE|- ...]', file=sys.stderr)
        return 2
    schema_path, doc_paths = args[0], args[1:]
    kind, loaded = load_json(schema_path)
    if kind == 'error':
        print(loaded.replace(': unreadable', ': the schema is unreadable'))
        return 2
    schema = loaded
    bad = False
    for path in doc_paths:
        kind, loaded = load_json(path)
        if kind == 'error':
            print(loaded)
            bad = True
            continue
        errors = []
        try:
            validate(loaded, schema, '', schema, errors)
        except SchemaError as e:
            print('%s: the schema does not apply: %s' % (path, e))
            bad = True
            continue
        if errors:
            bad = True
            seen = set()
            for p, msg in errors:
                core = core_message(msg)
                if (p, core) in seen:
                    continue
                seen.add((p, core))
                print('%s%s: %s' % (path, ': ' + p if p else '', core))
        elif not quiet:
            print('%s: ok' % path)
        elif not quiet:
            print('%s: ok' % path)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
