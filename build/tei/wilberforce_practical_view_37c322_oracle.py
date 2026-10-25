"""Independent source and TEI oracle for ticket 37c-322.

This validator owns a separate source scanner and TEI traversal. It does not
import the LIB-072 producer or the shared Project Gutenberg oracle.
"""

from __future__ import annotations

import ast
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-lib072-37c-322-readable-italic-independent-oracle"
ORACLE_VERSION = "2"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_ID = "wilberforce-practical-view"
SOURCE_ID = "gutenberg-37c-322-pg25709"
SOURCE_PATH = "raw/gutenberg/pg25709.txt"
SOURCE_SIZE = 659285
SOURCE_SHA256 = "995ff74ac2c819b526d4874878507bb85e1141f7e5b35a388c44846a963d6c96"
SOURCE_URL = "https://www.gutenberg.org/ebooks/25709"
WORK_TITLE = "A Practical View of the Prevailing Religious System of Professed Christians"
WITNESS_DESCRIPTION = (
    "Exact retained Project Gutenberg text member PG25709; treated as one source witness while edition, part, and constituent-work boundaries remain unresolved."
)
PROFILE_ID = "selected-proofread-37c-322-v3"
HEADING_MAP_SHA256 = "3dd00380a419994645f8ae6513262bc683777288ddc2e793efed26db2b42d898"
SOURCE_CORRECTION_ATTESTATION = (
    "The ticket-bound retained Project Gutenberg member was positively identified as human-proofread and carries Distributed Proofreaders attribution. This technical reconstruction does not independently audit the provider's individual corrections."
)
NONACCEPTANCE_DISCLAIMER = (
    "Nonaccepted technical candidate. Rights clearance, human acceptance, and publication authorization are separate and have not been performed."
)
ENCODING_POLICY = (
    "Balanced Project Gutenberg underscore delimiters are removed from readable text; each verified interior is encoded as hi rend=italic and identified by exact source locators and a raw source-slice digest. Underscores internal to ASCII alphanumeric identifiers remain literal text. Multiline emphasis is split at retained source lines with continuations linked to the opening fragment."
)
ACCOUNTABILITY_BLOCK_MAPPING = (
    "blank-line-delimited source blocks retained in order; source-located headings and mapped title attachments encoded; every underscore classified as literal source text or emphasis delimiter; emphasis interiors encoded as readable italics and removed delimiters located and reversible"
)
MARKUP_POLICY: dict[str, object] = {
    "contract": "ocd-pg-underscore-emphasis-source-slices-v2",
    "marker_character": "_",
    "expected_marker_count": 1304,
    "expected_delimiter_count": 1304,
    "expected_literal_marker_count": 0,
    "expected_span_count": 652,
    "maximum_interior_character_count": 566,
    "pairing_scope": "classify ASCII alphanumeric-internal underscores as literal; pair remaining emphasis delimiters within each blank-line-delimited source block",
    "classification_rule": "An underscore between ASCII letters or digits is literal source text and is not a Project Gutenberg emphasis delimiter. Other underscore characters are emphasis delimiters and must form balanced, nonempty pairs within one source block.",
    "representation": "Omit each paired outer delimiter from readable TEI; encode its exact interior as hi rend=italic, split only at retained source-line boundaries, and link continuation fragments to the opening fragment. Preserve internal literal underscores in the readable text.",
}
FORBIDDEN_IMPORTS = [
    "build.tei.gutenberg_evangelical_lib072_selected_reconstruction",
    "build.tei.gutenberg_proofread_selected_oracle",
    "build.tei.gutenberg_evangelical_lib072_reconstruction",
    "build.tei.gutenberg_evangelical_lib072_oracle",
]
ACCOUNTABILITY_MARKUP = {
    "contract": "ocd-pg-underscore-emphasis-source-slices-v2",
    "marker_character": "_",
    "marker_count": 1304,
    "delimiter_count": 1304,
    "literal_underscore_count": 0,
    "span_count": 652,
    "maximum_interior_character_count": 566,
    "pairing_scope": MARKUP_POLICY["pairing_scope"],
    "classification_rule": MARKUP_POLICY["classification_rule"],
    "representation": MARKUP_POLICY["representation"],
}
EOL_BYTES = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}


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

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _source_rows(content: bytes) -> list[dict[str, object]]:
    """Read only CR/LF boundaries and retain absolute byte and line locations."""
    content.decode("utf-8")
    rows: list[dict[str, object]] = []
    position = 0
    line_number = 1
    while position < len(content):
        cr = content.find(b"\r", position)
        lf = content.find(b"\n", position)
        candidates = [value for value in (cr, lf) if value >= 0]
        if not candidates:
            rows.append(
                {
                    "line_number": line_number,
                    "text": content[position:].decode("utf-8"),
                    "ending": "none",
                    "byte_start": position,
                    "byte_end": len(content),
                }
            )
            position = len(content)
            break
        stop = min(candidates)
        text = content[position:stop].decode("utf-8")
        if content[stop : stop + 2] == b"\r\n":
            ending, next_position = "crlf", stop + 2
        elif content[stop : stop + 1] == b"\r":
            ending, next_position = "cr", stop + 1
        else:
            ending, next_position = "lf", stop + 1
        rows.append(
            {
                "line_number": line_number,
                "text": text,
                "ending": ending,
                "byte_start": position,
                "byte_end": stop,
            }
        )
        position = next_position
        line_number += 1
    rebuilt = b"".join(
        str(row["text"]).encode("utf-8") + EOL_BYTES[str(row["ending"])]
        for row in rows
    )
    if rebuilt != content:
        raise ValueError("37c-322 oracle source row scan is not byte-lossless")
    return rows


def _source_units(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    block_number = 0
    for row in rows:
        if row["text"] == "":
            if active:
                block_number += 1
                units.append(
                    {"kind": "block", "block_number": block_number, "rows": active}
                )
                active = []
            units.append({"kind": "blank", "row": row})
        else:
            active.append(row)
    if active:
        block_number += 1
        units.append({"kind": "block", "block_number": block_number, "rows": active})
    return units


def _heading_plan(
    profile: Mapping[str, object],
    rows: list[dict[str, object]],
    units: list[dict[str, object]],
) -> dict[str, object]:
    works = profile.get("works")
    if not isinstance(works, list) or len(works) != 1 or not isinstance(works[0], dict):
        raise ValueError("37c-322 profile work inventory is invalid")
    raw_map = works[0].get("heading_map")
    if not isinstance(raw_map, list) or not raw_map:
        raise ValueError("37c-322 source-located heading map is absent")
    if _sha(_canonical(raw_map)) != HEADING_MAP_SHA256:
        raise ValueError("37c-322 profile heading map differs from oracle-owned locators")
    row_by_line = {int(row["line_number"]): row for row in rows}
    block_for_line: dict[int, dict[str, object]] = {}
    unit_index_by_block: dict[int, int] = {}
    for index, unit in enumerate(units):
        if unit["kind"] != "block":
            continue
        block_no = int(unit["block_number"])
        for row in unit["rows"]:
            block_for_line[int(row["line_number"])] = unit
        unit_index_by_block[block_no] = index

    headings: dict[int, Mapping[str, object]] = {}
    title_owner: dict[int, int] = {}
    title_rows_by_heading: dict[int, list[dict[str, object]]] = {}
    active_levels: dict[int, int] = {}
    previous_line = 0
    expected_keys = {
        "line_number",
        "source_text",
        "level",
        "parent_line",
        "attached_title_lines",
    }
    for item in raw_map:
        if not isinstance(item, Mapping) or set(item) != expected_keys:
            raise ValueError("37c-322 heading entry shape is invalid")
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
            or (parent_line is not None and not isinstance(parent_line, int))
        ):
            raise ValueError("37c-322 heading locator or level is invalid")
        if row_by_line[line_number]["text"] != item.get("source_text"):
            raise ValueError(f"37c-322 heading text drift at line {line_number}")
        unit = block_for_line.get(line_number)
        if unit is None or len(unit["rows"]) != 1:
            raise ValueError(f"37c-322 heading is not an isolated source block at {line_number}")
        if level == 1:
            if parent_line is not None:
                raise ValueError("37c-322 level-one heading declares a parent")
            active_levels.clear()
        elif parent_line is None or active_levels.get(level - 1) != parent_line:
            raise ValueError(f"37c-322 heading parent is unresolved at line {line_number}")
        for old_level in tuple(active_levels):
            if old_level >= level:
                del active_levels[old_level]
        if len(active_levels) != level - 1:
            raise ValueError(f"37c-322 heading level gap at line {line_number}")

        raw_titles = item.get("attached_title_lines")
        if not isinstance(raw_titles, list):
            raise ValueError("37c-322 attached title inventory is invalid")
        title_rows: list[dict[str, object]] = []
        for title in raw_titles:
            if not isinstance(title, Mapping) or set(title) != {"line_number", "source_text"}:
                raise ValueError("37c-322 attached title entry is invalid")
            title_line = title.get("line_number")
            if (
                not isinstance(title_line, int)
                or isinstance(title_line, bool)
                or title_line not in row_by_line
                or title_line in title_owner
                or title_line in headings
                or row_by_line[title_line]["text"] != title.get("source_text")
            ):
                raise ValueError(f"37c-322 attached title source drift at heading {line_number}")
            title_rows.append(row_by_line[title_line])
        if title_rows:
            title_numbers = [int(row["line_number"]) for row in title_rows]
            if title_numbers != list(range(title_numbers[0], title_numbers[0] + len(title_numbers))):
                raise ValueError("37c-322 attached title lines are not contiguous")
            first_block_index = unit_index_by_block[int(unit["block_number"])]
            following = next(
                (
                    candidate
                    for candidate in units[first_block_index + 1 :]
                    if candidate["kind"] == "block"
                ),
                None,
            )
            if following is None or [
                int(row["line_number"]) for row in following["rows"]
            ] != title_numbers:
                raise ValueError(f"37c-322 attached title is detached at heading {line_number}")
            for title_line in title_numbers:
                title_owner[title_line] = line_number
        headings[line_number] = item
        title_rows_by_heading[line_number] = title_rows
        active_levels[level] = line_number
        previous_line = line_number
    return {
        "headings": headings,
        "title_owner": title_owner,
        "title_rows_by_heading": title_rows_by_heading,
    }


def _ascii_alphanumeric(character: str) -> bool:
    return len(character) == 1 and character.isascii() and character.isalnum()


def _literal_underscore_census(
    rows: list[dict[str, object]],
    units: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Independently locate underscores inside ASCII alphanumeric tokens."""
    result: list[dict[str, object]] = []
    for unit in units:
        if unit["kind"] != "block":
            continue
        for row in unit["rows"]:
            text = str(row["text"])
            for index, character in enumerate(text):
                if character != "_":
                    continue
                previous = text[index - 1] if index else ""
                following = text[index + 1] if index + 1 < len(text) else ""
                if previous == "_" or following == "_":
                    raise ValueError(
                        f"adjacent underscore sequence is ambiguous at {row['line_number']}:{index + 1}"
                    )
                if _ascii_alphanumeric(previous) and _ascii_alphanumeric(following):
                    byte_offset = int(row["byte_start"]) + len(
                        text[:index].encode("utf-8")
                    )
                    result.append(
                        {
                            "line_number": row["line_number"],
                            "column": index + 1,
                            "byte_offset": byte_offset,
                            "character": "_",
                            "sha256": _sha(b"_"),
                        }
                    )
    return result


def _underscore_census(
    content: bytes,
    rows: list[dict[str, object]],
    units: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Classify literal identifier underscores, then bind delimiter slices."""
    row_by_line = {int(row["line_number"]): row for row in rows}
    result: list[dict[str, object]] = []
    marker_count = 0
    delimiter_count = 0
    for unit in units:
        if unit["kind"] != "block":
            continue
        block_number = int(unit["block_number"])
        block_rows = unit["rows"]
        characters: list[str] = []
        locations: list[tuple[int, int] | None] = []
        for index, row in enumerate(block_rows):
            if index:
                characters.append("\n")
                locations.append(None)
            for column, character in enumerate(str(row["text"]), 1):
                characters.append(character)
                locations.append((int(row["line_number"]), column))
        logical = "".join(characters)
        open_at: int | None = None
        for position, character in enumerate(logical):
            if character != "_":
                continue
            marker_count += 1
            previous = logical[position - 1] if position else ""
            following = logical[position + 1] if position + 1 < len(logical) else ""
            if previous == "_" or following == "_":
                location = locations[position]
                assert location is not None
                raise ValueError(
                    f"adjacent underscore sequence is ambiguous at {location[0]}:{location[1]}"
                )
            previous_location = locations[position - 1] if position else None
            following_location = (
                locations[position + 1] if position + 1 < len(locations) else None
            )
            marker_location = locations[position]
            if (
                previous_location is not None
                and following_location is not None
                and marker_location is not None
                and previous_location[0] == marker_location[0] == following_location[0]
                and _ascii_alphanumeric(previous)
                and _ascii_alphanumeric(following)
            ):
                continue
            delimiter_count += 1
            if open_at is None:
                open_at = position
                continue
            interior = logical[open_at + 1 : position]
            if not interior.strip():
                opening = locations[open_at]
                raise ValueError(
                    f"empty or ambiguous source underscore span at {opening[0]}:{opening[1]}"
                )
            opening = locations[open_at]
            closing = locations[position]
            if opening is None or closing is None:
                raise ValueError("37c-322 underscore marker maps to a line boundary")
            start_line, start_column = opening
            end_line, end_column = closing
            line_numbers = list(range(start_line, end_line + 1))
            fragments: list[dict[str, object]] = []
            for part_index, line_number in enumerate(line_numbers, 1):
                row = row_by_line[line_number]
                text = str(row["text"])
                first_column = start_column + 1 if line_number == start_line else 1
                last_column = end_column - 1 if line_number == end_line else len(text)
                if first_column > last_column:
                    raise ValueError(
                        f"empty emphasis continuation at {line_number}:{first_column}"
                    )
                fragment_text = text[first_column - 1 : last_column]
                fragments.append(
                    {
                        "line_number": line_number,
                        "start_column": first_column,
                        "end_column": last_column,
                        "part_index": part_index,
                        "part_count": len(line_numbers),
                        "text_sha256": _sha(fragment_text.encode("utf-8")),
                    }
                )
            start_row = row_by_line[start_line]
            end_row = row_by_line[end_line]
            start_byte = int(start_row["byte_start"]) + len(
                str(start_row["text"][: start_column - 1]).encode("utf-8")
            )
            end_byte = int(end_row["byte_start"]) + len(
                str(end_row["text"][:end_column]).encode("utf-8")
            )
            source_slice = content[start_byte:end_byte]
            if source_slice[:1] != b"_" or source_slice[-1:] != b"_":
                raise ValueError("37c-322 delimiter source slice lost an endpoint")
            span_number = len(result) + 1
            result.append(
                {
                    "span_id": f"{WORK_ID}-underscore-{span_number:04d}",
                    "block_id": f"{WORK_ID}-block-{block_number:05d}",
                    "start_line": start_line,
                    "start_column": start_column,
                    "end_line": end_line,
                    "end_column": end_column,
                    "logical_character_count": len(interior) + 2,
                    "interior_character_count": len(interior),
                    "physical_byte_count": len(source_slice),
                    "source_sha256": _sha(source_slice),
                    "source_slice_byte_start": start_byte,
                    "source_slice_byte_end": end_byte,
                    "opening_delimiter": {
                        "line_number": start_line,
                        "column": start_column,
                        "byte_offset": start_byte,
                        "character": "_",
                        "sha256": _sha(b"_"),
                    },
                    "closing_delimiter": {
                        "line_number": end_line,
                        "column": end_column,
                        "byte_offset": end_byte - 1,
                        "character": "_",
                        "sha256": _sha(b"_"),
                    },
                    "fragments": fragments,
                }
            )
            open_at = None
        if open_at is not None:
            location = locations[open_at]
            assert location is not None
            raise ValueError(
                f"unmatched source underscore in block {block_number} at {location[0]}:{location[1]}"
            )
    literal_markers = _literal_underscore_census(rows, units)
    if (
        marker_count != 1304
        or delimiter_count != 1304
        or len(literal_markers) != 0
        or len(result) != 652
    ):
        raise ValueError(
            "37c-322 underscore classification drifted "
            f"({marker_count} markers, {delimiter_count} delimiters, "
            f"{len(literal_markers)} literals, {len(result)} spans)"
        )
    if max(int(span["interior_character_count"]) for span in result) != 566:
        raise ValueError("37c-322 longest source underscore span is not 566 characters")
    return result


def _expected_accountability(
    rows: list[dict[str, object]],
    units: list[dict[str, object]],
    plan: Mapping[str, object],
    spans: list[dict[str, object]],
    literal_markers: list[dict[str, object]],
) -> dict[str, object]:
    headings = plan["headings"]
    title_owner = plan["title_owner"]
    span_ids_by_line: dict[int, list[str]] = {}
    spans_by_block: dict[str, list[dict[str, object]]] = {}
    for span in spans:
        block_id = str(span["block_id"])
        spans_by_block.setdefault(block_id, []).append(span)
        for fragment in span["fragments"]:
            span_ids_by_line.setdefault(int(fragment["line_number"]), []).append(
                str(span["span_id"])
            )
    line_ending_counts = {
        ending: sum(row["ending"] == ending for row in rows)
        for ending in ("crlf", "lf", "cr", "none")
    }
    line_records: list[dict[str, object]] = []
    block_records: list[dict[str, object]] = []
    for unit in units:
        if unit["kind"] == "blank":
            row = unit["row"]
            line_records.append(
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
        block_id = f"{WORK_ID}-block-{block_number:05d}"
        block_rows = unit["rows"]
        block_line_numbers: list[int] = []
        heading_lines: list[int] = []
        title_lines: list[int] = []
        for row in block_rows:
            line_number = int(row["line_number"])
            block_line_numbers.append(line_number)
            if line_number in headings:
                heading_lines.append(line_number)
            if line_number in title_owner:
                title_lines.append(line_number)
            line_records.append(
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
                    "source_underscore_span_ids": span_ids_by_line.get(line_number, []),
                }
            )
        block_records.append(
            {
                "block_id": block_id,
                "block_number": block_number,
                "start_line": min(block_line_numbers),
                "end_line": max(block_line_numbers),
                "line_count": len(block_line_numbers),
                "heading_lines": heading_lines,
                "attached_title_lines": title_lines,
                "underscore_marker_count": sum(
                    str(row["text"]).count("_") for row in block_rows
                ),
                "underscore_span_count": len(spans_by_block.get(block_id, [])),
            }
        )
    line_records.sort(key=lambda record: int(record["line_number"]))
    return {
        "contract": "ocd-selected-source-accountability-v3",
        "schema": "37c-322.source-accountability.schema.json",
        "profile_id": PROFILE_ID,
        "ticket_id": "37c-322",
        "assigned_work_count": 1,
        "assigned_member_count": 1,
        "adjacent_member_count": 0,
        "adjacent_inventory_scope": "not enumerated; only the exact source member declared in this ticket-bound SourceManifest is in scope",
        "source_members": [
            {
                "work_id": WORK_ID,
                "path": SOURCE_PATH,
                "bytes": SOURCE_SIZE,
                "sha256": SOURCE_SHA256,
                "disposition": "included in full as the one primary-source member in this ticket-bound SourceManifest",
            }
        ],
        "adjacent_retained_member_accounting": [],
        "works": [
            {
                "ticket_id": "37c-322",
                "work_id": WORK_ID,
                "source_path": SOURCE_PATH,
                "source_sha256": SOURCE_SHA256,
                "line_count": len(rows),
                "nonblank_line_count": sum(bool(row["text"]) for row in rows),
                "blank_line_count": sum(row["text"] == "" for row in rows),
                "source_block_count": len(block_records),
                "explicit_heading_count": len(headings),
                "character_count": sum(len(str(row["text"])) for row in rows),
                "line_ending_counts": line_ending_counts,
                "omitted_line_count": 0,
                "duplicate_line_count": 0,
                "source_block_selector_contract": f"#{WORK_ID}-block-%05d",
                "source_line_selector_contract": f"#{WORK_ID}-line-%05d",
                "source_lines": line_records,
                "source_blocks": block_records,
                "source_underscore_markup": {
                    **ACCOUNTABILITY_MARKUP,
                    "literal_markers": literal_markers,
                    "spans": spans,
                },
            }
        ],
        "total_line_count": len(rows),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_byte_reassembly": "readable TEI text plus exact recorded Gutenberg underscore delimiters and each source line's recorded CR/LF terminator",
        "block_mapping": ACCOUNTABILITY_BLOCK_MAPPING,
        "candidate_status": "nonaccepted",
        "human_review_required": True,
        "publication_ready": False,
    }


def _first_party_module_path(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    module_path = base.with_suffix(".py")
    if module_path.is_file():
        return module_path.resolve()
    package_path = base / "__init__.py"
    return package_path.resolve() if package_path.is_file() else None


def _resolved_import_name(module: str, path: Path, imported: str | None, level: int) -> str:
    if level == 0:
        return imported or ""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return ""
    base = parts[: len(parts) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, object]) -> tuple[Path, ...]:
    forbidden_value = policy.get("forbidden_oracle_imports")
    if not isinstance(forbidden_value, list) or any(
        not isinstance(item, str) for item in forbidden_value
    ):
        raise ValueError("37c-322 oracle forbidden-import policy is invalid")
    forbidden = tuple(forbidden_value)
    pending = ["build.tei.wilberforce_practical_view_37c322_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        package_parts = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
        pending.extend(
            package
            for index in range(1, len(package_parts) + 1)
            if (package := ".".join(package_parts[:index])) not in modules
        )
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import_name(module, path, node.module, node.level)
                if base:
                    names.append(base)
                    names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec", "import_module"})
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            ):
                raise ValueError("37c-322 oracle closure contains dynamic import or execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"37c-322 oracle closure contains forbidden import {name}")
                if _first_party_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in _closure_paths(root, policy)
    ]
    return _sha(_canonical(records))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    record = source_manifest.record
    if (
        record.get("ticket_id") != "37c-322"
        or record.get("work_id") != WORK_ID
        or record.get("source_id") != SOURCE_ID
    ):
        raise ValueError("37c-322 oracle rejects source identity drift")
    authorities = record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("37c-322 manifest authorities are invalid")
    primary = [item for item in authorities if item.get("role") == "primary-source"]
    if (
        len(primary) != 1
        or primary[0].get("name") != "primary-source"
        or primary[0].get("path") != SOURCE_PATH
        or primary[0].get("bytes") != SOURCE_SIZE
        or primary[0].get("sha256") != SOURCE_SHA256
    ):
        raise ValueError("37c-322 oracle requires the exact retained PG25709 member")
    converter = record.get("converter")
    validator = record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("37c-322 manifest callable bindings are invalid")
    logical_manifest = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != SOURCE_ID
        or candidate.manifest.get("source_manifest")
        != {"path": logical_manifest, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter") != dict(converter)
        or candidate.manifest.get("package_schema") != dict(record["package_schema"])
    ):
        raise ValueError("37c-322 candidate manifest binding drifted")

    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "37c-322 profile")
    policy = _strict_json(policy_bytes, "37c-322 validation policy")
    if (
        profile.get("profile_id") != PROFILE_ID
        or profile.get("ticket_id") != "37c-322"
        or profile.get("source_id") != SOURCE_ID
        or profile.get("source_scope") != "one-work-one-retained-project-gutenberg-member"
        or profile.get("primary_source_authority_name") != "primary-source"
        or profile.get("adjacent_retained_member_paths") != []
        or profile.get("source_underscore_policy") != MARKUP_POLICY
        or policy.get("ticket_id") != "37c-322"
        or policy.get("work_id") != WORK_ID
        or policy.get("source_path") != SOURCE_PATH
        or policy.get("source_underscore_policy") != MARKUP_POLICY
        or policy.get("forbidden_oracle_imports") != FORBIDDEN_IMPORTS
    ):
        raise ValueError("37c-322 profile or policy binding drifted")
    work_items = profile.get("works")
    if not isinstance(work_items, list) or len(work_items) != 1 or not isinstance(work_items[0], dict):
        raise ValueError("37c-322 profile work binding is invalid")
    work = work_items[0]
    if (
        work.get("work_id") != WORK_ID
        or work.get("ticket_id") != "37c-322"
        or work.get("source_path") != SOURCE_PATH
        or work.get("source_bytes") != SOURCE_SIZE
        or work.get("source_sha256") != SOURCE_SHA256
        or work.get("source_url") != SOURCE_URL
        or work.get("title") != WORK_TITLE
        or work.get("witness_description") != WITNESS_DESCRIPTION
        or profile.get("source_correction_attestation") != SOURCE_CORRECTION_ATTESTATION
    ):
        raise ValueError("37c-322 work identity or witness binding drifted")

    source_content = source_manifest.authority_path("primary-source").read_bytes()
    if len(source_content) != SOURCE_SIZE or _sha(source_content) != SOURCE_SHA256:
        raise ValueError("37c-322 retained source bytes drifted")
    rows = _source_rows(source_content)
    units = _source_units(rows)
    plan = _heading_plan(profile, rows, units)
    spans = _underscore_census(source_content, rows, units)
    literal_markers = _literal_underscore_census(rows, units)
    expected_accountability = _expected_accountability(
        rows, units, plan, spans, literal_markers
    )

    accountability_bytes = candidate.member_bytes("source-accountability.json")
    accountability = _strict_json(accountability_bytes, "37c-322 accountability")
    schema_bytes = source_manifest.authority_path("source-accountability-schema").read_bytes()
    schema = _strict_json(schema_bytes, "37c-322 accountability schema")
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if schema_errors:
        raise ValueError(f"37c-322 accountability schema failure: {schema_errors[0].message}")
    if accountability != expected_accountability or accountability_bytes != _canonical(expected_accountability):
        raise ValueError("37c-322 exact source and underscore accountability drifted")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        document = etree.fromstring(tei_bytes, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"37c-322 TEI is not well-formed XML: {exc}") from exc
    if not compiled_schema().validate(document):
        raise ValueError(f"37c-322 TEI P5 schema failure: {compiled_schema().error_log[0]}")
    q = lambda name: f"{{{TEI_NS}}}{name}"
    if (
        document.tag != q("TEI")
        or document.get(XML_ID) != f"gutenberg-{WORK_ID}"
        or set(document.attrib) != {XML_ID}
    ):
        raise ValueError("37c-322 TEI root identity drifted")
    if [child.tag for child in document] != [q("teiHeader"), q("text")]:
        raise ValueError("37c-322 TEI root structure drifted")
    header = document.find("./" + q("teiHeader"))
    file_desc = header.find("./" + q("fileDesc")) if header is not None else None
    title_stmt = file_desc.find("./" + q("titleStmt")) if file_desc is not None else None
    title_nodes = title_stmt.findall("./" + q("title")) if title_stmt is not None else []
    if (
        len(title_nodes) != 1
        or title_nodes[0].get("type") != "ticket-work-label"
        or title_nodes[0].text != WORK_TITLE
        or set(title_nodes[0].attrib) != {"type"}
    ):
        raise ValueError("37c-322 TEI title statement drifted")
    if file_desc is None or [child.tag for child in file_desc] != [
        q("titleStmt"),
        q("publicationStmt"),
        q("sourceDesc"),
    ]:
        raise ValueError("37c-322 file description structure drifted")
    if [child.tag for child in title_stmt] != [q("title")]:
        raise ValueError("37c-322 title statement contains an extra element")
    availability = file_desc.find("./" + q("publicationStmt") + "/" + q("availability")) if file_desc is not None else None
    availability_text = availability.findtext("./" + q("p")) if availability is not None else None
    if availability_text != NONACCEPTANCE_DISCLAIMER:
        raise ValueError("37c-322 nonacceptance disclaimer drifted")
    publication_stmt = file_desc.find("./" + q("publicationStmt"))
    if (
        publication_stmt is None
        or [child.tag for child in publication_stmt]
        != [q("publisher"), q("availability")]
        or publication_stmt.findtext("./" + q("publisher")) != "Open Christian Data"
        or availability is None
        or [child.tag for child in availability] != [q("p")]
    ):
        raise ValueError("37c-322 publication statement structure drifted")
    bibl = file_desc.find("./" + q("sourceDesc") + "/" + q("bibl")) if file_desc is not None else None
    if bibl is None or bibl.get("type") != "retained-witness" or bibl.get(XML_ID) != f"source-{WORK_ID}":
        raise ValueError("37c-322 source witness header is absent")
    source_desc = file_desc.find("./" + q("sourceDesc")) if file_desc is not None else None
    if (
        source_desc is None
        or [child.tag for child in source_desc] != [q("bibl")]
        or set(bibl.attrib) != {"type", XML_ID}
    ):
        raise ValueError("37c-322 source description structure drifted")
    bibl_title = bibl.find("./" + q("title"))
    witness_note = bibl.find("./" + q("note") + "[@type='witness-description']")
    correction_note = bibl.find("./" + q("note") + "[@type='source-correction-attestation']")
    ref = bibl.find("./" + q("ref"))
    if (
        bibl_title is None
        or bibl_title.get("type") != "ticket-work-label"
        or bibl_title.text != WORK_TITLE
        or set(bibl_title.attrib) != {"type"}
        or witness_note is None
        or witness_note.text != WITNESS_DESCRIPTION
        or set(witness_note.attrib) != {"type"}
        or correction_note is None
        or correction_note.text != SOURCE_CORRECTION_ATTESTATION
        or set(correction_note.attrib) != {"type"}
        or ref is None
        or ref.get("target") != SOURCE_URL
        or ref.text != SOURCE_PATH
        or set(ref.attrib) != {"target"}
        or [child.tag for child in bibl]
        != [q("title"), q("note"), q("note"), q("ref")]
    ):
        raise ValueError("37c-322 TEI witness or source correction header drifted")
    encoding_text = document.findtext(
        "./" + q("teiHeader") + "/" + q("encodingDesc") + "/" + q("projectDesc") + "/" + q("p")
    )
    if encoding_text != ENCODING_POLICY:
        raise ValueError("37c-322 source markup encoding statement drifted")
    encoding_desc = header.find("./" + q("encodingDesc")) if header is not None else None
    if (
        header is None
        or [child.tag for child in header] != [q("fileDesc"), q("encodingDesc")]
        or encoding_desc is None
        or [child.tag for child in encoding_desc] != [q("projectDesc")]
    ):
        raise ValueError("37c-322 TEI header structure drifted")
    text_node = document.find("./" + q("text"))
    group = text_node.find("./" + q("group")) if text_node is not None else None
    work_text = group.find("./" + q("text")) if group is not None else None
    body = work_text.find("./" + q("body")) if work_text is not None else None
    witness = body.find("./" + q("div")) if body is not None else None
    if (
        text_node is None
        or text_node.get("{http://www.w3.org/XML/1998/namespace}lang") != "en"
        or work_text is None
        or work_text.get(XML_ID) != WORK_ID
        or witness is None
        or witness.get("type") != "retained-text-witness"
        or witness.get("corresp") != f"#source-{WORK_ID}"
        or set(witness.attrib) != {"type", "corresp"}
        or [child.tag for child in document.find("./" + q("text"))] != [q("group")]
        or [child.tag for child in group] != [q("text")]
        or [child.tag for child in work_text] != [q("body")]
        or [child.tag for child in body] != [q("div")]
    ):
        raise ValueError("37c-322 TEI work body or witness wrapper drifted")

    heading_rows = plan["headings"]
    title_owner = plan["title_owner"]
    block_units = [unit for unit in units if unit["kind"] == "block"]
    line_nodes = witness.xpath(
        ".//tei:seg[@type='source-line'] | .//tei:space[@type='source-blank-line']",
        namespaces={"tei": TEI_NS},
    )
    document_line_nodes = document.xpath(
        ".//tei:seg[@type='source-line'] | .//tei:space[@type='source-blank-line']",
        namespaces={"tei": TEI_NS},
    )
    source_line_nodes = witness.xpath(
        ".//tei:seg[@type='source-line']", namespaces={"tei": TEI_NS}
    )
    blank_line_nodes = witness.xpath(
        ".//tei:space[@type='source-blank-line']", namespaces={"tei": TEI_NS}
    )
    if (
        len(line_nodes) != len(rows)
        or len(source_line_nodes) != sum(bool(row["text"]) for row in rows)
        or len(blank_line_nodes) != sum(row["text"] == "" for row in rows)
    ):
        raise ValueError("37c-322 TEI source line count drifted")
    if document_line_nodes != line_nodes:
        raise ValueError("37c-322 TEI contains a source line outside its witness")
    by_line = {int(row["line_number"]): node for row, node in zip(rows, line_nodes, strict=True)}
    if len(by_line) != len(rows):
        raise ValueError("37c-322 TEI source line identities are duplicated")
    span_fragments_by_line: dict[int, list[tuple[dict[str, object], dict[str, object]]]] = {}
    delimiter_columns_by_line: dict[int, list[int]] = {}
    for span in spans:
        delimiter_columns_by_line.setdefault(int(span["start_line"]), []).append(
            int(span["start_column"])
        )
        delimiter_columns_by_line.setdefault(int(span["end_line"]), []).append(
            int(span["end_column"])
        )
        for fragment in span["fragments"]:
            span_fragments_by_line.setdefault(int(fragment["line_number"]), []).append(
                (span, fragment)
            )
    expected_hi_count = 0
    for row, node in zip(rows, line_nodes, strict=True):
        line_number = int(row["line_number"])
        text = str(row["text"])
        if text == "":
            if (
                node.tag != q("space")
                or node.get("type") != "source-blank-line"
                or node.get("unit") != "line"
                or node.get("quantity") != "1"
                or node.get("n") != str(line_number)
                or node.get("subtype") != str(row["ending"])
                or node.get(XML_ID) != f"{WORK_ID}-blank-{line_number:05d}"
                or set(node.attrib)
                != {"type", "unit", "quantity", "n", "subtype", XML_ID}
                or node.text is not None
                or len(node)
            ):
                raise ValueError(
                    f"37c-322 TEI blank source line identity drift at {line_number}"
                )
            expected_visible = ""
        elif (
            node.tag != q("seg")
            or node.get("type") != "source-line"
            or node.get("n") != str(line_number)
            or node.get("subtype") != str(row["ending"])
            or node.get(XML_ID) != f"{WORK_ID}-line-{line_number:05d}"
            or set(node.attrib) != {"type", "n", "subtype", XML_ID}
        ):
            raise ValueError(f"37c-322 TEI source line identity drift at {line_number}")
        else:
            delimiter_columns = set(delimiter_columns_by_line.get(line_number, []))
            expected_visible = "".join(
                character
                for column, character in enumerate(text, 1)
                if column not in delimiter_columns
            )
        expected_fragments = sorted(
            (
                (
                    span,
                    fragment,
                    int(fragment["start_column"]) - 1
                    - sum(
                        delimiter < int(fragment["start_column"])
                        for delimiter in delimiter_columns_by_line.get(line_number, [])
                    ),
                    int(fragment["end_column"])
                    - sum(
                        delimiter <= int(fragment["end_column"])
                        for delimiter in delimiter_columns_by_line.get(line_number, [])
                    ),
                )
                for span, fragment in span_fragments_by_line.get(line_number, [])
            ),
            key=lambda item: item[2],
        )
        children = list(node)
        expected_hi_count += len(expected_fragments)
        if len(children) != len(expected_fragments):
            raise ValueError(f"37c-322 TEI italic fragment count drift at line {line_number}")
        cursor = 0
        prefix = node.text or ""
        for index, ((span, fragment, start, stop), child) in enumerate(
            zip(expected_fragments, children, strict=True)
        ):
            if prefix != expected_visible[cursor:start]:
                raise ValueError(f"37c-322 TEI text before italic fragment drift at line {line_number}")
            if child.tag != q("hi") or len(child) or child.get("rend") != "italic":
                raise ValueError(f"37c-322 readable emphasis rendition drift at line {line_number}")
            if child.text != expected_visible[start:stop]:
                raise ValueError(f"37c-322 TEI italic fragment text drift at line {line_number}")
            source_start = int(fragment["start_column"]) - 1
            source_stop = int(fragment["end_column"])
            if child.text != text[source_start:source_stop]:
                raise ValueError(f"37c-322 italic fragment source slice drift at line {line_number}")
            if int(fragment["part_index"]) == 1:
                if (
                    child.get(XML_ID) != span["span_id"]
                    or child.get("corresp") is not None
                    or set(child.attrib) != {"rend", XML_ID}
                ):
                    raise ValueError("37c-322 opening underscore wrapper identity drifted")
            elif (
                child.get("corresp") != f"#{span['span_id']}"
                or child.get(XML_ID) is not None
                or set(child.attrib) != {"rend", "corresp"}
            ):
                raise ValueError("37c-322 multiline underscore continuation drifted")
            next_start = (
                expected_fragments[index + 1][2]
                if index + 1 < len(expected_fragments)
                else len(expected_visible)
            )
            if (child.tail or "") != expected_visible[stop:next_start]:
                raise ValueError(f"37c-322 TEI text after italic fragment drift at line {line_number}")
            cursor = stop
            prefix = child.tail or ""
        if not expected_fragments and (children or (node.text or "") != expected_visible):
            raise ValueError(f"37c-322 TEI unmarked source line drift at {line_number}")
        if expected_fragments and cursor < len(expected_visible) and (children[-1].tail or "") != expected_visible[cursor:]:
            raise ValueError(f"37c-322 TEI trailing source line text drift at {line_number}")
        if "".join(node.itertext()) != expected_visible:
            raise ValueError(f"37c-322 TEI readable line projection drift at {line_number}")
    all_hi = document.xpath(".//tei:hi", namespaces={"tei": TEI_NS})
    if len(all_hi) != expected_hi_count or any(
        node.getparent().tag != q("seg")
        or node.getparent().get("type") != "source-line"
        or node.get("rend") != "italic"
        for node in all_hi
    ):
        raise ValueError("37c-322 TEI contains an extra, detached, or nonitalic hi element")

    reconstructed_rows: list[bytes] = []
    for row in rows:
        line_number = int(row["line_number"])
        visible = "".join(by_line[line_number].itertext())
        reconstructed = visible
        # Reinsert in ascending source-column order: after each earlier
        # delimiter is restored, later source columns match their original
        # offsets again.
        for column in sorted(delimiter_columns_by_line.get(line_number, [])):
            if column < 1 or column > len(reconstructed) + 1:
                raise ValueError(f"37c-322 delimiter locator cannot restore line {line_number}")
            reconstructed = reconstructed[: column - 1] + "_" + reconstructed[column - 1 :]
        if reconstructed != str(row["text"]):
            raise ValueError(f"37c-322 readable TEI cannot restore raw source line {line_number}")
        reconstructed_rows.append(
            reconstructed.encode("utf-8") + EOL_BYTES[str(row["ending"])]
        )
    if b"".join(reconstructed_rows) != source_content:
        raise ValueError("37c-322 candidate TEI and delimiter ledger do not reassemble retained source bytes")

    block_nodes = witness.xpath(".//tei:div[@xml:id]", namespaces={"tei": TEI_NS})
    all_witness_divs = witness.xpath(".//tei:div", namespaces={"tei": TEI_NS})
    expected_block_ids = {
        f"{WORK_ID}-block-{int(unit['block_number']):05d}" for unit in block_units
    }
    if len(block_nodes) != len(expected_block_ids) or len(all_witness_divs) != len(
        expected_block_ids
    ) or {
        node.get(XML_ID) for node in block_nodes
    } != expected_block_ids:
        raise ValueError("37c-322 TEI source block set drifted")
    allowed_witness_tags = {q(name) for name in ("div", "p", "head", "seg", "lb", "space", "hi")}
    if any(node.tag not in allowed_witness_tags for node in witness.iter()):
        raise ValueError("37c-322 TEI witness contains an unbound element")
    if any(child.tag not in {q("div"), q("space")} for child in witness):
        raise ValueError("37c-322 witness root contains an unbound source unit")
    block_by_id = {node.get(XML_ID): node for node in block_nodes}
    heading_sections: dict[int, etree._Element] = {}
    active_parent_by_level: dict[int, int] = {}
    blank_parent_line: dict[int, int | None] = {}
    for unit in units:
        if unit["kind"] == "blank":
            blank_parent_line[int(unit["row"]["line_number"])] = (
                active_parent_by_level[max(active_parent_by_level)]
                if active_parent_by_level
                else None
            )
            continue
        block_number = int(unit["block_number"])
        block_id = f"{WORK_ID}-block-{block_number:05d}"
        first_line = int(unit["rows"][0]["line_number"])
        node = block_by_id[block_id]
        heading = heading_rows.get(first_line)
        title_heading = title_owner.get(first_line)
        if heading is not None:
            level = int(heading["level"])
            parent_line = heading["parent_line"]
            if level == 1:
                active_parent_by_level.clear()
            else:
                for old_level in tuple(active_parent_by_level):
                    if old_level >= level:
                        del active_parent_by_level[old_level]
            if (
                node.get("type") != "source-heading-section"
                or node.get("n") != str(block_number)
                or node.get("subtype") != f"level-{level}"
                or set(node.attrib)
                != (
                    {"type", "n", "subtype", XML_ID, "corresp"}
                    if parent_line is not None
                    else {"type", "n", "subtype", XML_ID}
                )
            ):
                raise ValueError(f"37c-322 heading section drift at line {first_line}")
            if parent_line is None:
                if node.get("corresp") is not None or node.getparent() is not witness:
                    raise ValueError(f"37c-322 root heading parent drift at line {first_line}")
            elif node.get("corresp") != f"#{WORK_ID}-heading-{int(parent_line):05d}":
                raise ValueError(f"37c-322 nested heading parent reference drift at line {first_line}")
            head_nodes = node.findall("./" + q("head"))
            if len(head_nodes) != 1:
                raise ValueError(f"37c-322 source heading wrapper count drift at {first_line}")
            head = head_nodes[0]
            if (
                head.get("type") != "source-located-heading"
                or head.get("n") != str(first_line)
                or head.get("subtype") != str(level)
                or head.get(XML_ID) != f"{WORK_ID}-heading-{first_line:05d}"
                or set(head.attrib) != {"type", "n", "subtype", XML_ID}
            ):
                raise ValueError(f"37c-322 source heading element drift at {first_line}")
            if any(child.tag not in {q("head"), q("div"), q("space")} for child in node):
                raise ValueError(f"37c-322 heading section has an unbound child at {first_line}")
            heading_sections[first_line] = node
            active_parent_by_level[level] = first_line
            container = head
        else:
            expected_parent_line = (
                int(title_heading)
                if title_heading is not None
                else active_parent_by_level[max(active_parent_by_level)]
                if active_parent_by_level
                else None
            )
            if node.get("type") != "source-block" or node.get("n") != str(block_number) or node.get("subtype") is not None:
                raise ValueError(f"37c-322 source block wrapper drift at line {first_line}")
            if set(node.attrib) != {"type", "n", XML_ID}:
                raise ValueError(f"37c-322 source block attributes drift at line {first_line}")
            if title_heading is not None:
                heads = node.findall("./" + q("head"))
                if len(heads) != 1:
                    raise ValueError(f"37c-322 attached title wrapper count drift at {first_line}")
                container = heads[0]
                if (
                    container.get("type") != "source-attached-title"
                    or container.get("n") != str(first_line)
                    or container.get("corresp") != f"#{WORK_ID}-heading-{int(title_heading):05d}"
                    or container.get(XML_ID) != f"{WORK_ID}-title-{first_line:05d}"
                    or set(container.attrib) != {"type", "n", "corresp", XML_ID}
                ):
                    raise ValueError(f"37c-322 attached title wrapper drift at {first_line}")
            else:
                paragraphs = node.findall("./" + q("p"))
                if len(paragraphs) != 1:
                    raise ValueError(f"37c-322 source paragraph wrapper count drift at {first_line}")
                container = paragraphs[0]
                if (
                    container.get("n") != str(first_line)
                    or container.get(XML_ID) != f"{WORK_ID}-unit-{first_line:05d}"
                    or set(container.attrib) != {"n", XML_ID}
                ):
                    raise ValueError(f"37c-322 source paragraph identity drift at {first_line}")
            if list(node) != [container]:
                raise ValueError(f"37c-322 source block has an unbound child at {first_line}")

        expected_rows = unit["rows"]
        expected_children: list[tuple[str, int]] = []
        for index, row in enumerate(expected_rows):
            line_number = int(row["line_number"])
            expected_children.append(("seg", line_number))
            if index + 1 < len(expected_rows):
                expected_children.append(("lb", line_number))
        actual_children = list(container)
        if (
            len(actual_children) != len(expected_children)
            or (container.text or "")
            or any(child.tail for child in actual_children)
        ):
            raise ValueError(f"37c-322 source line-break sequence drift at block {block_number}")
        for child, (kind, line_number) in zip(actual_children, expected_children, strict=True):
            if kind == "seg":
                if child is not by_line[line_number]:
                    raise ValueError(f"37c-322 source line moved from block {block_number}")
            elif child.tag != q("lb") or child.get("type") != "source-line-break" or child.get("n") != str(line_number):
                raise ValueError(f"37c-322 source line-break identity drift at line {line_number}")
            elif set(child.attrib) != {"type", "n"}:
                raise ValueError(f"37c-322 source line-break attributes drift at line {line_number}")

        if heading is None:
            expected_parent = (
                heading_sections[expected_parent_line]
                if expected_parent_line is not None
                else witness
            )
        else:
            parent_line = heading["parent_line"]
            expected_parent = heading_sections[int(parent_line)] if parent_line is not None else witness
        if node.getparent() is not expected_parent:
            raise ValueError(f"37c-322 source block nesting drift at line {first_line}")

    blank_nodes = witness.xpath(".//tei:space[@type='source-blank-line']", namespaces={"tei": TEI_NS})
    document_blank_nodes = document.xpath(
        ".//tei:space[@type='source-blank-line']", namespaces={"tei": TEI_NS}
    )
    blank_rows = [row for row in rows if row["text"] == ""]
    if len(blank_nodes) != len(blank_rows) or document_blank_nodes != blank_nodes:
        raise ValueError("37c-322 source blank-line count drifted")
    for node, row in zip(blank_nodes, blank_rows, strict=True):
        line_number = int(row["line_number"])
        if (
            node.get("unit") != "line"
            or node.get("quantity") != "1"
            or node.get("n") != str(line_number)
            or node.get("subtype") != str(row["ending"])
            or node.get(XML_ID) != f"{WORK_ID}-blank-{line_number:05d}"
            or set(node.attrib) != {"type", "unit", "quantity", "n", "subtype", XML_ID}
            or len(node)
            or (node.text or "")
        ):
            raise ValueError(f"37c-322 source blank-line encoding drift at {line_number}")
        expected_parent_line = blank_parent_line[line_number]
        expected_parent = heading_sections[expected_parent_line] if expected_parent_line is not None else witness
        if node.getparent() is not expected_parent:
            raise ValueError(f"37c-322 blank-line nesting drift at {line_number}")

    expected_unit_events = [
        ("blank" if row["text"] == "" else "line", int(row["line_number"]))
        for row in rows
    ]
    observed_unit_events = [
        (
            "blank" if node.tag == q("space") else "line",
            int(node.get("n")),
        )
        for node in witness.iter()
        if (node.tag == q("space") and node.get("type") == "source-blank-line")
        or (node.tag == q("seg") and node.get("type") == "source-line")
    ]
    if observed_unit_events != expected_unit_events:
        raise ValueError("37c-322 source lines and blank delimiters are out of order")

    provenance_bytes = candidate.member_bytes("provenance.json")
    provenance = _strict_json(provenance_bytes, "37c-322 provenance")
    expected_provenance = {
        "contract": "ocd-selected-source-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "profile_id": PROFILE_ID,
        "ticket_id": "37c-322",
        "text_authority": "the one primary-source member declared by this ticket-bound SourceManifest",
        "work": {
            "work_id": WORK_ID,
            "ticket_work_label": WORK_TITLE,
            "source_path": SOURCE_PATH,
            "source_sha256": SOURCE_SHA256,
            "witness_description": WITNESS_DESCRIPTION,
        },
        "source_correction_attestation": SOURCE_CORRECTION_ATTESTATION,
        "human_review": "required",
        "accepted_ir": "not_accepted",
        "publication": "not_ready",
        "rights": {
            "provider_attribution": "Distributed Proofreaders attribution retained from the bound source record",
            "clearance": "not assessed by this technical reconstruction",
            "publication_state": "not_ready",
        },
    }
    if provenance != expected_provenance or provenance_bytes != _canonical(expected_provenance):
        raise ValueError("37c-322 provenance or review boundary drifted")
    unresolved = profile.get("unresolved")
    if not isinstance(unresolved, list) or candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(item) for item in unresolved
    ):
        raise ValueError("37c-322 unresolved evidence differs from the bound profile")
    readme = source_manifest.authority_path("source-local-readme").read_bytes()
    if candidate.member_bytes("README.source.md") != readme:
        raise ValueError("37c-322 source attribution README drifted")

    package_schema = source_manifest.authority_path("candidate-package-schema").read_bytes()
    xsd = source_manifest.authority_path("tei-p5-xsd").read_bytes()
    closure = _closure_digest(source_manifest.repository_root, policy)
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=SOURCE_SHA256,
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(package_schema),
        xsd_sha256=_sha(xsd),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
