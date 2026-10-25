"""Faithful line-level TEI reconstruction for the five LIB-072 works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib072-retained-texts-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


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
    content.decode("utf-8")
    rows: list[tuple[str, str]] = []
    for raw in content.splitlines(keepends=True):
        if raw.endswith(b"\r\n"):
            text, ending = raw[:-2].decode("utf-8"), "crlf"
        elif raw.endswith(b"\n"):
            text, ending = raw[:-1].decode("utf-8"), "lf"
        elif raw.endswith(b"\r"):
            text, ending = raw[:-1].decode("utf-8"), "cr"
        else:
            text, ending = raw.decode("utf-8"), "none"
        rows.append((text, ending))
    endings = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}
    if b"".join(text.encode("utf-8") + endings[e] for text, e in rows) != content:
        raise ValueError("LIB-072 retained source line decomposition is not lossless")
    return rows


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"LIB-072 authority {name!r} cardinality mismatch")
    return matches[0]


def _inventory(
    root: Path, profile: Mapping[str, object], assigned: set[str]
) -> list[dict[str, object]]:
    expected = profile.get("adjacent_retained_member_paths")
    if not isinstance(expected, list) or any(not isinstance(x, str) for x in expected):
        raise ValueError("LIB-072 adjacent inventory profile is invalid")
    paths = sorted(
        [member for base in (root / "raw/gutenberg", root / "raw/ia") for member in base.iterdir() if member.is_file()],
        key=lambda item: item.as_posix(),
    )
    logical = [item.relative_to(root).as_posix() for item in paths]
    if logical != expected:
        raise ValueError("LIB-072 adjacent retained-member inventory drifted")
    overrides = profile.get("adjacent_retained_member_dispositions")
    if not isinstance(overrides, dict) or any(
        not isinstance(path, str) or not isinstance(reason, str)
        for path, reason in overrides.items()
    ):
        raise ValueError("LIB-072 adjacent inventory dispositions are invalid")
    if not set(overrides) <= set(logical) - assigned:
        raise ValueError("LIB-072 adjacent inventory dispositions are out of scope")
    ticket_assigned = {
        str(member["source_path"])
        for work in profile["works"]
        for member in work["members"]
    }
    if assigned - ticket_assigned:
        raise ValueError("LIB-072 selected members are outside the ticket profile")
    result = []
    for path, member in zip(logical, paths, strict=True):
        content = member.read_bytes()
        result.append(
            {
                "path": path,
                "bytes": len(content),
                "sha256": _sha(content),
                "disposition": (
                    "included as one exact LIB-072 retained witness member"
                    if path in assigned
                    else (
                        "excluded: exact retained member assigned to another "
                        "LIB-072 work/package"
                        if path in ticket_assigned
                        else overrides.get(
                            path,
                            "excluded: adjacent retained member assigned outside LIB-072",
                        )
                    )
                ),
            }
        )
    return result


def _tei(work: Mapping[str, object], sources: Mapping[str, bytes]) -> bytes:
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(XML_ID, "lib072-gutenberg-evangelical")
    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = (
        f"LIB-072 retained witness: {work['title']}"
    )
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{TEI_NS}}}availability", status="restricted")
    etree.SubElement(availability, f"{{{TEI_NS}}}p").text = (
        "Nonaccepted reconstruction candidate; human acceptance and publication authorization are absent."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    source_list = etree.SubElement(source_desc, f"{{{TEI_NS}}}listBibl")
    bibl = etree.SubElement(source_list, f"{{{TEI_NS}}}bibl", type="retained-witness")
    bibl.set(XML_ID, f"source-{work['work_id']}")
    etree.SubElement(bibl, f"{{{TEI_NS}}}title").text = str(work["title"])
    etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = str(work["author"])
    etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="witness-description").text = str(work["witness_description"])
    for member in work["members"]:
        etree.SubElement(bibl, f"{{{TEI_NS}}}ref", target=str(member["source_url"])).text = str(member["source_path"])
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = (
        "Every retained physical source line is represented once and in member order as a source-line ab; subtype records its line-ending class for byte-exact UTF-8 reassembly."
    )
    text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    group = etree.SubElement(text, f"{{{TEI_NS}}}group")
    work_id = str(work["work_id"])
    work_text = etree.SubElement(group, f"{{{TEI_NS}}}text")
    work_text.set(XML_ID, work_id)
    body = etree.SubElement(work_text, f"{{{TEI_NS}}}body")
    for member_index, member in enumerate(work["members"], 1):
        key = f"{work_id}:{member_index}"
        division = etree.SubElement(
            body,
            f"{{{TEI_NS}}}div",
            type="retained-text-witness",
            n=str(member_index),
            corresp=f"#source-{work_id}",
        )
        for ordinal, (line, ending) in enumerate(_line_rows(sources[key]), 1):
            node = etree.SubElement(
                division,
                f"{{{TEI_NS}}}ab",
                type="source-line",
                subtype=ending,
                n=str(ordinal),
            )
            node.set(XML_ID, f"{work_id}-m{member_index}-line-{ordinal:05d}")
            node.text = line
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "LIB-072 profile",
    )
    all_works = profile.get("works")
    if not isinstance(all_works, list) or len(all_works) != 5:
        raise ValueError("LIB-072 profile must bind exactly five works")
    manifest_work_id = source_manifest.record.get("work_id")
    works = [work for work in all_works if work.get("work_id") == manifest_work_id]
    if len(works) != 1:
        raise ValueError("LIB-072 manifest must select exactly one profile work")
    sources: dict[str, bytes] = {}
    member_rows: list[dict[str, object]] = []
    work_rows: list[dict[str, object]] = []
    for work in works:
        work_id = str(work["work_id"])
        total_lines = total_chars = total_blanks = 0
        ending_counts = {ending: 0 for ending in ("crlf", "lf", "cr", "none")}
        member_hashes = []
        for member_index, member in enumerate(work["members"], 1):
            authority = _authority(source_manifest, str(member["authority_name"]))
            if authority.get("path") != member.get("source_path") or authority.get("role") != "primary-source":
                raise ValueError(f"LIB-072 source binding drifted for {work_id}")
            content = source_manifest.authority_path(str(member["authority_name"])).read_bytes()
            rows = _line_rows(content)
            sources[f"{work_id}:{member_index}"] = content
            member_hashes.append("sha256:" + _sha(content))
            total_lines += len(rows)
            total_chars += sum(len(line) for line, _ in rows)
            total_blanks += sum(not line for line, _ in rows)
            for ending in ending_counts:
                ending_counts[ending] += sum(observed == ending for _, observed in rows)
            member_rows.append({
                "work_id": work_id,
                "member_index": member_index,
                "path": authority["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "line_count": len(rows),
                "disposition": "included in full in declared work-member order",
            })
        claim = _sha("".join(member_hashes).encode("ascii")) if len(member_hashes) > 1 else member_hashes[0][7:]
        if claim != work["frozen_source_claim_sha256"]:
            raise ValueError(f"LIB-072 frozen source claim drifted for {work_id}")
        work_rows.append({
            "work_id": work_id,
            "member_count": len(work["members"]),
            "frozen_source_claim_sha256": claim,
            "line_count": total_lines,
            "character_count": total_chars,
            "blank_line_count": total_blanks,
            "line_ending_counts": ending_counts,
            "tei_selector_contract": f"#{work_id}-m%u-line-%05u",
            "omitted_line_count": 0,
            "duplicate_line_count": 0,
        })
    work = works[0]
    assigned = {str(member["source_path"]) for member in work["members"]}
    inventory = _inventory(source_manifest.repository_root, profile, assigned)
    accountability = {
        "contract": "ocd-lib072-source-accountability-v1",
        "schema": "gutenberg-evangelical-lib072.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "assigned_work_count": 1,
        "assigned_member_count": len(work["members"]),
        "adjacent_member_count": len(inventory),
        "source_members": member_rows,
        "adjacent_retained_member_accounting": inventory,
        "works": work_rows,
        "total_line_count": sum(int(row["line_count"]) for row in work_rows),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_byte_reassembly": "exact UTF-8 text plus recorded per-line terminator and member order",
        "candidate_status": "nonaccepted",
        "human_review_required": True,
        "publication_ready": False,
    }
    provenance = {
        "contract": "ocd-lib072-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "profile_id": profile["profile_id"],
        "text_authority": "the selected work's retained raw UTF-8 text members only",
        "diagnostic_non_authorities": ["build/parsers/gutenberg_evangelical.py", "canonical data JSON", "legacy TEI"],
        "works": [{
            "work_id": work["work_id"],
            "title": work["title"],
            "author": work["author"],
            "frozen_source_claim_sha256": work["frozen_source_claim_sha256"],
            "source_paths": [member["source_path"] for member in work["members"]],
            "witness_description": work["witness_description"],
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        } for work in works],
        "rights": {
            "project_gutenberg": "license notice and link preserved in README.source.md",
            "internet_archive": "digitization credits and scanned front/back matter preserved in line-level TEI",
            "human_rights_decision": "not performed",
            "publication_state": "not_ready",
        },
    }
    return {
        "content.tei.xml": _tei(work, sources),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in profile["unresolved"]),
        "README.source.md": source_manifest.authority_path("source-local-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
