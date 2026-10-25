"""Source-derived baseline and deliberate mutations for Watson's IA review candidate."""
from __future__ import annotations
from pathlib import Path
import pytest
from lxml import etree
from build.tei.watson_theological_institutes_ia import _convert
from build.tei.watson_theological_institutes_ia_oracle import check

ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

class StubManifest:
    repository_root = ROOT
    record = {"source_id": "ia-watson-theological-institutes-1825-1826"}
    def verify(self) -> None:
        pass

@pytest.fixture(scope="module")
def pair():
    out = _convert(StubManifest())
    return out["content.tei.xml"], out["source-accountability.json"]

def parse(content: bytes):
    return etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))

def first_body_page(tree):
    return tree.find(f"./{{{TEI}}}text/{{{TEI}}}group/{{{TEI}}}text/{{{TEI}}}body/{{{TEI}}}div")

def test_complete_two_volume_source_baseline(pair):
    content, account = pair
    assert check(ROOT, content, account) == {
        "pages": 1072, "paragraphs": 5121, "lines": 45287, "explicit_ocr_heads": 38}
    tree = parse(content)
    volumes = tree.findall(f"./{{{TEI}}}text/{{{TEI}}}group/{{{TEI}}}text")
    assert [v.get("n") for v in volumes] == ["I", "II"]
    assert [len(v.findall(f".//{{{TEI}}}pb")) for v in volumes] == [578, 494]

@pytest.mark.parametrize("mutation,reason", [
    ("omit_page", "page"),
    ("omit_derived_page", "page"),
    ("duplicate_page", "page"),
    ("swap_pages", "page"),
    ("change_word", "wording"),
    ("change_facs", "PDF/JP2 page binding"),
    ("move_section", "page"),
    ("change_volume", "volume"),
    ("change_heading", "role"),
])
def test_oracle_rejects_mutation(pair, mutation, reason):
    content, account = pair
    tree = parse(content)
    page = first_body_page(tree)
    assert page is not None
    if mutation == "omit_page":
        page.getparent().remove(page)
    elif mutation == "omit_derived_page":
        derived = tree.xpath("//*[@xml:id='v2-leaf-0306']")
        assert len(derived) == 1
        derived[0].getparent().remove(derived[0])
    elif mutation == "duplicate_page":
        duplicate = etree.fromstring(etree.tostring(page))
        for node in duplicate.iter():
            if node.get(XML_ID):
                node.set(XML_ID, node.get(XML_ID) + "-copy")
        page.addnext(duplicate)
    elif mutation == "swap_pages":
        other = page.getnext()
        assert other is not None
        page.addprevious(other)
    elif mutation == "change_word":
        lb = page.find(f".//{{{TEI}}}lb")
        assert lb is not None and lb.tail
        lb.tail += " INVENTED"
    elif mutation == "change_facs":
        page.find(f"{{{TEI}}}pb").set("facs", "scan.pdf#page=999")
    elif mutation == "move_section":
        back = page.getparent().getparent().find(f"{{{TEI}}}back")
        back.append(page)
    elif mutation == "change_volume":
        page.getparent().getparent().set("n", "III")
    elif mutation == "change_heading":
        head = tree.find(f".//{{{TEI}}}head")
        assert head is not None
        head.tag = f"{{{TEI}}}p"
    with pytest.raises(ValueError, match=reason):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)



