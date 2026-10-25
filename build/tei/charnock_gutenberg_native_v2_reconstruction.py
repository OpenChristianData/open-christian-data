"""Direct PG#53527 Charnock witness to distinct nonaccepted volume candidates."""

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


CONVERTER_ID = "ocd-charnock-pg53527-native-volume-to-tei"
CONVERTER_VERSION = "2"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
VOLUMES = {
    "charnock-existence-attributes-vol-1": (1, 33, 30307),
    "charnock-existence-attributes-vol-2": (2, 30308, 56434),
}
APPARATUS = (56435, 62447)
PAGE_RE = re.compile(r"\{([ab]\d+)\}")
NOTE_REF_RE = re.compile(r"\[(\d{1,4})\]")
DISCOURSE_RE = re.compile(r"DISCOURSE\s+([IVXLCDM]+)\.")
NOTE_LINE_RE = re.compile(r"^\s*(\d+)\s+–\s?(.*)$")


def _line_id(prefix: str, number: int) -> str:
    return f"{prefix}-line-{number:05d}"


def _note_id(prefix: str, number: int) -> str:
    return f"{prefix}-note-{number}"


def _strip_page_markers(text: str) -> str:
    return PAGE_RE.sub("", text)


def _heading_text(text: str) -> str:
    return _strip_page_markers(text).strip()


def _is_heading(text: str) -> bool:
    value = _heading_text(text)
    return bool(value) and len(value) < 120 and value.isupper()


def _is_discourse_start(text: str) -> bool:
    return bool(PAGE_RE.search(text) and DISCOURSE_RE.search(_heading_text(text)))


def _append_text(parent: etree._Element, value: str) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _append_inline(
    parent: etree._Element,
    text: str,
    state: dict[str, etree._Element | None],
    *,
    line_id: str,
    volume: int,
    allow_note_refs: bool,
    exclude_note_ref: bool = False,
) -> None:
    """Project one physical source line into readable TEI mixed content."""

    index = 0
    active = state.get("italic")
    while index < len(text):
        page = PAGE_RE.match(text, index)
        if page is not None:
            target = active if active is not None else parent
            marker = etree.SubElement(
                target,
                f"{{{TEI}}}pb",
                n=page.group(1),
                corresp=f"#{line_id}",
            )
            del marker
            state["page_marker_count"] = (state.get("page_marker_count") or 0) + 1
            index = page.end()
            continue
        if allow_note_refs and not exclude_note_ref:
            note_ref = NOTE_REF_RE.match(text, index)
            if note_ref is not None:
                number = int(note_ref.group(1))
                target = active if active is not None else parent
                ref = etree.SubElement(
                    target,
                    f"{{{TEI}}}ref",
                    type="note",
                    target=f"#{_note_id(f'charnock-shared-v{volume}', number)}",
                )
                ref.text = note_ref.group(0)
                index = note_ref.end()
                continue
        if text[index] == "_":
            if active is None:
                target = active if active is not None else parent
                active = etree.SubElement(target, f"{{{TEI}}}hi", rend="italic")
                state["italic"] = active
            else:
                active = None
                state["italic"] = None
            index += 1
            continue
        next_positions = [len(text)]
        page_start = text.find("{", index + 1)
        if page_start >= 0:
            next_positions.append(page_start)
        if allow_note_refs and not exclude_note_ref:
            ref_start = text.find("[", index + 1)
            if ref_start >= 0:
                next_positions.append(ref_start)
        underscore = text.find("_", index + 1)
        if underscore >= 0:
            next_positions.append(underscore)
        end = min(next_positions)
        target = active if active is not None else parent
        _append_text(target, text[index:end])
        index = end


def _append_line(
    target: etree._Element,
    row: Mapping[str, object],
    prefix: str,
    *,
    volume: int,
    first: bool,
    allow_note_refs: bool,
    exclude_note_ref: bool = False,
    state: dict[str, etree._Element | None] | None = None,
) -> None:
    state = state if state is not None else {}
    number = int(row["line"])
    value = str(row["text"])
    line_id = _line_id(prefix, number)
    # Line 100 is Gutenberg's wrapper explanation of the two-volume witness;
    # its bracketed ``[2]`` is literal wrapper prose, not a Charnock note ref.
    exclude_note_ref = exclude_note_ref or number == 100
    has_page = len(PAGE_RE.findall(value))
    if has_page > 1:
        raise ValueError(f"Charnock source line has multiple page markers: {number}")
    if not first:
        active_parent = state.get("italic")
        line_parent = active_parent if active_parent is not None else target
        etree.SubElement(
            line_parent,
            f"{{{TEI}}}lb",
            **{"break": "no"},
        )
        line_parent[-1].tail = " "
        if has_page == 0:
            line_parent[-1].set("corresp", f"#{line_id}")
    elif has_page == 0:
        target.set("corresp", f"#{line_id}")
    state["page_marker_count"] = 0
    _append_inline(
        target,
        value,
        state,
        line_id=line_id,
        volume=volume,
        allow_note_refs=allow_note_refs,
        exclude_note_ref=exclude_note_ref,
    )
    if state.get("page_marker_count") != has_page:
        raise ValueError(f"Charnock page-marker carrier drift at line {number}")


def _append_run(
    parent: etree._Element,
    rows: list[dict[str, object]],
    prefix: str,
    *,
    volume: int,
    allow_note_refs: bool,
    exclude_note_ref: bool = False,
    element_name: str = "p",
    element_attributes: Mapping[str, str] | None = None,
) -> etree._Element:
    if not rows:
        raise ValueError("Charnock cannot build an empty readable run")
    target = etree.SubElement(
        parent,
        f"{{{TEI}}}{element_name}",
        **dict(element_attributes or {}),
    )
    state: dict[str, etree._Element | None] = {"italic": None}
    for index, row in enumerate(rows):
        _append_line(
            target,
            row,
            prefix,
            volume=volume,
            first=index == 0,
            allow_note_refs=allow_note_refs,
            exclude_note_ref=exclude_note_ref,
            state=state,
        )
    target.tail = " "
    return target


def _append_blank(parent: etree._Element, row: Mapping[str, object], prefix: str) -> None:
    etree.SubElement(
        parent,
        f"{{{TEI}}}lb",
        type="source-blank-line",
        n=str(row["line"]),
        corresp=f"#{_line_id(prefix, int(row['line']))}",
    )


def _append_simple_section(
    parent: etree._Element,
    rows: list[dict[str, object]],
    prefix: str,
    *,
    volume: int,
    allow_note_refs: bool,
    exclude_note_ref: bool = False,
    section_type: str,
) -> etree._Element:
    section = etree.SubElement(parent, f"{{{TEI}}}div", type=section_type)
    pending: list[dict[str, object]] = []
    for row in rows:
        value = str(row["text"])
        if not value:
            if pending:
                _append_run(
                    section,
                    pending,
                    prefix,
                    volume=volume,
                    allow_note_refs=allow_note_refs,
                    exclude_note_ref=exclude_note_ref,
                )
                pending = []
            _append_blank(section, row, prefix)
            continue
        if _is_heading(value):
            if pending:
                _append_run(
                    section,
                    pending,
                    prefix,
                    volume=volume,
                    allow_note_refs=allow_note_refs,
                    exclude_note_ref=exclude_note_ref,
                )
                pending = []
            _append_run(
                section,
                [row],
                prefix,
                volume=volume,
                allow_note_refs=allow_note_refs,
                exclude_note_ref=exclude_note_ref,
                element_name="ab",
                element_attributes={
                    "type": "source-heading",
                    "subtype": "h2",
                },
            )
            continue
        pending.append(row)
    if pending:
        _append_run(
            section,
            pending,
            prefix,
            volume=volume,
            allow_note_refs=allow_note_refs,
            exclude_note_ref=exclude_note_ref,
        )
    return section


def _append_readable_volume(
    parent: etree._Element,
    rows: list[dict[str, object]],
    prefix: str,
    *,
    volume: int,
) -> etree._Element:
    readable = etree.SubElement(parent, f"{{{TEI}}}div", type="readable-transcription")
    front_boundary = 0
    for index, row in enumerate(rows):
        value = _heading_text(str(row["text"])).upper()
        if "LIFE AND CHARACTER" in value or "OF TEXTS." in value:
            front_boundary = index
    first_discourse = next(
        (
            index
            for index, row in enumerate(rows)
            if index > front_boundary and _is_discourse_start(str(row["text"]))
        ),
        len(rows),
    )
    front = _append_simple_section(
        readable,
        rows[:first_discourse],
        prefix,
        volume=volume,
        allow_note_refs=True,
        exclude_note_ref=False,
        section_type="front-matter",
    )
    del front
    current: etree._Element | None = None
    pending: list[dict[str, object]] = []

    def flush() -> None:
        nonlocal pending
        if pending:
            _append_run(
                current if current is not None else readable,
                pending,
                prefix,
                volume=volume,
                allow_note_refs=True,
            )
            pending = []

    for row in rows[first_discourse:]:
        value = str(row["text"])
        if _is_discourse_start(value):
            flush()
            match = DISCOURSE_RE.search(_heading_text(value))
            if match is None:
                raise ValueError("Charnock discourse heading did not carry a Roman numeral")
            current = etree.SubElement(
                readable,
                f"{{{TEI}}}div",
                type="discourse",
                n=match.group(1),
                **{XML_ID: f"{prefix}-discourse-{match.group(1)}"},
            )
            _append_run(
                current,
                [row],
                prefix,
                volume=volume,
                allow_note_refs=True,
                element_name="ab",
                element_attributes={
                    "type": "source-heading",
                    "subtype": "h1",
                },
            )
        elif not value:
            flush()
            _append_blank(current if current is not None else readable, row, prefix)
        elif _is_heading(value):
            flush()
            _append_run(
                current if current is not None else readable,
                [row],
                prefix,
                volume=volume,
                allow_note_refs=True,
                element_name="ab",
                element_attributes={
                    "type": "source-heading",
                    "subtype": "h2",
                },
            )
        else:
            pending.append(row)
    flush()
    return readable


def _append_readable_apparatus(
    parent: etree._Element,
    rows: list[dict[str, object]],
    prefix: str,
    *,
    volume: int,
) -> etree._Element:
    readable = etree.SubElement(parent, f"{{{TEI}}}div", type="readable-transcription")
    footnote_heading = next(
        (index for index, row in enumerate(rows) if int(row["line"]) == 59664),
        len(rows),
    )
    transcriber_heading = next(
        (index for index, row in enumerate(rows) if int(row["line"]) >= 61842),
        len(rows),
    )
    _append_simple_section(
        readable,
        rows[:footnote_heading],
        prefix,
        volume=volume,
        allow_note_refs=False,
        exclude_note_ref=True,
        section_type="index",
    )
    footnotes = etree.SubElement(readable, f"{{{TEI}}}div", type="footnotes")
    foot_rows = rows[footnote_heading:transcriber_heading]
    pending: list[dict[str, object]] = []
    current_note: etree._Element | None = None

    def flush_note() -> None:
        nonlocal pending
        if pending:
            if current_note is None:
                _append_run(
                    footnotes,
                    pending,
                    prefix,
                    volume=volume,
                    allow_note_refs=False,
                    exclude_note_ref=True,
                    element_name="ab",
                    element_attributes={
                        "type": "source-heading",
                        "subtype": "h2",
                    },
                )
            else:
                state: dict[str, etree._Element | None] = {"italic": None}
                for index, row in enumerate(pending):
                    _append_line(
                        current_note,
                        row,
                        prefix,
                        volume=volume,
                        first=index == 0,
                        allow_note_refs=False,
                        exclude_note_ref=True,
                        state=state,
                    )
            pending = []

    for row in foot_rows:
        value = str(row["text"])
        if not value:
            flush_note()
            _append_blank(footnotes, row, prefix)
            current_note = None
            continue
        match = NOTE_LINE_RE.match(value)
        if match:
            flush_note()
            current_note = etree.SubElement(
                footnotes,
                f"{{{TEI}}}note",
                place="end",
                n=match.group(1),
                **{XML_ID: _note_id(prefix, int(match.group(1)))},
            )
            pending.append(row)
        else:
            pending.append(row)
    flush_note()
    _append_simple_section(
        readable,
        rows[transcriber_heading:],
        prefix,
        volume=volume,
        allow_note_refs=False,
        exclude_note_ref=True,
        section_type="transcriber-notes",
    )
    return readable


def _add_line_ledger(
    parent: etree._Element,
    rows: list[dict[str, object]],
    prefix: str,
    *,
    volume: int,
) -> None:
    ledger = etree.SubElement(
        parent,
        f"{{{TEI}}}div",
        type="complete-xml-node-transcription",
        subtype="source-line-accountability",
    )
    for ordinal, row in enumerate(rows, 1):
        number = int(row["line"])
        feature_id = _line_id(prefix, number)
        record: dict[str, object] = {
            "feature_id": feature_id,
            "ordinal": ordinal,
            "kind": "source-line",
            "line": number,
            "text": str(row["text"]),
            "record_sha256": str(row["record_sha256"]),
            "volume": volume,
        }
        record["payload_sha256"] = _sha(_canonical(record))
        carrier = etree.SubElement(
            ledger,
            f"{{{TEI}}}note",
            type="source-line-accountability",
            n=str(ordinal),
            **{XML_ID: feature_id},
        )
        carrier.text = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Charnock authority {name} cardinality mismatch")
    return matches[0]


def _records(content: bytes) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    for number, record in enumerate(content.splitlines(keepends=True), 1):
        if record.endswith(b"\r\n"):
            payload, terminator = record[:-2], "CRLF"
        elif record.endswith(b"\n"):
            payload, terminator = record[:-1], "LF"
        else:
            payload, terminator = record, "none"
        text = payload.decode("utf-8-sig" if number == 1 else "utf-8")
        records.append(
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
        raise ValueError("Charnock source byte accounting is not contiguous")
    return records


def _line_type(number: int, text: str) -> str:
    if not text:
        return "blank"
    if PAGE_RE.search(text):
        return "page-marker-line"
    stripped = text.strip()
    if stripped.startswith("DISCOURSE ") or (
        stripped.isupper() and len(stripped) < 120
    ):
        return "heading"
    if number >= 61842:
        return "transcriber-note-line"
    if number >= 59664:
        return "footnote-line"
    if number >= 56435:
        return "index-line"
    return "text-line"


def _add_lines(
    parent: etree._Element, records: list[dict[str, object]], prefix: str
) -> None:
    for row in records:
        node = etree.SubElement(parent, f"{{{TEI}}}ab")
        number = int(row["line"])
        node.set(XML_ID, f"{prefix}-line-{number:05d}")
        node.set("n", str(number))
        node.set("type", _line_type(number, str(row["text"])))
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text = str(row["text"])
        node.text = text if text else None


def _build_tei(
    work_id: str,
    volume: int,
    body: list[dict[str, object]],
    apparatus: list[dict[str, object]],
    source_sha: str,
) -> bytes:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(
        title_stmt, f"{{{TEI}}}title"
    ).text = f"The Existence and Attributes of God, Vol. {volume}"
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Stephen Charnock"
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(
        publication, f"{{{TEI}}}p"
    ).text = "Nonaccepted reconstruction candidate; publication:not_ready."
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI}}}bibl")
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="work-id").text = work_id
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="gutenberg").text = "53527"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="sha256").text = source_sha
    text = etree.SubElement(root, f"{{{TEI}}}text")
    body_node = etree.SubElement(text, f"{{{TEI}}}body")
    volume_node = etree.SubElement(
        body_node, f"{{{TEI}}}div", type="volume-body", n=str(volume)
    )
    _append_readable_volume(volume_node, body, f"charnock-v{volume}", volume=volume)
    _add_line_ledger(volume_node, body, f"charnock-v{volume}", volume=volume)
    shared = etree.SubElement(body_node, f"{{{TEI}}}div", type="shared-apparatus")
    head = etree.SubElement(shared, f"{{{TEI}}}head")
    head.text = "Combined index, footnotes, and transcriber notes shared by the two-volumes-in-one witness"
    _append_readable_apparatus(
        shared, apparatus, f"charnock-shared-v{volume}", volume=volume
    )
    _add_line_ledger(
        shared, apparatus, f"charnock-shared-v{volume}", volume=volume
    )
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _module_path(root: Path, name: str) -> Path | None:
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


def _closure(root: Path, entry: Path) -> tuple[dict[str, str], ...]:
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
                else (
                    _imports(path, root, node)
                    if isinstance(node, ast.ImportFrom)
                    else ()
                )
            )
            for name in names:
                dependency = _module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    work_id = str(profile.get("work_id"))
    if (
        work_id not in VOLUMES
        or source_manifest.record.get("source_id") != f"{work_id}-pg53527-retained"
    ):
        raise ValueError("Charnock work/source identity mismatch")
    volume, start, end = VOLUMES[work_id]
    source = source_manifest.authority_path("retained-source").read_bytes()
    authority = _authority(source_manifest, "retained-source")
    if len(source) != authority["bytes"] or _sha(source) != authority["sha256"]:
        raise ValueError("Charnock retained source drifted")
    records = _records(source)
    body = records[start - 1 : end]
    apparatus = records[APPARATUS[0] - 1 : APPARATUS[1]]
    represented_numbers = set(range(start, end + 1)) | set(
        range(APPARATUS[0], APPARATUS[1] + 1)
    )
    rows = []
    for row in records:
        number = int(row["line"])
        represented = number in represented_numbers
        rows.append(
            {
                **row,
                "disposition": "represented" if represented else "evidence-only",
                "reason": "selected volume or shared two-volume apparatus"
                if represented
                else "Gutenberg wrapper/license or other volume body",
                "tei_selector": f"#charnock-{'v' + str(volume) if number <= end else 'shared-v' + str(volume)}-line-{number:05d}"
                if represented
                else None,
            }
        )
    source_inventory_sha = _sha(
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
                for row in records
            ]
        )
    )
    counts = {
        "body_lines": len(body),
        "shared_apparatus_lines": len(apparatus),
        "page_marker_lines": sum(
            bool(PAGE_RE.search(str(row["text"]))) for row in [*body, *apparatus]
        ),
        "discourse_heading_lines": sum(
            str(row["text"]).strip().startswith("DISCOURSE ") for row in body
        ),
    }
    if (
        profile.get("source_scope")
        != {
            "bytes": len(source),
            "physical_lines": len(records),
            "source_inventory_sha256": source_inventory_sha,
        }
        or profile.get("required_counts") != counts
    ):
        raise ValueError("Charnock profile source scope or structure floor drifted")
    closure = _closure(source_manifest.repository_root, Path(__file__))
    closure_sha = _sha(_canonical(closure))
    if profile.get("producer_import_closure_sha256") != closure_sha:
        raise ValueError("Charnock producer import closure drifted")
    tei = _build_tei(work_id, volume, body, apparatus, _sha(source))
    accountability = {
        "contract": "ocd-charnock-pg53527-source-accountability-v1",
        "work_id": work_id,
        "source_member": {key: authority[key] for key in ("path", "bytes", "sha256")},
        "body_line_range": [start, end],
        "shared_apparatus_line_range": list(APPARATUS),
        "physical_line_count": len(records),
        "represented_line_count": len(represented_numbers),
        "evidence_only_line_count": len(records) - len(represented_numbers),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_inventory_sha256": source_inventory_sha,
        "required_counts": counts,
        "lines": rows,
    }
    provenance = {
        "contract": "ocd-charnock-pg53527-candidate-provenance-v1",
        "status": "nonaccepted",
        "publication": "not_ready",
        "work_id": work_id,
        "source_sha256": _sha(source),
        "source_manifest_sha256": source_manifest.sha256,
        "producer_import_closure": list(closure),
        "producer_import_closure_sha256": closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "shared_apparatus_disposition": "The retained digital witness is two volumes in one; its combined index, footnotes, and transcriber notes are represented in both volume candidates as explicitly shared edition apparatus, not relabeled volume body.",
    }
    unresolved = [
        {
            "id": f"{work_id}-edition-identity",
            "status": "unresolved",
            "detail": "The witness identifies Robert Carter & Brothers 1853, Baker Books 1996/2000, and a two-volumes-in-one digital transcription; no single normalized edition identity is asserted.",
        },
        {
            "id": f"{work_id}-rights",
            "status": "unresolved",
            "detail": "The retained wrapper states a United States basis, directs readers elsewhere to check local law, and retains Project Gutenberg license/trademark terms; this is not worldwide rights clearance.",
        },
        {
            "id": f"{work_id}-shared-apparatus",
            "status": "unresolved",
            "detail": "The source combines the index, footnotes, and transcriber notes after both volume bodies. They remain explicitly shared rather than being guessed into volume-exclusive subsets.",
        },
        {
            "id": f"{work_id}-human-acceptance",
            "status": "unresolved",
            "detail": "This candidate is nonaccepted and has no human textual, identity, editorial, or rights acceptance.",
        },
    ]
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": source_manifest.authority_path(
            "attribution-readme"
        ).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
