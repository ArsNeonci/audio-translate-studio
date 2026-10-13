"""A small JSON Schema checker (standard library only) for the contract tests.

Supports the subset the contracts use: type (a name or a list, "integer" excludes booleans), required, properties,
additionalProperties (false or a schema), items, enum, const, minimum, minLength, pattern, anyOf and $ref to
"#/components/schemas/<name>". Unknown keywords are ignored. Returns a list of error strings; empty means valid.
"""
import re

TYPES = {
    'object': lambda v: isinstance(v, dict),
    'array': lambda v: isinstance(v, list),
    'string': lambda v: isinstance(v, str),
    'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
    'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    'boolean': lambda v: isinstance(v, bool),
    'null': lambda v: v is None,
}


def check(value, schema, spec, path='$'):
    if '$ref' in schema:
        name = schema['$ref'].rsplit('/', 1)[-1]
        return check(value, spec['components']['schemas'][name], spec, path)
    if 'anyOf' in schema:
        attempts = [check(value, option, spec, path) for option in schema['anyOf']]
        return [] if any(not errors for errors in attempts) else [f'{path}: matches no anyOf option (' + '; '.join(errors[0] for errors in attempts) + ')']
    errors = []
    kind = schema.get('type')
    if kind is not None:
        kinds = kind if isinstance(kind, list) else [kind]
        if not any(TYPES[k](value) for k in kinds):
            return [f'{path}: expected {"/".join(kinds)}, got {type(value).__name__}']
    if 'const' in schema and value != schema['const']: errors.append(f'{path}: expected {schema["const"]!r}, got {value!r}')
    if 'enum' in schema and value not in schema['enum']: errors.append(f'{path}: {value!r} not in {schema["enum"]}')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0): errors.append(f'{path}: shorter than {schema["minLength"]}')
        if 'pattern' in schema and not re.search(schema['pattern'], value): errors.append(f'{path}: {value!r} does not match {schema["pattern"]}')
    if TYPES['number'](value) and 'minimum' in schema and value < schema['minimum']: errors.append(f'{path}: below {schema["minimum"]}')
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value: errors.append(f'{path}: missing {key!r}')
        properties = schema.get('properties', {})
        extra = schema.get('additionalProperties', True)
        for key, item in value.items():
            if key in properties: errors += check(item, properties[key], spec, f'{path}.{key}')
            elif extra is False: errors.append(f'{path}: unexpected {key!r}')
            elif isinstance(extra, dict): errors += check(item, extra, spec, f'{path}.{key}')
    if isinstance(value, list) and 'items' in schema:
        for index, item in enumerate(value): errors += check(item, schema['items'], spec, f'{path}[{index}]')
    return errors
