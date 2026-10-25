"""Independent complete extracted-HTML oracle for Gerhardt PG30362."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree, html

from build.tei.gerhardt_pg30362_native import (
    ARCHIVE, ARCHIVE_SHA256, COVER, COVER_SHA256, ROOT, SOURCE, SOURCE_SHA256, TEI,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


VISIBLE_SHA256 = "7a920c3e0dd7f274879259e014278ace4eb7511263de107f8452de0468209bd7"


def _norm(value: str) -> str:
    return " ".join(value.split())


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive = resolve_repo_path(source_root, ARCHIVE.as_posix()).read_bytes()
    cover = resolve_repo_path(source_root, COVER.as_posix()).read_bytes()
    if (sha256(source).hexdigest() != SOURCE_SHA256
            or sha256(archive).hexdigest() != ARCHIVE_SHA256
            or sha256(cover).hexdigest() != COVER_SHA256):
        raise ValueError("PG30362 real extracted HTML/cover or ZIP hash differs")
    with zipfile.ZipFile(resolve_repo_path(source_root, ARCHIVE.as_posix())) as bundle:
        if set(bundle.namelist()) != {SOURCE.name, COVER.name}:
            raise ValueError("PG30362 ZIP member set differs")
        if bundle.read(SOURCE.name) != source or bundle.read(COVER.name) != cover:
            raise ValueError("PG30362 ZIP/real extracted member bytes differ")
    parsed = html.fromstring(source)
    body = parsed.find("body")
    if body is None or len(body) != 10 or body[0].tag != "header" or body[-1].tag != "footer":
        raise ValueError("PG30362 complete body/provider wrapper boundary differs")
    if list(body.iter("img")):
        raise ValueError("PG30362 extracted cover unexpectedly referenced in HTML")
    root = etree.fromstring(candidate)
    text = root.find(TEI + "text")
    if text is None:
        raise ValueError("PG30362 TEI text envelope differs")
    tei_body = text.find(TEI + "body")
    if tei_body is None or len(tei_body) != 1 or tei_body[0].get("type") != "complete-gutenberg-html-container":
        raise ValueError("PG30362 one complete source work container differs")
    source_text = _norm(" ".join(body.itertext()))
    candidate_text = _norm(" ".join(text.itertext()))
    if sha256(source_text.encode()).hexdigest() != VISIBLE_SHA256 or source_text != candidate_text:
        raise ValueError("PG30362 complete ordered source/TEI text differs")
    source_heads = [_norm(" ".join(node.itertext())) for node in body.iter()
                    if node.tag in {"h1", "h2", "h3", "h4"}]
    tei_heads = [_norm(" ".join(node.itertext())) for node in root.iter(TEI + "head")]
    if (len(source_heads) != 97 or source_heads != tei_heads
            or len(list(body.iter("h4"))) != 74
            or "BIOGRAPHICAL SKETCH." not in source_heads):
        raise ValueError("PG30362 complete heading/hymn sequence differs")
    source_links = [node.get("href") for node in body.iter("a") if node.get("href")]
    tei_links = [node.get("target") for node in root.iter(TEI + "ref") if node.get("target")]
    if len(source_links) != 125 or source_links != tei_links:
        raise ValueError("PG30362 complete ordered hyperlink targets differ")
    source_labels = [_norm(" ".join(node.itertext())) for node in body.iter("dt")]
    tei_labels = [_norm(" ".join(node.itertext())) for node in root.iter(TEI + "label")]
    if len(source_labels) != 94 or source_labels != tei_labels:
        raise ValueError("PG30362 first-line index labels differ")
    if (len(root.xpath("//tei:div[@type='provider-header']", namespaces={"tei": TEI[1:-1]})) != 1
            or len(root.xpath("//tei:div[@type='provider-footer']", namespaces={"tei": TEI[1:-1]})) != 1
            or list(root.iter(TEI + "graphic"))):
        raise ValueError("PG30362 typed provider wrapper or cover role differs")
    return dict(contract="ocd-pg30362-independent-complete-html-oracle-v1",
                source_sha256=SOURCE_SHA256, archive_sha256=ARCHIVE_SHA256,
                cover_sha256=COVER_SHA256, selected_direct_children=len(body),
                visible_sha256=VISIBLE_SHA256, headings=len(source_heads), hymns=74,
                hyperlink_targets=len(source_links), first_line_labels=len(source_labels),
                title="Paul Gerhardt's Spiritual Songs")
