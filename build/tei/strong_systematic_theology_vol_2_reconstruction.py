"""Source-bound TEI reconstruction for Project Gutenberg #44555, volume 2."""

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


CONVERTER_ID = "ocd-strong-pg44555-volume-2-lossless-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
WORK_ID = "strong-systematic-theology-vol-2"
SOURCE_ID = "strong-systematic-theology-vol-2-pg44555-retained"
EDITION = "Revised and enlarged edition (Judson Press, 1907), PG#44555 (Vol. 2 of 3 files)"
SOURCE_PATH = "raw/gutenberg/pg44555.txt"
VOLUME_RANGE = (26, 34172)
TITLE_PAGE_RANGE = (26, 61)
CONTENTS_RANGE = (62, 260)
FRONT_MATTER_RANGE = (261, 294)
PARTS = (
    ("IV", 295, 8225),
    ("V", 8225, 24652),
    ("VI", 24652, 34173),
)
PART_HEADING_LINE_RANGES = (
    (295, 295),
    (8225, 8225),
    (24652, 24653),
)
CHAPTERS = (
    ("IV", 300, 8225),
    ("I", 8230, 12213),
    ("II", 12213, 13773),
    ("III", 13773, 24652),
    ("I", 24658, 34173),
)
TOC_ENTRY = re.compile(
    r"^(?:Part\s+|Chapter\s+|Section\s+|"
    r"[IVXLCDM]+\.(?:\s+|—)|"
    r"\d+(?:st|nd|rd|th|d)?\.(?:\s+|—)|"
    r"[A-Z]\.(?:\s+|—)|"
    r"(?:First|Second|Third) [Dd]ivision\.)"
)
HEADING_KINDS = {
    6: "section",
    9: "subsection",
    12: "subsubsection",
    15: "subsubsubsection",
    18: "subsubsubsubsection",
}
HEADING_LEVELS = {kind: index for index, kind in enumerate(HEADING_KINDS.values(), 1)}


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
    authorities = manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Strong Vol. 2 authorities are invalid")
    matches = [item for item in authorities if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Strong Vol. 2 authority {name} cardinality mismatch")
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
        raise ValueError("Strong Vol. 2 source byte accounting is not contiguous")
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
    return f"strong-systematic-theology-vol-2-line-{number:05d}"


def _part_heading_rows(
    rows: list[dict[str, object]], start: int, line_range: tuple[int, int]
) -> list[dict[str, object]]:
    if line_range[0] != start or line_range[1] < line_range[0]:
        raise ValueError("Strong Vol. 2 part heading range is invalid")
    selected = rows[line_range[0] - 1 : line_range[1]]
    if not selected or any(not str(row["text"]).strip() for row in selected):
        raise ValueError("Strong Vol. 2 part heading range contains a blank line")
    return selected


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _toc_entries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for number in range(CONTENTS_RANGE[0], CONTENTS_RANGE[1] + 1):
        text = str(rows[number - 1]["text"])
        if not text.strip():
            continue
        stripped = text.strip()
        indent = len(text) - len(text.lstrip(" "))
        if TOC_ENTRY.match(stripped):
            current = {"toc_line": number, "indent": indent, "text": stripped}
            entries.append(current)
        elif current is not None:
            current["text"] = f"{current['text']} {stripped}"
    return entries


def _body_runs(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    runs: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for number in range(PARTS[0][1], VOLUME_RANGE[1] + 1):
        row = rows[number - 1]
        if str(row["text"]).strip():
            current.append(row)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _source_heading_blocks(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_text: dict[str, list[list[dict[str, object]]]] = {}
    for run in _body_runs(rows):
        by_text.setdefault(_normalize(" ".join(str(row["text"]).strip() for row in run)), []).append(run)

    matches: list[dict[str, object]] = []
    for entry in _toc_entries(rows):
        indent = int(entry["indent"])
        candidates = by_text.get(_normalize(str(entry["text"])), [])
        if indent not in HEADING_KINDS or len(candidates) != 1:
            continue
        run = candidates[0]
        matches.append(
            {
                "start_line": int(run[0]["line"]),
                "end_line": int(run[-1]["line"]),
                "kind": HEADING_KINDS[indent],
                "toc_line": int(entry["toc_line"]),
                "toc_indent": indent,
                "line_numbers": [int(row["line"]) for row in run],
            }
        )
    matches.sort(key=lambda item: int(item["start_line"]))
    if len(_toc_entries(rows)) != 175 or len(matches) != 167:
        raise ValueError("Strong Vol. 2 contents-to-body heading census drifted")
    return matches


def _expected_counts(rows: list[dict[str, object]]) -> dict[str, object]:
    headings = _source_heading_blocks(rows)
    selected = rows[VOLUME_RANGE[0] - 1 : VOLUME_RANGE[1]]
    structural = {
        number
        for heading in headings
        for number in heading["line_numbers"]
    } | {
        number
        for part_start, part_end in PART_HEADING_LINE_RANGES
        for number in range(part_start, part_end + 1)
    } | {start for _, start, _ in CHAPTERS}
    prose_groups: list[list[int]] = []
    current: list[int] = []
    for number in range(PARTS[0][1], VOLUME_RANGE[1] + 1):
        text = str(rows[number - 1]["text"])
        if number in structural:
            if current:
                prose_groups.append(current)
                current = []
        elif text:
            current.append(number)
        elif current:
            prose_groups.append(current)
            current = []
    if current:
        prose_groups.append(current)
    return {
        "part_count": len(PARTS),
        "chapter_count": len(CHAPTERS),
        "part_line_numbers": [start for _, start, _ in PARTS],
        "chapter_line_numbers": [start for _, start, _ in CHAPTERS],
        "title_page_line_range": list(TITLE_PAGE_RANGE),
        "contents_line_range": list(CONTENTS_RANGE),
        "front_matter_line_range": list(FRONT_MATTER_RANGE),
        "volume_line_range": list(VOLUME_RANGE),
        "volume_nonblank_lines": sum(bool(str(row["text"])) for row in selected),
        "volume_blank_lines": sum(not str(row["text"]) for row in selected),
        "contents_entry_count": len(_toc_entries(rows)),
        "contents_body_match_count": 175,
        "mapped_heading_count": len(headings),
        "mapped_heading_line_count": sum(len(item["line_numbers"]) for item in headings),
        "mapped_heading_line_ranges": [
            [int(item["start_line"]), int(item["end_line"])] for item in headings
        ],
        "mapped_heading_kind_counts": {
            kind: sum(item["kind"] == kind for item in headings)
            for kind in HEADING_KINDS.values()
        },
        "body_prose_group_count": len(prose_groups),
        "front_nonblank_lines": sum(bool(str(row["text"])) for row in rows[25:294]),
        "body_nonblank_lines": sum(bool(str(row["text"])) for row in rows[294:34172]),
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
    return tuple([base, *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")])


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


def _closure_digest(root: Path, entry: Path) -> str:
    return _sha(_canonical(_repository_import_closure(root, entry)))


def _check_profile(manifest: SourceManifest, rows: list[dict[str, object]]) -> dict[str, object]:
    profile = _strict(
        manifest.authority_path("reconstruction-profile").read_bytes(),
        "Strong Vol. 2 reconstruction profile",
    )
    source_scope = {
        "bytes": len(manifest.authority_path("retained-source").read_bytes()),
        "physical_lines": len(rows),
        "source_inventory_sha256": _inventory_sha(rows),
    }
    if (
        profile.get("contract") != "ocd-strong-pg44555-reconstruction-profile-v1"
        or profile.get("version") != 1
        or profile.get("work_id") != WORK_ID
        or profile.get("source_scope") != source_scope
        or profile.get("required_counts") != _expected_counts(rows)
        or profile.get("producer_import_closure_sha256")
        != _closure_digest(manifest.repository_root, Path(__file__).resolve(strict=True))
    ):
        raise ValueError("Strong Vol. 2 profile source scope or structure floor drifted")
    return profile


def _add_front_lines(parent: etree._Element, rows: list[dict[str, object]], kind: str) -> None:
    for row in rows:
        if not str(row["text"]):
            continue
        node = etree.SubElement(parent, f"{{{TEI}}}ab")
        node.set(XML_ID, _line_id(int(row["line"])))
        node.set("n", str(row["line"]))
        node.set("type", kind)
        node.set(XML_SPACE, "preserve")
        node.text = str(row["text"])


def _add_head(parent: etree._Element, rows: list[dict[str, object]], kind: str) -> None:
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
    headings: list[dict[str, object]],
) -> None:
    by_start = {int(item["start_line"]): item for item in headings}
    containers: list[tuple[int, etree._Element]] = []
    paragraph: list[dict[str, object]] = []

    def flush() -> None:
        if not paragraph:
            return
        target = containers[-1][1] if containers else parent
        node = etree.SubElement(target, f"{{{TEI}}}p")
        node.set(XML_SPACE, "preserve")
        for index, row in enumerate(paragraph):
            segment = etree.SubElement(node, f"{{{TEI}}}seg")
            segment.set(XML_ID, _line_id(int(row["line"])))
            segment.set("n", str(row["line"]))
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
            kind = str(heading["kind"])
            level = HEADING_LEVELS[kind]
            while containers and containers[-1][0] >= level:
                containers.pop()
            target = containers[-1][1] if containers else parent
            container = etree.SubElement(target, f"{{{TEI}}}div")
            container.set("type", kind)
            container.set("n", str(heading["start_line"]))
            length = len(heading["line_numbers"])
            _add_head(container, rows[index : index + length], kind)
            containers.append((level, container))
            index += length
            continue
        if str(row["text"]):
            paragraph.append(row)
        else:
            flush()
        index += 1
    flush()


def _build_tei(rows: list[dict[str, object]], source_sha: str) -> bytes:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = "Systematic Theology, Vol. 2"
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Augustus H. Strong"
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}p").text = (
        "Nonaccepted reconstruction candidate; publication:not_ready."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI}}}bibl")
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="work-id").text = WORK_ID
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="gutenberg").text = "44555"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="source-sha256").text = source_sha
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="edition").text = EDITION
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="source-path").text = SOURCE_PATH
    encoding = etree.SubElement(header, f"{{{TEI}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI}}}projectDesc")
    etree.SubElement(project, f"{{{TEI}}}p").text = (
        "Every nonblank line in the retained volume range is represented by a source-line "
        "carrier; contents-correlated headings are nested at their observed levels; "
        "blank separators and the Project Gutenberg envelope remain accounted evidence-only."
    )

    text = etree.SubElement(root, f"{{{TEI}}}text")
    front = etree.SubElement(text, f"{{{TEI}}}front")
    title_page = etree.SubElement(front, f"{{{TEI}}}div", type="title-page")
    _add_front_lines(title_page, rows[TITLE_PAGE_RANGE[0] - 1 : TITLE_PAGE_RANGE[1]], "title-page-line")
    contents = etree.SubElement(front, f"{{{TEI}}}div", type="contents")
    _add_front_lines(contents, rows[CONTENTS_RANGE[0] - 1 : CONTENTS_RANGE[1]], "contents-line")
    front_matter = etree.SubElement(front, f"{{{TEI}}}div", type="front-matter")
    _add_front_lines(
        front_matter,
        rows[FRONT_MATTER_RANGE[0] - 1 : FRONT_MATTER_RANGE[1]],
        "front-matter-line",
    )

    body = etree.SubElement(text, f"{{{TEI}}}body")
    headings = _source_heading_blocks(rows)
    heading_index = 0
    for (part_name, part_start, part_end), part_heading_range in zip(
        PARTS, PART_HEADING_LINE_RANGES, strict=True
    ):
        part = etree.SubElement(body, f"{{{TEI}}}div", type="part", n=part_name)
        _add_head(part, _part_heading_rows(rows, part_start, part_heading_range), "part")
        while heading_index < len(CHAPTERS):
            chapter_name, chapter_start, chapter_end = CHAPTERS[heading_index]
            if chapter_start < part_start:
                heading_index += 1
                continue
            if chapter_start >= part_end:
                break
            chapter = etree.SubElement(part, f"{{{TEI}}}div", type="chapter", n=chapter_name)
            _add_head(chapter, [rows[chapter_start - 1]], "chapter")
            _add_prose(chapter, rows[chapter_start : chapter_end - 1], headings)
            heading_index += 1
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _expected_unresolved() -> list[dict[str, str]]:
    values = (
        (
            "edition-identity",
            "The retained witness identifies the revised and enlarged 1907 Judson Press edition through Project Gutenberg #44555; no claim is made that the electronic transcription is a complete diplomatic facsimile of every paper-edition feature.",
        ),
        (
            "textual-form",
            "The retained file is an English Project Gutenberg plain-text witness of Augustus H. Strong's volume; no separate translator or editorial contributor is asserted from the current source envelope.",
        ),
        (
            "rights",
            "The Project Gutenberg wrapper states a United States basis and directs users to check local law; this candidate does not establish worldwide rights clearance or publication authorization.",
        ),
        (
            "source-envelope",
            "The retained member is volume 2 of a three-file Project Gutenberg set. Only pg44555.txt is in this ticket's declared member scope; volumes 1 and 3 are not silently inferred or included.",
        ),
        (
            "human-acceptance",
            "This candidate is nonaccepted and has no human textual, identity, editorial, or rights acceptance.",
        ),
    )
    return [
        {"id": f"{WORK_ID}-{suffix}", "status": "unresolved", "detail": detail}
        for suffix, detail in values
    ]


def _accountability(
    rows: list[dict[str, object]], source_authority: Mapping[str, object]
) -> dict[str, object]:
    selected = set(range(VOLUME_RANGE[0], VOLUME_RANGE[1] + 1))
    line_rows: list[dict[str, object]] = []
    for row in rows:
        number = int(row["line"])
        in_volume = number in selected
        represented = in_volume and bool(str(row["text"]))
        if represented:
            disposition = "represented"
            reason = "retained volume line represented in the TEI hierarchy"
            selector = f"#{_line_id(number)}"
        elif in_volume:
            disposition = "evidence-only"
            reason = "source paragraph separator represented by TEI block structure"
            selector = None
        else:
            disposition = "evidence-only"
            reason = "Project Gutenberg wrapper or license envelope retained as evidence-only"
            selector = None
        line_rows.append(
            {
                **row,
                "disposition": disposition,
                "reason": reason,
                "tei_selector": selector,
            }
        )
    return {
        "contract": "ocd-strong-pg44555-source-accountability-v1",
        "work_id": WORK_ID,
        "source_classification": {
            "source_type": "gutenberg_txt",
            "source_format": "plain text (UTF-8)",
            "ocr_classification": "non-ocr-retained-gutenberg-witness",
        },
        "source_member": {
            key: source_authority[key] for key in ("path", "bytes", "sha256")
        },
        "work_binding": {
            "work_id": WORK_ID,
            "title": "Systematic Theology, Vol. 2",
            "source_member": SOURCE_PATH,
            "source_selector": "retained volume lines 26-34172; PG #44555",
        },
        "volume_line_range": list(VOLUME_RANGE),
        "physical_line_count": len(rows),
        "represented_line_count": sum(item["disposition"] == "represented" for item in line_rows),
        "evidence_only_line_count": sum(item["disposition"] == "evidence-only" for item in line_rows),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_inventory_sha256": _inventory_sha(rows),
        "required_counts": _expected_counts(rows),
        "lines": line_rows,
    }


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("Strong Vol. 2 source identity mismatch")
    source = source_manifest.authority_path("retained-source").read_bytes()
    source_authority = _authority(source_manifest, "retained-source")
    if len(source) != source_authority["bytes"] or _sha(source) != source_authority["sha256"]:
        raise ValueError("Strong Vol. 2 retained source drifted")
    rows = _records(source)
    profile = _check_profile(source_manifest, rows)
    headings = _source_heading_blocks(rows)
    tei = _build_tei(rows, _sha(source))
    accountability = _accountability(rows, source_authority)
    closure = _repository_import_closure(
        source_manifest.repository_root, Path(__file__).resolve(strict=True)
    )
    closure_sha = _sha(_canonical(closure))
    provenance = {
        "contract": "ocd-strong-pg44555-candidate-provenance-v1",
        "status": "nonaccepted",
        "publication": "not_ready",
        "work_id": WORK_ID,
        "source_sha256": _sha(source),
        "source_manifest_sha256": source_manifest.sha256,
        "producer_import_closure": list(closure),
        "producer_import_closure_sha256": closure_sha,
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_scope": profile["source_scope"],
        "hierarchy": {
            "front": ["title-page", "contents", "front-matter"],
            "parts": 3,
            "chapters": 5,
            "contents_entries": 175,
            "sections": {
                kind: sum(item["kind"] == kind for item in headings)
                for kind in HEADING_KINDS.values()
            },
        },
    }
    return {
        "README.source.md": source_manifest.authority_path("attribution-readme").read_bytes(),
        "content.tei.xml": tei,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in _expected_unresolved()),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
