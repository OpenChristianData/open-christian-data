"""Independent byte, identity, license, and one-root oracle for retained PTA TEI."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Mapping

from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
ORACLE_VERSION = "2"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _parse(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, recover=False, huge_tree=False)
    return etree.fromstring(data, parser=parser)


def _closure(root: Path) -> str:
    paths = (
        "build/tei/pta_retained_tei.py",
        "build/tei/pta_retained_tei_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    )
    rows = [{"path": name, "sha256": _sha((root / name).read_bytes())} for name in paths]
    return _sha(_canonical(rows))


def _features(data: bytes) -> dict[str, object]:
    root = _parse(data)
    ns = {"tei": TEI}
    if etree.QName(root).localname != "TEI" or etree.QName(root).namespace != TEI:
        raise ValueError("source/candidate root is not TEI P5")
    titles = root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    if len(titles) != 1:
        raise ValueError("source/candidate does not have exactly one top-level title")
    body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if body is None:
        raise ValueError("source/candidate has no text/body")
    carriers = []
    for position, node in enumerate(body, 1):
        carriers.append({
            "position": position,
            "tag": etree.QName(node).localname if isinstance(node.tag, str) else "comment",
            "type": node.get("type"), "n": node.get("n"), "xml_id": node.get(XML_ID),
            "text_sha256": _sha("".join(node.itertext()).encode("utf-8")),
        })
    return {
        "root_name": "TEI", "root_namespace": TEI, "root_xml_id": root.get(XML_ID),
        "tei_root_count": len(root.xpath("//tei:TEI", namespaces=ns)),
        "tei_element_count": len(root.xpath("//*")),
        "title": " ".join("".join(titles[0].itertext()).split()),
        "title_count": len(titles), "language": root.get("{http://www.w3.org/XML/1998/namespace}lang"),
        "body_direct_child_count": len(body),
        "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
        "whole_document_text_sha256": _sha("".join(root.itertext()).encode("utf-8")),
        "body_carriers": carriers,
    }


def _oracle(source: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    root = source.repository_root
    profile_bytes = source.authority_path("complete-source-feature-profile").read_bytes()
    profile = json.loads(profile_bytes)
    policy_bytes = source.authority_path("independent-validation-policy").read_bytes()
    policy = json.loads(policy_bytes)
    source_bytes = source.authority_path("primary-source").read_bytes()
    candidate_bytes = candidate.member_bytes("content.tei.xml")
    receipt = json.loads(source.authority_path("acquisition-receipt").read_bytes())
    findings: list[str] = []
    if source.record.get("source_id") != profile.get("source_id") or source.record.get("work_id") != profile.get("work_id"):
        findings.append("source-manifest identity differs from route profile")
    if _sha(source_bytes) != profile.get("source_sha256") or len(source_bytes) != profile.get("source_bytes"):
        findings.append("retained PTA source hash or byte count differs")
    if source_bytes != candidate_bytes:
        findings.append("candidate TEI is not byte-identical to the complete retained PTA TEI member")
    if receipt.get("retained_file", {}).get("sha256") != _sha(source_bytes):
        findings.append("acquisition receipt source digest differs")
    if receipt.get("pinned_commit") != profile.get("pinned_commit") or receipt.get("cts_urn") != profile.get("cts_urn"):
        findings.append("pinned source release or CTS locator differs")
    if receipt.get("file_level_license", {}).get("target") != LICENSE:
        findings.append("receipt does not preserve the file-level CC BY-SA license")
    crosswalk_bytes = source.authority_path("source-crosswalk").read_bytes()
    try:
        crosswalk = json.loads(crosswalk_bytes)
        cross_record = next(item for item in crosswalk["records"] if item.get("record_id") == profile["manifest_row"])
        if _sha(crosswalk_bytes) != profile.get("crosswalk_sha256"):
            findings.append("source-selection crosswalk digest differs from the route profile")
        if cross_record.get("classification") != profile.get("crosswalk_classification_before_candidate"):
            findings.append("source-selection crosswalk row classification differs")
    except (json.JSONDecodeError, KeyError, StopIteration, TypeError) as exc:
        findings.append(f"source-selection crosswalk row could not be verified: {exc}")
    try:
        manifest_bytes = Path(profile["canonical_manifest_path"]).read_bytes()
        worklist_bytes = Path(profile["canonical_worklist_path"]).read_bytes()
        if _sha(manifest_bytes) != profile.get("canonical_manifest_sha256"):
            findings.append("canonical manifest digest differs from the route profile")
        if _sha(worklist_bytes) != profile.get("canonical_worklist_sha256"):
            findings.append("canonical worklist digest differs from the route profile")
        if profile.get("manifest_row_text", "").encode("utf-8") not in manifest_bytes.splitlines():
            findings.append("canonical manifest row text differs from the route profile")
        if profile.get("worklist_record_text", "").encode("utf-8") not in worklist_bytes.splitlines():
            findings.append("canonical worklist row text differs from the route profile")
    except (OSError, KeyError, TypeError) as exc:
        findings.append(f"canonical manifest/worklist authority could not be checked: {exc}")
    try:
        source_tree = _parse(source_bytes)
        candidate_tree = _parse(candidate_bytes)
        sfeature = _features(source_bytes)
        cfeature = _features(candidate_bytes)
    except (etree.XMLSyntaxError, ValueError) as exc:
        findings.append(f"source/candidate TEI parse failed: {exc}")
        sfeature = cfeature = {}
        source_tree = candidate_tree = None
    if source_tree is not None and candidate_tree is not None:
        if sfeature != cfeature:
            findings.append("candidate source feature inventory differs")
        if sfeature != profile.get("source_feature_inventory"):
            findings.append("source feature inventory differs from the hash-bound profile")
        schema = compiled_schema()
        if not schema.validate(candidate_tree):
            details = "; ".join(str(error) for error in list(schema.error_log)[:3])
            findings.append(f"candidate TEI fails the vendored TEI P5 schema: {details}")
        if sfeature.get("tei_root_count") != 1 or cfeature.get("tei_root_count") != 1:
            findings.append("candidate must preserve exactly one TEI root")
        if sfeature.get("title_count") != 1 or sfeature.get("title") != profile.get("source_title"):
            findings.append("source top-level title differs from exact route title")
        if candidate_tree.xpath("count(./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)", namespaces={"tei": TEI}) != 1:
            findings.append("candidate must have one top-level title only")
        source_desc = " ".join("".join(source_tree.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces={"tei": TEI})[0].itertext()).split())
        if profile.get("manifest_row") == "L812" and not ("The Third Part of the Ecclesiastical History" in source_desc and "pars tertia" in source_desc):
            findings.append("John Syriac source description no longer establishes the Part III boundary")
    expected_account = {
        "contract": "ocd-pta-exact-tei-source-accounting-v1",
        "manifest_row": profile["manifest_row"], "work_id": source.record["work_id"],
        "source_id": source.record["source_id"], "scope_id": profile["scope_id"],
        "canonical_title": profile["canonical_title"], "source_title": profile["source_title"],
        "cts_urn": profile["cts_urn"], "pinned_commit": profile["pinned_commit"],
        "source_path": profile["source_path"], "source_sha256": _sha(source_bytes),
        "source_bytes": len(source_bytes), "candidate_tei_sha256": _sha(candidate_bytes),
        "candidate_tei_bytes": len(candidate_bytes), "copy_mode": "exact-byte-preserving-retained-TEI",
        "source_scope": profile["source_scope"], "coverage_limits": profile["coverage_limits"],
        "file_level_license": profile["file_level_license"],
        "one_top_level_title_per_tei": True, "whole_source_member_represented_once": True,
        "feature_inventory": sfeature,
    }
    try:
        observed_account = json.loads(candidate.member_bytes("source-accountability.json"))
        if observed_account != expected_account:
            findings.append("source-accountability member differs from independent source inventory")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        findings.append(f"source-accountability member is invalid: {exc}")
    if candidate.member_bytes("README.source.md") != source.authority_path("source-attribution").read_bytes():
        findings.append("candidate attribution README differs from source-attribution authority")
    if candidate.member_bytes("provenance.json") != _canonical(policy["provenance"]):
        findings.append("candidate provenance differs from the nonaccepted route policy")
    expected_unresolved = b"".join(_canonical(item) for item in policy["unresolved"])
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        findings.append("candidate unresolved status differs from the route policy")
    if source.record.get("validator", {}).get("import_closure_sha256") != _closure(root):
        findings.append("oracle import-closure binding is stale")
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": "ocd-pta-retained-tei-independent-source-equality-oracle",
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure(root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source_bytes),
        "xsd_sha256": _sha(source.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": list(dict.fromkeys(findings)),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = "ocd-pta-retained-tei-independent-source-equality-oracle"
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
_oracle.import_closure = _closure
