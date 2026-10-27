"""Spurgeon reuses schema compilation and still validates every candidate document."""
from lxml import etree
import pytest
from build.tei import spurgeon_mtp_oracle as oracle
from build.lib.tei_xsd import compiled_tei_schema
from tests.test_tei_xsd import _write_schema_set


def test_spurgeon_reuses_compilation_and_rechecks_documents_and_schema_bytes(tmp_path, monkeypatch):
    paths = _write_schema_set(tmp_path)
    compilations, validations = [], []
    original = etree.XMLSchema

    def compile(*args, **kwargs):
        compilations.append(True)
        return original(*args, **kwargs)

    class Observed:
        def __init__(self, schema):
            self.schema = schema
        def validate(self, document):
            validations.append(document)
            return self.schema.validate(document)
        @property
        def error_log(self):
            return self.schema.error_log

    monkeypatch.setattr(etree, 'XMLSchema', compile)
    monkeypatch.setattr(oracle, 'compiled_tei_schema', lambda path: Observed(compiled_tei_schema(path)), raising=False)
    good = etree.ElementTree(etree.fromstring(b'<root xmlns="urn:main">text</root>'))
    bad = etree.ElementTree(etree.fromstring(b'<root xmlns="urn:main"><unexpected/></root>'))
    oracle._validate_tei_schema_document(good, paths['tei_all.xsd'])
    oracle._validate_tei_schema_document(good, paths['tei_all.xsd'])
    with pytest.raises(ValueError, match='Spurgeon TEI P5 validation failed'):
        oracle._validate_tei_schema_document(bad, paths['tei_all.xsd'])
    assert len(compilations) == 1
    assert validations == [good, good, bad]
    imported = paths['tei_all_teix.xsd']
    imported.write_bytes(imported.read_bytes().replace(b'base="xs:string"', b'base="xs:int"'))
    with pytest.raises(ValueError, match='Spurgeon TEI P5 validation failed'):
        oracle._validate_tei_schema_document(good, paths['tei_all.xsd'])
    assert len(compilations) == 2
    assert validations == [good, good, bad, good]
