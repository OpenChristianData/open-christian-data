"""Source-specific native-safe rendition of Teresa's complete PG8120 book."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-1/07/teresa-life-of-st-teresa-of-jesus/extracted/pg8120-h/pg8120-images.html")
ARCHIVE = Path("raw/clean-ready-acquisition-to-tei/master-1/07/teresa-life-of-st-teresa-of-jesus/pg8120-h.zip")
COVER = SOURCE.parent / "8120-cover.png"
SOURCE_SHA256 = "9aeeb297ddcd83e801b9782fd7c376af845491e3fd2a941a85530b0214ad3e74"
ARCHIVE_SHA256 = "92b3442c0b2c04c206152c41b698bd464899ac078c2660afa83c2c751b17d274"
COVER_SHA256 = "bf20cc07794aa2d1f6b350758dd7d7c7135a4759754f7058276d10be88ae04b6"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def source_bindings() -> list[dict]:
    result = []
    for path, digest, media_type, scope in (
        (SOURCE, SOURCE_SHA256, "text/html", "Real extracted PG8120 HTML text authority."),
        (ARCHIVE, ARCHIVE_SHA256, "application/zip", "Retained package, not text authority."),
        (COVER, COVER_SHA256, "image/png", "Real extracted cover support, not text authority."),
    ):
        data = resolve_repo_path(ROOT, path.as_posix()).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"PG8120 retained member changed: {path}")
        result.append(dict(path=path.as_posix(), bytes=len(data), sha256=digest,
                           media_type=media_type, scope=scope))
    with zipfile.ZipFile(resolve_repo_path(ROOT, ARCHIVE.as_posix())) as bundle:
        if sorted(bundle.namelist()) != sorted([SOURCE.name, COVER.name]):
            raise ValueError("PG8120 package members differ")
        if bundle.read(SOURCE.name) != resolve_repo_path(ROOT, SOURCE.as_posix()).read_bytes():
            raise ValueError("PG8120 extracted HTML differs from package")
        if bundle.read(COVER.name) != resolve_repo_path(ROOT, COVER.as_posix()).read_bytes():
            raise ValueError("PG8120 extracted cover differs from package")
    return result


def _wrap(node: etree._Element, *, attributes: dict[str, str]) -> None:
    wrapper = etree.Element(TEI + "seg", attributes)
    wrapper.tail, node.tail = node.tail, None
    parent = node.getparent()
    if parent is None:
        raise ValueError("PG8120 inline source carrier has no parent")
    parent.replace(node, wrapper)
    wrapper.append(node)


def adapt(original: bytes) -> bytes:
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if root.get(XML_LANG) != "en" or text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG8120 language envelope differs")
    before = " ".join(" ".join(text.itertext()).split())
    del root.attrib[XML_LANG]
    text.set(XML_LANG, "en")
    abbreviations = [node for node in root.iter(TEI + "abbr") if "n" in node.attrib]
    citations = [node for node in root.iter(TEI + "title") if "rend" in node.attrib]
    breaks = [node for node in root.iter(TEI + "milestone") if node.get("unit") == "typographic-break"]
    if len(abbreviations) != 528 or len(citations) != 337 or len(breaks) != 112:
        raise ValueError("PG8120 abbreviation/citation/separator census differs")
    for node in abbreviations:
        expansion = node.attrib.pop("n")
        if not expansion:
            raise ValueError("PG8120 empty source abbreviation title")
        _wrap(node, attributes={"ana": "urn:ocd:abbreviation-expansion", "n": expansion})
    for node in citations:
        rendition = node.attrib.pop("rend")
        if rendition != "citation":
            raise ValueError("PG8120 source citation rendition differs")
        _wrap(node, attributes={"rend": rendition})
    for node in breaks:
        node.set("unit", "source-horizontal-rule")
    if " ".join(" ".join(text.itertext()).split()) != before:
        raise ValueError("PG8120 native rendition changed source text")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
