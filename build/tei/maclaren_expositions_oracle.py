"""Independent source-to-TEI oracle for the bounded LIB-073 Maclaren cohort."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
from typing import Mapping
from xml.etree import ElementTree as ET

from jsonschema import Draft202012Validator
from lxml import etree as lxml_etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-lib073-maclaren-expositions-independent-source-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_TEI_ROOT = f"{{{_TEI}}}TEI"
_XML = "http://www.w3.org/XML/1998/namespace"
_XML_ID = f"{{{_XML}}}id"
_XML_SPACE = f"{{{_XML}}}space"
_BOM = b"\xef\xbb\xbf"
_START = "*** START OF THE PROJECT GUTENBERG EBOOK "
_END = "*** END OF THE PROJECT GUTENBERG EBOOK "
_NOTE_MARKER = re.compile(r"\[\d+\]")
_INLINE_SPAN = re.compile(r"_[^_\r\n]+_")
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _closure(root: Path) -> str:
    paths = (
        Path(__file__).resolve(strict=True),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/verifier.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    )
    rows = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    ]
    return _sha(_canonical(rows))


def _authority(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _json_object(data: bytes, label: str) -> dict[str, object]:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _source_set_sha256(source_manifest: SourceManifest) -> str:
    members = [
        {key: item[key] for key in ("name", "path", "bytes", "sha256")}
        for item in source_manifest.record["authorities"]
        if item["role"] == "primary-source"
    ]
    members.sort(key=lambda item: (str(item["path"]), str(item["name"])))
    if len(members) != 15:
        raise ValueError("Maclaren independent oracle requires exactly 15 primary sources")
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _read_member_lines(data: bytes) -> list[dict[str, object]]:
    """Read the retained file independently through a binary stream."""

    if not data.startswith(_BOM):
        raise ValueError("Independent source reader found no UTF-8 BOM")
    stream = io.BytesIO(data)
    records: list[dict[str, object]] = []
    number = 0
    while True:
        byte_start = stream.tell()
        chunk = stream.readline()
        if chunk == b"":
            break
        number += 1
        if not chunk.endswith(b"\r\n") or chunk.count(b"\n") != 1 or chunk.count(b"\r") != 1:
            raise ValueError(f"Independent source reader found non-CRLF framing at line {number}")
        body = chunk[:-2]
        content = body
        content_byte_start = byte_start
        if number == 1:
            if not body.startswith(_BOM):
                raise ValueError("Independent source reader lost first-line BOM")
            content = body[3:]
            content_byte_start += 3
        text = content.decode("utf-8", errors="strict")
        byte_end = stream.tell()
        records.append(
            {
                "line": number,
                "text": text,
                "byte_start": byte_start,
                "content_byte_start": content_byte_start,
                "content_byte_end": byte_start + len(body),
                "byte_end_exclusive": byte_end,
                "terminator": "CRLF",
                "source_line_sha256": _sha(chunk),
                "decoded_text_sha256": _sha(text.encode("utf-8")),
            }
        )
    if not records or stream.tell() != len(data):
        raise ValueError("Independent source reader did not cover the complete member")
    return records


def _uppercase_line(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and any(char.isalpha() for char in stripped) and stripped.upper() == stripped)


def _source_observations(lines: list[str]) -> dict[str, object]:
    start = [i for i, text in enumerate(lines, 1) if text.startswith(_START)]
    end = [i for i, text in enumerate(lines, 1) if text.startswith(_END)]
    contents = [i for i, text in enumerate(lines, 1) if text.strip() == "CONTENTS"]
    license_markers = [i for i, text in enumerate(lines, 1) if "START: FULL LICENSE" in text]
    metadata_lines = lines[: start[0] - 1] if len(start) == 1 else lines[:80]
    titles = [
        (i, text[len("Title:") :].strip())
        for i, text in enumerate(metadata_lines, 1)
        if text.startswith("Title:")
    ]
    authors = [
        (i, text[len("Author:") :].strip())
        for i, text in enumerate(metadata_lines, 1)
        if text.startswith("Author:")
    ]
    languages = [
        (i, text[len("Language:") :].strip())
        for i, text in enumerate(metadata_lines, 1)
        if text.startswith("Language:")
    ]
    credits = [
        i
        for i, text in enumerate(metadata_lines, 1)
        if text.startswith("Credits:") or text.startswith("E-text prepared by")
    ]
    return {
        "start_marker_lines": start,
        "end_marker_lines": end,
        "contents_lines": contents,
        "license_marker_lines": license_markers,
        "title_lines": titles,
        "author_lines": authors,
        "language_lines": languages,
        "credit_lines": credits,
        "empty_line_count": sum(text == "" for text in lines),
        "whitespace_only_line_count": sum(text != "" and text.isspace() for text in lines),
        "uppercase_line_count": sum(_uppercase_line(text) for text in lines),
        "uppercase_line_count_within_pg_wrapper": sum(
            _uppercase_line(text)
            for index, text in enumerate(lines, 1)
            if len(start) == 1 and len(end) == 1 and start[0] <= index <= end[0]
        ),
        "bracketed_digit_marker_lines": [
            index for index, text in enumerate(lines, 1) if _NOTE_MARKER.search(text)
        ],
        "underscore_delimited_inline_span_count": sum(
            len(_INLINE_SPAN.findall(text)) for text in lines
        ),
    }


def _inventory_members(data: bytes) -> tuple[list[tuple[str, str, str]], list[str]]:
    text = data.decode("utf-8", errors="strict")
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("## Alexander Maclaren"))
    except StopIteration as exc:
        raise ValueError("Independent inventory scan cannot locate Maclaren section") from exc
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end])
    rows: list[tuple[str, str, str]] = []
    for line in lines[start:end]:
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if len(fields) == 3 and fields[0].isdigit() and fields[2].startswith(
            "raw/gutenberg/sermons/maclaren/pg"
        ):
            rows.append((fields[0], fields[1], fields[2]))
    exclusion = re.search(
        r"Not included:\*{0,2}\s*PG#(\d+),\s*PG#(\d+),\s*PG#(\d+).*?different series\s+by different authors",
        section,
        re.IGNORECASE | re.DOTALL,
    )
    if exclusion is None:
        raise ValueError("Independent inventory scan cannot substantiate the three exclusions")
    return rows, list(exclusion.groups())


def _profile_and_sources(
    source_manifest: SourceManifest,
) -> tuple[dict[str, object], bytes, dict[str, object], bytes, list[dict[str, object]]]:
    record = source_manifest.record
    if record.get("work_id") != "maclaren-expositions" or record.get("ticket_id") != "LIB-073":
        raise ValueError("Independent Maclaren oracle received another route identity")
    profile_bytes = _authority(source_manifest, "reconstruction-profile")
    profile = _json_object(profile_bytes, "Maclaren profile")
    policy_bytes = _authority(source_manifest, "validation-policy")
    policy = _json_object(policy_bytes, "Maclaren validation policy")
    if (
        profile.get("contract") != "ocd-maclaren-expositions-profile-v1"
        or profile.get("work_id") != "maclaren-expositions"
        or profile.get("ticket_id") != "LIB-073"
        or policy.get("contract") != "ocd-maclaren-expositions-validation-policy-v1"
        or policy.get("work_id") != "maclaren-expositions"
        or policy.get("ticket_id") != "LIB-073"
    ):
        raise ValueError("Independent Maclaren profile or policy binding changed")
    inventory_bytes = _authority(source_manifest, "source-inventory")
    inventory_binding = profile.get("scope", {}).get("source_inventory")
    if not isinstance(inventory_binding, dict) or inventory_binding != {
        "path": "raw/gutenberg/sermons/PG_SERMON_INVENTORY.md",
        "bytes": len(inventory_bytes),
        "sha256": _sha(inventory_bytes),
    }:
        raise ValueError("Independent Maclaren inventory authority changed")
    inventory_rows, excluded_ids = _inventory_members(inventory_bytes)
    members = profile.get("members")
    if not isinstance(members, list) or len(members) != 15:
        raise ValueError("Independent profile must declare all 15 ordered members")
    expected_inventory_rows = [
        (str(member["pg_id"]), str(member["inventory_coverage"]), str(member["path"]))
        for member in members
    ]
    if inventory_rows != expected_inventory_rows:
        raise ValueError("Independent source inventory and profile member order differ")
    exclusions = profile.get("excluded_inventory_items")
    if (
        not isinstance(exclusions, list)
        or [str(item.get("pg_id")) for item in exclusions] != excluded_ids
        or any(
            item.get("disposition") != "excluded-different-series"
            or "different authors" not in str(item.get("reason", ""))
            for item in exclusions
        )
    ):
        raise ValueError("Independent source-inventory exclusions are incomplete")

    authorities = [
        item for item in record.get("authorities", ()) if item.get("role") == "primary-source"
    ]
    if len(authorities) != 15:
        raise ValueError("Independent source manifest does not bind exactly 15 primary members")
    source_members: list[dict[str, object]] = []
    for order, (profile_member, authority) in enumerate(zip(members, authorities, strict=True), 1):
        if (
            authority.get("name") != f"retained-pg-{profile_member['pg_id']}"
            or authority.get("path") != profile_member["path"]
            or authority.get("bytes") != profile_member["bytes"]
            or authority.get("sha256") != profile_member["sha256"]
            or profile_member.get("inventory_order") != order
        ):
            raise ValueError(f"Independent source manifest member binding changed at order {order}")
        data = source_manifest.authority_path(str(authority["name"])).read_bytes()
        if len(data) != profile_member["bytes"] or _sha(data) != profile_member["sha256"]:
            raise ValueError(f"Independent retained member {profile_member['pg_id']} hash mismatch")
        records = _read_member_lines(data)
        lines = [str(item["text"]) for item in records]
        facts = _source_observations(lines)
        if len(records) != profile_member["physical_line_count"]:
            raise ValueError(f"Independent physical-line count changed for PG {profile_member['pg_id']}")
        profile_facts = (
            "start_marker_lines",
            "end_marker_lines",
            "contents_lines",
            "empty_line_count",
            "whitespace_only_line_count",
            "uppercase_line_count",
            "uppercase_line_count_within_pg_wrapper",
            "bracketed_digit_marker_lines",
            "underscore_delimited_inline_span_count",
        )
        if any(facts[name] != profile_member.get(name) for name in profile_facts):
            raise ValueError(f"Independent source feature census changed for PG {profile_member['pg_id']}")
        if (
            len(facts["start_marker_lines"]) != 1
            or len(facts["end_marker_lines"]) != 1
            or facts["start_marker_lines"][0] >= facts["end_marker_lines"][0]
            or len(facts["license_marker_lines"]) != 1
            or facts["license_marker_lines"] != [profile_member["full_license_line"]]
            or facts["license_marker_lines"][0] <= facts["end_marker_lines"][0]
            or facts["title_lines"] != [
                (next(i for i, line in enumerate(lines[:80], 1) if line.startswith("Title:")), profile_member["title_observation"])
            ]
            or facts["author_lines"] != [(profile_member["author_line"], profile_member["author_observation"])]
            or facts["language_lines"] != [(profile_member["language_line"], profile_member["language_observation"])]
            or facts["credit_lines"] != [profile_member["credits_line"]]
        ):
            raise ValueError(f"Independent source title, credit, or wrapper evidence changed for PG {profile_member['pg_id']}")
        source_members.append(
            {
                "profile": profile_member,
                "authority": authority,
                "bytes": data,
                "records": records,
                "lines": lines,
                "facts": facts,
            }
        )
    totals = {
        "bytes": sum(len(member["bytes"]) for member in source_members),
        "physical_line_count": sum(len(member["records"]) for member in source_members),
        "exact_empty_line_count": sum(member["facts"]["empty_line_count"] for member in source_members),
        "whitespace_only_line_count": sum(member["facts"]["whitespace_only_line_count"] for member in source_members),
    }
    if totals != {
        key: profile["aggregate"][key]
        for key in ("bytes", "physical_line_count", "exact_empty_line_count", "whitespace_only_line_count")
    }:
        raise ValueError("Independent aggregate source census changed")
    discrepancy = profile.get("count_discrepancy")
    policy_counts = policy.get("count_policy")
    if (
        not isinstance(discrepancy, dict)
        or not isinstance(policy_counts, dict)
        or discrepancy.get("legacy_config_claim") != 1263
        or discrepancy.get("legacy_projection_records") != 1255
        or discrepancy.get("difference") != 8
        or discrepancy.get("source_verified_exposition_count") is not None
        or discrepancy.get("resolution") != "unresolved-from-retained-source"
        or discrepancy.get("route_uses_either_count_as_a_selection_limit") is not False
        or policy_counts.get("config_claim") != 1263
        or policy_counts.get("generated_projection_records") != 1255
        or policy_counts.get("difference") != 8
        or policy_counts.get("source_verified_exposition_count") is not None
        or policy_counts.get("reconciliation") != "unresolved-from-retained-source"
        or policy_counts.get("may_select_or_drop_source_units") is not False
    ):
        raise ValueError("Independent count policy no longer preserves the exact-eight uncertainty")
    return profile, profile_bytes, policy, policy_bytes, source_members


def _line_identifier(pg_id: str, line: int) -> str:
    return f"pg{pg_id}-line-{line:06d}"


def _line_kind(text: str, number: int, start: int, end: int) -> str:
    if text == "":
        return "empty"
    if text.isspace():
        return "whitespace"
    if number == start or number == end:
        return "wrapper"
    if _uppercase_line(text):
        return "uppercase"
    return "prose"


def _children_without_tail(element: ET.Element) -> list[ET.Element]:
    if element.text not in (None, ""):
        raise ValueError(f"Unexpected container text in TEI {element.tag}")
    children = list(element)
    if any(child.tail not in (None, "") for child in children):
        raise ValueError(f"Unexpected TEI inter-element text under {element.tag}")
    return children


def _assert_line_element(
    node: ET.Element,
    *,
    local: str,
    attributes: dict[str, str],
    text: str | None,
    label: str,
) -> None:
    if node.tag != f"{{{_TEI}}}{local}" or node.attrib != attributes:
        raise ValueError(f"TEI source-line carrier shape changed at {label}")
    if list(node) or node.text != text or node.tail not in (None, ""):
        raise ValueError(f"TEI source-line text or nesting changed at {label}")


def _check_region_lines(
    region: ET.Element,
    *,
    profile_member: Mapping[str, object],
    source_member: Mapping[str, object],
    region_record: Mapping[str, object],
) -> int:
    pg_id = str(profile_member["pg_id"])
    first = int(region_record["line_start"])
    last = int(region_record["line_end_inclusive"])
    records = source_member["records"][first - 1 : last]
    children = _children_without_tail(region)
    child_index = 0
    line_index = 0
    mapped_count = 0
    start = int(source_member["facts"]["start_marker_lines"][0])
    end = int(source_member["facts"]["end_marker_lines"][0])

    while line_index < len(records):
        record = records[line_index]
        number = int(record["line"])
        text = str(record["text"])
        kind = _line_kind(text, number, start, end)
        source_id = _line_identifier(pg_id, number)
        if child_index >= len(children):
            raise ValueError(f"TEI omits PG {pg_id} source line {number}")
        if kind == "prose":
            run: list[dict[str, object]] = []
            while line_index + len(run) < len(records):
                next_record = records[line_index + len(run)]
                if _line_kind(
                    str(next_record["text"]),
                    int(next_record["line"]),
                    start,
                    end,
                ) != "prose":
                    break
                run.append(next_record)
            paragraph = children[child_index]
            if paragraph.tag != f"{{{_TEI}}}p" or paragraph.attrib or paragraph.text not in (None, ""):
                raise ValueError(f"PG {pg_id} prose paragraph grouping changed at line {number}")
            paragraph_nodes = list(paragraph)
            if len(paragraph_nodes) != len(run) * 2 - 1:
                raise ValueError(f"PG {pg_id} prose line breaks changed at line {number}")
            for offset, line_record in enumerate(run):
                physical_line = int(line_record["line"])
                line_text = str(line_record["text"])
                segment = paragraph_nodes[offset * 2]
                line_id = _line_identifier(pg_id, physical_line)
                _assert_line_element(
                    segment,
                    local="seg",
                    attributes={
                        "type": "source-physical-line",
                        "n": str(physical_line),
                        _XML_ID: line_id,
                        _XML_SPACE: "preserve",
                    },
                    text=line_text,
                    label=f"PG {pg_id} line {physical_line}",
                )
                if offset:
                    line_break = paragraph_nodes[offset * 2 - 1]
                    _assert_line_element(
                        line_break,
                        local="lb",
                        attributes={"n": str(physical_line)},
                        text=None,
                        label=f"PG {pg_id} break before line {physical_line}",
                    )
                mapped_count += 1
            child_index += 1
            line_index += len(run)
            continue

        carrier = children[child_index]
        if kind == "empty":
            _assert_line_element(
                carrier,
                local="milestone",
                attributes={
                    "unit": "source-empty-line",
                    "n": str(number),
                    _XML_ID: source_id,
                },
                text=None,
                label=f"PG {pg_id} empty line {number}",
            )
        elif kind == "whitespace":
            if (
                carrier.tag != f"{{{_TEI}}}ab"
                or carrier.attrib != {"type": "source-whitespace-line", _XML_SPACE: "preserve"}
                or carrier.text not in (None, "")
            ):
                raise ValueError(f"PG {pg_id} whitespace-only line {number} changed")
            segments = list(carrier)
            if len(segments) != 1:
                raise ValueError(f"PG {pg_id} whitespace-only line {number} lost its line carrier")
            _assert_line_element(
                segments[0],
                local="seg",
                attributes={
                    "type": "source-physical-line",
                    "n": str(number),
                    _XML_ID: source_id,
                    _XML_SPACE: "preserve",
                },
                text=text,
                label=f"PG {pg_id} whitespace-only line {number}",
            )
        elif kind == "wrapper":
            _assert_line_element(
                carrier,
                local="ab",
                attributes={
                    "type": "gutenberg-envelope-marker",
                    "n": str(number),
                    _XML_ID: source_id,
                    _XML_SPACE: "preserve",
                },
                text=text,
                label=f"PG {pg_id} wrapper line {number}",
            )
        else:
            _assert_line_element(
                carrier,
                local="ab",
                attributes={
                    "type": "source-uppercase-line",
                    "n": str(number),
                    _XML_ID: source_id,
                    _XML_SPACE: "preserve",
                },
                text=text,
                label=f"PG {pg_id} uppercase line {number}",
            )
        mapped_count += 1
        child_index += 1
        line_index += 1

    if child_index != len(children):
        raise ValueError(f"PG {pg_id} TEI region contains extra or reordered carriers")
    return mapped_count


def _verify_tei_text(
    tei_bytes: bytes,
    profile: Mapping[str, object],
    source_members: list[dict[str, object]],
) -> int:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    try:
        root = ET.fromstring(tei_bytes, parser=parser)
    except ET.ParseError as exc:
        raise ValueError("Maclaren candidate is not well-formed TEI XML") from exc
    if root.tag != _TEI_ROOT or root.attrib != {_XML_ID: "maclaren-expositions-lib073-source-bound-candidate"}:
        raise ValueError("Maclaren candidate TEI root identity changed")
    if any(not isinstance(node.tag, str) for node in root.iter()):
        raise ValueError("Maclaren TEI contains an unaccounted comment or processing instruction")
    root_children = _children_without_tail(root)
    if [child.tag for child in root_children] != [f"{{{_TEI}}}teiHeader", f"{{{_TEI}}}text"]:
        raise ValueError("Maclaren TEI root header/text structure changed")
    header, text_node = root_children
    header_children = _children_without_tail(header)
    if len(header_children) != 1 or header_children[0].tag != f"{{{_TEI}}}fileDesc":
        raise ValueError("Maclaren TEI header file description changed")
    file_desc = header_children[0]
    file_children = _children_without_tail(file_desc)
    if [node.tag for node in file_children] != [
        f"{{{_TEI}}}titleStmt",
        f"{{{_TEI}}}publicationStmt",
        f"{{{_TEI}}}notesStmt",
        f"{{{_TEI}}}sourceDesc",
    ]:
        raise ValueError("Maclaren TEI file-description sections changed")
    title_stmt, publication, notes_stmt, source_desc = file_children
    title_author = _children_without_tail(title_stmt)
    if (
        [node.tag for node in title_author]
        != [f"{{{_TEI}}}title", f"{{{_TEI}}}author"]
        or title_author[0].text != profile["catalog_title_observation"]
        or title_author[1].text != "Alexander Maclaren"
    ):
        raise ValueError("Maclaren TEI display-title or author observation changed")
    publication_children = _children_without_tail(publication)
    if (
        len(publication_children) != 1
        or publication_children[0].tag != f"{{{_TEI}}}p"
        or publication_children[0].text
        != "Provisional, nonaccepted source-bound reconstruction. Rights review, human acceptance, release selection, and publication authorization have not been performed."
    ):
        raise ValueError("Maclaren TEI acceptance/rights publication boundary changed")
    scope_notes = _children_without_tail(notes_stmt)
    if (
        len(scope_notes) != 1
        or scope_notes[0].tag != f"{{{_TEI}}}note"
        or scope_notes[0].attrib != {"type": "source-scope-boundary"}
        or scope_notes[0].text
        != "The source-native cohort and all file-level boundaries are retained; "
        "its complete printed-edition lineage and exposition count remain unresolved."
    ):
        raise ValueError("Maclaren TEI source scope disclosure changed")
    source_desc_children = _children_without_tail(source_desc)
    if len(source_desc_children) != 1 or source_desc_children[0].tag != f"{{{_TEI}}}listBibl":
        raise ValueError("Maclaren TEI source description changed")
    bibliography = source_desc_children[0]
    bibl_entries = _children_without_tail(bibliography)
    if len(bibl_entries) != len(profile["members"]):
        raise ValueError("Maclaren TEI bibliography does not name all 15 members")
    for profile_member, bibl in zip(profile["members"], bibl_entries, strict=True):
        if (
            bibl.tag != f"{{{_TEI}}}bibl"
            or bibl.attrib != {
                _XML_ID: f"bibl-pg{profile_member['pg_id']}",
                "n": str(profile_member["inventory_order"]),
            }
        ):
            raise ValueError("Maclaren TEI bibliography member order or identity changed")
        parts = _children_without_tail(bibl)
        if [node.tag for node in parts] != [
            f"{{{_TEI}}}title",
            f"{{{_TEI}}}author",
            f"{{{_TEI}}}idno",
            f"{{{_TEI}}}idno",
            f"{{{_TEI}}}note",
        ]:
            raise ValueError(f"Maclaren PG {profile_member['pg_id']} bibliography fields changed")
        if (
            parts[0].text != profile_member["title_observation"]
            or parts[1].text != profile_member["author_observation"]
            or parts[2].text != profile_member["pg_id"]
            or parts[3].text != profile_member["sha256"]
            or parts[4].text != profile_member["path"]
            or parts[2].attrib != {"type": "project-gutenberg-ebook"}
            or parts[3].attrib != {"type": "sha256"}
            or parts[4].attrib != {"type": "retained-path"}
        ):
            raise ValueError(f"Maclaren PG {profile_member['pg_id']} source citation changed")

    text_children = _children_without_tail(text_node)
    if len(text_children) != 1 or text_children[0].tag != f"{{{_TEI}}}body":
        raise ValueError("Maclaren TEI text/body shell changed")
    body = text_children[0]
    member_nodes = _children_without_tail(body)
    if len(member_nodes) != len(profile["members"]):
        raise ValueError("Maclaren TEI body member count changed")
    observed_line_count = 0
    for profile_member, source_member, member_node in zip(
        profile["members"], source_members, member_nodes, strict=True
    ):
        pg_id = str(profile_member["pg_id"])
        if (
            member_node.tag != f"{{{_TEI}}}div"
            or member_node.attrib != {
                "type": "source-member",
                "n": pg_id,
                _XML_ID: f"member-pg{pg_id}",
            }
        ):
            raise ValueError(f"Maclaren TEI source-member order or identity changed at PG {pg_id}")
        region_nodes = _children_without_tail(member_node)
        start = int(source_member["facts"]["start_marker_lines"][0])
        end = int(source_member["facts"]["end_marker_lines"][0])
        ranges = (
            ("provider-preamble", 1, start - 1),
            ("gutenberg-text-and-wrapper", start, end),
            ("post-envelope-license-and-tail", end + 1, len(source_member["records"])),
        )
        if len(region_nodes) != 3:
            raise ValueError(f"Maclaren PG {pg_id} source-region count changed")
        mapped_member_count = 0
        for region_node, (region_type, first, last) in zip(region_nodes, ranges, strict=True):
            if (
                region_node.tag != f"{{{_TEI}}}div"
                or region_node.attrib != {
                    "type": region_type,
                    "n": f"{first}-{last}",
                    _XML_ID: f"member-pg{pg_id}-{region_type}",
                }
            ):
                raise ValueError(f"Maclaren PG {pg_id} region boundary or order changed")
            region_record = {
                "line_start": first,
                "line_end_inclusive": last,
            }
            mapped_member_count += _check_region_lines(
                region_node,
                profile_member=profile_member,
                source_member=source_member,
                region_record=region_record,
            )
        if mapped_member_count != len(source_member["records"]):
            raise ValueError(f"Maclaren PG {pg_id} does not map every physical source line once")
        observed_line_count += mapped_member_count

    all_ids = [node.attrib[_XML_ID] for node in root.iter() if _XML_ID in node.attrib]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Maclaren TEI contains duplicate xml:id values")
    return observed_line_count


def _accountability_record(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    source_members: list[dict[str, object]],
) -> dict[str, object]:
    member_records = []
    for source_member in source_members:
        profile_member = source_member["profile"]
        records = source_member["records"]
        facts = source_member["facts"]
        pg_id = str(profile_member["pg_id"])
        raw_line_inventory = [
            {
                key: line[key]
                for key in (
                    "line",
                    "byte_start",
                    "content_byte_start",
                    "content_byte_end",
                    "byte_end_exclusive",
                    "terminator",
                    "source_line_sha256",
                    "decoded_text_sha256",
                )
            }
            for line in records
        ]
        line_accounting = [
            {
                "line": int(line["line"]),
                "source_line_xml_id": _line_identifier(pg_id, int(line["line"])),
                "disposition": "represented-in-tei",
            }
            for line in records
        ]
        start = int(facts["start_marker_lines"][0])
        end = int(facts["end_marker_lines"][0])
        ranges = (
            ("provider-preamble", 1, start - 1),
            ("gutenberg-text-and-wrapper", start, end),
            ("post-envelope-license-and-tail", end + 1, len(records)),
        )
        regions = []
        for region_type, first, last in ranges:
            subset = records[first - 1 : last]
            if not subset:
                raise ValueError(f"Independent region audit found an empty PG {pg_id} region")
            regions.append(
                {
                    "type": region_type,
                    "line_start": first,
                    "line_end_inclusive": last,
                    "byte_start": int(subset[0]["byte_start"]),
                    "byte_end_exclusive": int(subset[-1]["byte_end_exclusive"]),
                    "line_count": len(subset),
                    "disposition": "represented-in-tei",
                    "first_line_xml_id": _line_identifier(pg_id, first),
                    "last_line_xml_id": _line_identifier(pg_id, last),
                }
            )
        member_records.append(
            {
                "inventory_order": profile_member["inventory_order"],
                "pg_id": pg_id,
                "path": profile_member["path"],
                "bytes": profile_member["bytes"],
                "sha256": profile_member["sha256"],
                "physical_line_count": len(records),
                "leading_utf8_bom": True,
                "line_ending": "CRLF",
                "line_inventory_sha256": _sha(_canonical(raw_line_inventory)),
                "line_accounting_sha256": _sha(_canonical(line_accounting)),
                "represented_line_count": len(records),
                "excluded_line_count": 0,
                "omitted_line_count": 0,
                "duplicate_line_count": 0,
                "start_marker_line": start,
                "end_marker_line": end,
                "full_license_line": facts["license_marker_lines"][0],
                "regions": regions,
            }
        )
    aggregate = profile["aggregate"]
    discrepancy = profile["count_discrepancy"]
    return {
        "contract": "ocd-maclaren-expositions-source-accountability-v1",
        "work_id": "maclaren-expositions",
        "ticket_id": "LIB-073",
        "source_manifest_sha256": source_manifest.sha256,
        "source_set_sha256": _source_set_sha256(source_manifest),
        "source_inventory": {
            **profile["scope"]["source_inventory"],
            "member_count": 15,
        },
        "source_member_count": 15,
        "physical_line_count": aggregate["physical_line_count"],
        "represented_line_count": aggregate["physical_line_count"],
        "excluded_line_count": 0,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "exact_empty_line_count": aggregate["exact_empty_line_count"],
        "whitespace_only_line_count": aggregate["whitespace_only_line_count"],
        "source_members": member_records,
        "inventory_exclusions": profile["excluded_inventory_items"],
        "count_discrepancy": {
            "legacy_config_claim": discrepancy["legacy_config_claim"],
            "legacy_projection_records": discrepancy["legacy_projection_records"],
            "difference": discrepancy["difference"],
            "source_verified_exposition_count": discrepancy["source_verified_exposition_count"],
            "resolution": discrepancy["resolution"],
            "route_uses_either_count_as_a_selection_limit": discrepancy[
                "route_uses_either_count_as_a_selection_limit"
            ],
            "disposition": discrepancy["disposition"],
        },
        "candidate_scope": {
            "status": "complete-retained-member-cohort-provisional",
            "included_member_count": 15,
            "included_source_line_count": aggregate["physical_line_count"],
            "excluded_source_line_count": 0,
            "individual_expositions_segmented": False,
            "source_unit_selection_by_legacy_count": False,
        },
    }


def _provenance_record(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
) -> dict[str, object]:
    authorities = {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]
    }
    return {
        "contract": "ocd-maclaren-expositions-candidate-provenance-v1",
        "status": "nonaccepted",
        "work_id": "maclaren-expositions",
        "ticket_id": "LIB-073",
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_set_sha256": _source_set_sha256(source_manifest),
        "authorities": authorities,
        "scope": {
            "member_count": 15,
            "physical_line_count": 339526,
            "source_unit_selection": "all-retained-member-lines; no exposition segmentation",
        },
        "identity_status": {
            "work_collection_boundary": "bounded-cohort-only; unresolved",
            "edition_relationship": "unresolved",
            "textual_form_and_revision": "unresolved",
            "contributor_role_adoption": "unresolved",
            "source_native_volume_and_book_boundaries": "preserved-as-observations; not-reconciled-to-edition-lineage",
        },
        "count_reconciliation": {
            "config_claim": profile["count_discrepancy"]["legacy_config_claim"],
            "projection_records": profile["count_discrepancy"]["legacy_projection_records"],
            "difference": 8,
            "status": "unresolved-from-retained-source",
        },
        "rights_status": policy["candidate_boundary"]["rights"],
        "acceptance_status": policy["candidate_boundary"]["human_acceptance"],
        "visual_review_status": policy["candidate_boundary"]["visual_review"],
        "release_status": "not-selected",
        "publication_status": policy["candidate_boundary"]["publication"],
        "canonical_data_or_ir_written": False,
    }


def _unresolved_records(profile: Mapping[str, object]) -> list[dict[str, str]]:
    details = profile["boundary_questions"]
    return [
        {
            "id": "maclaren-expositions-count-discrepancy-exact-eight",
            "status": "unresolved",
            "kind": "source-unit-count",
            "detail": profile["count_discrepancy"]["disposition"],
        },
        {
            "id": "maclaren-expositions-work-collection-and-edition-identity",
            "status": "unresolved",
            "kind": "work-and-edition-identity",
            "detail": details["work_collection_and_edition_relationship"],
        },
        {
            "id": "maclaren-expositions-textual-form-and-revision",
            "status": "unresolved",
            "kind": "textual-form",
            "detail": details["textual_form_and_revision"],
        },
        {
            "id": "maclaren-expositions-contributor-role-adoption",
            "status": "unresolved",
            "kind": "identity-and-contributor-roles",
            "detail": details["identity_and_contributor_roles"],
        },
        {
            "id": "maclaren-expositions-rights-review",
            "status": "unresolved",
            "kind": "rights",
            "detail": details["rights"],
        },
        {
            "id": "maclaren-expositions-human-acceptance-and-cvw",
            "status": "unresolved",
            "kind": "human-acceptance-and-visual-review",
            "detail": details["human_acceptance_and_visual_review"],
        },
    ]


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    record = source_manifest.record
    expected_candidate_binding = {
        "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != record.get("source_id")
        or candidate.manifest.get("source_manifest") != expected_candidate_binding
        or candidate.manifest.get("converter") != dict(record["converter"])
        or candidate.manifest.get("package_schema") != dict(record["package_schema"])
    ):
        raise ValueError("Maclaren candidate manifest binding changed")

    profile, profile_bytes, policy, policy_bytes, source_members = _profile_and_sources(
        source_manifest
    )
    if (
        profile.get("catalog_title_observation") != "Expositions of Holy Scripture"
        or any(
            not str(item["title_observation"]).startswith("Expositions of Holy Scripture")
            or item["author_observation"] != "Alexander Maclaren"
            for item in profile["members"]
        )
    ):
        raise ValueError("Maclaren source titles/authors do not support the bounded display labels")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    observed_line_count = _verify_tei_text(tei_bytes, profile, source_members)
    expected_line_total = sum(len(member["records"]) for member in source_members)
    if observed_line_count != expected_line_total:
        raise ValueError("Maclaren independent TEI line count differs from retained source")

    account_bytes = candidate.member_bytes("source-accountability.json")
    expected_account = _accountability_record(source_manifest, profile, source_members)
    account_schema = _json_object(
        _authority(source_manifest, "source-accountability-schema"),
        "Maclaren source-accountability schema",
    )
    account = _json_object(account_bytes, "Maclaren source accountability")
    errors = sorted(Draft202012Validator(account_schema).iter_errors(account), key=str)
    if errors:
        raise ValueError(f"Maclaren source-accountability schema failure: {errors[0].message}")
    if account != expected_account or account_bytes != _canonical(expected_account):
        raise ValueError("Maclaren complete source/member/line accountability changed")

    provenance_bytes = candidate.member_bytes("provenance.json")
    expected_provenance = _provenance_record(source_manifest, profile, policy)
    if provenance_bytes != _canonical(expected_provenance):
        raise ValueError("Maclaren provenance or nonacceptance boundary changed")
    unresolved = candidate.member_bytes("unresolved.jsonl")
    expected_unresolved = b"".join(
        _canonical(item) for item in _unresolved_records(profile)
    )
    if unresolved != expected_unresolved:
        raise ValueError("Maclaren unresolved identity/count/rights/acceptance findings changed")
    if candidate.member_bytes("README.source.md") != _authority(
        source_manifest, "attribution-readme"
    ):
        raise ValueError("Maclaren source-attribution handoff note changed")

    xsd_bytes = _authority(source_manifest, "tei-p5-xsd")
    schema_doc = lxml_etree.parse(
        str(source_manifest.authority_path("tei-p5-xsd")),
        lxml_etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False),
    )
    schema = lxml_etree.XMLSchema(schema_doc)
    tei_doc = lxml_etree.fromstring(
        tei_bytes,
        lxml_etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False),
    )
    if not schema.validate(tei_doc):
        last_error = schema.error_log.last_error
        raise ValueError(f"Maclaren candidate fails the pinned TEI P5 schema: {last_error}")

    schema_authority = next(
        item for item in record["authorities"] if item["role"] == "tei-validation-schema"
    )
    policy_schema = policy.get("tei_schema_authority")
    if (
        not isinstance(policy_schema, dict)
        or policy_schema.get("path") != schema_authority["path"]
        or policy_schema.get("role") != schema_authority["role"]
    ):
        raise ValueError("Maclaren validation policy does not pin the TEI schema authority")

    validator_sha256 = _sha(Path(__file__).read_bytes())
    import_closure_sha256 = _closure(source_manifest.repository_root)
    validator_binding = record["validator"]
    if (
        validator_binding.get("implementation_sha256") != validator_sha256
        or validator_binding.get("import_closure_sha256") != import_closure_sha256
    ):
        raise ValueError("Maclaren independent-oracle implementation or closure pin drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=validator_sha256,
        validator_import_closure_sha256=import_closure_sha256,
        source_sha256=_source_set_sha256(source_manifest),
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(_authority(source_manifest, "candidate-package-schema")),
        xsd_sha256=_sha(xsd_bytes),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
