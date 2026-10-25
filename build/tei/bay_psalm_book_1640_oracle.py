"""Independent whole-member oracle for the retained TCP N00001 TEI."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


TEI = "{http://www.tei-c.org/ns/1.0}"
ORACLE_ID = "ocd-tcp-n00001-independent-complete-source"
ORACLE_VERSION = "1"
SOURCE_ID = "tcp-N00001"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse(content: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_comments=False,
        huge_tree=True,
    )
    root = etree.fromstring(content, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("N00001 has an unexpected doctype")
    if root.xpath("//comment() | //processing-instruction()"):
        raise ValueError("N00001 has an unexpected comment or processing instruction")
    return root


def _sequence_sha(value: object) -> str:
    return _sha(_canonical(value))


def _inspect(content: bytes) -> tuple[dict[str, int], dict[str, int], dict[str, object]]:
    root = _parse(content)
    elements = list(root.iter())
    counts = dict(sorted(Counter(etree.QName(item).localname for item in elements).items()))
    census = {
        "elements": len(elements),
        "attributes": sum(len(item.attrib) for item in elements),
        "text_nodes": sum(item.text is not None for item in elements),
        "tail_nodes": sum(item.tail is not None for item in elements),
        "characters": sum(len((item.text or "") + (item.tail or "")) for item in elements),
    }
    ns = {"tei": TEI[1:-1]}
    body_books = root.xpath("/tei:TEI/tei:text/tei:body/tei:div", namespaces=ns)
    gaps = root.xpath("//tei:gap", namespaces=ns)
    page_breaks = root.xpath("//tei:pb", namespaces=ns)
    features: dict[str, object] = {
        "text_children": [
            [etree.QName(item).localname, item.get("type")]
            for item in root.xpath("/tei:TEI/tei:text/*", namespaces=ns)
        ],
        "front_division_types": [
            item.get("type")
            for item in root.xpath("/tei:TEI/tei:text/tei:front/tei:div", namespaces=ns)
        ],
        "body_division_types": [item.get("type") for item in body_books],
        "body_book_division_counts": [
            len(item.xpath("./tei:div", namespaces=ns)) for item in body_books
        ],
        "body_book_line_counts": [
            len(item.xpath(".//tei:l", namespaces=ns)) for item in body_books
        ],
        "back_division_types": [
            item.get("type")
            for item in root.xpath("/tei:TEI/tei:text/tei:back/tei:div", namespaces=ns)
        ],
        "gap_count": len(gaps),
        "gap_reasons": dict(sorted(Counter(item.get("reason") or "" for item in gaps).items())),
        "gap_reason_unit_extent_sha256": _sequence_sha(
            [[item.get("reason"), item.get("unit"), item.get("extent")] for item in gaps]
        ),
        "page_break_count": len(page_breaks),
        "page_facs_sha256": _sequence_sha([item.get("facs") for item in page_breaks]),
        "line_group_count": len(root.xpath("//tei:lg", namespaces=ns)),
        "line_count": len(root.xpath("//tei:l", namespaces=ns)),
        "note_count": len(root.xpath("//tei:note", namespaces=ns)),
        "table_count": len(root.xpath("//tei:table", namespaces=ns)),
    }
    if root.tag != TEI + "TEI":
        raise ValueError("N00001 does not have a TEI P5 root")
    return counts, census, features


def _content_findings(
    source: bytes,
    content: bytes,
    profile: Mapping[str, object],
    *,
    schema_path: Path | None,
) -> list[str]:
    findings: list[str] = []
    if len(source) != profile.get("source_bytes") or _sha(source) != profile.get("source_sha256"):
        findings.append("retained N00001 source byte binding failed")
    if content != source:
        findings.append("candidate TEI is not byte-identical to retained N00001 XML")
    try:
        counts, census, features = _inspect(content)
    except (etree.XMLSyntaxError, ValueError) as exc:
        return findings + [f"candidate N00001 XML envelope failed: {exc}"]
    if counts != profile.get("element_counts"):
        findings.append("candidate N00001 element census differs")
    if census != profile.get("source_census"):
        findings.append("candidate N00001 text, tail, or attribute census differs")
    if features != profile.get("source_features"):
        findings.append("candidate N00001 front/body/back, gap, page, verse, note, or table features differ")
    if schema_path is not None:
        schema = etree.XMLSchema(
            etree.parse(
                str(schema_path),
                etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
            )
        )
        candidate_root = _parse(content)
        if not schema.validate(etree.ElementTree(candidate_root)):
            findings.append(f"candidate N00001 TEI P5 validation failed: {schema.error_log.last_error}")
    return findings


def _closure_paths() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2]
    return (
        Path(__file__).resolve(),
        root / "ocd_kernel/__init__.py",
        root / "ocd_kernel/reconstruction/__init__.py",
        root / "ocd_kernel/reconstruction/contract.py",
    )


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    return _sha(
        _canonical(
            [
                {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
                for path in _closure_paths()
            ]
        )
    )


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source = source_manifest.authority_path("retained-tei-p5").read_bytes()
    content = candidate.member_bytes("content.tei.xml")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = json.loads(profile_bytes)
    policy = json.loads(policy_bytes)
    findings = _content_findings(
        source,
        content,
        profile,
        schema_path=source_manifest.authority_path("tei-p5-xsd"),
    )
    if (
        source_manifest.record.get("source_id") != SOURCE_ID
        or source_manifest.record.get("work_id") != "bay-psalm-book-1640"
        or profile.get("contract") != "ocd-tcp-n00001-complete-source-profile-v1"
        or policy.get("contract") != "ocd-tcp-n00001-exact-source-policy-v1"
    ):
        findings.append("N00001 manifest, profile, policy, or work identity differs")
    receipt = json.loads(
        source_manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8")
    )
    member = receipt.get("member", {})
    if (
        member.get("path") != profile.get("source_path")
        or member.get("bytes") != len(source)
        or member.get("sha256") != _sha(source)
        or receipt.get("verification", {}).get("member_count") != 1
    ):
        findings.append("N00001 retained acquisition identity or one-member scope differs")
    expected_manifest = {
        "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    for name, expected in (
        ("source_manifest", expected_manifest),
        ("converter", source_manifest.record["converter"]),
        ("package_schema", source_manifest.record["package_schema"]),
    ):
        if candidate.manifest.get(name) != expected:
            findings.append(f"candidate {name} binding failed")
    if candidate.manifest.get("status") != "nonaccepted":
        findings.append("candidate status is not nonaccepted")
    for name, expected in (
        ("README.source.md", source_manifest.authority_path("source-credit").read_bytes()),
        ("provenance.json", _canonical(policy["provenance"])),
        ("unresolved.jsonl", b"".join(_canonical(item) for item in policy["unresolved"])),
    ):
        if candidate.member_bytes(name) != expected:
            findings.append(f"candidate {name} differs from its authority")
    counts, census, features = _inspect(source)
    accountability = policy["accountability"] | {
        "source_id": SOURCE_ID,
        "source_content_bytes": len(source),
        "source_content_sha256": _sha(source),
        "candidate_content_bytes": len(content),
        "candidate_content_sha256": _sha(content),
        "element_counts": counts,
        "source_census": census,
        "source_features": features,
        "acquisition_receipt_sha256": _sha(
            source_manifest.authority_path("acquisition-receipt").read_bytes()
        ),
        "member_inventory_sha256": _sha(
            source_manifest.authority_path("member-inventory").read_bytes()
        ),
    }
    if candidate.member_bytes("source-accountability.json") != _canonical(accountability):
        findings.append("candidate N00001 source accountability differs from independent census")
    roles = {item["role"]: item for item in source_manifest.record["authorities"]}
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_digest(),
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": roles["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": roles["candidate-package-schema"]["sha256"],
        "source_sha256": roles["primary-source"]["sha256"],
        "xsd_sha256": roles["tei-validation-schema"]["sha256"],
        "policy_sha256": roles["independent-validation-policy"]["sha256"],
        "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
