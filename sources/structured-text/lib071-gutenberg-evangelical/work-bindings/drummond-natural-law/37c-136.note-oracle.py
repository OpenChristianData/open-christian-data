"""Independent retained-source check for the complete PG23334 note candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Mapping

from lxml import etree


ORACLE_ID = "ocd-drummond-pg23334-note-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_ID = "drummond-natural-law"
SOURCE_PATH = "raw/gutenberg/pg23334.txt"
SOURCE_SHA256 = "e13875abb98d6818ef2c9adbdce89a194368e082194881dcbf1e0c32a3c22333"
EXPECTED_POLICY = (
    "The complete retained PG23334 member is preserved in source order as numbered "
    "line carriers and blank delimiters. Source-located headings preserve the "
    "declared section structure. All 100 numbered footnote calls link to their "
    "source definitions; continuation blocks point to the definition, and each "
    "definition points to the section containing its call. Source spelling and "
    "line endings are unchanged. Unmapped hierarchy remains source-block text."
)
# Source-located sections that contain footnote calls. This is maintained by the
# checker, independently of the producer's heading profile and note map.
CALL_OWNERS = {
    100: "PREFACE.",
    588: "PART I.",
    1209: "PART II.",
    1754: "BIOGENESIS.",
    2503: "DEGENERATION.",
    3033: "GROWTH.",
    3426: "DEATH.",
    4089: "MORTIFICATION.",
    4603: "ETERNAL LIFE.",
    5611: "ENVIRONMENT.",
    6270: "CONFORMITY TO TYPE.",
    6924: "SEMI-PARASITISM.",
    7367: "PARASITISM.",
    7905: "CLASSIFICATION.",
}
NOTE_GROUP_ENDS = {
    501: 510,
    1674: 1754,
    2430: 2503,
    3011: 3033,
    3417: 3426,
    4050: 4089,
    4592: 4603,
    5577: 5611,
    6254: 6270,
    6877: 6924,
    7898: 7905,
    8861: 8888,  # The following unnumbered block is a transcriber's endnote.
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _authority(source_manifest: Any, name: str) -> Mapping[str, object]:
    rows = source_manifest.record["authorities"]
    matches = [row for row in rows if row.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"PG23334 requires exactly one {name} authority")
    return matches[0]


def _one(root: etree._Element, query: str) -> etree._Element:
    nodes = root.xpath(
        query,
        namespaces={"tei": TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"},
    )
    if len(nodes) != 1:
        raise ValueError(f"PG23334 expected one TEI node for {query!r}, found {len(nodes)}")
    return nodes[0]


def _source_lines(content: bytes) -> list[tuple[str, str]]:
    result = []
    for raw in content.splitlines(keepends=True):
        if raw.endswith(b"\r\n"):
            text, ending = raw[:-2], "crlf"
        elif raw.endswith(b"\n"):
            text, ending = raw[:-1], "lf"
        elif raw.endswith(b"\r"):
            text, ending = raw[:-1], "cr"
        else:
            text, ending = raw, "none"
        result.append((text.decode("utf-8"), ending))
    if len(result) != 9258:
        raise ValueError("PG23334 retained line count changed")
    return result


def _source_notes(lines: list[tuple[str, str]]) -> dict[int, dict[str, object]]:
    notes: dict[int, dict[str, object]] = {}
    for number, title in CALL_OWNERS.items():
        if lines[number - 1][0] != title:
            raise ValueError(f"PG23334 source section heading changed at line {number}")
    for group_line in NOTE_GROUP_ENDS:
        if lines[group_line - 1][0] != "FOOTNOTES:":
            raise ValueError(f"PG23334 source note group changed at line {group_line}")
    for line_number, (text, _) in enumerate(lines, 1):
        for match in re.finditer(r"\[(\d{1,3})\]", text):
            number = int(match.group(1))
            if not 1 <= number <= 100:
                continue
            note = notes.setdefault(number, {"number": number})
            if text.startswith(match.group(0)):
                field = "definition_line"
                note["definition_group_line"] = max(
                    (group for group in NOTE_GROUP_ENDS if group < line_number), default=0
                )
            else:
                field = "call_line"
                note["owner_heading_line"] = max(
                    (owner for owner in CALL_OWNERS if owner < line_number), default=0
                )
            if field in note:
                raise ValueError(f"PG23334 source note {number} has duplicate {field}")
            note[field] = line_number
    if sorted(notes) != list(range(1, 101)):
        raise ValueError("PG23334 source note numbering is incomplete")
    grouped: dict[int, list[dict[str, object]]] = {}
    for note in notes.values():
        if set(note) != {
            "number", "call_line", "definition_line", "definition_group_line", "owner_heading_line"
        }:
            raise ValueError(f"PG23334 source note {note['number']} lacks a call or definition")
        group_line = int(note["definition_group_line"])
        if group_line not in NOTE_GROUP_ENDS or int(note["definition_line"]) >= NOTE_GROUP_ENDS[group_line]:
            raise ValueError(f"PG23334 source note {note['number']} is outside its note group")
        grouped.setdefault(group_line, []).append(note)
    for group_line, members in grouped.items():
        members.sort(key=lambda note: int(note["definition_line"]))
        for index, note in enumerate(members):
            stop = (
                int(members[index + 1]["definition_line"])
                if index + 1 < len(members)
                else NOTE_GROUP_ENDS[group_line]
            )
            starts: list[int] = []
            in_block = True
            for line_number in range(int(note["definition_line"]) + 1, stop):
                if lines[line_number - 1][0] == "":
                    in_block = False
                elif not in_block:
                    starts.append(line_number)
                    in_block = True
            note["continuation_start_lines"] = starts
    return notes


def _check_tei_lines(root: etree._Element, lines: list[tuple[str, str]]) -> None:
    carriers = root.xpath(
        "//tei:text//tei:seg[@type='source-line'] | //tei:text//tei:space[@type='source-blank-line']",
        namespaces={"tei": TEI_NS},
    )
    if len(carriers) != len(lines):
        raise ValueError("PG23334 TEI source carrier count differs")
    for ordinal, (node, (text, ending)) in enumerate(zip(carriers, lines, strict=True), 1):
        if node.get("n") != str(ordinal) or node.get("subtype") != ending:
            raise ValueError(f"PG23334 TEI source order or ending differs at line {ordinal}")
        if text == "":
            if node.tag != f"{{{TEI_NS}}}space" or node.get("quantity") != "1":
                raise ValueError(f"PG23334 TEI blank delimiter differs at line {ordinal}")
        elif (
            node.tag != f"{{{TEI_NS}}}seg"
            or node.get(XML_ID) != f"{WORK_ID}-line-{ordinal:05d}"
            or "".join(node.itertext()) != text
        ):
            raise ValueError(f"PG23334 TEI source text differs at line {ordinal}")


def _check_notes(
    root: etree._Element,
    expected: dict[int, dict[str, object]],
) -> None:
    calls = root.xpath("//tei:ref[@type='source-footnote-call']", namespaces={"tei": TEI_NS})
    definitions = root.xpath("//tei:note[@type='source-footnote']", namespaces={"tei": TEI_NS})
    if len(calls) != 100 or len(definitions) != 100:
        raise ValueError("PG23334 TEI note call or definition count differs")
    continuation_expectations: dict[int, int] = {}
    for number in range(1, 101):
        row = expected[number]
        call_id = f"{WORK_ID}-note-call-{number:03d}"
        note_id = f"{WORK_ID}-note-{number:03d}"
        call = _one(root, f"//tei:ref[@xml:id='{call_id}']")
        note = _one(root, f"//tei:note[@xml:id='{note_id}']")
        marker = f"[{number}]"
        if (
            call.attrib.get("n") != str(number)
            or call.get("target") != f"#{note_id}"
            or call.text != marker
            or call.getparent().get("n") != str(row["call_line"])
            or note.get("n") != str(number)
            or note.get("target") != f"#{call_id}"
            or note.get("corresp") != f"#{WORK_ID}-heading-{int(row['owner_heading_line']):05d}"
            or not _one(note, ".//tei:seg[@type='source-line' and @n='%s']" % row["definition_line"]).text.startswith(marker)
        ):
            raise ValueError(f"PG23334 TEI note {number} identity or link differs from source")
        owner = _one(root, f"//tei:head[@n='{row['owner_heading_line']}' and @type='source-located-heading']")
        # The call belongs to the owner's section, while the definition
        # retains its physical location in the source's note group.
        if owner.getparent() not in tuple(call.iterancestors()):
            raise ValueError(f"PG23334 TEI note {number} call is detached from source section")
        group = _one(root, f"//tei:head[@n='{row['definition_group_line']}' and @type='source-located-heading']")
        if group.getparent() not in tuple(note.iterancestors()):
            raise ValueError(f"PG23334 TEI note {number} left its source note group")
        for start_line in row["continuation_start_lines"]:
            continuation_expectations[int(start_line)] = number
    actual_continuations = root.xpath(
        "//tei:div[@type='source-block' and starts-with(@corresp, '#drummond-natural-law-note-')]",
        namespaces={"tei": TEI_NS},
    )
    if len(actual_continuations) != len(continuation_expectations):
        raise ValueError("PG23334 note continuation block count differs")
    for start_line, number in continuation_expectations.items():
        segment = _one(root, f"//tei:seg[@type='source-line' and @n='{start_line}']")
        block = next(
            (ancestor for ancestor in segment.iterancestors()
             if ancestor.tag == f"{{{TEI_NS}}}div" and ancestor.get("type") == "source-block"),
            None,
        )
        if block is None or block.get("corresp") != f"#{WORK_ID}-note-{number:03d}":
            raise ValueError(f"PG23334 note continuation at line {start_line} is detached")


def _oracle(source_manifest: Any, candidate: Any) -> Mapping[str, object]:
    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("PG23334 oracle accepts only drummond-natural-law")
    source_manifest.verify()
    raw_authorities = [
        row for row in source_manifest.record["authorities"]
        if str(row.get("path", "")).startswith("raw/")
    ]
    if len(raw_authorities) != 1 or raw_authorities[0].get("path") != SOURCE_PATH:
        raise ValueError("PG23334 oracle requires the one exact retained source")
    source = source_manifest.authority_path("primary-source").read_bytes()
    if _sha(source) != SOURCE_SHA256 or len(source) != 566707:
        raise ValueError("PG23334 retained source bytes differ")
    lines = _source_lines(source)
    expected = _source_notes(lines)
    note_map = json.loads(source_manifest.authority_path("note-map").read_text(encoding="utf-8"))
    if (
        note_map.get("contract") != "ocd-drummond-pg23334-note-map-v1"
        or note_map.get("source_sha256") != SOURCE_SHA256
        or note_map.get("notes") != [expected[number] for number in range(1, 101)]
    ):
        raise ValueError("PG23334 note map differs from independent source inventory")
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    if root.tag != f"{{{TEI_NS}}}TEI" or root.findall(f".//{{{TEI_NS}}}TEI"):
        raise ValueError("PG23334 must have one complete TEI document")
    project = _one(root, "//tei:teiHeader/tei:encodingDesc/tei:projectDesc/tei:p")
    if project.text != EXPECTED_POLICY or "Carey" in project.text:
        raise ValueError("PG23334 TEI encoding policy is unrelated or incomplete")
    _check_tei_lines(root, lines)
    _check_notes(root, expected)
    schema_path = source_manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    if not schema.validate(root):
        raise ValueError(f"PG23334 TEI P5 schema invalid: {schema.error_log.last_error}")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if (
        account.get("total_line_count") != len(lines)
        or account.get("omitted_line_count") != 0
        or account.get("duplicate_line_count") != 0
        or account.get("candidate_status") != "nonaccepted"
        or account.get("source_members", [{}])[0].get("sha256") != SOURCE_SHA256
    ):
        raise ValueError("PG23334 source accounting or nonacceptance differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (
        provenance.get("source_manifest_sha256") != source_manifest.sha256
        or provenance.get("accepted_ir") != "not_accepted"
        or provenance.get("rights", {}).get("clearance") != "not assessed by this technical reconstruction"
    ):
        raise ValueError("PG23334 provenance or rights boundary differs")
    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("PG23334 candidate status differs")
    own_path = Path(__file__).resolve(strict=True)
    own_sha = _sha(own_path.read_bytes())
    own_relative = own_path.relative_to(source_manifest.repository_root).as_posix()
    closure = _sha(_canonical([{"path": own_relative, "sha256": own_sha}]))
    findings = [
        "one complete retained PG23334 source and one complete nonaccepted TEI",
        "all 9,258 source lines, text, blank delimiters, and endings match in order",
        "all 100 numbered calls, definitions, source note groups, section owners, and continuation blocks match source-derived expectations",
        "the TEI validates against the bound TEI P5 schema",
        "human review, rights clearance, and publication are not asserted",
    ]
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": own_sha,
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _authority(source_manifest, "reconstruction-profile")["sha256"],
        "package_schema_sha256": _authority(source_manifest, "candidate-package-schema")["sha256"],
        "source_sha256": SOURCE_SHA256,
        "xsd_sha256": _authority(source_manifest, "tei-p5-xsd")["sha256"],
        "policy_sha256": _authority(source_manifest, "validation-policy")["sha256"],
        "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
