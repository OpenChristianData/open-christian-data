"""Line-preserving TEI reconstruction for exact retained IA OCR envelopes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-manifest-acquisition-retained-ocr-to-tei"
CONVERTER_VERSION = "1"
PROFILE_AUTHORITY = "reconstruction-profile"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    record = json.loads(source_manifest.authority_path(PROFILE_AUTHORITY).read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("contract") != "ocd-manifest-acquisition-ocr-profile-v1":
        raise ValueError("OCR reconstruction profile contract mismatch")
    return record


def _line_parts(raw: bytes) -> list[tuple[str, bytes, bytes]]:
    result: list[tuple[str, bytes, bytes]] = []
    for chunk in raw.splitlines(keepends=True):
        if chunk.endswith(b"\r\n"):
            content, ending = chunk[:-2], b"\r\n"
        elif chunk.endswith((b"\n", b"\r")):
            content, ending = chunk[:-1], chunk[-1:]
        else:
            content, ending = chunk, b""
        result.append((content.decode("utf-8", errors="strict"), content, ending))
    return result


def _add_gaps(parent: etree._Element, profile: Mapping[str, object], key: str) -> None:
    for gap in profile.get(key, []):
        if not isinstance(gap, Mapping):
            raise ValueError("profile volume gap is invalid")
        etree.SubElement(parent, f"{{{TEI_NS}}}gap", {
            "reason": "not-retained",
            "unit": "volume",
            "extent": "unknown",
            "n": str(gap["label"]),
        })


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _profile(source_manifest)
    title = str(profile["title"])
    work_id = str(source_manifest.record["work_id"])
    ns = f"{{{TEI_NS}}}"
    root = etree.Element(ns + "TEI", nsmap={None: TEI_NS})
    header = etree.SubElement(root, ns + "teiHeader")
    file_desc = etree.SubElement(header, ns + "fileDesc")
    title_stmt = etree.SubElement(file_desc, ns + "titleStmt")
    etree.SubElement(title_stmt, ns + "title").text = title
    if profile.get("author"):
        etree.SubElement(title_stmt, ns + "author").text = str(profile["author"])
    for editor in profile.get("editors", []):
        etree.SubElement(title_stmt, ns + "editor").text = str(editor)
    edition_stmt = etree.SubElement(file_desc, ns + "editionStmt")
    etree.SubElement(edition_stmt, ns + "edition").text = str(profile["edition_statement"])
    publication = etree.SubElement(file_desc, ns + "publicationStmt")
    etree.SubElement(publication, ns + "publisher").text = "Open Christian Data (candidate reconstruction)"
    availability = etree.SubElement(publication, ns + "availability", status="unknown")
    etree.SubElement(availability, ns + "p").text = "Rights have not been resolved; this candidate does not authorize publication."
    source_desc = etree.SubElement(file_desc, ns + "sourceDesc")
    list_bibl = etree.SubElement(source_desc, ns + "listBibl")

    text_node = etree.SubElement(root, ns + "text")
    front = etree.SubElement(text_node, ns + "front")
    body = etree.SubElement(text_node, ns + "body")
    back = etree.SubElement(text_node, ns + "back")
    _add_gaps(body, profile, "missing_before")
    crosswalk: list[dict[str, object]] = []
    source_census: list[dict[str, object]] = []
    source_members = profile.get("source_members")
    if not isinstance(source_members, list) or not source_members:
        raise ValueError("profile requires source members")

    authorities = {item["name"]: item for item in source_manifest.record["authorities"]}
    for member_index, member in enumerate(source_members, 1):
        if not isinstance(member, Mapping):
            raise ValueError("profile source member is invalid")
        authority_name = str(member["authority"])
        authority = authorities.get(authority_name)
        if not isinstance(authority, Mapping) or authority.get("role") != "primary-source":
            raise ValueError("profile member is not bound to a primary source")
        source_path = source_manifest.authority_path(authority_name)
        raw = source_path.read_bytes()
        path = str(authority["path"])
        volume = str(member["volume"])
        bibl = etree.SubElement(list_bibl, ns + "bibl", {"corresp": f"#{work_id}-vol-{volume}"})
        etree.SubElement(bibl, ns + "title").text = str(member.get("title", title))
        etree.SubElement(bibl, ns + "idno", type="internet-archive-item").text = str(member["item_id"])
        etree.SubElement(bibl, ns + "date").text = str(member.get("date", ""))

        volume_div = etree.SubElement(body, ns + "div", {"type": "volume", "n": volume, XML_ID: f"{work_id}-vol-{volume}"})
        chunks = _line_parts(raw)
        section_starts = {int(section["start_line"]): section for section in member.get("sections", [])}
        current_parent = volume_div
        active_section = None
        byte_offset = 0
        for line_no, (line_text, content_bytes, ending) in enumerate(chunks, 1):
            section = section_starts.get(line_no)
            if section is not None:
                active_section = etree.SubElement(volume_div, ns + "div", {
                    "type": "work",
                    "n": str(section["title"]),
                    XML_ID: f"{work_id}-vol-{volume}-work-{len(section_starts) - len(section_starts) + line_no}",
                })
                current_parent = active_section
            feature_id = f"{work_id}-v{volume}-line-{line_no:05d}"
            carrier = etree.SubElement(current_parent, ns + "ab", {XML_ID: feature_id})
            carrier.text = line_text
            crosswalk.append({
                "feature_id": feature_id,
                "source_member": path,
                "source_sha256": str(authority["sha256"]),
                "volume": volume,
                "line": line_no,
                "byte_start": byte_offset,
                "byte_end": byte_offset + len(content_bytes),
                "line_ending_hex": ending.hex(),
                "text": line_text,
                "text_sha256": _sha(content_bytes),
                "tei_xml_id": feature_id,
                "disposition": "represented-verbatim",
            })
            byte_offset += len(content_bytes) + len(ending)
        if byte_offset != len(raw):
            raise ValueError(f"source byte accounting failed for {path}")
        source_census.append({
            "source_member": path,
            "source_sha256": str(authority["sha256"]),
            "source_bytes": len(raw),
            "line_count": len(chunks),
            "volume": volume,
            "disposition": "included-verbatim",
        })
    _add_gaps(body, profile, "missing_after")
    etree.SubElement(front, ns + "note", type="reconstruction-scope").text = str(profile["scope_note"])
    etree.SubElement(back, ns + "note", type="ocr-limitations").text = str(profile["ocr_note"])
    tei_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    accountability = {
        "contract": "ocd-manifest-acquisition-ocr-accountability-v1",
        "work_id": work_id,
        "profile_id": profile["profile_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_census": source_census,
        "represented_line_count": len(crosswalk),
        "omitted_line_count": 0,
        "duplicated_line_count": 0,
        "crosswalk": crosswalk,
    }
    provenance = {
        "contract": "ocd-source-provenance-v1",
        "work_id": work_id,
        "title": title,
        "edition_statement": profile["edition_statement"],
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_status": "nonaccepted",
        "rights_status": "unresolved",
        "source_members": source_census,
    }
    unresolved = [
        {"id": f"{work_id}-missing-volume-{gap['label']}", "kind": "unretained-volume", "text": "This volume was not in the exact retained item set; no text has been inferred."}
        for gap in profile.get("missing_before", []) + profile.get("missing_after", [])
    ]
    unresolved.extend({"id": str(item["id"]), "kind": "source-quality", "text": str(item["text"])} for item in profile.get("unresolved", []))
    readme = (
        f"# {title}\n\n"
        "Nonaccepted source-to-TEI candidate. Every decoded retained OCR line is carried verbatim and bound to its source member and byte interval in `source-accountability.json`. OCR has not been corrected.\n\n"
        f"{profile['scope_note']}\n\n{profile['ocr_note']}\n"
    )
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": ("".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for item in unresolved)).encode("utf-8"),
        "README.source.md": readme.encode("utf-8"),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
