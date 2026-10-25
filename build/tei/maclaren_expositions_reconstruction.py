"""Lossless readable TEI projection for the bounded LIB-073 PG cohort."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree
from jsonschema import Draft202012Validator

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib073-maclaren-expositions-retained-lines-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
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


def _authority(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _json_authority(source_manifest: SourceManifest, name: str) -> tuple[bytes, dict[str, object]]:
    content = _authority(source_manifest, name)
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} authority must be a JSON object")
    return content, value


def _source_set_sha256(source_manifest: SourceManifest) -> str:
    members = [
        {key: item[key] for key in ("name", "path", "bytes", "sha256")}
        for item in source_manifest.record["authorities"]
        if item["role"] == "primary-source"
    ]
    members.sort(key=lambda item: (str(item["path"]), str(item["name"])))
    if len(members) != 15:
        raise ValueError("Maclaren route requires exactly 15 primary-source authorities")
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _parse_source_lines(data: bytes) -> list[dict[str, object]]:
    """Read exact CRLF records while retaining the initial UTF-8 signature."""

    if not data.startswith(_BOM):
        raise ValueError("Maclaren PG member lost its leading UTF-8 BOM")
    crlf_count = data.count(b"\r\n")
    if crlf_count == 0 or crlf_count != data.count(b"\r") or crlf_count != data.count(b"\n"):
        raise ValueError("Maclaren PG member is not framed only by CRLF")
    chunks = data.split(b"\r\n")
    if chunks[-1] != b"":
        raise ValueError("Maclaren PG member must end with its source CRLF")

    records: list[dict[str, object]] = []
    byte_start = 0
    for number, raw_body in enumerate(chunks[:-1], start=1):
        content_bytes = raw_body
        content_byte_start = byte_start
        if number == 1:
            if not raw_body.startswith(_BOM):
                raise ValueError("Maclaren first line does not begin with its UTF-8 BOM")
            content_bytes = raw_body[len(_BOM) :]
            content_byte_start += len(_BOM)
        text = content_bytes.decode("utf-8", errors="strict")
        if any(
            not (
                codepoint in (0x9, 0xA, 0xD)
                or 0x20 <= codepoint <= 0xD7FF
                or 0xE000 <= codepoint <= 0xFFFD
                or 0x10000 <= codepoint <= 0x10FFFF
            )
            for codepoint in map(ord, text)
        ):
            raise ValueError(f"Maclaren source line {number} has an XML 1.0-forbidden character")
        byte_end = byte_start + len(raw_body) + 2
        records.append(
            {
                "line": number,
                "text": text,
                "byte_start": byte_start,
                "content_byte_start": content_byte_start,
                "content_byte_end": byte_start + len(raw_body),
                "byte_end_exclusive": byte_end,
                "terminator": "CRLF",
                "source_line_sha256": _sha(raw_body + b"\r\n"),
                "decoded_text_sha256": _sha(text.encode("utf-8")),
            }
        )
        byte_start = byte_end
    if byte_start != len(data):
        raise ValueError("Maclaren physical-line inventory does not span exact member bytes")
    return records


def _is_uppercase_source_line(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and any(character.isalpha() for character in stripped) and stripped == stripped.upper())


def _line_id(pg_id: str, line: int) -> str:
    return f"pg{pg_id}-line-{line:06d}"


def _source_feature_census(lines: list[str]) -> dict[str, object]:
    start = [
        number
        for number, text in enumerate(lines, start=1)
        if text.startswith(_START)
    ]
    end = [
        number
        for number, text in enumerate(lines, start=1)
        if text.startswith(_END)
    ]
    contents = [
        number for number, text in enumerate(lines, start=1) if text.strip() == "CONTENTS"
    ]
    license_lines = [
        number
        for number, text in enumerate(lines, start=1)
        if "START: FULL LICENSE" in text
    ]
    metadata_lines = lines[: start[0] - 1] if len(start) == 1 else lines[:80]
    title_lines = [
        (number, text.partition(":")[2].strip())
        for number, text in enumerate(metadata_lines, start=1)
        if text.startswith("Title:")
    ]
    author_lines = [
        (number, text.partition(":")[2].strip())
        for number, text in enumerate(metadata_lines, start=1)
        if text.startswith("Author:")
    ]
    language_lines = [
        (number, text.partition(":")[2].strip())
        for number, text in enumerate(metadata_lines, start=1)
        if text.startswith("Language:")
    ]
    credit_lines = [
        number
        for number, text in enumerate(metadata_lines, start=1)
        if text.startswith("Credits:") or text.startswith("E-text prepared by")
    ]
    return {
        "start_marker_lines": start,
        "end_marker_lines": end,
        "contents_lines": contents,
        "full_license_lines": license_lines,
        "title_lines": title_lines,
        "author_lines": author_lines,
        "language_lines": language_lines,
        "credit_lines": credit_lines,
        "empty_line_count": sum(text == "" for text in lines),
        "whitespace_only_line_count": sum(text != "" and text.isspace() for text in lines),
        "uppercase_line_count": sum(_is_uppercase_source_line(text) for text in lines),
        "uppercase_line_count_within_pg_wrapper": sum(
            _is_uppercase_source_line(text)
            for number, text in enumerate(lines, start=1)
            if len(start) == 1 and len(end) == 1 and start[0] <= number <= end[0]
        ),
        "bracketed_digit_marker_lines": [
            number
            for number, text in enumerate(lines, start=1)
            if _NOTE_MARKER.search(text)
        ],
        "underscore_delimited_inline_span_count": sum(
            len(_INLINE_SPAN.findall(text)) for text in lines
        ),
    }


def _inventory_rows(data: bytes) -> tuple[list[tuple[str, str, str]], list[str]]:
    text = data.decode("utf-8", errors="strict")
    try:
        maclaren = text.split("## Alexander Maclaren", 1)[1].split("\n## ", 1)[0]
    except IndexError as exc:
        raise ValueError("PG sermon inventory lacks the Maclaren section") from exc
    rows = re.findall(
        r"\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*"
        r"(raw/gutenberg/sermons/maclaren/pg\d+\.txt)\s*\|",
        maclaren,
    )
    excluded = re.search(
        r"Not included:\*{0,2}\s*PG#(\d+),\s*PG#(\d+),\s*PG#(\d+).*?different series\s+by different authors",
        maclaren,
        re.IGNORECASE | re.DOTALL,
    )
    if excluded is None:
        raise ValueError("PG sermon inventory no longer explains the three different-series exclusions")
    return rows, list(excluded.groups())


def _validate_route_scope(
    source_manifest: SourceManifest,
    profile: dict[str, object],
    policy: dict[str, object],
) -> list[Mapping[str, object]]:
    record = source_manifest.record
    if record.get("work_id") != "maclaren-expositions" or record.get("ticket_id") != "LIB-073":
        raise ValueError("Maclaren source manifest identity mismatch")
    if (
        profile.get("contract") != "ocd-maclaren-expositions-profile-v1"
        or profile.get("work_id") != record.get("work_id")
        or profile.get("ticket_id") != record.get("ticket_id")
        or policy.get("contract") != "ocd-maclaren-expositions-validation-policy-v1"
        or policy.get("work_id") != record.get("work_id")
        or policy.get("ticket_id") != record.get("ticket_id")
    ):
        raise ValueError("Maclaren profile or validation-policy identity mismatch")
    scope = profile.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("Maclaren profile scope is missing")
    inventory_meta = scope.get("source_inventory")
    if not isinstance(inventory_meta, dict):
        raise ValueError("Maclaren source-inventory binding is missing")
    inventory_bytes = _authority(source_manifest, "source-inventory")
    if (
        inventory_meta.get("path") != "raw/gutenberg/sermons/PG_SERMON_INVENTORY.md"
        or inventory_meta.get("bytes") != len(inventory_bytes)
        or inventory_meta.get("sha256") != _sha(inventory_bytes)
    ):
        raise ValueError("Maclaren PG inventory bytes no longer match the profile")

    members = profile.get("members")
    if not isinstance(members, list) or len(members) != 15:
        raise ValueError("Maclaren profile must bind exactly 15 ordered members")
    inventory_members, excluded_ids = _inventory_rows(inventory_bytes)
    expected_rows = [
        (
            str(item.get("pg_id")),
            str(item.get("inventory_coverage")),
            str(item.get("path")),
        )
        for item in members
        if isinstance(item, dict)
    ]
    if len(expected_rows) != len(members) or inventory_members != expected_rows:
        raise ValueError("Maclaren profile member order or coverage differs from the PG inventory")
    excluded = profile.get("excluded_inventory_items")
    if not isinstance(excluded, list) or [str(item.get("pg_id")) for item in excluded] != excluded_ids:
        raise ValueError("Maclaren inventory exclusions changed or are not explicit")
    if any(
        item.get("disposition") != "excluded-different-series"
        or "different authors" not in str(item.get("reason", ""))
        for item in excluded
    ):
        raise ValueError("Maclaren different-series exclusions lack source-inventory reasons")

    primary = [
        item
        for item in record.get("authorities", ())
        if item.get("role") == "primary-source"
    ]
    if len(primary) != len(members):
        raise ValueError("Maclaren source manifest must bind exactly the 15 profile members")
    for order, (member, authority) in enumerate(zip(members, primary, strict=True), start=1):
        if (
            authority.get("name") != f"retained-pg-{member['pg_id']}"
            or authority.get("path") != member["path"]
            or authority.get("bytes") != member["bytes"]
            or authority.get("sha256") != member["sha256"]
            or member.get("inventory_order") != order
        ):
            raise ValueError(f"Maclaren manifest primary-source binding changed at order {order}")
    return primary


def _verify_member_observations(
    member: Mapping[str, object], data: bytes
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if len(data) != member.get("bytes") or _sha(data) != member.get("sha256"):
        raise ValueError(f"Maclaren retained member {member.get('pg_id')} bytes drifted")
    records = _parse_source_lines(data)
    lines = [str(item["text"]) for item in records]
    facts = _source_feature_census(lines)
    if len(records) != member.get("physical_line_count"):
        raise ValueError(f"Maclaren member {member.get('pg_id')} physical line count changed")
    checks = {
        "start_marker_lines": member.get("start_marker_lines"),
        "end_marker_lines": member.get("end_marker_lines"),
        "contents_lines": member.get("contents_lines"),
        "empty_line_count": member.get("empty_line_count"),
        "whitespace_only_line_count": member.get("whitespace_only_line_count"),
        "uppercase_line_count": member.get("uppercase_line_count"),
        "uppercase_line_count_within_pg_wrapper": member.get("uppercase_line_count_within_pg_wrapper"),
        "bracketed_digit_marker_lines": member.get("bracketed_digit_marker_lines"),
        "underscore_delimited_inline_span_count": member.get("underscore_delimited_inline_span_count"),
    }
    if any(facts[name] != value for name, value in checks.items()):
        raise ValueError(f"Maclaren member {member.get('pg_id')} source-feature census changed")
    if (
        not data.startswith(_BOM)
        or member.get("leading_utf8_bom") is not True
        or member.get("line_ending") != "CRLF"
        or member.get("lone_lf_count") != 0
        or member.get("lone_cr_count") != 0
    ):
        raise ValueError(f"Maclaren member {member.get('pg_id')} encoding or newline profile changed")
    if (
        len(facts["start_marker_lines"]) != 1
        or len(facts["end_marker_lines"]) != 1
        or facts["start_marker_lines"][0] >= facts["end_marker_lines"][0]
        or len(facts["full_license_lines"]) != 1
        or facts["full_license_lines"] != [member.get("full_license_line")]
        or facts["full_license_lines"][0] <= facts["end_marker_lines"][0]
    ):
        raise ValueError(f"Maclaren member {member.get('pg_id')} Gutenberg envelope is ambiguous")
    title = facts["title_lines"]
    author = facts["author_lines"]
    language = facts["language_lines"]
    if (
        len(title) != 1
        or title[0][1] != member.get("title_observation")
        or len(author) != 1
        or author[0] != (member.get("author_line"), member.get("author_observation"))
        or len(language) != 1
        or language[0] != (member.get("language_line"), member.get("language_observation"))
        or facts["credit_lines"] != [member.get("credits_line")]
    ):
        raise ValueError(f"Maclaren member {member.get('pg_id')} title/credit observations changed")
    return records, facts


def _append_line_carrier(region: etree._Element, record: Mapping[str, object], pg_id: str) -> None:
    number = int(record["line"])
    text = str(record["text"])
    source_id = _line_id(pg_id, number)
    start_marker = text.startswith(_START)
    end_marker = text.startswith(_END)
    if text == "":
        etree.SubElement(
            region,
            f"{{{_TEI}}}milestone",
            {
                "unit": "source-empty-line",
                "n": str(number),
                _XML_ID: source_id,
            },
        )
        return
    if text.isspace():
        block = etree.SubElement(
            region,
            f"{{{_TEI}}}ab",
            {"type": "source-whitespace-line", _XML_SPACE: "preserve"},
        )
        segment = etree.SubElement(
            block,
            f"{{{_TEI}}}seg",
            {
                "type": "source-physical-line",
                "n": str(number),
                _XML_ID: source_id,
                _XML_SPACE: "preserve",
            },
        )
        segment.text = text
        return
    if start_marker or end_marker:
        carrier = etree.SubElement(
            region,
            f"{{{_TEI}}}ab",
            {
                "type": "gutenberg-envelope-marker",
                "n": str(number),
                _XML_ID: source_id,
                _XML_SPACE: "preserve",
            },
        )
        carrier.text = text
        return
    if _is_uppercase_source_line(text):
        carrier = etree.SubElement(
            region,
            f"{{{_TEI}}}ab",
            {
                "type": "source-uppercase-line",
                "n": str(number),
                _XML_ID: source_id,
                _XML_SPACE: "preserve",
            },
        )
        carrier.text = text
        return

    paragraph = region[-1] if len(region) and region[-1].tag == f"{{{_TEI}}}p" and region[-1].get("type") is None else None
    if paragraph is None:
        paragraph = etree.SubElement(region, f"{{{_TEI}}}p")
    elif len(paragraph):
        break_node = etree.SubElement(paragraph, f"{{{_TEI}}}lb")
        break_node.set("n", str(number))
    segment = etree.SubElement(
        paragraph,
        f"{{{_TEI}}}seg",
        {
            "type": "source-physical-line",
            "n": str(number),
            _XML_ID: source_id,
            _XML_SPACE: "preserve",
        },
    )
    segment.text = text


def _line_accounting_records(
    records: list[dict[str, object]], pg_id: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    inventory = [
        {
            key: record[key]
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
        for record in records
    ]
    accounting = [
        {
            "line": int(record["line"]),
            "source_line_xml_id": _line_id(pg_id, int(record["line"])),
            "disposition": "represented-in-tei",
        }
        for record in records
    ]
    return inventory, accounting


def _regions(
    records: list[dict[str, object]], facts: Mapping[str, object], pg_id: str
) -> list[dict[str, object]]:
    start_line = int(facts["start_marker_lines"][0])
    end_line = int(facts["end_marker_lines"][0])
    cuts = (
        ("provider-preamble", 1, start_line - 1),
        ("gutenberg-text-and-wrapper", start_line, end_line),
        ("post-envelope-license-and-tail", end_line + 1, len(records)),
    )
    result = []
    for region_type, first, last in cuts:
        subset = records[first - 1 : last]
        if not subset:
            raise ValueError(f"Maclaren member {pg_id} has an empty source region")
        result.append(
            {
                "type": region_type,
                "line_start": first,
                "line_end_inclusive": last,
                "byte_start": int(subset[0]["byte_start"]),
                "byte_end_exclusive": int(subset[-1]["byte_end_exclusive"]),
                "line_count": len(subset),
                "disposition": "represented-in-tei",
                "first_line_xml_id": _line_id(pg_id, first),
                "last_line_xml_id": _line_id(pg_id, last),
            }
        )
    return result


def _source_accountability(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    members: list[dict[str, object]],
) -> dict[str, object]:
    profile_members = profile["members"]
    member_records = []
    for source_member, profile_member in zip(members, profile_members, strict=True):
        line_inventory, line_accounting = _line_accounting_records(
            source_member["records"], str(profile_member["pg_id"])
        )
        records = source_member["records"]
        facts = source_member["facts"]
        member_records.append(
            {
                "inventory_order": profile_member["inventory_order"],
                "pg_id": profile_member["pg_id"],
                "path": profile_member["path"],
                "bytes": profile_member["bytes"],
                "sha256": profile_member["sha256"],
                "physical_line_count": len(records),
                "leading_utf8_bom": True,
                "line_ending": "CRLF",
                "line_inventory_sha256": _sha(_canonical(line_inventory)),
                "line_accounting_sha256": _sha(_canonical(line_accounting)),
                "represented_line_count": len(records),
                "excluded_line_count": 0,
                "omitted_line_count": 0,
                "duplicate_line_count": 0,
                "start_marker_line": facts["start_marker_lines"][0],
                "end_marker_line": facts["end_marker_lines"][0],
                "full_license_line": facts["full_license_lines"][0],
                "regions": _regions(records, facts, str(profile_member["pg_id"])),
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


def _provenance(
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


def _build_tei(profile: Mapping[str, object], members: list[dict[str, object]]) -> bytes:
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "maclaren-expositions-lib073-source-bound-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(
        profile["catalog_title_observation"]
    )
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = "Alexander Maclaren"
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}p").text = (
        "Provisional, nonaccepted source-bound reconstruction. Rights review, "
        "human acceptance, release selection, and publication authorization "
        "have not been performed."
    )
    notes = etree.SubElement(file_desc, f"{{{_TEI}}}notesStmt")
    etree.SubElement(notes, f"{{{_TEI}}}note", {"type": "source-scope-boundary"}).text = (
        "The source-native cohort and all file-level boundaries are retained; "
        "its complete printed-edition lineage and exposition count remain unresolved."
    )
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibliography = etree.SubElement(source_desc, f"{{{_TEI}}}listBibl")
    for profile_member in profile["members"]:
        bibl = etree.SubElement(
            bibliography,
            f"{{{_TEI}}}bibl",
            {
                _XML_ID: f"bibl-pg{profile_member['pg_id']}",
                "n": str(profile_member["inventory_order"]),
            },
        )
        etree.SubElement(bibl, f"{{{_TEI}}}title").text = str(
            profile_member["title_observation"]
        )
        etree.SubElement(bibl, f"{{{_TEI}}}author").text = str(
            profile_member["author_observation"]
        )
        etree.SubElement(bibl, f"{{{_TEI}}}idno", {"type": "project-gutenberg-ebook"}).text = str(
            profile_member["pg_id"]
        )
        etree.SubElement(bibl, f"{{{_TEI}}}idno", {"type": "sha256"}).text = str(
            profile_member["sha256"]
        )
        etree.SubElement(bibl, f"{{{_TEI}}}note", {"type": "retained-path"}).text = str(
            profile_member["path"]
        )
    text = etree.SubElement(root, f"{{{_TEI}}}text")
    body = etree.SubElement(text, f"{{{_TEI}}}body")
    for profile_member, source_member in zip(profile["members"], members, strict=True):
        pg_id = str(profile_member["pg_id"])
        member_div = etree.SubElement(
            body,
            f"{{{_TEI}}}div",
            {
                "type": "source-member",
                "n": pg_id,
                _XML_ID: f"member-pg{pg_id}",
            },
        )
        for region_record in source_member["regions"]:
            region = etree.SubElement(
                member_div,
                f"{{{_TEI}}}div",
                {
                    "type": str(region_record["type"]),
                    "n": f"{region_record['line_start']}-{region_record['line_end_inclusive']}",
                    _XML_ID: f"member-pg{pg_id}-{region_record['type']}",
                },
            )
            first = int(region_record["line_start"])
            last = int(region_record["line_end_inclusive"])
            for line_record in source_member["records"][first - 1 : last]:
                _append_line_carrier(region, line_record, pg_id)

    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile_bytes, profile = _json_authority(source_manifest, "reconstruction-profile")
    policy_bytes, policy = _json_authority(source_manifest, "validation-policy")
    _ = policy_bytes
    profile_members = _validate_route_scope(source_manifest, profile, policy)

    all_members: list[dict[str, object]] = []
    aggregate_bytes = 0
    aggregate_lines = 0
    for profile_member, authority in zip(profile["members"], profile_members, strict=True):
        data = source_manifest.authority_path(str(authority["name"])).read_bytes()
        records, facts = _verify_member_observations(profile_member, data)
        aggregate_bytes += len(data)
        aggregate_lines += len(records)
        region_records = _regions(records, facts, str(profile_member["pg_id"]))
        all_members.append(
            {
                "records": records,
                "facts": facts,
                "regions": region_records,
            }
        )
    if (
        aggregate_bytes != profile["aggregate"]["bytes"]
        or aggregate_lines != profile["aggregate"]["physical_line_count"]
    ):
        raise ValueError("Maclaren aggregate source census changed")

    accountability = _source_accountability(source_manifest, profile, all_members)
    accountability_schema = json.loads(
        _authority(source_manifest, "source-accountability-schema").decode("utf-8")
    )
    errors = sorted(Draft202012Validator(accountability_schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"Maclaren source-accountability schema failure: {errors[0].message}")

    unresolved = [
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
            "detail": profile["boundary_questions"]["work_collection_and_edition_relationship"],
        },
        {
            "id": "maclaren-expositions-textual-form-and-revision",
            "status": "unresolved",
            "kind": "textual-form",
            "detail": profile["boundary_questions"]["textual_form_and_revision"],
        },
        {
            "id": "maclaren-expositions-contributor-role-adoption",
            "status": "unresolved",
            "kind": "identity-and-contributor-roles",
            "detail": profile["boundary_questions"]["identity_and_contributor_roles"],
        },
        {
            "id": "maclaren-expositions-rights-review",
            "status": "unresolved",
            "kind": "rights",
            "detail": profile["boundary_questions"]["rights"],
        },
        {
            "id": "maclaren-expositions-human-acceptance-and-cvw",
            "status": "unresolved",
            "kind": "human-acceptance-and-visual-review",
            "detail": profile["boundary_questions"]["human_acceptance_and_visual_review"],
        },
    ]
    return {
        "content.tei.xml": _build_tei(profile, all_members),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(_provenance(source_manifest, profile, policy)),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": _authority(source_manifest, "attribution-readme"),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
