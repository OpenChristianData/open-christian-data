"""Source-specific native-safe rendition of Keble's complete PG4272 witness."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
import zipfile

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/4272/html/pg4272-images.html")
ARCHIVE = Path("raw/gutenberg/4272/pg4272-h.zip")
IMAGES = (
    (Path("raw/gutenberg/4272/html/images/covers.jpg"), "a083c32c32c155111a992e5ce4c672b22e2c0b85f46a3bdd6fea18c8fea57a34"),
    (Path("raw/gutenberg/4272/html/images/coverb.jpg"), "5dffa3b8b8621ceed34deb7f437f9dc8d9d94663ffd2589b15b7a5d40e113d4c"),
    (Path("raw/gutenberg/4272/html/images/tpb.jpg"), "11c1d1972955c3eada466e8449314015fb671a628ebf1474bf035e7946a3a8fc"),
    (Path("raw/gutenberg/4272/html/images/tps.jpg"), "a37aa546d09f8bda836685352af2071c83ccac281fe4f31dae0ffd8a9a0f5d19"),
)
SOURCE_SHA256 = "47149d0f9719209e82267e83606354d36a3ddbb18cecd6d54e9c971f5f5c2cb2"
ARCHIVE_SHA256 = "6672add075f8368f8dbbb05c5b3c902be82eeb461ccf83e2680989f71ffc0e15"
DIRECT_SHA256 = "ad2b4deaaac013233706413000c7a2e4a45bdc62630a39adfe133134172ad51c"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260926-pg4272-keble-1887-cassell-v1/package/content.tei.xml")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def source_bindings() -> list[dict]:
    declared = [(ARCHIVE, ARCHIVE_SHA256, "application/zip", "Retained package, not text authority."),
                (SOURCE, SOURCE_SHA256, "text/html", "Real extracted HTML text authority.")]
    declared.extend((path, digest, "image/jpeg", "Real extracted supporting image.") for path, digest in IMAGES)
    result = []
    for path, digest, media_type, scope in declared:
        data = resolve_repo_path(ROOT, path.as_posix()).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"PG4272 retained member changed: {path}")
        result.append(dict(path=path.as_posix(), bytes=len(data), sha256=digest,
                           media_type=media_type, scope=scope))
    with zipfile.ZipFile(resolve_repo_path(ROOT, ARCHIVE.as_posix())) as bundle:
        expected = {SOURCE.name: SOURCE}
        expected.update({"images/" + path.name: path for path, _ in IMAGES})
        if set(bundle.namelist()) != set(expected):
            raise ValueError("PG4272 ZIP member set differs")
        for member, path in expected.items():
            if bundle.read(member) != resolve_repo_path(ROOT, path.as_posix()).read_bytes():
                raise ValueError(f"PG4272 ZIP/extracted member differs: {member}")
    return result


def _norm(value: str) -> str:
    return " ".join(value.split())


def adapt(original: bytes) -> bytes:
    if sha256(original).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG4272 direct candidate changed")
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if text is None or root.get(XML_LANG) != "en" or text.get(XML_LANG) is not None:
        raise ValueError("PG4272 language envelope differs")
    before = _norm(" ".join(text.itertext()))
    del root.attrib[XML_LANG]
    text.set(XML_LANG, "en")
    source_desc = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}sourceDesc")
    if source_desc is None or [child.tag for child in source_desc] != [TEI + "p"]:
        raise ValueError("PG4272 direct bibliographic description differs")
    source_desc[0].tag = TEI + "bibl"
    pre = [node for node in root.iter(TEI + "ab") if node.get("type") == "source-html-pre"]
    if len(pre) != 1 or _norm(" ".join(pre[0].itertext())):
        raise ValueError("PG4272 empty layout pre differs")
    pre[0].set("type", "source-block")
    pre[0].set("subtype", "source-html-pre")
    source_images = list(html.fromstring(resolve_repo_path(ROOT, SOURCE.as_posix()).read_bytes()).iter("img"))
    markers = [node for node in root.iter(TEI + "milestone") if node.get("unit") == "source-image-reference"]
    if len(source_images) != len(markers) or len(markers) != 2:
        raise ValueError("PG4272 source/TEI image reference count differs")
    for marker, source_image in zip(markers, source_images):
        src, alt, title = source_image.get("src"), source_image.get("alt"), source_image.get("title")
        if (src not in {"images/covers.jpg", "images/tps.jpg"} or not alt or alt != title
                or marker.get("rend") != f"source-image-member:{src} source-alt:{alt} source-title:{title}"):
            raise ValueError("PG4272 source/TEI image semantics differ")
        graphic = etree.Element(TEI + "graphic", url=src, n=marker.get("n"))
        graphic.set(XML_ID, marker.get(XML_ID))
        graphic.set("ana", "urn:ocd:source-alt-and-title:" + quote(alt))
        graphic.tail = marker.tail
        marker.getparent().replace(marker, graphic)
    lists = [node for node in root.iter(TEI + "list") if node.get("n") is not None]
    if len(lists) != 1 or not lists[0].get("n", "").isdecimal():
        raise ValueError("PG4272 source list ordinal differs")
    lists[0].set("ana", "urn:ocd:source-ordinal:" + lists[0].attrib.pop("n"))
    if _norm(" ".join(text.itertext())) != before:
        raise ValueError("PG4272 native rendition changed complete source text")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
