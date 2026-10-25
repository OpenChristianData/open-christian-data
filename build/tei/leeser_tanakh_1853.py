"""Faithful one-TEI reconstruction for the retained eBible Leeser Tanakh USFM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
SOURCE_PREFIX = "source-usfm:englee/"
WORK_ID = "isaac-leeser-tanakh"
SOURCE_ID = "ebible-englee-leeser-1853-usfm"
CONVERTER_ID = "ocd-englee-leeser-usfm-to-tei-current"
CONVERTER_VERSION = "1"
PROFILE_NAME = "leeser-tanakh-1853.reconstruction-profile.json"
POLICY_NAME = "leeser-tanakh-1853.validation-policy.json"
ACCOUNTABILITY_SCHEMA_NAME = "leeser-tanakh-1853.source-accountability.schema.json"
SOURCE_ROOT = "raw/ebible/englee/usfm"


def _q(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _authority_rows(manifest: Any, role: str) -> list[dict[str, Any]]:
    return [dict(row) for row in manifest.record["authorities"] if row.get("role") == role]


def _profile(manifest: Any) -> dict[str, Any]:
    return json.loads(manifest.authority_path("leeser-profile").read_bytes())


def _source_lines(content: bytes, label: str) -> list[str]:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not strict UTF-8") from exc
    if text.startswith("\ufeff") or "\r" in text or text.endswith("\n"):
        raise ValueError(f"{label} has an unprofiled BOM, CR, or terminal newline")
    lines = text.split("\n")
    if any(not line.startswith("\\") for line in lines):
        raise ValueError(f"{label} contains an unmarked or empty source line")
    return lines


def convert(manifest: Any) -> dict[str, bytes]:
    manifest.verify()
    if manifest.record.get("work_id") != WORK_ID or manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("Leeser work/source identity binding mismatch")
    profile = _profile(manifest)
    if profile.get("work_boundary", {}).get("tei_documents") != 1:
        raise ValueError("Leeser profile does not bind exactly one TEI work")
    sources = _authority_rows(manifest, "primary-source")
    support = _authority_rows(manifest, "supporting-source")
    if len(sources) != 39:
        raise ValueError("Leeser route requires 39 ordered primary USFM members")
    expected_paths = [f"{SOURCE_ROOT}/{name}" for name in profile["book_members"]]
    if [row.get("path") for row in sources] != expected_paths:
        raise ValueError("Leeser primary member order differs from the profiled Tanakh order")
    if len(support) != 3 or {Path(str(row["path"])).name for row in support} != {"copr.htm", "keys.asc", "dejavuserif.css"}:
        raise ValueError("Leeser retained support-member set differs from profile")

    root = etree.Element(_q("TEI"), nsmap={None: TEI})
    root.set(XML_ID, WORK_ID)
    header = etree.SubElement(root, _q("teiHeader"))
    file_desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = "Isaac Leeser Tanakh"
    etree.SubElement(title_stmt, _q("author")).text = "Isaac Leeser"
    publication = etree.SubElement(file_desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("p")).text = (
        "Nonaccepted reconstruction candidate. Acceptance, rights assessment, and publication remain separate."
    )
    source_desc = etree.SubElement(file_desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = "Isaac Leeser Tanakh"
    etree.SubElement(bibl, _q("author")).text = "Isaac Leeser"
    etree.SubElement(bibl, _q("ref"), target="https://ebible.org/englee/").text = "eBible.org englee"
    encoding = etree.SubElement(header, _q("encodingDesc"))
    etree.SubElement(encoding, _q("p")).text = (
        "The top-level source title identifies one Tanakh work. All 39 ordered USFM book members, "
        "their headings, chapters, verses, and other source lines remain nested in this single TEI. "
        "Each decoded USFM line is preserved exactly in one source-line carrier; chapter boundaries "
        "are additionally represented by nested TEI divisions. No book is treated as a separate work."
    )
    etree.SubElement(encoding, _q("p")).text = (
        "The retained archive's copr.htm, keys.asc, and dejavuserif.css members are accounted for as "
        "support evidence and are not scripture text. The electronic source has not been collated "
        "against a physical 1853 printing."
    )
    profile_desc = etree.SubElement(header, _q("profileDesc"))
    lang_usage = etree.SubElement(profile_desc, _q("langUsage"))
    etree.SubElement(lang_usage, _q("language"), ident="en").text = "English"
    text_node = etree.SubElement(root, _q("text"))
    body = etree.SubElement(text_node, _q("body"))
    work = etree.SubElement(body, _q("div"), type="work")
    work.set(XML_ID, WORK_ID + "-work")
    for index, row in enumerate(sources, 1):
        name = Path(str(row["path"])).name
        raw = manifest.authority_path(f"usfm-{index:02d}").read_bytes()
        lines = _source_lines(raw, name)
        first = lines[0].split(maxsplit=2)
        if len(first) < 2 or first[0] != r"\id":
            raise ValueError(f"{name} does not begin with a valid USFM id")
        book_id = first[1]
        if book_id != profile["book_ids"][index - 1]:
            raise ValueError(f"{name} USFM id differs from source profile")
        book = etree.SubElement(work, _q("div"), type="book", n=book_id)
        book.set(XML_ID, f"{WORK_ID}-book-{book_id}")
        chapter_node = None
        chapter_ord = 0
        for line_no, line in enumerate(lines, 1):
            marker = line[1:].split(maxsplit=1)[0]
            if marker == "c":
                chapter_ord += 1
                content = line[2:].lstrip()
                label = content.split(maxsplit=1)[0] if content else ""
                if not label:
                    raise ValueError(f"{name}:{line_no} has an empty chapter label")
                chapter_node = etree.SubElement(book, _q("div"), type="chapter", n=label)
                chapter_node.set(XML_ID, f"{WORK_ID}-book-{book_id}-chapter-{chapter_ord:03d}")
            carrier_parent = chapter_node if chapter_node is not None else book
            carrier = etree.SubElement(
                carrier_parent,
                _q("ab"),
                type="usfm-source-line",
                n=str(line_no),
                corresp=f"{SOURCE_PREFIX}{name}#line={line_no}",
            )
            carrier.set(XML_SPACE, "preserve")
            carrier.text = line
    return {
        "content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True),
        "source-accountability.json": _canonical({
            "contract": "ocd-englee-source-accountability-v1",
            "source_manifest_sha256": manifest.sha256,
            "source_archive_sha256": profile["source_archive_sha256"],
            "work_id": WORK_ID,
            "work_boundary": profile["work_boundary"],
            "book_members": profile["book_members"],
            "book_ids": profile["book_ids"],
            "books": [
                {
                    "path": row["path"],
                    "bytes": row["bytes"],
                    "sha256": row["sha256"],
                    "book_id": profile["book_ids"][position],
                    "source_lines": len(_source_lines(manifest.authority_path(f"usfm-{position + 1:02d}").read_bytes(), Path(str(row["path"])).name)),
                    "chapters": sum(line[1:].split(maxsplit=1)[0] == "c" for line in _source_lines(manifest.authority_path(f"usfm-{position + 1:02d}").read_bytes(), Path(str(row["path"])).name)),
                }
                for position, row in enumerate(sources)
            ],
            "support_members": [
                {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"], "role": row["role"]}
                for row in support
            ],
            "book_count": 39,
            "source_line_count": 25239,
            "chapter_count": 929,
            "verse_count": 23145,
            "line_marker_counts": profile["expected"]["line_markers"],
            "line_mapping": "Every decoded USFM source line is one ordered TEI ab carrier with a member and line pointer.",
            "support_member_policy": profile["support_member_policy"],
            "excluded": [],
        }),
        "provenance.json": _canonical({
            "work_id": WORK_ID,
            "textual_form_id": "english",
            "edition_id": "ebible-englee-leeser-1853",
            "acquisition_id": "ebible-englee-usfm",
            "source_id": SOURCE_ID,
            "source_manifest_sha256": manifest.sha256,
            "source_archive_sha256": profile["source_archive_sha256"],
            "candidate_status": "nonaccepted",
            "human_acceptance": "not-recorded",
            "rights_assessment": "not-assessed",
            "publication_authorization": "not-established",
        }),
        "unresolved.jsonl": (
            '{"kind":"edition-collation","status":"not-performed","scope":"The retained electronic transcription has not been collated against the 1853 print witness."}\n'
        ).encode("utf-8"),
        "README.source.md": (
            "# Isaac Leeser Tanakh candidate\n\n"
            "One nonaccepted TEI reconstructs the 39 ordered eBible englee USFM book members as one work. "
            "The retained source title page names the Isaac Leeser Tanakh and identifies Isaac Leeser as translator. "
            "The ZIP's three ancillary members are hash-accounted as support evidence. This candidate does not "
            "record acceptance, a rights disposition, print collation, or publication authorization.\n"
        ).encode("utf-8"),
    }


convert.converter_id = CONVERTER_ID  # type: ignore[attr-defined]
convert.converter_version = CONVERTER_VERSION  # type: ignore[attr-defined]
