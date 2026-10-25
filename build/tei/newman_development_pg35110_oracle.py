"""Independent exact extracted-HTML oracle for Newman's sixth-edition PG35110."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path
from build.tei.newman_development_pg35110_native import (
    ARCHIVE, ARCHIVE_SHA256, COVER, COVER_SHA256, ROOT, SOURCE, SOURCE_SHA256,
)


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
HTML_URL = "https://www.gutenberg.org/cache/epub/35110/pg35110-images.html"
TITLE = "An Essay on the Development of Christian Doctrine"
EXPECTED_VISIBLE_SHA256 = "bbb3f7504b6851bbf0d86db09f2eed7f1a3ad96cf84340daf593ed47c383be20"


def _norm(value: str) -> str:
    return " ".join(value.split())


def _classes(node: etree._Element) -> set[str]:
    return set((node.get("class") or "").split())


def _visible_body(body: etree._Element) -> str:
    parts: list[str] = []

    def visit(node: etree._Element) -> None:
        if node.tag in {"header", "footer"} and "pg-boilerplate" in _classes(node):
            return
        if node.tag == "span" and "pagenum" in _classes(node):
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            if isinstance(child.tag, str):
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(body)
    return _norm("".join(parts))


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    source = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive = resolve_repo_path(source_root, ARCHIVE.as_posix()).read_bytes()
    cover = resolve_repo_path(source_root, COVER.as_posix()).read_bytes()
    for label, value, expected in (("HTML", source, SOURCE_SHA256),
                                   ("ZIP", archive, ARCHIVE_SHA256),
                                   ("cover", cover, COVER_SHA256)):
        if sha256(value).hexdigest() != expected:
            raise ValueError(f"PG35110 {label} retained hash differs")
    with zipfile.ZipFile(resolve_repo_path(source_root, ARCHIVE.as_posix())) as bundle:
        if bundle.namelist() != [SOURCE.name, COVER.name] or bundle.read(SOURCE.name) != source or bundle.read(COVER.name) != cover:
            raise ValueError("PG35110 extracted source differs from package members")
    document = html.fromstring(source, parser=html.HTMLParser(encoding="utf-8"))
    bodies = document.xpath("//body")
    if len(bodies) != 1:
        raise ValueError("PG35110 HTML body count differs")
    body = bodies[0]
    direct = [child for child in body if isinstance(child.tag, str)]
    header = [i for i, node in enumerate(direct) if node.get("id") == "pg-header"]
    footer = [i for i, node in enumerate(direct) if node.get("id") == "pg-footer"]
    if header != [0] or footer != [len(direct) - 1]:
        raise ValueError("PG35110 Gutenberg wrapper boundary differs")
    empty_pre = [node for node in direct[1:-1] if node.tag == "pre" and not _norm("".join(node.itertext()))]
    if len(empty_pre) != 2:
        raise ValueError("PG35110 empty HTML layout pre count differs")
    visible = _visible_body(body)
    if sha256(visible.encode()).hexdigest() != EXPECTED_VISIBLE_SHA256:
        raise ValueError("PG35110 selected source text differs")
    root = etree.fromstring(candidate)
    ns = {"tei": TEI_NS}
    text_nodes = root.xpath("/tei:TEI/tei:text", namespaces=ns)
    if len(text_nodes) != 1 or text_nodes[0].get(XML_LANG) != "en":
        raise ValueError("PG35110 accepted text/language envelope differs")
    rendered = _norm("".join(text_nodes[0].itertext()))
    if rendered != visible:
        raise ValueError("PG35110 first complete-body text stream differs")
    if root.xpath("string(/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)", namespaces=ns) != TITLE:
        raise ValueError("PG35110 electronic title differs")
    headings = [_norm("".join(node.itertext())) for node in body.xpath(".//h1")]
    if headings != ["AN ESSAY ON THE DEVELOPMENT OF CHRISTIAN DOCTRINE."]:
        raise ValueError("PG35110 retained title matter differs")
    if "SIXTH EDITION" not in visible or "February 2, 1878" not in visible or "February 23, 1878" not in visible:
        raise ValueError("PG35110 edition or prefatory date text differs")
    page_spans = body.xpath(".//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]")
    source_pages = [_norm("".join(node.itertext())) for node in page_spans]
    tei_pages = root.xpath("//tei:pb", namespaces=ns)
    if (len(source_pages) != 458 or len(tei_pages) != 458
            or source_pages != [f"[Pg {node.get('n')}]" for node in tei_pages]):
        raise ValueError("PG35110 printed-page marker sequence differs")
    greek = body.xpath(".//ins[contains(concat(' ', normalize-space(@class), ' '), ' greek ')]")
    foreign = root.xpath("//tei:foreign", namespaces=ns)
    if len(greek) != 26 or len(foreign) != 26:
        raise ValueError("PG35110 Greek source span count differs")
    for position, (source_greek, rendered_greek) in enumerate(zip(greek, foreign), 1):
        children = list(rendered_greek)
        if (rendered_greek.get(XML_LANG) != "grc" or len(children) != 1
                or children[0].tag != f"{{{TEI_NS}}}seg"
                or children[0].get("ana") != "urn:ocd:greek-transliteration"
                or children[0].get("n") != source_greek.get("title")
                or _norm("".join(children[0].itertext())) != _norm("".join(source_greek.itertext()))):
            raise ValueError(f"PG35110 Greek/transliteration span {position} differs")
    source_refs = body.xpath(".//a[contains(concat(' ', normalize-space(@class), ' '), ' fnanchor ')]")
    tei_refs = root.xpath("//tei:ref[@type='note']", namespaces=ns)
    tei_notes = root.xpath("//tei:note[@place='end']", namespaces=ns)
    source_targets = [node.get("href", "").removeprefix("#") for node in source_refs]
    tei_targets = [node.get("target", "").removeprefix("#newman-note-") for node in tei_refs]
    if (len(source_refs) != 401 or len(tei_refs) != 401 or len(tei_notes) != 400
            or source_targets != tei_targets
            or Counter(source_targets)["Footnote_315_3_296"] != 2
            or len(set(source_targets)) != 400
            or {node.get(XML_ID) for node in tei_notes} != {f"newman-note-{target}" for target in source_targets}):
        raise ValueError("PG35110 source footnote sequence or target mapping differs")
    parts = root.xpath("//tei:body/tei:div[@type='part']", namespaces=ns)
    chapters = root.xpath("//tei:body//tei:div[@type='chapter']", namespaces=ns)
    if len(parts) != 2 or len(chapters) != 12:
        raise ValueError("PG35110 part/chapter boundaries differ")
    return dict(contract="ocd-pg35110-independent-extracted-html-oracle-v1",
                source_sha256=SOURCE_SHA256, archive_sha256=ARCHIVE_SHA256,
                cover_sha256=COVER_SHA256, selected_direct_children=len(direct) - 2,
                excluded_layout_pre=2, visible_sha256=EXPECTED_VISIBLE_SHA256,
                printed_pages=458, greek_spans=26, note_references=401, note_bodies=400,
                parts=2, chapters=12, edition="sixth edition, 1878 prefatory dates",
                title=TITLE)
