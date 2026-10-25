"""Source-specific native rendition of the complete PG55819 HTML candidate."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree

from build.tei.singmaster_story_of_lutheran_missions_to_tei import (
    EXPECTED_ARCHIVE_SHA256, EXPECTED_HTML_SHA256, EXPECTED_IMAGES, HTML_URL,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-5/35/singmaster-story-of-lutheran-missions/pg55819-images.html")
ARCHIVE = SOURCE.parent / "pg55819-h.zip"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NS = {"tei": TEI[1:-1]}


def source_path() -> Path:
    path = resolve_repo_path(ROOT, SOURCE.as_posix())
    if sha256(path.read_bytes()).hexdigest() != EXPECTED_HTML_SHA256:
        raise ValueError("retained PG55819 HTML changed")
    return path


def retained_bindings() -> list[dict]:
    """Bind package and real extracted images; the HTML is the only text authority."""
    html = source_path().read_bytes()
    archive_path = resolve_repo_path(ROOT, ARCHIVE.as_posix())
    data = archive_path.read_bytes()
    if sha256(data).hexdigest() != EXPECTED_ARCHIVE_SHA256:
        raise ValueError("retained PG55819 ZIP changed")
    result = [dict(path=ARCHIVE.as_posix(), bytes=len(data),
                   sha256=sha256(data).hexdigest(), media_type="application/zip",
                   scope="Retained Gutenberg acquisition package, not text authority.")]
    with zipfile.ZipFile(archive_path) as bundle:
        if tuple(bundle.namelist()) != ("pg55819-images.html", *EXPECTED_IMAGES):
            raise ValueError("PG55819 ZIP member sequence changed")
        if bundle.read("pg55819-images.html") != html:
            raise ValueError("PG55819 HTML differs from ZIP member")
        for name in EXPECTED_IMAGES:
            relative = SOURCE.parent / name
            content = resolve_repo_path(ROOT, relative.as_posix()).read_bytes()
            if content != bundle.read(name):
                raise ValueError(f"PG55819 extracted illustration differs: {name}")
            result.append(dict(path=relative.as_posix(), bytes=len(content),
                               sha256=sha256(content).hexdigest(), media_type="image/jpeg",
                               scope="Retained HTML-referenced illustration, not text authority."))
    return result


def adapt(original: bytes) -> bytes:
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if root.get(XML_LANG) != "en" or text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG55819 language envelope differs")
    del root.attrib[XML_LANG]
    text.set(XML_LANG, "en")
    carriers = root.xpath("//*[@xml:id and starts-with(@xml:id, 'slm-src-B')]", namespaces={"xml": XML_ID.rsplit("}", 1)[0][1:]})
    before = [(node.get(XML_ID), " ".join("".join(node.itertext()).split())) for node in carriers]
    pages = root.xpath("//tei:pb[@type]", namespaces=NS)
    figures = root.xpath("//tei:figure[@source]", namespaces=NS)
    ordinals = root.xpath("//tei:cell[@n]|//tei:figDesc[@n]", namespaces=NS)
    if len(pages) != 21 or len(figures) != 36 or len(carriers) != 1010:
        raise ValueError("PG55819 source marker/carrier counts differ")
    for page in pages:
        if page.get("type") != "source-electronic-break" or page.get("facs") != HTML_URL:
            raise ValueError("PG55819 page-break semantics differ")
        page.set("rend", page.attrib.pop("type"))
    for figure in figures:
        if figure.get("source") != HTML_URL:
            raise ValueError("PG55819 figure source URL differs")
        del figure.attrib["source"]
    for node in ordinals:
        ordinal = node.get("n")
        if not ordinal or node.get(XML_ID) != f"slm-src-B{int(ordinal):04d}":
            raise ValueError("PG55819 cell/caption ordinal differs from source ID")
        del node.attrib["n"]
    after = [(node.get(XML_ID), " ".join("".join(node.itertext()).split())) for node in carriers]
    if after != before:
        raise ValueError("PG55819 native rendition changed source text carriers")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
