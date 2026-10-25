"""Independent source oracle for the LIB-058 Schaff volume 6 candidate."""

from __future__ import annotations

from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, _validation_authority_bindings
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-lib058-schaff-history-vol6-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
_STRUCTURAL_START_RE = re.compile(r"^<(?:ThML|ThML\.head|ThML\.body|div[123])(?:\s|>)", re.IGNORECASE)
_STRUCTURAL_END_RE = re.compile(r"^</(?:ThML|ThML\.head|ThML\.body|div[123])>", re.IGNORECASE)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict): raise ValueError(f"{label} must be an object")
    return value


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    value = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "profile")
    if value.get("work_id") != "schaff-history-vol-6": raise ValueError("profile work scope drift")
    return value


def _source(source_manifest: SourceManifest) -> tuple[bytes, list[bytes], Mapping[str, object]]:
    members = source_manifest.record.get("source_members")
    if not isinstance(members, tuple) or len(members) != 1 or not isinstance(members[0], Mapping): raise ValueError("source member inventory drift")
    member = members[0]
    content = (source_manifest.repository_root / str(member["path"])).read_bytes()
    if len(content) != int(member["bytes"]) or _sha(content) != str(member["sha256"]): raise ValueError("source member drift")
    lines = content.splitlines(keepends=True)
    if len(lines) != int(member["lines"]) or b"".join(lines) != content or any(b"\r" in line for line in lines): raise ValueError("physical line count or byte framing drift")
    return content, lines, member


def _source_structure(content: bytes) -> dict[str, object]:
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False))
    if root.tag != "ThML": raise ValueError("source root drift")
    head, body = root.find("ThML.head"), root.find("ThML.body")
    if head is None or body is None: raise ValueError("source head/body drift")
    top = list(body.findall("div1"))
    if [item.get("id") for item in top] != ["i", "ii", "iii", "iv"]: raise ValueError("source carrier order drift")
    content_carrier, index_carrier = top[2], top[3]
    content_div2 = list(content_carrier.findall("div2"))
    return {"root": root.tag, "head": head.tag, "body": body.tag, "body_top_level": [{"id": item.get("id"), "type": item.get("type"), "source_line": int(item.sourceline or 0), "elements": sum(1 for _ in item.iter())} for item in top], "content_div2": len(content_div2), "content_sections": sum(1 for item in content_div2 if item.get("type") == "Section"), "content_chapters": sum(1 for item in content_div2 if item.get("type") == "Chapter"), "content_div3": sum(1 for _ in content_carrier.iter("div3")), "index_div2": sum(1 for _ in index_carrier.iter("div2")), "tag_counts": dict(sorted(Counter(element.tag for element in root.iter()).items()))}


def _line_kind(text: str) -> str:
    stripped = text.strip()
    if not stripped: return "blank"
    if stripped.startswith("<?xml"): return "xml-declaration"
    if stripped.startswith("<!DOCTYPE") or stripped.startswith('"-//CCEL/') or stripped.startswith('"http://www.ccel.org/'): return "doctype"
    if "<!--" in stripped or stripped.startswith("-->"): return "comment"
    if _STRUCTURAL_START_RE.match(stripped): return "structural-start"
    if _STRUCTURAL_END_RE.match(stripped): return "structural-end"
    if re.match(r"^<(?:div1|div2|div3)\b", stripped, re.IGNORECASE): return "division-start"
    if re.match(r"^</(?:div1|div2|div3)>", stripped, re.IGNORECASE): return "division-end"
    if re.match(r"^<DC(?:\.|\s|>)", stripped) or re.match(r"^</?generalInfo\b", stripped): return "metadata"
    if re.search(r"<(?:p|note|scripRef|a|li|ul|index|verse|l|unclear|br)\b", stripped, re.IGNORECASE): return "textual-carrier"
    return "xml-content"


def _records(content: bytes, lines: list[bytes]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    offset = 0
    for number, raw in enumerate(lines, 1):
        line = raw[:-1] if raw.endswith(b"\n") else raw
        text = line.decode("utf-8", errors="strict")
        line_id = f"schaff-history-vol-6-line-{number:05d}"
        result.append({"id": line_id, "line": number, "byte_start": offset, "byte_end": offset + len(raw), "record_sha256": _sha(raw), "text_sha256": _sha(line), "line_ending": "LF" if raw.endswith(b"\n") else "EOF", "kind": _line_kind(text), "disposition": "represented", "target": f"#{line_id}", "text": text})
        offset += len(raw)
    if offset != len(content): raise ValueError("source byte accounting does not close")
    return result


def _expected_accountability(content: bytes, member: Mapping[str, object], records: list[dict[str, object]], structure: Mapping[str, object]) -> dict[str, object]:
    crosswalk = [{key: value for key, value in record.items() if key != "text"} for record in records]
    return {"contract": "ocd-lib058-source-accountability-v1", "work_id": "schaff-history-vol-6", "source_sha256": str(member["sha256"]), "source_bytes": len(content), "physical_lines": len(records), "represented_lines": len(records), "omitted_lines": 0, "duplicated_lines": 0, "member_census": [{"path": member["path"], "bytes": member["bytes"], "sha256": member["sha256"], "included": True, "reason": "The current LIB-058 manifest binds this sole exact retained CCEL ThML member."}], "excluded_members": [], "source_structure": structure, "crosswalk_sha256": _sha(_canonical(crosswalk)), "crosswalk": crosswalk}


def _expected_provenance(profile: Mapping[str, object], manifest_sha256: str) -> dict[str, object]:
    return {"contract": "ocd-lib058-provenance-v1", "work_id": "schaff-history-vol-6", "title": profile["title"], "creator": profile["creator"], "contributor_statement": profile["contributor_statement"], "source_format": "CCEL ThML XML", "source_url": profile["source_url"], "source_sha256": profile["source_sha256"], "source_manifest_sha256": manifest_sha256, "candidate_status": "nonaccepted", "publication_authorized": False, "technical_validation_is_human_acceptance": False, "rights": {"retained_statement": "The retained ThML header has an empty DC.Rights element; source config records public-domain metadata, but rights clearance remains unresolved.", "worldwide": "unresolved", "publication": "not authorized"}}


def _expected_unresolved() -> list[dict[str, object]]:
    return [{"id": "schaff-history-vol-6-identity", "kind": "identity", "status": "human-review-required", "scope": "work, volume, and retained ThML envelope", "detail": "The exact retained member is bound technically; human identity and boundary acceptance remain open."}, {"id": "schaff-history-vol-6-edition", "kind": "edition-witness", "status": "human-review-required", "scope": "CCEL electronic witness and Charles Scribner's Sons source statement", "detail": "Observed source/header statements remain unaccepted edition evidence."}, {"id": "schaff-history-vol-6-readings", "kind": "substantive-reading-editorial", "status": "human-review-required", "scope": "all retained physical lines and ThML carrier classes", "detail": "No silent correction, modernization, entity expansion, or editorial acceptance was performed."}, {"id": "schaff-history-vol-6-rights", "kind": "rights", "status": "human-review-required", "scope": "CCEL header rights statement and publication", "detail": "Worldwide rights and publication authorization remain unresolved."}, {"id": "schaff-history-vol-6-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance, accepted IR, CVW review, or publication authorization."}]


def _import_closure_sha256() -> str:
    paths = (("oracle", Path(__file__).resolve(strict=True)), ("source-manifest-contract", Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)), ("tei-validator", Path(inspect.getsourcefile(compiled_schema)).resolve(strict=True)))
    digest = hashlib.sha256()
    for label, path in paths:
        digest.update(label.encode("utf-8")); digest.update(b"\n"); digest.update(path.read_bytes()); digest.update(b"\n")
    return digest.hexdigest()


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    try:
        profile = _profile(source_manifest)
        content, lines, member = _source(source_manifest)
        records = _records(content, lines)
        structure = _source_structure(content)
        if profile.get("source_structure") != structure: findings.append("profile source topology does not match independent source census")
        accountability = _strict_json(candidate.member_bytes("source-accountability.json"), "accountability")
        schema = _strict_json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "accountability schema")
        findings.extend(error.message for error in Draft202012Validator(schema).iter_errors(accountability))
        if accountability != _expected_accountability(content, member, records, structure): findings.append("source accountability does not match independent extraction")
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        if not compiled_schema().validate(etree.ElementTree(root)): findings.extend(str(error) for error in compiled_schema().error_log)
        observed = []
        for carrier in root.xpath("//tei:div[@type='source-line']/*[self::tei:ab or self::tei:head]", namespaces={"tei": TEI_NS}):
            parent = carrier.getparent(); observed.append((parent.get(f"{{{XML_NS}}}id", ""), int(carrier.get("n", "0")), carrier.get("type", ""), "".join(carrier.itertext())))
        expected = [(str(item["id"]), int(item["line"]), str(item["kind"]), str(item["text"])) for item in records]
        if observed != expected: findings.append("TEI source-line carriers do not match independent source extraction")
        if _strict_json(candidate.member_bytes("provenance.json"), "provenance") != _expected_provenance(profile, source_manifest.sha256): findings.append("candidate provenance drift")
        unresolved = [_strict_json(line + b"\n", "unresolved") for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
        if unresolved != _expected_unresolved(): findings.append("unresolved human-boundary records drift")
        if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-readme").read_bytes(): findings.append("source README attribution drift")
        if source_manifest.record["validator"]["import_closure_sha256"] != _import_closure_sha256(): findings.append("oracle import closure drift")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError, etree.XMLSyntaxError) as exc:
        findings.append(str(exc))
    bindings = _validation_authority_bindings(source_manifest)
    result: dict[str, object] = {"status": "pass" if not findings else "fail", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION, "implementation_sha256": _sha(Path(__file__).read_bytes()), "import_closure_sha256": _import_closure_sha256(), "runtime": _runtime(), "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256, **bindings, "findings": sorted(str(item) for item in findings)}
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
