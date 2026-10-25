"""Native-safe rendition of the complete retained PG35873 biography candidate."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from zipfile import ZipFile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/35873/html/pg35873-images.html")
SOURCE_SHA256 = "dae8b3f359d08307b3214fca35fc465f87ef7111aecba98919afba8c8b188174"
ARCHIVE = Path("raw/gutenberg/35873/pg35873-h.zip")
ARCHIVE_SHA256 = "50bf34047e7b56152cca6a9dfe1e0998cfc9e2a9aa634ea4017ad25b560b8b45"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260923/george-smith-martyn-pg35873-v4-fragment-links/package/content.tei.xml")
DIRECT_SHA256 = "c69566894cb56f7a3c3191f19800dcc5a832fe462f9808c120502f21f31a0d06"
IMAGE_SHA256 = {
    "images/frontpiece.jpg": "6fb528b30701ea70b96ffb5166dd1dc550ec58f57a399cb4712337ff618bf16e",
    "images/page013.jpg": "c2beb6432a38fa54ca3dcda48ce09cc2a29a3f22c371cc578e176138f64b014c",
    "images/page032.jpg": "b91b7b38a51f6bff99a4382780902b0545330281c39fefc1d7127474757e870d",
    "images/page037.jpg": "511e3baaf230fbe3814fb800037d7dbd3cbf84d2c785bf5047815b5f5295ce73",
    "images/page045.jpg": "9264a3d83bd4a8c9e62008eab1e66a315e29ffd54235c587ef707a6e8ed92a6b",
    "images/page159.jpg": "5e734143f3ec090386bfe97283fd6cc32512291e4033c5a24ebc10f55618882d",
    "images/page161.jpg": "97803b8a803292e5893255fd2a06c5e45e5570aa9b4966082f8f3c537b752e36",
    "images/page357.jpg": "76a1ec7ed7578cfd741cd7c3317f9c2aea9fe17d6c4ef0b973ecf7b109d6e385",
    "images/page518.jpg": "9f9d82f2dadd1fcb14b27e99d472f71b6cd408c83876bb46591225c458f739b8",
    "images/page531.jpg": "6e494f7af22763eae530b992cbabc2c451adc226080ac73de961199384516972",
    "35873-cover.png": "ff3eb03dc974e395e8d9d7a6a4f14058433b278592126ccdd4c0ca016c9d2813",
}
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def source_bindings(*, source_root: Path = ROOT) -> list[dict]:
    """Bind real extracted members and verify their exact ZIP counterparts."""
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive_path = resolve_repo_path(source_root, ARCHIVE.as_posix())
    archive = archive_path.read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256 or sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PG35873 real HTML or ZIP changed")
    files = [("pg35873-images.html", SOURCE, "text/html", SOURCE_SHA256)]
    files.extend((name, SOURCE.parent / name, "image/png" if name.endswith(".png") else "image/jpeg", digest)
                 for name, digest in IMAGE_SHA256.items())
    with ZipFile(archive_path) as bundle:
        if bundle.namelist() != [name for name, _, _, _ in files] or bundle.testzip() is not None:
            raise ValueError("PG35873 ZIP member set, order, or CRC differs")
        for name, relative, _, digest in files:
            real = resolve_repo_path(source_root, relative.as_posix()).read_bytes()
            if sha256(real).hexdigest() != digest or bundle.read(name) != real:
                raise ValueError(f"PG35873 real extracted member differs: {name}")
    return [dict(path=ARCHIVE.as_posix(), bytes=len(archive), sha256=ARCHIVE_SHA256,
                 media_type="application/zip", scope="Retained package; not text authority.")] + [
        dict(path=relative.as_posix(), bytes=resolve_repo_path(source_root, relative.as_posix()).stat().st_size,
             sha256=digest, media_type=media_type,
             scope=("Sole retained text authority." if relative == SOURCE else
                    "Referenced illustration support." if name != "35873-cover.png" else
                    "Unreferenced extracted cover support."))
        for name, relative, media_type, digest in files
    ]


def adapt(original: bytes) -> bytes:
    """Retain image descriptions/caption binding while using supported native carriers."""
    if sha256(original).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG35873 repaired complete-body candidate changed")
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG35873 source language envelope differs")
    text.set(XML_LANG, "en")
    figures = list(root.iter(TEI + "figure"))
    rules = list(root.iter(TEI + "milestone"))
    if len(figures) != 10 or len(rules) != 18:
        raise ValueError("PG35873 figure/rule counts differ")
    for figure in figures:
        children = list(figure)
        if len(children) != 2 or children[0].tag != TEI + "graphic" or children[1].tag != TEI + "p":
            raise ValueError("PG35873 figure/graphic/caption structure differs")
        graphic, caption = children
        marker = re.fullmatch(r"class:figcenter source-style:width: [0-9]+px; source-role:figure source-aria-labelledby:([A-Za-z0-9_]+)", figure.get("rend") or "")
        if marker is None or caption.get(XML_ID) != marker.group(1):
            raise ValueError("PG35873 caption reference differs")
        figure.set("corresp", "#" + marker.group(1))
        del figure.attrib["rend"]
        detail = re.fullmatch(r"source-width:[0-9]+ source-height:[0-9]+ source-alt:(.*)", graphic.get("rend") or "", re.DOTALL)
        if detail is None or not detail.group(1) or graphic.get("url") not in IMAGE_SHA256:
            raise ValueError("PG35873 image dimensions/alternate text differ")
        description = etree.Element(TEI + "figDesc")
        description.text = detail.group(1)
        figure.insert(1, description)
        del graphic.attrib["rend"]
    for rule in rules:
        if rule.get("unit") != "rule" or len(rule) or (rule.text or "").strip():
            raise ValueError("PG35873 source rule differs")
        rule.set("unit", "source-horizontal-rule")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
