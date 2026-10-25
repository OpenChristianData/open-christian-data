"""A TEI envelope ID is source metadata, with the existing uniqueness checks."""

from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from ocd_kernel.projection.categories import hymns


FIXTURE = Path(__file__).parent / "fixtures/library-pipeline/categories/hymns/master.tei.xml"


@pytest.mark.parametrize("parse,validate,inventory", [
    (ET.fromstring, hymns._strict_et, hymns._inventory_et),
    (etree.fromstring, hymns._strict_lxml, hymns._inventory_lxml),
])
def test_envelope_id_is_accounted_and_invalid_attributes_still_fail(parse, validate, inventory):
    root = parse(FIXTURE.read_bytes())
    root.set(hymns.XML_ID, "retained-hymnal")
    validate(root)
    entries, _, _ = inventory(root)
    assert entries[0]["attributes"]["xml:id"] == "retained-hymnal"
    root[0].set(hymns.XML_ID, "retained-hymnal")
    with pytest.raises(hymns.UnsupportedStructure):
        validate(root)
    del root[0].attrib[hymns.XML_ID]
    root.set("unknown", "unaccounted")
    with pytest.raises(hymns.UnsupportedStructure, match="TEI attribute unknown"):
        validate(root)
