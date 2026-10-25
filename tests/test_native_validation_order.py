"""Native format ordering conserves validation and avoids duplicate tree walks."""
from copy import deepcopy

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import native_documents, sermons


def row():
    return {
        "work_id": "sample-work", "textual_form_id": "sample-form",
        "edition_id": "sample-edition", "record_id": "sample-record", "sequence": 1,
        "language": "en", "text": "Sample text", "representation_revision": "1",
        "provenance": {"edition_title": "Sample"}, "category": "sermons",
        "content_format": "ocd-native-content-v1",
        "locator": {"kind": "native-unit", "text_part": "body", "unit": 1},
        "structure": [{"kind": "division", "attributes": {}, "content": [
            {"kind": "paragraph", "attributes": {}, "content": [{"kind": "text", "text": "Sample text"}]}
        ]}],
    }


def test_native_format_order_keeps_both_complete_schema_branches(monkeypatch):
    schema, validator = sermons._schema()
    calls = []

    class ObservedValidator:
        def iter_errors(self, value):
            calls.append("original")
            return validator.iter_errors(value)

    class ObservedValidatorForNative:
        def __init__(self, current):
            self.current = current

        def iter_errors(self, value):
            calls.append("native-first")
            return self.current.iter_errors(value)

    original_schema = sermons._schema

    def observed_schema(*, native_first=False):
        current_schema, current = original_schema(native_first=native_first)
        assert current_schema == schema
        if native_first:
            assert current.schema == {**schema, "oneOf": list(reversed(schema["oneOf"]))}
            return schema, ObservedValidatorForNative(current)
        return schema, ObservedValidator()

    monkeypatch.setattr(sermons, "_schema", observed_schema)
    native_documents._validate_rows([row()], "sermons")
    assert calls == ["native-first"]


@pytest.mark.parametrize("mutation", ["unknown-kind", "extra-key", "empty-text", "missing-attributes", "speaker", "apparatus", "bad-locator"])
def test_native_format_order_preserves_rejection_and_original_error(mutation):
    value = deepcopy(row())
    structure = value["structure"][0]
    if mutation == "unknown-kind":
        structure["kind"] = "invented"
    elif mutation == "extra-key":
        structure["extra"] = True
    elif mutation == "empty-text":
        structure["content"][0]["content"][0]["text"] = ""
    elif mutation == "missing-attributes":
        del structure["attributes"]
    elif mutation == "speaker":
        structure["kind"] = "speech"
    elif mutation == "apparatus":
        structure["kind"] = "l812-apparatus"
    else:
        value["locator"]["unit"] = 0
    _, validator = sermons._schema()
    original = next(validator.iter_errors(value))
    with pytest.raises(PipelineError) as error:
        native_documents._validate_rows([value], "sermons")
    assert str(error.value) == "native sermon schema: " + original.message


def test_native_prose_tree_is_not_rewalked_by_python_schema_keywords():
    import cProfile
    from ocd_kernel.projection.categories import prose

    value = row()
    value['category'] = 'prose'
    paragraph = value['structure'][0]['content'][0]
    value['structure'][0]['content'] = [deepcopy(paragraph) for _ in range(100)]
    profile = cProfile.Profile()
    profile.runcall(prose._validate_prose_projection, {'rows': [value]})
    recursive_choices = sum(entry.callcount for entry in profile.getstats()
                            if not isinstance(entry.code, str)
                            and entry.code.co_name == 'oneOf'
                            and 'jsonschema' in entry.code.co_filename)
    assert recursive_choices < 20, f'{recursive_choices} Python schema alternatives for one native tree'


def test_native_sermon_tree_is_not_rewalked_after_schema_reordering():
    import cProfile

    value = row()
    paragraph = value['structure'][0]['content'][0]
    value['structure'][0]['content'] = [deepcopy(paragraph) for _ in range(100)]
    profile = cProfile.Profile()
    profile.runcall(native_documents._validate_rows, [value], 'sermons')
    choices = sum(entry.callcount for entry in profile.getstats()
                  if not isinstance(entry.code, str) and entry.code.co_name == 'oneOf'
                  and 'jsonschema' in entry.code.co_filename)
    assert choices < 20, f'{choices} Python schema alternatives after native schema reordering'
