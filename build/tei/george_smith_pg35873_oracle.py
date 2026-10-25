"""Independent real-HTML source oracle for George Smith's PG35873 biography."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from lxml import etree, html

from build.tei.george_smith_pg35873_native import (
    ARCHIVE, ARCHIVE_SHA256, IMAGE_SHA256, ROOT, SOURCE, SOURCE_SHA256, TEI, XML_ID,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


VISIBLE_SHA256 = "ec2c8cf941c1e09968f3bb225364742d93247530f6856858177950fc744dd7c3"


def _norm(value: str) -> str:
    return " ".join(value.split())


def _text_without_descriptions(node: etree._Element) -> str:
    parts = [node.text or ""]
    for child in node:
        if child.tag != TEI + "figDesc":
            parts.append(_text_without_descriptions(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _markers(node: etree._Element, *, source: bool) -> str:
    parts = [node.text or ""]
    for child in node:
        if source and child.tag == "br" or not source and child.tag == TEI + "lb":
            parts.append("\u001eBR\u001e")
        elif source and child.tag == "hr" or not source and child.tag == TEI + "milestone" and child.get("unit") == "source-horizontal-rule":
            parts.append("\u001eHR\u001e")
        elif not source and child.tag == TEI + "figDesc":
            pass
        else:
            parts.append(_markers(child, source=source))
        parts.append(child.tail or "")
    return "".join(parts)


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    raw = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG35873 real extracted HTML changed")
    archive_path = resolve_repo_path(source_root, ARCHIVE.as_posix())
    if sha256(archive_path.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PG35873 ZIP package changed")
    with ZipFile(archive_path) as archive:
        if set(archive.namelist()) != {SOURCE.name, *IMAGE_SHA256} or archive.read(SOURCE.name) != raw:
            raise ValueError("PG35873 ZIP text member differs")
        for name, digest in IMAGE_SHA256.items():
            extracted = resolve_repo_path(source_root, (SOURCE.parent / name).as_posix()).read_bytes()
            if sha256(extracted).hexdigest() != digest or archive.read(name) != extracted:
                raise ValueError(f"PG35873 ZIP/real extracted image differs: {name}")
    body = html.fromstring(raw).find(".//body")
    if (body is None or len(body) != 662 or body[0].tag != "header" or body[-1].tag != "footer"
            or len(list(body.iter())) - 1 != 7230):
        raise ValueError("PG35873 complete source body boundary differs")
    root = etree.fromstring(candidate)
    text = root.find(TEI + "text")
    target = text.find(TEI + "body") if text is not None else None
    if target is None or len(target) != 1 or target[0].get("type") != "source-html-body":
        raise ValueError("PG35873 one complete TEI biography body differs")
    source_text = _norm("".join(body.itertext()))
    target_text = _norm(_text_without_descriptions(target))
    if sha256(source_text.encode()).hexdigest() != VISIBLE_SHA256 or source_text != target_text:
        raise ValueError("PG35873 complete ordered source/TEI text differs")
    if _norm(_markers(body, source=True)) != _norm(_markers(target, source=False)):
        raise ValueError("PG35873 line-break or horizontal-rule positions differ")
    source_heads = [_norm("".join(node.itertext())) for node in body.iter()
                    if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}]
    target_heads = [_norm("".join(node.itertext())) for node in target.iter(TEI + "head")]
    if len(source_heads) != 38 or source_heads != target_heads or sum(h.startswith("CHAPTER ") for h in source_heads) != 15:
        raise ValueError("PG35873 heading/chapter order differs")
    source_links = [node.get("href") for node in body.iter("a") if node.get("href")]
    target_links = [node.get("target") for node in target.iter(TEI + "ref") if node.get("target")]
    if len(source_links) != 1378 or source_links != target_links:
        raise ValueError("PG35873 ordered hyperlink targets differ")
    source_ids = {node.get("id"): node for node in body.iter() if node.get("id")}
    target_ids = {node.get(XML_ID): node for node in target.iter() if node.get(XML_ID)}
    if len(source_ids) != 832 or len(target_ids) != len([node for node in target.iter() if node.get(XML_ID)]):
        raise ValueError("PG35873 source or TEI IDs are nonunique")
    if not set(source_ids).issubset(target_ids):
        raise ValueError("PG35873 source target IDs are missing")
    fragments = [link[1:] for link in source_links if link.startswith("#")]
    if len(fragments) != 1373 or len(set(fragments)) != 619:
        raise ValueError("PG35873 source fragment inventory differs")
    for name in set(fragments):
        if (name not in source_ids or name not in target_ids
                or _norm("".join(source_ids[name].itertext())) != _norm(_text_without_descriptions(target_ids[name]))):
            raise ValueError(f"PG35873 source link target identity differs: {name}")
    source_images = list(body.iter("img"))
    target_images = list(target.iter(TEI + "graphic"))
    figures = list(target.iter(TEI + "figure"))
    source_figures = [node for node in body.iter("div") if node.get("role") == "figure"]
    if (len(source_images) != 10 or len(target_images) != 10
            or len(figures) != 10 or len(source_figures) != 10
            or [node.get("src") for node in source_images] != [node.get("url") for node in target_images]
            or set(node.get("src") for node in source_images) != set(IMAGE_SHA256) - {"35873-cover.png"}):
        raise ValueError("PG35873 illustration paths or cover role differ")
    for source_figure, figure, source_image in zip(source_figures, figures, source_images):
        caption_id = source_figure.get("aria-labelledby")
        descriptions = list(figure.iter(TEI + "figDesc"))
        if (figure.get("corresp") != "#" + str(caption_id) or caption_id not in source_ids
                or len(descriptions) != 1 or descriptions[0].text != source_image.get("alt")
                or _norm("".join(source_ids[caption_id].itertext())) != _norm(_text_without_descriptions(target_ids[caption_id]))):
            raise ValueError("PG35873 image alternate text or caption attachment differs")
    for source_tag, tei_tag, count in (("tr", "row", 46), ("td", "cell", 123),
                                       ("li", "item", 759), ("br", "lb", 262), ("hr", "milestone", 18)):
        observed = list(body.iter(source_tag))
        mapped = list(target.iter(TEI + tei_tag))
        if len(observed) != count or len(mapped) != count:
            raise ValueError(f"PG35873 {source_tag}/{tei_tag} inventory differs")
    source_tables = list(body.iter("table"))
    target_tables = list(target.iter(TEI + "table"))
    if len(source_tables) != len(target_tables) != 3:
        raise ValueError("PG35873 table inventory differs")
    for source_table, target_table in zip(source_tables, target_tables):
        source_cells = [_norm("".join(cell.itertext())) for cell in source_table.iter() if cell.tag in {"td", "th"}]
        target_cells = [_norm("".join(cell.itertext())) for cell in target_table.iter(TEI + "cell")]
        if source_cells != target_cells:
            raise ValueError("PG35873 table cell content/order differs")
    source_notes = [_norm("".join(node.itertext())) for node in body.iter("div")
                    if "footnote" in (node.get("class") or "").split()]
    target_notes = [_norm("".join(node.itertext())) for node in target.iter(TEI + "note")]
    if len(source_notes) != 109 or source_notes != target_notes:
        raise ValueError("PG35873 footnote attachment/content differs")
    for html_tag, tei_type in (("header", "provider-header"), ("footer", "provider-footer")):
        source_wrapper = list(body.iter(html_tag))
        target_wrapper = [node for node in target.iter(TEI + "div") if node.get("type") == tei_type]
        if (len(source_wrapper) != len(target_wrapper) != 1
                or _norm("".join(source_wrapper[0].itertext())) != _norm("".join(target_wrapper[0].itertext()))):
            raise ValueError("PG35873 provider wrapper differs")
    return dict(contract="ocd-pg35873-independent-extracted-html-oracle-v1",
                source_sha256=SOURCE_SHA256, archive_sha256=ARCHIVE_SHA256,
                visible_sha256=VISIBLE_SHA256, direct_children=len(body), html_carriers=7230,
                headings=38, chapters=15, links=len(source_links), internal_links=len(fragments),
                unique_internal_targets=len(set(fragments)), source_ids=len(source_ids),
                images=len(source_images), tables=3, cells=123, notes=109,
                cover_role="unreferenced extracted support")
