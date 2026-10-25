"""Source-specific native rendition of the complete PG13360 TEI candidate.

The existing converter remains the transcription producer. This adapter only
relabels its title-page and fixed-width table carriers for the supported P5
and native-projection intersection; it does not select or rewrite source text.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-5/35/missionary-survey/pg13360.txt")
SOURCE_SHA256 = "9ecb274cbbd9cda2e699b643cf3f2c1a574ed60639b49d586d9c9a6af7772878"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NS = {"tei": TEI[1:-1]}


def source_path() -> Path:
    path = resolve_repo_path(ROOT, SOURCE.as_posix())
    if sha256(path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("retained PG13360 TXT changed")
    return path


def adapt(original: bytes) -> bytes:
    """Keep the source-line stream and PG orientation while remapping roles."""
    tree = etree.fromstring(original)
    text = tree.find(TEI + "text")
    if tree.get(XML_LANG) != "en" or text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG13360 source language envelope differs")
    del tree.attrib[XML_LANG]
    text.set(XML_LANG, "en")
    tables = tree.xpath("//tei:ab[@type='table-transcription']", namespaces=NS)
    if len(tables) != 76:
        raise ValueError(f"expected 76 fixed-width table blocks, found {len(tables)}")
    for table in tables:
        if (table.get("rend") != "fixed-width project-gutenberg-orientation"
                or table.get("style") != "display: block; margin: 0.75rem 0; white-space: pre-wrap; font-family: ui-monospace, monospace"):
            raise ValueError("PG13360 table carrier shape differs")
        del table.attrib["type"]
        del table.attrib["style"]
    pages = tree.xpath("/tei:TEI/tei:text/tei:front/tei:titlePage", namespaces=NS)
    if len(pages) != 1 or [etree.QName(child).localname for child in pages[0]] != [
            "docTitle", "byline", "docAuthor", "byline", "docAuthor", "docDate"]:
        raise ValueError("PG13360 title-page roles differ")
    page = pages[0]
    if len(page[0]) != 1 or page[0][0].tag != TEI + "titlePart" or page[0][0].get("type") != "main":
        raise ValueError("PG13360 main title differs")
    original_lines = [(seg.get("n"), "".join(seg.itertext())) for seg in tree.xpath(
        "//tei:seg[@type='source-line']", namespaces=NS)]
    date = page[-1]
    if date.get("when") != "1920":
        raise ValueError("PG13360 title-page date differs")
    title = page[0][0]
    page[0].remove(title)
    page.remove(page[0])
    page.insert(0, title)
    page.tag = TEI + "div"
    page.set("type", "title-page")
    roles = ["main-title", "byline", "author", "byline", "author", "date"]
    for child, role in zip(page, roles, strict=True):
        child.tag = TEI + "ab"
        child.attrib.pop("style", None)
        child.attrib.pop("when", None)
        child.attrib.pop("type", None)
        child.set("type", "source-block")
        child.set("subtype", role)
    signatures = tree.xpath("//tei:signed[@style]", namespaces=NS)
    if len(signatures) != 1 or signatures[0].get("style") != "display: block; margin: 0.75rem 0":
        raise ValueError("PG13360 signature carrier differs")
    del signatures[0].attrib["style"]
    adapted_lines = [(seg.get("n"), "".join(seg.itertext())) for seg in tree.xpath(
        "//tei:seg[@type='source-line']", namespaces=NS)]
    if adapted_lines != original_lines:
        raise ValueError("native adaptation changed selected source lines")
    result = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    return result


def validate_adapted(path: Path) -> None:
    if errors := validate_file(path):
        raise ValueError(f"PG13360 native rendition fails TEI P5: {errors[:3]}")
