"""Native-safe source-specific rendition of Newman's complete PG35110 witness."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-1/07/newman-development-christian-doctrine/extracted/pg35110-h/pg35110-images.html")
ARCHIVE = Path("raw/clean-ready-acquisition-to-tei/master-1/07/newman-development-christian-doctrine/pg35110-h.zip")
COVER = SOURCE.parent / "35110-cover.png"
SOURCE_SHA256 = "9713808e5dc56b6d0ffff66e4ea470b21760ee1aadca7ff8aad9da807e8822d4"
ARCHIVE_SHA256 = "8335ab4ef21bc0c17169eb8562d3271f49595ce851948476a32ce9ae8d7c22f6"
COVER_SHA256 = "646cdc94ca08554c8f187d755c64a8268448e2acebdfc5409b7ee201a8103bda"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
GREEK_ANA = "urn:ocd:greek-transliteration"


def source_bindings() -> list[dict]:
    bindings = []
    for path, digest, media_type, scope in (
        (SOURCE, SOURCE_SHA256, "text/html", "Extracted PG35110 HTML text authority."),
        (ARCHIVE, ARCHIVE_SHA256, "application/zip", "Retained acquisition package, not text authority."),
        (COVER, COVER_SHA256, "image/png", "Extracted cover image support, not text authority."),
    ):
        data = resolve_repo_path(ROOT, path.as_posix()).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"retained PG35110 member changed: {path}")
        bindings.append(dict(path=path.as_posix(), bytes=len(data), sha256=digest,
                             media_type=media_type, scope=scope))
    with zipfile.ZipFile(resolve_repo_path(ROOT, ARCHIVE.as_posix())) as bundle:
        if bundle.namelist() != [SOURCE.name, COVER.name]:
            raise ValueError("PG35110 package member sequence differs")
        if bundle.read(SOURCE.name) != resolve_repo_path(ROOT, SOURCE.as_posix()).read_bytes():
            raise ValueError("PG35110 extracted HTML differs from package")
        if bundle.read(COVER.name) != resolve_repo_path(ROOT, COVER.as_posix()).read_bytes():
            raise ValueError("PG35110 extracted cover differs from package")
    return bindings


def adapt(original: bytes) -> bytes:
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if root.get(XML_LANG) != "en" or text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG35110 language envelope differs")
    original_text = " ".join("".join(text.itertext()).split())
    del root.attrib[XML_LANG]
    text.set(XML_LANG, "en")
    foreign = list(root.iter(TEI + "foreign"))
    if len(foreign) != 26:
        raise ValueError("PG35110 Greek span count differs")
    for node in foreign:
        if (set(node.attrib) != {XML_LANG, "ana", "n"} or node.get(XML_LANG) != "grc"
                or node.get("ana") != GREEK_ANA or not node.get("n")):
            raise ValueError("PG35110 Greek/transliteration attributes differ")
        annotation = node.attrib.pop("ana")
        transliteration = node.attrib.pop("n")
        segment = etree.Element(TEI + "seg", ana=annotation, n=transliteration)
        segment.text, node.text = node.text, None
        for child in list(node):
            node.remove(child)
            segment.append(child)
        node.append(segment)
    if " ".join("".join(text.itertext()).split()) != original_text:
        raise ValueError("PG35110 native Greek rendition changed source text")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
