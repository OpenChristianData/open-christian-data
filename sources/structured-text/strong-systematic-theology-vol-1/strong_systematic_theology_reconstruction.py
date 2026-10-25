"""Source-local lossless TEI route for Project Gutenberg #44035, volume 1."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-strong-pg44035-volume-1-lossless-to-tei"
CONVERTER_VERSION = "2"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
WORK_ID = "strong-systematic-theology-vol-1"
SOURCE_ID = "strong-systematic-theology-vol-1-pg44035-retained"
VOLUME_RANGE = (26, 30580)
TITLE_PAGE_RANGE = (26, 62)
CONTENTS_RANGE = (63, 290)
PREFACE_RANGE = (291, 465)
PARTS = (
    ("I", 466, 4489),
    ("II", 4489, 9138),
    ("III", 9138, 19981),
    ("IV", 19981, 30581),
)
CHAPTERS = (
    ("I", 471, 2324),
    ("II", 2324, 3365),
    ("III", 3365, 4489),
    ("I", 4494, 5944),
    ("II", 5944, 7441),
    ("III", 7441, 9138),
    ("I", 9143, 11832),
    ("II", 11832, 16034),
    ("III", 16034, 19981),
    ("I", 19986, 25058),
    ("II", 25058, 29180),
    ("III", 29180, 30581),
)
TOC_ENTRY = re.compile(
    r"^(?:Preface|Part\s+|Chapter\s+|[IVXLCDM]+\.\s+|\d+\.\s+|"
    r"\d+(?:st|nd|rd|th|d)\.\s+|[A-Z]\.\s+|"
    r"(?:First|Second|Third) [Dd]ivision\.)"
)
HEADING_KINDS = {6: "section", 9: "subsection", 12: "subsubsection"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Strong authority {name} cardinality mismatch")
    return matches[0]


def _records(content: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    for number, record in enumerate(content.splitlines(keepends=True), 1):
        if record.endswith(b"\r\n"):
            payload, terminator = record[:-2], "CRLF"
        elif record.endswith(b"\n"):
            payload, terminator = record[:-1], "LF"
        else:
            payload, terminator = record, "none"
        text = payload.decode("utf-8-sig" if number == 1 else "utf-8")
        rows.append(
            {
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(record),
                "terminator": terminator,
                "text": text,
                "record_sha256": _sha(record),
            }
        )
        offset += len(record)
    if offset != len(content):
        raise ValueError("Strong source byte accounting is not contiguous")
    return rows


def _inventory_sha(rows: list[dict[str, object]]) -> str:
    return _sha(
        _canonical(
            [
                {
                    key: row[key]
                    for key in (
                        "line",
                        "byte_start",
                        "byte_end",
                        "terminator",
                        "record_sha256",
                    )
                }
                for row in rows
            ]
        )
    )


def _line_id(number: int) -> str:
    return f"strong-systematic-theology-vol-1-line-{number:05d}"


def _source_heading_blocks(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    toc_entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for number in range(66, 257):
        text = str(rows[number - 1]["text"])
        if not text.strip():
            continue
        stripped = text.strip()
        indent = len(text) - len(text.lstrip(" "))
        if TOC_ENTRY.match(stripped):
            current = {"toc_line": number, "indent": indent, "text": stripped}
            toc_entries.append(current)
        elif current is not None:
            current["text"] = f"{current['text']} {stripped}"

    body_blocks: list[dict[str, object]] = []
    block_start: int | None = None
    block_lines: list[str] = []
    for number in range(466, 30581):
        text = str(rows[number - 1]["text"])
        if text.strip():
            if block_start is None:
                block_start = number
                block_lines = []
            block_lines.append(text.strip())
        elif block_start is not None:
            body_blocks.append(
                {
                    "start_line": block_start,
                    "end_line": number - 1,
                    "text": " ".join(block_lines),
                }
            )
            block_start = None
            block_lines = []
    if block_start is not None:
        body_blocks.append(
            {"start_line": block_start, "end_line": 30580, "text": " ".join(block_lines)}
        )
    by_text: dict[str, list[dict[str, object]]] = {}
    for block in body_blocks:
        key = " ".join(str(block["text"]).split()).casefold()
        by_text.setdefault(key, []).append(block)

    matches: list[dict[str, object]] = []
    for entry in toc_entries:
        key = " ".join(str(entry["text"]).split()).casefold()
        candidates = by_text.get(key, [])
        if len(candidates) != 1:
            continue
        block = candidates[0]
        indent = int(entry["indent"])
        kind = HEADING_KINDS.get(indent)
        if kind is None:
            continue
        matches.append(
            {
                "start_line": int(block["start_line"]),
                "end_line": int(block["end_line"]),
                "kind": kind,
                "toc_line": int(entry["toc_line"]),
                "toc_indent": indent,
            }
        )
    matches.sort(key=lambda item: int(item["start_line"]))
    if len(toc_entries) != 176 or len(matches) != 159:
        raise ValueError("Strong source contents-to-body heading census drifted")
    return matches


def _expected_counts(rows: list[dict[str, object]]) -> dict[str, object]:
    selected = rows[VOLUME_RANGE[0] - 1 : VOLUME_RANGE[1]]
    headings = _source_heading_blocks(rows)
    return {
        "part_count": len(PARTS),
        "chapter_count": len(CHAPTERS),
        "part_line_numbers": [item[1] for item in PARTS],
        "chapter_line_numbers": [item[1] for item in CHAPTERS],
        "title_page_line_range": list(TITLE_PAGE_RANGE),
        "contents_line_range": list(CONTENTS_RANGE),
        "preface_line_range": list(PREFACE_RANGE),
        "volume_line_range": list(VOLUME_RANGE),
        "volume_nonblank_lines": sum(bool(str(row["text"])) for row in selected),
        "volume_blank_lines": sum(not str(row["text"]) for row in selected),
        "contents_entry_count": 176,
        "contents_body_match_count": 175,
        "mapped_heading_count": len(headings),
        "mapped_heading_line_ranges": [
            [int(item["start_line"]), int(item["end_line"])] for item in headings
        ],
        "mapped_heading_kind_counts": {
            kind: sum(item["kind"] == kind for item in headings)
            for kind in ("section", "subsection", "subsubsection")
        },
    }


def _closure_module_path(root: Path, name: str) -> Path | None:
    stem = root.joinpath(*name.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate.resolve(strict=True)
    return None


def _imports(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        package = list(path.relative_to(root).parts[:-1])
        base = ".".join(
            [
                *package[: len(package) - node.level + 1],
                *((node.module or "").split(".") if node.module else []),
            ]
        )
    return tuple(
        [base, *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")]
    )


def _repository_import_closure(root: Path, entry: Path) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        path.relative_to(root)
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = (
                tuple(alias.name for alias in node.names)
                if isinstance(node, ast.Import)
                else (_imports(path, root, node) if isinstance(node, ast.ImportFrom) else ())
            )
            for name in names:
                dependency = _closure_module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path) -> str:
    return _sha(_canonical(_repository_import_closure(root, Path(__file__))))


def _check_profile(manifest: SourceManifest, rows: list[dict[str, object]]) -> dict[str, object]:
    profile = _strict(
        manifest.authority_path("reconstruction-profile").read_bytes(),
        "Strong reconstruction profile",
    )
    source_scope = {
        "bytes": len(manifest.authority_path("retained-source").read_bytes()),
        "physical_lines": len(rows),
        "source_inventory_sha256": _inventory_sha(rows),
    }
    if (
        profile.get("contract") != "ocd-strong-pg44035-reconstruction-profile-v2"
        or profile.get("version") != 2
        or profile.get("work_id") != WORK_ID
        or profile.get("source_scope") != source_scope
        or profile.get("required_counts") != _expected_counts(rows)
        or profile.get("producer_import_closure_sha256") != _closure_digest(
            manifest.repository_root
        )
    ):
        raise ValueError("Strong profile source scope or structure floor drifted")
    return profile


def _add_front_lines(parent: etree._Element, rows: list[dict[str, object]], kind: str) -> None:
    for row in rows:
        text = str(row["text"])
        if not text:
            continue
        number = int(row["line"])
        node = etree.SubElement(parent, f"{{{TEI}}}ab")
        node.set(XML_ID, _line_id(number))
        node.set("n", str(number))
        node.set("type", f"{kind}-line")
        node.set(XML_SPACE, "preserve")
        node.text = text


def _add_section_head(
    parent: etree._Element, rows: list[dict[str, object]], kind: str
) -> None:
    first = rows[0]
    node = etree.SubElement(parent, f"{{{TEI}}}head")
    node.set(XML_ID, _line_id(int(first["line"])))
    node.set("n", str(first["line"]))
    node.set("type", kind)
    node.set(XML_SPACE, "preserve")
    node.text = str(first["text"])
    for row in rows[1:]:
        etree.SubElement(node, f"{{{TEI}}}lb")
        segment = etree.SubElement(node, f"{{{TEI}}}seg")
        segment.set(XML_ID, _line_id(int(row["line"])))
        segment.set("n", str(row["line"]))
        segment.set("type", "source-line")
        segment.set(XML_SPACE, "preserve")
        segment.text = str(row["text"])


def _add_prose(
    parent: etree._Element,
    rows: list[dict[str, object]],
    section_headings: list[dict[str, object]] | None = None,
) -> None:
    paragraph: list[dict[str, object]] = []
    by_start = {
        int(item["start_line"]): item for item in (section_headings or [])
    }
    containers: list[tuple[int, etree._Element]] = []

    def flush() -> None:
        if not paragraph:
            return
        target = containers[-1][1] if containers else parent
        node = etree.SubElement(target, f"{{{TEI}}}p")
        node.set(XML_SPACE, "preserve")
        for index, row in enumerate(paragraph):
            number = int(row["line"])
            segment = etree.SubElement(node, f"{{{TEI}}}seg")
            segment.set(XML_ID, _line_id(number))
            segment.set("n", str(number))
            segment.set("type", "source-line")
            segment.set(XML_SPACE, "preserve")
            segment.text = str(row["text"])
            if index + 1 < len(paragraph):
                etree.SubElement(node, f"{{{TEI}}}lb")
        paragraph.clear()

    index = 0
    while index < len(rows):
        row = rows[index]
        heading = by_start.get(int(row["line"]))
        if heading is not None:
            flush()
            length = int(heading["end_line"]) - int(heading["start_line"]) + 1
            kind = str(heading["kind"])
            level = {"section": 1, "subsection": 2, "subsubsection": 3}[kind]
            while containers and containers[-1][0] >= level:
                containers.pop()
            target = containers[-1][1] if containers else parent
            container = etree.SubElement(target, f"{{{TEI}}}div")
            container.set("type", kind)
            container.set("n", str(heading["start_line"]))
            _add_section_head(container, rows[index : index + length], kind)
            containers.append((level, container))
            index += length
            continue
        if str(row["text"]):
            paragraph.append(row)
        else:
            flush()
        index += 1
    flush()


def _add_head(parent: etree._Element, row: dict[str, object], kind: str) -> None:
    node = etree.SubElement(parent, f"{{{TEI}}}head")
    node.set(XML_ID, _line_id(int(row["line"])))
    node.set("n", str(row["line"]))
    node.set("type", kind)
    node.set(XML_SPACE, "preserve")
    node.text = str(row["text"])


def _build_tei(
    rows: list[dict[str, object]], source_sha: str, profile: Mapping[str, object]
) -> bytes:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = "Systematic Theology, Vol. 1"
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Augustus H. Strong"
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}p").text = (
        "Nonaccepted reconstruction candidate; publication:not_ready."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI}}}bibl")
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="work-id").text = WORK_ID
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="gutenberg").text = "44035"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="source-sha256").text = source_sha
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="edition").text = (
        "Revised and enlarged edition (Judson Press, 1907), PG#44035 (Vol. 1 of 3 files)"
    )
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="source-path").text = (
        "raw/gutenberg/pg44035.txt"
    )
    encoding = etree.SubElement(header, f"{{{TEI}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI}}}projectDesc")
    etree.SubElement(project, f"{{{TEI}}}p").text = (
        "Every nonblank line in the retained volume range is represented by a source-line "
        "carrier; contents-correlated section headings are nested at their observed levels; "
        "blank separators and the Project Gutenberg envelope remain accounted evidence-only."
    )
    text = etree.SubElement(root, f"{{{TEI}}}text")
    front = etree.SubElement(text, f"{{{TEI}}}front")
    title_page = etree.SubElement(front, f"{{{TEI}}}div", type="title-page")
    _add_front_lines(title_page, rows[TITLE_PAGE_RANGE[0] - 1 : TITLE_PAGE_RANGE[1]], "title-page")
    contents = etree.SubElement(front, f"{{{TEI}}}div", type="contents")
    _add_front_lines(contents, rows[CONTENTS_RANGE[0] - 1 : CONTENTS_RANGE[1]], "contents")
    preface = etree.SubElement(front, f"{{{TEI}}}div", type="preface")
    _add_head(preface, rows[PREFACE_RANGE[0] - 1], "preface")
    _add_prose(preface, rows[PREFACE_RANGE[0] : PREFACE_RANGE[1]])
    body = etree.SubElement(text, f"{{{TEI}}}body")
    section_headings = _source_heading_blocks(rows)
    chapter_index = 0
    for part_name, part_start, part_end in PARTS:
        part = etree.SubElement(body, f"{{{TEI}}}div", type="part", n=part_name)
        _add_head(part, rows[part_start - 1], "part")
        while chapter_index < len(CHAPTERS):
            chapter_name, chapter_start, chapter_end = CHAPTERS[chapter_index]
            if chapter_start < part_start:
                chapter_index += 1
                continue
            if chapter_start >= part_end:
                break
            chapter = etree.SubElement(part, f"{{{TEI}}}div", type="chapter", n=chapter_name)
            _add_head(chapter, rows[chapter_start - 1], "chapter")
            _add_prose(
                chapter,
                rows[chapter_start : chapter_end - 1],
                section_headings,
            )
            chapter_index += 1
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _accountability(rows: list[dict[str, object]], source_authority: Mapping[str, object]) -> dict[str, object]:
    selected = set(range(VOLUME_RANGE[0], VOLUME_RANGE[1] + 1))
    line_rows: list[dict[str, object]] = []
    for row in rows:
        number = int(row["line"])
        in_volume = number in selected
        represented = in_volume and bool(str(row["text"]))
        if represented:
            reason = "retained volume line represented in the TEI hierarchy"
            selector = f"#{_line_id(number)}"
            disposition = "represented"
        elif in_volume:
            reason = "source paragraph separator represented by TEI block structure"
            selector = None
            disposition = "evidence-only"
        else:
            reason = "Project Gutenberg wrapper or license envelope retained as evidence-only"
            selector = None
            disposition = "evidence-only"
        line_rows.append(
            {
                **row,
                "disposition": disposition,
                "reason": reason,
                "tei_selector": selector,
            }
        )
    return {
        "contract": "ocd-strong-pg44035-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member": {
            key: source_authority[key] for key in ("path", "bytes", "sha256")
        },
        "volume_line_range": list(VOLUME_RANGE),
        "physical_line_count": len(rows),
        "represented_line_count": sum(
            row["disposition"] == "represented" for row in line_rows
        ),
        "evidence_only_line_count": sum(
            row["disposition"] == "evidence-only" for row in line_rows
        ),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_inventory_sha256": _inventory_sha(rows),
        "required_counts": _expected_counts(rows),
        "lines": line_rows,
    }


def _expected_unresolved() -> list[dict[str, str]]:
    return [
        {
            "id": f"{WORK_ID}-edition-identity",
            "status": "unresolved",
            "detail": "The retained witness identifies the revised and enlarged 1907 Judson Press edition through Project Gutenberg #44035; no claim is made that the electronic transcription is a complete diplomatic facsimile of every paper-edition feature.",
        },
        {
            "id": f"{WORK_ID}-textual-form",
            "status": "unresolved",
            "detail": "The retained file is an English Project Gutenberg plain-text witness of Augustus H. Strong's volume; no separate translator or editorial contributor is asserted from the current source envelope.",
        },
        {
            "id": f"{WORK_ID}-rights",
            "status": "unresolved",
            "detail": "The Project Gutenberg wrapper states a United States basis and directs users to check local law; this candidate does not establish worldwide rights clearance or publication authorization.",
        },
        {
            "id": f"{WORK_ID}-source-envelope",
            "status": "unresolved",
            "detail": "The retained member is volume 1 of a three-file Project Gutenberg set. Only pg44035.txt is in this ticket's declared member scope; volumes 2 and 3 are not silently inferred or included.",
        },
        {
            "id": f"{WORK_ID}-human-acceptance",
            "status": "unresolved",
            "detail": "This candidate is nonaccepted and has no human textual, identity, editorial, or rights acceptance.",
        },
    ]


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("Strong source identity mismatch")
    source = source_manifest.authority_path("retained-source").read_bytes()
    source_authority = _authority(source_manifest, "retained-source")
    if len(source) != source_authority["bytes"] or _sha(source) != source_authority["sha256"]:
        raise ValueError("Strong retained source drifted")
    rows = _records(source)
    profile = _check_profile(source_manifest, rows)
    tei = _build_tei(rows, _sha(source), profile)
    accountability = _accountability(rows, source_authority)
    producer_closure = _repository_import_closure(
        source_manifest.repository_root, Path(__file__).resolve(strict=True)
    )
    producer_closure_sha = _sha(_canonical(producer_closure))
    provenance = {
        "contract": "ocd-strong-pg44035-candidate-provenance-v2",
        "status": "nonaccepted",
        "publication": "not_ready",
        "work_id": WORK_ID,
        "source_sha256": _sha(source),
        "source_manifest_sha256": source_manifest.sha256,
        "producer_import_closure": list(producer_closure),
        "producer_import_closure_sha256": producer_closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_scope": profile["source_scope"],
        "hierarchy": {
            "front": ["title-page", "contents", "preface"],
            "parts": 4,
            "chapters": 12,
            "contents_entries": 176,
            "sections": {"section": 56, "subsection": 67, "subsubsection": 36},
        },
    }
    readme = source_manifest.authority_path("attribution-readme").read_bytes()
    unresolved = b"".join(_canonical(item) for item in _expected_unresolved())
    return {
        "README.source.md": readme,
        "content.tei.xml": tei,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": unresolved,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
