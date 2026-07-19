from __future__ import annotations

import re
from pathlib import Path

from lxml import etree
import pytest

from build.tei.gutenberg_to_tei import ConversionError, _InlineState, _append_inline, convert_calvin_to_tei

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CALVIN_TEI = Path("ir/calvin/calvins-institutes.gutenberg.tei.xml")


def test_calvin_inline_carriers_preserve_markup_and_note_targets() -> None:
    paragraph = etree.Element(f"{{{TEI_NS}}}p")
    _append_inline(
        paragraph,
        "The _word_ [12] remains; snake_case is literal.",
        "pg64392",
        41,
        _InlineState(),
    )

    assert "".join(paragraph.itertext()) == "The word [12] remains; snake_case is literal."
    hi = paragraph.find(f"{{{TEI_NS}}}hi")
    ref = paragraph.find(f"{{{TEI_NS}}}ref")
    assert hi is not None and hi.get("rend") == "italic" and hi.text == "word"
    assert ref is not None
    assert ref.get("type") == "note"
    assert ref.get("target") == "#pg64392-note-12"
    assert ref.get(XML_ID) == "pg64392-ref-42-1"


def test_calvin_parenthetical_pairing_leaves_nonsequential_marker_literal() -> None:
    paragraph = etree.Element(f"{{{TEI_NS}}}p")
    note_numbers = frozenset({1, 2})
    state = _InlineState(
        parenthetical_note_numbers_by_source={"pg45001": note_numbers}
    )
    _append_inline(
        paragraph,
        "A (1) B (3) C (2).",
        "pg45001",
        10,
        state,
        parenthetical_note_numbers=note_numbers,
    )

    refs = paragraph.findall(f"{{{TEI_NS}}}ref")
    assert [ref.get("target") for ref in refs] == [
        "#pg45001-note-1",
        "#pg45001-note-2",
    ]
    assert "(3)" in "".join(paragraph.itertext())


def test_calvin_artifact_has_logical_books_and_selected_source_boundaries() -> None:
    assert CALVIN_TEI.exists(), "regenerate the committed Calvin TEI artifact first"
    tree = etree.parse(str(CALVIN_TEI))
    books = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div[@type='book']", namespaces=NS)
    assert [book.get(XML_ID) for book in books] == [
        "pg45001-book-I",
        "pg45001-book-II",
        "pg45001-book-III",
        "pg64392-book-IV",
    ]
    assert len(tree.xpath("/tei:TEI/tei:text/tei:body//tei:div[@type='chapter']", namespaces=NS)) == 80
    assert len(tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=NS)) == 1361
    assert len(tree.xpath("//tei:ref[@type='note']", namespaces=NS)) == 3505
    assert len(tree.xpath("//tei:ref[@type='note' and starts-with(@xml:id, 'pg45001-ref-')]", namespaces=NS)) == 2016
    assert len(tree.xpath("//tei:ref[@type='note' and starts-with(@xml:id, 'pg64392-ref-')]", namespaces=NS)) == 1489
    assert len(tree.xpath("//tei:note[@place='end']", namespaces=NS)) == 3506
    assert len(tree.xpath("//tei:note[@place='end' and starts-with(@xml:id, 'pg45001-note-')]", namespaces=NS)) == 2016
    assert len(tree.xpath("//tei:note[@place='end' and starts-with(@xml:id, 'pg64392-note-')]", namespaces=NS)) == 1490
    xml_ids = set(tree.xpath("//@xml:id", namespaces=NS))
    note_targets = {
        target.removeprefix("#")
        for target in tree.xpath("//tei:ref[@type='note']/@target", namespaces=NS)
    }
    assert note_targets <= xml_ids
    assert not any(
        re.search(
            # 1-4 digits, not 3-4: a leftover low-numbered marker like "(5)" is the
            # same defect as "(2016)" and must not slip past this gate.
            r"\(\d{1,4}\)",
            "".join(paragraph.xpath(".//text()[not(ancestor::tei:ref)]", namespaces=NS)),
        )
        for paragraph in tree.xpath(
            "/tei:TEI/tei:text/tei:body/tei:div[@xml:id='pg45001-book-I' or @xml:id='pg45001-book-II' or @xml:id='pg45001-book-III']//tei:p",
            namespaces=NS,
        )
    )
    assert not any(
        re.match(r"^Footnote \d+:", " ".join(paragraph.itertext()).strip())
        for paragraph in tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=NS)
    )
    assert not tree.xpath("//text()[contains(., 'END OF THE INSTITUTES.')]")


def test_calvin_volume_with_anchors_but_no_note_bodies_raises(tmp_path: Path) -> None:
    vol1 = tmp_path / "vol1.txt"
    vol2 = tmp_path / "vol2.txt"
    vol1.write_text(
        "*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
        "BOOK I.\n\nChapter I. Test\n\nBody.\n\nFOOTNOTES\n\n"
        "    1 A note body.\n*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n",
        encoding="utf-8",
    )
    vol2.write_text(
        "*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
        "BOOK III.\n\nCHAPTER I.\nTEST\n\nBody [1].\n\nEND OF THE INSTITUTES.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n",
        encoding="utf-8",
    )

    with pytest.raises(ConversionError, match="numeric note anchors but no recoverable note bodies"):
        convert_calvin_to_tei(vol1, vol2, tmp_path / "output.tei.xml")
