"""Small draft-07 subset validator and immutable merge helpers (stdlib only)."""
import copy
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = ('brow_up_L brow_up_R brow_angry brow_sad lid_close_L lid_close_R '
              'lid_happy eye_wide eye_narrow mouth_open mouth_smile mouth_frown '
              'mouth_wide mouth_smirk_L mouth_smirk_R mouth_small').split()
EXPRESSIONS = 'neutral happy confident angry surprised sad smug battle'.split()


class SpecError(ValueError):
    pass


def deep_merge(spec, patch):
    """Objects merge recursively; arrays/scalars replace, without mutating inputs."""
    if not isinstance(spec, dict) or not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(spec)
    for key, value in patch.items():
        result[key] = deep_merge(result.get(key), value)
    return result


def validate_json(value, schema, path='$'):
    kinds = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
             'integer': int, 'number': (int, float), 'null': type(None)}
    kind = schema.get('type')
    if kind:
        options = kind if isinstance(kind, list) else [kind]
        valid = any(isinstance(value, kinds[k]) and
                    not (k in ('integer', 'number') and isinstance(value, bool))
                    for k in options)
        if not valid:
            raise SpecError(f'{path}: expected {kind}')
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise SpecError(f'{path}: must be finite')
        for name, op in [('minimum', lambda a, b: a < b), ('maximum', lambda a, b: a > b)]:
            if name in schema and op(value, schema[name]):
                raise SpecError(f'{path}: violates {name} {schema[name]}')
    if 'enum' in schema and value not in schema['enum']:
        raise SpecError(f'{path}: expected one of {schema["enum"]}')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 100000):
            raise SpecError(f'{path}: invalid string length')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise SpecError(f'{path}: invalid format')
    if isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 100000):
            raise SpecError(f'{path}: invalid item count')
        if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise SpecError(f'{path}: duplicate items')
        for i, item in enumerate(value):
            validate_json(item, schema.get('items', {}), f'{path}[{i}]')
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                raise SpecError(f'{path}: missing {key}')
        props = schema.get('properties', {})
        for key, item in value.items():
            if key in props:
                validate_json(item, props[key], f'{path}.{key}')
            elif schema.get('additionalProperties') is False:
                raise SpecError(f'{path}: unknown key {key}')
            elif isinstance(schema.get('additionalProperties'), dict):
                validate_json(item, schema['additionalProperties'], f'{path}.{key}')
    return value


def validate_spec(spec):
    schema = json.loads((ROOT / 'schema/character_spec.schema.json').read_text(encoding='utf-8'))
    validate_json(spec, schema)
    names = [c['name'] for c in spec['hair']['clumps']]
    if len(names) != len(set(names)):
        raise SpecError('$.hair.clumps: duplicate names')
    for clump in spec['hair']['clumps']:
        if sum(v * v for v in clump['dir']) < 1e-8:
            raise SpecError(f'$.hair.clumps.{clump["name"]}: dir must be nonzero')
    return spec


def load_spec(path):
    return validate_spec(json.loads(Path(path).read_text(encoding='utf-8-sig')))
