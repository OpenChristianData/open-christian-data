"""Complete exact local XSD imports must be present in historical fixture mirrors."""
from hashlib import sha256
from pathlib import Path

from lxml import etree
import pytest

from tests.vendored_schema_mirrors import PINS, SCHEMA_RELATIVE, copy_vendored_schema_imports

ROOT = Path(__file__).resolve().parents[1]


def test_complete_vendored_imports_resolve_xml_id_without_network(tmp_path):
    target = tmp_path / SCHEMA_RELATIVE
    target.mkdir(parents=True)
    (target / "tei_all.xsd").write_bytes((ROOT / SCHEMA_RELATIVE / "tei_all.xsd").read_bytes())
    copy_vendored_schema_imports(ROOT, tmp_path)
    for name, digest in PINS.items():
        assert sha256((target / name).read_bytes()).hexdigest() == digest
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    assert isinstance(etree.XMLSchema(etree.parse(str(target / "tei_all.xsd"), parser)), etree.XMLSchema)


@pytest.mark.parametrize("changed", ("tei_all_xml.xsd", "tei_all_teix.xsd"))
def test_wrong_import_bytes_are_rejected_without_partial_copy(tmp_path, changed):
    source, destination = tmp_path / "input", tmp_path / "mirror"
    for root in (source, destination):
        (root / SCHEMA_RELATIVE).mkdir(parents=True)
        (root / SCHEMA_RELATIVE / "tei_all.xsd").write_bytes((ROOT / SCHEMA_RELATIVE / "tei_all.xsd").read_bytes())
    for name in ("tei_all_xml.xsd", "tei_all_teix.xsd"):
        raw = (ROOT / SCHEMA_RELATIVE / name).read_bytes()
        (source / SCHEMA_RELATIVE / name).write_bytes(raw + (b"\n<!-- changed -->\n" if name == changed else b""))
    with pytest.raises(ValueError, match="Vendored schema import bytes differ"):
        copy_vendored_schema_imports(source, destination)
    assert sorted(p.name for p in (destination / SCHEMA_RELATIVE).iterdir()) == ["tei_all.xsd"]
