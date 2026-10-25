"""Independent oracle for the exact Project Gutenberg volume-II member candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-calvins-institutes-independent-pg64392-member-oracle"
ORACLE_VERSION = "1"
_MEMBER_NAME = "retained-volume-2"
_MEMBER_PATH = "raw/gutenberg/pg64392.txt"
_LINE_COUNT = 38723
_SOURCE_BYTES = 2134850
_NOTE_COUNT = 1490
_START_LINE = 29
_END_LINE = 38373
_PRINCIPAL_START = 32957
_PRINCIPAL_END = 33423
_SCRIPTURE_START = 33424
_SCRIPTURE_END = 38372
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_BOOK = re.compile(r"^BOOK\s+([IVX]+)\.(?:\s|$)", re.IGNORECASE)
_CHAPTER = re.compile(r"^CHAPTER\s+([IVXLCDM]+)\.(?:\s|$)", re.IGNORECASE)
_NOTE = re.compile(r"^Footnote\s+(\d+):$", re.IGNORECASE)
_ANCHOR = re.compile(r"\[(\d+)\]")
_EMPHASIS = re.compile(r"_(.+?)_", re.DOTALL)
_RIGHTS_STATEMENT = (
    "The retained Project Gutenberg wrapper states a United States public-domain basis and a jurisdiction warning; "
    "Project Gutenberg license and trademark terms remain separate retained evidence. Worldwide status and publication "
    "authorization are unresolved."
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item
        for item in source_manifest.record["authorities"]
        if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Independent Calvin member authority {name} cardinality mismatch")
    return matches[0]


def _roman(value: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = previous = 0
    for character in reversed(value.upper()):
        current = values[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


def _scan_records(content: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    records = content.splitlines(keepends=True)
    for number, record in enumerate(records, 1):
        if not record.endswith(b"\r\n"):
            raise ValueError(f"Independent Calvin member line {number} is not CRLF-terminated")
        payload = record[:-2]
        try:
            text = payload.decode("utf-8-sig" if number == 1 else "utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Independent Calvin member line {number} is not UTF-8") from exc
        rows.append(
            {
                "volume": 2,
                "member": _MEMBER_PATH,
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(record),
                "terminator": "CRLF",
                "text": text,
                "text_sha256": _sha(payload),
                "record_sha256": _sha(record),
            }
        )
        offset += len(record)
    if offset != len(content):
        raise ValueError("Independent Calvin member byte accounting is not contiguous")
    return rows


def _paragraphs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: list[list[dict[str, object]]] = []
    for row in rows:
        blank = not str(row["text"]).strip()
        if not groups or (not str(groups[-1][0]["text"]).strip()) != blank:
            groups.append([])
        groups[-1].append(row)
    result = []
    for ordinal, group in enumerate(groups, 1):
        text = "\n".join(str(item["text"]) for item in group)
        result.append(
            {
                "id": f"calvin-v2-block-{ordinal:04d}",
                "volume": 2,
                "ordinal": ordinal,
                "start_line": int(group[0]["line"]),
                "end_line": int(group[-1]["line"]),
                "blank": not str(group[0]["text"]).strip(),
                "text": text,
                "text_sha256": _sha(text.encode("utf-8")),
                "line_ids": [
                    f"calvin-v2-line-{int(item['line']):05d}" for item in group
                ],
                "lines": group,
            }
        )
    return result


def _position(block: Mapping[str, object], offset: int) -> tuple[int, int]:
    before = str(block["text"])[:offset]
    return (
        int(block["start_line"]) + before.count("\n"),
        len(before.rsplit("\n", 1)[-1]) + 1,
    )


def _offset(block: Mapping[str, object], line: int, column: int) -> int:
    lines = str(block["text"]).split("\n")
    line_index = line - int(block["start_line"])
    if (
        line_index < 0
        or line_index >= len(lines)
        or column < 1
        or column > len(lines[line_index]) + 1
    ):
        raise ValueError("Calvin member source position falls outside its block")
    return sum(len(value) + 1 for value in lines[:line_index]) + column - 1


def _model(blocks: list[dict[str, object]]) -> dict[str, object]:
    physical_books: list[dict[str, object]] = []
    chapters: list[dict[str, object]] = []
    front: list[dict[str, object]] = []
    arguments: list[dict[str, object]] = []
    body: list[dict[str, object]] = []
    indexes: dict[str, list[dict[str, object]]] = {
        "principal-matters": [],
        "scripture": [],
    }
    anchors: list[dict[str, object]] = []
    notes: list[dict[str, object]] = []
    emphasis: list[dict[str, object]] = []
    phase = "gutenberg-header"
    current_book: int | None = None
    current_chapter: int | None = None
    active_note: dict[str, object] | None = None
    has_book = False
    emphasis_number = 0
    for block in blocks:
        first = str(block["text"]).partition("\n")[0].strip()
        upper = first.upper()
        line = int(block["start_line"])
        block.update(book=current_book, chapter=current_chapter, note=None)
        if line == _START_LINE:
            category, disposition, phase = "gutenberg-start-marker", "evidence-only", "front"
        elif line == _END_LINE:
            category, disposition, phase = "gutenberg-end-marker", "evidence-only", "pg-license"
        elif phase == "gutenberg-header":
            category, disposition = "gutenberg-header-evidence", "evidence-only"
        elif phase == "pg-license":
            category, disposition = "gutenberg-license-evidence", "evidence-only"
        elif bool(block["blank"]):
            category = "front-matter-spacing" if phase == "front" else f"{phase}-spacing"
            disposition = "evidence-only" if phase.startswith("gutenberg") or phase == "pg-license" else "represented"
        elif line == _PRINCIPAL_START:
            phase, category = "principal-matters-index", "principal-matters-index-heading"
            disposition = "represented"
            indexes["principal-matters"].append(block)
        elif line == _SCRIPTURE_START:
            phase, category = "scripture-index", "scripture-index-heading"
            disposition = "represented"
            indexes["scripture"].append(block)
        elif phase == "principal-matters-index":
            category, disposition = "principal-matters-index-entry", "represented"
            indexes["principal-matters"].append(block)
        elif phase == "scripture-index":
            category = "transcriber-note" if line == 38364 else "scripture-index-entry"
            disposition = "represented"
            indexes["scripture"].append(block)
        elif match := _BOOK.match(first):
            current_book = _roman(match.group(1))
            current_chapter = None
            phase = "chapter-body" if current_book == 3 else "book-argument"
            category, disposition = "book-heading", "represented"
            has_book = True
            block.update(book=current_book, chapter=None)
            physical_books.append(
                {
                    "volume": 2,
                    "book": current_book,
                    "start_line": block["start_line"],
                    "end_line": block["end_line"],
                    "heading_sha256": block["text_sha256"],
                }
            )
        elif match := _CHAPTER.match(first):
            current_chapter = _roman(match.group(1))
            phase = "chapter-body"
            active_note = None
            category, disposition = "chapter-heading", "represented"
            block.update(book=current_book, chapter=current_chapter)
            chapters.append(
                {
                    "volume": 2,
                    "book": current_book,
                    "chapter": current_chapter,
                    "start_line": block["start_line"],
                    "end_line": block["end_line"],
                    "heading_sha256": block["text_sha256"],
                }
            )
        elif match := _NOTE.fullmatch(first):
            phase = "chapter-notes"
            number = int(match.group(1))
            active_note = {
                "volume": 2,
                "number": number,
                "book": current_book,
                "chapter": current_chapter,
                "label": first,
                "label_block_id": block["id"],
                "block_ids": [block["id"]],
                "start_line": block["start_line"],
                "end_line": block["end_line"],
            }
            notes.append(active_note)
            category, disposition = "note-label", "represented"
            block["note"] = number
        elif phase == "chapter-notes" and active_note is not None:
            category, disposition = "note-body", "represented"
            block.update(note=active_note["number"], book=current_book, chapter=current_chapter)
            active_note["block_ids"].append(block["id"])
            active_note["end_line"] = block["end_line"]
        elif not has_book and phase == "front":
            category, disposition = "front-matter", "represented"
            block.update(book=None, chapter=None)
            front.append(block)
        elif phase == "book-argument":
            category, disposition = "book-argument", "represented"
            block.update(book=current_book, chapter=None)
            arguments.append(block)
        elif phase == "chapter-body" and upper == "END OF THE INSTITUTES.":
            category, disposition = "work-end-marker", "represented"
        elif phase == "chapter-body":
            category, disposition = "chapter-body", "represented"
            block.update(book=current_book, chapter=current_chapter)
            body.append(block)
        else:
            raise ValueError(f"Independent Calvin member parser cannot disposition {block['id']} in {phase}")
        block.update(category=category, disposition=disposition)
        if not bool(block["blank"]):
            for match in _EMPHASIS.finditer(str(block["text"])):
                emphasis_number += 1
                start_line, start_column = _position(block, match.start())
                end_line, end_column = _position(block, match.end() - 1)
                emphasis.append(
                    {
                        "occurrence": emphasis_number,
                        "id": f"calvin-emphasis-{emphasis_number:04d}",
                        "volume": 2,
                        "block_id": block["id"],
                        "start_line": start_line,
                        "start_column": start_column,
                        "end_line": end_line,
                        "end_column": end_column,
                        "value": match.group(1),
                        "value_sha256": _sha(match.group(1).encode("utf-8")),
                    }
                )
        if category == "chapter-body":
            for match in _ANCHOR.finditer(str(block["text"])):
                number = int(match.group(1))
                if number == 1473:
                    continue
                line_number, column = _position(block, match.start())
                anchors.append(
                    {
                        "volume": 2,
                        "occurrence": len(anchors) + 1,
                        "number": number,
                        "label": match.group(0),
                        "book": current_book,
                        "chapter": current_chapter,
                        "block_id": block["id"],
                        "line": line_number,
                        "column": column,
                    }
                )
    note_by_number = {int(item["number"]): item for item in notes}
    anchor_by_number = {int(item["number"]): item for item in anchors}
    if sorted(note_by_number) != list(range(1, _NOTE_COUNT + 1)):
        raise ValueError("Independent Calvin member note sequence drifted")
    if [int(item["number"]) for item in anchors] != [
        number for number in range(1, _NOTE_COUNT + 1) if number != 1473
    ]:
        raise ValueError("Independent Calvin member anchor sequence drifted")
    pairs = [
        {
            "volume": 2,
            "number": number,
            "anchor": anchor_by_number.get(number),
            "note": note_by_number[number],
        }
        for number in range(1, _NOTE_COUNT + 1)
    ]
    return {
        "physical_books": physical_books,
        "chapters": chapters,
        "front_blocks": front,
        "argument_blocks": arguments,
        "body_blocks": body,
        "indexes": indexes,
        "anchors": anchors,
        "notes": notes,
        "pairs": pairs,
        "emphasis": emphasis,
    }


def _inventory(rows: list[Mapping[str, object]], fields: tuple[str, ...]) -> list[dict[str, object]]:
    return [{key: row[key] for key in fields} for row in rows]


def _inventory_digests(model: Mapping[str, object]) -> dict[str, str]:
    structural = [
        {"kind": "volume", "volume": 2, "line": 1},
        *(
            {
                "kind": "book",
                **{
                    key: item[key]
                    for key in ("volume", "book", "start_line", "end_line", "heading_sha256")
                },
            }
            for item in model["physical_books"]
        ),
        *(
            {
                "kind": "chapter",
                **{
                    key: item[key]
                    for key in ("volume", "book", "chapter", "start_line", "end_line", "heading_sha256")
                },
            }
            for item in model["chapters"]
        ),
    ]
    index_fields = ("id", "start_line", "end_line", "text_sha256")
    anchor_fields = ("volume", "occurrence", "number", "label", "book", "chapter", "block_id", "line", "column")
    note_fields = ("volume", "number", "label", "book", "chapter", "label_block_id", "block_ids", "start_line", "end_line")
    emphasis_fields = ("occurrence", "id", "volume", "block_id", "start_line", "start_column", "end_line", "end_column", "value", "value_sha256")
    indexes = model["indexes"]
    return {
        "structural_events_sha256": _sha(_canonical(structural)),
        "front_blocks_sha256": _sha(_canonical(_inventory(model["front_blocks"], index_fields))),
        "argument_blocks_sha256": _sha(_canonical(_inventory(model["argument_blocks"], index_fields))),
        "chapter_body_blocks_sha256": _sha(_canonical(_inventory(model["body_blocks"], index_fields))),
        "principal_index_blocks_sha256": _sha(_canonical(_inventory(indexes["principal-matters"], index_fields))),
        "scripture_index_blocks_sha256": _sha(_canonical(_inventory(indexes["scripture"], index_fields))),
        "anchors_sha256": _sha(_canonical(_inventory(model["anchors"], anchor_fields))),
        "notes_sha256": _sha(_canonical(_inventory(model["notes"], note_fields))),
        "attachments_sha256": _sha(_canonical(model["pairs"])),
        "emphasis_sha256": _sha(_canonical(_inventory(model["emphasis"], emphasis_fields))),
    }


def _plain_and_inline(node: etree._Element) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    output: list[str] = []
    refs: list[dict[str, object]] = []
    emphasis: list[dict[str, object]] = []
    seen_line = False

    def walk(current: etree._Element) -> None:
        nonlocal seen_line
        local = etree.QName(current).localname
        if local == "lb":
            if seen_line:
                output.append("\n")
            seen_line = True
            return
        start = len("".join(output))
        if local == "ref":
            refs.append(
                {
                    "offset": start,
                    "number": int(current.get("n", "0")),
                    "label": "".join(current.itertext()),
                    "target": current.get("target"),
                }
            )
        if current.text:
            output.append(current.text)
        for child in current:
            walk(child)
            if child.tail:
                output.append(child.tail)
        if local == "hi":
            emphasis.append(
                {
                    "offset": start,
                    "id": current.get(_XML_ID),
                    "value": "".join(output)[start:],
                    "rend": current.get("rend"),
                    "ana": current.get("ana"),
                }
            )

    walk(node)
    return "".join(output), refs, emphasis


def _local_module_path(root: Path, module: str) -> Path | None:
    if not module or any(part in {"", ".", ".."} for part in module.split(".")):
        return None
    stem = root.joinpath(*module.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Calvin member oracle import closure escaped repository") from exc
        if resolved.is_file():
            return resolved
    return None


def _import_names(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        package = list(path.relative_to(root).parts[:-1])
        prefix = package[: len(package) - node.level + 1]
        base = ".".join([*prefix, *((node.module or "").split(".") if node.module else [])])
    return tuple([base, *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")])


def _closure(root: Path, entry: Path, forbidden: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        relative = path.relative_to(root)
        for depth in range(1, len(relative.parts)):
            initializer = root.joinpath(*relative.parts[:depth], "__init__.py")
            if initializer.is_file() and initializer.resolve() not in seen:
                pending.append(initializer.resolve())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = (
                tuple(alias.name for alias in node.names)
                if isinstance(node, ast.Import)
                else _import_names(path, root, node)
                if isinstance(node, ast.ImportFrom)
                else ()
            )
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"Calvin member oracle forbidden import: {name}")
                dependency = _local_module_path(root, name)
                if dependency is not None and dependency not in seen:
                    pending.append(dependency)
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix())
    )


def _runtime_paths(root: Path) -> None:
    for module_name in ("ocd_kernel.reconstruction.contract", "ocd_kernel.tei.validate"):
        path = Path(sys.modules[module_name].__file__).resolve(strict=True)
        try:
            relative = path.relative_to(root.resolve(strict=True))
        except ValueError as exc:
            raise ValueError(f"Calvin member oracle loaded {module_name} outside repository") from exc
        if "site-packages" in relative.as_posix() or "__editable__" in relative.as_posix():
            raise ValueError(f"Calvin member oracle loaded shadowed {module_name}")


def _expected_unresolved() -> bytes:
    records = (
        {"id": "calvin-author-name", "status": "unresolved", "detail": "Project Gutenberg metadata says Jean Calvin; the retained title page says John Calvin."},
        {"id": "calvin-edition-identity", "status": "unresolved", "detail": "The title page states Sixth American Edition, revised and corrected, Philadelphia, Presbyterian Board of Publication, 1813; this package does not normalize the claim."},
        {"id": "calvin-scripture-index-identity", "status": "unresolved", "detail": "The appended Scripture Index identifies S. T. Livermore, the Presbyterian Board of Publication, the University of Rochester, and MDCCCLII (1852)."},
        {"id": "calvin-project-gutenberg-record", "status": "unresolved", "detail": "The retained Gutenberg wrapper carries its release, update, credit, and Internet Archive image-production records; these remain evidence, not a synthesized edition claim."},
        {"id": "calvin-rights-jurisdiction-and-terms", "status": "unresolved", "detail": "The source asserts a United States public-domain basis, warns users to check local law, and imposes Project Gutenberg license and trademark terms; validation is not rights clearance."},
        {"id": "calvin-human-acceptance", "status": "unresolved", "detail": "This deterministic member candidate is explicitly nonaccepted and has not received human textual, identity, or rights acceptance."},
    )
    return b"".join(_canonical(record) for record in records)


def _expected_readme() -> bytes:
    return (
        "# Calvin Institutes volume II retained-member candidate\n\n"
        "This package-only README accompanies a nonaccepted reconstruction of the exact retained Project Gutenberg volume II text, eBook #64392.\n\n"
        "The represented boundary begins with Book III chapter XIV and continues through Book IV, the chapter notes, the principal-matters index, the Scripture Index, and the retained wrapper and license evidence. This is an explicitly partial member candidate, not a whole-work acceptance claim.\n\n"
        "Rights are deliberately split: the retained file states a United States public-domain basis, warns users outside the United States to check their jurisdiction, and retains Project Gutenberg redistribution and trademark conditions. Review the [Project Gutenberg License](https://www.gutenberg.org/license/) before redistribution. This package does not claim unconditional availability, worldwide public-domain status, human acceptance, or publication authorization.\n\n"
        "John Allen, Jean/John Calvin identity evidence, the Sixth American Edition title-page claim, the volume-II release/update records, Distributed Proofreaders credits, Internet Archive image evidence, S. T. Livermore, the Presbyterian Board of Publication, and the University of Rochester evidence remain visible.\n"
    ).encode("utf-8")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    expected_manifest = source_manifest.path.relative_to(root).as_posix()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != source_manifest.record.get("source_id")
        or candidate.manifest.get("source_manifest") != {"path": expected_manifest, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]
    ):
        raise ValueError("Calvin pg64392 member candidate authority binding mutation")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Calvin pg64392 member profile")
    policy = _strict(policy_bytes, "Calvin pg64392 member policy")
    if profile.get("profile_id") != "calvins-institutes-pg64392-member-source-v1" or policy.get("rights_statement") != _RIGHTS_STATEMENT:
        raise ValueError("Calvin pg64392 member profile or policy identity mutation")
    authority = _authority(source_manifest, _MEMBER_NAME)
    primary = [
        item
        for item in source_manifest.record["authorities"]
        if item.get("role") == "primary-source"
    ]
    if primary != [authority] or authority.get("path") != _MEMBER_PATH:
        raise ValueError("Calvin pg64392 member primary-source boundary mutation")
    source = source_manifest.authority_path(_MEMBER_NAME).read_bytes()
    members = [{"path": authority["path"], "bytes": len(source), "sha256": _sha(source)}]
    scope = profile.get("source_scope")
    if not isinstance(scope, dict) or scope.get("members") != members or scope.get("bytes") != _SOURCE_BYTES or scope.get("physical_lines") != _LINE_COUNT:
        raise ValueError("Calvin pg64392 member source scope mutation")
    rows = _scan_records(source)
    if len(rows) != _LINE_COUNT:
        raise ValueError("Calvin pg64392 member line count mutation")
    exact_inventory = [
        {key: row[key] for key in ("volume", "member", "line", "byte_start", "byte_end", "terminator", "record_sha256")}
        for row in rows
    ]
    exact_lines = _sha(_canonical(exact_inventory))
    if exact_lines != scope.get("derived_exact_line_inventory_sha256"):
        raise ValueError("Calvin pg64392 member ordered line inventory mutation")
    blocks = _paragraphs(rows)
    model = _model(blocks)
    counts = {
        "logical_books": len({int(item["book"]) for item in model["physical_books"]}),
        "physical_book_headings": len(model["physical_books"]),
        "chapters": len(model["chapters"]),
        "volume_2_chapters": len(model["chapters"]),
        "front_blocks": len(model["front_blocks"]),
        "argument_blocks": len(model["argument_blocks"]),
        "chapter_body_blocks": len(model["body_blocks"]),
        "principal_index_lines": _PRINCIPAL_END - _PRINCIPAL_START + 1,
        "principal_index_blocks": len(model["indexes"]["principal-matters"]),
        "scripture_index_lines": _SCRIPTURE_END - _SCRIPTURE_START + 1,
        "scripture_index_blocks": len(model["indexes"]["scripture"]),
        "volume_2_anchors": len(model["anchors"]),
        "volume_2_notes": len(model["notes"]),
        "emphasis_carriers": len(model["emphasis"]),
    }
    digests = _inventory_digests(model)
    if counts != profile.get("required_counts") or digests != profile.get("derived_inventory_digests"):
        raise ValueError("Calvin pg64392 member source-derived inventory mutation")

    accountability = _strict(candidate.member_bytes("source-accountability.json"), "Calvin member accountability")
    schema = _strict(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "Calvin member accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"Calvin member accountability schema failure: {errors[0].message}")
    line_to_block = {
        (2, line): block
        for block in blocks
        for line in range(int(block["start_line"]), int(block["end_line"]) + 1)
    }
    expected_lines = []
    for row in rows:
        block = line_to_block[(2, int(row["line"]))]
        expected_lines.append(
            {
                **row,
                "feature_id": f"calvin-v2-line-{int(row['line']):05d}",
                "block_id": block["id"],
                "category": block["category"],
                "disposition": block["disposition"],
                "tei_selector": f"#calvin-v2-line-{int(row['line']):05d}",
            }
        )
    represented = sum(row["disposition"] == "represented" for row in expected_lines)
    expected_events = [
        {"kind": "volume", "volume": 2, "line": 1},
        *model["physical_books"],
        *model["chapters"],
    ]
    if (
        accountability.get("source_members") != members
        or accountability.get("source_bytes") != _SOURCE_BYTES
        or accountability.get("physical_line_count") != _LINE_COUNT
        or accountability.get("represented_line_count") != represented
        or accountability.get("evidence_only_line_count") != _LINE_COUNT - represented
        or accountability.get("omitted_line_count") != 0
        or accountability.get("duplicate_line_count") != 0
        or accountability.get("derived_member_set_sha256") != members[0]["sha256"]
        or accountability.get("derived_exact_line_inventory_sha256") != exact_lines
        or accountability.get("inventory_digests") != digests
        or accountability.get("lines") != expected_lines
        or accountability.get("structural_events") != expected_events
        or accountability.get("note_attachments") != model["pairs"]
        or accountability.get("emphasis_carriers") != model["emphasis"]
    ):
        raise ValueError("Calvin pg64392 member accountability mutation")

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    if etree.QName(tei).text != f"{{{_TEI}}}TEI" or not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError(f"Calvin pg64392 member TEI P5 failure: {compiled_schema().error_log.last_error}")
    ns = {"tei": _TEI, "xml": "http://www.w3.org/XML/1998/namespace"}
    if tei.get(_XML_ID) != "calvins-institutes-gutenberg-pg64392-member-candidate":
        raise ValueError("Calvin pg64392 member TEI root identity mutation")
    header = tei.xpath("./tei:teiHeader", namespaces=ns)
    if len(header) != 1 or tei.xpath("string(./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256'])", namespaces=ns) != members[0]["sha256"]:
        raise ValueError("Calvin pg64392 member TEI source digest mutation")
    if b"pg45001" in candidate.member_bytes("content.tei.xml") or b"pg45001" in candidate.member_bytes("README.source.md"):
        raise ValueError("Calvin pg64392 member candidate contains excluded source identity")
    volume_texts = tei.xpath("./tei:text/tei:group/tei:text", namespaces=ns)
    if [(node.get(_XML_ID), node.get("n")) for node in volume_texts] != [("calvin-volume-2", "2")]:
        raise ValueError("Calvin pg64392 member physical-volume wrapper mutation")
    observed_lines = [str(value) for value in tei.xpath("//tei:text//tei:lb/@xml:id", namespaces=ns)]
    expected_line_ids = [str(value) for block in blocks for value in block["line_ids"]]
    if observed_lines != expected_line_ids:
        raise ValueError("Calvin pg64392 member TEI line omission, duplication, or reorder")
    block_nodes = {
        str(node.get(_XML_ID)): node
        for node in tei.xpath("//*[@xml:id]", namespaces=ns)
        if "-block-" in str(node.get(_XML_ID))
    }
    observed_refs: list[dict[str, object]] = []
    observed_emphasis: list[dict[str, object]] = []
    for block in blocks:
        node = block_nodes.get(str(block["id"]))
        if node is None:
            raise ValueError(f"Calvin pg64392 member TEI block missing: {block['id']}")
        plain, refs, emphasis = _plain_and_inline(node)
        if plain != block["text"] or node.get("type") != block["category"]:
            raise ValueError(f"Calvin pg64392 member TEI block text or kind mutation: {block['id']}")
        if [str(value) for value in node.xpath(".//tei:lb/@xml:id", namespaces=ns)] != list(block["line_ids"]):
            raise ValueError(f"Calvin pg64392 member TEI block line attachment mutation: {block['id']}")
        for ref in refs:
            observed_refs.append(
                {
                    "number": ref["number"],
                    "label": ref["label"],
                    "target": ref["target"],
                    "block_id": block["id"],
                }
            )
        observed_emphasis.extend(emphasis)
    expected_refs = [
        {
            "number": int(item["number"]),
            "label": item["label"],
            "target": f"#calvin-v2-note-{int(item['number']):04d}",
            "block_id": item["block_id"],
        }
        for item in model["anchors"]
    ]
    if observed_refs != expected_refs:
        raise ValueError("Calvin pg64392 member TEI note-reference mutation")
    blocks_by_id = {str(block["id"]): block for block in blocks}
    expected_emphasis = [
        {
            "offset": _offset(
                blocks_by_id[str(item["block_id"])],
                int(item["start_line"]),
                int(item["start_column"]),
            )
            + 1,
            "id": item["id"],
            "value": item["value"],
            "rend": "underscore",
            "ana": "#source-emphasis",
        }
        for item in model["emphasis"]
    ]
    if observed_emphasis != expected_emphasis:
        mismatch = next(
            (
                index,
                observed_emphasis[index] if index < len(observed_emphasis) else None,
                expected_emphasis[index] if index < len(expected_emphasis) else None,
            )
            for index in range(max(len(observed_emphasis), len(expected_emphasis)))
            if index >= len(observed_emphasis)
            or index >= len(expected_emphasis)
            or observed_emphasis[index] != expected_emphasis[index]
        )
        raise ValueError(
            "Calvin pg64392 member TEI emphasis mutation at "
            f"occurrence {mismatch[0] + 1}: observed={mismatch[1]!r}; expected={mismatch[2]!r}"
        )
    expected_note_ids = [f"calvin-v2-note-{number:04d}" for number in range(1, _NOTE_COUNT + 1)]
    note_nodes = tei.xpath("//tei:note[starts-with(@xml:id, 'calvin-v2-note-')]", namespaces=ns)
    if [node.get(_XML_ID) for node in note_nodes] != expected_note_ids:
        raise ValueError("Calvin pg64392 member TEI note order mutation")
    for node, note in zip(note_nodes, model["notes"], strict=True):
        parent = node.getparent()
        chapter = parent.getparent() if parent is not None else None
        book = chapter.getparent() if chapter is not None else None
        if node.get("n") != str(note["number"]) or node.get("place") != "end" or parent is None or parent.get("subtype") != "chapter-endnotes" or chapter is None or chapter.get(_XML_ID) != f"calvin-v2-book-{note['book']}-chapter-{note['chapter']}" or book is None or book.get(_XML_ID) != f"calvin-book-{note['book']}-volume-2":
            raise ValueError(f"Calvin pg64392 member TEI note ancestry mutation: {note['number']}")
    if len(tei.xpath("//tei:note[@xml:id='calvin-v2-note-1473']", namespaces=ns)) != 1 or tei.xpath("//tei:ref[@target='#calvin-v2-note-1473']", namespaces=ns):
        raise ValueError("Calvin pg64392 member sole unreferenced note mutation")
    books = tei.xpath("//tei:div[@type='book']", namespaces=ns)
    if [
        (node.get("n"), node.get("part"), node.get(_XML_ID), node.getparent().getparent().get(_XML_ID))
        for node in books
    ] != [("3", "F", "calvin-book-3-volume-2", "calvin-volume-2"), ("4", "N", "calvin-book-4-volume-2", "calvin-volume-2")]:
        raise ValueError("Calvin pg64392 member book wrapper mutation")
    chapters = tei.xpath("//tei:div[@type='chapter']", namespaces=ns)
    expected_chapters = [
        (
            f"calvin-v2-book-{item['book']}-chapter-{item['chapter']}",
            str(item["chapter"]),
            f"calvin-book-{item['book']}-volume-2",
        )
        for item in model["chapters"]
    ]
    if [
        (node.get(_XML_ID), node.get("n"), node.getparent().get(_XML_ID))
        for node in chapters
    ] != expected_chapters:
        raise ValueError("Calvin pg64392 member chapter wrapper mutation")
    if len(tei.xpath("//tei:div[@type='index' and @subtype='principal-matters']/*[@type='principal-matters-index-heading' or @type='principal-matters-index-entry']", namespaces=ns)) != 203 or len(tei.xpath("//tei:div[@type='index' and @subtype='scripture']/*[@type='scripture-index-heading' or @type='scripture-index-entry' or @type='transcriber-note']", namespaces=ns)) != 838:
        raise ValueError("Calvin pg64392 member index block mutation")
    if not tei.xpath("//tei:div[@type='source-evidence' and @subtype='project-gutenberg-header']", namespaces=ns) or not tei.xpath("//tei:div[@type='source-evidence' and @subtype='project-gutenberg-license']", namespaces=ns):
        raise ValueError("Calvin pg64392 member wrapper/license evidence missing")

    provenance = _strict(candidate.member_bytes("provenance.json"), "Calvin member provenance")
    expected_authorities = {
        str(item["name"]): {key: item[key] for key in ("path", "role", "bytes", "sha256")}
        for item in source_manifest.record["authorities"]
    }
    converter_path = root / str(source_manifest.record["converter"]["implementation_path"])
    producer_closure = _closure(root, converter_path, tuple(str(item) for item in policy.get("producer_forbidden_import_prefixes", [])))
    if provenance.get("contract") != "ocd-calvins-institutes-pg64392-member-candidate-provenance-v1" or provenance.get("status") != "nonaccepted" or provenance.get("authorities") != expected_authorities or provenance.get("loaded_module_paths") != {"converter": "build/tei/calvins_institutes_pg64392_member_reconstruction.py", "shared_renderer": "build/tei/calvins_institutes_reconstruction.py", "contract": "ocd_kernel/reconstruction/contract.py"} or provenance.get("producer_import_closure") != list(producer_closure) or provenance.get("producer_import_closure_sha256") != _sha(_canonical(producer_closure)) or provenance.get("source_member_set_sha256") != members[0]["sha256"] or provenance.get("identity_conflicts") != profile.get("identity_conflicts") or provenance.get("rights") != profile.get("rights") or provenance.get("source_bytes_embedded_in_candidate") is not False:
        raise ValueError("Calvin pg64392 member provenance mutation")
    _runtime_paths(root)
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    oracle_closure = _closure(root, Path(__file__), forbidden)
    if _sha(Path(__file__).read_bytes()) != source_manifest.record["validator"]["implementation_sha256"] or _sha(_canonical(oracle_closure)) != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("Calvin pg64392 member oracle implementation or closure drifted")
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved() or candidate.member_bytes("README.source.md") != _expected_readme():
        raise ValueError("Calvin pg64392 member unresolved or source README mutation")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _sha(_canonical(oracle_closure)),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": members[0]["sha256"],
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
