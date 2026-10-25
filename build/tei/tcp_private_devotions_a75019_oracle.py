"""Producer-independent oracle for the exact-byte EEBO-TCP A75019 candidate."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-eebo-tcp-a75019-exact-source-oracle"
ORACLE_VERSION = "3"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json_object(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _strict_jsonl(content: bytes, label: str) -> list[dict[str, object]]:
    if not content or not content.endswith(b"\n"):
        raise ValueError(f"{label} must be nonempty LF-terminated JSONL")
    lines = content.splitlines()
    if any(not line for line in lines):
        raise ValueError(f"{label} has an empty record")
    return [_strict_json_object(line, f"{label}[{index}]") for index, line in enumerate(lines)]


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
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in _closure_paths()
    ]
    return _sha(_canonical(records))


def _parse(content: bytes) -> etree._Element:
    return etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = list(root.iter())
    counts = Counter(etree.QName(element).localname for element in elements)
    census = {
        "elements": len(elements),
        "attributes": sum(len(element.attrib) for element in elements),
        "text_nodes": sum(element.text is not None for element in elements),
        "tail_nodes": sum(element.tail is not None for element in elements),
        "characters": sum(
            len((element.text or "") + (element.tail or "")) for element in elements
        ),
    }
    return dict(sorted(counts.items())), census


def _plain_mapping(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_bytes = source_manifest.authority_path("retained-tei-p5").read_bytes()
    candidate_bytes = candidate.member_bytes("content.tei.xml")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json_object(profile_bytes, "reconstruction profile")
    policy = _strict_json_object(policy_bytes, "validation policy")
    findings: list[str] = []

    expected_source_manifest = {
        "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    expected_converter = dict(source_manifest.record["converter"])
    expected_package_schema = dict(source_manifest.record["package_schema"])
    if candidate.manifest.get("status") != "nonaccepted":
        findings.append("candidate manifest status is not nonaccepted")
    if candidate.manifest.get("source_id") != source_manifest.record.get("source_id"):
        findings.append("candidate manifest source_id binding failed")
    if _plain_mapping(candidate.manifest.get("source_manifest")) != expected_source_manifest:
        findings.append("candidate manifest source-manifest path or digest binding failed")
    if _plain_mapping(candidate.manifest.get("converter")) != expected_converter:
        findings.append("candidate manifest converter binding failed")
    if _plain_mapping(candidate.manifest.get("package_schema")) != expected_package_schema:
        findings.append("candidate manifest package-schema binding failed")

    readme_bytes = candidate.member_bytes("README.source.md")
    expected_readme = source_manifest.authority_path(
        "source-local-attribution-readme"
    ).read_bytes()
    if readme_bytes != expected_readme or _sha(readme_bytes) != policy.get("readme_sha256"):
        findings.append("source README bytes do not match the bound attribution authority")

    provenance_bytes = candidate.member_bytes("provenance.json")
    expected_provenance = _canonical(policy.get("provenance"))
    try:
        provenance = _strict_json_object(provenance_bytes, "provenance")
    except ValueError:
        provenance = None
    if provenance is None or provenance_bytes != expected_provenance:
        findings.append("provenance bytes do not match the complete validation policy")

    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    expected_unresolved_rows = policy.get("unresolved")
    expected_unresolved = (
        b"".join(_canonical(row) for row in expected_unresolved_rows)
        if isinstance(expected_unresolved_rows, list)
        else b""
    )
    try:
        unresolved = _strict_jsonl(unresolved_bytes, "unresolved ledger")
    except ValueError:
        unresolved = None
    if unresolved is None or unresolved != expected_unresolved_rows or unresolved_bytes != expected_unresolved:
        findings.append("unresolved ledger records, order, status, or bytes differ from policy")

    try:
        source_root = _parse(source_bytes)
        source_counts, source_census = _census(source_root)
    except etree.XMLSyntaxError as exc:
        findings.append(f"retained source XML parsing failed: {exc}")
        source_root = None
        source_counts = {}
        source_census = {}
    if source_counts != profile.get("element_counts") or source_census != profile.get("source_census"):
        findings.append("retained source census does not match profile")
    if source_root is not None:
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        title = source_root.xpath("string(./t:teiHeader/t:fileDesc/t:titleStmt/t:title)", namespaces=ns)
        author = source_root.xpath("string(./t:teiHeader/t:fileDesc/t:sourceDesc/t:biblFull/t:titleStmt/t:author)", namespaces=ns)
        source_note = source_root.xpath("string(./t:teiHeader/t:fileDesc/t:sourceDesc/t:biblFull/t:notesStmt/t:note[1])", namespaces=ns)
        tcp_id = source_root.xpath("string(./t:teiHeader/t:fileDesc/t:publicationStmt/t:idno[@type='DLPS'])", namespaces=ns)
        date = source_root.xpath("string(./t:teiHeader/t:fileDesc/t:sourceDesc/t:biblFull/t:publicationStmt/t:date)", namespaces=ns)
        license_target = source_root.xpath("string(./t:teiHeader/t:fileDesc/t:publicationStmt/t:availability//t:ref/@target)", namespaces=ns)
        identity = {"title": title, "author": author, "source_attribution_note": source_note,
                    "tcp_id": tcp_id, "print_date": date, "license_target": license_target}
        if identity != profile.get("identity"):
            findings.append("TCP A75019 title, qualified authorship, date, or licensed text layer changed")
        text = source_root.find("{http://www.tei-c.org/ns/1.0}text")
        if text is None:
            findings.append("source TEI text is absent")
        else:
            parts = [etree.QName(child).localname for child in text if isinstance(child.tag, str)]
            if parts != profile.get("text_parts"):
                findings.append("source front/body/back sequence differs from profile")
            divisions = []
            for element in text.iter():
                if isinstance(element.tag, str) and etree.QName(element).localname == "div":
                    heading = " ".join("".join(element.find("{http://www.tei-c.org/ns/1.0}head").itertext()).split()) if element.find("{http://www.tei-c.org/ns/1.0}head") is not None else ""
                    divisions.append({"type": element.get("type"), "head": heading})
            if divisions != profile.get("ordered_divisions"):
                findings.append("source division order or heading attachment differs from profile")
            pages = [{"n": node.get("n"), "facs": node.get("facs"), "rendition": node.get("rendition")}
                     for node in text.iter() if isinstance(node.tag, str) and etree.QName(node).localname == "pb"]
            if pages != profile.get("ordered_pages"):
                findings.append("source page and facsimile milestone sequence differs from profile")
        xml_id = "{http://www.w3.org/XML/1998/namespace}id"
        ids = [node.get(xml_id) for node in source_root.iter() if isinstance(node.tag, str) and node.get(xml_id)]
        internal = [node.get("target") for node in source_root.iter() if isinstance(node.tag, str) and
                    etree.QName(node).localname == "ref" and node.get("target", "").startswith("#")]
        if ids != profile.get("source_xml_ids") or internal != profile.get("internal_targets"):
            findings.append("source ID or fragment-link census differs from profile")
        if len(ids) != len(set(ids)) or any(target[1:] not in set(ids) for target in internal):
            findings.append("source fragment target does not resolve uniquely")

    accountability_policy = policy.get("accountability")
    expected_accountability = {
        **accountability_policy,
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source_bytes),
        "source_content_sha256": _sha(source_bytes),
        "candidate_content_bytes": len(candidate_bytes),
        "candidate_content_sha256": _sha(candidate_bytes),
        "source_census": source_census,
        "element_counts": source_counts,
    } if isinstance(accountability_policy, dict) else {}
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    try:
        accountability = _strict_json_object(accountability_bytes, "source accountability")
    except ValueError:
        accountability = None
    if accountability is None or accountability_bytes != _canonical(expected_accountability):
        findings.append("source accountability bytes do not bind the complete path, census, counts, and zero-loss policy")

    if candidate_bytes != source_bytes:
        findings.append("candidate TEI is not byte-identical to retained A75019 XML")

    # Inspect candidate identifiers and links even if a separate byte-conservation
    # finding already rejects it. This makes fragment closure an independent gate.
    try:
        candidate_root = _parse(candidate_bytes)
    except etree.XMLSyntaxError as exc:
        findings.append(f"candidate XML parsing failed: {exc}")
    else:
        candidate_counts, candidate_census = _census(candidate_root)
        if candidate_counts != source_counts or candidate_census != source_census:
            findings.append("candidate census does not match retained source")
        xml_id = "{http://www.w3.org/XML/1998/namespace}id"
        candidate_ids = [node.get(xml_id) for node in candidate_root.iter()
                         if isinstance(node.tag, str) and node.get(xml_id)]
        candidate_internal = [node.get("target") for node in candidate_root.iter()
                              if isinstance(node.tag, str) and etree.QName(node).localname == "ref"
                              and node.get("target", "").startswith("#")]
        if candidate_ids != profile.get("source_xml_ids") or candidate_internal != profile.get("internal_targets"):
            findings.append("candidate source-ID or internal-link mapping changed")
        if len(candidate_ids) != len(set(candidate_ids)) or any(
            target[1:] not in set(candidate_ids) for target in candidate_internal
        ):
            findings.append("candidate internal fragment target does not resolve uniquely")
        # P5 validation is required for a passing candidate. Already rejected
        # mutations need only the focused structural and byte-conservation checks.
        if not findings:
            schema = etree.XMLSchema(
                etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
            )
            if not schema.validate(candidate_root):
                findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")

    bindings = {item["role"]: item for item in source_manifest.record["authorities"]}
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
        "profile_sha256": bindings["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": bindings["candidate-package-schema"]["sha256"],
        "source_sha256": bindings["primary-source"]["sha256"],
        "xsd_sha256": bindings["tei-validation-schema"]["sha256"],
        "policy_sha256": bindings["independent-validation-policy"]["sha256"],
        "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
