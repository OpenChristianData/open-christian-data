"""Source-local native rendition of the complete retained PG53809 HTML."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/53809/html/pg53809-images.html")
SOURCE_SHA256 = "8df472969235d6f814221b6a5eea03c48fe9d2d4de89d7f6c7c325ec3924db03"
ARCHIVE = Path("raw/gutenberg/53809/pg53809-h.zip")
ARCHIVE_SHA256 = "29b2a5fa0cae2bcb8beb8473215fd417f208456e5c9ac46683d81147ae8cda19"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260923/stephens-chrysostom-pg53809-final/package/content.tei.xml")
DIRECT_SHA256 = "1eb5f264328e9405dc5203514eed17b3bc8fbe9f7f7a58c64036032c98efa97f"
SUPPORT = {
    "images/cover.jpg": "61a8aff61f90e379094bb720ed626a003ae79dfd5ac721ed3423427ac5ef98dc",
    "images/frontispiece.jpg": "a7bc9e34e776fa87b9786b5c9ab2453099e87f826dbd89b4a78f4a2232a316c7",
}
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def source_bindings(*, source_root: Path = ROOT) -> list[dict]:
    """Bind the ZIP package and every extracted member by byte equality."""
    archive_path = resolve_repo_path(source_root, ARCHIVE.as_posix())
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    package = archive_path.read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256 or sha256(package).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PG53809 real HTML or package changed")
    members = [(SOURCE.name, SOURCE, "text/html", SOURCE_SHA256)]
    members.extend((name, SOURCE.parent / name, "image/jpeg", digest) for name, digest in SUPPORT.items())
    with ZipFile(archive_path) as archive:
        if archive.namelist() != [name for name, _, _, _ in members] or archive.testzip() is not None:
            raise ValueError("PG53809 ZIP member set, order, or CRC differs")
        for name, relative, _, digest in members:
            real = resolve_repo_path(source_root, relative.as_posix()).read_bytes()
            if sha256(real).hexdigest() != digest or archive.read(name) != real:
                raise ValueError(f"PG53809 extracted member differs: {name}")
    return [dict(path=ARCHIVE.as_posix(), bytes=len(package), sha256=ARCHIVE_SHA256,
                 media_type="application/zip", scope="Retained package; not text authority.")] + [
        dict(path=relative.as_posix(), bytes=resolve_repo_path(source_root, relative.as_posix()).stat().st_size,
             sha256=digest, media_type=media_type,
             scope=("Sole retained text authority." if relative == SOURCE else
                    "Unreferenced extracted cover support." if name == "images/cover.jpg" else
                    "HTML-referenced frontispiece support."))
        for name, relative, media_type, digest in members
    ]


def adapt(original: bytes, *, source_root: Path = ROOT) -> bytes:
    """Restore source whitespace and use supported native carriers without text loss."""
    if sha256(original).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG53809 historical direct candidate changed")
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG53809 real extracted HTML changed")
    source_body = html.fromstring(source).xpath("//body")
    if len(source_body) != 1:
        raise ValueError("PG53809 HTML body differs")
    source_lists = [node for node in source_body[0].iter("ul") if node.text == "\r\n    " and
                    "You pay a royalty fee of 20%" in "".join(node.itertext())]
    if len(source_lists) != 1:
        raise ValueError("PG53809 Gutenberg license list whitespace differs")
    root = etree.fromstring(original)
    body = root.find(".//" + TEI + "body")
    if body is None:
        raise ValueError("PG53809 candidate body is missing")
    lists = [node for node in body.iter(TEI + "list") if node.get(XML_ID) == "src-11873"]
    if len(lists) != 1 or lists[0].text not in (None, ""):
        raise ValueError("PG53809 license list carrier differs")
    lists[0].text = source_lists[0].text
    graphics = list(body.iter(TEI + "graphic"))
    if len(graphics) != 1 or graphics[0].get("url") != "images/frontispiece.jpg" or graphics[0].get("rend") != "source-width:500 source-height:648" or graphics[0].get("ana") is not None:
        raise ValueError("PG53809 frontispiece rendition differs")
    graphics[0].set("ana", "source-rend:" + graphics[0].get("rend"))
    del graphics[0].attrib["rend"]
    cells = list(body.iter(TEI + "cell"))
    if len(cells) != 74 or any(cell.get("role") != "data" or cell.get("ana") is not None for cell in cells):
        raise ValueError("PG53809 contents table roles differ")
    for cell in cells:
        cell.set("ana", "source-role:data")
        del cell.attrib["role"]
    markers = list(body.iter(TEI + "milestone"))
    if len(markers) != 32 or any(marker.get("unit") != "rule" for marker in markers):
        raise ValueError("PG53809 horizontal-rule inventory differs")
    for marker in markers:
        marker.set("unit", "source-horizontal-rule")
    source_nodes = list(source_body[0].iter())[1:]
    source_ids = {node.get("id"): f"src-{position:05d}"
                  for position, node in enumerate(source_nodes, 1) if node.get("id")}
    if len(source_ids) != 2016:
        raise ValueError("PG53809 source fragment ID inventory differs")
    local_refs = 0
    for ref in body.iter(TEI + "ref"):
        literal = ref.get("target") or ""
        if not literal.startswith("#"):
            continue
        if ref.get("n") is not None or unquote(literal[1:]) not in source_ids:
            raise ValueError("PG53809 source fragment target differs")
        ref.set("target", "#" + source_ids[unquote(literal[1:])])
        ref.set("n", literal)
        local_refs += 1
    if local_refs != 3548:
        raise ValueError("PG53809 source fragment link inventory differs")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
