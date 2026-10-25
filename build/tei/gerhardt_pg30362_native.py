"""Source-specific native-safe rendition of Gerhardt's complete PG30362 book."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/30362/html/pg30362-images.html")
ARCHIVE = Path("raw/gutenberg/30362/pg30362-h.zip")
COVER = Path("raw/gutenberg/30362/html/30362-cover.png")
SOURCE_SHA256 = "4683ce424e86a0964bb0c030eb3029baf2d3fd9c2671612aaab69e5e611b9ea5"
ARCHIVE_SHA256 = "e5f97d62a381a8abc4bf666784b62a3966487be97b3626a916abd6dca3d2b750"
COVER_SHA256 = "217599494912c6636dae439b017fd80e6ffc7dc89cb42da9d2b8ea82e477a4fe"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260927-pg30362-gerhardt-kelly-1867-v5/package/content.tei.xml")
DIRECT_SHA256 = "dd82ea39d69e4aad38ba51053a0c773e8efe15392d925f286d3350eb1f27599e"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def source_bindings() -> list[dict]:
    result = []
    for path, digest, media_type, scope in (
        (ARCHIVE, ARCHIVE_SHA256, "application/zip", "Retained package, not text authority."),
        (SOURCE, SOURCE_SHA256, "text/html", "Real extracted HTML text authority."),
        (COVER, COVER_SHA256, "image/png", "Real extracted cover support, not HTML-referenced."),
    ):
        data = resolve_repo_path(ROOT, path.as_posix()).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"PG30362 retained member changed: {path}")
        result.append(dict(path=path.as_posix(), bytes=len(data), sha256=digest,
                           media_type=media_type, scope=scope))
    with zipfile.ZipFile(resolve_repo_path(ROOT, ARCHIVE.as_posix())) as bundle:
        if set(bundle.namelist()) != {SOURCE.name, COVER.name}:
            raise ValueError("PG30362 ZIP member set differs")
        for path in (SOURCE, COVER):
            if bundle.read(path.name) != resolve_repo_path(ROOT, path.as_posix()).read_bytes():
                raise ValueError(f"PG30362 ZIP/extracted member differs: {path.name}")
    return result


def _norm(value: str) -> str:
    return " ".join(value.split())


def adapt(original: bytes) -> bytes:
    if sha256(original).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG30362 direct candidate changed")
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if text is None or root.get("{http://www.w3.org/XML/1998/namespace}lang") is not None:
        raise ValueError("PG30362 source language envelope differs")
    before = _norm(" ".join(text.itertext()))
    source_desc = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}sourceDesc")
    if source_desc is None or [child.tag for child in source_desc] != [TEI + "p"]:
        raise ValueError("PG30362 direct bibliographic description differs")
    source_desc[0].tag = TEI + "bibl"
    lists = [node for node in root.iter(TEI + "list") if node.get("n") is not None]
    if len(lists) != 3 or any(not node.get("n", "").isdecimal() for node in lists):
        raise ValueError("PG30362 source list ordinal census differs")
    for node in lists:
        node.set("ana", "urn:ocd:source-ordinal:" + node.attrib.pop("n"))
    labels = list(root.iter(TEI + "label"))
    if len(labels) != 94 or any(node.get(XML_ID) != "source-node-" + node.get("n", "") for node in labels):
        raise ValueError("PG30362 generated label ordinal/ID pairs differ")
    for node in labels:
        del node.attrib["n"]
    sized = [node for node in labels if node.get("rend") is not None]
    if len(sized) != 2 or any(node.get("rend") != "source-class:small" for node in sized):
        raise ValueError("PG30362 source small-label renditions differ")
    for node in sized:
        segment = etree.Element(TEI + "seg", rend=node.attrib.pop("rend"))
        segment.text, node.text = node.text, None
        segment.extend(list(node))
        node.append(segment)
    if _norm(" ".join(text.itertext())) != before:
        raise ValueError("PG30362 native rendition changed source text")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
