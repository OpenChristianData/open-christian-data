"""Faithful direct TEI candidate for eBible's 1895 Revised Version."""

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
SOURCE_PREFIX = "source-usfm:eng-rv/"
CONFIG_RELATIVE = (
    "sources/structured-text/revised-version-with-apocrypha/config.json"
)
RAW_PREFIX = (
    "raw/clean-ready-acquisition-to-tei/master-3/21/"
    "revised-version-with-apocrypha/"
)
OUTPUT_PREFIX = (
    "reports/clean-ready-acquisition-to-tei/master-3/21/"
    "revised-version-with-apocrypha/"
)
DEFAULT_OUTPUT = OUTPUT_PREFIX + "candidate"

OT_IDS = (
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA",
    "2SA", "1KI", "2KI", "1CH", "2CH", "EZR", "NEH", "EST", "JOB",
    "PSA", "PRO", "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN",
    "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP",
    "HAG", "ZEC", "MAL",
)
APOCRYPHA_FILE_IDS = (
    "TOB", "JDT", "ESG", "WIS", "SIR", "BAR", "S3Y", "SUS", "BEL",
    "1MA", "2MA", "1ES", "MAN", "2ES",
)
NT_IDS = (
    "MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL",
    "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM",
    "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV",
)

_LINE_MARKERS = {
    "id", "h", "toc1", "toc2", "toc3", "mt1", "mt2", "mt3", "c",
    "v", "p", "nb", "m", "pc", "q1", "q2", "b", "d", "s1", "ms1",
    "ms2", "is1", "ip",
}
_PAIRED_INLINE = {"w", "add", "f", "x", "qs", "it", "bk"}
_INTERNAL_INLINE = {"fr", "ft", "fqa", "fq", "xo", "xt"}
_INLINE_TOKEN = re.compile(r"\\([A-Za-z0-9]+)(\*)?")
_WORD_PAYLOAD = re.compile(r'^(?P<word>.*)\|strong="(?P<strong>[^"]+)"$', re.DOTALL)
_SOURCE_POINTER = re.compile(
    r"^source-usfm:eng-rv/(?P<file>[^#]+)#line=(?P<line>[1-9][0-9]*)$"
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
    body = line[1:]
    parts = body.split(maxsplit=1)
    marker = parts[0]
    content = parts[1] if len(parts) == 2 else ""
    return marker, content


def _book_files(source_root: Path) -> list[Path]:
    return sorted(source_root.glob("*.usfm"))


def _book_id(path: Path) -> str:
    first_line = path.read_text(encoding="utf-8").split("\n", 1)[0]
    marker, content = _parse_source_line(first_line)
    if marker != "id" or not content:
        raise ValueError(f"USFM member does not start with an id: {path.name}")
    return content.split()[0]


def _validate_authority_root(
    source_root: Path, config: dict[str, Any]
) -> dict[str, object]:
    inventory, inventory_sha256 = _shallow_member_inventory(source_root)
    expected = config["authority"]
    if inventory_sha256 != expected["member_inventory_sha256"]:
        raise ValueError(
            "authority member inventory digest mismatch: "
            f"{inventory_sha256} != {expected['member_inventory_sha256']}"
        )
    if len(inventory) != expected["member_count"]:
        raise ValueError("authority member count mismatch")

    book_files = _book_files(source_root)
    if len(book_files) != expected["book_file_count"]:
        raise ValueError("authority book-file count mismatch")
    book_ids = [_book_id(path) for path in book_files]
    declared_ids = list(OT_IDS + APOCRYPHA_FILE_IDS + NT_IDS)
    if book_ids != declared_ids:
        raise ValueError(f"authority book order mismatch: {book_ids!r}")

    chapter_count = 0
    verse_count = 0
    line_count = 0
    terminal_newline_files = 0
    line_markers: Counter[str] = Counter()
    all_markers: Counter[str] = Counter()
    special_verse_labels: list[dict[str, str]] = []
    seen_addresses: set[tuple[str, str, str]] = set()
    current_chapter = ""
    baruch_epistle = False

    for path in book_files:
        current_book_id = _book_id(path)
        content = path.read_bytes()
        if content.startswith(b"\xef\xbb\xbf"):
            raise ValueError(f"unexpected UTF-8 BOM in {path.name}")
        if b"\r" in content:
            raise ValueError(f"non-LF line ending in {path.name}")
        if content.endswith(b"\n"):
            terminal_newline_files += 1
        text = content.decode("utf-8")
        lines = text.split("\n")
        line_count += len(lines)
        for line_number, line in enumerate(lines, start=1):
            marker, marker_content = _parse_source_line(line)
            if marker not in _LINE_MARKERS:
                raise ValueError(
                    f"unsupported line marker {marker!r} in {path.name}:{line_number}"
                )
            line_markers[marker] += 1
            all_markers.update(_INLINE_TOKEN.findall(line))
            if marker == "c":
                chapter_count += 1
                current_chapter = marker_content.split()[0]
            elif marker == "v":
                verse_count += 1
                verse_label = marker_content.split(maxsplit=1)[0]
                address = (current_book_id, current_chapter, verse_label)
                if address in seen_addresses:
                    raise ValueError(f"duplicate source verse address: {address!r}")
                seen_addresses.add(address)
                if not verse_label.isdigit():
                    special_verse_labels.append(
                        {
                            "book": address[0],
                            "chapter": current_chapter,
                            "verse": verse_label,
                        }
                    )
            if (
                path.name == "47-BAReng-rv.usfm"
                and current_chapter == "6"
                and marker == "ms1"
                and marker_content.strip() == "THE EPISTLE OF JEREMY."
            ):
                baruch_epistle = True

    paired_counts: dict[str, int] = {}
    flat_marker_counts: dict[str, int] = Counter()
    for (marker, closing), count in all_markers.items():
        key = marker + ("*" if closing else "")
        flat_marker_counts[key] += count
    for marker in sorted(_PAIRED_INLINE):
        opening = flat_marker_counts[marker]
        closing = flat_marker_counts[f"{marker}*"]
        if opening != closing:
            raise ValueError(
                f"unbalanced inline marker {marker}: {opening} != {closing}"
            )
        paired_counts[marker] = opening
    unknown_inline = set(flat_marker_counts) - _LINE_MARKERS - _INTERNAL_INLINE - {
        marker for name in _PAIRED_INLINE for marker in (name, f"{name}*")
    }
    if unknown_inline:
        raise ValueError(f"unsupported inline markers: {sorted(unknown_inline)}")
    if not baruch_epistle:
        raise ValueError("Baruch chapter 6 Epistle of Jeremy boundary is missing")

    return {
        "member_count": len(inventory),
        "book_file_count": len(book_files),
        "book_ids": book_ids,
        "member_inventory_sha256": inventory_sha256,
        "chapter_count": chapter_count,
        "verse_count": verse_count,
        "source_line_count": line_count,
        "terminal_newline_files": terminal_newline_files,
        "line_marker_counts": dict(sorted(line_markers.items())),
        "inline_marker_counts": dict(sorted(flat_marker_counts.items())),
        "paired_inline_counts": paired_counts,
        "special_verse_labels": special_verse_labels,
        "baruch_epistle_of_jeremy": baruch_epistle,
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
    authority_archive = resolve_repo_path(repository_root, config["source_file"])
    comparison_archive = resolve_repo_path(
        repository_root, config["comparison_source_file"]
    )
    _validate_file_binding(
        authority_archive,
        {
            "bytes": config["authority"]["archive_bytes"],
            "sha256": config["authority"]["archive_sha256"],
        },
        "authority archive",
    )
    _validate_file_binding(
        comparison_archive,
        {
            "bytes": config["comparison_carrier"]["archive_bytes"],
            "sha256": config["comparison_carrier"]["archive_sha256"],
        },
        "comparison archive",
    )
    for witness in config["witnesses"]:
        _validate_file_binding(
            resolve_repo_path(repository_root, witness["path"]),
            witness,
            str(witness["role"]),
        )

    raw_root = resolve_repo_path(repository_root, RAW_PREFIX.rstrip("/"))
    source_page = raw_root / "metadata" / "official-source-page.html"
    details_page = raw_root / "metadata" / "official-details-page.html"
    required_page_tokens = (
        b"eng-rv_usfm.zip",
        b"RevisedVersionHolyBible1895.pdf",
        b"RevisedVersionHolyBible1913.pdf",
        b"TOB_RV.pdf",
        b"ESG_RV.pdf",
    )
    source_page_bytes = source_page.read_bytes()
    missing_tokens = [
        token.decode("ascii")
        for token in required_page_tokens
        if token not in source_page_bytes
    ]
    if missing_tokens:
        raise ValueError(f"official source page is missing links: {missing_tokens}")
    if b"public domain" not in details_page.read_bytes().lower():
        raise ValueError("official details page lacks the public-domain statement")
    header_files = sorted((raw_root / "http-headers").glob("*.txt"))
    if len(header_files) != 8:
        raise ValueError("retained HTTP-header count mismatch")
    inventory, inventory_sha256 = _member_inventory(raw_root)
    return {
        "raw_root": str(raw_root),
        "retained_file_count": len(inventory),
        "retained_file_inventory_sha256": inventory_sha256,
        "retained_files": inventory,
        "http_header_files": len(header_files),
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

    book_ids: list[str] = []
    chapter_count = 0
    verse_count = 0
    source = root / "eng-rv_usfx.xml"
    for _, element in etree.iterparse(str(source), events=("end",), huge_tree=True):
        if element.tag == "book":
            book_id = element.get("id")
            if book_id is None:
                raise ValueError("USFX book lacks id")
            book_ids.append(book_id)
        elif element.tag == "c":
            chapter_count += 1
        elif element.tag == "v":
            verse_count += 1
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
    declared = list(OT_IDS + APOCRYPHA_FILE_IDS + NT_IDS)
    if book_ids != declared:
        raise ValueError("comparison carrier book order mismatch")
    return {
        "book_count": len(book_ids),
        "chapter_count": chapter_count,
        "verse_count": verse_count,
        "book_ids": book_ids,
        "member_count": len(inventory),
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
    if marker == "w":
        return etree.SubElement(parent, _q("w"))
    if marker == "add":
        return etree.SubElement(parent, _q("supplied"), reason="source-marked")
    if marker == "f":
        return etree.SubElement(parent, _q("note"), type="footnote")
    if marker == "x":
        return etree.SubElement(parent, _q("note"), type="cross-reference")
    if marker == "qs":
        return etree.SubElement(parent, _q("seg"), type="usfm-qs")
    if marker == "it":
        return etree.SubElement(parent, _q("hi"), rend="italic")
    if marker == "bk":
        return etree.SubElement(parent, _q("title"), type="book-name")
    raise ValueError(f"unsupported paired inline marker: {marker}")


def _normalize_closed_inline(marker: str, element: etree._Element) -> None:
    if marker == "w":
        payload = element.text or ""
        match = _WORD_PAYLOAD.fullmatch(payload)
        if match is None:
            raise ValueError(f"unsupported USFM word payload: {payload!r}")
        element.text = match.group("word")
        element.set("n", match.group("strong"))
    elif marker in {"f", "x"} and (element.text or "").strip() == "+":
        element.text = None


def _append_inline(parent: etree._Element, value: str) -> None:
    stack: list[tuple[str, etree._Element]] = [("root", parent)]
    position = 0
    for token in _INLINE_TOKEN.finditer(value):
        _append_text(stack[-1][1], value[position : token.start()])
        marker = token.group(1)
        closing = token.group(2) == "*"
        if closing:
            matching = next(
                (index for index in range(len(stack) - 1, 0, -1) if stack[index][0] == marker),
                None,
            )
            if matching is None:
                raise ValueError(f"unmatched closing inline marker: {marker}")
            _normalize_closed_inline(marker, stack[matching][1])
            stack = stack[:matching]
        elif marker in _PAIRED_INLINE:
            child = _inline_element(stack[-1][1], marker)
            stack.append((marker, child))
        elif marker in _INTERNAL_INLINE:
            container = next(
                (
                    index
                    for index in range(len(stack) - 1, 0, -1)
                    if stack[index][0] in {"f", "x"}
                ),
                None,
            )
            if container is None:
                raise ValueError(f"inline submarker {marker} is outside a note")
            stack = stack[: container + 1]
            child = etree.SubElement(
                stack[-1][1], _q("seg"), type=f"usfm-{marker}"
            )
            stack.append((marker, child))
        else:
            raise ValueError(f"unsupported inline marker: {marker}")
        position = token.end()
    _append_text(stack[-1][1], value[position:])
    unclosed = [marker for marker, _ in stack[1:] if marker in _PAIRED_INLINE]
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
    node = etree.SubElement(
        parent,
        _q(tag),
        corresp=pointer,
        **attributes,
    )
    _add_raw_note(node, raw_line)
    _append_inline(node, content)
    return node


def _make_header(root: etree._Element, config: dict[str, Any]) -> None:
    header = etree.SubElement(root, _q("teiHeader"))
    file_desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = config["title"]
    for contributor in config["contributors"]:
        statement = etree.SubElement(title_stmt, _q("respStmt"))
        etree.SubElement(statement, _q("resp")).text = "Revision"
        etree.SubElement(statement, _q("name")).text = contributor
    publication = etree.SubElement(file_desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("publisher")).text = (
        "Nonaccepted ticket-21 source-faithful candidate; not publication."
    )
    availability = etree.SubElement(publication, _q("availability"), status="free")
    etree.SubElement(
        availability, _q("licence"), target=config["source_url"]
    ).text = "The retained eBible source identifies this edition as public domain."
    source_desc = etree.SubElement(file_desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = config["source_edition"]
    etree.SubElement(bibl, _q("ref"), target=config["source_url"]).text = (
        "Official eBible eng-rv source page"
    )

    encoding = etree.SubElement(header, _q("encodingDesc"))
    etree.SubElement(encoding, _q("p")).text = (
        "Every retained USFM line is preserved exactly in a source-usfm-raw note "
        "and projected into source-defined book, chapter, verse, note, cross-reference, "
        "supplied-text, poetry, and inline-word structures."
    )
    etree.SubElement(encoding, _q("p")).text = (
        "The 1895 and 1913 scans and the Tobit and Greek Esther replacement scans "
        "are identity and completeness witnesses only; print-only prelims are not "
        "silently fabricated into the structured text."
    )
    profile = etree.SubElement(header, _q("profileDesc"))
    language_usage = etree.SubElement(profile, _q("langUsage"))
    etree.SubElement(language_usage, _q("language"), ident="en").text = "English"
    revision = etree.SubElement(header, _q("revisionDesc"))
    etree.SubElement(
        revision, _q("change"), when=config["retrieved_at_utc"][:10]
    ).text = "Generated deterministic nonaccepted TEI candidate."


def _testament_parent(body: etree._Element, book_id: str) -> etree._Element:
    testament_type = (
        "old-testament"
        if book_id in OT_IDS
        else "apocrypha"
        if book_id in APOCRYPHA_FILE_IDS
        else "new-testament"
    )
    matches = [
        child
        for child in body
        if child.tag == _q("div") and child.get("type") == testament_type
    ]
    if len(matches) != 1:
        raise ValueError(f"missing testament container: {testament_type}")
    return matches[0]


def _render_book(body: etree._Element, path: Path) -> None:
    lines = path.read_text(encoding="utf-8").split("\n")
    book_id = _book_id(path)
    testament = _testament_parent(body, book_id)
    book: etree._Element | None = None
    chapter: etree._Element | None = None
    current_chapter = ""
    for line_number, raw_line in enumerate(lines, start=1):
        marker, content = _parse_source_line(raw_line)
        pointer = _source_pointer(path, line_number)
        if marker == "id":
            book = etree.SubElement(
                testament,
                _q("div"),
                type="book",
                n=book_id,
                corresp=pointer,
            )
            book.set(XML_ID, f"rv-{book_id}")
            _add_raw_note(book, raw_line)
            _add_line_element(
                book,
                "ab",
                "id-label",
                content,
                raw_line,
                pointer + ":label",
                type="source-id-label",
            )
            continue
        if book is None:
            raise ValueError(f"content precedes id in {path.name}:{line_number}")
        container = chapter if chapter is not None else book
        if marker == "c":
            current_chapter = content.split()[0]
            chapter = etree.SubElement(
                book,
                _q("div"),
                type="chapter",
                n=current_chapter,
                corresp=pointer,
            )
            chapter.set(XML_ID, f"rv-{book_id}-{current_chapter}")
            if book_id == "BAR" and current_chapter == "6":
                chapter.set("ana", "#epistle-of-jeremy")
            _add_raw_note(chapter, raw_line)
        elif marker == "v":
            if chapter is None:
                raise ValueError(f"verse precedes chapter in {path.name}:{line_number}")
            verse_parts = content.split(maxsplit=1)
            verse_label = verse_parts[0]
            verse_text = verse_parts[1] if len(verse_parts) == 2 else ""
            _add_line_element(
                chapter,
                "ab",
                marker,
                verse_text,
                raw_line,
                pointer,
                type="verse",
                n=verse_label,
            ).set(XML_ID, f"rv-{book_id}-{current_chapter}-{verse_label}")
        elif marker in {"h", "toc1", "toc2", "toc3", "mt1", "mt2", "mt3"}:
            _add_line_element(
                container,
                "ab",
                marker,
                content,
                raw_line,
                pointer,
                type=f"usfm-{marker}",
            )
        elif marker in {"s1", "ms1", "ms2", "is1", "d"}:
            node = _add_line_element(
                container,
                "ab",
                marker,
                content,
                raw_line,
                pointer,
                type=f"usfm-{marker}",
            )
            if (
                book_id == "BAR"
                and current_chapter == "6"
                and marker == "ms1"
                and content.strip() == "THE EPISTLE OF JEREMY."
            ):
                node.set("ana", "#epistle-of-jeremy")
        elif marker in {"q1", "q2"}:
            _add_line_element(
                container,
                "ab",
                marker,
                content,
                raw_line,
                pointer,
                type="poetry-line",
                n=marker,
            )
        else:
            line_type = {
                "p": "paragraph-break",
                "nb": "continuation-paragraph",
                "m": "flush-paragraph",
                "pc": "centered-paragraph",
                "b": "stanza-break",
                "ip": "introduction-paragraph",
            }[marker]
            _add_line_element(
                container,
                "ab",
                marker,
                content,
                raw_line,
                pointer,
                type=line_type,
                n=marker,
            )


def _verify_source_files(tei_bytes: bytes, source_root: Path) -> dict[str, object]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(tei_bytes, parser=parser)
    reconstructed: dict[str, dict[int, str]] = defaultdict(dict)
    for node in root.iter():
        pointer = node.get("corresp")
        if pointer is None or not pointer.startswith(SOURCE_PREFIX):
            continue
        match = _SOURCE_POINTER.fullmatch(pointer)
        if match is None:
            continue
        raw_notes = [
            child
            for child in node
            if child.tag == _q("note") and child.get("type") == "source-usfm-raw"
        ]
        if len(raw_notes) != 1 or raw_notes[0].text is None:
            raise ValueError(f"source pointer lacks one exact raw note: {pointer}")
        file_name = match.group("file")
        line_number = int(match.group("line"))
        if line_number in reconstructed[file_name]:
            raise ValueError(f"duplicate source pointer: {pointer}")
        reconstructed[file_name][line_number] = raw_notes[0].text

    verified_lines = 0
    book_files = _book_files(source_root)
    if set(reconstructed) != {path.name for path in book_files}:
        raise ValueError("TEI source-file coverage mismatch")
    for path in book_files:
        expected = path.read_text(encoding="utf-8")
        lines = reconstructed[path.name]
        expected_numbers = list(range(1, len(expected.split("\n")) + 1))
        if sorted(lines) != expected_numbers:
            raise ValueError(f"TEI source-line coverage mismatch: {path.name}")
        reopened = "\n".join(lines[number] for number in expected_numbers)
        if reopened != expected:
            raise ValueError(f"TEI source-file roundtrip mismatch: {path.name}")
        verified_lines += len(lines)
    return {
        "source_file_roundtrip_exact": True,
        "source_files_verified": len(book_files),
        "source_lines_verified": verified_lines,
    }


def _tei(
    repository_root: Path, config: dict[str, Any]
) -> tuple[bytes, dict[str, object]]:
    source_root = resolve_repo_path(repository_root, config["source_root"])
    authority = _validate_authority_root(source_root, config)
    comparison = _validate_comparison_carrier(repository_root, config)
    if (
        comparison["book_count"] != authority["book_file_count"]
        or comparison["chapter_count"] != authority["chapter_count"]
        or comparison["verse_count"] != authority["verse_count"]
    ):
        raise ValueError("USFM and USFX structural censuses differ")

    root = etree.Element(_q("TEI"), nsmap={None: TEI_NS})
    root.set(XML_ID, "revised-version-with-apocrypha-eng-rv")
    root.set(XML_LANG, "en")
    root.set("ana", "#nonaccepted-candidate")
    _make_header(root, config)
    text = etree.SubElement(root, _q("text"))
    body = etree.SubElement(text, _q("body"))
    for testament_type, label in (
        ("old-testament", "Old Testament"),
        ("apocrypha", "Apocrypha / Deuterocanon"),
        ("new-testament", "New Testament"),
    ):
        testament = etree.SubElement(body, _q("div"), type=testament_type)
        testament.set(XML_ID, f"rv-{testament_type}")
        etree.SubElement(testament, _q("head")).text = label
    for path in _book_files(source_root):
        _render_book(body, path)

    tei_bytes = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    parsed = etree.fromstring(tei_bytes, parser=parser)
    compiled_schema().assertValid(etree.ElementTree(parsed))
    roundtrip = _verify_source_files(tei_bytes, source_root)
    return tei_bytes, {
        "authority": authority,
        "comparison": comparison,
        **roundtrip,
    }


def _witness_boundaries(config: dict[str, Any]) -> dict[str, object]:
    return {
        "contract": "ocd-revised-version-witness-boundaries-v1",
        "structured_authority": "eBible eng-rv USFM package",
        "comparison_carrier": "eBible eng-rv USFX package",
        "whole_bible_witnesses": {
            "RevisedVersionHolyBible1895.pdf": (
                "Exact 1895 edition witness; identity and bounded visual evidence only"
            ),
            "RevisedVersionHolyBible1913.pdf": (
                "Later whole-Bible witness with revised marginal references; evidence only"
            ),
        },
        "replacement_witnesses": {
            "TOB_RV.pdf": (
                "Tobit scan retained for whole-Bible scan drop-outs; evidence only"
            ),
            "ESG_RV.pdf": (
                "Greek Esther scan retained for whole-Bible scan drop-outs; evidence only"
            ),
        },
        "apocrypha_accounting": {
            "file_members": len(APOCRYPHA_FILE_IDS),
            "textual_units": len(APOCRYPHA_FILE_IDS) + 1,
            "embedded_unit": {
                "source_member": "47-BAReng-rv.usfm",
                "chapter": "6",
                "title": "THE EPISTLE OF JEREMY.",
            },
        },
        "print_only_prelims_1895": [
            "title leaf",
            "names and order of the Old Testament, Apocrypha, and New Testament",
            "preface",
        ],
        "print_only_prelims_1913": [
            "title leaf for the edition with revised marginal references",
            "preface to the edition with marginal references",
            "marginal-reference notation key",
            "Revisers' prefaces",
        ],
        "print_prelims_projected_to_tei": False,
        "replacement_scans_projected_to_tei": False,
        "source_edition": config["source_edition"],
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
    inline = authority["inline_marker_counts"]
    line_markers = authority["line_marker_counts"]

    receipt = {
        "contract": "ocd-revised-version-source-receipt-v1",
        "resource_id": config["resource_id"],
        "title": config["title"],
        "source_url": config["source_url"],
        "source_download_url": config["source_download_url"],
        "retrieved_at_utc": config["retrieved_at_utc"],
        "source_updated_at_utc": config["source_updated_at_utc"],
        "source_edition": config["source_edition"],
        "rights": {
            "status": "public-domain",
            "evidence": (
                "The retained official eBible details page states that the work is in "
                "the public domain and may be copied and used freely."
            ),
        },
        "authority": config["authority"],
        "comparison_carrier": config["comparison_carrier"],
        "witnesses": config["witnesses"],
        "retained_file_count": acquisition["retained_file_count"],
        "retained_file_inventory_sha256": acquisition[
            "retained_file_inventory_sha256"
        ],
        "retained_files": acquisition["retained_files"],
        "completeness_spot_check": {
            "opening": "02-GENeng-rv.usfm Genesis title and 1:1",
            "middle_transition": "40-MALeng-rv.usfm ending to 41-TOBeng-rv.usfm opening",
            "embedded_apocrypha_unit": (
                "47-BAReng-rv.usfm chapter 6, THE EPISTLE OF JEREMY"
            ),
            "ending": "96-REVeng-rv.usfm Revelation 22:21",
            "unusual": [
                "Strong-linked words",
                "supplied text",
                "footnotes",
                "cross-references",
                "poetry and stanza breaks",
                "source-merged Sirach verse labels",
            ],
        },
        "unresolved_questions": [
            (
                "The structured source is an eBible digital edition dated 2026-08-08; "
                "human review must decide whether its edition identity and replacement-"
                "witness lineage are sufficient for catalog acceptance."
            ),
            (
                "The 1895 print title, order tables, and preface are not represented in "
                "the structured source and are retained as print-only witness evidence."
            ),
            (
                "The 1913 scan is a later revised-marginal-references witness and is not "
                "treated as the transformation authority for the 1895 expression."
            ),
            (
                "The official page identifies separate Tobit and Greek Esther scans as "
                "compensation for whole-Bible scan drop-outs; they remain evidence only."
            ),
        ],
    }
    text_counts = {
        "old_testament_books": len(OT_IDS),
        "apocrypha_file_members": len(APOCRYPHA_FILE_IDS),
        "apocrypha_units": len(APOCRYPHA_FILE_IDS) + 1,
        "new_testament_books": len(NT_IDS),
        "chapters": authority["chapter_count"],
        "verses": authority["verse_count"],
        "source_lines": authority["source_line_count"],
        "word_links": inline["w"],
        "supplied_text_spans": inline["add"],
        "footnotes": inline["f"],
        "cross_references": inline["x"],
        "poetry_lines": line_markers["q1"] + line_markers["q2"],
    }
    accountability = {
        "contract": "ocd-revised-version-source-accountability-v1",
        "source_member_binding": "pass",
        "source_file_roundtrip_exact": evidence["source_file_roundtrip_exact"],
        "source_files_verified": evidence["source_files_verified"],
        "text_counts": text_counts,
        "line_marker_counts": line_markers,
        "inline_marker_counts": inline,
        "special_verse_labels": authority["special_verse_labels"],
        "usfx_structural_census": {
            "books": comparison["book_count"],
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
    boundaries = _witness_boundaries(config)
    unresolved = {
        "contract": "ocd-revised-version-unresolved-v1",
        "items": receipt["unresolved_questions"],
        "held": [
            "Brenton English Septuagint",
            "Anderson New Testament",
            "tickets 22-27",
        ],
        "candidate_status": "nonaccepted",
    }
    validation = {
        "contract": "ocd-revised-version-validation-v1",
        "status": "pass",
        "tei_p5_schema": "vendored tei_all.xsd",
        "tei_p5_valid": True,
        "source_member_binding": "pass",
        "source_file_roundtrip_exact": True,
        "usfm_usfx_structural_census": "pass",
        "witness_binding": "pass",
        "accountability_status": "pass",
        "candidate_status": "nonaccepted",
    }
    readme = (
        "# Revised Version with Apocrypha ticket-21 candidate\n\n"
        "This is a deterministic, nonaccepted faithful TEI candidate from the "
        "retained eBible `eng-rv` USFM package.\n\n"
        "It preserves 39 Old Testament books, fifteen Apocrypha/Deuterocanon "
        "textual units (fourteen source files plus the Epistle of Jeremy inside "
        "Baruch 6), and 27 New Testament books. The 1895/1913 whole-Bible scans "
        "and Tobit/Greek-Esther replacement scans are evidence only. This packet "
        "is not canonical data, WorkCatalog acceptance, human textual acceptance, "
        "or publication.\n"
    ).encode("utf-8")
    outputs = {
        "README.md": readme,
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "source-receipt.json": _canonical(receipt),
        "unresolved.json": _canonical(unresolved),
        "validation.json": _canonical(validation),
        "witness-boundaries.json": _canonical(boundaries),
    }
    manifest = {
        "contract": "ocd-revised-version-candidate-manifest-v1",
        "candidate_id": "revised-version-with-apocrypha-eng-rv-ticket-21",
        "status": "nonaccepted",
        "source_revision": config["source_updated_at_utc"],
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


def write_candidate(
    repository_root: Path, destination: Path
) -> dict[str, object]:
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
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output-relative", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    relative = str(args.output_relative).replace("\\", "/")
    if not relative.startswith(OUTPUT_PREFIX) or ".." in Path(relative).parts:
        raise SystemExit(f"output must stay below {OUTPUT_PREFIX}")
    destination = resolve_repo_path(repository_root, relative)
    print(
        json.dumps(
            write_candidate(repository_root, destination),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
