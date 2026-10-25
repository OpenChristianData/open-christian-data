"""Independent full extracted-HTML and source-feature oracle for Teresa PG8120."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree, html

from build.tei.teresa_pg8120_native import (
    ARCHIVE, ARCHIVE_SHA256, COVER, COVER_SHA256, ROOT, SOURCE, SOURCE_SHA256,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
VISIBLE_SHA256 = "f90f701e32b054a5bc4b52ae060e94126eb1c5883b732a17e392f82a5ed7f3bb"
TITLE = "The Life of St. Teresa of Jesus, of the Order of Our Lady of Carmel"


def _norm(value: str) -> str:
    return " ".join(value.split())


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive = resolve_repo_path(source_root, ARCHIVE.as_posix()).read_bytes()
    cover = resolve_repo_path(source_root, COVER.as_posix()).read_bytes()
    for name, data, digest in (("HTML", source, SOURCE_SHA256),
                               ("ZIP", archive, ARCHIVE_SHA256),
                               ("cover", cover, COVER_SHA256)):
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"PG8120 {name} real-file/package hash differs")
    with zipfile.ZipFile(resolve_repo_path(source_root, ARCHIVE.as_posix())) as bundle:
        if (sorted(bundle.namelist()) != sorted([SOURCE.name, COVER.name])
                or bundle.read(SOURCE.name) != source or bundle.read(COVER.name) != cover):
            raise ValueError("PG8120 ZIP members differ from real extracted HTML/cover")
    bodies = html.fromstring(source.decode("utf-8")).xpath("//body")
    if len(bodies) != 1:
        raise ValueError("PG8120 retained HTML body count differs")
    body = bodies[0]
    direct = [node for node in body if isinstance(node.tag, str)]
    if (len(direct) != 2505 or direct[0].get("id") != "pg-header"
            or direct[-1].get("id") != "pg-footer"):
        raise ValueError("PG8120 Gutenberg wrapper or complete book boundary differs")
    book = direct[1:-1]
    if len(book) != 2503 or sum(node.tag == "pre" and not _norm("".join(node.itertext())) for node in book) != 2:
        raise ValueError("PG8120 selected book roots or empty layout pre count differs")
    visible = _norm(" ".join(str(value) for node in book for value in node.xpath(".//text()") if str(value).strip()))
    if sha256(visible.encode()).hexdigest() != VISIBLE_SHA256:
        raise ValueError("PG8120 complete selected source text differs")
    root = etree.fromstring(candidate)
    ns = {"tei": TEI_NS}
    text_nodes = root.xpath("/tei:TEI/tei:text", namespaces=ns)
    if len(text_nodes) != 1 or text_nodes[0].get(XML_LANG) != "en":
        raise ValueError("PG8120 accepted text/language envelope differs")
    if _norm(" ".join(text_nodes[0].itertext())) != visible:
        raise ValueError("PG8120 complete ordered source/TEI text differs")
    if root.xpath("string(/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)", namespaces=ns) != TITLE:
        raise ValueError("PG8120 electronic title differs")
    if not all(value in visible for value in ("Third Edition Enlarged", "David Lewis", "Benedict Zimmerman", "MCMIV")):
        raise ValueError("PG8120 third-edition title/translator matter differs")
    source_nodes = [node for base in book for node in [base, *base.xpath(".//*")]]
    abbreviations = [node for node in source_nodes if node.tag == "abbr"]
    titled_abbr = [node for node in abbreviations if node.get("title")]
    tei_abbr = root.xpath("//tei:abbr", namespaces=ns)
    expanded = root.xpath("//tei:seg[@ana='urn:ocd:abbreviation-expansion']/tei:abbr", namespaces=ns)
    if len(abbreviations) != 529 or len(titled_abbr) != 528 or len(tei_abbr) != 529 or len(expanded) != 528:
        raise ValueError("PG8120 abbreviation/expansion counts differ")
    for position, (source_abbr, rendered_abbr) in enumerate(zip(titled_abbr, expanded), 1):
        parent = rendered_abbr.getparent()
        if parent.get("n") != source_abbr.get("title") or _norm("".join(rendered_abbr.itertext())) != _norm("".join(source_abbr.itertext())):
            raise ValueError(f"PG8120 abbreviation expansion {position} differs")
    citations = [node for node in source_nodes if node.tag == "cite"]
    tei_citations = root.xpath("//tei:seg[@rend='citation']/tei:title", namespaces=ns)
    if len(citations) != 337 or len(tei_citations) != 337:
        raise ValueError("PG8120 cited-title counts differ")
    for position, (source_title, rendered_title) in enumerate(zip(citations, tei_citations), 1):
        if _norm("".join(source_title.itertext())) != _norm("".join(rendered_title.itertext())):
            raise ValueError(f"PG8120 cited title {position} differs")
    separators = root.xpath("//tei:milestone[@unit='source-horizontal-rule']", namespaces=ns)
    if sum(node.tag == "hr" for node in source_nodes) != 112 or len(separators) != 112:
        raise ValueError("PG8120 source typographic separator count differs")
    source_languages = Counter(node.get("lang") for node in source_nodes if node.get("lang") in {"es", "la", "fr", "he"})
    tei_languages = Counter(node.get(XML_LANG) for node in text_nodes[0].iter() if node.get(XML_LANG) in {"es", "la", "fr", "he"})
    if source_languages != tei_languages or sum(source_languages.values()) != 300:
        raise ValueError("PG8120 source language-mark sequence/count differs")
    source_note_links = [node for node in source_nodes if node.tag == "a" and (node.get("href") or "").startswith("#")
                         and "note" in node.get("href", "") and _norm("".join(node.itertext())).isdigit()]
    tei_note_links = root.xpath("//tei:ref[@type='note']", namespaces=ns)
    tei_notes = root.xpath("//tei:note[@place='end']", namespaces=ns)
    ids = {node.get(XML_ID) for node in root.iter() if node.get(XML_ID)}
    if (len(source_note_links) != 730 or len(tei_note_links) != 730 or len(tei_notes) != 730
            or any((ref.get("target") or "").removeprefix("#") not in ids for ref in tei_note_links)):
        raise ValueError("PG8120 source note reference/body accounting differs")
    note_by_source_id = {}
    for note in tei_notes:
        corresp = note.get("corresp", "")
        source_id = corresp.rsplit("#", 1)[-1]
        if "#" not in corresp or not source_id or source_id in note_by_source_id:
            raise ValueError("PG8120 source note anchor mapping differs")
        note_by_source_id[source_id] = note
    for position, (source_ref, tei_ref) in enumerate(zip(source_note_links, tei_note_links), 1):
        source_id = source_ref.get("href", "").removeprefix("#")
        note = note_by_source_id.get(source_id)
        if (note is None or tei_ref.get("target") != "#" + note.get(XML_ID, "")
                or _norm("".join(source_ref.itertext())) != tei_ref.get("n")):
            raise ValueError(f"PG8120 source note target {position} differs")
    if (len(root.xpath("//tei:body//tei:div[@type='chapter']", namespaces=ns)) != 40
            or len(root.xpath("//tei:back//tei:div[@type='relation']", namespaces=ns)) != 11
            or len(root.xpath("//tei:back//tei:div[@type='index']", namespaces=ns)) != 1
            or root.xpath("//tei:pb", namespaces=ns)):
        raise ValueError("PG8120 Life/Relations/Index boundary or invented page differs")
    return dict(contract="ocd-pg8120-independent-extracted-html-oracle-v1",
                source_sha256=SOURCE_SHA256, archive_sha256=ARCHIVE_SHA256,
                cover_sha256=COVER_SHA256, selected_direct_roots=len(book),
                visible_sha256=VISIBLE_SHA256, abbreviations=len(abbreviations),
                titled_abbreviations=len(titled_abbr), citations=len(citations),
                typographic_breaks=len(separators), language_marks=sum(source_languages.values()),
                note_links=len(tei_note_links), note_bodies=len(tei_notes),
                life_chapters=40, relations=11, title=TITLE)
