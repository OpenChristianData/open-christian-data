"""Independent lxml oracle for the complete retained N18328 package."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_ID = "tcp-N18328"
ORACLE_ID = "ocd-convicts-n18328-independent-complete-xml"
ORACLE_VERSION = "1"
REVISION = "convicts-n18328-electronic-agent-v1"
IDENTITY = {
    "work_id": "convicts-visitor",
    "textual_form_id": "convicts-visitor-tcp-retained",
    "edition_id": "convicts-visitor-tcp-electronic",
    "acquisition_id": "convicts-visitor-tcp-acquired",
}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _parse(content: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False)
    root = etree.fromstring(content, parser)
    if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
        raise ValueError("unsupported N18328 XML declaration, comment, or instruction")
    return root


def _text_counts(text: etree._Element) -> dict[str, int]:
    return dict(sorted(Counter(etree.QName(node).localname for node in text.iter()).items()))


def _suffix(content: bytes) -> bytes:
    parts = content.split(b"</teiHeader>", 1)
    if len(parts) != 2:
        raise ValueError("N18328 TEI header boundary is absent")
    return parts[1]


def _check(source: bytes, content: bytes, profile: Mapping[str, object], *, schema_path: Path | None) -> list[str]:
    problems: list[str] = []
    try:
        original = _parse(source)
        candidate = _parse(content)
        source_suffix = _suffix(source)
        candidate_suffix = _suffix(content)
    except (etree.XMLSyntaxError, ValueError) as exc:
        return [f"N18328 XML parse or envelope failed: {exc}"]
    if original.tag != TEI + "TEI" or candidate.tag != original.tag:
        return ["N18328 source/candidate requires one TEI root"]
    source_header = original.find(TEI + "teiHeader")
    candidate_header = candidate.find(TEI + "teiHeader")
    source_text = original.find(TEI + "text")
    candidate_text = candidate.find(TEI + "text")
    if (source_header is None or candidate_header is None or source_text is None
            or candidate_text is None or len(original) != 2 or len(candidate) != 2):
        return ["N18328 source/candidate header or complete text is absent"]

    if (len(source) != profile.get("source_bytes") or _sha(source) != profile.get("source_sha256")
            or _sha(source_suffix) != profile.get("source_text_suffix_sha256")):
        problems.append("retained N18328 source bytes or text suffix differ from profile")
    if _sha(content) != profile.get("candidate_sha256"):
        problems.append("candidate bytes differ from the pinned N18328 candidate")
    if (source_suffix != candidate_suffix
            or etree.tostring(source_text, with_tail=False) != etree.tostring(candidate_text, with_tail=False)):
        problems.append("candidate complete text or exact text suffix differs from source")
    if _sha(etree.tostring(source_text, with_tail=False)) != profile.get("source_text_tree_sha256"):
        problems.append("retained N18328 text tree differs from profile")
    if _sha(etree.tostring(source_header, with_tail=False)) != profile.get("source_header_tree_sha256"):
        problems.append("retained N18328 header differs from profile")
    if _text_counts(source_text) != profile.get("text_element_counts"):
        problems.append("retained N18328 text element census differs from profile")
    front = source_text.find(TEI + "front")
    body = source_text.find(TEI + "body")
    if (front is None or body is None or [part.tag for part in source_text] != [TEI + "front", TEI + "body"]
            or [division.get("type") for division in front] != profile.get("front_division_types")
            or [division.get("type") for division in body] != profile.get("body_division_types")):
        problems.append("N18328 complete front/body work boundary differs")

    values = {node.get("type"): node.text for node in candidate_header.iter(TEI + "idno")}
    expected_values = IDENTITY | {
        "source_sha256": str(profile["source_sha256"]),
        "source_bytes": str(profile["source_bytes"]),
        "sha256": str(profile["source_sha256"]),
        "representation_revision": REVISION,
    }
    if any(values.get(key) != value for key, value in expected_values.items()):
        problems.append("N18328 candidate identity, source, or revision header binding differs")

    stripped = deepcopy(candidate_header)
    source_desc = stripped.find(TEI + "fileDesc/" + TEI + "sourceDesc")
    revision_desc = stripped.find(TEI + "revisionDesc")
    if source_desc is None or revision_desc is None:
        problems.append("N18328 candidate header additions are absent")
    else:
        bindings = [node for node in source_desc if node.tag == TEI + "bibl"
                    and any(item.get("type") == "work_id" and item.text == IDENTITY["work_id"]
                            for item in node.iter(TEI + "idno"))]
        changes = [node for node in revision_desc if node.tag == TEI + "change"
                   and node.get(XML_ID) == REVISION]
        if len(bindings) != 1 or len(changes) != 1:
            problems.append("N18328 candidate header additions differ")
        else:
            source_desc.remove(bindings[0])
            revision_desc.remove(changes[0])
            if etree.tostring(stripped, with_tail=False) != etree.tostring(source_header, with_tail=False):
                problems.append("candidate surviving header differs from retained source")

    if schema_path is not None:
        schema = etree.XMLSchema(etree.parse(str(schema_path), etree.XMLParser(resolve_entities=False, no_network=True)))
        if not schema.validate(etree.ElementTree(candidate)):
            problems.append(f"N18328 candidate TEI P5 validation failed: {schema.error_log.last_error}")
    return problems


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    paths = (Path(__file__).resolve(), root / "ocd_kernel/__init__.py",
             root / "ocd_kernel/reconstruction/__init__.py", root / "ocd_kernel/reconstruction/contract.py")
    return _sha(_json([{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
                       for path in paths]))


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source = manifest.authority_path("retained-tei-p5").read_bytes()
    content = candidate.member_bytes("content.tei.xml")
    profile_bytes = manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = manifest.authority_path("validation-policy").read_bytes()
    profile = json.loads(profile_bytes)
    policy = json.loads(policy_bytes)
    problems = _check(source, content, profile, schema_path=manifest.authority_path("tei-p5-xsd"))
    if (manifest.record.get("source_id") != SOURCE_ID or manifest.record.get("work_id") != IDENTITY["work_id"]
            or profile.get("contract") != "ocd-convicts-n18328-complete-xml-profile-v1"
            or policy.get("contract") != "ocd-convicts-n18328-complete-xml-policy-v1"):
        problems.append("N18328 manifest, profile, or policy identity differs")
    acquisition = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    source_path = "raw/tcp/high-range/N18328/N18328.xml"
    member = acquisition.get("member", {})
    if (profile.get("source_path") != source_path or member.get("path") != source_path
            or member.get("bytes") != len(source) or member.get("sha256") != _sha(source)
            or acquisition.get("verification", {}).get("member_count") != 1):
        problems.append("N18328 retained acquisition identity or scope differs")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("source-credit").read_bytes():
        problems.append("N18328 source credit member differs")
    if candidate.member_bytes("provenance.json") != _json(policy["provenance"]):
        problems.append("N18328 provenance member differs from policy")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(item) for item in policy["unresolved"]):
        problems.append("N18328 unresolved member differs from policy")

    source_root = _parse(source)
    source_header = source_root.find(TEI + "teiHeader")
    source_text = source_root.find(TEI + "text")
    expected_account = {
        "contract": "ocd-convicts-n18328-source-accountability-v1",
        "source_path": source_path,
        "source_bytes": len(source),
        "source_sha256": _sha(source),
        "candidate_bytes": len(content),
        "candidate_sha256": _sha(content),
        "selection": "/TEI/text",
        "source_header_tree_sha256": _sha(etree.tostring(source_header, with_tail=False)),
        "source_text_tree_sha256": _sha(etree.tostring(source_text, with_tail=False)),
        "source_text_suffix_sha256": _sha(_suffix(source)),
        "text_element_counts": _text_counts(source_text),
        "acquisition_receipt_sha256": _sha(manifest.authority_path("acquisition-receipt").read_bytes()),
        "member_inventory_sha256": _sha(manifest.authority_path("member-inventory").read_bytes()),
    }
    if candidate.member_bytes("source-accountability.json") != _json(expected_account):
        problems.append("N18328 accountability member differs from independent source observation")

    mutations = []
    for name, change in (
        ("speaker", lambda root: setattr(next(root.iter(TEI + "speaker")), "text", "Invented speaker")),
        ("verse", lambda root: setattr(next(root.iter(TEI + "l")), "text", "Invented verse")),
        ("page", lambda root: next(root.iter(TEI + "pb")).set("n", "invented")),
    ):
        try:
            altered = _parse(content)
            change(altered)
            findings = _check(source, etree.tostring(altered, encoding="utf-8"), profile, schema_path=None)
            if "candidate complete text or exact text suffix differs from source" in findings:
                mutations.append(name)
        except (StopIteration, etree.XMLSyntaxError, ValueError) as exc:
            problems.append(f"N18328 {name} mutation setup failed: {exc}")
    if mutations != ["speaker", "verse", "page"]:
        problems.append(f"N18328 mutation rejection coverage differs: {mutations}")

    result = {
        "status": "pass" if not problems else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_digest(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": str(manifest.record["package_schema"]["sha256"]),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": problems + [f"mutation rejected: {name}" for name in mutations],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
