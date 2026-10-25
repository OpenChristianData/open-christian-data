"""Source-bound complete PG76498 Lutheran hymn-book HTML to TEI P5 route."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE = "raw/gutenberg/76498/pg76498-h.zip"
ARCHIVE_SHA = "37de1a88d36166c86377e7451ccaabd6e870259b3089c2eb01f2abbe3b67a2c5"
MEMBERS = (
    ("pg76498-images.html", 1700540, "c13e936c8b681c23ca402237581d9d9208ad0b8a34465315ea8c9138da5b6d3b"),
    ("images/cover.jpg", 126730, "eb9590ad6bf057918abea5131b785d777670e3a155a8980eca0946f328276799"),
    ("images/concordia.jpg", 3583, "089ff870cdf7c780fb50540f4b53da8aac0d8dcf47e188566f13b7b462002ad2"),
)
CONVERTER_ID = "ocd-pg76498-lutheran-hymnbook-source-bound-html-to-tei"
CONVERTER_VERSION = "1"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _e(parent: etree._Element, name: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attrs)


def _append(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _source(repository_root: Path) -> tuple[bytes, list[dict[str, object]]]:
    path = resolve_repo_path(repository_root, SOURCE)
    data = path.read_bytes()
    if len(data) != 461780 or _sha(data) != ARCHIVE_SHA:
        raise ValueError("PG76498 retained ZIP identity differs")
    rows: list[dict[str, object]] = []
    with ZipFile(path) as archive:
        infos = archive.infolist()
        if tuple(info.filename for info in infos) != tuple(item[0] for item in MEMBERS):
            raise ValueError("PG76498 archive member order or set differs")
        if archive.testzip() is not None:
            raise ValueError("PG76498 archive CRC failure")
        for info, (name, size, digest) in zip(infos, MEMBERS, strict=True):
            if info.flag_bits & 1 or info.is_dir() or ".." in Path(info.filename).parts:
                raise ValueError(f"unsafe archive member {info.filename}")
            member = archive.read(info)
            if len(member) != size or _sha(member) != digest:
                raise ValueError(f"PG76498 member identity differs: {name}")
            rows.append({"name": name, "bytes": size, "sha256": digest,
                         "crc32": f"{info.CRC:08x}",
                         "disposition": "complete HTML witness" if name.endswith(".html") else
                         ("cover/favicon support image; not visible in body" if "cover" in name else
                          "source-body concordia figure image")})
        html_bytes = archive.read("pg76498-images.html")
    decoded = html_bytes.decode("utf-8", errors="strict")
    if "\ufffd" in decoded or not decoded.startswith("<!DOCTYPE html>"):
        raise ValueError("PG76498 HTML encoding or doctype changed")
    return html_bytes, rows


def _mark(out: etree._Element, source: etree._Element, ordinal: Mapping[etree._Element, int]) -> None:
    source_id = source.get("id")
    out.set(XML_ID, source_id or f"src-{ordinal[source]:05d}")
    if source_id and not (source.tag == "span" and "pagenum" in source.get("class", "").split()):
        out.set("n", source_id)
    annotations = [f"class:{name}" for name in source.get("class", "").split()]
    for key in ("style", "title", "alt", "width", "height", "role", "dir"):
        if source.get(key):
            annotations.append(f"source-{key}:{source.get(key)}")
    if annotations:
        out.set("rend", " ".join(annotations))
    if source.get("lang"):
        out.set("{http://www.w3.org/XML/1998/namespace}lang", source.get("lang"))
    if source.get("href"):
        out.set("target", source.get("href"))
    if source.get("src"):
        out.set("url", source.get("src"))
    if source.get("colspan"):
        out.set("cols", source.get("colspan"))
    if source.get("rowspan"):
        out.set("rows", source.get("rowspan"))


def _inline(source: etree._Element, parent: etree._Element, ordinal: Mapping[etree._Element, int]) -> None:
    tag = source.tag.lower()
    classes = set(source.get("class", "").split())
    if tag == "span" and "pagenum" in classes:
        label = "".join(source.itertext())
        match = re.fullmatch(r"\[(\d+)\]", label)
        if not match or len(source):
            raise ValueError("unsupported source page marker")
        out = _e(parent, "pb", n=match.group(1))
        _mark(out, source, ordinal)
        out.set("rend", " ".join(filter(None, (out.get("rend"), f"source-label:{label}"))))
        return
    if tag in {"i", "em", "b", "strong"}:
        out = _e(parent, "hi")
        out.set("rend", "italic" if tag in {"i", "em"} else "bold")
    elif tag == "a":
        out = _e(parent, "ref", target=source.get("href")) if source.get("href") else _e(parent, "seg", type="source-anchor")
    elif tag == "img":
        out = _e(parent, "graphic", url=source.get("src", ""))
    elif tag == "br":
        out = _e(parent, "lb")
    elif tag == "span":
        out = _e(parent, "seg", type="html-span")
    else:
        raise ValueError(f"unexpected inline source tag {tag}")
    _mark(out, source, ordinal)
    if tag in {"i", "em", "b", "strong"}:
        out.set("rend", " ".join(filter(None, (out.get("rend"), "italic" if tag in {"i", "em"} else "bold"))))
    _append(out, source.text)
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("unexpected non-element in source inline flow")
        _inline(child, out, ordinal)
        _append(out, child.tail)


def _block(source: etree._Element, parent: etree._Element, ordinal: Mapping[etree._Element, int]) -> None:
    tag = source.tag.lower()
    classes = set(source.get("class", "").split())
    if tag == "div" and "verse" in classes:
        out = _e(parent, "l")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            _inline(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag == "div" and "stanza" in classes:
        out = _e(parent, "lg", type="stanza")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            if child.tag == "div" and "verse" in child.get("class", "").split():
                _block(child, out, ordinal)
            elif child.tag == "span" and "pagenum" in child.get("class", "").split():
                _inline(child, out, ordinal)
            else:
                raise ValueError(f"unexpected stanza child {child.tag}")
            _append(out, child.tail)
        return
    if tag == "div" and "footnote" in classes:
        out = _e(parent, "note", place="bottom")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            _block(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag in {"div", "header", "footer", "blockquote"}:
        kind = ("provider-header" if tag == "header" else "provider-license" if tag == "footer" else
                "poetry-container" if "poetry-container" in classes else
                "poetry" if "poetry" in classes else
                "chapter" if "chapter" in classes else
                "footnotes" if "footnotes" in classes else "html-" + tag)
        out = _e(parent, "div", type=kind)
        _mark(out, source, ordinal)
        pending: etree._Element | None = None
        def text_run(value: str | None) -> None:
            nonlocal pending
            if not value:
                return
            if not value.strip():
                _append(pending if pending is not None else out, value)
                return
            if pending is None:
                pending = _e(_e(out, "div", type="html-flow"), "p")
            _append(pending, value)
        text_run(source.text)
        for child in source:
            if not isinstance(child.tag, str):
                raise ValueError("unexpected non-element in source block flow")
            child_classes = set(child.get("class", "").split())
            if child.tag == "span" and "pagenum" in child_classes:
                pending = None
                _inline(child, out, ordinal)
            elif child.tag in {"span", "a", "i", "em", "b", "strong", "img", "br"}:
                if pending is None:
                    pending = _e(_e(out, "div", type="html-flow"), "p")
                _inline(child, pending, ordinal)
            else:
                pending = None
                _block(child, _e(out, "div", type="source-block-carrier"), ordinal)
            text_run(child.tail)
        return
    if tag in {"h1", "h2", "h3", "h4"}:
        out = _e(parent, "div", type="source-heading", subtype=f"html-heading-level-{tag[1:]}")
        _mark(out, source, ordinal)
        head = _e(out, "head")
        _append(head, source.text)
        for child in source:
            _inline(child, head, ordinal)
            _append(head, child.tail)
        return
    if tag == "p":
        out = _e(parent, "p")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            _inline(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag == "ul":
        out = _e(parent, "list", type="unordered")
        _mark(out, source, ordinal)
        for child in source:
            if child.tag != "li":
                raise ValueError(f"unexpected list child {child.tag}")
            _block(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag == "li":
        out = _e(parent, "item")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            _inline(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag == "table":
        out = _e(parent, "div", type="source-table")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            _block(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag == "tbody":
        out = _e(parent, "table")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            _block(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag == "tr":
        out = _e(parent, "row")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            _block(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag in {"td", "th"}:
        out = _e(parent, "cell", role="label" if tag == "th" else "data")
        _mark(out, source, ordinal)
        _append(out, source.text)
        for child in source:
            if child.tag in {"p", "div", "ul", "table"}:
                _block(child, out, ordinal)
            else:
                _inline(child, out, ordinal)
            _append(out, child.tail)
        return
    if tag == "figure":
        out = _e(parent, "div", type="source-figure")
        _mark(out, source, ordinal)
        figure = _e(out, "figure")
        _append(out, source.text)
        for child in source:
            if child.tag != "img":
                raise ValueError(f"unexpected figure child {child.tag}")
            _inline(child, figure, ordinal)
            _append(out, child.tail)
        return
    if tag == "hr":
        out = _e(parent, "milestone", unit="rule")
        _mark(out, source, ordinal)
        return
    if tag in {"a", "span", "br"}:
        out = _e(_e(parent, "div", type="source-inline-block"), "p")
        _inline(source, out, ordinal)
        return
    raise ValueError(f"unmapped source block tag {tag}")


def make_tei(html_bytes: bytes) -> tuple[bytes, dict[str, int]]:
    doc = html.document_fromstring(html_bytes.decode("utf-8", errors="strict"))
    body = doc.find("body")
    if doc.tag != "html" or doc.get("lang") != "en" or body is None:
        raise ValueError("PG76498 HTML shell changed")
    nodes = [node for node in body.iterdescendants() if isinstance(node.tag, str)]
    ordinal = {node: i for i, node in enumerate(nodes, 1)}
    source_ids = [node.get("id") for node in nodes if node.get("id")]
    if len(source_ids) != len(set(source_ids)) or any(
        value.startswith("src-") or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", value)
        for value in source_ids
    ):
        raise ValueError("source IDs are duplicated or collide with generated TEI IDs")
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "lutheran-hymnbook-pg76498-candidate")
    header = _e(root, "teiHeader")
    file_desc = _e(header, "fileDesc")
    title_stmt = _e(file_desc, "titleStmt")
    _e(title_stmt, "title").text = "Evangelical Lutheran Hymn-Book: Abridged Edition"
    _e(title_stmt, "author").text = "Lutheran Church—Missouri Synod"
    publication = _e(file_desc, "publicationStmt")
    _e(publication, "publisher").text = "Open Christian Data"
    _e(_e(publication, "availability", status="restricted"), "p").text = "Nonaccepted source-bound TEI candidate. Project Gutenberg labels the item public domain in the USA; broader rights review and publication are separate."
    source_desc = _e(file_desc, "sourceDesc")
    bibl = _e(source_desc, "bibl")
    _e(bibl, "title").text = "Evangelical Lutheran Hymn-Book: Abridged Edition"
    _e(bibl, "author").text = "Lutheran Church—Missouri Synod"
    _e(bibl, "pubPlace").text = "St. Louis, Mo."
    _e(bibl, "publisher").text = "Concordia Publishing House"
    _e(bibl, "date").text = "1927"
    _e(bibl, "idno", type="project-gutenberg-ebook").text = "76498"
    _e(bibl, "idno", type="retained-zip-sha256").text = ARCHIVE_SHA
    text = _e(root, "text")
    content = _e(_e(text, "body"), "div", type="source-html-body")
    section = _e(content, "div", type="front-matter")
    hymn: etree._Element | None = None
    section_count = 0
    hymn_numbers: list[int] = []
    for child in body:
        if not isinstance(child.tag, str):
            raise ValueError("unexpected source body non-element")
        classes = set(child.get("class", "").split())
        if child.tag == "div" and "chapter" in classes:
            section_count += 1
            section = _e(content, "div", type="source-section", n=str(section_count))
            hymn = None
        elif child.tag in {"h3", "h4"} and re.fullmatch(r"hymn_\d+", child.get("id", "")):
            number = int(child.get("id").split("_")[1])
            hymn_numbers.append(number)
            hymn = _e(section, "div", type="hymn", n=str(number))
        elif child.tag == "footer" and child.get("id") == "pg-footer":
            section = _e(content, "div", type="provider-footer")
            hymn = None
        owner = hymn if hymn is not None else section
        _block(child, _e(owner, "div", type="source-block-carrier"), ordinal)
        _append(owner, child.tail)
    if hymn_numbers != list(range(1, 595)) or section_count != 53 or len(nodes) != 28540:
        raise ValueError("PG76498 hymn, section, or carrier envelope changed")
    result = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    counts = Counter(node.tag for node in nodes)
    return result, {"source_html_carriers": len(nodes), "source_hymns": len(hymn_numbers),
                    "source_sections": section_count, "source_stanzas": sum("stanza" in (n.get("class") or "").split() for n in nodes),
                    "source_verse_lines": sum("verse" in (n.get("class") or "").split() for n in nodes),
                    "source_page_markers": sum("pagenum" in (n.get("class") or "").split() for n in nodes),
                    "source_images": counts["img"]}


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if source_manifest.authority_path("retained-source") != resolve_repo_path(source_manifest.repository_root, SOURCE):
        raise ValueError("PG76498 source path binding differs")
    html_bytes, members = _source(source_manifest.repository_root)
    tei_bytes, counts = make_tei(html_bytes)
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile["carrier_count"] != counts["source_html_carriers"] or profile["archive_members"] != members:
        raise ValueError("PG76498 source profile differs")
    account = {**policy["accountability"], "source_archive_sha256": ARCHIVE_SHA,
               "source_html_sha256": _sha(html_bytes), "archive_members": members,
               "tei_sha256": _sha(tei_bytes), "source_profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
               **counts}
    return {"README.source.md": source_manifest.authority_path("source-local-attribution-readme").read_bytes(),
            "content.tei.xml": tei_bytes, "source-accountability.json": _json(account),
            "provenance.json": _json(policy["provenance"]),
            "unresolved.jsonl": b"".join(_json(row) for row in policy["unresolved"])}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
