"""Independent byte, structure, and policy oracle for TCP A41072."""

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


ORACLE_ID = "ocd-tcp-a41072-exact-source-oracle"
ORACLE_VERSION = "1"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _closure_paths() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2]
    return (
        Path(__file__).resolve(),
        root / "ocd_kernel/__init__.py",
        root / "ocd_kernel/library/__init__.py",
        root / "ocd_kernel/library/_common.py",
        root / "ocd_kernel/reconstruction/__init__.py",
        root / "ocd_kernel/reconstruction/contract.py",
    )


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    return _sha(_canonical([{"path": p.relative_to(root).as_posix(), "sha256": _sha(p.read_bytes())} for p in _closure_paths()]))


def _strict_json(content: bytes, label: str) -> dict:
    def pairs(items: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label}: duplicate key {key}")
            result[key] = value
        return result
    value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError(f"{label}: object required")
    return value


def _inspect(content: bytes) -> tuple[etree._Element, dict[str, int], dict[str, int], dict]:
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    elements = list(root.iter())
    counts = dict(sorted(Counter(etree.QName(item).localname for item in elements).items()))
    census = {
        "elements": len(elements),
        "attributes": sum(len(item.attrib) for item in elements),
        "text_nodes": sum(item.text is not None for item in elements),
        "tail_nodes": sum(item.tail is not None for item in elements),
        "characters": sum(len((item.text or "") + (item.tail or "")) for item in elements),
    }
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    features = {
        "tcp_ids": root.xpath("/tei:TEI/tei:teiHeader//tei:idno[@type='TCP']/text()", namespaces=ns),
        "title_stmt_titles": ["".join(item.itertext()) for item in root.xpath("/tei:TEI/tei:teiHeader//tei:titleStmt/tei:title", namespaces=ns)],
        "text_children": [[etree.QName(item).localname, item.get("type")] for item in root.xpath("/tei:TEI/tei:text/*", namespaces=ns)],
        "front_div_types": [item.get("type") for item in root.xpath("/tei:TEI/tei:text/tei:front/tei:div", namespaces=ns)],
        "body_div_types": [item.get("type") for item in root.xpath("/tei:TEI/tei:text/tei:body/tei:div", namespaces=ns)],
        "g_refs": dict(sorted(Counter(item.get("ref") for item in root.xpath("//tei:g", namespaces=ns)).items())),
        "gap_reasons": dict(sorted(Counter(item.get("reason") for item in root.xpath("//tei:gap", namespaces=ns)).items())),
        "page_numbers": [item.get("n") for item in root.xpath("//tei:pb", namespaces=ns)],
    }
    return root, counts, census, features


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source = source_manifest.authority_path("retained-tei-p5").read_bytes()
    content = candidate.member_bytes("content.tei.xml")
    profile = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "profile")
    policy = _strict_json(source_manifest.authority_path("validation-policy").read_bytes(), "policy")
    findings: list[str] = []
    expected_manifest = {"path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(), "sha256": source_manifest.sha256}
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_id") != source_manifest.record["source_id"]:
        findings.append("nonaccepted candidate/source identity binding failed")
    for name, expected in (("source_manifest", expected_manifest), ("converter", source_manifest.record["converter"]), ("package_schema", source_manifest.record["package_schema"])):
        if candidate.manifest.get(name) != expected:
            findings.append(f"candidate {name} binding failed")
    if len(source) != profile["source_bytes"] or _sha(source) != profile["source_sha256"]:
        findings.append("retained source byte binding failed")
    if content != source:
        findings.append("candidate TEI is not byte-identical to retained A41072 XML")
    try:
        root, counts, census, features = _inspect(source)
        if (counts, census, features) != (profile["element_counts"], profile["source_census"], profile["source_features"]):
            findings.append("retained source complete census/features drifted")
        if root.tag != "{http://www.tei-c.org/ns/1.0}TEI":
            findings.append("retained source is not TEI P5")
    except etree.XMLSyntaxError as exc:
        findings.append(f"retained source XML invalid: {exc}")
        root, counts, census = None, {}, {}
    for name, actual, expected in (
        ("README.source.md", candidate.member_bytes("README.source.md"), source_manifest.authority_path("source-local-attribution-readme").read_bytes()),
        ("provenance.json", candidate.member_bytes("provenance.json"), _canonical(policy["provenance"])),
        ("unresolved.jsonl", candidate.member_bytes("unresolved.jsonl"), b"".join(_canonical(row) for row in policy["unresolved"])),
    ):
        if actual != expected:
            findings.append(f"{name} differs from source authority/policy")
    accountability = policy["accountability"] | {
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source), "source_content_sha256": _sha(source),
        "candidate_content_bytes": len(content), "candidate_content_sha256": _sha(content),
        "element_counts": counts, "source_census": census,
    }
    if candidate.member_bytes("source-accountability.json") != _canonical(accountability):
        findings.append("source accountability differs from independent census")
    if not findings:
        candidate_root, c_counts, c_census, c_features = _inspect(content)
        if (c_counts, c_census, c_features) != (counts, census, profile["source_features"]):
            findings.append("candidate source features differ")
        schema = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
        if not schema.validate(candidate_root):
            findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")
    roles = {item["role"]: item for item in source_manifest.record["authorities"]}
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()), "import_closure_sha256": _closure_digest(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": roles["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": roles["candidate-package-schema"]["sha256"],
        "source_sha256": roles["primary-source"]["sha256"],
        "xsd_sha256": roles["tei-validation-schema"]["sha256"],
        "policy_sha256": roles["independent-validation-policy"]["sha256"], "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
