"""Independent source-to-TEI checks for retained Internet Archive OCR lines."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-manifest-acquisition-retained-ocr-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(data: bytes, label: str) -> dict[str, object]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _member_lines(raw: bytes) -> list[tuple[str, int, int, bytes]]:
    lines: list[tuple[str, int, int, bytes]] = []
    offset = 0
    for chunk in raw.splitlines(keepends=True):
        if chunk.endswith(b"\r\n"):
            content, ending = chunk[:-2], b"\r\n"
        elif chunk.endswith((b"\n", b"\r")):
            content, ending = chunk[:-1], chunk[-1:]
        else:
            content, ending = chunk, b""
        text = content.decode("utf-8", errors="strict")
        lines.append((text, offset, offset + len(content), ending))
        offset += len(chunk)
    if offset != len(raw):
        raise ValueError("source-line byte traversal incomplete")
    return lines


def _source_digest(source_manifest: SourceManifest) -> str:
    primary = [item for item in source_manifest.record["authorities"] if item.get("role") == "primary-source"]
    records = sorted(({"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in primary), key=lambda row: (row["path"], row["name"]))
    return str(records[0]["sha256"]) if len(records) == 1 else _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": records}))


def _closure_digest(root: Path) -> str:
    paths = (
        Path(__file__),
        root / "ocd_kernel/__init__.py",
        root / "ocd_kernel/reconstruction/__init__.py",
        root / "ocd_kernel/reconstruction/contract.py",
        root / "ocd_kernel/tei/__init__.py",
        root / "ocd_kernel/tei/validate.py",
    )
    rows = [{"path": path.resolve(strict=True).relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in paths]
    return _sha(_canonical(rows))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    record = source_manifest.record
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    accountability_schema_bytes = source_manifest.authority_path("source-accountability-schema").read_bytes()
    profile = _strict_json(profile_bytes, "reconstruction profile")
    policy = _strict_json(policy_bytes, "validation policy")
    candidate_manifest = candidate.manifest
    if candidate_manifest.get("status") != "nonaccepted" or candidate_manifest.get("source_id") != record.get("source_id"):
        raise ValueError("candidate identity or acceptance-state mutation")

    raw_sources = []
    expected_lines: list[tuple[str, str, int, str]] = []
    for member in profile["source_members"]:
        authority = next(item for item in record["authorities"] if item.get("name") == member["authority"])
        raw = source_manifest.authority_path(str(member["authority"])).read_bytes()
        if len(raw) != authority["bytes"] or _sha(raw) != authority["sha256"]:
            raise ValueError("retained OCR source hash mismatch")
        raw_sources.append({"source_member": authority["path"], "source_sha256": authority["sha256"], "source_bytes": len(raw), "line_count": len(_member_lines(raw)), "volume": str(member["volume"]), "disposition": "included-verbatim"})
        expected_lines.extend((line[0], str(authority["path"]), line_no, str(member["volume"])) for line_no, line in enumerate(_member_lines(raw), 1))

    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False)
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    compiled_schema().assertValid(document)
    if document.tag != f"{{{TEI_NS}}}TEI":
        raise ValueError("candidate root is not TEI")
    actual_title = document.findtext(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title")
    if actual_title != profile["title"]:
        raise ValueError("candidate title does not match bound profile")
    actual = []
    for carrier in document.xpath(".//tei:body//tei:ab", namespaces={"tei": TEI_NS}):
        actual.append(("".join(carrier.itertext()), carrier.get(XML_ID)))
    if len(actual) != len(expected_lines):
        raise ValueError("candidate source-line cardinality mismatch")
    for ordinal, ((expected_text, source_path, line_no, volume), (actual_text, feature_id)) in enumerate(zip(expected_lines, actual), 1):
        wanted_id = f"{record['work_id']}-v{volume}-line-{line_no:05d}"
        if actual_text != expected_text or feature_id != wanted_id:
            raise ValueError(f"candidate text/order/id mismatch at crosswalk ordinal {ordinal} ({source_path}:{line_no})")

    accountability = _strict_json(candidate.member_bytes("source-accountability.json"), "source accountability")
    errors = list(Draft202012Validator(json.loads(accountability_schema_bytes.decode("utf-8"))).iter_errors(accountability))
    if errors:
        raise ValueError(f"source accountability schema failure: {errors[0].message}")
    if accountability.get("source_census") != raw_sources or accountability.get("represented_line_count") != len(expected_lines) or accountability.get("omitted_line_count") != 0 or accountability.get("duplicated_line_count") != 0:
        raise ValueError("source accountability census mismatch")
    crosswalk = accountability.get("crosswalk")
    if not isinstance(crosswalk, list) or len(crosswalk) != len(expected_lines):
        raise ValueError("source accountability crosswalk size mismatch")
    for row, (expected_text, source_path, line_no, volume) in zip(crosswalk, expected_lines):
        if (row.get("source_member"), row.get("line"), row.get("volume"), row.get("text"), row.get("disposition")) != (source_path, line_no, volume, expected_text, "represented-verbatim"):
            raise ValueError("source accountability crosswalk text/order/binding mismatch")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines() if line.strip()]
    expected_gap_labels = [str(item["label"]) for key in ("missing_before", "missing_after") for item in profile.get(key, [])]
    if [item.get("id") for item in unresolved if item.get("kind") == "unretained-volume"] != [f"{record['work_id']}-missing-volume-{label}" for label in expected_gap_labels]:
        raise ValueError("unretained-volume ledger mismatch")
    if b"nonaccepted" not in candidate.member_bytes("provenance.json"):
        raise ValueError("candidate provenance lost nonaccepted state")

    policy = _strict_json(policy_bytes, "validation policy")
    xsd = source_manifest.authority_path("tei-p5-xsd").read_bytes()
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_digest(root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _source_digest(source_manifest),
        "xsd_sha256": _sha(xsd),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
