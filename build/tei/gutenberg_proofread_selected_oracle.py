"""Independent oracle for the four ticket-bound Gutenberg proofread sources.

The oracle receives one per-ticket SourceManifest and reads only its one
primary-source file plus the explicitly named profile, policy, schemas and
README authorities. It never discovers or enumerates source directories and
does not import either reconstruction adapter.
"""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from lxml import etree


ORACLE_ID = "ocd-gutenberg-selected-proofread-independent-oracle"
ORACLE_VERSION = "3"
PROFILE_CONTRACT = "ocd-selected-source-profile-v2"
HEADING_MAP_CONTRACT = "ocd-source-located-heading-map-v1"
HEADING_POLICY = "exact-source-located-lines-with-declared-parent-and-title-attachments"
CAREY_TABLE_MAP_CONTRACT = "ocd-carey-source-table-map-v1"
CAREY_TABLE_MAP_SHA256 = "b84420afaf235ba4c724f6e9f9241c121c4fc189d5fadd57241069806f69018b"
CAREY_TABLE_SUMMARY = (
    ("europe", 819, 930, 817, 5, 2, 19, 0, 1),
    ("asia", 935, 1034, 933, 5, 10, 16, 3, 5),
    ("africa", 1039, 1080, 1037, 5, 1, 4, 0, 0),
    ("america", 1085, 1182, 1083, 6, 7, 26, 4, 2),
)
ACCOUNTABILITY_BLOCK_MAPPING = (
    "blank-line-delimited source blocks retained in order; source-located headings and mapped title attachments encoded"
)
NONACCEPTANCE_DISCLAIMER = (
    "Nonaccepted technical candidate. Rights clearance, human acceptance, and publication authorization are separate and have not been performed."
)
SOURCE_CORRECTION_ATTESTATION = (
    "The ticket-bound retained Project Gutenberg member was positively identified as human-proofread and carries Distributed Proofreaders attribution. This technical reconstruction does not independently audit the provider's individual corrections."
)
ENCODING_POLICY = (
    "The exact single retained text member is represented in source order. Each nonblank run between exact blank lines retains a source-block selector; line breaks and blank delimiters are explicit. Only exact source-located headings and mapped title runs are encoded as sections and attached titles. For Carey, the four retained geographical tables preserve source-located rows, cells, grouped population columns, continuations, blanks, qualifiers, and note links. Unmapped capitalization, contents entries, and unresolved hierarchy remain as source-block text."
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
ALLOWED_SOURCES = {
    "carey-enquiry": {
        "owner": "lib071",
        "ticket_id": "37c-094",
        "source_id": "gutenberg-37c-094-pg11449",
        "source_path": "raw/gutenberg/pg11449.txt",
        "source_bytes": 117568,
        "source_sha256": "6dc07e5606be5a0032d6583fa5b663a81ed0971a5d9d1f267cfc14959aa602c0",
        "source_url": "https://www.gutenberg.org/ebooks/11449",
        "title": "An Enquiry into the Obligations of Christians to Use Means for the Conversion of the Heathens",
        "witness_description": "Exact retained Project Gutenberg text member PG11449; treated as one source witness while edition, part, and constituent-work boundaries remain unresolved.",
        "ticket_path": "plans/2026-08-31-sample-first-library-verification/issues/37c-094-carey-enquiry.md",
    },
    "drummond-greatest-thing": {
        "owner": "lib071",
        "ticket_id": "37c-135",
        "source_id": "gutenberg-37c-135-pg16739",
        "source_path": "raw/gutenberg/pg16739.txt",
        "source_bytes": 204970,
        "source_sha256": "12f442db074bfd81db981dfb7c423120e830feb2019b2c0db253692e23624048",
        "source_url": "https://www.gutenberg.org/ebooks/16739",
        "title": "The Greatest Thing in the World and Other Addresses",
        "witness_description": "Exact retained Project Gutenberg text member PG16739; treated as one source witness while edition, part, and constituent-work boundaries remain unresolved.",
        "ticket_path": "plans/2026-08-31-sample-first-library-verification/issues/37c-135-drummond-greatest-thing.md",
    },
    "drummond-natural-law": {
        "owner": "lib071",
        "ticket_id": "37c-136",
        "source_id": "gutenberg-37c-136-pg23334",
        "source_path": "raw/gutenberg/pg23334.txt",
        "source_bytes": 566707,
        "source_sha256": "e13875abb98d6818ef2c9adbdce89a194368e082194881dcbf1e0c32a3c22333",
        "source_url": "https://www.gutenberg.org/ebooks/23334",
        "title": "Natural Law in the Spiritual World",
        "witness_description": "Exact retained Project Gutenberg text member PG23334; treated as one source witness while edition, part, and constituent-work boundaries remain unresolved.",
        "ticket_path": "plans/2026-08-31-sample-first-library-verification/issues/37c-136-drummond-natural-law.md",
    },
    "wilberforce-practical-view": {
        "owner": "lib072",
        "ticket_id": "37c-322",
        "source_id": "gutenberg-37c-322-pg25709",
        "source_path": "raw/gutenberg/pg25709.txt",
        "source_bytes": 659285,
        "source_sha256": "995ff74ac2c819b526d4874878507bb85e1141f7e5b35a388c44846a963d6c96",
        "source_url": "https://www.gutenberg.org/ebooks/25709",
        "title": "A Practical View of the Prevailing Religious System of Professed Christians",
        "witness_description": "Exact retained Project Gutenberg text member PG25709; treated as one source witness while edition, part, and constituent-work boundaries remain unresolved.",
        "ticket_path": "plans/2026-08-31-sample-first-library-verification/issues/37c-322-wilberforce-practical-view.md",
    },
}
# (source line, nesting level, parent heading line, attached title source lines).
# This oracle-owned table is separate from each manifest-bound profile and from
# both producer modules. Unlisted capitalization stays text until a reviewer
# establishes a source location and hierarchy.
EXPECTED_HEADING_LAYOUT = {
    "carey-enquiry": (
        (69, 1, None, ()),
        (142, 1, None, ()),
        (147, 2, 142, (150, 151)),
        (293, 2, 142, (296, 297)),
        (800, 2, 142, (803,)),
        (817, 3, 800, ()),
        (933, 3, 800, ()),
        (1037, 3, 800, ()),
        (1083, 3, 800, ()),
        (1281, 2, 142, (1284, 1285)),
        (1490, 2, 142, (1493, 1494)),
        (1715, 1, None, ()),
        (1751, 1, None, ()),
    ),
    "drummond-greatest-thing": (
        (71, 1, None, ()),
        (89, 1, None, ()),
        (116, 1, None, (118,)),
        (195, 2, 116, ()),
        (264, 2, 116, ()),
        (702, 2, 116, ()),
        (938, 1, None, ()),
        (1197, 1, None, ()),
        (1324, 2, 1197, ()),
        (1663, 2, 1197, ()),
        (1790, 2, 1197, ()),
        (1959, 1, None, (1961,)),
        (2342, 1, None, (2344,)),
        (2474, 2, 2342, ()),
        (2677, 2, 2342, ()),
        (3039, 2, 2342, ()),
        (3254, 1, None, ()),
        (3600, 1, None, ()),
    ),
    "drummond-natural-law": (
        (79, 1, None, ()),
        (100, 1, None, ()),
        (501, 2, 100, ()),
        (510, 1, None, ()),
        (518, 2, 510, (520,)),
        (539, 2, 510, (541,)),
        (564, 1, None, ()),
        (588, 2, 564, ()),
        (1209, 2, 564, ()),
        (1674, 3, 1209, ()),
        (1754, 1, None, ()),
        (2430, 2, 1754, ()),
        (2503, 1, None, ()),
        (3011, 2, 2503, ()),
        (3033, 1, None, ()),
        (3417, 2, 3033, ()),
        (3426, 1, None, ()),
        (4050, 2, 3426, ()),
        (4089, 1, None, ()),
        (4592, 2, 4089, ()),
        (4603, 1, None, ()),
        (5577, 2, 4603, ()),
        (5611, 1, None, ()),
        (6254, 2, 5611, ()),
        (6270, 1, None, ()),
        (6877, 2, 6270, ()),
        (6924, 1, None, ()),
        (7367, 1, None, ()),
        (7898, 2, 7367, ()),
        (7905, 1, None, ()),
        (8858, 1, None, ()),
        (8861, 1, None, ()),
        (8936, 1, None, ()),
    ),
    "wilberforce-practical-view": (
        (81, 1, None, ()),
        (170, 1, None, ()),
        (210, 1, None, ()),
        (215, 1, None, (217,)),
        (547, 1, None, (549,)),
        (552, 2, 547, (554,)),
        (896, 2, 547, (898,)),
        (1100, 2, 547, (1102,)),
        (1281, 1, None, (1283, 1284, 1285, 1286)),
        (1289, 2, 1281, (1291,)),
        (1649, 2, 1281, (1651,)),
        (2004, 2, 1281, (2006, 2007)),
        (2335, 2, 1281, (2337, 2338)),
        (2719, 1, None, (2721, 2722)),
        (2725, 2, 2719, ()),
        (3150, 2, 2719, ()),
        (3936, 2, 2719, (3938, 3939)),
        (4756, 2, 2719, (4758, 4759, 4760)),
        (5481, 2, 2719, (5483, 5484)),
        (6112, 2, 2719, (6114,)),
        (6647, 1, None, (6649, 6650)),
        (6915, 1, None, (6917, 6918, 6919, 6920)),
        (7974, 1, None, (7976,)),
        (8687, 2, 7974, (8689, 8690)),
        (8795, 2, 7974, (8797,)),
        (9083, 2, 7974, (9085,)),
        (9221, 1, None, ()),
        (9226, 1, None, ()),
        (9843, 1, None, ()),
        (10498, 1, None, ()),
    ),
}
_ENDING_BYTES = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}


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


def _authority(source_manifest: Any, name: str) -> Mapping[str, object]:
    records = source_manifest.record.get("authorities")
    if not isinstance(records, tuple):
        raise ValueError("selected source manifest authorities are invalid")
    matches = [item for item in records if isinstance(item, Mapping) and item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"selected source manifest must bind one {name!r} authority")
    return matches[0]


def _member_records(source_manifest: Any) -> tuple[Mapping[str, object], ...]:
    records = source_manifest.record.get("authorities")
    if not isinstance(records, tuple) or not records:
        raise ValueError("selected source manifest authority inventory is invalid")
    return tuple(item for item in records if isinstance(item, Mapping))


def _assert_ticket_authority_inventory(
    source_manifest: Any,
    expected_binding: Mapping[str, object],
    work_id: str,
) -> None:
    ticket_id = str(expected_binding["ticket_id"])
    owner = str(expected_binding["owner"])
    binding_directory = (
        f"sources/structured-text/{owner}-gutenberg-evangelical/"
        f"work-bindings/{work_id}"
    )
    converter_path = f"build/tei/gutenberg_evangelical_{owner}_selected_reconstruction.py"
    successor_suffix = "-tables-v3" if ticket_id == "37c-094" else ""
    expected = {
        "work-identity": ("work-identity", f"{binding_directory}/config.json"),
        "ticket-scope": ("ticket-scope", str(expected_binding["ticket_path"])),
        "primary-source": ("primary-source", str(expected_binding["source_path"])),
        "source-local-readme": (
            "source-attribution-readme",
            f"{binding_directory}/{ticket_id}.README.source.md",
        ),
        "reconstruction-profile": (
            "complete-source-feature-profile",
            f"{binding_directory}/{ticket_id}{successor_suffix}.reconstruction-profile.json",
        ),
        "validation-policy": (
            "independent-validation-policy",
            f"{binding_directory}/{ticket_id}{successor_suffix}.validation-policy.json",
        ),
        "source-accountability-schema": (
            "complete-source-accountability-schema",
            f"{binding_directory}/{ticket_id}{successor_suffix}.source-accountability.schema.json",
        ),
        "tei-p5-xsd": (
            "tei-validation-schema",
            "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
        ),
        "tei-p5-xsd-teix": (
            "tei-validation-schema-dependency",
            "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
        ),
        "tei-p5-xsd-xml": (
            "tei-validation-schema-dependency",
            "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
        ),
        "candidate-package-schema": (
            "candidate-package-schema",
            "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
        ),
        "converter-implementation": (
            "source-converter-implementation",
            converter_path,
        ),
        "oracle-implementation": (
            "independent-validator-implementation",
            "build/tei/gutenberg_proofread_selected_oracle.py",
        ),
    }
    records = _member_records(source_manifest)
    observed = {str(item.get("name")): item for item in records}
    if len(records) != len(expected) or set(observed) != set(expected):
        raise ValueError("selected-source manifest authority inventory is not ticket-isolated")
    for name, (role, path) in expected.items():
        authority = observed[name]
        if authority.get("role") != role or authority.get("path") != path:
            raise ValueError(f"selected-source manifest authority {name!r} is out of ticket scope")
        logical_parts = tuple(part.casefold() for part in Path(path).parts)
        if logical_parts and logical_parts[0] == "raw" and (
            name != "primary-source" or path != expected_binding["source_path"]
        ):
            raise ValueError("selected-source manifest binds an adjacent raw member")


def _assert_raw_scope_before_read(
    source_manifest: Any, expected_binding: Mapping[str, object]
) -> None:
    """Reject any authority inventory that could include adjacent retained sources."""
    records = _member_records(source_manifest)
    raw_records = []
    for record in records:
        logical_path = record.get("path")
        if isinstance(logical_path, str):
            parts = tuple(part.casefold() for part in Path(logical_path).parts)
            if parts and parts[0] == "raw":
                raw_records.append(record)
    if (
        len(raw_records) != 1
        or raw_records[0].get("name") != "primary-source"
        or raw_records[0].get("role") != "primary-source"
        or raw_records[0].get("path") != expected_binding["source_path"]
    ):
        raise ValueError("selected-source manifest may bind only its exact primary source under raw/")


def _source_lines_from_regex(content: bytes) -> list[tuple[str, str]]:
    """Independent CR/LF scanner based on delimiter-tokenized byte pairs."""
    content.decode("utf-8")
    parts = re.split(rb"(\r\n|\r|\n)", content)
    if content == b"":
        return []
    if len(parts) % 2 == 0:
        raise ValueError("selected source has an incomplete line-delimiter sequence")
    rows: list[tuple[str, str]] = []
    for offset in range(0, len(parts) - 1, 2):
        ending_bytes = parts[offset + 1]
        ending = {b"\r\n": "crlf", b"\r": "cr", b"\n": "lf"}.get(ending_bytes)
        if ending is None:
            raise ValueError("selected source contains an unexpected line delimiter")
        rows.append((parts[offset].decode("utf-8"), ending))
    if parts[-1] != b"":
        rows.append((parts[-1].decode("utf-8"), "none"))
    rebuilt = b"".join(text.encode("utf-8") + _ENDING_BYTES[ending] for text, ending in rows)
    if rebuilt != content:
        raise ValueError("independent source-line scanner did not reassemble source bytes")
    return rows


def _expected_units(rows: list[tuple[str, str]]) -> list[dict[str, object]]:
    """Independently inventory blank lines and nonblank source blocks."""
    units: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    block_number = 0

    def flush() -> None:
        nonlocal active, block_number
        if not active:
            return
        block_number += 1
        units.append({"kind": "block", "block_number": block_number, "rows": active})
        active = []

    for line_number, (text, ending) in enumerate(rows, 1):
        row = {"line_number": line_number, "text": text, "ending": ending}
        if text == "":
            flush()
            units.append({"kind": "blank", "row": row})
        else:
            active.append(row)
    flush()
    return units


def _verified_heading_map(
    work_id: str,
    work: Mapping[str, object],
    rows: list[tuple[str, str]],
    units: list[dict[str, object]],
) -> tuple[dict[int, tuple[int, int | None]], dict[int, int], dict[int, tuple[int, ...]]]:
    """Check the manifest map against oracle-owned locators and exact source rows."""
    expected_layout = EXPECTED_HEADING_LAYOUT.get(work_id)
    raw_map = work.get("heading_map")
    if expected_layout is None or not isinstance(raw_map, list):
        raise ValueError("selected-source oracle has no independent heading map for this work")
    observed_layout: list[tuple[int, int, int | None, tuple[int, ...]]] = []
    observed_heading_text: dict[int, str] = {}
    observed_title_text: dict[int, str] = {}
    for item in raw_map:
        if not isinstance(item, Mapping) or set(item) != {
            "line_number",
            "source_text",
            "level",
            "parent_line",
            "attached_title_lines",
        }:
            raise ValueError("selected-source heading map entry shape differs")
        line_number = item.get("line_number")
        level = item.get("level")
        parent_line = item.get("parent_line")
        title_records = item.get("attached_title_lines")
        if (
            not isinstance(line_number, int)
            or isinstance(line_number, bool)
            or not isinstance(level, int)
            or isinstance(level, bool)
            or not isinstance(title_records, list)
            or (parent_line is not None and (not isinstance(parent_line, int) or isinstance(parent_line, bool)))
        ):
            raise ValueError("selected-source heading-map locator values are invalid")
        title_numbers: list[int] = []
        for title in title_records:
            if not isinstance(title, Mapping) or set(title) != {"line_number", "source_text"}:
                raise ValueError("selected-source attached-title map entry shape differs")
            title_line = title.get("line_number")
            title_text = title.get("source_text")
            if (
                not isinstance(title_line, int)
                or isinstance(title_line, bool)
                or not isinstance(title_text, str)
                or not 1 <= title_line <= len(rows)
                or rows[title_line - 1][0] != title_text
            ):
                raise ValueError("selected-source attached-title text differs from retained source")
            title_numbers.append(title_line)
            observed_title_text[title_line] = title_text
        source_text = item.get("source_text")
        if (
            not isinstance(source_text, str)
            or not 1 <= line_number <= len(rows)
            or rows[line_number - 1][0] != source_text
        ):
            raise ValueError("selected-source heading text differs from retained source")
        observed_heading_text[line_number] = source_text
        observed_layout.append((line_number, level, parent_line, tuple(title_numbers)))
    if tuple(observed_layout) != expected_layout:
        raise ValueError("selected-source profile heading locations or hierarchy differ from oracle map")

    row_by_line = {
        int(row["line_number"]): row
        for unit in units
        if unit["kind"] == "block"
        for row in unit["rows"]
    }
    block_by_line: dict[int, dict[str, object]] = {}
    block_unit_index: dict[int, int] = {}
    for unit_index, unit in enumerate(units):
        if unit["kind"] != "block":
            continue
        block_number = int(unit["block_number"])
        block_unit_index[block_number] = unit_index
        for row in unit["rows"]:
            block_by_line[int(row["line_number"])] = unit

    active: dict[int, int] = {}
    heading_roles: dict[int, tuple[int, int | None]] = {}
    title_owner: dict[int, int] = {}
    title_groups: dict[int, tuple[int, ...]] = {}
    for line_number, level, parent_line, title_numbers in expected_layout:
        if line_number not in row_by_line or row_by_line[line_number]["text"] != observed_heading_text[line_number]:
            raise ValueError(f"oracle heading locator is absent from source line {line_number}")
        block = block_by_line[line_number]
        block_rows = block["rows"]
        if len(block_rows) != 1 or int(block_rows[0]["line_number"]) != line_number:
            raise ValueError(f"oracle heading locator is not an isolated source block at line {line_number}")
        if level == 1:
            if parent_line is not None:
                raise ValueError("oracle level-one heading unexpectedly has a parent")
            active.clear()
        else:
            if active.get(level - 1) != parent_line:
                raise ValueError(f"oracle heading parent is not active at line {line_number}")
            active = {depth: parent for depth, parent in active.items() if depth < level}
        if len(active) != level - 1:
            raise ValueError(f"oracle heading hierarchy has an unresolved level at line {line_number}")
        active[level] = line_number
        heading_roles[line_number] = (level, parent_line)
        title_groups[line_number] = title_numbers
        if title_numbers:
            if title_numbers != tuple(range(title_numbers[0], title_numbers[0] + len(title_numbers))):
                raise ValueError(f"oracle attached title lines are noncontiguous at heading {line_number}")
            current_index = block_unit_index[int(block["block_number"])]
            following_blocks = [
                unit for unit in units[current_index + 1 :] if unit["kind"] == "block"
            ]
            if not following_blocks or tuple(
                int(row["line_number"]) for row in following_blocks[0]["rows"]
            ) != title_numbers:
                raise ValueError(f"oracle attached title is not the next source block at heading {line_number}")
            for title_line in title_numbers:
                if title_line in title_owner or title_line in heading_roles:
                    raise ValueError("oracle heading and title locations overlap")
                title_owner[title_line] = line_number
    if set(observed_title_text) != set(title_owner):
        raise ValueError("profile has title text outside the oracle-owned attachment map")
    return heading_roles, title_owner, title_groups


def _accountability_lines(
    units: list[dict[str, object]],
    work_id: str,
    heading_roles: Mapping[int, tuple[int, int | None]],
    title_owner: Mapping[int, int],
    table_line_roles: Mapping[int, str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    table_line_roles = table_line_roles or {}
    lines: list[dict[str, object]] = []
    blocks: list[dict[str, object]] = []
    for unit in units:
        if unit["kind"] == "blank":
            row = unit["row"]
            lines.append(
                {
                    "line_number": row["line_number"],
                    "text_sha256": _sha(str(row["text"]).encode("utf-8")),
                    "line_ending": row["ending"],
                    "structural_role": table_line_roles.get(
                        int(row["line_number"]), "blank-line"
                    ),
                    "block_id": None,
                }
            )
            continue
        number = int(unit["block_number"])
        block_id = f"{work_id}-block-{number:05d}"
        observed: list[int] = []
        for row in unit["rows"]:
            line_number = int(row["line_number"])
            observed.append(line_number)
            lines.append(
                {
                    "line_number": line_number,
                    "text_sha256": _sha(str(row["text"]).encode("utf-8")),
                    "line_ending": row["ending"],
                    "structural_role": table_line_roles.get(
                        line_number,
                        "explicit-source-heading"
                        if line_number in heading_roles
                        else "source-attached-title"
                        if line_number in title_owner
                        else "source-block-text",
                    ),
                    "block_id": block_id,
                }
            )
        blocks.append(
            {
                "block_id": block_id,
                "block_number": number,
                "start_line": min(observed),
                "end_line": max(observed),
                "line_count": len(observed),
                "heading_lines": [int(row["line_number"]) for row in unit["rows"] if int(row["line_number"]) in heading_roles],
                "attached_title_lines": [int(row["line_number"]) for row in unit["rows"] if int(row["line_number"]) in title_owner],
            }
        )
    return lines, blocks


def _xml_children_exact(parent: etree._Element, expected_tags: list[str]) -> list[etree._Element]:
    children = list(parent)
    if [child.tag for child in children] != expected_tags:
        raise ValueError("candidate TEI element order or child inventory differs from source")
    if parent.text not in (None, "") or any(child.tail not in (None, "") for child in children):
        raise ValueError("candidate TEI contains unaccounted mixed text")
    return children


def _verify_source_group(
    element: etree._Element,
    rows: list[dict[str, object]],
    *,
    work_id: str,
    expected_tag: str,
    expected_type: str | None,
    expected_corresp: str | None = None,
    expected_subtype: str | None = None,
    expected_xml_id: str,
) -> None:
    if element.tag != f"{{{TEI_NS}}}{expected_tag}":
        raise ValueError("candidate TEI source group has the wrong semantic role")
    expected_attributes = {"n": str(rows[0]["line_number"]), XML_ID: expected_xml_id}
    if expected_type is not None:
        expected_attributes["type"] = expected_type
    if expected_corresp is not None:
        expected_attributes["corresp"] = expected_corresp
    if expected_subtype is not None:
        expected_attributes["subtype"] = expected_subtype
    if element.attrib != expected_attributes:
        raise ValueError("candidate TEI source group identity or heading attachment differs")
    expected_child_tags: list[str] = []
    for index in range(len(rows)):
        expected_child_tags.append(f"{{{TEI_NS}}}seg")
        if index + 1 < len(rows):
            expected_child_tags.append(f"{{{TEI_NS}}}lb")
    children = _xml_children_exact(element, expected_child_tags)
    child_index = 0
    for row_index, row in enumerate(rows):
        segment = children[child_index]
        child_index += 1
        line_number = int(row["line_number"])
        if (
            segment.attrib
            != {
                "type": "source-line",
                "n": str(line_number),
                "subtype": str(row["ending"]),
                XML_ID: f"{work_id}-line-{line_number:05d}",
            }
            or segment.text != row["text"]
            or len(segment) != 0
        ):
            raise ValueError("candidate TEI source-line text, order, or ending differs from source")
        if row_index + 1 < len(rows):
            line_break = children[child_index]
            child_index += 1
            if (
                line_break.attrib
                != {"type": "source-line-break", "n": str(line_number)}
                or len(line_break) != 0
                or line_break.text not in (None, "")
            ):
                raise ValueError("candidate TEI line-break marker differs from source order")


def _section_ancestry(element: etree._Element, work_id: str) -> tuple[int, ...]:
    result: list[int] = []
    ancestors = list(element.iterancestors())
    for ancestor in reversed(ancestors):
        if ancestor.tag != f"{{{TEI_NS}}}div":
            continue
        if "source-heading-section" not in str(ancestor.get("type", "")).split():
            continue
        heading_nodes = ancestor.findall(f"{{{TEI_NS}}}head[@type='source-located-heading']")
        if len(heading_nodes) != 1:
            raise ValueError("candidate TEI heading section lacks one direct mapped heading")
        heading = heading_nodes[0]
        if heading.get(XML_ID) != f"{work_id}-heading-{int(heading.get('n', '0')):05d}":
            raise ValueError("candidate TEI heading section identity is malformed")
        result.append(int(heading.get("n", "0")))
    return tuple(result)


def _source_events(
    units: list[dict[str, object]],
    heading_roles: Mapping[int, tuple[int, int | None]],
    title_owner: Mapping[int, int],
) -> list[dict[str, object]]:
    active: dict[int, int] = {}
    events: list[dict[str, object]] = []
    for unit in units:
        if unit["kind"] == "blank":
            events.append({"kind": "blank", "row": unit["row"], "ancestry": tuple(active[level] for level in sorted(active))})
            continue
        block_number = int(unit["block_number"])
        for row in unit["rows"]:
            line_number = int(row["line_number"])
            if line_number in heading_roles:
                level, parent_line = heading_roles[line_number]
                if level == 1:
                    active.clear()
                else:
                    if active.get(level - 1) != parent_line:
                        raise ValueError(f"oracle parent heading is not active at line {line_number}")
                    active = {depth: value for depth, value in active.items() if depth < level}
                active[level] = line_number
            if line_number in title_owner and title_owner[line_number] not in active.values():
                raise ValueError(f"oracle attached title has no active parent at line {line_number}")
            events.append(
                {
                    "kind": "source-line",
                    "row": row,
                    "block_number": block_number,
                    "ancestry": tuple(active[level] for level in sorted(active)),
                }
            )
    return events


def _carey_table_specs(
    work: Mapping[str, object], rows: list[tuple[str, str]]
) -> list[Mapping[str, object]]:
    raw_tables = work.get("source_tables")
    if (
        not isinstance(raw_tables, list)
        or len(raw_tables) != len(CAREY_TABLE_SUMMARY)
        or _sha(_canonical(raw_tables)) != CAREY_TABLE_MAP_SHA256
    ):
        raise ValueError("Carey table profile differs from the oracle-owned source map")
    for table, expected in zip(raw_tables, CAREY_TABLE_SUMMARY, strict=True):
        if not isinstance(table, Mapping):
            raise ValueError("Carey table profile contains a non-object record")
        (
            table_id,
            start_line,
            end_line,
            heading_line,
            column_count,
            blank_count,
            continuation_count,
            group_count,
            note_count,
        ) = expected
        header_rows = table.get("header_rows")
        if (
            table.get("table_id") != table_id
            or table.get("start_line") != start_line
            or table.get("end_line") != end_line
            or table.get("heading_line") != heading_line
            or not isinstance(table.get("column_roles"), list)
            or len(table["column_roles"]) != column_count
            or not isinstance(table.get("blank_lines"), list)
            or len(table["blank_lines"]) != blank_count
            or not isinstance(table.get("continuations"), Mapping)
            or len(table["continuations"]) != continuation_count
            or not isinstance(table.get("groups"), list)
            or len(table["groups"]) != group_count
            or not isinstance(table.get("notes"), list)
            or len(table["notes"]) != note_count
            or not isinstance(header_rows, Mapping)
            or header_rows != {
                "title": start_line,
                "columns": start_line + 1,
                "units": start_line + 2,
            }
        ):
            raise ValueError(f"Carey table {table_id!r} range or feature counts differ from the oracle map")
        actual_blanks = [
            line_number
            for line_number in range(start_line, end_line + 1)
            if rows[line_number - 1][0] == ""
        ]
        if table.get("blank_lines") != actual_blanks:
            raise ValueError(f"Carey table {table_id!r} blank-row map differs from retained source")
    return raw_tables


def _oracle_table_relations(
    table: Mapping[str, object],
) -> tuple[dict[int, int], dict[int, int], dict[int, Mapping[str, object]]]:
    raw_continuations = table.get("continuations")
    raw_groups = table.get("groups")
    raw_notes = table.get("notes")
    if (
        not isinstance(raw_continuations, Mapping)
        or not isinstance(raw_groups, list)
        or not isinstance(raw_notes, list)
    ):
        raise ValueError("Carey table relationship maps have an invalid shape")
    continuations: dict[int, int] = {}
    for source_line, owner_line in raw_continuations.items():
        try:
            line_number = int(source_line)
        except (TypeError, ValueError) as exc:
            raise ValueError("Carey continuation line locator is invalid") from exc
        if not isinstance(owner_line, int) or isinstance(owner_line, bool):
            raise ValueError("Carey continuation owner is invalid")
        continuations[line_number] = owner_line
    group_owner: dict[int, int] = {}
    for group in raw_groups:
        if not isinstance(group, Mapping):
            raise ValueError("Carey group relationship is invalid")
        heading_line = group.get("heading_line")
        ranges = group.get("member_ranges")
        if not isinstance(heading_line, int) or isinstance(heading_line, bool) or not isinstance(ranges, list):
            raise ValueError("Carey group relationship locator is invalid")
        for member_range in ranges:
            if (
                not isinstance(member_range, list)
                or len(member_range) != 2
                or any(not isinstance(value, int) or isinstance(value, bool) for value in member_range)
                or member_range[1] < member_range[0]
            ):
                raise ValueError("Carey group member range is invalid")
            for line_number in range(member_range[0], member_range[1] + 1):
                previous = group_owner.get(line_number)
                if previous is not None and previous != heading_line:
                    raise ValueError("Carey source row has conflicting group owners")
                group_owner[line_number] = heading_line
    note_by_line: dict[int, Mapping[str, object]] = {}
    for note in raw_notes:
        if not isinstance(note, Mapping):
            raise ValueError("Carey table note is invalid")
        start_line = note.get("start_line")
        end_line = note.get("end_line")
        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or end_line < start_line
        ):
            raise ValueError("Carey table note range is invalid")
        for line_number in range(start_line, end_line + 1):
            if line_number in note_by_line:
                raise ValueError("Carey source line has conflicting note roles")
            note_by_line[line_number] = note
    return continuations, group_owner, note_by_line


def _oracle_table_row_role(
    table: Mapping[str, object],
    line_number: int,
    note: Mapping[str, object] | None,
    continuations: Mapping[int, int],
) -> str:
    header_rows = table["header_rows"]
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
    if line_number in continuations:
        return "continuation"
    return "data"


def _oracle_whitespace_run(text: str, position: int) -> tuple[int, int]:
    left = min(max(position, 0), len(text))
    right = left
    while left > 0 and text[left - 1].isspace():
        left -= 1
    while right < len(text) and text[right].isspace():
        right += 1
    return left, right


def _oracle_table_cuts(
    text: str, boundaries: list[int], *, minimum_gap: int
) -> list[int | None]:
    cuts: list[int | None] = []
    for index, requested in enumerate(boundaries):
        position = min(max(requested, 0), len(text))
        if position == 0 or position >= len(text):
            cuts.append(position)
            continue
        if index == 0:
            token_start = position
            if not text[token_start].isspace():
                while token_start > 0 and not text[token_start - 1].isspace():
                    token_start -= 1
                first_token = text[token_start:].split(None, 1)[0]
                if first_token[:1].isdigit() or first_token.casefold() in {"unknown.", "undiscovered"}:
                    cuts.append(token_start)
                    continue
                token_start = position
            cursor = max(position, token_start)
            limit = min(len(text), requested + 12)
            found = False
            while cursor < limit:
                if text[cursor].isspace():
                    gap_start, gap_end = _oracle_whitespace_run(text, cursor)
                    next_token = text[gap_end:].split(None, 1)[0] if gap_end < len(text) else ""
                    if gap_end <= requested + 12 and (
                        next_token[:1].isdigit()
                        or next_token.casefold() in {"unknown.", "undiscovered"}
                    ):
                        cuts.append(gap_end)
                        found = True
                        break
                    cursor = max(cursor + 1, gap_end)
                else:
                    cursor += 1
            if found:
                continue
        gap_start, gap_end = _oracle_whitespace_run(text, position)
        cuts.append(position if gap_end - gap_start >= minimum_gap else None)
    return cuts


def _oracle_table_header_fields(
    table: Mapping[str, object], line_number: int
) -> tuple[list[dict[str, object]], list[int]]:
    header_rows = table["header_rows"]
    base_fields = table["base_fields"]
    if not isinstance(header_rows, Mapping) or not isinstance(base_fields, list):
        raise ValueError("Carey table header fields are invalid")
    if line_number == header_rows.get("columns"):
        raw_fields = base_fields
        boundary_key = "column_heading_boundaries"
    elif line_number == header_rows.get("units"):
        raw_fields = base_fields
        boundary_key = "unit_heading_boundaries"
    else:
        subcolumns = table.get("subcolumns")
        if not isinstance(subcolumns, Mapping) or line_number != subcolumns.get("line_number"):
            raise ValueError("Carey table line is not an independently declared header")
        raw_fields = [{"role": role, "cols": 1} for role in subcolumns.get("column_roles", [])]
        boundary_key = "boundaries"
        table = subcolumns
    boundaries = table.get(boundary_key)
    if not isinstance(raw_fields, list) or not isinstance(boundaries, list):
        raise ValueError("Carey table header boundary map is incomplete")
    fields = [
        {"role": str(item["role"]), "cols": int(item["cols"])}
        for item in raw_fields
        if isinstance(item, Mapping)
    ]
    if len(fields) != len(raw_fields) or len(boundaries) != len(fields) - 1:
        raise ValueError("Carey table header boundary count differs from its fields")
    return fields, [int(boundary) for boundary in boundaries]


def _oracle_table_cell_descriptors(
    table: Mapping[str, object], line_number: int, text: str, row_role: str
) -> list[dict[str, object]]:
    columns = table.get("column_roles")
    if not isinstance(columns, list):
        raise ValueError("Carey table grid roles are invalid")
    column_count = len(columns)
    overrides = table.get("cell_overrides", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("Carey table override map is invalid")
    override = overrides.get(str(line_number))
    if override is not None:
        if not isinstance(override, list) or not override:
            raise ValueError("Carey table override row is empty")
        output: list[dict[str, object]] = []
        source_cursor = 0
        column_cursor = 1
        for cell in override:
            if not isinstance(cell, Mapping):
                raise ValueError("Carey table override cell is invalid")
            start = cell.get("start")
            end = cell.get("end")
            start_column = cell.get("start_column")
            span = cell.get("cols")
            source_roles = cell.get("source_roles")
            if (
                start != source_cursor
                or not isinstance(end, int)
                or isinstance(end, bool)
                or end < source_cursor
                or end > len(text)
                or start_column != column_cursor
                or not isinstance(span, int)
                or isinstance(span, bool)
                or span < 1
                or not isinstance(source_roles, list)
            ):
                raise ValueError("Carey table override cells are not contiguous in source and grid")
            output.append(dict(cell))
            source_cursor = end
            column_cursor += span
        if source_cursor != len(text) or column_cursor - 1 != column_count:
            raise ValueError("Carey table override does not cover its source row and column grid")
        return output

    if row_role in {"table-superheading", "group-heading", "table-note", "footnote"}:
        cell_role = "table-heading" if row_role == "table-superheading" else row_role
        return [{
            "role": cell_role,
            "source_roles": [],
            "start_column": 1,
            "cols": column_count,
            "start": 0,
            "end": len(text),
        }]

    if row_role in {"column-headings", "unit-headings", "column-subheadings"}:
        fields, boundaries = _oracle_table_header_fields(table, line_number)
        cuts: list[int | None] = boundaries
    elif line_number in {int(value) for value in table.get("uncertain_layout_lines", [])}:
        boundaries = [int(value) for value in table.get("column_boundaries", [])]
        return [
            {"role": "country", "source_roles": ["country"], "start_column": 1, "cols": 1, "start": 0, "end": boundaries[0]},
            {"role": "unresolved-layout", "source_roles": list(columns)[1:], "start_column": 2, "cols": column_count - 1, "start": boundaries[0], "end": len(text)},
        ]
    elif line_number in {int(value) for value in table.get("wide_country_lines", [])}:
        boundaries = [int(value) for value in table.get("column_boundaries", [])]
        return [
            {"role": "country", "source_roles": ["country"], "start_column": 1, "cols": column_count - 1, "start": 0, "end": boundaries[-1]},
            {"role": "religion", "source_roles": ["religion"], "start_column": column_count, "cols": 1, "start": boundaries[-1], "end": len(text)},
        ]
    else:
        subcolumns = table.get("subcolumns")
        if isinstance(subcolumns, Mapping) and line_number > int(subcolumns.get("line_number", 0)):
            fields = [{"role": value, "cols": 1} for value in subcolumns.get("column_roles", [])]
            boundaries = [int(value) for value in subcolumns.get("body_boundaries", [])]
            minimum_gap = 1
        else:
            fields = table.get("base_fields")
            boundaries = [int(value) for value in table.get("column_boundaries", [])]
            minimum_gap = 2
        if not isinstance(fields, list):
            raise ValueError("Carey table body fields are invalid")
        fields = [
            {"role": str(item["role"]), "cols": int(item["cols"])}
            for item in fields
            if isinstance(item, Mapping)
        ]
        cuts = _oracle_table_cuts(text, boundaries, minimum_gap=minimum_gap)

    if len(cuts) != len(fields) - 1:
        raise ValueError("Carey source row boundary count differs from its fields")
    output = []
    field_start = 0
    source_start = 0
    column_start = 1
    for index, field in enumerate(fields):
        span = int(field["cols"])
        if index != len(fields) - 1 and cuts[index] is None:
            continue
        end = len(text) if index == len(fields) - 1 else min(len(text), int(cuts[index]))
        members = fields[field_start : index + 1]
        source_roles = [str(item["role"]) for item in members]
        grid_span = sum(int(item["cols"]) for item in members)
        if len(members) == 1:
            role_name = str(field["role"])
        elif set(source_roles) == {"length", "breadth"}:
            role_name = "extent-qualifier"
        else:
            role_name = "ambiguous-span"
        output.append({
            "role": role_name,
            "source_roles": source_roles,
            "start_column": column_start,
            "cols": grid_span,
            "start": source_start,
            "end": end,
        })
        column_start += grid_span
        source_start = end
        field_start = index + 1
    if column_start - 1 != column_count:
        raise ValueError("Carey source row cells do not cover the declared column grid")
    return output


def _oracle_table_header_targets(table: Mapping[str, object], work_id: str) -> dict[str, list[str]]:
    header_rows = table["header_rows"]
    fields = table["base_fields"]
    if not isinstance(header_rows, Mapping) or not isinstance(fields, list):
        raise ValueError("Carey table header targets are invalid")
    targets: dict[str, list[str]] = {}
    column = 1
    for field in fields:
        role = str(field["role"])
        targets[role] = [
            f"#{work_id}-cell-{int(header_rows['columns']):05d}-c{column:02d}",
            f"#{work_id}-cell-{int(header_rows['units']):05d}-c{column:02d}",
        ]
        column += int(field["cols"])
    subcolumns = table.get("subcolumns")
    if isinstance(subcolumns, Mapping):
        column = 1
        for role in subcolumns.get("column_roles", []):
            targets[str(role)] = [
                f"#{work_id}-cell-{int(subcolumns['line_number']):05d}-c{column:02d}"
            ]
            column += 1
    return targets


def _oracle_table_cell_type(role: str, text: str) -> str | None:
    lowered = text.casefold()
    if text.strip() == "":
        return "empty-field"
    if role == "unresolved-layout":
        return "layout-uncertain"
    if any(
        term in lowered
        for term in ("undiscovered", "in compass.", "in number.", "unknown.", "a cluster of isles.")
    ):
        return "source-qualifier"
    return None


def _oracle_table_accounting(
    work_id: str,
    tables: list[Mapping[str, object]],
    rows: list[tuple[str, str]],
    units: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[int, str]]:
    block_by_line = {
        int(row["line_number"]): int(unit["block_number"])
        for unit in units
        if unit["kind"] == "block"
        for row in unit["rows"]
    }
    output: list[dict[str, object]] = []
    line_roles: dict[int, str] = {}
    for table in tables:
        table_id = str(table["table_id"])
        continuations, group_owner, note_by_line = _oracle_table_relations(table)
        table_rows: list[dict[str, object]] = []
        column_count = len(table["column_roles"])
        for line_number in range(int(table["start_line"]), int(table["end_line"]) + 1):
            text, ending = rows[line_number - 1]
            note = note_by_line.get(line_number)
            if text == "":
                row_role = "source-blank-line"
                descriptors = [{
                    "role": "blank-line",
                    "source_roles": [],
                    "start_column": 1,
                    "cols": column_count,
                    "start": 0,
                    "end": 0,
                }]
            else:
                row_role = _oracle_table_row_role(table, line_number, note, continuations)
                descriptors = _oracle_table_cell_descriptors(table, line_number, text, row_role)
            cells = []
            for descriptor in descriptors:
                start = int(descriptor["start"])
                end = int(descriptor["end"])
                value = text[start:end]
                cells.append({
                    "cell_id": f"{work_id}-cell-{line_number:05d}-c{int(descriptor['start_column']):02d}",
                    "role": descriptor["role"],
                    "source_roles": list(descriptor["source_roles"]),
                    "start_column": descriptor["start_column"],
                    "cols": descriptor["cols"],
                    "source_start": start,
                    "source_end": end,
                    "source_text_sha256": _sha(value.encode("utf-8")),
                    "type": _oracle_table_cell_type(str(descriptor["role"]), value),
                })
            block_number = block_by_line.get(line_number)
            if text and block_number is None:
                raise ValueError(f"oracle table row {line_number} has no source-block accounting selector")
            note_target = None
            note_role = None
            if note is not None:
                note_role = str(note.get("role", "table-note"))
                note_target = note.get("target_line", note.get("attach_to", "table"))
                if not (
                    note_target == "table"
                    or isinstance(note_target, int) and not isinstance(note_target, bool)
                ):
                    raise ValueError(f"oracle table note target is invalid at line {line_number}")
            table_rows.append({
                "line_number": line_number,
                "row_id": f"{work_id}-row-{line_number:05d}",
                "row_role": row_role,
                "line_ending": ending,
                "source_text_sha256": _sha(text.encode("utf-8")),
                "block_id": f"{work_id}-block-{block_number:05d}" if block_number is not None else None,
                "group_owner_line": group_owner.get(line_number),
                "continuation_owner_line": continuations.get(line_number),
                "note_role": note_role,
                "note_target": note_target,
                "cells": cells,
            })
            line_roles[line_number] = f"source-table-{table_id}-{row_role}"
        output.append({
            "table_id": table["table_id"],
            "heading_line": table["heading_line"],
            "start_line": table["start_line"],
            "end_line": table["end_line"],
            "header_rows": table["header_rows"],
            "column_roles": table["column_roles"],
            "row_count": len(table_rows),
            "rows": table_rows,
        })
    return output, line_roles


def _verify_carey_table_nodes(
    witness: etree._Element,
    work_id: str,
    tables: list[Mapping[str, object]],
    rows: list[tuple[str, str]],
    units: list[dict[str, object]],
    expected_events: list[dict[str, object]],
) -> tuple[dict[int, tuple[str, str]], set[int], set[int]]:
    table_nodes = [
        node
        for node in witness.iterdescendants()
        if node.tag == f"{{{TEI_NS}}}table"
    ]
    if len(table_nodes) != len(tables):
        raise ValueError("candidate TEI Carey table inventory differs from source map")
    table_by_id = {str(table["table_id"]): table for table in tables}
    event_by_line = {
        int(event["row"]["line_number"]): event for event in expected_events
    }
    table_lines: dict[int, Mapping[str, object]] = {}
    for table in tables:
        for line_number in range(int(table["start_line"]), int(table["end_line"]) + 1):
            if line_number in table_lines:
                raise ValueError("oracle Carey source table ranges overlap")
            table_lines[line_number] = table
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
    table_block_numbers: set[int] = set()
    for unit in units:
        if unit["kind"] != "block":
            continue
        block_number = int(unit["block_number"])
        block_lines = [int(row["line_number"]) for row in unit["rows"]]
        selected = [line_number for line_number in block_lines if line_number in table_lines]
        if selected:
            if len(selected) != len(block_lines) or len({str(table_lines[line]["table_id"]) for line in selected}) != 1:
                raise ValueError("oracle Carey table range splits a blank-delimited source block")
            if block_start_by_line.get(block_lines[0]) != block_number:
                raise ValueError("oracle Carey table source-block start map is inconsistent")
            table_block_numbers.add(block_number)

    nodes_by_id: dict[str, etree._Element] = {}
    for node in table_nodes:
        table_id = str(node.get("n", ""))
        if table_id not in table_by_id or table_id in nodes_by_id:
            raise ValueError("candidate TEI Carey table identity is unknown or duplicated")
        nodes_by_id[table_id] = node

    line_values: dict[int, tuple[str, str]] = {}
    for table_id, table in table_by_id.items():
        node = nodes_by_id[table_id]
        start_line = int(table["start_line"])
        end_line = int(table["end_line"])
        column_count = len(table["column_roles"])
        expected_attributes = {
            "type": "source-located-table",
            "n": table_id,
            "rows": str(end_line - start_line + 1),
            "cols": str(column_count),
            "corresp": f"#{work_id}-heading-{int(table['heading_line']):05d}",
            XML_ID: f"{work_id}-table-{table_id}",
        }
        if node.attrib != expected_attributes or node.text not in (None, ""):
            raise ValueError(f"candidate TEI table {table_id!r} binding or dimensions differ")
        expected_ancestry = event_by_line[start_line]["ancestry"]
        if _section_ancestry(node, work_id) != expected_ancestry:
            raise ValueError(f"candidate TEI table {table_id!r} is detached from its source heading")
        table_rows = list(node)
        if len(table_rows) != end_line - start_line + 1 or any(
            row.tag != f"{{{TEI_NS}}}row" for row in table_rows
        ):
            raise ValueError(f"candidate TEI table {table_id!r} row inventory differs")
        continuations, group_owner, note_by_line = _oracle_table_relations(table)
        header_targets = _oracle_table_header_targets(table, work_id)
        footnote_markers = {
            int(note["marker_line"]): (
                str(note["marker"]),
                int(note["start_line"]),
            )
            for note in table.get("notes", [])
            if isinstance(note, Mapping)
            and isinstance(note.get("marker_line"), int)
            and isinstance(note.get("marker"), str)
        }
        for offset, row_node in enumerate(table_rows):
            line_number = start_line + offset
            text, ending = rows[line_number - 1]
            note = note_by_line.get(line_number)
            if text == "":
                row_role = "source-blank-line"
                descriptors = []
                expected_row_attributes = {
                    "role": row_role,
                    "n": str(line_number),
                    XML_ID: f"{work_id}-row-{line_number:05d}",
                }
                expected_cell_attributes = {
                    "role": "blank-line",
                    "rend": "empty-field",
                    "n": "1",
                    "cols": str(column_count),
                    XML_ID: f"{work_id}-cell-{line_number:05d}-c01",
                }
                if row_node.attrib != expected_row_attributes or row_node.text not in (None, ""):
                    raise ValueError(f"candidate TEI blank row {line_number} differs from source")
                blank_cells = list(row_node)
                if len(blank_cells) != 1 or blank_cells[0].tag != f"{{{TEI_NS}}}cell":
                    raise ValueError(f"candidate TEI blank row {line_number} has the wrong cell count")
                if blank_cells[0].attrib != expected_cell_attributes or len(blank_cells[0]) != 1:
                    raise ValueError(f"candidate TEI blank table cell {line_number} differs")
                blank_space = blank_cells[0][0]
                if blank_space.tag != f"{{{TEI_NS}}}space" or blank_space.attrib != {
                    "type": "source-blank-line",
                    "unit": "line",
                    "quantity": "1",
                    "n": str(line_number),
                    "subtype": ending,
                    XML_ID: f"{work_id}-blank-{line_number:05d}",
                } or len(blank_space) != 0 or blank_space.text not in (None, ""):
                    raise ValueError(f"candidate TEI blank table line ending {line_number} differs")
                line_values[line_number] = ("", ending)
                continue

            row_role = _oracle_table_row_role(table, line_number, note, continuations)
            descriptors = _oracle_table_cell_descriptors(table, line_number, text, row_role)
            block_number = block_by_line.get(line_number)
            if block_number is None:
                raise ValueError(f"oracle table source row {line_number} has no source block")
            row_analyses = [f"#{work_id}-block-{block_number:05d}"]
            if line_number in group_owner:
                row_analyses.append(f"#{work_id}-row-{group_owner[line_number]:05d}")
            if note is not None:
                target = note.get("target_line", note.get("attach_to", "table"))
                row_analyses.append(
                    f"#{work_id}-row-{int(target):05d}"
                    if isinstance(target, int) and not isinstance(target, bool)
                    else f"#{work_id}-table-{table_id}"
                )
            expected_row_attributes = {
                "role": row_role,
                "n": str(line_number),
                XML_ID: f"{work_id}-row-{line_number:05d}",
                "ana": " ".join(row_analyses),
            }
            continuation_owner = continuations.get(line_number)
            if continuation_owner is not None:
                expected_row_attributes["corresp"] = f"#{work_id}-row-{continuation_owner:05d}"
            if row_node.attrib != expected_row_attributes or row_node.text not in (None, ""):
                raise ValueError(f"candidate TEI table row {line_number} role or attachment differs")
            actual_cells = list(row_node)
            if len(actual_cells) != len(descriptors) or any(
                cell.tag != f"{{{TEI_NS}}}cell" for cell in actual_cells
            ):
                raise ValueError(f"candidate TEI table row {line_number} cell inventory differs")
            for descriptor, cell in zip(descriptors, actual_cells, strict=True):
                start = int(descriptor["start"])
                end = int(descriptor["end"])
                value = text[start:end]
                source_roles = [str(role) for role in descriptor["source_roles"]]
                role_name = str(descriptor["role"])
                expected_cell_attributes = {
                    "role": role_name,
                    "n": str(descriptor["start_column"]),
                    XML_ID: (
                        f"{work_id}-cell-{line_number:05d}-c{int(descriptor['start_column']):02d}"
                    ),
                }
                if int(descriptor["cols"]) > 1:
                    expected_cell_attributes["cols"] = str(descriptor["cols"])
                cell_type = _oracle_table_cell_type(role_name, value)
                if cell_type is not None:
                    expected_cell_attributes["rend"] = cell_type
                references = []
                for source_role in source_roles:
                    references.extend(header_targets.get(source_role, []))
                if references:
                    expected_cell_attributes["ana"] = " ".join(dict.fromkeys(references))
                if continuation_owner is not None and value.strip() != "":
                    expected_cell_attributes["corresp"] = (
                        f"#{work_id}-cell-{continuation_owner:05d}-c{int(descriptor['start_column']):02d}"
                    )
                if cell.attrib != expected_cell_attributes or cell.text not in (None, ""):
                    raise ValueError(f"candidate TEI table cell {line_number} attributes differ from source map")
                actual_cell_children = list(cell)
                expects_anchor = (
                    block_start_by_line.get(line_number) == block_number
                    and int(descriptor["start_column"]) == 1
                )
                if expects_anchor:
                    if not actual_cell_children or actual_cell_children[0].tag != f"{{{TEI_NS}}}anchor":
                        raise ValueError(f"candidate TEI table source block {block_number} lacks its start selector")
                    anchor = actual_cell_children.pop(0)
                    if anchor.attrib != {
                        "type": "source-block-start",
                        XML_ID: f"{work_id}-block-{block_number:05d}",
                    } or len(anchor) != 0 or anchor.text not in (None, ""):
                        raise ValueError(f"candidate TEI table source block selector {block_number} differs")
                if start == end:
                    if actual_cell_children:
                        raise ValueError(f"candidate TEI empty source cell at line {line_number} contains text")
                else:
                    if len(actual_cell_children) != 1:
                        raise ValueError(f"candidate TEI source cell at line {line_number} lacks one text fragment")
                    segment = actual_cell_children[0]
                    if segment.tag != f"{{{TEI_NS}}}seg" or segment.attrib != {
                        "type": "source-line-fragment",
                        "n": f"{line_number}:{start}-{end}",
                        "subtype": ending,
                        XML_ID: f"{work_id}-fragment-{line_number:05d}-{start:04d}-{end:04d}",
                    }:
                        raise ValueError(f"candidate TEI source fragment locator at line {line_number} differs")
                    marker = footnote_markers.get(line_number)
                    if marker is not None and marker[0] in value:
                        before, after = value.split(marker[0], 1)
                        references = list(segment)
                        if (
                            segment.text != before
                            or len(references) != 1
                            or references[0].tag != f"{{{TEI_NS}}}ref"
                            or references[0].attrib != {
                                "type": "table-footnote-marker",
                                "target": f"#{work_id}-row-{marker[1]:05d}",
                            }
                            or references[0].text != marker[0]
                            or references[0].tail != after
                        ):
                            raise ValueError(f"candidate TEI footnote marker at line {line_number} is detached")
                    elif segment.text != value or len(segment) != 0:
                        raise ValueError(f"candidate TEI source fragment text at line {line_number} differs")
            line_values[line_number] = (text, ending)

    if set(line_values) != set(table_lines):
        raise ValueError("candidate TEI Carey rows do not cover every mapped table source line")
    return line_values, table_block_numbers, set(table_lines)


def _check_candidate_tei(
    tei_bytes: bytes,
    profile: Mapping[str, object],
    expected_binding: Mapping[str, object],
    expected_units: list[dict[str, object]],
    expected_source_bytes: bytes,
    heading_roles: Mapping[int, tuple[int, int | None]],
    title_owner: Mapping[int, int],
    title_groups: Mapping[int, tuple[int, ...]],
    table_specs: list[Mapping[str, object]],
) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, remove_blank_text=False)
    root = etree.fromstring(tei_bytes, parser=parser)
    work = profile["works"][0]
    work_id = str(work["work_id"])
    if root.tag != f"{{{TEI_NS}}}TEI" or root.attrib != {XML_ID: f"gutenberg-{work_id}"}:
        raise ValueError("candidate TEI root identity differs from selected work")
    root_children = _xml_children_exact(
        root,
        [f"{{{TEI_NS}}}teiHeader", f"{{{TEI_NS}}}text"],
    )
    header, outer_text = root_children
    if header.attrib:
        raise ValueError("candidate TEI header attributes differ from the pinned header")
    header_children = _xml_children_exact(
        header,
        [f"{{{TEI_NS}}}fileDesc", f"{{{TEI_NS}}}encodingDesc"],
    )
    file_desc, encoding_desc = header_children
    if file_desc.attrib or encoding_desc.attrib:
        raise ValueError("candidate TEI header container attributes differ from the pinned header")
    file_desc_children = _xml_children_exact(
        file_desc,
        [
            f"{{{TEI_NS}}}titleStmt",
            f"{{{TEI_NS}}}publicationStmt",
            f"{{{TEI_NS}}}sourceDesc",
        ],
    )
    title_stmt, publication_stmt, source_desc = file_desc_children
    if title_stmt.attrib or publication_stmt.attrib or source_desc.attrib:
        raise ValueError("candidate TEI fileDesc container attributes differ from the pinned header")
    title_nodes = _xml_children_exact(title_stmt, [f"{{{TEI_NS}}}title"])
    if (
        title_nodes[0].attrib != {"type": "ticket-work-label"}
        or title_nodes[0].text != work["title"]
        or len(title_nodes[0]) != 0
    ):
        raise ValueError("candidate TEI title label differs from bound ticket profile")
    publication_children = _xml_children_exact(
        publication_stmt,
        [f"{{{TEI_NS}}}publisher", f"{{{TEI_NS}}}availability"],
    )
    publisher, availability = publication_children
    if publisher.text != "Open Christian Data" or publisher.attrib or len(publisher) != 0:
        raise ValueError("candidate TEI publication header differs from technical candidate")
    availability_paragraphs = _xml_children_exact(availability, [f"{{{TEI_NS}}}p"])
    if (
        availability.attrib
        or availability_paragraphs[0].text != NONACCEPTANCE_DISCLAIMER
        or availability_paragraphs[0].attrib
        or len(availability_paragraphs[0]) != 0
    ):
        raise ValueError("candidate TEI availability disclaimer drifted")
    bibl_nodes = _xml_children_exact(source_desc, [f"{{{TEI_NS}}}bibl"])
    bibl = bibl_nodes[0]
    if bibl.attrib != {"type": "retained-witness", XML_ID: f"source-{work_id}"}:
        raise ValueError("candidate TEI sourceDesc witness identity differs")
    bibl_children = _xml_children_exact(
        bibl,
        [
            f"{{{TEI_NS}}}title",
            f"{{{TEI_NS}}}note",
            f"{{{TEI_NS}}}note",
            f"{{{TEI_NS}}}ref",
        ],
    )
    source_title, witness_note, correction_note, source_ref = bibl_children
    if (
        source_title.attrib != {"type": "ticket-work-label"}
        or source_title.text != work["title"]
        or len(source_title) != 0
    ):
        raise ValueError("candidate TEI sourceDesc title binding differs")
    if (
        witness_note.attrib != {"type": "witness-description"}
        or witness_note.text != work["witness_description"]
        or len(witness_note) != 0
    ):
        raise ValueError("candidate TEI sourceDesc witness description differs")
    if (
        correction_note.attrib != {"type": "source-correction-attestation"}
        or correction_note.text != profile.get("source_correction_attestation")
        or len(correction_note) != 0
    ):
        raise ValueError("candidate TEI source correction attestation differs from bound profile")
    if (
        source_ref.attrib != {"target": expected_binding["source_url"]}
        or source_ref.text != expected_binding["source_path"]
        or len(source_ref) != 0
    ):
        raise ValueError("candidate TEI sourceDesc/reference binding differs from exact source")
    encoding_children = _xml_children_exact(
        encoding_desc,
        [f"{{{TEI_NS}}}projectDesc"],
    )
    if encoding_desc.attrib or encoding_children[0].attrib:
        raise ValueError("candidate TEI encoding header attributes differ from the pinned header")
    project_paragraphs = _xml_children_exact(
        encoding_children[0],
        [f"{{{TEI_NS}}}p"],
    )
    if (
        project_paragraphs[0].text != ENCODING_POLICY
        or project_paragraphs[0].attrib
        or len(project_paragraphs[0]) != 0
    ):
        raise ValueError("candidate TEI heading-map policy header differs")

    if outer_text.attrib != {XML_LANG: "en"}:
        raise ValueError("candidate TEI outer text language binding differs")
    outer_children = _xml_children_exact(outer_text, [f"{{{TEI_NS}}}group"])
    selected_text_nodes = _xml_children_exact(outer_children[0], [f"{{{TEI_NS}}}text"])
    selected_text = selected_text_nodes[0]
    if selected_text.attrib != {XML_ID: work_id}:
        raise ValueError("candidate TEI nested work identity or inherited-language scope differs")
    selected_text_children = _xml_children_exact(selected_text, [f"{{{TEI_NS}}}body"])
    body = selected_text_children[0]
    witnesses = _xml_children_exact(body, [f"{{{TEI_NS}}}div"])
    witness = witnesses[0]
    if witness.attrib != {"type": "retained-text-witness", "corresp": f"#source-{work_id}"}:
        raise ValueError("candidate TEI retained-witness scope differs")

    expected_events = _source_events(expected_units, heading_roles, title_owner)
    if work_id == "carey-enquiry":
        table_line_values, table_block_numbers, table_line_numbers = _verify_carey_table_nodes(
            witness,
            work_id,
            table_specs,
            _source_lines_from_regex(expected_source_bytes),
            expected_units,
            expected_events,
        )
    else:
        if table_specs or witness.findall(f".//{{{TEI_NS}}}table"):
            raise ValueError("candidate TEI contains a table outside the Carey source map")
        table_line_values, table_block_numbers, table_line_numbers = {}, set(), set()

    allowed_content_tags = {
        f"{{{TEI_NS}}}div",
        f"{{{TEI_NS}}}head",
        f"{{{TEI_NS}}}p",
        f"{{{TEI_NS}}}seg",
        f"{{{TEI_NS}}}lb",
        f"{{{TEI_NS}}}space",
        f"{{{TEI_NS}}}table",
        f"{{{TEI_NS}}}row",
        f"{{{TEI_NS}}}cell",
        f"{{{TEI_NS}}}anchor",
        f"{{{TEI_NS}}}ref",
    }
    for node in witness.iterdescendants():
        if node.tag not in allowed_content_tags:
            raise ValueError("candidate TEI contains an unaccounted content element")
        if node.text not in (None, "") and node.tag not in {
            f"{{{TEI_NS}}}seg",
            f"{{{TEI_NS}}}ref",
        }:
            raise ValueError("candidate TEI contains unaccounted mixed content")

    blocks_by_number = {
        int(unit["block_number"]): unit["rows"]
        for unit in expected_units
        if unit["kind"] == "block"
    }
    expected_block_ids = {
        f"{work_id}-block-{number:05d}" for number in blocks_by_number
    }
    block_nodes: dict[int, etree._Element] = {}
    for node in witness.iterdescendants():
        if node.tag != f"{{{TEI_NS}}}div":
            continue
        block_type = str(node.get("type", ""))
        if block_type not in {"source-block", "source-heading-section"}:
            raise ValueError("candidate TEI contains a division outside the source-block map")
        try:
            block_number = int(str(node.get("n")))
        except ValueError as exc:
            raise ValueError("candidate TEI source block number is invalid") from exc
        if (
            node.get(XML_ID) != f"{work_id}-block-{block_number:05d}"
            or block_number not in blocks_by_number
            or block_number in block_nodes
        ):
            raise ValueError("candidate TEI source-block identity differs from source inventory")
        block_nodes[block_number] = node
    table_anchors: dict[int, etree._Element] = {}
    for node in witness.iterdescendants():
        if node.tag != f"{{{TEI_NS}}}anchor":
            continue
        if node.get("type") != "source-block-start":
            raise ValueError("candidate TEI contains an unaccounted table anchor")
        try:
            block_number = int(str(node.get(XML_ID)).rsplit("-", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError("candidate TEI table source-block anchor identity is invalid") from exc
        if (
            block_number not in table_block_numbers
            or node.get(XML_ID) != f"{work_id}-block-{block_number:05d}"
            or block_number in table_anchors
        ):
            raise ValueError("candidate TEI table source-block anchor differs from source inventory")
        table_anchors[block_number] = node
    expected_table_block_ids = {
        f"{work_id}-block-{number:05d}" for number in table_block_numbers
    }
    if (
        set(block_nodes) != set(blocks_by_number) - table_block_numbers
        or set(table_anchors) != table_block_numbers
        or {str(node.get(XML_ID)) for node in block_nodes.values()} | {
            str(node.get(XML_ID)) for node in table_anchors.values()
        }
        != expected_block_ids
        or {str(node.get(XML_ID)) for node in table_anchors.values()}
        != expected_table_block_ids
    ):
        raise ValueError("candidate TEI source-block inventory is incomplete or duplicated")

    title_block_by_line = {
        int(row["line_number"]): int(unit["block_number"])
        for unit in expected_units
        if unit["kind"] == "block"
        for row in unit["rows"]
        if int(row["line_number"]) in title_owner
    }
    for block_number, block_rows in blocks_by_number.items():
        if block_number in table_block_numbers:
            first_line = int(block_rows[0]["line_number"])
            anchor = table_anchors[block_number]
            row_ancestor = next(
                (
                    ancestor
                    for ancestor in anchor.iterancestors()
                    if ancestor.tag == f"{{{TEI_NS}}}row"
                ),
                None,
            )
            cell_ancestor = anchor.getparent()
            if (
                row_ancestor is None
                or row_ancestor.get("n") != str(first_line)
                or cell_ancestor is None
                or cell_ancestor.tag != f"{{{TEI_NS}}}cell"
            ):
                raise ValueError("candidate TEI table block selector is not at the first source row")
            continue
        block = block_nodes[block_number]
        first_line = int(block_rows[0]["line_number"])
        if first_line in heading_roles:
            level, parent_line = heading_roles[first_line]
            expected_attributes = {
                "type": "source-heading-section",
                "n": str(block_number),
                "subtype": f"level-{level}",
                XML_ID: f"{work_id}-block-{block_number:05d}",
            }
            if parent_line is not None:
                expected_attributes["corresp"] = f"#{work_id}-heading-{parent_line:05d}"
            if block.attrib != expected_attributes:
                raise ValueError("candidate TEI heading section level or parent binding differs")
            direct_children = list(block)
            if not direct_children or direct_children[0].tag != f"{{{TEI_NS}}}head":
                raise ValueError("candidate TEI mapped heading is missing from its section")
            heading = direct_children[0]
            _verify_source_group(
                heading,
                block_rows,
                work_id=work_id,
                expected_tag="head",
                expected_type="source-located-heading",
                expected_subtype=str(level),
                expected_xml_id=f"{work_id}-heading-{first_line:05d}",
            )
            if any(
                child.tag not in {
                    f"{{{TEI_NS}}}space",
                    f"{{{TEI_NS}}}div",
                    f"{{{TEI_NS}}}table",
                }
                for child in direct_children[1:]
            ):
                raise ValueError("candidate TEI heading section has unsupported direct content")
        elif first_line in title_block_by_line:
            owner_line = title_owner[first_line]
            if tuple(int(row["line_number"]) for row in block_rows) != title_groups[owner_line]:
                raise ValueError("candidate TEI title block differs from mapped heading attachment")
            expected_attributes = {
                "type": "source-block",
                "n": str(block_number),
                XML_ID: f"{work_id}-block-{block_number:05d}",
            }
            if block.attrib != expected_attributes:
                raise ValueError("candidate TEI attached-title source block identity differs")
            children = _xml_children_exact(block, [f"{{{TEI_NS}}}head"])
            _verify_source_group(
                children[0],
                block_rows,
                work_id=work_id,
                expected_tag="head",
                expected_type="source-attached-title",
                expected_corresp=f"#{work_id}-heading-{owner_line:05d}",
                expected_xml_id=f"{work_id}-title-{first_line:05d}",
            )
        else:
            expected_attributes = {
                "type": "source-block",
                "n": str(block_number),
                XML_ID: f"{work_id}-block-{block_number:05d}",
            }
            if block.attrib != expected_attributes:
                raise ValueError("candidate TEI ordinary source block identity differs")
            children = _xml_children_exact(block, [f"{{{TEI_NS}}}p"])
            _verify_source_group(
                children[0],
                block_rows,
                work_id=work_id,
                expected_tag="p",
                expected_type=None,
                expected_xml_id=f"{work_id}-unit-{first_line:05d}",
            )

    expected_non_table_events = [
        event
        for event in expected_events
        if int(event["row"]["line_number"]) not in table_line_numbers
    ]
    observed_events = [
        node
        for node in witness.iterdescendants()
        if node.tag == f"{{{TEI_NS}}}space"
        and not any(ancestor.tag == f"{{{TEI_NS}}}table" for ancestor in node.iterancestors())
        or node.tag == f"{{{TEI_NS}}}seg" and node.get("type") == "source-line"
    ]
    if len(observed_events) != len(expected_non_table_events):
        raise ValueError("candidate TEI non-table source-line inventory differs")
    observed_line_values = dict(table_line_values)
    for expected_event, node in zip(expected_non_table_events, observed_events, strict=True):
        row = expected_event["row"]
        line_number = int(row["line_number"])
        if node.tag == f"{{{TEI_NS}}}space":
            if expected_event["kind"] != "blank":
                raise ValueError("candidate TEI blank delimiter is adjacent to the wrong source line")
            if node.attrib != {
                "type": "source-blank-line",
                "unit": "line",
                "quantity": "1",
                "n": str(line_number),
                "subtype": str(row["ending"]),
                XML_ID: f"{work_id}-blank-{line_number:05d}",
            } or len(node) != 0 or node.text not in (None, ""):
                raise ValueError("candidate TEI source blank delimiter differs from retained source")
            if _section_ancestry(node, work_id) != expected_event["ancestry"]:
                raise ValueError("candidate TEI blank delimiter heading ancestry differs from oracle map")
            observed_line_values[line_number] = ("", str(row["ending"]))
        else:
            if expected_event["kind"] != "source-line":
                raise ValueError("candidate TEI source text replaced a blank delimiter")
            if (
                node.get("type") != "source-line"
                or node.get("n") != str(line_number)
                or node.get("subtype") != row["ending"]
                or node.get(XML_ID) != f"{work_id}-line-{line_number:05d}"
                or node.text != row["text"]
                or len(node) != 0
            ):
                raise ValueError("candidate TEI source-line text, order, or ending differs from source")
            block_ancestor = next(
                (
                    ancestor
                    for ancestor in node.iterancestors()
                    if ancestor.tag == f"{{{TEI_NS}}}div"
                    and str(ancestor.get("type", ""))
                    in {"source-block", "source-heading-section"}
                ),
                None,
            )
            expected_block_number = int(expected_event["block_number"])
            if block_ancestor is None or block_ancestor.get(XML_ID) != f"{work_id}-block-{expected_block_number:05d}":
                raise ValueError("candidate TEI source line is detached from its blank-delimited block")
            if _section_ancestry(node, work_id) != expected_event["ancestry"]:
                raise ValueError("candidate TEI heading-to-content ancestry differs from oracle map")
            observed_line_values[line_number] = (str(row["text"]), str(row["ending"]))

    observed_event_order: list[int] = []
    for node in witness.iterdescendants():
        if node.tag == f"{{{TEI_NS}}}row":
            observed_event_order.append(int(str(node.get("n", "0"))))
        elif node.tag == f"{{{TEI_NS}}}space":
            if any(ancestor.tag == f"{{{TEI_NS}}}table" for ancestor in node.iterancestors()):
                continue
            if node.get("type") != "source-blank-line":
                raise ValueError("candidate TEI contains an unaccounted source-space element")
            observed_event_order.append(int(str(node.get("n", "0"))))
        elif node.tag == f"{{{TEI_NS}}}seg":
            segment_type = node.get("type")
            if segment_type == "source-line":
                observed_event_order.append(int(str(node.get("n", "0"))))
            elif segment_type != "source-line-fragment":
                raise ValueError("candidate TEI contains an unaccounted source segment")
    expected_event_order = [int(event["row"]["line_number"]) for event in expected_events]
    if observed_event_order != expected_event_order:
        raise ValueError("candidate TEI source lines, table rows, and blank delimiters are out of order")
    if set(observed_line_values) != set(expected_event_order):
        raise ValueError("candidate TEI source-line and table-row coverage is incomplete")
    observed_line_rows = [observed_line_values[line_number] for line_number in expected_event_order]

    all_heads = witness.findall(f".//{{{TEI_NS}}}head")
    title_group_starts = {lines[0] for lines in title_groups.values() if lines}
    if len(all_heads) != len(heading_roles) + len(title_group_starts):
        raise ValueError("candidate TEI contains a missing or unlisted source heading")
    actual_source_heading_lines = {
        int(head.get("n", "0"))
        for head in all_heads
        if head.get("type") == "source-located-heading"
    }
    actual_title_lines = {
        int(head.get("n", "0"))
        for head in all_heads
        if head.get("type") == "source-attached-title"
    }
    if (
        actual_source_heading_lines != set(heading_roles)
        or actual_title_lines != title_group_starts
    ):
        raise ValueError("candidate TEI heading selections differ from the independent source map")

    reassembled_bytes = b"".join(
        text.encode("utf-8") + _ENDING_BYTES[ending]
        for text, ending in observed_line_rows
    )
    if reassembled_bytes != expected_source_bytes:
        raise ValueError("candidate TEI source byte reassembly mismatch")
    return reassembled_bytes


def _oracle(source_manifest: Any, candidate: Any) -> Mapping[str, object]:
    """Compare actual readable TEI against expectations derived from one source member."""
    work_id = source_manifest.record.get("work_id")
    if not isinstance(work_id, str) or work_id not in ALLOWED_SOURCES:
        raise ValueError("selected-source oracle rejects an out-of-scope work")
    expected_binding = ALLOWED_SOURCES[work_id]
    _assert_raw_scope_before_read(source_manifest, expected_binding)
    _assert_ticket_authority_inventory(source_manifest, expected_binding, work_id)
    source_manifest.verify()
    records = _member_records(source_manifest)
    primary = [item for item in records if item.get("role") == "primary-source"]
    if (
        len(primary) != 1
        or primary[0].get("path") != expected_binding["source_path"]
        or source_manifest.record.get("source_id") != expected_binding["source_id"]
        or source_manifest.record.get("ticket_id") != expected_binding["ticket_id"]
        or source_manifest.record.get("retained_source_path") != expected_binding["source_path"]
        or primary[0].get("name") != "primary-source"
        or primary[0].get("bytes") != expected_binding["source_bytes"]
        or primary[0].get("sha256") != expected_binding["source_sha256"]
    ):
        raise ValueError("selected-source oracle requires the exact ticket-bound source member")
    profile_authority = _authority(source_manifest, "reconstruction-profile")
    policy_authority = _authority(source_manifest, "validation-policy")
    accountability_schema_authority = _authority(source_manifest, "source-accountability-schema")
    xsd_authority = _authority(source_manifest, "tei-p5-xsd")
    teix_xsd_authority = _authority(source_manifest, "tei-p5-xsd-teix")
    xml_xsd_authority = _authority(source_manifest, "tei-p5-xsd-xml")
    package_schema_authority = _authority(source_manifest, "candidate-package-schema")
    if (
        profile_authority.get("role") != "complete-source-feature-profile"
        or policy_authority.get("role") != "independent-validation-policy"
        or accountability_schema_authority.get("role") != "complete-source-accountability-schema"
        or xsd_authority.get("role") != "tei-validation-schema"
        or teix_xsd_authority.get("role") != "tei-validation-schema-dependency"
        or xml_xsd_authority.get("role") != "tei-validation-schema-dependency"
        or package_schema_authority.get("role") != "candidate-package-schema"
    ):
        raise ValueError("selected-source oracle authority roles drifted")
    if (
        xsd_authority.get("path") != "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
        or teix_xsd_authority.get("path")
        != "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"
        or xml_xsd_authority.get("path")
        != "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"
    ):
        raise ValueError("selected-source TEI schema authority paths drifted")

    profile = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "selected work profile")
    policy = _strict_json(source_manifest.authority_path("validation-policy").read_bytes(), "selected validation policy")
    account_schema = _strict_json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "selected accountability schema")
    work_rows = profile.get("works")
    if (
        profile.get("contract") != PROFILE_CONTRACT
        or profile.get("heading_map_contract") != HEADING_MAP_CONTRACT
        or profile.get("source_scope") != "one-work-one-retained-project-gutenberg-member"
        or profile.get("ticket_id") != expected_binding["ticket_id"]
        or profile.get("source_id") != expected_binding["source_id"]
        or profile.get("heading_policy") != HEADING_POLICY
        or "explicit_heading_markers" in profile
        or profile.get("adjacent_retained_member_paths") != []
        or profile.get("source_correction_attestation") != SOURCE_CORRECTION_ATTESTATION
        or not isinstance(work_rows, list)
        or len(work_rows) != 1
        or not isinstance(work_rows[0], dict)
        or work_rows[0].get("work_id") != work_id
        or work_rows[0].get("source_path") != expected_binding["source_path"]
        or work_rows[0].get("source_bytes") != expected_binding["source_bytes"]
        or work_rows[0].get("source_sha256") != expected_binding["source_sha256"]
        or work_rows[0].get("source_url") != expected_binding["source_url"]
        or work_rows[0].get("title") != expected_binding["title"]
        or work_rows[0].get("source_form") != "human-proofread Project Gutenberg plain text"
        or work_rows[0].get("witness_description") != expected_binding["witness_description"]
        or not isinstance(work_rows[0].get("heading_map"), list)
        or profile.get("primary_source_authority_name") != "primary-source"
        or work_id == "carey-enquiry"
        and (
            profile.get("profile_id") != "selected-proofread-37c-094-tables-v3"
            or profile.get("table_map_contract") != CAREY_TABLE_MAP_CONTRACT
        )
        or work_id != "carey-enquiry" and "table_map_contract" in profile
    ):
        raise ValueError("selected-source profile scope, source-quality attestation, or heading map drifted")
    expected_policy_contract = (
        "ocd-selected-source-validation-policy-v3"
        if work_id == "carey-enquiry"
        else "ocd-selected-source-validation-policy-v2"
    )
    if (
        policy.get("contract") != expected_policy_contract
        or policy.get("ticket_id") != expected_binding["ticket_id"]
        or policy.get("work_id") != work_id
        or policy.get("source_path") != expected_binding["source_path"]
        or policy.get("source_scope") != profile["source_scope"]
        or policy.get("source_inventory") != "one explicit primary-source member; no adjacent-source traversal"
    ):
        raise ValueError("selected-source validation policy drifted")
    required_mutations = {
        "false-positive heading for ordinary prose",
        "missing mapped heading",
        "altered mapped heading",
        "detached heading title/content",
        "sourceDesc/reference drift",
        "human-acceptance disclaimer drift",
        "rights-clearance disclaimer drift",
        "blank-delimiter deletion",
        "line-ending mutation",
        "adjacent raw-source authority insertion",
    }
    if work_id == "carey-enquiry":
        required_mutations.update(
            {
                "table-cell-span or role drift",
                "row-continuation detachment",
                "table-group detachment",
                "table-note or footnote attachment drift",
                "table blank-row deletion",
                "table source-cell text drift",
            }
        )
    declared_mutations = policy.get("rejected_mutations")
    if not isinstance(declared_mutations, list) or not required_mutations.issubset(set(declared_mutations)):
        raise ValueError("selected-source validation policy omits required adversarial mutations")

    source_content = source_manifest.authority_path(str(profile["primary_source_authority_name"])).read_bytes()
    source_digest = _sha(source_content)
    work = work_rows[0]
    if (
        len(source_content) != work.get("source_bytes")
        or source_digest != work.get("source_sha256")
        or len(source_content) != primary[0].get("bytes")
        or source_digest != primary[0].get("sha256")
    ):
        raise ValueError("selected source bytes do not match the bound source manifest and profile")

    rows = _source_lines_from_regex(source_content)
    units = _expected_units(rows)
    heading_roles, title_owner, title_groups = _verified_heading_map(
        work_id,
        work,
        rows,
        units,
    )
    table_specs = _carey_table_specs(work, rows) if work_id == "carey-enquiry" else []
    expected_table_accounting, table_line_roles = _oracle_table_accounting(
        work_id,
        table_specs,
        rows,
        units,
    )
    tei_bytes = candidate.member_bytes("content.tei.xml")
    reassembled_bytes = _check_candidate_tei(
        tei_bytes,
        profile,
        expected_binding,
        units,
        source_content,
        heading_roles,
        title_owner,
        title_groups,
        table_specs,
    )
    if reassembled_bytes != source_content:
        raise ValueError("candidate TEI source byte reassembly mismatch")
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    schema_parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    schema_document = etree.parse(str(xsd_path), parser=schema_parser)
    schema_root = schema_document.getroot()
    schema_imports = schema_root.findall("{http://www.w3.org/2001/XMLSchema}import")
    import_targets = {item.get("schemaLocation") for item in schema_imports}
    if import_targets != {"tei_all_teix.xsd", "tei_all_xml.xsd"}:
        raise ValueError("bound TEI schema import inventory differs from explicit dependencies")
    for authority_name, authority in (
        ("tei-p5-xsd-teix", teix_xsd_authority),
        ("tei-p5-xsd-xml", xml_xsd_authority),
    ):
        imported_path = (xsd_path.parent / str(authority.get("path")).rsplit("/", 1)[-1]).resolve(strict=True)
        if imported_path != source_manifest.authority_path(authority_name):
            raise ValueError(f"bound TEI schema import does not resolve to {authority_name!r}")
    tei_schema = etree.XMLSchema(schema_document)
    tei_document = etree.fromstring(
        tei_bytes,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
    )
    tei_schema.assertValid(tei_document)

    expected_lines, expected_blocks = _accountability_lines(
        units,
        work_id,
        heading_roles,
        title_owner,
        table_line_roles,
    )
    accounting_bytes = candidate.member_bytes("source-accountability.json")
    accounting = _strict_json(accounting_bytes, "source accountability")
    errors = list(Draft202012Validator(account_schema).iter_errors(accounting))
    if errors:
        raise ValueError(f"source accountability schema rejected candidate: {errors[0].message}")
    if accounting_bytes != _canonical(accounting):
        raise ValueError("source accountability is not canonical JSON")
    expected_account_contract = (
        "ocd-selected-source-accountability-v3"
        if work_id == "carey-enquiry"
        else "ocd-selected-source-accountability-v2"
    )
    if (
        accounting.get("contract") != expected_account_contract
        or accounting.get("schema") != Path(str(accountability_schema_authority["path"])).name
        or accounting.get("profile_id") != profile.get("profile_id")
        or accounting.get("ticket_id") != expected_binding["ticket_id"]
        or accounting.get("assigned_work_count") != 1
        or accounting.get("assigned_member_count") != 1
        or accounting.get("adjacent_member_count") != 0
        or accounting.get("adjacent_retained_member_accounting") != []
    ):
        raise ValueError("candidate source-accountability scope is invalid")
    accounted_work = accounting.get("works")
    if not isinstance(accounted_work, list) or len(accounted_work) != 1:
        raise ValueError("source accountability must contain exactly the selected work")
    work_account = accounted_work[0]
    if (
        work_account.get("ticket_id") != expected_binding["ticket_id"]
        or work_account.get("work_id") != work_id
        or work_account.get("source_path") != expected_binding["source_path"]
        or work_account.get("source_sha256") != source_digest
        or work_account.get("line_count") != len(rows)
        or work_account.get("nonblank_line_count") != sum(text != "" for text, _ in rows)
        or work_account.get("blank_line_count") != sum(text == "" for text, _ in rows)
        or work_account.get("source_block_count") != len(expected_blocks)
        or work_account.get("explicit_heading_count")
        != sum(len(block["heading_lines"]) for block in expected_blocks)
        or work_account.get("character_count") != sum(len(text) for text, _ in rows)
        or work_account.get("line_ending_counts")
        != {
            ending: sum(observed == ending for _, observed in rows)
            for ending in ("crlf", "lf", "cr", "none")
        }
        or work_account.get("source_block_selector_contract")
        != f"#{work_id}-block-%05d"
        or work_account.get("source_line_selector_contract")
        != f"#{work_id}-line-%05d"
        or work_account.get("source_lines") != expected_lines
        or work_account.get("source_blocks") != expected_blocks
        or work_id == "carey-enquiry"
        and work_account.get("source_tables") != expected_table_accounting
        or work_id != "carey-enquiry" and "source_tables" in work_account
        or accounting.get("total_line_count") != len(rows)
        or accounting.get("omitted_line_count") != 0
        or accounting.get("duplicate_line_count") != 0
        or accounting.get("source_byte_reassembly")
        != "exact UTF-8 source line text plus its recorded CR/LF terminator"
        or accounting.get("block_mapping") != ACCOUNTABILITY_BLOCK_MAPPING
        or accounting.get("candidate_status") != "nonaccepted"
        or accounting.get("human_review_required") is not True
        or accounting.get("publication_ready") is not False
    ):
        raise ValueError("source-accountability ledger differs from independent source inventory")
    source_member_rows = accounting.get("source_members")
    if (
        not isinstance(source_member_rows, list)
        or len(source_member_rows) != 1
        or source_member_rows[0].get("path") != expected_binding["source_path"]
        or source_member_rows[0].get("bytes") != len(source_content)
        or source_member_rows[0].get("sha256") != source_digest
    ):
        raise ValueError("source-accountability member set differs from exact retained source")

    provenance = _strict_json(candidate.member_bytes("provenance.json"), "candidate provenance")
    if (
        provenance.get("contract") != "ocd-selected-source-provenance-v1"
        or provenance.get("source_manifest_sha256") != source_manifest.sha256
        or provenance.get("ticket_id") != expected_binding["ticket_id"]
        or provenance.get("profile_id") != profile.get("profile_id")
        or provenance.get("text_authority")
        != "the one primary-source member declared by this ticket-bound SourceManifest"
        or provenance.get("source_correction_attestation")
        != profile.get("source_correction_attestation")
        or provenance.get("human_review") != "required"
        or provenance.get("accepted_ir") != "not_accepted"
        or provenance.get("publication") != "not_ready"
        or provenance.get("rights", {}).get("clearance") != "not assessed by this technical reconstruction"
        or provenance.get("rights", {}).get("provider_attribution")
        != "Distributed Proofreaders attribution retained from the bound source record"
    ):
        raise ValueError("candidate provenance or nonacceptance state drifted")
    provenance_work = provenance.get("work")
    if (
        not isinstance(provenance_work, Mapping)
        or provenance_work.get("work_id") != work_id
        or provenance_work.get("ticket_work_label") != expected_binding["title"]
        or provenance_work.get("source_path") != expected_binding["source_path"]
        or provenance_work.get("source_sha256") != source_digest
        or provenance_work.get("witness_description") != work.get("witness_description")
    ):
        raise ValueError("candidate provenance work identity differs from the selected source")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-local-readme").read_bytes():
        raise ValueError("candidate attribution README differs from bound source-local README")
    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    unresolved = profile.get("unresolved")
    if not isinstance(unresolved, list) or unresolved_bytes != b"".join(_canonical(item) for item in unresolved):
        raise ValueError("candidate unresolved ledger differs from bound work profile")
    manifest = candidate.manifest
    if (
        manifest.get("contract") != "ocd-candidate-package-v1"
        or manifest.get("status") != "nonaccepted"
        or manifest.get("source_id") != expected_binding["source_id"]
        or manifest.get("source_manifest", {}).get("sha256") != source_manifest.sha256
    ):
        raise ValueError("candidate package does not bind the exact nonaccepted source selection")

    oracle_path = Path(__file__).resolve(strict=True)
    implementation_sha256 = _sha(oracle_path.read_bytes())
    import_closure = _sha(
        _canonical(
            [
                {
                    "path": "build/tei/gutenberg_proofread_selected_oracle.py",
                    "sha256": implementation_sha256,
                }
            ]
        )
    )
    expected_bindings = {
        "profile_sha256": profile_authority.get("sha256"),
        "package_schema_sha256": package_schema_authority.get("sha256"),
        "source_sha256": source_digest,
        "xsd_sha256": xsd_authority.get("sha256"),
        "policy_sha256": policy_authority.get("sha256"),
    }
    findings = [
        "exactly one ticket-bound retained source member was selected",
        "every source line, blank-line delimiter, and CR/LF ending is accounted for in order",
        "exact source-located headings, mapped title attachments, blank delimiters, and section ancestry match independent source expectations",
        "readable TEI and its source-accountability ledger match independent source-derived expectations",
        "the TEI document validates against the bound TEI P5 schema",
        "candidate remains nonaccepted; human acceptance, rights clearance, and publication are not asserted",
    ]
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha256,
        "import_closure_sha256": import_closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": expected_bindings["profile_sha256"],
        "package_schema_sha256": expected_bindings["package_schema_sha256"],
        "source_sha256": expected_bindings["source_sha256"],
        "xsd_sha256": expected_bindings["xsd_sha256"],
        "policy_sha256": expected_bindings["policy_sha256"],
        "findings": findings,
    }
    if candidate.manifest.get("source_manifest", {}).get("path") != source_manifest.path.relative_to(source_manifest.repository_root).as_posix():
        raise ValueError("candidate source manifest path differs from selected work manifest")
    for name, expected in expected_bindings.items():
        if result[name] != expected:
            raise ValueError(f"selected-source oracle {name} authority mismatch")
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
