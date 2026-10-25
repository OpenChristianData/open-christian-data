"""Independently check the structured Maclaren fifteen-member TEI candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import sys

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_SPACE = f"{{{XML}}}space"
MAP = Path("sources/sermons/maclaren-expositions/full-cohort-v3/source-structure-map.json")
MAP_SHA = "a7e40fe8f1eae31d5ceac9bbc9f14db3ad6f8d76df24bb8e20ff174cda4bd5bc"
PROFILE = Path("sources/sermons/maclaren-expositions/maclaren-expositions.reconstruction-profile.json")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
LINE_ID = re.compile(r"pg(?P<pg>[0-9]+)-line-(?P<line>[0-9]{6})\Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source_lines(root: Path, member: dict[str, object]) -> list[str]:
    data = (root / str(member["path"])).read_bytes()
    if len(data) != member["bytes"] or _sha(data) != member["sha256"]:
        raise ValueError(f"PG #{member['pg_id']} differs from the frozen source map")
    if (not data.startswith(b"\xef\xbb\xbf") or not data.endswith(b"\r\n")
            or data.count(b"\r\n") != data.count(b"\n")
            or data.count(b"\r\n") != data.count(b"\r")):
        raise ValueError(f"PG #{member['pg_id']} physical line framing changed")
    lines = data.decode("utf-8-sig").split("\r\n")[:-1]
    if len(lines) != member["physical_line_count"]:
        raise ValueError(f"PG #{member['pg_id']} physical line count changed")
    return lines


def _nearest_div(node: etree._Element, kind: str) -> etree._Element | None:
    parent = node.getparent()
    while parent is not None:
        if parent.tag == f"{{{TEI}}}div" and parent.get("type") == kind:
            return parent
        parent = parent.getparent()
    return None


def _one(nodes: list[etree._Element], label: str) -> etree._Element:
    if len(nodes) != 1:
        raise ValueError(f"candidate requires exactly one {label}; found {len(nodes)}")
    return nodes[0]


def _load_mapping(root: Path) -> tuple[dict[str, object], bytes]:
    data = (root / MAP).read_bytes()
    if _sha(data) != MAP_SHA:
        raise ValueError("Maclaren structured source map differs from the reviewed v3 map")
    mapping = json.loads(data)
    if (mapping.get("contract") != "maclaren-expositions-structured-cohort-map-v3"
            or mapping.get("status") != "nonaccepted-source-mapping-proposal"
            or mapping.get("work_id") != "maclaren-expositions"
            or mapping.get("edition_id") != "maclaren-expositions-pg-fifteen-volume-cohort"
            or mapping.get("source_member_count") != 15
            or mapping.get("source_line_count") != 339526):
        raise ValueError("Maclaren structured source map scope changed")
    return mapping, data


def _check_map_against_profile(root: Path, mapping: dict[str, object]) -> list[dict[str, object]]:
    profile_data = (root / PROFILE).read_bytes()
    if _sha(profile_data) != mapping["profile_sha256"]:
        raise ValueError("Maclaren source profile binding changed")
    profile = json.loads(profile_data)
    members = list(mapping["members"])
    profiled = list(profile["members"])
    if len(members) != len(profiled) or [str(x["pg_id"]) for x in members] != [str(x["pg_id"]) for x in profiled]:
        raise ValueError("Maclaren retained member order changed")
    for member, expected in zip(members, profiled, strict=True):
        for key in ("path", "bytes", "sha256"):
            if member[key] != expected[key]:
                raise ValueError(f"PG #{member['pg_id']} map/profile {key} differs")
        if member["physical_line_count"] != expected["physical_line_count"]:
            raise ValueError(f"PG #{member['pg_id']} map/profile line count differs")
        if member["end_marker_line"] != expected["end_marker_lines"][0]:
            raise ValueError(f"PG #{member['pg_id']} end marker binding differs")
    return members


def _heading_inventory(mapping: dict[str, object]) -> tuple[dict[tuple[str, int], dict[str, object]], set[tuple[str, int]]]:
    headings: dict[tuple[str, int], dict[str, object]] = {}
    epigraph_lines: set[tuple[str, int]] = set()
    roles: dict[str, int] = {}
    nonexact = 0
    for member in mapping["members"]:
        pg = str(member["pg_id"])
        for part in member["parts"]:
            for row in part["headings"]:
                key = (pg, int(row["line"]))
                if key in headings:
                    raise ValueError(f"duplicate mapped heading PG #{pg} line {row['line']}")
                headings[key] = row
                role = str(row["role"])
                roles[role] = roles.get(role, 0) + 1
                span = row.get("adjacent_epigraph_lines")
                if role == "exposition" and not row["found_in_contents_text"]:
                    nonexact += 1
                    if (not isinstance(span, list) or len(span) != 2
                            or not all(isinstance(value, int) for value in span)
                            or not (int(row["line"]) < span[0] <= span[1] <= int(part["body_end"]))):
                        raise ValueError(f"non-exact PG #{pg} heading lacks an adjacent epigraph span")
                    epigraph_lines.update((pg, number) for number in range(span[0], span[1] + 1))
                elif span is not None:
                    raise ValueError(f"unexpected epigraph span on PG #{pg} line {row['line']}")
    if len(headings) != 1444 or roles != {
        "exposition": 1386,
        "book-section": 43,
        "internal-subsection": 14,
        "verse-column-label": 1,
    } or nonexact != 28:
        raise ValueError(f"Maclaren heading census changed: headings={len(headings)} roles={roles} nonexact={nonexact}")
    return headings, epigraph_lines


def check_candidate(root: Path, candidate_bytes: bytes) -> dict[str, object]:
    mapping, mapping_data = _load_mapping(root)
    members = _check_map_against_profile(root, mapping)
    headings, epigraph_lines = _heading_inventory(mapping)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
    document = etree.fromstring(candidate_bytes, parser)
    tree = etree.ElementTree(document)
    schema = etree.XMLSchema(etree.parse(str(root / XSD), parser))
    if not schema.validate(tree):
        raise ValueError(f"candidate fails pinned TEI P5 XSD: {schema.error_log.last_error}")
    if document.tag != f"{{{TEI}}}TEI" or dict(document.attrib) != {XML_ID: "maclaren-expositions-full-cohort-v3"}:
        raise ValueError("candidate root identity changed")
    title = _one(document.xpath("./t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces={"t": TEI}), "title")
    author = _one(document.xpath("./t:teiHeader/t:fileDesc/t:titleStmt/t:author", namespaces={"t": TEI}), "author")
    publication = _one(document.xpath("./t:teiHeader/t:fileDesc/t:publicationStmt/t:p", namespaces={"t": TEI}), "publication statement")
    if (title.text, author.text, publication.text) != (
        "Expositions of Holy Scripture",
        "Alexander Maclaren",
        "Nonaccepted source-bound candidate; rights and publication decisions remain open.",
    ):
        raise ValueError("candidate title, author, or nonacceptance boundary changed")
    bibliography = document.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc/t:listBibl/t:bibl", namespaces={"t": TEI})
    if len(bibliography) != 15:
        raise ValueError("candidate source bibliography does not contain 15 retained members")
    for bibl, member in zip(bibliography, members, strict=True):
        values = [(node.get("type"), node.text) for node in bibl if node.tag == f"{{{TEI}}}idno"]
        retained = bibl.xpath("./t:note[@type='retained-path']", namespaces={"t": TEI})
        if (bibl.get(XML_ID) != f"bibl-pg{member['pg_id']}"
                or values != [("project-gutenberg-ebook", str(member["pg_id"])), ("sha256", member["sha256"])]
                or len(retained) != 1 or retained[0].text != member["path"]):
            raise ValueError(f"PG #{member['pg_id']} source bibliography binding changed")

    source_members = document.xpath("./t:text/t:body/t:div[@type='source-member']", namespaces={"t": TEI})
    if len(source_members) != 15:
        raise ValueError("candidate body does not contain 15 source-member divisions")
    observed_headings: dict[tuple[str, int], str] = {}
    epigraph_owners: dict[tuple[str, int], str | None] = {}
    total_lines = 0
    for order, (source_member, member) in enumerate(zip(source_members, members, strict=True), 1):
        pg = str(member["pg_id"])
        if dict(source_member.attrib) != {"type": "source-member", "n": str(order), XML_ID: f"member-pg{pg}"}:
            raise ValueError(f"PG #{pg} source-member identity or order changed")
        lines = _source_lines(root, member)
        expected_line = 1
        parts = source_member.xpath("./t:div[@type='source-part' or @type='printed-volume' or @type='printed-volume-group']", namespaces={"t": TEI})
        if len(parts) != len(member["parts"]):
            raise ValueError(f"PG #{pg} source-part count changed")
        for index, (part_node, part) in enumerate(zip(parts, member["parts"], strict=True), 1):
            expected_kind = ("printed-volume-group" if part["kind"] == "printed-volumes-I-II-undivided"
                             else "printed-volume" if str(part["kind"]).startswith("printed-volume-")
                             else "source-part")
            if dict(part_node.attrib) != {"type": expected_kind, "n": str(index), XML_ID: f"pg{pg}-part-{index}"}:
                raise ValueError(f"PG #{pg} part {index} identity or type changed")
        seen_numbers: list[int] = []
        for node in source_member.iter():
            identity = node.get(XML_ID)
            if identity is None:
                continue
            match = LINE_ID.fullmatch(identity)
            if not match:
                if node is source_member or node.tag == f"{{{TEI}}}div":
                    continue
                raise ValueError(f"PG #{pg} contains an unexpected xml:id {identity}")
            if match.group("pg") != pg:
                raise ValueError(f"PG #{pg} contains a carrier for PG #{match.group('pg')}")
            number = int(match.group("line"))
            if number != expected_line:
                raise ValueError(f"PG #{pg} source line {expected_line} is omitted, duplicated, or reordered")
            expected_line += 1
            seen_numbers.append(number)
            expected_text = lines[number - 1]
            if node.get("n") != str(number):
                raise ValueError(f"PG #{pg} line {number} ordinal changed")
            if expected_text == "":
                if node.tag != f"{{{TEI}}}milestone" or node.get("unit") != "source-empty-line" or node.text not in (None, ""):
                    raise ValueError(f"PG #{pg} empty line {number} carrier changed")
            elif (node.tag not in (f"{{{TEI}}}seg", f"{{{TEI}}}ab")
                  or node.text != expected_text or node.get(XML_SPACE) != "preserve"):
                raise ValueError(f"PG #{pg} line {number} text or carrier changed")
            key = (pg, number)
            if key in headings:
                role = str(headings[key]["role"])
                if role in ("exposition", "book-section"):
                    if node.tag != f"{{{TEI}}}seg" or node.getparent().tag != f"{{{TEI}}}head":
                        raise ValueError(f"PG #{pg} {role} heading at line {number} is not a readable head")
                    owner = _nearest_div(node, role)
                    if owner is None:
                        raise ValueError(f"PG #{pg} {role} heading at line {number} has wrong attachment")
                else:
                    if node.tag != f"{{{TEI}}}ab" or node.get("type") != role:
                        raise ValueError(f"PG #{pg} {role} marker at line {number} changed")
                observed_headings[key] = role
            if key in epigraph_lines or key in headings:
                owner = _nearest_div(node, "exposition")
                epigraph_owners[key] = owner.get(XML_ID) if owner is not None else None
        if seen_numbers != list(range(1, len(lines) + 1)):
            raise ValueError(f"PG #{pg} complete source line coverage changed")
        total_lines += len(seen_numbers)
        back = _one(source_member.xpath("./t:div[@type='gutenberg-license-tail']", namespaces={"t": TEI}), f"PG #{pg} Gutenberg tail")
        if back.get("n") != f"{member['end_marker_line']}-{member['physical_line_count']}":
            raise ValueError(f"PG #{pg} Gutenberg tail boundary changed")
        for index, part in enumerate(member["parts"], 1):
            part_node = _one(source_member.xpath(f"./t:div[@xml:id='pg{pg}-part-{index}']", namespaces={"t": TEI, "xml": XML}), f"PG #{pg} part {index}")
            part_numbers = [int(match.group("line")) for node in part_node.iter()
                            if (identity := node.get(XML_ID)) is not None
                            and (match := LINE_ID.fullmatch(identity)) is not None]
            next_start = (int(member["parts"][index]["line_start"])
                          if index < len(member["parts"]) else int(member["end_marker_line"]))
            if part_numbers != list(range(int(part["line_start"]), next_start)):
                raise ValueError(f"PG #{pg} part {index} source ownership changed")

    if total_lines != 339526 or observed_headings != {key: str(row["role"]) for key, row in headings.items()}:
        raise ValueError("candidate complete line or heading census changed")
    for key, row in headings.items():
        if row["role"] != "exposition" or row["found_in_contents_text"]:
            continue
        pg, heading_line = key
        owner = epigraph_owners.get(key)
        if owner is None:
            raise ValueError(f"PG #{pg} non-exact exposition heading {heading_line} lacks an exposition owner")
        first, last = row["adjacent_epigraph_lines"]
        if any(epigraph_owners.get((pg, number)) != owner for number in range(first, last + 1)):
            raise ValueError(f"PG #{pg} non-exact title {heading_line} lost its adjacent scripture epigraph")

    for node in document.iter():
        if node.tail not in (None, ""):
            raise ValueError("candidate contains unaccounted tail text")
        if node.tag == f"{{{TEI}}}head":
            children = list(node)
            if len(children) != 1 or children[0].tag != f"{{{TEI}}}seg":
                raise ValueError("candidate contains an invented or compound head")
    source_set = [{key: member[key] for key in ("pg_id", "path", "bytes", "sha256", "physical_line_count")}
                  for member in members]
    return {
        "contract": "maclaren-expositions-structured-oracle-v3",
        "status": "pass",
        "work_id": "maclaren-expositions",
        "edition_id": "maclaren-expositions-pg-fifteen-volume-cohort",
        "candidate_sha256": _sha(candidate_bytes),
        "source_map_sha256": _sha(mapping_data),
        "source_member_set_sha256": _sha(_canonical(source_set)),
        "source_members": 15,
        "source_parts": 26,
        "source_lines": total_lines,
        "mapped_markers": len(headings),
        "exposition_heads": 1386,
        "book_section_heads": 43,
        "internal_subsections": 14,
        "verse_column_labels": 1,
        "nonexact_toc_title_cases_with_adjacent_epigraphs": 28,
        "tei_p5_xsd": "valid",
        "findings": [],
        "claims_excluded": [
            "human visual acceptance",
            "certain print-edition lineage",
            "rights clearance",
            "public release selection",
            "publication",
        ],
    }


def _role(source_manifest: object, role: str) -> dict[str, object]:
    matches = [dict(item) for item in source_manifest.record["authorities"] if item["role"] == role]
    if len(matches) != 1:
        raise ValueError(f"Maclaren v3 source manifest requires one {role} authority")
    return matches[0]


def _oracle(source_manifest: object, candidate: object) -> dict[str, object]:
    """Adapt the source-local checker to the canonical validation contract."""
    checked = check_candidate(source_manifest.repository_root, candidate.member_bytes("content.tei.xml"))
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    readme = candidate.member_bytes("README.source.md")
    if (
        accountability.get("candidate_tei_sha256") != checked["candidate_sha256"]
        or accountability.get("source_map_sha256") != checked["source_map_sha256"]
        or accountability.get("physical_line_count") != 339526
        or accountability.get("mapped_marker_count") != 1444
        or provenance.get("source_manifest_sha256") != source_manifest.sha256
        or provenance.get("candidate_tei_sha256") != checked["candidate_sha256"]
        or provenance.get("acceptance_status") != "not-accepted"
        or len(unresolved) != 3
        or b"rights opinion or clearance" not in readme
    ):
        raise ValueError("Maclaren v3 package sidecars differ from the checked TEI and source scope")
    primary = sorted(
        (
            {key: item[key] for key in ("name", "path", "bytes", "sha256")}
            for item in source_manifest.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda item: (item["path"], item["name"]),
    )
    source_sha = _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": primary}))
    implementation_sha = _sha(Path(__file__).read_bytes())
    validator = source_manifest.record["validator"]
    body = {
        "status": "pass",
        "oracle_id": _oracle.oracle_id,
        "oracle_version": _oracle.oracle_version,
        "implementation_sha256": implementation_sha,
        "import_closure_sha256": validator["import_closure_sha256"],
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _role(source_manifest, "complete-source-feature-profile")["sha256"],
        "package_schema_sha256": _role(source_manifest, "candidate-package-schema")["sha256"],
        "source_sha256": source_sha,
        "xsd_sha256": _role(source_manifest, "tei-validation-schema")["sha256"],
        "policy_sha256": _role(source_manifest, "independent-validation-policy")["sha256"],
        "findings": [],
    }
    body["result_sha256"] = _sha(_canonical(body))
    return body


_oracle.oracle_id = "ocd-lib073-maclaren-expositions-structured-oracle-v3"
_oracle.oracle_version = "3"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = check_candidate(args.root, args.candidate.read_bytes())
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
