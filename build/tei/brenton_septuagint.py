"""Faithful deterministic TEI candidate for eBible's corrected eng-Brenton."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import compiled_schema


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SOURCE_PREFIX = "source-usfm:eng-Brenton/"
CONFIG_RELATIVE = "sources/structured-text/brenton-septuagint/config.json"
RAW_RELATIVE = "raw/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint"
OUTPUT_PREFIX = "reports/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint/"
DEFAULT_OUTPUT = OUTPUT_PREFIX + "candidate"

MEMBER_IDS = (
    "FRT", "INT", "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT",
    "1SA", "2SA", "1KI", "2KI", "1CH", "2CH", "EZR", "NEH", "JOB", "PSA",
    "PRO", "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "HOS", "JOL", "AMO",
    "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL", "TOB",
    "JDT", "ESG", "WIS", "SIR", "BAR", "LJE", "SUS", "BEL", "1MA", "2MA",
    "1ES", "MAN", "3MA", "4MA", "DAG", "BAK", "OTH", "XXA", "XXB", "XXC",
)
PARATEXT_IDS = frozenset({"FRT", "INT", "BAK", "OTH", "XXA", "XXB", "XXC"})
TEXTUAL_IDS = tuple(value for value in MEMBER_IDS if value not in PARATEXT_IDS)

LINE_MARKERS = {
    "id", "h", "toc1", "toc2", "toc3", "mt1", "mt2", "c", "v", "p", "nb",
    "b", "d", "im", "ip", "ib", "is1", "is2", "tr", "tc1", "tc2",
}
PAIRED_INLINE = {"add", "f", "x", "sc", "it", "+it", "vp"}
INTERNAL_INLINE = {"fr", "ft", "fqa", "xo", "xt", "fl"}
INLINE_TOKEN = re.compile(r"\\([+]?[A-Za-z0-9_-]+)(\*)?")
SOURCE_POINTER = re.compile(
    r"^source-usfm:eng-Brenton/(?P<file>[^#]+)#line=(?P<line>[1-9][0-9]*)$"
)


def _q(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _load_config(repository_root: Path) -> dict[str, Any]:
    value = json.loads((repository_root / CONFIG_RELATIVE).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("source config is not an object")
    return value


def _member(path: Path, root: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(content),
        "sha256": _sha(content),
    }


def _members(root: Path, paths: Iterable[Path]) -> list[dict[str, object]]:
    return [_member(path, root) for path in sorted(paths)]


def _member_inventory(root: Path) -> tuple[list[dict[str, object]], str]:
    inventory = _members(root, (path for path in root.rglob("*") if path.is_file()))
    return inventory, _sha(_canonical(inventory))


def _shallow_member_inventory(root: Path) -> tuple[list[dict[str, object]], str]:
    inventory = _members(root, (path for path in root.iterdir() if path.is_file()))
    return inventory, _sha(_canonical(inventory))


def _parse_source_line(line: str) -> tuple[str, str]:
    if not line.startswith("\\"):
        raise ValueError(f"USFM line does not begin with a marker: {line!r}")
    parts = line[1:].split(maxsplit=1)
    return parts[0], parts[1] if len(parts) == 2 else ""


def _member_id(path: Path) -> str:
    first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    marker, content = _parse_source_line(first)
    if marker != "id" or not content:
        raise ValueError(f"USFM member does not start with an id: {path.name}")
    return content.split()[0]


def _member_files(source_root: Path) -> list[Path]:
    by_id: dict[str, Path] = {}
    for path in source_root.glob("*.usfm"):
        member_id = _member_id(path)
        if member_id in by_id:
            raise ValueError(f"duplicate USFM member id: {member_id}")
        by_id[member_id] = path
    if set(by_id) != set(MEMBER_IDS):
        raise ValueError("authority member-id set mismatch")
    return [by_id[member_id] for member_id in MEMBER_IDS]


def _flat_marker_counts(lines: Iterable[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        for marker, closing in INLINE_TOKEN.findall(line):
            counts[marker + ("*" if closing else "")] += 1
    return counts


def _validate_authority_root(
    source_root: Path, config: dict[str, Any]
) -> dict[str, object]:
    inventory, inventory_sha256 = _shallow_member_inventory(source_root)
    expected = config["authority"]
    if inventory_sha256 != expected["member_inventory_sha256"]:
        raise ValueError("authority member inventory digest mismatch")
    if len(inventory) != expected["member_count"]:
        raise ValueError("authority member count mismatch")
    files = _member_files(source_root)
    if len(files) != expected["usfm_file_count"]:
        raise ValueError("authority USFM-file count mismatch")

    chapter_count = 0
    verse_count = 0
    source_line_count = 0
    terminal_newline_files = 0
    line_markers: Counter[str] = Counter()
    inline_markers: Counter[str] = Counter()
    addresses: set[tuple[str, str, str]] = set()
    merged_verse_labels: list[dict[str, str]] = []
    for path in files:
        member_id = _member_id(path)
        content = path.read_bytes()
        if content.startswith(b"\xef\xbb\xbf"):
            raise ValueError(f"unexpected UTF-8 BOM in {path.name}")
        if b"\r" in content:
            raise ValueError(f"non-LF line ending in {path.name}")
        if content.endswith(b"\n"):
            terminal_newline_files += 1
        lines = content.decode("utf-8").split("\n")
        source_line_count += len(lines)
        inline_markers.update(_flat_marker_counts(lines))
        current_chapter = ""
        for line_number, line in enumerate(lines, start=1):
            marker, marker_content = _parse_source_line(line)
            if marker not in LINE_MARKERS:
                raise ValueError(
                    f"unsupported line marker {marker!r} in {path.name}:{line_number}"
                )
            line_markers[marker] += 1
            if marker == "c":
                chapter_count += 1
                current_chapter = marker_content.split()[0]
            elif marker == "v":
                verse_count += 1
                if not current_chapter:
                    raise ValueError(f"verse precedes chapter in {path.name}:{line_number}")
                verse_label = marker_content.split(maxsplit=1)[0]
                address = (member_id, current_chapter, verse_label)
                if address in addresses:
                    raise ValueError(f"duplicate verse address: {address!r}")
                addresses.add(address)
                if not verse_label.isdigit():
                    merged_verse_labels.append(
                        {"member": member_id, "chapter": current_chapter, "verse": verse_label}
                    )

    for marker in PAIRED_INLINE:
        if inline_markers[marker] != inline_markers[marker + "*"]:
            raise ValueError(f"unbalanced inline marker: {marker}")
    allowed = LINE_MARKERS | PAIRED_INLINE | INTERNAL_INLINE
    unknown = {
        marker.removesuffix("*")
        for marker in inline_markers
        if marker.removesuffix("*") not in allowed
    }
    if unknown:
        raise ValueError(f"unsupported inline markers: {sorted(unknown)}")
    return {
        "member_count": len(inventory),
        "usfm_file_count": len(files),
        "member_ids": list(MEMBER_IDS),
        "textual_book_count": len(TEXTUAL_IDS),
        "paratext_file_count": len(PARATEXT_IDS),
        "member_inventory_sha256": inventory_sha256,
        "chapter_count": chapter_count,
        "verse_count": verse_count,
        "source_line_count": source_line_count,
        "terminal_newline_files": terminal_newline_files,
        "line_marker_counts": dict(sorted(line_markers.items())),
        "inline_marker_counts": dict(sorted(inline_markers.items())),
        "merged_verse_labels": merged_verse_labels,
    }


def _validate_file_binding(path: Path, binding: dict[str, Any], label: str) -> None:
    content = path.read_bytes()
    if len(content) != binding["bytes"]:
        raise ValueError(f"{label} byte count mismatch")
    if _sha(content) != binding["sha256"]:
        raise ValueError(f"{label} digest mismatch")


def _validate_acquisition(
    repository_root: Path, config: dict[str, Any]
) -> dict[str, object]:
    authority = config["authority"]
    comparison = config["comparison_carrier"]
    _validate_file_binding(
        resolve_repo_path(repository_root, config["source_file"]),
        {"bytes": authority["archive_bytes"], "sha256": authority["archive_sha256"]},
        "authority archive",
    )
    _validate_file_binding(
        resolve_repo_path(repository_root, config["comparison_source_file"]),
        {"bytes": comparison["archive_bytes"], "sha256": comparison["archive_sha256"]},
        "comparison archive",
    )
    _validate_file_binding(
        resolve_repo_path(repository_root, config["rendering_witness"]["path"]),
        config["rendering_witness"],
        "rendering witness",
    )
    raw_root = resolve_repo_path(repository_root, RAW_RELATIVE)
    required_tokens = {
        "metadata/official-index.html": (
            b"1870 Introduction", b"1844 Preface", b"Errata", b"Appendix",
        ),
        "metadata/official-details-page.html": (
            b"eng-Brenton_usfx.zip", b"eng-Brenton_usfm.zip", b"Public Domain",
        ),
        "metadata/official-pdf-list.html": (
            b"eng-Brenton_all.pdf", b"eng-Brenton_3MA.pdf", b"eng-Brenton_4MA.pdf",
            b"eng-Brenton_XXA.pdf", b"eng-Brenton_XXB.pdf", b"eng-Brenton_XXC.pdf",
            b"eng-Brenton_BAK.pdf",
        ),
    }
    for relative, tokens in required_tokens.items():
        content = (raw_root / relative).read_bytes()
        missing = [token.decode("ascii") for token in tokens if token not in content]
        if missing:
            raise ValueError(f"official metadata {relative} is missing {missing}")
    headers = sorted((raw_root / "http-headers").glob("*.txt"))
    if len(headers) != 7:
        raise ValueError("retained HTTP-header count mismatch")
    inventory, inventory_sha256 = _member_inventory(raw_root)
    return {
        "raw_root": str(raw_root),
        "retained_file_count": len(inventory),
        "retained_file_inventory_sha256": inventory_sha256,
        "retained_files": inventory,
        "http_header_files": len(headers),
    }


def _validate_comparison_carrier(
    repository_root: Path, config: dict[str, Any]
) -> dict[str, object]:
    root = resolve_repo_path(repository_root, config["comparison_source_root"])
    inventory, inventory_sha256 = _shallow_member_inventory(root)
    expected = config["comparison_carrier"]
    if len(inventory) != expected["member_count"]:
        raise ValueError("comparison carrier member count mismatch")
    if inventory_sha256 != expected["member_inventory_sha256"]:
        raise ValueError("comparison carrier member inventory digest mismatch")
    member_ids: list[str] = []
    chapter_count = 0
    verse_count = 0
    source = root / "eng-Brenton_usfx.xml"
    for _, element in etree.iterparse(str(source), events=("end",), huge_tree=True):
        if element.tag == "book":
            member_id = element.get("id")
            if member_id is None:
                raise ValueError("USFX book lacks id")
            member_ids.append(member_id)
        elif element.tag == "c":
            chapter_count += 1
        elif element.tag == "v":
            verse_count += 1
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
    if member_ids != list(MEMBER_IDS):
        raise ValueError("comparison carrier member order mismatch")
    return {
        "member_count": len(member_ids),
        "member_ids": member_ids,
        "chapter_count": chapter_count,
        "verse_count": verse_count,
        "archive_member_count": len(inventory),
        "member_inventory_sha256": inventory_sha256,
    }


def _append_text(parent: etree._Element, value: str) -> None:
    if not value:
        return
    if len(parent):
        child = parent[-1]
        child.tail = (child.tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _inline_element(parent: etree._Element, marker: str) -> etree._Element:
    if marker == "add":
        return etree.SubElement(parent, _q("supplied"), reason="source-marked")
    if marker == "f":
        return etree.SubElement(parent, _q("note"), type="footnote")
    if marker == "x":
        return etree.SubElement(parent, _q("note"), type="cross-reference")
    if marker == "sc":
        return etree.SubElement(parent, _q("hi"), rend="small-caps")
    if marker in {"it", "+it"}:
        return etree.SubElement(parent, _q("hi"), rend="italic")
    if marker == "vp":
        return etree.SubElement(parent, _q("seg"), type="source-verse-number")
    raise ValueError(f"unsupported paired inline marker: {marker}")


def _append_inline(parent: etree._Element, value: str) -> None:
    stack: list[tuple[str, etree._Element]] = [("root", parent)]
    position = 0
    for token in INLINE_TOKEN.finditer(value):
        _append_text(stack[-1][1], value[position:token.start()])
        marker = token.group(1)
        closing = token.group(2) == "*"
        if closing:
            matching = next(
                (index for index in range(len(stack) - 1, 0, -1) if stack[index][0] == marker),
                None,
            )
            if matching is None:
                raise ValueError(f"unmatched closing inline marker: {marker}")
            stack = stack[:matching]
        elif marker in PAIRED_INLINE:
            child = _inline_element(stack[-1][1], marker)
            stack.append((marker, child))
        elif marker in INTERNAL_INLINE:
            container = next(
                (
                    index for index in range(len(stack) - 1, 0, -1)
                    if stack[index][0] in {"f", "x"}
                ),
                None,
            )
            if container is None:
                raise ValueError(f"inline submarker {marker} is outside a note")
            stack = stack[:container + 1]
            child = etree.SubElement(stack[-1][1], _q("seg"), type=f"usfm-{marker}")
            stack.append((marker, child))
        else:
            raise ValueError(f"unsupported inline marker: {marker}")
        position = token.end()
    _append_text(stack[-1][1], value[position:])
    unclosed = [marker for marker, _ in stack[1:] if marker in PAIRED_INLINE]
    if unclosed:
        raise ValueError(f"unclosed inline markers: {unclosed}")


def _source_pointer(path: Path, line_number: int) -> str:
    return f"{SOURCE_PREFIX}{path.name}#line={line_number}"


def _add_raw_note(parent: etree._Element, raw_line: str) -> None:
    etree.SubElement(parent, _q("note"), type="source-usfm-raw").text = raw_line


def _add_line_element(
    parent: etree._Element,
    tag: str,
    marker: str,
    content: str,
    raw_line: str,
    pointer: str,
    **attributes: str,
) -> etree._Element:
    node = etree.SubElement(parent, _q(tag), corresp=pointer, **attributes)
    node.set("n", marker) if "n" not in attributes else None
    _add_raw_note(node, raw_line)
    _append_inline(node, content)
    return node


def _make_header(root: etree._Element, config: dict[str, Any]) -> None:
    header = etree.SubElement(root, _q("teiHeader"))
    file_desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = config["title"]
    statement = etree.SubElement(title_stmt, _q("respStmt"))
    etree.SubElement(statement, _q("resp")).text = "Translation"
    etree.SubElement(statement, _q("name")).text = config["translator"]
    publication = etree.SubElement(file_desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("publisher")).text = (
        "Open Christian Data nonaccepted ticket-21 candidate; not publication."
    )
    availability = etree.SubElement(publication, _q("availability"), status="free")
    etree.SubElement(availability, _q("licence"), target=config["source_url"]).text = (
        "The official eBible record identifies Brenton as public domain."
    )
    source_desc = etree.SubElement(file_desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = config["source_edition"]
    etree.SubElement(bibl, _q("ref"), target=config["source_url"]).text = (
        "Official eBible eng-Brenton source page"
    )
    encoding = etree.SubElement(header, _q("encodingDesc"))
    etree.SubElement(encoding, _q("p")).text = (
        "Every exact USFM source line is retained in a source-usfm-raw note and "
        "projected into source-defined member, chapter, verse, note, cross-reference, "
        "table, supplied-text, typography, and paratext structures."
    )
    etree.SubElement(encoding, _q("p")).text = (
        "The eBible PDF is a generated rendering witness only. Electronic corrections "
        "are documented by the retained Errata member and are not independently altered."
    )
    profile = etree.SubElement(header, _q("profileDesc"))
    usage = etree.SubElement(profile, _q("langUsage"))
    etree.SubElement(usage, _q("language"), ident="en").text = "English"
    revision = etree.SubElement(header, _q("revisionDesc"))
    etree.SubElement(revision, _q("change"), when=config["retrieved_at_utc"][:10]).text = (
        "Generated deterministic nonaccepted TEI candidate."
    )


def _render_member(body: etree._Element, path: Path) -> None:
    lines = path.read_text(encoding="utf-8").split("\n")
    member_id = _member_id(path)
    member: etree._Element | None = None
    chapter: etree._Element | None = None
    current_chapter = ""
    table: etree._Element | None = None
    row: etree._Element | None = None
    for line_number, raw_line in enumerate(lines, start=1):
        marker, content = _parse_source_line(raw_line)
        pointer = _source_pointer(path, line_number)
        if marker == "id":
            member = etree.SubElement(
                body,
                _q("div"),
                type="paratext" if member_id in PARATEXT_IDS else "book",
                n=member_id,
                corresp=pointer,
            )
            member.set(XML_ID, f"brenton-{member_id}")
            _add_raw_note(member, raw_line)
            _add_line_element(
                member, "ab", "id-label", content, raw_line, pointer + ":label",
                type="source-id-label",
            )
            continue
        if member is None:
            raise ValueError(f"content precedes id in {path.name}:{line_number}")
        container = chapter if chapter is not None else member
        if marker not in {"tr", "tc1", "tc2"}:
            table = None
            row = None
        if marker == "c":
            current_chapter = content.split()[0]
            chapter = etree.SubElement(
                member, _q("div"), type="chapter", n=current_chapter, corresp=pointer
            )
            chapter.set(XML_ID, f"brenton-{member_id}-{current_chapter}")
            _add_raw_note(chapter, raw_line)
        elif marker == "v":
            if chapter is None:
                raise ValueError(f"verse precedes chapter in {path.name}:{line_number}")
            parts = content.split(maxsplit=1)
            verse_label = parts[0]
            verse_text = parts[1] if len(parts) == 2 else ""
            node = _add_line_element(
                chapter, "ab", marker, verse_text, raw_line, pointer,
                type="verse", n=verse_label,
            )
            node.set(XML_ID, f"brenton-{member_id}-{current_chapter}-{verse_label}")
        elif marker in {"tr", "tc1", "tc2"}:
            if marker == "tr":
                if table is None:
                    table = etree.SubElement(container, _q("table"), type="source-table")
                row = etree.SubElement(table, _q("row"), role="data")
                source_cell = etree.SubElement(
                    row, _q("cell"), role="label", corresp=pointer
                )
                _add_raw_note(source_cell, raw_line)
            else:
                if row is None:
                    raise ValueError(f"table cell precedes row in {path.name}:{line_number}")
                cell = etree.SubElement(
                    row, _q("cell"), n=marker.removeprefix("tc"), corresp=pointer
                )
                _add_raw_note(cell, raw_line)
                _append_inline(cell, content)
        elif marker in {"h", "toc1", "toc2", "toc3", "mt1", "mt2", "d", "is1", "is2"}:
            _add_line_element(
                container, "ab", marker, content, raw_line, pointer, type=f"usfm-{marker}"
            )
        else:
            line_type = {
                "p": "paragraph-break",
                "nb": "continuation-paragraph",
                "b": "stanza-break",
                "im": "introduction-line",
                "ip": "introduction-paragraph",
                "ib": "introduction-break",
            }[marker]
            _add_line_element(
                container, "ab", marker, content, raw_line, pointer, type=line_type
            )


def _verify_source_files(tei_bytes: bytes, source_root: Path) -> dict[str, object]:
    root = etree.fromstring(
        tei_bytes,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    reconstructed: dict[str, dict[int, str]] = defaultdict(dict)
    for node in root.iter():
        pointer = node.get("corresp")
        if pointer is None or not pointer.startswith(SOURCE_PREFIX):
            continue
        match = SOURCE_POINTER.fullmatch(pointer)
        if match is None:
            continue
        raw_notes = [
            child for child in node
            if child.tag == _q("note") and child.get("type") == "source-usfm-raw"
        ]
        if len(raw_notes) != 1 or raw_notes[0].text is None:
            raise ValueError(f"source pointer lacks one exact raw note: {pointer}")
        file_name = match.group("file")
        line_number = int(match.group("line"))
        if line_number in reconstructed[file_name]:
            raise ValueError(f"duplicate source pointer: {pointer}")
        reconstructed[file_name][line_number] = raw_notes[0].text
    files = _member_files(source_root)
    if set(reconstructed) != {path.name for path in files}:
        raise ValueError("TEI source-file coverage mismatch")
    verified_lines = 0
    for path in files:
        expected = path.read_text(encoding="utf-8")
        numbers = list(range(1, len(expected.split("\n")) + 1))
        lines = reconstructed[path.name]
        if sorted(lines) != numbers:
            raise ValueError(f"TEI source-line coverage mismatch: {path.name}")
        if "\n".join(lines[number] for number in numbers) != expected:
            raise ValueError(f"TEI source-file roundtrip mismatch: {path.name}")
        verified_lines += len(numbers)
    return {
        "source_file_roundtrip_exact": True,
        "source_files_verified": len(files),
        "source_lines_verified": verified_lines,
    }


def _tei(
    repository_root: Path, config: dict[str, Any]
) -> tuple[bytes, dict[str, object]]:
    source_root = resolve_repo_path(repository_root, config["source_root"])
    authority = _validate_authority_root(source_root, config)
    comparison = _validate_comparison_carrier(repository_root, config)
    if (
        comparison["member_count"] != authority["usfm_file_count"]
        or comparison["chapter_count"] != authority["chapter_count"]
        or comparison["verse_count"] != authority["verse_count"]
    ):
        raise ValueError("USFM and USFX structural censuses differ")
    root = etree.Element(_q("TEI"), nsmap={None: TEI_NS})
    root.set(XML_ID, "brenton-septuagint-eng-Brenton")
    root.set(XML_LANG, "en")
    root.set("ana", "#nonaccepted-candidate")
    _make_header(root, config)
    body = etree.SubElement(etree.SubElement(root, _q("text")), _q("body"))
    for path in _member_files(source_root):
        _render_member(body, path)
    tei_bytes = etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    parsed = etree.fromstring(
        tei_bytes,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    compiled_schema().assertValid(etree.ElementTree(parsed))
    roundtrip = _verify_source_files(tei_bytes, source_root)
    return tei_bytes, {"authority": authority, "comparison": comparison, **roundtrip}


def _witness_boundaries(config: dict[str, Any]) -> dict[str, object]:
    return {
        "contract": "ocd-brenton-witness-boundaries-v1",
        "structured_authority": "eBible eng-Brenton USFM package",
        "comparison_carrier": "eBible eng-Brenton USFX package",
        "rendering_witness": config["rendering_witness"],
        "rendering_witness_is_transformation_authority": False,
        "electronic_corrections": {
            "documented_by": "101-XXCeng-Brenton.usfm",
            "treatment": "preserved exactly as supplied; no independent modernization",
        },
        "structured_member_order": list(MEMBER_IDS),
        "pdf_terminal_order": ["OTH", "XXA", "XXB", "XXC", "BAK"],
        "structured_and_pdf_terminal_order_differs": True,
        "order_treatment": (
            "The candidate follows the USFM/USFX structured authority order, where BAK "
            "precedes OTH/XXA/XXB/XXC; the generated PDF renders Appendix last."
        ),
        "print_only_content_claimed": False,
        "independent_historical_print_scan_retained": False,
        "historical_print_typography_reconstructed": False,
        "candidate_status": "nonaccepted",
        "human_identity_and_textual_review_required": True,
    }


def _build_candidate(repository_root: Path) -> dict[str, bytes]:
    repository_root = repository_root.resolve()
    config = _load_config(repository_root)
    acquisition = _validate_acquisition(repository_root, config)
    tei_bytes, evidence = _tei(repository_root, config)
    authority = evidence["authority"]
    comparison = evidence["comparison"]
    line_counts = authority["line_marker_counts"]
    inline_counts = authority["inline_marker_counts"]
    text_counts = {
        "textual_books": len(TEXTUAL_IDS),
        "paratext_members": len(PARATEXT_IDS),
        "chapters": authority["chapter_count"],
        "verse_records": authority["verse_count"],
        "source_lines": authority["source_line_count"],
        "footnotes": inline_counts["f"],
        "cross_references": inline_counts["x"],
        "supplied_text_spans": inline_counts["add"],
        "small_caps_spans": inline_counts["sc"],
        "italic_spans": inline_counts["it"] + inline_counts["+it"],
        "verse_number_spans": inline_counts["vp"],
        "table_rows": line_counts["tr"],
        "table_cells": line_counts["tc1"] + line_counts["tc2"],
    }
    receipt = {
        "contract": "ocd-brenton-source-receipt-v1",
        "resource_id": config["resource_id"],
        "title": config["title"],
        "translator": config["translator"],
        "source_url": config["source_url"],
        "source_download_url": config["source_download_url"],
        "retrieved_at_utc": config["retrieved_at_utc"],
        "source_files_dated": config["source_files_dated"],
        "generated_html_dated": config["generated_html_dated"],
        "source_edition": config["source_edition"],
        "rights": {
            "status": "public-domain",
            "evidence": "The retained official eBible source and details pages identify Brenton as public domain.",
        },
        "authority": config["authority"],
        "comparison_carrier": config["comparison_carrier"],
        "rendering_witness": config["rendering_witness"],
        "retained_file_count": acquisition["retained_file_count"],
        "retained_file_inventory_sha256": acquisition["retained_file_inventory_sha256"],
        "retained_files": acquisition["retained_files"],
        "completeness_spot_check": {
            "opening": "FRT abbreviations, INT 1870 introduction, Genesis 1:1",
            "middle": "III Maccabees 1:1 and IV Maccabees 1:1",
            "textual_ending": "IV Maccabees 18:24",
            "terminal_paratext": [
                "Appendix", "Books of the Apocrypha overview", "Jeremiah table",
                "1844 preface", "Errata",
            ],
            "unusual": [
                "footnotes", "cross-references", "supplied text", "small caps",
                "italics", "source verse-number spans", "tables",
            ],
        },
        "unresolved_questions": [
            (
                "Human review must decide whether the corrected 2025-12-12 eBible "
                "electronic edition identity is sufficient for catalog acceptance."
            ),
            (
                "The structured package places Appendix before the remaining terminal "
                "paratext, while the generated PDF renders Appendix last."
            ),
            (
                "No independent historical print scan was retained; no print-only "
                "content or historical typesetting is claimed or reconstructed."
            ),
        ],
    }
    accountability = {
        "contract": "ocd-brenton-source-accountability-v1",
        "source_member_binding": "pass",
        "source_file_roundtrip_exact": evidence["source_file_roundtrip_exact"],
        "source_files_verified": evidence["source_files_verified"],
        "text_counts": text_counts,
        "member_ids": list(MEMBER_IDS),
        "line_marker_counts": line_counts,
        "inline_marker_counts": inline_counts,
        "merged_verse_labels": authority["merged_verse_labels"],
        "usfx_structural_census": {
            "members": comparison["member_count"],
            "chapters": comparison["chapter_count"],
            "verses": comparison["verse_count"],
        },
        "tei_sha256": _sha(tei_bytes),
        "tei_p5_valid": True,
        "candidate_status": "nonaccepted",
        "canonical_data_or_ir_changed": False,
        "work_catalog_changed": False,
        "publication_ready": False,
    }
    validation = {
        "contract": "ocd-brenton-validation-v1",
        "status": "pass",
        "tei_p5_schema": "vendored tei_all.xsd",
        "tei_p5_valid": True,
        "source_member_binding": "pass",
        "source_file_roundtrip_exact": True,
        "usfm_usfx_structural_census": "pass",
        "rendering_witness_binding": "pass",
        "accountability_status": "pass",
        "candidate_status": "nonaccepted",
    }
    unresolved = {
        "contract": "ocd-brenton-unresolved-v1",
        "items": receipt["unresolved_questions"],
        "held": ["Anderson New Testament", "tickets 22-27"],
        "candidate_status": "nonaccepted",
    }
    readme = (
        "# Brenton Septuagint ticket-21 candidate\n\n"
        "This is a deterministic, nonaccepted faithful TEI candidate from the retained "
        "eBible `eng-Brenton` USFM authority package. It preserves 53 textual books and "
        "seven paratext members, including the 1870 introduction, 1844 preface, errata, "
        "Appendix, Apocrypha overview, and Jeremiah table. It is not canonical acceptance, "
        "human textual acceptance, or publication.\n"
    ).encode("utf-8")
    outputs = {
        "README.md": readme,
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "source-receipt.json": _canonical(receipt),
        "unresolved.json": _canonical(unresolved),
        "validation.json": _canonical(validation),
        "witness-boundaries.json": _canonical(_witness_boundaries(config)),
    }
    manifest = {
        "contract": "ocd-brenton-candidate-manifest-v1",
        "candidate_id": "brenton-septuagint-eng-Brenton-ticket-21",
        "status": "nonaccepted",
        "source_revision": config["source_files_dated"],
        "source_authority_sha256": config["authority"]["archive_sha256"],
        "members": [
            {"name": name, "bytes": len(content), "sha256": _sha(content)}
            for name, content in sorted(outputs.items())
        ],
        "human_review_required": True,
        "publication_ready": False,
    }
    outputs["manifest.json"] = _canonical(manifest)
    return outputs


def write_candidate(repository_root: Path, destination: Path) -> dict[str, object]:
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"candidate destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    outputs = _build_candidate(repository_root)
    for name, content in sorted(outputs.items()):
        (destination / name).write_bytes(content)
    return {
        "destination": str(destination),
        "members": [
            {"name": name, "bytes": len(content), "sha256": _sha(content)}
            for name, content in sorted(outputs.items())
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-relative", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    relative = str(args.output_relative).replace("\\", "/")
    if not relative.startswith(OUTPUT_PREFIX) or ".." in Path(relative).parts:
        raise SystemExit(f"output must stay below {OUTPUT_PREFIX}")
    destination = resolve_repo_path(repository_root, relative)
    print(json.dumps(write_candidate(repository_root, destination), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
