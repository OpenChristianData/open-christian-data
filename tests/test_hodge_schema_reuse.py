"""Hodge retains document checks and binds every schema-compiler dependency."""
from pathlib import Path
from types import SimpleNamespace

from lxml import etree
import pytest

from build.lib.tei_xsd import compiled_tei_schema
from build.tei import aa_hodge_outlines_oracle as oracle
from tests.test_tei_xsd import _write_schema_set


def test_hodge_reuses_compilation_but_validates_each_document_and_changed_schema(tmp_path, monkeypatch):
    paths = _write_schema_set(tmp_path)
    compilations, validations = [], []
    original = etree.XMLSchema

    def compile(*args, **kwargs):
        compilations.append(True)
        return original(*args, **kwargs)

    class Observed:
        def __init__(self, schema):
            self.schema = schema
        def assertValid(self, document):
            validations.append(etree.tostring(document))
            self.schema.assertValid(document)

    monkeypatch.setattr(etree, "XMLSchema", compile)
    monkeypatch.setattr(oracle, "compiled_tei_schema", lambda path: Observed(compiled_tei_schema(path)))
    monkeypatch.setattr(oracle, "_authority", lambda *_: ({}, paths["tei_all.xsd"]))
    content = [b'<root xmlns="urn:main">text</root>']
    candidate = SimpleNamespace(member_bytes=lambda _: content[0])
    monkeypatch.setattr(oracle, "_expected_tei_bytes", lambda _: content[0])
    for _ in range(2):
        with pytest.raises(ValueError, match="TEI root identity drift"):
            oracle._validate_tei(object(), candidate, ())
    content[0] = b'<root xmlns="urn:main"><unexpected/></root>'
    with pytest.raises(etree.DocumentInvalid):
        oracle._validate_tei(object(), candidate, ())
    assert len(compilations) == 1 and len(validations) == 3
    content[0] = b'<root xmlns="urn:main">text</root>'
    imported = paths["tei_all_teix.xsd"]
    imported.write_bytes(imported.read_bytes().replace(b'base="xs:string"', b'base="xs:int"'))
    with pytest.raises(etree.DocumentInvalid):
        oracle._validate_tei(object(), candidate, ())
    assert len(compilations) == 2 and len(validations) == 4


@pytest.mark.parametrize("logical", (
    "build/__init__.py", "build/lib/__init__.py", "build/lib/tei_xsd.py",
    "build/tei/aa_hodge_outlines_oracle.py",
))
@pytest.mark.parametrize("missing", (False, True))
def test_hodge_closure_binds_every_executed_first_party_dependency(tmp_path, logical, missing):
    root = Path(__file__).resolve().parents[1]
    for relative in oracle._FIRST_PARTY_IMPORT_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / relative).read_bytes())
    before = oracle._import_closure_sha256(root)
    assert oracle._import_closure_sha256(tmp_path) == before
    changed = tmp_path / logical
    if missing:
        changed.unlink()
        with pytest.raises(FileNotFoundError):
            oracle._import_closure_sha256(tmp_path)
    else:
        changed.write_bytes(changed.read_bytes() + b"\n# dependency drift\n")
        assert oracle._import_closure_sha256(tmp_path) != before
