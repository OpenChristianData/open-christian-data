"""Independent complete extracted-HTML oracle for Keble PG4272."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
import zipfile

from lxml import etree, html

from build.tei.keble_pg4272_native import (
    ARCHIVE, ARCHIVE_SHA256, IMAGES, ROOT, SOURCE, SOURCE_SHA256, TEI, XML_LANG,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


VISIBLE_SHA256 = "126ced22e9ab4c56b80e03380cbef186e4a8d3076ebb527c90a163c9d8fb5fd0"


def _norm(value: str) -> str:
    return " ".join(value.split())


def _line_segments(node: etree._Element, break_tag: str) -> list[str]:
    parts: list[str] = []

    def visit(item: etree._Element) -> None:
        if item.tag == break_tag:
            parts.append("\uE000")
        if item.text:
            parts.append(item.text)
        for child in item:
            visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return [_norm(part) for part in "".join(parts).split("\uE000")]


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive = resolve_repo_path(source_root, ARCHIVE.as_posix()).read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256 or sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PG4272 real HTML or ZIP hash differs")
    images = {}
    for path, digest in IMAGES:
        data = resolve_repo_path(source_root, path.as_posix()).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"PG4272 real extracted image differs: {path}")
        images["images/" + path.name] = data
    with zipfile.ZipFile(resolve_repo_path(source_root, ARCHIVE.as_posix())) as bundle:
        if set(bundle.namelist()) != {SOURCE.name, *images}:
            raise ValueError("PG4272 ZIP members differ")
        if bundle.read(SOURCE.name) != source or any(bundle.read(name) != data for name, data in images.items()):
            raise ValueError("PG4272 ZIP/real extracted member bytes differ")
    parsed = html.fromstring(source)
    body = parsed.find("body")
    if body is None or len(body) != 1459 or body[0].tag != "header" or body[-1].tag != "footer":
        raise ValueError("PG4272 complete body/provider wrapper boundary differs")
    root = etree.fromstring(candidate)
    text = root.find(TEI + "text")
    if text is None or text.get(XML_LANG) != "en" or root.get(XML_LANG) is not None:
        raise ValueError("PG4272 native language envelope differs")
    tei_body = text.find(TEI + "body")
    if tei_body is None or len(tei_body) != 1 or tei_body[0].get("type") != "complete-gutenberg-html-container":
        raise ValueError("PG4272 one complete source work container differs")
    source_text = _norm(" ".join(body.itertext()))
    tei_text = _norm(" ".join(text.itertext()))
    if sha256(source_text.encode()).hexdigest() != VISIBLE_SHA256 or source_text != tei_text:
        raise ValueError("PG4272 complete ordered source/TEI text differs")
    source_headings = [_norm(" ".join(node.itertext())) for node in body.iter()
                       if node.tag in {"h1", "h2", "h3", "h4"}]
    tei_headings = [_norm(" ".join(node.itertext())) for node in root.iter(TEI + "head")]
    if (len(source_headings) != 116 or source_headings != tei_headings
            or "THE CHRISTIAN YEAR" not in source_headings or "Ordination." not in source_headings):
        raise ValueError("PG4272 full heading sequence differs")
    source_breaks = list(body.iter("br"))
    tei_breaks = list(text.iter(TEI + "lb"))
    if len(source_breaks) != 5369 or len(tei_breaks) != 5369 or _line_segments(body, "br") != _line_segments(text, TEI + "lb"):
        raise ValueError("PG4272 complete source line-break sequence differs")
    source_images = [(node.get("src"), node.get("alt"), node.get("title"),
                      node.getparent().get("href") if node.getparent().tag == "a" else None)
                     for node in body.iter("img")]
    tei_graphics = [node for node in root.iter(TEI + "graphic")]
    if len(source_images) != len(tei_graphics) or len(source_images) != 2:
        raise ValueError("PG4272 referenced image count differs")
    for position, ((src, alt, title, linked), graphic) in enumerate(zip(source_images, tei_graphics), 1):
        if (src not in images or linked not in images or not alt or alt != title
                or graphic.getparent().tag != TEI + "ref" or graphic.getparent().get("target") != linked
                or graphic.get("url") != src
                or graphic.get("ana") != "urn:ocd:source-alt-and-title:" + quote(alt)):
            raise ValueError(f"PG4272 referenced image {position} differs")
    if (len(root.xpath("//tei:div[@type='provider-header']", namespaces={"tei": TEI[1:-1]})) != 1
            or len(root.xpath("//tei:div[@type='provider-footer']", namespaces={"tei": TEI[1:-1]})) != 1
            or len(root.xpath("//tei:ab[@type='source-block'][@subtype='source-html-pre']", namespaces={"tei": TEI[1:-1]})) != 1):
        raise ValueError("PG4272 provider wrapper or empty pre carrier differs")
    return dict(contract="ocd-pg4272-independent-complete-html-oracle-v1",
                source_sha256=SOURCE_SHA256, archive_sha256=ARCHIVE_SHA256,
                image_sha256={path.as_posix(): digest for path, digest in IMAGES},
                selected_direct_children=len(body), visible_sha256=VISIBLE_SHA256,
                headings=len(source_headings), line_breaks=len(source_breaks),
                image_references=[list(item) for item in source_images], title="The Christian Year")
