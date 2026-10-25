"""Exact retained-source and mutation checks for Lumby's readable edition."""

from __future__ import annotations

from pathlib import Path

from lxml import etree
import pytest

from build.tei.expositors_bible_lib034_readable_lumby import convert
from build.tei.expositors_bible_lib034_readable_lumby_oracle import check


MEMBER = "lumby-expositorpeter"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _candidate(root: Path) -> Path:
    root.mkdir()
    tei, account = convert(MEMBER)
    candidate = root / f"{MEMBER}.tei.xml"
    candidate.write_bytes(tei)
    (root / f"{MEMBER}.source-accountability.json").write_bytes(account)
    return candidate


def test_exact_source_oracle_and_native_projection(tmp_path: Path) -> None:
    _candidate(tmp_path / "original")
    result = check(MEMBER, tmp_path / "original")
    assert result["source_elements"] == 2428
    assert result["source_comments"] == 18
    assert result["native_rows"] == 5
    assert result["p5"] is True


def test_oracle_rejects_changed_source_text(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-text")
    tree = etree.parse(str(candidate))
    node = next(node for node in tree.xpath("//tei:text//*[@xml:id]", namespaces=NS)
                if node.text and node.text.strip())
    node.text += " changed"
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source ID or direct text/tail differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_unresolved_href(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-link")
    tree = etree.parse(str(candidate))
    nodes = tree.xpath("//tei:seg[@type='source-unresolved-link']", namespaces=NS)
    assert [node.get("n") for node in nodes] == ["#", "#foreign", "#"]
    nodes[1].set("n", "#invented")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source-broken local link differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_source_citation(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-citation")
    tree = etree.parse(str(candidate))
    nodes = tree.xpath("//tei:hi[@rend='source-citation']", namespaces=NS)
    assert len(nodes) == 4
    nodes[0].set("rend", "ordinary-emphasis")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source citation rendition differs"):
        check(MEMBER, candidate.parent)
