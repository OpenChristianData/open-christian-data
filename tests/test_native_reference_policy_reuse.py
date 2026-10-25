"""Reference batches keep full checks without decoding the schema per reference."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from ocd_kernel.projection import native_content, native_content_check
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes


@pytest.mark.parametrize('independent', [False, True])
def test_reference_batch_reads_schema_at_most_twice(monkeypatch, independent):
    raw = ('<div xmlns="http://www.tei-c.org/ns/1.0"><p>' +
           '<ref cRef="John.3.16-18">John 3</ref>' * 50 + '</p></div>').encode()
    codes = load_book_codes(BOOK_CODES_PATH)
    source = native_content_check.SCHEMA if independent else native_content.SCHEMA
    reads = []
    for method in ['read_text', 'read_bytes']:
        original = getattr(Path, method)
        def record(path, *args, _original=original, **kwargs):
            if path == source:
                reads.append(path)
            return _original(path, *args, **kwargs)
        monkeypatch.setattr(Path, method, record)
    if independent:
        records = native_documents._observe_prose_references(etree.fromstring(raw), codes)
    else:
        records = native_documents._prose_references(ET.fromstring(raw), codes)
    assert len(records) == 50
    assert len(reads) <= 2, f'{len(reads)} schema reads for one reference batch'


@pytest.mark.parametrize('independent', [False, True])
def test_reference_batch_rejects_schema_drift(tmp_path, monkeypatch, independent):
    from ocd_kernel.library._common import PipelineError
    schema = tmp_path / 'schema.json'
    original = native_content.SCHEMA.read_bytes()
    schema.write_bytes(original)
    monkeypatch.setattr(native_content, 'SCHEMA', schema)
    monkeypatch.setattr(native_content_check, 'SCHEMA', schema)
    raw = b'<div xmlns="http://www.tei-c.org/ns/1.0"><ref cRef="John.3.16">John 3</ref></div>'
    codes = load_book_codes(BOOK_CODES_PATH)
    if independent:
        observed = native_documents.observe_content
        def change(*args, **kwargs):
            value = observed(*args, **kwargs)
            schema.write_bytes(original + b' ')
            return value
        monkeypatch.setattr(native_documents, 'observe_content', change)
        with pytest.raises(ValueError, match='schema changed during reference verification'):
            native_documents._observe_prose_references(etree.fromstring(raw), codes)
    else:
        project = native_content.project_content
        def change(*args, **kwargs):
            value = project(*args, **kwargs)
            schema.write_bytes(original + b' ')
            return value
        monkeypatch.setattr(native_content, 'project_content', change)
        with pytest.raises(PipelineError, match='schema changed during reference projection'):
            native_documents._prose_references(ET.fromstring(raw), codes)


def test_source_profile_extensions_do_not_mutate_shared_batch_policy():
    from copy import deepcopy
    schema = json.loads(native_content.SCHEMA.read_bytes())
    before = deepcopy(schema)
    raw = b'<ref xmlns="http://www.tei-c.org/ns/1.0" cRef="John.3.16">John 3</ref>'
    for _ in range(2):
        content = native_content.project_content(ET.fromstring(raw), source_profile=native_content.SOURCE_LINES_PROFILE,
                                                 _policy=schema['x-ocd-native-content'])
        assert native_content.readable_content(content, _policy=schema['x-ocd-native-content']) == 'John 3'
        observed, text = native_content_check.observe_content(raw, source_profile=native_content_check.SOURCE_LINES_PROFILE,
                                                              _schema=schema)
        assert observed == content and text == 'John 3'
        assert schema == before
