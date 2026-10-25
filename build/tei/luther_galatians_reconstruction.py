"""Source-bound TEI route for Project Gutenberg 1549, Luther on Galatians."""

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


WORK_ID = "luther-commentary-on-galatians"
SOURCE_ID = "luther-commentary-on-galatians-pg1549-retained"
SOURCE_PATH = "raw/gutenberg/pg1549.txt"
CONVERTER_ID = "ocd-luther-galatians-pg1549-line-faithful-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
CHAPTER_LINES = (166, 1410, 2935, 5181, 6703, 8250)
VERSE_CARRIER = re.compile(r"^\s+VERSES?\s+\d")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _records(data: bytes) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    offset = 0
    for number, raw in enumerate(data.splitlines(keepends=True), 1):
        if raw.endswith(b"\r\n"):
            payload, ending = raw[:-2], "CRLF"
        elif raw.endswith(b"\n"):
            payload, ending = raw[:-1], "LF"
        elif raw.endswith(b"\r"):
            payload, ending = raw[:-1], "CR"
        else:
            payload, ending = raw, "none"
        text = payload.decode("utf-8-sig" if number == 1 else "utf-8", errors="strict")
        result.append({
            "line": number,
            "byte_start": offset,
            "byte_end": offset + len(raw),
            "terminator": ending,
            "text": text,
            "record_sha256": _sha(raw),
        })
        offset += len(raw)
    if offset != len(data):
        raise ValueError("Luther Galatians source byte accounting is not contiguous")
    return result


def _chapter_starts(rows: list[dict[str, object]]) -> tuple[int, ...]:
    found = tuple(
        int(row["line"])
        for row in rows
        if re.fullmatch(r"CHAPTER [1-6]", str(row["text"]))
    )
    if found != CHAPTER_LINES:
        raise ValueError(f"Luther Galatians chapter boundaries drifted: {found}")
    return found


def _counts(rows: list[dict[str, object]]) -> dict[str, object]:
    starts = _chapter_starts(rows)
    carriers = [str(row["text"]) for row in rows if VERSE_CARRIER.match(str(row["text"]))]
    singular = sum(text.lstrip().startswith("VERSE ") for text in carriers)
    plural = sum(text.lstrip().startswith("VERSES ") for text in carriers)
    return {
        "physical_lines": len(rows),
        "blank_lines": sum(str(row["text"]) == "" for row in rows),
        "whitespace_only_lines": sum(bool(str(row["text"])) and not str(row["text"]).strip() for row in rows),
        "nonblank_lines": sum(bool(str(row["text"]).strip()) for row in rows),
        "chapter_count": len(starts),
        "chapter_heading_lines": list(starts),
        "singular_verse_carrier_count": singular,
        "plural_verse_carrier_count": plural,
        "verse_carrier_count": len(carriers),
        "represented_lines": len(rows),
        "unrepresented_lines": 0,
    }


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    authorities = manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Luther Galatians manifest authorities are invalid")
    matches = [item for item in authorities if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Luther Galatians authority {name} cardinality mismatch")
    return matches[0]


def _module_file(root: Path, dotted: str) -> Path | None:
    base = root.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate.resolve(strict=True)
    return None


def _closure(root: Path, entry: Path, forbidden: tuple[str, ...] = ()) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    seen: set[Path] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        current.relative_to(root)
        seen.add(current)
        tree = ast.parse(current.read_text(encoding="utf-8"), filename=str(current))
        targets: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = list(current.relative_to(root).parts[:-1])
                    prefix = ".".join([*package[: len(package) - node.level + 1], *((node.module or "").split(".") if node.module else [])])
                else:
                    prefix = node.module or ""
                targets.extend([prefix, *(f"{prefix}.{alias.name}" for alias in node.names if alias.name != "*")])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "__import__"}:
                raise ValueError("Luther Galatians route contains dynamic execution")
        for target in targets:
            if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden):
                raise ValueError(f"Luther Galatians independent oracle imports forbidden producer {target}")
            dependency = _module_file(root, target)
            if dependency is not None and dependency not in seen:
                pending.append(dependency)
    return tuple({"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix()))


def _line_id(number: int) -> str:
    return f"luther-galatians-line-{number:05d}"


def _append_line(parent: etree._Element, row: Mapping[str, object]) -> str:
    number = int(row["line"])
    text = str(row["text"])
    line_id = _line_id(number)
    carrier_kind = "verse-carrier" if VERSE_CARRIER.match(text) else ("blank-line" if text == "" else "source-line")
    node = etree.SubElement(parent, f"{{{TEI}}}ab", {XML_ID: line_id, "type": carrier_kind, XML_SPACE: "preserve"})
    if text:
        node.text = text
    return f"#{line_id}"


def _work_ranges(rows: list[dict[str, object]]) -> list[tuple[str, int, int]]:
    starts = _chapter_starts(rows)
    ranges = [("gutenberg-header", 1, 29), ("work-front-matter", 30, starts[0] - 1)]
    ranges.extend((f"chapter-{index}", start, (starts[index] - 1 if index < len(starts) else 8799)) for index, start in enumerate(starts, 1))
    ranges.append(("gutenberg-footer", 8800, len(rows)))
    if len(rows) != 9150 or ranges[0][1:] != (1, 29) or ranges[-1][1:] != (8800, 9150):
        raise ValueError("Luther Galatians Gutenberg envelope is not the pinned member")
    return ranges


def _tei(rows: list[dict[str, object]], source_sha: str) -> bytes:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI}, attrib={"{http://www.w3.org/XML/1998/namespace}lang": "en"})
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = "COMMENTARY ON THE EPISTLE TO THE GALATIANS"
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Martin Luther"
    resp = etree.SubElement(title_stmt, f"{{{TEI}}}respStmt")
    etree.SubElement(resp, f"{{{TEI}}}resp").text = "Translator"
    etree.SubElement(resp, f"{{{TEI}}}name").text = "Theodore Graebner"
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}p").text = "Nonaccepted technical reconstruction candidate; no rights or publication decision is made here."
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    etree.SubElement(source_desc, f"{{{TEI}}}p").text = f"Retained source raw/gutenberg/pg1549.txt, SHA-256 {source_sha}."
    text_node = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text_node, f"{{{TEI}}}body")
    for name, first, last in _work_ranges(rows):
        if name.startswith("chapter-"):
            number = int(name.split("-")[-1])
            div = etree.SubElement(body, f"{{{TEI}}}div", {"type": "chapter", "n": str(number)})
            heading = etree.SubElement(div, f"{{{TEI}}}head", {XML_ID: _line_id(first)})
            heading.text = str(rows[first - 1]["text"])
            for row in rows[first:last]:
                _append_line(div, row)
        else:
            region_type = "source-envelope" if name in {"gutenberg-header", "gutenberg-footer"} else "front-matter"
            div = etree.SubElement(body, f"{{{TEI}}}div", {"type": region_type, "subtype": name})
            for row in rows[first - 1:last]:
                _append_line(div, row)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _accountability(rows: list[dict[str, object]], source_sha: str) -> dict[str, object]:
    line_records = []
    for row in rows:
        line_records.append({
            **row,
            "disposition": "represented",
            "reason": "Physical source line preserved in source order; chapter headings and verse-carrier occurrences retain source-derived physical-line locations.",
            "tei_selector": f"#{_line_id(int(row['line']))}",
        })
    inventory = [{key: row[key] for key in ("line", "byte_start", "byte_end", "terminator", "record_sha256")} for row in rows]
    return {
        "contract": "ocd-luther-galatians-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member": {"path": SOURCE_PATH, "bytes": sum(int(row["byte_end"]) - int(row["byte_start"]) for row in rows), "sha256": source_sha},
        "physical_line_count": len(rows),
        "represented_line_count": len(rows),
        "evidence_only_line_count": 0,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_inventory_sha256": _sha(_canonical(inventory)),
        "required_counts": _counts(rows),
        "lines": line_records,
    }


def _unresolved() -> bytes:
    items = [
        {"id": "edition-identity", "status": "unresolved", "scope": "The retained header identifies a Gutenberg English text and title-page date; this candidate does not make a new edition-equivalence determination."},
        {"id": "verse-carrier-count-semantics", "status": "unresolved", "scope": "The assignment names 217 repeated carriers; a direct source scan finds 216 singular VERSE and 14 plural VERSES carrier lines. All 230 literal occurrences are preserved, without verse-number identity attributes."},
        {"id": "rights-clearance", "status": "unresolved", "scope": "The retained Gutenberg license text is preserved in the envelope; no jurisdictional rights clearance is asserted."},
        {"id": "human-acceptance", "status": "pending", "scope": "This nonaccepted candidate has not received human visual review or acceptance."},
    ]
    return b"".join(_canonical(item) for item in items)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("source_id") != SOURCE_ID or source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Luther Galatians source/work identity mismatch")
    source = source_manifest.authority_path("retained-source").read_bytes()
    retained = _authority(source_manifest, "retained-source")
    if len(source) != retained.get("bytes") or _sha(source) != retained.get("sha256"):
        raise ValueError("Luther Galatians retained-source binding drifted")
    rows = _records(source)
    if not source.startswith(b"\xef\xbb\xbf") or any(row["terminator"] != "CRLF" for row in rows):
        raise ValueError("Luther Galatians source BOM or CRLF framing drifted")
    if (
        str(rows[28]["text"]) != "*** START OF THE PROJECT GUTENBERG EBOOK COMMENTARY ON THE EPISTLE TO THE GALATIANS ***"
        or str(rows[8799]["text"]) != "*** END OF THE PROJECT GUTENBERG EBOOK COMMENTARY ON THE EPISTLE TO THE GALATIANS ***"
    ):
        raise ValueError("Luther Galatians Gutenberg envelope markers drifted")
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    counts = _counts(rows)
    expected_scope = profile.get("source_scope")
    expected_envelope = profile.get("envelope")
    if (
        expected_scope != {"path": SOURCE_PATH, "bytes": len(source), "sha256": _sha(source), "physical_lines": len(rows), "encoding": "UTF-8 with BOM", "line_ending": "CRLF"}
        or expected_envelope != {"header_and_start_marker_lines": [1, 29], "work_lines": [30, 8799], "end_marker_and_footer_lines": [8800, 9150], "chapter_heading_lines": list(CHAPTER_LINES)}
        or profile.get("required_counts") != counts
        or counts != {"physical_lines": 9150, "blank_lines": 1576, "whitespace_only_lines": 8, "nonblank_lines": 7566, "chapter_count": 6, "chapter_heading_lines": list(CHAPTER_LINES), "singular_verse_carrier_count": 216, "plural_verse_carrier_count": 14, "verse_carrier_count": 230, "represented_lines": 9150, "unrepresented_lines": 0}
    ):
        raise ValueError("Luther Galatians profile or source carrier census drifted")
    closure = _closure(source_manifest.repository_root, Path(__file__).resolve(strict=True))
    closure_sha = _sha(_canonical(closure))
    if profile.get("producer_import_closure_sha256") != closure_sha:
        raise ValueError("Luther Galatians producer import closure drifted")
    runtime = f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"
    provenance = {
        "contract": "ocd-luther-galatians-candidate-provenance-v1",
        "status": "nonaccepted",
        "publication": "not_ready",
        "work_id": WORK_ID,
        "source_sha256": _sha(source),
        "source_manifest_sha256": source_manifest.sha256,
        "producer_import_closure": list(closure),
        "producer_import_closure_sha256": closure_sha,
        "runtime": runtime,
        "source_scope": expected_scope,
        "required_counts": counts,
        "verse_identity_policy": "No verse-number identity is asserted; source occurrences are located only by physical line number.",
    }
    return {
        "README.source.md": source_manifest.authority_path("attribution-readme").read_bytes(),
        "content.tei.xml": _tei(rows, _sha(source)),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(_accountability(rows, _sha(source))),
        "unresolved.jsonl": _unresolved(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
