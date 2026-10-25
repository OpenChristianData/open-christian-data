"""Conservative source-bound TEI reconstruction for the three assigned LIB-072 works.

This route accepts one independently prepared, work-specific SourceManifest at a
time. It reads no adjacent-source directory and never enumerates raw/gutenberg
or raw/ia. Blank-line-delimited source blocks and every source line terminator
are retained; only exact source-located heading-map entries are encoded as headings.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Protocol

from lxml import etree

CONVERTER_ID = "ocd-lib072-selected-proofread-text-to-tei"
CONVERTER_VERSION = "4"
PROFILE_CONTRACT = "ocd-selected-source-profile-v2"
HEADING_MAP_CONTRACT = "ocd-source-located-heading-map-v1"
HEADING_POLICY = "exact-source-located-lines-with-declared-parent-and-title-attachments"
SOURCE_SCOPE = "one-work-one-retained-project-gutenberg-member"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ACCOUNTABILITY_BLOCK_MAPPING = (
    "blank-line-delimited source blocks retained in order; source-located headings and mapped title attachments encoded; all balanced Project Gutenberg underscore spans counted and located"
)
NONACCEPTANCE_DISCLAIMER = (
    "Nonaccepted technical candidate. Rights clearance, human acceptance, and publication authorization are separate and have not been performed."
)
ENCODING_POLICY = (
    "The exact single retained text member is represented in source order. Each nonblank run between exact blank lines retains a source-block selector; line breaks and blank delimiters are explicit. Only the exact source-located heading map bound in the work profile is encoded as nested source-heading sections, and mapped title line runs are attached to their mapped heading. Balanced Project Gutenberg underscore spans are represented by hi rend source-underscore fragments that retain both literal delimiters; a multiline span is split only at retained source lines and its later fragments point to the opening fragment. Unmapped capitalization, contents entries, and unresolved hierarchy remain as source-block text."
)
UNDERSCORE_MARKUP_CONTRACT = "ocd-pg-underscore-span-census-v1"
EXPECTED_UNDERSCORE_MARKER_COUNT = 1304
EXPECTED_UNDERSCORE_SPAN_COUNT = 652
EXPECTED_MAX_UNDERSCORE_INTERIOR_CHARACTERS = 566
UNDERSCORE_REPRESENTATION = (
    "one TEI hi rend source-underscore fragment per source-line intersection; literal opening and closing underscore characters remain inside the fragments; continuation fragments corresp to the opening fragment xml:id"
)
SOURCE_UNDERSCORE_POLICY = {
    "contract": UNDERSCORE_MARKUP_CONTRACT,
    "marker_character": "_",
    "expected_marker_count": EXPECTED_UNDERSCORE_MARKER_COUNT,
    "expected_span_count": EXPECTED_UNDERSCORE_SPAN_COUNT,
    "maximum_interior_character_count": EXPECTED_MAX_UNDERSCORE_INTERIOR_CHARACTERS,
    "pairing_scope": "balanced pairs reset at each blank-line-delimited source block",
    "representation": UNDERSCORE_REPRESENTATION,
}
ALLOWED_SOURCES = {
    "wilberforce-practical-view": {
        "ticket_id": "37c-322",
        "source_id": "gutenberg-37c-322-pg25709",
        "source_path": "raw/gutenberg/pg25709.txt",
        "source_bytes": 659285,
        "source_sha256": "995ff74ac2c819b526d4874878507bb85e1141f7e5b35a388c44846a963d6c96",
        "source_url": "https://www.gutenberg.org/ebooks/25709",
        "title": "A Practical View of the Prevailing Religious System of Professed Christians",
    },
}
_EOL_BYTES = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}


class SourceManifestLike(Protocol):
    @property
    def record(self) -> Mapping[str, object]: ...

    @property
    def sha256(self) -> str: ...

    def authority_path(self, name: str) -> Path: ...

    def verify(self) -> None: ...


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _line_rows(content: bytes) -> list[tuple[str, str]]:
    """Split only on CR/LF and retain each exact UTF-8 line terminator."""
    content.decode("utf-8")
    rows: list[tuple[str, str]] = []
    start = 0
    position = 0
    while position < len(content):
        if content[position] not in (0x0A, 0x0D):
            position += 1
            continue
        text = content[start:position].decode("utf-8")
        if content[position] == 0x0D and position + 1 < len(content) and content[position + 1] == 0x0A:
            ending = "crlf"
            position += 2
        else:
            ending = "cr" if content[position] == 0x0D else "lf"
            position += 1
        rows.append((text, ending))
        start = position
    if start < len(content):
        rows.append((content[start:].decode("utf-8"), "none"))
    if b"".join(text.encode("utf-8") + _EOL_BYTES[ending] for text, ending in rows) != content:
        raise ValueError("LIB-072 selected source line decomposition is not lossless")
    return rows


def _units(rows: list[tuple[str, str]]) -> list[dict[str, object]]:
    """Group exact nonblank runs while retaining each source blank line."""
    units: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    block_number = 0
    for line_number, (text, ending) in enumerate(rows, 1):
        row = {"line_number": line_number, "text": text, "ending": ending}
        if text == "":
            if active:
                block_number += 1
                units.append({"kind": "block", "block_number": block_number, "rows": active})
                active = []
            units.append({"kind": "blank", "row": row})
        else:
            active.append(row)
    if active:
        block_number += 1
        units.append({"kind": "block", "block_number": block_number, "rows": active})
    return units


def _underscore_spans(
    work_id: str,
    rows: list[tuple[str, str]],
    units: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Census balanced source underscores independently within each source block."""
    if units is None:
        units = _units(rows)
    spans: list[dict[str, object]] = []
    marker_count = 0
    for unit in units:
        if unit["kind"] != "block":
            continue
        block_number = int(unit["block_number"])
        block_rows = unit["rows"]
        markers = [
            (int(row["line_number"]), column + 1)
            for row in block_rows
            for column, character in enumerate(str(row["text"]))
            if character == "_"
        ]
        marker_count += len(markers)
        if len(markers) % 2:
            line_number, column = markers[-1]
            raise ValueError(
                f"unmatched source underscore in block {block_number} at {line_number}:{column}"
            )
        rows_by_line = {int(row["line_number"]): row for row in block_rows}
        for pair_index in range(0, len(markers), 2):
            start_line, start_column = markers[pair_index]
            end_line, end_column = markers[pair_index + 1]
            if end_line < start_line or (
                end_line == start_line and end_column <= start_column
            ):
                raise ValueError(
                    f"ambiguous source underscore pair in block {block_number}"
                )
            line_numbers = list(range(start_line, end_line + 1))
            fragment_texts: list[str] = []
            fragment_records: list[dict[str, object]] = []
            raw_parts: list[bytes] = []
            for part_index, line_number in enumerate(line_numbers, 1):
                row = rows_by_line.get(line_number)
                if row is None:
                    raise ValueError(
                        f"source underscore span crosses a blank line at {line_number}"
                    )
                text = str(row["text"])
                first_column = start_column if line_number == start_line else 1
                last_column = end_column if line_number == end_line else len(text)
                if (
                    first_column < 1
                    or last_column < first_column
                    or last_column > len(text)
                ):
                    raise ValueError(
                        f"source underscore span has an invalid line fragment at {line_number}"
                    )
                fragment_text = text[first_column - 1 : last_column]
                fragment_texts.append(fragment_text)
                raw_parts.append(fragment_text.encode("utf-8"))
                fragment_records.append(
                    {
                        "line_number": line_number,
                        "start_column": first_column,
                        "end_column": last_column,
                        "part_index": part_index,
                        "part_count": len(line_numbers),
                        "text_sha256": _sha(fragment_text.encode("utf-8")),
                    }
                )
                if line_number < end_line:
                    ending = str(row["ending"])
                    if ending not in _EOL_BYTES or not _EOL_BYTES[ending]:
                        raise ValueError(
                            f"source underscore span crosses a line without a terminator at {line_number}"
                        )
                    raw_parts.append(_EOL_BYTES[ending])
            logical_span = "\n".join(fragment_texts)
            interior = logical_span[1:-1]
            if not interior.strip():
                raise ValueError(
                    f"empty or ambiguous source underscore span at {start_line}:{start_column}"
                )
            source_bytes = b"".join(raw_parts)
            span_number = len(spans) + 1
            spans.append(
                {
                    "span_id": f"{work_id}-underscore-{span_number:04d}",
                    "block_id": f"{work_id}-block-{block_number:05d}",
                    "start_line": start_line,
                    "start_column": start_column,
                    "end_line": end_line,
                    "end_column": end_column,
                    "logical_character_count": len(logical_span),
                    "interior_character_count": len(interior),
                    "physical_byte_count": len(source_bytes),
                    "source_sha256": _sha(source_bytes),
                    "fragments": fragment_records,
                }
            )
    if marker_count != EXPECTED_UNDERSCORE_MARKER_COUNT:
        raise ValueError(
            f"source underscore marker census drifted: {marker_count}"
        )
    if len(spans) != EXPECTED_UNDERSCORE_SPAN_COUNT:
        raise ValueError(f"source underscore span census drifted: {len(spans)}")
    if max(int(span["interior_character_count"]) for span in spans) != EXPECTED_MAX_UNDERSCORE_INTERIOR_CHARACTERS:
        raise ValueError("source underscore maximum interior length drifted")
    return spans


def _heading_plan(
    work: Mapping[str, object],
    rows: list[tuple[str, str]],
    units: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Validate source-located labels and mapped title runs against exact source rows."""
    if units is None:
        units = _units(rows)
    raw_map = work.get("heading_map")
    if not isinstance(raw_map, list) or not raw_map:
        raise ValueError("selected work has no source-located heading map")

    row_by_line = {
        number: {"line_number": number, "text": text, "ending": ending}
        for number, (text, ending) in enumerate(rows, 1)
    }
    block_by_line: dict[int, dict[str, object]] = {}
    next_unit_by_block: dict[int, int] = {}
    for unit_index, unit in enumerate(units):
        if unit["kind"] != "block":
            continue
        block_number = int(unit["block_number"])
        for row in unit["rows"]:
            block_by_line[int(row["line_number"])] = unit
        next_unit_by_block[block_number] = unit_index

    headings: dict[int, Mapping[str, object]] = {}
    title_owner: dict[int, int] = {}
    title_lines_by_heading: dict[int, list[Mapping[str, object]]] = {}
    active_by_level: dict[int, int] = {}
    previous_line = 0
    required_keys = {
        "line_number",
        "source_text",
        "level",
        "parent_line",
        "attached_title_lines",
    }
    for item in raw_map:
        if not isinstance(item, Mapping) or set(item) != required_keys:
            raise ValueError("selected work heading-map entry has an invalid shape")
        line_number = item.get("line_number")
        level = item.get("level")
        parent_line = item.get("parent_line")
        if (
            not isinstance(line_number, int)
            or isinstance(line_number, bool)
            or line_number <= previous_line
            or line_number not in row_by_line
            or not isinstance(level, int)
            or isinstance(level, bool)
            or level < 1
            or (parent_line is not None and (not isinstance(parent_line, int) or isinstance(parent_line, bool)))
        ):
            raise ValueError("selected work heading-map location or level is invalid")
        source_text = item.get("source_text")
        if not isinstance(source_text, str) or row_by_line[line_number]["text"] != source_text or source_text == "":
            raise ValueError(f"selected work heading-map source text drifted at line {line_number}")
        if level == 1:
            if parent_line is not None:
                raise ValueError("level-one source heading cannot declare a parent")
            active_by_level.clear()
        else:
            if parent_line is None or active_by_level.get(level - 1) != parent_line:
                raise ValueError(f"source heading hierarchy is unresolved at line {line_number}")
            for old_level in tuple(active_by_level):
                if old_level >= level:
                    del active_by_level[old_level]
        if len(active_by_level) != level - 1:
            raise ValueError(f"source heading hierarchy has a missing level at line {line_number}")

        heading_block = block_by_line[line_number]
        heading_rows = heading_block["rows"]
        if len(heading_rows) != 1 or int(heading_rows[0]["line_number"]) != line_number:
            raise ValueError(f"mapped source heading is not an isolated source block at line {line_number}")

        raw_titles = item.get("attached_title_lines")
        if not isinstance(raw_titles, list):
            raise ValueError(f"mapped title-line inventory is invalid at heading line {line_number}")
        title_rows: list[Mapping[str, object]] = []
        for title in raw_titles:
            if not isinstance(title, Mapping) or set(title) != {"line_number", "source_text"}:
                raise ValueError(f"mapped title-line entry is invalid at heading line {line_number}")
            title_line = title.get("line_number")
            title_text = title.get("source_text")
            if (
                not isinstance(title_line, int)
                or isinstance(title_line, bool)
                or title_line not in row_by_line
                or title_line in title_owner
                or title_line in headings
                or not isinstance(title_text, str)
                or title_text == ""
                or row_by_line[title_line]["text"] != title_text
            ):
                raise ValueError(f"mapped title-line source text drifted at heading line {line_number}")
            title_rows.append(row_by_line[title_line])
        if title_rows:
            title_numbers = [int(row["line_number"]) for row in title_rows]
            if title_numbers != list(range(title_numbers[0], title_numbers[0] + len(title_numbers))):
                raise ValueError(f"mapped title lines are not contiguous at heading line {line_number}")
            heading_unit_index = next_unit_by_block[int(heading_block["block_number"])]
            following_blocks = [
                unit
                for unit in units[heading_unit_index + 1 :]
                if unit["kind"] == "block"
            ]
            if not following_blocks or [int(row["line_number"]) for row in following_blocks[0]["rows"]] != title_numbers:
                raise ValueError(f"mapped title run is not the following source block at heading line {line_number}")
            for title_row in title_rows:
                title_owner[int(title_row["line_number"])] = line_number

        headings[line_number] = item
        title_lines_by_heading[line_number] = title_rows
        active_by_level[level] = line_number
        previous_line = line_number

    if len(headings) != len(raw_map) or len(title_owner) != sum(len(item) for item in title_lines_by_heading.values()):
        raise ValueError("selected work heading map contains duplicate source locations")
    return {
        "headings": headings,
        "title_owner": title_owner,
        "title_lines_by_heading": title_lines_by_heading,
        "units": units,
    }


def _select(source_manifest: SourceManifestLike) -> tuple[dict[str, object], Mapping[str, object]]:
    work_id = source_manifest.record.get("work_id")
    if not isinstance(work_id, str) or work_id not in ALLOWED_SOURCES:
        raise ValueError("LIB-072 selected route rejects an out-of-scope work")
    expected = ALLOWED_SOURCES[work_id]
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple) or not authorities:
        raise ValueError("LIB-072 selected manifest authorities are invalid")
    raw_authorities = []
    for authority in authorities:
        if not isinstance(authority, Mapping):
            raise ValueError("LIB-072 selected manifest authority is invalid")
        logical_path = authority.get("path")
        if isinstance(logical_path, str):
            parts = tuple(part.casefold() for part in Path(logical_path).parts)
            if parts and parts[0] == "raw":
                raw_authorities.append(authority)
    if (
        len(raw_authorities) != 1
        or raw_authorities[0].get("name") != "primary-source"
        or raw_authorities[0].get("role") != "primary-source"
        or raw_authorities[0].get("path") != expected["source_path"]
    ):
        raise ValueError("LIB-072 selected manifest may bind only its exact primary source under raw/")
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "LIB-072 selected profile",
    )
    works = profile.get("works")
    if (
        profile.get("contract") != PROFILE_CONTRACT
        or profile.get("heading_map_contract") != HEADING_MAP_CONTRACT
        or profile.get("source_scope") != SOURCE_SCOPE
        or profile.get("source_underscore_policy") != SOURCE_UNDERSCORE_POLICY
        or profile.get("ticket_id") != expected["ticket_id"]
        or profile.get("source_id") != expected["source_id"]
        or profile.get("heading_policy") != HEADING_POLICY
        or "explicit_heading_markers" in profile
        or profile.get("adjacent_retained_member_paths") != []
        or not isinstance(works, list)
        or len(works) != 1
        or not isinstance(works[0], dict)
        or works[0].get("work_id") != work_id
        or works[0].get("ticket_id") != expected["ticket_id"]
        or works[0].get("source_path") != expected["source_path"]
        or works[0].get("source_bytes") != expected["source_bytes"]
        or works[0].get("source_sha256") != expected["source_sha256"]
        or works[0].get("source_url") != expected["source_url"]
        or works[0].get("title") != expected["title"]
        or not isinstance(works[0].get("heading_map"), list)
    ):
        raise ValueError("LIB-072 selected profile scope or source-heading map drift")
    work = works[0]
    primary = [item for item in authorities if item.get("role") == "primary-source"]
    if (
        len(primary) != 1
        or primary[0].get("name") != profile.get("primary_source_authority_name")
        or primary[0].get("path") != expected["source_path"]
        or source_manifest.record.get("source_id") != expected["source_id"]
        or source_manifest.record.get("ticket_id") != expected["ticket_id"]
    ):
        raise ValueError("LIB-072 selected manifest must bind exactly its one allowed source")
    return profile, work


def _append_text(node: etree._Element, value: str) -> None:
    if not value:
        return
    if len(node):
        node[-1].tail = (node[-1].tail or "") + value
    else:
        node.text = (node.text or "") + value


def _append_lines(
    parent: etree._Element,
    work_id: str,
    rows: list[dict[str, object]],
    underscore_spans: list[dict[str, object]],
) -> None:
    fragments_by_line: dict[int, list[tuple[dict[str, object], dict[str, object]]]] = {}
    for span in underscore_spans:
        fragments = span["fragments"]
        for fragment in fragments:
            fragments_by_line.setdefault(int(fragment["line_number"]), []).append(
                (span, fragment)
            )
    for index, row in enumerate(rows):
        line_number = int(row["line_number"])
        line_text = str(row["text"])
        segment = etree.SubElement(
            parent,
            f"{{{TEI_NS}}}seg",
            type="source-line",
            n=str(line_number),
            subtype=str(row["ending"]),
        )
        segment.set(XML_ID, f"{work_id}-line-{line_number:05d}")
        cursor = 1
        for span, fragment in sorted(
            fragments_by_line.get(line_number, []),
            key=lambda item: int(item[1]["start_column"]),
        ):
            start_column = int(fragment["start_column"])
            end_column = int(fragment["end_column"])
            if start_column < cursor or end_column < start_column or end_column > len(line_text):
                raise ValueError(
                    f"source underscore fragments overlap or drift at line {line_number}"
                )
            _append_text(segment, line_text[cursor - 1 : start_column - 1])
            hi = etree.SubElement(
                segment,
                f"{{{TEI_NS}}}hi",
                rend="source-underscore",
            )
            if int(fragment["part_index"]) == 1:
                hi.set(XML_ID, str(span["span_id"]))
            else:
                hi.set("corresp", f"#{span['span_id']}")
            hi.text = line_text[start_column - 1 : end_column]
            cursor = end_column + 1
        _append_text(segment, line_text[cursor - 1 :])
        if index + 1 < len(rows):
            line_break = etree.SubElement(parent, f"{{{TEI_NS}}}lb", type="source-line-break")
            line_break.set("n", str(line_number))


def _tei(
    work: Mapping[str, object],
    content: bytes,
    source_correction_attestation: str,
    underscore_spans: list[dict[str, object]],
) -> bytes:
    rows = _line_rows(content)
    units = _units(rows)
    plan = _heading_plan(work, rows, units)
    headings = plan["headings"]
    title_owner = plan["title_owner"]
    work_id = str(work["work_id"])
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(XML_ID, f"gutenberg-{work_id}")

    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    title = etree.SubElement(title_stmt, f"{{{TEI_NS}}}title", type="ticket-work-label")
    title.text = str(work["title"])
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{TEI_NS}}}availability")
    etree.SubElement(availability, f"{{{TEI_NS}}}p").text = NONACCEPTANCE_DISCLAIMER
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI_NS}}}bibl", type="retained-witness")
    bibl.set(XML_ID, f"source-{work_id}")
    etree.SubElement(bibl, f"{{{TEI_NS}}}title", type="ticket-work-label").text = str(work["title"])
    etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="witness-description").text = str(
        work["witness_description"]
    )
    etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="source-correction-attestation").text = (
        source_correction_attestation
    )
    etree.SubElement(bibl, f"{{{TEI_NS}}}ref", target=str(work["source_url"])).text = str(
        work["source_path"]
    )

    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = ENCODING_POLICY
    text = etree.SubElement(root, f"{{{TEI_NS}}}text", {"{http://www.w3.org/XML/1998/namespace}lang": "en"})
    group = etree.SubElement(text, f"{{{TEI_NS}}}group")
    work_text = etree.SubElement(group, f"{{{TEI_NS}}}text")
    work_text.set(XML_ID, work_id)
    body = etree.SubElement(work_text, f"{{{TEI_NS}}}body")
    witness = etree.SubElement(
        body,
        f"{{{TEI_NS}}}div",
        type="retained-text-witness",
        corresp=f"#source-{work_id}",
    )

    headings_by_line = headings
    title_owner_by_line = title_owner
    sections_by_line: dict[int, etree._Element] = {}
    active_sections: dict[int, int] = {}

    def current_parent() -> etree._Element:
        if not active_sections:
            return witness
        return sections_by_line[active_sections[max(active_sections)]]

    for unit in units:
        if unit["kind"] == "blank":
            row = unit["row"]
            space = etree.SubElement(
                current_parent(),
                f"{{{TEI_NS}}}space",
                type="source-blank-line",
                unit="line",
                quantity="1",
                n=str(row["line_number"]),
                subtype=str(row["ending"]),
            )
            space.set(XML_ID, f"{work_id}-blank-{int(row['line_number']):05d}")
            continue

        block_number = int(unit["block_number"])
        block_id = f"{work_id}-block-{block_number:05d}"
        block_rows = unit["rows"]
        first_line = int(block_rows[0]["line_number"])
        if first_line in headings_by_line:
            heading = headings_by_line[first_line]
            if len(block_rows) != 1:
                raise ValueError(f"mapped source heading block is not isolated at line {first_line}")
            level = int(heading["level"])
            parent_line = heading["parent_line"]
            if level == 1:
                parent = witness
                active_sections.clear()
            else:
                if not isinstance(parent_line, int) or active_sections.get(level - 1) != parent_line:
                    raise ValueError(f"source heading parent is detached at line {first_line}")
                parent = sections_by_line[parent_line]
                for old_level in tuple(active_sections):
                    if old_level >= level:
                        del active_sections[old_level]
            block = etree.SubElement(
                parent,
                f"{{{TEI_NS}}}div",
                type="source-heading-section",
                n=str(block_number),
                subtype=f"level-{level}",
            )
            block.set(XML_ID, block_id)
            if parent_line is not None:
                block.set("corresp", f"#{work_id}-heading-{int(parent_line):05d}")
            head = etree.SubElement(
                block,
                f"{{{TEI_NS}}}head",
                type="source-located-heading",
                n=str(first_line),
                subtype=str(level),
            )
            head.set(XML_ID, f"{work_id}-heading-{first_line:05d}")
            _append_lines(head, work_id, block_rows, underscore_spans)
            sections_by_line[first_line] = block
            active_sections[level] = first_line
            continue

        title_heading = title_owner_by_line.get(first_line)
        parent = (
            sections_by_line[title_heading]
            if title_heading is not None
            else current_parent()
        )
        block = etree.SubElement(
            parent,
            f"{{{TEI_NS}}}div",
            type="source-block",
            n=str(block_number),
        )
        block.set(XML_ID, block_id)
        if title_heading is not None:
            title_rows = plan["title_lines_by_heading"][title_heading]
            if [int(row["line_number"]) for row in title_rows] != [
                int(row["line_number"]) for row in block_rows
            ]:
                raise ValueError(f"mapped source title block drifted at line {first_line}")
            title = etree.SubElement(
                block,
                f"{{{TEI_NS}}}head",
                type="source-attached-title",
                n=str(first_line),
                corresp=f"#{work_id}-heading-{title_heading:05d}",
            )
            title.set(XML_ID, f"{work_id}-title-{first_line:05d}")
            _append_lines(title, work_id, title_rows, underscore_spans)
        else:
            paragraph = etree.SubElement(
                block,
                f"{{{TEI_NS}}}p",
                n=str(first_line),
            )
            paragraph.set(XML_ID, f"{work_id}-unit-{first_line:05d}")
            _append_lines(paragraph, work_id, block_rows, underscore_spans)

    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifestLike) -> Mapping[str, bytes]:
    profile, work = _select(source_manifest)
    source_manifest.verify()
    authority_name = str(profile["primary_source_authority_name"])
    content = source_manifest.authority_path(authority_name).read_bytes()
    if (
        len(content) != work.get("source_bytes")
        or _sha(content) != work.get("source_sha256")
        or len(content) != ALLOWED_SOURCES[str(work["work_id"])]["source_bytes"]
        or _sha(content) != ALLOWED_SOURCES[str(work["work_id"])]["source_sha256"]
    ):
        raise ValueError(f"LIB-072 selected retained source drift: {work['work_id']}")
    rows = _line_rows(content)
    units = _units(rows)
    plan = _heading_plan(work, rows, units)
    underscore_spans = _underscore_spans(str(work["work_id"]), rows, units)
    headings = plan["headings"]
    title_owner = plan["title_owner"]
    underscore_spans_by_block: dict[str, list[dict[str, object]]] = {}
    underscore_span_ids_by_line: dict[int, list[str]] = {}
    for span in underscore_spans:
        block_id = str(span["block_id"])
        underscore_spans_by_block.setdefault(block_id, []).append(span)
        for fragment in span["fragments"]:
            underscore_span_ids_by_line.setdefault(
                int(fragment["line_number"]), []
            ).append(str(span["span_id"]))
    ending_counts = {
        ending: sum(observed == ending for _, observed in rows)
        for ending in ("crlf", "lf", "cr", "none")
    }
    line_ledger: list[dict[str, object]] = []
    block_ledger: list[dict[str, object]] = []
    for unit in units:
        if unit["kind"] == "blank":
            row = unit["row"]
            line_ledger.append(
                {
                    "line_number": row["line_number"],
                    "text_sha256": _sha(str(row["text"]).encode("utf-8")),
                    "line_ending": row["ending"],
                    "structural_role": "blank-line",
                    "block_id": None,
                    "source_underscore_span_ids": [],
                }
            )
            continue
        block_number = int(unit["block_number"])
        block_id = f"{work['work_id']}-block-{block_number:05d}"
        heading_lines = [
            int(row["line_number"])
            for row in unit["rows"]
            if int(row["line_number"]) in headings
        ]
        attached_title_lines = [
            int(row["line_number"])
            for row in unit["rows"]
            if int(row["line_number"]) in title_owner
        ]
        line_numbers: list[int] = []
        for row in unit["rows"]:
            line_number = int(row["line_number"])
            line_numbers.append(line_number)
            line_ledger.append(
                {
                    "line_number": line_number,
                    "text_sha256": _sha(str(row["text"]).encode("utf-8")),
                    "line_ending": row["ending"],
                    "structural_role": (
                        "explicit-source-heading"
                        if line_number in headings
                        else "source-attached-title"
                        if line_number in title_owner
                        else "source-block-text"
                    ),
                    "block_id": block_id,
                    "source_underscore_span_ids": underscore_span_ids_by_line.get(
                        line_number, []
                    ),
                }
            )
        block_ledger.append(
            {
                "block_id": block_id,
                "block_number": block_number,
                "start_line": min(line_numbers),
                "end_line": max(line_numbers),
                "line_count": len(line_numbers),
                "heading_lines": heading_lines,
                "attached_title_lines": attached_title_lines,
                "underscore_marker_count": sum(
                    str(row["text"]).count("_") for row in unit["rows"]
                ),
                "underscore_span_count": len(
                    underscore_spans_by_block.get(block_id, [])
                ),
            }
        )
    line_ledger.sort(key=lambda record: int(record["line_number"]))
    source_member = {
        "work_id": work["work_id"],
        "path": work["source_path"],
        "bytes": len(content),
        "sha256": _sha(content),
        "disposition": "included in full as the one primary-source member in this ticket-bound SourceManifest",
    }
    work_row = {
        "ticket_id": profile["ticket_id"],
        "work_id": work["work_id"],
        "source_path": work["source_path"],
        "source_sha256": _sha(content),
        "line_count": len(rows),
        "nonblank_line_count": sum(bool(text) for text, _ in rows),
        "blank_line_count": sum(text == "" for text, _ in rows),
        "source_block_count": len(block_ledger),
        "explicit_heading_count": sum(len(item["heading_lines"]) for item in block_ledger),
        "character_count": sum(len(text) for text, _ in rows),
        "line_ending_counts": ending_counts,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_block_selector_contract": f"#{work['work_id']}-block-%05d",
        "source_line_selector_contract": f"#{work['work_id']}-line-%05d",
        "source_lines": line_ledger,
        "source_blocks": block_ledger,
        "source_underscore_markup": {
            "contract": UNDERSCORE_MARKUP_CONTRACT,
            "marker_character": "_",
            "marker_count": sum(
                sum(str(source_row["text"]).count("_") for source_row in source_block["rows"])
                for source_block in units
                if source_block["kind"] == "block"
            ),
            "span_count": len(underscore_spans),
            "maximum_interior_character_count": max(
                int(span["interior_character_count"]) for span in underscore_spans
            ),
            "pairing_scope": "balanced pairs reset at each blank-line-delimited source block",
            "representation": UNDERSCORE_REPRESENTATION,
            "spans": underscore_spans,
        },
    }
    schema_path = source_manifest.authority_path("source-accountability-schema")
    accountability: dict[str, object] = {
        "contract": "ocd-selected-source-accountability-v2",
        "schema": schema_path.name,
        "profile_id": profile["profile_id"],
        "ticket_id": profile["ticket_id"],
        "assigned_work_count": 1,
        "assigned_member_count": 1,
        "adjacent_member_count": 0,
        "adjacent_inventory_scope": "not enumerated; only the exact source member declared in this ticket-bound SourceManifest is in scope",
        "source_members": [source_member],
        "adjacent_retained_member_accounting": [],
        "works": [work_row],
        "total_line_count": len(rows),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_byte_reassembly": "exact UTF-8 source line text plus its recorded CR/LF terminator",
        "block_mapping": ACCOUNTABILITY_BLOCK_MAPPING,
        "candidate_status": "nonaccepted",
        "human_review_required": True,
        "publication_ready": False,
    }
    provenance = {
        "contract": "ocd-selected-source-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "profile_id": profile["profile_id"],
        "ticket_id": profile["ticket_id"],
        "text_authority": "the one primary-source member declared by this ticket-bound SourceManifest",
        "work": {
            "work_id": work["work_id"],
            "ticket_work_label": work["title"],
            "source_path": work["source_path"],
            "source_sha256": _sha(content),
            "witness_description": work["witness_description"],
        },
        "source_correction_attestation": profile["source_correction_attestation"],
        "human_review": "required",
        "accepted_ir": "not_accepted",
        "publication": "not_ready",
        "rights": {
            "provider_attribution": "Distributed Proofreaders attribution retained from the bound source record",
            "clearance": "not assessed by this technical reconstruction",
            "publication_state": "not_ready",
        },
    }
    unresolved = profile.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("LIB-072 selected profile unresolved evidence is invalid")
    readme = source_manifest.authority_path("source-local-readme").read_bytes()
    return {
        "content.tei.xml": _tei(
            work,
            content,
            str(profile["source_correction_attestation"]),
            underscore_spans,
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
