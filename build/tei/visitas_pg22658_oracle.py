"""Independent complete real-HTML and real-image oracle for PG22658."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from lxml import etree, html

from build.tei.visitas_pg22658_native import (
    ARCHIVE, ARCHIVE_SHA256, IMAGE_SHA256, ROOT, SOURCE, SOURCE_SHA256, TEI,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


VISIBLE_SHA256 = "af06ad18205f236678ec7cfd5dfd363e228cc410eade4a3d6f17b20d258e7db8"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _norm(value: str) -> str:
    return " ".join(value.split())


def _markers(node: etree._Element, *, source: bool) -> str:
    parts = [node.text or ""]
    for child in node:
        if (source and child.tag == "br") or (not source and child.tag == TEI + "lb"):
            parts.append("\u001eBR\u001e")
        elif (source and child.tag == "hr") or (not source and child.tag == TEI + "milestone"
                                                 and child.get("unit") == "source-horizontal-rule"):
            parts.append("\u001eHR\u001e")
        else:
            parts.append(_markers(child, source=source))
        parts.append(child.tail or "")
    return "".join(parts)


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    raw = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive_path = resolve_repo_path(source_root, ARCHIVE.as_posix())
    if (sha256(raw).hexdigest() != SOURCE_SHA256
            or sha256(archive_path.read_bytes()).hexdigest() != ARCHIVE_SHA256):
        raise ValueError("PG22658 real extracted HTML or ZIP changed")
    with ZipFile(archive_path) as archive:
        if set(archive.namelist()) != {SOURCE.name, *IMAGE_SHA256} or archive.read(SOURCE.name) != raw:
            raise ValueError("PG22658 ZIP text/member set differs")
        for name, digest in IMAGE_SHA256.items():
            extracted = resolve_repo_path(source_root, (SOURCE.parent / name).as_posix()).read_bytes()
            if sha256(extracted).hexdigest() != digest or archive.read(name) != extracted:
                raise ValueError(f"PG22658 ZIP/real extracted image differs: {name}")
    body = html.fromstring(raw).find(".//body")
    if (body is None or len(body) != 5576 or body[0].tag != "header" or body[-1].tag != "footer"
            or len(list(body.iter())) - 1 != 10601):
        raise ValueError("PG22658 complete HTML/provider boundary differs")
    root = etree.fromstring(candidate)
    text = root.find(TEI + "text")
    if text is None or [etree.QName(child).localname for child in text] != ["front", "body", "back"]:
        raise ValueError("PG22658 complete front/body/back text envelope differs")
    source_text = _norm("".join(body.itertext()))
    candidate_text = _norm("".join(text.itertext()))
    if sha256(source_text.encode()).hexdigest() != VISIBLE_SHA256 or source_text != candidate_text:
        raise ValueError("PG22658 complete ordered source/TEI text differs")
    if _norm(_markers(body, source=True)) != _norm(_markers(text, source=False)):
        raise ValueError("PG22658 line-break or horizontal-rule positions differ")
    source_heads = [_norm("".join(node.itertext())) for node in body.iter()
                    if node.tag in {"h1", "h2", "h3", "h4"}]
    target_heads = [_norm("".join(node.itertext())) for node in text.iter(TEI + "head")]
    if len(source_heads) != 431 or source_heads != target_heads:
        raise ValueError("PG22658 complete heading sequence differs")
    source_links = [node.get("href") for node in body.iter("a") if node.get("href")]
    target_links = [node.get("target") for node in text.iter(TEI + "ref") if node.get("target")]
    if len(source_links) != 139 or source_links != target_links:
        raise ValueError("PG22658 ordered hyperlink targets differ")
    source_ids = {node.get("id"): node for node in body.iter() if node.get("id")}
    target_ids = {node.get(XML_ID): node for node in text.iter() if node.get(XML_ID)}
    if (len(source_ids) != 57 or len(target_ids) != 57
            or not set(source_ids).issubset(target_ids)):
        raise ValueError("PG22658 source/TEI target identity differs")
    fragments = [link[1:] for link in source_links if link.startswith("#")]
    if len(fragments) != 134 or len(set(fragments)) != 43:
        raise ValueError("PG22658 internal fragment inventory differs")
    for name in set(fragments):
        if (name not in source_ids or name not in target_ids
                or _norm("".join(source_ids[name].itertext()))
                != _norm("".join(target_ids[name].itertext()))):
            raise ValueError(f"PG22658 internal link target content differs: {name}")
    source_images = list(body.iter("img"))
    target_images = list(text.iter(TEI + "graphic"))
    if (len(source_images) != 4 or len(target_images) != 4
            or [node.get("src") for node in source_images] != [node.get("url") for node in target_images]
            or set(node.get("src") for node in source_images) != set(IMAGE_SHA256) - {"22658-cover.png"}
            or any(node.get("alt") for node in source_images)):
        raise ValueError("PG22658 four referenced images or cover role differ")
    source_paragraphs = [_norm("".join(node.itertext())) for node in body.iter("div")
                         if node.get("class") == "pg_body_wrapper"]
    target_paragraphs = [_norm("".join(node.itertext())) for node in text.iter(TEI + "p")
                         if node.get("rend") == "html-div pg_body_wrapper"]
    if len(source_paragraphs) != 5070 or source_paragraphs != target_paragraphs:
        raise ValueError("PG22658 source paragraph sequence differs")
    for source_tag, tei_tag, expected in (("br", "lb", 4210), ("hr", "milestone", 13),
                                          ("li", "item", 4)):
        if (len(list(body.iter(source_tag))) != expected
                or len(list(text.iter(TEI + tei_tag))) != expected):
            raise ValueError(f"PG22658 {source_tag}/{tei_tag} carrier inventory differs")
    markers = [node for node in text.iter(TEI + "anchor") if (node.get("type") or "").startswith("source-container-")]
    starts = [node for node in markers if node.get("type") == "source-container-start"]
    ends = [node for node in markers if node.get("type") == "source-container-end"]
    if (len(starts) != 7 or len(ends) != 7
            or [node.get("n") for node in starts]
            != ["header pg-boilerplate pgheader", "div container", "div", "div", "div", "div", "footer pg-boilerplate pgheader"]
            or not {"pg-header", "pg-machine-header", "pg-header-authlist", "pg-footer"}.issubset(target_ids)):
        raise ValueError("PG22658 provider/container boundary markers differ")
    return dict(contract="ocd-pg22658-independent-complete-html-oracle-v1",
                source_sha256=SOURCE_SHA256, archive_sha256=ARCHIVE_SHA256,
                visible_sha256=VISIBLE_SHA256, direct_children=len(body), html_carriers=10601,
                headings=len(source_heads), hyperlinks=len(source_links),
                internal_links=len(fragments), unique_internal_targets=len(set(fragments)),
                paragraphs=len(source_paragraphs), images=len(source_images),
                cover_role="unreferenced extracted support", container_pairs=7, horizontal_rules=13)
