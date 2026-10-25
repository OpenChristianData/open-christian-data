"""The accepted PG77576 Virgin Mary endnote must remain public readable text."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document, verify_accepted_document,
)


ROOT = Path(__file__).resolve().parents[1]
EDITION = (Path("library/works/pg77576-ignatius-virgin-mary")
           / "forms/pg77576-ignatius-virgin-mary-english"
           / "editions/pg77576-ignatius-virgin-mary-pg77576-edition")
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def test_accepted_master_endnote_has_readable_corresponding_row() -> None:
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    tree = etree.parse(str(master))
    note = tree.xpath("/t:TEI/t:text/t:back/t:div/t:note[@xml:id='f2025']/t:p",
                      namespaces=NS)
    assert len(note) == 1
    expected_note = re.sub(r"\s+", " ", "".join(note[0].itertext())).strip()

    projection = project_accepted_document(ROOT, acceptance_path=acceptance, category="prose")
    rows, receipt = projection["rows"], projection["receipt"]
    assert len(rows) == 2
    assert rows[0]["text"].endswith("Amen.")
    assert rows[1]["locator"] == {"kind": "native-unit", "text_part": "back", "unit": 1}
    assert rows[1]["text"] == expected_note
    assert rows[1]["text"].strip()
    assert verify_accepted_document(ROOT, acceptance_path=acceptance,
                                    rows=rows, receipt=receipt, category="prose") == []

    corrupted = deepcopy(rows)
    corrupted[1]["text"] = ""
    assert verify_accepted_document(ROOT, acceptance_path=acceptance,
                                    rows=corrupted, receipt=receipt, category="prose")
