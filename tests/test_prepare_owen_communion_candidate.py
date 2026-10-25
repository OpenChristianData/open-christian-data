"""Bounded source and candidate checks for the Communion-only extraction."""

from __future__ import annotations

from lxml import etree
import pytest

from build.tools.prepare_owen_communion_candidate import (
    PARENT,
    ROOT,
    SOURCE,
    WORK_ID,
    _parse,
    extract,
)


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@pytest.fixture(scope="module")
def exact_pair() -> tuple[bytes, bytes]:
    path = PARENT / "package/content.tei.xml"
    if not path.is_file():
        pytest.skip("Exact retained LIB-050 candidate package is unavailable")
    return path.read_bytes(), (ROOT / SOURCE).read_bytes()


def test_communion_only_scope_preserves_target_and_accounts_for_siblings(exact_pair) -> None:
    parent, source = exact_pair
    candidate, scope = extract(parent, source)
    document = _parse(candidate)
    readable = next(node for node in document.iter(TEI + "div") if node.get("type") == "readable-transcription")
    assert [node.get(XML_ID) for node in readable] == [f"{WORK_ID}--i"]
    assert [row["disposition"] for row in scope] == [
        "included-work-text", "excluded-sibling-work",
        "excluded-mixed-container-index", "excluded-mixed-container-index",
    ]
    parent_tree = _parse(parent)
    original = next(
        node for node in parent_tree.iter(TEI + "TEI") if node.get(XML_ID) == WORK_ID
    )
    original_readable = next(
        node for node in original.iter(TEI + "div") if node.get("type") == "readable-transcription"
    )
    assert etree.tostring(readable[0], method="c14n") == etree.tostring(
        original_readable[0], method="c14n"
    )


def test_changed_printed_boundary_is_rejected(exact_pair) -> None:
    parent, source = exact_pair
    root = _parse(source)
    body = root.find("ThML.body")
    last_page = list(body)[0].findall(".//pb")[-1]
    last_page.set("n", "999")
    with pytest.raises(ValueError, match="printed boundary"):
        extract(parent, etree.tostring(root))


def test_missing_target_carrier_is_rejected_by_independent_oracle(exact_pair) -> None:
    parent, source = exact_pair
    corpus = _parse(parent)
    member = next(node for node in corpus.iter(TEI + "TEI") if node.get(XML_ID) == WORK_ID)
    readable = next(node for node in member.iter(TEI + "div") if node.get("type") == "readable-transcription")
    paragraph = next(node for node in readable[0].iter(TEI + "p"))
    paragraph.getparent().remove(paragraph)
    with pytest.raises(ValueError, match="readable|carrier|wording"):
        extract(etree.tostring(corpus), source)
