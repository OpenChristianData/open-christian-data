"""Focused safety and report-contract checks for the isolated split utility."""

import json

from lxml import etree
import pytest

from build.tools import split_combined_tei_books as split


def _tei() -> etree._Element:
    return etree.Element(f"{{{split.TEI}}}TEI")


def test_plain_books_rejects_traversal_even_when_source_suffix_matches() -> None:
    batch = _tei()
    header = etree.SubElement(batch, f"{{{split.TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{split.TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{split.TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{split.TEI}}}title").text = "Batch"
    text = etree.SubElement(batch, f"{{{split.TEI}}}text")
    body = etree.SubElement(text, f"{{{split.TEI}}}body")
    for source_id in ("s1", "s2"):
        division = etree.SubElement(body, f"{{{split.TEI}}}div")
        division.set(split.XML_ID, f"candidate-{source_id}")
    provenance = {"works": [
        {"work_id": "../escape", "source_root_id": "s1"},
        {"work_id": "safe-book", "source_root_id": "s2"},
    ]}
    with pytest.raises(ValueError, match="unsafe review/work ID"):
        split._plain_books("lib047", batch, provenance, {})


@pytest.mark.parametrize("unsafe", ["../escape", "safe/child", "..", "C:\\escape", "safe\\child", "UPPER", "a..b"])
def test_writer_rejects_unsafe_review_ids_before_creating_output(tmp_path, unsafe: str) -> None:
    output = tmp_path / "review"
    with pytest.raises(ValueError, match="unsafe review/work ID"):
        split._write_review_outputs(output, [(unsafe, _tei(), {})], {})
    assert not output.exists()


def test_late_generation_error_leaves_no_partial_final_tree(tmp_path, monkeypatch) -> None:
    output = tmp_path / "review"
    original = split._serialize
    calls = 0

    def fail_second(node: etree._Element) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected late generation error")
        return original(node)

    monkeypatch.setattr(split, "_serialize", fail_second)
    books = [("first-book", _tei(), {}), ("second-book", _tei(), {})]
    with pytest.raises(RuntimeError, match="injected late generation error"):
        split._write_review_outputs(output, books, {})
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_inventory_names_only_other_extracted_selections(tmp_path) -> None:
    output = tmp_path / "review"
    report = {"source_wide_boundary_and_apparatus_disposition": "unresolved"}
    split._write_review_outputs(output, [("first-book", _tei(), {}), ("second-book", _tei(), {})], report)
    saved = json.loads((output / "split-inventory.json").read_text(encoding="utf-8"))
    assert saved["book_count"] == 2
    assert saved["books"][0]["other_extracted_review_ids"] == ["second-book"]
    assert "excluded_sibling_work_ids" not in saved["books"][0]
    assert saved["source_wide_boundary_and_apparatus_disposition"] == "unresolved"
