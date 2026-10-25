"""Independent retained-byte oracle for the two PG#53527 Charnock routes."""

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

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-charnock-pg53527-independent-native-partition-oracle"
ORACLE_VERSION = "2"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NS = {"tei": TEI}
VOLUMES = {
    "charnock-existence-attributes-vol-1": (1, 33, 30307),
    "charnock-existence-attributes-vol-2": (2, 30308, 56434),
}
APPARATUS = (56435, 62447)
PAGE_RE = re.compile(r"\{([ab]\d+)\}")
NOTE_REF_RE = re.compile(r"\[(\d{1,4})\]")
NOTE_LINE_RE = re.compile(r"^\s*(\d+)\s+–\s?(.*)$")
DISCOURSE_RE = re.compile(r"DISCOURSE\s+([IVXLCDM]+)\.")
CANDIDATE_KEYS = {
    "contract",
    "status",
    "source_id",
    "source_manifest",
    "converter",
    "package_schema",
    "members",
}
CANDIDATE_MEMBER_NAMES = [
    "README.source.md",
    "content.tei.xml",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
]
ACCOUNTABILITY_KEYS = {
    "contract",
    "work_id",
    "source_member",
    "body_line_range",
    "shared_apparatus_line_range",
    "physical_line_count",
    "represented_line_count",
    "evidence_only_line_count",
    "omitted_line_count",
    "duplicate_line_count",
    "source_inventory_sha256",
    "required_counts",
    "lines",
}
ACCOUNTABILITY_LINE_KEYS = {
    "line",
    "byte_start",
    "byte_end",
    "terminator",
    "text",
    "record_sha256",
    "disposition",
    "reason",
    "tei_selector",
}
PROVENANCE_KEYS = {
    "contract",
    "status",
    "publication",
    "work_id",
    "source_sha256",
    "source_manifest_sha256",
    "producer_import_closure",
    "producer_import_closure_sha256",
    "runtime",
    "shared_apparatus_disposition",
}
SHARED_DISPOSITION = (
    "The retained digital witness is two volumes in one; its combined index, "
    "footnotes, and transcriber notes are represented in both volume candidates "
    "as explicitly shared edition apparatus, not relabeled volume body."
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
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Charnock oracle authority {name} cardinality mismatch")
    return matches[0]


def _scan(content: bytes) -> list[dict[str, object]]:
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
        raise ValueError("Charnock oracle source byte accounting failed")
    return rows


def _expected_line_type(number: int, text: str) -> str:
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


def _line_id(prefix: str, number: int) -> str:
    return f"{prefix}-line-{number:05d}"


def _note_id(prefix: str, number: int) -> str:
    return f"{prefix}-note-{number}"


def _visible(element: etree._Element) -> str:
    """Read the native TEI projection without consulting the producer."""

    parts = [element.text or ""]
    for child in element:
        name = etree.QName(child).localname
        if name in {"milestone", "pb"}:
            pass
        elif name == "lb" and child.get("break") != "no":
            parts.append("\n")
        else:
            parts.append(_visible(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _source_visible(rows: list[dict[str, object]]) -> str:
    value = " ".join(str(row["text"]) for row in rows)
    value = PAGE_RE.sub("", value).replace("_", "")
    return " ".join(value.split())


def _expected_italic_spans(rows: list[dict[str, object]]) -> list[str]:
    """Derive the source's paired underscore spans without producer helpers."""

    value = " ".join(str(row["text"]) for row in rows)
    positions = [index for index, character in enumerate(value) if character == "_"]
    if len(positions) % 2:
        raise ValueError("Charnock source italic marker count is unpaired")
    return [
        " ".join(PAGE_RE.sub("", value[left + 1 : right]).split())
        for left, right in zip(positions[::2], positions[1::2], strict=True)
    ]


def _actual_discourse_starts(
    rows: list[dict[str, object]], *, start: int, end: int
) -> list[tuple[int, str]]:
    """Return source-defined discourse starts after the contents boundary.

    The witness prints a contents list before the body.  Its Roman-numeral
    headings are source lines, but they are not body discourse ancestors.  The
    final front-matter heading (the life/contents heading) is a stable source
    boundary for the selected volume; actual body headings follow it.
    """

    selected = rows[start - 1 : end]
    front_boundary = -1
    for index, row in enumerate(selected):
        value = _source_visible([row]).upper()
        if "LIFE AND CHARACTER" in value or "OF TEXTS." in value:
            front_boundary = index
    result: list[tuple[int, str]] = []
    for index, row in enumerate(selected):
        if index <= front_boundary:
            continue
        value = str(row["text"])
        if not PAGE_RE.search(value):
            continue
        match = DISCOURSE_RE.search(PAGE_RE.sub("", value))
        if match is not None:
            result.append((int(row["line"]), match.group(1)))
    return result


def _line_pointers(element: etree._Element) -> list[str]:
    pointers: list[str] = []
    for current in element.iter():
        for pointer in (current.get("corresp") or "").split():
            if pointer.startswith("#"):
                pointers.append(pointer[1:])
    return pointers


def _source_heading(text: str) -> bool:
    value = PAGE_RE.sub("", text).strip()
    return bool(value) and len(value) < 120 and value.isupper()


def _expected_volume_paragraphs(
    rows: list[dict[str, object]], *, start: int, end: int, prefix: str
) -> list[list[str]]:
    """Derive source paragraph line intervals from physical blank/head lines."""

    starts = [line for line, _numeral in _actual_discourse_starts(rows, start=start, end=end)]
    boundaries = [start, *starts, end + 1]
    expected: list[list[str]] = []
    for left, right in zip(boundaries, boundaries[1:]):
        pending: list[str] = []
        for row in rows[left - 1 : right - 1]:
            value = str(row["text"])
            if not value or _source_heading(value):
                if pending:
                    expected.append(pending)
                    pending = []
                continue
            pending.append(_line_id(prefix, int(row["line"])))
        if pending:
            expected.append(pending)
    return expected


def _page_expectations(
    rows: list[dict[str, object]], prefix: str
) -> list[tuple[str, str]]:
    expected: list[tuple[str, str]] = []
    for row in rows:
        for match in PAGE_RE.finditer(str(row["text"])):
            expected.append(
                (match.group(1), _line_id(prefix, int(row["line"])))
            )
    return expected


def _footnote_intervals(
    apparatus: list[dict[str, object]],
) -> list[tuple[int, list[dict[str, object]]]]:
    foot_rows = [
        row
        for row in apparatus
        if 59664 <= int(row["line"]) < 61842
    ]
    starts = [
        index
        for index, row in enumerate(foot_rows)
        if NOTE_LINE_RE.match(str(row["text"])) is not None
    ]
    intervals: list[tuple[int, list[dict[str, object]]]] = []
    for ordinal, index in enumerate(starts):
        stop = starts[ordinal + 1] if ordinal + 1 < len(starts) else len(foot_rows)
        chunk = [row for row in foot_rows[index:stop] if str(row["text"])]
        match = NOTE_LINE_RE.match(str(chunk[0]["text"]))
        if match is None:
            raise ValueError("Charnock source footnote interval start drifted")
        intervals.append((int(match.group(1)), chunk))
    return intervals


def _verify_native_projection(
    document: etree._Element,
    rows: list[dict[str, object]],
    apparatus: list[dict[str, object]],
    *,
    volume: int,
    start: int,
    end: int,
) -> None:
    """Validate native prose, structure, line carriers, and note links independently."""

    volume_divs = document.xpath("//tei:div[@type='volume-body']", namespaces=NS)
    shared_divs = document.xpath(
        "//tei:div[@type='shared-apparatus']", namespaces=NS
    )
    if len(volume_divs) != 1 or len(shared_divs) != 1:
        raise ValueError("Charnock native volume or shared boundary drifted")
    volume_div = volume_divs[0]
    shared_div = shared_divs[0]
    if dict(volume_div.attrib) != {"type": "volume-body", "n": str(volume)} or dict(
        shared_div.attrib
    ) != {"type": "shared-apparatus"}:
        raise ValueError("Charnock native volume identity boundary drifted")
    volume_readable = volume_div.xpath(
        "./tei:div[@type='readable-transcription']", namespaces=NS
    )
    shared_readable = shared_div.xpath(
        "./tei:div[@type='readable-transcription']", namespaces=NS
    )
    if len(volume_readable) != 1 or len(shared_readable) != 1:
        raise ValueError("Charnock readable transcription boundary drifted")
    if _visible(volume_readable[0]).replace("\n", " ").split() != _source_visible(
        rows[start - 1 : end]
    ).split():
        raise ValueError("Charnock readable volume wording or order drifted")
    if _visible(shared_readable[0]).replace("\n", " ").split() != _source_visible(
        apparatus
    ).split():
        raise ValueError("Charnock readable shared apparatus wording or order drifted")

    for label, readable, selected_rows in (
        ("volume", volume_readable[0], rows[start - 1 : end]),
        ("shared apparatus", shared_readable[0], apparatus),
    ):
        expected_italic = _expected_italic_spans(selected_rows)
        observed_nodes = readable.xpath(".//tei:hi", namespaces=NS)
        if any(node.get("rend") != "italic" for node in observed_nodes):
            raise ValueError(
                f"Charnock source-derived {label} italic rendition drifted"
            )
        observed_italic = [
            " ".join(_visible(node).replace("\n", " ").split())
            for node in observed_nodes
        ]
        if observed_italic != expected_italic:
            raise ValueError(
                f"Charnock source-derived {label} italic span sequence drifted"
            )

    expected_line_ids = {
        *(_line_id(f"charnock-v{volume}", number) for number in range(start, end + 1)),
        *(
            _line_id(f"charnock-shared-v{volume}", number)
            for number in range(APPARATUS[0], APPARATUS[1] + 1)
        ),
    }
    pointers: dict[str, list[etree._Element]] = {}
    for readable in (*volume_readable, *shared_readable):
        for element in readable.iter():
            for pointer in (element.get("corresp") or "").split():
                if pointer.startswith("#"):
                    pointers.setdefault(pointer[1:], []).append(element)
    if set(pointers) != expected_line_ids or any(
        len(items) != 1 for items in pointers.values()
    ):
        missing = sorted(expected_line_ids - set(pointers))
        invented = sorted(set(pointers) - expected_line_ids)
        duplicated = sorted(
            key for key, items in pointers.items() if len(items) != 1
        )
        raise ValueError(
            "Charnock native line carrier census drifted: "
            f"missing={missing[:3]!r}, invented={invented[:3]!r}, "
            f"duplicated={duplicated[:3]!r}"
        )

    expected_discourse_starts = _actual_discourse_starts(
        rows, start=start, end=end
    )
    discourses = volume_readable[0].xpath(
        ".//tei:div[@type='discourse']", namespaces=NS
    )
    observed_discourses = [str(item.get("n")) for item in discourses]
    expected_numerals = [numeral for _line, numeral in expected_discourse_starts]
    if observed_discourses != expected_numerals or len(discourses) != len(
        expected_discourse_starts
    ) or not all(
        item.xpath("./tei:ab[@type='source-heading']", namespaces=NS)
        for item in discourses
    ):
        raise ValueError("Charnock discourse structure or heading carriers drifted")
    if not volume_readable[0].xpath(
        ".//tei:p", namespaces=NS
    ) or not shared_readable[0].xpath(".//tei:div[@type='index']", namespaces=NS):
        raise ValueError("Charnock readable meaningful structure is incomplete")

    observed_pages = [
        (str(marker.get("n")), (marker.get("corresp") or "")[1:])
        for marker in volume_readable[0].xpath(
            ".//tei:pb", namespaces=NS
        )
    ]
    expected_pages = _page_expectations(
        rows[start - 1 : end], f"charnock-v{volume}"
    )
    if observed_pages != expected_pages:
        raise ValueError("Charnock body page milestone value or location drifted")
    observed_shared_pages = [
        (str(marker.get("n")), (marker.get("corresp") or "")[1:])
        for marker in shared_readable[0].xpath(
            ".//tei:pb", namespaces=NS
        )
    ]
    expected_shared_pages = _page_expectations(
        apparatus, f"charnock-shared-v{volume}"
    )
    if observed_shared_pages != expected_shared_pages:
        raise ValueError("Charnock shared page milestone value or location drifted")

    for label, readable, selected, prefix in (
        ("volume", volume_readable[0], rows[start - 1 : end], f"charnock-v{volume}"),
        ("shared", shared_readable[0], apparatus, f"charnock-shared-v{volume}"),
    ):
        page_nodes = readable.xpath(".//tei:pb", namespaces=NS)
        if any(set(node.attrib) != {"n", "corresp"} for node in page_nodes):
            raise ValueError(f"Charnock {label} page carrier attributes drifted")
        blank_nodes = readable.xpath(".//tei:lb[@type='source-blank-line']", namespaces=NS)
        observed_blanks = [(node.get("n"), node.get("corresp")) for node in blank_nodes]
        expected_blanks = [(str(row["line"]), f"#{_line_id(prefix, int(row['line']))}")
                           for row in selected if str(row["text"]) == ""]
        if (observed_blanks != expected_blanks or
                any(set(node.attrib) != {"type", "n", "corresp"} for node in blank_nodes)):
            raise ValueError(f"Charnock {label} blank-line carrier order or attributes drifted")
        if readable.xpath(".//tei:milestone", namespaces=NS):
            raise ValueError(f"Charnock {label} legacy milestone remains")

    # Every source-defined discourse interval must remain under its own native
    # discourse ancestor.  A flat carrier or a moved paragraph can preserve
    # words and global line coverage while violating this ownership contract.
    discourse_boundaries = [line for line, _numeral in expected_discourse_starts]
    prefix = f"charnock-v{volume}"
    for index, (discourse, (line, numeral)) in enumerate(
        zip(discourses, expected_discourse_starts, strict=True)
    ):
        stop = (
            discourse_boundaries[index + 1] - 1
            if index + 1 < len(discourse_boundaries)
            else end
        )
        expected_interval = {
            _line_id(prefix, number) for number in range(line, stop + 1)
        }
        observed_interval = _line_pointers(discourse)
        if (
            discourse.get("n") != numeral
            or discourse.get(XML_ID) != f"{prefix}-discourse-{numeral}"
            or set(observed_interval) != expected_interval
            or len(observed_interval) != len(expected_interval)
        ):
            raise ValueError(
                "Charnock discourse line interval or ancestor ownership drifted"
            )
        heading = discourse.xpath("./tei:ab[@type='source-heading'][1]", namespaces=NS)
        if len(heading) != 1 or _visible(heading[0]).replace("\n", " ").split() != _source_visible(
            [rows[line - 1]]
        ).split():
            raise ValueError("Charnock discourse heading source interval drifted")
    front_expected = {
        _line_id(prefix, number)
        for number in range(start, expected_discourse_starts[0][0])
    }
    front = volume_readable[0].xpath(
        "./tei:div[@type='front-matter']", namespaces=NS
    )
    if len(front) != 1 or set(_line_pointers(front[0])) != front_expected or len(
        _line_pointers(front[0])
    ) != len(front_expected):
        raise ValueError("Charnock front-matter line interval drifted")
    expected_paragraphs = _expected_volume_paragraphs(
        rows, start=start, end=end, prefix=prefix
    )
    observed_paragraphs = [
        _line_pointers(paragraph)
        for paragraph in volume_readable[0].xpath(".//tei:p", namespaces=NS)
    ]
    if observed_paragraphs != expected_paragraphs:
        raise ValueError("Charnock native paragraph line intervals drifted")

    note_ids = {
        str(item.get(XML_ID))
        for item in shared_readable[0].xpath(".//tei:note", namespaces=NS)
    }
    expected_note_ids = {
        _note_id(f"charnock-shared-v{volume}", number) for number in range(1, 1044)
    }
    if note_ids != expected_note_ids:
        raise ValueError("Charnock shared footnote identity census drifted")
    note_by_id = {
        str(note.get(XML_ID)): note
        for note in shared_readable[0].xpath(".//tei:note", namespaces=NS)
    }
    intervals = _footnote_intervals(apparatus)
    if len(intervals) != 1043:
        raise ValueError("Charnock source footnote interval census drifted")
    note_prefix = f"charnock-shared-v{volume}"
    for number, interval_rows in intervals:
        note = note_by_id.get(_note_id(note_prefix, number))
        if note is None or note.get("n") != str(number) or note.get("place") != "end":
            raise ValueError("Charnock footnote identity or placement drifted")
        expected_interval = {
            _line_id(note_prefix, int(row["line"])) for row in interval_rows
        }
        observed_interval = _line_pointers(note)
        if (
            set(observed_interval) != expected_interval
            or len(observed_interval) != len(expected_interval)
            or _visible(note).replace("\n", " ").split()
            != _source_visible(interval_rows).split()
        ):
            raise ValueError(
                "Charnock footnote source interval or native attachment drifted"
            )
    refs = volume_readable[0].xpath(
        ".//tei:ref[@type='note']", namespaces=NS
    )
    expected_refs = [
        match.group(1)
        for number, row in enumerate(rows[start - 1 : end], start)
        if number != 100
        for match in NOTE_REF_RE.finditer(str(row["text"]))
    ]
    observed_refs = [
        (str(ref.get("target"))[1:] if (ref.get("target") or "").startswith("#") else "")
        for ref in refs
    ]
    if observed_refs != [
        _note_id(f"charnock-shared-v{volume}", int(number))
        for number in expected_refs
    ] or any((ref.text or "") != f"[{number}]" for ref, number in zip(refs, expected_refs, strict=True)):
        raise ValueError("Charnock footnote reference attachment drifted")
    if any(target not in note_by_id for target in observed_refs):
        raise ValueError("Charnock footnote reference target does not resolve")

    for prefix, selected_rows, parent in (
        (f"charnock-v{volume}", rows[start - 1 : end], volume_div),
        (f"charnock-shared-v{volume}", apparatus, shared_div),
    ):
        ledgers = parent.xpath(
            "./tei:div[@type='complete-xml-node-transcription']", namespaces=NS
        )
        if len(ledgers) != 1:
            raise ValueError("Charnock source-line ledger boundary drifted")
        carriers = ledgers[0].xpath("./tei:note", namespaces=NS)
        if len(carriers) != len(selected_rows):
            raise ValueError("Charnock source-line ledger omission or duplication")
        for ordinal, (carrier, row) in enumerate(zip(carriers, selected_rows, strict=True), 1):
            number = int(row["line"])
            feature_id = _line_id(prefix, number)
            if (
                dict(carrier.attrib)
                != {
                    XML_ID: feature_id,
                    "type": "source-line-accountability",
                    "n": str(ordinal),
                }
                or carrier.tail
                or
                carrier.get(XML_ID) != feature_id
                or carrier.get("type") != "source-line-accountability"
                or carrier.get("n") != str(ordinal)
            ):
                raise ValueError("Charnock source-line ledger identity drifted")
            try:
                record = json.loads(carrier.text or "")
            except json.JSONDecodeError as exc:
                raise ValueError("Charnock source-line ledger JSON is invalid") from exc
            if not isinstance(record, dict):
                raise ValueError("Charnock source-line ledger record is not an object")
            digest = record.pop("payload_sha256", None)
            expected_record = {
                "feature_id": feature_id,
                "ordinal": ordinal,
                "kind": "source-line",
                "line": number,
                "text": str(row["text"]),
                "record_sha256": str(row["record_sha256"]),
                "volume": volume,
            }
            if record != expected_record or digest != _sha(_canonical(record)):
                raise ValueError("Charnock source-line ledger payload drifted")


def _add_expected_lines(
    parent: etree._Element, rows: list[dict[str, object]], prefix: str
) -> None:
    for row in rows:
        number = int(row["line"])
        node = etree.SubElement(parent, f"{{{TEI}}}ab")
        node.set(XML_ID, f"{prefix}-line-{number:05d}")
        node.set("n", str(number))
        node.set("type", _expected_line_type(number, str(row["text"])))
        node.set(XML_SPACE, "preserve")
        node.text = str(row["text"]) or None


def _expected_tei(
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
    _add_expected_lines(volume_node, body, f"charnock-v{volume}")
    shared = etree.SubElement(body_node, f"{{{TEI}}}div", type="shared-apparatus")
    etree.SubElement(shared, f"{{{TEI}}}head").text = (
        "Combined index, footnotes, and transcriber notes shared by the "
        "two-volumes-in-one witness"
    )
    _add_expected_lines(shared, apparatus, f"charnock-shared-v{volume}")
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


def _repository_import_closure(
    root: Path, entry: Path, forbidden: tuple[str, ...]
) -> tuple[dict[str, str], ...]:
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
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError(
                    "Charnock oracle closure contains dynamic import or execution"
                )
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
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(
                        f"Charnock oracle closure contains forbidden import {name}"
                    )
                dependency = _module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(
    root: Path, policy: Mapping[str, object], entry: Path | None = None
) -> str:
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    return _sha(
        _canonical(_repository_import_closure(root, entry or Path(__file__), forbidden))
    )


def _runtime_paths(root: Path) -> None:
    for name in ("ocd_kernel.reconstruction.contract", "ocd_kernel.tei.validate"):
        module_file = getattr(sys.modules[name], "__file__", None)
        if not isinstance(module_file, str):
            raise ValueError("Charnock oracle runtime dependency has no path")
        path = Path(module_file).resolve(strict=True)
        path.relative_to(root)
        if "site-packages" in path.parts or "__editable__" in path.name:
            raise ValueError("Charnock oracle runtime dependency is shadowed")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Charnock profile")
    policy = _strict(policy_bytes, "Charnock policy")
    work_id = str(profile.get("work_id"))
    if work_id not in VOLUMES:
        raise ValueError("Charnock oracle work identity mismatch")
    volume, start, end = VOLUMES[work_id]
    expected_manifest = source_manifest.path.relative_to(root).as_posix()
    candidate_manifest = _strict(
        candidate.member_bytes("manifest.json"), "Charnock candidate manifest"
    )
    manifest_members = candidate_manifest.get("members")
    if (
        set(candidate_manifest) != CANDIDATE_KEYS
        or not isinstance(manifest_members, list)
        or any(
            not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"}
            for item in manifest_members
        )
        or [item["name"] for item in manifest_members] != CANDIDATE_MEMBER_NAMES
        or candidate_manifest.get("contract") != "ocd-candidate-package-v1"
        or candidate_manifest.get("status") != "nonaccepted"
        or candidate_manifest.get("source_id") != source_manifest.record["source_id"]
        or candidate_manifest.get("source_manifest")
        != {"path": expected_manifest, "sha256": source_manifest.sha256}
        or candidate_manifest.get("converter") != source_manifest.record["converter"]
        or candidate_manifest.get("package_schema")
        != source_manifest.record["package_schema"]
    ):
        raise ValueError("Charnock candidate authority binding mutation")
    source = source_manifest.authority_path("retained-source").read_bytes()
    authority = _authority(source_manifest, "retained-source")
    if (len(source), len(source.splitlines()), _sha(source)) != (
        3949934,
        62798,
        str(authority["sha256"]),
    ):
        raise ValueError("Charnock exact retained witness drifted")
    rows = _scan(source)
    inventory_sha = _sha(
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
    expected_counts = {
        "body_lines": end - start + 1,
        "shared_apparatus_lines": APPARATUS[1] - APPARATUS[0] + 1,
        "page_marker_lines": sum(
            bool(PAGE_RE.search(str(row["text"])))
            for row in [*rows[start - 1 : end], *rows[APPARATUS[0] - 1 : APPARATUS[1]]]
        ),
        "discourse_heading_lines": sum(
            str(row["text"]).strip().startswith("DISCOURSE ")
            for row in rows[start - 1 : end]
        ),
    }
    if (
        profile.get("source_scope")
        != {
            "bytes": len(source),
            "physical_lines": len(rows),
            "source_inventory_sha256": inventory_sha,
        }
        or profile.get("required_counts") != expected_counts
    ):
        raise ValueError("Charnock profile scope or structure floor drifted")
    accountability = _strict(
        candidate.member_bytes("source-accountability.json"), "Charnock accountability"
    )
    represented = set(range(start, end + 1)) | set(
        range(APPARATUS[0], APPARATUS[1] + 1)
    )
    if (
        set(accountability) != ACCOUNTABILITY_KEYS
        or accountability.get("contract")
        != "ocd-charnock-pg53527-source-accountability-v1"
        or not isinstance(accountability.get("source_member"), dict)
        or set(accountability["source_member"]) != {"path", "bytes", "sha256"}
        or accountability.get("work_id") != work_id
        or accountability.get("source_member")
        != {
            key: authority[key]
            for key in (
                "path",
                "bytes",
                "sha256",
            )
        }
        or accountability.get("body_line_range") != [start, end]
        or accountability.get("shared_apparatus_line_range") != list(APPARATUS)
        or accountability.get("physical_line_count") != len(rows)
        or accountability.get("represented_line_count") != len(represented)
        or accountability.get("evidence_only_line_count")
        != len(rows) - len(represented)
        or accountability.get("omitted_line_count") != 0
        or accountability.get("duplicate_line_count") != 0
        or accountability.get("source_inventory_sha256") != inventory_sha
        or accountability.get("required_counts") != expected_counts
    ):
        raise ValueError("Charnock source accountability counts or bindings drifted")
    accounted = accountability.get("lines")
    if not isinstance(accounted, list) or len(accounted) != len(rows):
        raise ValueError("Charnock line accounting is incomplete")
    for expected, observed in zip(rows, accounted, strict=True):
        if not isinstance(observed, dict) or set(observed) != ACCOUNTABILITY_LINE_KEYS:
            raise ValueError("Charnock source line shape drifted")
        number = int(expected["line"])
        for key in (
            "line",
            "byte_start",
            "byte_end",
            "terminator",
            "text",
            "record_sha256",
        ):
            if observed.get(key) != expected[key]:
                raise ValueError("Charnock source line accounting drifted")
        if observed.get("disposition") != (
            "represented" if number in represented else "evidence-only"
        ):
            raise ValueError("Charnock source line disposition drifted")
        expected_reason = (
            "selected volume or shared two-volume apparatus"
            if number in represented
            else "Gutenberg wrapper/license or other volume body"
        )
        expected_selector = None
        if number in represented:
            prefix = f"v{volume}" if number <= end else f"shared-v{volume}"
            expected_selector = f"#charnock-{prefix}-line-{number:05d}"
        if (
            observed.get("reason") != expected_reason
            or observed.get("tei_selector") != expected_selector
        ):
            raise ValueError("Charnock source line reason or TEI selector drifted")
    tei_bytes = candidate.member_bytes("content.tei.xml")
    document = etree.fromstring(tei_bytes)
    if (
        etree.tostring(
            document, encoding="UTF-8", xml_declaration=True, pretty_print=False
        )
        != tei_bytes
    ):
        raise ValueError("Charnock TEI serialized bytes are not canonical")
    if not compiled_schema().validate(etree.ElementTree(document)):
        raise ValueError(
            f"Charnock TEI P5 validation failed: {compiled_schema().error_log.last_error}"
        )
    if document.tag != f"{{{TEI}}}TEI" or document.attrib:
        raise ValueError("Charnock TEI root identity or namespace drifted")
    header = document.xpath("./tei:teiHeader", namespaces=NS)
    if len(header) != 1 or len(header[0]) != 1:
        raise ValueError("Charnock TEI header topology drifted")
    file_desc = header[0][0]
    if (
        file_desc.tag != f"{{{TEI}}}fileDesc"
        or [etree.QName(child).localname for child in file_desc]
        != ["titleStmt", "publicationStmt", "sourceDesc"]
    ):
        raise ValueError("Charnock TEI file description topology drifted")
    title_stmt, publication_stmt, source_desc = file_desc
    if [etree.QName(child).localname for child in title_stmt] != [
        "title",
        "author",
    ] or [etree.QName(child).localname for child in publication_stmt] != [
        "p"
    ] or [etree.QName(child).localname for child in source_desc] != ["bibl"]:
        raise ValueError("Charnock TEI metadata child topology drifted")
    bibl = source_desc[0]
    if [etree.QName(child).localname for child in bibl] != ["idno", "idno", "idno"] or [
        child.get("type") for child in bibl
    ] != ["work-id", "gutenberg", "sha256"]:
        raise ValueError("Charnock TEI source identity topology drifted")
    text_nodes = document.xpath("./tei:text", namespaces=NS)
    if len(text_nodes) != 1 or len(text_nodes[0]) != 1:
        raise ValueError("Charnock TEI text topology drifted")
    body_nodes = text_nodes[0].xpath("./tei:body", namespaces=NS)
    if len(body_nodes) != 1 or len(body_nodes[0]) != 2 or [
        dict(child.attrib) for child in body_nodes[0]
    ] != [
        {"type": "volume-body", "n": str(volume)},
        {"type": "shared-apparatus"},
    ]:
        raise ValueError("Charnock TEI body partition topology drifted")
    if (
        document.xpath("string(//tei:idno[@type='work-id'])", namespaces=NS) != work_id
        or document.xpath("string(//tei:titleStmt/tei:title)", namespaces=NS)
        != f"The Existence and Attributes of God, Vol. {volume}"
        or document.xpath("string(//tei:idno[@type='gutenberg'])", namespaces=NS)
        != "53527"
        or document.xpath("string(//tei:idno[@type='sha256'])", namespaces=NS)
        != _sha(source)
        or document.xpath("string(//tei:author)", namespaces=NS) != "Stephen Charnock"
    ):
        raise ValueError("Charnock TEI identity/source binding drifted")
    if (
        document.xpath("string(//tei:publicationStmt/tei:p)", namespaces=NS)
        != "Nonaccepted reconstruction candidate; publication:not_ready."
    ):
        raise ValueError("Charnock TEI rights/publication boundary drifted")
    if (
        document.xpath(
            "string(//tei:div[@type='shared-apparatus']/tei:head)", namespaces=NS
        )
        != "Combined index, footnotes, and transcriber notes shared by the two-volumes-in-one witness"
    ):
        raise ValueError("Charnock shared apparatus heading drifted")
    _verify_native_projection(
        document,
        rows,
        rows[APPARATUS[0] - 1 : APPARATUS[1]],
        volume=volume,
        start=start,
        end=end,
    )
    readme = source_manifest.authority_path("attribution-readme").read_bytes()
    if (
        candidate.member_bytes("README.source.md") != readme
        or b"Project Gutenberg" not in readme
        or b"publication:not_ready" not in readme
    ):
        raise ValueError("Charnock attribution/rights README drifted")
    expected_unresolved = [
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
    if candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(item) for item in expected_unresolved
    ) or set(policy.get("required_unresolved_ids", [])) != {
        item["id"] for item in expected_unresolved
    }:
        raise ValueError("Charnock unresolved evidence drifted")
    provenance = _strict(
        candidate.member_bytes("provenance.json"), "Charnock provenance"
    )
    producer_path = root / str(
        source_manifest.record["converter"]["implementation_path"]
    )
    producer_closure = _repository_import_closure(
        root,
        producer_path,
        tuple(
            str(item) for item in policy.get("producer_forbidden_import_prefixes", [])
        ),
    )
    producer_closure_sha = _sha(_canonical(producer_closure))
    expected_runtime = (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({Path(sys.executable).resolve(strict=True)})"
    )
    if (
        set(provenance) != PROVENANCE_KEYS
        or provenance.get("contract") != "ocd-charnock-pg53527-candidate-provenance-v1"
        or provenance.get("status") != "nonaccepted"
        or provenance.get("publication") != "not_ready"
        or provenance.get("work_id") != work_id
        or provenance.get("source_sha256") != _sha(source)
        or provenance.get("source_manifest_sha256") != source_manifest.sha256
        or provenance.get("producer_import_closure") != list(producer_closure)
        or provenance.get("producer_import_closure_sha256") != producer_closure_sha
        or provenance.get("runtime") != expected_runtime
        or provenance.get("shared_apparatus_disposition") != SHARED_DISPOSITION
        or profile.get("producer_import_closure_sha256") != producer_closure_sha
    ):
        raise ValueError("Charnock provenance/import closure drifted")
    _runtime_paths(root)
    closure_sha = _closure_digest(root, policy)
    if (
        closure_sha != source_manifest.record["validator"]["import_closure_sha256"]
        or _sha(Path(__file__).read_bytes())
        != source_manifest.record["validator"]["implementation_sha256"]
    ):
        raise ValueError("Charnock oracle implementation/import closure drifted")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _sha(source),
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
