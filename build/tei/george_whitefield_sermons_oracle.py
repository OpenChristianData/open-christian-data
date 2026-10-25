"""Independent retained-source oracle for the provisional LIB-060 candidate."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping
from xml.etree import ElementTree as ET
from xml.parsers import expat

from jsonschema import Draft202012Validator
from lxml import etree as lxml_etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-lib060-george-whitefield-independent-source-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_HEADING = re.compile(r"SERMON\s+([IVXLCDM]+)\.")
_BLOCK_SOURCE_TAGS = frozenset(
    {"div", "div1", "div2", "p", "h1", "h2", "h3", "h4", "scripCom", "insertIndex"}
)


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


def _source_set_sha256(source_manifest: SourceManifest) -> str:
    members = [
        {
            key: item[key]
            for key in ("name", "path", "bytes", "sha256")
        }
        for item in source_manifest.record["authorities"]
        if item["role"] == "primary-source"
    ]
    members.sort(key=lambda item: (str(item["path"]), str(item["name"])))
    if len(members) == 1:
        return str(members[0]["sha256"])
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _tei_local(node: ET.Element) -> str:
    if not isinstance(node.tag, str):
        return ""
    return node.tag.rsplit("}", 1)[-1]


def _source_events(node: ET.Element) -> list[list[object]]:
    events: list[list[object]] = []

    def visit(current: ET.Element) -> None:
        if current.tag is ET.Comment:
            events.append(["comment", current.text or ""])
        elif current.tag is ET.ProcessingInstruction:
            target, separator, data = (current.text or "").partition(" ")
            events.append(["pi", target, data if separator else ""])
        else:
            events.append(
                [
                    "start",
                    str(current.tag),
                    [[key, value] for key, value in current.attrib.items()],
                ]
            )
            if current.text is not None:
                events.append(["text", current.text])
            for child in current:
                visit(child)
                if child.tail is not None:
                    events.append(["tail", child.tail])
            events.append(["end", str(current.tag)])

    visit(node)
    return events


def _source_contains_block(source: ET.Element) -> bool:
    if source.tag in {ET.Comment, ET.ProcessingInstruction}:
        return False
    if str(source.tag) in _BLOCK_SOURCE_TAGS:
        return True
    return any(_source_contains_block(child) for child in source)


def _expected_tei_name(source_tag: str, source: ET.Element) -> str:
    if source_tag in {"div", "div1", "div2", "ThML.body"}:
        return "div"
    if source_tag == "ThML.head":
        return "note"
    if source_tag in {"h1", "h2", "h3", "h4"}:
        return "ab"
    if source_tag == "p":
        return "p"
    if source_tag in {"a", "scripRef"}:
        return "ref"
    if source_tag in {"i", "b"}:
        return "hi"
    if source_tag == "note":
        return "note"
    if source_tag == "br":
        return "lb"
    if source_tag in {"scripCom", "insertIndex"}:
        return "ab"
    if any(_source_contains_block(child) for child in source):
        return "div"
    return "seg"


def _assert_source_node_matches_tei(source: ET.Element, target: ET.Element) -> None:
    if source.tag is ET.Comment:
        if target.tag is not ET.Comment or target.text != source.text:
            raise ValueError("CCEL source comment was not preserved at its source position")
        return
    if source.tag is ET.ProcessingInstruction:
        if target.tag is not ET.ProcessingInstruction or target.text != source.text:
            raise ValueError("CCEL processing instruction was not preserved in the mapped tree")
        return
    source_tag = str(source.tag)
    expected_tag = _expected_tei_name(source_tag, source)
    if _tei_local(target) != expected_tag:
        raise ValueError(f"CCEL source element {source_tag!r} has no exact TEI source-tag mapping")
    expected_attributes = [[key, value] for key, value in source.attrib.items()]
    try:
        annotation = json.loads(target.get("n", ""))
    except json.JSONDecodeError as exc:
        raise ValueError("CCEL TEI source-attribute annotation is invalid JSON") from exc
    if (
        annotation
        != {"source_tag": source_tag, "source_attributes": expected_attributes}
        or target.text != source.text
    ):
        raise ValueError(f"CCEL source attributes or text changed for {source_tag!r}")
    source_children = list(source)
    target_children = list(target)
    if len(source_children) != len(target_children):
        raise ValueError(f"CCEL child count changed for source element {source_tag!r}")
    for source_child, target_child in zip(source_children, target_children):
        _assert_source_node_matches_tei(source_child, target_child)
        if target_child.tail != source_child.tail:
            raise ValueError(f"CCEL child tail changed for source element {source_tag!r}")


def _xml_source_observation(source_bytes: bytes, profile_member: Mapping[str, object]):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    root = ET.fromstring(source_bytes, parser=parser)
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if root.tag != profile_member["expected_root"] or head is None or body is None:
        raise ValueError("CCEL source root/head/body identity changed")

    xml_declaration: dict[str, object] = {}
    processing_instructions: list[dict[str, str]] = []
    doctypes: list[str] = []
    prolog_events: list[dict[str, str]] = []
    epilog_comments: list[str] = []
    depth = 0
    root_seen = False
    expat_parser = expat.ParserCreate()

    def on_start(_name: str, _attributes: dict[str, str]) -> None:
        nonlocal depth, root_seen
        if depth == 0:
            root_seen = True
        depth += 1

    def on_end(_name: str) -> None:
        nonlocal depth
        depth -= 1

    def on_instruction(target: str, data: str) -> None:
        item = {"target": target, "data": data}
        processing_instructions.append(item)
        if not root_seen:
            prolog_events.append({"kind": "processing-instruction", **item})

    def on_comment(text: str) -> None:
        if depth == 0:
            if root_seen:
                epilog_comments.append(text)
            else:
                prolog_events.append({"kind": "comment", "text": text})

    expat_parser.XmlDeclHandler = lambda version, encoding, standalone: xml_declaration.update(
        {"version": version or "", "encoding": encoding or ""}
    )
    expat_parser.StartElementHandler = on_start
    expat_parser.EndElementHandler = on_end
    expat_parser.ProcessingInstructionHandler = on_instruction
    expat_parser.CommentHandler = on_comment
    expat_parser.StartDoctypeDeclHandler = lambda name, system_id, public_id, has_internal_subset: doctypes.append(
        name
    )
    expat_parser.Parse(source_bytes, True)
    doctype = "" if not doctypes else "!DOCTYPE " + doctypes[0]
    if doctype != profile_member["expected_doctype"]:
        raise ValueError("CCEL document type declaration changed")

    comments: list[dict[str, object]] = []
    for event in prolog_events:
        if event["kind"] == "comment":
            text = event["text"]
            comments.append(
                {
                    "document_order": len(comments) + 1,
                    "parent_tag": None,
                    "text_sha256": _sha(text.encode("utf-8")),
                    "text": text,
                }
            )
    in_root_comment_count = 0

    def visit_comments(parent: ET.Element) -> None:
        nonlocal in_root_comment_count
        for child in parent:
            if child.tag is ET.Comment:
                in_root_comment_count += 1
                comments.append(
                    {
                        "document_order": len(comments) + 1,
                        "parent_tag": str(parent.tag),
                        "text_sha256": _sha((child.text or "").encode("utf-8")),
                        "text": child.text or "",
                    }
                )
            else:
                visit_comments(child)

    visit_comments(root)
    pre_root_comment_count = sum(event["kind"] == "comment" for event in prolog_events)
    for text in epilog_comments:
        comments.append(
            {
                "document_order": len(comments) + 1,
                "parent_tag": None,
                "text_sha256": _sha(text.encode("utf-8")),
                "text": text,
            }
        )
    element_counts: dict[str, int] = {}
    for node in root.iter():
        if isinstance(node.tag, str):
            element_counts[node.tag] = element_counts.get(node.tag, 0) + 1
    carriers = body.findall("div1")
    carrier_ids = [node.get("id") for node in carriers]
    if carrier_ids != profile_member["expected_direct_div1_ids"]:
        raise ValueError("CCEL direct div1 carrier set or source order changed")
    sermon_ids = profile_member["expected_sermon_div1_ids"]
    carrier_rows = []
    for index, node in enumerate(carriers, 1):
        title = next(
            (
                " ".join("".join(child.itertext()).split())
                for child in node
                if child.tag in {"h1", "h2", "h3", "h4"}
            ),
            "",
        )
        carrier_rows.append(
            {
                "index": index,
                "source_id": node.get("id"),
                "source_tag": "div1",
                "source_title_observation": title,
                "event_sha256": _sha(_canonical(_source_events(node))),
                "disposition": "represented-complete-source-carrier",
                "candidate_xml_id": f"ccel-div1-{node.get('id')}",
            }
        )
    if [row["source_id"] for row in carrier_rows if row["source_id"] in sermon_ids] != sermon_ids:
        raise ValueError("CCEL sermon carrier set or order changed")
    if len(comments) != profile_member["expected_xml_comment_count"]:
        raise ValueError("CCEL XML comment count changed")
    if pre_root_comment_count != profile_member["expected_pre_root_xml_comment_count"]:
        raise ValueError("CCEL pre-root XML comment count changed")
    if in_root_comment_count != profile_member["expected_in_root_xml_comment_count"]:
        raise ValueError("CCEL in-root XML comment count changed")
    if len(epilog_comments) != profile_member["expected_post_root_xml_comment_count"]:
        raise ValueError("CCEL post-root XML comment count changed")
    if sum(event["kind"] == "processing-instruction" for event in prolog_events) != profile_member[
        "expected_pre_root_processing_instruction_count"
    ]:
        raise ValueError("CCEL pre-root processing-instruction count changed")
    if len(processing_instructions) != profile_member["expected_processing_instruction_count"]:
        raise ValueError("CCEL processing-instruction count changed")
    return {
        "root": root,
        "head": head,
        "body": body,
        "xml_declaration": xml_declaration,
        "processing_instructions": processing_instructions,
        "prolog_events": prolog_events,
        "comments": comments,
        "element_counts": dict(sorted(element_counts.items())),
        "carriers": carrier_rows,
    }


def _pg_source_observation(data: bytes, member: Mapping[str, object]):
    stream = io.BytesIO(data)
    lines: list[str] = []
    records: list[dict[str, object]] = []
    cursor = 0
    line_number = 0
    while True:
        chunk = stream.readline()
        if chunk == b"":
            break
        line_number += 1
        if chunk.endswith(b"\r\n"):
            body_bytes, terminator = chunk[:-2], "CRLF"
        elif chunk.endswith(b"\n"):
            body_bytes, terminator = chunk[:-1], "LF"
        elif chunk.endswith(b"\r"):
            body_bytes, terminator = chunk[:-1], "CR"
        else:
            body_bytes, terminator = chunk, "none"
        line_text = body_bytes.decode("utf-8", errors="strict")
        if line_number == 1 and line_text.startswith("\ufeff"):
            line_text = line_text[1:]
        lines.append(line_text)
        records.append(
            {
                "line": line_number,
                "byte_start": cursor,
                "byte_end": cursor + len(body_bytes),
                "terminator": terminator,
                "record_sha256": _sha(body_bytes),
            }
        )
        cursor += len(chunk)
    if cursor != len(data) or line_number != member["expected_physical_line_count"]:
        raise ValueError("Project Gutenberg line/byte inventory does not span the exact member")

    start_markers = [
        index
        for index, line in enumerate(lines)
        if line.startswith("*** START OF THE PROJECT GUTENBERG EBOOK ")
    ]
    end_markers = [
        index
        for index, line in enumerate(lines)
        if line.startswith("*** END OF THE PROJECT GUTENBERG EBOOK ")
    ]
    if len(start_markers) != 1 or len(end_markers) != 1 or start_markers[0] >= end_markers[0]:
        raise ValueError("Project Gutenberg wrapper markers are missing or ambiguous")
    heading_rows: list[tuple[int, str]] = []
    for index in range(start_markers[0] + 1, end_markers[0]):
        found = _HEADING.fullmatch(lines[index].strip())
        if found:
            heading_rows.append((index, found.group(1)))
    if [label for _, label in heading_rows] != member["expected_source_sermon_labels"]:
        raise ValueError("Project Gutenberg source-native sermon labels/order changed")
    finish_lines = [
        index
        for index in range(heading_rows[-1][0] + 1, end_markers[0])
        if lines[index].strip() == "FINIS."
    ]
    if len(finish_lines) != 1:
        raise ValueError("Project Gutenberg FINIS boundary is missing or ambiguous")

    sermon_carriers: list[dict[str, object]] = []
    line_carriers: list[dict[str, object] | None] = [None] * len(lines)
    selected = set(member["selected_source_sermon_labels"])
    for ordinal, (heading_index, label) in enumerate(heading_rows):
        next_index = (
            heading_rows[ordinal + 1][0]
            if ordinal + 1 < len(heading_rows)
            else finish_lines[0]
        )
        selected_here = label in selected
        disposition = (
            "represented-source-native-carrier"
            if selected_here
            else "not-selected-by-current-work-specific-config"
        )
        for line_index in range(heading_index, next_index):
            line_carriers[line_index] = {
                "source_label": label,
                "disposition": disposition,
            }
        title_index = next(
            (
                index
                for index in range(heading_index + 1, next_index)
                if lines[index].strip()
            ),
            None,
        )
        begin_byte = int(records[heading_index]["byte_start"])
        stop_byte = int(records[next_index - 1]["byte_end"])
        start_line = heading_index + 1
        end_line = next_index
        sermon_carriers.append(
            {
                "source_label": label,
                "start_line": start_line,
                "end_line_inclusive": end_line,
                "title_line": title_index + 1 if title_index is not None else None,
                "title_observation": lines[title_index] if title_index is not None else "",
                "block_sha256": _sha(data[begin_byte:stop_byte]),
                "disposition": disposition,
                "candidate_xml_id": f"pg77041-sermon-{label.lower()}" if selected_here else None,
                "exclusion_reason": None
                if selected_here
                else "The work-specific config names two supplementary titles, not this carrier; relation to the catalog work remains unresolved.",
            }
        )
    for index, record in enumerate(records):
        carrier = line_carriers[index]
        if carrier is None:
            record["disposition"] = "provider-or-nonsermon-envelope-not-in-tei-body"
            record["carrier"] = None
        else:
            record["disposition"] = carrier["disposition"]
            record["carrier"] = carrier["source_label"]
    return {
        "lines": lines,
        "records": records,
        "sermons": sermon_carriers,
        "start_marker_line": start_markers[0] + 1,
        "end_marker_line": end_markers[0] + 1,
        "start_indices": {label: index for index, label in heading_rows},
    }


def _expected_unresolved() -> list[dict[str, str]]:
    return [
        {
            "id": "george-whitefield-collection-edition-part-boundary",
            "status": "unresolved",
            "kind": "identity",
            "detail": "The CCEL member identifies a 59-sermon selected collection while Project Gutenberg identifies Volume 6 (of 6) and source-native Sermons LVIII and LIX. The retained evidence does not establish a shared collection, edition, or part boundary.",
        },
        {
            "id": "george-whitefield-cross-witness-numbering",
            "status": "unresolved",
            "kind": "scope",
            "detail": "CCEL div1 ids lviii and lix identify different title carriers from Project Gutenberg's source-native LVIII and LIX. Legacy shared records 60 and 61 are not adopted; no global sermon ordinal is assigned.",
        },
        {
            "id": "george-whitefield-project-gutenberg-other-sermons",
            "status": "unresolved",
            "kind": "scope",
            "detail": "The other 26 Project Gutenberg sermon carriers are fully inventoried but not selected because the current work-specific config names only two supplementary titles. Their relation to the catalog work remains undecided.",
        },
        {
            "id": "george-whitefield-rights-review",
            "status": "unresolved",
            "kind": "rights",
            "detail": "No rights inquiry or clearance was performed. This nonaccepted candidate does not authorize release or publication.",
        },
        {
            "id": "george-whitefield-human-acceptance-and-visual-review",
            "status": "unresolved",
            "kind": "acceptance",
            "detail": "No human textual acceptance or CVW visual review is represented by the mechanical candidate route.",
        },
    ]


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    record = source_manifest.record
    if record.get("ticket_id") != "LIB-060" or record.get("work_id") != "george-whitefield-sermons":
        raise ValueError("George Whitefield oracle manifest identity mismatch")
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != record.get("source_id")
        or candidate.manifest.get("source_manifest")
        != {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "sha256": source_manifest.sha256,
        }
        or candidate.manifest.get("converter") != dict(record["converter"])
        or candidate.manifest.get("package_schema") != dict(record["package_schema"])
    ):
        raise ValueError("George Whitefield candidate manifest binding changed")

    profile_bytes = _authority(source_manifest, "reconstruction-profile")
    profile = json.loads(profile_bytes)
    policy_bytes = _authority(source_manifest, "validation-policy")
    policy = json.loads(policy_bytes)
    if (
        profile.get("contract") != "ocd-george-whitefield-reconstruction-profile-v1"
        or policy.get("contract") != "ocd-george-whitefield-validation-policy-v1"
        or policy.get("work_id") != record.get("work_id")
        or policy.get("ticket_id") != record.get("ticket_id")
    ):
        raise ValueError("George Whitefield work profile or policy binding changed")
    route = json.loads(_authority(source_manifest, "legacy-route-observation"))
    if (
        route.get("collection_id") != record.get("work_id")
        or route.get("title") != profile.get("catalog_title_observation")
        or route.get("source_hash") != f"sha256:{profile['members'][0]['sha256']}"
        or route.get("supplementary_source", {}).get("source_hash")
        != f"sha256:{profile['members'][1]['sha256']}"
    ):
        raise ValueError("George Whitefield legacy route no longer names the exact raw members")

    ccel_data = _authority(source_manifest, "retained-ccel-xml")
    pg_data = _authority(source_manifest, "retained-project-gutenberg-text")
    ccel_member, pg_member = profile["members"]
    for data, member, label in (
        (ccel_data, ccel_member, "CCEL"),
        (pg_data, pg_member, "Project Gutenberg"),
    ):
        if len(data) != member["bytes"] or _sha(data) != member["sha256"]:
            raise ValueError(f"Retained {label} bytes do not match the exact profile binding")

    ccel = _xml_source_observation(ccel_data, ccel_member)
    pg = _pg_source_observation(pg_data, pg_member)
    if ccel["xml_declaration"].get("version") != "1.0" or ccel["xml_declaration"].get("encoding", "").upper() != "UTF-8":
        raise ValueError("CCEL XML declaration is missing or changed")
    if not pg_data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Project Gutenberg UTF-8 BOM changed")

    tei_parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    tei_root = ET.fromstring(candidate.member_bytes("content.tei.xml"), parser=tei_parser)
    if tei_root.tag != f"{{{_TEI}}}TEI" or tei_root.get(_XML_ID) != "george-whitefield-sermons-lib060-candidate":
        raise ValueError("George Whitefield candidate TEI identity changed")
    header = tei_root.find(f"{{{_TEI}}}teiHeader")
    file_desc = header.find(f"{{{_TEI}}}fileDesc") if header is not None else None
    text_title = (
        file_desc.find(f"{{{_TEI}}}titleStmt/{{{_TEI}}}title")
        if file_desc is not None
        else None
    )
    if text_title is None or text_title.text != profile["catalog_title_observation"]:
        raise ValueError("George Whitefield candidate title is not the source-bound display-title observation")
    availability = (
        file_desc.find(f"{{{_TEI}}}publicationStmt/{{{_TEI}}}availability")
        if file_desc is not None
        else None
    )
    if (
        availability is None
        or availability.get("status") != "unknown"
        or "Rights review was not performed" not in "".join(availability.itertext())
    ):
        raise ValueError("George Whitefield candidate rights boundary changed")

    body = tei_root.find(f"{{{_TEI}}}text/{{{_TEI}}}body")
    if body is None or len(body) != 2:
        raise ValueError("George Whitefield candidate does not contain exactly two source-member projections")
    ccel_projection, pg_projection = list(body)
    if ccel_projection.get(_XML_ID) != "member-ccel-whitefield":
        raise ValueError("CCEL candidate source-member identity changed")
    _assert_source_node_matches_tei(ccel["body"], ccel_projection)
    notes = file_desc.find(f"{{{_TEI}}}notesStmt") if file_desc is not None else None
    head_projection = None
    if notes is not None:
        head_projection = next(
            (
                node
                for node in notes.findall(f"{{{_TEI}}}note")
                if node.get("type") == "source-header-event-ledger"
            ),
            None,
        )
    if head_projection is None:
        raise ValueError("Complete CCEL ThML.head event ledger is missing from candidate TEI")
    expected_head_events = _canonical(_source_events(ccel["head"])).decode("utf-8").rstrip("\n")
    if head_projection.text != expected_head_events:
        raise ValueError("CCEL ThML.head event ledger differs from the independently parsed source")
    observed_prolog_events = []
    for node in notes.findall(f"{{{_TEI}}}note") if notes is not None else []:
        note_type = node.get("type")
        if note_type == "source-processing-instruction":
            observed_prolog_events.append(
                {"kind": "processing-instruction", **json.loads(node.get("n", "{}"))}
            )
        elif note_type == "source-prolog-comment":
            observed_prolog_events.append({"kind": "comment", "text": node.text or ""})
    if observed_prolog_events != ccel["prolog_events"]:
        raise ValueError("CCEL pre-root processing instructions or comments changed or were reordered")
    source_pi_notes = [
        {"target": event["target"], "data": event["data"]}
        for event in observed_prolog_events
        if event["kind"] == "processing-instruction"
    ]
    if source_pi_notes != ccel["processing_instructions"]:
        raise ValueError("CCEL source processing instructions changed or were reordered")

    pg_expected_labels = pg_member["selected_source_sermon_labels"]
    if (
        pg_projection.get(_XML_ID) != "member-project-gutenberg-77041"
        or pg_projection.get("type") != "source-project-gutenberg-member"
    ):
        raise ValueError("Project Gutenberg candidate member identity changed")
    observed_pg_sections = list(pg_projection)
    if [section.get("n") for section in observed_pg_sections] != pg_expected_labels:
        raise ValueError("Project Gutenberg candidate carrier order or source-native labels changed")
    pg_rows_by_label = {row["source_label"]: row for row in pg["sermons"]}
    for section in observed_pg_sections:
        label = str(section.get("n"))
        row = pg_rows_by_label[label]
        if section.get(_XML_ID) != row["candidate_xml_id"] or section.get("type") != "source-gutenberg-sermon":
            raise ValueError("Project Gutenberg candidate sermon identity changed")
        expected_lines = list(
            range(int(row["start_line"]), int(row["end_line_inclusive"]) + 1)
        )
        line_nodes = list(section)
        observed_lines = [int(node.get("n", "-1")) for node in line_nodes]
        if (
            [node.get("type") for node in line_nodes] != ["source-physical-line"] * len(expected_lines)
            or observed_lines != expected_lines
        ):
            raise ValueError(f"Project Gutenberg {label} physical line sequence changed")
        for node, line_number in zip(line_nodes, expected_lines):
            if (node.text or "") != pg["lines"][line_number - 1] or node.tail is not None:
                raise ValueError(f"Project Gutenberg source line {line_number} changed")

    list_bibl = file_desc.find(f"{{{_TEI}}}sourceDesc/{{{_TEI}}}listBibl") if file_desc is not None else None
    bibliographies = list(list_bibl) if list_bibl is not None else []
    if len(bibliographies) != 2:
        raise ValueError("Candidate source bibliography does not identify exactly two retained members")
    if (
        bibliographies[0].get("n") != "CCEL"
        or bibliographies[0].findtext(f"{{{_TEI}}}title") != profile["catalog_title_observation"]
        or bibliographies[0].findtext(f"{{{_TEI}}}idno[@type='sha256']") != ccel_member["sha256"]
        or bibliographies[0].findtext(f"{{{_TEI}}}note[@type='retained-path']") != ccel_member["path"]
    ):
        raise ValueError("Candidate CCEL source citation/hash/path mismatch")
    pg_title = next(
        (line.partition(":")[2].strip() for line in pg["lines"] if line.strip().startswith("Title:")),
        "",
    )
    pg_author = next(
        (line.partition(":")[2].strip() for line in pg["lines"] if line.strip().startswith("Author:")),
        "",
    )
    if (
        bibliographies[1].get("n") != "Project Gutenberg"
        or bibliographies[1].findtext(f"{{{_TEI}}}title") != pg_title
        or bibliographies[1].findtext(f"{{{_TEI}}}author") != pg_author
        or bibliographies[1].findtext(f"{{{_TEI}}}idno[@type='project-gutenberg-ebook']") != "77041"
        or bibliographies[1].findtext(f"{{{_TEI}}}idno[@type='sha256']") != pg_member["sha256"]
        or bibliographies[1].findtext(f"{{{_TEI}}}note[@type='retained-path']") != pg_member["path"]
    ):
        raise ValueError("Candidate Project Gutenberg source citation/hash/path mismatch")

    ccel_bytes = _authority(source_manifest, "retained-ccel-xml")
    pg_rows = pg["sermons"]
    expected_accountability: dict[str, object] = {
        "contract": "ocd-george-whitefield-source-accountability-v1",
        "work_id": record["work_id"],
        "ticket_id": record["ticket_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_set_sha256": _source_set_sha256(source_manifest),
        "ccel": {
            "path": ccel_member["path"],
            "bytes": len(ccel_bytes),
            "sha256": _sha(ccel_bytes),
            "source_root": str(ccel["root"].tag),
            "source_title_observation": profile["catalog_title_observation"],
            "xml_version": str(ccel["xml_declaration"].get("version", "")),
            "encoding": str(ccel["xml_declaration"].get("encoding", "")),
            "doctype": "",
            "ordered_carriers": ccel["carriers"],
            "processing_instructions": ccel["processing_instructions"],
            "prolog_events": ccel["prolog_events"],
            "comments": ccel["comments"],
            "element_counts": ccel["element_counts"],
            "head_event_sha256": _sha(_canonical(_source_events(ccel["head"]))),
            "body_event_sha256": _sha(_canonical(_source_events(ccel["body"]))),
        },
        "project_gutenberg": {
            "path": pg_member["path"],
            "bytes": len(pg_data),
            "sha256": _sha(pg_data),
            "physical_line_count": len(pg["records"]),
            "line_inventory_sha256": _sha(_canonical(pg["records"])),
            "line_inventory": pg["records"],
            "sermon_carriers": pg_rows,
            "selected_source_labels": pg_expected_labels,
            "start_marker_line": pg["start_marker_line"],
            "end_marker_line": pg["end_marker_line"],
        },
        "candidate_scope": {
            "status": "provisional; collection and cross-witness relationship unresolved",
            "included": [
                "All 62 ordered CCEL direct div1 carriers, including title-page, contents, 59 sermon, and indexes carriers.",
                "Project Gutenberg source-native sermon carriers LVIII and LIX, preserved separately with their source labels.",
            ],
            "excluded": [
                {
                    "member": "retained-project-gutenberg-text",
                    "source_carrier_count": 26,
                    "reason": "The current source-local config names two supplementary titles only. These remaining carriers are explicitly not selected, but are not declared outside the larger work or corpus.",
                },
                {
                    "member": "retained-project-gutenberg-text",
                    "source_carrier": "provider/header/contents/license/closing matter and all physical lines outside the two selected sermon intervals",
                    "reason": "The complete physical member and all such lines are inventoried; this matter is not projected as sermon body text.",
                },
            ],
            "unknowns": [
                "Whether the two source members belong to one collection, edition, or part sequence.",
                "Whether Project Gutenberg source-native labels LVIII and LIX correspond to any shared catalog ordinals.",
                "Whether the 26 not-selected Project Gutenberg sermon carriers fall inside the catalog work boundary.",
                "Rights review, human textual acceptance, release selection, and publication authorization.",
            ],
        },
    }
    account_bytes = candidate.member_bytes("source-accountability.json")
    account = json.loads(account_bytes)
    if account != expected_accountability or account_bytes != _canonical(expected_accountability):
        raise ValueError("George Whitefield source-accountability inventory mismatch")
    accountability_schema = json.loads(
        _authority(source_manifest, "source-accountability-schema")
    )
    account_errors = sorted(
        Draft202012Validator(accountability_schema).iter_errors(account), key=str
    )
    if account_errors:
        raise ValueError(f"Source-accountability schema failure: {account_errors[0].message}")

    xsd_bytes = _authority(source_manifest, "tei-p5-xsd")
    schema_doc = lxml_etree.parse(
        str(source_manifest.authority_path("tei-p5-xsd")),
        lxml_etree.XMLParser(resolve_entities=False, no_network=True),
    )
    schema = lxml_etree.XMLSchema(schema_doc)
    tei_doc = lxml_etree.fromstring(
        candidate.member_bytes("content.tei.xml"),
        lxml_etree.XMLParser(resolve_entities=False, no_network=True),
    )
    if not schema.validate(tei_doc):
        last_error = schema.error_log.last_error
        raise ValueError(f"Candidate TEI fails the pinned TEI P5 schema: {last_error}")

    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    if unresolved != _expected_unresolved():
        raise ValueError("George Whitefield unresolved identity/scope/rights gates changed")
    if candidate.member_bytes("README.source.md") != _authority(
        source_manifest, "source-attribution-readme"
    ):
        raise ValueError("George Whitefield source attribution README changed")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    authorities = {
        str(item["name"]): {
            key: item[key]
            for key in ("path", "bytes", "sha256", "role")
        }
        for item in record["authorities"]
    }
    expected_provenance = {
        "contract": "ocd-george-whitefield-candidate-provenance-v1",
        "status": "nonaccepted",
        "work_id": record["work_id"],
        "ticket_id": record["ticket_id"],
        "source_id": record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_set_sha256": _source_set_sha256(source_manifest),
        "authorities": authorities,
        "identity_status": {
            "collection_boundary": "unresolved",
            "edition_relationship": "unresolved",
            "part_relationship": "unresolved",
            "cross_witness_numbering": "unresolved; source-native labels only",
        },
        "rights_status": "not-reviewed",
        "acceptance_status": "not-accepted",
        "release_status": "not-selected",
        "publication_status": "not-authorized",
        "canonical_data_or_ir_written": False,
    }
    if provenance != expected_provenance:
        raise ValueError("George Whitefield candidate provenance/decision boundary changed")

    implementation_sha256 = _sha(Path(__file__).read_bytes())
    closure = _closure(source_manifest.repository_root)
    validator = record["validator"]
    if (
        validator.get("implementation_sha256") != implementation_sha256
        or validator.get("import_closure_sha256") != closure
    ):
        raise ValueError("George Whitefield oracle implementation/closure pin drifted")
    source_set_sha256 = _source_set_sha256(source_manifest)
    facts = MechanicalFacts(
        validator_implementation_sha256=implementation_sha256,
        validator_import_closure_sha256=closure,
        source_sha256=source_set_sha256,
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(
            _authority(source_manifest, "candidate-package-schema")
        ),
        xsd_sha256=_sha(xsd_bytes),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
