"""Source-bound checks for Adeney's two separate CCEL electronic editions."""

from __future__ import annotations

from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib036_readable_adeney_pair_oracle import check


CANDIDATES = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib036-adeney-pair-candidates-20260928-v3"
)
NS = "{http://www.tei-c.org/ns/1.0}"


@pytest.mark.parametrize(
    ("member_id", "expected_elements", "expected_rows"),
    [
        ("adeney-expositoreznehes", 2695, 37),
        ("adeney-expositorsonglament", 2424, 4),
    ],
)
def test_exact_source_oracle(member_id: str, expected_elements: int, expected_rows: int) -> None:
    result = check(member_id, CANDIDATES / member_id, formal=True)
    assert result["source_elements"] == expected_elements
    assert result["native_rows"] == expected_rows
    assert result["p5"] is True
    tree = etree.parse(str(CANDIDATES / member_id / "content.tei.xml"))
    indexes = tree.findall(f".//{NS}div[@type='source-index']")
    assert len(indexes) == 2
    assert not tree.findall(f".//{NS}quote[@type='source-index']")


def test_oracle_rejects_lost_commentary_text(tmp_path: Path) -> None:
    member_id = "adeney-expositoreznehes"
    source = CANDIDATES / member_id
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(source / name, tmp_path / name)
    xml_path = tmp_path / "content.tei.xml"
    tree = etree.parse(str(xml_path))
    body = tree.getroot().find(f"{NS}text/{NS}body")
    assert body is not None
    paragraph = next(node for node in body.iter(NS + "p") if node.text and node.text.strip())
    paragraph.text = paragraph.text + " invented"
    tree.write(str(xml_path), encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source ID or direct text/tail differs"):
        check(member_id, tmp_path, formal=True)


def test_oracle_rejects_changed_comment_disposition(tmp_path: Path) -> None:
    member_id = "adeney-expositorsonglament"
    source = CANDIDATES / member_id
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(source / name, tmp_path / name)
    ledger = tmp_path / "source-accountability.json"
    content = ledger.read_text(encoding="utf-8")
    assert "source-comment-ledger-only" in content
    ledger.write_text(content.replace("source-comment-ledger-only", "discarded", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="source comments ledger differs"):
        check(member_id, tmp_path, formal=True)


@pytest.mark.parametrize("member_id", ["adeney-expositoreznehes", "adeney-expositorsonglament"])
def test_oracle_rejects_index_as_quote(member_id: str, tmp_path: Path) -> None:
    source = CANDIDATES / member_id
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(source / name, tmp_path / name)
    xml_path = tmp_path / "content.tei.xml"
    tree = etree.parse(str(xml_path))
    index = tree.find(f".//{NS}div[@type='source-index']")
    assert index is not None
    index.tag = NS + "quote"
    index.set("type", "source-div")
    tree.write(str(xml_path), encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="TEI tag differs"):
        check(member_id, tmp_path, formal=True)
