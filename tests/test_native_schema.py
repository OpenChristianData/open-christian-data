"""Complete native schemas keep the original validity and error behavior."""
from copy import deepcopy
import json
from pathlib import Path
import random

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.projection.native_content_check import native_content_errors, projection_validator
from tests.test_native_validation_order import row

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'schemas/v2/native-content.schema.json').read_bytes())


def signature(errors):
    return [(error.message, list(error.path), list(error.schema_path)) for error in errors]


def native_cases():
    values = [None, True, False, 0, 1.5, '', [], {}, {'kind': 'text', 'text': 'Text'}]
    for kind in SCHEMA['oneOf'][1]['properties']['kind']['enum']:
        values.append({'kind': kind, 'attributes': {}, 'content': []})
    base = row()['structure'][0]
    values.extend([base, {'kind': 'speech', 'attributes': {}, 'content': [
        {'kind': 'speaker', 'attributes': {}, 'content': [{'kind': 'text', 'text': 'Paul'}]}]}])
    rng = random.Random(20261025)
    replacements = [None, True, False, 0, -1, '', 'invalid', [], {}, ['unexpected']]
    for _ in range(300):
        value = deepcopy(base)
        target = rng.choice([value, value['content'][0], value['content'][0]['content'][0]])
        key = rng.choice(['kind', 'attributes', 'content', 'text', 'unexpected'])
        if rng.randrange(4) == 0:
            target.pop(key, None)
        else:
            target[key] = deepcopy(rng.choice(replacements))
        values.append(value)
    return values


@pytest.mark.parametrize('value', native_cases())
def test_complete_native_schema_has_identical_validity_and_diagnostics(value):
    original = signature(jsonschema.Draft202012Validator(SCHEMA).iter_errors(value))
    assert signature(native_content_errors(SCHEMA, value)) == original


@pytest.mark.parametrize('mutation', ['changed-kind', 'missing-content', 'additional-property', 'speaker', 'apparatus', 'wrong-locator', 'wrong-category'])
def test_category_schema_keeps_exact_error_paths_and_messages(mutation):
    common = json.loads((ROOT / 'schemas/v2/public-row.schema.json').read_bytes())
    schema = json.loads((ROOT / 'schemas/v2/categories/prose.schema.json').read_bytes())
    registry = Registry().with_resources((value['$id'], Resource.from_contents(value, default_specification=DRAFT202012))
                                         for value in (common, SCHEMA))
    original = jsonschema.Draft202012Validator(schema, registry=registry)
    optimized = projection_validator(schema, registry=registry)
    value = row()
    value['category'] = 'prose'
    node = value['structure'][0]
    if mutation == 'changed-kind': node['kind'] = 'invented'
    elif mutation == 'missing-content': del node['content']
    elif mutation == 'additional-property': node['unexpected'] = True
    elif mutation == 'speaker': node['kind'] = 'speech'
    elif mutation == 'apparatus': node['kind'] = 'l812-apparatus'
    elif mutation == 'wrong-locator': value['locator']['unit'] = 0
    else: value['category'] = 'sermons'
    errors = signature(original.iter_errors(value))
    assert errors
    assert signature(optimized.iter_errors(value)) == errors


def test_fresh_schema_content_changes_the_compiled_validator():
    value = {'kind': 'text', 'text': 'Text'}
    assert not list(native_content_errors(SCHEMA, value))
    changed = deepcopy(SCHEMA)
    changed['oneOf'][0]['properties']['text']['minLength'] = 10
    assert signature(native_content_errors(changed, value)) == signature(jsonschema.Draft202012Validator(changed).iter_errors(value))
    assert not list(native_content_errors(SCHEMA, value))


def test_unrelated_references_and_formats_keep_original_validation():
    resource = {'$id': 'ocd://fixture', 'type': 'string', 'format': 'date'}
    registry = Registry().with_resource(resource['$id'], Resource.from_contents(resource, default_specification=DRAFT202012))
    schema = {'$ref': resource['$id']}
    options = {'registry': registry, 'format_checker': jsonschema.FormatChecker()}
    original = jsonschema.Draft202012Validator(schema, **options)
    optimized = projection_validator(schema, **options)
    for value in ['2026-10-25', 'invalid', None, 0, True, {}, []]:
        assert signature(optimized.iter_errors(value)) == signature(original.iter_errors(value))
