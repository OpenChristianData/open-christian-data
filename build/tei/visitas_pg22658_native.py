"""Native-safe source-specific rendition of the complete PG22658 Portuguese HTML."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/22658/html/pg22658-images.html")
SOURCE_SHA256 = "41453261d2b07071df4997d28dc7fe290d12fc7a22e7648f4127dd3de9b12ec6"
ARCHIVE = Path("raw/gutenberg/22658/pg22658-h.zip")
ARCHIVE_SHA256 = "5a9dfe34e2c4e2b2b5c37937f4630ac141fc7d194bb30fb2ae2858a404b8b430"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260923/pg22658-l789-v6/package/content.tei.xml")
DIRECT_SHA256 = "79ec1874bbbb5e5976e6f5a770128e846f30c0e8dd27114adf43c810a2b67bde"
IMAGE_SHA256 = {
    "images/011.png": "00daa20a94356eb5bf5459ffe27a8115d28f4ef67dfbfac902389bc9f414c3ea",
    "images/168.png": "bcfec1eb6a82932ef4a0fdc3350018d3a0fdb1ff8a8611a687f1527ca9b24892",
    "images/229.png": "c71753c157e47047bcf8dee5d9b1e301310a131e54355bab4db333ef141b24d4",
    "images/361.png": "cafded5d0214d730d798238a2db0c45563b6e2ff0e85daf790f820b2c794ef25",
    "22658-cover.png": "388f00f18b212049f3b8c358facc0eca35467a50dfe8bf7a91842701f5529991",
}
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def source_bindings(*, source_root: Path = ROOT) -> list[dict]:
    """Verify the ZIP as a package against all real extracted files."""
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive_path = resolve_repo_path(source_root, ARCHIVE.as_posix())
    archive = archive_path.read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256 or sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PG22658 real HTML or ZIP changed")
    files = [(SOURCE.name, SOURCE, "text/html", SOURCE_SHA256)]
    files.extend((name, SOURCE.parent / name, "image/png", digest)
                 for name, digest in IMAGE_SHA256.items())
    with ZipFile(archive_path) as bundle:
        if bundle.namelist() != [name for name, _, _, _ in files] or bundle.testzip() is not None:
            raise ValueError("PG22658 ZIP member set, order, or CRC differs")
        for name, relative, _, digest in files:
            real = resolve_repo_path(source_root, relative.as_posix()).read_bytes()
            if sha256(real).hexdigest() != digest or bundle.read(name) != real:
                raise ValueError(f"PG22658 real extracted member differs: {name}")
    return [dict(path=ARCHIVE.as_posix(), bytes=len(archive), sha256=ARCHIVE_SHA256,
                 media_type="application/zip", scope="Retained package; not text authority.")] + [
        dict(path=relative.as_posix(), bytes=resolve_repo_path(source_root, relative.as_posix()).stat().st_size,
             sha256=digest, media_type=media_type,
             scope=("Sole retained text authority." if relative == SOURCE else
                    "HTML-referenced image support." if name != "22658-cover.png" else
                    "Unreferenced extracted cover support."))
        for name, relative, media_type, digest in files
    ]


def adapt(original: bytes) -> bytes:
    """Use native horizontal rules and typed zero-width container boundaries."""
    if sha256(original).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG22658 historical complete-HTML candidate changed")
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if root.get(XML_LANG) != "pt" or text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG22658 Portuguese language envelope differs")
    text.set(XML_LANG, "pt")
    del root.attrib[XML_LANG]
    source_desc = root.find(TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "sourceDesc")
    if (source_desc is None or len(source_desc) != 1 or source_desc[0].tag != TEI + "p"
            or source_desc[0].text
            != "Project Gutenberg eBook 22658; retained archive SHA-256 " + ARCHIVE_SHA256 + "."):
        raise ValueError("PG22658 source bibliography differs")
    source_desc[0].tag = TEI + "bibl"
    markers = list(root.iter(TEI + "milestone"))
    if len(markers) != 27:
        raise ValueError("PG22658 source boundary/rule count differs")
    stack: list[str] = []
    starts = ends = rules = 0
    for marker in markers:
        unit = marker.get("unit")
        if len(marker) or (marker.text or "").strip():
            raise ValueError("PG22658 boundary marker contains text")
        if unit == "source-rule":
            if set(marker.attrib) != {"unit"}:
                raise ValueError("PG22658 horizontal rule attributes differ")
            marker.set("unit", "source-horizontal-rule")
            rules += 1
        elif unit == "source-container":
            label = marker.get("n")
            if not label or not set(marker.attrib).issubset({"unit", "n", "{http://www.w3.org/XML/1998/namespace}id"}):
                raise ValueError("PG22658 source container start differs")
            stack.append(label)
            marker.tag = TEI + "anchor"
            marker.set("type", "source-container-start")
            del marker.attrib["unit"]
            starts += 1
        elif unit == "source-container-end":
            label = marker.get("n")
            if not stack or stack.pop() != label or set(marker.attrib) != {"unit", "n"}:
                raise ValueError("PG22658 source container nesting differs")
            marker.tag = TEI + "anchor"
            marker.set("type", "source-container-end")
            del marker.attrib["unit"]
            ends += 1
        else:
            raise ValueError(f"PG22658 unsupported source marker: {unit}")
    if stack or (starts, ends, rules) != (7, 7, 13):
        raise ValueError("PG22658 complete container/rule inventory differs")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
