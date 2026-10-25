"""Faithful line-level TEI reconstruction for the ten LIB-071 witnesses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib071-retained-texts-to-tei"
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
    """Decode strict UTF-8 and retain each physical line-ending class."""
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
    if b"".join(
        text.encode("utf-8")
        + {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}[ending]
        for text, ending in rows
    ) != content:
        raise ValueError("retained source line decomposition is not lossless")
    return rows


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"LIB-071 authority {name!r} cardinality mismatch")
    return matches[0]


def _inventory(root: Path, profile: Mapping[str, object]) -> list[dict[str, object]]:
    expected = profile.get("adjacent_retained_member_paths")
    if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
        raise ValueError("LIB-071 adjacent inventory profile is invalid")
    paths = sorted(
        [item for base in (root / "raw/gutenberg", root / "raw/ia") for item in base.iterdir() if item.is_file()],
        key=lambda item: item.as_posix(),
    )
    logical = [item.relative_to(root).as_posix() for item in paths]
    if logical != expected:
        raise ValueError("LIB-071 adjacent retained-member inventory drifted")
    assigned = {str(item["source_path"]) for item in profile["works"]}
    overrides = profile.get("adjacent_retained_member_dispositions")
    if not isinstance(overrides, dict) or any(
        not isinstance(path, str) or not isinstance(reason, str)
        for path, reason in overrides.items()
    ):
        raise ValueError("LIB-071 adjacent inventory dispositions are invalid")
    if not set(overrides) <= set(logical) - assigned:
        raise ValueError("LIB-071 adjacent inventory dispositions are out of scope")
    return [
        {
            "path": path,
            "bytes": len(member.read_bytes()),
            "sha256": _sha(member.read_bytes()),
            "disposition": (
                "included as one exact LIB-071 work witness"
                if path in assigned
                else overrides.get(
                    path,
                    "excluded: adjacent retained member assigned outside LIB-071",
                )
            ),
        }
        for path, member in zip(logical, paths, strict=True)
    ]


def _tei(
    profile: Mapping[str, object], sources: Mapping[str, bytes]
) -> bytes:
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(XML_ID, "lib071-gutenberg-evangelical")
    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = (
        "LIB-071: ten retained Gutenberg and Internet Archive evangelical witnesses"
    )
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(
        publication, f"{{{TEI_NS}}}availability", status="restricted"
    )
    etree.SubElement(availability, f"{{{TEI_NS}}}p").text = (
        "Nonaccepted reconstruction candidate; human acceptance and publication authorization are absent."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    source_list = etree.SubElement(source_desc, f"{{{TEI_NS}}}listBibl")
    for work in profile["works"]:
        bibl = etree.SubElement(source_list, f"{{{TEI_NS}}}bibl", type="retained-witness")
        bibl.set(XML_ID, f"source-{work['work_id']}")
        etree.SubElement(bibl, f"{{{TEI_NS}}}title").text = str(work["title"])
        etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = str(work["author"])
        etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="witness-description").text = str(
            work["witness_description"]
        )
        etree.SubElement(bibl, f"{{{TEI_NS}}}ref", target=str(work["source_url"])).text = str(
            work["source_path"]
        )
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = (
        "Each retained physical source line is represented once, in order, as a source-line ab. "
        "Its exact line-ending class is recorded in subtype, enabling byte-for-byte UTF-8 reassembly."
    )
    text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    group = etree.SubElement(text, f"{{{TEI_NS}}}group")
    for work in profile["works"]:
        work_id = str(work["work_id"])
        work_text = etree.SubElement(group, f"{{{TEI_NS}}}text")
        work_text.set(XML_ID, work_id)
        body = etree.SubElement(work_text, f"{{{TEI_NS}}}body")
        division = etree.SubElement(
            body,
            f"{{{TEI_NS}}}div",
            type="retained-text-witness",
            corresp=f"#{'source-' + work_id}",
        )
        for ordinal, (line, ending) in enumerate(_line_rows(sources[work_id]), 1):
            node = etree.SubElement(
                division,
                f"{{{TEI_NS}}}ab",
                type="source-line",
                subtype=ending,
                n=str(ordinal),
            )
            node.set(XML_ID, f"{work_id}-line-{ordinal:05d}")
            node.text = line
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "LIB-071 profile",
    )
    works = profile.get("works")
    if not isinstance(works, list) or len(works) != 10:
        raise ValueError("LIB-071 profile must bind exactly ten works")
    sources: dict[str, bytes] = {}
    member_rows: list[dict[str, object]] = []
    work_rows: list[dict[str, object]] = []
    for work in works:
        work_id = str(work["work_id"])
        authority = _authority(source_manifest, str(work["authority_name"]))
        if authority.get("path") != work.get("source_path") or authority.get("role") != "primary-source":
            raise ValueError(f"LIB-071 source binding drifted for {work_id}")
        content = source_manifest.authority_path(str(work["authority_name"])).read_bytes()
        rows = _line_rows(content)
        sources[work_id] = content
        member_rows.append(
            {
                "work_id": work_id,
                "path": authority["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "disposition": "included in full as the sole retained witness for this work",
            }
        )
        work_rows.append(
            {
                "work_id": work_id,
                "source_path": authority["path"],
                "source_sha256": _sha(content),
                "line_count": len(rows),
                "character_count": sum(len(text) for text, _ in rows),
                "blank_line_count": sum(not text for text, _ in rows),
                "line_ending_counts": {
                    ending: sum(row_ending == ending for _, row_ending in rows)
                    for ending in ("crlf", "lf", "cr", "none")
                },
                "tei_selector_contract": f"#{work_id}-line-%05d",
                "omitted_line_count": 0,
                "duplicate_line_count": 0,
            }
        )
    inventory = _inventory(source_manifest.repository_root, profile)
    accountability = {
        "contract": "ocd-lib071-source-accountability-v1",
        "schema": "gutenberg-evangelical-lib071.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "assigned_work_count": 10,
        "assigned_member_count": 10,
        "adjacent_member_count": len(inventory),
        "source_members": member_rows,
        "adjacent_retained_member_accounting": inventory,
        "works": work_rows,
        "total_line_count": sum(int(row["line_count"]) for row in work_rows),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_byte_reassembly": "exact UTF-8 text plus recorded per-line terminator",
        "candidate_status": "nonaccepted",
        "human_review_required": True,
        "publication_ready": False,
    }
    provenance = {
        "contract": "ocd-lib071-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "profile_id": profile["profile_id"],
        "text_authority": "the ten retained raw UTF-8 text members only",
        "diagnostic_non_authorities": [
            "build/parsers/gutenberg_evangelical.py",
            "canonical data JSON",
            "legacy TEI",
        ],
        "works": [
            {
                "work_id": work["work_id"],
                "title": work["title"],
                "author": work["author"],
                "source_path": work["source_path"],
                "source_sha256": _sha(sources[str(work["work_id"])]),
                "witness_description": work["witness_description"],
                "human_review": "required",
                "accepted_ir": "not_accepted",
                "publication": "not_ready",
            }
            for work in works
        ],
        "rights": {
            "project_gutenberg": "license notice and link preserved in README.source.md",
            "internet_archive": "digitization credits and all scanned front/back matter preserved in line-level TEI",
            "human_rights_decision": "not performed",
            "publication_state": "not_ready",
        },
    }
    unresolved = list(profile["unresolved"])
    readme = source_manifest.authority_path("source-local-readme").read_bytes()
    return {
        "content.tei.xml": _tei(profile, sources),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
