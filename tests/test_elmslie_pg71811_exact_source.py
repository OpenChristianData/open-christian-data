"""Pin the complete retained PG71811 electronic witness and source-local mapper."""

from __future__ import annotations

from pathlib import Path

from lxml import etree
import pytest

from build.tei.elmslie_pg71811_native import reconstruct
from build.tei.elmslie_pg71811_oracle import check
from ocd_kernel.projection.categories.native_documents import (
    ELMSLIE_CHOICE_PROFILE, project_document, verify_document,
)
from ocd_kernel.tei.validate import validate_file


NS = {"t": "http://www.tei-c.org/ns/1.0"}
CONTEXT = {
    "identity": {
        "work_id": "elmslie-books-of-chronicles",
        "textual_form_id": "elmslie-books-of-chronicles-gutenberg-retained",
        "edition_id": "elmslie-books-of-chronicles-gutenberg-electronic",
    },
    "language": "en", "representation_revision": "elmslie-pg71811-v1",
    "edition_title": "The Books of Chronicles", "category": "prose",
    "projection_profile": ELMSLIE_CHOICE_PROFILE, "_allow_acceptance_metadata": True,
}


def test_full_source_p5_native_and_independent_oracle(tmp_path: Path) -> None:
    candidate, tally = reconstruct()
    path = tmp_path / "elmslie.tei.xml"
    path.write_bytes(candidate)
    assert validate_file(path) == []
    result = check(candidate)
    assert result["abbreviation_choices"] == 7255
    assert result["hrefs"] == 2543
    assert result["table_rows"] == [19, 110, 9]
    assert result["table_cells"] == [53, 452, 18]
    assert result["definition_terms"] == 564
    assert result["definition_descriptions"] == 724
    assert tally["#comment"] == 1
    projection = project_document(path, **CONTEXT)
    assert len(projection["rows"]) == 1
    assert verify_document(path, projection["rows"], projection["receipt"], **CONTEXT) == []


@pytest.mark.parametrize(
    ("xpath", "attribute", "replacement", "message"),
    [
        (".//t:choice/t:expan", None, "mutated expansion", "abbreviation choice differs"),
        (".//t:ref[@target]", "target", "#mutated", "ordered literal HTML hrefs differ"),
        (".//t:table/t:row/t:cell", None, "mutated table cell", "displayed source text differs"),
        (".//t:graphic", "url", "images/mutated.jpg", "figure/image support differs"),
    ],
)
def test_oracle_rejects_source_semantic_mutations(
    xpath: str, attribute: str | None, replacement: str, message: str,
) -> None:
    candidate, _ = reconstruct()
    root = etree.fromstring(candidate)
    selected = root.xpath(xpath, namespaces=NS)
    assert selected
    if attribute:
        selected[0].set(attribute, replacement)
    else:
        selected[0].text = replacement
    with pytest.raises(ValueError, match=message):
        check(etree.tostring(root, encoding="UTF-8", xml_declaration=True))
