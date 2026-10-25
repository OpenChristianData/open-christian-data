"""Native-safe, source-specific rendition of the complete PG55955 HTML candidate."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-5/35/ports-of-entry-missionary-herald/pg55955-images.html")
SOURCE_SHA256 = "a8d4f79ae076080cd64ef07b3cb798dcdcfc1b9d38f461f0648c9844b0bb3dbf"
SOURCE_URL = "https://www.gutenberg.org/cache/epub/55955/pg55955-images.html"
IMAGE_ROOT = SOURCE.parent / "images"
IMAGE_NAMES = (
    "cover.jpg", "i_004.jpg", "i_009.jpg", "i_016.jpg", "i_021.jpg", "i_022.jpg",
    "i_back.jpg", "i_cover.jpg", "i_decor.jpg", "i_decor2.jpg", "i_title.jpg",
)
IMAGE_SHA256 = {
    "cover.jpg": "e64898b34a803a7e9714a8e94a87a3ea66d268def9054f8a5f0b4178233b56d8",
    "i_004.jpg": "5cc16469bdfe20e755ef96784b2cdbfb4c3382c96c2e723d2bc8fa58c531755e",
    "i_009.jpg": "e19dd878c40d643d060971c625e0321a8485a87e1f4c15c93c43f7d24dde4c7b",
    "i_016.jpg": "73318a5c71a957726df0ff08c80c5547d3c4b25981b72895e841a86ac55e6056",
    "i_021.jpg": "c8f49f03c02ce1403b7ff5fe9cd9ad075d2055c6215d90483776cf442e2ccf3c",
    "i_022.jpg": "45e6a8da02c0cc74e62e04ef2d0df6b1952dd1a25663119e3dfeb6482a501535",
    "i_back.jpg": "11b67de87e9ffca73d7782d9ca413ddd732b79703cc78eb8f2796be279c3b178",
    "i_cover.jpg": "5d7e36c0920ee6308b5b349b0554ba09ac4bbc1373930310b47497c3e34dbdf8",
    "i_decor.jpg": "d31aa10267e98f396b0faa9b3e72e93b7b97f79a4e7d61aca8752b53c39eb5a7",
    "i_decor2.jpg": "b96f4aed62c91a0fd886026398730fd5814823c92fa68f1e1d7943a0dc6be43d",
    "i_title.jpg": "5868148a50aaadd46b11e261330c181a9d08856e22e8e38f615473dc41f21b54",
}
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NS = {"tei": TEI[1:-1]}


def source_path() -> Path:
    path = resolve_repo_path(ROOT, SOURCE.as_posix())
    if sha256(path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("retained PG55955 HTML changed")
    return path


def image_bindings() -> list[dict]:
    result = []
    for name in IMAGE_NAMES:
        relative = IMAGE_ROOT / name
        content = resolve_repo_path(ROOT, relative.as_posix()).read_bytes()
        if sha256(content).hexdigest() != IMAGE_SHA256[name]:
            raise ValueError(f"retained PG55955 image changed: {name}")
        result.append(dict(path=relative.as_posix(), bytes=len(content),
                           sha256=sha256(content).hexdigest(), media_type="image/jpeg",
                           scope="Retained HTML-referenced image support, not independent text authority."))
    return result


def adapt(original: bytes) -> bytes:
    """Keep all source text and graphical/table order with native carrier names."""
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if root.get(XML_LANG) != "en" or text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG55955 source language envelope differs")
    del root.attrib[XML_LANG]
    text.set(XML_LANG, "en")
    carriers_before = [(node.get(XML_ID), " ".join("".join(node.itertext()).split()))
                       for node in root.iter() if (node.get(XML_ID) or "").startswith("poe-src-B")]
    rules = root.xpath("//tei:milestone[@unit='typographic-rule']", namespaces=NS)
    figures = root.xpath("//tei:figure[@source]", namespaces=NS)
    captions = root.xpath("//tei:figDesc[@n]", namespaces=NS)
    cells = root.xpath("//tei:cell[@n]", namespaces=NS)
    if len(rules) != 15 or len(figures) != 12 or len(captions) != 8 or len(cells) != 503:
        raise ValueError("PG55955 horizontal-rule/figure/cell carrier counts differ")
    for rule in rules:
        if set(rule.attrib) not in ({"unit"}, {"unit", "rend"}) or rule.get("rend") not in (None, "style1"):
            raise ValueError("PG55955 horizontal-rule attributes differ")
        rule.set("unit", "source-horizontal-rule")
    for figure in figures:
        if figure.get("source") != SOURCE_URL:
            raise ValueError("PG55955 figure provenance URL differs")
        del figure.attrib["source"]
    for node in [*captions, *cells]:
        ordinal = node.get("n")
        if not ordinal or node.get(XML_ID) != f"poe-src-B{int(ordinal):04d}":
            raise ValueError("PG55955 caption/cell ordinal differs from source carrier ID")
        del node.attrib["n"]
    carriers_after = [(node.get(XML_ID), " ".join("".join(node.itertext()).split()))
                      for node in root.iter() if (node.get(XML_ID) or "").startswith("poe-src-B")]
    if carriers_after != carriers_before or len(carriers_after) != 868:
        raise ValueError("PG55955 native rendition changed the complete source carrier stream")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
