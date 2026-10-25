"""Conservative source-bound TEI reconstruction for the three assigned LIB-071 works.

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

CONVERTER_ID = "ocd-lib071-selected-proofread-text-to-tei"
CONVERTER_VERSION = "4"
PROFILE_CONTRACT = "ocd-selected-source-profile-v2"
HEADING_MAP_CONTRACT = "ocd-source-located-heading-map-v1"
CAREY_TABLE_MAP_CONTRACT = "ocd-carey-source-table-map-v1"
HEADING_POLICY = "exact-source-located-lines-with-declared-parent-and-title-attachments"
SOURCE_SCOPE = "one-work-one-retained-project-gutenberg-member"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ACCOUNTABILITY_BLOCK_MAPPING = (
    "blank-line-delimited source blocks retained in order; source-located headings and mapped title attachments encoded"
)
NONACCEPTANCE_DISCLAIMER = (
    "Nonaccepted technical candidate. Rights clearance, human acceptance, and publication authorization are separate and have not been performed."
)
ENCODING_POLICY = (
    "The exact single retained text member is represented in source order. Each nonblank run between exact blank lines retains a source-block selector; line breaks and blank delimiters are explicit. Only exact source-located headings and mapped title runs are encoded as sections and attached titles. For Carey, the four retained geographical tables preserve source-located rows, cells, grouped population columns, continuations, blanks, qualifiers, and note links. Unmapped capitalization, contents entries, and unresolved hierarchy remain as source-block text."
)
ALLOWED_SOURCES = {
    "carey-enquiry": {
        "ticket_id": "37c-094",
        "source_id": "gutenberg-37c-094-pg11449",
        "source_path": "raw/gutenberg/pg11449.txt",
        "source_bytes": 117568,
        "source_sha256": "6dc07e5606be5a0032d6583fa5b663a81ed0971a5d9d1f267cfc14959aa602c0",
        "source_url": "https://www.gutenberg.org/ebooks/11449",
        "title": "An Enquiry into the Obligations of Christians to Use Means for the Conversion of the Heathens",
    },
    "drummond-greatest-thing": {
        "ticket_id": "37c-135",
        "source_id": "gutenberg-37c-135-pg16739",
        "source_path": "raw/gutenberg/pg16739.txt",
        "source_bytes": 204970,
        "source_sha256": "12f442db074bfd81db981dfb7c423120e830feb2019b2c0db253692e23624048",
        "source_url": "https://www.gutenberg.org/ebooks/16739",
        "title": "The Greatest Thing in the World and Other Addresses",
    },
    "drummond-natural-law": {
        "ticket_id": "37c-136",
        "source_id": "gutenberg-37c-136-pg23334",
        "source_path": "raw/gutenberg/pg23334.txt",
        "source_bytes": 566707,
        "source_sha256": "e13875abb98d6818ef2c9adbdce89a194368e082194881dcbf1e0c32a3c22333",
        "source_url": "https://www.gutenberg.org/ebooks/23334",
        "title": "Natural Law in the Spiritual World",
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
        raise ValueError("LIB-071 selected source line decomposition is not lossless")
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
        raise ValueError("LIB-071 selected route rejects an out-of-scope work")
    expected = ALLOWED_SOURCES[work_id]
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple) or not authorities:
        raise ValueError("LIB-071 selected manifest authorities are invalid")
    raw_authorities = []
    for authority in authorities:
        if not isinstance(authority, Mapping):
            raise ValueError("LIB-071 selected manifest authority is invalid")
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
        raise ValueError("LIB-071 selected manifest may bind only its exact primary source under raw/")
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "LIB-071 selected profile",
    )
    works = profile.get("works")
    if (
        profile.get("contract") != PROFILE_CONTRACT
        or profile.get("heading_map_contract") != HEADING_MAP_CONTRACT
        or profile.get("source_scope") != SOURCE_SCOPE
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
        raise ValueError("LIB-071 selected profile scope or source-heading map drift")
    work = works[0]
    if work_id == "carey-enquiry" and profile.get("table_map_contract") != CAREY_TABLE_MAP_CONTRACT:
        raise ValueError("Carey selected profile has no supported source-table map")
    primary = [item for item in authorities if item.get("role") == "primary-source"]
    if (
        len(primary) != 1
        or primary[0].get("name") != profile.get("primary_source_authority_name")
        or primary[0].get("path") != expected["source_path"]
        or source_manifest.record.get("source_id") != expected["source_id"]
        or source_manifest.record.get("ticket_id") != expected["ticket_id"]
    ):
        raise ValueError("LIB-071 selected manifest must bind exactly its one allowed source")
    return profile, work


def _append_lines(parent: etree._Element, work_id: str, rows: list[dict[str, object]]) -> None:
    for index, row in enumerate(rows):
        line_number = int(row["line_number"])
        segment = etree.SubElement(
            parent,
            f"{{{TEI_NS}}}seg",
            type="source-line",
            n=str(line_number),
            subtype=str(row["ending"]),
        )
        segment.set(XML_ID, f"{work_id}-line-{line_number:05d}")
        segment.text = str(row["text"])
        if index + 1 < len(rows):
            line_break = etree.SubElement(parent, f"{{{TEI_NS}}}lb", type="source-line-break")
            line_break.set("n", str(line_number))


def _source_tables(work: Mapping[str, object]) -> list[Mapping[str, object]]:
    if work.get("work_id") != "carey-enquiry":
        return []
    tables = work.get("source_tables")
    if not isinstance(tables, list) or len(tables) != 4:
        raise ValueError("Carey profile must map exactly four source tables")
    observed: list[Mapping[str, object]] = []
    previous_end = 0
    identities: set[str] = set()
    for item in tables:
        if not isinstance(item, Mapping):
            raise ValueError("Carey source-table map contains a non-object entry")
        table_id = item.get("table_id")
        start_line = item.get("start_line")
        end_line = item.get("end_line")
        heading_line = item.get("heading_line")
        columns = item.get("column_roles")
        base_fields = item.get("base_fields")
        boundaries = item.get("column_boundaries")
        header_rows = item.get("header_rows")
        continuations = item.get("continuations")
        notes = item.get("notes")
        groups = item.get("groups")
        if (
            not isinstance(table_id, str)
            or not table_id
            or table_id in identities
            or not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or start_line <= previous_end
            or end_line < start_line
            or not isinstance(heading_line, int)
            or isinstance(heading_line, bool)
            or not isinstance(columns, list)
            or not columns
            or any(not isinstance(role, str) or not role for role in columns)
            or not isinstance(base_fields, list)
            or not base_fields
            or not isinstance(boundaries, list)
            or len(boundaries) != len(base_fields) - 1
            or any(not isinstance(position, int) or isinstance(position, bool) or position < 0 for position in boundaries)
            or not isinstance(header_rows, Mapping)
            or set(header_rows) != {"title", "columns", "units"}
            or any(not isinstance(header_rows[key], int) for key in header_rows)
            or not isinstance(continuations, Mapping)
            or not isinstance(notes, list)
            or not isinstance(groups, list)
        ):
            raise ValueError("Carey source-table map has invalid identifiers, ranges, or columns")
        identities.add(table_id)
        previous_end = end_line
        span_total = 0
        for field in base_fields:
            if (
                not isinstance(field, Mapping)
                or set(field) != {"role", "cols"}
                or not isinstance(field.get("role"), str)
                or not isinstance(field.get("cols"), int)
                or isinstance(field.get("cols"), bool)
                or field.get("cols", 0) < 1
            ):
                raise ValueError("Carey source-table base field has an invalid role or span")
            span_total += int(field["cols"])
        if span_total != len(columns):
            raise ValueError("Carey source-table base fields do not cover its declared grid")
        for key in ("title", "columns", "units"):
            if not start_line <= int(header_rows[key]) <= end_line:
                raise ValueError("Carey source-table header locator falls outside its table")
        observed.append(item)
    return observed


def _table_row_roles(table: Mapping[str, object]) -> tuple[dict[int, int], dict[int, int], dict[int, Mapping[str, object]]]:
    continuations: dict[int, int] = {}
    raw_continuations = table.get("continuations")
    if not isinstance(raw_continuations, Mapping):
        raise ValueError("Carey table continuation map is invalid")
    for raw_line, owner in raw_continuations.items():
        try:
            line_number = int(raw_line)
        except (TypeError, ValueError) as exc:
            raise ValueError("Carey table continuation locator is invalid") from exc
        if not isinstance(owner, int) or isinstance(owner, bool):
            raise ValueError("Carey table continuation owner is invalid")
        continuations[line_number] = owner

    group_owner: dict[int, int] = {}
    raw_groups = table.get("groups")
    if not isinstance(raw_groups, list):
        raise ValueError("Carey table group map is invalid")
    for group in raw_groups:
        if not isinstance(group, Mapping):
            raise ValueError("Carey table group entry is invalid")
        heading_line = group.get("heading_line")
        member_ranges = group.get("member_ranges")
        if (
            not isinstance(heading_line, int)
            or isinstance(heading_line, bool)
            or not isinstance(member_ranges, list)
        ):
            raise ValueError("Carey table group locator is invalid")
        for member_range in member_ranges:
            if (
                not isinstance(member_range, list)
                or len(member_range) != 2
                or any(not isinstance(value, int) or isinstance(value, bool) for value in member_range)
                or member_range[1] < member_range[0]
            ):
                raise ValueError("Carey table group member range is invalid")
            for line_number in range(member_range[0], member_range[1] + 1):
                if line_number in group_owner and group_owner[line_number] != heading_line:
                    raise ValueError("Carey source row has conflicting table group owners")
                group_owner[line_number] = heading_line

    note_by_line: dict[int, Mapping[str, object]] = {}
    raw_notes = table.get("notes")
    if not isinstance(raw_notes, list):
        raise ValueError("Carey table note map is invalid")
    for note in raw_notes:
        if not isinstance(note, Mapping):
            raise ValueError("Carey table note entry is invalid")
        start_line = note.get("start_line")
        end_line = note.get("end_line")
        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or end_line < start_line
        ):
            raise ValueError("Carey table note locator is invalid")
        for line_number in range(start_line, end_line + 1):
            if line_number in note_by_line:
                raise ValueError("Carey source line has conflicting note roles")
            note_by_line[line_number] = note
    return continuations, group_owner, note_by_line


def _table_header_fields(
    table: Mapping[str, object], line_number: int
) -> tuple[list[dict[str, object]], list[int]]:
    header_rows = table["header_rows"]
    base_fields = table["base_fields"]
    if not isinstance(header_rows, Mapping) or not isinstance(base_fields, list):
        raise ValueError("Carey table header map is invalid")
    columns = int(header_rows["columns"])
    units = int(header_rows["units"])
    if line_number == columns:
        raw_fields = table.get("base_fields")
        boundary_key = "column_heading_boundaries"
    elif line_number == units:
        raw_fields = table.get("base_fields")
        boundary_key = "unit_heading_boundaries"
    else:
        subcolumns = table.get("subcolumns")
        if not isinstance(subcolumns, Mapping) or line_number != subcolumns.get("line_number"):
            raise ValueError("Carey source line is not a declared table header")
        raw_fields = [{"role": role, "cols": 1} for role in subcolumns.get("column_roles", [])]
        boundary_key = "boundaries"
        table = subcolumns
    boundaries = table.get(boundary_key)
    if not isinstance(raw_fields, list) or not isinstance(boundaries, list):
        raise ValueError("Carey table heading columns are incomplete")
    fields: list[dict[str, object]] = []
    for item in raw_fields:
        if not isinstance(item, Mapping):
            raise ValueError("Carey table heading field is invalid")
        fields.append({"role": str(item["role"]), "cols": int(item["cols"])})
    if len(boundaries) != len(fields) - 1:
        raise ValueError("Carey table heading boundaries do not match its fields")
    return fields, [int(position) for position in boundaries]


def _whitespace_run_around(text: str, position: int) -> tuple[int, int]:
    left = min(max(position, 0), len(text))
    right = left
    while left > 0 and text[left - 1].isspace():
        left -= 1
    while right < len(text) and text[right].isspace():
        right += 1
    return left, right


def _source_table_cuts(
    text: str, boundaries: list[int], *, minimum_gap: int = 2
) -> list[int | None]:
    cuts: list[int | None] = []
    for index, requested in enumerate(boundaries):
        position = min(max(requested, 0), len(text))
        if position == 0 or position >= len(text):
            cuts.append(position)
            continue
        if index == 0:
            # The country column is ragged. Anchor its right edge to the first
            # extent token at or after the printed column, rather than slicing a
            # long country name or shifting the next numeric column left.
            token_start = position
            if not text[token_start].isspace():
                while token_start > 0 and not text[token_start - 1].isspace():
                    token_start -= 1
                token = text[token_start:].split(None, 1)[0]
                if token[:1].isdigit() or token.casefold() in {"unknown.", "undiscovered"}:
                    cuts.append(token_start)
                    continue
                else:
                    token_start = position
            cursor = max(position, token_start)
            limit = min(len(text), requested + 12)
            while cursor < limit:
                if text[cursor].isspace():
                    gap_start, gap_end = _whitespace_run_around(text, cursor)
                    token = text[gap_end:].split(None, 1)[0] if gap_end < len(text) else ""
                    if (
                        gap_end <= requested + 12
                        and (token[:1].isdigit() or token.casefold() in {"unknown.", "undiscovered"})
                    ):
                        cuts.append(gap_end)
                        break
                    cursor = max(cursor + 1, gap_end)
                else:
                    cursor += 1
            if len(cuts) == index + 1:
                continue
        gap_start, gap_end = _whitespace_run_around(text, position)
        if gap_end - gap_start >= minimum_gap:
            cuts.append(position)
        else:
            cuts.append(None)
    return cuts


def _table_cell_descriptors(
    table: Mapping[str, object],
    row: Mapping[str, object],
    role: str,
) -> list[dict[str, object]]:
    line_number = int(row["line_number"])
    text = str(row["text"])
    columns = table.get("column_roles")
    if not isinstance(columns, list):
        raise ValueError("Carey table grid columns are invalid")
    column_count = len(columns)
    raw_overrides = table.get("cell_overrides", {})
    if not isinstance(raw_overrides, Mapping):
        raise ValueError("Carey table cell overrides are invalid")
    override = raw_overrides.get(str(line_number))
    if override is not None:
        if not isinstance(override, list) or not override:
            raise ValueError("Carey table cell override has no descriptors")
        descriptors: list[dict[str, object]] = []
        cursor = 0
        column = 1
        for item in override:
            if not isinstance(item, Mapping) or set(item) != {
                "role", "source_roles", "start_column", "cols", "start", "end"
            }:
                raise ValueError("Carey table cell override descriptor shape differs")
            start = item.get("start")
            end = item.get("end")
            start_column = item.get("start_column")
            cols = item.get("cols")
            source_roles = item.get("source_roles")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start != cursor
                or end < start
                or end > len(text)
                or not isinstance(start_column, int)
                or isinstance(start_column, bool)
                or start_column != column
                or not isinstance(cols, int)
                or isinstance(cols, bool)
                or cols < 1
                or not isinstance(source_roles, list)
                or any(not isinstance(value, str) or not value for value in source_roles)
            ):
                raise ValueError("Carey table cell override is noncontiguous or outside its grid")
            descriptors.append(dict(item))
            cursor = end
            column += cols
        if cursor != len(text) or column - 1 != column_count:
            raise ValueError("Carey table cell override does not cover source text and grid")
        return descriptors
    if role in {"table-superheading", "group-heading", "table-note", "footnote"}:
        cell_role = "table-heading" if role == "table-superheading" else role
        return [{"role": cell_role, "source_roles": [], "start_column": 1, "cols": column_count, "start": 0, "end": len(text)}]

    if role in {"column-headings", "unit-headings", "column-subheadings"}:
        header_fields, boundaries = _table_header_fields(table, line_number)
        cuts = boundaries
    elif line_number in {int(value) for value in table.get("uncertain_layout_lines", [])}:
        boundaries = [int(value) for value in table.get("column_boundaries", [])]
        if not boundaries:
            raise ValueError("Carey uncertain-layout line has no declared columns")
        return [
            {"role": "country", "source_roles": ["country"], "start_column": 1, "cols": 1, "start": 0, "end": boundaries[0]},
            {"role": "unresolved-layout", "source_roles": list(table.get("column_roles", []))[1:], "start_column": 2, "cols": column_count - 1, "start": boundaries[0], "end": len(text)},
        ]
    elif line_number in {int(value) for value in table.get("wide_country_lines", [])}:
        boundaries = [int(value) for value in table.get("column_boundaries", [])]
        if not boundaries:
            raise ValueError("Carey wide-label line has no declared columns")
        return [
            {"role": "country", "source_roles": ["country"], "start_column": 1, "cols": column_count - 1, "start": 0, "end": boundaries[-1]},
            {"role": "religion", "source_roles": ["religion"], "start_column": column_count, "cols": 1, "start": boundaries[-1], "end": len(text)},
        ]
    else:
        subcolumns = table.get("subcolumns")
        if isinstance(subcolumns, Mapping) and line_number > int(subcolumns.get("line_number", 0)):
            fields = [{"role": value, "cols": 1} for value in subcolumns.get("column_roles", [])]
            boundaries = [int(value) for value in subcolumns.get("body_boundaries", [])]
        else:
            fields = table.get("base_fields")
            boundaries = [int(value) for value in table.get("column_boundaries", [])]
        if not isinstance(fields, list):
            raise ValueError("Carey table body fields are invalid")
        header_fields = [
            {"role": str(item["role"]), "cols": int(item["cols"])}
            for item in fields
            if isinstance(item, Mapping)
        ]
        cuts = _source_table_cuts(
            text,
            boundaries,
            minimum_gap=(
                1
                if isinstance(subcolumns, Mapping)
                and line_number > int(subcolumns.get("line_number", 0))
                else 2
            ),
        )

    if len(cuts) != len(header_fields) - 1:
        raise ValueError("Carey table source line has inconsistent column boundaries")
    cell_groups: list[dict[str, object]] = []
    group_start = 0
    source_start = 0
    column_start = 1
    for index, field in enumerate(header_fields):
        if not isinstance(field, Mapping):
            raise ValueError("Carey table field descriptor is invalid")
        role_name = str(field["role"])
        span = int(field["cols"])
        split = index == len(header_fields) - 1 or cuts[index] is not None
        if not split:
            continue
        end = len(text) if index == len(header_fields) - 1 else min(len(text), int(cuts[index]))
        members = header_fields[group_start : index + 1]
        source_roles = [str(item["role"]) for item in members]
        grid_span = sum(int(item["cols"]) for item in members)
        if len(members) == 1:
            cell_role = role_name
        elif set(source_roles) == {"length", "breadth"}:
            cell_role = "extent-qualifier"
        else:
            cell_role = "ambiguous-span"
        cell_groups.append(
            {
                "role": cell_role,
                "source_roles": source_roles,
                "start_column": column_start,
                "cols": grid_span,
                "start": source_start,
                "end": end,
            }
        )
        column_start += grid_span
        source_start = end
        group_start = index + 1
    if column_start - 1 != column_count:
        raise ValueError("Carey table generated cell spans do not cover the declared column grid")
    return cell_groups


def _table_row_role(table: Mapping[str, object], line_number: int, note: Mapping[str, object] | None) -> str:
    header_rows = table.get("header_rows")
    if isinstance(header_rows, Mapping):
        if line_number == header_rows.get("title"):
            return "table-superheading"
        if line_number == header_rows.get("columns"):
            return "column-headings"
        if line_number == header_rows.get("units"):
            return "unit-headings"
    subcolumns = table.get("subcolumns")
    if isinstance(subcolumns, Mapping) and line_number == subcolumns.get("line_number"):
        return "column-subheadings"
    if note is not None:
        return str(note.get("role", "table-note"))
    groups = table.get("groups")
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, Mapping) and line_number == group.get("heading_line"):
                return str(group.get("row_role", "group-heading"))
    continuations, _, _ = _table_row_roles(table)
    if line_number in continuations:
        return "continuation"
    return "data"


def _table_header_targets(table: Mapping[str, object]) -> dict[str, list[str]]:
    header_rows = table["header_rows"]
    fields = table["base_fields"]
    if not isinstance(header_rows, Mapping) or not isinstance(fields, list):
        raise ValueError("Carey table heading targets are invalid")
    targets: dict[str, list[str]] = {}
    column = 1
    for field in fields:
        if not isinstance(field, Mapping):
            raise ValueError("Carey table heading target field is invalid")
        role = str(field["role"])
        targets[role] = [
            f"#{table['work_id']}-cell-{int(header_rows['columns']):05d}-c{column:02d}",
            f"#{table['work_id']}-cell-{int(header_rows['units']):05d}-c{column:02d}",
        ]
        column += int(field["cols"])
    subcolumns = table.get("subcolumns")
    if isinstance(subcolumns, Mapping):
        sub_column = 1
        for role in subcolumns.get("column_roles", []):
            targets[str(role)] = [f"#{table['work_id']}-cell-{int(subcolumns['line_number']):05d}-c{sub_column:02d}"]
            sub_column += 1
    return targets


def _table_qualifier(text: str) -> bool:
    lowered = text.casefold()
    return any(
        term in lowered
        for term in ("undiscovered", "in compass.", "in number.", "unknown.", "a cluster of isles.")
    )


def _source_table_accounting(
    work: Mapping[str, object],
    rows: list[tuple[str, str]],
    units: list[dict[str, object]],
) -> list[dict[str, object]]:
    work_id = str(work["work_id"])
    block_by_line = {
        int(row["line_number"]): int(unit["block_number"])
        for unit in units
        if unit["kind"] == "block"
        for row in unit["rows"]
    }
    output: list[dict[str, object]] = []
    for table in _source_tables(work):
        continuations, group_owner, note_by_line = _table_row_roles(table)
        table_rows: list[dict[str, object]] = []
        column_count = len(table["column_roles"])
        for line_number in range(int(table["start_line"]), int(table["end_line"]) + 1):
            text, ending = rows[line_number - 1]
            note = note_by_line.get(line_number)
            if text == "":
                row_role = "source-blank-line"
                descriptors = [
                    {
                        "role": "blank-line",
                        "source_roles": [],
                        "start_column": 1,
                        "cols": column_count,
                        "start": 0,
                        "end": 0,
                    }
                ]
            else:
                row_role = _table_row_role(table, line_number, note)
                descriptors = _table_cell_descriptors(
                    table,
                    {"line_number": line_number, "text": text},
                    row_role,
                )

            cells: list[dict[str, object]] = []
            for descriptor in descriptors:
                start = int(descriptor["start"])
                end = int(descriptor["end"])
                value = text[start:end]
                cell_type = (
                    "empty-field"
                    if value.strip() == ""
                    else "layout-uncertain"
                    if descriptor["role"] == "unresolved-layout"
                    else "source-qualifier"
                    if _table_qualifier(value)
                    else None
                )
                cells.append(
                    {
                        "cell_id": (
                            f"{work_id}-cell-{line_number:05d}-c{int(descriptor['start_column']):02d}"
                        ),
                        "role": descriptor["role"],
                        "source_roles": list(descriptor["source_roles"]),
                        "start_column": descriptor["start_column"],
                        "cols": descriptor["cols"],
                        "source_start": start,
                        "source_end": end,
                        "source_text_sha256": _sha(value.encode("utf-8")),
                        "type": cell_type,
                    }
                )
            block_number = block_by_line.get(line_number)
            if text != "" and block_number is None:
                raise ValueError(f"Carey source table line {line_number} has no source-block selector")
            note_target = None
            note_role = None
            if note is not None:
                note_role = str(note.get("role", "table-note"))
                note_target = note.get("target_line", note.get("attach_to", "table"))
                if not (
                    note_target == "table"
                    or isinstance(note_target, int) and not isinstance(note_target, bool)
                ):
                    raise ValueError(f"Carey source table note target is invalid at line {line_number}")
            table_rows.append(
                {
                    "line_number": line_number,
                    "row_id": f"{work_id}-row-{line_number:05d}",
                    "row_role": row_role,
                    "line_ending": ending,
                    "source_text_sha256": _sha(text.encode("utf-8")),
                    "block_id": (
                        f"{work_id}-block-{block_number:05d}"
                        if block_number is not None
                        else None
                    ),
                    "group_owner_line": group_owner.get(line_number),
                    "continuation_owner_line": continuations.get(line_number),
                    "note_role": note_role,
                    "note_target": note_target,
                    "cells": cells,
                }
            )
        output.append(
            {
                "table_id": table["table_id"],
                "heading_line": table["heading_line"],
                "start_line": table["start_line"],
                "end_line": table["end_line"],
                "header_rows": table["header_rows"],
                "column_roles": table["column_roles"],
                "row_count": len(table_rows),
                "rows": table_rows,
            }
        )
    return output


def _append_table_marker(
    segment: etree._Element,
    value: str,
    line_number: int,
    note_targets: Mapping[int, tuple[str, str]],
) -> None:
    marker = note_targets.get(line_number)
    if marker is None or marker[0] not in value:
        segment.text = value
        return
    literal, target_line = marker
    before, after = value.split(literal, 1)
    segment.text = before
    reference = etree.SubElement(
        segment,
        f"{{{TEI_NS}}}ref",
        type="table-footnote-marker",
        target=f"#{segment.get('data-table-id', '')}-row-{target_line:05d}",
    )
    # data-table-id is an internal construction aid and is removed before output.
    reference.text = literal
    reference.tail = after
    del segment.attrib["data-table-id"]


def _append_table(
    parent: etree._Element,
    work_id: str,
    table: Mapping[str, object],
    rows: list[tuple[str, str]],
    block_by_line: Mapping[int, int],
    block_start_by_line: Mapping[int, int],
) -> None:
    table_id = str(table["table_id"])
    start_line = int(table["start_line"])
    end_line = int(table["end_line"])
    columns = table["column_roles"]
    column_count = len(columns)
    table_element = etree.SubElement(
        parent,
        f"{{{TEI_NS}}}table",
        type="source-located-table",
        n=table_id,
        rows=str(end_line - start_line + 1),
        cols=str(column_count),
        corresp=f"#{work_id}-heading-{int(table['heading_line']):05d}",
    )
    table_element.set(XML_ID, f"{work_id}-table-{table_id}")
    continuations, group_owner, note_by_line = _table_row_roles(table)
    header_targets = _table_header_targets({**table, "work_id": work_id})
    footnote_markers: dict[int, tuple[str, str]] = {}
    for note in table.get("notes", []):
        if isinstance(note, Mapping) and isinstance(note.get("marker_line"), int) and isinstance(note.get("marker"), str):
            footnote_markers[int(note["marker_line"])] = (
                str(note["marker"]),
                f"{work_id}-row-{int(note['start_line']):05d}",
            )

    for line_number in range(start_line, end_line + 1):
        text, ending = rows[line_number - 1]
        row_id = f"{work_id}-row-{line_number:05d}"
        row_type = "source-blank-line" if text == "" else _table_row_role(table, line_number, note_by_line.get(line_number))
        row = etree.SubElement(
            table_element,
            f"{{{TEI_NS}}}row",
            role=row_type,
            n=str(line_number),
        )
        row.set(XML_ID, row_id)
        if text == "":
            cell = etree.SubElement(
                row,
                f"{{{TEI_NS}}}cell",
                role="blank-line",
                rend="empty-field",
                n="1",
                cols=str(column_count),
                **{XML_ID: f"{work_id}-cell-{line_number:05d}-c01"},
            )
            etree.SubElement(
                cell,
                f"{{{TEI_NS}}}space",
                type="source-blank-line",
                unit="line",
                quantity="1",
                n=str(line_number),
                subtype=ending,
                **{XML_ID: f"{work_id}-blank-{line_number:05d}"},
            )
            continue

        block_number = block_by_line.get(line_number)
        if block_number is None:
            raise ValueError(f"Carey table row {line_number} has no source-block accounting selector")
        row_analyses = [f"#{work_id}-block-{block_number:05d}"]
        if line_number in group_owner:
            row_analyses.append(f"#{work_id}-row-{group_owner[line_number]:05d}")
        note = note_by_line.get(line_number)
        if note is not None:
            target = note.get("target_line", note.get("attach_to", "table"))
            row_analyses.append(
                f"#{work_id}-row-{int(target):05d}"
                if isinstance(target, int) and not isinstance(target, bool)
                else f"#{work_id}-table-{table_id}"
            )
        row.set("ana", " ".join(row_analyses))
        continuation_owner = continuations.get(line_number)
        if continuation_owner is not None:
            row.set("corresp", f"#{work_id}-row-{continuation_owner:05d}")

        descriptors = _table_cell_descriptors(table, {"line_number": line_number, "text": text}, row_type)
        for descriptor in descriptors:
            start = int(descriptor["start"])
            end = int(descriptor["end"])
            source_roles = [str(role) for role in descriptor.get("source_roles", [])]
            role_name = str(descriptor["role"])
            cell_attributes: dict[str, str] = {
                "role": role_name,
                "n": str(descriptor["start_column"]),
                XML_ID: f"{work_id}-cell-{line_number:05d}-c{int(descriptor['start_column']):02d}",
            }
            if int(descriptor["cols"]) > 1:
                cell_attributes["cols"] = str(descriptor["cols"])
            value = text[start:end]
            if value.strip() == "":
                cell_attributes["rend"] = "empty-field"
            elif role_name == "unresolved-layout":
                cell_attributes["rend"] = "layout-uncertain"
            elif _table_qualifier(value):
                cell_attributes["rend"] = "source-qualifier"
            references: list[str] = []
            for source_role in source_roles:
                references.extend(header_targets.get(source_role, []))
            if references:
                cell_attributes["ana"] = " ".join(dict.fromkeys(references))
            cell = etree.SubElement(row, f"{{{TEI_NS}}}cell", **cell_attributes)
            if block_start_by_line.get(line_number) == block_number and int(descriptor["start_column"]) == 1:
                anchor = etree.SubElement(cell, f"{{{TEI_NS}}}anchor", type="source-block-start")
                anchor.set(XML_ID, f"{work_id}-block-{block_number:05d}")
            if continuation_owner is not None and value.strip() != "":
                cell.set(
                    "corresp",
                    f"#{work_id}-cell-{continuation_owner:05d}-c{int(descriptor['start_column']):02d}",
                )
            if start >= end:
                continue
            segment = etree.SubElement(
                cell,
                f"{{{TEI_NS}}}seg",
                type="source-line-fragment",
                n=f"{line_number}:{start}-{end}",
                subtype=ending,
            )
            segment.set(XML_ID, f"{work_id}-fragment-{line_number:05d}-{start:04d}-{end:04d}")
            marker = footnote_markers.get(line_number)
            if marker is not None and marker[0] in value:
                before, after = value.split(marker[0], 1)
                segment.text = before
                reference = etree.SubElement(
                    segment,
                    f"{{{TEI_NS}}}ref",
                    type="table-footnote-marker",
                    target=f"#{marker[1]}",
                )
                reference.text = marker[0]
                reference.tail = after
            else:
                segment.text = value


def _tei(
    work: Mapping[str, object],
    content: bytes,
    source_correction_attestation: str,
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

    source_tables = _source_tables(work)
    tables_by_line: dict[int, Mapping[str, object]] = {}
    for table in source_tables:
        start_line = int(table["start_line"])
        end_line = int(table["end_line"])
        for line_number in range(start_line, end_line + 1):
            if line_number in tables_by_line:
                raise ValueError("Carey source-table ranges overlap")
            tables_by_line[line_number] = table
    block_by_line = {
        int(row["line_number"]): int(unit["block_number"])
        for unit in units
        if unit["kind"] == "block"
        for row in unit["rows"]
    }
    block_start_by_line = {
        int(unit["rows"][0]["line_number"]): int(unit["block_number"])
        for unit in units
        if unit["kind"] == "block"
    }
    emitted_tables: set[str] = set()

    for unit in units:
        if unit["kind"] == "blank":
            row = unit["row"]
            if int(row["line_number"]) in tables_by_line:
                continue
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
        table_members = {
            str(tables_by_line[line_number]["table_id"])
            for line_number in (int(row["line_number"]) for row in block_rows)
            if line_number in tables_by_line
        }
        if table_members:
            table = tables_by_line[first_line] if first_line in tables_by_line else None
            if (
                len(table_members) != 1
                or table is None
                or any(int(row["line_number"]) not in tables_by_line for row in block_rows)
            ):
                raise ValueError(f"Carey table range splits a source block at line {first_line}")
            start_line = int(table["start_line"])
            if first_line == start_line:
                table_id = str(table["table_id"])
                _append_table(
                    current_parent(),
                    work_id,
                    table,
                    rows,
                    block_by_line,
                    block_start_by_line,
                )
                emitted_tables.add(table_id)
            continue
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
            _append_lines(head, work_id, block_rows)
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
            _append_lines(title, work_id, title_rows)
        else:
            paragraph = etree.SubElement(
                block,
                f"{{{TEI_NS}}}p",
                n=str(first_line),
            )
            paragraph.set(XML_ID, f"{work_id}-unit-{first_line:05d}")
            _append_lines(paragraph, work_id, block_rows)

    if emitted_tables != {str(table["table_id"]) for table in source_tables}:
        raise ValueError("Carey converter did not emit every mapped source table")

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
        raise ValueError(f"LIB-071 selected retained source drift: {work['work_id']}")
    rows = _line_rows(content)
    units = _units(rows)
    source_table_ledger = _source_table_accounting(work, rows, units)
    table_role_by_line = {
        int(row["line_number"]): f"source-table-{table['table_id']}-{row['row_role']}"
        for table in source_table_ledger
        for row in table["rows"]
    }
    plan = _heading_plan(work, rows, units)
    headings = plan["headings"]
    title_owner = plan["title_owner"]
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
                    "structural_role": table_role_by_line.get(
                        int(row["line_number"]), "blank-line"
                    ),
                    "block_id": None,
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
                    "structural_role": table_role_by_line.get(
                        line_number,
                        "explicit-source-heading"
                        if line_number in headings
                        else "source-attached-title"
                        if line_number in title_owner
                        else "source-block-text",
                    ),
                    "block_id": block_id,
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
    }
    if source_table_ledger:
        work_row["source_tables"] = source_table_ledger
    schema_path = source_manifest.authority_path("source-accountability-schema")
    accountability: dict[str, object] = {
        "contract": (
            "ocd-selected-source-accountability-v3"
            if source_table_ledger
            else "ocd-selected-source-accountability-v2"
        ),
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
        raise ValueError("LIB-071 selected profile unresolved evidence is invalid")
    readme = source_manifest.authority_path("source-local-readme").read_bytes()
    return {
        "content.tei.xml": _tei(
            work,
            content,
            str(profile["source_correction_attestation"]),
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
