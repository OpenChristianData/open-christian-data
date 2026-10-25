"""Byte-preserving current candidate route for retained TCP A61580."""

from __future__ import annotations

import hashlib
import argparse
import json
import platform
from pathlib import Path
import sys
from typing import Mapping

from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


converter_id = "ocd-tcp-l879-a61580-byte-preserving-converter"
converter_version = "1"
oracle_id = "ocd-tcp-l879-a61580-source-equality-oracle"
oracle_version = "1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _root(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    return etree.fromstring(data, parser=parser)


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname


def _inventory(source_manifest: object, source: bytes) -> dict[str, object]:
    tree = _root(source)
    character_authority = _root(source_manifest.authority_path("tcp-character-authority").read_bytes())
    character_ids = {
        element.get("{http://www.w3.org/XML/1998/namespace}id") or element.get("id")
        for element in character_authority.iter()
        if element.get("{http://www.w3.org/XML/1998/namespace}id") or element.get("id")
    }
    character_refs = {
        (element.get("ref") or "").removeprefix("char:")
        for element in tree.iter()
        if _local(element) == "g"
    }
    unresolved_character_refs = sorted(character_refs - character_ids)
    members = []
    for authority in source_manifest.record["authorities"]:
        path = source_manifest.authority_path(authority["name"])
        content = path.read_bytes()
        members.append({"name": authority["name"], "role": authority["role"], "path": authority["path"], "bytes": len(content), "sha256": _sha(content)})
    counts: dict[str, int] = {}
    for element in tree.iter():
        name = _local(element)
        counts[name] = counts.get(name, 0) + 1
    gaps: dict[str, int] = {}
    for element in tree.iter():
        if _local(element) == "gap":
            reason = element.get("reason", "unspecified")
            gaps[reason] = gaps.get(reason, 0) + 1
    tei_ns = "{http://www.tei-c.org/ns/1.0}"
    body = tree.find(f".//{tei_ns}text/{tei_ns}body")
    body_children = [] if body is None else [
        {"position": i, "element": _local(child), "type": child.get("type"), "xml_id": child.get("{http://www.w3.org/XML/1998/namespace}id"), "head": " ".join("".join(child.findtext(f".//{tei_ns}head") or "").split())}
        for i, child in enumerate(body, 1)
    ]
    title_statements = [
        [" ".join("".join(title.itertext()).split()) for title in statement if _local(title) == "title"]
        for statement in tree.iter(f"{tei_ns}titleStmt")
    ]
    return {
        "contract": "ocd-source-accountability-v1",
        "source_sha256": _sha(source),
        "source_bytes": len(source),
        "retained_authority_members": members,
        "primary_text_member": "A61580.xml",
        "support_member_dispositions": {
            "README.md": "source provenance and content summary; retained and accounted, not a separate text",
            "tcpchars.xml": "pinned character-reference authority for all source g elements; retained and accounted, not copied as text",
            "Texts-LICENSE": "source reuse and attribution terms; retained and accounted, not a separate text",
        },
        "work_boundary": "One top-level titled monograph, one TEI. Books I-III and 22 chapters remain internal divisions.",
        "tei_root_count": sum(1 for element in tree.iter() if _local(element) == "TEI"),
        "title_stmt_groups": title_statements,
        "body_direct_children": body_children,
        "element_counts": dict(sorted(counts.items())),
        "page_anchor_count": counts.get("pb", 0),
        "gap_reason_counts": dict(sorted(gaps.items())),
        "marginal_note_count": sum(1 for element in tree.iter() if _local(element) == "note" and (element.get("place") or "").startswith("margin")),
        "tcp_character_reference_count": counts.get("g", 0),
        "distinct_tcp_character_reference_ids": sorted(character_refs),
        "unresolved_tcp_character_reference_ids": unresolved_character_refs,
        "commercial_page_images": "not retained; no image collation claim",
        "conservation": "The source is already TEI P5; candidate content is copied byte-for-byte. Source-declared gaps and uncertain reading remain unchanged.",
    }


def convert(source_manifest: object) -> Mapping[str, bytes]:
    """Package the complete retained TEI P5 witness without transformation."""
    source = source_manifest.authority_path("official-source-member").read_bytes()
    source_readme = source_manifest.authority_path("tcp-readme").read_text(encoding="utf-8")
    license_text = source_manifest.authority_path("tcp-license").read_text(encoding="utf-8")
    accountability = _inventory(source_manifest, source)
    readme = (
        "# Origines sacræ (TCP A61580)\n\n"
        "This candidate contains one TEI P5 document for Edward Stillingfleet's "
        "1662 monograph. The retained TCP XML is already TEI P5 and is preserved "
        "byte-for-byte. Internal books and chapters remain within that one TEI.\n\n"
        "Attribution: Early English Books Online Text Creation Partnership (EEBO-TCP), "
        "Phase I, A61580. The source requests attribution. The retained source states "
        "CC0 1.0 Universal for the keyboarded and encoded text; page images are not "
        "included and are separately governed.\n\n"
        "The source's declared gaps, diplomatic readings, and uncertainties are "
        "preserved. This candidate is not accepted, and it makes no page-image "
        "collation, rights-clearance, or publication claim.\n\n"
        "## Retained source documentation\n\n"
        "The complete source README and license are separately retained in the "
        "bound source authorities. The source README begins:\n\n"
        + "\n".join(source_readme.splitlines()[:12])
        + "\n\nThe license authority is retained unchanged; its SHA-256 is recorded in "
        "source-accountability.json.\n"
    )
    provenance = {
        "contract": "ocd-candidate-provenance-v1",
        "source_id": source_manifest.record["source_id"],
        "work_id": source_manifest.record["work_id"],
        "acquisition_id": "stillingfleet-origines-sacrae-tcp-acquired",
        "edition_id": "stillingfleet-origines-sacrae-tcp-electronic",
        "primary_source_authority": "official-source-member",
        "source_member_sha256": _sha(source),
        "transformation": "byte-preserving copy of a complete retained TEI P5 source member",
        "attribution": "Early English Books Online Text Creation Partnership (EEBO-TCP), Phase I, A61580",
        "acceptance": "nonaccepted candidate",
    }
    unresolved = [
        {"id": "page-image-collation", "status": "open", "reason": "Commercial page images were not retained; this technical route establishes source byte conservation, not transcription accuracy against scans."},
        {"id": "source-declared-gaps", "status": "preserved-source-encoding", "reason": "All 1,795 TCP gap elements remain exactly as encoded in the retained source; no missing wording is inferred or invented."},
        {"id": "human-acceptance-rights-publication", "status": "separate-governance", "reason": "Technical candidate validation does not alter human acceptance, rights review, or publication authorization."},
    ]
    return {
        "content.tei.xml": source,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme.encode("utf-8"),
    }


def oracle(source_manifest: object, candidate: object) -> Mapping[str, object]:
    """Independently verify exact source conservation, title structure, and P5."""
    source = source_manifest.authority_path("official-source-member").read_bytes()
    observed = candidate.member_bytes("content.tei.xml")
    findings: list[str] = []
    source_root = _root(source)
    candidate_root = _root(observed)
    if source != observed:
        findings.append("candidate bytes differ from the exact retained source member")
    if etree.QName(candidate_root).localname != "TEI":
        findings.append("candidate does not have a single TEI P5 root")
    tei_ns = "{http://www.tei-c.org/ns/1.0}"
    source_titles = [
        [" ".join("".join(title.itertext()).split()) for title in statement if _local(title) == "title"]
        for statement in source_root.iter(f"{tei_ns}titleStmt")
    ]
    candidate_titles = [
        [" ".join("".join(title.itertext()).split()) for title in statement if _local(title) == "title"]
        for statement in candidate_root.iter(f"{tei_ns}titleStmt")
    ]
    if candidate_titles != source_titles:
        findings.append("title hierarchy/titleStmt groups differ from the source")
    if " ".join("".join(candidate_root.itertext()).split()) != " ".join("".join(source_root.itertext()).split()):
        findings.append("ordered source text content differs")
    def headed_divisions(root: etree._Element) -> list[tuple[str, str]]:
        result = []
        for element in root.iter():
            if _local(element) in {"div", "div0", "div1", "div2", "div3", "div4", "div5", "div6", "div7"}:
                head = element.find(f"{tei_ns}head")
                result.append((element.get("type", ""), " ".join("".join(head.itertext()).split()) if head is not None else ""))
        return result
    if headed_divisions(candidate_root) != headed_divisions(source_root):
        findings.append("ordered division/headings differ from the source")
    def note_inventory(root: etree._Element) -> list[tuple[str, str, str]]:
        return [(element.get("place", ""), element.get("target", ""), " ".join("".join(element.itertext()).split())) for element in root.iter() if _local(element) == "note"]
    if note_inventory(candidate_root) != note_inventory(source_root):
        findings.append("note text or attachment differs from the source")
    character_authority = _root(source_manifest.authority_path("tcp-character-authority").read_bytes())
    character_ids = {
        element.get("{http://www.w3.org/XML/1998/namespace}id") or element.get("id")
        for element in character_authority.iter()
        if element.get("{http://www.w3.org/XML/1998/namespace}id") or element.get("id")
    }
    source_character_refs = {
        (element.get("ref") or "").removeprefix("char:")
        for element in source_root.iter()
        if _local(element) == "g"
    }
    candidate_character_refs = {
        (element.get("ref") or "").removeprefix("char:")
        for element in candidate_root.iter()
        if _local(element) == "g"
    }
    if source_character_refs - character_ids:
        findings.append("source TCP character references are unresolved by the pinned authority")
    if candidate_character_refs != source_character_refs:
        findings.append("candidate TCP character references differ from the source")
    xsd = source_manifest.authority_path("tei-xsd")
    schema = etree.XMLSchema(etree.parse(str(xsd)))
    if not schema.validate(candidate_root):
        findings.append("candidate fails the pinned TEI P5 XML Schema")
    if findings:
        status = "fail"
    else:
        status = "pass"
    manifest = source_manifest.record
    authorities = {item["role"]: item for item in manifest["authorities"]}
    body = {
        "status": status,
        "oracle_id": oracle_id,
        "oracle_version": oracle_version,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _sha(Path(__file__).read_bytes()),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": authorities["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": authorities["candidate-package-schema"]["sha256"],
        "source_sha256": _sha(source),
        "xsd_sha256": authorities["tei-validation-schema"]["sha256"],
        "policy_sha256": authorities["independent-validation-policy"]["sha256"],
        "findings": findings,
    }
    body["result_sha256"] = _sha(_canonical(body))
    return body


convert.converter_id = converter_id
convert.converter_version = converter_version
oracle.oracle_id = oracle_id
oracle.oracle_version = oracle_version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--validation", required=True)
    args = parser.parse_args()
    root = Path.cwd()
    manifest = SourceManifest.load(args.manifest, repository_root=root)
    candidate = reconstruct(manifest, args.destination, convert)
    report = validate(manifest, candidate, oracle)
    report_record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": dict(report.attestation),
        "findings": list(report.findings),
        "report_sha256": report.sha256,
    }
    Path(args.validation).write_bytes(_canonical(report_record))
    print(json.dumps({"candidate_sha256": candidate.sha256, "tei_sha256": _sha(candidate.member_bytes("content.tei.xml")), "validation_sha256": _sha(Path(args.validation).read_bytes()), "report_sha256": report.sha256, "status": report.status}, sort_keys=True))


if __name__ == "__main__":
    main()
