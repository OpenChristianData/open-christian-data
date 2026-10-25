"""Focused source-ground corruption checks for Robertson's scan/column TEI."""
from __future__ import annotations

from pathlib import Path

from lxml import etree
import pytest

from build.tei.robertson_harmony_1922_oracle import check
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "sources/robertson-harmony-1922/source-manifest.json"
CANDIDATE = Path(
    r"D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925\robertson-harmony-v2\package"
)
NS = {"t": "http://www.tei-c.org/ns/1.0"}


@pytest.fixture(scope="module")
def bound_pair() -> tuple[SourceManifest, bytes, bytes]:
    source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
    candidate = CandidatePackage.load(CANDIDATE)
    return source, candidate.member_bytes("content.tei.xml"), candidate.member_bytes("source-accountability.json")


def test_baseline_complete_source_traversal(bound_pair: tuple[SourceManifest, bytes, bytes]) -> None:
    source, tei, account = bound_pair
    result = check(source, tei, account)
    assert result["pages"] == 362
    assert result["counts"]["direct_paragraphs"] == 2684
    assert len(result["no_ocr_leaves"]) == 21


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("omit_page", "page count"),
        ("change_word", "word text"),
        ("move_direct_paragraph", "direct paragraph attachment|column order"),
        ("change_position", "word text/position"),
        ("change_page_id", "page identity"),
        ("remove_map_image", "image/gap"),
    ],
)
def test_source_mutations_are_rejected(
    bound_pair: tuple[SourceManifest, bytes, bytes], mutation: str, message: str
) -> None:
    source, tei, account = bound_pair
    root = etree.fromstring(tei)
    pages = root.xpath("./t:text/t:body/t:div/t:div", namespaces=NS)
    assert len(pages) == 362
    if mutation == "omit_page":
        pages[-1].getparent().remove(pages[-1])
    elif mutation == "change_word":
        word = pages[6].xpath(".//t:w", namespaces=NS)[0]
        word.text = "INVENTED"
    elif mutation == "move_direct_paragraph":
        page = pages[40]
        direct = page.xpath("./t:div[@type='source-direct-paragraph']", namespaces=NS)[0]
        page.remove(direct)
        page.append(direct)
    elif mutation == "change_position":
        word = pages[6].xpath(".//t:w", namespaces=NS)[0]
        word.set("rend", "coords:0,0,0,0 confidence:0")
    elif mutation == "change_page_id":
        pages[6].set("n", "9999")
    elif mutation == "remove_map_image":
        page = pages[9]
        page.remove(page.xpath("./t:figure", namespaces=NS)[0])
    else:
        raise AssertionError(mutation)
    changed = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    assert changed != tei
    with pytest.raises(ValueError, match=message):
        check(source, changed, account)

