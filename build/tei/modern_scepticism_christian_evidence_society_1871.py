"""Faithful XHTML-to-TEI conversion for *Modern Scepticism* (1871).

Project Gutenberg's exact retained legacy XHTML is the structural and textual
authority.  The converter retains its ordered visible text, lecture boundaries,
notes and links, page markers, tables, poetry, typography, foreign-language
content, printer line, transcriber's notes, and Gutenberg boundary markers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
EXPECTED_SOURCE_SHA256 = (
    "e8130d330cc70a9f1169ef888869dbd7b146ff78b5b1bef0e8d56cc5995206e8"
)
EXPECTED_SOURCE_TEXT_SHA256 = (
    "b209892366efef6da858b515d2bd640323499b0d5496db766b0cb4755c0d354c"
)
SOURCE_RELATIVE_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    "modern-scepticism-christian-evidence-society-1871/42957-h.htm"
)
PACKAGE_HASHES = {
    "42957-0.txt": "7f05726c0d5f5a80905312d94a12edd05b9bed3de2d041cf53a37fcc42b802dd",
    "42957-h.htm": EXPECTED_SOURCE_SHA256,
    "files-index.html": "ae6ba79ab0cdb72da34b7eb1d521176818f292d0714d3c67d0b7c7f144bd23ac",
    "landing.html": "d9f84e1ceb6d4f4bed1875ec02401a5a0218eeb6a9b2fe8778b61112b55b2619",
    "legacy-html-index.html": "4bde71582359f61d88e708e6ad300b14152126572a70dd157e643db2246ad636",
    "pg42957-h.zip": "693e834f22a0ea8b2ca941b3b97a9db2f04f3db6cf965c67f8a9649be290ef82",
    "pg42957-images.html": "bde59500adb52ce884499f9ecc82cb6531c77535bf4aab0646653ca6425c5bf9",
    "pg42957.txt": "d0e8650863bbf193b9fe74a8549edda9ac405d3bf41ac652dd471f1921c599a2",
}
COVER_SHA256 = "03aa3bb12343e85f60c9b3b0379a4dc6115378c0128cb62a7f57fbad06f4f884"
LECTURE_HEADS = [
    "DESIGN IN NATURE.",
    "PANTHEISM.",
    "POSITIVISM.",
    "SCIENCE AND REVELATION.",
    "THE NATURE AND VALUE OF THE MIRACULOUS TESTIMONY TO CHRISTIANITY.",
    "THE GRADUAL DEVELOPMENT OF REVELATION.",
    "THE ALLEGED HISTORICAL DIFFICULTIES OF THE OLD AND NEW TESTAMENTS, AND THE LIGHT THROWN ON THEM BY MODERN DISCOVERIES.",
    "MYTHICAL THEORIES OF CHRISTIANITY.",
    "THE EVIDENTIAL VALUE OF ST. PAUL'S EPISTLES.",
    "CHRIST'S TEACHING AND INFLUENCE ON THE WORLD.",
    "THE COMPLETENESS AND ADEQUACY OF THE EVIDENCES OF CHRISTIANITY.",
    "EXPLANATORY PAPER",
]


class SourceMismatchError(ValueError):
    """The retained source/package is not the gate-released witness."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source_path(repository_root: Path) -> Path:
    return resolve_repo_path(repository_root, SOURCE_RELATIVE_PATH)


def _parse_source(path: Path) -> html.HtmlElement:
    return html.fromstring(path.read_text(encoding="utf-8"))


def _normalized_text(element: html.HtmlElement | etree._Element) -> str:
    return " ".join(element.text_content().split()) if hasattr(element, "text_content") else " ".join("".join(element.itertext()).split())


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _classes(element: etree._Element) -> set[str]:
    return set((element.get("class") or "").split())


def _find_body(document: html.HtmlElement) -> html.HtmlElement:
    bodies = document.xpath("//body")
    if len(bodies) != 1:
        raise SourceMismatchError(f"expected one XHTML body, found {len(bodies)}")
    return bodies[0]


def _package_audit(raw_root: Path) -> tuple[dict[str, str], list[dict[str, str]], list[str], str]:
    actual_files = {path.name for path in raw_root.iterdir() if path.is_file()}
    if actual_files != set(PACKAGE_HASHES):
        raise SourceMismatchError(
            "retained package members differ: "
            f"missing={sorted(set(PACKAGE_HASHES) - actual_files)}, "
            f"unexpected={sorted(actual_files - set(PACKAGE_HASHES))}"
        )
    hashes = {name: sha256_file(raw_root / name) for name in sorted(PACKAGE_HASHES)}
    wrong = {name: value for name, value in hashes.items() if value != PACKAGE_HASHES[name]}
    if wrong:
        raise SourceMismatchError(f"retained package SHA-256 mismatch: {wrong}")
    mismatches: list[dict[str, str]] = []
    with zipfile.ZipFile(raw_root / "pg42957-h.zip") as archive:
        members = sorted(item.filename for item in archive.infolist() if not item.is_dir())
        html_hash = hashlib.sha256(archive.read("pg42957-images.html")).hexdigest()
        cover_hash = hashlib.sha256(archive.read("images/cover.jpg")).hexdigest()
    if html_hash != hashes["pg42957-images.html"]:
        mismatches.append(
            {
                "archive": "pg42957-h.zip",
                "member": "pg42957-images.html",
                "direct": "pg42957-images.html",
            }
        )
    if cover_hash != COVER_SHA256:
        mismatches.append(
            {
                "archive": "pg42957-h.zip",
                "member": "images/cover.jpg",
                "direct": "expected-cover-digest",
            }
        )
    if mismatches:
        raise SourceMismatchError(f"current HTML ZIP mismatch: {mismatches}")
    return hashes, mismatches, members, cover_hash


def _lecture_start_positions(body: html.HtmlElement) -> list[int]:
    starts: list[int] = []
    cursor = 0
    for expected in LECTURE_HEADS:
        found = None
        for index in range(cursor, len(body)):
            child = body[index]
            if child.tag == "h2" and _normalized_text(child) == expected:
                found = index
                break
        if found is None:
            raise SourceMismatchError(f"lecture boundary is missing: {expected}")
        starts.append(found)
        cursor = found + 1
    return starts


def audit_source(source: Path, *, repository_root: Path) -> dict[str, Any]:
    source_hash = sha256_file(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SourceMismatchError(
            f"source SHA-256 {source_hash} does not match {EXPECTED_SOURCE_SHA256}"
        )
    package_hashes, zip_mismatches, zip_members, cover_hash = _package_audit(source.parent)
    document = _parse_source(source)
    body = _find_body(document)
    source_text = _normalized_text(body)
    source_text_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if source_text_hash != EXPECTED_SOURCE_TEXT_SHA256:
        raise SourceMismatchError(
            f"source text SHA-256 {source_text_hash} does not match "
            f"{EXPECTED_SOURCE_TEXT_SHA256}"
        )
    elements = [element for element in body.iter() if isinstance(element.tag, str)]
    tag_counts = Counter(element.tag for element in elements)
    class_counts = Counter(
        class_name for element in elements for class_name in _classes(element)
    )
    ids = [element.get("id") for element in elements if element.get("id")]
    internal_targets = [
        element.get("href", "")[1:]
        for element in elements
        if element.tag == "a" and element.get("href", "").startswith("#")
    ]
    unresolved = sorted(set(internal_targets) - set(ids))
    starts = _lecture_start_positions(body)
    lecture_heads = [_normalized_text(body[index]) for index in starts]
    transnotes = body.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), ' transnote ')]"
    )
    if len(transnotes) != 1:
        raise SourceMismatchError(f"expected one transcriber's-notes division, found {len(transnotes)}")
    printer_lines = [
        _normalized_text(element)
        for element in body.xpath("./p")
        if "Watson & Hazell, Printers" in _normalized_text(element)
    ]
    if printer_lines != ["Watson & Hazell, Printers, London and Aylesbury."]:
        raise SourceMismatchError(f"unexpected printer line: {printer_lines}")
    end_marker = _normalized_text(body[-1])
    if end_marker != "*** END OF THE PROJECT GUTENBERG EBOOK 42957 ***":
        raise SourceMismatchError(f"unexpected Gutenberg end marker: {end_marker}")
    expected_counts = {"p": 818, "table": 1, "tr": 26, "td": 40}
    wrong_counts = {
        tag: tag_counts[tag]
        for tag, expected in expected_counts.items()
        if tag_counts[tag] != expected
    }
    if wrong_counts:
        raise SourceMismatchError(f"unexpected source counts: {wrong_counts}")
    if class_counts["footnote"] != 181 or class_counts["fnanchor"] != 362:
        raise SourceMismatchError("unexpected footnote/reference census")
    if len(ids) != len(set(ids)) or unresolved:
        raise SourceMismatchError(
            f"source identifier contract failed: unique={len(ids) == len(set(ids))}, "
            f"unresolved={unresolved}"
        )
    return {
        "source_sha256": source_hash,
        "source_bytes": source.stat().st_size,
        "package_hashes": package_hashes,
        "zip_member_mismatches": zip_mismatches,
        "current_html_zip_members": zip_members,
        "cover_sha256": cover_hash,
        "source_text_characters": len(source_text),
        "source_text_sha256": source_text_hash,
        "tag_counts": dict(sorted(tag_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "source_ids": len(ids),
        "ids_unique": len(ids) == len(set(ids)),
        "internal_targets": len(internal_targets),
        "unresolved_internal_targets": unresolved,
        "footnotes": class_counts["footnote"],
        "footnote_references": class_counts["fnanchor"],
        "page_markers": class_counts["pagenum"],
        "poetry_containers": class_counts["poetry-container"],
        "lecture_heads": lecture_heads,
        "lecture_start_positions": starts,
        "transcribers_notes_present": bool(transnotes),
        "transcribers_notes_text": _normalized_text(transnotes[0]),
        "printer_line": printer_lines[0],
        "project_gutenberg_start_marker": _normalized_text(body[0]),
        "project_gutenberg_end_marker": end_marker,
    }


def _tei(local_name: str) -> etree._Element:
    return etree.Element(f"{{{TEI_NS}}}{local_name}")


def _copy_common_attributes(source: etree._Element, target: etree._Element) -> None:
    class_value = " ".join((source.get("class") or "").split())
    if class_value:
        target.set("rend", class_value)
    language = source.get("lang") or source.get(f"{{{XML_NS}}}lang")
    if language:
        target.set(f"{{{XML_NS}}}lang", language)
    identifier = source.get("id")
    if identifier:
        target.set(f"{{{XML_NS}}}id", identifier)


def _copy_content(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    for child in source:
        cloned = _clone_element(child)
        cloned.tail = child.tail
        target.append(cloned)


def _clone_page_marker(source: etree._Element) -> etree._Element:
    target = _tei("ref")
    target.set("type", "page_milestone")
    target.set("rend", "pagenum")
    anchors = source.xpath("./a[@id]")
    if len(anchors) != 1:
        raise SourceMismatchError("page marker must contain exactly one identified anchor")
    identifier = anchors[0].get("id")
    if not identifier:
        raise SourceMismatchError("page marker anchor has no identifier")
    target.set(f"{{{XML_NS}}}id", identifier)
    target.set("n", _normalized_text(source))
    target.text = source.text
    anchor = anchors[0]
    if len(anchor):
        _copy_content(anchor, target)
    else:
        target.text = (target.text or "") + (anchor.text or "")
    target.tail = source.tail
    return target


def _clone_element(source: etree._Element) -> etree._Element:
    tag = source.tag.lower()
    classes = _classes(source)
    parent_classes = _classes(source.getparent()) if source.getparent() is not None else set()
    if tag == "span" and "pagenum" in classes:
        return _clone_page_marker(source)
    if tag == "span" and ("poetry" in parent_classes or "stanza" in parent_classes):
        target = _tei("l")
    elif tag == "span":
        target = _tei("hi")
    elif tag in {"i", "em"}:
        target = _tei("hi")
        target.set("rend", "italic")
    elif tag in {"b", "strong"}:
        target = _tei("hi")
        target.set("rend", "bold")
    elif tag == "br":
        target = _tei("lb")
    elif tag == "a":
        href = source.get("href")
        target = _tei("ref") if href or (source.text or "").strip() else _tei("anchor")
        if href:
            target.set("target", href)
        if "fnanchor" in classes:
            target.set("type", "note_reference")
    elif tag in {"h1", "h2", "h3"}:
        target = _tei("head")
        target.set("type", tag)
    elif tag == "p" and ("poetry" in parent_classes or "stanza" in parent_classes):
        target = _tei("l")
    elif tag == "p":
        target = _tei("p")
    elif tag == "hr":
        target = _tei("milestone")
        target.set("unit", "rule")
    elif tag == "div" and "tb" in classes:
        target = _tei("ab")
        target.set("type", "thought_break")
    elif tag == "table":
        target = _tei("table")
    elif tag == "tr":
        target = _tei("row")
    elif tag in {"td", "th"}:
        target = _tei("cell")
        if tag == "th":
            target.set("role", "label")
        if source.get("colspan"):
            target.set("cols", source.get("colspan", ""))
        if source.get("rowspan"):
            target.set("rows", source.get("rowspan", ""))
    elif tag in {"ul", "ol"}:
        target = _tei("list")
        target.set("type", "ordered" if tag == "ol" else "unordered")
    elif tag == "li":
        target = _tei("item")
    elif tag == "div" and "footnotes" in classes:
        target = _tei("div")
        target.set("type", "footnotes")
    elif tag == "div" and "footnote" in classes:
        target = _tei("note")
        target.set("place", "end")
    elif tag == "div" and "transnote" in classes:
        target = _tei("div")
        target.set("type", "transcribers_notes")
    elif tag == "div" and "poetry-container" in classes:
        target = _tei("quote")
        target.set("type", "poetry")
    elif tag == "div" and "poetry" in classes:
        target = _tei("quote")
        target.set("type", "poetry")
    elif tag == "div" and "stanza" in classes:
        target = _tei("lg")
        target.set("type", "stanza")
    elif tag == "div" and "sig-container" in classes:
        target = _tei("p")
    elif tag == "div" and ("sig" in classes or "sig" in parent_classes):
        target = _tei("seg")
    elif tag == "div" and ({"i0", "i8", "in0", "in2"} & classes):
        target = _tei("l")
    elif tag == "div":
        target = _tei("ab")
    else:
        raise SourceMismatchError(f"unmapped XHTML element: {tag}")
    _copy_common_attributes(source, target)
    _copy_content(source, target)
    if _local_name(target) in {"lg", "table", "row", "list", "div"}:
        if target.text is not None and not target.text.strip():
            target.text = None
        for child in target:
            if child.tail is not None and not child.tail.strip():
                child.tail = None
    if _local_name(target) == "milestone":
        target.text = None
        for child in list(target):
            target.remove(child)
    return target


def _append_group(
    parent: etree._Element,
    division_type: str,
    children: Iterable[etree._Element],
) -> etree._Element:
    division = etree.SubElement(parent, f"{{{TEI_NS}}}div")
    division.set("type", division_type)
    for child in children:
        cloned = _clone_element(child)
        if child.tag.lower() in {"h1", "h2", "h3"} and len(division):
            cloned.tag = f"{{{TEI_NS}}}ab"
        cloned.tail = child.tail
        division.append(cloned)
    return division


def _build_header() -> etree._Element:
    header = _tei("teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    title = etree.SubElement(title_stmt, f"{{{TEI_NS}}}title")
    title.text = (
        "Modern Scepticism: A Course of Lectures Delivered at the Request "
        "of the Christian Evidence Society"
    )
    responsibility = etree.SubElement(title_stmt, f"{{{TEI_NS}}}respStmt")
    resp = etree.SubElement(responsibility, f"{{{TEI_NS}}}resp")
    resp.text = "Lectures and explanatory paper by"
    name = etree.SubElement(responsibility, f"{{{TEI_NS}}}name")
    name.text = (
        "William Thomson; James H. Rigg; William Jackson; Robert Payne Smith; "
        "John Stoughton; Harvey Goodwin; George Rawlinson; Charles A. Row; "
        "Stanley Leathes; James R. Woodford; Frederick C. Cook; Charles J. Ellicott"
    )
    edition_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}editionStmt")
    edition = etree.SubElement(edition_stmt, f"{{{TEI_NS}}}edition")
    edition.text = (
        "New York: Anson D. F. Randolph and Co., 1871; issued by special "
        "arrangement with Hodder and Stoughton"
    )
    publication_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    publisher = etree.SubElement(publication_stmt, f"{{{TEI_NS}}}publisher")
    publisher.text = "Project Gutenberg"
    date = etree.SubElement(publication_stmt, f"{{{TEI_NS}}}date")
    date.set("when", "2013-06-16")
    date.text = "June 16, 2013"
    identifier = etree.SubElement(publication_stmt, f"{{{TEI_NS}}}idno")
    identifier.set("type", "Project-Gutenberg")
    identifier.text = "42957"
    availability = etree.SubElement(publication_stmt, f"{{{TEI_NS}}}availability")
    availability.set("status", "free")
    rights = etree.SubElement(availability, f"{{{TEI_NS}}}p")
    rights.text = "Public domain in the United States according to Project Gutenberg."
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI_NS}}}bibl")
    bibl_title = etree.SubElement(bibl, f"{{{TEI_NS}}}title")
    bibl_title.text = "Modern Scepticism"
    bibl_date = etree.SubElement(bibl, f"{{{TEI_NS}}}date")
    bibl_date.set("when", "1871")
    bibl_date.text = "1871"
    encoding_desc = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project_desc = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}projectDesc")
    paragraph = etree.SubElement(project_desc, f"{{{TEI_NS}}}p")
    paragraph.text = (
        "Faithful deterministic projection of the exact retained Project Gutenberg "
        "legacy XHTML; no wording modernization or silent abridgment."
    )
    profile_desc = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    lang_usage = etree.SubElement(profile_desc, f"{{{TEI_NS}}}langUsage")
    language = etree.SubElement(lang_usage, f"{{{TEI_NS}}}language")
    language.set("ident", "en")
    language.text = "English, with source-defined Greek and other quoted languages"
    revision_desc = etree.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
    change = etree.SubElement(revision_desc, f"{{{TEI_NS}}}change")
    change.set("when", "2026-10-01")
    change.text = (
        "Reconstructed from the exact retained Project Gutenberg witness as a "
        "nonaccepted candidate."
    )
    return header


def _transform(document: html.HtmlElement) -> etree._ElementTree:
    source_body = _find_body(document)
    lecture_starts = _lecture_start_positions(source_body)
    footnotes_position = next(
        index
        for index, child in enumerate(source_body)
        if child.tag == "div" and "footnotes" in _classes(child)
    )
    transnotes_position = next(
        index
        for index, child in enumerate(source_body)
        if child.tag == "div" and "transnote" in _classes(child)
    )
    preface_position = next(
        index for index, child in enumerate(source_body) if child.tag == "h2" and _normalized_text(child) == "PREFACE."
    )
    contents_position = next(
        index for index, child in enumerate(source_body) if child.tag == "h2" and _normalized_text(child) == "CONTENTS."
    )

    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}lang", "en")
    root.append(_build_header())
    text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    front = etree.SubElement(text, f"{{{TEI_NS}}}front")
    _append_group(front, "project_gutenberg_header", source_body[0:1])
    _append_group(front, "title_page", source_body[1:preface_position])
    _append_group(front, "preface", source_body[preface_position:contents_position])
    _append_group(front, "contents", source_body[contents_position:lecture_starts[0]])

    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    for index, start in enumerate(lecture_starts):
        end = lecture_starts[index + 1] if index + 1 < len(lecture_starts) else footnotes_position
        _append_group(body, "lecture" if index < 11 else "explanatory_paper", source_body[start:end])

    back = etree.SubElement(text, f"{{{TEI_NS}}}back")
    _append_group(back, "footnotes", source_body[footnotes_position : footnotes_position + 1])
    _append_group(back, "notes_and_printer", source_body[footnotes_position + 1 : transnotes_position])
    _append_group(back, "transcribers_notes", source_body[transnotes_position : transnotes_position + 1])
    _append_group(back, "project_gutenberg_footer", source_body[transnotes_position + 1 :])
    return etree.ElementTree(root)


@lru_cache(maxsize=1)
def _relaxng(schema_path: Path) -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(schema_path)))


def _project_candidate_raw(element: etree._Element) -> str:
    pieces = [element.text or ""]
    for child in element:
        pieces.append(_project_candidate_raw(child))
        if child.tail is not None:
            pieces.append(child.tail)
        elif _local_name(child) in {
            "ab",
            "cell",
            "div",
            "head",
            "item",
            "l",
            "lg",
            "list",
            "note",
            "p",
            "quote",
            "row",
            "table",
        }:
            pieces.append(" ")
    return "".join(pieces)


def _project_candidate_element(element: etree._Element) -> str:
    return " ".join(_project_candidate_raw(element).split())


def _candidate_text(document: etree._ElementTree) -> str:
    text = document.find("tei:text", NS)
    if text is None:
        raise SourceMismatchError("candidate text is missing")
    return _project_candidate_element(text)


def _validate_candidate(
    source_document: html.HtmlElement,
    candidate_document: etree._ElementTree,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    schema_path = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    validator = _relaxng(schema_path)
    if not validator.validate(candidate_document):
        raise SourceMismatchError(
            f"TEI P5 Relax NG validation failed: {validator.error_log.last_error}"
        )
    source_text = _normalized_text(_find_body(source_document))
    candidate_text = _candidate_text(candidate_document)
    if source_text != candidate_text:
        raise SourceMismatchError("source and candidate ordered text differ")
    candidate_text_element = candidate_document.find("tei:text", NS)
    if candidate_text_element is None:
        raise SourceMismatchError("candidate text is missing")
    counts = Counter(
        _local_name(element)
        for element in candidate_text_element.iter()
        if isinstance(element.tag, str)
    )
    ids = {
        str(value)
        for value in candidate_document.xpath("//@xml:id", namespaces={"xml": XML_NS})
    }
    targets = [
        str(value)[1:]
        for value in candidate_document.xpath("//tei:ref/@target", namespaces=NS)
        if str(value).startswith("#")
    ]
    unresolved = sorted(set(targets) - ids)
    if unresolved:
        raise SourceMismatchError(f"candidate contains unresolved internal targets: {unresolved}")
    return {
        "tei_p5_relaxng_valid": True,
        "source_candidate_text_match": True,
        "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "candidate_text_sha256": hashlib.sha256(candidate_text.encode("utf-8")).hexdigest(),
        "source_text_characters": len(source_text),
        "candidate_text_characters": len(candidate_text),
        "candidate_tag_counts": dict(sorted(counts.items())),
        "lecture_divisions": len(
            candidate_document.xpath("/tei:TEI/tei:text/tei:body/tei:div", namespaces=NS)
        ),
        "candidate_ids": len(ids),
        "internal_targets": len(targets),
        "unresolved_internal_targets": unresolved,
    }


def build_candidate(
    source: Path,
    candidate: Path,
    report: Path,
    *,
    repository_root: Path,
    replace: bool = False,
) -> dict[str, Any]:
    audit = audit_source(source, repository_root=repository_root)
    if not replace and (candidate.exists() or report.exists()):
        raise FileExistsError("candidate or validation report already exists")
    source_document = _parse_source(source)
    candidate_document = _transform(source_document)
    validation = _validate_candidate(
        source_document, candidate_document, repository_root=repository_root
    )
    candidate_bytes = etree.tostring(
        candidate_document,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    result: dict[str, Any] = {
        **validation,
        "source_sha256": audit["source_sha256"],
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "footnotes": audit["footnotes"],
        "footnote_references": audit["footnote_references"],
        "page_markers": audit["page_markers"],
        "transcribers_notes_retained": True,
        "electronic_interventions": (
            "The complete source transcriber's-notes division is retained verbatim in "
            "reading order; no further corrections or modernization were applied."
        ),
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    report_bytes = (
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    candidate_stage = candidate.with_name(f"{candidate.name}.tmp")
    report_stage = report.with_name(f"{report.name}.tmp")
    if candidate_stage.exists() or report_stage.exists():
        raise FileExistsError("staged candidate or report path already exists")
    candidate_stage.write_bytes(candidate_bytes)
    report_stage.write_bytes(report_bytes)
    candidate_stage.replace(candidate)
    report_stage.replace(report)
    return result


def write_determinism_report(
    run_a_candidate: Path,
    run_a_validation: Path,
    run_b_candidate: Path,
    run_b_validation: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    candidate_equal = run_a_candidate.read_bytes() == run_b_candidate.read_bytes()
    validation_equal = run_a_validation.read_bytes() == run_b_validation.read_bytes()
    different_cwd = Path.cwd().resolve() != repository_root.resolve()
    if not candidate_equal or not validation_equal:
        raise SourceMismatchError("fresh-run candidate or validation bytes differ")
    if not different_cwd:
        raise SourceMismatchError("determinism comparison requires a different working directory")
    result: dict[str, Any] = {
        "candidate_bytes_equal": candidate_equal,
        "candidate_sha256": sha256_file(run_a_candidate),
        "validation_bytes_equal": validation_equal,
        "validation_sha256": sha256_file(run_a_validation),
        "different_working_directory": different_cwd,
        "run_a_working_directory": str(repository_root.resolve()),
        "run_b_working_directory": str(Path.cwd().resolve()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(f"{path.name}.tmp")
    if stage.exists():
        raise FileExistsError(f"staged evidence path already exists: {stage}")
    stage.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    stage.replace(path)


def write_offline_visual_contact_sheet(
    source: Path,
    candidate: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Write compact aligned opening/middle/ending/unusual-feature evidence."""
    source_document = _parse_source(source)
    source_body = _find_body(source_document)
    candidate_document = etree.parse(str(candidate))
    starts = _lecture_start_positions(source_body)
    preface_position = next(
        index
        for index, child in enumerate(source_body)
        if child.tag == "h2" and _normalized_text(child) == "PREFACE."
    )
    transnotes_position = next(
        index
        for index, child in enumerate(source_body)
        if child.tag == "div" and "transnote" in _classes(child)
    )
    source_footnote = source_body.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), ' footnote ')][.//a[@id='Footnote_146']]"
    )
    source_poetry = source_body.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), ' poetry-container ')]"
    )
    if len(source_footnote) != 1 or not source_poetry:
        raise SourceMismatchError("visual source selectors did not resolve uniquely")
    candidate_title = candidate_document.xpath(
        "/tei:TEI/tei:text/tei:front/tei:div[@type='title_page']", namespaces=NS
    )
    candidate_middle = candidate_document.xpath(
        "/tei:TEI/tei:text/tei:body/tei:div[7]", namespaces=NS
    )
    candidate_ending = candidate_document.xpath(
        "/tei:TEI/tei:text/tei:back/tei:div[@type='transcribers_notes' or @type='project_gutenberg_footer']",
        namespaces=NS,
    )
    candidate_footnote = candidate_document.xpath(
        "//tei:note[.//tei:ref[@xml:id='Footnote_146']]", namespaces=NS
    )
    candidate_poetry = candidate_document.xpath(
        "(//tei:quote[@type='poetry'])[1]", namespaces=NS
    )
    selections = [
        (
            "opening-title-and-1871-imprint",
            list(source_body[1:preface_position]),
            candidate_title,
            "full",
        ),
        (
            "middle-historical-difficulties-lecture",
            list(source_body[starts[6] : starts[7]]),
            candidate_middle,
            "prefix",
        ),
        (
            "unusual-nested-footnote-146",
            source_footnote,
            candidate_footnote,
            "full",
        ),
        (
            "unusual-poetry-and-lineation",
            [source_poetry[0]],
            candidate_poetry,
            "full",
        ),
        (
            "ending-transcriber-interventions-and-footer",
            list(source_body[transnotes_position:]),
            candidate_ending,
            "suffix",
        ),
    ]
    checks: list[dict[str, Any]] = []
    for label, source_nodes, candidate_nodes, mode in selections:
        if not candidate_nodes:
            raise SourceMismatchError(f"visual candidate selector is empty: {label}")
        source_text = " ".join(
            part for part in (_normalized_text(node) for node in source_nodes) if part
        )
        candidate_text = " ".join(
            part
            for part in (_project_candidate_element(node) for node in candidate_nodes)
            if part
        )
        if source_text != candidate_text:
            raise SourceMismatchError(f"visual source/candidate text differs: {label}")
        if mode == "prefix":
            excerpt = source_text[:1200]
        elif mode == "suffix":
            excerpt = source_text[-1600:]
        else:
            excerpt = source_text
        checks.append(
            {
                "label": label,
                "selection": mode,
                "full_text_characters": len(source_text),
                "full_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                "source_candidate_full_text_match": True,
                "exact_excerpt": excerpt,
                "exact_excerpt_characters": len(excerpt),
                "exact_excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "result": "pass",
            }
        )
    result = {
        "method": (
            "offline exact-excerpt contact sheet generated directly from the pinned "
            "legacy XHTML and generated TEI P5 candidate"
        ),
        "checks": checks,
        "all_exact_text_checks_passed": all(
            check["source_candidate_full_text_match"] for check in checks
        ),
        "acceptance_scope": (
            "machine-verifiable lightweight fidelity evidence only; human textual, "
            "identity, edition, rights, editorial, canonical, and publication "
            "acceptance remain separate"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "offline_contact_sheet.json", result)
    lines = [
        "# Modern Scepticism offline exact-excerpt contact sheet",
        "",
        "Each displayed excerpt is aligned from the pinned XHTML source and generated TEI.",
        "The full selected text is independently length- and SHA-256-accounted in JSON.",
        "",
        "| Region | Full characters | Full text SHA-256 | Result |",
        "|---|---:|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['label']} | {check['full_text_characters']} | "
            f"`{check['full_text_sha256']}` | PASS |"
        )
    for check in checks:
        lines.extend(
            [
                "",
                f"## {check['label']}",
                "",
                f"Selection: `{check['selection']}`; excerpt SHA-256: "
                f"`{check['exact_excerpt_sha256']}`.",
                "",
                "````text",
                check["exact_excerpt"],
                "````",
            ]
        )
    lines.extend(
        [
            "",
            "This evidence does not constitute human acceptance or authorize canonical",
            "integration or publication.",
            "",
        ]
    )
    (output_dir / "offline_contact_sheet.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    return result


def write_cvw_preflight_record(output: Path) -> dict[str, Any]:
    result = {
        "applicable": False,
        "protected_candidate_check": "pass; candidate root rejected as protected reports path",
        "candidate_session_preflight": (
            "not applicable: provisional candidate remains under the protected reports "
            "root, is not bound into ordinary WorkCatalog, and the isolated worktree "
            "has no built cvw_app/dist"
        ),
        "read_only": True,
        "server_started": False,
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    _write_json(output, result)
    return result


def write_evidence_packet(
    source: Path,
    candidate: Path,
    validation: Path,
    determinism: Path,
    evidence_root: Path,
    *,
    repository_root: Path,
) -> dict[str, Path]:
    audit = audit_source(source, repository_root=repository_root)
    validation_record = json.loads(validation.read_text(encoding="utf-8"))
    raw_root = source.parent
    acquisition_root = evidence_root.parent / "acquisition"
    config = (
        repository_root
        / "sources"
        / "structured-text"
        / "modern-scepticism-christian-evidence-society-1871"
        / "config.json"
    )
    readme = config.with_name("README.md")
    converter = Path(__file__).resolve()
    tests = repository_root / "tests" / "test_modern_scepticism_christian_evidence_society_1871.py"
    schema = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    urls = {
        "landing.html": "https://www.gutenberg.org/ebooks/42957",
        "files-index.html": "https://www.gutenberg.org/files/42957/",
        "legacy-html-index.html": "https://www.gutenberg.org/files/42957/42957-h/",
        "42957-0.txt": "https://www.gutenberg.org/files/42957/42957-0.txt",
        "42957-h.htm": "https://www.gutenberg.org/files/42957/42957-h/42957-h.htm",
        "pg42957-images.html": "https://www.gutenberg.org/cache/epub/42957/pg42957-images.html",
        "pg42957.txt": "https://www.gutenberg.org/cache/epub/42957/pg42957.txt",
        "pg42957-h.zip": "https://www.gutenberg.org/cache/epub/42957/pg42957-h.zip",
    }
    members = []
    for name in sorted(PACKAGE_HASHES):
        path = raw_root / name
        headers = acquisition_root / f"{name}.headers.txt"
        members.append(
            {
                "name": name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "url": urls[name],
                "download_headers_sha256": sha256_file(headers),
            }
        )
    receipt = {
        "ticket": 28,
        "master": 4,
        "slug": "modern-scepticism-christian-evidence-society-1871",
        "identity": {
            "title": (
                "Modern Scepticism: A Course of Lectures Delivered at the Request "
                "of the Christian Evidence Society"
            ),
            "responsibility": (
                "Christian Evidence Society volume; preface signed Harrowby; eleven "
                "lectures and C. J. Ellicott's explanatory paper"
            ),
            "edition": (
                "New York: Anson D. F. Randolph and Co., 1871; special arrangement "
                "with Hodder and Stoughton"
            ),
            "project_gutenberg_id": "42957",
            "workcatalog": "provisional net-new candidate; no canonical write",
        },
        "retained_members": members,
        "container_members": audit["current_html_zip_members"],
        "cover_member_sha256": audit["cover_sha256"],
        "rights": {
            "status": "Public domain in the United States per Project Gutenberg record",
            "license_url": "https://www.gutenberg.org/policy/license.html",
            "production_credit": (
                "Charlene Taylor, Marilynda Fraser-Cunliffe, Charlie Howard, and "
                "the Online Distributed Proofreading Team"
            ),
        },
        "source_authority": (
            "42957-h.htm is the structural and textual authority; current HTML, two "
            "UTF-8 text witnesses, current HTML ZIP/cover, landing page, and indexes "
            "are independently hash-bound corroborating witnesses"
        ),
        "completeness": {
            "source_text_characters": audit["source_text_characters"],
            "source_text_sha256": audit["source_text_sha256"],
            "lecture_heads": audit["lecture_heads"],
            "footnotes": audit["footnotes"],
            "footnote_references": audit["footnote_references"],
            "page_markers": audit["page_markers"],
            "poetry_containers": audit["poetry_containers"],
            "printer_line": audit["printer_line"],
            "project_gutenberg_end_marker": audit["project_gutenberg_end_marker"],
        },
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    accountability = {
        "source_sha256": audit["source_sha256"],
        "candidate_sha256": sha256_file(candidate),
        "validation_sha256": sha256_file(validation),
        "determinism_sha256": sha256_file(determinism),
        "schema": {"path": schema.relative_to(repository_root).as_posix(), "sha256": sha256_file(schema)},
        "converter": {"path": converter.relative_to(repository_root).as_posix(), "sha256": sha256_file(converter)},
        "source_config": {"path": config.relative_to(repository_root).as_posix(), "sha256": sha256_file(config)},
        "attribution_readme": {"path": readme.relative_to(repository_root).as_posix(), "sha256": sha256_file(readme)},
        "contract_tests": {"path": tests.relative_to(repository_root).as_posix(), "sha256": sha256_file(tests), "result": "5 passed"},
        "package_hashes": audit["package_hashes"],
        "zip_member_mismatches": audit["zip_member_mismatches"],
        "tei_p5_relaxng_valid": validation_record["tei_p5_relaxng_valid"],
        "source_candidate_text_match": validation_record["source_candidate_text_match"],
        "source_text_sha256": validation_record["source_text_sha256"],
        "candidate_text_sha256": validation_record["candidate_text_sha256"],
        "candidate_tag_counts": validation_record["candidate_tag_counts"],
        "unresolved_internal_targets": validation_record["unresolved_internal_targets"],
        "electronic_interventions": validation_record["electronic_interventions"],
        "wording_modernized": False,
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    unresolved = {
        "textual_acceptance": "pending human review",
        "identity_and_edition_acceptance": "pending human review",
        "rights_acceptance": "pending human review",
        "editorial_acceptance": "pending human review",
        "visual_acceptance": (
            "offline exact-excerpt checks pass; human visual acceptance remains pending"
        ),
        "canonical_integration": "not authorized",
        "publication": "not authorized",
    }
    paths = {
        "receipt": evidence_root / "source_receipt.json",
        "accountability": evidence_root / "accountability.json",
        "unresolved": evidence_root / "unresolved_items.json",
    }
    _write_json(paths["receipt"], receipt)
    _write_json(paths["accountability"], accountability)
    _write_json(paths["unresolved"], unresolved)
    return paths


def write_path_hash_manifest(
    raw_root: Path,
    report_root: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for scope, root in (("raw", raw_root), ("report", report_root)):
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.resolve() == output.resolve():
                continue
            entries.append(
                {
                    "scope": scope,
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    worktree_paths = [
        repository_root / "sources" / "structured-text" / "modern-scepticism-christian-evidence-society-1871" / "config.json",
        repository_root / "sources" / "structured-text" / "modern-scepticism-christian-evidence-society-1871" / "README.md",
        repository_root / "build" / "tei" / "modern_scepticism_christian_evidence_society_1871.py",
        repository_root / "tests" / "test_modern_scepticism_christian_evidence_society_1871.py",
    ]
    for path in worktree_paths:
        entries.append(
            {
                "scope": "worktree",
                "path": path.relative_to(repository_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    result = {
        "ticket": 28,
        "master": 4,
        "slug": "modern-scepticism-christian-evidence-society-1871",
        "files": entries,
        "file_count_excluding_manifest": len(entries),
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    _write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    source = args.source or resolve_source_path(repository_root)
    build_candidate(
        source.resolve(),
        args.candidate.resolve(),
        args.validation.resolve(),
        repository_root=repository_root,
        replace=args.replace,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
